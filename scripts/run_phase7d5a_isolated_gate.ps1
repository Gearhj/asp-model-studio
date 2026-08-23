<#
    Phase 7D.5A (Workstream E) — reproducible isolated governed gate.

    Creates a FRESH throwaway runtime root OUTSIDE the repository and the shared development .runtime, seeds a
    Gen-3 v2 / Gen-2 v1 authority into it through the ACTUAL production publisher (tests/_governed_runtime_seed.py),
    then runs the deterministic governed test selection (git ls-files) against that isolated root with
    ASP_REQUIRE_ISOLATED_RUNTIME=1 so the code can never fall back to the shared .runtime. Nothing is copied from
    the user's .runtime; the shared runtime is never read or mutated. The throwaway root is deleted on exit unless
    -KeepRoot is given.

    Usage:
        pwsh -File scripts/run_phase7d5a_isolated_gate.ps1              # seed + full governed selection
        pwsh -File scripts/run_phase7d5a_isolated_gate.ps1 -KeepRoot    # keep the isolated root for inspection
        pwsh -File scripts/run_phase7d5a_isolated_gate.ps1 -Select 'tests/sports_cockpit_phase7d3_test.py'
#>
[CmdletBinding()]
param(
    [string[]]$Select,
    [switch]$KeepRoot
)
$ErrorActionPreference = "Stop"
$repo = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$py = Join-Path $repo ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { $py = "python" }

# A throwaway root under the OS temp dir — never the repo, never .runtime, never the scratchpad.
$root = Join-Path ([System.IO.Path]::GetTempPath()) ("asp-isolated-gate-" + [System.Guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Force -Path $root | Out-Null

$env:ASP_MODEL_STUDIO_RUNTIME_ROOT = $root
$env:ASP_REQUIRE_ISOLATED_RUNTIME = "1"
$env:PYTHONDONTWRITEBYTECODE = "1"
Write-Host "== Phase 7D.5A isolated gate ==" -ForegroundColor Cyan
Write-Host "isolated runtime root: $root"

$rc = 1
try {
    Push-Location $repo
    Write-Host "-- seeding governed authority via the production publisher --"
    & $py -m tests._governed_runtime_seed
    if ($LASTEXITCODE -ne 0) { throw "governed seeder failed ($LASTEXITCODE)" }

    if (-not $Select -or $Select.Count -eq 0) {
        $Select = (& git ls-files "tests/sports_*_test.py") -split "`n" | Where-Object { $_ -ne "" }
    }
    Write-Host ("-- running {0} governed test files under isolation --" -f $Select.Count)
    & $py -m pytest @Select -rsfE -p no:cacheprovider -q
    $rc = $LASTEXITCODE
}
finally {
    Pop-Location
    if (-not $KeepRoot) {
        Remove-Item -Recurse -Force -ErrorAction SilentlyContinue $root
        Write-Host "removed isolated root"
    } else {
        Write-Host "kept isolated root: $root"
    }
    Remove-Item Env:\ASP_MODEL_STUDIO_RUNTIME_ROOT -ErrorAction SilentlyContinue
    Remove-Item Env:\ASP_REQUIRE_ISOLATED_RUNTIME -ErrorAction SilentlyContinue
}
exit $rc
