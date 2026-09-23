# Second real telemetry source: portable HTTP

This small Python HTTP workload demonstrates portability without implementing a
business application. It uses only the standard library, exposes Prometheus text
format 0.0.4 at `/metrics`, and measures actual `/work` requests with a monotonic
clock. Counters, duration sums and cumulative histogram buckets are updated only
by executed requests. Scrapes and failure-control calls are not counted. No status
series exists until that status has actually occurred. In particular, absence of
5xx observations remains insufficient evidence, not a fabricated zero error ratio.

`POST /failure/on` makes subsequent `/work` requests return HTTP 503 for at most
120 seconds; `/failure/off` restores HTTP 200 immediately. Failure controls do not
directly change counters, create incidents, or write deployment events. This is a
local-only demonstration server, not a production HTTP server. Published ports
are loopback-only. Do not expose these unauthenticated controls publicly.

## Adapter and profiles

`rook_backend.telemetry.TelemetryAdapter` defines `metrics(service)` and `close()`.
The existing Prometheus adapter implements it, returning the same `ServiceMetrics`
contract for both sources. API and worker own independent HTTP clients, with the
existing bounded timeout, request deadline, five-minute window, and source-sample
freshness checks. Every query for a snapshot shares one evaluation timestamp.

Reviewed profiles in `telemetry_profiles.py` own instrument names, identity/status
labels and query construction. Both require counters and classic histogram buckets
measured in seconds. They do not guess alternative instruments or units. Native
histograms, summaries, arbitrary OpenMetrics instruments and other query languages
are not supported by these two profiles. Add an explicit tested adapter/profile
for a different contract. Missing series remain null/insufficient; old evidence is
stale; connection/protocol failures return generic HTTP 503.

| Profile | Request counter | Duration buckets | Identity / status labels |
|---|---|---|---|
| `otel-demo` (default) | `http_server_request_duration_seconds_count` | `http_server_request_duration_seconds_bucket` | `service_name`, `service_namespace`, `http_response_status_code` |
| `local-http` | `local_http_requests_total` | `local_http_request_duration_seconds_bucket` | `app`, `namespace`, `code` |

`ROOK_TELEMETRY_SOURCES` is an operator-owned JSON map from service names to
`{"profile":"local-http","url":"http://portable-prometheus:9090"}`. The API caller
can only select a safe service name, never a URL or PromQL. Unmapped services keep
using `ROOK_PROMETHEUS_URL` and the original Demo profile. An unset default URL
returns unavailable for unmapped services; it never redirects them to another source.
The map accepts at most 20 entries and rejects unknown profiles/fields.

This milestone preserves one configured namespace (`ROOK_PROMETHEUS_NAMESPACE`)
and environment per Rook installation. Both local workloads use that same namespace
(`opentelemetry-demo` by default), with distinct service names. This is an identity
scope, not a claim that the second server is part of the external Demo. If you
change the namespace, change `WORKLOAD_NAMESPACE` too. Service-name collisions
across sources and multi-environment routing are not supported. Existing change
recording/correlation therefore keeps its original namespace/environment semantics.

The evaluator and store use normalized measurements; they contain no source-specific
metric names. Incident query references come from the adapter rather than being
reconstructed as Demo queries. No raw telemetry is stored in PostgreSQL. This
milestone does not migrate or relabel historical incidents.

## Run alongside the existing Demo

Run from the Rook repository root in PowerShell, with the existing `.env` and Demo
network prepared. Do not restart or edit the Demo. First confirm ports 8082 and
9092 are free. Keep using the existing Rook Compose project name (`rook-local`
below); do not accidentally start another PostgreSQL stack.

```powershell
$compose = @('compose', '-p', 'rook-local', '-f', 'docker-compose.yml',
    '-f', 'docker-compose.telemetry.yml', '-f', 'docker-compose.portable.yml',
    '--profile', 'worker')
docker @compose config --quiet
if ($LASTEXITCODE -ne 0) { throw 'Invalid Compose configuration; stop' }
# Rebuild the backend so API and worker both have the new adapter/profile code.
docker @compose up --build --detach api worker portable-http portable-prometheus
if ($LASTEXITCODE -ne 0) { throw 'Startup failed; inspect logs before proceeding' }
docker @compose ps
docker @compose exec portable-prometheus promtool check config /etc/prometheus/prometheus.yml
if ($LASTEXITCODE -ne 0) { throw 'Scrape configuration invalid' }
Invoke-RestMethod 'http://127.0.0.1:9092/api/v1/targets' |
    Select-Object -ExpandProperty data | Select-Object -ExpandProperty activeTargets |
    Select-Object health, scrapeUrl, lastError
```

For the second workload alone, omit `docker-compose.telemetry.yml` and set the
worker services to only `portable-http` in a separate local override. With the
supplied configuration it also evaluates `frontend`; absent Demo connectivity
correctly reports unavailable for that service. PostgreSQL and the new workload
remain on Rook's default network. Only API/worker join the Demo network when its
existing override is included. Demo ports 8080/9090 and Rook port 8001 are unchanged.

In a second PowerShell terminal at the repository root, issue real traffic for
six minutes, allowing scrapes and the five-minute query window to accumulate:

```powershell
& .\apps\api\.venv\Scripts\python.exe deploy/local/portable-http/traffic.py --seconds 360
if ($LASTEXITCODE -ne 0) { throw 'Traffic generator failed' }
```

After at least two successful scrapes, verify the API and source. A full five
minutes of traffic is preferable for a representative window. The dashboard
already accepts `portable-http` in its service input; no frontend change is needed.

```powershell
Invoke-RestMethod 'http://127.0.0.1:8001/services/portable-http/metrics' | ConvertTo-Json -Depth 8
Invoke-RestMethod 'http://127.0.0.1:8001/services/frontend/metrics' | ConvertTo-Json -Depth 8
Invoke-RestMethod 'http://127.0.0.1:8001/health/live'
Invoke-RestMethod 'http://127.0.0.1:8001/health/ready'
```

## Controlled failure and recovery

Keep traffic running. This affects only the new workload. The worker evaluates
both services every 30 seconds by default. Allow at least two scrapes of the 503
series plus a worker sweep; do not infer detection from the failure-control response.
If the first six-minute traffic run has finished, start it again in the second
terminal before enabling failure.

```powershell
try {
    Invoke-RestMethod -Method Post 'http://127.0.0.1:8082/failure/on'
    curl.exe --silent --show-error --write-out "`nHTTP %{http_code}`n" 'http://127.0.0.1:8082/work'
    Start-Sleep -Seconds 45
    Invoke-RestMethod 'http://127.0.0.1:8001/services/portable-http/metrics' | ConvertTo-Json -Depth 8
    Invoke-RestMethod 'http://127.0.0.1:8001/incidents' |
        Where-Object service_name -eq 'portable-http' | ConvertTo-Json -Depth 8
    docker @compose logs --tail 20 worker
} finally {
    Invoke-RestMethod -Method Post 'http://127.0.0.1:8082/failure/off'
}
curl.exe --silent --show-error --write-out "`nHTTP %{http_code}`n" 'http://127.0.0.1:8082/work'
& .\apps\api\.venv\Scripts\python.exe deploy/local/portable-http/traffic.py --seconds 360
Invoke-RestMethod 'http://127.0.0.1:8001/services/portable-http/metrics' | ConvertTo-Json -Depth 8
```

Confirm measured error evidence breaches the configured threshold and a persisted
incident exists; repeated evaluations must retain its ID. Recovery to HTTP 200 is
immediate, but errors remain in the rolling window until they age out. Once the
observed 503 counter has a zero rate with sufficient fresh samples, an error ratio
of zero is a measured value. Incidents still require explicit operator resolution;
do not resolve early and mistake a new later breach for failed deduplication.

To compare Prometheus at the API's exact evaluation time:

```powershell
$snapshot = Invoke-RestMethod 'http://127.0.0.1:8001/services/portable-http/metrics'
$query = 'sum(rate(local_http_requests_total{app="portable-http",namespace="opentelemetry-demo"}[5m]))'
$time = $snapshot.evaluation_timestamp.ToString([Globalization.CultureInfo]::InvariantCulture)
Invoke-RestMethod ('http://127.0.0.1:9092/api/v1/query?time=' + $time + '&query=' + [uri]::EscapeDataString($query))
```

Use the reviewed profile's p95/error expressions for the other measurements.
Prometheus evaluation time is not source freshness time: Rook separately checks
the latest sample of every contributor in the five-minute range. As before, series
that disappeared entirely outside that range cannot be identified by this query.

To stop only this addition, retain data and leave the Demo/database untouched:

```powershell
docker @compose stop portable-http portable-prometheus
```

Rook will then report this source unavailable or stale as appropriate. To remove
its route, recreate API/worker using the original Compose files without the portable
override. Never use `down --volumes` or Docker prune for this exercise.

## Validation and provenance

Unit tests use explicitly test-only Prometheus protocol fixtures. A separate test
starts an actual loopback HTTP server and verifies requests, 503 failures, recovery,
counts and cumulative latency buckets; it does not manufacture a Prometheus response
or seed product records. Docker-independent tests do not establish end-to-end
scraping, live PromQL, or PostgreSQL incident persistence for this source.

Current verification: 120 backend tests passed, one PostgreSQL integration test
was skipped, and two dependency deprecation warnings were reported. All 21 frontend
tests and TypeScript checks passed without frontend changes. Python syntax, TOML,
YAML, OpenAPI, whitespace and the merged Compose configuration passed. Locked sync
resolved the existing lock but failed downloading the Hatchling build dependency
from PyPI with connection-refused error 10061. No dependencies or lockfile changed.
The loopback workload test passed with actual HTTP 200/503/recovery responses.
Docker engine access was denied in this session, so image builds, Prometheus
scrapes, live queries and PostgreSQL incidents from this source remain unverified.
Run the commands above from a Docker-enabled terminal to complete that verification.

Python reuses the backend's `3.13.13-slim-bookworm` pin. Prometheus is pinned to
`prom/prometheus:v3.2.1` ([upstream release](https://github.com/prometheus/prometheus/releases/tag/v3.2.1)).
The text exposition follows the [official format](https://prometheus.io/docs/instrumenting/exposition_formats/).
Tags are version pins, not immutable digests. No backend dependencies are added.
