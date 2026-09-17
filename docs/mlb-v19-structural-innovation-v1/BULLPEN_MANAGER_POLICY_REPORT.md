# Bullpen and manager policy report

## Current capability

The simulator can represent starter exposure, pitcher changes by PA ordinal, anonymous relief templates, base/out transitions, and game state. Separate survival and transition research components exist. Retrospective replay can identify actual relievers and substitutions, but those facts are prohibited as pregame inputs.

## Missing evidence

A valid named-bullpen policy needs, for every target cutoff:

- active roster and option/injury status;
- reliever role and handedness;
- recent pitches, batters faced, days of rest, and multi-day usage;
- availability uncertainty rather than roster-membership certainty;
- manager/team selection policy conditional on inning, score, base state, upcoming lineup, and prior usage;
- chronological target-game reliever and removal labels for Development only.

The retained cross-season population does not provide those fields with certified pregame clocks. The September prospective supplements are useful forward evidence but cannot repair historical availability. A manager model was therefore not fit, and an oracle actual-reliever comparison was not used.

## Disposition

`INSUFFICIENT_ADMISSIBLE_EVIDENCE`. Preserve anonymous fallback semantics until a bounded prospective named-reliever archive has adequate coverage. Missing evidence must remain a fallback, not a fabricated available reliever.
