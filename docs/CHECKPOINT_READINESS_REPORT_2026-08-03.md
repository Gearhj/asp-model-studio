# ATLAS overnight controlled-checkpoint readiness report

Date: 2026-08-03  
Repository: `C:\Users\james\ds-workflow-starter`  
Audit mode: source freeze, read-only live authority inspection, isolated external validation

## Final checkpoint-readiness verdict

**NOT READY: TEST OR BUILD FAILURE**

The production build and TypeScript compiler are green, but required frontend regression and headless route gates are red. This single allowed verdict is independently reinforced by two additional checkpoint blockers: a non-atomic persistence migration runner and current Predictive preprocessing paths that perform target-directed Outliers/Missing Values analysis over `full_dataset` with client-supplied target semantics.

No repair was implemented during this freeze. No slice is approved for staging.

## 1. Blocking findings

| Severity | Gate | Finding | Disposition |
|---|---|---|---|
| P1 | Frontend regression | 12 of 80 relevant Node test files failed; 17 of 656 TAP cases failed. The required regression wrapper is red at 17/18. | Frozen and reported; no expectation was rewritten. |
| P1 | Backend regression | Five of 61 selected backend files reproduced red results: 16 failed cases and 3 setup errors, primarily from fixtures that no longer satisfy exact identity, Analysis Partition, and target-authority contracts. | Frozen and reported; no fixture or product code was changed. |
| P1 | Headless route smoke | Production Chromium passed Step 00, then stopped at Step 01 because the test expects the retired heading “Source Selection, File Upload, and Target Setup” while the page renders “Data Acquisition.” Steps 02-07 were not exercised. | Frozen and reported; no test bypass or edit. |
| P1 | Migration integrity | An intentionally failing external migration persisted its partial table and row without recording a `schema_migrations` row. The next initialization then failed on the existing table. | Isolated outside the repository; no repair. |
| P1 | Predictive data scope | Outliers and Missing Values still calculate event rate, IV/correlation, and ranking over `scope="full_dataset"`; Outliers accepts client target/event/problem and Missing accepts client event/problem. | Source defect; no live endpoint invoked and no holdout data read. |
| P1 | Generated-code safety | Multiple current production templates contain fabricated loaders/paths or unsafe identifier interpolation across Python, SAS, R, and SQL. | Source defect; no generated code executed. |
| P1 | Test isolation defaults | The default Playwright config points to the live development stack; several tests reference live HELOC or mutable live roots. Only the external controlled harness was used. | Unsafe suites/configurations were skipped or externalized. |

## 2. Repository and Git state

Protected pre-audit baseline:

| Item | Value |
|---|---|
| Branch | `codex/phase2a-canonical-lineage` |
| HEAD | `24961ad4da6566c53cf4634796a439f7498fcc0e` |
| Upstream | `origin/codex/phase2a-canonical-lineage` |
| Ahead / behind | `0 / 0` |
| Modified tracked | 125 |
| Untracked | 96 |
| Deleted tracked | 0 |
| Staged | 0 |
| Pre-audit paths classified | 221 |
| Tracked diff | +80,999 / -5,685 |
| Binary tracked diff entries | 0 |
| Index | empty |

The four checkpoint deliverables are audit-generated untracked documentation and are intentionally outside the 221-path pre-audit classification baseline. The final status is expected to be 125 modified tracked plus 100 untracked paths, with the same empty index. Final verification is recorded in Section 18.

`git -c core.safecrlf=false diff --check` returned exit 0. Git emitted CRLF-conversion warnings under the default Windows configuration, but no whitespace error was reported.

## 3. External safety snapshot

Complete, readable snapshot:

`C:\Users\james\AppData\Local\Temp\atlas-checkpoint-readiness-20260803-233441`

It contains branch/HEAD/upstream metadata, status/name-status/numstat/diff inventories, a working-tree patch, migration/test/documentation manifests, service metadata, database metadata, 630 principal-source hashes, and 900 protected-authority hashes. It contains no copied raw dataset, credential, cookie, token, browser profile, or sealed-holdout row assignment.

An earlier incomplete attempt is preserved without deletion at:

`C:\Users\james\AppData\Local\Temp\atlas-checkpoint-readiness-20260803-233349`

That attempt stopped when Git LF warnings were treated as fatal. It is not used as the baseline.

## 4. Complete working-tree classification

The machine-readable file is `CHECKPOINT_WORKING_TREE_CLASSIFICATION_2026-08-03.csv`. It contains 221 unique, nonblank baseline paths with status, byte size, tracked numstat where available, category, ownership, dependencies, source requirement, commit/never-stage/human-review flags, and slice.

| Category | Meaning | Paths | Tracked | Untracked | Bytes | + / - | Disposition |
|---|---|---:|---:|---:|---:|---:|---|
| A | Production frontend source | 58 | 50 | 8 | 2,526,438 | 7,556 / 1,965 | commit candidate |
| B | Production backend source | 33 | 25 | 8 | 1,563,868 | 6,229 / 592 | commit candidate |
| C | Database migration | 4 | 0 | 4 | 18,722 | — | commit candidate |
| D | Automated test | 77 | 39 | 38 | 1,409,924 | 2,518 / 433 | commit candidate; validation only |
| E | Product/architecture documentation | 3 | 0 | 3 | 89,251 | — | commit candidate after human review |
| F | Runtime authority | 13 | 1 | 12 | 142,713 | 329 / 384 | never stage |
| G | Dataset artifact/metadata authority | 3 | 3 | 0 | 3,120 | 11 / 11 | never stage |
| H | Evidence/MDD authority | 12 | 7 | 5 | 9,634,776 | 64,356 / 2,300 | never stage |
| I | Browser screenshot/audit evidence | 15 | 0 | 15 | 2,639,126 | — | never stage; human review |
| J | Temporary acceptance script | 0 | 0 | 0 | 0 | — | none in baseline |
| K | Cache/generated test output | 3 | 0 | 3 | 652,996 | — | never stage |
| L | Log file | 0 | 0 | 0 | 0 | — | none in baseline |
| M | External/misplaced path | 0 | 0 | 0 | 0 | — | none found |
| N | Ambiguous | 0 | 0 | 0 | 0 | — | none found |

Totals: 175 source/test/documentation commit candidates and 46 never-stage paths. No malformed drive-prefixed filename, embedded-backslash filename, duplicate `.tmp` prefix, misplaced audit path, modified database, tracked deletion, or ambiguous path was found.

Independent QA confirmed:

- 221 CSV paths exactly equal the protected baseline;
- 175 slice paths are unique, with no missing or extra commit candidate;
- 46 exact never-stage paths are unique, with no missing or extra runtime/audit path;
- the slice and never-stage sets have zero intersection;
- all recorded sizes and tracked numstats match.

## 5. Protected live authorities before and after

The baseline and final manifests each contain 900 paths. Every path was hashed through a read-sharing handle so the live SQLite databases could be inspected without journal-mode mutation.

| Comparison | Result |
|---|---:|
| Protected paths before | 900 |
| Protected paths after | 900 |
| Missing after | 0 |
| Hash errors | 0 |
| Changed hashes | **0** |
| Principal-source paths compared | 630 |
| Principal-source hash changes | **0** |

Manifests:

- `...\protected-authority-hashes-before.csv`
- `...\protected-authority-hashes-after.csv`
- `...\principal-source-hashes.csv`
- `...\principal-source-hashes-after.csv`

The live HELOC partition, Dataset Library registry/link/activation, checkpoint, persistence/security databases, target/predictor/partition authorities, evidence/MDD, feature manifests, and model artifacts did not change during the controlled run.

### Current HELOC authority metadata — read only

No source rows, assignment JSON, sealed-holdout positions, or target values were read.

| Authority | Current safe metadata |
|---|---|
| Project | `atlas-mrzpau4t`; active |
| Dataset | `ds_heloc_train_6bdb184b_05905` |
| Exact version | `v_1785186305905_6bdb184b` |
| Durable link | active |
| Activation | active, revision 1 |
| Target contract | `target-contract-9a0bbd69645b7e5e0b4c` |
| Predictor authorization | `predictor-auth-491392549aa93a6ad258`, current |
| Analysis Partition | `analysis-partition-688c2184b4e9b8181946-r1`, revision 1, current |
| Development / sealed holdout | 5,020 / 1,255 of 6,275; 80/20 |
| Holdout status | sealed; isolation verified |
| Assignment checksum | `ed04b51eef3ebfccc846ff742203978ae0463ee871807c6045595b68106bb6c5` |
| Partition artifact checksum | `688c2184b4e9b8181946766e2577c1f1a53f9c88de2adf81a1d3affbc8dcd5fa` |
| Feature manifest | `fm-8e2dc2933912d428`; 28 features; passed/current/confirmed/persisted; split `not_created` |
| EDA documentation | draft; reviewer pending; 7 unresolved blocking findings; latest approval stale/not next-step eligible |
| MDD | working draft `mdd-version-analysis-partition-688c2184b4e9b8181946-r1`; no validated version |
| Candidate/evaluation | no current candidate decision, holdout exposure, or evaluation package |
| Legacy model version | one quarantined/noncurrent `legacy_unresolved` version; no current model pointer |

Items requiring James's attention:

- the project record says project type `predictive-modeling` but workflow type `credit-risk-studio`;
- the current feature manifest is confirmed but still reports split `not_created` while the Analysis Partition is current;
- EDA documentation is stale and not eligible for the next step;
- the relational `datasets`/`dataset_versions` rows for the exact JSON-backed authority remain absent, a previously documented architecture contradiction;
- the only model version is legacy-unresolved and references a historical noncanonical version identifier. It is not current and was not retrieved or promoted.

## 6. Migration audit

| Check | Result |
|---|---|
| Migration count | 27 |
| Ordered range | `0001_initial.sql` through `0027_special_value_reviews.sql` |
| Duplicate identifiers | 0 |
| Numeric gaps | 0 |
| Invalid names/order conflicts | 0 |
| Live ledger | 27/27, none duplicate/missing/extra |
| Fresh install | passed; 27 migrations, integrity `ok`, FK findings 0 |
| Second fresh initialization | passed; schema/ledger/timestamps/counts unchanged |
| Representative 0016→0027 upgrade | passed; six synthetic records retained; integrity `ok`, FK findings 0 |
| Second upgraded initialization | passed; schema/ledger/counts unchanged |
| Live/fresh schema | 223 vs 223 objects; no missing/extra/different definition |
| Failure atomicity | **failed** |

The isolated atomicity probe created a synthetic migration containing `CREATE TABLE`, one `INSERT`, then an intentional invalid `SELECT`. Initialization failed, but the table and row persisted and the ledger row did not. A second initialization failed on `table already exists`. The runner uses `executescript()` inside the Python transaction context, so rollback does not protect the full migration/ledger unit.

Additional migration debt:

- filenames are not validated for sequence/content hash;
- no migration lock or `BEGIN IMMEDIATE` protects concurrent initialization;
- name-only idempotency cannot detect edits to released SQL;
- startup catches persistence failure and retains legacy/local fallback, which can mask a partial schema;
- the security database has no migration/version ledger, although its current five-table schema matches a fresh initialization.

External audit evidence:

`C:\Users\james\AppData\Local\Temp\atlas-checkpoint-migration-audit-20260803-234921-b7f09a73\migration_audit_results.json`

No destructive experiment ran against a live database.

## 7. Test-storage isolation precheck

| Gate | Result |
|---|---|
| Static scanner | passed; 91 Python test sources inspected |
| Focused nonmutating guard cases | 23 passed, 1 intentionally externalized |
| Pre-import rebinding probe | 1 passed from external Windows Temp |
| Full external-harness guard | 24/24 passed after adding only the omitted empty protected-directory scaffold outside the repository |

The canonical scanner was run before broad suites. Every counted mutating process used an external Windows Temp root and was isolated from live persistence, security, Dataset Library, checkpoint, evidence, feature, model, and scoring authorities.

One discarded backend batch accidentally expanded a literal batch prefix and allowed its external processes to share a Temp family. The agent stopped all children, counted none of those results, and relaunched with genuinely unique roots. The shared path was still external; no live or repository authority was targeted.

Known isolation source debt remains:

- the default E2E config targets the already-running `127.0.0.1:5174` stack;
- two visual-intelligence E2E files reference the live HELOC artifact;
- `target_source_exclusion_test.py` can conditionally read that artifact;
- `run_security_tests.py` normally creates/removes repository `.tmp` roots;
- several Node/Python fixtures use repository-relative `.tmp` under a normal checkout;
- `server/python_execution.py` uses repository `.tmp/python-execution` for a production sandbox.

Those paths were not allowed to touch the live checkout in this audit.

## 8. Frontend validation

All counted commands ran from the frozen external source harness with per-process external Temp roots. Exact per-file commands, durations, roots, and logs are in:

`C:\Users\james\AppData\Local\Temp\atlas-checkpoint-readiness-20260803-233441\frontend-validation\consolidated-results.csv`

Summary:

| Metric | Result |
|---|---:|
| Relevant Node test files | 80 |
| Process-pass / process-fail | 68 / 12 |
| TAP cases | 656 |
| TAP pass / fail / skip | 639 / 17 / 0 |
| Static assertion sites | 4,669 |
| Actual Node warning/deprecation lines | 0 |

Red files and frozen signatures:

1. `entryPageIntegrity.test.mjs` — transpiled temp import cannot resolve `projectScopedRoutes`.
2. `predictiveProjectContext.test.mjs` — expects `savePredictiveProjectContextToDatabase`.
3. `predictiveProjectContextWow.test.mjs` — expects `data-testid="model-charter"`.
4. `edaFinalAcceptancePolish.test.mjs` — expects old full-governed-population target-balance scope.
5. `edaVisualIntelligencePhase1.test.mjs` — expects retired target-resolution source text.
6. `edaVisualIntelligencePhase11.test.mjs` — expects retired Python-context `canSave` expression.
7. `governedProfile.test.mjs` — two stale event-rate/legacy-anchor expectations.
8. `preparationReferenceLayout.test.mjs` — expects old “1. Choose Validation Approach” heading.
9. `creditRiskStudio.test.mjs` — 12 stale layout/workflow/source assertions.
10. `modelDiagnostics.test.mjs` — stale cross-page Pozzolo label expectation.
11. `regression.test.mjs` — missing expected `Target Mean`; wrapper result 17/18.
12. `taskContext.test.mjs` — transpiled temp import cannot resolve `scopedTrainingHistory.js`.

The separate `regressionMetricValidator.test.mjs` was not executed because its current contract calls the live backend, can start training, and deletes a project. This safety skip is explicit and cannot be counted as a pass.

## 9. Backend validation

All counted backend files ran from the frozen external source harness. Each file had its own Python process and external authority root. Exact commands, roots, counts, runtimes, and per-file logs are in:

- `C:\Users\james\AppData\Local\Temp\atlas-checkpoint-backend-validation-20260804-000112\batch-a-valid\results.json`
- `C:\Users\james\AppData\Local\Temp\atlas-checkpoint-backend-validation-20260804-000112\batch-b-valid\results.json`
- `C:\Users\james\AppData\Local\Temp\atlas-checkpoint-backend-validation-20260804-000112\batch-c-valid\results.json`
- deterministic reruns: `C:\Users\james\AppData\Local\Temp\atlas-checkpoint-backend-validation-20260804-000112\confirmations`

| Metric | Result |
|---|---:|
| Selected backend files | 61 |
| Pytest-collected files | 60 |
| Passed / failed / errors | 701 / 16 / 3 |
| Skipped / intentionally deselected | 24 / 1 |
| Subtests passed | 147 |
| Warnings | 322 |
| Parallel matrix wall time | 554.5s |
| Sum of isolated per-file runtimes | 1,313.49s |
| Deterministic confirmation wall time | 116.6s |

One script-style authorization file, `predictive_governance_authorization_test.py`, is intentionally not pytest-collectable. Pytest returned exit 5; its canonical direct entry point then passed all six cross-project authorization checks in 15.68s.

Five red files reproduced independently:

1. `dataset_lifecycle_test.py` — 3 passed, 11 failed; its shared registration helper omits the now-required exact expected `dataset_id` and `dataset_version_id`, so registration returns HTTP 422.
2. `phase2a_registration_external_identity_test.py` — 6 passed, 2 failed with `sqlite3.OperationalError: no such table: analysis_partitions`.
3. `project_context_hydration_authority_test.py` — 3 setup errors because its fixture omits the new non-null `analysis_partitions.problem_type` value.
4. `pretraining_artifact_invalidation_test.py` — 3 passed, 2 failed: one fixture lacks `target_semantics_authority` (`KeyError` at `training_job_service.py:1869`), and the other expected stale-input text is preempted by the authoritative missing-target message.
5. `training_job_scope_identity_test.py` — 1 passed, 1 failed because its fixture `SimpleNamespace` lacks `target` (`AttributeError` at `training_job_service.py:1154`).

The 24 skips are explicit missing-fixture/capability skips: eight in `governed_profile_test.py`, five in `iv_reference_test.py`, ten in `target_source_exclusion_test.py`, and one in `project_context_persistence_test.py`. The exact real-grid-search case in `validation_design_training_contract_test.py` was intentionally deselected; its other seven cases passed.

Suites that launch real training, evaluation/scoring, or combined flows were excluded by the safety contract: `model_training_reliability_test.py`, `training_validation_policy_execution_test.py`, `training_holdout_isolation_test.py`, `model_registry_test.py`, `analytical_data_plane_test.py`, `predictive_modeling_repair_test.py`, and the Evaluation/Scoring suites. The safe durability suite `model_registry_durability_test.py` passed 29/29.

Warnings are dependency/deprecation debt (Matplotlib/Pyparsing, Pydantic v2, FastAPI `on_event`, and one pandas date-parsing warning), not live-authority or holdout access. The required backend gate is red.

## 10. Security gate

The canonical containment/security gate passed in the external harness: **62 Python tests plus 30 structural assertions**. Bootstrap/local-development/test-header containment remained fail-closed by default. No authentication bypass, development impersonation default, credential, cookie, token, or live security authority was used.

The live security database was opened read only. Its schema matches a fresh isolated initialization, and integrity is `ok`. It retains 67 known historical `credentials -> users` foreign-key findings; no cleanup or write occurred.

## 11. TypeScript, build, Python compilation, and diff hygiene

| Gate | Result |
|---|---|
| `npx.cmd tsc -b --pretty false` | passed; 46.076s; no diagnostics |
| `npm.cmd run build:modeling` | passed; wall 75.483s; Vite 30.03s; 3,439 modules |
| Python `compileall` | passed; 8.448s; bytecode redirected externally |
| `git diff --check` | passed after suppressing line-ending advisory output |

Build warnings, not failures:

- `baseline-browser-mapping` data is more than two months old;
- `caniuse-lite` data is nine months old;
- `largeDataPolicy.ts` is both statically and dynamically imported and will not split;
- chunks larger than 500 kB: main 598.12 kB, EChartsPanel 715.36 kB, ExperimentalDesignWorkflowPage 992.00 kB.

The first sandboxed build attempt failed with `spawn EPERM`; the authorized external-harness retry passed. This was a sandbox process-launch restriction, not a compiler/source failure.

## 12. Database integrity

### Persistence database

Read-only checks:

- 77 user tables, 223 schema objects, 123 named indexes, 23 triggers, and 64 foreign-key definitions;
- `PRAGMA integrity_check`: `ok`;
- `PRAGMA foreign_key_check`: 312 findings, exactly matching the previously documented debt:
  - `decision_journal -> projects`: 182;
  - `evidence_artifacts -> projects`: 113;
  - `project_collaborators -> projects`: 17;
- current-pointer and uniqueness anomaly checks: 0;
- live/fresh schema difference: 0.

Known metadata orphans remain:

- one Analysis Partition lacks relational `datasets` and `dataset_versions` parents;
- one legacy model version lacks those relational parents.

The exact authority remains present in JSON Dataset Library/link/activation storage. Counts did not increase during this run, and no historical debt was described as newly introduced.

### Security database

- five tables; integrity `ok`;
- 67 known historical `credentials -> users` findings;
- fresh/double initialization: stable empty schema, integrity `ok`, FK findings 0;
- no migration/version ledger exists.

## 13. Source scans

### Blocking current-source matches

1. `server/preprocessing/outlier_router.py`, `outlier_service.py`, and `src/steps/Step04_Outliers.tsx` accept/propagate browser target semantics and compute target-informed metrics over `full_dataset`.
2. `server/preprocessing/missing_router.py` and `src/steps/Step04_MissingValues.tsx` accept/propagate client event/problem semantics and compute target-informed missingness/IV/correlation over `full_dataset`.
3. Generated-code paths with fabricated loaders/paths or unsafe interpolation occur in Time Series Data Acquisition/templates, `WorkflowPlaceholderStep.tsx`, `IntelligentWorkbench.tsx`, `ChartStudio.tsx`, the Credit Risk scorecard engine, Model Diagnostics SAS output, and `notebookExport.ts`.
4. Default/live-root test references occur in Playwright config, two EDA visual-intelligence specs, `target_source_exclusion_test.py`, and the normal security-runner `.tmp` setup.

### Nonblocking/legacy matches requiring later review

- first/latest project, dataset, version, and model fallbacks remain in noncanonical Studio/utility surfaces;
- `notebookExport.ts` contains target-directed work from a generic `TRAIN.csv` template before exact partition binding;
- `analyticsWorkbench.test.mjs` imports live runtime SAS configuration for structural checks;
- the production Python execution sandbox defaults inside repository `.tmp`.

### Clean or intentional dispositions

- no hardcoded live project/dataset/version ID in production source;
- live-ID matches are confined to test fixtures, documentation, audit evidence, or runtime authority;
- project-scoped Predictive routes are authoritative; `/stepXX` paths are compatibility redirects only;
- no direct `location.reload()` in source;
- no enabled-by-default authentication bypass or development impersonation;
- no arbitrary current/latest Analysis Partition fallback;
- EDA does not directly materialize holdout rows, and candidate selection/threshold code rejects holdout evidence;
- no static production import of `.runtime`, `server/artifacts`, `audit-output`, `.tmp`, or test-results JSON;
- inspected global listeners have paired cleanup and scoped event validation;
- no unresolved merge-conflict marker or temporary security bypass marker.

## 14. Production-build headless route smoke

Command family: Playwright Chromium, one worker, headless, disposable production Vite preview, external Temp/output/profile roots.

| Item | Result |
|---|---|
| Build | passed |
| Step 00 Project Context | passed exact scoped URL, project, dataset/version, and render checks |
| Step 01 Data Acquisition | page rendered, but stale heading expectation failed |
| Steps 02-07 | not reached |
| HTTP 5xx | 0 |
| Console errors | 0 |
| Page errors | 0 |
| Training/completion mutations | 0 |
| Final/sealed-holdout request matches | 0 |
| Preview shutdown | confirmed; port no longer reachable |

Exact failure: `tests/e2e/predictive-route-integrity-matrix.spec.ts:930` expected `/Source Selection, File Upload, and Target Setup/i`; the current page says `Data Acquisition`.

The spec intercepts all `/api/**` traffic with synthetic auth/project/dataset/workflow responses. Therefore it validates UI composition only; it does **not** satisfy the requested real isolated-database integration gate. This limitation and the incomplete Step 02-07 traversal are blockers.

Evidence:

`C:\Users\james\AppData\Local\Temp\atlas-route-matrix-20260804-000357-pwweb`

No live service, HELOC project, credential, training job, completion action, or holdout endpoint was used.

## 15. Current feature dependency graph

```text
S1 security/storage + identity + migrations 0024-0027
  -> Analysis Partition / predictor authorization / special-value authority
  -> activation and derivative invalidation
  -> S2 project-scoped routing + authoritative Project Context
       -> S3 Data Acquisition UX + reproducibility
            -> S4 development-only EDA + Target Intelligence
       -> S5 Validation Design + governed training lineage

S5 functional acceptance also depends on S3 and S4.
```

Two lifecycle feedback paths are intentional, not compile-time cycles:

- activation/target/predictor changes invalidate the Analysis Partition, while current partition status gates Data Acquisition readiness;
- partition reset invalidates feature manifests, model documentation, and evidence.

Runtime F/G/H authorities are preserved inputs/outputs. They are never source dependencies to stage.

## 16. Proposed slices and never-stage policy

Exact five-slice Bash manifests are in `CHECKPOINT_PROPOSED_COMMIT_SLICES_2026-08-03.md`:

| Slice | Paths | Depends on |
|---|---:|---|
| S1 governed identity/Analysis Partition authority | 43 | security/storage foundation |
| S2 project-scoped routing/Project Context | 58 | S1 |
| S3 Data Acquisition UX/reproducibility | 24 | S1, S2 |
| S4 EDA development scope/Target Intelligence | 32 | S1, S2, S3 |
| S5 Validation Design/training lineage | 18 | S1, S2; functional acceptance after S3/S4 |

No command was executed. S1 and all dependent slices remain unapproved.

The exact 46-path and pattern-based never-stage policy is in `CHECKPOINT_NEVER_STAGE_MANIFEST_2026-08-03.md`. Important: live JSON authorities already tracked by Git cannot be protected by `.gitignore`; use exact positive manifests and inspect the index.

## 17. Files requiring James's review

- the three pre-existing architecture/product reports before any future documentation slice;
- all 13 feature/VIF runtime authorities;
- all three Dataset Library/recovery authorities;
- all 12 EDA/evidence/MDD authorities;
- all 15 prior browser/audit files, whose JSON result files record failed acceptance;
- the current project-type/workflow-type contradiction and stale EDA documentation state;
- whether selected sanitized audit screenshots should be retained outside source control.

Default disposition for every runtime/evidence/audit item is preserve locally and never stage.

## 18. Final services and Git verification

| Service | Baseline PID | Final PID | Command provenance | Health |
|---|---:|---:|---|---:|
| Frontend `127.0.0.1:5174` | 86880 | 86880 | repository `node_modules/.../vite.js --mode modeling --host 127.0.0.1 --port 5174 --strictPort` | HTTP 200 |
| Backend `127.0.0.1:8001` | 89928 | 89928 | listener child of repository `.venv` Uvicorn parent PID 83500 | HTTP 200, `{"ok":true,"status":"running"}` |

The controlled tests did not stop or restart either live service. No service restart was necessary.

Final Git verification after all four permitted deliverables were present:

- branch: `codex/phase2a-canonical-lineage` (unchanged);
- HEAD: `24961ad4da6566c53cf4634796a439f7498fcc0e` (unchanged);
- upstream: `origin/codex/phase2a-canonical-lineage`, ahead/behind `0/0`;
- index: empty, with **0 staged paths**;
- working tree: **225 paths** = 125 modified tracked + 100 untracked + 0 deleted;
- set comparison: the original 221 paths remain present and the only four additions are the four requested checkpoint deliverables;
- principal-source comparison: 630/630 paths unchanged, 0 missing, 0 hash changes;
- protected-authority comparison: 900/900 paths unchanged, 0 missing, 0 hash changes, 0 read errors.

No Git mutation or source/runtime-authority mutation was performed.

## 19. Morning checklist for James

1. Review the **NOT READY** verdict and blockers.
2. Confirm the Git index is empty.
3. Review `CHECKPOINT_NEVER_STAGE_MANIFEST_2026-08-03.md`.
4. Review `CHECKPOINT_PROPOSED_COMMIT_SLICES_2026-08-03.md`.
5. Open the live HELOC project without performing completion actions.
6. Verify Project Context remains stable.
7. Verify the consolidated Data Acquisition page.
8. Confirm Analysis Partition `analysis-partition-688c2184b4e9b8181946-r1`, revision 1.
9. Confirm the Python and SAS context text is accurate and does not fabricate paths.
10. Confirm the protected-authority comparison still shows zero changes.
11. Reject staging until the migration, source-scope, frontend regression, and complete route-smoke blockers are repaired and rerun.
12. Never use `git add -A`, `git add .`, or `git add -u`.
13. Resume the page-by-page workflow at EDA only after a later checkpoint decision.

## 20. Remaining limitations

- Real-training, Evaluation, and Scoring suites were excluded by the task safety boundary and are not claimed as passing evidence.
- The required real isolated-database browser matrix through Model Training does not currently exist; the available route spec mocks API transport.
- The route smoke stopped at Step 01, so no current Step 02-07 browser evidence is claimed.
- One intentionally unsafe frontend test was skipped instead of being allowed to train/delete against a live service.
- Current foreign-key debt and relational-vs-JSON Dataset Library divergence remain unresolved.
- No browser heap metric was collected; this was not a stability soak.
- No historical runtime/evidence file was deleted, repaired, normalized, or staged.

## 21. Scope and safety confirmations

- The live HELOC partition and all 900 protected authority hashes are unchanged.
- No sealed-holdout rows, positions, assignment JSON, or values were accessed or emitted.
- No training, Evaluation, Interpretation, promotion, Model Registry mutation, or Scoring occurred.
- No product source or existing test was edited.
- Only the four requested checkpoint documents were created in the repository.
- The Git index remained empty; no staging or commit command was executed.
- Nothing was committed, pushed, reset, restored, cleaned, amended, rebased, merged, cherry-picked, stashed, or discarded.
- No pre-existing repository, runtime, audit, screenshot, report, or untracked item was deleted. Test runners only managed their own external disposable process/profile lifecycle.
- No credential, password, token, cookie, API key, authentication header, connection string, or browser-session data was printed or retained.
- No application environment-variable value was printed; only the required isolated external Temp evidence roots are recorded.
- No automatically generated staging command was executed.

Stop condition met: this report documents checkpoint readiness only. No feature implementation or downstream modeling phase was started.

---

## 2026-08-04 checkpoint-blocker remediation appendix

The focused remediation repaired the original five backend red files, aligned the 12 stale/frontend-fixture files with the accepted contracts, implemented transactional migration execution, and added exact development-population scope controls. Those focused results were provisional because the mandatory final one-frozen-state matrix had not yet run.

During the pre-freeze protected-authority audit, 2 of 900 protected paths changed byte hashes: `server/artifacts/security/atlas_security.db` and `server/data/atlas_local.db`. No protected path was missing. Both original listeners (frontend PID 86880 and backend PID 89928) had also disappeared before the planned controlled restart. The safe logical HELOC partition metadata still matched project `atlas-mrzpau4t`, dataset `ds_heloc_train_6bdb184b_05905`, version `v_1785186305905_6bdb184b`, partition `analysis-partition-688c2184b4e9b8181946-r1`, revision 1, but the byte-level stop condition is authoritative.

Work stopped immediately. No restore, deletion, migration of the live database, service restart, final gate, training, Evaluation, Interpretation, promotion, or Scoring was performed after detection.

**Updated verdict: NOT READY: RUNTIME ISOLATION FAILURE**

Full evidence and remediation status are documented in `CHECKPOINT_BLOCKER_REMEDIATION_REPORT_2026-08-04.md`. The original 2026-08-03 red verdict and results above remain historical and were not rewritten.
