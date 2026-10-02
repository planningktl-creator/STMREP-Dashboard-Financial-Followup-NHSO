import json
import uuid
import requests
from repstm.cli import Packer,State
from repstm.db import Pgweb,body_size

class FakeDB:
    def __init__(self):self.sent=[]
    def apply(self,ident,payload):
        self.sent.append((ident,json.loads(json.dumps(payload))))
        return {'inserted':sum(len(g['rows']) for g in payload['groups'])}

def test_batches_bound_real_encoded_body_and_rows(tmp_path):
    db=FakeDB();state=State(tmp_path/'state.sqlite');pack=Packer(db,state,max_bytes=8192,max_records=5)
    group={'document_key':'a'*64,'sheet_index':0,'kind':'unmapped_rows','columns':['source_row','extra_data']}
    for i in range(21):pack.row(group,[i+1,[[0,1,"ภาษาไทย O'Reilly \\ newline\n"*20]]])
    pack.flush()
    assert sum(len(g['rows']) for _,p in db.sent for g in p['groups'])==21
    assert all(body_size(b,p)<=8192 for b,p in db.sent)
    assert all(sum(len(g['rows']) for g in p['groups'])<=5 for _,p in db.sent)
    assert not state.pending().fetchall()

def test_failure_keeps_exact_pending_batch_for_replay(tmp_path):
    class TimeoutDB:
        def apply(self,ident,payload):raise RuntimeError('timeout after commit')
    state=State(tmp_path/'state.sqlite');pack=Packer(TimeoutDB(),state)
    pack.add('complete','a'*64)
    ident=pack.batch_id
    try:pack.flush()
    except RuntimeError:pass
    pending=state.pending().fetchall()
    assert len(pending)==1 and pending[0][0]==ident
    payload=json.loads(pending[0][1]);fake=FakeDB()
    result=fake.apply(ident,payload);state.acknowledge(ident,payload,result)
    assert fake.sent[0][0]==ident and not state.pending().fetchall()

def test_gateway_timeout_retries_identical_sql(monkeypatch):
    class Response:
        status_code=200
        def raise_for_status(self):pass
        def json(self):return {'rows':[[{'replayed':True}]]}
    class Session:
        def __init__(self):self.calls=[]
        def post(self,url,**kwargs):
            self.calls.append(kwargs['data']['query'])
            if len(self.calls)==1:raise requests.Timeout()
            return Response()
    monkeypatch.setattr('repstm.db.time.sleep',lambda _:None)
    session=Session();db=Pgweb('https://example.test',session=session)
    assert db.apply(uuid.uuid4(),{'run_id':str(uuid.uuid4())})['replayed']
    assert session.calls[0]==session.calls[1]
