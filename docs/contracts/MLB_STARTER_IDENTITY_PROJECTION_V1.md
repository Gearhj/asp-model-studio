# MLB_STARTER_IDENTITY_PROJECTION_V1

**Status:** research component (Phase 5F). Predicts the pregame starting pitcher per team-game
and closes the last critical participation oracle in the whole-game simulator. **Not** a
production forecast, betting model, or market comparison.

## Purpose

Predict which pitcher starts each team-game using only information available strictly before the
target game, then measure the game-level cost (Q0→Q1) of replacing the oracle starter identity
with the projection inside the whole-game Monte Carlo.

## Prediction timestamp semantics

Prediction is made pregame: all features derive from events strictly before the target game
date. The target-game starter label and any same-game usage are never features.

## Target

Per team-game, the actual starting pitcher = the first pitcher (minimum play number) that team's
pitching side sends out in the governed `play_transition` ledger. Exactly one starter per
team-game. Team-games where no prior evidence exists yield no candidate pool and are reported
(not silently dropped).

## Candidate pitcher pool

Per team-game on date D: the team's **season-to-date starters** (same calendar year, before D)
**∪ recent starters** (started for the team within the prior 45 days). A candidate-pool miss —
the true starter is not in the pool — caps achievable accuracy and is reported as a critical
metric (~7.5%: season openers, debut starters, and long-injury returns). The actual target-game
starter is never used to force pool inclusion.

## Temporal policy

Strictly prior-date features only. No target-game starter label, same-game usage, future
rotation/schedule/results, target box score, or future bullpen appearances. Doubleheaders are
identified via the governed schedule fields; ambiguous same-date sequencing is treated fail-closed.

## Features

Per candidate, all from prior-date history: rotation-turn proximity (`-|team-games-since-last-
start − 5|`), days-turn proximity, team-games since last start, starts in the prior 30 days,
season-to-date starts, days since last appearance, season start frequency, a rotation-rest-band
indicator, and a recent-appearance indicator. No injury status is invented; no future schedule
assignment is used.

## Baselines

S0 most-overdue (longest rotation wait, capped), S1 rotation-order (team-games-since-last-start
closest to a 5-turn), S2 highest season start frequency. The model must beat the best baseline to
justify complexity.

## Retained model

A within-team-game candidate-ranking L2 logistic model (fit on 2021–2023 development), scoring
P(candidate starts) per candidate and softmax-normalizing within the team-game; the top candidate
is the projected starter, and the full distribution is retained for uncertainty diagnostics. No
new PA features; no retraining of D3/L1/S2/B1.

## Evaluation

2024 validation / 2025 frozen (no tuning on 2025). Per season: candidate-pool coverage, top-1/2/3
accuracy, log loss, Brier, MRR, mean candidate count, and segmentation by month (early season),
rotation cadence (rest), and opener/irregular starts. Per-game uncertainty (top probability,
top1–top2 gap, entropy, candidate count) is recorded.

## Simulator integration

Two branches over the Phase 5E P3 projected-participation simulator:

- **Q0** — P3 with `STARTER_IDENTITY_ORACLE` (actual starter).
- **Q1** — P3 with the **projected** starter identity; starter duration is bound to the projected
  identity: the actual S2 `s2_bfp` when the projection is correct, otherwise the projected
  pitcher's own mean historical batters-faced (median fallback). Lineup (L1) and bullpen (B1) are
  unchanged; D3, transition model, kernel, 500 sims/game, and RNG lineage are identical to Q0.

Selection policy: **top-1** projected starter (deterministic; the simplest policy the model
supports). A projected starter that cannot resolve to D3 pitcher state uses only the governed
missing-history fallback (counted); the actual starter is never silently substituted.

## Decisions

Model: `STARTER_IDENTITY_RESEARCH_COMPONENT` / `…_BASELINE` / `…_REJECTED` / `…_BLOCKED`.
Simulator: `STARTER_IDENTITY_PROJECTION_ACCEPTABLE` / `…_MATERIAL_DEGRADATION` / `…_BLOCKING`.

## Limitations

Prior-date rotation cadence only; pool coverage caps top-1 (~92.5%). Q1 duration policy is a
governed proxy, not a re-run of S2 on the projected identity. Still a historical source population
with no injury/scratch or confirmed-lineup feed — not a live pregame forecast. Winner probability
is a diagnostic only; no sportsbook data, edge, ROI, or parlays.
