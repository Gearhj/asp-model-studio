# ASP NFL M1 Chronological Score-Distribution Modeling Benchmark

**Research disposition:** `RESEARCH_SHADOW` / `NOT_PROMOTED`
**Foundation:** `asp.nfl.gold-data-foundation.v1:sha256:f3e142f05bf9f503168b256db4e05d83c373e94425e1c3147d0817fdf37f3bbb`
**Selection receipt:** `a5862f0bbc76918ecd87ae35dd7935272909f01d55e895168cd958bfb338c6db`

## Executive result

The only fully materialized, point-in-time game-level feature tier was **LONG_HISTORY_CORE**. The OOF-selected recency and model decisions were frozen before final OOT outcome rows were materialized. The selected research challenger is **nfl-m1-xgboost-fixed-research-challenger-2026-shadow**; it remains disconnected from product deployment.

## Population and exclusions

- Pregame Gold: **7,276 games**, 197 ordered predictors, seasons 1999–2025.
  Authority: `gold-table:gold_nfl_game_pregame_v1` / manifest `c13393c738f7629f4f7ff812069fa5cb29402e9bf08690e8d63586dacf9cd295`.
- Play-state Gold: **1,109,384 rows**; preserved for later work and not modeled here.
  Authority: `gold-table:gold_nfl_play_state_v1` / manifest `3bfbe3ea89d3c29f19ac1a194fdef71582806a8e4cbf843aa150fb5db2a4e841`.
- Eligible modeled games: **7,276**; Gold exclusions: `{}`.
- Source schedule exclusions: `{'NO_FINAL_SCORE_TRUTH': 272}` (the 272 rows are prospective 2026 games without final truth).
- Preseason, cancelled/postponed, missing-score, and invalid-identity rows were never silently dropped; every category was audited.

## Exact chronological design

| Fold | Train dates | Train games | Validation dates | Validation games |
|---|---:|---:|---:|---:|
| FOLD_1 | 1999-09-12–2020-02-02 | 5,583 | 2020-09-10–2021-02-07 | 269 |
| FOLD_2 | 1999-09-12–2021-02-07 | 5,852 | 2021-09-09–2022-02-13 | 285 |
| FOLD_3 | 1999-09-12–2022-02-13 | 6,137 | 2022-09-08–2023-02-12 | 284 |
| FOLD_4 | 1999-09-12–2023-02-12 | 6,421 | 2023-09-07–2024-02-11 | 285 |
| FOLD_5 | 1999-09-12–2024-02-11 | 6,706 | 2024-09-05–2025-02-09 | 285 |

Combined OOF: **1,408 games**. Final untouched OOT: **285 games**, 2025-09-04–2026-02-08. Games were grouped and date-atomic; preprocessing and recency weights were refit inside each fold.

## Feature-tier result

`LONG_HISTORY_CORE` is the exact 197-column registered predictor order. Recent 4/8/16 and season-to-date form is already embedded in it. Quarterback, roster/usage, travel/weather, and recent-rich source families were not silently zero-filled or improvised: their pregame game-level timing contracts are not materialized in the current Gold authority. Accordingly, they are reported as unavailable/partial rather than treated as failed models.

## Declared model and simulation configuration

- Fixed seed: **731001**; OOF draws: **2,000** per candidate/game; final OOT draws: **10,000**; paired bootstrap resamples: **2,000**.
- Logistic C grid: `[0.1, 1.0, 10.0]`.
- Score grid: `[{'candidate_id': 'ridge-alpha-10', 'family': 'RIDGE', 'parameters': {'alpha': 10.0}}, {'candidate_id': 'ridge-alpha-100', 'family': 'RIDGE', 'parameters': {'alpha': 100.0}}, {'candidate_id': 'hgb-leaves-15', 'family': 'HIST_GRADIENT_BOOSTING', 'parameters': {'l2_regularization': 1.0, 'learning_rate': 0.05, 'max_iter': 120, 'max_leaf_nodes': 15, 'min_samples_leaf': 20}}, {'candidate_id': 'hgb-leaves-31', 'family': 'HIST_GRADIENT_BOOSTING', 'parameters': {'l2_regularization': 1.0, 'learning_rate': 0.05, 'max_iter': 120, 'max_leaf_nodes': 31, 'min_samples_leaf': 20}}, {'candidate_id': 'extra-trees-leaf-3', 'family': 'EXTRA_TREES', 'parameters': {'max_features': 0.7, 'min_samples_leaf': 3, 'n_estimators': 160}}, {'candidate_id': 'extra-trees-leaf-7', 'family': 'EXTRA_TREES', 'parameters': {'max_features': 0.7, 'min_samples_leaf': 7, 'n_estimators': 160}}, {'candidate_id': 'xgboost-fixed-research-challenger', 'family': 'XGBOOST', 'parameters': {'colsample_bytree': 0.8, 'learning_rate': 0.03, 'max_depth': 3, 'min_child_weight': 5.0, 'n_estimators': 200, 'reg_lambda': 5.0, 'subsample': 0.9}}]`.
- Objectives: `INDEPENDENT_EXPECTED_HOME_AND_AWAY_POINTS_WITH_PAIRED_OOS_RESIDUAL_SIMULATION` and `BINARY_HOME_WIN_LOG_LOSS`.
- Preprocessing: `FOLD_LOCAL_MEDIAN_PLUS_MISSING_INDICATORS_AND_EXPLICIT_CATEGORICAL_MISSING`. Distribution: `CORRELATED_EMPIRICAL_PAIRED_OOS_RESIDUAL_SIMULATION` with common random numbers.

## OOF selection

- Best feature tier: **LONG_HISTORY_CORE**.
- Best recency strategy: **ALL_AVAILABLE_HISTORY** for the best single score family.
- Best single model: **xgboost-fixed-research-challenger** (XGBOOST).
- Best ensemble: **development-cross-fitted-score-win-ensemble**, score components `['EXTRA_TREES', 'HIST_GRADIENT_BOOSTING', 'RIDGE', 'XGBOOST']` with weights `[0.19294147961008903, 0.0011544890924726407, 0.1509161013929482, 0.6549879299044902]`; probability components `['SCORE_ENSEMBLE', 'LOGISTIC_HOME_WIN']` with weights `[0.9635018453380648, 0.036498154661935185]`; calibration `NONE`.
- Second-level weights were genuine chronological cross-fits: a fold's labels never fit the weights used to score that fold. Fold 1 used a predeclared neutral/score-only meta policy because no earlier OOF fold existed.

### OOF metrics

| Candidate | Joint NLL | Win log loss | Brier | Team-points MAE | Margin MAE | Total MAE |
|---|---:|---:|---:|---:|---:|---:|
| development-cross-fitted-score-win-ensemble | 7.985684 | 0.637544 | 0.222952 | 7.456301 | 10.077783 | 10.635126 |
| extra-trees-leaf-3 | 7.959298 | 0.642759 | 0.225531 | 7.501933 | 10.188392 | 10.668787 |
| hgb-leaves-15 | 7.904070 | 0.637199 | 0.222949 | 7.483309 | 10.128077 | 10.677521 |
| ridge-alpha-100 | 7.962275 | 0.645910 | 0.226735 | 7.541095 | 10.224801 | 10.802703 |
| xgboost-fixed-research-challenger | 7.881856 | 0.636976 | 0.222772 | 7.452063 | 10.098244 | 10.616456 |
| elo-team-strength-baseline | — | 0.656031 | 0.231291 | 7.723560 | 10.504333 | 10.908381 |
| home-win-logistic-c-0.1 | — | 0.653463 | 0.230248 | — | — | — |
| league-home-team-prior | — | 0.692061 | 0.249445 | 7.907105 | 10.996045 | 10.908381 |
| rolling-scoring-margin-8 | — | 0.658187 | 0.232811 | 7.628524 | 10.399814 | 10.680664 |

## Final 2025 OOT

| Candidate | Joint NLL | Win log loss | Brier | ECE | Accuracy | Team-points MAE | Margin MAE | Total MAE |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| extra-trees-leaf-3 | 8.340092 | 0.629596 | 0.220364 | 0.059828 | 0.624561 | 7.473503 | 10.101987 | 10.628634 |
| hgb-leaves-15 | 8.284663 | 0.625302 | 0.218742 | 0.047246 | 0.628070 | 7.475001 | 10.062257 | 10.720416 |
| ridge-alpha-100 | 8.243835 | 0.620705 | 0.216093 | 0.054115 | 0.645614 | 7.403085 | 10.056441 | 10.579545 |
| xgboost-fixed-research-challenger | 8.277688 | 0.628770 | 0.220433 | 0.060070 | 0.624561 | 7.446131 | 10.090092 | 10.652762 |
| frozen-score-win-ensemble | 8.381056 | 0.626102 | 0.219141 | 0.059025 | 0.624561 | 7.421229 | 10.035559 | 10.607923 |
| home-win-logistic-c-0.1 | — | 0.631234 | 0.221169 | 0.056779 | 0.628070 | — | — | — |
| league-home-team-prior | — | 0.692863 | 0.249847 | 0.030954 | 0.533333 | 7.912737 | 11.010277 | 11.030095 |
| rolling-scoring-margin-8 | — | 0.645907 | 0.226994 | 0.082796 | 0.652632 | 7.596112 | 10.327067 | 10.723174 |
| elo-team-strength-baseline | — | 0.669285 | 0.236853 | 0.057181 | 0.614035 | 7.741834 | 10.459068 | 11.030095 |

## Historical market comparison

Line semantics remain **`MARKET_SNAPSHOT_TIMING_UNPROVEN`**. Final OOT had 285 complete two-sided moneylines, 285 spreads, and 285 totals. The frozen five-fold OOF population had 1408 complete moneylines, 1408 spreads, and 1408 totals. Market fields were joined only after forecasts; zero market fields were predictors. No ROI or bankroll result is reported.

Sportsbook no-vig home-win log loss: **0.606989**; Brier: **0.210906**. Best selected model minus market log-loss point estimate: **0.023659** with paired 95% interval **[-0.004177, 0.050118]**. The interval crosses zero, so the selected model did not clearly improve on the market benchmark. Model and market probabilities are conditioned on non-tied moneyline settlements; 1 tied final is reported as a push and excluded from log loss.

Final OOT ensemble conditional-on-nonpush home-cover metrics: rows **284**, log loss **0.723437**, Brier **0.263671**, ECE **0.092115**. Conditional-on-nonpush over metrics: rows **285**, log loss **0.705011**, Brier **0.255658**, ECE **0.054103**. Exact modeled spread/total push mass is retained separately; sportsbook no-vig line metrics are in the same compact market table. The governed nflverse spread is interpreted as projected home scoring margin (home cover iff actual home margin exceeds the line).
Final OOT score projection errors on complete line rows: sportsbook spread MAE **9.670175**, ensemble score-margin MAE **10.035559**; sportsbook total MAE **10.422807**, ensemble projected-total MAE **10.607923**.

## Bootstrap and stability

All intervals are paired whole-game bootstrap intervals (candidate minus baseline). A difference is not called clear when its interval crosses zero.

| Comparison | Metric | Difference | Paired 95% interval | Conclusion |
|---|---|---:|---:|---|
| best_single_vs_elo | homeWinLogLoss | -0.040515 | [-0.076316, -0.003520] | CLEAR_CANDIDATE_IMPROVEMENT |
| best_single_vs_elo | meanTeamPointsAbsoluteError | -0.295703 | [-0.514672, -0.070462] | CLEAR_CANDIDATE_IMPROVEMENT |
| best_single_vs_market | homeWinLogLoss | 0.023659 | [-0.004177, 0.050118] | INCONCLUSIVE_INTERVAL_CROSSES_ZERO |
| best_single_vs_rolling | homeWinLogLoss | -0.017137 | [-0.042867, 0.007509] | INCONCLUSIVE_INTERVAL_CROSSES_ZERO |
| best_single_vs_rolling | meanTeamPointsAbsoluteError | -0.149981 | [-0.308987, 0.007037] | INCONCLUSIVE_INTERVAL_CROSSES_ZERO |
| ensemble_vs_best_single | homeWinLogLoss | -0.002668 | [-0.007330, 0.001955] | INCONCLUSIVE_INTERVAL_CROSSES_ZERO |
| ensemble_vs_best_single | meanTeamPointsAbsoluteError | -0.024902 | [-0.054799, 0.004768] | INCONCLUSIVE_INTERVAL_CROSSES_ZERO |

The 2020 sensitivity changed the selected OOF challenger: **False**. The frozen best single model's OOT log loss after excluding 2020 from training was **0.629896**.
Final OOT weekly log loss ranged from **0.484440** (week 2) to **0.870601** (week 22); home-score MAE was **7.268751** and away-score MAE was **7.573708**. These slices were descriptive only and did not affect selection.
Regular season: **272 games**, log loss **0.628083**, team-points MAE **7.378513**. Postseason: **13 games**, log loss **0.584661**, team-points MAE **8.314988**; the postseason sample is descriptive and small.

Detailed week/month/season-phase, regular/postseason, home/away score, favorite/underdog, divisional, rest, venue, total, and model-market disagreement slices are in `docs/nfl_m1/stability_slices.csv`. Quarterback-continuity slicing is explicitly unavailable because starter timing is unproven.

## Distribution methodology

Home and away expected points are modeled jointly through paired, out-of-sample residual simulation. The paired residual bank preserves empirical home/away error correlation; fixed common random numbers make candidate comparisons reproducible. The score/win ensemble changes OUTCOME-GROUP mass by deterministic resampling while preserving conditional score distributions, so its home-win probability remains part of a coherent joint score PMF. Every PMF was checked finite, nonnegative, integral, and unit-mass. Overtime probability is not identified by final-score residuals and is therefore `NOT_SUPPORTED`, not fabricated.

## Research-only 2026 artifact

- Candidate: `nfl-m1-xgboost-fixed-research-challenger-2026-shadow`
- Manifest SHA-256: `ab9c066052b288f3f6162d8f8558e673988fb52172c72fe00aa855aa800a45e9`
- Artifact SHA-256: `7bec06646fd5035380107501d07e139425ac483a47e02e0bbbd56301124fb8fd`
- Training cutoff: `2026-02-08` (complete NFL season 2025; no season-2026 outcomes).
- Status: `RESEARCH_SHADOW`, `NOT_PROMOTED`, not deployed, not published to AI Sports Predictor.

## Limitations

- Only `LONG_HISTORY_CORE` is fully materialized at game level; requested rich tiers await governed pregame derivations.
- Historical market timestamps are unproven, so they are not described as opening or closing lines.
- Residual simulation is empirical and final-score based; it does not model play states or separately identify overtime incidence.
- The sample is one league era with 1,408 development OOF games and 285 final OOT games; paired intervals govern claims.
- 2026 has schedule/roster evidence but no completed outcomes in the foundation, so no 2026 performance claim is made.

## Verification and artifacts

- External OOF prediction ledger: `C:\Users\james\asp-data-staging\nfl\m1-modeling-benchmark-v1\predictions\five-fold-oof-point-predictions.parquet` (`ba8a695675c9222746cc1d6a31608604c7a5e50083574cd6717f1dd34c199a1b`).
- External OOF distribution ledger: `C:\Users\james\asp-data-staging\nfl\m1-modeling-benchmark-v1\predictions\five-fold-oof-distribution-predictions.parquet` (`ea7a5594779d7e88742d9c4f5331514d953162d89ef21d28fca07b608bee1093`).
- External final OOT predictions: `C:\Users\james\asp-data-staging\nfl\m1-modeling-benchmark-v1\predictions\final-2025-oot-game-predictions.parquet` (`6274ef11761ad3c277c3f56cc478da4251e24ff66d78d26265f0a8e62967ace8`).
- Exact OOF joint draws manifest: `C:\Users\james\asp-data-staging\nfl\m1-modeling-benchmark-v1\simulations\five-fold-oof\manifest.json` (`9867335db807ec6b36a24ff7963a67e1b2375f19416212c7b6fa5451bff7e351`).
- Exact final OOT joint draws manifest: `C:\Users\james\asp-data-staging\nfl\m1-modeling-benchmark-v1\simulations\final-oot\manifest.json` (`10a7b02673b14a0c4c92b426e713d69e3e7038d85c29134e8f8b04ae06489705`).
- OOF/final market evaluation: `C:\Users\james\asp-data-staging\nfl\m1-modeling-benchmark-v1\predictions\five-fold-oof-market-comparison.parquet` and `C:\Users\james\asp-data-staging\nfl\m1-modeling-benchmark-v1\predictions\final-2025-market-comparison.parquet`.
- Charts and compact CSV evidence: `docs/nfl_m1/`; the manifest includes aggregate and per-fold metrics/calibration, feature coefficients, source-era missingness, semantic missing-reason counts, market evidence, stability slices, and exact temporal splits.
- Focused NFL M1 tests: **57 passed**, command `python -m pytest -p no:cacheprovider tests/nfl_m1_artifact_test.py tests/nfl_m1_benchmark_test.py tests/nfl_m1_data_temporal_test.py tests/nfl_m1_distribution_metrics_test.py tests/nfl_m1_models_test.py tests/nfl_m1_reporting_test.py -q`.
- The runner contains no promotion or product-registry call, and sportsbook fields are guarded from predictors.

ASP_NFL_M1_MODELING_BENCHMARK_COMPLETE
