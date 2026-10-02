import json
import sqlite3
import uuid
import pytest
from financial.config import Settings
from financial.worker import Worker

class LostResponse:
    def __init__(self):self.committed={};self.calls=[]
    def put_records(self,snapshot,dataset,rows,batch_id):
        self.calls.append(batch_id)
        if batch_id not in self.committed:
            self.committed[batch_id]=rows
            raise RuntimeError('simulated response lost after commit')
        assert self.committed[batch_id]==rows
        return {'replayed':True}

def test_worker_pending_uuid_survives_commit_then_timeout(tmp_path):
    state=sqlite3.connect(tmp_path/'pending.sqlite')
    state.execute('CREATE TABLE pending(id TEXT PRIMARY KEY,dataset TEXT,rows_json TEXT)')
    db=LostResponse();worker=Worker(Settings(data_dir=tmp_path),None);snapshot=str(uuid.uuid4())
    rows=[{'source_key':'DEMO','payload':{'amount':'0.001'},'record_hash':'synthetic'}]
    with pytest.raises(RuntimeError):worker.send_rows(db,state,snapshot,'op',rows)
    pending=state.execute('SELECT id,dataset,rows_json FROM pending').fetchall()
    assert len(pending)==1
    batch,dataset,raw=pending[0];db.put_records(snapshot,dataset,json.loads(raw),batch)
    state.execute('DELETE FROM pending WHERE id=?',(batch,));state.commit()
    assert db.calls==[batch,batch] and len(db.committed)==1

def test_worker_batches_max_500_and_256kb(tmp_path):
    class Recorder:
        def __init__(self):self.rows=[]
        def put_records(self,snapshot,dataset,rows,batch_id):self.rows.append(list(rows))
    state=sqlite3.connect(':memory:');state.execute('CREATE TABLE pending(id TEXT PRIMARY KEY,dataset TEXT,rows_json TEXT)')
    db=Recorder();worker=Worker(Settings(data_dir=tmp_path),None)
    worker.send_rows(db,state,str(uuid.uuid4()),'op',[{'source_key':str(i),'payload':{'thai':'ภาษาไทย'*30},'record_hash':'x'} for i in range(1001)])
    assert sum(map(len,db.rows))==1001 and max(map(len,db.rows))<=500
    assert state.execute('SELECT count(*) FROM pending').fetchone()[0]==0
