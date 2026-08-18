# ASP Model Studio — Phase 5 Deterministic MLB Game Replay Engine

**Contract:** `MLB_GAME_REPLAY_ENGINE_V1` · Mechanical, not predictive. No probabilistic
simulation, Monte Carlo, win/run-line/total probabilities, or betting logic.

---

## Executive Verdict

**`GAME_REPLAY_ENGINE_READY`.** The deterministic kernel reconstructs game state from the
governed FD1 `play_transition` ledger and reproduces **99.986%** of all 7,289 real
2023–2025 games **exactly** — event by event and state by state — with **100%** final-score
and inning-sequence reconciliation and **99.986%** base-out continuity. The single
non-exact game is a documented source-data quirk (an `NP` "no-play" row recorded with
`outs_before = 3`), not an engine defect. The mechanics are trustworthy enough to begin
building a probabilistic simulator on top — which does **not** yet exist.

| Metric | Full 2023–2025 |
| --- | --- |
| Games attempted | 7,289 |
| EXACT_REPLAY | **7,288 (99.986%)** |
| PARTIAL_REPLAY | 0 |
| REPLAY_MISMATCH | 1 |
| SOURCE_INSUFFICIENT | 0 |
| Final-score exact rate | 100.0% |
| Inning-sequence exact rate | 100.0% |
| Base-out continuity rate | 99.986% |
| Game-end valid rate | 100.0% |
| Runtime (full replay) | ~27 s |

## Replay Contract

A deterministic **replay validator**: it consumes actual historical events and reproduces
state transitions exactly, classifying each game `EXACT_REPLAY` / `PARTIAL_REPLAY` /
`REPLAY_MISMATCH` / `SOURCE_INSUFFICIENT`. It samples nothing and predicts nothing. Runner
destinations come from the source after-state (actual advancement), never from crude
one-base-per-single rules.

## Source Schemas

Only the governed FD1 `play_transition` family (949,217 plays; 570,548 in the 2023–2025
primary seasons across 7,289 games; dataset manifest `1b58d5d1…`). Verified authoritative
properties: `play_number` contiguous 1..N per game; within-half `*_before == prev *_after`
(perfect continuity); `base_mask` bits first=1/second=2/third=4 match
`runner_on_{first,second,third}` (empty encoded as the string `None`); `runs_scored`
reconciles score deltas; extra innings place an automatic runner on second; regulation
innings 9 (or 7 for the 2021–2022 doubleheader rule); `top_bottom = 0` is the top half
(visitor batting), `1` the bottom (home batting) — verified against which team's score
increases.

## State Model

`inning`, `top`, `outs`, `base_mask` (0..7), `away_score`, `home_score`, `terminal`. The
engine tracks state independently from a fresh start and validates it against the source at
every play, then adopts the authoritative after-state.

## Event Taxonomy

Plays carry the frozen 8-class PA vocabulary (`pa_outcome`) plus the raw `event_text`, but
the engine's mechanics are driven by the authoritative base/out/score deltas rather than the
coarse 8-class target — deliberately, because the source carries richer runner-advancement
evidence than the 8-class model target. Outcome labels are retained for mismatch forensics.

## Runner Advancement

Taken directly from `base_mask_after` / `runner_on_{...}_after` (actual destinations). No
inference. A single that scores a runner from first, a double that leaves a runner at third,
a fielder's choice, and a sacrifice all reproduce their true resulting base state.

## Out Handling

Outs are validated to stay in `[0,3]` and never decrease within a play; the third out ends
the half-inning. Double plays, sacrifices, force outs, fielder's choices, strikeout-plus-
advancement, and reached-on-error are all handled by consuming the source out/base deltas,
never collapsed into simplistic BIP_OUT logic.

## Inning / Game Rules

Deterministic half-inning transitions (top→bottom same inning; bottom→top increments
inning; outs reset; bases clear). The extra-innings automatic runner on second is honored at
a half start (including when a no-op marker play precedes the first real play). Game-end is
validated to flag only genuine anomalies (a completed regulation game left tied); weather /
called games that legitimately end before regulation with a leader are valid, not anomalies.

## Batter Order & Pitcher Tracking

The engine tracks the active-pitcher sequence per game from `pitcher_id` transitions
(retrospective, never inferred) as a future validation target for probabilistic usage
integration. Batting-order reconciliation is available through the source lineup fields; the
replay does not use it as a predictive lineup model.

## 75-Game Sample Results

A deterministic, diverse per-season sample (25 × 2023/2024/2025 including extra-inning,
high-scoring, low-scoring, walk-off, and multi-reliever games — no cherry-picking of easy
games) replayed **100% EXACT_REPLAY, zero mismatches**, so the full population was executed.

## Full Replay Results

7,289 games, 99.986% EXACT_REPLAY, 100% final-score and inning reconciliation (table above).

## Mismatch Forensics

The only residual (1 game, `retrosheet:game:MIA202304160`) is a **source-data quirk**: an
`NP` "no-play" row recorded with `outs_before = 3` at a half-inning boundary, which
contradicts the mechanical invariant that a play begins with fewer than three outs. It is
classified honestly as `REPLAY_MISMATCH` and **not** patched with a hard-coded game id — no
general semantic rule is wrong. Two general rules *were* corrected during development, each
verified against the source: the extra-innings ghost runner appears on the first *real* play
after a no-op marker (the half-start flag now survives leading markers), and weather-shortened
games are legitimate ends (the game-end validator no longer requires reaching regulation).

## Readiness Decision

`GAME_REPLAY_ENGINE_READY`. This means the deterministic mechanics are trustworthy enough to
begin probabilistic simulation. It does **not** mean a forecasting simulator exists.

## Future Probabilistic Simulator Design

The engine exposes clean provider seams (`PAOutcomeProvider`, `RunnerAdvanceProvider`,
`ParticipationProvider`, `PitcherUsageProvider`, `HistoricalReplayProvider`,
`SimulationEngine`). The future simulator swaps the deterministic `HistoricalReplayProvider`
(actual events) for a sampling provider (model-drawn PA outcomes), reusing the identical
base-out / half-inning / scoring kernel. Nothing else in the kernel changes.

## Base-Out Transition Next Step

For a *sampled* PA outcome the simulator will need `P(runner advancement | PA outcome, base
state, outs, player/game context)`. The governed `play_transition` ledger already contains
the (base-state, outs, PA-outcome → after-state) empirical transitions across 570k+ plays to
estimate that distribution later. It is **not** implemented now.

## Residual Layer Next Step

Documented, not implemented: once probabilistic simulation exists, compare the simulated game
distribution to historical actual games and investigate residual corrections for team, park,
weather, defense, bullpen sequencing, contact quality, and strategy. No residual correction
is added to deterministic replay.

## Launch Implications

The deterministic kernel is the first proven, launch-critical simulation foundation. The
next launch-critical step is the **base-out transition distribution + a probabilistic
PA-outcome provider** (swapping actual events for sampled events on this identical kernel),
followed by whole-game Monte Carlo — none of which exist yet. Game Simulator, Monte Carlo,
residual layer, and ASP export remain `NOT_CONFIGURED`.
