-- Immutable evidence, replay-safe writes and receipt allocation guards.
CREATE TABLE IF NOT EXISTS followup.task_history(
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,task_id uuid NOT NULL REFERENCES followup.tasks(id),
 status text NOT NULL,team text NOT NULL,due_date date,note text NOT NULL,actor_ref text NOT NULL,
 changed_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS task_history_task_idx ON followup.task_history(task_id,id);
CREATE OR REPLACE FUNCTION followup.capture_task_history() RETURNS trigger LANGUAGE plpgsql AS $fn$
BEGIN
 IF TG_OP='INSERT' OR (NEW.status,NEW.team,NEW.due_date,NEW.note) IS DISTINCT FROM (OLD.status,OLD.team,OLD.due_date,OLD.note) THEN
  INSERT INTO followup.task_history(task_id,status,team,due_date,note,actor_ref) VALUES(NEW.id,NEW.status,NEW.team,NEW.due_date,NEW.note,NEW.actor_ref);
 END IF;
 RETURN NEW;
END $fn$;
DROP TRIGGER IF EXISTS task_history_capture ON followup.tasks;
CREATE TRIGGER task_history_capture AFTER INSERT OR UPDATE ON followup.tasks FOR EACH ROW EXECUTE FUNCTION followup.capture_task_history();
CREATE TABLE IF NOT EXISTS followup.receipts(
 hcode text NOT NULL,source_ref text NOT NULL,total_amount numeric NOT NULL,
 occurred_at timestamptz NOT NULL,actor_ref text NOT NULL,created_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(hcode,source_ref)
);
CREATE OR REPLACE FUNCTION followup.record_observation(p_id uuid,p_actor text,p_data jsonb)
RETURNS jsonb LANGUAGE plpgsql AS $fn$
DECLARE old followup.observations; receipt followup.receipts; allocated numeric; meta jsonb;
BEGIN
 PERFORM pg_advisory_xact_lock(hashtextextended(p_id::text,0));
 meta:=jsonb_build_object('component_key',coalesce(p_data->>'component_key','case_total'),'receipt_total',p_data->>'receipt_total');
 SELECT * INTO old FROM followup.observations WHERE id=p_id;
 IF FOUND THEN
  IF old.hcode<>p_data->>'hcode' OR old.encounter_key<>p_data->>'encounter_key' OR old.event_type<>p_data->>'event_type'
    OR old.occurred_at<>(p_data->>'occurred_at')::timestamptz OR old.amount IS DISTINCT FROM (p_data->>'amount')::numeric
    OR old.source_ref<>p_data->>'source_ref' OR old.verification<>p_data->>'verification' OR old.metadata<>meta THEN
   RAISE EXCEPTION 'OBSERVATION_ID_COLLISION';
  END IF;
  RETURN jsonb_build_object('id',p_id,'replayed',true);
 END IF;
 IF NOT EXISTS(SELECT 1 FROM his.cases WHERE hcode=p_data->>'hcode' AND encounter_key=p_data->>'encounter_key') THEN RAISE EXCEPTION 'CASE_NOT_FOUND'; END IF;
 IF p_data->>'event_type'='CASH_RECEIPT' THEN
  IF p_data->>'amount' IS NULL OR p_data->>'receipt_total' IS NULL THEN RAISE EXCEPTION 'CASH_ALLOCATION_REQUIRED'; END IF;
  PERFORM pg_advisory_xact_lock(hashtextextended((p_data->>'hcode')||':receipt:'||(p_data->>'source_ref'),0));
  SELECT * INTO receipt FROM followup.receipts WHERE hcode=p_data->>'hcode' AND source_ref=p_data->>'source_ref';
  IF FOUND AND (receipt.total_amount<>(p_data->>'receipt_total')::numeric OR receipt.occurred_at<>(p_data->>'occurred_at')::timestamptz) THEN RAISE EXCEPTION 'RECEIPT_TOTAL_COLLISION'; END IF;
  INSERT INTO followup.receipts(hcode,source_ref,total_amount,occurred_at,actor_ref)
   VALUES(p_data->>'hcode',p_data->>'source_ref',(p_data->>'receipt_total')::numeric,(p_data->>'occurred_at')::timestamptz,p_actor) ON CONFLICT DO NOTHING;
  IF (p_data->>'amount')::numeric*(p_data->>'receipt_total')::numeric<0 THEN RAISE EXCEPTION 'CASH_ALLOCATION_SIGN_MISMATCH'; END IF;
  SELECT coalesce(sum(abs(amount)),0) INTO allocated FROM followup.observations WHERE hcode=p_data->>'hcode' AND source_ref=p_data->>'source_ref' AND event_type='CASH_RECEIPT' AND verification='reviewed';
  IF p_data->>'verification'='reviewed' AND allocated+abs((p_data->>'amount')::numeric)>abs((p_data->>'receipt_total')::numeric) THEN RAISE EXCEPTION 'RECEIPT_OVER_ALLOCATED'; END IF;
 END IF;
 INSERT INTO followup.observations(id,hcode,encounter_key,event_type,occurred_at,amount,source_ref,verification,actor_ref,metadata)
 VALUES(p_id,p_data->>'hcode',p_data->>'encounter_key',p_data->>'event_type',(p_data->>'occurred_at')::timestamptz,(p_data->>'amount')::numeric,p_data->>'source_ref',p_data->>'verification',p_actor,meta);
 INSERT INTO followup.audit_events(actor_ref,event,object_id,detail) VALUES(p_actor,'evidence_committed',p_id::text,jsonb_build_object('event_type',p_data->>'event_type'));
 RETURN jsonb_build_object('id',p_id,'replayed',false);
END $fn$;

CREATE OR REPLACE FUNCTION followup.open_appeal(p_id uuid,p_actor text,p_case bigint,p_claim bigint,p_reason text)
RETURNS jsonb LANGUAGE plpgsql AS $fn$
DECLARE c his.cases; a followup.appeals; rows jsonb; baseline numeric;
BEGIN
 PERFORM pg_advisory_xact_lock(hashtextextended(p_id::text,0));
 SELECT * INTO c FROM his.cases WHERE id=p_case;
 IF NOT FOUND OR NOT EXISTS(SELECT 1 FROM followup.claim_links WHERE case_id=p_case AND claim_id=p_claim AND status='linked') THEN RAISE EXCEPTION 'CLAIM_NOT_UNIQUELY_LINKED'; END IF;
 SELECT * INTO a FROM followup.appeals WHERE id=p_id;
 IF FOUND THEN
  IF a.hcode<>c.hcode OR a.encounter_key<>c.encounter_key OR a.claim_id<>p_claim OR a.reason<>p_reason THEN RAISE EXCEPTION 'APPEAL_ID_COLLISION'; END IF;
  RETURN jsonb_build_object('id',p_id,'replayed',true);
 END IF;
 SELECT coalesce(jsonb_agg(jsonb_build_object('id',id,'document_id',document_id,'net_amount',net_amount::text) ORDER BY id),'[]'),sum(net_amount)
 INTO rows,baseline FROM reporting.stm_current WHERE claim_id=p_claim;
 INSERT INTO followup.appeals(id,hcode,encounter_key,claim_id,reason,baseline_amount,baseline_rows,actor_ref)
 VALUES(p_id,c.hcode,c.encounter_key,p_claim,p_reason,baseline,rows,p_actor);
 INSERT INTO followup.audit_events(actor_ref,event,object_id) VALUES(p_actor,'appeal_baseline_frozen',p_id::text);
 RETURN jsonb_build_object('id',p_id,'replayed',false,'baseline_amount',baseline::text);
END $fn$;

CREATE OR REPLACE FUNCTION followup.resolve_appeal(p_id uuid,p_actor text,p_result jsonb)
RETURNS jsonb LANGUAGE plpgsql AS $fn$
DECLARE a followup.appeals; row_ids bigint[]; total numeric; n integer; effect numeric; rows jsonb;
BEGIN
 SELECT * INTO a FROM followup.appeals WHERE id=p_id FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'APPEAL_NOT_FOUND'; END IF;
 SELECT array_agg(DISTINCT value::text::bigint ORDER BY value::text::bigint) INTO row_ids FROM jsonb_array_elements(p_result->'statement_row_ids');
 IF cardinality(row_ids)<>jsonb_array_length(p_result->'statement_row_ids') THEN RAISE EXCEPTION 'DUPLICATE_RESULT_ROWS'; END IF;
 IF a.status='resolved' THEN
  IF a.result_rows<>to_jsonb(row_ids) OR a.outcome<>p_result->>'outcome' OR a.effect_type<>p_result->>'effect_type' OR a.source_ref<>p_result->>'source_ref' THEN RAISE EXCEPTION 'APPEAL_RESULT_IMMUTABLE'; END IF;
  RETURN jsonb_build_object('id',p_id,'incremental_amount',a.incremental_amount::text,'replayed',true);
 END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended(a.claim_id::text||':appeal',0));
 SELECT count(*),sum(t.net_amount) INTO n,total FROM reporting.stm_current t WHERE t.id=ANY(row_ids) AND t.claim_id=a.claim_id AND t.net_amount IS NOT NULL;
 IF n<>cardinality(row_ids) THEN RAISE EXCEPTION 'RESULT_ROWS_NOT_CURRENT_SAME_CLAIM'; END IF;
 IF EXISTS(SELECT 1 FROM jsonb_array_elements(a.baseline_rows) x WHERE (x->>'id')::bigint=ANY(row_ids)) THEN RAISE EXCEPTION 'RESULT_INCLUDES_BASELINE'; END IF;
 IF EXISTS(SELECT 1 FROM followup.appeals o CROSS JOIN LATERAL jsonb_array_elements(o.result_rows) x WHERE o.id<>p_id AND o.status='resolved' AND x::text::bigint=ANY(row_ids)) THEN RAISE EXCEPTION 'RESULT_ALREADY_ATTRIBUTED'; END IF;
 IF p_result->>'effect_type' NOT IN ('DELTA','REPLACEMENT') OR p_result->>'outcome' NOT IN ('approved','partial','rejected') THEN RAISE EXCEPTION 'INVALID_APPEAL_RESULT'; END IF;
 IF p_result->>'effect_type'='REPLACEMENT' AND a.baseline_amount IS NULL THEN RAISE EXCEPTION 'APPEAL_BASELINE_UNKNOWN'; END IF;
 effect:=CASE WHEN p_result->>'effect_type'='DELTA' THEN total ELSE total-a.baseline_amount END;
 UPDATE followup.appeals SET status='resolved',outcome=p_result->>'outcome',effect_type=p_result->>'effect_type',
  source_ref=p_result->>'source_ref',result_rows=to_jsonb(row_ids),incremental_amount=effect,actor_ref=p_actor,updated_at=now() WHERE id=p_id;
 INSERT INTO followup.audit_events(actor_ref,event,object_id,detail) VALUES(p_actor,'appeal_result_reviewed',p_id::text,jsonb_build_object('effect_type',p_result->>'effect_type','statement_rows',n));
 RETURN jsonb_build_object('id',p_id,'incremental_amount',effect::text,'replayed',false);
END $fn$;
