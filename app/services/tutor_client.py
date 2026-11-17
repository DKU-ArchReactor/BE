"""Transport-only TUTOR client; no TUTOR implementation dependency."""
import asyncio
from uuid import uuid4
import grpc
from fastapi import HTTPException
from pydantic import ValidationError
from app.contracts.tutor_contract.v1 import tutor_pb2 as pb, tutor_pb2_grpc as rpc
from app.core.config import settings
from app.schemas.tutor_sample import TutorSampleResponse

ERROR_STATUS = {
    grpc.StatusCode.INVALID_ARGUMENT: 422,
    grpc.StatusCode.RESOURCE_EXHAUSTED: 429,
    grpc.StatusCode.DEADLINE_EXCEEDED: 504,
    grpc.StatusCode.UNAVAILABLE: 503,
}

async def sample(message: str, disconnected=None):
    if not settings.TUTOR_GRPC_TARGET:
        raise HTTPException(503, 'TUTOR service is not configured')
    request_id = str(uuid4())
    async with grpc.aio.insecure_channel('dns:///' + settings.TUTOR_GRPC_TARGET,
            options=[('grpc.max_receive_message_length', 16 * 1024),
                     ('grpc.max_send_message_length', 16 * 1024), ('grpc.enable_retries', 0)]) as channel:
        call = rpc.TutorStub(channel).Sample(pb.SampleRequest(request_id=request_id, message=message),
                                            timeout=settings.TUTOR_GRPC_TIMEOUT_SECONDS)
        async def watch_disconnect():
            while not call.done():
                if disconnected is not None and await disconnected():
                    call.cancel()
                    return
                await asyncio.sleep(0.05)
        watcher = asyncio.create_task(watch_disconnect())
        try:
            response = await call
        except grpc.aio.AioRpcError as exc:
            raise HTTPException(ERROR_STATUS.get(exc.code(), 502), f'TUTOR: {exc.code().name}') from None
        except asyncio.CancelledError:
            call.cancel()
            raise
        finally:
            watcher.cancel()
            await asyncio.gather(watcher, return_exceptions=True)
    if response.request_id != request_id or response.message != message:
        raise HTTPException(502, 'TUTOR contract mismatch')
    try:
        return TutorSampleResponse(request_id=response.request_id, schema_version=response.schema_version,
            tutor_version=response.tutor_version, message=response.message, reply=response.reply, sample=response.sample)
    except ValidationError:
        raise HTTPException(502, 'Invalid TUTOR response') from None
