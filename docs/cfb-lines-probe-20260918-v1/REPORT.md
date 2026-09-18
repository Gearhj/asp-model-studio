# One bounded CFB lines validation

This standalone intake implements James's September 18 authorization for exactly
one `GET /lines?year=2026&week=4&seasonType=regular`: zero retries, 5 MiB, $0.
It does not change the selected model, recurring source plan, installed deployment,
input pointer, forecast publication, consumer configuration or scheduler.

Before live execution, inspect retained CFB request manifests for this exact probe
and reuse a usable response if present. The script itself prevents repetition of
its canonical attempt, including failures or interruption. Source code starts from
reviewed commit `73c2a5b92d6dcf0159ec1ffcc7ce39927b8d336c` in a separate worktree.

The existing publisher's `state/publisher.lock` serializes the probe with the
single owner. A durable request reservation is placed in
`state/capture/attempts/lines-week4-2026-once` before HTTP. The existing owner counts
this receipt toward UTC-day and period ceilings, includes raw `response.json` in
retention, and conservatively charges an interrupted unknown attempt at its full
seven-request/25-MiB capture allowance. Successful probe accounting records one
request and actual response bytes. Because the existing owner also uses the last
attempt time for spacing, the probe conservatively restarts its 90-minute minimum.
Run promptly after a natural owner capture and disclose that next due boundary.

The probe requires a verified, successful owner capture in the same private state
root, completed within 30 minutes, with retained `/info` bytes and no later known
attempt. It makes no additional entitlement HTTP requests. The latest checked
free allowance and a conservative one-unit deduction are reported separately;
the deduction is not mislabeled as a newly queried account balance.

Credentials are loaded only through the previously reviewed transport, never
printed, copied or hashed. Redirects and retries are disabled. Raw response bytes
remain private under the capture attempt. Acquisition time is never substituted
for quote time. Claude determines price authority and owns any consumer action.

Run `scripts/probe_cfb_lines_once.py` with explicit `--state-root`, `--plan`,
`--grant`, `--deployment`, `--probe-grant`, `--entitlement-receipt`, and `--env-file`.
The one-shot grant binds `approvedBy=James`, the exact request object, recurring
plan SHA, `maxRequests=1`, `maxResponseBytes=5242880`, `retryCount=0`,
`maxCostUsd=0`, and a hashed `authorizationEvidence` reference.

Focused synthetic verification: nine checks cover successful one-request intake,
retained response reuse, shared ledger counting, zero retry after a failure or
interruption, all request/byte/storage budgets, stale entitlement refusal, exact
byte ceiling and the absence of invented quote or settlement conventions.
Live execution evidence is retained separately outside Git.
