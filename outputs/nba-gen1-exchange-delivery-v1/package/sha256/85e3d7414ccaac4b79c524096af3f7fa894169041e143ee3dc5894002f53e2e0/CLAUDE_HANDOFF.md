# CLAUDE_HANDOFF — NBA early point/Elo research forecast

Import delivery index: `C:\Users\james\asp-model-exchange\nba-gen1-research-v1\point-elo-v1\packages\sha256\85e3d7414ccaac4b79c524096af3f7fa894169041e143ee3dc5894002f53e2e0\index.json`

**Package / physical index SHA-256:** `85e3d7414ccaac4b79c524096af3f7fa894169041e143ee3dc5894002f53e2e0` (9,455 bytes). The delivery directory uses this INDEX digest. The original local directory used the FORECAST digest; do not interchange them.

Forecast schema: `NBA_GEN1_REDUCED_POINT_ELO_FORECAST_V1`. Delivery envelope: `NBA_GEN1_POINT_ELO_EXCHANGE_INDEX_V1`.
Original forecast ID: `nba-point:1b0f9b6fa8d5ce8adc2532664afd941eaf889b6bdf6d6a8013295c43ba1e554f`.
Original forecast SHA-256: `27f766e341cc211317d61e7ed842d7bbff7521664da5b27a0776bfc5394a8767` (21,524 bytes).
Original local index SHA-256: `22a6748510653c50820aea4391a79040058d55230a793a3ee059597bc82d4a7a` (679 bytes), retained as `original-local-index.json`.

Verify raw physical bytes without newline normalization. Verify index hash equals package directory, then every `files` entry. Import `forecast.json` once by `(forecastId, forecastSha256)`; reject conflicting bytes for an existing ID. Original model/input bindings stay intact. The consumer reads retained values, not executable/pickle model files.

**Boston Celtics at Detroit Pistons** — canonical `nba-espn:game:401909088`, ESPN game ID `401909088`, Boston franchise `nba-neil:franchise:BOS`, Detroit franchise `nba-neil:franchise:DET`. Reconcile those source identities to AISP's NBA identities; do not join on date/team names alone. Captured schedule: **October 20, 2026, 19:00 UTC / 3:00 PM EDT**. The retained source explicitly marks the time valid. Preserve `game.source_revision` (`github-asset:552084615:sha256:d4ffe0d974dbec227af1ea5d731e0f36426839a170bfd0bbffc39b65f933a090`).

| Consumer value | Retained value | Meaning |
|---|---:|---|
| Boston expected points | 111.93456692347031 | Ridge alpha100 |
| Detroit expected points | 113.78511290268382 | Ridge alpha100 |
| Expected total / Detroit margin | 225.71967982615413 / +1.850545979213507 | Point expectations only |
| Boston win probability | 0.41887505293332616 | Separate Elo output |
| Detroit win probability | 0.5811249470666738 | Separate Elo output |
| Tie probability | 0 | Final NBA outcomes |

Probabilities are **fractions 0–1**; percentage display multiplies once. Points include overtime. Label the card **“Early research forecast — September 14, 2026”**. Label score means “Ridge expected points” and winner probabilities “Elo win probability — separate model output.” Do not imply a shared joint simulation or force their favored sides to agree.

Collapsed details should show `restSupportAudit`: both raw 190-day regular-season gaps were marked `SEASON_OPENER_NO_ORDINARY_REST`; treated rest/difference are null, rest-known and back-to-back indicators zero. They are not claims of 190 days of physical rest. Show missing player availability/strength, starters, lineups and injury inputs, plus historical-training revision limitations and original source/model bindings.

Keep `distributions.drawCount=0`; home, away, total, margin and interval distributions remain **null**. Over/Under probabilities, market fair prices, simulation intervals and MCSE are unavailable. Do not derive them from expected total or attach a simulation count. NBA stays research-only and unfunded: no account, wagers, decisions, bankroll, staking or scheduler authority is granted.

Original source cutoff: **2026-09-14T13:04:43.697362Z**.
Original forecast creation: **2026-09-14T13:09:39.891972Z**.
Original local export: **2026-09-14T13:09:39.901986Z**.
Actual exchange publication: read **`publication-receipt.json` beside this index**. Its `publishedAtUtc` is the delivery-completion clock. The unchanged original forecast retains `publishedAtUtc=null`; the original local index's `published=false` describes its earlier local-export state. Neither is rewritten or used to backdate exchange publication.

A later authorized forecast must be a new immutable ID/digest with its own captures and clocks. Name this forecast ID/hash in `supersedesForecastId` / `supersedesForecastSha256` in the new delivery envelope, and retain both versions. A schedule correction is an appended schedule revision or authorized new forecast, never an overwrite of this early snapshot. Publication of the same bytes is idempotent and is not a newer forecast.

Minimal AISP work: add this schema to the research importer; verify/deduplicate and reconcile ESPN identities; store original clocks and delivery clock separately; display the two labeled outputs and collapsed details; leave unsupported distribution/market fields unavailable. After actual import/display, return a consumer receipt under `C:\Users\james\asp-model-exchange\nba-gen1-research-v1\point-elo-v1\consumer-receipts` naming package index SHA, forecast ID/SHA, canonical/source game identity, import time, imported count and display checks. Publication alone is not integration confirmation.

No forecast was regenerated, fitted or simulated for this delivery. Existing NBA assessments and MLB/NFL operations remain untouched. Reproduce delivery verification using `.venv/Scripts/python.exe -B scripts/publish_nba_gen1_point_exchange.py --verify`.
