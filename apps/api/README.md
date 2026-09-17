# Rook backend foundation

This slice provides a FastAPI app factory, typed configuration, and process liveness. It does not implement database integration, telemetry, a worker, or monitored-service health.

## Current verification status

The user completed local verification and reported:

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

## Continuous integration

[Backend CI](../../.github/workflows/backend-ci.yml) runs on pull requests targeting `main`, pushes to `main`, and manual dispatch, without path filters. One Ubuntu job has a 10-minute timeout and read-only repository permissions; checkout does not persist credentials. Actions are pinned to full commit SHAs, and uv is pinned to 0.11.7.

CI reads Python from `.python-version`, then runs `uv sync --locked --managed-python` and `uv run --locked python -m pytest` in `apps/api`. Test failures fail the job, and dependency warnings remain visible. It performs no deployment. Local workflow validation is not an actual GitHub Actions run; execution must be verified after pushing. Manual dispatch becomes available once the workflow exists on the default branch.

## Configuration and structure

`ROOK_APP_NAME` sets the FastAPI title (default `Rook API`). Empty or whitespace-only values are rejected. This is the only application setting; `.env` files are not loaded automatically. Set it in PowerShell with `$env:ROOK_APP_NAME = 'Rook API'`.

`create_app(settings: Settings | None = None)` accepts explicit configuration or reads environment settings when called. Configuration is immutable, and each app owns its own state. The shared `rook_backend.config` module does not import FastAPI and can later support another entry point without introducing a worker now.

Tests cover the exact liveness response, configuration defaults and overrides, invalid environment values, and independent application state and OpenAPI titles. They require no external service.
