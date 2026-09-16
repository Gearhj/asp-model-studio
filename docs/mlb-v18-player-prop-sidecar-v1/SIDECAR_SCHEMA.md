# `ASP_MLB_V18_PLAYER_PROP_POPULATION_V1`

The sidecar is canonical UTF-8 JSON (`ensure_ascii=false`, finite numbers only, sorted keys, compact separators). Its SHA-256 is over the complete physical bytes and names its local research object directory.

## Top-level fields

| Field | Meaning |
|---|---|
| `schemaVersion` | Exact schema identifier. |
| `createdAt` | Actual sidecar creation time, separate from forecast clocks. |
| `binding` | Game, forecast object, paired population, model, transition, seed, clocks, starters and lineup revisions. |
| `batters` | 18 canonical participants, ordered by side and frozen batting slot. |
| `startingPitchers` | Two canonical named starters. |
| `anonymousReliefSummary` | Team-level anonymous relief BF/K arrays, retained solely for isolation/reconciliation. |
| `accounting` | Per-draw and aggregate reconciliation results. |
| `definitions`, `limitations`, `authority` | Semantics and research-only restrictions. |

Each statistic is a deterministic zlib-compressed, base64-encoded little-endian unsigned 16-bit vector. The record retains the element count and SHA-256 of the uncompressed bytes. Decoding rejects a length or digest mismatch.

Batters retain `PA`, `SINGLE`, `DOUBLE`, `TRIPLE`, `HOME_RUN`, `HITS`, and `TOTAL_BASES`. Starting pitchers retain `BATTERS_FACED` and `STRIKEOUTS`. All vectors have exactly the forecast draw count.

Canonical identity is `playerId`; `mlbamId`, `teamId`, side, slot, display name and the model-template player identity are bound metadata. Display names never join records.

The sidecar is additive and local. It is not an exchange package, discovery object, forecast revision or consumer contract.
