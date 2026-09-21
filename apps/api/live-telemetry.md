# Read-only live service metrics

`GET /services/{service_name}/metrics` queries the user-observed HTTP instruments
`http_server_request_duration_seconds_count` and
`http_server_request_duration_seconds_bucket`. Service names and the configured
namespace accept 1-128 ASCII letters, digits, dots, underscores, or hyphens,
starting with a letter or digit. Callers cannot supply a URL, namespace, time,
window, or PromQL. Each response uses one server-selected Unix evaluation time
for all queries, a fixed 300-second window, and explicit units and statuses.

Settings (all prefixed `ROOK_`):

| Setting | Default | Purpose |
|---|---|---|
| `PROMETHEUS_URL` | unset | Optional HTTP(S) backend; unset returns generic 503 |
| `PROMETHEUS_NAMESPACE` | `opentelemetry-demo` | Validated identity selector |
| `PROMETHEUS_TIMEOUT_SECONDS` | 2 | Per HTTP operation and upstream query timeout, 0.05-10 seconds |
| `PROMETHEUS_DEADLINE_SECONDS` | 8 | Overall query sequence deadline, 0.05-30 seconds |
| `PROMETHEUS_FRESHNESS_SECONDS` | 120 | Maximum source age, 1-300 seconds |

The async client belongs to application lifespan and closes on shutdown. Redirects
and implicit proxy environment settings are disabled. Responses are bounded to
2 MB each and connections to ten per process. Prometheus errors, malformed or
partial responses, disabled configuration, and timeouts return HTTP 503
`{"status":"unavailable"}` without connection details. API liveness and database
readiness do not depend on Prometheus. No telemetry is persisted.

## Evidence semantics and limits

For each metric, `value`, `unit`, `status`, `reason`, and
`oldest_latest_sample_timestamp` are returned. The timestamp is the minimum of
the latest samples across contributing series, not the oldest historical sample
in the window. `measured` is not a health assessment.
Request rate is a summed counter rate; latency is an estimated histogram p95 in
seconds; error ratio is the 5xx counter rate divided by all requests, from 0 to 1.

The API also requests raw five-minute counter and bucket matrices. It takes the
latest actual sample timestamp of **each** returned series, then the oldest of
those timestamps. An old contributor makes the measurement `stale` with a null
value, even if other contributors are fresh. Request-rate freshness uses all
counter series; p95 uses all bucket series; error ratio uses all denominator
counter series, including its error subset. Query evaluation timestamps are not
used as sample timestamps.

Every returned contributor must have at least two valid samples. Missing results,
missing 5xx series, zero/missing request rate, invalid numeric values, and inadequate
samples produce null with `insufficient_data`; no zero-fill is applied. Thus the
user-observed empty 5xx query is not presented as zero errors. A measured zero
error ratio is possible only with an actual error counter series that did not
increase and sufficient nonzero total traffic.

Freshness covers contributors observed in the five-minute matrix, not a complete
inventory: series absent for the entire window cannot be detected, and older
evidence is reported as insufficient rather than reconstructed. Two samples are
the computational minimum, not proof of five minutes of continuous coverage.
Collector buffering, clock skew, missing buckets, and partial instrumentation
can limit interpretation. There is no completeness or causal claim. Versions
are not filtered, so simultaneous versions within the same service/namespace are
aggregated. The full five-minute matrices are used transiently, then discarded.

## Validation record

The user verified Demo startup and frontend telemetry; see the
[Demo runbook](../../deploy/local/otel-demo/README.md). Those observations justify
the metric names but do not verify this new API. Final local verification with
`.venv\Scripts\python.exe -m pytest` passed 47 tests with three warnings: two
existing dependency deprecations (Starlette/httpx and AnyIO BlockingPortal) and
one pytest cache write-permission warning. There were no test failures.
Compose configuration validation passed for the Rook merge (without interpolation)
and the pinned Demo merge. These are client-side checks, not Docker runtime tests.
API-to-Demo runtime checks remain pending; the running Demo was not restarted.

`httpx` must be declared as a runtime dependency: previously it was dev-only and
would be absent from the `--no-dev` Docker image. Its version constraint is
unchanged. The requested locked sync failed at default-cache initialization
with access denied (`os error 5`). Earlier lock generation was blocked too:
using the project cache, PyPI connection failed with `os error 10061`. Offline
resolution also failed because FastAPI metadata was not cached. `uv.lock` remains
unchanged and must be regenerated before locked CI or Docker builds can pass.
No lockfile was handwritten. Complete the following steps in your terminal.
After regeneration, inspect `git diff -- apps/api/uv.lock` from the root: only
the runtime httpx dependency and requirement should be added; stop if unrelated
package versions change. Do not use an upgrade option.

## PowerShell completion and runtime verification

From Rook root, with the Demo already running on `opentelemetry-demo`, use your
normal Docker-enabled terminal. Stop on errors. Keep the existing Rook Compose
project name if you previously set one; these commands use the root default.
Keep existing database credentials and volumes.

```powershell
Push-Location apps/api
try {
    uv lock --managed-python
    if ($LASTEXITCODE -ne 0) { throw 'Lock generation failed; stop' }
    uv sync --locked --managed-python
    if ($LASTEXITCODE -ne 0) { throw 'Locked install failed; stop' }
    .\.venv\Scripts\python.exe -m pytest
    if ($LASTEXITCODE -ne 0) { throw 'Tests failed; stop' }
} finally { Pop-Location }

if (-not (Test-Path .env)) { Copy-Item .env.example .env }
$rookCompose = @('compose', '-f', 'docker-compose.yml', '-f', 'docker-compose.telemetry.yml')
docker @rookCompose config --quiet
if ($LASTEXITCODE -ne 0) { throw 'Compose validation failed; stop' }
docker @rookCompose build api
if ($LASTEXITCODE -ne 0) { throw 'Build failed; stop' }
docker @rookCompose up --detach --wait --wait-timeout 120
if ($LASTEXITCODE -ne 0) { throw 'Startup failed; stop' }
docker @rookCompose ps

$result = Invoke-RestMethod http://127.0.0.1:8001/services/frontend/metrics -TimeoutSec 15
$result | ConvertTo-Json -Depth 8
Invoke-RestMethod http://127.0.0.1:8001/health/live
Invoke-RestMethod http://127.0.0.1:8001/health/ready

# Use exactly the API's query builders and returned evaluation time.
$querySource = @'
import json
from rook_backend.telemetry import queries
print(json.dumps(queries("frontend", "opentelemetry-demo")))
'@
$planJson = $querySource | & .\apps\api\.venv\Scripts\python.exe -
if ($LASTEXITCODE -ne 0) { throw 'Query generation failed; stop' }
$plan = $planJson | ConvertFrom-Json
$at = ([double]$result.evaluation_timestamp).ToString('R', [Globalization.CultureInfo]::InvariantCulture)
foreach ($entry in $plan.PSObject.Properties) {
    $query = [Uri]::EscapeDataString($entry.Value)
    $direct = Invoke-RestMethod "http://127.0.0.1:9090/api/v1/query?query=$query&time=$at" -TimeoutSec 10
    $entry.Name
    $direct | ConvertTo-Json -Depth 12
}
```

Compare finite measured values at this timestamp, allowing floating-point rounding.
An empty error result must match null/insufficient_data. Inspect matrices when
Rook suppresses an otherwise calculable value for staleness or inadequate samples.
Late-arriving telemetry can change a later query at the same historical timestamp;
run the comparison promptly and record any difference rather than treating it as
proven agreement. Browse the storefront to produce additional real requests and
repeat after sufficient export/sample time. Do not inject workload failures.

The optional override adds the Demo network to the API while retaining `default`;
PostgreSQL stays only on `default`. To verify unavailable behavior without stopping
the workload, disconnect only this Rook API from the Demo network, then reconnect:

```powershell
$apiId = docker @rookCompose ps -q api
if ($LASTEXITCODE -ne 0 -or -not $apiId) { throw 'API container not found' }
docker network disconnect opentelemetry-demo $apiId
if ($LASTEXITCODE -ne 0) { throw 'Disconnect failed; stop' }
try {
    curl.exe --silent --show-error --max-time 15 --write-out "`n%{http_code}`n" http://127.0.0.1:8001/services/frontend/metrics
    # Expect generic unavailable and HTTP 503; liveness must stay 200.
    Invoke-RestMethod http://127.0.0.1:8001/health/live
} finally {
    docker network connect opentelemetry-demo $apiId
    if ($LASTEXITCODE -ne 0) { throw 'Reconnect failed; restore the API network before continuing' }
}
Invoke-RestMethod http://127.0.0.1:8001/services/frontend/metrics
# When finished, stop only Rook; preserve containers and volumes:
# docker @rookCompose stop
```
