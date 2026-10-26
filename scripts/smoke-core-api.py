"""Live HTTPS acceptance test. Passwords/tokens stay in process memory only."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import secrets
import urllib.error
import urllib.request
import uuid


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--url', default='https://d1j3nkcez6kncs.cloudfront.net')
    parser.add_argument('--output', default='dist/core-api-smoke.json')
    args = parser.parse_args()
    def call(path, data=None, token=None, method=None):
        headers={'Content-Type':'application/json'}
        if token:
            headers['Authorization']='Bearer '+token
        request=urllib.request.Request(args.url+path, data=json.dumps(data).encode() if data is not None else None,
            headers=headers, method=method)
        try:
            with urllib.request.urlopen(request,timeout=30) as response:
                payload=response.read()
                return response.status,json.loads(payload) if payload else None
        except urllib.error.HTTPError as error:
            return error.code,None
    def expect(result, code):
        assert result[0]==code, f'Expected HTTP {code}, got {result[0]}'
        return result[1]
    tokens, users, files = [], [], []
    report = {'checks':{}}
    try:
        for _ in range(2):
            user='grpc_smoke_'+uuid.uuid4().hex[:12]
            password=secrets.token_urlsafe(30)
            email=user+'@example.com'
            expect(call('/auth/signup',dict(user_id=user,email=email,password=password,name='gRPC smoke')),201)
            tokens.append(expect(call('/auth/login',dict(email=email,password=password)),200)['access_token'])
            users.append(user)
        source='''int main(void) {
          int value = 6 * 7;
          asm volatile("mv a0, %0\\nli a7, 1\\necall" : : "r"(value) : "a0", "a7");
          return 0;
        }'''
        file=expect(call('/api/v1/files',dict(title='grpc-smoke.c',content=source,lang='c'),tokens[0]),201)
        files.append(file['file_id'])
        build=expect(call('/api/v1/build/compile',dict(file_id=file['file_id'],compiler_opt='-O0'),tokens[0]),201)
        assert build['status']=='success', 'RV32IM compilation failed'
        request=dict(build_id=build['build_id'],mode='pipeline',max_cycles=2000)
        assert call('/api/v1/simulation/run',request)[0] in (401,403)
        expect(call('/api/v1/simulation/run',request,tokens[1]),403)
        report['checks']['authentication_and_ownership']='PASS'
        response=expect(call('/api/v1/simulation/run',request,tokens[0]),200)
        assert response['execution_status']=='COMPLETED'
        assert response['result']['console_output']=='42'
        report['core_version']=response['core_version']
        report['checks']['compiled_rv32im_pipeline']='PASS'
        response=expect(call('/api/v1/simulation/run',{**request,'mode':'single'},tokens[0]),200)
        assert response['execution_status']=='COMPLETED' and response['result']['console_output']=='42'
        report['checks']['compiled_rv32im_single']='PASS'
        response=expect(call('/api/v1/simulation/run',{**request,'max_cycles':1},tokens[0]),200)
        assert response['execution_status']=='CYCLE_LIMIT'
        report['checks']['cycle_limit']='PASS'
        with ThreadPoolExecutor(max_workers=2) as pool:
            responses=list(pool.map(lambda _:expect(call('/api/v1/simulation/run',request,tokens[0]),200),range(2)))
        assert responses[0]['execution_id']!=responses[1]['execution_id']
        assert responses[0]['result']==responses[1]['result']
        report['checks']['concurrent_state_isolation']='PASS'
        native_source=expect(call('/api/v1/files',dict(title='native-smoke.c',content='int main(){return 0;}',lang='c'),tokens[0]),201)
        files.append(native_source['file_id'])
        native=expect(call('/api/v1/build/compile',dict(file_id=native_source['file_id'],compiler_opt='-O0',compile_profile='native'),tokens[0]),201)
        assert native['status']=='success'
        expect(call('/api/v1/simulation/run',{**request,'build_id':native['build_id']},tokens[0]),422)
        report['checks']['native_elf_rejected']='PASS'
        report['status']='PASS'
    finally:
        for file_id in files:
            call('/api/v1/files/'+file_id,token=tokens[0],method='DELETE')
        report['test_users']=users
        Path(args.output).parent.mkdir(exist_ok=True)
        Path(args.output).write_text(json.dumps(report,indent=2))
        print(json.dumps(report))


if __name__ == '__main__':
    main()
