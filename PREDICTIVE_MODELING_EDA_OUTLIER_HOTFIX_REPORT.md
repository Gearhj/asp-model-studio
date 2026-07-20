# Predictive Modeling EDA / Outlier Hotfix Report

## 1. Root Cause of EDA 404

The visible EDA regression was caused by frontend/backend route drift in the local development environment. The current frontend calls `POST /api/eda/workspace/{section}` for lazy EDA sections. The patched source backend exposes that route, but the running browser dev proxy on `5174` was still pointed at a stale backend on `8001`, where `POST /api/eda/workspace/overview` returned `404` with an empty body. The active patched backend on `8004` returned the EDA overview successfully.

## 2. Exact Failing Endpoint

- URL: `/api/eda/workspace/overview`
- Method: `POST`
- Payload: current EDA workspace request body, initially `{}` / target inferred from backend dataset state
- Observed stale-backend status: `404`
- Observed stale-backend response body: empty

## 3. Backend Route Fix

`server/eda/eda_router.py` now preserves `POST /api/eda/workspace/{section}` and adds compatibility aliases:

- `POST /api/eda/profile`
- `POST /api/eda/analyze`

The router now returns structured `409` JSON when the backend dataset or target contract is missing, instead of a generic failure.

## 4. Dataset Registration Contract Fix

The canonical EDA and Outlier services continue to use `DatasetStore` through `DATASTORE.get_active_df()` and `DATASTORE.get_raw_active_df()`. Missing backend dataset state is now reported as a controlled session/dataset problem so the UI tells the user to return to Data Acquisition and re-register, instead of rendering a blank page.

## 5. EDA Fallback Behavior

The EDA page now renders the shell, hero, tabs, recovery panel, and disabled completion state when the backend route or dataset is unavailable. The user sees:

- what failed
- the endpoint
- response status
- recovery guidance
- Retry
- Go to Data Acquisition
- technical details disclosure

It no longer displays only `Not Found`.

## 6. EDA Performance Changes

The existing lazy section design remains intact: Overview loads first, and Target, Predictors, Relationships, Stability, and Findings load on tab demand. The patch keeps shell-first rendering and avoids synchronous all-tab computation before the page appears.

## 7. Root Cause of Outlier `.map()` Crash

The Outlier page assumed `payload.features`, per-feature `methods`, `rendered_sample`, and `quantiles` were always present. When backend profile loading failed or returned a partial payload, array/object operations could run against `undefined`.

## 8. Null-Safety Changes

Added `src/lib/workflowSafety.ts` with:

- `safeArray`
- `safeObject`
- `formatNullableMetric`
- `getDatasetScopeLabel`

EDA and Outliers now normalize missing arrays and objects before rendering. Outliers also shows a blocked recovery panel with Retry, Go to Data Acquisition, Go to EDA, and technical details.

## 9. Downstream Pages Audited

Reviewed the shared profile consumers in:

- Step02 EDA
- Step03 Outliers
- Step04 Missing Values
- Step05 Feature Engineering
- Step06 Balance & Split
- Step07 Model Training

The direct crash path was fixed in EDA and Outliers, and the existing downstream pages already use guarded `?? []` / optional access patterns for the relevant profile fields.

## 10. Tests Added

Updated `tests/predictiveModelingRepair.test.mjs` to assert:

- EDA unavailable panel exists
- EDA recovery actions exist
- EDA route unavailable messaging exists
- EDA uses `safeArray` and `safeObject`
- Outliers uses `safeArray`
- Outliers recovery actions exist
- Backend EDA workspace route is registered
- Backend compatibility aliases are registered
- Backend structured `backend_dataset_missing` handling exists

## 11. Tests Run

- `npx tsc -b`
- `npm run test:predictive-modeling-repair`
- `npm run test:workflow-navigation-state`
- `npm run test:open-project`
- `npm run test:persistence`
- `npm run test:regression`
- `npm run test:dataset-library`
- `npm run test:credit-risk-studio`
- `npm run build`

## 12. Test Results

All listed tests passed. `npm run build` passed. Vite reported existing browser-data/chunk-size warnings only.

## 13. Manual Acceptance Results

Manual backend route checks:

- FastAPI app route inspection confirmed `POST /api/eda/workspace/{section}`, `POST /api/eda/profile`, and `POST /api/eda/analyze`.
- Stale `8001` backend reproduced the browser symptom: `POST /api/eda/workspace/overview` returned `404`.
- Patched `8004` backend returned `200` for `POST /api/eda/workspace/overview`, with full-dataset EDA overview payload.
- Restarted the `5174` Vite dev server after the proxy fix.
- Browser-facing proxy check returned `200` for `POST http://127.0.0.1:5174/api/eda/workspace/overview`.

Full browser route and backend proxy wiring were verified after restarting the `5174` dev server.

## 14. Remaining Limitations

If a stale backend remains running on the proxy port, the browser can still call old code until the dev server/backend are restarted. The Vite proxy now defaults to `8004` and supports `VITE_API_PROXY_TARGET` for explicit backend selection.

## 15. Files Modified

- `server/eda/eda_router.py`
- `src/lib/workflowSafety.ts`
- `src/steps/Step02_EDA.tsx`
- `src/steps/Step04_Outliers.tsx`
- `tests/predictiveModelingRepair.test.mjs`
- `vite.config.ts`

## 16. No Fake Analytics Introduced

No fake EDA, outlier, missing-value, feature, split, or training metrics were introduced. The UI renders controlled unavailable states when backend analytics are not available.

## 17. Source Workspace Confirmation

All changes were made in `C:\Users\james\ds-workflow-starter`.

## 18. Clean Copy Sync Confirmation

`npm run sync:atlas` was run after validation. The first sandboxed run was blocked by Windows access denied on the clean-copy destination despite script exit code `0`. The sync was rerun with escalation and completed successfully with robocopy code `3`, copying 30 files with zero failures.
