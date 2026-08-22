# Phase 7A.2 — Independent Codex Authority Gate

Date: 2026-08-20  
Repository: `C:\Users\james\asp-model-studio`  
Branch: `phase7-advanced-mlb-data-integration`  
HEAD: `06c880a05d3e79ba9b0d8f81fec3fb4f80130ffb`

## Executive decision

Phase 7A.2 is not an acceptable authority boundary for advanced acquisition. The Gen-3 research object, temporal masks, row counts, governed preprocessing code, and stored A2 metrics are internally coherent. The new server panel can also execute a narrowly correct Gen-3 2021–2023 development / 2024 validation path under honest state.

Those positives do not establish the claimed product invariant. The application still has two Model Laboratory execution systems; the prominent legacy system bypasses the active binding, executes the fixed Gen-2 object, scores 2025, and exposes its metrics. Every new project route is authenticated but lacks project authorization. Raw `projectId` values control filesystem roots. Gen-2 bindings are stamped with Gen-3 contracts, superseded bindings remain executable, execution does not verify the registered object's hashes/contracts, and the result cannot echo the required contract SHA identities because it does not contain them. The new authorized result is also disconnected from the downstream scientist stages.

The reported A2 log-loss difference is numerically credible but is not an independently bound run proof. It exists in a mutable reconciliation JSON that omits the run authority, full dataset identity, contract/config/environment identities, predictions, and preprocessor fingerprint. A bounded independent research-only A2 refit was stopped before completion, so this audit does not misrepresent the stored `3.55e-10` value as an independently reproduced result.

## 1. Repository and change audit

| Item | Observation |
|---|---|
| Branch | Exact: `phase7-advanced-mlb-data-integration` |
| HEAD | Exact: `06c880a05d3e79ba9b0d8f81fec3fb4f80130ffb` |
| Baseline used for Phase 7A diff | `e9d3f64` |
| Phase 7A.1/7A.2 commits | `5b23d75`, `9a2af0e`, `8212aa4`, `c5d8b4e`, `dee5f6c`, `06c880a` |
| Tracked delta | 22 files; 2,420 insertions and 19 deletions |
| Raw/runtime artifacts committed | None in `git diff --name-status e9d3f64..HEAD` |
| `git diff --check` | Passed |
| Pre-existing untracked reports | `GPT56_SOL_INDEPENDENT_ASP_AUDIT.md`; `docs/PHASE_7_CORE_CODEX_ACCEPTANCE_REPORT.md` |
| Application files modified by this audit | None |
| File created by this audit | `docs/PHASE_7A2_CODEX_ACCEPTANCE_REPORT.md` only |

The six commits introduce the Gen-3 contracts/publication path, authority service and routes, server-catalog UI panels, flow tests, and A2 reconciliation. The untracked reports were preserved unchanged.

## 2. Data Warehouse server catalog

### What passes

- Data Warehouse mounts `Gen3CatalogSection` and obtains its cards from authenticated `/cockpit/gen3/catalog` rather than embedding the dataset entries directly in the component (`src/sports/SportsEvidenceSurfaces.tsx`; `src/sports/cockpit/Gen3CatalogSection.tsx:24-34`).
- The returned UI contains a selectable Gen-2 entry, a selectable Gen-3 research entry, and a separate Gen-3 sealed-2025 entry.
- The sealed entry is represented as `GEN3_SEALED`, `SEALED_OOT_RESTRICTED`, and `selectable: false`; `create_binding` rejects nonselectable entries before object verification (`server/sports_cockpit/gen3_authority.py:128-136,179-186`). Direct selection of the known sealed catalog version therefore fails closed.

### What fails

The endpoint is server-returned but is not an authoritative registry resolver:

- `catalog()` synthesizes Gen-2 from a fixed/glob-resolved object and Gen-3 from one mutable registration file (`gen3_authority.py:87-141`).
- `register_gen3()` writes a separate ASP registry, but `_resolve_version()` ignores it and iterates the synthesized catalog (`gen3_authority.py:144-163`).
- Gen-2 rows, seasons, roles, target, and label are hard-coded. The API also returns absolute `objectPath` values (`gen3_authority.py:91-104,110-127`).
- Merely mounting the UI POSTs `/cockpit/gen3/register`; any authenticated user can trigger this global registry mutation (`Gen3CatalogSection.tsx:24-34`; `router.py:178-180`).
- The frontend truncates immutable IDs and hard-codes “8-class,” “Pregame-safe,” and governance labels rather than displaying contract-derived server evidence (`Gen3CatalogSection.tsx:66-77`).

Result: Data Warehouse server-backed = **partial pass**. Visibility is real, but registration/resolution and displayed scientific semantics are not authoritative enough for the claimed invariant.

## 3. Data & Population binding

Selecting a dataset in the new panel does create a backend `PROJECT_MODELING_DATASET_BINDING_V1` containing an opaque binding ID, project/actor strings, full dataset version and logical content SHA, generation, feature-view ID, contract IDs/SHAs, development seasons, validation season, and sealed seasons (`gen3_authority.py:179-205`). A friendly label alone cannot be submitted as a version because `_resolve_version` requires an exact catalog version ID.

The binding nevertheless fails the acceptance gate:

1. `projectId` is client text, not an authorized canonical project. Routes only check that it is nonblank (`router.py:166-170`).
2. The stored `actor` is never used to authorize later reads or operations. `_validate_authority(..., actor)` never compares it (`gen3_authority.py:282-317`).
3. `create_binding` unconditionally stamps `GC.all_contracts()` onto both generations (`gen3_authority.py:188-200`). The Gen-2 catalog entry itself reports no target or temporal contract IDs (`gen3_authority.py:87-104`), yet a Gen-2 binding claims the Gen-3 target, population, temporal, feature, and preprocessing contracts.
4. The scientific authority is duplicated. The legacy `DatasetSection` and guided workflow still use localStorage/notes as their binding authority and completion signal (`src/sports/cockpit/cockpitSteps1.tsx:42-56,212-305`; `src/sports/workflow/workflowState.ts:59-69,229-243`).
5. A server-side Gen-2↔Gen-3 switch does not call `invalidateForDatasetChange`. Target/configuration/lab/results can therefore survive a material data-authority change (`Gen3CatalogSection.tsx:106-112`; `cockpitSteps1.tsx:220-224`; `cockpitApi.ts:299-328`).

Result: Data & Population server binding = **implemented but not accepted as project scientific authority**.

## 4. Active-binding restore and stale state

The service primitive returns the pointer-selected binding, and returns `None` when no active pointer exists (`gen3_authority.py:217-225`). The selection panel refreshes from the server after a bind, so the latest pointer wins in that one component under a normal same-project request (`Gen3CatalogSection.tsx:106-112`).

The complete behavior fails:

- All restore errors—401, 403, 404, 422, 500, or network—are collapsed to `null`, not only a genuine 404 (`Gen3CatalogSection.tsx:39-50`).
- The Model Lab effect has an empty dependency array even though it reads `projectId`; changing projects can retain the prior project binding (`Gen3AuthorityPanel.tsx:41-57`).
- On any Model Lab restore failure, the first selectable entry is silently preselected (`Gen3AuthorityPanel.tsx:48-54`). Other UI locations also substitute fixed project/dataset defaults.
- Every new binding remains `revision: 1, status: ACTIVE`. Creating a later binding replaces only `active.json`; the earlier binding remains issuable and executable because `issue_run_authority` never requires it to equal the active pointer (`gen3_authority.py:189-204,236-244`). A stale tab can therefore execute Gen-2 after another tab selects Gen-3.
- When a new project has no local cockpit snapshot, `useCockpitPersistence` advances `hydratedFor` without resetting the singleton store. In-memory notes/config/lab/result from project A can remain visible in project B (`src/sports/cockpit/cockpitPersistence.ts:81-103`).

Result: binding restore = **partial**; server-wins stale browser state = **fail**; cross-project binding access = **fail**.

## 5. Target, population, temporal, feature, and preprocessing authority

### Gen-2

The backend masks development season 2023 and validation season 2024. Its combined object contains seasons 2023, 2024, and 2025 (`gen3_authority.py:87-104,331-345`). The selected fit masks are therefore correct in the narrow sense.

Identity is not correct. The binding does not obtain registered Gen-2 contracts; it attaches the current Gen-3 contract bundle. Execution also does not verify the Gen-2 object's logical/physical hash, embedded feature contract, schema, row count, or preprocessing authority before fitting.

### Gen-3

Independent inspection of the research-only object established:

| Population | Rows |
|---|---:|
| 2021 | 181,752 |
| 2022 | 181,979 |
| 2023 | 184,104 |
| Development 2021–2023 | **547,835** |
| Validation 2024 | **182,449** |
| Research object total 2021–2024 | 730,284 |

The registered research logical content SHA is `05c91a1471385d30933356ce0026cf715bb4c7566ce035efe71c75af6ad39124`. The ordered 22 input features expand to 32 model columns for both development and validation under `FoldPreprocessor`. The target class order is:

`STRIKEOUT, WALK_HBP_CI, HOME_RUN, SINGLE, DOUBLE, TRIPLE, BIP_OUT, OTHER_REACH`.

Every 2021 row was correctly prior-blind in the inspected research object: both prior-missing flags were set and all batter/pitcher prior-stat columns were non-finite. The temporal and preprocessing implementation used by the governed and server paths is aligned: chronological 0.8 inner development split, fold-training-only mean imputation, standardization, and one-hot encoding for the three categorical context features.

There are two material authority defects:

- `_verify_object` verifies only existence, non-symlink status, and the season column. It does not recompute physical/logical SHA, inspect embedded metadata/contracts, verify schema/row count, or prove the resolved path is beneath an immutable object root (`gen3_authority.py:166-175`). A changed file can execute while the result repeats the catalog's old SHA.
- `MLB_GEN3_KNOWLEDGE_TIME_CONTRACT_V1` claims every feature is known before the scheduled game begins (`server/sports_modeling/gen3_contracts.py:72-79`). The feature set includes inning, half, outs, bases, and score difference immediately before the target plate appearance. The frozen Gen-2 contract correctly describes this as conditional pre-terminal plate-appearance state and explicitly says it is not pregame-known (`server/sports_modeling/feature_contract.py:344-363`). The UI's “Pregame-safe (governed)” label is therefore scientifically false.

Result: Gen-3 rows/folds/preprocessing = **verified**; complete immutable scientific identity = **not verified/incorrectly described**.

## 6. Model Laboratory binding

The new `Gen3AuthorityPanel` can consume a restored binding and issue an authority. It is not the exclusive or downstream-authoritative Model Laboratory:

- The panel independently loads the catalog, silently defaults the first selectable entry after any binding error, renders its own dataset selector, and can create a new binding (`Gen3AuthorityPanel.tsx:31-64,93-109`). It does not merely consume the selection made in Data & Population.
- The existing candidate suite remains directly below it and POSTs only a client config to `/cockpit/experiment/run` (`src/sports/cockpit/cockpitSteps2.tsx:53-70,86-131`). It has no project, binding, version, content SHA, or contract authority.
- The legacy backend always evaluates both 2024 and 2025 and returns/computes champion comparisons from both (`server/sports_cockpit/modeling.py:517-532,604-646`). The UI stores and displays `frozen2025` (`cockpitSteps2.tsx:62-70,369-370,422-440,482-493,601-676`).
- The Gen-3 result stays in component-local `result` state. It never calls Zustand `setLastResult`; Evaluation, Calibration, Simulation, Champion/Challenger, and Registry all read `lastResult` (`Gen3AuthorityPanel.tsx:34-39,67-74`; `cockpitSteps2.tsx:422,482,522,601,657`). Repository search finds no caller of `setLastResult` beyond its definition (`cockpitApi.ts:224,290`).

Result: Model Lab binding = **fail**. A Gen-3 selection can coexist with a prominent Gen-2 execution, and a successful authorized run cannot flow into the remaining scientist workflow.

## 7. End-to-end authority invariant

| Identity | UI → binding | Binding → authority | Authority → loaded object | Authority → result | Overall |
|---|---|---|---|---|---|
| Dataset version | Partial; independent/legacy selectors coexist | Present | Path chosen from synthesized catalog, not verified registry object | Present | **Fail** |
| Dataset content SHA | Displayed truncated; legacy path omits it | Present | Claimed SHA is not recomputed against bytes | Present | **Fail** |
| Target contract SHA | Not displayed | Present | Gen-2 incorrectly receives Gen-3 SHA | Absent from result | **Fail** |
| Population contract SHA | Not displayed | Present | Same generation mismatch risk | Absent from result | **Fail** |
| Temporal contract SHA | UI shows shortened ID, not SHA | Present | Gen-2 incorrectly receives Gen-3 SHA | Absent from result | **Fail** |
| Feature contract SHA | Not displayed | Present | Object metadata/schema not verified | Absent from result | **Fail** |
| Preprocessing contract SHA | UI hard-codes a friendly description | Present | Server code uses the governed preprocessor, but object/contract binding is not proven | Absent from result | **Fail** |

The backend result assertions compare only `runAuthorityId`, canonical config SHA, and dataset content SHA (`gen3_authority.py:408-411`). The UI compares only the first two (`Gen3AuthorityPanel.tsx:83-84`). Although result evidence contains contract IDs, it omits all five contract SHA fields (`gen3_authority.py:385-401`). The exact invariant requested by the gate cannot be represented, much less independently verified, at the result layer.

## 8. Gen-2 / Gen-3 execution distinction

Code masks are distinct:

- Gen-2 binding: development `[2023]`, validation `2024`.
- Gen-3 binding: development `[2021, 2022, 2023]`, validation `2024`.

Under an untampered, current binding, the isolated authority executor uses those masks (`gen3_authority.py:328-345`). Independent research-object inspection verified the Gen-3 row membership and matrix dimensions. A Gen-2 execution was deliberately not run because its loader deserializes the combined 2023–2025 object before masking.

The product cannot guarantee that neither executes the other:

- the legacy candidate suite always bypasses the active binding;
- superseded bindings remain executable;
- current object bytes are not hash/contract verified;
- server-side dataset changes do not invalidate stale browser experiment state.

Forged contract SHA and config-fingerprint fields are checked, and known sealed catalog selection is rejected. However, contract IDs, generation, actor, current active-binding status, and current code/environment are not fully validated. This is stored-field self-consistency, not complete execution authority.

## 9. A2 scientific equivalence

### Stored and code-level evidence

| Check | Governed A2 logistic | Server-authorized reconciliation |
|---|---:|---:|
| Development seasons | 2021–2023 | 2021–2023 |
| Development rows | 547,835 | 547,835 |
| Validation season | 2024 | 2024 |
| Validation rows | 182,449 | 182,449 |
| Selected C | 0.05 | 0.05 |
| Iterations | 673 | 673 |
| Log loss | **1.48273326** | **1.4827332596445002** |
| Reported absolute difference | — | **3.5549985e-10** |
| Predeclared tolerance | — | `1e-6` |

The governed script and authority executor use the same `FEATURE_NAMES`, `FoldPreprocessor`, development/validation masks, chronological date-atomic 0.8 inner split, C grid, L2/LBFGS solver, `max_iter=2000`, `tol=1e-7`, label encoding, class order, and `evaluate_multiclass` implementation (`scripts/phase7a_governed_ablation.py:66-143`; `gen3_authority.py:328-380`). The authority records seed `20260819`, but neither logistic constructor supplies `random_state`; both operational fits therefore use the same effective `random_state=None`. The declared seed is metadata-only for logistic and should not be represented as an applied estimator parameter.

The stored result is not independently reproducible evidence:

- `.runtime/.../reconciliation-7a2.json` has no producing code path and is only read/trusted by a test.
- It omits full dataset SHA, run/binding/authority IDs, all contract SHAs, canonical effective-config SHA, code/environment identity, class order, predictions, and preprocessor fingerprint.
- The governed source record was produced at older revision `e9d3f64` with `dirtyTree=true`, not at audited HEAD.
- One exact independent A2 refit was attempted on the asserted 2021–2024 research object and stopped cleanly at the 120-second bound before returning a metric. No partial result or artifact was persisted.

The numerical equivalence is accepted as **stored/code-equivalent evidence within tolerance**, but not as an immutable server-authority proof and not as a reason to accept the phase.

The former `1.49223` result is correctly explained: governed HGB A2 has log loss `1.49222912`, Brier `0.70833116`, top-1 `0.45102467`, macro-F1 `0.09109444`, no early stopping, and 200 iterations. It is not the logistic A2 result.

## 10. 2025 physical blinding

The answer differs by path and must not be collapsed into one success badge.

### Isolated Gen-3 authority path

- Research object seasons are physically 2021–2024.
- The sealed 2025 object is a separate nonselectable registration with no executable `objectPath` in its catalog entry.
- Gen-3 development is 2021–2023 and validation is 2024.
- Result evidence contains validation metrics only; no 2025 metric/prediction field is present.

This narrow path passes by current code design.

### Complete server-authorized product / Model Lab

- Catalog construction hashes the full combined Gen-2 2023–2025 parquet with `path.read_bytes()` twice (`gen3_authority.py:87-100`). Catalog access is part of Model Lab mount, binding resolution, authority issuance, and authority validation.
- Executing Gen-2 calls `pq.read_table` for all feature and outcome columns across the combined object before applying season masks; `encode_labels(labels)` also sees the full labels array (`gen3_authority.py:320-346`).
- The legacy Model Lab endpoint actually evaluates 2025 and returns `frozen2025` metrics (`modeling.py:517-532,614-646`).
- `sealedSeasonsLoaded: []` is hard-coded, not observed instrumentation, yet the UI renders it as “confirmed” (`gen3_authority.py:396`; `Gen3AuthorityPanel.tsx:149`).

Therefore the complete product claims “2025 is not opened,” “not scored,” and “not payload-exposed” are false.

Audit safety statement: this audit did **not** open the Gen-3 sealed object, deserialize the Gen-2 combined object, score 2025, or expose 2025 predictions. Research-only diagnostics asserted seasons exactly `{2021, 2022, 2023, 2024}`.

## 11. Experiment identity and retries

### Narrow passes

- Run-authority and experiment-run IDs are random opaque UUID hex values.
- Each successful execution creates a new run ID; a collision is rejected, and `_write_json_atomic` is used (`gen3_authority.py:383-407`).
- The same authority can create distinct retry records rather than overwrite a config-hash filename.
- Evidence is written only after fitting/metrics. An interrupted fit cannot create a `COMPLETE` evidence record through this function.

### Failures

- There is no `RUNNING` or `FAILED` attempt record, so operational retry history and interruption evidence are absent.
- “Append-only/immutable” is a convention over mutable JSON files; records are not content-addressed, signed, permission-hardened, or registry-transaction-bound. Existing tests directly tamper shared authority JSON.
- The effective fingerprint includes stored contract SHAs, revision, and environment SHA, but excludes contract IDs, generation, actor, binding status/revision, and dirty-tree content. `dirtyTree` is only a Boolean.
- Execution recomputes the fingerprint from stored authority fields but does not recompute the currently running code revision/environment. The same authority may therefore execute after software drift while retaining its old fingerprint (`gen3_authority.py:245-267,303-316`).
- HGB accepts unbounded client `maxIter` and `learningRate`; a read-only proof produced `maxIter=1000000000000` (`gen3_authority.py:228-233,371-378`). This creates a resource-exhaustion path, made worse by missing project authorization.

Result: unique retry IDs = **pass**; stable/complete effective identity = **partial**; immutable append-only evidence = **fail**.

## 12. Candidate activation

Activation records an opaque `experimentRunId` and `runAuthorityId`, dataset version, metrics fingerprint, actor string, and timestamp (`gen3_authority.py:437-447`). It does not call D3/C4 promotion and does not independently score 2025. It does not consume “last browser result.”

It is not accepted as project-scoped authority:

- the route has authentication but no project ACL;
- raw project ID controls its filesystem directory and uncontained `active.json` pointer;
- any authenticated user who can name another project/run can activate it;
- its `resultFingerprint` hashes metrics only, not the full result authority;
- activation files/pointers remain mutable filesystem JSON.

Result: opaque review-candidate linkage = **narrow pass**; authorized immutable project activation = **fail**.

## 13. Authorization and security regression

All sports-cockpit routes are authenticated at router mount (`server/main.py:463-500`), and the new Gen-3 routes also declare `require_user` locally (`router.py:173-223`). The earlier legacy experiment-ID containment repair and user-Python default-off control pass; Python execution requires explicit `ATLAS_ENABLE_PYTHON_RUN` opt-in and is disabled by default (`server/python_execution.py:115`).

Two new critical regressions block acceptance.

### P0 — Cross-project IDOR and mutation

The routes do not call the established `authorize_modeling_scope` control (`server/core/modeling_scope.py:56-106`). `_project` only checks for nonblank text, read routes omit actor entirely, and service validation ignores actor. A read-only direct route proof using a different authenticated viewer successfully read another project's active binding and listed four runs.

Impact: any authenticated user who knows or guesses a project ID can read its binding/runs, replace its active dataset, issue/execute authority, retrieve results, and activate a candidate.

Minimal repair: call `authorize_modeling_scope(user, project_id, "view"|"edit")` on every route, pass only the canonical returned project ID, and enforce the same ACL/actor ownership at the service boundary.

### P0 — Windows path traversal through `projectId`

`project_id` is inserted directly into binding, authority, run, and activation roots. `_contained` validates a child beneath a root that already includes attacker input; several `active.json` operations are not containment-checked at all (`gen3_authority.py:78-83,203-221,268-278,404-446`). A read-only path proof with `..\..\phase7a2-outside` showed that the computed project path escapes the intended bindings root and that `_contained` accepts the resulting attacker-selected root.

Impact: authenticated traversal/absolute-path input can redirect server-account reads and writes of fixed-name JSON records outside the intended per-project store.

Minimal repair: resolve an authorized canonical project first, encode/hash it to a storage key, validate every final path relative to one fixed state root, and never use client text as the containment root.

### Other security results

| Control | Result |
|---|---|
| Authentication | **Pass** at app router mount; duplicated locally for Gen-3 routes |
| Project authorization | **Fail** |
| Binding/run opaque ID format | **Partial pass**; binding/authority/run IDs checked, project ID unsafe |
| Registered object path containment/integrity | **Fail** at consumption |
| Known sealed catalog version selectable | **No**, narrow pass |
| Complete 2025 access boundary | **Fail** through combined Gen-2 and legacy paths |
| Legacy experiment traversal fix | **Pass** in focused test |
| User-submitted Python default | **Disabled**, pass |

## 14. UI completeness classification

### A. Waterfall and season panels — **BLOCKER**

The new active-binding selector appears immediately above legacy population/target/waterfall content that describes the Gen-2 modeling/evaluation matrix and 2023/2024/2025 roles (`cockpitSteps1.tsx:402-505`). The target panel calls the legacy analysis endpoint and displays the old frozen-final framing. A reasonable scientist can select Gen-3 server-side while nearby panels continue to look like the active Gen-2 authority.

Minimal repair: drive every target, population, season, waterfall, and row-count panel from the active binding and its generation-specific registered contracts; label historical/source lineage separately and non-authoritatively.

### B. Legacy notes-based `DatasetSection` — **BLOCKER**

It remains directly beneath the server selector, hard-codes `asp.mlb.open-data.fd1`, writes local note/binding state, and presents itself as the authoritative dataset (`cockpitSteps1.tsx:206-305,402-418`). It can say Gen-2 is selected while the server binding is Gen-3, and other workflow completion logic still trusts it.

Minimal repair: remove it from the modeling-authority flow. If retained for provenance, make it read-only “source lineage,” never a selection/completion authority.

These are not cosmetic repairs. They materially affect which data a scientist reasonably believes will execute.

## 15. Focused tests and test quality

### Commands/executions

| Check | Outcome |
|---|---|
| `node --test tests/gen3ScientistFlow.test.mjs` | Windows sandbox `spawn EPERM` before test execution |
| `node tests/gen3ScientistFlow.test.mjs` | 5/5 passed |
| `node --test --test-isolation=none tests/gen3ScientistFlow.test.mjs` | 5/5 passed in focused subaudit |
| Three exact canonical/temporal/preprocessing contract tests | 3/3 passed |
| Safe Phase-7A authority cases: contracts, publisher idempotency/tamper, legacy experiment traversal, Python default | Six passed; symlink case skipped because symlink creation was unavailable. The first default-temp attempt had five passes and two setup errors; isolated workspace temp resolved one and converted the unsupported symlink case to a skip. |
| Stored HGB-root-cause and A2-reconciliation tests | 2/2 passed |
| Research-only 2021–2024 object/mask/preprocessor diagnostics | Passed; rows and fingerprints above |
| Exact A2 logistic refit | Bounded attempt interrupted cleanly at 120 seconds; no result/write |

No broad tournament, download, registry write, candidate activation, D3/C4 mutation, sealed-object read, Gen-2 execution, or 2025 score was performed.

### Quality assessment

Passing tests do not prove the claimed authority behavior:

- `gen3ScientistFlow.test.mjs` is a source-string test. It asserts endpoint strings, labels, and even a source comment; it does not render the UI or exercise HTTP behavior.
- `sports_cockpit_gen3_flow_test.py` directly calls service functions, bypasses authentication/authorization, uses fixed persistent runtime IDs, and contains a tautological initial-state assertion: `... in (None,) or True` (`:41`). Its A2 test reads the reconciliation JSON rather than producing or binding it.
- The older “project scoped” test proves directory separation using one actor, not two-user project authorization (`sports_cockpit_gen3_authority_test.py:159`).
- The “stale binding” test changes a content SHA; it does not prove that a superseded binding is rejected.
- Several suites depend on and mutate shared runtime authority JSON; tamper tests do not restore all records. This conflicts with the claimed immutable evidence boundary.
- No behavioral test covers two users/two projects, project-ID traversal, ACL view/edit distinctions, active-binding CAS, stale-tab execution, project-switch races, HTTP 403/404/error behavior, complete Model Lab path exclusivity, dataset-change invalidation, downstream result activation, object-hash verification, or full result-contract echo.
- Full Python authority/flow suites were deliberately not run because their fixtures can read the combined Gen-2 2023–2025 object, open the sealed object, execute models, and mutate persistent runtime state, contrary to this audit's constraints.

Required tests should use isolated temporary authority/registry stores and stubbed immutable objects, exercise authenticated HTTP routes with two users and two projects, and verify the complete rendered UI and run lifecycle without opening any sealed data.

## 16. Blocking findings register

| ID | Severity | Evidence | Impact | Minimal repair |
|---|---|---|---|---|
| A2-01 | **P0** | `router.py:166-223`; `modeling_scope.py:56-106`; `gen3_authority.py:282-317` | Cross-project binding/run/result disclosure and mutation by any authenticated user | Enforce canonical project ACL with view/edit checks at route and service boundaries |
| A2-02 | **P0** | `gen3_authority.py:78-83,203-221,268-278,404-446` | Windows traversal/absolute project path redirects state reads/writes | Safe encoded canonical project storage key; containment against one fixed root |
| A2-03 | **P0** | `cockpitSteps2.tsx:53-70,86-131`; `modeling.py:517-532,614-646` | Active Gen-3 binding can coexist with Gen-2 execution, 2025 scoring, and frozen payload exposure | Remove/disable legacy execution; require one binding/run-authority path for every Model Lab action |
| A2-04 | **P1** | `gen3_authority.py:87-104,188-200` | Gen-2 result falsely carries Gen-3 contract authority | Store and bind generation-specific registered contract bundles |
| A2-05 | **P1** | `gen3_authority.py:166-175` | Tampered/unregistered bytes can execute under a trusted SHA | Verify content-addressed path, physical/logical SHA, embedded metadata, schema, rows, and contracts before load |
| A2-06 | **P1** | `gen3_authority.py:189-204,236-244` | Superseded binding remains executable; last-writer-wins concurrency | Revisions, CAS, supersession/revocation, and active-pointer check at issue and execute |
| A2-07 | **P1** | `cockpitSteps1.tsx:42-56,212-305,402-418`; `workflowState.ts:59-69,229-243` | Local and server bindings can disagree while both look authoritative | One server-side lifecycle authority; legacy state becomes non-authoritative lineage only |
| A2-08 | **P1** | `Gen3CatalogSection.tsx:106-112`; `cockpitApi.ts:299-328` | Old target/config/results survive a server dataset change | Atomically invalidate/rebind downstream experiment state on binding revision change |
| A2-09 | **P1** | `Gen3AuthorityPanel.tsx:34-39,67-74`; `cockpitSteps2.tsx:422,482,522,601,657` | Authorized result cannot reach Evaluation/Calibration/Simulation/Registry | Activate one immutable run ID in shared project state and retrieve it by authority |
| A2-10 | **P1** | `gen3_authority.py:385-411`; `Gen3AuthorityPanel.tsx:83-84` | Required contract-SHA equality cannot be proven at result/UI | Echo and assert full dataset + all contract IDs/SHAs + generation + object receipt |
| A2-11 | **P1** | `gen3_authority.py:245-267,303-316` | Fingerprint can survive code/environment drift and does not represent dirty content | Hash current code/worktree/environment at execution; include full binding revision/generation/IDs |
| A2-12 | **P1** | `gen3_contracts.py:72-79`; `feature_contract.py:344-363`; `Gen3CatalogSection.tsx:75-77` | False “pregame-safe” scientific claim | Replace with honest pre-terminal PA-state contract and UI wording |
| A2-13 | **P1** | `gen3_authority.py:228-233,371-378` | Unbounded authenticated HGB resource exhaustion | Strict typed finite/range bounds, quotas, background-job cancellation |
| A2-14 | **P1** | `.runtime/.../reconciliation-7a2.json`; `sports_cockpit_gen3_flow_test.py:73-82` | A2 equality is mutable/unbound and only trusted by tests | Persist immutable run authority, preprocessor/model, predictions, full hashes, and comparator linkage |
| A2-15 | **P1** | `Gen3CatalogSection.tsx:39-50`; `Gen3AuthorityPanel.tsx:41-57` | Errors/defaults/project changes can display the wrong binding | Explicit loading/empty/error states, 404-only null, abort stale requests, dependency on project ID |
| A2-16 | **P1** | `cockpitSteps1.tsx:402-505` | Nearby Gen-2 panels materially contradict active Gen-3 authority | Re-drive all material panels from active binding before acquisition |

## Minimum acceptance repair sequence

1. Close the project ACL and `projectId` traversal defects; add two-user/two-project HTTP tests.
2. Make one server active-binding/run-authority system mandatory for all Model Lab execution. Remove the legacy 2025-scoring path from the scientist workflow.
3. Resolve dataset versions from an immutable registry, use generation-specific contracts, and verify object hashes/metadata/contracts before load.
4. Add binding revision/CAS/supersession and invalidate every downstream experiment state on a binding revision change.
5. Persist a project-scoped active experiment run and feed Evaluation, Calibration, Simulation, Champion/Challenger, and Registry from that immutable ID.
6. Include all dataset/contract identities, current code/environment, object receipt, preprocessing/model fingerprints, and predictions in append-only evidence; make retries and failed attempts auditable.
7. Correct the knowledge-time contract and remove every misleading Gen-2/local-authority panel or relabel it as source lineage.
8. Replace static/shared-runtime tests with isolated authenticated behavioral tests for the complete UI→binding→authority→object→result chain and physical sealed-data isolation.

## Final report

| Requested field | Result |
|---|---|
| Branch | `phase7-advanced-mlb-data-integration` |
| HEAD | `06c880a05d3e79ba9b0d8f81fec3fb4f80130ffb` |
| Worktree before report | Only the two pre-existing untracked reports; `.pytest_cache` was unreadable to Git and was not touched |
| Files created | `docs/PHASE_7A2_CODEX_ACCEPTANCE_REPORT.md` |
| Tests run | Source-only Node 5/5; safe contract/publisher/traversal/Python cases 6 pass/1 skip after temp isolation; stored reconciliation checks 2/2; unsafe 2025-bearing suites omitted |
| Live executions performed | Read-only route/path/parameter proofs; research-only 2021–2024 object and preprocessing diagnostics; one bounded A2 logistic attempt interrupted before result; no persistent or sealed execution |
| Data Warehouse server-backed | Partial: cards come from server, but catalog is synthesized/hard-coded and not the resolver registry |
| Data & Population server binding | Exists, but not project-authorized, generation-correct, or exclusive |
| Binding restore | Partial same-project pointer restore; error/project-switch/stale-binding behavior fails |
| Server-wins stale browser state | No |
| Model Lab binding | No; independent panel plus binding-free legacy suite |
| Result echo | No; required contract SHAs are absent and object bytes are not verified |
| Gen-2 development | 2023 |
| Gen-2 validation | 2024 |
| Gen-2 identity correct | No; Gen-3 contracts are stamped onto Gen-2 and object integrity is not verified |
| Gen-3 development | 2021–2023 |
| Gen-3 development row count | 547,835 |
| Gen-3 validation | 2024 |
| Gen-3 validation row count | 182,449 |
| Gen-3 identity correct | Partial implementation; not accepted due object verification and false knowledge-time authority |
| A2 governed LL | 1.48273326 |
| A2 server LL | 1.4827332596445002 (stored reconciliation) |
| A2 reported difference | 3.5549985e-10 |
| A2 equivalence accepted | Numeric stored/code equivalence: yes; immutable independent authority proof: no |
| 2025 opened by this audit | No |
| 2025 scored by this audit | No |
| 2025 payload exposed by this audit | No |
| 2025 opened by complete application path | Yes: combined Gen-2 bytes/catalog and full Gen-2 frame |
| 2025 scored by complete application path | Yes: legacy Model Lab |
| 2025 payload exposed by complete application path | Yes: legacy `frozen2025` API/UI fields |
| Authentication | Yes |
| Cross-project authorization | No |
| Traversal | Failed: new raw-`projectId` Windows path regression |
| Python execution default | Disabled |
| Waterfall/season panels | **BLOCKER** |
| Legacy `DatasetSection` | **BLOCKER** |
| Final verdict | **PHASE_7A2_REJECTED** |

