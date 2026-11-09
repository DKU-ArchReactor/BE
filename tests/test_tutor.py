import copy
import pytest
from fastapi import FastAPI
from app.routers import tutor
from app.schemas.tutor import ExplainItem, ExplainRequest
from app.services.tutor import compile_explanations, simulation_explanations
from app.services.tutor.rules import explain
from tests.test_anonymous_simulation import post, api, compile_guest  # reuse guest API fixture


@pytest.mark.parametrize('text,category', [
    ('', 'empty'), ('// note', 'comment'), ('#include <x.h>', 'preprocessor'),
    ('int main() {', 'function'), ('return 0;', 'return'), ('if (x)', 'if'),
    ('else if (x)', 'else_if'), ('else', 'else'), ('for(;;)', 'for'),
    ('while(x)', 'while'), ('int x = 2;', 'initialization'), ('int x;', 'declaration'),
    ('x += 1;', 'assignment'), ('f(x);', 'call'), ('}', 'scope'),
])
def test_c_rules(text, category):
    assert explain(ExplainItem(kind='c', text=text)).category == category


def test_rule_api_before_compile_and_bounded_inputs():
    app = FastAPI()
    app.include_router(tutor.router)
    status, result = post(app, '/api/v1/tutor/explain', {'items': [
        {'kind': 'c', 'text': 'int x = 2;', 'line': 4},
        {'kind': 'asm', 'text': 'lw a0, 0(a1)'},
        {'kind': 'crt', 'text': 'auipc ra, 0', 'pc': '0x10000'},
    ]})
    assert status == 200 and result['schema_version'] == '1.0'
    assert result['items'][0]['category'] == 'initialization'
    assert '스택' not in result['items'][1]['summary']
    assert result['items'][2]['kind'] == 'crt'
    assert 'main()' not in result['items'][2]['summary']
    for payload in ({'items': []}, {'items': [{'kind': 'c', 'text': 'x' * 4097}]},
                    {'items': [{'kind': 'c', 'text': ''}] * 129}):
        assert post(app, '/api/v1/tutor/explain', payload)[0] == 422


def test_cycle_events_coexist_and_preserve_evidence():
    result = {'history': [{'clock': 12, 'cycle_events': {
        'stall': {'has_stall': True, 'stall_desc': 'load-use', 'assembly': 'add x6,x5,x7'},
        'forwarding': {'has_forwarded': True, 'forwarding_info': {'target_register': ['x5']}},
        'control_hazard': {'has_flush': True, 'flush_reason': 'control_hazard_branch_taken',
                           'redirect_pc': '0x10020', 'flushed_stages': ['IF', 'ID']},
    }}, {'clock': 13, 'cycle_events': {'stall': {'has_stall': False}}}],
    'program': {'code_mapping': {'0x10000': {'assembly': 'auipc ra, 0', 'source_line': None}}}}
    before = copy.deepcopy(result)
    bundle = simulation_explanations(result)
    assert result == before
    assert len(bundle['cycle_explanations']) == 1
    cycle = bundle['cycle_explanations'][0]
    assert cycle['cycle'] == 12 and cycle['history_index'] == 0
    assert [x['type'] for x in cycle['events']] == ['stall', 'forwarding', 'flush']
    assert cycle['events'][0]['detail'] == 'load-use'
    assert cycle['events'][1]['evidence']['forwarding_info']['target_register'] == ['x5']
    assert '0x10020' in cycle['events'][2]['detail']
    assert '예측 실패' not in cycle['events'][2]['detail']


def test_old_or_empty_results_are_supported():
    assert simulation_explanations({'history': [{'clock': 0}], 'program': None})['cycle_explanations'] == []
    assert simulation_explanations({})['asm_instructions'] == []


def test_build_rules_in_both_guest_modes(api):
    for lang, content in [('c', 'int x = 2;'), ('asm', 'addi sp,sp,-16')]:
        _, result = compile_guest(api, lang=lang, content=content)
        assert result['tutor']['schema_version'] == '1.0'
        assert bool(result['tutor']['c_lines']) == (lang == 'c')
    _, native = compile_guest(api, compile_profile='native')
    assert native['tutor'] is None


def test_guest_simulation_adds_tutor_without_replacing_core_result(api):
    _, build = compile_guest(api)
    _, result = post(api.app, '/api/v1/simulation/run', {'simulation_token': build['simulation_token']})
    assert result['result']['console_output'] == 'ok'
    assert result['tutor']['cycle_explanations'] == []
