CREATE SCHEMA IF NOT EXISTS his;
CREATE SCHEMA IF NOT EXISTS followup;
CREATE SCHEMA IF NOT EXISTS analytics;
CREATE TABLE IF NOT EXISTS followup.schema_versions(version text PRIMARY KEY,installed_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS followup.audit_events(
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,actor_ref text NOT NULL,event text NOT NULL,
 object_id text,detail jsonb NOT NULL DEFAULT '{}',created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS audit_event_time_idx ON followup.audit_events(created_at DESC);
CREATE TABLE IF NOT EXISTS followup.jobs(
 id uuid PRIMARY KEY,kind text NOT NULL CHECK(kind IN ('IMPORT','HIS_SYNC')),actor_ref text NOT NULL,
 status text NOT NULL DEFAULT 'queued',payload jsonb NOT NULL,progress jsonb NOT NULL DEFAULT '{}',
 result jsonb NOT NULL DEFAULT '{}',error_code text,owner_id uuid,lease_until timestamptz,
 pause_requested boolean NOT NULL DEFAULT false,created_at timestamptz NOT NULL DEFAULT now(),updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS jobs_queue_idx ON followup.jobs(status,created_at);
CREATE TABLE IF NOT EXISTS followup.job_files(
 id uuid PRIMARY KEY,job_id uuid NOT NULL REFERENCES followup.jobs(id),source text NOT NULL,
 filename text NOT NULL,storage_path text NOT NULL,sha256 text NOT NULL,byte_size bigint NOT NULL,
 status text NOT NULL DEFAULT 'uploaded',profile jsonb NOT NULL DEFAULT '{}',UNIQUE(job_id,filename,sha256)
);
CREATE INDEX IF NOT EXISTS job_files_job_idx ON followup.job_files(job_id);
CREATE TABLE IF NOT EXISTS his.snapshots(
 id uuid PRIMARY KEY,job_id uuid REFERENCES followup.jobs(id),hcode text NOT NULL,dstart date NOT NULL,dend date NOT NULL,
 status text NOT NULL DEFAULT 'building',coverage jsonb NOT NULL DEFAULT '{}',registry_profile jsonb NOT NULL DEFAULT '{}',
 cost_semantics text NOT NULL DEFAULT 'unverified',cost_review text,
 created_at timestamptz NOT NULL DEFAULT now(),completed_at timestamptz,CHECK(dend>=dstart)
);
CREATE INDEX IF NOT EXISTS snapshots_scope_idx ON his.snapshots(hcode,dstart,dend,completed_at DESC);
CREATE TABLE IF NOT EXISTS his.records(
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,snapshot_id uuid NOT NULL REFERENCES his.snapshots(id),
 dataset text NOT NULL,source_key text NOT NULL,payload jsonb NOT NULL,record_hash text NOT NULL,
 captured_at timestamptz NOT NULL DEFAULT now(),UNIQUE(snapshot_id,dataset,source_key)
);
CREATE INDEX IF NOT EXISTS records_an_idx ON his.records(snapshot_id,dataset,(payload->>'an'));
CREATE INDEX IF NOT EXISTS records_vn_idx ON his.records(snapshot_id,dataset,(payload->>'vn'));
CREATE INDEX IF NOT EXISTS records_hn_idx ON his.records(snapshot_id,dataset,(payload->>'hn'));
CREATE INDEX IF NOT EXISTS records_icode_idx ON his.records(snapshot_id,dataset,(payload->>'icode'));
CREATE TABLE IF NOT EXISTS his.batches(
 id uuid PRIMARY KEY,snapshot_id uuid NOT NULL REFERENCES his.snapshots(id),dataset text NOT NULL,
 payload_hash text NOT NULL,records bigint NOT NULL,committed_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS his.issues(
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,snapshot_id uuid NOT NULL REFERENCES his.snapshots(id),
 dataset text NOT NULL,source_key text,code text NOT NULL,severity text NOT NULL DEFAULT 'warning',
 detail jsonb NOT NULL DEFAULT '{}',created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS his_issues_snapshot_idx ON his.issues(snapshot_id,code);
CREATE TABLE IF NOT EXISTS his.cases(
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,snapshot_id uuid NOT NULL REFERENCES his.snapshots(id),
 hcode text NOT NULL,encounter_key text NOT NULL,care_type text NOT NULL CHECK(care_type IN ('IP','OP')),
 source_record_id bigint NOT NULL REFERENCES his.records(id),hn text,cid text,vn text,an text,linked_an text,
 name text,sex text,birthday date,age_years integer,age_band text,admitted_at timestamptz,discharged_at timestamptz,
 service_date date,fiscal_year_be integer,ward text,department text,pttype text,nhso_code text,pdx text,
 drg text,grouper_version text,rw numeric,adjrw numeric,los integer,dchtype text,dchstts text,
 his_summary_charge numeric,his_summary_uc numeric,his_summary_paid numeric,his_summary_remain numeric,
 identity_status text NOT NULL DEFAULT 'unverified',quality jsonb NOT NULL DEFAULT '{}',
 UNIQUE(snapshot_id,encounter_key)
);
CREATE INDEX IF NOT EXISTS cases_service_idx ON his.cases(snapshot_id,service_date,care_type,id);
CREATE INDEX IF NOT EXISTS cases_an_idx ON his.cases(snapshot_id,an) WHERE an IS NOT NULL;
CREATE INDEX IF NOT EXISTS cases_vn_idx ON his.cases(snapshot_id,vn) WHERE vn IS NOT NULL;
CREATE INDEX IF NOT EXISTS cases_hn_idx ON his.cases(hcode,hn);
CREATE TABLE IF NOT EXISTS his.case_lines(
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,snapshot_id uuid NOT NULL REFERENCES his.snapshots(id),
 source_record_id bigint NOT NULL REFERENCES his.records(id),case_id bigint REFERENCES his.cases(id),
 icode text,billcode text,item_name text,unit text,quantity numeric,unit_price numeric,charge_amount numeric,
 raw_cost numeric,observed_item_cost numeric,estimated_item_cost numeric,estimate_as_of timestamptz,
 service_date date,department text,cost_method text NOT NULL DEFAULT 'unverified',
 UNIQUE(snapshot_id,source_record_id)
);
CREATE INDEX IF NOT EXISTS lines_case_idx ON his.case_lines(case_id);
CREATE INDEX IF NOT EXISTS lines_snapshot_idx ON his.case_lines(snapshot_id);
CREATE TABLE IF NOT EXISTS followup.claim_links(
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,snapshot_id uuid NOT NULL REFERENCES his.snapshots(id),
 case_id bigint NOT NULL REFERENCES his.cases(id),claim_id bigint NOT NULL REFERENCES eclaim.claims(id),
 status text NOT NULL,method text NOT NULL,evidence jsonb NOT NULL DEFAULT '{}',created_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(snapshot_id,case_id,claim_id)
);
CREATE INDEX IF NOT EXISTS links_claim_idx ON followup.claim_links(claim_id,snapshot_id);
CREATE INDEX IF NOT EXISTS links_case_idx ON followup.claim_links(case_id);
CREATE TABLE IF NOT EXISTS followup.observations(
 id uuid PRIMARY KEY,hcode text NOT NULL,encounter_key text NOT NULL,claim_id bigint REFERENCES eclaim.claims(id),
 event_type text NOT NULL CHECK(event_type IN ('SUBMISSION','APPEAL_SENT','CASH_RECEIPT','DEADLINE')),
 occurred_at timestamptz NOT NULL,amount numeric,source_ref text NOT NULL,verification text NOT NULL DEFAULT 'unverified',
 actor_ref text NOT NULL,recorded_at timestamptz NOT NULL DEFAULT now(),metadata jsonb NOT NULL DEFAULT '{}',
 UNIQUE(hcode,event_type,source_ref,encounter_key)
);
CREATE INDEX IF NOT EXISTS observations_case_idx ON followup.observations(hcode,encounter_key,event_type);
CREATE TABLE IF NOT EXISTS followup.tasks(
 id uuid PRIMARY KEY,hcode text NOT NULL,encounter_key text NOT NULL,reason text NOT NULL,
 status text NOT NULL DEFAULT 'open' CHECK(status IN ('open','in_progress','waiting','resolved')),
 team text NOT NULL DEFAULT 'ทีมเรียกเก็บ',due_date date,note text NOT NULL DEFAULT '',
 actor_ref text NOT NULL,created_at timestamptz NOT NULL DEFAULT now(),updated_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(hcode,encounter_key,reason)
);
CREATE INDEX IF NOT EXISTS tasks_status_idx ON followup.tasks(hcode,status,due_date);
CREATE TABLE IF NOT EXISTS followup.appeals(
 id uuid PRIMARY KEY,hcode text NOT NULL,encounter_key text NOT NULL,claim_id bigint REFERENCES eclaim.claims(id),
 reason text NOT NULL,status text NOT NULL DEFAULT 'review',baseline_amount numeric,baseline_rows jsonb NOT NULL DEFAULT '[]',
 opened_at timestamptz NOT NULL DEFAULT now(),sent_at timestamptz,outcome text,incremental_amount numeric,
 result_rows jsonb NOT NULL DEFAULT '[]',effect_type text,source_ref text,actor_ref text NOT NULL,updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS appeals_case_idx ON followup.appeals(hcode,encounter_key);
CREATE TABLE IF NOT EXISTS followup.rule_packs(
 id uuid PRIMARY KEY,name text NOT NULL,version text NOT NULL,care_type text NOT NULL,payer_code text NOT NULL,
 effective_from date NOT NULL,effective_to date NOT NULL,verification text NOT NULL DEFAULT 'review',
 authority_url text NOT NULL,authority_clause text,review_reference text,definition jsonb NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(),UNIQUE(name,version),CHECK(effective_to>=effective_from)
);
CREATE TABLE IF NOT EXISTS followup.instrument_catalog(
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,icode text NOT NULL,billcode text,item_name text,
 category text,legacy_rate numeric,source_ref text NOT NULL,source_year integer,verification text NOT NULL DEFAULT 'observed_only',
 UNIQUE(icode,source_ref)
);

CREATE OR REPLACE FUNCTION his.apply_batch(p_id uuid,p_snapshot uuid,p_dataset text,p_rows jsonb) RETURNS jsonb
LANGUAGE plpgsql AS $fn$
DECLARE existing his.batches%ROWTYPE; item jsonb; n bigint:=0; ph text; old_hash text;
BEGIN
 IF jsonb_typeof(p_rows)<>'array' OR jsonb_array_length(p_rows)>500 THEN RAISE EXCEPTION 'HIS_BATCH_LIMIT'; END IF;
 IF p_dataset NOT IN ('patient','person','ip','op','ip_diag','op_diag','ip_procedure','op_procedure','lines','ip_finance','op_finance','rights','drg','rep_bridge','submission_op','submission_nhso','fdh','pttype','drug','nondrug','ward','department','dchtype','dchstts') THEN RAISE EXCEPTION 'HIS_DATASET_INVALID'; END IF;
 ph:=encode(sha256(convert_to(p_rows::text,'UTF8')),'hex');
 PERFORM pg_advisory_xact_lock(hashtextextended(p_id::text,0));
 SELECT * INTO existing FROM his.batches WHERE id=p_id;
 IF FOUND THEN
  IF existing.payload_hash<>ph OR existing.snapshot_id<>p_snapshot OR existing.dataset<>p_dataset THEN RAISE EXCEPTION 'HIS_BATCH_COLLISION'; END IF;
  RETURN jsonb_build_object('replayed',true,'inserted',0,'records',existing.records);
 END IF;
 PERFORM 1 FROM his.snapshots WHERE id=p_snapshot AND status IN ('building','waiting_session') FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'SNAPSHOT_IMMUTABLE'; END IF;
 FOR item IN SELECT value FROM jsonb_array_elements(p_rows) LOOP
  IF coalesce(item->>'source_key','')='' OR jsonb_typeof(item->'payload')<>'object' THEN RAISE EXCEPTION 'HIS_RECORD_INVALID'; END IF;
  old_hash:=NULL;
  SELECT record_hash INTO old_hash FROM his.records WHERE snapshot_id=p_snapshot AND dataset=p_dataset AND source_key=item->>'source_key';
  IF old_hash IS NOT NULL AND old_hash<>item->>'record_hash' THEN RAISE EXCEPTION 'SOURCE_CHANGED_DURING_SNAPSHOT'; END IF;
  INSERT INTO his.records(snapshot_id,dataset,source_key,payload,record_hash)
   VALUES(p_snapshot,p_dataset,item->>'source_key',item->'payload',item->>'record_hash') ON CONFLICT DO NOTHING;
  IF FOUND THEN n:=n+1; END IF;
 END LOOP;
 INSERT INTO his.batches(id,snapshot_id,dataset,payload_hash,records) VALUES(p_id,p_snapshot,p_dataset,ph,jsonb_array_length(p_rows));
 RETURN jsonb_build_object('replayed',false,'inserted',n,'records',jsonb_array_length(p_rows));
END $fn$;

CREATE OR REPLACE VIEW analytics.rep_claim_observations AS
SELECT c.id AS claim_id,c.hcode,c.payer_family,c.patient_type,c.tran_id,c.hn,c.an,c.pid,
 r.id AS rep_row_id,r.rep_no,r.service_date,r.category,r.record_role,r.error_code,r.billed_amount,
 r.expected_amount,r.nhso_amount,
 EXISTS(SELECT 1 FROM reporting.rep_current hist WHERE hist.claim_id=c.id) AS rep_observed,
 (r.id IS NOT NULL AND (r.error_code IS NULL OR r.error_code='0')) AS rep_accepted,
 s.statement_amount,s.statement_rows,s.appeal_rows,s.adjustment_rows,s.statement_known
FROM eclaim.claims c
LEFT JOIN reporting.rep_latest r ON r.claim_id=c.id
LEFT JOIN LATERAL (
 SELECT sum(t.net_amount) AS statement_amount,count(*) AS statement_rows,count(t.net_amount) AS statement_known,
 count(*) FILTER(WHERE lower(coalesce(t.category,'')) LIKE '%appeal%' OR t.category='อุทธรณ์') AS appeal_rows,
 count(*) FILTER(WHERE t.net_amount<0) AS adjustment_rows
 FROM reporting.stm_current t WHERE t.claim_id=c.id
) s ON true;

CREATE OR REPLACE VIEW analytics.case_financials AS
SELECT c.*,
 l.line_count,l.cost_known_count,l.estimated_cost_count,l.line_charge,
 CASE WHEN (s.coverage->'lines'->>'state')='complete' THEN l.line_charge ELSE c.his_summary_charge END AS his_charge_amount,
 CASE WHEN (s.coverage->'lines'->>'state')='complete' THEN 'service_lines' ELSE 'his_summary' END AS his_charge_basis,
 l.observed_item_cost,l.estimated_item_cost,
 CASE WHEN l.line_count>0 THEN l.cost_known_count::numeric/l.line_count ELSE NULL END AS cost_coverage_rate,
 cl.linked_claim_count,cl.ambiguous_claim_count,cl.rep_observed_count,cl.rep_accepted_count,
 CASE WHEN cl.ambiguous_claim_count=0 AND cl.rep_accepted_count=cl.expected_known THEN cl.rep_expected_amount END AS rep_expected_amount,
 CASE WHEN cl.ambiguous_claim_count=0 AND cl.rep_accepted_count=cl.nhso_known THEN cl.rep_nhso_amount END AS rep_nhso_amount,
 CASE WHEN cl.ambiguous_claim_count=0 AND cl.statement_rows=cl.statement_known THEN cl.statement_amount END AS stm_net_amount,cl.statement_rows,
 ob.submitted_amount,ob.cash_received_amount,ob.first_submitted_at,
 CASE WHEN cl.ambiguous_claim_count>0 THEN 'MATCH_REVIEW'
      WHEN coalesce(s.coverage->'lines'->>'state','unavailable')<>'complete' THEN 'SOURCE_INCOMPLETE'
      WHEN cl.linked_claim_count=0 AND ob.first_submitted_at IS NOT NULL THEN 'REP_PENDING'
      WHEN cl.linked_claim_count=0 THEN 'SUBMISSION_UNVERIFIED'
      WHEN cl.rep_observed_count=0 THEN 'REP_PENDING'
      WHEN cl.rep_unresolved_count>0 THEN 'REP_REVISION_REVIEW'
      WHEN cl.rep_accepted_count=0 THEN 'REP_REJECTED'
      WHEN cl.uncovered_claim_count=cl.linked_claim_count THEN 'NOT_COVERED'
      WHEN cl.uncovered_claim_count>0 THEN 'PAYMENT_SCOPE_REVIEW'
      WHEN cl.statement_rows=0 THEN 'STM_PENDING'
      WHEN cl.statement_amount IS NULL OR cl.rep_nhso_amount IS NULL THEN 'AMOUNT_UNKNOWN'
      WHEN cl.statement_amount<=0 THEN 'ZERO_OR_REVERSAL'
      WHEN abs(cl.statement_amount-cl.rep_nhso_amount)<=0.01 THEN 'MATCHED'
      WHEN cl.statement_amount<cl.rep_nhso_amount THEN 'STATEMENT_PARTIAL'
      ELSE 'OVER_EXPECTED' END AS tracking_status,
 s.coverage,s.completed_at AS as_of,tasks.task_teams,tasks.next_followup_date,tasks.open_task_count
FROM his.cases c JOIN his.snapshots s ON s.id=c.snapshot_id
LEFT JOIN LATERAL (
 SELECT count(*) AS line_count,count(observed_item_cost) AS cost_known_count,count(estimated_item_cost) AS estimated_cost_count,
 CASE WHEN count(charge_amount)=count(*) THEN coalesce(sum(charge_amount),0) END AS line_charge,sum(observed_item_cost) AS observed_item_cost,sum(estimated_item_cost) AS estimated_item_cost
 FROM his.case_lines WHERE case_id=c.id
) l ON true
LEFT JOIN LATERAL (
 SELECT count(*) FILTER(WHERE x.status='linked') AS linked_claim_count,count(*) FILTER(WHERE x.status<>'linked') AS ambiguous_claim_count,
 count(*) FILTER(WHERE x.status='linked' AND o.rep_observed) AS rep_observed_count,
 count(*) FILTER(WHERE x.status='linked' AND o.rep_accepted) AS rep_accepted_count,
 count(*) FILTER(WHERE x.status='linked' AND o.rep_observed AND o.rep_row_id IS NULL) AS rep_unresolved_count,
 count(*) FILTER(WHERE x.status='linked' AND o.payer_family NOT IN ('UCS','STP','DEMO')) AS uncovered_claim_count,
 count(o.expected_amount) FILTER(WHERE x.status='linked' AND o.rep_accepted) AS expected_known,
 count(o.nhso_amount) FILTER(WHERE x.status='linked' AND o.rep_accepted) AS nhso_known,
 coalesce(sum(o.statement_known) FILTER(WHERE x.status='linked'),0) AS statement_known,
 sum(o.expected_amount) FILTER(WHERE x.status='linked' AND o.rep_accepted) AS rep_expected_amount,
 sum(o.nhso_amount) FILTER(WHERE x.status='linked' AND o.rep_accepted) AS rep_nhso_amount,
 sum(o.statement_amount) FILTER(WHERE x.status='linked') AS statement_amount,
 coalesce(sum(o.statement_rows) FILTER(WHERE x.status='linked'),0) AS statement_rows
 FROM followup.claim_links x JOIN analytics.rep_claim_observations o ON o.claim_id=x.claim_id WHERE x.case_id=c.id
) cl ON true
LEFT JOIN LATERAL (
 WITH evidence AS (SELECT * FROM followup.observations WHERE hcode=c.hcode AND encounter_key=c.encounter_key AND verification='reviewed'),
 ranked AS (SELECT *,dense_rank() OVER(PARTITION BY metadata->>'component_key' ORDER BY occurred_at DESC) AS r FROM evidence WHERE event_type='SUBMISSION'),
 components AS (SELECT metadata->>'component_key' AS component,count(*) AS n,max(amount) AS amount FROM ranked WHERE r=1 GROUP BY 1)
 SELECT (SELECT CASE WHEN bool_and(n=1 AND amount IS NOT NULL) THEN sum(amount) END FROM components) AS submitted_amount,
 (SELECT sum(amount) FROM evidence WHERE event_type='CASH_RECEIPT') AS cash_received_amount,
 (SELECT min(occurred_at) FROM evidence WHERE event_type='SUBMISSION') AS first_submitted_at
) ob ON true
LEFT JOIN LATERAL (
 SELECT string_agg(DISTINCT team,', ') AS task_teams,min(due_date) AS next_followup_date,count(*) AS open_task_count
 FROM followup.tasks WHERE hcode=c.hcode AND encounter_key=c.encounter_key AND status<>'resolved'
) tasks ON true
WHERE s.status IN ('ready','partial');

CREATE OR REPLACE FUNCTION followup.take_job(p_owner uuid) RETURNS jsonb LANGUAGE plpgsql AS $fn$
DECLARE j followup.jobs%ROWTYPE;
BEGIN
 -- One import/sync worker across processes, with crash recovery by lease.
 PERFORM pg_advisory_xact_lock(10929,27001);
 IF EXISTS(SELECT 1 FROM followup.jobs WHERE owner_id IS NOT NULL AND lease_until>now() AND status IN ('inspecting','importing','syncing','refreshing','verifying')) THEN RETURN NULL; END IF;
 SELECT * INTO j FROM followup.jobs WHERE pause_requested=false AND
  (status='queued' OR (owner_id IS NOT NULL AND lease_until<now() AND status IN ('inspecting','importing','syncing','refreshing','verifying')))
  ORDER BY created_at LIMIT 1 FOR UPDATE SKIP LOCKED;
 IF NOT FOUND THEN RETURN NULL; END IF;
 UPDATE followup.jobs SET owner_id=p_owner,lease_until=now()+interval '180 seconds',
  status=CASE WHEN kind='IMPORT' AND status='queued' THEN 'inspecting' WHEN kind='HIS_SYNC' THEN 'syncing' ELSE status END,
  updated_at=now() WHERE id=j.id RETURNING * INTO j;
 RETURN to_jsonb(j);
END $fn$;

INSERT INTO followup.schema_versions(version) VALUES('0.1.0') ON CONFLICT DO NOTHING;
