CREATE OR REPLACE FUNCTION his.rebuild_links(p_snapshot uuid) RETURNS bigint LANGUAGE plpgsql AS $fn$
DECLARE n bigint;
BEGIN
 DELETE FROM followup.claim_links WHERE snapshot_id=p_snapshot;
 INSERT INTO followup.claim_links(snapshot_id,case_id,claim_id,status,method,evidence)
 WITH candidates AS (
  SELECT DISTINCT c.id AS case_id,q.id AS claim_id,
   CASE WHEN c.care_type='IP' THEN 'HCODE_AN_PATIENT' ELSE 'HIS_VN_TRAN_BRIDGE' END AS method,
   (c.identity_status='unique' AND ((c.hn IS NOT NULL AND q.hn=c.hn) OR (c.cid IS NOT NULL AND q.pid=c.cid))
     AND NOT(c.hn IS NOT NULL AND q.hn IS NOT NULL AND c.hn<>q.hn)
     AND NOT(c.cid IS NOT NULL AND q.pid IS NOT NULL AND c.cid<>q.pid)) AS identity_ok
  FROM his.cases c JOIN eclaim.claims q ON q.hcode=c.hcode AND q.patient_type=c.care_type
   AND ((c.care_type='IP' AND q.an=c.an)
     OR (c.care_type='OP' AND EXISTS(
      SELECT 1 FROM his.records b WHERE b.snapshot_id=p_snapshot AND b.dataset='rep_bridge'
       AND b.payload->>'vn'=c.vn AND b.payload->>'rep_eclaim_detail_tran_id'=q.tran_id
       AND (NULLIF(b.payload->>'hcode','') IS NULL OR b.payload->>'hcode'=c.hcode)
       AND NOT(NULLIF(b.payload->>'hn','') IS NOT NULL AND b.payload->>'hn'<>c.hn)
       AND NOT(NULLIF(b.payload->>'pid','') IS NOT NULL AND c.cid IS NOT NULL AND b.payload->>'pid'<>c.cid)
     )))
  WHERE c.snapshot_id=p_snapshot
 ), checked AS (SELECT *,count(*) OVER(PARTITION BY claim_id) AS alternatives FROM candidates)
 SELECT p_snapshot,case_id,claim_id,CASE WHEN alternatives=1 AND identity_ok THEN 'linked' ELSE 'review' END,
 method,jsonb_build_object('candidate_count',alternatives,'patient_consistent',identity_ok,'payer_verification','observed_claim_scope') FROM checked;
 GET DIAGNOSTICS n=ROW_COUNT;
 RETURN n;
END $fn$;

CREATE OR REPLACE FUNCTION his.finalize_snapshot(p_snapshot uuid) RETURNS jsonb LANGUAGE plpgsql AS $fn$
DECLARE snap his.snapshots%ROWTYPE; n bigint; line_n bigint;
BEGIN
 SELECT * INTO snap FROM his.snapshots WHERE id=p_snapshot FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'SNAPSHOT_NOT_FOUND'; END IF;
 IF snap.status IN ('ready','partial') THEN RETURN jsonb_build_object('replayed',true); END IF;
 IF snap.status NOT IN ('building','waiting_session') THEN RAISE EXCEPTION 'SNAPSHOT_NOT_BUILDING'; END IF;
 INSERT INTO his.issues(snapshot_id,dataset,source_key,code,severity,detail)
 SELECT p_snapshot,dataset,source_key,'SOURCE_VALUE_INVALID','warning',jsonb_build_object('fields',payload->'_issues')
 FROM his.records WHERE snapshot_id=p_snapshot AND payload ? '_issues';
 INSERT INTO his.issues(snapshot_id,dataset,source_key,code,severity,detail)
 SELECT p_snapshot,dataset,coalesce(NULLIF(payload->>CASE WHEN dataset='ip' THEN 'an' ELSE 'vn' END,''),'(missing)'),
 'ENCOUNTER_KEY_NOT_UNIQUE','error',jsonb_build_object('rows',count(*))
 FROM his.records WHERE snapshot_id=p_snapshot AND dataset IN ('ip','op')
 GROUP BY dataset,payload->>CASE WHEN dataset='ip' THEN 'an' ELSE 'vn' END
 HAVING count(*)>1 OR NULLIF(payload->>CASE WHEN dataset='ip' THEN 'an' ELSE 'vn' END,'') IS NULL;

 INSERT INTO his.cases(snapshot_id,hcode,encounter_key,care_type,source_record_id,hn,cid,vn,an,linked_an,
  name,sex,birthday,age_years,age_band,admitted_at,discharged_at,service_date,fiscal_year_be,ward,department,
  pttype,nhso_code,pdx,drg,grouper_version,rw,adjrw,los,dchtype,dchstts,
  his_summary_charge,his_summary_uc,his_summary_paid,his_summary_remain,identity_status,quality)
 WITH target AS (
  SELECT *,payload->>CASE WHEN dataset='ip' THEN 'an' ELSE 'vn' END AS business_key,
  count(*) OVER(PARTITION BY dataset,payload->>CASE WHEN dataset='ip' THEN 'an' ELSE 'vn' END) AS key_count
  FROM his.records WHERE snapshot_id=p_snapshot AND dataset IN ('ip','op')
 ), selected AS (
  SELECT r.*,CASE WHEN dataset='ip' THEN 'IP' ELSE 'OP' END AS care,
   (r.payload->>CASE WHEN dataset='ip' THEN 'dchdate' ELSE 'vstdate' END)::date AS svc,
   p.p AS patient,p.n AS patient_count,f.p AS finance,d.pdx,d.pdx_count,pt.p AS right_master,
   coalesce((r.payload->>'regdate')::date,(r.payload->>'vstdate')::date) AS entered
  FROM target r
  LEFT JOIN LATERAL (SELECT CASE WHEN count(*)=1 THEN jsonb_agg(payload)->0 ELSE NULL END AS p,count(*) AS n
   FROM his.records WHERE snapshot_id=p_snapshot AND dataset='patient' AND payload->>'hn'=r.payload->>'hn') p ON true
  LEFT JOIN LATERAL (SELECT CASE WHEN count(*)=1 THEN jsonb_agg(payload)->0 END AS p FROM his.records WHERE snapshot_id=p_snapshot
   AND dataset=CASE WHEN r.dataset='ip' THEN 'ip_finance' ELSE 'op_finance' END
   AND payload->>CASE WHEN r.dataset='ip' THEN 'an' ELSE 'vn' END=r.business_key) f ON true
  LEFT JOIN LATERAL (SELECT CASE WHEN count(*)=1 THEN min(payload->>'icd10') ELSE NULL END AS pdx,count(*) AS pdx_count
   FROM his.records WHERE snapshot_id=p_snapshot AND dataset=CASE WHEN r.dataset='ip' THEN 'ip_diag' ELSE 'op_diag' END
    AND payload->>CASE WHEN r.dataset='ip' THEN 'an' ELSE 'vn' END=r.business_key AND payload->>'diagtype'='1') d ON true
  LEFT JOIN LATERAL (SELECT CASE WHEN count(*)=1 THEN jsonb_agg(payload)->0 END AS p FROM his.records WHERE snapshot_id=p_snapshot AND dataset='pttype'
    AND payload->>'pttype'=r.payload->>'pttype') pt ON true
  WHERE key_count=1 AND NULLIF(business_key,'') IS NOT NULL
 ), aged AS (
  SELECT *,extract(year FROM age(entered,(patient->>'birthday')::date))::integer AS years FROM selected
 )
 SELECT p_snapshot,snap.hcode,care||':'||business_key,care,id,payload->>'hn',patient->>'cid',payload->>'vn',
 CASE WHEN care='IP' THEN business_key END,CASE WHEN care='OP' THEN NULLIF(payload->>'an','') END,
 NULLIF(concat_ws(' ',patient->>'pname',patient->>'fname',patient->>'lname'),''),patient->>'sex',(patient->>'birthday')::date,years,
 CASE WHEN years IS NULL THEN NULL WHEN years<5 THEN '0–4' WHEN years<15 THEN '5–14' WHEN years<45 THEN '15–44' WHEN years<65 THEN '45–64' ELSE '65+' END,
 (payload->>'_admitted_at')::timestamptz,(payload->>'_discharged_at')::timestamptz,svc,
 extract(year FROM svc)::integer+543+CASE WHEN extract(month FROM svc)>=10 THEN 1 ELSE 0 END,
 payload->>'ward',coalesce(payload->>'main_dep',payload->>'last_dep'),payload->>'pttype',right_master->>'nhso_code',pdx,
 payload->>'drg',payload->>'grouper_version',(payload->>'rw')::numeric,(payload->>'adjrw')::numeric,
 CASE WHEN care='IP' THEN svc-entered END,payload->>'dchtype',payload->>'dchstts',
 (finance->>'income')::numeric,(finance->>'uc_money')::numeric,(finance->>'paid_money')::numeric,(finance->>'remain_money')::numeric,
 CASE WHEN patient_count=1 AND NULLIF(payload->>'hn','') IS NOT NULL THEN 'unique' WHEN patient_count>1 THEN 'duplicate_hn' ELSE 'unverified' END,
 jsonb_build_object('pdx_count',pdx_count,'patient_rows',patient_count,'negative_los',svc<entered,'linked_admission',NULLIF(payload->>'an',''))
 FROM aged;
 GET DIAGNOSTICS n=ROW_COUNT;

 INSERT INTO his.case_lines(snapshot_id,source_record_id,case_id,icode,billcode,item_name,unit,quantity,unit_price,
  charge_amount,raw_cost,observed_item_cost,estimated_item_cost,estimate_as_of,service_date,department,cost_method)
 SELECT p_snapshot,r.id,c.id,r.payload->>'icode',m.p->>'billcode',m.p->>'name',m.p->>'unit',
  (r.payload->>'qty')::numeric,(r.payload->>'unitprice')::numeric,(r.payload->>'sum_price')::numeric,(r.payload->>'cost')::numeric,
  CASE WHEN snap.cost_review IS NOT NULL AND snap.cost_review<>'' AND snap.cost_semantics='line' THEN (r.payload->>'cost')::numeric
       WHEN snap.cost_review IS NOT NULL AND snap.cost_review<>'' AND snap.cost_semantics='unit' THEN (r.payload->>'cost')::numeric*(r.payload->>'qty')::numeric END,
  (m.p->>'unitcost')::numeric*(r.payload->>'qty')::numeric,snap.created_at,(r.payload->>'vstdate')::date,r.payload->>'dep_code',snap.cost_semantics
 FROM his.records r
 LEFT JOIN his.cases c ON c.snapshot_id=p_snapshot AND c.encounter_key=
   CASE WHEN NULLIF(r.payload->>'an','') IS NOT NULL THEN 'IP:'||(r.payload->>'an') ELSE 'OP:'||(r.payload->>'vn') END
 LEFT JOIN LATERAL (SELECT CASE WHEN count(*)=1 THEN jsonb_agg(payload)->0 END AS p FROM his.records
   WHERE snapshot_id=p_snapshot AND dataset IN ('drug','nondrug') AND payload->>'icode'=r.payload->>'icode') m ON true
 WHERE r.snapshot_id=p_snapshot AND r.dataset='lines';
 GET DIAGNOSTICS line_n=ROW_COUNT;
 INSERT INTO his.issues(snapshot_id,dataset,code,severity,detail)
 SELECT p_snapshot,'lines','UNASSIGNED_SERVICE_LINES','warning',jsonb_build_object('count',count(*))
 FROM his.case_lines WHERE snapshot_id=p_snapshot AND case_id IS NULL HAVING count(*)>0;
 PERFORM his.rebuild_links(p_snapshot);
 UPDATE his.snapshots SET status=CASE WHEN (coverage->'ip'->>'state')='complete' AND (coverage->'op'->>'state')='complete'
   AND NOT EXISTS(SELECT 1 FROM his.issues WHERE snapshot_id=p_snapshot AND severity='error') THEN 'ready' ELSE 'partial' END,
   completed_at=now() WHERE id=p_snapshot;
 RETURN jsonb_build_object('cases',n,'lines',line_n,'replayed',false);
END $fn$;
