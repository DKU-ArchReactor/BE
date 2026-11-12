"""Bounded snapshots from CORE, ownership checks and explicit per-question projection."""
from datetime import datetime, timedelta, timezone
import hashlib
import json
import re
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import delete, select

from app.core.config import settings
from app.models.assistant_execution import AssistantExecution
from app.models.user import User
from app.services.tutor import simulation_explanations

MAX_SNAPSHOT_BYTES = 2 * 1024 * 1024
MAX_PROMPT_BYTES = 16384
MAX_MEMORY_WORDS = 2048
STAGES = ('IF', 'ID', 'EX', 'MEM', 'WB')
METRICS = ('accumulated_instructions', 'accumulated_stalls', 'accumulated_forwards')
# Explicit keys, not recursive passthrough: console output, paths and buffers are excluded.
EVENT_FIELDS = {
    'stall': ('has_stall', 'stage', 'assembly', 'stall_reason', 'stall_desc'),
    'forwarding': ('has_forwarded', 'stage', 'assembly', 'forwarded_operand_count', 'forwarding_desc'),
    'control_hazard': ('has_control_instruction', 'has_flush', 'stage', 'assembly', 'taken',
                      'target_pc', 'fallthrough_pc', 'flushed_stages', 'flush_reason', 'redirect_pc'),
    'runtime_error': ('has_error', 'code', 'stage', 'assembly', 'reason'),
}
FORWARD_FIELDS = ('has_forwarded', 'forwarded_from', 'forwarded_to', 'target_register', 'forwarded_value')


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def word(value):
    if isinstance(value, str) and re.fullmatch(r'0x[0-9a-fA-F]{1,8}', value):
        value = int(value, 16)
    if type(value) is not int or not 0 <= value <= 0xffffffff:
        raise ValueError('Invalid RV32 word')
    return value


def hexword(value):
    return f'0x{value:08x}'


def memory_words(value):
    if not isinstance(value, dict) or len(value) > MAX_MEMORY_WORDS:
        raise ValueError('Unsupported memory snapshot')
    result = {}
    for address, data in value.items():
        address = word(address)
        if address % 4 or str(address) in result:
            raise ValueError('Invalid word address')
        result[str(address)] = word(data)
    return result


def small(value):
    if value is None or type(value) is bool:
        return value
    if type(value) is int and 0 <= value <= 0xffffffff:
        return value
    if isinstance(value, str) and len(value) <= 512:
        return value
    if isinstance(value, list) and len(value) <= 8:
        if any(isinstance(item, (list, dict)) for item in value):
            raise ValueError('Nested evidence arrays are unsupported')
        return [small(item) for item in value]
    raise ValueError('Unsupported evidence value')


def events(value):
    output = {}
    for name, fields in EVENT_FIELDS.items():
        entry = value.get(name, {})
        if not isinstance(entry, dict):
            raise ValueError('Invalid event')
        output[name] = {key: small(entry[key]) for key in fields if key in entry}
        if name == 'forwarding' and 'forwarding_info' in entry:
            info = entry['forwarding_info']
            output[name]['forwarding_info'] = {key: small(info[key]) for key in FORWARD_FIELDS if key in info}
    return output


def build_snapshot(response, elf):
    """Only called on server-produced results, never on a client-supplied trace."""
    result = response['result']
    if response['result_schema_version'] != '1.0' or result['schema_version'] != '1.0':
        raise ValueError('Unsupported CORE schema')
    history = result['history']
    if not 1 <= len(history) <= 2000 or result['summary']['total_cycles'] != len(history):
        raise ValueError('Invalid history size')
    mode = result['simulator']['mode']
    if mode not in ('single', 'pipeline'):
        raise ValueError('Invalid engine mode')
    initial_memory = memory_words(result['initial_state']['memory_snapshot'])
    previous_memory = initial_memory
    frames = []
    mappings = {}
    for index, cycle in enumerate(history):
        if type(cycle['clock']) is not int or cycle['clock'] != index:
            raise ValueError('Non-contiguous CORE clocks')
        state = cycle['global_result']
        registers = [word(state['registers'][f'x{i}']) for i in range(32)]
        metrics = {key: small(state['metrics'][key]) for key in METRICS}
        if any(type(v) is not int for v in metrics.values()):
            raise ValueError('Missing counters')
        current_memory = memory_words(state['memory_snapshot'])
        stage_data = {}
        for stage in STAGES:
            activity = cycle.get('stage_activity', {}).get(stage, {})
            stage_data[stage] = {key: small(activity[key]) for key in ('pc', 'assembly', 'status', 'source_line')
                                 if key in activity}
            pc = activity.get('pc')
            if pc is not None:
                key = hexword(word(pc))
                # CORE emits instruction evidence on stages, not program.code_mapping.
                # Use the executed instruction and DWARF line from this same run.
                if activity.get('assembly'):
                    mappings[key] = {name: small(activity[name]) for name in ('assembly', 'source_line') if name in activity}
        frames.append({'clock': index, 'current_pc': hexword(word(state['current_pc'])),
                       'registers': registers, 'metrics': metrics, 'stage_activity': stage_data,
                       'cycle_events': events(cycle.get('cycle_events', {})),
                       'memory_changes': {key: val for key, val in current_memory.items() if previous_memory.get(key) != val},
                       'memory_removed': sorted(set(previous_memory) - set(current_memory))})
        previous_memory = current_memory
    tutor = simulation_explanations({'history': frames, 'program': {'code_mapping': mappings}})
    # Missing DWARF lines do not prove an instruction belongs to CRT startup.
    for instruction in tutor['asm_instructions']:
        instruction['runtime_explanation'] = None
    # The existing deterministic tutor operates on exactly the sanitized trace.
    payload = {'schema_version': '1.0', 'execution_id': str(UUID(response['execution_id'])),
               'artifact_sha256': hashlib.sha256(elf).hexdigest(), 'mode': mode,
               'core_version': small(response['core_version']), 'result_schema_version': '1.0',
               'execution_status': response['execution_status'], 'initial_memory': initial_memory,
               'frames': frames, 'tutor': tutor,
               'summary': {key: small(result['summary'][key]) for key in
                           ('total_cycles', 'instructions_executed', 'stalls', 'forwards') if key in result['summary']}}
    encoded = canonical(payload).encode()
    if len(encoded) > MAX_SNAPSHOT_BYTES:
        raise ValueError('Snapshot too large')
    return payload, hashlib.sha256(encoded).hexdigest()


def purge_expired(db, now=None):
    now = now or datetime.now(timezone.utc)
    ids = select(AssistantExecution.execution_id).where(AssistantExecution.expires_at <= now).limit(500)
    db.execute(delete(AssistantExecution).where(AssistantExecution.execution_id.in_(ids)))
    db.commit()


def store_snapshot(db, user_id, payload, version, now=None):
    now = now or datetime.now(timezone.utc)
    # Serialize retention changes per owner across workers. Do not log payloads.
    db.execute(select(User.user_id).where(User.user_id == user_id).with_for_update()).scalar_one()
    rows = list(db.scalars(select(AssistantExecution).where(AssistantExecution.user_id == user_id)
                          .order_by(AssistantExecution.created_at.desc(), AssistantExecution.execution_id)))
    kept = 0
    for row in rows:
        expiry = row.expires_at.replace(tzinfo=timezone.utc) if row.expires_at.tzinfo is None else row.expires_at
        if expiry <= now or kept >= settings.ASSISTANT_CONTEXT_MAX_SNAPSHOTS - 1:
            db.delete(row)
        else:
            kept += 1
    row = AssistantExecution(execution_id=payload['execution_id'], user_id=user_id,
        artifact_sha256=payload['artifact_sha256'], result_version=version, mode=payload['mode'],
        created_at=now, expires_at=now + timedelta(seconds=settings.ASSISTANT_CONTEXT_TTL_SECONDS), payload=payload)
    db.add(row)
    descriptor = {'available': True, 'execution_id': row.execution_id, 'result_version': row.result_version,
            'artifact_sha256': row.artifact_sha256, 'mode': row.mode,
            'cycle_min': 0, 'cycle_max': len(payload['frames']) - 1, 'expires_at': row.expires_at.isoformat()}
    db.commit()
    # A concurrent newer run may already evict this row after commit.
    return descriptor


def context_error(status, code, message):
    return HTTPException(status, {'code': code, 'message': message})


def resolve_context(db, reference, user_id, now=None):
    now = now or datetime.now(timezone.utc)
    row = db.scalar(select(AssistantExecution).where(AssistantExecution.execution_id == str(reference.execution_id),
                                                    AssistantExecution.user_id == user_id))
    if row is None:
        raise context_error(404, 'CONTEXT_NOT_FOUND', '참고할 실행 결과가 없습니다. 로그인 상태에서 다시 실행해 주세요.')
    expiry = row.expires_at.replace(tzinfo=timezone.utc) if row.expires_at.tzinfo is None else row.expires_at
    if expiry <= now:
        raise context_error(410, 'CONTEXT_EXPIRED', '실행 맥락이 만료되었습니다. 다시 실행해 주세요.')
    if (reference.result_version != row.result_version or reference.artifact_sha256 != row.artifact_sha256
            or reference.mode != row.mode):
        raise context_error(409, 'CONTEXT_MISMATCH', '선택한 실행과 코드 버전이 일치하지 않습니다. 실행 결과를 다시 선택해 주세요.')
    payload = row.payload
    # Detect storage corruption/version drift rather than silently mixing evidence.
    if hashlib.sha256(canonical(payload).encode()).hexdigest() != row.result_version:
        raise context_error(409, 'CONTEXT_MISMATCH', '실행 결과 버전이 변경되었습니다. 다시 실행해 주세요.')
    if reference.cycle >= len(payload['frames']):
        raise context_error(422, 'CONTEXT_CYCLE_UNAVAILABLE', '해당 실행에 없는 사이클입니다.')
    frame = payload['frames'][reference.cycle]
    memory = dict(payload['initial_memory'])
    for past in payload['frames'][:reference.cycle + 1]:
        memory.update(past['memory_changes'])
        for key in past['memory_removed']:
            memory.pop(key, None)
    selected_memory = {}
    for address in reference.memory_addresses:
        key = str(address)
        if key not in memory:
            raise context_error(422, 'CONTEXT_MEMORY_UNAVAILABLE', '선택한 주소의 메모리 값이 실행 결과에 없습니다.')
        selected_memory[hexword(address)] = hexword(memory[key])
    metrics = frame['metrics']
    retired = metrics['accumulated_instructions']
    selected_pcs = {hexword(word(value['pc'])) for value in frame['stage_activity'].values() if value.get('pc') is not None}
    instructions = [entry for entry in payload['tutor']['asm_instructions'] if entry['pc'] in selected_pcs]
    cycle_tutor = [entry for entry in payload['tutor']['cycle_explanations'] if entry['cycle'] == reference.cycle]
    summary = dict(payload['summary'])
    count = summary.get('instructions_executed', 0)
    summary['cpi'] = summary['total_cycles'] / count if count else None
    output = {'schema_version': '1.0', 'reference': reference.model_dump(mode='json', exclude={'memory_addresses'}),
              'state_phase': 'after_cycle', 'clock_is_zero_based': True,
              'elapsed_cycles': reference.cycle + 1,
              'current_pc': frame['current_pc'],
              'registers': {f'x{i}': hexword(value) for i, value in enumerate(frame['registers'])},
              'selected_memory_words': selected_memory, 'memory_scope': 'explicitly_selected_addresses_only',
              'metrics_at_selected_cycle': {**metrics, 'cpi': (reference.cycle + 1) / retired if retired else None},
              'stage_activity': frame['stage_activity'], 'cycle_events': frame['cycle_events'],
              'whole_run_summary': summary, 'execution_status': payload['execution_status'],
              'tutor': {'schema_version': payload['tutor']['schema_version'],
                        'asm_instructions': instructions, 'cycle_explanations': cycle_tutor}}
    if len(canonical(output).encode()) > MAX_PROMPT_BYTES:
        raise context_error(413, 'CONTEXT_TOO_LARGE', '선택한 실행 맥락이 너무 큽니다. 메모리 범위를 줄여 주세요.')
    return output
