# MLB_BASE_OUT_TRANSITION_MODEL_V1

Governed **simulation component / transition model** contract. Not a PA-outcome model, not a
game forecast, not a betting model, not a production deployment, not a Monte Carlo result.

## Purpose

The launch-critical bridge between a sampled eight-class PA outcome and the proven
deterministic game kernel (`MLB_GAME_REPLAY_ENGINE_V1`, `GAME_REPLAY_ENGINE_READY`). Given a
game state and a PA outcome class, return a probability distribution over **legal** next-state
transitions from which the future simulator samples.

## Parent & source authorities

Parent replay engine `MLB_GAME_REPLAY_ENGINE_V1`. Source: the governed FD1 `play_transition`
family (dataset manifest `1b58d5d1…`) — the same authoritative before/after ledger the replay
kernel consumes. No new data.

## Transition target

Canonical signature `(outs_added, base_mask_after, runs_scored)`. On the third out the
half-inning ends and the source clears the bases, so `base_mask_after = 0` and surviving
runners are stranded.

## State representation & event mapping

Conditioned on `(pa_outcome ∈ 8 classes, outs_before ∈ {0,1,2}, base_mask_before ∈ 0..7)` =
192 primary cells. `pa_outcome` is already the frozen 8-class label
(`STRIKEOUT, WALK_HBP_CI, HOME_RUN, SINGLE, DOUBLE, TRIPLE, BIP_OUT, OTHER_REACH`); 35,868
non-PA marker rows are excluded. 913,349 eligible PAs; 99.92% satisfy the single-PA runner-
conservation invariant, the 0.08% residual (multi-play / source quirks) are excluded from
fitting and evaluation with reason.

## Deterministic rules

`HOME_RUN` is mechanically deterministic (verified 100%): bases clear, outs unchanged,
`runs = occupied runners + batter`. `STRIKEOUT` (98.9% ordinary) and `WALK_HBP_CI` (99.6%
forced-advance) are low-entropy but retained empirical to capture legal exceptions (dropped
third strike, steals, extra advancement).

## Empirical model & smoothing

Champion **T0** = empirical conditional distribution `P(transition | outcome, outs, base)`
fit on development seasons only, with **Dirichlet(α=0.5) smoothing spread over the enumerated
legal transition set** of the cell — so unseen-but-legal transitions receive small positive
probability while illegal transitions receive exactly zero.

## Legality

A transition is legal iff `outs_before ∈ {0,1,2}`, `outs_added ≥ 0`, `runs ≥ 0`,
`outs_before + outs_added ≤ 3`, `base_mask_after ∈ 0..7`, and runner conservation holds:
inning-continues → `popcount(before)+1 == popcount(after)+runs+outs_added` with a valid
forward (no-pass) runner assignment; inning-ends → `base_mask_after == 0` and
`popcount(before)+1 − outs_added − runs ≥ 0` (stranded ≥ 0). Illegal probability mass is
always **zero**, hard-validated per cell.

## Fallback hierarchy

`L0_EXACT (outcome,outs,base)` → `L1_OUTCOME_OUTS` → `L2_OUTCOME` → `L3_LEGAL_PRIOR`
(uniform over the enumerated legal set). Every level is filtered to transitions legal for the
current base state, so legality is preserved under fallback. Fallback usage is reported on
2024 and 2025.

## Temporal fitting

Development 2021–2023; out-of-time validation 2024; frozen final 2025. 2025 is never used for
policy selection. A predeclared context challenger (T1: + inning band) is retained only if it
improves 2024, does not reverse on 2025, and clears a whole-game bootstrap — otherwise T0.

## Evaluation

One-step transition backtest: multiclass transition log loss and summed Brier; top-1 and
top-2 transition coverage; runs-scored MAE; outs-added, base-mask-after, and inning-ending
accuracy; per-outcome and per-cell breakdown; transition entropy; deterministic/stochastic
share; error concentration (Pareto). Plus a stochastic legality stress test (repeated sampled
transitions through the deterministic kernel — required illegal-state count **zero**) and a
seeded reproducibility check.

## RNG contract

Sampling accepts an explicit RNG. Same (state, outcome, model authority, seed) reproduces the
same transition; a different seed can produce an alternative legal path in stochastic cells.

## Artifact identity

Data-only JSON (never pickle/joblib/dill — executable serialization is a governed RCE risk).
Content-addressed under ignored runtime storage; SHA-256 and byte count recorded.

## Exclusions

No whole-game Monte Carlo, win/run-line/total probabilities, betting edge, AISP integration,
E6, archetypes, algorithm tournament, new PA training, D3/E1/E2 changes, premium data,
residual model, prospective feed, provider/network calls, or new data acquisition.
