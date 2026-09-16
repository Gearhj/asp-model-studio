# CLAUDE_HANDOFF — MLB roster freshness repair

Published: 2026-09-15T02:07:27.830940+00:00

Classification: producer deployment update and consumer source-owner change request.

ATL@CHC missed because the September 14 AISP daily source job timed out on the Cubs team-stat request. Team-stat, roster, and bullpen work shared one team-level try block, so the Cubs roster endpoint was never called. The last roster remained the September 13 capture and crossed the 30-hour gate before T-60. Starters and both confirmed lineups were available before T-15; no forecast was created or published.

The Model Studio visibility and immutable-forecast metadata repair is committed and built, but it is not active. Windows denied administrator-required re-registration of the existing S4U task. The existing 4757da task and manifest remain paired, and the consumer-engaged STOP sentinel remains in place because the successor has not passed a natural S4U invocation.

Claude action: change the existing AISP source owner so an unrelated team-stat failure cannot suppress roster acquisition. The existing availability poll should make a deduplicated, bounded active-roster refresh for only teams whose roster will exceed 30 hours by T-15: one attempt by T-60 and at most one retry before T-45. Retain raw bytes and the existing ingestion lineage. Do not create a scheduler or weaken the freshness gate.

Administrator action: re-register the same task against the immutable 0a2fb828 deployment, then allow one natural S4U invocation to succeed before removing the STOP sentinel.

```powershell
.\scripts\install_mlb_v18_unattended.ps1 -Mode Install -CodeRoot .\.deployments\mlb-v18-unattended\0a2fb8282d68d1a06ac478e5cf3e3442dafe09d8
```

Read `roster-freshness-repair.json` for all ten September 14 ages, the 15-game next-slate inventory, source receipts, readiness enum contract, and physical evidence bindings.

Package identity uses `ASP_FILENAME_TO_SHA256_MAP_CANONICAL_JSON_UTF8_V1`: normalized POSIX member filenames map to raw-byte SHA-256 values, encoded as canonical UTF-8 JSON with ensure_ascii=false, allow_nan=false, sorted keys, and compact separators. Member sizes, the manifest, receipt, and identity field itself are excluded. The old ced67 package reproduces.

Publication does not establish AISP acknowledgement or activate either requested change.
