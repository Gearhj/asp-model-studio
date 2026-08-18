# MLB_LINEUP_PROJECTION_V1

## Scope and authorities

`MLB_LINEUP_PROJECTION_V1` is a retrospective research contract for batter
start probabilities and a deterministic nine-player batting-order estimate. It
is not a roster, official-lineup, game-simulation, betting, or deployment
authority. Canonical player UUIDs are exact join, grouping, lineage, and final
tie-break keys only; they are never model features.

Every live materialization binds the exact registered FD1 dataset manifest and
partition authority, MLB identity-bridge manifest/alias/dimension/join-audit
authorities, Phase 3 feature authority, `MLB_DYNAMIC_PLAYER_STATE_V1`, the
source partition IDs, contract SHA, code revision, and creation time. Fixture
mode alone may represent dynamic state as explicitly missing.

## Population, eligibility, and pool

The binary target is `actual_starting_lineup`; `actual_batting_order` is
evaluation-only. Complete-lineup eligibility is derived per `game_id`: there
must be exactly two team groups, and each group must contain exactly nine
starter markers with non-null order set `{1,...,9}`. Live execution reconciles
the derived eligible-game counts to the parent manifest authority exactly:
2,423 (2023), 2,418 (2024), and 2,420 (2025). All lineup target and order
metrics use only this eligible population; excluded games are counted in
coverage evidence.

For target date `D`, the pool is the deterministic union of:

- current-season prior appearances for the same team;
- same-team participation in the trailing 45 days; and
- prior-season same-team participation only during the first 45 target-season
  days.

Every source must satisfy `source.final_available_date < D`. Same-date rows,
including an earlier scheduled doubleheader, are excluded. Current target
participants are never injected. Uncovered positives and empty pools are
measured. No pre-run live pool size or coverage is claimed; the frozen
acceptable coverage threshold is `0.95`. Missing roster/transaction/injury
feeds are a coverage and prospective-use limitation, not automatic blocking.

## Frozen features and candidates

The exact ordered feature list is:

`prior_starts_7d`, `prior_starts_14d`, `prior_starts_30d`,
`prior_appearances_7d`, `prior_appearances_14d`,
`prior_appearances_30d`, `prior_pa_7d`, `prior_pa_14d`, `prior_pa_30d`,
`days_since_appearance`, `days_since_start`, `season_start_rate`,
`trailing_order_mean`, `trailing_order_mode`,
`prior_season_participation`, `early_season_indicator`,
`dynamic_batter_availability`, `dynamic_batter_ess`.

`L0` is the trailing start-frequency baseline. `L1` is regularized L2
logistic regression with `C` selected from `{0.05, 0.2, 1.0}` in the
date-atomic inner-2023 split. `L2` is optional bounded histogram gradient
boosting (`maxIter=100`, `maxDepth=4`, `learningRate=0.05`). Disabled optional
candidates are explicit and are never silently substituted.

The nine highest probabilities are selected with UUID as final tie-break.
Order is the deterministic probability-weighted historical-order estimator;
current target order is never a feature.

## Folds, metrics, and decision

All tuning is date-atomic within 2023. Candidate selection uses 2024 only;
2025 is one evaluation-only refit/evaluation fold. Public metric names are
`binaryLogLoss`, `brierScore`, `averagePrecision`, `calibration`,
`topLabelCalibration`, `poolCoverage`, `uncoveredPositiveCount`,
`totalActualPositiveCount`, `teamGameCount`,
`completeLineupEligibleTeamGameCount`, `top9Recall`, `topNinePrecision`,
`topNineF1`, `completeLineupRate`, `completeLineupRecoveryRate`,
`exactLineupRate`, `exactOrderRate`, `battingOrderMae`, and
`earlySeasonTop9Recall`. Whole-game deterministic cluster bootstrap evidence
compares the selected candidate with `L0`.

The terminal enum is exactly `LINEUP_RESEARCH_COMPONENT`,
`LINEUP_RESEARCH_BASELINE`, `LINEUP_REJECTED`, or `LINEUP_BLOCKED`.
`LINEUP_RESEARCH_COMPONENT` requires positive raw binary-log-loss improvement
over `L0` in both 2024 and 2025 and pool coverage at least `0.95` in both.
Mixed/tied valid evidence is baseline; consistently worse governing evidence
is rejected; integrity failure is blocked.

Live execution is a supervised worker process with a 90-minute lineup-stage
hard stop, eight-hour overall stop, 90-second progress-silence stop, and 8-GiB
process-tree RSS stop. The worker emits an independent heartbeat every 30
seconds; a supervisor stop prevents registration while preserving completed
content-addressed checkpoints.

Artifacts and checkpoints are content-addressed in ignored runtime storage.
Every JSON envelope and Parquet metadata body records the non-circular creation
time, revision, dataset/bridge/Phase-3/component-contract authorities, temporal
fold, exact source partitions, and target/class order. Artifact references
carry ID, SHA-256, byte count, media type, and governed logical URI. Exchange
writes are prohibited.
