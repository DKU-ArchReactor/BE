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


def test_private_builds_and_missing(api):
    client, record, db = api
    record.file.project.user_id = 'other'
    url = f'/api/v1/build/logs?build_id={record.build_id}'
    assert client.get(url).status_code == 403
    db.get.return_value = None
    assert client.get(url).status_code == 404


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
    assert result['instructions'][0]['runtime_context']['function'] == '_start'
    assert result['instructions'][-1]['runtime_context'] is None


def test_runtime_context_requires_matching_function_and_source_evidence():
    result = parse_disassembly('''00010000 <malloc>:
/runtime/allocator.c:32
 10000: 00000013 nop
00010004 <free>:
/runtime/allocator.c:57
 10004: 00008067 ret
00010008 <malloc>:
/tmp/source.c:2
 10008: 00000013 nop
0001000c <_start>:
 1000c: 00000013 nop
00010010 <unknown>:
/runtime/allocator.c:60
 10010: 00000013 nop
''')
    items = result['instructions']
    assert items[0]['runtime_context']['label'] == 'malloc 내부'
    assert items[1]['runtime_context']['label'] == 'free 내부'
    assert '이전 값이 남을 수' in items[1]['runtime_context']['detail']
    assert all(item['runtime_context'] is None for item in items[2:])
    assert result['source_map'] == {'2': ['0x00010008']}


@pytest.mark.parametrize('data', [b'', b'not elf', b'x' * (256 * 1024 + 1)])
def test_invalid_elf_rejected_without_tool(data):
    with pytest.raises(InspectionError):
        inspect_elf(data)


def test_compile_keeps_single_user_source_pass_dwarf4_and_nonfatal_inspection(monkeypatch):
    import subprocess
    from pathlib import Path
    from app.services import build_service
    from app.services.binary import inspect as inspector
    calls = []
    def compile_command(command):
        calls.append(command)
        Path(command[command.index('-o') + 1]).write_bytes(b'elf')
        return subprocess.CompletedProcess(command, 0, 'compiler stdout', 'compiler warning')
    def unavailable(binary):
        raise InspectionError('inspection unavailable')
    monkeypatch.setattr(build_service, '_run', compile_command)
    monkeypatch.setattr(inspector, 'inspect_elf', unavailable)
    result = build_service.compile_source('int main(){return 0;}', 'c', '-O2', 'rv32im')
    assert len(calls) == 2
    assert all('-S' not in command and '-gdwarf-4' in command for command in calls)
    assert '-c' in calls[0] and any(path.endswith('/allocator.c') for path in calls[0])
    assert sum(any(path.endswith('/source.c') for path in command) for command in calls) == 1
    assert result.status == BuildStatus.success and result.binary == b'elf'
    assert result.stdout == 'compiler stdout\ncompiler stdout'
    assert result.stderr == 'compiler warning\ncompiler warning'
    assert result.analysis is None and result.analysis_error == 'inspection unavailable'
