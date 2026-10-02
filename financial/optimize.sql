CREATE OR REPLACE FUNCTION his.rebuild_links_for_claims(p_snapshot uuid,p_claim_ids bigint[]) RETURNS bigint LANGUAGE plpgsql AS $fn$
DECLARE n bigint;
BEGIN
 DELETE FROM followup.claim_links WHERE snapshot_id=p_snapshot AND (p_claim_ids IS NULL OR claim_id=ANY(p_claim_ids));
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
  WHERE c.snapshot_id=p_snapshot AND (p_claim_ids IS NULL OR q.id=ANY(p_claim_ids))
 ), checked AS (SELECT *,count(*) OVER(PARTITION BY claim_id) AS alternatives FROM candidates)
 SELECT p_snapshot,case_id,claim_id,CASE WHEN alternatives=1 AND identity_ok THEN 'linked' ELSE 'review' END,
 method,jsonb_build_object('candidate_count',alternatives,'patient_consistent',identity_ok,'payer_verification','observed_claim_scope') FROM checked;
 GET DIAGNOSTICS n=ROW_COUNT;
 RETURN n;
END $fn$;

-- Queue entries survive worker/release restarts. Inserting a dirty reporting
-- key happens in the document activation transaction before visibility changes.
CREATE TABLE IF NOT EXISTS his.dirty_claim_links (
 claim_id bigint PRIMARY KEY REFERENCES eclaim.claims(id) ON DELETE CASCADE,
 queued_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS analytics.data_state (
 hcode text PRIMARY KEY,revision bigint NOT NULL DEFAULT 0
);
INSERT INTO analytics.data_state(hcode) VALUES('10929') ON CONFLICT DO NOTHING;

CREATE OR REPLACE FUNCTION analytics.bump_revision() RETURNS trigger LANGUAGE plpgsql AS $fn$
BEGIN
 INSERT INTO analytics.data_state(hcode,revision) VALUES(NEW.hcode,1)
 ON CONFLICT(hcode) DO UPDATE SET revision=analytics.data_state.revision+1;
 IF TG_OP='UPDATE' AND OLD.hcode IS DISTINCT FROM NEW.hcode THEN
  INSERT INTO analytics.data_state(hcode,revision) VALUES(OLD.hcode,1)
  ON CONFLICT(hcode) DO UPDATE SET revision=analytics.data_state.revision+1;
 END IF;
 RETURN NEW;
END $fn$;
DROP TRIGGER IF EXISTS documents_revision ON ingest.documents;
CREATE TRIGGER documents_revision AFTER UPDATE ON ingest.documents FOR EACH ROW
 WHEN (OLD.status IS DISTINCT FROM NEW.status OR OLD.is_current IS DISTINCT FROM NEW.is_current)
 EXECUTE FUNCTION analytics.bump_revision();
DROP TRIGGER IF EXISTS snapshots_revision ON his.snapshots;
CREATE TRIGGER snapshots_revision AFTER UPDATE ON his.snapshots FOR EACH ROW
 WHEN (NEW.status IN ('ready','partial') AND OLD.status IS DISTINCT FROM NEW.status)
 EXECUTE FUNCTION analytics.bump_revision();
DROP TRIGGER IF EXISTS tasks_revision ON followup.tasks;
CREATE TRIGGER tasks_revision AFTER INSERT OR UPDATE ON followup.tasks FOR EACH ROW EXECUTE FUNCTION analytics.bump_revision();
DROP TRIGGER IF EXISTS observations_revision ON followup.observations;
CREATE TRIGGER observations_revision AFTER INSERT OR UPDATE ON followup.observations FOR EACH ROW EXECUTE FUNCTION analytics.bump_revision();
DROP TRIGGER IF EXISTS identity_revision ON eclaim.claims;
CREATE TRIGGER identity_revision AFTER UPDATE ON eclaim.claims FOR EACH ROW
 WHEN (OLD.hcode IS DISTINCT FROM NEW.hcode OR OLD.patient_type IS DISTINCT FROM NEW.patient_type
 OR OLD.an IS DISTINCT FROM NEW.an OR OLD.hn IS DISTINCT FROM NEW.hn OR OLD.pid IS DISTINCT FROM NEW.pid OR OLD.tran_id IS DISTINCT FROM NEW.tran_id)
 EXECUTE FUNCTION analytics.bump_revision();

CREATE OR REPLACE FUNCTION his.queue_claim_links() RETURNS trigger LANGUAGE plpgsql AS $fn$
DECLARE key bigint;
BEGIN
 IF TG_TABLE_SCHEMA='reporting' THEN key:=NEW.claim_id; ELSE key:=NEW.id; END IF;
 INSERT INTO his.dirty_claim_links(claim_id) VALUES(key) ON CONFLICT DO NOTHING;
 RETURN NEW;
END $fn$;
DROP TRIGGER IF EXISTS reporting_queue_links ON reporting.dirty_claims;
CREATE TRIGGER reporting_queue_links AFTER INSERT ON reporting.dirty_claims FOR EACH ROW EXECUTE FUNCTION his.queue_claim_links();
DROP TRIGGER IF EXISTS claim_queue_links ON eclaim.claims;
CREATE TRIGGER claim_queue_links AFTER UPDATE ON eclaim.claims FOR EACH ROW
 WHEN (OLD.hcode IS DISTINCT FROM NEW.hcode OR OLD.patient_type IS DISTINCT FROM NEW.patient_type
 OR OLD.an IS DISTINCT FROM NEW.an OR OLD.hn IS DISTINCT FROM NEW.hn OR OLD.pid IS DISTINCT FROM NEW.pid OR OLD.tran_id IS DISTINCT FROM NEW.tran_id)
 EXECUTE FUNCTION his.queue_claim_links();
INSERT INTO his.dirty_claim_links(claim_id) SELECT claim_id FROM reporting.dirty_claims ON CONFLICT DO NOTHING;

CREATE OR REPLACE FUNCTION his.rebuild_links(p_snapshot uuid) RETURNS bigint LANGUAGE plpgsql AS $fn$
BEGIN
 RETURN his.rebuild_links_for_claims(p_snapshot,NULL);
END $fn$;

CREATE OR REPLACE FUNCTION his.refresh_links(p_limit integer DEFAULT 200) RETURNS integer LANGUAGE plpgsql AS $fn$
DECLARE keys bigint[]; snap uuid;
BEGIN
 IF p_limit<1 OR p_limit>2000 THEN RAISE EXCEPTION 'INVALID_REFRESH_LIMIT'; END IF;
 SELECT array_agg(claim_id) INTO keys FROM (
  SELECT claim_id FROM his.dirty_claim_links ORDER BY claim_id LIMIT p_limit FOR UPDATE SKIP LOCKED
 ) selected;
 IF keys IS NULL THEN RETURN 0; END IF;
 -- Keep old snapshots affected by an identity change, including candidates
 -- that have moved to another AN. New OP links require the verified VN bridge.
 FOR snap IN
  SELECT DISTINCT s.id FROM his.snapshots s WHERE s.status IN ('ready','partial') AND (
   EXISTS(SELECT 1 FROM followup.claim_links l WHERE l.snapshot_id=s.id AND l.claim_id=ANY(keys)) OR
   EXISTS(SELECT 1 FROM his.cases c JOIN eclaim.claims q ON q.hcode=c.hcode AND q.patient_type=c.care_type
    AND q.id=ANY(keys) WHERE c.snapshot_id=s.id AND (
     (c.care_type='IP' AND c.an=q.an) OR
     (c.care_type='OP' AND EXISTS(SELECT 1 FROM his.records b WHERE b.snapshot_id=s.id AND b.dataset='rep_bridge'
       AND b.payload->>'vn'=c.vn AND b.payload->>'rep_eclaim_detail_tran_id'=q.tran_id))))
  ) ORDER BY s.id
 LOOP
  PERFORM his.rebuild_links_for_claims(snap,keys);
 END LOOP;
 DELETE FROM his.dirty_claim_links WHERE claim_id=ANY(keys);
 RETURN cardinality(keys);
END $fn$;

CREATE OR REPLACE FUNCTION analytics.refresh_status(p_hcode text) RETURNS jsonb LANGUAGE sql STABLE AS $fn$
 WITH pending AS (
  SELECT (SELECT count(*) FROM reporting.dirty_claims d JOIN eclaim.claims c ON c.id=d.claim_id WHERE c.hcode=p_hcode) AS claims,
   -- Month queue is global: conservatively mark reports pending until drained.
   (SELECT count(*) FROM reporting.dirty_months) AS months,
   (SELECT count(*) FROM his.dirty_claim_links) AS links
 ) SELECT jsonb_build_object('data_revision',coalesce((SELECT revision::text FROM analytics.data_state WHERE hcode=p_hcode),'0'),
  'state',CASE WHEN claims+months+links=0 THEN 'ready' ELSE 'pending' END,'pending',to_jsonb(p)) FROM pending p;
$fn$;
INSERT INTO followup.schema_versions(version) VALUES('0.2.0-optimize') ON CONFLICT DO NOTHING;

-- EXPLAIN on the 5,000-case fixture measured ~2.4 s of JIT compilation
-- versus ~0.1 s of execution. Scope this setting to the report function;
-- do not change the shared hospital database or leak a BEGIN transaction.
CREATE OR REPLACE FUNCTION analytics.report_json(p_sql text) RETURNS jsonb
 LANGUAGE plpgsql SECURITY INVOKER SET jit=off AS $fn$
DECLARE result jsonb;
BEGIN
 EXECUTE p_sql INTO result;
 RETURN result;
END $fn$;
CREATE OR REPLACE FUNCTION analytics.explain_query(p_sql text) RETURNS jsonb
 LANGUAGE plpgsql SECURITY INVOKER SET jit=off AS $fn$
DECLARE result jsonb;
BEGIN
 EXECUTE 'EXPLAIN (ANALYZE,BUFFERS,FORMAT JSON) '||p_sql INTO result;
 RETURN result;
END $fn$;
REVOKE ALL ON FUNCTION analytics.report_json(text),analytics.explain_query(text) FROM PUBLIC;

