import asyncio
import httpx
import pytest
from app.schemas.assistant import ChatRequest
from app.services.tutor.solid import SolidProvider, HttpxTransport
from app.services.tutor.agent import AgentError


def run_transport(body, status=200, content_type='text/event-stream'):
    seen = []
    def handler(request):
        seen.append(request)
        return httpx.Response(status, content=body, headers={'content-type': content_type})
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return [event async for event in SolidProvider(HttpxTransport(client)).stream(
                ChatRequest(messages=[{'role': 'user', 'content': '스톨 설명'}]))]
    return asyncio.run(run()), seen


def test_real_http_adapter_unicode_sse_usage():
    events, seen = run_transport('data: {"choices":[{"index":0,"delta":{"content":"설명"},"finish_reason":null}]}\n\n'
        'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\n'
        'data: {"choices":[],"usage":{"prompt_tokens":2,"completion_tokens":3,"total_tokens":5}}\n\n'
        'data: [DONE]\n\n')
    assert events[0] == {'type':'delta', 'text':'설명'}
    assert events[-1]['usage']['totalTokens'] == 5
    assert str(seen[0].url) == 'https://dku-chat.kloud.zone/llm/v1/chat/completions'


@pytest.mark.parametrize('status,code', [(401,'MODEL_ACCESS_DENIED'),(403,'MODEL_ACCESS_DENIED'),
    (429,'MODEL_BUSY'),(500,'MODEL_UNAVAILABLE'),(302,'MODEL_UNAVAILABLE')])
def test_error_status_masking(status, code):
    with pytest.raises(AgentError) as exc:
        run_transport('private upstream detail', status)
    assert exc.value.code == code
    assert 'private' not in exc.value.message


@pytest.mark.parametrize('body', ['data: [DONE]\n\n', 'data: invalid\n\n',
    'data: {"choices":[{"delta":{"content":"partial"}}]}\n\n', 'x'*70000])
def test_invalid_truncated_and_oversized_stream(body):
    with pytest.raises(AgentError):
        run_transport(body)
