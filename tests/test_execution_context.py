"""Owned immutable evidence, bounded egress, and legacy SSE regression checks."""
import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

from fastapi import HTTPException
from pydantic import ValidationError
import pytest
from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import Session

import app.models  # register relationships
from app.core.config import settings
from app.core.database import Base, get_db
from app.core.deps import get_current_user_optional
from app.models.user import User
from app.models.assistant_execution import AssistantExecution
from app.routers import assistant, simulation
from app.schemas.assistant import ChatRequest
from app.schemas.execution_context import ExecutionContextReference
from app.services.assistant import context, maintenance
from app.services.assistant.agent import get_agent_provider
from app.services.assistant.classifier import classification_input
from app.services.assistant.guarded import GuardedProvider
from app.services.assistant.policy import Decision
from app.services.assistant.solid_llm import answer_messages
from tests.test_assistant import chat_app, call, PAYLOAD
from tests.test_anonymous_simulation import api, post, compile_guest

NOW = datetime(2026, 11, 12, tzinfo=timezone.utc)


def response(mode='pipeline'):
    history = []
    for index in range(3):
        history.append({'clock': index, 'global_result': {
            'current_pc': '0x00010004', 'registers': {f'x{i}': hex(index if i == 1 else 0) for i in range(32)},
            'metrics': dict(zip(context.METRICS, [index, int(index > 0), index])),
            'memory_snapshot': {'0x1000': hex(index + 10), **({'0x1004': '0x55'} if index < 2 else {})},
            'console_output': 'PRIVATE_CONSOLE'},
            'stage_activity': {'EX': {'pc': '0x00010000', 'assembly': 'addi x1, x0, 1', 'source_line': 2}},
            'buffers': {'private': 'PRIVATE_BUFFER'},
            'cycle_events': {'stall': {'has_stall': index == 1, 'stall_reason': 'load_use', 'stall_desc': 'load-use hazard',
                                       'private': 'PRIVATE_EVENT'}}})
    return {'execution_id': str(uuid4()), 'result_schema_version': '1.0', 'core_version': 'test',
            'execution_status': 'COMPLETED', 'result': {'schema_version': '1.0', 'simulator': {'mode': mode},
            'initial_state': {'memory_snapshot': {'0x1000': '0x9'}}, 'history': history,
            'summary': {'total_cycles': 3, 'instructions_executed': 2, 'stalls': 1, 'forwards': 2}}}


@pytest.fixture
def db():
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add_all([User(user_id=user, email=user+'@example.invalid', password_hash='unused', name=user)
                         for user in ('alice', 'bob')])
        session.commit()
        yield session
    engine.dispose()


def save(db, body=None, cycle=1, now=NOW, **kwargs):
    payload, version = context.build_snapshot(body or response(), b'synthetic-elf')
    descriptor = context.store_snapshot(db, 'alice', payload, version, now)
    reference = ExecutionContextReference(**{key: descriptor[key] for key in
        ('execution_id', 'result_version', 'artifact_sha256', 'mode')}, cycle=cycle, **kwargs)
    return reference, payload


def test_projection_tracks_selected_cycle_not_final_and_does_not_leak(db):
    reference, payload = save(db, memory_addresses=[0x1000])
    result = context.resolve_context(db, reference, 'alice', NOW)
    assert result['registers']['x1'] == '0x00000001'
    assert result['selected_memory_words'] == {'0x00001000': '0x0000000b'}
    assert result['elapsed_cycles'] == 2 and result['metrics_at_selected_cycle']['cpi'] == 2
    assert result['whole_run_summary']['cpi'] == 1.5
    assert result['tutor']['asm_instructions'][0]['text'] == 'addi x1, x0, 1'
    assert result['tutor']['cycle_explanations'][0]['events'][0]['type'] == 'stall'
    assert 'PRIVATE_' not in context.canonical(payload)
    assert 'PRIVATE_' not in context.canonical(result)
    assert 'initial_memory' not in result and 'frames' not in result
    assert 'alice' not in context.canonical(result)
    first = context.resolve_context(db, reference.model_copy(update={'cycle': 0, 'memory_addresses': []}), 'alice', NOW)
    assert first['metrics_at_selected_cycle']['cpi'] is None
    assert first['selected_memory_words'] == {}


@pytest.mark.parametrize('changes,status', [
    ({'execution_id': uuid4()}, 404), ({'mode': 'single'}, 409),
    ({'artifact_sha256': '0'*64}, 409), ({'result_version': '0'*64}, 409),
    ({'cycle': 3}, 422), ({'memory_addresses': [0x2000]}, 422),
    ({'cycle': 2, 'memory_addresses': [0x1004]}, 422),
])
def test_reference_mismatch_never_silently_falls_back(db, changes, status):
    reference, _ = save(db)
    with pytest.raises(HTTPException) as error:
        context.resolve_context(db, reference.model_copy(update=changes), 'alice', NOW)
    assert error.value.status_code == status


def test_ownership_expiry_corruption_and_cleanup(db):
    reference, _ = save(db)
    with pytest.raises(HTTPException) as error:
        context.resolve_context(db, reference, 'bob', NOW)
    assert error.value.status_code == 404
    with pytest.raises(HTTPException) as error:
        context.resolve_context(db, reference, 'alice', NOW + timedelta(hours=1))
    assert error.value.status_code == 410
    row = db.get(AssistantExecution, str(reference.execution_id))
    row.payload = {**row.payload, 'core_version': 'tampered'}
    db.commit()
    with pytest.raises(HTTPException) as error:
        context.resolve_context(db, reference, 'alice', NOW)
    assert error.value.status_code == 409
    context.purge_expired(db, NOW + timedelta(hours=1))
    assert db.scalar(select(func.count()).select_from(AssistantExecution)) == 0


def test_retention_and_size_limits(db, monkeypatch):
    monkeypatch.setattr(settings, 'ASSISTANT_CONTEXT_MAX_SNAPSHOTS', 2)
    first, _ = save(db)
    save(db, now=NOW + timedelta(seconds=1))
    last, _ = save(db, now=NOW + timedelta(seconds=2))
    assert db.get(AssistantExecution, str(first.execution_id)) is None
    assert db.scalar(select(func.count()).select_from(AssistantExecution)) == 2
    monkeypatch.setattr(context, 'MAX_PROMPT_BYTES', 100)
    with pytest.raises(HTTPException) as error:
        context.resolve_context(db, last, 'alice', NOW + timedelta(seconds=3))
    assert error.value.status_code == 413
    monkeypatch.setattr(context, 'MAX_SNAPSHOT_BYTES', 100)
    with pytest.raises(ValueError):
        context.build_snapshot(response(), b'elf')


@pytest.mark.parametrize('change', [
    lambda r: r['result'].update(schema_version='2.0'),
    lambda r: r['result']['history'][0].update(clock=1),
    lambda r: r['result']['history'][0]['global_result']['registers'].update(x1=True),
    lambda r: r['result']['history'][0]['global_result'].update(memory_snapshot={'0x1': '0x0'}),
    lambda r: r['result']['history'][0]['cycle_events']['stall'].update(stall_desc='a'*513),
])
def test_invalid_core_evidence_fails_closed(change):
    body = response()
    change(body)
    with pytest.raises((ValueError, KeyError, TypeError)):
        context.build_snapshot(body, b'elf')


@pytest.mark.parametrize('addresses', [[0]*2, [1], [True], [-4], [2**32], list(range(0, 68, 4))])
def test_memory_reference_validation(db, addresses):
    reference, _ = save(db)
    with pytest.raises(ValidationError):
        ExecutionContextReference(**{**reference.model_dump(), 'memory_addresses': addresses})


def test_untrusted_data_cannot_replace_private_context(db):
    reference, _ = save(db)
    with pytest.raises(ValidationError):
        ChatRequest(**PAYLOAD, _execution_context={'registers': {}})
    with pytest.raises(ValidationError):
        ChatRequest(**PAYLOAD, context={**reference.model_dump(), 'registers': {}})
    request = ChatRequest(**PAYLOAD, context=reference)
    request._execution_context = context.resolve_context(db, reference, 'alice', NOW)
    classifier = json.loads(classification_input(request))
    assert classifier['execution_reference'] == {'mode': 'pipeline', 'cycle': 1}
    assert 'registers' not in classification_input(request)
    messages = answer_messages(request)
    assert 'ARCHREACTOR_EXECUTION_CONTEXT' in messages[-2]['content']
    assert messages[-1]['content'] == PAYLOAD['messages'][0]['content']
    assert 'load-use hazard' in messages[-2]['content']


@pytest.mark.parametrize('decision', list(Decision))
def test_gate_only_sends_context_to_answer_after_allow(db, decision):
    reference, _ = save(db)
    request = ChatRequest(**PAYLOAD, context=reference)
    request._execution_context = context.resolve_context(db, reference, 'alice', NOW)
    class Classifier:
        async def classify(self, req, observation):
            return decision
    class Answer:
        async def stream(self, req):
            assert req._execution_context['reference']['cycle'] == 1
            yield {'type': 'delta', 'text': 'grounded answer'}
            yield {'type': 'done', 'usage': {}, 'stop_reason': 'end_turn'}
    factory = Mock(return_value=Answer())
    async def collect():
        return [event async for event in GuardedProvider(Classifier(), factory).stream(request)]
    output = asyncio.run(collect())
    assert [event['type'] for event in output] == ['delta', 'done']
    assert factory.call_count == int(decision == Decision.ALLOW)
    assert ('context' in output[-1]) == (decision == Decision.ALLOW)


def test_invalid_context_precedes_quota_and_provider(chat_app, db, monkeypatch):
    app, quota = chat_app
    reference, _ = save(db)
    provider = Mock()
    app.dependency_overrides[get_agent_provider] = lambda: provider
    monkeypatch.setattr(assistant, 'resolve_context', Mock(side_effect=HTTPException(404, 'missing')))
    status, body = asyncio.run(call(app, {**PAYLOAD, 'context': reference.model_dump(mode='json')}))
    assert status == 404 and 'delta' not in body
    quota.assert_not_called()
    provider.stream.assert_not_called()


def test_context_route_sse_and_quota_once(chat_app, db, monkeypatch):
    app, quota = chat_app
    reference, _ = save(db)
    evidence = context.resolve_context(db, reference, 'alice', NOW)
    monkeypatch.setattr(assistant, 'resolve_context', lambda *args: evidence)
    class Provider:
        async def stream(self, request):
            assert request._execution_context == evidence
            yield {'type': 'delta', 'text': 'result'}
            yield {'type': 'done', 'context': evidence['reference'], 'usage': {}}
    app.dependency_overrides[get_agent_provider] = Provider
    status, body = asyncio.run(call(app, {**PAYLOAD, 'context': reference.model_dump(mode='json')}))
    assert status == 200 and '"context"' in body and '"done"' in body
    quota.assert_called_once()


def test_capture_requires_login_and_defaults_to_no_storage(api):
    _, compiled = compile_guest(api)
    payload = {'simulation_token': compiled['simulation_token'], 'capture_assistant_context': True}
    assert post(api.app, '/api/v1/simulation/run', payload)[0] == 401
    assert api.runs == [] and api.db.mock_calls == []


def test_capture_storage_failure_preserves_simulation(api, monkeypatch):
    from sqlalchemy.exc import SQLAlchemyError
    _, compiled = compile_guest(api)
    api.app.dependency_overrides[get_current_user_optional] = lambda: SimpleNamespace(user_id='alice')
    monkeypatch.setattr(simulation, 'build_snapshot', lambda *args: ({}, 'version'))
    monkeypatch.setattr(simulation, 'store_snapshot', Mock(side_effect=SQLAlchemyError('do not expose')))
    status, body = post(api.app, '/api/v1/simulation/run', {
        'simulation_token': compiled['simulation_token'], 'capture_assistant_context': True})
    assert status == 200 and body['execution_status'] == 'COMPLETED'
    assert body['assistant_context'] == {'available': False, 'code': 'CONTEXT_STORAGE_UNAVAILABLE'}
    assert 'do not expose' not in json.dumps(body)


def test_cleanup_shutdown_and_sanitized_failure(monkeypatch, caplog):
    called = []
    def fail():
        called.append(True)
        raise RuntimeError('private connection string')
    monkeypatch.setattr(maintenance, 'sweep', fail)
    async def run():
        async with maintenance.lifespan(None):
            for _ in range(100):
                if called:
                    break
                await asyncio.sleep(.005)
    asyncio.run(run())
    assert called and 'assistant_context_cleanup_failed' in caplog.text
    assert 'private connection string' not in caplog.text


def test_capture_success_uses_server_evidence_and_owner(api, monkeypatch):
    _, compiled = compile_guest(api)
    api.app.dependency_overrides[get_current_user_optional] = lambda: SimpleNamespace(user_id='alice')
    source = response()
    async def run(*args, **kwargs):
        return deepcopy(source)
    monkeypatch.setattr(simulation, 'run_simulation', run)
    captured = []
    def store(db, user, payload, version):
        captured.append((user, payload, version))
        return {'available': True, 'execution_id': payload['execution_id']}
    monkeypatch.setattr(simulation, 'store_snapshot', store)
    status, body = post(api.app, '/api/v1/simulation/run', {
        'simulation_token': compiled['simulation_token'], 'capture_assistant_context': True})
    assert status == 200 and body['assistant_context']['available'] is True
    assert captured[0][0] == 'alice'
    assert captured[0][1]['execution_id'] == source['execution_id']
    assert captured[0][1]['tutor']['asm_instructions']


def test_eval_comparison_accepts_equivalent_hex_but_not_incorrect_facts():
    from scripts.evaluate_assistant_context import matches
    assert matches({'value': '0xA'}, {'value': '0x0000000a'})
    assert not matches({'value': '0xB'}, {'value': '0x0000000a'})
    assert not matches({'cpi': 0}, {'cpi': None})
    assert not matches({'instructions': True}, {'instructions': 1})
    assert not matches({}, {'cpi': 1.5})
