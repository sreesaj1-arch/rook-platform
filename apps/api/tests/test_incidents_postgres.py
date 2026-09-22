"""Opt-in real PostgreSQL verification; explicit fixtures, never Demo telemetry.

Run as a script inside the existing API container with current source on PYTHONPATH,
or set ROOK_TEST_POSTGRES=1 for pytest with reachable database configuration.
Only this test's unique namespace is deleted on cleanup; no volumes are touched.
"""

import asyncio
import os
import sys
from uuid import uuid4

from sqlalchemy import delete

from rook_backend.config import Settings
from rook_backend.database import Database
from rook_backend.incident_store import PostgresIncidentStore, incidents
from rook_backend.incidents import Rules, InvalidTransition, evaluate_service
from rook_backend.telemetry import Measurement, ServiceMetrics, Unavailable


async def verify_postgres() -> None:
    database = Database(Settings())
    other_database = Database(Settings())
    store = PostgresIncidentStore(database)
    other = PostgresIncidentStore(other_database)
    namespace = "rook-test-" + uuid4().hex
    rules = Rules(error_ratio=0.1)

    class FixtureSource:
        unavailable = False
        data = ServiceMetrics(
            service_name="explicit-test-fixture", service_namespace=namespace,
            evaluation_timestamp=1000, freshness_threshold_seconds=120,
            metrics={"error_ratio": Measurement(value=0.2, unit="ratio", status="measured",
                        oldest_latest_sample_timestamp=990)},
        )

        async def metrics(self, service: str) -> ServiceMetrics:
            if self.unavailable:
                raise Unavailable()
            return self.data

    source = FixtureSource()
    initialized = False
    try:
        assert await database.ready(), "PostgreSQL not ready"
        await store.initialize()
        initialized = True
        results = await asyncio.gather(*[
            evaluate_service("explicit-test-fixture", source, target, rules)
            for target in (store, other, store)
        ])
        first = results[0].incidents[0]
        assert all(result.incidents[0].id == first.id for result in results)
        assert await other.get(first.id) == first  # Independent connection, committed state.
        await store.initialize()  # Repeat bootstrap preserves persisted data.
        acknowledged = await other.transition(first.id, "acknowledged")
        assert acknowledged.state == "acknowledged"
        assert (await store.get(first.id)).state == "acknowledged"
        await store.transition(first.id, "resolved")
        for state in ("acknowledged", "resolved", "open"):
            try:
                await other.transition(first.id, state)
            except InvalidTransition:
                pass
            else:
                raise AssertionError("Invalid transition accepted")
        assert (await other.get(first.id)).state == "resolved"
        assert (await evaluate_service("explicit-test-fixture", source, store, rules)).incidents == []
        # A new observed breach after resolution can open a new incident.
        source.data = source.data.model_copy(update={
            "evaluation_timestamp": 1100,
            "metrics": {"error_ratio": Measurement(value=0.3, unit="ratio", status="measured",
                         oldest_latest_sample_timestamp=1090)},
        })
        second = (await evaluate_service("explicit-test-fixture", source, store, rules)).incidents[0]
        assert second.id != first.id
        source.unavailable = True
        assert (await evaluate_service("explicit-test-fixture", source, store, rules)).status == "unavailable"
        assert (await other.get(second.id)).state == "open"
        source.unavailable = False
        # Below-threshold recovery evidence does not automatically resolve this slice.
        source.data.metrics["error_ratio"] = Measurement(value=0.01, unit="ratio", status="measured",
                                                       oldest_latest_sample_timestamp=1090)
        assert (await evaluate_service("explicit-test-fixture", source, store, rules)).incidents == []
        assert (await other.get(second.id)).state == "open"
        assert (await other.transition(second.id, "resolved")).state == "resolved"
        print("PASS: real PostgreSQL persistence, concurrent deduplication, transitions, rollback and recovery policy")
    finally:
        try:
            if initialized:
                async with store.transaction() as connection:
                    await connection.execute(delete(incidents).where(incidents.c.service_namespace == namespace))
        finally:
            await database.close()
            await other_database.close()


def test_real_postgres() -> None:
    if os.environ.get("ROOK_TEST_POSTGRES") != "1":
        import pytest
        pytest.skip("Set ROOK_TEST_POSTGRES=1 with reachable PostgreSQL to run explicit integration fixtures")
    asyncio.run(verify_postgres(), loop_factory=asyncio.SelectorEventLoop if sys.platform == "win32" else None)


if __name__ == "__main__":
    asyncio.run(verify_postgres(), loop_factory=asyncio.SelectorEventLoop if sys.platform == "win32" else None)
