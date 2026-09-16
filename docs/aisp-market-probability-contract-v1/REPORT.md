# Multisport producer probability contract v1

**IMPLEMENTED_FOR_PAIRED_POPULATIONS.** The new pure library answers moneyline, spread, total, and same-game joint questions by exact enumeration of an immutable paired final-score population. It carries forecast/model/package/population identities, returns win/loss/push/void mass, an effective draw count, win-probability MCSE, and push-aware fair-price components. It contains no sportsbook, quote, edge, eligibility, decision, stake, database, exchange, model-run, or scheduler logic.

Work began from clean reviewed base `a7ee3d40283fa735f0ae25c790895378954bfa6d`, the current four-sport Scotty readiness branch that descends from `codex/source-development-v1`. The MMA feasibility and no-network harness branches are siblings and remain unchanged.

## Sport dispositions

| Sport | Moneyline | Spread / total | Same-game joint | Cross-game | Verdict |
|---|---|---|---|---|---|
| MLB unrestricted V18 | Direct | Derivable from 5,000 paired finals | Supported by per-cell intersection | Unsupported | Operational math when the exact controlling forecast population is bound. |
| NFL M1 | Direct three-way | Derivable from 10,000 paired finals | Supported | Unsupported | Operational math with explicit tie settlement and retained tie-model limitation. |
| NBA joint baseline | Direct joint channel | Derivable from 10,000 paired finals | Supported | Unsupported | Research-only. Joint winner stays separate from Elo. |
| NBA point/Elo | Elo winner only | Unsupported | Unsupported | Unsupported | `drawCount=0`; means cannot answer totals or spreads. |
| CFB baseline | Direct joint channel | Derivable from 10,000 paired finals | Supported | Unsupported | Research-only; calibrated-margin, Elo and joint channels remain distinct. |

No cross-game joint population exists for any sport. The default is fail-closed. A caller can deliberately request a labeled `INDEPENDENCE_ASSUMPTION` convolution for research display; the result has no empirical draw count or MCSE and cannot be represented as a model-derived parlay probability.

## Actual retained-source audit

One immutable population per sport was read and reconciled without accessing outcomes: MLB object `2f07648c…bdac` (5,000), NFL IND–KC package `5c459282…f117` (10,000), NBA joint package `00cd4990…97a9d` (10,000), and CFB package `223bbc35…ff76` (10,000). Cell counts, published winner mass, and declared tie behavior reconciled. Canonical population hashes and physical member hashes are retained in `source-validation.json`.

This confirms package compatibility, not forecast accuracy, freshness, market eligibility, consumer import, or decision authority. No Final OOT, result, or sealed evidence was opened.

## Numerical semantics

Spread lines attach to the selected team. Total lines compare against `awayScore + homeScore`. Integer equality is a push. HOME/AWAY moneyline queries require an explicit tie settlement. Same-game joint outcomes are intersected inside each paired score cell; they are not products of marginal probabilities.

The synthetic eight-draw golden vector proves integer pushes, half-point no-push behavior, spread signs, and correlation. HOME moneyline win mass is `3/8`; OVER 2.5 win mass is `5/8`; their naive product is `15/64`, while the actual joint win mass is `2/8`.

## Verification and accounting

Focused test result: 9 passed. The deterministic verifier reconciles three golden vectors. The retained-source audit reconciles all four sport populations. The core module imports no network, subprocess, database, filesystem, provider, or sportsbook client and performs no I/O.

Provider calls/bytes/cost: **0 / 0 / $0**. Model fits/runs, forecast changes, exchange writes, AISP writes, outcome reads, sealed reads, scheduler changes, and deployments: **0**. Existing models, forecasts, packages, discovery pointers, deployments, and owners are unchanged.

The consumer must add a sport-specific verified-population adapter, bind the exact current forecast revision, pass explicit market orientation and settlement rules, and retain all existing freshness, experiment, quote, decision, and stake gates. No consumer acknowledgement exists for this source-only handoff.
