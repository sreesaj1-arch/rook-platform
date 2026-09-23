# Rook on local Kubernetes

Docker Compose remains the primary development path. This chart packages the
existing API, worker, PostgreSQL and React dashboard without changing Compose or
the external Demo. Kubernetes runtime verification is pending until a local cluster
is available. There is no ingress, public database, authentication, cloud deployment,
telemetry generator, or Kubernetes event collector in this chart.

## Prerequisites and images

Use kubectl, Helm 3, and a running local Kubernetes cluster (kind or Docker Desktop)
with a default dynamic storage provisioner, or set `postgres.storage.storageClass`.
Check `kubectl config get-contexts` and select your local context explicitly. Do not
run these commands against a remote cluster. This chart creates fresh product state
in a dedicated namespace; it does not import Compose's PostgreSQL volume.

From the repository root in PowerShell:

```powershell
docker build -t rook-backend:k8s-local apps/api
if ($LASTEXITCODE -ne 0) { throw 'Backend build failed' }
docker build -t rook-frontend:k8s-local apps/frontend
if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed' }
# For an existing kind cluster named rook-local:
kind load docker-image rook-backend:k8s-local rook-frontend:k8s-local --name rook-local
if ($LASTEXITCODE -ne 0) { throw 'Image loading failed' }
```

For another local runtime, import these images using that runtime's supported
method or set registry-accessible image references. Do not assume that Docker's
host image store is automatically shared with Kubernetes. Use a new image tag on
each rebuild; `IfNotPresent` may otherwise reuse an old node image.

## Render and install

Choose the actual local context below (`kind-rook-local` is only an example):

```powershell
$context = 'kind-rook-local'
$namespace = 'rook-k8s-local'
kubectl --context $context get nodes
if ($LASTEXITCODE -ne 0) { throw 'Local cluster unavailable; stop' }
helm lint deploy/helm/rook
if ($LASTEXITCODE -ne 0) { throw 'Helm lint failed' }
helm template rook deploy/helm/rook --namespace $namespace
if ($LASTEXITCODE -ne 0) { throw 'Helm rendering failed' }
kubectl --context $context create namespace $namespace
if ($LASTEXITCODE -ne 0) { throw 'Inspect the namespace before proceeding; do not overwrite unrelated resources' }
```

The default configuration references an existing Secret `rook-db` with key
`password`. Create it in this namespace without placing a password in command
history, tracked files, or Helm values:

```powershell
$secure = Read-Host 'New local PostgreSQL password' -AsSecureString
$pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
try {
    $password = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
    $secret = @{
        apiVersion = 'v1'; kind = 'Secret'
        metadata = @{name = 'rook-db'; namespace = $namespace}
        type = 'Opaque'; stringData = @{password = $password}
    }
    $secret | ConvertTo-Json -Depth 5 | kubectl --context $context create -f -
    if ($LASTEXITCODE -ne 0) { throw 'Secret creation failed' }
} finally {
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer)
    Remove-Variable password,secret,secure -ErrorAction SilentlyContinue
}

helm upgrade --install rook deploy/helm/rook --kube-context $context --namespace $namespace `
    --set api.image=rook-backend:k8s-local --set worker.image=rook-backend:k8s-local `
    --set frontend.image=rook-frontend:k8s-local --wait --timeout 10m
if ($LASTEXITCODE -ne 0) { throw 'Install not Ready; inspect pods and logs before retrying' }
kubectl --context $context -n $namespace get pods,pvc,services
kubectl --context $context -n $namespace logs deployment/rook-worker --tail=30
```

With telemetry unset, worker evaluation attempts report unavailable; a Ready pod
is not evidence of monitored-service health. To receive measurements, supply a
reachable source as described below. The API init container runs the existing
idempotent `incident_cli init-db` before serving traffic. It retries through the
Kubernetes init-container lifecycle if PostgreSQL has not started. The worker also
retains its existing idempotent initialization and PostgreSQL ownership lock.

The chart can optionally create a Secret using `postgres.secret.create=true` and
`postgres.secret.password` in an untracked values file. Helm then stores that value
in release metadata and includes it in rendered output. Prefer the existing Secret
path above. Secret changes require explicit API/worker rollouts. PostgreSQL credentials
and database/user values initialize an empty volume only: changing values does not
rotate an existing database password or migrate stored product state.

## Local access and verification

Use separate terminals for each port-forward, using your actual context. These
ports avoid Compose's 8001/8080 bindings. Ctrl+C stops only that port-forward.

```powershell
kubectl --context kind-rook-local -n rook-k8s-local port-forward --address 127.0.0.1 service/rook-frontend 8083:8080
```

```powershell
kubectl --context kind-rook-local -n rook-k8s-local port-forward --address 127.0.0.1 service/rook-api 8003:8000
```

```powershell
Invoke-RestMethod http://127.0.0.1:8003/health/live
Invoke-RestMethod http://127.0.0.1:8003/health/ready
(Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8083/).StatusCode
Invoke-RestMethod http://127.0.0.1:8083/api/health/ready
Invoke-RestMethod http://127.0.0.1:8083/api/incidents
```

Open `http://127.0.0.1:8083` for the existing dashboard. Nginx strips `/api/` and
forwards requests to the release's API Service. It preserves methods, bodies,
query strings and API error statuses; it does not retry incident POSTs. The Vite
proxy on port 5173 is unchanged. PostgreSQL has only an internal headless ClusterIP
Service; there is no host or NodePort database publication.

## Telemetry and values

Supply values using `-f <your-local-values.yaml>` on both `helm template` and
`helm upgrade --install`. Keep local files under ignored `tmp/` and keep credentials
out of source URLs. Example shape (replace addresses with verified reachable ones):

```yaml
telemetry:
  prometheusUrl: http://prometheus.monitoring.svc.cluster.local:9090
  namespace: opentelemetry-demo
  sources:
    portable-http:
      profile: local-http
      url: http://portable-prometheus.monitoring.svc.cluster.local:9090
worker:
  services: [frontend, portable-http]
  intervalSeconds: 30
  errorRatio: 0.05
  p95Seconds: 0.5
```

These addresses are examples, not services installed by this chart. The existing
Demo can remain in Docker, but Docker Compose DNS names do not resolve in pods.
Likewise `127.0.0.1` inside a pod is not the host. The Demo's loopback-only host
publication may not be reachable through `host.docker.internal` on your runtime.
Use a verified network path, an operator-managed local relay, or an existing
in-cluster Prometheus; do not silently expose the Demo publicly or modify its checkout.
If there is no reachable source, leave the URL unset. No measurements or incidents
are seeded. Missing evidence retains the existing unavailable/stale/insufficient
semantics. Source namespace and change environment must remain stable per database.

Other values cover API/worker/frontend image, pull policy, replicas and resources;
PostgreSQL image, database/user, Secret reference, storage class and size; Prometheus
timeouts, freshness and service-to-profile routing; and change correlation window.
PostgreSQL is deliberately one instance with no replication. Keep one worker by
default; additional replicas still contend on the existing ownership lock and do
not promise parallel scheduling. Worker readiness/liveness checks loop progress,
not database or Prometheus health. API liveness is process-only and readiness checks
the database. Frontend probes check only the static server. API/worker use UID/GID
10001 with writable `/tmp`; PostgreSQL uses UID/GID 999 on its volume.

## Safe uninstall and limitations

After confirming the context, namespace and release belong to this installation:

```powershell
helm uninstall rook --kube-context kind-rook-local --namespace rook-k8s-local
kubectl --context kind-rook-local -n rook-k8s-local get pvc
```

This removes only the release resources. StatefulSet-created PVCs are retained;
do not delete the namespace, PVCs or cluster to clean up this milestone. Keep the
original database Secret for reinstalling against retained data. An externally
created Secret is not removed by Helm; a chart-created Secret is removed on
uninstall, so securely preserve its password beforehand. No volume deletion,
Docker prune, or unrelated-resource cleanup is part of these instructions.

This is a single-node local deployment foundation, not HA, backups, a migration
framework, a completed canary/rollback demonstration, or automatic Kubernetes
deployment observation. Storage resizing and PostgreSQL major upgrades require
separate planning. Existing Compose remains usable and independent.

## Validation status

The implementation pass ran 120 backend tests successfully (one optional integration
test skipped; two dependency deprecation warnings), 21 frontend tests, TypeScript,
and the production Vite build. Python syntax, TOML, OpenAPI, chart metadata/values
YAML, JSON Schema validation, template control-block balance, and whitespace checks
passed. Control-block checks are not a substitute for Helm lint or manifest rendering.
Helm was absent from PATH and `tmp/helm-tools` was empty; no tools were downloaded
during this pass. `kubectl config get-contexts` returned no contexts. Helm lint,
rendered Kubernetes YAML validation, container execution, and cluster runtime checks
remain pending. No Kubernetes pods or fabricated runtime results are claimed.
