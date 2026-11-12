import asyncio
from contextlib import aclosing
import json
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.schemas.assistant import ChatRequest
from app.services.assistant.agent import AgentError, AgentProvider, assistant_ready, get_agent_provider
from app.services.assistant.usage import reserve_request
from app.services.assistant.context import resolve_context
from app.services.assistant.telemetry import log_failure

router = APIRouter(prefix='/api/v1/assistant', tags=['assistant'])


@router.get('/status', summary='AI 연결 준비 상태')
def status():
    enabled = assistant_ready()
    return {'enabled': enabled, 'code': 'ENABLED' if enabled else 'AGENT_NOT_CONFIGURED',
            'editor_source_supported': True}


@router.get('/transport-check', summary='모델 호출 없는 SSE 통신 점검',
            description='고정된 진단 이벤트 2개만 전송합니다. 사용자 입력·DB·외부 AI에 접근하지 않습니다.',
            responses={200: {'content': {'text/event-stream': {}}}})
def transport_check():
    async def events():
        yield _sse({'type': 'diagnostic', 'sequence': 1, 'model_invoked': False})
        await asyncio.sleep(0.5)
        yield _sse({'type': 'done', 'sequence': 2, 'model_invoked': False})
    return StreamingResponse(events(), media_type='text/event-stream', headers={
        'Cache-Control': 'no-cache, no-store', 'X-Accel-Buffering': 'no',
    })


def _sse(event: dict) -> str:
    return 'data: ' + json.dumps(event, ensure_ascii=False) + '\n\n'


@router.post('/chat', summary='AI 어시스턴트 스트리밍 대화',
             responses={200: {'content': {'text/event-stream': {}}},
                        429: {'description': 'Request allowance exceeded'},
                        503: {'description': 'Assistant disabled'}})
def chat(body: ChatRequest, current: User = Depends(get_current_user),
         db: Session = Depends(get_db), provider: AgentProvider | None = Depends(get_agent_provider)):
    body._request_id = uuid4().hex
    request_id = body._request_id

    def failure(code, message):
        code = log_failure(request_id, body._processing_stage, code)
        return {'type': 'error', 'code': code, 'request_id': request_id,
                'message': f'{message} (문의 코드: {request_id})'}

    try:
        if provider is None:
            raise HTTPException(503, {'code': 'AGENT_NOT_CONFIGURED', 'message': 'AI 연결이 아직 활성화되지 않았습니다.'})
        if body.context is not None:
            body._processing_stage = 'context'
            body._execution_context = resolve_context(db, body.context, current.user_id)
        body._processing_stage = 'quota'
        reserve_request(db, current.user_id)
    except HTTPException as error:
        detail = error.detail if isinstance(error.detail, dict) else {}
        # These messages are controlled by our own admission/context checks.
        event = failure(detail.get('code'), detail.get('message', 'AI 요청을 처리하지 못했습니다.'))
        raise HTTPException(error.status_code, {key: value for key, value in event.items() if key != 'type'},
                            headers={**(error.headers or {}), 'X-Assistant-Request-Id': request_id}) from None
    except Exception:
        event = failure('MODEL_UNAVAILABLE', 'AI 요청을 준비하지 못했습니다. 잠시 후 다시 시도해 주세요.')
        raise HTTPException(500, {key: value for key, value in event.items() if key != 'type'},
                            headers={'X-Assistant-Request-Id': request_id}) from None

    async def events():
        yield ': connected\n\n'
        pending = None
        try:
            async with asyncio.timeout(settings.ASSISTANT_TIMEOUT_SECONDS):
                async with aclosing(provider.stream(body)) as stream:
                    try:
                        while True:
                            pending = asyncio.create_task(anext(stream))
                            while not pending.done():
                                done, _ = await asyncio.wait({pending}, timeout=10)
                                if not done:
                                    yield ': keepalive\n\n'
                            try:
                                event = pending.result()
                            except StopAsyncIteration:
                                break
                            yield _sse(event)
                            if event['type'] == 'done':
                                break
                    finally:
                        if pending is not None:
                            pending.cancel()
                            await asyncio.gather(pending, return_exceptions=True)
        except TimeoutError:
            yield _sse(failure('MODEL_TIMEOUT', '응답 시간이 초과되었습니다. 질문을 줄여 다시 시도해 주세요.'))
        except AgentError as error:
            yield _sse(failure(error.code, error.message))
        except asyncio.CancelledError:
            log_failure(request_id, body._processing_stage, 'CLIENT_DISCONNECTED')
            raise
        except Exception:
            yield _sse(failure('MODEL_UNAVAILABLE', 'AI 응답 처리에 실패했습니다.'))

    return StreamingResponse(events(), media_type='text/event-stream', headers={
        'Cache-Control': 'no-cache, no-store', 'X-Accel-Buffering': 'no',
        'X-Assistant-Request-Id': request_id,
    })
