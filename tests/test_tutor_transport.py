import asyncio
from concurrent import futures
import grpc
import pytest
from fastapi import FastAPI, HTTPException
from httpx import AsyncClient, ASGITransport
from app.contracts.tutor_contract.v1 import tutor_pb2 as pb, tutor_pb2_grpc as rpc
from app.core.config import settings
from app.routers.tutor_sample import router
from app.services.tutor_client import sample

class TestTutor(rpc.TutorServicer):
    mode = 'ok'
    def Sample(self, request, context):
        if self.mode == 'invalid': context.abort(grpc.StatusCode.INVALID_ARGUMENT, 'private detail')
        if self.mode == 'busy': context.abort(grpc.StatusCode.RESOURCE_EXHAUSTED, 'private detail')
        if self.mode == 'slow':
            import time
            while context.is_active(): time.sleep(0.01)
            return pb.SampleResponse()
        return pb.SampleResponse(request_id=request.request_id if self.mode != 'mismatch' else 'bad',
            schema_version='2.0' if self.mode == 'schema' else '1.0', tutor_version='test',
            message=request.message, reply='sample', sample=True)

@pytest.fixture
def upstream(monkeypatch):
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=2))
    handler = TestTutor()
    rpc.add_TutorServicer_to_server(handler, server)
    port = server.add_insecure_port('127.0.0.1:0')
    server.start()
    monkeypatch.setattr(settings, 'TUTOR_GRPC_TARGET', f'127.0.0.1:{port}')
    yield handler
    server.stop(0).wait()

def test_rest_grpc_roundtrip(upstream):
    app = FastAPI(); app.include_router(router)
    async def run():
        async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
            response = await client.post('/api/v1/tutor/sample', json={'message':'안녕하세요'})
            assert response.status_code == 200
            assert response.json()['message'] == '안녕하세요' and response.json()['sample'] is True
            for payload in [{'message':''}, {'message':' '*3}, {'message':'a'*257}, {'message':'ok','extra':1}]:
                assert (await client.post('/api/v1/tutor/sample', json=payload)).status_code == 422
    asyncio.run(run())

@pytest.mark.parametrize('mode,status',[('invalid',422),('busy',429),('mismatch',502),('schema',502),('slow',504)])
def test_error_translation(upstream, monkeypatch, mode, status):
    upstream.mode=mode
    monkeypatch.setattr(settings,'TUTOR_GRPC_TIMEOUT_SECONDS',0.1)
    with pytest.raises(HTTPException) as exc: asyncio.run(sample('hello'))
    assert exc.value.status_code == status
    assert 'private detail' not in exc.value.detail

def test_unconfigured(monkeypatch):
    monkeypatch.setattr(settings,'TUTOR_GRPC_TARGET','')
    with pytest.raises(HTTPException) as exc: asyncio.run(sample('hello'))
    assert exc.value.status_code == 503

def test_disconnect_cancels_rpc(upstream):
    upstream.mode='slow'
    async def disconnected(): return True
    with pytest.raises(asyncio.CancelledError): asyncio.run(sample('hello',disconnected))
