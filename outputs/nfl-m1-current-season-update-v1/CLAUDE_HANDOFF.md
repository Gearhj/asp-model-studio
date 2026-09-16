Claude — NFL M1 current-season input update

Created 2026-09-13T19:48:02.326743+00:00. This is a newly created documentation handoff. Original forecast, source and publication clocks remain in the bound artifacts.

Ready: 15 eligible games in the original seven-day publication window; **1 new CURRENT forecast produced and published, 14 unchanged forecasts reused, 10 already-started Week 1 games excluded from new publication**. The new forecast is PIT at NE, `2026_02_PIT_NE` / `nflverse:2026_02_PIT_NE`, kickoff September 20 at 17:00Z. Its import is **not confirmed**: the single exact consumer check returned zero rows. [Consumer receipt](C:\Users\james\asp-model-studio\outputs\nfl-m1-current-season-update-v1\consumer-acknowledgement-pit-ne-current-v9.json).

Use the existing `import-nfl-shadow-forecast-bundle` workflow and NFL locator:

`C:\Users\james\asp-model-exchange\aisp-daily-forecast-bundles\nfl-2026-research-shadow-index.json`

Physical SHA-256 at this handoff: `d3daaf6288d5fc92323521e53d7ae532b8940ffd9cfbcb65c1e585c3ad646111`; 29,884 bytes. This navigation file may advance under existing scheduling; inspect any successor and preserve exact child identities.

The current September 20 aggregate import bundle is:

`C:/Users/james/asp-model-exchange/aisp-daily-forecast-bundles/sha256/c3bdb77c587cde795e771569b93df099e692885140c5bbfe8a5feefb541af88f/bundle.json`

SHA-256 `c3bdb77c587cde795e771569b93df099e692885140c5bbfe8a5feefb541af88f`. It preserves 28 original EARLY/CURRENT children across 14 games; eight of those games belong to this seven-day handoff selection. Deduplicate by exact forecast ID and retain earlier versions. The new single-forecast original bundle is `C:\Users\james\asp-model-exchange\aisp-daily-forecast-bundles\sha256\70b79b2164a104cbd3fd13bf73639b447a5ef017b89d80736160e22d0f7a7d6f\bundle.json`, SHA-256 `70b79b2164a104cbd3fd13bf73639b447a5ef017b89d80736160e22d0f7a7d6f` (61,608 bytes).

Exact new child: `asp-sports-game-forecast:sha256:04a40eb0855d57beb207eafbd6de4a751f0e894393f6f40073adae0864eb5ce5`, CURRENT v9. Prior CURRENT v8: `asp-sports-game-forecast:sha256:ab0668e22a8613c4d5704fe00d07a9ddeb8e4df2e957728a89562d84159693a5`. Engine remains **NFL_M1_XGBOOST / NFL_M1_2026_RESEARCH_SHADOW_V1**; 197 features, existing fitted preprocessing, weights and paired residual authority remain unchanged. Model manifest `ab9c066052b288f3f6162d8f8558e673988fb52172c72fe00aa855aa800a45e9`, model binary `7bec06646fd5035380107501d07e139425ac483a47e02e0bbbd56301124fb8fd`. New child producer revision `08c1582c8b371ae9ae55e6c369b53975039e8487`. Research-only/execution/promotion flags remain unchanged.

PIT–NE expected away/home scores: 17.6889/24.6129 → 17.8508/24.8582. P(NE/PIT/tie), as fractions: .6976/.2708/.0316 → .6989/.2700/.0311. Expected home margin: 6.9240 → 7.0074; total: 42.3018 → 42.7090. Retained population: 10,000 original paired score draws per forecast. This is an input update, not evidence of improved accuracy.

The three original NFL core source contracts stopped at 2025. V2 admits the verified 2026 PBP/player/team assets while preserving V1 historical verification. Both completed 2026 games now have PBP. New England's September 9 game updates 80 PIT–NE inputs. Player/team weekly tables are available, but named-player and pregame-QB features are not active M1 inputs.

Source cutoff: September 13 19:13:28.131274Z. Forecast cutoff: 19:15:52.815675Z; embedded availability: 19:15:58.088640Z. The numerical-run clock 19:15:58.348722Z preceded the physical index write at19:22:14.839501Z. Handoff-only recovery finished 19:46:03.968806Z. These are distinct clocks; this later document does not restamp the forecast.

The rolling publisher published successfully, then its handoff builder wrongly included already-started peers from a full retained slate. Commit `dbc1bcf` fixes selection against the complete Foundation-verified activation window, with additive `selectionScope` accounting in existing handoff V2. Original source bundles remain complete. Recovery generated **zero forecasts** and left the forecast index/locator unchanged.

Verified rolling handoff: `C:\Users\james\asp-model-studio\outputs\nfl-m1-current-season-update-v1\publication\sha256\fc386f141cc4220556bc4c6d314c7fdf2ac96d702831ab64e89254510f67fc06\handoff.json`; SHA-256 `fc386f141cc4220556bc4c6d314c7fdf2ac96d702831ab64e89254510f67fc06`; 57,152 bytes. It binds 15 selected games and four per-date handoffs. [Result and preservation receipt](C:\Users\james\asp-model-studio\outputs\nfl-m1-current-season-update-v1\objects\sha256\c284655973126014f7f57a8aa707d365860f3b0c386bf78498e4054be6912fdd\update-result.json) records 2,245 preserved original indexed forecast entries. [Decision/miss report](C:\Users\james\asp-model-studio\outputs\nfl-m1-current-season-update-v1\DECISION.md) includes the two original pregame games, all distribution scores and governed final identities.

Existing AISP producer settings point to this checkout and its virtual environment; recent CURRENT/FINAL/import/final-ingest/evaluation jobs succeeded. Two operational follow-ups remain with Claude: include actual imported NFL source/dependency paths in the existing dirty-code guard; identify who invokes the repaired Foundation source sync before normal current publication. No recurring Foundation-refresh owner was established by the inspection. The existing command is `.venv/Scripts/python.exe -B -m scripts.sync_nfl_current_season --through latest-completed` using its established source scope and limits. This task added no scheduler and changed no AISP settings.

Source intake used three asset downloads/419,166 bytes plus three metadata queries/1,889,129 bytes; known incremental cost $0. No fitting or new source accounts. The source cap repair is commit `08c1582`; handoff recovery/scope code is `dbc1bcf`. Existing MLB publication, studies and completed NFL restoration are preserved.

Reproduce retained reporting: `.venv/Scripts/python.exe -B scripts/report_nfl_m1_input_update.py`. The existing publication command used was `.venv/Scripts/python.exe -B -m scripts.publish_nfl_rolling_shadow --window-days 7`. Future ordinary runs preserve unchanged forecasts through the existing input-value checks.
