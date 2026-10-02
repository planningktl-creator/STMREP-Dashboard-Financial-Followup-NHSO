"""Finite read-only HOSxP registry. Dataset SQL cannot be supplied by an API caller."""
from __future__ import annotations
import hashlib
import json

QUERY_VERSION='2026-10-02.2'
# Admission-date coverage is needed to observe readmissions discharged after the scope.
TARGET_IP = "SELECT an FROM ipt WHERE (dchdate BETWEEN :start AND :end) OR (regdate BETWEEN :start AND :end) OR (dchdate IS NULL AND regdate<=:end)"
TARGET_OP = "SELECT vn FROM ovst WHERE vstdate BETWEEN :start AND :end"
TARGET_HN = f"SELECT hn FROM ovst WHERE vstdate BETWEEN :start AND :end UNION SELECT hn FROM ipt WHERE an IN ({TARGET_IP})"
DATE_PARAMS = {'start': 'date', 'end': 'date'}
PAGE_PARAMS = {**DATE_PARAMS, 'cursor': 'string', 'limit': 'integer'}
LINE_WHERE = f"(an IN ({TARGET_IP}) OR ((an IS NULL OR an='') AND vn IN ({TARGET_OP})))"

# Money is cast to text at source: no binary floating point round trip.
DATASETS = {
 'patient': ('patient', 'hos_guid', 'hos_guid,hn,cid,pname,fname,lname,sex,birthday,death,deathday,last_update', f'hn IN ({TARGET_HN})'),
 'person': ('person', 'person_id', 'person_id,patient_hn,cid,birthdate,sex,last_update', f'patient_hn IN ({TARGET_HN})'),
 'ip': ('ipt', 'an', 'an,hn,vn,regdate,regtime,dchdate,dchtime,ward,first_ward,pttype,dchtype,dchstts,drg,mdc,rw::text AS rw,adjrw::text AS adjrw,grouper_version,grouper_err,hos_guid', f'an IN ({TARGET_IP})'),
 'op': ('ovst', 'hos_guid', 'hos_guid,vn,hn,an,vstdate,vsttime,pttype,doctor,main_dep,last_dep,ovstist,ovstost', f'vn IN ({TARGET_OP})'),
 'ip_diag': ('iptdiag', 'ipt_diag_id', 'ipt_diag_id,an,hn,diagtype,icd10,diag_no', f'an IN ({TARGET_IP})'),
 'op_diag': ('ovstdiag', 'ovst_diag_id', 'ovst_diag_id,vn,hn,diagtype,icd10,diag_no', f'vn IN ({TARGET_OP})'),
 'ip_procedure': ('iptoprt', 'iptoprt_id', 'iptoprt_id,an,icd9,priority', f'an IN ({TARGET_IP})'),
 'op_procedure': ('ovstoprt', 'ovst_oprt_id', 'ovst_oprt_id,vn,icd9cm', f'vn IN ({TARGET_OP})'),
 'lines': ('opitemrece', 'hos_guid', 'hos_guid,an,vn,hn,icode,qty::text AS qty,unitprice::text AS unitprice,sum_price::text AS sum_price,cost::text AS cost,income,paidst,vstdate,dep_code,last_modified', f"(an IN ({TARGET_IP}) OR ((an IS NULL OR an='') AND vn IN ({TARGET_OP})))"),
 'ip_finance': ('an_stat', 'an', 'an,hn,income::text AS income,uc_money::text AS uc_money,paid_money::text AS paid_money,remain_money::text AS remain_money,discount_money::text AS discount_money', f'an IN ({TARGET_IP})'),
 'op_finance': ('vn_stat', 'vn', 'vn,hn,income::text AS income,uc_money::text AS uc_money,paid_money::text AS paid_money,remain_money::text AS remain_money,discount_money::text AS discount_money', f'vn IN ({TARGET_OP})'),
 'rights': ('ipt_pttype', 'ipt_pttype_id', 'ipt_pttype_id,an,pttype,begin_date,expire_date,hospmain,hospsub,project_code,auth_datetime,claim_service_type_code', f'an IN ({TARGET_IP})'),
 'drg': ('ipt_drg_result', 'ipt_drg_result_id', 'ipt_drg_result_id,an,drg,mdc,rw::text AS rw,adjrw::text AS adjrw,grouper_version,update_datetime,err,warn', f'an IN ({TARGET_IP})'),
 'rep_bridge': ('rep_eclaim_detail', 'rep_eclaim_detail_id', 'rep_eclaim_detail_id,vn,hn,pid,hcode,rep_eclaim_detail_rep_no,rep_eclaim_detail_tran_id,rep_eclaim_detail_patient_type,rep_eclaim_import_datetime', f'vn IN ({TARGET_OP})'),
 'submission_op': ('ovst_eclaim', 'vn', 'vn,upload_status_code,upload_datetime,fdh_ready', f'vn IN ({TARGET_OP})'),
 'submission_nhso': ('ovst_nhso_send', 'vn', 'vn,send_date,send_time,send_done,data_ok,reply_error,nhso_error_code,update_datetime', f'vn IN ({TARGET_OP})'),
 'fdh': ('fdh_claim_status', 'fdh_claim_status_id', 'fdh_claim_status_id,vn,hn,fdh_claim_status_datetime,transaction_uid,fdh_act_amt::text AS fdh_act_amt,fdh_stm_period', f'vn IN ({TARGET_OP})'),
 'pttype': ('pttype', 'pttype', 'pttype,name,nhso_code,nhso_subinscl,export_eclaim,grouper_version,grouper_release', 'TRUE'),
 'drug': ('drugitems', 'icode', 'icode,name,units AS unit,unitcost::text AS unitcost,billcode,last_update', f'icode IN (SELECT icode FROM opitemrece WHERE {LINE_WHERE})'),
 'nondrug': ('nondrugitems', 'icode', 'icode,name,unit,unitcost::text AS unitcost,billcode,last_update', f'icode IN (SELECT icode FROM opitemrece WHERE {LINE_WHERE})'),
 'ward': ('ward', 'ward', 'ward,name', 'TRUE'),
 'department': ('kskdepartment', 'depcode', 'depcode,department', 'TRUE'),
 'dchtype': ('dchtype', 'dchtype', 'dchtype,name,nhso_dchtype', 'TRUE'),
 'dchstts': ('dchstts', 'dchstts', 'dchstts,name,nhso_dchstts', 'TRUE'),
}

REGISTRY = {'database': {'sql': 'SELECT version() AS version', 'params': {}}}
for name, (table, pk, fields, where) in DATASETS.items():
    ordered_key=f'{pk}::text COLLATE "C"'
    REGISTRY[name] = {'sql': f"SELECT {pk}::text AS source_key,{fields} FROM {table} WHERE ({where}) AND (:cursor='' OR {ordered_key} > :cursor) ORDER BY {ordered_key} LIMIT :limit", 'params': PAGE_PARAMS if ':start' in where or ':end' in where else {'cursor': 'string', 'limit': 'integer'}}
    business = 'hn' if name == 'patient' else 'vn' if name == 'op' else pk
    REGISTRY[name + '_profile'] = {'sql': f"SELECT count(*)::text AS rows,count(DISTINCT {pk})::text AS distinct_source_keys,count(*) FILTER(WHERE {pk} IS NULL)::text AS null_source_keys,count(DISTINCT {business})::text AS distinct_business_keys,count(*) FILTER(WHERE {business} IS NULL OR {business}::text='')::text AS missing_business_keys FROM {table} WHERE ({where})", 'params': DATE_PARAMS if ':start' in where or ':end' in where else {}}
REGISTRY['patient_registry'] = {'sql': "SELECT count(*)::text AS registry_rows,count(DISTINCT NULLIF(hn,''))::text AS registry_hn,count(*) FILTER(WHERE hn IS NULL OR hn='')::text AS missing_hn FROM patient", 'params': {}}

CORE_DATASETS = ('ip', 'op')
QUERY_FINGERPRINT=hashlib.sha256(json.dumps(REGISTRY,sort_keys=True,separators=(',',':')).encode()).hexdigest()
