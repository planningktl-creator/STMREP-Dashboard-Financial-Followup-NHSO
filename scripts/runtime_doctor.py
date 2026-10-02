"""Read-only deployment check. No Session, SQL, upload, retries or response dumps."""
import argparse
import json
from pathlib import Path
import re
import time
from urllib.parse import urlsplit

import requests


def validate_origin(value):
    parsed = urlsplit(value)
    if (not parsed.hostname or parsed.username or parsed.password or parsed.query
            or parsed.fragment or parsed.path not in ('', '/')
            or parsed.scheme not in ('http', 'https')
            or parsed.scheme == 'http' and parsed.hostname not in ('localhost', '127.0.0.1', '::1')):
        raise ValueError('Use an HTTPS origin without credentials, path, query or fragment')
    return value.rstrip('/')


def inspect_runtime(origin, expected_revision=None, client=None):
    origin = validate_origin(origin)
    owned = client is None
    client = client or requests.Session()
    checks = []

    def probe(route):
        started = time.monotonic()
        record = {'route': route}
        data = None
        response = None
        try:
            response = client.get(origin+route, timeout=(3, 5), allow_redirects=False, stream=True)
            record['http'] = response.status_code
            # Never include arbitrary bodies, redirect locations or headers.
            kind = response.headers.get('Content-Type', '').split(';', 1)[0].lower()
            if response.status_code == 404:
                record['code'] = 'API_ROUTE_NOT_FOUND'
            elif response.is_redirect:
                record['code'] = 'API_REDIRECTED'
            elif kind == 'text/event-stream':
                record['code'] = 'INVALID_API_RESPONSE'  # Do not wait for an endless stream.
            else:
                body = bytearray()
                deadline = time.monotonic()+5
                for chunk in response.iter_content(chunk_size=1):
                    if time.monotonic() >= deadline: raise requests.Timeout()
                    body.extend(chunk)
                    if len(body) > 65536: break
                    if kind == 'text/html' and b'</title>' in body: break
                if not re.fullmatch(r'application/(?:[\w.+-]+\+)?json', kind):
                    if b'<title>Waking Up App' in body:
                        record['code'] = 'PLATFORM_WAKING'
                    elif b'<title>App Starting' in body:
                        record['code'] = 'PLATFORM_STARTING'
                    else:
                        record['code'] = 'INVALID_API_RESPONSE'
                    return record, None
                try:
                    if len(body) > 65536: raise ValueError()
                    data = json.loads(body)
                    if not isinstance(data, dict): raise ValueError()
                    record['code'] = 'JSON'
                except ValueError:
                    record['code'] = 'INVALID_API_RESPONSE'
        except requests.Timeout:
            record['code'] = 'API_TIMEOUT'
        except requests.RequestException:
            record['code'] = 'NETWORK_UNAVAILABLE'
        finally:
            if response is not None: response.close()
            record['seconds'] = round(time.monotonic()-started, 3)
            checks.append(record)
        return record, data

    try:
        health, data = probe('/api/health')
        if data is not None:
            valid = (health['http'] == 200 and data.get('status') == 'ok'
                     and data.get('hospital') == '10929' and data.get('mode') == 'live'
                     and isinstance(data.get('version'), str)
                     and re.fullmatch(r'[0-9A-Za-z.+-]{1,40}', data['version']))
            health['code'] = 'READY' if valid else 'WRONG_APPLICATION_OR_MODE'
            revision = data.get('build_revision', '')
            if valid:
                health['version'] = data['version']
                health['build_revision'] = revision if isinstance(revision,str) and re.fullmatch(r'[a-f0-9]{40}|[a-f0-9]{64}', revision) else 'unknown'
                if expected_revision and revision != expected_revision:
                    health['code'] = 'REVISION_MISMATCH'
        # Avoid further calls to an unverified backend (and auto-wake gateways).
        if health['code'] == 'READY':
            ready, data = probe('/api/health/ready')
            if data is not None:
                allowed = {'READY','DISABLED','DEMO','DRAINING','WORKER_UNAVAILABLE',
                    'STORAGE_LOW','STORAGE_UNAVAILABLE','DATABASE_UNAVAILABLE','SCHEMA_MISSING','READINESS_TIMEOUT'}
                components = data.get('checks', {})
                if not isinstance(components, dict): components = {}
                ready['components'] = {key: value if isinstance(value,str) and value in allowed else 'INVALID_STATUS'
                    for key,value in components.items() if key in ('database','storage','temporary','worker','draining','deadline')}
                required = ('database','storage','temporary','worker','draining')
                ok = (ready['http'] == 200 and data.get('status') == 'ready'
                      and all(ready['components'].get(key) == 'READY' for key in required)
                      and all(v == 'READY' for v in ready['components'].values()))
                ready['code'] = 'READY' if ok else 'NOT_READY'
        return {'status':'ready' if len(checks)==2 and all(c['code']=='READY' for c in checks) else 'blocked',
                'checks':checks,'scope':'api_identity_and_readiness_only',
                'requires_platform_verification':['persistent_volume','service_port','auto_sleep_disabled']}
    finally:
        if owned: client.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', required=True, help='HTTPS origin (no credentials)')
    parser.add_argument('--expected-revision')
    parser.add_argument('--output', type=Path, help='Save sanitized JSON evidence')
    args = parser.parse_args()
    if args.expected_revision and not re.fullmatch(r'[a-f0-9]{40}|[a-f0-9]{64}',args.expected_revision):
        parser.error('Expected revision must be a complete Git SHA')
    try: result = inspect_runtime(args.url, args.expected_revision)
    except ValueError: parser.error('Invalid origin; use HTTPS without credentials, path, query or fragment')
    encoded = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded+'\n', encoding='utf-8')
    print(encoded)
    raise SystemExit(0 if result['status']=='ready' else 1)


if __name__ == '__main__': main()
