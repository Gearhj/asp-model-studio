param(
    [string]$RepositoryRoot = 'C:\Users\james\asp-model-studio'
)
$ErrorActionPreference = 'Stop'
$runtime = Join-Path $RepositoryRoot '.runtime\nba-gen1-publisher\deployment.json'
if (-not (Test-Path -LiteralPath $runtime)) { throw "NBA runtime manifest missing: $runtime" }
$binding = Get-Content -LiteralPath $runtime -Raw | ConvertFrom-Json
$deployment = Join-Path $RepositoryRoot ('.deployments\nba-gen1-publisher\' + $binding.deploymentId)
$manifest = Join-Path $deployment 'deployment-manifest.json'
if (-not (Test-Path -LiteralPath $manifest)) { throw "NBA deployment missing: $manifest" }
$actual = (Get-FileHash -LiteralPath $manifest -Algorithm SHA256).Hash.ToLowerInvariant()
if ($actual -ne $binding.deploymentManifestSha256) { throw 'NBA deployment manifest hash mismatch' }
$python = Join-Path $RepositoryRoot '.venv\Scripts\python.exe'
$script = Join-Path $deployment 'scripts\publish_nba_gen1_production_forecast.py'
& $python $script --handoff-index $binding.handoffPath --deployment-manifest $manifest --effective-at-utc $binding.effectiveAtUtc
exit $LASTEXITCODE

