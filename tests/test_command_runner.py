import sys
from app.services.command_runner import run_command


def test_timeout_and_stream_capture():
    result = run_command([sys.executable, '-c', 'import time; print("before", flush=True); time.sleep(5)'], timeout=.1)
    assert result.returncode == 124
    assert 'before' in result.stdout
    assert 'timeout' in result.stderr


def test_parent_environment_not_forwarded(monkeypatch):
    monkeypatch.setenv('COMPILER_TEST_PRIVATE_VALUE', 'must-not-inherit')
    result = run_command([sys.executable, '-c', 'import os; print(os.getenv("COMPILER_TEST_PRIVATE_VALUE", "absent"))'])
    assert result.returncode == 0
    assert result.stdout.strip() == 'absent'


def test_large_output_is_rejected():
    result = run_command([sys.executable, '-c', 'print("x" * (5 * 1024 * 1024))'])
    assert result.returncode == 124
    assert 'output limit' in result.stderr
