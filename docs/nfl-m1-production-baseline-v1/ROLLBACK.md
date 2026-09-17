# Rollback to research shadow

Rollback does not delete forecasts, finals, scores, positions, receipts or exchange evidence.

1. Remove the AISP operator values `NFL_PRODUCTION_HANDOFF_PATH` and `NFL_PRODUCTION_HANDOFF_SHA256`, or replace them with a separately reviewed, hash-pinned `NFL_M1_SHADOW_ONLY` handoff.
2. Reload only the existing `ASP Backend 8010` owner through its supported supervisor path.
3. Require `/api/v1/research/nfl-production-status` to return `NOT_RECEIVED` or the verified `NFL_M1_SHADOW_ONLY` status.
4. Confirm the ordinary research forecast, import and scoring jobs remain armed and no second scheduler exists.

The model, configuration, forecasts and scoring evidence are unchanged by this authority rollback.

