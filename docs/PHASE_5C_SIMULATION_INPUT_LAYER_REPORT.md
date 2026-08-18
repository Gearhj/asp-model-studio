# ASP Model Studio — Phase 5C Simulation Input Layer

**Contracts:** `D3_PROBABILISTIC_PA_PROVIDER_V1`, `MLB_HISTORICAL_PARTICIPANT_REPLAY_PROVIDER_V1`,
`MLB_GAME_INITIALIZATION_CONTRACT_V1`. Simulation-input interface layer — **not** a game
forecast, betting model, or Monte-Carlo result. No whole-game Monte Carlo was executed.

---

## 1. Executive Verdict

**`MONTE_CARLO_ENTRY_GATES_PASSED`.** The three final entry-gate components are built and
validated on real governed data. The D3 provider **loads** (does not retrain) the governed
data-only D3 model and reproduces the frozen `raw_D3` predictions **bit-for-bit** (365,375
2024-2025 PAs, maximum absolute probability difference **0.0**, reproduced log loss 2024
**1.4765879683** / 2025 **1.4740998598**, matching the known D3 metrics 1.476588 / 1.474100).
Historical participants reconstruct exactly for **2,429 / 2,429 (2024)** and **2,429 / 2,430
(2025)** games with 100% active-batter and active-pitcher resolution. Game initialization
validates to the canonical inning-1 opener. A bounded 40-game × 50-PA stochastic integration
composed all four seams with **0 illegal states, 0 invalid probability vectors, 0 duplicated
or lost runners**, reproducible under seed and divergent across seeds. Gates 5, 6, 7 are
closed; whole-game Monte Carlo remains **LOCKED** and NOT_CONFIGURED.

## 2. Phase 5A / 5B Parent Authorities

- **`MLB_GAME_REPLAY_ENGINE_V1`** — `GAME_REPLAY_ENGINE_READY` (7,288/7,289 exact; final-score
  and inning 100%; base/out continuity 99.986%). The deterministic kernel is unchanged.
- **`MLB_BASE_OUT_TRANSITION_MODEL_V1`** — `BASE_OUT_TRANSITION_MODEL_READY` (T0 empirical
  conditional; 2024/2025 transition log loss 0.2266/0.2280; illegal probability mass 0; model
  SHA `4f312af6…3459e4`, data-only JSON). Consumed unchanged.

Neither authority was modified or invalidated.

## 3. D3 Provider Contract (`D3_PROBABILISTIC_PA_PROVIDER_V1`)

The provider accepts a simulation-time context (game identity/date, inning, top/bottom, outs
before, base mask before, batting-team score differential, batter/pitcher canonical identity,
batter/pitcher state authority) and returns the exact eight-class probability vector in the
immutable order `STRIKEOUT, WALK_HBP_CI, HOME_RUN, SINGLE, DOUBLE, TRIPLE, BIP_OUT,
OTHER_REACH`, plus model / feature-contract / preprocessing authorities, fold season,
missing-history flags, warnings, and a probability-validation result. No class reorder.

## 4. D3 Artifact Verification

The provider **loads** the governed data-only artifacts persisted by
`MLB_DYNAMIC_PLAYER_STATE_V1` (selected challenger candidate **D3**, multinomial-logistic L2,
C=0.05). Each artifact's SHA-256 is verified **before** any deserialization:

| Fold | model-state | preprocessor |
| --- | --- | --- |
| 2024 (trained 2023) | `af6c0a46…238f` | `3a159b71…fbea` |
| 2025 (trained 2023-24) | `722aeed9…a8be` | `83024194…cf91` |

State table `6117988d…3b03`; frozen fold predictions `d7a69298…7ad5` (2024) / `3b262e60…1ee1`
(2025). All are JSON/Parquet **data-only — no pickle/joblib/executable deserialization**. The
provider rebuilds the exact governed scoring path (`FoldPreprocessor` fixed one-hot + mean-
impute/standardize, then multinomial softmax on the loaded coefficients/intercepts) and
rejects any mismatched model authority, preprocessing authority, class order, or fold season.
Model + preprocessor load once per session (measured **2.88 ms**); there is **no per-PA model
loading**.

## 5. Simulation-Time Feature Construction

The 33 D3 features expand to 43 model inputs. Roles were traced from the governed contract:

- **Current game state** — `context_inning`, `context_top_bottom`, `context_outs_before`,
  `context_base_mask_before`, `context_batting_score_diff_before`: supplied by the evolving
  simulated game state; vary per plate appearance.
- **Frozen cumulative player state** — `batter_b_*`, `pitcher_b_*` (log-odds, ESS, entropy,
  days-since-evidence, 7/30/90-day counts, missing-history): the B_CUMULATIVE state is history
  strictly before the game date, so it is **frozen per game** and never accumulates within a
  simulated game.

The provider uses no target PA result, no later PA evidence, no target-game future player
performance, no final score, no actual outcome, and no current-game cumulative player evidence
D3 did not historically have. The original D3 temporal contract is preserved. Because the
governed state table always supplies a row (missing-history players shrunk to the role-league
prior with `missing_history=1`), the provider uses the governed missing-history policy directly
and invents no league-average fallback.

## 6. Historical D3 Reproduction

Feeding every historical pre-PA context through the provider reproduces the frozen `raw_D3`
vectors:

| Metric | Value |
| --- | --- |
| rows compared | **365,375** (2024: 182,449 · 2025: 182,926) |
| maximum absolute probability difference | **0.0** |
| mean absolute probability difference | **0.0** |
| mismatch count (any class > 1e-9) | **0** |
| class-order mismatch count | **0** |
| reproduced 2024 log loss | **1.4765879683** (expected 1.476588) |
| reproduced 2025 log loss | **1.4740998598** (expected 1.474100) |

Reproduction is exact (0.0) when a fold is scored in one batch, matching how training scored
it. Sub-batch scoring agrees within BLAS floating-point non-associativity (~1e-16), well inside
the numerical-tolerance reproduction the contract requires. The adapter is faithful; entry is
not blocked.

## 7. D3 Scoring Performance

Batch scoring **27,967 PAs/second** (20,000-row matrix in 0.72 s); single-row latency
**0.93 ms**; model-load cost **2.88 ms once per session**; **no per-PA model loading**. Model
and preprocessor are immutable after load and safely reused across calls.

## 8. Participant Replay Contract (`MLB_HISTORICAL_PARTICIPANT_REPLAY_PROVIDER_V1`)

Reconstructs **actual** historical participants (labeled `HISTORICAL_REPLAY_ONLY`) from the FD1
`play_transition` ledger: starting lineup + batting order per team, starting catcher (role code
2), starting pitcher, pitcher-change sequence, batter substitutions, and the active batter/slot
and active pitcher per plate appearance. It is not the prospective participation provider and
not the Milestone B forecasts. Identity is bound exactly from terminal PA rows; the
retrosheet↔canonical map is 1:1 (0 violations across 365,375 PAs). A game that cannot be
exactly reconstructed is marked `PARTICIPANT_REPLAY_INCOMPLETE`.

## 9. Participant Coverage

| Season | Games | Complete replay | Active batter resolved | Active pitcher resolved | Substitutions reconciled | Eligible |
| --- | --- | --- | --- | --- | --- | --- |
| 2024 | 2,429 | 2,429 | 100% (182,449) | 100% (182,449) | 2,429 | 2,429 |
| 2025 | 2,430 | 2,429 | 100% (182,926) | 100% (182,926) | 2,429 | 2,429 (99.96%) |

Every 2024 game and 2,429 of 2,430 2025 games reconstruct exactly; the one 2025 exclusion is a
game whose ledger does not satisfy the exact-replay predicate (honestly marked incomplete, not
guessed).

## 10. Game Initialization (`MLB_GAME_INITIALIZATION_CONTRACT_V1`)

Validates the historical opener: inning 1, top half, 0 outs, bases empty, 0-0, two distinct
teams, two nine-player distinct batting orders, both starting pitchers, replay mode
`HISTORICAL_REPLAY`. Pins the dataset, replay, transition-model, PA-model, and participant-
provider authorities and one RNG lineage. Era/special-rule mechanics (extra-inning automatic
runner, shortened/suspended/doubleheader games) are handled source-realistically by the proven
kernel/transition model and documented, not reinvented. A sample eligible game validated
cleanly.

## 11. Short-Sequence Integration

Bounded stochastic integration (40 eligible 2024 games × 50 PAs = **2,000 sampled PAs**)
composing HistoricalParticipantReplay → D3ProbabilisticPAProvider → BaseOutTransition →
deterministic kernel: **0 illegal states, 0 invalid probability vectors, 0 duplicated runners,
0 lost runners, 0 unresolved participants**, inning progression valid throughout. Every D3
vector valid, every sampled class legal, every sampled transition legal for its state, runner
identities applied forward without duplication/loss, next batter and active pitcher resolved.
These are interface-integration checks, **not** game forecasts.

## 12. RNG / Reproducibility

One controlled lineage: master seed → per-game seed (`SHA-256(game_key)` folded into a NumPy
`SeedSequence`) → independent PA-sample and transition child generators. The integration is
**same-seed reproducible** (identical event stream) and **different-seed divergent** (different
sampled classes). Verified.

## 13. Monte Carlo Eligible Population

A game is eligible when initialization is valid, participants replay exactly, the D3 scorer
resolves every PA participant's governed state, the transition authority is valid, and terminal
rules are supported. **Eligible: 2024 = 2,429 / 2,429 (100%); 2025 = 2,429 / 2,430 (99.96%);
total 4,858.** This is the defined (not simulated) Phase 5D historical evaluation population.

## 14. Monte Carlo Performance Estimate

At 27,967 PA/s and ≈76 PAs/game (no simulation executed):

| Workload | PA calls | Estimated runtime |
| --- | --- | --- |
| one game × 1,000 sims | 76,000 | ≈ 2.7 s |
| 15-game slate × 1,000 sims/game | 1,140,000 | ≈ 40.8 s |
| full 2024 season × 1,000 sims/game | 184,604,000 | ≈ 6,601 s (≈ 1.8 h) |

## 15. Batching Recommendation

A 15-game slate at 1,000 sims completes in well under a minute, so **batching is not required**
for slate-scale Monte Carlo. For full-season sweeps, the design seam is present: collect
same-step simulation states across many simulations into one feature matrix and issue a single
model call (the provider's `score_batch` path). No stack rewrite is warranted; the measured
throughput does not require it.

## 16. Security / Artifact Boundary

The D3 adapter consumes trusted target-local **data-only** artifacts (JSON model/preprocessor,
Parquet state/predictions). SHA-256 is verified **before** deserialization for every model and
preprocessor. No pickle/joblib/executable artifact is produced or consumed, and no artifact
crosses a repository boundary. The persisted Phase 5C artifact is data-only JSON. A safer
governed bundle format for a future AISP export is **not** solved here.

## 17. Registry / Graph

Registered as an authority-gated `phase4.simulationInput` projection (run
`simulation-input-7d6f5d8404626529`) carrying the D3 reproduction, participant coverage,
eligible population, throughput, short-sequence legality, performance estimate, and entry
decision — no game-forecast or betting metrics. Model graph after Phase 5C:

```
Historical Game Replay        READY
Base-Out Transition Model     READY
D3 Probabilistic PA Provider  READY
Historical Participant Replay READY
Game Initialization           READY
Whole-Game Monte Carlo        NOT_CONFIGURED (LOCKED)
Historical Game-Level Backtest NOT_CONFIGURED
Game Calibration / Residual / Prospective Feed / Premium / ASP Export / Forward Monitoring  NOT_CONFIGURED
```

## 18. Remaining Limitations

One-step provider integration only; no whole-game Monte Carlo executed. Historical participants
only (`HISTORICAL_REPLAY_ONLY`); no prospective participation feed. The short-sequence
integration holds the historical starting pitcher throughout a bounded sequence (bullpen usage
is a Phase 5D concern). D3 is loaded and reproduced exactly — not retrained, not modified. One
2025 game is `PARTICIPANT_REPLAY_INCOMPLETE`.

## 19. Monte Carlo Entry Decision

**`MONTE_CARLO_ENTRY_GATES_PASSED`.** All gates satisfied: replay engine READY, transition
model READY, D3 exact reproduction, probability validation, participant replay sufficient,
initialization valid, short-sequence integration legal, reproducibility, authority pinning, no
state corruption, viable computation plan.

## 20. Exact Phase 5D Next Step

Run the **first whole-game Monte Carlo** on the unchanged proven kernel + this input layer:
initialize each eligible historical game, sample its PAs through the D3 provider and the
base-out transition model over the deterministic kernel with the controlled RNG lineage, then a
**historical game-level backtest** (reconstructed vs actual final-score / total distributions —
diagnostic reconciliation only, no win/run-line/total probabilities and no betting). Game
calibration, residual layer, prospective participation feed, premium contact-quality, and ASP
export remain lower-priority and NOT_CONFIGURED.
