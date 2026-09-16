# NBA Gen 1: ordinary-rest correction and current history

The nine negative Development expectations were linear extrapolation from unsupported calendar gaps. One input-availability correction removes all nine without clipping scores. The complete 2025–26 regular season is now admitted, assessed with a rule frozen before score access, and included in a separately refitted research baseline. No universal accuracy improvement is established.

The saved first-fold Ridge trained on 968 oriented 2019–20 games. HOME rest spanned 0–8 days and AWAY rest 0–9. The nine failed rows supplied 129–287 days since the preceding retained regular game. Dates and subtraction reconcile; excluded postseason games mean these values do not measure all-competition physical rest. Training-median imputation, StandardScaler and Ridge alpha100/SVD applied correctly. Original expectations reproduce exactly at their original batch size, and all 78 coefficient contributions reconcile within 8.53e-14 points. The first corrected fold retains numerically identical medians, scaler means and fitted coefficients: the failure is at input support, not model deserialization or orientation.

The direct original-unit HOME-score coefficients were −0.676016 per HOME gap day and −0.198390 per AWAY gap day, plus a separately retained rest-difference term. All feature values, units, fitted ranges, coefficients and preceding-game identities for every affected game are in [the full diagnosis](diagnosis/nine-negative-ridge-diagnosis.json). Coefficient accounting is associational, not causal.

The single frozen remedy learns a shared maximum from known, non-opener fitting inputs only: 9 days in the initial fold, 12 in subsequent folds and the current model. Season-opening, missing or outside-support gaps become unavailable ordinary rest. `rest_days` becomes missing, `rest_known` and `back_to_back` become zero, and the raw difference is recomputed. Raw values/reasons remain in the audit. Training-only median imputation fills missing values; the difference has its own median. No score clipping, invented hiatus effect or extra hyperparameter search. Seven numeric columns may change; the other 71 and Elo are exact.

| Development population | Games | Margin MAE original → corrected | Total MAE original → corrected | Team-score MSE original → corrected |
|---|---:|---:|---:|---:|
| All Development | 3,538 | 11.406 → 10.949 | 15.976 → 15.423 | 188.538 → 144.295 |
| Both ordinary-rest inputs supported | 3,488 | 10.939 → 10.947 | 15.451 → 15.407 | 144.231 → 143.887 |
| Original nine failures | 9 | 143.678 → 11.260 | 173.182 → 17.518 | 14777.233 → 149.789 |
| Other unavailable-rest games | 41 | 22.126 → 11.027 | 26.122 → 16.280 | 755.498 → 177.810 |

These Development observations were used to diagnose and define the remedy. Ordinary-game inputs stay unchanged; their small forecast changes in later folds come from refitting with the corrected training inputs. Ordinary margin MAE worsens by 0.008 points, while total MAE improves by 0.044. The nine games retain their original predictions in the prior report.

| Date | Away at home | Actual H/A | Original expected H/A | Corrected expected H/A |
|---|---|---:|---:|---:|
| 2020-12-22 | LAC at LAL | 109 / 116 | -0.664 / 102.806 | 123.535 / 117.287 |
| 2020-12-23 | ATL at CHI | 104 / 124 | -136.224 / 96.115 | 125.256 / 120.313 |
| 2020-12-23 | MIL at BOS | 122 / 121 | -2.061 / 103.968 | 122.541 / 118.325 |
| 2020-12-23 | CHO at CLE | 121 / 114 | -136.077 / 97.587 | 125.404 / 121.785 |
| 2020-12-23 | DAL at PHO | 106 / 102 | -2.687 / 101.417 | 121.915 / 115.773 |
| 2020-12-23 | DET at MIN | 111 / 101 | -138.182 / 91.420 | 123.299 / 115.618 |
| 2020-12-23 | SAS at MEM | 119 / 131 | -1.593 / 102.200 | 123.009 / 116.557 |
| 2020-12-23 | MIA at ORL | 113 / 107 | -1.935 / 107.580 | 123.139 / 122.124 |
| 2020-12-23 | UTA at POR | 100 / 120 | -1.451 / 100.140 | 123.151 / 114.496 |

| Assessment | Games | Model for points | Margin MAE | Total MAE | Home / away MAE | Team-score MSE |
|---|---:|---|---:|---:|---:|---:|
| 2023–24 reused diagnostic | 1,225 | Original Ridge100 | 11.074 | 14.779 | 9.381 / 9.247 | 135.624 |
| 2023–24 reused diagnostic | 1,225 | Ordinary-rest Ridge100 | 11.156 | 14.802 | 9.430 / 9.251 | 136.339 |
| 2024–25 reused diagnostic | 1,221 | Original Ridge100 | 10.947 | 14.898 | 9.213 / 9.356 | 135.576 |
| 2024–25 reused diagnostic | 1,221 | Ordinary-rest Ridge100 | 10.952 | 14.903 | 9.225 / 9.349 | 135.700 |
| 2025–26 fixed new assessment | 1,225 | Elo benchmark | 11.484 | 16.319 | 10.233 / 9.914 | 160.835 |
| 2025–26 fixed new assessment | 1,225 | Original Ridge100 | 11.399 | 15.189 | 9.774 / 9.407 | 145.682 |
| 2025–26 fixed new assessment | 1,225 | Ordinary-rest Ridge100 | 11.393 | 15.178 | 9.771 / 9.406 | 145.526 |

The correction slightly worsens both reused seasons. On 2025–26, corrected-minus-original margin MAE is −0.00614 (95% week-block interval −0.02437 to +0.01318); total MAE is −0.01121 (−0.03467 to +0.01412). Both include zero. The 2,000 paired calendar-week resamples use seed 731201; games, not draws, are the observations. Retain the correction for the demonstrated support failure, without a superiority claim.

All three 2025–26 point arms retain identical independent Elo winner probabilities: 832/1,225 correct picks, log loss 0.606258 and binary Brier 0.208971, defined as mean((p_home − home_win)^2). NBA final ties have zero probability. Ridge expected-score and Elo winner channels are independently estimated; their favored sides are not forced to agree and no shared simulation population is claimed.

Population roles: 2019–20 initializes fitting; 2020–21 through 2022–23 are Development. Previously inspected 2023–24 and 2024–25 are reused diagnostics. The 2025–26 regular-season scope and one correction were declared before its outcomes, and the three comparison models were frozen on 6,952 earlier oriented games before score conversion. Every rolling row excludes its target, same-date and later games. This is Category A reconstruction from finalized records, not certified historical information availability or prospective assessment. After assessment, current artifacts were separately refitted on 8,177 oriented games from 8,289 regular-history games spanning 2019–20 through 2025–26.

2025–26 coverage: 1,230 real regular games, 82 for each of 30 teams, from October 21, 2025 through April 12, 2026; 1,225 oriented targets and five neutral history-only games. Four All-Star games, 85 playoff games, six play-in games and four postponed original IDs were excluded before score conversion. The Cup final supplies date-only calendar context. Postponement notes resolve to makeup identities without double-counting.

The SportsDataverse ESPN-derived season export is licensed as data under CC BY 4.0, with retained attribution and changes disclosure; see [source admission](source-review/SOURCE.md). It was acquired September 14, 2026 at 12:52:46.784132 UTC; the release revision was updated September 9 at 05:18:08 UTC. Those are actual export/capture clocks, not invented historical game-publication timestamps. Original FiveThirtyEight CC BY and Neil Paine MIT attribution remain attached to earlier history. No boxes or period scores were acquired or fabricated.

Frozen current configuration: `NBA_GEN1_ELO_WIN_RIDGE_A100_ORDINARY_REST_V1`; Ridge alpha100 expected points, unchanged Elo 1500/K20/home65/scale400/2⁄3 annual regression winner probabilities, 78 score/date features, ordinary-rest support 0–12 days, research-only/unfunded. Model, preprocessing and feature/support identities are in [current refit receipt](current-research/receipt.json). No player availability, injuries, possession efficiencies, lineups or market odds are supplied.

The overtime-dependent joint simulator remains unassessed. Joint draws, CRPS, energy score, prediction intervals and tie-resolution effects are unavailable. A separate point/Elo runner constructs an outcome-free future feature snapshot and requires real source, identity, history-completeness and cutoff evidence. Future forecast status and exact export are recorded in `FUTURE_HANDOFF.md` when available; historical model fit alone is not publication or AISP confirmation.

One feature-assembly attempt failed before predictions because the new Cup-context metadata carried an extra source-ID field. Its execution receipt/code were preserved. A narrow metadata projection and source-ID storage-type conversion repaired the interface; no model, cohort, threshold or outcome selection changed. The successful fixed assessment is retained once.

Focused verification reproduces all corrected historical expectations exactly, preserves 129 prior artifact files and eight unrelated dirty files, and verifies source/cohort/78-feature continuity. Tests of chronology, support, identity and future runner mechanics are software checks, not forecasting observations. No MLB/NFL operations or production authority changed.

Reproducible commands (existing completed stages verify/reuse immutable artifacts):

```powershell
.venv/Scripts/python.exe -B scripts/run_nba_gen1_rest.py --stage development
.venv/Scripts/python.exe -B scripts/run_nba_gen1_rest.py --stage reused-diagnostics
.venv/Scripts/python.exe -B scripts/run_nba_gen1_rest_2026.py --stage freeze
.venv/Scripts/python.exe -B scripts/run_nba_gen1_rest_2026.py --stage assess
.venv/Scripts/python.exe -B scripts/run_nba_gen1_rest_2026.py --stage refit
.venv/Scripts/python.exe -B scripts/verify_nba_gen1_rest.py
```

Next step after this baseline operates: assess its already-frozen future point/Elo forecast with the governed final, retaining the two channels separately. No new challenger is selected from these results.
