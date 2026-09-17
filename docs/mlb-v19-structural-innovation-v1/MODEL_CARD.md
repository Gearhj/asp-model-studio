# Model card: MLB_V19_TEAM_DEFENSE_BIP_EB_V1

## Purpose

Research whether a completion-aware, shrunk team fielding conversion rate adds information to the exact V18 PA probabilities. This is a bounded structural challenger, not a production model.

## Inputs and formula

For each target date, use only prior games whose retained completion date is earlier than the target date. Count `SINGLE`, `DOUBLE`, and `TRIPLE` as BIP hits and `BIP_OUT` as BIP outs for each fielding team. Shrink the team BIP hit rate to the league rate with selected prior strength 1,600. Apply the team-minus-league log-odds difference, capped at ±0.35, to V18's conditional BIP hit probability.

The output keeps total BIP mass fixed, keeps the V18 single/double/triple proportions fixed within hit mass, and preserves `STRIKEOUT`, `WALK_HBP_CI`, `HOME_RUN`, and `OTHER_REACH` bit for bit.

## Training and selection

- Development: 2023 fold 0.
- Selection window: 2023-08-01 through 2023-10-01.
- Frozen choices: prior strength 100, 400, or 1,600; cap 0.35.
- Selected: 1,600 by Development conditional BIP log loss.
- Assessment: reused 2024 fold 1 only; 99,646 PAs after two delayed-game exclusions.

## Limitations

This is not a player defense model. The estimate confounds fielders, park, pitchers, positioning, schedule, scorer effects, and other team context. The retained data does not bind named pregame fielders or positions. Its assessment is reused evidence and inherits the exact V18 baseline's unresolved rolling-history chronology defect. It cannot support a promotion claim.

## Result and authority

Point estimates moved slightly lower, but the primary 95% interval crossed zero. Disposition: `NO_INCREMENTAL_VALUE`. No forecast, simulation, shadow, ensemble, or production authority.

\n