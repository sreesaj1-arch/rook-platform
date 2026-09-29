# Local GitOps with Argo CD

This is an opt-in handoff of the existing Helm deployment to Argo CD, not a second
deployment or a new runtime architecture. Docker Compose remains the primary
development path. This directory does not install Argo CD or the external Demo.
Do not apply it to a remote cluster.

## Ownership and desired state

| Item | Owner |
|---|---|
| Rook API, worker, frontend, PostgreSQL StatefulSet, Services, ConfigMap | Argo CD after the reviewed handoff, rendered from `deploy/helm/rook` |
| `rook-k8s-local` namespace, existing `rook-db` Secret | Operator, never this Application |
| PostgreSQL data PVC | Created by StatefulSet controller, retained; never delete during rollback/uninstall |
| Argo CD installation, repository access, local image availability | Operator |
| Demo, Prometheus, Docker Compose, incident decisions | Existing systems, unchanged |

`application.yaml` is also the Docker Desktop environment example. It points to
the repository's real HTTPS origin and the existing chart commit
`b5634406b9fcab99c63460ad24a24ef7d0e17459`. Argo reads that remote commit, never
uncommitted workspace files. Inline `valuesObject` supplies the local environment
without requiring a new values file at that older commit. The Application itself
is applied by the operator; it does not manage itself. After review/publication,
keep its values and chart SHA in Git and explicitly reapply that file when they
change. No commits or pushes are performed by these instructions automatically.

Application name and Helm release name are both `rook` to preserve the existing
instance-label selectors. The dedicated `rook-local` AppProject allows only this
repository, in-cluster destination and `rook-k8s-local` namespace, and only the
four chart resource kinds. It cannot manage Secrets, namespaces or cluster-scoped
resources. Existing chart defaults provide PostgreSQL image/storage/resources;
copy any live custom settings into `valuesObject` before adopting them.

Sync is **manual**: no `automated` policy, self-healing, automatic pruning, retry
loop, destructive replace/force, or deletion finalizer. `sync.yaml` requests one
operator sync with pruning and force explicitly false. `FailOnSharedResource`
rejects resources tracked by another Argo Application; it does **not** establish
ownership of untracked resources. The operator must review collisions first.
There are no ignored routing differences to hide drift. Removing a resource from
Git leaves it live and potentially OutOfSync; that is intentional with pruning off.

## 1. Context, existing state and external Secret

Run from the repository root in PowerShell. Stop on every failed command. Keep
these functions/variables for subsequent blocks; all Kubernetes commands explicitly
use Docker Desktop, without changing your global/current context.

```powershell
$ErrorActionPreference = 'Stop'
$context = 'docker-desktop'
$namespace = 'rook-k8s-local'
$gitops = 'deploy/gitops/argocd'
function Check-Native { if ($LASTEXITCODE -ne 0) { throw 'Command failed; stop and inspect' } }
kubectl config get-contexts $context
Check-Native
kubectl --context $context --request-timeout=10s get nodes
Check-Native
kubectl --context $context -n $namespace get deployments,statefulsets,pods,services,pvc
Check-Native
kubectl --context $context -n $namespace get secret rook-db -o name
Check-Native
kubectl --context $context -n $namespace get pvc -o 'custom-columns=NAME:.metadata.name,UID:.metadata.uid,VOLUME:.spec.volumeName'
Check-Native
kubectl --context $context -n $namespace get secret rook-db -o 'custom-columns=NAME:.metadata.name,UID:.metadata.uid'
Check-Native
```

Record PVC/Secret identities for comparison afterward; never print Secret data.
The existing Helm release must be healthy, in this namespace, named `rook`.
If the namespace/Secret is absent, stop and follow the existing
[Kubernetes prerequisites and secure interactive Secret creation](../../helm/rook/README.md).
Do not replace an existing Secret or rotate a database password through values.
Namespace auto-creation is deliberately absent; no namespace is adopted implicitly.

## 2. Argo CD installation is a separate operator action

```powershell
kubectl --context $context get crd applications.argoproj.io appprojects.argoproj.io
Check-Native
kubectl --context $context -n argocd get deployments,statefulsets,pods
Check-Native
```

If absent, **stop here until you intentionally install Argo CD**. Follow the
[official installation guide](https://argo-cd.readthedocs.io/en/stable/getting_started/),
review a supported release and pin its full upstream commit. For example, the
following is a user-run installation sequence, not something this milestone ran:

```powershell
# Obtain the full commit of your reviewed upstream Argo CD release; do not use HEAD/stable.
$argoInstallCommit = Read-Host 'Reviewed argoproj/argo-cd release commit (40 hex characters)'
if ($argoInstallCommit -notmatch '^[0-9a-f]{40}$') { throw 'An exact reviewed upstream commit is required' }
kubectl --context docker-desktop get nodes
Check-Native
kubectl --context docker-desktop create namespace argocd
Check-Native # If it already exists, inspect its ownership before continuing manually.
kubectl --context docker-desktop -n argocd apply --server-side -f "https://raw.githubusercontent.com/argoproj/argo-cd/$argoInstallCommit/manifests/install.yaml"
Check-Native
kubectl --context docker-desktop -n argocd rollout status deployment/argocd-server --timeout=300s
Check-Native
kubectl --context docker-desktop -n argocd rollout status statefulset/argocd-application-controller --timeout=300s
Check-Native
```

Installation creates Argo's own cluster-level controller permissions; the Rook
AppProject restrictions do not restrict those controller permissions globally.
Do not expose the server publicly. Access its existing administration UI through
`kubectl --context docker-desktop -n argocd port-forward --address 127.0.0.1 service/argocd-server 8443:443`
in another terminal. Use upstream login instructions without saving credentials
in Git or transcripts. No Rook authentication feature is introduced here.

## 3. Prepare images and review Helm handoff

The example tags are `rook-backend:gitops-b5634406` (API and worker) and
`rook-frontend:gitops-b5634406`. Build those only from the corresponding reviewed
commit; use a new unique tag and update values for any other build. `Never` prevents
a missing local image from silently falling back to a registry image. No images
are pushed. Docker Desktop must make these images available to its Kubernetes
nodes; an `ErrImageNeverPull` means they are not loaded, not a successful rollout.
Verify your Docker Desktop provisioner/image-store configuration; do not assume
host Docker and all Kubernetes nodes share a store. Import using that runtime's
supported method if required. Keep the previous images for rollback.

```powershell
if ((git rev-parse HEAD) -ne 'b5634406b9fcab99c63460ad24a24ef7d0e17459') {
    throw 'Select unique image tags for this reviewed source revision before building'
}
if (git status --porcelain -- apps/api apps/frontend) { throw 'Build contexts differ from the pinned commit' }
docker build -t rook-backend:gitops-b5634406 apps/api
Check-Native
docker build -t rook-frontend:gitops-b5634406 apps/frontend
Check-Native
docker image inspect rook-backend:gitops-b5634406 rook-frontend:gitops-b5634406 --format '{{.RepoTags}} {{.Id}}'
Check-Native
```

Retain the [image security findings](../../../docs/IMAGE_SECURITY.md); GitOps does
not remediate or accept those risks. CI tests/builds/scans the revision, but does
not publish images or sync Kubernetes. The operator reviews CI, prepares local
images, updates desired state and approves a separate sync. Argo CD has no CI
credential or image-publishing permission.

The example Prometheus URL `http://host.docker.internal:9090` was observed working
from this Docker Desktop cluster on 2026-09-28. It is environment-specific, not
Compose DNS. On another machine verify pod connectivity first, use a reachable
in-cluster/external URL, or explicitly disable with an empty string. Do not silently
disable existing telemetry during adoption. Preserve source profiles, namespace,
worker services/thresholds/interval, database username/name/storage and canary state.
URLs must not contain credentials. No new relay or Demo change is installed here.

Before first sync, review `helm get values rook --kube-context docker-desktop -n rook-k8s-local`
privately: legacy Helm values can contain credentials; do not paste/save them in
tracked files. Copy only non-secret settings into the Application. Check images,
selectors, ConfigMap, StatefulSet immutable fields and all resource names. Existing
canary resources must either match explicitly enabled canary values or be retained
intentionally; prune must stay off. Export a secure database backup if needed.

**Argo uses Helm to render, not `helm upgrade` or Helm release history.** Once adopted,
stop direct Helm upgrades, rollbacks and uninstalls, including the Helm-mutating
`deploy/helm/rook/switch-api.ps1`. Keep its old release metadata untouched as historical
evidence, but it is no longer current desired state. Do not run two deployment owners.
The original Helm-only path and scripts remain unchanged for installations that
have not been handed over.

## 4. Apply, inspect drift, then explicitly sync

After reviewing environment values and resource ownership:

First inspect `kubectl --context docker-desktop -n argocd get applications,appprojects`.
If `rook` or `rook-local` already exists, verify its repository, destination and
owner before proceeding; never overwrite an unrelated Application/Project with
these names. `apply` is appropriate only for this reviewed installation.

```powershell
kubectl --context $context -n argocd apply --dry-run=server -f "$gitops/project.yaml"
Check-Native
kubectl --context $context -n argocd apply -f "$gitops/project.yaml"
Check-Native
kubectl --context $context -n argocd apply --dry-run=server -f "$gitops/application.yaml"
Check-Native
kubectl --context $context -n argocd apply -f "$gitops/application.yaml"
Check-Native
kubectl --context $context -n argocd annotate application rook argocd.argoproj.io/refresh=hard --overwrite
Check-Native
kubectl --context $context -n argocd get application rook -o yaml
Check-Native
```

Applying the Application only configures comparison; it does not sync workloads.
Inspect the UI's manifests/diff and conditions. Review all differences, including
resources not already tracked by Argo. Reject unexpected names, namespaces,
database/storage changes or shared-resource warnings. For a missing/private Git
revision, configure repository read access outside Git or choose a reachable
reviewed commit; never embed a token in the URL. A local commit is not accessible
to Argo until the user separately publishes it.

Only after the diff is accepted (and the canary gates below, if switching):

```powershell
kubectl --context $context -n argocd patch application rook --type merge --patch-file "$gitops/sync.yaml"
Check-Native
kubectl --context $context -n argocd wait application/rook --for=jsonpath='{.status.operationState.phase}'=Succeeded --timeout=300s
Check-Native
kubectl --context $context -n argocd wait application/rook --for=jsonpath='{.status.sync.status}'=Synced --timeout=300s
Check-Native
kubectl --context $context -n argocd wait application/rook --for=jsonpath='{.status.health.status}'=Healthy --timeout=300s
Check-Native
kubectl --context $context -n $namespace get deployments,statefulsets,pods,pvc
Check-Native
kubectl --context $context -n $namespace logs deployment/rook-worker --tail=20
Check-Native
```

Check the operation's start/finish time and revision as well as these waits; an
old Succeeded status is not proof that a new request completed. A failed sync can
partially apply resources. Inspect `.status.conditions`, `.status.operationState`,
events and logs, fix the actual issue, review the new diff, then request another
sync. Do not use force, replace, prune or automatic retry to bypass a failure.
Argo Healthy/Synced means deployment reconciliation, not healthy monitored services.

Refresh comparison with the annotation above to detect drift. With a pinned SHA,
new remote commits do not change desired state until the operator updates the
Application; changes in live resources appear OutOfSync and remain until a manual
sync. Inspect the UI diff before any reapplication.

## 5. Canary, traffic switch and rollback

Keep the [existing safety model](../../helm/rook/CANARY.md): separate stable and
canary workloads, whole-Service selection, no weighted split or automatic rollback.
Use two reviewed desired-state changes, not one combined staging/promotion sync:

1. Set `canary.enabled: true`, an available unique image/version, replicas >= 1,
   and `apiTraffic: stable` in the Git-managed Application values. Reapply, review,
   manually sync and wait for both Deployments Ready. Leave all other values unchanged.
2. Check the canary directly using the read-only gate below. Only after success,
   change **only** `apiTraffic` to `canary` in desired state, reapply and review the
   diff: only the active API Service selector may change. Run the gate again just
   before explicitly syncing. Any failure means stop; never sync an unready target.
3. Inspect Ready EndpointSlices and their target pod image/version, then issue new
   requests through `rook-api` and frontend `/api`. Existing API port-forwards stay
   attached to their selected pod, so restart them or use fresh in-cluster requests.
4. Roll back by restoring **only** `apiTraffic: stable` in Git-managed desired state,
   verify stable image/version/readiness and health, reapply and manually sync.
   Metrics need not recover before restoring routing. Verify stable endpoint pod
   identities and new Service requests afterward. Keep canary available for inspection.

These Git changes/publication remain explicit operator work; this milestone does
not commit or push them. A SHA change may also change templates: inspect the full
rendered diff and never treat it as a routing-only operation without evidence.

Read-only gate (set expected image/version to the exact reviewed target values):

```powershell
$target = 'canary' # Use 'stable' for rollback.
$expectedImage = Read-Host 'Exact target image from reviewed Application values'
$expectedVersion = Read-Host 'Exact target version label from reviewed Application values'
$component = if ($target -eq 'canary') { 'api-canary' } else { 'api' }
foreach ($name in (@('rook-api', "rook-$component") | Sort-Object -Unique)) {
    $raw = kubectl --context $context -n $namespace get deployment $name -o json
    Check-Native
    $candidate = ($raw -join "`n") | ConvertFrom-Json
    if ($candidate.spec.replicas -lt 1 -or
        $candidate.status.observedGeneration -ne $candidate.metadata.generation -or
        $candidate.status.updatedReplicas -ne $candidate.spec.replicas -or
        $candidate.status.readyReplicas -ne $candidate.spec.replicas -or
        $candidate.status.availableReplicas -ne $candidate.spec.replicas) {
        throw "$name is not fully Ready; keep stable available and do not sync"
    }
}
$raw = kubectl --context $context -n $namespace get deployment "rook-$component" -o json
Check-Native
$d = ($raw -join "`n") | ConvertFrom-Json
if ($d.spec.replicas -lt 1 -or $d.status.observedGeneration -ne $d.metadata.generation -or
    $d.status.updatedReplicas -ne $d.spec.replicas -or $d.status.readyReplicas -ne $d.spec.replicas -or
    $d.status.availableReplicas -ne $d.spec.replicas -or
    $d.spec.template.spec.containers[0].image -ne $expectedImage -or
    $d.spec.template.metadata.labels.'app.kubernetes.io/version' -ne $expectedVersion) {
    throw 'Target not fully Ready at the expected image/version; do not sync'
}
@'
import json, math, sys, urllib.request
target = sys.argv[1]
base = 'http://rook-api-' + target + ':8000'
for path, expected in [('/health/live', 'alive'), ('/health/ready', 'ready')]:
    with urllib.request.urlopen(base + path, timeout=15) as r:
        assert r.status == 200 and json.load(r)['status'] == expected
if target == 'canary':
    with urllib.request.urlopen(base + '/services/frontend/metrics', timeout=15) as r:
        body = json.load(r)
        assert r.status == 200
        for key in ('request_rate', 'p95_latency'):
            metric = body['metrics'][key]
            assert metric['status'] == 'measured' and math.isfinite(metric['value'])
        print(json.dumps(body))
print('Direct target gate passed')
'@ | kubectl --context $context -n $namespace exec -i deployment/rook-api -- python - $target
Check-Native
```

After syncing, `kubectl --context docker-desktop -n rook-k8s-local get service rook-api -o yaml`
must select `api-canary` for canary or `api` for stable. Inspect
`kubectl --context docker-desktop -n rook-k8s-local get endpointslices -l kubernetes.io/service-name=rook-api -o yaml`
and inspect every Ready target Pod: UID must match targetRef UID and component,
image and version must match the chosen deployment. A readiness race remains
possible; stop and explicitly roll back on failed post-switch checks.

Preferred rollback is a reviewed Git desired-state reversal and manual sync.
Alternatively the Argo UI History and Rollback action can restore a reviewed
successful deployment (prune unchecked); review its entire chart/values/image
set and database compatibility first. History rollback does not update Git or
the Application spec: immediately reconcile those to the intended revision/values
before any further sync. Never use stale Helm history after adoption. Neither
kind of rollback undoes schema/data writes, proves service recovery, or resolves
an incident. Real workload telemetry is evidence, not a fabricated rollout result.

## 6. Runtime verification and safe detachment

Use separate localhost-only port-forward terminals:

```powershell
kubectl --context docker-desktop -n rook-k8s-local port-forward --address 127.0.0.1 service/rook-api 8003:8000
```

```powershell
kubectl --context docker-desktop -n rook-k8s-local port-forward --address 127.0.0.1 service/rook-frontend 8083:8080
```

```powershell
Invoke-RestMethod http://127.0.0.1:8003/health/live
Invoke-RestMethod http://127.0.0.1:8003/health/ready
Invoke-RestMethod http://127.0.0.1:8003/services/frontend/metrics
(Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8083/).StatusCode
Invoke-RestMethod http://127.0.0.1:8083/api/health/ready
```

Compare PVC/Secret UIDs with the baseline, ensure PostgreSQL and worker remain
Ready and worker logs show evaluations. Measurements must remain measured or
explicitly stale/insufficient/unavailable, never invented healthy values. Generated
traffic and controlled failures are allowed only as real running-software evidence.

To detach **only the Application**, first ensure no sync is running and inspect
its finalizers. The provided manifest has none; stop if another tool added one.

```powershell
$raw = kubectl --context docker-desktop -n argocd get application rook -o json
Check-Native
$app = ($raw -join "`n") | ConvertFrom-Json
if ($app.metadata.finalizers.Count -gt 0 -or $app.operation -or
    $app.status.operationState.phase -in @('Running','Terminating')) {
    throw 'Application is not safe to detach; inspect finalizers/active operation'
}
kubectl --context docker-desktop -n argocd delete application rook --cascade=orphan
Check-Native
kubectl --context docker-desktop -n rook-k8s-local get pods,pvc
Check-Native
kubectl --context docker-desktop -n rook-k8s-local get secret rook-db -o name
Check-Native
```

Do not delete the namespace, PVC, Secret, Helm release, AppProject or Argo CD
installation as part of detachment. Workloads keep running without reconciliation.
Returning to Helm needs a separate reviewed ownership/values handoff; old Helm
metadata is stale. There are no destructive cleanup commands in this runbook.

## Validation status and offline commands

Runtime baseline observed 2026-09-28: Docker Desktop node and API, canary, worker,
frontend, PostgreSQL Ready; API liveness/readiness and frontend returned HTTP 200.
Real frontend metrics at evaluation timestamp `1790632420.7284572` were request
rate `11.550625658889858`, p95 `0.0371467391304348`, error ratio `0.0`, all measured.
These historical readings are not expected values or fixtures. Worker logs showed
successful evaluations. No workloads, PVCs or Secrets were modified.

**Argo CD runtime is pending:** no deployments/statefulsets in `argocd`, and
`applications.argoproj.io` CRD returned NotFound. No Argo installation, Application
apply, adoption or sync was attempted. Healthy/Synced and GitOps rollback are not
claimed. User installation, environment review and explicit sync remain necessary.

Offline validation completed: 120 backend tests passed, one opt-in PostgreSQL
integration test skipped, two dependency deprecation warnings; 21 frontend tests,
TypeScript and production build passed. Helm 4.2.3 lint/default/canary rendering,
eight chart tests, seven new GitOps tests and five Helm switch/rollback tests passed.
YAML, TOML, OpenAPI, Python syntax, both PowerShell scripts and all 12 PowerShell
blocks in this runbook parsed successfully. Actionlint and whitespace/diff checks
passed. The secret-pattern check found only an intentionally rejected test-fixture
URL in `test_gitops.py`, not a real credential. CRD server-side validation remains
pending until Argo CD is installed; offline contracts do not replace that check.

With Helm on this process's PATH, use the existing isolated CI tooling environment:

```powershell
uv run --no-project --python 3.13.13 --with-requirements scripts/ci/requirements.txt python deploy/gitops/argocd/test_gitops.py
uv run --no-project --python 3.13.13 --with-requirements scripts/ci/requirements.txt python scripts/ci/check_helm.py
& ./deploy/helm/rook/tests/switch-api.tests.ps1
uv run --project apps/api --locked python scripts/ci/check_backend.py
git diff --check
```

Official references: [Helm rendering/release naming](https://argo-cd.readthedocs.io/en/stable/user-guide/helm/),
[Application fields](https://argo-cd.readthedocs.io/en/stable/user-guide/application-specification/),
[manual kubectl sync](https://argo-cd.readthedocs.io/en/stable/user-guide/sync-kubectl/),
[sync options](https://argo-cd.readthedocs.io/en/stable/user-guide/sync-options/),
[non-cascading deletion](https://argo-cd.readthedocs.io/en/stable/user-guide/app_deletion/).
