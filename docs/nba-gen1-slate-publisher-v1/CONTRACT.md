# NBA Gen1 slate publisher contract

This successor replaces the uninstalled one-game execution design, not the
selected model. Installation and consumer activation are separate operations.
The superseded 7e04b1 deployment must not be installed. No existing task is
changed by staging, input admission, or local verification.

## Numerical authorities

Configuration: `NBA_GEN1_ELO_WIN_RIDGE_A100_ORDINARY_REST_V1`. Frozen Ridge
alpha100 ordinary-rest supplies point means; chronological Elo independently
supplies controlling winner probabilities. The fixed
`NBA_GEN1_JOINT_FINAL_PAIRED_OOF_LATTICE_V1` supplies 10,000 paired final-score
draws (HOME, AWAY), totals, margins, intervals and distribution probabilities.
Its master seed remains 20260914 with the existing per-game deterministic
derivation. No model, preprocessing, residual bank or numerical module is fitted
or changed. Input-history updates recompute the same features and chronological
Elo state using newly admitted earlier games; they do not refit the models.

Close-score correction remains disabled and rejected. Historical simulated
one-point finishes were 7.78% versus 4.01% observed. Overtime games remain harder.
There is no profitability claim or player/lineup/injury information.

## Due games, freshness and revisions

Every admitted schedule row receives a disposition. Supported targets are NBA
regular STD, mapped distinct teams, scheduled and nonneutral. Neutral games can
enter symmetric history but not production targets. Other competition types,
unresolved identities, cancellations, postponements and completed games remain
explicit. A date/team-pair duplicate or source identity conflict stops admission.
BOS–DET is not blacklisted: its original research packages remain byte-identical,
and it can receive a distinct future production revision under these rules.

Checkpoints: T−7 days, T−24 hours, T−6 hours, T−60 minutes. A 15-minute owner tick
checks every due game; the final publication cutoff is T−30 minutes. These are
producer checkpoints, not an assertion about AISP's betting deadline. Consumers
must enforce their own potentially earlier decision deadline. No publisher
clock is presented as a wagering deadline.

Schedule acquisition and history-membership certification must be at most 24
hours old; at the T−60 checkpoint both must be at most two hours old. They must
not be future-dated. Date arithmetic uses aware UTC; the source calendar date is
validated using America/New_York, including daylight-saving changes and UTC
midnight. Final outcomes enter features only after source capture; target and
same-date/later games remain excluded by the unchanged feature contract.

Freshness, status, source integrity and pre-cutoff eligibility are checked BEFORE
reuse, then again after rendering and immediately before publication. Unchanged
input and release bytes reuse the identical package at later checkpoints, with
new eligibility receipts rather than refreshed forecast clocks. A new admitted
input version, target change, or release produces a distinct revision key.
Earlier packages are preserved even when no longer eligible. Packages whose
inputs fail or whose game has started can never become current by reuse.

## Versioned input admission and refresh

`admit_nba_gen1_slate_inputs.py` takes a retained capture receipt, frozen base
model/history certificate and retained source-rights references. It reads
identity/status metadata first, then only eligible regular FINAL score rows for
future feature updates. It rebuilds the current season from the supplied source
version, retaining corrections and predecessor lineage. This never turns current
acquisition times into historical publication vintages.

All raw, normalized history and model artifacts remain private and outside Git.
The input registry uses immutable `versions/sha256/<digest>/input.json` objects
and one atomic `current.json` pointer. A capture cannot regress in time or silently
change model weights. Repeating the same capture reuses the original input version.
Updates are snapshotted at tick start, so a concurrent pointer update affects only
the next tick. Changed input digests do not require an executable rebuild.

The supplied refresh path is for season-end 2027. A later season requires an
explicit reviewed completed-season base-history rollover; it is not automatically
certified by this deployment. Score/date features do not require team boxes.

Responsible owner: Model Studio NBA source admission. `capture_nba_slate_refresh.py`
defaults to a no-network plan and is NOT called by the publisher launcher. Live
execution additionally requires `--execute`, a hash-pinned James authorization,
validity interval, exact plan and retained rights evidence. No such grant is
created in this task. Future scheduling of capture is a separately authorized
pre-publication phase of the same canonical NBA owner, not a second Windows task.

Proposed source: the already reviewed CC BY 4.0 SportsDataverse/hoopR ESPN-derived
`nba_schedule_2027.parquet` season release. One GET per capture; up to three
allowlisted HTTPS redirects; zero retries; at least 60 minutes between attempts;
24 capture attempts / UTC day; 16 MiB body/capture, 384 MiB/day, 5 GiB private
retained store. Failed attempts count. Stop on refusal, schema drift, rights
change, identity failure or quota. Retained reference sizes are 86,466 bytes for
the early 2027 schedule and 525,802 bytes for the completed 2026 schedule; the
future response size is unknown. Cost $0, no credentials, NBA.com or sportsbook
calls. These are proposed limits, not new acquisition authority or a reset of
earlier allowances. Preserve attribution and changes disclosure from the
original source-rights receipt. Never delete old objects to evade the storage cap.

After permitted capture, the operator reviews its status/schema and runs local
admission. The runtime input pointer then sees the new version on its next tick.
Missing or delayed source finals fail closed as incomplete membership. No new
HTTP Last-Modified timestamp is invented; receipts preserve allowed headers,
actual retrieval, source bytes, schema fingerprint and corrections separately.

## Package discovery and clocks

The selected model handoff remains immutable. The slate release binds it plus
the new executable manifest and input policy. No historical artifact is promoted.

The additive `NBA_GEN1_PRODUCTION_FORECAST_PACKAGE_INDEX_V2` retains the prior
forecast schema, full population and probability fields. Its **publishedAtUtc is
null while prepared**. Consumers must use the bound immutable publication receipt's
`committedAtUtc` as the conservative first confirmed availability. This is essential
for interruption recovery: preparation is not evidence of exchange publication.
The publication receipt is copied into the exchange, not left solely in private
runtime storage. Its digest is bound by discovery. Both creation and confirmed
publication must precede the consumer's applicable deadline; no timestamp restamp
or historical reclassification is allowed.

`slate-discovery/current.json` atomically points to a content-addressed, immutable
discovery version. Versions retain their predecessor, all revisions, per-game
dispositions, preserved earlier packages and consumerAcknowledged=false. Only a
matching current revision with `currentlyEligible=true` and an unexpired
`eligibilityValidUntilUtc` can be considered eligible. `preservedEarlierPackages`
never implies current eligibility. The eligibility lease lasts at most one
15-minute tick, and is shortened by source expiry or the publication cutoff;
consumer caches must fail closed when it expires even if a later tick fails.
The old one-game discovery file is untouched.
This additive discovery/clock contract needs Claude's explicit import support;
package preparation or this handoff does not activate AISP.

## Failure and recovery

The OS-held single-owner lock has no stale-PID deletion loophole and releases on
process exit. Each game is isolated: a failed game is recorded, successful games
remain committed, and discovery includes the coverage gap. Prepared transaction
records survive an interruption before or after atomic package publication;
recovery verifies the exact bytes and does not resimulate a completed transaction.
If the game is no longer eligible, recovery leaves it historical/unpublished.

Runner start, per-game and completion receipts are durable and append-only.
PowerShell 5.1 writes an independent launcher start/final receipt, stdout/stderr,
Python exit and wrapper exit. Missing final receipts mean interruption, not
success. Runtime 12-minute task limit may interrupt a large slate; already committed
games survive and the next natural tick resumes pending eligible transactions.
No broad test suite, model search, provider collection or other sport owner is
part of this release.
