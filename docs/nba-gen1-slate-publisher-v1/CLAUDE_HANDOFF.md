# Claude/AISP — NBA slate publisher successor

Producer implementation is staged, NOT installed. NBA consumer is NOT activated.
This handoff grants no decision, position, wagering or model-promotion authority.
Deployment `0aa50236f9dcac875106c13c6749e025126370e700a4467915275251ad583a88`; physical manifest SHA `4454b2e4cd0981e9d98bb900972459d54117ca72919867375e5c0d0b089a7573`.
Release `C:\Users\james\asp-model-studio\outputs\nba-gen1-slate-publisher-v1\release-final\releases\sha256\c123faf6e48fc2db7f60729671e13c320d2ec1cd86944d603fac9f0e136a2dd9\release.json` with SHA `c123faf6e48fc2db7f60729671e13c320d2ec1cd86944d603fac9f0e136a2dd9`.
Prospective effective boundary: `2026-09-18T13:07:50.312471+00:00`.

Validate index bytes and every bound member. Retain the selected underlying
model handoff `7113b71ff5819c89103ad19d5f9afb22c51dbc92980be12b56ce8826cb34ccaf`.
Do not replace or relabel its original PHI–NYK or the earlier BOS–DET research
forecasts. A future new BOS–DET package has its own forecast/revision identity.

The V2 package retains explicit Ridge point expectations, Elo winner probabilities,
and 10,000 paired joint score draws. Elo is the controlling winner channel; joint
winner probabilities are a separate summary, while totals/intervals use the full
joint population. Close-score correction is disabled. Probability units are 0–1.

Required additive import changes, pending your own implementation/verification:

1. Follow `nba-gen1-production-v1/slate-discovery/current.json` to its physically
   hashed immutable version. Preserve all packages/revisions. Do not scan unrelated
   research artifacts or treat preserved historical entries as current.
2. Support `NBA_GEN1_PRODUCTION_FORECAST_PACKAGE_INDEX_V2`. Package/forecast
   publishedAtUtc remains null in prepared bytes. Actual confirmed publication is
   the bound exchange publicationReceipt's committedAtUtc. Verify its hash and
   exact package, forecast and revision binding. Never substitute creation time.
3. Require current eligibility and an unexpired eligibilityValidUntilUtc (maximum
   one 15-minute tick), source/model bindings, pre-tipoff creation/publication, and
   your independently governed decision cutoff. A producer cutoff is not a wager
   deadline. Verify the forecast population and point/Elo/joint channel orientation.
4. Import idempotently by forecast ID plus physical package digest, retain old
   revisions, and keep research history before the effective boundary unchanged.
5. Obtain separate AISP activation authority and supply an actual consumer receipt.
   Do not assume that existing AISP pin handling implements these additive fields.

No real packages were issued this task: all 1197 supported
retained games are outside T−7 days and the inputs need refresh. Earliest checkpoint
is 2026-10-13T19:00:00+00:00, subject to fresh evidence. The only discovered predecessor
PHI–NYK package is preserved as historical, not recertified as currently eligible.
There is no consumer acknowledgement. ACTIVATE.md is not required: use the exact
supported commands in ACTIVATION.md after authorization. No second scheduler.
