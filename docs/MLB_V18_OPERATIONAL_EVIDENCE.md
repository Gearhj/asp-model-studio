# September 10 V18 operational evidence reconciliation

The retained receipts establish two prospective research forecasts and three explicit pregame skips across the five-game slate. The final publisher's `scheduledGameCount=2` counted the two games still in the future, not the full day. This audit does not establish unattended operation.

The complete machine-readable audit is `outputs/mlb-v18-unattended-v1/evidence/sha256/2bcf37de2fd76316ec850ebec2f06c7383fcd7c5afa275071ea21f8aafc95e29/sept10-operational-evidence.json`, SHA-256 `2bcf37de2fd76316ec850ebec2f06c7383fcd7c5afa275071ea21f8aafc95e29`, 12,167,507 bytes. It contains every required raw field, each game's 34 source templates, actual values and null counts, frozen treatment, original source clocks, canonical participants and ordered lineups, numerical role/dependency mappings, refresh limitations, forecast child checksums, and original versus rerun lineage. Earlier audit objects and all original publications remain preserved.

Reproduce with `.venv\Scripts\python.exe scripts\reconcile_mlb_v18_operational_evidence.py`. The script only reads explicitly scoped operational JSON, frozen preprocessing metadata and executable checksums. It does not deserialize an estimator, execute inference, fetch sources or access AISP. Repetition reuses the identical audit bytes.

## Full slate, using retained evidence

| Game | Canonical event | First pitch UTC | Exactly one disposition | First pregame blocker |
|---|---|---|---|---|
| TB–ATL | `9fbada7c-368e-439c-8ed5-cf3dd65169a2` | 16:15 | Explicitly skipped before first pitch | Current player-level V18 sufficient statistics unavailable |
| HOU–PHI | `8a0a0c75-60fc-478c-ba5d-5502ba52d2d2` | 17:05 | Explicitly skipped before first pitch | Current player-level V18 sufficient statistics unavailable |
| TEX–SEA | `7946a01b-6daf-47b1-957b-edd64a316204` | 20:10 | Explicitly skipped before first pitch | Current player-level V18 sufficient statistics unavailable; both ordered lineups also missing |
| COL–NYY | `147789ea-5c5e-4485-991b-289eb12a6f4a` | 23:05 | Published before first pitch | None at successful publication |
| PIT–CWS | `1a36f34b-466f-4980-967f-fb9ba2778834` | 23:40 | Published before first pitch | None at successful publication |

The original bridge captured all five at `15:03:16.472933Z` and recorded its skips at `15:08:55.446471Z`, before even TB–ATL started. Its immutable receipt is `outputs/mlb-v18-current-slate-v1/objects/sha256/1b15231ac3e29c2756f92325334563386a0ba559ef290f12f682d06a5e175bca/bridge-receipt.json`. Thus TB–ATL was discovered and explicitly skipped; a later inventory excluding it does not erase that earlier evidence.

The independent schedule-only capture at `16:23:29.223375Z` confirms five scheduled identities; its receipt SHA is `036bc0dbcb06f001b2460d476742fbe3663540aa25d28bfae9a6882f2ef79a3a`, raw projection SHA `9e63819961793d73b649c81bedd82fa0b6cf9fc139280394ed6a2dbbdf563549`. That projection contains no results, PA, innings or lineup payloads. No current retrieval is used to backdate availability.

By the current-history adapter's first eligible availability at `21:07:30.438839Z`, the first three games had passed their scheduled starts. HOU had reached 215/246 supported fields at `16:33:45.925196Z`; its remaining 31 fields were the player PA/pitch-history family. TEX still lacked lineups in that retained intermediate capture. The source repair finished too late for these games. This explains the late deployment; it does not excuse future days omitting started games from daily accounting.

## Original forecast identities and clocks

All times below are September 10, UTC. Exact original observation, availability and ingestion timestamps are retained independently in the JSON. Several AISP ingestion fields precede observation fields; the audit preserves this source convention and checks that both precede capture, rather than relabeling either as provider publication time.

| Item | COL–NYY | PIT–CWS |
|---|---|---|
| MLB event ID | 823499 | 824550 |
| Forecast created | 21:29:52.660204 | 21:19:31.550594 |
| Evidence capture cutoff | 21:22:10.924683 | 21:12:24.335226 |
| Time before scheduled first pitch | 95.12 minutes | 140.47 minutes |
| Away starter | Ryan Feltner, MLBAM 663372 | Jared Jones, MLBAM 683003 |
| Home starter | Max Fried, MLBAM 608331 | Hagen Smith, MLBAM 696146 |
| Starter evidence observed/available | 21:21:42.802411 | 21:11:21.726045 |
| Lineup evidence observed/available | 21:21:43.283325 | 21:11:28.754885 |
| Away win / home win | 0.357 / 0.643 | 0.5718 / 0.4282 |
| Expected away / home runs | 3.6106 / 4.8468 | 4.5232 / 3.6322 |
| Expected total / home margin | 8.4574 / 1.2362 | 8.1554 / −0.8910 |
| Forecast object digest | `c87d341420ff02a6fe420c498b61472af5857015e6771f35d2f5b5706db69c3d` | `dbce974760e2106b2fa23a7ef7fd348d67b261d06e690febae2556fa0dd12fdf` |
| Physical forecast.json digest | `e0f7d7d2420177bf3b55c674d482dd8974024e5ded3daeb2923f67b1934a6760` | `c01c38997cf14fc75c8b4a66425ab5f6594a0022c61e8f5f6a952f073ef181e9` |

All four starter records say `PROBABLE`; all four ordered lineups say `CONFIRMED`. The JSON includes each batting order position, player name, MLBAM ID, AISP UUID and model canonical player ID. COL's independently timestamped Anthony Volpe handedness supplement was retrieved at `21:21:09.868087Z`; it did not overwrite the original lineup's null batting hand.

Both forecasts used 5,000 simulations, master seed `20260907`, zero illegal states/nonterminations, and a retained exact 64-simulation replay claim. This audit independently recomputed the published expected home/away scores and win frequencies from the saved simulated population; no simulation was run.

The original PIT execution points to feature snapshot `17e38a5587faec6e62e1718762498edc36e4cd12cbdda241000466b8be4ee1fc`. The later aggregate's PIT snapshot `ee26fb4d1f0e36ae7e398be23bcb5a048f0f934b8257ccf3735aad0d8f969a72` is later evidence for numerical reuse; it is not PIT's original forecast evidence. The audit reads the snapshot bound by each original execution artifact.

Final aggregate completed at `21:29:54.124442Z`. Rerun `b756e73f56e3467325f83eccc2452220162ea285e553e0d0db44400b1af555b4` completed at `21:31:07.538966Z`: zero new inference, identical two forecast object hashes, reused compositions, and identical handoff descriptor. The final handoff logical identity is `df620d9564e133b0b53dcdd75666c263069d93aa277476a70ab4abd289dc0666`; physical SHA-256 `791e5c53df79d8c3c26ca3a3514d1302dc402fea5d49024fb88133ceb3b0380a`.

## What 246 supported fields actually means

The original 33 consisted of 6 identity fields, 6 handedness fields, 5 hypothetical PA-state fields and 16 basic calendar fields. The 213 additions were exactly 25 annual-prior fields, 31 PA/pitch-window and exposure fields, 150 team/schedule/venue-context fields and 7 further calendar fields. This was source assembly and accepted feature calculation, not 213 new external feeds.

Each successful game supplied 18 initial batting-order matchup templates plus 16 active pitching-staff templates, each with all 246 required keys and zero unsupported field cells. There were nevertheless 68 null raw cells for COL–NYY and 352 for PIT–CWS out of 8,364 per game. All are annual-prior-domain values. These counts include repeated template values and are not counts of distinct players. The JSON accounts for every absent cell and its frozen transformation.

Frozen treatment is explicit: the 11 Wave 1 rate families retain a valid raw rate or null and add posterior mean, exposure, reliability, posterior standard deviation and history-state predictors. The 10 Wave 2 families put their frozen component-posterior mean into the existing model slot. The frozen `COLD_EXPOSURE` rule maps an absent annual-domain log exposure to zero with `prior_missing=1`; dependency count fields remain null, not fabricated observations. Global median/mode imputation is prohibited in the frozen transformation metadata.

For example, PIT's original first template has no eligible annual pitcher prior. Its raw WHIP/SO-per-BFP/log-BFP are null. Saved treated outputs contain WHIP `1.2808138981170765`, raw SO-per-BFP null, log-BFP `0`, and posterior SO mean `0.22252411868692873`, standard deviation `0.04888245760762837`, with `TRUE_COLD_START`. That frozen label refers to the absent FD1 annual-prior domain: the source evidence explicitly says `careerNoHistoryInferred=false`. It must not be described as the pitcher having no actual career or current rolling history.

The 246-field accounting traces selected HGB slots and prior dependencies. Posterior uncertainty columns are predictors in the classifier and can change probability means; they are not an uncertainty-only multiplier. The five simulated PA-state fields also enter HGB probabilities. Identity/date fields support canonical mapping and point-in-time eligibility. The audit establishes these computational paths, not a measured nonzero importance for each field. Monte Carlo standard error is a separate function of simulation count and forecast win probability.

The prior PA estimator is frozen fold 5, SHA `44ec4f457741f1aaeff42b81af1be5fd2712e494709ff1a0a8f0742b88d71c8b`; transition fold 4 is `0e5e480f897ddefa5f9dddbc229a8a43bf29f7b81443c25ece611d9d4032b253`. Their physical checksums were verified without deserialization. The parent is `a6e7e99122f1b60701a4728b97b32fcc11e03405bfd456ed6cd54f69b69adb27`, treatment manifest `4d158e01a4a7d84fe6e7641f61edf0e9848f1775e025a2cec6c29cda22d479f3`. No target-class, Development split or sealed-boundary changes were made.

## Evidence semantics and refresh limitations

The player rolling windows use separately acquired completed-game history through September 9, exact last-100-PA/last-250-BF ordering, and accepted-history exposure. Original assembly availability is `21:07:30.438839Z`. This is current pregame evidence assembled retrospectively, not proof of availability at earlier historical forecast dates. The audit never opens source PA archives or sealed Final OOT payloads.

Annual inputs use the latest eligible FD1 prior season. The recorded archive observation/availability is August 16 `05:21:08.171241Z`, ingestion September 10 `16:34:31.579920Z`. An eligible prior can be older than 2025 when a player's latest available row is older. Loading and calculating from this frozen archive is automatic; acquiring a new annual FD1 release is not implemented by this adapter. It must not be presented as a current 2026 annual strength update.

Both games' context fields explicitly flag unavailable previous-game end/duration, current/previous venue altitude, numeric bullpen workload and pregame temperature. Rest/travel use scheduled start intervals and venue paths, not measured end-to-start recovery. Actual numeric bullpen workload and weather are not secretly filled by these indicator fields.

The pitching pool contains current active nonstarter roster members with current player histories, initially observed around 06:00 Eastern. This is an active staff candidate distribution. It does not prove reliever-specific availability or predict actual appearances. Starter `daysRest`, `workload`, `pitchesLastStart` and `pitchesPreviousDay` are null in the source participant records. The accepted starter-removal policy and team-staff mixture remain fixed. Ordered starting lineups remain fixed through simulation, without bench substitutions.

These limits matter for interpretation but do not justify modifying frozen V18 or substituting stale templates. Future publication must independently verify current roster/lineup/starter evidence, source completeness and pregame cutoff; the September 10 success supplies no blanket future authority.

The audit performed zero provider requests, zero spending, zero inference/fits, zero AISP writes and zero sealed-data reads. It verifies original child bytes, current input/treated ordering, canonical lineup bindings, original clocks, saved population reconciliation, full-day identity accounting and exact retained rerun identities. Research authority remains `RESEARCH_SHADOW / NOT_PROMOTED`, with no wagering authority and no AISP model execution.

## Existing upstream refresh ownership

A separate read-only inspection of `C:\Users\james\ai-sports-predictor` found the upstream source refresh is already part of AISP's backend scheduler. `server/app/main.py:30` starts its scheduler; the local configuration enables `SCHEDULER_ENABLED` and `LIVE_SHADOW_ENABLED`. The existing `http://127.0.0.1:8010/readyz` response reported `ready`, database `reachable`, scheduler `running`. This inspection made no job call or AISP write.

`server/app/jobs/scheduler.py:382` schedules the daily pipeline at 06:00 America/New_York. `server/app/jobs/orchestrator.py:1690` calls schedule and MLB-data refresh; `refresh_mlb_data` fetches current team rosters at line 1279 and game lineups at line 1343. The daily pipeline has startup catch-up when that day's successful 06:00 run is absent. It is not a promise of execution while Windows is off.

The availability job is scheduled at the configured fast interval (`scheduler.py:445`), default 2 minutes. `services/live_shadow_service.py:63` applies a 10-minute per-game cadence outside four hours before first pitch and 2 minutes inside four hours. The job fetches schedule and, inside four hours, current ordered lineups. `orchestrator.py:265` persists verified starter evidence when its latest observation is older than ten minutes, even if the starter identity is unchanged. These are source freshness observations, not newly published model forecasts.

Unchanged lineup content also receives fresh observation clocks: `data_sources/mlb.py:770` records the HTTP retrieval time as `LineupDTO.available_as_of`; `ingestion/normalizer.py:451` deduplicates on both that timestamp and the DTO checksum, then stores observation and availability at that time. A successful new nonempty lineup response therefore does not retain an old observation time merely because the batting order is unchanged. The poll's ingestion receipt is aggregate (due/polled games, persisted lineups, starter heartbeats), not a per-game successful-empty-lineup receipt.

The monitored-game query admits future LIVE rows, but this scheduled job fetches only its current local `event_date`; next-day games do not receive tomorrow's roster/lineup evidence from today's source query. Next-day daily rosters are captured by that day's 06:00 job. Same-day roster and event-aware starter/lineup freshness checks are therefore appropriate publication dependencies.

Both the tracked and installed `scripts/start-backend.cmd` / `C:\Users\james\AppData\Local\asp\start-backend.cmd` point to `scripts/asp-backend-supervisor.ps1`, documented as the supervisor for task `ASP Backend 8010`. Direct Task Scheduler and process-owner queries in this execution context returned OS access errors. The live health response proves a running scheduler; task ancestry and actual task restart settings require separate owner verification and are not inferred from the launcher files alone. No additional AISP adapter was installed.
