# MLB_PROJECTED_PARTICIPATION_ABLATION_V1

**Status:** research study (Phase 5E). Controlled P0→P3 participation ablation of the whole-game
Monte Carlo. **Not** a production forecast, betting model, or market comparison. Winner
probability is a game-distribution diagnostic only.

## Purpose

Measure how much game-level predictive value is lost as historical oracle participants are
progressively replaced by ASP's own frozen Milestone B research components. The only dimension
that changes across branches is participation realism; the D3 PA model, the Phase 5B base-out
transition model, the kernel, the simulation count (500/game), the RNG lineage, and the
evaluation metrics are identical.

## Branches

| branch | participation | knowledge |
| --- | --- | --- |
| **P0** | historical oracle | actual lineup, starter, pitcher changes/bullpen by PA ordinal (reproduces Phase 5D) |
| **P1** | projected lineup (L1) + oracle pitching | projected starting nine; actual pitching |
| **P2** | P1 + projected starter duration (S2) | starter IDENTITY actual (oracle); projected removal point; oracle bullpen after |
| **P3** | P2 + projected bullpen (B1) | projected reliever sequence — `PROJECTED_PARTICIPATION_RESEARCH_MODE` |

## Parent authorities

`MLB_WHOLE_GAME_MONTE_CARLO_V1` (P0 = Phase 5D run `whole-game-mc-7aed0242bdcee1d2`),
`MLB_GAME_REPLAY_ENGINE_V1`, `MLB_BASE_OUT_TRANSITION_MODEL_V1` (SHA `4f312af6…3459e4`),
`D3_PROBABILISTIC_PA_PROVIDER_V1`, `MLB_HISTORICAL_PARTICIPANT_REPLAY_PROVIDER_V1`,
`MLB_GAME_INITIALIZATION_CONTRACT_V1`, and the Milestone B components **L1** (lineup, selected),
**S2** (starter duration, selected, `CONDITIONAL_ON_HISTORICAL_STARTER_IDENTITY`), **B1**
(bullpen usage, selected). None are retrained or modified.

## Participant knowledge allowed per branch

- **Lineup (P1+):** projected starting nine = top-9 by L1 start probability per (game, team).
  Batting order is proxied by L1 start-probability order (L1 predicts no order; D3 has no
  batting-order feature, so the effect is second-order). Actual lineup is used only for
  evaluation (retrospective recall), never to choose the projected nine.
- **Starter (P2+):** starter IDENTITY is the actual one (oracle — S2 is conditional on it);
  the projected removal point is `round(S2 s2_bfp)` batters faced. Labeled
  `STARTER_IDENTITY_ORACLE + PROJECTED_STARTER_DURATION`.
- **Bullpen (P3):** projected reliever sequence from B1 (candidates in appearance-probability
  order, each for `round(b1_bfp)` batters). Actual relievers are never used to choose the P3
  bullpen.

## Temporal policy

The D3 cumulative B-state is materialized only for (player, date) pairs that actually appeared. A
projected player absent from the game date resolves to their **most-recent prior materialized
cumulative state** (B-state is cumulative and slowly varying); a player with no prior state
resolves to the role-league mean. All fallback usage is counted. No target-game future evidence
is used.

## RNG policy

One deterministic lineage per game (master seed → `SHA-256(game_id)` → PA-sample + transition
generators), identical across branches, so a branch delta reflects participation only, not RNG
noise.

## Comparable population

Primary comparison uses the intersection of games where all four branches are constructible
(both teams have a 9-player L1 projection and an S2 starter) and the game is Phase-5D-eligible.
2024 and 2025 are reported separately.

## Metrics

Per branch/season: home-win Brier/log loss/ECE; away/home/total-run CRPS; total-run MAE/RMSE/bias;
run-differential MAE/RMSE; 50/80/90/95% interval coverage; dispersion; simulation legality.
Incremental degradation (P1−P0, P2−P1, P3−P2, P3−P0) in absolute and relative terms, with a
deterministic whole-game bootstrap (500 replicates) reporting mean delta, 95% CI, and
P(worse)/P(better). Practical-magnitude thresholds (relative): <1% NEGLIGIBLE, <3% SMALL, <8%
MEANINGFUL, ≥8% LARGE.

## Terminal decision states

Overall: `PROJECTED_PARTICIPATION_VALUE_PRESERVED` / `…_ACCEPTABLE_DEGRADATION` /
`…_MATERIAL_DEGRADATION` / `…_BLOCKING`. Per component:
`{LINEUP,STARTER_DURATION,BULLPEN}_GAME_IMPACT_{ACCEPTABLE,MATERIAL,BLOCKING}`.

## Absolute exclusions

No retraining of D3/L1/S2/B1, no new participation features, E6, clustering, archetypes,
algorithm tournament, premium data, sportsbook data, betting edge/ROI/parlays, AISP connection,
prospective feeds, residual corrections, or UI redesign. This is one controlled ablation.
