# Team-only MLB show preview research model

Configuration: `MLB_TEAM_LOGISTIC_C1_POISSON_A1_SHOW_PREVIEW_V1`. Model artifact: `model-trained-through-2023.joblib`, SHA `27486409ddc1c65220b0da51b7fa120c7bbfa6703437dc16ea8ab00a93044a03`. This is the assessed 2024 fold model, trained on 7,285 target games in 2021-2023. It is retained without an additional post-assessment refit.

Purpose: research/editorial day-before winner probabilities and expected team runs. No final-pregame, wagering, promotion, stake, position or scheduler authority. Distinct from V18.

Sixteen inputs are defined in FEATURE_CONTRACT.json. Both teams contribute prior-season run scoring, run prevention and win rates shrunk by 40 games to earlier-league rates; their most recent up to60 current-season games are shrunk by20 games to that prior; current and recent support counts are scaled. Prior/current rates use only completed dates earlier than the day-before date. No rest value is invented from incomplete schedule observations. Unknown prior teams use league shrinkage; incomplete history is unavailable, never equivalent to zero games.

One fixed L2 LogisticRegression C=1 supplies pHome; pAway=1-pHome, pTie=0 for decided full MLB games. Independent PoissonRegressor alpha=1 heads supply home and away mean runs. Each estimator has its own StandardScaler fitted only on earlier training targets. No calibration fit. No joint draws, intervals, tail model, or Over/Under probabilities. Probabilities and expected scores must not be described as one simulation population.

| Assessment | Games | Model | Log loss | Binary Brier | AUC | Accuracy | Away MAE | Home MAE | Total MAE |
|---|---:|---|---:|---:|---:|---:|---:|---:|---:|
| 2022 Development | 2428 | benchmark | 0.69098 | 0.24892 | 0.5000 | 53.34% | 2.524 | 2.429 | 3.504 |
| 2022 Development | 2428 | candidate | 0.68028 | 0.24347 | 0.5921 | 57.54% | 2.459 | 2.383 | 3.495 |
| 2023 Development | 2430 | benchmark | 0.69273 | 0.24979 | 0.5000 | 52.10% | 2.558 | 2.487 | 3.628 |
| 2023 Development | 2430 | candidate | 0.68258 | 0.24481 | 0.5804 | 56.13% | 2.490 | 2.443 | 3.615 |
| 2024 reused Validation | 2429 | benchmark | 0.69239 | 0.24962 | 0.5000 | 52.16% | 2.516 | 2.400 | 3.421 |
| 2024 reused Validation | 2429 | candidate | 0.68216 | 0.24454 | 0.5842 | 56.24% | 2.468 | 2.370 | 3.412 |

2024 candidate-minus-benchmark log loss: -0.010229, paired calendar-week 95% interval [-0.016017, -0.004589]. Binary Brier is mean((pHome-homeWin)^2), range0..1. The benchmark estimates league home probability and mean scores on exactly the same earlier target training games. AUC0.5 is its constant-probability consequence.

Total MAE difference -0.009119, interval [-0.025568, 0.008192]: no clear total-accuracy improvement established. All 2,429 Validation rows have unknown preview starters and lineups; there is no supported known-versus-missing personnel contrast.

Early-support Validation: 339 games, candidate LL0.66906 versus0.69710; ECE10 0.0636 versus 0.0473, so aggregate score improvement does not establish uniformly better calibration. Later-support:2,090 games, LL0.68429. Overall ECE10 0.0182; mean pHome 0.5356 versus realized home-win fraction 0.5216. Reliability bin counts/probabilities/outcomes are retained in ASSESSMENT.json. Small-bin noise and missing pitching remain limitations.

2019-2020 are history-only. 2021 is initial training; 2022 and2023 are season-forward Development diagnostics; 2024 is reused Validation, not untouched OOT. 2025 and2026 outcomes were not opened. Historical final records were acquired later and source vintages are uncertified. This supports a qualified research baseline, not a current-season superiority or profitability claim.

Attribution: The information used here was obtained free of charge from and is copyrighted by Retrosheet. Interested parties may contact Retrosheet at www.retrosheet.org.
