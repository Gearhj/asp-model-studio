param(
  [string]$Source = "C:\Users\james\ds-workflow-starter",
  [string]$Destination = "C:\Users\james\Projects\ATLAS\atlas-app"
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path -LiteralPath $Source)) {
  throw "ATLAS source folder does not exist: $Source"
}

if (-not (Test-Path -LiteralPath $Destination)) {
  New-Item -ItemType Directory -Force -Path $Destination | Out-Null
}

$excludeDirs = @(
  ".git",
  "node_modules",
  "dist",
  ".venv",
  "__pycache__",
  ".pytest_cache",
  ".cache",
  ".runtime",
  "server\artifacts"
)

$excludeFiles = @(
  ".env",
  ".env.local",
  "*.pyc"
)

$robocopyArgs = @(
  $Source,
  $Destination,
  "/E",
  "/R:2",
  "/W:1",
  "/NFL",
  "/NDL",
  "/NP",
  "/XD"
) + $excludeDirs + @("/XF") + $excludeFiles

Write-Host "ATLAS clean-copy sync"
Write-Host "Source:      $Source"
Write-Host "Destination: $Destination"
Write-Host "Excluded directories: $($excludeDirs -join ', ')"
Write-Host "Excluded files: $($excludeFiles -join ', ')"
Write-Host "Runtime artifacts: server/artifacts is intentionally excluded by default."

& robocopy @robocopyArgs
$code = $LASTEXITCODE

if ($code -le 7) {
  Write-Host "Robocopy completed successfully with code $code."
  exit 0
}

throw "Robocopy failed with code $code."
