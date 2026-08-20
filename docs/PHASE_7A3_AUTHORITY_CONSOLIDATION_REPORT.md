# Phase 7A.3 — Authority Consolidation, Project ACL, Path Containment & Single Execution Path

**Branch:** `phase7-advanced-mlb-data-integration` · **Base HEAD:** `06c880a` · No external data downloaded;
D3/C4, Gen-2/Gen-3 science, and the sealed 2025 object untouched. Preserved untracked audit reports
(`GPT56_SOL_INDEPENDENT_ASP_AUDIT.md`, `docs/PHASE_7_CORE_CODEX_ACCEPTANCE_REPORT.md`,
`docs/PHASE_7A2_CODEX_ACCEPTANCE_REPORT.md`) left unstaged.

Responds to the Codex `PHASE_7A2_REJECTED` blocker list (A2-01 … A2-16). This phase closes the three P0
security/authority failures and the authority-critical P1s at the server; the frontend-consolidation P1s
(A2-15/16/18) and the sealed-file-access instrumentation test remain open — see the verdict.

---

## Blocker-by-blocker disposition

| ID | Sev | Finding | Fix | Status |
|---|---|---|---|---|
| **A2-01** | P0 | Cross-project IDOR: any authenticated user could read/mutate another project by supplying its id | Every `/cockpit/gen3/*` route now calls `authorize_modeling_scope(user, project_id, view/edit)` → only the resolved **canonical authorized** project id reaches the service (401/403/404); `StaleAuthorityError`→409 | **Fixed** |
| **A2-02** | P0 | Windows traversal through raw `projectId` in filesystem paths | `_project_key = sha256(canonical_project_id)[:32]` (opaque hex); `_state()` resolves strictly beneath one fixed `STATE_ROOT` and checks containment; no raw id, separators, drive letters, or `..` survive | **Fixed** |
| **A2-03** | P0 | Legacy binding-free Model-Lab execution coexisted with active Gen-3 binding, scored 2025, exposed `frozen2025` | The candidate-suite execution is **disabled** in the scientist Model Lab (banner + disabled Run); model execution flows **only** through the server-authorized Gen-3 path (active binding → run authority → authorized execution). The authorized path never touches 2025 (Gen-2 executes 2023 dev / 2024 val) | **Fixed (Model Lab); autopilot/grid in later Tuning step noted below)** |
| **A2-04** | P1 | Gen-2 bindings stamped with Gen-3 contracts | `contracts_for_generation(generation)` — Gen-2 resolves `MLB_GEN2_*` (+ frozen `MLB_PA_FEATURE_*`) contracts; Gen-3 resolves `MLB_GEN3_*`. A Gen-2 result never carries a Gen-3 contract id | **Fixed** |
| **A2-05** | P1 | Tampered/unregistered bytes could execute under a trusted SHA | `_verify_object` before load: physical SHA vs registry receipt, row count, season set, schema SHA → returns an object **receipt** echoed in the result; any mismatch fails closed | **Fixed** |
| **A2-06** | P1 | Superseded bindings stayed executable; last-writer-wins | Binding `revision`/`status` (ACTIVE/SUPERSEDED) + active pointer; create supersedes prior + CAS `expectedRevision`; issue/execute require the current ACTIVE binding revision (else 409) | **Fixed** |
| **A2-07** | P1 | Local + server bindings could both look authoritative | Server binding is the sole execution authority; frontend registration removed (build-only); legacy `DatasetSection` **still present** as non-authoritative lineage but not yet formally demoted | **Partial** |
| **A2-08/09** | P1 | Old target/config/results survived a dataset change; authorized result couldn't reach downstream | `_invalidate_downstream` marks the active candidate STALE on binding change (server-side); `ACTIVE_CANDIDATE_REVIEW_V1` + `get_active_candidate` resolves the active run by id for downstream | **Fixed (backend); UI invalidation display pending** |
| **A2-10** | P1 | Contract-SHA equality unprovable at result | Result echoes **all** contract ids+SHAs + object receipt + generation + binding revision + fingerprints; equality asserted in code + tests | **Fixed** |
| **A2-11** | P1 | Fingerprint survived code/env drift; dirty was only boolean | Execution recomputes git HEAD + **worktree content digest** + environment SHA and fails stale if they differ from the authority | **Fixed** |
| **A2-12** | P1 | False "pregame-safe" label | `MLB_GEN3_KNOWLEDGE_TIME_CONTRACT_V2` — `safetyClass = CONDITIONAL_PRE_TERMINAL_PA_STATE`; distinguishes pregame features vs in-game pre-terminal PA state vs prohibited post-PA/target; UI "Knowledge time" wording updated | **Fixed** |
| **A2-13** | P1 | Unbounded HGB parameters | `_validate_hyperparameters`: finite only; `maxIter∈[10,1000]`, `learningRate∈[0.001,1.0]`, `maxDepth∈[1,16]`; NaN/inf/absurd rejected | **Fixed** |
| **A2-14** | P1 | A2 equality was a mutable JSON only trusted by tests | Genuine server-authorized A2 logistic run through the repaired path, persisted as immutable run evidence with authority/receipt/preprocessor/model/prediction fingerprints (below) | **Fixed** |
| **A2-15** | P1 | Errors/defaults could display the wrong binding | Explicit loading/empty(404)/error differentiation and abort-on-project-switch **not yet** implemented in the panel | **Deferred** |
| **A2-16** | P1 | Nearby Gen-2 panels contradict active Gen-3 authority | Material Data & Population panels (waterfall/season) **not yet** re-driven by the active binding | **Deferred** |

## Registry & registration (Gate 6)

Registration is now an explicit **build/admin action** (`scripts/phase7a_build_gen3.py` calls
`register_gen3()`); the frontend no longer registers on mount and only READS `GET /cockpit/gen3/catalog`,
which resolves from the immutable content-addressed receipts (`registration.json` + the Gen-2 view
metadata) — no glob-invented versions, no UI side effect.

## A2 genuine equivalence evidence (Gate 20)

A real server-authorized Gen-3 A2 **governed-logistic** run through the repaired single path (active
binding → run authority → object-integrity-verified execution → immutable run evidence), persisted at
`.runtime/…/mlb-pa-gen3-v2/a2-evidence-7a3.json` — no longer the mutable `reconciliation-7a2.json`:

| Field | Value |
|---|---|
| Real server run id | `0ce1911efdae4363846565798e8b9980` |
| Object receipt (physical SHA) | `73d27ffee88e3080…` |
| Preprocessor / model / prediction fingerprint | `49623488530b…` / `aaa29440062c…` / `320868d9ae1b…` |
| Generation / dev rows / val rows | GEN3 / 547,835 / 182,449 |
| Seasons in object / sealed accessed | [2021,2022,2023,2024] / **[]** |
| Convergence | lbfgs, converged, nIter 673, C=0.05 |
| Governed A2 logistic | 1.48273326 |
| **Server-authorized A2 logistic** | **1.4827332596** |
| **Difference / tolerance / equivalent** | **3.55e-10 / 1e-6 / yes** |

## Tests

- **New:** `tests/sports_cockpit_gen3_acl_test.py` — **two real users / two real projects** (real
  persistence + SharingService): owner authorized, cross-project view/edit **403**, unknown project 404,
  blank 400; isolated cross-project state; **traversal-shaped project ids cannot escape the fixed root**
  (opaque hex key); dataset-binding change **invalidates the active candidate**. Isolated temp DB + temp
  authority root.
- **Rewritten (Gate 25 isolation):** `tests/sports_cockpit_gen3_authority_test.py` — per-test opaque
  projects (no shared runtime id, no supersession bleed); generation-distinction, 2025 blinding, forged-SHA
  fail-closed (incl. knowledge-time), superseded-binding rejection, full-receipt echo, retry identity,
  activation + downstream resolution, opaque-id validation.
- **Preserved:** `sports_cockpit_gen3_flow_test.py` (5) passes.
- **Regression:** frontend cockpit suites (6g1 10, 6g2 12, ModelLab 12, PaModelingCockpit 16, nav 9,
  gen3ScientistFlow 5) pass; **TSC clean · production build clean · py_compile OK**.

## Remaining blockers (honest)

1. **A2-15/16 (frontend authority):** the deep Data & Population panels (waterfall/season/target
   distribution) are not yet re-driven by the active binding, and the panel lacks full
   loading/empty/error/stale differentiation with project-switch aborts. The legacy notes-based
   `DatasetSection` is not yet formally demoted to read-only source-lineage.
2. **A2-18 (hydration isolation):** project-switch Zustand hydration isolation not implemented this phase.
3. **Sealed-file-access instrumentation (Gate 23):** execution proves 2025 is absent from the object,
   folds, and result (season-set + receipt checks), but a file-open counter on a hermetic stubbed sealed
   object is not yet wired.
4. **A2-03 residue:** the Model-Lab candidate suite is disabled, but the Autopilot/Grid controls in the
   later Tuning step still post to the legacy endpoint; they need the same treatment.

## Verdict

**`PHASE_7A3_BLOCKED`**

All three **P0** blockers are closed (A2-01 project ACL, A2-02 opaque path containment, A2-03 single
Model-Lab execution path with no 2025 scoring) and the **authority-critical P1s** are closed (A2-04
generation contracts, A2-05 object integrity, A2-06 binding lifecycle/CAS, A2-09 downstream invalidation,
A2-10 full receipt echo, A2-11 code/worktree/env drift, A2-12 knowledge-time V2, A2-13 resource bounds,
A2-14 genuine A2 evidence at 3.55e-10). Two-user/two-project authorization, path traversal, and
downstream invalidation are proven by isolated behavioral tests.

It is **BLOCKED** on the remaining P1 **frontend-consolidation** work — A2-15 (full loading/empty/error/
stale states + project-switch abort), A2-16 (re-drive the material Data & Population panels from the
active binding), A2-18 (project-switch hydration isolation), the formal demotion of the legacy
`DatasetSection`, the Autopilot/Grid legacy-endpoint residue in the Tuning step, and a hermetic
sealed-file-open instrumentation test (Gate 23). These are UI-authority and test-instrumentation gaps, not
new security failures; the server authority boundary is now sound. Re-audit after the frontend
consolidation lands.
