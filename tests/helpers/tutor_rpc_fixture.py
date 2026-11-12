"""Contract-only remote fixture. Educational correctness is tested in TUTOR."""
import json
from app.contracts.tutor_contract.v1 import tutor_pb2 as pb, tutor_pb2_grpc as rpc


def explanation(kind):
    return {'kind': kind, 'category': 'fixture', 'title': 'remote explanation',
            'summary': 'remote summary', 'detail': 'remote detail', 'reads': ['x11'], 'writes': ['x10']}


class ContractTutor(rpc.TutorServicer):
    def respond(self, request, bundle):
        return pb.TutorResponse(request_id=request.request_id, schema_version='1.0',
            tutor_version='contract-fixture', result_json=json.dumps({'schema_version': '1.0', **bundle}))

    def Explain(self, request, context):
        return self.respond(request, {'items': [explanation(item.kind) for item in request.items]})

    def Compile(self, request, context):
        return self.respond(request, {'c_lines': [
            {'line': i, 'text': line, 'explanation': explanation('c')}
            for i, line in enumerate(request.source.splitlines(), 1)
        ] if request.lang == 'c' else [], 'asm_instructions': []})

    def Analyze(self, request, context):
        result = json.loads(request.result_json)
        mappings = (result.get('program') or {}).get('code_mapping') or {}
        instructions = [{'pc': f'0x{int(pc, 16):08X}', 'text': entry['assembly'],
                         'source_line': entry.get('source_line'), 'source_file': 'EXCLUDED_FILE_PATH',
                         'retire_count': 999, 'explanation': explanation('asm')}
                        for pc, entry in mappings.items() if entry.get('assembly')]
        cycles = []
        for index, frame in enumerate(result.get('history') or []):
            events = []
            for name, flag, kind in [('stall', 'has_stall', 'stall'), ('forwarding', 'has_forwarded', 'forwarding'),
                                     ('control_hazard', 'has_flush', 'flush')]:
                evidence = frame.get('cycle_events', {}).get(name, {})
                if evidence.get(flag):
                    events.append({'type': kind, 'title': kind, 'summary': kind, 'detail': kind, 'evidence': evidence})
            if events:
                cycles.append({'history_index': index, 'cycle': frame['clock'], 'events': events})
        return self.respond(request, {'asm_instructions': instructions, 'cycle_explanations': cycles, 'execution_steps': []})
