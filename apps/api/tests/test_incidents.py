"""Test-only measurements and SQLite persistence; no Demo or Docker required."""

import asyncio
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex

from rook_backend.api.app import create_app
from rook_backend.config import Settings
from rook_backend.database import Database
from rook_backend.incident_store import PostgresIncidentStore, incidents, metadata
from rook_backend.incidents import Rules, InvalidTransition, evaluate_service
from rook_backend.telemetry import Measurement, ServiceMetrics, Unavailable


def snapshot(value=0.2, status="measured", timestamp=990, now=1000):
    return ServiceMetrics(
        service_name="frontend", service_namespace="opentelemetry-demo",
        evaluation_timestamp=now, freshness_threshold_seconds=120,
        metrics={"error_ratio": Measurement(value=value, unit="ratio", status=status,
                  oldest_latest_sample_timestamp=timestamp),
                 "p95_latency": Measurement(value=0.5, unit="seconds", status="measured",
                  oldest_latest_sample_timestamp=timestamp)},
    )


class SQLiteStore(PostgresIncidentStore):
    """Execute the actual repository SQL without an async SQLite dependency.

    PostgreSQL advisory locking is separately asserted, not simulated as proven.
    """

    def __init__(self):
        self.engine = create_engine("sqlite://")
        metadata.create_all(self.engine)
        self.locks = 0

    @asynccontextmanager
    async def transaction(self):
        owner = self
        with self.engine.begin() as connection:
            class Adapter:
                async def run_sync(self, operation):
                    return operation(connection)

                async def execute(self, statement):
                    if str(statement).startswith("SELECT pg_advisory_xact_lock"):
                        owner.locks += 1
                        return None
                    return connection.execute(statement)
            yield Adapter()


@pytest.fixture
def store():
    result = SQLiteStore()
    yield result
    result.engine.dispose()


def test_create_retrieve_deduplicate_and_ignore_old_samples(store):
    async def check():
        source = AsyncMock()
        source.metrics.return_value = snapshot()
        rules = Rules(error_ratio=0.1, p95_latency=0.3)
        result = await evaluate_service("frontend", source, store, rules)
        assert result.status == "evaluated"
        assert len(result.incidents) == 2
        incident = result.incidents[0]
        assert incident.state == "open" and incident.value == 0.2
        assert incident.data_quality == "measured"
        assert incident.oldest_latest_sample_timestamp == 990
        assert 'http_response_status_code=~"5.."' in incident.evidence_query
        assert await store.get(incident.id) == incident
        assert await store.get(uuid4()) is None
        repeated = await evaluate_service("frontend", source, store, rules)
        assert repeated.incidents == result.incidents
        source.metrics.return_value = snapshot(value=0.4, timestamp=995, now=1010)
        updated = await evaluate_service("frontend", source, store, rules)
        assert updated.incidents[0].id == incident.id
        assert updated.incidents[0].value == 0.4
        assert updated.incidents[0].opened_at == 1000
        source.metrics.return_value = snapshot()
        old = await evaluate_service("frontend", source, store, rules)
        assert old.incidents == updated.incidents
        assert len(await store.list()) == 2
        assert len(await store.list(limit=1, offset=1)) == 1
        assert store.locks == 4
    asyncio.run(check())


@pytest.mark.parametrize("value,status,timestamp", [
    (None, "insufficient_data", None), (0.9, "stale", 800),
    (0.9, "measured", 800), (float("nan"), "measured", 990),
    (float("inf"), "measured", 990), (0.9, "measured", 1001),
    (0.1, "measured", 990), (0, "measured", 990),
])
def test_no_incident_for_bad_evidence_or_no_breach(store, value, status, timestamp):
    async def check():
        source = AsyncMock()
        source.metrics.return_value = snapshot(value, status, timestamp)
        result = await evaluate_service("frontend", source, store, Rules(error_ratio=0.1))
        assert result.incidents == [] and await store.list() == []
        if value is None:
            assert result.measurements["error_ratio"].value is None
            assert result.measurements["error_ratio"].status == "insufficient_data"
    asyncio.run(check())


def test_unavailable_and_missing_do_not_resolve_active_incident(store):
    async def check():
        source = AsyncMock()
        source.metrics.return_value = snapshot()
        rules = Rules(error_ratio=0.1)
        opened = (await evaluate_service("frontend", source, store, rules)).incidents
        source.metrics.side_effect = Unavailable("private connection")
        result = await evaluate_service("frontend", source, store, rules)
        assert result.status == "unavailable" and "private" not in result.model_dump_json()
        source.metrics.side_effect = None
        for data in [snapshot(None, "insufficient_data", None), snapshot(0.01)]:
            source.metrics.return_value = data
            await evaluate_service("frontend", source, store, rules)
            assert await store.list() == opened
    asyncio.run(check())


def test_acknowledged_is_active_and_resolved_allows_new_incident(store):
    async def check():
        rules = Rules(error_ratio=0.1)
        first = (await store.record(snapshot(), rules))[0]
        await store.transition(first.id, "acknowledged")
        repeated = (await store.record(snapshot(now=1020, timestamp=1010), rules))[0]
        assert repeated.id == first.id and repeated.state == "acknowledged"
        await store.transition(first.id, "resolved")
        new = (await store.record(snapshot(now=1040, timestamp=1030), rules))[0]
        assert new.id != first.id and len(await store.list()) == 2
    asyncio.run(check())


def test_api_retrieval_and_validation(monkeypatch, store):
    incident = asyncio.run(store.record(snapshot(), Rules(error_ratio=0.1)))[0]
    # Use detached results across the TestClient thread, not a SQLite connection.
    repository = AsyncMock()
    repository.list.return_value = [incident]
    repository.get.return_value = incident
    monkeypatch.setattr("rook_backend.api.incidents.incident_store", lambda request: repository)
    with TestClient(create_app(Settings())) as client:
        assert client.get("/incidents").json()[0]["id"] == str(incident.id)
        assert client.get(f"/incidents/{incident.id}").json()["value"] == 0.2
        assert client.get("/incidents/not-a-uuid").status_code == 422
        assert client.get("/incidents?limit=101").status_code == 422
        repository.get.return_value = None
        assert client.get(f"/incidents/{uuid4()}").status_code == 404
        repository.list.side_effect = Unavailable("private")
        response = client.get("/incidents")
        assert response.status_code == 503 and response.json() == {"status": "unavailable"}
        assert client.get("/health/live").json() == {"status": "alive"}


def test_disabled_database_and_app_isolation():
    first, second = create_app(Settings(db_password=None)), create_app(Settings(db_password=None))
    with TestClient(first) as a, TestClient(second) as b:
        assert first.state.database is not second.state.database
        assert a.get("/incidents").status_code == b.get("/incidents").status_code == 503
        assert a.get("/health/live").status_code == 200
        assert b.get("/health/ready").status_code == 503


def test_store_instances_do_not_share_data(store):
    other = SQLiteStore()
    try:
        asyncio.run(store.record(snapshot(), Rules(error_ratio=0.1)))
        assert asyncio.run(other.list()) == []
    finally:
        other.engine.dispose()


def test_postgres_unique_active_index():
    index = next(iter(incidents.indexes))
    ddl = str(CreateIndex(index).compile(dialect=postgresql.dialect()))
    assert "UNIQUE INDEX" in ddl and "WHERE state IN ('open', 'acknowledged')" in ddl


def test_rules_require_explicit_finite_thresholds():
    from pydantic import ValidationError
    for kwargs in [{"error_ratio": 2}, {"p95_latency": 0}, {"error_ratio": float("nan")}]:
        with pytest.raises(ValidationError):
            Rules(**kwargs)
    with pytest.raises(ValueError, match="threshold"):
        asyncio.run(evaluate_service("frontend", AsyncMock(), AsyncMock(), Rules()))


def test_store_disconnected_is_generic():
    store = PostgresIncidentStore(Database(Settings(db_password=None)))
    with pytest.raises(Unavailable):
        asyncio.run(store.list())


def test_initialization_is_repeatable_and_rejects_schema_drift(store):
    async def check():
        await store.initialize()
        created = await store.record(snapshot(), Rules(error_ratio=0.1))
        await store.initialize()
        assert await store.list() == created
        with store.engine.begin() as connection:
            connection.execute(text("ALTER TABLE rook_incidents ADD COLUMN unexpected INTEGER"))
        with pytest.raises(ValueError, match="schema mismatch"):
            await store.initialize()
        assert len(await store.list()) == 1
    asyncio.run(check())


def test_transaction_failure_rolls_back_and_hides_details():
    database = MagicMock()
    connection = MagicMock()
    connection.execute = AsyncMock(side_effect=OperationalError(
        "private statement", {}, Exception("private connection")))
    transaction = database.engine.begin.return_value
    transaction.__aenter__ = AsyncMock(return_value=connection)
    transaction.__aexit__ = AsyncMock(return_value=False)
    with pytest.raises(Unavailable) as failure:
        asyncio.run(PostgresIncidentStore(database).record(snapshot(), Rules(error_ratio=0.1)))
    assert str(failure.value) == ""
    transaction.__aexit__.assert_awaited_once()
    assert transaction.__aexit__.call_args.args[0] is OperationalError


def test_cli_closes_resources_when_prometheus_unavailable(monkeypatch):
    from rook_backend.incident_cli import run
    database, source = MagicMock(), AsyncMock()
    database.close = AsyncMock()
    source.metrics.side_effect = Unavailable()
    monkeypatch.setattr("rook_backend.incident_cli.Database", lambda settings: database)
    monkeypatch.setattr("rook_backend.incident_cli.Prometheus", lambda settings: source)
    assert asyncio.run(run("evaluate", "frontend", Rules(error_ratio=0.1), Settings())) == 1
    database.close.assert_awaited_once()
    source.close.assert_awaited_once()


@pytest.mark.parametrize("states", [
    ["acknowledged", "resolved"], ["resolved"],
])
def test_transitions_preserve_evidence_and_reject_invalid_changes(store, states):
    async def check():
        first = (await store.record(snapshot(), Rules(error_ratio=0.1)))[0]
        current = first
        for state in states:
            current = await store.transition(first.id, state)
            assert current.model_dump(exclude={"state"}) == first.model_dump(exclude={"state"})
            assert (await store.get(first.id)).state == state
            with pytest.raises(InvalidTransition):
                await store.transition(first.id, state)
        for target in ["open", "acknowledged", "resolved"]:
            with pytest.raises(InvalidTransition):
                await store.transition(first.id, target)
            assert await store.get(first.id) == current
        assert await store.transition(uuid4(), "resolved") is None
        assert await store.record(snapshot(), Rules(error_ratio=0.1)) == []
        assert len(await store.list()) == 1
    asyncio.run(check())


@pytest.mark.parametrize("action,target", [("acknowledge", "acknowledged"), ("resolve", "resolved")])
def test_transition_endpoints(monkeypatch, store, action, target):
    incident = asyncio.run(store.record(snapshot(), Rules(error_ratio=0.1)))[0]
    repository = AsyncMock()
    repository.transition.return_value = incident.model_copy(update={"state": target})
    monkeypatch.setattr("rook_backend.api.incidents.incident_store", lambda request: repository)
    with TestClient(create_app(Settings())) as client:
        url = f"/incidents/{incident.id}/{action}"
        assert client.post(url).json()["state"] == target
        repository.transition.assert_awaited_once_with(incident.id, target)
        for error, code, status in [(InvalidTransition(), 409, "invalid_transition"),
                                    (Unavailable("private"), 503, "unavailable")]:
            repository.transition.side_effect = error
            response = client.post(url)
            assert response.status_code == code and response.json() == {"status": status}
        repository.transition.side_effect = None
        repository.transition.return_value = None
        assert client.post(url).status_code == 404
        assert client.post(f"/incidents/bad-id/{action}").status_code == 422


def test_transition_app_resources_are_isolated():
    first, second = create_app(Settings(db_password=None)), create_app(Settings(db_password=None))
    with TestClient(first) as a, TestClient(second) as b:
        assert first.state.database is not second.state.database
        assert a.post(f"/incidents/{uuid4()}/resolve").status_code == 503
        assert b.get("/health/live").status_code == 200
