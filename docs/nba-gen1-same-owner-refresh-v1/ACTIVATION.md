# Final successor activation and rollback — not executed

Deployment: `34b4060ff4ae4609f4fb61a2c5bd8518fa0587396e5cd1c489d78ec411d8ccf6`; physical manifest SHA-256 `07c0b9b95578f78fbecee77718ff697f61fb2586e271a9a2f7e77a28891ac5ec`.
Source commit: `a4f3058759889a7fa8406a12a49ab1b905541ae4`. All 35 members verified.
Do not install superseded 0aa50236 or 7e04b1cc. No NBA task currently exists.

The installer Plan passed read-only with owner count zero. The proposed single owner is S4U / Limited / IgnoreNew, 15-minute cadence, 12-minute execution budget. It refuses a different existing owner. This task did not request Windows elevation, install, or start a scheduled task.

Exact disabled-network commands, for separately authorized execution where applicable:

```powershell
& 'C:\Users\james\asp-model-studio\.deployments\nba-gen1-slate-publisher\34b4060ff4ae4609f4fb61a2c5bd8518fa0587396e5cd1c489d78ec411d8ccf6/scripts/install_nba_gen1_slate_publisher.ps1' -Mode Plan -DeploymentId '34b4060ff4ae4609f4fb61a2c5bd8518fa0587396e5cd1c489d78ec411d8ccf6' -ExpectedManifestSha256 '07c0b9b95578f78fbecee77718ff697f61fb2586e271a9a2f7e77a28891ac5ec' -ReleasePath 'C:\Users\james\asp-model-studio\outputs\nba-gen1-same-owner-refresh-v1\release-final\releases\sha256\515a5e128c1037fb039382e23f3a0dd9820b924eba5fc13cb10bca67e80ec435\release.json' -ReleaseSha256 '515a5e128c1037fb039382e23f3a0dd9820b924eba5fc13cb10bca67e80ec435' -InputPointer 'C:\Users\james\asp-model-studio\outputs\nba-gen1-same-owner-refresh-v1\inputs\current.json'
```

```powershell
& 'C:\Users\james\asp-model-studio\.deployments\nba-gen1-slate-publisher\34b4060ff4ae4609f4fb61a2c5bd8518fa0587396e5cd1c489d78ec411d8ccf6/scripts/install_nba_gen1_slate_publisher.ps1' -Mode Install -DeploymentId '34b4060ff4ae4609f4fb61a2c5bd8518fa0587396e5cd1c489d78ec411d8ccf6' -ExpectedManifestSha256 '07c0b9b95578f78fbecee77718ff697f61fb2586e271a9a2f7e77a28891ac5ec' -ReleasePath 'C:\Users\james\asp-model-studio\outputs\nba-gen1-same-owner-refresh-v1\release-final\releases\sha256\515a5e128c1037fb039382e23f3a0dd9820b924eba5fc13cb10bca67e80ec435\release.json' -ReleaseSha256 '515a5e128c1037fb039382e23f3a0dd9820b924eba5fc13cb10bca67e80ec435' -InputPointer 'C:\Users\james\asp-model-studio\outputs\nba-gen1-same-owner-refresh-v1\inputs\current.json'
```

```powershell
& 'C:\Users\james\asp-model-studio\.deployments\nba-gen1-slate-publisher\34b4060ff4ae4609f4fb61a2c5bd8518fa0587396e5cd1c489d78ec411d8ccf6/scripts/install_nba_gen1_slate_publisher.ps1' -Mode Verify -DeploymentId '34b4060ff4ae4609f4fb61a2c5bd8518fa0587396e5cd1c489d78ec411d8ccf6' -ExpectedManifestSha256 '07c0b9b95578f78fbecee77718ff697f61fb2586e271a9a2f7e77a28891ac5ec' -ReleasePath 'C:\Users\james\asp-model-studio\outputs\nba-gen1-same-owner-refresh-v1\release-final\releases\sha256\515a5e128c1037fb039382e23f3a0dd9820b924eba5fc13cb10bca67e80ec435\release.json' -ReleaseSha256 '515a5e128c1037fb039382e23f3a0dd9820b924eba5fc13cb10bca67e80ec435' -InputPointer 'C:\Users\james\asp-model-studio\outputs\nba-gen1-same-owner-refresh-v1\inputs\current.json'
```

```powershell
& 'C:\Users\james\asp-model-studio\.deployments\nba-gen1-slate-publisher\34b4060ff4ae4609f4fb61a2c5bd8518fa0587396e5cd1c489d78ec411d8ccf6/scripts/install_nba_gen1_slate_publisher.ps1' -Mode Remove -DeploymentId '34b4060ff4ae4609f4fb61a2c5bd8518fa0587396e5cd1c489d78ec411d8ccf6' -ExpectedManifestSha256 '07c0b9b95578f78fbecee77718ff697f61fb2586e271a9a2f7e77a28891ac5ec' -ReleasePath 'C:\Users\james\asp-model-studio\outputs\nba-gen1-same-owner-refresh-v1\release-final\releases\sha256\515a5e128c1037fb039382e23f3a0dd9820b924eba5fc13cb10bca67e80ec435\release.json' -ReleaseSha256 '515a5e128c1037fb039382e23f3a0dd9820b924eba5fc13cb10bca67e80ec435' -InputPointer 'C:\Users\james\asp-model-studio\outputs\nba-gen1-same-owner-refresh-v1\inputs\current.json'
```

For production refresh, James must first approve this exact REFRESH_AUTHORIZATION_PROPOSAL.json and REFRESH_PLAN.json hash and the final deployment installation. Create a separate immutable approved grant from REFRESH_GRANT_TEMPLATE.json, retain the actual approval, and compute its physical SHA. Then append the following to the same Plan/Install/Verify/Remove commands (not a separate task):

```powershell
-EnableNetwork -RefreshGrantPath '<exact approved grant path>' -RefreshGrantSha256 '<physical approved grant SHA-256>'
```

The template remains false and cannot authorize capture. Grant filenames/approval clocks cannot honestly be supplied before authorization. Installation may precede the grant's future start; the owner remains zero-network until a legitimately due capture inside the exact period. Never install disabled mode and silently edit the runtime binding; use the supported installer with the intended approved configuration.

Rollback: use **Remove** with the exact same pins and grant arguments used for Install. It verifies the task and runtime binding, stops/unregisters only that exact NBA owner and removes only its binding. Keep every deployment, input, source object, package, discovery and receipt. The prior state is **no NBA task**; do not install a superseded deployment. An immediate Install verification failure unregisters only its newly created task. A differing owner/binding stops for review rather than overwriting it.

After authorized installation, verify the action/principal/runtime binding and observe natural invocations. The local wrapper evidence here is not proof of S4U or live-source success. AISP activation remains a separate owner action; no environment or consumer change belongs in this installer.
