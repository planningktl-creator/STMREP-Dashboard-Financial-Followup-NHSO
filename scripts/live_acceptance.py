"""Local acceptance through authenticated APIs; patient responses are never logged."""
import argparse
import json
from pathlib import Path
import time
import uuid
import requests

from financial.config import ROOT

def request(client, method, url, **kwargs):
    for attempt in range(8):
        try:
            response=client.request(method,url,**kwargs)
            if response.status_code not in (502,503,504):
                response.raise_for_status()
                return response
        except (requests.Timeout,requests.ConnectionError):
            pass
        time.sleep(min(30,2**attempt))
    raise RuntimeError('GATEWAY_UNAVAILABLE_AFTER_RETRIES')

def main():
    args=argparse.ArgumentParser();args.add_argument('--url',default='http://127.0.0.1:18729');args.add_argument('--start',default='2026-09-29');args.add_argument('--end',default='2026-09-29');opts=args.parse_args()
    private=ROOT/'.data';auth=json.loads((private/'local-live-client.json').read_text(encoding='utf-8-sig'))
    client=requests.Session();client.cookies.set('stmrep_session',auth['cookie']);client.headers['x-csrf-token']=auth['csrf']
    identity=client.get(opts.url+'/api/session',timeout=120);identity.raise_for_status()
    if identity.json()['hospital']!='10929':raise RuntimeError('HOSPITAL_MISMATCH')
    checkpoint=private/'live-acceptance-job.json'
    if checkpoint.exists():job=json.loads(checkpoint.read_text())
    else:
        body={'start':opts.start,'end':opts.end,'request_id':str(uuid.uuid4())}
        response=client.post(opts.url+'/api/his/sync',json=body,timeout=120);response.raise_for_status();job=response.json()
        checkpoint.write_text(json.dumps(job),encoding='utf-8')
    prior=None
    while True:
        response=request(client,'GET',opts.url+'/api/jobs/'+job['job_id'],timeout=120);result=response.json()
        state=(result['status'],result.get('progress',{}).get('dataset'))
        if state!=prior:print(json.dumps({'status':state[0],'dataset':state[1]}),flush=True);prior=state
        if result['status'] in ('completed','completed_with_issues','failed','waiting_session','paused'):break
        time.sleep(10)
    report={'job_status':result['status'],'error_code':result.get('error_code'),'result':result.get('result')}
    snapshot=result.get('result',{}).get('snapshot_id')
    if snapshot:
        snapshots=request(client,'GET',opts.url+'/api/snapshots',timeout=120).json()['items'];snap=next(s for s in snapshots if s['id']==snapshot)
        report['snapshot']=snap
        params={'start':opts.start,'end':opts.end,'snapshot_id':snapshot,'limit':1}
        cases=request(client,'GET',opts.url+'/api/cases',params=params,timeout=180)
        report['cases_api_passed']=True;report['sample_case_count']=len(cases.json()['items'])
        if cases.json()['items']:
            case_id=cases.json()['items'][0]['id']
            detail=request(client,'GET',opts.url+'/api/cases/'+str(case_id),timeout=180)
            report['case_detail_api_passed']=True
            report['case_has_source_snapshot']=detail.json()['case']['snapshot_id']==snapshot
            report['case_amount_types_valid']=all(v is None or isinstance(v,str) for k,v in detail.json()['case'].items() if k.endswith('_amount'))
        overview=request(client,'GET',opts.url+'/api/overview',params={k:v for k,v in params.items() if k!='limit'},timeout=240)
        report['overview_api_passed']=True;report['overview_meta_snapshot_valid']=overview.json()['meta']['snapshot_id']==snapshot
    (private/'live_acceptance.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k not in ('snapshot','result')}),flush=True)

if __name__=='__main__':main()
