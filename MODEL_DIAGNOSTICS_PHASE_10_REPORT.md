# ATLAS Phase 10A Model Diagnostics Report

## Summary

Phase 10A adds a governed scored-output path from Predictive Modeling Scoring into Dataset Library, Model Diagnostics, Chart Studio, Analytics Workbench, and exports.

## Implemented

- Added `POST /api/scoring/register-scored-dataset`.
- Added scored-output metadata using `datasetRole: "scored_output"`.
- Added automatic scored column detection for score, prediction, actual, residual, and decile.
- Added derived `atlas_residual` when actual and prediction are available.
- Added derived `atlas_score_decile` when score is available.
- Added `/model-diagnostics` route and sidebar item.
- Added diagnostics for score distribution, lift/decile, residuals, actual-vs-predicted, calibration, and segment performance.
- Added generated Python, SQL, R, and SAS-compatible code.
- Added Excel, Word, and PowerPoint diagnostics exports.
- Added “Save Diagnostics as Insight.”
- Added scored-output badges and links in Dataset Library and Dataset Detail.
- Added scored-output guidance and links in Chart Studio and Analytics Workbench.

## Data Handling

Scored datasets are persisted as backend Dataset Library artifacts under `server/artifacts/datasets`. Browser localStorage is not used for scored-output rows.

Current Scoring page registration stores the rows returned by the scoring response preview. It labels this limitation clearly. A future backend scoring artifact endpoint should register the full scored output without relying on the browser response.

## Tests

Added:

- `npm run test:model-diagnostics`

Required verification:

- `npx tsc -b`
- `npm run test:model-diagnostics`
- `npm run test:chart-studio`
- `npm run test:analytics-workbench`
- `npm run test:dataset-library`
- `npm run build:modeling`
- `npm run build`
- `npm run sync:atlas`

## Known Limitations

- Full warehouse-scale scored output storage is not implemented yet.
- Diagnostics currently operate on Dataset Library sample/preview artifacts.
- Stability tracking across multiple scored-output versions is not yet implemented.
- Model monitoring queue integration remains future work.

## Phase 10B Scored Registration Browser UX Fix

Phase 10B makes the scored-output path usable from the browser after scoring and adds explicit no-treatment handling on the Outliers page.

### Regression scored output registration

- The Scoring page now shows a visible `Register Scored Output` panel after scored preview rows exist.
- The panel includes dataset name, rows available, columns available, detected roles, and direct navigation to Dataset Library, Model Diagnostics, and Chart Studio.
- Regression scored preview rows are registered with `predicted_value` / `prediction` semantics instead of requiring a classification-style score or probability column.
- Regression diagnostics are marked as available for residual diagnostics, actual-versus-predicted, prediction distribution, and segment performance when supporting columns exist.
- The preview-row limitation is shown directly in the registration panel:
  `ATLAS will register the scored preview rows returned by this scoring run. Full scored-output artifact registration will be added when backend scoring artifacts are available.`

### Model Diagnostics dropdown fix

- Model Diagnostics now has actionable empty-state links:
  - `Go to Scoring`
  - `Open Dataset Library`
- Diagnostics fall back to the prediction column when a regression scored dataset does not contain a separate score/probability column.

### Dataset Library scored output visibility

- Registered scored outputs continue to use `datasetRole: "scored_output"` and are linked to the current project.
- Dataset Library and Dataset Detail continue to display the Scored Output metadata and diagnostics links.

### Chart Studio scored output visibility

- Registered scored outputs continue to satisfy the Chart Studio `Scored Outputs` filter through scored-output role/source metadata.

### Outliers None method support

- Outliers Global Method now includes `None - no treatment`.
- Individual variable Method now includes:
  - `Use global method`
  - `None - no treatment`
  - existing IQR, Z-score, and winsorization methods
- Variable-level `None` produces zero flagged outliers and no capping preview.
- The selected `None` value is persisted in `modeling-tool-outlier-methods`, so latitude/longitude style fields can remain untreated after reopen.
- The ATLAS readout explicitly says: `no outlier treatment applied`.

### Tests run

- Passed in this run:
  - `npx tsc -b`
  - `npm run test:model-diagnostics`
  - `npm run test:chart-studio`
  - `npm run test:analytics-workbench`
  - `npm run test:dataset-library`
  - `npm run test:regression`
  - `npm run test:persistence`
  - `npm run build:modeling`
  - `npm run build`
  - `python -m py_compile server\scoring\scoring_router.py server\model_diagnostics\diagnostics_store.py server\model_diagnostics\diagnostics_router.py`
  - Clean copy: `npm run test:model-diagnostics`
  - Clean copy: `npm run build`

### Manual QA results

- Browser QA attempted against `http://127.0.0.1:5174`, but the running app redirected direct workflow routes to `/login`. Sign in is required before completing the interactive checks below:
  - Score a regression dataset.
  - Confirm `Register Scored Output` panel appears.
  - Register scored preview output.
  - Confirm the dataset appears in Dataset Library, Model Diagnostics, and Chart Studio Scored Outputs.
  - Set Outliers global method to `None`.
  - Set Latitude and Longitude variable methods to `None`.
  - Reopen and confirm selections persist.

### Clean-copy sync confirmation

- Completed with `npm run sync:atlas`.
- Runtime artifacts under `server/artifacts` were intentionally excluded by the sync script.

## Phase 10C TRAIN Scored Output and Regression Diagnostics Fix

Phase 10C completes the scored-output diagnostic path for development TRAIN, TEST, and OOT/external scored datasets.

### TRAIN / TEST / OOT registration

- The Scoring page now exposes a visible `TRAIN Scored Output` card.
- TRAIN scoring uses `POST /api/score/development-split` and scores the backend development TRAIN split from the fitted final model.
- TEST and OOT registration remain available from uploaded scoring files.
- Registration success messages include the split name, such as `Scored TRAIN dataset registered.`
- Registration success actions include:
  - `Open in Model Diagnostics`
  - `Open Dataset Library`
  - `Open in Chart Studio`
- Model Diagnostics links include the registered `datasetId` and `versionId` when available.

### Actual target preservation

- Scoring responses now include `target_column` metadata when a target is available.
- Preview rows include both:
  - normalized `actual`
  - original target column name, for example `MedHouseVal`
- Scored registration passes `targetColumn`, `actualColumn`, `predictionColumn`, and residual role metadata into the Dataset Library artifact.

### Regression residual field generation

- Regression scored rows now include:
  - `predicted_value`
  - `prediction`
  - original target column, such as `MedHouseVal`
  - `actual`
  - `atlas_residual`
  - `atlas_abs_residual`
  - `atlas_squared_residual`
  - `atlas_percent_error`
- Backend registration also computes missing residual aliases when actual and prediction columns are available.

### Model Diagnostics regression layout

- Regression scored outputs use `Prediction Distribution` instead of treating predictions as classification probabilities.
- `Actual vs Predicted` renders when actual and prediction columns exist.
- `Residual Diagnostics` renders when actual/prediction or residual columns exist.
- `Segment Performance` uses an overrideable segment column and explains when no low-cardinality segment exists.

### Classification-only diagnostic guidance

- `Lift / Decile` now requires a score/probability column and binary actual outcome.
- `Calibration` now requires a score/probability column and binary actual outcome.
- Regression scored outputs show explanatory guidance instead of blank lift/calibration panels.

### Field override controls

Model Diagnostics now includes field mapping controls for:

- Actual column
- Prediction column
- Score/probability column
- Residual column
- Segment column
- Positive class value

These overrides are passed to `/api/model-diagnostics/run` so users can correct ATLAS role detection without rewriting the registered dataset.

### Tests run

- Passed in this Phase 10C verification run:
  - `npx tsc -b`
  - `python -m py_compile server\evaluation\eval_service.py server\evaluation\eval_router.py server\scoring\scoring_router.py server\model_diagnostics\diagnostics_store.py server\model_diagnostics\diagnostics_router.py`
  - `npm run test:model-diagnostics`
  - `npm run test:chart-studio`
  - `npm run test:analytics-workbench`
  - `npm run test:dataset-library`
  - `npm run test:regression`
  - `npm run test:persistence`
  - `npm run build:modeling`
  - `npm run build`
  - `npm run sync:atlas`
  - Clean copy: `npm run test:model-diagnostics`
  - Clean copy: `npm run build`

### Manual QA status

- Pending browser sign-in session:
  - Register TRAIN scored output.
  - Register TEST scored output.
  - Register OOT scored output.
  - Confirm `MedHouseVal` or the project target is detected as the actual column.
  - Confirm `predicted_value` is detected as the prediction column.
  - Confirm Actual vs Predicted, Residual Diagnostics, and Prediction Distribution render.
  - Confirm Lift / Decile and Calibration show classification-only guidance for regression scored outputs.

### Known limitations

- Full scored-output artifact registration remains future work. Current registration uses scored preview rows from the scoring response.
- Model Diagnostics operates on Dataset Library sample/preview rows, not warehouse-scale full scored tables.
- Browser manual QA was not completed in this run because direct workflow and diagnostics routes require a signed-in ATLAS session.

## Phase 10D Diagnostic Expansion and Regression Mapping Fix

### Regression field mapping correction

- Diagnostics now explicitly blocks prediction-like fields from being inferred as the actual target.
- Blocked actual aliases include `predicted_value`, `prediction`, `score`, `probability`, `p_hat`, `pred`, `y_pred`, and `fitted_value`.
- Actual mapping now prefers explicit metadata such as `targetColumn`, `target`, and `actualColumn` before inference.
- Diagnostics now returns a `diagnosticMode` value: `classification`, `regression`, `prediction_only`, or `unmapped`.
- Diagnostics now returns `mappingWarnings` when actual/prediction fields are missing or mapped to the same column.

### Added model diagnostic outputs

- Predicted Value Summary
- Actual Distribution
- Top 10 Highest Predictions
- Bottom 10 Lowest Predictions
- Largest Absolute Errors
- Top Overpredictions
- Top Underpredictions
- Prediction Band Summary
- Regression Fit Summary
- TRAIN/TEST/OOT Scored Split Comparison

### Segment diagnostics

- Segment diagnostics now supports explicit segment override.
- Numeric segment fields with many distinct values are binned into quantiles before segment-level metrics are calculated.
- Segment output now reports mean prediction and, when actual values exist, mean actual, residual, absolute residual, and RMSE.

### Generated code updates

- Python, SQL, R, and SAS-compatible generated code now includes:
  - prediction summaries
  - top/bottom prediction ranking
  - largest residual errors
  - prediction-band summaries
- SAS-compatible output now includes `proc means`, `proc sort`, `proc print`, and `proc rank`.

### Export updates

Excel diagnostics export now includes separate sheets for:

- Field Mapping
- Prediction Summary
- Top 10 Highest Predictions
- Bottom 10 Lowest Predictions
- Largest Absolute Errors
- Top Overpredictions
- Top Underpredictions
- Prediction Band Summary
- Regression Fit Summary
- Segment Performance
- Split Comparison
- Lift Decile
- Calibration
- Generated Code
- Metadata
- Governance Notes

### Tests run

- Passed:
  - `python -m py_compile server\model_diagnostics\diagnostics_store.py server\model_diagnostics\diagnostics_router.py server\scoring\scoring_router.py`
  - `npx tsc -b`
  - `npm run test:model-diagnostics`
  - `npm run test:chart-studio`
  - `npm run test:analytics-workbench`
  - `npm run test:dataset-library`
  - `npm run test:regression`
  - `npm run test:persistence`
  - `npm run build:modeling`
  - `npm run build`
  - `npm run sync:atlas`
  - Clean copy: `npm run test:model-diagnostics`
  - Clean copy: `npm run build`

### Clean-copy sync

- Source folder: `C:\Users\james\ds-workflow-starter`
- Clean copy: `C:\Users\james\Projects\ATLAS\atlas-app`
- Sync command: `npm run sync:atlas`
- Runtime artifacts remain intentionally excluded from sync.

### Manual QA status

- Browser QA remains dependent on a signed-in ATLAS session and locally registered TRAIN/TEST/OOT scored-output datasets.

## Phase 10E Model Diagnostics Deepening, VIF, and Pozzolo Detail

### Actual target and diagnostic mode hardening

- Scored registration now blocks prediction-like columns from being inferred as actual target fields.
- Diagnostics continues to prefer explicit `targetColumn`, `actualColumn`, and stored column role metadata before fallback inference.
- Regression scored outputs now show regression diagnostics first and suppress classification-only lift/calibration visuals behind a clear explanatory note.
- The Model Diagnostics page now includes a `Refresh Diagnostics Fields` action that re-runs scored-row field mapping, residual calculations, and diagnostic mode detection.

### New diagnostic outputs

- Classification Summary Metrics:
  - AUC
  - Gini
  - KS
  - base event rate
  - events / non-events
- Detailed Classification Lift Table:
  - Decile
  - # of accounts
  - % of all accounts
  - Min score
  - Max score
  - Avg score
  - Expected # of events
  - Actual event rate
  - Actual # of events
  - Cumulative % of all accounts
  - Cumulative % of events
  - Cumulative % of non-events
  - Lift
- Population Waterfall:
  - Full Developmental Dataset
  - Balance the Data
  - Information Value Filter
  - Correlation Analysis Filter
  - Recursive Feature Elimination
  - Final Model Features
- VIF / Multicollinearity Analysis:
  - Formula shown as `VIF_j = 1 / (1 - R_j^2)`
  - Tolerance shown as `1 / VIF`
  - Status and recommendation per variable
- Pozzolo Prior Correction:
  - Equation shown as `alpha = [pi / (1 - pi)] / [pi_s / (1 - pi_s)]; p_corrected = (alpha * p_s) / (1 - p_s + alpha * p_s)`
  - Clearly marked as classification-only and not applicable to regression outputs.
- KPI Aggregation:
  - Regression and classification KPI rollups with RYG status and governance recommendation text.

### Export updates

Excel diagnostics export now includes additional sheets for:

- Classification Metrics
- Detailed Lift Table
- Population Waterfall
- VIF Analysis
- Pozzolo Calibration
- KPI Aggregation

Word and PowerPoint exports now summarize:

- prediction / fit metrics
- classification metrics
- detailed lift availability
- population waterfall
- VIF formula and rows reviewed
- Pozzolo calibration equation
- KPI governance recommendation

### Generated code updates

Python, SQL, R, and SAS-compatible generated diagnostics code now includes reproducibility guidance for:

- detailed classification lift table
- decile ranking
- VIF formula
- Pozzolo prior correction equation

### Tests run

- Passed:
  - `python -m py_compile server\model_diagnostics\diagnostics_store.py server\model_diagnostics\diagnostics_router.py server\scoring\scoring_router.py`
  - `npx tsc -b`
  - `npm run test:model-diagnostics`
  - `npm run test:chart-studio`
  - `npm run test:analytics-workbench`
  - `npm run test:dataset-library`
  - `npm run test:regression`
  - `npm run test:persistence`
  - `npm run build:modeling`
  - `npm run build`
  - `npm run sync:atlas`
  - Clean copy: `npm run test:model-diagnostics`
  - Clean copy: `npm run build`

### Clean-copy sync

- Source folder: `C:\Users\james\ds-workflow-starter`
- Clean copy: `C:\Users\james\Projects\ATLAS\atlas-app`
- Sync command: `npm run sync:atlas`
- Runtime artifacts under `server/artifacts` remain intentionally excluded from sync.

### Manual QA status

- Browser QA was not completed in this run because the scored-output diagnostics path requires a signed-in ATLAS session and locally registered TRAIN/TEST/OOT scored outputs.
- Recommended manual QA:
  - Register TEST and OOT scored outputs from a regression model where the target is present.
  - Confirm Model Diagnostics mode is `Regression`.
  - Confirm Actual Distribution, Actual vs Predicted, Residual Diagnostics, VIF, KPI Aggregation, and Population Waterfall render.
  - Confirm classification lift/calibration panels are suppressed for regression and shown for binary classification scored outputs.
  - Export Excel and confirm the new sheets are present.

### Known limitations

- Diagnostics still operate on Dataset Library scored-output sample/preview artifacts until full warehouse-scale scored output persistence is implemented.
- Population waterfall currently uses available scored-output metadata and governance placeholders where source-stage row counts are not yet available.
- KPI thresholds are deterministic defaults and should become configurable in a future monitoring-governance phase.
- Pozzolo correction requires known original and sampled event rates; when these are unavailable ATLAS reports the equation and available inferred rates instead of fabricating corrected probabilities.

## Phase 10F Full Scored Dataset Registration

### Full original-row preservation

ATLAS scoring now constructs a full scored-output row set in the backend response instead of forcing the frontend to register only preview prediction rows.

For each scored row, ATLAS preserves:

- original input feature columns
- original target column when present
- `actual` alias when target is present
- `predicted_value`
- `prediction`
- regression residual fields:
  - `atlas_residual`
  - `atlas_abs_residual`
  - `atlas_squared_residual`
  - `atlas_percent_error`
- `split`

The scoring response now includes:

- `scored_rows`
- `scored_columns`
- `scored_row_scope: full_scored_output`

The visible scoring preview remains small for browser usability, but the governed Dataset Library registration consumes `scored_rows` first.

### TRAIN / TEST / OOT full scored output

The Scoring page now registers TRAIN, TEST, and OOT scored outputs using the same full-row registration path. Registration metadata records `rowScope`, scored columns, column roles, target, prediction, residual fields, split, metrics, and stability information.

### Scored dataset rebuild / repair

Dataset Detail and Model Diagnostics now expose a `Re-register Full Scored Dataset` action.

Current repair behavior is intentionally conservative:

> ATLAS cannot rebuild this scored dataset because the original scoring input rows are not available. Re-run scoring and register the full scored output.

This avoids pretending legacy prediction-only datasets can be reconstructed when the original scoring input rows were never persisted.

### Dataset Detail scored-output completeness

Dataset Detail now includes a `Scored Output Completeness` panel for scored-output datasets.

Checks include:

- Feature columns present
- Target column present
- Prediction column present
- Residual fields present
- Rows reviewed
- Columns reviewed
- Diagnostic readiness

Readiness statuses include:

- Ready for regression diagnostics
- Prediction-only, actual target missing
- Prediction-only, original features missing
- Ready for classification diagnostics
- Needs field mapping

### Regression diagnostics population

Full scored-output registration provides Model Diagnostics with the columns needed for:

- Mode = Regression
- Actual column = target or `actual`
- Prediction column = `predicted_value`
- Regression Fit Summary
- Actual vs Predicted
- Residual Diagnostics
- Largest Absolute Errors
- Top Overpredictions
- Top Underpredictions
- Prediction Band Summary
- Segment Performance
- Scored Split Comparison

Classification-only diagnostics remain available for binary classification outputs and are no longer primary empty panels for regression outputs.

### VIF workflow placement

VIF is now visible in the main modeling workflow on Feature Engineering.

The card shows:

- formula: `VIF_j = 1 / (1 - R_j^2)`
- Variable
- VIF
- Tolerance
- R-squared against other predictors
- Status
- Recommendation

Thresholds:

- `VIF < 5`: Low concern
- `5 <= VIF < 10`: Moderate concern
- `VIF >= 10`: High concern

### Pozzolo workflow placement

Pozzolo prior correction is now visible in the classification scoring context.

The Scoring page shows:

- `alpha = [pi / (1 - pi)] / [pi_s / (1 - pi_s)]`
- `p_corrected = (alpha * p_s) / (1 - p_s + alpha * p_s)`
- expanded corrected probability equation
- sample training event rate `pi_s`
- target population event rate `pi`
- correction factor `alpha`
- mean original probability
- mean corrected probability
- Brier before / after when actuals are present in the preview

Regression scoring clearly states:

> Pozzolo correction is classification-only and does not apply to regression predictions.

### Tests run

- Passed:
  - `python -m py_compile server\evaluation\eval_service.py server\scoring\scoring_router.py server\model_diagnostics\diagnostics_store.py server\model_diagnostics\diagnostics_router.py`
  - `npx tsc -b`
  - `npm run test:model-diagnostics`
  - `npm run test:chart-studio`
  - `npm run test:analytics-workbench`
  - `npm run test:dataset-library`
  - `npm run test:regression`
  - `npm run test:persistence`
  - `npm run build:modeling`
  - `npm run build`
  - `npm run sync:atlas`
  - Clean copy: `npm run test:model-diagnostics`
  - Clean copy: `npm run build`

### Manual QA status

Manual browser QA still needs a signed-in ATLAS session and newly re-registered TRAIN/TEST/OOT scored outputs. Recommended checks:

1. Re-run scoring for TRAIN.
2. Register TRAIN scored output.
3. Re-run/register TEST scored output.
4. Re-run/register OOT scored output.
5. Open Dataset Detail for TEST scored output.
6. Confirm original features, target, `actual`, `predicted_value`, residual fields, and `split` are present.
7. Open Model Diagnostics and confirm regression mode, fit summary, actual-vs-predicted, residual diagnostics, largest errors, segment performance, and split comparison populate.
8. Confirm VIF appears in Feature Engineering.
9. Confirm Pozzolo appears in classification scoring and is marked not applicable for regression.

### Clean-copy sync confirmation

- Source folder: `C:\Users\james\ds-workflow-starter`
- Clean copy: `C:\Users\james\Projects\ATLAS\atlas-app`
- Sync command: `npm run sync:atlas`
- Clean-copy verification passed:
  - `npm run test:model-diagnostics`
  - `npm run build`
- Runtime artifacts under `server/artifacts` remain intentionally excluded from sync.

### Known limitations

- Existing legacy prediction-only scored datasets cannot be rebuilt unless users re-run scoring and register the new full scored output.
- Full warehouse-scale scored-output persistence is still future work; this phase preserves full rows through the current scoring response and Dataset Library registration path.
- Browser payload size may be larger for very large scored outputs because full scored rows are returned for registration.

## Phase 10G Workflow Polish, VIF Fix, Training Layout, Evaluation Insights, and Export Repair

### VIF analysis repair

VIF now uses explicit predictor eligibility rules in both Feature Engineering and Model Diagnostics:

- excludes target, row IDs, split/fold flags, predictions, probabilities, scores, residuals, deciles, ranks, output fields, and diagnostics fields
- excludes non-numeric variables
- excludes constants
- excludes variables with too many missing values
- returns exact unavailability reasons: `Not enough rows`, `Constant variable`, `Too many missing values`, `Singular matrix`, `Non-numeric variable`, and `Diagnostic/output field`
- shows `VIF_j = 1 / (1 - R_j^2); Tolerance = 1 / VIF`

Model Diagnostics exports now include the VIF table and reason/status fields.

### Balance & Split K-fold visualization

The K-fold diagram now includes a clearer explanation that each row is one training run, the validation fold rotates, and training folds are the remaining blocks. The visualization also shows estimated rows per fold when local row counts are available.

### Model Training workflow polish

Visible training UX changes:

- `Max parallel models` renamed to `Max parallel model jobs`
- helper scale added:
  - 1 safest/slowest
  - 2 recommended for laptops
  - 4 faster but needs CPU/RAM
  - 6+ powerful workstations/servers
- PCA relabeled to `Apply PCA preprocessing` with guidance and default-no wording
- model cards now include:
  - Best for
  - Strengths
  - Cautions
  - Tuning status
- a dedicated `Train Selected Models` action section was added under selected algorithm cards
- results section is labeled `Training Results`
- Best Params fallback now distinguishes:
  - tuned parameter set
  - `Default parameters, not tuned.`
  - `No tunable parameters used.`
  - `Tuning failed: no best parameter set returned.`

### Evaluation interpretation cards

Regression evaluation readouts now include more actionable interpretation for:

- Actual vs Predicted
- Residuals vs Predicted
- Q-Q Plot
- Residual Distribution
- Residual Diagnostics by Predicted Decile

The Q-Q Plot interpretation now explains why tail deviation matters and recommends next actions such as reviewing outlier segments, target transformations, nonlinear terms/interactions, robust regression, and OOT residual behavior.

### Model Diagnostics export repair

Export buttons now pass the current field mapping overrides to the backend export endpoint. This keeps Excel, Word, and PowerPoint exports aligned with the on-screen diagnostics.

Excel exports now include the added sheets:

- Actual Summary
- Actual vs Predicted
- Residual Diagnostics
- Segment Performance
- Split Comparison
- Generated Code
- Metadata
- Governance Notes

Existing export sheets remain, including Summary, Field Mapping, Prediction Summary, Top/Bottom Predictions, Largest Absolute Errors, Top Over/Underpredictions, Prediction Band Summary, Regression Fit Summary, Population Waterfall, VIF Analysis, Pozzolo Calibration, and KPI Aggregation.

### Tests run for 10G

- Passed:
  - `npm run test:model-diagnostics`
  - `npm run test:chart-studio`
  - `npm run test:analytics-workbench`
  - `npm run test:dataset-library`
  - `npm run test:regression`
  - `npm run test:persistence`
  - `npx tsc -b`
  - `npm run build:modeling`
  - `npm run build`
  - `npm run sync:atlas`
  - Clean copy: `npm run test:model-diagnostics`
  - Clean copy: `npm run build`

Build warnings observed:

- Vite chunk-size warning for the existing large main bundle.
- Browserslist / baseline-browser-mapping data age warnings.

These were warnings only; builds completed successfully.

### Clean-copy sync confirmation for 10G

- Source folder: `C:\Users\james\ds-workflow-starter`
- Clean copy: `C:\Users\james\Projects\ATLAS\atlas-app`
- Sync command: `npm run sync:atlas`
- Runtime artifacts under `server/artifacts` intentionally excluded.
- Clean-copy Model Diagnostics tests passed.
- Clean-copy build passed.
