# D3_PROBABILISTIC_PA_PROVIDER_V1

**Status:** engineering interface contract (Phase 5C, Monte-Carlo entry gate 5).
**Not** a new model, a game forecast, a betting model, or a Monte-Carlo result.

## Purpose

Invoke the already-governed D3 plate-appearance model faithfully inside the proven Phase 5
kernel. The provider **loads** the existing D3 model — it does not retrain, refit, relabel, or
alter D3, its hyperparameters, its features, or its class order. Given a simulation-time
invocation context it returns the frozen eight-class PA probability vector.

## Parent authority

`MLB_DYNAMIC_PLAYER_STATE_V1` (selected challenger candidate **D3** =
`context + cumulative batter state + cumulative pitcher state`, multinomial-logistic L2,
C=0.05). The provider consumes the run's data-only artifacts unchanged.

## Immutable eight-class order

Index → label, never reordered:

```
0 STRIKEOUT   1 WALK_HBP_CI   2 HOME_RUN   3 SINGLE
4 DOUBLE      5 TRIPLE        6 BIP_OUT    7 OTHER_REACH
```

## Invocation context (input)

A simulation-time context carries at minimum: game id / simulation identity, game date,
inning, top/bottom, outs before, base mask before, batting-team score differential before,
batter canonical identity, pitcher canonical identity, and the batter/pitcher state authority
(the governed dynamic-player-state B_CUMULATIVE table).

## Response (output)

Exact eight-class probability vector (immutable order), model authority, feature-contract
authority, preprocessing authority, fold season, batter/pitcher missing-history flags,
invocation warnings/missingness, and the probability validation result.

## Governed artifacts (data-only, hash-verified before deserialization)

| Fold | model-state SHA-256 | preprocessor SHA-256 |
| --- | --- | --- |
| 2024 (trained 2023) | `af6c0a46…238f` | `3a159b71…fbea` |
| 2025 (trained 2023-24) | `722aeed9…a8be` | `83024194…cf91` |

State table `mlb-dynamic-player-state-v1.parquet` SHA-256 `6117988d…3b03`. Frozen fold
predictions `dynamic-fold-{2024,2025}-predictions.parquet` (`raw_D3_*` columns) are the
bit-exact reproduction target. All artifacts are **JSON/Parquet data-only — no pickle,
joblib, or executable deserialization** (governed security rule). The SHA-256 of every model
and preprocessor artifact is verified **before** any parsing.

## Temporal fold selection

There is one D3 model per temporal fold. The 2024 fold (trained on 2023) scores 2024 games;
the 2025 fold (trained on 2023-2024) scores 2025 games. The provider selects the model by the
game's season, reproducing the frozen `raw_D3` predictions for that fold.

## Simulation-time feature construction

The 33 D3 features expand to 43 model inputs. Feature roles:

- **Current game state** (`context_inning`, `context_top_bottom`, `context_outs_before`,
  `context_base_mask_before`, `context_batting_score_diff_before`) — supplied by the evolving
  simulated game state; these vary per plate appearance.
- **Frozen cumulative player state** (`batter_b_*`, `pitcher_b_*`) — the B_CUMULATIVE state is
  history strictly before the game date, so it is **frozen per game** and never accumulates
  within a simulated game.

The provider must not use the target PA result, any later PA evidence, target-game future
player performance, the final score, the actual game outcome, or any current-game cumulative
player evidence D3 did not historically have at the invocation point. The original D3 temporal
contract is preserved.

## No fallback invention

The governed dynamic-player-state table always supplies a B-state row for a player with a
target PA on that date; a missing-history player is shrunk to the role-league prior and
carries `missing_history=1` (a model feature). The provider therefore uses the governed
missing-history policy directly and invents no league-average fallback. A player with no
governed state row fails closed (the PA is unresolvable, and any game containing it is
Monte-Carlo ineligible).

## Probability validation

Every response must have exactly eight probabilities, all finite, all in [0, 1], summing to 1
within `1e-9`, in the correct class order, with model and preprocessing authorities present.
No NaNs, no silent fallback.

## Reproduction gate

For every eligible 2024/2025 historical PA, feeding the historical pre-PA context through the
provider reproduces the frozen `raw_D3` vector to `0.0` maximum absolute difference and
reproduces the known D3 log loss (2024 ≈ 1.476588, 2025 ≈ 1.474100). Any deviation blocks
Monte-Carlo entry.

## Throughput

Model and preprocessor load exactly once per session (no per-PA model loading). A batch
scoring path builds one feature matrix and issues a single vectorized model call — the
throughput seam a future batched Monte Carlo uses.

## Prohibitions

No D3 retraining / hyperparameter / feature changes, no E1/E2/E6, no algorithm tournament, no
premium data, no residual model, no win/run-line/total probabilities, no betting edge, no AI
Sports Predictor connection, no provider/network calls, no whole-game Monte Carlo.
