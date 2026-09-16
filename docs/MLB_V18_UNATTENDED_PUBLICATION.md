# V18 unattended current-slate publication

This successor operationalizes the frozen V18 publisher; it does not promote a model or change AISP. The starting MLB branch was `codex/mlb-v18-current-state-pipeline-v1` at `48075e0967479d2fc13658874780d1a98ac377a6`. The NBA branch `codex/nba-sportsdataio-pilot-v1` at `da05d9f6f12ecb628101dab42f67709101d01265` remains preserved. Unrelated NFL work is not part of these commits.

## Evidence and scientific meaning

[September 10 reconciliation](MLB_V18_OPERATIONAL_EVIDENCE.md) links the immutable 246-field, per-template audit. The full five-game day comprises TB–ATL, HOU–PHI and TEX–SEA explicitly skipped before first pitch, then COL–NYY and PIT–CWS published. The player-history bridge became available too late for the first three; they were not undiscovered games. No late replacement was created.

Both original forecasts retain 5,000 simulations and seed 20260907. COL/NYY away/home probabilities are 0.357/0.643 and expected scores 3.6106/4.8468. PIT/CWS are 0.5718/0.4282 and 4.5232/3.6322. Original object hashes are `c87d341420ff02a6fe420c498b61472af5857015e6771f35d2f5b5706db69c3d` and `dbce974760e2106b2fa23a7ef7fd348d67b261d06e690febae2556fa0dd12fdf`.

All 246 input slots were supported, including accepted annual-prior null branches; this does not mean every slot was currently measured. Workload, weather and previous-game-end gaps remain explicit. The staff pool is a candidate mixture, not a forecast of actual reliever availability; fixed starting lineups do not model bench substitutions. The original PIT staff pool used fifteen same-day roster observations and one September 9 observation. This successor does not rewrite that evidence: future captures select each team's latest complete roster retrieval and retain superseded per-player ACTIVE records separately. Absence from a later active roster is not relabeled as an observed injury or inactive status.

The accepted PA/preprocessor/encoder SHA remains `44ec4f457741f1aaeff42b81af1be5fd2712e494709ff1a0a8f0742b88d71c8b`; treatment manifest remains `4d158e01a4a7d84fe6e7641f61edf0e9848f1775e025a2cec6c29cda22d479f3`. Target classes, chronological Development authority, frozen transition and sealed Final OOT evaluation remain unchanged. Independently acquired finalized operational history uses the existing explicit current-input authorization; it is not sealed evaluation access. The RF executable remains blocked and the ensemble non-operational.

## Implemented changes

- Current plus next available regular-season slate discovery uses the outcome-free MLB schedule projection. Every provider event is retained, including missing canonical mappings, time/team conflicts, closed games and explicit skips. AISP is read-only.
- A cheap participant preflight precedes historical assembly and model loading. Required ordered lineups must be confirmed. Original starter/lineup observations must be no older than 30 minutes inside four hours before first pitch (24 hours farther out). This reflects the existing two-minute upstream lineup polling and ten-minute starter verification, not a modified AISP readiness score. The latest team roster batch has a 30-hour maximum age, allowing six hours beyond its daily cadence. Freshness is rechecked after source assembly.
- Existing completed-day source catalogs and player windows are reused. Daily catch-up remains bounded to 14 dates, two concurrent public calls, and a three-day correction window. Missing static handedness can use at most four explicitly current, canonically mapped participant identity requests per tick; cached identities are reused. Source failures receive cooldowns, not an inner retry loop.
- Numerical identity excludes producer revision, file paths and polling metadata. It retains frozen artifacts, seed, simulation count, regulation length, ordered participants and eligible input values. All source/participant clocks are validated before reuse. No model is loaded for a numerical cache hit.
- Exact per-player window anchoring removes batch-dependent floating-point cancellation without rounding or changing Gold/the estimator. The first verified vector is keyed by role, canonical player, exact content authority and ordered last-N source proof. Prior vectors are reused only when these proofs match. Annual, lineup and context values remain current. Four final-bit differences in a live PIT verification exposed this defect; its redundant inference was stopped before publication. The repaired vector and original provider inputs subsequently matched byte-for-byte and reused the original object with zero inference. Receipt: `outputs/mlb-v18-unattended-v1/objects/sha256/88218b69879c8834786a66dbffa392e0ce80094879e88945184b6b69c53c8814/exact-source-window-reuse-verification.json`.
- New inference/publication closes five minutes before scheduled first pitch, with checks before and after scoring and before immutable publication. Closed games can retain their authentic earlier forecast, but cannot receive a new retrospective one. An OS-held lock and Scheduler IgnoreNew prevent parallel owners; the launcher owns its child process tree.
- Immutable exchange packages verify logical and physical hashes, byte counts, participants and child bindings. A stable handoff and game accounting reuse the original package/receipt; new polling receipts remain in Studio. Empty forecast packages are accounting-only, not falsely importable.

## Cadence, ownership and dependencies

See [Windows deployment and ownership](MLB_V18_SCHEDULER_OWNERSHIP.md) for installation, pinned code, kill switch, failure receipts and verification. The canonical task is `\ASP MLB V18 Research Publisher`. The five-minute Windows wake is a local dispatcher, not five-minute indiscriminate model inference. Games beyond 24 hours are accounted but deferred. Due-game source checkpoints are 6 hours, 60 minutes, 30 minutes, 15 minutes and 5 minutes as first pitch approaches; closed slates switch to an hourly check. Persisted failures use 15-minute then 60-minute per-game cooldowns; a failed global stage uses 30 minutes. STOP prevents a new launch and is checked between stages; an already-running bounded stage may finish before its next check. Scheduler's 60-minute limit owns descendant cleanup.

Upstream AISP evidence capture already belongs to the independently supervised `ASP Backend 8010` startup task. PostgreSQL runs as an automatic Windows service. Its 06:00 Eastern daily run refreshes rosters/schedules, with startup catch-up; its availability job refreshes current-day starters/lineups. Tomorrow's AISP canonical schedule is not guaranteed to exist tonight. The V18 dispatcher rechecks, never manufactures mappings or writes AISP to unblock itself. It depends on these local services, public source availability, network connectivity and the existing archives/venv remaining available.

The scheduled deployment is a committed-byte snapshot under `.deployments/mlb-v18-unattended/<commit>`, not the currently checked-out branch. Shared immutable outputs/runtime remain in the original repository. Code/config and Python hashes are checked before launch. Startup/StartWhenAvailable support future-game catch-up after restart; no claim is made of continuous operation while the computer is asleep/off, or of an actual reboot/logout test unless recorded in the execution receipt. Codex and its NFL archive heartbeat are not owners of this producer.

## Sources, economics and limitations

| Source | Classification | Use and constraint |
|---|---|---|
| MLB Stats public schedule/identity endpoint | Free public access observed; published rate limit/SLA unknown (not claimed unlimited) | Outcome-free schedule discovery; bounded missing-hand queries; no key, billing endpoint or odds allowance |
| Baseball Savant Statcast CSV | Free public access observed; throttling/rate ceiling unknown | Completed-day PA/pitch evidence; two-request concurrency cap, original bytes and rights retained |
| AISP PostgreSQL observations | Local archive | SELECT-only schedule, starters, lineups, roster, source clocks; no job trigger, persistence change or paid provider call |
| Accepted Silver/FD1/model artifacts | Local archive | Governed current-player windows, annual priors and frozen inference; not current roster/lineup substitutes |

The official [Statcast CSV documentation](https://baseballsavant.mlb.com/csv-docs) defines the downloaded fields. The [Stats API documentation endpoint](https://docs.statsapi.mlb.com/) exposed no public rate-limit guarantee during this inspection. Neither establishes commercial redistribution rights. Existing restrictions remain LOCAL_PRIVATE_MODEL_DEVELOPMENT, attribution, Statcast GOVERNED_LOCAL_RESEARCH_ONLY and commercial-rights review; raw redistribution is not authorized. No paid/metered sports or odds source is called. New receipts count actual urlopen invocations including failures, not merely successful captures; urllib internal redirect hops are outside that measurement boundary. Documentation browsing is separate from the producer request ledger.

## Latest real run and AISP handoff

Actual tick `7c39644f59430242fd12db3d4dd260c1068f75748745c590375b70220ebdb565` completed at 2026-09-10 23:35:07 UTC: all 20 games accounted; September 10 retains two forecasts/three closed skips; September 11 has zero forecasts/fifteen explicit missing-canonical-event skips. No post-start forecast or new model fit was created. Later scheduled verification receipts supersede the operational status, not these preserved artifacts.

The two-forecast, full-five-game handoff physical SHA is `04ab74c05d699fda5a9c092e5efc050f3ac8d06d35644d27cc755a5ddac2a5d8`. Its exchange package root is `C:\Users\james\asp-model-exchange\mlb-v18-current\sha256\436227aa81f905424f7b4543a5352e2021646aa81b1f3b07b994e762a68e699d`. `exchange-package.json` supplies the exact relocated handoff/receipt paths and executable import command. The September 11 empty package is evidence of pending source identity, not a successful forecast publication.

Claude: verify all package child hashes, preserve `capturedAt <= forecastCreatedAt < scheduledStart`, use actual `forecastCreatedAt` as forecast availability and `capturedAt` as evidence cutoff, then run the `importCommand` in that exchange manifest and repeat once for idempotency. Import only precomputed V18 as a separate RESEARCH_SHADOW track beside Gen1. Do not execute V18, rewrite Gen1, change policy, create decisions/positions, or grant wagering/promotion authority. The original AISP importer timestamp mapping needs Claude's confirmation/correction; this assignment makes no AISP changes and does not claim a completed import. These current forecasts include Broadcast Replay and numerical population, not newly generated renderer geometry supplements.

Focused checks cover source request failures/accounting, exact window/vector reuse, changed-input-only versioning, eligibility/cutoffs, stale-roster exclusion, scheduler cadence/ownership/committed deployment and exchange idempotency. No broad suite, training, calibration, model selection, sealed evaluation access or unrelated UI work was run.

## Installation boundary observed in this run

Windows rejected actual registration as current-user S4U/Limited: `Windows rejected registration of ASP MLB V18 Research Publisher as current-user S4U: Access is denied.` No alternate owner was created, no security policy/ACL changed, and no password or SYSTEM fallback was used. The task is **not installed**; S4U network/database behavior and actual scheduled execution remain unverified. The durable mechanism is prepared, but unattended operation is blocked on administrator registration.

A manual pinned-launcher verification successfully reached the free schedule endpoint and local read-only database, then exposed a deployment-junction path mismatch when creating the import receipt. That failure is retained as tick `5cacae58c20daacf2859755784c119936e47ea54eeb2dd1c1e5b5daa1675ae3b`. Output roots are now resolved to the canonical shared directory; a focused Windows junction regression passed. The original launcher marked its configured owner as Windows even for this manual test; this receipt is **not evidence of a scheduled logon**. The corrected launcher separately labels manual and scheduled invocations. The final verification receipt records the corrected release result.

AISP's existing `verify_daily_slate` function independently accepted the real relocated exchange handoff and both forecasts. Only its read-only verification function was called: no importer/database transaction, model execution or AISP file change occurred.

## Final verified delivery

Verdict: `MLB_V18_UNATTENDED_PUBLICATION_PARTIALLY_BLOCKED`.

The corrected pinned release is `9bb1a947fc863596433fac569822ad95f2c71dac` (704 committed code/config files; 16,606,598 bytes; launcher also pins the build receipt). A manual launch completed at **23:47:40 UTC** with all twenty games accounted and **both exchange packages reused exactly**, zero new inference and zero new forecast objects. Its original mode is explicitly `manual-pinned-launcher-verification`; this is not an S4U execution test. Frozen V18 reloaded from that deployment and reproduced the 32-row physically Development-only fixture bit-for-bit, maximum difference zero. The actual STOP test exited before Python started; its temporary STOP file was removed afterward, preserving its receipt.

Machine-readable delivery: `outputs/mlb-v18-unattended-v1/objects/sha256/9501b0d80b6e93e76511301d1b77764029a0720a88008bd7dd0759a5e608e570/delivery-verification.json`, SHA-256 `9501b0d80b6e93e76511301d1b77764029a0720a88008bd7dd0759a5e608e570`. This links the manual tick, launcher/STOP records, source captures, exact reuse proof, both exchange packages and the Windows blocker.

Actual source accounting: **6 public schedule HTTP invocations; $0; no Statcast, identity, odds or paid calls in this assignment**. Five retained captures contain 215,862 downloaded bytes. One initial output-path failure occurred **after** the HTTP download but before source receipt persistence, so it counts as a sixth request; its byte count is unavailable, not zero. This corrects the initial assumption that that failure made no request. The unused redundant inference was explicitly stopped; one new-current-forecast attempt started and none completed. The original two forecast objects did not change. Source telemetry now counts failed requests at the actual HTTP boundary. Documentation browsing is excluded from this producer ledger.

Twenty-one focused tests across publication, source requests, identity, dispatcher, exchange and deployment passed, including the concrete junction regression. Additional actual checks established Windows PowerShell 5.1 parsing/guard execution, pinned reload, STOP behavior, real package reuse and AISP read-only verification. No full suite was run.

### September 11 pending slate

Every row below has the same first blocker: `CANONICAL_EVENT_NOT_REGISTERED_IN_LOCAL_IDENTITY_SOURCE`. Provider event and team identities and scheduled starts are present; AISP's event UUID binding is not. The next-day source capture therefore cannot yet attest its starter/lineup/roster/input contract. These are explicit pending skips, not forecasts or invented mappings. The current-day AISP pipeline normally registers/captures its slate at 06:00 Eastern; the prepared producer will recheck if it is installed. No historical lineup is substituted.

| Away–home | MLB event ID | Scheduled start UTC |
|---|---|---|
| PIT–CHC | 824631 | September 11 18:20 |
| COL–DET | 824227 | September 11 22:40 |
| LAA–WSH | 822684 | September 11 22:45 |
| NYM–NYY | 823498 | September 11 23:05 |
| BAL–TOR | 822767 | September 11 23:07 |
| KC–BOS | 824711 | September 11 23:10 |
| HOU–TB | 822930 | September 11 23:10 |
| LAD–MIA | 823817 | September 11 23:10 |
| PHI–ATL | 824873 | September 11 23:15 |
| CIN–MIL | 823736 | September 11 23:45 |
| CLE–MIN | 823659 | September 12 00:10 |
| CWS–STL | 823012 | September 12 00:15 |
| SEA–ATH | 824954 | September 12 01:40 |
| TEX–AZ | 825036 | September 12 01:40 |
| SD–SF | 823173 | September 12 02:15 |

### Exact administrator action

Task absence was rechecked at **23:49:00 UTC: zero matching V18 tasks**. There is no actual next scheduled run. Open PowerShell **as Administrator under James's account**, then run:

```powershell
$release = 'C:\Users\james\asp-model-studio\.deployments\mlb-v18-unattended\9bb1a947fc863596433fac569822ad95f2c71dac'
& "$release\scripts\install_mlb_v18_unattended.ps1" -Mode Install -RepositoryRoot 'C:\Users\james\asp-model-studio' -CodeRoot $release
Start-ScheduledTask -TaskName 'ASP MLB V18 Research Publisher'
Get-ScheduledTaskInfo -TaskName 'ASP MLB V18 Research Publisher'
```

Then inspect `.runtime/mlb-v18-unattended/state.json` and its referenced tick after the first **due** scheduled run. A `NOT_DUE` tick proves dispatcher launch, not source/model execution; actual S4U local-DB/public-HTTP access still needs that due run. The manual test left the next source checkpoint at approximately September 11 00:47 UTC, but no process will run it without installation. The kill switch is `C:\Users\james\asp-model-studio\.runtime\mlb-v18-unattended\STOP`. Closing Codex would not stop a successfully installed Windows task; powered-off/sleep time is not continuous operation, and restart catches up only still-future games.

Claude's exact next instruction: read `C:\Users\james\asp-model-exchange\mlb-v18-current\sha256\436227aa81f905424f7b4543a5352e2021646aa81b1f3b07b994e762a68e699d\exchange-package.json`, verify its child bindings, and run its `importCommand` after ensuring forecast availability uses `forecastCreatedAt` rather than capture time. Reimport once for idempotency. This imports only the two precomputed V18 research forecasts with all five September 10 games accounted; leave Gen1, policies, decisions, positions and wagering authority unchanged. The fifteen-game September 11 package is accounting-only and must not be passed to the forecast importer.
