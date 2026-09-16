# Stable error vocabulary

| Code | Meaning |
|---|---|
| `SPORT_UNSUPPORTED` | Sport is outside MLB, NFL, NBA, and CFB. |
| `IDENTITY_INCOMPLETE` / `IDENTITY_INVALID` | Required forecast or physical identity is absent or malformed. |
| `PAIRED_POPULATION_UNAVAILABLE` | The source is point-only or has zero draws. |
| `INVALID_SCORE_POPULATION` | Scores/counts are negative, fractional, empty, or otherwise invalid. |
| `DUPLICATE_SCORE_CELL` | Joint support contains the same away/home cell twice. |
| `DRAW_COUNT_MISMATCH` | Cell counts do not equal the declared population count. |
| `POPULATION_HASH_MISMATCH` | Canonical score-population SHA-256 differs from the expected binding. |
| `LEG_INVALID` / `MARKET_UNSUPPORTED` / `SELECTION_INVALID` | Market request is malformed or unsupported. |
| `TIE_SETTLEMENT_REQUIRED` | A two-way moneyline omitted tie treatment. |
| `JOINT_REQUIRES_MULTIPLE_LEGS` | Same-game joint request contains fewer than two legs. |
| `CROSS_GAME_JOINT_UNSUPPORTED` | No cross-game population exists and independence mode was not explicitly enabled. |
| `CROSS_GAME_IDENTITY_INVALID` | Cross-game inputs repeat or omit game identities. |
| `CROSS_GAME_INPUT_INVALID` | A marginal result lacks full win/loss/push/void mass. |
| `PROBABILITY_MASS_MISMATCH` | Calculated state mass does not reconcile to one. |

Adapters may return structured `UNSUPPORTED` responses for unavailable populations, but must not turn identity, hash, or count errors into approximate results.
