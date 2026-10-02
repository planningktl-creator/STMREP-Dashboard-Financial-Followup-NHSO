"""Run synthetic SQL assertions in one rolled-back subtransaction. No PHI output."""
from pathlib import Path
import json
import time
import uuid
from financial.config import ROOT,Settings
from financial.db import Database,ident,json_sql,literal
from financial.normalize import normalize
from financial.repository import Repository

def main():
    db=Database(Settings.from_env().pgweb_url);snapshot=str(uuid.uuid4());batch=str(uuid.uuid4())
    datasets={
     'patient':[{'source_key':'DEMO-P','hn':'DEMO-HN','cid':'DEMO-CID','fname':'ผู้ป่วยจำลอง','lname':'ทดสอบ','birthday':'1980-01-01','sex':'1'}],
     'ip':[{'source_key':'DEMO-AN','an':'DEMO-AN','hn':'DEMO-HN','regdate':'2026-01-01','dchdate':'2026-01-05','pttype':'DEMO','drg':'DEMO-DRG','grouper_version':'DEMO-V','adjrw':'1.001'}],
     'op':[{'source_key':'DEMO-OVST','vn':'DEMO-VN','hn':'DEMO-HN','vstdate':'2026-01-01','pttype':'DEMO'}],
     'ip_diag':[{'source_key':'DEMO-D1','an':'DEMO-AN','diagtype':'1','icd10':'DEMO-DX'},{'source_key':'DEMO-D2','an':'DEMO-AN','diagtype':'2','icd10':'DEMO-DX2'}],
     'lines':[{'source_key':'DEMO-L1','an':'DEMO-AN','vn':'DEMO-VN','icode':'DEMO-ITEM','qty':'2','sum_price':'10.001','cost':'5'},{'source_key':'DEMO-L2','an':'DEMO-AN','icode':'DEMO-ITEM','qty':'1','sum_price':'-1.001','cost':'0'}]
    }
    statements=[f"INSERT INTO his.snapshots(id,hcode,dstart,dend,coverage) VALUES({ident(snapshot)},'10929','2026-01-01','2026-01-31','{{\"ip\":{{\"state\":\"complete\"}},\"op\":{{\"state\":\"complete\"}},\"lines\":{{\"state\":\"complete\"}}}}');"]
    for dataset,rows in datasets.items():
        payload=json_sql([normalize(dataset,row) for row in rows]);b=batch if dataset=='patient' else str(uuid.uuid4())
        statements.append(f"PERFORM his.apply_batch({ident(b)},{ident(snapshot)},{literal(dataset)},{payload});")
        if dataset=='patient':statements.append(f"v:=his.apply_batch({ident(b)},{ident(snapshot)},'patient',{payload}); ASSERT (v->>'replayed')::boolean,'batch replay failed';")
    statements.append(f"PERFORM his.finalize_snapshot({ident(snapshot)}); PERFORM his.finalize_snapshot({ident(snapshot)});")
    statements.append(f"ASSERT (SELECT count(*)=2 FROM his.cases WHERE snapshot_id={ident(snapshot)}),'diagnoses changed denominator'; SELECT id INTO c FROM his.cases WHERE snapshot_id={ident(snapshot)} AND care_type='IP'; SELECT id INTO op FROM his.cases WHERE snapshot_id={ident(snapshot)} AND care_type='OP'; ASSERT (SELECT count(*)=2 FROM his.case_lines WHERE case_id=c),'AN line priority failed'; ASSERT (SELECT his_charge_amount=9 AND observed_item_cost IS NULL FROM analytics.case_financials WHERE id=c),'precision / unknown cost failed';")
    # A real schema test uses fake identifiers, documents, rows, amounts only.
    prefix=uuid.uuid4().hex
    statements.append(f"INSERT INTO eclaim.claims(hcode,payer_family,patient_type,tran_id,hn,an,pid) VALUES('10929','DEMO','IP','DEMO-{prefix}','DEMO-HN','DEMO-AN','DEMO-CID') RETURNING id INTO claim;")
    statements.append(f"INSERT INTO ingest.layouts(fingerprint,definition) VALUES('DEMO-{prefix}','{{}}');")
    for source,var,reported in [('REP','dr','2026-01-08'),('STM','ds','2026-01-10')]:
        fp=uuid.uuid4().hex+uuid.uuid4().hex
        statements.append(f"INSERT INTO ingest.documents(fingerprint,logical_key,source,hcode,payer_family,patient_type,reported_at,expected_counts,status,is_current) VALUES('{fp}','DEMO-{source}-{prefix}','{source}','10929','DEMO','IP','{reported}','{{}}','ready',true) RETURNING id INTO {var}; INSERT INTO ingest.sheets(document_id,sheet_index,name,kind,layout_id,physical_rows,data_rows) VALUES({var},0,'DEMO','{source}','DEMO-{prefix}',3,2) RETURNING id INTO {'sr' if source=='REP' else 'ss'};")
    statements.append("INSERT INTO eclaim.rep_claims(document_id,sheet_id,claim_id,source_row,hcode,payer_family,patient_type,tran_id,hn,an,pid,expected_amount,nhso_amount,extra_data) SELECT dr,sr,claim,2,'10929','DEMO','IP',tran_id,'DEMO-HN','DEMO-AN','DEMO-CID',10,10,'{}' FROM eclaim.claims WHERE id=claim;")
    statements.append("INSERT INTO eclaim.stm_claims(document_id,sheet_id,claim_id,source_row,net_amount,extra_data) VALUES(ds,ss,claim,2,10,'{}') RETURNING id INTO base_row;")
    statements.append(f"PERFORM his.rebuild_links({ident(snapshot)}); ASSERT (SELECT status='linked' FROM followup.claim_links WHERE case_id=c AND claim_id=claim),'AN matching failed'; ASSERT (SELECT stm_net_amount=10 AND rep_nhso_amount=10 FROM analytics.case_financials WHERE id=c),'financial aggregation failed';")
    statements.append(f"DELETE FROM his.dirty_claim_links; INSERT INTO reporting.dirty_claims(claim_id) VALUES(claim) ON CONFLICT DO NOTHING; ASSERT EXISTS(SELECT 1 FROM his.dirty_claim_links WHERE claim_id=claim),'durable link queue missing'; ASSERT analytics.refresh_status('10929')->>'state'='pending','partial refresh not visible'; PERFORM his.refresh_links(1); ASSERT NOT EXISTS(SELECT 1 FROM his.dirty_claim_links),'bounded link checkpoint failed'; ASSERT (SELECT status='linked' FROM followup.claim_links WHERE case_id=c AND claim_id=claim),'incremental link differs from rebuild';")
    statements.append("INSERT INTO eclaim.rep_claims(document_id,sheet_id,claim_id,source_row,hcode,payer_family,patient_type,tran_id,hn,an,pid,expected_amount,nhso_amount,extra_data) SELECT dr,sr,claim,3,'10929','DEMO','IP',tran_id,'DEMO-HN','DEMO-AN','DEMO-CID',11,11,'{}' FROM eclaim.claims WHERE id=claim; ASSERT (SELECT rep_observed AND rep_row_id IS NULL FROM analytics.rep_claim_observations WHERE claim_id=claim),'latest tied REP selected incorrectly'; DELETE FROM eclaim.rep_claims WHERE document_id=dr AND source_row=3;")
    statements.append("UPDATE eclaim.claims SET pid='DEMO-CONFLICT' WHERE id=claim;")
    statements.append("ASSERT EXISTS(SELECT 1 FROM his.dirty_claim_links WHERE claim_id=claim),'identity change not queued'; ASSERT his.refresh_links(1)=1,'identity refresh not resumed'; ASSERT (SELECT status='review' FROM followup.claim_links WHERE case_id=c AND claim_id=claim),'incremental identity accepted';")
    statements.append(f"PERFORM his.rebuild_links({ident(snapshot)}); ASSERT (SELECT status='review' FROM followup.claim_links WHERE case_id=c AND claim_id=claim),'patient conflict accepted'; ASSERT (SELECT stm_net_amount IS NULL FROM analytics.case_financials WHERE id=c),'ambiguous money leaked'; UPDATE eclaim.claims SET pid='DEMO-CID' WHERE id=claim; PERFORM his.rebuild_links({ident(snapshot)});")
    encounter='IP:DEMO-AN'
    def event(amount,source,typ='SUBMISSION',stamp='2026-01-02T12:00:00+07:00',total=None):
        return {'hcode':'10929','encounter_key':encounter,'event_type':typ,'occurred_at':stamp,'amount':amount,'source_ref':source,'verification':'reviewed','component_key':'case_total','receipt_total':total}
    for amt,ref,stamp in [('10','DEMO-SUB1','2026-01-02T12:00:00+07:00'),('12','DEMO-SUB2','2026-01-03T12:00:00+07:00')]:
        e=str(uuid.uuid4());data=json_sql(event(amt,ref,stamp=stamp));statements.append(f"PERFORM followup.record_observation({ident(e)},'DEMO-ACTOR',{data}); PERFORM followup.record_observation({ident(e)},'DEMO-ACTOR',{data});")
    statements.append("ASSERT (SELECT submitted_amount=12 FROM analytics.case_financials WHERE id=c),'resubmission counted twice';")
    receipt=json_sql(event('6','DEMO-RECEIPT','CASH_RECEIPT',total='10'))
    statements.append(f"PERFORM followup.record_observation({ident(uuid.uuid4())},'DEMO-ACTOR',{receipt});")
    statements.append(f"BEGIN PERFORM followup.record_observation({ident(uuid.uuid4())},'DEMO-ACTOR',{json_sql(event('5','DEMO-RECEIPT','CASH_RECEIPT',total='10'))}); RAISE EXCEPTION 'assert receipt guard'; EXCEPTION WHEN OTHERS THEN IF SQLERRM NOT LIKE '%RECEIPT_OVER_ALLOCATED%' THEN RAISE; END IF; END;")
    appeal=str(uuid.uuid4());statements.append(f"PERFORM followup.open_appeal({ident(appeal)},'DEMO-ACTOR',c,claim,'DEMO appeal'); ASSERT (SELECT baseline_amount=10 FROM followup.appeals WHERE id={ident(appeal)}),'baseline incorrect'; INSERT INTO eclaim.stm_claims(document_id,sheet_id,claim_id,source_row,net_amount,extra_data) VALUES(ds,ss,claim,3,-2,'{{}}') RETURNING id INTO result_row;")
    statements.append(f"v:=followup.resolve_appeal({ident(appeal)},'DEMO-ACTOR',jsonb_build_object('statement_row_ids',jsonb_build_array(result_row),'outcome','partial','effect_type','DELTA','source_ref','DEMO-APPEAL-RESULT')); ASSERT (v->>'incremental_amount')::numeric=-2,'appeal sign incorrect';")
    statements.append("INSERT INTO followup.tasks(id,hcode,encounter_key,reason,actor_ref) VALUES(gen_random_uuid(),'10929','IP:DEMO-AN','DEMO task','DEMO-ACTOR') RETURNING id INTO task; UPDATE followup.tasks SET status='resolved' WHERE id=task; ASSERT (SELECT count(*)=2 FROM followup.task_history WHERE task_id=task),'task history missing';")
    class QueryRecorder:
        def json(self,sql):self.sql=sql;return {}
    recorder=QueryRecorder()
    Repository(Settings()).derived_stats(recorder,f'c.snapshot_id={ident(snapshot)}',snapshot)
    statements.append(f"v:=({recorder.sql}); ASSERT (v#>>'{{his,encounters}}')::bigint=2 AND (v#>>'{{financial,his_charge_amount}}')::numeric=9 AND (v#>>'{{financial,stm_net_amount}}')::numeric=8 AND (v#>>'{{trend,0,his_charge_amount}}')::numeric=9,'atomic report totals incorrect'; ASSERT jsonb_typeof(v#>'{{financial,his_charge_amount}}')='string' AND (v->'input_document_ids') @> jsonb_build_array(dr,ds),'report precision or lineage missing';")
    statements.append("jit_before:=current_setting('jit'); v:=analytics.report_json('SELECT jsonb_build_object(''jit'',current_setting(''jit''))'); ASSERT v->>'jit'='off','report JIT setting missing'; ASSERT current_setting('jit')=jit_before,'report JIT leaked'; BEGIN PERFORM analytics.report_json('SELECT to_jsonb(1/0)'); EXCEPTION WHEN division_by_zero THEN NULL; END; ASSERT current_setting('jit')=jit_before,'failed report JIT leaked';")
    statements.append("RAISE EXCEPTION 'ROLLBACK_SYNTHETIC_SUCCESS';")
    sql="DO $test$ DECLARE c bigint; op bigint; claim bigint; dr bigint; ds bigint; sr bigint; ss bigint; base_row bigint; result_row bigint; task uuid; v jsonb; jit_before text; BEGIN BEGIN "+'\n'.join(statements)+" EXCEPTION WHEN OTHERS THEN IF SQLERRM<>'ROLLBACK_SYNTHETIC_SUCCESS' THEN RAISE; END IF; END; END $test$;"
    start=time.monotonic();db.execute(sql)
    report={'status':'passed','fixture':'synthetic_only','transaction':'rolled_back','elapsed_seconds':round(time.monotonic()-start,3),
     'checks':['batch replay','snapshot replay','diagnosis denominator','AN priority','precision','unknown cost','AN patient matching','identity quarantine','ambiguous money null','latest submission per component','receipt allocation guard','appeal frozen baseline','signed appeal delta','task history','atomic dashboard counts/totals','decimal report strings/document lineage']}
    report['checks']+=['durable dirty-link queue','bounded incremental refresh','pending financial metadata','identity change queue/resume','latest tied REP has no winner','report JIT scope and error restoration']
    (ROOT/'.ci').mkdir(exist_ok=True)
    (ROOT/'.ci/SQL_INTEGRATION_RESULT.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report))

if __name__=='__main__':main()
