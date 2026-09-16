# Temporary NFL archive / MLB prospective-measurement handoff

Status snapshot: 2026-09-11 21:04:53 UTC. Repository branch:
`codex/mlb-starter-duration-source-intake-v1`; starting commit
`edc6f5460b9ad066b2a2b0f2fd461e17ac3266d4`.

## Actual scheduler changes

Only `archive-nfl-forward-evidence` was paused, at
2026-09-11T20:52:51.349Z. Its original six-hour recurrence, complete prompt,
task/thread identities, original config bytes, scheduler row/run state, archive
cursor and five referenced archive metadata objects are preserved in an
immutable pre-change receipt. No NFL evidence was changed by this assignment.
Its prior last run was 2026-09-11T15:35:29.175Z and prior next run was
2026-09-11T21:35:24Z; the paused scheduler correctly has no scheduled next run.
The original archive cursor SHA-256 remains
`b9987199d7baef8fbc1578d073803cab41169443e6f52e17705df7234e14ab98`.

`mlb-starter-pair-readiness` became ACTIVE at 2026-09-11T20:57:47.720Z,
on its five-minute recurrence. Both task states were verified against their
configuration files and the scheduler's read-only database, not inferred from
an update request. All task mutations used the supported automation tool.

Immutable receipts live under
`outputs/mlb-starter-duration-paired-research-v1/monitoring/objects/sha256/<digest>/monitor-event.json`:

| Event | SHA-256 |
| --- | --- |
| Original configuration/state/evidence snapshot | `a01c77204d2049e98202dfc64eafe6a71184762d1521aa380be204500802e2e4` |
| NFL pause actually verified | `ffbeed222d166ddb1aee93a0748466ab87accf961e810e8bc00e10823c3a90dc` |
| MLB activation actually verified | `88429d5d439c9e9d8376e948e4dc6c8eb7060411112c4b2422bfee67785745b8` |
| Latest readiness/scoring attempt | `6dc0fe6ba6e05057790f519b54d2f28f27517b68450d03cbb0df847c90f887e4` |

`monitoring/current.json` is the mutable pointer to this immutable event chain.
The snapshot receipts intentionally contain original local task configuration;
they are not an AISP forecast-import payload.

## Prospective accounting

The last completed all-game readiness pass (20:09:48.133091 UTC) accounted for
all 15 declared September 11 games: 1 expired unpublished game (PIT–CHC),
13 pending and 1 published pair. Two subsequent checks at 21:01:52 and
21:04:53 deferred additional readiness inspection because the production
publisher owned its existing lock. Thus **zero games received a fresh readiness
inspection in these two attempts**; the saved 15-game accounting is not a claim
of freshly refreshed sources. Pending games remain eligible for later scheduled
checks while their deadlines are open, without expanding the acquisition scope.

There is 1 published pair, 1 awaiting a persisted final and 0 scored. The pair
is COL–DET, game `7323d8f3-9b24-464d-903e-fe290913d73b` / MLBAM `824227`,
published at 20:09:47.587959 UTC before its 22:35 UTC deadline (22:40 start).
Pair SHA-256 remains
`fdee9e2fa72c8339c9bbd0d9e723d8898c34c80671c44eaf1d1f843674edfd45`;
population SHA-256 remains
`1bc53f34cb40173459fbd2b6f2ba88d618c8f2e6f6616f59bbb9659dbc244534`.
Both frozen 5,000-draw arms, inputs and probabilities remain unchanged.

No final connection or outcome query was opened: the pair had not started.
This assignment made 0 provider requests, downloaded 0 provider bytes and cost
$0; prior cumulative intake remains 60 requests / 23,363,290 bytes / $0.

## Final measurement, not development

The scorer first reads status/timing/revision metadata. It requires a persisted
revisioned `game_final_outcomes` FINAL with eligible timestamps; a bare canonical
game FINAL without revision lineage is insufficient. Only then may a separate
final-only query retrieve scores. Both arms use the same final revision.

Each arm reports binary winner log loss/Brier; predicted-minus-actual home and
away runs, home margin and total (signed, absolute and squared error); empirical
marginal CRPS; joint Euclidean energy score; and 50%, 80% and 90% prediction
intervals and coverage. These are single-game measurements, not independent
trials for each simulation or a model-selection comparison.

Actual starter BF for Mason Adams (away, MLBAM 690279) and Framber Valdez (home,
664285) requires exact saved player/team/game identity, the same final revision,
explicit actual-starter attribution, an eligible official source, a successful
source checkpoint and retained checksum/timestamp lineage. The optional read is
isolated so missing historical-boxscore tables or facts cannot abort whole-game
scoring. Unsupported BF remains explicit; it is never inferred from team PA.
The existing AISP finalizer does not itself guarantee that these starter-history
observations are populated. No actual BF availability is claimed yet.

The predeclared experimental difference is the starter-duration adapter; the PA
model and other controlled inputs are unchanged. Different simulated stopping
times can alter downstream play trajectories. Realized error differences do
not establish managerial causality, general superiority or wagering edge.

No fitting, tuning, selection, official V18 changes, 2% threshold changes,
positions, settlements, AISP writes or wagering authority changes occurred.
The three permanent quarantine exclusions and remaining sealed OOT are unchanged.

## Automatic NFL restoration and actual-run verification

Every wake first runs `scripts/manage_mlb_pair_monitor.py decision`. Restore
the original NFL task when all currently published pairs are scored, or at
2026-09-12T20:52:51.349Z (24 hours after pause), whichever occurs first. Do not
declare another slate. Expired unpublished games cannot be backfilled.

The helper returns exact supported-tool arguments to pause MLB and restore NFL.
After those tool calls, `restored` checks actual ACTIVE NFL / PAUSED MLB state
and records the original and newly scheduled next-run timestamps separately.
It does not silently replace the historical prior-next-run information.
`verify-restored-archive` then executes the original idempotent NFL archive
once, verifies that the preserved original metadata remains unchanged, and
records actual execution. Delete only the completed MLB heartbeat after both
verification steps succeed. Never delete the NFL task.

The hard-limit restoration decision takes priority even if MLB pair/readiness
artifacts are missing or corrupt. Such problems must be reported but cannot
indefinitely suppress NFL restoration. Readiness/scoring failures receive
immutable monitor receipts. Failed supported task restoration requires a
notification and restoration-only retry, not renewed MLB work after expiry.

**Restoration and the resumed archive run are not yet due or verified.** These
are local Codex heartbeats: the computer must be awake and Codex running. They
are not an OS-independent unattended service. If unavailable at the limit,
restoration is the first action on the next wake; exact wall-clock execution
while the computer/app is stopped is not guaranteed.

## Focused verification

Three focused tests pass: existing paired-scoring metrics and the extended
final-gating/optional-BF regression, plus the restoration decision regression.
Checks cover nonfinal score-read prevention, provenance requirement, optional
BF failures/conflicts, first-of-completion/24-hour restoration, restoration
despite corrupt MLB artifacts, already-restored behavior, and nonoverlapping
published/expired/pending accounting. No model or simulation reruns were used.

The live switch and two actual final-read guards are recorded separately from
test fixtures. Future restoration is verified only by its actual receipts.
