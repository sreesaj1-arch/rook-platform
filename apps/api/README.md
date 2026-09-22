# Rook backend foundation

This slice provides a FastAPI app factory, typed configuration, process liveness, database readiness, optional read-only Prometheus service metrics, and explicit incident evaluation with PostgreSQL product state. The independently started [background worker](worker.md) schedules evaluations; the API never starts a worker or infers service health from missing evidence.

## First incident milestone

`GET /incidents` lists persisted incidents (newest first, `limit` 1-100 and
`offset` 0-100000). `GET /incidents/{UUID}` returns one incident or 404. Database
failure or an uninitialized table returns generic 503; malformed IDs return 422.
Neither route triggers detection. Existing health and metrics behavior is unchanged.

`rook_backend.incidents.evaluate_service(service, source, store, rules)` is an
async entry point shared by tests and the background worker. It calls the same live
Prometheus adapter as the metrics endpoint, without an internal HTTP hop. Thresholds
are explicit: error ratio uses 0-1 units and p95 uses seconds. A strict threshold
breach in one fresh measured five-minute snapshot opens an incident immediately.
This initial detector does not yet implement the accepted architecture's sustained
violation/recovery durations or minimum-volume rules; it is not full V1 detection.

Missing 5xx series remain null/insufficient data. Stale, invalid, insufficient or
unavailable measurements cannot open, update or resolve an incident. Rules operate
independently, so measured latency can breach while error evidence is missing.
No automatic resolution occurs, including after a measured below-threshold result.
Explicit operator transitions are available through `POST /incidents/{UUID}/acknowledge`
(open to acknowledged) and `POST /incidents/{UUID}/resolve` (open or acknowledged
to resolved). They need no request body and return the updated incident. Repeated
actions, backward transitions and actions on resolved incidents return HTTP 409
`{"status":"invalid_transition"}` without changing stored state. Unknown IDs return
404, malformed UUIDs 422, and database failures generic 503. Manual resolution is
not proof of measured recovery; the stored values remain the original breach
evidence. Automated recovery and transition timestamps/history remain planned; scheduling is provided by the optional worker.

PostgreSQL stores only incident product state: service/namespace, rule, threshold,
latest breach value/unit, evaluation time, source evidence time and a PromQL
reference. No raw counters, histograms, logs or traces are copied. `data_quality`
describes the stored breach evidence at evaluation time, not current service health
or current freshness. Referenced evidence may expire from Prometheus. Repeated
breaches update one active incident, preserving its ID, opened time and acknowledged
state; old evaluations or unchanged source timestamps do not overwrite newer evidence.
The same ownership lock guards transitions and evaluation. Already resolved evidence
cannot reopen an incident; a later fresh breach with advancing evaluation and source
timestamps may create a new incident. The existing `evaluate_service` entry point
can be called directly or repeatedly by the independently started worker.
A transaction-level PostgreSQL advisory lock serializes writers, and a partial
unique index enforces one active incident per namespace/service/rule. Transactions
have a ten-second overall deadline plus existing driver/server timeouts.

Schema creation uses the explicit `init-db` command or the worker's idempotent initialization, never API startup. It creates
the first table/index if absent and can be repeated without deleting records.
It does not migrate existing columns; a detected column mismatch fails and needs
an explicit reviewed migration. Future schema changes require migrations; Alembic
is not needed for this single initial schema. Do not delete an existing volume.

From `apps/api` in PowerShell, with the existing `ROOK_DB_*` and
`ROOK_PROMETHEUS_*` environment configured for reachable services:

```powershell
uv sync --locked --managed-python
if ($LASTEXITCODE -ne 0) { throw 'Locked sync failed' }
.\.venv\Scripts\python.exe -m rook_backend.incident_cli init-db
if ($LASTEXITCODE -ne 0) { throw 'Schema initialization failed' }
# Example operator-selected thresholds, not observed telemetry values.
.\.venv\Scripts\python.exe -m rook_backend.incident_cli evaluate --service frontend --error-ratio 0.05 --p95-seconds 0.5
if ($LASTEXITCODE -ne 0) { throw 'Evaluation unavailable or configuration invalid' }
Invoke-RestMethod http://127.0.0.1:8001/incidents
```

The CLI uses a Windows selector event loop and closes its database and HTTP
resources. PostgreSQL in the existing Compose setup has no host port: run these
Python module commands inside a Rook API container containing this code when using
that private database (`docker compose exec api python -m rook_backend.incident_cli ...`).
The API must use the existing telemetry override to reach Prometheus. The host
commands do not make Compose-only names reachable from Windows. The one-shot CLI does not schedule evaluations; use the [worker runbook](worker.md) for continuous evaluation. An empty incident list is valid;
never insert demo incidents to populate it.

Unit tests use test-only measurements and in-memory SQLite for repository SQL;
PostgreSQL locking is not established by SQLite tests. Live PostgreSQL persistence
and detection from an actual workload breach still require runtime verification.

Local lifecycle validation: Python 3.13.13 ran 75 passing backend tests with one
opt-in real PostgreSQL integration test skipped and
two existing Starlette/httpx and AnyIO deprecation warnings (not application
failures). Pytest's cache plugin was disabled because the existing cache directory
was not writable. Locked sync resolved 30 packages but failed fetching Hatchling
from `https://pypi.org/simple/hatchling/`: connection refused, Windows error 10061.
Dependencies and `uv.lock` are unchanged. Rerun the locked sync command above in
the user terminal before runtime verification; no global settings change is needed.

### Real PostgreSQL lifecycle verification

The assistant's Docker check failed with `permission denied while trying to connect
to the docker API at npipe:////./pipe/dockerDesktopLinuxEngine`. Live PostgreSQL
verification has **not** passed in this session. The opt-in integration test uses
explicit test fixtures in a UUID namespace, checks committed state through independent
connections, concurrent evaluation deduplication, valid/invalid transitions and the
manual recovery policy, then deletes only its own fixture rows. It creates the
incident table if absent; no schema/volume is dropped and no Demo state is changed.

From the repository root, run this sequence against the existing Rook API container.
It copies current Python source to a unique temporary directory and runs the check
in a separate process using that container's existing private PostgreSQL configuration.
It does not rebuild, restart or replace the running API, and therefore does not verify
that the running HTTP server has loaded the new routes. The latter requires your
normal later deployment step. No pytest installation in the runtime image is needed.

```powershell
$apiContainer = 'rook-local-api-1'
$checkDir = '/tmp/rook-incident-check-' + [guid]::NewGuid().ToString('N')
$labels = docker inspect --format '{{json .Config.Labels}}' $apiContainer
if ($LASTEXITCODE -ne 0) { throw 'Existing Rook API container unavailable; stop' }
if (($labels | ConvertFrom-Json).'com.docker.compose.service' -ne 'api') { throw 'Not the Rook API service; stop' }
docker exec $apiContainer python -c 'import os,sys; os.mkdir(sys.argv[1])' $checkDir
if ($LASTEXITCODE -ne 0) { throw 'Cannot create verification directory; stop' }
try {
    docker cp apps/api/src/rook_backend "${apiContainer}:${checkDir}/rook_backend"
    if ($LASTEXITCODE -ne 0) { throw 'Source copy failed' }
    docker cp apps/api/tests/test_incidents_postgres.py "${apiContainer}:${checkDir}/check.py"
    if ($LASTEXITCODE -ne 0) { throw 'Test copy failed' }
    docker exec -e "PYTHONPATH=$checkDir" $apiContainer python "$checkDir/check.py"
    if ($LASTEXITCODE -ne 0) { throw 'PostgreSQL lifecycle verification failed' }
} finally {
    docker exec $apiContainer python -c 'import pathlib,shutil,sys; p=pathlib.Path(sys.argv[1]).resolve(); assert str(p).startswith(sys.argv[2]) and len(p.name) == 52; shutil.rmtree(p)' $checkDir '/tmp/rook-incident-check-'
}
```

For pytest with an already reachable PostgreSQL configuration, set
`$env:ROOK_TEST_POSTGRES = '1'` and run
`.\.venv\Scripts\python.exe -m pytest tests/test_incidents_postgres.py` from
`apps/api`, then remove that opt-in environment variable. Normal CI skips this
external-service check; test fixtures are never imported by application code.

For the live telemetry configuration, evidence semantics, current validation limits,
and exact PowerShell build/start/comparison commands, see [live telemetry](live-telemetry.md).

## Current verification status

Before the database foundation changes, the user completed local verification and reported:

- Python 3.13.13.
- `uv sync --locked --managed-python` succeeded using the generated `uv.lock`.
- pytest: 7 passed, with 2 dependency deprecation warnings.
- Uvicorn served an actual browser request to `/health/live`, which returned `{"status":"alive"}`.

These are the user's local results; the documentation update did not rerun installation, tests, or the HTTP check. The dependency warnings are distinct from application test failures.

## PowerShell setup

Prerequisite: uv and network access to its Python distribution and package sources when downloads are needed. From the repository root, use the existing lockfile and pinned uv-managed Python:

```powershell
Set-Location apps/api
uv sync --locked --managed-python
.\.venv\Scripts\python.exe --version
.\.venv\Scripts\python.exe -c "import sys; print(sys.executable)"
```

Normal setup requires no project-local cache or interpreter overrides. uv uses an isolated `apps/api/.venv` with managed Python, not Conda base. Do not use `--active` or install packages into Conda base.

Only when intentionally changing dependency declarations, regenerate the lockfile with uv:

```powershell
uv lock --managed-python
```

Never hand-edit `uv.lock`. Review dependency changes and use `uv sync --locked --managed-python` to install the resulting lockfile. Routine setup does not require running `uv lock`.

The interpreter must report Python 3.13.13 and an executable under `apps/api/.venv`. No environment activation or PowerShell execution-policy change is needed. Commands use this explicit executable even if Conda base is active in the parent terminal. Check each uv command succeeds before continuing.

## Optional cache or interpreter troubleshooting

If the default uv cache or interpreter directory is not writable, these overrides can be used from the repository root in a separate PowerShell session:

```powershell
$repoRoot = (Get-Location).Path
$env:UV_CACHE_DIR = Join-Path $repoRoot '.uv-cache'
$env:UV_PYTHON_INSTALL_DIR = Join-Path $repoRoot '.uv-python'
uv python install 3.13.13 --no-bin
Set-Location (Join-Path $repoRoot 'apps/api')
uv sync --locked --managed-python
```

These variables affect only that process and its children. The directories are ignored by Git, and `--no-bin` avoids installing user-level executable links. Close the troubleshooting session to discard its overrides. Directory overrides do not resolve network or proxy failures; inspect the reported connection error separately.

## Run and test

From `apps/api`:

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m uvicorn rook_backend.api.app:create_app --factory --host 127.0.0.1 --port 8000
```

In another PowerShell terminal:

```powershell
Invoke-WebRequest -Uri http://127.0.0.1:8000/health/live -UseBasicParsing
```

Expect HTTP 200 and `{"status":"alive"}`. Stop the foreground server with Ctrl+C in the terminal that started it. A liveness response means only that the API process handled the request; it does not claim database connectivity, readiness, or health of the monitored workload.

## Docker

From the repository root, with Docker Desktop running Linux containers:

```powershell
docker build --tag rook-backend:local apps/api
if ($LASTEXITCODE -ne 0) { throw 'Backend image build failed' }
```

The build context is `apps/api`. Both stages use the official [Python 3.13.13 slim-bookworm image](https://hub.docker.com/_/python/tags?name=3.13.13-slim-bookworm), matching `.python-version`; a build assertion checks that match. The builder installs [uv 0.11.7](https://github.com/astral-sh/uv/releases/tag/0.11.7) and runs `uv sync --locked --no-dev --no-editable`. Only the resulting virtual environment is copied into the runtime stage, leaving uv and isolated package-build tooling behind. The package is installed non-editably, without development dependencies. Image tags are version-pinned, not digest-pinned.

The runtime uses UID/GID 10001 and starts the existing Uvicorn app factory on `0.0.0.0:8000` without reload. The build-context allowlist excludes local environments, caches, downloaded interpreters, and secret files. Do not put credentials in Python source.

Run this verification block in the same PowerShell session. It binds only host localhost, checks HTTP and the runtime UID, prints logs, and cleans up only the container it creates. If port 8001 is occupied, leave the existing service alone and retry when the port is available.

```powershell
$containerName = 'rook-backend-check-' + [guid]::NewGuid().ToString('N')
$containerId = docker create --name $containerName --publish 127.0.0.1:8001:8000 rook-backend:local
if ($LASTEXITCODE -ne 0) { throw 'Container creation failed' }
try {
    docker start $containerId
    if ($LASTEXITCODE -ne 0) { throw 'Container startup failed' }
    $response = $null
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        try {
            $response = Invoke-WebRequest -Uri http://127.0.0.1:8001/health/live -UseBasicParsing -TimeoutSec 2
            break
        } catch { Start-Sleep -Seconds 1 }
    }
    if ($null -eq $response -or $response.StatusCode -ne 200) { throw 'Liveness HTTP check failed' }
    $body = $response.Content | ConvertFrom-Json
    if ($body.status -ne 'alive' -or @($body.PSObject.Properties).Count -ne 1) { throw 'Unexpected liveness response' }
    'HTTP {0}: {1}' -f $response.StatusCode, $response.Content
    $containerUid = docker exec $containerId id -u
    if ($LASTEXITCODE -ne 0 -or $containerUid -notmatch '^\d+$' -or [int]$containerUid -eq 0) { throw 'Non-root check failed' }
    'Container UID: {0}' -f $containerUid
} finally {
    docker logs $containerId
    docker stop $containerId
    docker rm $containerId
}
```

After a successful build, this cleanup retains `rook-backend:local`. No prune or cleanup of other containers is needed.

The user completed direct Docker runtime verification and reported:

- `GET http://127.0.0.1:8001/health/live` returned HTTP 200 and `{"status":"alive"}`.
- `docker exec rook-backend-check id` confirmed UID/GID 10001.
- Container logs showed successful Uvicorn startup and request handling.

These results are from the user's local verification. The final documentation review did not repeat the Docker build or runtime tests.

## Database foundation and Compose

The root `docker-compose.yml` builds the existing backend and uses the official [PostgreSQL 17.6-bookworm image](https://hub.docker.com/layers/library/postgres/17.6-bookworm/images/sha256-45cd22f8d32e189d245403954882f88e7a8714301fda80dab6da90f1265b25a3). PostgreSQL has a project-scoped named volume and `pg_isready` health check. It publishes no host port. Only the API is published, at `127.0.0.1:8001`.

Copy the root `.env.example` to `.env` for local development; its public example values are not production credentials. `.env` is ignored by Git and is outside the `apps/api` image context. The existing `.dockerignore` also excludes environment and secret files inside that context. Do not print resolved Compose configuration or connection settings into shared logs. Changing initialization credentials after a volume exists does not change credentials stored in PostgreSQL; retain the original values or change the database role deliberately. Do not delete the volume to fix this.

Application lifespan creates one SQLAlchemy async engine per app and disposes it on shutdown. Connections are opened lazily, so an unavailable database does not prevent process liveness. For this probe-only foundation, `NullPool` closes connections after each check and avoids stale pooled connections after restart. Readiness executes only `SELECT 1`, with a three-second async deadline (configurable from 0.05 to 10 seconds), a two-second connection timeout, and a two-second server statement timeout. Cancellation releases the connection; scheduling and driver cleanup may add a small delay. No SQL or connection-error details are logged by the application or returned in responses.

- `GET /health/live`: process-only HTTP 200, `{"status":"alive"}`, without touching the database.
- `GET /health/ready`: HTTP 200, `{"status":"ready"}`, when the query succeeds; otherwise HTTP 503, `{"status":"unavailable"}`. This does not report monitored-service health.
- Without `ROOK_DB_PASSWORD`, the standalone API starts normally but readiness returns 503.

### Validation status

The user completed local database milestone verification:

- `uv lock` and sync succeeded with SQLAlchemy and psycopg dependencies in `uv.lock`.
- Pytest passed all 19 tests, with two dependency deprecation warnings.
- With Compose PostgreSQL running, readiness returned HTTP 200 and `{"status":"ready"}`.
- After PostgreSQL stopped, readiness returned HTTP 503 and `{"status":"unavailable"}`, while liveness remained HTTP 200 and `{"status":"alive"}`.
- After PostgreSQL restarted, readiness recovered to HTTP 200 and `{"status":"ready"}`.

During final review, the assistant independently reran the Docker-independent suite using the project virtual environment on Python 3.13.13: `python -B -m pytest -p no:cacheprovider` passed all 19 tests with the same two warnings. These concern Starlette's use of `httpx` in its test client and the deprecated AnyIO `BlockingPortal` alias; they are dependency deprecations, not application failures. Docker checks were not repeated; the real database outage and recovery results above are from the user's local verification.

### Repeat local validation in PowerShell

From the repository root, install from the existing lockfile and run the Docker-independent tests:

```powershell
Push-Location apps/api
try {
    uv sync --locked --managed-python
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed' }
    .\.venv\Scripts\python.exe -m pytest
    if ($LASTEXITCODE -ne 0) { throw 'Tests failed' }
} finally { Pop-Location }
```

Then run the following in one session with Docker Desktop using Linux containers. It creates an isolated Compose project, checks actual readiness, stops only that project's database, checks 503 and independent liveness, then restarts the database and checks recovery. Leave any existing service on port 8001 alone; wait until the port is available before running. Cleanup retains the named volume and image.

```powershell
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
$rookProject = 'rook-db-check-' + [guid]::NewGuid().ToString('N')

function Assert-RookHealth([string]$Path, [int]$Code, [string]$Status) {
    $result = @(curl.exe --silent --show-error --max-time 5 --write-out "`n%{http_code}" "http://127.0.0.1:8001/health/$Path")
    if ($LASTEXITCODE -ne 0) { throw 'HTTP request failed' }
    $body = ($result[0..($result.Count - 2)] -join "`n") | ConvertFrom-Json
    if ([int]$result[-1] -ne $Code -or $body.status -ne $Status) { throw "Unexpected $Path response" }
    "$Path HTTP $Code : $Status"
}

try {
    docker compose -p $rookProject up --build --detach --wait --wait-timeout 120
    if ($LASTEXITCODE -ne 0) { throw 'Compose startup failed' }
    $ready = $false
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        try { Assert-RookHealth ready 200 ready; $ready = $true; break }
        catch { Start-Sleep -Seconds 1 }
    }
    if (-not $ready) { throw 'Initial readiness failed' }
    docker compose -p $rookProject stop postgres
    if ($LASTEXITCODE -ne 0) { throw 'Database stop failed' }
    Assert-RookHealth ready 503 unavailable
    Assert-RookHealth live 200 alive
    docker compose -p $rookProject start postgres
    if ($LASTEXITCODE -ne 0) { throw 'Database restart failed' }
    $ready = $false
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        try { Assert-RookHealth ready 200 ready; $ready = $true; break }
        catch { Start-Sleep -Seconds 1 }
    }
    if (-not $ready) { throw 'Readiness recovery failed' }
    docker compose -p $rookProject logs api
} finally {
    docker compose -p $rookProject down
}
```

Do not add `--volumes` or run Docker prune. The `.env` values configure this local PostgreSQL instance and are passed to the API by Compose; the Python application does not load `.env` directly. For a host-based Windows API using psycopg async connections, use a selector event loop (for example, `asyncio.run(server.serve(), loop_factory=asyncio.SelectorEventLoop)`); the normal Compose runtime is Linux. Docker-independent unit tests stub database I/O and do not require this Windows driver setup.

## Continuous integration

[Backend CI](../../.github/workflows/backend-ci.yml) runs on pull requests targeting `main`, pushes to `main`, and manual dispatch, without path filters. One Ubuntu job has a 10-minute timeout and read-only repository permissions; checkout does not persist credentials. Actions are pinned to full commit SHAs, and uv is pinned to 0.11.7.

CI reads Python from `.python-version`, then runs `uv sync --locked --managed-python` and `uv run --locked python -m pytest` in `apps/api`. Test failures fail the job, and dependency warnings remain visible. It performs no deployment. Local workflow validation is not an actual GitHub Actions run; execution must be verified after pushing. Manual dispatch becomes available once the workflow exists on the default branch.

## Configuration and structure

`ROOK_APP_NAME` sets the FastAPI title (default `Rook API`). Empty or whitespace-only values are rejected. Database settings are `ROOK_DB_HOST` (default `postgres`), `ROOK_DB_PORT` (5432), `ROOK_DB_NAME` and `ROOK_DB_USER` (both `rook_local`), `ROOK_DB_PASSWORD` (unset), and `ROOK_READINESS_TIMEOUT_SECONDS` (3). The password is stored as a secret value and omitted from settings representations. `.env` files are not loaded automatically.

`create_app(settings: Settings | None = None)` accepts explicit configuration or reads environment settings when called. Configuration is immutable, and each app owns its own state. The shared `rook_backend.config` module does not import FastAPI and can later support another entry point without introducing a worker now.

Tests cover the exact liveness response, configuration defaults and overrides, invalid environment values, and independent application state and OpenAPI titles. They require no external service.
