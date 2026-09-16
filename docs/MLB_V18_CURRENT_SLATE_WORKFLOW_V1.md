# Current-slate V18 source bridge — September 10, 2026

## Outcome

**SOURCE_BRIDGE_OPERATIONAL_FORECAST_PUBLICATION_BLOCKED.** The live local schedule is now connected to a repeatable, content-addressed Model Studio source capture and current-input composer. Five September 10 games were found; none has sufficient evidence for a V18 forecast. No forecast handoff was produced. No unattended/nightly task was installed, and nightly **forecast publication is not operational**.

Started on `codex/mlb-regime-hybrid-ensemble-v1` at `0a70049bc1e2d78b6eae4c33e79eb6cc62607a5f`. V18 remains retained, RF/ensemble operationalization remains closed, and unrelated existing NFL/untracked work is preserved.

## What AISP actually displays

| Property | AISP current Gen1 | Model Studio V18 research |
|---|---|---|
| Model | `asp_mlb_ensemble / 2.0.0-gate2-08cca634c81b` | Frozen corrected HGB V18 PA estimator + accepted transition/simulation authority |
| Exact identity | Model UUID `d149cf07-c60e-4cfe-b887-d6703e4c6c94` | PA artifact `44ec4f457741f1aaeff42b81af1be5fd2712e494709ff1a0a8f0742b88d71c8b`; parent bundle `a6e7e99122f1b60701a4728b97b32fcc11e03405bfd456ed6cd54f69b69adb27` |
| Learned artifact | No artifact URI/checksum; registered training description: `not trained; deterministic Gate 2 development model` | Saved, checksum-verified fitted estimator, priors and semantic preprocessor |
| Computation | Weighted rating baseline, Poisson run model and deterministic untrained development challenger; direct game simulation | Eight-class PA probabilities, base/out transitions and 5,000-game simulation |
| Inputs | `mlb_pregame / 2.0.0`; persisted game-level snapshots and optional sources | Exactly 246 source fields and 273 semantically treated inputs, with player-specific sufficient statistics and chronological context |
| Updating | AISP's independent 06:00 local pipeline and event-driven rescores | Separate Model Studio publisher and AISP handoff importer; last saved slate was September 8 |
| Timestamps | Forecast generation, snapshot `data_as_of`, original `observed_at` and `available_as_of` are separate | Must retain source timestamps, actual execution-before-first-pitch and frozen model/treatment lineage |
| Authority | `CURRENT_DEVELOPMENT`; displayed selection can include a governed rescore DRAFT as well as PUBLISHED rows | `RESEARCH_SHADOW`, `NOT_PROMOTED`, no wagering or AISP model-execution authority |

Relevant AISP implementation: `server/app/services/forecast_service.py` (`generate_for_game`, `_versions`), `server/app/forecasting/ensemble.py`, `server/app/services/feature_snapshot_service.py`, `server/app/services/read_service.py:2902`, `server/app/jobs/scheduler.py:382`. These were inspected read-only. The current Gen1 feature snapshot is not a V18 feature vector. Current weather may be available; Gen1 passes wind as `None`, and the old V18 provider does not numerically consume its snapshot weather.

**Why Studio saw only September 8:** the previous bounded inspection examined saved Studio/exchange artifacts, not the live AISP schedule. The database contains September 10 games. AISP's independent Gen1 production does not update Studio's saved V18 slate. The existing V18 source reader was capable of read-only database access, but no current immutable source capture/composition bridge had run. This phase repairs that local connection rather than treating expired saved artifacts as the entire local data inventory.

## Exact next-slate accounting

The read-only capture uses PostgreSQL `localhost:5432/asp`, confirms `transaction_read_only=on`, and rolls back its repeatable-read transaction. It chooses the next local MLB slate from future game timestamps. It does not invoke AISP's generator, importer or rescorer, and does not reuse a prior game's lineup.

All five games have canonical event/team IDs, exact MLB source-event IDs, probable-starter identities and timestamps. All 46 available participants map exactly through the existing identity-only crosswalk; no identity substitutions or unresolved mappings occurred. Team season aggregates, ratings, roster metadata and weather are present. They are not player-specific V18 histories.

| Game | Canonical game ID | Start UTC, Sep 10 | Current-game lineups | V18 skip |
|---|---|---|---|---|
| TB–ATL | `9fbada7c-368e-439c-8ed5-cf3dd65169a2` | 16:15 | Both confirmed | Missing source families A–D below |
| HOU–PHI | `8a0a0c75-60fc-478c-ba5d-5502ba52d2d2` | 17:05 | Both confirmed | Missing source families A–D |
| TEX–SEA | `7946a01b-6daf-47b1-957b-edd64a316204` | 20:10 | Both missing | A–D plus both current ordered lineups |
| COL–NYY | `147789ea-5c5e-4485-991b-289eb12a6f4a` | 23:05 | Both missing | A–D plus both current ordered lineups |
| PIT–CWS | `1a36f34b-466f-4980-967f-fb9ba2778834` | 23:40 | Both missing | A–D plus both current ordered lineups |

A. Player-granularity sufficient statistics compatible with the V18 contract; team totals cannot be allocated to individual players.

B. Current last-100 batter PA / last-250 pitcher windows, exposures, pitch composition, swings/whiffs and velocity aggregates, with coverage-through and observation/availability evidence. Model Studio's old rolling templates are not current observations.

C. Complete team-history authority for all required rest/travel/series context. The bridge derives source-backed calendar fields; it does not treat an absent history table as zero games/travel.

D. Current bullpen membership/workload/availability and the corresponding player-state distribution. All five applicable bullpen tables are empty; all ten starter rest/workload/pitch-count fields are null. Historical bullpen templates are not current availability.

For the two lineup-complete games, the bridge constructs 18 diagnostic starting-lineup rows each: **33/246 raw fields supported/composed**, including identity, defined initial simulation state and source-backed calendar/matchup fields. This supports dependencies for **27/273** treated fields; treatment is not executed. The remaining three games cannot supply starting-lineup rows. Every missing field, dependency, original source timestamp and identity is recorded in the per-game coverage objects. These are not forecasts or observed plate appearances.

Three AISP venue timezone fields were null. Exact MLB venue IDs `4705`, `2681`, `680` now resolve through the existing `MLB_CONTEXT_STATIC_AUTHORITY_V1` registry to Truist Park, Citizens Bank Park and T-Mobile Park. No home-city inference or AISP database repair was used. The other two persisted timezones reconcile with their exact venues.

Current Gen1 snapshots still report `0.361111` completeness and, at capture, lag newer confirmed lineup observations for the early games. This score is not used as V18 coverage or awarded readiness points.

## Implemented step and boundaries

- `scripts/inventory_mlb_current_slate.py`: actual next-slate SELECT-only source export with current-game lineups and original source identities/times/checksums.
- `mlb_v18_current_inputs.py`: exact-order, source-backed composition with current identities/dates, calendar and handedness; missing evidence, wrong player/event bindings and stale history remain explicit.
- `mlb_v18_current_slate.py` and `scripts/run_mlb_v18_current_slate.py`: content-addressed per-game source/composition objects and immutable run receipts; unchanged source and numerical identities are separate from execution/publication clocks. No fallback to the historical-template simulator.

The saved semantic/prior transforms are still explicitly Development-only. A truthful September date is not accepted by those guards. The guards and their frozen implementation hashes were **not** changed, monkeypatched or evaded with a historical date. After source-backed complete current rows exist, a separately verified prospective transform seam preserving all fitted parameters remains an integration prerequisite. It is not presented as an external-data failure; work stops here because the independent missing PA/pitch evidence is already decisive.

The external gap was checked beyond empty AISP tables: since August 28 its relevant local ingestion metadata shows schedule/person refreshes, team-data refreshes and availability polling—not a current PA/pitch stream. The inspected September 10 raw schedule export contains `people` and `schedule`, not pitches/PA histories. Studio's Statcast filename inventory ends August 27. No sealed August 14–27 payload was opened. No providers were called.

To rerun the repaired local evidence step from Model Studio:

```powershell
.venv\Scripts\python.exe scripts/run_mlb_v18_current_slate.py
```

This is the entry point a nightly owner can invoke; it is **not** an installed unattended task or a completed forecast publisher. It records classified missing-source skips. Do not run the legacy historical-template publisher as a substitute for this incomplete current contract.

## Focused verification and receipts

Four focused tests passed in the supported Windows context: event/participant identity and home/away parity; stale/missing input handling; actual first-pitch/source cutoff rejection; content-addressed reuse and numerical identity. The default sandbox could not access pytest-created temporary directories; the approved Windows execution context passed without access-control changes.

Accepted V18 artifact reload reproduced **32 existing Development fixture predictions bit-for-bit**, maximum difference zero, with 246/273 feature-order parity. No fits. Actual current-slate capture and repeated offline processing succeeded. Both unchanged source and composition hashes were identical across reruns; all five source objects were reused and zero numerical forecasts were created.

- Source capture: `outputs/mlb-v18-current-slate-v1/inventory/sha256/8707a193d42f7a28089f76157ffcd2398867a7501964f431701052f6118388c6/current-slate-input-inventory.json`.
- Reload evidence: `outputs/mlb-v18-current-slate-v1/objects/sha256/b4644299ba9a51a1ea52882270374478c40c89e182c5679286afa7b2f6d2b07d/run-receipt.json`.
- Final bridge: `outputs/mlb-v18-current-slate-v1/objects/sha256/1b15231ac3e29c2756f92325334563386a0ba559ef290f12f682d06a5e175bca/bridge-receipt.json`.
- Final run/code identities: `outputs/mlb-v18-current-slate-v1/objects/sha256/8eec3f73ff46f4b71e3584d8bd1a1a967ad5de128d798bfd78d6843c5553eae3/run-receipt.json`.

Each named object contains or is linked by physical SHA-256 and byte counts. These are source/readiness research receipts, **not** AISP forecast handoffs.

## Next action and one forward requirement

**AISP import action: none.** Do not import these source objects as forecasts. Required next input is a legitimate timestamped, player-granularity current sufficient-statistics/window export (or landed source evidence from which the existing feature pipeline can produce it), plus complete context/bullpen evidence and the three games' current ordered lineups. Preserve the sealed OOT boundary when sourcing or initializing these histories. Once those inputs exist, validate the prospective transform seam and connect the completed vectors to the existing frozen simulator/handoff format.

**Forward candidate requirement:** every newly trained candidate must preserve its complete fitted estimator, fitted preprocessor (including priors, encodings and missing-value parameters), ordered feature/target contract, and a reload fixture with expected transformed inputs/predictions. The candidate receipt must reference their hashes and byte counts and record reload verification. This is recorded as a requirement only; no platform-wide hardening was added.

No official AISP forecast, policy, threshold, position or settlement changed. V18/ensemble promotion and wagering authority remain disabled. RF searches/training, model fitting, OOT access and broad testing were not performed.
