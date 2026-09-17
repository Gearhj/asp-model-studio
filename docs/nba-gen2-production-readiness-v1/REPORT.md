# NBA production readiness and Gen2 team-box foundation

## Disposition

**NBA_GEN1_PRODUCTION_BASELINE_V1 is staged and inactive.** Gen2 was not fit.
The authorized historical intake stopped fail-closed after the first licensed
team-box response exposed unresolved minutes/overtime and rebound semantics.
The existing Gen1 baseline is therefore the selected production-capable
fallback. No forecast was relabelled, no scheduler was installed, and no AISP
state changed.

## Source decision and activity

NBA.com Stats was rejected before acquisition because the current NBA.com
Terms of Use prohibit NBA Statistics in connection with gambling activity and
restrict comprehensive regularly updated databases without consent. `nba_api`
would wrap the same endpoints and does not change that authority. NBA.com
activity was zero requests, zero bytes, and zero cost.

The selected alternative was the retained SportsDataverse/hoopR ESPN-derived
team-box release, licensed CC BY 4.0. One response was acquired:

| Item | Result |
|---|---:|
| Asset | `team_box_2019.parquet` |
| Season scope | 2018-19 regular season and playoffs, separate `season_type` values |
| HTTP requests | 1 |
| Bytes | 152,257 |
| SHA-256 | `3f3f15ccfd1f676e0aaf5bfbdb8fd5cd69f9a21a4961cd4f6337d857593c788a` |
| Cost | $0 |
| NBA.com requests | 0 |

The immutable failure receipt is
`C:\Users\james\asp-data-staging\nba\gen2-team-box-v1\receipts\sha256\632125f21647099fa5df121dc68f872559581628c605758b963faf433da0ec32\acquisition-failure.json`.
Raw bytes remain private and outside Git.

## Population integrity

The retained response contains 2,628 team rows and 1,314 games: exactly two
opponent rows per game, 1,314 home and 1,314 away rows, no duplicate
`(game_id, team_id)` key, no orphan opponent joins, no required traditional-stat
nulls, and no score-formula or opponent-score failures. All possession
component denominators are positive.

It does not contain minutes or an overtime-period field. The provider's
`total_rebounds` exceeds `offensive_rebounds + defensive_rebounds` on 2,613 of
2,628 rows, median difference eight. This likely represents a different team-
rebound convention, but it cannot be silently treated as the requested
reconciled REB field. A declared addendum proposed joining the matching licensed
schedule exports for `status_period`, deriving team minutes as `240 + 25*OT`,
and retaining provider total rebounds separately from `OREB + DREB`. Automatic
approval review enforced the requested stop-on-schema-instability rule before
additional requests.

Because overtime and rebound semantics are unresolved and only one season is
present, no governed multi-season population identity was issued and no Gen2
feature or model comparison ran.

## Selected baseline

The fallback is the exact existing configuration
`NBA_GEN1_ELO_WIN_RIDGE_A100_ORDINARY_REST_V1`:

* Corrected Ridge alpha 100 supplies expected team points.
* Chronological Elo supplies winner probabilities independently.
* `NBA_GEN1_JOINT_FINAL_PAIRED_OOF_LATTICE_V1` supplies the retained 10,000-draw
  joint final-score distribution when distribution output is required.
* `NBA_GEN1_CLOSE_MARGIN_PARITY_TRANSPORT_R8_V1` remains disabled. It improved
  one-point-mass realism but did not establish a meaningful proper-score gain.

The refit binds 8,177 training games from 8,289 historical games through the
2025-26 season. Historical inputs are Category A finalized-record
reconstruction, not certified historical publication vintages.

### Reused assessment evidence

| Evidence | Games | Score MAE | Margin MAE | Total MAE | Winner log loss | Brier | AUC |
|---|---:|---:|---:|---:|---:|---:|---:|
| 2023-24 | 1,225 | 9.31 | 11.07 | 14.78 | 0.616 | 0.214 | 0.714 |
| 2024-25 | 1,221 | 9.28 | 10.95 | 14.90 | 0.617 | 0.214 | 0.716 |

| Joint residual evidence | Value |
|---|---:|
| Games | 7,009 |
| Energy score | 10.434157 |
| Total CRPS | 10.755059 |
| Margin CRPS | 7.873538 |
| Winner log loss | 0.625271 |
| Winner Brier | 0.217916 |
| Simulated one-point mass / observed | 7.78% / 4.01% |

These are reused inspected historical results. They are not a fresh Gen2
assessment or proof of wagering profitability.

## Production boundary

The content-addressed handoff sets `productionLabelAllowedAfterExplicitActivation=true`
but remains `STAGED_INACTIVE`. It grants no wagering, decision, position, or
scheduler authority. Existing BOS-DET point and joint forecasts remain immutable
research forecasts and cannot be relabelled as production.

The staged scheduler descriptor names one future canonical owner,
`ASP NBA Forecast Publisher`, but installs nothing. The prospective 2026-27
team-box hook is designed to run after each governed final, retain a revisioned
source object, and update features only for later targets. It is not created or
activated.

## Exact next steps

1. Renew authorization to continue the licensed hoopR addendum: seven remaining
   team-box files plus eight schedule files, 15 additional successful requests,
   total planned requests 16, under 256 MiB and $0.
2. Reconcile `status_period`, minutes, regular season/playoffs, aliases, and
   rebound semantics; then issue the governed population identity.
3. Only after that population passes, freeze and run the Ridge/Elo, Ridge+box,
   and one nonlinear chronological comparison.
4. Separately authorize the supported NBA owner installation and AISP pin to
   activate the staged Gen1 baseline. Activation must generate a new eligible
   prospective forecast rather than relabel the retained BOS-DET research files.

