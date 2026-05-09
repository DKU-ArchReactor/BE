from unittest.mock import patch

import pytest

from app.models.build import BuildStatus
from app.services import build_service
from app.services.binary import process_binary


def test_process_binary_passthrough():
    assert process_binary(b"abc") == b"abc"
    assert process_binary(b"") == b""


def test_compile_source_success_for_valid_c():
    result = build_service.compile_source(
        content="int main(){return 0;}", lang="c", compiler_opt="-O2"
    )
    assert result.status == BuildStatus.success
    assert result.binary is not None and len(result.binary) > 0
    assert result.assembly is not None and len(result.assembly) > 0


def test_compile_source_failure_logs_error():
    result = build_service.compile_source(
        content="int main(){ return undeclared_thing; }",
        lang="c",
        compiler_opt="",
    )
    assert result.status == BuildStatus.failed
    assert result.binary is None
    assert "undeclared" in result.log or "error" in result.log.lower()


def test_compile_source_unsupported_lang_raises():
    with pytest.raises(build_service.UnsupportedLanguageError):
        build_service.compile_source(content="x", lang="rust", compiler_opt="")


def test_upload_compile_artifacts_routes_through_process_binary_hook():
    result = build_service.CompileResult(
        status=BuildStatus.success,
        log="",
        assembly="X",
        binary=b"ORIG",
    )
    with patch("app.services.build_service.upload_bytes") as up, patch(
        "app.services.build_service.process_binary", return_value=b"TRANSFORMED"
    ) as hook:
        upload_compile_artifacts = build_service.upload_compile_artifacts
        asm_key, bin_key = upload_compile_artifacts("builds/test", result)

    hook.assert_called_once_with(b"ORIG")
    # 어셈블리 + 바이너리 두 번 업로드됨, 두 번째 호출(바이너리)에 변환된 바이트 전달
    assert up.call_count == 2
    assert up.call_args_list[-1].args[1] == b"TRANSFORMED"
    assert asm_key == "builds/test/assembly.s"
    assert bin_key == "builds/test/binary.elf"


def test_upload_compile_artifacts_skips_on_failure():
    result = build_service.CompileResult(
        status=BuildStatus.failed,
        log="error",
        assembly=None,
        binary=None,
    )
    with patch("app.services.build_service.upload_bytes") as up:
        asm_key, bin_key = build_service.upload_compile_artifacts(
            "builds/test", result
        )
    up.assert_not_called()
    assert asm_key is None and bin_key is None
