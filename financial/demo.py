"""Explicitly synthetic runtime. Never connects to PostgreSQL or BMS."""
from __future__ import annotations

from copy import deepcopy
from datetime import date, timedelta
from decimal import Decimal
import uuid

from .domain import aging, fiscal_year, money_sum, peer_summary

DEMO_SNAPSHOT = '11111111-1111-4111-8111-111111111111'


class DemoRepository:
    def __init__(self):
        self.data=[];self.tasks=[];self.events=[];self.appeal_data=[];self.job_data=[]
        statuses=['MATCHED','STM_PENDING','REP_REJECTED','SUBMISSION_UNVERIFIED','STATEMENT_PARTIAL','MATCH_REVIEW']
        as_of=date.today()
        for i in range(1,121):
            care='IP' if i%3 else 'OP';status=statuses[i%len(statuses)]
            charge=Decimal(28000+i*793) if care=='IP' else Decimal(750+i*91)
            rep=charge*Decimal('.72') if status not in ('SUBMISSION_UNVERIFIED','MATCH_REVIEW') else None
            stm=rep if status=='MATCHED' else rep*Decimal('.67') if status=='STATEMENT_PARTIAL' else None
            service=as_of-timedelta(days=i)
            self.data.append({'id':i,'snapshot_id':DEMO_SNAPSHOT,'hcode':'10929','encounter_key':f'{care}:DEMO{i:06}',
                'care_type':care,'hn':f'DEMO{i%67:04}','cid':None,'vn':f'DEMOVN{i:06}' if care=='OP' else None,
                'an':f'DEMOAN{i:06}' if care=='IP' else None,'linked_an':None,'name':f'ผู้ป่วยจำลอง {i:03}',
                'sex':str(1+i%2),'age_years':35+i%30,'age_band':'45–64' if i%2 else '15–44',
                'admitted_at':(service-timedelta(days=4)).isoformat()+'T09:00:00+07:00',
                'discharged_at':service.isoformat()+'T10:00:00+07:00' if care=='IP' else None,
                'service_date':service.isoformat(),'fiscal_year_be':fiscal_year(service),'ward':'DEMO-W1' if i%2 else 'DEMO-W2',
                'department':'คลินิกตัวอย่าง','pttype':'DEMO-UCS','nhso_code':'DEMO-UCS','pdx':'DEMO-DX',
                'drg':'DEMO-DRG' if care=='IP' else None,'grouper_version':'DEMO-VERSION','rw':'1.55','adjrw':'1.61','los':4 if care=='IP' else None,
                'dchtype':'DEMO','dchstts':'DEMO','identity_status':'unique','quality':{},
                'line_count':4,'cost_known_count':0,'estimated_cost_count':4,'his_charge_amount':str(charge),
                'his_charge_basis':'service_lines','his_summary_charge':str(charge),'his_summary_uc':None,'his_summary_paid':None,'his_summary_remain':None,
                'line_charge':str(charge),'observed_item_cost':None,'estimated_item_cost':str(charge*Decimal('.46')),
                'cost_coverage_rate':'0','linked_claim_count':0 if status=='SUBMISSION_UNVERIFIED' else 1,
                'ambiguous_claim_count':1 if status=='MATCH_REVIEW' else 0,'rep_observed_count':int(rep is not None),
                'rep_accepted_count':int(rep is not None and status!='REP_REJECTED'),'rep_expected_amount':str(rep) if rep is not None else None,
                'rep_nhso_amount':str(rep) if rep is not None else None,'stm_net_amount':str(stm) if stm is not None else None,
                'statement_rows':int(stm is not None),'submitted_amount':None,'cash_received_amount':None,'first_submitted_at':None,
                'tracking_status':status,'as_of':as_of.isoformat(),'aging':{**aging(service,as_of),'basis':'service_date_not_actual_submission_lag'}})

    def snapshots(self):
        return [{'id':DEMO_SNAPSHOT,'dstart':min(x['service_date'] for x in self.data),'dend':date.today().isoformat(),
                 'status':'synthetic','coverage':{'ip':{'state':'synthetic'},'op':{'state':'synthetic'}},
                 'cost_semantics':'unverified','registry_profile':{'registry_hn':'25000'},'completed_at':date.today().isoformat()}]

    def snapshot(self,snapshot_id=None):return self.snapshots()[0]

    def selection(self,start,end,care=None,status=None,search=None):
        return [deepcopy(c) for c in self.data if str(start)<=c['service_date']<=str(end)
                and (not care or c['care_type']==care) and (not status or (status=='FOLLOWUP' and c['tracking_status']!='MATCHED') or c['tracking_status']==status)
                and (not search or any(search.lower() in str(c.get(f,'')).lower() for f in ('name','hn','an','vn')))]

    def meta(self,start,end):
        return {'mode':'demo','synthetic':True,'snapshot_id':DEMO_SNAPSHOT,'as_of':date.today().isoformat(),
                'scope':{'start':str(start),'end':str(end)},'range_covered':False,'coverage':{'state':'synthetic'},
                'statement_cache':{'stale':False},'claim_denominator_status':'SYNTHETIC_ONLY'}

    def cases(self,start,end,snapshot_id=None,care=None,status=None,search=None,cursor=0,limit=50):
        rows=self.selection(start,end,care,status,search);page=[r for r in rows if r['id']>cursor]
        return {'items':page[:limit],'next_cursor':page[limit-1]['id'] if len(page)>limit else None,
                'count':len(rows),'meta':self.meta(start,end)}

    def overview(self,start,end,snapshot_id=None):
        rows=self.selection(start,end);ip=[x for x in rows if x['care_type']=='IP'];op=[x for x in rows if x['care_type']=='OP']
        fields=['his_charge_amount','observed_item_cost','estimated_item_cost','rep_expected_amount','rep_nhso_amount','stm_net_amount','submitted_amount','cash_received_amount']
        financial={f:money_sum([x[f] for x in rows]) for f in fields};financial.update({'cost_coverage_rate':'0','line_count':len(rows)*4,'cost_known_count':0,
                                                                                   'charge_contributing_count':len(rows),'stm_contributing_count':sum(x['stm_net_amount'] is not None for x in rows)})
        months=sorted(set(r['service_date'][:7] for r in rows));trend=[]
        for month in months:
            group=[r for r in rows if r['service_date'].startswith(month)]
            trend.append({'month':month,'encounters':len(group),'ip':sum(r['care_type']=='IP' for r in group),'op':sum(r['care_type']=='OP' for r in group),
                          **{f:money_sum([r[f] for r in group]) for f in ('his_charge_amount','rep_nhso_amount','stm_net_amount','observed_item_cost')}})
        statuses=[{'tracking_status':s,'count':sum(r['tracking_status']==s for r in rows)} for s in sorted(set(r['tracking_status'] for r in rows))]
        return {'meta':self.meta(start,end),'his':{'encounters':len(rows),'patients':len(set(r['hn'] for r in rows)),
                 'op_visits':len(op),'ip_admissions':len(ip),'missing_hn':0,'missing_pdx':0,'total_adjrw':str(len(ip)*Decimal('1.61')),
                 'cmi':'1.61' if ip else None,'avg_los':'4' if ip else None,'adjrw_contributing_count':len(ip)},
                'financial':financial,'statement':[],'sources':[{'source':'REP','files':106,'documents':106},{'source':'STM','files':178,'documents':175}],
                'trend':trend,'status_counts':statuses,'worklist':[x for x in rows if x['tracking_status']!='MATCHED'][:8],
                'quality':[],'completeness':{'status':'REQUIRES_VERIFIED_RULES','verified_rules':0,'submission_rate':None,'rep_rate':None,'stm_rate':None}}

    def case(self,case_id):
        case=next((deepcopy(c) for c in self.data if c['id']==case_id),None)
        if not case:return None
        lines=[{'id':case_id*10+j,'icode':f'DEMO-ITEM-{j}','billcode':f'DEMO-BILL-{j}','item_name':name,'unit':'หน่วย',
                'quantity':'1','unit_price':str(Decimal(case['his_charge_amount'])/4),'charge_amount':str(Decimal(case['his_charge_amount'])/4),
                'observed_item_cost':None,'estimated_item_cost':str(Decimal(case['estimated_item_cost'])/4),'cost_method':'unverified','estimate_as_of':case['as_of']}
               for j,name in enumerate(('ยาตัวอย่าง','ค่าบริการตัวอย่าง','อุปกรณ์ตัวอย่าง','การตรวจตัวอย่าง'),1)]
        group=[r for r in self.data if r['care_type']==case['care_type']]
        peers={'status':'OBSERVED_COMPARISON','count':len(group),'small_sample':len(group)<20,
               'summary':{f:peer_summary(group,f) for f in ('his_charge_amount','stm_net_amount','observed_item_cost')},'definition':'กลุ่มจำลองสำหรับทดสอบหน้าจอ'}
        return {'case':case,'lines':lines,'lines_next_cursor':None,'diagnoses':[{'payload':{'icd10':'DEMO-DX','diagtype':'1'}}],
                'procedures':[],'claims':[{'claim_id':case_id,'link_status':'linked','payer_family':'DEMO-UCS','tran_id':f'DEMO-TRAN-{case_id}',
                 'rep_no':'DEMO-REP','rep_observed':bool(case['rep_observed_count']),'rep_accepted':bool(case['rep_accepted_count']),
                 'nhso_amount':case['rep_nhso_amount'],'statement_amount':case['stm_net_amount']}] if case['linked_claim_count'] else [],
                'statements':[{'id':case_id,'claim_id':case_id,'net_amount':case['stm_net_amount'],'document_ref':'DEMO-STM','sheet':'ตัวอย่าง','source_row':10}] if case['stm_net_amount'] is not None else [],
                'events':[x for x in self.events if x['encounter_key']==case['encounter_key']],
                'tasks':[x for x in self.tasks if x['encounter_key']==case['encounter_key']],
                'appeals':self.appeals(case['encounter_key']),'rule':{'status':'REVIEW','reason':'NO_VERIFIED_APPLICABLE_RULE','required':None,'expected_amount':None},
                'peers':peers,'meta':self.meta(case['service_date'],case['service_date'])}

    def case_lines(self,case_id,cursor,limit):return [l for l in self.case(case_id)['lines'] if l['id']>cursor][:limit+1]
    def rule_list(self):return []
    def appeals(self,encounter=None):return [deepcopy(x) for x in self.appeal_data if not encounter or x['encounter_key']==encounter]
    def jobs(self):return deepcopy(self.job_data)
    def job(self,job_id):return next((deepcopy(x) for x in self.job_data if x['id']==job_id),None)
    def quality(self,snapshot=None):return {'snapshot':self.snapshot(),'his':[],'rep_stm':[], 'message':'ข้อมูลจำลอง ไม่มีการเชื่อมระบบจริง'}
    def orphan_claims(self,*args,**kwargs):return {'items':[],'next_cursor':None,'status':'SYNTHETIC_ONLY'}
