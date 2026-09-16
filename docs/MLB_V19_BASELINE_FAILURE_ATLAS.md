# Frozen V18 Development failure atlas for V19 research

The baseline's exact stored raw probabilities yield **log loss 1.4749323734016222** and **summed eight-class Brier 0.7031806519766071** on the matched 494,432 PAs across 6,570 games. These are descriptive, already-used Development observations, not an independent confirmation set or new prospective results.

The [machine-readable atlas](../outputs/mlb-v19-current-state-specialists-v1/baseline-atlas/sha256/d1b27325f5c2d0ac2ef048e282578cca12b5e09cb95827145a428fc594312b73/baseline-failure-atlas.json), SHA-256 `d1b27325f5c2d0ac2ef048e282578cca12b5e09cb95827145a428fc594312b73`, contains all overall, fold, regime, complement, month, batting-team and fielding-team diagnostics; eight-class calibration/reliability and confusion matrices; exposure weighting; fixed exposure bins; and three exact earlier-fold eligibility snapshots. The [manifest](../outputs/mlb-v19-current-state-specialists-v1/baseline-atlas/sha256/095fd951c57f6d7c289a7f9525fe5de1c5762ad82e9614eebd819872f2e8fc4d/manifest.json) has SHA-256 `095fd951c57f6d7c289a7f9525fe5de1c5762ad82e9614eebd819872f2e8fc4d`.

## Population and weighting

The authenticated, physically separated Development cache ends August 6, 2026. It excludes the 7,107 original eligible OOF rows unavailable through the safe physical boundary; the true August 14–27 Final OOT remains unread. The existing outcome-independent hold is preserved. Classes remain `STRIKEOUT`, `WALK_HBP_CI`, `HOME_RUN`, `SINGLE`, `DOUBLE`, `TRIPLE`, `BIP_OUT`, `OTHER_REACH`.

Primary metrics give one weight to each observed PA: frequent players and longer games contribute in proportion to actual observed exposure. They do **not** reweight an observation by its historical-prior denominator. Equal-game weighting first averages PA loss within each game, then averages games equally: log loss **1.4686716171494238**, Brier **0.7008458642771244**. For subgroup equal-game metrics, only that subgroup's PAs within a game are averaged. Distinct games appear in multiple overlapping regimes; regime counts must not be summed.

This atlas uses raw V18 probabilities. Equal chronological calibration and paired candidate-minus-baseline intervals belong to the final matched candidate evaluation. It would be invalid to compare these raw figures selectively against an evaluation-fitted or differently calibrated challenger.

## Five chronological folds

| Fold | PAs | Games | Raw log loss | Raw Brier |
|---|---:|---:|---:|---:|
| 1 | 99,780 | 1,330 | 1.4803167017 | 0.7037020401 |
| 2 | 100,267 | 1,338 | 1.4800885143 | 0.7055720791 |
| 3 | 99,926 | 1,327 | 1.4665179569 | 0.7001997240 |
| 4 | 100,302 | 1,327 | 1.4750876460 | 0.7045961926 |
| 5 | 94,157 | 1,248 | 1.4725003267 | 0.7017371619 |

The machine artifact retains the full per-fold reliability bins and hard-label confusion matrix, not merely these two averages. No model was fit or reloaded to produce this atlas; the separate baseline-reproduction receipt establishes exact saved-estimator reproduction.

## Early season, cold start and fixed regimes

| Pregame-defined recorded regime | PAs | Games containing regime PAs | Raw log loss | Raw Brier |
|---|---:|---:|---:|---:|
| First 30 season days | 70,515 | 933 | 1.4815052226 | 0.7070327599 |
| Batter annual prior missing | 36,991 | 4,864 | 1.4692558767 | 0.7039647286 |
| Pitcher annual prior missing | 48,890 | 3,475 | 1.4898334755 | 0.7095789978 |
| Batter recorded rolling exposure 1–99 PA | 25,192 | 4,463 | 1.4624000052 | 0.7038434492 |
| Pitcher recorded rolling exposure 1–249 BF | 76,211 | 5,240 | 1.4938065165 | 0.7119142370 |
| Batter zero recorded rolling observations | 944 | 291 | 1.4931238919 | 0.7136405153 |
| Pitcher zero recorded rolling observations | 4,791 | 459 | 1.5045677098 | 0.7122402694 |
| Known-handedness platoon advantage | 273,508 | 6,568 | 1.4839435676 | 0.7055718456 |
| Batting travel/short-rest proxy | 8,239 | 204 | 1.4609326911 | 0.6981640757 |
| Fielding travel/short-rest proxy | 8,082 | 204 | 1.4521705197 | 0.6942003729 |
| Same-division alignment | 155,641 | 2,069 | 1.4729083572 | 0.7024074921 |
| Historical relief-role prior: observed GS/G below 0.5 | 195,171 | 6,552 | 1.4789046850 | 0.7068188885 |

These definitions use the fixed predeclared registry, not the realized score, PA outcome, inning or bases. Missing annual authority does not establish no career experience or rookie identity. Historical GS/G does not identify the role actually performed that game. Schedule-start rest proxies are not measured recovery.

Early-season evaluation is uneven across chronological folds: 21,382 / 19,338 / 1,090 / 28,705 / **0** PAs. Fold 3 has only 15 early-season games; fold 5 has none. An apparent overall early-season benefit cannot be presented as five independent seasonal replications.

## Persistent versus transient patterns

Specialist eligibility is replayed unchanged from the declaration: at least two earlier folds each with 2,000 PAs and 100 games; pooled three months and ten teams; consistent excess loss of at least 0.01 or consistent class residual magnitude of at least 0.005. Selection is capped at two and uses **earlier V18 OOF predictions only**.

| Before evaluation fold | Selected from earlier evidence | Interpretation |
|---|---|---|
| 3 | Platoon advantage; early season | Earlier folds support these declared diagnostic conditions. |
| 4 | Platoon advantage; early season | Fold 3 has inadequate early-season size, so earlier adequate seasons determine eligibility. |
| 5 | Platoon advantage; low-exposure batter | Early-season directional bias no longer meets persistence; the next eligible regime enters under the fixed ranking. |

Platoon advantage has higher average log loss than its complement in every fold: **+0.02132, +0.01935, +0.01756, +0.02012, +0.02339**. It does **not** show the same material class-residual direction in every fold. A subgroup can have higher log loss because its outcome distribution is intrinsically harder to predict; excess loss alone is not proof of correctable model failure. Specialist out-of-sample improvement must establish that separately.

Low-exposure batters have BIP-out underprediction in folds 1–4: observed minus predicted **+1.91, +0.55, +1.39, +1.13 percentage points**. That qualifies from earlier evidence, but fold 5 reverses to **−0.10 percentage points**. It is a valid earlier-fold research hypothesis, not an enduring five-fold bias.

Annual-prior-missing batters similarly show BIP-out residuals **+1.86, +0.56, +0.62, +0.05, −0.84 percentage points**. Their earlier bias weakens and reverses. They qualify before folds 3 and 4 but are outside the two selected regimes; they no longer qualify before fold 5.

Early-season strikeout overprediction and BIP-out underprediction exceed 0.5 percentage points in the first two adequate folds, but not the later adequate early-season fold. Its failure regime is therefore **transient/unstable**, not confirmed persistence.

Pitcher annual-missing, pitcher low-exposure, zero-observation players, travel/rest, divisional alignment and historical relief propensity do not satisfy the declared persistence/support conditions. Their descriptive subgroup losses remain reported; high loss or a few unusual games do not create extra specialist permission. All-fold atlas review does not change any prior-fold gate or specialist eligibility.

## Calibration and rare outcomes

Bias below is predicted minus observed rate, in percentage points. ECE uses fixed ten probability bins; coarse bins may hide within-bin structure, especially for rare classes.

| Class | Observed count | Observed rate | Predicted rate | Bias, pp | One-v-rest Brier | ECE |
|---|---:|---:|---:|---:|---:|---:|
| STRIKEOUT | 110,400 | 0.223287 | 0.223805 | +0.05185 | 0.169037 | 0.001599 |
| WALK_HBP_CI | 47,452 | 0.095973 | 0.096988 | +0.10156 | 0.085656 | 0.002508 |
| HOME_RUN | 15,040 | 0.030419 | 0.031061 | +0.06424 | 0.029421 | 0.000642 |
| SINGLE | 70,235 | 0.142052 | 0.141866 | −0.01860 | 0.121554 | 0.001675 |
| DOUBLE | 20,846 | 0.042162 | 0.043557 | +0.13956 | 0.040399 | 0.001396 |
| TRIPLE | 1,792 | 0.003624 | 0.003221 | −0.04035 | 0.003612 | 0.000405 |
| BIP_OUT | 224,419 | 0.453893 | 0.451122 | −0.27705 | 0.245003 | 0.005927 |
| OTHER_REACH | 4,248 | 0.008592 | 0.008380 | −0.02121 | 0.008499 | 0.000250 |

Average true-class log loss is 5.74274 for triples and 4.70393 for OTHER_REACH. Sparse outcomes demand honest sample-size reporting and per-class calibration, not elimination or relabeling of the accepted targets.

The maximum-probability hard classifier mostly chooses BIP_OUT: rare classes need not be its argmax to have useful probabilities. For example, the saved confusion matrix has no argmax HOME_RUN/DOUBLE/TRIPLE predictions. This is a hard-label diagnostic, not proof that those probability columns are absent or useless. Probabilistic log loss/Brier and class calibration remain the primary metrics.

## What this atlas cannot establish

Historical pregame participant/ordered-lineup vintages are absent. The available 20 May 2–3, 2026 game-score diagnostics permit only a separately labeled **ORACLE_MECHANICS_SENSITIVITY_NONPREGAME** simulation comparison, not pregame winner/score/margin/total forecasting superiority. No simulation was run for this atlas. Winner calibration, tails, extra-inning calibration and predictive score-interval coverage remain unsupported until a genuinely prospective or historically vintage-valid game cohort exists.

Bullpen fatigue, starter confirmation uncertainty, lineup changes, weather extremes, altitude, game favorite/underdog, true rookie/transaction state and market disagreement are unsupported historical regime families here. Current source supplements cannot be retrospectively inserted into this Development evaluation. No previous 40-game market result is reused as confirmation.

## Reproduction and scope

Run `.venv\Scripts\python.exe scripts\build_mlb_v19_baseline_atlas.py`. It authenticates the existing Development caches, verifies exact PA/game/target alignment and game-atomic folds, joins the outcome-free team map and reads only saved V18 probabilities. It uses the same pure regime/evaluation helpers as the predeclared study. No new candidate predictions are read; no estimator is loaded or fitted; no provider call, AISP write, scheduled-deployment action or sealed-data read occurs.
