import json
import requests
import pytest

from scripts.runtime_doctor import inspect_runtime, validate_origin


class Gateway:
    def __init__(self, health, ready=None):
        self.health, self.ready = health, ready
        self.paths = []

    def get(self, url, **options):
        assert options['allow_redirects'] is False
        self.paths.append(url)
        response = requests.Response()
        value = self.ready if url.endswith('/ready') else self.health
        response.status_code, kind, body = value
        response.headers['Content-Type'] = kind
        response._content = body.encode()
        response._content_consumed = True
        return response


def test_waking_page_is_failure_even_with_http_200():
    gateway = Gateway((200, 'text/html', '<title>Waking Up App...</title>'))
    result = inspect_runtime('https://fixture.example.invalid', client=gateway)
    assert result['status'] == 'blocked'
    assert result['checks'][0]['code'] == 'PLATFORM_WAKING'
    assert len(gateway.paths) == 1  # No DB/readiness calls without our API.


def test_platform_starting_interstitial_is_not_app_readiness():
    html='<title>App Starting — stm-rep-v2</title> Application is starting'
    result=inspect_runtime('https://fixture.example.invalid', client=Gateway((200,'text/html',html)))
    assert result['checks'][0]['code']=='PLATFORM_STARTING'


def test_missing_api_route_does_not_expose_response():
    result = inspect_runtime('https://fixture.example.invalid', client=Gateway(
        (404, 'application/json', '{"detail":"SECRET_RESPONSE"}')))
    assert result['checks'][0]['code'] == 'API_ROUTE_NOT_FOUND'
    assert 'SECRET_RESPONSE' not in json.dumps(result)


def test_stream_is_rejected_without_reading_it():
    gateway = Gateway((200, 'text/event-stream', 'data: keepalive\n\n'))
    result = inspect_runtime('https://fixture.example.invalid', client=gateway)
    assert result['checks'][0]['code'] == 'INVALID_API_RESPONSE'


def test_schema_missing_and_revision_mismatch():
    health = (200, 'application/json', json.dumps({'status':'ok','hospital':'10929',
        'version':'0.2.0-rc.3','mode':'live','build_revision':'a'*40}))
    ready = (503, 'application/json', json.dumps({'status':'not_ready',
        'checks':{'database':'SCHEMA_MISSING','worker':'READY'}}))
    result = inspect_runtime('https://fixture.example.invalid', client=Gateway(health,ready))
    assert result['status'] == 'blocked'
    assert result['checks'][-1]['components']['database'] == 'SCHEMA_MISSING'
    result = inspect_runtime('https://fixture.example.invalid', expected_revision='b'*40,
                             client=Gateway(health,ready))
    assert result['checks'][0]['code'] == 'REVISION_MISMATCH'


def test_ready_requires_live_identity_and_valid_components():
    health = (200, 'application/json', json.dumps({'status':'ok','hospital':'10929',
        'version':'0.2.0-rc.3','mode':'live','build_revision':'a'*40}))
    ready = (200, 'application/json', json.dumps({'status':'ready','checks':{
        'database':'READY','storage':'READY','temporary':'READY','worker':'READY','draining':'READY'}}))
    assert inspect_runtime('https://fixture.example.invalid', client=Gateway(health,ready))['status']=='ready'
    bad = (200, 'application/json', '{"status":"ready","checks":{}}')
    assert inspect_runtime('https://fixture.example.invalid', client=Gateway(health,bad))['status']=='blocked'


@pytest.mark.parametrize('origin', ['https://user:secret@example.invalid',
    'https://example.invalid/?token=secret','https://example.invalid/#secret','http://example.invalid'])
def test_origin_refuses_credentials_and_nonlocal_http(origin):
    with pytest.raises(ValueError): validate_origin(origin)
