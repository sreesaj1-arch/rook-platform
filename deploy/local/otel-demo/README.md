# Pinned local OpenTelemetry Demo

This prepares Demo **3.1.0**, commit
`dedc0178918e260823323b8d95005a8cb924b007`, in sibling checkout
`../rook-otel-demo`. It does not implement Rook telemetry queries.

Use the upstream `start-minimal` file combination: `compose.yaml`,
`compose.observability.yaml`, and the empty `compose.extras.yaml`, followed by
Rook's override. This retains observability, the application, and its dependencies;
Kafka, accounting, fraud detection, AI, and profiling layers are not selected.
The release's Locust generator sends real automated requests. No failures are
injected here. The user has since verified startup and frontend metrics below.

`demo.env` overrides upstream `latest` workload tags and the old resource version.
Other image tags come from the pinned upstream `.env`; these are version tags,
not immutable registry digests. The user has successfully started the Demo.
The sibling `.env.override` and Rook's root `.env` are deliberately not loaded.
Shell variables take precedence over environment files, so the sequence rejects
overlapping variables without displaying their values or changing the shell.

Only `127.0.0.1:8080` (storefront and proxied UIs) and `127.0.0.1:9090`
(Prometheus) are published. Port 8001 stays available for Rook. `!override`
replaces port lists instead of merging public and loopback bindings; Compose
**2.24.4+** is required. Container ports, DNS, and the upstream
`opentelemetry-demo` bridge network are retained. Rook's optional
`docker-compose.telemetry.yml` now attaches only its API to this network.
The flagd UI's bind mount is read-only to prevent edits to the upstream checkout;
feature-flag editing through that UI is intentionally unavailable in this setup.

The user reported 1710 GB free on C:, 15.43 GiB allocated Docker memory, and no
running containers. Those are user observations, not new measurements here.
The user subsequently verified Demo 3.1.0 running on `opentelemetry-demo`, with
Prometheus reachable at host `http://127.0.0.1:9090` and internal
`http://prometheus:9090`. The assistant subsequently validated the merged Compose
configuration without contacting the engine. No Docker runtime checks were rerun.

For `frontend`, the user observed `http_server_request_duration_seconds_count`
and `http_server_request_duration_seconds_bucket`, with `service_name="frontend"`,
`service_namespace="opentelemetry-demo"`, `service_version="3.1.0"`,
`http_request_method`, and `http_response_status_code` labels. Observed response
codes were 200, 304, and 308. At evaluation time `1790012334`, five-minute queries
returned 12.554856282828768 requests/second, p95 0.023633056829430687 seconds, and
an empty 5xx error ratio. These are historical user observations, not fixtures,
expected constants, or proof of zero errors. New API runtime comparison remains
pending; see [API verification](../../../apps/api/live-telemetry.md).

## Ordered PowerShell sequence

Run from Rook's repository root in one session. Stop on any error. The guarded
block validates before pulling or starting anything. Do not bypass a failure or
replace pinned images with `latest`. Fixed upstream container and network names
allow only one copy; the first-start checks reject existing names rather than
removing unrelated resources. To inspect an already started instance, use the
status command below without repeating the first-start block.

```powershell
$rookRoot = (Get-Location).Path
$demoRoot = (Resolve-Path (Join-Path $rookRoot '../rook-otel-demo')).Path
$integration = Join-Path $rookRoot 'deploy/local/otel-demo'
$demoCompose = @(
    'compose', '--project-name', 'rook-otel-demo',
    '--project-directory', $demoRoot,
    '--env-file', (Join-Path $demoRoot '.env'),
    '--env-file', (Join-Path $integration 'demo.env'),
    '-f', (Join-Path $demoRoot 'compose.yaml'),
    '-f', (Join-Path $demoRoot 'compose.observability.yaml'),
    '-f', (Join-Path $demoRoot 'compose.extras.yaml'),
    '-f', (Join-Path $integration 'compose.override.yaml')
)

& {
    $ErrorActionPreference = 'Stop'
    # 1. Verify source and prevent shell overrides of the reproducible inputs.
    $head = git -C $demoRoot rev-parse HEAD
    if ($LASTEXITCODE -ne 0 -or $head -ne 'dedc0178918e260823323b8d95005a8cb924b007') {
        throw 'Unexpected Demo checkout; stop.'
    }
    $changes = git -C $demoRoot status --porcelain
    if ($LASTEXITCODE -ne 0 -or $changes) { throw 'Demo checkout must be clean; stop.' }
    $keys = Get-Content (Join-Path $demoRoot '.env'), (Join-Path $integration 'demo.env') |
        ForEach-Object { if ($_ -match '^([A-Za-z_][A-Za-z0-9_]*)=') { $Matches[1] } }
    foreach ($key in ($keys | Sort-Object -Unique)) {
        if ($null -ne [Environment]::GetEnvironmentVariable($key, 'Process')) {
            throw "Shell variable $key overrides the environment files; use a clean shell."
        }
    }

    # 2. Validate the merge without printing environment values.
    docker @demoCompose config --quiet
    if ($LASTEXITCODE -ne 0) { throw 'Compose validation failed; stop.' }
    $json = docker @demoCompose config --format json
    if ($LASTEXITCODE -ne 0) { throw 'Cannot inspect merged configuration; stop.' }
    $config = ($json -join "`n") | ConvertFrom-Json
    $ports = @()
    foreach ($entry in $config.services.PSObject.Properties) {
        $service = $entry.Value
        if ($service.image -match '^ghcr.io/open-telemetry/demo:') {
            if ($service.image -ne "ghcr.io/open-telemetry/demo:3.1.0-$($entry.Name)") {
                throw "Unexpected workload image for $($entry.Name); stop."
            }
        }
        if ($service.environment.OTEL_RESOURCE_ATTRIBUTES -and
            $service.environment.OTEL_RESOURCE_ATTRIBUTES -notmatch '(^|,)service.version=3\.1\.0(,|$)') {
            throw "Unexpected resource version for $($entry.Name); stop."
        }
        [pscustomobject]@{ Service = $entry.Name; Image = $service.image }
        foreach ($port in $service.ports) {
            $ports += "$($entry.Name) $($port.host_ip):$($port.published):$($port.target)/$($port.protocol)"
        }
    }
    $expected = @('frontend-proxy 127.0.0.1:8080:8080/tcp', 'prometheus 127.0.0.1:9090:9090/tcp')
    if (@(Compare-Object $expected $ports).Count -ne 0) { throw 'Unexpected publications; stop.' }
    $ports
    $fixedNames = @($config.services.PSObject.Properties.Value.container_name)
    Remove-Variable json, config # Do not print or save the resolved environment.

    # 3. Check engine, fixed names, and host ports before any download.
    $names = @(docker ps -a --format '{{.Names}}')
    if ($LASTEXITCODE -ne 0) { throw 'Docker inspection failed; stop.' }
    if (@($fixedNames | Where-Object { $_ -in $names }).Count) { throw 'Demo container name already exists; stop.' }
    $networks = @(docker network ls --format '{{.Name}}')
    if ($LASTEXITCODE -ne 0) { throw 'Network inspection failed; stop.' }
    if ('opentelemetry-demo' -in $networks) { throw 'Demo network already exists; stop.' }
    $listeners = @(Get-NetTCPConnection -State Listen)
    if (@($listeners | Where-Object { $_.LocalPort -in @(8080, 9090) }).Count) {
        throw 'Port 8080 or 9090 is occupied; leave its owner untouched and stop.'
    }

    # 4. Pull exact configured tags, then start the supported minimal stack.
    docker @demoCompose pull
    if ($LASTEXITCODE -ne 0) { throw 'Pinned image pull failed; stop.' }
    docker @demoCompose up --detach --no-build --pull never --wait --wait-timeout 300
    if ($LASTEXITCODE -ne 0) { throw 'Startup failed; inspect status below; do not retry blindly.' }

    # 5. Status. A started container is not proof of service metric availability.
    docker @demoCompose ps --all
    if ($LASTEXITCODE -ne 0) { throw 'Status inspection failed.' }
}

# After the block, status may also be inspected independently:
# docker @demoCompose ps --all
# When finished, run this shutdown command in the same session:
# docker @demoCompose down
```

The explicit project directory keeps build contexts and relative bind mounts in
the sibling checkout, even though the final override lives in Rook. Keep the
same `$demoCompose` arguments for status and shutdown. `down` removes this
project's containers and network, without deleting volumes or images; do not add
`--volumes`, `--remove-orphans`, or use Docker prune. It does not promise retention
of telemetry in container writable layers.

After successful startup, browse `http://127.0.0.1:8080/` to make real requests.
Grafana and Locust are proxied under `/grafana/` and `/loadgen/`. Prometheus is at
`http://127.0.0.1:9090/`. Observe actual series before implementing queries and
allow at least five minutes of traffic. No data must be interpreted as unknown
or insufficient evidence, never as automatically healthy. Upstream minimal mode
still loads some Collector configuration for absent optional backends; startup
status alone does not establish a fully successful telemetry pipeline.
