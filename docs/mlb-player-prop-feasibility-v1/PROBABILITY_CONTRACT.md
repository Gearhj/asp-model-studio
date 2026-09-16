# Proposed pure player-prop probability contract

**Current availability: blocked.** This contract becomes executable only after an identity-preserving per-draw sidecar passes forecast invariance and player/team reconciliation. It must not be applied to current score populations or team aggregates.

## Input

- Exact canonical game, MLBAM gamePk, forecast, package, model/configuration and player-count-population identities.
- Canonical player ID and MLBAM player ID; team side; `BATTER` or `STARTING_PITCHER` role; batting slot when applicable.
- One prop type: `BATTER_HITS`, `BATTER_TOTAL_BASES`, `BATTER_HOME_RUNS`, or `STARTING_PITCHER_STRIKEOUTS`.
- Exact nonnegative integer or half-unit line and `OVER`, `UNDER` or threshold/yes-no orientation.
- Verified full per-draw integer statistic from the original correlated population.
- Exact lineup, starter and source cutoffs; explicit quote/house-rule compatibility supplied outside the pure calculator.

## Output

```json
{
  "schemaVersion": "MLB_V18_PLAYER_PROP_PROBABILITY_RESPONSE_V1",
  "status": "SUPPORTED_CONDITIONAL_RESEARCH",
  "identity": {
    "canonicalGameId": "...", "mlbamGamePk": "...",
    "canonicalPlayerId": "...", "mlbamPlayerId": "...",
    "forecastId": "...", "forecastObjectSha256": "...",
    "modelId": "MLB_V18_HGB_PA", "packageSha256": "...",
    "populationSha256": "..."
  },
  "market": {"propType": "BATTER_HITS", "side": "OVER", "line": 0.5},
  "mass": {
    "units": "FRACTION_0_TO_1",
    "pWin": 0.0, "pPush": 0.0, "pLoss": 0.0,
    "pVoid": null, "voidStatus": "UNSUPPORTED"
  },
  "counts": {"drawCount": 5000, "win": 0, "push": 0, "loss": 0},
  "monteCarlo": {"winIndicatorStandardError": 0.0},
  "cutoffs": {"sourceCutoff": "...", "lineupAvailableAt": "...", "starterAvailableAt": "..."},
  "conditions": ["FROZEN_PLAYER_STARTS", "GAME_GRADED_UNDER_COMPATIBLE_RULES"],
  "authority": "RESEARCH_ONLY_NO_WAGERING_OR_FINAL_PREGAME_AUTHORITY"
}
```

Win, push and loss counts must sum to draw count, and their conditional probabilities must sum to one. `pVoid` remains null until a supported participation/void model exists. A caller demanding unconditional win/push/loss/void mass receives `UNSUPPORTED_VOID_MODEL`; the calculator must not renormalize or substitute zero.

MCSE is `sqrt(pWin*(1-pWin)/drawCount)` for simulation sampling precision. It is not uncertainty about the model, participants or inputs. The contract performs no I/O, quote retrieval, fair-price/edge calculation, eligibility, decision or staking.

## Fail-closed errors

- `NAMED_PLAYER_POPULATION_UNAVAILABLE`
- `FORECAST_OR_POPULATION_IDENTITY_MISMATCH`
- `DRAW_COUNT_OR_MASS_MISMATCH`
- `PARTICIPANT_REVISION_MISMATCH`
- `PLAYER_ROLE_OR_ORIENTATION_MISMATCH`
- `UNSUPPORTED_VOID_MODEL`
- `NAMED_RELIEVER_UNSUPPORTED`
- `INVALID_LINE_OR_PROP_TYPE`
