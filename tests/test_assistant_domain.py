"""Transport/guard regressions. Semantic accuracy is measured separately against SOLID."""
import asyncio
from contextlib import asynccontextmanager
import json
import logging
from pathlib import Path
from threading import BoundedSemaphore

import httpx2
from openai import AsyncOpenAI
import pytest

from app.core.config import settings
from app.schemas.assistant import ChatRequest
from app.services.assistant.agent import AgentError, get_agent_provider
from app.services.assistant.classifier import TopicClassifier, classification_input
from app.services.assistant.guarded import GuardedProvider
from app.services.assistant.policy import Decision, DOMAIN_POLICY, FIXED_RESPONSES
from app.services.assistant.prompt import SYSTEM_PROMPT
from app.services.assistant.telemetry import Observation, logger
from app.services.assistant import solid_llm
from tests.test_assistant import call, chat_app
from tests.test_solid_llm import Body, frame

@pytest.fixture(autouse=True)
def capture_usage_logs(caplog):
    logger.addHandler(caplog.handler)
    try:
        yield
    finally:
        logger.removeHandler(caplog.handler)


CASES = json.loads((Path(__file__).parent / 'fixtures/assistant_domain_cases.json').read_text())
REQUEST = ChatRequest(messages=[{'role': 'user', 'content': '스톨이 뭐야?'}])


def completion(content='{"decision":"ALLOW","topics":["code","hazards"]}', **kwargs):
    choice = {'index': 0, 'finish_reason': 'stop',
              'message': {'role': 'assistant', 'content': content}}
    choice.update(kwargs)
    return {'id': 'classification', 'created': 0, 'model': 'test', 'object': 'chat.completion',
            'choices': [choice], 'usage': {'prompt_tokens': 20, 'completion_tokens': 5, 'total_tokens': 25}}


def gateway(result=None, handler=None):
    requests, clients = [], []
    answer_body = Body(frame('설명입니다.') + frame(finish='stop') + frame(choices=False,
        usage={'prompt_tokens': 30, 'completion_tokens': 10, 'total_tokens': 40}) + b'data: [DONE]\n\n')
    async def respond(request):
        payload = json.loads(request.content)
        requests.append(payload)
        if handler:
            return await handler(request)
        if payload['stream']:
            return httpx2.Response(200, stream=answer_body, headers={'content-type': 'text/event-stream'})
        return httpx2.Response(200, json=result or completion())

    @asynccontextmanager
    async def factory():
        async with AsyncOpenAI(base_url='https://solid.test/v1', api_key='test-placeholder', max_retries=0,
                http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(respond))) as client:
            clients.append(client)
            yield client
    return factory, requests, clients


def provider(factory):
    return GuardedProvider(TopicClassifier(factory),
        lambda **kw: solid_llm.SolidLLMProvider(factory, **kw))


def collect(subject, request=REQUEST):
    async def run():
        return [event async for event in subject.stream(request)]
    return asyncio.run(run())


@pytest.mark.parametrize('case', CASES, ids=lambda c: c['id'])
def test_decision_routes_without_answer_call_unless_allowed(case):
    factory, requests, clients = gateway(completion(json.dumps({'decision':case['expected'], 'topics':['code'] if case['expected']=='ALLOW' else []})))
    request = ChatRequest(messages=case['messages'])
    events = collect(provider(factory), request)
    assert [e['type'] for e in events] == ['delta', 'done']
    assert len(requests) == (2 if case['expected'] == 'ALLOW' else 1)
    assert requests[0]['stream'] is False
    assert DOMAIN_POLICY in requests[0]['messages'][0]['content']
    data = json.loads(requests[0]['messages'][1]['content'])
    assert data['latest_question'] == case['messages'][-1]['content']
    if case['expected'] != 'ALLOW':
        assert events[0]['text'] == FIXED_RESPONSES[case['expected']]
        assert events[1]['usage'] == {}
    else:
        assert requests[1]['messages'][0]['content'] == SYSTEM_PROMPT
        assert DOMAIN_POLICY in SYSTEM_PROMPT
    assert all(client.is_closed() for client in clients)


def test_context_is_bounded_without_truncating_latest_question():
    request = ChatRequest(messages=[{'role':'user' if i%2==0 else 'assistant','content':str(i)*2000}
                                   for i in range(8)] + [{'role':'user','content':'마지막 질문'*1000}])
    data = json.loads(classification_input(request))
    assert data['latest_question'] == request.messages[-1].content
    assert sum(len(m['content']) for m in data['recent_history']) <= 4000
    assert len(data['recent_history']) <= 6
    assert all(m['truncated'] for m in data['recent_history'])
    assert data['recent_history'] == []  # A standalone latest question needs no history.


@pytest.mark.parametrize('content', [None, '', 'ALLOW', '```json\n{"decision":"ALLOW"}\n```',
    '{"decision":"allow"}', '{"decision":"ALLOW","explanation":"x"}',
    '{"decision":"OUT_OF_SCOPE","decision":"ALLOW"}', '[{"decision":"ALLOW"}]',
    '{"decision":null}', '{"decision":true}', '{"decision":"ALLOW"} garbage', 'x'*257])
def test_invalid_output_never_calls_answer(content):
    factory, requests, _ = gateway(completion(content))
    with pytest.raises(AgentError) as error:
        collect(provider(factory))
    assert error.value.code == 'CLASSIFICATION_UNAVAILABLE'
    assert len(requests) == 1


@pytest.mark.parametrize('overrides', [
    {'finish_reason':'length'}, {'index':1}, {'finish_reason':'content_filter'},
    {'message':{'role':'assistant','content':'{"decision":"ALLOW"}','refusal':'refused'}},
    {'message':{'role':'assistant','content':'{"decision":"ALLOW"}',
                'tool_calls':[{'id':'1','type':'function','function':{'name':'x','arguments':'{}'}}]}},
])
def test_incomplete_and_unsupported_results_fail_closed(overrides):
    factory, requests, _ = gateway(completion(**overrides))
    with pytest.raises(AgentError):
        collect(provider(factory))
    assert len(requests) == 1


@pytest.mark.parametrize('status', [400,401,403,429,500])
def test_classifier_upstream_failure_no_retry_or_fallback(status):
    async def fail(request):
        return httpx2.Response(status, json={'error':{'message':'SECRET raw conversation'}})
    factory, requests, clients = gateway(handler=fail)
    with pytest.raises(AgentError) as error:
        collect(provider(factory))
    assert error.value.code == 'CLASSIFICATION_UNAVAILABLE'
    assert 'SECRET' not in str(error.value)
    assert len(requests) == 1 and clients[0].is_closed()


def test_json_schema_opt_in_keeps_validation(monkeypatch):
    monkeypatch.setattr(settings, 'SOLID_LLM_CLASSIFICATION_FORMAT', 'json_schema')
    factory, requests, _ = gateway(completion('{"decision":"WRONG"}'))
    with pytest.raises(AgentError): collect(provider(factory))
    assert requests[0]['response_format']['json_schema']['strict'] is True
    assert len(requests) == 1


def test_stage_usage_and_total_no_raw_text_logged(caplog):
    factory, _, _ = gateway()
    with caplog.at_level(logging.INFO, logger='app.services.assistant.telemetry'):
        collect(provider(factory))
    record = json.loads(next(r.message for r in caplog.records if r.name.endswith('telemetry')))
    assert record['stages']['classification']['totalTokens'] == 25
    assert record['stages']['answer']['totalTokens'] == 40
    assert record['total']['totalTokens'] == 65
    assert '스톨' not in caplog.text and 'test-placeholder' not in caplog.text


def test_unknown_usage_not_counted_as_zero(caplog):
    observation = Observation()
    observation.record('classification', {'totalTokens':25})
    observation.record('answer', {})
    with caplog.at_level(logging.INFO): observation.finish('interrupted')
    assert json.loads(caplog.records[-1].message)['total'] == {}


def test_classification_timeout_and_cancellation_close_client_and_release_slot(monkeypatch):
    monkeypatch.setattr(solid_llm, '_slots', BoundedSemaphore(1))
    monkeypatch.setattr(settings, 'ASSISTANT_CLASSIFICATION_TIMEOUT_SECONDS', 0.02)
    entered = None
    async def hang(request):
        if entered is not None:
            entered.set()
        await asyncio.Event().wait()
    factory, requests, clients = gateway(handler=hang)
    with pytest.raises(AgentError) as error: collect(provider(factory))
    assert error.value.code == 'CLASSIFICATION_UNAVAILABLE'
    assert clients[-1].is_closed()
    async def cancel():
        nonlocal entered
        entered = asyncio.Event()
        monkeypatch.setattr(settings, 'ASSISTANT_CLASSIFICATION_TIMEOUT_SECONDS', 2)
        pending = asyncio.create_task(anext(provider(factory).stream(REQUEST)))
        await asyncio.wait_for(entered.wait(), timeout=1)
        pending.cancel()
        with pytest.raises(asyncio.CancelledError): await pending
    asyncio.run(cancel())
    assert all(client.is_closed() for client in clients)
    # The timeout may occur before its HTTP transport starts on a cold runtime.
    assert 1 <= len(requests) <= 2
    assert len(clients) == 2
    assert solid_llm._slots.acquire(blocking=False)
    solid_llm._slots.release()


@pytest.mark.parametrize('decision', list(Decision))
def test_guarded_route_sse_quota_once(chat_app, decision):
    app, quota = chat_app
    factory, requests, _ = gateway(completion(json.dumps({'decision':decision, 'topics':['hazards'] if decision==Decision.ALLOW else []})))
    app.dependency_overrides[get_agent_provider] = lambda: provider(factory)
    status, body = asyncio.run(call(app))
    assert status == 200 and '"delta"' in body and '"done"' in body and '"error"' not in body
    assert len(requests) == (2 if decision == Decision.ALLOW else 1)
    quota.assert_called_once()


def test_classifier_failure_uses_existing_error_event(chat_app):
    app, quota = chat_app
    factory, requests, _ = gateway(completion('not json'))
    app.dependency_overrides[get_agent_provider] = lambda: provider(factory)
    status, body = asyncio.run(call(app))
    assert status == 200 and 'CLASSIFICATION_UNAVAILABLE' in body and '"done"' not in body
    assert '"delta"' not in body and len(requests) == 1
    quota.assert_called_once()


def test_total_deadline_spans_both_stages(chat_app, monkeypatch):
    app, quota = chat_app
    monkeypatch.setattr(settings, 'ASSISTANT_TIMEOUT_SECONDS', 0.05)
    async def classify_delay(request):
        await asyncio.sleep(0.03)
        return httpx2.Response(200,json=completion())
    factory, _, clients = gateway(handler=classify_delay)
    closed = []
    class SlowAnswer:
        def __init__(self, **kw): pass
        async def stream(self, request):
            try:
                await asyncio.sleep(0.03)
                yield {'type':'delta','text':'too late'}
            finally: closed.append(True)
    app.dependency_overrides[get_agent_provider] = lambda: GuardedProvider(TopicClassifier(factory),SlowAnswer)
    _, body = asyncio.run(call(app))
    assert 'MODEL_TIMEOUT' in body and '"done"' not in body and closed == [True]
    assert clients[0].is_closed()
    quota.assert_called_once()


def test_disconnect_during_classification_closes_upstream(chat_app):
    app, quota = chat_app
    async def hang(request): await asyncio.Event().wait()
    factory, requests, clients = gateway(handler=hang)
    app.dependency_overrides[get_agent_provider] = lambda: provider(factory)
    asyncio.run(call(app, disconnect_after=0.03))
    assert len(requests) == 1 and clients[0].is_closed()
    quota.assert_called_once()


def test_disconnect_during_guarded_answer_closes_upstream(chat_app):
    app, quota = chat_app
    factory, requests, clients = gateway()
    app.dependency_overrides[get_agent_provider] = lambda: provider(factory)
    asyncio.run(call(app, disconnect_on_delta=True))
    assert len(requests) == 2 and all(c.is_closed() for c in clients)
    quota.assert_called_once()


@pytest.mark.parametrize('choice_count', [0, 2])
def test_missing_or_multiple_choices_fail_closed(choice_count):
    result = completion()
    result['choices'] = result['choices'] * choice_count
    factory, requests, _ = gateway(result)
    with pytest.raises(AgentError): collect(provider(factory))
    assert len(requests) == 1


def test_plain_json_mode_still_requires_valid_decision(monkeypatch):
    monkeypatch.setattr(settings, 'SOLID_LLM_CLASSIFICATION_FORMAT', 'none')
    factory, requests, _ = gateway(completion('{"decision":"SMALL_TALK","topics":[]}'))
    assert collect(provider(factory))[-1]['type'] == 'done'
    assert 'response_format' not in requests[0] and len(requests) == 1
    factory, requests, _ = gateway(completion('ALLOW'))
    with pytest.raises(AgentError): collect(provider(factory))
    assert len(requests) == 1


def test_classifier_shares_worker_capacity_with_answer(monkeypatch):
    monkeypatch.setattr(solid_llm, '_slots', BoundedSemaphore(1))
    factory, requests, _ = gateway()
    solid_llm._slots.acquire()
    try:
        with pytest.raises(AgentError) as error: collect(provider(factory))
        assert error.value.code == 'MODEL_BUSY'
        assert requests == []
    finally:
        solid_llm._slots.release()
    assert collect(provider(factory))[-1]['type'] == 'done'


def test_guarded_route_rejects_quota_before_classification(chat_app):
    from fastapi import HTTPException
    app, quota = chat_app
    factory, requests, _ = gateway()
    app.dependency_overrides[get_agent_provider] = lambda: provider(factory)
    quota.side_effect = HTTPException(429, 'limited')
    assert asyncio.run(call(app))[0] == 429
    assert requests == []


def test_total_deadline_also_stops_classification(chat_app, monkeypatch):
    app, quota = chat_app
    monkeypatch.setattr(settings, 'ASSISTANT_TIMEOUT_SECONDS', 0.02)
    monkeypatch.setattr(settings, 'ASSISTANT_CLASSIFICATION_TIMEOUT_SECONDS', 1)
    async def hang(request): await asyncio.Event().wait()
    factory, requests, clients = gateway(handler=hang)
    app.dependency_overrides[get_agent_provider] = lambda: provider(factory)
    _, body = asyncio.run(call(app))
    assert 'MODEL_TIMEOUT' in body and '"done"' not in body
    assert len(requests) == 1 and clients[0].is_closed()
    quota.assert_called_once()
