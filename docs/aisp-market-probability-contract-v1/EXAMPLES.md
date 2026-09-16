# Contract examples

Lines below are illustrative and are not recorded sportsbook offers. They show which immutable channel must answer each question.

## MLB total

Bind the exact unrestricted 5,000-draw V18 FINAL_PREGAME population for the target game, then request:

```json
{"market":"TOTAL","selection":"OVER","line":8.5}
```

Every accepted V18 score pair contributes once. The score-limited, survival, and transition research populations cannot replace the controlling population.

## NFL moneyline and spread

For a HOME moneyline, tie handling is mandatory:

```json
{"market":"MONEYLINE","selection":"HOME","tieSettlement":"PUSH"}
```

For an away underdog:

```json
{"market":"SPREAD","selection":"AWAY","line":3.5}
```

The NFL M1 population’s equal-score mass stays visible. It is not silently divided between home and away.

## NBA point-only rejection and joint total

`NBA_GEN1_ELO_WIN_RIDGE_A100_ORDINARY_REST_V1` has `drawCount=0`. The question “Over 225.5?” returns `PAIRED_POPULATION_UNAVAILABLE`; it cannot be answered from the expected total.

The separate `NBA_GEN1_JOINT_FINAL_PAIRED_OOF_LATTICE_V1` population supports:

```json
{"market":"TOTAL","selection":"OVER","line":225.5}
```

Its joint-derived winner probability remains separate from published Elo.

## CFB integer total

```json
{"market":"TOTAL","selection":"UNDER","line":55}
```

The response preserves mass at exactly 55 as a push. The baseline paired-residual population is permitted; cluster and gap challengers are not substituted.

## Same-game correlated two-leg request

```json
[
  {"market":"MONEYLINE","selection":"HOME","tieSettlement":"PUSH"},
  {"market":"TOTAL","selection":"OVER","line":47.5}
]
```

The implementation evaluates both legs in each same-game score cell. In the synthetic golden fixture, HOME win is `3/8` and OVER 2.5 is `5/8`; their naive product is `15/64`, while their actual joint win probability is `2/8`. The product is therefore rejected.

## Push and half-point vectors

The golden fixture’s OVER 3 has counts `win=1, loss=3, push=4, void=0`. UNDER 2.5 has `win=3, loss=5, push=0, void=0`. See `fixtures/golden-vectors.json` for exact population bytes and SHA-256.

## Cross-game request

Combining results from two distinct games raises `CROSS_GAME_JOINT_UNSUPPORTED` by default. If a research caller explicitly enables independence, the response is labeled:

```json
{"status":"APPROXIMATE_RESEARCH_ONLY","method":"INDEPENDENCE_ASSUMPTION","effectiveDrawCount":null,"winProbabilityMonteCarloStandardError":null}
```

That approximation must not be presented as a model-derived parlay probability.
