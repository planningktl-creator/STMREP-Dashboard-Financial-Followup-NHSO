import threading
import time
from contextlib import nullcontext
from datetime import date
import uuid

import pytest

from financial.db import database_request, scoped_database
from financial.limits import TemporaryBudget
from financial.repository import Repository
from financial.config import Settings
from repstm.gateway import Gate


def test_foreground_and_lease_precede_next_background_batch():
    gate=Gate();order=[]
    def run(priority,label):
        with gate.slot(priority,0):order.append(label)
    with gate.slot(1,0):
        a=threading.Thread(target=run,args=(1,'batch'));a.start()
        b=threading.Thread(target=run,args=(0,'reader'));b.start()
        until=time.monotonic()+1
        while len(gate.waiters)!=2 and time.monotonic()<until:time.sleep(.001)
        assert len(gate.waiters)==2
    a.join(1);b.join(1)
    assert order==['reader','batch']


def test_gateway_deadline_does_not_cancel_inflight_batch():
    gate=Gate();errors=[]
    def waiting():
        try:
            with gate.slot(0,0,time.monotonic()+.02):raise AssertionError()
        except RuntimeError as exc:errors.append(str(exc))
    with gate.slot(1,0):
        thread=threading.Thread(target=waiting);thread.start();thread.join(1)
        assert gate.active
    assert errors==['REPORT_TIMEOUT'] and not gate.waiters and not gate.active


def test_gateway_releases_slot_after_failure():
    gate=Gate()
    with pytest.raises(ValueError):
        with gate.slot(0,0):raise ValueError()
    with gate.slot(1,0):assert gate.active


def test_scoped_connections_nested_reused_and_closed_on_error(monkeypatch):
    made=[]
    class DB:
        def __init__(self,url):self.closed=False;made.append(self)
        def close(self):self.closed=True
    monkeypatch.setattr('financial.db.Database',DB)
    @database_request
    def nested():return scoped_database('synthetic')
    @database_request
    def request():
        first=scoped_database('synthetic')
        assert nested() is first and not first.closed
        raise ValueError()
    with pytest.raises(ValueError):request()
    assert len(made)==1 and made[0].closed
    nested()
    assert len(made)==2 and made[1].closed


def test_scoped_connections_never_shared_between_threads(monkeypatch):
    made=[];barrier=threading.Barrier(2)
    class DB:
        def __init__(self,url):made.append(self)
        def close(self):pass
    monkeypatch.setattr('financial.db.Database',DB)
    @database_request
    def request():
        db=scoped_database('synthetic');barrier.wait(timeout=1)
        assert scoped_database('synthetic') is db
    threads=[threading.Thread(target=request) for _ in range(2)]
    for t in threads:t.start()
    for t in threads:t.join(2)
    assert len(made)==2 and made[0] is not made[1]


def test_temporary_budget_bounds_unknown_and_concurrent_uploads(tmp_path):
    budget=TemporaryBudget(100)
    budget.reserve(75,tmp_path,0)
    with pytest.raises(Exception,match='TEMPORARY_STORAGE_BUSY'):budget.reserve(26,tmp_path,0)
    budget.release(75);budget.reserve(100,tmp_path,0);budget.release(100)
    assert budget.reserved==0


def test_temporary_low_disk_is_distinct_from_busy(tmp_path,monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setattr('financial.limits.shutil.disk_usage',lambda _:SimpleNamespace(free=20))
    budget=TemporaryBudget(100)
    with pytest.raises(Exception,match='TEMPORARY_STORAGE_LOW'):budget.reserve(15,tmp_path,10)
    assert budget.reserved==0


def test_overview_sql_contains_all_observations_and_one_materialized_scope():
    repo=Repository(Settings())
    sql=repo.overview_sql('false',None,date(2026,1,1),date(2026,1,31))
    assert sql.count('WITH scoped AS MATERIALIZED')==1
    assert all(key in sql for key in ['monthly_totals','refresh_status','his.issues','ingest.files','rule_packs','unallocated_dates'])
    assert '::text AS his_charge_amount' in sql


def test_search_prefix_preserves_literal_percent_underscore():
    import base64
    sql=Repository(Settings()).condition(str(uuid.uuid4()),None,None,search='00_%')
    assert base64.b64encode(b'00!_!%%').decode() in sql
    assert "ESCAPE '!'" in sql
    numeric=Repository(Settings()).condition(str(uuid.uuid4()),None,None,search='0000123')
    assert 'position(' not in numeric and 'c.hn LIKE' in numeric


def test_background_progress_after_eight_foreground_requests():
    gate=Gate();gate.foreground_streak=8;order=[]
    def run(priority):
        with gate.slot(priority,0):order.append(priority)
    with gate.slot(0,0):
        threads=[threading.Thread(target=run,args=(p,)) for p in (0,2)]
        for t in threads:t.start()
        until=time.monotonic()+1
        while len(gate.waiters)!=2 and time.monotonic()<until:time.sleep(.001)
        assert len(gate.waiters)==2
    for t in threads:t.join(1)
    assert order==[2,0]


def test_successful_upload_persists_manifest_and_byte_count(tmp_path,monkeypatch):
    from fastapi.testclient import TestClient
    from financial.main import create_app
    from scripts.synthetic_workbook import write_rep
    fixture=write_rep(tmp_path/'fixture.xls',3)
    audits=[]
    class DB:
        def rows(self,_):return []
        def execute(self,_):pass
        def audit(self,*args):audits.append(args)
    app=create_app(Settings(mode='demo',cookie_secure=False,worker_enabled=False,data_dir=tmp_path/'data',minimum_free_bytes=0))
    monkeypatch.setattr(app.state.repository,'db',lambda:DB(),raising=False)
    with TestClient(app) as client:
        connected=client.post('/api/session/demo').json()
        next(iter(app.state.sessions.active.values())).demo=False
        key=str(uuid.uuid4())
        with fixture.open('rb') as f:
            response=client.post('/api/imports/uploads',headers={'x-csrf-token':connected['csrf'],'idempotency-key':key},files={'files':('eclaim_10929_SYNTHETIC.xls',f)})
        assert response.status_code==202 and response.json()=={'job_id':key,'files':1}
        assert audits[0][-1]=={'files':1,'bytes':fixture.stat().st_size}
        stored=list((tmp_path/'data').rglob('*.xls'))
        assert len(stored)==1 and stored[0].read_bytes()==fixture.read_bytes()
        assert not list((tmp_path/'data').rglob('*.partial'))
