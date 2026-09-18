param(
    [ValidateSet('Prepare','Install','Verify','Remove')][string]$Mode = 'Verify',
    [string]$RepositoryRoot = 'C:\Users\james\asp-model-studio',
    [string]$DeploymentId,
    [string]$HandoffPath,
    [string]$HandoffSha256,
    [string]$EffectiveAtUtc
)
$ErrorActionPreference = 'Stop'
$taskName = 'ASP NBA Forecast Publisher'
$runtimeRoot = Join-Path $RepositoryRoot '.runtime\nba-gen1-publisher'
$runtimeManifest = Join-Path $runtimeRoot 'deployment.json'

function Assert-Deployment {
    if (-not $DeploymentId) { throw 'DeploymentId is required' }
    $deployment = Join-Path $RepositoryRoot ('.deployments\nba-gen1-publisher\' + $DeploymentId)
    $manifestPath = Join-Path $deployment 'deployment-manifest.json'
    if (-not (Test-Path -LiteralPath $manifestPath)) { throw "Missing deployment manifest: $manifestPath" }
    $manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
    if ($manifest.deploymentId -ne $DeploymentId) { throw 'Deployment identity/path mismatch' }
    foreach ($member in $manifest.members) {
        $path = Join-Path $deployment ($member.relativePath -replace '/', '\')
        if (-not (Test-Path -LiteralPath $path)) { throw "Missing deployment member: $path" }
        $sha = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($sha -ne $member.sha256 -or (Get-Item -LiteralPath $path).Length -ne $member.bytes) { throw "Deployment member mismatch: $path" }
    }
    return @{ Root=$deployment; Manifest=$manifestPath; ManifestSha=(Get-FileHash -LiteralPath $manifestPath -Algorithm SHA256).Hash.ToLowerInvariant() }
}

if ($Mode -eq 'Remove') {
    $tasks = @(Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue)
    foreach ($task in $tasks) { Unregister-ScheduledTask -TaskName $task.TaskName -Confirm:$false }
    if (Test-Path -LiteralPath $runtimeManifest) { Remove-Item -LiteralPath $runtimeManifest -Force }
    Write-Output '{"status":"REMOVED","taskName":"ASP NBA Forecast Publisher"}'
    exit 0
}

$checked = Assert-Deployment
if (-not $HandoffPath -or -not $HandoffSha256 -or -not $EffectiveAtUtc) { throw 'HandoffPath, HandoffSha256 and EffectiveAtUtc are required' }
if (-not (Test-Path -LiteralPath $HandoffPath)) { throw "Missing handoff: $HandoffPath" }
if ((Get-FileHash -LiteralPath $HandoffPath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $HandoffSha256) { throw 'Handoff hash mismatch' }
[DateTimeOffset]::Parse($EffectiveAtUtc) | Out-Null
New-Item -ItemType Directory -Path $runtimeRoot -Force | Out-Null
$binding = [ordered]@{
    schema = 'NBA_GEN1_PUBLISHER_RUNTIME_BINDING_V1'
    deploymentId = $DeploymentId
    deploymentManifestSha256 = $checked.ManifestSha
    handoffPath = $HandoffPath
    handoffSha256 = $HandoffSha256
    effectiveAtUtc = $EffectiveAtUtc
    taskName = $taskName
}
$json = $binding | ConvertTo-Json -Depth 8 -Compress
[IO.File]::WriteAllText($runtimeManifest + '.tmp', $json + "`n", [Text.UTF8Encoding]::new($false))
Move-Item -LiteralPath ($runtimeManifest + '.tmp') -Destination $runtimeManifest -Force

if ($Mode -eq 'Prepare') {
    Write-Output ($binding | ConvertTo-Json -Depth 8)
    exit 0
}

if ($Mode -eq 'Install') {
    $owner = [Security.Principal.WindowsIdentity]::GetCurrent()
    $ownerSid = $owner.User.Value
    $powershell = "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"
    $wrapper = Join-Path $checked.Root 'scripts\invoke_nba_gen1_publisher.ps1'
    $args = "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$wrapper`" -RepositoryRoot `"$RepositoryRoot`""
    $action = New-ScheduledTaskAction -Execute $powershell -Argument $args -WorkingDirectory $checked.Root
    $trigger = New-ScheduledTaskTrigger -Once -At ((Get-Date).AddMinutes(1)) `
        -RepetitionInterval (New-TimeSpan -Minutes 15) `
        -RepetitionDuration (New-TimeSpan -Days 3650)
    $principal = New-ScheduledTaskPrincipal -UserId $ownerSid -LogonType S4U -RunLevel Limited
    $settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 12)
    $definition = New-ScheduledTask -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Description "NBA Gen1 production publisher; deployment=$DeploymentId"
    Register-ScheduledTask -TaskName $taskName -InputObject $definition -Force | Out-Null
}

$tasks = @(Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue)
if ($tasks.Count -ne 1) { throw "Expected exactly one canonical NBA owner; found $($tasks.Count)" }
$task = $tasks[0]
if ($task.Principal.LogonType.ToString() -ne 'S4U' -or $task.Principal.RunLevel.ToString() -ne 'Limited' -or $task.Settings.MultipleInstances.ToString() -ne 'IgnoreNew') {
    throw 'NBA owner is not S4U/Limited/IgnoreNew'
}
Write-Output ([ordered]@{status='VERIFIED';taskCount=1;taskName=$taskName;deploymentId=$DeploymentId;logonType='S4U';runLevel='Limited';multipleInstances='IgnoreNew';runtimeManifest=$runtimeManifest} | ConvertTo-Json -Depth 8)
