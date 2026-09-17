# AISP/Claude handoff: multisport feature readiness

This is a research-status handoff. It contains no forecast package, no consumer import request and no authority change.

## What AISP may display now

AISP may describe the current producer limitations already bound to its existing forecasts:

* **NFL:** team-level M1 uses prior scoring/EPA/success/explosiveness and schedule context; current quarterback/personnel, injuries and weather are not model inputs. The bounded direct EPA matchup and missingness additions did not improve reused evidence.
* **CFB:** Gen 1 uses Elo, scoring, yardage, recent form, prior shrinkage, rest and venue context. It lacks governed conference-realignment, roster, transfer, recruiting, quarterback and coaching inputs. Roughly 39% of reused later games are low-support under the fewer-than-five rule.
* **NBA:** Ridge expected scores and Elo winner probability remain separate outputs. The model lacks possessions/team-box efficiency and player availability. The existing paired-residual distribution retains the disclosed excess one-point-margin limitation.

These statements may appear as collapsed model limitations or research notes. They do not alter probabilities, forecast identities, decision policy or wagering authority.

## What AISP must not display

Do not label any tested feature block as selected, promoted, validated on untouched OOT, prospectively superior or production-ready. Do not expose the direct EPA arithmetic block as a new NFL model. Do not infer injury adjustments, player availability or weather effects. Do not compare the NFL binary diagnostic Brier with its operational three-way Brier or with NBA/CFB without the exact convention.

No new numbers in this handoff bind to a live game. Historical metrics are aggregate diagnostics only. No AISP probability, fair price, edge, decision or position follows.

## Producer roadmap

The next producer research dependencies are:

1. NFL fold-local schedule-fitted pass/run offense and defense effects using existing governed data.
2. CFB effective-dated conference identity and schedule-strength estimation.
3. NBA timestamped team game boxes for possession, pace and efficiency features.

Personnel/injury work for all sports remains blocked on a revisioned point-in-time source and identity contract. See `INJURY_AVAILABILITY_MATRIX.json` and `CANDIDATE_FEATURE_READINESS.json`.

## Integrity

Consume the reports from this Git branch only. `artifact-index.json` binds every file. There is no exchange location and no expected AISP acknowledgement. Existing model, forecast, account, decision and scheduler state must remain unchanged.
