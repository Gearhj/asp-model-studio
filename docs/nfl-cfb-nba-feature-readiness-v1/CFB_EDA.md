# College Football readiness and exploratory analysis

## Population and model

The bound CFB population contains 7,744 games from 2014 through 2024. Team cardinality grows from 130 in 2021 to 131 in 2022, 133 in 2023 and 134 in 2024, which makes effective-dated identity and division/conference membership material. The current baseline is `CFB_GEN1_RIDGE_A100`: 35 point-in-time team-level features for Elo, scoring, yardage, turnovers, prior shrinkage, recent-five form, rest and venue context.

Development is 2021-22; 2023-24 is reused later evidence. The bound point-model run does not recreate the separate Development-fixed winner calibrator, so it reports expected-score winner accuracy and no new log loss/Brier. Existing CFB joint and probability artifacts remain unchanged.

## Targets and baseline

Mean scores are 29.88 home and 25.83 away, for a 55.71 total and +4.06 home margin. Home teams won 58.03%; final games have no ties. Overtime occurrence is not identifiable in the projection.

| Season | Games | Score MAE | Margin MAE | Total MAE | Expected-score winner accuracy |
|---|---:|---:|---:|---:|---:|
| 2023 | 749 | 9.29 | 13.04 | 13.16 | 73.4% |
| 2024 | 742 | 9.27 | 13.51 | 12.66 | 68.7% |

Elo difference is the strongest univariate margin association at 0.528. Recent margin, team Elo and prior margin also matter. Total associations are much weaker, consistent with the remaining total-error problem.

## Missingness, cold start and identity

The projection has no null feature cells. This means the current upstream pipeline emits a complete matrix; it does not prove complete source observation. Raw source-missing, delayed and fallback indicators are required upstream so a model can distinguish evidence from substitution. The missingness-only challenger is therefore byte-equivalent in information and exactly matches baseline.

Cold start is substantial: 38.3% of 2023 and 39.5% of 2024 games contain at least one team with fewer than five current-season games. In 2024, low-support margin MAE was 14.82 versus 12.65 after both teams reached five games. The support-aware block reduced pooled score MAE by 0.010, but its interval [-0.032, +0.011] crosses zero and total MAE rose 0.001. It failed the frozen gate.

The identities show new programs across recent seasons, but the projection lacks effective-dated conference/division membership and alias-lineage fields. Conference realignment, FBS/FCS transitions and school-name changes therefore cannot be analyzed beyond team-count changes without a governed mapping.

## Feature experiment and blocked context

Simple offense-versus-opponent-defense scoring and yardage contrasts changed pooled errors by less than 0.001. These arithmetic contrasts do not estimate schedule strength. The next defensible experiment fits opponent strength from the prior schedule and carries an explicit new-team prior.

Returning production, transfers, recruiting, quarterback continuity, coaching changes, travel, altitude, weather and rivalry/postseason context are not certified inputs. Current rankings or end-season ratings must not be projected backward. Those families require timestamped sources, effective dates and stable player/program identities.

## Disposition

Strengths: stable score/yardage/Elo baseline, explicit current-season support, broad historical program coverage and strong expected-score discrimination. Weaknesses: high early-season uncertainty, no raw missingness provenance, no effective-dated conference identity, and no roster/coaching context. No tested block passed. Further research is justified for one schedule-strength challenger after the identity extension; the roster/recruiting program remains source-gated.
