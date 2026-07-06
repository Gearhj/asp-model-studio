# Predictive Workflow QA Fix Report

## Summary

This pass focused on regression/classification separation across the Predictive Modeling workflow. ATLAS now uses a shared problem-type utility and removes the most visible classification artifacts from regression project paths.

## Root Cause

Regression support existed in several pages, but problem-type logic was duplicated locally. Some pages still used classification defaults such as IV, event rate, fraud/non-fraud labels, balancing methods, TEST/OOT terminology, mixed model metrics, and confusion/ROC report sections even when the target was continuous.

## Files Changed

- `src/lib/problemType.ts`
- `src/lib/projectContext.ts`
- `src/lib/modelDevelopmentDocument.ts`
- `src/lib/governanceReport.ts`
- `src/steps/Step00_ProjectContext.tsx`
- `src/steps/Step01_DataAcquisition.tsx`
- `src/steps/Step04_Outliers.tsx`
- `src/steps/Step06_BalancingSplit.tsx`
- `src/steps/Step06_Train.tsx`
- `src/steps/Step10_Scoring.tsx`
- `tests/regression.test.mjs`

## Implemented Fixes

- Added centralized problem-type helpers:
  - `getProblemType`
  - `getTargetType`
  - `isRegressionProject`
  - `isClassificationProject`
  - `isBinaryClassificationProject`
  - `getMetricSetForProblemType`
- Updated Project Context:
  - Regression success metrics are regression-only.
  - False Positive / False Negative labels become Overprediction / Underprediction for regression.
- Updated Data Acquisition:
  - Regression variable summary uses `Corr(Target)` instead of IV.
  - Regression target summary shows mean, median, standard deviation, min, and max instead of event rate.
- Updated Outliers:
  - Regression uses target correlation as the feature signal.
  - Regression guidance no longer uses fraud/anomaly-only language.
- Updated Balance & Split:
  - Regression branch hides balancing, SMOTE, class weights, and event-rate controls.
  - Regression branch shows split validation diagnostics and regression metric guidance.
- Updated Model Training:
  - Probability calibration control is hidden for regression.
  - Evaluation CTA is centered, blue, and labeled `Mark Complete & Go to Evaluation`.
- Updated Scoring:
  - Renamed Holdout TEST to External Validation Dataset.
  - Renamed OOT to Out-of-Time Dataset.
  - Regression PSI language uses prediction distribution wording.
- Updated Model Development Document and Governance Report:
  - Candidate model tables are problem-type specific.
  - Regression reports exclude AUC, PR-AUC, KS, lift, ROC/PR, and confusion matrix sections from the main regression summary.
  - Regression reports include regression metrics and note that balancing is not applicable.

## Tests Run

- `npm run test:persistence` - passed
- `npm run test:regression` - passed
- `npm run test:workflow-navigation-state` - passed
- `npm run test:data-acquisition` - passed
- `npm run test:experimental-design` - passed
- `npm run build:modeling` - passed
- `npm run build` - passed

## Manual QA Notes

Manual browser smoke testing was not run in this pass. The source-level regression tests and TypeScript/Vite builds verified that the patched paths compile and that the expected regression-safe UI/report strings are present.

## Known Limitations

- EDA and Interpretation still have deeper UX opportunities for regression-specific visual storytelling, but core metric/report leakage was addressed.
- Model Monitoring sample data can still contain canned classification examples when no project-specific production models exist.
- Governance Report and Model Development Document are now filtered by problem type, but historical browser storage can still contain old experiment records; filtered tables prevent those records from appearing in the current problem-family report.
