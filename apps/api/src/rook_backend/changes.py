"""Operator-observed product changes and temporal evidence, never causation."""

import asyncio
import math
import time
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import Column, Float, Index, MetaData, String, Table, insert, select, text

from rook_backend.config import Settings
from rook_backend.incident_store import PostgresIncidentStore
from rook_backend.incidents import Incident
from rook_backend.telemetry import SERVICE, Unavailable

Identity = Annotated[str, Field(pattern=f'^{SERVICE}$')]


class ChangeEvent(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True, hide_input_in_errors=True)
    id: UUID
    service_name: Identity
    service_namespace: Identity
    deployment_identifier: str = Field(min_length=1, max_length=256, pattern=r'\S')
    environment: Identity
    observed_timestamp: float = Field(ge=0, allow_inf_nan=False, strict=True)
    source: Literal['operator', 'deployment_action']
    kind: Literal['deployment', 'configuration']
    summary: str = Field(min_length=1, max_length=500, pattern=r'\S')

    @field_validator('observed_timestamp')
    @classmethod
    def no_future_observation(cls, value: float) -> float:
        if value > time.time():
            raise ValueError('Observation cannot be in the future')
        return value


change_metadata = MetaData()
changes = Table(
    'rook_change_events', change_metadata,
    Column('id', String(36), primary_key=True),
    Column('service_name', String(128), nullable=False),
    Column('service_namespace', String(128), nullable=False),
    Column('deployment_identifier', String(256), nullable=False),
    Column('environment', String(128), nullable=False),
    Column('observed_timestamp', Float, nullable=False),
    Column('source', String(32), nullable=False),
    Column('kind', String(32), nullable=False),
    Column('summary', String(500), nullable=False),
)
Index('rook_changes_service_time', changes.c.environment, changes.c.service_namespace,
      changes.c.service_name, changes.c.observed_timestamp)


class ChangeConflict(Exception):
    """An event ID was reused with different content."""


class ChangeStore:
    def __init__(self, persistence: PostgresIncidentStore) -> None:
        self.persistence = persistence

    async def record(self, event: ChangeEvent) -> ChangeEvent:
        async with self.persistence.transaction() as connection:
            await connection.execute(text('SELECT pg_advisory_xact_lock(73190504)'))
            existing = (await connection.execute(select(changes).where(
                changes.c.id == str(event.id)))).mappings().first()
            if existing:
                result = ChangeEvent.model_validate(dict(existing))
                if result != event:
                    raise ChangeConflict()
                return result
            await connection.execute(insert(changes).values(**event.model_dump(mode='json')))
        return event

    async def recent(self, service: str, namespace: str, environment: str,
                     start: float, end: float, limit: int = 100) -> list[ChangeEvent]:
        async with self.persistence.transaction() as connection:
            rows = (await connection.execute(select(changes).where(
                changes.c.service_name == service, changes.c.service_namespace == namespace,
                changes.c.environment == environment,
                changes.c.observed_timestamp >= start, changes.c.observed_timestamp <= end,
            ).order_by(changes.c.observed_timestamp.desc(), changes.c.id).limit(limit))).mappings()
            return [ChangeEvent.model_validate(dict(row)) for row in rows]


class IncidentWithChanges(Incident):
    nearby_changes: list[ChangeEvent] = Field(default_factory=list)
    nearby_changes_status: Literal['available', 'unavailable', 'missing_timestamp'] = 'available'
    nearby_changes_truncated: bool = False
    correlation_window_seconds: int
    correlation_environment: str
    correlation_basis: Literal['temporal proximity to incident opened_at; not proof of causation'] = (
        'temporal proximity to incident opened_at; not proof of causation')


async def nearby(incidents: list[Incident], store: ChangeStore, settings: Settings) -> list[IncidentWithChanges]:
    result = [IncidentWithChanges(**item.model_dump(),
              correlation_window_seconds=settings.change_correlation_window_seconds,
              correlation_environment=settings.change_environment) for item in incidents]
    try:
        # Bound enrichment of the entire page, not just each database query.
        async with asyncio.timeout(3):
            for index, item in enumerate(result):
                anchor = item.opened_at
                if anchor is None or not math.isfinite(anchor) or anchor < 0:
                    result[index] = item.model_copy(update={'nearby_changes_status': 'missing_timestamp'})
                    continue
                window = settings.change_correlation_window_seconds
                rows = await store.recent(item.service_name, item.service_namespace, settings.change_environment,
                                          max(0, anchor - window), anchor + window, 21)
                result[index] = item.model_copy(update={'nearby_changes': rows[:20], 'nearby_changes_truncated': len(rows) > 20})
    except (Unavailable, TimeoutError):
        return [item.model_copy(update={'nearby_changes': [], 'nearby_changes_status': 'unavailable',
                                       'nearby_changes_truncated': False}) for item in result]
    return result
