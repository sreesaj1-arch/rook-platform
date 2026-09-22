"""PostgreSQL incident product state, with explicit schema bootstrap."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
from uuid import UUID, uuid4

from sqlalchemy import (Column, Float, Index, Integer, MetaData, String, Table,
                        CheckConstraint, insert, inspect, select, text, update)
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncConnection

from rook_backend.database import Database
from rook_backend.incidents import Incident, IncidentState, Rules, breaches, validate_transition
from rook_backend.telemetry import ServiceMetrics, Unavailable, queries

metadata = MetaData()
incidents = Table(
    "rook_incidents", metadata,
    Column("id", String(36), primary_key=True),
    Column("service_name", String(128), nullable=False),
    Column("service_namespace", String(128), nullable=False),
    Column("rule", String(32), nullable=False),
    Column("state", String(16), nullable=False),
    Column("opened_at", Float, nullable=False),
    Column("evaluation_timestamp", Float, nullable=False),
    Column("oldest_latest_sample_timestamp", Float, nullable=False),
    Column("window_seconds", Integer, nullable=False),
    Column("value", Float, nullable=False),
    Column("unit", String(32), nullable=False),
    Column("threshold", Float, nullable=False),
    Column("reason", String(256), nullable=False),
    Column("data_quality", String(32), nullable=False),
    Column("evidence_query", String(2048), nullable=False),
    CheckConstraint("state IN ('open', 'acknowledged', 'resolved')"),
    CheckConstraint("rule IN ('error_ratio', 'p95_latency')"),
    CheckConstraint("data_quality = 'measured'"),
)
active = incidents.c.state.in_(["open", "acknowledged"])
Index("rook_incidents_active_rule", incidents.c.service_namespace,
      incidents.c.service_name, incidents.c.rule, unique=True,
      postgresql_where=active, sqlite_where=active)


class PostgresIncidentStore:
    def __init__(self, database: Database) -> None:
        self.database = database

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[AsyncConnection]:
        if self.database.engine is None:
            raise Unavailable()
        try:
            async with asyncio.timeout(10):
                async with self.database.engine.begin() as connection:
                    yield connection
        except (SQLAlchemyError, OSError, TimeoutError):
            raise Unavailable() from None

    async def initialize(self) -> None:
        """Explicit first-schema creation only. Never alter existing tables."""
        async with self.transaction() as connection:
            await connection.execute(text("SELECT pg_advisory_xact_lock(73190501)"))
            await connection.run_sync(metadata.create_all)
            def verify(sync_connection: Connection) -> None:
                inspector = inspect(sync_connection)
                actual = {c["name"]: c for c in inspector.get_columns(incidents.name)}
                if set(actual) != set(incidents.c.keys()):
                    raise ValueError("Incident schema mismatch; explicit migration required")
                for column in incidents.c:
                    observed = actual[column.name]
                    if (observed["type"].python_type != column.type.python_type
                            or observed["nullable"] != column.nullable
                            or getattr(observed["type"], "length", None) != getattr(column.type, "length", None)):
                        raise ValueError("Incident schema mismatch; explicit migration required")
                indexes = inspector.get_indexes(incidents.name)
                if not any(index["name"] == "rook_incidents_active_rule" and index["unique"]
                           for index in indexes):
                    raise ValueError("Incident index mismatch; explicit migration required")
            await connection.run_sync(verify)

    async def list(self, limit: int = 100, offset: int = 0) -> list[Incident]:
        async with self.transaction() as connection:
            rows = (await connection.execute(select(incidents).order_by(
                incidents.c.opened_at.desc(), incidents.c.id).limit(limit).offset(offset))).mappings()
            return [Incident.model_validate(dict(row)) for row in rows]

    async def get(self, incident_id: UUID) -> Incident | None:
        async with self.transaction() as connection:
            row = (await connection.execute(select(incidents).where(
                incidents.c.id == str(incident_id)))).mappings().first()
            return Incident.model_validate(dict(row)) if row else None

    async def record(self, snapshot: ServiceMetrics, rules: Rules) -> list[Incident]:
        candidates = breaches(snapshot, rules)
        if not candidates:
            return []
        plan = queries(snapshot.service_name, snapshot.service_namespace)
        result = []
        async with self.transaction() as connection:
            # One bounded transaction serializes this milestone's writers. The
            # unique partial index also guards against duplicate active incidents.
            await connection.execute(text("SELECT pg_advisory_xact_lock(73190502)"))
            for name, metric, threshold in candidates:
                existing = (await connection.execute(select(incidents).where(
                    incidents.c.service_name == snapshot.service_name,
                    incidents.c.service_namespace == snapshot.service_namespace,
                    incidents.c.rule == name, active))).mappings().first()
                if not existing:
                    previous = (await connection.execute(select(incidents).where(
                        incidents.c.service_name == snapshot.service_name,
                        incidents.c.service_namespace == snapshot.service_namespace,
                        incidents.c.rule == name).order_by(
                            incidents.c.evaluation_timestamp.desc()).limit(1))).mappings().first()
                    if previous and (previous["evaluation_timestamp"] >= snapshot.evaluation_timestamp
                                     or previous["oldest_latest_sample_timestamp"] >= metric.oldest_latest_sample_timestamp):
                        # Replaying already resolved evidence cannot open a new incident.
                        continue
                if existing and (existing["evaluation_timestamp"] >= snapshot.evaluation_timestamp
                                 or existing["oldest_latest_sample_timestamp"] >= metric.oldest_latest_sample_timestamp):
                    result.append(Incident.model_validate(dict(existing)))
                    continue
                incident = Incident(
                    id=existing["id"] if existing else uuid4(),
                    service_name=snapshot.service_name, service_namespace=snapshot.service_namespace,
                    rule=name, state=existing["state"] if existing else "open",
                    opened_at=existing["opened_at"] if existing else snapshot.evaluation_timestamp,
                    evaluation_timestamp=snapshot.evaluation_timestamp,
                    oldest_latest_sample_timestamp=metric.oldest_latest_sample_timestamp,
                    value=metric.value, unit=metric.unit, threshold=threshold,
                    reason=f"{name} exceeded configured threshold", evidence_query=plan[name],
                )
                values = incident.model_dump(mode="json")
                if existing:
                    await connection.execute(update(incidents).where(
                        incidents.c.id == str(incident.id)).values(**values))
                else:
                    await connection.execute(insert(incidents).values(**values))
                result.append(incident)
        return result

    async def transition(self, incident_id: UUID, target: IncidentState) -> Incident | None:
        """Atomic operator action; no telemetry freshness or recovery claim."""
        async with self.transaction() as connection:
            # Share evaluation's ownership lock so a stale evaluation cannot undo
            # acknowledgment or resolution. Validation and update are atomic.
            await connection.execute(text("SELECT pg_advisory_xact_lock(73190502)"))
            row = (await connection.execute(select(incidents).where(
                incidents.c.id == str(incident_id)))).mappings().first()
            if row is None:
                return None
            validate_transition(row["state"], target)
            await connection.execute(update(incidents).where(
                incidents.c.id == str(incident_id)).values(state=target))
            return Incident.model_validate({**dict(row), "state": target})
