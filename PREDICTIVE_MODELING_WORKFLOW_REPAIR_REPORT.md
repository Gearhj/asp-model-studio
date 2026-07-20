# Predictive Modeling Workflow Repair Report

Date: 2026-07-12

## Scope And Workspace

All implementation work was completed in the source workspace:

`C:\Users\james\ds-workflow-starter`

The clean ATLAS copy was not edited directly. The final sync status is recorded at the end of this report.

## Root Causes And Repairs

| Issue | Root cause | Repair |
| --- | --- | --- |
| Preview settings changed modeling data | Preview-sampled rows were reused as the modeling and persistence payload | Separated full source rows, registered row count, preview rows, and profiling rows. Preview controls now affect presentation only. |
| Data quality claimed full coverage incorrectly | Browser profile rows were labeled as a full report and generic UI included HELOC fallbacks | Added a full-data backend quality service with explicit scope and removed generic HELOC, `RiskPerformance`, `bad_flag`, and `atlas_split` fallbacks. |
| Numeric values appeared as dates | Generic values were passed through date parsing without a schema or name gate | Numeric values are rejected before date parsing. Date ranges require date-like schema or names and recognized date strings. |
| Python synchronization was misleading | The shared panel exposed only Python and did not surface existing SAS runtime modes | Replaced it with the shared Python and SAS code workspace, honest SAS diagnostics, explicit compatibility mode, and saved SAS export support. |
| Generated Data Acquisition code was generic | Static `TRAIN.csv` and `target` notebook code ignored source provenance | Generated Python and SAS now use the actual source type. Dataset Library code includes dataset ID, version, name, target, and governed features. |
| EDA had no standard next action | EDA bypassed `StepShell` and rendered its own code panel | EDA now uses `StepShell`, completes `step02`, routes to `/step03`, and has one shared code panel. |
| Balance & Split lacked final feature governance | There was no shared full-data feature profile or final editable selected-column contract | Added shared feature profiling and a final predictor table with IV or correlation, locks, filters, bulk actions, and persisted selections. |
| Training remained Pending | The UI submitted one synchronous multi-model request and had no job state | Added background jobs, per-model status, polling, partial results, cancellation, refresh resume, and bounded workers. |
| Training controls overstated behavior | Calibration and parallelism were not fully applied, while PCA appeared available | Calibration is implemented, `max_parallel` is honored up to the safe local cap, and PCA is disabled and labeled planned. |
| Authenticated workflow actions failed in local cross-origin development | Several direct `fetch` calls omitted `credentials: "include"` | Added credentials to Balance & Split, training, evaluation, interpretation, scoring, and shared training-summary calls. |

## Files Created

- `server/preprocessing/data_profile_types.py`
- `server/preprocessing/quality_profile_service.py`
- `server/preprocessing/quality_profile_router.py`
- `server/preprocessing/feature_profile_service.py`
- `server/preprocessing/feature_profile_router.py`
- `server/training/training_job_types.py`
- `server/training/training_job_service.py`
- `src/lib/featureProfiling.ts`
- `tests/predictiveModelingRepair.test.mjs`
- `tests/predictive_modeling_repair_test.py`
- `PREDICTIVE_MODELING_WORKFLOW_REPAIR_REPORT.md`

## Files Modified For This Repair

- `package.json`
- `server/main.py`
- `server/core/metadata_router.py`
- `server/datasets/dataset_router.py`
- `server/training/trainer.py`
- `server/training/trainer_router.py`
- `server/training/trainer_service.py`
- `src/components/CopilotCard.tsx`
- `src/components/StepPythonPanel.tsx`
- `src/components/code/CodeLanguageTabs.tsx`
- `src/components/code/CodeWorkspacePanel.tsx`
- `src/lib/datasetLibrary.ts`
- `src/lib/decisionJournal.ts`
- `src/lib/enterpriseDataAccess.ts`
- `src/lib/localDataset.ts`
- `src/lib/notebookExport.ts`
- `src/steps/IntelligentWorkbench.tsx`
- `src/steps/Step01_DataAcquisition.tsx`
- `src/steps/Step02_EDA.tsx`
- `src/steps/Step06_BalancingSplit.tsx`
- `src/steps/Step06_Train.tsx`
- `src/steps/Step08_Evaluation.tsx`
- `src/steps/Step09_Interpretation.tsx`
- `src/steps/Step10_Scoring.tsx`
- `tests/creditRiskStudio.test.mjs`
- `tests/dataAcquisition.test.mjs`
- `tests/modelDiagnostics.test.mjs`
- `tests/python_execution_test.py`
- `tests/regression.test.mjs`

The worktree also contained pre-existing A/B Testing and Phase 1 platform changes. Those changes were preserved and not reverted.

## Data Acquisition

- `fullSourceRows` and the backend registered artifact remain the modeling population.
- `previewRows` controls only the visible table.
- `profilingRows` controls only browser fallback profiling.
- Backend-imported and Dataset Library assets are not replaced with cached preview rows.
- Dataset Library versions must contain `data_full.csv` before activation. Preview-only registrations are blocked honestly.
- The collapsed `Preview & Profiling Settings` section shows modeling, preview, and profile row counts.
- `Profile row limit` is an active numeric control.
- The page states that preview and profiling settings do not change the registered dataset.

## Data Quality And Readiness

`POST /api/data/quality-profile` profiles the full active `DatasetStore` dataframe and returns:

- Scope, profiled and registered row counts, generated time, version, and hash
- Missingness, duplicate rows, and duplicate ID candidates
- Constant and near-zero variance columns
- Cardinality and datatype findings
- Leakage candidates and outlier prevalence
- Target health and legitimate date ranges
- Memory estimate, warnings, and readiness status

Browser fallback output is labeled `Complete Browser Dataset` or `Preview Profile`. It is never labeled full when only preview rows are available.

## Python And SAS Reproducibility

- The shared panel exposes only configured languages, currently Python and SAS.
- Python remains executable through the governed Python endpoint.
- SASPy execution uses `/api/code/sas/run` only when diagnostics report an executable tested session.
- Local compatibility uses `/api/code/sas-compatible/run` only after explicit selection.
- Template and external export modes do not claim execution.
- Unsupported SAS statements are returned by the compatibility backend.
- User-edited Python and SAS persist and are preserved in notebook export.
- Data Acquisition code changes with file, SQL, cloud, Dataset Library, or Python-loader provenance.

## EDA Navigation

EDA now renders in the common workflow frame with:

- Title `Step 2: Exploratory Data Analysis`
- The required subtitle
- One code workspace
- A disabled reason when no valid dataset is loaded
- `Mark Complete & Next Step` that completes `step02` and routes to Outliers

## Final Predictor Review

`POST /api/data/feature-profile` uses the active full development dataframe.

Classification profiles use the explicit event definition, governed bins, missing bins, and smoothing for IV. Regression profiles use target correlation. Unsupported categorical regression association is labeled not evaluated.

Balance & Split now includes:

- Search and selected/eligible filters
- IV, missingness, predictor name, and type sorting
- Select all eligible, clear optional, restore selection, and weak-signal actions
- Descriptive statistics and signal strength
- Locked target, split, system, prohibited, and leakage rows
- A zero-predictor continuation guard

Selection changes update `LocalDataset.selected_columns`, dispatch the dataset event, update `/api/data/set_target`, invalidate splits and stale training summary, and write a Decision Journal entry.

## Training Job Architecture

The Model Training page now creates jobs with `POST /api/model/train/jobs`, polls `GET /api/model/train/jobs/{job_id}`, and cancels through `POST /api/model/train/jobs/{job_id}/cancel`.

The service provides:

- Immediate job creation
- Queued, Training, Complete, Failed, Cancelled, and Not selected states
- Per-model isolation and partial ranked results
- Bounded `ThreadPoolExecutor` execution
- Requested and honored parallelism
- Cancellation and refresh resume
- Exact trained feature names and feature count
- Standard persisted training summary for Evaluation

## Training Controls

- Calibration: implemented with `CalibratedClassifierCV` where supported and reported per result.
- Grid search: reports parameter grid, best score, and runtime.
- Parallel model jobs: honored with a local cap of 4.
- PCA: disabled and labeled `Planned. Not applied by the current backend.`
- Existing synchronous `/api/model/train`: retained for compatibility but the page uses job endpoints.

## Tests Added

`tests/predictiveModelingRepair.test.mjs` verifies the frontend and service contracts.

`tests/predictive_modeling_repair_test.py` verifies full-data quality, numeric date safety, IV, correlation, locked fields, immediate job creation, per-model completion/failure, parallelism, cancellation, and exact trained features.

## Validation Results

Passed:

- `npm run build`
- `npx tsc -b`
- Python `compileall` for `server`
- `npm run test:predictive-modeling-repair`
- `npm run test:project-types`
- `npm run test:open-project`
- `npm run test:persistence`
- `npm run test:workflow-navigation-state`
- `npm run test:regression`
- `npm run test:dataset-library`
- `npm run test:analytics-workbench`
- `npm run test:model-documentation`
- `npm run test:evidence-graph`
- `npm run test:credit-risk-studio`
- `npm run test:data-acquisition`
- `npm run test:python-execution`
- `npm run test:model-diagnostics`

No test failures remain. Build warnings are limited to existing outdated browser compatibility metadata and the existing large Vite chunk warning.

## Manual Workflow Results

Manual QA used the in-app browser and an isolated repaired stack on `http://127.0.0.1:5175` with FastAPI on port `8002`. Port `8001` was occupied by a stale external ATLAS process that did not expose the new endpoints, so it was not modified.

The walkthrough used a registered full 5,000-row binary fraud dataset with 31 columns and `Class` as target.
The temporary QA registration and its generated runtime files were removed after the walkthrough. Runtime artifacts were not synced to the clean copy.

Confirmed:

- Data Acquisition showed 5,000 registered and profiled rows with `Full Dataset` scope.
- Changing preview rows from 100 to 40 left modeling rows at 5,000.
- Numeric `Time` did not create a date range.
- No generic HELOC fallback values appeared.
- Full-data IV loaded and target `Class` remained locked.
- Python code included the actual Dataset Library ID, version, name, target, and selected features.
- SAS showed `Template Only`; SASPy was disabled because no executable SASPy session was configured.
- EDA displayed the standard next action and navigated to `/step03`.
- Balance & Split displayed full-data IV and statistics.
- Two predictors were deselected; the count persisted as 28 after page reload.
- Balance & Split saved successfully and navigated to Model Training.
- Model Training showed 28 features and two selected models.
- The background job completed 2 of 2 models with two honored workers.
- Final results reported 28 governed trained features and created experiment records.
- Evaluation loaded the completed leaderboard plus backend confusion and decile diagnostics.
- Browser console contained no warnings or errors after final reload.
- Final backend requests for training summary, curves, and deciles returned HTTP 200.

No mock metrics or dataset-specific generic fallbacks were introduced by this repair.

## Sync Confirmation

`npm run sync:atlas` completed successfully on 2026-07-12. Robocopy returned success code 3 with 81 files copied, zero failed files, and the configured runtime and environment exclusions preserved.
