"""Static ELF inspection only. Runtime pipeline state remains owned by CORE."""
import os
import re
from app.services.command_runner import run_command
import tempfile
from pathlib import Path

MAX_ELF = 256 * 1024
MAX_OUTPUT = 4 * 1024 * 1024


class InspectionError(Exception):
    pass


def parse_disassembly(text: str) -> dict:
    instructions = []
    source_map = {}
    source_line = None
    source_file = None
    for line in text.splitlines():
        if re.match(r'^\s*[0-9a-fA-F]+ <.*>:$', line):
            source_line = source_file = None
        location = re.match(r'^(.*\.(?:c|s|S)):(\d+)(?:\s.*)?$', line.strip())
        if location:
            source_file = Path(location[1]).name
            source_line = int(location[2]) or None
            continue
        instruction = re.match(r'^\s*([0-9a-fA-F]+):\s+[0-9a-fA-F]{4,8}\s+(.+)$', line)
        if not instruction:
            continue
        pc = f'0x{int(instruction[1], 16):08x}'
        # Startup code must not be assigned to the user's source file.
        mapped_line = source_line if source_file == 'source.c' else None
        instructions.append({'pc': pc, 'assembly': instruction[2].strip(),
                             'source_line': mapped_line, 'source_file': source_file})
        if mapped_line is not None:
            source_map.setdefault(str(mapped_line), []).append(pc)
    return {'instructions': instructions, 'source_map': source_map,
            'mapping_available': bool(source_map)}


def inspect_elf(binary: bytes) -> dict:
    if len(binary) > MAX_ELF:
        raise InspectionError('ELF exceeds 256 KiB')
    if len(binary) < 52 or binary[:6] != b'\x7fELF\x01\x01' or int.from_bytes(binary[18:20], 'little') != 243:
        raise InspectionError('Expected a little-endian ELF32 RISC-V binary')
    tool = os.environ.get('RISCV_OBJDUMP', 'riscv64-unknown-elf-objdump')
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / 'program.elf'
        path.write_bytes(binary)
        result = run_command([tool, '-d', '-l', '-h', str(path)])
        if result.returncode == 127:
            raise InspectionError('RISC-V objdump or resource limiter is not installed')
        if result.returncode == 124:
            raise InspectionError('ELF inspection exceeded time or output limits')
        if result.returncode:
            raise InspectionError('Invalid or unsupported ELF')
        if len(result.stdout) > MAX_OUTPUT:
            raise InspectionError('Disassembly exceeds output limit')
        text = result.stdout.replace(directory + '/', '')
    sections = []
    for line in text.splitlines():
        match = re.match(r'^\s*\d+\s+(\S+)\s+([0-9a-fA-F]+)\s+([0-9a-fA-F]+)\s+', line)
        if match:
            sections.append({'name': match[1], 'size': int(match[2], 16),
                             'address': f'0x{int(match[3], 16):08x}'})
    return {'disassembly': text, 'sections': sections, **parse_disassembly(text)}
