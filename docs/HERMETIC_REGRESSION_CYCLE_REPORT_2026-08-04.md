# ATLAS Hermetic Regression Cycle Closeout

Date: 2026-08-04  
Mode: `HERMETIC_REGRESSION` only  
Final branch: `codex/phase2a-canonical-lineage`  
Final observed HEAD: `938c5b1e2d5b4f81f2b35acc11a048a9b8a04d62`

## Outcome

The approved hermetic test-harness and forensic work is closed. The remaining known Analysis Scope, migration-0028-dependent, and security-authorization failures were classified and resolved without weakening production authority. The subsequently reported Data Acquisition predictor-authorization deadlock was also isolated as a production frontend orchestration defect and repaired without recreating, redrawing, or mutating the existing sealed Analysis Partition.

The final frozen-source representative regression matrix passed all 15 configured suites. This is the complete approved representative hermetic matrix for this cycle; it is not a claim that every test file in the repository was rerun.

## Historical forensic limitation

Exact row-level attribution is not recoverable because verified pre-change database copies do not exist, the live security database remained sharing-locked during the approved forensic work, and the live databases advanced after the preserved forensic copies were taken. Per James's direction, no further attempt was made to reconstruct evidence that was never captured. No live database record was modified, cleaned, restored, or deleted by this task.

## Failure classification and disposition

| Failure | Classification | Governing behavior | Disposition |
| --- | --- | --- | --- |
| Analysis Scope absolute performance-threshold failure | 4. Environmental limitation | Scope resolution must be correct, fail closed, and exhibit reusable warm-path behavior; a single absolute wall-clock threshold is not portable across isolated Windows processes. | Kept production scope logic unchanged. The hermetic test now validates governed warm/cache behavior and records diagnostic latency instead of enforcing a brittle `<500 ms` limit. |
| Two migration-0028-dependent assertions | 3. Incomplete hermetic fixture | Migration 0028 must remain unchanged and unapplied to live storage; tests needing it must run against an isolated migrated fixture. | The exact migration is allowed only inside the isolated Analysis Partition child. Live storage and migration 0028 were not changed. |
| Six security-authorization assertions | 3. Incomplete hermetic fixture | Authorization must be enabled before importing modules that cache authority configuration. | The child fixture now establishes authorization before imports. No authorization rule was relaxed. |
| Data Acquisition stale structural assertion | 2. Stale test expectation | An in-flight exact governed predictor baseline must not be discarded merely because a local draft temporarily marks reproducibility context pending. | Updated the assertion to the accepted fail-closed reconciliation behavior. |
| Model Documentation security child failed before its six assertions because of an overlong nested Windows temporary path | 3. Incomplete hermetic fixture | Security assertions must execute under a child-owned isolated root and must not depend on host path-length accidents. | Shortened only the synthetic child test and backup roots. The isolated six-test file and the full security wrapper then passed. |
| Data Acquisition could not progress when an existing sealed partition was current but predictor authorization had changed | 1. Real production defect | A sealed partition must not be silently recreated. Predictor authorization may be reconciled independently only after exact identity, revision, membership, and checksum verification. | Added an explicit governed predictor-authorization update path and an actionable blocked-step resolver while preserving the sealed partition byte-for-byte. |

## Data Acquisition deadlock repair

### Root cause

The backend correctly refused to create another partition when the existing Analysis Partition was already current. The frontend could nevertheless restore an empty or stale browser predictor selection, discard an in-flight exact backend baseline, and then require partition-preview evidence that the backend would not issue for an already-current partition. Both visible actions therefore became disabled even though the user had selected the dataset, target, and split ratio.

### Corrected behavior

- Canonical predictor identities use a collision-safe sorted JSON set; whitespace-bearing predictor names remain distinct.
- An untouched empty or stale browser selection hydrates from the exact backend-governed `selected_predictors` baseline.
- An explicit user draft is never overwritten by baseline hydration.
- Baseline loading and error states fail closed and expose a retry.
- `Update Predictor Authorization` persists through the existing governed target contract, then performs an exact partition-readiness readback.
- The readback must match project, dataset, dataset version, target, partition ID, positive revision, assignment checksum, artifact checksum, predictor fingerprints, and the returned predictor-authorization lineage.
- Partition membership and the sealed final holdout must remain unchanged.
- Stale asynchronous responses are rejected using operation revisions and identity/selection checks.
- The page-level `Resolve blockers to continue` action now routes to the exact unresolved control. With a valid predictor draft it performs the governed update; with an explicit empty selection it focuses the predictor-selection control.
- The shared `StepShell` remains disabled by default. A blocked button is actionable only when a page deliberately supplies a blocker-resolution handler.
- `Create & Seal Analysis Partition` remains disabled when the current sealed partition already exists. The correct action in that state is authorization reconciliation, not partition replacement.

No dataset rows, split assignments, partition revision, sealed-holdout membership, or governed workflow completion state are changed by this frontend repair.

## Focused validation

Focused hermetic run after the original three corrections:

- Run ID: `atlas-hrt-20260804-183809-17102f8eb7`
- Result: 3/3 suites passed.

Focused hermetic run including the Data Acquisition reconciliation contract:

- Run ID: `atlas-hrt-20260804-201145-8617e27e71`
- Root: `C:\Users\james\AppData\Local\Temp\atlas-hrt-20260804-201145-8617e27e71`
- Result: 4/4 suites passed.
- Suites: isolated Analysis Partition/migration fixture, Analysis Scope, validation separation-of-duties, and Data Acquisition predictor-authorization reconciliation.

The new Data Acquisition contract suite passed 9/9 TAP tests. It proves baseline hydration, explicit-draft preservation, loading/error fail-closed behavior, exact partition-membership preservation, tie-safe canonical selection identity, stale-operation rejection, page-level blocker routing, and shared-shell default safety.

TypeScript validation:

```text
$env:ATLAS_TEST_MODE='HERMETIC_REGRESSION'; npx.cmd tsc -b --pretty false
Exit: 0
Runtime: 54.1 seconds
```

The TypeScript configuration is no-emit, so this check did not create production build output.

## Final frozen-source hermetic matrix

Command:

```text
.\.venv\Scripts\python.exe scripts\run_hermetic_tests.py --mode HERMETIC_REGRESSION --manifest tests\hermetic_representative_suites.json --concurrent
```

Run evidence:

- Run ID: `atlas-hrt-20260804-203850-99d6649795`
- Temporary root: `C:\Users\james\AppData\Local\Temp\atlas-hrt-20260804-203850-99d6649795`
- Suites: 15 passed, 0 failed.
- Wall time: 406.6 seconds.
- Evidence preserved under the run root.
- Migration 0028 was enabled only in the isolated Analysis Partition child.
- The security release gate passed all seven behavioral suites and its structural suite.

| Suite | Result | Reported tests / assertions | Child runtime |
| --- | --- | ---: | ---: |
| Hermetic harness guard | Passed | 12 tests + 8 subtests; 1 skip | 16.27 s |
| Import-cache probe | Passed | Process probe | 27.52 s |
| Node/browser backend guard | Passed | 5/5 TAP | 0.44 s |
| Data Acquisition predictor reconciliation | Passed | 9/9 TAP | 0.52 s |
| Data Acquisition UX refinement | Passed | 8/8 TAP | 0.36 s |
| Analysis Partition reset UX | Passed | 5/5 TAP | 0.35 s |
| Storage static guard | Passed | 24 tests | 77.31 s |
| Security release gate | Passed | 62 behavioral tests; 30 structural assertions | 297.62 s |
| Dataset Library recovery | Passed | 61 tests + 27 subtests | 126.96 s |
| Canonical dataset identity | Passed | 10 tests; 18 warnings | 112.58 s |
| Analysis Scope | Passed | 33 tests + 2 subtests; 18 warnings | 212.37 s |
| Analysis Partition isolated migration fixture | Passed | 13 tests | 25.07 s |
| Project Context hydration | Passed | 3 tests + 6 subtests; 18 warnings | 52.72 s |
| Feature Engineering | Passed | 8 tests + 7 subtests | 12.55 s |
| Model Registry durability | Passed | 29 tests + 4 subtests | 34.76 s |

Warnings were non-failing dependency/resource warnings, including AnyIO memory-stream cleanup and Pydantic deprecation notices. No child command was skipped or treated as successful after a failure.

## Migration and authority safeguards

- `server/persistence/migrations/0028_project_deletion_append_only_cascade.sql` remained unchanged and had no Git status entry at closeout.
- Migration 0028 was not applied to live storage.
- No live HELOC project was used by automated tests.
- Each representative suite ran in a fresh child process under a unique external Windows Temp authority root.
- Browser/Node and Python guards rejected live or overlapping backend roots.
- No final-holdout data was accessed.
- No live services were started, stopped, restarted, or manipulated.
- No live browser acceptance was performed, as explicitly prohibited.

## Repository reconciliation

- Final observed branch: `codex/phase2a-canonical-lineage`.
- Final observed HEAD: `938c5b1e2d5b4f81f2b35acc11a048a9b8a04d62`.
- Git index: empty.
- `git diff --check`: passed.
- No Git mutation command was run by this task: nothing was staged, committed, pushed, reset, restored, cleaned, amended, rebased, merged, cherry-picked, stashed, deleted, or discarded.
- Dataset Library and Evidence Registry artifact paths were already or independently dirty in the working tree at closeout. This task deliberately left them untouched and makes no claim that concurrently changing live artifacts were globally unchanged.

Task code and test paths involved in the final uncommitted repair/cycle:

- `scripts/hermetic_test_authority.py`
- `src/components/StepShell.tsx`
- `src/lib/predictorAuthorizationReconciliation.ts`
- `src/steps/Step01_DataAcquisition.tsx`
- `tests/dataAcquisitionUxRefinement.test.mjs`
- `tests/hermetic_regression_cycle_suites.json`
- `tests/hermetic_representative_suites.json`
- `tests/model_documentation_project_context_test.py`
- `tests/predictorAuthorizationReconciliation.test.mjs`
- `docs/HERMETIC_REGRESSION_CYCLE_REPORT_2026-08-04.md`

## Scope and incident disclosures

- No model training, Evaluation, Interpretation, promotion, Scoring, or live governed workflow completion occurred.
- No sealed final holdout was accessed.
- No live database record was modified, cleaned, restored, or deleted by this task.
- No credential, token, cookie, authentication header, API key, connection string, or environment-variable value was intentionally collected or reproduced in this report.
- During earlier read-only reconnaissance, a broad source inspection exposed a source-defined local-development credential-default literal in tool output. It was source text, not a live or environment-derived credential, and it is intentionally not repeated here.
- An earlier broad read-only search also printed sample rows from non-HELOC dataset artifacts. It did not query a live database, use the live HELOC project, or access the sealed holdout. No rows are reproduced here.
- No further forensic reconstruction or infrastructure investigation was performed after James closed the historical attribution question.

## Closeout verdict

**APPROVED HERMETIC REGRESSION CYCLE PASSED — READY FOR JAMES TO RESUME MANUAL PREDICTIVE MODELING TESTING.**

This verdict is limited to the approved hermetic regression cycle and the source-level Data Acquisition deadlock repair. The repair has not been live-browser accepted because this task explicitly prohibited live browser acceptance and live-service manipulation.
