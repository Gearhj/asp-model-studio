NFL M1 current-season update and completed-game review — September 13, 2026

The demonstrated defect was a 2025 availability cap on three existing source families. Current 2026 nflverse PBP/player/team assets were available. The repair admits them through an explicit V2 coverage policy while retaining exact V1 verification and all 326 earlier partitions. Fitted M1 components and feature definitions are unchanged.

The active producer is `NFL_M1_XGBOOST / NFL_M1_2026_RESEARCH_SHADOW_V1`, using 197 LONG_HISTORY_CORE inputs and 10,000 paired empirical-residual score draws (seed 731001). It is separate from the NFL play-level research simulator. Model manifest `ab9c066052b288f3f6162d8f8558e673988fb52172c72fe00aa855aa800a45e9`, binary `7bec06646fd5035380107501d07e139425ac483a47e02e0bbbd56301124fb8fd`, and February 8, 2026 training cutoff remain fixed. Calibration and research-only authority remain unchanged.

**Actual input freshness.** The prior Foundation already had two completed games, superseding the old zero-game receipt. Their scores entered the features, but all 20 PBP-derived metrics were missing in the 2026 team-game rows for NE, SEA, SF and LAR. Those metrics previously ended on February 8; they now extend through September 10, matching both completed 2026 games in the source. No newer timestamp is being substituted for a numerical change.

| Existing source family | 2026 records | Source asset updated UTC | Captured UTC | Bytes |
|---|---:|---|---|---:|
| [play_by_play](https://github.com/nflverse/nflverse-data/releases/download/pbp/play_by_play_2026.parquet) | 323 | 2026-09-13T13:48:37Z | 2026-09-13T19:11:47.184082+00:00 | 294,820 |
| [weekly_player_stats](https://github.com/nflverse/nflverse-data/releases/download/stats_player/stats_player_week_2026.parquet) | 135 | 2026-09-13T13:50:13Z | 2026-09-13T19:11:47.533480+00:00 | 71,654 |
| [weekly_team_stats](https://github.com/nflverse/nflverse-data/releases/download/stats_team/stats_team_week_2026.parquet) | 4 | 2026-09-13T13:50:16Z | 2026-09-13T19:11:47.961336+00:00 | 52,692 |

The modern release tags are `pbp`, `stats_player`, and `stats_team`. The older player_stats release is deprecated; its presence does not establish current availability. Release-container dates (2022/2025) are separate from the 2026 asset-update clocks. The versioned registry still preserves all original season ranges except the three approved core families, extended from 2025 to 2026. Normal source discovery remains dynamic; the one-time intake pins this exact snapshot.

Source intake: three asset downloads, 419,166 bytes; three preceding metadata queries, 1,889,129 bytes; 2,308,295 response-body bytes in total; known incremental cost $0. The one-time asset allowance is fully used and persists across retries. Raw files remain in external staging. [Source receipt](C:\Users\james\asp-model-studio\outputs\nfl-m1-current-season-update-v1\source-intake.json) records paths, byte counts, digests, rights and clocks. Metadata responses were not retained as raw files; the observed fields are preserved and actual downloaded bytes match the pinned upstream checksums.

Foundation changed from `f1544974dff02e2ef26f44d0384c5635e99cfe89d9e0cf8e201488cd3eafb6d8` to `b2ee9217a8f67312416316b8075da8a49ca7839abe0d83168b5d531bb1e1be39`, published at **19:13:28.131274Z**. Bronze is `37696e4f1f34fb11a10c25927adcea234c7251330be371dbc3fc248201ac73d9`. Weekly player/team tables are now populated; the active M1 predictor uses team-game history, not named-player or starting-QB features.

**Concrete future update: PIT at NE, September 20 at 17:00Z.** New England’s September 9 game changes 80 inputs: 20 season-to-date values and the corresponding last-4/8/16 averages. All other 14 vectors in the declared seven-day window are unchanged. Examples (fractions/rate units retain the existing definition):

| NE input | Before | After |
|---|---:|---:|
| home_offensive_epa_per_play_season_to_date | missing | -0.10962827 |
| home_pass_epa_per_play_season_to_date | missing | -0.12837095 |
| home_turnover_rate_season_to_date | missing | 0.03529412 |
| home_offensive_epa_per_play_last_4 | -0.24193294 | -0.20885677 |
| home_success_rate_last_4 | 0.34568038 | 0.36373789 |
| home_sack_rate_last_4 | 0.14501335 | 0.12661716 |

| PIT–NE snapshot | Source cutoff UTC | Expected PIT–NE | P(NE / PIT / tie) | Margin NE−PIT | Total |
|---|---|---:|---|---:|---:|
| CURRENT v8, `ab0668e2…` | Sept 12 19:44:59.784362 | 17.6889–24.6129 | .6976 / .2708 / .0316 | 6.9240 | 42.3018 |
| CURRENT v9, `04a40eb0…` | Sept 13 19:13:28.131274 | 17.8508–24.8582 | .6989 / .2700 / .0311 | 7.0074 | 42.7090 |

Old forecast ID: `asp-sports-game-forecast:sha256:ab0668e22a8613c4d5704fe00d07a9ddeb8e4df2e957728a89562d84159693a5`; created Sept 13 09:30:23.037035Z. New forecast ID: `asp-sports-game-forecast:sha256:04a40eb0855d57beb207eafbd6de4a751f0e894393f6f40073adae0864eb5ce5`; forecast cutoff 19:15:52.815675Z; forecast availability clock 19:15:58.088640Z; producer revision `08c1582c8b371ae9ae55e6c369b53975039e8487`. The index was physically written at approximately 19:22:14Z, before kickoff. These clocks remain separate from the later handoff creation.

A focused two-row inference check, with no new simulations, confirms the deterministic M1 score means changed from NE/PIT **24.507397/17.536741** to **24.754488/17.708284**. The published distributions retain their own 10,000 draws. Their small win-probability difference is below the roughly 0.46 percentage-point Monte Carlo standard error of either estimate; they are not a certified paired-Monte-Carlo comparison. This is an input update, not an observed accuracy gain.

**All completed eligible games at the declared 19:02:02Z snapshot.** Selection used completion/identity/clock metadata before reading score payloads. Both games had already finished; the forecasts themselves were genuinely frozen and imported before kickoff. No score-based subset or reconstructed historical forecast is used. Dates below are NFL schedule dates; probabilities are fractions.

| Game / original forecast | Expected away–home | Actual away–home | P(home / away / tie) | Log loss | NFL Brier | Absolute margin error | Absolute total error |
|---|---:|---:|---|---:|---:|---:|---:|
| NE–SEA 2026-09-09, [67584a9c…](C:\Users\james\asp-model-exchange\aisp-daily-forecast-bundles\sha256\368e235de6586e3f716143b260cb2412f18a80ec71fe7f4b3f23bd6636dcdfd7\bundle.json) | 19.94–22.75 | 10–13 | 0.5736 / 0.3966 / 0.0298 | 0.555823 | 0.339997 | 0.1936 | 19.6900 |
| SF–LAR 2026-09-10, [1c1d19f1…](C:\Users\james\asp-model-exchange\aisp-daily-forecast-bundles\sha256\9d35ad743330e4f2027f43574339707f589e9d802754295d677f29a4460426e1\bundle.json) | 22.05–27.06 | 27–7 | 0.6394 / 0.3340 / 0.0266 | 1.096614 | 0.853096 | 25.0165 | 15.1113 |

Brier is **SUM of squared errors across HOME/AWAY/TIE** (range 0–2); no MLB zero-tie binary conversion is applied. Log loss is −ln(probability of the realized winner). One of two winner picks was correct; mean log loss .826219 and mean three-class Brier .596546. Both original populations retain 10,000 paired scores, allowing these distribution scores (lower is better):

| Game | Away CRPS | Home CRPS | Total CRPS | Margin CRPS | Joint energy |
|---|---:|---:|---:|---:|---:|
| NE–SEA | 6.0094 | 5.8862 | 12.6449 | 2.7707 | 9.0062 |
| SF–LAR | 3.3508 | 14.9635 | 8.8767 | 18.0394 | 14.6846 |

NE–SEA’s total 23 is at the 6.25th inclusive percentile of its frozen population; its three-point winning margin was predicted closely. LAR’s seven points are at the 1.39th percentile, and its −20 margin at the 3.06th. The missing later-season intake does not explain either opening-game miss: neither forecast could have used a completed 2026 prior game at its original cutoff.

Observed localization: Seattle’s source records Darnold injured on a Q1 12:27 sack after two pass attempts; Lock supplied 22 of its 24 attempts. New England threw three fourth-quarter interceptions. LAR had 10 possessions versus SF’s nine, two giveaways and two failed fourth downs, including fourth-and-goal at SF’s one. Its three red-zone possessions produced one TD, one turnover on downs and one clock-ending drive. LAR had two 20+ yard plays versus SF’s one, so explosive scarcity alone does not explain seven points. Bennett’s three attempts came on the last drive after the 27–7 deficit. These are observed pathways, not conditional event-probability calibration findings. M1 has no retained play/drive predictions against which to make that claim.

No compatible timestamp-bound market benchmark was used. Schedule price fields lack a certified quote observation clock. Simulation MCSE describes sampling precision, not total model/input uncertainty.

**One next experiment.** Compare one QB-participation-aware paired-residual sampler with M1’s existing pooled residual bank, keeping the fitted score regressors and other inputs fixed. The pooled bank already contains some injury/backup games; test whether genuinely pregame QB evidence improves their weighting. Use existing PBP passer identities and player-week evidence only in authorized chronological Development construction, with pregame QB/backup availability certified before each cutoff and scenario estimates trained before each assessment period. Historical pregame QB timing and suitable chronological residuals remain prerequisites. Realized substitutions, these two inspected results and sealed OOT cannot set the weights. Freeze one candidate and a complete future eligible slate before outcomes; retain 10,000 draws and shared randomness. Primary measure: joint energy score; winner log loss/Brier and total/margin CRPS are guardrails. Reject if improvement requires future participation knowledge, the predefined distribution score worsens, or winner performance deteriorates. A small first cohort may remain inconclusive.

Operational state: existing AISP producer settings point to this checkout and its virtual environment; recent CURRENT, FINAL, import, final-ingest and evaluation jobs succeeded. No scheduler or restoration state was changed. The inspected producer loads the current Foundation; no recurring Foundation-refresh owner was established. The existing repaired source-sync command is the supported refresh path. AISP’s existing dirty-code guard also omits some actual NFL source/dependency paths; Claude owns extending that guard and arranging source refresh within the existing workflow. No new scheduler is required.

Verification reused the established model/feature checks and scorers, added source-policy and handoff-selection regressions, reconciled the actual changed vectors, and preserved all eight unrelated dirty files. No model fit, recalibration, new provider account, MLB study change, sealed-study evaluation, reset, merge or push occurred. Operational historical feature materialization is distinct from a new historical evaluation.

Immutable scoring and governed final bindings:

- 2026_01_NE_SEA: final `cd264a36-6274-455c-8918-2447c7397175`, payload SHA-256 `1e7d2a6f1a558df28817613b83027962598fcedb0ca6aa4289b451cee521e258`.
- 2026_01_SF_LA: final `f1804c33-c1a0-43cd-a8c4-5ec13a4abe3c`, payload SHA-256 `d8b6dcfa9658f5fa393bc3126a770437af81236a058e509dd30d7c75b457b8cf`.

[Scoring receipt](C:\Users\james\asp-model-studio\outputs\nfl-m1-current-season-update-v1\miss-analysis\objects\sha256\6e10b9a6fc71623d3c3f167e17b3eed404ad3d19e43480c4be83cec3fd75d803\scoring.json) · [Final/import evidence](C:\Users\james\asp-model-studio\outputs\nfl-m1-current-season-update-v1\miss-analysis\governed-finals-and-imports.json) · [Postgame receipt](C:\Users\james\asp-model-studio\outputs\nfl-m1-current-season-update-v1\miss-analysis\objects\sha256\7e307823759ee56c58b3c001f004fbaaa605aa2805623b79e7d2df4a480db62c\postgame-diagnostic.json)

Reproduce the retained comparison without new forecasts:

```powershell
.venv/Scripts/python.exe -B scripts/report_nfl_m1_input_update.py
.venv/Scripts/python.exe -B outputs/nfl-m1-current-season-update-v1/miss-analysis/analyze.py
.venv/Scripts/python.exe -B outputs/nfl-m1-current-season-update-v1/miss-analysis/postgame.py
```

**Publication finish.** 1 new forecast produced and published; 14 unchanged forecasts reused across 15 eligible games. Ten already-started games received no new forecast. The handoff-only repair preserved the declared cohort and generated zero forecasts. [Verified rolling handoff](C:\Users\james\asp-model-studio\outputs\nfl-m1-current-season-update-v1\publication\sha256\fc386f141cc4220556bc4c6d314c7fdf2ac96d702831ab64e89254510f67fc06\handoff.json) (SHA-256 `fc386f141cc4220556bc4c6d314c7fdf2ac96d702831ab64e89254510f67fc06`). Consumer import remains unconfirmed at the one exact check. [Claude handoff](C:\Users\james\asp-model-exchange\aisp-daily-forecast-bundles\handoffs\sha256\bdeeea126d94d8131e4968790821aba8ec747a252629f1b47094462247c9c023\CLAUDE_HANDOFF.md). Source code commit `08c1582`; handoff code commit `dbc1bcf`.
