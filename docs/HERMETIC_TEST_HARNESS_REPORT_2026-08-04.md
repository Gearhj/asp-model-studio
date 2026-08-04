# ATLAS Hermetic Test Harness Report - 2026-08-04

## Scope and final verdict

This phase was limited to runtime-isolation forensics, test launchers, test
guards, test-only fixtures, and documentation. It did not change product
business logic, workflow pages, migration contents, migration execution, or
runtime stores.

**Final verdict: NOT READY: FORENSIC EVIDENCE INSUFFICIENT**

The harness behaviors themselves are demonstrated: pre-import authority setup,
fresh source-only children, negative alias protection, positive writes through
eight stores, concurrent database isolation, Node/live-backend rejection, and
representative high-risk suite execution. The overall requested validation
cannot receive a ready verdict because no verified pre-change database copies
exist, both live databases advanced again during this phase through an
unattributed external writer, and the live security database remained
sharing-locked during the final post-harness canary/current-state snapshot.
That prevented a final security canary count and a current live HELOC logical
state query. The lock was not bypassed.

## 1. Historical failure class

The prior failure class was import-order authority capture:

1. a Python test process imported `server.main` or a transitive ATLAS module;
2. provider modules resolved default live paths into module constants or
   process singletons;
3. a later test fixture changed environment configuration;
4. cached providers continued to reference the earlier authority; and
5. a nominally isolated test could write live persistence, security, Dataset
   Library, checkpoint, evidence, documentation, or artifact state.

The repository also contains hard-coded `__file__`-relative artifact roots for
EDA documentation, MDD, notebooks, analytics, projects, SQL Studio, and Credit
Risk Studio. Those roots cannot be redirected by environment alone.

## 2. Authority inventory

The complete machine-readable authority inventory is:

- `docs/HERMETIC_TEST_AUTHORITY_MAP_2026-08-04.csv`

It records each authority's default, configuration key, provider, import-time
behavior, reset/override mechanism, consumers, and hermetic resolution. The
principal dependency patterns are:

```text
child environment
  -> pre-import sitecustomize guard
  -> provider module or persistence singleton
  -> repository/store
  -> server.main and focused suite
```

Environment-configurable providers are directed under a unique child root.
Hard-coded `__file__` providers are isolated by executing a source-only mirror
whose `server/artifacts` tree is created empty beneath that same child root.
The parent launcher never imports an ATLAS application module.

## 3. Import-time caching inventory

High-risk import-time authorities include:

- `server.security.security_store`: security root/database and security-mode
  constants;
- `server.datasets.dataset_registry`: Dataset Library, registry, users, and
  project-link constants;
- `server.core.session_checkpoint`: checkpoint path and timer-backed state;
- `server.evidence.evidence_store`: evidence root, registry, and items roots;
- `server.model_registry.model_artifacts`: model artifact root;
- `server.scoring_runs.scoring_run_artifacts`: scoring artifact root;
- `server.python_execution`: Python runtime and SAS configuration roots;
- EDA documentation, MDD, notebook, analytics, project, SQL Studio, and Credit
  Risk stores: hard-coded `__file__`-relative roots.

`server.persistence.db.get_database` refreshes its singleton if the configured
database changes, while many legacy tests still rebind module constants. The
harness does not rely on those late test hooks: it establishes all authorities
before `sitecustomize`, plugins, test collection, or ATLAS imports.

## 4. Parent and child design

`scripts/run_hermetic_tests.py` defaults exclusively to
`HERMETIC_REGRESSION`. It rejects any other mode and accepts either explicit
suite targets or the checked-in representative-suite manifest.
An explicit `CONTROLLED_LIVE_ACCEPTANCE` attempt was rejected before a run
root was created with safe launcher exit code 64; live acceptance is not
implemented by this harness.

For each invocation it:

1. creates a unique run ID and Windows Temp root;
2. creates a short unique physical child root to avoid Windows path pressure;
3. validates every authority before creating the source mirror;
4. copies only source/configuration file types from `server`, `scripts`,
   `tests`, and `shared`;
5. excludes `.git`, `.env*`, runtime roots, artifacts, raw/binary data,
   migration `0028`, and reparse-linked source;
6. creates all required external authority roots;
7. builds a sanitized child environment and test metadata;
8. starts one fresh bootstrap process per compatible suite family;
9. executes the pre-import guard from `sitecustomize`;
10. captures PID, run/suite identity, timestamps, result, safe failure category,
    and created-file inventory; and
11. preserves all evidence without automatic deletion.

Nested Python interpreters re-run the full guard. They may inherit the parent's
post-guard sentinel, but every authority, run identifier, source root, metadata
field, and live-backend restriction is revalidated before any ATLAS import.

## 5. Environment setup order

The child receives isolated locations for:

- persistence and security databases;
- Dataset Library, catalog files, links, active selections, and backups;
- checkpoint/workflow compatibility state;
- persistence-backed target, predictor, partition, training, candidate,
  Evaluation, Model Registry, and scoring metadata;
- evidence, feature manifests, model artifacts, scoring artifacts, VIF plans,
  Python/SAS runtime, browser storage, and Playwright output; and
- hard-coded documentation/analytics/project/notebook/Credit Risk roots through
  source-mirror relocation.

Only after that complete map exists does the bootstrap import ATLAS. A source
manifest and authority manifest are written for each child. The final source
manifests report `migration_0028_included=false` and
`raw_data_included=false`.

## 6. Canonical path and alias protections

The pure-standard-library guard canonicalizes paths and fails before ATLAS
import for:

- relative paths and traversal;
- UNC/device aliases;
- case-insensitive aliases;
- detectable 8.3 aliases;
- symlinks, junctions, and reparse components;
- repository roots and repository pseudo-temporary roots;
- exact live paths and live parent/child overlap;
- Dataset Library source/backup overlap;
- pairwise test-authority overlap; and
- shared writable databases across children.

Filesystem inventories never follow symlinks, junctions, or reparse points.
This was added after one negative junction scenario caused a read-only walker
to enumerate through the preserved link; no file was copied or changed, and
both database hashes were unchanged immediately afterward.

## 7. Negative guard results

The final guard run covered rejection of:

- live persistence and security databases;
- live Dataset Library, checkpoint, evidence, MDD, and feature roots;
- repository `.tmp`;
- live parent and child aliases;
- case, relative, traversal, UNC/device, symlink, junction, and available
  short-name aliases;
- backup/source overlap;
- missing authority metadata;
- missing/invalid run identity;
- shared writable databases; and
- a cached `server.*` module before bootstrap.

Run `atlas-hrt-20260804-181031-d80c286b1e` passed 12 guard tests and 8
subtests; one platform-dependent alias test was skipped because the operating
system did not expose that alias mechanism. A rejected launch uses exit code
86 and emits only a safe category. An intentional missing-target scenario used
run `atlas-hrt-20260804-172855-44403c2428`: the missing child failed with exit
88 while the independent guard child (PID 92848) passed, proving child-failure
independence.

## 8. Positive guard and import-cache results

Positive coverage proves:

- external unique roots are accepted;
- all configured authorities exist beneath the correct child;
- required metadata is present;
- inherited nested-child guard state is fully revalidated;
- a fresh process imports `server.main`, security, persistence, Dataset
  Library, checkpoint, evidence, MDD, notebooks, feature manifests, model
  artifacts, and scoring artifacts;
- writes through security, persistence, Dataset Library, checkpoint, evidence,
  MDD, and feature-manifest stores remain beneath the child root; and
- migration `0028` is absent and unapplied in the child.

Concurrent run `atlas-hrt-20260804-175602-2889ab27f7` used PIDs 81344 and
100076. Both children passed, each recorded eight store writes, each created
2,702 files, and each isolated security database contained exactly one of its
own synthetic users. Cross-child isolation status was `passed` with fixture
counts `[1, 1]`.

## 9. Test-run canaries

Synthetic identifiers use the fixed safe prefix `atlas-hrt-` and never use the
HELOC project, dataset, or user identity.

Available final live checks found:

- persistence main database raw bytes: zero prefix occurrences;
- 645 safe JSON files under `.runtime` and `server/artifacts`: zero matching
  files and zero occurrences, with no read/enumeration/stability failures;
- earlier strict scans of the live security main: zero occurrences before the
  final representative runs; and
- every resolved child authority manifest: external and unique.

The last post-test scan completed at 18:12 UTC, after the final negative-launch
guard scenario. Persistence remained stable at the hash recorded in the
forensic report, no SQLite sidecar existed, and the JSON scan had zero read,
enumeration, or stability errors.

The final security main-file scan could not be repeated because a Windows
sharing lock denied even a strict non-writer read handle. The lock was not
weakened. Therefore a final zero-live-security-canary result cannot be claimed,
which is one reason for the non-ready verdict.

## 10. Representative high-risk suites

All entries below were invoked through `scripts/run_hermetic_tests.py`; none was
run directly.

| Suite | Run ID | PID | Result | Child duration | Files / bytes |
|---|---|---:|---|---:|---:|
| Guard | `atlas-hrt-20260804-181031-d80c286b1e` | 102252 | 12 passed; 8 subtests passed; 1 skipped | 11.60 s | 829 / 14,010,183 |
| Node/browser guard | `atlas-hrt-20260804-180041-17f06fc37f` | 94640 | 5 passed | 0.22 s | 643 / 10,517,523 |
| Storage-isolation guard | `atlas-hrt-20260804-174116-142019b517` | 102008 | 24 passed | 69.71 s | 2,814 / 64,174,943 |
| Concurrent import/store probe A | `atlas-hrt-20260804-175602-2889ab27f7` | 81344 | passed; 8 stores | 25.44 s | 2,702 / 62,958,811 |
| Concurrent import/store probe B | `atlas-hrt-20260804-175602-2889ab27f7` | 100076 | passed; 8 stores | 25.46 s | 2,702 / 62,958,812 |
| Dataset Library recovery | `atlas-hrt-20260804-174933-a2968b1790` | 87888 | 61 passed; 27 subtests passed | 122.10 s | 1,442 / 29,522,603 |
| Canonical dataset identity | `atlas-hrt-20260804-174931-2e495c1b1c` | 97028 | 10 passed; 18 warnings | 106.46 s | 2,903 / 65,514,497 |
| Analysis Scope | `atlas-hrt-20260804-175155-ec0533596e` | 97192 | 32 passed; 1 performance assertion failed; 2 subtests passed; 18 warnings | 219.03 s | 2,908 / 67,608,849 |
| Analysis Partition | `atlas-hrt-20260804-174256-0edb643f37` | 98036 | 11 passed; 2 migration-0028-dependent assertions failed | 30.60 s | 1,994 / 42,695,475 |
| Project Context hydration | `atlas-hrt-20260804-174442-2ab2fc94a9` | 100600 | 3 passed; 6 subtests passed; 18 warnings | 43.53 s | 2,902 / 65,471,996 |
| Feature Engineering | `atlas-hrt-20260804-173520-5061def3fa` | 92040 | 8 passed; 7 subtests passed | 12.49 s | 1,454 / 29,447,979 |
| Model Registry durability | `atlas-hrt-20260804-173520-5061def3fa` | 100192 | 29 passed; 4 subtests passed | 36.30 s | 1,205 / 22,074,764 |
| Security gate | `atlas-hrt-20260804-174900-ac8dcc9f69` | 98616 | 34 passed; 6 authorization assertions failed; later entries not run by fail-fast gate | 196.33 s | 9,185 / 213,240,643 |

The exact external temporary root for each reported child was:

| Suite / child | External temporary root |
|---|---|
| Guard | `C:\Users\james\AppData\Local\Temp\atlas-hrt-20260804-181031-d80c286b1e\c\e14c97c9f5` |
| Node/browser guard | `C:\Users\james\AppData\Local\Temp\atlas-hrt-20260804-180041-17f06fc37f\c\4455e4f8d6` |
| Storage-isolation guard | `C:\Users\james\AppData\Local\Temp\atlas-hrt-20260804-174116-142019b517\c\2a5e1b3e76` |
| Concurrent import/store probe A | `C:\Users\james\AppData\Local\Temp\atlas-hrt-20260804-175602-2889ab27f7\c\ff431b3025` |
| Concurrent import/store probe B | `C:\Users\james\AppData\Local\Temp\atlas-hrt-20260804-175602-2889ab27f7\c\5cc566e816` |
| Dataset Library recovery | `C:\Users\james\AppData\Local\Temp\atlas-hrt-20260804-174933-a2968b1790\c\f6616b0c66` |
| Canonical dataset identity | `C:\Users\james\AppData\Local\Temp\atlas-hrt-20260804-174931-2e495c1b1c\c\130dd3ee74` |
| Analysis Scope | `C:\Users\james\AppData\Local\Temp\atlas-hrt-20260804-175155-ec0533596e\c\ee5f1bbe74` |
| Analysis Partition | `C:\Users\james\AppData\Local\Temp\atlas-hrt-20260804-174256-0edb643f37\c\02d19694a8` |
| Project Context hydration | `C:\Users\james\AppData\Local\Temp\atlas-hrt-20260804-174442-2ab2fc94a9\c\255a1b66f1` |
| Feature Engineering | `C:\Users\james\AppData\Local\Temp\atlas-hrt-20260804-173520-5061def3fa\children\feature_engineering_acceptance_repair_test-8b7c367a08` |
| Model Registry durability | `C:\Users\james\AppData\Local\Temp\atlas-hrt-20260804-173520-5061def3fa\children\model_registry_durability_test-26d39a69d7` |
| Security gate | `C:\Users\james\AppData\Local\Temp\atlas-hrt-20260804-174900-ac8dcc9f69\c\e691d469b7` |

These roots and their structured summaries were preserved. The shortened
children also used a suite-local operating-system temporary directory at
`<external temporary root>\t`.

The Analysis Scope failure measured approximately 668 ms against a 500 ms warm
overhead threshold; it was not an authority/path failure. The two Analysis
Partition failures expect the project-deletion cascade supplied by migration
`0028`, which was deliberately excluded because this phase forbids applying or
editing it. The security gate passed its first four behavioral files (34 tests)
and then recorded six role-authorization expectation failures in the fifth;
that is a product-contract result and was not repaired in this isolation phase.
Its captured output contained eight warning lines, including four deprecation
warning lines; later gate entries were not executed after the fail-fast result.

No representative child reported a live resolved authority. All evidence roots
were preserved.

## 11. Windows fixture corrections

Three test-only fixtures used `tempfile.mkdtemp` for Dataset Library backups.
Under the restricted Windows test token, Python created owner-only directories
that the same restricted child could not traverse, yielding `WinError 5` below
otherwise hermetic paths. The fixtures now create collision-resistant
directories beneath the already-isolated child Temp authority with inherited
test ACLs. Corrected reruns passed for canonical identity and Project Context;
Analysis Scope advanced to its independent performance assertion.

The storage-isolation fixture also now resets the pre-import sentinel before a
nested interpreter. The generalized guard independently revalidates inherited
nested-child state, as demonstrated by the 61-test Dataset Library recovery
pass.

## 12. Node and browser isolation

`scripts/hermetic_node_guard.mjs` requires hermetic mode, run/test metadata,
and browser/Playwright roots beneath the child root. It rejects:

- `http://127.0.0.1:8001`;
- `http://localhost:5174`;
- the IPv6 loopback equivalent; and
- browser storage outside the child root.

The final Node run passed all five tests. It did not use Playwright, an existing
browser profile, an authenticated session, the live backend, or the HELOC
project. `CONTROLLED_LIVE_ACCEPTANCE` remains unimplemented and was not run.

## 13. Forensic and protected-state result

The historical, immutable 15:05 persistence copy confirms the expected HELOC
project, dataset, dataset version, Analysis Partition, revision, counts, seed,
stratification, assignment checksum, artifact checksum, active link, active
activation, and sealed/verified status. No row membership or holdout value was
read.

That copy is not a current-state proof. Both live main files advanced again at
approximately 17:25:47 UTC. The persistence main was stable in the final check,
but the security main remained sharing-locked, so no safe current immutable
pair could be captured and current HELOC logical state could not be queried.
The process responsible remains unresolved. See
`docs/RUNTIME_ISOLATION_FORENSIC_REPORT_2026-08-04.md`.

No new training job, Evaluation, Interpretation, promotion, or Scoring was
executed by this phase. No sealed-holdout contents or membership were accessed.

## 14. Service-state result

An initial non-elevated listener probe incorrectly reported no services. A
later read-only elevated process inspection showed the pre-existing frontend
listener on PID 86880 and backend listener on PID 89928, both started before
this phase. No service action was taken.

During later forensic checks both listeners disappeared without any start,
stop, kill, or restart action by this work. Final checks reported no listener
on ports 5174 or 8001. That external lifecycle change and the later database
locks are unresolved and are not attributed to the harness.

## 15. Exact commands used for final harness validation

Key launcher commands were:

```powershell
.\.venv\Scripts\python.exe scripts\run_hermetic_tests.py --suite tests/hermetic_test_harness_test.py --suite tests/hermetic_node_guard.test.mjs
.\.venv\Scripts\python.exe scripts\run_hermetic_tests.py --suite tests/test_storage_isolation_guard_test.py
.\.venv\Scripts\python.exe scripts\run_hermetic_tests.py --suite tests/hermetic_import_cache_probe.py --suite tests/hermetic_import_cache_probe.py --concurrent
.\.venv\Scripts\python.exe scripts\run_hermetic_tests.py --suite tests/dataset_library_recovery_test.py
.\.venv\Scripts\python.exe scripts\run_hermetic_tests.py --suite tests/canonical_dataset_identity_test.py
.\.venv\Scripts\python.exe scripts\run_hermetic_tests.py --suite tests/analysis_scope_test.py
.\.venv\Scripts\python.exe scripts\run_hermetic_tests.py --suite tests/analysis_partition_contract_test.py
.\.venv\Scripts\python.exe scripts\run_hermetic_tests.py --suite tests/project_context_hydration_authority_test.py
.\.venv\Scripts\python.exe scripts\run_hermetic_tests.py --suite tests/feature_engineering_acceptance_repair_test.py --suite tests/model_registry_durability_test.py
.\.venv\Scripts\python.exe scripts\run_hermetic_tests.py --suite scripts/run_security_tests.py
```

Final static checks parsed five Python harness files, the authority CSV, and the
representative JSON manifest; ran `node --check` for both Node files; and ran
`git diff --check` over the narrow phase files. They passed. Git emitted only
line-ending advisories for four already-modified files.

Baseline Git commands were the required read-only status, branch, HEAD, log,
diff, cached-index, and untracked-file inventory commands. Evidence is under:

- `C:\Users\james\AppData\Local\Temp\atlas-runtime-isolation-20260804-123957`

Final Git verification retained branch
`codex/phase2a-canonical-lineage` at
`24961ad4da6566c53cf4634796a439f7498fcc0e`, exactly synchronized with its
configured upstream. It reported 279 pre-existing-plus-phase working-tree
entries, zero index entries, zero tracked deletions, and no `git diff --check`
error. Permission notices for already-existing pytest cache directories and
line-ending advisories were non-mutating warnings.

## 16. Files changed by this phase

Harness and guard files:

- `scripts/hermetic_test_authority.py`
- `scripts/hermetic_test_bootstrap.py`
- `scripts/run_hermetic_tests.py`
- `scripts/hermetic_node_guard.mjs`
- `scripts/run_security_tests.py`
- `tests/hermetic_test_harness_test.py`
- `tests/hermetic_import_cache_probe.py`
- `tests/hermetic_node_guard.test.mjs`
- `tests/hermetic_representative_suites.json`
- `tests/test_storage_isolation_guard_test.py`

Test-only Windows authority fixtures:

- `tests/canonical_dataset_identity_test.py`
- `tests/analysis_scope_test.py`
- `tests/project_context_hydration_authority_test.py`

Reports:

- `docs/RUNTIME_ISOLATION_FORENSIC_REPORT_2026-08-04.md`
- `docs/HERMETIC_TEST_HARNESS_REPORT_2026-08-04.md`
- `docs/HERMETIC_TEST_AUTHORITY_MAP_2026-08-04.csv`

No `server` product source, frontend page, migration, schema, or runtime-store
implementation was changed by this phase.

## 17. Remaining limitations and separate follow-ups

1. Acquire transactionally consistent before/after database snapshots in a
   separately authorized, quiescent forensic phase.
2. Identify the process holding and advancing the live security/persistence
   authorities with approved process-to-file attribution evidence.
3. Address the Analysis Scope performance threshold separately.
4. Reconcile the six security role-authorization expectations separately; do
   not weaken authorization to satisfy them.
5. Run the two migration-0028-dependent partition assertions only in a phase
   that explicitly authorizes that isolated migration contract.
6. Consider production configuration hooks for the hard-coded documentation,
   notebook, analytics, project, SQL Studio, and Credit Risk roots. This would
   be a production-source change and was intentionally not attempted here.
7. Investigate the source-defined development credential defaults in a focused
   security phase. During this run, a broad provider-source read emitted a
   source-defined password-default literal. It was not read from an environment
   variable, database, cookie, token, session, or live credential, but the
   requested blanket no-password-output confirmation cannot be made.

## 18. Safety confirmations

- Migration `0028` was not edited, copied into a child mirror, or applied by
  the harness. The historical verified database copy records migrations only
  through `0027`; the locked current security authority does not change that
  persistence-copy finding.
- No service was started, stopped, killed, or restarted by this phase.
- No product workflow source was changed.
- No model training, Evaluation, Interpretation, promotion, or Scoring occurred.
- No sealed-holdout positions, values, membership lists, or raw regulated rows
  were accessed.
- The Git index remained empty throughout validation.
- Nothing was staged, committed, pushed, reset, restored, checked out, cleaned,
  amended, rebased, merged, cherry-picked, stashed, deleted, or discarded.
- No environment-variable value, live credential record, token, cookie,
  session value, authentication header, API key, or connection string was
  printed. A source-defined password-default literal was accidentally emitted
  during source inventory, so a broader no-password-output confirmation is not
  possible.
- No live database was opened with SQLite after the initial sidecar incident;
  final current-state snapshot attempts failed closed on the security sharing
  lock.
