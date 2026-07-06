# ATLAS Analytical Visualization Polish Report

## Summary

This pass upgrades the predictive modeling workflow charts from decorative mini-graphs toward professional analytical diagnostics. The work focuses on improving charts that already existed rather than adding disconnected containers.

## Pages Changed

- EDA
- Outliers
- Balance & Split
- Feature Engineering
- Model Training
- Evaluation
- Scoring
- Interpretation

## Chart Improvements Made

### EDA

- Improved the `Target Distribution` chart:
  - visible x-axis target values
  - visible y-axis record counts
  - gridlines
  - mean reference line
  - median reference line
  - Q1 and Q3 quartile markers
  - axis labels
  - explanatory readout for skewness, kurtosis, and tail behavior
- Improved `Top Features by Corr(Target)`:
  - ranked horizontal bars
  - signed correlation values
  - positive/negative color distinction
  - weak/moderate/strong strength labels

### Outliers

- Enlarged selected-feature histograms.
- Added visible x-axis value ticks and y-axis count ticks.
- Added low/high cap threshold lines and labels.
- Kept before/after distributions on comparable axes.
- Expanded percentile summary to P1, P5, P25, P50, P75, P95, and P99.
- Added an ATLAS readout explaining how capping changes the distribution and why conservative capping is recommended.

### Balance & Split

- Improved regression target distribution comparison:
  - comparable train/holdout axes
  - visible target-value ticks
  - visible record-count ticks
  - train mean reference line
  - holdout mean reference line
  - chart readout explaining split alignment risk
- Existing key feature alignment table remains in place with standardized differences and pass/review/fail status.

### Evaluation

- Improved regression diagnostics:
  - Actual vs Predicted chart now has numeric ticks and a labeled 45-degree identity line.
  - Residuals vs Predicted chart now has numeric ticks and a labeled zero-residual line.
  - Q-Q plot now has theoretical/residual quantile ticks and interpretation text.
  - Residual Distribution now has count ticks, residual ticks, and a zero marker.
  - Added compact chart explanations covering what each chart shows, what good looks like, and what ATLAS sees.
- Existing residual decile table remains as the detailed diagnostic table.

### Scoring

- Improved regression prediction distribution charts:
  - visible x-axis predicted values
  - visible y-axis record counts
  - mean prediction line
  - axis labels
  - ATLAS readout for underfit/schema-risk patterns
- Improved VSI drift visualization:
  - pass/warning/fail threshold markers
  - values shown on bars
  - plain-language readout describing failed drift variables
- Added metric comparison mini-bars for RMSE, MAE, and R-squared across External Validation and OOT where available.

### Feature Engineering

- Added a top `Feature Engineering Summary` section:
  - polynomial feature count
  - interaction feature count
  - binned feature count
  - rule-based feature count
  - scaler selection
  - target-excluded status
- Added a structured `Created Features` table:
  - created feature name
  - type
  - formula/rule
  - source variables
  - target leakage check

### Model Training

- Added a visible `Training Readiness` panel:
  - dataset status
  - target
  - feature count
  - selected model count
  - optimization metric
  - grid search status
- Existing validation setup, execution settings, advanced search, and training queue sections remain grouped.

### Interpretation

- Added a regression-first interpretation focus section:
  - Top Drivers
  - Direction
  - Nonlinear Effects
  - Reduced Set
- Reinforced that projected response surfaces are advanced diagnostics for regression and that SHAP/PDP/RFE should be reviewed first.

## Verification

### Tests Run

- `npm run build:modeling` passed.
- `npm run test:regression` passed.
- `npm run test:data-acquisition` passed.

### Local Health Checks

- Frontend `http://127.0.0.1:5174/dashboard` returned `200`.
- Backend `http://127.0.0.1:8001/api/health` returned `{"ok":true,"status":"running"}`.

## Manual QA Notes

Manual browser automation was not rerun with screenshots in this environment because the Playwright browser binary is not installed locally. The prior attempt failed with a missing Chromium executable. I did not download browsers during this pass.

I verified through build, tests, local health checks, and source-level checks that the requested visual sections and chart enhancements are present in the affected workflow pages.

## Remaining Visual Limitations

- Some charts are still hand-coded SVGs. They now include axes, ticks, reference lines, and readouts, but a future shared charting layer would improve consistency further.
- Scoring residual and actual-vs-predicted plots require uploaded scoring files that include the target variable. When only predictions are available, ATLAS can show prediction distribution, PSI/VSI, and metric summaries.
- Feature Engineering preview tables can still become horizontally wide for high-dimensional data. The new summary and created-feature list reduce reliance on the raw preview table, but virtualization would be a future improvement.
- Evaluation charts use available backend residual arrays. If a backend model does not return residual point data, ATLAS shows an explicit unavailable state.
