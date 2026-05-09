import shlex
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from app.core.storage import upload_bytes
from app.models.build import BuildStatus
from app.services.binary import process_binary

COMPILE_TIMEOUT_SEC = 10
SUPPORTED_LANGS = {"c", "asm"}


class UnsupportedLanguageError(Exception):
    pass


@dataclass
class CompileResult:
    status: BuildStatus
    log: str
    assembly: str | None
    binary: bytes | None


def compile_source(content: str, lang: str, compiler_opt: str) -> CompileResult:
    """소스를 임시 디렉토리에서 gcc로 컴파일해 어셈블리/ELF/로그를 반환."""
    lang = lang.lower()
    if lang not in SUPPORTED_LANGS:
        raise UnsupportedLanguageError(f"Unsupported lang: {lang}")

    opt_tokens = shlex.split(compiler_opt) if compiler_opt else []

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        src_name = "source.c" if lang == "c" else "source.s"
        src_path = tmp_path / src_name
        asm_path = tmp_path / "source.s"
        elf_path = tmp_path / "source.elf"

        src_path.write_text(content)

        log_parts: list[str] = []

        # 어셈블리 산출물 생성 (C는 -S, asm은 입력 자체가 어셈블리)
        if lang == "c":
            asm_cmd = ["gcc", "-S", *opt_tokens, "-o", str(asm_path), str(src_path)]
            asm_proc = _run(asm_cmd)
            log_parts.append(_format_log(asm_cmd, asm_proc))
            if asm_proc.returncode != 0:
                return CompileResult(
                    status=BuildStatus.failed,
                    log="\n".join(log_parts),
                    assembly=None,
                    binary=None,
                )

        # ELF 바이너리 생성
        bin_cmd = ["gcc", *opt_tokens, "-o", str(elf_path), str(src_path)]
        bin_proc = _run(bin_cmd)
        log_parts.append(_format_log(bin_cmd, bin_proc))
        if bin_proc.returncode != 0:
            return CompileResult(
                status=BuildStatus.failed,
                log="\n".join(log_parts),
                assembly=asm_path.read_text() if asm_path.exists() else None,
                binary=None,
            )

        assembly = asm_path.read_text() if asm_path.exists() else None
        binary = elf_path.read_bytes()
        return CompileResult(
            status=BuildStatus.success,
            log="\n".join(log_parts),
            assembly=assembly,
            binary=binary,
        )


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            cmd,
            shell=False,
            capture_output=True,
            text=True,
            timeout=COMPILE_TIMEOUT_SEC,
        )
    except subprocess.TimeoutExpired as e:
        return subprocess.CompletedProcess(
            cmd, returncode=124, stdout=e.stdout or "", stderr=f"timeout after {COMPILE_TIMEOUT_SEC}s"
        )
    except FileNotFoundError as e:
        return subprocess.CompletedProcess(
            cmd, returncode=127, stdout="", stderr=f"command not found: {e}"
        )


def _format_log(cmd: list[str], proc: subprocess.CompletedProcess) -> str:
    header = "$ " + " ".join(shlex.quote(c) for c in cmd)
    parts = [header]
    if proc.stdout:
        parts.append(proc.stdout.rstrip())
    if proc.stderr:
        parts.append(proc.stderr.rstrip())
    parts.append(f"[exit {proc.returncode}]")
    return "\n".join(parts)


def upload_compile_artifacts(
    prefix: str, result: CompileResult
) -> tuple[str | None, str | None]:
    """성공한 빌드의 어셈블리/바이너리를 S3에 업로드. (assembly_key, binary_key) 반환."""
    if result.status != BuildStatus.success:
        return None, None

    assembly_key = None
    binary_key = None
    if result.assembly is not None:
        assembly_key = f"{prefix}/assembly.s"
        upload_bytes(assembly_key, result.assembly.encode("utf-8"), "text/plain")
    if result.binary is not None:
        processed = process_binary(result.binary)
        binary_key = f"{prefix}/binary.elf"
        upload_bytes(binary_key, processed, "application/octet-stream")
    return assembly_key, binary_key
