import asyncio
import copy
import json
from pathlib import Path
import pytest
from pydantic import ValidationError
from app.schemas.assistant import ChatRequest
from app.services.assistant.evidence import cpi_check, address_checks, execution_evidence
from app.services.assistant.classifier import parse_classification
from app.services.assistant.solid_llm import answer_messages
from app.services.assistant.agent import AgentError
from tests.test_assistant_domain import completion, gateway, provider, collect

FIXTURE = json.loads((Path(__file__).parent/'fixtures/assistant_quality_cases.json').read_text())[0]

def request(*topics, question='첨부 코드 설명해'):
    req = ChatRequest(messages=[{'role':'user','content':question}], editor_source=FIXTURE['editor_source'])
    req._execution_context = copy.deepcopy(FIXTURE['context'])
    req._answer_topics = topics
    return req

@pytest.mark.parametrize('decision,topics', [('ALLOW',[]),('ALLOW',['secrets']),('ALLOW',['cpi','cpi']),
    ('CLARIFY',['cpi']),('ALLOW','cpi'),('ALLOW',[1])])
def test_invalid_topics_fail_closed_without_answer(decision, topics):
    factory, requests, _ = gateway(completion(json.dumps({'decision':decision,'topics':topics})))
    with pytest.raises(AgentError): collect(provider(factory))
    assert len(requests)==1


def test_valid_classification_sets_only_internal_topics():
    req=request()
    factory, sent, _=gateway(completion('{"decision":"ALLOW","topics":["cpi"]}'))
    events=collect(provider(factory),req)
    assert req._answer_topics==('cpi',)
    assert events[-1]['context']==req._execution_context['reference']
    assert 'verified_metrics' in sent[1]['messages'][-2]['content']
    assert 'ARCHREACTOR_EDITOR_SOURCE' not in str(sent[1])
    with pytest.raises(ValidationError):
        ChatRequest(messages=[{'role':'user','content':'CPI'}],_answer_topics=['cpi'])


def test_selection_is_union_without_modifying_original_and_no_hash_identity():
    req=request('cpi','hazards')
    original=copy.deepcopy(req._execution_context)
    value=execution_evidence(req)
    assert 'verified_metrics' in value and 'cycle_events' in value
    assert 'registers' not in value and 'selected_memory_words' not in value
    assert 'artifact_sha256' not in value['reference']
    assert req._execution_context==original
    assert value['observed_loop_iterations'] is None


def test_static_code_and_identity_do_not_receive_execution_values():
    for topic in ['code','flow','identity','service','concept']:
        req=request(topic)
        value=execution_evidence(req)
        assert not {'registers','selected_memory_words','stage_activity','verified_metrics','execution_status'} & value.keys()
        assert value['relationship_to_editor_source']=='not_verified'
        if topic!='identity': assert 'reference' not in value
        messages=answer_messages(req)
        assert any('ARCHREACTOR_EDITOR_SOURCE' in m['content'] for m in messages)==(topic in ['code','flow'])


def test_stack_and_memory_are_distinct_scopes():
    stack=execution_evidence(request('stack',question='s0-20 주소'))
    assert set(stack['registers'])=={'x2','x8'}
    assert 'selected_memory_words' not in stack
    memory=execution_evidence(request('memory'))
    assert memory['selected_memory_words']==FIXTURE['context']['selected_memory_words']

@pytest.mark.parametrize('elapsed,retired,reported,status,cpi', [
    (0,1,0,'inconsistent',None), (26,13,2,'verified',2), (3,2,1.5,'verified',1.5), (26,13,9,'inconsistent',None),
    (0,0,None,'undefined',None),(2,0,0,'inconsistent',None),(None,2,1,'missing',None),
    (2,1,None,'missing',None),(True,1,1,'inconsistent',None),(-1,1,-1,'inconsistent',None),
    (2,1,float('nan'),'inconsistent',None),(2,1,float('inf'),'inconsistent',None)])
def test_cpi_validation(elapsed,retired,reported,status,cpi):
    result=cpi_check(elapsed,retired,reported)
    assert (result['status'],result['cpi'])==(status,cpi)
    json.dumps(result,allow_nan=False)


def test_selected_and_whole_scopes_and_counter_contradiction():
    req=request('cpi')
    req._execution_context['whole_run_summary']={'total_cycles':100,'instructions_executed':80,'cpi':1.25,'stalls':2,'forwards':10}
    metrics=execution_evidence(req)['verified_metrics']
    assert metrics['selected']['cpi']==2 and metrics['whole_run']['cpi']==1.25
    req._execution_context['whole_run_summary']['stalls']=0
    metrics=execution_evidence(req)['verified_metrics']
    assert not metrics['consistent_ranges']
    assert metrics['selected']['cpi'] is None and metrics['selected']['status']=='inconsistent'


def test_byte_difference_offsets_and_overflow_no_expression_execution():
    regs={'x2':'0x7fffefdc','x8':'0x7fffeffc','x0':'0x00000000'}
    values=address_checks('s0-20 과 sp+0x20 및 x0-1',regs)
    assert values[0]['difference_bytes']==32
    assert [v.get('address') for v in values[1:]]==['0x7fffefe8','0x7fffeffc',None]
    assert values[-1]['status']=='out_of_range'
    assert len(address_checks('s0-2.5 또는 s0-20/2',regs))==1
    assert address_checks('s0-20',{'x8':'__import__("os")'})==[]


def test_history_is_bounded_data_and_current_question_is_last():
    req=request('code')
    from app.schemas.assistant import ChatMessage
    req.messages=[ChatMessage(role='user' if n%2==0 else 'assistant',content='x'*2000) for n in range(8)]+[ChatMessage(role='user',content='이 코드 설명해')]
    messages=answer_messages(req)
    data=json.loads(messages[1]['content'].split('\n',1)[1])
    assert sum(len(x['content']) for x in data)<=4000
    assert all(m['role']!='assistant' for m in messages)
    assert messages[-1]['content']=='이 코드 설명해'
