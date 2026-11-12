"""Exercise the real SDK parser against in-memory HTTP, never a live model."""
import asyncio
from contextlib import asynccontextmanager
import json
from threading import BoundedSemaphore

import httpx2
from openai import AsyncOpenAI
from pydantic import SecretStr, ValidationError
import pytest

from app.core.config import Settings, settings
from app.routers import assistant
from app.schemas.assistant import ChatRequest
from app.services.assistant import solid_llm
from app.services.assistant.agent import AgentError, get_agent_provider

REQUEST = ChatRequest(messages=[{'role':'user', 'content':'스톨이 뭐야?'}])


def frame(content=None, finish=None, *, usage=None, choices=True):
    value = {'id':'test', 'created':0, 'model':'local/qwen3-coder-next', 'object':'chat.completion.chunk',
             'choices':[{'index':0,'delta':{'content':content},'finish_reason':finish}] if choices else []}
    if usage is not None:
        value['usage'] = usage
    return ('data: '+json.dumps(value, ensure_ascii=False)+'\n\n').encode()


class Body(httpx2.AsyncByteStream):
    def __init__(self, payload, *, hang=False):
        self.payload, self.hang, self.closed = payload, hang, False

    async def __aiter__(self):
        # Split frames and multi-byte Korean characters across transport reads.
        for i in range(0, len(self.payload), 7):
            yield self.payload[i:i+7]
        if self.hang:
            await asyncio.Event().wait()

    async def aclose(self):
        self.closed = True


def provider_for(body, *, status=200, handler=None):
    requests, clients = [], []

    async def respond(request):
        requests.append(request)
        if handler:
            return await handler(request)
        return httpx2.Response(status, stream=body, headers={'content-type':'text/event-stream'})

    @asynccontextmanager
    async def factory():
        async with AsyncOpenAI(base_url='https://solid.test/llm/v1', api_key='test-only-placeholder',
                max_retries=0, http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(respond))) as client:
            clients.append(client)
            yield client

    return solid_llm.SolidLLMProvider(factory), requests, clients


def collect(provider):
    async def run():
        return [event async for event in provider.stream(REQUEST)]
    return asyncio.run(run())


def test_sdk_stream_mapping_korean_usage_and_request_contract(monkeypatch):
    monkeypatch.setattr(settings, 'SOLID_LLM_INCLUDE_USAGE', True)
    body = Body(frame() + frame('스톨은 ') + frame('대기입니다.') + frame(finish='stop')
                + frame(choices=False, usage={'prompt_tokens':10,'completion_tokens':5,'total_tokens':15})
                + b'data: [DONE]\n\n')
    provider, requests, clients = provider_for(body)
    events = collect(provider)
    assert ''.join(e['text'] for e in events if e['type']=='delta') == '스톨은 대기입니다.'
    assert events[-1] == {'type':'done','stop_reason':'end_turn',
                          'usage':{'inputTokens':10,'outputTokens':5,'totalTokens':15}}
    payload = json.loads(requests[0].content)
    assert str(requests[0].url) == 'https://solid.test/llm/v1/chat/completions'
    assert payload['model'] == 'local/qwen3-coder-next'
    assert payload['max_tokens'] == 2048 and payload['stream'] is True
    assert payload['stream_options'] == {'include_usage': True}
    assert payload['messages'][0]['role'] == 'system'
    assert '자동으로 조회할 수 없습니다' in payload['messages'][0]['content']
    assert payload['messages'][1] == REQUEST.messages[0].model_dump()
    assert 'tools' not in payload
    assert body.closed and clients[0].is_closed()


def test_usage_absent_stays_unknown_and_length_maps_to_max_tokens(monkeypatch):
    monkeypatch.setattr(settings, 'SOLID_LLM_INCLUDE_USAGE', False)
    provider, requests, _ = provider_for(Body(frame('답변', 'length')+b'data: [DONE]\n\n'))
    assert collect(provider)[-1] == {'type':'done','stop_reason':'max_tokens','usage':{}}
    assert 'stream_options' not in json.loads(requests[0].content)


@pytest.mark.parametrize('payload', [
    b'data: [DONE]\n\n', frame('unfinished'), frame(finish='stop'),
    b'data: {not json}\n\n', b'data: {"error":{"message":"private upstream detail"}}\n\n',
    frame('partial', 'tool_calls'),
])
def test_incomplete_malformed_empty_and_tool_streams_are_not_success(payload):
    body = Body(payload)
    provider, _, clients = provider_for(body)
    with pytest.raises(AgentError) as error:
        collect(provider)
    assert 'private upstream' not in str(error.value)
    assert body.closed and clients[0].is_closed()


@pytest.mark.parametrize('status,code', [(401,'MODEL_ACCESS_DENIED'),(403,'MODEL_ACCESS_DENIED'),
    (402,'MODEL_QUOTA_EXCEEDED'),(429,'MODEL_BUSY'),(500,'MODEL_UNAVAILABLE')])
def test_http_errors_are_sanitized_and_not_retried(status, code):
    body = Body(b'{"error":{"message":"private-key-and-user-prompt"}}')
    provider, requests, clients = provider_for(body, status=status)
    with pytest.raises(AgentError) as error:
        collect(provider)
    assert error.value.code == code and 'private' not in str(error.value)
    assert len(requests) == 1 and clients[0].is_closed()


@pytest.mark.parametrize('error_type,code', [(httpx2.ReadTimeout,'MODEL_TIMEOUT'),
                                           (httpx2.ConnectError,'MODEL_UNAVAILABLE')])
def test_network_errors_are_sanitized(error_type, code):
    async def fail(request):
        raise error_type('private detail', request=request)
    provider, requests, clients = provider_for(None, handler=fail)
    with pytest.raises(AgentError) as error:
        collect(provider)
    assert error.value.code == code
    assert len(requests) == 1 and clients[0].is_closed()


def test_cancellation_closes_upstream_and_releases_capacity(monkeypatch):
    monkeypatch.setattr(solid_llm, '_slots', BoundedSemaphore(1))
    body = Body(frame('첫 답변'), hang=True)
    provider, _, clients = provider_for(body)

    async def run():
        stream = provider.stream(REQUEST)
        assert (await anext(stream))['type'] == 'delta'
        pending = asyncio.create_task(anext(stream))
        await asyncio.sleep(0.01)
        pending.cancel()
        await asyncio.gather(pending, return_exceptions=True)
        await stream.aclose()
        assert solid_llm._slots.acquire(blocking=False)
        solid_llm._slots.release()
    asyncio.run(run())
    assert body.closed and clients[0].is_closed()


def test_worker_admission_is_bounded_and_recovers(monkeypatch):
    monkeypatch.setattr(solid_llm, '_slots', BoundedSemaphore(1))
    provider, requests, _ = provider_for(Body(frame('first'), hang=True))

    async def run():
        stream = provider.stream(REQUEST)
        await anext(stream)
        try:
            with pytest.raises(AgentError, match='요청이 많습니다'):
                await anext(provider.stream(REQUEST))
            assert len(requests) == 1
        finally:
            await stream.aclose()
        assert solid_llm._slots.acquire(blocking=False)
        solid_llm._slots.release()
    asyncio.run(run())


def test_missing_configuration_keeps_status_and_chat_disabled(monkeypatch):
    monkeypatch.setattr(settings, 'ASSISTANT_ENABLED', True)
    monkeypatch.setattr(settings, 'SOLID_LLM_API_KEY', SecretStr('  '))
    assert get_agent_provider() is None
    assert assistant.status() == {'enabled':False,'code':'AGENT_NOT_CONFIGURED'}
    monkeypatch.setattr(settings, 'SOLID_LLM_API_KEY', SecretStr('test-only-placeholder'))
    from app.services.assistant.guarded import GuardedProvider
    assert isinstance(get_agent_provider(), GuardedProvider)
    assert assistant.status()['enabled'] is True
    monkeypatch.setattr(settings, 'ASSISTANT_ENABLED', False)
    assert get_agent_provider() is None


@pytest.mark.parametrize('url', ['http://solid.test/v1','https://user:pass@solid.test/v1',
                                 'https://solid.test/v1?token=x','https://solid.test/v1#x'])
def test_gateway_url_requires_https_without_embedded_secrets(url):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, SOLID_LLM_BASE_URL=url)
