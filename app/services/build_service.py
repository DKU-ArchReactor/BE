import shlex
import os
import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from app.core.storage import upload_bytes
from app.models.build import BuildStatus
from app.services.binary import process_binary
from app.services.basic_c import validate_basic_c

COMPILE_TIMEOUT_SEC = 10
SUPPORTED_LANGS = {"c", "asm"}


class UnsupportedOptionsError(ValueError):
    pass


class UnsupportedLanguageError(Exception):
    pass


@dataclass
class CompileResult:
    status: BuildStatus
    log: str
    assembly: str | None
    binary: bytes | None
    stdout: str | None = None
    stderr: str | None = None
    analysis: dict | None = None
    analysis_error: str | None = None
    diagnostics: list[dict] | None = None


def compile_source(content: str, lang: str, compiler_opt: str, compile_profile: str = "native") -> CompileResult:
    """소스를 임시 디렉토리에서 gcc로 컴파일해 어셈블리/ELF/로그를 반환."""
    lang = lang.lower()
    if lang not in SUPPORTED_LANGS:
        raise UnsupportedLanguageError(f"Unsupported lang: {lang}")

    opt_tokens = shlex.split(compiler_opt) if compiler_opt else []

    if any(not re.fullmatch(r"-(?:O[0-3sg]|Wall|Wextra|Werror|g|std=(?:c99|c11|c17|gnu11))", token) for token in opt_tokens):
        raise UnsupportedOptionsError("Unsupported compiler option")
    if compile_profile not in {"native", "rv32im"}:
        raise UnsupportedOptionsError("Unsupported compile profile")
    if lang == 'c' and compile_profile == 'rv32im':
        diagnostics = validate_basic_c(content)
        if diagnostics:
            log = '\n'.join(f"{d['line']}행 {d['column']}열: {d['message']}" for d in diagnostics)
            return CompileResult(BuildStatus.failed, log, None, None,
                                 stdout='', stderr=log, diagnostics=diagnostics)
    compiler = os.environ.get("RISCV_CC", "riscv64-unknown-elf-gcc") if compile_profile == "rv32im" else "gcc"
    profile_flags = (["-g", "-march=rv32im", "-mabi=ilp32", "-O0", "-ffreestanding", "-nostdlib",
                      "-nostartfiles", "-fno-pic", "-fno-pie", "-fno-builtin", "-fno-inline",
                      "-msmall-data-limit=0", "-gdwarf-4"] if compile_profile == "rv32im" else [])
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        src_name = "source.c" if lang == "c" else "source.s"
        src_path = tmp_path / src_name
        asm_path = tmp_path / "source.s"
        elf_path = tmp_path / "source.elf"

        src_path.write_text(content)

        log_parts: list[str] = []
        outputs: list[str] = []
        errors: list[str] = []

        # ELF 바이너리 생성
        link_flags = []
        inputs = [str(src_path)]
        if compile_profile == "rv32im":
            runtime = Path(__file__).parent / "rv32im"
            link_flags = ["-Wl,--no-relax", "-Wl,-T," + str(runtime / "link.ld")]
            # C entry is _start -> main -> ecall 10; assembly defines _start itself.
            if lang == "c":
                allocator = tmp_path / 'allocator.o'
                runtime_cmd = [compiler, '-march=rv32im', '-mabi=ilp32', '-O2', '-g', '-gdwarf-4',
                               '-ffreestanding', '-fno-builtin', '-fno-strict-aliasing',
                               '-fno-tree-loop-distribute-patterns',
                               '-fno-pic', '-fno-pie', '-msmall-data-limit=0',
                               '-ffunction-sections', '-fdata-sections',
                               '-c', str(runtime / 'allocator.c'), '-o', str(allocator)]
                runtime_proc = _run(runtime_cmd)
                log_parts.append(_format_log(runtime_cmd, runtime_proc))
                outputs.append(runtime_proc.stdout)
                errors.append(runtime_proc.stderr)
                if runtime_proc.returncode:
                    return CompileResult(BuildStatus.failed, '\n'.join(log_parts), None, None,
                                         stdout='\n'.join(outputs), stderr='\n'.join(errors))
                # Force the trusted declarations even when users omit the optional
                # include. User preprocessing is restricted by validate_basic_c.
                profile_flags += ['-I', str(runtime / 'include')]
                src_path.write_text('#include <stdlib.h>\n#line 1 "' + str(src_path) + '"\n' + content)
                link_flags += ['-Wl,--gc-sections']
                inputs.insert(0, str(runtime / "start.S"))
                inputs.append(str(allocator))
        bin_cmd = [compiler, *profile_flags, *opt_tokens, *link_flags, "-o", str(elf_path), *inputs]
        bin_proc = _run(bin_cmd)
        log_parts.append(_format_log(bin_cmd, bin_proc))
        outputs.append(bin_proc.stdout)
        errors.append(bin_proc.stderr)
        if bin_proc.returncode != 0:
            return CompileResult(
                status=BuildStatus.failed,
                log="\n".join(log_parts),
                stdout="\n".join(outputs), stderr="\n".join(errors),
                assembly=asm_path.read_text() if asm_path.exists() else None,
                binary=None,
            )

        assembly = asm_path.read_text() if asm_path.exists() else None
        binary = elf_path.read_bytes()
        analysis = None
        analysis_error = None
        if compile_profile == "rv32im":
            from app.services.binary.inspect import inspect_elf, InspectionError
            try:
                analysis = inspect_elf(binary)
            except InspectionError as error:
                analysis_error = str(error)
        return CompileResult(
            status=BuildStatus.success,
            log="\n".join(log_parts),
            stdout="\n".join(outputs), stderr="\n".join(errors),
            assembly=assembly,
            binary=binary, analysis=analysis, analysis_error=analysis_error,
        )


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    from app.services.command_runner import run_command
    return run_command(cmd, COMPILE_TIMEOUT_SEC)


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
