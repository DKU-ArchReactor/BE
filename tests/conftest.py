"""A remote contract fixture keeps BE tests independent of TUTOR implementation."""
from concurrent import futures
import grpc
import pytest


@pytest.fixture(scope='session')
def tutor_rpc_endpoint():
    from app.contracts.tutor_contract.v1 import tutor_pb2_grpc as rpc
    from tests.helpers.tutor_rpc_fixture import ContractTutor
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=4))
    rpc.add_TutorServicer_to_server(ContractTutor(), server)
    port = server.add_insecure_port('127.0.0.1:0')
    server.start()
    yield f'127.0.0.1:{port}'
    server.stop(0).wait()


@pytest.fixture(autouse=True)
def local_tutor_only(monkeypatch, tutor_rpc_endpoint):
    from app.core.config import settings
    monkeypatch.setattr(settings, 'TUTOR_GRPC_TARGET', tutor_rpc_endpoint)
