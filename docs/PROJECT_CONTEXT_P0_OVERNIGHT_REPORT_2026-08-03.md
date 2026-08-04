# ATLAS Project Context P0 overnight report

Date: 2026-08-03  
Branch: `codex/phase2a-canonical-lineage`  
Baseline and final HEAD: `24961ad4da6566c53cf4634796a439f7498fcc0e`

## Outcome

The Project Context feedback loop is repaired and the repaired production composition passed focused integration, project-scoped route, 30-minute stability, ten-restart browser, security, storage-isolation, compilation, and production-build validation.

The live HELOC lineage was not used for test writes. The live Dataset Library registry, project link, and workflow checkpoint retained their exact pre-run SHA-256 hashes. No training, Evaluation, Interpretation, promotion, or Scoring was performed, and no final-holdout data was requested.

One pre-existing, out-of-scope Model Registry project-deletion defect remains: an archive-on-project-delete test receives HTTP 400 because predictor-authorization manifests are append-only. Historical SQLite foreign-key debt also remains and is documented below. Neither issue invalidates the Project Context lifecycle result, and neither was repaired in this assignment.

## 1. Repository safety baseline

The mandatory pre-edit snapshot is recoverable at:

`C:\Users\james\AppData\Local\Temp\atlas-p0-project-context-20260803-083559`

It contains the branch/HEAD record, binary working-tree patch, tracked and untracked manifests, source/runtime classification, authority checksums, and expected repair-file list. Credentials, browser profiles, cookies, and tokens were not copied.

Baseline facts:

- Branch: `codex/phase2a-canonical-lineage`
- HEAD: `24961ad4da6566c53cf4634796a439f7498fcc0e`
- The repository was already heavily dirty: 70 tracked paths were modified before this task.
- Index before work: empty.
- Index after work: empty.
- Final read-only status: 89 tracked modifications and 68 Git-visible untracked files after adding this report.
- Final `git diff --check`: exit 0; only existing LF-to-CRLF and inaccessible pytest-cache warnings.

Protected authority hashes matched the snapshot at completion:

| Authority | SHA-256 | Match |
|---|---|---:|
| `server/artifacts/datasets/registry.json` | `7fbe95e6fb48326e594c039353c76dc3287d11350510c8fd16a165c6ec84446f` | yes |
| `server/artifacts/datasets/project_links.json` | `9f3568b6c4b971e94d0ca0832e7c05fa12f6a36139af5632d2a3c6b31b9fb890` | yes |
| `.runtime/workflow_checkpoint.json` | `73571f38e6515fc2cc018a5298a0f68004929075b2483c6819e8f64e08f7e00c` | yes |

The exact accepted HELOC identifiers were treated only as immutable acceptance context; they were not hardcoded into production logic.

## 2. Confirmed root cause and lifecycle

### Before

1. `PredictiveIdentityProvider` completed authoritative project, workflow, and dataset hydration.
2. `Step00_ProjectContext` mounted.
3. A restoration/mount effect unconditionally emitted `atlas-project-context-updated`.
4. The provider treated that broad metadata event as an identity invalidation and returned to blocking `resolving`.
5. Step 00 unmounted, hydration completed, and Step 00 remounted.
6. The mount effect emitted again, creating an unbounded loop despite successful HTTP 200 authority responses.

The old save path also had overlapping project PUT behavior, making an ambiguous response surface as a conflict even when the backend had converged.

### After

1. A project-scoped route initiates one blocking identity hydration.
2. The provider atomically publishes `ready` and retains the last valid identity.
3. Step 00 mounts once and initial hydration emits zero Project Context update events.
4. Hydrated values and MDD restoration populate form state without invalidating identity.
5. An explicit successful user save performs one metadata mutation, publishes a typed metadata result, and updates presentation state in place.
6. Background verification does not unmount the workflow or return identity to blocking `resolving`.
7. Same/older revisions and duplicate request IDs are ignored; different-project or prior-user responses cannot publish into the current context.

## 3. Repair design

### Identity and metadata are independent

Identity status owns blocking authority resolution: route project, authenticated user, project authorization, workflow type, exact canonical dataset/version/revision, target, predictor authorization, and Analysis Partition.

Metadata status owns mutable Project Context presentation: name, narratives, intended use, review/override language, deployment presentation, and MDD-linked context. A metadata save or verification error remains local and does not destroy the ready identity.

### Event and callback contract

The normal path is a typed provider callback. The compatibility browser event remains only after an acknowledged user save and carries exactly:

`project_id`, `project_revision`, `request_id`, `changed_fields`, `source`, `saved_at`

`source` must be `user_save`. Hydration, provider publication, backend restoration, route mount, and stale responses do not dispatch the event. Duplicate request IDs are idempotently ignored. EDA documentation validates the exact project, revision, request ID, timestamp, and source before responding.

### Revision behavior

- Same project and revision: duplicate, ignored.
- Same project and older revision: stale, ignored.
- Same project and newer metadata revision: presentation metadata updates in place.
- Different route project: one new blocking hydration; prior responses cannot publish.
- Different authenticated user: prior-user context is cleared and authority is rehydrated.
- Dataset/identity revision change: exact backend verification; no browser-storage fallback.
- Unsaved form edits win over older background verification.

### Save behavior

The ordinary save validates the scoped project, prevents concurrent duplicates, persists only Project Context metadata, preserves governed identity, shows `Saved to ATLAS database`, and performs any evidence/MDD work through the existing sequence. An ambiguous PUT is verified with a GET; exact convergence remains a successful `user_save`, while an already-converged precheck is recorded as background verification. Narrative changes do not reactivate a dataset, recreate target/predictor contracts, replace the Analysis Partition, or reload the route.

## 4. Task source changes

Lifecycle and metadata repair:

- `src/components/PredictiveIdentityProvider.tsx`
- `src/components/documentation/EdaDocumentationLiveLink.tsx`
- `src/lib/projectContextMetadata.ts`
- `src/lib/projectContextPersistence.ts`
- `src/lib/useProjectContextAutosave.ts`
- `src/steps/Step00_ProjectContext.tsx`

Project-scoped navigation normalization:

- `src/components/eda/TargetIntelligenceWorkspace.tsx`
- `src/steps/CreditRiskStudio.tsx`
- `src/steps/Dashboard.tsx`
- `src/steps/IntelligentWorkbench.tsx`
- `src/steps/ModelDiagnostics.tsx`
- `src/steps/ModelDocumentationStudio.tsx`
- `src/steps/NotebookExport.tsx`
- `src/steps/ProjectOverview.tsx`
- `src/steps/Step02_EDA.tsx`
- `src/steps/Step04_Outliers.tsx`
- `src/steps/Step06_BalancingSplit.tsx`
- `src/steps/Step06_Train.tsx`
- `src/steps/Step08_Evaluation.tsx`
- `src/steps/Step10_Scoring.tsx`
- `src/steps/Step11_ModelDevelopmentDocument.tsx`

The latter files contain navigation-only normalization where the route is not part of this assignment; those governed phases were not opened or executed.

## 5. Tests added or updated

- `tests/analysisScope.test.mjs`
- `tests/bureau_detection_exact_binding_test.py`
- `tests/datasetLibrary.test.mjs`
- `tests/evidenceCanonicalIdentity.test.mjs`
- `tests/model_registry_test.py`
- `tests/predictiveModelingRepair.test.mjs`
- `tests/projectContextPersistence.test.mjs`
- `tests/regression.test.mjs`
- `tests/e2e/predictive-route-integrity-matrix.spec.ts`
- `tests/e2e/project-context-backend-restart.integration.ts`
- `tests/e2e/project-context-backend-restart.playwright.config.ts`
- `tests/e2e/project-context-backend-restart.vite.config.ts`
- `tests/e2e/project-context-hydration.spec.ts`
- `tests/e2e/project-context-stability-soak.spec.ts`
- `tests/e2e/project-scoped-composition-lifecycle.spec.ts`
- `tests/projectContextMetadata.test.mjs`
- `tests/projectScopedPredictiveNavigation.test.mjs`
- `tests/projectScopedRoutes.test.mjs`
- `tests/project_context_backend_restart_soak_test.py`
- `tests/project_context_browser_restart_integration_test.py`

All browser lifecycle instrumentation is test-only; verbose production logging was not added.

## 6. Focused and production-composition validation

| Validation | Result | Runtime/notes |
|---|---:|---|
| Project Context metadata Node contract | 9/9 passed | typed payload, revision and dedupe rules |
| Project Context persistence Node contract | 21/21 passed | save, ambiguity verification, preservation |
| Authoritative context Node contract | 16/16 passed | project/user/identity isolation |
| Python hydration authority | 3 tests + 6 subtests passed | isolated authorities |
| Focused actual composition | 3/3 passed | real provider + Step 00 |
| EDA production composition | 1/1 passed | same-origin production bundle |
| Final production-build composition set | 22/22 passed | 1.5 minutes |
| Project-scoped navigation contract | 19/19 passed | all rendered links scoped |
| Predictive route matrix | 1/1 passed | 48.2 seconds; Step 00 through Step 07 |

The final 22-test production-build run covered Project Context hydration, Predictive Identity readiness, actual composition lifecycle, and the route matrix. An earlier 18/22 run isolated two test-only causes: hardcoded backend inspection URLs under production preview and assertions racing intentional unmount during navigation. The harness was corrected; the final run passed 22/22.

## 7. Thirty-minute stability soak

Exact command form:

```powershell
npx playwright test tests/e2e/project-context-stability-soak.spec.ts --project=chromium --reporter=json
```

The production-preview base URL, full-soak switch, and JSON-output destination were supplied through the isolated harness. Their environment-variable values are intentionally not reproduced in this report.

Result: 1/1 passed in 30.1 minutes (`1,803,038 ms` reporter duration; `1,800,079 ms` measured soak).

Required workload completed:

- 5 isolated browser contexts
- 2 isolated users
- 1,000 stable DOM samples
- 100 metadata saves
- 100 full reloads
- 100 Project Context/Data Acquisition/EDA back-forward cycles
- Minimum 30-minute runtime

Key assertions and counters:

- During the save phase, each of 100 saves incremented the project PUT counter exactly once.
- 100 save events were observed; identity hydration remained 1 start / 1 completion; safe-boundary mounts remained 0.
- Every DOM sample was `{ model: true, gate: false, error: false, status: ready }`.
- Each reload had 1–4 bounded project GETs, exactly one fresh composition hydration, one model mount, zero model unmounts while on Step 00, and no request storm after settling.
- The final 301 project PUT total includes the 100 explicit metadata saves plus later compatibility-persistence writes caused by reload/history composition; it does not mean three metadata mutations per save.
- Primary-context totals: 402 project GETs, 301 project PUTs, 101 workflow GETs, 302 identity GETs, 101 sample GETs, 101 EDA overview POSTs, 101 documentation GETs, 1 documentation draft, 0 unknown requests.
- Each of the other four contexts had 2 project GETs, 1 workflow GET, 1 identity GET, 1 sample GET, 0 PUTs, and 0 unknown requests.
- Final history lifecycle: Project Context 101 mounts/101 unmounts; EDA 101 mounts/100 unmounts because EDA intentionally remained mounted at the end; safe-boundary mounts 0.
- Listener accounting was balanced: `popstate` 102 adds/100 removals/2 active, `storage` 405/402/3, dataset-identity 1/0/1. In every case, adds minus removals equaled the active mounted listeners.
- Provider transition was only `resolving -> ready` in each fresh composition.
- Reliable browser heap telemetry was not exposed, so no memory figure is invented. DOM stability, listener balance, quiescence, and bounded request counts were used as the resource-leak gates.

Evidence: `.tmp/project-context-soak-full-20260803.json`.

The first attempted command used a Windows path form that Playwright did not discover and exited immediately with `No tests found`; it did not consume the required duration. The corrected forward-slash invocation above completed the full 30-minute run.

## 8. Ten-restart resilience

Two isolated restart harnesses passed:

```powershell
.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests\project_context_backend_restart_soak_test.py
.venv\Scripts\python.exe -m pytest -q -s -p no:cacheprovider tests\project_context_browser_restart_integration_test.py
```

- API restart harness: 1/1 passed in 136.82 seconds; 10 backend replacements plus baseline; 55 HTTP 200 authority/health/EDA checks.
- Production-bundle Chromium restart harness: 1/1 passed in 317.27 seconds; 11 complete browser compositions and 10 listener replacements.
- Browser PIDs: baseline `67296`; then `69528`, `71864`, `59516`, `71564`, `69772`, `71420`, `62588`, `73148`, `71408`, `65488`.
- Every old listener stopped and every new listener became healthy.
- All 11 Step 00 passes had one mount, zero unmounts, zero Project Context events, and `resolving -> ready`.
- All 11 Data Acquisition passes rendered the exact isolated project/dataset/version/revision.
- All 11 EDA passes returned HTTP 200 with `development_population`; final-holdout accessed/used-for-selection flags were false.
- Total browser API requests: 377.
- Authority recreation mutations: 0.
- Forbidden training/Evaluation/Interpretation/Scoring/Model Registry requests: 0.
- Final-holdout data requests: 0.
- One compatibility metadata PUT occurred per composition, limited to `modelId`, `hasDataset`, `projectTools`, and `compatibilityStore`; it did not recreate any authority.

Evidence: `.tmp/atlas_project_context_restart_soak_239e90aa055d431b9290e2b302147e39/browser-restart-integration-result.json`.

## 9. Project-scoped workflow matrix

The production-build matrix rendered and navigated all current Predictive Modeling routes from Step 00 through Step 07:

1. Project Context
2. Data Acquisition
3. EDA
4. Outliers
5. Missing Values
6. Feature Engineering
7. Training and Validation Design
8. Model Training

All retained the scoped project URL, exact isolated identity, correct visible page signal, stable back/forward behavior, and no safe boundary, console exception, HTTP 500, Untitled-project flash, or infinite loader. The Model Training workspace rendered only; no training job was started.

Final source scans:

- Rendered raw `/stepXX` navigation: 0 matches.
- `location.reload()` in source: 0 matches.
- Workflow `window.location` writes: 0. One unrelated write remains in Interpretation for a model JSON export URL.
- `atlas-project-context-updated`: exactly one dispatch and one balanced listener add/remove pair.
- Project identity selected authoritatively from browser storage: 0 matches in the strict authority scan and 0 failures in the route/authority contracts.

## 10. Broad regression, security, and build results

Commands and results:

```powershell
npx tsc -b
npm run build
npm run test:regression
.venv\Scripts\python.exe -m compileall -q server tests
.venv\Scripts\python.exe scripts\run_security_tests.py
```

- TypeScript: passed twice, including the final post-soak check.
- Production build: passed; 3,437 modules; 106.6 seconds total; Vite build 38.27 seconds.
- Regression script: 18/18 passed after adding the new route helper and both transitive dependencies to its isolated transpilation directory.
- Selected broad Node suite: 450/450 passed in 11.85 seconds.
- Python compilation: passed.
- Security gate: 62 behavioral tests passed plus 30 structural assertions in 297.8 seconds:
  - containment 15
  - lockout 6
  - persistence authentication 5
  - project access 8
  - segregation of duties 6
  - SQLite persistence 16
  - Model Documentation 6
  - user-management structural assertions 30

Safe broad Python results, executed with isolated roots and fresh processes where needed:

- Initial broad group: 268 passed, 1 skipped, 67 subtests.
- Target Intelligence fresh process: 50 passed + 10 subtests.
- Preprocessing premium: 15 passed.
- Preprocessing table: 4 passed.
- Missing Values: 3 passed.
- Feature Engineering acceptance: 8 passed + 7 subtests.
- Feature Engineering progression: 5 passed.
- Validation Design: 8 passed.
- Training preflight: 9 passed.
- Phase 2B1 candidate contract: 8 passed + 7 subtests.
- Training holdout: 6 passed.
- Holdout governance: 12 passed.
- Model Documentation: 6 passed.
- Model Registry durability: 29 passed + 4 subtests.
- Bureau exact binding: 9 passed.
- Storage isolation: 24 passed.
- Model Registry isolated main selection: 11 passed, 1 deselected; comparison test passed individually.
- Documentation bundle isolated selection: 1 passed, 11 deselected in 20.63 seconds.

Observed and handled validation issues:

- A combined Python process produced 19 Target Intelligence setup errors because cached security-database module state crossed isolated fixtures. Every affected file passed when rerun in a fresh process; production code was not weakened.
- One storage-guard failure was an incomplete checkpoint fixture and passed after fixture correction.
- The final regression script initially omitted `projectScopedRoutes`, then its `authoritativeProjectContext` and `datasetIdentity` dependencies from the temporary transpilation sandbox. The test harness now includes the dependency chain and passes 18/18.
- The known Model Registry project-deletion test remains a real failure: expected HTTP 200, received HTTP 400, safe message `predictor authorization manifests are append-only`. This needs a separate governed deletion/cascade repair.

Warnings:

- Build: stale Browserslist/caniuse data, mixed dynamic/static import warning, and chunks above 500 KB.
- Security tests: AnyIO unclosed-stream warnings and a Pydantic `dict` deprecation warning.
- Git diff check: LF/CRLF warnings and inaccessible generated pytest-cache directories; no whitespace error.

## 11. Read-only storage integrity

SQLite was opened read-only with `query_only`; database size and timestamps were unchanged.

- `atlas_local.db`: `integrity_check=ok`; 312 historical foreign-key orphans:
  - decision journal to projects: 182
  - evidence artifacts to projects: 113
  - project collaborators to projects: 17
- `atlas_security.db`: `integrity_check=ok`; 67 historical credential-to-user orphans.
- The HELOC project had zero local-database FK findings.
- The findings date to July 21–24 and appear fixture/history related. Current writers enable foreign keys and cascading behavior.

These records were not changed. They require a separate backed-up, governed data-hygiene review rather than silent deletion during this P0 task.

## 12. Repository classification

Final Git-visible classification after this report:

| Class | Tracked | Untracked | Total |
|---|---:|---:|---:|
| A. Production source | 56 | 12 | 68 |
| B. Migration | 0 | 1 | 1 |
| C. Automated tests/scripts | 29 | 26 | 55 |
| D. Documentation | 0 | 1 | 1 |
| E. Runtime authority | 4 | 10 | 14 |
| F. Screenshots/audit | 0 | 15 | 15 |
| G. Temporary script | 0 | 0 | 0 |
| H. Generated output | 0 | 3 | 3 |
| I. Ambiguous | 0 | 0 | 0 |

Of the 70 pre-task tracked changes, 62 remain byte-for-byte identical to the external snapshot. The complete per-file baseline classification is stored in `source-runtime-classification.csv` in the safety directory.

Task-generated runtime quarantine:

`C:\Users\james\AppData\Local\Temp\atlas-p0-project-context-20260803-083559\task-generated-runtime-quarantine`

It contains 76 generated registry-regression feature manifests and one generated EDA-documentation artifact (77 files, 499,193 bytes). They were moved intact to a recoverable external quarantine; no task-generated runtime authority remains under those repository roots.

A final recursive provenance scan also found 78 ignored `registry-regression` manifest files whose filesystem timestamps are August 1, before this assignment. They are pre-existing runtime material, were not counted as task output, and were left untouched.

Retained ignored restart evidence contains 43 files and 1,503,850 bytes under `.tmp/atlas_project_context_restart_soak_239e90aa055d431b9290e2b302147e39`.

### Recommended commit slices

1. Canonical backend authority and migration already present in the dirty tree, with its focused tests.
2. Project-scoped routing and authoritative identity.
3. Project Context lifecycle repair and actual-composition tests.
4. Predictive navigation normalization and route matrix.
5. Restart and soak infrastructure.
6. Broader fixture-contract updates, reviewed separately because of the Model Registry defect.
7. This report.

Dependencies are sequential: authority before routing, routing before lifecycle, lifecycle before route normalization, and all production slices before restart/soak evidence.

Never stage:

- `server/artifacts/**`
- `.runtime/**`
- `.tmp/**`
- `audit-output/**`
- `test-results/**`
- `.pytest_cache/**`
- `pytest-cache-files-*/**`
- `dist/**`
- external safety/quarantine directories
- credentials, `.env*`, browser profiles, cookies, logs, databases, or generated datasets

Human review is required for all pre-task dirty changes, navigation-only changes touching later governed phases, Model Registry fixture changes and its unresolved deletion defect, bureau fixture-root changes, all runtime JSON, and eventual disposal of quarantined/evidence artifacts.

## 13. Morning live checklist

1. Sign in.
2. Open project `atlas-mrzpau4t`.
3. Open Project Context.
4. Confirm loading completes once.
5. Observe for 30 seconds and confirm no remount/loading loop.
6. Open Data Acquisition and confirm the exact registered HELOC dataset/version and activation revision 1.
7. Open EDA and confirm the Overview renders successfully.
8. Refresh Project Context and EDA and repeat the stability check.
9. Restart FastAPI once.
10. Reopen Project Context, Data Acquisition, and EDA and repeat the checks.
11. Resume the Predictive Modeling workflow only after these pass.

## 14. Completion state and explicit confirmations

- Frontend at completion: HTTP 200 on port 5174, listener PID 38276.
- Backend at completion: health HTTP 200 on port 8001, listener PID 69656.
- Live HELOC Project Context was not modified solely for testing.
- Dataset activation was not recreated; registry and project-link hashes are unchanged.
- The Analysis Partition was not replaced.
- No full-population target-directed fallback was introduced; restart EDA remained `development_population`.
- Final-holdout data access: 0 requests.
- No model training occurred.
- Evaluation was not opened.
- Interpretation was not opened.
- No candidate or model was promoted.
- Scoring was not opened or performed.
- No credentials, cookies, tokens, passwords, connection strings, API keys, or environment-variable values were printed.
- Nothing was staged, committed, pushed, reset, restored, cleaned through Git, amended, stashed, or discarded.
- No source or runtime file was deleted. The 77 task-generated artifacts were retained in recoverable external quarantine.

The assignment stops here, with Project Context lifecycle stability, project-scoped route integrity, restart resilience, and automated Predictive Modeling route rendering established.
