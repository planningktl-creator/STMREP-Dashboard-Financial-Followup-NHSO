"""Disposable PostgreSQL/pgweb/container acceptance. Never uses hospital endpoints."""
import json
import os
import re
from pathlib import Path
import sqlite3
import subprocess
import sys
import time
import uuid
import hashlib
import requests

ROOT=Path(__file__).resolve().parent.parent
COMPOSE=['docker','compose','-p','stmrep-release-test','-f',str(ROOT/'deploy/compose.test.yaml')]


def command(args, input=None):
    return subprocess.run(args,cwd=ROOT,input=input,stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=True).stdout


def compose(*args,input=None):return command(COMPOSE+list(args),input)


def wait(url,ready=True):
    for _ in range(60):
        try:
            response=requests.get(url,timeout=6)
            if response.status_code==200:return response
        except requests.RequestException:pass
        time.sleep(1)
    raise RuntimeError('TEST_SERVICE_NOT_READY')


def main():
    os.environ['PGWEB_URL']='http://127.0.0.1:18831'
    os.environ['APP_MODE']='live'
    os.environ['PGWEB_MIN_INTERVAL']='0'
    os.environ['DATA_DIR']=str(ROOT/'.ci/data')
    from financial.db import Database,ident,json_sql
    from financial.config import Settings
    from financial.worker import Worker
    from repstm.schema import schema_sql
    checks=[]
    try:
        compose('up','-d','postgres','pgweb','app')
        wait('http://127.0.0.1:18830/healthz')
        wait('http://127.0.0.1:18831/api/info')
        db=Database(os.environ['PGWEB_URL'])
        assert db.scalar('SELECT current_database()')=='stmrep_test'
        compose('--profile','live','up','-d','live')
        wait('http://127.0.0.1:18832/healthz')
        assert requests.get('http://127.0.0.1:18832/api/health/ready',timeout=7).status_code==503
        assert requests.get('http://127.0.0.1:18832/healthz',timeout=3).status_code==200
        compose('stop','live')
        checks.append('missing schema returns readiness 503 while liveness remains healthy')
        db.execute(schema_sql());db.migrate();db.migrate()
        checks.append('fresh database migration/replay')
        environment=os.environ.copy()
        command([sys.executable,'-m','scripts.integration_check'])
        checks.append('16 synthetic SQL assertions')
        identity=compose('exec','-T','app','python','-c','import os;print(str(os.getuid())+":"+str(os.getgid()))').strip()
        assert identity==b'10929:10929'
        response=requests.get('http://127.0.0.1:18830/api/health/ready',timeout=6)
        assert response.status_code==200
        page=requests.get('http://127.0.0.1:18830/',timeout=5)
        assert page.status_code==200
        assets=set(re.findall(r'(?:src|href)="(/assets/[^\"]+)"',page.text))
        assert assets and any(asset.endswith('.js') for asset in assets)
        for asset in assets:
            response=requests.get('http://127.0.0.1:18830'+asset,timeout=5)
            assert response.status_code==200 and 'text/html' not in response.headers.get('content-type','')
        assert requests.get('http://127.0.0.1:18830/api/health',timeout=5).status_code==200
        command(['docker','run','--rm','--entrypoint','python','stmrep:release-test','-c',
                 "from pathlib import Path; p=Path('/app'); assert not (p/'.env').exists(); assert not list(p.rglob('*.xls')); assert not list(p.rglob('*.sqlite*')); assert not list((p/'.data').iterdir()); assert not (p/'docs').exists(); print('image_clean')"])
        checks.append('UID/GID 10929:10929; same-origin HTML/assets/API; readiness; image excludes runtime data')
        marker="from pathlib import Path;import sqlite3; p=Path('/app/.data');(p/'archive').mkdir(exist_ok=True);(p/'archive/synthetic.txt').write_text('synthetic-only');c=sqlite3.connect(p/'pending.sqlite');c.execute('CREATE TABLE IF NOT EXISTS pending(id TEXT PRIMARY KEY,payload TEXT)');c.execute(\"INSERT OR IGNORE INTO pending VALUES('SYNTHETIC-UUID','SYNTHETIC-PAYLOAD')\");c.commit();c.close()"
        compose('exec','-T','app','python','-c',marker)
        compose('stop','app');compose('up','-d','--force-recreate','app')
        wait('http://127.0.0.1:18830/healthz')
        assertion="from pathlib import Path;import sqlite3;p=Path('/app/.data');assert (p/'archive/synthetic.txt').read_text()=='synthetic-only';c=sqlite3.connect(p/'pending.sqlite');assert c.execute('SELECT count(*) FROM pending').fetchone()[0]==1;c.close()"
        compose('exec','-T','app','python','-c',assertion)
        backup=compose('exec','-T','app','python','-c',"import io,tarfile,sys;t=tarfile.open(fileobj=sys.stdout.buffer,mode='w|');t.add('/app/.data',arcname='data');t.close()")
        command(['docker','volume','create','stmrep-release-test-restore'])
        command(['docker','run','--rm','-i','--user','0','--entrypoint','python','-v','stmrep-release-test-restore:/restore','stmrep:release-test','-c',"import sys,tarfile; t=tarfile.open(fileobj=sys.stdin.buffer,mode='r|');t.extractall('/restore',filter='data')"],input=backup)
        command(['docker','run','--rm','--entrypoint','python','-v','stmrep-release-test-restore:/restore:ro','stmrep:release-test','-c',assertion.replace('/app/.data','/restore/data')])
        checks.append('SIGTERM/recreate retains volume/archive/checkpoint; volume restore')
        snapshot=str(uuid.uuid4());batch_file=ROOT/'.ci/pending.sqlite';batch_file.parent.mkdir(exist_ok=True)
        db.execute(f"INSERT INTO his.snapshots(id,hcode,dstart,dend) VALUES({ident(snapshot)},'10929','2026-01-01','2026-01-02')")
        class LostResponse:
            def put_records(self,*args):db.put_records(*args);raise RuntimeError('SYNTHETIC_LOST_RESPONSE')
        state=sqlite3.connect(batch_file)
        state.execute('CREATE TABLE IF NOT EXISTS pending(id TEXT PRIMARY KEY,dataset TEXT,rows_json TEXT)')
        state.execute('DELETE FROM pending');state.commit()
        worker=Worker(Settings(data_dir=batch_file.parent),None)
        row={'source_key':'DEMO-RESTORE','payload':{'hn':'DEMO-HN'},'record_hash':'synthetic'}
        try:worker.send_rows(LostResponse(),state,snapshot,'patient',[row])
        except RuntimeError as exc:assert str(exc)=='SYNTHETIC_LOST_RESPONSE'
        pending=state.execute('SELECT id,dataset,rows_json FROM pending').fetchall();assert len(pending)==1
        batch,dataset,raw=pending[0];assert db.put_records(snapshot,dataset,json.loads(raw),batch)['replayed']
        assert db.scalar(f'SELECT count(*) FROM his.records WHERE snapshot_id={ident(snapshot)}')==1
        state.close();checks.append('lost response after real commit/replay uses same UUID')
        dump=compose('exec','-T','postgres','pg_dump','-U','synthetic','-d','stmrep_test','-Fc')
        compose('exec','-T','postgres','createdb','-U','synthetic','stmrep_restored')
        compose('exec','-T','postgres','pg_restore','-U','synthetic','-d','stmrep_restored','--exit-on-error',input=dump)
        restored=compose('exec','-T','postgres','psql','-U','synthetic','-d','stmrep_restored','-At','-c',f"SELECT count(*) FROM his.records WHERE snapshot_id='{snapshot}'::uuid").strip()
        assert restored==b'1';checks.append('PostgreSQL dump/restore preserves synthetic source rows')
        compose('--profile','live','up','-d','live')
        wait('http://127.0.0.1:18832/api/health/ready')
        job=str(uuid.uuid4())
        from financial.queries import QUERY_VERSION,QUERY_FINGERPRINT
        payload={'start':'2026-01-01','end':'2026-01-02','query_registry_version':QUERY_VERSION,'query_registry_fingerprint':QUERY_FINGERPRINT}
        db.execute(f"INSERT INTO followup.jobs(id,kind,actor_ref,payload) VALUES({ident(job)},'HIS_SYNC','SYNTHETIC-NO-SESSION',{json_sql(payload)})")
        for _ in range(20):
            if db.scalar(f'SELECT status FROM followup.jobs WHERE id={ident(job)}')=='waiting_session':break
            time.sleep(1)
        assert db.scalar(f'SELECT status FROM followup.jobs WHERE id={ident(job)}')=='waiting_session'
        compose('stop','live');compose('--profile','live','up','-d','--force-recreate','live')
        wait('http://127.0.0.1:18832/api/health/ready')
        assert db.scalar(f'SELECT count(*) FROM followup.jobs WHERE id={ident(job)}')==1
        checks.append('live worker/session missing and restart preserves job')
        compose('stop','pgweb');started=time.monotonic()
        unavailable=requests.get('http://127.0.0.1:18832/api/health/ready',timeout=7)
        assert unavailable.status_code==503 and time.monotonic()-started<6
        assert requests.get('http://127.0.0.1:18832/healthz',timeout=3).status_code==200
        checks.append('database outage bounded readiness/liveness independent')
        report={'status':'passed','fixture':'synthetic_only','postgres_major':17,'checks':checks}
        (ROOT/'.ci/deployment-result.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
        print(json.dumps(report))
    finally:
        compose('--profile','live','down','--volumes','--remove-orphans')
        command(['docker','volume','rm','stmrep-release-test-restore']) if 'backup' in locals() else None


if __name__=='__main__':main()
