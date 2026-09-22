# Rook service dashboard

React/TypeScript dashboard for the existing Rook metrics and incident APIs. Requires
Node 24.15+ and npm. Run from the repository root in PowerShell:

```powershell
Set-Location apps/frontend
npm ci
if ($LASTEXITCODE -ne 0) { throw 'Install failed' }
npm test
if ($LASTEXITCODE -ne 0) { throw 'Tests failed' }
npm run build
if ($LASTEXITCODE -ne 0) { throw 'Build failed' }
npm run dev
```

Open `http://127.0.0.1:5173`. Keep the existing Rook API running at
`http://127.0.0.1:8001`; no backend or CORS change is required. Vite forwards
`/api/services/{service}/metrics` to `/services/{service}/metrics` on port 8001.
The dev server binds to loopback and fails if 5173 is occupied. Stop only this
foreground dev server with Ctrl+C. The proxy is development-only; the build in
`dist/` would require equivalent `/api` routing when hosted. No deployment is
included.

## Incident register

The register loads `GET /incidents?limit=50&offset=...` through the existing `/api`
proxy, showing all services, newest first, with previous/next pages. Selecting a
record loads `GET /incidents/{id}`. Metrics refresh (manual or opt-in auto-refresh)
also refreshes incidents and the selected detail; incident reload is available
independently. Requests time out after 12 seconds, and obsolete reads are canceled.

Details show ID, service/namespace, state, reason, observed value/unit, optional
threshold and UTC evidence/opened/evaluation timestamps. **The backend has no
state-update timestamp.** “State updated” therefore says “Not provided by API”;
the latest breach evaluation is labeled separately and never presented as the time
of acknowledgment or resolution. Evidence quality refers to the historical breach,
not the current service state. No incident is inferred from metrics in the browser.

Open incidents offer acknowledgment and resolution; acknowledged incidents offer
resolution; resolved incidents disable both actions. Actions POST to the existing
`/incidents/{id}/acknowledge` or `/resolve` route. Controls disable while a request
is pending. The UI reloads authoritative state after an action, including failure;
it never applies an optimistic state change. HTTP 409 has an explicit conflict
message and asks for reload. A network failure can mean an action was applied but
its response was lost, so it is never automatically retried. Resolution is an
operator action, not proof of recovery.

Loading, empty, request-error and unavailable responses are shown explicitly.
An empty register does not mean healthy services. No application fixtures, sample
incidents or fabricated metric values are used. New components share the existing
theme variables, focus styles, responsive rules and reduced-motion behavior.

### Nearby changes

Incident details display **Nearby changes — temporal correlation only** from the
existing incident list/detail responses. Each event shows its ID, service and
namespace, version/deployment identifier, environment, source, observed UTC time,
and the API's display metadata (kind and summary). The window is the server's
configured number of seconds before and after incident opening, not a browser
calculation. Temporal proximity does not establish an explanation for an incident.

Available empty results, missing incident timestamps, unavailable/malformed
enrichment, loading, and detail-request errors are distinct states. Missing
enrichment never becomes an empty result. Truncated responses explicitly indicate
that only the 20 most recent events are shown. Reload incidents or refresh metrics
to reload selected details and changes. Acknowledgment and resolution are unchanged.

Correlation milestone validation: 21 unit tests, TypeScript, production build,
and the Edge browser check passed. Live metrics and an existing incident were read;
that incident had no nearby changes. Populated/multiple events, loading and error
states, and transitions used browser-test-only fixtures with no database writes.
Dark desktop and light mobile screenshots were inspected; mobile overflow,
keyboard focus, and reduced-motion checks passed. No dependencies were added.

### Browser verification commands

With Vite and the API already running, `npm run test:browser` uses the installed
Windows Microsoft Edge in a separate headless test profile. It needs no additional
dependencies. Set `$env:ROOK_FRONTEND_URL = 'http://127.0.0.1:5174'` if using a
different Vite port; `EDGE_PATH` can override the installed executable path. This
is separate from `npm test`, which does not require a browser or backend.

The browser check first reads the real metrics and incident APIs, then uses
test-only response fixtures inside that browser to exercise incident details,
all states/actions, HTTP 409 and unavailable/empty states without database writes.
It also verifies manual refresh, theme switching, mobile overflow, reduced motion
and keyboard focus. Screenshots and disposable Edge profiles remain under ignored
`node_modules/.cache`; no test assets enter the application build.

Incident milestone validation: 18 unit tests and the separate Edge browser check
passed, along with TypeScript and production build checks. Live request rate and
p95 remained measured, with null/insufficient error evidence. The live incident
list was empty, so populated state/action browser checks used test-only fixtures;
no live incident was created or changed. Dark desktop and light mobile views were
visually inspected. No backend behavior, dependencies or deployment was changed.

The page requests `frontend` on load. Submit a safe service name to load or refresh
its snapshot. Requests have a 12-second deadline; changing service cancels the
previous request and prevents late responses replacing the current service.
Refresh clears the previous snapshot so an API failure cannot leave old values
looking current. Refresh is manual by default. Opt into auto-refresh to request
another snapshot 30 seconds after each response completes, including errors.
Requests do not overlap; switching auto-refresh off cancels its pending timer.
Manual refresh remains available. Auto-refresh starts off on each page load.

The dashboard defaults to a dark glass theme with a custom faceted SVG rook.
The light/dark toggle saves your preference locally when browser storage is
available. Keyboard focus is visible, and reduced-motion preferences disable
decorative animation and transitions. No external visual assets are loaded.

Each card displays the returned value, unit, status, reason and UTC evidence
timestamp. Null values display a dash, never zero. Error ratio retains its API
unit (ratio, 0-1), rather than silently converting to percent. Evidence time is
`oldest_latest_sample_timestamp`: the oldest of each contributing series' latest
samples. Evaluation time is separate. Measured is not a service health claim;
stale and insufficient data have text labels as well as distinct colors.

## Verify with real telemetry

1. Open the dashboard with the API and Demo already running. Inspect the browser
   Network response for `/api/services/frontend/metrics` and compare all card
   values, units, reasons and timestamps. Displayed values round to six significant
   digits. No historical observations are hardcoded.
2. If 5xx series are absent, the error ratio should remain a dash with the API's
   `Insufficient data` status and reason, not 0% or healthy.
3. Enter a service with no collected telemetry to inspect the empty-measurement
   state. Invalid names must show inline validation without sending a request.
4. Use browser request blocking for `/api/services/*` and refresh to inspect the
   API-error state; unblock and retry. Use network throttling to inspect loading.
   No workload shutdown or failure injection is necessary.
5. Inspect both themes at narrow/mobile width and navigate using the keyboard.
   Enable reduced motion in your system or browser and check that animation stops.
6. Enable auto-refresh and observe a new Network request after 30 seconds following
   a completed response. Disable it and confirm no further scheduled requests.

`npm run check` runs TypeScript checks. `npm test` uses Node's built-in runner
for selector safety, response validation, null/zero semantics and HTTP handling;
its protocol fixtures exist only in the test file. These unit checks do not
establish browser rendering or live API connectivity.

## Completed validation

Eight unit tests passed, and TypeScript checking plus the Vite production build
succeeded. Browser checks against the live backend passed in headless Microsoft
Edge, with dark, light and mobile screenshots visually inspected. Real request
rate and p95 latency appeared, while missing server-error evidence remained
null/insufficient data. No mock telemetry was used in the browser checks.

Service validation, manual refresh, a blocked-request error and retry recovery,
and an actual service without telemetry were checked. Theme switching, keyboard
focus, reduced-motion behavior and mobile overflow checks passed. Auto-refresh
on/off was checked with accelerated browser timers while requests still reached
the real API. Unit-test protocol fixtures remain test-only.
