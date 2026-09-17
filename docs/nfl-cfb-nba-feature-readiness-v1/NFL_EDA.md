# NFL readiness and exploratory analysis

## Population and model

The bound NFL population contains 6,695 regular/postseason-code historical rows from 1999 through 2024 and 32 teams in each recent season. The current research clone uses the `NFL_M1_XGBOOST` feature contract: 197 game-level fields covering scoring, EPA, success, explosiveness, downs/red zone, turnovers/pressure/pace, rest, schedule and venue context. The fixed estimator is fitted separately at each origin; the current all-history artifact is never applied retrospectively.

The report evaluates 2022 as Development and 2023-24 as previously inspected later evidence. NFL ties are real outcomes. Probability diagnostics exclude ties and are explicitly binary home-win diagnostics; they are not the production three-way summed Brier and are not directly comparable to NBA binary Brier.

## Data-generating process and targets

Across the full admitted history, mean score is 23.17 home and 20.92 away, mean total 44.09 and mean home margin 2.25. Home teams won 56.15%, away teams 43.64%, and 14 games tied (0.21%). The projection does not retain a governed overtime indicator, so tie and overtime mechanism analysis is unavailable.

Recent chronological baseline performance:

| Season | Games | Score MAE | Margin MAE | Total MAE | Expected-score winner accuracy | Log loss | Binary Brier | AUC |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 2023 | 272 | 7.57 | 10.40 | 10.60 | 63.2% | 0.656 | 0.232 | 0.653 |
| 2024 | 272 | 7.23 | 10.03 | 10.00 | 69.1% | 0.618 | 0.214 | 0.721 |

Calibration bias was +0.0003 in 2023 and +0.0179 in 2024. These native research-clone probabilities are useful diagnostics, not a re-certification of the operational joint law.

## Feature availability, missingness and drift

There are 20,631 missing feature cells. `game_type`, `roof` and `surface` are entirely absent in the bound projection. Several season-to-date defensive, red-zone and explosive fields are missing in roughly 6% of rows, mainly when history is unavailable. The explicit missing-indicator block made total MAE 0.056 points worse, with a 95% interval entirely above zero. Adding indicators alone does not repair missing evidence.

`home_prior_games` and `away_prior_games` have PSI 4.55 and 4.88 from Development to reused later evidence. They are cumulative-support fields, so this is partly an age/time trend. They also fail to identify a Week 1 or rookie-style cold start: no reused 2023/24 game had either team below five by this definition. A current-season team support field and player-level exposure are needed.

The strongest univariate associations with margin are recent scoring and offensive EPA. `home_points_for_last_16` correlates +0.226 with home margin; home offensive EPA windows are about +0.22. This supports EPA as a useful family but does not establish incremental value.

## Bounded feature blocks

Direct opposing-unit pass/rush EPA contrasts did not pass: pooled score MAE changed +0.021, margin +0.026 and total +0.048, all worse in point estimate. This is not the planned opponent-adjustment estimator. The smallest justified next experiment fits separate, shrunk offensive and defensive pass/run team effects from the earlier schedule inside every origin.

The generic cold-start block changed score MAE +0.010 and the combined block +0.023; neither interval excluded zero. Missingness also failed. No candidate was promoted.

## Failure regions and blocked features

In 2023, short-week/rest-stress games had margin MAE 11.70 versus 10.30 for ordinary rest; in 2024 the difference narrowed to 10.20 versus 10.02. High/low scoring and favorite-side differences are not stable across the two seasons. These are diagnostic segments and do not justify routing.

Current M1 does not contain certified current quarterback, offensive-line, skill-position, defensive-personnel, injury or weather revisions. The bound venue fields are unusable because roof/surface are absent. Special-teams information is also not independently represented. Adding these requires a new revisioned source contract; actual snaps or later inactive lists are prohibited.

## Disposition

Strengths: wide earlier-game efficiency history, stable identities, native tie-aware production architecture, and meaningful EPA/scoring signal. Weaknesses: no current personnel/injury/weather, incomplete venue fields, and no schedule-fitted opponent adjustment. The direct additions tested here failed. Further research is justified only for the predeclared opponent-adjusted team-effects challenger using existing governed data.
