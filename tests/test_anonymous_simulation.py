import asyncio
import json
import time
import uuid
from types import SimpleNamespace
from unittest.mock import Mock

import jwt
import pytest
from fastapi import FastAPI

from app.core import simulation_token as tokens
from app.core.database import get_db
from app.core.security import create_access_token, decode_access_token
from app.models.build import BuildStatus
from app.routers import build, simulation
from app.services.build_service import CompileResult


@pytest.fixture
def api(monkeypatch):
    # Synthetic test key only; no live credentials or external services.
    monkeypatch.setattr(tokens.settings, 'JWT_SECRET_KEY', 'anonymous-simulation-test-key-only')
    monkeypatch.setattr(tokens.settings, 'JWT_ALGORITHM', 'HS256')
    app = FastAPI()
    app.include_router(build.router)
    app.include_router(simulation.router)
    db = Mock()
    db.get.side_effect = AssertionError('Guest requests must not query the DB')
    db.add.side_effect = AssertionError('Guest requests must not create DB records')
    db.flush.side_effect = AssertionError('Guest requests must not flush DB records')
    db.commit.side_effect = AssertionError('Guest requests must not commit DB records')
    app.dependency_overrides[get_db] = lambda: db
    storage = {}
    monkeypatch.setattr(build.build_service, 'compile_source', lambda **kw: CompileResult(
        BuildStatus.success, '', 'assembly', b'elf'))

    def upload(prefix, result):
        if result.status != BuildStatus.success:
            return None, None
        storage[f'{prefix}/binary.elf'] = result.binary
        return f'{prefix}/assembly.s', f'{prefix}/binary.elf'

    monkeypatch.setattr(build.build_service, 'upload_compile_artifacts', upload)
    monkeypatch.setattr(build, 'presigned_get_url', lambda key: 'https://example.invalid/' + key)
    monkeypatch.setattr(simulation, 'download_bytes', lambda key, limit: storage[key])
    runs = []

    async def run(elf, mode, max_cycles, disconnected, timings):
        runs.append((elf, mode, max_cycles))
        return {'execution_status': 'COMPLETED', 'result': {
            'summary': {}, 'history': [], 'console_output': 'ok'}}

    monkeypatch.setattr(simulation, 'run_simulation', run)
    return SimpleNamespace(app=app, db=db, storage=storage, runs=runs)


def post(app, path, payload):
    """Exercise FastAPI routing, auth dependencies and validation without a socket."""
    messages = []
    body = json.dumps(payload).encode()

    async def receive():
        return {'type': 'http.request', 'body': body, 'more_body': False}

    async def send(message):
        messages.append(message)

    asyncio.run(app({
        'type': 'http', 'http_version': '1.1', 'method': 'POST', 'scheme': 'http',
        'path': path, 'raw_path': path.encode(), 'query_string': b'',
        'headers': [(b'content-type', b'application/json')],
        'server': ('test', 80), 'client': ('test', 1234), 'root_path': '',
    }, receive, send))
    status = next(m['status'] for m in messages if m['type'] == 'http.response.start')
    data = b''.join(m.get('body', b'') for m in messages if m['type'] == 'http.response.body')
    return status, json.loads(data)


def compile_guest(api, **overrides):
    return post(api.app, '/api/v1/build/compile', {
        'content': 'int main(){return 0;}', 'lang': 'c', 'compiler_opt': '-O0', **overrides})


def test_guest_compile_then_simulate_without_login_or_saved_file(api):
    status, compiled = compile_guest(api)
    assert status == 201 and compiled['status'] == 'success'
    assert compiled['build_id'] is None
    assert compiled['simulation_token_expires_in'] == 300
    token = compiled['simulation_token']
    assert tokens.anonymous_binary_key(token) in api.storage
    for mode in ('single', 'pipeline'):
        status, response = post(api.app, '/api/v1/simulation/run', {
            'simulation_token': token, 'mode': mode, 'max_cycles': 100})
        assert status == 200 and response['execution_status'] == 'COMPLETED'
    assert api.runs == [(b'elf', 'single', 100), (b'elf', 'pipeline', 100)]
    assert api.db.mock_calls == []


def test_no_token_for_native_or_failed_compile(api, monkeypatch):
    _, response = compile_guest(api, compile_profile='native')
    assert response['simulation_token'] is None
    assert response['simulation_token_expires_in'] is None
    monkeypatch.setattr(build.build_service, 'compile_source', lambda **kw: CompileResult(
        BuildStatus.failed, 'compiler error', None, None))
    _, response = compile_guest(api)
    assert response['status'] == 'failed' and response['simulation_token'] is None


def test_saved_build_still_requires_login(api):
    status, _ = post(api.app, '/api/v1/simulation/run', {'build_id': str(uuid.uuid4())})
    assert status == 401 and not api.runs
    assert api.db.mock_calls == []


@pytest.mark.parametrize('payload', [
    {}, {'build_id': None}, {'simulation_token': ''},
    {'build_id': str(uuid.uuid4()), 'simulation_token': 'token'},
    {'simulation_token': 'token', 'max_cycles': 2001},
    {'simulation_token': 'token', 'mode': 'invalid'},
])
def test_invalid_request_rejected(api, payload):
    status, _ = post(api.app, '/api/v1/simulation/run', payload)
    assert status == 422 and not api.runs


def test_expired_token_rejected_before_storage_or_core(api, monkeypatch):
    issued_at = int(time.time()) - 301
    with monkeypatch.context() as context:
        context.setattr(tokens.time, 'time', lambda: issued_at)
        token = tokens.create_simulation_token(uuid.uuid4())
    status, response = post(api.app, '/api/v1/simulation/run', {'simulation_token': token})
    assert status == 410 and 'expired' in response['detail']
    assert not api.runs


def test_tampered_and_login_tokens_rejected(api):
    _, compiled = compile_guest(api)
    token = compiled['simulation_token']
    header, payload, signature = token.split('.')
    signature = ('A' if signature[0] != 'A' else 'B') + signature[1:]
    login_token, _ = create_access_token('user')
    for invalid in (f'{header}.{payload}.{signature}', login_token, 'garbage'):
        status, _ = post(api.app, '/api/v1/simulation/run', {'simulation_token': invalid})
        assert status == 401
    with pytest.raises(jwt.InvalidTokenError):
        decode_access_token(token)
    assert not api.runs


@pytest.mark.parametrize('changes', [
    {'aud': 'another-service'}, {'artifact_id': '../private/file'},
    {'artifact_id': None}, {'exp': None},
])
def test_invalid_signed_claims_rejected(api, changes):
    now = int(time.time())
    claims = {'artifact_id': str(uuid.uuid4()), 'aud': tokens.TOKEN_AUDIENCE,
              'iat': now, 'exp': now + 300, **changes}
    token = jwt.encode(claims, tokens._signing_key(), algorithm='HS256')
    status, _ = post(api.app, '/api/v1/simulation/run', {'simulation_token': token})
    assert status == 401 and not api.runs


def test_default_signing_secret_cannot_issue_guest_capability(api, monkeypatch):
    monkeypatch.setattr(tokens.settings, 'JWT_SECRET_KEY', 'change-me-jwt-secret')
    status, _ = compile_guest(api)
    assert status == 503 and not api.storage
