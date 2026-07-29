# Predictive Modeling Deep-System Review

**Requested report date:** 2026-07-28
**Execution window:** 2026-07-28 through 2026-07-29
**Repository:** `C:\Users\james\ds-workflow-starter`
**Reviewed HEAD:** `5b8ea34` plus the preserved working tree
**Disposition:** Conditional paid-pilot readiness; all verified P0 findings from this review are repaired and covered by focused tests, but the P1 items below still prevent an unconditional production-readiness claim.

## 1. Overall verdict

The Predictive Modeling workflow has a materially stronger analytical and governance spine than its legacy architecture suggests. The current target-source exclusion, feature-manifest, validation-design, split, training, evaluation, model-registry, scoring-run, evidence, and documentation contracts provide a credible foundation for a controlled pilot.

Two P0 defect classes were verified during this review:

1. A fitted result could be promoted as final, reported as ready, exported, or scored without proving that its project, immutable dataset version, target, problem type, feature manifest, split, validation design, and training job still matched the active workspace.
2. Monitoring and legacy Model Documentation routes authenticated the caller but did not consistently authorize the addressed project or direct object. Global monitoring lists and summaries could therefore disclose records from projects the caller could not view.

Both defects are repaired. Promotion and scoring now fail closed on stale lineage, and governance routes now authorize direct objects, filter aggregate results, prevent cross-project evidence substitution, and use the authenticated actor for document attribution.

The remaining paid-pilot blockers are primarily durability, version binding, and scale concerns—not an identified target-leakage or holdout-contamination defect.

## 2. Review scope and method

The review covered:

- Project Context through Model Monitoring.
- Dataset identity, target semantics, deterministic target-source exclusion, preparation, feature materialization, splitting, training, evaluation, interpretation, scoring, documentation, implementation, registry, and monitoring.
- Memory behavior, process-global state, concurrency, long-running jobs, restart recovery, response bounds, and browser rendering.
- Project isolation, direct-object authorization, evidence, decision journal, audit attribution, and model-version linkage.
- Source inspection, TypeScript compilation, production build, focused integration tests, regression tests, MDD tests, monitoring tests, and the complete security gate.

The active HELOC project was not destructively changed. No credential was accessed or derived. No Git state-changing operation was performed.

## 3. What is working well

### 3.1 Dataset and target controls

- The working dataset store is scoped by authenticated user and project through `authorize_modeling_scope` and an explicit active-project context.
- Dataset identity is carried through the active source metadata, manifest, split, training summary, final-model metadata, model registry, and scoring records.
- The target and deterministic target-source exclusions are centralized through predictor authorization rather than being reimplemented ad hoc on every page.
- `RiskPerformance` remains excluded from predictor authorization for the HELOC `bad_flag` workflow. Focused target-source tests and Predictive Modeling repair tests remain green.
- Full-population preparation summaries and governed EDA/profile services use the backend workspace rather than treating browser previews as population statistics.

### 3.2 Preparation and feature lifecycle

- Outlier and missing-value treatment operate on the backend workspace, carry dataset-version metadata, and mark downstream split state stale.
- Feature-manifest changes clear preview state, reset resident splits, and carry a new manifest identity.
- The current UI emphasizes exact, table-first professional review while retaining visual analysis.
- Split creation records target/event semantics, selected predictors, feature-manifest identity, validation design, prevalence, and split state.

### 3.3 Training and evaluation discipline

- Training preflight rejects stale or missing splits and resolves the governed feature set.
- Cross-validation and fitting are performed on training data; balancing is applied to the training partition.
- External TEST/OOT concepts remain confirmation populations rather than tuning inputs.
- Candidate failure isolation and cancellation are covered by the Predictive Modeling repair suite.
- Expensive evaluation visuals use bounded samples in several paths (for example, partial-dependence and sensitivity samples), which protects browser and service responsiveness for ordinary projects.

### 3.4 Registry and scoring

- Immutable model-version records include dataset and feature-manifest identities.
- Scoring runs can reference the real `modelVersionId` rather than only a display label.
- Executable model objects are not exposed through the JSON export endpoint; the endpoint produces a governed manifest and directs executable deployment through approved artifact formats.
- Final-model status now distinguishes artifact presence from readiness and reports a stale blocker explicitly.

### 3.5 Governance surfaces

- Evidence, decisions, audit events, validation artifacts, scoring runs, and model versions have durable persistence repositories.
- The MDD framework and Model Documentation Studio tests pass.
- Monitoring produces audit, evidence, notification, event, and decision outputs.
- The P0 authorization repair now applies project permissions to monitoring plans, metrics, runs, observations, alerts, actions, baselines, and events, including direct-object IDs and aggregate views.

## 4. Analytical-integrity findings

| Priority | Finding | Status | Evidence / remediation |
|---|---|---|---|
| P0 | Final-model promotion and scoring did not prove complete active lineage. A feature change could reset splits while old fitted results remained resident, allowing a stale result to appear final. | **Fixed** | `server/evaluation/eval_service.py` now computes the active binding, validates promotion, reports stale status, and rejects stale final/named scoring artifacts. `server/evaluation/eval_router.py` returns a conflict for stale export. Training metadata now carries validation-design identity. |
| P0 | Legacy governance routes were authenticated but not consistently project-authorized. | **Fixed** | Monitoring direct objects and aggregates now use project permission checks; MDD project/document/evidence/export routes authorize the document project. A new isolated two-user integration test proves fail-closed behavior. |
| P1 | Legacy or recovered workspaces can still use the label `in-memory` where an immutable dataset version is absent. | Open | Paid-pilot projects should require a registered immutable dataset version before split/training/final promotion. Final promotion now fails closed when the binding is missing, but earlier exploratory operations still support compatibility state. |
| P1 | Raw fitted training objects and active training jobs are not durable through a real server restart. | Open | `TRAINING_JOBS` is explicitly excluded from the session checkpoint. Persist job commands, checkpoints, terminal results, and approved model artifacts in a recoverable job/artifact service. |
| P1 | Some legacy MDD, monitoring, evidence, and implementation records are project-bound but not structurally model-version-bound. | Open | Add `model_version_id` (and, where relevant, dataset/split/validation identities) to the records listed in section 7. |
| P2 | Several evaluation paths copy full train/test frames before encoding or diagnostics. | Open | Move large diagnostics to bounded columnar queries and artifact-backed jobs; retain full-population calculations only where statistically required. |

No evidence was found that `RiskPerformance` is intentionally admitted into IV, preparation, feature, split, training, evaluation, or scoring schemas. The target-source exclusion tests remain the release guard for this invariant.

## 5. Scale and volume findings

### P1 paid-pilot blockers

1. **Volatile training jobs and fitted objects.** `TrainingJobService` uses daemon threads and resident job/result objects. Server restart loses the active execution object even though lightweight workspace state is checkpointed.
2. **Whole-frame residency and copying.** `DatasetStore` retains raw, processed, train, and test DataFrames and returns defensive copies. Split generation, balancing, training handoff, and evaluation can multiply memory use for large populations.
3. **Synchronous expensive diagnostics.** Several evaluation/interpretation operations execute in request handlers and construct encoded copies. SHAP-like, boundary, permutation, and sensitivity workloads should become bounded jobs with deadlines and persisted outputs.
4. **Project-level checkpoint growth.** The session checkpoint serializes resident scoped DataFrames/results. It is a compatibility recovery layer, not an appropriate multi-user, multi-million-row persistence architecture.
5. **Unbounded row request shapes in legacy endpoints.** Scoring and metadata routes accept row arrays that become DataFrames. Platform request-size middleware limits raw bytes, but row counts and analytical work should also have explicit endpoint limits and asynchronous bulk paths.
6. **Model artifact loading policy.** Registry artifacts are durable, but repeated high-volume scoring should use a bounded, keyed model cache with eviction and metrics rather than ad hoc loads or resident evaluation state.

### P2 scale improvements

- Replace CSV working scans with registered Parquet/Arrow and DuckDB queries.
- Materialize immutable column summaries keyed by user authorization, project, dataset/version/hash, target contract, feature manifest, and analytical parameters.
- Batch feature profiling instead of per-feature repeated DataFrame construction.
- Add query deadlines and cancellation to full-population EDA/preparation requests.
- Virtualize tables above the current bounded display limits and make all “show all” options explicit.
- Split large page components and heavy visualization bundles by route.
- Add process and worker metrics for resident frame bytes, fitted artifact bytes, queue depth, cancellation latency, and checkpoint duration.

### P3 optimization

- Reuse encoded evaluation matrices within one immutable model/split binding.
- Reduce defensive copies after immutable handoff boundaries are established.
- Precompute stable label/formatting metadata for very wide schemas.

## 6. User-experience findings

### Working well

- The current Preparation pages lead with complete professional tables and make global strategy changes visible in the underlying summaries.
- Outlier histograms expose cutoffs, and the feature-count control keeps initial rendering bounded.
- Feature Engineering now has a persistent completion path and a visible fixed action bar.
- The Predictive workflow shell exposes progress and next actions without requiring users to rediscover a hidden footer button.
- Disabled analytical actions increasingly show their blockers.

### Remaining risks

| Priority | Area | Finding |
|---|---|---|
| P1 | Cross-page state language | “Current,” “ready,” “confirmed,” and “complete” are still implemented by multiple feature-specific components. Consolidate these into a shared lineage/status vocabulary. |
| P1 | Long pages | Several workflow pages exceed 2,000 source lines and combine orchestration, tables, charts, evidence, and forms. This raises regression risk and makes responsive/accessibility review difficult. |
| P1 | Browser acceptance | Protected pages could not be walked during this run because the available browser session was not authenticated. No protected-state screenshot or browser error claim is made. |
| P2 | Wide-schema review | Table-first pages need consistent column pinning, saved filters, bulk review, and virtualization for hundreds or thousands of predictors. |
| P2 | Responsive behavior | Automated source and component checks exist, but a signed-in viewport matrix still needs to cover 1280, 1440, and 1920 pixel desktop widths plus supported compact layouts. |

## 7. Governed lifecycle and documentation findings

### Correctly version-bound today

- Model registry versions.
- Scoring runs through `model_version_id`.
- Final-model promotion metadata after this repair.
- Dataset and feature-manifest identities in model-version metadata.
- Experimental Design study/design versions (reported separately).

### Records that remain project-bound and should also bind to a model version

1. `mdd_documents` and the legacy file-backed Model Documentation records.
2. `documentation_packages` and exported MDD artifacts.
3. Monitoring plans, baselines, runs, alerts, actions, and their evidence.
4. Implementation/handoff decisions and deployment manifests.
5. Generic evidence items supporting evaluation, interpretation, implementation, or monitoring when their payload lacks a `modelVersionId`.
6. Decision-journal entries for champion approval, implementation approval, threshold approval, and monitoring/revalidation.
7. Validation findings and approvals that evaluate a specific champion.

The correct target is not to remove `project_id`; it is to retain project scope and add the immutable model-version foreign key plus relevant dataset/validation lineage.

### Stale-document behavior

Feature/split/model lifecycle changes can invalidate analytical artifacts, but MDD and monitoring records do not yet have one uniform, database-enforced stale-state propagation mechanism. Add an artifact dependency graph keyed by model version and publish invalidation events transactionally.

## 8. Model-training findings

- Training preflight correctly treats the active split, manifest, target, and source exclusions as governed input.
- Training-only resampling and cross-validation behavior is covered by the current repair/regression contracts.
- Stale-job publication checks compare active dataset/split context before publishing.
- Candidate-level failures are isolated; one failed algorithm does not erase successful candidates.
- Cancellation is supported.

Remaining P1 work:

- Persist queued/running job records and restart recovery.
- Persist an immutable training command, environment identity, library versions, seeds, folds, sampling policy, and artifact checksum before execution.
- Replace raw daemon threads with a bounded executor/worker service.
- Add per-user/project concurrency quotas, queue fairness, timeouts, and memory budgets.
- Make training artifact promotion transactional with model-version creation.

## 9. Evaluation and interpretation risks

- Final-selection integrity is fixed, but some diagnostic paths still derive their context from resident evaluation results rather than loading an immutable registry artifact by model version.
- Multiple expensive diagnostics are synchronous and memory-heavy.
- Small or degenerate samples correctly return unavailable statistics in several paths; this honest-state convention should be applied everywhere.
- Threshold selection, calibration, and candidate ranking should continue to prove that holdout/OOT rows were not used. Add immutable population-role tags to every metric artifact so this can be audited without reading implementation code.
- Interpretation artifacts should be linked to `model_version_id`, dataset version, split/validation design, feature manifest, method parameters, and library versions.

## 10. Scoring, implementation, and monitoring risks

- Final scoring now rejects stale lineage and no longer silently substitutes a ranked candidate when `final` is missing.
- JSON model export is a review manifest, not an executable pickle.
- Scoring-run persistence and model-version linkage are good foundations.

Remaining P1 work:

- Require a registry model version for all production/bulk scoring; keep resident-result scoring explicitly developmental.
- Add asynchronous, bounded bulk scoring over registered immutable dataset versions.
- Bind implementation and monitoring records to the deployed model version.
- Add signed artifact verification and a deployment environment identity.
- Add monitoring baseline versioning and transactional linkage to the exact scoring schema.

## 11. Exact verified defects and fixes

### P0-1 — stale final-model lineage

**Before:** promotion/status/scoring could rely on resident result names and incomplete metadata.
**After:** the service compares project, dataset version, target, problem type, feature manifest, split, validation design, and training job. Missing or mismatched lineage returns a blocker; scoring/export fail closed; the registry receives the complete binding.

Focused files:

- `server/evaluation/eval_service.py`
- `server/evaluation/eval_router.py`
- `server/training/training_job_service.py`
- `tests/predictive_modeling_repair_test.py`

### P0-2 — governance direct-object authorization

**Before:** monitoring and legacy documentation routes could read or mutate project-keyed records after authentication without verifying project permission. Monitoring aggregate routes could include unauthorized projects. Client-supplied document attribution was trusted.

**After:** every monitoring project/direct-object route resolves the record’s project and checks view/edit permission; list/summary results are filtered to authorized projects; documentation project/direct-object/evidence/export routes authorize the document project; cross-project evidence substitution is rejected; document attribution comes from the authenticated user.

Focused files:

- `server/monitoring/router.py`
- `server/monitoring/monitoring_service.py`
- `server/model_documentation/documentation_router.py`
- `tests/predictive_governance_authorization_test.py`

## 12. Recommended remediation order

1. **P1 — durable training execution:** database job records, bounded workers, restart recovery, immutable commands, and artifact checksums.
2. **P1 — model-version foreign keys:** MDD, documentation packages, implementation, decisions, evidence, monitoring, baselines, runs, alerts, actions, and validation.
3. **P1 — production scoring path:** registry-only model selection, signed artifact loading, async registered-dataset scoring, quotas, and reproducibility.
4. **P1 — columnar scale architecture:** Parquet/Arrow/DuckDB working datasets, bounded queries, cached immutable summaries, and memory budgets.
5. **P1 — authenticated browser release pass:** HELOC non-destructive walkthrough, supported viewports, console/network review, and screenshots.
6. **P2 — component decomposition and virtualization:** shared workflow status/lineage components and virtualized wide tables.
7. **P2/P3 — diagnostic caching and route-level code splitting.**

## 13. Items safe to defer

- Cosmetic motion refinements that do not change analytical interpretation.
- Additional chart types where exact tables and existing diagnostics already answer the decision.
- Micro-optimizing small registered datasets.
- Consolidating every compatibility artifact store in one release, provided production paths use the durable repositories.
- Advanced interpretation methods until their lineage, compute bounds, and evidence contract are defined.

## 14. Paid-pilot readiness assessment

**Verdict: conditional.**

Suitable for a controlled, low-concurrency pilot when:

- projects use registered immutable dataset versions;
- the repaired final-model promotion/scoring contract is used;
- administrators understand that active training jobs are not restart-durable;
- production scoring is not represented as fully hardened deployment;
- MDD/monitoring model-version linkage is completed before formal model-risk signoff;
- an authenticated HELOC browser acceptance pass is completed.

Not yet ready for an unconditional multi-user production claim at millions of rows.

## 15. Browser evidence

The in-app browser connected to both `http://127.0.0.1:5174` and `http://localhost:5174`. The ATLAS sign-in page loaded, but no active authenticated session was present and no other browser tab/session was available to claim.

Because credentials were explicitly out of scope:

- no login was attempted;
- no seeded administrator credential was used or derived;
- no protected HELOC page was opened;
- no HELOC state was changed;
- no protected-state screenshot was captured;
- no claim of authenticated Predictive Modeling browser acceptance is made.

The unauthenticated app shell reloaded to DOM content loaded in **737 ms** on the local development server. This is not a measurement of a protected workflow page.

## 16. Test and build evidence

| Check | Result |
|---|---|
| Predictive Modeling repair contract | Passed; source contract plus backend integration, including stale final-model rejection, 360-row full-scope checks, completed training, cancellation, RFE, final readiness, and 288 scored training rows |
| Governance authorization integration | Passed; monitoring direct-object denial, aggregate filtering, MDD project/document/export denial |
| Regression suite | 18/18 passed |
| MDD framework | Passed |
| Model Documentation Studio | Passed |
| Monitoring Center | 8/8 source tests plus backend lifecycle passed |
| Security gate | Passed: 55 behavioral tests across six suites plus 30 structural assertions |
| TypeScript | `npx tsc -b` passed |
| Production modeling build | Passed; 3,414 modules transformed |

Non-failing build findings:

- The main bundle and several analytical chunks exceed the current 500 KB warning threshold.
- The Experimental Design chunk is 991,996 bytes minified / approximately 243 KB gzip.
- Browser compatibility metadata is stale and should be updated in a dedicated dependency-maintenance change.

## 17. Repository safety confirmation

- No file under `audit-output` was modified.
- Existing working-tree changes and untracked artifacts were preserved.
- No reset, clean, restore, stash, stage, commit, push, rebase, or history rewrite was performed.
