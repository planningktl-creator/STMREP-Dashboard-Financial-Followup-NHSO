import asyncio
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from fastapi.testclient import TestClient
import pytest
import requests

from financial.config import Settings
from financial.main import create_app
from financial.operations import readiness, storage_check
from financial.worker import Worker
from financial.import_service import Paused
from repstm.db import Pgweb, REQUEST_DEADLINE


def test_readiness_database_schema_storage_worker_and_drain(tmp_path,monkeypatch):
    settings=Settings(data_dir=tmp_path,worker_enabled=False,minimum_free_bytes=0)
    worker=Worker(settings,None)
    monkeypatch.setattr('financial.operations.database_check',lambda _: 'READY')
    assert asyncio.run(readiness(settings,worker,False))[1]==200
    for failure in ('DATABASE_UNAVAILABLE','SCHEMA_MISSING'):
        monkeypatch.setattr('financial.operations.database_check',lambda _:failure)
        result,status=asyncio.run(readiness(settings,worker,False))
        assert status==503 and result['checks']['database']==failure
    monkeypatch.setattr('financial.operations.database_check',lambda _: 'READY')
    monkeypatch.setattr('financial.operations.storage_check',lambda *_:'STORAGE_UNAVAILABLE')
    assert asyncio.run(readiness(settings,worker,False))[1]==503
    monkeypatch.setattr('financial.operations.storage_check',lambda *_:'READY')
    settings.worker_enabled=True
    assert asyncio.run(readiness(settings,worker,False))[0]['checks']['worker']=='WORKER_UNAVAILABLE'
    settings.worker_enabled=False
    assert asyncio.run(readiness(settings,worker,True))[1]==503


def test_readiness_no_retry_short_timeout(monkeypatch):
    from financial.operations import database_check
    seen=[]
    def query(self,sql,retry=True):
        seen.append((retry,self.timeout,REQUEST_DEADLINE.get()-time.monotonic()))
        return {'rows':[[True]]}
    monkeypatch.setattr(Pgweb,'query',query)
    assert database_check('https://gateway.example.invalid')=='READY'
    assert seen[0][0] is False and seen[0][1]==2 and 0<seen[0][2]<=4


def test_storage_probe_cleanup_and_low_space(tmp_path,monkeypatch):
    assert storage_check(tmp_path,0)=='READY' and not list(tmp_path.iterdir())
    assert storage_check(tmp_path,10**30)=='STORAGE_LOW'
    monkeypatch.setattr('financial.operations.tempfile.TemporaryFile',lambda **_:(_ for _ in ()).throw(PermissionError()))
    assert storage_check(tmp_path,0)=='STORAGE_UNAVAILABLE'


def test_draining_rejects_mutations_health_remains_live(tmp_path):
    app=create_app(Settings(mode='demo',worker_enabled=False,data_dir=tmp_path,minimum_free_bytes=0))
    with TestClient(app) as client:
        assert client.get('/api/health/ready').status_code==200
        app.state.draining=True
        assert client.get('/api/health').status_code==200
        assert client.get('/api/health/ready').status_code==503
        assert client.post('/api/session/demo').json()['error']=='SERVICE_DRAINING'


def test_deadline_shared_across_gateway_calls(monkeypatch):
    class Session:
        def post(self,*_,**kwargs):raise requests.Timeout('DO_NOT_LOG_ME')
        def close(self):pass
    db=Pgweb('https://example.invalid',session=Session())
    db.min_interval=0
    token=REQUEST_DEADLINE.set(time.monotonic()+.1)
    try:
        with pytest.raises(RuntimeError,match='REPORT_TIMEOUT'):db.query('SYNTHETIC SELECT')
    finally:REQUEST_DEADLINE.reset(token)


def test_shutdown_persists_unsent_his_uuid(tmp_path):
    state=sqlite3.connect(tmp_path/'pending.sqlite')
    state.execute('CREATE TABLE pending(id TEXT PRIMARY KEY,dataset TEXT,rows_json TEXT)')
    worker=Worker(Settings(data_dir=tmp_path),None);worker.stop.set()
    class MustNotSend:
        def put_records(self,*_):raise AssertionError('sent after shutdown')
    with pytest.raises(Paused):worker.send_rows(MustNotSend(),state,str(uuid.uuid4()),'op',[{'source_key':'DEMO'}])
    pending=state.execute('SELECT id,rows_json FROM pending').fetchall()
    assert len(pending)==1 and uuid.UUID(pending[0][0])
    state.close()


def test_worker_close_waits_for_thread(tmp_path):
    worker=Worker(Settings(data_dir=tmp_path,shutdown_timeout=1),None)
    worker.thread=threading.Thread(target=lambda:worker.stop.wait(1))
    worker.thread.start();worker.close()
    assert worker.stop.is_set() and not worker.thread.is_alive()


def test_report_http_deadline_and_safe_error(tmp_path,monkeypatch):
    app=create_app(Settings(mode='demo',cookie_secure=False,worker_enabled=False,data_dir=tmp_path,report_timeout=.05))
    async def slow():await asyncio.sleep(.2);return []
    app.add_api_route('/api/test-slow',slow)
    app.router.routes.insert(0,app.router.routes.pop())
    with TestClient(app) as client:
        response=client.get('/api/test-slow')
        assert response.status_code==503 and response.json()['error']=='REPORT_TIMEOUT'


def test_invalid_upload_magic_and_filename(tmp_path,monkeypatch):
    app=create_app(Settings(mode='demo',cookie_secure=False,worker_enabled=False,data_dir=tmp_path))
    with TestClient(app) as client:
        response=client.post('/api/session/demo');session=next(iter(app.state.sessions.active.values()))
        session.demo=False
        headers={'x-csrf-token':response.json()['csrf'],'idempotency-key':str(uuid.uuid4())}
        for name,code in [('wrong.xls','SOURCE_FILENAME_INVALID'),('eclaim_10929_DEMO.xls','BIFF_XLS_REQUIRED')]:
            result=client.post('/api/imports/uploads',headers=headers,files={'files':(name,b'SYNTHETIC')})
            assert result.status_code==422 and result.json()['detail']==code
        assert not list(tmp_path.rglob('*.partial'))


def test_operational_middleware_preserves_financial_guard(tmp_path):
    app=create_app(Settings(mode='demo',worker_enabled=False,data_dir=tmp_path))
    def denied():raise RuntimeError('RECEIPT_OVER_ALLOCATED: SYNTHETIC_PRIVATE_DETAIL')
    app.add_api_route('/api/test-denied',denied)
    app.router.routes.insert(0,app.router.routes.pop())
    with TestClient(app) as client:
        response=client.get('/api/test-denied')
        assert response.status_code==409 and response.json()=={'error':'RECEIPT_OVER_ALLOCATED'}
