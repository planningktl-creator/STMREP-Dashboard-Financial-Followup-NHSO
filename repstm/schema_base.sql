CREATE SCHEMA IF NOT EXISTS ingest;
CREATE SCHEMA IF NOT EXISTS eclaim;
CREATE SCHEMA IF NOT EXISTS reporting;

CREATE TABLE IF NOT EXISTS ingest.schema_versions (
 version text PRIMARY KEY, installed_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS ingest.runs (
 id uuid PRIMARY KEY, started_at timestamptz NOT NULL DEFAULT now(), finished_at timestamptz,
 status text NOT NULL DEFAULT 'running', metadata jsonb NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS ingest.documents (
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 fingerprint text NOT NULL UNIQUE CHECK(length(fingerprint)=64),
 logical_key text NOT NULL, document_ref text, source text NOT NULL CHECK(source IN ('REP','STM')),
 hcode text NOT NULL, payer_family text NOT NULL, patient_type text NOT NULL CHECK(patient_type IN ('IP','OP')),
 reported_at timestamptz, statement_month date, expected_counts jsonb NOT NULL,
 source_counts jsonb NOT NULL DEFAULT '{}', source_sums jsonb NOT NULL DEFAULT '{}',
 status text NOT NULL DEFAULT 'loading' CHECK(status IN ('loading','ready','blocked','ambiguous')),
 is_current boolean NOT NULL DEFAULT false, created_at timestamptz NOT NULL DEFAULT now(), completed_at timestamptz
);
CREATE INDEX IF NOT EXISTS documents_logical_idx ON ingest.documents(logical_key,reported_at DESC);
CREATE INDEX IF NOT EXISTS documents_statement_idx ON ingest.documents(hcode,statement_month);
CREATE UNIQUE INDEX IF NOT EXISTS documents_current_idx ON ingest.documents(logical_key) WHERE is_current;
CREATE TABLE IF NOT EXISTS ingest.files (
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY, sha256 text NOT NULL CHECK(length(sha256)=64),
 source_path text NOT NULL, filename text NOT NULL, byte_size bigint NOT NULL, archive_path text,
 document_id bigint NOT NULL REFERENCES ingest.documents(id), reported_at timestamptz,
 metadata jsonb NOT NULL DEFAULT '{}', UNIQUE(sha256,source_path)
);
CREATE INDEX IF NOT EXISTS files_document_idx ON ingest.files(document_id);
CREATE TABLE IF NOT EXISTS ingest.file_document_links (
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 file_id bigint NOT NULL REFERENCES ingest.files(id),
 document_id bigint NOT NULL REFERENCES ingest.documents(id),
 linked_at timestamptz NOT NULL DEFAULT now(),UNIQUE(file_id,document_id)
);
CREATE INDEX IF NOT EXISTS file_document_links_document_idx ON ingest.file_document_links(document_id);
INSERT INTO ingest.file_document_links(file_id,document_id) SELECT id,document_id FROM ingest.files ON CONFLICT DO NOTHING;
CREATE OR REPLACE VIEW ingest.document_files AS
 SELECT f.*,l.document_id AS linked_document_id FROM ingest.files f JOIN ingest.file_document_links l ON l.file_id=f.id;
CREATE TABLE IF NOT EXISTS ingest.layouts (
 fingerprint text PRIMARY KEY, definition jsonb NOT NULL, first_seen_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS ingest.sheets (
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY, document_id bigint NOT NULL REFERENCES ingest.documents(id),
 sheet_index integer NOT NULL, name text NOT NULL, kind text NOT NULL,
 layout_id text NOT NULL REFERENCES ingest.layouts(fingerprint), physical_rows bigint NOT NULL,
 data_rows bigint NOT NULL, metadata jsonb NOT NULL DEFAULT '[]', UNIQUE(document_id,sheet_index)
);
CREATE TABLE IF NOT EXISTS ingest.batches (
 id uuid PRIMARY KEY, run_id uuid NOT NULL REFERENCES ingest.runs(id), payload_hash text NOT NULL,
 committed_at timestamptz NOT NULL DEFAULT now(), records bigint NOT NULL, result jsonb NOT NULL
);
CREATE TABLE IF NOT EXISTS ingest.issues (
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY, document_id bigint REFERENCES ingest.documents(id),
 sheet_index integer, source_row bigint, severity text NOT NULL, code text NOT NULL,
 detail jsonb NOT NULL DEFAULT '{}', created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS issues_document_idx ON ingest.issues(document_id);
CREATE UNIQUE INDEX IF NOT EXISTS issues_provenance_idx ON ingest.issues(document_id,sheet_index,source_row,code) NULLS NOT DISTINCT;
CREATE TABLE IF NOT EXISTS eclaim.claims (
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY, hcode text NOT NULL, payer_family text NOT NULL,
 patient_type text NOT NULL, tran_id text NOT NULL, hn text, an text, pid text,
 UNIQUE(hcode,payer_family,patient_type,tran_id)
);
CREATE INDEX IF NOT EXISTS claims_hn_idx ON eclaim.claims(hcode,hn);
CREATE INDEX IF NOT EXISTS claims_an_idx ON eclaim.claims(hcode,an) WHERE an IS NOT NULL;
CREATE INDEX IF NOT EXISTS claims_pid_idx ON eclaim.claims(pid) WHERE pid IS NOT NULL;

-- FACT_TABLES

CREATE TABLE IF NOT EXISTS reporting.dirty_claims (
 claim_id bigint PRIMARY KEY REFERENCES eclaim.claims(id)
);
CREATE TABLE IF NOT EXISTS reporting.dirty_months (
 basis text NOT NULL, month date NOT NULL, PRIMARY KEY(basis,month)
);
CREATE TABLE IF NOT EXISTS reporting.reconciliation_matches (
 stm_claim_id bigint PRIMARY KEY REFERENCES eclaim.stm_claims(id),
 rep_claim_id bigint REFERENCES eclaim.rep_claims(id), status text NOT NULL,
 candidate_count integer NOT NULL, method text NOT NULL DEFAULT 'HCODE_PAYER_TYPE_REP_TRAN',
 refreshed_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS reconciliation_rep_idx ON reporting.reconciliation_matches(rep_claim_id);
CREATE TABLE IF NOT EXISTS reporting.monthly_totals (
 basis text NOT NULL, month date NOT NULL, hcode text NOT NULL, payer_family text NOT NULL,
 patient_type text NOT NULL, category text NOT NULL, fiscal_year_be integer NOT NULL,
 rep_count bigint NOT NULL, stm_count bigint NOT NULL, billed_amount numeric NOT NULL,
 expected_amount numeric NOT NULL, statement_amount numeric NOT NULL,
 refreshed_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(basis,month,hcode,payer_family,patient_type,category)
);
