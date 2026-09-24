# Test-only command doubles. No external commands, metrics, or cluster writes.
$ErrorActionPreference = 'Stop'
$switch = Join-Path $PSScriptRoot '../switch-api.ps1'
function helm {
    $global:LASTEXITCODE = 0
    if ($args[0] -eq 'get') {
        return @{api=@{image='stable:test';version='stable'};canary=@{enabled=$true;image='canary:test';version='test'}} | ConvertTo-Json
    }
    if ($args[0] -eq 'upgrade') {
        $global:rookTestupgrades++
        $global:rookTestmockActive = if ('apiTraffic=canary' -in $args) { 'api-canary' } else { 'api' }
        return
    }
    throw 'Unexpected Helm invocation'
}
function kubectl {
    $global:LASTEXITCODE = 0
    $tokens = @($args)
    if ('exec' -in $tokens) {
        $global:rookTestprobes++
        if ($global:rookTestfailProbe) { $global:LASTEXITCODE = 1 }
        return
    }
    $index = [Array]::IndexOf($tokens, 'get')
    if ($index -lt 0) { throw 'Missing get verb: argument forwarding broken' }
    $kind = $tokens[$index + 1]
    $name = $tokens[$index + 2]
    $component = if ($name -eq 'rook-api-canary') { 'api-canary' } else { 'api' }
    $image = if ($component -eq 'api-canary') { 'canary:test' } else { 'stable:test' }
    $version = if ($component -eq 'api-canary') { 'test' } else { 'stable' }
    switch ($kind) {
        'deployment' {
            $ready = if ($global:rookTestunready -and $component -eq 'api-canary') { 0 } else { 1 }
            return @{
                metadata=@{generation=1}
                spec=@{replicas=1;template=@{metadata=@{labels=@{'app.kubernetes.io/version'=$version}};spec=@{containers=@(@{image=$image})}}}
                status=@{observedGeneration=1;updatedReplicas=1;readyReplicas=$ready;availableReplicas=$ready}
            } | ConvertTo-Json -Depth 10
        }
        'service' { return @{spec=@{selector=@{'app.kubernetes.io/component'=$global:rookTestmockActive}}} | ConvertTo-Json -Depth 5 }
        'endpointslices' {
            return @{items=@(@{endpoints=@(@{conditions=@{ready=$true};targetRef=@{kind='Pod';name="rook-$global:rookTestmockActive";uid='test-only'}})})} | ConvertTo-Json -Depth 8
        }
        'pod' {
            return @{metadata=@{uid='test-only';labels=@{'app.kubernetes.io/component'=$component;'app.kubernetes.io/version'=$version}};spec=@{containers=@(@{image=$image})}} | ConvertTo-Json -Depth 8
        }
        default { throw "Unexpected kubectl kind: $kind" }
    }
}

$cases = @(
    @{name='canary success';target='canary';image='canary:test';version='test';unready=$false;failProbe=$false;expected=1},
    @{name='unready refuses switch';target='canary';image='canary:test';version='test';unready=$true;failProbe=$false;expected=0},
    @{name='image mismatch refuses switch';target='canary';image='wrong:test';version='test';unready=$false;failProbe=$false;expected=0},
    @{name='failed direct check refuses switch';target='canary';image='canary:test';version='test';unready=$false;failProbe=$true;expected=0},
    @{name='explicit stable rollback';target='stable';image='stable:test';version='stable';unready=$true;failProbe=$false;expected=1}
)
foreach ($case in $cases) {
    $global:rookTestupgrades=0; $global:rookTestprobes=0; $global:rookTestmockActive='api'
    $global:rookTestunready=$case.unready; $global:rookTestfailProbe=$case.failProbe
    $failed=$false
    try {
        & $switch -Context test-only -Namespace test-only -Target $case.target -ExpectedImage $case.image -ExpectedVersion $case.version
    } catch { $failed=$true }
    if ($global:rookTestupgrades -ne $case.expected -or $failed -ne ($case.expected -eq 0)) {
        throw "Failed test: $($case.name) (upgrades=$global:rookTestupgrades, failure=$failed)"
    }
    if ($case.expected -eq 1 -and $global:rookTestprobes -ne 2) { throw 'Both direct and active-Service probes required' }
    Write-Output "PASS: $($case.name)"
}
Write-Output '5 operator-switch tests passed (test doubles only, no runtime evidence).'
