from pathlib import Path
import json
import time
import uuid
import httpx
import pytest
from fastapi.testclient import TestClient
from financial.bms import Sessions,BmsError
from financial.config import Settings
from financial.main import create_app

@pytest.fixture
def client(tmp_path):
    app=create_app(Settings(mode='demo',cookie_secure=False,worker_enabled=False,data_dir=tmp_path))
    with TestClient(app) as c:yield c

def auth(client):
    response=client.post('/api/session/demo');assert response.status_code==200
    return {'x-csrf-token':response.json()['csrf']}

def test_auth_and_server_boundary(client):
    assert client.get('/api/cases?start=2026-01-01&end=2026-12-31').status_code==401
    h=auth(client)
    assert client.get('/api/session').json()['hospital']=='10929'
    assert client.post('/api/tasks',json={'case_id':1,'reason':'simulated'}).status_code==403
    assert client.post('/api/tasks',headers={**h,'Origin':'https://untrusted.invalid'},json={'case_id':1,'reason':'simulated'}).status_code==403
    assert client.post('/api/sql',headers=h,json={'sql':'select 1'}).status_code in (404,405)
    assert client.get('/api/cases?start=2026-01-01&end=2026-12-31&limit=101').status_code==422

def test_case_task_evidence_and_denominator(client):
    h=auth(client);period='?start=2020-01-01&end=2029-01-01'
    assert client.get('/api/overview'+period).status_code==422
    snap=client.get('/api/snapshots').json()['items'][0]
    period=f'?start={snap["dstart"]}&end={snap["dend"]}'
    overview=client.get('/api/overview'+period).json()
    assert overview['his']['encounters']==120
    assert overview['financial']['observed_item_cost'] is None
    assert overview['completeness']['submission_rate'] is None
    task={'case_id':1,'reason':'simulated task','note':'ข้อมูลจำลอง'}
    first=client.post('/api/tasks',headers=h,json=task).json()
    second=client.post('/api/tasks',headers=h,json={**task,'status':'resolved'}).json()
    assert first['id']==second['id']
    assert len(client.get('/api/cases/1').json()['tasks'])==1
    evidence={'case_id':1,'id':str(uuid.uuid4()),'event_type':'SUBMISSION','occurred_at':'2026-01-01T12:00:00+07:00','amount':'0.001','source_ref':'SIMULATED-EVIDENCE','verification':'reviewed'}
    assert client.post('/api/observations',headers=h,json=evidence).status_code==200
    assert client.post('/api/observations',headers=h,json=evidence).status_code==200
    assert len(client.get('/api/cases/1').json()['events'])==1
    assert client.post('/api/observations',headers=h,json={**evidence,'amount':'99'}).status_code==409
    assert client.post('/api/his/sync',headers=h,json={'start':'2026-01-01','end':'2026-01-02','request_id':str(uuid.uuid4())}).status_code==409
    assert client.get('/api/planning/forecast').json()['prediction'] is None
    assert client.post('/api/planning/scenario',headers=h,json={'volume':'1','charge_per_case':'NaN'}).status_code==422

def fake_bms(hospital='10929',target='https://his.example.invalid',ttl=10):
    def handler(request):
        if request.method=='GET':return httpx.Response(200,json={'MessageCode':200,'result':{'user_info':{'hospital_code':hospital,'bms_url':target,'bms_session_code':'SYNTHETIC_TOKEN'},'expired_second':ttl}})
        return httpx.Response(200,json={'MessageCode':200,'data':[{'version':'PostgreSQL simulated'}],'record_count':1})
    return httpx.Client(transport=httpx.MockTransport(handler))

def test_bms_hospital_host_expiry_query_registry(tmp_path):
    settings=Settings(bms_hosts=('his.example.invalid',),worker_enabled=False,data_dir=tmp_path)
    s=Sessions(settings,fake_bms());session=s.connect('SYNTHETIC_CODE')
    assert session.hospital=='10929' and 'SYNTHETIC_CODE' not in session.actor
    with pytest.raises(BmsError):s.query(session,'sql_from_browser',{})
    with pytest.raises(BmsError):s.query(session,'op',{'sql':'select 1'})
    session.expires_at=time.time()-1
    with pytest.raises(BmsError):s.get(session.cookie)
    with pytest.raises(BmsError):Sessions(settings,fake_bms('00000')).connect('SYNTHETIC')
    with pytest.raises(BmsError):Sessions(settings,fake_bms(target='https://untrusted.invalid')).connect('SYNTHETIC')
    with pytest.raises(BmsError):Sessions(settings,fake_bms(target='http://his.example.invalid')).connect('SYNTHETIC')
    with pytest.raises(BmsError):Sessions(settings,fake_bms(ttl=0)).connect('SYNTHETIC')

def test_demo_upload_rejected_before_any_patient_storage(client,tmp_path):
    h=auth(client)
    result=client.post('/api/imports/uploads',headers={**h,'idempotency-key':str(uuid.uuid4())},files={'files':('eclaim_10929_SIMULATED.xls',b'synthetic')})
    assert result.status_code==409

def test_bms_cursor_and_transient_retry(tmp_path,monkeypatch):
    from financial.queries import REGISTRY
    calls=[]
    def handler(request):
        body=json.loads(request.content);calls.append(body)
        if len(calls)==1:return httpx.Response(503)
        assert body['params']['cursor']['value']==''
        return httpx.Response(200,json={'MessageCode':200,'data':[],'record_count':0})
    from financial.bms import Session
    monkeypatch.setattr('financial.bms.time.sleep',lambda _:None)
    s=Sessions(Settings(data_dir=tmp_path),httpx.Client(transport=httpx.MockTransport(handler)))
    session=Session('SYNTHETIC','SYNTHETIC','https://his.example.invalid','SYNTHETIC',None,'10929',time.time()+60,'SYNTHETIC')
    assert s.query(session,'ward',{'cursor':'','limit':1000})==[]
    assert len(calls)==2 and ':cursor IS NULL' not in REGISTRY['ward']['sql']
    assert 'units AS unit' in REGISTRY['drug']['sql']
    assert 'COLLATE "C"' in REGISTRY['ward']['sql']

def test_bms_adapter_authorization_error_invalidates_session(tmp_path):
    from financial.bms import Session
    client=httpx.Client(transport=httpx.MockTransport(lambda _:httpx.Response(501,json={'MessageCode':401,'Message':'Authorization Error'})))
    sessions=Sessions(Settings(data_dir=tmp_path),client)
    session=Session('SYNTHETIC','SYNTHETIC','https://his.example.invalid','SYNTHETIC',None,'10929',time.time()+600,'SYNTHETIC')
    sessions.active[session.cookie]=session
    with pytest.raises(BmsError,match='BMS_SESSION_EXPIRED'):
        sessions.query(session,'database',{})
    with pytest.raises(BmsError,match='BMS_SESSION_REQUIRED'):
        sessions.get(session.cookie)

def test_streaming_body_limit_and_upload_auth_before_parsing(tmp_path):
    app=create_app(Settings(mode='demo',cookie_secure=False,worker_enabled=False,data_dir=tmp_path,max_upload_bytes=1))
    with TestClient(app) as client:
        body=(b' '*600000 for _ in range(2))
        assert client.post('/api/session',content=body,headers={'content-type':'application/json'}).status_code==413
        assert client.post('/api/imports/uploads',content=b'invalid multipart',headers={'content-type':'multipart/form-data; boundary=invalid'}).status_code==401
