import { StrictMode, useEffect, useState } from 'react';
import type { FormEvent } from 'react';
import { createRoot } from 'react-dom/client';
import { displayValue, evidenceTime, loadSnapshot, metricNames, safeService } from './api';
import type { Snapshot } from './api';
import './styles.css';

type State = { kind: 'loading' } | { kind: 'error'; message: string } | { kind: 'loaded'; data: Snapshot | null };
const titles = { request_rate: 'Request rate', p95_latency: 'p95 latency', error_ratio: 'Server error ratio' };
const labels = { measured: 'Measured', stale: 'Stale', insufficient_data: 'Insufficient data' };

function RookMark() {
  return <svg viewBox="0 0 200 230" fill="none" aria-hidden="true" className="rook-mark">
    <path d="M100 210 21 169 100 128 179 169Z" stroke="#65d4df" strokeOpacity=".4" strokeDasharray="3 5" />
    <path d="m42 163 58-30 58 30-58 31Z" fill="#183e56" stroke="#65d4df" strokeOpacity=".5" />
    <path d="m42 163 58 31v15l-58-30Z" fill="#173041" /><path d="m100 194 58-31v16l-58 30Z" fill="#0c202e" />
    <path d="m62 153 11-67 27 14v72Z" fill="#4cbbc8" /><path d="m100 100 27-14 11 67-38 19Z" fill="#1b677e" />
    <path d="m56 66 44 23v25L56 91Z" fill="#78e2df" /><path d="m100 89 44-23v25l-44 23Z" fill="#287f99" />
    <path d="m56 66 44-23 44 23-44 23Z" fill="#b9f5e9" />
    <path d="m56 66 0-24 15-8v24l-15 8Zm29 15V57l15-8v24l-15 8Zm30 0V57l15-8v24l-15 8Z" fill="#92eae4" />
    <path d="m56 42 15-8 15 8-15 8Zm29 15 15-8 15 8-15 8Zm30 0 15-8 14 8-14 8Z" fill="#d3fff4" />
    <path d="m71 50 15-8v24l-15 8Zm29 15 15-8v24l-15 8Zm30 0 14-8v24l-14 8Z" fill="#27778d" />
    <path d="m84 125 0 24m0-35v3" stroke="#d3fff4" strokeWidth="3" strokeLinecap="round" />
  </svg>;
}

function App() {
  const [theme, setTheme] = useState<'dark' | 'light'>(() => {
    try { return localStorage.getItem('rook-theme') === 'light' ? 'light' : 'dark'; }
    catch { return 'dark'; }
  });
  const [autoRefresh, setAutoRefresh] = useState(false);
  const [input, setInput] = useState('frontend');
  const [service, setService] = useState('frontend');
  const [revision, setRevision] = useState(0);
  const [validation, setValidation] = useState('');
  const [state, setState] = useState<State>({ kind: 'loading' });
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    try { localStorage.setItem('rook-theme', theme); } catch { /* Storage is optional. */ }
  }, [theme]);
  useEffect(() => {
    if (!autoRefresh || state.kind === 'loading') return;
    const timer = window.setTimeout(() => setRevision((value) => value + 1), 30000);
    return () => window.clearTimeout(timer);
  }, [autoRefresh, state, revision]);
  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    const timer = window.setTimeout(() => controller.abort(), 12000);
    setState({ kind: 'loading' });
    loadSnapshot(service, controller.signal)
      .then((data) => { if (active) setState({ kind: 'loaded', data }); })
      .catch((error: unknown) => {
        if (active) setState({ kind: 'error', message: controller.signal.aborted
          ? 'The request timed out. Retry when the API is available.'
          : error instanceof Error ? error.message : 'Unable to load metrics.' });
      }).finally(() => window.clearTimeout(timer));
    return () => { active = false; controller.abort(); window.clearTimeout(timer); };
  }, [service, revision]);

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const next = input.trim();
    if (!safeService(next)) {
      setValidation('Use 1–128 letters, numbers, dots, underscores or hyphens. Start with a letter or number.');
      return;
    }
    setValidation('');
    setState({ kind: 'loading' });
    setService(next);
    setRevision((value) => value + 1);
  }
  const data = state.kind === 'loaded' ? state.data : null;
  const empty = state.kind === 'loaded' && (!data || metricNames.every((name) => !data.metrics[name] || data.metrics[name]?.value === null));
  return <>
    <a className="skip-link" href="#main">Skip to service evidence</a>
    <div className="technical-background" aria-hidden="true" />
    <header className="topbar"><a className="brand" href="/" aria-label="Rook home"><span className="brand-symbol"><RookMark /></span> ROOK<span className="brand-caption">OBSERVABILITY</span></a><div className="header-tools"><span className="top-label">Local workspace</span><button className="theme-toggle" aria-label="Light theme" aria-pressed={theme === 'light'} onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}><span aria-hidden="true">{theme === 'dark' ? '☀' : '☾'}</span> {theme === 'dark' ? 'Light mode' : 'Dark mode'}</button></div></header>
    <main id="main">
      <div className="intro"><div><p className="eyebrow"><span /> OPERATIONS / SERVICE EVIDENCE</p><h1>Clarity in every<br /><em>signal.</em></h1><p className="lede">Real measurements. Visible uncertainty.<br />A focused view of your running services.</p><div className="hero-tags"><span>OpenTelemetry workload</span><span>Prometheus evidence</span></div></div><div className="rook-scene" aria-hidden="true"><div className="rook-halo" /><RookMark /><span className="scene-label">OBSERVE / UNDERSTAND</span></div></div>
      <section className="toolbar" aria-label="Service selection">
        <form onSubmit={submit} noValidate><div className="field"><label htmlFor="service">Service name</label><input id="service" value={input} onChange={(event) => setInput(event.target.value)} maxLength={128} spellCheck={false} aria-invalid={Boolean(validation)} aria-describedby={validation ? 'validation' : undefined} /></div><button type="submit">{state.kind === 'loading' ? 'Load service' : 'Refresh metrics'} <span aria-hidden="true">↗</span></button></form>
        <div className="refresh-controls"><button className="auto-toggle" type="button" aria-pressed={autoRefresh} onClick={() => setAutoRefresh((value) => !value)}><span className="switch" aria-hidden="true"><span /></span> Auto-refresh {autoRefresh ? 'on' : 'off'}</button><p className="window">5 minute window <span> / {autoRefresh ? '30s after each response' : 'Manual refresh'}</span></p></div>
      </section>
      {validation && <p id="validation" className="notice error" role="alert">{validation}</p>}
      <section aria-label="Service metrics" aria-busy={state.kind === 'loading'}>
        <div className="section-heading"><div className="service-title"><span className="service-icon" aria-hidden="true">◈</span><h2>{service}</h2><span>{data ? data.service_namespace : 'Service measurements'}</span></div><span className="section-caption">HTTP / LAST 5 MINUTES</span></div>
        {state.kind === 'loading' && <div className="notice" role="status">Loading measured evidence…</div>}
        {state.kind === 'error' && <div className="notice error" role="alert"><strong>Unable to load evidence</strong><p>{state.message}</p><button onClick={() => setRevision((value) => value + 1)}>Retry request</button></div>}
        {empty && <div className="notice" role="status">No usable measurements in this response. Missing evidence does not mean zero errors or a healthy service.</div>}
        {state.kind === 'loaded' && data && <>
          <div className="cards">{metricNames.map((name) => {
            const metric = data.metrics[name];
            return <article className={`card card-${name}`} key={name}><div className="card-heading"><h3>{titles[name]}</h3><span className={`badge ${metric?.status ?? 'insufficient_data'}`}><span className="status-dot" aria-hidden="true" />{metric ? labels[metric.status] : 'Not returned'}</span></div>
              <p className="value">{metric ? displayValue(metric) : '—'}</p><p className="unit">{metric?.unit ?? 'Unit not returned'}</p>
              <dl><dt>Reason</dt><dd>{metric?.reason ?? (metric ? 'None reported' : 'Metric not included in response')}</dd><dt>Evidence timestamp (UTC)</dt><dd>{evidenceTime(metric?.oldest_latest_sample_timestamp ?? null)}</dd></dl>
            </article>;
          })}</div>
          <p className="evaluated">Evaluated at <time>{evidenceTime(data.evaluation_timestamp)}</time> <span> / {autoRefresh ? 'Auto-refresh enabled · 30s after each response' : 'Manual snapshot · Auto-refresh off'}</span></p>
        </>}
      </section>
      <aside className="legend"><h2>Read the evidence</h2><p><strong>Measured</strong> means the API returned a measurement. <strong>Stale</strong> means a contributing source is too old. <strong>Insufficient data</strong> means the API cannot support a value.</p><p>The evidence timestamp is the oldest latest sample across contributing series. A missing error ratio stays empty; it is never replaced with zero. Ratios are shown as returned (0–1), not percentages.</p></aside>
      <footer>ROOK <span>Real telemetry. Explicit uncertainty.</span></footer>
    </main>
  </>;
}

createRoot(document.getElementById('root')!).render(<StrictMode><App /></StrictMode>);
