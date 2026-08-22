# Phase 7A.5 — Final Independent Codex Authority / Scientist-Workflow Acceptance Gate

**Audit date:** 2026-08-21  
**Repository:** `C:\Users\james\asp-model-studio`  
**Branch:** `phase7-advanced-mlb-data-integration`  
**HEAD:** `7eb8de556682108d86b6ea1135a3085fe16703da`  
**Decision:** Rejected. Phase 7B must not begin from this authority/workflow state.

## Executive conclusion

Phase 7A.3–7A.5 made substantial, verifiable repairs: the new Gen-2/Gen-3 project routes are authenticated and project-authorized, project IDs are mapped to opaque contained storage keys, binding revisions supersede prior bindings, authorized manual and Autopilot runs use immutable run IDs, the new knowledge-time wording is scientifically honest, HGB inputs have useful numerical bounds, and the server invalidates an active candidate when its dataset binding changes.

Those repairs do not close the final gate. The scientist workflow still has multiple data/result authorities, ordinary scientist-reachable code still reads or scores sealed 2025, the functional Evaluation/Calibration/Simulation panels do not consume the server active candidate, and the current Gen-3 binding silently applies a V2 contract bundle to an object content-addressed under V1. The object receipt independently verifies physical bytes, rows, and seasons, but not the registered logical digest, embedded schema/contract identities, object kind, or generation. The shipped hermetic tests stub away the production catalog behavior that opens the combined Gen-2 2023–2025 object.

This is not nonblocking debt. It is a failure of the claimed single-authority and sealed-evidence invariants.

## 1. Repository state

| Check | Independent result |
|---|---|
| Branch | `phase7-advanced-mlb-data-integration` |
| HEAD | `7eb8de556682108d86b6ea1135a3085fe16703da` |
| Local `main` ref | `924db29511f93909f9d785855bfa056775443690` |
| Staged files at entry | None |
| Tracked modifications at entry | None |
| Pre-existing untracked files | `GPT56_SOL_INDEPENDENT_ASP_AUDIT.md`, `docs/PHASE_7A2_CODEX_ACCEPTANCE_REPORT.md`, `docs/PHASE_7_CORE_CODEX_ACCEPTANCE_REPORT.md` |
| Other status signal | `.pytest_cache` was unreadable; it was not touched |
| Raw/runtime data in `06c880a..HEAD` | None; the 21-file delta contains source, tests, scripts, and reports only |
| Push/commit by this audit | None |
| Application/runtime mutation by this audit | None |

Recent Phase 7A.3–7A.5 commits, oldest to newest:

- `ef2aa4c` — project ACL/path/contracts/binding/integrity
- `283c099` — single authorized Model Lab path and knowledge-time label
- `db54a6b` — authorization/path/lifecycle tests
- `dfff487` — project state/frontend consolidation
- `af657af` — authorized suite, sealed instrumentation, legacy containment
- `39a0869` — tests
- `8e2efeb` — active-binding data workflow
- `dbf5e6a` — Autopilot and downstream-candidate wiring
- `7eb8de5` — final source-oriented tests

The three preserved reports remained byte-identical during the audit:

- `GPT56_SOL_INDEPENDENT_ASP_AUDIT.md`: SHA-256 `2072FCB956DD35F12EC9FD3FDFF99DCD892AA66D83F8DC397B19C4FC886DC3A9`
- `docs/PHASE_7A2_CODEX_ACCEPTANCE_REPORT.md`: SHA-256 `4D01057823BDD5142FC3C9BE4AECA6EAF865D37AEF76EE4813210C27DBB11E86`
- `docs/PHASE_7_CORE_CODEX_ACCEPTANCE_REPORT.md`: SHA-256 `00ADBFE2A25581BA855EC9487560F63208CC2B9449EDD70AD210B11A1BF9F80D`

## 2. Tests and diagnostics

### Completed

- `git diff --check 06c880a..HEAD`: passed.
- Frontend/source suites with Node test isolation disabled: **41/41 passed**:
  - `gen3FrontendConsolidation.test.mjs`: 7
  - `gen3ScientistFlow.test.mjs`: 6
  - `cockpitModelLab.test.mjs`: 12
  - `paModelingCockpit.test.mjs`: 16
- Isolated Python ACL/traversal plus hermetic sealed suite: **9/9 passed in 11.52 s**:
  - three selected `sports_cockpit_gen3_acl_test.py` cases
  - all six `sports_cockpit_gen3_sealed_access_test.py` cases
- Focused authority/contract selection: **3/3 passed**; 12 Matplotlib deprecation warnings.
- Independent authenticated HTTP matrix using a real temporary `SharingService`:
  - owner requests allowed: **20/20**
  - cross-user/cross-project requests denied before modeling service: **20/20**
- Windows traversal matrix: eight payload families, including `..\..`, `..\`, encoded traversal, drive absolute, UNC, mixed separators, and slash absolute; writes outside the fixed temporary root: **0**.
- Hermetic published-object integrity matrix, authority-forgery matrix, code/environment-drift matrix, numeric/resource matrix, suite-concurrency probe, and Gen-2 target-access instrumentation.
- Research-only 2021–2024 A2 design/preprocessor reconstruction and stored-evidence hash verification. No 2025 row was loaded for this diagnostic.
- In-app-browser availability probe: no browser tab and no listener on the configured frontend/backend ports (`5274`, `8001`). A live app was not started because the production catalog itself opens the combined 2023–2025 Gen-2 object; the source and hermetic failures were already decisive.

### Bounded models executed

- Four tiny HGB fits against hermetic synthetic fixtures only, including one 10-iteration combined-season stub used to instrument Gen-2 target-column access.
- No real current-HEAD A2 logistic refit. The historical server run took 530.04 seconds and did not persist coefficients/predictions, so treating a new exact fit as a small acceptance probe would be misleading.
- No real 2025 object or target was opened or scored by this audit.
- No D3/C4 model, registry, champion, or governed runtime artifact was modified.

### Why passing tests do not establish acceptance

The frontend suites are predominantly source-string assertions. They pass while Evaluation and Calibration still read `lastResult`, because they check that an active-candidate card exists rather than that the functional panels consume it. The sealed suite replaces the complete production catalog with stub entries (`tests/sports_cockpit_gen3_sealed_access_test.py:59-80`), thereby omitting the production Gen-2 catalog construction that opens/hashes the combined object. The committed ACL tests primarily exercise services directly, not authenticated HTTP across every route. No committed test covers the live V1-object/V2-binding mismatch, logical/embedded-metadata tampering, full authority-field forgery, post-fit drift, or concurrent suites.

## 3. Gate-by-gate decision

| Gate | Result | Evidence and conclusion |
|---|---|---|
| One dataset authority | **FAIL** | The server binding exists, but legacy `DatasetSection`, target notes/localStorage, legacy population, and local `lastResult` remain material scientist surfaces (`cockpitSteps1.tsx:196-303,316-399`; `cockpitSteps2.tsx:452-595`). |
| Data Warehouse | **PARTIAL** | It renders the server catalog, but the catalog is synthesized rather than resolved from `ASP_REGISTRY`, always constructs Gen-2, and opens/hashes the combined Gen-2 object (`gen3_authority.py:124-186`). |
| Data & Population | **FAIL** | The active Gen-3 card reports the requested aggregate roles, but a second interactive fixed-Gen-2 “Modeling dataset” control mutates browser notes only. The page is gated by legacy `/cockpit/population`, and per-season Gen-3 development counts are fabricated by equal division (`gen3_authority.py:296-300`). |
| Target | **FAIL** | `TargetSelector` is browser-note authority and calls fixed `/cockpit/target-analysis`; its prominent season list includes 2025. Backend aggregate/per-season distributions cover the full fixed Gen-2 frame (`cockpitSteps1.tsx:316-399`; `engine.py:664-700`). |
| Model Lab | **FAIL** | The new panel requires a binding and uses run authority, but its effect has `[]` while reading `projectId`, so project switches can retain a prior binding (`Gen3AuthorityPanel.tsx:41-57`). A successful result can crash because the UI expects `sealedSeasonsLoaded` while the backend emits `sealedSeasonsAccessed` (`Gen3AuthorityPanel.tsx:19-24,144`; `gen3_authority.py:535`). |
| Autopilot | **PARTIAL PASS** | QUICK/STANDARD call `/cockpit/gen3/run-suite`; each candidate gets an authority and immutable run, selection uses 2024, Deep is disabled, and no champion is promoted (`cockpitSteps2.tsx:336-381`; `gen3_authority.py:553-576`). Candidates remain browser leaderboard entries without an activation action, `source` is client-supplied, and concurrent suites are unbounded. |
| Tuning/grid | **PASS AS UNAVAILABLE** | The legacy grid is honestly disabled and the scientist is directed to authorized Autopilot Standard (`cockpitSteps2.tsx:386-418`). The old source path is dead/hard-disabled, not an available governed tuner. |
| Active candidate | **PARTIAL BACKEND / FAIL WORKFLOW** | Activation writes `ACTIVE_CANDIDATE_REVIEW_V1` keyed by immutable run ID and rejects a run from a stale binding (`gen3_authority.py:600-632`). Autopilot candidates have no UI activation action, and the downstream card is informational only. |
| Evaluation | **FAIL** | It fetches/renders an active-candidate card, then functional diagnostics still read Zustand `lastResult`; a valid Gen-3 active candidate cannot populate them (`cockpitSteps2.tsx:420-509`). |
| Calibration | **FAIL** | It also reads `lastResult`, charts raw local results, and does not consume or explicitly block on the authoritative parent (`cockpitSteps2.tsx:514-551`). |
| Simulation | **FAIL** | It uses local `lastResult/config` and binding-free `/cockpit/simulate`, not project/binding/run/candidate identity (`cockpitSteps2.tsx:558-633`; `router.py:265-274`). Backend quick/full modes accept 2025 (`simulation.py:227-264,392-405`). |
| Dataset change invalidation | **PARTIAL** | Backend supersedes the old binding and removes/stales the active candidate (`gen3_authority.py:219-257,331-340`). Frontend rebind does not call `invalidateForDatasetChange`; sibling population state does not refresh; same-version rebind silently invalidates without a banner; local target/lab/result/simulation state survives (`Gen3CatalogSection.tsx:112-121,229-238`; `cockpitApi.ts:325-355`). |
| Project switch/hydration | **PARTIAL** | The singleton Zustand state is now reset before applying a project snapshot (`cockpitPersistence.ts:81-106`), a genuine repair. Component-local Model Lab binding/result state does not refetch/reset on `projectId`; Autopilot and candidate cards can transiently display prior-project state. |
| Two-user authorization | **PASS FOR NEW GEN-3 ROUTES** | All ten new routes require a user and call `authorize_modeling_scope`; behavioral HTTP matrix allowed 20/20 owner and denied 20/20 cross-project attempts before service execution (`router.py:178-250`). |
| Path containment | **PASS** | Canonical project IDs become opaque SHA-derived keys under a fixed resolved root (`gen3_authority.py:75-91`). Eight Windows-relevant authenticated traversal families caused zero external writes. |
| Object integrity | **FAIL** | Physical byte, row-count, and season tampering fail. Logical SHA, expected schema, embedded metadata, bundle, object kind, and generation are not independently checked; forged logical SHA/generation/schema expectation/bundle were accepted (`gen3_authority.py:190-210`). `_resolve_version` uses mutable synthesized catalog, not the registry. |
| Gen-2/Gen-3 contracts | **FAIL** | Generation-specific target/temporal/population/feature contracts improved. Gen-2 still carries `MLB_GEN3_KNOWLEDGE_TIME_CONTRACT_V2` and `MLB_GEN3_PREPROCESSING_CONTRACT_V1` (`gen3_contracts.py:145-170`). More critically, the live Gen-3 object was published under V1 bundle `f6877060…`; current binding stamps V2 bundle `86a60f6c…`. |
| Knowledge time | **SEMANTICS PASS / AUTHORITY FAIL** | V2 truthfully classifies the context features as `CONDITIONAL_PRE_TERMINAL_PA_STATE` and explicitly says they are not pregame-safe (`gen3_contracts.py:72-89`). That V2 contract is not the bundle embedded in/content-addressing the live object. |
| Hermetic sealed 2025 | **FAIL SYSTEM-WIDE** | Stub-only Gen-3 authority flow recorded zero sealed-stub opens. Production catalog/population opens the combined Gen-2 object, authorized Gen-2 execution reads its 2025 outcome column, target/data preview expose 2025, ablation scores and selects on 2025, and simulation accepts 2025. |
| A2 scientific reproduction | **NUMERIC EQUIVALENCE PASS / ACCEPTANCE FAIL** | Stored server LL is within tolerance, and design/preprocessor/hash checks pass. It is historical evidence, not a current-HEAD reproduction; the run crossed worktree drift, its coefficients/predictions were not stored, and it carries the object/contract mismatch. |
| Code/environment drift | **PARTIAL** | Pre-execution worktree/package drift is rejected (`gen3_authority.py:429-446`). Identity-computation failure degrades to `UNKNOWN`, untracked contents are not hashed, and the long fit does not recheck drift before evidence is committed. The stored A2 authority/result have different worktree SHAs. |
| Resource bounds | **PARTIAL / FAIL AVAILABILITY** | HGB nonfinite/huge/negative/depth cases rejected 6/6; nine-candidate suite rejected. Huge seed is accepted, unknown logistic hyperparameters are silently ignored, fractional integers truncate, malformed mappings can raise uncaught `AttributeError`, and simultaneous suites enter execution concurrently. |
| Residual legacy aids | **FAIL / BLOCKERS** | See the dedicated classification below. |
| Test quality | **FAIL AS ACCEPTANCE EVIDENCE** | Useful unit/service checks exist, but strongest product claims rely on source strings and a catalog-stubbed sealed fixture. Decisive regressions pass all focused tests. |
| UI/workflow blocker | **YES** | A scientist can misunderstand the active dataset/target/model/candidate and whether 2025 is available; these are material scientific-authority errors, not cosmetic UX debt. |

## 4. Highest-priority findings

### P0-01 — Sealed 2025 remains in ordinary scientist behavior

**Evidence**

- Feature-ablation UI calls `/cockpit/feature/ablation` and claims “2025 is sealed and is never scored” (`cockpitSteps1.tsx:1603-1633`). Backend runs two legacy experiments, computes `delta2025`, uses it in `VALUE_CONFIRMED`/`VALUE_MARGINAL`, and returns frozen metrics (`modeling.py:693-742`); each experiment evaluates 2025 (`modeling.py:517-532`).
- The prominent target selector maps all `perSeason` results; backend target analysis calculates the full fixed Gen-2 aggregate and each target season, including 2025 (`cockpitSteps1.tsx:316-399`; `engine.py:664-700`).
- Data Preview permits season 2025 and displays `outcome` plus target distribution (`DataPreviewPanel.tsx:28-109`; `engine.py:581-660`).
- `/cockpit/simulate` quick/full accepts 2025 and computes outcome-based metrics (`router.py:265-274`; `simulation.py:227-350,392-405`).
- These legacy routes are authenticated through the router mount (`server/main.py:500`) but have no project ACL, active binding, or run authority.

**Impact:** final-holdout evidence is observable and influences feature decisions; the claimed physical/statistical seal is false.

**Minimum repair:** remove 2025 from every ordinary object and route, publish separate research/sealed objects for Gen-2 as well as Gen-3, return `410` from legacy execution endpoints or migrate them to the authorized 2024-only path, and instrument target-column reads/predictions/metrics/payloads across the production catalog and every scientist route.

### P0-02 — The scientist workflow is not one authority

**Evidence**

- Server Gen-3 binding and population cards coexist with an interactive, fixed-Gen-2 browser-note `DatasetSection` and browser-note target confirmation (`cockpitSteps1.tsx:212-399,411-509`).
- Evaluation and Calibration still use persisted local `lastResult`; Simulation uses that result/local config and a legacy endpoint (`cockpitSteps2.tsx:452-595`).
- The server active-candidate response contains only scalar metrics and no confusion/reliability/calibration/model artifact needed by those panels (`gen3_authority.py:512-513,621-632`).
- The standalone cockpit header still describes fixed Gen-2 roles and local experiment state (`PaModelingCockpit.tsx:71-83`).

**Impact:** the dataset/result displayed as “active” can differ from the dataset/model that supplies diagnostics, calibration, or simulation.

**Minimum repair:** remove selection/confirmation authority from local notes, make target/features/preprocessing binding-derived, persist run-ID-keyed predictions/diagnostics/model/preprocessor, and require each downstream stage to resolve the current project’s active candidate or explicitly block.

### P0-03 — The governed Gen-3 object is silently rebound to a different contract

**Evidence**

- Runtime registration: research logical SHA `05c91a1471385d30933356ce0026cf715bb4c7566ce035efe71c75af6ad39124`, contract bundle `f687706080e038000e618518b063ad46a92c5b1f604a2cf2cb27309eb28a250a`, knowledge-time V1 `0a690986…afb8b1`.
- Current code: bundle `86a60f6caefc74b14f8068d684541dd8d03ed66004cf95632374e10f1fd65ffa`, knowledge-time V2 `6ab2d6e5…91d8d`.
- Publishing includes the bundle in the logical digest and embeds bundle/contract metadata (`gen3_publish.py:40-55,95-118`).
- Catalog reads `registration["contracts"]` but never uses it; `create_binding` stamps current code contracts (`gen3_authority.py:140-166,219-251`).

**Impact:** result evidence claims an authority that did not govern construction/content-addressing of its input object.

**Minimum repair:** either republish and register the exact same rows under V2, or continue binding the published V1 identities. Verify registry, embedded metadata, logical digest, schema, bundle, generation, object kind, rows, and seasons before binding and again before execution.

### P1-04 — Object and run receipts are incomplete/self-attesting

Physical tampering fails closed, which is positive. The executor’s schema digest omits nullability while the publisher includes it, so the algorithms do not even agree. Hermetic probes showed: publisher/executor schema SHA unequal; forged logical SHA accepted; forged generation accepted; forged expected schema ignored; forged contract bundle ignored. Authority validation also accepted altered contract IDs, bundle, and binding revision because it checks six SHA fields but not all identity fields (`gen3_authority.py:190-210,412-448`).

**Minimum repair:** resolve the exact immutable registry entry; recompute the publisher’s logical digest algorithm; verify every embedded and registered identity; compare the complete authority record to the current binding/registry; content-address or authenticate stored authority/evidence.

### P1-05 — Model Lab and downstream handoff have deterministic UI failures

- Successful manual execution returns `sealedSeasonsAccessed`; the UI reads `sealedSeasonsLoaded.length`, causing a result-render failure (`Gen3AuthorityPanel.tsx:19-24,144`; `gen3_authority.py:535`).
- The panel’s binding effect does not depend on `projectId`; errors collapse into a first-selectable fallback presentation (`Gen3AuthorityPanel.tsx:41-57`).
- Autopilot candidates cannot be activated from their leaderboard.
- Evaluation/Calibration/Simulation do not consume the active candidate.

**Minimum repair:** share generated API types, use the project-keyed binding state machine everywhere, reset component-local state on project/revision change, add run-ID activation for suite candidates, and add a behavioral lab→activate→refresh→evaluation→calibration/simulation test.

### P1-06 — Dataset invalidation is split between server and stale browser state

The backend supersedes and invalidates correctly. The selector does not invoke local dataset invalidation, its sibling population component does not refresh after binding change, and a same-version click creates a new revision/invalidation without a change banner. A different version leaves browser target/features/lab/result/simulation state intact.

**Minimum repair:** one project/binding-revision authority provider, server CAS/no-op for same version, and atomic frontend reset/refetch after a confirmed revision change.

### P1-07 — Heavy authorized execution is not concurrency-bounded

Per-request candidate count and HGB ranges are useful. There is no semaphore, reservation, queue, or per-project/user quota; two simultaneous suite requests entered model execution. Unknown/malformed input handling is also inconsistent (`gen3_authority.py:343-364,553-576`).

**Minimum repair:** typed schemas with `extra=forbid`, exact integer/range/seed bounds and uniform 422 mapping, plus a bounded per-project/user execution scheduler or semaphore.

## 5. Project security

| Item | Result |
|---|---|
| Two-user isolation | **PASS for new Gen-3 routes** — 20/20 owner requests allowed; 20/20 cross-user/project requests denied before service |
| Two-project server state | **PASS** — opaque per-project roots and active pointers remained distinct |
| Cross-project read | **DENIED** for new routes |
| Cross-project write/issue/execute/activate | **DENIED** for new routes |
| Traversal | **PASS** — eight Windows-relevant variants, zero writes outside fixed root |
| Legacy routes | **FAIL authority scope** — production-authenticated, but no project/binding/run identity |

## 6. Generation contracts and populations

### Gen-2

- Target/temporal/population/feature identities: generation-specific.
- Development: 2023, 184,104 rows.
- Validation: 2024, 182,449 rows.
- Frozen: 2025, 182,926 rows in the same combined object.
- Contract correctness: **FAIL** because Gen-2 bundle still carries Gen-3 knowledge-time and preprocessing IDs.
- Sealed access: **FAIL**. Authorized loading reads `outcome` for all 2023–2025 rows before masking, while evidence still reports `sealedSeasonsAccessed=[]` (`gen3_authority.py:451-474,535`).

### Gen-3

- Active label: MLB Gen-3 Base Research View / requested UI label “MLB Gen-3 Base Research.”
- Development: 2021–2023, 547,835 rows.
- Validation: 2024, 182,449 rows.
- Sealed: separate nonselectable 2025 entry.
- Target: `outcome`, eight classes.
- Feature count: 22 governed base features, transformed to 32 model columns.
- Knowledge-time wording: `CONDITIONAL_PRE_TERMINAL_PA_STATE`, scientifically correct.
- Contract correctness: **FAIL** because current V2 binding does not match the V1-published object.
- Sealed Gen-3 object access on the isolated authorized research path: zero in the stub tests. System-wide sealed acceptance: **FAIL** due production Gen-2/catalog and legacy paths.
- Population detail defect: the API reports each development season as `547835 // 3 = 182611`, rather than registered per-season counts (`gen3_authority.py:296-300`).

## 7. A2 scientific reproduction

No new exact server fit was run at current HEAD. The stored historical server evidence reports:

| Field | Value |
|---|---:|
| Governed comparator LL | `1.48273326` |
| Stored server LL | `1.4827332596445002` |
| Absolute difference | `3.5549985e-10` |
| Tolerance check | Pass (`< 1e-6`) |
| Brier | `0.7061395390730664` |
| Top-label ECE | `0.003112544507234644` |
| Top-1 | `0.45242232075812966` |
| Macro-F1 | `0.08640780054871053` |
| Logistic | `C=0.05`, `lbfgs`, `max_iter=2000`, `n_iter=673` |
| Development / validation | `547835 × 32` / `182449 × 32` |
| Preprocessor fingerprint | `49623488530b…` |

Independent checks verified the canonical config hash, metric hash, summary/run agreement, design sizes, preprocessor fingerprint, and complete 2021 prior blindness. Exact independent metric recomputation is impossible from stored evidence because coefficients, intercepts, class array, and predictions were not persisted; `modelFingerprint` covers estimator name, C, and coefficient shape, not coefficient values (`gen3_authority.py:500-518`). The stored authority and result also contain different worktree SHAs, proving the long fit crossed drift; execution checks identity only before fitting.

**A2 acceptance:** numeric equivalence passes; current-HEAD governed acceptance does not.

## 8. Residual legacy aids

| Question | Feature ablation | Whole-game simulator |
|---|---|---|
| A. Scientist reachable? | **Yes** — live Prepare control | **Yes** — live Simulation stage and authenticated API |
| B. Can alter active binding? | No | No |
| C. Can train/select a Gen-3 candidate? | Not a server Gen-3 candidate, but it trains two legacy models and its verdict influences feature selection | No server candidate; evaluates local config/`lastResult` |
| D. Can change champion authority? | Not directly | Not directly; promotion UI remains disabled |
| E. Can read/score sealed 2025? | **Yes** — scores both models and uses 2025 delta in verdict | **Yes** — backend quick/full modes accept 2025 |
| F. Can masquerade as current evidence? | Yes, as a scientist-visible “value” verdict disconnected from active binding | Yes, as the Simulation-stage result of local/stale config |
| G. Clearly labeled D3/legacy? | **No**; the UI falsely says 2025 is never scored | **No** authoritative parent/legacy D3 identity is enforced |
| Classification | **BLOCKER** | **BLOCKER** |

Neither requires deletion merely for being legacy. Both require genuine segregation: project authorization, immutable D3 parent identity, 2024-only physical inputs, no active-candidate/promotion semantics, and truthful labels/payloads.

## 9. 2025 acceptance ledger

The following describes product behavior. Separately, this audit opened/scored **zero real 2025 objects/targets**.

| Assertion | Result |
|---|---|
| Sealed object opened | **FAIL** — production catalog/population opens and hashes the combined Gen-2 2023–2025 object; authorized Gen-2 execution loads it |
| Sealed target read | **FAIL** — Gen-2 authorized loader reads all outcomes; target analysis/data preview expose 2025; ablation/simulation read it |
| Sealed predictions | **FAIL** — legacy experiment/ablation predict 2025; simulator accepts 2025 |
| Sealed metrics | **FAIL** — legacy experiment/autopilot/ablation calculate and return frozen metrics; ablation verdict uses them |
| Sealed payload exposure | **FAIL** — target distributions, preview outcomes, legacy frozen metrics/deltas are reachable |
| Stub Gen-3 sealed-object opens | 0 in the six shipped hermetic tests, but that is path-local evidence only |

## 10. Minimum repair set before Phase 7B

1. **Enforce the seal physically and at every route.** Split ordinary Gen-2 research from 2025; remove frozen rows/targets from catalog/materialization and ordinary execution; migrate or retire legacy execution/autopilot/ablation/simulation routes; eliminate 2025 from target/preview payloads.
2. **Repair Gen-3 provenance.** Republish/re-register under V2 or bind V1. Resolve an immutable registry entry and verify the publisher-compatible logical digest, embedded schema and contract metadata, object kind/generation, rows, and seasons.
3. **Establish one scientist authority.** Remove local Dataset/Target selection semantics. Make target, population, features, preprocessing, execution, result, and downstream stages derive from the same active binding and run ID.
4. **Complete active-candidate artifacts.** Persist immutable model/preprocessor and validation predictions/diagnostics; make Evaluation, Calibration, and Simulation consume the current active run or block. Add Autopilot candidate activation.
5. **Fix binding/project state transitions.** Project-key every component; refresh on binding revision; atomically invalidate local/server downstream state; make same-version binds no-op or explicit CAS revisions.
6. **Fix API/result contracts and resource controls.** Share generated types, correct the sealed-access field mismatch, use strict request schemas, and bound concurrent heavy work.
7. **Replace claim-oriented tests with behavioral gates.** Authenticated HTTP two-user/two-project lifecycle; real production resolver boundary with instrumented research/sealed objects; embedded/logical tamper cases; run-authority field forgery; post-fit drift; concurrency; and browser E2E binding→run→activate→refresh→downstream.

## 11. Required final summary

### AUTHORITY

- Data Warehouse = **PARTIAL** — server catalog shown, but synthesized/mutable and opens combined Gen-2.
- Data & Population = **FAIL** — server binding coexists with legacy Gen-2/browser authority.
- target = **FAIL** — local notes plus fixed Gen-2 endpoint; 2025 exposed.
- Model Lab = **FAIL** — authorized core exists, but project-stale state and successful-result field mismatch.
- Autopilot = **PARTIAL PASS** — authorized immutable runs; no suite-candidate activation and no concurrency bound.
- tuning = **PASS AS EXPLICITLY UNAVAILABLE**.
- active candidate = **PARTIAL BACKEND / FAIL END-TO-END**.
- Evaluation = **FAIL** — functional diagnostics use `lastResult`.

### PROJECT SECURITY

- two-user = **PASS for new Gen-3 routes**.
- two-project = **PASS server-side; PARTIAL UI isolation**.
- cross-project read = **DENIED for new Gen-3 routes**.
- cross-project write = **DENIED for new Gen-3 routes**.
- traversal = **PASS**, zero external writes across eight Windows-relevant variants.

### GEN-2

- contracts correct = **NO** — Gen-3 knowledge-time/preprocessing IDs remain in the bundle.
- development = **2023 / 184,104**.
- validation = **2024 / 182,449**.
- sealed access = **FAIL** — combined 2025 target column is physically read before masking.

### GEN-3

- contracts correct = **NO** — V2 binding over V1-published content.
- development = **2021–2023**.
- rows = **547,835**.
- validation = **2024**.
- rows = **182,449**.
- sealed access = **0 only on the isolated Gen-3 stub path; system-wide FAIL**.

### A2

- governed LL = `1.48273326`.
- server LL = `1.4827332596445002` (historical stored run, not current-HEAD refit).
- difference = `3.5549985e-10` absolute.
- accepted = **NO for this gate**; numeric tolerance alone passes.

### 2025

- object opened = **FAIL in product behavior; 0 real objects opened by this audit**.
- target read = **FAIL in product behavior; 0 real targets read by this audit**.
- predictions = **FAIL — legacy paths support them**.
- metrics = **FAIL — legacy paths calculate/use them**.
- payload exposure = **FAIL**.

### LEGACY AIDS

- feature ablation classification = **BLOCKER**.
- whole-game simulator classification = **BLOCKER**.

### REMAINING BLOCKERS

- ordinary 2025 target/prediction/metric access and selection leakage;
- competing server/browser/legacy data and result authorities;
- Gen-3 V1-object/V2-binding provenance mismatch;
- incomplete object and run-authority verification;
- disconnected active-candidate downstream flow;
- Model Lab project-staleness/result-contract failure;
- incomplete dataset-change invalidation;
- unbounded concurrent heavy suites;
- claim-oriented tests that miss each of the above.

### FINAL VERDICT

**PHASE_7A5_REJECTED**
