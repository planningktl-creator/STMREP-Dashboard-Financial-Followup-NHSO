"""Internal database gateway. No request accepts SQL from the browser."""
from __future__ import annotations

import base64
from datetime import date, datetime
from decimal import Decimal
import json
from pathlib import Path
import re
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
from inspect import signature

from repstm.db import Pgweb

_scope = ContextVar('stmrep_database_scope', default=None)


@contextmanager
def database_scope():
    if _scope.get() is not None:
        yield
        return
    connections = {}
    token = _scope.set(connections)
    try:
        yield
    finally:
        for db in connections.values():
            db.close()
        _scope.reset(token)


def database_request(function):
    @wraps(function)
    def scoped(*args, **kwargs):
        with database_scope():
            return function(*args, **kwargs)
    scoped.__signature__ = signature(function, eval_str=True)
    return scoped


def scoped_database(url):
    connections = _scope.get()
    if connections is None:
        return Database(url)
    if url not in connections:
        connections[url] = Database(url)
    return connections[url]


def encode_special(value):
    if isinstance(value, (Decimal, date, datetime, Path, uuid.UUID)):
        return str(value)
    raise TypeError('UNSUPPORTED_JSON_TYPE')


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'),
                      default=encode_special,
                      allow_nan=False)


def literal(value):
    if value is None:
        return 'NULL'
    # All untrusted strings become base64, never SQL escapes/interpolation.
    data = base64.b64encode(str(value).encode('utf-8')).decode('ascii')
    return f"convert_from(decode('{data}','base64'),'UTF8')"


def json_sql(value):
    return literal(canonical(value)) + '::jsonb'


def ident(value):
    return "'" + str(uuid.UUID(str(value))) + "'::uuid"


class Database:
    def __init__(self, url, priority='foreground'):
        if not url:
            raise RuntimeError('DATABASE_NOT_CONFIGURED')
        self.transport = Pgweb(url, timeout=90, priority=priority)

    def close(self):
        self.transport.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def rows(self, sql):
        data = self.transport.query(sql)
        columns = data.get('columns', [])
        return [dict(zip(columns, row)) for row in data.get('rows', [])]

    def scalar(self, sql):
        return self.transport.scalar(sql)

    def execute(self, sql):
        return self.transport.query(sql)

    def json(self, sql):
        value = self.scalar(sql)
        return json.loads(value) if isinstance(value, str) else value

    def report_json(self,sql):
        # SQL originates only from the repository, never an HTTP request field.
        return self.json(f'SELECT analytics.report_json({literal(sql)})')

    def migrate(self):
        sql = Path(__file__).with_name('schema.sql').read_text(encoding='utf-8')
        sql += '\n' + Path(__file__).with_name('finalize.sql').read_text(encoding='utf-8')
        sql += '\n' + Path(__file__).with_name('followup.sql').read_text(encoding='utf-8')
        sql += '\n' + Path(__file__).with_name('optimize.sql').read_text(encoding='utf-8')
        self.execute('DO $migration$ BEGIN\n' + sql + '\nEND $migration$;')

    def audit(self, actor, event, object_id=None, detail=None):
        self.execute(f"INSERT INTO followup.audit_events(actor_ref,event,object_id,detail) VALUES({literal(actor)},{literal(event)},{literal(object_id)},{json_sql(detail or {})})")

    def put_records(self, snapshot, dataset, rows, batch_id=None):
        batch = batch_id or str(uuid.uuid4())
        return self.json(f'SELECT his.apply_batch({ident(batch)},{ident(snapshot)},{literal(dataset)},{json_sql(rows)})')
