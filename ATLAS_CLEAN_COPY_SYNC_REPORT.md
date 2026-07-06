# ATLAS Clean-Copy Sync Report

## Folder Roles

- Source workspace: `C:\Users\james\ds-workflow-starter`
- Clean ATLAS copy: `C:\Users\james\Projects\ATLAS\atlas-app`

Neither folder was renamed, moved, or deleted.

## Sync Command

Command run from the source workspace:

```powershell
npm run sync:atlas
```

This calls:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/sync-atlas-clean-copy.ps1
```

## Sync Script

Created:

`scripts/sync-atlas-clean-copy.ps1`

The script copies source code and documentation from the source workspace to the clean ATLAS copy using `robocopy`.

## Copy Result

Robocopy completed successfully with code `3`.

Summary from the sync run:

| Category | Total | Copied | Skipped | Failed | Extras |
|---|---:|---:|---:|---:|---:|
| Directories | 122 | 56 | 66 | 0 | 0 |
| Files | 536 | 340 | 196 | 0 | 3 |
| Bytes | 34.78 MB | 32.72 MB | 2.06 MB | 0 | 1.7 KB |

Robocopy code `3` means files were copied and some extra files were present in the destination. It is still a successful result because there were no failed copies.

## Exclusions

Excluded directories:

- `.git`
- `node_modules`
- `dist`
- `.venv`
- `__pycache__`
- `.pytest_cache`
- `.cache`
- `.runtime`
- `server\artifacts`

Excluded files:

- `.env`
- `.env.local`
- `*.pyc`

## Runtime Artifacts

`server/artifacts` was intentionally excluded from the default sync.

Reason: this folder contains runtime/user-generated data such as dataset artifacts and analytics artifacts. The sync is intentionally non-destructive and should not overwrite or delete user runtime data unless explicitly requested.

## Hash Verification

All required key files matched by SHA256 after sync.

| File | Source Modified | Destination Modified | Match |
|---|---|---|---|
| `package.json` | 2026-07-06 16:56:48 | 2026-07-06 16:56:48 | Yes |
| `src/apps/ModelingApp.tsx` | 2026-07-06 16:19:29 | 2026-07-06 16:19:29 | Yes |
| `src/components/Sidebar.tsx` | 2026-07-06 16:19:45 | 2026-07-06 16:19:45 | Yes |
| `src/steps/AnalyticsWorkbench.tsx` | 2026-07-06 16:23:19 | 2026-07-06 16:23:19 | Yes |
| `src/steps/DatasetLibrary.tsx` | 2026-07-06 14:57:31 | 2026-07-06 14:57:31 | Yes |
| `src/steps/DatasetDetail.tsx` | 2026-07-06 16:20:43 | 2026-07-06 16:20:43 | Yes |
| `src/steps/Step01_DataAcquisition.tsx` | 2026-07-06 13:20:49 | 2026-07-06 13:20:49 | Yes |
| `src/steps/Step09_Interpretation.tsx` | 2026-07-06 12:24:18 | 2026-07-06 12:24:18 | Yes |
| `src/lib/datasetLibrary.ts` | 2026-07-06 16:05:26 | 2026-07-06 16:05:26 | Yes |
| `src/lib/auth.ts` | 2026-07-06 14:58:06 | 2026-07-06 14:58:06 | Yes |
| `server/main.py` | 2026-07-06 16:14:39 | 2026-07-06 16:14:39 | Yes |
| `server/datasets/dataset_router.py` | 2026-07-06 14:51:36 | 2026-07-06 14:51:36 | Yes |
| `server/security/security_router.py` | 2026-07-06 14:58:56 | 2026-07-06 14:58:56 | Yes |
| `server/analytics/analytics_router.py` | 2026-07-06 16:22:18 | 2026-07-06 16:22:18 | Yes |

Full SHA256 evidence:

| File | Source SHA256 | Destination SHA256 |
|---|---|---|
| `package.json` | `F5C2FB1F326128DE69B77381B9CC14BDEAFBC9AEEB030D2B564DDCABCBFE8656` | `F5C2FB1F326128DE69B77381B9CC14BDEAFBC9AEEB030D2B564DDCABCBFE8656` |
| `src/apps/ModelingApp.tsx` | `84F10A9057B40FEFEEC3A8EE5F577100D532D74807D3D925EA71E6D730523CFE` | `84F10A9057B40FEFEEC3A8EE5F577100D532D74807D3D925EA71E6D730523CFE` |
| `src/components/Sidebar.tsx` | `5EAA81BDBCE736D9F60DF6590DF7504AD2292EA3A835E123CAFE50DAC88A564A` | `5EAA81BDBCE736D9F60DF6590DF7504AD2292EA3A835E123CAFE50DAC88A564A` |
| `src/steps/AnalyticsWorkbench.tsx` | `A61179D02751A8CBFCF13D3444C68664700DBA34200022BAE5B4144DC435A49A` | `A61179D02751A8CBFCF13D3444C68664700DBA34200022BAE5B4144DC435A49A` |
| `src/steps/DatasetLibrary.tsx` | `0F4980C88AE3027AD6C2D8C6299B0635516174E7736A154F00F4767EAF47FF10` | `0F4980C88AE3027AD6C2D8C6299B0635516174E7736A154F00F4767EAF47FF10` |
| `src/steps/DatasetDetail.tsx` | `8C552EE3A15D515188842BF4340BB71266771E4A480CE6B71ED5D5723FBD519F` | `8C552EE3A15D515188842BF4340BB71266771E4A480CE6B71ED5D5723FBD519F` |
| `src/steps/Step01_DataAcquisition.tsx` | `1BCE22D59C633F5E968EE6EE40640294C0B51258BDD6E40FE9BA48814E045685` | `1BCE22D59C633F5E968EE6EE40640294C0B51258BDD6E40FE9BA48814E045685` |
| `src/steps/Step09_Interpretation.tsx` | `CC4C68716326946641319CE0197FE4C412C84CBB66648658D71F42A9DD0B92D0` | `CC4C68716326946641319CE0197FE4C412C84CBB66648658D71F42A9DD0B92D0` |
| `src/lib/datasetLibrary.ts` | `8D31144BBE78354DC624C1C98A4996BE855798DBBF7C1D5294054D11B831188B` | `8D31144BBE78354DC624C1C98A4996BE855798DBBF7C1D5294054D11B831188B` |
| `src/lib/auth.ts` | `CDECC9772FC6E7E5A83C4484B5EFF39B6FCF23150AFEC495DB9D39015468A39A` | `CDECC9772FC6E7E5A83C4484B5EFF39B6FCF23150AFEC495DB9D39015468A39A` |
| `server/main.py` | `70DD5835F4E6C9173789D79079F97FBF39325642AD37D27E45E3DA21AA23F101` | `70DD5835F4E6C9173789D79079F97FBF39325642AD37D27E45E3DA21AA23F101` |
| `server/datasets/dataset_router.py` | `CA4C86FEF7DEC600C37EC5CCB830CF77E7D0D77CC21FC401778A63CF1222A123` | `CA4C86FEF7DEC600C37EC5CCB830CF77E7D0D77CC21FC401778A63CF1222A123` |
| `server/security/security_router.py` | `491B89319E6E7527D4EBD78839297C70D8DC19A5D3E95C732FA29A1A7FD5DEA3` | `491B89319E6E7527D4EBD78839297C70D8DC19A5D3E95C732FA29A1A7FD5DEA3` |
| `server/analytics/analytics_router.py` | `ED2239F46B98988129319C0E409EF556EC5D87D22ED7EE05AF8162493B945DC4` | `ED2239F46B98988129319C0E409EF556EC5D87D22ED7EE05AF8162493B945DC4` |

## Clean-Copy Verification

Commands run from `C:\Users\james\Projects\ATLAS\atlas-app`:

```powershell
npm run build
npm run test:user-management
npm run test:dataset-library
npm run test:analytics-workbench
```

Results:

- `npm run build`: passed.
- `npm run test:user-management`: passed, 25 assertions.
- `npm run test:dataset-library`: passed.
- `npm run test:analytics-workbench`: passed.

Build warnings:

- Existing Vite chunk-size warning remains.
- Existing stale browser data warnings remain for `baseline-browser-mapping` and `caniuse-lite`.

## Known Limitations

- The sync is non-destructive and does not remove extra files in the clean copy.
- `server/artifacts` is intentionally excluded by default and must be handled separately if runtime data needs to be copied.
- The clean-copy build validates the frontend bundle, not the live backend server process.

## Acceptance Status

- Sync script exists: yes.
- Clean ATLAS copy has current source files: yes.
- SHA256 comparison confirms key files match: yes.
- Clean-copy build passes: yes.
- Clean-copy tests pass: yes.
- Sync report documents result: yes.

The clean-copy sync gate is passed.

## Post-Upgrade Sync Addendum

After the Analytics Workbench UX and Code Workspace upgrade, `npm run sync:atlas` was run again.

Additional changed files verified after the upgrade:

| File | Source Modified | Destination Modified | Match |
|---|---|---|---|
| `package.json` | 2026-07-06 16:56:48 | 2026-07-06 16:56:48 | Yes |
| `src/steps/AnalyticsWorkbench.tsx` | 2026-07-06 17:06:17 | 2026-07-06 17:06:17 | Yes |
| `server/python_execution.py` | 2026-07-06 17:01:03 | 2026-07-06 17:01:03 | Yes |
| `tests/analyticsWorkbench.test.mjs` | 2026-07-06 17:05:18 | 2026-07-06 17:05:18 | Yes |
| `ANALYTICS_WORKBENCH_PHASE_8_REPORT.md` | 2026-07-06 17:05:51 | 2026-07-06 17:05:51 | Yes |

Post-upgrade SHA256 evidence:

| File | Source SHA256 | Destination SHA256 |
|---|---|---|
| `package.json` | `F5C2FB1F326128DE69B77381B9CC14BDEAFBC9AEEB030D2B564DDCABCBFE8656` | `F5C2FB1F326128DE69B77381B9CC14BDEAFBC9AEEB030D2B564DDCABCBFE8656` |
| `src/steps/AnalyticsWorkbench.tsx` | `9A0968BE75549BF9C276ED636A89F3D3784FF67F348EC6F6666CBED47BCBE702` | `9A0968BE75549BF9C276ED636A89F3D3784FF67F348EC6F6666CBED47BCBE702` |
| `server/python_execution.py` | `F06E15EDCDC4C178B99D69E5DD1606025F65CD4F08915044FBCC8DA9CD3E055A` | `F06E15EDCDC4C178B99D69E5DD1606025F65CD4F08915044FBCC8DA9CD3E055A` |
| `tests/analyticsWorkbench.test.mjs` | `F7633D820DD8FE81F3C5BCF06B073396A03F63B1F002BDCD6237AFE96ABE8088` | `F7633D820DD8FE81F3C5BCF06B073396A03F63B1F002BDCD6237AFE96ABE8088` |
| `ANALYTICS_WORKBENCH_PHASE_8_REPORT.md` | `1B61072E0C6534A1844488F3B3AED5AA0A2E4EF712B6E963320BCCFAA460C6F3` | `1B61072E0C6534A1844488F3B3AED5AA0A2E4EF712B6E963320BCCFAA460C6F3` |

Post-upgrade clean-copy verification:

- `npm run test:analytics-workbench`: passed.
- `npm run test:user-management`: passed.
- `npm run test:dataset-library`: passed.
- `npm run test:persistence`: passed.
- `npm run build`: passed.
