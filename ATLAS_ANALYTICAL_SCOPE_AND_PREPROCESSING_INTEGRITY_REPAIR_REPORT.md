# ATLAS Analytical Scope and Preprocessing Integrity Repair Report

## 1. Executive summary

This repair establishes backend-authoritative population semantics and separates preparation policy from fitted preprocessing state. The work is intentionally limited to analytical-scope integrity, duplicate governance, holdout isolation, preprocessing execution, sample-coverage disclosure, evidence lineage, and the minimal UI contract changes needed to display those facts. It is not a visual redesign and does not claim that the entire ATLAS platform is production-ready.

The acceptance fixture is the existing HELOC project `atlas-mrzpau4t`, dataset version `v_1785186305905_6bdb184b`, and Analysis Partition `analysis-partition-688c2184b4e9b8181946-r1`. Those identities and counts are verification evidence only; no HELOC identity or count is hard-coded into product logic.

## 2. Verified root causes

### Population and response scope

The durable Analysis Partition was already authoritative for 6,275 registered rows, 5,020 Development Population rows, and 1,255 sealed final-holdout rows. The primary mismatch was introduced downstream: EDA response adaptation labeled every workspace response `development_population` but assigned the generic `row_count` from a full registered structural frame. The frontend scope badge then rendered that invalid pair literally.

Several mixed-scope EDA payloads also exposed one undifferentiated compatibility scope even though their structural predictor statistics and target-directed statistics used different populations. A separate workspace-draft compatibility object could contradict an exact governed scope about immutable-version, evidence, and MDD eligibility.

### Duplicate metrics and decisions

Four independent duplicate calculations existed:

- Data Acquisition used a full-frame pandas duplicate count.
- Governed profiling used a separate grouped SQL calculation.
- EDA Overview used the registered authorized-predictor frame.
- Target, Findings, and documentation independently recomputed Development Population duplicates using predictors plus target.

The values were not necessarily mathematically inconsistent, but the product omitted comparison scope, comparison columns, duplicate unit, and keep semantics. Findings also exposed two writable decision authorities: the governed parent finding and a legacy duplicate decision control.

### Outlier and missing-value fitting

The preparation pages obtained the full registered source frame. Outlier thresholds and missing-value estimators were fitted from the passed full series, allowing sealed-holdout predictor values to influence parameters. The same routes could persist one full row-aligned processed frame, and split creation later preferred that processed frame.

Outlier counts mixed predictor cells with affected rows. A global IQR policy was inherited by numeric storage types without sufficient semantic eligibility. Missing-value application fitted statistics without the same special-value exclusions used by its preview. The zero-null path avoided materialization, but its response and UI could still present an inactive median as an active imputation value.

### CV, final fit, and holdout opening

The model pipeline fitted generic sklearn imputers within folds, but it did not execute the governed Outliers and Missing Values recipe within each fold. Moreover, the fold input could already be a globally fitted processed frame. Generic imputers ran regardless of an approved no-treatment decision. Candidate artifacts were fitted before lock, and Evaluation could consume holdout arrays materialized earlier by split creation.

### Legacy restoration and invalidation

Response adapters rewrote legacy preparation records to resemble current applications without proving their fit scope. Checkpoint restoration validated dataset identity but not preprocessing contract version, fit population, predictor-authorization revision, special-value policy, or holdout parameter influence. Consequently, analytically unverifiable processed state could be restored as current.

The current HELOC checkpoint demonstrated this defect directly. Its outlier record had no preprocessing contract version, paired `scope=development_population` with `row_count=6275`, stored 5,464 changed predictor cells as `changed_values`, and carried the partition-creation Predictor Authorization while embedding a different current authorization. That record is not eligible to be grandfathered into the repaired contract.

### VIF and rendered samples

VIF correctly used a Development Population complete-case cohort and pairwise correlations correctly used pairwise-complete Development data, but the API did not fully disclose coverage, included/excluded event prevalence, exclusion reasons, preliminary status, or automatic-decision limitations. Rendered pairwise samples were bounded separately but lacked a consistently exposed deterministic sample signature.

### Known target source and Findings completion

`RiskPerformance` was known elsewhere as the deterministic source of `bad_flag`, but the current Predictor Authorization revision supplied to EDA had no target-source exclusion lineage. Browser-only language could therefore say no signal was detected. Findings blocker numbers were assembled independently in the frontend and backend from different mixtures of unresolved parents, missing fields, severe child evidence, and stale documentation.

## 3. Exact files changed

The repository was already dirty when this repair began. The following is the exact task-attributable source, test, acceptance, and report inventory; unrelated pre-existing edits and generated/runtime authorities were preserved and are not claimed as part of this repair.

Backend and shared contracts:

```text
scripts/run_security_tests.py
server/analysis_partition/service.py
server/core/dataset_state_keys.py
server/core/dataset_store.py
server/core/metadata_router.py
server/core/population_contract.py
server/core/session_checkpoint.py
server/eda/analytical_contract.py
server/eda/documentation_service.py
server/eda/documentation_types.py
server/eda/workspace_service.py
server/evaluation/eval_router.py
server/evaluation/eval_service.py
server/model_registry/model_registry_service.py
server/preprocessing/development_scope.py
server/preprocessing/execution_contract.py
server/preprocessing/feature_profile_service.py
server/preprocessing/governed_profile_service.py
server/preprocessing/missing_router.py
server/preprocessing/outlier_router.py
server/preprocessing/outlier_service.py
server/preprocessing/predictor_authorization.py
server/preprocessing/preparation_documentation_router.py
server/preprocessing/preprocessing_contract.py
server/preprocessing/quality_profile_service.py
server/scoring_runs/scoring_run_service.py
server/scoring_runs/treatment_replay.py
server/splitting/split_router.py
server/splitting/split_service.py
server/training/candidate_contract.py
server/training/trainer.py
server/training/trainer_router.py
server/training/trainer_service.py
server/training/training_job_service.py
server/training/training_preflight_service.py
```

Frontend contracts and minimal presentation changes:

```text
src/components/documentation/PreparationDocumentationLiveLink.tsx
src/components/eda/FindingsDecisionWorkspace.tsx
src/components/eda/TargetIntelligenceWorkspace.tsx
src/components/eda/visual/VifExplorer.tsx
src/components/eda/visual/predictorVisualData.ts
src/lib/dataAcquisitionEdaHandoff.ts
src/lib/dataScope.ts
src/lib/edaDocumentationApi.ts
src/lib/edaDocumentationPayload.ts
src/lib/edaFindingGovernance.ts
src/lib/edaFindings.ts
src/lib/enterpriseDataAccess.ts
src/lib/experimentTracking.ts
src/lib/governanceReport.ts
src/lib/modelDevelopmentDocument.ts
src/lib/outlierPremium.ts
src/lib/preparationGovernance.ts
src/lib/vifSimulatorSelection.ts
src/steps/Step01_DataAcquisition.tsx
src/steps/Step02_EDA.tsx
src/steps/Step04_MissingValues.tsx
src/steps/Step04_Outliers.tsx
src/steps/Step06_Train.tsx
```

Behavioral tests and focused acceptance:

```text
tests/analysis_partition_fixture.py
tests/analytical_scope_preprocessing_integrity_test.py
tests/canonical_dataset_identity_test.py
tests/dataAcquisitionFinalAcceptanceRepair.test.mjs
tests/e2e/analytical-scope-preprocessing-integrity-isolated.spec.ts
tests/edaAnalyticalScopeLabels.test.mjs
tests/edaFindingsGovernance.test.mjs
tests/eda_governed_analytical_contract_test.py
tests/eda_governed_completion_test.py
tests/eda_http_transport_contract_test.py
tests/eda_phase1_predictor_authorization_test.py
tests/eda_population_contract_test.py
tests/evaluation_exact_lineage_test.py
tests/exact_registry_scoring_contract_test.py
tests/external_scoring_treatment_replay_test.py
tests/holdoutIsolationFrontend.test.mjs
tests/missing_table_first_backend_test.py
tests/model_registry_durability_test.py
tests/model_training_preflight_authority_test.py
tests/preparationPremiumWorkflow.test.mjs
tests/preparationTableFirstContract.test.mjs
tests/preparationWorkflowCorrections.test.mjs
tests/preparation_premium_backend_test.py
tests/preparation_table_first_backend_contract_test.py
tests/preprocessing_development_scope_test.py
tests/preprocessing_v2_contract_test.py
tests/pretraining_artifact_invalidation_test.py
tests/targetIntelligence.test.mjs
tests/training_holdout_isolation_test.py
tests/training_job_scope_identity_test.py
tests/training_validation_policy_execution_test.py
tests/vifResolutionPlan.test.mjs
tests/vifSimulatorSelectionState.test.mjs
tests/vif_resolution_plan_test.py
```

Deliverable:

```text
ATLAS_ANALYTICAL_SCOPE_AND_PREPROCESSING_INTEGRITY_REPAIR_REPORT.md
```

## 4. Canonical population/count contract before and after

Before the repair, `scope`, `row_count`, full-population counts, Development counts, fit counts, and rendered counts were assembled in ad hoc dictionaries. A payload could state `scope=development_population` while carrying the registered population row count.

After the repair, one shared contract binds identity, population counts, named analytical scopes, purpose-specific holdout truth, and compatibility aliases. A generic `row_count` is derived only from the response's primary scope. Mixed-scope responses identify each sub-scope explicitly and cannot represent full structural results as Development Population results.

The contract distinguishes registered, Development, sealed holdout, analysis, fit, application, and rendered sample row counts. It also distinguishes descriptive, target-directed, fit, application, materialization, and rendering scopes.

## 5. HELOC population reconciliation

| Governed population | Authoritative rows | Identity/source |
|---|---:|---|
| Registered Population | 6,275 | Analysis Partition `population_count` |
| Development Population | 5,020 | `development-688c2184b4e9b8181946-r1` |
| Sealed Final Holdout | 1,255 | `sealed-holdout-688c2184b4e9b8181946-r1` |

The 80/20 role assignment is durable. Target-directed EDA and preparation previews use the 5,020-row Development Population. Registered-population predictor-only structural profiling may include holdout predictor values only when labeled structural; the holdout target remains sealed and those predictor values do not influence fitted parameters, recommendations, feature selection, VIF disposition, tuning, or candidate choice.

## 6. Duplicate-count reconciliation

The repaired duplicate contract reports duplicate groups, participant rows, redundant rows beyond the retained occurrence, unique rows after exact deduplication, valid-target and target-missing duplicate rows, comparison columns, target inclusion, population scope, and keep semantics.

| Previously displayed value | Actual source and definition | Correct interpretation |
|---:|---|---|
| 351 | Registered structural source comparison; 25 comparison columns; target excluded; `keep=first` | 351 redundant rows across 3 duplicate groups; 354 participant rows; 5,924 unique rows after exact deduplication |
| 352 | Registered authorized-predictor structural comparison; 23 comparison columns; target excluded; `keep=first` | 352 redundant rows across 2 predictor-profile groups; 354 participant rows; 5,923 unique predictor profiles |
| 279 | Development Population target-directed comparison; 23 authorized predictors plus `bad_flag` (24 columns); target included; `keep=first` | 279 redundant target-bearing rows across 3 groups; 282 participant rows; 4,741 unique rows after exact deduplication; all 282 participant rows have a valid target and 0 are target-missing |

For completeness, the same Development Population compared on authorized predictors without the target contains 280 redundant rows across 2 predictor-profile groups. These figures differ because the comparison population and comparison schema differ; they are no longer presented as interchangeable.

## 7. Outlier fit/application architecture

Before: the selected policy and its fitted parameters were conflated. Page preview and application could fit on the registered frame and materialize a full processed frame.

After: the approved policy is versioned independently. Page thresholds and decision metrics are a Development-only preview artifact. CV fits a fresh artifact per training fold. After candidate lock, the final artifact is fitted once on the complete Development Population and applied unchanged at the authorized final-reporting, TEST, OOT, or scoring boundary. Governed special values and true nulls are excluded from ordinary-value fitting and preserved during application unless an exact approved policy says otherwise.

## 8. Missing-value fit/application architecture

Before: mean, median, and mode could be fitted on the full preparation frame, and preview/application special-value handling differed.

After: the approved missing-value strategy is a recipe. Estimated values are fit only from ordinary observed values in the authorized fitting population. Fold artifacts are fold-local; the final artifact is Development-fitted. Only true-null cells are filled. If no ordinary value exists for an estimated strategy, execution fails closed. Constant treatment remains configuration-driven.

For the zero-null HELOC fixture, active treatment is `NONE`, materialization is not required, no processed frame is created, and no generic imputer is fitted. Reference medians/modes remain inactive planning statistics and are not labeled imputed values.

The fixture contains 0 true-null cells and 15,324 governed `-7`/`-8`/`-9` special-value cells across 22 predictors covered by exact governed special-value lineage. The latter is a predictor-cell count, not a row or observation count. `ExternalRiskEstimate` remains an authorized predictor, but its 357 reserved `-9` sentinel cells are not silently added to the governed-special disclosure because that feature/value pair is absent from the exact special-value review. Those sentinels are nevertheless protected from outlier and imputation fitting through the separate `protected_sentinel_excluded_count` contract.

## 9. CV fold-local preprocessing implementation

The training path consumes an exact governed recipe and never treats a preparation-page preview or globally fitted processed frame as CV input. For every fold, it selects the fold-training rows, fits approved outlier and missing parameters only on those rows, applies the frozen values to validation rows, and fits encoding/scaling on the same fold-training rows. Fold lineage includes recipe revision, train/validation identity and counts, fitted parameters, excluded null/special counts, checksum, and explicit zero validation-fold parameter influence.

## 10. Final Development fit and holdout application

Candidate lock triggers a final preprocessing fit on the complete Development Population and links that immutable fitted artifact to the selected model version. The sealed holdout is not transformed or materialized before lock. Evaluation opens it only for final reporting and applies the fixed Development-fitted artifact without refitting.

## 11. Analytical-type and outlier-eligibility rules

The policy distinguishes continuous numeric, count, bounded percentage/rate, ordinal code, binary, constant, identifier, bureau-special-coded numeric, and unknown/review-required variables. Binary, constant, and identifier fields are ineligible. Ordinal and unknown low-cardinality integer fields do not inherit global clipping. Bounded rates honor authoritative bounds. Global IQR applies only where governed metadata supports eligibility. An otherwise-ineligible override requires feature-level rationale and authoritative semantic support.

## 12. VIF and pairwise sample coverage

VIF now reports the Development denominator, exact eligible/excluded rows, coverage rate, included/excluded event counts and rates, true-null and special-value exclusions, calculation stage, preliminary/final status, coverage warning, and model-family relevance. Low-coverage VIF cannot be the sole authority for automatic exclusion; final VIF is required on the approved post-treatment design matrix.

For the current fixture, the raw complete-case VIF cohort is 1,214 of 5,020 Development rows (24.1833%; 3,806 excluded). The reviewed pair with 2,407 eligible rows covers 47.9482% of Development (2,613 excluded). Both limitations are material and are disclosed explicitly.

Correlation pairs expose pairwise eligible rows, coverage, excluded rows, method, and available stability metadata. Analytical eligible rows and rendered rows are separate fields, and bounded rendering carries its deterministic sampling method and signature.

## 13. RiskPerformance target-source lineage

The repaired lineage distinguishes a known deterministic source excluded upstream from the absence of additional suspected leakage among authorized predictors. `RiskPerformance` remains excluded from authorization, EDA predictor analysis, VIF, feature engineering, model-ready manifests, training, and scoring inputs. The platform does not rediscover it by opening sealed-holdout targets.

## 14. Findings authority and completion contract

The exact-duplicate parent finding is the only writable duplicate authority. Historical legacy state is retained for audit as a read-only compatibility record. Retain may be recorded with rationale. Exclude is a governed population-membership change and therefore blocks downstream execution until Data Acquisition creates a revised population and new Analysis Partition; EDA itself never deletes rows.

One backend completion contract distinguishes unresolved required parents, missing fields, severe child evidence, stale documentation, actual workflow completion blockers, accepted-with-conditions status, and completion eligibility. Frontend completion indicators consume that same contract.

## 15. Legacy artifacts and downstream invalidation

Preparation records that lack preprocessing contract version 2 or required fit lineage remain preserved as history but are classified stale with `legacy_preprocessing_fit_scope_unverified`. They are not rewritten to appear compliant. Dependent processed frames are quarantined/ignored and downstream split, training, candidate, Evaluation, interpretation, scoring, and MDD state is invalidated through the existing project-scoped mechanisms. Reconfirmation and recomputation are required.

## 16. Evidence and MDD changes

Preparation evidence and MDD payloads use the backend contract for registered, Development, holdout, fit, application, and rendered counts; purpose-specific holdout truth; duplicate definition/disposition; analytical eligibility; special-value exclusions; zero-null status; fold-local execution; final Development fit; actor, timestamp, revision, checksum, and upstream/downstream references. Browser planning preferences are labeled drafts and do not claim to be executed treatment history.

## 17. New and updated tests

New behavioral suites:

- `tests/analytical_scope_preprocessing_integrity_test.py` covers canonical population invariants, canonical duplicate groups/participants/redundant rows, sealed-partition duplicate policy, target-source lineage, and completion authority.
- `tests/eda_population_contract_test.py` covers 100/80/20 mixed-scope EDA, holdout-target perturbation invariance, VIF denominator/coverage, and pairwise/rendered-sample separation.
- `tests/preprocessing_v2_contract_test.py` covers outlier and missing holdout poisoning, special/null preservation, analytical-type eligibility, fold-local fitting, zero-null no-op behavior, final Development fit, fixed holdout application, and legacy artifact staleness.
- `tests/vifSimulatorSelectionState.test.mjs` covers simulator isolation from generic EDA selection, material/review defaults, explicit VIF-row selection, and non-mutation.
- `tests/exact_registry_scoring_contract_test.py` and `tests/external_scoring_treatment_replay_test.py` cover final-fitted artifact linkage and fixed TEST/OOT/scoring replay.
- `tests/e2e/analytical-scope-preprocessing-integrity-isolated.spec.ts` is the focused browser proof.

Existing suites were updated to use exact Analysis Partition identities and contract-v2 fixtures instead of treating legacy full-frame preparation as valid. This includes the named Development-scope, training-isolation, validation-policy, Missing Values, preparation, governed EDA, Findings, VIF, Evaluation lineage, registry, preflight, training-job, invalidation, and frontend contract suites listed in section 3.

Two obsolete sentinel assertions were repaired rather than weakened: reserved bureau sentinels are asserted under `protected_sentinel_excluded_count`, while `special_value_count` requires exact governed feature/value lineage. The table-first synthetic fixture now supplies that lineage explicitly when its expected governed-special count is three.

## 18. Commands run and results

Final successful gates:

| Command | Final result |
|---|---|
| `npm run test:analysis-scope` | PASS: 15 frontend tests and 33 backend tests |
| `npm run test:preparation-premium` | PASS: 13 premium frontend tests, 10 table-first frontend tests, 15 premium backend tests, and 8 table-first/Missing backend tests |
| `node tests/edaAnalyticalScopeLabels.test.mjs` | PASS: 5 tests |
| `node tests/edaDevelopmentContext.test.mjs` | PASS |
| `node tests/edaFindingsGovernance.test.mjs` | PASS: 10 tests |
| `node tests/holdoutIsolationFrontend.test.mjs` | PASS |
| `node tests/vifSimulatorSelectionState.test.mjs` | PASS: 4 tests |
| `.\.venv\Scripts\python.exe -m pytest tests/preprocessing_development_scope_test.py tests/training_holdout_isolation_test.py tests/training_validation_policy_execution_test.py tests/eda_governed_analytical_contract_test.py tests/eda_findings_documentation_contract_test.py tests/vif_resolution_plan_test.py tests/analytical_scope_preprocessing_integrity_test.py tests/eda_population_contract_test.py tests/preprocessing_v2_contract_test.py -q` | PASS: 82 tests and 2 subtests |
| `.\.venv\Scripts\python.exe -m pytest tests/canonical_dataset_identity_test.py tests/pretraining_artifact_invalidation_test.py tests/evaluation_exact_lineage_test.py tests/exact_registry_scoring_contract_test.py tests/external_scoring_treatment_replay_test.py tests/model_registry_durability_test.py tests/model_training_preflight_authority_test.py tests/training_job_scope_identity_test.py tests/checkpoint_lifecycle_test.py tests/dataset_identity_checkpoint_clear_test.py -q` | PASS: 146 tests and 7 subtests; run with isolated OS-temp authorities outside the repository |
| `.\.venv\Scripts\python.exe scripts\run_security_tests.py` | PASS: 7 behavioral security tests and 1 structural security gate |
| `.\.venv\Scripts\python.exe scripts\check_test_storage_isolation.py` | PASS: 135 Python test sources inspected |
| `.\.venv\Scripts\python.exe tests\test_storage_isolation_guard_test.py` | PASS: 24 tests |
| `npm run build` | PASS: TypeScript project build plus Vite production build; 3,451 modules transformed and built in 34.48 seconds |
| `.\.venv\Scripts\python.exe -m compileall -q server` | PASS |
| `git diff --check` | PASS; line-ending notices only |

Verification reruns are recorded rather than omitted:

- A first parallel aggregate accidentally invoked the stateful `analysis_scope_test.py` both through `npm run test:analysis-scope` and through a second pytest process. The standalone command passed, while the duplicate concurrent invocation produced recovery-journal collisions. The aggregate also exposed the obsolete sentinel assertion described in section 17. The assertion/fixture was corrected and all suites were rerun serially.
- The first sandboxed persistence/checkpoint aggregate could not create isolated SQLite/backup files in the OS temp directory. Redirecting backups inside the workspace was then correctly rejected by ATLAS because a backup root may not physically overlap protected repository storage. The unchanged suite was rerun with external isolated OS-temp authority and passed 146 tests plus 7 subtests.
- The sandboxed Vite build initially failed to spawn a compiler subprocess (`EPERM`). The unchanged build was rerun with subprocess permission and passed.

The requested 17-hour whole-platform acceptance was not run.

## 19. Focused isolated browser acceptance

Command:

```text
.\.venv\Scripts\python.exe scripts\run_isolated_full_workflow_acceptance.py --spec analytical-scope-preprocessing-integrity-isolated.spec.ts --timeout-seconds 1200
```

Result: PASS, 1 Playwright test in approximately 1.8 minutes.

- Run ID: `atlas-hrt-20260812-025717-31a78f6915`
- Acceptance result: `C:\Users\james\AppData\Local\Temp\atlas-hrt-20260812-025717-31a78f6915\c\c42181775d\authorities\playwright-output\acceptance-result.json`
- Result SHA-256: `dc34aff4cb0547e3682bf673156cd78781f2ff16ccc3c8e487808938dc012045`
- Source hash before and after: `ae7d670583bb8bc03e4e8175fdaf5862afe6d0e97e2abc996ac40afb1f369aea` (identical)
- Live data opened: false
- Live services touched: false
- Live/unexpected origin or WebSocket contacts: 0
- Teardown: all owned ports closed and processes stopped

Screenshots, each visually inspected after the run:

```text
C:\Users\james\AppData\Local\Temp\atlas-hrt-20260812-025717-31a78f6915\c\c42181775d\authorities\playwright-output\artifacts\analytical-scope-preproces-aaadc--lock-preparation-isolation-isolated-chromium\01-data-acquisition-populations.png
C:\Users\james\AppData\Local\Temp\atlas-hrt-20260812-025717-31a78f6915\c\c42181775d\authorities\playwright-output\artifacts\analytical-scope-preproces-aaadc--lock-preparation-isolation-isolated-chromium\02-data-acquisition-duplicates.png
C:\Users\james\AppData\Local\Temp\atlas-hrt-20260812-025717-31a78f6915\c\c42181775d\authorities\playwright-output\artifacts\analytical-scope-preproces-aaadc--lock-preparation-isolation-isolated-chromium\03-target-lineage-and-leakage.png
C:\Users\james\AppData\Local\Temp\atlas-hrt-20260812-025717-31a78f6915\c\c42181775d\authorities\playwright-output\artifacts\analytical-scope-preproces-aaadc--lock-preparation-isolation-isolated-chromium\04-outlier-development-fit-and-count-units.png
C:\Users\james\AppData\Local\Temp\atlas-hrt-20260812-025717-31a78f6915\c\c42181775d\authorities\playwright-output\artifacts\analytical-scope-preproces-aaadc--lock-preparation-isolation-isolated-chromium\05-missing-zero-null-none-no-frame.png
C:\Users\james\AppData\Local\Temp\atlas-hrt-20260812-025717-31a78f6915\c\c42181775d\authorities\playwright-output\artifacts\analytical-scope-preproces-aaadc--lock-preparation-isolation-isolated-chromium\06-findings-single-duplicate-authority-repartition.png
```

The browser proved 6,275 registered / 5,020 Development / 1,255 sealed holdout; explicit duplicate scopes and units; RiskPerformance excluded upstream plus no additional authorized-predictor leakage candidates; Development-only outlier fit and cell/row separation; no pre-lock holdout materialization; 0 true nulls, active treatment None, no processed frame, and 15,324 governed special-value cells across 22 predictors; one writable duplicate disposition; fail-closed repartition recovery; and hard-reload persistence without resurrecting a legacy preparation artifact.

One final documentation-draft request was reset while the disposable backend was being torn down. It occurred after the assertions and screenshots, produced no browser/test failure, and did not contact a live authority.

## 20. Remaining risks and intentionally deferred work

The repair does not redesign workflow pages or introduce new visualizations. It does not replace every exploratory complete-case method; raw VIF therefore remains preliminary at 24.1833% coverage and must be repeated on the approved post-treatment design matrix before it can support an exclusion decision.

The focused browser acceptance intentionally stops at the scope/preparation/Findings proof requested for this task. Training, Evaluation, registry, and scoring lineage were verified behaviorally rather than by running the long end-to-end browser workflow. Broader platform production-readiness, unrelated workflows, and the 17-hour whole-platform acceptance remain outside this task.
