"""5-user load with a real BIFF import, only in disposable Docker test infra.

The serve command installs synthetic sessions only in this test entrypoint.
Production financial.server never imports or enables it. No hospital endpoint,
credentials, row values, SQL text or plans are emitted as benchmark artifacts.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from decimal import Decimal
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid
from urllib.parse import urlparse
import requests

ROOT=Path(__file__).resolve().parents[1]
COMPOSE=['docker','compose','-p','stmrep-perf-test','-f',str(ROOT/'deploy/compose.test.yaml')]
BASE='http://127.0.0.1:18834'
COOKIE='SYNTHETIC_PERFORMANCE_ONLY'
SNAPSHOT='22222222-2222-4222-8222-222222222222'


def command(*args):
    return subprocess.check_output(list(args),cwd=ROOT,stderr=subprocess.PIPE)


def test_database(url):
    from financial.db import Database
    assert urlparse(url).hostname in ('pgweb','127.0.0.1'), 'DISPOSABLE_ENDPOINT_REQUIRED'
    db=Database(url)
    assert db.scalar('SELECT current_database()')=='stmrep_test','DISPOSABLE_DATABASE_REQUIRED'
    return db


def serve():
    if os.getenv('PERFORMANCE_TEST_ONLY')!='1':raise SystemExit('DISPOSABLE_TEST_ONLY')
    from financial.config import Settings
    from financial.bms import Session
    from financial.main import create_app
    import uvicorn
    probe=test_database(os.environ['PGWEB_URL']);probe.transport.session.close()
    delay=float(os.getenv('SYNTHETIC_PGWEB_DELAY','0'))
    if delay:
        # Injectable delay exists only in this disposable test entrypoint.
        original=requests.Session
        class SlowGatewaySession(original):
            def post(self,*args,**kwargs):
                time.sleep(delay)
                return super().post(*args,**kwargs)
        requests.Session=SlowGatewaySession
    app=create_app(Settings.from_env())
    app.state.sessions.active[COOKIE]=Session(COOKIE,'synthetic:performance','','',None,'10929',time.time()+3600,'SYNTHETIC_CSRF')
    uvicorn.run(app,host='0.0.0.0',port=8000,access_log=False)


def seed(db, count):
    from financial.db import ident
    from repstm.schema import schema_sql
    if not db.scalar("SELECT to_regclass('ingest.documents') IS NOT NULL"):db.execute(schema_sql())
    db.migrate()
    s=ident(SNAPSHOT)
    coverage=json.dumps({'op':{'state':'complete'},'ip':{'state':'complete'},'lines':{'state':'complete'}})
    db.execute(f"""INSERT INTO his.snapshots(id,hcode,dstart,dend,status,coverage,completed_at)
      VALUES({s},'10929','2026-01-01','2026-01-31','ready','{coverage}'::jsonb,now()) ON CONFLICT DO NOTHING;
      INSERT INTO his.records(snapshot_id,dataset,source_key,payload,record_hash)
      SELECT {s},'SYNTHETIC_CASE','SYNTHETIC-'||n,'{{}}','synthetic' FROM generate_series(1,{count}) n ON CONFLICT DO NOTHING;
      INSERT INTO his.cases(snapshot_id,hcode,encounter_key,care_type,source_record_id,hn,cid,vn,an,
       name,service_date,fiscal_year_be,his_summary_charge,identity_status,grouper_version,los)
      SELECT {s},'10929',CASE WHEN n%3=0 THEN 'OP:' ELSE 'IP:' END||'SYNTHETIC-'||n,
       CASE WHEN n%3=0 THEN 'OP' ELSE 'IP' END,r.id,lpad(n::text,7,'0'),'SYNTHETIC-PID'||lpad(n::text,6,'0'),
       CASE WHEN n%3=0 THEN 'SYNTHETIC-VN'||lpad(n::text,6,'0') END,
       CASE WHEN n%3<>0 THEN 'SYNTHETIC-AN'||lpad(n::text,6,'0') END,
       'ผู้ป่วยจำลอง','2026-01-05',2569,10,'unique','SYNTHETIC-V1',4
       FROM generate_series(1,{count}) n JOIN his.records r ON r.snapshot_id={s} AND r.dataset='SYNTHETIC_CASE' AND r.source_key='SYNTHETIC-'||n ON CONFLICT DO NOTHING;
      INSERT INTO his.records(snapshot_id,dataset,source_key,payload,record_hash)
       SELECT {s},'SYNTHETIC_LINE','SYNTHETIC-L'||c.id||'-'||n,'{{}}','synthetic' FROM his.cases c CROSS JOIN generate_series(1,4) n WHERE c.snapshot_id={s} ON CONFLICT DO NOTHING;
      INSERT INTO his.case_lines(snapshot_id,source_record_id,case_id,quantity,charge_amount,observed_item_cost)
       SELECT {s},r.id,c.id,1,CASE WHEN n=1 THEN 12.123 WHEN n=2 THEN -2.123 ELSE 0 END,NULL
       FROM his.cases c CROSS JOIN generate_series(1,4) n JOIN his.records r ON r.snapshot_id={s} AND r.dataset='SYNTHETIC_LINE' AND r.source_key='SYNTHETIC-L'||c.id||'-'||n
       WHERE c.snapshot_id={s} ON CONFLICT DO NOTHING;
      ANALYZE his.cases; ANALYZE his.case_lines; ANALYZE his.records;""")


def metrics(name):
    text=command('docker','exec',name,'python','-c',
       "import pathlib,json; p=pathlib.Path('/sys/fs/cgroup');print(json.dumps({n:int((p/n).read_text()) for n in ['memory.peak','memory.current','memory.max']}))")
    return json.loads(text)


def main(args):
    os.environ['PGWEB_MIN_INTERVAL']='0'
    name='stmrep-perf-app'
    out=ROOT/'.ci';out.mkdir(exist_ok=True)
    command(*COMPOSE,'up','-d','postgres','pgweb')
    try:
        until=time.monotonic()+60
        while time.monotonic()<until:
            try:
                if requests.get('http://127.0.0.1:18831/api/info',timeout=2).status_code==200:break
            except requests.RequestException:pass
            time.sleep(.5)
        else:raise RuntimeError('PERFORMANCE_GATEWAY_UNAVAILABLE')
        db=test_database('http://127.0.0.1:18831');seed(db,args.cases)
        fixture=ROOT/'.ci'/('eclaim_10929_IP_25690108_010101'+('001' if args.label=='baseline' else '002')+'.xls')
        from scripts.synthetic_workbook import write_rep
        from repstm.parser import parse_file
        write_rep(fixture,args.import_rows,rep_no='99'+str(uuid.uuid4().int%1000000).zfill(6))
        parsed=parse_file(fixture)
        assert not [x for x in parsed['issues'] if x['severity']=='error']
        # Baseline image uses current test runner mounted outside the app package.
        command('docker','run','-d','--name',name,'--network','stmrep-perf-test_default',
          '--cpus','2','--memory','2g','--read-only','--cap-drop','ALL','--security-opt','no-new-privileges:true',
          '--tmpfs','/app/.data:uid=10929,gid=10929,mode=700',
          '-v','stmrep-perf-temporary:/tmp/stmrep',
          '-v',str(Path(__file__).resolve())+':/app/performance_runner.py:ro',
          '-p','127.0.0.1:18834:8000','-e','APP_MODE=live','-e','COOKIE_SECURE=false','-e','WORKER_ENABLED=true',
          '-e','PGWEB_URL=http://pgweb:8081','-e','PGWEB_MIN_INTERVAL=0.25','-e','PERFORMANCE_TEST_ONLY=1',
          '-e','SYNTHETIC_PGWEB_DELAY='+str(args.gateway_delay),
          '--entrypoint','python',args.image,'/app/performance_runner.py','serve')
        client=requests.Session();client.cookies.set('stmrep_session',COOKIE)
        headers={'X-CSRF-Token':'SYNTHETIC_CSRF','Idempotency-Key':str(uuid.uuid4())}
        until=time.monotonic()+60
        while time.monotonic()<until:
            try:
                if client.get(BASE+'/healthz',timeout=2).status_code==200:break
            except requests.RequestException:pass
            time.sleep(.5)
        else:raise RuntimeError('PERFORMANCE_SERVER_UNAVAILABLE')
        scope=f'?start=2026-01-01&end=2026-01-31&snapshot_id={SNAPSHOT}'
        before=client.get(BASE+'/api/overview'+scope,timeout=90);before.raise_for_status()
        before=before.json();assert before['his']['encounters']==args.cases
        assert Decimal(before['financial']['his_charge_amount'])==args.cases*10
        started=time.monotonic()
        with fixture.open('rb') as reader:
            response=client.post(BASE+'/api/imports/uploads',headers=headers,files={'files':(fixture.name,reader,'application/vnd.ms-excel')},timeout=30)
        response.raise_for_status();job=response.json()['job_id']
        deadline=time.monotonic()+90
        while time.monotonic()<deadline:
            state=client.get(BASE+'/api/jobs/'+job,timeout=15).json()['status']
            if state=='awaiting_import':break
            if state in ('failed','blocked'):raise RuntimeError('FIXTURE_INSPECTION_FAILED')
            time.sleep(.3)
        else:raise RuntimeError('FIXTURE_INSPECTION_TIMEOUT')
        response=client.post(BASE+'/api/jobs/'+job+'/start',headers=headers,timeout=15)
        response.raise_for_status()
        def user(index):
            session=requests.Session();session.cookies.set('stmrep_session',COOKIE)
            measured=[]
            try:
                for _ in range(args.iterations):
                    for path,label in [('/api/cases'+scope+'&search=0000','cases'),('/api/overview'+scope,'overview'),('/healthz','liveness')]:
                        t=time.monotonic();result=session.get(BASE+path,timeout=90);elapsed=time.monotonic()-t
                        result.raise_for_status();data=result.json()
                        if label=='overview':assert data['his']['encounters']==args.cases and Decimal(data['financial']['his_charge_amount'])==args.cases*10
                        measured.append((label,elapsed))
            finally:session.close()
            return measured
        with ThreadPoolExecutor(max_workers=5) as pool:
            results=sum(list(pool.map(user,range(5))),[])
        deadline=time.monotonic()+180
        while time.monotonic()<deadline:
            detail=client.get(BASE+'/api/jobs/'+job,timeout=30).json()
            if detail['status'].startswith('completed'):break
            if detail['status']=='failed':raise RuntimeError('FIXTURE_IMPORT_FAILED')
            time.sleep(.5)
        else:raise RuntimeError('FIXTURE_IMPORT_TIMEOUT')
        assert detail['status']=='completed','FIXTURE_NOT_VERIFIED'
        assert detail['result']['inserted_records']==args.import_rows*3 and detail['result']['skipped_files']==0,'FIXTURE_IMPORT_MUST_DO_REAL_WORK'
        peak=metrics(name)
        ops=client.get(BASE+'/api/operations',timeout=30).json()
        def summary(label):
            times=sorted(t for key,t in results if key==label)
            return {'requests':len(times),'p95_seconds':round(times[math.ceil(.95*len(times))-1],4),'max_seconds':round(max(times),4)}
        report={'fixture':'synthetic_only','label':args.label,'image':args.image,'concurrent_users':5,'injected_gateway_delay_seconds':args.gateway_delay,
           'resources':{'cpu_cores':2,'memory_limit_bytes':peak['memory.max'],'peak_memory_bytes':peak['memory.peak']},
           'fixture_cases':args.cases,'fixture_lines':args.cases*4,'fixture_import_records':args.import_rows*3,
           'import_elapsed_seconds':round(time.monotonic()-started,3),'import_result':detail['result'],
           'latency':{key:summary(key) for key in ['cases','overview','liveness']},
           'gateway':ops.get('gateway',{}),'application_resources':ops.get('resources',{}),
           'financial_checks':['encounter count invariant','signed charges invariant','unknown costs retained','real BIFF continuation import'],
           'limitations':['synthetic fixture, not full hospital corpus','local pgweb, BMS gateway latency unverified']}
        passed=all(report['latency'][key]['p95_seconds']<=limit for key,limit in [('cases',2),('overview',5),('liveness',1)]) and peak['memory.peak']<=peak['memory.max']*.75
        report['status']='passed' if passed else 'targets_not_met'
        (out/('performance-'+args.label+'.json')).write_text(json.dumps(report,indent=2),encoding='utf-8')
        print(json.dumps(report))
        if args.enforce and not passed:raise SystemExit(1)
    finally:
        if 'db' in locals():db.close()
        subprocess.run(['docker','rm','-f',name],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        if not args.keep_database:
            command(*COMPOSE,'down','--volumes','--remove-orphans')
            subprocess.run(['docker','volume','rm','stmrep-perf-temporary'],stdout=subprocess.PIPE,stderr=subprocess.PIPE)


if __name__=='__main__':
    if len(sys.argv)>1 and sys.argv[1]=='serve':serve()
    else:
        parser=argparse.ArgumentParser();parser.add_argument('--image',default='stmrep:release-test')
        parser.add_argument('--label',default='optimized');parser.add_argument('--cases',type=int,default=1000)
        parser.add_argument('--import-rows',type=int,default=500);parser.add_argument('--iterations',type=int,default=4)
        parser.add_argument('--enforce',action='store_true');parser.add_argument('--keep-database',action='store_true')
        parser.add_argument('--gateway-delay',type=float,default=0)
        args=parser.parse_args()
        if not 1<=args.cases<=100000 or not 1<=args.import_rows<=60000 or not 1<=args.iterations<=50:parser.error('FIXTURE_BOUNDS_INVALID')
        if not 0<=args.gateway_delay<=2:parser.error('FIXTURE_DELAY_INVALID')
        main(args)
