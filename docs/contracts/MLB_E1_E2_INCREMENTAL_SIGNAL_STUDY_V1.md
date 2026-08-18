# MLB_E1_E2_INCREMENTAL_SIGNAL_STUDY_V1

Governed **research study** contract for the Phase 4E controlled feature-ablation
experiment. This is not a promoted model and does not change any champion/challenger or
feature-family readiness status.

## Question

Does the governed **E1** pitch-sequence process family, and then the **E2** batter ×
pitcher process-interaction family, improve out-of-time plate-appearance probability
quality on top of the frozen **D3** dynamic-state model — in a practically meaningful and
temporally stable way — and do they specifically repair D3's known STRIKEOUT / WALK_HBP_CI
weakness?

## Branches (feature ablation only)

| Branch | Feature set |
| --- | --- |
| **A** | D3: `CONTEXT_FEATURES` (5) + batter cumulative state `batter_b_*` (14) + pitcher cumulative state `pitcher_b_*` (14) |
| **B** | A + 48 numeric E1 pitch-sequence process features (`MLB_PITCH_SEQUENCE_PROCESS_FEATURES_V1`) |
| **C** | B + 25 E2 process-interaction features (`MLB_BATTER_PITCHER_PROCESS_INTERACTIONS_V1`) |

E1 nominally exposes 50 named columns (25 batter-side + 25 pitcher-side); two of those
(`batter_id`, `pitcher_id`) are identity keys used only for the join, leaving **48 numeric
predictors**. E2 exposes 25 numeric predictors.

## Fixed model policy (no tuning)

- `sklearn.linear_model.LogisticRegression`, true multinomial, `penalty=l2`, `solver=lbfgs`.
- **`C = 0.05`** — the frozen D3 regularization. **No grid search, no C tuning, no class
  weights, no additional algorithms.**
- `max_iter = 2000`, `tol = 1e-7`; fail closed on non-convergence.
- Frozen MLB class order: `STRIKEOUT, WALK_HBP_CI, HOME_RUN, SINGLE, DOUBLE, TRIPLE,
  BIP_OUT, OTHER_REACH`.

## Population alignment (exact, comparable)

All three branches use the **identical 549,479-PA** governed target population — the D3 PA
feature view (`sha256:42884747…`), seasons 2023/2024/2025 = 184104 / 182449 / 182926. E1
and E2 features are attached to that population through the registered FD1 identity bridge
(`retrosheet:player:*` → `canonical_player_uuid`, 1:1 RESOLVED) as a pure per-(player,date)
(E1) and per-(batter,pitcher,date) (E2) lookup. E1 features are a function of the player and
date only; E2 of the batter, pitcher, and date only — verified by within-group uniqueness —
so the lookup reproduces exactly the value a direct materialization on this population would
give, with **no join fan-out and no row loss** (100% match). No rows are dropped; A/B/C are
evaluated on the same rows, labels, seasons, and game clusters.

## Temporal protocol (rolling origin)

- 2023 — development authority (only training data for the 2024 fold).
- 2024 — first frozen out-of-time evaluation fold (train on 2023).
- 2025 — frozen rolling-origin final evaluation (train on 2023+2024). Never used for
  selection; under the fixed policy there is nothing to select.
- All learned preprocessing (mean imputation, standardization) is fit on the training fold
  only. E1/E2 materializations are themselves prior-date leakage-safe.

## Correctness anchor

Branch A must reproduce the frozen D3 log loss within `5e-6`:
`2024 = 1.476588`, `2025 = 1.474100`. If it does not, the study fails closed and emits no
E1/E2 verdict.

## Metrics

- Primary: multiclass log loss; summed multiclass Brier.
- Secondary: top-label ECE, classwise ECE, predicted-probability distribution, per-class
  recall/precision/F1 (descriptive), top-1 accuracy (descriptive only — never a selector).
- Classwise: observed count/rate, mean predicted probability, class-conditional log loss,
  classwise Brier, calibration — for every class, both folds, all branches.
- Catastrophic misses: realized outcomes assigned `< 0.5% / 1% / 2% / 5%`; count, row share,
  share of total log loss, class composition.
- Uncertainty: deterministic whole-`game_id` cluster bootstrap (500 replicates, seed
  20260817) of B−A, C−B, C−A for log loss and Brier; report mean, 95% CI, P(improvement>0).

## Practical-significance bands (relative loss improvement)

`NEGLIGIBLE < 0.1% ≤ SMALL < 0.5% ≤ MEANINGFUL < 2% ≤ LARGE`. A bootstrap CI excluding zero
is necessary but not sufficient; the reported verdict weighs magnitude and temporal
stability, not only significance.

## Verdict enums

- E1: `E1_PREDICTIVE_VALUE_{CONFIRMED,MARGINAL,NOT_CONFIRMED,NEGATIVE}`
- E2: `E2_INCREMENTAL_VALUE_{CONFIRMED,MARGINAL,NOT_CONFIRMED,NEGATIVE}`

`CONFIRMED` requires improvement in **both** 2024 and 2025, a decisive bootstrap
(P(better) ≥ 0.975 both folds) and at least `SMALL` practical magnitude both folds;
`MARGINAL` improves both years decisively but below `SMALL`; `NEGATIVE` is worse in both
years; otherwise `NOT_CONFIRMED`. Readiness status is not affected by the verdict.

## Next-step decision tree

- PATH 1 — E1 and E2 both help → E6 handedness/platoon, then archetypes, then algorithm
  tournament.
- PATH 2 — E1 helps, E2 adds little → E6, then nonlinear algorithm tournament; do not
  expand manual E2.
- PATH 3 — neither helps → stop expanding free pitch-sequence engineering; prioritize E6
  and/or premium-data trial; no E1 V2 without a specific failure hypothesis.
- PATH 4 — only STRIKEOUT improves → retain E1/E2 for K-related component modeling;
  consider specialized/multitask architecture; do not assume universal PA benefit.

## Exclusions

No model promotion, no champion/challenger change, no E6/archetype/handedness/platoon work,
no algorithm tournament, no grid search, no calibration search, no label-based feature
selection, no new feature engineering, no E1 V2, no E2 expansion, no provider/network calls,
no new data acquisition.
