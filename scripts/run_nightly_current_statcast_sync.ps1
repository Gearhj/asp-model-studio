<#
.SYNOPSIS
Runs the governed incremental current-Statcast synchronization command.

.DESCRIPTION
Uses the repository-local Python environment, writes a timestamped log beneath
the ignored ASP Model Studio runtime, and returns the Python command's exit code.
The Python command owns the nonblocking interprocess publication lock, so this
wrapper cannot bypass concurrency protection.
#>
[CmdletBinding()]
param(
    [string]$Through = 'latest-completed',
    [int]$CorrectionLookback = 3
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$logPath = $null
try {
    if ($Through -ne 'latest-completed' -and
        $Through -notmatch '^\d{4}-\d{2}-\d{2}$') {
        throw "Through must be 'latest-completed' or an ISO date (YYYY-MM-DD)."
    }
    if ($CorrectionLookback -lt 0) {
        throw 'CorrectionLookback must be zero or greater.'
    }

    $repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
    $python = Join-Path $repoRoot '.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
        throw "Missing repository Python environment: $python"
    }

    $logRoot = Join-Path $repoRoot '.runtime\asp-model-studio\logs'
    [IO.Directory]::CreateDirectory($logRoot) | Out-Null
    $stamp = Get-Date -Format 'yyyyMMdd-HHmmssfff'
    $logPath = Join-Path $logRoot "current-statcast-sync-$stamp-$PID.log"

    $startedAt = [DateTimeOffset]::Now.ToString('o')
    $startLine = "CURRENT_STATCAST_SYNC_WRAPPER start=$startedAt through=$Through correctionLookback=$CorrectionLookback"
    $startLine | Tee-Object -FilePath $logPath

    Push-Location $repoRoot
    try {
        $commandArguments = @(
            '-B',
            '-m', 'scripts.sync_mlb_current_statcast',
            '--through', $Through,
            '--correction-lookback', [string]$CorrectionLookback
        )

        # Windows PowerShell 5.1 surfaces native stderr as error records. Keep
        # those records in the combined log and let the process exit code remain
        # authoritative rather than treating a warning line as a script failure.
        $previousErrorActionPreference = $ErrorActionPreference
        try {
            $ErrorActionPreference = 'Continue'
            & $python @commandArguments 2>&1 |
                Tee-Object -FilePath $logPath -Append
            $commandExit = [int]$LASTEXITCODE
        }
        finally {
            $ErrorActionPreference = $previousErrorActionPreference
        }
    }
    finally {
        Pop-Location
    }

    $finishedAt = [DateTimeOffset]::Now.ToString('o')
    $finishStatus = if ($commandExit -eq 0) { 'SUCCESS' } else { 'FAILED' }
    $finishLine = "CURRENT_STATCAST_SYNC_WRAPPER finish=$finishedAt status=$finishStatus exitCode=$commandExit log=$logPath"
    $finishLine | Tee-Object -FilePath $logPath -Append
    exit $commandExit
}
catch {
    $failureLine = "CURRENT_STATCAST_SYNC_WRAPPER status=FAILED exitCode=1 message=$($_.Exception.Message)"
    if ($logPath) {
        try { Add-Content -LiteralPath $logPath -Value $failureLine -Encoding UTF8 }
        catch { }
    }
    [Console]::Error.WriteLine($failureLine)
    exit 1
}
