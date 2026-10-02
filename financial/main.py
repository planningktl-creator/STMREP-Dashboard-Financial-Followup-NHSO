from __future__ import annotations

from contextlib import asynccontextmanager
import asyncio
from datetime import date, datetime
import hashlib
import json
from pathlib import Path
import re
import secrets
from typing import Literal
import uuid
import time
import shutil
import tempfile

from fastapi import FastAPI, Depends, File, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator
from starlette.concurrency import run_in_threadpool

from .bms import Sessions, Session, BmsError
from .config import Settings, ROOT
from .db import Database, literal, ident, json_sql, canonical, database_request
from .demo import DemoRepository
from .domain import scenario, backtest, number
from .repository import Repository, json_values
from .worker import Worker
from .limits import RequestBodyLimit, TemporaryBudget
from .queries import QUERY_VERSION,QUERY_FINGERPRINT
from .operations import VERSION, BUILD_REVISION, readiness as operational_readiness, event, counters, monitor_loop, resource_metrics
from repstm.db import REQUEST_DEADLINE, gateway_counters


class Connect(BaseModel):
    session_code: str = Field(min_length=1,max_length=512)
    marketplace_token: str | None = Field(default=None,max_length=2048)


class Sync(BaseModel):
    start: date
    end: date
    request_id: uuid.UUID


class TaskBody(BaseModel):
    case_id: int = Field(gt=0)
    reason: str = Field(min_length=1,max_length=100)
    status: Literal['open','in_progress','waiting','resolved']='open'
    team: str = Field(default='ทีมเรียกเก็บ',max_length=100)
    due_date: date | None = None
    note: str = Field(default='',max_length=2000)


class ObservationBody(BaseModel):
    case_id: int = Field(gt=0)
    id: uuid.UUID
    event_type: Literal['SUBMISSION','APPEAL_SENT','CASH_RECEIPT','DEADLINE']
    occurred_at: datetime
    amount: str | None = None
    source_ref: str = Field(min_length=3,max_length=500)
    verification: Literal['unverified','reviewed']='unverified'
    component_key: str = Field(default='case_total',min_length=1,max_length=100)
    receipt_total: str | None = None

    @field_validator('occurred_at')
    @classmethod
    def timezone_required(cls,value):
        if value.tzinfo is None:raise ValueError('Timezone is required')
        return value

    @field_validator('amount','receipt_total')
    @classmethod
    def decimal_required(cls,value):
        n=number(value)
        return str(n) if n is not None else None


class AppealBody(BaseModel):
    case_id: int = Field(gt=0)
    claim_id: int = Field(gt=0)
    reason: str = Field(min_length=3,max_length=2000)
    id: uuid.UUID


class AppealResult(BaseModel):
    outcome: Literal['approved','partial','rejected']
    effect_type: Literal['DELTA','REPLACEMENT']
    statement_row_ids: list[int] = Field(min_length=1,max_length=200)
    source_ref: str = Field(min_length=3,max_length=500)


class ScenarioBody(BaseModel):
    volume: str
    charge_per_case: str | None = None
    cost_per_case: str | None = None
    verified_recovery_per_case: str | None = None


def valid_range(start,end):
    if end<start or (end-start).days>5*366:
        raise HTTPException(422,'INVALID_DATE_RANGE')


def create_app(settings=None):
    settings=settings or Settings.from_env()
    sessions=Sessions(settings)
    repository=DemoRepository() if settings.mode=='demo' else Repository(settings)
    worker=Worker(settings,sessions)
    temporary_budget=TemporaryBudget()

    @asynccontextmanager
    async def lifespan(app):
        settings.data_dir.mkdir(parents=True,exist_ok=True)
        app.state.draining=False
        worker.start()
        monitor=asyncio.create_task(monitor_loop())
        try:
            yield
        finally:
            app.state.draining=True
            monitor.cancel()
            try:await monitor
            except asyncio.CancelledError:pass
            await asyncio.to_thread(worker.close)
            sessions.client.close()

    app=FastAPI(title='STMREP Financial Follow-up NHSO',version=VERSION,lifespan=lifespan,
                docs_url='/api/docs' if settings.mode=='demo' else None,openapi_url='/api/openapi.json' if settings.mode=='demo' else None)
    app.state.settings=settings;app.state.sessions=sessions;app.state.repository=repository;app.state.worker=worker
    app.state.draining=False
    app.add_middleware(RequestBodyLimit,max_bytes=settings.max_upload_bytes+1024*1024)

    @app.exception_handler(BmsError)
    async def bms_error(request,exc):
        return JSONResponse({'error':exc.code},status_code=exc.status)

    @app.exception_handler(Exception)
    async def safe_error(request,exc):
        if str(exc)=='REPORT_TIMEOUT':return JSONResponse({'error':'REPORT_TIMEOUT'},503)
        safe_codes=('OBSERVATION_ID_COLLISION','RECEIPT_TOTAL_COLLISION','RECEIPT_OVER_ALLOCATED','CASH_ALLOCATION_SIGN_MISMATCH','APPEAL_ID_COLLISION','APPEAL_RESULT_IMMUTABLE','RESULT_ROWS_NOT_CURRENT_SAME_CLAIM','RESULT_INCLUDES_BASELINE','RESULT_ALREADY_ATTRIBUTED','APPEAL_BASELINE_UNKNOWN','DUPLICATE_RESULT_ROWS','CLAIM_NOT_UNIQUELY_LINKED','REQUEST_ID_COLLISION')
        for code in safe_codes:
            if re.search(r'\b'+code+r'\b',str(exc)):
                return JSONResponse({'error':code},status_code=409)
        return JSONResponse({'error':'SERVICE_UNAVAILABLE','reference':str(uuid.uuid4())},status_code=503)

    @app.middleware('http')
    async def perimeter(request,call_next):
        temporary_reservation=0
        if app.state.draining and request.method not in ('GET','HEAD','OPTIONS'):
            return JSONResponse({'error':'SERVICE_DRAINING'},503)
        if request.url.path.startswith('/api/') and request.method not in ('GET','HEAD','OPTIONS'):
            if request.url.path=='/api/imports/uploads':
                # Authenticate before multipart parsing allocates temporary files.
                try:upload_session=sessions.get(request.cookies.get('stmrep_session'))
                except BmsError as exc:return JSONResponse({'error':exc.code},exc.status)
                if upload_session.demo:return JSONResponse({'error':'DEMO_DOES_NOT_ACCEPT_PATIENT_FILES'},409)
                if not secrets.compare_digest(request.headers.get('x-csrf-token',''),upload_session.csrf):
                    return JSONResponse({'error':'CSRF_TOKEN_REQUIRED'},403)
            origin=request.headers.get('origin')
            if origin and origin not in settings.origins:
                return JSONResponse({'error':'ORIGIN_REJECTED'},403)
            length=request.headers.get('content-length')
            if length:
                try:size=int(length)
                except ValueError:return JSONResponse({'error':'CONTENT_LENGTH_INVALID'},400)
                if size<0:return JSONResponse({'error':'CONTENT_LENGTH_INVALID'},400)
                if size>settings.max_upload_bytes+1024*1024:
                    return JSONResponse({'error':'UPLOAD_TOO_LARGE'},413)
        timed=request.method=='GET' and request.url.path.startswith('/api/') and not request.url.path.startswith('/api/health')
        if request.url.path=='/api/imports/uploads' and request.method=='POST':
            temporary_reservation=int(request.headers.get('content-length') or settings.max_upload_bytes+1024*1024)
            try:
                await asyncio.to_thread(temporary_budget.reserve,temporary_reservation,Path(tempfile.gettempdir()),settings.minimum_free_bytes)
            except HTTPException as exc:
                event(exc.detail)
                return JSONResponse({'error':exc.detail},exc.status_code)
        deadline_token=REQUEST_DEADLINE.set(time.monotonic()+max(.01,settings.report_timeout-1)) if timed else None
        try:
            response=await asyncio.wait_for(call_next(request),settings.report_timeout) if timed else await call_next(request)
        except TimeoutError:
            event('REPORT_TIMEOUT');response=JSONResponse({'error':'REPORT_TIMEOUT'},503)
        except Exception as exc:
            event('REQUEST_FAILED');response=await safe_error(request,exc)
        finally:
            if deadline_token is not None:REQUEST_DEADLINE.reset(deadline_token)
            if temporary_reservation:temporary_budget.release(temporary_reservation)
        response.headers['Cache-Control']=('no-store' if request.url.path.startswith('/api/') or request.url.path=='/healthz'
                                           else 'public, max-age=31536000, immutable' if request.url.path.startswith('/assets/') else 'no-cache')
        response.headers['Referrer-Policy']='no-referrer'
        response.headers['X-Content-Type-Options']='nosniff'
        response.headers['X-Frame-Options']='SAMEORIGIN'
        response.headers['Content-Security-Policy']="default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'self'"
        return response

    def authenticated(request:Request):
        return sessions.get(request.cookies.get('stmrep_session'))

    def authorized(request:Request,session:Session=Depends(authenticated)):
        if not secrets.compare_digest(request.headers.get('x-csrf-token',''),session.csrf):
            raise HTTPException(403,'CSRF_TOKEN_REQUIRED')
        return session

    def session_response(response,session):
        response.set_cookie('stmrep_session',session.cookie,httponly=True,secure=settings.cookie_secure,
                            samesite='strict',max_age=max(1,int(session.expires_at-__import__('time').time())))
        return {'hospital':session.hospital,'csrf':session.csrf,'mode':'demo' if session.demo else 'live',
                'expires_at':session.expires_at,'actor_kind':'BMS_SESSION' if not session.demo else 'SYNTHETIC'}

    @app.get('/api/health')
    @app.get('/healthz')
    @database_request
    def health():return {'status':'ok','mode':settings.mode,'hospital':settings.hospital,'version':VERSION,'build_revision':BUILD_REVISION}

    @app.get('/api/health/ready')
    async def ready():
        body,status=await operational_readiness(settings,worker,app.state.draining)
        return JSONResponse(body,status)

    @app.get('/api/operations')
    @database_request
    def operations(session:Session=Depends(authenticated)):
        disk=shutil.disk_usage(settings.data_dir)
        jobs=[] if session.demo else repository.db().rows("SELECT status,count(*) AS count,count(*) FILTER(WHERE status IN ('queued','inspecting','importing','syncing','refreshing','verifying') AND coalesce((progress->>'observed_at')::timestamptz,created_at)<now()-interval '10 minutes') AS stalled FROM followup.jobs GROUP BY status")
        return {'events':counters(),'gateway':gateway_counters(),'jobs':jobs,'resources':resource_metrics(),
                'storage':{'total_bytes':disk.total,'free_bytes':disk.free,'low':disk.free<settings.minimum_free_bytes}}

    @app.post('/api/session')
    @database_request
    def connect(body:Connect,response:Response):
        session=sessions.connect(body.session_code,body.marketplace_token)
        return session_response(response,session)

    @app.post('/api/session/demo')
    @database_request
    def demo(response:Response):return session_response(response,sessions.demo_session())

    @app.get('/api/session')
    @database_request
    def current(session:Session=Depends(authenticated)):
        return {'hospital':session.hospital,'csrf':session.csrf,'mode':settings.mode,'expires_at':session.expires_at,'actor_kind':'BMS_SESSION' if not session.demo else 'SYNTHETIC'}

    @app.delete('/api/session')
    @database_request
    def logout(request:Request,response:Response,session:Session=Depends(authorized)):
        sessions.remove(request.cookies.get('stmrep_session'))
        response.delete_cookie('stmrep_session');return {'status':'logged_out'}

    @app.get('/api/snapshots')
    @database_request
    def snapshots(session:Session=Depends(authenticated)):return {'items':repository.snapshots()}

    @app.get('/api/overview')
    @database_request
    def overview(start:date,end:date,snapshot_id:uuid.UUID|None=None,session:Session=Depends(authenticated)):
        valid_range(start,end)
        return repository.overview(start,end,str(snapshot_id) if snapshot_id else None)

    @app.get('/api/cases')
    @database_request
    def cases(start:date,end:date,snapshot_id:uuid.UUID|None=None,care:Literal['IP','OP']|None=None,
              status:str|None=None,search:str|None=None,cursor:int=0,limit:int=50,session:Session=Depends(authenticated)):
        valid_range(start,end)
        if cursor<0 or not 1<=limit<=100 or (search and len(search)>100) or (status and len(status)>100):raise HTTPException(422,'INVALID_FILTER')
        return repository.cases(start,end,str(snapshot_id) if snapshot_id else None,care,status,search,cursor,limit)

    @app.get('/api/cases/{case_id}')
    @database_request
    def case_detail(case_id:int,session:Session=Depends(authenticated)):
        result=repository.case(case_id)
        if result is None:raise HTTPException(404,'CASE_NOT_FOUND')
        return result

    @app.get('/api/cases/{case_id}/lines')
    @database_request
    def lines(case_id:int,cursor:int=0,limit:int=50,session:Session=Depends(authenticated)):
        if cursor<0 or not 1<=limit<=100:raise HTTPException(422,'INVALID_CURSOR')
        items=repository.case_lines(case_id,cursor,limit)
        return {'items':items[:limit],'next_cursor':items[limit-1]['id'] if len(items)>limit else None}

    @app.get('/api/orphans')
    @database_request
    def orphans(start:date,end:date,cursor:int=0,limit:int=50,snapshot_id:uuid.UUID|None=None,session:Session=Depends(authenticated)):
        valid_range(start,end)
        if cursor<0 or not 1<=limit<=100:raise HTTPException(422,'INVALID_CURSOR')
        return repository.orphan_claims(start,end,cursor,limit,str(snapshot_id) if snapshot_id else None)

    @app.get('/api/quality')
    @database_request
    def quality(snapshot_id:uuid.UUID|None=None,session:Session=Depends(authenticated)):
        return repository.quality(str(snapshot_id) if snapshot_id else None)

    @app.get('/api/rules')
    @database_request
    def rules(session:Session=Depends(authenticated)):return {'items':repository.rule_list()}

    @app.get('/api/dictionary')
    @database_request
    def dictionary(session:Session=Depends(authenticated)):
        path=Path(__file__).with_name('dictionary.json')
        return json.loads(path.read_text(encoding='utf-8')) if path.exists() else {'tables':[]}

    @app.get('/api/jobs')
    @database_request
    def jobs(session:Session=Depends(authenticated)):return {'items':repository.jobs()}

    @app.get('/api/jobs/{job_id}')
    @database_request
    def job(job_id:uuid.UUID,session:Session=Depends(authenticated)):
        result=repository.job(str(job_id))
        if result is None:raise HTTPException(404,'JOB_NOT_FOUND')
        return result

    @app.post('/api/his/sync',status_code=202)
    @database_request
    def sync(body:Sync,session:Session=Depends(authorized)):
        valid_range(body.start,body.end)
        if session.demo:raise HTTPException(409,'DEMO_DOES_NOT_READ_HIS')
        payload={'start':body.start.isoformat(),'end':body.end.isoformat(),
                 'query_registry_version':QUERY_VERSION,'query_registry_fingerprint':QUERY_FINGERPRINT}
        db=repository.db()
        existing=db.rows(f'SELECT payload FROM followup.jobs WHERE id={ident(body.request_id)}')
        if existing and any(json_values(existing[0])['payload'].get(k)!=payload[k] for k in ('start','end')):
            raise HTTPException(409,'REQUEST_ID_COLLISION')
        db.execute(f"INSERT INTO followup.jobs(id,kind,actor_ref,payload) VALUES({ident(body.request_id)},'HIS_SYNC',{literal(session.actor)},{json_sql(payload)}) ON CONFLICT DO NOTHING")
        db.audit(session.actor,'his_sync_requested',str(body.request_id),payload)
        return {'job_id':str(body.request_id)}

    @app.post('/api/imports/uploads',status_code=202)
    async def upload(request:Request,files:list[UploadFile]=File(...),session:Session=Depends(authorized)):
        if session.demo:raise HTTPException(409,'DEMO_DOES_NOT_ACCEPT_PATIENT_FILES')
        if not 1<=len(files)<=20:raise HTTPException(422,'SELECT_1_TO_20_FILES')
        try:job_id=str(uuid.UUID(request.headers.get('idempotency-key','')))
        except ValueError:raise HTTPException(422,'IDEMPOTENCY_KEY_REQUIRED') from None
        def store_files():
            entries=[];total=0
            for file in files:
                filename=file.filename or ''
                if '/' in filename or '\\' in filename or not re.fullmatch(r'(STM_10929_|eclaim_10929_)[^\x00-\x1f/\\]+\.xls',filename,re.IGNORECASE):
                    raise HTTPException(422,'SOURCE_FILENAME_INVALID')
                source='STM' if filename.upper().startswith('STM_') else 'REP'
                target=settings.data_dir/'uploads'/job_id
                target.mkdir(parents=True,exist_ok=True)
                temp=target/(str(uuid.uuid4())+'.partial')
                digest=hashlib.sha256();size=0;magic=b''
                try:
                    with temp.open('wb') as writer:
                        while chunk:=file.file.read(1024*1024):
                            if not magic:magic=chunk[:8]
                            size+=len(chunk);total+=len(chunk)
                            if size>settings.max_file_bytes or total>settings.max_upload_bytes:raise HTTPException(413,'UPLOAD_TOO_LARGE')
                            if shutil.disk_usage(target).free<len(chunk)+settings.minimum_free_bytes:raise HTTPException(503,'STORAGE_LOW')
                            digest.update(chunk);writer.write(chunk)
                    if magic!=bytes.fromhex('D0CF11E0A1B11AE1'):raise HTTPException(422,'BIFF_XLS_REQUIRED')
                    sha=digest.hexdigest();dest=target/sha/filename;dest.parent.mkdir(exist_ok=True)
                    temp.replace(dest)
                    entries.append({'id':str(uuid.uuid4()),'source':source,'filename':filename,'storage_path':str(dest.resolve()),'sha256':sha,'byte_size':size})
                finally:
                    if temp.exists():temp.unlink()
            if len(set((e['filename'],e['sha256']) for e in entries))!=len(entries):raise HTTPException(422,'DUPLICATE_FILES_IN_UPLOAD')
            return entries
        try:
            entries=await run_in_threadpool(store_files)
        finally:
            for file in files:await file.close()
        total=sum(entry['byte_size'] for entry in entries)
        fingerprint=hashlib.sha256(canonical(sorted((e['filename'],e['sha256']) for e in entries)).encode()).hexdigest()
        @database_request
        def persist():
            db=repository.db()
            existing=db.rows(f'SELECT payload FROM followup.jobs WHERE id={ident(job_id)}')
            if existing:
                if json_values(existing[0])['payload'].get('manifest_hash')!=fingerprint:raise HTTPException(409,'REQUEST_ID_COLLISION')
                return
            sql=f"PERFORM pg_advisory_xact_lock(hashtextextended({literal(job_id)},0)); IF EXISTS(SELECT 1 FROM followup.jobs WHERE id={ident(job_id)}) THEN IF NOT EXISTS(SELECT 1 FROM followup.jobs WHERE id={ident(job_id)} AND payload->>'manifest_hash'={literal(fingerprint)}) THEN RAISE EXCEPTION 'REQUEST_ID_COLLISION'; END IF; RETURN; END IF; INSERT INTO followup.jobs(id,kind,actor_ref,payload) VALUES({ident(job_id)},'IMPORT',{literal(session.actor)},{json_sql({'manifest_hash':fingerprint,'import_authorized':False})});"
            for entry in entries:
                sql+=f"INSERT INTO followup.job_files(id,job_id,source,filename,storage_path,sha256,byte_size) VALUES({ident(entry['id'])},{ident(job_id)},{literal(entry['source'])},{literal(entry['filename'])},{literal(entry['storage_path'])},{literal(entry['sha256'])},{entry['byte_size']});"
            db.execute('DO $upload$ BEGIN '+sql+' END $upload$;')
            db.audit(session.actor,'files_uploaded',job_id,{'files':len(entries),'bytes':total})
        await run_in_threadpool(persist)
        return {'job_id':job_id,'files':len(entries)}

    @app.post('/api/jobs/{job_id}/start')
    @database_request
    def start_job(job_id:uuid.UUID,session:Session=Depends(authorized)):
        if session.demo:raise HTTPException(409,'DEMO_JOB_DISABLED')
        db=repository.db()
        count=db.scalar(f"SELECT count(*) FROM followup.job_files WHERE job_id={ident(job_id)} AND status='inspected'")
        if not count:raise HTTPException(409,'NO_INSPECTED_FILES')
        rows=db.rows(f"UPDATE followup.jobs SET status='queued',payload=payload||'{{\"import_authorized\":true}}'::jsonb,pause_requested=false,error_code=NULL,updated_at=now() WHERE id={ident(job_id)} AND kind='IMPORT' AND status='awaiting_import' RETURNING id")
        if not rows:raise HTTPException(409,'JOB_NOT_AWAITING_IMPORT')
        db.audit(session.actor,'import_started',str(job_id),{'files':count})
        return {'status':'queued'}

    @app.post('/api/jobs/{job_id}/pause')
    @database_request
    def pause_job(job_id:uuid.UUID,session:Session=Depends(authorized)):
        if session.demo:raise HTTPException(409,'DEMO_JOB_DISABLED')
        repository.db().execute(f"UPDATE followup.jobs SET pause_requested=true,updated_at=now(),status=CASE WHEN status='queued' THEN 'paused' ELSE status END WHERE id={ident(job_id)} AND status IN ('queued','inspecting','importing','syncing')")
        return {'status':'pause_requested'}

    @app.post('/api/jobs/{job_id}/resume')
    @database_request
    def resume_job(job_id:uuid.UUID,session:Session=Depends(authorized)):
        if session.demo:raise HTTPException(409,'DEMO_JOB_DISABLED')
        rows=repository.db().rows(f"UPDATE followup.jobs SET status='queued',pause_requested=false,error_code=NULL,owner_id=NULL,lease_until=NULL,payload=payload||{json_sql({'resume_actor':session.actor})},updated_at=now() WHERE id={ident(job_id)} AND status IN ('paused','failed','waiting_session') RETURNING id")
        if not rows:raise HTTPException(409,'JOB_NOT_RESUMABLE')
        return {'status':'queued'}

    @app.post('/api/tasks')
    @database_request
    def task(body:TaskBody,session:Session=Depends(authorized)):
        result=repository.case(body.case_id)
        if not result:raise HTTPException(404,'CASE_NOT_FOUND')
        case=result['case'];task_id=str(uuid.uuid4())
        data={'id':task_id,'encounter_key':case['encounter_key'],'reason':body.reason,'status':body.status,'team':body.team,
              'due_date':body.due_date.isoformat() if body.due_date else None,'note':body.note}
        if session.demo:
            existing=next((t for t in repository.tasks if t['encounter_key']==data['encounter_key'] and t['reason']==body.reason),None)
            if existing:existing.update({**data,'id':existing['id']});data=existing
            else:repository.tasks.append(data)
        else:
            db=repository.db()
            rows=db.rows(f"INSERT INTO followup.tasks(id,hcode,encounter_key,reason,status,team,due_date,note,actor_ref) VALUES({ident(task_id)},{literal(case['hcode'])},{literal(case['encounter_key'])},{literal(body.reason)},{literal(body.status)},{literal(body.team)},{literal(body.due_date)}::date,{literal(body.note)},{literal(session.actor)}) ON CONFLICT(hcode,encounter_key,reason) DO UPDATE SET status=excluded.status,team=excluded.team,due_date=excluded.due_date,note=excluded.note,actor_ref=excluded.actor_ref,updated_at=now() RETURNING id::text")
            data['id']=rows[0]['id'];db.audit(session.actor,'task_updated',data['id'],{'case_id':body.case_id,'status':body.status})
        return data

    @app.post('/api/observations')
    @database_request
    def observation(body:ObservationBody,session:Session=Depends(authorized)):
        result=repository.case(body.case_id)
        if not result:raise HTTPException(404,'CASE_NOT_FOUND')
        case=result['case']
        if body.event_type=='CASH_RECEIPT' and (body.receipt_total is None or body.amount is None):raise HTTPException(422,'CASH_TOTAL_AND_ALLOCATION_REQUIRED')
        if body.event_type=='CASH_RECEIPT' and body.verification=='reviewed' and number(body.amount)*number(body.receipt_total)<0:raise HTTPException(422,'CASH_ALLOCATION_SIGN_MISMATCH')
        data={**body.model_dump(mode='json'),'encounter_key':case['encounter_key']}
        if session.demo:
            existing=next((e for e in repository.events if e['id']==str(body.id)),None)
            if existing and existing!=data:raise HTTPException(409,'OBSERVATION_ID_COLLISION')
            if not existing:repository.events.append(data)
        else:
            db=repository.db()
            db.execute(f'SELECT followup.record_observation({ident(body.id)},{literal(session.actor)},{json_sql({**data,"hcode":case["hcode"]})})')
            db.audit(session.actor,'evidence_recorded',str(body.id),{'case_id':body.case_id,'type':body.event_type})
        return {'id':str(body.id),'status':'recorded'}

    @app.get('/api/appeals')
    @database_request
    def appeals(session:Session=Depends(authenticated)):return {'items':repository.appeals()}

    @app.post('/api/appeals')
    @database_request
    def new_appeal(body:AppealBody,session:Session=Depends(authorized)):
        result=repository.case(body.case_id)
        if not result:raise HTTPException(404,'CASE_NOT_FOUND')
        case=result['case']
        if not any(c['claim_id']==body.claim_id and c['link_status']=='linked' for c in result['claims']):raise HTTPException(409,'CLAIM_NOT_UNIQUELY_LINKED')
        if session.demo:
            data={'id':str(body.id),'encounter_key':case['encounter_key'],'claim_id':body.claim_id,'reason':body.reason,'status':'review',
                  'baseline_amount':case['stm_net_amount'],'baseline_rows':[r['id'] for r in result['statements']],'incremental_amount':None,'opened_at':datetime.now().isoformat()}
            if not any(a['id']==data['id'] for a in repository.appeal_data):repository.appeal_data.append(data)
        else:
            db=repository.db()
            db.execute(f'SELECT followup.open_appeal({ident(body.id)},{literal(session.actor)},{int(body.case_id)},{int(body.claim_id)},{literal(body.reason)})')
            db.audit(session.actor,'appeal_opened',str(body.id),{'case_id':body.case_id,'claim_id':body.claim_id})
        return {'id':str(body.id)}

    @app.post('/api/appeals/{appeal_id}/result')
    @database_request
    def appeal_result(appeal_id:uuid.UUID,body:AppealResult,session:Session=Depends(authorized)):
        if session.demo:raise HTTPException(409,'DEMO_HAS_NO_NEW_STATEMENT_EVIDENCE')
        return repository.db().json(f'SELECT followup.resolve_appeal({ident(appeal_id)},{literal(session.actor)},{json_sql(body.model_dump())})')

    @app.post('/api/planning/scenario')
    @database_request
    def planning(body:ScenarioBody,session:Session=Depends(authorized)):
        try:return scenario(**body.model_dump())
        except ValueError:raise HTTPException(422,'INVALID_SCENARIO') from None

    @app.get('/api/planning/forecast')
    @database_request
    def forecast(session:Session=Depends(authenticated)):
        return {'status':'NOT_READY','reason':'HISTORICAL_COMPLETENESS_NOT_CERTIFIED','prediction':None,
                'required':['24 complete consecutive months','same measure and coverage','rolling-origin backtest','error reporting']}

    @app.get('/api/readiness')
    @database_request
    def readiness(session:Session=Depends(authenticated)):
        if session.demo:return {'mode':'demo','synthetic':True,'his':'synthetic','rep_stm':'synthetic','cost':'unverified','cash':'unavailable','forecast':'not_ready'}
        snaps=repository.snapshots()
        return {'mode':'live','hospital':session.hospital,'his':'snapshot_available' if snaps else 'not_synced',
                'latest_snapshot':snaps[0] if snaps else None,'rep_stm':'configured' if settings.pgweb_url else 'not_configured',
                'cost':settings.cost_semantics,'cash':'requires_receipt_evidence','staff':'deferred','forecast':'not_ready'}

    dist=ROOT/'frontend'/'dist'
    if (dist/'assets').exists():app.mount('/assets',StaticFiles(directory=dist/'assets'),name='assets')

    @app.get('/{path:path}',include_in_schema=False)
    @database_request
    def spa(path:str):
        if path.startswith('api/'):raise HTTPException(404,'ENDPOINT_NOT_FOUND')
        if not (dist/'index.html').exists():return JSONResponse({'message':'Build frontend with npm --prefix frontend run build'},503)
        return FileResponse(dist/'index.html')
    return app


app=create_app()
