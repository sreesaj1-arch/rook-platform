import assert from 'node:assert/strict';
import { test } from 'node:test';
import { canAcknowledge, canResolve, loadIncident, loadIncidents, parseIncident, stateLabels, transitionIncident } from './incidents.ts';

// Explicit protocol fixtures, only imported by tests.
const fixture = () => ({ id: '11111111-1111-4111-8111-111111111111', service_name: 'test-service',
  service_namespace: 'test-only', state: 'open', reason: 'p95_latency exceeded threshold',
  value: 0.6, threshold: 0.5, unit: 'seconds', opened_at: 1000, evaluation_timestamp: 1100,
  oldest_latest_sample_timestamp: 1090, data_quality: 'measured' });
const signal = () => new AbortController().signal;

test('incident list and detail load through existing proxy', async context => {
  const row = fixture();
  context.mock.method(globalThis, 'fetch', async (url: string) => {
    if (url === '/api/incidents?limit=50&offset=0') return Response.json([row]);
    assert.equal(url, `/api/incidents/${row.id}`);
    return Response.json(row);
  });
  assert.equal((await loadIncidents(signal()))[0].value, 0.6);
  assert.equal((await loadIncident(row.id, signal())).opened_at, 1000);
});
test('empty incident response stays empty', async context => {
  context.mock.method(globalThis, 'fetch', async () => Response.json([]));
  assert.deepEqual(await loadIncidents(signal()), []);
});
test('all states keep distinct display labels and permitted actions', () => {
  for (const state of ['open', 'acknowledged', 'resolved'] as const) {
    assert.equal(parseIncident({ ...fixture(), state }).state, state);
    assert.equal(stateLabels[state], state[0].toUpperCase() + state.slice(1));
    assert.equal(canAcknowledge(state), state === 'open');
    assert.equal(canResolve(state), state !== 'resolved');
  }
});
for (const action of ['acknowledge', 'resolve'] as const) {
  test(`successful ${action} uses POST and confirmed server state`, async context => {
    const state = action === 'acknowledge' ? 'acknowledged' : 'resolved';
    context.mock.method(globalThis, 'fetch', async (url: string, init: RequestInit) => {
      assert.equal(url, `/api/incidents/${fixture().id}/${action}`);
      assert.equal(init.method, 'POST');
      return Response.json({ ...fixture(), state });
    });
    assert.equal((await transitionIncident(fixture().id, action, signal())).state, state);
  });
}
test('409 action conflict is clear and no upstream detail leaks', async context => {
  context.mock.method(globalThis, 'fetch', async () => new Response('private', { status: 409 }));
  await assert.rejects(transitionIncident(fixture().id, 'resolve', signal()), /HTTP 409.*Reload/);
});
test('unavailable list and details never become empty or healthy', async context => {
  context.mock.method(globalThis, 'fetch', async () => new Response('private', { status: 503 }));
  await assert.rejects(loadIncidents(signal()), /API unavailable/);
  await assert.rejects(loadIncident(fixture().id, signal()), /API unavailable/);
});
test('ambiguous failed POST requires reload, never automatic retry', async context => {
  let requests = 0;
  context.mock.method(globalThis, 'fetch', async () => { requests++; throw new TypeError('connection'); });
  await assert.rejects(transitionIncident(fixture().id, 'resolve', signal()), /server may have applied it/);
  assert.equal(requests, 1);
});
test('invalid evidence and selectors rejected; absent threshold stays unknown', async () => {
  assert.equal(parseIncident({ ...fixture(), threshold: undefined }).threshold, null);
  for (const patch of [{ value: NaN }, { state: 'healthy' }, { data_quality: 'stale' },
    { data_quality: 'insufficient_data' }, { opened_at: Infinity }]) {
    assert.throws(() => parseIncident({ ...fixture(), ...patch }));
  }
  await assert.rejects(loadIncident('../bad', signal()), /Invalid incident ID/);
});
test('wrong incident identity in detail is rejected', async context => {
  context.mock.method(globalThis, 'fetch', async () => Response.json(fixture()));
  await assert.rejects(loadIncident('22222222-2222-4222-8222-222222222222', signal()), /identity/);
});

const change = (id = '22222222-2222-4222-8222-222222222222') => ({ id,
  service_name: 'test-service', service_namespace: 'test-only', deployment_identifier: 'test-version',
  environment: 'test', source: 'operator', kind: 'configuration', summary: 'Test-only observation',
  observed_timestamp: 990 });
const enriched = () => ({ ...fixture(), nearby_changes: [change()], nearby_changes_status: 'available',
  nearby_changes_truncated: false, correlation_window_seconds: 300, correlation_environment: 'test' });

test('detail retains one or multiple nearby changes and their metadata', async context => {
  const row = { ...enriched(), nearby_changes: [change(), change('33333333-3333-4333-8333-333333333333')] };
  context.mock.method(globalThis, 'fetch', async () => Response.json(row));
  assert.deepEqual((await loadIncident(row.id, signal())).nearby_changes, row.nearby_changes);
  assert.equal(parseIncident(enriched()).nearby_changes[0].summary, 'Test-only observation');
});

test('available empty changes are distinct from unavailable and missing timestamp', () => {
  const empty = parseIncident({ ...enriched(), nearby_changes: [] });
  assert.equal(empty.nearby_changes_status, 'available');
  assert.deepEqual(empty.nearby_changes, []);
  for (const status of ['unavailable', 'missing_timestamp']) {
    const row = parseIncident({ ...enriched(), nearby_changes_status: status });
    assert.equal(row.nearby_changes_status, status);
    assert.deepEqual(row.nearby_changes, []);
    assert.equal(row.state, 'open');
  }
});

test('missing and malformed change enrichment stays unavailable without losing incident actions', () => {
  assert.equal(parseIncident(fixture()).nearby_changes_status, 'unavailable');
  for (const patch of [{ observed_timestamp: null }, { observed_timestamp: Infinity }, { id: 'bad' }, { summary: {} }]) {
    const row = parseIncident({ ...enriched(), nearby_changes: [{ ...change(), ...patch }] });
    assert.equal(row.nearby_changes_status, 'unavailable');
    assert.equal(canAcknowledge(row.state), true);
  }
});
