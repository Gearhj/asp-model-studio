# Multisport feature engineering audit and opportunity map V1

**James’s concern is partly correct.** These are not unengineered models: they already contain substantial rolling, shrinkage, Elo, support and contextual information. The larger gaps are independent personnel/possession signals and reliable point-in-time collection. Feature count overstates distinct information; correlated windows, fallback values and reserved indicators are not separate observed signals.

The principal next assignment is **NFL opponent-adjusted pass/run EPA and offense-versus-defense context**, using existing admitted data. Its source path is usable without acquisition, and EPA/scoring reliance survives the bounded earlier-season audit. Incremental gain remains unmeasured; no challenger is implemented or promoted here.

| Model/channel | Exact count | Maturity and limitation |
|---|---:|---|
| MLB V18 PA |246 raw dependencies →273 treated →436 encoded | Broad engineered system;218 raw fields retain a direct treated slot,28 are dependencies;55 treatment outputs are added. Historical training chronology uncertified. |
| NFL M1 XGBoost |197 raw predictors |21 context +22 metrics ×4 windows ×2 sides; rich team history, no explicit adjusted efficiency or current personnel. Current bound vector197 nonnull, not197 fresh current-season observations. |
| NBA Ridge point |78 |71 vary within assessed seasons;7 support/context inputs are constant within each assessed season. Strong score/date baseline, no possessions or players. |
| NBA Elo/joint/close-margin |3 /5 /4 documented channel inputs | Separate winner output, paired OOF residuals, and postprocessing; not extra point predictors. |
| CFB Ridge |35 |34 vary in at least one assessed season; home_long_gap constant. Elo/score/yards/turnover/rest priors; no recruiting or personnel. |
| Separate research |MLB survival6; style73; regime33; CFB cluster8; NFL play10 selector/support inputs; drive25 |Not combined into production counts. Drive OT feature always0 in fitting; completed drive study retained baseline. |

The inventory contains **1449 rows**, including each raw/treated/encoded stage and separate component inputs. These are not independent predictors in one model. MLB has 24 treated categorical fields with one observed fitting level plus reserved UNKNOWN; 12 are missing=1 flags. These are not evidence of 24 usable observed contextual signals.

## Bounded empirical evidence

Development first: NBA2020–21 through2022–23 (3538 games), CFB2021–22 (1464), NFL2022 (271). The method was frozen before reused later evidence: NBA2023–24/2024–25 (2446), CFB2023/24 (1491), NFL2023/24 (544). All historical periods were previously inspected; none is a fresh test. No2026 labels entered numerical assessment. NFL uses fixed-recipe earlier-origin research clones; this is not retrospective execution of the current all-history model.

One deterministic within-month family permutation per origin, six NBA and seven NFL/CFB families. No family refits or hyperparameter search. Positive error deltas mean perturbation hurt; negative is not proof a refit without that family would improve. Intervals use2000 paired calendar-week block resamples and condition on the single perturbation.

| Reused later family | Games | Margin MAE delta [95% block interval] | Total MAE delta [95% block interval] |
|---|---:|---:|---:|
| CFB ELO | 1491 | +1.446 [+1.130, +1.786] | -0.011 [-0.036, +0.013] |
| CFB PRIOR_SCORING | 1491 | +0.004 [-0.036, +0.041] | +0.281 [+0.124, +0.439] |
| CFB RECENT_FIVE | 1491 | +0.422 [+0.205, +0.619] | +0.044 [-0.067, +0.157] |
| CFB SCHEDULE_SUPPORT_CONTEXT | 1491 | +0.101 [-0.008, +0.213] | -0.004 [-0.055, +0.049] |
| CFB SEASON_SCORING | 1491 | +0.006 [-0.103, +0.117] | -0.008 [-0.048, +0.035] |
| CFB TURNOVERS | 1491 | -0.003 [-0.033, +0.024] | -0.006 [-0.044, +0.032] |
| CFB YARDAGE | 1491 | +0.081 [-0.026, +0.184] | +0.401 [+0.227, +0.590] |
| NBA ELO | 2446 | +0.700 [+0.533, +0.881] | +0.043 [-0.052, +0.135] |
| NBA PRIOR_SCORING | 2446 | +0.076 [-0.001, +0.158] | +0.041 [+0.006, +0.076] |
| NBA RECENT_SCORING | 2446 | +1.285 [+1.066, +1.508] | +2.177 [+1.898, +2.442] |
| NBA REST_SCHEDULE | 2446 | +0.125 [+0.051, +0.198] | +0.010 [-0.029, +0.049] |
| NBA SCORING_VARIABILITY | 2446 | +0.039 [+0.003, +0.074] | +0.017 [-0.041, +0.077] |
| NBA SUPPORT_LEAGUE | 2446 | +0.006 [-0.015, +0.025] | +0.015 [-0.002, +0.033] |
| NFL DOWN_RED_ZONE | 544 | +0.004 [-0.047, +0.057] | +0.013 [-0.039, +0.064] |
| NFL EPA | 544 | +0.200 [-0.054, +0.467] | +0.072 [-0.085, +0.236] |
| NFL EXPLOSIVENESS | 544 | +0.115 [+0.029, +0.205] | -0.051 [-0.130, +0.029] |
| NFL SCHEDULE_SUPPORT_VENUE | 544 | +0.014 [-0.042, +0.074] | +0.054 [-0.027, +0.139] |
| NFL SCORING | 544 | +0.449 [+0.184, +0.703] | +0.193 [-0.005, +0.394] |
| NFL SUCCESS | 544 | +0.138 [+0.034, +0.242] | -0.005 [-0.079, +0.071] |
| NFL TURNOVER_PRESSURE_PACE | 544 | -0.035 [-0.088, +0.017] | -0.026 [-0.078, +0.031] |

NBA recent scoring history and Elo have repeatable margin reliance; scoring history dominates its total channel. Variability and some support/prior coefficients change signs and add little stable conditional reliance. NBA Elo probabilities remain independently unchanged in this point-model perturbation.

CFB Elo matters most for margins and yardage for totals. Recent-five margin adds smaller repeatable reliance. Raw season scoring and turnovers are weak conditional on those correlated proxies; do not interpret this as evidence that scoring or turnovers are inherently irrelevant. Priors matter more to total than margin.

NFL EPA, scoring and explosiveness matter to margins; EPA/scoring effects survive all three origins. Success reliance grows in2024, while down/red-zone and turnover/pressure/pace blocks are mixed. Gain is retained only as a descriptive tree diagnostic. NFL log loss/Brier/AUC here use the native normal-margin probability proxy on non-ties; they are not operational joint-law metrics. CFB later probability metrics use its frozen Development-only calibrator; in-sample Development calibrated probabilities were deliberately omitted.

All feature-family season metrics, score-channel errors, calibration bias, and team/support/favorite stability cells are in `FEATURE_IMPORTANCE_AND_ABLATION.json`. Individual coefficients are associational. Team cells with fewer than 20 exposures are unavailable; point-mean favored side is not a market favorite. NFL empirical clones use the declared REG/POST-code filter; the retained cohort contains regular-season games only, so this is not a playoff assessment. Within-month permutation cannot assess reliance on a season or month value constant inside that block. Distribution energy/CRPS are unavailable because no distribution engine was perturbed or rerun. MLB proper-score importance was skipped for the precise chronology reason recorded above.

## Risks and source gaps

**Access exception:** discovery accidentally exposed raw2026 NFL result rows in a rejected input snapshot. Zero outcome access cannot be claimed. The file was not reused, and the rows entered no fit, perturbation, metric or recommendation. `ACCESS_EXCEPTION.json` and the risk register preserve this qualification.

Historical revised archives are CategoryA reconstruction, not certified pregame vintages. CFB lacks a historical completion-before-donor certificate; the existing Development calibration backfill is same-population. NFL play-ID ordering was a confirmed research defect already documented by the completed drive study. NBA ordinary-rest extrapolation was already corrected and its frozen forecasts reproduce exactly. No new production defect repair is performed by this audit.

Top missing families per sport: MLB named relief availability, explicit starter/replacement coupling, genuine pregame park/weather context; NFL opponent-adjusted efficiency, current personnel/QB/OL context, special teams; NBA possession efficiency/pace, projected minutes/availability, lineup strength; CFB opponent-adjusted game performance, recruiting/returning production, QB/roster continuity. Existing travel/platoon/EPA/success features should not be reacquired as if absent.

## Ranked opportunities

| Rank | Opportunity | Weighted1–5 | Source gate |
|---:|---|---:|---|
| 1 | NFL: Opponent-adjusted EPA and offense-defense matchup | 4.330 | READY_FOR_BOUNDED_INTERNAL_RESEARCH |
| 2 | CFB: Conference/opponent adjustment of team performance | 3.900 | READY_FOR_BOUNDED_INTERNAL_RESEARCH |
| 3 | CFB: Recruiting/returning-production prior | 3.740 | SOURCE_TIMING_SCOPE_OR_INCREMENTAL_EVIDENCE_PREREQUISITE |
| 4 | NBA: Pace and team possession efficiency | 3.460 | SOURCE_TIMING_SCOPE_OR_INCREMENTAL_EVIDENCE_PREREQUISITE |
| 5 | MLB: Bullpen workload/availability | 3.430 | SOURCE_TIMING_SCOPE_OR_INCREMENTAL_EVIDENCE_PREREQUISITE |

Weights were frozen in `AUDIT_DESIGN.json` before ranking: incremental value25%, demonstrated weakness15%, historical depth8%, prospective availability10%, PIT10%, licensing5%, identity5%, missingness5%, effort5%, maintainability4%, interpretability3%, leakage5%. High means favorable; these are judgmental priorities, not measured future gains. Source-gated ideas cannot win solely on score.

For each sport, the next candidate would be MLB named bullpen exposure; NFL adjusted pass/run offense-defense context; NBA team possessions/efficiency before an expansive player model; CFB chronological opponent-adjusted yardage/score context before new recruiting intake. **Only NFL is the principal recommended next assignment.** NBA player matchup specialists, untimed market blends, unclocked injuries, MLB blanket run changes and CFB end-season ratings should not be pursued now.

NFL principal estimate:3–5 engineering days, USD0 incremental provider cost and0 new calls, using existing admitted local data. The brief freezes scope, chronological roles, baseline, endpoints and rejection rule for a subsequent authorized assignment. No acquisition or implementation starts here. Other estimates/rights gates are in the opportunity map; unknown costs are explicitly unknown.

## Preservation and reproduction

NFL drive study was completed first and safely committed: implementation `8454985b8bfeb986a8d0b53d45652149fac715b2`, evidence `7055d8c24f24cba35978591adfb5995b6d098fba`. It did not pass advancement gates. This audit leaves that evidence and all production models, forecasts, AISP, schedules and provider balances untouched. No provider/data API calls, sportsbook objects, new simulations, prospective forecasts or consumer handoff. Public documentation reads only.

Run from `C:\Users\james\asp-model-studio`:

```powershell
.\.venv\Scripts\python.exe -B scripts/multisport_audit_empirical.py --stage development
.\.venv\Scripts\python.exe -B scripts/multisport_audit_empirical.py --stage later
.\.venv\Scripts\python.exe -B scripts/multisport_audit_inventory.py
.\.venv\Scripts\python.exe -B scripts/multisport_audit_report.py
.\.venv\Scripts\python.exe -B scripts/multisport_audit_verify.py
```

Existing design files are frozen and must not be redeclared. Reproduction writes only this audit directory; source models are read-only. `PERMITTED_INPUT_PROJECTIONS.json` binds the exact pre-2026 numerical extracts saved after assessment for safe reproduction; these are not pregame captures. `SOURCE_BINDINGS.json` binds local contracts/models by physical bytes; `EXTERNAL_DOCUMENTATION_INDEX.json` binds authored notes to exact official URLs. `artifact-index.json` binds final deliverables; physical hashes are not logical model IDs. Focused verification records exact original Ridge reproduction, no-fit saved-model permutation replay, chronology/target exclusion and unchanged bound artifacts.
