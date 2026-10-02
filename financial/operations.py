"""Bounded readiness and aggregate operational telemetry; never logs source data."""
import asyncio
import json
import logging
import shutil
import tempfile
import time
import os
from pathlib import Path
from collections import Counter
from threading import Lock

from repstm.db import Pgweb, REQUEST_DEADLINE

VERSION = '0.2.0-rc.3'
BUILD_REVISION = os.getenv('BUILD_REVISION','unknown')
if BUILD_REVISION == 'unknown':
    try:BUILD_REVISION=(Path(__file__).resolve().parents[1]/'build-revision').read_text().strip()
    except OSError:pass
_counts = Counter()
_lock = Lock()
_loop_stats={'samples':0,'max_delay_seconds':0.0}


async def monitor_loop():
    while True:
        before=time.monotonic()
        await asyncio.sleep(.5)
        with _lock:
            _loop_stats['samples']+=1
            _loop_stats['max_delay_seconds']=max(_loop_stats['max_delay_seconds'],max(0,time.monotonic()-before-.5))


def resource_metrics():
    def value(name):
        try:return int((Path('/sys/fs/cgroup')/name).read_text().strip())
        except (OSError,ValueError):return None
    with _lock:loop=dict(_loop_stats)
    return {'process_cpu_seconds':time.process_time(),'memory_bytes':value('memory.current'),
            'peak_memory_bytes':value('memory.peak'),'memory_limit_bytes':value('memory.max'),'event_loop':loop}


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
        result = db.query("SELECT to_regclass('followup.schema_versions') IS NOT NULL AND to_regclass('his.records') IS NOT NULL AND to_regclass('ingest.batches') IS NOT NULL AND to_regclass('analytics.case_financials') IS NOT NULL AND to_regprocedure('his.finalize_snapshot(uuid)') IS NOT NULL AND to_regprocedure('followup.take_job(uuid)') IS NOT NULL AND to_regprocedure('his.refresh_links(integer)') IS NOT NULL AND to_regprocedure('analytics.refresh_status(text)') IS NOT NULL AND to_regprocedure('analytics.report_json(text)') IS NOT NULL AS schema_ready", retry=False)
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
        checks['temporary'] = await asyncio.to_thread(storage_check, Path(tempfile.gettempdir()), settings.minimum_free_bytes)
        checks['database'] = await asyncio.to_thread(database_check, settings.pgweb_url) if settings.mode == 'live' else 'DEMO'
    try:
        await asyncio.wait_for(inspect(), timeout=5)
    except TimeoutError:
        checks['deadline'] = 'READINESS_TIMEOUT'
    ok = all(value in ('READY', 'DISABLED', 'DEMO') for value in checks.values())
    return {'status': 'ready' if ok else 'not_ready', 'checks': checks}, 200 if ok else 503
