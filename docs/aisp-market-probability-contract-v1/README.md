# AISP market probability producer contract v1

This contract gives AISP a side-effect-free way to ask what an already-published, immutable paired final-score population implies for a moneyline, spread, total, or same-game combination. It does not fetch sportsbook lines, run a model, create a forecast, decide whether a quote is timely, select a side, calculate an edge, determine eligibility, or size a position.

The implementation is `server/sports_shared/market_probabilities.py`. Inputs are exact game/forecast/model/configuration/package identities plus a count-weighted joint score population. The population is canonicalized as ordered `{awayScore,homeScore,count}` cells and hashed before use. Its counts must equal the declared draw count. Probability units are always fractions from 0 to 1.

## Supported calculations

Moneyline returns home, away, or tie settlement mass. A HOME or AWAY moneyline requires the caller to state whether a tied modeled final is a `PUSH`, `LOSS`, or `VOID`. This is essential for NFL, whose retained discrete population contains tie mass. NBA, CFB, and MLB admitted final populations have declared tie-free treatments, but the same reconciliation remains enforced.

Spread uses the selected team’s signed line:

```text
HOME -1.5 wins when homeScore + (-1.5) > awayScore
AWAY +1.5 wins when awayScore + (+1.5) > homeScore
```

Total uses the original paired final scores:

```text
OVER L wins when awayScore + homeScore > L
UNDER L wins when awayScore + homeScore < L
integer equality is PUSH; half-point lines have no push for integer scores
```

Same-game joint probability is computed inside each retained score cell. It is never the product of leg marginals. A loss dominates; otherwise all wins produce `WIN`, any void produces `VOID`, and remaining non-wins produce `PUSH`. That is a raw outcome-state breakdown. AISP remains responsible for a sportsbook’s specific reduced-leg parlay settlement.

Cross-game combinations fail closed because no retained cross-game joint population exists. An explicit `allow_independence_assumption=True` call produces a separately labeled `INDEPENDENCE_ASSUMPTION` convolution. It is approximate research output with no effective draw count or Monte Carlo standard error.

## Fair-price components

The library returns the probability terms and the push-aware fair decimal price:

```text
1 + pLoss / pWin
```

Push and void mass are treated as refunded. If `pWin=0`, the fair decimal result is null. This is not a quote comparison, an edge, a recommendation, or a decision.

## Integrity and freshness

The query result binds the exact sport, game, forecast, model, configuration, package SHA-256, canonical population SHA-256, and draw count. An adapter must verify the immutable source package before constructing `JointScorePopulation`; this pure library intentionally does not access files or networks. A later forecast revision requires a new binding and must not overwrite the previous result.

Freshness and authority inherit from the bound forecast. A mathematically valid query can still be stale, research-only, outside a consumer window, missing an eligibility supplement, or otherwise unusable for a decision. AISP owns those gates.

## Use

```python
from server.sports_shared.market_probabilities import (
    JointScorePopulation,
    evaluate_market,
    evaluate_same_game_joint,
)

population = JointScorePopulation.from_cells(
    sport="NFL",
    game_id=event_id,
    forecast_id=forecast_id,
    model_id=model_id,
    configuration_id=configuration_id,
    package_sha256=verified_package_sha256,
    cells=verified_joint_score_cells,
    draw_count=verified_draw_count,
    expected_population_sha256=verified_population_sha256,
)

total = evaluate_market(population, {
    "market": "TOTAL", "selection": "OVER", "line": 47.5,
})

same_game = evaluate_same_game_joint(population, [
    {"market": "MONEYLINE", "selection": "HOME", "tieSettlement": "PUSH"},
    {"market": "TOTAL", "selection": "OVER", "line": 47.5},
])
```

## Verification

```powershell
$python = 'C:\Users\james\asp-model-studio\.venv\Scripts\python.exe'
& $python -B -m pytest tests/test_market_probabilities.py -q -p no:cacheprovider
& $python -B scripts/verify_market_probability_contract.py
```

The fixture is synthetic. These commands perform no provider calls, model runs, exchange publications, scheduler actions, or AISP writes.
