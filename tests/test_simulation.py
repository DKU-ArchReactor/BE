import asyncio
import json
import shutil
import uuid
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import Mock

import grpc
import pytest
from fastapi import HTTPException
from app.contracts.archreactor_contract.v1 import simulation_pb2 as pb, simulation_pb2_grpc as rpc
from app.services import simulation_service as client
from app.routers.simulation import owned_binary
from app.models.build import BuildStatus
from app.services.build_service import compile_source, UnsupportedOptionsError


def test_ownership_and_failed_build():
    db, user = Mock(), SimpleNamespace(user_id='owner')
    db.get.return_value = None
    with pytest.raises(HTTPException) as e:
        owned_binary(db, user, uuid.uuid4())
    assert e.value.status_code == 404
    build = SimpleNamespace(file=SimpleNamespace(project=SimpleNamespace(user_id='other')),
                            status=BuildStatus.success, binary_key='builds/x/binary.elf')
    db.get.return_value = build
    with pytest.raises(HTTPException) as e:
        owned_binary(db, user, uuid.uuid4())
    assert e.value.status_code == 403
    build.file.project.user_id = 'owner'
    build.status = BuildStatus.failed
    with pytest.raises(HTTPException) as e:
        owned_binary(db, user, uuid.uuid4())
    assert e.value.status_code == 409
    build.status = BuildStatus.success
    assert owned_binary(db, user, uuid.uuid4()) == build.binary_key


@pytest.mark.parametrize('option', ['-fplugin=/tmp/x', '-march=rv64gc', '-Wl,-T,/etc/passwd', '@/tmp/options'])
def test_compiler_options_cannot_override_profile(option):
    with pytest.raises(UnsupportedOptionsError):
        compile_source('int main(){return 0;}', 'c', option, 'rv32im')


def test_rv32im_elf():
    if not shutil.which('riscv64-unknown-elf-gcc'):
        pytest.skip('cross compiler verified in Linux CodeBuild')
    result = compile_source('int main(){return 0;}', 'c', '-O0', 'rv32im')
    assert result.status == BuildStatus.success, result.log
    assert result.binary[:6] == b'\x7fELF\x01\x01'
    assert int.from_bytes(result.binary[18:20], 'little') == 243


class FakeCore(rpc.SimulatorServicer):
    def __init__(self, code=None, schema='1.0'):
        self.code, self.schema = code, schema
    def RunSimulation(self, request, context):
        if self.code:
            context.abort(self.code, 'test')
        return pb.RunSimulationResponse(request_id=request.request_id, execution_id='test', status=pb.COMPLETED,
            core_version='future-compatible-core', result_schema_version=self.schema,
            result_json=json.dumps({'schema_version':self.schema, 'summary':{}, 'history':[], 'console_output':'ok', 'new_field':42}).encode())


@pytest.mark.parametrize('code,http', [(None,None), (grpc.StatusCode.UNAVAILABLE,503),
    (grpc.StatusCode.DEADLINE_EXCEEDED,504), (grpc.StatusCode.INVALID_ARGUMENT,422),
    (grpc.StatusCode.RESOURCE_EXHAUSTED,429)])
def test_client_mapping(monkeypatch, code, http):
    server = grpc.server(ThreadPoolExecutor(max_workers=2))
    rpc.add_SimulatorServicer_to_server(FakeCore(code), server)
    port = server.add_insecure_port('127.0.0.1:0')
    server.start()
    monkeypatch.setattr(client.settings, 'CORE_GRPC_TARGET', f'127.0.0.1:{port}')
    try:
        if http:
            with pytest.raises(HTTPException) as e:
                asyncio.run(client.run_simulation(b'elf', 'pipeline', 2))
            assert e.value.status_code == http
        else:
            response = asyncio.run(client.run_simulation(b'elf', 'pipeline', 2))
            assert response['core_version'] == 'future-compatible-core'
            assert response['result']['new_field'] == 42
    finally:
        server.stop(0).wait()
