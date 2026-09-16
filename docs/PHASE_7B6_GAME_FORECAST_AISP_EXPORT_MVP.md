# Phase 7B6 — Game Forecast and AISP Export MVP

Status: **COMPLETE**

## Scope and scientific boundary

- Branch: `codex/game-simulation-market-mvp`
- Base HEAD: `edeb9e964e11adf91ad51f55582304c776cd07b0`
- Bronze, Silver, and Gold were not rebuilt.
- No PA model was fit. No model was promoted.
- No 2025 or 2026 data was used.
- Nothing was pushed and no remote was modified.
- `C:\Users\james\ai-sports-predictor` was not modified.

E10 was meta-fit on the combined five-fold OOF predictions and labels. Its Fold 1–5 results therefore are **not** strictly out-of-fold and are intentionally neither generated nor reported as OOF. Direct Gold alone receives the five-fold OOF evaluation. Direct Gold and E10 are compared only on the untouched final holdout: **13,766 PAs, 183 games, 2024-09-16 through 2024-09-29**.

## Governed population

| Cohort | PA rows | Games | Direct Gold status | E10 status |
|---|---:|---:|---|---|
| Fold 1 | 105,063 | 1,403 | Strictly OOF | Not reported |
| Fold 2 | 105,289 | 1,406 | Strictly OOF | Not reported |
| Fold 3 | 104,339 | 1,382 | Strictly OOF | Not reported |
| Fold 4 | 105,172 | 1,393 | Strictly OOF | Not reported |
| Fold 5 | 104,662 | 1,396 | Strictly OOF | Not reported |
| Final holdout | 13,766 | 183 | Untouched holdout | Untouched holdout |

The persisted ledger contains 7,346 candidate-game records: 6,980 Direct Gold fold records, 183 Direct Gold holdout records, and 183 E10 holdout records. There are no E10 Fold 1–5 records.

## Direct Gold — six-cohort game evaluation

Calibration is the persisted `FIXED_10_EQUAL_WIDTH_HOME_WIN_BINS` reliability table; ECE below is its weighted absolute calibration error.

| Cohort | ML log loss | Brier | ECE | Winner acc. | Away-run MAE | Home-run MAE | Mean team-run MAE | Total-run MAE | Run-diff MAE | Max stability Δp |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Fold 1 | 0.681885056 | 0.244114307 | 0.031622951 | 0.561653599 | 2.601191019 | 2.578099786 | 2.589645403 | 3.812874555 | 3.399513186 | 0.146000000 |
| Fold 2 | 0.667946881 | 0.237605116 | 0.014354908 | 0.591038407 | 2.443532006 | 2.331080370 | 2.387306188 | 3.474589616 | 3.333936700 | 0.152000000 |
| Fold 3 | 0.687341070 | 0.247125143 | 0.037473951 | 0.547033285 | 2.473291606 | 2.426301013 | 2.449796310 | 3.653879161 | 3.377149783 | 0.145000000 |
| Fold 4 | 0.693832284 | 0.250025689 | 0.046912419 | 0.552045944 | 2.524525485 | 2.419221823 | 2.471873654 | 3.497613783 | 3.513511845 | 0.160000000 |
| Fold 5 | 0.682418537 | 0.244649806 | 0.018980659 | 0.565186246 | 2.457300143 | 2.388184097 | 2.422742120 | 3.446713467 | 3.423431232 | 0.158000000 |
| Holdout | 0.689884465 | 0.248563219 | 0.090562842 | 0.524590164 | 2.524896175 | 2.333142077 | 2.429019126 | 3.315174863 | 3.515622951 | 0.122000000 |

Five-fold Direct Gold OOF aggregate over 6,980 games:

- moneyline log loss `0.6826487185617438`;
- Brier `0.2446861070200573`;
- ECE `0.02323510028653299`;
- winner accuracy `0.5634670487106017`;
- mean team-run / total-run / run-difference MAE `2.4643139684813757 / 3.5771038681948424 / 3.409410458452722`.

Direct Gold over all 7,163 strictly out-of-sample games:

- moneyline log loss `0.6828335770917282`;
- Brier `0.24478515929079994`;
- ECE `0.024348178137651874`;
- winner accuracy `0.5624738238168365`;
- mean team-run / total-run / run-difference MAE `2.463412257434036 / 3.5704121178277255 / 3.412123970403462`.

### First-five Direct Gold evaluation

The first-five outcome is evaluated as a three-way away/home/tie distribution. Four historical games lacked governed first-five truth; they remain explicitly unavailable rather than being fabricated. Coverage is 7,159 of 7,163 games overall and 183 of 183 on the final holdout.

| Cohort | Coverage | 3-way log loss | Summed Brier | Winner/tie acc. | Mean team-run MAE | Total-run MAE | Run-diff MAE |
|---|---:|---:|---:|---:|---:|---:|---:|
| Fold 1 | 1.000000000 | 1.036489138 | 0.624900852 | 0.468282252 | 1.911181753 | 2.759750535 | 2.541357092 |
| Fold 2 | 0.997866287 | 1.009214632 | 0.608633631 | 0.492516037 | 1.791234498 | 2.628926586 | 2.402607270 |
| Fold 3 | 1.000000000 | 1.009925389 | 0.612498061 | 0.468162084 | 1.865097323 | 2.758559334 | 2.548083213 |
| Fold 4 | 0.999282125 | 0.989996298 | 0.602830999 | 0.483477011 | 1.849916667 | 2.584847701 | 2.588567529 |
| Fold 5 | 1.000000000 | 0.986039878 | 0.597779146 | 0.492836676 | 1.804592049 | 2.562019341 | 2.543450573 |
| Holdout | 1.000000000 | 1.031893013 | 0.628019902 | 0.415300546 | 1.802177596 | 2.630683060 | 2.433524590 |

Five-fold Direct OOF aggregate first-five results: coverage `0.9994269340974212`, three-way log loss `1.0063683762746003`, summed Brier `0.6093408311353211`, winner/tie accuracy `0.48107798165137616`, and mean team-run / total-run / run-difference MAE `1.8443734231651374 / 2.6587342316513762 / 2.524623853211009`.

## E10 versus Direct Gold — untouched holdout only

| Engine | ML log loss | Brier | ECE | Winner acc. | Away-run MAE | Home-run MAE | Mean team-run MAE | Total-run MAE | Run-diff MAE |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Direct Gold | 0.689884465 | 0.248563219 | 0.090562842 | 0.524590164 | 2.524896175 | 2.333142077 | 2.429019126 | 3.315174863 | 3.515622951 |
| E10 | 0.681377167 | 0.244498989 | 0.084092896 | 0.524590164 | 2.496125683 | 2.283065574 | 2.389595628 | 3.260295082 | 3.477879781 |

| Engine | F5 coverage | F5 3-way log loss | F5 summed Brier | F5 winner/tie acc. | F5 mean team-run MAE | F5 total-run MAE | F5 run-diff MAE |
|---|---:|---:|---:|---:|---:|---:|---:|
| Direct Gold | 1.000000000 | 1.031893013 | 0.628019902 | 0.415300546 | 1.802177596 | 2.630683060 | 2.433524590 |
| E10 | 1.000000000 | 1.024197658 | 0.621558284 | 0.420765027 | 1.768439891 | 2.597601093 | 2.412289617 |

E10 is numerically better on holdout moneyline log loss by `-0.008507298304209529` (E10 minus Direct). The fixed-seed, 2,000-iteration paired whole-game bootstrap 95% interval is `[-0.02507892029935546, 0.007551198071710137]`. It includes zero.

**GAME_ENGINE_COMPARISON_INCONCLUSIVE**

Both Direct Gold and the frozen E10 reliability-gated ensemble remain authorized only as future `RESEARCH_SHADOW` forecast sources. Neither is selected or promoted.

## Simulator output and integrity

Every persisted game-engine record contains:

- away/home win probabilities and expected runs;
- away/home team-run distributions;
- joint score distribution;
- home-minus-away run-difference distribution;
- total-runs distribution;
- first-five away/home/tie probabilities;
- first-five score, team-run, run-difference, and total distributions;
- empirical standard deviations, fixed quantiles, central 50/80/90/95% prediction intervals, and 100/250/500/1,000-draw stability checkpoints.

All 7,346 candidate-game simulations completed 1,000 of 1,000 draws with zero nontermination, zero illegal states, and zero probability-reconciliation failures. On the holdout, maximum/mean maximum home-win-probability drift versus the 1,000-draw result was `0.122 / 0.0420710383` for Direct Gold and `0.157 / 0.0434699454` for E10.

Inputs are pregame-only: the starting nine is cycled, the announced starter is held constant, and actual substitutions and actual reliever choices are never read. There were zero target-context or outcome reads and zero future player-feature or stance rows.

One governed Fold 5 batter had no Gold snapshot on or before 2024-08-07. That single role used the explicit `ROLE_COLD_START_NO_PRIOR_GOLD_SNAPSHOT` representation—training-fitted imputation plus missing/insufficient flags—with no same-day row, no future row, no other-player fallback, and no dropped game.

## AISP contracts

The implementation defines and strictly validates these sport-neutral versions:

- `AISP_GAME_FORECAST_EXPORT_V1`
- `AISP_MARKET_QUOTE_V1`
- `AISP_BET_CANDIDATE_V1`
- `AISP_DAILY_FORECAST_BUNDLE_V1`

The game export binds event/team identity, scheduled start and cutoff authority, engine and simulator identity, full-game and first-five forecasts/distributions, uncertainty, readiness and missing-input evidence, explanations, immutable forecast identity, and `RESEARCH_SHADOW` status. Unknown fields, inconsistent identities, executable status, promotion, parlays, invalid distributions, and post-2024 events fail closed.

## Historical odds and market pricing

**HISTORICAL_ODDS_INSUFFICIENT**

The governed input has zero persisted, timestamped, two-sided sportsbook quotes and zero covered games. No price, line, no-vig probability, edge, expected value, closing-line value, historical staking result, or ROI was fabricated or reported.

The forward SHADOW contract supports all required families:

- full-game moneyline;
- first-five moneyline;
- run line ±1.5;
- full-game total;
- first-five total;
- team total.

When a governed quote is present, the contract computes model probability, fair odds, break-even probability, proportional no-vig probability for complete two-sided prices, edge, expected value, and uncertainty-adjusted edge. Synthetic prices exist only in clearly labeled contract tests and are absent from the governed bundle.

## Research-only board and virtual staking

The persisted forward ledger contains 28 daily boards (14 dates × 2 engines), 366 candidate-game boards, and 2,562 market rows: seven rows per game because team total has separate home and away subjects. All 2,562 states are `NO_BET`; every virtual stake is zero; parlays and execution are disabled.

Concrete persisted example—Direct Gold, 2024-09-16, `game-333de160d3127f92b47ab749`:

- away/home win probabilities: `0.335 / 0.665`;
- expected away/home score: `3.232 / 4.676`;
- expected total and home-minus-away margin: `7.908 / 1.444`;
- first-five away/home/tie: `0.295 / 0.540 / 0.165`;
- full-game moneyline price, line, no-vig probability, edge, and EV: `null` because no governed quote exists;
- readiness: `NOT_READY`, with missing scheduled-start timestamp, forecast-cutoff timestamp, and governed two-sided quote;
- decision: `NO_BET`; virtual stake: `0.0`.

The virtual-only policy is quarter Kelly (`0.25`) with a `0.50%` normal unit, `1.00%` maximum position, `2.00%` maximum same-game exposure, and `5.00%` maximum daily exposure. The normal unit is not a forced minimum. In the example, Kelly is not calculated from a nonexistent price, and position, game, and daily exposure all remain zero.

## Immutable external AISP bundle

One content-addressed example was written to the sanctioned external exchange root only:

- object root: `C:\Users\james\asp-model-exchange\aisp-daily-forecast-bundles\sha256\784ccb36d14e4eb988c22b755d35ecee5e7d29f2f0fe1fa5fdd39c5a64d33ca4`
- logical URI: `asp-model-exchange://aisp-daily-forecast-bundles/sha256/784ccb36d14e4eb988c22b755d35ecee5e7d29f2f0fe1fa5fdd39c5a64d33ca4/bundle.json`
- bundle SHA-256: `784ccb36d14e4eb988c22b755d35ecee5e7d29f2f0fe1fa5fdd39c5a64d33ca4`
- immutable bundle ID: `aisp-daily-forecast-bundle:sha256:8603a53c6028987aa8476c7b00608110f7e7403705e136d50e6e59c22b98a76d`
- consumer fixture SHA-256: `4dacce1341cd3b45db4f038926694503db5a4c3cc0009122f6cc5a720f51e899`
- validation-instructions SHA-256: `3bf7e0480e71bb15b34e0d683bdc41001a701e542e0df3bb6f73b3a2c88700dc`

The exact three-file object is `bundle.json`, `consumer-import-fixture.json`, and `VALIDATION.md`. Independent production verification passed. The bundle contains two forecasts (Direct Gold and E10 for the same earliest holdout game), zero quotes, and zero bet candidates. Its status is `RESEARCH_SHADOW_NOT_READY`; execution, model promotion, and parlays are all false.

### AISP import instructions

1. Resolve the exact logical URI in `consumer-import-fixture.json`; never select a “latest” object.
2. SHA-256 `bundle.json` and require equality with both `bundleSha256` and the URI address.
3. Parse JSON with duplicate-key rejection and validate the four exact contract versions.
4. Require the declared child counts and verify every child content binding.
5. Reject unknown fields, post-2024 event data, parlays, executable records, model promotion, non-research status, or missing readiness evidence.
6. Treat the bundle as immutable research-shadow evidence only. It authorizes no wagering, provider call, model fit, or promotion.

The exact consumer next step is prospective, timestamped, two-sided sportsbook quote capture into the SHADOW ledger, followed by governed contract import in AISP. Qualification thresholds remain unset until a separate prospective policy is approved.

## Verification and immutable study identity

- Relevant bounded automated suite: **92 passed**.
- Final game-study cold-start delta: **8 passed**.
- Export example builder tests: **4 passed**.
- Final stance/future-row checks: **7 passed**.
- Independent study-source verification: passed over all 7,346 JSONL records.
- Independent AISP bundle verification: passed; regenerated Direct and E10 forecasts matched the bundle exactly.
- Governed study request/address SHA-256: `7f4bfc8da4ccb0f3bea0959481422a4104b5e882753ee868396086c20bc1165b`.
- Governed study manifest SHA-256: `ffde66fada1f9708e2c7dc2fb7885051c9f26fecbf4623e4ae1627ace981a499`.
- Governed study results SHA-256: `6578b7c39000b275a907960cc77b8ad4752201500ef6d3544ec50c9e6e529d82`.

## Limitations

- Pregame PA probability cards are static within a simulation and do not react to simulated fatigue, times-through-order, substitutions, or bullpen deployment.
- Historical Retrosheet starter records identify starters but lack captured-at timestamps; exports therefore remain `NOT_READY` for consumer execution.
- First-five truth is unavailable for four non-holdout historical games and remains explicitly missing.
- No governed historical sportsbook quote history exists, so no market benchmark, historical betting ROI, or threshold qualification is claimed.
- E10 has only the 183-game untouched holdout game evaluation. Its Fold 1–5 predictions are not OOF and are not reported as such.
- The comparison interval includes zero. No game engine is selected, and neither research engine is promoted.

AISP_GAME_FORECAST_EXPORT_MVP_COMPLETE
