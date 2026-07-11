# CREDIT_RISK_STUDIO_PHASE_15_REPORT

## Phase 15A Credit Risk Studio Foundation

ATLAS now includes a Credit Risk Studio solution pack for regulated consumer-lending model development. The studio is a specialized workspace for credit-risk setup, target documentation, variable mapping, underwriting feature review, scorecard scaling, explainability, adverse-action evidence, decision strategy, portfolio monitoring, and evidence readiness.

## Files Added

- `src/steps/CreditRiskStudio.tsx`
- `src/lib/creditRiskStudio.ts`
- `server/credit_risk/__init__.py`
- `server/credit_risk/credit_risk_types.py`
- `server/credit_risk/credit_risk_store.py`
- `server/credit_risk/credit_risk_router.py`
- `tests/creditRiskStudio.test.mjs`
- `CREDIT_RISK_STUDIO_PHASE_15_REPORT.md`

## Files Updated

- `src/apps/ModelingApp.tsx`
- `src/components/Sidebar.tsx`
- `src/steps/ProjectOverview.tsx`
- `server/main.py`
- `package.json`

## Navigation and Routing

- Added `/credit-risk-studio`.
- Added Credit Risk Studio to the primary sidebar after Model Evidence Center.
- Added Credit Risk Studio to the full-width studio route list.

## Backend Endpoints

- `GET /api/credit-risk/profile`
- `POST /api/credit-risk/profile`
- `PUT /api/credit-risk/profile/{profile_id}`
- `GET /api/credit-risk/profile/project/{project_id}`
- `POST /api/credit-risk/readiness`
- `POST /api/credit-risk/evidence`
- `POST /api/credit-risk/export/excel`

Profiles are persisted under `server/artifacts/credit_risk`.

## Evidence Center Integration

Credit Risk Studio evidence capture creates Model Evidence Center records with:

- `financialDomain = credit_risk`
- `financialTechnique`
- `creditRiskContext`
- `supportsSections`
- credit-risk tags
- regulatory relevance for model risk, adverse action, and fair lending review where applicable

Evidence buttons are available for target definition, variable mapping, WOE/IV, manual binning, reject inference, VIF/correlation, PDO scaling, scorecard scaling, adverse action, fair lending, monotonic constraints, surrogate scorecard evidence, cutoff optimization, risk-based pricing, strategy trees, TTC/PIT, PSI, challenger/champion, and monitoring thresholds.

## Project Overview Integration

Project Overview now displays a Credit Risk Profile card when a profile exists for the active project. The card shows product type, model purpose, target event, target window, TTC/PIT assumption, readiness score, and links to Credit Risk Studio and Model Evidence Center.

## Scorecard Scaling

Credit Risk Studio includes a PDO scaling preview:

- `Factor = PDO / ln(2)`
- `Offset = BaseScore - Factor * ln(BaseOdds)`
- `Score = Offset + Factor * ln(odds)`

The implementation is a documentation and preview foundation. It is not a full scorecard trainer.

## Intentionally Deferred

The following engines were intentionally not built in Phase 15A:

- WOE/IV computation engine
- Reject inference engine
- Fair lending analytics engine
- Scorecard optimization engine
- Strategy optimization engine
- Full adverse-action reason-code generator

## Tests Run

- `npx tsc -b` - passed
- `.\.venv\Scripts\python.exe -m py_compile server\credit_risk\__init__.py server\credit_risk\credit_risk_types.py server\credit_risk\credit_risk_store.py server\credit_risk\credit_risk_router.py server\main.py` - passed
- `npm run test:credit-risk-studio` - passed
- `npm run test:evidence-graph` - passed
- `npm run test:model-documentation` - passed
- `npm run test:model-diagnostics` - passed
- `npm run test:dataset-library` - passed
- `npm run test:notebook-studio` - passed
- `npm run test:sql-data-studio` - passed
- `npm run test:analytics-workbench` - passed
- `npm run test:chart-studio` - passed
- `npm run test:persistence` - passed
- `npm run test:regression` - passed
- `npm run build:modeling` - passed
- `npm run build` - passed

## Build Notes

The build completes successfully. Existing warnings remain:

- Browserslist/caniuse-lite data is stale.
- Some bundles exceed the Vite chunk-size warning threshold.

## Clean Copy Sync

- `npm run sync:atlas` - passed
- clean-copy `npm run test:credit-risk-studio` - passed
- clean-copy `npm run build` - passed

The sync script intentionally excluded `server/artifacts`, so local runtime data was not copied into the clean ATLAS source tree.

## Manual QA Checklist

Completed browser route smoke test:

- Opened `http://127.0.0.1:5174/credit-risk-studio`.
- Confirmed page title: `ATLAS | Enterprise AI Model Development Platform`.
- Confirmed visible content for Credit Risk Studio, Project Setup, Scorecard Scaling, Credit Risk Guide, and the sidebar entry.

Recommended deeper browser QA:

1. Open `/credit-risk-studio`.
2. Confirm the sidebar link opens Credit Risk Studio.
3. Select Credit Card and Application Underwriting.
4. Document target event and target window.
5. Save the credit-risk setup.
6. Open Scorecard Scaling and confirm Factor/Offset preview.
7. Capture Credit Risk Evidence.
8. Open Model Evidence Center and confirm the evidence item appears.
9. Open Project Overview and confirm the Credit Risk Profile card appears.

## Phase 15B WOE / IV and Manual Characteristic Binning

Phase 15B adds the first functional underwriting analytics engine to Credit Risk Studio.

### Backend

- Added WOE / IV request, save, manual binning, evidence, and export types in `server/credit_risk/credit_risk_types.py`.
- Added `server/credit_risk/woe_iv_engine.py`.
- Added API endpoints:
  - `POST /api/credit-risk/woe-iv/run`
  - `GET /api/credit-risk/woe-iv/{analysis_id}`
  - `GET /api/credit-risk/woe-iv/project/{project_id}`
  - `POST /api/credit-risk/woe-iv/save`
  - `POST /api/credit-risk/woe-iv/export/excel`
  - `POST /api/credit-risk/woe-iv/save-evidence`
  - `POST /api/credit-risk/woe-iv/apply-manual-bins`
  - `POST /api/credit-risk/woe-iv/generate-code`
- WOE / IV artifacts persist under `server/artifacts/credit_risk/woe_iv`.
- Excel export includes Summary, IV Ranking, WOE Tables, Manual Bins, Variables Needing Review, Monotonicity Review, Evidence Mapping, and Code References sheets.

### WOE / IV Logic

- Event is treated as Bad.
- Non-event is treated as Good.
- Default smoothing is 0.5.
- `WOE = ln(Distribution Good / Distribution Bad)`.
- `IV contribution = (Distribution Good - Distribution Bad) * WOE`.
- Quantile and equal-width binning are implemented.
- Tree fallback currently uses quantile-style binning with a warning.
- Monotonic merge performs a first-pass adjacent merge until the bad-rate trend is monotonic or no further merge is possible.

### Frontend

Credit Risk Studio > Underwriting Feature Review now includes:

- WOE / IV setup controls.
- Predictor selection.
- WOE / IV formula help.
- Run WOE / IV Analysis.
- IV Ranking table.
- Selected Variable Detail with bin-level WOE table.
- Bad-rate, WOE, IV contribution, and population distribution charts.
- Manual Characteristic Binning editor.
- Save manual bins and lock approved bins controls.
- Python, SQL, R, and SAS-compatible generated code tabs.
- Export WOE / IV to Excel.
- Save WOE / IV Evidence and Save Manual Binning Evidence.

Project Overview now surfaces WOE / IV status, top IV variable, variables reviewed, and review item count when an analysis exists for the active project.

### Evidence Integration

WOE / IV and manual binning evidence is saved to the Model Evidence Center with credit-risk metadata, target/event context, top IV variables, variables needing review, and governance relevance flags.

### Phase 15B Tests

- Static tests were added for WOE / IV UI labels, formulas, backend endpoints, typed client functions, engine formulas, manual binning, evidence integration, and Project Overview status display.

## Phase 15C Credit Risk Scorecard Modeling Engine

### Summary

Phase 15C adds the first functional credit-risk scorecard modeling workflow to Credit Risk Studio. The user can move from Dataset and Target selection through WOE / IV variable selection, logistic scorecard training, PDO scaling, scorecard points, performance diagnostics, cutoff preview, generated code, Excel export, and evidence capture.

### Why Scorecard Modeling Matters

Credit-risk workflows need a transparent underwriting model artifact, not just governance forms. The scorecard engine creates a model record with coefficients, score scaling, points by characteristic bin, lift, KS, cutoff previews, generated reproducibility code, and evidence metadata suitable for downstream documentation.

### Scorecard Modeling Section

A new Credit Risk Studio section, `Scorecard Modeling`, was added between `Underwriting Feature Review` and `Scorecard Scaling`.

The section includes:

- Model Setup
- WOE Variable Selection
- Train Scorecard Model
- Model Performance
- Scorecard Points Table
- Score Distribution
- Cutoff Strategy Preview
- Generated Code
- Evidence Actions

### WOE Variable Selection

The section uses the latest WOE / IV analysis when available. Default variable selection includes variables with IV >= 0.02 and IV < 0.50 while excluding target, ID, score, prediction, probability, and protected-field name patterns. Variables with IV >= 0.50 are flagged as suspicious for leakage review.

If WOE / IV has not been run, the user can explicitly train a raw logistic baseline. ATLAS labels this as not scorecard-ready until WOE bins are approved.

### Logistic Scorecard Training

Backend file added:

- `server/credit_risk/scorecard_engine.py`

New API endpoints:

- `POST /api/credit-risk/scorecard/train`
- `GET /api/credit-risk/scorecard/{model_id}`
- `GET /api/credit-risk/scorecard/project/{project_id}`
- `POST /api/credit-risk/scorecard/export/excel`
- `POST /api/credit-risk/scorecard/save-evidence`
- `POST /api/credit-risk/scorecard/generate-code`
- `POST /api/credit-risk/scorecard/register-model`

The trainer uses `sklearn.linear_model.LogisticRegression` when available. If sklearn is unavailable, ATLAS returns a clear local-environment requirement message rather than fake model output.

### PDO Scaling Integration

The scorecard trainer uses the same scaling assumptions documented in Scorecard Scaling:

- `Factor = PDO / ln(2)`
- `Offset = BaseScore - Factor * ln(BaseOdds)`
- `Score = Offset + Factor * log(odds)`

The model stores PDO, base score, base odds, factor, offset, score direction, and score bounds.

### Scorecard Points Table

The generated points table includes:

- Variable
- Bin
- WOE
- Coefficient
- Raw contribution
- Points
- Reason code label

This is the primary transparent scorecard artifact for underwriting model review.

### Model Performance Metrics

The first implementation returns:

- AUC
- KS
- Gini
- Log loss
- Event rate
- Train rows
- Validation rows

It also creates:

- Detailed lift table
- KS table
- Score distribution
- Bad rate by decile
- Lift / decile chart
- Cutoff strategy preview

### Cutoff Strategy Preview

The preview includes:

- Score cutoff
- Approval rate
- Bad rate
- Expected loss
- Expected profit
- Population approved
- Population declined
- Recommendation

Expected loss/profit populate when average balance, loss given default, and revenue per booked account are supplied.

### Generated Code

Generated code is available for:

- Python
- SQL
- R
- SAS-compatible

The SAS-compatible output includes `PROC LOGISTIC` style code and score scaling logic.

### Excel Export

Scorecard Excel export includes:

- Model Summary
- Performance Metrics
- Detailed Lift Table
- KS Table
- Score Distribution
- Scorecard Points
- WOE Variables
- Cutoff Strategy
- Evidence Mapping
- Generated Code

### Evidence Center Integration

Evidence buttons were added for:

- Save Scorecard Model Evidence
- Save Scorecard Scaling Evidence
- Save Model Performance Evidence
- Save Cutoff Strategy Evidence
- Save Scorecard Points Evidence

Evidence metadata includes credit-risk domain, scorecard modeling technique, PDO settings, performance metrics, top variables, selected cutoff, and documentation-section mappings.

### Project Overview Integration

Project Overview now displays:

- Scorecard Model status
- Champion scorecard model
- AUC
- KS
- Gini
- PDO
- Base score
- Base odds
- Selected cutoff

### Model Documentation Studio Integration

Scorecard evidence is saved through the shared Model Evidence Center and supports Model Training Strategy, Model Performance, Model Interpretation, Scoring and External Validation, Implementation Plan, Monitoring Plan, Fair Lending and Governance Considerations, and Appendices.

### Phase 15C Tests

- Static tests were added for the Scorecard Modeling section, section order, model setup, WOE variable selection, raw logistic baseline option, PDO formulas, points table, performance panels, lift/cutoff tables, charts, generated code tabs, PROC LOGISTIC output, scorecard evidence actions, scorecard endpoints, and Project Overview scorecard metrics.

### Phase 15C Known Limitations

- Scorecard modeling uses available registered dataset rows or preview/sample rows depending on Dataset Library artifacts.
- WOE transformation depends on Phase 15B WOE bins.
- Reject inference is not included yet.
- Fair lending testing is not included yet.
- Adverse-action reason-code generation is not included yet.
- Production scoring deployment is not included yet.

### Recommended Next Build

The next credit-risk build should add adverse-action reason code generation and a first-pass fair lending testing workspace.

## Remaining Limitations

Credit Risk Studio is still not a full scorecard modeling platform. Phase 15B adds WOE / IV analysis and manual binning, but the following remain future work:

- reject inference engine
- fair lending analytics engine
- strategy optimization engine
- full adverse-action reason-code generator

## Phase 15D Dual-Track Credit Risk Modeling Workflow

### Summary

Phase 15D extends Credit Risk Studio into a dual-track underwriting development workflow. Analysts can now choose a Traditional Scorecard path, an AI/ML Underwriting path, or Compare Both. The existing WOE / IV, manual binning, logistic scorecard, PDO scaling, points table, validation, cutoff, explainability, evidence, code, and Excel export capabilities remain intact under the Traditional Scorecard path.

### New Workflow Structure

The current Credit Risk Studio workflow is:

1. Project Setup
2. Population and Target
3. Credit Risk EDA
4. Characteristic Screening
5. Modeling Approach
6. Traditional Scorecard Path
7. AI/ML Underwriting Path
8. Champion / Challenger Comparison
9. Cutoff and Decision Strategy
10. Explainability and Adverse Action
11. Monitoring and Portfolio Risk
12. Evidence and Documentation

### Modeling Approach Selector

The new Modeling Approach section lets the user select:

- Traditional Scorecard: transparent WOE / IV, binning, logistic scorecard, PDO scaling, points, cutoff, and reason-code-ready evidence.
- AI/ML Underwriting: modern challenger modeling with calibrated probabilities, feature importance, monotonic constraint documentation, explainability warnings, and surrogate-scorecard review.
- Compare Both: governed champion/challenger workflow for scorecard baseline versus AI/ML challenger.

### Traditional Scorecard Path

The existing scorecard workflow was preserved and consolidated into the Traditional Scorecard path. It still includes:

- WOE / IV setup and analysis.
- Manual characteristic binning.
- Approved WOE variable handoff to scorecard training.
- Logistic scorecard training.
- PDO scaling and scorecard point tables.
- AUC, KS, Gini, log loss, lift, score distribution, cutoff preview, generated code, Excel export, and evidence capture.

### AI/ML Underwriting Path

Added an AI/ML challenger path with model cards for:

- Logistic Regression Baseline
- Random Forest
- XGBoost
- LightGBM
- CatBoost
- Monotonic Gradient Boosting
- Calibrated AI/ML Model

The backend only trains models supported by the local environment. Unsupported libraries return clear unavailable messages instead of fake results. Local supported fallback models include logistic regression, random forest, gradient boosting, and calibrated variants where scikit-learn is available.

### AI/ML Explainability and Governance

The AI/ML path includes:

- Feature importance panel.
- SHAP fallback warning when SHAP is unavailable.
- Reason-code candidate mapping guidance.
- PDP / ICE placeholder with a clear future-work explanation.
- Surrogate scorecard placeholder and governance note.
- Complexity warning for model risk review.
- Monotonic constraints panel for documenting expected directionality and enforcement status.

### Champion / Challenger Comparison

Added a Champion / Challenger Comparison section with a side-by-side comparison table covering performance, calibration, explainability, adverse action readiness, fair lending readiness, monitoring readiness, and model risk complexity.

The section includes:

- Select Scorecard as Champion
- Select AI/ML as Champion
- Keep AI/ML as Challenger
- Save Champion / Challenger Evidence
- Open Model Evidence Center

### Cutoff and Adverse Action Updates

Cutoff and adverse-action sections now include model source/type selectors so the user can document decisions for the Traditional Scorecard, AI/ML Underwriting model, or selected Champion Model.

### Backend Additions

Added compact AI/ML underwriting summaries under `server/artifacts/credit_risk/ml_models`.

New API routes:

- `POST /api/credit-risk/ml/train`
- `GET /api/credit-risk/ml/{model_id}`
- `GET /api/credit-risk/ml/project/{project_id}`
- `POST /api/credit-risk/ml/export/excel`
- `POST /api/credit-risk/ml/save-evidence`
- `POST /api/credit-risk/champion-comparison/run`
- `POST /api/credit-risk/champion-comparison/save-decision`
- `POST /api/credit-risk/champion-comparison/save-evidence`

### Project Overview Integration

Project Overview now surfaces:

- Modeling Approach
- Scorecard Status
- AI/ML Status
- Champion Decision
- Champion Model
- Scorecard AUC / KS / Gini
- AI/ML AUC / KS / Gini
- Selected Champion
- Evidence Readiness

### Tests Run

- `npm run test:credit-risk-studio` - passed.
- `npx tsc -b` - passed.
- `.\.venv\Scripts\python.exe -m py_compile server\credit_risk\credit_risk_types.py server\credit_risk\credit_risk_router.py server\credit_risk\ml_engine.py server\main.py` - passed.
- `npm run test:evidence-graph` - passed.
- `npm run test:model-documentation` - passed.
- `npm run test:model-diagnostics` - passed.
- `npm run test:dataset-library` - passed.
- `npm run test:notebook-studio` - passed.
- `npm run test:sql-data-studio` - passed.
- `npm run test:analytics-workbench` - passed.
- `npm run test:chart-studio` - passed.
- `npm run test:persistence` - passed.
- `npm run test:regression` - passed.
- `npm run build:modeling` - passed.
- `npm run build` - passed.
- `npm run test:evidence-graph` - passed.
- `npm run test:model-documentation` - passed.
- `npm run test:model-diagnostics` - passed.
- `npm run test:dataset-library` - passed.
- `npm run test:notebook-studio` - passed.
- `npm run test:sql-data-studio` - passed.
- `npm run test:analytics-workbench` - passed.
- `npm run test:chart-studio` - passed.
- `npm run test:persistence` - passed.
- `npm run test:regression` - passed.
- `npm run build:modeling` - passed.
- `npm run build` - passed.
- Clean copy `npm run test:credit-risk-studio` - passed.
- Clean copy `npm run build` - passed.

### Manual QA Results

Manual browser QA was not run during this implementation pass. Static tests verify the dual-track workflow labels, modeling approach selector, traditional scorecard path preservation, AI/ML path labels, monotonic constraints, explainability placeholders, champion/challenger actions, backend routes, typed client functions, and Project Overview status fields.

### Clean-Copy Sync Confirmation

Confirmed. `npm run sync:atlas` copied the verified Phase 15D dual-track changes to `C:\Users\james\Projects\ATLAS\atlas-app`. The clean copy passed `npm run test:credit-risk-studio` and `npm run build`. The sync script intentionally excluded `server/artifacts`, so local runtime model artifacts were not copied into the clean source tree.

### Known Limitations

- XGBoost, LightGBM, and CatBoost are shown as unavailable unless their Python libraries are installed locally.
- Monotonic constraints are documented but not enforced for unsupported local model engines.
- SHAP, PDP / ICE, and surrogate scorecard are governance-ready placeholders unless supporting explainability artifacts are added.
- AI/ML model training stores compact summaries only; full model binaries are not yet packaged for deployment from Credit Risk Studio.
- Fair lending testing, reject inference, and legally validated adverse-action reason generation remain future phases.

### Recommended Next Build

- Add fair lending analytics and adverse-action reason-code generation.
- Connect scored TRAIN / TEST / OOT datasets directly into Credit Risk Studio validation.
- Add governed model packaging for selected scorecard and AI/ML champion models.

## Phase 15E Credit Risk Studio Dataset Binding and HELOC QA Fixes

### Summary

Phase 15E focused on QA defects found before the HELOC test run. Credit Risk Studio now treats the Project Setup dataset as the canonical source for downstream schema, target controls, EDA, characteristic screening, WOE / IV, scorecard requests, AI/ML requests, and evidence-derived state.

### Dataset Binding

- Changing the active dataset now persists the dataset ID and version.
- The selected dataset schema, profile, and sample metadata are reloaded immediately.
- Stale schema-derived state is cleared on dataset change, including variable mappings, target summary, WOE / IV results, scorecard outputs, AI/ML outputs, and champion comparison state.
- Variable mappings are rebuilt only from the active dataset schema.
- Credit Risk Studio now displays the active dataset label and a schema mismatch warning when saved mappings do not match the active schema.

### HELOC Target and Dataset Defaults

The HELOC flow now recognizes the expected project setup:

- Dataset: `HELOC_TRAIN`
- Target column: `bad_flag`
- Event / bad value: `1`
- Non-event / good value: `0`
- Original target label: `RiskPerformance`
- Split column: `atlas_split`
- Validation dataset: `HELOC_TEST`
- OOT dataset: `HELOC_OOT`
- OOT type: Synthetic holdout

### Predictor Exclusions and Roles

- `bad_flag` defaults to Target.
- `RiskPerformance` defaults to Original Target Label / Excluded.
- `atlas_split` defaults to Split Indicator / Excluded.
- Target, original-label, split, prediction, probability, PD, protected-label, and ID-like fields are excluded from predictors.
- HELOC bureau-style attributes such as `ExternalRiskEstimate`, `MSinceOldestTradeOpen`, `NumSatisfactoryTrades`, `NetFractionRevolvingBurden`, and `PercentTradesWBalance` default to Bureau.
- HELOC bureau variables are not auto-flagged as protected/sensitive fields.

### Target Summary

Added a selected-dataset target summary before WOE / IV:

- Profiled rows / total rows
- Good count
- Bad count
- Bad rate
- Indeterminate count
- Missing target count
- Target window
- Outcome source

Important limitation: the current local HELOC artifact contains a 5,000-row `data_sample.csv` while the profile reports 6,275 rows. ATLAS therefore labels the HELOC target summary as a preview sample summary and does not imply exact full-population target counts unless the full dataset artifact is available.

### Special Values

Added bureau special-value profiling for `-7`, `-8`, and `-9`:

- Special value counts by variable
- Special value rate
- Recommended treatment language
- Preservation guidance so bureau special values are not accidentally treated as ordinary missing values

### Step Navigation and Validation

Added bottom workflow CTAs:

- Confirm Project Setup and Continue
- Save Target Definition and Continue
- Save EDA Evidence and Continue
- Confirm Characteristic Screening and Continue
- Save Scorecard Progress and Continue
- Save AI/ML Progress and Continue
- Save Champion Decision and Continue
- Open Model Evidence Center / Open Model Documentation Studio

Project Setup, Population and Target, and Characteristic Screening now include validation before continuing.

### Tests Run

- `npm run test:credit-risk-studio` - passed.
- `npx tsc -b` - passed.
- `.\.venv\Scripts\python.exe -m py_compile server\credit_risk\credit_risk_types.py server\credit_risk\credit_risk_router.py server\credit_risk\ml_engine.py server\main.py` - passed.

### Manual QA Results

Manual browser QA has not yet been run for Phase 15E. Static and build checks verify the dataset-binding logic, HELOC defaults, target summary endpoint, special-value profiling, predictor exclusions, role defaults, schema mismatch language, and bottom CTA labels.

### Clean-Copy Sync

Confirmed. `npm run sync:atlas` copied the verified Phase 15E changes to `C:\Users\james\Projects\ATLAS\atlas-app`. The clean copy passed `npm run test:credit-risk-studio` and `npm run build`. The sync script intentionally excluded `server/artifacts`, so local runtime dataset/model artifacts were not copied into the clean source tree.

## Phase 15F Population and Target Dropdown Hydration Hotfix

### Summary

Fixed a Credit Risk Studio hydration defect where the active dataset banner correctly displayed `HELOC_TRAIN`, but the Population and Target dropdowns remained empty or stale. The selected dataset schema is now the source of truth for target, original target label, split column, validation dataset, OOT dataset, variable mappings, and target summary requests.

### Fixes

- The selected dataset profile now calls `setSchema(columns)` so Population and Target dropdowns populate from the active dataset schema.
- Stale saved target fields are rejected if they are not present in the selected dataset schema.
- `bad_flag` auto-selects as Target Column when present.
- `RiskPerformance` auto-selects as Original Target Label Column when present.
- `atlas_split` auto-selects as Split Column when present.
- `HELOC_TEST` auto-selects as Validation Dataset when available.
- `HELOC_OOT` auto-selects as OOT Dataset when available.
- OOT Type defaults to Synthetic holdout when the HELOC OOT dataset is found.
- Added a Refresh Dataset Schema button near the active dataset banner.
- Added a visible schema-load error if Dataset Library schema hydration fails.
- Target Summary now shows “Select a target column to calculate the target summary” instead of misleading blank cards when no target is selected.

### HELOC Target Summary Note

The current local HELOC profile reports 6,275 rows, but the persisted `data_sample.csv` contains 5,000 rows. ATLAS will calculate the target summary from the available artifact and label it as a preview sample summary when the full data artifact is not available.

### Tests Run

- `npm run test:credit-risk-studio` - passed.
- `npm run test:dataset-library` - passed.
- `npm run test:evidence-graph` - passed.
- `npm run test:model-documentation` - passed.
- `npm run test:model-diagnostics` - passed.
- `npm run test:regression` - passed.
- `npx tsc -b` - passed.
- `npm run build:modeling` - passed.
- `npm run build` - passed.

### Manual QA Results

Manual browser QA was not run in this pass. Static checks verify the refresh action, HELOC schema fields, HELOC validation/OOT dataset defaults, target-summary empty-state guidance, and absence of California housing field leakage in Credit Risk Studio.

### Clean-Copy Sync

Confirmed. `npm run sync:atlas` copied the Phase 15F hydration fix to `C:\Users\james\Projects\ATLAS\atlas-app`. The clean copy passed `npm run test:credit-risk-studio` and `npm run build`.

## Phase 15G Credit Risk Studio Predictive Modeling Wrapper Re-architecture

### Summary

Credit Risk Studio is now positioned as a regulated underwriting solution pack on top of the full ATLAS Predictive Modeling workflow rather than a separate replacement workflow. The studio keeps the existing WOE/IV, manual binning, scorecard, PDO scaling, AI/ML challenger, champion/challenger, adverse action, fair lending, stability, and evidence tools, while making it explicit that Tier 1 credit-risk models still require the full model-development lifecycle.

### Why the Re-architecture Was Needed

The prior Credit Risk Studio experience could appear to bypass standard predictive-model development controls. For underwriting models, that is not appropriate. The updated design clarifies that Credit Risk Studio extends, rather than replaces, the full ATLAS lifecycle: project context, data acquisition, bureau review, EDA, outliers, missing values, feature engineering, split strategy, model training, evaluation, interpretation, scoring, documentation, implementation, and monitoring.

### Wrapper Design

Credit Risk Studio now has five visible wrapper areas:

- Credit Risk Setup
- Predictive Workflow
- Underwriting Tools
- Champion / Challenger
- Evidence and Documentation

The studio header includes a Tier 1 underwriting banner explaining that credit-risk development requires full data quality review, EDA, train/test/OOT validation, model diagnostics, interpretation, scoring, documentation, implementation, monitoring, and governance evidence.

### Predictive Modeling Workflow Reuse

The new Predictive Workflow section displays every ATLAS predictive workflow step with underwriting-specific relevance text and an action to open the underlying step. This makes the connection between the general modeling workflow and credit-risk underwriting controls visible to the analyst.

Included steps:

- Project Context
- Data Acquisition
- Credit Bureau Data Review
- EDA
- Outliers
- Missing Values
- Feature Engineering
- Balance & Split
- Model Training
- Evaluation
- Interpretation
- Scoring
- Documentation Review
- Model Implementation
- Model Monitoring

### Underwriting Tools Preserved

All existing underwriting workbench capabilities were preserved:

- Bureau Special Value Profile
- WOE / IV and manual characteristic binning
- Traditional Scorecard Modeling
- PDO Scaling and Scorecard Points
- AI/ML Underwriting Challenger
- Monotonic constraints
- Surrogate scorecard
- Cutoff strategy
- Adverse action
- Fair lending hooks
- PSI / stability review
- Champion / challenger evidence

### Diagnostics, Documentation, and Evidence Integration

Credit Risk Studio now surfaces first-class links to:

- Model Diagnostics
- Model Documentation Studio with Credit Risk Evidence
- Model Evidence Center
- Credit Risk Evidence Pack export

Project Overview now includes a Credit Risk Studio wrapper readiness summary with:

- Predictive Workflow completion
- Underwriting Tools readiness
- Model Diagnostics status
- Documentation Studio status
- Model Evidence Center coverage
- Monitoring Readiness

### Target Leakage Fix

Credit Risk Studio now uses a shared predictor-candidate filter so target and scoring artifact fields do not enter underwriting feature analysis or model requests.

Excluded from WOE variables, IV ranking, scorecard variables, and AI/ML predictors:

- Current target column
- Original target label column
- Split column
- `RiskPerformance`
- `bad_flag`
- `atlas_split`
- target/outcome/label fields
- prediction/probability/score/PD fields

The filter is applied in UI defaults, target changes, variable selection buttons, WOE/IV requests, generated WOE code requests, scorecard training requests, scorecard generated-code requests, and AI/ML challenger requests.

### Full Dataset Versus Preview Handling

Credit Risk Studio continues to label target summaries based on the available dataset artifact. The current local HELOC profile reports 6,275 rows, while the persisted browser/backend sample artifact contains 5,000 rows. When the full artifact is unavailable, ATLAS labels the summary as preview/sample-derived rather than implying full-population statistics.

### Tests Run

- `npm run test:credit-risk-studio` - passed.
- `npm run test:evidence-graph` - passed.
- `npm run test:model-documentation` - passed.
- `npm run test:model-diagnostics` - passed.
- `npm run test:dataset-library` - passed.
- `npm run test:notebook-studio` - passed.
- `npm run test:sql-data-studio` - passed.
- `npm run test:analytics-workbench` - passed.
- `npm run test:chart-studio` - passed.
- `npm run test:persistence` - passed.
- `npm run test:regression` - passed.
- `npx tsc -b` - passed.
- `npm run build:modeling` - passed.
- `npm run build` - passed.

### Manual QA Results

Manual browser QA was not run in this pass. Static tests and builds verify the visible wrapper labels, predictive workflow step list, underwriting tool links, target-leakage filtering, Project Overview wrapper readiness fields, and cross-feature compile stability.

### Clean-Copy Sync

Confirmed. `npm run sync:atlas` copied the Phase 15G wrapper re-architecture to `C:\Users\james\Projects\ATLAS\atlas-app`. The clean copy passed `npm run test:credit-risk-studio` and `npm run build`. The sync script intentionally excluded `server/artifacts`, so local runtime dataset/model artifacts were not copied into the clean source tree.

### Known Limitations

- Credit Risk Studio still relies on the existing predictive workflow routes instead of embedding every predictive step directly inside the studio.
- Full warehouse-scale HELOC summaries depend on registered full-data artifacts; local sample artifacts can still produce preview-labeled summaries.
- AI/ML challenger packaging and deployment export remain compact-summary oriented.
- Manual browser QA should be run before a stakeholder demo.

### Recommended Next Build

Run a full HELOC smoke test through Project Setup, Population and Target, Predictive Workflow, WOE/IV, Scorecard, AI/ML challenger, Champion / Challenger, Model Diagnostics, Model Documentation Studio, and Model Evidence Center to validate the wrapper experience end to end.
## Phase 15H Credit Risk Studio as Predictive Modeling Solution Pack

### Summary
Credit Risk Studio has been redesigned so the primary experience is the full Predictive Modeling workflow running in Credit Risk Mode. The page now presents Project Context, Data Acquisition, Credit Bureau Data Review, EDA, Outliers, Missing Values, Feature Engineering, Balance & Split, Model Training, Evaluation, Interpretation, Scoring, Documentation Review, Model Implementation, and Model Monitoring as the main workflow rail inside `/credit-risk-studio`.

### Why the prior wrapper design was still confusing
The prior design showed a Predictive Workflow tab that linked out to regular predictive pages while also keeping a separate Credit Risk Workflow rail. That created two apparent development paths and made credit-risk work feel like a dashboard wrapper rather than the actual modeling workflow.

### New unified workflow design
The primary rail now uses the predictive modeling step list and keeps navigation on `/credit-risk-studio?step=...`. The selected predictive step renders a Credit Risk Mode panel, its evidence mapping, and the underwriting overlay content mapped to that workflow step. A secondary “Open in full Predictive Modeling” action remains available when the user explicitly wants to leave the studio.

### Predictive Modeling step reuse
The studio now shares the workflow store current step state through `setCurrentStepId` and maps each Credit Risk Studio query step to the existing predictive workflow step IDs (`step00` through `step13`). Existing credit-risk implementation panels are reused as overlays instead of being exposed as a competing primary rail.

### Credit-risk overlays by step
Overlays were added to the selected workflow step summary for project context, data acquisition, bureau data review, EDA, outliers, missing values, feature engineering, balance/split, model training, evaluation, interpretation, scoring, documentation review, implementation, and monitoring. The existing WOE/IV, manual binning, scorecard, AI/ML challenger, champion/challenger, cutoff, adverse-action, evidence, and monitoring panels remain available as step-specific underwriting content.

### Underwriting tools panel
A persistent underwriting tools panel is available from every workflow step. It includes WOE / IV, manual binning, Traditional Scorecard Modeling, PDO scaling, scorecard points, AI/ML Underwriting Challenger, champion/challenger comparison, cutoff strategy, adverse action, fair lending hooks, PSI/stability, bureau special-value profiling, monotonic constraints, surrogate scorecard, Model Diagnostics, Model Evidence Center, and Model Documentation Studio.

### Shared state requirements
Credit Risk Studio now updates the shared ATLAS workflow current step while staying on `/credit-risk-studio`. Existing project state, dataset IDs, target fields, split fields, selected predictors, model IDs, scored dataset IDs, evidence readiness, and documentation mappings continue to flow through the persisted credit-risk profile and workflow store.

### Target leakage protections
The predictor candidate filters continue to block `RiskPerformance`, `bad_flag`, `atlas_split`, target columns, original target labels, split indicators, prediction/probability fields, and sensitive demographic patterns. Dataset changes still clear schema-derived outputs, WOE analysis, scorecard model state, ML model state, target summary, and champion comparison state.

### Full dataset versus preview handling
The target summary still labels preview output as `Preview Sample Summary` when full artifacts are unavailable. The Model Training overlay now explicitly calls out that production-style training requires Full Dataset mode and must not silently use preview data.

### Evidence and documentation integration
Every workflow step summary shows evidence generated for that step. Documentation Review and the persistent tools panel expose Model Evidence Center, Model Documentation Studio, and Model Diagnostics as first-class destinations. MDS section mapping remains available for Business Purpose, Data Sources, Population Definition, Target Definition, Data Quality, Missing Value Treatment, Outlier Treatment, Feature Engineering, Model Training Strategy, Model Performance, Model Interpretation, Scoring and Implementation, Fair Lending and Governance Considerations, Monitoring Plan, Limitations, and Appendices.

### Tests run
- `npm run test:credit-risk-studio`
- `npm run test:evidence-graph`
- `npm run test:model-documentation`
- `npm run test:model-diagnostics`
- `npm run test:dataset-library`
- `npm run test:notebook-studio`
- `npm run test:sql-data-studio`
- `npm run test:analytics-workbench`
- `npm run test:chart-studio`
- `npm run test:persistence`
- `npm run test:regression`
- `npx tsc -b`
- `npm run build:modeling`

### Manual QA results
Manual browser QA was not run in this pass. Static route tests and TypeScript/build validation confirm that Credit Risk Studio registers the route, keeps step navigation in the studio through `?step=...`, renders all predictive workflow steps, exposes underwriting tools, and keeps leakage protections in place.

### Clean-copy sync confirmation
Pending final `npm run sync:atlas` after the full build.

### Known limitations
The implementation reuses the existing Credit Risk Studio panels as overlays rather than extracting every predictive page into separate shared `src/components/modeling/steps/*` components. The optional “Open in full Predictive Modeling” action still links to the underlying predictive routes by design.

### Recommended next build
Extract reusable predictive step shells into shared components and mount those directly inside Credit Risk Studio where the existing step pages are suitable for embedded use.

### Acceptance criteria
Credit Risk Studio no longer presents a Predictive Workflow tab plus a separate credit-risk rail as competing primary paths. The full predictive modeling workflow is the main navigation, step clicks stay inside `/credit-risk-studio`, underwriting tools are overlays/add-ons, HELOC leakage fields remain excluded from predictors, dataset changes clear stale artifacts, and MDS/MEC/Diagnostics remain first-class destinations.

## Phase 15I Credit Risk Studio Layout and State Fixes

### Summary
Phase 15I tightens the redesigned Credit Risk Studio after browser QA. The fixes focus on compact layout, HELOC state correctness, Population and Target hydration, Data Acquisition behavior, and readable documentation mapping in the right rail.

### Header whitespace fix
The large header was replaced with a compact enterprise header containing only the title, subtitle, summary cards, and a collapsed readiness details panel. Workflow navigation and setup controls now sit below the header so the active workflow content appears sooner without scrolling.

### Header stale state fix
Credit Risk Studio now normalizes stale recovered regression state when HELOC datasets are available. If old REG/housing state or a stale housing target is detected, the studio restores the HELOC credit-risk source of truth: `HELOC_TRAIN`, `bad_flag = 1`, `RiskPerformance`, `atlas_split`, `HELOC_TEST`, `HELOC_OOT`, and `Synthetic holdout`.

### Population and Target dropdown hydration
The selected credit-risk dataset schema remains the source for Target Column, Original Target Label Column, and Split Column dropdown options. HELOC defaults hydrate to `bad_flag`, `RiskPerformance`, and `atlas_split`, with validation/OOT dataset defaults mapped to `HELOC_TEST` and `HELOC_OOT`.

### Data Acquisition redesign
Data Acquisition no longer renders the Population and Target setup form. It now shows a dataset lineage summary for training, validation, OOT, target, event value, original label, split column, source type, and dataset purpose. It includes actions for Dataset Library, Population and Target, saving Data Acquisition evidence, and continuing to Credit Bureau Data Review. If target setup is incomplete, it shows a clear banner.

### Mapped Documentation Sections formatting
The right rail evidence and documentation panel is now single-column at sidebar width, and checklist items have stable spacing with non-overlapping icons and text. Mapped Documentation Sections remain readable at standard browser widths.

### Tests run
- `npm run test:credit-risk-studio`
- `npm run test:dataset-library`
- `npm run test:evidence-graph`
- `npm run test:model-documentation`
- `npm run test:model-diagnostics`
- `npm run test:persistence`
- `npm run test:regression`
- `npx tsc -b`
- `npm run build:modeling`

### Manual QA results
Manual browser QA was not run in this pass. Static and build validation cover the compact header structure, collapsed readiness details, HELOC default state, Data Acquisition summary behavior, and readable mapped documentation checklist.

### Clean-copy sync confirmation
Pending final `npm run sync:atlas` after the full build.

### Known limitations
The stale-state correction intentionally targets recovered REG/housing state and missing HELOC defaults. It does not prevent a user from explicitly selecting a non-HELOC dataset for another credit-risk project.

### Recommended next build
Add browser-level Playwright coverage for `/credit-risk-studio?step=data-acquisition` and `/credit-risk-studio?step=project-context` so compact layout and no-stale-state behavior are validated against rendered DOM, not only source-level tests.

### Acceptance criteria
The header is compact, readiness details are collapsed by default, HELOC state hydrates to `HELOC_TRAIN` and `bad_flag = 1`, stale REG/housing values are scrubbed from HELOC setup, Population and Target dropdowns hydrate, Data Acquisition shows lineage instead of broken target controls, and Mapped Documentation Sections are readable.

## Phase 15J Credit Risk Studio UX Correction

### Summary
Phase 15J corrects the post-15H/15I user experience so Credit Risk Studio feels like a working model-development workflow rather than a dashboard. The primary workflow remains the full Predictive Modeling sequence inside `/credit-risk-studio`, with credit-risk fields, checks, tools, and evidence embedded in the relevant steps.

### Why the Phase 15H Design Was Not Usable
The 15H design fixed the architecture but left too much visible sidebar material and made several steps feel like summaries or link hubs. Data Acquisition was too passive, the right rail competed with the active step, and EDA/outlier/missing/split review did not feel like focused working pages.

### Right Rail Simplification
The right rail now defaults to a minimal Current Step Guide with required inputs, recommended next action, and critical warnings. Heavy content moved into collapsed sections: Open Underwriting Tools, Evidence Readiness, Mapped Documentation Sections, Champion / Challenger, and Model Diagnostics / MEC / MDS links.

### Data Acquisition Controls
Data Acquisition now includes working controls for training dataset, validation dataset, OOT dataset, OOT type, dataset source type, source/upload source, dataset purpose, lineage notes, target column, event value, original target label column, and split column. HELOC defaults remain `HELOC_TRAIN`, `HELOC_TEST`, `HELOC_OOT`, `Synthetic holdout`, `bad_flag`, `1`, `RiskPerformance`, and `atlas_split`.

### EDA Redesign
EDA now includes target distribution, good/bad count, bad rate, missingness table, special bureau value profile, variable distribution table, candidate predictor ranking, leakage warnings, high-cardinality/schema review hooks, and basic association guidance. It avoids generic “Pending” placeholders when schema context is available.

### Restored Working Step Pattern
Outliers, Missing Values, and Balance & Split now render focused in-studio panels with purpose/inputs/outputs/evidence, working tables, treatment guidance, evidence buttons, and confirm-and-continue actions. Existing detailed scorecard, WOE/IV, AI/ML, cutoff, interpretation, monitoring, evidence, MEC, MDS, and diagnostics surfaces remain available.

### Contextual Underwriting Tools
Underwriting tools are collapsed by default and opened intentionally from the right rail. Step-specific warnings and next actions call out the relevant tool category rather than showing all tools on every page.

### Target Leakage Protections
Leakage protections remain enforced through `isCreditRiskPredictorCandidate`: `RiskPerformance`, `bad_flag`, `atlas_split`, target fields, original labels, split indicators, prediction/probability fields, and sensitive demographic patterns are excluded from predictor, WOE/IV, scorecard, AI/ML, and feature selection flows.

### Tests Run
- `npm run test:credit-risk-studio`
- `npm run test:evidence-graph`
- `npm run test:model-documentation`
- `npm run test:model-diagnostics`
- `npm run test:dataset-library`
- `npm run test:notebook-studio`
- `npm run test:sql-data-studio`
- `npm run test:analytics-workbench`
- `npm run test:chart-studio`
- `npm run test:persistence`
- `npm run test:regression`
- `npx tsc -b`
- `npm run build:modeling`

### Manual QA Results
Manual browser QA was not run in this pass. Static and build validation cover collapsed right rail behavior, editable Data Acquisition controls, HELOC defaults, stronger EDA sections, in-studio Outliers/Missing Values/Balance & Split panels, and leakage exclusions.

### Clean-Copy Sync Confirmation
Pending final `npm run build`, `npm run sync:atlas`, and clean-copy validation.

### Known Limitations
The EDA enhancements use available profile/schema/WOE artifacts. Full charts and richer correlation statistics should be added by embedding the existing EDA/Analytics Workbench internals directly once those components are extracted for reuse.

### Recommended Next Build
Extract reusable predictive step components for EDA, Outliers, Missing Values, Balance & Split, and Model Training so Credit Risk Studio can mount the exact predictive workflow internals plus credit-risk overlays.

### Acceptance Criteria
Credit Risk Studio no longer presents as a busy dashboard, Data Acquisition supports direct dataset/target confirmation, EDA contains useful review sections, the right rail is minimal and collapsed by default, underwriting tools are contextual, workflow depth is preserved, leakage protections remain active, and WOE/IV, scorecard, PDO, AI/ML, MEC, MDS, and diagnostics functions remain available.

## Phase 15K Credit Risk Studio Workflow Routing and Step Mapping Fixes

### Summary
Phase 15K fixes remaining workflow routing issues after Phase 15J. Credit Risk Studio now has editable project naming, deterministic Data Acquisition continuation, exact Tier 1 route mapping, a distinct Credit Bureau Data Review page, separated EDA content, and ordered continue actions through Bureau Review, EDA, Outliers, Missing Values, Feature Engineering, and Balance & Split.

### Project naming fix
Credit Risk Studio now exposes a Project name field with Rename project and Save project name action controls. The default HELOC run name is `HELOC Traditional Scorecard Test Run`. Saving updates the workflow store, the Credit Risk Studio header, the Current Project area, and the persisted credit-risk profile so Project Overview uses the same project name after refresh.

### Data Acquisition routing fix
The Confirm Data Acquisition and Continue action now saves the current Data Acquisition state, marks source/target readiness, updates the URL to `/credit-risk-studio?step=credit-bureau-data-review`, and renders Credit Bureau Data Review directly. The route has explicit loading and failure states: `Loading Credit Bureau Data Review...` and `Unable to load Credit Bureau Data Review. Retry dataset schema refresh.`

### Step mapping fix
The workflow route map now uses the requested 15-step order and exact slugs: `project-context`, `data-acquisition`, `credit-bureau-data-review`, `eda`, `outliers`, `missing-values`, `feature-engineering`, `balance-split`, `model-training`, `evaluation`, `interpretation`, `scoring`, `documentation-review`, `model-implementation`, and `model-monitoring`.

### Credit Bureau Data Review page
Credit Bureau Data Review is now a real in-studio page rather than a duplicate EDA render. It shows `HELOC_TRAIN`, bureau variable inventory, trade-line variables, delinquency variables, inquiry variables, utilization / burden variables, special values `-7`, `-8`, and `-9`, original target label exclusion, target leakage exclusions, bureau limitation notes, evidence actions, and Confirm Credit Bureau Data Review and Continue.

### EDA page separation
The EDA route now renders an EDA-titled page with target distribution, good/bad counts, bad rate, predictor distribution summary, missingness summary, candidate variable ranking, leakage warnings, bad-rate by variable hooks, Analytics Workbench and Chart Studio links, Save EDA Evidence, and Confirm EDA and Continue. If full metrics are unavailable, it explains whether schema-only EDA is shown or the target column is not selected.

### Outliers page
Outliers remains a focused in-studio step with numeric variable outlier profile, special value reminder, treatment selector, reviewer notes, evidence saving, and Confirm Outliers and Continue. HELOC special values default to Create special bin.

### Missing Values page
Missing Values now includes missing value profile, bureau special value profile, `-7` count, `-8` count, `-9` count, special value rate, treatment plan, evidence saving, and Confirm Missing Values and Continue. The page explicitly states that HELOC `-7`, `-8`, and `-9` values should be preserved as special bins unless the user documents a different treatment.

### Workflow order enforcement
Continue actions now move in the required order: Data Acquisition to Credit Bureau Data Review, Credit Bureau Data Review to EDA, EDA to Outliers, Outliers to Missing Values, Missing Values to Feature Engineering, and Feature Engineering to Balance & Split. Feature Engineering shows a warning if EDA, Outliers, and Missing Values have not been documented before the user jumps there.

### Tests run
- `npm run test:credit-risk-studio`
- `npm run test:evidence-graph`
- `npm run test:model-documentation`
- `npm run test:model-diagnostics`
- `npm run test:dataset-library`
- `npm run test:notebook-studio`
- `npm run test:sql-data-studio`
- `npm run test:analytics-workbench`
- `npm run test:chart-studio`
- `npm run test:persistence`
- `npm run test:regression`
- `npx tsc -b`
- `npm run build:modeling`
- `npm run build`

### Manual QA results
Manual browser QA was not run in this pass. Static tests cover the requested route map, route-specific pages, project-name controls, HELOC defaults, leakage exclusions, and continue handlers. Build validation confirmed the updated UI compiles.

### Clean-copy sync confirmation
`npm run sync:atlas` succeeded after rerunning with elevated permissions because the normal sync hit destination Access Denied errors. Clean copy validation passed:
- `npm run test:credit-risk-studio`
- `npm run build`

### Known limitations
Project-name editing saves through the existing workflow store and credit-risk profile. Broader cross-studio project metadata systems should be unified later so every studio reads one canonical project record.

### Recommended next build
Add browser-level Playwright coverage for `/credit-risk-studio?step=credit-bureau-data-review`, `/credit-risk-studio?step=eda`, `/credit-risk-studio?step=outliers`, `/credit-risk-studio?step=missing-values`, and project-name persistence after refresh.

### Acceptance criteria
Project name can be edited from Credit Risk Studio, Data Acquisition reliably opens Credit Bureau Data Review, Credit Bureau Data Review is not blank and does not render EDA content, the workflow proceeds through Bureau Review, EDA, Outliers, Missing Values, and Feature Engineering in order, no required Tier 1 step is skipped, HELOC OOT type is Synthetic holdout, and the clean copy is synced and builds.

## Phase 15L Credit Risk Studio Real Predictive Workflow Integration

### Summary
Phase 15L corrects Credit Risk Studio from a static imitation workflow into Predictive Modeling running in Credit Risk Mode. The main workflow now mounts the real ATLAS Predictive Modeling step components for Data Acquisition, EDA, Outliers, Missing Values, Feature Engineering, Balance & Split, Model Training, Evaluation, Interpretation, Scoring, Documentation Review, Model Implementation, and Model Monitoring, with underwriting overlays added inside those steps.

### Why prior pages were insufficient
The prior Credit Risk Studio pages had the right labels but too many static summaries and local placeholder tables. That made the workflow feel separate from ATLAS Predictive Modeling and left important working controls, tables, and model-development behavior disconnected from the main path.

### Bureau auto-detection in Data Acquisition
Credit Bureau Data Review is no longer a required main workflow step. Bureau review is folded into Data Acquisition and downstream overlays. Data Acquisition now auto-detects HELOC bureau fields, reports bureau data detected, bureau variable count, risk estimate fields, trade/file depth fields, delinquency fields, inquiry fields, utilization/burden fields, special values `-7`, `-8`, and `-9`, and recommends preserving special values as special bins.

### EDA real functionality
EDA now embeds the real `Step02_EDA` Predictive Modeling page and layers credit-risk overlays for target distribution, good/bad counts, bad rate, bureau groups, special values, bad-rate spread by bureau variable, leakage warnings, Analytics Workbench, and Chart Studio.

### Outliers real functionality
Outliers now embeds the real `Step04_Outliers` workflow. Credit Risk Mode adds overlays that clarify `-7`, `-8`, and `-9` are bureau special values, not ordinary numeric outliers, and that the default treatment is to create special bins or preserve the values for WOE / IV unless explicitly changed.

### Missing Values real functionality
Missing Values now embeds the real `Step04_MissingValues` workflow. Credit Risk Mode distinguishes ordinary null missingness from HELOC bureau special values and adds the required preservation guidance for `-7`, `-8`, and `-9`.

### Feature Engineering integration
Feature Engineering now embeds the real `Step05_EncodingScaling` workflow and keeps WOE / IV, manual characteristic binning, special bureau value binning, approved bins, excluded feature rationale, transformation evidence, and generated transformation code in the main feature engineering path.

### Balance & Split integration
Balance & Split now embeds the real `Step06_BalancingSplit` workflow and overlays the HELOC split contract: `HELOC_TRAIN`, `HELOC_TEST`, `HELOC_OOT`, and `Synthetic holdout`.

### Model Training integration
Model Training now embeds the real `Step06_Train` workflow and overlays credit-risk choices for Traditional Scorecard, AI/ML Underwriting Challenger, and Compare Both. Scorecard-specific WOE variables, manual bins, logistic regression, PDO scaling, and scorecard points remain available, while AI/ML uses the available Predictive Modeling engines.

### Target leakage protections
Leakage protections remain enforced through `isCreditRiskPredictorCandidate`: `RiskPerformance`, `bad_flag`, `atlas_split`, target fields, original target labels, split indicators, predictions/probabilities, and sensitive demographic patterns remain excluded from predictor lists, WOE / IV variables, feature engineering candidates, model training predictors, interpretation predictor lists, and scoring input predictors.

### Preview versus full data handling
Credit Risk Studio now explicitly states that model training should not use preview data silently. Full registered HELOC datasets are preferred, and preview-mode model training must be explicit.

### Tests run
- `npm run test:credit-risk-studio`
- `npm run test:evidence-graph`
- `npm run test:model-documentation`
- `npm run test:model-diagnostics`
- `npm run test:dataset-library`
- `npm run test:notebook-studio`
- `npm run test:sql-data-studio`
- `npm run test:analytics-workbench`
- `npm run test:chart-studio`
- `npm run test:persistence`
- `npm run test:regression`
- `npx tsc -b`
- `npm run build:modeling`
- `npm run build`

### Manual QA results
Manual browser QA was not run in this pass. Static validation confirms the required real predictive step components are imported and mounted inside Credit Risk Studio with credit-risk overlays. Build validation confirms the integrated page compiles.

### Clean-copy sync confirmation
`npm run sync:atlas` succeeded after rerunning with elevated permissions because the normal sync hit destination Access Denied errors. Clean copy validation passed:
- `npm run test:credit-risk-studio`
- `npm run build`

### Known limitations
The real predictive step pages are currently embedded as full page components inside Credit Risk Studio. A cleaner next build should extract each predictive step into shared embeddable workbench components so Credit Risk Studio can mount the same functionality without nested page chrome.

### Recommended next build
Refactor Predictive Modeling steps into reusable `PredictiveStepWorkbench` components with shared state contracts. Credit Risk Studio should consume those workbenches directly, while the standalone `/stepXX` routes wrap the same workbenches in their normal page shells.

### Acceptance criteria
Credit Risk Studio uses real Predictive Modeling workflow functionality, Data Acquisition auto-detects bureau data, Credit Bureau Data Review is not a separate required main step, EDA is analytical, Outliers and Missing Values have working treatment controls through the real workflow pages, Feature Engineering contains WOE / IV and manual binning, Balance & Split uses HELOC split datasets, Model Training uses real model training controls, target leakage exclusions remain enforced, and the clean copy is synced and builds.

## Phase 15M Data Acquisition Formatting, Bureau Treatment Controls, and Outliers Fix

### Summary
Phase 15M fixes QA issues found during the HELOC walkthrough after Phase 15L. The work cleans up the real Data Acquisition layout, adds a persistent global bureau special-value treatment control, protects the embedded Outliers page with an in-page error boundary, strengthens Outliers and Missing Values treatment controls, and keeps leakage exclusions enforced in IV-based feature selection.

### Data Acquisition formatting fixes
The real Data Acquisition page now gives the Data Sampling area more room, puts Sampling Method and Sample Detail on one clean row, moves explanatory sampling text below the controls, and keeps Target Variable in a bordered panel. Profile cards, Variable Summary, Data Quality Report, Data Lineage, and Python Synchronization remain readable with less crowding.

### Bureau special value global treatment control
Credit Risk Studio now includes a global bureau special-value control above the treatment table. Users can apply `Create special bin`, `Create indicator and impute`, `Convert to missing`, `Preserve raw special value`, or `Review manually` to all visible rows, or only to `-7`, `-8`, or `-9`. The global rationale is persisted with the selected treatment decisions.

### Outliers blank page fix
Embedded predictive steps are wrapped in an in-page error boundary. If the embedded Outliers workflow fails to load, Credit Risk Studio now shows: `Unable to load Outliers step. Refresh dataset schema or open full Predictive Modeling Outliers page.` The Outliers overlay also shows active dataset, global/per-variable treatment controls, HELOC bureau-special warning, reviewer notes, evidence save, and continue controls.

### Missing Values treatment controls
Missing Values now layers credit-risk controls over the real Predictive Modeling Missing Values workflow: global treatment, per-variable treatment, no treatment, imputation options, missing indicator, special bin, drop variable, drop rows, review manually, reviewer notes, save evidence, and continue. HELOC `-7`, `-8`, and `-9` remain separated from ordinary null missingness.

### EDA evidence readiness
EDA overlays now explicitly include feature relationship/correlation to target, histogram, box plot, dataset profile, missingness snapshot, correlation heatmap, pairwise plots, candidate predictor ranking, leakage warnings, Save EDA Evidence, Confirm EDA and Continue, Analytics Workbench, and Chart Studio.

### Target leakage protection
The real Data Acquisition Variable Summary disables predictor selection for `RiskPerformance`, `bad_flag`, and `atlas_split`. Those fields are labeled as `Original Target Label / Excluded`, `Target / Excluded`, and `Split Indicator / Excluded`, and are removed from selected modeling columns.

### Tests run
- `npm run test:credit-risk-studio`
- `npm run test:evidence-graph`
- `npm run test:model-documentation`
- `npm run test:model-diagnostics`
- `npm run test:dataset-library`
- `npm run test:notebook-studio`
- `npm run test:sql-data-studio`
- `npm run test:analytics-workbench`
- `npm run test:chart-studio`
- `npm run test:persistence`
- `npm run test:regression`
- `npx tsc -b`
- `npm run build:modeling`
- `npm run build`

### Manual QA results
Manual browser QA was not run in this pass. Static validation confirms the layout controls, special-value global treatment controls, Outliers fallback, EDA evidence controls, Missing Values controls, and leakage exclusions are wired. Build validation confirms the integrated page compiles.

### Clean-copy sync confirmation
`npm run sync:atlas` succeeded after rerunning with elevated permissions because the normal sync hit destination Access Denied errors. Clean copy validation passed:
- `npm run test:credit-risk-studio`
- `npm run build`

### Known limitations
The global bureau treatment decision is persisted in browser storage for the current studio session. A future backend-backed evidence object should store the exact selected treatment matrix with evidence records.

### Recommended next build
Extract shared embeddable predictive workbench components from the full step pages so Credit Risk Studio can avoid nested page chrome while still using the same engines, tables, and controls.

### Acceptance criteria
Data Acquisition formatting is clean, IV-based feature selection still works, bureau special values have a global treatment control, global treatment can be applied to all special-value rows, Outliers no longer renders blank and survives direct URL/refresh through an in-page fallback, Outliers and Missing Values expose working treatment controls, target leakage protections remain enforced, and the clean copy is synced and builds.
## Phase 15N Credit Risk Studio True Wrapper and Outliers Runtime Fix

### Summary

Phase 15N tightens Credit Risk Studio into a true specialized wrapper around the Predictive Modeling workflow. Embedded Predictive Modeling steps now stay inside `/credit-risk-studio?step=<step-name>` when their normal step controls advance the workflow, and the full Predictive Modeling route is available only as an explicit secondary action.

### Why the Prior Implementation Was Still Routing Incorrectly

The studio mounted real Predictive Modeling step components, but those components still used their normal `StepShell` next routes such as `/step05`. When clicked inside Credit Risk Studio, the user could leave the underwriting wrapper and land in the generic Predictive Modeling flow.

### Credit Risk Studio True Wrapper Behavior

- Added a Credit Risk Studio route-preservation guard in `StepShell`.
- Normal step routes such as `/step03`, `/step04`, `/step05`, `/step07`, `/step08`, and `/step09` are translated to `/credit-risk-studio?step=outliers`, `/credit-risk-studio?step=missing-values`, `/credit-risk-studio?step=feature-engineering`, `/credit-risk-studio?step=model-training`, `/credit-risk-studio?step=evaluation`, and `/credit-risk-studio?step=interpretation` when the current page is Credit Risk Studio.
- `Open in full Predictive Modeling` remains available as an explicit secondary link in each embedded real-step wrapper.

### Embedded Predictive Modeling Components

The studio continues to mount the real Predictive Modeling components for data acquisition, EDA, outliers, missing values, feature engineering, balance/split, model training, evaluation, interpretation, scoring, documentation review, implementation, and monitoring.

### Credit-Risk Overlays

Credit-risk overlays remain visible around the real workflow components, including:

- WOE / IV, manual characteristic binning, special bureau value binning, excluded-feature rationale, and transformation evidence in Feature Engineering.
- Traditional scorecard, AI/ML challenger, compare-both workflow, WOE variables, PDO settings, and scorecard status in Model Training.
- AUC, KS, Gini, lift, bad-rate by decile, TRAIN / TEST / OOT comparison, and cutoff strategy in Evaluation.
- Scorecard points, WOE directionality, reason-code candidates, adverse action mapping, and SHAP / surrogate explanation hooks in Interpretation.

### Outliers Blank Screen Fix

- Added a local embedded-step error boundary fallback for Credit Risk Studio.
- The fallback displays: `Unable to load this Credit Risk Studio step. The step failed while rendering the embedded Predictive Modeling component.`
- Fallback actions include Retry, Refresh Dataset Schema, and Open in full Predictive Modeling.
- The Outliers overlay includes HELOC-specific controls and warnings for no treatment, cap / winsorize, create special bin, exclude from model, review manually, global treatment, per-variable treatment, Save Outlier Evidence, and Confirm Outliers and Continue.

### Feature Engineering Row Preview Fix

- Feature Engineering now defaults to `Preview first 10 rows`.
- Added a row-count selector for 10, 25, 50, and 100 rows.
- The displayed row count is sliced from the transformed preview so the label and actual row count match.

### Sensitivity Analysis Fix

- Final Model Sensitivity Analysis now evaluates `-20%` and `+20%` scenarios for numeric features and selects the largest absolute prediction delta.
- The table now shows negative scenario prediction, positive scenario prediction, baseline prediction, largest scenario, delta, direction, relative impact, and direction explanation.
- Bureau special values `-7`, `-8`, and `-9` are preserved during percentage perturbation.
- Rows with bureau special values display: `Sensitivity analysis excludes special bureau values from percentage perturbation. Special values require separate bin-level or reason-code review.`

### HELOC State Protection

The HELOC test run remains anchored to:

- Project: `HELOC Traditional Scorecard Test Run`
- Dataset: `HELOC_TRAIN`
- Validation dataset: `HELOC_TEST`
- OOT dataset: `HELOC_OOT`
- Target: `bad_flag`
- Event value: `1`
- Original label: `RiskPerformance`
- Split column: `atlas_split`
- OOT type: `Synthetic holdout`

### Target Leakage Protection

The following exclusions remain enforced for predictor candidates, WOE / IV variables, scorecard variables, AI/ML variables, sensitivity features, and scoring inputs:

- `RiskPerformance` = Original Target Label / Excluded
- `bad_flag` = Target / Excluded
- `atlas_split` = Split Indicator / Excluded

### Tests Run

- `npm run test:credit-risk-studio` - passed
- `npm run test:evidence-graph` - passed
- `npm run test:model-documentation` - passed
- `npm run test:model-diagnostics` - passed
- `npm run test:dataset-library` - passed
- `npm run test:notebook-studio` - passed
- `npm run test:sql-data-studio` - passed
- `npm run test:analytics-workbench` - passed
- `npm run test:chart-studio` - passed
- `npm run test:persistence` - passed
- `npm run test:regression` - passed
- `npx tsc -b` - passed
- `npm run build:modeling` - passed
- `npm run build` - passed

### Manual QA Results

Manual browser QA was run against `http://127.0.0.1:5174` after signing in with the local development admin account.

- `/credit-risk-studio` opened successfully and showed Credit Risk Studio content, `HELOC_TRAIN`, `bad_flag`, and the explicit `Open in full Predictive Modeling` action.
- `/credit-risk-studio?step=feature-engineering` stayed inside Credit Risk Studio and did not route to `/step05`.
- Feature Engineering showed the real embedded Predictive Modeling step plus WOE / IV, manual characteristic binning, and special bureau value binning overlays.
- Feature Engineering displayed `Preview first 10 rows` and the scoped preview table rendered exactly 10 rows.
- `/credit-risk-studio?step=outliers` loaded directly, stayed inside Credit Risk Studio, rendered nonblank content, and showed the bureau special value warning.
- Refreshing `/credit-risk-studio?step=outliers` kept the route in Credit Risk Studio and rendered the Outliers content again.
- Outliers showed no treatment, cap / winsorize, create special bin, exclude from model, review manually, Save Outlier Evidence, and Confirm Outliers and Continue.
- `/credit-risk-studio?step=model-training` stayed inside Credit Risk Studio and showed real model training controls with Traditional Scorecard, AI/ML Underwriting Challenger, and PDO tooling.
- `/credit-risk-studio?step=interpretation` stayed inside Credit Risk Studio and showed the real Interpretation workflow, Final Model Sensitivity Analysis, leakage-exclusion messaging, and adverse action mapping overlay.

The active browser state did not have final sensitivity rows loaded, so the richer negative/positive/baseline sensitivity columns were validated by static/API tests rather than visible-row browser QA in this run.

### Clean-Copy Sync Confirmation

- Initial `npm run sync:atlas` failed with Windows destination access-denied errors.
- Elevated `npm run sync:atlas` passed.
- Clean-copy `npm run test:credit-risk-studio` passed.
- Clean-copy `npm run build` passed.

### Known Limitations

- The embedded Predictive Modeling components still own their internal local state and backend fetch behavior.
- The error boundary catches render failures; asynchronous data-load failures must still be handled inside each embedded step.
- Full browser QA remains necessary to verify direct refresh behavior for `/credit-risk-studio?step=outliers` in the active local runtime.

### Recommended Next Build

Add first-class `creditRiskMode` props to each Predictive Modeling step so embedded steps can receive explicit project, dataset, target, split, and solution-pack context instead of relying on shared workflow/browser state.

### Acceptance Criteria

- Credit Risk Studio no longer routes to normal workflow pages unless the user explicitly clicks Open in full Predictive Modeling.
- Feature Engineering stays inside `/credit-risk-studio?step=feature-engineering`.
- Outliers has a local fallback instead of a blank gray screen.
- Feature Engineering preview defaults to 10 rows with matching label.
- Sensitivity analysis clearly explains `-20%` / `+20%` scenario selection and preserves bureau special values.
- Credit-risk overlays remain visible inside real Predictive Modeling steps.
- HELOC state and target leakage protections remain enforced.

## Phase 15O Data Acquisition Page Cleanup

### Summary

Phase 15O narrows the Credit Risk Studio Data Acquisition work to layout, state placement, and duplicate-control removal. The Credit Risk Studio wrapper now embeds the real ATLAS Data Acquisition workflow without re-rendering its own role/target form below the step. The embedded page owns the canonical summary, source selection, dataset role assignment, target setup, sampling controls, quality report, variable selection, lineage, and Python sync sequence.

### Data Acquisition Order

The redesigned page renders the Data Acquisition content in this order:

1. Current Project Summary
2. Source Selection and File Upload
3. Dataset Role Assignment
4. Target Setup
5. Sampling and Profiling Controls
6. Full Data Quality Report
7. Variable Summary / Feature Selection
8. Data Lineage and Python Sync
9. Evidence and continue actions from the Credit Risk Studio wrapper

### HELOC Defaults

The Current Project Summary and setup panels preserve these HELOC defaults:

- Project: `HELOC Risk Model TEST`
- Training dataset: `HELOC_TRAIN`
- Validation dataset: `HELOC_TEST`
- OOT dataset: `HELOC_OOT`
- Target: `bad_flag = 1`
- Model purpose: `Application Underwriting`
- Product type: `Credit Card`
- Original target label: `RiskPerformance`
- Split column: `atlas_split`
- OOT type: `Synthetic holdout`

### UI Corrections

- Source cards are near the top and `Upload File` is selected by default.
- `Choose File` now appears directly beneath Source Selection and File Upload.
- Advanced SQL, cloud, existing-dataset, and Python source options are collapsed by default.
- Dataset role controls appear once: Training Dataset, Validation Dataset, OOT Dataset, OOT Type, Dataset Source Type, Dataset Purpose.
- Target setup controls appear once: Target Column, Event / Bad Value, Non-event / Good Value, Original Target Label Column, Split Column.
- `RiskPerformance`, `bad_flag`, and `atlas_split` receive explicit leakage warnings.
- Sampling controls use one row: Sampling Method, Sample Detail, Profile Rows, with explanatory text below the row.
- The full data quality report is collapsed by default and includes dataset version, hash, duplicate rows, memory estimate, highest missing fields, potential leakage, constant columns, near-zero variance, high-cardinality categoricals, and date ranges.
- Variable Summary now doubles as Feature Selection and includes Keep, Column, Role, Type, IV / Corr(Target), Missing %, Distinct, Mean, Min, Max, Leakage status, and Reason.
- Protected fields are disabled and excluded; eligible bureau features remain selectable.
- Data Lineage and Python Sync appear after Variable Summary, with Python Synchronization collapsed by default.
- The Credit Risk Studio Data Acquisition wrapper bottom actions are limited to Open Dataset Library, Refresh Dataset Schema, Save Data Acquisition Evidence, and Confirm Data Acquisition and Continue.

### Tests Run

- `npm run test:credit-risk-studio` - passed
- `npm run test:dataset-library` - passed
- `npm run test:persistence` - passed
- `npm run test:regression` - passed
- `npx tsc -b` - passed
- `npm run build:modeling` - passed with existing browsers-data and chunk-size warnings
- `npm run build` - passed with existing browsers-data and chunk-size warnings

### Manual QA Results

Manual browser QA was run against `http://127.0.0.1:5174/credit-risk-studio?step=data-acquisition`.

- The page opened inside Credit Risk Studio and stayed on `/credit-risk-studio?step=data-acquisition`.
- Current Project Summary appeared before Source Selection and File Upload.
- `Upload File` was selected by default and `Choose File` appeared directly beneath the source cards.
- Dataset Role Assignment, Target Setup, Sampling and Profiling Controls, Full Data Quality Report, Variable Summary / Feature Selection, and Data Lineage and Python Sync appeared in the requested order.
- Advanced source options, Full Data Quality Report, and Python Synchronization were collapsed by default.
- Loading `HELOC_TRAIN` from Existing Dataset selected `bad_flag` as the target and showed a binary target profile.
- Full Data Quality Report displayed dataset version, hash, duplicate rows, memory estimate, highest missing fields, potential leakage, constant columns, near-zero variance, high-cardinality categoricals, and date ranges after expansion.
- Variable Summary / Feature Selection rendered the protected `RiskPerformance`, `bad_flag`, and `atlas_split` rows as disabled and excluded.
- `ExternalRiskEstimate` remained enabled; it was toggled off and back on successfully.
- No duplicate role/target controls appeared after Variable Summary.
- Bottom Data Acquisition wrapper actions appeared once each: Open Dataset Library, Refresh Dataset Schema, Save Data Acquisition Evidence, Confirm Data Acquisition and Continue.

### Clean-Copy Sync Confirmation

- Initial `npm run sync:atlas` failed with Windows destination access-denied errors.
- Elevated `npm run sync:atlas` passed.
- Clean-copy `npm run test:credit-risk-studio` passed.
- Clean-copy `npm run build` passed with existing browsers-data and chunk-size warnings.

### Known Limitations

- StepShell still owns its generic Predictive Modeling step-completion footer inside the embedded workflow.
- Data Preview remains available in the real Data Acquisition step because downstream Predictive Modeling workflows still rely on preview and profile feedback.
- The wrapper does not duplicate Data Acquisition controls; Population and Target controls remain available only in their own non-Data-Acquisition wrapper context.

### Acceptance Criteria

- Data Acquisition no longer repeats role/target/source controls after Variable Summary.
- Upload File is selected and file selection is visible near the top of the page.
- HELOC project, dataset, target, product, and purpose defaults are visible.
- Leakage fields are excluded and protected from predictor selection.
- Quality, lineage, and Python sync sections are ordered and collapsed where requested.
- The Credit Risk Studio wrapper uses the real Data Acquisition step and keeps only the four requested bottom actions.
