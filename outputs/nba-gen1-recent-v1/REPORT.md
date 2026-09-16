# NBA Gen 1 recent research model: 2019–20 through 2024–25

**Recent data were acquired, the league/Elo benchmarks were assessed, and both Ridge and HGB were fitted. The locked Validation choice is Ridge alpha 100 for expected scores, retaining the unchanged chronological Elo winner-probability channel.** It improves total and margin error in the final 2024–25 Category-A holdout. This is a reduced score/date research baseline with a documented early-fold numerical limitation; it is not a validated joint-distribution model or funded/production release.

The source is Neil Paine’s published NBA Elo data archive, updated from FiveThirtyEight. The selected immutable April 14, 2025 export supplies game dates, season, mirrored teams/scores, neutral/playoff flags and explicit is_home orientation. Its data-repository MIT license permits reuse; Neil Paine’s notice and upstream FiveThirtyEight attribution/CC BY notice are retained. No API-client license is being used as a substitute for data rights. The previously completed FiveThirtyEight approval was not reopened.

One dataset GET downloaded **15,487,867 bytes, $0**. Across this assignment and the completed historical pilot: **2 dataset requests, 33,661,132 bytes, $0**. The previous allowance was not reset. This pinned asset’s one-call allowance is exhausted and reruns use cached bytes. Source-review documentation accounting is separate: seven retained metadata/document GETs (23,700 bytes), one HEAD probe, and browser response sizes not fully retained. No account, trial, provider key, vendor contact, sportsbook credits or spending.

Actual capture: **2026-09-14T02:16:50.818127+00:00**. Physical source SHA-256 `a0d7d27e829ed73d5c132d86ee6e41d4fd07c684c3d23c9c8a8d42f2de9924a5`. The publisher file commit is April 14, 2025; it is not a per-game historical information-availability timestamp. [Source review and terms](SOURCE_REVIEW.md), [bounded acquisition receipt](acquisition.json). The later FiveThirtyEight download route currently returns HTML; the admitted archive was the usable newer alternative. No 2025–26 rows exist in this source.

| Season | Frozen role | Real regular games | Eligible home/away targets | Neutral history only |
|---|---|---:|---:|---:|
| 2019-20 | INITIAL_FIT | 1,059 | 968 | 91 |
| 2020-21 | DEVELOPMENT | 1,080 | 1,080 | 0 |
| 2021-22 | DEVELOPMENT | 1,230 | 1,230 | 0 |
| 2022-23 | DEVELOPMENT | 1,230 | 1,228 | 2 |
| 2023-24 | VALIDATION | 1,230 | 1,225 | 5 |
| 2024-25 | FINAL_CATEGORY_A_HOLDOUT | 1,230 | 1,221 | 9 |

**7,059 real regular-season games** were admitted. Of these, 6,952 have source home/away orientation; 968 initial-fit targets are unscored, leaving **5,984 distinct assessment games**. The 107 neutral regular-season games remain in score/Elo history with zero home advantage and are excluded from home/away targets. The COVID-era shortened seasons retain their actual source populations; no games are invented.

The blank playoff field includes play-in games and NBA Cup finals. Primary NBA calendar cutoffs exclude play-ins/postseason before score access. The 2023-12-09 IND/LAL and 2024-12-17 MIL/OKC Cup finals provide **dates only** for rest/density; their scores are never interpreted or included in ratings, rolling scores or assessment. [Scope classification](scope-classification.json), [identity reconciliation](holdout/reconciliation.json).

Every admitted game has exactly two reciprocal source rows and consistent mirrored scores. Constructed source keys use season/date/unordered team pair; they are not asserted official NBA game IDs. The 30 team codes remain stable across these six seasons. An identity-only overlap check agrees on 7,133 old explicit-home games after documented CHA→CHO and NOH→NOP franchise aliases. It did not reopen prior pilot outcomes or assessment.

Roles and selection rules were frozen from metadata before numerical scores were parsed. All three stages retain pre-access executable hashes. Development uses expanding prior-season fits; Validation receives models fitted before its season; the final holdout receives four already frozen benchmark/finalist models. The old 2014–15 holdout remains an inspected pilot result and is never reused for tuning. [Declaration](declaration.json).

This is **Category A: reconstructed historical development/assessment from finalized records acquired today**. Source publication vintages and original schedule/score revision availability are missing. Recorded dates establish ordering, not proof that the finalized facts were known then. B (certified historical information availability) and C (genuine future pregame capture) are not claimed. No historical publication clock is invented.

The implemented reduced contract has **78 score/date-derived numeric features**, not the original 65 box-feature model. It reuses chronological Elo, shrunk prior/current scoring and allowance, support, regular-season gaps and calendar density, adding earlier margin/total moments and variability. Last 20 earlier games and 10 pseudo-games of prior shrinkage are fixed. All target/same-day/later results are excluded; source Elo/pre/post ratings and probabilities are ignored. Possessions, shooting efficiency, rebounds, turnovers, injuries, players and odds are not fabricated.

Regular-season games supply score/rating histories. Cup dates augment only rest/density. Postseason/preseason dates do not enter these gap features, so they are **gaps since admitted regular-season/context games, not certified all-competition rest**. This distinction is material to the first Ridge fold’s numerical limitation below.

| Assessment season | N | League log loss / Brier | Elo log loss / Brier | League margin / total MAE | Elo margin / total MAE |
|---|---:|---:|---:|---:|---:|
| 2020–21 | 1,080 | 0.68952 / 0.24819 | 0.64949 / 0.22927 | 12.055 / 15.721 | 11.346 / 15.721 |
| 2021–22 | 1,230 | 0.68932 / 0.24809 | 0.63895 / 0.22367 | 12.251 / 16.024 | 11.180 / 16.024 |
| 2022–23 | 1,228 | 0.68232 / 0.24460 | 0.64721 / 0.22746 | 10.945 / 16.093 | 10.200 / 16.093 |
| 2023–24 | 1,225 | 0.68981 / 0.24833 | 0.61583 / 0.21443 | 12.449 / 16.320 | 11.092 / 16.320 |
| 2024–25 | 1,221 | 0.68930 / 0.24808 | 0.61674 / 0.21444 | 12.576 / 15.950 | 11.095 / 15.950 |

Binary NBA Brier is `(pHomeWin − I(home win))²`. Away probability is `1 − pHomeWin`, final tie probability 0. Elo beats league winner log loss and Brier in every assessed season. **Every Ridge/HGB point arm keeps exactly the same Elo winner probability and winner picks. Their identical winner scores are by construction and do not demonstrate a winner-probability improvement from the point models.** No distribution-based winner link or calibration was added.

Development compared only Ridge alpha 10/100 and HGB L2 10/50 with the existing fixed settings. Imputation/scaling stay within each earlier-season training fold; HGB has no random validation split or early stopping. Development selected alpha 100 and L2=50 within their families. Validation selects by mean team-score MSE, requiring at least 1% improvement and at most 2% degradation in either margin or total MAE; near-equal qualifying families prefer Ridge. This proper point-mean gate is separately identified; the original full joint-energy gate remains unassessed.

| Season | Elo margin / total MAE | Ridge α100 margin / total MAE | HGB L2=50 margin / total MAE | Elo / Ridge / HGB team-score MSE |
|---|---:|---:|---:|---:|
| 2020–21 | 11.346 / 15.721 | 12.859 / 17.975 | 11.600 / 15.665 | 150.822 / 300.566 / 149.466 |
| 2021–22 | 11.180 / 16.024 | 11.233 / 14.987 | 11.414 / 15.129 | 152.802 / 141.045 / 144.091 |
| 2022–23 | 10.200 / 16.093 | 10.301 / 15.209 | 10.538 / 15.139 | 148.624 / 137.583 / 139.958 |
| 2023–24 | 11.092 / 16.320 | 11.074 / 14.779 | 11.173 / 15.186 | 157.058 / 135.624 / 142.611 |
| 2024–25 | 11.095 / 15.950 | 10.947 / 14.898 | 11.234 / 15.454 | 149.778 / 135.576 / 144.012 |

Team-score MSE is `mean((home_error² + away_error²)/2)`, equivalent to `mean((margin_error² + total_error²)/4)`. MAEs are points. All candidate rows stay in their original common cohorts, including poor predictions. Full alpha 10 / L2=10 results and home/away errors remain in the stage reports: [Development](development/assessment.json), [Validation](validation/assessment.json), [final holdout](holdout/assessment.json).

| Holdout candidate minus Elo | Margin MAE Δ [95%] | Total MAE Δ [95%] | Team-score MSE Δ [95%] |
|---|---:|---:|---:|
| ridge_a100 | -0.148 [-0.259, -0.038] | -1.052 [-1.356, -0.751] | -14.201 [-17.926, -10.587] |
| hgb_l2_50 | +0.139 [-0.012, +0.301] | -0.496 [-0.863, -0.150] | -5.766 [-9.639, -2.103] |

Negative differences favor the candidate. Existing uncertainty uses 2,000 paired calendar-week block bootstrap replicates, seed 731201. Observed games are assessment units; neither source-vintage uncertainty nor current-era transportability is bounded by these intervals. No simulation sampling precision is being presented as predictive certainty.

**Research baseline decision:** retain the Validation-selected **Ridge alpha 100 expected-score channel with chronological Elo win probabilities**, alongside the unrestricted Elo point benchmark. Ridge reduces Validation team-score MSE 13.6% and holdout MSE 9.5%; holdout total MAE improves 1.052 points and margin MAE 0.148 points. HGB improves totals less and has slightly worse margins. This is a measured recent point-score gain, not a new winner-model gain or a full distribution champion.

**Material limitation:** pooled Development MSE for Ridge alpha 100 is 188.538 versus Elo 150.747. Its 2020–21 fit produced nine nonpositive team-score expectations, minimum −138.182. The first, LAC at LAL on 2020-12-22, follows 130/129-day admitted regular-season gaps versus training ranges 0–8 / 0–9; retained Ridge coefficients contribute −87.030/−25.377 HOME points relative to the training-mean feature vector. This demonstrates extreme linear extrapolation in that case, not an orientation/scaler mismatch. All nine predictions remain unchanged in scoring. The alpha 10 variant had twelve nonpositive expectations in that same initial assessment season. All later assessed seasons and all league/Elo/HGB forecasts had positive expectations; Ridge’s Validation range is 98.129–134.694 and holdout 97.762–127.334. This is evidence of poor first-fold/long-gap support, not justification to clip predictions, change thresholds after holdout or claim unrestricted early-season robustness. [Bounded numerical-risk receipt](ridge-development-numerical-risk.json).

The first-fold risk is attached to the research artifact. Before any later Ridge shadow export, finite positive means and adequate feature/history support must be verified; any unsupported output must remain unavailable. A broader offseason/calendar-treatment correction would require a separately declared comparison on data beyond the already inspected seasons, not silent repair of these receipts. Coefficients in the fitted artifacts describe conditional associations, not causal basketball effects.

After the one-time holdout receipt was saved, the locked Ridge/Elo configuration was **refitted on 6,952 oriented games through 2025-04-13** under a separate identity. [Refit receipt](post-assessment-refit/receipt.json). Ridge artifact SHA-256 `cf8520a1d2aaf412919cc4248704e9fbce9ab373417159d4327625b7eac67dd1`; Elo reference artifact `b27a1a395dfd0109b7ba6eff1d701e3195f5880191cf177948f7a2a7e0f6f5eb`. Refitting does not revise selection, historical predictions or their clocks.

Genuine paired season-forward HOME/AWAY residuals are retained with each model/game in the prediction parquets. They are finalized-record Category-A residuals, not prospective draws. The existing joint simulator still lacks its required overtime-period evidence. It was not run or modified; no tied draws were dropped, overtime adjustment applied, joint-energy/CRPS/interval score computed or validated joint forecast claimed.

**Exact remaining dependency for a genuine future forecast:** the selected export ends with the 2024–25 regular season. A permitted 2025–26 result update plus an actual upcoming NBA schedule/game identity and evidence captured before that game’s cutoff is still required to establish current histories. Historical reconstruction cannot substitute for those captures. A full joint-score package additionally needs the unchanged simulator’s overtime evidence; boxes are optional for this reduced point model but necessary for the separate possession/efficiency feature model. No current source request, schedule, AISP import or display confirmation is fabricated. No future forecast was published.

Reproduce from the repository root; completed stage receipts are reused without new source requests or holdout assessment:

```powershell
.venv/Scripts/python.exe -B scripts/acquire_nba_gen1_recent.py
.venv/Scripts/python.exe -B scripts/declare_nba_gen1_recent.py
.venv/Scripts/python.exe -B scripts/run_nba_gen1_recent.py --stage development
.venv/Scripts/python.exe -B scripts/run_nba_gen1_recent.py --stage validation
.venv/Scripts/python.exe -B scripts/run_nba_gen1_recent.py --stage holdout
.venv/Scripts/python.exe -B scripts/verify_nba_gen1_recent.py
```

A numerical reproduction in a separate output folder must copy the declaration pointer and its original immutable bindings, reuse the same source bytes and preserve the actual repeat clocks. It is a reproduction of an inspected assessment, not a new holdout. Partial-stage folders intentionally refuse silent overwrite.

**Verification:** 28 focused software checks (17 source/features, 8 model/preprocessor, 3 selector) are separate from forecast evidence. Reloading 26 assessed artifacts reproduced all 31,012 stored model-game numerical rows exactly, including bad Development values. All probabilities reconcile, target/date exclusions and frozen stage ordering pass, and the two later refit artifacts are retained. Prior pilot/source attribution and the 8 inherited dirty files remain unchanged. [Verification receipt](verification.json).

NBA remains research-only and unfunded. No MLB/NFL operations, existing model artifacts, accounts, policy, sportsbook credits, scheduler or Claude live-score UI was changed. No purchase, trial or vendor contact occurred.

Attribution: NBA data archive published by Neil Paine, updated from FiveThirtyEight; retain [Neil Paine’s MIT notice](source-review/neil-paine-LICENSE.txt) and original FiveThirtyEight/Basketball-Reference attribution and CC BY4.0 notice. ASP Model Studio reconciles source rows, applies declared scope, reconstructs chronological features and fits independent research models. No publisher endorsement is implied.
