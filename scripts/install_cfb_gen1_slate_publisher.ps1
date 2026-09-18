param(
    [ValidateSet('Plan','Install','Verify','Remove')][string]$Mode = 'Verify',
    [string]$RepositoryRoot = 'C:\Users\james\asp-model-studio',
    [string]$DeploymentId,
    [string]$ReleasePath,
    [string]$ReleaseSha256,
    [string]$InputPointer,
    [switch]$EnableNetwork,
    [string]$GrantPath = '',
    [string]$GrantSha256 = '',
    [Parameter(Mandatory=$true)][string]$ExpectedManifestSha256
)
$ErrorActionPreference = 'Stop'
$taskName = 'ASP CFB Forecast Publisher'
$runtimeRoot = Join-Path $RepositoryRoot '.runtime\cfb-gen1-slate-publisher'
$runtimeManifest = Join-Path $runtimeRoot 'deployment.json'

function Assert-Deployment {
    if (-not $DeploymentId) { throw 'DeploymentId is required' }
    $deployment = Join-Path $RepositoryRoot ('.deployments\cfb-gen1-slate-publisher\' + $DeploymentId)
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

$checked = Assert-Deployment
if ($checked.ManifestSha -ne $ExpectedManifestSha256) { throw 'Deployment manifest differs from authorized physical hash' }
if (-not $ReleasePath -or -not $ReleaseSha256 -or -not $InputPointer) { throw 'ReleasePath, ReleaseSha256, InputPointer required' }
if ((Get-FileHash -LiteralPath $ReleasePath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $ReleaseSha256) { throw 'Release hash mismatch' }
$release = Get-Content -LiteralPath $ReleasePath -Raw | ConvertFrom-Json
if ($release.deploymentManifest.sha256 -ne $ExpectedManifestSha256) { throw 'Release/deployment binding mismatch' }
if ((Get-FileHash -LiteralPath $release.refreshAuthorizationProposal.path -Algorithm SHA256).Hash.ToLowerInvariant() -ne $release.refreshAuthorizationProposal.sha256) { throw 'Refresh requirements identity mismatch' }
if ((Get-FileHash -LiteralPath $release.refreshPlan.path -Algorithm SHA256).Hash.ToLowerInvariant() -ne $release.refreshPlan.sha256) { throw 'Exact recurring refresh plan mismatch' }
if ($EnableNetwork) {
    if (-not $GrantPath -or -not $GrantSha256) { throw 'Explicit exact recurring grant required; one-time grant is insufficient' }
    if ((Get-FileHash -LiteralPath $GrantPath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $GrantSha256) { throw 'Grant physical hash mismatch' }
    $grant = Get-Content -LiteralPath $GrantPath -Raw | ConvertFrom-Json
    $plan = Get-Content -LiteralPath $release.refreshPlan.path -Raw | ConvertFrom-Json
    if ($grant.approvedBy -ne 'James' -or $grant.liveCaptureAuthorized -ne $true -or $grant.planSha256 -ne $release.refreshPlan.sha256 -or $grant.deploymentId -ne $DeploymentId -or $grant.validFromUtc -ne $plan.validFromUtc -or $grant.validUntilUtc -ne $plan.validUntilUtc) { throw 'Recurring grant does not match this exact deployment/plan' }
    if ($Mode -in @('Plan','Install') -and ([DateTimeOffset]::UtcNow -lt [DateTimeOffset]::Parse($plan.validFromUtc) -or [DateTimeOffset]::UtcNow -ge [DateTimeOffset]::Parse($plan.validUntilUtc))) { throw 'Recurring grant period closed' }
}
$inputVersion = Get-Content -LiteralPath $InputPointer -Raw | ConvertFrom-Json
if ((Get-FileHash -LiteralPath $inputVersion.inputManifest.path -Algorithm SHA256).Hash.ToLowerInvariant() -ne $inputVersion.inputManifest.sha256) { throw 'Input pointer/member mismatch' }
$binding = [ordered]@{
    schema = 'CFB_GEN1_SLATE_PUBLISHER_RUNTIME_BINDING_V1'
    deploymentId = $DeploymentId
    deploymentManifestSha256 = $checked.ManifestSha
    releasePath = $ReleasePath
    releaseSha256 = $ReleaseSha256
    inputPointer = $InputPointer
    stateRoot = Join-Path $runtimeRoot 'state'
    exchangeRoot = Join-Path $RepositoryRoot '..\asp-model-exchange\cfb-gen1-production-v1'
    taskName = $taskName
    networkEnabled = [bool]$EnableNetwork
    grantPath = $GrantPath
    grantSha256 = $GrantSha256
    capturePointer = Join-Path (Split-Path -Parent $InputPointer) 'capture-current.json'
}
$json = $binding | ConvertTo-Json -Depth 8 -Compress
$tasks = @(Get-ScheduledTask -ErrorAction Stop | Where-Object { $_.TaskName -eq $taskName })
if ($tasks.Count -gt 1) { throw 'Duplicate CFB owners; no mutation allowed' }
$powershell = "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"
$wrapper = Join-Path $checked.Root 'scripts\invoke_cfb_gen1_slate_publisher.ps1'
$actionArguments = "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$wrapper`" -RepositoryRoot `"$RepositoryRoot`""
$expectedOwnerSid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
function Assert-Task($task) {
    $registeredUser = [string]$task.Principal.UserId
    if ($registeredUser -like 'S-1-*') { $registeredSid = $registeredUser }
    else { $registeredSid = ([Security.Principal.NTAccount]::new($registeredUser)).Translate([Security.Principal.SecurityIdentifier]).Value }
    if ($task.TaskPath -ne '\' -or @($task.Actions).Count -ne 1 -or
        $registeredSid -ne $expectedOwnerSid -or
        $task.Actions.Execute -ne $powershell -or $task.Actions.Arguments -ne $actionArguments -or
        $task.Actions.WorkingDirectory -ne $checked.Root -or
        $task.Description -ne "CFB Gen1 slate publisher; deployment=$DeploymentId" -or
        $task.Principal.LogonType.ToString() -ne 'S4U' -or $task.Principal.RunLevel.ToString() -ne 'Limited' -or
        $task.Settings.MultipleInstances.ToString() -ne 'IgnoreNew' -or
        @($task.Triggers).Count -ne 1 -or $task.Triggers[0].Repetition.Interval -ne 'PT15M') {
        throw 'Existing CFB owner differs from the exact authorized action/principal/cadence; no overwrite allowed'
    }
}
if ($tasks.Count -eq 1) { Assert-Task $tasks[0] }
if (Test-Path -LiteralPath $runtimeManifest) {
    $retained = Get-Content -LiteralPath $runtimeManifest -Raw | ConvertFrom-Json
    foreach ($key in $binding.Keys) {
        if ($retained.$key -cne $binding[$key]) { throw "Runtime binding differs at $key; no overwrite allowed" }
    }
}
if ($Mode -eq 'Plan') {
    [ordered]@{status='PLAN_VERIFIED_NO_WRITES';taskCount=$tasks.Count;binding=$binding;
        execute=$powershell;arguments=$actionArguments;workingDirectory=$checked.Root;
        cadence='PT15M';firstRun='Natural trigger one minute after installation';
        logonType='S4U';runLevel='Limited';multipleInstances='IgnoreNew';
        deploymentMemberCount=@((Get-Content -LiteralPath $checked.Manifest -Raw | ConvertFrom-Json).members).Count} | ConvertTo-Json -Depth 8
    exit 0
}
if ($Mode -eq 'Remove') {
    if ($tasks.Count -eq 1) {
        Stop-ScheduledTask -TaskName $taskName
        Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
    }
    if (Test-Path -LiteralPath $runtimeManifest) { Remove-Item -LiteralPath $runtimeManifest -Force }
    Write-Output '{"status":"REMOVED","taskName":"ASP CFB Forecast Publisher"}'
    exit 0
}

if ($Mode -eq 'Install' -and $tasks.Count -eq 0) {
    $owner = [Security.Principal.WindowsIdentity]::GetCurrent()
    $ownerSid = $owner.User.Value
    # Keep the fully qualified SID in XML; New-ScheduledTaskPrincipal resolves it
    # to a bare local account on this host, which S4U registration rejected.
    function Xml-Escape([string]$value) { return [Security.SecurityElement]::Escape($value) }
    $start = (Get-Date).AddMinutes(1).ToString('yyyy-MM-ddTHH:mm:sszzz')
    $taskXml = @"
<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo><Description>CFB Gen1 slate publisher; deployment=$DeploymentId</Description></RegistrationInfo>
  <Triggers><TimeTrigger><Repetition><Interval>PT15M</Interval><Duration>P3650D</Duration><StopAtDurationEnd>false</StopAtDurationEnd></Repetition><StartBoundary>$start</StartBoundary><Enabled>true</Enabled></TimeTrigger></Triggers>
  <Principals><Principal id="Author"><UserId>$ownerSid</UserId><LogonType>S4U</LogonType><RunLevel>LeastPrivilege</RunLevel></Principal></Principals>
  <Settings><MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy><DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries><StopIfGoingOnBatteries>false</StopIfGoingOnBatteries><StartWhenAvailable>true</StartWhenAvailable><ExecutionTimeLimit>PT12M</ExecutionTimeLimit><Enabled>true</Enabled></Settings>
  <Actions Context="Author"><Exec><Command>$(Xml-Escape $powershell)</Command><Arguments>$(Xml-Escape $actionArguments)</Arguments><WorkingDirectory>$(Xml-Escape $checked.Root)</WorkingDirectory></Exec></Actions>
</Task>
"@
    # Never use -Force: a concurrent owner appearing after Plan must stop installation.
    Register-ScheduledTask -TaskName $taskName -Xml $taskXml | Out-Null
    try {
        Assert-Task (Get-ScheduledTask -TaskName $taskName -ErrorAction Stop)
        New-Item -ItemType Directory -Path $runtimeRoot -Force | Out-Null
        [IO.File]::WriteAllText($runtimeManifest + '.tmp', $json + "`n", [Text.UTF8Encoding]::new($false))
        Move-Item -LiteralPath ($runtimeManifest + '.tmp') -Destination $runtimeManifest -Force
    } catch {
        Stop-ScheduledTask -TaskName $taskName
        Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
        if (Test-Path -LiteralPath $runtimeManifest) { Remove-Item -LiteralPath $runtimeManifest }
        throw
    }
}

$tasks = @(Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue)
if ($tasks.Count -ne 1) { throw "Expected exactly one canonical CFB owner; found $($tasks.Count)" }
$task = $tasks[0]
Assert-Task $task
if (-not (Test-Path -LiteralPath $runtimeManifest)) { throw 'Expected runtime binding is absent' }
Write-Output ([ordered]@{status='VERIFIED';taskCount=1;taskName=$taskName;deploymentId=$DeploymentId;logonType='S4U';runLevel='Limited';multipleInstances='IgnoreNew';runtimeManifest=$runtimeManifest} | ConvertTo-Json -Depth 8)
