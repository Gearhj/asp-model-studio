param(
  [ValidateSet('Plan','Install')][string]$Mode = 'Plan',
  [Parameter(Mandatory=$true)][string]$DeploymentRoot,
  [string]$TaskName = 'ASP NFL Personnel Evidence Capture',
  [string]$RuntimeRoot = 'C:\Users\james\asp-model-studio\.runtime\nfl-personnel-capture'
)
$ErrorActionPreference='Stop'
$marker='ASP_NFL_PERSONNEL_EVIDENCE_OWNER_V1'
$manifestPath=Join-Path $DeploymentRoot 'deployment-manifest.json'
$manifest=Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
if ($manifest.ownerMarker -ne $marker) { throw 'Deployment owner marker mismatch' }
foreach ($member in $manifest.members) {
  $path=Join-Path $DeploymentRoot ([string]$member.path)
  $actual=(Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
  if ($actual -ne [string]$member.sha256) { throw "Deployment verification failed: $($member.path)" }
}
$launcher=Join-Path $DeploymentRoot 'scripts\invoke_nfl_personnel_capture.ps1'
$actionArgs="-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$launcher`" -DeploymentRoot `"$DeploymentRoot`" -RuntimeRoot `"$RuntimeRoot`""
$plan=[ordered]@{
  mode=$Mode; taskName=$TaskName; ownerMarker=$marker; deploymentId=$manifest.identitySha256
  principal="$env:USERDOMAIN\$env:USERNAME"; logonType='S4U'; runLevel='Limited'; multipleInstances='IgnoreNew'
  tickCadence='PT15M'; executionTimeLimit='PT15M'; boundedSlots='MON_TUE_15:15_ET; WED_SUN_07:15_11:15_15:15_19:15_ET'
  requestCeilings=@{perCapture=6;perUtcDay=28;bytesPerCapture=67108864;retainedBytes=2147483648}
  action="powershell.exe $actionArgs"; rightsAcknowledgement=(Join-Path $RuntimeRoot 'RIGHTS_ACKNOWLEDGEMENT.json')
}
if ($Mode -eq 'Plan') { $plan | ConvertTo-Json -Depth 5; exit 0 }

$priorTask=Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
$priorManifestBytes=if (Test-Path (Join-Path $RuntimeRoot 'deployment.json')) {[IO.File]::ReadAllBytes((Join-Path $RuntimeRoot 'deployment.json'))} else {$null}
$priorRightsBytes=if (Test-Path (Join-Path $RuntimeRoot 'RIGHTS_ACKNOWLEDGEMENT.json')) {[IO.File]::ReadAllBytes((Join-Path $RuntimeRoot 'RIGHTS_ACKNOWLEDGEMENT.json'))} else {$null}
try {
  $otherOwners=Get-ScheduledTask | Where-Object { $_.TaskName -ne $TaskName -and $_.Description -like "*$marker*" }
  if ($otherOwners) { throw 'A second NFL personnel capture owner already exists' }
  New-Item -ItemType Directory -Force -Path $RuntimeRoot | Out-Null
  $rights=[ordered]@{contract='NFL_PERSONNEL_CAPTURE_RIGHTS_ACK_V1';authorized=$true;authorizedBy='James';scope='Free nflverse personnel evidence acquisition and local private retention for prospective NFL research';prohibitions=@('AISP writes','exchange writes','forecast publication','model fitting','outcome access','paid providers');recordedAtUtc=[DateTimeOffset]::UtcNow.ToString('o')}
  [IO.File]::WriteAllText((Join-Path $RuntimeRoot 'RIGHTS_ACKNOWLEDGEMENT.json'),($rights|ConvertTo-Json -Compress),[Text.UTF8Encoding]::new($false))
  $next=(Get-Date).AddMinutes(1)
  $trigger=New-ScheduledTaskTrigger -Once -At $next -RepetitionInterval (New-TimeSpan -Minutes 15) -RepetitionDuration (New-TimeSpan -Days 180)
  $action=New-ScheduledTaskAction -Execute 'powershell.exe' -Argument $actionArgs -WorkingDirectory $DeploymentRoot
  $principal=New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType S4U -RunLevel Limited
  $settings=New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 15) -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
  $task=New-ScheduledTask -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Description "$marker deployment=$($manifest.identitySha256) data-only research owner"
  Register-ScheduledTask -TaskName $TaskName -InputObject $task -Force | Out-Null
  $runtimeManifest=[ordered]@{schemaVersion='NFL_PERSONNEL_CAPTURE_RUNTIME_DEPLOYMENT_V1';deploymentId=$manifest.identitySha256;deploymentPath=$DeploymentRoot;taskName=$TaskName;ownerMarker=$marker;installedAtUtc=[DateTimeOffset]::UtcNow.ToString('o');sourceCommit=$manifest.sourceCommit;singleOwner=$true}
  [IO.File]::WriteAllText((Join-Path $RuntimeRoot 'deployment.json'),($runtimeManifest|ConvertTo-Json -Compress),[Text.UTF8Encoding]::new($false))
  $installed=Get-ScheduledTask -TaskName $TaskName
  if ($installed.Principal.LogonType -ne 'S4U' -or $installed.Principal.RunLevel -ne 'Limited' -or $installed.Settings.MultipleInstances -ne 'IgnoreNew') { throw 'Installed task security/overlap policy mismatch' }
  if ($installed.Actions.Arguments -notlike "*$($manifest.identitySha256)*") { throw 'Installed task action does not bind exact deployment' }
  $owners=@(Get-ScheduledTask | Where-Object { $_.Description -like "*$marker*" })
  if ($owners.Count -ne 1) { throw "Expected one owner; found $($owners.Count)" }
  [ordered]@{status='INSTALLED';deploymentId=$manifest.identitySha256;taskName=$TaskName;ownerCount=$owners.Count;nextRun=(Get-ScheduledTaskInfo -TaskName $TaskName).NextRunTime;plan=$plan} | ConvertTo-Json -Depth 6
} catch {
  if (!$priorTask) { Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue }
  if ($null -ne $priorManifestBytes) {[IO.File]::WriteAllBytes((Join-Path $RuntimeRoot 'deployment.json'),$priorManifestBytes)} else {Remove-Item -LiteralPath (Join-Path $RuntimeRoot 'deployment.json') -Force -ErrorAction SilentlyContinue}
  if ($null -ne $priorRightsBytes) {[IO.File]::WriteAllBytes((Join-Path $RuntimeRoot 'RIGHTS_ACKNOWLEDGEMENT.json'),$priorRightsBytes)} else {Remove-Item -LiteralPath (Join-Path $RuntimeRoot 'RIGHTS_ACKNOWLEDGEMENT.json') -Force -ErrorAction SilentlyContinue}
  throw
}
