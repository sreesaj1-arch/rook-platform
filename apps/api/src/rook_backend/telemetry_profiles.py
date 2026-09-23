"""Reviewed Prometheus profiles; HTTP callers cannot supply queries or URLs."""

import json
import re
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, HttpUrl

SERVICE = r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}"
ProfileName = Literal['otel-demo', 'local-http']


def validate_identity(service: str, namespace: str) -> None:
    if not re.fullmatch(SERVICE, service) or not re.fullmatch(SERVICE, namespace):
        raise ValueError('Invalid service identity')


class SourceConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra='forbid', hide_input_in_errors=True)
    profile: ProfileName
    url: HttpUrl


@dataclass(frozen=True)
class PrometheusProfile:
    counter: str
    bucket: str
    service_label: str
    namespace_label: str
    status_label: str

    def queries(self, service: str, namespace: str) -> dict[str, str]:
        validate_identity(service, namespace)
        labels = f'{self.service_label}={json.dumps(service)},{self.namespace_label}={json.dumps(namespace)}'
        count = f'{self.counter}{{{labels}}}'
        bucket = f'{self.bucket}{{{labels}}}'
        errors = f'{self.counter}{{{labels},{self.status_label}=~"5.."}}'
        rate = f'sum(rate({count}[5m]))'
        return {
            'request_rate': rate,
            'p95_latency': f'histogram_quantile(0.95, sum by (le)(rate({bucket}[5m])))',
            'error_ratio': f'sum(rate({errors}[5m])) / {rate}',
            'counter_sources': f'{count}[5m]',
            'bucket_sources': f'{bucket}[5m]',
        }


PROFILES = {
    'otel-demo': PrometheusProfile('http_server_request_duration_seconds_count',
        'http_server_request_duration_seconds_bucket', 'service_name', 'service_namespace',
        'http_response_status_code'),
    'local-http': PrometheusProfile('local_http_requests_total',
        'local_http_request_duration_seconds_bucket', 'app', 'namespace', 'code'),
}


def queries(service: str, namespace: str) -> dict[str, str]:
    """Compatibility entry point: the Demo's original five queries, unchanged."""
    return PROFILES['otel-demo'].queries(service, namespace)
