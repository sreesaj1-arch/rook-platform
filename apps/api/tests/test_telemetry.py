import asyncio
from copy import deepcopy

import httpx
import pytest
from fastapi.testclient import TestClient

from rook_backend.api.app import create_app
from rook_backend.config import Settings
from rook_backend.telemetry import queries


def responses() -> dict:
    """Synthetic protocol fixtures only; never imported by application code."""
    def vector(value: str) -> dict:
        return {"status": "success", "data": {"resultType": "vector", "result": [
            {"metric": {}, "value": [1000, value]}]}}

    def matrix(bucket: bool = False) -> dict:
        return {"status": "success", "data": {"resultType": "matrix", "result": [
            {"metric": {"http_response_status_code": code, **({"le": "+Inf"} if bucket else {})},
             "values": [[900, "10"], [990, "20"]]} for code in ("200", "500")]}}

    return {"request_rate": vector("2"), "p95_latency": vector("0.1"),
            "error_ratio": vector("0.2"), "counter_sources": matrix(), "bucket_sources": matrix(True)}


def run(monkeypatch: pytest.MonkeyPatch, payloads: dict, fault: str | None = None,
        timeout: float = 2.0):
    monkeypatch.setattr("rook_backend.telemetry.time.time", lambda: 1000.0)
    plan = queries("frontend", "opentelemetry-demo")
    seen = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if fault == "deadline":
            await asyncio.sleep(1)
        if fault == "timeout":
            raise httpx.ReadTimeout("private-host")
        if fault == "http":
            return httpx.Response(500, text="private-host")
        if fault == "json":
            return httpx.Response(200, text="not json")
        name = next(key for key, value in plan.items() if value == request.url.params["query"])
        return httpx.Response(200, json=payloads[name])

    real_client = httpx.AsyncClient
    clients = []

    def factory(**kwargs):
        client = real_client(transport=httpx.MockTransport(handler), **kwargs)
        clients.append(client)
        return client

    monkeypatch.setattr("rook_backend.telemetry.httpx.AsyncClient", factory)
    app = create_app(Settings(prometheus_url="http://private-host:9090", prometheus_deadline_seconds=0.05,
                              prometheus_timeout_seconds=timeout))
    with TestClient(app) as client:
        response = client.get("/services/frontend/metrics")
        assert client.get("/health/live").json() == {"status": "alive"}
        assert not clients[0].is_closed
    assert clients[0].is_closed
    assert not hasattr(app.state, "prometheus")
    assert "private-host" not in response.text
    return response, seen


def test_values_time_and_cleanup(monkeypatch):
    response, seen = run(monkeypatch, responses())
    assert response.status_code == 200
    body = response.json()
    assert body["evaluation_timestamp"] == 1000
    assert body["window_seconds"] == 300
    assert len(seen) == 5
    assert {request.url.params["time"] for request in seen} == {"1000.0"}
    assert body["metrics"]["request_rate"]["value"] == 2
    assert body["metrics"]["p95_latency"]["unit"] == "seconds"
    assert body["metrics"]["error_ratio"]["value"] == 0.2
    # 900 is the oldest historical sample; 990 is the oldest latest sample.
    assert all(metric["oldest_latest_sample_timestamp"] == 990 for metric in body["metrics"].values())


@pytest.mark.parametrize("timeout,expected", [(2.0, "2000ms"), (0.05, "50ms"), (1.25, "1250ms")])
def test_prometheus_duration_and_empty_error_result(monkeypatch, timeout, expected):
    payloads = responses()
    payloads["error_ratio"]["data"]["result"] = []
    payloads["counter_sources"]["data"]["result"].pop()
    response, seen = run(monkeypatch, payloads, timeout=timeout)
    assert response.status_code == 200
    assert len(seen) == 5
    assert {request.url.params["timeout"] for request in seen} == {expected}
    assert {request.url.params["time"] for request in seen} == {"1000.0"}
    metric = response.json()["metrics"]["error_ratio"]
    assert metric["value"] is None
    assert metric["status"] == "insufficient_data"


@pytest.mark.parametrize("value", ["NaN", "+Inf", "-Inf", "-1"])
def test_invalid_values(monkeypatch, value):
    payloads = responses()
    payloads["p95_latency"]["data"]["result"][0]["value"][1] = value
    result = run(monkeypatch, payloads)[0].json()["metrics"]["p95_latency"]
    assert result["value"] is None
    assert result["status"] == "insufficient_data"


@pytest.mark.parametrize("case", ["empty_error", "zero", "one_sample", "missing_bucket", "stale", "partial_stale"])
def test_evidence(monkeypatch, case):
    payloads = responses()
    metric = "error_ratio"
    expected = "insufficient_data"
    if case == "empty_error":
        payloads["error_ratio"]["data"]["result"] = []
        payloads["counter_sources"]["data"]["result"].pop()
    elif case == "zero":
        payloads["request_rate"]["data"]["result"][0]["value"][1] = "0"
        metric = "request_rate"
    elif case == "one_sample":
        payloads["counter_sources"]["data"]["result"][0]["values"] = [[990, "20"]]
        metric = "request_rate"
    elif case == "missing_bucket":
        payloads["bucket_sources"]["data"]["result"] = []
        metric = "p95_latency"
    else:
        expected = "stale"
        metric = "p95_latency"
        rows = payloads["bucket_sources"]["data"]["result"]
        for row in (rows if case == "stale" else rows[:1]):
            row["values"] = [[750, "10"], [800, "20"]]
    result = run(monkeypatch, payloads)[0].json()["metrics"][metric]
    assert result["status"] == expected
    assert result["value"] is None


@pytest.mark.parametrize("fault", ["http", "timeout", "deadline", "json"])
def test_unavailable(monkeypatch, fault):
    response, _ = run(monkeypatch, responses(), fault)
    assert response.status_code == 503
    assert response.json() == {"status": "unavailable"}


@pytest.mark.parametrize("change", ["kind", "sample", "warnings"])
def test_invalid_protocol(monkeypatch, change):
    payloads = deepcopy(responses())
    data = payloads["request_rate"]
    if change == "kind":
        data["data"]["resultType"] = "scalar"
    elif change == "sample":
        data["data"]["result"][0]["value"] = [1000]
    else:
        data["warnings"] = ["partial response"]
    assert run(monkeypatch, payloads)[0].status_code == 503


@pytest.mark.parametrize("service", ['bad"selector', "frontend{", "frontend\\", "a" * 129, "bad name"])
def test_unsafe_selectors(service):
    with pytest.raises(ValueError):
        queries(service, "opentelemetry-demo")
    with TestClient(create_app(Settings(prometheus_url=None))) as client:
        assert client.get(f"/services/{service}/metrics").status_code == 422


def test_disabled():
    with TestClient(create_app(Settings(prometheus_url=None))) as client:
        response = client.get("/services/frontend/metrics")
        assert response.status_code == 503
        assert response.json() == {"status": "unavailable"}


def test_app_clients_are_isolated():
    first = create_app(Settings(prometheus_url="http://first.test"))
    second = create_app(Settings(prometheus_url="http://second.test"))
    with TestClient(first):
        first_client = first.state.prometheus.client
        with TestClient(second):
            second_client = second.state.prometheus.client
            assert first.state.prometheus is not second.state.prometheus
            assert first_client is not second_client
            first.state.prometheus.marker = "first-only"
            assert not hasattr(second.state.prometheus, "marker")
        assert second_client.is_closed
        assert not first_client.is_closed
    assert first_client.is_closed


def test_database_cleanup_on_prometheus_initialization_failure(monkeypatch):
    from unittest.mock import AsyncMock, MagicMock

    database = MagicMock()
    database.close = AsyncMock()
    monkeypatch.setattr("rook_backend.api.app.Database", lambda settings: database)
    def fail(settings):
        raise RuntimeError("initialization failed")
    monkeypatch.setattr("rook_backend.api.app.Prometheus", fail)
    app = create_app(Settings())
    with pytest.raises(RuntimeError, match="initialization failed"):
        with TestClient(app):
            pass
    database.close.assert_awaited_once()
    assert not hasattr(app.state, "database")


def test_malformed_labels_are_unavailable(monkeypatch):
    payloads = responses()
    payloads["counter_sources"]["data"]["result"][0]["metric"]["bad"] = []
    assert run(monkeypatch, payloads)[0].status_code == 503


def test_stale_denominator_cannot_hide_behind_fresh_error_series(monkeypatch):
    payloads = responses()
    payloads["counter_sources"]["data"]["result"][0]["values"] = [[750, "10"], [800, "20"]]
    body = run(monkeypatch, payloads)[0].json()
    for name in ("request_rate", "error_ratio"):
        assert body["metrics"][name]["status"] == "stale"
        assert body["metrics"][name]["oldest_latest_sample_timestamp"] == 800
        assert body["metrics"][name]["value"] is None
