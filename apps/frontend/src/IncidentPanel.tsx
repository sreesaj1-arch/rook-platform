import { useEffect, useRef, useState } from 'react';
import { evidenceTime } from './api';
import { canAcknowledge, canResolve, loadIncident, loadIncidents, stateLabels, transitionIncident } from './incidents';
import type { Incident } from './incidents';

type Load<T> = { kind: 'loading' } | { kind: 'error'; message: string } | { kind: 'loaded'; data: T };
const message = (error: unknown) => error instanceof Error ? error.message : 'Incident request failed.';

export function IncidentEvidence({ incident }: { incident: Incident }) {
  return <dl className="incident-evidence">
    <div><dt>Incident ID</dt><dd>{incident.id}</dd></div>
    <div><dt>Service / namespace</dt><dd>{incident.service_name} / {incident.service_namespace}</dd></div>
    <div><dt>Reason</dt><dd>{incident.reason}</dd></div>
    <div><dt>Observed value / threshold</dt><dd>{incident.value} {incident.unit} / {incident.threshold ?? 'Not available'} {incident.threshold !== null ? incident.unit : ''}</dd></div>
    <div><dt>Evidence timestamp (UTC)</dt><dd>{evidenceTime(incident.oldest_latest_sample_timestamp)}</dd></div>
    <div><dt>Created / opened (UTC)</dt><dd>{evidenceTime(incident.opened_at)}</dd></div>
    <div><dt>Latest breach evaluation (UTC)</dt><dd>{evidenceTime(incident.evaluation_timestamp)}</dd></div>
    <div><dt>State updated (UTC)</dt><dd>Not provided by API</dd></div>
    <div><dt>Evidence quality when recorded</dt><dd>{incident.data_quality} — historical breach evidence, not current health</dd></div>
  </dl>;
}

export function Incidents({ refreshToken }: { refreshToken: number }) {
  const [list, setList] = useState<Load<Incident[]>>({ kind: 'loading' });
  const [detail, setDetail] = useState<Load<Incident>>({ kind: 'loading' });
  const [selected, setSelected] = useState<string | null>(null);
  const [offset, setOffset] = useState(0);
  const [revision, setRevision] = useState(0);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState('');
  const [actionFailed, setActionFailed] = useState(false);
  const actionController = useRef<AbortController | null>(null);
  useEffect(() => () => actionController.current?.abort(), []);

  useEffect(() => {
    if (busy) return;
    const controller = new AbortController();
    setList({ kind: 'loading' });
    loadIncidents(controller.signal, offset).then(data => {
      if (!controller.signal.aborted) setList({ kind: 'loaded', data });
    }).catch(error => { if (!controller.signal.aborted) setList({ kind: 'error', message: message(error) }); });
    return () => controller.abort();
  }, [refreshToken, revision, offset, busy]);

  useEffect(() => {
    if (!selected || busy) return;
    const controller = new AbortController();
    setDetail({ kind: 'loading' });
    loadIncident(selected, controller.signal).then(data => {
      if (!controller.signal.aborted) { setDetail({ kind: 'loaded', data }); }
    }).catch(error => { if (!controller.signal.aborted) setDetail({ kind: 'error', message: message(error) }); });
    return () => controller.abort();
  }, [selected, refreshToken, revision, busy]);

  async function act(action: 'acknowledge' | 'resolve') {
    if (!selected || busy || actionController.current) return;
    const controller = new AbortController();
    actionController.current = controller;
    setBusy(true); setNotice('');
    try {
      const result = await transitionIncident(selected, action, controller.signal);
      if (!controller.signal.aborted) setNotice(`Incident ${stateLabels[result.state].toLowerCase()}.`);
    } catch (error) {
      if (!controller.signal.aborted) { setNotice(message(error)); setActionFailed(true); }
    } finally {
      actionController.current = null;
      if (!controller.signal.aborted) { setBusy(false); setRevision(value => value + 1); }
    }
  }

  return <section className="incidents-section" aria-label="Incidents">
    <div className="section-heading"><h2>Incident register</h2><button disabled={busy} onClick={() => { setActionFailed(false); setNotice(''); setRevision(value => value + 1); }}>Reload incidents</button></div>
    <p className="incident-context">All services · persisted incidents only. Missing telemetry does not create an incident. Resolved is an operator state, not proof of recovery.</p>
    {notice && <p role={actionFailed ? 'alert' : 'status'} className={`notice ${actionFailed ? 'error' : ''}`}>{notice}</p>}
    <div aria-busy={list.kind === 'loading'}>
      {list.kind === 'loading' && <p role="status" className="notice">Loading incidents…</p>}
      {list.kind === 'error' && <p role="alert" className="notice error">{list.message}</p>}
      {list.kind === 'loaded' && list.data.length === 0 && <p role="status" className="notice">{offset === 0 ? 'No incidents recorded.' : 'No incidents on this page.'} This does not establish service health.</p>}
      {list.kind === 'loaded' && <ul className="incident-list">{list.data.map(incident => <li key={incident.id}>
        <button className="incident-select" disabled={busy} aria-expanded={selected === incident.id} aria-controls="incident-detail" onClick={() => {
          setDetail({ kind: 'loading' }); setSelected(incident.id); setNotice(''); setActionFailed(false); setRevision(value => value + 1);
        }}><span><strong>{incident.service_name}</strong><span className="incident-id">{incident.id}</span><span>{incident.reason}</span></span>
          <span className={`badge incident-${incident.state}`}>{stateLabels[incident.state]}</span>
        </button>
      </li>)}</ul>}
    </div>
    <nav className="incident-pagination" aria-label="Incident pages">
      <button disabled={busy || offset === 0} onClick={() => { setOffset(value => value - 50); setSelected(null); }}>Previous</button>
      <span>Page {offset / 50 + 1} · up to 50 records</span>
      <button disabled={busy || list.kind !== 'loaded' || list.data.length < 50 || offset >= 100000} onClick={() => { setOffset(value => value + 50); setSelected(null); }}>Next</button>
    </nav>
    <div id="incident-detail" aria-busy={Boolean(selected) && (detail.kind === 'loading' || busy)}>
      {selected && <article className="card incident-detail"><h3>Incident details</h3>
        {detail.kind === 'loading' && <p role="status">Loading incident details…</p>}
        {detail.kind === 'error' && <p role="alert" className="notice error">{detail.message}</p>}
        {detail.kind === 'loaded' && <>
          <p><span className={`badge incident-${detail.data.state}`}>{stateLabels[detail.data.state]}</span></p>
          <IncidentEvidence incident={detail.data} />
          <div className="incident-actions">
            <button disabled={busy || actionFailed || !canAcknowledge(detail.data.state)} onClick={() => void act('acknowledge')}>Acknowledge</button>
            <button disabled={busy || actionFailed || !canResolve(detail.data.state)} onClick={() => void act('resolve')}>Resolve incident</button>
          </div>
          {busy && <p role="status">Applying action…</p>}
        </>}
      </article>}
    </div>
  </section>;
}
