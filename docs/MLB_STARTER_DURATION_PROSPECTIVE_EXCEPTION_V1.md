# MLB starter-duration prospective exception — execution report

Status: **FIRST_REAL_PROSPECTIVE_STARTER_DURATION_PAIR_PUBLISHED**.

Two complete starter histories; one real COL–DET pair published; one pair
awaiting final and zero scored. Acquisition totals remain 60 requests,
23,363,290 original bytes and $0. No missing source field prevents this pair.

This is a narrowly authorized continuation of the existing frozen V18 versus
fitted-HGB starter-duration pilot. No model, calibration, policy, staking rule,
or other simulation mechanic was changed. The reference remains frozen V18;
the HGB arm remains research-only with no wagering authority.

## Completed compatible history

The first eligible matchup's two announced starters now have complete compatible
history through September 10, 2026, under the existing all-prior-eligible-starts
definition beginning January 1, 2023.

| Pitcher | MLBAM ID | Candidate starts | Eligible prior starts | Preserved exclusions | Unresolved |
|---|---:|---:|---:|---:|---:|
| Framber Valdez | 664285 | 118 | 116 | 2 | 0 |
| Mason Adams | 690279 | 3 | 3 | 0 | 0 |
| Total | | 121 | 119 | 2 | 0 |

Of these eligible starts, 62 are from 2025–2026. The certified 2023/24 ledger was
reused, not reconstructed or refitted. Valdez's existing exclusions remain:

- July 15, 2023: `MID_PA_STARTER_CHANGE`.
- July 26, 2023: `RAW_FD1_EVENT_IDENTITY_MISMATCH`.

The retained 2025 source has 2,430 raw Retrosheet games matching 2,430 gamelog
identities. Valdez's 31 candidate starts matched the FD1 enumeration and passed
the frozen eligibility checks. Adams's official MLB debut date, August 25,
2026, establishes the absence of earlier MLB starts; absent tables were not used
as proof of zero history.

Current HGB input construction retains `homePitcher`, `calendarMonth`,
`priorStartCount`, the arithmetic mean `priorStartBfMean`, `daysRest`, and
`historyMissing`; the simulator supplies evolving `bf`. No shorter history
window, generic median, or false no-history branch was introduced. Current
input receipt is `objects/sha256/cf5730ebaad61b68d3b19f0b3ea4b317d599056a267cd5d2404029d3180cdc7b/duration-input-readiness.json`
under the paired-research output root. Source availability is
`2026-09-11T19:34:26.302782Z`; the input check was `19:35:02.095161Z`.

| Input | Away: Adams | Home: Valdez |
|---|---:|---:|
| homePitcher | 0 | 1 |
| calendarMonth | 9 | 9 |
| priorStartCount | 3 | 116 |
| priorStartBfMean | 19.666666666666668 | 25.448275862068964 |
| daysRest | 5 | 5 |
| historyMissing | false | false |

## Exact source exception and permanent quarantine

The new authorization permits separately acquired completed-game evidence only
for the following starter-history derivatives used in genuinely future
pregame forecasts:

| Date | Authorized pitcher | MLB game PK | Canonical game ID |
|---|---|---:|---|
| August 17, 2026 | Valdez | 823343 | `game-3580e8be4936befc32ff752d` |
| August 24, 2026 | Valdez | 824235 | `game-a0765f54db9c74c24161785f` |
| August 25, 2026 | Adams | 822693 | `game-e53ecedc71413e735ca59695` |

All three corresponding **whole games**, including every player and component,
are permanently excluded from independent Final OOT evaluation. The reason is
`PROSPECTIVE_FEATURE_CONSTRUCTION`. Existing identity-only metadata identifies
230 excluded observations, leaving **13,837** of the original **14,067**.
These counts did not require reading sealed outcome payloads. Future reports
must disclose the reduced cohort; they must not call it the original untouched
Final OOT.

The original sealed evaluation files remain unread. No forecast-error analysis,
model comparison, tuning, calibration decision, or promotion claim is authorized
on the three quarantined games. Necessary source reconciliation fields remain
quarantined; raw quarantined evidence is not included in the exchange handoff.
The existing 56-observation hold remains preserved.

## Acquisition and verification

- Three newly authorized source requests: **469,715 downloaded original bytes**.
- Cumulative bounded intake: **60 requests; 23,363,290 downloaded original bytes; $0**.
- No paid calls, sportsbook credits, model fits, or AISP writes.
- Earlier source failures and their receipts remain preserved. Source projection
  corrections retain the original bytes and explicit lineage rather than
  overwriting them or relabeling them as a successful earlier attempt.
- The completed projection preserves actual retrieval/availability clocks.
  Current retrieval is not represented as a historical pregame publication vintage.
- Exact exception tuples and hash-bound authority/quarantine references are
  checked before protected source or derived parquet bytes. Actual derived rows
  must match their authorized descriptors. Other protected games remain denied.
- Focused history/input checks: 5 passed; source intake: 1 passed;
  quarantine identity/disclosure gate: 1 passed. No broad suite or repeated
  synthetic mechanics campaign was run. Two actual cached dispatcher resumes
  reused the same complete history manifest without another source request.
- Request 58's first validation rejected surplus native feed fields. Its
  original response and failure receipt remain immutable; an explicit local
  whitelist projection recovered the required evidence without retrying HTTP.
  All three original feeds and their three derived projections stay quarantined.

## Immutable evidence references

- Source amendment: `outputs/mlb-starter-duration-paired-research-v1/intake/objects/sha256/ff44954b71645132efc4509bb5d0582f1bb4de25a86b706e58491a9f609119d5.source-amendment.json`
  — SHA-256 `ff44954b71645132efc4509bb5d0582f1bb4de25a86b706e58491a9f609119d5`.
- Permanent whole-game quarantine: `server/artifacts/governance/mlb-final-oot-quarantine-v1.json`
  — SHA-256 `59ce1dccab97c520c4c3007281a2597cb89fb5d0ae8007ae89a09f008d8a495a`.
- Preserved partial history: `outputs/mlb-starter-duration-paired-research-v1/starter-history/objects/sha256/e66ed0857e0b463db680f4f206506c9d15ef6caac8557c449177a6dfe362565f/manifest.json`.
- Retained 2025 lineage-corrected reconciliation: `outputs/mlb-starter-duration-paired-research-v1/starter-history/reconciliations/sha256/380268e820ed5030483f53139e872143b286af27dc0a2d7099521e9a9198174d/reconciliation.json`.
- Exact original 2025 execution source: `outputs/mlb-starter-duration-paired-research-v1/starter-history/code/sha256/cc0eb940f6f6763b2ea2fedb025d6dd78758a4e6ac6be34f4cfc0ed035761ac7.py`.
- Completed successor history: `outputs/mlb-starter-duration-paired-research-v1/starter-history/objects/sha256/68088a2cb3d4c2e754c65fda27acc547a035e609ade847152efe64068805383f/manifest.json`
  — 94,759 bytes; starts parquet SHA-256 `91512893b3d57b0b7a22ea2dd0d72e5ded9f326a2f72dda2a3617e8f6156d5ef`, 14,200 bytes, 121 rows.
- Acquisition successor: `outputs/mlb-starter-duration-paired-research-v1/intake/objects/sha256/771adaff5d9d9308aab47ccd86c8282e95aa95410143d8ae6c546edc18af9c2f.intake-manifest.json`
  — 92,142 bytes; 31 current-history source games including the three exceptions.
- Identity-only accounting: `outputs/mlb-starter-duration-paired-research-v1/quarantine-key-accounting/objects/sha256/47b1af811219ef30c94225c511b9b8a8860443066f39d28b0e4b155f2201baa8.json`
  — 12,520 bytes. The three games contribute 87, 71 and 72 original PA keys.
  All 230 terminal PAs match; two additional source entries are reviewed
  runner-only events, not missing PAs. Only the separately published,
  authenticated UNMATERIALIZED key companion was read, not original sealed Gold.

## Prospective publication and handoff

**One real pair was published at 20:09:47.587959 UTC on September 11, 2026.**
Event `7323d8f3-9b24-464d-903e-fe290913d73b`, MLBAM game `824227`, pair
`mlb-duration-pair-51de2e1e0481f6165a43459f`. Both current starter identities,
ordered lineups and the complete V18 producer object passed the existing gate.

| COL–DET arm | DET win probability | Expected COL runs | Expected DET runs | Adams BF mean / median / 5–95% | Valdez BF mean / median / 5–95% |
|---|---:|---:|---:|---|---|
| Frozen V18 existing hook | 0.6138 | 4.0254 | 5.0294 | 18.6182 / 19 / 11–25 | 18.8466 / 19 / 11–25 |
| Same V18 + frozen HGB hook | 0.6188 | 4.0854 | 5.0410 | 21.3412 / 22 / 15–27 | 25.4564 / 26 / 20–31 |

These are predictive population summaries, not observed game results. The
home-win change is +0.005 (0.5 percentage points); its paired Monte Carlo
standard error is 0.005459. That describes simulation noise, not across-game
predictive uncertainty or evidence that HGB is better. No actual starter BF
error is available before a final.

Current participants were captured at `20:01:16.252752Z`; their latest relevant
availability was `19:58:12.822192Z`. The history itself remained the unchanged
`19:34:26.302782Z` projection. The full 5,000-per-arm population ran from
`20:03:07.460514Z` to `20:09:47.495818Z` (400.035 seconds), after authentication
and the existing real-input checks. Total first-numerical-operation to
publication was 510.094 seconds. One numerical attempt, zero model fits.

The HGB artifact reloaded with 0 mismatches across 64 rows / 192 probabilities.
The real V18 initial PA probabilities reloaded exactly across 18 rows, eight
classes, 246 raw and 273 treated inputs. The 5,000 reference home-run, away-run,
innings and PA-count arrays exactly matched the existing producer population.
Both arms completed 5,000 simulations with zero illegal or unfinished games.

Both arms retain 5,000 draws and the declared randomness/adapter semantics.
Valid saved pairs may be scored only against permitted persisted finals after
the event; an unplayed pair is awaiting final, not evaluated evidence.

The unchanged September 11 declaration is
`objects/sha256/b3f6debf668aba1cafbe308489255772a593e9d03532d5b3097f101af32bd19b/declaration.json`
under the paired-research root. COL–DET's deadline is **22:35 UTC**, five minutes
before the scheduled **22:40 UTC** start. The earlier PIT–CHC deadline was already
closed; it remains terminal and was not backfilled. Every due game is inspected
in declared deadline order. Other incomplete histories, starters, lineups and
producer objects remain explicit pending reasons while their windows are open.
The completed source intake covers these two pitchers, not the entire slate.

Exchange namespace: `C:\Users\james\asp-model-exchange\mlb-starter-duration-research-v1\current.json`.

Immutable published artifacts under the paired-research output root:

- Pair: `objects/sha256/fdee9e2fa72c8339c9bbd0d9e723d8898c34c80671c44eaf1d1f843674edfd45/paired-forecast.json` (6,550 bytes).
- Populations: `objects/sha256/1bc53f34cb40173459fbd2b6f2ba88d618c8f2e6f6616f59bbb9659dbc244534/paired-populations.json` (520,188 bytes).
- Publication receipt: `objects/sha256/b3e30fe26927002d28bc1d617710b41227c981d3a68773d459e00b9904e29279/pair-publication-receipt.json` (888 bytes).
- AISP handoff: `objects/sha256/ad0a9b58889d41914760b71191677a9818fb13ce519c85534133b01a1dbf5ffa/aisp-paired-handoff.json` (15,293 bytes).
- Full execution receipt: `objects/sha256/81b5e80bb0225306e56a396e8c31ccc961f8057cf7fa9adf7fd19a938df61b6b/resume-execution-receipt.json` (14,944 bytes).
- Scoring receipt: `objects/sha256/edfa5d65eb2de2f824f9026055ffefaed267898ca216b01feb2165ac59f0c855/scoring-receipt.json` (849 bytes): **1 awaiting final, 0 scored** at `20:09:50.324033Z`. No outcome database connection was opened for this unstarted pair.

The exported `current.json` index is 51,932 bytes, SHA-256
`2eed387ab4f9b14747a1fc9fc09fa944ec14e3bb46c649346d25b8a35d296c32`.
All files retain `RESEARCH_SHADOW`, `NOT_PROMOTED`, `wageringAuthority=false`
and `executionAllowedInAISP=false`. The six original/projected quarantined
source feeds are explicitly omitted from exchange objects.

Independent read-only verification checked the existing published-pointer
validator and all 66 copied exchange artifacts (24,785,853 bytes): zero checksum,
byte-count or path failures. All six quarantined source hashes were absent from
both the exchange index and its physical object directories. No model rerun or
protected-source payload read was involved in this verification.

Claude's next action: **Import both precomputed arms from this research exchange
index, resolving artifacts by SHA-256; keep them separate from official V18,
with no execution or wagering authority. Do not import quarantined raw source
feeds or change policies, positions or settlements.** No AISP import was run here.

Repeatable cached-only command from the repository:

```powershell
.\.venv\Scripts\python.exe scripts/run_mlb_starter_duration_paired.py resume --declaration outputs/mlb-starter-duration-paired-research-v1/objects/sha256/b3f6debf668aba1cafbe308489255772a593e9d03532d5b3097f101af32bd19b/declaration.json
```

The research task `mlb-starter-pair-readiness` is currently **PAUSED**. Its prompt
has been updated to this source amendment and cached-only execution. Codex
rejected activation because the same chat already owns the active six-hour
`archive-nfl-forward-evidence` heartbeat. James was asked whether to temporarily
pause that unrelated task; no such change has been assumed. Manual readiness
checks continue, with production-lock deferral. A paused task is not an active
five-minute service, and a Codex heartbeat would still require Codex and the
computer to remain running. The separate Windows V18 production task was not
changed or triggered by this assignment.

Starting and ending branch: `codex/mlb-starter-duration-source-intake-v1`.
Starting commit: `144e85a95de2f71c20c099917d075fcf9ce9d60e`.
Completed intake/quarantine commit: `1b6fdbb5a9898b51fb32017d8555664898c20d22`.

COL–DET's one numerical attempt began at `2026-09-11T20:01:17.494096Z`,
immediately before frozen HGB reload inference, after production had released
its lock. Its input SHA-256 is
`1edf51b946cc429166f73e08c9f414f6158fa94fa3456c7e8dbd9f5b6cb95ad7`.
This actual start precedes the separately verified completion/publication
above. Earlier missing-input checks and production-lock deferrals consumed no
numerical attempt. The final dispatcher inspected all remaining matchups:
one published pair, 13 pending games, one expired skip. Its next due check is
`20:14:47.631948Z`; this is a due time, not a claim that the paused task will run.
The repeatable command can score this saved pair after legitimate persisted
finals arrive. No interactive wait for tonight's final is required.
