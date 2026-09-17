# MLB Diamond Twin incremental-value screen

## Disposition: `NO_MATERIAL_INCREMENTAL_VALUE`

The bounded named-defense screen does not justify a Diamond Twin build. On 631 reused 2024 games and 47,286 exact fold-1 V18 plate appearances, actual target-game starting defenders made every assessed PA identifiable, but the development-fitted named-position adjustment worsened every predeclared proper score. Conditional BIP log loss increased by 0.001824 (95% calendar-date interval +0.001104 to +0.002538); eight-class log loss increased by 0.001181 (+0.000736 to +0.001654). A strictly prior-date carry-forward lineup proxy produced almost the same degradation.

The adjustment was mechanically large, not useful. In the explicitly retrospective fixed-realized-PA exposure proxy it changed home-win probability by 8.62 percentage points on average, yet winner log loss worsened by 0.02883 (95% +0.01102 to +0.04417), Brier by 0.01224 (+0.00425 to +0.01933), total MAE by 0.0718 runs, and margin MAE by 0.0670 runs. Large forecast movement without better proper scores is evidence against advancing this identity formulation.

## Population and chronology

The numerical baseline is the byte-verified V18 matched OOF population, SHA-256 `3e816c20f6276837062b97aaa5398984ac0b3660731cc086dfae4aef04f2c8ba`. The screen used 697 games / 52,360 PAs from March 20–May 19, 2024 for development and 631 games / 47,286 PAs from May 20–July 6 for reused assessment. It excluded 134 target PAs belonging to known delayed or unresolved games. Same-date lineups were forbidden as carry-forward evidence.

This isolates affected targets but does not repair the inherited suspended-game defect in V18's earlier rolling history. The Silver participant and result tables are also marked `modelEligible=false` and `approvedForTraining=false`. Results are therefore retrospective upper-bound and research-proxy evidence, never a deployable challenger or clean chronological validation.

## What was tested

One frozen architecture fit L2-penalized player-by-position residual effects around V18's conditional BIP hit probability. It preserved total BIP mass, V18's hit-type mix, and all non-BIP class probabilities. The target lineup was used only as an oracle. The deployable proxy carried forward the latest complete starting defense from a strictly earlier calendar date. Separate catcher, infield, and outfield identity ablations all worsened the PA scores.

The completed team-level `MLB_V19_TEAM_DEFENSE_BIP_EB_V1` experiment was not rerun. Pitcher GB/FB × defense, batter direction × defense, measured spatial alignment, catcher skill, named bullpen use, manager policy, and archetype interactions could not be tested honestly in the exact common population.

## Capital-allocation decision

| Concept | Disposition | Evidence |
|---|---|---|
| Aggregate defense | `NO_MATERIAL_INCREMENTAL_VALUE` | Completed V19 team BIP experiment was already rejected. |
| Named defense | `NO_MATERIAL_INCREMENTAL_VALUE` | Actual-participant oracle and prior-date proxy both worsened proper scores. |
| Spatial/matchup defense | `DATA_CAPTURE_REQUIRED_BEFORE_ASSESSMENT` | No governed spray, contact coordinates, fielder positioning, or pitcher GB/FB feature in the common population. |
| Catcher | `INSUFFICIENT_ADMISSIBLE_EVIDENCE` | Catcher identity worsened scores; framing, blocking, throwing, and game-calling quality were absent. |
| Bullpen | `DATA_CAPTURE_REQUIRED_BEFORE_ASSESSMENT` | No point-in-time named-reliever availability, role, and workload population. |
| Manager policy | `DATA_CAPTURE_REQUIRED_BEFORE_ASSESSMENT` | Retained manager identity is retrospective; no point-in-time policy state exists. |
| Archetype specialists | `DATA_CAPTURE_REQUIRED_BEFORE_ASSESSMENT` | Required interaction inputs and a chronology-valid common population are absent. Missingness is not evidence of value. |

No defense implementation should proceed. If future work revisits spatial defense, its first gate should be a separately governed point-in-time capture and an oracle ceiling using measured BIP direction/quality and fielder alignment. Bullpen, manager, and archetype work should remain unstarted until their own evidence and chronology gates exist.

## Integrity and authority

External artifact root: `C:\Users\james\asp-data-staging\mlb\diamond-twin-screen-v1`

- Assessment SHA-256: `5e865281823c62f327b8fde71dab281f34e488daca62e1ca6cea9100f9c5dcc7`
- Artifact index SHA-256: `51b7c0da785ac945db9027669fc35552e2bc5d4bd81fa5579f457686dca948cc`
- Provider calls, network bytes, credits, and cost: zero
- AISP writes, exchange writes, forecast publications, owner changes, and scheduler changes: zero
- Final OOT, sealed August 14–27 evidence, 2025 outcomes, and 2026 outcomes: not accessed
