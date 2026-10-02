"""pgweb transport; SQL literals contain only validated UUIDs/base64."""
from __future__ import annotations

import base64
import json
import os
import time
import logging
import threading
from collections import Counter
from contextvars import ContextVar
from urllib.parse import urlencode

import requests

from .parser import canonical

MAX_BODY = 256 * 1024
REQUEST_DEADLINE = ContextVar('pgweb_request_deadline', default=None)
_gateway_counts = Counter()
_gateway_lock = threading.Lock()


def gateway_counters():
    with _gateway_lock:return dict(_gateway_counts)


def gateway_event(code):
    with _gateway_lock:_gateway_counts[code]+=1
    logging.getLogger('stmrep.gateway').warning(json.dumps({'event':code}))


def batch_sql(batch_id, payload):
    import uuid
    ident = str(uuid.UUID(str(batch_id)))
    encoded = base64.b64encode(canonical(payload).encode("utf-8")).decode("ascii")
    return f"SELECT ingest.apply_batch('{ident}'::uuid,convert_from(decode('{encoded}','base64'),'UTF8')::jsonb) AS result"


def body_size(batch_id, payload):
    return len(urlencode({"query":batch_sql(batch_id,payload)}).encode("ascii"))


class Pgweb:
    def __init__(self, url, timeout=330, session=None):
        self.url = url.rstrip("/") + "/api/query"
        self.timeout = timeout
        self.session = session or requests.Session()
        self.request_count = 0
        self.request_seconds = 0.0
        self.min_interval = float(os.getenv('PGWEB_MIN_INTERVAL','0.25'))
        self.last_request = 0.0

    def query(self, sql, retry=True):
        for attempt in range(6 if retry else 1):
            deadline=REQUEST_DEADLINE.get()
            remaining=deadline-time.monotonic() if deadline is not None else None
            if remaining is not None and remaining<=0:
                raise RuntimeError('REPORT_TIMEOUT')
            delay=self.min_interval-(time.monotonic()-self.last_request)
            if remaining is not None and delay>=remaining:raise RuntimeError('REPORT_TIMEOUT')
            if delay>0:time.sleep(delay)
            started = time.monotonic()
            self.last_request=started
            self.request_count += 1
            try:
                remaining=deadline-time.monotonic() if deadline is not None else None
                if remaining is not None and remaining<=0:raise RuntimeError('REPORT_TIMEOUT')
                timeout=(min(15,remaining/2),min(self.timeout,remaining/2)) if remaining is not None else (15,self.timeout)
                response = self.session.post(self.url, data={"query":sql},timeout=timeout)
                self.request_seconds += time.monotonic()-started
                if response.status_code in (429,502,503,504):
                    gateway_event('GATEWAY_TRANSIENT_ERROR')
                    raise requests.ConnectionError(f"Temporary gateway HTTP {response.status_code}")
                if response.status_code == 413:
                    raise RuntimeError("PAYLOAD_TOO_LARGE: reduce --batch-bytes")
                try:data = response.json()
                except ValueError:
                    response.raise_for_status()
                    raise RuntimeError('Invalid JSON response from pgweb') from None
                if data.get("error"):
                    # Do not echo SQL/payload (may contain patient information).
                    message = str(data["error"])
                    if 'deadlock detected' in message or 'could not serialize access' in message:
                        # PostgreSQL has rolled back this atomic request.
                        raise requests.ConnectionError('Retryable transaction conflict')
                    raise RuntimeError(message[:1200])
                response.raise_for_status()
                return data
            except (requests.Timeout, requests.ConnectionError) as exc:
                gateway_event('GATEWAY_RETRY' if retry and attempt<5 else 'GATEWAY_UNAVAILABLE')
                self.session.close() if hasattr(self.session,'close') else None
                if not retry or attempt == 5:
                    raise RuntimeError(f"PGWEB_UNAVAILABLE ({type(exc).__name__}: {str(exc)[:150]}): pending batches retained for resume") from None
                delay=min(2**attempt,15)
                if deadline is not None and time.monotonic()+delay>=deadline:raise RuntimeError('REPORT_TIMEOUT') from None
                time.sleep(delay)

    def scalar(self, sql):
        data=self.query(sql)
        value=data["rows"][0][0]
        return json.loads(value) if isinstance(value,str) and value[:1] in ("{","[") else value

    def apply(self, batch_id, payload):
        if body_size(batch_id,payload)>MAX_BODY:
            raise ValueError("Encoded batch exceeds 256 KiB")
        return self.scalar(batch_sql(batch_id,payload))

    def identity(self):
        return self.scalar("SELECT current_database()||':'||(SELECT installed_at::text FROM ingest.schema_versions WHERE version='1.0.0')")

    def refresh(self, progress=None):
        total=0
        while True:
            n=self.scalar("SELECT reporting.refresh_claims(2000)")
            total+=n
            if not n:break
            if progress:progress({"phase":"reconcile","claims":total})
        rows=self.query("SELECT basis,month::text FROM reporting.dirty_months ORDER BY basis,month")["rows"]
        for basis,month in rows:
            if basis not in ("service","statement") or len(month)!=10:raise ValueError("Invalid reporting bucket")
            self.query(f"SELECT reporting.refresh_month('{basis}','{month}'::date)")
            if progress:progress({"phase":"aggregate","basis":basis,"month":month})
