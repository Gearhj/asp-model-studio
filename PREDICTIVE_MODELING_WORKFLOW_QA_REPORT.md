# Predictive Modeling Workflow QA Report

## Phase 10I Cleanup Summary

This pass addressed Predictive Modeling QA issues found in the recovered classification workflow while preserving the existing regression workflow behavior.

## Fixes Completed

### Open Project

- Moved Project Recovery, Deep Recovery Scan, and Project Storage Diagnostics into `Advanced Recovery Tools`.
- Projects, search, filters, and Card/Detailed View controls now appear first.
- Advanced Recovery Tools auto-expands only when recovery/storage attention is required.

### EDA Classification Target Analysis

- Classification targets now render a class-distribution view instead of regression-style percentiles.
- Added class counts, event count, non-event count, event rate, non-event rate, class balance, target missingness, and rare-event warning.
- Replaced the misleading target histogram with a class count bar chart and event-rate summary.
- Regression targets still use the continuous target histogram and percentile diagnostics.

### EDA Layout

- Moved Feature, Render Sample %, Bins, and Layout controls below Target Variable Analysis.
- Added `Feature Investigation Controls` section before selected-feature charts.

### Feature Engineering VIF

- Fixed false `Too many missing values` results caused by requiring at least 20 numeric values from a small preview sample.
- VIF eligibility now uses a true missingness threshold.
- VIF excludes target, ID-like, row/index, prediction/output, residual, diagnostic, and rank fields.
- Added diagnostics: Rows used for VIF, Predictors evaluated, Predictors excluded, and Missingness threshold.

### Interpretation

- Classification models no longer enter the Linear Regression Statistical Output path.
- Linear Regression OLS-style output is gated to true regression Linear Regression models.
- Logistic Regression now renders logistic coefficients, odds ratios, and log-odds guidance.
- KNN now renders `K-Nearest Neighbors` and a classifier-specific interpretation panel.
- KNN no longer relies on a hard-coded `KNN (k=7)` label; if k is unavailable, the panel says `k not available`.

### RFE

- Added frontend timeout protection for RFE requests.
- RFE now reports `RFE could not complete: <reason>` on failure.
- Unsupported models such as KNN/SVM-style models show: `RFE is not available for the selected model. Select a linear, tree, or estimator-compatible model.`
- Added visible running status with timeout-protection language.

## Tests Run

- `npx tsc -b`
- `npm run test:open-project`
- `npm run test:persistence`
- `npm run test:dataset-library`
- `npm run test:regression`
- `npm run test:model-diagnostics`
- `npm run test:chart-studio`
- `npm run test:analytics-workbench`
- `npm run build:modeling`
- `npm run build`

## Manual QA Status

Manual browser QA was not completed in this automated pass. Static coverage, TypeScript compilation, and production builds passed in the working source folder.

## Known Limitations

- RFE timeout is enforced in the frontend; long backend work may still continue server-side until the request is cancelled or the backend finishes.
- Feature Engineering VIF uses the best available browser/backend sample, not a full warehouse-scale modeling matrix.
- KNN local neighbor explanations depend on backend neighbor-detail availability; the current panel provides model-specific guidance and available hyperparameter readout.

## Clean-Copy Sync

Completed with `npm run sync:atlas`.

Clean-copy verification passed in `C:\Users\james\Projects\ATLAS\atlas-app`:

- `npm run test:open-project`
- `npm run test:regression`
- `npm run test:model-diagnostics`
- `npm run build`

The sync intentionally excluded `server/artifacts`, `.runtime`, dependency folders, build output, caches, and local environment files.

## Source Verification Result

Passed in `C:\Users\james\ds-workflow-starter`:

- `npx tsc -b`
- `npm run test:open-project`
- `npm run test:persistence`
- `npm run test:dataset-library`
- `npm run test:regression`
- `npm run test:model-diagnostics`
- `npm run test:chart-studio`
- `npm run test:analytics-workbench`
- `npm run build:modeling`
- `npm run build`

Build warnings observed but not blocking:

- Browser baseline / caniuse-lite data is stale.
- The main Vite bundle is larger than the default warning threshold.

## Final Phase 10I Status

Complete. Predictive Modeling cleanup changes were verified in the source workspace and synced to the clean ATLAS copy.
