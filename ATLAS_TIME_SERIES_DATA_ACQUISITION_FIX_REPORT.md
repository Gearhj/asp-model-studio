# ATLAS Time Series Data Acquisition Fix Report

## 1. Scope
Fixed the Time Series & Forecasting Data Acquisition page so it is a real governed data selection, upload, mapping, profile, and persistence step instead of a cosmetic scaffold.

## 2. Files Changed
- `src/workflows/time-series/TimeSeriesDataAcquisition.tsx`
- `src/workflows/time-series/TimeSeriesWorkflowShell.tsx`
- `src/workflows/time-series/timeSeriesCodeTemplates.ts`
- `tests/timeSeriesForecasting.test.mjs`

## 3. Data Source Behavior
The page now exposes Dataset Library, Upload and Register, Existing Project Dataset, SQL Data Studio, and Python / Notebook Output source cards. Dataset Library and Upload and Register are active. SQL and Python outputs are intentionally disabled until those outputs are registered as governed datasets.

## 4. Dataset Library Integration
The page calls `listDatasets`, `listProjectDatasets`, `getDatasetProfile`, and `getDatasetPreview`. Selecting a registered dataset loads the latest version metadata, schema, profile, and preview rows.

## 5. Upload and Register
The page calls the existing `uploadDataset` Dataset Library API with a Time Series & Forecasting domain and then selects the registered dataset for mapping.

## 6. Schema-Driven Mapping
Mapping controls are populated from real profile schema or preview columns. The old hardcoded examples in the shared shell were removed.

## 7. Required Mapping Fields
The page supports date/time column, target value column, entity/group multi-select, optional segment column, exogenous driver multi-select, aggregation frequency, aggregation method, missing timestamp policy, duplicate timestamp policy, forecast horizon, and evaluation metrics.

## 8. Store Item Demand Recognition
The page recognizes datasets with `date`, `store`, `item`, and `sales` columns and recommends Daily frequency, Sum aggregation, store + item entity grain, a 90-day horizon, and WAPE / MAE / RMSE / Bias metrics.

## 9. Profiling
The page computes a visible preview profile from loaded dataset metadata and preview rows: row count, column count, date coverage, unique periods, duplicate timestamp rows, entity count, exogenous drivers, target summary, top entities, target-over-time chart, timestamp heatmap, mapping table, and preview rows.

## 10. Visuals
The page includes a single Time coverage timeline, a single Missing timestamp calendar heatmap, a target-over-time line chart, target profile cards, entity profile, Data mapping table, and preview table.

## 11. Persistence
Confirming the page writes a compact local `atlas-time-series-data-acquisition:{projectId}` bundle and updates workflow state through the workflow store.

## 12. Database Evidence
Confirming the page writes a `time_series_input_bundle` evidence artifact through `saveEvidenceToDatabase`, with dataset lineage and registry-visible tags.

## 13. Decision and Audit Trail
Confirming the page records a decision journal event and database decision record. The persisted payload includes an `audit_log` action summary.

## 14. Navigation
The page marks Time Series Data Acquisition complete, marks Time Series Profile in progress, saves the active project snapshot, mirrors the project to SQLite, and navigates to the next Time Series workflow route.

## 15. Code Panel
The page now has Time Series Data Acquisition-specific Python and SAS-compatible code. The shared time-series code template was also updated to load from Dataset Library and save the input bundle artifact.

## 16. Automated Validation
Passed:
- `npx tsc -b`
- `npm run build`
- `npm run test:time-series-forecasting`
- `npm run test:workflow-library`
- `npm run test:dataset-library`
- `npm run test:persistence`
- `npm run test:registry-dashboard`
- `npm run test:validation-center`
- `npm run test:sqlite-persistence`
- `npm run test:regression`
- `npm run test:project-types`
- `npm run test:workflow-navigation-state`
- `npm run test:open-project`
- `npm run test:model-documentation`
- `npm run test:evidence-graph`
- `npm run test:optimization`
- `npm run test:user-management`
- `npm run test:credit-risk-studio`

## 17. Clean Copy Sync
`npm run sync:atlas` was run after validation to sync the clean copy. The sandboxed attempt hit destination access denial, then the elevated rerun succeeded and copied the validated source to `C:\Users\james\Projects\ATLAS\atlas-app`.
