# MLB V18 player-prop calibration feasibility

## Disposition

`INSUFFICIENT_ADMISSIBLE_EVIDENCE_NO_HISTORICAL_ASSESSMENT`

The new V18 player-prop population is mechanically correct, but there is not yet an honest Development/Validation population on which to claim predictive validity. No assessment outcomes were loaded and no calibration metrics were computed. Batter 1+ hit, batter total bases, batter home run, and starting-pitcher strikeouts all remain `INSUFFICIENT_EVIDENCE`.

This is a coverage result, not a failed model result. The historical system has fold-specific PA predictions and simulation dependencies, but its game participants are actual Retrosheet starters/batting orders without captured-at authority or the explicitly named historical-participant oracle. The existing integrity receipt reports zero certified historical metric rows. Running the final fold-5 V18 artifact over those games would also violate the requested out-of-sample rule.

## Evidence audit before outcome access

| Requirement | Historical 2022–26 research paths | Current prospective V18 path | Admissibility |
|---|---|---|---|
| Pregame lineup and order | Actual Retrosheet starting records; no observed publication timestamp | Complete confirmed lineups with observation IDs and clocks | Historical fails; current passes |
| Named starters | Retrosheet start records / oracle | Two canonical named probable starters with source clocks | Historical fails point-in-time proof; current passes |
| Pregame features | Chronological feature machinery exists, but original fitted-history chronology is uncertified | Source cutoff, snapshot, prior-day history and immutable raw templates retained | Current is target-excluding but keeps chronology qualification |
| Model fit excludes target/later evidence | Five historical OOF PA folds exist; the current final fold-5 artifact is not OOF for its own training history | Operational fold 5 trained through 2026-05-01; current September games are later | Current passes target exclusion |
| Simulation dependencies | Direct PA OOF and fold-local transition artifacts exist, with incomplete later transition certification | One frozen PA model and transition model bind every current object | Present |
| Player identity | Historical canonical identities exist but participant selection is postgame/oracle | Canonical player UUID plus MLBAM ID, team, side and batting slot retained | Current passes |
| Governed result source | Historical labels exist but cannot cure participant timing | Corrected diagnostic V2 has 1,173 completed PAs across 15 games | Result source exists only for a separate small cohort |
| Per-draw prop population | Not historically retained | One unique forecast has a local sidecar; both copies were derived after start | No eligible assessment cohort |

The inspected current inventory contains 89 immutable forecast objects for 86 distinct games dated September 10–16. All 89 have two complete confirmed lineups, two named starters, 5,000 draws, source/capture/create clocks before first pitch, PA artifact `44ec4f457741f1aaeff42b81af1be5fd2712e494709ff1a0a8f0742b88d71c8b`, and transition artifact `0e5e480f897ddefa5f9dddbc229a8a43bf29f7b81443c25ece611d9d4032b253`. Duplicate objects are immutable revisions, not extra games.

Only MIA–AZ MLBAM 825030 has a derived player-prop population. Its authenticated sidecar is `3259706deca700ac6d0ea1b8779eaae9fdbcc359612b69ad3168dd920924d3d4`; it binds forecast object `2f07648c51e830736d65ff37689c563bb2195ec767090d14ecc8e905968cbdac`. The capture adapter classifies it `RETROSPECTIVE_DERIVATION_ONLY` because the sidecar creation time follows scheduled first pitch. Exact forecast replay still proves mechanical preservation, but one post-start derivation cannot be a frozen Validation cohort.

The corrected postgame V2 package is known to contain 1,176 play records: 1,173 completed PAs and three inning-ending baserunning outs across 15 September 12 games. It was not opened in this task. Those games have no sidecar captured before their starts, the package has been inspected in earlier diagnostics, and 270 possible starting-batter observations are below the frozen future minimum. Replaying them now could only create reused exploratory evidence, not untouched-with-respect-to-selection Validation.

## Why no historical metrics are reported

The existing historical game simulator cycles an actual recorded starting lineup. Its report states that Retrosheet starter records have no captured-at timestamp, and Phase 5 calls the path `HISTORICAL_PARTICIPANTS_ORACLE_MODE`. That violates the requirement not to substitute actual postgame participation for prospective participation. Separately, the V18 Development integrity receipt reports 0 certified historical metric rows because historical publication availability and complete fitted-feature chronology are not established.

The Final OOT payload and every sealed/protected result remained unopened. No reduced Final OOT evaluation was attempted because this assignment prohibited Final OOT access altogether.

## Inactive prospective capture adapter

`mlb_v18_player_prop_calibration.build_capture_record` authenticates one forecast, its lineup/starter revisions, source clocks, model/transition lineage, and an optional sidecar. It rejects outcome-bearing inputs, later lineup/starter evidence, model/target overlap, identity drift, and tampering. A missing sidecar is `SIDECAR_PENDING`; a post-start sidecar is `RETROSPECTIVE_DERIVATION_ONLY`; only a pre-start sidecar is `PROSPECTIVE_CALIBRATION_CAPTURE_READY`.

The CLI is a dry run unless an explicit local output root is supplied. It does not read outcomes. It is not connected to a scheduler or production owner. The smallest later integration is an inactive hook in the existing V18 owner after immutable forecast creation and before first pitch: run the already verified passive sidecar and then register the capture. No second scheduler is required.

## Predeclared future study

The complete pre-registration is in `PROSPECTIVE_CAPTURE_PLAN.json`. It uses game-date-atomic chronological roles. Development completes before any Validation result is read. The primary 1+ hit family requires at least 2,500 batter-games, 125 games, 200 players and 10 dates in each role. Two-way Poisson cluster bootstrap weights game date and canonical player identity; the 5,000 simulation draws are never treated as observed games.

The simple comparison is an earlier-only beta-smoothed player hit rate combined with an earlier-only batting-slot PA distribution. Its independent-PA assumption is disclosed and it is used only as a transparent baseline. Development may fit a separately identified calibration challenger. Validation gates are frozen in the plan; no threshold changes follow outcome inspection.

Count families use the whole predicted count distribution plus fixed thresholds. No historical sportsbook lines are invented, and no profitability metric is authorized. Starting-pitcher strikeouts stay separate because V18's starter-removal hook and anonymous bullpen determine exposure.

## Participation and settlement limits

The V18 population is conditional on the frozen nine-player starting lineups. A confirmed start does not eliminate later pinch hitting, defensive replacement, injury, walk-off exposure, or shortened-game risk. The official starter's own full-game player total is the label; actual substitutions and realized PA counts are never supplied to the simulation. A late scratch, a different actual starter, cancellation, postponement, or incompatible shortened-game settlement is excluded with an explicit disposition because V18 has no unconditional participation or void probability.

## Per-prop disposition

| Prop | Mechanical population | Predictive evidence | Disposition |
|---|---|---|---|
| Batter 1+ hit | Direct per-draw `HITS >= 1` | No admissible Development/Validation cohort | `INSUFFICIENT_EVIDENCE` |
| Batter total bases | Direct per-draw TB | No admissible Development/Validation cohort | `INSUFFICIENT_EVIDENCE` |
| Batter home run | Direct per-draw HR | No admissible Development/Validation cohort; rare-event minimum not met | `INSUFFICIENT_EVIDENCE` |
| Starting-pitcher strikeouts | Direct K while V18 reports `STARTER` | No admissible cohort; duration assumptions require separate scoring | `INSUFFICIENT_EVIDENCE` |

## Operations and compute

- Model fits: 0
- Assessment simulations: 0
- Sidecar simulations: 0 in this task; the retained prior replay was read and authenticated only
- Outcome / sealed / Final OOT reads: 0 / 0 / 0
- Provider calls / bytes / cost: 0 / 0 / $0
- AISP writes / exchange writes / forecast publications: 0 / 0 / 0
- Scheduler / owner / production changes: 0 / 0 / 0

The exact next dependency is to activate the outcome-free hook inside the existing V18 owner for consecutive future eligible forecasts, retain governed revised player-game results only after role closure, and let the two chronological roles reach their frozen minimums. Until then, no AISP player-prop probability is supported.
