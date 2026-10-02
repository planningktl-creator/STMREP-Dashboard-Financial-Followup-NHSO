from __future__ import annotations

from dataclasses import dataclass
import hashlib
import ipaddress
import json
import secrets
import threading
import time
from urllib.parse import urlparse

import httpx

from .queries import REGISTRY


class BmsError(RuntimeError):
    def __init__(self, code, status=502):
        super().__init__(code)
        self.code, self.status = code, status


@dataclass
class Session:
    cookie: str
    actor: str
    api_url: str
    bearer: str
    marketplace: str | None
    hospital: str
    expires_at: float
    csrf: str
    demo: bool = False


class Sessions:
    def __init__(self, settings, client=None):
        self.settings = settings
        self.client = client or httpx.Client(timeout=httpx.Timeout(60, connect=15), follow_redirects=False)
        self.active: dict[str, Session] = {}
        self.lock = threading.RLock()
        self.query_lock = threading.Lock()

    def _decode(self, response):
        if len(response.content) > 20 * 1024 * 1024:
            raise BmsError('BMS_RESPONSE_TOO_LARGE')
        # The installed BMS adapter uses 500/501 for an invalid Session too.
        if response.status_code in (401, 403, 500, 501):
            raise BmsError('BMS_SESSION_EXPIRED', 401)
        if response.status_code == 409:
            raise BmsError('BMS_QUERY_REJECTED')
        if response.status_code >= 400:
            raise BmsError('BMS_UNAVAILABLE')
        for encoding in ('utf-8-sig', 'cp874'):
            try:
                value = json.loads(response.content.decode(encoding))
                if isinstance(value, dict):
                    return value
            except (UnicodeError, ValueError):
                continue
        raise BmsError('BMS_INVALID_RESPONSE')

    def _target(self, url):
        parsed = urlparse(url)
        if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise BmsError('BMS_TARGET_REJECTED', 403)
        host = parsed.hostname.lower()
        # Exact or subdomain entries are explicit operator configuration.
        allowed = any(host == x or (x.startswith('*.') and host.endswith(x[1:])) for x in self.settings.bms_hosts)
        if not allowed:
            raise BmsError('BMS_TARGET_NOT_ALLOWLISTED', 403)
        return url.rstrip('/')

    def connect(self, code, marketplace=None):
        if self.settings.mode == 'demo':
            raise BmsError('LIVE_SESSION_DISABLED_IN_DEMO', 400)
        if not 1 <= len(code) <= 512 or any(ord(c) < 32 for c in code):
            raise BmsError('BMS_SESSION_INVALID', 400)
        try:
            payload = self._decode(self.client.get(self.settings.paste_url, params={'Action': 'GET', 'code': code}))
        except httpx.HTTPError:
            raise BmsError('BMS_UNAVAILABLE') from None
        if str(payload.get('MessageCode', 0)) not in ('0', '200'):
            raise BmsError('BMS_SESSION_INVALID', 401)
        result = payload.get('result') or {}
        user = result.get('user_info') or {}
        hospital = str(user.get('hospital_code') or '').strip()
        if hospital != self.settings.hospital:
            raise BmsError('HOSPITAL_MISMATCH', 403)
        bearer = str(user.get('bms_session_code') or result.get('key_value') or '').strip()
        if not bearer:
            raise BmsError('BMS_SESSION_INVALID', 401)
        target = self._target(str(user.get('bms_url') or ''))
        ttl = result.get('expired_second')
        ttl = min(int(ttl), 8 * 3600) if isinstance(ttl, (float, int)) else 900
        if ttl <= 0:
            raise BmsError('BMS_SESSION_EXPIRED', 401)
        session = Session(secrets.token_urlsafe(32), 'bms:' + hashlib.sha256(code.encode()).hexdigest(), target,
                          bearer, marketplace, hospital, time.time() + ttl, secrets.token_urlsafe(24))
        version = self.query(session, 'database', {})
        if not version or 'postgresql' not in str(version[0].get('version', '')).lower():
            raise BmsError('BMS_POSTGRESQL_REQUIRED', 400)
        with self.lock:
            self.active[session.cookie] = session
        return session

    def demo_session(self):
        if self.settings.mode != 'demo':
            raise BmsError('DEMO_DISABLED', 404)
        session = Session(secrets.token_urlsafe(32), 'demo:synthetic', '', '', None, self.settings.hospital,
                          time.time() + 3600, secrets.token_urlsafe(24), True)
        with self.lock:
            self.active[session.cookie] = session
        return session

    def get(self, cookie):
        with self.lock:
            session = self.active.get(cookie or '')
            if not session or session.expires_at <= time.time():
                self.active.pop(cookie or '', None)
                raise BmsError('BMS_SESSION_REQUIRED', 401)
            return session

    def find_actor(self, actor):
        with self.lock:
            return next((s for s in self.active.values() if s.actor == actor and s.expires_at > time.time()), None)

    def remove(self, cookie):
        with self.lock:
            self.active.pop(cookie or '', None)

    def query(self, session, name, params):
        if session.demo or session.expires_at <= time.time():
            raise BmsError('BMS_SESSION_EXPIRED', 401)
        definition = REGISTRY.get(name)
        if not definition:
            raise BmsError('QUERY_NOT_REGISTERED', 400)
        if set(params) != set(definition['params']):
            raise BmsError('QUERY_PARAMETERS_INVALID', 400)
        typed = {k: {'value': v, 'value_type': definition['params'][k]} for k, v in params.items()}
        body = {'app': 'STMREP-Dashboard-Financial-Followup-NHSO', 'sql': definition['sql'], 'params': typed}
        if session.marketplace:
            body['marketplace-token'] = session.marketplace
        try:
            with self.query_lock:
                for attempt in range(4):
                    try:
                        with self.client.stream('POST', session.api_url + '/api/sql', json=body,
                                                headers={'Authorization': 'Bearer ' + session.bearer}) as response:
                            content = bytearray()
                            for chunk in response.iter_bytes():
                                content.extend(chunk)
                                if len(content) > 20 * 1024 * 1024:
                                    raise BmsError('BMS_RESPONSE_TOO_LARGE')
                            payload = self._decode(httpx.Response(response.status_code, content=bytes(content)))
                        break
                    except (httpx.HTTPError, BmsError) as exc:
                        if isinstance(exc,BmsError) and exc.status==401:
                            session.expires_at=min(session.expires_at,time.time()-1)
                        transient=isinstance(exc,httpx.HTTPError) or exc.code=='BMS_UNAVAILABLE'
                        if not transient or attempt==3:
                            raise
                        time.sleep(2**attempt)
        except httpx.HTTPError:
            raise BmsError('BMS_UNAVAILABLE') from None
        if str(payload.get('MessageCode', 0)) not in ('0', '200'):
            if str(payload.get('MessageCode')) in ('401','403','500','501'):
                session.expires_at=min(session.expires_at,time.time()-1)
                raise BmsError('BMS_SESSION_EXPIRED',401)
            raise BmsError('BMS_QUERY_REJECTED')
        rows = payload.get('data')
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise BmsError('BMS_ROW_SHAPE_INVALID')
        if payload.get('record_count') is not None and int(payload['record_count']) != len(rows):
            raise BmsError('BMS_ROW_COUNT_MISMATCH')
        return rows
