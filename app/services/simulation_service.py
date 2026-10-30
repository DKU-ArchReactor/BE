"""Transport-only CORE client; simulator implementations are never imported."""
import asyncio
import json
import math
import time
import uuid

import grpc
from fastapi import HTTPException
from app.contracts.archreactor_contract.v1 import simulation_pb2 as pb, simulation_pb2_grpc as rpc
from app.core.config import settings

MAX_ELF = 256 * 1024
MAX_RESULT = 8 * 1024 * 1024
ERROR_STATUS = {
    grpc.StatusCode.INVALID_ARGUMENT: 422,
    grpc.StatusCode.RESOURCE_EXHAUSTED: 429,
    grpc.StatusCode.DEADLINE_EXCEEDED: 504,
    grpc.StatusCode.UNAVAILABLE: 503,
    grpc.StatusCode.CANCELLED: 499,
}


async def run_simulation(elf: bytes, mode: str, max_cycles: int, disconnected=None, timings=None):
    if not settings.CORE_GRPC_TARGET:
        raise HTTPException(503, 'CORE service is not configured')
    if len(elf) > MAX_ELF:
        raise HTTPException(413, 'ELF exceeds 256 KiB')
    request_id = str(uuid.uuid4())
    rpc_start = time.perf_counter()
    # New channel per request observes replacement task addresses without BE deployment.
    async with grpc.aio.insecure_channel('dns:///' + settings.CORE_GRPC_TARGET,
            options=[('grpc.max_receive_message_length', MAX_RESULT),
                     ('grpc.max_send_message_length', MAX_ELF + 1024),
                     ('grpc.enable_retries', 0)]) as channel:
        call = rpc.SimulatorStub(channel).RunSimulation(pb.RunSimulationRequest(
            request_id=request_id, elf=elf, mode=pb.SINGLE if mode == 'single' else pb.PIPELINE,
            max_cycles=max_cycles), timeout=settings.CORE_GRPC_TIMEOUT_SECONDS)
        async def watch_disconnect():
            while not call.done():
                if disconnected is not None and await disconnected():
                    call.cancel()
                    return
                await asyncio.sleep(0.05)
        watcher = asyncio.create_task(watch_disconnect())
        try:
            response = await call
            if timings is not None:
                timings['core-rpc'] = (time.perf_counter() - rpc_start) * 1000
                for key, value in await call.trailing_metadata():
                    if key in {'core-load', 'core-sim', 'core-cpu', 'core-json', 'core-worker'}:
                        try:
                            duration = float(value)
                        except (ValueError, TypeError):
                            continue
                        if math.isfinite(duration) and 0 <= duration <= settings.CORE_GRPC_TIMEOUT_SECONDS * 1000:
                            timings[key] = duration
        except grpc.aio.AioRpcError as exc:
            raise HTTPException(ERROR_STATUS.get(exc.code(), 502), f'CORE: {exc.code().name}') from None
        except asyncio.CancelledError:
            call.cancel()
            raise
        finally:
            watcher.cancel()
            await asyncio.gather(watcher, return_exceptions=True)
    if response.request_id != request_id or response.result_schema_version.split('.')[0] != settings.CORE_RESULT_SCHEMA_MAJOR:
        raise HTTPException(502, 'CORE contract mismatch')
    try:
        decode_start = time.perf_counter()
        result = json.loads(response.result_json)
        if timings is not None:
            timings['be-json-decode'] = (time.perf_counter() - decode_start) * 1000
        if not isinstance(result, dict) or result.get('schema_version') != response.result_schema_version:
            raise ValueError()
        if not isinstance(result['summary'], dict) or not isinstance(result['history'], list) or not isinstance(result['console_output'], str):
            raise ValueError()
        status = pb.ExecutionStatus.Name(response.status)
    except (ValueError, KeyError, TypeError):
        raise HTTPException(502, 'Invalid CORE response') from None
    return {'request_id': request_id, 'execution_id': response.execution_id,
            'execution_status': status, 'core_version': response.core_version,
            'result_schema_version': response.result_schema_version, 'result': result}
