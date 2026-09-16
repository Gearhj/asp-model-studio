# Frozen V18 conditional champion — prospective handoff

V18 is registered in the live Model Studio database as the conditional operational MLB forecasting champion. The frozen artifact is executable and exactly reproducible. AISP activation is **not performed** by this assignment. Missing current game evidence still produces explicit skips; historical temporal validation is under review, not clean.

## Exact authority and reproducibility

- Starting branch: `codex/mlb-v19-current-state-specialists-v1`, commit `5b70c9350dc19f513b7cbfe484ddb2d009fb802d`.
- Delivery branch: `codex/mlb-v18-conditional-champion-v1`. The commit containing this document is the delivery commit.
- Registry model: `model-mlb-v18-conditional-operational-champion-v1`.
- Registry version: `mv-mlb-v18-conditional-3e8dcc1c50dcdfd2d748e5e0`.
- Fitted model: `MLB_V18_HGB_PA`, existing fold 5, SHA-256 `44ec4f457741f1aaeff42b81af1be5fd2712e494709ff1a0a8f0742b88d71c8b`.
- Champion manifest: `outputs/mlb-v18-conditional-champion-v1/champion/sha256/3e8dcc1c50dcdfd2d748e5e0de8e7595ad0b50a2c62eb9baadb4ffe9e5d640c2/champion-manifest.json`, SHA-256 `3e8dcc1c50dcdfd2d748e5e0de8e7595ad0b50a2c62eb9baadb4ffe9e5d640c2`.
- Frozen model bindings SHA: `6297787b57e7e74436036e75b40cf67339115f0cbf6333406766179c9569a235`.
- Actual live registration receipt SHA: `abe96ab97b3ea3215cc4c0656085a806123840968a1645a259adef002e2b11b8`; registered at `2026-09-11T16:31:16.445840+00:00` in `.runtime/asp-model-studio/persistence/asp_model_studio.db`.

The immutable manifest references original bytes, not newly serialized fitted objects. It binds all parent artifacts, transformations, semantic missing-value rules, fitted priors/encoder, simulation dependencies and class mapping. Dimensions: **246 raw → 273 treated → 436 encoded**. Eight classes retain combined `WALK_HBP_CI` and separate `OTHER_REACH`; probabilities are aligned to accepted class order. Calibration is identity (`RETAIN_RAW_V18`); the unselected temperature candidate is not applied.

Operational fold 5 trained on 582,342 eligible PAs / 7,728 games, nominal March 30, 2023–May 1, 2026. It is not a full-Development refit. Registered Development contains 683,662 PAs, 683,606 eligible after the unchanged 56-observation hold, through August 13, 2026. August 14–27 Final OOT remains sealed and unread. Original artifacts/results and their historical research labels remain unchanged; this separate decision changes prospective authority, not original provenance or source-use rights.

Exactly one estimator call checked 32 saved Development fixture rows: 256 probabilities and 8,736 treated cells matched exactly. Receipt SHA `56a8578309fe81d93497e8a0e0fde734d3be33913f5a06b0f3d94a145def8ef1`. The live registry's new-connection pointer, exact-context resolution, idempotent registration and fitted pipeline reload passed without additional inference. Generic promotion/clean-validation gates are unchanged; the explicit V18 pathway retains the historical limitation and rejects attempts to remove it through generic status changes.

## Bounded Development repair and limitations

Completion-authority manifest SHA: `853fc330c98e56e987905980e06225190cbe8985c4c19f4c2b035c20dba2078f`. Detailed counts and source receipts are under its `development-integrity/sha256/` folder. This new diagnostic projection covers 8,976 games / 676,499 physically isolated PAs through August 6; it does not pretend to be the original full accepted population.

Known completion-date bounds cover 545,516 PAs. Fourteen delayed games contain 1,033 PAs. `NYN202309280` has 61 PAs with unknown reverted-game finalization. Another 130,922 safe 2026 PAs lack certified completion authority. Unknowns are excluded; original event dates remain unchanged. Known completion dates permit only strictly later-date diagnostic contribution. Historical source-publication timestamps remain unknown; same-completion-day order is explicitly partial.

| Fold | Conservative future-label game quarantine | Proven later labels minimum | Potential training-feature exposure PAs | Potential validation-feature exposure PAs / games |
| --- | ---: | ---: | ---: | ---: |
| 1 | 0 | 0 | 485 | 1,502 / 24 |
| 2 | 70 | 55 | 1,987 | 6,724 / 117 |
| 3 | 0 | 0 | 8,711 | 232 / 3 |
| 4 | 0 | 0 | 8,943 | 0 / 0 |
| 5 | 0 | 0 | 8,943 | 80 / 1 |

`BOS202406260` crosses fold 2's July 6 training end: its later innings occurred August 26. All 70 PAs require conservative whole-game quarantine, but only 55 inning-3-or-later labels are asserted to be proven future labels. Proven inter-date reorderings involve 3,076 batter PA rows and 1,379 pitcher PA rows; these overlap and are **not** counts of changed numerical feature values. All five original preprocessing artifacts are hash-verified and potentially affected.

New diagnostic identity: `completion-diagnostic-6c9fde5e36682d492379efadf229345139ac1c902b8831cf74f72a9010248a80`. Candidate conservative eligibility is 460,976 rows, but certified metric eligibility is zero. No sensitivity metrics were run: complete 2026 completion evidence, finalization/publication availability and frozen rolling-feature provenance cannot be certified. Existing log-loss/Brier results remain stored numerical historical observations, not clean point-in-time estimates. Exact numerical reload remains supportable. The study did not reconstruct a clean five-fold comparison, rerun V19, or change V18.

## Installed publisher and slate evidence

Readiness report SHA: `52f69bf3e78c9657a5fbd169c520f17fb77104f335f43ae9860a033b3f80a0a7`, scheduler snapshot at September 11 **16:21:26 UTC**, latest substantive receipt 16:17:25 UTC.

- Windows task `\ASP MLB V18 Research Publisher`: enabled, S4U, pinned deployment `9bb1a947fc863596433fac569822ad95f2c71dac`, every five minutes plus startup, `StartWhenAvailable`, overlapping runs ignored. It is owned by Windows Task Scheduler and survives closing Codex; reboot execution is configured, not demonstrated by a forced reboot. No task/deployment change or manual trigger occurred.
- 197 retained current-pin scheduled receipts: 37 substantive, 160 dispatcher `NOT_DUE`; those are not 197 inference runs. Real successful free-schedule HTTP requests and read-only local database identity results are evidenced.
- September 11: 15/15 mapped games, **0 forecasts** at the stated as-of. Last substantive preflights lack all 15 home lineups and 14 away lineups; two away starters and one home starter also missing. Counts overlap and clocks vary: PIT–CHC refreshed 11:57 EDT, other retained preflights 07:07 EDT. `CHECKPOINT_NOT_DUE` is not a claim of fresh or complete inputs.
- September 12: 15 games, **0 forecasts**, all 15 missing local canonical event mappings. The report accounts for every event/team/start/checkpoint and exact skip reason.
- Current history remains through September 9; refresh is deferred until participant preflight is eligible. Publication timestamps do not make history current.
- COL–NYY and PIT–CWS September 10 forecasts remain legitimate original pregame evidence, with unchanged forecast objects and simulation references. They are not newly issued September 11 forecasts and cannot justify retrospective decisions.
- Local accounting handoff/receipt hashes verify. Six external exchange file checks returned `PermissionError [Errno 13]` even in the supported Windows context. No ACL was weakened. The importer must verify accessible source bytes in its own authorized environment; external exchange readability is not proven here.

## Claude handoff and exact action

Champion handoff:

`C:\Users\james\asp-model-studio\outputs\mlb-v18-conditional-champion-v1\aisp-handoff\sha256\a3d6ea3fdb9ddecc42e7b5ecac975d0d132931c0ca7bfc0938bdcef205f2d300\champion-handoff.json`

SHA-256: `a3d6ea3fdb9ddecc42e7b5ecac975d0d132931c0ca7bfc0938bdcef205f2d300` (15,971 bytes).

Verify from Model Studio without model execution or AISP writes:

```powershell
.\.venv\Scripts\python.exe scripts/package_mlb_v18_conditional_champion.py verify --manifest outputs/mlb-v18-conditional-champion-v1/aisp-handoff/sha256/a3d6ea3fdb9ddecc42e7b5ecac975d0d132931c0ca7bfc0938bdcef205f2d300/champion-handoff.json --sha256 a3d6ea3fdb9ddecc42e7b5ecac975d0d132931c0ca7bfc0938bdcef205f2d300
```

**Claude instruction:** Implement/import `AISP_MLB_V18_CONDITIONAL_CHAMPION_HANDOFF_V1` using the exact handoff above. Register its immutable model identity as primary prospective MLB forecasting champion with `historical_validation_under_review` visible. Do not execute V18 in AISP. Keep historical Gen1/V2.1 and all positions/settlements untouched. Implement the handoff's distinct V18 experiment, exact future boundary, atomic capital/last-decision receipt and no-fallback guards before enabling virtual decisions. Missing valid pregame V18 forecasts must skip, not use Gen1. Keep existing readiness, quotes, cutoffs, staking and 2% adjusted-edge rules. Verify accessible local/exchange files under the authorized AISP account; do not bypass an access denial.

There is **no existing champion activation command** in AISP's daily importer. The exact already-supported command for importing the two September 10 objects as historical shadow evidence, if not already imported, is below. It does not activate champion authority or authorize any retroactive positions. Run from `C:\Users\james\ai-sports-predictor\server`:

```powershell
& "C:\Users\james\ai-sports-predictor\.venv\Scripts\python.exe" -m scripts.mlb_v18_daily_slate import --handoff "C:\Users\james\asp-model-studio\outputs\mlb-v18-current-state-pipeline-v1\handoffs\sha256\8f63f8a4384288a6b90613eedea5c69c698914a922bd2ee607018a4adfcb7dc5\aisp-handoff.json" --receipt "C:\Users\james\asp-model-studio\outputs\mlb-v18-current-state-pipeline-v1\slates\2026-09-10\sha256\929c4f012e40884b955c7a3defc4272d03e52f0aecae9786f9f6cf1966ae5da8\slate-result.json"
```

September 11/12 packages are accounting-only/empty and must not be passed to that forecast importer. Future nonempty immutable scheduled packages can use the existing importer; the separate champion supplement governs prospective use without rewriting their original research provenance.

## Prospective model-era boundary

Boundary: **2026-09-12T04:00:00Z / September 12 midnight EDT**, pending Claude's timely activation. If missed, require a new immutable future-boundary supplement; never backdate. Forecasting champion designation alone does not create positions.

The current AISP persistence contract binds a single controlling engine and Gen1 forecast foreign keys, not immutable model-era segments. Therefore encode a distinct identity: **`ASP_MLB_V18_CONDITIONAL_VIRTUAL_20260912_V1`**. Do not overwrite V2.1's forecasting identity. Last Gen1 and first V18 decision IDs are future facts: handoff defines exact scoped predicates and requires Claude to record actual IDs, not invent them. Decisions before the boundary remain immutable; after the boundary, only actual pregame V18 forecasts with exact event identity can enter the new experiment.

Capture realized balance and outstanding reserves atomically at the boundary. Do not invent an opening balance or silently reset another $1,000. Preserve Gen1 open-position liabilities and their subsequent settlements in their original experiment; transfer/carry forward only explicitly reconciled capital. If safe capital-transfer/forecast linkage is not implemented, activate forecasting only and leave V18 virtual-position creation disabled. Maintain separate Gen1 and V18 performance. No real-money authority is granted.

## Focused verification and accounting

- Nine focused tests passed: three completion projections, four conditional registry/era guards, two existing registry reload/authorization regressions. Only these relevant tests ran; initial sandbox temporary-directory access failed, then the supported Windows context passed without access-control changes.
- Completion projection and frozen-binding builders reproduced identical hashes on immutable reruns. Handoff checksums verified. No historical artifact overwrite occurred.
- New estimator fits: **0**. Estimator inference: **1 call / 32 fixture rows**. New game simulations/forecasts: **0**. Registration reload does not call predict/fit.
- Final OOT payload accesses: **0**. Assignment-initiated provider requests: **0**, cost **$0**. Existing autonomous scheduler continued independently; retained receipts prove its earlier provider/DB actions, not actions initiated by this assignment.
- AISP writes: **0**. Scheduler/task/deployment mutations: **0**. V19/RF/NBA/NFL work preserved. Three preexisting tracked output-pointer changes remain unstaged.
- Incidental packaging failures were recovered without another inference: physical-vs-logical historical JSON digest corrected; one unregistered future-timestamp draft was explicitly voided and preserved in `ABORTED_DRAFTS.json`. Only the actual-clock manifest above was registered.

Disposition: **MLB_V18_CHAMPION_ACTIVATION_PARTIALLY_BLOCKED**. The exact frozen Model Studio champion and handoff are ready. Claude must implement AISP activation/linkage; per-game publication still needs legitimate lineups/starters and next-day canonical mappings, and the external exchange copy needs authorized readability verification. Historical timing limitations are disclosed conditions, not a reason to delay prospective forecasting activation.
