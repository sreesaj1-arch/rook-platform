# Explicit operator action. No scheduler, automatic rollback, or cluster creation.
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$Context,
    [Parameter(Mandatory)][string]$Namespace,
    [ValidatePattern('^[a-z0-9]([-a-z0-9]*[a-z0-9])?$')][string]$Release = 'rook',
    [Parameter(Mandatory)][ValidateSet('stable','canary')][string]$Target,
    [Parameter(Mandatory)][string]$ExpectedImage,
    [Parameter(Mandatory)][string]$ExpectedVersion,
    [ValidatePattern('^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}$')][string]$Service = 'frontend'
)
$ErrorActionPreference = 'Stop'
$kube = @('--context', $Context, '--namespace', $Namespace, '--request-timeout=15s')
function Read-Kube([string[]]$Arguments) {
    $result = & kubectl @kube @Arguments
    if ($LASTEXITCODE -ne 0) { throw "kubectl failed: $($Arguments[0])" }
    return ($result -join "`n") | ConvertFrom-Json
}
function Assert-Ready([string]$Name) {
    $deployment = Read-Kube -Arguments @('get','deployment',$Name,'-o','json')
    if ($deployment.spec.replicas -lt 1 -or
        $deployment.status.observedGeneration -ne $deployment.metadata.generation -or
        $deployment.status.updatedReplicas -ne $deployment.spec.replicas -or
        $deployment.status.readyReplicas -ne $deployment.spec.replicas -or
        $deployment.status.availableReplicas -ne $deployment.spec.replicas) {
        throw "$Name is not fully rolled out and Ready; traffic unchanged"
    }
    return $deployment
}
$null = Get-Command helm -ErrorAction Stop
$stable = Assert-Ready "$Release-api"
$component = if ($Target -eq 'canary') { 'api-canary' } else { 'api' }
$deployment = Assert-Ready "$Release-$component"
if ($deployment.spec.template.spec.containers[0].image -ne $ExpectedImage -or
    $deployment.spec.template.metadata.labels.'app.kubernetes.io/version' -ne $ExpectedVersion) {
    throw 'Image/version does not match the operator expectation; traffic unchanged'
}
# Check Helm desired state too, so an upgrade cannot replace the verified image.
$valuesJson = & helm get values $Release --kube-context $Context --namespace $Namespace --all -o json
if ($LASTEXITCODE -ne 0) { throw 'Cannot read Helm release values' }
$values = ($valuesJson -join "`n") | ConvertFrom-Json
$selected = if ($Target -eq 'canary') { $values.canary } else { $values.api }
if (($Target -eq 'canary' -and -not $values.canary.enabled) -or
    $selected.image -ne $ExpectedImage -or $selected.version -ne $ExpectedVersion) {
    throw 'Helm values differ from verified workload; traffic unchanged'
}
# Use a new in-cluster connection to the dedicated Service, not a stale port-forward.
$probe = @'
import json, math, sys, urllib.request
base, service, require_metrics = sys.argv[1:]
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
for path, expected in (('/health/live','alive'),('/health/ready','ready')):
    with opener.open(base + path, timeout=15) as response:
        body=json.load(response)
        assert response.status == 200 and body['status']==expected
        print(path, response.status, body)
if require_metrics == 'canary':
    with opener.open(base + '/services/' + service + '/metrics', timeout=15) as response:
        body=json.load(response)
        assert response.status == 200 and body['service_name']==service
        for name in ('request_rate','p95_latency'):
            metric=body['metrics'][name]
            assert metric['status']=='measured' and math.isfinite(metric['value'])
        print(json.dumps(body))
'@
$probe | & kubectl @kube exec -i "deployment/$Release-api" -- python - "http://${Release}-api-${Target}:8000" $Service $Target
if ($LASTEXITCODE -ne 0) { throw 'Direct verification failed; traffic unchanged' }
$null = Assert-Ready "$Release-$component"
Write-Host "Operator requested switch to $Target ($ExpectedImage, $ExpectedVersion)."
& helm upgrade $Release $PSScriptRoot --kube-context $Context --namespace $Namespace `
    --reuse-values --set "apiTraffic=$Target" --wait --timeout 5m
if ($LASTEXITCODE -ne 0) { throw 'Helm upgrade failed; inspect actual selector. No automatic rollback was attempted.' }
$active = Read-Kube -Arguments @('get','service',"$Release-api",'-o','json')
if ($active.spec.selector.'app.kubernetes.io/component' -ne $component) { throw 'Unexpected active selector' }
$verified = $false
for ($attempt = 0; $attempt -lt 30; $attempt++) {
    $slices = Read-Kube -Arguments @('get','endpointslices','-l',"kubernetes.io/service-name=$Release-api",'-o','json')
    $endpoints = @($slices.items | ForEach-Object { $_.endpoints } | Where-Object { $_.conditions.ready -eq $true })
    if ($endpoints.Count) {
        $correct = $true
        foreach ($endpoint in $endpoints) {
            if ($endpoint.targetRef.kind -ne 'Pod') { $correct = $false; break }
            $pod = Read-Kube -Arguments @('get','pod',$endpoint.targetRef.name,'-o','json')
            if ($pod.metadata.uid -ne $endpoint.targetRef.uid -or
                $pod.metadata.labels.'app.kubernetes.io/component' -ne $component -or
                $pod.metadata.labels.'app.kubernetes.io/version' -ne $ExpectedVersion -or
                $pod.spec.containers[0].image -ne $ExpectedImage) { $correct = $false; break }
        }
        if ($correct) { $verified = $true; break }
    }
    Start-Sleep -Seconds 2
}
if (-not $verified) { throw 'Endpoint convergence unverified. Inspect routing and perform explicit rollback if needed.' }
$probe | & kubectl @kube exec -i "deployment/$Release-api" -- python - "http://${Release}-api:8000" $Service $Target
if ($LASTEXITCODE -ne 0) { throw 'Active-Service verification failed. No automatic rollback was attempted.' }
Write-Host "Verified $Target selector, Ready endpoint pod identities, and new Service requests."
