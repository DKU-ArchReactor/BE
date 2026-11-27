"""Allocator behavior on the host, plus real RV32 compilation/engine execution."""
import ctypes
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from app.models.build import BuildStatus
from app.services.build_service import compile_source

RUNTIME = Path(__file__).resolve().parents[1] / 'app/services/rv32im'


@pytest.fixture
def allocator(tmp_path):
    compiler = shutil.which('cc')
    if not compiler:
        pytest.skip('host C compiler required')
    library = tmp_path / 'allocator.so'
    command = [compiler, '-shared', '-fPIC', '-O2', '-fno-builtin', '-fno-strict-aliasing',
               '-DARCHREACTOR_HOST_TEST', '-Dmalloc=ar_malloc', '-Dcalloc=ar_calloc',
               '-Drealloc=ar_realloc', '-Dfree=ar_free', str(RUNTIME / 'allocator.c'), '-o', str(library)]
    subprocess.run(command, check=True, capture_output=True)
    lib = ctypes.CDLL(str(library))
    lib.ar_malloc.argtypes = [ctypes.c_size_t]
    lib.ar_malloc.restype = ctypes.c_void_p
    lib.ar_calloc.argtypes = [ctypes.c_size_t, ctypes.c_size_t]
    lib.ar_calloc.restype = ctypes.c_void_p
    lib.ar_realloc.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
    lib.ar_realloc.restype = ctypes.c_void_p
    lib.ar_free.argtypes = [ctypes.c_void_p]
    lib.ar_free.restype = None
    return lib


def test_alignment_exhaustion_and_zero_size(allocator):
    lib = allocator
    assert not lib.ar_malloc(0)
    lib.ar_free(None)
    assert not lib.ar_malloc(ctypes.c_size_t(-1).value)
    ptr = lib.ar_malloc(4080)
    assert ptr and ptr % 16 == 0
    assert not lib.ar_malloc(1)
    lib.ar_free(ptr)
    for size in [1, 15, 16, 17, 31, 3000]:
        ptr = lib.ar_malloc(size)
        assert ptr and ptr % 16 == 0
        lib.ar_free(ptr)


def test_free_reuses_and_coalesces_neighbors(allocator):
    lib = allocator
    first, second, third = [lib.ar_malloc(100) for _ in range(3)]
    ctypes.memset(third, 0xA5, 100)
    lib.ar_free(first)
    lib.ar_free(second)
    merged = lib.ar_malloc(200)
    assert merged == first
    assert ctypes.string_at(third, 100) == b'\xa5' * 100
    lib.ar_free(third)
    lib.ar_free(merged)
    assert lib.ar_malloc(4080) == first


def test_calloc_clears_reused_memory_and_checks_overflow(allocator):
    lib = allocator
    ptr = lib.ar_malloc(64)
    ctypes.memset(ptr, 0xFF, 64)
    lib.ar_free(ptr)
    cleared = lib.ar_calloc(16, 4)
    assert cleared == ptr and ctypes.string_at(cleared, 64) == bytes(64)
    assert not lib.ar_calloc(ctypes.c_size_t(-1).value, 2)
    assert not lib.ar_calloc(2, ctypes.c_size_t(-1).value)
    assert not lib.ar_calloc(0, 8)
    assert not lib.ar_calloc(8, 0)


def test_realloc_preserves_data_and_failure_keeps_original(allocator):
    lib = allocator
    ptr = lib.ar_realloc(None, 32)
    ctypes.memmove(ptr, bytes(range(32)), 32)
    grown = lib.ar_realloc(ptr, 80)
    assert grown and ctypes.string_at(grown, 32) == bytes(range(32))
    assert not lib.ar_realloc(grown, 4096)
    assert ctypes.string_at(grown, 32) == bytes(range(32))
    assert lib.ar_realloc(grown, 16) == grown
    assert not lib.ar_realloc(grown, 0)
    assert lib.ar_malloc(4080)


PROGRAM = '''#include <stdlib.h>
volatile int total;
static int *values;
int main(void) {
    values = calloc(2, sizeof(int));
    if (values == NULL) return 1;
    if (values[0] != 0) return 2;
    values[0] = 20;
    values[1] = 22;
    int *grown = realloc(values, 4 * sizeof(int));
    if (grown == NULL) { free(values); return 3; }
    values = grown;
    total = values[0] + values[1];
    free(values);
    int *again = malloc(2 * sizeof(int));
    if (again == NULL) return 4;
    again[0] = total;
    int result = again[0];
    free(again);
    return result;
}
'''


@pytest.fixture
def rv32_binary():
    if not shutil.which(os.environ.get('RISCV_CC', 'riscv64-unknown-elf-gcc')):
        pytest.skip('RISC-V compiler required')
    result = compile_source(PROGRAM, 'c', '-O0 -Wall -Werror', 'rv32im')
    assert result.status == BuildStatus.success, result.log
    assert result.binary[:6] == b'\x7fELF\x01\x01'
    return result.binary


def test_rv32_runtime_links_heap(rv32_binary):
    from io import BytesIO
    from elftools.elf.elffile import ELFFile
    elf = ELFFile(BytesIO(rv32_binary))
    symbols = elf.get_section_by_name('.symtab')
    assert symbols.get_symbol_by_name('__archreactor_heap_start')[0]['st_value'] == 0x10004000
    assert symbols.get_symbol_by_name('__archreactor_heap_end')[0]['st_value'] == 0x10005000
    supported = {'.text', '.rodata', '.data', '.sdata', '.bss', '.sbss'}
    assert all(not section['sh_flags'] & 2 or not section['sh_size'] or section.name in supported
               for section in elf.iter_sections())


def test_optional_header_and_unused_runtime_removal(rv32_binary):
    from io import BytesIO
    from elftools.elf.elffile import ELFFile
    for source in [PROGRAM.replace('#include <stdlib.h>\n', ''),
                   'volatile int x=42; int main(void){return x;}']:
        result = compile_source(source, 'c', '-O0 -Wall -Werror', 'rv32im')
        assert result.status == BuildStatus.success, result.log
        elf = ELFFile(BytesIO(result.binary))
        if 'malloc' not in source:
            assert not elf.get_section_by_name('.symtab').get_symbol_by_name('malloc')
        if result.analysis:
            assert all(1 <= int(line) <= len(source.splitlines()) for line in result.analysis['source_map'])


@pytest.mark.parametrize('mode', ['single', 'pipeline'])
def test_real_core_executes_all_four_allocators(rv32_binary, tmp_path, mode):
    source = os.environ.get('CORE_SOURCE')
    if not source:
        pytest.skip('Set CORE_SOURCE for real CORE execution')
    elf = tmp_path / 'heap.elf'
    elf.write_bytes(rv32_binary)
    script = '''
import json, sys
from app.state import create_state, delete_state
from app.simulator import run_simulation
binary = open(sys.argv[1], 'rb').read()
state = create_state('allocation-test', binary, mode=sys.argv[2])
result = run_simulation('allocation-test', max_cycles=2000)
print(json.dumps({'status': result['status'], 'a0': state['regs'][10],
                  'cycles': result['summary']['total_cycles'],
                  'payload_bytes': len(json.dumps(result, separators=(',', ':')).encode())}))
delete_state('allocation-test')
'''
    process = subprocess.run([sys.executable, '-c', script, str(elf), mode], cwd=source,
                             capture_output=True, text=True, timeout=30)
    assert process.returncode == 0, process.stderr
    result = json.loads(process.stdout)
    assert result['status'] == 'halted', result
    assert result['a0'] == 42, result
    assert result['payload_bytes'] < 8 * 1024 * 1024 - 1024, result
