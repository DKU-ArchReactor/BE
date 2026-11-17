import asyncio
import uuid
from types import SimpleNamespace
from unittest.mock import Mock, AsyncMock
import pytest
from fastapi import HTTPException
from app.schemas.assistant import ChatRequest
from app.services.tutor import context
from app.models.build import BuildStatus


def request(**kw):
    return ChatRequest(messages=[{'role':'user','content':'왜 스톨인가요?'}], execution={
        'build_id': str(uuid.uuid4()), 'history_index': 0, **kw})


@pytest.fixture
def setup(monkeypatch):
    record = SimpleNamespace(status=BuildStatus.success, binary_key='owned.elf')
    monkeypatch.setattr(context, 'owned_build', lambda *a: record)
    download = Mock(return_value=b'ELF')
    run = AsyncMock(return_value={'execution_id':'rerun-id','core_version':'1',
        'result':{'summary':{}, 'history':[{'clock':1,'cycle_events':{}}]}})
    monkeypatch.setattr(context,'download_bytes',download)
    monkeypatch.setattr(context,'run_simulation',run)
    return record, download, run


def test_context_is_server_rerun(setup):
    result = asyncio.run(context.resolve_context(request(), Mock(), Mock()))
    assert 'server_rerun_not_original_execution' in result.messages[0].content
    assert 'rerun-id' in result.messages[0].content
    assert result.execution is None
    assert result.messages[-1].content == '왜 스톨인가요?'


def test_wrong_owner_never_downloads(setup, monkeypatch):
    def denied(*args):
        raise HTTPException(403, 'Access denied')
    monkeypatch.setattr(context,'owned_build',denied)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(context.resolve_context(request(), Mock(), Mock()))
    assert exc.value.status_code == 403
    setup[1].assert_not_called()
    setup[2].assert_not_called()


def test_index_outside_result(setup):
    with pytest.raises(HTTPException) as exc:
        asyncio.run(context.resolve_context(request(history_index=10), Mock(), Mock()))
    assert exc.value.status_code == 422


def test_context_too_large(setup):
    setup[2].return_value['result']['history'][0]['data'] = 'x'*8000
    with pytest.raises(HTTPException) as exc:
        asyncio.run(context.resolve_context(request(), Mock(), Mock()))
    assert exc.value.status_code == 413
