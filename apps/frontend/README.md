# Rook service dashboard

Minimal React/TypeScript dashboard for the existing Rook metrics API. Requires
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
