import asyncio
from contextlib import aclosing
import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.schemas.assistant import ChatRequest
from app.services.assistant.agent import AgentError, AgentProvider, get_agent_provider
from app.services.assistant.usage import reserve_request

router = APIRouter(prefix='/api/v1/assistant', tags=['assistant'])


@router.get('/status', summary='AI 연결 준비 상태')
def status():
    return {'enabled': settings.ASSISTANT_ENABLED,
            'code': 'ENABLED' if settings.ASSISTANT_ENABLED else 'AGENT_NOT_CONFIGURED'}


@router.get('/transport-check', summary='모델 호출 없는 SSE 통신 점검',
            description='고정된 진단 이벤트 2개만 전송합니다. 사용자 입력·DB·Bedrock에 접근하지 않습니다.',
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
    if provider is None:
        raise HTTPException(503, {'code': 'AGENT_NOT_CONFIGURED', 'message': 'AI 연결이 아직 활성화되지 않았습니다.'})
    reserve_request(db, current.user_id)

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
            yield _sse({'type': 'error', 'code': 'MODEL_TIMEOUT', 'message': '응답 시간이 초과되었습니다. 질문을 줄여 다시 시도해 주세요.'})
        except AgentError as error:
            yield _sse({'type': 'error', 'code': error.code, 'message': error.message})
        except Exception:
            yield _sse({'type': 'error', 'code': 'MODEL_UNAVAILABLE', 'message': 'AI 응답 처리에 실패했습니다.'})

    return StreamingResponse(events(), media_type='text/event-stream', headers={
        'Cache-Control': 'no-cache, no-store', 'X-Accel-Buffering': 'no',
    })
