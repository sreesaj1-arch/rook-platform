# Pull-request validation

[Rook CI](../.github/workflows/backend-ci.yml) extends the existing workflow in
place, preserving the `backend-tests` job and `Backend tests` check name. Every PR
(any target branch), push to `main`, and manual dispatch receives all four jobs.
There are no path filters, secrets, registry logins, image pushes, or deployments.
Actual GitHub execution can only be confirmed after the workflow is pushed.

| Job | Checks | Budget |
|---|---|---|
| Backend tests | Python from `.python-version`, uv 0.11.7 locked sync, complete pytest suite, Python AST syntax, TOML parsing, generated OpenAPI routes, commit-range/local whitespace, scanner error-handling unit tests | 10 minutes |
| Frontend checks | Node 24.15.0, `npm ci`, all Node unit tests, TypeScript and Vite production build | 10 minutes |
| Container builds and advisory scan | Build the shared API/worker image and production frontend image, then scan both local images | 20 minutes |
| Helm and rollback checks | Checksum-verified Helm 4.2.3, YAML syntax, default/canary lint, default/staged/active canary rendering and contract tests, PowerShell rollback-script tests | 10 minutes |

The frontend build already runs `tsc --noEmit`; there is no duplicate TypeScript
step. Its Dockerfile necessarily builds assets again to verify the actual image.
Helm is mandatory in its CI job: rendering cannot silently pass as skipped tests.
Rendered YAML is parsed by the existing chart tests, which also check selectors,
probes, stable/canary separation and unchanged unrelated resources. YAML parsing
supports the existing Compose `!override` tags. No Kubernetes context is needed.
The same Helm job also runs the local [GitOps safety contracts](../deploy/gitops/argocd/test_gitops.py):
repository/revision/destination boundaries, external Secrets, manual-only sync,
no pruning/force/finalizers, and environment rendering. It does not install or sync
Argo CD. Deployment remains a separate [operator-reviewed action](../deploy/gitops/argocd/README.md).

Jobs use Ubuntu 24.04, `contents: read`, full-SHA action pins and checkout with
persisted credentials disabled. PRs use `pull_request`, never `pull_request_target`.
No cross-run dependency/build caches are saved; installs use the existing uv/npm
lockfiles. CI-only Python validators have explicit pins in
[`scripts/ci/requirements.txt`](../scripts/ci/requirements.txt); application
dependencies and lockfiles are unchanged. New runs cancel obsolete checks on the
same ref. Whitespace checks compare the PR base/push-before commit with HEAD;
manual/first-push checks inspect HEAD, and local checks include untracked text files.

Images are tagged `rook-backend:ci-$GITHUB_SHA` and `rook-frontend:ci-$GITHUB_SHA`.
For a PR, this identifies the tested merge commit, not just its source-branch tip.
The worker shares the backend image, so a third build is unnecessary. These are
local tags only, not claims of bit-for-bit reproducibility: base image version
tags and upstream package availability remain external inputs.

## Advisory vulnerability scan

The scanner helper downloads Trivy 0.69.3 and verifies a hardcoded SHA-256 against
the official immutable release. It executes only the verified binary, scans local
Docker images for HIGH/CRITICAL vulnerabilities, and never runs application images
or sends image contents to a registry. No mutable Trivy action tag is used.

Findings are advisory at this milestone and appear in the log and job summary.
Download/database outages or scan timeouts emit explicit warnings stating that
coverage is unavailable; they are never described as a clean scan and do not fail
otherwise valid builds. Missing built images and a scanner checksum mismatch do
fail. There is no blanket `continue-on-error` around builds or tests. A completed
scan with no findings is limited to that scanner/database, not proof of security.
The helper supports Linux/Windows x64 and bounds each scan to three minutes.

## Reproduce locally in PowerShell

Use a separate shell from the repository root, Python/uv as documented in the
[backend README](../apps/api/README.md), Node 24.15.0, and Helm 4.2.3 on this process's
PATH. Do not install anything into Conda base. Stop at the first failed command.

```powershell
function Confirm-CI { if ($LASTEXITCODE -ne 0) { throw 'Check failed; stop and inspect its output' } }
Push-Location apps/api
try {
    uv sync --locked --managed-python
    Confirm-CI
    uv run --locked python -m pytest
    Confirm-CI
} finally { Pop-Location }
uv run --project apps/api --locked python scripts/ci/check_backend.py
Confirm-CI
uv run --project apps/api --locked python -m unittest discover -s scripts/ci/tests
Confirm-CI
Push-Location apps/frontend
try {
    npm ci
    Confirm-CI
    npm test
    Confirm-CI
    npm run build
    Confirm-CI
} finally { Pop-Location }
uv run --no-project --python 3.13.13 --with-requirements scripts/ci/requirements.txt python scripts/ci/check_helm.py
Confirm-CI
& ./deploy/helm/rook/tests/switch-api.tests.ps1
git diff --check
Confirm-CI
```

The rollback tests use test-only command doubles; they never connect to Kubernetes
or perform a real switch. They are not evidence of an actual rollout. CI uses
runner PowerShell (`pwsh`); Windows PowerShell is also supported locally.

Only the following checks require Docker (Linux containers). They do not start or
stop the existing Rook/Demo stacks, delete volumes, or push images:

```powershell
$sha = git rev-parse HEAD
Confirm-CI
docker build --tag "rook-backend:ci-$sha" apps/api
Confirm-CI
docker build --tag "rook-frontend:ci-$sha" apps/frontend
Confirm-CI
uv run --project apps/api --locked python scripts/ci/scan_images.py "rook-backend:ci-$sha" "rook-frontend:ci-$sha"
Confirm-CI
```

Locally these tags identify HEAD, but builds also include uncommitted build-context
changes. Record that distinction when sharing results. Image retention is intentional;
these instructions contain no prune or unrelated-resource cleanup commands.

## Checks deliberately outside ordinary PR CI

The PostgreSQL integration test remains opt-in (`ROOK_TEST_POSTGRES=1`); normal
pytest reports it skipped. The existing `npm run test:browser` integration test
requires Windows Edge, a running dashboard/API, and real measured service telemetry.
It is not a cluster-free unit test and is not replaced with fabricated metrics in
CI. Run it locally using the [frontend instructions](../apps/frontend/README.md).
Its UI protocol fixtures remain confined to tests. The PR frontend job runs every
test in `src/*.test.ts`; it does not claim browser or live-service coverage.

Canary traffic switching, real failure/recovery and operator rollback remain
explicit runtime exercises in the [canary runbook](../deploy/helm/rook/CANARY.md).
The Demo checkout is never modified or started by CI.

Future image publication should be a separate trusted-main workflow with narrowly
scoped registry write permissions and immutable digest outputs. Deployment and
environment approvals can follow separately; fork PR checks should retain their
current read-only, secret-free boundary. No repository rules or required-check
settings are changed here.

## Local validation of this milestone

Locked backend sync succeeded with the process proxy temporarily removed; no
global settings changed. Backend pytest reported 120 passed, one opt-in PostgreSQL
test skipped, and two dependency deprecation warnings. Four scanner-helper tests
passed, including outage reporting and refusal to execute a checksum mismatch.

The original frontend native binding was locked by another running process.
That process was left alone. An isolated copy under ignored `tmp/` completed
`npm ci --offline`, all 21 unit tests, TypeScript and the production build. Missing
local dependency files from the interrupted install were restored from this
lockfile-validated copy without replacing the locked file. The existing browser
integration test also passed against the running real API and dashboard.

Both production images built with commit-based local tags. The advisory scanner
ran and emitted vulnerability findings, including frontend `libexpat`
`CVE-2026-93990` (HIGH; installed `2.8.4-r0`, reported fix `2.8.5-r0`). The subsequent [image security review](IMAGE_SECURITY.md) records the targeted
remediation, refreshed scans and every remaining advisory.

Helm 4.2.3 lint, rendering and all eight chart tests passed, as did the five
operator-switch tests. YAML, TOML, OpenAPI, Python syntax, changed-file whitespace,
and diff checks passed. Locally downloaded checksum-verified actionlint 1.7.7
accepted the workflow; optional ShellCheck/Pyflakes integrations were unavailable.
These are local results, not a completed GitHub Actions execution.

## Verified upstream pins

Action SHAs were checked against the official GitHub tag refs:
[checkout v4.2.2](https://github.com/actions/checkout/releases/tag/v4.2.2),
[setup-uv v6.0.1](https://github.com/astral-sh/setup-uv/releases/tag/v6.0.1), and
[setup-node v4.4.0](https://github.com/actions/setup-node/releases/tag/v4.4.0).
Helm's archive checksum comes from [the official distribution](https://get.helm.sh/helm-v4.2.3-linux-amd64.tar.gz.sha256sum).
Scanner checksums come from [Trivy's v0.69.3 release assets](https://github.com/aquasecurity/trivy/releases/tag/v0.69.3);
the upstream [security advisory](https://github.com/aquasecurity/trivy/security/advisories/GHSA-69fq-xp46-6x23)
identifies that immutable release as unaffected by the later compromised releases.
