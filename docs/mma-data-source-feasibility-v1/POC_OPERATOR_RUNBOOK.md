# UFC Generation 1 no-network POC harness

This harness plans and validates the bounded two-card study. It performs **zero network calls by default** and the checked-in CLI intentionally refuses `--execute-live`. It is not an ingestion owner, scheduler, model, forecast producer or AISP integration.

## Local secrets

Put secrets only in untracked `C:\Users\james\asp-model-studio-source\.env.mma.local` or the local process environment:

```text
MMA_API_SPORTS_KEY=<owner supplied value>
MMA_THE_ODDS_API_KEY=<owner supplied value>
MMA_POC_RIGHTS_APPROVED=YES
```

`.env.local` and `.env.*.local` are ignored by repository rules. Never pass values on the command line, echo them, include them in a URL, or attach them to a receipt. The code reports only whether required names are present. `MMA_POC_RIGHTS_APPROVED=YES` may be set only after the acquisition/retention/modeling/derived-publication conditions in the feasibility report are approved.

## Safe commands

```powershell
Set-Location C:\Users\james\asp-model-studio-source
python -m server.sports_mma.poc.plan_cli
python -m unittest server.sports_mma.poc.test_poc_harness -v
```

The plan must report `liveExecution=false`, `networkCalls=0`, API-Sports requests `80/80`, and The Odds API credits `80/80`, region `us`, market `h2h`.

## Reserved later live command

```powershell
python -m server.sports_mma.poc.plan_cli --execute-live
```

That command currently exits with `LIVE_EXECUTION_NOT_IMPLEMENTED_IN_NO_NETWORK_HARNESS`. A later authorized task must add and review the transport and raw-capture store. It must preserve the same CLI flag, require all three local variables above, reserve budget before each call, and never log headers or query secrets. Do not modify the CLI to bypass this stop.

## Ceilings and stop conditions

- API-Sports: at most 80 total HTTP requests for the entire POC.
- The Odds API: at most 80 credits, exactly one `us` region, `h2h` only.
- Stop before a call when the remaining provider-reported balance conflicts with the local ledger.
- Stop on schema drift, HTTP auth/rate errors, missing timestamps, future/post-cutoff evidence, identity ambiguity, orphan joins, participant reversal without a version, incomplete final/result statistics, or a latency breach.
- Stop if rights, retention or publication authority is uncertain. Do not substitute website scraping.

## Capture, quarantine and cleanup

Live raw bytes, if separately authorized later, belong in an ignored local quarantine such as `.runtime/mma-poc-v1/private-sources/`, never Git. Write bytes atomically, hash after re-read, then append a metadata receipt containing provider, endpoint identity without credentials, byte count, timestamps, schema fingerprint and predecessor. Conflicts and drift move to a read-only quarantine and do not update canonical records. Cleanup removes only explicitly named scratch files after their absolute path is verified inside that runtime root; immutable captures and receipts remain until the approved retention policy says otherwise.

## Still prohibited

Provider calls, historical dataset download, UFC/UFCStats/Tapology/Sherdog scraping, bulk ingestion, model fitting, forecast publication, exchange or AISP writes, scheduler creation, and production activation remain prohibited pending separate authorization. SportsGameOdds remains outside this harness pending entitlement and ML/derivative-use clearance.
