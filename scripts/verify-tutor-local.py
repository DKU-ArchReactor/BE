"""Real BE client -> local TUTOR gRPC; compiler/CPU use the deployed public BE.

No AWS changes, database, user credentials, or LLM calls. Tokens remain in memory.
"""
import argparse
import asyncio
from copy import deepcopy
import json
import os
from pathlib import Path
import sys
from urllib.request import Request, urlopen
from urllib.error import HTTPError

SOURCE = 'int main(void) {\n volatile int x = 4;\n if (x > 2) return x * 3;\n return 0;\n}\n'


def run(tutor_source, base_url):
    root = Path(__file__).resolve().parents[1]
    sys.path[:0] = [str(root), str(tutor_source), str(tutor_source / 'src')]
    os.environ['DEBUG'] = 'false'
    from service.server import create_server
    from app.core.config import settings
    from app.services import tutor_client
    from app.services.tutor import compile_explanations, simulation_explanations
    from app.services.assistant.context import build_snapshot
    from app.schemas.tutor import ExplainItem
    server, _, port = create_server('127.0.0.1:0')
    server.start()
    settings.TUTOR_GRPC_TARGET = f'127.0.0.1:{port}'
    def post(path, body):
        request = Request(base_url.rstrip('/') + path, data=json.dumps(body).encode(),
                          headers={'Content-Type': 'application/json'})
        with urlopen(request, timeout=60) as response:
            return json.load(response)
    try:
        assert asyncio.run(tutor_client.sample('local integration')).sample is True
        explained = tutor_client.explain_items([ExplainItem(kind='asm', text='lbu a0,0(a1)')])
        assert explained.items[0].model_extra['memory']['extension'] == 'zero'
        compiled = compile_explanations(SOURCE, 'c', None)
        assert compiled and len(compiled['c_lines']) == 5
        build = post('/api/v1/build/compile', {'content': SOURCE, 'lang': 'c', 'compile_profile': 'rv32im', 'compiler_opt': '-O0 -g'})
        assert build['status'] == 'success'
        with urlopen(build['binary_url'], timeout=30) as response:
            elf = response.read(256*1024+1)
        results = []
        for mode in ('single', 'pipeline'):
            envelope = post('/api/v1/simulation/run', {'simulation_token': build['simulation_token'], 'mode': mode, 'max_cycles': 2000})
            assert envelope['execution_status'] == 'COMPLETED'
            original = deepcopy(envelope['result'])
            tutor = simulation_explanations(original, elf_bytes=elf, source=SOURCE, source_file='source.c')
            assert tutor is not None and original == envelope['result']
            assert tutor['source_mapping']['basis'] == 'elf_dwarf'
            assert len(tutor['execution_steps']) == len(original['history'])
            final = original['history'][-1]['global_result']
            assert int(final['registers']['x10'], 16) == 12
            snapshot, _ = build_snapshot(envelope, elf)
            assert snapshot['tutor']['available'] and snapshot['tutor']['asm_instructions']
            assert all('source_file' not in item and 'retire_count' not in item for item in snapshot['tutor']['asm_instructions'])
            results.append(final)
        assert results[0]['registers'] == results[1]['registers']
        assert results[0]['memory_snapshot'] == results[1]['memory_snapshot']
        return {'passed': True, 'checks': ['Sample', 'Explain', 'Compile', 'Analyze single', 'Analyze pipeline', 'assistant snapshot']}
    finally:
        server.stop(0).wait()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--tutor-source', required=True, type=Path)
    parser.add_argument('--api-base', default='https://d1j3nkcez6kncs.cloudfront.net')
    args = parser.parse_args()
    try:
        print(json.dumps(run(args.tutor_source.resolve(), args.api_base)))
    except Exception as error:
        print(json.dumps({'passed': False, 'error': type(error).__name__,
                          'http_status': error.code if isinstance(error, HTTPError) else None}))
        raise SystemExit(1)
