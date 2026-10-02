"""Generate the reviewable, idempotent PostgreSQL migration."""
from pathlib import Path
from .parser import KINDS, COMMON, CLAIM_FIELDS, ITEM_FIELDS, SUMMARY_FIELDS

NUMERIC = {"billed_amount","expected_amount","nhso_amount","compensation_amount","deduction_amount","net_amount","rw","quantity","unit_price"}
INTEGER = {"source_row","passed_count","total_count","failed_count"}

def schema_sql():
    base = Path(__file__).with_name("schema_base.sql").read_text(encoding="utf-8")
    tables=[]
    for kind, columns in KINDS.items():
        schema = "ingest" if kind == "unmapped_rows" else "eclaim"
        defs=["id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY",
              "document_id bigint NOT NULL REFERENCES ingest.documents(id)",
              "sheet_id bigint NOT NULL REFERENCES ingest.sheets(id)"]
        if kind.endswith("claims") or kind in ("rep_drug_items","rep_instrument_items","rep_denial_items","rep_zero_pay_items"):
            defs.append("claim_id bigint REFERENCES eclaim.claims(id)")
        if columns == ITEM_FIELDS:
            defs.append("rep_claim_id bigint REFERENCES eclaim.rep_claims(id)")
        for c in columns:
            typ = "numeric" if c in NUMERIC else "bigint" if c in INTEGER else "date" if c == "service_date" else "timestamptz" if c.endswith("_at") else "jsonb" if c == "extra_data" else "text"
            tail = " NOT NULL" if c in ("source_row","extra_data") else ""
            defs.append(f"{c} {typ}{tail}")
        if kind.endswith('claims'):
            defs.append("fiscal_year_be integer GENERATED ALWAYS AS (extract(year FROM service_date)::integer + CASE WHEN extract(month FROM service_date)>=10 THEN 1 ELSE 0 END + 543) STORED")
        defs.append("UNIQUE(sheet_id,source_row)")
        tables.append(f"CREATE TABLE IF NOT EXISTS {schema}.{kind} (\n  "+",\n  ".join(defs)+"\n);")
        tables.append(f"CREATE INDEX IF NOT EXISTS {kind}_doc_idx ON {schema}.{kind}(document_id);")
        if "claim_id" in " ".join(defs):
            tables.append(f"CREATE INDEX IF NOT EXISTS {kind}_claim_idx ON {schema}.{kind}(claim_id);")
        if columns == ITEM_FIELDS:
            tables.append(f"CREATE INDEX IF NOT EXISTS {kind}_parent_idx ON {schema}.{kind}(rep_claim_id);")
        if kind.endswith('claims'):
            tables.append(f"CREATE INDEX IF NOT EXISTS {kind}_match_idx ON {schema}.{kind}(hcode,payer_family,patient_type,rep_no,tran_id);")
            tables.append(f"CREATE INDEX IF NOT EXISTS {kind}_claim_rep_idx ON {schema}.{kind}(claim_id,rep_no);")
            tables.append(f"CREATE INDEX IF NOT EXISTS {kind}_doc_tran_idx ON {schema}.{kind}(document_id,tran_id);")
            tables.append(f"CREATE INDEX IF NOT EXISTS {kind}_service_idx ON {schema}.{kind}(hcode,service_date);")
    return base.replace("-- FACT_TABLES", "\n".join(tables)) + "\n" + Path(__file__).with_name("schema_functions.sql").read_text(encoding="utf-8")
