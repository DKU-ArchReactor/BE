import asyncio
import json
import logging
import re
from unittest.mock import Mock
import pytest
from fastapi import HTTPException
from app.routers import assistant
from app.services.assistant.agent import AgentError, get_agent_provider
from app.services.assistant.telemetry import logger
from tests.test_assistant import chat_app, call

@pytest.fixture(autouse=True)
def capture(caplog):
    logger.addHandler(caplog.handler)
    logger.setLevel(logging.INFO)
    yield
    logger.removeHandler(caplog.handler)


def failure_records(caplog):
    return [json.loads(r.message) for r in caplog.records if r.name == logger.name and 'assistant_failure' in r.message]

@pytest.mark.parametrize('stage,code', [('classification','CLASSIFICATION_UNAVAILABLE'), ('answer','MODEL_STREAM_ERROR')])
def test_sse_error_has_same_safe_reference_as_log(chat_app, caplog, stage, code):
    app, quota = chat_app
    class Provider:
        async def stream(self, request):
            request._processing_stage = stage
            raise AgentError(code, '안전한 오류 안내')
            yield
    app.dependency_overrides[get_agent_provider] = Provider
    status, body = asyncio.run(call(app, {'messages':[{'role':'user','content':'PRIVATE_QUESTION'}]}))
    event = json.loads(next(line[6:] for line in body.splitlines() if line.startswith('data: ')))
    record = failure_records(caplog)[-1]
    assert status == 200 and event['type'] == 'error'
    assert re.fullmatch('[a-f0-9]{32}', event['request_id'])
    assert record['requestId'] == event['request_id']
    assert record['stage'] == stage and record['code'] == code
    assert event['request_id'] in event['message']
    assert 'PRIVATE_QUESTION' not in caplog.text
    quota.assert_called_once()


def test_unexpected_error_never_logs_exception_body(chat_app, caplog):
    app, _ = chat_app
    class Provider:
        async def stream(self, request):
            request._processing_stage = 'answer'
            raise RuntimeError('PRIVATE_TOKEN_AND_SOURCE')
            yield
    app.dependency_overrides[get_agent_provider] = Provider
    _, body = asyncio.run(call(app))
    assert 'PRIVATE_TOKEN_AND_SOURCE' not in body + caplog.text
    assert failure_records(caplog)[-1]['code'] == 'MODEL_UNAVAILABLE'


def test_quota_failure_keeps_status_and_does_not_invoke_provider(chat_app, caplog, monkeypatch):
    app, _ = chat_app
    quota = Mock(side_effect=HTTPException(429, {'code':'ASSISTANT_RATE_LIMIT','message':'잠시 기다려 주세요.'}))
    monkeypatch.setattr(assistant, 'reserve_request', quota)
    class Provider:
        async def stream(self, request):
            pytest.fail('must not invoke model after quota rejection')
            yield
    app.dependency_overrides[get_agent_provider] = Provider
    status, body = asyncio.run(call(app))
    assert status == 429
    assert json.loads(body)['detail']['request_id'] == failure_records(caplog)[-1]['requestId']
    assert failure_records(caplog)[-1]['stage'] == 'quota'
    quota.assert_called_once()


def test_untrusted_diagnostic_metadata_is_not_logged(caplog):
    from app.services.assistant.telemetry import log_failure
    log_failure('a'*32, 'PRIVATE_STAGE', 'PRIVATE_CODE')
    assert 'PRIVATE_' not in caplog.text
    assert failure_records(caplog)[-1]['code'] == 'MODEL_UNAVAILABLE'
