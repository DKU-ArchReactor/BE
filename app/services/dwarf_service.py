"""Extract DWARF line number mapping from ELF binaries."""
from __future__ import annotations

import io
from typing import Dict, Optional


def extract_pc_to_line_map(elf_bytes: bytes) -> Dict[str, int]:
    """
    ELF 바이너리의 .debug_line DWARF 섹션에서 PC -> C Source Line 매핑 딕셔너리를 추출한다.
    오직 사용자 C 소스(source.c)에 속한 라인만 추출하고, start.S 등 런타임 파일은 제외한다.
    반환 키 형식: '0x00010018'
    """
    pc_map: Dict[str, int] = {}
    try:
        from elftools.elf.elffile import ELFFile
    except ImportError:
        return pc_map

    try:
        stream = io.BytesIO(elf_bytes)
        elf = ELFFile(stream)
        if not elf.has_dwarf_info():
            return pc_map

        dwarfinfo = elf.get_dwarf_info()
        for cu in dwarfinfo.iter_CUs():
            lineprog = dwarfinfo.line_program_for_CU(cu)
            if lineprog is None:
                continue

            file_entries = lineprog["file_entry"]
            # file_entries[0] 또는 file_idx로 파일명 확인
            entries = lineprog.get_entries()
            prev_state = None
            for entry in entries:
                state = entry.state
                if state is None:
                    continue
                if prev_state and not prev_state.end_sequence and prev_state.line > 0:
                    # 파일명 검사: source.c 에 속하는 경우만 매핑 (start.S 등은 CRT로 취급하기 위해 None)
                    is_source_c = False
                    try:
                        file_idx = prev_state.file - 1
                        if 0 <= file_idx < len(file_entries):
                            fname = file_entries[file_idx].name.decode("utf-8", errors="ignore")
                            if "source.c" in fname:
                                is_source_c = True
                    except Exception:
                        pass

                    if is_source_c:
                        curr_addr = prev_state.address
                        end_addr = state.address if state.address > curr_addr else curr_addr + 4
                        while curr_addr < end_addr:
                            pc_key = f"0x{curr_addr & 0xFFFFFFFF:08X}".lower()
                            pc_map[pc_key] = prev_state.line
                            curr_addr += 4
                prev_state = state
    except Exception:
        pass

    return pc_map


def enrich_simulation_history_with_mapping(result: dict, elf_bytes: bytes) -> dict:
    """
    시뮬레이션 결과 JSON에 PC 기반 C Source Line 번호를 주입한다.
    이미 CORE 엔진에서 source_line이 제공된 경우 덮어쓰지 않고 유지한다.
    """
    if not isinstance(result, dict) or "history" not in result or not isinstance(result["history"], list):
        return result

    history = result["history"]
    if not history:
        return result

    # 1. CORE 엔진에서 이미 source_line을 제공하고 있는지 샘플 검사
    first_buffers = history[0].get("buffers") if isinstance(history[0], dict) else None
    if isinstance(first_buffers, dict):
        has_core_mapping = any(
            isinstance(buf, dict) and "source_line" in buf and buf["source_line"] is not None
            for buf in first_buffers.values()
        )
        if has_core_mapping:
            # 이미 코어가 자체 매핑 정보를 제공하므로 그대로 반환 (Future-proof)
            return result

    # 2. 코어 엔진에 매핑 정보가 없으므로 ELF DWARF 정보에서 매핑 테이블 추출
    pc_map = extract_pc_to_line_map(elf_bytes)
    if not pc_map:
        return result

    # 3. 각 사이클 버퍼(buffers, stage_activity, if_stage 등)에 source_line 주입
    for cycle_item in history:
        if not isinstance(cycle_item, dict):
            continue

        target_containers = []
        if isinstance(cycle_item.get("buffers"), dict):
            target_containers.append(cycle_item["buffers"])
        if isinstance(cycle_item.get("stage_activity"), dict):
            target_containers.append(cycle_item["stage_activity"])
        for stg in ("if_stage", "id_stage", "ex_stage", "mem_stage", "wb_stage"):
            if isinstance(cycle_item.get(stg), dict):
                target_containers.append({stg: cycle_item[stg]})

        for container in target_containers:
            for buf in container.values():
                if not isinstance(buf, dict):
                    continue
                # 이미 채워져 있다면 보존
                if "source_line" in buf and buf["source_line"] is not None:
                    continue

                raw_pc = buf.get("pc")
                if not raw_pc or not isinstance(raw_pc, str):
                    buf["source_line"] = None
                    continue

                clean_pc = raw_pc.strip().lower()
                if not clean_pc.startswith("0x"):
                    clean_pc = f"0x{clean_pc}"
                try:
                    num = int(clean_pc, 16)
                    norm_pc = f"0x{num:08x}"
                    buf["source_line"] = pc_map.get(norm_pc, None)
                except ValueError:
                    buf["source_line"] = None

    return result
