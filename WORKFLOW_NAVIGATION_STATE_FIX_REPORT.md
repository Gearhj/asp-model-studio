# WORKFLOW_NAVIGATION_STATE_FIX_REPORT

## Root Cause

Several workflow pages were keeping important UI selections in component-local React state and then reinitializing from defaults when the page remounted. In some cases, saved browser state existed, but the page did not read it on mount. In other cases, backend column metadata was preferred over the user-filtered local dataset, which allowed excluded variables to reappear downstream.

The highest-risk issue was in Model Training: ATLAS persisted only selected model names, not the full checkbox map. That meant explicit deselections could be lost because the page could not distinguish "user intentionally turned this off" from "no saved state exists."

## Files Changed

- `package.json`
- `src/lib/localDataset.ts`
- `src/steps/Step01_DataAcquisition.tsx`
- `src/steps/Step04_MissingValues.tsx`
- `src/steps/Step04_Outliers.tsx`
- `src/steps/Step05_EncodingScaling.tsx`
- `src/steps/Step06_Train.tsx`
- `tests/workflowNavigationState.test.mjs`

## Pages Fixed

- Data Acquisition
  - Rehydrates target, selected features, rows, data quality, and metadata from the cached modeling dataset on mount.
  - Saves Select All / None changes immediately.
  - Preserves explicit empty feature selections instead of converting them back to all features.

- Outliers
  - Uses the user-selected local dataset columns as the authoritative feature scope whenever available.
  - Prevents excluded variables from reappearing from backend column metadata.

- Missing Values
  - Uses selected local dataset columns as the authoritative feature scope whenever available.
  - Rehydrates missing-value strategies from saved config.
  - Autosaves missing-value strategy edits so sidebar/direct navigation does not lose them.

- Feature Engineering
  - Rehydrates feature-builder state from compact local storage when store state is not populated.
  - Autosaves transforms, interactions, binning, and rule features.
  - Continues filtering controls to user-selected feature columns only.

- Model Training
  - Rehydrates max parallel models, calibration, PCA, grid search, search depth, and selected models from saved training config.
  - Persists a full `selected_map`, including explicit deselections.
  - Prevents problem-type/default selection logic from overwriting saved selections on remount.

- Experimental Design workflow
  - Confirmed existing dynamic workflow page reloads node evidence from `loadNodeState(projectId, step.id)` when project or step changes.
  - No additional Experimental Design code change was required in this pass.

## Automated Tests Added

Added `tests/workflowNavigationState.test.mjs` and `npm run test:workflow-navigation-state`.

Covered:

1. Data Acquisition selected columns rehydrate without excluded variables.
2. Explicit empty feature selections stay empty instead of defaulting to all columns.
3. Source regression checks confirm key workflow pages read saved state on remount.

## Test Results

- `npm run test:workflow-navigation-state` passed.
- `npm run build` passed.

Build warnings remain existing bundle-size/browser-data warnings only.

## Manual Back/Forward QA Results

Browser route smoke test completed against the running local app:

- Loaded `http://127.0.0.1:5174/step07`.
- Navigated to `http://127.0.0.1:5174/step08`.
- Used browser Back.
- Confirmed Step 7: Model Training rendered.
- Used browser Forward.
- Confirmed Step 8: Evaluation rendered.

Also confirmed direct route loads for:

- `http://127.0.0.1:5174/step07`
- `http://127.0.0.1:5174/step05`

The browser automation API available in this session is read-only for page storage writes, so I could not inject a synthetic upload session into browser storage for full file-upload QA. The automated test covers the selected-column cache behavior directly.

## Remaining Limitations

- Full manual upload/back-forward QA should still be run by the user with a real dataset because browser automation could not set file inputs or write session storage in this environment.
- Some older pages still use local storage keys rather than a single typed project snapshot field. This fix makes them rehydrate correctly, but a future cleanup should consolidate these per-page keys into a canonical project-state slice.
- Downstream invalidation is still warning-oriented in this pass. ATLAS does not yet produce a full dependency graph explaining exactly which later pages were invalidated by each upstream edit.
