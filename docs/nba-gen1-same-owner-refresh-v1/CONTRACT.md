# NBA Gen1 single-owner refresh and publication

This supersedes uninstalled deployment `0aa50236f9dcac875106c13c6749e025126370e700a4467915275251ad583a88`. It does not install, approve network access, or activate AISP. The final staged identities are in RELEASE_RECEIPT.json and ACTIVATION.md. The physical REFRESH_PLAN.json hash is in the immutable refresh-authorization proposal, not a self-referential field inside the plan.

## One invocation

`ASP NBA Forecast Publisher` remains the sole proposed task: S4U, Limited, IgnoreNew, 15 minutes, 12-minute execution ceiling. Its existing wrapper calls one Python owner. A single OS lock spans planning, capture, admission and slate dispatch. The compatibility capture command only displays the plan; standalone live execution is disabled. No new capture task exists.

1. Verify the deployed release, every member, exact plan, current input pointer, frozen models and residual identity.
2. Recover a completed capture from its durable ledger if admission was interrupted. Do not request it again. An interrupted transport with unknown completion stops for review and reserves its budget; it is never automatically retried.
3. Plan against the retained schedule, actual UTC time, local New York daily boundary and prior actual source validation. Most 15-minute ticks have zero network intent.
4. A due capture requires both the explicit enabled runtime flag and a James grant bound to this deployment, proposal and plan's physical hashes and exact authorization interval. Default is disabled. A due but unapproved refresh produces `LIVE_ACQUISITION_NOT_AUTHORIZED`, zero calls and no publication.
5. Conditional response 304 references the preceding physical raw object and original acquisition clock. It adds an actual server-validation clock; it does not claim missing finals became available. An unchanged 200 likewise reuses bytes. Changed 200 retains a new physical object and predecessor.
6. Admit the whole schedule/history version. Metadata selects completed regular-season games before scores are read. All eligible current-season finals are rebuilt from the same snapshot; corrections cannot leave stale rows behind. Identity, final score and frozen-model verification completes before atomic `current.json` replacement. Original source clocks remain present.
7. Dispatch all due games from one admitted snapshot. Check freshness, status, effective time and pre-tipoff cutoff before reuse. Unchanged prediction content reuses the original package and clocks; actual validation-only input revisions are retained separately. Changed content creates a new revision while due.
8. Publish immutable packages, publication receipts and cumulative discovery. A per-game failure does not erase successful games. Discovery carries time-limited current-eligibility leases, all earlier revisions and explicit exclusions.

Every invocation writes immutable owner-start, phase and owner-final receipts plus a runner receipt. The PowerShell wrapper writes start/final launcher receipts, captured stdout/stderr, exits and physical runner binding. A crash can leave a start without final; that is interruption evidence, never success. Local tests are not natural S4U receipts.

## Source and proposed bounds

One asset only: `https://github.com/sportsdataverse/sportsdataverse-data/releases/download/espn_nba_schedules/nba_schedule_2027.parquet` (2026-27 schedule/status/full-game final scores). Existing score/date history through 2025-26 remains local. Team-box data is preserved but not used by this selected model. No NBA.com, nba_api, sportsbook, credentials, discovery API or second source.

The exact JSON lists the expected physical Parquet fields, admitted metadata and score fields, retained CC BY 4.0 rights references, attribution and correction semantics. Three bounded HTTPS transport redirects may follow the originating asset's Location responses using the enumerated hosts/path prefixes. Signed transport queries cannot be enumerated before a server response; they are not independent acquisition endpoints and are not logged. An unexpected redirect fails closed.

Proposed ceilings: one logical asset check per invocation; at most four HTTP requests including redirects; eight capture attempts / 32 HTTP requests per UTC day; 16 MiB response bodies per invocation and 128 MiB per day; zero retries; at least 60 minutes between attempts; 5 GiB private source/capture/admission storage with 32 MiB admission headroom reserved before capture. The existing forecast/evidence retention policy is separate. Counters persist before the first call and after every request/chunk. No historical allowance is reset.

Proposed interval: **2026-10-13 18:00 UTC through 2027-04-19 04:00 UTC**, end exclusive. This is not an authorization. Any altered source, schema, budget, period or cadence requires a new proposal and grant.

## Efficient refresh policy

The retained 2027 asset's Last-Modified is September 9 and acquisition September 14. Release metadata does not establish an hourly update SLA. This policy checks availability; it cannot compel upstream updates.

| Phase | Trigger |
|---|---|
| Preseason/opening | First admitted tipoff minus seven days minus 60 minutes; no earlier calls |
| Routine status/corrections | First eligible tick at/after 10:00 America/New_York; prior successful validation satisfies that day |
| Publication preparation | Within the hour before T-7d, T-24h, T-6h and T-1h, if no validation since that hour began |
| Freshness protection | Due-game input age reaches 23h; final-hour age reaches 90m |
| Postgame history | Check at scheduled tipoff+4h; this is not assumed final. If unresolved, at most every two hours for 48h, subject to all global ceilings |

Freshness: schedule validation and complete-history validation at most 24h old, at most 2h at T-1h. Publication ends at T-30m. A source 304 does not waive identity/completion checks. Any elapsed unresolved regular game blocks whole-version admission. `SOURCE_FINAL_PENDING` may be reconsidered at the next bounded due capture; no repeated HTTP retry. Access refusal, schema drift or identity/score inconsistency is quarantined for explicit review. The prior admitted pointer, packages and discovery revisions remain unchanged on failure; no stale forecast is silently renewed. Existing eligibility leases expire without a refresh.

## Recovery and authority

Capture committed, admission interrupted: reuse the retained capture locally. Admission committed, publication interrupted: use the complete admitted pointer. Package prepared/copied, journal interrupted: existing per-game transactions recover without resimulation. Unknown HTTP completion: no automatic retry. Global input failure skips the entire publication phase; per-game rendering failures are isolated only after complete admission.

The unchanged point model is `NBA_GEN1_ELO_WIN_RIDGE_A100_ORDINARY_REST_V1`: Ridge alpha100 expected scores and separate chronological Elo winner probabilities. Joint scores/totals use `NBA_GEN1_JOINT_FINAL_PAIRED_OOF_LATTICE_V1`, 10,000 paired draws, deterministic master seed 20260914. Their probability authorities remain distinct. Close-score challenger stays disabled. One-point finishes were 7.78% simulated versus 4.01% observed; the correction was rejected; overtime is harder; no profitability claim.

No new model fit, source data request, forecast, consumer import, decision or position is authorized by this code or proposal. AISP must separately validate/pin the completed handoff and explicitly activate its consumer. Earlier BOS-DET and PHI-NYK packages remain immutable with their original authorities.

## Reproducible focused verification

From the source checkout, with the existing Model Studio Python environment:

```powershell
& 'C:\Users\james\asp-model-studio\.venv\Scripts\python.exe' -m pytest tests/test_nba_same_owner_refresh.py tests/test_nba_slate_publisher.py tests/test_nba_gen1_production.py -q -p no:cacheprovider
```

All lifecycle transport fixtures are synthetic and inject responses without using HTTP. The retained real slate is verified only at the actual current time, which is before its first checkpoint. See VERIFICATION.json for exact launcher/runner receipts and physical preservation checks.
