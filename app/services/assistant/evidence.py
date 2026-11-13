"""Bounded server-only evidence projection and deterministic RV32 arithmetic.

No retrieval, evaluation of user expressions, model calls, or persistence here.
The route has already authenticated and resolved the execution reference.
"""
import math
import re


def cpi_check(elapsed, retired, reported):
    result = {'elapsed_cycles': elapsed, 'retired_instructions': retired,
              'reported_cpi': reported, 'cpi': None, 'status': 'missing'}
    if elapsed is None or retired is None:
        return result
    if any(type(v) is not int or v < 0 for v in (elapsed, retired)):
        return {**result, 'status': 'inconsistent'}
    if retired == 0:
        return {**result, 'status': 'undefined' if reported is None else 'inconsistent'}
    computed = elapsed / retired
    # Accept only floating-point serialization noise, not a different CPI.
    if (type(reported) not in (int, float) or not math.isfinite(reported)
            or not math.isclose(reported, computed, rel_tol=0, abs_tol=1e-9)):
        return {**result, 'status': 'inconsistent' if reported is not None else 'missing'}
    return {**result, 'status': 'verified', 'cpi': computed}


def rv32(value):
    if not isinstance(value, str) or not re.fullmatch(r'0[xX][0-9a-fA-F]{1,8}', value):
        return None
    return int(value, 16)


def address_checks(question, registers):
    # Named RV32 operands only. Never eval a question or a code comment.
    aliases = {'sp': 'x2', 's0': 'x8', 'fp': 'x8', **{f'x{i}': f'x{i}' for i in range(32)}}
    checks = []
    sp, s0 = rv32(registers.get('x2')), rv32(registers.get('x8'))
    if sp is not None and s0 is not None:
        checks.append({'expression': 's0-sp', 'difference_bytes': s0-sp,
                       'meaning': 'address_difference_only_not_frame_size'})
    pattern = r'(?<![\w])(' + '|'.join(sorted(aliases, key=len, reverse=True)) + r')\s*([+-])\s*(0x[0-9a-f]+|[0-9]+)(?![\w.]|\s*[+*/-])'
    for match in list(re.finditer(pattern, question, re.I))[:8]:
        alias, op, raw = match.groups()
        base = rv32(registers.get(aliases[alias.lower()]))
        if base is None or len(raw) > 10:
            continue
        offset = int(raw, 16 if raw.lower().startswith('0x') else 10)
        if offset > 0xffffffff:
            continue
        result = base + (offset if op == '+' else -offset)
        checks.append({'expression': match.group(), 'base': f'0x{base:08x}', 'offset_bytes': offset,
                       'status': 'verified' if 0 <= result <= 0xffffffff else 'out_of_range',
                       'address': f'0x{result:08x}' if 0 <= result <= 0xffffffff else None})
    return checks


def execution_evidence(request):
    context = request._execution_context
    if context is None:
        return None
    topics = set(request._answer_topics)
    result = {
        'reference': {k: context['reference'][k] for k in ('execution_id', 'mode', 'cycle')},
        'clock_is_zero_based': True,
        'state_phase': context.get('state_phase'),
        'relationship_to_editor_source': 'not_verified',
        'observed_loop_iterations': None,
        'initialization_completed': None,
    }
    if not topics & {'mapping', 'registers', 'memory', 'stack', 'hazards', 'cpi', 'identity'}:
        # A static explanation has no reason to receive an execution clock/ID.
        result.pop('reference')
        result.pop('clock_is_zero_based')
        result.pop('state_phase')
    tutor = context.get('tutor') or {}
    if topics & {'mapping', 'registers', 'memory', 'stack', 'hazards'}:
        result['stage_activity'] = context.get('stage_activity', {})
        result['tutor'] = {}
        if topics & {'mapping', 'registers', 'memory', 'stack'}:
            result['tutor']['asm_instructions'] = tutor.get('asm_instructions', [])
        if 'hazards' in topics:
            result['tutor']['cycle_explanations'] = tutor.get('cycle_explanations', [])
    registers = context.get('registers') or {}
    if topics & {'registers', 'memory'}:
        result['registers'] = registers
    elif 'stack' in topics:
        result['registers'] = {k: registers[k] for k in ('x2', 'x8') if k in registers}
    if topics & {'memory', 'stack'}:
        result['address_checks'] = address_checks(request.messages[-1].content, registers)
    if 'memory' in topics:
        result['selected_memory_words'] = context.get('selected_memory_words', {})
        result['memory_scope'] = 'explicitly_selected_addresses_only'
    if topics & {'hazards', 'cpi'}:
        result['cycle_events'] = context.get('cycle_events', {})
    if 'cpi' in topics:
        selected = context.get('metrics_at_selected_cycle') or {}
        whole = context.get('whole_run_summary') or {}
        selected_check = cpi_check(context.get('elapsed_cycles'), selected.get('accumulated_instructions'), selected.get('cpi'))
        whole_check = cpi_check(whole.get('total_cycles'), whole.get('instructions_executed'), whole.get('cpi'))
        contradictions = []
        for before, after in ((context.get('elapsed_cycles'), whole.get('total_cycles')),
                (selected.get('accumulated_instructions'), whole.get('instructions_executed')),
                (selected.get('accumulated_stalls'), whole.get('stalls')),
                (selected.get('accumulated_forwards'), whole.get('forwards'))):
            if type(before) is int and type(after) is int and before > after:
                contradictions.append('selected_counter_exceeds_whole_run')
        if contradictions:
            selected_check.update(status='inconsistent', cpi=None)
            whole_check.update(status='inconsistent', cpi=None)
        result['verified_metrics'] = {'selected': selected_check, 'whole_run': whole_check,
                                      'consistent_ranges': not bool(contradictions)}
    return result


def include_source(request):
    return bool(set(request._answer_topics) & {'code', 'mapping', 'registers', 'memory', 'flow', 'stack', 'hazards'})
