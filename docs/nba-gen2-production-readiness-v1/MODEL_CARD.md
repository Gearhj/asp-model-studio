# NBA production baseline model card

## Selected configuration

`NBA_GEN1_PRODUCTION_BASELINE_V1` remains the staged, inactive baseline.

Expected scores come from corrected Ridge alpha 100 using the established 78
chronological score/date, Elo, rest, support, variability and schedule-density
features. Winner probabilities come from chronological Elo as an independent
model output. `NBA_GEN1_JOINT_FINAL_PAIRED_OOF_LATTICE_V1` supplies the retained
10,000-draw joint distribution. The close-score challenger remains disabled.

## Gen2 decision

Two frozen team-box challengers were assessed on the exact common population:

* `GEN2_RIDGE_A100_TEAM_BOX_V1`
* `GEN2_HGB_L2_10_TEAM_BOX_V1`

They added prior-game possession, pace, offensive/defensive rating, effective
field-goal, turnover, offensive-rebound, free-throw and three-point features.
OREB and DREB were used directly. Source `total_rebounds` was preserved
separately. Completed schedule periods supplied overtime status and derived
team minutes without fabrication.

Neither challenger passed the frozen 2023-24 joint-energy and guardrail gate.
Ridge's primary difference was effectively zero with uncertainty spanning
material improvement and degradation; HGB was worse. Later Ridge improvements
are reused diagnostics and do not reverse the selection decision. No Gen2
artifact has production, publication or wagering authority.

## Evidence and limitations

The SportsDataverse/hoopR evidence is CC BY 4.0 Category A reconstructed
historical evidence. Current retrieval does not certify original historical
publication vintages. One corrupt team-box game is explicitly quarantined.
Playoffs are retained separately and were not pooled into regular-season
fitting or assessment.

Gen1 still excludes player availability, lineups, injuries, referees and
travel. Its joint residual distribution retains excess one-point mass. The
prospective 2026-27 team-box hook is designed but not installed.

Status: staged, inactive; no scheduler installed and no AISP pin changed.
