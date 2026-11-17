"""BE REST -> generated gRPC contract; rule semantics are owned by TUTOR."""
from copy import deepcopy
from fastapi import FastAPI
import pytest
from app.core.config import settings
from app.routers import tutor
from app.schemas.tutor import ExplainItem
from app.services import tutor_client
from app.services.tutor import simulation_explanations
from tests.test_anonymous_simulation import post, api, compile_guest


def test_explain_batch_keeps_additive_fields_and_input_order():
    app = FastAPI()
    app.include_router(tutor.router)
    status, body = post(app, '/api/v1/tutor/explain', {'items': [
        {'kind': 'c', 'text': 'return 1;'}, {'kind': 'asm', 'text': 'mv a0,a1'}]})
    assert status == 200 and [item['kind'] for item in body['items']] == ['c', 'asm']
    assert body['items'][1]['reads'] == ['x11']


@pytest.mark.parametrize('items', [[], [{'kind': 'c', 'text': 'x'*4097}], [{'kind': 'c', 'text': ''}]*129])
def test_invalid_rest_inputs_are_rejected(items):
    app = FastAPI()
    app.include_router(tutor.router)
    assert post(app, '/api/v1/tutor/explain', {'items': items})[0] == 422


def test_build_and_both_simulation_modes_keep_core_envelope(api):
    for lang in ('c', 'asm'):
        status, build = compile_guest(api, lang=lang)
        assert status == 201 and bool(build['tutor']['c_lines']) == (lang == 'c')
        for mode in ('single', 'pipeline'):
            status, result = post(api.app, '/api/v1/simulation/run', {'simulation_token': build['simulation_token'], 'mode': mode})
            assert status == 200 and result['result']['console_output'] == 'ok'
            assert result['tutor']['schema_version'] == '1.0'
    assert compile_guest(api, compile_profile='native')[1]['tutor'] is None


def test_missing_tutor_does_not_fail_compiler_engine_or_context(api, monkeypatch):
    monkeypatch.setattr(settings, 'TUTOR_GRPC_TARGET', '')
    _, build = compile_guest(api)
    assert build['tutor'] is None
    status, result = post(api.app, '/api/v1/simulation/run', {'simulation_token': build['simulation_token']})
    assert status == 200 and result['tutor'] is None and result['execution_status'] == 'COMPLETED'
    from app.services.assistant.context import build_snapshot
    from tests.test_execution_context import response
    payload, _ = build_snapshot(response(), b'elf')
    assert payload['tutor']['available'] is False
    assert payload['frames']


def test_analysis_forwards_elf_and_preserves_input(monkeypatch):
    captured = []
    def invoke(method, message):
        captured.append((method, message))
        return {'schema_version': '1.0', 'asm_instructions': [], 'cycle_explanations': [], 'execution_steps': []}
    monkeypatch.setattr(tutor_client, '_invoke', invoke)
    result = {'history': []}
    before = deepcopy(result)
    assert simulation_explanations(result, elf_bytes=b'ELF')['schema_version'] == '1.0'
    assert captured[0][0] == 'Analyze' and captured[0][1].elf == b'ELF'
    assert result == before


def test_assistant_projection_normalizes_pc_and_excludes_partial_trace_counters():
    from app.services.assistant.context import build_snapshot
    from tests.test_execution_context import response
    body = response()
    for frame in body['result']['history']:
        frame['stage_activity']['EX']['pc'] = '0x00010ABC'
    payload, _ = build_snapshot(body, b'elf')
    instruction = payload['tutor']['asm_instructions'][0]
    assert instruction['pc'] == '0x00010abc'
    assert 'retire_count' not in instruction and 'source_file' not in instruction
    assert 'EXCLUDED_FILE_PATH' not in str(payload)


def test_assistant_uses_file_aware_source_line_correction_without_mutating_result():
    from app.services.assistant.context import build_snapshot
    from tests.test_execution_context import response
    body = response()
    body['tutor'] = {'source_mapping': {'basis': 'elf_dwarf'},
                     'asm_instructions': [{'pc': '0x00010000', 'source_line': None}]}
    before = deepcopy(body)
    payload, _ = build_snapshot(body, b'elf')
    assert payload['frames'][0]['stage_activity']['EX']['source_line'] is None
    assert payload['tutor']['asm_instructions'][0]['source_line'] is None
    assert body == before
