# Timing and revision audit

The retained Foundation is a **current finalized snapshot**, not an archive of every historical release. Injury `date_modified` is useful row metadata: 75,383 of 84,684 retained rows match a unique team-week kickoff and carry an earlier modification time, while 26 are at or after kickoff. This does not prove which physical bytes were available at a historical cutoff because later corrections can be present in the downloaded 2026 snapshot.

Weekly rosters have season/week and IDs but no retained row publication time. Depth charts have a date field, but the upstream source and conventions changed and no append-only historical revision chain is retained. Snap counts, participation, and player-game statistics are postgame. They are prohibited for the target game and may be used only after a conservative prior-game availability boundary.

The nflverse release tag creation time is not the publication time of each later-mutated season asset. `assetUpdatedAt` and the local 2026 retrieval time describe the artifact now; neither reconstructs the bytes that existed before an old kickoff. The open nflverse issue #102 asks this exact roster-vintage question and has no authoritative answer as of this audit.

Accordingly, no 2023–2024 outcome assessment was opened. The evidence gate failed before outcomes.
