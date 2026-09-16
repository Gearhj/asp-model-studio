# Orientation and settlement rules

These are producer definitions for a future research population. Sportsbook house rules remain quote-specific and must be captured by the consumer before comparison.

## Statistics

- `BATTER_HITS`: `SINGLE + DOUBLE + TRIPLE + HOME_RUN` for the named batter.
- `BATTER_TOTAL_BASES`: `SINGLE + 2*DOUBLE + 3*TRIPLE + 4*HOME_RUN`. Walk, HBP, catcher interference, error/other reach and fielder's choice contribute zero.
- `BATTER_HOME_RUNS`: count of `HOME_RUN` for the named batter.
- `STARTING_PITCHER_STRIKEOUTS`: count of opposing `STRIKEOUT` PAs while the named starter is active. The current system cannot define a named-reliever K prop.

The current eight-class outcome collapses walk/HBP/catcher interference and coarse other reaches, but that does not prevent the four statistics above. It would prevent props requiring distinctions inside those classes.

## Line settlement

For a nonnegative integer statistic `X` and line `L`:

- Over wins when `X > L`, pushes when `X = L`, loses when `X < L`.
- Under wins when `X < L`, pushes when `X = L`, loses when `X > L`.
- A yes/no “1+ hit” or “to homer” proposition is equivalent to `X >= 1` versus `X = 0`; no numeric push occurs.
- Integer lines may push; half-unit lines cannot push because the statistic is integer-valued.

Player identity never follows a batting slot after a real substitution. The present simulator keeps the original player in that slot, so a future sidecar describes the frozen-player path, not official substitution mechanics.

## Void and game changes

V18 does not model a late scratch, non-start, in-game injury, cancellation or postponement probability. It also does not encode each sportsbook's minimum-participation or listed-player rules. `pVoid` is therefore unavailable. A quote can be compared only after the consumer establishes compatible rules and either receives an eligibility observation that makes the player/game action under those rules while retaining the original forecast cutoff, or receives a separately governed participation/void probability model.

Without one of those conditions, display only the real quote as **“Sportsbook market — no AISP assessment.”** Do not expose a model probability, fair price, edge, decision or position.

## Orientation checks

The future adapter must match game ID, MLBAM gamePk, team side, canonical player ID and role. A player name string is not identity. For pitcher props it must also prove the player is the frozen starter for the pitching team and count strikeouts from the opponent's batting events. A lineup or starter revision cannot overwrite the earlier sidecar.
