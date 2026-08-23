<#
    Phase 7D.5A / 7D.5A.2 — reproducible, FULLY data-hermetic, collection-aware isolated governed gate.

    Creates a FRESH throwaway runtime root OUTSIDE the repository and the shared .runtime, seeds a Gen-3 authority
    into it through the ACTUAL production publisher, then (1) captures the EXACT pytest collection, (2) runs the full
    deterministic governed selection (git ls-files) under ASP_REQUIRE_ISOLATED_RUNTIME=1 with the external-data
    access guard active, and (3) runs collection-aware skip governance against the committed gate policy. The gate
    fails if pytest fails, if governance fails (missing/extra/critical/unknown/changed skip), or if the data guard
    recorded ANY external-data open. Nothing is copied from the user's .runtime; the shared runtime is never mutated.

    This is the FULL gate — it does NOT accept a subset selection (there is no -Select). Subset debugging must use an
    ordinary `pytest <files>` invocation, which can never emit this gate's readiness result.

    Usage:
        pwsh -File scripts/run_phase7d5a_isolated_gate.ps1                # full gate
        pwsh -File scripts/run_phase7d5a_isolated_gate.ps1 -WritePolicy   # (reviewed) record the gate policy
        pwsh -File scripts/run_phase7d5a_isolated_gate.ps1 -KeepRoot      # keep the isolated root for inspection
#>
[CmdletBinding()]
param(
    [switch]$KeepRoot,
    [switch]$WritePolicy
)
$ErrorActionPreference = "Stop"
$repo = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$py = Join-Path $repo ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { $py = "python" }

$root = Join-Path ([System.IO.Path]::GetTempPath()) ("asp-isolated-gate-" + [System.Guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Force -Path $root | Out-Null

$env:ASP_MODEL_STUDIO_RUNTIME_ROOT = $root
$env:ASP_REQUIRE_ISOLATED_RUNTIME = "1"
$env:PYTHONDONTWRITEBYTECODE = "1"
$dataManifest = Join-Path $root "isolated-data-violations.json"
$env:ASP_ISOLATED_DATA_MANIFEST = $dataManifest
Write-Host "== Phase 7D.5A.2 isolated gate ==" -ForegroundColor Cyan
Write-Host "isolated runtime root: $root"

$rc = 1
try {
    Push-Location $repo
    Write-Host "-- seeding governed authority via the production publisher --"
    & $py -m tests._governed_runtime_seed
    if ($LASTEXITCODE -ne 0) { throw "governed seeder failed ($LASTEXITCODE)" }

    $selectionGlob = "tests/sports_*_test.py"
    $Select = (& git ls-files $selectionGlob) -split "`n" | Where-Object { $_ -ne "" }
    $collected = Join-Path $root "collected.txt"
    $junit = Join-Path $root "gate-junit.xml"
    $manifest = Join-Path $root "skip-manifest.json"
    $policy = Join-Path $repo "scripts/phase7d5a_gate_policy.json"

    Write-Host ("-- collecting {0} governed test files (collect-only) --" -f $Select.Count)
    # capture STDOUT only (node ids); discard stderr warnings so they can never interleave with a node line
    & $py -m pytest @Select --collect-only -q -p no:cacheprovider 2>$null | Out-File -FilePath $collected -Encoding utf8

    Write-Host "-- running the full governed selection under isolation (data guard active) --"
    & $py -m pytest @Select -rsfE -p no:cacheprovider -q "--junitxml=$junit"
    $pytestRc = $LASTEXITCODE

    Write-Host "-- collection-aware skip governance (fail-closed) --"
    $govArgs = @("scripts/phase7d5a_skip_governance.py", "--collected", $collected, "--junit", $junit,
                 "--out", $manifest, "--policy", $policy, "--selection", $selectionGlob)
    if ($WritePolicy) { $govArgs += "--write-policy" }
    & $py @govArgs
    $govRc = $LASTEXITCODE

    Write-Host "-- external-data access manifest --"
    $dataRc = 0
    if (Test-Path $dataManifest) {
        $dm = Get-Content $dataManifest -Raw | ConvertFrom-Json
        $vcount = @($dm.violations).Count
        if ($vcount -gt 0) { Write-Host "  EXTERNAL-DATA VIOLATIONS: $vcount" -ForegroundColor Red; $dataRc = 1 }
        else { Write-Host "  zero unexpected external-data opens" }
    } else { Write-Host "  (no data manifest written)" }

    Write-Host "-- skip manifest: $manifest --"
    if ($pytestRc -ne 0 -or ($govRc -ne 0 -and -not $WritePolicy) -or $dataRc -ne 0) { $rc = 1 } else { $rc = 0 }
    Write-Host ("-- gate result: pytest={0} governance={1} data={2} => {3} --" -f $pytestRc, $govRc, $dataRc, $rc)
}
finally {
    Pop-Location
    if (-not $KeepRoot) {
        Remove-Item -Recurse -Force -ErrorAction SilentlyContinue $root
        Write-Host "removed isolated root"
    } else { Write-Host "kept isolated root: $root" }
    Remove-Item Env:\ASP_MODEL_STUDIO_RUNTIME_ROOT -ErrorAction SilentlyContinue
    Remove-Item Env:\ASP_REQUIRE_ISOLATED_RUNTIME -ErrorAction SilentlyContinue
    Remove-Item Env:\ASP_ISOLATED_DATA_MANIFEST -ErrorAction SilentlyContinue
}
exit $rc
