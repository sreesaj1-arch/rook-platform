"""Bounded, read-only Prometheus measurements. No persistence or health inference."""

import asyncio
import json
import math
import re
import time
from typing import Literal

import httpx
from pydantic import BaseModel

from rook_backend.config import Settings

COUNTER = "http_server_request_duration_seconds_count"
BUCKET = "http_server_request_duration_seconds_bucket"
SERVICE = r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}"


class Unavailable(Exception):
    """Upstream unavailable; never expose the underlying exception."""


class Measurement(BaseModel):
    value: float | None = None
    unit: str
    status: Literal["measured", "stale", "insufficient_data"]
    reason: str | None = None
    oldest_latest_sample_timestamp: float | None = None


class ServiceMetrics(BaseModel):
    service_name: str
    service_namespace: str
    evaluation_timestamp: float
    window_seconds: int = 300
    freshness_threshold_seconds: float
    metrics: dict[str, Measurement]


def queries(service: str, namespace: str) -> dict[str, str]:
    if not re.fullmatch(SERVICE, service) or not re.fullmatch(SERVICE, namespace):
        raise ValueError("Invalid service identity")
    labels = f"service_name={json.dumps(service)},service_namespace={json.dumps(namespace)}"
    count = f"{COUNTER}{{{labels}}}"
    bucket = f"{BUCKET}{{{labels}}}"
    errors = f'{COUNTER}{{{labels},http_response_status_code=~"5.."}}'
    rate = f"sum(rate({count}[5m]))"
    return {
        "request_rate": rate,
        "p95_latency": f"histogram_quantile(0.95, sum by (le)(rate({bucket}[5m])))",
        "error_ratio": f"sum(rate({errors}[5m])) / {rate}",
        "counter_sources": f"{count}[5m]",
        "bucket_sources": f"{bucket}[5m]",
    }


def parse_result(payload: object, kind: str) -> list[dict]:
    if not isinstance(payload, dict) or payload.get("status") != "success":
        raise ValueError("Invalid response")
    if payload.get("warnings") or payload.get("infos"):
        raise ValueError("Partial response")
    data = payload.get("data")
    if not isinstance(data, dict) or data.get("resultType") != kind:
        raise ValueError("Invalid result type")
    result = data.get("result")
    if not isinstance(result, list) or (kind == "vector" and len(result) > 1):
        raise ValueError("Invalid result")
    for row in result:
        if not isinstance(row, dict) or not isinstance(row.get("metric"), dict):
            raise ValueError("Invalid series")
        if any(not isinstance(key, str) or not isinstance(value, str)
               for key, value in row["metric"].items()):
            raise ValueError("Invalid labels")
        samples = row.get("values") if kind == "matrix" else [row.get("value")]
        if not isinstance(samples, list) or not samples:
            raise ValueError("Invalid samples")
        previous = -math.inf
        for sample in samples:
            if not isinstance(sample, list) or len(sample) != 2:
                raise ValueError("Invalid sample")
            timestamp, value = sample
            if type(timestamp) not in (int, float) or not math.isfinite(timestamp) or timestamp <= previous:
                raise ValueError("Invalid timestamp")
            if not isinstance(value, str):
                raise ValueError("Invalid sample value")
            float(value)
            previous = timestamp
    return result


def measurement(value: float | None, unit: str, sources: list[dict], now: float,
                threshold: float, traffic: float | None) -> Measurement:
    oldest = min((row["values"][-1][0] for row in sources), default=None)
    result = Measurement(unit=unit, status="insufficient_data", reason="missing_or_inadequate_samples",
                         oldest_latest_sample_timestamp=oldest)
    if oldest is not None and now - oldest > threshold:
        return result.model_copy(update={"status": "stale", "reason": "source_samples_too_old"})
    if not sources or any(len(row["values"]) < 2 for row in sources):
        return result
    if any(sample[0] > now or not math.isfinite(float(sample[1])) or float(sample[1]) < 0
           for row in sources for sample in row["values"]):
        return result.model_copy(update={"reason": "invalid_source_samples"})
    if traffic is None or not math.isfinite(traffic) or traffic <= 0:
        return result.model_copy(update={"reason": "missing_or_zero_request_rate"})
    if value is None or not math.isfinite(value) or value < 0 or (unit == "ratio" and value > 1):
        return result.model_copy(update={"reason": "missing_or_invalid_result"})
    return result.model_copy(update={"value": value, "status": "measured", "reason": None})


class Prometheus:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.client = httpx.AsyncClient(
            timeout=settings.prometheus_timeout_seconds,
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
            trust_env=False, follow_redirects=False,
        ) if settings.prometheus_url else None

    async def close(self) -> None:
        if self.client is not None:
            await self.client.aclose()

    async def query(self, query: str, timestamp: float, kind: str) -> list[dict]:
        assert self.client is not None
        url = str(self.settings.prometheus_url).rstrip("/") + "/api/v1/query"
        async with self.client.stream("GET", url, params={
            "query": query, "time": str(timestamp),
            # Prometheus duration units require integer quantities, not "2.0s".
            "timeout": f"{int(self.settings.prometheus_timeout_seconds * 1000)}ms",
        }) as response:
            response.raise_for_status()
            body = bytearray()
            async for chunk in response.aiter_bytes():
                body.extend(chunk)
                if len(body) > 2_000_000:
                    raise ValueError("Response too large")
        return parse_result(json.loads(body), kind)

    async def metrics(self, service: str) -> ServiceMetrics:
        if self.client is None:
            raise Unavailable()
        timestamp = time.time()
        plan = queries(service, self.settings.prometheus_namespace)
        try:
            async with asyncio.timeout(self.settings.prometheus_deadline_seconds):
                results = {}
                for name, query in plan.items():
                    results[name] = await self.query(query, timestamp, "matrix" if name.endswith("sources") else "vector")
                values = {name: float(results[name][0]["value"][1]) if results[name] else None
                          for name in ("request_rate", "p95_latency", "error_ratio")}
                counters = results["counter_sources"]
                buckets = results["bucket_sources"]
                # The ratio depends on every denominator series AND the error subset.
                error_sources = [row for row in counters if re.fullmatch(
                    r"5\d\d", row["metric"].get("http_response_status_code", ""))]
                sources = {"request_rate": counters, "p95_latency": buckets,
                           "error_ratio": counters if error_sources else []}
                units = {"request_rate": "requests/second", "p95_latency": "seconds", "error_ratio": "ratio"}
                measured = {name: measurement(values[name], units[name], sources[name], timestamp,
                            self.settings.prometheus_freshness_seconds, values["request_rate"])
                            for name in values}
                return ServiceMetrics(service_name=service, service_namespace=self.settings.prometheus_namespace,
                                      evaluation_timestamp=timestamp,
                                      freshness_threshold_seconds=self.settings.prometheus_freshness_seconds,
                                      metrics=measured)
        except (httpx.HTTPError, TimeoutError, ValueError, TypeError, KeyError):
            raise Unavailable() from None
