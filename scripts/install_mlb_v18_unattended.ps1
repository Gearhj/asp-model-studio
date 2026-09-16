[CmdletBinding()]
param(
    [ValidateSet('Plan', 'Prepare', 'Install')]
    [string]$Mode = 'Plan',
    [string]$RepositoryRoot = (Split-Path -Parent $PSScriptRoot),
    [Parameter(Mandatory = $true)]
    [string]$CodeRoot,
    [string]$PythonPath,
    [switch]$Force
)

# Registration is deliberately explicit. Plan performs only read-only checks.
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$taskName = 'ASP MLB V18 Research Publisher'
$ownershipMarker = 'ASP_MLB_V18_UNATTENDED_OWNER_V1'

function Resolve-LocalPath([string]$Value) {
    $resolved = (Resolve-Path -LiteralPath $Value -ErrorAction Stop).ProviderPath
    if ($resolved.StartsWith('\\')) { throw 'Only local paths are supported for S4U execution.' }
    if ($resolved.Contains('"') -or $resolved.Contains("`r") -or $resolved.Contains("`n")) {
        throw 'Deployment paths may not contain quotes or line breaks.'
    }
    return $resolved.TrimEnd('\')
}

function Escape-Xml([string]$Value) { return [System.Security.SecurityElement]::Escape($Value) }
function Get-TaskArguments($Task) {
    return (($Task.Actions | ForEach-Object {
        if ($_.PSObject.Properties['Arguments']) { $_.Arguments }
    }) -join ' ')
}

$RepositoryRoot = Resolve-LocalPath $RepositoryRoot
$CodeRoot = Resolve-LocalPath $CodeRoot
$deploymentParent = Join-Path $RepositoryRoot '.deployments\mlb-v18-unattended'
if (-not $CodeRoot.StartsWith($deploymentParent.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase)) {
    throw "CodeRoot must be a pinned snapshot below $deploymentParent, separate from mutable runtime and outputs."
}
if (-not $PythonPath) { $PythonPath = Join-Path $RepositoryRoot '.venv\Scripts\python.exe' }
$PythonPath = Resolve-LocalPath $PythonPath
if ($PythonPath -ne (Join-Path $RepositoryRoot '.venv\Scripts\python.exe')) {
    throw 'PythonPath must identify this repository''s intended .venv\Scripts\python.exe.'
}
$stateRoot = Join-Path $RepositoryRoot '.runtime\mlb-v18-unattended'
$manifestPath = Join-Path $stateRoot 'deployment.json'
$launcherPath = Join-Path $CodeRoot 'scripts\invoke_mlb_v18_unattended.ps1'
$runnerPath = Join-Path $CodeRoot 'scripts\run_mlb_v18_unattended.py'
$buildReceiptPath = Join-Path $CodeRoot 'deployment-build.json'
foreach ($required in @($launcherPath, $runnerPath, $buildReceiptPath, (Join-Path $CodeRoot 'server'))) {
    if (-not (Test-Path -LiteralPath $required)) { throw "Missing deployment input: $required" }
}
foreach ($sharedName in @('outputs', '.runtime')) {
    $shared = Get-Item -LiteralPath (Join-Path $CodeRoot $sharedName)
    $expectedTarget = Join-Path $RepositoryRoot $sharedName
    if (-not ($shared.Attributes -band [IO.FileAttributes]::ReparsePoint) -or
        @($shared.Target).Count -ne 1 -or
        (Resolve-LocalPath @($shared.Target)[0]) -ne (Resolve-LocalPath $expectedTarget)) {
        throw "Deployment $sharedName must be a directory junction to $expectedTarget."
    }
}

$codeFiles = @(
    foreach ($directory in @('scripts', 'server', 'tools')) {
        $directoryPath = Join-Path $CodeRoot $directory
        if (Test-Path -LiteralPath $directoryPath) {
            Get-ChildItem -LiteralPath $directoryPath -Recurse -File |
                Where-Object { $_.Extension.ToLowerInvariant() -in @('.py', '.json', '.ps1', '.toml', '.yaml', '.yml') -and $_.FullName -notmatch '[\\/]__pycache__[\\/]' }
        }
    }
    Get-ChildItem -LiteralPath $CodeRoot -File |
        Where-Object { $_.Extension.ToLowerInvariant() -in @('.py', '.json', '.ps1', '.toml', '.yaml', '.yml') }
) | Sort-Object FullName -Unique
$codeHashes = @($codeFiles | ForEach-Object {
    [ordered]@{
        path = $_.FullName.Substring($CodeRoot.Length + 1).Replace('\', '/')
        sha256 = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        bytes = $_.Length
    }
})
$buildReceipt = Get-Content -LiteralPath $buildReceiptPath -Raw | ConvertFrom-Json
if ($buildReceipt.schema_version -ne 1 -or
    $buildReceipt.repository_root -ne $RepositoryRoot -or
    $buildReceipt.code_root -ne $CodeRoot -or
    $buildReceipt.commit -ne (Split-Path -Leaf $CodeRoot)) {
    throw 'Deployment build receipt does not match the selected repository/commit directory.'
}
$buildPaths = @($buildReceipt.files | ForEach-Object { $_.path }) + @('deployment-build.json')
if (Compare-Object ($buildPaths | Sort-Object) (@($codeHashes | ForEach-Object { $_.path }) | Sort-Object)) {
    throw 'Deployment code/config file set differs from its immutable build receipt.'
}
foreach ($entry in $buildReceipt.files) {
    $actual = @($codeHashes | Where-Object { $_.path -eq $entry.path })
    if ($actual.Count -ne 1 -or $actual[0].sha256 -ne $entry.sha256 -or
        $actual[0].bytes -ne $entry.bytes) {
        throw "Deployment code/config bytes differ from committed build receipt: $($entry.path)"
    }
}
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$ownerSid = $identity.User.Value
$manifest = [ordered]@{
    schema_version = 1
    owner_marker = $ownershipMarker
    task_name = $taskName
    repository_root = $RepositoryRoot
    code_root = $CodeRoot
    python_executable = $PythonPath
    python_sha256 = (Get-FileHash -LiteralPath $PythonPath -Algorithm SHA256).Hash.ToLowerInvariant()
    runner_path = $runnerPath
    launcher_path = $launcherPath
    state_root = $stateRoot
    output_root = (Join-Path $RepositoryRoot 'outputs\mlb-v18-unattended-v1')
    kill_switch = (Join-Path $stateRoot 'STOP')
    owner_sid = $ownerSid
    logon_type = 'S4U'
    code_hashes = $codeHashes
    code_extensions = @('.py', '.json', '.ps1', '.toml', '.yaml', '.yml')
    deployed_commit = $buildReceipt.commit
    prepared_at_utc = [DateTime]::UtcNow.ToString('o')
}

# Inspect all task definitions only to find an existing V18 owner. Never replace
# an unrelated task and never silently delete or disable a competing owner.
try { $tasks = @(Get-ScheduledTask -ErrorAction Stop) }
catch { throw "Cannot inventory Windows Task Scheduler: $($_.Exception.Message). Registration was not attempted." }
$existing = @($tasks | Where-Object { $_.TaskPath -eq '\' -and $_.TaskName -eq $taskName })
if ($existing.Count -gt 1) { throw 'More than one canonical owner was returned by Task Scheduler.' }
if ($existing.Count -eq 1 -and -not ([string]$existing[0].Description).StartsWith($ownershipMarker)) {
    throw "The task name $taskName is already used by a different owner."
}
$competing = @($tasks | Where-Object {
    -not ($_.TaskPath -eq '\' -and $_.TaskName -eq $taskName) -and
    (($_.TaskName -match 'MLB.*V18|V18.*MLB') -or
     ((Get-TaskArguments $_) -match 'run_mlb_v18_(unattended|current_state|current_slate)|invoke_mlb_v18_unattended'))
})
if ($competing.Count -gt 0) {
    throw ('Another V18 scheduled owner exists: ' + (($competing | ForEach-Object { $_.TaskPath + $_.TaskName }) -join ', '))
}
if ($existing.Count -eq 1 -and $existing[0].State.ToString() -eq 'Running') {
    throw 'The canonical task is running. Wait for completion before replacing its deployment manifest.'
}
if ($existing.Count -eq 1 -and $existing[0].Principal.UserId -notin @($ownerSid, $identity.Name, $env:USERNAME)) {
    throw 'The canonical task belongs to a different Windows user; its ownership will not be replaced.'
}

$startBoundary = [DateTime]::Now.AddMinutes(1).ToString('yyyy-MM-ddTHH:mm:ss')
$powershellPath = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$arguments = '-NoLogo -NoProfile -NonInteractive -WindowStyle Hidden -File "' + $launcherPath + '" -ManifestPath "' + $manifestPath + '" -ScheduledInvocation'
$taskXml = @"
<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo><Description>$(Escape-Xml ($ownershipMarker + '; current-user S4U; pinned code; 5-minute local dispatcher'))</Description></RegistrationInfo>
  <Triggers>
    <BootTrigger><Enabled>true</Enabled><Delay>PT1M</Delay></BootTrigger>
    <TimeTrigger><Repetition><Interval>PT5M</Interval><StopAtDurationEnd>false</StopAtDurationEnd></Repetition><StartBoundary>$startBoundary</StartBoundary><Enabled>true</Enabled></TimeTrigger>
  </Triggers>
  <Principals><Principal id="Author"><UserId>$(Escape-Xml $ownerSid)</UserId><LogonType>S4U</LogonType><RunLevel>LeastPrivilege</RunLevel></Principal></Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries><StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate><StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <IdleSettings><StopOnIdleEnd>false</StopOnIdleEnd><RestartOnIdle>false</RestartOnIdle></IdleSettings>
    <AllowStartOnDemand>true</AllowStartOnDemand><Enabled>true</Enabled><Hidden>false</Hidden>
    <RunOnlyIfIdle>false</RunOnlyIfIdle><WakeToRun>false</WakeToRun><ExecutionTimeLimit>PT60M</ExecutionTimeLimit><Priority>7</Priority>
  </Settings>
  <Actions Context="Author"><Exec><Command>$(Escape-Xml $powershellPath)</Command><Arguments>$(Escape-Xml $arguments)</Arguments><WorkingDirectory>$(Escape-Xml $CodeRoot)</WorkingDirectory></Exec></Actions>
</Task>
"@

$summary = [ordered]@{
    mode = $Mode
    task_name = $taskName
    principal = $identity.Name
    owner_sid = $ownerSid
    logon_type = 'S4U'
    run_level = 'LeastPrivilege'
    existing_canonical_owner = ($existing.Count -eq 1)
    code_root = $CodeRoot
    python_executable = $PythonPath
    hashed_code_files = $codeHashes.Count
    manifest_path = $manifestPath
    kill_switch = $manifest.kill_switch
    schedule = 'At startup after 1 minute; every 5 minutes indefinitely; StartWhenAvailable'
    execution_time_limit_minutes = 60
    multiple_instances = 'IgnoreNew'
    network_capability = 'Not established by installation: validate a real scheduled run under this S4U identity.'
    task_xml = $taskXml
}

if ($Mode -in @('Prepare', 'Install')) {
    New-Item -ItemType Directory -Path $stateRoot -Force | Out-Null
    $utf8 = New-Object System.Text.UTF8Encoding($false)
    $manifestJson = $manifest | ConvertTo-Json -Depth 8
    # Registration can trigger execution, so its manifest must already exist.
    # Keep the previous manifest recoverable when updating a stopped owner.
    $backupPath = $null
    if (Test-Path -LiteralPath $manifestPath) {
        $backupPath = Join-Path $stateRoot ('deployment.previous-' + [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssfffffffZ') + '.json')
        Copy-Item -LiteralPath $manifestPath -Destination $backupPath
    }
    $stagedPath = Join-Path $stateRoot ('deployment.' + [Guid]::NewGuid().ToString('N') + '.tmp')
    [IO.File]::WriteAllText($stagedPath, $manifestJson, $utf8)
    Move-Item -LiteralPath $stagedPath -Destination $manifestPath -Force
    if ($Mode -eq 'Prepare') {
        $summary['installed'] = $false
        $summary['manifest_prepared'] = $true
        $summary | ConvertTo-Json -Depth 8
        exit 0
    }
    if ($existing.Count -eq 1 -and -not $Force) {
        if ($backupPath) { Copy-Item -LiteralPath $backupPath -Destination $manifestPath -Force }
        throw "Replacing the existing canonical owner requires the explicit -Force switch."
    }
    try {
        Register-ScheduledTask -TaskName $taskName -TaskPath '\' -Xml $taskXml -Force -ErrorAction Stop | Out-Null
    }
    catch {
        if ($backupPath) { Copy-Item -LiteralPath $backupPath -Destination $manifestPath -Force }
        throw "Windows rejected registration of $taskName as current-user S4U: $($_.Exception.Message). No alternate owner was created; the manifest is prepared but installation is unverified."
    }
    $registered = Get-ScheduledTask -TaskName $taskName -TaskPath '\' -ErrorAction Stop
    if ($registered.Principal.UserId -notin @($ownerSid, $identity.Name, $env:USERNAME) -or
        $registered.Principal.LogonType.ToString() -ne 'S4U' -or
        $registered.Principal.RunLevel.ToString() -ne 'Limited' -or
        $registered.Settings.MultipleInstances.ToString() -ne 'IgnoreNew' -or
        -not $registered.Settings.StartWhenAvailable -or
        $registered.Settings.ExecutionTimeLimit -ne 'PT1H' -and $registered.Settings.ExecutionTimeLimit -ne 'PT60M') {
        throw 'Registered task principal/settings do not match the requested owner; inspect the task before trusting unattended execution.'
    }
    $info = Get-ScheduledTaskInfo -TaskName $taskName -TaskPath '\' -ErrorAction Stop
    $summary['installed'] = $true
    $summary['registered_state'] = $registered.State.ToString()
    $summary['next_run_time'] = $info.NextRunTime.ToString('o')
    $summary['started_by_installer'] = $false
}
$summary | ConvertTo-Json -Depth 8
