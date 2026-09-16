# Claude handoff — forecast delivery timing

Type: **delivery-status update + producer scheduling repair**. This does not activate a consumer change.

Prepared: 2026-09-14T23:51:33.737020Z (2026-09-14T19:51:33.737020-04:00).

A real producer timing defect existed: the deployed T-5 research deadline and T-30 fast-check boundary could place an otherwise valid publication after AISP's T-15 decision deadline. No September 14 game was shown to be affected by that timing defect. Nine controlling V18 forecasts were published and imported before their decision windows. ATL–CHC was not published because Cubs active-pitching-roster evidence remained older than 30 hours; its 19:25 EDT decision deadline passed.

The repair is committed and frozen at `4757da061139e6196450bd43653ee1ecc850ba58`, with a T-45 delivery target, five-minute T-60 checks/retries, separate T-15/T-5 labels and a dispatcher-jitter fix. Windows denied S4U task re-registration. The existing task and deployment `9bb1a947fc863596433fac569822ad95f2c71dac` remain healthy. An administrator must re-register that existing task through `scripts/install_mlb_v18_unattended.ps1`; do not add a second scheduler.

| Game | MLBAM | Start EDT | Forecast suffix | Imported EDT | Latest decision EDT | Status |
|---|---:|---:|---|---:|---:|---|
| LAD@CIN | 824465 | 18:40 | 402d25a2426e | 15:48:32 | 18:22:16 | PUBLISHED_BEFORE_DECISION_WINDOW, IMPORT_CONFIRMED, DECISION_CONFIRMED |
| CWS@CLE | 824386 | 18:40 | 9450b5b6f734 | 16:26:34 | 18:22:16 | PUBLISHED_BEFORE_DECISION_WINDOW, IMPORT_CONFIRMED, DECISION_CONFIRMED |
| DET@TOR | 822765 | 19:07 | 9287f14baa17 | 17:41:39 | 18:47:13 | PUBLISHED_BEFORE_DECISION_WINDOW, IMPORT_CONFIRMED, DECISION_CONFIRMED |
| BAL@NYM | 823575 | 19:10 | b98c8ce9d4ec | 15:48:32 | 18:52:24 | PUBLISHED_BEFORE_DECISION_WINDOW, IMPORT_CONFIRMED, DECISION_CONFIRMED |
| ATL@CHC | 824629 | 19:40 | — | — | — | INPUTS_PENDING, DEADLINE_MISSED |
| NYY@MIN | 823656 | 19:40 | f7c4f1f3d4cf | 17:31:04 | 19:22:15 | PUBLISHED_BEFORE_DECISION_WINDOW, IMPORT_CONFIRMED, DECISION_CONFIRMED |
| SF@STL | 823006 | 19:45 | f8776311bb20 | 16:06:27 | 19:27:21 | PUBLISHED_BEFORE_DECISION_WINDOW, IMPORT_CONFIRMED, DECISION_CONFIRMED |
| SD@COL | 824308 | 20:40 | e4b1f04485e2 | 17:56:49 | — | PUBLISHED_BEFORE_DECISION_WINDOW, IMPORT_CONFIRMED |
| SEA@LAA | 823981 | 21:38 | 84a4806590ef | 18:57:06 | — | PUBLISHED_BEFORE_DECISION_WINDOW, IMPORT_CONFIRMED |
| MIA@AZ | 825034 | 21:40 | 0e90e5784bf9 | 19:36:52 | — | PUBLISHED_BEFORE_DECISION_WINDOW, IMPORT_CONFIRMED |

NFL DEN@KC starts 20:15 EDT (00:15 UTC). Its final window is 19:45–20:00 EDT. CURRENT v7 `2d9d0197…c487aec9` is imported and valid for fallback/reuse; its 4.30% mass is exactly 430 equal-score simulated finals, not an “other” category. At 19:49:35 EDT, AISP persisted decision `94f5efe0-e006-4e8a-bfdd-7c4246961dd9` as `QUALIFIED_BET` / `AWAY`, bound to that exact v7 forecast. The job receipt then failed with `Object of type UUID is not JSON serializable`. Preserve the persisted decision and fix the consumer-owned result serializer; do not recreate the decision to hide the failed receipt.

Use `timing-audit.json` for full forecast IDs, canonical identities, source/creation/publication/import clocks, predictions, evidence gates, package hashes and exact decision bindings. No consumer scheduling change is requested.
