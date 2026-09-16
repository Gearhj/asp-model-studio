# Data and identity requirements

## Required binding for a future player-count population

1. Canonical game ID, MLBAM gamePk, away/home orientation, scheduled start and status revision.
2. Exact forecast ID, immutable object/package SHA-256, population identity, engine/configuration, PA and transition artifact hashes, draw count and seed policy.
3. Exact source cutoff, capture, forecast creation and sidecar creation clocks.
4. Canonical player ID, MLBAM player ID, display name, team, side, batting slot or starting-pitcher role.
5. Confirmed ordered-lineup and starter evidence IDs, source/observed/available/ingested timestamps and hashes.
6. Per-draw integer player statistics from the same full simulation population: PA, H, 1B, 2B, 3B, HR, TB; starter BF and K.
7. Reconciliation: player class counts sum to team class counts; starter plus anonymous relief strikeouts sum to team batting strikeouts; draw count and every original score match.
8. Limitations: fixed lineup, no substitutions/scratch model, transparent starter hook, anonymous relief, conditional participation and research-only authority.

## Proposed research-sidecar identity

The sidecar must have its own content address and creation clock. It must reference, never replace, the parent forecast. A later lineup, starter or schedule revision requires a new forecast/sidecar pair. Reuse is allowed only when the original owner proves unchanged eligible evidence and the participant binding is byte-identical.

Suggested schema fields:

```json
{
  "schemaVersion": "MLB_V18_PLAYER_PROP_POPULATION_V1",
  "authority": "RESEARCH_ONLY_NO_DECISION_AUTHORITY",
  "game": {"canonicalGameId": "...", "mlbamGamePk": "..."},
  "forecastBinding": {
    "forecastId": "...", "forecastObjectSha256": "...",
    "modelId": "MLB_V18_HGB_PA", "populationSha256": "...",
    "drawCount": 5000, "seed": 20260908
  },
  "participantBinding": {
    "canonicalPlayerId": "...", "mlbamPlayerId": "...",
    "role": "BATTER", "side": "AWAY", "battingOrderPosition": 1,
    "lineupStatus": "CONFIRMED"
  },
  "counts": {"plateAppearances": [], "hits": [], "totalBases": [], "homeRuns": []},
  "voidModel": {"status": "UNSUPPORTED", "probability": null}
}
```

Arrays above are schematic; a compressed histogram is sufficient for one prop only if it is derived from and cryptographically bound to the exact full player-count vector. Retain the vector or a jointly sufficient per-draw representation when same-player or same-game intersections may later be required.

## Required pure query result after support exists

The query input must include the exact population binding, canonical player identity, prop type, side and integer/half-unit line. The result must return win/push/loss counts and probabilities, draw count, binomial MCSE for the requested win indicator, probability units `FRACTION_0_TO_1`, and the participant/source cutoffs.

`pVoid` must not be silently set to zero. Until a supported participation/void model exists, it is `null` and the conditional win/push/loss mass must be labeled conditional on the frozen player starting and the game being graded. A consumer requiring unconditional four-way mass must reject the result.
