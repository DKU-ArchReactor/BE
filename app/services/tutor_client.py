"""Transport-only TUTOR client; no TUTOR implementation dependency."""
import asyncio
import json
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
    grpc.StatusCode.UNIMPLEMENTED: 503,
}

MAX_REQUEST = 16 * 1024 * 1024
MAX_RESPONSE = 32 * 1024 * 1024


def _invoke(method, message):
    if not settings.TUTOR_GRPC_TARGET:
        raise HTTPException(503, 'TUTOR service is not configured')
    if message.ByteSize() > MAX_REQUEST:
        raise HTTPException(413, 'TUTOR request exceeds 16 MiB')
    try:
        with grpc.insecure_channel('dns:///' + settings.TUTOR_GRPC_TARGET, options=[
            ('grpc.max_receive_message_length', MAX_RESPONSE),
            ('grpc.max_send_message_length', MAX_REQUEST), ('grpc.enable_retries', 0),
        ]) as channel:
            response = getattr(rpc.TutorStub(channel), method)(message, timeout=settings.TUTOR_GRPC_TIMEOUT_SECONDS)
    except grpc.RpcError as error:
        raise HTTPException(ERROR_STATUS.get(error.code(), 502), f'TUTOR: {error.code().name}') from None
    if response.request_id != message.request_id or response.schema_version != '1.0' or not response.tutor_version:
        raise HTTPException(502, 'TUTOR contract mismatch')
    try:
        def invalid_constant(value):
            raise ValueError('Non-finite JSON')
        bundle = json.loads(response.result_json, parse_constant=invalid_constant)
        if not isinstance(bundle, dict) or bundle.get('schema_version') != '1.0':
            raise ValueError('Invalid schema')
        return bundle
    except (ValueError, TypeError, RecursionError):
        raise HTTPException(502, 'Invalid TUTOR response') from None


def explain_items(items):
    from app.schemas.tutor import ExplainResponse
    messages = [pb.ExplainItem(kind=item.kind, text=item.text, line=item.line,
        **({'pc': item.pc} if item.pc is not None else {})) for item in items]
    bundle = _invoke('Explain', pb.ExplainRequest(request_id=str(uuid4()), items=messages))
    try:
        result = ExplainResponse.model_validate(bundle)
        if len(result.items) != len(items) or any(a.kind != b.kind for a, b in zip(result.items, items)):
            raise ValueError('Item mismatch')
        return result
    except (ValidationError, ValueError):
        raise HTTPException(502, 'Invalid TUTOR explanations') from None


def compiled_source(source, lang, assembly):
    request = pb.CompileRequest(request_id=str(uuid4()), source=source, lang=lang.lower(),
        **({'assembly': assembly} if assembly is not None else {}))
    bundle = _invoke('Compile', request)
    if not isinstance(bundle.get('c_lines'), list) or not isinstance(bundle.get('asm_instructions'), list):
        raise HTTPException(502, 'Invalid TUTOR compilation explanations')
    return bundle


def analyze_result(result, *, source='', source_file=None, elf_bytes=None):
    try:
        encoded = json.dumps(result, ensure_ascii=False, allow_nan=False, separators=(',', ':'))
    except (ValueError, TypeError, RecursionError):
        raise HTTPException(422, 'Invalid simulation JSON') from None
    request = pb.AnalyzeRequest(request_id=str(uuid4()), result_json=encoded, source=source,
        source_file=source_file or '', elf=elf_bytes or b'')
    bundle = _invoke('Analyze', request)
    if (not isinstance(bundle.get('asm_instructions'), list)
            or not isinstance(bundle.get('cycle_explanations'), list)
            or not isinstance(bundle.get('execution_steps'), list)):
        raise HTTPException(502, 'Invalid TUTOR analysis')
    return bundle

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
