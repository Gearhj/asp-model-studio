# MLB_STARTER_DURATION_V1

## Scope, target, and time

`MLB_STARTER_DURATION_V1` is `CONDITIONAL_ON_HISTORICAL_STARTER_IDENTITY`.
It predicts duration for the supplied historical starter identity; it does not
predict who starts. Batters faced (`stat_p_bfp`) is the primary target and outs
(`stat_p_ipouts`) is secondary. Inning-reach labels are `outs >= 15`, `>= 18`,
and `>= 21`. The identity conditions the row and its strictly prior history but
is not a model feature.

Every source must satisfy `source.final_available_date < target.game_date`.
Same-date, current-game, and future evidence is excluded. Live execution binds
the exact FD1 dataset, identity bridge and join audit, Phase 3 authority,
dynamic-state/history-index artifacts, source partitions, contract SHA,
revision, and creation time. This component has no retrospective candidate
pool and makes no pre-run coverage claim. Lack of a roster or starter
announcement feed is a prospective limitation, not automatic blocking.

## Frozen features and candidates

The exact feature order is:

`prior_starts_7d`, `prior_starts_14d`, `prior_starts_30d`, `prior_bfp_7d`,
`prior_bfp_14d`, `prior_bfp_30d`, `prior_outs_7d`, `prior_outs_14d`,
`prior_outs_30d`, `previous_start_bfp`, `previous_start_outs`,
`trailing_3_start_mean_bfp`, `trailing_3_start_mean_outs`,
`trailing_5_start_mean_bfp`, `trailing_5_start_mean_outs`,
`team_prior_date_mean_bfp`, `team_prior_date_mean_outs`,
`starts_previous_30d`, `days_rest`, `season_to_date_start_count`,
`season_to_date_mean_bfp`, `season_to_date_mean_outs`, `prior_season_bfp`,
`prior_season_outs`, `early_season_indicator`,
`dynamic_pitcher_log_odds_strikeout`,
`dynamic_pitcher_log_odds_walk_hbp_ci`,
`dynamic_pitcher_log_odds_home_run`, `dynamic_pitcher_log_odds_single`,
`dynamic_pitcher_log_odds_double`, `dynamic_pitcher_log_odds_triple`,
`dynamic_pitcher_log_odds_bip_out`, `dynamic_pitcher_missing_history`,
`dynamic_pitcher_ess`.

`S0` is global training-fold mean/median. `S1` is pitcher rolling location with
`S0` fallback. `S2` is Ridge regression with alpha selected from
`{0.1, 1.0, 10.0}` inside date-atomic inner 2023. `S3` is optional bounded
histogram gradient boosting (`maxIter=100`, `maxDepth=4`,
`learningRate=0.05`). The three inning-reach probabilities use bounded L2
logistic heads and are projected so `P21 <= P18 <= P15`.

## Folds, metrics, and decision

Inner tuning uses 2023 only; selection is 2024 only; 2025 is evaluation-only.
Public metrics are `bfpMae`, `bfpRmse`, `bfpMedianAbsoluteError`, `outsMae`,
`outsRmse`, `outsMedianAbsoluteError`, `reach15LogLoss`, `reach15Brier`,
`reach15Calibration`, the corresponding `reach18*` and `reach21*` fields, and
`earlySeasonBfpMae`. Whole-game bootstrap comparisons are reported against
both `S0` and `S1`.

The terminal enum is exactly `STARTER_DURATION_RESEARCH_COMPONENT`,
`STARTER_DURATION_RESEARCH_BASELINE`, `STARTER_DURATION_REJECTED`, or
`STARTER_DURATION_BLOCKED`. Component status requires the selected model to
improve both BFP MAE and BFP RMSE against both `S0` and `S1` in both 2024 and
2025. Mixed/tied evidence is baseline, consistently worse evidence is
rejected, and integrity failure is blocked.

Live execution is a supervised worker process with a 90-minute
starter-duration-stage hard stop, eight-hour overall stop, 90-second
progress-silence stop, and 8-GiB process-tree RSS stop. The worker emits an
independent heartbeat every 30 seconds; a supervisor stop prevents
registration while preserving completed content-addressed checkpoints.

Content-addressed runtime JSON/Parquet bodies embed creation time, revision,
dataset/bridge/Phase-3/component-contract authorities, fold, exact source
partitions, and target order. References carry the non-circular artifact ID,
SHA-256, bytes, media type, and governed logical URI. Exchange writes are
prohibited.
