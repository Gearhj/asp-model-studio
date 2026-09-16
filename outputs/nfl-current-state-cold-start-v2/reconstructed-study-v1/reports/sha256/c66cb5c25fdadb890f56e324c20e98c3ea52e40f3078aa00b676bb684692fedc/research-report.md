# NFL current-state V2 — completed research report

Run `bd347be16547007eb9ded9878b9650674f2c9c5e52473fd3ab674a9afe4bdd83` · Study completed 2026-09-10T00:03:13.014513+00:00.

RESEARCH_SHADOW / NOT_PROMOTED. M1 is not replaced. No wagering authority or model execution in AISP is granted.

## Bottom line

The completed study used 6,988 reconstructed source games and 1,408 out-of-fold games at each availability lag. All 44 registered fields use A+B evidence treatment, with zero generic median/mode fallbacks. The comparisons below describe finalized historical archives—not genuine historical publication snapshots or proof of production superiority. The current numerical core ends with 2024-season evidence; sealed 2025 was not read. Current roster/depth context is separate and is not a numerical model input.

## Evidence and chronology

| Class / scope | What the evidence supports |
| --- | --- |
| RETROSPECTIVE_RECONSTRUCTED_AS_OF | Historical features, targets, OOF forecasts and metrics from eligible prior events in finalized archives; unknown late corrections remain. |
| OBSERVED_AS_OF | Actually captured current source bytes and timestamps; current saved forecast observation, not observed game outcomes or historical model-input vintages. |
| Current-2026-only supplemental context | Archived roster/depth identities and available named-player priors; no inferred confirmed starter, roster-weighted numerical carry-forward or historical uplift claim. |
| Excluded / unsupported | actual target starter/rookie, coach change, injury, high roster turnover, weather, travel/timezone; sealed 2025, untimed prices and future/target/same-slate outcomes. |

Completion rule: When exact defensible completion time is unavailable, following calendar day at12:00 America/New_York is an explicitly assumed conservative completion upper bound; add48/72h embargo. Never substitute this for an observed publication time.

Cutoff rule: Common season/week slate cutoff before its first game (first game date00:00America/New_York when kickoff unavailable). No target/same-slate outcomes update another forecast.

Source rows potentially exposed to unverified corrections: 6,988 (100.0%). Correction-bias magnitude: unavailable. The 48/72-hour comparison measures the declared availability-mask sensitivity, not revision bias.

## Cohort and warmup

| Quantity | Recorded count |
| --- | --- |
| Source games | 6988 |
| Raw PBP rows | 1230857 |
| Team-game metric rows | 307472 |
| QB-game rows | 17227 |
| 1999 source-only warmup games | 258 |
| Model training begins | 2000 |
| Validation season 2020 | 269 |
| Validation season 2021 | 285 |
| Validation season 2022 | 284 |
| Validation season 2023 | 285 |
| Validation season 2024 | 285 |
| Validation games per lag (same IDs) | 1408 |

The first source season supplies prior history but is not a training-target season. Three schedule-derived historical rows in the prior semantic cohort have no eligible PBP team-game here; no score-only pseudo-exposures were manufactured. The 2020–2024 validation membership is unchanged.

| Excluded historical game | Date | Reason |
| --- | --- | --- |
| 1999_01_BAL_STL | 1999-09-12 | No corresponding eligible reconstructed PBP team-game |
| 2000_03_SD_KC | 2000-09-17 | No corresponding eligible reconstructed PBP team-game |
| 2000_06_BUF_MIA | 2000-10-08 | No corresponding eligible reconstructed PBP team-game |

## Model and treatment method

Numerator/exposure evidence is opponent-adjusted and pooled into league/team/unit priors. Observed zero with positive exposure is data; zero opportunities add no observation. Fold-selected retention provides between-season regression; lagged prior-usage QB evidence is not a target-starter designation. The historical QB-labeled layer is pass-attempt-weighted prior usage grouped by the source passer_player_id; it may include occasional non-QB passers and is not independently verified historical QB-role or target-starter identity. Unavailable linear increments are excluded with an explicit indicator; the nonlinear branch retains native missing values. Neither is a replacement raw median.

| Component | Declared method |
| --- | --- |
| DYNAMIC | Opponent-adjusted exposure-weighted scoring offense/defense baseline. Unit and prior-usage QB states enter the hierarchical and residual components; they are not silently claimed as separate dynamic-baseline effects. |
| HIERARCHICAL | Fold-local standardized prior-state Ridge(alpha40) home/awayscoremodel |
| RESIDUAL | Bounded HGB score residual on structured hierarchicalmean, two targets |
| ENSEMBLE | Convex mixture of HIERARCHICAL andRESIDUAL jointscorelaws, weight learnedonlyfromearlierouterOOFseasons; warmupHIERARCHICALwhen insufficient diversity/history |

Recency scope: Only offseason retention is selected inside the fold; within-season game half-life is fixed at eight games.

Uncertainty scope: Scoring posterior variance and missing-season/source inflation, not full propagated QB/parameter uncertainty or empirically calibrated coverage. This is not a fully propagated Bayesian posterior.

Final selected retention: 0.3500; final residual ensemble weight: 0.6121; disposition: `EARLIER_OOF_ONLY_WEIGHT_FITTED`. Decay is selected on the last training season; paired score residuals come from chronological inner holdout, not in-sample residuals. The ensemble uses earlier outer OOF seasons only and falls back to its declared hierarchical warmup when unsupported. Final-score targets include overtime; the numerical model does not reconstruct an overtime decision process.

### Exact 44-field inventory

Every row below is `A_RECONSTRUCTABLE_WITH_B_SEASON_START_PRIOR`, uses reconstructed evidence, and has `genericMedianOrModeFallback=false`. Full treatment, missingness, uncertainty and exclusion metadata are retained in the model card and inventory artifact.

| Field | Unit | Numerator / measurement | Actual exposure denominator |
| --- | --- | --- | --- |
| home_points_for_season_to_date | points per completed game | final points including overtime | completed team games |
| home_points_against_season_to_date | points per completed game | opponent final points including overtime | completed team games |
| home_offensive_epa_per_play_season_to_date | EPA points per eligible play | sum observed EPA on pass/run plays | pass/run plays with observed EPA |
| home_pass_epa_per_play_season_to_date | EPA points per eligible play | sum observed pass-play EPA | pass plays with observed EPA |
| home_rush_epa_per_play_season_to_date | EPA points per eligible play | sum observed run-play EPA | run plays with observed EPA |
| home_defensive_epa_per_play_season_to_date | EPA points per eligible play | opponent sum observed EPA on pass/run plays | pass/run plays with observed EPA |
| home_defensive_pass_epa_per_play_season_to_date | EPA points per eligible play | opponent sum observed pass-play EPA | pass plays with observed EPA |
| home_defensive_rush_epa_per_play_season_to_date | EPA points per eligible play | opponent sum observed run-play EPA | run plays with observed EPA |
| home_success_rate_season_to_date | probability | sum observed source success on pass/run plays | pass/run plays with observed success |
| home_defensive_success_rate_season_to_date | probability | opponent sum observed source success on pass/run plays | pass/run plays with observed success |
| home_explosive_pass_rate_season_to_date | probability | pass plays gaining at least 20 yards | pass plays with observed yards |
| home_explosive_rush_rate_season_to_date | probability | run plays gaining at least 10 yards | run plays with observed yards |
| home_defensive_explosive_pass_allowed_rate_season_to_date | probability | opponent pass plays gaining at least 20 yards | pass plays with observed yards |
| home_defensive_explosive_rush_allowed_rate_season_to_date | probability | opponent run plays gaining at least 10 yards | run plays with observed yards |
| home_early_down_success_rate_season_to_date | probability | source success on first/second-down pass/run plays | first/second-down pass/run plays with observed success |
| home_third_down_conversion_rate_season_to_date | probability | sum observed third_down_converted | third-down plays with observed conversion flag |
| home_fourth_down_conversion_rate_season_to_date | probability | sum observed fourth_down_converted | fourth-down plays with observed conversion flag |
| home_red_zone_td_play_rate_season_to_date | probability | touchdowns on pass/run plays starting within 20 yards | such red-zone plays with observed touchdown flag |
| home_turnover_rate_season_to_date | probability | plays with interception or lost fumble | possession plays with both turnover flags observed |
| home_sack_rate_season_to_date | probability | observed sacks on quarterback dropbacks | dropbacks with observed sack flag |
| home_penalty_rate_season_to_date | probability | sum observed penalty flag | possession plays with observed penalty flag |
| home_seconds_per_play_season_to_date | seconds per eligible play | sum consecutive-row elapsed game clock on pass/run plays in [0,120] seconds | pass/run plays with supported observed elapsed clock |
| away_points_for_season_to_date | points per completed game | final points including overtime | completed team games |
| away_points_against_season_to_date | points per completed game | opponent final points including overtime | completed team games |
| away_offensive_epa_per_play_season_to_date | EPA points per eligible play | sum observed EPA on pass/run plays | pass/run plays with observed EPA |
| away_pass_epa_per_play_season_to_date | EPA points per eligible play | sum observed pass-play EPA | pass plays with observed EPA |
| away_rush_epa_per_play_season_to_date | EPA points per eligible play | sum observed run-play EPA | run plays with observed EPA |
| away_defensive_epa_per_play_season_to_date | EPA points per eligible play | opponent sum observed EPA on pass/run plays | pass/run plays with observed EPA |
| away_defensive_pass_epa_per_play_season_to_date | EPA points per eligible play | opponent sum observed pass-play EPA | pass plays with observed EPA |
| away_defensive_rush_epa_per_play_season_to_date | EPA points per eligible play | opponent sum observed run-play EPA | run plays with observed EPA |
| away_success_rate_season_to_date | probability | sum observed source success on pass/run plays | pass/run plays with observed success |
| away_defensive_success_rate_season_to_date | probability | opponent sum observed source success on pass/run plays | pass/run plays with observed success |
| away_explosive_pass_rate_season_to_date | probability | pass plays gaining at least 20 yards | pass plays with observed yards |
| away_explosive_rush_rate_season_to_date | probability | run plays gaining at least 10 yards | run plays with observed yards |
| away_defensive_explosive_pass_allowed_rate_season_to_date | probability | opponent pass plays gaining at least 20 yards | pass plays with observed yards |
| away_defensive_explosive_rush_allowed_rate_season_to_date | probability | opponent run plays gaining at least 10 yards | run plays with observed yards |
| away_early_down_success_rate_season_to_date | probability | source success on first/second-down pass/run plays | first/second-down pass/run plays with observed success |
| away_third_down_conversion_rate_season_to_date | probability | sum observed third_down_converted | third-down plays with observed conversion flag |
| away_fourth_down_conversion_rate_season_to_date | probability | sum observed fourth_down_converted | fourth-down plays with observed conversion flag |
| away_red_zone_td_play_rate_season_to_date | probability | touchdowns on pass/run plays starting within 20 yards | such red-zone plays with observed touchdown flag |
| away_turnover_rate_season_to_date | probability | plays with interception or lost fumble | possession plays with both turnover flags observed |
| away_sack_rate_season_to_date | probability | observed sacks on quarterback dropbacks | dropbacks with observed sack flag |
| away_penalty_rate_season_to_date | probability | sum observed penalty flag | possession plays with observed penalty flag |
| away_seconds_per_play_season_to_date | seconds per eligible play | sum consecutive-row elapsed game clock on pass/run plays in [0,120] seconds | pass/run plays with supported observed elapsed clock |

### Recorded treatment coverage

Counts below are game × semantic-field cells, reported once per fold because the components share their treatment state. The separate excluded-incremental count also covers supplemental inputs and is not an additional mutually exclusive 44-field branch.

| Lag | Validation season | Games | Prior-only cells | Current-evidence cells | Unknown-source cells | Excluded incremental cells |
| --- | --- | --- | --- | --- | --- | --- |
| 48 | 2020 | 269 | 792 | 11044 | 0 | 0 |
| 48 | 2021 | 285 | 748 | 11792 | 0 | 0 |
| 48 | 2022 | 284 | 749 | 11747 | 0 | 0 |
| 48 | 2023 | 285 | 749 | 11791 | 0 | 0 |
| 48 | 2024 | 285 | 748 | 11792 | 0 | 0 |
| 72 | 2020 | 269 | 1364 | 10472 | 0 | 0 |
| 72 | 2021 | 285 | 1364 | 11176 | 0 | 0 |
| 72 | 2022 | 284 | 1365 | 11131 | 0 | 0 |
| 72 | 2023 | 285 | 1365 | 11175 | 0 | 0 |
| 72 | 2024 | 285 | 1320 | 11220 | 0 | 0 |

The turnover definition deliberately requires both flags to be observed rather than converting missing flags into zero. Historical EPA is the provider-derived historical label, not a newly fold-trained EPA model. Clock evidence is elapsed source game clock, not a fitted legal play-duration process. No historical target-game starters, roster, injuries, venue/weather or market prices are introduced.

## Full-season candidate comparison

Lower log loss, Brier and MAE are better. Brier is the sum across away/tie/home classes. The new candidates are raw distributions; no fitted calibration is applied to them. All numbers are saved OOF results on the same validation game identities.

| Pipeline | Games | Log loss | Brier Σ3 | Home ECE | Home MAE | Away MAE | Margin MAE | Total MAE |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| DYNAMIC_LAG48 | 1408 | 0.6986 | 0.4705 | 0.0457 | 7.6484 | 7.5586 | 10.4542 | 10.6805 |
| HIERARCHICAL_LAG48 | 1408 | 0.6807 | 0.4529 | 0.0337 | 7.5995 | 7.4063 | 10.1636 | 10.6733 |
| RESIDUAL_LAG48 | 1408 | 0.6803 | 0.4524 | 0.0262 | 7.6170 | 7.4318 | 10.1944 | 10.6867 |
| ENSEMBLE_LAG48 | 1408 | 0.6805 | 0.4527 | 0.0322 | 7.6081 | 7.4127 | 10.1624 | 10.6776 |
| DYNAMIC_LAG72 | 1408 | 0.6982 | 0.4703 | 0.0489 | 7.6685 | 7.5646 | 10.4648 | 10.6996 |
| HIERARCHICAL_LAG72 | 1408 | 0.6809 | 0.4538 | 0.0251 | 7.6323 | 7.4243 | 10.2018 | 10.6988 |
| RESIDUAL_LAG72 | 1408 | 0.6785 | 0.4524 | 0.0289 | 7.6245 | 7.4433 | 10.1652 | 10.7275 |
| ENSEMBLE_LAG72 | 1408 | 0.6796 | 0.4532 | 0.0276 | 7.6376 | 7.4256 | 10.1678 | 10.7089 |

### Saved M1 / HGB-T2 / C2 / C3 comparators

These saved recipes retain their legacy prior-date availability treatment; they were not retrained under the new 48/72-hour embargo. Saved chronological calibrations are reused where present, without refitting. Differences therefore cannot be attributed solely to the 44-field change.

| Reference | Games | Log loss | Brier Σ3 | Home ECE | Home MAE | Away MAE | Margin MAE | Total MAE |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| M1_RECIPE_FOLD_REFIT raw | 1408 | 0.6749 | 0.4488 | 0.0298 | 7.4745 | 7.4290 | 10.0699 | 10.6270 |
| M1_RECIPE_FOLD_REFIT saved calibrated | 1408 | 0.6653 | 0.4529 | 0.0374 | 7.4745 | 7.4290 | 10.0699 | 10.6270 |
| HGB_T2 raw | 1408 | 0.6748 | 0.4489 | 0.0211 | 7.4865 | 7.4737 | 10.1357 | 10.6985 |
| HGB_T2 saved calibrated | 1408 | 0.6621 | 0.4519 | 0.0318 | 7.4865 | 7.4737 | 10.1357 | 10.6985 |
| C2 raw | 1408 | 0.6740 | 0.4483 | 0.0206 | 7.4779 | 7.4392 | 10.0945 | 10.6076 |
| C2 saved calibrated | 1408 | 0.6624 | 0.4516 | 0.0277 | 7.4779 | 7.4392 | 10.0945 | 10.6076 |
| C3 raw | 1408 | 0.6742 | 0.4482 | 0.0208 | 7.4852 | 7.4421 | 10.0944 | 10.6019 |
| C3 saved calibrated | 1408 | 0.6618 | 0.4510 | 0.0281 | 7.4852 | 7.4421 | 10.0944 | 10.6019 |

## Early-season calibration and distribution coverage

Classwise intercept/slope are diagnostic fits only, not deployed calibrators. A missing diagnostic is not a successful fit. Coverage targets 90%; sharpness is interval width in score points. Week-1 inference has few season/week blocks and is descriptive. All class reliability bins, tie diagnostics, key-number masses, CRPS, home/away coverage and subgroup metrics are included in the model card.

| Pipeline | Cohort | N | Log loss | Home ECE | Home intercept | Home slope | Diagnostic status | Margin 90% coverage | Total 90% coverage | Margin width | Total width |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| DYNAMIC_LAG48 | WEEK_1 | 80 | 0.7358 | 0.1183 | -0.4376 | 1.9669 | DESCRIPTIVE_DIAGNOSTIC | 0.8875 | 0.9500 | 44.6337 | 43.5800 |
| DYNAMIC_LAG48 | WEEKS_1_4 | 319 | 0.7252 | 0.0812 | -0.3266 | 1.5350 | DESCRIPTIVE_DIAGNOSTIC | 0.8903 | 0.9185 | 44.5592 | 43.4129 |
| DYNAMIC_LAG48 | WEEKS_5_8 | 290 | 0.6919 | 0.0906 | -0.1699 | 1.6413 | DESCRIPTIVE_DIAGNOSTIC | 0.8793 | 0.8966 | 44.4219 | 43.2950 |
| DYNAMIC_LAG48 | FULL_SEASON | 1408 | 0.6986 | 0.0457 | -0.1798 | 1.6871 | DESCRIPTIVE_DIAGNOSTIC | 0.8892 | 0.8970 | 44.3917 | 43.3132 |
| HIERARCHICAL_LAG48 | WEEK_1 | 80 | 0.7379 | 0.0706 | -0.0054 | 0.7614 | DESCRIPTIVE_DIAGNOSTIC | 0.9000 | 0.9500 | 43.4912 | 44.3456 |
| HIERARCHICAL_LAG48 | WEEKS_1_4 | 319 | 0.7203 | 0.0446 | -0.0206 | 0.6996 | DESCRIPTIVE_DIAGNOSTIC | 0.9060 | 0.9404 | 43.4489 | 44.2284 |
| HIERARCHICAL_LAG48 | WEEKS_5_8 | 290 | 0.6651 | 0.0679 | 0.1020 | 0.9264 | DESCRIPTIVE_DIAGNOSTIC | 0.8897 | 0.9207 | 43.3964 | 44.1255 |
| HIERARCHICAL_LAG48 | FULL_SEASON | 1408 | 0.6807 | 0.0337 | 0.1136 | 0.8586 | DESCRIPTIVE_DIAGNOSTIC | 0.8977 | 0.9077 | 43.3047 | 44.0968 |
| RESIDUAL_LAG48 | WEEK_1 | 80 | 0.7353 | 0.0947 | -0.0080 | 0.7455 | DESCRIPTIVE_DIAGNOSTIC | 0.9000 | 0.9500 | 43.6350 | 44.2819 |
| RESIDUAL_LAG48 | WEEKS_1_4 | 319 | 0.7160 | 0.0536 | -0.0239 | 0.7149 | DESCRIPTIVE_DIAGNOSTIC | 0.9060 | 0.9342 | 43.6740 | 44.0784 |
| RESIDUAL_LAG48 | WEEKS_5_8 | 290 | 0.6652 | 0.0792 | 0.1000 | 0.9107 | DESCRIPTIVE_DIAGNOSTIC | 0.8897 | 0.9207 | 43.5784 | 43.9695 |
| RESIDUAL_LAG48 | FULL_SEASON | 1408 | 0.6803 | 0.0262 | 0.1091 | 0.8510 | DESCRIPTIVE_DIAGNOSTIC | 0.8949 | 0.9048 | 43.4955 | 43.9355 |
| ENSEMBLE_LAG48 | WEEK_1 | 80 | 0.7379 | 0.0675 | -0.0047 | 0.7692 | DESCRIPTIVE_DIAGNOSTIC | 0.9000 | 0.9500 | 43.5425 | 44.3537 |
| ENSEMBLE_LAG48 | WEEKS_1_4 | 319 | 0.7205 | 0.0572 | -0.0234 | 0.7027 | DESCRIPTIVE_DIAGNOSTIC | 0.9060 | 0.9373 | 43.4737 | 44.1561 |
| ENSEMBLE_LAG48 | WEEKS_5_8 | 290 | 0.6657 | 0.0620 | 0.0985 | 0.9285 | DESCRIPTIVE_DIAGNOSTIC | 0.8897 | 0.9207 | 43.4324 | 44.0186 |
| ENSEMBLE_LAG48 | FULL_SEASON | 1408 | 0.6805 | 0.0322 | 0.1097 | 0.8640 | DESCRIPTIVE_DIAGNOSTIC | 0.8963 | 0.9055 | 43.3430 | 44.0080 |
| DYNAMIC_LAG72 | WEEK_1 | 80 | 0.7345 | 0.1184 | -0.4308 | 1.9058 | DESCRIPTIVE_DIAGNOSTIC | 0.9000 | 0.9500 | 44.7556 | 43.5431 |
| DYNAMIC_LAG72 | WEEKS_1_4 | 319 | 0.7245 | 0.0799 | -0.3320 | 1.5960 | DESCRIPTIVE_DIAGNOSTIC | 0.8903 | 0.9216 | 44.6281 | 43.5122 |
| DYNAMIC_LAG72 | WEEKS_5_8 | 290 | 0.6922 | 0.0826 | -0.1748 | 1.5906 | DESCRIPTIVE_DIAGNOSTIC | 0.8897 | 0.9000 | 44.5353 | 43.4550 |
| DYNAMIC_LAG72 | FULL_SEASON | 1408 | 0.6982 | 0.0489 | -0.1829 | 1.6924 | DESCRIPTIVE_DIAGNOSTIC | 0.8899 | 0.8991 | 44.4478 | 43.4093 |
| HIERARCHICAL_LAG72 | WEEK_1 | 80 | 0.7347 | 0.0573 | -0.0217 | 0.7794 | DESCRIPTIVE_DIAGNOSTIC | 0.9000 | 0.9500 | 43.6038 | 44.4300 |
| HIERARCHICAL_LAG72 | WEEKS_1_4 | 319 | 0.7139 | 0.0396 | -0.0211 | 0.7301 | DESCRIPTIVE_DIAGNOSTIC | 0.9060 | 0.9404 | 43.5138 | 44.2549 |
| HIERARCHICAL_LAG72 | WEEKS_5_8 | 290 | 0.6696 | 0.0509 | 0.0987 | 0.9036 | DESCRIPTIVE_DIAGNOSTIC | 0.8897 | 0.9138 | 43.5366 | 44.1884 |
| HIERARCHICAL_LAG72 | FULL_SEASON | 1408 | 0.6809 | 0.0251 | 0.1136 | 0.8669 | DESCRIPTIVE_DIAGNOSTIC | 0.8942 | 0.9041 | 43.4166 | 44.1711 |
| RESIDUAL_LAG72 | WEEK_1 | 80 | 0.7273 | 0.0611 | -0.0254 | 0.8030 | DESCRIPTIVE_DIAGNOSTIC | 0.9000 | 0.9500 | 43.6313 | 44.3175 |
| RESIDUAL_LAG72 | WEEKS_1_4 | 319 | 0.7131 | 0.0718 | -0.0311 | 0.7210 | DESCRIPTIVE_DIAGNOSTIC | 0.9028 | 0.9342 | 43.5618 | 44.1597 |
| RESIDUAL_LAG72 | WEEKS_5_8 | 290 | 0.6678 | 0.0591 | 0.1015 | 0.9058 | DESCRIPTIVE_DIAGNOSTIC | 0.8828 | 0.9207 | 43.6000 | 44.0476 |
| RESIDUAL_LAG72 | FULL_SEASON | 1408 | 0.6785 | 0.0289 | 0.1098 | 0.8760 | DESCRIPTIVE_DIAGNOSTIC | 0.8949 | 0.9027 | 43.4687 | 44.0245 |
| ENSEMBLE_LAG72 | WEEK_1 | 80 | 0.7280 | 0.0670 | -0.0355 | 0.7992 | DESCRIPTIVE_DIAGNOSTIC | 0.9000 | 0.9500 | 43.5456 | 44.4169 |
| ENSEMBLE_LAG72 | WEEKS_1_4 | 319 | 0.7139 | 0.0670 | -0.0388 | 0.7178 | DESCRIPTIVE_DIAGNOSTIC | 0.9028 | 0.9373 | 43.4934 | 44.2481 |
| ENSEMBLE_LAG72 | WEEKS_5_8 | 290 | 0.6688 | 0.0441 | 0.0847 | 0.9033 | DESCRIPTIVE_DIAGNOSTIC | 0.8862 | 0.9207 | 43.5602 | 44.2041 |
| ENSEMBLE_LAG72 | FULL_SEASON | 1408 | 0.6796 | 0.0276 | 0.0978 | 0.8714 | DESCRIPTIVE_DIAGNOSTIC | 0.8949 | 0.9048 | 43.4165 | 44.1411 |

### Saved reference early-season calibration

These diagnostic summaries describe each saved raw or saved-calibrated probability series; score forecasts themselves are not recalibrated by this report.

| Reference | Probability series | Cohort | N | Log loss | Brier Σ3 | Home ECE | Home intercept | Home slope | Status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| M1_RECIPE_FOLD_REFIT | raw | WEEK_1 | 80 | 0.7406 | 0.4970 | 0.1688 | -0.0851 | 0.7871 | DESCRIPTIVE_DIAGNOSTIC |
| M1_RECIPE_FOLD_REFIT | raw | WEEKS_1_4 | 319 | 0.7096 | 0.4735 | 0.0322 | -0.1310 | 0.9176 | DESCRIPTIVE_DIAGNOSTIC |
| M1_RECIPE_FOLD_REFIT | raw | WEEKS_5_8 | 290 | 0.6710 | 0.4524 | 0.0837 | 0.0296 | 0.8947 | DESCRIPTIVE_DIAGNOSTIC |
| M1_RECIPE_FOLD_REFIT | saved calibrated | WEEK_1 | 80 | 0.7566 | 0.4987 | 0.0715 | -0.0190 | 0.6813 | DESCRIPTIVE_DIAGNOSTIC |
| M1_RECIPE_FOLD_REFIT | saved calibrated | WEEKS_1_4 | 319 | 0.6937 | 0.4707 | 0.0442 | -0.0522 | 0.7818 | DESCRIPTIVE_DIAGNOSTIC |
| M1_RECIPE_FOLD_REFIT | saved calibrated | WEEKS_5_8 | 290 | 0.6367 | 0.4424 | 0.0418 | 0.0867 | 0.8927 | DESCRIPTIVE_DIAGNOSTIC |
| HGB_T2 | raw | WEEK_1 | 80 | 0.7556 | 0.5106 | 0.1023 | -0.0804 | 0.6225 | DESCRIPTIVE_DIAGNOSTIC |
| HGB_T2 | raw | WEEKS_1_4 | 319 | 0.7070 | 0.4724 | 0.0490 | -0.1137 | 0.8957 | DESCRIPTIVE_DIAGNOSTIC |
| HGB_T2 | raw | WEEKS_5_8 | 290 | 0.6734 | 0.4549 | 0.0925 | 0.0465 | 0.8515 | DESCRIPTIVE_DIAGNOSTIC |
| HGB_T2 | saved calibrated | WEEK_1 | 80 | 0.7640 | 0.5056 | 0.0735 | -0.0140 | 0.6102 | DESCRIPTIVE_DIAGNOSTIC |
| HGB_T2 | saved calibrated | WEEKS_1_4 | 319 | 0.6934 | 0.4708 | 0.0487 | -0.0351 | 0.8035 | DESCRIPTIVE_DIAGNOSTIC |
| HGB_T2 | saved calibrated | WEEKS_5_8 | 290 | 0.6431 | 0.4479 | 0.0533 | 0.0933 | 0.8927 | DESCRIPTIVE_DIAGNOSTIC |
| C2 | raw | WEEK_1 | 80 | 0.7564 | 0.5019 | 0.1003 | -0.0695 | 0.6746 | DESCRIPTIVE_DIAGNOSTIC |
| C2 | raw | WEEKS_1_4 | 319 | 0.7188 | 0.4821 | 0.0479 | -0.1064 | 0.8330 | DESCRIPTIVE_DIAGNOSTIC |
| C2 | raw | WEEKS_5_8 | 290 | 0.6819 | 0.4601 | 0.0665 | 0.0362 | 0.8194 | DESCRIPTIVE_DIAGNOSTIC |
| C2 | saved calibrated | WEEK_1 | 80 | 0.7674 | 0.5020 | 0.0830 | -0.0171 | 0.5728 | DESCRIPTIVE_DIAGNOSTIC |
| C2 | saved calibrated | WEEKS_1_4 | 319 | 0.6992 | 0.4773 | 0.0413 | -0.0308 | 0.7429 | DESCRIPTIVE_DIAGNOSTIC |
| C2 | saved calibrated | WEEKS_5_8 | 290 | 0.6476 | 0.4497 | 0.0641 | 0.0929 | 0.8276 | DESCRIPTIVE_DIAGNOSTIC |
| C3 | raw | WEEK_1 | 80 | 0.7554 | 0.5007 | 0.1409 | -0.0799 | 0.6995 | DESCRIPTIVE_DIAGNOSTIC |
| C3 | raw | WEEKS_1_4 | 319 | 0.7190 | 0.4811 | 0.0498 | -0.1138 | 0.8336 | DESCRIPTIVE_DIAGNOSTIC |
| C3 | raw | WEEKS_5_8 | 290 | 0.6821 | 0.4602 | 0.0583 | 0.0381 | 0.8173 | DESCRIPTIVE_DIAGNOSTIC |
| C3 | saved calibrated | WEEK_1 | 80 | 0.7618 | 0.5016 | 0.1662 | -0.0257 | 0.5938 | DESCRIPTIVE_DIAGNOSTIC |
| C3 | saved calibrated | WEEKS_1_4 | 319 | 0.7018 | 0.4795 | 0.0664 | -0.0351 | 0.7168 | DESCRIPTIVE_DIAGNOSTIC |
| C3 | saved calibrated | WEEKS_5_8 | 290 | 0.6480 | 0.4501 | 0.0617 | 0.0981 | 0.8270 | DESCRIPTIVE_DIAGNOSTIC |

## Paired log-loss differences and comparisons with M1

Difference = new candidate minus saved reference: negative favors the new candidate on this metric; positive favors the reference. Intervals use 2,000 whole season/week block resamples and are exploratory after Development model selection, not independent confirmation. The primary RESIDUAL_LAG48 comparisons are below; all eight pipelines against every available raw/calibrated reference remain in the model card.

| Reference | Series | Cohort | N | Δ log loss | 95% interval | Blocks | Descriptive reading |
| --- | --- | --- | --- | --- | --- | --- | --- |
| C2 | raw | WEEK_1 | 80 | -0.0211 | [-0.0585, 0.0101] | 5 | interval spans zero |
| C2 | raw | WEEKS_1_4 | 319 | -0.0027 | [-0.0264, 0.0213] | 20 | interval spans zero |
| C2 | raw | WEEKS_5_8 | 290 | -0.0167 | [-0.0370, 0.0047] | 20 | interval spans zero |
| C2 | raw | FULL_SEASON | 1408 | 0.0063 | [-0.0034, 0.0161] | 109 | interval spans zero |
| C3 | raw | WEEK_1 | 80 | -0.0201 | [-0.0648, 0.0163] | 5 | interval spans zero |
| C3 | raw | WEEKS_1_4 | 319 | -0.0030 | [-0.0271, 0.0206] | 20 | interval spans zero |
| C3 | raw | WEEKS_5_8 | 290 | -0.0169 | [-0.0379, 0.0055] | 20 | interval spans zero |
| C3 | raw | FULL_SEASON | 1408 | 0.0061 | [-0.0036, 0.0161] | 109 | interval spans zero |
| HGB_T2 | raw | WEEK_1 | 80 | -0.0203 | [-0.0330, -0.0114] | 5 | lower candidate loss |
| HGB_T2 | raw | WEEKS_1_4 | 319 | 0.0091 | [-0.0155, 0.0344] | 20 | interval spans zero |
| HGB_T2 | raw | WEEKS_5_8 | 290 | -0.0082 | [-0.0300, 0.0154] | 20 | interval spans zero |
| HGB_T2 | raw | FULL_SEASON | 1408 | 0.0055 | [-0.0042, 0.0165] | 109 | interval spans zero |
| M1_RECIPE_FOLD_REFIT | raw | WEEK_1 | 80 | -0.0053 | [-0.0183, 0.0129] | 5 | interval spans zero |
| M1_RECIPE_FOLD_REFIT | raw | WEEKS_1_4 | 319 | 0.0064 | [-0.0158, 0.0266] | 20 | interval spans zero |
| M1_RECIPE_FOLD_REFIT | raw | WEEKS_5_8 | 290 | -0.0059 | [-0.0238, 0.0136] | 20 | interval spans zero |
| M1_RECIPE_FOLD_REFIT | raw | FULL_SEASON | 1408 | 0.0054 | [-0.0028, 0.0138] | 109 | interval spans zero |
| C2 | saved calibrated | WEEK_1 | 80 | -0.0321 | [-0.1222, 0.0296] | 5 | interval spans zero |
| C2 | saved calibrated | WEEKS_1_4 | 319 | 0.0168 | [-0.0170, 0.0457] | 20 | interval spans zero |
| C2 | saved calibrated | WEEKS_5_8 | 290 | 0.0176 | [-0.0035, 0.0396] | 20 | interval spans zero |
| C2 | saved calibrated | FULL_SEASON | 1408 | 0.0179 | [0.0043, 0.0303] | 109 | higher candidate loss |
| C3 | saved calibrated | WEEK_1 | 80 | -0.0265 | [-0.1131, 0.0330] | 5 | interval spans zero |
| C3 | saved calibrated | WEEKS_1_4 | 319 | 0.0142 | [-0.0167, 0.0422] | 20 | interval spans zero |
| C3 | saved calibrated | WEEKS_5_8 | 290 | 0.0171 | [-0.0039, 0.0390] | 20 | interval spans zero |
| C3 | saved calibrated | FULL_SEASON | 1408 | 0.0185 | [0.0059, 0.0305] | 109 | higher candidate loss |
| HGB_T2 | saved calibrated | WEEK_1 | 80 | -0.0287 | [-0.0972, 0.0234] | 5 | interval spans zero |
| HGB_T2 | saved calibrated | WEEKS_1_4 | 319 | 0.0227 | [-0.0088, 0.0533] | 20 | interval spans zero |
| HGB_T2 | saved calibrated | WEEKS_5_8 | 290 | 0.0221 | [-0.0003, 0.0454] | 20 | interval spans zero |
| HGB_T2 | saved calibrated | FULL_SEASON | 1408 | 0.0182 | [0.0066, 0.0306] | 109 | higher candidate loss |
| M1_RECIPE_FOLD_REFIT | saved calibrated | WEEK_1 | 80 | -0.0213 | [-0.0970, 0.0307] | 5 | interval spans zero |
| M1_RECIPE_FOLD_REFIT | saved calibrated | WEEKS_1_4 | 319 | 0.0224 | [-0.0073, 0.0497] | 20 | interval spans zero |
| M1_RECIPE_FOLD_REFIT | saved calibrated | WEEKS_5_8 | 290 | 0.0285 | [0.0111, 0.0460] | 20 | higher candidate loss |
| M1_RECIPE_FOLD_REFIT | saved calibrated | FULL_SEASON | 1408 | 0.0150 | [0.0034, 0.0264] | 109 | higher candidate loss |

Against the saved raw M1 recipe, the primary challenger's full-season mean log loss is higher: Δ=0.0054, 95% interval [-0.0028, 0.0138]. This does not establish production superiority or justify promotion. Other metrics and early-season comparisons may disagree.

## 72-hour minus 48-hour sensitivity

| Component | Matched games | Changed-probability games | Mean \|class Δp\| | Maximum \|class Δp\| | Δ full log loss | 95% interval |
| --- | --- | --- | --- | --- | --- | --- |
| DYNAMIC | 1408 | 1406 | 0.0100 | 0.0850 | -0.0004 | [-0.002586525350701545, 0.0016159028624849424] |
| ENSEMBLE | 1408 | 1408 | 0.0217 | 0.2270 | -0.0009 | [-0.005989887028914672, 0.00418133299743502] |
| HIERARCHICAL | 1408 | 1408 | 0.0184 | 0.1605 | 0.0002 | [-0.004017437087262173, 0.004377134624433597] |
| RESIDUAL | 1408 | 1407 | 0.0246 | 0.2365 | -0.0018 | [-0.00771113880732727, 0.003596765905147138] |

## Current 2026 publication

Published 64 immutable forecasts and 64 joint-score artifacts for 16 forecast events from 16 selected schedule events; 0 explicit skip records. Each published distribution represents 5,000 paired score draws. Forecast summaries and every source reference are in the model card.

The stale 2024-season numerical history is regressed across intervening seasons. Missing sealed 2025 initialization is explicitly recorded; the extra uncertainty is not calibrated. A fresh archive retrieval does not make the underlying team statistics current. Current roster/depth and named-player context is supplemental only: no confirmed current starter, roster-weighted numerical carry-forward, injury, coaching or weather adjustment is claimed. Current-2026 listed-QB context uses the archived source position=QB designation, but remains nonnumerical. The current numerical historical-source guard accepts only 1999–2024; future incorporation of 2026 statistics into the numerical core is not implemented or claimed. Forward archival begins now and is a separate capability.

| Current source family | Recorded status | Observed at | Object effective at | Selected row effective times | Selected QB rows |
| --- | --- | --- | --- | --- | --- |
| depth_charts | OBSERVED_CONTEXT_ONLY_NOT_MODEL_INPUT | 2026-09-09T23:07:57.851895Z | unavailable | 2026-09-08T11:56:57Z | 92 |
| injuries | UNAVAILABLE_AT_FORECAST_CUTOFF | unavailable | unavailable | unavailable | unavailable |
| practice_reports | UNAVAILABLE_AT_FORECAST_CUTOFF | unavailable | unavailable | unavailable | unavailable |
| rosters | OBSERVED_CONTEXT_ONLY_NOT_MODEL_INPUT | 2026-09-09T23:07:57.851895Z | unavailable | unavailable | 119 |
| weather_forecasts | UNAVAILABLE_AT_FORECAST_CUTOFF | unavailable | unavailable | unavailable | unavailable |
| weekly_rosters | OBSERVED_CONTEXT_ONLY_NOT_MODEL_INPUT | 2026-09-09T23:07:57.851895Z | unavailable | unavailable | 119 |

| Engine | Published forecasts |
| --- | --- |
| NFL_CURRENT_STATE_DYNAMIC_V2 | 16 |
| NFL_CURRENT_STATE_ENSEMBLE_V2 | 16 |
| NFL_CURRENT_STATE_HIERARCHICAL_V2 | 16 |
| NFL_CURRENT_STATE_RESIDUAL_V2 | 16 |

### Primary residual research forecasts

Means below are the published empirical joint-law expectations, not a separate unrounded mean estimator. All four engines and uncertainty/source timestamps are retained in the model card. The historical-through date includes the 2024 season's postseason in calendar 2025; the sealed exclusion is the 2025 NFL season.

| Event | Away | Home | Expected away | Expected home | Away win | Tie | Home win | Forecast cutoff UTC | Historical evidence through |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2026_01_NE_SEA | NE | SEA | 14.9578 | 30.7288 | 0.1212 | 0.0096 | 0.8692 | 2026-09-10T00:03:40.556936+00:00 | 2025-02-09 |
| 2026_01_SF_LA | SF | LAR | 16.2512 | 31.5160 | 0.1302 | 0.0096 | 0.8602 | 2026-09-10T00:03:42.289959+00:00 | 2025-02-09 |
| 2026_01_ATL_PIT | ATL | PIT | 15.9260 | 29.9770 | 0.1396 | 0.0136 | 0.8468 | 2026-09-10T00:03:43.941557+00:00 | 2025-02-09 |
| 2026_01_BAL_IND | BAL | IND | 18.9426 | 27.8574 | 0.2380 | 0.0256 | 0.7364 | 2026-09-10T00:03:45.573042+00:00 | 2025-02-09 |
| 2026_01_BUF_HOU | BUF | HOU | 17.6552 | 29.0974 | 0.1790 | 0.0200 | 0.8010 | 2026-09-10T00:03:47.193674+00:00 | 2025-02-09 |
| 2026_01_CHI_CAR | CHI | CAR | 15.8136 | 29.5218 | 0.1434 | 0.0148 | 0.8418 | 2026-09-10T00:03:48.703467+00:00 | 2025-02-09 |
| 2026_01_CLE_JAX | CLE | JAX | 13.8974 | 30.7112 | 0.1072 | 0.0124 | 0.8804 | 2026-09-10T00:03:50.344878+00:00 | 2025-02-09 |
| 2026_01_NO_DET | NO | DET | 13.6508 | 35.0860 | 0.0666 | 0.0064 | 0.9270 | 2026-09-10T00:03:51.882150+00:00 | 2025-02-09 |
| 2026_01_NYJ_TEN | NYJ | TEN | 16.6054 | 29.2576 | 0.1610 | 0.0146 | 0.8244 | 2026-09-10T00:03:53.468062+00:00 | 2025-02-09 |
| 2026_01_TB_CIN | TB | CIN | 17.2836 | 31.6984 | 0.1386 | 0.0080 | 0.8534 | 2026-09-10T00:03:54.991254+00:00 | 2025-02-09 |
| 2026_01_ARI_LAC | ARI | LAC | 16.1764 | 30.4250 | 0.1408 | 0.0086 | 0.8506 | 2026-09-10T00:03:56.667891+00:00 | 2025-02-09 |
| 2026_01_GB_MIN | GB | MIN | 16.8446 | 30.0548 | 0.1522 | 0.0162 | 0.8316 | 2026-09-10T00:03:58.334952+00:00 | 2025-02-09 |
| 2026_01_MIA_LV | MIA | LV | 16.0630 | 29.3120 | 0.1506 | 0.0132 | 0.8362 | 2026-09-10T00:03:59.925503+00:00 | 2025-02-09 |
| 2026_01_WAS_PHI | WAS | PHI | 15.4414 | 32.9060 | 0.1014 | 0.0122 | 0.8864 | 2026-09-10T00:04:01.440265+00:00 | 2025-02-09 |
| 2026_01_DAL_NYG | DAL | NYG | 15.3886 | 29.8448 | 0.1374 | 0.0074 | 0.8552 | 2026-09-10T00:04:03.139417+00:00 | 2025-02-09 |
| 2026_01_DEN_KC | DEN | KC | 15.4578 | 30.9848 | 0.1226 | 0.0138 | 0.8636 | 2026-09-10T00:04:04.691846+00:00 | 2025-02-09 |

Current-slate warning: all 16 primary forecasts favor the home team; saved home-win probabilities range from 0.7364 to 0.9270. This concentration requires review. It is not calibrated confidence, evidence of accuracy or a diagnosed cause; the saved predictions remain unchanged.

The completed handoff records no skipped events.

### Joint-law and independent play-engine limits

Home/away/tie, expected scores, margin, total and score-distribution queries reconcile to the same empirical joint score law. Paired inner-holdout residuals retain score dependence, but nonnegative integer final scores are not constrained to legal scoring sequences. This is not a play/drive simulator; no trajectories, overtime incidence or tactical path is inferred. The independent play engine remains a different generating law.

Saved-law comparison: 16 matched events / 64 event-model rows, status `NOT_COUPLED_NOT_CALIBRATED_TO_MATCH`. Models executed: 0; calibration fits: 0; new play paths: 0. Any disagreement is not an accuracy result, outcome test or wagering edge. Full deltas and differing source timestamps are retained in the model card.

## Fit accounting, runtime and verification

Study runtime: 2252.33 seconds (37.54 minutes). This is the runtime recorded by the study, not an inferred end-to-end duration including source preparation/publication. The table is reconciled against the exact saved fit-event ledger. It covers this completed run only, not unrecorded or separately abandoned attempts.

| Recorded event | Count |
| --- | --- |
| DECAY_EVALUATION_COMPLETE | 33 |
| DECAY_EVALUATION_START | 33 |
| ENSEMBLE_WEIGHT_DISPOSITION | 10 |
| ESTIMATOR_FIT_COMPLETE | 66 |
| ESTIMATOR_FIT_START | 66 |
| FINAL_ENSEMBLE_WEIGHT_DISPOSITION | 1 |
| FINAL_MODEL_RELOAD_VERIFIED | 1 |
| FOLD_COMPLETE | 10 |
| PRIOR_PARAMETER_FIT_COMPLETE | 22 |
| PRIOR_PARAMETER_FIT_START | 22 |
| RESIDUAL_AUTHORITY_FIT_COMPLETE | 33 |
| RESIDUAL_AUTHORITY_FIT_START | 33 |
| SCALER_FIT | 22 |

| Calibration diagnostics accounting | Count |
| --- | --- |
| optimizerStarts | 280 |
| optimizerSuccesses | 280 |
| optimizerFailures | 0 |
| insufficientClassSupport | 80 |

Applied calibrator fits: 0. Generic median fallbacks: 0; generic mode fallbacks: 0. All ten completed folds and the final model have zero recorded serialization mismatches. Diagnostic optimizer failures/insufficient support remain explicitly accounted above; a completed run is not a claim that every calibration diagnostic succeeded. Finalization recorded zero model fits, provider calls and AISP writes, and verified publication checksums/distribution objects. Registration rerun was NO_OP.

## Forward archive and prospective markets

The archival schedule receipt is `ACTIVE` at a 6-hour cadence. Computer on and Codex app running. Scheduling is not a guarantee of uninterrupted capture. Archive already available local source snapshots; no provider acquisition or model execution. Captured observation time is the actual capture time, not backdated source retrieval. Missing families stay unavailable. This creates evidence for future genuine OBSERVED_AS_OF validation; it cannot repair missing historical vintages.

Prospective market status: `PENDING_TIMESTAMPED_MARKET_EVIDENCE`; supplied timestamped quote snapshots: 0. Model-only forecasts remain separate. No untimed price tuning or wagering edge is authorized. The exact export contract is linked below; quote observation and first-availability must precede the frozen forecast cutoff and kickoff. This bounded comparison supports eligible two-way moneylines only; spread/total records may be retained but automated line comparison remains unsupported.

## Claude / AISP import instruction

The following is copied from the completed handoff; this report does not assert that an AISP import has happened:

> Verify the handoff and each forecast/artifact manifest checksum and byte count. Register the separate NFL_CURRENT_STATE_*_V2 research engines and import precomputed forecasts plus NFL_LABS_SCORE_DISTRIBUTION_V1 artifacts by canonical event/model/forecast identity. Keep M1 and play-level engines separate; do not execute models, replace prior forecasts, grant wagering authority, or infer drive/play paths.

## Immutable delivery references

| Artifact | Path | SHA-256 |
| --- | --- | --- |
| Report model card (all saved metrics, intervals and forecast summaries) | [Report model card (all saved metrics, intervals and forecast summaries)](<C:/Users/james/asp-model-studio/outputs/nfl-current-state-cold-start-v2/reconstructed-study-v1/reports/sha256/c49fc76d2dad4177c8ab258740b33c22557a8137f68f2da643d2b71672ae4062/model-card.json>) | c49fc76d2dad4177c8ab258740b33c22557a8137f68f2da643d2b71672ae4062 |
| Completed study | [Completed study](<C:/Users/james/asp-model-studio/outputs/nfl-current-state-cold-start-v2/reconstructed-study-v1/runs/bd347be16547007eb9ded9878b9650674f2c9c5e52473fd3ab674a9afe4bdd83/result.json>) | 29989f3af980fd2cb0fa97096f570ced6950d66b981168d83d97c38243f160e3 |
| Delivery receipt | [Delivery receipt](<C:/Users/james/asp-model-studio/outputs/nfl-current-state-cold-start-v2/reconstructed-study-v1/deliveries/sha256/c0cf12c5c79efe78b239c8158ff628c7adf25133ac21e03880dee74f039a0ce9/delivery.json>) | c0cf12c5c79efe78b239c8158ff628c7adf25133ac21e03880dee74f039a0ce9 |
| Methodology | [Methodology](<C:/Users/james/asp-model-studio/outputs/nfl-current-state-cold-start-v2/reconstructed-study-v1/methodology-contract.json>) | 2b9ee995ad0cb46a2672a129b2cb6672986e2538702e9812aadbf128601b0c92 |
| 44-field inventory | [44-field inventory](<C:/Users/james/asp-model-studio/outputs/nfl-current-state-cold-start-v2/reconstructed-study-v1/runs/bd347be16547007eb9ded9878b9650674f2c9c5e52473fd3ab674a9afe4bdd83/treatment-inventory.json>) | c3a385ba6541899c5437f02cf97269ac82224ec6ba6091ec38b3bf8a61ae2abc |
| Fitted state metadata (no execution) | [Fitted state metadata (no execution)](<C:/Users/james/asp-model-studio/outputs/nfl-current-state-cold-start-v2/reconstructed-study-v1/runs/bd347be16547007eb9ded9878b9650674f2c9c5e52473fd3ab674a9afe4bdd83/final-through2024-lag48/fitted-state.json>) | 2c59350ce94df3a118f1da17249e41ddd1ccbfb62ee7c0b3ea1d57b8a3b3671e |
| Fit receipts | [Fit receipts](<C:/Users/james/asp-model-studio/outputs/nfl-current-state-cold-start-v2/reconstructed-study-v1/runs/bd347be16547007eb9ded9878b9650674f2c9c5e52473fd3ab674a9afe4bdd83/fit-receipts.jsonl>) | d85edc2233c12bdbb11e2deb080fc8cbd2f01437dc99d6aa3787865c16f56be8 |
| Distribution handoff | [Distribution handoff](<C:/Users/james/asp-model-studio/outputs/nfl-current-state-cold-start-v2/reconstructed-study-v1/current-publication/handoffs/sha256/b12b3157dbfcd932a1c5f21988e2fe0611522f8120cf41980e82e797adea6f13/handoff.json>) | b12b3157dbfcd932a1c5f21988e2fe0611522f8120cf41980e82e797adea6f13 |
| Publication manifest | [Publication manifest](<C:/Users/james/asp-model-studio/outputs/nfl-current-state-cold-start-v2/reconstructed-study-v1/current-publication/manifests/sha256/2ef31af5f111c1b429bd355dfbfbd2834fd42ea8b16f14effb1393ee7d4bbbf4/manifest.json>) | 2ef31af5f111c1b429bd355dfbfbd2834fd42ea8b16f14effb1393ee7d4bbbf4 |
| Timestamped quote export contract | [Timestamped quote export contract](<C:/Users/james/asp-model-studio/outputs/nfl-current-state-cold-start-v2/reconstructed-study-v1/prospective-market-comparison/contracts/sha256/d020eb8b0ddb9728a98b58bc17d808d8c87be66378deb83bbd2498c80d25a0a3/aisp-timed-quote-export-contract.json>) | d020eb8b0ddb9728a98b58bc17d808d8c87be66378deb83bbd2498c80d25a0a3 |
| Forward archive schedule receipt | [Forward archive schedule receipt](<C:/Users/james/asp-model-studio/outputs/nfl-current-state-cold-start-v2/reconstructed-study-v1/forward-archive-schedule.json>) | 27fcac8ea772f73ceaa879961eccc6bc1a1090a14cd926063513fb369a94803b |
| Three-game cohort reconciliation | [Three-game cohort reconciliation](<C:/Users/james/asp-model-studio/outputs/nfl-current-state-cold-start-v2/reconstructed-study-v1/cohort-reconciliation.json>) | b4bf3c4ef91cd303517cf05832fa703fe06cf4674c09e9ed0b8a2a06f32c509d |

## What remains scientifically unproven

Genuine historical publication timing and late-correction magnitude; production superiority; target-starter/rookie, injury, coaching, roster-turnover or weather uplift; calibrated current cold-start uncertainty; legal score-path/OT dynamics; and betting value against timestamped, settlement-compatible prices remain unproven. Prospective evidence capture and independent validation are still required. No promotion, champion replacement or wagering activation occurred.
