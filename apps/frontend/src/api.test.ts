import assert from 'node:assert/strict';
import { test } from 'node:test';
import { displayValue, evidenceTime, loadSnapshot, parseSnapshot, safeService } from './api.ts';

// Test-only API protocol examples. No fixture is imported by the dashboard.
const example = () => ({ service_name: 'frontend', service_namespace: 'test',
  evaluation_timestamp: 1000, window_seconds: 300, metrics: {
    error_ratio: { value: null, unit: 'ratio', status: 'insufficient_data',
      reason: 'missing_samples', oldest_latest_sample_timestamp: null },
  } });

test('service validation rejects unsafe or oversized selectors', () => {
  assert.ok(safeService('frontend'));
  assert.ok(safeService('my-service.v2'));
  for (const name of ['', 'a"}', '../api', 'x\n', 'a'.repeat(129)]) assert.equal(safeService(name), false);
});
test('missing errors remain null and preserve reason and timestamp', () => {
  const metric = parseSnapshot(example(), 'frontend').metrics.error_ratio!;
  assert.equal(metric.value, null);
  assert.equal(metric.reason, 'missing_samples');
  assert.equal(displayValue(metric), '—');
  assert.equal(evidenceTime(metric.oldest_latest_sample_timestamp), 'Not available');
});
test('zero is displayed only when returned; stale status is preserved', () => {
  const data = example();
  const metric = { ...data.metrics.error_ratio, value: 0, status: 'stale', oldest_latest_sample_timestamp: 900 };
  const parsed = parseSnapshot({ ...data, metrics: { error_ratio: metric } }, 'frontend').metrics.error_ratio!;
  assert.equal(parsed.status, 'stale');
  assert.equal(displayValue(parsed), '0');
  assert.equal(evidenceTime(parsed.oldest_latest_sample_timestamp), '1970-01-01T00:15:00.000Z');
});
test('empty metrics are accepted without inventing values', () => {
  assert.deepEqual(parseSnapshot({ ...example(), metrics: {} }, 'frontend').metrics, {});
});
test('invalid values, unknown status and wrong identity are rejected', () => {
  for (const patch of [{ value: Infinity }, { value: NaN }, { status: 'healthy' }, { status: 'measured', value: null }]) {
    const data = example();
    assert.throws(() => parseSnapshot({ ...data, metrics: { error_ratio: { ...data.metrics.error_ratio, ...patch } } }, 'frontend'));
  }
  assert.throws(() => parseSnapshot(example(), 'other'));
});
test('unavailable response is an error, not empty data, and hides upstream details', async (context) => {
  context.mock.method(globalThis, 'fetch', async () => new Response('private upstream detail', { status: 503 }));
  await assert.rejects(loadSnapshot('frontend', new AbortController().signal), /Telemetry is unavailable/);
});
test('successful transport uses local proxy and validates the result', async (context) => {
  context.mock.method(globalThis, 'fetch', async (url: string) => {
    assert.equal(url, '/api/services/frontend/metrics');
    return Response.json(example());
  });
  assert.equal((await loadSnapshot('frontend', new AbortController().signal))?.service_name, 'frontend');
});
test('204 is an explicit empty-data response', async (context) => {
  context.mock.method(globalThis, 'fetch', async () => new Response(null, { status: 204 }));
  assert.equal(await loadSnapshot('frontend', new AbortController().signal), null);
});
