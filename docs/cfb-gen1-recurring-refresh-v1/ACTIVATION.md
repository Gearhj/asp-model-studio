# Exact CFB successor activation and rollback

Status: **STAGED; NOT INSTALLED; RECURRING NETWORK NOT AUTHORIZED; AISP NOT ACTIVATED.** Do not install the superseded offline deployment. The seven-request one-time grant is exhausted and must not be reused for recurring capture.

Deployment: `d3b088089057a7d94b758249d842518fe7f847d0b269e88f95c85ac7a14d372d`. Manifest SHA: `80ced0b8b4ee541d489cb6bb402bda6b6f2c2079a6d3913a0aabfa3847fb4872`. Release SHA: `cf12a5fccfcca4ff682f2d532f772865c947e03735d0fdc32389fa592a02454c`. Exact proposed recurring plan: `C:\Users\james\asp-model-studio\.deployments\cfb-gen1-slate-publisher\d3b088089057a7d94b758249d842518fe7f847d0b269e88f95c85ac7a14d372d\configuration\REFRESH_PLAN.json`, SHA `3fead29fb55a23eb91a1d7051a762a3f1786b87421d2eff8c009e55e34975a60`, 6914 bytes. Validity ends 2026-10-01T00:00:00Z; a later request requires a new reviewed successor proposal. Model and other owners remain untouched.

## Read-only Plan (already verified)

```powershell
$stage = Get-Content -LiteralPath 'C:\Users\james\asp-model-studio\outputs\cfb-gen1-refresh-20260918-v1\successor\release-receipt.json' -Raw | ConvertFrom-Json
$installer = Join-Path (Split-Path -Parent $stage.deploymentManifest.path) 'scripts\install_cfb_gen1_slate_publisher.ps1'
$publisherArgs = @{
  DeploymentId = 'd3b088089057a7d94b758249d842518fe7f847d0b269e88f95c85ac7a14d372d'
  ExpectedManifestSha256 = '80ced0b8b4ee541d489cb6bb402bda6b6f2c2079a6d3913a0aabfa3847fb4872'
  ReleasePath = 'C:\Users\james\asp-model-studio\outputs\cfb-gen1-refresh-20260918-v1\successor\releases\sha256\cf12a5fccfcca4ff682f2d532f772865c947e03735d0fdc32389fa592a02454c\release.json'
  ReleaseSha256 = 'cf12a5fccfcca4ff682f2d532f772865c947e03735d0fdc32389fa592a02454c'
  InputPointer = 'C:\Users\james\asp-model-studio\outputs\cfb-gen1-slate-publisher-v1\final\inputs\current.json'
}
& $installer -Mode Plan @publisherArgs
```

The supported installer can run under Windows PowerShell 5.1. Do not change principals/ACLs or install a different deployment.

## Separate exact approval required before network/installation

James must authorize this exact deployment and plan physical SHA, its endpoints, free entitlement, 7/capture, 28/day, 200/period including carried seven, 25 MiB/capture, 100 MiB/day, 2 GiB storage, zero retry and stated validity. No such recurring authorization exists yet. Only after it is received, retain a private immutable nonsecret JSON acknowledgement with:

```json
{"approvedBy":"James","liveCaptureAuthorized":true,"planSha256":"3fead29fb55a23eb91a1d7051a762a3f1786b87421d2eff8c009e55e34975a60","deploymentId":"d3b088089057a7d94b758249d842518fe7f847d0b269e88f95c85ac7a14d372d","validFromUtc":"2026-09-18T00:00:00Z","validUntilUtc":"2026-10-01T00:00:00Z"}
```

This example is a schema, not an executed approval. Do not create an approved grant before authorization. Append the exact user approval/evidence reference and actual acknowledgement creation clock before hashing. Keep only the existing local `CFBD_API_KEY` in the original ignored `.env.local`; never put its value in the grant, task arguments or receipts.

After approval, supply the real acknowledgement path and physical SHA, and use the **same** argument set for Plan/Install/Verify/Remove:

```powershell
$publisherArgs.EnableNetwork = $true
$publisherArgs.GrantPath = '<actual approved immutable grant path>'
$publisherArgs.GrantSha256 = '<physical SHA-256 of that grant>'
& $installer -Mode Plan @publisherArgs
# Administrator installation only after explicit approval:
& $installer -Mode Install @publisherArgs
& $installer -Mode Verify @publisherArgs
```

Exactly one `ASP CFB Forecast Publisher`, S4U/Limited/IgnoreNew, every 15 minutes, first natural trigger about one minute after installation. An existing different owner or binding causes refusal, never overwrite. Shared state `C:\Users\james\asp-model-studio\.runtime\cfb-gen1-slate-publisher\state` retains the 57 committed forecasts, preventing regeneration on deployment change. Input pointer remains `C:\Users\james\asp-model-studio\outputs\cfb-gen1-slate-publisher-v1\final\inputs\current.json`. No second capture task. No `Start-ScheduledTask` or competing manual publisher is needed.

Observe natural invocations: launcher/Python exits 0; durable capture/admission/publication receipts; current status/freshness before reuse; cumulative discovery. NOT_DUE, NETWORK_DISABLED, budget/entitlement/input blocks remain truthful. Network calls require a due capture AND the exact valid grant. Earliest next proposed capture can be 2026-09-18T17:25:24Z (13:25:24 EDT), or the first natural tick thereafter if due; not backdated. Earliest next game checkpoint: Miami–Wake T−6h 17:30Z / 13:30 EDT. If activation happens later, only then-open legitimate windows are eligible. Do not force a capture merely to test installation.

## Exact rollback

If this newly installed task/binding fails verification, invoke `& $installer -Mode Remove @publisherArgs`. It verifies the exact owner/action before stopping/unregistering only this CFB task and removing only its runtime deployment binding. Verify/Remove remain available after the network authorization expires. Keep grant, raw objects, all receipts, model files, inputs, immutable releases, forecasts, discovery and publication journals. Recheck no CFB task and no CFB runtime binding, and unchanged unrelated owners. There was no previous installed CFB owner to restore. Do **not** install the superseded offline owner as rollback. Installation exceptions also unregister only the just-created CFB task. An interrupted/uncertain provider batch requires operator review; do not reset its ledger or retry it.

## Deterministic no-network verification

```powershell
Set-Location 'C:\Users\james\asp-model-studio\.tmp\cfb-gen1-slate-publisher-v1'
& 'C:\Users\james\asp-model-studio\.venv\Scripts\python.exe' scripts/verify_cfb_live_refresh_run.py --root 'C:\Users\james\asp-model-studio\outputs\cfb-gen1-refresh-20260918-v1'
& 'C:\Users\james\asp-model-studio\.venv\Scripts\python.exe' -m pytest tests/test_cfb_capture.py tests/test_cfb_recurring_refresh.py tests/test_cfb_slate_publisher.py -q -p no:cacheprovider
```

First command rehashes the existing 57 packages, raw bindings and 24 preserved objects; no model run/network/write. Tests use isolated synthetic fixtures. No one-time capture command should be rerun. AISP environment/database/backend and activation are outside this task; Claude needs explicit consumer discovery/clock integration, not an invented production pin.
