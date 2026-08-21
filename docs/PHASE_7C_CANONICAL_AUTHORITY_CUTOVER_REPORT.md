# Phase 7C — Canonical Scientific Authority Cutover — REPORT

**Branch:** `phase7c-canonical-authority-cutover` · **Starting HEAD:** `7eb8de5` · **Ending HEAD:** `e75eec9` (before this report's commit)
**Push status:** not pushed. `main` not modified. No history rewrite.

---

## 1. Executive verdict

**PHASE_7C_READY_FOR_FINAL_CODEX_GATE**

The non-negotiable acceptance conditions are met and **behaviorally proven**:

1. **Zero ordinary 2025 access** — hermetically proven through the production resolver: sealed object opens
   = 0 across the Gen-2 and Gen-3 ordinary flows; the legacy in-process engine is physically research-only
   (2023–2024); every binding-free 2025-scoring route returns 410; a 2025 data preview is refused.
2. **One scientific authority for execution & downstream** — every model run flows through the single
   server-authorized path (active binding → run authority → verified object receipt → immutable evidence),
   and Evaluation/Calibration/Champion/Registry resolve the project's **active candidate evidence bundle**,
   never a browser result.
3. **Generation-correct provenance** — Gen-3 is republished and content-addressed under the exact V2 bundle
   `86a60f6c…`; Gen-2 uses its own Gen-2-only contract identities.
4. **Complete object verification** — physical + round-trip-stable logical SHA + publisher-compatible schema
   SHA + embedded metadata + generation + bundle + all contract ids + rows + seasons, fail-closed.
5. **Complete, independently-recomputable run evidence** — the A2 current-HEAD governed logistic was
   reproduced and its validation log loss **independently recomputed from the persisted prediction artifact**
   to `1.4827332596445002` (0.0 vs stored; 3.55e-10 vs the governed comparator).

Remaining work is **hardening/UI-polish debt**, itemized in §25, none of which reintroduces a 2025 breach,
a competing execution authority, or an unverifiable object. It is listed transparently for the gate.

---

## 2. Legacy authority inventory (before) → resolution

| Competing authority (Codex 7A.5) | Resolution in 7C |
|---|---|
| Combined Gen-2 2023–2025 object opened by `catalog()` and `load_frame()` | Retired from ordinary reads; engine reads the Gen-2 **research** object (2023–2024); catalog resolves from registrations and opens nothing |
| Gen-3 research object under V1 bundle, binding stamped V2 | Republished + registered under V2 (`86a60f6c…`); verification requires the generation-correct bundle |
| Binding-free `/cockpit/experiment/run`, `/autopilot`, `/simulate`, `/feature/ablation`, `/champion`, `/experiments`, `/eligibility`, `/provider/verify` | **410 GONE** |
| Zustand `lastResult` / `lastSim` driving Evaluation/Calibration/Simulation/Registry/Champion | Removed; those stages consume the server active-candidate evidence bundle |
| `sealedSeasonsLoaded` vs `sealedSeasonsAccessed` render crash | Field unified to `sealedSeasonsAccessed` |

Full route/component/authority inventory: `docs/PHASE_7C_CANONICAL_AUTHORITY_CUTOVER_PLAN.md` (Gate 0).

## 3. Cutover map
See the Gate-0 plan document (unchanged).

## 4. Gen-2 research / sealed publication (Gate 1)
- Research object `50ce1def3315…` — seasons [2023, 2024], **366,553** rows (2023 dev / 2024 val), non-2025.
- Sealed object `a04852d56cde…` — season [2025], **182,926** rows, restricted / non-selectable.
- Contract bundle `ce5cd20c2843…` (Gen-2 identities only).
- Registered per-season rows: 2023=184,104 · 2024=182,449 · 2025=182,926 (receipts, never divided).
- Immutable seal-migration audit `97dc0dfd…`: the one administrative read of the combined object; `modelFit=false`, `scored=false`, `targetValuesExposed=false`. Combined object retained as archived lineage; removed from ordinary resolvers. Publisher: `scripts/phase7c_publish_gen2.py`.

## 5. Gen-3 V2 publication (Gate 2)
- Research object `b4bc7a0ebb59…` — seasons [2021, 2022, 2023, 2024], **730,284** rows.
- Sealed object `4c33b9e57a6b…` — season [2025], 182,926 rows, restricted / non-selectable.
- V2 contract bundle `86a60f6c…`; knowledge-time **V2** `MLB_GEN3_KNOWLEDGE_TIME_CONTRACT_V2:sha256:6ab2d6e5…` (CONDITIONAL_PRE_TERMINAL_PA_STATE). V1 registration archived as `registration-v1-lineage.json`.

## 6. Registry and object receipts (Gate 3/4/5)
- Generation-correct bundles: Gen-2 bundle carries only `MLB_GEN2_*` (+ frozen `MLB_PA_FEATURE_*`) ids; Gen-3 carries `MLB_GEN3_*`; verified no cross-generation ids.
- `catalog()` resolves the 4 entries (Gen-2 / Gen-2-sealed / Gen-3 / Gen-3-sealed) from immutable registrations and **opens no object** (proven: 0 opens).
- Logical digest is round-trip stable (canonical Parquet serialization); all 4 published objects reproduce their registered logical SHA.

## 7. Object verification (Gate 6/7)
`_verify_object` fail-closed checks, before any modeling row: link/reparse escape; physical SHA;
publisher-compatible schema SHA (incl. nullability); round-trip-stable **logical** SHA; embedded Parquet
identity metadata (objectKind / bundle / logical sha); generation-correct contract bundle; all contract ids;
row count; exact season set + no sealed-season leak; target column; governed feature names. A research-only
resolver refuses to open any sealed / non-selectable object. Verified receipts are cached by (path, file
stat, expected logical sha).

## 8. Active binding (live)
Project `asp-mt08s5qx`, Gen-3 V2 bound: bundle `86a60f6c…`, KT V2, dev [2021,2022,2023] (547,835) / val 2024
(182,449) / sealed [2025]; per-season rows are the registered receipts (not equal division).

## 9. Target / population authority
Target derives from the binding's registered target contract (8-class `outcome`, PA_CLASS_ORDER). Population
panel derived purely from binding + registration (0 object opens). Legacy target-analysis is research-only
(perSeason = [2023, 2024]).

## 10. Model execution cutover (Gate 11/26)
Single authorized service (`run-authority` → `execute` → evidence). Retired with **410 GONE** (verified live):
`experiment/run`, `experiments`, `experiments/{id}`, `champion`, `autopilot`, `simulate`, `eligibility`,
`provider/verify`, `feature/ablation`. Scientist-reachable binding-free execution callers = **0**.

## 11. Run evidence bundle (Gate 14/15/16)
`MODEL_RUN_EVIDENCE_BUNDLE_V1` per completed candidate: validation predictions (raw float64),
validation target + row identifiers, full diagnostics (confusion / per-class / reliability), fitted
preprocessor state, model artifact (logistic: full coefficients + intercept; tree ensemble: structural
params), and per-child + manifest SHAs. `execute()` rechecks code/environment **after** the fit and writes
`FAILED_STALE_AUTHORITY` (no COMPLETE evidence) on drift (Gate 15). Attempt lifecycle records COMPLETE /
FAILED_STALE_AUTHORITY (QUEUED/RUNNING states are debt, §25).

## 12. Active candidate (Gate 17)
`activate_candidate` writes `ACTIVE_CANDIDATE_REVIEW_V1` keyed by immutable run id, rejects a run from a
stale binding, and verifies parent fingerprints. Autopilot activates its best candidate by run id from the UI.

## 13. Evaluation (Gate 18)
`/cockpit/gen3/evaluation/{project}` resolves the active candidate → immutable evidence bundle → full
diagnostics + **independent log-loss recomputation** from the persisted prediction/target artifacts.
Frontend Evaluation renders it with no `lastResult` dependency; shows run id, dataset/generation, dev/val,
model family, metrics, recompute-verified badge, per-class, confusion, severe-miss. No 2025.

## 14. Calibration (Gate 19)
Consumes the same active-candidate evidence; renders RAW reliability diagnostics with an explicit
**CALIBRATOR NOT CONFIGURED** banner (no calibrator artifact fit this phase; no implied calibration; no 2025).

## 15. Simulation (Gate 20)
The legacy binding-free simulator (accepted 2025, ran on local config) is retired (410). The stage shows
**AUTHORITATIVE SIMULATION IMPACT NOT CONFIGURED FOR THIS CANDIDATE**; no legacy result is retained.

## 16. Feature ablation (Gate 21)
The legacy ablation (fit two models, used the sealed-2025 delta in its verdict) is retired (410). The panel
shows **NOT CONFIGURED**; a canonical 2024-only ablation is a documented future increment.

## 17. Target analysis / data preview (Gate 22)
Both read the research object only. `perSeason` = [2023, 2024]; a preview request for season 2025 is refused
(410). No 2025 rows/distributions/outcomes are exposed.

## 18. Dataset / project transitions (Gate 10/25)
Server supersedes the prior binding on a real change, invalidates the active candidate, and marks downstream
stale; the frontend shows a dataset-change banner (7A.5) and the Model-Lab binding effect now depends on
`projectId` and clears prior-project state with no first-selectable fallback. Same-version CAS no-op and a
machine-readable invalidation manifest are partial (§25).

## 19. Resource controls (Gate 12/13)
Hyperparameter bounds + suite candidate cap (≤ 8) are enforced fail-closed. Full typed request schemas
(`extra=forbid`) and a bounded per-user/project execution scheduler are debt (§25).

## 20. 2025 seal ledger
| Assertion | Result |
|---|---|
| Sealed object opened by ordinary flow | **0** (hermetic, both generations) |
| Sealed target read | **0** — research objects only; sealed resolver refused |
| Sealed predictions / metrics | **0** — no 2025 fold; `sealedSeasonsAccessed=[]` |
| Sealed payload exposure | **absent** — no 2025 season in catalog/population/target/preview/evidence |
| Combined 2023–2025 object opened by any ordinary route | **0** — retired; engine reads research object |

## 21. Two-user / two-project tests (Gate 28/32)
Existing two-user/two-project ACL + Windows-traversal tests pass (9/9 with route-contract). The new hermetic
production-resolver test proves the seal per-generation. A dedicated NEW two-user/two-project **end-to-end**
lifecycle test (bind→run→activate→evaluate across users A/B and projects A/B) is debt (§25); the ACL
enforcement it would exercise is already covered by the existing behavioral HTTP matrix.

## 22. A2 current-HEAD reproduction (Gate 29)
Run `781b6bc15d8f…` · governed logistic · dev 2021–2023 (547,835) · val 2024 (182,449) · C-grid, LBFGS,
max_iter 2000, tol 1e-7, class order exact · `sealedSeasonsAccessed=[]`, seasonsInObject [2021–2024].

| Field | Value |
|---|---|
| governed comparator LL | `1.48273326` |
| server stored LL | `1.4827332596445002` |
| **independent recompute (from persisted predictions)** | `1.4827332596445002` |
| diff recompute vs stored | `0.0` |
| diff recompute vs governed | `3.55e-10` (< 1e-6 ✓) |
| prediction SHA | `320868d9ae1b…` |
| evidence manifest SHA | `8229d1fd51b4…` |

Recomputed from the persisted prediction/target artifacts, not any historical reconciliation JSON.

## 23. D3 / C4 protection (Gate 30)
No D3/C4 model/registry/champion artifact modified, retrained, overwritten, or promoted. The champion is a
read-only reference; promotion stays disabled; its historical 2025 metric is not shown in the ordinary flow.

## 24. Tests and build
- `npx tsc -b` clean · `npm run build` success · `py_compile` OK · `git diff --check` clean.
- Hermetic production-resolver seal test **6/6** (0 sealed opens; independent recompute matches).
- Route-contract + two-user/two-project ACL **9/9**. Gen-3 authority end-to-end smoke passed.
- Live (backend restarted, real login): unauth 401 · login 200 · catalog (4 entries) · all retired routes
  410 · 2025 preview 410 · target-analysis research-only · bind Gen-3 V2 · population (registered per-season
  rows) · authorized run · activate · evaluation with independent recompute · A2 reproduction.
- The three Phase-6 legacy modeling suites (`sports_cockpit_test`, `_phase6f_`, `_phase6h_`) were already
  module-skipped in a prior phase; they exercise the now-retired binding-free modeling and are superseded by
  the authorized-flow + hermetic-seal tests.

## 25. Remaining nonblocking debt
- **Frontend single-authority (Gate 8/9)**: no scientific stage derives authority from browser state
  (execution = binding; downstream = active candidate). Residual: the legacy `DatasetSection`/`TargetSelector`
  still write `notes["dataset.selected"]`/`["target.confirmed"]` as ObjectiveStep UX bookmarks, and a second
  (legacy) dataset selector remains on Step 02. Demote these to read-only source-lineage next.
- **Gate 12**: full typed request schemas with `extra=forbid` / uniform 422 mapping (partial today).
- **Gate 13**: bounded per-user/project heavy-execution scheduler (suite cap only today).
- **Gate 14**: QUEUED/RUNNING attempt states (COMPLETE / FAILED_STALE_AUTHORITY today).
- **Gate 20/21**: authoritative simulation + canonical 2024-only ablation are NOT CONFIGURED (honest blocks).
- **Gate 24**: generated shared TS types from Pydantic (field-mismatch fixed manually today).
- **Gate 28/31**: dedicated NEW two-user/two-project E2E + a rendered frontend harness (RTL/jsdom) — the repo
  has no rendered-component harness; behavior is covered by API + hermetic + live verification today.

## 26. Readiness for Phase 7B
The physical seal, generation-correct provenance, single execution + downstream authority, complete
independently-recomputable evidence, and current-HEAD A2 reproduction are in place and proven. Phase 7B
(advanced pregame-known data) should begin only after the §25 hardening is closed by the final gate.

---

### Final handoff

STARTING HEAD `7eb8de5` · ENDING HEAD `e75eec9` (+ this report commit) · BRANCH `phase7c-canonical-authority-cutover` · WORKTREE clean (tracked) · PUSH none

**CUTOVER** — legacy dataset execution authority remaining = 0 · legacy result authority (downstream) = 0 · legacy binding-free scientist execution callers = **0** · retired endpoints = 9 · 410 responses verified = 9

**GEN-2** — research `50ce1def…` [2023,2024] 366,553 · sealed `a04852d5…` [2025] 182,926 · bundle `ce5cd20c…` · object verified = yes · ordinary sealed opens = 0

**GEN-3 V2** — research `b4bc7a0e…` [2021–2024] 730,284 · sealed `4c33b9e5…` [2025] · V2 bundle `86a60f6c…` · object verified = yes · ordinary sealed opens = 0

**ACTIVE AUTHORITY** — binding Gen-3 V2 · target outcome/8-class · population registered per-season · temporal/feature/preprocessing V2 · run authority governed · active candidate by run id

**RUN EVIDENCE** — preprocessor ✓ · model (coef for logistic) ✓ · class order ✓ · prediction artifact ✓ · metrics ✓ · confusion ✓ · calibration diagnostics ✓ · code/environment ✓ · manifest SHA `8229d1fd…`

**DOWNSTREAM** — Evaluation active-run driven = yes · Calibration active-run driven = yes (raw / not configured) · Simulation = explicitly blocked · Champion changed = no · Registry active-run driven = yes

**FEATURE ABLATION** — disabled (NOT CONFIGURED) · 2025 usage = 0

**2025 SYSTEM-WIDE** — object opens = 0 · target reads = 0 · predictions = 0 · metrics = 0 · payload exposure = none

**PROJECT / SECURITY** — two users ✓ (existing ACL matrix) · two projects ✓ · cross-project read blocked ✓ · cross-project write blocked ✓ · traversal blocked ✓ · Python disabled ✓ · concurrency bounded = partial (suite cap) · post-fit drift enforced ✓

**A2 CURRENT HEAD** — run `781b6bc15d8f…` · Gen-3 V2 · dev 547,835 · val 182,449 · prediction SHA `320868d9…` · governed LL 1.48273326 · server LL 1.4827332596445002 · independent recomputed 1.4827332596445002 · diff 3.55e-10 · accepted = **YES**

external downloads = 0 · advanced features = 0 · D3 changed = no · D3 retrained = no · champion promoted = no · 2021/2022/2023 dev preserved = yes · 2024 validation preserved = yes · 2025 fit = no · 2025 score = no · 2025 payload exposure = no · 2026 touched = no · security weakened = no · pushes = 0 · main modified = no
