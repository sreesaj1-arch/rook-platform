# Background incident worker

The worker runs `python -m rook_backend.worker` in a separate process using the
same image and shared evaluator as the API. It never creates an incident from
stale, unavailable, missing or insufficient evidence. Generated HTTP traffic and
controlled failures are allowed: their telemetry comes from real running software.
Fabricated metrics, invented incident records and seeded demonstration incidents
are prohibited. Test fixtures belong only in tests.

## Start with Compose

Prerequisites: the root `.env` already configures the local PostgreSQL instance,
Docker is available, and the pinned [Demo](../../deploy/local/otel-demo/README.md)
is running on `opentelemetry-demo`. Run from the Rook repository root in PowerShell.
Use the existing project name (`rook-local` below) to avoid creating a second stack.

```powershell
$rookCompose = @('compose', '-p', 'rook-local', '-f', 'docker-compose.yml', '-f', 'docker-compose.telemetry.yml', '--profile', 'worker')
docker @rookCompose config --quiet
if ($LASTEXITCODE -ne 0) { throw 'Compose validation failed; stop' }
docker @rookCompose build api
if ($LASTEXITCODE -ne 0) { throw 'Image build failed; stop' }
docker @rookCompose up --detach --no-build --wait --wait-timeout 120 postgres api worker
if ($LASTEXITCODE -ne 0) { throw 'Startup failed; inspect status and logs before retrying' }
docker @rookCompose ps
docker @rookCompose logs --tail 50 worker
Invoke-RestMethod http://127.0.0.1:8001/health/live
Invoke-RestMethod http://127.0.0.1:8001/health/ready
```

The `worker` profile is opt-in. API and worker attach to both Rook's default
network and the Demo network through the telemetry override; PostgreSQL stays
on Rook's network with no published port. Only the API publishes port 8001 on
localhost. Omitting the telemetry override leaves Prometheus unconfigured, so
evaluations report unavailable rather than inventing observations.

## Configuration and scheduling

Worker settings are validated separately from API settings. The Compose file
passes the following variables from the shell or root `.env`:

| Environment variable | Default | Meaning |
|---|---|---|
| `ROOK_WORKER_SERVICES` | `["frontend"]` | JSON array of 1-20 unique, safe service names |
| `ROOK_WORKER_INTERVAL_SECONDS` | `30` | Wait after a completed sweep, from 1 to 3600 seconds |
| `ROOK_WORKER_ERROR_RATIO` | `0.05` | Strict breach threshold, ratio units 0-1 |
| `ROOK_WORKER_P95_SECONDS` | `0.5` | Strict breach threshold in seconds, greater than zero |

These defaults are rule configuration, not measured values. For example, before
startup set `$env:ROOK_WORKER_INTERVAL_SECONDS = '15'`. Recreate only the worker
with `docker @rookCompose up --detach --no-build worker` to apply configuration
changes. Removing a shell override does not change an already running container.

The worker also consumes the existing `ROOK_DB_*` and `ROOK_PROMETHEUS_*`
settings. Compose supplies database credentials and the telemetry override sets
`ROOK_PROMETHEUS_URL=http://prometheus:9090`. Other shared settings retain their
backend defaults unless explicitly passed to the process; arbitrary shell variables
are not automatically forwarded by Compose. Do not print resolved environments.

The first sweep starts immediately. Services run sequentially, then the worker
waits the configured interval; this is not a fixed start-to-start cadence or a
catch-up queue. A PostgreSQL transaction advisory lock prevents concurrent sweeps
while ownership is held; a competing worker skips a busy sweep. Existing incident
write locks and uniqueness constraints preserve deduplication and transitions.

Initialization checks/creates the initial incident schema idempotently. It does
not perform destructive migrations. Each service has a deadline of the Prometheus
deadline plus 12 seconds; the whole sweep is bounded by 15 seconds plus that budget
per service. An unavailable sweep waits before trying again. Logs report outcomes
without connection details. The heartbeat health check reports loop progress only:
`healthy` is not proof that Prometheus, PostgreSQL or the monitored service is healthy.

The evaluator retains its fixed five-minute measurement window and immediate
threshold behavior. Sustained violation/recovery rules remain planned. An outage
never resolves an incident; resolution remains an explicit operator action.

## Graceful shutdown

```powershell
docker @rookCompose stop worker
if ($LASTEXITCODE -ne 0) { throw 'Worker stop failed' }
docker @rookCompose logs --tail 20 worker
```

Compose sends SIGTERM and allows 20 seconds before forced termination. The worker
cancels pending work, exits the ownership transaction, closes HTTP/database
resources, removes its heartbeat and logs `worker stopped`. API, PostgreSQL, Demo
and volumes remain untouched. Start it again with `docker @rookCompose start worker`.
For a host process with reachable database/Prometheus configuration, run
`apps/api/.venv/Scripts/python.exe -m rook_backend.worker` from the repository root
and stop with Ctrl+C. Compose-only database names are not reachable from Windows.

## Controlled real-telemetry failure and recovery

This exercise is documented, **not yet executed or validated for this worker**.
Use only the local Demo 3.1.0. Its `GET /api/products` handler calls the
`product-catalog` dependency. Temporarily stopping that container should cause
real request failures; confirm actual HTTP results and exported metrics rather
than assuming a particular status code or guaranteed incident.

First start the worker as above. Verify baseline requests and metrics, record any
existing incidents, and confirm the catalog belongs to the intended Demo:

```powershell
Invoke-WebRequest http://127.0.0.1:8080/api/products -UseBasicParsing -TimeoutSec 10
Invoke-RestMethod http://127.0.0.1:8001/services/frontend/metrics
Invoke-RestMethod http://127.0.0.1:8001/incidents
$catalog = 'product-catalog'
$info = docker inspect --format '{{json .}}' $catalog | ConvertFrom-Json
if ($LASTEXITCODE -ne 0) { throw 'Catalog inspection failed' }
if ($info.Config.Image -ne 'ghcr.io/open-telemetry/demo:3.1.0-product-catalog' -or
    -not $info.State.Running -or
    $null -eq $info.NetworkSettings.Networks.'opentelemetry-demo') {
    throw 'Unexpected catalog container; stop without changing it'
}
try {
    docker stop $catalog
    if ($LASTEXITCODE -ne 0) { throw 'Catalog stop failed' }
    # Bounded real requests; existing Demo-generated traffic may also continue.
    $until = (Get-Date).AddMinutes(6)
    while ((Get-Date) -lt $until) {
        curl.exe --silent --output NUL --write-out "HTTP %{http_code}`n" --max-time 3 http://127.0.0.1:8080/api/products
        Start-Sleep -Milliseconds 250
    }
    Invoke-RestMethod http://127.0.0.1:8001/services/frontend/metrics
    Invoke-RestMethod http://127.0.0.1:8001/incidents
    docker @rookCompose logs --tail 30 worker
} finally {
    docker start $catalog
    if ($LASTEXITCODE -ne 0) { Write-Error 'Catalog restart failed; restore this container immediately' }
}
```

Allow at least two source samples and several worker sweeps. Success requires a
fresh **measured** ratio or p95 above its configured threshold and a corresponding
persisted `frontend` incident with matching evidence times. Repeated evaluations
should retain the active incident ID. No incident is the correct outcome if
measurements are missing, stale or below threshold. If the request path does not
export usable evidence, report that limitation; do not insert records or relabel
missing 5xx evidence as zero. Stopping the catalog does not modify the Demo checkout.

After restart, repeat the baseline HTTP request and metrics command. Let more than
five minutes of real successful traffic replace the failing window and inspect
fresh evidence again. A restart alone is not recovery. A missing error ratio still
means insufficient evidence. Once the operator has assessed recovery, resolve only
the selected exercise incident (replace the UUID); this action does not certify health:

```powershell
$incidentId = '<UUID of the verified exercise incident>'
Invoke-RestMethod -Method Post "http://127.0.0.1:8001/incidents/$incidentId/resolve"
```

Do not delete volumes, prune Docker, stop unrelated containers, or leave the catalog
stopped. Worker container startup and this failure demonstration remain pending
runtime verification; earlier local validation passed 90 tests with one PostgreSQL
integration test skipped and two dependency deprecation warnings.
