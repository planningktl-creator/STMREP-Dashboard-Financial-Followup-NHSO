-- All functions use caller privileges, and one HTTP call is one transaction.
ALTER TABLE eclaim.rep_claims ADD COLUMN IF NOT EXISTS deduction_amount numeric;
ALTER TABLE eclaim.rep_claims ADD COLUMN IF NOT EXISTS net_amount numeric;
ALTER TABLE eclaim.rep_claims ADD COLUMN IF NOT EXISTS record_role text DEFAULT 'reported';
ALTER TABLE eclaim.stm_claims ADD COLUMN IF NOT EXISTS deduction_amount numeric;
ALTER TABLE eclaim.stm_claims ADD COLUMN IF NOT EXISTS net_amount numeric;
ALTER TABLE reporting.monthly_totals ADD COLUMN IF NOT EXISTS nhso_expected_amount numeric NOT NULL DEFAULT 0;
ALTER TABLE reporting.monthly_totals ADD COLUMN IF NOT EXISTS missing_amount_count bigint NOT NULL DEFAULT 0;
CREATE OR REPLACE FUNCTION ingest.complete_document(p_id bigint) RETURNS void
LANGUAGE plpgsql SECURITY INVOKER AS $fn$
DECLARE d ingest.documents; k text; expected bigint; actual bigint; newest timestamptz; tied integer;
BEGIN
 SELECT * INTO d FROM ingest.documents WHERE id=p_id FOR UPDATE;
 IF d.status='blocked' THEN RETURN; END IF;
 IF EXISTS(SELECT 1 FROM ingest.issues WHERE document_id=p_id AND severity='error' AND code<>'REVISION_TIMESTAMP_TIE') THEN
  UPDATE ingest.documents SET status='blocked',is_current=false WHERE id=p_id; RETURN;
 END IF;
 FOR k,expected IN SELECT key,value::text::bigint FROM jsonb_each(d.expected_counts) LOOP
  IF k NOT IN ('rep_claims','stm_claims','rep_drug_items','rep_instrument_items','rep_denial_items',
               'rep_zero_pay_items','rep_summaries','stm_rep_summaries','stm_period_summaries','unmapped_rows') THEN
   RAISE EXCEPTION 'Unknown record kind';
  END IF;
  EXECUTE format('SELECT count(*) FROM %I.%I WHERE document_id=$1',CASE WHEN k='unmapped_rows' THEN 'ingest' ELSE 'eclaim' END,k) INTO actual USING p_id;
  IF actual<>expected THEN RAISE EXCEPTION 'Document row count mismatch for %: expected %, got %',k,expected,actual; END IF;
 END LOOP;
 -- Resolve each child only against the same document and parent sequence.
 FOR k IN SELECT unnest(ARRAY['rep_drug_items','rep_instrument_items','rep_denial_items','rep_zero_pay_items']) LOOP
  EXECUTE format($sql$
   UPDATE eclaim.%I i SET rep_claim_id=p.parent_id,claim_id=p.claim_id,tran_id=coalesce(i.tran_id,p.tran_id)
   FROM (SELECT x.id AS item_id,min(r.id) AS parent_id,min(r.claim_id) AS claim_id,min(r.tran_id) AS tran_id
         FROM eclaim.%I x JOIN eclaim.rep_claims r ON r.document_id=x.document_id
          AND ((x.tran_id IS NOT NULL AND r.tran_id=x.tran_id)
            OR (x.tran_id IS NULL AND r.source_seq=x.parent_seq AND coalesce(r.record_role,'reported')='reported'))
          AND (x.hn IS NULL OR r.hn IS NULL OR x.hn=r.hn)
          AND (x.an IS NULL OR r.an IS NULL OR x.an=r.an)
          AND (x.pid IS NULL OR r.pid IS NULL OR x.pid=r.pid)
         WHERE x.document_id=$1
         GROUP BY x.id HAVING count(*)=1) p
   WHERE i.id=p.item_id
  $sql$,k,k) USING p_id;
  EXECUTE format($sql$
   INSERT INTO ingest.issues(document_id,sheet_index,source_row,severity,code,detail)
   SELECT i.document_id,s.sheet_index,i.source_row,'warning','ITEM_PARENT_UNRESOLVED',jsonb_build_object('kind',%L)
   FROM eclaim.%I i JOIN ingest.sheets s ON s.id=i.sheet_id
   WHERE i.document_id=$1 AND i.rep_claim_id IS NULL
     AND NOT EXISTS(SELECT 1 FROM ingest.issues x WHERE x.document_id=i.document_id AND x.sheet_index=s.sheet_index AND x.source_row=i.source_row AND x.code='ITEM_PARENT_UNRESOLVED')
  $sql$,k,k) USING p_id;
 END LOOP;
 -- Revisions invalidate reconciliation and aggregates of the previous version too.
 INSERT INTO reporting.dirty_claims(claim_id)
 SELECT claim_id FROM eclaim.rep_claims r JOIN ingest.documents x ON x.id=r.document_id WHERE x.logical_key=d.logical_key AND claim_id IS NOT NULL
 UNION SELECT claim_id FROM eclaim.stm_claims r JOIN ingest.documents x ON x.id=r.document_id WHERE x.logical_key=d.logical_key AND claim_id IS NOT NULL ORDER BY 1 ON CONFLICT DO NOTHING;
 INSERT INTO reporting.dirty_months(basis,month)
 SELECT 'service',date_trunc('month',r.service_date)::date FROM eclaim.rep_claims r JOIN ingest.documents x ON x.id=r.document_id WHERE x.logical_key=d.logical_key AND r.service_date IS NOT NULL
 UNION SELECT 'service',date_trunc('month',r.service_date)::date FROM eclaim.rep_claims r WHERE r.service_date IS NOT NULL AND r.claim_id IN
  (SELECT c.claim_id FROM eclaim.rep_claims c WHERE c.document_id=p_id)
 UNION SELECT 'service',date_trunc('month',r.service_date)::date FROM eclaim.stm_claims r JOIN ingest.documents x ON x.id=r.document_id WHERE x.logical_key=d.logical_key AND r.service_date IS NOT NULL
 UNION SELECT 'statement',x.statement_month FROM ingest.documents x WHERE x.logical_key=d.logical_key AND x.statement_month IS NOT NULL ON CONFLICT DO NOTHING;
 UPDATE ingest.documents SET status='ready',completed_at=coalesce(completed_at,now()) WHERE id=p_id;
 PERFORM pg_advisory_xact_lock(hashtextextended(d.logical_key,0));
 SELECT max(reported_at) INTO newest FROM ingest.documents WHERE logical_key=d.logical_key AND status IN ('ready','ambiguous');
 SELECT count(*) INTO tied FROM ingest.documents WHERE logical_key=d.logical_key AND status IN ('ready','ambiguous') AND reported_at IS NOT DISTINCT FROM newest;
 UPDATE ingest.documents SET is_current=false WHERE logical_key=d.logical_key AND is_current;
 IF tied>1 THEN
  UPDATE ingest.documents SET status='ambiguous' WHERE logical_key=d.logical_key AND reported_at IS NOT DISTINCT FROM newest;
  INSERT INTO ingest.issues(document_id,severity,code) SELECT p_id,'error','REVISION_TIMESTAMP_TIE'
   WHERE NOT EXISTS(SELECT 1 FROM ingest.issues WHERE document_id=p_id AND code='REVISION_TIMESTAMP_TIE');
 ELSE
  UPDATE ingest.documents SET is_current=true WHERE logical_key=d.logical_key AND status='ready' AND reported_at IS NOT DISTINCT FROM newest;
 END IF;
END $fn$;

CREATE OR REPLACE FUNCTION ingest.apply_batch(p_batch_id uuid,p_payload jsonb) RETURNS jsonb
LANGUAGE plpgsql SECURITY INVOKER AS $fn$
DECLARE old ingest.batches; ph text:=encode(sha256(convert_to(p_payload::text,'UTF8')),'hex'); x jsonb; g jsonb; d ingest.documents;
 sid bigint; k text; ns text; values_json jsonb; cols text; inserted bigint:=0; n bigint;
 result jsonb; rid uuid:=(p_payload->>'run_id')::uuid; completed text; fid bigint; new_document_id bigint;
BEGIN
 IF coalesce((SELECT sum(jsonb_array_length(entry.value->'rows')) FROM jsonb_array_elements(coalesce(p_payload->'groups','[]')) AS entry(value)),0)>500 THEN
  RAISE EXCEPTION 'Batch exceeds 500 source records';
 END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended(p_batch_id::text,0));
 SELECT * INTO old FROM ingest.batches WHERE id=p_batch_id;
 IF FOUND THEN
  IF old.payload_hash<>ph THEN RAISE EXCEPTION 'Batch ID reused with different payload'; END IF;
  RETURN old.result || jsonb_build_object('replayed',true,'original_inserted',old.records,'inserted',0);
 END IF;
 INSERT INTO ingest.runs(id) VALUES(rid) ON CONFLICT DO NOTHING;
 FOR x IN SELECT * FROM jsonb_array_elements(coalesce(p_payload->'documents','[]')) LOOP
  INSERT INTO ingest.documents(fingerprint,logical_key,document_ref,source,hcode,payer_family,patient_type,reported_at,statement_month,expected_counts,source_counts,source_sums)
  VALUES(x->>'key',x->>'logical_key',x->>'document_ref',x->>'source',x->>'hcode',x->>'payer_family',x->>'patient_type',
         (x->>'reported_at')::timestamptz,(x->>'statement_month')::date,x->'expected_counts',coalesce(x->'source_counts','{}'),coalesce(x->'source_sums','{}'))
  ON CONFLICT(fingerprint) DO UPDATE SET reported_at=greatest(ingest.documents.reported_at,excluded.reported_at);
 END LOOP;
 FOR x IN SELECT * FROM jsonb_array_elements(coalesce(p_payload->'files','[]')) LOOP
  SELECT id INTO new_document_id FROM ingest.documents WHERE fingerprint=x->>'document_key';
  IF new_document_id IS NULL THEN RAISE EXCEPTION 'Missing file document'; END IF;
  INSERT INTO ingest.files(sha256,source_path,filename,byte_size,archive_path,document_id,reported_at,metadata)
  SELECT x->>'sha256',x->>'source_path',x->>'filename',(x->>'byte_size')::bigint,x->>'archive_path',id,(x->>'reported_at')::timestamptz,coalesce(x->'metadata','{}')
  FROM ingest.documents WHERE fingerprint=x->>'document_key'
  ON CONFLICT(sha256,source_path) DO UPDATE SET archive_path=excluded.archive_path,
   document_id=CASE WHEN (SELECT ds.status FROM ingest.documents ds WHERE ds.id=ingest.files.document_id)='blocked'
                    THEN excluded.document_id ELSE ingest.files.document_id END
  RETURNING id INTO fid;
  INSERT INTO ingest.file_document_links(file_id,document_id) VALUES(fid,new_document_id) ON CONFLICT DO NOTHING;
 END LOOP;
 FOR x IN SELECT * FROM jsonb_array_elements(coalesce(p_payload->'sheets','[]')) LOOP
  INSERT INTO ingest.layouts(fingerprint,definition) VALUES(x->>'layout_id',x->'layout') ON CONFLICT DO NOTHING;
  INSERT INTO ingest.sheets(document_id,sheet_index,name,kind,layout_id,physical_rows,data_rows,metadata)
  SELECT id,(x->>'sheet_index')::integer,x->>'name',x->>'kind',x->>'layout_id',(x->>'physical_rows')::bigint,(x->>'data_rows')::bigint,coalesce(x->'metadata','[]')
  FROM ingest.documents WHERE fingerprint=x->>'document_key' ON CONFLICT(document_id,sheet_index) DO NOTHING;
 END LOOP;
 FOR x IN SELECT * FROM jsonb_array_elements(coalesce(p_payload->'issues','[]')) LOOP
  INSERT INTO ingest.issues(document_id,sheet_index,source_row,severity,code,detail)
  SELECT id,(x->>'sheet_index')::integer,(x->>'source_row')::bigint,x->>'severity',x->>'code',coalesce(x->'detail','{}')
  FROM ingest.documents WHERE fingerprint=x->>'document_key' ON CONFLICT DO NOTHING;
 END LOOP;
 FOR g IN SELECT * FROM jsonb_array_elements(coalesce(p_payload->'groups','[]')) LOOP
  k:=g->>'kind'; ns:=CASE WHEN k='unmapped_rows' THEN 'ingest' ELSE 'eclaim' END;
  IF k NOT IN ('rep_claims','stm_claims','rep_drug_items','rep_instrument_items','rep_denial_items','rep_zero_pay_items',
               'rep_summaries','stm_rep_summaries','stm_period_summaries','unmapped_rows') THEN RAISE EXCEPTION 'Unknown kind'; END IF;
  SELECT * INTO d FROM ingest.documents WHERE fingerprint=g->>'document_key';
  IF d.id IS NULL THEN RAISE EXCEPTION 'Missing document'; END IF;
  IF d.status IN ('ready','ambiguous') THEN CONTINUE; END IF;
  SELECT id INTO sid FROM ingest.sheets WHERE document_id=d.id AND sheet_index=(g->>'sheet_index')::integer;
  IF sid IS NULL THEN RAISE EXCEPTION 'Missing sheet'; END IF;
  IF EXISTS(SELECT 1 FROM jsonb_array_elements_text(g->'columns') c WHERE c IN ('id','claim_id','rep_claim_id','document_id','sheet_id')) THEN RAISE EXCEPTION 'Reserved column'; END IF;
  SELECT jsonb_agg(r.obj || jsonb_build_object('document_id',d.id,'sheet_id',sid)) INTO values_json
  FROM (SELECT (SELECT jsonb_object_agg(c.value,v.value->(c.ordinality::integer-1)) FROM jsonb_array_elements_text(g->'columns') WITH ORDINALITY c) obj
        FROM jsonb_array_elements(g->'rows') v) r;
  IF values_json IS NULL THEN CONTINUE; END IF;
  IF k IN ('rep_claims','stm_claims') THEN
   INSERT INTO eclaim.claims(hcode,payer_family,patient_type,tran_id,hn,an,pid)
   SELECT DISTINCT ON(j->>'hcode',j->>'payer_family',j->>'patient_type',j->>'tran_id')
    j->>'hcode',j->>'payer_family',j->>'patient_type',j->>'tran_id',j->>'hn',j->>'an',j->>'pid'
   FROM jsonb_array_elements(values_json) j WHERE nullif(j->>'tran_id','') IS NOT NULL
   ORDER BY j->>'hcode',j->>'payer_family',j->>'patient_type',j->>'tran_id',(j->>'source_row')::bigint ON CONFLICT DO NOTHING;
   INSERT INTO ingest.issues(document_id,sheet_index,source_row,severity,code)
   SELECT d.id,(g->>'sheet_index')::integer,(j->>'source_row')::bigint,'error','CLAIM_IDENTITY_CONFLICT'
   FROM jsonb_array_elements(values_json) j JOIN eclaim.claims c ON c.hcode=j->>'hcode' AND c.payer_family=j->>'payer_family' AND c.patient_type=j->>'patient_type' AND c.tran_id=j->>'tran_id'
   WHERE (c.hn IS NOT NULL AND j->>'hn' IS NOT NULL AND c.hn<>j->>'hn')
      OR (c.an IS NOT NULL AND j->>'an' IS NOT NULL AND c.an<>j->>'an')
      OR (c.pid IS NOT NULL AND j->>'pid' IS NOT NULL AND c.pid<>j->>'pid') ON CONFLICT DO NOTHING;
  END IF;
  SELECT string_agg(format('%I',a.attname),',' ORDER BY a.attnum) INTO cols
  FROM pg_attribute a WHERE a.attrelid=format('%I.%I',ns,k)::regclass AND a.attnum>0 AND NOT a.attisdropped
   AND a.attname NOT IN ('id','claim_id','rep_claim_id','fiscal_year_be');
  IF k IN ('rep_claims','stm_claims','rep_drug_items','rep_instrument_items','rep_denial_items','rep_zero_pay_items') THEN
   SELECT jsonb_agg(j || jsonb_build_object('claim_id',c.id)) INTO values_json FROM jsonb_array_elements(values_json) j
   LEFT JOIN eclaim.claims c ON c.hcode=j->>'hcode' AND c.payer_family=j->>'payer_family' AND c.patient_type=j->>'patient_type' AND c.tran_id=j->>'tran_id'
    AND (c.hn IS NULL OR j->>'hn' IS NULL OR c.hn=j->>'hn') AND (c.an IS NULL OR j->>'an' IS NULL OR c.an=j->>'an') AND (c.pid IS NULL OR j->>'pid' IS NULL OR c.pid=j->>'pid');
   cols:=cols||',claim_id';
  END IF;
  EXECUTE format('INSERT INTO %I.%I(%s) SELECT %s FROM jsonb_populate_recordset(NULL::%I.%I,$1) ON CONFLICT(sheet_id,source_row) DO NOTHING',ns,k,cols,cols,ns,k) USING values_json;
  GET DIAGNOSTICS n=ROW_COUNT; inserted:=inserted+n;
 END LOOP;
 FOR completed IN SELECT jsonb_array_elements_text(coalesce(p_payload->'complete','[]')) LOOP
  SELECT id INTO sid FROM ingest.documents WHERE fingerprint=completed;
  PERFORM ingest.complete_document(sid);
 END LOOP;
 result:=jsonb_build_object('inserted',inserted,'replayed',false,'completed',coalesce(p_payload->'complete','[]'),
  'document_statuses',coalesce((SELECT jsonb_object_agg(fingerprint,status) FROM ingest.documents
   WHERE fingerprint IN(SELECT jsonb_array_elements_text(coalesce(p_payload->'complete','[]')))),'{}'::jsonb));
 INSERT INTO ingest.batches(id,run_id,payload_hash,records,result) VALUES(p_batch_id,rid,ph,inserted,result);
 RETURN result;
END $fn$;

DROP VIEW IF EXISTS reporting.rep_reconciliation;
DROP VIEW IF EXISTS reporting.rep_latest;
DROP VIEW IF EXISTS reporting.rep_current;
DROP VIEW IF EXISTS reporting.stm_current;
CREATE OR REPLACE VIEW reporting.rep_current AS
SELECT r.* FROM eclaim.rep_claims r JOIN ingest.documents d ON d.id=r.document_id WHERE d.status='ready' AND d.is_current AND coalesce(r.record_role,'reported')='reported';
CREATE OR REPLACE VIEW reporting.stm_current AS
SELECT s.*,d.statement_month FROM eclaim.stm_claims s JOIN ingest.documents d ON d.id=s.document_id WHERE d.status='ready' AND d.is_current;

-- Service-month KPIs count one latest REP snapshot per clinical claim.
-- Round-specific reconciliation continues to use all current report documents.
CREATE OR REPLACE VIEW reporting.rep_latest AS
WITH ranked AS (
 SELECT r.id,r.claim_id,dense_rank() OVER(PARTITION BY r.claim_id ORDER BY d.reported_at DESC NULLS LAST) AS rank
 FROM reporting.rep_current r JOIN ingest.documents d ON d.id=r.document_id WHERE r.claim_id IS NOT NULL
), unique_latest AS (SELECT min(id) id FROM ranked WHERE rank=1 GROUP BY claim_id HAVING count(*)=1)
SELECT r.* FROM reporting.rep_current r JOIN unique_latest u ON u.id=r.id;

CREATE OR REPLACE VIEW reporting.rep_reconciliation AS
WITH paid AS (
 SELECT m.rep_claim_id,count(*) AS stm_count,sum(s.net_amount) AS statement_amount,count(*) FILTER(WHERE s.net_amount IS NULL) AS missing_amounts
 FROM reporting.reconciliation_matches m JOIN reporting.stm_current s ON s.id=m.stm_claim_id
 WHERE m.status='MATCHED' GROUP BY m.rep_claim_id
)
SELECT r.*,coalesce(p.stm_count,0) AS stm_count,coalesce(p.statement_amount,0) AS statement_amount,
 CASE WHEN coalesce(p.missing_amounts,0)=0 THEN r.nhso_amount-coalesce(p.statement_amount,0) END AS difference,
 CASE WHEN r.payer_family NOT IN ('UCS','STP') THEN 'NOT_COVERED'
      WHEN EXISTS(SELECT 1 FROM reporting.reconciliation_matches m JOIN reporting.stm_current s ON s.id=m.stm_claim_id
                  WHERE m.status='AMBIGUOUS' AND s.claim_id=r.claim_id AND s.rep_no=r.rep_no) THEN 'REVIEW_REQUIRED'
      WHEN r.error_code IS NOT NULL AND r.error_code<>'0' THEN CASE WHEN coalesce(p.stm_count,0)>0 THEN 'REVIEW_REQUIRED' ELSE 'REP_REJECTED' END
      WHEN r.nhso_amount IS NULL THEN 'UNKNOWN_EXPECTED'
      WHEN coalesce(p.missing_amounts,0)>0 THEN 'UNKNOWN_STATEMENT'
      WHEN coalesce(p.stm_count,0)=0 THEN 'MISSING_STM'
      WHEN coalesce(p.statement_amount,0)<=0 THEN 'ZERO_OR_REVERSAL'
      WHEN abs(r.nhso_amount-p.statement_amount)<=0.01 THEN 'MATCHED_FULL'
      WHEN p.statement_amount>r.nhso_amount THEN 'OVER_EXPECTED'
      ELSE 'MATCHED_PARTIAL' END AS reconciliation_status
FROM reporting.rep_current r LEFT JOIN paid p ON p.rep_claim_id=r.id;

DROP FUNCTION IF EXISTS reporting.refresh_claims(integer);
CREATE OR REPLACE FUNCTION reporting.refresh_claims(p_limit integer DEFAULT 2000,p_claim_ids bigint[] DEFAULT NULL) RETURNS integer
LANGUAGE plpgsql AS $fn$
DECLARE keys bigint[]; n integer;
BEGIN
 SELECT array_agg(claim_id) INTO keys FROM (SELECT claim_id FROM reporting.dirty_claims WHERE p_claim_ids IS NULL OR claim_id=ANY(p_claim_ids) ORDER BY claim_id LIMIT p_limit FOR UPDATE SKIP LOCKED) q;
 IF keys IS NULL THEN RETURN 0; END IF;
 DELETE FROM reporting.reconciliation_matches m USING eclaim.stm_claims s WHERE m.stm_claim_id=s.id AND s.claim_id=ANY(keys);
 INSERT INTO reporting.reconciliation_matches(stm_claim_id,rep_claim_id,status,candidate_count)
 SELECT s.id,CASE WHEN count(r.id)=1 THEN min(r.id) END,
        CASE WHEN count(r.id)=1 THEN 'MATCHED' WHEN count(r.id)=0 THEN 'MISSING_REP' ELSE 'AMBIGUOUS' END,count(r.id)
 FROM reporting.stm_current s LEFT JOIN reporting.rep_current r ON r.claim_id=s.claim_id AND r.rep_no=s.rep_no
 WHERE s.claim_id=ANY(keys) GROUP BY s.id;
 DELETE FROM reporting.dirty_claims WHERE claim_id=ANY(keys);
 n:=array_length(keys,1); RETURN n;
END $fn$;

CREATE OR REPLACE FUNCTION reporting.refresh_month(p_basis text,p_month date) RETURNS void
LANGUAGE plpgsql AS $fn$
BEGIN
 IF p_basis NOT IN ('service','statement') THEN RAISE EXCEPTION 'Invalid reporting basis'; END IF;
 INSERT INTO reporting.dirty_months(basis,month) VALUES(p_basis,p_month) ON CONFLICT DO NOTHING;
 PERFORM 1 FROM reporting.dirty_months WHERE basis=p_basis AND month=p_month FOR UPDATE;
 DELETE FROM reporting.monthly_totals WHERE basis=p_basis AND month=p_month;
 INSERT INTO reporting.monthly_totals(basis,month,hcode,payer_family,patient_type,category,fiscal_year_be,rep_count,stm_count,billed_amount,expected_amount,statement_amount,nhso_expected_amount,missing_amount_count)
 SELECT p_basis,p_month,hcode,payer_family,patient_type,category,extract(year FROM p_month)::integer+CASE WHEN extract(month FROM p_month)>=10 THEN 1 ELSE 0 END+543,
 sum(rep_count),sum(stm_count),sum(billed),sum(expected),sum(paid),sum(nhso_expected),sum(missing_amounts)
 FROM (
  SELECT hcode,payer_family,patient_type,category,count(*) rep_count,0::bigint stm_count,
   coalesce(sum(billed_amount),0) billed,coalesce(sum(expected_amount) FILTER(WHERE error_code IS NULL OR error_code='0'),0) expected,0::numeric paid,
   coalesce(sum(nhso_amount) FILTER(WHERE error_code IS NULL OR error_code='0'),0) nhso_expected,count(*) FILTER(WHERE billed_amount IS NULL OR expected_amount IS NULL) missing_amounts
  FROM reporting.rep_latest WHERE p_basis='service' AND service_date>=p_month AND service_date<(p_month+interval '1 month') GROUP BY 1,2,3,4
  UNION ALL
  SELECT hcode,payer_family,patient_type,category,0,count(*),0,0,coalesce(sum(net_amount),0),0,count(*) FILTER(WHERE net_amount IS NULL)
  FROM reporting.stm_current WHERE (p_basis='service' AND service_date>=p_month AND service_date<(p_month+interval '1 month'))
    OR (p_basis='statement' AND statement_month=p_month) GROUP BY 1,2,3,4
 ) q GROUP BY 1,2,3,4,5,6,7;
 DELETE FROM reporting.dirty_months WHERE basis=p_basis AND month=p_month;
END $fn$;

INSERT INTO ingest.schema_versions(version) VALUES('1.0.0') ON CONFLICT DO NOTHING;
