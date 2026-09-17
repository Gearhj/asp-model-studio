# NBA_GEN1_PRODUCTION_BASELINE_V1 model card

Status: staged, inactive production-capable fallback.

Expected scores come from corrected Ridge alpha 100 using 78 chronological
score/date, Elo, rest, support, variability, and schedule-density features.
Winner probabilities come from Elo as an independent output. A paired
chronological out-of-fold residual sampler can produce 10,000 coherent home and
away final-score draws, totals, margins, and intervals.

The model excludes possessions, Four Factors, injuries, lineups, projected
minutes, player strength, referees, and travel. Historical source vintages are
reconstructed from finalized records. The joint sampler has excess one-point
mass. The close-score challenger remains disabled because its proper-score gain
was negligible.

Authority after this task: no active scheduler, no active production pin, no
wagering or decision authority, and no relabeling of existing research forecasts.

