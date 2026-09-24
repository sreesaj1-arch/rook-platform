# Local API canary and operator rollback

This exercise keeps `rook-api` running while `rook-api-canary` is checked.
`rook-api-stable` and `rook-api-canary` are direct ClusterIP Services; the existing
`rook-api` Service selects exactly one component using `apiTraffic: stable|canary`.
There is no weighted traffic, automatic promotion, or automatic rollback. The
frontend continues proxying to `rook-api`; worker and PostgreSQL are unchanged.

## Preconditions

Use an existing local release installed using [the Kubernetes runbook](README.md),
Helm 3.14 or newer, kubectl, and Docker. Keep its namespace, Secret, database,
telemetry settings and images. Run from the repository root. Do not run concurrent
upgrades. Review the chart before switching: Helm applies the whole chart.

Use only schema-compatible API builds: both versions share the database and run
the existing idempotent schema initializer. Routing rollback does not undo database
changes or writes. This first exercise rebuilds the same application under a new
unique image tag and pod version label. It proves routing and rollback mechanics,
not a behavioral or performance improvement. No fake incidents are needed.

The configured Prometheus must be reachable from pods with real workload traffic.
The switch gate requires measured request rate and p95 for the selected service.
Missing error evidence may remain null/insufficient_data. These metrics describe
the monitored application, not Rook API latency or canary-specific performance.
No generated metric values, seeded incidents, or assumed healthy data are allowed.

## 1. Inspect and prepare (stop on any failed command)

```powershell
$ErrorActionPreference = 'Stop'
$context = 'docker-desktop'
$namespace = 'rook-k8s-local'
$release = 'rook'
$chart = 'deploy/helm/rook'
function Check-Native { if ($LASTEXITCODE -ne 0) { throw 'Command failed; stop and inspect' } }
kubectl --context $context -n $namespace get deployments,pods,services,pvc
Check-Native
helm status $release --kube-context $context -n $namespace
Check-Native
$stableJson = kubectl --context $context -n $namespace get deployment "$release-api" -o json
Check-Native
$stableImage = (($stableJson -join "`n") | ConvertFrom-Json).spec.template.spec.containers[0].image
$version = 'canary-' + (Get-Date -Format 'yyyyMMddHHmmss')
$canaryImage = "rook-backend:$version"
docker build -t $canaryImage apps/api
Check-Native
# For kind instead: kind load docker-image $canaryImage --name rook-local
# Docker Desktop must share the image with its Kubernetes runtime. If image pull
# fails, stop and import it using your runtime's supported method; do not retag stable.
docker image inspect $canaryImage --format '{{.Id}}'
Check-Native
helm lint $chart
Check-Native
helm template $release $chart --set canary.enabled=true --set apiTraffic=stable
Check-Native
helm template $release $chart --set canary.enabled=true --set apiTraffic=canary
Check-Native
```

## 2. Stage canary while stable serves

`--reset-then-reuse-values` adds new chart defaults while preserving the release's
existing custom configuration. Inspect the rollout; do not change worker, frontend,
database or telemetry settings during this exercise. Stable gains a version label
on the first upgrade, so wait for that rollout too. Deployment selectors are unchanged.

```powershell
helm upgrade $release $chart --kube-context $context -n $namespace `
    --reset-then-reuse-values --set apiTraffic=stable --set api.version=stable `
    --set canary.enabled=true --set-string "canary.image=$canaryImage" `
    --set-string "canary.version=$version" --set canary.replicas=1 --wait --timeout 10m
Check-Native
kubectl --context $context -n $namespace rollout status deployment/rook-api --timeout=120s
Check-Native
kubectl --context $context -n $namespace rollout status deployment/rook-api-canary --timeout=120s
Check-Native
kubectl --context $context -n $namespace get pods -l app.kubernetes.io/instance=rook `
    -o 'custom-columns=NAME:.metadata.name,COMPONENT:.metadata.labels.app\.kubernetes\.io/component,VERSION:.metadata.labels.app\.kubernetes\.io/version,IMAGE:.spec.containers[0].image,IMAGE_ID:.status.containerStatuses[0].imageID,READY:.status.containerStatuses[0].ready'
Check-Native
kubectl --context $context -n $namespace get service rook-api -o jsonpath='{.spec.selector}'
Check-Native
```

The selector must still be component `api`. If staging fails, inspect pods/events
and logs; do not switch. Startup/liveness check `/health/live`; readiness checks
`/health/ready`. Readiness is database availability, not monitored-service health.

## 3. Verify directly, then explicitly switch

```powershell
& "$chart/switch-api.ps1" -Context $context -Namespace $namespace -Release $release `
    -Target canary -ExpectedImage $canaryImage -ExpectedVersion $version -Service frontend
kubectl --context $context -n $namespace get service rook-api -o jsonpath='{.spec.selector}'
Check-Native
kubectl --context $context -n $namespace get endpointslices -l kubernetes.io/service-name=rook-api -o wide
Check-Native
kubectl --context $context -n $namespace logs deployment/rook-api-canary --tail=30
Check-Native
```

The script checks complete rollout/readiness and expected image/version in both
the Deployment and Helm values. It sends real liveness, readiness and metrics
requests through the direct canary Service from the stable API pod before changing
anything. A failed gate leaves traffic unchanged. It then performs a Helm upgrade
setting `apiTraffic=canary`, checks ready EndpointSlice pod identities, and sends
new requests through the active Service. Every endpoint must belong to the canary.

Keep the same reviewed chart and images throughout. A readiness race or a failure
after the switch can still interrupt traffic; there is no automatic fallback.
On any post-switch error inspect the actual selector and use the rollback below.
Do not bypass the gate with a raw selector patch or an unchecked Helm upgrade.

An existing `kubectl port-forward service/rook-api` stays connected to its selected
pod and cannot prove a switch. Restart it after switching, or use the script's
fresh in-cluster Service requests. Frontend port-forwarding stays on the frontend
pod and its `/api` proxy uses the active Service.

## 4. Explicit operator rollback

```powershell
& "$chart/switch-api.ps1" -Context $context -Namespace $namespace -Release $release `
    -Target stable -ExpectedImage $stableImage -ExpectedVersion stable
kubectl --context $context -n $namespace get service rook-api -o jsonpath='{.spec.selector}'
Check-Native
kubectl --context $context -n $namespace get endpointslices -l kubernetes.io/service-name=rook-api -o wide
Check-Native
kubectl --context $context -n $namespace logs deployment/rook-api --tail=30
Check-Native
```

Rollback requires a Ready stable deployment, the expected image/version, and real
health responses. It does not require Prometheus to recover before restoring stable.
The script verifies selector `api`, stable ready endpoint identities and HTTP 200
health responses. Stable has remained running throughout; canary remains available
for inspection. The operator may disable it **after** verifying stable routing:

```powershell
helm upgrade $release $chart --kube-context $context -n $namespace `
    --reuse-values --set apiTraffic=stable --set canary.enabled=false --wait --timeout 5m
Check-Native
```

No PVC, namespace, Secret or unrelated workload is deleted. Persist the reviewed
`apiTraffic` choice in your desired-state values before the next deployment so an
older values file cannot accidentally switch it back. Do not use automatic rollback
flags. A full `helm rollback` changes the entire release and should only be used
after reviewing that revision's images, configuration and database compatibility;
the targeted traffic reversal above is preferred here.

## Validation record and limitations

The exercise completed on Docker Desktop Kubernetes on 2026-09-23 using the
existing WinGet Helm 4.3.0 executable (not initially on this session's PATH).
No tool download or global PATH change was needed.

- Built `rook-backend:canary-20260923-01` from the unchanged backend application.
  Runtime image digest: `sha256:33fe4701ac7fdec28f06aa485b4f7a16d2157f43b0b290501ee39b6a02b3f465`.
- Revision 3 staged canary with stable traffic. Both APIs became Ready. The initial
  upgrade also rolled frontend/worker because their configuration checksum changed;
  they returned Ready. PostgreSQL remained Ready.
- Direct canary `/health/live`, `/health/ready` and metrics checks returned HTTP 200.
  At evaluation timestamp `1790207182.881865`, real frontend telemetry showed
  `11.579842157459185` requests/second, p95 `0.03553453947368422` seconds and measured
  error ratio `0.0`. These are historical observations, not configured values.
- Revision 4 explicitly switched the API Service to `api-canary`.
  Ready endpoint `10.244.0.15` belonged to `rook-api-canary-6ff9579ddd-xl9ns` with
  version label `canary-20260923-01`. Active-Service health and metrics returned 200.
  Comparing rendered release manifests confirmed this switch changed only the API Service.
- Revision 5 explicitly switched back to stable `rook-backend:local`.
  Ready endpoint `10.244.0.14` belonged to `rook-api-598d8d7ffd-cxgxr`.
  The script checked endpoint pod identities and new real Service health requests.
  Post-rollback metrics, incidents and frontend API proxy returned 200; worker logs
  showed successful evaluations. No incident was fabricated or required.
- Final state: stable serves traffic; canary remains Ready for inspection. No volumes
  or unrelated resources were removed. No automatic rollback was used.

This demonstrates routing and rollback of a versioned same-application rebuild.
It does not establish canary-specific latency, weighted traffic splitting,
zero-downtime guarantees, schema migration rollback, or behavioral differences.
Readiness can change after a successful gate. Automated rollback remains future work.

Validation: 120 backend tests passed (one skipped; two dependency deprecation
warnings), 21 frontend unit tests and the existing browser test passed against the
running Kubernetes frontend. Browser fixtures were confined to test-only UI checks;
its live metrics check used the actual API. TypeScript and production build passed.
Eight chart tests and five operator-switch tests passed, including both routing
renders and unchanged non-API resources. Operator-switch unit tests use command
doubles only; the live results above are separate evidence. Helm lint passed
(icon recommendation only). Python/PowerShell syntax, TOML, YAML, OpenAPI and
whitespace checks passed. Run the additional checks with:

```powershell
# Python environment needs the already available PyYAML and jsonschema tools.
# Helm must be on this process's PATH for the rendering tests.
python deploy/helm/rook/tests/test_chart.py
& ./deploy/helm/rook/tests/switch-api.tests.ps1
```

References: [Helm upgrade options](https://docs.helm.sh/docs/helm/helm_upgrade/),
[kubectl port-forward behavior](https://kubernetes.io/docs/reference/kubectl/generated/kubectl_port-forward/).
