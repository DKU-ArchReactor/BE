"""Bounded compiler process execution. This is not an OS security sandbox."""
import os
import signal
import shutil
import subprocess
import sys
import tempfile
import time

MAX_OUTPUT = 4 * 1024 * 1024


def run_command(command: list[str], timeout: float = 10) -> subprocess.CompletedProcess:
    executable = command
    if sys.platform.startswith('linux'):
        limiter = shutil.which('prlimit')
        if limiter is None:
            return subprocess.CompletedProcess(command, 127, '', 'prlimit is required on Linux')
        executable = [limiter, '--as=536870912', '--fsize=8388608', '--cpu=10', '--nofile=64', '--', *command]
    with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
        try:
            process = subprocess.Popen(executable, stdout=stdout, stderr=stderr,
                start_new_session=True, env={'PATH': os.environ.get('PATH', '/usr/bin:/bin'), 'LANG': 'C', 'TMPDIR': tempfile.gettempdir()})
        except FileNotFoundError:
            return subprocess.CompletedProcess(command, 127, '', 'Required compiler tool is not installed')
        reason = None
        deadline = time.monotonic() + timeout
        try:
            while process.poll() is None:
                if time.monotonic() >= deadline:
                    reason = f'timeout after {timeout}s'
                    break
                if os.fstat(stdout.fileno()).st_size + os.fstat(stderr.fileno()).st_size > MAX_OUTPUT:
                    reason = 'compiler output limit exceeded'
                    break
                time.sleep(0.02)
        finally:
            # Kill descendants even if their parent exited first.
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
        stdout.seek(0)
        stderr.seek(0)
        out = stdout.read(MAX_OUTPUT + 1)
        err = stderr.read(MAX_OUTPUT + 1)
        if len(out) + len(err) > MAX_OUTPUT:
            reason = 'compiler output limit exceeded'
        return subprocess.CompletedProcess(command, 124 if reason else process.returncode,
            out[:MAX_OUTPUT].decode('utf-8', errors='replace'),
            reason or err[:MAX_OUTPUT].decode('utf-8', errors='replace'))
