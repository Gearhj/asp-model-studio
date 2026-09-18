# Supported activation and rollback

STAGED ONLY. No installation, elevation retry or task mutation was performed.
Only deployment `0aa50236f9dcac875106c13c6749e025126370e700a4467915275251ad583a88` is the proposed successor. Do not install 7e04b1 or the
intermediate local verification candidate. Plan is read-only. Install requires
separate James authorization for this exact successor and Administrator execution
as James; it creates at most one S4U/Limited/IgnoreNew owner at 15 minutes and
refuses a different existing owner. Verify is read-only. Remove is the supported
rollback of this exact task and runtime binding only, retaining every artifact.
The command sequence below is documentation, not activation authorization.

```powershell
& 'C:\Users\james\asp-model-studio\.deployments\nba-gen1-slate-publisher\0aa50236f9dcac875106c13c6749e025126370e700a4467915275251ad583a88\scripts\install_nba_gen1_slate_publisher.ps1' -Mode Plan -DeploymentId '0aa50236f9dcac875106c13c6749e025126370e700a4467915275251ad583a88' -ExpectedManifestSha256 '4454b2e4cd0981e9d98bb900972459d54117ca72919867375e5c0d0b089a7573' -ReleasePath 'C:\Users\james\asp-model-studio\outputs\nba-gen1-slate-publisher-v1\release-final\releases\sha256\c123faf6e48fc2db7f60729671e13c320d2ec1cd86944d603fac9f0e136a2dd9\release.json' -ReleaseSha256 'c123faf6e48fc2db7f60729671e13c320d2ec1cd86944d603fac9f0e136a2dd9' -InputPointer 'C:\Users\james\asp-model-studio\outputs\nba-gen1-slate-publisher-v1\inputs\current.json'
```

```powershell
& 'C:\Users\james\asp-model-studio\.deployments\nba-gen1-slate-publisher\0aa50236f9dcac875106c13c6749e025126370e700a4467915275251ad583a88\scripts\install_nba_gen1_slate_publisher.ps1' -Mode Install -DeploymentId '0aa50236f9dcac875106c13c6749e025126370e700a4467915275251ad583a88' -ExpectedManifestSha256 '4454b2e4cd0981e9d98bb900972459d54117ca72919867375e5c0d0b089a7573' -ReleasePath 'C:\Users\james\asp-model-studio\outputs\nba-gen1-slate-publisher-v1\release-final\releases\sha256\c123faf6e48fc2db7f60729671e13c320d2ec1cd86944d603fac9f0e136a2dd9\release.json' -ReleaseSha256 'c123faf6e48fc2db7f60729671e13c320d2ec1cd86944d603fac9f0e136a2dd9' -InputPointer 'C:\Users\james\asp-model-studio\outputs\nba-gen1-slate-publisher-v1\inputs\current.json'
```

```powershell
& 'C:\Users\james\asp-model-studio\.deployments\nba-gen1-slate-publisher\0aa50236f9dcac875106c13c6749e025126370e700a4467915275251ad583a88\scripts\install_nba_gen1_slate_publisher.ps1' -Mode Verify -DeploymentId '0aa50236f9dcac875106c13c6749e025126370e700a4467915275251ad583a88' -ExpectedManifestSha256 '4454b2e4cd0981e9d98bb900972459d54117ca72919867375e5c0d0b089a7573' -ReleasePath 'C:\Users\james\asp-model-studio\outputs\nba-gen1-slate-publisher-v1\release-final\releases\sha256\c123faf6e48fc2db7f60729671e13c320d2ec1cd86944d603fac9f0e136a2dd9\release.json' -ReleaseSha256 'c123faf6e48fc2db7f60729671e13c320d2ec1cd86944d603fac9f0e136a2dd9' -InputPointer 'C:\Users\james\asp-model-studio\outputs\nba-gen1-slate-publisher-v1\inputs\current.json'
```

```powershell
& 'C:\Users\james\asp-model-studio\.deployments\nba-gen1-slate-publisher\0aa50236f9dcac875106c13c6749e025126370e700a4467915275251ad583a88\scripts\install_nba_gen1_slate_publisher.ps1' -Mode Remove -DeploymentId '0aa50236f9dcac875106c13c6749e025126370e700a4467915275251ad583a88' -ExpectedManifestSha256 '4454b2e4cd0981e9d98bb900972459d54117ca72919867375e5c0d0b089a7573' -ReleasePath 'C:\Users\james\asp-model-studio\outputs\nba-gen1-slate-publisher-v1\release-final\releases\sha256\c123faf6e48fc2db7f60729671e13c320d2ec1cd86944d603fac9f0e136a2dd9\release.json' -ReleaseSha256 'c123faf6e48fc2db7f60729671e13c320d2ec1cd86944d603fac9f0e136a2dd9' -InputPointer 'C:\Users\james\asp-model-studio\outputs\nba-gen1-slate-publisher-v1\inputs\current.json'
```

After separately authorized installation, observe natural invocations; never
substitute local verification for Task Scheduler/S4U success. Compare the task
action and runtime binding, launcher/runner receipts and owner count. Runtime:
`C:\Users\james\asp-model-studio\.runtime\nba-gen1-slate-publisher`.
The installer unregisters its newly created task if its immediate verification
fails; it never overwrites another owner. No other sport owner is altered.

Input refresh is independently inactive. Inspect its no-network plan:

```powershell
& 'C:\Users\james\asp-model-studio\.venv\Scripts\python.exe' 'C:\Users\james\asp-model-studio\.deployments\nba-gen1-slate-publisher\0aa50236f9dcac875106c13c6749e025126370e700a4467915275251ad583a88\scripts\capture_nba_slate_refresh.py'
```

Later live capture requires `--execute --authorization <James-approved-receipt>
--authorization-sha256 <physical-sha> --private-root <private-store>`. The receipt
schema is `NBA_SLATE_REFRESH_AUTHORIZATION_V1`, with authorizedBy=James,
executeApproved=true, validFromUtc/validUntilUtc, the exact REFRESH_PLAN.json
object and rightsEvidence physical references. No such authorization is issued here.
The existing NBA forecast task does NOT call this network client. A future
authorized same-owner capture phase may call it, then admit its returned receipt:

```powershell
& 'C:\Users\james\asp-model-studio\.venv\Scripts\python.exe' 'C:\Users\james\asp-model-studio\.deployments\nba-gen1-slate-publisher\0aa50236f9dcac875106c13c6749e025126370e700a4467915275251ad583a88\scripts\admit_nba_gen1_slate_inputs.py' --capture '<CAPTURE_RECEIPT>' --base-model-receipt 'C:\Users\james\asp-model-studio\outputs\nba-gen1-long-gap-v1\current-research\receipt.json' --base-coverage 'C:\Users\james\asp-model-studio\outputs\nba-gen1-long-gap-v1\current-history-coverage.json' --rights 'C:\Users\james\asp-model-studio\outputs\nba-gen1-long-gap-v1\source-review\admission.json' --rights 'C:\Users\james\asp-model-studio\outputs\nba-gen1-long-gap-v1\source-review\hoopr-LICENSE.md' --registry-root 'C:\Users\james\asp-model-studio\outputs\nba-gen1-slate-publisher-v1\inputs' --season-end 2027 --reviewed-by '<responsible Model Studio owner>'
```

Do not copy the old capture and restamp it. Changes produce append-only input
versions and an atomic pointer; the executable, model and preprocessing remain fixed.
Current acquisition age and the checkpoint must pass before new forecasts or reuse.
