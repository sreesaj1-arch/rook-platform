/** Persisted product state only; never infer incidents from metric cards. */
export type IncidentState = 'open' | 'acknowledged' | 'resolved';
export type Incident = {
  id: string; service_name: string; service_namespace: string; state: IncidentState;
  reason: string; value: number; unit: string; threshold: number | null;
  opened_at: number; evaluation_timestamp: number; oldest_latest_sample_timestamp: number;
  data_quality: 'measured';
};
export const stateLabels = { open: 'Open', acknowledged: 'Acknowledged', resolved: 'Resolved' };
export const canAcknowledge = (state: IncidentState) => state === 'open';
export const canResolve = (state: IncidentState) => state === 'open' || state === 'acknowledged';
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const finite = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v) && v >= 0;
const timestamp = (v: unknown) => finite(v) && v <= 8.64e12;

export function parseIncident(value: unknown): Incident {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('Invalid incident response.');
  const row = value as Record<string, unknown>;
  if (typeof row.id !== 'string' || !uuid.test(row.id)
    || !['open', 'acknowledged', 'resolved'].includes(String(row.state))
    || !['service_name', 'service_namespace', 'reason', 'unit'].every(key => typeof row[key] === 'string' && row[key])
    || !finite(row.value) || !(row.threshold == null || finite(row.threshold))
    || ![row.opened_at, row.evaluation_timestamp, row.oldest_latest_sample_timestamp].every(timestamp)
    || row.data_quality !== 'measured') throw new Error('Invalid incident response.');
  return { ...row, threshold: row.threshold ?? null } as Incident;
}

export class IncidentApiError extends Error {
  status: number;
  constructor(status: number) {
    super(status === 409 ? 'This action conflicts with the current incident state (HTTP 409). Reload before trying again.'
      : status === 503 ? 'Incident API unavailable. No incident state can be inferred.'
      : status === 404 ? 'This incident is no longer available.'
      : `Incident request failed (HTTP ${status}).`);
    this.status = status;
  }
}

async function request(path: string, signal: AbortSignal, method = 'GET'): Promise<unknown> {
  try {
    const response = await fetch(`/api/incidents${path}`, {
      method, signal: AbortSignal.any([signal, AbortSignal.timeout(12000)]),
    });
    if (!response.ok) throw new IncidentApiError(response.status);
    return await response.json();
  } catch (error) {
    if (error instanceof IncidentApiError) throw error;
    throw new Error(method === 'POST'
      ? 'Action result could not be confirmed. Reload before retrying; the server may have applied it.'
      : 'Unable to load incidents. Check the API connection and retry.');
  }
}

export async function loadIncidents(signal: AbortSignal, offset = 0): Promise<Incident[]> {
  if (!Number.isInteger(offset) || offset < 0 || offset > 100000) throw new Error('Invalid incident page.');
  const body = await request(`?limit=50&offset=${offset}`, signal);
  if (!Array.isArray(body) || body.length > 50) throw new Error('Invalid incident list response.');
  const rows = body.map(parseIncident);
  if (new Set(rows.map(row => row.id)).size !== rows.length) throw new Error('Duplicate incident IDs in response.');
  return rows;
}

export async function loadIncident(id: string, signal: AbortSignal): Promise<Incident> {
  if (!uuid.test(id)) throw new Error('Invalid incident ID.');
  const row = parseIncident(await request(`/${id}`, signal));
  if (row.id !== id) throw new Error('Unexpected incident identity.');
  return row;
}

export async function transitionIncident(id: string, action: 'acknowledge' | 'resolve', signal: AbortSignal): Promise<Incident> {
  if (!uuid.test(id) || !['acknowledge', 'resolve'].includes(action)) throw new Error('Invalid incident action.');
  const row = parseIncident(await request(`/${id}/${action}`, signal, 'POST'));
  if (row.id !== id || row.state !== (action === 'acknowledge' ? 'acknowledged' : 'resolved')) {
    throw new Error('Action result could not be confirmed. Reload the incident before retrying.');
  }
  return row;
}
