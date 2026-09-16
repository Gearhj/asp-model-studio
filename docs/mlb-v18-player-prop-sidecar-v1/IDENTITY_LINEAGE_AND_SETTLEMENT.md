# Identity, lineage, reconciliation and settlement

## Identity and orientation

Top-half events belong to the away batting lineup and home pitching side. Bottom-half events belong to the home batting lineup and away pitching side. `battingOrderPosition` is resolved only against the frozen confirmed lineup for that side. A reversed orientation therefore changes the identity check and cannot silently reassign counts.

The frozen lineup supplies canonical player UUID, MLBAM ID, team UUID, batting slot and lineup observation. The saved provider input supplies the exact V18 model-template player identity for that slot. `STARTER` binds only to the named opposing starter. `TEAM_BULLPEN` is recorded as anonymous team relief and never assigned to a person.

A later lineup, starter, schedule or forecast revision requires a newly bound sidecar. The evaluator can enforce expected game, forecast, population and lineup-observation identities and rejects mismatches.

## Reconciliation

For every draw:

- `H = 1B + 2B + 3B + HR` for each batter.
- `TB = 1B + 2×2B + 3×3B + 4×HR` for each batter.
- Named-batter PA sums match retained team and whole-game PA totals.
- Named-batter outcome counts match the existing passive team outcome counters.
- Named-batter HR counts match the team `HOME_RUN` outcome count. They are not equated to runs scored.
- Named-starter plus anonymous-relief BF equals opponent PA.
- Named-starter BF matches the existing starter-exposure counter.
- Starter strikeouts are counted only on `STARTER` events; bullpen strikeouts remain anonymous.

## Settlement

For an over at line `L`, win means count `> L`, push `= L`, loss `< L`. Under reverses win and loss. Integer lines can push; half lines cannot. One-plus hit and HR yes use over 0.5. HR no uses under 0.5.

Conditional win/loss/push counts sum to draw count and their probabilities sum to one. `pVoid` remains null because participation and sportsbook grading rules are unsupported. A consumer requiring unconditional four-way mass must fail closed.
