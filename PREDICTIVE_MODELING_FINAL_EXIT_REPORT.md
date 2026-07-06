# Predictive Modeling Final Exit Report

Generated: 2026-07-06

## Scope

This hotfix was limited to:

1. Linear Regression statistical output on the Interpretation page.
2. Model Development Document summarization so default reports no longer dump every workflow event.

## Linear Regression Inference Implementation

- Added fitted-pipeline Linear Regression inference in `server/evaluation/eval_service.py`.
- Uses the transformed training design matrix from the fitted sklearn pipeline.
- Computes and returns:
  - intercept
  - feature coefficients
  - standardized coefficients / weights (`standardized_weight`)
  - standard errors
  - t-statistics
  - p-values
  - 95% confidence intervals (`confidence_interval_lower`, `confidence_interval_upper`)
  - coefficient direction
  - absolute rank
  - R-squared
  - adjusted R-squared
  - RMSE
  - MAE
  - MSE
  - observation count
  - predictor count
  - residual degrees of freedom
  - residual standard error
  - F-statistic and Prob(F-statistic), when available
  - AIC, BIC, and log-likelihood, when available
  - condition number, when available
- Updated `src/steps/Step09_Interpretation.tsx` to show:
  - `Linear Regression Statistical Output`
  - Regression Equation
  - expandable full fitted equation
  - Model Fit Summary
  - Coefficient Inference Table with `p Value`, `Std Error`, `t Value`, confidence intervals, standardized weight, direction, and rank
  - Diagnostic Notes with plain-English interpretation guidance

## P-Value Availability

P-values and confidence intervals are available when:

- the fitted model is a Linear Regression pipeline,
- the transformed design matrix is available,
- residual degrees of freedom are positive,
- the design matrix is full-rank,
- SciPy is available for Student-t distribution calculations.

If inference cannot be computed, ATLAS now returns specific reasons, including:

- `Statistical inference unavailable because the transformed design matrix is singular.`
- `Statistical inference unavailable because SciPy is unavailable.`
- `Statistical inference unavailable because residual degrees of freedom are invalid.`
- `Statistical inference unavailable because training data is unavailable.`

Coefficients and standardized weights still display when available.

## Root Cause Found

The Linear Regression backend inference existed, but the display path was not reliably reaching it.

Root causes fixed:

- Model artifacts were keyed only by model key, such as `linreg`, without project, dataset, target, or problem-type scope.
- Step 9 requested `/interpretation/details?model=linreg` without enough context to distinguish a fresh Linear Regression artifact from a stale artifact created under another project or target.
- The Evaluation page selection was not persisted into Interpretation, so Step 9 could default to a different top-ranked model.
- The Step 9 renderer fell through to the generic classifier-style equation display when a response omitted `model_type`, causing `logit(p)` output to appear for Linear Regression.

Fixes implemented:

- Added scoped artifact metadata in `server/core/result_store.py`.
- Cleared stale model artifacts whenever dataset, target, or selected data changes.
- Passed project ID, dataset version, target, and problem type through model training and interpretation endpoints.
- Added stale-artifact rejection with debug metadata to interpretation responses.
- Persisted the Evaluation selected model for Step 9.
- Added a Linear Regression rendering fallback based on the selected model row so Linear Regression does not render through the classifier equation component.
- Added a Step 9 diagnostic `apiBase` query override for local browser verification without changing normal workflow routing.

## Browser Confirmation

The local app and backend were started successfully:

- `http://127.0.0.1:8001/api/health` returned `{"ok":true,"status":"running"}`
- `http://127.0.0.1:5174/dashboard` returned HTTP 200

A stale orphaned listener remained on port 8001 and returned the old lightweight equation payload. A clean corrected backend was started on port 8002 for browser verification.

Browser-confirmed on:

`http://127.0.0.1:5174/step09?apiBase=http%3A%2F%2F127.0.0.1%3A8002%2Fapi`

The browser rendered:

- `Linear Regression Statistical Output`
- `Regression Equation`
- `Model Fit Summary`
- `Coefficient Inference Table`
- `Std Error`
- `t Value`
- `p Value`
- `95% CI Lower`
- `95% CI Upper`
- `Inference available`

The rendered coefficient table showed p-values and confidence intervals for `MedInc`, `HouseAge`, and `AveRooms`.

## Model Document Event Summarization Changes

- Executive Summary mode no longer includes decision-journal timeline sections.
- Governance mode now includes a concise material-decision table instead of the full raw event history.
- The default material summary table uses:
  - Decision Area
  - Final Decision
  - Evidence
  - Owner / Source
  - Timestamp
- Technical Appendix mode includes the full audit trail only when the user explicitly selects:
  - `Include Full Decision Journal Appendix`
- Decision events are deduplicated by workflow step, action type, and subject.
- Default report output excludes:
  - repeated save events,
  - page visits,
  - toggle testing,
  - Python smoke test activity,
  - non-predictive Experimental Design workflow events.
- The report remains focused on the current project, current target, current problem type, and current champion/final model evidence.

## Tests Run

- `npm run test:regression` - passed
- `npm run build` - passed

Build completed with existing Vite warnings about chunk size and stale browser baseline data.

## Clean-Copy Sync Confirmation

Completed final sync after this diagnostic patch to:

`C:\Users\james\Projects\ATLAS\atlas-app`

Files synced:

- `server/evaluation/eval_service.py`
- `server/evaluation/eval_router.py`
- `server/training/trainer_service.py`
- `server/training/trainer_router.py`
- `server/core/result_store.py`
- `server/core/metadata_router.py`
- `src/lib/localDataset.ts`
- `src/steps/Step06_Train.tsx`
- `src/steps/Step08_Evaluation.tsx`
- `src/steps/Step09_Interpretation.tsx`
- `tests/regression.test.mjs`
- `PREDICTIVE_MODELING_FINAL_EXIT_REPORT.md`

Clean-copy verification:

- `npm run build` in `C:\Users\james\Projects\ATLAS\atlas-app` - passed

The clean-copy build completed with the same existing Vite warnings about bundle size and stale browser baseline data.

## Remaining Known Limitations

- Linear Regression inference is OLS-style post-fit inference on the transformed pipeline matrix. It is appropriate for standard linear regression review, but interpretation depends on preprocessing and transformed feature names.
- P-values are unavailable if the transformed matrix is singular, residual degrees of freedom are invalid, training data is unavailable, or SciPy is unavailable.
- Full decision-journal audit history remains available only in Technical Appendix mode with the explicit full-audit checkbox enabled.
- Port 8001 had orphaned stale listeners during verification. The corrected implementation was verified through a clean backend on port 8002 and normal frontend route with the Step 9 `apiBase` diagnostic override.
