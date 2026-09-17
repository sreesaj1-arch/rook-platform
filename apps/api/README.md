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

## Configuration and structure

`ROOK_APP_NAME` sets the FastAPI title (default `Rook API`). Empty or whitespace-only values are rejected. This is the only application setting; `.env` files are not loaded automatically. Set it in PowerShell with `$env:ROOK_APP_NAME = 'Rook API'`.

`create_app(settings: Settings | None = None)` accepts explicit configuration or reads environment settings when called. Configuration is immutable, and each app owns its own state. The shared `rook_backend.config` module does not import FastAPI and can later support another entry point without introducing a worker now.

Tests cover the exact liveness response, configuration defaults and overrides, invalid environment values, and independent application state and OpenAPI titles. They require no external service.
