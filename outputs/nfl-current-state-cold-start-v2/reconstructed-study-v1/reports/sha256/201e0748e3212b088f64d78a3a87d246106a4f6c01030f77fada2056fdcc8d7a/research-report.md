# NFL current-state V2 — partial completion; learned current challenger blocked

Run `bd347be16547007eb9ded9878b9650674f2c9c5e52473fd3ab674a9afe4bdd83` · Study completed 2026-09-10T00:03:13.014513+00:00.

RESEARCH_SHADOW / NOT_PROMOTED. M1 is not replaced. No wagering authority or model execution in AISP is granted.

## Bottom line

Partial completion: the fallback-free historical treatment, Development study and forward archive are implemented. The learned HIERARCHICAL, RESIDUAL and ENSEMBLE current forecasts are BLOCKED and scientifically unusable in the missing-2025 regime because an uncertainty flag also shifted their score means. Only the separate DYNAMIC baseline is admitted, research-only. Do not import the original 64-forecast handoff as the current usable package.

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

Corrective admission: 16 DYNAMIC baseline forecasts admitted; 48 learned event-model forecasts withheld. These are model-specific withholdings, not missing games. The original forecasts, historical OOF results and fit records remain unchanged for audit; no corrective refit or replacement forecast is claimed. [Admission receipt](<C:/Users/james/asp-model-studio/outputs/nfl-current-state-cold-start-v2/reconstructed-study-v1/corrective-admission/supplements/sha256/1cff387543e7401da00cc6f1512444b0c70884948d1f6878f51d8bcdc6843586/admission.json>). [Exact saved contribution diagnostic](<C:/Users/james/asp-model-studio/outputs/nfl-current-state-cold-start-v2/reconstructed-study-v1/corrective-admission/diagnostics/sha256/5a223ec9114c97d35212aa09cdbbe5478c9a92ce1953defb8010addd74cb5acb/diagnostic.json>).

Diagnosed limitation: A sparsely observed training missing-season count entered the learned score mean, not only uncertainty. The current symmetric one-season gap creates an asymmetric +14.130862247907825 home-margin term. Saved moments of the nonnegative integer home flag imply one training value 2 and 6729 zeros; the away flag was constant zero with zero coefficients. This regime is unvalidated. DYNAMIC does not consume the flag in its scoring-only mean. Historical Development results remain unchanged; HIERARCHICAL/RESIDUAL/ENSEMBLE are not usable current challengers under this gap.

| Saved missing-season mean term | Minimum contribution | Maximum contribution |
| --- | --- | --- |
| Home score points | 8.5611 | 8.5611 |
| Away score points | -5.5697 | -5.5697 |
| Home-minus-away margin points | 14.1309 | 14.1309 |

These are saved linear-term contributions, not newly recomputed or corrected forecasts. [Corrective completion, market and registration receipt](<C:/Users/james/asp-model-studio/outputs/nfl-current-state-cold-start-v2/reconstructed-study-v1/corrective-completions/sha256/4b3e56873701ae9d6b04fac7514e65b23ac75d528930ba3f2c03f7f496488f37/completion.json>).

Published 16 immutable forecasts and 16 joint-score artifacts for 16 forecast events from 16 selected schedule events; 48 explicit skip records. Each published distribution represents 5,000 paired score draws. Forecast summaries and every source reference are in the model card.

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

### Admitted dynamic-baseline research forecasts

Means below are the published empirical joint-law expectations, not a separate unrounded mean estimator. Admitted forecast summaries and uncertainty/source timestamps are retained in the model card. The historical-through date includes the 2024 season's postseason in calendar 2025; the sealed exclusion is the 2025 NFL season.

| Event | Away | Home | Expected away | Expected home | Away win | Tie | Home win | Forecast cutoff UTC | Historical evidence through |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2026_01_NE_SEA | NE | SEA | 21.1788 | 24.3486 | 0.4078 | 0.0312 | 0.5610 | 2026-09-10T00:03:40.556936+00:00 | 2025-02-09 |
| 2026_01_SF_LA | SF | LAR | 21.7822 | 24.7242 | 0.4142 | 0.0386 | 0.5472 | 2026-09-10T00:03:42.289959+00:00 | 2025-02-09 |
| 2026_01_ATL_PIT | ATL | PIT | 21.9678 | 24.3586 | 0.4312 | 0.0394 | 0.5294 | 2026-09-10T00:03:43.941557+00:00 | 2025-02-09 |
| 2026_01_BAL_IND | BAL | IND | 23.3062 | 23.8468 | 0.4888 | 0.0122 | 0.4990 | 2026-09-10T00:03:45.573042+00:00 | 2025-02-09 |
| 2026_01_BUF_HOU | BUF | HOU | 22.7024 | 24.0406 | 0.4716 | 0.0180 | 0.5104 | 2026-09-10T00:03:47.193674+00:00 | 2025-02-09 |
| 2026_01_CHI_CAR | CHI | CAR | 22.3054 | 24.0472 | 0.4564 | 0.0290 | 0.5146 | 2026-09-10T00:03:48.703467+00:00 | 2025-02-09 |
| 2026_01_CLE_JAX | CLE | JAX | 21.2596 | 24.1680 | 0.4182 | 0.0312 | 0.5506 | 2026-09-10T00:03:50.344878+00:00 | 2025-02-09 |
| 2026_01_NO_DET | NO | DET | 21.5122 | 25.5636 | 0.3706 | 0.0414 | 0.5880 | 2026-09-10T00:03:51.882150+00:00 | 2025-02-09 |
| 2026_01_NYJ_TEN | NYJ | TEN | 22.1670 | 23.9840 | 0.4540 | 0.0308 | 0.5152 | 2026-09-10T00:03:53.468062+00:00 | 2025-02-09 |
| 2026_01_TB_CIN | TB | CIN | 22.8838 | 24.6826 | 0.4582 | 0.0264 | 0.5154 | 2026-09-10T00:03:54.991254+00:00 | 2025-02-09 |
| 2026_01_ARI_LAC | ARI | LAC | 21.8898 | 24.3506 | 0.4300 | 0.0384 | 0.5316 | 2026-09-10T00:03:56.667891+00:00 | 2025-02-09 |
| 2026_01_GB_MIN | GB | MIN | 22.1760 | 23.9504 | 0.4554 | 0.0308 | 0.5138 | 2026-09-10T00:03:58.334952+00:00 | 2025-02-09 |
| 2026_01_MIA_LV | MIA | LV | 22.0278 | 23.6274 | 0.4642 | 0.0244 | 0.5114 | 2026-09-10T00:03:59.925503+00:00 | 2025-02-09 |
| 2026_01_WAS_PHI | WAS | PHI | 22.1220 | 25.7032 | 0.3894 | 0.0380 | 0.5726 | 2026-09-10T00:04:01.440265+00:00 | 2025-02-09 |
| 2026_01_DAL_NYG | DAL | NYG | 22.0048 | 23.9788 | 0.4480 | 0.0346 | 0.5174 | 2026-09-10T00:04:03.139417+00:00 | 2025-02-09 |
| 2026_01_DEN_KC | DEN | KC | 22.0536 | 23.9752 | 0.4498 | 0.0336 | 0.5166 | 2026-09-10T00:04:04.691846+00:00 | 2025-02-09 |

### Explicit skips

```json
[
  {
    "artifact": {
      "byteCount": 67407,
      "path": "C:\\Users\\james\\asp-model-studio\\outputs\\nfl-current-state-cold-start-v2\\reconstructed-study-v1\\current-publication\\nfl-labs-score-distributions-v2\\sha256\\1b2710486acfce679f8d241767997ec9f7fc2dbc1e90e82a6cf79e78b3c2fe6c\\artifact.json",
      "sha256": "1b2710486acfce679f8d241767997ec9f7fc2dbc1e90e82a6cf79e78b3c2fe6c"
    },
    "disposition": "WITHHELD_FROM_CURRENT_IMPORT_OR_USE_ORIGINAL_OBJECT_PRESERVED",
    "eventId": "2026_01_NE_SEA",
    "forecastId": "nfl-current-state-v2:sha256:b055c2ff943a6f20e34fe184630274d90fee8fa08c028d997735f46a430cee05",
    "modelId": "NFL_CURRENT_STATE_HIERARCHICAL_V2",
    "reason": "MISSING_SEASON_MEAN_EXTRAPOLATION_UNVALIDATED"
  },
  {
    "artifact": {
      "byteCount": 68094,
      "path": "C:\\Users\\james\\asp-model-studio\\outputs\\nfl-current-state-cold-start-v2\\reconstructed-study-v1\\current-publication\\nfl-labs-score-distributions-v2\\sha256\\e7f406822795529d584dab75550a3fadcc87756bb33a043cebe0f993a1f4c8c1\\artifact.json",
      "sha256": "e7f406822795529d584dab75550a3fadcc87756bb33a043cebe0f993a1f4c8c1"
    },
    "disposition": "WITHHELD_FROM_CURRENT_IMPORT_OR_USE_ORIGINAL_OBJECT_PRESERVED",
    "eventId": "2026_01_NE_SEA",
    "forecastId": "nfl-current-state-v2:sha256:d4c09444c1242643a2306faa094593748ebfb3fae16e3ac626f5b83b4de20583",
    "modelId": "NFL_CURRENT_STATE_RESIDUAL_V2",
    "reason": "MISSING_SEASON_MEAN_EXTRAPOLATION_UNVALIDATED"
  },
  {
    "artifact": {
      "byteCount": 78047,
      "path": "C:\\Users\\james\\asp-model-studio\\outputs\\nfl-current-state-cold-start-v2\\reconstructed-study-v1\\current-publication\\nfl-labs-score-distributions-v2\\sha256\\34a43247cd91dcefa8b9a36489d0190eb28a57f4c0c9cb893d3a21fba1581ef7\\artifact.json",
      "sha256": "34a43247cd91dcefa8b9a36489d0190eb28a57f4c0c9cb893d3a21fba1581ef7"
    },
    "disposition": "WITHHELD_FROM_CURRENT_IMPORT_OR_USE_ORIGINAL_OBJECT_PRESERVED",
    "eventId": "2026_01_NE_SEA",
    "forecastId": "nfl-current-state-v2:sha256:f661b0aaab747fae7256f160ef5314cffd6d7cb8217f662f793b9561ace8ff13",
    "modelId": "NFL_CURRENT_STATE_ENSEMBLE_V2",
    "reason": "MISSING_SEASON_MEAN_EXTRAPOLATION_UNVALIDATED"
  },
  {
    "artifact": {
      "byteCount": 67762,
      "path": "C:\\Users\\james\\asp-model-studio\\outputs\\nfl-current-state-cold-start-v2\\reconstructed-study-v1\\current-publication\\nfl-labs-score-distributions-v2\\sha256\\f2ddba149fba74041cad56994fcaca68c1444435b6fc6848ebae5b35c03996e1\\artifact.json",
      "sha256": "f2ddba149fba74041cad56994fcaca68c1444435b6fc6848ebae5b35c03996e1"
    },
    "disposition": "WITHHELD_FROM_CURRENT_IMPORT_OR_USE_ORIGINAL_OBJECT_PRESERVED",
    "eventId": "2026_01_SF_LA",
    "forecastId": "nfl-current-state-v2:sha256:02c8c015e613d9e1854796a852ff2e169d064777d393f449f90f241b1d03253e",
    "modelId": "NFL_CURRENT_STATE_HIERARCHICAL_V2",
    "reason": "MISSING_SEASON_MEAN_EXTRAPOLATION_UNVALIDATED"
  },
  {
    "artifact": {
      "byteCount": 68414,
      "path": "C:\\Users\\james\\asp-model-studio\\outputs\\nfl-current-state-cold-start-v2\\reconstructed-study-v1\\current-publication\\nfl-labs-score-distributions-v2\\sha256\\91e9b795de9864edf0f373efc6afa64c11f05bbefc0a8e42072b0d4899cd5b2b\\artifact.json",
      "sha256": "91e9b795de9864edf0f373efc6afa64c11f05bbefc0a8e42072b0d4899cd5b2b"
    },
    "disposition": "WITHHELD_FROM_CURRENT_IMPORT_OR_USE_ORIGINAL_OBJECT_PRESERVED",
    "eventId": "2026_01_SF_LA",
    "forecastId": "nfl-current-state-v2:sha256:178404bbd99b5e80213acc17d4fb58c1a73034cca96383700a054561cdfd0094",
    "modelId": "NFL_CURRENT_STATE_RESIDUAL_V2",
    "reason": "MISSING_SEASON_MEAN_EXTRAPOLATION_UNVALIDATED"
  },
  {
    "artifact": {
      "byteCount": 78099,
      "path": "C:\\Users\\james\\asp-model-studio\\outputs\\nfl-current-state-cold-start-v2\\reconstructed-study-v1\\current-publication\\nfl-labs-score-distributions-v2\\sha256\\04bf4367c3bb5286588f4fb9ac2ddd4ca769a5b47dacafd984b0612f14787a46\\artifact.json",
      "sha256": "04bf4367c3bb5286588f4fb9ac2ddd4ca769a5b47dacafd984b0612f14787a46"
    },
    "disposition": "WITHHELD_FROM_CURRENT_IMPORT_OR_USE_ORIGINAL_OBJECT_PRESERVED",
    "eventId": "2026_01_SF_LA",
    "forecastId": "nfl-current-state-v2:sha256:ceb5a8d29a7b28141bf9390b6e8ffa4072d031e155c098177e0f0553741ec14f",
    "modelId": "NFL_CURRENT_STATE_ENSEMBLE_V2",
    "reason": "MISSING_SEASON_MEAN_EXTRAPOLATION_UNVALIDATED"
  },
  {
    "artifact": {
      "byteCount": 68922,
      "path": "C:\\Users\\james\\asp-model-studio\\outputs\\nfl-current-state-cold-start-v2\\reconstructed-study-v1\\current-publication\\nfl-labs-score-distributions-v2\\sha256\\302e6a2b2a34a1128c454bfb07555c9de560ef4076142b1274fc7f4c31a6d0cb\\artifact.json",
      "sha256": "302e6a2b2a34a1128c454bfb07555c9de560ef4076142b1274fc7f4c31a6d0cb"
    },
    "disposition": "WITHHELD_FROM_CURRENT_IMPORT_OR_USE_ORIGINAL_OBJECT_PRESERVED",
    "eventId": "2026_01_ATL_PIT",
    "forecastId": "nfl-current-state-v2:sha256:f41f10d25313e5282a5345e6c53057be7f9fd8bcc120cca3e7053bd54ec87333",
    "modelId": "NFL_CURRENT_STATE_HIERARCHICAL_V2",
    "reason": "MISSING_SEASON_MEAN_EXTRAPOLATION_UNVALIDATED"
  },
  {
    "artifact": {
      "byteCount": 69125,
      "path": "C:\\Users\\james\\asp-model-studio\\outputs\\nfl-current-state-cold-start-v2\\reconstructed-study-v1\\current-publication\\nfl-labs-score-distributions-v2\\sha256\\3348cf47a26d1de91ca9c0259b6c720aa0f7456c693977ae5c55255a7bce1513\\artifact.json",
      "sha256": "3348cf47a26d1de91ca9c0259b6c720aa0f7456c693977ae5c55255a7bce1513"
    },
    "disposition": "WITHHELD_FROM_CURRENT_IMPORT_OR_USE_ORIGINAL_OBJECT_PRESERVED",
    "eventId": "2026_01_ATL_PIT",
    "forecastId": "nfl-current-state-v2:sha256:0d9b51464fdc122551c45fa2d5ce9ff31d4cb0340d53c7bce9cbe11af54fd472",
    "modelId": "NFL_CURRENT_STATE_RESIDUAL_V2",
    "reason": "MISSING_SEASON_MEAN_EXTRAPOLATION_UNVALIDATED"
  },
  {
    "artifact": {
      "byteCount": 77584,
      "path": "C:\\Users\\james\\asp-model-studio\\outputs\\nfl-current-state-cold-start-v2\\reconstructed-study-v1\\current-publication\\nfl-labs-score-distributions-v2\\sha256\\1953484ab8f0c6d795ced333dcafa8ffbde3197a27586960f353c181d0bfcb28\\artifact.json",
      "sha256": "1953484ab8f0c6d795ced333dcafa8ffbde3197a27586960f353c181d0bfcb28"
    },
    "disposition": "WITHHELD_FROM_CURRENT_IMPORT_OR_USE_ORIGINAL_OBJECT_PRESERVED",
    "eventId": "2026_01_ATL_PIT",
    "forecastId": "nfl-current-state-v2:sha256:4ce187259454981d540ff5d689c69cf7feeb7c40381341f3bf2e8a2d03f904e3",
    "modelId": "NFL_CURRENT_STATE_ENSEMBLE_V2",
    "reason": "MISSING_SEASON_MEAN_EXTRAPOLATION_UNVALIDATED"
  },
  {
    "artifact": {
      "byteCount": 69752,
      "path": "C:\\Users\\james\\asp-model-studio\\outputs\\nfl-current-state-cold-start-v2\\reconstructed-study-v1\\current-publication\\nfl-labs-score-distributions-v2\\sha256\\7400edb01b152bad9abd68bcacf3fbc5d3ec419cbe31be5cf3e7ec98993bbb62\\artifact.json",
      "sha256": "7400edb01b152bad9abd68bcacf3fbc5d3ec419cbe31be5cf3e7ec98993bbb62"
    },
    "disposition": "WITHHELD_FROM_CURRENT_IMPORT_OR_USE_ORIGINAL_OBJECT_PRESERVED",
    "eventId": "2026_01_BAL_IND",
    "forecastId": "nfl-current-state-v2:sha256:11808cdaf763a5ce8f8f2270836caba28444b96118d2a4b6e0addd2e42775690",
    "modelId": "NFL_CURRENT_STATE_HIERARCHICAL_V2",
    "reason": "MISSING_SEASON_MEAN_EXTRAPOLATION_UNVALIDATED"
  },
  {
    "artifact": {
      "byteCount": 69275,
      "path": "C:\\Users\\james\\asp-model-studio\\outputs\\nfl-current-state-cold-start-v2\\reconstructed-study-v1\\current-publication\\nfl-labs-score-distributions-v2\\sha256\\94366a18dadeacb645b684317ac8ad7f2bb11e132de13d7b3f47de3c23f8d0bf\\artifact.json",
      "sha256": "94366a18dadeacb645b684317ac8ad7f2bb11e132de13d7b3f47de3c23f8d0bf"
    },
    "disposition": "WITHHELD_FROM_CURRENT_IMPORT_OR_USE_ORIGINAL_OBJECT_PRESERVED",
    "eventId": "2026_01_BAL_IND",
    "forecastId": "nfl-current-state-v2:sha256:7d872a6905bd590d375523aa09afaf7240c275285f64c670e5384cf635b1c3c1",
    "modelId": "NFL_CURRENT_STATE_RESIDUAL_V2",
    "reason": "MISSING_SEASON_MEAN_EXTRAPOLATION_UNVALIDATED"
  },
  {
    "artifact": {
      "byteCount": 80199,
      "path": "C:\\Users\\james\\asp-model-studio\\outputs\\nfl-current-state-cold-start-v2\\reconstructed-study-v1\\current-publication\\nfl-labs-score-distributions-v2\\sha256\\c5e2c0de42004c3cebb194f233da5637466a909875fe663389c724c307356d39\\artifact.json",
      "sha256": "c5e2c0de42004c3cebb194f233da5637466a909875fe663389c724c307356d39"
    },
    "disposition": "WITHHELD_FROM_CURRENT_IMPORT_OR_USE_ORIGINAL_OBJECT_PRESERVED",
    "eventId": "2026_01_BAL_IND",
    "forecastId": "nfl-current-state-v2:sha256:4b9216e74d99991b919bfaf9ac702c1d5bd9453f9d561709761011c4c6bb5c1d",
    "modelId": "NFL_CURRENT_STATE_ENSEMBLE_V2",
    "reason": "MISSING_SEASON_MEAN_EXTRAPOLATION_UNVALIDATED"
  },
  {
    "artifact": {
      "byteCount": 68298,
      "path": "C:\\Users\\james\\asp-model-studio\\outputs\\nfl-current-state-cold-start-v2\\reconstructed-study-v1\\current-publication\\nfl-labs-score-distributions-v2\\sha256\\2df68a04d64ab51e8369c01a23d10979e143b9c07cbabc70e1808cfb6bfed65d\\artifact.json",
      "sha256": "2df68a04d64ab51e8369c01a23d10979e143b9c07cbabc70e1808cfb6bfed65d"
    },
    "disposition": "WITHHELD_FROM_CURRENT_IMPORT_OR_USE_ORIGINAL_OBJECT_PRESERVED",
    "eventId": "2026_01_BUF_HOU",
    "forecastId": "nfl-current-state-v2:sha256:145df4e7f2941ac9c918116103969abefe3bc87a5cfa477f2508807a9ec5513d",
    "modelId": "NFL_CURRENT_STATE_HIERARCHICAL_V2",
    "reason": "MISSING_SEASON_MEAN_EXTRAPOLATION_UNVALIDATED"
  },
  {
    "artifact": {
      "byteCount": 70341,
      "path": "C:\\Users\\james\\asp-model-studio\\outputs\\nfl-current-state-cold-start-v2\\reconstructed-study-v1\\current-publication\\nfl-labs-score-distributions-v2\\sha256\\3ee766055c42dcd5c2b1487ea0dade363493a51e0048d469c9d5b5bd8ed7b328\\artifact.json",
      "sha256": "3ee766055c42dcd5c2b1487ea0dade363493a51e0048d469c9d5b5bd8ed7b328"
    },
    "disposition": "WITHHELD_FROM_CURRENT_IMPORT_OR_USE_ORIGINAL_OBJECT_PRESERVED",
    "eventId": "2026_01_BUF_HOU",
    "forecastId": "nfl-current-state-v2:sha256:36f20d8cd726c875cff1bf3a794de0d66eb502d2688cb41a3a4ce3fb7fbeb85f",
    "modelId": "NFL_CURRENT_STATE_RESIDUAL_V2",
    "reason": "MISSING_SEASON_MEAN_EXTRAPOLATION_UNVALIDATED"
  },
  {
    "artifact": {
      "byteCount": 79223,
      "path": "C:\\Users\\james\\asp-model-studio\\outputs\\nfl-current-state-cold-start-v2\\reconstructed-study-v1\\current-publication\\nfl-labs-score-distributions-v2\\sha256\\aefb63adbf5e33b8ee4f61127b45deac9b3c51dec6841be63f475a4227dc4986\\artifact.json",
      "sha256": "aefb63adbf5e33b8ee4f61127b45deac9b3c51dec6841be63f475a4227dc4986"
    },
    "disposition": "WITHHELD_FROM_CURRENT_IMPORT_OR_USE_ORIGINAL_OBJECT_PRESERVED",
    "eventId": "2026_01_BUF_HOU",
    "forecastId": "nfl-current-state-v2:sha256:90f17c2b8d2936e76119729494876585b3522656f30b44fd486615ce9afe506b",
    "modelId": "NFL_CURRENT_STATE_ENSEMBLE_V2",
    "reason": "MISSING_SEASON_MEAN_EXTRAPOLATION_UNVALIDATED"
  },
  {
    "artifact": {
      "byteCount": 68569,
      "path": "C:\\Users\\james\\asp-model-studio\\outputs\\nfl-current-state-cold-start-v2\\reconstructed-study-v1\\current-publication\\nfl-labs-score-distributions-v2\\sha256\\f2c44a5ecd123fa94cdf2e91ab313fc55fd259e0eccdd1d88e472170359299c4\\artifact.json",
      "sha256": "f2c44a5ecd123fa94cdf2e91ab313fc55fd259e0eccdd1d88e472170359299c4"
    },
    "disposition": "WITHHELD_FROM_CURRENT_IMPORT_OR_USE_ORIGINAL_OBJECT_PRESERVED",
    "eventId": "2026_01_CHI_CAR",
    "forecastId": "nfl-current-state-v2:sha256:d8c7744a3f15526a078d49beb19b255c26bd5395361f41fd1b8ff4f3cdf095b4",
    "modelId": "NFL_CURRENT_STATE_HIERARCHICAL_V2",
    "reason": "MISSING_SEASON_MEAN_EXTRAPOLATION_UNVALIDATED"
  },
  {
    "artifact": {
      "byteCount": 68251,
      "path": "C:\\Users\\james\\asp-model-studio\\outputs\\nfl-current-state-cold-start-v2\\reconstructed-study-v1\\current-publication\\nfl-labs-score-distributions-v2\\sha256\\37c80538618c6f3816edbf043c420405fb579314b28a827b21f710807875b838\\artifact.json",
      "sha256": "37c80538618c6f3816edbf043c420405fb579314b28a827b21f710807875b838"
    },
    "disposition": "WITHHELD_FROM_CURRENT_IMPORT_OR_USE_ORIGINAL_OBJECT_PRESERVED",
    "eventId": "2026_01_CHI_CAR",
    "forecastId": "nfl-current-state-v2:sha256:bf7f46a4c5c9cde48215baeb7071b391106da54606baefb4486c403eca5867b5",
    "modelId": "NFL_CURRENT_STATE_RESIDUAL_V2",
    "reason": "MISSING_SEASON_MEAN_EXTRAPOLATION_UNVALIDATED"
  },
  {
    "artifact": {
      "byteCount": 77392,
      "path": "C:\\Users\\james\\asp-model-studio\\outputs\\nfl-current-state-cold-start-v2\\reconstructed-study-v1\\current-publication\\nfl-labs-score-distributions-v2\\sha256\\04d35a16256841ccdaea4721aa80e0f4cd444c59465bc166986081ac90498f60\\artifact.json",
      "sha256": "04d35a16256841ccdaea4721aa80e0f4cd444c59465bc166986081ac90498f60"
    },
    "disposition": "WITHHELD_FROM_CURRENT_IMPORT_OR_USE_ORIGINAL_OBJECT_PRESERVED",
    "eventId": "2026_01_CHI_CAR",
    "forecastId": "nfl-current-state-v2:sha256:f9af0d95b4d108e77e086f02354e193c5285d5b18188ac3afb9ace49906335cb",
    "modelId": "NFL_CURRENT_STATE_ENSEMBLE_V2",
    "reason": "MISSING_SEASON_MEAN_EXTRAPOLATION_UNVALIDATED"
  },
  {
    "artifact": {
      "byteCount": 66999,
      "path": "C:\\Users\\james\\asp-model-studio\\outputs\\nfl-current-state-cold-start-v2\\reconstructed-study-v1\\current-publication\\nfl-labs-score-distributions-v2\\sha256\\9f983f6d20b599c7b3d0634cf6e129f010370b9ecff6d78c766a51ecf2ab8ff5\\artifact.json",
      "sha256": "9f983f6d20b599c7b3d0634cf6e129f010370b9ecff6d78c766a51ecf2ab8ff5"
    },
    "disposition": "WITHHELD_FROM_CURRENT_IMPORT_OR_USE_ORIGINAL_OBJECT_PRESERVED",
    "eventId": "2026_01_CLE_JAX",
    "forecastId": "nfl-current-state-v2:sha256:3792042e280be54727bf0e036507ce61d2c468d0143026696b48945e3ce9cdca",
    "modelId": "NFL_CURRENT_STATE_HIERARCHICAL_V2",
    "reason": "MISSING_SEASON_MEAN_EXTRAPOLATION_UNVALIDATED"
  },
  {
    "artifact": {
      "byteCount": 67483,
      "path": "C:\\Users\\james\\asp-model-studio\\outputs\\nfl-current-state-cold-start-v2\\reconstructed-study-v1\\current-publication\\nfl-labs-score-distributions-v2\\sha256\\c3a58c5a9c30b52b79533c84d40deb173116084f9525667d6c727664f64d5639\\artifact.json",
      "sha256": "c3a58c5a9c30b52b79533c84d40deb173116084f9525667d6c727664f64d5639"
    },
    "disposition": "WITHHELD_FROM_CURRENT_IMPORT_OR_USE_ORIGINAL_OBJECT_PRESERVED",
    "eventId": "2026_01_CLE_JAX",
    "forecastId": "nfl-current-state-v2:sha256:6023002ceab7bbee72be41212282625b4378732be24c1725b7090ce00328ecc2",
    "modelId": "NFL_CURRENT_STATE_RESIDUAL_V2",
    "reason": "MISSING_SEASON_MEAN_EXTRAPOLATION_UNVALIDATED"
  },
  {
    "artifact": {
      "byteCount": 75091,
      "path": "C:\\Users\\james\\asp-model-studio\\outputs\\nfl-current-state-cold-start-v2\\reconstructed-study-v1\\current-publication\\nfl-labs-score-distributions-v2\\sha256\\81d4f0252b3667671f1992c89bb3ca791fba83665d85c86b721906112c5e6106\\artifact.json",
      "sha256": "81d4f0252b3667671f1992c89bb3ca791fba83665d85c86b721906112c5e6106"
    },
    "disposition": "WITHHELD_FROM_CURRENT_IMPORT_OR_USE_ORIGINAL_OBJECT_PRESERVED",
    "eventId": "2026_01_CLE_JAX",
    "forecastId": "nfl-current-state-v2:sha256:6955e6af82c07bfdbd0713f493e6cf6179c9e78d0e989c0f3c70c9e2079efa00",
    "modelId": "NFL_CURRENT_STATE_ENSEMBLE_V2",
    "reason": "MISSING_SEASON_MEAN_EXTRAPOLATION_UNVALIDATED"
  },
  {
    "artifact": {
      "byteCount": 66928,
      "path": "C:\\Users\\james\\asp-model-studio\\outputs\\nfl-current-state-cold-start-v2\\reconstructed-study-v1\\current-publication\\nfl-labs-score-distributions-v2\\sha256\\bdab335b300dcbbe2a720935032da09e472063e035d63450f82e040f6533b285\\artifact.json",
      "sha256": "bdab335b300dcbbe2a720935032da09e472063e035d63450f82e040f6533b285"
    },
    "disposition": "WITHHELD_FROM_CURRENT_IMPORT_OR_USE_ORIGINAL_OBJECT_PRESERVED",
    "eventId": "2026_01_NO_DET",
    "forecastId": "nfl-current-state-v2:sha256:3c481d2f0957d52fe56e385822ac7f4536242b0ac7b27707d472443ba4c68da5",
    "modelId": "NFL_CURRENT_STATE_HIERARCHICAL_V2",
    "reason": "MISSING_SEASON_MEAN_EXTRAPOLATION_UNVALIDATED"
  },
  {
    "artifact": {
      "byteCount": 67962,
      "path": "C:\\Users\\james\\asp-model-studio\\outputs\\nfl-current-state-cold-start-v2\\reconstructed-study-v1\\current-publication\\nfl-labs-score-distributions-v2\\sha256\\181841ddbbb1178a78da749d547cc7ef530cad308163960f59b5ea405bc8bec6\\artifact.json",
      "sha256": "181841ddbbb1178a78da749d547cc7ef530cad308163960f59b5ea405bc8bec6"
    },
    "disposition": "WITHHELD_FROM_CURRENT_IMPORT_OR_USE_ORIGINAL_OBJECT_PRESERVED",
    "eventId": "2026_01_NO_DET",
    "forecastId": "nfl-current-state-v2:sha256:eaad2b7f0cc46d2b0e05304934179e32dcda56ab8e517a47a7a03efcfe1a2887",
    "modelId": "NFL_CURRENT_STATE_RESIDUAL_V2",
    "reason": "MISSING_SEASON_MEAN_EXTRAPOLATION_UNVALIDATED"
  },
  {
    "artifact": {
      "byteCount": 80240,
      "path": "C:\\Users\\james\\asp-model-studio\\outputs\\nfl-current-state-cold-start-v2\\reconstructed-study-v1\\current-publication\\nfl-labs-score-distributions-v2\\sha256\\cb545a7fd00a8daa646c56158fc86f47d04e56667fbfdd7d131473e85e5b6696\\artifact.json",
      "sha256": "cb545a7fd00a8daa646c56158fc86f47d04e56667fbfdd7d131473e85e5b6696"
    },
    "disposition": "WITHHELD_FROM_CURRENT_IMPORT_OR_USE_ORIGINAL_OBJECT_PRESERVED",
    "eventId": "2026_01_NO_DET",
    "forecastId": "nfl-current-state-v2:sha256:088ccf49bc304f386da25fe5ceadc615d527be76f613fbbe9cf3b8d0131d1745",
    "modelId": "NFL_CURRENT_STATE_ENSEMBLE_V2",
    "reason": "MISSING_SEASON_MEAN_EXTRAPOLATION_UNVALIDATED"
  },
  {
    "artifact": {
      "byteCount": 68821,
      "path": "C:\\Users\\james\\asp-model-studio\\outputs\\nfl-current-state-cold-start-v2\\reconstructed-study-v1\\current-publication\\nfl-labs-score-distributions-v2\\sha256\\4ca7992bd9a2e7ef1ae52551aa00bc8113fe1ed7552e6e3867bdc67cdd9321e0\\artifact.json",
      "sha256": "4ca7992bd9a2e7ef1ae52551aa00bc8113fe1ed7552e6e3867bdc67cdd9321e0"
    },
    "disposition": "WITHHELD_FROM_CURRENT_IMPORT_OR_USE_ORIGINAL_OBJECT_PRESERVED",
    "eventId": "2026_01_NYJ_TEN",
    "forecastId": "nfl-current-state-v2:sha256:004d0be07853d051b02e88bc175a0a8d6ebab9d908315807e7b2e6b1319754bf",
    "modelId": "NFL_CURRENT_STATE_HIERARCHICAL_V2",
    "reason": "MISSING_SEASON_MEAN_EXTRAPOLATION_UNVALIDATED"
  },
  {
    "artifact": {
      "byteCount": 70299,
      "path": "C:\\Users\\james\\asp-model-studio\\outputs\\nfl-current-state-cold-start-v2\\reconstructed-study-v1\\current-publication\\nfl-labs-score-distributions-v2\\sha256\\ea3c9ed50e44c2b5e6082ee8907c2622899db79b0f11a53193b53a4fc9a3926e\\artifact.json",
      "sha256": "ea3c9ed50e44c2b5e6082ee8907c2622899db79b0f11a53193b53a4fc9a3926e"
    },
    "disposition": "WITHHELD_FROM_CURRENT_IMPORT_OR_USE_ORIGINAL_OBJECT_PRESERVED",
    "eventId": "2026_01_NYJ_TEN",
    "forecastId": "nfl-current-state-v2:sha256:215967f4fbe8ab3e6736965d1589c2c3310dbf92a8984e0e202a05bdf999795f",
    "modelId": "NFL_CURRENT_STATE_RESIDUAL_V2",
    "reason": "MISSING_SEASON_MEAN_EXTRAPOLATION_UNVALIDATED"
  },
  {
    "artifact": {
      "byteCount": 80881,
      "path": "C:\\Users\\james\\asp-model-studio\\outputs\\nfl-current-state-cold-start-v2\\reconstructed-study-v1\\current-publication\\nfl-labs-score-distributions-v2\\sha256\\11c11ef6d4229febd099ca24e0469e267dfe8a8a545a2a2f59a3ed81f8c25c23\\artifact.json",
      "sha256": "11c11ef6d4229febd099ca24e0469e267dfe8a8a545a2a2f59a3ed81f8c25c23"
    },
    "disposition": "WITHHELD_FROM_CURRENT_IMPORT_OR_USE_ORIGINAL_OBJECT_PRESERVED",
    "eventId": "2026_01_NYJ_TEN",
    "forecastId": "nfl-current-state-v2:sha256:ef52849ab1c13a833933c61e5085b15b204909c0af36bd91bfaaed59720aff83",
    "modelId": "NFL_CURRENT_STATE_ENSEMBLE_V2",
    "reason": "MISSING_SEASON_MEAN_EXTRAPOLATION_UNVALIDATED"
  },
  {
    "artifact": {
      "byteCount": 69592,
      "path": "C:\\Users\\james\\asp-model-studio\\outputs\\nfl-current-state-cold-start-v2\\reconstructed-study-v1\\current-publication\\nfl-labs-score-distributions-v2\\sha256\\99df2c28a743050ef6c6e82ddf46bdfd7800b74e9562e1707780932d3e3e53db\\artifact.json",
      "sha256": "99df2c28a743050ef6c6e82ddf46bdfd7800b74e9562e1707780932d3e3e53db"
    },
    "disposition": "WITHHELD_FROM_CURRENT_IMPORT_OR_USE_ORIGINAL_OBJECT_PRESERVED",
    "eventId": "2026_01_TB_CIN",
    "forecastId": "nfl-current-state-v2:sha256:96fc8e94318f0e7467caacb675f199977e93117241c779b8bcc63a0c0d28e91e",
    "modelId": "NFL_CURRENT_STATE_HIERARCHICAL_V2",
    "reason": "MISSING_SEASON_MEAN_EXTRAPOLATION_UNVALIDATED"
  },
  {
    "artifact": {
      "byteCount": 69132,
      "path": "C:\\Users\\james\\asp-model-studio\\outputs\\nfl-current-state-cold-start-v2\\reconstructed-study-v1\\current-publication\\nfl-labs-score-distributions-v2\\sha256\\f0cb005a287d53f86558f7e1b0fc4401bc457239748ece19f5b58b930d375adc\\artifact.json",
      "sha256": "f0cb005a287d53f86558f7e1b0fc4401bc457239748ece19f5b58b930d375adc"
    },
    "disposition": "WITHHELD_FROM_CURRENT_IMPORT_OR_USE_ORIGINAL_OBJECT_PRESERVED",
    "eventId": "2026_01_TB_CIN",
    "forecastId": "nfl-current-state-v2:sha256:3e02f28e6e346393032bf1d9005aa82c022b0b77a6cf2b251270eb1ad5ec79f7",
    "modelId": "NFL_CURRENT_STATE_RESIDUAL_V2",
    "reason": "MISSING_SEASON_MEAN_EXTRAPOLATION_UNVALIDATED"
  },
  {
    "artifact": {
      "byteCount": 77473,
      "path": "C:\\Users\\james\\asp-model-studio\\outputs\\nfl-current-state-cold-start-v2\\reconstructed-study-v1\\current-publication\\nfl-labs-score-distributions-v2\\sha256\\173b9e029ee680d749bcca445a143f37280e9e3a91c437ec104e534ecdf6deb1\\artifact.json",
      "sha256": "173b9e029ee680d749bcca445a143f37280e9e3a91c437ec104e534ecdf6deb1"
    },
    "disposition": "WITHHELD_FROM_CURRENT_IMPORT_OR_USE_ORIGINAL_OBJECT_PRESERVED",
    "eventId": "2026_01_TB_CIN",
    "forecastId": "nfl-current-state-v2:sha256:b2b16816543334206a0c75e5c27e7e62ef82b44185da2125c6f80e521ddcfbc0",
    "modelId": "NFL_CURRENT_STATE_ENSEMBLE_V2",
    "reason": "MISSING_SEASON_MEAN_EXTRAPOLATION_UNVALIDATED"
  },
  {
    "artifact": {
      "byteCount": 68470,
      "path": "C:\\Users\\james\\asp-model-studio\\outputs\\nfl-current-state-cold-start-v2\\reconstructed-study-v1\\current-publication\\nfl-labs-score-distributions-v2\\sha256\\b47ccedab6831795137f303cf3bc81848f84e841dc5b2fc43e584e8e994cc390\\artifact.json",
      "sha256": "b47ccedab6831795137f303cf3bc81848f84e841dc5b2fc43e584e8e994cc390"
    },
    "disposition": "WITHHELD_FROM_CURRENT_IMPORT_OR_USE_ORIGINAL_OBJECT_PRESERVED",
    "eventId": "2026_01_ARI_LAC",
    "forecastId": "nfl-current-state-v2:sha256:43ba9ac4140eecfca8f4b06e7f24c5dda4ffbf6059599dfee66c829a3b523eae",
    "modelId": "NFL_CURRENT_STATE_HIERARCHICAL_V2",
    "reason": "MISSING_SEASON_MEAN_EXTRAPOLATION_UNVALIDATED"
  },
  {
    "artifact": {
      "byteCount": 69121,
      "path": "C:\\Users\\james\\asp-model-studio\\outputs\\nfl-current-state-cold-start-v2\\reconstructed-study-v1\\current-publication\\nfl-labs-score-distributions-v2\\sha256\\282ab1f8fd1b8bed6fb804b251a420d27da1c544980c3f98e77491f820519461\\artifact.json",
      "sha256": "282ab1f8fd1b8bed6fb804b251a420d27da1c544980c3f98e77491f820519461"
    },
    "disposition": "WITHHELD_FROM_CURRENT_IMPORT_OR_USE_ORIGINAL_OBJECT_PRESERVED",
    "eventId": "2026_01_ARI_LAC",
    "forecastId": "nfl-current-state-v2:sha256:48eb8ee7ce701af373971ab8fdcf5aa32bcae2ecfd992edb511cd4a13dc54a90",
    "modelId": "NFL_CURRENT_STATE_RESIDUAL_V2",
    "reason": "MISSING_SEASON_MEAN_EXTRAPOLATION_UNVALIDATED"
  },
  {
    "artifact": {
      "byteCount": 78418,
      "path": "C:\\Users\\james\\asp-model-studio\\outputs\\nfl-current-state-cold-start-v2\\reconstructed-study-v1\\current-publication\\nfl-labs-score-distributions-v2\\sha256\\b96faab60919773dbd6f2435d83b72bfb2c2b36b6f6c87c03f32993d227b2d5e\\artifact.json",
      "sha256": "b96faab60919773dbd6f2435d83b72bfb2c2b36b6f6c87c03f32993d227b2d5e"
    },
    "disposition": "WITHHELD_FROM_CURRENT_IMPORT_OR_USE_ORIGINAL_OBJECT_PRESERVED",
    "eventId": "2026_01_ARI_LAC",
    "forecastId": "nfl-current-state-v2:sha256:8f30ea49110840128384af839971ede9903c653b6dc9dbba57732a4c7c97ea0c",
    "modelId": "NFL_CURRENT_STATE_ENSEMBLE_V2",
    "reason": "MISSING_SEASON_MEAN_EXTRAPOLATION_UNVALIDATED"
  },
  {
    "artifact": {
      "byteCount": 69818,
      "path": "C:\\Users\\james\\asp-model-studio\\outputs\\nfl-current-state-cold-start-v2\\reconstructed-study-v1\\current-publication\\nfl-labs-score-distributions-v2\\sha256\\2b6f904ddc92dffe6e71143917ac7c24c0cb836733cb996eeff7fac7d6bb5e6d\\artifact.json",
      "sha256": "2b6f904ddc92dffe6e71143917ac7c24c0cb836733cb996eeff7fac7d6bb5e6d"
    },
    "disposition": "WITHHELD_FROM_CURRENT_IMPORT_OR_USE_ORIGINAL_OBJECT_PRESERVED",
    "eventId": "2026_01_GB_MIN",
    "forecastId": "nfl-current-state-v2:sha256:fcb4a85f9de81e5eb8fd261825e8acd5b1f881f92c44365a6222fd80fa6865b2",
    "modelId": "NFL_CURRENT_STATE_HIERARCHICAL_V2",
    "reason": "MISSING_SEASON_MEAN_EXTRAPOLATION_UNVALIDATED"
  },
  {
    "artifact": {
      "byteCount": 70037,
      "path": "C:\\Users\\james\\asp-model-studio\\outputs\\nfl-current-state-cold-start-v2\\reconstructed-study-v1\\current-publication\\nfl-labs-score-distributions-v2\\sha256\\bace1809c7a04bdbe78aea8cacacf5dcfc6090de2d95cdc476ff4f2a9c562516\\artifact.json",
      "sha256": "bace1809c7a04bdbe78aea8cacacf5dcfc6090de2d95cdc476ff4f2a9c562516"
    },
    "disposition": "WITHHELD_FROM_CURRENT_IMPORT_OR_USE_ORIGINAL_OBJECT_PRESERVED",
    "eventId": "2026_01_GB_MIN",
    "forecastId": "nfl-current-state-v2:sha256:20346f55e17e69c5de9a9f1bee6d455f8190f09ffb5ec21bbcb56637a39ddaf4",
    "modelId": "NFL_CURRENT_STATE_RESIDUAL_V2",
    "reason": "MISSING_SEASON_MEAN_EXTRAPOLATION_UNVALIDATED"
  },
  {
    "artifact": {
      "byteCount": 78138,
      "path": "C:\\Users\\james\\asp-model-studio\\outputs\\nfl-current-state-cold-start-v2\\reconstructed-study-v1\\current-publication\\nfl-labs-score-distributions-v2\\sha256\\e351b6cffc633a958f0e71f6e8cd266f1d5234c7a76ce61af56cbaa380782aa5\\artifact.json",
      "sha256": "e351b6cffc633a958f0e71f6e8cd266f1d5234c7a76ce61af56cbaa380782aa5"
    },
    "disposition": "WITHHELD_FROM_CURRENT_IMPORT_OR_USE_ORIGINAL_OBJECT_PRESERVED",
    "eventId": "2026_01_GB_MIN",
    "forecastId": "nfl-current-state-v2:sha256:380240121177b620d8f92cdaaf954f08f64e5f5bef054e15a6546453e49bd65c",
    "modelId": "NFL_CURRENT_STATE_ENSEMBLE_V2",
    "reason": "MISSING_SEASON_MEAN_EXTRAPOLATION_UNVALIDATED"
  },
  {
    "artifact": {
      "byteCount": 68056,
      "path": "C:\\Users\\james\\asp-model-studio\\outputs\\nfl-current-state-cold-start-v2\\reconstructed-study-v1\\current-publication\\nfl-labs-score-distributions-v2\\sha256\\d82cf0dcf88ed9878ca321a17fa2165f6b55a812c0d77371ac099c56ce030d44\\artifact.json",
      "sha256": "d82cf0dcf88ed9878ca321a17fa2165f6b55a812c0d77371ac099c56ce030d44"
    },
    "disposition": "WITHHELD_FROM_CURRENT_IMPORT_OR_USE_ORIGINAL_OBJECT_PRESERVED",
    "eventId": "2026_01_MIA_LV",
    "forecastId": "nfl-current-state-v2:sha256:fa683087904a2ba6f74eda738ec65fae86e7602f8735b45c97eeda5c3ad720d3",
    "modelId": "NFL_CURRENT_STATE_HIERARCHICAL_V2",
    "reason": "MISSING_SEASON_MEAN_EXTRAPOLATION_UNVALIDATED"
  },
  {
    "artifact": {
      "byteCount": 69145,
      "path": "C:\\Users\\james\\asp-model-studio\\outputs\\nfl-current-state-cold-start-v2\\reconstructed-study-v1\\current-publication\\nfl-labs-score-distributions-v2\\sha256\\ce12f00acd416eb872ee438b2eeb03a35a2740f9c7f70bbdbe8f159cf12f32f1\\artifact.json",
      "sha256": "ce12f00acd416eb872ee438b2eeb03a35a2740f9c7f70bbdbe8f159cf12f32f1"
    },
    "disposition": "WITHHELD_FROM_CURRENT_IMPORT_OR_USE_ORIGINAL_OBJECT_PRESERVED",
    "eventId": "2026_01_MIA_LV",
    "forecastId": "nfl-current-state-v2:sha256:6dfaaae1f111f2f4e958fea4c9039887039d3a7a5f93be0c12d4f4cc8d2c8ddc",
    "modelId": "NFL_CURRENT_STATE_RESIDUAL_V2",
    "reason": "MISSING_SEASON_MEAN_EXTRAPOLATION_UNVALIDATED"
  },
  {
    "artifact": {
      "byteCount": 76486,
      "path": "C:\\Users\\james\\asp-model-studio\\outputs\\nfl-current-state-cold-start-v2\\reconstructed-study-v1\\current-publication\\nfl-labs-score-distributions-v2\\sha256\\0f3a82f752ab66c1335cc26e54c76016ac4924f654818e9002ea6f6ace34fdb2\\artifact.json",
      "sha256": "0f3a82f752ab66c1335cc26e54c76016ac4924f654818e9002ea6f6ace34fdb2"
    },
    "disposition": "WITHHELD_FROM_CURRENT_IMPORT_OR_USE_ORIGINAL_OBJECT_PRESERVED",
    "eventId": "2026_01_MIA_LV",
    "forecastId": "nfl-current-state-v2:sha256:2a20bb4db37de8e8ba33fcb266e4687b1b98d04ed00d59b532a9d931aa99faf2",
    "modelId": "NFL_CURRENT_STATE_ENSEMBLE_V2",
    "reason": "MISSING_SEASON_MEAN_EXTRAPOLATION_UNVALIDATED"
  },
  {
    "artifact": {
      "byteCount": 66956,
      "path": "C:\\Users\\james\\asp-model-studio\\outputs\\nfl-current-state-cold-start-v2\\reconstructed-study-v1\\current-publication\\nfl-labs-score-distributions-v2\\sha256\\6cb0f285e17026973456c038e28df7d2951b1065ddd25d86a46f391e7bb1ea1c\\artifact.json",
      "sha256": "6cb0f285e17026973456c038e28df7d2951b1065ddd25d86a46f391e7bb1ea1c"
    },
    "disposition": "WITHHELD_FROM_CURRENT_IMPORT_OR_USE_ORIGINAL_OBJECT_PRESERVED",
    "eventId": "2026_01_WAS_PHI",
    "forecastId": "nfl-current-state-v2:sha256:9ded952703034f1b175c79f0db0b4301068f6618011a583c6df6633894efe3c3",
    "modelId": "NFL_CURRENT_STATE_HIERARCHICAL_V2",
    "reason": "MISSING_SEASON_MEAN_EXTRAPOLATION_UNVALIDATED"
  },
  {
    "artifact": {
      "byteCount": 68424,
      "path": "C:\\Users\\james\\asp-model-studio\\outputs\\nfl-current-state-cold-start-v2\\reconstructed-study-v1\\current-publication\\nfl-labs-score-distributions-v2\\sha256\\c6d03230082f1874a3379ca3e084a252d2148c498642c5f64652f718385b8fe4\\artifact.json",
      "sha256": "c6d03230082f1874a3379ca3e084a252d2148c498642c5f64652f718385b8fe4"
    },
    "disposition": "WITHHELD_FROM_CURRENT_IMPORT_OR_USE_ORIGINAL_OBJECT_PRESERVED",
    "eventId": "2026_01_WAS_PHI",
    "forecastId": "nfl-current-state-v2:sha256:606c354dffbb1507cdcb6e5f52e7fde391b7406e83bf72bb5f1aae7472bcebff",
    "modelId": "NFL_CURRENT_STATE_RESIDUAL_V2",
    "reason": "MISSING_SEASON_MEAN_EXTRAPOLATION_UNVALIDATED"
  },
  {
    "artifact": {
      "byteCount": 76119,
      "path": "C:\\Users\\james\\asp-model-studio\\outputs\\nfl-current-state-cold-start-v2\\reconstructed-study-v1\\current-publication\\nfl-labs-score-distributions-v2\\sha256\\553164ad9608a71a9626881f27e05ba8a4891e9db4b9fb5340d3a494fbf48b9f\\artifact.json",
      "sha256": "553164ad9608a71a9626881f27e05ba8a4891e9db4b9fb5340d3a494fbf48b9f"
    },
    "disposition": "WITHHELD_FROM_CURRENT_IMPORT_OR_USE_ORIGINAL_OBJECT_PRESERVED",
    "eventId": "2026_01_WAS_PHI",
    "forecastId": "nfl-current-state-v2:sha256:206ebc0ec849376e9bd474981f2f96278e146377279e8fbc196da6b82c7d3e0c",
    "modelId": "NFL_CURRENT_STATE_ENSEMBLE_V2",
    "reason": "MISSING_SEASON_MEAN_EXTRAPOLATION_UNVALIDATED"
  },
  {
    "artifact": {
      "byteCount": 68345,
      "path": "C:\\Users\\james\\asp-model-studio\\outputs\\nfl-current-state-cold-start-v2\\reconstructed-study-v1\\current-publication\\nfl-labs-score-distributions-v2\\sha256\\91ccef9d02ebd54e19c0ab355bd1fcc295dcdefc45096c29ff44482fecf85e3a\\artifact.json",
      "sha256": "91ccef9d02ebd54e19c0ab355bd1fcc295dcdefc45096c29ff44482fecf85e3a"
    },
    "disposition": "WITHHELD_FROM_CURRENT_IMPORT_OR_USE_ORIGINAL_OBJECT_PRESERVED",
    "eventId": "2026_01_DAL_NYG",
    "forecastId": "nfl-current-state-v2:sha256:0c0693423df6b10ccba7fac28871d6d18f2f7e792d5b6de943caa3d7b453f36d",
    "modelId": "NFL_CURRENT_STATE_HIERARCHICAL_V2",
    "reason": "MISSING_SEASON_MEAN_EXTRAPOLATION_UNVALIDATED"
  },
  {
    "artifact": {
      "byteCount": 68552,
      "path": "C:\\Users\\james\\asp-model-studio\\outputs\\nfl-current-state-cold-start-v2\\reconstructed-study-v1\\current-publication\\nfl-labs-score-distributions-v2\\sha256\\503003d082d88c094b2c0c5ea2d41d2e0e4e714ad132e0799fd072c4fa101ec4\\artifact.json",
      "sha256": "503003d082d88c094b2c0c5ea2d41d2e0e4e714ad132e0799fd072c4fa101ec4"
    },
    "disposition": "WITHHELD_FROM_CURRENT_IMPORT_OR_USE_ORIGINAL_OBJECT_PRESERVED",
    "eventId": "2026_01_DAL_NYG",
    "forecastId": "nfl-current-state-v2:sha256:f4ad8427488341f236cb7f59e669f2f0a3e585cd58e7bc4f2c07645c6dcd657f",
    "modelId": "NFL_CURRENT_STATE_RESIDUAL_V2",
    "reason": "MISSING_SEASON_MEAN_EXTRAPOLATION_UNVALIDATED"
  },
  {
    "artifact": {
      "byteCount": 78592,
      "path": "C:\\Users\\james\\asp-model-studio\\outputs\\nfl-current-state-cold-start-v2\\reconstructed-study-v1\\current-publication\\nfl-labs-score-distributions-v2\\sha256\\2709579e90e71e2965edb3e7fef7cbef430abef316436229d7c9b58da0e54546\\artifact.json",
      "sha256": "2709579e90e71e2965edb3e7fef7cbef430abef316436229d7c9b58da0e54546"
    },
    "disposition": "WITHHELD_FROM_CURRENT_IMPORT_OR_USE_ORIGINAL_OBJECT_PRESERVED",
    "eventId": "2026_01_DAL_NYG",
    "forecastId": "nfl-current-state-v2:sha256:f37047064ee76955329a10de5b7c55c2d8b54111a5737c8506e87dd7d03de997",
    "modelId": "NFL_CURRENT_STATE_ENSEMBLE_V2",
    "reason": "MISSING_SEASON_MEAN_EXTRAPOLATION_UNVALIDATED"
  },
  {
    "artifact": {
      "byteCount": 68459,
      "path": "C:\\Users\\james\\asp-model-studio\\outputs\\nfl-current-state-cold-start-v2\\reconstructed-study-v1\\current-publication\\nfl-labs-score-distributions-v2\\sha256\\54f41aa57f872ad1422b63351c8cd847bb4f1c760f553cd67b6a4266992ce404\\artifact.json",
      "sha256": "54f41aa57f872ad1422b63351c8cd847bb4f1c760f553cd67b6a4266992ce404"
    },
    "disposition": "WITHHELD_FROM_CURRENT_IMPORT_OR_USE_ORIGINAL_OBJECT_PRESERVED",
    "eventId": "2026_01_DEN_KC",
    "forecastId": "nfl-current-state-v2:sha256:62882ed1ea90d3e0552c2603ebbffaae5dffc590dd5f236698c910a89d9ac21a",
    "modelId": "NFL_CURRENT_STATE_HIERARCHICAL_V2",
    "reason": "MISSING_SEASON_MEAN_EXTRAPOLATION_UNVALIDATED"
  },
  {
    "artifact": {
      "byteCount": 68469,
      "path": "C:\\Users\\james\\asp-model-studio\\outputs\\nfl-current-state-cold-start-v2\\reconstructed-study-v1\\current-publication\\nfl-labs-score-distributions-v2\\sha256\\7556c98beed8674722e241c86ba0763c830c36c5186a45c42898922e669b06c1\\artifact.json",
      "sha256": "7556c98beed8674722e241c86ba0763c830c36c5186a45c42898922e669b06c1"
    },
    "disposition": "WITHHELD_FROM_CURRENT_IMPORT_OR_USE_ORIGINAL_OBJECT_PRESERVED",
    "eventId": "2026_01_DEN_KC",
    "forecastId": "nfl-current-state-v2:sha256:e9eb4f8d403ba70babfd8483d0cd321905194006d94520d0df264ce671513b34",
    "modelId": "NFL_CURRENT_STATE_RESIDUAL_V2",
    "reason": "MISSING_SEASON_MEAN_EXTRAPOLATION_UNVALIDATED"
  },
  {
    "artifact": {
      "byteCount": 77937,
      "path": "C:\\Users\\james\\asp-model-studio\\outputs\\nfl-current-state-cold-start-v2\\reconstructed-study-v1\\current-publication\\nfl-labs-score-distributions-v2\\sha256\\043a048769b47cde05ead94250fe2994f2d069a28a690ea55a554690a1fe0897\\artifact.json",
      "sha256": "043a048769b47cde05ead94250fe2994f2d069a28a690ea55a554690a1fe0897"
    },
    "disposition": "WITHHELD_FROM_CURRENT_IMPORT_OR_USE_ORIGINAL_OBJECT_PRESERVED",
    "eventId": "2026_01_DEN_KC",
    "forecastId": "nfl-current-state-v2:sha256:4e290ce082ca2de726f5d9e3ca9d4a056848fada569e92ff52be1ae6f776cc85",
    "modelId": "NFL_CURRENT_STATE_ENSEMBLE_V2",
    "reason": "MISSING_SEASON_MEAN_EXTRAPOLATION_UNVALIDATED"
  }
]
```

### Joint-law and independent play-engine limits

Home/away/tie, expected scores, margin, total and score-distribution queries reconcile to the same empirical joint score law. Paired inner-holdout residuals retain score dependence, but nonnegative integer final scores are not constrained to legal scoring sequences. This is not a play/drive simulator; no trajectories, overtime incidence or tactical path is inferred. The independent play engine remains a different generating law.

Predecessor audit only; this comparison does not admit withheld models. Saved-law comparison: 16 matched events / 64 event-model rows, status `NOT_COUPLED_NOT_CALIBRATED_TO_MATCH`. Models executed: 0; calibration fits: 0; new play paths: 0. Any disagreement is not an accuracy result, outcome test or wagering edge. Full deltas and differing source timestamps are retained in the model card.

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

### Actual publication rerun verification

This verifies the preserved original 64-forecast publication before corrective admission, not admission of the blocked models. The separate completed rerun receipt records `EXACT_REUSE`: 64 of 64 forecast object references were identical; 0 new numerical forecasts; 0 probability/distribution mismatches. The rerun covered 16 events with 0 skips in 19.42 seconds. Original delivery, handoff, manifest, pointer, frozen model and statistics were unchanged. Model fits: 0; provider calls: 0; AISP writes: 0. This verifies publication reuse, not predictive accuracy. [Exact verification receipt](<C:/Users/james/asp-model-studio/outputs/nfl-current-state-cold-start-v2/reconstructed-study-v1/verification/sha256/57c9023781ecf2d1cb52aa27959dd8d93cc46e5d1167d394242add18e34cec1b/actual-publication-idempotency.json>).

## Forward archive and prospective markets

The archival schedule receipt is `ACTIVE` at a 6-hour cadence. Computer on and Codex app running. Scheduling is not a guarantee of uninterrupted capture. Archive already available local source snapshots; no provider acquisition or model execution. Captured observation time is the actual capture time, not backdated source retrieval. Missing families stay unavailable. This creates evidence for future genuine OBSERVED_AS_OF validation; it cannot repair missing historical vintages.

Prospective market status: `PENDING_TIMESTAMPED_MARKET_EVIDENCE`; supplied timestamped quote snapshots: 0. Model-only forecasts remain separate. No untimed price tuning or wagering edge is authorized. The exact export contract is linked below; quote observation and first-availability must precede the frozen forecast cutoff and kickoff. This bounded comparison supports eligible two-way moneylines only; spread/total records may be retained but automated line comparison remains unsupported.

## Claude / AISP import instruction

Use only the corrective admitted handoff linked below. The predecessor 64-forecast handoff is audit evidence, not current import authority. HIERARCHICAL, RESIDUAL and ENSEMBLE are withheld.

The following is copied from the completed handoff; this report does not assert that an AISP import has happened:

> Import ONLY this corrective handoff's 16 NFL_CURRENT_STATE_DYNAMIC_V2 precomputed research-baseline forecasts and score-distribution artifacts. Verify checksums and byte counts. Do not import or admit the 48 HIERARCHICAL, RESIDUAL or ENSEMBLE forecasts from the predecessor: MISSING_SEASON_MEAN_EXTRAPOLATION_UNVALIDATED. Preserve original forecast timestamps and all prior evidence. No current hierarchical/residual challenger is admitted; no model execution, promotion or wagering authority.

## Immutable delivery references

| Artifact | Path | SHA-256 |
| --- | --- | --- |
| Report model card (all saved metrics, intervals and forecast summaries) | [Report model card (all saved metrics, intervals and forecast summaries)](<C:/Users/james/asp-model-studio/outputs/nfl-current-state-cold-start-v2/reconstructed-study-v1/reports/sha256/dbc8488ff3de7c9a48695e023f75d17be7299803fe3ee7908ea95fc94ec93180/model-card.json>) | dbc8488ff3de7c9a48695e023f75d17be7299803fe3ee7908ea95fc94ec93180 |
| Completed study | [Completed study](<C:/Users/james/asp-model-studio/outputs/nfl-current-state-cold-start-v2/reconstructed-study-v1/runs/bd347be16547007eb9ded9878b9650674f2c9c5e52473fd3ab674a9afe4bdd83/result.json>) | 29989f3af980fd2cb0fa97096f570ced6950d66b981168d83d97c38243f160e3 |
| Original delivery receipt (predecessor audit) | [Original delivery receipt (predecessor audit)](<C:/Users/james/asp-model-studio/outputs/nfl-current-state-cold-start-v2/reconstructed-study-v1/deliveries/sha256/c0cf12c5c79efe78b239c8158ff628c7adf25133ac21e03880dee74f039a0ce9/delivery.json>) | c0cf12c5c79efe78b239c8158ff628c7adf25133ac21e03880dee74f039a0ce9 |
| Methodology | [Methodology](<C:/Users/james/asp-model-studio/outputs/nfl-current-state-cold-start-v2/reconstructed-study-v1/methodology-contract.json>) | 2b9ee995ad0cb46a2672a129b2cb6672986e2538702e9812aadbf128601b0c92 |
| 44-field inventory | [44-field inventory](<C:/Users/james/asp-model-studio/outputs/nfl-current-state-cold-start-v2/reconstructed-study-v1/runs/bd347be16547007eb9ded9878b9650674f2c9c5e52473fd3ab674a9afe4bdd83/treatment-inventory.json>) | c3a385ba6541899c5437f02cf97269ac82224ec6ba6091ec38b3bf8a61ae2abc |
| Fitted state metadata (no execution) | [Fitted state metadata (no execution)](<C:/Users/james/asp-model-studio/outputs/nfl-current-state-cold-start-v2/reconstructed-study-v1/runs/bd347be16547007eb9ded9878b9650674f2c9c5e52473fd3ab674a9afe4bdd83/final-through2024-lag48/fitted-state.json>) | 2c59350ce94df3a118f1da17249e41ddd1ccbfb62ee7c0b3ea1d57b8a3b3671e |
| Fit receipts | [Fit receipts](<C:/Users/james/asp-model-studio/outputs/nfl-current-state-cold-start-v2/reconstructed-study-v1/runs/bd347be16547007eb9ded9878b9650674f2c9c5e52473fd3ab674a9afe4bdd83/fit-receipts.jsonl>) | d85edc2233c12bdbb11e2deb080fc8cbd2f01437dc99d6aa3787865c16f56be8 |
| Admitted distribution handoff | [Admitted distribution handoff](<C:/Users/james/asp-model-studio/outputs/nfl-current-state-cold-start-v2/reconstructed-study-v1/corrective-admission/handoffs/sha256/9d2f4f8f59a72fbcc7b2be4175fc187e9e8ea0cb79312f5182d0fdbd343a8252/handoff.json>) | 9d2f4f8f59a72fbcc7b2be4175fc187e9e8ea0cb79312f5182d0fdbd343a8252 |
| Admitted publication manifest | [Admitted publication manifest](<C:/Users/james/asp-model-studio/outputs/nfl-current-state-cold-start-v2/reconstructed-study-v1/corrective-admission/manifests/sha256/8cfdd1d8610b881028feee22163726a6eefac49ca4e1cdb30ac53f8547dc613f/manifest.json>) | 8cfdd1d8610b881028feee22163726a6eefac49ca4e1cdb30ac53f8547dc613f |
| Timestamped quote export contract | [Timestamped quote export contract](<C:/Users/james/asp-model-studio/outputs/nfl-current-state-cold-start-v2/reconstructed-study-v1/prospective-market-comparison/contracts/sha256/d020eb8b0ddb9728a98b58bc17d808d8c87be66378deb83bbd2498c80d25a0a3/aisp-timed-quote-export-contract.json>) | d020eb8b0ddb9728a98b58bc17d808d8c87be66378deb83bbd2498c80d25a0a3 |
| Forward archive schedule receipt | [Forward archive schedule receipt](<C:/Users/james/asp-model-studio/outputs/nfl-current-state-cold-start-v2/reconstructed-study-v1/forward-archive-schedule.json>) | 27fcac8ea772f73ceaa879961eccc6bc1a1090a14cd926063513fb369a94803b |
| Three-game cohort reconciliation | [Three-game cohort reconciliation](<C:/Users/james/asp-model-studio/outputs/nfl-current-state-cold-start-v2/reconstructed-study-v1/cohort-reconciliation.json>) | b4bf3c4ef91cd303517cf05832fa703fe06cf4674c09e9ed0b8a2a06f32c509d |

## What remains scientifically unproven

The learned current challenger is blocked by a diagnosed mean-extrapolation defect, not merely awaiting promotion. Future repair and a separately authorized validation are required before those learned current forecasts can be scientifically used.

Genuine historical publication timing and late-correction magnitude; production superiority; target-starter/rookie, injury, coaching, roster-turnover or weather uplift; calibrated current cold-start uncertainty; legal score-path/OT dynamics; and betting value against timestamped, settlement-compatible prices remain unproven. Prospective evidence capture and independent validation are still required. No promotion, champion replacement or wagering activation occurred.
