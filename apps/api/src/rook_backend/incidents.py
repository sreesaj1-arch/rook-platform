"""Incident contracts and explicit evaluation; no scheduler or raw telemetry storage."""

import math
from typing import Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from rook_backend.telemetry import Measurement, ServiceMetrics, Unavailable, queries

IncidentState = Literal["open", "acknowledged", "resolved"]
MetricName = Literal["error_ratio", "p95_latency"]


class InvalidTransition(Exception):
    """The requested target is not allowed from the current incident state."""


def validate_transition(current: IncidentState, target: IncidentState) -> None:
    allowed = {"open": {"acknowledged", "resolved"}, "acknowledged": {"resolved"}, "resolved": set()}
    if target not in allowed[current]:
        raise InvalidTransition()


class Incident(BaseModel):
    model_config = ConfigDict(frozen=True)
    id: UUID
    service_name: str
    service_namespace: str
    rule: MetricName
    state: IncidentState
    opened_at: float
    evaluation_timestamp: float
    oldest_latest_sample_timestamp: float
    window_seconds: int = 300
    value: float
    unit: str
    threshold: float
    reason: str
    data_quality: Literal["measured"] = "measured"
    evidence_query: str


class Rules(BaseModel):
    """No implicit thresholds: the operator must configure at least one rule."""

    model_config = ConfigDict(frozen=True, allow_inf_nan=False)
    error_ratio: float | None = Field(default=None, ge=0, le=1)
    p95_latency: float | None = Field(default=None, gt=0)


class Evaluation(BaseModel):
    status: Literal["evaluated", "unavailable"]
    measurements: dict[str, Measurement] = Field(default_factory=dict)
    incidents: list[Incident] = Field(default_factory=list)


class MetricsSource(Protocol):
    async def metrics(self, service: str) -> ServiceMetrics: ...


class IncidentStore(Protocol):
    async def record(self, snapshot: ServiceMetrics, rules: Rules) -> list[Incident]: ...


def breaches(snapshot: ServiceMetrics, rules: Rules) -> list[tuple[MetricName, Measurement, float]]:
    """Only fresh, finite, measured evidence can create or update incidents."""
    result = []
    if snapshot.window_seconds != 300 or not math.isfinite(snapshot.evaluation_timestamp):
        return result
    for name, unit in (("error_ratio", "ratio"), ("p95_latency", "seconds")):
        threshold = getattr(rules, name)
        metric = snapshot.metrics.get(name)
        if threshold is None or metric is None or metric.status != "measured":
            continue
        value, timestamp = metric.value, metric.oldest_latest_sample_timestamp
        if (value is None or not math.isfinite(value) or value < 0
                or timestamp is None or not math.isfinite(timestamp)
                or not 0 <= snapshot.evaluation_timestamp - timestamp <= snapshot.freshness_threshold_seconds
                or metric.unit != unit or (name == "error_ratio" and value > 1)):
            continue
        if value > threshold:
            result.append((name, metric, threshold))
    return result


async def evaluate_service(service: str, source: MetricsSource, store: IncidentStore,
                           rules: Rules) -> Evaluation:
    """One evaluation for a future worker. Unavailable evidence never mutates state."""
    if rules.error_ratio is None and rules.p95_latency is None:
        raise ValueError("Configure at least one incident threshold")
    try:
        snapshot = await source.metrics(service)
    except Unavailable:
        return Evaluation(status="unavailable")
    if snapshot.service_name != service:
        raise ValueError("Unexpected service identity")
    queries(service, snapshot.service_namespace)  # Validate identity before persistence.
    incidents = await store.record(snapshot, rules)
    return Evaluation(status="evaluated", measurements=snapshot.metrics, incidents=incidents)
