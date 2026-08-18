# MLB_PA_SEVERE_MISS_FORENSIC_STUDY_V1

Governed **forensic research study** contract for Phase 4F. Analysis only — no model is
promoted, no official observation is removed, no individual loss is clipped for reporting,
and no outcome is relabelled.

## Question

Is the D3 PA model mediocre everywhere, or is a relatively small set of structured baseball
situations disproportionately damaging prediction quality? If severe individual misses have
a repeatable, **pre-prediction** signature, which correction is highest value?

## Inputs and authorities

Regenerates the frozen Phase 4E A/B/C out-of-sample probabilities (A = D3, B = D3+E1,
C = D3+E1+E2) under the identical fixed policy (`C=0.05` multinomial l2 logistic, lbfgs) on
the identical **549,479-PA** population. Branch A must reproduce the frozen D3 log loss
(2024 = 1.476588, 2025 = 1.474100) as a correctness anchor or the study fails closed. Class
order is the frozen MLB order (0 STRIKEOUT … 7 OTHER_REACH). Governed segmentation evidence
comes from registered FD1 families `player_game_batting` (lineup/position, incl. DH),
`player_game_pitching` (`actual_start_flag` → starter/reliever), `player_game_fielding`
(catcher context), and `plate_appearance` (game state) — all **RETROSPECTIVE**
(timing-risk labelled) and used for segmentation only, never as a pregame model feature.

## Analyses

Individual log loss and summed multiclass Brier (governed floor, no new clipping); full
percentile distributions; Pareto/Lorenz loss concentration; multiple severe-miss
definitions (worst-loss percentiles, true-class-probability thresholds, excess-vs-A);
confusion-pair rankings; actual-outcome over-indexing; governed segmentation by batter
position/role, starter vs reliever, substitute/pinch, catcher certainty, batter/pitcher
history, E1 process state, E2 interaction region, game state, month/season phase; game and
(anonymized) player concentration; probability-resolution (overconfident-wrong vs rare
outcome); target-free OOD (standardized Mahalanobis, fit on training-eligible folds);
tail-sensitivity (diagnostic only); and one diagnostic **pre-prediction** severe-miss
classifier (fit 2024, evaluated out-of-time 2025; predictors exclude outcome, loss, future
information, and retrospective role/position). Randomness verdict, corrective-category
assignment, and a 6-axis priority ranking (impact, repeatability, detectability, ease,
betting relevance, data availability).

## Absolute prohibitions

No removal of legitimate hard observations from the official population; no loss clipping /
winsorizing for official metrics; no dropping of rare outcomes, positions, relievers, or
rookies to improve a score; no target relabelling; 2025 is not used to design/fine-tune any
correction repeatedly. A future product may legitimately *abstain from a bet*; that is
distinct from removing observations from evaluation, and the distinction is preserved.

## Bounded correction gate

Only a strong, repeatable, pre-prediction-detectable, materially loss-contributing pattern
may trigger at most one or two bounded diagnostic correction experiments (minimal fixed
policy, evaluated out-of-time on 2024 **and** 2025). No full algorithm tournament, no broad
grid search, no broad feature expansion. Nothing is promoted.
