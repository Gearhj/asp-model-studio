# Target-aware analysis source inventory

Date: 2026-08-04

Scope: production Predictive Modeling analysis, preparation, feature-building,
training-selection, evaluation, and generated-notebook call paths. This review
used synthetic data only. No registered HELOC rows, partition assignments, or
final-holdout values were read.

## Governing population contract

ATLAS uses three intentionally different analytical populations:

| Contract | Permitted use | Target access |
| --- | --- | --- |
| A. Full governed population | Predictor-only structure: counts, types, missingness, quantiles, outlier cutoffs, distributions, and transformation previews | Prohibited after an Analysis Partition exists, except the explicitly labeled Data Acquisition target composition/quality result |
| B. Exact development population | IV, WOE, event rates, target association, monotonicity, target-informed rankings, recommendations, candidate selection, cross-validation, calibration, and pre-exposure threshold policy | Required; membership is resolved from the exact durable project/dataset/version/target/partition/revision contract and selected by row position |
| C. Sealed final holdout | One-time, exact-candidate evaluation reporting after candidate and threshold lock | Prohibited for preprocessing, EDA, feature recommendations, candidate ranking, feature selection, calibration, and threshold tuning |

`server/preprocessing/development_scope.py` is the shared enforcement boundary
for preparation services. `resolve_development_analysis_scope` resolves the
current exact predictor authorization and documented Analysis Partition,
verifies identity and positive revision, treats request target/event/problem
fields only as contradiction checks, and materializes development rows only.
`DevelopmentAnalysisScope.materialize_aligned_features` checks row count and
exact index equality, then selects with `iloc`; this preserves correct row
membership even when labels are duplicated. Missing, stale, cross-project, and
cross-version identities fail closed. The returned metadata states structural,
target-directed, and holdout scopes separately and includes canonical
`analytical_scope`, `population_id`, `population_count`, `partition_id`,
`partition_revision`, `holdout_excluded`, `source_checksum`, `actor`, and
`timestamp` fields.

## Production call-path inventory

| Operation | Entry point and calculation path | Population and authority | Final-holdout behavior | Status |
| --- | --- | --- | --- | --- |
| Data Acquisition target composition and mapping | `server/preprocessing/governed_profile_service.py::governed_target_profile` -> `resolve_target_mapping` / `compute_quality` | Full immutable registered version. This is the sole labeled full-target exception. Exact development scope is additionally required for predictor WOE/IV once a partition exists. | No holdout selection, ranking, or tuning use; result is labeled as the eligible/full registered population. | Enforced |
| Governed predictor WOE and IV | `governed_target_profile` -> development `_FrameSession` -> `compute_predictor_iv` | Exact durable development rows and governed target mapping. Before the first partition, values are `pending_analysis_partition`; a stale historical/current partition fails closed. | Not materialized or used. | Enforced |
| Preparation feature inventory and univariate target association | `server/preprocessing/feature_profile_service.py::profile_features` -> `information_value` / development correlation | Full governed predictor frame supplies structural statistics. Exact development features/target supply IV or correlation. Pre-partition inventory is structural only. | Not materialized or used. | Enforced |
| Bureau-special structural detection | `server/preprocessing/bureau_detection_router.py` -> `server/preprocessing/bureau_detection_service.py::detect_bureau_data` | Full governed frame is loaded with `include_target=False`. Exact current authorization supplies allowed predictors. | Target is absent from the structural frame. | Enforced |
| Bureau-special event-rate and event-count comparisons | `detect_bureau_data` -> `_event_rate` / `_event_count` | Exact development features and governed development target/event only. Boolean masks are applied positionally so duplicate labels cannot reselect rows. | Not materialized or used; full-target fallback removed. | Enforced |
| Outlier thresholds, counts, capping previews, and post-treatment structural summaries | `server/preprocessing/outlier_router.py` -> `server/preprocessing/outlier_service.py::summary` | Full governed predictor-only frame. The target is dropped before service invocation. | Target and holdout labels are never inspected. | Enforced |
| Outlier IV, correlation, event-rate impact, and target-informed ordering | `OutlierService.summary` using `development_features` / `development_target` | Exact development scope resolved by project, dataset, version, target, authorization, partition ID, and revision. | Not materialized or used. | Enforced |
| Missing counts/rates, distributions, and imputed-value previews | `server/preprocessing/missing_router.py::missing_summary` | Full governed predictor-only structural frame. Target is removed before missing normalization. | Target and holdout labels are never inspected. | Enforced |
| Informative missingness, missing-vs-observed target comparison, IV, and target-informed ordering | `missing_summary` -> `_informative_missingness` / `information_value` | Exact development feature and target series only. | Not materialized or used. | Enforced |
| Missing/outlier validate and apply | `validate_missing_values`, `apply_missing_values`, and `apply_outlier_treatments` | Exact identity and authorization required. Treatment is applied structurally to predictors; missing apply restores the unchanged target positionally. Row deletion fails closed because it would invalidate sealed partition membership. | No holdout target analysis. | Enforced |
| EDA target-source exclusion | `server/eda/workspace_service.py::_predictor_authorization` -> `_detect_frame_target_sources` | Durable upstream exclusions are authoritative. Any dynamic deterministic-source check uses only the positionally materialized development frame and target. | Not materialized or used. | Enforced |
| EDA structural overview | `EDAWorkspaceService._cached(section="overview")` | Full governed predictor-only frame. If exact target-directed authority is unavailable, Overview is explicitly partial and contains no target profile, IV, WOE, ranking, or relationship result. | No target access. | Enforced |
| EDA target profile, event rate, predictor preview, target-by-predictor, predictor diagnostics, monotonicity, relationships, stability, and findings | `_cached` -> exact `resolve_development_partition` -> `_target`, `_target_predictor_preview`, `_target_by_predictor_locked`, `_predictors`, `_relationships`, `_stability`, `_findings`; governed harmonization uses `server/eda/analytical_contract.py` | Exact documented development population, governed target contract, and authorized predictors. IV, quantile/category event rates, missing-value target deltas, correlations, ranking, and recommendations all consume the development factory frame/target. | Not materialized or used. Metadata says `development_population`, `final_holdout_accessed=False`, and `final_holdout_used_for_selection=False`. | Enforced |
| Auto-VIF target signal and resolution recommendations | `EDAWorkspaceService.generate_vif_resolution_plan` -> `server/eda/vif_resolution.py::build_vif_resolution_plan` | VIF/correlation matrix and target signal are built from the exact development materialization. `development_signal` is the only target-informed tie-break input; the plan records `target_informed_evidence=development_population_only`. | Not materialized or used. Accepting a plan creates draft Feature Engineering recommendations only. | Enforced |
| Feature Engineering builders | `server/features/feature_service.py` | Target and deterministic sources are excluded by the exact predictor authorization contract. Numeric bins, rule categories, arithmetic/ratio/interaction/date-derived features are structural and unsupervised; there is no production target encoder or supervised-binning builder. | No target access and no automatic predictor removal. | Enforced |
| Target-informed feature recommendations / univariate screening | EDA findings and VIF plan -> draft recommendation evidence consumed by Feature Engineering | Development-only evidence. Acceptance is a governed proposal, not dataset mutation or automatic selection. | Not materialized or used. | Enforced |
| Training data resolution | `server/training/training_preflight_service.py` and `server/training/trainer_service.py::_get_training_partition` | Exact documented Analysis Partition and governed validation design are verified before use. Training workers receive development training/validation arrays only. | Preflight verifies sealed-holdout metadata without inspecting holdout arrays. | Enforced |
| Candidate fitting, hyperparameter search, calibration, and ranking | `server/training/trainer.py::_validated_cv_splits`, `_train_classification_model`, `_selection_metric_record`, `selection_sort_key`; orchestration in `training_job_service.py` | Governed folds inside the development population. Parameter search and calibration are fold-local. Ranking evidence is out-of-fold/cross-validation mean only. | Candidate contracts reject final-holdout ranking evidence. | Enforced |
| Threshold preparation | `trainer.py::_train_classification_model` -> candidate contract in `server/training/candidate_contract.py` | Classification threshold is locked before holdout exposure (`platform_governed_default_0_5`); `selection_threshold_tuned=False`. | Candidate contract rejects holdout-derived threshold/calibration sources. | Enforced |
| Training-only RFE / feature ranking | `server/evaluation/eval_service.py` RFE path (`DATASTORE.X_train` / `DATASTORE.y_train` with deterministic internal development validation) | Development training arrays only; the source candidate is exact-ID bound. | `holdout_used=False`; no `X_test`/`y_test` participation in RFE. | Enforced |
| Final Evaluation | `eval_service.py::_open_final_holdout` and reporting builders | Exact candidate, artifact, dataset version, split, manifest, threshold policy, and durable exposure contract must match before opening one final holdout. | Reporting only. The final holdout cannot alter training summary, ranking, selection, feature recommendations, calibration, or threshold policy. | Enforced |
| Generated Python notebook | `src/lib/notebookExport.ts` | Pre-partition EDA is predictor-only. Target-directed EDA and bureau target comparisons are emitted after exact assignment identity/revision verification and use `y_development` selected by `iloc`. | The export never builds a full target vector; holdout positions are validated, counted, removed from memory, and never materialized as features or target. | Enforced |

## Non-workflow and unreachable code

- `server/analytics/query_service.py` and its pandas/DuckDB engines power the
  general Analytics Workbench. They operate on the user-authorized bounded query
  frame and are not a Predictive Modeling preprocessing, selection, or training
  fallback.
- Legacy `_current_dataset_and_target` and `_infer_target` definitions in
  `server/training/trainer_service.py` have no production callers. The active
  training path is the exact governed partition path above.
- No production target-encoding or supervised-binning builder was found. Any
  future implementation must resolve the exact development scope and record the
  same explicit lineage before it can become reachable.

## Regression guards

`tests/preprocessing_development_scope_test.py` uses synthetic isolated data to
prove divergent full/development event rates, holdout invariance and no target
access, missing/stale/cross-project/cross-version fail-closed behavior,
duplicate-index positional correctness, and durable restart restoration.

`tests/target_aware_production_scope_scan_test.py` statically rejects known
full-target fallbacks, requires development-bound target-aware calls, verifies
explicit EDA development metadata, and prevents generated notebooks from
reintroducing pre-partition target distribution or full-target-vector access.
