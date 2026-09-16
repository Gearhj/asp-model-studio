# Starter-duration intake and prospective-pair readiness

Date: 2026-09-11. Starting branch/commit: `codex/mlb-starter-duration-paired-research-v1` / `951ebb2375872ec978d63548146c9d9cc9bfbec1`. Work isolated on `codex/mlb-starter-duration-source-intake-v1`; concurrent operational V18/NFL changes are not included.

## Outcome and the required decision

**Zero complete current starter histories, zero legitimate forecast pairs.** Nonsealed intake is implemented and connected to the existing dispatcher. The first matchup is COL–DET, canonical event `7323d8f3-9b24-464d-903e-fe290913d73b`, source game `824227`, scheduled 2026-09-11 22:40 UTC, deadline 22:35 UTC. Both ordered lineups and both announced starters were available in the actual 19:03 UTC read-only capture. This is not a claim that every V18 producer input is ready.

| Pitcher | Enumerated candidates since 2023 | Eligible | Preserved exclusions | Unresolved protected appearances | Complete history |
|---|---:|---:|---:|---:|---|
| Framber Valdez, MLBAM 664285 | 118 | 114 | 2 | 2 | No |
| Mason Adams, MLBAM 690279 | 3 | 2 | 0 | 1 | No |
| Total | 121 | 116 | 2 | 3 | 0 of 2 |

The 2026 enumeration is of **pitching appearances**, not assumed starts. Unread protected appearances cannot yet be classified as starts or justified exclusions. Hence no all-prior mean, rest or false zero-history feature is supplied to HGB. All 14 still-open games have at least one protected pitching appearance in their announced starters' metadata; no permission-free complete-history candidate was found. Two games also lack one announced starter identity. Only COL–DET received full nonsealed history intake.

The existing `JAMES_2026_09_10_NEW_FINALIZED_SOURCE_HISTORY_EXCEPTION_V1` expressly permits current V18 rolling PA/pitch inputs. No explicit authority for HGB starter-history eligibility derivatives was found. Sealed evaluation files were not opened, and no equivalent protected outcome feed was downloaded. The new source declaration, SHA-256 `e73efabea4fa4423f02c46b2c27cdb21a54e5b967f3751a81abceca101a5223f`, records that distinction before acquisition.

One narrow decision is needed for these appearances:

| Pitcher | Date | MLB gamePk |
|---|---|---:|
| Framber Valdez | 2026-08-17 | 823343 |
| Framber Valdez | 2026-08-24 | 824235 |
| Mason Adams | 2026-08-25 | 822693 |

Requested use is separately acquired finalized source evidence **only to classify eligible prior starts and derive the existing prospective HGB prior-start inputs**. Required fields are declared starter/team/player identities, attributed BF and outs, ordered PA terminal categories, batter/runner identities and base origins, pitching substitutions/counts and non-PA actions, completion/resumption/source clocks, and final-score fields solely for source reconciliation. These include outcome-bearing source facts; this is not a disguised BF-only or metadata-only request. No evaluation, selection, tuning, sealed-file opening or broader protected-history permission is requested. Approval would still be followed by source reconciliation, real producer verification and the actual pregame deadline check; it would not itself guarantee a pair.

## Actual intake and coverage

- **57 requests, 22,893,575 original downloaded bytes, $0.** Ceiling remains 200 requests / 524,288,000 bytes, including retries. Zero paid calls, redirects, automatic retries or protected outcome payloads. One proposed invocation was rejected before execution; it made no request and is not counted. Subsequent requests used the supported approval mechanism after the metadata-only safeguard was established.
- One safe 2025 metadata projection probe; two first-pair 2026 appearance enumerations; one completion-metadata request; 28 nonsealed completed-game feeds; one two-pitcher identity request; 24 additional announced-pitcher metadata enumerations to establish whether another open pair avoids the permission dependency.
- Sequential requests were paced at least one second apart and stop on rate-limit/error responses. This is a conservative local rate policy, not a claimed published numerical MLB rate allowance. Interrupted requests reserve their maximum payload size in the durable shared ledger. Cached original bytes and retrieval receipts are reused.
- Certified 2023/24 ledger: Valdez 59 candidates = 57 eligible + two preserved exclusions, 1,462 eligible BF. Exclusions are 2023-07-15 `MID_PA_STARTER_CHANGE` and 2023-07-26 `RAW_FD1_EVENT_IDENTITY_MISMATCH`.
- Retained 2025 source: 2,430 raw game identities match 2,430 game-log identities; all 31 Valdez candidate starts reconcile against frozen Retrosheet/FD1 parsing, final scores, outs and independent starter usage. All 31 eligible, 802 BF, zero intersections with the frozen hold. No new 2025 game-feed acquisition was needed for this reconciliation.
- Authoritative identity metadata places Adams's MLB debut on 2026-08-25. This establishes zero MLB history in 2023–25; an absent Retrosheet mapping alone did not.
- 2026: Valdez 28 appearances = 26 eligible starts (636 BF) + zero exclusions + two unresolved protected appearances. Adams three appearances = two eligible starts (41 BF) + zero exclusions + one unresolved protected appearance. **31 = 28 + 0 + 3**. Every downloaded nonsealed feed reconciles.
- The original 56-observation hold remains unchanged. The three 2026 hold dates are July 17, July 19 and August 5; no first-pair 2026 candidate falls on these dates. Hold metadata and safe 2025 identity partitions were used without opening mixed/protected 2026 feature payloads.

Unknown original historical publication times remain unknown. Original acquisition clocks are retained in raw receipts; a newly constructed projection records its actual availability and does not claim historical pregame availability or a newly refreshed source. Current retrieval may serve a later real forecast, not a historical backtest.

All 28 feeds support the frozen starter-attribution rules. Runner-only `other_out` events are distinguished using observed runner/base-origin evidence, not by adjusting counts to match a box score. One May 13 PA has an approximately 7.6-second within-PA timestamp inversion; raw clocks and the anomaly are retained. Native event order and same-venue-date completion evidence establish the needed facts without inventing an elapsed duration. Unsupported events fail closed.

Rights remain local private research/model development, with applicable attribution, governed local research restrictions and commercial-rights review; no raw public redistribution authority is claimed.

## Implementation and preserved evidence

- `scripts/acquire_mlb_starter_duration_history.py`: bounded first-matchup acquisition, metadata-only protected enumeration, immutable raw bytes/receipts, shared request/byte accounting and cached recovery. It deliberately does not bulk-acquire the other games.
- `server/sports_current_statcast/mlb_starter_duration_history.py`: retained-2025 reconciliation, completed-start source adapter, identity/hold/coverage accounting and content-addressed partial projection. Partial coverage explicitly cannot authorize inference.
- `mlb_starter_duration_current_inputs.py`: protected manifest declaration checked before Parquet payload access; protected rows/unknown appearances cannot be transformed into supported HGB inputs.
- Existing paired dispatcher: open missing inputs are `PENDING_INPUTS`, five-minute cooldown, closed deadline is terminal, input checks consume no numerical attempt. The one attempt is reserved immediately before actual estimator inference, after artifact authentication. Existing model identities, 5,000 draws per arm, seeds and simulation mechanics remain unchanged. Production priority, locks, STOP and the declared execution bound remain enforced.
- Existing `resume` command connects cached intake, compatible projection, current input checks, paired execution, separate exchange export and persisted-final scoring. Exchange failure preserves the local package. No second simulation framework or source collector was created.
- V2 intake contract preserves V1 and clarifies prospective retrieval versus historical vintages. V1 already allowed prospective use of newly retrieved evidence; the successor is not presented as removal of an actual historical-vintage requirement.
- The first 2025 reconciliation `ecc375b80c9d7552b4e228bd2a1dc371e6865d4788eac1fde5400fe9a8ef5dcb` remains unchanged. Its original execution code was recovered byte-identically and archived; successor `380268e820ed5030483f53139e872143b286af27dc0a2d7099521e9a9198174d` points to the immutable code while preserving parsed starts. The initial partial projection `e66ed0857e0b463db680f4f206506c9d15ef6caac8557c449177a6dfe362565f` is also preserved.

## Prospective outputs and execution

| Actual output | Reference V18 | V18 + frozen HGB |
|---|---|---|
| Real pairs published | 0 | 0 |
| Home-win probability / expected home and away runs | Not generated | Not generated |
| Forecast starter-BF summaries | Not generated | Not generated |
| Actual numerical attempts | 0 | 0 |
| Awaiting-final / scored pairs | 0 / 0 | 0 / 0 |

No historical pair or synthetic fixture is being reported as a forecast. PIT–CHC was already past its 18:15 UTC deadline and remains terminal; it cannot be backfilled. The other 14 were pending at the actual check, not terminal skips.

The initial actual integrated resume at 19:03 UTC exposed `unhashable type: 'dict'` in structured readiness-reason deduplication. It consumed no numerical attempt; its receipt `48157cdb6c5d90864a2c73e660fcb59327448e628f54ccfe1f42413b4d77e4b0` remains immutable. The targeted repair preserves structured per-player reasons. Cached-intake identity was also corrected so unchanged source evidence does not create fresh projection availability merely because another receipt is issued.

The repaired actual resume completed at **19:09:17 UTC**, after the cooldown, with **14 pending, one terminal, zero attempts and zero pairs**. COL–DET's remaining reasons are incomplete/unapproved protected starter history and `COMPLETE_CURRENT_V18_PRODUCER_OBJECT_UNAVAILABLE`; neither starter nor ordered lineup was missing at this check. The real producer must finish its own complete object before this research path can execute; no substitute was created. All other games' reasons are preserved individually in the handoff. Actual cached execution reused original intake `d1d29d6ff210ca2793a2974fcab18563ce1c13ee847b40af444809cdf756a6e3` and projection `e66ed0857e0b463db680f4f206506c9d15ef6caac8557c449177a6dfe362565f`, with no new source requests or source-availability clock advancement.

Final execution receipt: `outputs/mlb-starter-duration-paired-research-v1/objects/sha256/68cdf9a3b401dd834bad8e546697c74aa170bc2dcda6b9baaee9f90aa5e3c2b8/resume-execution-receipt.json`. Local handoff: `outputs/mlb-starter-duration-paired-research-v1/objects/sha256/9dc573ac7787eca3a8c77ad7401712cfad5fd76c71b67b529ae68340ca32bee7/aisp-paired-handoff.json`, 16,267 bytes, SHA-256 `9dc573ac7787eca3a8c77ad7401712cfad5fd76c71b67b529ae68340ca32bee7`. Separate exchange index SHA-256: `9d2f7e1cfa85d65ac6abcfdb1f3ff1d2e84aef2e319cef240b4087b22f183e60`, 45,085 bytes; **59 reachable exchange artifacts, zero checksum/byte mismatches**. Scoring receipt `4b143b7cf6dce54df18a8c8b43c434716acabb94d22b7d42f912dab3f5f74fbf` records zero pairs, so no outcome database connection was needed. Earliest next eligible readiness check is **19:14:17 UTC**, but that is a cooldown time, not a scheduled invocation while the task is paused.

### Repeatable command and task ownership

From `C:\Users\james\asp-model-studio`:

```powershell
.\.venv\Scripts\python.exe scripts/run_mlb_starter_duration_paired.py resume --declaration outputs/mlb-starter-duration-paired-research-v1/objects/sha256/b3f6debf668aba1cafbe308489255772a593e9d03532d5b3097f101af32bd19b/declaration.json
```

This command uses cached evidence only. `--allow-free-network` enables the existing bounded authorized intake but **does not override the protected-date guard**. New protected authority, if granted, must first be recorded and narrowly implemented; neither this command nor the paused task grants it. A new slate requires a new pre-outcome declaration after this slate's windows close.

Minimal Codex heartbeat `mlb-starter-pair-readiness` is durably configured at five-minute cadence but **PAUSED pending the protected-use decision**, with no scheduled invocation while paused. Its configuration is `C:\Users\james\.codex\automations\mlb-starter-pair-readiness\automation.toml`. This is a Codex-app-owned local task, not a Windows service: the machine must be awake and Codex running. Configuration persists, but execution does not continue with Codex closed or the computer off; after a restart Codex must run and the task must be explicitly activated. The OpenAI Docs skill informed these ownership limits. [Official automation documentation](https://learn.chatgpt.com/docs/automations?surface=app).

The only authorized exchange namespace remains `C:\Users\james\asp-model-exchange\mlb-starter-duration-research-v1\current.json`. With zero pairs, its consumer action is `NO_FORECAST_IMPORT_WHILE_PAIR_COUNT_ZERO`; Claude should not activate/import a forecast from this readiness-only handoff.

## Focused verification

Three new parser checks cover a retained real 2025 feed and substitution guard, protected-before-payload access, and timestamp ambiguity. One intake check covers metadata projection and interrupted-request budget accounting. One input check covers generic authority failing to authorize protected history. Three directly affected dispatcher checks cover the publication seam, identity/deadline/checksum protections, and pending/cooldown/no-attempt behavior. The pending check was amended and rerun for the actual structured-reason error. No broad suite or model fit was run. Prior real HGB reload/mechanics receipt `9b0d37bed1ea35e2817011a973cc12cec6026ff59d815dca4261f060ba1f52bb` is reused, not relabeled as this run's real paired forecast.

Live V18, fitted HGB/calibration, policy/staking gates including the 2% edge threshold, all old forecasts, positions and settlements are unchanged by this assignment. No AISP write, promotion or protected evaluation occurred.
