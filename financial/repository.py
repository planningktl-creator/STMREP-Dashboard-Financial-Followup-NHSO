from __future__ import annotations

from datetime import date, datetime,timedelta
from zoneinfo import ZoneInfo
from decimal import Decimal
import json
import uuid

from .db import Database, literal, ident, json_sql
from .domain import aging, peer_summary, number, ratio
from .rules import evaluate

MONEY_FIELDS = {'his_summary_charge','his_summary_uc','his_summary_paid','his_summary_remain','line_charge',
 'his_charge_amount','observed_item_cost','estimated_item_cost','cost_coverage_rate','rep_expected_amount',
 'rep_nhso_amount','stm_net_amount','submitted_amount','cash_received_amount','rw','adjrw'}
CASE_FIELDS = ['id','snapshot_id','hcode','encounter_key','care_type','hn','cid','vn','an','linked_an','name','sex','age_years','age_band',
 'admitted_at','discharged_at','service_date','fiscal_year_be','ward','department','pttype','nhso_code','pdx','drg','grouper_version',
 'rw','adjrw','los','dchtype','dchstts','identity_status','quality','his_summary_charge','his_summary_uc','his_summary_paid',
 'his_summary_remain','line_count','cost_known_count','estimated_cost_count','line_charge','his_charge_amount','his_charge_basis',
 'observed_item_cost','estimated_item_cost','cost_coverage_rate','linked_claim_count','ambiguous_claim_count','rep_observed_count',
 'rep_accepted_count','rep_expected_amount','rep_nhso_amount','stm_net_amount','statement_rows','submitted_amount',
 'cash_received_amount','first_submitted_at','tracking_status','as_of','task_teams','next_followup_date','open_task_count']
SELECT_CASE = ','.join(f'c.{f}::text AS {f}' if f in MONEY_FIELDS or f in ('snapshot_id',) else f'c.{f}' for f in CASE_FIELDS)


def json_values(row):
    for field in ('coverage','profile','payload','progress','result','quality','definition','baseline_rows','result_rows','evidence','registry_profile','detail','metadata'):
        if field in row and isinstance(row[field],str):
            row[field]=json.loads(row[field])
    return row


def source_complete(snapshot, dataset):
    return bool(snapshot and snapshot.get('coverage',{}).get(dataset,{}).get('state')=='complete')


def protect_denominators(his, snapshot):
    """An unread population is unknown, even if the observed subset is empty."""
    his['observed_counts']={k:his.get(k) for k in ('encounters','patients','op_visits','linked_admission_visits','ip_admissions','missing_hn','missing_pdx')}
    op=source_complete(snapshot,'op');ip=source_complete(snapshot,'ip')
    if not op:
        his['op_visits']=his['linked_admission_visits']=None
    if not ip:
        his['ip_admissions']=his['total_adjrw']=his['avg_los']=his['cmi']=None
    if not (op and ip):
        for field in ('encounters','patients','missing_hn','missing_pdx'):
            his[field]=None
    return his


class Repository:
    def __init__(self, settings):
        self.settings=settings

    def db(self):return Database(self.settings.pgweb_url)

    def snapshots(self):
        return [json_values(r) for r in self.db().rows(f"SELECT id::text AS id,dstart::text,dend::text,status,coverage,registry_profile,cost_semantics,created_at::text,completed_at::text FROM his.snapshots WHERE hcode={literal(self.settings.hospital)} ORDER BY created_at DESC LIMIT 50")]

    def snapshot(self, snapshot_id=None):
        db=self.db()
        where=f' AND id={ident(snapshot_id)}' if snapshot_id else " AND status IN ('ready','partial')"
        rows=db.rows(f"SELECT id::text AS id,dstart::text,dend::text,status,coverage,registry_profile,cost_semantics,completed_at::text AS as_of FROM his.snapshots WHERE hcode={literal(self.settings.hospital)}{where} ORDER BY completed_at DESC NULLS LAST LIMIT 1")
        return json_values(rows[0]) if rows else None

    def condition(self,snapshot,start,end,care=None,status=None,search=None):
        sql=f'c.snapshot_id={ident(snapshot)} AND c.hcode={literal(self.settings.hospital)}'
        if start:sql+=f' AND c.service_date>={literal(start)}::date'
        if end:sql+=f' AND c.service_date<={literal(end)}::date'
        if care in ('IP','OP'):sql+=' AND c.care_type='+literal(care)
        if status=='FOLLOWUP':sql+=" AND (c.tracking_status NOT IN ('MATCHED','NOT_COVERED') OR c.open_task_count>0)"
        elif status:sql+=' AND c.tracking_status='+literal(status)
        if search:sql+=f" AND (position({literal(search)} in coalesce(c.hn,''))>0 OR position({literal(search)} in coalesce(c.an,''))>0 OR position({literal(search)} in coalesce(c.vn,''))>0 OR position(lower({literal(search)}) in lower(coalesce(c.name,'')))>0)"
        return sql

    def meta(self,snapshot,start,end):
        covered=bool(snapshot and snapshot['dstart']<=str(start) and snapshot['dend']>=str(end)
                     and source_complete(snapshot,'op') and source_complete(snapshot,'ip'))
        return {'snapshot_id':snapshot['id'] if snapshot else None,'as_of':snapshot.get('as_of') if snapshot else None,
                'scope':{'start':str(start),'end':str(end)},'source_scope':{'start':snapshot['dstart'],'end':snapshot['dend']} if snapshot else None,
                'coverage':snapshot['coverage'] if snapshot else {},'range_covered':covered,'mode':'live',
                'snapshot_status':snapshot.get('status') if snapshot else 'unavailable',
                'claim_denominator_status':'REQUIRES_VERIFIED_RULES'}

    def derived_stats(self,db,where,snapshot_id):
        sums=','.join('sum('+f+')::text AS '+f for f in ['his_charge_amount','observed_item_cost','estimated_item_cost','rep_expected_amount','rep_nhso_amount','stm_net_amount','submitted_amount','cash_received_amount'])
        # One PostgreSQL statement shares one MVCC snapshot for all derived totals.
        # Materialize the expensive financial view once, rather than per KPI.
        return db.json(f"""WITH scoped AS MATERIALIZED (
            SELECT c.* FROM analytics.case_financials c WHERE {where}
        ) SELECT jsonb_build_object(
         'report_at',CURRENT_TIMESTAMP::text,
         'input_document_ids',(SELECT coalesce(jsonb_agg(id ORDER BY id),'[]'::jsonb) FROM ingest.documents WHERE hcode={literal(self.settings.hospital)} AND status='ready' AND is_current),
         'his',(SELECT to_jsonb(t) FROM (SELECT count(*) AS encounters,count(DISTINCT hn) AS patients,
            count(*) FILTER(WHERE care_type='OP' AND linked_an IS NULL) AS op_visits,
            count(*) FILTER(WHERE care_type='OP' AND linked_an IS NOT NULL) AS linked_admission_visits,
            count(*) FILTER(WHERE care_type='IP') AS ip_admissions,count(*) FILTER(WHERE hn IS NULL) AS missing_hn,
            count(*) FILTER(WHERE pdx IS NULL) AS missing_pdx,sum(adjrw) FILTER(WHERE care_type='IP')::text AS total_adjrw,
            count(adjrw) FILTER(WHERE care_type='IP') AS adjrw_contributing_count,
            avg(los) FILTER(WHERE care_type='IP')::text AS avg_los FROM scoped) t),
         'financial',(SELECT to_jsonb(t) FROM (SELECT {sums},sum(line_count)::bigint AS line_count,
            sum(cost_known_count)::bigint AS cost_known_count,count(his_charge_amount) AS charge_contributing_count,
            count(stm_net_amount) AS stm_contributing_count FROM scoped) t),
         'grouper',(SELECT to_jsonb(t) FROM (SELECT count(DISTINCT grouper_version) AS versions,
            count(*) FILTER(WHERE grouper_version IS NULL) AS missing FROM scoped WHERE care_type='IP') t),
         'trend',(SELECT coalesce(jsonb_agg(to_jsonb(t) ORDER BY month),'[]'::jsonb) FROM (
            SELECT to_char(service_date,'YYYY-MM') AS month,count(*) AS encounters,
            count(*) FILTER(WHERE care_type='IP') AS ip,count(*) FILTER(WHERE care_type='OP' AND linked_an IS NULL) AS op,
            sum(his_charge_amount)::text AS his_charge_amount,sum(rep_nhso_amount)::text AS rep_nhso_amount,
            sum(stm_net_amount)::text AS stm_net_amount,sum(observed_item_cost)::text AS observed_item_cost
            FROM scoped GROUP BY 1) t),
         'statuses',(SELECT coalesce(jsonb_agg(to_jsonb(t) ORDER BY count DESC),'[]'::jsonb) FROM (
            SELECT tracking_status,count(*) AS count FROM scoped GROUP BY 1) t),
         'worklist',(SELECT coalesce(jsonb_agg(to_jsonb(t) ORDER BY id),'[]'::jsonb) FROM (
            SELECT {SELECT_CASE} FROM scoped c WHERE c.tracking_status NOT IN ('MATCHED','NOT_COVERED') OR c.open_task_count>0 ORDER BY c.id LIMIT 8) t)
        )""")

    def overview(self,start,end,snapshot_id=None):
        db=self.db();snap=self.snapshot(snapshot_id);meta=self.meta(snap,start,end)
        statement=db.rows(f"SELECT patient_type,sum(rep_count)::bigint AS rep_count,sum(stm_count)::bigint AS stm_count,sum(billed_amount)::text AS rep_billed_amount,sum(expected_amount)::text AS rep_expected_amount,sum(statement_amount)::text AS statement_amount,min(refreshed_at)::text AS as_of FROM reporting.monthly_totals WHERE hcode={literal(self.settings.hospital)} AND basis='service' AND month>=date_trunc('month',{literal(start)}::date) AND month<=date_trunc('month',{literal(end)}::date) GROUP BY patient_type")
        dirty=db.rows('SELECT (SELECT count(*) FROM reporting.dirty_claims) AS claims,(SELECT count(*) FROM reporting.dirty_months) AS months')[0]
        meta['statement_cache']={'scope':'whole_months','stale':bool(dirty['claims'] or dirty['months']),'dirty':dirty}
        sources=db.rows(f"SELECT d.source,count(*) AS files,count(DISTINCT d.id) AS documents FROM ingest.files f JOIN ingest.documents d ON d.id=f.document_id WHERE d.hcode={literal(self.settings.hospital)} GROUP BY d.source")
        if not snap:
            return {'meta':meta,'his':None,'financial':{'his_charge_amount':None,'observed_item_cost':None,'rep_nhso_amount':None,'stm_net_amount':None,'cash_received_amount':None},
                    'statement':statement,'sources':sources,'trend':[],'status_counts':[],'worklist':[],
                    'completeness':{'status':'HIS_NOT_CONNECTED','submission_rate':None,'rep_rate':None,'stm_rate':None}}
        where=self.condition(snap['id'],start,end)
        derived=self.derived_stats(db,where,snap['id'])
        his=derived['his'];financial=derived['financial']
        meta.update(his_as_of=snap.get('as_of'),as_of=derived['report_at'],
                    rep_stm_input_document_ids=derived['input_document_ids'],aggregate_consistency='single_postgresql_statement')
        financial['cost_coverage_rate']=ratio(financial['cost_known_count'],financial['line_count'])
        his['cmi']=ratio(his['total_adjrw'],his['ip_admissions'],his['adjrw_contributing_count']==his['ip_admissions'])
        grouper=derived['grouper']
        his['grouper_scope']=grouper
        if grouper['versions']!=1 or grouper['missing']:
            his['cmi']=None
        protect_denominators(his,snap)
        his['registry']=snap.get('registry_profile')
        his['unallocated_dates']=db.rows(f"SELECT count(*) FILTER(WHERE service_date IS NULL) AS encounters,count(*) FILTER(WHERE care_type='IP' AND discharged_at IS NULL) AS active_admissions FROM his.cases WHERE snapshot_id={ident(snap['id'])}")[0]
        if not source_complete(snap,'ip'):
            his['unallocated_dates']={'encounters':None,'active_admissions':None}
        trend=derived['trend'];statuses=derived['statuses'];sample=derived['worklist']
        for case in sample:
            json_values(case)
            case['aging']=aging(date.fromisoformat(str(case['service_date'])[:10]) if case.get('service_date') else None,datetime.now(ZoneInfo('Asia/Bangkok')).date())
        reviews=db.rows(f"SELECT code,severity,count(*) AS count FROM his.issues WHERE snapshot_id={ident(snap['id'])} GROUP BY 1,2 ORDER BY 3 DESC")
        rules=self.rule_list()
        # No whole-population rate until eligible denominator and event coverage are verified.
        return {'meta':meta,'his':his,'financial':financial,'statement':statement,'sources':sources,'trend':trend,
                'status_counts':statuses,'worklist':sample,'quality':reviews,
                'completeness':{'status':'REQUIRES_VERIFIED_RULES','verified_rules':sum(r['verification']=='applicability_verified' for r in rules),
                                'submission_rate':None,'rep_rate':None,'stm_rate':None}}

    def cases(self,start,end,snapshot_id=None,care=None,status=None,search=None,cursor=0,limit=50):
        snap=self.snapshot(snapshot_id)
        if not snap:return {'items':[],'next_cursor':None,'meta':self.meta(None,start,end),'count':None}
        where=self.condition(snap['id'],start,end,care,status,search)
        db=self.db()
        rows=db.rows(f'SELECT {SELECT_CASE} FROM analytics.case_financials c WHERE {where} AND c.id>{int(cursor)} ORDER BY c.id LIMIT {int(limit)+1}')
        more=len(rows)>limit;rows=rows[:limit]
        for row in rows:
            json_values(row)
            row['aging']=aging(date.fromisoformat(str(row['service_date'])[:10]) if row.get('service_date') else None,datetime.now(ZoneInfo('Asia/Bangkok')).date())
            row['aging']['basis']='service_date_not_actual_submission_lag'
        count=db.scalar(f'SELECT count(*) FROM his.cases c WHERE '+where.split(' AND c.tracking_status=')[0]) if not status else None
        return {'items':rows,'next_cursor':rows[-1]['id'] if more else None,'meta':self.meta(snap,start,end),'count':count}

    def case(self,case_id):
        db=self.db()
        rows=db.rows(f'SELECT {SELECT_CASE} FROM analytics.case_financials c WHERE c.id={int(case_id)} AND c.hcode={literal(self.settings.hospital)}')
        if not rows:return None
        case=json_values(rows[0]);snapshot=case['snapshot_id']
        lines=db.rows(f"SELECT id,icode,billcode,item_name,unit,quantity::text,unit_price::text,charge_amount::text,observed_item_cost::text,estimated_item_cost::text,estimate_as_of::text,service_date::text,cost_method FROM his.case_lines WHERE case_id={int(case_id)} ORDER BY id LIMIT 51")
        key_field='an' if case['care_type']=='IP' else 'vn';key_value=case['an'] if case['care_type']=='IP' else case['vn']
        diagnoses=db.rows(f"SELECT source_key,payload FROM his.records WHERE snapshot_id={ident(snapshot)} AND dataset={literal('ip_diag' if case['care_type']=='IP' else 'op_diag')} AND payload->>{literal(key_field)}={literal(key_value)} ORDER BY source_key LIMIT 100")
        procedures=db.rows(f"SELECT source_key,payload FROM his.records WHERE snapshot_id={ident(snapshot)} AND dataset={literal('ip_procedure' if case['care_type']=='IP' else 'op_procedure')} AND payload->>{literal(key_field)}={literal(key_value)} ORDER BY source_key LIMIT 100")
        claims=db.rows(f"SELECT l.status AS link_status,l.method,l.evidence,o.claim_id,o.payer_family,o.tran_id,o.rep_no,o.rep_row_id,o.rep_observed,o.rep_accepted,o.error_code,o.billed_amount::text,o.expected_amount::text,o.nhso_amount::text,o.statement_amount::text,o.statement_rows FROM followup.claim_links l JOIN analytics.rep_claim_observations o ON o.claim_id=l.claim_id WHERE l.case_id={int(case_id)} ORDER BY o.claim_id")
        statements=db.rows(f"SELECT t.id,t.claim_id,t.rep_no,t.category,t.service_date::text,t.net_amount::text,d.document_ref,d.reported_at::text,s.name AS sheet,t.source_row FROM reporting.stm_current t JOIN followup.claim_links l ON l.claim_id=t.claim_id AND l.case_id={int(case_id)} JOIN ingest.documents d ON d.id=t.document_id JOIN ingest.sheets s ON s.id=t.sheet_id ORDER BY d.reported_at,t.id LIMIT 200")
        events=db.rows(f"SELECT id::text,event_type,occurred_at::text,amount::text,source_ref,verification,metadata FROM followup.observations WHERE hcode={literal(case['hcode'])} AND encounter_key={literal(case['encounter_key'])} ORDER BY occurred_at")
        tasks=db.rows(f"SELECT id::text,reason,status,team,due_date::text,note,updated_at::text FROM followup.tasks WHERE hcode={literal(case['hcode'])} AND encounter_key={literal(case['encounter_key'])} ORDER BY created_at")
        appeals=self.appeals(case['encounter_key'])
        rules=evaluate(case,lines[:50],self.rule_list(),case['line_count']<=50)
        return {'case':case,'lines':lines[:50],'lines_next_cursor':lines[49]['id'] if len(lines)>50 else None,
                'diagnoses':[json_values(x) for x in diagnoses],'procedures':[json_values(x) for x in procedures],
                'claims':[json_values(x) for x in claims],'statements':statements,'events':[json_values(x) for x in events],
                'tasks':tasks,'appeals':appeals,'rule':rules,'peers':self.peers(case),
                'readmission':self.readmission(case),'instruments':self.instruments(case),
                'truncation':{'diagnoses':len(diagnoses)>=100,'procedures':len(procedures)>=100,'statements':len(statements)>=200},
                'meta':{'snapshot_id':snapshot,'as_of':case['as_of'],'mode':'live'}}

    def case_lines(self,case_id,cursor,limit):
        return self.db().rows(f"SELECT l.id,l.icode,l.billcode,l.item_name,l.unit,l.quantity::text,l.charge_amount::text,l.observed_item_cost::text,l.estimated_item_cost::text,l.cost_method FROM his.case_lines l JOIN his.cases c ON c.id=l.case_id WHERE c.id={int(case_id)} AND c.hcode={literal(self.settings.hospital)} AND l.id>{int(cursor)} ORDER BY l.id LIMIT {int(limit)+1}")

    def readmission(self,case):
        if case['care_type']!='IP' or not case.get('discharged_at') or case['identity_status']!='unique':
            return {'observed':None,'reason':'DISCHARGE_OR_IDENTITY_UNAVAILABLE'}
        rows=self.db().rows(f"SELECT x.encounter_key,x.admitted_at::text FROM his.cases x WHERE x.snapshot_id={ident(case['snapshot_id'])} AND x.hcode={literal(case['hcode'])} AND x.hn={literal(case['hn'])} AND x.identity_status='unique' AND x.care_type='IP' AND x.id<>{int(case['id'])} AND x.admitted_at>{literal(case['discharged_at'])}::timestamptz AND x.admitted_at<={literal(case['discharged_at'])}::timestamptz+interval '28 days' ORDER BY x.admitted_at LIMIT 10")
        snap=self.snapshot(case['snapshot_id'])
        window_end=datetime.fromisoformat(case['discharged_at'].replace(' ','T')).astimezone(ZoneInfo('Asia/Bangkok'))+timedelta(days=28)
        coverage=snap['coverage'].get('ip',{})
        captured=coverage.get('read_started_at')
        observed_through=datetime.fromisoformat(captured.replace('Z','+00:00')) if captured else None
        covered=bool(snap['dend']>=window_end.date().isoformat() and observed_through and observed_through>=window_end
                     and coverage.get('state')=='complete' and coverage.get('admission_dates_covered'))
        return {'observed':True if rows else False if covered else None,'window_complete':covered,'admissions':rows,'scope':'โรงพยาบาลนี้และ snapshot นี้; ไม่สรุปว่าเป็น unplanned readmission'}

    def instruments(self,case):
        db=self.db()
        rows=db.rows(f"WITH actual AS (SELECT billcode,count(*) AS line_count,sum(quantity) AS quantity,sum(charge_amount) AS charge FROM his.case_lines WHERE case_id={int(case['id'])} AND billcode IS NOT NULL AND EXISTS(SELECT 1 FROM followup.instrument_catalog cat WHERE cat.icode=his.case_lines.icode) GROUP BY billcode),reported AS (SELECT i.item_code AS billcode,sum(i.quantity) AS quantity,sum(i.compensation_amount) AS compensation,count(*) AS records FROM eclaim.rep_instrument_items i JOIN followup.claim_links l ON l.claim_id=i.claim_id AND l.case_id={int(case['id'])} AND l.status='linked' JOIN reporting.rep_latest r ON r.id=i.rep_claim_id GROUP BY i.item_code) SELECT coalesce(a.billcode,r.billcode) AS billcode,a.line_count,a.quantity::text AS his_quantity,a.charge::text AS his_charge,r.quantity::text AS rep_quantity,r.compensation::text AS rep_compensation,r.records FROM actual a FULL JOIN reported r USING(billcode) ORDER BY coalesce(a.billcode,r.billcode) LIMIT 101")
        return {'items':rows[:100],'truncated':len(rows)>100,'basis':'catalog identity observed; current rates/eligibility unverified','complete_rate':None}

    def peers(self,case):
        if not case.get('pttype'):
            return {'status':'UNAVAILABLE','reason':'PAYER_MISSING','count':0}
        if case['care_type']=='IP' and (not case.get('drg') or not case.get('grouper_version')):
            return {'status':'UNAVAILABLE','reason':'DRG_VERSION_MISSING','count':0}
        if case['care_type']=='OP' and not case.get('pdx'):
            return {'status':'UNAVAILABLE','reason':'PDX_MISSING','count':0}
        conditions=[f"snapshot_id={ident(case['snapshot_id'])}",f"care_type={literal(case['care_type'])}",f"pttype IS NOT DISTINCT FROM {literal(case['pttype'])}",f"age_band IS NOT DISTINCT FROM {literal(case.get('age_band'))}"]
        conditions.append(f"service_date BETWEEN (SELECT dstart FROM his.snapshots WHERE id={ident(case['snapshot_id'])}) AND (SELECT dend FROM his.snapshots WHERE id={ident(case['snapshot_id'])})")
        if case['care_type']=='IP':
            conditions.extend([f"drg={literal(case['drg'])}",f"grouper_version={literal(case['grouper_version'])}",f"(CASE WHEN los=0 THEN 0 WHEN los<=3 THEN 1 WHEN los<=7 THEN 2 WHEN los<=14 THEN 3 ELSE 4 END)={0 if not case.get('los') else 1 if case['los']<=3 else 2 if case['los']<=7 else 3 if case['los']<=14 else 4}"])
        else:
            conditions.append(f"left(replace(pdx,'.',''),3)=left(replace({literal(case['pdx'])},'.',''),3)")
        rows=self.db().rows(f"SELECT his_charge_amount::text,stm_net_amount::text,observed_item_cost::text,cost_coverage_rate::text FROM analytics.case_financials WHERE {' AND '.join(conditions)} LIMIT 10001")
        if len(rows)>10000:return {'status':'PARTIAL','reason':'COHORT_TOO_LARGE','count':len(rows)}
        result={field:peer_summary(rows,field) for field in ('his_charge_amount','stm_net_amount')}
        result['observed_item_cost']=peer_summary([r for r in rows if number(r['cost_coverage_rate'])==1], 'observed_item_cost')
        return {'status':'OBSERVED_COMPARISON','count':len(rows),'small_sample':len(rows)<20,'summary':result,
                'definition':'IP: payer, DRG/version, age band, LOS band; OP: payer, ICD3, age band',
                'clinical_adjustment':'descriptive_not_risk_adjusted'}

    def rule_list(self):
        return [json_values(r) for r in self.db().rows(f"SELECT id::text,name,version,care_type,payer_code,effective_from::text,effective_to::text,verification,authority_url,authority_clause,review_reference,definition FROM followup.rule_packs ORDER BY name,version")]

    def appeals(self,encounter=None):
        where=f'hcode={literal(self.settings.hospital)}'
        if encounter:where+=' AND encounter_key='+literal(encounter)
        return [json_values(r) for r in self.db().rows(f"SELECT id::text,encounter_key,claim_id,reason,status,baseline_amount::text,baseline_rows,opened_at::text,sent_at::text,outcome,incremental_amount::text,result_rows,effect_type,source_ref FROM followup.appeals WHERE {where} ORDER BY opened_at DESC LIMIT 200")]

    def jobs(self):
        return [json_values(r) for r in self.db().rows('SELECT id::text,kind,status,progress,result,error_code,created_at::text,updated_at::text FROM followup.jobs ORDER BY created_at DESC LIMIT 100')]

    def job(self,job_id):
        rows=self.db().rows(f'SELECT id::text,kind,status,progress,result,error_code,created_at::text,updated_at::text FROM followup.jobs WHERE id={ident(job_id)}')
        if not rows:return None
        result=json_values(rows[0])
        result['files']=[json_values(r) for r in self.db().rows(f'SELECT id::text,source,filename,byte_size,sha256,status,profile FROM followup.job_files WHERE job_id={ident(job_id)} ORDER BY filename')]
        return result

    def quality(self,snapshot=None):
        snap=self.snapshot(snapshot)
        db=self.db()
        rep=db.rows(f"SELECT i.severity,i.code,count(*) AS count FROM ingest.issues i JOIN ingest.documents d ON d.id=i.document_id WHERE d.hcode={literal(self.settings.hospital)} GROUP BY 1,2 ORDER BY 3 DESC")
        his=db.rows(f'SELECT dataset,severity,code,source_key,detail FROM his.issues WHERE snapshot_id={ident(snap["id"])} ORDER BY id LIMIT 200') if snap else []
        return {'snapshot':snap,'his':[json_values(r) for r in his],'rep_stm':rep,
                'message':'Schema presence does not certify source availability, cost semantics or deadlines.'}

    def orphan_claims(self,start,end,cursor=0,limit=50,snapshot=None):
        snap=self.snapshot(snapshot)
        where=f"c.hcode={literal(self.settings.hospital)} AND c.id>{int(cursor)} AND EXISTS(SELECT 1 FROM reporting.rep_current r WHERE r.claim_id=c.id AND r.service_date BETWEEN {literal(start)}::date AND {literal(end)}::date UNION ALL SELECT 1 FROM reporting.stm_current s WHERE s.claim_id=c.id AND s.service_date BETWEEN {literal(start)}::date AND {literal(end)}::date)"
        if snap:where+=f" AND NOT EXISTS(SELECT 1 FROM followup.claim_links l WHERE l.claim_id=c.id AND l.snapshot_id={ident(snap['id'])} AND l.status='linked')"
        rows=self.db().rows(f'SELECT c.id,c.payer_family,c.patient_type,c.tran_id,c.hn,c.an FROM eclaim.claims c WHERE {where} ORDER BY c.id LIMIT {int(limit)+1}')
        return {'items':rows[:limit],'next_cursor':rows[limit-1]['id'] if len(rows)>limit else None,
                'status':'NOT_LINKED_TO_SELECTED_HIS_SNAPSHOT' if snap else 'HIS_UNAVAILABLE'}
