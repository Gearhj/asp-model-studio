# Claude / AISP handoff

Model Studio disposition: `NFL_M1_PRODUCTION_READY_AWAITING_EXPLICIT_ACTIVATION`.

Pin these exact bytes in AISP's supported settings:

- `NFL_PRODUCTION_HANDOFF_PATH=C:\Users\james\asp-model-exchange\nfl-m1-production-v1\handoffs\sha256\29d00078f389608ccd5a5e1db3db89b8594e45c7e7a9892f2d54e26f38557279\handoff.json`
- `NFL_PRODUCTION_HANDOFF_SHA256=29d00078f389608ccd5a5e1db3db89b8594e45c7e7a9892f2d54e26f38557279`

The handoff names immutable discovery:

- relative path `nfl-m1-production-v1/discovery/sha256/6341df1c144cca3c9bc637c9ff43546b5b8f789924e9ada9560d70beed51c46f/discovery-index.json`
- SHA-256 `6341df1c144cca3c9bc637c9ff43546b5b8f789924e9ada9560d70beed51c46f`
- physical bytes 191,852

The handoff is 87,182 bytes, canonical UTF-8 JSON, and was accepted by the exact live adapter with `production_label_allowed=true`. It takes effect at 2026-09-20T17:00:00Z. DET at BUF on September 17 remains research-shadow and must not be relabelled.

Consumer action:

1. Set the two supported pins in AISP's runtime configuration without changing decision or settlement policy.
2. Reload the existing `ASP Backend 8010` task; do not create another owner.
3. Require `GET /api/v1/research/nfl-production-status` to return `NFL_M1_PRODUCTION_BASELINE_PROSPECTIVE_MONITORING`, accepted true, the exact handoff SHA and production-label allowed true.
4. Check Week 2 scoring readiness. Sunday/Monday games at or after the effective time should show the exact governing forecast; DET-BUF should remain before-effective/research.
5. Observe the next natural existing forecast/import invocation. Verify its model/configuration/artifact, package hash, independently reconstructed population hash, 10,000 draws and pre-kickoff publication. No manual competing producer is needed.

No AISP acknowledgement exists yet. Publication alone is not consumer activation.

