from concurrent import futures
import json
import time
import grpc
import pytest
from fastapi import HTTPException
from app.contracts.tutor_contract.v1 import tutor_pb2 as pb, tutor_pb2_grpc as rpc
from app.core.config import settings
from app.schemas.tutor import ExplainItem
from app.services import tutor_client


class AnalysisFixture(rpc.TutorServicer):
    mode = 'ok'

    def respond(self, request, context, bundle):
        errors = {'invalid': grpc.StatusCode.INVALID_ARGUMENT,
                  'busy': grpc.StatusCode.RESOURCE_EXHAUSTED,
                  'unimplemented': grpc.StatusCode.UNIMPLEMENTED}
        if self.mode in errors:
            context.abort(errors[self.mode], 'PRIVATE_TUTOR_INPUT')
        if self.mode == 'slow':
            while context.is_active():
                time.sleep(0.005)
        encoded = json.dumps({'schema_version': '1.0', **bundle})
        if self.mode == 'json':
            encoded = 'PRIVATE_TUTOR_INPUT'
        if self.mode == 'nan':
            encoded = '{"schema_version":"1.0","value":NaN}'
        if self.mode == 'deep':
            encoded = '{"schema_version":"1.0","extra":'+'['*10000+'0'+']'*10000+'}'
        return pb.TutorResponse(request_id='mismatch' if self.mode == 'id' else request.request_id,
            schema_version='2.0' if self.mode == 'schema' else '1.0',
            tutor_version='' if self.mode == 'version' else 'test', result_json=encoded)

    def Explain(self, request, context):
        items = [{'kind': item.kind, 'category': 'test', 'title': 'test', 'summary': 'test', 'detail': 'test'} for item in request.items]
        if self.mode == 'null_item':
            items = [None]
        if self.mode == 'kind':
            items[0]['kind'] = 'c'
        return self.respond(request, context, {'items': items})

    def Compile(self, request, context):
        return self.respond(request, context, {} if self.mode == 'shape' else {'c_lines': [], 'asm_instructions': []})

    def Analyze(self, request, context):
        return self.respond(request, context, {} if self.mode == 'shape' else {
            'asm_instructions': [], 'cycle_explanations': [], 'execution_steps': []})


@pytest.fixture
def remote(monkeypatch):
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=2))
    fixture = AnalysisFixture()
    rpc.add_TutorServicer_to_server(fixture, server)
    port = server.add_insecure_port('127.0.0.1:0')
    server.start()
    monkeypatch.setattr(settings, 'TUTOR_GRPC_TARGET', f'127.0.0.1:{port}')
    monkeypatch.setattr(settings, 'TUTOR_GRPC_TIMEOUT_SECONDS', 0.1)
    yield fixture
    server.stop(0).wait()


@pytest.mark.parametrize('mode,status', [
    ('invalid', 422), ('busy', 429), ('unimplemented', 503), ('slow', 504),
    ('id', 502), ('schema', 502), ('version', 502), ('json', 502), ('nan', 502), ('deep', 502),
    ('null_item', 502), ('kind', 502),
])
def test_explain_rejects_mismatched_or_failed_responses(remote, mode, status):
    remote.mode = mode
    with pytest.raises(HTTPException) as error:
        tutor_client.explain_items([ExplainItem(kind='asm', text='nop')])
    assert error.value.status_code == status
    assert 'PRIVATE_TUTOR_INPUT' not in error.value.detail


@pytest.mark.parametrize('method', ['compile', 'analyze'])
def test_incomplete_result_shape_is_not_returned_as_success(remote, method):
    remote.mode = 'shape'
    with pytest.raises(HTTPException) as error:
        if method == 'compile':
            tutor_client.compiled_source('return 0;', 'c', None)
        else:
            tutor_client.analyze_result({})
    assert error.value.status_code == 502
