# CFB Gen1 staged slate publisher

This deployment preserves `CFB_GEN1_RIDGE_A100_PAIRED_RESIDUAL_V1`. It does not select a model, create a champion claim or grant AISP authority. The original numerical modules `pipeline.py` and `current.py` are byte-identical to the starting commit.

## Separate numerical channels

- Expected away/home points are the retained Ridge alpha100 margin/total expectations, not averages relabelled from a simulation.
- `ridgeHomeWinProbability` is the frozen Development margin calibrator's probability. Its name is the existing contract, not a claim that Ridge regression itself emits probabilities.
- `eloHomeWinProbability` is the independent chronological Elo diagnostic channel.
- `jointHomeWinProbability`, all four PMFs, total-line probabilities and intervals come from the same 10,000 paired residual draws. They need not agree with the calibrated or Elo channel. Never force agreement or combine their denominators.

Probabilities are fractions [0,1]. Draws have `home_score`, `away_score`, `total = home + away`, `home_margin = home - away`; winner is home > away. Existing final-score law floors negative sampled scores, stochastically rounds and resamples entire tied pairs. It includes full-game scores (overtime in the historical targets), but is not a drive/possession or explicit overtime simulator. Transform counts and means remain visible. MCSE measures sampling precision, not model/input uncertainty. No more elaborate football score-support rule was added.

## Versioned input admission

Source is retained, authorized CFBD evidence. An input capture manifest lists endpoint, nonsecret parameters, HTTP status, actual acquisition clock, physical SHA-256, bytes and raw private path. Admission accepts local manifests only; there is no network or credential reader in the owner. Raw responses, fitted objects and feature populations stay outside Git and outside consumer packages.

The year-specific schedule and FBS school master use CFBD IDs, with effective-season alias records and their actual known-at clock. This is a source-year identity rule, not fabricated legal rename dates. Case/whitespace normalization only; ambiguous or unknown names cannot merge school histories. New IDs without prior-season support stay blocked. FBS/FBS regular-season games through week 14 use the original scope rule; FBS-involved completed regular games supply chronological context. Postseason and other-sport rows do not become targets.

Every completed context game needs two oriented team-stat joins with total yards and turnovers and valid untied integer final scores. Source-declared completed records are used only after capture, never injected into earlier prospective artifacts. Original frozen historical inputs through 2025, existing preprocessing and current feature builder stay unchanged. A correction reconstructs current feature state from its newly captured version; it cannot rewrite prior packages. Historical source vintages remain uncertified. Current target outcomes, participants and sportsbook data are not used for model selection.

An atomic admitted-input pointer advances only after complete validation. Missing final boxes, unresolved elapsed nonfinal events, duplicates, invalid identities, schema changes or failed capture/admission leave the earlier pointer untouched. A refreshed schedule cannot certify absent completed-game stats. The retained source lacks explicit cancellation/postponement/replacement statuses: unresolved past starts fail closed; source changes need governed successor evidence. Same-event rescheduling retains the source game ID and creates a new eligible version. Replacement-event identity is not guessed.

## Publication lifecycle

One proposed `ASP CFB Forecast Publisher` S4U/Limited/IgnoreNew owner, every 15 minutes; installation is not authorized by staging. Due windows begin at T-7d, T-24h, T-6h and T-60m. Missed checkpoints may be caught up only while genuinely pregame and before T-30m. No historical checkpoint clock is manufactured.

AISP's inspected House Divided interface has a T-15m cutoff; its CFB path explicitly lacks an official decision pipeline. The producer closes at T-30m, leaving 15 minutes, without claiming a verified CFB import cadence or moving a consumer deadline. Claude must confirm its eventual pipeline/cadence before activation.

Schedule and completed-history membership must be no older than 24h, tightened to 2h at T-60m. Both are tested before reuse and after rendering. Expired, stale, not-due, missing-input, game-failure, preserved-history and currently-eligible statuses stay distinct. A new capture clock alone is not a new numerical forecast: target feature values, oriented identity/time and release binding determine the revision key. A valid unchanged target reuses exact package bytes; its reuse receipt binds the new input version and preserves original creation/source clocks.

Per-game failures do not hide successful games. Prepared and committed journals recover interrupted publication without regenerating completed populations. One OS lock prevents parallel owners. Start/final launcher receipts, phase receipts, runner receipts and per-game completed/failed receipts are durable. A start without a final receipt is interruption, not success.

## Immutable output and consumer integration

Forecast/package schemas remain the existing `CFB_GEN1_PROSPECTIVE_RESEARCH_FORECAST_V1` and `CFB_GEN1_PRIVATE_RESEARCH_PACKAGE_INDEX_V1` so the current research parser can independently verify the bytes. New artifacts explicitly say staged prospective baseline, research-only and no wagering/AISP authority. Earlier Syracuse-Pittsburgh and Coastal-Delaware artifacts remain research artifacts unchanged.

Package address is the physical SHA-256 of canonical UTF-8 index bytes. Forecast logical identity is separate. Package member hashes and the retained ordered population are independently reconciled. Source cutoff <= creation < kickoff. Creation is not publication: `publishedAtUtc` in the immutable prepared index remains null; the bound append-only publication receipt records conservative first durable availability (`committedAtUtc`). After interruption, this can be later than physical rename and is never backdated. Existing consumer code's package-local publication receipt is not silently substituted: Claude must read the discovery-bound publication receipt.

`slate-discovery/current.json` atomically points to a content-addressed `CFB_GEN1_SLATE_DISCOVERY_V1` manifest. Every manifest retains all committed package revisions, all game dispositions and predecessor reference. It never replaces a slate with one game. Currently-eligible leases expire at the next tick, freshness limit or publication cutoff, whichever is first. An inactive publisher cannot leave an indefinitely current forecast. A preserved historical package is not a presently eligible revision.

No source-refresh transport, automatic acquisition, installation, consumer pin, decision or wagering action is activated. See the exact `REFRESH_REQUIREMENTS.json` for the one-capture authorization scope and the final activation receipt for installation commands. An additional recurring acquisition implementation/approval is required before claiming unattended season-long refresh.
