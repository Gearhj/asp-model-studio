# Reduced NBA point/Elo research forecast

`NBA_GEN1_REDUCED_POINT_ELO_FORECAST_V1` is separate from the original 65-feature joint simulator. It reports ordinary-rest Ridge score expectations and the unchanged chronological Elo winner probabilities as **independent channels**. It has no simulated draws, score distributions, total-line probabilities, intervals or overtime-resolution adjustment. Missing distribution fields are `null`; `drawCount` is zero.

The entry point is `server.sports_nba_gen1.point_forecast.build_point_forecast`. It uses the current fitted receipt, a genuine captured future schedule and an independently reviewed current-history coverage receipt. No source acquisition, model fitting, scheduler, account, decision, wager, AISP write or activation is performed. The existing strict joint-simulator contract remains unchanged.

Each physical reference is `{path, sha256, bytes}`. SHA-256 and byte count refer to exact delivered bytes, without newline normalization. Source capture and export times are actual clocks. Unknown historical revision vintages are not replaced with invented clocks.

## Current research receipt

Use `outputs/nba-gen1-long-gap-v1/current-research/receipt.json` once its real refit completes. Required entries:

- `models.ridge_a100_rest`: the `rest_study.fit_bound` receipt, including `artifact`, `trainingIdentitySha256`, `trainingGameIds`, `trainingLastDate`, `restSupport` and bound `numericalModules`.
- `models.elo`: the existing Elo model receipt, with the same identity/training/code bindings.
- `history.games`: bound normalized score-history Parquet.
- `history.contextMetadata`: bound JSON containing the explicitly projected `contextOnlyEvents` list, possibly empty. Cup outcomes remain excluded; dates affect calendar context only.
- `history.acquisition`: bound latest historical-source acquisition receipt with actual `acquiredAtUtc`.

These fitted receipts describe research artifacts, not independently certified future publication. Their `futurePublicationEligible=false` remains historically true. A genuine new forecast needs the separate schedule and coverage evidence below; no old receipt is modified.

## Genuine schedule evidence

The schedule JSON must contain:

| Field | Definition |
|---|---|
| `schema` | `NBA_GEN1_REDUCED_SCHEDULE_EVIDENCE_V1` |
| `dataClassification` | `REAL_UNSCRAMBLED_GAMES`; fixtures are rejected |
| `reviewedBy` | Named source/normalization review |
| `capturedAtUtc` | Actual capture timestamp with timezone, at or before source cutoff |
| `sourceObject` | Physical reference to retained real source bytes |
| `rightsEvidence` | Nonempty list of bound applicable source-use documents/reviews; flags alone do not confer rights |
| `target` | Exact identity-only object described below, reconciled to source bytes |

The exact target fields are:

```text
game_id, source_game_id, season_end, game_date,
home_team_id, away_team_id, home_team_code, away_team_code,
season_type, status, neutral_site, scheduled_tipoff_utc, source_revision
```

`season_end` is the integer season end year; `2027` means 2026–27. `game_date` is the source's Eastern-calendar date and must equal the scheduled UTC tipoff converted to America/New_York. Require `season_type=REGULAR`, `status=SCHEDULED`, `neutral_site=false`, distinct reconciled canonical teams and a nonempty source revision. No outcome, box, lineup or undeclared target field is accepted. Reconciled schedule revision/source identity must resolve postponements or replacements without duplicating a game.

## Current history coverage

The coverage JSON must contain:

| Field | Definition |
|---|---|
| `schema` | `NBA_GEN1_REDUCED_CURRENT_HISTORY_V1` |
| `reviewedBy` | Named completeness and identity review |
| `currentResearchReceiptSha256` | Exact bound current-research receipt |
| `targetGameId`, `teamIds` | Target game and both canonical teams |
| `sourceCutoffUtc`, `completeThroughUtc` | Both equal the requested forecast cutoff |
| `regularSeasonMembershipComplete` | `true` only after checking actual retained schedule/completed-game membership |
| `missingGameIds` | Empty list; unsupported intervening regular games cannot be silently omitted |
| `identityReconciled` | `true` backed by actual mapping evidence |
| `historyPopulation`, `contextMetadata` | Exactly the current receipt's bound populations |
| `evidence` | Nonempty physical references supporting completeness and identity claims |
| `allHistoryRowsCoveredBySourceCaptures` | `true` only after all source lineage is reconciled |
| `sourceCaptures` | One entry per required historical source, each with actual `capturedAtUtc`, bound `sourceObject`, and nonempty `rightsEvidence` references |

The coverage receipt is a reviewed conclusion from actual schedule/history evidence, not permission to invent a `complete` flag. Applicable published data terms can establish rights; no bespoke vendor permission is required if those terms and existing authorization cover the work. A currently acquired finalized historical record can support a future forecast after its real capture. This does not certify that record's historical revision availability before earlier games.

Targets, same-date rows and later rows are excluded by metadata before history scores enter target construction. A direct state snapshot reproduces all 78 existing numeric fields without adding a dummy target final. Both teams need at least five current/prior-season games. The frozen fitted rest treatment handles unsupported ordinary-calendar-rest inputs. No boxes or overtime periods are required for this reduced output.

## Output and clocks

Require `schedule capture <= source cutoff <= actual execution start < original tipoff` and completion before tipoff. Every required historical source must have been captured no later than cutoff. A forecast created or exported after its original deadline is unavailable.

`pointExpectations` contains home, away, total and home-margin means in points, including overtime. `winnerProbabilities` contains home/away fractions from the existing Elo formula and structural final-game tie probability zero. These probabilities do not come from the Ridge scores. Do not imply a shared joint distribution or derive over/under probabilities from these means.

The object retains raw feature values/hash, rest-treatment reasons, model/preprocessor/training identity, executing forecast code hash, schedule/history bindings, actual creation time and separate export time. `publishedAtUtc` stays `null`: the local exporter does not publish to AISP or assert consumer confirmation. No Monte Carlo precision is reported because no simulation is run.

Local export uses `sha256/<physical forecast hash>/forecast.json` and a checksummed `index.json`. It preserves the original fitted receipt and source artifacts. All authority flags remain research-only/unfunded, without production, wagering, scheduler or account authority.

```powershell
.venv/Scripts/python.exe -B scripts/forecast_nba_gen1_point.py `
  --current-receipt outputs/nba-gen1-long-gap-v1/current-research/receipt.json `
  --schedule-evidence <real-captured-schedule.json> `
  --history-coverage <reviewed-current-history-coverage.json> `
  --source-cutoff <actual-UTC-cutoff> `
  --output outputs/nba-gen1-long-gap-v1/future-point-export
```

Placeholders make this example unusable until actual evidence exists. Missing evidence returns `UNAVAILABLE_NO_FORECAST_EXPORTED` with its precise reason. The unit fixtures verify mechanics only and must never be offered as a real forecast.
