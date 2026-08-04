# ATLAS Data Acquisition Information Architecture Report

Date: 2026-08-03 (acceptance completed 2026-08-04 UTC)  
Repository: `C:\Users\james\ds-workflow-starter`  
Branch: `codex/phase2a-canonical-lineage`  
HEAD: `24961ad4da6566c53cf4634796a439f7498fcc0e`

## 1. Exact before-change repetition inventory

Counting basis: the completed registered-library state, with the Atlas Guide, sidebar, breadcrumbs, generated code, and deliberately opened technical provenance excluded.

| Field | Before occurrences | Principal before locations |
|---|---:|---|
| Dataset display name | 9, plus 1 transient load message | Hero, status strip, selector, loaded identity, asset card, Current Dataset Summary, lineage |
| Dataset ID | 1 normally | Registered-asset card; conditional reactivation/registration notices added occurrences |
| Dataset-version ID | 5, plus 1 transient | Selector, loaded identity, asset narrative/stat, Current Dataset Summary |
| Full governed row count | 11 | Hero, selector, asset card, Target Distribution, Current Dataset Summary, preview, readiness, quality, bureau scope |
| Source column count | 7 | Hero, import status, asset card, Current Dataset Summary, preview, readiness, quality |
| Target name | 11 | Hero, status, Target Setup, Target Distribution, Current Dataset Summary, preview, exclusion row, partition |
| Positive value | 3 | Target input, chart label, mapping metric |
| Negative value | 3 | Target input, chart label, mapping metric |
| Full-population event count | 2 | Target Distribution metric and chart |
| Full-population event rate | 5 | Target Distribution, preview, readiness, quality |
| Authorized predictor count | 0 | Not rendered from backend authority |
| Selected predictor count | 2 | Status strip and Current Dataset Summary |
| Evaluated predictor count | 1 | Governed profile summary |
| Registration state | 4 | Hero, status, registered-asset heading/stat |
| Project-link state | 5 | Hero, status, asset narrative/badge/stat |
| Load state | 6, plus 1 transient | Hero, status, load action, loaded identity, seven-row checklist, preview note |
| Analysis Partition identity | 2 | Readiness/status and current-partition summary |
| Development count | 2 scoped occurrences | Predictor analytical scope and current-partition summary |
| Holdout count | 1 | Current-partition summary |

Before source anchor: `Step01_DataAcquisition.tsx` SHA-256 `882387464EE19DA20122C686490DB45583EB1923F485C5A14A5AFAC3EE0DFBCB`.

## 2. Exact after-change repetition inventory

| Field | After occurrences | Retained visible locations |
|---|---:|---|
| Dataset display name | 4 | Data Contract, selector, successful-load identity, lineage |
| Dataset ID | 0 normally | Technical provenance only |
| Dataset-version ID | 3 | Data Contract, version selector, successful-load identity |
| Full governed row count | 6 | Data Contract, scope strip, selector label, Target Distribution, preview scope, special-value scope |
| Source column count | 2 | Data Contract and Predictor Authorization Funnel |
| Target name | 8 | Data Contract, Target Setup, Target Distribution, preview header, funnel exclusion, partition stratification |
| Positive value | 4 | Data Contract mapping, Target Setup, distribution mapping, chart class label |
| Negative value | 3 | Target Setup, distribution mapping, chart class label |
| Full-population event count | 2 | Target Distribution metric and chart |
| Full-population event rate | 2 | Target Distribution metric and chart |
| Authorized predictor count | 2 | Data Contract and backend-authoritative funnel |
| Selected predictor count | 1 | Funnel, explicitly “Analyst-selected” |
| Evaluated predictor count | 2 | Funnel and analytical-coverage summary |
| Registration state | 3 | Data Contract metric/chip and collapsed provenance summary |
| Project-link state | 3 | Data Contract metric/chip and collapsed provenance summary |
| Load state | 4 | Status chip, action, loaded identity, collapsed success disclosure |
| Analysis Partition identity | 2 | Current-status identity and current-partition summary |
| Development count | 3 | Scope strip, analytical scope, current-partition summary |
| Holdout count | 2 | Scope strip and current-partition summary |

Conditional additions are limited to the transient success message, explicit-reactivation notice, or an opened provenance disclosure. Current source anchor: `Step01_DataAcquisition.tsx` SHA-256 `B66AAC9BE6AC8F6F76B6FAC58E254AD6823231939802B39C464F00369457F9D0`.

## 3. Before-and-after main-content scroll height

Measured at 1920 × 897:

| Measurement | Before | After | Change |
|---|---:|---:|---:|
| Document scroll height | 7,367 px | 6,859 px | −508 px (−6.90%) |
| Main-content scroll height | 7,241 px | 6,700 px | −541 px (−7.47%) |
| Summary/status blocks | 12 | 11 | −1 |
| Visible disclosures | 2 | 3 | +1 |
| Expanded disclosures | 1 | 1 | unchanged |
| Horizontal overflow | none | none | unchanged |

The preferred 25% reduction was not reached. The implemented 7.47% reduction removes repeated identity/readiness surfaces while leaving every requested analytical table and directly discoverable decision workspace visible. The stronger special-value workspace also consumes deliberate vertical space.

## 4. Before-and-after information architecture

Before: hero; status strip; Source Selection/File Upload/Target Setup; registered-asset card; Current Dataset Summary; Data Preview; repeated readiness and identity rails; bureau review; variable summary; partition; duplicated Data Lineage headings; collapsed code.

After:

1. Source and Target
2. Data Quality
3. Credit Bureau and Special Values
4. Predictor Authorization
5. Development and Final Evaluation Populations
6. Data Lineage and Reproducibility

A sticky six-item navigator provides active-section state, completion state, unresolved badges, mouse navigation, keyboard activation, focus visibility, and stable in-page scrolling without reloading or changing the project-scoped route.

## 5. Canonical Data Contract design

The existing dark header is now the single canonical Data Contract. Its backend-derived fields are dataset, exact version, eligible population, source columns, target/event mapping, authorized predictors, source type, registration, project link, and Analysis Partition. Compact chips show registered, linked, version loaded, target confirmed, predictor authorization, and partition state. A four-scope strip distinguishes full governed population, browser preview, development population, and sealed final holdout.

## 6. Sections removed, merged, or collapsed

- Removed the standalone Current Dataset Summary.
- Removed the second large registered-asset summary rail.
- Removed repeated general identity from Data Quality.
- Removed repeated full-population event rate from unrelated cards.
- Removed the duplicate inner Data Lineage heading.
- Collapsed the completed seven-stage load checklist behind “Dataset loaded and verified / 7 of 7 checks completed / View load details.”
- Collapsed owner, internal IDs, hashes, registration detail, and link detail into dataset provenance.
- Kept browser-session and advanced lineage details as progressive disclosures.

## 7. Unique analytical functionality preserved

Target selection/mapping, full-population class distribution, preview table, horizontal table scrolling, duplicate/null/constant/NZV/datatype/cardinality/leakage/outlier/special findings, bureau detection signals, per-code statistics and treatments, predictor selection and IV coverage, partition preview/current identity, evidence/MDD lineage, and code copy/download actions remain available. Bureau codes remain separate from nulls and ordinary outliers.

## 8. Predictor Authorization Funnel and count reconciliation

The funnel is returned by the reproducibility-context backend from the exact predictor-authorization manifest. It displays named stages: source columns; target exclusions; candidate predictors; analyst-selected predictors; authorized predictors; additional exclusions; analytically evaluated predictors; and model-ready status. Every exclusion contains its field and reason. Browser `headers.length` or selected-checkbox counts cannot override backend authority. In the isolated fixture, 3 source columns − `bad_flag` target exclusion = 2 candidate/selected/authorized predictors; model-ready status remains explicitly not established in Data Acquisition.

## 9. Special-Value Treatment visual design

The section now uses a deep indigo decision header, light working surface, dark table header, purple special-value semantics, amber unresolved state, green reviewed state, sticky variable navigation, selected-variable emphasis, backend revision/evidence state, and a readable 12-column governed table. The upper attention callout appears only after durable status resolves; it no longer flashes a misleading 0 detected/0 unresolved loading state.

## 10. Special-value completion behavior

The durable backend contract is blocking. Open decisions, unsaved drafts, load errors, or an unconfirmed durable review disable continuation. The footer states the exact unresolved count and “Complete Special-Value Review to Continue.” Zero detected variables persist `not_required`; confirmed reviews require zero open decisions. Local storage is a draft cache only, never confirmation authority.

## 11. New-project split behavior

An isolated project with no current partition shows exactly 70/30, 80/20 (Recommended), and 90/10. Seed 42 and target stratification are fixed. Backend preview returns exact population counts and target sufficiency before “Create & Seal Analysis Partition” is enabled. No ratio is accepted from browser calculation alone.

## 12. Current-partition Change Split Ratio behavior

A current sealed partition remains read-only and hides initial creation controls. The primary action is “Change Split Ratio,” not “Reset Analysis Partition.” The current ID, revision, split, membership counts, seed, stratification, seal, evidence, and MDD remain visible while no change is active.

## 13. Impact review and reset/revision behavior

Change Split Ratio opens a governed impact workspace listing downstream artifacts that become stale. A different standard ratio, backend reset preview, exact current partition ID/revision, rationale, acknowledgement, and concurrency-bound preview fingerprint are required. Normal post-seal `/preview` still fails closed with HTTP 409; `/reset-preview` is explicit, deterministic, and non-mutating. Confirmation creates a new revision only after exact validation. Isolated acceptance moved 70/30 revision 1 to 90/10 revision 2; the prior sealed revision was preserved for audit.

## 14. Step 6 remains read-only for partition membership

Training and Validation Design rendered the exact revision-2 partition as a read-only reference: partition IDs, 162/18 counts, 90/10, deterministic method, seed 42, target stratification, seal, evidence, and MDD. It did not expose editable ratio, seed, or stratification controls. CV, balancing, class weights, TEST, OOT, and external-validation policies remain Step 6 responsibilities.

## 15. Python context contract

GET `/api/data/reproducibility-context` returns exact confirmed metadata only: project, dataset name/ID/version, target and event mapping, authorized predictors, exclusions, authorization ID, partition ID/revision, development count, and protected holdout count. Generated Python uses JSON-safe literals, provides supported metadata/API guidance, assumes no local path, exposes no assignments or rows, and marks final holdout as protected metadata only. Stale or unconfirmed selection clears current code.

## 16. SAS context contract

The SAS tab emits safely quoted macro variables and SAS name literals for target/predictors. It does not fabricate a `LIBNAME`, `CASLIB`, DSN, physical path, schema, or table. When no supported direct loader exists, it emits verified context and an explicit no-path assumption. Copy/download output uses the same generated source shown on screen.

## 17. Code-safety behavior

Python values are double-encoded through JSON-safe serialization. SAS character values double embedded quotes; column names use `sasColumnReference`. Adversarial dataset/column-name tests cover Python and SAS injection. The endpoint excludes row data, target aggregates, assignments, artifact paths, and holdout-access material. Source scans found no acceptance-specific IDs, direct reload, unsupported loader, or fabricated Data Acquisition binding.

## 18. Exact files changed in this phase

Config:

- `package.json`

Server/migrations:

- `server/analysis_partition/__init__.py`
- `server/analysis_partition/router.py`
- `server/analysis_partition/service.py`
- `server/analysis_partition/types.py`
- `server/core/metadata_router.py`
- `server/persistence/migrations/0027_special_value_reviews.sql`
- `server/persistence/repositories/__init__.py`
- `server/persistence/repositories/special_value_review_repository.py`
- `server/persistence/service.py`
- `server/preprocessing/bureau_detection_router.py`
- `server/preprocessing/bureau_detection_types.py`
- `server/preprocessing/special_value_review_service.py`

Frontend:

- `src/components/BureauReviewPanel.tsx`
- `src/components/StepPythonPanel.tsx`
- `src/components/code/CodeLanguageTabs.tsx`
- `src/components/code/CodeWorkspacePanel.tsx`
- `src/components/dataAcquisition/DataAcquisitionSectionNav.tsx`
- `src/components/dataAcquisition/DatasetLoadProgressPanel.tsx`
- `src/lib/bureauDetection.ts`
- `src/lib/dataAcquisitionReproducibility.ts`
- `src/steps/Step01_DataAcquisition.tsx`

Tests/report:

- `tests/analysis_partition_contract_test.py`
- `tests/analysis_partition_product_completion_test.py`
- `tests/analysisPartitionProductCompletionFrontend.test.mjs`
- `tests/analysisPartitionResetUxContract.test.mjs`
- `tests/bureau_detection_exact_binding_test.py`
- `tests/bureauDetectionExactBinding.test.mjs`
- `tests/codeWorkspaceUx.test.mjs`
- `tests/data_acquisition_reproducibility_context_test.py`
- `tests/dataAcquisition.test.mjs`
- `tests/dataAcquisitionReproducibility.test.mjs`
- `tests/dataAcquisitionStatus.test.mjs`
- `tests/dataAcquisitionUx.test.mjs`
- `tests/dataAcquisitionUxRefinement.test.mjs`
- `tests/edaEntryReadinessContract.test.mjs`
- `tests/predictiveModelingRepair.test.mjs`
- `tests/special_value_review_contract_test.py`
- `docs/DATA_ACQUISITION_INFORMATION_ARCHITECTURE_REPORT_2026-08-03.md`

## 19. Tests added and updated

Focused coverage now verifies the canonical summary, reduced repetition, collapsed/native load disclosure, section navigation, preview scope, backend funnel, special hierarchy/completion, durable special review, three split choices, explicit reset preview, concurrency fingerprint, Step 6 read-only inheritance, exact Python/SAS context, escaping, no fabricated binding, no holdout data, route stability, EDA entry readiness, restart recovery, and storage isolation.

## 20. Commands run

Repository/safety: `git status --short`, `git branch --show-current`, `git rev-parse HEAD`, `git log -10 --oneline`, `git diff --check`, `git diff --stat`, `git diff --name-status`, `git diff --cached --name-only`, and `git ls-files --others --exclude-standard`.

Primary validation commands:

- `node --test` with the 25-file Data Acquisition/frontend regression matrix.
- `npx tsc -b`.
- `npm run build:modeling`.
- `python scripts/run_security_tests.py`.
- `.venv\Scripts\python.exe scripts\check_test_storage_isolation.py`.
- `.venv\Scripts\python.exe -m py_compile` on changed backend modules.
- `.venv\Scripts\python.exe -m pytest -p no:cacheprovider` for reproducibility, special review, bureau binding, predictor authorization, target distribution/exclusion, partition, identity, persistence, EDA, MDD, and related regressions.
- `.venv\Scripts\python.exe .tmp\data_acquisition_post_acceptance_harness.py`.
- Read-only `sqlite3 -readonly` metadata queries for protected HELOC authority.
- `rg` scans for duplicate summaries, live IDs, reloads, unscoped routes, direct holdout access, fabricated paths/loaders/SAS bindings, and unsafe interpolation.

## 21. Exact validation results

- Final frontend matrix: 209 tests, 209 passed, 0 failed/skipped/cancelled; 13.1 s.
- Final focused post-visual-QA matrix: 22 tests, 22 passed; 1.50 s.
- Final TypeScript compilation: exit 0; 57.2 s on the final source graph.
- Final production build: 3,439 modules, exit 0, 34.73 s. Non-failing warnings: stale baseline-browser/caniuse data, one existing dynamic/static import overlap, and chunks over 500 kB.
- Reset-preview backend matrix: 80 unique tests passed, 0 failed/skipped. The focused 4-test invocation also passed with 28 deselected. Runtimes: 8.95 s, 14.05 s, 40.87 s, 80.81 s, and 7.29 s by suite. Warnings: 12 Matplotlib/PyParsing and 4 pandas third-party deprecations.
- Broader backend regression run: 347 pytest cases plus 64 subtests passed; 1 documented skip; no failure.
- Security gate: 7 behavioral groups plus 1 structural group; 62 behavioral tests and 30 structural assertions passed; 288 s. Non-failing anyio stream and Pydantic deprecation warnings were recorded.
- Storage-isolation guard: 91 Python sources inspected; passed; 86.2 s.
- Python compilation: exit 0.
- `git diff --check`: exit 0; only working-copy line-ending and inaccessible pytest-cache warnings were emitted by Git status/diff enumeration.

## 22. Browser acceptance results

Complete UUID-isolated production-browser run: passed in 78.098 s.

- Project: `project_397ab4153f8640eba7e3f89000192725`
- Dataset: `ds_isolated-data-acquisition-dataset_437b001b`
- Version: `v_1785811767801_437b001b`
- Activation revision: 1
- Target contract: `target-contract-687b077780b8517d11af`
- Predictor authorization: `predictor-auth-fc0495350dc56da2718f`
- Initial partition: `analysis-partition-6b7a28208adaaff9e533-r1` (70/30, revision 1)
- Changed partition: `analysis-partition-87c372152855a9a7bed4-r2` (90/10, revision 2)
- Backend PID in isolated restart: 81876 → 62352; health HTTP 200.
- Recovery: exact project/dataset/version/target/authorization/partition restored; no fallback.
- Diagnostics: 0 page errors, 0 unexpected console errors, 0 unexpected HTTP errors, 0 forbidden requests, and 0 holdout-data requests. One pre-partition status HTTP 409 was explicitly expected.
- Python/SAS exact identity: passed. Unsupported loader/fabricated SAS binding: absent.
- Step 6 exact read-only partition: passed.

A supplemental UUID-isolated run captured the collapsed seven-stage load result. It later stopped on a harness wait-string mismatch after the screenshot; this did not alter production and is not used as the complete workflow result.

The earlier complete run's element-only restart PNG was blank even though its exact-identity assertions passed. It was superseded by the complete run above, whose 209,710-byte full-viewport recovery image was visually inspected and shows partition revision 2 after restart. One sandboxed replacement attempt stopped before browser startup on `spawn EPERM`, and one attempt reached the opt-in collapsed-load branch before encountering its stale wait text; neither reached live authority or changed production. The final default workflow run above passed.

## 23. Screenshot paths

Before evidence root:

- `.tmp/atlas_project_context_restart_soak_3e7641c2fdf14b0cad6747581043b059/screenshots/data-acquisition-before-1920x897.png`
- `.tmp/atlas_project_context_restart_soak_3e7641c2fdf14b0cad6747581043b059/screenshots/data-acquisition-before-full-page.png`

Complete after evidence root: `.tmp/atlas_project_context_restart_soak_b584fe1933df42c28738a4989d4d2969/screenshots/`

- `data-acquisition-after-canonical-header.png`
- `data-acquisition-after-target.png`
- `data-acquisition-after-quality.png`
- `data-acquisition-after-special-values.png`
- `data-acquisition-after-predictor-funnel.png`
- `data-acquisition-after-new-project-ratios.png`
- `data-acquisition-after-current-partition.png`
- `data-acquisition-after-python-context.png`
- `data-acquisition-after-sas-context.png`
- `data-acquisition-after-split-impact.png`
- `data-acquisition-after-split-result.png`
- `data-acquisition-after-step6-read-only-partition.png`
- `data-acquisition-after-restart-recovery.png`
- `data-acquisition-after-full-page.png`

Collapsed-load supplemental evidence:

- `.tmp/atlas_project_context_restart_soak_338b18340c5545ce9794d49495e621d7/screenshots/data-acquisition-after-collapsed-load.png`

## 24. Final frontend/backend PIDs and health

Normal services before restart: frontend listener 73416 (npm root 83312), backend listener 80784 (virtual-environment root 84744). Both ports were verified closed. Final listeners: frontend 86880, backend 89928. `http://127.0.0.1:5174/` returned HTTP 200 and `http://127.0.0.1:8001/api/health` returned HTTP 200.

## 25. Protected-authority comparison

Byte-identical before/after: Dataset Library registry, project links, evidence registry, EDA documentation authority, current feature manifest, MDD document, and MDD index.

The shared `.runtime/workflow_checkpoint.json` and `server/data/atlas_local.db` container hashes changed while a separate live browser session continued workflow autosaves. This phase never opened the live HELOC project in its browser harness. Read-only semantic comparison proves the protected contract stayed exact:

- Active dataset: `atlas-mrzpau4t` / `ds_heloc_train_6bdb184b_05905` / `v_1785186305905_6bdb184b`, activation revision 1, active.
- Project link: exact dataset, active, timestamps unchanged.
- Partition: `analysis-partition-688c2184b4e9b8181946-r1`, revision 1, current.
- Counts: 6,275 total; 5,020 development; 1,255 final holdout.
- Policy: 80/20, seed 42, target stratification by `bad_flag`.
- Assignment checksum: `ed04b51eef3ebfccc846ff742203978ae0463ee871807c6045595b68106bb6c5`.
- Artifact checksum: `688c2184b4e9b8181946766e2577c1f1a53f9c88de2adf81a1d3affbc8dcd5fa`.
- Final holdout: sealed; isolation verified; evidence and MDD recorded.

No row-assignment JSON or holdout values were selected during this comparison.

## 26. Remaining limitations

- Default page height fell 7.47%, short of the preferred 25% target, because core analytics and decision controls remain visible.
- Evaluated-predictor count and partition ID each retain two deliberately scoped occurrences.
- Shared runtime checkpoint/database hashes cannot remain byte-stable while another live session autosaves; semantic protected-record verification is therefore required.
- The supplemental collapsed-load run stopped after capture on a harness-only wait-string mismatch; the independent complete acceptance run passed every governed workflow/restart checkpoint.

## 27. Recommended commit slice

Commit only the 39 files listed in section 18 after a human reviews overlap with the pre-existing dirty tree. Keep Data Acquisition UI, reproducibility backend, durable special review, explicit partition reset preview, focused tests, package test script, and this report in one intentional slice because the contracts are interdependent.

## 28. Files that must not be staged

Do not stage `.tmp/**`, `dist/**`, `.runtime/**`, `server/data/**`, `server/artifacts/**`, `audit-output/**`, `test-results/**`, caches, isolated databases, isolated screenshots unless intentionally archived elsewhere, or unrelated pre-existing dirty source/tests. The safety snapshot remains outside the repository at `C:\Users\james\AppData\Local\Temp\atlas-data-acquisition-ux-20260803-191337`.

## 29. Project Context confirmation

Project Context was not redesigned. No Project Context source file has a modification time after the phase baseline (`2026-08-03T23:13:38Z`). Existing dirty Project Context-related files predate this phase. Its lifecycle/persistence regressions remained green.

## 30. Live HELOC partition confirmation

The live HELOC Analysis Partition was not reset, replaced, revised, or recreated. Its exact metadata and checksums match the pre-run read-only snapshot listed in section 25.

## 31. Final-holdout access confirmation

No final-holdout row, feature, target, assignment, or aggregate data was accessed. Only protected count/status/checksum metadata was read. Browser instrumentation recorded zero final-holdout-data requests.

## 32. Downstream workflow confirmation

No training job was started. Evaluation, Interpretation, promotion, and Scoring were not opened or performed. Step 6 was opened only to verify its read-only Analysis Partition reference.

## 33. Git-operation confirmation

Nothing was staged, committed, pushed, reset, restored, cleaned, amended, stashed, discarded, or checked out. The index is empty. Branch and HEAD remain `codex/phase2a-canonical-lineage` and `24961ad4da6566c53cf4634796a439f7498fcc0e`.

## 34. Secret-handling confirmation

No credentials, cookies, tokens, passwords, API keys, connection strings, or environment-variable values were printed or included in screenshots/reporting.
