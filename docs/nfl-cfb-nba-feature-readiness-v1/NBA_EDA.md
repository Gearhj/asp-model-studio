# NBA readiness and exploratory analysis

## Population and model

The bound NBA population contains 6,952 regular-season games in audit seasons 2020-2025 with 30 stable franchise identities. The point baseline is corrected Ridge alpha 100 with 78 score/date features. Elo supplies winner probability as a separately estimated channel. The assessed point model and Elo are not summaries of one shared simulation population.

Development is audit seasons 2021-23; 2024-25 is reused later evidence. Existing paired-residual and close-score distribution work is retained but not rerun here.

## Targets and baseline

Mean score is 113.81 home and 111.94 away, total 225.75 and home margin 1.88. Home teams won 55.16%; final scores have no ties. Overtime periods are not separately retained in this projection, although target scores include the final result.

| Audit season | Games | Score MAE | Margin MAE | Total MAE | Expected-score winner accuracy | Elo log loss | Elo Brier | Elo AUC |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 2024 | 1,225 | 9.31 | 11.07 | 14.78 | 65.1% | 0.616 | 0.214 | 0.714 |
| 2025 | 1,221 | 9.28 | 10.95 | 14.90 | 66.4% | 0.617 | 0.214 | 0.716 |

Elo calibration bias is about +0.037 in both later seasons, indicating average home probability exceeds observed home-win rate by 3.7 percentage points. This is a diagnostic; this task did not recalibrate Elo.

## Missingness, drift and cold start

The population has 2,258 missing cells, concentrated in rolling score/margin/total standard deviations during sparse history. League cumulative means and history counts have very high PSI because they advance systematically over time. That is a monitoring and representation issue, not proof they should be deleted.

Low-support rates are 6.6% in 2024 and 6.3% in 2025. The support-aware cold-start block changed score MAE -0.003 with interval [-0.007, +0.001], margin +0.004 and total -0.008; it failed the gate. Missingness indicators and rest-density interactions also failed.

In 2025, back-to-back/rest-stress games had score MAE 9.59 and total MAE 15.63 versus 9.15 and 14.57 under ordinary rest. The corresponding 2024 gap favored the stressed group, so this is not a stable routing region.

## Missing basketball information

The 78-feature baseline contains score history, variability, Elo, rest and schedule density. It lacks governed possessions, offensive/defensive efficiency, pace, effective field-goal rate, turnover rate, rebounding and free-throw rate. It also lacks timestamped lineups, rotations, projected minutes, injury revisions, trades and player-strength inputs. Actual minutes or the final active roster are postgame/final evidence and cannot fill that gap.

The strongest associations support the current architecture: Elo difference correlates 0.379 with margin, while rolling team totals correlate about 0.28 with final total. Total MAE remains near 14.8 points, making possession-based team efficiency the smallest high-value extension.

## Joint distribution limitation

Prior retained assessment found the paired-residual joint baseline preserved dependence and improved energy score, but simulated one-point margins occurred 7.78% versus 4.01% observed. A bounded close-score treatment reduced that mass to roughly 4.52% but changed energy score by only -0.00008 with uncertainty spanning zero, so it was not selected. That distribution limitation remains separate from this point-feature audit.

## Disposition

Strengths: stable score/date chronology, explicit rest/support features, solid Elo discrimination and separate joint-distribution research. Weaknesses: no possession components or player availability, modest home-probability bias, and an unresolved close-margin distribution artifact. No tested block passed. Further research should first bind governed team boxes and build possession/pace/efficiency features; player-level work follows only after a revisioned pregame availability feed exists.
