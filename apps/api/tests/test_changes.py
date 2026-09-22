"""Explicit test-only observations; no production sample events."""
import asyncio
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from rook_backend.api.app import create_app
from rook_backend.changes import ChangeEvent, ChangeStore, ChangeConflict, nearby, change_metadata
from rook_backend.config import Settings
from rook_backend.incidents import Rules
from rook_backend.telemetry import Unavailable
from .test_incidents import SQLiteStore, snapshot


def event(**updates):
    return ChangeEvent(id=updates.pop('id', uuid4()), service_name=updates.pop('service_name', 'frontend'),
        service_namespace=updates.pop('service_namespace', 'opentelemetry-demo'),
        environment=updates.pop('environment', 'local'), deployment_identifier='test-release',
        observed_timestamp=updates.pop('observed_timestamp', 990.0), source='operator',
        kind='deployment', summary='Explicit test-only observation', **updates)


@pytest.fixture
def storage():
    persistence = SQLiteStore()
    change_metadata.create_all(persistence.engine)
    yield persistence, ChangeStore(persistence)
    persistence.engine.dispose()


def test_persistence_idempotency_conflict_and_filtering(storage):
    persistence, store = storage
    async def check():
        first = event()
        assert await store.record(first) == first
        assert await store.record(first) == first
        with pytest.raises(ChangeConflict):
            await store.record(first.model_copy(update={'summary': 'Different test content'}))
        for other in [event(service_name='other'), event(environment='other'),
                      event(service_namespace='other'), event(observed_timestamp=500.0)]:
            await store.record(other)
        assert await ChangeStore(persistence).recent('frontend', 'opentelemetry-demo', 'local', 900, 1100) == [first]
    asyncio.run(check())


def test_window_multiple_changes_boundaries_and_no_causation(storage):
    persistence, store = storage
    async def check():
        incident = (await persistence.record(snapshot(), Rules(error_ratio=0.1)))[0]
        for timestamp in [899, 900, 990, 1100, 1101]:
            await store.record(event(observed_timestamp=float(timestamp)))
        result = (await nearby([incident], store, Settings(change_correlation_window_seconds=100)))[0]
        assert [row.observed_timestamp for row in result.nearby_changes] == [1100, 990, 900]
        assert result.nearby_changes_status == 'available'
        assert result.state == incident.state and result.reason == incident.reason
        assert result.correlation_basis == 'temporal proximity to incident opened_at; not proof of causation'
        assert 'caused by' not in result.model_dump_json()
        assert (await nearby([incident], store, Settings(change_environment='other')))[0].nearby_changes == []
    asyncio.run(check())


@pytest.mark.parametrize('value', [None, float('nan'), float('inf'), -1, '990', 999999999999.0])
def test_missing_invalid_future_timestamp_rejected(value):
    with pytest.raises(ValidationError):
        event(observed_timestamp=value)


def test_missing_timestamp_field_rejected():
    payload = event().model_dump()
    del payload['observed_timestamp']
    with pytest.raises(ValidationError):
        ChangeEvent.model_validate(payload)


def test_unavailable_enrichment_preserves_incident(storage):
    persistence, _ = storage
    async def check():
        incident = (await persistence.record(snapshot(), Rules(error_ratio=0.1)))[0]
        failing = AsyncMock()
        failing.recent.side_effect = Unavailable('private')
        result = (await nearby([incident], failing, Settings()))[0]
        assert result.id == incident.id and result.state == 'open'
        assert result.nearby_changes == [] and result.nearby_changes_status == 'unavailable'
        assert 'private' not in result.model_dump_json()
    asyncio.run(check())


def test_api_record_recent_and_incident_responses(monkeypatch, storage):
    persistence, _ = storage
    incident = asyncio.run(persistence.record(snapshot(), Rules(error_ratio=0.1)))[0]
    changes = AsyncMock()
    observation = event()
    changes.record.return_value = observation
    changes.recent.return_value = [observation]
    repository = AsyncMock()
    repository.list.return_value = [incident]
    repository.get.return_value = incident
    monkeypatch.setattr('rook_backend.api.changes.change_store', lambda request: changes)
    monkeypatch.setattr('rook_backend.api.incidents.change_store', lambda request: changes)
    monkeypatch.setattr('rook_backend.api.incidents.incident_store', lambda request: repository)
    with TestClient(create_app(Settings())) as client:
        assert client.post('/changes', json=observation.model_dump(mode='json')).status_code == 201
        assert client.get('/services/frontend/changes').json()[0]['id'] == str(observation.id)
        for path in ['/incidents', f'/incidents/{incident.id}']:
            response = client.get(path)
            row = response.json()[0] if path == '/incidents' else response.json()
            assert row['nearby_changes'][0]['id'] == str(observation.id)
        changes.recent.return_value = []
        assert client.get(f'/incidents/{incident.id}').json()['nearby_changes'] == []
        changes.record.side_effect = ChangeConflict()
        assert client.post('/changes', json=observation.model_dump(mode='json')).status_code == 409
        changes.record.side_effect = Unavailable()
        assert client.post('/changes', json=observation.model_dump(mode='json')).status_code == 503
        bad = observation.model_dump(mode='json'); bad.pop('observed_timestamp')
        assert client.post('/changes', json=bad).status_code == 422
        assert client.get('/services/frontend/changes?lookback_seconds=86401').status_code == 422


def test_app_database_and_environment_isolation(storage):
    persistence, store = storage
    other = SQLiteStore()
    change_metadata.create_all(other.engine)
    try:
        asyncio.run(store.record(event()))
        assert asyncio.run(ChangeStore(other).recent('frontend','opentelemetry-demo','local',0,2000)) == []
        first, second = create_app(Settings(change_environment='one')), create_app(Settings(change_environment='two'))
        with TestClient(first) as a, TestClient(second) as b:
            assert first.state.database is not second.state.database
            assert first.state.settings.change_environment != second.state.settings.change_environment
            assert a.post('/changes', json=event().model_dump(mode='json')).status_code == 422
            assert b.get('/health/live').status_code == 200
    finally:
        other.engine.dispose()


def test_enrichment_is_bounded_and_anchored_to_opened_time(storage):
    persistence, store = storage
    async def check():
        incident = (await persistence.record(snapshot(), Rules(error_ratio=0.1)))[0]
        for timestamp in range(980, 1005):
            await store.record(event(observed_timestamp=float(timestamp)))
        # A later breach update must not shift the correlation anchor.
        incident = incident.model_copy(update={'evaluation_timestamp': 10000.0})
        result = (await nearby([incident], store, Settings()))[0]
        assert len(result.nearby_changes) == 20 and result.nearby_changes_truncated
        assert result.nearby_changes[0].observed_timestamp == 1004
    asyncio.run(check())
