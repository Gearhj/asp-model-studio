# ASP Model Studio Phase 4 Player State and Usage Report

## Executive Result

Milestone A completed as governed research. `MLB_DYNAMIC_PLAYER_STATE_V1` selected D3 from 2024-only evidence and registered `DYNAMIC_STATE_RESEARCH_CHALLENGER`. Phase 3 remains `RESEARCH_BASELINE`. Milestone B was not executed in this checkpoint because the session usage budget was nearly exhausted; no lineup, starter-duration, or bullpen result is claimed.

## Phase 3 Baseline Authority

- Run: `sports-pa-research-run:sha256:9ee241378320fb820aab2531a6525d2d4624d42e7ff6c406e147f28c6800fd07`
- Run SHA: `dc62d2bd07df9ddd26494512c748a5859cf9667cdc901f002f6d2a86b619658e`
- Feature contract SHA: `fc3227fe1488f0cf422dc40c634a9b0b1c432828d479a68ea6ba7a0dce038d1e`
- Feature view: `mlb-pa-feature-view:sha256:74b9c24bb57dd75061a5de0f967c4a57e492eab9e016be950a036292bf8f958b`
- Graph: `mlb-pa-model-graph:sha256:c42cec805870c4eae5f935aa406714e5cecd0f46ff0dfd2ca78d57e2397de18b` (20 nodes, 28 edges)
- Status: `RESEARCH_BASELINE`, unchanged.

## Dynamic Player-State Contract

`MLB_DYNAMIC_PLAYER_STATE_V1` has semantic SHA `af4754aaf4ea4b064de8337de4249fc818d5d5f5992b55d29557738daeda5cb0`. It fixes the eight-class Phase 3 order, seven log odds relative to `OTHER_REACH`, effective sample size, entropy, days since evidence, 7/30/90-day counts, explicit missing history, row identities, checksums, dataset/bridge authorities, and source partitions. State schema SHA is `3da739c4a9c2ca53584d21488bbb82f6f1959107f6c0f48a2d43dd6b669119ba`; history schema SHA is `40103cddaed2ab365dc6bb01f79ae8bf7c9307ba47d11057a083520b61a98ed6`.

## Temporal and Same-Date Policy

Only evidence with `final_available_date < target.game_date` is eligible. Same-date games, including earlier doubleheader games, current-game evidence, and future evidence are excluded. Policy tuning is chronological and date-atomic inside 2023. Selection uses 2024 only; 2025 is frozen final evidence.

## Batter-State Construction

Prior completed PAs are exact-joined to canonical batter identity and accumulated in A preseason, B cumulative, and C recency representations. The governing D3 uses B cumulative state. Missing history remains an explicit indicator; player identity is lineage only and never a predictive category.

## Pitcher-State Construction

Prior completed PAs faced are processed under the identical class order, cutoff, shrinkage, uncertainty, and missing-history rules. The governing D3 uses B cumulative pitcher state. No player names, handedness, or manufactured attributes are used.

## Recency and Shrinkage Selection

The bounded 2023 grid selected policy `mlb-dynamic-player-state-policy:sha256:6db7c14882f25b33d63fd5726380306cc429535ee47bcac3e05cb08632b7f3c5`: cumulative/no decay (`halfLifeDays=null`) with prior ESS 300. The PA logistic grid selected `C=0.05` for D1-D4.

## Dynamic PA Candidates

- D0: immutable Phase 3 raw C4 probabilities; no refit or relabel.
- D1: context plus dynamic batter B state.
- D2: context plus dynamic pitcher B state.
- D3: context plus cumulative batter and pitcher B state.
- D4: context plus recency-weighted batter and pitcher C state.

All new candidates use fold-local preprocessing and true multinomial L2 logistic regression with `C` in `{0.05, 0.2, 1.0}`.

## 2024 Dynamic-State Results

| Candidate | Log loss | Summed Brier | Top-label ECE | Runtime seconds |
|---|---:|---:|---:|---:|
| D0 | 1.4842548490 | 0.7067859080 | 0.0117306649 | 0.000 |
| D1 | 1.4821169740 | 0.7061064750 | 0.0085213016 | 276.687 |
| D2 | 1.4903084723 | 0.7094059784 | 0.0079279036 | 302.906 |
| D3 | 1.4765879683 | 0.7038595501 | 0.0057375808 | 360.499 |
| D4 | 1.4765879683 | 0.7038595501 | 0.0057375808 | 359.370 |

D3 and D4 tied on the governing metrics; the frozen ordinal tie-break selected D3.

## 2025 Dynamic-State Results

| Candidate | Log loss | Summed Brier | Top-label ECE |
|---|---:|---:|---:|
| D0 | 1.4816765958 | 0.7063844063 | 0.0037567915 |
| D1 | 1.4796924317 | 0.7057842998 | 0.0034937580 |
| D2 | 1.4889707764 | 0.7092061571 | 0.0035867436 |
| D3 | 1.4740998598 | 0.7035281534 | 0.0028407451 |
| D4 | 1.4740998598 | 0.7035281534 | 0.0028407451 |

These results did not participate in selection.

## Calibration

The 2024 scalar-temperature experiment fitted `T=0.9821039849791475`. It was eligible on 2024 but failed the frozen 2025 non-worsening gate, so it was not retained. Registered final probabilities remain raw; raw and scaled evidence are preserved.

## Bootstrap Comparison

The deterministic bootstrap used 500 whole-`game_id` resamples (2,429 clusters in 2024 and 2,430 in 2025). Probability D3 was better than D0 was 1.0 for log loss and Brier in both folds.

- 2024 log-loss difference CI: `[-0.0083781188, -0.0069946467]`
- 2024 Brier difference CI: `[-0.0032575103, -0.0025964970]`
- 2025 log-loss difference CI: `[-0.0082291828, -0.0069508445]`
- 2025 Brier difference CI: `[-0.0031607438, -0.0025188771]`

## Dynamic-State Decision

`DYNAMIC_STATE_RESEARCH_CHALLENGER`. D3 improves raw log loss and Brier over D0 in both folds without a governing calibration defect. This does not alter Phase 3, authorize deployment, or create a simulator or bundle.

## Lineup Candidate-Pool Construction

Not executed in this checkpoint. The pending contract requires prior-date participation only, measured pool coverage, no target-game injection, and separate complete-order eligibility.

## Lineup Projection Results

No registered results.

## Lineup Decision

Not configured; no decision has been registered.

## Starter-Duration Features

Not executed. The pending component remains conditional on historical starter identity and must use prior-date workload only.

## Starter-Duration Results

No registered results.

## Starter-Duration Decision

Not configured; no decision has been registered.

## Bullpen Candidate-Pool Construction

Not executed. The pending component requires prior-date relief history, measured pool coverage, and no target-game reliever injection.

## Bullpen-Usage Results

No registered results.

## Bullpen-Usage Decision

Not configured; no decision has been registered.

## Strict and Enhanced Separation

All registered predictors are strict prior-date evidence. Actual participation and usage fields remain retrospective targets only. No enhanced same-date or actual-participant analysis was used for the decision.

## Artifact Lineage

- Registered component: `sports-phase4-component:dynamic-player-state:sha256:0f26a926ba8de5ba542ca41c324f42dcf8735ecd8173e0c9a7ed509e8d0a0433`
- Study: `sports-phase4-study:sha256:d1584bfed29842976dac911fdbbbdbf466b3b7cacaf68ffe68fc808f8d75ffa7`
- Study SHA: `59b1c93227c2b2506503881fa80cc2e49b27c574c6d57f8b6c01cd61a06748a5`
- Checkpoint: `mlb-dynamic-player-state-checkpoint:sha256:54d24d1342bf5d10a8d6b5b7da547f6d2644b82a3f3bbd25ff0b3feac76a8333`
- State artifact: `sports-phase4-artifact:dynamic_player_state:sha256:6117988df812bb35dc0fdafd7f8b78d0c0a62a8454e598e4271f2da148bf3b03`; content SHA `f11fe8fedbc4e105278f2ef59be56f5e8d32e7d4615c98b8e7cd3c2cc8bc86fe`; 621,516 rows.
- History artifact: `sports-phase4-artifact:dynamic_history_index:sha256:316355ab2ddcbab922bf9d00894228612b4b58998e0167dfda55e5b5fb1547c3`; content SHA `482baed9438a428a78c3e8b28d467269eb5f9e78d317dda92bf7c388f07f4fc0`; 347,169 aggregate rows from 913,349 source rows and 1,826,698 resolved references.
- Registered inventory: 32 logical artifact references. Artifact bodies remain outside Git and SQLite.

## Model Graph

Registered graph `sports-phase4-model-graph:sha256:14749dbd4501cbe46657140b55a0a82327bfb4172064561f74ab540e90d47dbd` extends, rather than replaces, the frozen Phase 3 graph. Participation, starter, bullpen, confirmed feeds, platoon, base-out transition, simulator, residual, bundle, and monitoring nodes remain incomplete or not configured as applicable.

## Runtime and Storage

The successful governed run completed in 45m16s. Validation reused all 329 cached dataset entries with zero misses. Runtime Parquet/model/prediction artifacts are beneath ignored repository-owned storage. SQLite contains metadata and logical references only. Two earlier attempts failed closed before fitting or registration while semantic Arrow/Parquet content hashing was corrected; the original checkpoint and artifact identities were preserved.

## Tests

- Dynamic state/training/runner/CLI/supervision: 43/43 passed.
- A-only Phase 4 registry and dataset projection: 38 passed, 1 B compatibility test intentionally deselected.
- Post-registration CLI registered-ID regression: 10/10 passed.
- Full Phase 3, frontend, build, browser, authentication, storage, and provider-disabled gates remain for the Milestone B/final checkpoint.

## Browser QA

Deferred to the final Milestone B checkpoint. No authentication was weakened and no session was injected. The application was not stopped.

## Remaining Data Gaps

No governed handedness, birth date, age, debut date, position, injury, transaction, roster, or announcement-time authority exists. Lineup and bullpen candidate pools therefore retain prospective roster-coverage limitations; platoon modeling remains not configured.

## Remaining Simulator Components

Lineup projection, starter duration, bullpen usage, confirmed-lineup feed, probable-starter feed, injury/transaction feed, platoon, base-out transition, game simulation, residual modeling, bundle export, and forward monitoring remain incomplete or not configured. No game probabilities or betting outputs were produced.

## Recommended Next Step

Resume Milestone B from the preserved source checkpoint. Finish the pending lineup population/bootstrap/calibration corrections, component-local checkpoint/resume behavior, exact dynamic-history lineage, registry schema alignment, focused tests, then run the governed participation CLI. Only after coherent B decisions should the frontend, browser QA, full acceptance gates, and Commit 2 be completed.

---

# MILESTONE B ENGINEERING READINESS

> Added 2026-08-18 by an engineering-readiness pass (no model training, no grid
> search, no calibration, no bootstrap, no methodology change). This section
> documents structural readiness only. **No Milestone B analytical results exist
> yet** — Codex owns the actual runs and Commit 2. See
> `docs/PHASE_4_MILESTONE_B_RUNBOOK.md` for the exact run sequence.

## Components structurally ready

| Component | Contract | Backend | Frontend surface | Status |
|-----------|----------|---------|------------------|--------|
| Lineup projection | `MLB_LINEUP_PROJECTION_V1` | present | Participation & Usage | **READY_TO_RUN** |
| Starter duration | `MLB_STARTER_DURATION_V1` | present | Participation & Usage | **READY_TO_RUN** |
| Bullpen usage | `MLB_BULLPEN_USAGE_V1` | present | Participation & Usage | **READY_TO_RUN** |
| Catcher influence readiness | `MLB_CATCHER_INFLUENCE_READINESS_V1` | present + **EXECUTED** (audit, not a model) | Participation & Usage (real results) | **CATCHER_INFLUENCE_PARTIALLY_READY** |

The lineup / starter / bullpen components are implemented end-to-end
(`server/sports_phase4/participation_{features,metrics,training,runner}.py`,
`scripts/run_mlb_participation_usage.py`) and are exercised by the passing
Milestone B backend tests.

**Catcher influence readiness is built as a data-availability AUDIT and has now been
EXECUTED against the real governed FD1 dataset** (2026-08-18) — not a predictive
model. Real coverage numbers are below; the predictive catcher graph nodes remain
`NOT_CONFIGURED`.

### Real audit results (executed against registered FD1 authority)

- **Terminal status: `CATCHER_INFLUENCE_PARTIALLY_READY`.** Runtime **26 s**
  (332,159 fielding rows, 913,349 PAs across 2021–2025), audit
  `runId=catcher-readiness-8f0f7a7ffef68098`, content SHA
  `d9db5fed12e1cc42aabfa5c6a5011e9a8f4cd09439b318b998ff4838d1cb74d8`.
- **Starting-catcher reconstruction: essentially complete** (via
  `player_game_fielding.fielding_position == 2`): 2023 = 100.0 %, 2024 = 99.98 %,
  2025 = 100.0 % of team-games have a determinable starting catcher (0 missing).
- **PA-level catcher assignment: ~87 %** (2023 86.1 %, 2024 87.6 %, 2025 87.6 %).
  The shortfall is **structural, not a bug:** ~12 % of team-games use more than one
  catcher and there is **no governed substitution-event / PA-index family**, so those
  multi-catcher-game PAs are honestly reported **AMBIGUOUS** rather than forward-filled.
  Unique catchers ≈ 95–104 per season.
- **Pitcher-catcher battery history is dense** (deterministic-catcher PAs only): 2024
  median 102 prior battery PAs, p90 588, max 2311; **65.5 % of PAs have ≥50** and
  **50.6 % have ≥100** prior battery PAs. Battery fallback readiness: ~64 % of PAs sit
  at LEVEL_3 (battery-pooled) or LEVEL_4 (battery-specific).
- **Catcher × batter history is sparse** (as expected): 2024 median 9 prior PAs,
  only ~21.8 % with ≥25, ~20.9 % with 0 prior. A future study should therefore prefer
  a catcher main effect + batter-archetype interaction + hierarchical partial pooling
  over per-pair estimation.
- **Free feature inventory:** 11 DERIVABLE + 9 PARTIALLY_AVAILABLE (catcher starts,
  workload, rest, battery/catcher-batter prior counts derivable; passed balls /
  putouts / assists / errors / double plays present as **postgame** descriptive
  evidence via `stat_d_*`, innings from `stat_d_ifouts`). **15 premium/tracking gaps**
  (framing, pitch location/target, pop time, arm, exchange, **pitch-caller identity**,
  ABS challenge) remain unavailable and are never fabricated.
- **Identity linkage:** exact within-package Retrosheet IDs
  (`player_game_fielding.player_id` ↔ `plate_appearance.pitcher_id/batter_id`); no
  names, no fuzzy matching. (The raw `canonical_identity_resolved` flag is `False` by
  design — the governed bridge canonicalizes cross-family identities at join time.)
- **Why PARTIALLY_READY (not READY):** the READY gate needs ≥90 % PA catcher-assignment
  coverage; the honest measured value is ~87 %. The status was **not** lowered to
  BLOCKED nor raised to READY — it reflects the real evidence. The frontend renders
  these real numbers via `/api/sports/datasets/active → phase4.catcherReadiness`.

### MLB_CATCHER_INFLUENCE_READINESS_V1 (readiness audit)

- **What it is:** a governed audit that measures, from existing free evidence only,
  how reliably catcher identity can be reconstructed (starting catcher per team-game;
  catcher-at-PA with substitution/ambiguity handling — never forward-filled) and how
  sparse pitcher-catcher battery and catcher×batter histories are (prior-only sample
  bands `0 / 1-9 / 10-24 / 25-49 / 50-99 / 100-249 / 250+`, with strict no-target-self
  inclusion). It also inventories free-derivable catcher features vs premium/tracking
  gaps (framing, pitch location/target, pop time, arm, exchange, ABS challenge, and
  the pitch **caller identity** that free data cannot supply).
- **What it is NOT:** no catcher effect estimation, no framing/pitch-call claim, no
  score/ranking, no betting output, no model performance metric.
- **Terminal statuses:** `CATCHER_INFLUENCE_READY_FOR_RESEARCH_DESIGN` /
  `CATCHER_INFLUENCE_PARTIALLY_READY` / `CATCHER_INFLUENCE_DATA_AUDIT_BLOCKED`
  (decided from real coverage at run time; READY authorizes a future study *design*,
  never a proven predictive effect).
- **Implementation:** `server/sports_phase4/catcher_readiness.py` (pure,
  schema-agnostic algorithms) + `tests/sports_phase4_catcher_readiness_test.py`
  (23 hermetic tests) + `docs/contracts/MLB_CATCHER_INFLUENCE_READINESS_V1.md`.
  The Parquet→normalized-structure adapter (which the audit itself reports
  availability for) is wired by the operator at run time.
- **Future study (documentation only):** `MLB_CATCHER_AND_BATTERY_EFFECT_V1`
  ablation `M0→M5` with hierarchical partial pooling (shrink sparse batteries toward
  pitcher → catcher → archetype → league). No coefficients estimated.
- **Independence:** the catcher readiness audit is a **separate** step and is **not**
  a prerequisite for the already-ready lineup/starter/bullpen analytical run.

## Temporal / leakage contract (verified structurally)

The runner records and enforces a strict prior-date policy, encoded in the
artifact bindings (`assemble_participation_run` → `temporalPolicy`):
`sourceFinalAvailableDate = STRICTLY_BEFORE_TARGET_GAME_DATE`,
`sameDateEvidenceExcluded = true`, `doubleheaderSameDateEvidenceExcluded = true`,
`innerTuningSeason = 2023`, `selectionSeason = 2024`, `finalEvaluationSeason = 2025`.
Feature construction excludes the target date via `bisect_left` on the finalized
game ordinal and a `_strict_row_guard` requiring
`strict_same_game_pregame_eligible == false` and
`strict_prior_eligible_after_game_final == true`. IDs are not model features;
candidate coverage misses remain measurable. 2025 cannot influence tuning or
selection (`validate_component_shape` requires `selected.selectionSeason == 2024`
and folds `== [2024, 2025]`).

## Checkpoint / resume

- **Content-addressed** feature checkpoint and final checkpoint, written with
  atomic temp-then-replace; a differing content-addressed checkpoint is rejected
  (no silent reuse under changed inputs).
- **Supervised** worker with an 8h overall limit, a 90s silence watchdog, an 8GiB
  RSS limit, and per-component stage limits (90–120 min). A **30s heartbeat**
  (`WorkerEventEmitter(heartbeat_seconds=30.0)`) prevents another silent run.
- **Not implemented:** fine-grained mid-training resume that skips already-fitted
  components after an interruption — a rerun re-fits. This is acceptable because the
  estimated full run is short (see below) and the watchdog bounds it; adding it
  would require changing the modeling path and is deliberately out of scope here.

## Runtime estimate

`--estimate-only` reports **900–2100 s (≈15–35 min)** for the full three-component
run at 500 bootstrap resamples with optional HGB disabled, ≤200 MB of runtime
artifacts. (Milestone A's D3 run was 45m16s for reference.)

## Registry / graph readiness

- Migration `0034_sports_phase4_research_registry.sql` is the single head; the
  Phase 4 study registry accepts the combined study (`build_phase4_study_payload`
  requires all three components) with per-component decision, candidates,
  hyperparameters, temporal policy, coverage, 2024/2025 folds, calibration decision,
  bootstrap evidence, limitations, artifact logical URIs, and terminal status.
- Allowed per-component terminal states:
  `{LINEUP|STARTER_DURATION|BULLPEN_USAGE}_{RESEARCH_COMPONENT|RESEARCH_BASELINE|REJECTED|BLOCKED}`.
- The registered study extends (does not replace) the frozen Phase 3 graph; future
  nodes (catcher state, battery interaction, pitch selection, framing, blocking,
  throwing/running control, ABS challenge, confirmed-lineup/probable-starter/injury
  feeds, platoon, base-out transition, simulator, residual, bundle, monitoring)
  remain `NOT_CONFIGURED`.

## Frontend / backend contract

`server/sports_phase4/participation_runner.validate_component_shape` enforces exactly
the fields `src/sports/sportsEvidenceApi.ts::normalizePhase4Component` consumes, and
`src/sports/Phase4Surfaces.tsx` renders every value existence-gated with honest
`NOT_RUN` / `NOT_CONFIGURED` empty states. Both ends are covered by
`tests/sportsProductConversion.test.mjs` (15/15). No fabricated metrics, stale
Phase 3 values, or empty-response-as-success paths were found.

## Verification performed (this pass)

- Milestone B participation pytest (contract/features/CLI/training-runner): **22/22**.
- Sports frontend contract (`sportsProductConversion.test.mjs`): **15/15**.
- `--estimate-only` CLI: clean (no training, no provider).
- `tsc --noEmit`: **exit 0**. Migration head: single (`0034`).
- No engineering defect requiring repair was found; the checkpoint is green. No code
  was changed by this pass.

## Remaining analytical execution (Codex owns)

Run the governed participation CLI to produce the three component decisions, register
the combined study, then complete frontend/browser verification and Commit 2 — as
laid out step-by-step in `docs/PHASE_4_MILESTONE_B_RUNBOOK.md`.

---

# E1 FREE PITCH-SEQUENCE PROCESS FEATURE READINESS

> Added 2026-08-18. **No model was trained or evaluated**; this is a leakage-safe
> feature *materialization* readiness. No predictive improvement is claimed. It is a
> separate feature-development step and is **not** a blocker for the Milestone B
> participation run. Contract: `docs/contracts/MLB_PITCH_SEQUENCE_PROCESS_FEATURES_V1.md`.

## Executed result (real FD1 data)

- **Terminal status: `PITCH_SEQUENCE_FEATURES_READY`.** Runtime **26 s**
  (943,682 pitch-sequence rows read → **568,935** target-PA feature rows for
  2023–2025). Materialization `pitch-sequence-features-ae7eadd6ade83f28`; feature
  Parquet content SHA `7017c3c88ca96d77…` (~42.6 MB, ignored runtime storage — not
  committed). CLI: `scripts/run_mlb_pitch_sequence_features.py`.
- **Parser (`MLB_PITCH_SEQUENCE_PARSER_V1`): 100.00 % of symbols classified, 0
  unknown**, every season 2021–2025; only ~1,203 empty-sequence PAs (~0.13 %). The
  documented Retrosheet category table (B/C/S/F/X/H + automatic/bunt/foul-tip/pitchout
  variants + non-pitch markers) covers every symbol present; nothing is silently
  dropped. Velocity / pitch type / location / movement / target / catcher-call are
  **absent from the free data and never inferred**.
- **50 features** (25 batter + 25 pitcher): per entity, **cumulative** (all prior
  dates) and **trailing-30-day** windows of ball/called-strike/swinging-strike/foul/
  in-play rates, pitches-per-PA, two-strike-PA rate, first-pitch-strike rate, plus
  `prior_pas` / `prior_pitches` sample sizes and `missing_history` / `low_sample`
  indicators. Trailing-60/90-day deferred (runtime), reconstructable from the same
  day-level cumulative table.
- **Strict temporal safety:** a target PA's own pitches and all same-date PAs
  (doubleheaders included) are excluded; prior evidence is strictly earlier than the
  target date (`merge_asof(..., allow_exact_matches=False)`). Validated by hermetic
  tests (`tests/sports_phase4_pitch_sequence_run_test.py`).
- **Coverage:** both batter and pitcher prior history present for **98.6–98.8 %** of
  target PAs; batter missing-history 325–368/season (mostly rookies' first PAs),
  pitcher 1,852–2,282. Early-season (March) batter missing rate ~1 % → ~0.1 % by
  season end. Feature means match MLB norms (batter ball rate ≈0.361, whiff ≈0.122,
  first-pitch-strike ≈0.611), an independent correctness check.

## STRIKEOUT-relevant readiness (D3's known weakness)

Does E1 plausibly contain process information relevant to the observed STRIKEOUT
failure? **Yes, by availability** (not by any model result): batter & pitcher
swinging-strike tendency **AVAILABLE**, called-strike tendency **AVAILABLE**,
two-strike frequency **AVAILABLE**, first-pitch-strike tendency **AVAILABLE**,
sequence-length/discipline **AVAILABLE**; two-strike swing/miss tendency **PARTIAL**.

## WALK / HBP-relevant readiness

Batter & pitcher ball-rate tendency **AVAILABLE**, pitches-per-PA **AVAILABLE**,
called-strike tendency **AVAILABLE**; full-count frequency and
intentional-ball/pitchout distinction **PARTIAL**.

## Rare-outcome limitation (do not oversell E1)

Process features alone likely will **not** resolve HOME_RUN / DOUBLE / TRIPLE /
OTHER_REACH — the free data lack exit velocity, launch angle, barrel/hard-hit, pitch
location, velocity, and movement. E1 measures plate-discipline *process*, not contact
quality.

## Integration & next step (E2)

Registered as a content-addressed feature-family artifact (no model ID, no metrics),
surfaced to the frontend via `phase4.pitchSequenceFeatures` (Player & Team State →
E1 section); graph adds a READY Pitch-Sequence Process Features node while E2
interactions, handedness/platoon (E6), archetypes, and all algorithm challengers stay
`NOT_CONFIGURED`. **E2 (documentation only)** will combine batter process state ×
pitcher process state (e.g. batter swinging-strike rate × pitcher swinging-strike
rate; batter ball rate × pitcher ball rate; batter two-strike vulnerability × pitcher
two-strike dominance) — materialized in a later task, then tested in a separate
governed model experiment.

---

# E2 BATTER × PITCHER PROCESS INTERACTION READINESS

> Added 2026-08-18. **No model trained or evaluated; no target used; no
> target-based feature selection.** E2 is a bounded, leakage-safe *transform of E1*
> — no predictive improvement is claimed. Separate, non-blocking feature step.
> Contract: `docs/contracts/MLB_BATTER_PITCHER_PROCESS_INTERACTIONS_V1.md`.

## Executed result (real, from the content-addressed E1 artifact)

- **Terminal status: `PROCESS_INTERACTIONS_READY`.** Runtime **4 s** — read the
  parent E1 artifact (`pitch-sequence-features-ae7eadd6ade83f28`, feature SHA
  `7017c3c88ca96d77…`, **SHA-verified**, no FD1/pitch_sequence rescan), built E2 for
  the exact E1 population. Materialization `process-interactions-75bfccb2e5d08cd6`;
  feature Parquet content SHA `39110d4269c9f61f…` (ignored runtime storage — not
  committed). CLI: `scripts/run_mlb_process_interactions.py`.
- **Row alignment:** 568,935 in → **568,935 out** (pure row-local transform; no
  merge, no fan-out — asserted at build time and in tests, closing the fan-out class
  of defect the catcher audit found).
- **25 bounded features** (hard max 60; the 25×25 Cartesian product is deliberately
  avoided) across 6 baseball-motivated families: strikeout 4, walk 5, first-pitch 2,
  contact 3, sample/reliability 7, recent-form (trailing-30d) 4.
- **Integrity:** **0 exact-duplicate features, 0 near-constant features**, and a
  single high-|Pearson| pair (`bp_log_sample_product` ~ `bp_min_log_sample`, r=0.962)
  flagged for future fold-local handling (not removed — no target-based selection).
- **Coverage (inherited from E1):** both-process-history present 98.6/98.8/98.8%
  (2023/24/25); both-low-sample very small (121/94/76). Feature values are consistent
  products of the E1 rates (e.g. 2024 `bp_ball_rate_product` mean 0.130 ≈ 0.36×0.36;
  `bp_first_pitch_strike_product` 0.374 ≈ 0.61×0.61) — an independent correctness
  check.
- **Missingness preserved honestly:** a product/abs-diff of a null E1 input stays
  null (no global-average imputation); `both_process_history_present`,
  `batter/pitcher_process_missing`, `both_process_low_sample` are explicit indicators.

## STRIKEOUT / WALK interaction readiness (availability, not model result)

STRIKEOUT: swing-miss vulnerability × dominance, called-strike exposure × tendency,
two-strike vulnerability × dominance, first-pitch-strike interaction, and
sample-reliability interaction all **AVAILABLE**. WALK: ball-tendency × ball-tendency,
patience × command, pitches-per-PA × pitches-per-BF, called-strike × command contrast
**AVAILABLE**; full-count interaction **PARTIAL**.

## What E2 still cannot solve

E2 still lacks handedness/platoon, velocity, pitch type, movement, location, contact
quality, catcher framing, and the actual pitch caller — none are inferred. Rare
batted-ball outcomes remain limited by missing contact-quality/tracking evidence.

## Integration & next steps

Registered as a content-addressed feature-family artifact (no model ID, no metrics),
surfaced via `phase4.processInteractions` (Player & Team State → E2 section); graph
now shows a READY Batter-Pitcher Process Interactions node while handedness/platoon
(E6), archetypes, and all algorithm challengers stay `NOT_CONFIGURED`.

- **Recommended E6 next step:** acquire a governed player-profile companion (bats
  L/R/S, throws L/R, primary position, optional age/debut) to segment these
  interactions by platoon quadrant (LHB/RHB × LHP/RHP + switch-hitter side).
- **Recommended future model experiment:** a governed PA-model challenger that adds
  D3 state + E1 process features + E2 interactions (later + E6/archetypes), evaluated
  with the frozen 2024-selection / 2025-final rolling-origin protocol — the only place
  any predictive value of E1/E2 may be claimed.

# E1/E2 INCREMENTAL SIGNAL STUDY (D3 vs D3+E1 vs D3+E1+E2)

**Contract:** `MLB_E1_E2_INCREMENTAL_SIGNAL_STUDY_V1` · **Study ID:**
`e1-e2-incremental-signal-study-682384367a7a0982` · study SHA `8e86354a6e370630…`.
Research study, **not** a promoted model; D3 champion/challenger status is unchanged.

## Purpose

Stop building features long enough to prove whether the features already built actually
improve prediction. This is a **feature ablation only** — one fixed model family, the
frozen D3 regularization (`C=0.05` multinomial l2 logistic, lbfgs), no grid search, no
algorithm tournament, no label-based feature selection, no calibration search.

## Branches, population, protocol

| Branch | Features (named) | Meaning |
| --- | --- | --- |
| A | 33 | D3: context (5) + batter_b (14) + pitcher_b (14) cumulative state |
| B | 81 | A + 48 numeric E1 pitch-sequence process features |
| C | 106 | B + 25 E2 batter × pitcher process-interaction features |

All three branches use the **identical 549,479-PA** population (2023/2024/2025 =
184104 / 182449 / 182926). E1/E2 attach through the registered FD1 identity bridge as a
pure per-(player,date)/(batter,pitcher,date) lookup — **100 % match, zero fan-out, zero
row loss** — so A/B/C differ only in feature set. Rolling origin: train 2023 → evaluate
2024; refit through 2024 → evaluate 2025 (frozen). Fold-local imputation/standardization.
**Correctness anchor: Branch A reproduced the frozen D3 log loss exactly** (2024 =
1.476588, 2025 = 1.474100).

## Raw out-of-time metrics

| Branch | 2024 log loss | 2025 log loss | 2024 Brier | 2025 Brier |
| --- | --- | --- | --- | --- |
| A (D3) | 1.476588 | 1.474100 | 0.703860 | 0.703528 |
| B (D3+E1) | **1.475178** | **1.472346** | 0.703204 | 0.702736 |
| C (D3+E1+E2) | 1.475659 | 1.472397 | 0.703354 | 0.702715 |

## Incremental value and whole-game bootstrap (500 replicates, seed 20260817)

| Comparison | 2024 Δlog loss (rel) | P(better) | 2025 Δlog loss (rel) | P(better) |
| --- | --- | --- | --- | --- |
| **B − A (E1)** | −0.001410 (+0.096 %) | 1.000 | −0.001754 (+0.119 %) | 1.000 |
| **C − B (E2)** | +0.000481 (−0.033 %) | 0.000 | +0.000051 (−0.004 %) | 0.176 |
| **C − A (E1+E2)** | −0.000929 (+0.063 %) | 1.000 | −0.001703 (+0.116 %) | 1.000 |

E1's B−A improvement is **decisive in both years** (bootstrap 95 % CI excludes zero,
P=1.000) but its **magnitude is NEGLIGIBLE-to-SMALL** (< 0.12 %). E2's C−B change is
**worse in both years** — decisively worse in 2024 (P better = 0.000) and statistically
indistinguishable-to-worse in 2025 (P = 0.176).

## Classwise: does E1/E2 repair the known STRIKEOUT / WALK weakness?

**Yes at the class level.** Class-conditional log loss (lower = better):

| Class | Year | A | B | C | E1 (B−A) | E2 (C−B) |
| --- | --- | --- | --- | --- | --- | --- |
| STRIKEOUT | 2024 | 1.45198 | 1.44694 | 1.44467 | **−0.00504** | **−0.00227** |
| STRIKEOUT | 2025 | 1.46629 | 1.46175 | 1.45833 | **−0.00454** | **−0.00342** |
| WALK_HBP_CI | 2024 | 2.25069 | 2.26197 | 2.24493 | +0.01127 | **−0.01704** |
| WALK_HBP_CI | 2025 | 2.30109 | 2.29876 | 2.28952 | −0.00233 | **−0.00924** |

E1 improves STRIKEOUT in **both** years; E2 adds a **further** STRIKEOUT improvement in
both years and repairs WALK_HBP_CI in both years. The value of E1/E2 is genuinely
concentrated in the plate-discipline classes — exactly where the free encoding has signal.

## Rare / batted-ball outcomes (why E2 is aggregate-negative)

E2's net-negative aggregate comes from the contact-quality classes it cannot see. E2 makes
DOUBLE worse in both years (≈ +0.010 class-conditional log loss) and HOME_RUN mixed, while
helping TRIPLE and OTHER_REACH. E1 similarly trades small STRIKEOUT/OTHER_REACH gains for
small DOUBLE/HOME_RUN losses. As hypothesized (not proven), this reflects the absence of
exit velocity, launch angle, barrel/hard-hit, pitch location, velocity, and movement — E1/E2
measure *process/discipline*, not contact quality.

## Catastrophic misses & calibration

Tail behaviour is essentially flat across A/B/C: realized outcomes assigned < 0.5 %/1 %/2 %/5 %
probability differ by only tens of rows out of ~182k per season, and the tail's share of
total log loss is unchanged. E1/E2 **shift average performance, not tail risk**, and create
no new catastrophic failures. Raw top-label ECE is comparable across branches (B/C are not
worse-calibrated than A); the feature-value verdict uses raw outputs only — no temperature
scaling was applied.

## Verdict

- **E1 → `E1_PREDICTIVE_VALUE_MARGINAL`.** Decisively improves out-of-time log loss and
  Brier in both years and improves STRIKEOUT specifically, but the aggregate magnitude is
  NEGLIGIBLE-to-SMALL (< 0.12 %).
- **E2 → `E2_INCREMENTAL_VALUE_NEGATIVE`.** On top of E1 it does not improve the aggregate
  (worse in 2024, neutral-to-worse in 2025), even though it further improves the STRIKEOUT
  and WALK discipline classes. Its manual pairwise interactions add batted-ball error the
  model cannot offset without contact-quality features.

Feature-family **readiness** status is unchanged — predictive value and materialization
readiness are separate concepts.

## Prioritized next step — PATH 2

E6 handedness/platoon next, then a nonlinear algorithm tournament (a linear model may not
capture E2-style interactions; a tree/boosting learner might extract matchup value E2's
hand-built products cannot). **Do not expand manual E2 aggressively.** E6 should proceed;
archetypes should not yet; the algorithm tournament should proceed; premium-data priority is
not raised by this study (E1 already shows the free encoding carries a small, real,
discipline-class signal). Retain E1/E2 as candidate inputs for a K/BB-focused component or
multitask architecture, where their class-level value is strongest.

# MILESTONE B EXECUTION RESULT (governed real run)

**Executed:** 2026-08-18 · **Run runtime:** ~21m46s (supervised worker, 500 whole-game
bootstrap replicates, watchdogs active) · **Run ID:**
`sports-participation-usage-run:sha256:37895c8a…` · **Study ID:**
`sports-phase4-study:sha256:4bd93ba8…` · **Graph ID:**
`sports-phase4-model-graph:sha256:43dc15a2…` · 84 artifacts (32 dynamic + 20 lineup +
22 starter + 20 bullpen).

**Authorities:** FD1 dataset `sports-dataset-1b58d5d1def2c9b7` (manifest `1b58d5d1…`,
partition authority `8dec143b…`), identity bridge `sports-identity-bridge-6b69e7dcf4c5db76`,
D3 dynamic-state parent component `DYNAMIC_STATE_RESEARCH_CHALLENGER` (unchanged). Temporal
protocol: prior-date candidate pools only; retrospective 2024 selection / frozen 2025
rolling-origin evaluation; no target-game participant injection; no 2025 tuning.

## Lineup projection — `LINEUP_RESEARCH_COMPONENT` (selected L1)

| Metric | 2024 | 2025 |
| --- | --- | --- |
| top-9 recall | 0.7981 | 0.8040 |
| top-9 F1 | 0.7981 | 0.8041 |
| exact batting-position rate | 0.5475 | 0.5407 |
| start-probability log loss | 0.1666 | 0.1615 |
| start-probability Brier | 0.0520 | 0.0500 |
| early-season top-9 recall | 0.7969 | 0.8022 |
| candidate-pool coverage | 99.38% | 99.34% |

Bootstrap vs L0 baseline (500 whole-game replicates): −0.3543 (2024) / −0.3543 (2025) log
loss, 95% CI excludes zero, **P(selected better) = 1.000** both folds. Uncovered actual
starters are measured, never injected.

## Starter duration — `STARTER_DURATION_RESEARCH_COMPONENT` (selected S2)

Historical evaluation remains explicitly `CONDITIONAL_ON_HISTORICAL_STARTER_IDENTITY`
(pregame announcement timing is not claimed).

| Metric | 2024 | 2025 |
| --- | --- | --- |
| BF MAE | 2.775 | 2.751 |
| BF RMSE | 3.755 | 3.721 |
| outs MAE | 2.878 | 2.798 |
| reach-18-outs Brier | 0.2164 | 0.2142 |

Bootstrap: vs S0 −0.4395 (2024) / −0.3683 (2025) BF MAE; vs S1 −0.2325 (2024) / −0.2563
(2025); all 95% CIs exclude zero, **P(selected better) = 1.000** for all four comparisons.

## Bullpen usage — `BULLPEN_USAGE_RESEARCH_COMPONENT` (selected B1)

| Metric | 2024 | 2025 |
| --- | --- | --- |
| appearance log loss | 0.2987 | 0.2924 |
| appearance Brier | 0.0958 | 0.0930 |
| top-3 reliever recall | 0.4215 | 0.4220 |
| top-5 reliever recall | 0.6661 | 0.6585 |
| expected reliever-count MAE | 1.083 | 1.101 |
| candidate-pool coverage | 96.37% | 96.07% |

Bootstrap vs B0 baseline: −0.1145 (2024) / −0.1157 (2025) log loss, 95% CI excludes zero,
**P(selected better) = 1.000** both folds. Calibration acceptable both folds (ECE ≤ 0.05).

## Calibration decisions

Each component's binary probabilities use the governed equal-count decile calibration
(`MLB_PARTICIPATION_BINARY_CALIBRATION_V2`). No new calibration search was run; raw
probabilities are retained where a frozen gate does not accept scaling. Bullpen calibration
was acceptable in both folds; lineup/starter report calibration descriptively.

## Catcher readiness reference

Catcher influence readiness was executed separately (see the catcher-readiness section) and
is referenced, not re-run, by this closeout.

## Registry / graph

Registered as content-addressed, logical-URI-oriented artifacts (feature views, model state,
predictions, metrics, calibration, bootstrap, lineage, component cards, study summary) — no
raw model bytes in relational metadata, no placeholder metrics. The model graph (24 nodes,
26 edges) now shows real **Dynamic Player State**, **Lineup projection research**, **Starter
duration research**, and **Bullpen usage research** nodes alongside the frozen Phase 3
baseline. Future nodes remain `NOT_CONFIGURED`: **Handedness and platoon**, **Base-out
transition**, **Game simulator**, **Residual correction layer**, **ASP export bundle**, and
**Prospective monitoring**. No node implies launch readiness.

## Engineering fixes applied during execution (registry ↔ runner schema reconciliation)

Milestone B had never been executed end-to-end, so the Phase 4 registry validator had drifted
behind the runner's current V2 metrics/calibration/bootstrap schema. The smallest justified
fixes were applied and each was verified against the governed run's own persisted evidence
(not guessed): (1) the participation runner now reconciles the dynamic componentId to the
registry's strict form exactly as registration does; (2) the stale `EXPECTED_COMPLETE_LINEUP_GAMES`
golden constant was corrected to the governed-derived `{2430, 2429, 2430}` (every target game
carries a complete nine-batter lineup); (3–5) the lineup/starter/bullpen metric key-sets now
include the governed exact-batting-position, stratified, and history-depth fields; (6) the
lineup team-game rows accept `exactBattingPosition*`; (7) the binary-calibration validator was
rewritten for the equal-count V2 schema; (8) `exactLineupRate`/`exactOrderRate` are now
reconciled per game (both teams exact) as the metrics define them; (9) the bootstrap validator
accepts the V2 schema, cluster policy fields, and the current cluster count. All three
reconstructed components pass the full participation validator offline.

## Limitations

Retrospective reconstruction is not prospective proof. No governed roster, transaction,
injury, option, or announcement feed is present, so these components are research components,
not deployable pregame predictors. Uncovered actual participants are measured and never
injected into candidate pools.

## Remaining simulator prerequisites

A plate-appearance-level game simulator requires: (1) a governed prospective roster /
lineup / probable-starter / bullpen-availability feed to make the participation components
pregame-usable; (2) the base-out transition component; (3) an integration layer combining D3
PA probabilities with the participation/usage layer; and (4) a residual correction layer.
None exist yet; the graph reflects this honestly.

## Launch-critical next steps (ranked by launch value, from Phase 4 evidence)

1. **Game-simulation integration.** The participation/usage layer (lineup, starter, bullpen)
   and D3 PA probabilities now both exist as research components; the missing launch-critical
   piece is the integration/simulator that turns them into game-level projections. This is the
   single highest-value next step and gates every downstream product.
2. **Prospective roster / lineup / probable-starter feed.** The components are strong
   retrospectively (bootstrap P=1.000) but are explicitly not pregame-usable without a governed
   prospective participation feed. This is the prerequisite that converts the research
   components into deployable inputs — second only to the simulator it feeds.
3. **Premium contact-quality (Statcast) data trial.** Phase 4F showed the D3 severe-error tail
   is ~99% contact-quality batted-ball outcomes invisible to the free features; premium data is
   the only lever on that tail. Raised in priority by Phase 4F, but it improves PA quality
   rather than unblocking launch, so it ranks below the simulator + feed.
4. **E6 handedness/platoon.** Phase 4E showed marginal aggregate value with real STRIKEOUT/WALK
   class-level signal; unchanged priority — worthwhile but not launch-critical.
5. **Algorithm tournament.** Phase 4F showed the severe tail is data-limited, not
   model-family-limited; a nonlinear tournament may help the bulk but not the tail. Lower
   priority than premium data for the dominant error mode.
6. **Catcher/battery predictive model and bundle export.** Deferred until the simulator and a
   prospective feed exist; exporting to AI Sports Predictor is premature before then.

**Priority-change summary from Milestone B + 4E + 4F:** simulator integration is now the #1
launch blocker; premium-data priority is **raised** (4F); nonlinear-algorithm priority is
**not raised** for the tail (4F); E6 priority is **unchanged** (4E).
