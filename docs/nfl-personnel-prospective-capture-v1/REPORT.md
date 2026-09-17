# NFL prospective personnel capture activation report

## Disposition

`IMPLEMENTED_AND_DEPLOYMENT_STAGED_INSTALLATION_BLOCKED_BY_AUTOMATIC_APPROVAL_REVIEW`

The data-only capture owner, immutable deployment builder, supported Plan/Install path, outcome-free projection, tests, and operator documentation are complete. The reviewed member bytes have deployment identity `cbf3686a0c8ceb22dd135b5af9f3fb4738a8114a2e7ac969712992292404d20d`. The builder records the final Git source commit as lineage without making documentation-only commits alter the content identity.

The predecessor deployment passed supported installer Plan mode. Automatic approval review rejected Install mode before it executed because the recurring S4U task can make durable external requests and the reviewer could not treat the attached work order as visible explicit authorization. No task, rights acknowledgement, runtime manifest, data root, provider request, or capture was created. This is an approval gate, not a runtime or code failure. Re-run Plan against the final deployment before installation.

## Sources and cadence

The live plan uses six free nflverse release assets: `injuries_2026.parquet`, `roster_weekly_2026.parquet`, `depth_charts_2026.parquet`, `snap_counts_2026.parquet`, `players.parquet`, and `draft_picks.parquet`. Schedules are not requested. The owner reads only eight identity/time columns from the registered local Foundation schedule object; score, result, total, overtime, market, weather, and schedule-QB columns are excluded.

Retained forward vintages show depth-chart and roster content changes observed on September 9, 12, 13, 15, 16, and 17. Upstream asset timestamps were generally morning UTC, with several 12:36–13:58Z updates. The staged schedule therefore uses one Monday/Tuesday capture and three Wednesday-through-Sunday capture windows at 07:15, 11:15, and 15:15 America/New_York. A 15-minute task tick merely gates those slots; all other invocations are zero-call `NOT_DUE` receipts. At six assets, the normal maximum is 18 calls/day, below the immutable 28-call ceiling.

## Evidence contract

Raw provider bytes are private, outside Git, content-addressed, append-only, and capped at 64 MiB/capture and 2 GiB retained. Transfers are streamed with a hard remaining-byte bound; staged bytes are reread and hashed before atomic move. ETag/Last-Modified validators are retained. A 304 reuses an exact predecessor; an unavailable 2026 asset is explicit and is not replaced with an older season.

The projection binds exact game, team, player, source, retrieval, and source-version identity. Depth rank 1 with a matching weekly roster row is `PROBABLE_FROM_CURRENT_DEPTH_CHART`; it is never called confirmed. Ambiguous and unavailable states remain explicit. `EARLY`, `CURRENT`, and `FINAL_PREGAME` use T-48h, T-6h, and T-15m evidence cutoffs. Late captures cannot backfill an earlier horizon.

Complete captured weeks are Development only. No outcome fields, model fitting, model scoring, forecast publication, AISP write, exchange write, decision, position, or promotion is authorized.

## Verification

- 14 focused tests passed.
- Python modules compiled.
- PowerShell installer/launcher parsed without errors.
- Installer Plan mode bound S4U, Limited, IgnoreNew, 15-minute tick, 15-minute runtime ceiling, and one owner marker.
- Post-rejection inspection found zero matching tasks, zero runtime manifest, zero rights acknowledgement, and zero data root.
- The existing MLB task still points to deployment `b8cae23dde745d0d5f5cf4d160b4970d2892c38b`.
- Provider calls: 0; provider bytes: 0; cost: $0; AISP writes: 0; exchange writes: 0; outcome reads: 0.

## Remaining activation step

The owner must repeat the supported Install command after explicit authorization is supplied in a visible user message. Then run one bounded `--initial-authorized` capture and observe the next natural scheduled tick. Installation success requires exactly one owner, matching task/runtime deployment IDs, S4U/Limited/IgnoreNew, and launcher exit code 0. Capture success additionally requires a content receipt, projection receipt, and unchanged MLB/forecast-owner state.

## Post-install correction

After visible authorization, Windows installed deployment `cbf3686a0c8ceb22dd135b5af9f3fb4738a8114a2e7ac969712992292404d20d`. The initial capture and first natural invocation both failed before provider access because its isolated deployment copied the repository's broad `server.sports_nfl_m1` initializer, which imported omitted modeling modules. Provider calls and retained bytes remained zero. The task recorded `LastTaskResult=1`; no capture receipt was created.

The builder now maps a dedicated minimal package initializer into the isolated deployment. Fifteen focused tests pass, including an explicit mapping test. The corrected content identity is `3139cff08216d9e16fcaa5d012a23738605e14f66c3fffc4687f73ecda7f7dcf`. Replacing the installed exact deployment requires separate visible authorization; the current task must not be silently rebound.
