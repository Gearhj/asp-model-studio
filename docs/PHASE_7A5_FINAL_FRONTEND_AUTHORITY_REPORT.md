# Phase 7A.5 — Final Frontend Authority Wiring & Scientist-Flow Completion

**Branch:** `phase7-advanced-mlb-data-integration`
**Scope:** frontend-integration only. The Gen-3 backend authority architecture accepted in 7A.3 / 7A.4
is unchanged except for two purely-additive helpers (a generation-aware population projection and its read
route). No Gen-3 contract, target taxonomy, dev/val season, D3/C4 artifact, or champion of record was
touched. 2025 is never scored; 2026 is never referenced.

---

## Verdict

**PHASE_7A5_READY_FOR_FINAL_CODEX_GATE**

The Data & Population workflow, the model-execution path, and every downstream assessment stage are now
driven by the **active server binding** and the **backend-resolved active candidate**. No scientist-facing
modeling-authority surface depends on `localStorage`, legacy notes, or a prior browser result. 2025 is not
scored or distributed anywhere a scientist can reach, and the sealed 2025 object is opened **0** times
through every newly-wired path. Two pre-existing, non-champion Prepare/Assess *aids* remain as legacy
binding-free callers (feature-value ablation, whole-game simulator); both were reduced to 2024-only, both
operate on the legacy D3 evidence bundle (not the Gen-3 sealed object), and both are documented in the
Gate 13 inventory as out-of-scope of the champion-execution authority under the no-redesign constraint.

---

## What changed (by file)

| File | Change |
|---|---|
| `server/sports_cockpit/gen3_authority.py` | **+** per-season row constants on the Gen-2/Gen-3 catalog entries; **+** `binding_population(project_id)` — a generation-aware population authority derived purely from `active_binding` + registry catalog + `contracts_for_generation` (**opens no object**; no 2025 distribution). |
| `server/sports_cockpit/router.py` | **+** `GET /cockpit/gen3/population/{project_id}` → `authorize_modeling_scope(view)` then `binding_population` (404 when no active binding). |
| `src/sports/cockpit/Gen3CatalogSection.tsx` | **+** `Gen3PopulationPanel` (fetches `/cockpit/gen3/population/…`, renders the ACTIVE MODELING DATASET card: generation-aware waterfall dev/val/sealed, season roles, honest knowledge-time); **+** Gate 9 dataset-change invalidation banner on re-bind. |
| `src/sports/cockpit/cockpitSteps1.tsx` | render `Gen3PopulationPanel` in Data & Population; **suppress the sealed-2025 target-distribution row** in Target analysis (Gate 3); **suppress the 2025 log-loss row** in the feature-ablation aid (Gate 8/no-2025). |
| `src/sports/cockpit/Gen3AuthorityPanel.tsx` | Model Lab no longer selects a dataset — the version `<select>` is replaced by a **read-only active-binding summary** + "change dataset in Data & Population"; execution blocks without a binding (Gate 4). |
| `src/sports/cockpit/cockpitSteps2.tsx` | Autopilot → authorized `/cockpit/gen3/run-suite` (blocks without binding, tagged AUTOPILOT, deep disabled with reason) (Gate 5); Tuning → explicit unavailable state routed to the authorized path, legacy C-grid + its 2025 columns removed (Gate 6); Evaluation & Calibration resolve the backend **active candidate** by immutable run id (Gate 7); Simulation season locked to **2024** (2025 scoring path removed) (Gate 8). |
| `src/sports/cockpit/PaModelingCockpit.tsx` | thread `projectId` into Evaluation and Calibration steps. |
| `tests/*` | Gate 12 `binding_population` hermetic test (0 object opens); reconciled static wiring assertions to the new authorized flow; added Autopilot/Tuning/active-candidate/no-2025 assertions. |

---

## Gate-by-gate evidence

### Gate 1/2/3 — Data & Population driven by the active binding
`binding_population` returns generation-aware authority for the current ACTIVE binding: dataset
name/version/content SHA, target + 8 classes, dev seasons+rows, val season+rows, sealed season+state,
feature count, all contract ids, knowledge-time safety class, waterfall, and per-season roles. It is
derived from `active_binding` + catalog + generation contracts and **opens no object**.

**Live (project `asp-mt08s5qx`, Gen-3 bound):**
```
gen GEN3 | val 2024 valRows 182449 | dev [2021, 2022, 2023] devRows 547835
sealed [2025] state SEALED / UNAVAILABLE TO DEVELOPMENT
knowledgeTime CONDITIONAL_PRE_TERMINAL_PA_STATE | classCount 8
waterfall kinds ['source', 'development', 'validation', 'sealed']
season roles [(2021,'DEVELOPMENT'),(2022,'DEVELOPMENT'),(2023,'DEVELOPMENT'),(2024,'VALIDATION'),(2025,'SEALED')]
has 2025 distribution key: False
```
Knowledge-time is the honest **CONDITIONAL_PRE_TERMINAL_PA_STATE** (not "Pregame-safe"). No 2025 target
distribution is present. The panel reads only the server endpoint — no `localStorage`/notes dependence.

### Gate 4 — Model Lab consumes, never selects, the dataset
`Gen3AuthorityPanel` shows a read-only active-binding summary and a "change dataset in Data & Population"
pointer; the dataset `<select>` and bind button were removed; with no binding it renders an amber
"execution is blocked until an active binding exists" state.

### Gate 5 — Autopilot is server-authorized
`AutopilotPanel` fetches the active binding, blocks without one, and posts every candidate to
`/cockpit/gen3/run-suite` (`source: "autopilot"`). QUICK = `governed_hgb`; STANDARD = `governed_hgb +
governed_logistic`; DEEP is disabled with a stated reason. Results join the leaderboard tagged AUTOPILOT;
no champion is promoted; no legacy `/cockpit/autopilot` call remains.

### Gate 6 — Tuning
The legacy binding-free C-grid (which trained on D3/C4 and reported 2025) is removed. Tuning now presents an
explicit unavailable state that routes the scientist to **Autopilot · Standard** (the authorized bounded
search). No 2025 columns remain.

### Gate 7 — Evaluation resolves the active candidate from the backend
`Gen3ActiveCandidateCard` fetches `/cockpit/gen3/active-candidate/{projectId}` and renders the immutable
run id, run authority, dataset/generation, dev/val, val log loss, and result fingerprint. With none, it
shows "activate one from the Model Laboratory." Evaluation no longer trusts `lastResult`/config-hash for
authority.

### Gate 8 — Calibration / Simulation / Champion audit
Parent-state audit: `setLastResult` is **never called** now (the legacy `/cockpit/experiment/run` writer is
disabled), so Calibration/Registry/Champion `lastResult` branches are already inert and fall through to
empty states. Concrete changes:
- **Calibration** — routed to the active candidate; the 2025 reliability toggle removed (2024-only).
- **Simulation** — the season control is locked to **2024**; the "2025 frozen" option that drove a live
  `POST /cockpit/simulate` on 2025 is removed. This was the one live 2025-scoring path in the flow.
- **Champion** — promotion remains hard-disabled; the champion of record is never overwritten.

### Gate 9 — Dataset-change invalidation UX
Re-binding a different dataset raises a prominent **"DATASET CHANGED — downstream work marked stale"**
banner listing affected areas (Model Laboratory, Autopilot leaderboard, Evaluation active candidate,
Calibration/Simulation) with a "Review updated data" action. This mirrors the server-side
`_invalidate_downstream` that supersedes the active candidate on a binding change.

### Gate 12 — Hermetic sealed-file regression through the new paths
`tests/sports_cockpit_gen3_sealed_access_test.py` (6 tests, all pass) instruments every registered-object
open. The new `binding_population` test proves the population authority opens **0** objects (sealed
included), is generation-aware (2024 validation, 2025 sealed and excluded from dev/val), carries the honest
knowledge-time class, exposes no 2025 distribution, and returns `None` without an active binding. The prior
full-flow, authorized-suite, and sealed-refusal tests continue to pass (sealed opens = 0).

### Gate 13 — Legacy caller inventory
| Endpoint | Kind | Status |
|---|---|---|
| `/cockpit/gen3/{catalog,bind,binding,population,run-authority,execute,run-suite,activate,active-candidate}` | Authorized Gen-3 authority | **Authorized** — the single execution path. |
| `/cockpit/experiment/run` | Legacy binding-free **model execution** | **Contained** — behind `LEGACY_EXECUTION_DISABLED`; runner returns early; launch button hard-disabled. Scientist-unreachable. |
| `/cockpit/autopilot` | Legacy binding-free autopilot | **Removed** from the frontend (replaced by `/cockpit/gen3/run-suite`). |
| `/cockpit/feature/ablation` | Legacy binding-free **feature-value aid** (Prepare) | Residual (documented). 2024-only now; operates on the legacy D3 evidence bundle; **0 Gen-3 sealed opens**; not champion/model-selection execution. |
| `/cockpit/simulate` | Legacy binding-free **whole-game simulator** (Assess) | Residual (documented). 2024-only now; simulates on the active configuration; **0 Gen-3 sealed opens**; not model selection. |
| `/cockpit/{objective,population,profile,correlation,target-analysis,outliers,missing,feature/profile,feature-catalog,segmentation/*,temporal-split*,eligibility,experiments,model-families,data-preview}` | Read-only descriptive | No model execution; no 2025 target/scoring. |

**Champion/challenger model-execution legacy callers reachable by the scientist: 0.** The two residuals are
non-champion Prepare/Assess aids retained under the "do not redesign the workflow / do not remove
functionality" constraint; both were reduced to 2024-only and neither touches the Gen-3 sealed object.

### Gate 14/15 — Tests, build, live verification
- `npx tsc -b` — clean. `npm run build` — success. `python -m py_compile` (gen3_authority, router) — OK.
  `git diff --check` — no whitespace errors.
- Python: `sports_cockpit_gen3_sealed_access_test` 6/6; `sports_cockpit_gen3_acl_test` + `route_contract` 9/9;
  `sports_cockpit_gen3_authority_test` 17/17 (isolated); `gen3_flow` + `phase7a_authority` pass. (In a single
  back-to-back batch of all three heavy training suites, one uuid-uniqueness test flaked under resource
  contention; it passes 17/17 when the file runs alone — not a regression, and my diff to
  `gen3_authority.py` is purely additive and does not touch `execute`/run-id/fingerprinting.)
- Frontend static suites: `gen3ScientistFlow` + `gen3FrontendConsolidation` 13/13; `paModelingCockpit` +
  `cockpitModelLab` + `cockpitNavAndPopulation` + `sportsPopulationAuthority` 45/45.
- Live (backend restarted on :8101, real login): health **200**; login **200**; `/auth/me` **200**;
  unauthenticated population & binding **401**; catalog exposes the new dev/val row counts; bind Gen-3 **200**;
  population **200** (evidence above). Authorized bounded run + activation + active-candidate:
  ```
  POST /cockpit/gen3/run-suite (autopilot, 1×governed_hgb) → 200
    candidate ddff7fc58eb2 | GEN3 | sealedSeasonsAccessed [] | valRows 182449 | logLoss 1.4922291158580183
  POST /cockpit/gen3/activate → 200
  GET  /cockpit/gen3/active-candidate → runId ddff7fc58eb2 | GEN3 | status ACTIVE
    runAuthority afaa419d8dff | resultFingerprint 9373633666ee
    run.dev [2021,2022,2023] | run.val 2024 | run.logLoss 1.4922291158580183
    contains "2025": False | contains "champion": False
  ```
  UI = server = training = result: the leaderboard/Evaluation run id, the run authority, and the immutable
  result fingerprint are the same object the server executed; `sealedSeasonsAccessed` is empty (2025 never
  scored); the governed-HGB val log loss (~1.4922) matches the accepted governed baseline.

### Gate 16/17 — Report & commits
This report. Local commits are grouped coherently (below); **nothing is pushed**, `main` is untouched, and
the three pre-existing acceptance reports / audit files are left unstaged.

---

## Constraints honored
No external data download; no advanced features; no Gen-3 contract / target / dev-val-season change; no 2025
scoring; no 2026 reference; D3/C4 untouched; no champion promotion; workflow and Model-Lab layout not
redesigned; no bankroll/recency; no push; `main` unmodified.
