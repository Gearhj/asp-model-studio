# MLB V18 PA finalist and governed game-baseline foundation

Status: `PA_FINALIST_AND_PARTIAL_TRANSITION_FOUNDATION_COMPLETE_V18_GAME_EVALUATION_BLOCKED`.

## PA-finalist decision

Disposition: `ADVANCE_AS_QUALIFIED_PA_FINALIST_FOR_GAME_SIMULATION_DEVELOPMENT`; decision `mlb-v18-pa-finalist-5c9628d50f433e92e1e9eb6d962326a8`.

On 501,539 matched PAs, V18 log loss was 1.474589538657 versus 1.474558302223 for V14 (difference +0.000031236434; paired game-clustered 95% CI [-0.000211973146, +0.000281453522]). V18 did not demonstrate superiority, equivalence, or noninferiority. It advances only as the governed PA-component finalist for Development game-simulation work.

All six predefined cold/no-history point estimates were worse. The either-player cold-start and three overlapping 47-game team no-history intervals were nominally positive; they remain uncertainty/qualification risks, not a basis for a V14/V18 hybrid.

## Calibration decision

Disposition: `CALIBRATION_CHALLENGER_REQUIRED_BEFORE_BASELINE_SIMULATION`; decision `mlb-v18-calibration-e12164c461d36b9667b415147591e448`.

The predeclared criterion was hashed before evidence loading and evaluates aggregate, class, rare-class, probability-band, fold, and stable-subgroup behavior. One populated temporal-fold reliability-band gate fails, so a calibration challenger is required before the baseline can be qualified. No calibrator was fitted here. Raw V18 probabilities remain permissible only for a clearly labeled uncalibrated Development baseline; sparse no-history groups remain non-gating warnings.

| Calibration gate | Observed | Maximum | Pass |
| --- | ---: | ---: | --- |
| overallEce | 0.004589942 | 0.010000000 | True |
| overallMaximumPerClassAbsoluteError | 0.002852433 | 0.005000000 | True |
| rareClassMaximumAbsoluteError | 0.000398041 | 0.003000000 | True |
| maximumFoldEce | 0.011952988 | 0.015000000 | True |
| maximumFoldPerClassAbsoluteError | 0.013058008 | 0.015000000 | True |
| maximumPopulatedReliabilityBandGap | 0.058372294 | 0.040000000 | False |
| maximumStableSubgroupEce | 0.005284793 | 0.015000000 | True |
| maximumStableSubgroupPerClassAbsoluteError | 0.005345769 | 0.015000000 | True |

## Executable authority result

V18 game disposition: `V18_GAME_BASELINE_BLOCKED_MISSING_PREGAME_AND_TEMPLATE_AUTHORITY`. The current Stage3 readiness endpoint reports no registered executable artifact, zero governed games, and missing timestamped lineup/starter authority. A V18 game run therefore fails closed: no realized PA sequence, actual substitutions, or actual relievers were substituted.

The repository does support the sequential 24-state engine and fold-local transition estimation. A 4,096-draw, participant-free league-average null conformance run completed with zero illegal and zero nonterminated simulations; it is not a V18 forecast or game-level evaluation.

## Capability matrix

| Capability | Classification | Implication |
| --- | --- | --- |
| Confirmed pregame batting orders and original knowledge timestamps | `MISSING_AUTHORITY` | V18 historical and prospective game scoring fails closed. |
| Historical Retrosheet starting lineups | `POST_OUTCOME_OR_ORACLE_ONLY` | May describe an oracle research analysis only; not used here. |
| Starting-pitcher identity and confirmation timestamp | `MISSING_AUTHORITY` | No V18 game may be scored. |
| Historical starter and reliever identities | `POST_OUTCOME_OR_ORACLE_ONLY` | Not used as pregame evidence. |
| Bench and substitution candidates | `MISSING_AUTHORITY` | Substitutions cannot be simulated prospectively. |
| Bullpen roster, handedness, quality, availability, and workload | `MISSING_AUTHORITY` | Starter-to-bullpen behavior must not be fabricated. |
| V18 batter/pitcher features for hypothetical PAs | `MISSING_AUTHORITY` | Saved V18 OOF models cannot legally be driven through a full simulated game. |
| Dynamic inning/half/outs/base/score/PA ordinal state | `SUPPORTED_ONLY_AS_A_DECLARED_BASELINE_ASSUMPTION` | Executable when a compatible PA provider is supplied. |
| Historical PA outcome and pre/post-PA base/out state | `SUPPORTED_BY_FOLD_LOCAL_HISTORICAL_ESTIMATION` | Supports exact transition fitting through fold 4 training and complete validation only for folds 1-3; 2026 authority is missing. |
| Runner advancement conditional on outcome/base-out state | `SUPPORTED_BY_FOLD_LOCAL_HISTORICAL_ESTIMATION` | Transition artifacts are executable for four training folds; evaluation is complete for folds 1-3 only. |
| Double plays, sacrifices, errors within a PA | `DEFERRED_SPECIALIST_COMPONENT` | Transition uncertainty is retained; no specialist added. |
| Steals, caught stealing, wild pitches, passed balls, pickoffs between PAs | `MISSING_AUTHORITY` | Baseline cannot model these events explicitly. |
| Starter workload, fatigue, times through order, removal | `DEFERRED_SPECIALIST_COMPONENT` | Do not silently hold a starter for a qualified V18 baseline. |
| Manager hook and reliever selection | `DEFERRED_SPECIALIST_COMPONENT` | Requires a separately evaluated chronological component. |
| Park environment | `MISSING_AUTHORITY` | Park-specific game distributions are unavailable. |
| Weather and umpire | `MISSING_AUTHORITY` | No weather/umpire scenario is asserted. |
| League and season context | `SUPPORTED_BY_GOVERNED_PREGAME_AUTHORITY` | Usable only after a prospective template builder exists. |
| Walk-off and regulation completion rules | `SUPPORTED_ONLY_AS_A_DECLARED_BASELINE_ASSUMPTION` | Verified in null conformance. |
| Current extra-inning automatic runner | `SUPPORTED_ONLY_AS_A_DECLARED_BASELINE_ASSUMPTION` | Mechanics are available; era/rule version still needs a game authority. |
| Gen 1 independent-Poisson comparison | `SUPPORTED_ONLY_AS_A_DECLARED_BASELINE_ASSUMPTION` | A fair numeric V18 comparison is not reported. |
| Richer Gen 2 sequential engine reuse | `SUPPORTED_ONLY_AS_A_DECLARED_BASELINE_ASSUMPTION` | Engine code is reused only for participant-free conformance. |

## Fold-local transition evidence

The registered FD1 authority supplied 549,479 explicit terminal-PA transitions from 570,548 play-transition rows across 7,289 games, covering 2023-03-30 through 2025-09-28. It is retrospective target evidence used only inside its corresponding training/evaluation windows. The opaque Current Gold 2025-2026 PA keys were not sorted or inferred.

| Fold | Status | Train transitions | Validation transitions | Model log loss | Null log loss | Difference | Transition ECE | Base accuracy | Outs accuracy |
| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | `FIT_AND_EVALUATION_COMPLETE` | 184,104 | 100,588 | 0.256099 | 1.150581 | -0.894482 | 0.004408 | 0.9108 | 0.9750 |
| 2 | `FIT_AND_EVALUATION_COMPLETE` | 284,692 | 101,209 | 0.258692 | 1.153076 | -0.894384 | 0.001975 | 0.9098 | 0.9750 |
| 3 | `FIT_AND_EVALUATION_COMPLETE` | 385,901 | 100,008 | 0.261405 | 1.160879 | -0.899474 | 0.002026 | 0.9098 | 0.9750 |
| 4 | `FIT_COMPLETE_EVALUATION_BLOCKED_INCOMPLETE_REGISTERED_TRANSITION_VALIDATION_AUTHORITY` | 485,909 | 63,570 (partial/not scored) | — | — | — | — | — | — |
| 5 | `BLOCKED_MISSING_COMPLETE_REGISTERED_TRANSITION_TRAINING_AUTHORITY` | 549,479 | 0 (partial/not scored) | — | — | — | — | — | — |

Four transition estimators were fitted: folds 1-4 had complete training authority. Only folds 1-3 had complete validation authority and were evaluated. Fold 4 validation extends into 2026 and fold 5 training/validation require 2026, while registered FD1 ends on 2025-09-28. Partial fold-4 rows were not scored as complete-fold evidence. Each fitted JSON artifact contains exact counts and probabilities for outcome × outs × base, outcome × outs, and outcome backoffs, plus a uniform legal prior. Home runs use the deterministic conservation rule. Every artifact was reloaded and all 192 distributions were legality/sum checked.

## Inning/game evaluation and comparisons

V18 inning and game metrics, team-run distributions, home-win scoring, temporal/park/cold propagation, and representative game paths are **not estimable**. That is a result of missing pregame authority, not a silent omission. The older Gen 1/Phase 7 evidence uses different cohorts, model contracts, and historically reconstructed participants, so no misleading numeric same-game comparison is reported.

## Error and Regime Atlas foundation

The component ledger covers 6,664 OOF games with saved PA loss/entropy, fold-local transition loss/null improvement, sparse-backoff rate, and an explicit missing-authority flag. Participation, run-distribution, and game-calibration errors remain null because no valid game forecast exists.

## Prioritized simulator challengers

1. **Timestamped confirmed-lineup and announced-starter authority plus V18 prospective feature-template builder** — sample/effect evidence: 0 currently governed games; Restores coverage from zero to potentially all qualified games.
2. **BIP_OUT advancement subtype challenger** — sample/effect evidence: 137036; 0.26610415260651665.
3. **Cold-start PA probability specialist** — sample/effect evidence: 83174; 0.0006849245018535678.
4. **Prospective starter hook and bullpen selection/availability** — sample/effect evidence: No governed bullpen decisions; Not estimable until participant baseline exists.
5. **OTHER_REACH transition taxonomy** — sample/effect evidence: 2948; 1.1920557447697917.

## Governance and next step

Smallest next step: Register immutable pregame lineup and starter snapshots with source/observation/receipt timestamps, add ordered 2026 transition targets, then implement and fixture-test an 18-row V18 raw-template builder against each saved fold pipeline before any game evaluation.

No PA estimator or calibrator was fitted. 4 authorized transition fits, 3 complete-fold transition evaluations, and one participant-free null conformance simulation were completed. Final OOT remained sealed; no model was promoted, exported, deployed, merged, or registered in AISP.
