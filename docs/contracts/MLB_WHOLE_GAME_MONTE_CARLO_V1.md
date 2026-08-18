# MLB_WHOLE_GAME_MONTE_CARLO_V1

**Status:** research simulation component (Phase 5D). **Not** a production forecast, betting
model, live prediction engine, or market-comparison. Winner probability is a game-distribution
diagnostic only.

## Purpose

Combine the four proven Phase 5 components — actual historical participants (oracle mode), the
frozen D3 PA-outcome provider, the Phase 5B empirical base-out transition model, and the
deterministic Phase 5A kernel — into the smallest whole-game stochastic driver, and evaluate
the resulting game-level score distributions against actual 2024/2025 games.

## Parent authorities

- `MLB_GAME_REPLAY_ENGINE_V1` (kernel semantics) — READY
- `MLB_BASE_OUT_TRANSITION_MODEL_V1` (model SHA `4f312af6…3459e4`) — READY
- `D3_PROBABILISTIC_PA_PROVIDER_V1` (D3 model authority = dynamic-state contract SHA) — READY
- `MLB_HISTORICAL_PARTICIPANT_REPLAY_PROVIDER_V1` — READY
- `MLB_GAME_INITIALIZATION_CONTRACT_V1` — READY

None are retrained, rebuilt, or modified. The D3 fold is selected by season (2024 fold trained
on 2023; 2025 fold trained on 2023-24) and reproduces the frozen `raw_D3` probabilities exactly
(the whole-game engine decomposes the multinomial-logistic predictor for speed but produces the
same softmax to machine precision).

## Participant mode

**`HISTORICAL_PARTICIPANTS_ORACLE_MODE`.** Participants are keyed to the batting team's
plate-appearance ordinal from the actual game: the k-th time a team bats it faces the
batter/pitcher it actually faced on its k-th PA, replaying the real batting order, substitutions,
and pitcher changes by PA ordinal. When a simulated game runs longer than the actual game
(sampled extra innings), the batting order continues from the starting nine and the last actual
pitcher is retained. This is an oracle upper-bound reference — **not** a prospective pregame
decision, since real substitutions were partly reactions to the actual game state.

## Simulation inputs

Per game: game id/date, season, regulation innings, and the oracle batter/pitcher contribution
sequences per team, derived from the governed FD1 `play_transition` ledger.

## RNG policy

One deterministic lineage per game: master study seed → per-game seed (`SHA-256(game_id)` folded
into a NumPy `SeedSequence`) → independent PA-sample and transition child generators. Fixed-size
draws per step make a game's outcome independent of which simulations are still active. Same
master seed + authorities + game reproduces the identical sample; a different seed diverges.

## Simulation loop

Per simulation: initialize (inning 1, top, 0 outs, bases empty, 0-0); while not terminal —
resolve active batter/pitcher (oracle), construct the D3 context from current game state, obtain
the eight-class PA probability vector, sample a PA outcome, obtain the Phase 5B transition
distribution for `(outcome, outs, base)`, sample a legal transition, apply it through the kernel
semantics (runs to the batting team, outs/base updated, half-inning switch on the third out),
advance the batting order, and continue. Baseball mechanics are never duplicated outside the
proven kernel/transition model.

## Terminal rules

Regulation = 9 innings. A half-inning ends on the third out. The home team does not bat in the
bottom half when already leading after the top of a regulation-or-later inning; a game is decided
after the bottom half of a regulation-or-later inning when the score is not tied; a walk-off ends
the game immediately when the home team takes the lead in the bottom of a regulation-or-later
inning. Ties after regulation go to extra innings with the automatic runner on second at each
half start. A watchdog force-terminates any game exceeding 200 plate appearances (recorded).

## Outputs

Per game (aggregate only): mean/median away, home, total runs and run differential; score
quantiles (5/10/25/50/75/90/95); prediction intervals (50/80/90/95); home-win probability;
mean innings and extra-inning rate; per-game CRPS for away/home/total; interval-coverage hits;
plus the actual away/home/total/differential and winner. Every simulated plate appearance is
**not** persisted.

## Historical evaluation policy

2024 and 2025 evaluated separately. Score MAE/RMSE/bias (away, home, total, differential),
total-run CRPS, prediction-interval coverage, winner Brier/log loss/ECE and calibration bins,
distribution-shape comparison, temporal and retrospective-band diagnostics (labeled
`RETROSPECTIVE_DIAGNOSTIC_ONLY`), error concentration (Pareto), and a G0 generic-baseball
baseline ablation (fixed league-average PA distribution over the same kernel/transitions/
participants) isolating D3's game-level value.

## Uncertainty summaries

Monte Carlo convergence is measured on a stratified pilot at 100/250/500/1000 simulations; the
development-standard count is chosen as the lowest count with stable game-distribution summaries.

## Absolute exclusions

No D3 retraining/changes, E1/E2/E6, algorithm tournament, premium/Statcast data, transition-model
changes, new lineup/starter/bullpen/catcher models, residual/home-field/park/calibration
correction, prospective/live feeds, or UI redesign. No moneyline/run-line/total lines, closing
odds, CLV, market edge, ROI, parlays, or betting strategy. No provider/network calls, no new data.
Readiness labels are limited to `WHOLE_GAME_SIMULATOR_RESEARCH_BASELINE_READY` /
`…_PARTIALLY_READY` / `…_BLOCKED`; never production/betting/live-ready.
