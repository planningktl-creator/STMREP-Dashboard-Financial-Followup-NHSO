from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import threading
import time
from urllib.parse import urlencode
import uuid

from .bms import BmsError
from .db import Database, ident, literal, json_sql, canonical
from .import_service import profile_file, import_manifest, Paused
from .normalize import normalize
from .queries import DATASETS, REGISTRY,QUERY_VERSION,QUERY_FINGERPRINT
from .operations import event


class Worker:
    def __init__(self, settings, sessions):
        self.settings, self.sessions = settings, sessions
        self.owner = str(uuid.uuid4())
        self.stop = threading.Event()
        self.thread = None

    def start(self):
        if self.settings.mode == 'live' and self.settings.worker_enabled and self.settings.pgweb_url:
            self.thread = threading.Thread(target=self.loop, daemon=True, name='financial-worker')
            self.thread.start()

    def close(self):
        self.stop.set()
        if self.thread:
            self.thread.join(timeout=self.settings.shutdown_timeout)
            event('WORKER_STOPPED' if not self.thread.is_alive() else 'WORKER_SHUTDOWN_TIMEOUT')

    def update(self, db, job_id, status=None, progress=None, result=None, error=None, release=False):
        sets = ['updated_at=now()']
        if status is not None:
            sets.append('status=' + literal(status))
        if progress is not None:
            sets.append('progress=progress||' + json_sql({**progress,'observed_at':datetime.now(timezone.utc).isoformat()}))
        if result is not None:
            sets.append('result=' + json_sql(result))
        if error is not None:
            sets.append('error_code=' + literal(error))
        if release:
            sets.extend(['owner_id=NULL', 'lease_until=NULL'])
        db.execute(f"UPDATE followup.jobs SET {','.join(sets)} WHERE id={ident(job_id)} AND owner_id={ident(self.owner)}")

    def paused(self, db, job_id):
        row = db.rows(f'SELECT pause_requested,owner_id::text AS owner FROM followup.jobs WHERE id={ident(job_id)}')[0]
        return row['pause_requested'] or row['owner'] != self.owner or self.stop.is_set()

    def heartbeat(self, job_id, done):
        db = Database(self.settings.pgweb_url)
        while not done.wait(30):
            try:
                db.execute(f"UPDATE followup.jobs SET lease_until=now()+interval '180 seconds',updated_at=now() WHERE id={ident(job_id)} AND owner_id={ident(self.owner)}")
            except Exception:
                # A lost lease is checked before the next batch, never silently reacquired.
                pass

    def loop(self):
        while not self.stop.is_set():
            try:
                db = Database(self.settings.pgweb_url)
                job = db.json(f'SELECT followup.take_job({ident(self.owner)})')
                if not job:
                    self.stop.wait(3)
                    continue
                if self.stop.is_set():
                    self.update(db,job['id'],status='paused',error='SERVICE_DRAINING',release=True)
                    break
                heartbeat_done = threading.Event()
                heartbeat = threading.Thread(target=self.heartbeat,args=(job['id'],heartbeat_done),daemon=True)
                heartbeat.start()
                try:
                    if job['kind'] == 'IMPORT':
                        self.run_import(db, job)
                    else:
                        self.run_his(db, job)
                except Paused:
                    event('JOB_PAUSED')
                    self.update(db,job['id'],status='paused',error='PAUSE_REQUESTED',release=True)
                except BmsError as exc:
                    event('HIS_WAITING_SESSION' if exc.status==401 else 'HIS_FAILED')
                    state = 'waiting_session' if exc.status == 401 else 'failed'
                    if state=='waiting_session' and job['kind']=='HIS_SYNC':
                        db.execute(f"UPDATE his.snapshots SET status='waiting_session' WHERE job_id={ident(job['id'])} AND status='building'")
                    self.update(db,job['id'],status=state,error=exc.code,release=True)
                except Exception as exc:
                    event('JOB_FAILED')
                    # No exception SQL, token, row or payload may enter operational history.
                    self.update(db,job['id'],status='failed',error=type(exc).__name__.upper(),release=True)
                finally:
                    heartbeat_done.set()
            except Exception:
                event('WORKER_GATEWAY_UNAVAILABLE')
                self.stop.wait(8)

    def run_import(self, db, job):
        files = db.rows(f'SELECT * FROM followup.job_files WHERE job_id={ident(job["id"])} ORDER BY filename,id')
        for entry in files:
            if isinstance(entry['profile'],str):
                entry['profile']=json.loads(entry['profile'])
        payload = job['payload']
        if isinstance(payload,str):
            payload=json.loads(payload)
        callback=lambda progress:self.update(db,job['id'],progress=progress)
        check_pause=lambda:self.paused(db,job['id'])
        if not payload.get('import_authorized'):
            for i,entry in enumerate(files):
                if check_pause():
                    raise Paused()
                try:
                    with Path(entry['storage_path']).open('rb') as reader:
                        actual_sha = hashlib.file_digest(reader,'sha256').hexdigest()
                    if actual_sha!=entry['sha256']:
                        raise ValueError('MANIFEST_HASH_CHANGED')
                    profile=profile_file(entry['storage_path'])
                    entry['profile']=profile
                    state='blocked' if profile['errors'] else 'inspected'
                except Exception:
                    profile={'errors':1,'issues':{'WORKBOOK_PARSE_FAILED':1},'rows':{}}
                    entry['profile']=profile
                    state='blocked'
                db.execute(f"UPDATE followup.job_files SET profile={json_sql(profile)},status={literal(state)} WHERE id={ident(entry['id'])}")
                callback({'phase':'inspecting','inspected_files':i+1,'total_files':len(files)})
            result={'files':len(files),'blocked_files':sum(f['profile'].get('errors',0)>0 for f in files)}
            self.update(db,job['id'],status='awaiting_import',result=result,release=True)
            return
        self.update(db,job['id'],status='importing')
        # Files that cannot be mapped stay visible in this job, never become financial rows.
        accepted=[entry for entry in files if not entry['profile'].get('errors',1)]
        result=import_manifest(db,job,accepted,self.settings.data_dir/'checkpoints'/f"{job['id']}.sqlite3",
                               self.settings.data_dir/'archive',callback,check_pause)
        self.update(db,job['id'],status='refreshing',progress={'phase':'refreshing'})
        db.transport.refresh(lambda p:callback(p))
        snapshots=db.rows(f"SELECT id::text AS id FROM his.snapshots WHERE hcode={literal(self.settings.hospital)} AND status IN ('ready','partial') ORDER BY completed_at DESC")
        for snapshot in snapshots:
            if check_pause():raise Paused()
            db.execute(f"SELECT his.rebuild_links({ident(snapshot['id'])})")
        self.update(db,job['id'],status='verifying',progress={'phase':'verifying'})
        failed=0
        for entry in accepted:
            remote=db.rows(f"SELECT id,status,expected_counts,source_counts FROM ingest.documents WHERE fingerprint={literal(entry['profile']['fingerprint'])}")
            state='complete' if remote and remote[0]['status']=='ready' else 'needs_review'
            failed+=int(state!='complete')
            db.execute(f"UPDATE followup.job_files SET status={literal(state)} WHERE id={ident(entry['id'])}")
        result['blocked_files']=len(files)-len(accepted)+failed
        result['verified_files']=len(accepted)-failed
        self.update(db,job['id'],status='completed_with_issues' if result['blocked_files'] else 'completed',result=result,release=True)
        db.audit(job['actor_ref'],'import_completed',job['id'],result)

    def run_his(self, db, job):
        payload=job['payload']
        if isinstance(payload,str):payload=json.loads(payload)
        if payload.get('query_registry_fingerprint') not in (None,QUERY_FINGERPRINT):
            raise BmsError('QUERY_REGISTRY_CHANGED_REQUIRES_NEW_JOB',409)
        session=self.sessions.find_actor(payload.get('resume_actor') or job['actor_ref'])
        if session is None:
            raise BmsError('BMS_SESSION_REQUIRED',401)
        snapshot=str(uuid.uuid5(uuid.UUID(job['id']),'his-snapshot'))
        db.execute(f"INSERT INTO his.snapshots(id,job_id,hcode,dstart,dend,cost_semantics,cost_review) VALUES({ident(snapshot)},{ident(job['id'])},{literal(session.hospital)},{literal(payload['start'])}::date,{literal(payload['end'])}::date,{literal(self.settings.cost_semantics)},{literal(self.settings.cost_review or None)}) ON CONFLICT DO NOTHING")
        db.execute(f"UPDATE his.snapshots SET status='building' WHERE id={ident(snapshot)} AND status='waiting_session'")
        scope={'start':payload['start'],'end':payload['end']}
        state_path=self.settings.data_dir/'checkpoints'/f'{job["id"]}-his.sqlite3'
        state_path.parent.mkdir(parents=True,exist_ok=True)
        state=sqlite3.connect(state_path)
        state.execute('CREATE TABLE IF NOT EXISTS pending(id TEXT PRIMARY KEY,dataset TEXT,rows_json TEXT)')
        try:
            for batch_id,dataset,raw in state.execute('SELECT id,dataset,rows_json FROM pending').fetchall():
                db.put_records(snapshot,dataset,json.loads(raw),batch_id)
                state.execute('DELETE FROM pending WHERE id=?',(batch_id,));state.commit()
            try:
                profile=self.sessions.query(session,'patient_registry',{})[0]
                db.execute(f'UPDATE his.snapshots SET registry_profile={json_sql(profile)} WHERE id={ident(snapshot)}')
            except BmsError as exc:
                if exc.status==401:raise
            current=db.json(f'SELECT coverage FROM his.snapshots WHERE id={ident(snapshot)}') or {}
            for dataset in DATASETS:
                if self.paused(db,job['id']):raise Paused()
                if current.get(dataset,{}).get('state')=='complete':continue
                observed_started=datetime.now(timezone.utc).isoformat()
                try:
                    before=self.sessions.query(session,dataset+'_profile',scope if REGISTRY[dataset+'_profile']['params'] else {})[0]
                    if int(before['rows'])!=int(before['distinct_source_keys']) or int(before['null_source_keys']):
                        current[dataset]={'state':'unverified','reason':'SOURCE_PRIMARY_KEY_NOT_UNIQUE','profile':before}
                        continue
                    cursor=db.scalar(f'SELECT max(source_key COLLATE "C") FROM his.records WHERE snapshot_id={ident(snapshot)} AND dataset={literal(dataset)}')
                    while True:
                        if self.paused(db,job['id']):raise Paused()
                        params={k:scope[k] for k in ('start','end') if k in REGISTRY[dataset]['params']}
                        params.update({'cursor':cursor or '', 'limit':1000})
                        page=self.sessions.query(session,dataset,params)
                        if not page:break
                        rows=[normalize(dataset,row) for row in page]
                        keys=[row['source_key'] for row in rows]
                        if keys!=sorted(set(keys)) or (cursor is not None and keys[0]<=cursor):
                            raise ValueError('SOURCE_CURSOR_NOT_MONOTONIC')
                        self.send_rows(db,state,snapshot,dataset,rows)
                        cursor=keys[-1]
                        self.update(db,job['id'],progress={'phase':'syncing','dataset':dataset,'snapshot_id':snapshot,
                                                          'dataset_rows':db.scalar(f'SELECT count(*) FROM his.records WHERE snapshot_id={ident(snapshot)} AND dataset={literal(dataset)}')})
                        if len(page)<1000:break
                    after=self.sessions.query(session,dataset+'_profile',scope if REGISTRY[dataset+'_profile']['params'] else {})[0]
                    actual=db.scalar(f'SELECT count(*) FROM his.records WHERE snapshot_id={ident(snapshot)} AND dataset={literal(dataset)}')
                    complete=int(before['rows'])==int(after['rows'])==actual
                    current[dataset]={'state':'complete' if complete else 'partial','profile_before':before,'profile_after':after,
                                      'actual_rows':actual,'read_started_at':observed_started,
                                      'read_finished_at':datetime.now(timezone.utc).isoformat(),'source_transaction_consistent':False,
                                      'query_version':QUERY_VERSION,'query_sha256':hashlib.sha256(REGISTRY[dataset]['sql'].encode()).hexdigest(),
                                      'admission_dates_covered':dataset=='ip'}
                except BmsError as exc:
                    if exc.status==401:
                        db.execute(f"UPDATE his.snapshots SET coverage={json_sql(current)},status='waiting_session' WHERE id={ident(snapshot)}")
                        raise
                    if exc.code=='BMS_UNAVAILABLE':
                        # A transport outage is not evidence that every source table is absent.
                        current[dataset]={'state':'unavailable','reason':exc.code}
                        db.execute(f'UPDATE his.snapshots SET coverage={json_sql(current)} WHERE id={ident(snapshot)}')
                        raise
                    current[dataset]={'state':'unavailable','reason':exc.code}
                db.execute(f'UPDATE his.snapshots SET coverage={json_sql(current)} WHERE id={ident(snapshot)}')
            db.execute(f'UPDATE his.snapshots SET coverage={json_sql(current)} WHERE id={ident(snapshot)}')
            result=db.json(f'SELECT his.finalize_snapshot({ident(snapshot)})')
            status=db.scalar(f'SELECT status FROM his.snapshots WHERE id={ident(snapshot)}')
            result['snapshot_id']=snapshot
            self.update(db,job['id'],status='completed' if status=='ready' else 'completed_with_issues',result=result,release=True)
            db.audit(job['actor_ref'],'his_snapshot_completed',snapshot,{'status':status,**result})
        finally:
            state.close()

    def send_rows(self,db,state,snapshot,dataset,rows):
        batch=[]
        def send():
            if not batch:return
            batch_id=str(uuid.uuid4())
            raw=canonical(batch)
            state.execute('INSERT INTO pending VALUES(?,?,?)',(batch_id,dataset,raw));state.commit()
            if self.stop.is_set():raise Paused('SERVICE_DRAINING')
            db.put_records(snapshot,dataset,batch,batch_id)
            state.execute('DELETE FROM pending WHERE id=?',(batch_id,));state.commit()
        for row in rows:
            trial=batch+[row]
            query=f'SELECT his.apply_batch({ident(str(uuid.UUID(int=0)))},{ident(snapshot)},{literal(dataset)},{json_sql(trial)})'
            size=len(urlencode({'query':query}).encode('ascii'))
            if len(trial)>500 or size>256*1024:
                send();batch=[]
                query=f'SELECT his.apply_batch({ident(str(uuid.UUID(int=0)))},{ident(snapshot)},{literal(dataset)},{json_sql([row])})'
                if len(urlencode({'query':query}).encode('ascii'))>256*1024:
                    raise ValueError('HIS_ROW_EXCEEDS_BATCH_LIMIT')
            batch.append(row)
        send()
