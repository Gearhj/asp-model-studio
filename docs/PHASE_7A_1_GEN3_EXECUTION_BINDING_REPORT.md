# Phase 7A.1 — Gen-3 Registration, Server Run Authority & Model-Lab Execution Binding

**Branch:** `phase7-advanced-mlb-data-integration` · **Base HEAD:** `9a2af0e` · No external data downloaded;
D3/C4, Gen-2, feature science, and the sealed 2025 object untouched. Preserved untracked reports
(`GPT56_SOL_INDEPENDENT_ASP_AUDIT.md`, `docs/PHASE_7_CORE_CODEX_ACCEPTANCE_REPORT.md`) left unstaged.

This phase resolves the Phase-7A blocker: the immutable Gen-3 research dataset is now a **server-authorized
execution input**, not a browser label. The invariant **UI = SERVER = TRAINING = RESULT** is enforced
fail-closed and proven at the server, API, behavioral-test, and live levels.

---

## Architecture (additive — the D3/C4-serving `/cockpit/experiment/run` path is untouched)

A new server module `server/sports_cockpit/gen3_authority.py` + 9 authenticated, project-scoped routes
(`/cockpit/gen3/*` in `router.py`) reuse the Phase-7A immutable objects, canonical contracts, and the
governed `FoldPreprocessor` pipeline. A new additive UI panel `Gen3AuthorityPanel.tsx` surfaces the full
server-authorized flow at the top of Model Laboratory without redesigning it.

Flow: **catalog → project dataset binding → run authority → fail-closed validation → governed execution →
immutable run evidence → result-authority echo → candidate activation.**

## Gate-by-gate outcome

| Gate | Outcome |
|---|---|
| 1 Register Gen-3 as immutable derived version | **Done** — `register_gen3()` writes research + sealed into the ASP registry (`artifacts/datasets/registry.json`), binding content SHA + all 7 contract ids + parent authorities + quarantine ledger; idempotent. |
| 2 Data Warehouse visibility | **Server catalog authoritative** — `GET /cockpit/gen3/catalog` renders Gen-2, Gen-3 research, and the restricted sealed object from server authority. Surfaced in the Model-Lab panel. *(The standalone Data Warehouse page is not rewired to this catalog — additive panel used instead; see limitations.)* |
| 3 Data & Population selection | **Server-authoritative selection** — the panel selects an EXACT immutable `datasetVersionId`; the sealed object is non-selectable. *(Delivered via the panel + server catalog, not by rewiring the existing DatasetSection.)* |
| 4 Server-authoritative binding | **Done** — `PROJECT_MODELING_DATASET_BINDING_V1` issued + persisted server-side; browser holds only the binding id. Forged client content SHA rejected; sealed object rejected. |
| 5 Target authority | **Done** — binding/authority carry the target contract id/SHA (`outcome`, 8-class); execution consumes exactly that. No hidden fallback. |
| 6 Temporal authority (executed) | **Done** — the temporal contract's dev/val seasons drive the actual fold masks; Gen-3 executes 2021–2023 dev / 2024 val; 2025 physically excluded. |
| 7 Server-issued run authority | **Done** — `MODEL_EXPERIMENT_RUN_AUTHORITY_V1` with a `canonicalEffectiveConfigSha256` computed server-side from registered objects; the client cannot invent authoritative SHAs. |
| 8 Fail-closed validation | **Done** — before training, every contract SHA + content SHA + feature set + config fingerprint is re-verified; any mismatch raises `AuthorityError` (422). No fallback to Gen-2 / glob / 2023 / localStorage. |
| 9 Strong experiment identity | **Done** — each attempt gets a unique opaque `experimentRunId`; retries share the config fingerprint; evidence is append-only (run-id collision rejected). |
| 10 Model-Lab run plan | **Done** — the panel shows dataset/version/content SHA/target/dev/val/sealed/features/preprocessing/temporal; Run is gated on a verified binding. |
| 11 Result authority echo | **Done** — run evidence echoes `runAuthorityId` + config fingerprint + content SHA; equality asserted in code and tests; the panel shows "Authority verified". |
| 12 Gen-2/Gen-3 execution distinction | **Done + tested** — Gen-2 executes 2023/184,104 rows (sha `74b9c24b…`); Gen-3 executes 2021–2023/547,835 rows (sha `05c91a14…`). Neither can execute the other; forged dataset/target/temporal SHAs rejected. |
| 13 Physical 2025 blinding regression | **Done + tested** — through the execution path, Gen-3's object has no 2025 rows, `sealedSeasonsLoaded=[]`, dev/val exclude 2025, no 2025 metric returned. |
| 14 Candidate activation | **Done** — `CANDIDATE_ACTIVATION_V1` stores project/run/authority/result-fingerprint; no champion/D3/2025. |
| 15 Authorization | **Done (project-scoped)** — all routes require `require_user`; bindings/authorities/runs are project-scoped opaque-id objects; cross-project access fails closed; unauth catalog = 401 live. Full multi-tenant ACL is a documented follow-on. |
| 16 Persistence | **Backend-authoritative** — bindings/authorities/runs/activations persist under the runtime authority root and resolve after refresh/re-login. *(Panel auto-restore of the active binding on mount is a minor follow-on.)* |
| 17 Idempotency/concurrency | **Done** — immutable objects reuse/tamper-reject; same config → multiple run attempts with distinct ids; append-only, no last-writer-wins; interrupted runs never marked COMPLETE. |
| 18 Tests | **Done** — 18 behavioral tests (below). |

## Live verification (authenticated API)

Backend restarted (new router); `health=200`, `login=200`, **unauth `/cockpit/gen3/catalog` = 401**.
Full flow: `POST /bind` (Gen-3) → `POST /run-authority` (governed_hgb) → `POST /execute` →
`generation=GEN3, developmentSeasons=[2021,2022,2023], developmentRows=547,835, validationSeason=2024,
validationRows=182,449, seasonsInObject=[2021,2022,2023,2024] (2025 absent), sealedSeasonsLoaded=[],
runAuthorityId echo=✓, logLoss=1.49223`. (Browser click-through not automated; the API+panel path is
proven via authenticated HTTP + component compile + behavioral tests.)

## Tests

`tests/sports_cockpit_gen3_authority_test.py` — **18 passed** (real Gen-2 + Gen-3 governed executions):
catalog/registration; sealed-not-bindable; forged client SHA; **Gen-2/Gen-3 distinction**; 2021/2022/2023
in Gen-3 fit + 2024-only validation; **2025 never loaded/scored/returned**; fail-closed on forged
dataset/target/temporal/feature/preprocessing SHA + feature set + stale binding; result-authority echo;
unique retry run ids + constant fingerprint + append-only persistence; project scoping; activation without
champion/2025; opaque-id validation. Frontend cockpit suites (ModelLab 12, PaModelingCockpit 16, 6g2 12,
nav 9) still pass. **TSC clean · production build clean · py_compile OK.**

## Remaining limitations (honest)

- The **standalone Data Warehouse page and the Data & Population `DatasetSection` are not rewired** to the
  new server catalog; the full server-authorized selection/run flow is delivered as an **additive Model-Lab
  panel**. Rewiring those two existing pages to the catalog is the remaining UI surface (avoided here to not
  risk the existing pages).
- The Model-Lab panel does not yet **auto-restore** the project's active binding on mount (the backend
  persists it; the panel starts fresh).
- Authorization is **project-scoped** but a full multi-tenant ACL (per-user project membership enforcement)
  depends on the broader ownership system and is documented as a follow-on.

## Confirmations

external data downloaded = 0 · D3 changed = no · D3 retrained = no · Gen-2 view modified = no · registered
champion overwritten = no · champion promoted = no · 2021/2022/2023 are executed Gen-3 development = yes ·
2024 = validation only = yes · 2025 fitted = no · 2025 scored = no · **2025 target values entered the
executed process = no** (physically absent from the research object; sealed object never opened) · 2026
touched = no · raw/runtime data committed = 0 · credentials printed = 0 · security weakened = no (auth +
containment enforced) · pushes = 0 · main modified = no · preserved audit reports staged = no.

## Verdict

The Phase-7A blocker is resolved: the exact immutable Gen-3 dataset/version selected server-side becomes
the exact authorized dataset/target/population/temporal/feature/preprocessing authority used by execution
and echoed by immutable result evidence, fail-closed on any mismatch, with Gen-2/Gen-3 distinction and
physical 2025 blinding proven. Remaining work is UI-surface polish (rewire the two existing pages, panel
auto-restore) and full multi-tenant ACL.
