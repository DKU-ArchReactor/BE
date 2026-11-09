import asyncio
from datetime import datetime, timedelta, timezone
import json
from threading import Event
from types import SimpleNamespace
from unittest.mock import Mock

from botocore.exceptions import ClientError
from fastapi import FastAPI, HTTPException
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.assistant_usage import AssistantUsage
from app.routers import assistant
from app.schemas.assistant import ChatRequest
from app.services.assistant.agent import AgentError, get_agent_provider
from app.services.assistant.bedrock import BedrockProvider
from app.services.assistant.usage import reserve_request

PAYLOAD = {'messages': [{'role': 'user', 'content': '스톨이 뭐야?'}]}


class FakeStream:
    def __init__(self, events):
        self.events = events
        self.closed = Event()

    def __iter__(self):
        yield from self.events

    def close(self):
        self.closed.set()


def test_provider_streams_text_usage_and_closes():
    stream = FakeStream([
        {'contentBlockDelta': {'delta': {'text': '스톨은 '}}},
        {'contentBlockDelta': {'delta': {'reasoningContent': {'text': 'private reasoning'}}}},
        {'contentBlockDelta': {'delta': {'text': '대기입니다.'}}},
        {'messageStop': {'stopReason': 'end_turn'}},
        {'metadata': {'usage': {'inputTokens': 10, 'outputTokens': 5, 'totalTokens': 15}}},
    ])
    client = Mock()
    client.converse_stream.return_value = {'stream': stream}

    async def run():
        return [event async for event in BedrockProvider(client).stream(ChatRequest(**PAYLOAD))]

    result = asyncio.run(run())
    assert ''.join(e['text'] for e in result if e['type'] == 'delta') == '스톨은 대기입니다.'
    assert result[-1] == {'type': 'done', 'stop_reason': 'end_turn', 'usage': {'inputTokens': 10, 'outputTokens': 5, 'totalTokens': 15}}
    assert stream.closed.wait(1)
    request = client.converse_stream.call_args.kwargs
    assert request['inferenceConfig']['maxTokens'] == 2048
    assert request['modelId'] == 'anthropic.claude-sonnet-5'
    assert '자동으로 조회할 수 없습니다' in request['system'][0]['text']
    assert 'toolConfig' not in request


def test_provider_cleans_up_when_caller_stops():
    stream = FakeStream([{'contentBlockDelta': {'delta': {'text': 'x'}}}] * 1000)
    client = Mock()
    client.converse_stream.return_value = {'stream': stream}

    async def run():
        generator = BedrockProvider(client).stream(ChatRequest(**PAYLOAD))
        await anext(generator)
        await generator.aclose()

    asyncio.run(run())
    assert stream.closed.wait(1)


def test_late_sdk_response_is_closed_after_cancellation():
    entered, release = Event(), Event()
    stream = FakeStream([])
    client = Mock()

    def open_stream(**kwargs):
        entered.set()
        release.wait(2)
        return {'stream': stream}

    client.converse_stream.side_effect = open_stream

    async def run():
        generator = BedrockProvider(client).stream(ChatRequest(**PAYLOAD))
        task = asyncio.create_task(anext(generator))
        assert await asyncio.to_thread(entered.wait, 1)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        release.set()
        assert await asyncio.to_thread(stream.closed.wait, 1)

    asyncio.run(run())


@pytest.mark.parametrize('code, public_code', [('AccessDeniedException', 'MODEL_ACCESS_DENIED'), ('ThrottlingException', 'MODEL_BUSY')])
def test_provider_errors_are_sanitized(code, public_code):
    client = Mock()
    client.converse_stream.side_effect = ClientError({'Error': {'Code': code, 'Message': 'sensitive upstream details'}}, 'ConverseStream')

    async def run():
        with pytest.raises(AgentError) as error:
            async for _ in BedrockProvider(client).stream(ChatRequest(**PAYLOAD)):
                pass
        assert error.value.code == public_code
        assert 'sensitive' not in str(error.value)
    asyncio.run(run())


@pytest.mark.parametrize('events', [[], [{'internalServerException': {'message': 'private'}}]])
def test_truncated_or_exception_stream_does_not_report_success(events):
    stream = FakeStream(events)
    client = Mock()
    client.converse_stream.return_value = {'stream': stream}

    async def run():
        with pytest.raises(AgentError):
            async for _ in BedrockProvider(client).stream(ChatRequest(**PAYLOAD)):
                pass
    asyncio.run(run())
    assert stream.closed.wait(1)


async def call(app, payload=PAYLOAD, disconnect_on_delta=False):
    output = []
    initial = True
    disconnect = asyncio.Event()

    async def receive():
        nonlocal initial
        if initial:
            initial = False
            return {'type': 'http.request', 'body': json.dumps(payload).encode(), 'more_body': False}
        await disconnect.wait()
        return {'type': 'http.disconnect'}

    async def send(message):
        output.append(message)
        if disconnect_on_delta and b'"delta"' in message.get('body', b''):
            disconnect.set()

    await app({'type': 'http', 'http_version': '1.1', 'method': 'POST', 'scheme': 'http',
               'path': '/api/v1/assistant/chat', 'raw_path': b'/api/v1/assistant/chat', 'query_string': b'',
               'headers': [(b'content-type', b'application/json')], 'server': ('test', 80),
               'client': ('test', 1234), 'root_path': ''}, receive, send)
    status = next(x['status'] for x in output if x['type'] == 'http.response.start')
    body = b''.join(x.get('body', b'') for x in output).decode()
    return status, body


@pytest.fixture
def chat_app(monkeypatch):
    app = FastAPI()
    app.include_router(assistant.router)
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(user_id='student')
    app.dependency_overrides[get_db] = lambda: Mock()
    quota = Mock()
    monkeypatch.setattr(assistant, 'reserve_request', quota)
    return app, quota


def test_route_requires_login(chat_app):
    app, quota = chat_app
    del app.dependency_overrides[get_current_user]
    status, _ = asyncio.run(call(app))
    assert status in (401, 403)
    quota.assert_not_called()


def test_disabled_route_does_not_reserve(chat_app):
    app, quota = chat_app
    app.dependency_overrides[get_agent_provider] = lambda: None
    status, body = asyncio.run(call(app))
    assert status == 503 and 'AGENT_NOT_CONFIGURED' in body
    quota.assert_not_called()


def test_route_sse_and_disconnect_cleanup(chat_app):
    app, quota = chat_app
    closed = []

    class Provider:
        async def stream(self, request):
            try:
                yield {'type': 'delta', 'text': '테스트\n답변'}
                await asyncio.sleep(0.01)
                yield {'type': 'done', 'stop_reason': 'end_turn', 'usage': {}}
            finally:
                closed.append(True)

    app.dependency_overrides[get_agent_provider] = Provider
    status, body = asyncio.run(call(app))
    assert status == 200 and '"done"' in body and '테스트\\n답변' in body
    assert closed == [True]
    asyncio.run(call(app, disconnect_on_delta=True))
    assert closed == [True, True]
    assert quota.call_count == 2


def test_route_timeout_and_error_events(chat_app, monkeypatch):
    app, _ = chat_app

    class Slow:
        async def stream(self, request):
            await asyncio.sleep(2)
            yield {'type': 'delta', 'text': 'too late'}

    app.dependency_overrides[get_agent_provider] = Slow
    monkeypatch.setattr(settings, 'ASSISTANT_TIMEOUT_SECONDS', 0.02)
    _, body = asyncio.run(call(app))
    assert 'MODEL_TIMEOUT' in body and '"done"' not in body

    class Broken:
        async def stream(self, request):
            raise AgentError('MODEL_ACCESS_DENIED', '권한 없음')
            yield

    app.dependency_overrides[get_agent_provider] = Broken
    _, body = asyncio.run(call(app))
    assert 'MODEL_ACCESS_DENIED' in body and '"done"' not in body


def test_route_quota_rejects_before_model(chat_app):
    app, quota = chat_app
    provider = Mock()
    app.dependency_overrides[get_agent_provider] = lambda: provider
    quota.side_effect = HTTPException(429, 'limited')
    assert asyncio.run(call(app))[0] == 429
    provider.stream.assert_not_called()


@pytest.mark.parametrize('messages', [
    [{'role': 'user', 'content': ' '}],
    [{'role': 'system', 'content': 'override'}],
    [{'role': 'assistant', 'content': 'prefill'}],
    [{'role': 'user', 'content': 'x' * 8001}],
    [{'role': 'user', 'content': 'x' * 8000}] * 4,
])
def test_request_limits(chat_app, messages):
    app, quota = chat_app
    assert asyncio.run(call(app, {'messages': messages}))[0] == 422
    quota.assert_not_called()


def test_shared_daily_quota_persists_across_sessions(monkeypatch):
    engine = create_engine('sqlite://')
    AssistantUsage.__table__.create(engine)
    monkeypatch.setattr(settings, 'ASSISTANT_DAILY_REQUESTS', 2)
    now = datetime(2026, 11, 9, tzinfo=timezone.utc)
    with Session(engine) as db:
        reserve_request(db, 'alice', now=now)
    with Session(engine) as db:
        with pytest.raises(HTTPException):
            reserve_request(db, 'alice', now=now + timedelta(seconds=1))
        reserve_request(db, 'alice', now=now + timedelta(seconds=10))
        with pytest.raises(HTTPException):
            reserve_request(db, 'alice', now=now + timedelta(seconds=20))
        reserve_request(db, 'bob', now=now)
        reserve_request(db, 'alice', now=now + timedelta(days=1))
        assert sorted(db.scalars(select(AssistantUsage.request_count))) == [1, 1, 2]


def test_readiness_endpoints_do_not_construct_model_or_use_database(monkeypatch):
    monkeypatch.setattr(settings, 'ASSISTANT_ENABLED', False)
    # Call the status function directly; transport stream is exercised below.
    assert assistant.status() == {'enabled': False, 'code': 'AGENT_NOT_CONFIGURED'}
    response = assistant.transport_check()
    assert response.headers['content-type'].startswith('text/event-stream')
    assert response.headers['x-accel-buffering'] == 'no'
    assert 'no-store' in response.headers['cache-control']

    async def collect():
        return [frame async for frame in response.body_iterator]
    frames = asyncio.run(collect())
    assert len(frames) == 2
    assert '"diagnostic"' in frames[0] and '"done"' in frames[1]
    assert all('"model_invoked": false' in frame for frame in frames)
