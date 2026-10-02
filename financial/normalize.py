from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
import hashlib
from zoneinfo import ZoneInfo

from .db import canonical
from .domain import number, identifier

MONEY = {'qty', 'unitprice', 'sum_price', 'cost', 'income', 'uc_money', 'paid_money', 'remain_money',
         'discount_money', 'rw', 'adjrw', 'unitcost', 'fdh_act_amt'}
IDENTITY = {'hn', 'an', 'vn', 'cid', 'pid', 'icode', 'billcode', 'patient_hn', 'rep_eclaim_detail_tran_id'}
DATES = {'birthday', 'birthdate', 'regdate', 'dchdate', 'vstdate', 'begin_date', 'expire_date', 'send_date'}
TIMESTAMPS = {'last_update', 'last_modified', 'update_datetime', 'upload_datetime', 'rep_eclaim_import_datetime',
              'fdh_claim_status_datetime', 'auth_datetime'}
THAI = ZoneInfo('Asia/Bangkok')


def local_timestamp(value):
    if value in (None, ''):
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        dt = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    return (dt if dt.tzinfo else dt.replace(tzinfo=THAI)).isoformat()


def normalize(dataset, row):
    source_key = str(row.get('source_key') or '')
    if not source_key:
        raise ValueError('SOURCE_KEY_MISSING')
    payload = dict(row)
    issues = []
    for key, value in row.items():
        try:
            if key in IDENTITY:
                payload[key] = identifier(value)
            elif key in MONEY and not (key == 'income' and dataset == 'lines'):
                n = number(value)
                payload[key] = str(n) if n is not None else None
            elif key in DATES:
                payload[key] = date.fromisoformat(str(value)[:10]).isoformat() if value not in (None, '') else None
            elif key in TIMESTAMPS:
                payload[key] = local_timestamp(value)
        except (ValueError, TypeError):
            payload[key] = None
            issues.append({'code': 'SOURCE_VALUE_INVALID', 'field': key})
    for dest, date_key, time_key in ([('_admitted_at','regdate','regtime'),('_discharged_at','dchdate','dchtime')] if dataset == 'ip' else [('_admitted_at','vstdate','vsttime')] if dataset == 'op' else []):
        try:
            payload[dest] = local_timestamp(str(payload[date_key]) + 'T' + str(row.get(time_key) or '00:00:00')) if payload.get(date_key) else None
        except (ValueError, TypeError):
            payload[dest] = None
            issues.append({'code':'SOURCE_VALUE_INVALID','field':time_key})
    if issues:
        payload['_issues'] = issues
    return {'source_key': source_key, 'payload': payload,
            'record_hash': hashlib.sha256(canonical(payload).encode('utf-8')).hexdigest()}
