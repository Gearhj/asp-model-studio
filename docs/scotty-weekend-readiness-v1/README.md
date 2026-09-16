# Scotty weekend producer readiness — September 19–20, 2026

**READY_WITH_DISCLOSURES.** Observation: September 16 at **15:55:04 UTC / 11:55:04 EDT**. No demonstrated P0/P1 producer defect, no production repair, no owner invocation and no new forecast or simulation. This local audit does not replace the release or publish a competing exchange handoff.

The sealed demo remains `f0e87d7a48d33566c7b76bb4490503ed25b49bff72e63b9107de3b1580f8889a`, based on source `bbe6d1c602fe5bfc0bda04c5d6134b6e90857a5e`. All 25 files in its directory remained unchanged. Discovery SHA remains `7977342c8eb87692b81bc253acd95f616bb44b9ab8e9e67ae54394f20c52ddf6`.

`READINESS.json` contains the **30-game MLB timing inventory and all 16 exact NFL forecast/version/package/eligibility bindings**, original clocks, consumer evidence, code hashes and activity accounting. Physical SHA-256 **`6462d1b24de22ca1452b7b252c57a4a33fb4e6406ee55b0571a8c86b57b0c308`**, **120,848 bytes**. The original remains at `C:\Users\james\asp-model-studio\.runtime\scotty-weekend-readiness-20260916-v1\READINESS-final.json`.

## MLB natural owner

`ASP MLB V18 Research Publisher` remains bound to deployment **`77d39e1ae08e05be82e19bdb0bab21999fba1d3b`**, with S4U launch configuration. Successive `windows-task-scheduler` receipts advanced naturally. The captured tick ran **15:54:10–15:54:21 UTC**, status `BOUNDED_TICK_COMPLETED`; next expected substantive tick was **15:59:10 UTC / 11:59:10 EDT** at capture. STOP remained absent and untouched. The read-only Task Scheduler query returned Access Denied, so health is receipt-based, not a new live enumeration of registered tasks.

Receipt: `C:\Users\james\asp-model-studio\outputs\mlb-v18-unattended-v1\objects\sha256\cf2bb456425514eee43bee712943b75d25e88fa5b612af3be370368548a5b8a3\tick.json` (70,702 bytes; physical SHA equals directory name).

That receipt records **two genuine September 16 forecasts** published through the ordinary owner; captured package **`11d60602a8034c284d18a85e29b891db05c7e17be36c1bd660e7932a3b8adae8`**. September 17's zero-forecast package is accounting only. Direct live exchange-member reads returned Access Denied in this session. Publication is qualified by the immutable owner receipt, not independently verified child bytes or confirmed AISP import. No permissions were bypassed.

Authentic packages appear in `C:\Users\james\asp-model-exchange\mlb-v18-current\sha256\<package-content-sha>\exchange-package.json`, with exact handoff/receipt paths inside. AISP's existing five-minute `asp-model-exchange-consumer` scans this tree, verifies members, reuses exact checksums and excludes accounting-only packages. The read-only consumer observation confirmed the import gate enabled. Historical MIA–Arizona remains historical.

### Weekend scope and inputs

The official identity-only schedule contains **15 Saturday and 15 Sunday games**. Neither day yet had canonical AISP rows or per-game participant/weather evidence at the read-only capture. This is **NOT_YET_DUE**, not a demonstrated failure: actual bridge code covers D through D+2 every three hours. Saturday enters scope Thursday September 17; Sunday Friday September 18. V18 selects D and D+1, so its weekend capture begins Friday/Saturday respectively. Exact live bridge phase was unavailable.

| Input | Required evidence / current state |
|---|---|
| Schedule | All 30 official gamePk, sides and kickoff retained; canonical mappings pending. Time/side disagreement fails closed. |
| Starter | Authenticated MLBAM identity and eligible source/capture clocks; weekend snapshots pending. |
| Lineup | Confirmed ordered nine-player lineup per team. No projected/generic fallback. Participant age limit is 30 minutes within four hours of start, otherwise 24 hours. |
| Active pitching roster | Nonempty active P/SP/RP evidence, maximum age 30 hours. Existing 06:00 EDT daily owner succeeded September 16 for all 30 teams, with no roster/team-stat/bullpen request-family failures. Weekend refreshes are still required. |
| Weather | Current publication explicitly passes `temperature=None`. Weather is not a separate hard participant gate and is not represented as a fresh weather prediction; frozen missing-input treatment is unchanged. |
| History | Existing governed owner refreshes when due; completeness and chronology remain required. This audit opened no protected history payloads. |

V18 checks rapidly at **T−60**, targets delivery **T−45**, consumer window opens **T−30**, decision closes **T−15**. **T−5** is an independent research-publication deadline, never a decision extension. Import and evaluation each have five-minute cadence. Missing eligible inputs can still prevent publication.

| First game | Start EDT / UTC | T−60 | T−45 | T−30 | T−15 |
|---|---|---|---|---|---|
| Sat MIL at BAL | 16:05 / 20:05 | 15:05 / 19:05 | 15:20 / 19:20 | 15:35 / 19:35 | 15:50 / 19:50 |
| Sun PHI at NYM | 13:10 / 17:10 | 12:10 / 16:10 | 12:25 / 16:25 | 12:40 / 16:40 | 12:55 / 16:55 |

All 30 timezone-aware checkpoints, including Saturday games after UTC midnight, are retained in JSON. Observed bounded ticks took about 5–100 seconds; this is not a guaranteed fresh-game simulation runtime.

## NFL Week 2 freshness

All **16 exact CURRENT forecasts and 16 eligibility supplements are import-confirmed** by a read-only consumer receipt at **15:40:01 UTC**, physical SHA **`f68a9a883c5ff555b14a4a69ef2270da2e4af2b0e6ceb8618c3b5717318b8392`**, 12,240 bytes. This does not confirm Claude's concurrent release reconciliation or display.

Physical bundle addresses under `C:\Users\james\asp-model-exchange\aisp-daily-forecast-bundles\sha256\<address>\bundle.json`:

* DET–BUF: `d9c8269ce6e2af681b2bd4cfe73c72d80316651874be390b7f708a0a1c7f8e8c`.
* Fourteen Sunday games: `5c45928219f5c893e0f2acb9572622ff93f0e57dc4c43a00de840ce92e2ff11714`.
* NYG–LA: `1538e66798300da0e209aa7b8f91419343549041e9321c01727fad0baa4eeca1`.

The AISP-owned daily producer succeeded September 16 **05:30:59–05:40:04 EDT**, creating zero numerical successors. Foundation metadata updated **09:32:37 UTC / 05:32:37 EDT**, manifest `a677ba9501a7b9e4f0a1dfc9c574c1ec321f46cdfef0802a9aaf45ff38b52a8b`. No Foundation outcome table was opened. Eligible vectors stayed unchanged, so September 14–15 objects are correctly reused. Daily checks continue **05:30 EDT / 09:30 UTC**; unchanged CURRENT objects may remain correct through Sunday.

All 16 retained vectors have **197 team-history/schedule features**. Current named personnel, roster participation, injuries and target weather are **not modeled**. Roof/surface are schedule features, not weather. All 14 Sunday forecasts share these structural omissions; there is no supported player-specific stale-input claim. A newer timestamp cannot supply excluded features.

The existing FINAL generator polls each **one minute**, event-gated T−30 through T−15, and skips already-frozen games. Current scheduler code supersedes the older five-minute description in the read-only inspector; import/freeze cadence remains five minutes. FINAL uses the last admitted Foundation rather than collecting another one. First FINAL is a separate horizon; an identical existing FINAL is reused. Any new Week 2 forecast needs a new exact paper supplement, produced by the existing completion path; a failure blocks use rather than transferring old eligibility.

FINAL publication must complete by **T−21**, reserving six minutes for import. IND–KC kickoff: Sunday **20:20 EDT / Monday September 21 00:20 UTC**. Generation opens **19:50 EDT / 23:50 UTC**; completion deadline **19:59 EDT / 23:59 UTC**; decision deadline **20:05 EDT / 00:05 UTC**. Slow execution can still miss this window; no deadline extension is authorized.

### Optional IND–KC play-level enhancement

**Feasibility stop; no simulation or supplemental package.** The verified V2 spatial publisher requires exactly 16 Week 1 M1 distribution-supplement parents. Current parent discovery has those 16 and zero for `2026_02_IND_KC`. The Week 2 CURRENT bundle and paper eligibility have different contracts and cannot silently replace that parent.

Minimum next engineering: review a one-event binding adapter using the exact existing CURRENT M1 population without resimulation, retaining V2 population/spatial/geometry validation and additive publication. No fit is inherently required, but the compatible path is not established. The independent play model is trained through 2024 and lacks current named personnel/injury/weather inputs; it does not explain or replace M1. This optional gap does not block the M1 demonstration. The old DEN–KC example remains historical; the all-game publisher was not invoked.

## CFB / NBA

Coastal Carolina away at Delaware remains `cfbd:401869940`, September 19 **11:30 EDT / 15:30 UTC**, package `223bbc35becc894560cc255dd7b786d2921c3201d63875c0af4a1af4e0b3ff76`, discoverable through the unchanged sealed demo. Bytes verified; research-only, **no Coastal–Delaware paper supplement**. Retained older CFB eligibility does not transfer.

NBA BOS–DET point/Elo package `85e3d7414ccaac4b79c524096af3f7fa894169041e143ee3dc5894002f53e2e0` and joint package `00cd49902fc00beb0a8edea9bb8a18ffa6e78d5e5da6c397c6a986c0af397a9d` verified unchanged. NBA remains season inactive. Neither sport was regenerated.

## Weekend watch / dependencies

1. **Before Friday close:** AISP's existing bridge should have both weekend dates registered. Inspect `bridge-mlb-canonical-events` for `SCHEDULE_SOURCE_UNAVAILABLE`, mapping failures or incomplete sides if not. Claude owns that consumer path.
2. **Saturday 15:05 / Sunday 12:10 EDT:** inspect the single MLB owner's `state.json` and latest immutable tick. Escalate `FAILED_BOUNDED_TICK`, `KILL_SWITCH_ACTIVE`, nonadvancing receipts beyond cadence, or `SOURCE_OR_PUBLICATION_STAGE_FAILED`. Do not start another owner.
3. **By first T−45 (15:20 / 12:25 EDT):** inspect `sourcePreflight.reasons`, confirmed lineups, starter identity and `ROSTER_MISSING`, `ROSTER_STALE_BLOCKING`, `ROSTER_SOURCE_FAILED`. Model Studio owns publisher diagnosis; AISP's existing owners supply participant/roster evidence. Accounting-only publication is not a forecast.
4. **Before each T−15:** require an AISP import receipt for the exact forecast. `PACKAGE_NOT_READABLE`, child checksum mismatch or disabled import gates are concrete consumer dependencies. This session has no MLB import acknowledgement and could not independently read live package bytes.
5. **NFL Sunday:** verify daily 05:30 EDT producer completion; unchanged reuse is valid. For IND–KC watch 19:50–19:59 producer completion and exact successor eligibility import before 20:05. Preserve personnel/injury/weather limitations.

Immediate verification gaps: read-only Task Scheduler visibility and live MLB child-file access. These were not bypassed. Future eligible inputs and timely consumer import remain operational dependencies, not failures demonstrated now. No new admin, scheduler or provider action is requested by this audit.

## Focused verification / accounting

Verified **110 physical reference bindings**, 16 unchanged CURRENT IDs/vectors, 30 UTC/EDT timing calculations, CFB/NBA members and sealed-release/discovery preservation. No broad tests or model assessment. The initial collector used an incorrect discovery filename; corrected to actual `discovery.json` before the successful retained run, without altering runtime artifacts.

```powershell
Set-Location C:\Users\james\asp-model-studio-source
& C:\Users\james\asp-model-studio\.venv\Scripts\python.exe -B scripts/audit_scotty_weekend_readiness.py --verify docs/scotty-weekend-readiness-v1/READINESS.json
```

`--output <new-path>` captures another explicitly requested observation without network, database, model or owner invocation. Historical verification checks immutable bindings; recorded code hashes are snapshots, not a requirement to freeze future source work.

Task-initiated provider calls **0**, external provider bytes **0**, cost **$0**, AISP writes **0**, model/simulation runs **0**, scheduler changes **0**, forecast publications **0**. The independent natural tick recorded one free schedule-identity request, not triggered by this task. Original repositories, worktrees, deployed models, forecast versions and AISP records were left unchanged by this work.
