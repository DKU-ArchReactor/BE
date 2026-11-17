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
from app.services.tutor.agent import AgentError, AgentProvider, get_agent_provider
from app.services.tutor.usage import reserve_request

router = APIRouter(prefix='/api/v1/assistant', tags=['assistant'])


def _sse(event: dict) -> str:
    return 'data: ' + json.dumps(event, ensure_ascii=False) + '\n\n'


@router.post('/chat', summary='AI 어시스턴트 스트리밍 대화',
             responses={200: {'content': {'text/event-stream': {}}},
                        429: {'description': 'Request allowance exceeded'},
                        503: {'description': 'Assistant disabled'}})
async def chat(body: ChatRequest, current: User = Depends(get_current_user),
         db: Session = Depends(get_db), provider: AgentProvider | None = Depends(get_agent_provider)):
    if provider is None:
        raise HTTPException(503, {'code': 'AGENT_NOT_CONFIGURED', 'message': 'AI 연결이 아직 활성화되지 않았습니다.'})
    reserve_request(db, current.user_id)
    if body.execution is not None:
        from app.services.tutor.context import resolve_context
        body = await resolve_context(body, db, current)

    async def events():
        yield ': connected\n\n'
        if body._context_metadata is not None:
            yield _sse({'type': 'context', **body._context_metadata})
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
