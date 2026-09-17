param(
  [Parameter(Mandatory=$true)][string]$DeploymentRoot,
  [string]$RuntimeRoot = 'C:\Users\james\asp-model-studio\.runtime\nfl-personnel-capture',
  [string]$DataRoot = 'C:\Users\james\asp-data-staging\nfl\personnel-captures-v1',
  [string]$FoundationRoot = 'C:\Users\james\asp-data-staging\nfl\foundation-v1'
)
$ErrorActionPreference = 'Stop'
$started = [DateTimeOffset]::UtcNow
$manifestPath = Join-Path $DeploymentRoot 'deployment-manifest.json'
$manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
foreach ($member in $manifest.members) {
  $path = Join-Path $DeploymentRoot ([string]$member.path)
  if (!(Test-Path -LiteralPath $path -PathType Leaf)) { throw "Missing deployed member: $($member.path)" }
  $actual = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
  if ($actual -ne [string]$member.sha256) { throw "Deployment hash mismatch: $($member.path)" }
}
$python = 'C:\Users\james\asp-model-studio\.venv\Scripts\python.exe'
$runner = Join-Path $DeploymentRoot 'scripts\run_nfl_personnel_prospective_capture.py'
$stdout = Join-Path $RuntimeRoot 'last-python-stdout.txt'
$stderr = Join-Path $RuntimeRoot 'last-python-stderr.txt'
New-Item -ItemType Directory -Force -Path $RuntimeRoot | Out-Null
$process = Start-Process -FilePath $python -ArgumentList @($runner,'--execute','--runtime-root',$RuntimeRoot,'--data-root',$DataRoot,'--foundation-root',$FoundationRoot) -WorkingDirectory $DeploymentRoot -WindowStyle Hidden -Wait -PassThru -RedirectStandardOutput $stdout -RedirectStandardError $stderr
$ended = [DateTimeOffset]::UtcNow
$lastRunPath = Join-Path $RuntimeRoot 'LAST_RUN.json'
$lastRun = if (Test-Path -LiteralPath $lastRunPath) { Get-Content -LiteralPath $lastRunPath -Raw | ConvertFrom-Json } else { $null }
$receipt = [ordered]@{
  schemaVersion='NFL_PERSONNEL_CAPTURE_LAUNCHER_RECEIPT_V1'; deploymentId=$manifest.identitySha256
  startedAtUtc=$started.ToString('o'); completedAtUtc=$ended.ToString('o'); python_exit_code=$process.ExitCode
  boundedStatus=if ($lastRun) { $lastRun.status } else { 'NO_LAST_RUN_RECEIPT' }
  providerCalls=if ($lastRun) { $lastRun.providerCalls } else { $null }
  stdoutSha256=(Get-FileHash -LiteralPath $stdout -Algorithm SHA256).Hash.ToLowerInvariant()
  stderrSha256=(Get-FileHash -LiteralPath $stderr -Algorithm SHA256).Hash.ToLowerInvariant()
}
$json = $receipt | ConvertTo-Json -Compress
$bytes = [Text.Encoding]::UTF8.GetBytes($json)
$hasher = [Security.Cryptography.SHA256]::Create()
try { $digestBytes = $hasher.ComputeHash($bytes) } finally { $hasher.Dispose() }
$digest = -join ($digestBytes | ForEach-Object { $_.ToString('x2') })
$receiptDir = Join-Path $RuntimeRoot ("launcher-receipts\sha256\" + $digest)
New-Item -ItemType Directory -Force -Path $receiptDir | Out-Null
[IO.File]::WriteAllBytes((Join-Path $receiptDir 'receipt.json'), $bytes)
[IO.File]::WriteAllBytes((Join-Path $RuntimeRoot 'LATEST_LAUNCHER_RECEIPT.json'), [Text.Encoding]::UTF8.GetBytes((@{path=(Join-Path $receiptDir 'receipt.json');sha256=$digest} | ConvertTo-Json -Compress)))
exit $process.ExitCode
