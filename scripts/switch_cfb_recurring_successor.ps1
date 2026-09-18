param(
    [Parameter(Mandatory=$true)][string]$PreviousEvidenceRoot,
    [Parameter(Mandatory=$true)][string]$SuccessorEvidenceRoot
)
$ErrorActionPreference = 'Stop'
$shell = "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"
$helper = Join-Path $PSScriptRoot 'activate_cfb_recurring_20260918.ps1'
$task = Get-ScheduledTask -TaskName 'ASP CFB Forecast Publisher' -ErrorAction Stop
if ($task.State.ToString() -eq 'Running') { throw 'CFB owner is running; wait for natural completion before switching' }
$taskInfo = Get-ScheduledTaskInfo -InputObject $task
if ($taskInfo.NextRunTime -le (Get-Date).AddMinutes(2)) { throw 'Natural trigger is imminent; wait for its completion before switching' }
# The existing supported installer verifies the exact old task and binding;
# it refuses any different owner. Never overwrite or alter an active task.
& $shell -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $helper -Mode Verify -EvidenceRoot $PreviousEvidenceRoot
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
$task = Get-ScheduledTask -TaskName 'ASP CFB Forecast Publisher' -ErrorAction Stop
if ($task.State.ToString() -eq 'Running') { throw 'Natural owner started during verification; no removal performed' }
& $shell -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $helper -Mode Remove -EvidenceRoot $PreviousEvidenceRoot
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $shell -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $helper -Mode Install -EvidenceRoot $SuccessorEvidenceRoot
$installResult = $LASTEXITCODE
if ($installResult -ne 0) {
    # Restore only the verified healthy predecessor using its own installer.
    & $shell -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $helper -Mode Install -EvidenceRoot $PreviousEvidenceRoot
    exit $installResult
}
& $shell -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $helper -Mode Verify -EvidenceRoot $SuccessorEvidenceRoot
exit $LASTEXITCODE
