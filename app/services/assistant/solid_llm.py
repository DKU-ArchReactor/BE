"""SOLID's OpenAI-compatible Chat Completions stream, with bounded concurrency."""
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from threading import BoundedSemaphore

import httpx2
from openai import AsyncOpenAI, APIError, APIStatusError, APIConnectionError, APITimeoutError

from app.core.config import settings
from app.schemas.assistant import ChatRequest
from app.services.assistant.agent import AgentError
from app.services.assistant.prompt import SYSTEM_PROMPT
from app.services.assistant.telemetry import token_usage

# Nonblocking admission shared within a worker, also safe across event loops.
_slots = BoundedSemaphore(8)


@asynccontextmanager
async def gateway_client():
    # Per-request lifetime ensures cleanup on timeout, cancellation and shutdown.
    # Disable redirects and retries: never forward credentials to a redirect target
    # or replay a potentially billed request. No fallback to an OpenAI endpoint.
    async with AsyncOpenAI(
        base_url=settings.SOLID_LLM_BASE_URL,
        api_key=settings.SOLID_LLM_API_KEY.get_secret_value(),
        max_retries=0,
        http_client=httpx2.AsyncClient(
            timeout=httpx2.Timeout(20, connect=5, write=5, pool=5),
            follow_redirects=False,
            trust_env=False,
        ),
    ) as client:
        yield client


def public_error(error: APIError) -> AgentError:
    if isinstance(error, APITimeoutError):
        return AgentError('MODEL_TIMEOUT', 'AI 응답 시간이 초과되었습니다. 잠시 후 다시 시도해 주세요.')
    if isinstance(error, APIStatusError):
        if error.status_code in (401, 403):
            return AgentError('MODEL_ACCESS_DENIED', 'AI 서비스 인증 또는 모델 접근 권한을 확인해야 합니다. 관리자에게 문의해 주세요.')
        if error.status_code == 402:
            return AgentError('MODEL_QUOTA_EXCEEDED', 'AI 서비스 계정의 사용 한도 또는 결제 상태를 확인해야 합니다. 관리자에게 문의해 주세요.')
        if error.status_code == 429:
            return AgentError('MODEL_BUSY', 'AI 요청 제한 또는 계정 월 한도를 초과했습니다. 잠시 후 다시 시도하거나 관리자에게 문의해 주세요.')
    if isinstance(error, APIConnectionError):
        return AgentError('MODEL_UNAVAILABLE', 'AI 서비스에 연결할 수 없습니다. 잠시 후 다시 시도해 주세요.')
    return AgentError('MODEL_UNAVAILABLE', 'AI 응답을 받지 못했습니다. 잠시 후 다시 시도해 주세요.')


class SolidLLMProvider:
    def __init__(self, client_factory=None, usage_observer=None):
        self.client_factory = client_factory or gateway_client
        self.usage_observer = usage_observer or (lambda usage: None)

    async def stream(self, request: ChatRequest) -> AsyncIterator[dict]:
        if not _slots.acquire(blocking=False):
            raise AgentError('MODEL_BUSY', 'AI 요청이 많습니다. 잠시 후 다시 시도해 주세요.')
        try:
            self.usage_observer({})
            async with self.client_factory() as client:
                options = {}
                if settings.SOLID_LLM_INCLUDE_USAGE:
                    options['stream_options'] = {'include_usage': True}
                stream = await client.chat.completions.create(
                    model=settings.SOLID_LLM_MODEL,
                    messages=[{'role': 'system', 'content': SYSTEM_PROMPT},
                              *[m.model_dump() for m in request.messages]],
                    max_tokens=settings.ASSISTANT_MAX_TOKENS,
                    stream=True,
                    **options,
                )
                stop_reason = None
                usage = {}
                has_text = False
                async with stream:
                    async for chunk in stream:
                        if chunk.usage is not None:
                            usage.update(token_usage(chunk.usage))
                            self.usage_observer(usage)
                        # Role-only chunks and final usage-only chunks are valid.
                        for choice in chunk.choices or []:
                            if choice.index != 0:
                                continue
                            delta = choice.delta
                            if delta.refusal:
                                raise AgentError('MODEL_CONTENT_FILTERED', 'AI 서비스가 이 요청의 응답을 제한했습니다.')
                            if delta.tool_calls or delta.function_call:
                                raise AgentError('MODEL_STREAM_ERROR', '지원하지 않는 AI 응답 형식입니다.')
                            if delta.content:
                                if stop_reason is not None or not isinstance(delta.content, str):
                                    raise AgentError('MODEL_STREAM_ERROR', 'AI 응답 형식이 올바르지 않습니다.')
                                has_text = True
                                yield {'type': 'delta', 'text': delta.content}
                            if choice.finish_reason is not None:
                                reasons = {'stop': 'end_turn', 'length': 'max_tokens',
                                           'content_filter': 'content_filtered'}
                                if choice.finish_reason not in reasons:
                                    raise AgentError('MODEL_STREAM_ERROR', '지원하지 않는 AI 응답 종료 형식입니다.')
                                stop_reason = reasons[choice.finish_reason]
                if stop_reason is None:
                    raise AgentError('MODEL_STREAM_ERROR', 'AI 응답 연결이 완료 전에 끊겼습니다.')
                if not has_text:
                    raise AgentError('MODEL_STREAM_ERROR', 'AI 서비스가 답변 내용을 반환하지 않았습니다.')
                # Missing usage stays unknown ({}), never a fabricated zero.
                yield {'type': 'done', 'stop_reason': stop_reason, 'usage': usage}
        except APIError as error:
            raise public_error(error) from None
        except (ValueError, TypeError, AttributeError):
            raise AgentError('MODEL_STREAM_ERROR', 'AI 응답 형식이 올바르지 않습니다.') from None
        finally:
            _slots.release()
