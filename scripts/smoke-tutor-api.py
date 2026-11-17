"""Verify the public REST -> private TUTOR gRPC path without credentials or model cost."""
import argparse
import json
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from uuid import UUID


def request(base, message):
    req = Request(base.rstrip('/') + '/api/v1/tutor/sample',
        data=json.dumps(message).encode(), headers={'Content-Type':'application/json'}, method='POST')
    try:
        response = urlopen(req, timeout=20)
    except HTTPError as error:
        response = error
    with response:
        return response.status, json.load(response)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', default='https://d1j3nkcez6kncs.cloudfront.net')
    args=parser.parse_args()
    results=[]
    for message in ['Hello TUTOR', 'TUTOR 연결 확인']:
        status, body=request(args.base_url, {'message':message})
        assert status==200, (status,body)
        UUID(body['request_id'])
        assert body['schema_version']=='1.0' and body['sample'] is True
        assert body['message']==message and body['tutor_version'] and body['reply']
        results.append({'http_status':status, 'response':body})
    for payload in [{'message':''},{'message':' '*3},{'message':'a'*257},{'message':'hello','unknown':True}]:
        status,_=request(args.base_url,payload)
        assert status==422, status
    print(json.dumps({'status':'PASS','valid_requests':results,'invalid_requests':4},ensure_ascii=False,indent=2))

if __name__=='__main__': main()
