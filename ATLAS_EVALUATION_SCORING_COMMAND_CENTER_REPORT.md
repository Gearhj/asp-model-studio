# ATLAS Evaluation and Scoring Command Center Report

## Executive Summary

This focused build redesigns Predictive Modeling Evaluation, the Evaluation-to-Interpretation review handoff, and Predictive Modeling Scoring. It preserves the repaired fitted-artifact pipeline and replaces the prior generic report experience with analytical command centers built from persisted model outputs.

Evaluation now answers four explicit questions: which candidates performed best, why they performed best, what operating tradeoffs exist, and which candidates deserve deeper interpretation. Scoring now separates development TRAIN diagnostics, independent in-time TEST evidence, out-of-time OOT evidence, cross-dataset performance, stability, and output registration.

No candidate is automatically approved or labeled Champion. Rankings remain provisional until interpretation, operating-policy review, independent validation, and governance review are complete.

## Evaluation Changes

### Command Center Structure

Evaluation now follows the required A-H sequence:

1. ATLAS Performance Summary
2. Top Candidate Comparison
3. Interactive Model Explorer
4. Threshold and Operating Policy
5. Dataset Performance
6. Stability and Calibration
7. Full Leaderboard
8. Interpretation Comparison Tray

The top summary uses actual training and holdout artifacts. It identifies the current governing-metric leader, TEST and OOT availability, strongest evidence, unresolved risks, and the next review action without implying final approval.

### Removed Checkbox Behavior

The `Select for Interpretation` checkbox column was removed. Candidate review now uses deliberate actions:

- Review Model
- Add to Comparison / Remove from Comparison
- Open Interpretation
- Compare Selected Models
- Clear Comparison

### Candidate Comparison

The top three supervised candidates render as prominent comparison cards with family, PR-AUC, ROC-AUC, recall, precision, KS, F1, runtime, calibration, interpretability, TEST status, and OOT status.

A project-scoped comparison tray persists two to four candidates in browser state. Browser QA confirmed:

- Logistic Regression and KNN remained in the tray after navigating to Interpretation and returning.
- `Compare Selected Models` opened `/step09?model=logreg&compare=logreg%2Cknn`.
- Direct Decision Tree review opened `/step09?model=dtree&compare=logreg%2Cknn%2Cdtree`.

### Interactive and Model-Specific Diagnostics

Changing the model under review updates common fitted-artifact diagnostics:

- ROC and precision-recall curves
- active confusion matrix
- lift, gain, capture, and decile evidence
- calibration and Brier evidence
- internal validation, TEST, and OOT status

Model-family panels are artifact-aware:

- Logistic Regression: coefficients, direction, magnitude, odds-ratio context, intercept, and regularization.
- Decision Tree: rendered tree, node and leaf counts, depth, branch rules, event rates, and complexity settings.
- KNN: decision-region and neighborhood visualization plus selected-neighbor and distance context.
- Extra Trees and tree ensembles: fitted native feature importance and estimator settings.
- Other supported families: family-specific diagnostics when the fitted object exposes them.
- Unsupported diagnostics: explicit unavailable state with the reason; no fabricated output.
- Anomaly algorithms: separate Supplemental Anomaly Diagnostics and no champion eligibility.

The browser fixture rendered a real Decision Tree with 19 nodes, 10 leaves, and displayed depth 4. KNN exposed a dedicated neighborhood decision-region visualization. Extra Trees exposed fitted native feature importance.

### Threshold Explorer

The threshold section includes:

- slider and operating-policy presets
- review-capacity input
- predicted positives and review volume
- precision, recall, F1, false-positive rate
- false positives, false negatives, fraud capture, and expected alert rate
- an active-threshold confusion matrix
- `Save as Proposed Operating Policy`, which records a proposal without approving it

Browser QA selected `Maximize F1`. The active threshold changed from 0.500 to 0.824 and recomputed the matrix and metrics:

- precision: 36.0%
- recall: 86.1%
- F1: 0.5082
- false-positive rate: 0.3%
- predicted positives / review volume: 172
- false positives: 110
- false negatives: 10

### Calibration, Dataset Roles, and Interpretation

Calibration is a distinct analytical region with reliability evidence, predicted versus observed rates, Brier score, method, slope/intercept where available, and prevalence-correction status.

Internal validation, TEST, and OOT remain different evidence roles. Missing TEST or OOT artifacts display explicit not-loaded states rather than simulated results. Interpretation continues to provide model-specific explanation, feature importance, SHAP, PDP, sensitivity, RFE, full-versus-reduced comparison, and final-model saving.

## Scoring Changes

### Command Center Structure

Scoring now follows the required A-H sequence:

1. Governed Final-Model Scoring Contract
2. TRAIN Scoring - Development Diagnostics
3. TEST Scoring - Independent In-Time Evaluation
4. OOT Scoring - Out-of-Time Stability Evaluation
5. Cross-Dataset Performance
6. Stability Command Center
7. Scored Output Registration
8. Developer Tools and Reproducibility

### Governed Contract

The read-only contract exposes the actual saved artifact identity:

- final model and version
- fitted estimator / model family
- retained feature count and manifest
- feature-selection method
- preprocessing and calibration
- proposed threshold policy
- modeled and natural event rates when available
- source candidate, dataset version, and artifact hash

Directly saved fitted candidates now preserve estimator-class metadata. The browser contract correctly rendered `Logistic Regression pipeline` instead of an unavailable estimator.

### TRAIN, TEST, and OOT Separation

The three scoring roles use distinct layouts, accents, language, and controls.

- TRAIN is explicitly labeled development diagnostics and not independent evidence.
- TEST requires an external in-time validation dataset and preserves dataset identity/version.
- OOT requires a later-period dataset and preserves the evaluation period separately from TEST.

Browser QA scored the governed TRAIN split with the saved final Logistic Regression artifact. It returned 1,440 scored rows and a full preview. TEST and OOT correctly remained gated because no compatible external files were loaded during the browser session.

### Cross-Dataset Performance

The comparison table presents TRAIN, TEST, OOT, TEST change, and OOT change for:

- ROC-AUC and PR-AUC
- accuracy, explicitly de-emphasized as context only
- precision, recall, and F1
- KS
- top-decile lift and capture
- Brier score
- mean score and event rate

The live TRAIN diagnostic fixture returned ROC-AUC 0.9878, PR-AUC 0.9767, KS 0.9141, top-decile lift 5.0000, and Brier score 0.0191. Empty TEST/OOT cells were represented as unavailable, not zero.

### Prediction PSI and Variable Stability Index

PSI and VSI are no longer buried in OOT. The dedicated Stability Command Center provides:

- Prediction PSI for TRAIN-to-TEST and TRAIN-to-OOT
- Variable Stability Index for feature-level shifts
- governed pass/warning/fail thresholds
- score-distribution comparisons
- top unstable variables and drill-down data
- save-as-evidence and add-to-monitoring-plan actions

When TEST or OOT has not been scored, stability remains explicitly pending. Backend tests exercise actual TEST/OOT scoring, Prediction PSI, feature VSI, and registration payloads.

### Registration and Links

TRAIN, TEST, and OOT outputs retain independent registration states. Full scored rows, diagnostic columns, final-model metadata, prediction fields, target fields, residuals where applicable, and stability metadata remain available to Dataset Library. Model Diagnostics and Chart Studio links are preserved.

## Files Modified

- `package.json`
- `server/evaluation/eval_router.py`
- `server/evaluation/eval_service.py`
- `src/lib/interpretationCandidates.ts`
- `src/steps/Step08_Evaluation.tsx`
- `src/steps/Step09_Interpretation.tsx`
- `src/steps/Step10_Scoring.tsx`
- `tests/evaluationScoringCommandCenter.test.mjs`
- `tests/evaluation_scoring_command_center_test.py`
- `tests/predictiveGoldStandardWorkflow.test.mjs`
- `ATLAS_EVALUATION_SCORING_COMMAND_CENTER_REPORT.md`

No Project Context, Data Acquisition, EDA, Outliers, Missing Values, Feature Engineering, Balance & Split, or Model Training source was changed for this build.

## Automated Validation

All required commands passed:

| Command | Result |
| --- | --- |
| `npx tsc -b` | Passed |
| `npm run build` | Passed |
| `npm run test:evaluation-scoring-command-center` | Passed |
| `npm run test:predictive-gold-standard-workflow` | Passed |
| `npm run test:model-documentation` | Passed |
| `npm run test:evidence-graph` | Passed |
| `npm run test:monitoring-center` | Passed |
| `npm run test:registry-dashboard` | Passed |
| `npm run test:sqlite-persistence` | Passed, including 15 Python backend tests |
| `npm run test:regression` | Passed, 18/18 |

The focused suite verifies the removed checkbox, model-review actions, persistent comparison set, selected-model navigation, top-three real candidates, model-dependent common diagnostics, Decision Tree/KNN/linear diagnostics, anomaly separation, threshold-dependent metrics and matrix, calibration, distinct TEST/OOT roles, final-artifact scoring contract, TRAIN/TEST/OOT zones, cross-dataset comparison, Prediction PSI, VSI, registration, links, Interpretation/RFE continuity, and final-model continuity.

## Manual Browser QA

QA was performed in the running ATLAS application at `http://127.0.0.1:5174/` with the backend at `http://127.0.0.1:8001/`.

The browser fixture used a real 170,884-row credit-card dataset, a governed 20% holdout, a 1,440-row balanced training split, and fitted Logistic Regression, Decision Tree, KNN, and Extra Trees artifacts. Confirmed behavior:

- no `Select for Interpretation` checkbox
- prominent top-three candidate cards
- artifact-backed linear, tree, KNN, and ensemble diagnostics
- rendered Decision Tree visualization
- KNN neighborhood visualization
- calibration and separate TEST/OOT roles
- live threshold recalculation and matching confusion matrix
- persistent comparison tray and exact Interpretation routing
- read-only final-model scoring contract
- visually distinct TRAIN, TEST, and OOT regions
- real TRAIN scoring
- cross-dataset comparison
- dedicated Prediction PSI / Variable Stability Index region
- registration, evidence, monitoring, Dataset Library, Model Diagnostics, and Chart Studio affordances

## Screenshots Reviewed

- `artifacts/qa/evaluation-scoring/evaluation-command-center-top.png`
- `artifacts/qa/evaluation-scoring/evaluation-decision-tree.png`
- `artifacts/qa/evaluation-scoring/evaluation-threshold-live.png`
- `artifacts/qa/evaluation-scoring/scoring-command-center-top.png`
- `artifacts/qa/evaluation-scoring/scoring-cross-dataset-and-stability.png`

## Known Limitations

- TEST and OOT scoring require user-supplied datasets matching the final feature schema. The manual browser run intentionally did not fabricate those files; the UI showed correct gated states, while backend tests verified real TEST/OOT metrics, PSI, VSI, and registration contracts.
- Diagnostics such as OOB score, training loss history, support-vector detail, or model-native SHAP are displayed only when the fitted estimator exposes the required artifact. Unsupported evidence is labeled unavailable with a reason.
- The build emits existing Vite chunk-size and stale Browserslist data warnings. They do not block compilation or runtime behavior and are outside this focused Evaluation/Scoring scope.

## Completion Confirmations

- No model is automatically approved or called Champion.
- Existing Interpretation, RFE, final-model saving, and fitted-artifact handoff are preserved.
- Existing Scoring registration and downstream links are preserved.
- `npm run sync:atlas` completed after this report and the passing validation suite.
