# NBA reduced point/Elo research forecast — genuine future capture

One genuine future **point/Elo research forecast** is exported locally for **Boston at Detroit, October 20, 2026**, canonical game `nba-espn:game:401909088` / ESPN `401909088`. The retained schedule gives tipoff **2026-10-20T19:00:00Z**, with `time_valid=true` and matching source date/start-date/status-time fields in the separately bound clock review. This is the captured source's schedule revision; later revisions must retain this original object.

No AISP write, exchange publication or consumer acknowledgement has occurred. NBA remains research-only and unfunded.

## Exact artifacts

- Local index: `C:\Users\james\asp-model-studio\outputs\nba-gen1-long-gap-v1\future-point-export\sha256\27f766e341cc211317d61e7ed842d7bbff7521664da5b27a0776bfc5394a8767\index.json`
- Index physical SHA-256: `22a6748510653c50820aea4391a79040058d55230a793a3ee059597bc82d4a7a` — **679 bytes**.
- Forecast in that directory: `forecast.json`.
- Forecast physical SHA-256: `27f766e341cc211317d61e7ed842d7bbff7521664da5b27a0776bfc5394a8767` — **21,524 bytes**.
- Forecast ID: `nba-point:1b0f9b6fa8d5ce8adc2532664afd941eaf889b6bdf6d6a8013295c43ba1e554f`.
- Verification: [future-point-export-verification.json](C:/Users/james/asp-model-studio/outputs/nba-gen1-long-gap-v1/future-point-export-verification.json), SHA-256 `c81a2ae44a6c4241c177dbdf012239ab7055eb82aa0569a00a911b4177caf3c4`.

Verify physical hashes and byte counts without newline normalization. Follow the index's exact forecast reference and preserve its game, forecast ID, configuration, feature/model/source bindings and clocks. The schema is `NBA_GEN1_REDUCED_POINT_ELO_FORECAST_V1`; the [contract](C:/Users/james/asp-model-studio/docs/nba-gen1-long-gap-v1/POINT_FORECAST_CONTRACT.md) gives the field and input definitions.

## Forecast values and interpretation

| Quantity | Value |
|---|---:|
| Detroit expected points | 113.78511290268382 |
| Boston expected points | 111.93456692347031 |
| Expected total | 225.71967982615413 |
| Expected Detroit margin | +1.850545979213507 |
| Detroit win probability | 0.5811249470666738 |
| Boston win probability | 0.41887505293332616 |
| Final-game tie probability | 0 |

Score means are in points, including overtime. Probabilities are fractions from 0 to 1. **Ridge supplies score means; chronological Elo supplies win probabilities separately.** They are not derived from a shared joint population, and their favored teams are not forced to agree.

Combined configuration: `NBA_GEN1_ELO_WIN_RIDGE_A100_ORDINARY_REST_V1`. Point component: `NBA_GEN1_ORDINARY_REST_RIDGE_A100_V1`. The exact current research receipt, fitted model/preprocessor, training identities, rest-support treatment, executing code and raw 78-field snapshot are bound inside the forecast.

Both teams' raw recorded regular-season gaps are **190 days**. The frozen ordinary-rest treatment correctly marks both as `SEASON_OPENER_NO_ORDINARY_REST`: treated rest is unavailable, `rest_known=0`, `back_to_back=0`, and the treated difference is unavailable. These are not asserted to be 190 days of physical rest. The raw values and reasons remain retained.

**Joint draws, home/away/total/margin distributions, prediction intervals, total-line probabilities and simulation MCSE are unavailable.** `drawCount=0`; distribution fields are null. Do not derive Over/Under probabilities from the expected total, describe this as the 65-feature model, or present it as an assessed joint simulator. No box, possession, player, lineup, injury or overtime-period inputs have been fabricated.

## Original clocks and evidence classification

| Clock | Actual UTC timestamp |
|---|---|
| Schedule capture / forecast source cutoff | 2026-09-14T13:04:43.697362Z |
| Forecast creation completed | 2026-09-14T13:09:39.891972Z |
| Local export | 2026-09-14T13:09:39.901986Z |
| Captured scheduled tipoff | 2026-10-20T19:00:00Z |
| Exchange publication / AISP import | Unavailable; neither claimed |

This is a genuine pre-cutoff forecast with **Category-A reconstructed historical training**. Current history is bound to 8,289 real regular-season records through April 12, 2026; the refit uses 8,177 oriented targets. Coverage verifies all 82 preceding-season regular games for each target team and no intervening 2026–27 regular game at or before the cutoff. Original historical revision availability remains unknown; present captures do not retroactively certify earlier pregame vintages.

The final verification confirms exact physical bindings, loaded-model reproduction of the saved expected scores, exact Elo probability reproduction, probability mass one, score total/margin identities and creation/export before the captured tipoff. No forecast was regenerated for verification. Separately, 13 focused software checks and one real 2026 target-snapshot equivalence check establish mechanics; they are not additional forecasting observations or accuracy evidence.

The reproducible execution command used is retained below. It would create a **new** forecast version with new actual clocks if run again; it must not replace this original package.

```powershell
.venv/Scripts/python.exe -B scripts/forecast_nba_gen1_point.py `
  --current-receipt outputs/nba-gen1-long-gap-v1/current-research/receipt.json `
  --schedule-evidence outputs/nba-gen1-long-gap-v1/future-schedule-evidence-qualified.json `
  --history-coverage outputs/nba-gen1-long-gap-v1/current-history-coverage.json `
  --source-cutoff 2026-09-14T13:04:43.697362+00:00 `
  --output outputs/nba-gen1-long-gap-v1/future-point-export
```
