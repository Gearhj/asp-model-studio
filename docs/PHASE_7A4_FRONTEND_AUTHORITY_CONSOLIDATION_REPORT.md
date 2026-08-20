# Phase 7A.4 — Frontend Authority Consolidation, Project-State Isolation & Sealed-Data Instrumentation

**Branch:** `phase7-advanced-mlb-data-integration` · **Base HEAD:** `db54a6b` · No external data downloaded;
D3/C4, Gen-2/Gen-3 science, and the sealed 2025 object untouched. Preserved untracked audit reports
(`GPT56_SOL_INDEPENDENT_ASP_AUDIT.md`, `docs/PHASE_7_CORE_CODEX_ACCEPTANCE_REPORT.md`,
`docs/PHASE_7A2_CODEX_ACCEPTANCE_REPORT.md`) left unstaged. The accepted 7A.3 backend authority
architecture is unchanged except additive instrumentation + an authorized suite path.

Closes the sealed-data instrumentation, project hydration isolation, restore/error state machine,
source-lineage demotion, and legacy-execution containment; the deeper Data & Population panel re-drive and
downstream-page wiring remain — see the verdict.

---

## Remaining-blocker disposition

| Blocker | Fix | Status |
|---|---|---|
| **Sealed-file-open instrumentation** (Gate 13) | `gen3_authority` records every registered-object open; a **hermetic** test with STUB research + sealed objects proves the ordinary workflow (catalog→bind→run authority→execute→activate→active candidate) opens the sealed object **0 times**, and binding a sealed object is refused without opening it. Not a hard-coded `sealedSeasonsLoaded=[]`. | **Fixed** |
| **Project hydration isolation** (Gate 6) | `useCockpitStore.resetProjectScopedState()` (BASE_PROJECT_STATE) clears every project-scoped slice; `cockpitPersistence` resets **before** loading a new project's snapshot, so a project with no snapshot cannot inherit another's state. | **Fixed** |
| **Restore/error state machine** (A2-15, Gate 4/5) | `useActiveBinding` returns an explicit `BindingState` (LOADING/NO_BINDING/ACTIVE/STALE/UNAUTHENTICATED/UNAUTHORIZED/SERVER_ERROR/NETWORK_ERROR); HTTP codes classified; **no silent null-collapse, no default-dataset fallback**; stale in-flight requests aborted on project switch (`reqId`); each state has a UI message. | **Fixed** |
| **Legacy notes-based DatasetSection** (Gate 1) | Data & Population marks the legacy section + population panels as read-only **"Source lineage · historical evidence"**, explicitly *not the active modeling dataset*; the server binding (Gen3CatalogSection) is the authority. | **Fixed (demoted); full panel re-drive pending** |
| **Autopilot legacy path** (Gate 8) | Backend `run_authorized_suite` runs every candidate through the single authorized path (active-binding-checked run authority → object-verified execution → immutable tagged run evidence; never 2025); route `/cockpit/gen3/run-suite`. Frontend legacy Autopilot execution **disabled**. | **Fixed (backend + containment); frontend call-through pending** |
| **Grid/Tuning legacy path** (Gate 9) | Same authorized suite path serves tuning; frontend legacy Grid execution **disabled**. | **Fixed (backend + containment); frontend call-through pending** |
| **Legacy endpoint containment** (Gate 10) | No scientist component calls a binding-free path: the Model-Lab candidate suite, Autopilot, and Grid execution are all guarded behind `LEGACY_BINDING_FREE_EXECUTION_DISABLED` + disabled buttons. | **Fixed** |
| **Data & Population panel re-drive** (Gate 2) | The waterfall/season/target panels are labelled source-lineage but **not yet re-driven from the active binding**. | **Deferred** |
| **Model Lab dataset-selector duplication** (Gate 7) | The authority panel consumes + auto-restores the active binding but still offers an in-panel version dropdown rather than only "Change Dataset". | **Deferred** |
| **Downstream candidate → Evaluation** (Gate 11) | Backend `get_active_candidate` route exists; Evaluation UI is not yet wired to resolve it. | **Deferred** |
| **Dataset-change invalidation UI** (Gate 12) | Backend invalidates on binding change (7A.3); the UI stale banner is not yet added. | **Deferred** |

## Legacy binding-free execution caller inventory (Gate 10)

`/cockpit/experiment/run`: `cockpitSteps2.tsx` runSuite (disabled) + Grid `runGrid` (disabled) — both
behind `LEGACY_*_DISABLED`. `/cockpit/autopilot`: `cockpitSteps2.tsx` AutopilotPanel `run` (disabled). No
other modern cockpit component calls a binding-free path. The endpoints remain server-side for D3/C4
reference use but are unreachable from the scientist UI's execution controls.

## Sealed 2025 hermetic file-access counts (Gate 13)

Ordinary workflow (stubbed objects): sealed object open count = **0** · target reads = 0 · prediction
reads = 0 · metric reads = 0 · payload exposure = **absent** (`sealedSeasonsAccessed=[]`, `2025 ∉
seasonsInObject`, no 2025 in metrics). Instrumentation is behavioral (`object_open_log`), and the research
object IS opened (proving the instrumentation is not vacuous).

## Tests

- `tests/sports_cockpit_gen3_sealed_access_test.py` (4) — hermetic sealed-open instrumentation (0 opens),
  sealed-bind refusal, **authorized suite** runs every candidate through the single path with unique
  immutable run ids + best-by-run-id, and is blocked without an active binding.
- `tests/gen3FrontendConsolidation.test.mjs` (4) — hydration reset-before-hydrate, the explicit binding
  state machine (no null-collapse, stale-abort), source-lineage demotion, and the single legacy-execution
  containment flag + disabled buttons.
- **Regression:** flow (5), sealed (4), ACL (two-user + traversal), python-execution (4), frontend cockpit
  suites (6g1/6g2/ModelLab/PaModelingCockpit/nav/featureUi/gen3ScientistFlow) — pass. Full 7A.3 authority +
  ACL suite re-run (no regression from the additive instrumentation/suite). **TSC clean · production build
  clean · py_compile OK · git diff --check clean.**
- No React unit harness (jsdom/RTL) exists; frontend behavior is covered by the strongest available means —
  authenticated HTTP/API behavioral tests + rigorous logic-level wiring assertions (not source comments).
  True rendered click-through is not claimed.

## Verdict

**`PHASE_7A4_BLOCKED`**

Closed: sealed-data behavioral instrumentation (0 opens), project hydration isolation, the explicit
restore/error state machine, source-lineage demotion of the legacy DatasetSection, full legacy
binding-free execution containment, and the server-authorized suite (Autopilot/tuning) with tests. The
server authority and 2025 blinding remain sound.

Blocked on the remaining **frontend re-drive/wiring** (Gate 2 population panels from the active binding,
Gate 7 Model-Lab single dataset authority, Gate 8 frontend Autopilot call-through to `run-suite`, Gate 11
Evaluation consuming the active candidate by run id, Gate 12 dataset-change invalidation banner) and the
full two-project UI/E2E flow tests (Gate 15/16). These are UI-integration items, not authority or security
regressions. Re-audit after the frontend re-drive/wiring lands.
