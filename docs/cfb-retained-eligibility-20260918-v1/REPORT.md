# Retained CFB paper-window eligibility

The original lifecycle ended discovery eligibility at the T-30 publication
deadline. That prevented a separately authorized consumer decision window from
using an unchanged forecast during T-30 through T-15. The repair separates the
existing publication cutoff from revalidation of an already committed forecast.

`POLICY`, its revision-key contribution, prediction inputs and the numerical
release identity are unchanged. New rendering and publication still require a
time strictly before T-30. A final check also prevents a durable publication
commit whose recorded clock is at or after that cutoff.

Only an immutable `release.paperEligibilityAuthorization` reference with the
expected virtual-only schema, James authorization, frozen CFB model, exact
refresh-plan binding and active period enables the additional retained path.
Absent or expired authorization preserves the original T-30 behavior. Invalid
or physically altered authorization fails closed. No real-money or model
promotion authority is added.

Before any reuse lookup, the owner still checks current scheduled status,
kickoff, scope, identity/input blockers, schedule/history freshness and complete
history. During T-30 through T-15, it then requires the exact committed revision,
matching game and forecast identities, verified package bytes and a publication
clock strictly before T-30. A missing or changed revision cannot be rendered,
recovered from preparation or published in that interval. Started or completed
games cannot receive renewed eligibility.

Authorized leases are limited by all of T-15, grant/plan expiry, the existing
15-minute cadence and source freshness. A pre-T-30 owner evaluation may therefore
issue an authorized lease crossing T-30, while preserving the original package
bytes and publication clock. Discovery explicitly labels this additional
eligibility `VIRTUAL_RESEARCH_ONLY` and binds its immutable authorization.

Focused verification: **42 tests passed** across the new retained-eligibility
tests and existing slate/recurring lifecycle tests. Cases include T-31, T-30,
T-29, T-16, T-15, kickoff, source-declared completion, stale inputs, missing
identity/history, grant expiry, changed revisions, absent commitment, exact
cutoff rejection, a render crossing the cutoff and unchanged numerical revision
identity. Tests are synthetic and make no provider requests or model fits.

Source base: `2463920170fa09244beaacfd4c391fbb9c218c48`; independent worktree and
branch `codex/cfb-retained-eligibility-20260918-v1`. This source change does not
install a deployment, invoke a live owner, acquire data or edit AISP. A reviewed
immutable operational successor must include it and the exact authorized grant.
