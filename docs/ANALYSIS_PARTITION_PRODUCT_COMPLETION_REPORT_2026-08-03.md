# ATLAS Analysis Partition product-completion closeout report

Date: 2026-08-03  
Status: **NOT FULLY COMPLETE — implementation and every final automated gate passed, but operational acceptance is blocked by failed runtime isolation and concurrent live-authority changes**  
Runtime isolation: **FAILED BUT RECONCILED**  
Branch: `codex/phase2a-canonical-lineage`  
Inherited HEAD: `24961ad4da6566c53cf4634796a439f7498fcc0e`

## Executive disposition

The Analysis Partition product contract is implemented and the final frozen-code validation is green. Data Acquisition owns one durable pre-EDA development/final-holdout assignment; EDA target-aware work is development-only; Training and Validation Design inherits the assignment read-only; and training policy cannot redraw or expose the final holdout.

The overall phase is not unconditionally complete. During the final validation window, authenticated live UI/API activity changed protected HELOC runtime authorities. The Analysis Partition's immutable identity, revision, membership, seed, stratification, assignment checksum, population checksum, and artifact checksum did not change. Its documentation fields did change from unrecorded references to exact recorded evidence/MDD references, and the current feature manifest changed from 30 definitions to 28. The final restart also triggered normal live-browser rehydration writes to workflow state and the checkpoint. Those differences are attributed and preserved, but they mean runtime isolation did not pass and the live partition record was not byte/logically untouched.

No closeout test created the live 21:35–21:51 records: audit timestamps, exact owner identity, endpoint sequence, and redirected test roots attribute them to authenticated live Data Acquisition, Outliers, Missing Values, Feature Engineering, MDD, project-save, and checkpoint activity. The earlier full-population EDA/Target Intelligence artifacts remain a separate historical safeguard breach. Nothing was deleted, restored, normalized, or staged to conceal either fact.

## 1. Exact protected authority at final read-only verification

| Field | Final value |
|---|---|
| project_id | `atlas-mrzpau4t` |
| dataset_id | `ds_heloc_train_6bdb184b_05905` |
| dataset_version_id | `v_1785186305905_6bdb184b` |
| target | `bad_flag` |
| activation_revision | `1` |
| target_contract_id | `target-contract-9a0bbd69645b7e5e0b4c` |
| predictor_authorization_id | `predictor-auth-491392549aa93a6ad258` |
| analysis_partition_id | `analysis-partition-688c2184b4e9b8181946-r1` |
| revision | `1` |
| development / final holdout | `5,020 / 1,255` of `6,275` |
| design | `80/20`, deterministic, seed `42`, target-stratified on `bad_flag` |
| state | `current`, final holdout `sealed`, isolation `verified` |
| assignment checksum | `ed04b51eef3ebfccc846ff742203978ae0463ee871807c6045595b68106bb6c5` |
| population checksum | `0d81ad64bb8ac0b0314abb28a05b94c74e6dc97138ff05ddbb864440d081875a` |
| artifact checksum | `688c2184b4e9b8181946766e2577c1f1a53f9c88de2adf81a1d3affbc8dcd5fa` |
| evidence reference | `ev-analysis-partition-688c2184b4e9b8181946-r1` |
| MDD section reference | `mdd-section-analysis-partition-688c2184b4e9b8181946-r1` |
| current partitions for exact identity | `1` |
| candidate decisions / evaluation packages / holdout exposures / run records | `0 / 0 / 0 / 0` |

The exact relational project link remains active and the exact modeling version remains active at revision 1. The JSON Dataset Library contains exactly one HELOC_TRAIN version, 6,275 rows by 26 columns; the registered content checksum matches the governed `data_full` file. The relational `datasets` and `dataset_versions` catalog tables nevertheless contain no row for this exact identity. That catalog contradiction is an existing unresolved durability limitation; no fallback was used to hide it.

The partition documentation retry at `2026-08-03T21:35:43Z` updated only documentation state and `updated_at`. It did not alter revision, membership, seed, stratification, target mapping, or the three partition checksums. Because the record did change, this report does not call the live partition wholly unchanged.

## 2. Product contract implemented

### Split options and explanation

The normal Data Acquisition creation surface exposes exactly:

| Option | Behavior |
|---|---|
| 70% Development / 30% Final Holdout | Selectable; more final-evaluation precision and fewer development observations. |
| 80% Development / 20% Final Holdout | Default and recommended general-purpose balance. |
| 90% Development / 10% Final Holdout | Selectable only when backend target and count sufficiency permits it. |

The page states that the development population is used for EDA, preparation, feature decisions, CV, tuning, and candidate ranking. The sealed final holdout is opened only after candidate lock for final unseen-observation evaluation. Changing the option refreshes a backend preview in place; it does not create membership.

### Backend preview and sufficiency

`POST /api/analysis-partitions/preview` accepts the exact project/dataset/version, target contract and mapping, predictor authorization, problem type, ratio, seed, stratification, and deterministic method. It returns exact counts, class or regression-target coverage, checks, warnings, blockers, recommendation state, rationale requirement, and a preview fingerprint.

Policy `atlas.analysis_partition.supervised_default` version `1.0` recognizes only 70/30, 80/20, and 90/10. Classification requires at least two event and two non-event rows in both populations; fewer than 30 minority-class holdout rows is advisory. Regression requires at least 10 finite holdout targets, treats fewer than 30 as advisory, rejects constant/non-finite coverage, and checks target bands plus 5th/95th-percentile extremes. A nonrecommended choice or warning requires a rationale of at least 10 characters.

Preview is deterministic and read-only. The router resolves project ACL, exact active Dataset Library version, durable target contract, and durable predictor authorization before returning protected detail. Missing or contradictory identity/semantics fail closed. An existing sealed current partition blocks ordinary alternate target-aware previews outside the governed reset-impact path.

### Creation, reuse, concurrency, and reset

`POST /api/analysis-partitions/confirm` is the single Create & Seal action. It authorizes the exact project, recomputes preview, validates the exact fingerprint, enforces sufficiency/rationale, deterministically assigns every eligible row once, persists checksums and immutable IDs, seals holdout isolation, records actor/time, and creates exact evidence/MDD references before publishing readiness.

The repository uses a per-project lock and `BEGIN IMMEDIATE`. Identical concurrent confirms converge on one partition/revision; contradictory creates return the current conflict; different projects remain isolated; unauthorized requests fail before protected data or mutation. Existing exact membership is read-only. Documentation recovery uses `POST /api/analysis-partitions/complete-documentation`, exact ID/revision optimistic concurrency, idempotent sidecars, and exact read-back without recalculating membership.

Reset is exceptional. It requires exact current ID/revision, actor, rationale, acknowledgement, and impact preflight. Migration 0026 coordinates append-only reset history and native derivative invalidation; previous history is superseded, not overwritten. External file/memory evidence cannot share the SQLite transaction, so a cross-store crash window remains and consumers fail closed.

### Legacy revision-1 compatibility and documentation gates

A legacy record becomes usable only through explicit `verified_legacy_v1` verification of project, immutable dataset version, target semantics, complete assignments, counts, seed, stratification, and checksum. First/latest/count-only/browser/checkpoint promotion is forbidden. Ambiguous legacy state remains unusable.

EDA, Validation Design, and Training reread the exact durable partition with documentation readiness required. Browser flags are not authority. Partition evidence and MDD remain distinct durable stores and both must read back exactly.

### Training and Validation Design de-duplication

Step 6 renders the inherited partition read-only and has no editable holdout share, membership seed, membership stratification, or second train/test split. It continues to configure CV, folds/repeats, groups/time fields, fold-local preprocessing, training-only balancing/class weights, external TEST/OOT, compatibility checks, predictor review, and rationale. Backend request echoes are compare-only and mismatches to the sealed partition are rejected.

### EDA, Target Intelligence, and training-policy scope

Target-aware EDA derives target/problem/event semantics from the exact documented Analysis Partition and materializes development positions only. Client values are compare-only; contradictions return `target_contract_stale`. Full-population behavior remains allowed only for pre-partition Data Acquisition target distribution and predictor-only structural/descriptive diagnostics.

Governed Target Intelligence evidence and export require the exact documented development scope. The local workspace export is explicitly labeled draft, not version-pinned, not governed evidence, and not MDD-eligible. It cannot enter governed evidence. The frontend distinguishes Development Population target metrics from legitimate full-population structural diagnostics.

Preparation drafts use a strict allowlist and carry no membership authority. Notebook export requires exact identity-bound partition JSON, validates revision/hash/sealed isolation/full coverage, materializes development only, does not materialize final-holdout positions, applies balancing inside training only, ranks candidates on development validation, and hard-stops Evaluation without the exact governed evaluation package.

## 3. Six former Analysis Scope compatibility failures

| Test | Classification | Governed contract and correction |
|---|---|---|
| `test_workspace_target_analysis_without_exact_identity_fails_closed` | A — obsolete expectation | Production correctly returned structured `dataset_identity_required` detail. Test now validates code, recovery, and correlation ID instead of a legacy substring. |
| `test_draft_evidence_save_is_rejected_server_side` | A — obsolete expectation | Draft evidence remains HTTP 409; test now validates structured `eda_analytical_scope_not_current` and operation metadata. |
| `test_scope_transition_requires_exact_identity_before_governed_result` | A — obsolete expectation | Exact identity remains mandatory; test now validates the structured fail-closed contract. |
| `test_no_filesystem_path_or_population_rows_reach_the_browser` | B — incomplete isolated fixture | The fixture had no Analysis Partition. It now creates a deterministic governed 80/20 partition, then verifies the response omits paths and population rows. Production behavior did not change for this failure. |
| `test_regression_target_analysis_without_exact_identity_fails_closed` | A — obsolete expectation | Regression uses the same structured exact-identity failure contract. |
| `test_summary_export_requires_documented_development_scope` | A — obsolete expectation | Backend summary export no longer returns a draft success. It returns HTTP 409 without documented development scope; exact governed export returns development-only output with `finalHoldoutAccessed=false`. |

Final classification: five obsolete assertions, one incomplete fixture, zero production regressions, zero ambiguous contracts. The final unloaded suite passed 33 tests plus 2 subtests with 0 failures and 0 skips.

## 4. Frozen production source and exact production file manifest

The reproducible final fingerprint covers 84 changed production files: 1 under `scripts`, 31 under `server`, and 52 under `src`. Algorithm: union of tracked-modified and discoverable-untracked paths under those roots; exclude artifacts, data, migrations, tests, generated/cache/runtime/build paths; normalize `/`; ordinal sort; hash records `UTF-8 path + NUL + lowercase ASCII raw-file SHA-256 hex + LF`.

Final reproducible fingerprint: `898ee386ece95aad1d13f99ea5d3bac27c1899be3f540c7c9edcaad7ca0e2b9c` (8,463-byte fingerprint stream). Two independent implementations produced this value before and after the final restart. An earlier internal note recorded `3234784f...ab1b9`, but that value cannot be reproduced with the documented algorithm and is not used as freeze evidence. The mismatch is reconciled as an invalid intermediate fingerprint claim, not silently represented as a match.

Exact production manifest:

```text
scripts/run_security_tests.py
server/analysis_partition/__init__.py
server/analysis_partition/router.py
server/analysis_partition/service.py
server/analysis_partition/types.py
server/analytics/analysis_scope.py
server/analytics/target_intelligence_router.py
server/core/metadata_router.py
server/datasets/dataset_identity.py
server/eda/analytical_contract.py
server/eda/documentation_service.py
server/eda/eda_router.py
server/eda/workspace_service.py
server/main.py
server/persistence/repositories/__init__.py
server/persistence/repositories/analysis_partition_repository.py
server/persistence/repositories/holdout_governance_repository.py
server/persistence/repositories/model_registry_repository.py
server/persistence/repositories/predictor_authorization_repository.py
server/persistence/repositories/project_dataset_activation_repository.py
server/persistence/service.py
server/preprocessing/bureau_detection_router.py
server/preprocessing/bureau_detection_service.py
server/preprocessing/bureau_detection_types.py
server/preprocessing/predictor_authorization.py
server/splitting/split_router.py
server/splitting/split_service.py
server/training/candidate_contract.py
server/training/trainer.py
server/training/trainer_router.py
server/training/training_job_service.py
server/training/training_preflight_service.py
src/apps/ModelingApp.tsx
src/components/BureauReviewPanel.tsx
src/components/CopilotCard.tsx
src/components/ModeSwitcher.tsx
src/components/PredictiveIdentityProvider.tsx
src/components/Sidebar.tsx
src/components/StepPythonPanel.tsx
src/components/StepShell.tsx
src/components/documentation/EdaDocumentationLiveLink.tsx
src/components/eda/TargetIntelligenceWorkspace.tsx
src/components/eda/TargetVisualInsights.tsx
src/components/ui/AtlasWorkflow.tsx
src/lib/authReturnPath.ts
src/lib/authoritativeProjectContext.ts
src/lib/breadcrumbs.ts
src/lib/bureauDetection.ts
src/lib/dataScope.ts
src/lib/edaDocumentationApi.ts
src/lib/edaWorkspaceReadiness.ts
src/lib/localProjects.ts
src/lib/modelDevelopmentDocument.ts
src/lib/notebookExport.ts
src/lib/preparationGovernance.ts
src/lib/projectContext.ts
src/lib/projectContextMetadata.ts
src/lib/projectContextPersistence.ts
src/lib/projectScopedRoutes.ts
src/lib/serverPersistence.ts
src/lib/targetIntelligence.ts
src/lib/targetIntelligenceApi.ts
src/lib/useProjectContextAutosave.ts
src/lib/workflowSafety.ts
src/state/useWorkflowStore.ts
src/steps/AuthPages.tsx
src/steps/CreditRiskStudio.tsx
src/steps/Dashboard.tsx
src/steps/IntelligentWorkbench.tsx
src/steps/ModelDiagnostics.tsx
src/steps/ModelDocumentationStudio.tsx
src/steps/NewProject.tsx
src/steps/NotebookExport.tsx
src/steps/ProjectOverview.tsx
src/steps/ProjectUtilityPages.tsx
src/steps/Step00_ProjectContext.tsx
src/steps/Step01_DataAcquisition.tsx
src/steps/Step02_EDA.tsx
src/steps/Step04_Outliers.tsx
src/steps/Step06_BalancingSplit.tsx
src/steps/Step06_Train.tsx
src/steps/Step08_Evaluation.tsx
src/steps/Step10_Scoring.tsx
src/steps/Step11_ModelDevelopmentDocument.tsx
```

Migrations added/applied:

- `0024_analysis_partitions.sql` — durable partition/event authority.
- `0025_analysis_partition_product_completion.sql` — product-completion contract fields and indexes.
- `0026_analysis_partition_reset_coordination.sql` — reset operations and derivative invalidation coordination.

## 5. Final automated gates

All authoritative final gates ran after the last production edit. There were no unexplained assertion failures and no silently skipped failures.

### Backend product/documentation ledger — 18 isolated commands

Every command used `./.venv/Scripts/python.exe -m pytest <file(s)> -q -p no:cacheprovider` in a fresh process; suites with different storage/security roots were not combined.

| Files / area | Tests | Subtests | Warnings | Pytest time / wall time |
|---|---:|---:|---:|---:|
| seven-file Analysis Partition aggregate | 81 | 0 | 4 | 158.77 / 170.3 s |
| `split_atomicity_test.py` | 6 | 0 | 12 | 35.48 / 45.1 s |
| `validation_design_training_contract_test.py` | 8 | 0 | 34 | 33.38 / 46.0 s |
| `training_holdout_isolation_test.py` | 6 | 0 | 40 | 34.23 / 48.0 s |
| `holdout_governance_persistence_test.py` | 12 | 0 | 0 | 23.72 / 34.7 s |
| `vif_resolution_plan_test.py` | 12 | 0 | 0 | 46.28 / 55.3 s |
| `preparation_premium_backend_test.py` | 15 | 0 | 0 | 6.56 / 17.8 s |
| `preparation_table_first_backend_contract_test.py` | 4 | 0 | 0 | 7.43 / 13.1 s |
| `missing_table_first_backend_test.py` | 3 | 0 | 0 | 4.78 / 15.0 s |
| `feature_engineering_acceptance_repair_test.py` | 8 | 7 | 0 | 9.50 / 14.6 s |
| `feature_engineering_progression_contract_test.py` | 5 | 0 | 0 | 6.61 / 11.9 s |
| `feature_engineering_checkpoint_documentation_test.py` | 2 | 0 | 0 | 4.40 / 16.2 s |
| `model_training_preflight_authority_test.py` | 19 | 0 | 12 | 9.79 / 16.8 s |
| `training_validation_policy_execution_test.py` | 8 | 0 | 47 | 10.13 / 14.5 s |
| `phase2b1_candidate_contract_test.py` | 8 | 7 | 0 | 0.96 / 5.4 s |
| `validation_segregation_of_duties_test.py` | 6 | 0 | 18 | 48.01 / 53.8 s |
| `eda_documentation_contract_test.py` | 14 | 10 | 0 | 2.97 / 7.1 s |
| `eda_findings_documentation_contract_test.py` | 2 | 0 | 0 | 0.84 / 9.1 s |
| **Total** | **219** | **24** | **167** | — |

The seven-file aggregate command contained `analysis_partition_contract`, `analysis_partition_product_completion`, `analysis_partition_product_matrix`, `analysis_partition_validation_reuse`, `analysis_partition_legacy_compatibility`, `analysis_partition_documentation_gate`, and `validation_design_partition_target_authority`.

Exact frozen backend product/documentation commands:

```text
./.venv/Scripts/python.exe -m pytest tests/analysis_partition_contract_test.py tests/analysis_partition_product_completion_test.py tests/analysis_partition_product_matrix_test.py tests/analysis_partition_validation_reuse_test.py tests/analysis_partition_legacy_compatibility_test.py tests/analysis_partition_documentation_gate_test.py tests/validation_design_partition_target_authority_test.py -q -p no:cacheprovider
./.venv/Scripts/python.exe -m pytest tests/split_atomicity_test.py -q -p no:cacheprovider
./.venv/Scripts/python.exe -m pytest tests/validation_design_training_contract_test.py -q -p no:cacheprovider
./.venv/Scripts/python.exe -m pytest tests/training_holdout_isolation_test.py -q -p no:cacheprovider
./.venv/Scripts/python.exe -m pytest tests/holdout_governance_persistence_test.py -q -p no:cacheprovider
./.venv/Scripts/python.exe -m pytest tests/vif_resolution_plan_test.py -q -p no:cacheprovider
./.venv/Scripts/python.exe -m pytest tests/preparation_premium_backend_test.py -q -p no:cacheprovider
./.venv/Scripts/python.exe -m pytest tests/preparation_table_first_backend_contract_test.py -q -p no:cacheprovider
./.venv/Scripts/python.exe -m pytest tests/missing_table_first_backend_test.py -q -p no:cacheprovider
./.venv/Scripts/python.exe -m pytest tests/feature_engineering_acceptance_repair_test.py -q -p no:cacheprovider
./.venv/Scripts/python.exe -m pytest tests/feature_engineering_progression_contract_test.py -q -p no:cacheprovider
./.venv/Scripts/python.exe -m pytest tests/feature_engineering_checkpoint_documentation_test.py -q -p no:cacheprovider
./.venv/Scripts/python.exe -m pytest tests/model_training_preflight_authority_test.py -q -p no:cacheprovider
./.venv/Scripts/python.exe -m pytest tests/training_validation_policy_execution_test.py -q -p no:cacheprovider
./.venv/Scripts/python.exe -m pytest tests/phase2b1_candidate_contract_test.py -q -p no:cacheprovider
./.venv/Scripts/python.exe -m pytest tests/validation_segregation_of_duties_test.py -q -p no:cacheprovider
./.venv/Scripts/python.exe -m pytest tests/eda_documentation_contract_test.py -q -p no:cacheprovider
./.venv/Scripts/python.exe -m pytest tests/eda_findings_documentation_contract_test.py -q -p no:cacheprovider
```

### Scope, identity, storage, and security

| Exact command / area | Final result |
|---|---|
| `pytest tests/analysis_scope_test.py -q -p no:cacheprovider` | 33 passed + 2 subtests, 18 warnings, 149.35 s / 153.5 s wall |
| `pytest tests/target_intelligence_test.py tests/target_intelligence_partition_evidence_test.py -q -p no:cacheprovider` | 53 passed + 10 subtests, 30 warnings, 116.30 s / 122.4 s wall |
| `pytest tests/eda_governed_analytical_contract_test.py tests/eda_http_transport_contract_test.py -q -p no:cacheprovider` | 28 passed + 4 subtests, 13 warnings, 67.26 s / 78.4 s wall |
| `pytest tests/canonical_dataset_identity_test.py -q -p no:cacheprovider` | 10 passed, 18 warnings, 142.98 s / 160.4 s wall |
| `pytest tests/dataset_library_recovery_test.py -q -p no:cacheprovider` | 61 passed + 27 subtests, 198.38 s / 212.8 s wall |
| `pytest tests/model_registry_durability_test.py -q -p no:cacheprovider` | 29 passed + 4 subtests, 67.08 s / 74.4 s wall |
| `python tests/test_storage_isolation_guard_test.py` | 24 passed, 77.473 s / 99.8 s wall |
| `python scripts/run_security_tests.py` | 7 behavioral suites, 62 tests + 30 structural assertions, 0 failures/skips, 323.4 s wall |

The security behavioral suites reported 15, 6, 5, 8, 6, 16, and 6 passes. Nonblocking output was limited to four AnyIO resource warnings and two Pydantic `dict` deprecations. The broad `model_registry_test.py` was intentionally not run because it starts training; it is not represented as passing.

### Frontend, compilation, and build

| Command / gate | Final result |
|---|---|
| `node --test` over the 26 changed/new contract files | 259 passed, 0 failed/skipped/cancelled/todo; 14.427 s Node / 20.5 s wall |
| `node --test` over the 14 complementary contract files | 92 passed, 0 failed/skipped/cancelled/todo; 5.708 s Node / 14.4 s wall |
| `npm run test:regression` | 18 passed, 0 failed/skipped; 0.985 s / 11.6 s wall |
| **Node total** | **369 passed, 0 failed/skipped** |
| `npx tsc -b` | exit 0; no diagnostics; 125.3 s wall |
| `npm run build` | exit 0; 3,437 modules; Vite 1m17s; 204.8 s wall |
| `python -m compileall -q server tests` | exit 0 |
| `git diff --check` | exit 0; 111 line-ending warnings; 0 whitespace errors |

Exact frozen Node commands:

```text
node --test tests/analysisScope.test.mjs tests/dataAcquisitionValidationSimplification.test.mjs tests/datasetLibrary.test.mjs tests/edaAnalyticalScopeLabels.test.mjs tests/edaWorkspaceNavigation.test.mjs tests/evidenceCanonicalIdentity.test.mjs tests/experimentCanonicalIdentity.test.mjs tests/featureEngineeringProgressionContract.test.mjs tests/openProjectRoute.test.mjs tests/predictiveIdentityReadiness.test.mjs tests/predictiveModelingCommandCenter.test.mjs tests/predictiveModelingRepair.test.mjs tests/projectContextPersistence.test.mjs tests/regression.test.mjs tests/targetIntelligence.test.mjs tests/userManagement.test.mjs tests/analysisPartitionProductCompletionFrontend.test.mjs tests/analysisPartitionResetUxContract.test.mjs tests/authReturnPath.test.mjs tests/authoritativeProjectContext.test.mjs tests/bureauDetectionExactBinding.test.mjs tests/edaEntryReadinessContract.test.mjs tests/edaPartialReadinessFrontend.test.mjs tests/projectContextMetadata.test.mjs tests/projectScopedPredictiveNavigation.test.mjs tests/projectScopedRoutes.test.mjs

node --test tests/vifResolutionPlan.test.mjs tests/preparationPremiumWorkflow.test.mjs tests/preparationTableFirstContract.test.mjs tests/featureBuilderValidation.test.mjs tests/featureEngineeringCompletionContract.test.mjs tests/featureEngineeringProgressionContract.test.mjs tests/modelTrainingInteraction.test.mjs tests/modelTrainingPresetActionContract.test.mjs tests/modelTrainingProgression.test.mjs tests/holdoutIsolationFrontend.test.mjs tests/mddFramework.test.mjs tests/edaDocumentationMdd.test.mjs tests/canonicalDatasetIdentity.test.mjs tests/evidenceCanonicalIdentity.test.mjs
```

Build warnings were the existing browser-data/caniuse freshness notice, one mixed static/dynamic import, and three chunks above 500 kB. Two Open Project tests intentionally logged quota-recovery messages.

Environmental attempts are not counted as assertion failures: initial sandbox Node workers could not spawn (`EPERM`); two sandbox Python runs could not create/backup temp roots (`WinError 5`); one concurrent Analysis Scope run hit resource contention and its 500 ms performance assertion measured 955 ms. The identical unloaded/elevated commands above are the authoritative green results.

## 6. Source and authority scans

Final read-only scans passed for duplicate/editable holdout controls, first/latest partition fallback, browser partition authority, target-directed full-population EDA, EDA holdout reads, client target/problem/event control, training-policy overrides, undocumented partition bypass, draft governed Target Intelligence output, hardcoded live IDs, and unscoped Predictive Modeling pages.

Specific dispositions:

- Step 1 owns standard ratio selection; Step 6 reads inherited membership only.
- Partition repository current lookup uses exact `status='current'`; revision ordering appears only in audit history.
- `localStorage.splitStrategy` affects Copilot advisory copy only; it is not authority.
- EDA contains no holdout materialization/open call and sets `finalHoldoutAccessed=false`.
- Target/problem/event request fields are compare-only downstream; durable contradictions fail closed.
- Training policy is derived from approved design; failed-model retry still reruns preflight.
- Calls without documentation readiness are limited to partition management/recovery/reset and pre-partition structural Data Acquisition.
- Operational Predictive Modeling pages render only on project-scoped routes; legacy `/stepXX` paths redirect.
- No live HELOC acceptance ID is hardcoded in production source.

One nonblocking documentation residue remains: `server/eda/workspace_types.py` contains an outdated request docstring describing full in-memory population, while execution is exact documented development scope.

## 7. Runtime-isolation reconciliation

External pre-run snapshot: `C:\Users\james\AppData\Local\Temp\atlas-analysis-partition-product-20260803-102806`.

### Protected hash comparison

| Authority | Pre-run SHA-256 | Final SHA-256 | Disposition |
|---|---|---|---|
| Dataset Library registry | `7fbe95e6...84446f` | `bb40cfd2...31e6d9` | Changed by authenticated exact-version activation/link projection at 21:35Z; catalog still contains the same one governed version. |
| project links projection | `9f3568b6...9fb890` | `c37fb6c3...ff09db` | Changed by the same live activation/link request; exact project/version link. |
| workflow checkpoint | `73571f38...7e00c` | `473a9d44...20dc5` | Changed by live workflow actions and again by post-restart browser rehydration; exact identity/partition retained, zero result scopes. |
| recovery journal | not in protected baseline | `a69b92a7...8f0d3` | One committed/resolved exact link operation; no unresolved journal. |
| EDA documentation | already dirty pre-run | `f913b206...346b54` | Three authenticated draft saves at 21:35–21:36Z; current approvals stale and readiness blocked. |
| evidence registry | clean at pre-run | `cd9a7c41...9af2e` | Live evidence refreshes and feature confirmation; 272 unique IDs, no duplicate-ID group. |
| current feature manifest | clean at pre-run | `aeefef10...e3430c` | Live Feature Engineering finalization; now `fm-8e2dc2933912d428`. |
| feature-manifest version | absent pre-run | `46d5a74f...b171b` | New immutable version from the same live action. |
| model document / index | clean at pre-run | `081f7278...8c72f` / `562ca0b7...d90d24` | Live exact feature attachment updated recovered document shell. |

Hashes are abbreviated only in this comparison table; exact current runtime hashes are recorded in the read-only audit evidence and include:

- outlier evidence `ev-governed-outlier-treatment-and-special-val-6f54f85fc59d909d`, `ed0e96171afd72e388861ca5741f4ddbc6704c2cf2b9c296963a94ac199f3155`;
- missing evidence `ev-missing-value-validation-no-treatment-requ-56830e6baf0a8852`, `6bbd86eb8655a424ef8e93112988eadcf762f9aa009e7e0ce459de79946de66c`;
- feature evidence `ev-governed-feature-manifest-7a80399a072f0da4`, `6583df325bf0c30b63e4ef6fc92733f20b2cfdd1171111c015b379399996a1cb`;
- current feature pointer `aeefef10ad9337d2b5fc900466c74bef223165036ab63280b3c2c077c6e3430c`;
- feature version `46d5a74f0a725106e0276a730ce4c5efd3f1feca7688f27d13be9ca97deb171b`;
- model document `081f72781360b78d02b916383cca00c45a81e34291d47a09145ac2ed7ad8c72f`; and
- document index `562ca0b759f62957a75119ea5f375bfbb6f69b40a7c1a14703bd280674d90d24`.

### Exact changed/created records and attribution

| Record(s) | Actor/time/source | Current reference and classification |
|---|---|---|
| Dataset projection operation `dataset-projection-f183a8f30cc748b7bb5cd5ab04cc3037` | authenticated owner, 21:35:10Z; Data Acquisition exact activation/link API | Referenced by active JSON projection; non-synthetic, safe exact identity, but unauthorized for this closeout. |
| Partition evidence `ev-analysis-partition-688c2184b4e9b8181946-r1` and partition row documentation fields | authenticated owner; `complete-documentation` retry at 21:35:43Z | Referenced by exact partition/checkpoint; non-synthetic and internally exact; partition metadata changed, membership did not. |
| MDD document/version/section/block/link `mdd-document-1af2077e8d97253bc3c7`, `mdd-version-analysis-partition-...-r1`, `mdd-section-analysis-partition-...-r1`, `mdd-block-analysis-partition-...-r1`, `mdd-evidence-link-analysis-partition-...-r1` | same retry, 21:35:43Z | Exact partition sidecars; current partition/checkpoint references section; non-synthetic. |
| EDA documentation draft `1af207...fff9e` | three authenticated draft-save APIs, 21:35:59–21:36:07Z | Not the current EDA step evidence; stale/blocked rather than safe for carry-forward. |
| Outlier and Missing Values evidence records above | authenticated evidence-capture endpoints, 21:44:43Z and 21:45:15Z | Current workflow references them; non-synthetic; legacy records lack AP revision lineage and remain unresolved for strict lineage. |
| Feature manifest `fm-8e2dc2933912d428`, materialization `mt-72e2e97ee20cf6c1`, feature evidence, feature MDD attachment | authenticated preview/materialize/confirm/evidence/MDD sequence, 21:51:01–21:51:12Z | Current checkpoint references it. It has 28 definitions (23 selected originals, 5 unselected planned definitions), replacing the pre-run 30-definition pointer by excluding target-source `RiskPerformance` and internal `atlas_split`. Non-synthetic and not safe to delete. |
| workflow checkpoint | project-save/workflow update at 21:51:44Z and post-restart rehydration at 22:10:02Z | Exact project/version/AP and current feature manifest, zero result scopes; non-synthetic. SQLite says classification while embedded legacy compatibility `problem_type` is null/unverified, so consumers must use durable SQLite authority. |
| recovered model document `doc-atlas-mrzpau4t-1785363288` | authenticated feature MDD attachment at 21:51:12Z | Exact feature attachment is valid, but global shell remains contradictory (`Class` target and legacy dataset alongside HELOC), 0% completion, not export-ready. |

Historical current-project runtime artifacts preserved from earlier in the phase:

- `ev-target-intel-af288f22039b46c69429`, SHA-256 `29edc077b73be7487e53e93e78910252f64b5e8356282d43181f2f972094d902`;
- EDA evidence `eda-19c43c06`, `eda-b8c03464`, `eda-d95e8ff4`, and `eda-7fd351ce`; and
- VIF plan `vif-plan-50b8ce1a6786b7ad`, SHA-256 `1a3a15b546eac5a6453e024d1a08fed19282ca190b69dfc9c37c0a58db3ffdc3`.

The Target Intelligence artifact records target/predictor aggregation over all 6,275 rows, no Analysis Partition ID, and no development-scope declaration. It therefore proves historical access to the 1,255-row sealed holdout. The four EDA artifacts are stale/contradictory historical evidence; one labels development scope while retaining a 6,275-row top-level lineage count. The final code closes this path prospectively but cannot erase the historical access. No evidence shows those artifacts were used for feature selection, tuning, candidate ranking, threshold selection, Training, Evaluation, Interpretation, promotion, or Scoring.

Runtime-isolation outcome: **failed but reconciled**. The sources and exact lineages of the observed writes are identified; none are proven synthetic tests. Consequently there is no deletion proposal. A safe forensic/cleanup proposal is: quiesce live clients and services; capture a new external path/hash/mtime/size manifest; obtain James's explicit authorization; preserve/quarantine suspect artifacts outside the repository; never delete or stage them; never restore registry/link/checkpoint blindly; recover only from verified source bytes; then rerun exact active-identity, partition, feature-manifest, documentation, and restart verification.

## 8. Final service restart and integrity

After the last source edit and all final gates:

| Service | Pre-restart listener | Post-restart listener | Result |
|---|---:|---:|---|
| Vite, port 5174 | `81652` | `73416` | old tree stopped, port closed, replacement HTTP 200 |
| FastAPI, port 8001 | `85428` | `80784` | old tree stopped, port closed, replacement `/api/health` HTTP 200 with `{"ok":true,"status":"running"}` |

Replacement launchers were npm PID `83312` (via cmd PID `73936`) and venv Python PID `84744`. Migrations 0024, 0025, and 0026 remained installed. Post-restart read-only retrieval returned exactly one current partition and the exact identity, revision, membership, design, and three checksums in Section 1. No first/latest/checkpoint/browser/anonymous fallback was used for that SQLite verification.

The user's already-open authenticated browser reconnected after service startup and generated project-open, dataset-view, project-save, workflow-state, and checkpoint activity at 22:09–22:10Z. That explains the post-restart database/checkpoint byte changes. Logical partition/target/predictor/activation authority remained exact, but this further confirms that the runtime was not quiescent.

Read-only integrity after restart:

- Final read-only snapshot at `2026-08-03T18:23:12-04:00`: database SHA-256 `fa20ed35d1266682626b3bda752ac8505879d3dc052388d098598a2f3b1da854`; checkpoint SHA-256 `473a9d44faac72234c68648f685525191f80cbd53eb51412031dd85d02120dc5`. The exact partition values in Section 1 and the single-current-partition count were unchanged at this snapshot.
- `PRAGMA integrity_check`: `ok`.
- `PRAGMA foreign_key_check`: 312 historical findings — `decision_journal` 182, `evidence_artifacts` 113, `project_collaborators` 17.
- The 312 findings match the previously documented historical debt and were not repaired in this closeout.
- Relational exact dataset/version rows remain absent despite the active link/activation and intact JSON Dataset Library.

## 9. Repository inventory and Git safety

Final discoverable file inventory:

| Category | Tracked dirty | Untracked | Total |
|---|---:|---:|---:|
| Production under `server`/`src` | 71 | 12 | 83 |
| Tests | 34 | 34 | 68 |
| Documentation | 0 | 2 | 2 |
| Runtime/generated/audit output | 11 | 35 | 46 |
| Tooling and migrations | 1 | 3 | 4 |
| **Total** | **117** | **86** | **203** |

`git status --short` collapses some untracked directories; the 86 count is from `git ls-files --others --exclude-standard`. Twenty inaccessible pytest-cache roots are excluded and remain untouched. Tracked diff stat: 117 files, 78,546 insertions, 4,939 deletions. Branch/HEAD/upstream remain `codex/phase2a-canonical-lineage`, `24961ad4da6566c53cf4634796a439f7498fcc0e`, and 0 ahead / 0 behind. The index is empty.

## 10. Recommended review/commit slices

No commit was created. Suggested human-reviewed order:

1. canonical dataset/project/target/predictor authority and prior migrations;
2. project-scoped identity/routing and context lifecycle;
3. Analysis Partition repository/service/router plus migrations 0024–0026;
4. Data Acquisition Analysis Partition UX and focused frontend contracts;
5. Training and Validation Design de-duplication and policy execution;
6. exact documentation recovery and legacy compatibility;
7. development-only EDA/Target Intelligence and governed export;
8. preparation/notebook holdout-isolation changes;
9. isolated concurrency/security/recovery/durability tests;
10. this closeout report after runtime forensics are reviewed.

Never stage without explicit review: `server/artifacts/**`, `.runtime/**`, `.tmp/**`, `server/data/**`, databases, `audit-output/**`, `test-results/**`, pytest caches, `dist/**`, logs, generated datasets, browser profiles, cookies, credentials, or any unrelated inherited dirty file.

## 11. Deferred manual browser checklist

No browser was controlled by this closeout task. A later explicitly authorized, quiesced acceptance should:

1. open exact project/version and verify activation revision 1;
2. verify Data Acquisition shows exact partition revision 1 and 5,020/1,255 read-only membership;
3. verify the documentation evidence/MDD references shown in Section 1;
4. verify EDA reports structured blocked/stale documentation state until its current draft is reviewed, without reading holdout;
5. verify Target Intelligence governed export says Development Population and 5,020 rows;
6. verify Step 6 has no editable membership controls and shows inherited seed/stratification;
7. verify Model Training preflight is bound to the exact partition/feature authority and do not start training;
8. reload/restart and confirm exact partition checksums again;
9. confirm no new partition, candidate, evaluation, interpretation, promotion, or scoring record; and
10. stop.

## 12. Remaining limitations and final confirmations

Remaining limitations:

1. Operational closeout is blocked because runtime isolation failed even though all automated gates passed.
2. Partition documentation metadata changed live during the window; immutable membership and checksums did not.
3. The current feature manifest materially changed live from 30 to 28 definitions and is referenced by checkpoint/evidence/MDD.
4. The SQLite dataset/version catalog lacks the exact rows while active link/activation and JSON Dataset Library remain exact.
5. The EDA documentation draft is stale/blocked and the recovered model-document shell is globally contradictory.
6. The checkpoint's legacy problem-type compatibility field is unresolved while SQLite records classification.
7. Historical Target Intelligence/EDA evidence proves pre-repair sealed-holdout access.
8. SQLite has 312 historical foreign-key findings.
9. External evidence/MDD stores retain a reset crash-consistency window.
10. `workspace_types.py` has one outdated, non-executable scope docstring.

Final confirmations:

- All authoritative final automated gates passed: **yes**.
- Runtime isolation passed: **no — failed but reconciled**.
- Any live authority changed: **yes — projections, documentation, evidence, feature manifest, MDD, workflow state, checkpoint, and database bytes**.
- HELOC partition identity/revision/membership/seed/stratification/checksums changed: **no**.
- HELOC partition record changed: **yes — documentation status/references and `updated_at`**.
- Model training performed in this closeout: **no**.
- Evaluation opened/performed: **no**.
- Interpretation opened/performed: **no**.
- Candidate/model promotion performed: **no**.
- Scoring opened/performed: **no**.
- Files staged, committed, pushed, reset, restored, cleaned, amended, stashed, or discarded: **no**.
- Index empty: **yes**.
- Phase fully complete: **no; implementation validation is complete, operational acceptance is blocked by the runtime findings above**.
