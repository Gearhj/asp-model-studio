# Claude / AISP handoff

Model Studio disposition: `NFL_M1_PRODUCTION_BASELINE_ACTIVATED`.

AISP has pinned these exact bytes in its supported settings:

- `NFL_PRODUCTION_HANDOFF_PATH=C:\Users\james\asp-model-exchange\nfl-m1-production-v1\handoffs\sha256\29d00078f389608ccd5a5e1db3db89b8594e45c7e7a9892f2d54e26f38557279\handoff.json`
- `NFL_PRODUCTION_HANDOFF_SHA256=29d00078f389608ccd5a5e1db3db89b8594e45c7e7a9892f2d54e26f38557279`

The handoff names immutable discovery:

- relative path `nfl-m1-production-v1/discovery/sha256/6341df1c144cca3c9bc637c9ff43546b5b8f789924e9ada9560d70beed51c46f/discovery-index.json`
- SHA-256 `6341df1c144cca3c9bc637c9ff43546b5b8f789924e9ada9560d70beed51c46f`
- physical bytes 191,852

The handoff is 87,182 bytes, canonical UTF-8 JSON, and was accepted by the exact live adapter with `production_label_allowed=true`. It takes effect at 2026-09-20T17:00:00Z. DET at BUF on September 17 remains research-shadow and must not be relabelled.

Activation verification:

1. The existing `ASP Backend 8010` owner was restarted once; no second owner was created.
2. Live status is `NFL_M1_PRODUCTION_BASELINE_PROSPECTIVE_MONITORING`, accepted true, with the exact handoff SHA and production-label allowed true.
3. Natural import job `72ebb57f-3905-4e57-a331-a3ed8c8eeaaa` succeeded after 97.115 seconds and reused the unchanged populations.
4. All 15 Sunday/Monday games are governed; DET-BUF remains before-effective/research.
5. Week 2 scoring readiness remains 16/16.

No further consumer activation action is required. Continue the 50-game first review and 100-game calibration review under the published monitoring contract.
