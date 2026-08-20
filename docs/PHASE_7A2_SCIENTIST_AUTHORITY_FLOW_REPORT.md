# Phase 7A.2 — Scientist Dataset Flow, Active-Binding Restore & Gen-3 Execution Reconciliation

**Branch:** `phase7-advanced-mlb-data-integration` · **Base HEAD:** `c5d8b4e` · No external data downloaded;
D3/C4, Gen-2, Gen-3 science, and the sealed 2025 object untouched. Preserved untracked reports
(`GPT56_SOL_INDEPENDENT_ASP_AUDIT.md`, `docs/PHASE_7_CORE_CODEX_ACCEPTANCE_REPORT.md`) left unstaged.

Narrow scope: (1) drive Data Warehouse from the server catalog, (2) drive Data & Population from the
server binding with auto-restore, (3) make Model Lab consume the active binding, (4) explain + reconcile
the 1.49223 vs 1.482733 result.

---

## Data Warehouse — before / after

- **Before:** the Data Warehouse page rendered only the registered-evidence surface; the Gen-3 catalog was
  not visible; no server-authoritative modeling-dataset catalog was surfaced.
- **After:** `DataWarehouseEvidencePage` renders `Gen3CatalogSection mode="warehouse"` at the top, fed by
  `GET /cockpit/gen3/catalog` (server authority, never hard-coded). It lists Gen-2, Gen-3 Base Research,
  and the **restricted sealed 2025** object, each with server-supplied version id, content SHA, rows,
  feature count, seasons, development/validation roles, target, knowledge-time, and governance status. The
  sealed object is shown as *restricted / not selectable* and exposes no target distribution or metrics.

## Data & Population — before / after

- **Before:** dataset selection was notes-based (browser-local) with a single dataset; no server binding.
- **After:** `PopulationBody` leads with `Gen3CatalogSection mode="selection"`. Selecting Gen-2 or Gen-3
  calls `POST /cockpit/gen3/bind` (server-authoritative `PROJECT_MODELING_DATASET_BINDING_V1`); the active
  binding **auto-restores on mount** via `GET /cockpit/gen3/binding/{project}` and **server state wins**
  over any local cache. The authoritative banner shows the bound version, content SHA, development seasons,
  validation season, and sealed season directly from the server binding. *(The legacy notes-based section
  is retained below for its registered-source population/lineage detail — see limitations.)*

## Active-binding restore & server-vs-browser precedence (Gate 4)

`useActiveBinding(projectId)` resolves the server binding on mount and re-resolves after any bind, so the
scientist never re-selects an already-governed dataset after navigation/refresh/re-login. If local
presentation state disagrees, the server binding is the authority (verified: bind Gen-2 then Gen-3 →
`active_binding` returns Gen-3; a project with none returns `null`, never a Gen-2 fallback). Live:
binding Gen-3 for a project then `GET /binding/{project}` returns `GEN3, dev [2021,2022,2023], val 2024,
content 05c91a14…`.

## Model Laboratory (Gate 9)

`Gen3AuthorityPanel` now **consumes the project's active binding on mount** (rather than starting fresh),
shows the run plan (dataset/version/content/target/dev/val/sealed/features/preprocessing/temporal), gates
Run on a verified binding, executes server-authorized, and echoes the authority in the result.

## The 1.49223 root cause + A2 scientific equivalence (Gates 7–8) — RESOLVED

**Root cause: model family, not configuration.** The Phase-7A.1 live Gen-3 run used `governed_hgb`; its
1.49223 is the **governed HGB A2** result (governed ablation HGB A2 = 1.49222912, |Δ| < 1e-4). The
1.482733 figure is the **governed logistic** A2.

**Equivalence proof (Gate 8).** A server-authorized Gen-3 execution with `governed_logistic` (same object
`05c91a14…`, dev 2021–2023 / 547,835 rows, val 2024 / 182,449 rows, C selected over the frozen grid → 0.05,
nIter 673, mean+standardize FoldPreprocessor, frozen class order, `evaluate_multiclass`) was reconciled
against the governed Phase-7A A2 logistic:

| Comparator | Val 2024 log loss |
|---|---|
| Governed Phase-7A A2 logistic | 1.48273326 |
| Server-authorized A2 logistic | 1.48273326 |
| **Difference** | **3.55e-10** (tolerance **1e-6**) → **equivalent** |

The server-authorized path is scientifically identical to the governed comparator for the same family;
the earlier apparent gap was a same-configuration different-model-family comparison, now documented.

## Full authority path (Gate 10)

Proven at server + API + behavioral-test + live levels (Phase 7A.1 suite + new flow tests):

`UI dataset version = binding dataset version = run-authority dataset version = training object =
result dataset version`, and likewise for content SHA + target/temporal/feature/preprocessing contract
SHAs. Gen-2 selection executes Gen-2 (2023 / 184,104); Gen-3 selection executes Gen-3 (2021–2023 /
547,835, val 2024 / 182,449); neither can execute the other; forged/stale authority fails closed.

## 2025 physical blinding (Gate 12)

Sealed object is non-selectable in the catalog/warehouse; the research object contains no 2025 rows; run
authority carries no sealed path; the loader never opens the sealed object; execution returns no 2025
development/validation/metric/prediction payload (`sealedSeasonsLoaded = []`, `2025 ∉ seasonsInObject`).

## Tests / build

- **New:** `tests/gen3ScientistFlow.test.mjs` (5 — Data Warehouse/Data & Population/Model-Lab wiring +
  sealed restriction); `tests/sports_cockpit_gen3_flow_test.py` (5 — catalog, active-binding restore +
  server-wins, error/fail-closed states, 1.49223 root cause, A2 equivalence ≤ 1e-6 with diff 3.55e-10).
- **Regression:** Phase-7A authority 10 + python-execution 4 (14 pass, 1 skip); frontend cockpit suites
  (6g1 10, 6g2 12, ModelLab 12, nav 9, PaModelingCockpit 16, featureUi 14) all pass; Phase-7A.1 authority
  suite unchanged (backend authority not modified this phase).
- **TSC clean · production build clean · py_compile OK · git diff --check clean.**
- **Live:** health 200, login 200, unauth binding 401, active-binding auto-restore returns Gen-3 authority.

## Remaining limitations (honest)

- The server-authoritative selection is added **additively**; the legacy notes-based `DatasetSection` is
  **retained** (not removed) beneath it for its registered-source population detail.
- The detailed **population waterfall / season panels** on Data & Population are **not yet re-driven by the
  active binding** — they still show the registered FD1 source-lineage view. The authoritative binding
  facts (dev/val/target/content) come from the server binding; the deep population panels are the follow-on.
- Full multi-tenant ACL remains a documented follow-on (project-scoping is enforced).

## Verdict

**`PHASE_7A2_READY_FOR_CODEX_GATE`**

All four mission items are delivered and proven: Data Warehouse uses the server catalog; Data & Population
creates/restores the server binding (server wins); Model Lab consumes the binding; and the 1.49223 result
is explained (governed HGB family) with the A2 logistic equivalence proven to **3.55e-10**. The authority
invariant and 2025 physical blinding hold end-to-end. The remaining items are UI-completeness follow-ons
(legacy section coexistence; deep population panels re-driven by the binding), documented for the gate.
