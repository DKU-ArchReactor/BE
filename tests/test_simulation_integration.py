"""HTTP -> BE client -> test-only RPC fixture -> real CORE engine."""
from io import BytesIO
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import Mock
import uuid

import grpc
import pytest
from fastapi import FastAPI

from app.core.database import get_db
from app.core.deps import get_current_user_optional
from app.models.build import BuildStatus
from app.routers import simulation
from app.services import simulation_service
from tests.test_anonymous_simulation import post


@pytest.fixture(scope='module')
def core_endpoint():
    source = os.environ.get('CORE_SOURCE')
    if not source:
        pytest.skip('Set CORE_SOURCE to the CORE engine checkout')
    root = Path(source).resolve()
    assert (root / 'app/single_cycle_engine.py').is_file(), 'CORE_SOURCE must contain the new single engine'
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    target = f'127.0.0.1:{port}'
    options = {'creationflags': subprocess.CREATE_NO_WINDOW} if sys.platform == 'win32' else {}
    fixture = Path(__file__).parent / 'helpers/core_rpc_fixture.py'
    process = subprocess.Popen([sys.executable, str(fixture), '--core-source', str(root), '--port', str(port)],
                               stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, **options)
    channel = grpc.insecure_channel(target)
    try:
        grpc.channel_ready_future(channel).result(timeout=10)
        yield target, root
    finally:
        channel.close()
        process.terminate()
        try:
            process.communicate(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate()


@pytest.fixture
def api(core_endpoint, monkeypatch):
    target, root = core_endpoint
    monkeypatch.setattr(simulation_service.settings, 'CORE_GRPC_TARGET', target)
    app = FastAPI()
    app.include_router(simulation.router)
    user = SimpleNamespace(user_id='test-owner')
    db = Mock()
    db.get.return_value = SimpleNamespace(file=SimpleNamespace(project=SimpleNamespace(user_id=user.user_id)),
        status=BuildStatus.success, binary_key='test/binary.elf')
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user_optional] = lambda: user
    data = (root / 'tests/program2.elf').read_bytes()
    storage = {'data': data}
    monkeypatch.setattr(simulation, 'download_bytes', lambda key, limit: storage['data'])
    return app, storage


def execute(app, mode, **overrides):
    return post(app, '/api/v1/simulation/run', {'build_id': str(uuid.uuid4()), 'mode': mode, **overrides})


def test_http_both_engines_preserve_real_state_and_metadata(api):
    app, storage = api
    responses = []
    for mode, cycles in [('single', 97), ('pipeline', 134)]:
        status, body = execute(app, mode)
        assert status == 200 and body['execution_status'] == 'COMPLETED'
        result = body['result']
        assert result['simulator']['mode'] == mode
        assert result['summary']['total_cycles'] == cycles
        assert result['summary']['instructions_executed'] == 97
        assert result['initial_state']['metrics']['accumulated_instructions'] == 0
        assert result['program']['instructions'] and result['program']['memory_regions']
        assert 'ALL PASS' in result['console_output']
        assert body['result_schema_version'] == result['schema_version']
        if mode == 'single':
            assert result['simulator']['pipeline_model'] == 'single-cycle'
            assert all(not any(cycle['buffers'].values()) for cycle in result['history'])
        responses.append(body)
    assert responses[0]['execution_id'] != responses[1]['execution_id']
    assert responses[0]['result']['program']['fingerprint'] == responses[1]['result']['program']['fingerprint']
    for key in ('registers', 'memory_snapshot', 'console_output'):
        assert responses[0]['result']['history'][-1]['global_result'][key] == responses[1]['result']['history'][-1]['global_result'][key]


@pytest.mark.parametrize('mode', ['single', 'pipeline'])
def test_http_cycle_limit_has_distinct_execution_status(api, mode):
    status, body = execute(api[0], mode, max_cycles=1)
    assert status == 200 and body['execution_status'] == 'CYCLE_LIMIT'
    assert body['result']['status'] == 'error'
    assert body['result']['summary']['total_cycles'] == 1


def test_http_invalid_elf_is_422(api):
    app, storage = api
    storage['data'] = b'not an ELF'
    status, body = execute(app, 'single')
    assert status == 422
    assert body['detail'] == 'CORE: INVALID_ARGUMENT'


def test_http_runtime_fault_is_a_simulation_result(api):
    from elftools.elf.elffile import ELFFile
    app, storage = api
    data = bytearray(storage['data'])
    elf = ELFFile(BytesIO(data))
    text = elf.get_section_by_name('.text')
    data[24:28] = int(text['sh_addr']).to_bytes(4, 'little')
    data[text['sh_offset']:text['sh_offset'] + 4] = (0x00202283).to_bytes(4, 'little')
    storage['data'] = bytes(data)
    status, body = execute(app, 'single')
    assert status == 200 and body['execution_status'] == 'SIMULATION_ERROR'
    event = body['result']['history'][-1]['cycle_events']['runtime_error']
    assert event['code'] == 'MEMORY_ALIGNMENT_ERROR'


def test_guest_request_uses_same_engine_path(api, monkeypatch):
    app, storage = api
    app.dependency_overrides[get_current_user_optional] = lambda: None
    monkeypatch.setattr(simulation, 'anonymous_binary_key', lambda token: 'test/binary.elf')
    status, body = post(app, '/api/v1/simulation/run', {'simulation_token': 'test-boundary-only', 'mode': 'single'})
    assert status == 200 and body['execution_status'] == 'COMPLETED'
    assert body['result']['summary']['total_cycles'] == 97


def test_http_rejects_another_users_build_before_core_execution(api):
    app, storage = api
    storage['data'] = b'invalid ELF would fail if execution were reached'
    db = app.dependency_overrides[get_db]()
    db.get.return_value.file.project.user_id = 'another-user'
    status, body = execute(app, 'single')
    assert status == 403 and body['detail'] == 'Access denied'


@pytest.mark.parametrize('mode', ['single', 'pipeline'])
def test_real_core_context_matches_every_selected_cycle(api, mode, tmp_path):
    from datetime import datetime, timezone
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from app.core.database import Base
    import app.models
    from app.models.user import User
    from app.schemas.execution_context import ExecutionContextReference
    from app.services.assistant.context import build_snapshot, store_snapshot, resolve_context
    app, storage = api
    status, body = execute(app, mode)
    assert status == 200
    payload, version = build_snapshot(body, storage['data'])
    assert payload['tutor']['asm_instructions'], 'Real CORE has no program.code_mapping; derive executed instructions'
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    now = datetime.now(timezone.utc)
    with Session(engine) as db:
        db.add(User(user_id='owner', email='owner@example.invalid', password_hash='unused', name='owner'))
        db.commit()
        descriptor = store_snapshot(db, 'owner', payload, version, now)
        for index, cycle in enumerate(body['result']['history']):
            state = cycle['global_result']
            addresses = [int(address, 16) for address in state['memory_snapshot']][:16]
            ref = ExecutionContextReference(**{k: descriptor[k] for k in
                ('execution_id', 'result_version', 'artifact_sha256', 'mode')}, cycle=index, memory_addresses=addresses)
            projected = resolve_context(db, ref, 'owner', now)
            assert projected['registers'] == {key: value.lower() for key, value in state['registers'].items()}
            assert projected['selected_memory_words'] == {f'0x{address:08x}': next(value.lower() for key, value in
                state['memory_snapshot'].items() if int(key, 16) == address) for address in addresses}
            for counter in ('accumulated_stalls', 'accumulated_forwards', 'accumulated_instructions'):
                assert projected['metrics_at_selected_cycle'][counter] == state['metrics'][counter]
            retired = state['metrics']['accumulated_instructions']
            assert projected['metrics_at_selected_cycle']['cpi'] == ((index+1)/retired if retired else None)
            kinds = {e['type'] for c in projected['tutor']['cycle_explanations'] for e in c['events']}
            for kind, name, flag in [('stall', 'stall', 'has_stall'), ('forwarding', 'forwarding', 'has_forwarded'),
                                     ('flush', 'control_hazard', 'has_flush')]:
                assert (kind in kinds) == bool(cycle['cycle_events'][name][flag])
    engine.dispose()
