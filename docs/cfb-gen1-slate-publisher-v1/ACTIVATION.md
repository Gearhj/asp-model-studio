# CFB activation requirements — not executed

Final deployment `7934282ddb839f8fbcde4f63c7e0710cccf07967db26abdb7acca9e1c6fb66b9`; manifest physical SHA `d605dd64d2c4d645e36bc45d6c608b3a5c17be2ccd444d1596413b3565b98cef`; release physical SHA `5c853df0e441902eb71dfb1426ab645e707e22d8e91399b755fd332e0080530e`. Plan verifies all 14 immutable members, exact runtime binding and absence of a conflicting task.

```powershell
$receipt = Get-Content 'C:\Users\james\asp-model-studio\outputs\cfb-gen1-slate-publisher-v1\final\release-receipt.json' -Raw | ConvertFrom-Json
$installer = Join-Path (Split-Path $receipt.deploymentManifest.path) 'scripts\install_cfb_gen1_slate_publisher.ps1'
& $installer -Mode Plan -DeploymentId $receipt.deploymentId -ExpectedManifestSha256 $receipt.deploymentManifest.sha256 -ReleasePath $receipt.release.path -ReleaseSha256 $receipt.release.sha256 -InputPointer $receipt.inputPointer
```

After explicit installation authorization, use the same supported command with `-Mode Install`, then `-Mode Verify`. It installs only **ASP CFB Forecast Publisher**, S4U/Limited/IgnoreNew, at 15-minute cadence. Do not install the draft deployment. Administrator execution may be necessary; this assignment made no elevation attempt. No task is currently installed. An existing different owner must stop installation; never force an overwrite.

Rollback uses the identical command with `-Mode Remove` for this exact owner/binding only. It preserves all input, forecast, discovery, release, evidence and launcher artifacts. There is no previous installed CFB deployment to restore. Other owners are outside this procedure.

Installation does not authorize acquisition or consumer activation. Authorize the exact `40f4a5dc2130e6ad9135d62fcf92448db04590dc9e66c8be7e65b3b103782415` requirement packet separately. Retain new raw objects privately; do not invoke old acquisition defaults that overwrite retained paths. Publish the new local capture pointer (`sourceManifest` with path/sha256/bytes) to `C:\Users\james\asp-model-studio\outputs\cfb-gen1-slate-publisher-v1\final\inputs\capture-current.json`. Under its existing lock the owner validates and admits it before dispatch. Live capture transport is not bundled; use a separately reviewed bounded intake execution after approval. Recurring live capture requires a later explicit same-owner extension, not a second task.

Consumer action: Claude verifies and pins the exact release/model/feature identities through a separately approved CFB authority contract, connects cumulative discovery, and records the bound immutable publication receipt clock. Existing research import accepts package bytes but does not itself provide production activation. Do not invent environment pin names or copy NBA/NFL pins. No decisions or wagering authority are conveyed.

Offline deterministic checks:

```powershell
Set-Location 'C:\Users\james\asp-model-studio\.tmp\cfb-gen1-slate-publisher-v1'
& 'C:\Users\james\asp-model-studio\.venv\Scripts\python.exe' scripts/verify_cfb_gen1_slate_stage.py --receipt 'C:\Users\james\asp-model-studio\outputs\cfb-gen1-slate-publisher-v1\final\release-receipt.json'
& 'C:\Users\james\asp-model-studio\.venv\Scripts\python.exe' -m pytest tests/test_cfb_slate_publisher.py -q -p no:cacheprovider
```

Independent baseline reproduction (reuses completed evidence if this output already exists; use a new private output directory only for a deliberate numerical rerun):

```powershell
& 'C:\Users\james\asp-model-studio\.venv\Scripts\python.exe' scripts/prepare_cfb_gen1_publisher.py --output 'C:\Users\james\asp-model-studio\outputs\cfb-gen1-slate-publisher-v1'
```

The forecast runner has no clock-override CLI and must not be used to manufacture earlier prospective issues. Synthetic test clocks remain separate. Observe the natural task after approved installation, preserving truthful NOT_DUE, STALE_INPUT_REJECTED and REUSED_IMMUTABLE dispositions.
