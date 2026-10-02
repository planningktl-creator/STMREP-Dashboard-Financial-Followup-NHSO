from repstm.cli import State
import pytest
from repstm.cli import archive,file_sha

def test_atomic_ack_records_row_checkpoint_and_compact_receipt(tmp_path):
    state=State(tmp_path/'state.sqlite')
    payload={'run_id':'00000000-0000-0000-0000-000000000001','groups':[
        {'document_key':'a'*64,'sheet_index':2,'kind':'rep_claims','columns':['source_row','tran_id'],
         'rows':[[6,'001'],[7,'002']]}]}
    ident='00000000-0000-0000-0000-000000000002'
    state.queue(ident,payload)
    assert state.checkpoint('a'*64,2,'rep_claims')==0
    state.acknowledge(ident,payload,{'inserted':2})
    assert state.checkpoint('a'*64,2,'rep_claims')==7
    assert not state.pending().fetchall()
    receipt=state.db.execute('SELECT payload FROM batches WHERE id=?',(ident,)).fetchone()[0]
    assert '"payload_sha256"' in receipt and '"tran_id"' not in receipt

def test_server_block_status_is_reflected_in_local_checkpoint(tmp_path):
    state=State(tmp_path/'state.sqlite')
    parsed={'document':{'key':'a'*64,'expected_counts':{}},'issues':[]}
    state.parsed('example.xls','b'*64,parsed)
    ident='00000000-0000-0000-0000-000000000002'
    payload={'run_id':ident,'_done_files':[{'path':'example.xls','sha256':'b'*64,'errors':0}]}
    state.queue(ident,payload)
    state.acknowledge(ident,payload,{'document_statuses':{'a'*64:'blocked'}})
    assert state.done('example.xls','b'*64)
    assert not state.done('example.xls','b'*64,retry_blocked=True)

def test_archive_is_verified_and_preserves_the_original_snapshot(tmp_path):
    source=tmp_path/'file.xls';source.write_bytes(b'original workbook bytes')
    sha=file_sha(source);stored=archive(source,sha,tmp_path/'archive')
    source.write_bytes(b'changed after archival')
    from pathlib import Path
    assert file_sha(Path(stored))==sha
    Path(stored).write_bytes(b'corrupted archive')
    with pytest.raises(RuntimeError,match='ARCHIVE_HASH_MISMATCH'):archive(source,sha,tmp_path/'archive')
