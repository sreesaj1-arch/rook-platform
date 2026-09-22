export const metricNames = ['request_rate', 'p95_latency', 'error_ratio'] as const;
export type MetricName = typeof metricNames[number];
export type Metric = {
  value: number | null;
  unit: string;
  status: 'measured' | 'stale' | 'insufficient_data';
  reason: string | null;
  oldest_latest_sample_timestamp: number | null;
};
export type Snapshot = {
  service_name: string;
  service_namespace: string;
  evaluation_timestamp: number;
  window_seconds: number;
  metrics: Partial<Record<MetricName, Metric>>;
};
export function safeService(value: string): boolean {
  return /^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}$/.test(value) && !/[\r\n]/.test(value);
}
const record = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value);
const finite = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value);
const timestamp = (value: unknown): value is number =>
  finite(value) && value >= 0 && value <= 8.64e12;

export function parseSnapshot(value: unknown, service: string): Snapshot {
  if (!record(value) || value.service_name !== service || typeof value.service_namespace !== 'string'
    || !timestamp(value.evaluation_timestamp) || value.window_seconds !== 300 || !record(value.metrics)) {
    throw new Error('The API returned an invalid metrics response.');
  }
  const metrics: Snapshot['metrics'] = {};
  for (const name of metricNames) {
    const item = value.metrics[name];
    if (item === undefined) continue;
    if (!record(item) || typeof item.unit !== 'string' || !item.unit
      || !['measured', 'stale', 'insufficient_data'].includes(String(item.status))
      || !(item.reason === null || typeof item.reason === 'string')
      || !(item.value === null || (finite(item.value) && item.value >= 0))
      || !(item.oldest_latest_sample_timestamp === null || timestamp(item.oldest_latest_sample_timestamp))
      || (item.status === 'measured' && item.value === null)) {
      throw new Error('The API returned an invalid metric.');
    }
    metrics[name] = item as Metric;
  }
  return { service_name: service, service_namespace: value.service_namespace,
    evaluation_timestamp: value.evaluation_timestamp, window_seconds: 300, metrics };
}

export async function loadSnapshot(service: string, signal: AbortSignal): Promise<Snapshot | null> {
  if (!safeService(service)) throw new Error('Enter a valid service name.');
  const response = await fetch(`/api/services/${encodeURIComponent(service)}/metrics`, { signal });
  if (!response.ok) throw new Error(response.status === 503
    ? 'Telemetry is unavailable. Check the API and Prometheus, then retry.'
    : `The API request failed (HTTP ${response.status}).`);
  if (response.status === 204) return null;
  const body: unknown = await response.json();
  if (body === null) return null;
  return parseSnapshot(body, service);
}

export function displayValue(metric: Metric): string {
  return metric.value === null ? '—' : new Intl.NumberFormat('en', { maximumSignificantDigits: 6 }).format(metric.value);
}
export function evidenceTime(value: number | null): string {
  return value === null ? 'Not available' : new Date(value * 1000).toISOString();
}
