# MLB_BULLPEN_USAGE_V1

## Scope, target, and pool

`MLB_BULLPEN_USAGE_V1` is retrospective research for player/team-game relief
appearance probabilities plus conditional BFP/outs evidence. It is not a
prospective roster, availability, game-simulation, betting, or deployment
authority. Evaluation includes every primary target team-game, including
zero-reliever and empty-candidate-pool games.

For target date `D`, the candidate pool is the deterministic union of:

- current-season prior relief appearances for the same team;
- same-team relief appearances in the trailing 30 days; and
- prior-season same-team relief appearances only during the first 45
  target-season days.

All sources require `source.final_available_date < D`; same-date evidence and
current target participants are excluded. Uncovered positives, empty pools,
zero-reliever games, and exact denominators are persisted. No pre-run pool size
or coverage is claimed. The frozen acceptable coverage threshold is `0.95`.
Missing roster/transaction/injury/option feeds are an explicit coverage and
prospective-use limitation, not automatic blocking.

## Frozen features and candidates

The exact feature order is:

`appearances_3d`, `appearances_7d`, `appearances_14d`, `prior_bfp_1d`,
`prior_bfp_3d`, `prior_bfp_7d`, `prior_bfp_14d`, `prior_outs_1d`,
`prior_outs_3d`, `prior_outs_7d`, `prior_outs_14d`, `days_since_relief`,
`appeared_yesterday`, `appeared_on_two_consecutive_prior_days`,
`season_appearance_count`, `season_relief_share`, `season_bfp`, `season_outs`,
`prior_team_usage_rate`, `prior_season_relief`, `early_season_indicator`,
`dynamic_pitcher_log_odds_strikeout`,
`dynamic_pitcher_log_odds_walk_hbp_ci`,
`dynamic_pitcher_log_odds_home_run`, `dynamic_pitcher_log_odds_single`,
`dynamic_pitcher_log_odds_double`, `dynamic_pitcher_log_odds_triple`,
`dynamic_pitcher_log_odds_bip_out`, `dynamic_pitcher_missing_history`,
`dynamic_pitcher_ess`.

`B0` is the frozen recency/workload heuristic. `B1` is regularized L2 logistic
regression with `C` selected from `{0.05, 0.2, 1.0}` inside date-atomic inner
2023. `B2` is optional bounded histogram gradient boosting (`maxIter=100`,
`maxDepth=4`, `learningRate=0.05`). Candidate probabilities are not normalized
to force a reliever.

## Folds, metrics, and decision

Inner tuning uses 2023 only, selection uses 2024 only, and 2025 is
evaluation-only. Public metrics are `binaryLogLoss`, `brierScore`,
`averagePrecision`, `calibration`, `topLabelCalibration`, `poolCoverage`,
`uncoveredPositiveCount`, `totalActualPositiveCount`, `teamGameCount`,
`teamGameSetRecall`, `teamGameSetJaccard`, `top3Recall`, `top5Recall`,
`relieverCountMae`, `expectedRelieverCountMae`, `zeroRelieverAccuracy`,
`conditionalBfpMae`, `conditionalOutsMae`, and `earlySeasonSetRecall`.
Whole-game bootstrap evidence compares the selected candidate with `B0`.

The terminal enum is exactly `BULLPEN_USAGE_RESEARCH_COMPONENT`,
`BULLPEN_USAGE_RESEARCH_BASELINE`, `BULLPEN_USAGE_REJECTED`, or
`BULLPEN_USAGE_BLOCKED`. Component status requires, in both 2024 and 2025:
raw binary log loss strictly better than `B0`; raw Brier non-worse within
`1e-10`; raw top-label ECE at most `0.05`; all ten required reliability bins
finite and nonempty; and pool coverage at least `0.95`. Scaled evidence cannot
satisfy this gate. Mixed/tied evidence is baseline, consistently worse evidence
is rejected, and integrity failure is blocked.

Live execution is a supervised worker process with a 120-minute
bullpen-usage-stage hard stop, eight-hour overall stop, 90-second
progress-silence stop, and 8-GiB process-tree RSS stop. The worker emits an
independent heartbeat every 30 seconds; a supervisor stop prevents
registration while preserving completed content-addressed checkpoints.

All live bodies bind exact FD1, bridge/join-audit, Phase 3, dynamic-state,
source-partition, component-contract, fold, target-order, revision, and creation
authorities. JSON and Parquet artifacts are content-addressed in ignored
runtime storage; references carry ID, SHA-256, bytes, media type, and governed
logical URI. Exchange writes are prohibited.
