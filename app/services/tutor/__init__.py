"""Read-only deterministic tutor. No model calls or simulation state changes."""
import hashlib
from app.schemas.tutor import ExplainItem
from app.services.tutor.rules import explain


def compile_explanations(source: str, lang: str, assembly: str | None) -> dict:
    entries = []
    if lang.lower() == 'c':
        for line, text in enumerate(source.splitlines(), 1):
            entries.append({'line': line, 'text': text, 'explanation': explain(ExplainItem(kind='c', text=text[:4096], line=line)).model_dump()})
    instructions = []
    for line, text in enumerate((assembly or '').splitlines(), 1):
        if text.strip():
            instructions.append({'line': line, 'text': text, 'explanation': explain(ExplainItem(kind='asm', text=text[:4096], line=line)).model_dump()})
    return {'schema_version': '1.0', 'source_sha256': hashlib.sha256(source.encode()).hexdigest(),
            'c_lines': entries, 'asm_instructions': instructions}


def simulation_explanations(result: dict) -> dict:
    instructions = []
    mapping = (result.get('program') or {}).get('code_mapping') or {}
    for pc, entry in mapping.items():
        if not isinstance(entry, dict) or not entry.get('assembly'):
            continue
        text = entry['assembly']
        kind = 'crt' if entry.get('source_line') is None else 'asm'
        instructions.append({'pc': pc, 'text': text, 'source_line': entry.get('source_line'),
            'explanation': explain(ExplainItem(kind='asm', text=text[:4096])).model_dump(),
            'runtime_explanation': explain(ExplainItem(kind=kind, text=text[:4096], pc=str(pc)[:32])).model_dump() if kind == 'crt' else None})
    cycles = []
    for index, cycle in enumerate(result.get('history', [])):
        if not isinstance(cycle, dict):
            continue
        events = cycle.get('cycle_events') or {}
        explanations = []
        for name, flag, kind, title, description, fallback in (
            ('stall', 'has_stall', 'stall', '데이터 해저드 / 스톨', 'stall_desc', 'CORE가 스톨을 보고했습니다. 구체적인 원인 정보는 제공되지 않았습니다.'),
            ('forwarding', 'has_forwarded', 'forwarding', '데이터 포워딩', 'forwarding_desc', 'CORE가 피연산자 포워딩을 보고했습니다. 전달 경로는 이벤트 근거를 확인하세요.'),
            ('control_hazard', 'has_flush', 'flush', '제어 흐름 변경 / 플러시', 'flush_reason', 'CORE가 플러시를 보고했습니다. 구체적인 원인 정보는 제공되지 않았습니다.'),
        ):
            evidence = events.get(name) or {}
            if evidence.get(flag) is not True:
                continue
            reason = evidence.get(description)
            detail = reason or fallback
            if kind == 'flush' and reason == 'control_hazard_branch_taken':
                detail = '분기 또는 점프로 실행 흐름이 변경되어 후속 명령어를 비웁니다.'
                if evidence.get('flushed_stages'):
                    detail += ' 비운 단계: ' + ', '.join(evidence['flushed_stages']) + '.'
                if evidence.get('redirect_pc'):
                    detail += ' 이동 PC: ' + str(evidence['redirect_pc']) + '.'
            explanations.append({'type': kind, 'title': title, 'summary': detail,
                                 'detail': detail, 'evidence': evidence})
        if explanations:
            cycles.append({'history_index': index, 'cycle': cycle.get('clock'), 'events': explanations})
    return {'schema_version': '1.0', 'asm_instructions': instructions, 'cycle_explanations': cycles}
