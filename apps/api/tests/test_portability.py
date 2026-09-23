"""Protocol fixtures stay in tests; workload tests send actual loopback requests."""

import asyncio
import importlib.util
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from rook_backend.api.app import create_app
from rook_backend.config import Settings
from rook_backend.telemetry import Prometheus, queries
from rook_backend.telemetry_profiles import PROFILES
from rook_backend.worker import WorkerSettings, run_worker
from .test_incidents import SQLiteStore
from .test_telemetry import responses

ROUTES = {'portable-http': {'profile': 'local-http', 'url': 'http://second.test:9090'}}


def install_transport(monkeypatch, case='measured'):
    monkeypatch.setattr('rook_backend.telemetry.time.time', lambda: 1000.0)
    payloads = responses()
    for key in ('counter_sources', 'bucket_sources'):
        for row in payloads[key]['data']['result']:
            row['metric']['code'] = row['metric'].pop('http_response_status_code')
    if case == 'missing':
        payloads['counter_sources']['data']['result'].pop()
        payloads['error_ratio']['data']['result'] = []
    elif case == 'stale':
        payloads['counter_sources']['data']['result'][0]['values'] = [[750, '10'], [800, '20']]
    elif case == 'unsupported':
        payloads['bucket_sources']['data']['result'] = []
        payloads['p95_latency']['data']['result'] = []
    plan = PROFILES['local-http'].queries('portable-http', 'opentelemetry-demo')
    seen, clients = [], []
    async def handler(request):
        seen.append(request)
        if case == 'unavailable':
            raise httpx.ConnectError('private details')
        name = next(key for key, value in plan.items() if value == request.url.params['query'])
        return httpx.Response(200, json=payloads[name])
    real_client = httpx.AsyncClient
    def client(**kwargs):
        result = real_client(transport=httpx.MockTransport(handler), **kwargs)
        clients.append(result)
        return result
    monkeypatch.setattr('rook_backend.telemetry.httpx.AsyncClient', client)
    return seen, clients


def test_demo_query_compatibility():
    count = 'http_server_request_duration_seconds_count{service_name="frontend",service_namespace="opentelemetry-demo"}'
    bucket = 'http_server_request_duration_seconds_bucket{service_name="frontend",service_namespace="opentelemetry-demo"}'
    error = 'http_server_request_duration_seconds_count{service_name="frontend",service_namespace="opentelemetry-demo",http_response_status_code=~"5.."}'
    rate = f'sum(rate({count}[5m]))'
    assert queries('frontend', 'opentelemetry-demo') == {
        'request_rate': rate, 'p95_latency': f'histogram_quantile(0.95, sum by (le)(rate({bucket}[5m])))',
        'error_ratio': f'sum(rate({error}[5m])) / {rate}',
        'counter_sources': f'{count}[5m]', 'bucket_sources': f'{bucket}[5m]',
    }


@pytest.mark.parametrize('routes', [
    {'bad{': {'profile': 'local-http', 'url': 'http://valid.test'}},
    {'valid': {'profile': 'unknown', 'url': 'http://valid.test'}},
    {'valid': {'profile': 'local-http', 'url': 'file:///private'}},
    {'valid': {'profile': 'local-http', 'url': 'http://valid.test', 'query': 'arbitrary'}},
])
def test_invalid_source_configuration(routes):
    with pytest.raises(ValidationError):
        Settings(telemetry_sources=routes)


def test_source_configuration_from_environment(monkeypatch):
    monkeypatch.setenv('ROOK_TELEMETRY_SOURCES', '{"portable-http":{"profile":"local-http","url":"http://second.test"}}')
    assert Settings().telemetry_sources['portable-http'].profile == 'local-http'
    assert WorkerSettings().telemetry_sources['portable-http'].profile == 'local-http'


@pytest.mark.parametrize('case', ['measured', 'missing', 'stale', 'unsupported', 'unavailable'])
def test_second_source_normalization_and_cleanup(monkeypatch, case):
    seen, clients = install_transport(monkeypatch, case)
    app = create_app(Settings(prometheus_url=None, telemetry_sources=ROUTES))
    with TestClient(app) as client:
        response = client.get('/services/portable-http/metrics')
        assert client.get('/health/live').status_code == 200
        # No default URL: unknown services do not silently query the second source.
        assert client.get('/services/unknown/metrics').status_code == 503
    assert all(client.is_closed for client in clients)
    assert all(request.url.host == 'second.test' for request in seen)
    assert {request.url.params['time'] for request in seen} == {'1000.0'}
    assert 'private details' not in response.text
    if case == 'unavailable':
        assert response.status_code == 503
        assert response.json() == {'status': 'unavailable'}
        return
    assert response.status_code == 200
    assert len(seen) == 5
    metrics = response.json()['metrics']
    key = 'p95_latency' if case == 'unsupported' else 'error_ratio'
    if case == 'measured':
        assert metrics['request_rate']['value'] == 2
        assert metrics['p95_latency']['value'] == 0.1
        assert metrics[key]['value'] == 0.2
        assert metrics[key]['status'] == 'measured'
    else:
        assert metrics[key]['value'] is None
        assert metrics[key]['status'] == ('stale' if case == 'stale' else 'insufficient_data')


def test_default_and_override_routing(monkeypatch):
    seen = []
    async def handler(request):
        seen.append(request)
        kind = 'matrix' if request.url.params['query'].endswith('[5m]') else 'vector'
        return httpx.Response(200, json={'status': 'success', 'data': {'resultType': kind, 'result': []}})
    real_client = httpx.AsyncClient
    monkeypatch.setattr('rook_backend.telemetry.httpx.AsyncClient', lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw))
    async def check():
        source = Prometheus(Settings(prometheus_url='http://demo.test', telemetry_sources=ROUTES))
        try:
            await source.metrics('frontend')
            await source.metrics('portable-http')
            assert {r.url.host for r in seen[:5]} == {'demo.test'}
            assert {r.url.host for r in seen[5:]} == {'second.test'}
            assert 'http_server_request_duration_seconds_count' in seen[0].url.params['query']
            assert 'local_http_requests_total' in seen[5].url.params['query']
        finally:
            await source.close()
    asyncio.run(check())


@pytest.mark.parametrize('case', ['measured', 'missing', 'stale', 'unavailable'])
def test_worker_uses_normalized_second_source_and_deduplicates(monkeypatch, case):
    install_transport(monkeypatch, case)
    async def check():
        store = SQLiteStore()
        database = MagicMock()
        database.close = AsyncMock()
        @asynccontextmanager
        async def lock(db):
            yield True
        sweeps = []
        async def wait(stop, seconds):
            sweeps.append(seconds)
            if len(sweeps) == 2:
                stop.set()
        monkeypatch.setattr('rook_backend.worker.Database', lambda s: database)
        monkeypatch.setattr('rook_backend.worker.PostgresIncidentStore', lambda db: store)
        monkeypatch.setattr('rook_backend.worker.ownership', lock)
        monkeypatch.setattr('rook_backend.worker.wait_interval', wait)
        try:
            await run_worker(WorkerSettings(telemetry_sources=ROUTES, prometheus_url=None,
                worker_services=('portable-http',), worker_p95_seconds=None), asyncio.Event())
            rows = await store.list()
            assert len(rows) == (1 if case == 'measured' else 0)
            if rows:
                assert rows[0].service_name == 'portable-http'
                assert 'local_http_requests_total' in rows[0].evidence_query
                assert 'code=~"5.."' in rows[0].evidence_query
            assert len(sweeps) == 2
        finally:
            store.engine.dispose()
    asyncio.run(check())


def test_real_workload_requests_failure_and_recovery():
    path = Path(__file__).resolve().parents[3] / 'deploy/local/portable-http/server.py'
    spec = importlib.util.spec_from_file_location('test_workload', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    server = module.Workload(('127.0.0.1', 0))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with httpx.Client(base_url=f'http://127.0.0.1:{server.server_port}', trust_env=False) as client:
            assert 'code=' not in client.get('/metrics').text
            assert client.get('/work').status_code == 200
            assert client.post('/failure/on').status_code == 200
            assert 'code="503"' not in client.get('/metrics').text
            assert client.get('/work').status_code == 503
            assert client.get('/work').status_code == 503
            assert client.post('/failure/off').status_code == 200
            assert client.get('/work').status_code == 200
            exposition = client.get('/metrics').text
            for code in (200, 503):
                labels = f'app="portable-http",namespace="opentelemetry-demo",code="{code}"'
                assert f'local_http_requests_total{{{labels}}} 2\n' in exposition
                assert f'local_http_request_duration_seconds_bucket{{{labels},le="+Inf"}} 2\n' in exposition
                assert f'local_http_request_duration_seconds_count{{{labels}}} 2\n' in exposition
                count, elapsed, buckets = server.samples[code]
                assert count == 2 and elapsed > 0 and buckets == sorted(buckets)
            assert client.get('/metrics').text == exposition  # Scrapes don't count as work.
            with server.lock:
                server.failure_until = 0  # Test-only expiry; production uses monotonic time.
            assert client.get('/work').status_code == 200
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
