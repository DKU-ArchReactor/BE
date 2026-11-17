import uuid
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.build import BuildStatus
from app.routers import build
from app.services.binary.inspect import inspect_elf, InspectionError, parse_disassembly


@pytest.fixture
def api():
    uid = 'owner'
    record = SimpleNamespace(build_id=uuid.uuid4(), file_id=uuid.uuid4(),
        file=SimpleNamespace(project=SimpleNamespace(user_id=uid)),
        log='combined', stdout='out', stderr='err', status=BuildStatus.success, binary_key='private/build.elf')
    db = Mock()
    db.get.return_value = record
    app = FastAPI()
    app.include_router(build.router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(user_id=uid)
    return TestClient(app), record, db


def test_logs_preserve_streams_and_legacy(api):
    client, record, _ = api
    url = f'/api/v1/build/logs?build_id={record.build_id}'
    response = client.get(url)
    assert response.status_code == 200
    assert response.json()['stderr'] == 'err'
    assert response.json()['streams_available']
    record.stdout = record.stderr = None
    result = client.get(url).json()
    assert result['log'] == 'combined' and result['stdout'] is None
    assert not result['streams_available']


@pytest.mark.parametrize('path', ['logs', 'objdump'])
def test_private_builds_and_missing(api, path):
    client, record, db = api
    record.file.project.user_id = 'other'
    url = f'/api/v1/build/{path}?build_id={record.build_id}'
    assert client.get(url).status_code == 403
    db.get.return_value = None
    assert client.get(url).status_code == 404


def test_disassembly_success_and_failed_build(api, monkeypatch):
    client, record, _ = api
    download = Mock(return_value=b'elf')
    monkeypatch.setattr(build, 'download_bytes', download)
    monkeypatch.setattr(build, 'inspect_elf', lambda binary: dict(disassembly='asm', instructions=[],
        source_map={}, sections=[], mapping_available=False))
    url = f'/api/v1/build/objdump?build_id={record.build_id}'
    assert client.get(url).json()['disassembly'] == 'asm'
    record.status = BuildStatus.failed
    assert client.get(url).status_code == 409
    assert download.call_count == 1


def test_mapping_one_to_many_and_startup_excluded():
    result = parse_disassembly('''00010000 <_start>:
/app/start.S:4
 10000: 00000013 nop
00010004 <main>:
/tmp/source.c:2
 10004: 00100513 li a0,1
 10008: 00008067 ret
0001000c <helper>:
 1000c: 00008067 ret
''')
    assert result['source_map'] == {'2': ['0x00010004', '0x00010008']}
    assert result['instructions'][0]['source_line'] is None
    assert result['instructions'][-1]['source_line'] is None


@pytest.mark.parametrize('data', [b'', b'not elf', b'x' * (256 * 1024 + 1)])
def test_invalid_elf_rejected_without_tool(data):
    with pytest.raises(InspectionError):
        inspect_elf(data)
