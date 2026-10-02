"""Bounded readiness and aggregate operational telemetry; never logs source data."""
import asyncio
import json
import logging
import shutil
import tempfile
import time
from collections import Counter
from threading import Lock

from repstm.db import Pgweb, REQUEST_DEADLINE

VERSION = '0.2.0-rc.1'
_counts = Counter()
_lock = Lock()


def event(code):
    with _lock:
        _counts[code] += 1
    logging.getLogger('stmrep.operations').warning(json.dumps({'event': code}))


def counters():
    with _lock:
        return dict(_counts)


def storage_check(path, minimum_free_bytes):
    try:
        path.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryFile(dir=path) as probe:
            probe.write(b'readiness'); probe.flush()
        if shutil.disk_usage(path).free < minimum_free_bytes:
            return 'STORAGE_LOW'
        return 'READY'
    except OSError:
        return 'STORAGE_UNAVAILABLE'


def database_check(url):
    token = REQUEST_DEADLINE.set(time.monotonic() + 4)
    try:
        db = Pgweb(url, timeout=2)
        result = db.query("SELECT to_regclass('followup.schema_versions') IS NOT NULL AND to_regclass('his.records') IS NOT NULL AND to_regclass('ingest.batches') IS NOT NULL AND to_regclass('analytics.case_financials') IS NOT NULL AND to_regprocedure('his.finalize_snapshot(uuid)') IS NOT NULL AND to_regprocedure('followup.take_job(uuid)') IS NOT NULL AS schema_ready", retry=False)
        return 'READY' if result['rows'][0][0] else 'SCHEMA_MISSING'
    except Exception:
        return 'DATABASE_UNAVAILABLE'
    finally:
        if 'db' in locals():db.session.close()
        REQUEST_DEADLINE.reset(token)


async def readiness(settings, worker, draining):
    checks = {'draining': 'DRAINING' if draining else 'READY'}
    checks['worker'] = ('READY' if worker.thread and worker.thread.is_alive() and not worker.stop.is_set()
                        else 'WORKER_UNAVAILABLE') if settings.mode == 'live' and settings.worker_enabled else 'DISABLED'
    async def inspect():
        checks['storage'] = await asyncio.to_thread(storage_check, settings.data_dir, settings.minimum_free_bytes)
        checks['database'] = await asyncio.to_thread(database_check, settings.pgweb_url) if settings.mode == 'live' else 'DEMO'
    try:
        await asyncio.wait_for(inspect(), timeout=5)
    except TimeoutError:
        checks['deadline'] = 'READINESS_TIMEOUT'
    ok = all(value in ('READY', 'DISABLED', 'DEMO') for value in checks.values())
    return {'status': 'ready' if ok else 'not_ready', 'checks': checks}, 200 if ok else 503
