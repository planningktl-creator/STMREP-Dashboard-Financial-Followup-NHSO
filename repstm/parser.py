"""Read BIFF Excel files without executing formulas or legacy importer code.

Core fields are typed; every original populated cell is also retained by column
in extra_data. Header paths and cell types make all remaining fields addressable.
Clinical timestamps are Thai local time. Money is never summed using float.
"""
from __future__ import annotations

import collections
import hashlib
import json
import re
from datetime import datetime, timezone, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path

import xlrd

BANGKOK = timezone(timedelta(hours=7))
VERSION = "2026-10-01.1"
REGISTRY = json.loads(Path(__file__).with_name('mapping_registry.json').read_text(encoding='utf-8'))
_approved_path=Path(__file__).with_name('approved_layouts.json')
APPROVED_LAYOUTS=json.loads(_approved_path.read_text(encoding='utf-8'))['layouts'] if _approved_path.exists() else {}
COMMON = ["source_row", "hcode", "payer_family", "patient_type", "program", "category",
          "rep_no", "source_seq", "tran_id", "hn", "an", "pid", "full_name",
          "admitted_at", "discharged_at", "service_date", "extra_data"]
CLAIM_FIELDS = COMMON + ["billed_amount", "expected_amount", "nhso_amount", "compensation_amount",
                         "deduction_amount", "net_amount", "rw", "error_code", "seq_no", "invoice_no"]
ITEM_FIELDS = COMMON + ["parent_seq", "item_seq", "item_code", "tmt_code", "item_name",
                        "quantity", "unit_price", "billed_amount", "compensation_amount", "error_code"]
SUMMARY_FIELDS = ["source_row", "hcode", "payer_family", "patient_type", "program", "category",
                  "rep_no", "passed_count", "total_count", "failed_count", "billed_amount",
                  "compensation_amount", "net_amount", "extra_data"]
REP_FIELDS = CLAIM_FIELDS + ['record_role']
KINDS = {"rep_claims": REP_FIELDS, "stm_claims": CLAIM_FIELDS,
         **{k: ITEM_FIELDS for k in ("rep_drug_items", "rep_instrument_items", "rep_denial_items", "rep_zero_pay_items")},
         **{k: SUMMARY_FIELDS for k in ("rep_summaries", "stm_rep_summaries", "stm_period_summaries")},
         "unmapped_rows": ["source_row", "extra_data"]}


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def content_digest(value):
    """Hash the exact canonical JSON without allocating a second workbook."""
    encoder=json.JSONEncoder(ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)
    checksum=hashlib.sha256();parts=[];size=0
    for chunk in encoder.iterencode(value):
        parts.append(chunk);size+=len(chunk)
        if size>=262144:
            checksum.update(''.join(parts).encode('utf-8'));parts.clear();size=0
    if parts:checksum.update(''.join(parts).encode('utf-8'))
    return checksum.hexdigest()


def text(value):
    if value is None or value == "":
        return None
    if isinstance(value, (int, float, Decimal)):
        number = Decimal(str(value))
        return format(number, "f").rstrip("0").rstrip(".") if "." in format(number, "f") else str(number)
    value = str(value).strip()
    return None if value in ("", "-") else value


def number(value):
    s = text(value)
    if s is None:
        return None
    s = s.replace(",", "")
    if s.startswith("(") and s.endswith(")"):
        s = "-" + s[1:-1]
    try:
        n = Decimal(s)
        if not n.is_finite():
            raise InvalidOperation
        return format(n, "f")
    except InvalidOperation as exc:
        raise ValueError("INVALID_NUMERIC") from exc


def sum_present(*values):
    """A missing amount is not a zero amount."""
    present = [Decimal(v) for v in values if v is not None]
    return str(sum(present, Decimal(0))) if present else None


def cell_number(sheet,row,column):
    if column is None or column>=sheet.ncols:return None
    cell=sheet.cell(row,column)
    if cell.ctype not in (xlrd.XL_CELL_NUMBER,xlrd.XL_CELL_TEXT,xlrd.XL_CELL_EMPTY,xlrd.XL_CELL_BLANK):
        raise ValueError('INVALID_NUMERIC_CELL_TYPE')
    return number(cell.value)


def integer_count(value):
    n=number(value)
    if n is None:return None
    exact=Decimal(n)
    if exact!=exact.to_integral_value():raise ValueError('INVALID_COUNT')
    return int(exact)


def timestamp(value, datemode=0, cell_type=None):
    if text(value) is None:
        return None
    if cell_type == xlrd.XL_CELL_DATE:
        return xlrd.xldate_as_datetime(value, datemode).replace(tzinfo=BANGKOK).isoformat()
    s = text(value)
    # Normalize BE before validating leap days against the Gregorian calendar.
    thai = re.match(r'^(\d{1,2}/\d{1,2}/)(\d{4})(.*)$', s)
    iso_thai = re.match(r'^(\d{4})(-\d{2}-\d{2}.*)$', s)
    if thai and int(thai[2]) >= 2400:s=thai[1]+str(int(thai[2])-543)+thai[3]
    elif iso_thai and int(iso_thai[1]) >= 2400:s=str(int(iso_thai[1])-543)+iso_thai[2]
    for fmt in ("%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M", "%d/%m/%Y", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(s, fmt)
            return dt.replace(tzinfo=BANGKOK).isoformat()
        except ValueError:
            pass
    raise ValueError("INVALID_DATE")


def fiscal_year(service_date):
    if not service_date:
        return None
    d = datetime.fromisoformat(service_date)
    return d.year + (d.month >= 10) + 543


def raw_cells(sheet, row):
    # Arrays avoid repeating 120 header strings for every source row.
    return [[c, cell.ctype, format(Decimal(str(cell.value)), "f") if cell.ctype == xlrd.XL_CELL_NUMBER else cell.value]
            for c in range(sheet.ncols)
            if (cell := sheet.cell(row, c)).ctype not in (xlrd.XL_CELL_EMPTY, xlrd.XL_CELL_BLANK)]


def clean_header(v):
    return re.sub(r"\s+", " ", str(v)).strip()


def headers(sheet, start, end):
    values = {(r, c): clean_header(sheet.cell_value(r, c)) for r in range(start, end) for c in range(sheet.ncols)}
    for r1, r2, c1, c2 in sheet.merged_cells:
        if start <= r1 < end:
            v = values.get((r1, c1), "")
            for r in range(r1, min(r2, end)):
                for c in range(c1, c2):
                    values[r, c] = v
    return [" / ".join(dict.fromkeys(values.get((r, c), "") for r in range(start, end) if values.get((r, c), "")))
            for c in range(sheet.ncols)]


def numeric_seq(value):
    s = text(value)
    return bool(s and s.isdigit())


def identifier(sheet,row,column):
    if column is None or column>=sheet.ncols:return None
    cell=sheet.cell(row,column)
    if cell.ctype in (xlrd.XL_CELL_ERROR,xlrd.XL_CELL_BOOLEAN,xlrd.XL_CELL_DATE):
        raise ValueError('INVALID_IDENTIFIER_CELL_TYPE')
    if cell.ctype==xlrd.XL_CELL_NUMBER:
        if not Decimal(str(cell.value)).is_finite() or abs(cell.value)>=2**53:raise ValueError('UNSAFE_NUMERIC_IDENTIFIER')
        book=sheet.book
        xf=book.xf_list[sheet.cell_xf_index(row,column)]
        fmt=book.format_map[xf.format_key].format_str.split(';')[0]
        if re.fullmatch(r'0{2,}',fmt) and float(cell.value).is_integer():
            return str(int(cell.value)).zfill(len(fmt))
    return text(cell.value)


def family(code):
    if "STP" in code:
        return "STP"
    if "SSS" in code:
        return "SSS"
    if "LGO" in code:
        return "LGO"
    if "CS" in code:
        return "OFC"
    if "BKK" in code:
        return "BKK"
    if "BMT" in code:
        return "BMT"
    if "SRT" in code:
        return "SRT"
    if "PVT" in code:
        return "PVT"
    base=code.split('_')[0]
    if base in ('IP','OP','OP43','ORF','IPUCS','OPUCS'):return 'UCS'
    return 'UNKNOWN:'+base


def parse_file(path: Path, profile_only=False, allow_new_layouts=False, content_path=None):
    path = Path(path)
    source = "STM" if path.name.upper().startswith("STM_") else "REP"
    match = re.match(r"(?:STM|eclaim)_(\d+)_(.*)\.xls$", path.name, re.I)
    if not match:
        raise ValueError("UNSUPPORTED_FILENAME")
    hcode, tail = match.groups()
    pt = "IP" if tail.upper().startswith("IP") else "OP"
    code = re.split(r"_\d{8}", tail)[0].upper() if source == "REP" else tail[:5].upper()
    scheme = family(code) if source == "REP" else "UCS"
    file_category = "appeal" if "APPEAL" in code else "normal"
    wb = xlrd.open_workbook(str(content_path or path), formatting_info=True, on_demand=True)
    raw=(lambda sheet,row: []) if profile_only else raw_cells
    issues, sheets, groups, controls = [], [], [], []
    reported_at, statement_month, document_ref = None, None, None
    if source == "REP":
        m = re.search(r"_(\d{8})_(\d{6})(\d*)", path.stem)
        if m:
            date_part = m[1]
            yr = int(date_part[:4]); yr -= 543 if yr >= 2400 else 0
            dt = datetime.strptime(f"{yr:04d}{date_part[4:]}{m[2]}", "%Y%m%d%H%M%S")
            reported_at = dt.replace(tzinfo=BANGKOK).isoformat()
        first = wb.sheet_by_index(0)
        for r in range(min(10, first.nrows)):
            for v in first.row_values(r):
                printed=re.search(r'ออกรายงานวันที่\s*(\d+/\d+/\d+)\s*เวลา\s*(\d+:\d+)',str(v))
                if printed:reported_at=timestamp(printed[1]+' '+printed[2])
        del first
    else:
        summary = wb.sheet_by_index(0)
        for r in range(min(10, summary.nrows)):
            for v in summary.row_values(r):
                s = str(v)
                m = re.search(r"เลขที่เอกสาร\s*(\S+)", s)
                if m:
                    document_ref = m[1]
                m = re.search(r"ออกรายงานวันที่\s*(\d+/\d+/\d+)\s*เวลา\s*(\d+:\d+)", s)
                if m:
                    reported_at = timestamp(m[1] + " " + m[2])
        m = re.search(r"S(\d{4})(\d{2})", document_ref or path.name)
        if m:
            statement_month = f"{int(m[1])-543:04d}-{m[2]}-01"
        del summary
    counts = collections.Counter()
    sums = collections.defaultdict(Decimal)

    def issue(code_, severity="error", sheet=None, row=None, detail=None):
        issues.append({"code": code_, "severity": severity, "sheet_index": sheet,
                       "source_row": row, "detail": detail or {}})

    if scheme.startswith('UNKNOWN:'):issue('UNKNOWN_REPORT_FAMILY',detail={'report_family':code})

    for si in range(wb.nsheets):
        sheet=wb.sheet_by_index(si)
        name = sheet.name.strip()
        program = "STP" if "STP" in name else "D1" if "D1" in name else code.split("_APPEAL")[0] if source == "REP" else "UCS"
        payer = "STP" if program == "STP" else scheme
        category = "appeal" if "อุทธรณ์" in name else "normal" if source == "STM" else file_category
        kind, hr, start, hdr = None, None, 0, []
        anchor = [r for r in range(min(40, sheet.nrows)) if any(str(v).strip().upper() == "TRAN_ID" for v in sheet.row_values(r))]
        if source == "STM" and "รายละเอียด" in name:
            kind = "stm_claims"
        elif source == "REP" and name.lower().startswith("detail"):
            kind = "rep_claims"
        elif name.lower().startswith("data drug"):
            kind = "rep_drug_items"
        elif name.lower().startswith("data instrument"):
            kind = "rep_instrument_items"
        elif name.lower().startswith("data deny"):
            kind = "rep_denial_items"
        elif name.lower().startswith("data sheet 0"):
            kind = "rep_zero_pay_items"
        elif source == "STM" and "รายงานสรุป" in name:
            kind, hr = "stm_rep_summaries", 11
        elif source == "STM" and "รายงานพึงรับ" in name:
            kind = "stm_period_summaries"
        elif source == "REP" and name.lower().startswith("summary"):
            kind = 'rep_summaries'
            hr=next((r for r in range(min(20,sheet.nrows))
                     if re.sub(r'[^A-Z]','',str(sheet.cell_value(r,2)).upper())=='REPNO'),1)
        if kind in ("stm_claims", "rep_claims") or kind in ITEM_KINDS:
            if not anchor and kind=='rep_instrument_items' and sheet.ncols==14:
                anchor=[r for r in range(min(40,sheet.nrows)) if str(sheet.cell_value(r,1)).strip()=='HN']
            if not anchor:
                issue("MISSING_HEADER", sheet=si)
                kind = "unmapped_rows"
            else:
                hr = anchor[0]
                # ORF has merged financial headers above the TRAN_ID row.
                crossing=[r1 for r1,r2,c1,c2 in sheet.merged_cells if r1 < hr < r2 and r1>=hr-3]
                if crossing:hr=min(hr,*crossing)
                seqcol = 1 if kind.endswith("claims") else 0
                data_rows = [r for r in range(hr+1, sheet.nrows) if numeric_seq(sheet.cell_value(r, seqcol))]
                start = data_rows[0] if data_rows else min(hr+3, sheet.nrows)
                hdr = headers(sheet, hr, start)
                valid = validate_layout(kind, sheet.ncols, hdr)
                if not valid:
                    issue("UNSUPPORTED_LAYOUT", sheet=si, detail={"columns": sheet.ncols})
                    kind = "unmapped_rows"
        elif hr is not None:
            if kind == "stm_rep_summaries":
                start = min(14, sheet.nrows); hdr = headers(sheet, hr, start)
            else:
                start = next((r for r in range(2, sheet.nrows) if numeric_seq(sheet.cell_value(r, 2))), sheet.nrows)
                hdr = headers(sheet, hr, start)
                if sheet.ncols not in (55,56,57,59,65) or not any('จำนวนราย' in h and h.endswith('/ ผ่าน') for h in hdr):
                    issue('UNSUPPORTED_SUMMARY_LAYOUT',sheet=si,detail={'columns':sheet.ncols})
                    kind='unmapped_rows'
        if kind is None:
            issue("UNKNOWN_SHEET", sheet=si, detail={"name": name})
            kind = "unmapped_rows"
        if kind=='stm_period_summaries':hdr=['labeled_period_summary']
        candidate_layout={"source":source,"kind":kind,"width":sheet.ncols,"header_paths":hdr,
                          "header_row":None if hr is None else hr+1,"data_start_row":start+1,"mapping_version":VERSION}
        if kind!='unmapped_rows' and APPROVED_LAYOUTS and not allow_new_layouts and digest(candidate_layout) not in APPROVED_LAYOUTS:
            issue('UNAPPROVED_LAYOUT_FINGERPRINT',sheet=si,detail={'fingerprint':digest(candidate_layout),'columns':sheet.ncols})
            kind='unmapped_rows'
        rows = []
        section=category
        if kind=='stm_claims':
            for r in range(start):
                label=' '.join(str(v) for v in sheet.row_values(r)[:2])
                if 'ข้อมูลอุทธรณ์' in label:section='appeal'
                elif 'ข้อมูลปกติ' in label:section='normal'
        for r in range(start, sheet.nrows):
            vals = sheet.row_values(r)
            if kind=='stm_claims':
                label=' '.join(str(v) for v in vals[:2])
                if 'ข้อมูลอุทธรณ์' in label:section='appeal'
                elif 'ข้อมูลปกติ' in label:section='normal'
            if not any(v != "" for v in vals):
                continue
            if kind.endswith("claims") and (not numeric_seq(vals[1]) or not text(vals[0])):
                continue
            if kind in ITEM_KINDS and not numeric_seq(vals[0]):
                continue
            if kind == "stm_rep_summaries" and not numeric_seq(vals[2]):
                continue
            if kind == "rep_summaries" and not numeric_seq(vals[2]):
                continue
            if kind == "stm_period_summaries":
                continue  # Parsed by labeled sections below, not fixed line offsets.
            rec = {"source_row": r+1, "hcode": hcode, "payer_family": payer, "patient_type": pt,
                   "program": program, "category": section if kind=='stm_claims' else category, "extra_data": raw(sheet, r)}
            try:
                if kind.endswith("claims"):
                    parse_claim(rec, vals, sheet, r, wb.datemode, source, hdr)
                    if kind=='rep_claims' and rec['billed_amount'] is None:
                        issue('BILLED_AMOUNT_UNAVAILABLE','warning',si,r+1)
                    if not rec.get("tran_id"):
                        issue("MISSING_TRAN_ID", sheet=si, row=r+1)
                    if rec.get("service_date") is None:
                        issue("MISSING_SERVICE_DATE", "warning", si, r+1)
                    if kind == "stm_claims":
                        key = f"{program}:{rec['category']}"
                        counts[key] += 1
                        sums[key] += Decimal(rec.get("compensation_amount") or "0")
                elif kind in ITEM_KINDS:
                    parse_item(rec, vals, kind, wb.datemode, sheet, r, hdr)
                elif kind in ("rep_summaries", "stm_rep_summaries"):
                    parse_summary(rec, vals, hdr, kind, sheet, r)
            except ValueError as exc:
                issue(str(exc), sheet=si, row=r+1)
                rec["extra_data"] = raw(sheet, r)
                # Bad rows remain in a provenance table; the document is blocked.
                groups.append({"sheet_index": si, "kind": "unmapped_rows", "columns": KINDS["unmapped_rows"],
                               "rows": [[r+1, rec["extra_data"]]]})
                continue
            rows.append([rec.get(c) for c in KINDS[kind]])
        if kind == "stm_period_summaries":
            section = "normal"
            found = {}
            for r in range(sheet.nrows):
                vals = sheet.row_values(r)
                if "ข้อมูลอุทธรณ์" in str(vals[0]): section = "appeal"
                if "ข้อมูลปกติ" in str(vals[0]): section = "normal"
                if "ผู้ป่วย" in str(vals[0]) and len(vals)>4:
                    rec = {"source_row": r+1, "hcode": hcode, "payer_family": payer,
                           "patient_type": pt, "program": program, "category": section,
                           "passed_count": integer_count(cell_number(sheet,r,2)), "compensation_amount": cell_number(sheet,r,4),
                           "extra_data": raw(sheet, r)}
                    found[section] = rec
                elif any(str(v).strip() == "รวม" for v in vals):
                    total_col = next(c for c,v in enumerate(vals) if str(v).strip() == "รวม") + 1
                    rec = found.setdefault(section, {"source_row": r+1, "hcode": hcode, "payer_family": payer,
                          "patient_type": pt, "program": program, "category": section, "passed_count": 0, "extra_data": []})
                    rec["net_amount"] = cell_number(sheet,r,total_col)
            for section, rec in found.items():
                rows.append([rec.get(c) for c in KINDS[kind]])
                controls.append({"key": f"{program}:{section}", "count": rec["passed_count"],
                                 "gross": rec.get("compensation_amount"), "net": rec.get("net_amount"), "sheet_index": si, "source_row": rec["source_row"]})
            hdr = ["labeled_period_summary"]
        layout = {"source": source, "kind": kind, "width": sheet.ncols, "header_paths": hdr,
                  "header_row": None if hr is None else hr+1, "data_start_row": start+1, "mapping_version": VERSION}
        layout_id = digest(layout)
        metadata_rows = [raw(sheet, r) for r in range(min(start, sheet.nrows))]
        used={row[0] for row in rows}
        used.update(row[0] for g in groups if g['kind']=='unmapped_rows' and g['sheet_index']==si for row in g['rows'])
        other_rows=[]
        if not profile_only:
            for r in range(start,sheet.nrows):
                if r+1 in used:continue
                cells=raw(sheet,r)
                if not cells:continue
                labels=' '.join(str(v) for v in sheet.row_values(r)[:3])
                role='total' if 'รวม' in labels or 'total' in labels.lower() else 'note'
                other_rows.append({'excel_row':r+1,'role':role,'cells':cells})
        sheets.append({"sheet_index": si, "name": sheet.name, "kind": kind, "layout_id": layout_id,
                       "layout": layout, "physical_rows": sheet.nrows, "data_rows": len(rows),
                       "metadata": {'headers':metadata_rows,'other_rows':other_rows}})
        if rows:
            groups.append({"sheet_index": si, "kind": kind, "columns": KINDS[kind], "rows": rows})
        wb.unload_sheet(si)
        del sheet
    for control in controls:
        key = control["key"]
        if control['count'] is not None and counts[key] != control["count"]:
            issue("SUMMARY_COUNT_MISMATCH", 'warning', sheet=control["sheet_index"], row=control["source_row"],
                  detail={"group": key, "expected": control["count"], "actual": counts[key]})
        if control["gross"] is not None and abs(sums[key]-Decimal(control["gross"])) > Decimal("0.01"):
            issue("SUMMARY_AMOUNT_MISMATCH", 'warning', sheet=control["sheet_index"], row=control["source_row"],
                  detail={"group": key, "expected": control["gross"], "actual": str(sums[key]),'basis':'gross_before_salary'})
    wb.release_resources()
    # Appeal workbooks also contain older REP rows as reference material. They
    # remain immutable history, but are not a second active report of that REP.
    summary_nos = {str(row[g['columns'].index('rep_no')]) for g in groups if g['kind']=='rep_summaries'
                   for row in g['rows'] if row[g['columns'].index('rep_no')]}
    if source=='REP':
        actual_counts=collections.Counter();actual_passed=collections.Counter();actual_sums=collections.defaultdict(Decimal)
        for g in groups:
            if g['kind']!='rep_claims':continue
            for row in g['rows']:
                rep=row[g['columns'].index('rep_no')]
                role='reported' if not summary_nos or rep in summary_nos else 'reference'
                row[g['columns'].index('record_role')]=role
                if role=='reported':
                    actual_counts[rep]+=1
                    if row[g['columns'].index('error_code')] in (None,'0'):
                        actual_passed[rep]+=1
                        basis='nhso_amount' if sheets[g['sheet_index']]['layout']['width']==114 else 'expected_amount'
                        actual_sums[rep]+=Decimal(row[g['columns'].index(basis)] or 0)
        for g in groups:
            if g['kind']!='rep_summaries':continue
            for row in g['rows']:
                rec=dict(zip(g['columns'],row));rep=rec['rep_no']
                # Some exports list only accepted claims. Count that basis
                # separately from all submitted claims and keep both summaries.
                valid_counts={v for v in (rec['passed_count'],rec['total_count']) if v is not None}
                if valid_counts and (actual_counts[rep] not in valid_counts or
                                     (rec['passed_count'] is not None and actual_passed[rep]!=rec['passed_count'])):
                    issue('REP_SUMMARY_COUNT_MISMATCH','warning',g['sheet_index'],rec['source_row'],
                          {'rep_no':rep,'expected_total':rec['total_count'],'expected_passed':rec['passed_count'],
                           'actual_total':actual_counts[rep],'actual_passed':actual_passed[rep]})
                # Appeal totals compare old/new rounds and use a separate basis.
                if file_category=='normal' and rec['compensation_amount'] is not None and abs(actual_sums[rep]-Decimal(rec['compensation_amount']))>Decimal('0.01'):
                    issue('REP_SUMMARY_AMOUNT_MISMATCH','warning',g['sheet_index'],rec['source_row'],
                          {'rep_no':rep,'expected':rec['compensation_amount'],'actual':str(actual_sums[rep]),'basis':'accepted_claims_same_payer_basis'})
    rep_nos = sorted(summary_nos or {str(row[g["columns"].index("rep_no")]) for g in groups if "rep_no" in g["columns"]
                      for row in g["rows"] if row[g["columns"].index("rep_no")]})
    if source == "REP":
        document_ref = ":".join([code, *rep_nos]) if rep_nos else path.stem
    logical_key = ":".join([source, hcode, pt, document_ref or path.stem])
    content = {"logical_key": logical_key, "statement_month": statement_month,
               "layouts": [{k:s[k] for k in ("sheet_index","name","layout_id")} for s in sheets], "groups": groups}
    fp = digest({'profile_file':path.name}) if profile_only else content_digest(content)
    expected = collections.Counter()
    for g in groups: expected[g["kind"]] += len(g["rows"])
    document = {"key": fp, "logical_key": logical_key, "document_ref": document_ref,
                "source": source, "hcode": hcode, "patient_type": pt, "payer_family": scheme,
                "reported_at": reported_at, "statement_month": statement_month,
                "expected_counts": dict(expected), "source_counts": dict(counts),
                "source_sums": {k:str(v) for k,v in sums.items()}}
    return {"document": document, "sheets": sheets, "groups": groups, "issues": issues}


ITEM_KINDS = {"rep_drug_items", "rep_instrument_items", "rep_denial_items", "rep_zero_pay_items"}


def validate_layout(kind, width, hdr):
    candidates=[r for r in REGISTRY['families'] if r['kind']==kind and width in r['widths']]
    return any(all(int(c)<len(hdr) and token in hdr[int(c)] for c,token in r['required_headers'].items()) for r in candidates)


def parse_claim(rec, v, sheet, row, datemode, source, hdr):
    def get(c): return v[c] if c is not None and c < len(v) else None
    def num(c): return cell_number(sheet,row,c)
    is_orf = source == "REP" and len(v) == 114
    rec.update({"rep_no": identifier(sheet,row,0), "source_seq": identifier(sheet,row,1), "tran_id": identifier(sheet,row,2),
                "hn": identifier(sheet,row,3), "an": None if is_orf else identifier(sheet,row,4),
                "pid": identifier(sheet,row,4 if is_orf else 5), "full_name": text(get(5 if is_orf else 6))})
    ac, dc = (7,8) if source == "STM" else (6,None) if is_orf else (8,9)
    rec["admitted_at"] = timestamp(get(ac), datemode, sheet.cell_type(row,ac))
    rec["discharged_at"] = timestamp(get(dc), datemode, sheet.cell_type(row,dc)) if dc is not None else None
    clinical = rec["discharged_at"] if rec["patient_type"] == "IP" else rec["admitted_at"]
    rec["service_date"] = clinical[:10] if clinical else None
    if source == "STM":
        rec["billed_amount"] = num(11)
        rec["compensation_amount"] = num(34 if rec["program"] == "STP" else 37)
        rec['deduction_amount']=num(19)
        # The statement's final compensation column already incorporates the
        # paid IP component after payroll deductions. Do not deduct it twice.
        rec['net_amount']=rec['compensation_amount']
        rec["seq_no"] = text(get(41)) if len(v)>41 else None
        rec["rw"] = num(13)
    elif len(v) in (58,59):
        charge=next((c for c,h in enumerate(hdr) if 'เรียกเก็บ' in h and 'ค่ารักษา' in h),None)
        rec["billed_amount"] = num(charge)
        rec["expected_amount"] = sum_present(num(10), num(11))
        rec["nhso_amount"] = num(11)  # Only PP received from NHSO, not employer compensation.
        rec["error_code"] = text(get(12));rec["rw"] = num(28)
    elif len(v) == 74:
        rec["billed_amount"] = num(35);rec["expected_amount"] = num(60)
        rec["error_code"] = text(get(61));rec["rw"] = num(30)
    elif is_orf:
        rec["billed_amount"] = num(21);rec["expected_amount"] = num(32)
        rec["nhso_amount"] = num(31);rec["error_code"] = text(get(101))
    else:
        # Old 120-column headers use one merged charge column; newer layouts
        # label charge components 1.1/1.2/1.3. Resolve the explicit total.
        total = next((c for c,h in enumerate(hdr) if '1.3' in h and 'เรียกเก็บ' in h), None)
        if total is None:
            total = next((c for c,h in enumerate(hdr) if re.search(r'\(1\)',h) and 'เรียกเก็บ' in h), None)
        if total is None: raise ValueError("MISSING_CHARGE_MAPPING")
        rec["billed_amount"] = num(total);rec["nhso_amount"] = num(10)
        rec["expected_amount"] = sum_present(num(10), num(11))
        rec["error_code"] = text(get(13));rec["rw"] = num(36)
    if source == "REP":
        seq = next((c for c,h in enumerate(hdr) if h.strip() == 'SEQ NO'),None)
        invoice = next((c for c,h in enumerate(hdr) if h.strip() == 'INVOICE NO'),None)
        rec["seq_no"] = text(get(seq));rec["invoice_no"] = text(get(invoice))


def parse_item(rec, v, kind, datemode, sheet, row, hdr):
    def get(c): return v[c] if c<len(v) else None
    def num(c): return cell_number(sheet,row,c)
    def ident(c):return identifier(sheet,row,c)
    if kind=='rep_instrument_items' and len(v)==14:
        rec.update(parent_seq=text(get(0)),tran_id=None,hn=ident(1),an=ident(2),
                   admitted_at=timestamp(get(3),datemode,sheet.cell_type(row,3)),pid=ident(4),full_name=text(get(5)),
                   item_seq=text(get(6)),item_code=ident(7),item_name=text(get(8)),quantity=num(9),
                   billed_amount=num(10),compensation_amount=num(12),error_code=text(get(13)))
        return
    extended = kind in ("rep_denial_items", "rep_zero_pay_items")
    rec.update({"parent_seq":text(get(0)),"tran_id":ident(1),"hn":ident(3 if extended else 2),
                "an":ident(4 if extended else 3),"pid":ident(6 if extended else 5),
                "full_name":text(get(7 if extended else 6))})
    dc = 5 if extended else 4
    rec["admitted_at"] = timestamp(get(dc),datemode,sheet.cell_type(row,dc))
    rec["item_seq"] = text(get(7)) if not extended else None
    if kind == "rep_drug_items":
        total=next((c for c,h in enumerate(hdr) if 'รวมชดเชย' in h),None)
        if total is None:raise ValueError('MISSING_DRUG_COMPENSATION_MAPPING')
        rec.update(item_code=ident(8),tmt_code=ident(9),item_name=text(get(10)),
                   quantity=num(15),unit_price=num(16),billed_amount=num(17),
                   compensation_amount=num(total), error_code=text(get(len(v)-1)))
    elif kind == "rep_instrument_items":
        rec.update(item_code=ident(8),item_name=text(get(9)),quantity=num(10),
                   billed_amount=num(11),compensation_amount=num(13),error_code=text(get(15)))
    elif kind == "rep_zero_pay_items":
        rec.update(item_code=ident(9),tmt_code=ident(10),
                   billed_amount=num(12),compensation_amount=num(13),error_code=text(get(15)))
    else:
        rec.update(item_code=ident(9),billed_amount=num(11),error_code=text(get(12)))


def parse_summary(rec, v, hdr, kind, sheet, row):
    def num(c):return cell_number(sheet,row,c)
    def count(c):return integer_count(num(c))
    rec["rep_no"] = text(v[2])
    if kind == "stm_rep_summaries":
        rec["category"] = "appeal" if "อุทธรณ์" in str(v[3]) else "normal"
        rec["passed_count"] = count(4);rec["billed_amount"] = num(5)
        total = next((c for c,h in enumerate(hdr) if 'พึงรับทั้งหมด' in h),None)
        rec["compensation_amount"] = num(total)
    else:
        normal_passed = next((c for c,h in enumerate(hdr) if 'ข้อมูลปกติ' in h and h.endswith('/ ผ่าน')),None)
        appeal_passed = next((c for c,h in enumerate(hdr) if 'ข้อมูลอุทธรณ์' in h and h.endswith('/ ผ่าน')),None)
        counts=[count(c) for c in (normal_passed,appeal_passed) if c is not None]
        rec['passed_count']=sum(x for x in counts if x is not None) if any(x is not None for x in counts) else None
        allcols=[c for c,h in enumerate(hdr) if 'จำนวนราย' in h and h.endswith('/ ทั้งหมด')]
        totals=[count(c) for c in allcols]
        rec['total_count']=sum(x for x in totals if x is not None) if any(x is not None for x in totals) else count(3)
        failedcols=[c for c,h in enumerate(hdr) if 'จำนวนราย' in h and h.endswith('/ ไม่ผ่าน')]
        failures=[count(c) for c in failedcols]
        rec['failed_count']=sum(x for x in failures if x is not None) if any(x is not None for x in failures) else None
        total = next((c for c,h in enumerate(hdr) if h.strip() == 'จ่ายชดเชยทั้งสิ้น'),None)
        if total is not None:
            employer=next((c for c,h in enumerate(hdr) if h.strip()=='จ่ายชดเชยต้นสังกัด'),None)
            rec['compensation_amount']=sum_present(num(total),num(employer))
        else:
            parts=[c for c,h in enumerate(hdr) if h.startswith('ชดเชยสุทธิ /') and ('ค่ารักษา' in h or 'PP' in h)]
            rec['compensation_amount']=sum_present(*(num(c) for c in parts))
