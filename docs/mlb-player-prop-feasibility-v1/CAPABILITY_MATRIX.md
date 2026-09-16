# Prop capability matrix

`DIRECT` means exact named-player values exist for every retained draw. `DERIVABLE_AFTER_IDENTITY_COUNTER` means unchanged correlated simulation can produce the values, but the current immutable population does not contain them. `UNSUPPORTED` means current mechanics or identity do not support the quantity.

| Market / question | Required statistic | Existing 5,000-draw package | Existing simulator | Dependence treatment | Current disposition |
|---|---|---|---|---|---|
| Batter 1+ hit | Per-draw named batter count of `SINGLE+DOUBLE+TRIPLE+HOME_RUN` | Team scores plus one trace; no full player events | Side+slot maps to fixed lineup | Count within each original draw | `DERIVABLE_AFTER_IDENTITY_COUNTER`; no probability now |
| Batter hits O/U | Same integer hit count | Same gap | Same support | Count within each original draw | `DERIVABLE_AFTER_IDENTITY_COUNTER`; no probability now |
| Batter total bases | `SINGLE+2*DOUBLE+3*TRIPLE+4*HOME_RUN` | Same gap | Eight classes are sufficient | Count within each original draw | `DERIVABLE_AFTER_IDENTITY_COUNTER`; no probability now |
| Batter home run | Named batter `HOME_RUN` count | Same gap | Eight classes are sufficient | Count within each original draw | `DERIVABLE_AFTER_IDENTITY_COUNTER`; no probability now |
| Starting-pitcher strikeouts | Opposing `STRIKEOUT` PAs while named starter active | Starter BF exists, starter K count does not | Named starter plus `STARTER` state exists | Count within each original draw | `DERIVABLE_AFTER_IDENTITY_COUNTER`; duration caveat; no probability now |
| Named-reliever strikeouts | Strikeouts while specific reliever active | Anonymous relief only | No named availability/selection | Cannot recover | `UNSUPPORTED` |
| Scratch/cancellation void | Probability prop is void under exact book rules | No participation/void model | Status gate only; fixed participants | Cannot infer from PA paths | `UNSUPPORTED` |

## Existing retained identities

The current package binds canonical game, MLB source game, forecast, model/transition authorities, source cutoff, evidence digest, feature snapshot, confirmed lineup authorities, starters, 5,000 simulations and master seed. This is necessary but insufficient: the package must also bind each per-draw statistic to a canonical player and the exact participant revision.

## Non-identifiability example

Suppose a team has one single in each of two draws. The retained team aggregate can arise from player A recording the single in both draws, giving `P(A 1+ hit)=1`, or player B recording both, giving `P(A 1+ hit)=0`. Team/inning totals are identical. No post-processing of the aggregate can choose between those allocations.
