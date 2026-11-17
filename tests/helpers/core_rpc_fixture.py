"""Test-only wire fixture around real engine execution; never deploy this file."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import subprocess
import sys
import uuid
import base64

import grpc

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from app.contracts.archreactor_contract.v1 import simulation_pb2 as pb, simulation_pb2_grpc as rpc

WORKER = '''
import base64, json, sys
from io import BytesIO
from elftools.elf.elffile import ELFFile
from app.state import create_state, delete_state
from app.simulator import run_simulation
body = json.load(sys.stdin)
if sys.platform == 'linux':
    import resource
    resource.setrlimit(resource.RLIMIT_AS, (384 * 1024 * 1024, 384 * 1024 * 1024))
try:
    data = base64.b64decode(body['elf'])
    elf = ELFFile(BytesIO(data))
    if elf.elfclass != 32 or not elf.little_endian or elf['e_machine'] != 'EM_RISCV':
        raise ValueError('Invalid RV32 ELF')
    if sum(section['sh_size'] for section in elf.iter_sections() if section['sh_flags'] & 2) > 64 * 1024:
        print(json.dumps({'error': 'RESOURCE_EXHAUSTED'}))
        sys.exit(0)
    create_state(body['id'], data, mode=body['mode'])
    result = run_simulation(body['id'], max_cycles=body['max_cycles'])
    status = 'COMPLETED' if result['status'] == 'halted' else (
        'CYCLE_LIMIT' if result['summary']['total_cycles'] >= body['max_cycles']
        and not result['history'][-1]['cycle_events']['runtime_error']['has_error'] else 'SIMULATION_ERROR')
    print(json.dumps({'status': status, 'result': result}))
except MemoryError:
    print(json.dumps({'error': 'RESOURCE_EXHAUSTED'}))
except Exception:
    print(json.dumps({'error': 'INVALID_ARGUMENT'}))
finally:
    delete_state(body['id'])
'''


class EngineFixture(rpc.SimulatorServicer):
    def __init__(self, source):
        self.source = source

    def RunSimulation(self, request, context):
        execution_id = str(uuid.uuid4())
        options = {'creationflags': subprocess.CREATE_NO_WINDOW} if sys.platform == 'win32' else {}
        try:
            process = subprocess.run([sys.executable, '-c', WORKER], cwd=self.source, input=json.dumps({
                'id': execution_id, 'elf': base64.b64encode(request.elf).decode(),
                'mode': 'single' if request.mode == pb.SINGLE else 'pipeline', 'max_cycles': request.max_cycles,
            }), capture_output=True, text=True, encoding='utf-8', timeout=8, check=True, **options)
            body = json.loads(process.stdout)
        except subprocess.TimeoutExpired:
            context.abort(grpc.StatusCode.DEADLINE_EXCEEDED, 'Fixture worker timeout')
        if 'error' in body:
            if body['error'] == 'RESOURCE_EXHAUSTED':
                context.abort(grpc.StatusCode.RESOURCE_EXHAUSTED, 'Fixture resource limit')
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, 'Fixture ELF validation failed')
        result = body['result']
        return pb.RunSimulationResponse(
            request_id=request.request_id, execution_id=execution_id, status=pb.ExecutionStatus.Value(body['status']),
            core_version='test-fixture-engine', result_schema_version=result['schema_version'],
            result_json=json.dumps(result, ensure_ascii=False).encode('utf-8'))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--core-source', required=True, type=Path)
    parser.add_argument('--port', required=True, type=int)
    args = parser.parse_args()
    server = grpc.server(ThreadPoolExecutor(max_workers=2), options=[
        ('grpc.max_receive_message_length', 256 * 1024 + 1024),
        ('grpc.max_send_message_length', 8 * 1024 * 1024),
    ])
    rpc.add_SimulatorServicer_to_server(EngineFixture(args.core_source.resolve()), server)
    if not server.add_insecure_port(f'127.0.0.1:{args.port}'):
        raise RuntimeError('Fixture port unavailable')
    server.start()
    server.wait_for_termination()
