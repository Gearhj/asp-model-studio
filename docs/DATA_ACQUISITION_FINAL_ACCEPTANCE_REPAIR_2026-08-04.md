# ATLAS Data Acquisition Final Acceptance Repair

Date: 2026-08-04 (America/New_York)  
Scope: Data Acquisition, its canonical handoff into EDA, governed Analysis Partition ratio changes, and Special-Value Treatment Review  
Branch: `codex/phase2a-canonical-lineage`  
HEAD: `938c5b1e2d5b4f81f2b35acc11a048a9b8a04d62`

## Outcome

The focused repair is implemented and ready for the bounded live manual acceptance checklist in this report.

Data Acquisition now builds one backend-authoritative handoff, verifies every required durable authority by exact identity, and navigates only after a successful read-back. EDA consumes that same complete contract, rejects stale or partial identity, and verifies that target-directed results use the Development Population while excluding the sealed final holdout.

The split-ratio action is now discoverable and revision-safe. A sealed partition remains read-only until the analyst explicitly opens **Change Split Ratio - Creates New Revision**, reviews backend-authoritative impact, acknowledges invalidations, supplies any required rationale, and confirms a new revision.

Special-Value Treatment Review is now a table-first workspace with one affected feature per row, inline treatment controls, expandable code evidence, filters and burden sorting, explicit unresolved state, first-blocker navigation, and a compact confirmed summary.

This is not a full-repository checkpoint verdict. Dedicated acceptance, backend analytical, Analysis Partition, security, storage-isolation, TypeScript, build, Python compilation, and diff checks are green. Several legacy frontend files could not start inside the source-only hermetic mirror because the mirror omitted runtime package inputs; those environment limitations are documented below and are not reported as passing tests.

## Root cause

The original DA-to-EDA path reconstructed authority from several partially overlapping sources:

- Data Acquisition held the correct active Dataset Library identity, target contract, predictor authorization, Special-Value Review, and Analysis Partition.
- navigation could occur without rereading and comparing every persisted prerequisite;
- EDA rebuilt parts of its entry contract from route state, browser state, display labels, and independently fetched partial endpoints;
- secondary EDA requests did not all carry the same complete lineage;
- stale asynchronous responses could outlive a project/context change; and
- backend EDA services could resolve analytical state before fully comparing the browser assertion with exact durable authority.

That allowed the page shell to show the correct project while an analytical request lacked `dataset_id`, showed a pending target, or lacked verified predictor and partition lineage. The visible result was split-brain canonical state.

The repair makes browser state subordinate. Browser storage remains available for non-authoritative UI preferences and project-scoped drafts, but it cannot create or replace dataset, target, predictor-authorization, Special-Value Review, or partition authority.

## Before and after flow

### Before

`Data Acquisition state -> partial persistence -> route navigation -> EDA reconstructs identity -> independent analytical requests`

Failure modes included incomplete identifiers, display-name substitution, stale browser context, inconsistent nested EDA requests, and late prerequisite errors.

### After

`Final DA action -> persist required state -> read current DA reproducibility context -> compare exact active identity -> read exact Special-Value Review -> verify current Analysis Partition -> build canonical handoff -> navigate to /projects/:projectId/step02 -> EDA rereads and compares the same handoff -> every analytical request and response verifies exact lineage`

The canonical contract contains:

- `project_id`
- `dataset_id`
- `dataset_version_id`
- `activation_revision`
- `target_contract_id`
- target column and positive/negative mapping
- `predictor_authorization_id`
- `special_value_review_id` and revision
- `analysis_partition_id` and revision

EDA now:

- fails with the actual project-scoped prerequisite before constructing an analytical request;
- deep-links and refreshes using durable authority;
- uses abort/sequence guards so a stale request cannot overwrite a newer context;
- binds all nested analytical calls and documentation calls to the complete handoff;
- rejects mismatched response lineage; and
- requires `scope=development_population`, `final_holdout_accessed=false`, and the explicit sealed-holdout exclusion marker for target-directed responses.

No first-version, latest-version, project-display-name, dataset-display-name, browser-snapshot, or anonymous-scope fallback was added.

## Governed split-ratio behavior

For a project without a partition, Data Acquisition presents:

- 70% Development / 30% Final Holdout;
- 80% Development / 20% Final Holdout (Recommended);
- 90% Development / 10% Final Holdout;
- a backend-authoritative preview; and
- **Create & Seal Analysis Partition**.

For a project with a current sealed partition, the existing identity, revision, split, counts, seed, stratification, seal, and isolation state are read-only. The primary action is **Change Split Ratio - Creates New Revision**.

Opening that action does not mutate state. It shows:

- current partition ID and revision;
- current split, population counts, seed, and stratification;
- proposed standard ratio;
- backend preview counts and sufficiency findings;
- downstream invalidations;
- explicit acknowledgement;
- analyst rationale when required by backend policy; and
- **Create New Analysis Partition Revision** and Cancel actions.

Immediately before confirmation, the client rereads the exact current partition, target contract, and durable predictor authorization. Optimistic concurrency prevents replacing a changed baseline. A successful response must contain a newer positive revision, preserve the prior revision, remain sealed and isolation-verified, and leave downstream evidence stale for explicit recomputation. It does not navigate automatically.

The live HELOC split-change flow was not exercised.

## Table-first Special-Value Treatment Review

The Variable Navigator is no longer the primary interaction. The master table contains one affected attribute per row with these columns:

- Attribute
- Number of special codes
- Special-code summary
- Affected rows
- Population percentage
- Largest event-rate difference, when valid
- Recommended treatment
- Selected treatment
- Rationale status
- Review status
- Details action

Each row provides an inline treatment selector. Supported policies preserve the backend contract: leave governed codes unchanged, create an indicator, impute with a valid value, exclude from modeling, or apply a supported feature-specific override. No policy is silently committed. **Apply selected default to unresolved attributes** changes explicit browser-draft selections only; save or confirm remains required.

Rows are ordered unresolved-first, then reviewed. Search, status and treatment filters, sortable burden columns, keyboard-accessible controls, and no-reload interaction are provided. The footer can clear conflicting filters, expand the first unresolved feature, scroll to it, and focus the missing control.

Expanded rows retain code-level evidence: code, definition, count, population share, event count/rate, regular-value event rate, difference, effective treatment, override, and rationale.

The backend contract also now:

- keeps bureau codes distinct from true nulls, parse failures, and ordinary outliers;
- fingerprints datatypes and canonical source checksum;
- preserves a valid review across an activation-revision-only refresh of the same exact dataset version;
- marks target-informed review stale when the Analysis Partition changes;
- binds target-informed comparisons to development positions only;
- validates governed replacement values against datatype, finiteness, booleans, and detected special codes; and
- rereads the durable review before reporting completion.

Evidence export state is visible and retryable. An evidence-service failure does not misrepresent the durable review revision or silently rewrite its treatments.

## Exact task-touched files

The repository was already substantially dirty. This is the task-attributable file set, not a blanket staging recommendation.

### Frontend production

- `src/components/BureauReviewPanel.tsx`
- `src/components/CopilotCard.tsx`
- `src/components/PredictiveIdentityProvider.tsx`
- `src/components/StepShell.tsx`
- `src/components/eda/TargetIntelligenceWorkspace.tsx`
- `src/components/eda/visual/PredictorDistributionExplorer.tsx`
- `src/components/eda/visual/RelationshipExplorer.tsx`
- `src/components/eda/visual/VifExplorer.tsx`
- `src/components/eda/visual/VifResolutionPlanPanel.tsx`
- `src/lib/bureauDetection.ts`
- `src/lib/creditBureau.ts`
- `src/lib/dataAcquisitionEdaHandoff.ts` (new)
- `src/lib/targetIntelligenceApi.ts`
- `src/steps/Step01_DataAcquisition.tsx`
- `src/steps/Step02_EDA.tsx`

### Backend production

- `server/analytics/target_intelligence_router.py`
- `server/eda/analytical_contract.py`
- `server/eda/documentation_service.py`
- `server/eda/eda_router.py`
- `server/eda/workspace_service.py`
- `server/eda/workspace_types.py`
- `server/persistence/repositories/special_value_review_repository.py`
- `server/preprocessing/bureau_detection_router.py`
- `server/preprocessing/bureau_detection_service.py`
- `server/preprocessing/bureau_detection_types.py`
- `server/preprocessing/special_value_review_service.py`

### Tests

- `tests/analysisPartitionProductCompletionFrontend.test.mjs`
- `tests/analysisPartitionResetUxContract.test.mjs`
- `tests/analysis_partition_fixture.py`
- `tests/bureauDetectionExactBinding.test.mjs`
- `tests/bureau_detection_exact_binding_test.py`
- `tests/dataAcquisitionFinalAcceptanceRepair.test.mjs` (new)
- `tests/dataAcquisitionUxRefinement.test.mjs`
- `tests/dataAcquisitionValidationSimplification.test.mjs`
- `tests/data_acquisition_validation_simplification_test.py`
- `tests/edaCanonicalIdentity.test.mjs`
- `tests/edaPartialReadinessFrontend.test.mjs`
- `tests/edaVisualIntelligencePhase11.test.mjs`
- `tests/eda_governed_analytical_contract_test.py`
- `tests/eda_http_transport_contract_test.py`
- `tests/eda_phase1_predictor_authorization_test.py`
- `tests/special_value_review_contract_test.py`
- `tests/targetIntelligence.test.mjs`
- `tests/target_aware_production_scope_scan_test.py`
- `tests/vifResolutionPlan.test.mjs`
- `tests/vif_resolution_plan_test.py`

## Automated validation

All automated test invocations below used:

`scripts/run_hermetic_tests.py --mode HERMETIC_REGRESSION`

No test targeted ports 5174 or 8001, the live HELOC project, or a live authority root.

### Focused final handoff and EDA run

Run root: `C:\Users\james\AppData\Local\Temp\atlas-hrt-20260805-020440-17b52b6483`

Result: 9 of 9 suites passed.

| Suite | Result |
| --- | --- |
| `dataAcquisitionFinalAcceptanceRepair.test.mjs` | 11 passed |
| `dataAcquisitionValidationSimplification.test.mjs` | 7 passed |
| `data_acquisition_validation_simplification_test.py` | 3 passed |
| `edaCanonicalIdentity.test.mjs` | 4 passed |
| `edaEntryReadinessContract.test.mjs` | 5 passed |
| `eda_governed_analytical_contract_test.py` | 22 passed; 2 subtests passed |
| `eda_http_transport_contract_test.py` | 19 passed; 12 subtests passed; 13 warnings |
| `eda_phase1_predictor_authorization_test.py` | 15 passed; 27 subtests passed; 13 warnings |
| `projectScopedPredictiveNavigation.test.mjs` | 3 passed |

### Split and Analysis Partition run

Run root: `C:\Users\james\AppData\Local\Temp\atlas-hrt-20260805-020955-5f1cc0b305`

Result: 6 of 6 suites passed.

| Suite | Result |
| --- | --- |
| `dataAcquisitionUxRefinement.test.mjs` | 8 passed |
| `analysisPartitionProductCompletionFrontend.test.mjs` | 11 passed |
| `analysisPartitionResetUxContract.test.mjs` | 5 passed |
| `analysis_partition_product_completion_test.py` | 32 passed |
| `analysis_partition_product_matrix_test.py` | 8 passed |
| `analysis_partition_validation_reuse_test.py` | 8 passed |

### Special-value and exact-binding runs

- `special_value_review_contract_test.py`: 7 passed. Run root: `C:\Users\james\AppData\Local\Temp\atlas-hrt-20260805-015332-104166281c`.
- `bureau_detection_exact_binding_test.py`: 14 passed. Run root: `C:\Users\james\AppData\Local\Temp\atlas-hrt-20260805-015032-ea6edd95df`.
- An initial Special-Value Review run exposed missing type/special-code replacement rejection. The production repository validation and fixture were corrected; the final 7-test run above is green.

### Established DA reproducibility follow-up

Run root: `C:\Users\james\AppData\Local\Temp\atlas-hrt-20260805-022733-ce36e599e4`

- `data_acquisition_reproducibility_context_test.py`: 2 passed.
- Six legacy frontend suites did not reach assertions: five failed at module loading because the source-only hermetic mirror did not contain `typescript`; `dataAcquisitionUx.test.mjs` failed because the mirror did not contain `package.json`. This is an execution-environment limitation, not a passed gate. See Remaining limitations.

### Canonical identity and documentation support

Run root: `C:\Users\james\AppData\Local\Temp\atlas-hrt-20260805-012703-433c0afbd8`

- `analysis_partition_documentation_gate_test.py`: 5 passed.
- `analysis_partition_legacy_compatibility_test.py`: 10 passed, 4 warnings.
- `canonical_dataset_identity_test.py`: 10 passed, 18 warnings.
- `evidence_canonical_identity_test.py`: did not reach assertions because Windows denied creation of an isolated backup directory. A second isolated run reproduced the same setup-only `WinError 5`; it is not reported as passed.

### Hermetic isolation, storage, and security

- Hermetic harness and guards: 4 of 4 suites passed at `C:\Users\james\AppData\Local\Temp\atlas-hrt-20260805-015603-7fdd18f4d6`.
  - `hermetic_test_harness_test.py`: 12 passed, 1 skipped, 8 subtests passed.
  - `hermetic_node_guard.test.mjs`: 5 passed.
  - `test_storage_isolation_guard_test.py`: 24 passed.
  - `scripts/check_test_storage_isolation.py`: passed.
- Security release gate: 7 behavioral suites and 1 structural suite passed at `C:\Users\james\AppData\Local\Temp\atlas-hrt-20260805-015922-5117087ffc`; the output includes 30 user-management assertions.

### Static gates

- TypeScript: `npx tsc -b` passed against the final source (40.6 seconds).
- Production build: `npm.cmd run build` passed after the sandbox-only `spawn EPERM` attempt was rerun with approved process execution. Vite built 3,441 modules in 33.52 seconds; warnings were limited to browser-data freshness, mixed dynamic/static import, and chunk size.
- Python compilation: passed with bytecode directed to `C:\Users\james\AppData\Local\Temp\atlas-da-pycompile-a97b4b01a85541a081bce45212baa036` (4.9 seconds).
- `git diff --check`: passed; only line-ending conversion warnings were emitted.
- Git conflict scan: no unmerged paths.
- Production live-identifier scan: no hardcoded HELOC project, dataset, version, or partition identifiers in `src` or `server` production code (artifact/data directories excluded).
- Migration 0028 source diff: empty.

## Development-only analytical scope

Target-independent structural analysis may use the Full Governed Population. Every target-informed EDA or Special-Value comparison resolves the exact current Analysis Partition, verifies project/dataset/version/target/predictor lineage, materializes development positions only, and returns explicit scope metadata.

Tests deliberately varied holdout target values and verified that development results were invariant. Duplicate dataframe indexes remain positionally handled. Missing, stale, cross-project, and cross-version authority fails closed. The final holdout is represented only by exclusion metadata and counts; no holdout frame was opened.

## Protected-authority comparison

The safety snapshot was created at:

`C:\Users\james\AppData\Local\Temp\atlas-da-final-acceptance-20260804-172856`

Read-only logical comparison before and after the hermetic runs shows the live HELOC authority unchanged:

| Authority | Before | After |
| --- | --- | --- |
| Project | `atlas-mrzpau4t` | unchanged |
| Dataset | `ds_heloc_train_6bdb184b_05905` | unchanged |
| Dataset version | `v_1785186305905_6bdb184b` | unchanged |
| Activation revision | 1 | unchanged |
| Target contract | `target-contract-9a0bbd69645b7e5e0b4c` (`bad_flag`, 1/0) | unchanged |
| Predictor authorization | `predictor-auth-491392549aa93a6ad258` | unchanged |
| Analysis Partition | `analysis-partition-688c2184b4e9b8181946-r1` | unchanged |
| Partition revision/status | 1 / current | unchanged |
| Population | 6,275 total; 5,020 development; 1,255 sealed holdout | unchanged |
| Split / seed / stratification | 80/20; 42; target on `bad_flag` | unchanged |
| Assignment hash | `ed04b51eef3ebfccc846ff742203978ae0463ee871807c6045595b68106bb6c5` | unchanged |
| Population fingerprint | `0d81ad64bb8ac0b0314abb28a05b94c74e6dc97138ff05ddbb864440d081875a` | unchanged |
| Artifact hash | `688c2184b4e9b8181946766e2577c1f1a53f9c88de2adf81a1d3affbc8dcd5fa` | unchanged |
| Holdout state | sealed / isolation verified | unchanged |
| Durable project link | active, exact dataset/version | unchanged |

File-level hashes for the local database, Dataset Library projections, recovery journal, and runtime checkpoint advanced after the safety snapshot. The Dataset Library diff is an exact-version link/projection timestamp refresh and retains the same project/dataset/version; the current logical query above is unchanged. The latest pre-final and post-final hashes are identical, proving the final hermetic test runs did not touch those live paths. The evidence-registry hash remained identical throughout. The security database remained sharing-locked and was not opened or copied.

Migration 0028:

- SHA-256 before and after: `2256C1AFD0EE4B8667DCADCA4422950B29144A7745B48394E83D1C2B72F672C8`
- source diff: none
- latest applied migration in the live read-only schema history: `0027_special_value_reviews.sql`
- migration 0028 remains unapplied and unchanged

## Manual live acceptance checklist

This checklist was prepared but not executed. Stop at the first successfully loaded EDA tab.

1. Open project `atlas-mrzpau4t` and navigate to Data Acquisition.
2. Confirm Special-Value Treatment Review shows 6/6 reviewed.
3. Confirm Atlas Guide shows target `bad_flag`.
4. Confirm the current Analysis Partition is `analysis-partition-688c2184b4e9b8181946-r1`, revision 1.
5. Select **Change Split Ratio - Creates New Revision** and confirm the governed impact workflow shows current counts of 5,020 development and 1,255 final holdout.
6. Cancel; confirm the partition remains revision 1 and no state changes.
7. Select the final Data Acquisition continuation action.
8. Confirm EDA loads the exact dataset ID/version, target mapping, predictor authorization, and Analysis Partition identity.
9. Confirm target-directed EDA reports Development Population and explicitly reports the sealed final holdout as excluded/not accessed.
10. Confirm no new partition revision was created, then stop before Outliers.

## Remaining limitations

1. **Legacy frontend hermetic packaging.** Six older DA/canonical frontend suites and the older `bureauDetectionExactBinding.test.mjs` could not import `typescript` (or, for one suite, read `package.json`) from their source-only child mirrors. Assertions did not execute. Dedicated source-contract suites covering this repair passed, and both the TypeScript compiler and production build passed against final source. Fixing the already-approved hermetic infrastructure is outside this focused product repair.
2. **Evidence canonical identity fixture.** `evidence_canonical_identity_test.py` produced 14 setup errors in each of two isolated runs because Windows denied creation of its backup directory. No test assertion or live authority was reached. Reopening infrastructure forensics was outside scope.
3. **Migration-0028-dependent legacy assertions.** Two older Analysis Partition contract assertions depend on migration 0028 behavior. The task expressly prohibited applying or editing that migration, so they remain legitimately blocked and are not claimed as green.
4. **Live browser acceptance.** No live browser action was performed. The checklist above is the only live acceptance deliverable.
5. **Mutable projection hashes.** File hashes for several live projection/runtime containers advanced during ordinary live-service activity between baseline and final audit. Exact logical HELOC authority and partition checksums remained unchanged, and the final hermetic runs left the resulting hashes stable.

## Safety confirmations

- The live HELOC Analysis Partition remains revision 1 with identical assignment, population, and artifact checksums.
- No sealed-holdout values or membership payload were read.
- No model training was started.
- Evaluation was not opened or executed.
- Interpretation was not opened or executed.
- No model promotion occurred.
- No Scoring occurred.
- Migration 0028 was neither applied nor modified.
- No live split revision or governed workflow completion was performed.
- The Git index is empty.
- Branch and HEAD are unchanged and match the upstream branch (`0 ahead / 0 behind`).
- No files were staged, committed, pushed, reset, restored, cleaned, stashed, discarded, deleted, amended, rebased, merged, or cherry-picked.
- No credentials, cookies, tokens, secrets, authentication headers, connection strings, or environment-variable values were printed.

## Final assessment

**READY FOR BOUNDED LIVE MANUAL DATA ACQUISITION ACCEPTANCE WITH DOCUMENTED NONBLOCKING HARNESS LIMITATIONS.**

The repaired DA-to-EDA contract is exact and fail-closed, the split-ratio workflow is discoverable and revision-safe, and Special-Value Review is table-first. The live HELOC partition is unchanged. Manual acceptance must stop after the first successfully loaded EDA tab.
