"""Reuse the reviewed importer and durable receipts, with explicit job progress."""
from __future__ import annotations

import collections
from pathlib import Path
import sqlite3
import threading

from repstm.cli import State, Packer, archive, file_sha
from repstm.parser import parse_file, VERSION
from .db import literal, ident, json_sql


class Paused(RuntimeError):
    pass


def profile_file(path):
    parsed = parse_file(Path(path))
    # No cell payload or person data in progress/history responses.
    return {'fingerprint': parsed['document']['key'], 'mapping_version': VERSION,
            'rows': parsed['document']['expected_counts'], 'sheet_count': len(parsed['sheets']),
            'issues': dict(collections.Counter(x['code'] for x in parsed['issues'])),
            'errors': sum(x['severity'] == 'error' for x in parsed['issues']),
            'warnings': sum(x['severity'] == 'warning' for x in parsed['issues'])}


class JobPacker(Packer):
    def __init__(self, db, state, callback, check_pause, run_id):
        super().__init__(db, state, run_id=run_id)
        self.callback, self.check_pause = callback, check_pause

    def flush(self):
        if self.check_pause():
            # Persist before pause, even if it has never been sent.
            if any(self.payload[k] for k in self.payload if k != 'run_id'):
                self.state.queue(self.batch_id, self.payload)
            raise Paused('PAUSE_REQUESTED')
        before = self.batch_count
        super().flush()
        if self.batch_count != before:
            self.callback({'phase': 'importing', 'committed_batches': self.batch_count,
                           'inserted_records': self.total_rows})


def import_manifest(database, job, paths, state_path, archive_dir, callback, check_pause):
    state = State(state_path)
    transport = database.transport
    try:
        state.target(transport.identity())
        for batch_id, raw in state.pending().fetchall():
            if check_pause():
                raise Paused('PAUSE_REQUESTED')
            import json
            payload = json.loads(raw)
            result = transport.apply(batch_id, payload)
            state.acknowledge(batch_id, payload, result)
        state.seed_remote(transport)
        pack = JobPacker(transport, state, callback, check_pause, job['id'])
        database.execute(f"INSERT INTO ingest.runs(id,metadata) VALUES({ident(job['id'])},{json_sql({'source':'web','mapping_version':VERSION})}) ON CONFLICT DO NOTHING")
        processed = skipped = blocked = 0
        for entry in paths:
            path = Path(entry['storage_path'])
            sha = file_sha(path)
            if sha != entry['sha256']:
                raise ValueError('MANIFEST_HASH_CHANGED')
            if state.done(path, sha):
                skipped += 1
                continue
            arc = archive(path, sha, Path(archive_dir))
            parsed = parse_file(path, content_path=arc)
            if parsed['document']['key'] != entry['profile']['fingerprint']:
                raise ValueError('MAPPING_CHANGED_SINCE_INSPECTION')
            was_partial = state.db.execute("SELECT 1 FROM files WHERE path=? AND sha256=? AND status='parsed'", (str(path),sha)).fetchone()
            state.parsed(path, sha, parsed)
            key = parsed['document']['key']
            duplicate = state.ready_document(key)
            if was_partial and not duplicate:
                state.sync_checkpoint(transport, key)
            pack.add('documents', parsed['document'])
            pack.add('files', {'sha256':sha,'source_path':str(path.resolve()),'filename':path.name,
                              'byte_size':path.stat().st_size,'archive_path':arc,'document_key':key,
                              'reported_at':parsed['document']['reported_at']})
            if not duplicate:
                for sheet in parsed['sheets']:
                    pack.add('sheets',{**sheet,'document_key':key})
                for issue in parsed['issues']:
                    pack.add('issues',{**issue,'document_key':key})
                for group in parsed['groups']:
                    header = {k:v for k,v in group.items() if k!='rows'}
                    header['document_key']=key
                    last = state.checkpoint(key,group['sheet_index'],group['kind'])
                    index = group['columns'].index('source_row')
                    for row in group['rows']:
                        if row[index] > last:
                            pack.row(header,row)
            errors = sum(x['severity']=='error' for x in parsed['issues'])
            blocked += int(errors>0)
            pack.add('complete',key)
            pack.add('_done_files',{'path':str(path),'sha256':sha,'errors':errors})
            processed += 1
            callback({'phase':'importing','processed_files':processed,'skipped_files':skipped,
                      'total_files':len(paths),'inserted_records':pack.total_rows,'committed_batches':pack.batch_count})
            parsed = None
        pack.flush()
        database.execute(f"UPDATE ingest.runs SET status='complete',finished_at=now() WHERE id={ident(job['id'])}")
        return {'processed_files':processed,'skipped_files':skipped,'blocked_files':blocked,
                'inserted_records':pack.total_rows,'requests':transport.request_count}
    finally:
        state.db.close()
