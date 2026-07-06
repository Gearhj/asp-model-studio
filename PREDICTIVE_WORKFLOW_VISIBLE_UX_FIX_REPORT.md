# Predictive Workflow Visible UX Fix Report

## Summary

This pass implements visible predictive-modeling workflow improvements across EDA, Outliers, Missing Values, Feature Engineering, Balance & Split, Model Training, Evaluation, Interpretation, Scoring, and Model Development Document generation.

The goal was to make the predictive workflow visibly reflect regression/classification context instead of only changing test utilities or hidden logic.

## Files Changed

- `src/steps/Step02_EDA.tsx`
- `src/steps/Step04_Outliers.tsx`
- `src/steps/Step04_MissingValues.tsx`
- `src/steps/Step05_EncodingScaling.tsx`
- `src/steps/Step06_BalancingSplit.tsx`
- `src/steps/Step06_Train.tsx`
- `src/steps/Step08_Evaluation.tsx`
- `src/steps/Step09_Interpretation.tsx`
- `src/steps/Step10_Scoring.tsx`
- `src/lib/modelDevelopmentDocument.ts`

## Visible UX Changes

### EDA

- Added a `Target Variable Analysis` section near the top of EDA.
- Shows target name, problem type, row count, missing percentage, mean, median, standard deviation, min, max, skewness, and kurtosis.
- Added a target distribution histogram with mean and median guide lines.
- Added target percentile cards.
- Added top features by `Corr(Target)`.
- Added a geographic target-analysis prompt when `Latitude` and `Longitude` exist.
- EDA now hydrates target analysis from either browser-cached data or backend `/api/data/get_sample`.

### Outliers

- Reworked the page into a more focused outlier workbench.
- Added global method summary, total outlier count, features with outliers, max outlier rate, and highest-risk feature cards.
- Added a clickable main feature table.
- Added a selected-feature detail panel with before/after histogram preview, percentile summary, target relationship, selected treatment, and recommendation.
- Collapsed full histogram previews into an expandable section.

### Missing Values

- Added a strong green no-action-needed success state when no missing values are detected.
- The page now explicitly tells the user imputation can be skipped when there is nothing to treat.

### Feature Engineering

- Prevented the target variable from appearing in generated preview columns.
- Improved rule-based feature labels and helper text so the user understands the feature, condition, match value, output value, and default value.

### Balance & Split

- Added regression train-vs-holdout alignment visuals.
- Added train and holdout target summary cards.
- Added target distribution comparison.
- Added key feature alignment table with train mean, holdout mean, standardized difference, and status.
- Added a split quality readout.

### Model Training

- Added a clearer training configuration section:
  - Validation Setup
  - Execution Settings
  - Advanced Search
- Regression mode now displays regression-oriented optimization guidance instead of classification calibration language.

### Evaluation

- Expanded regression diagnostics:
  - RMSE, MAE, R-squared, adjusted R-squared, residual metrics
  - Model error comparison bars
  - Actual vs predicted
  - Residuals vs predicted
  - Q-Q plot
  - Residual distribution
  - Residual decile diagnostics
  - Bias and fit interpretation cards

### Scoring

- Added regression scoring visuals:
  - Prediction distribution preview
  - TEST vs OOT prediction distribution comparison
  - Top VSI drift table
  - Performance comparison table
- Relabeled regression stability as `Prediction PSI`.

### Interpretation

- Regression pages now prioritize feature importance, SHAP-style summary, PDP/sensitivity, and RFE.
- The projected prediction surface is demoted into an advanced expandable section for regression models.
- Classification response surfaces remain visible in the primary flow.

### Model Development Document

- Model documentation now filters experiments to the current project/dataset context before selecting final model content.
- Added project ID, dataset version, final model ID, and final training run ID to the report context.
- Reduced risk of stale classification/fraud/experimental entries appearing in regression model documentation.

## Verification

### Automated

- `npm run test:regression` passed.
- `npm run test:data-acquisition` passed.
- `npm run build:modeling` passed.
- `npm run build` passed.

### HTTP Smoke Checks

- Frontend health check: `http://127.0.0.1:5174/dashboard` returned `200`.
- Backend health check: `http://127.0.0.1:8001/api/health` returned `{"ok":true,"status":"running"}`.

### Source Presence Checks

Verified the visible section labels are present in source:

- `Target Variable Analysis`
- `Train vs Holdout Alignment`
- `No Action Needed`
- `Validation Setup`
- `Regression Fit & Residual Diagnostics`
- `Prediction Distribution Preview`
- `Advanced: Projected Prediction Surface`

## Manual Browser QA

Attempted headless Playwright page checks against the local app. The installed Playwright package could not launch because the Chromium headless binary is not installed in this environment:

`Executable doesn't exist at ... chromium_headless_shell...`

I did not download browsers because this pass was focused on local source changes and the environment has restricted network/dependency behavior. I replaced that with HTTP smoke checks, builds, regression tests, data-acquisition tests, and source-level presence checks.

## Known Limitations

- EDA target analysis requires either browser-cached data or a backend sample. The page now supports both, but it will still not show target analysis if no dataset is loaded.
- Scoring visuals use the currently available score summaries and preview predictions. Actual-vs-predicted and residual scoring visuals depend on uploaded scoring files containing the target column.
- Model Development Document filtering is based on current project/dataset identifiers and available experiment metadata. Older stale experiments with incomplete metadata may still require clearing or archival from the Decision Journal/Experiments pages.
