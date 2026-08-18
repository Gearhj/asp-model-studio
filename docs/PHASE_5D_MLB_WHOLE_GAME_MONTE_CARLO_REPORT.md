# ASP Model Studio — Phase 5D First Whole-Game Monte Carlo + Historical Game-Level Backtest

**Contract:** `MLB_WHOLE_GAME_MONTE_CARLO_V1` · Research simulation component under
`HISTORICAL_PARTICIPANTS_ORACLE_MODE`. **Not** a production forecast, betting model, live
prediction engine, or market comparison. Winner probability is a game-distribution diagnostic
only. Run `whole-game-mc-7aed0242bdcee1d2`, 500 simulations/game, master seed 20260818.

---

## 1. Executive Verdict

**`WHOLE_GAME_SIMULATOR_RESEARCH_BASELINE_READY`.** Combining actual historical participants
(oracle), the frozen D3 PA-outcome provider, the Phase 5B empirical transition model, and the
proven kernel produces whole-game score distributions that resemble actual MLB games well: total
runs are nearly unbiased (2024 +0.41, 2025 −0.11 runs), dispersion is well-shaped (simulated/
actual total-run std ratio 1.02 / 0.94), prediction intervals are close to nominal (90% coverage
93.2% / 90.7%), and the simulator's home-win rate matches reality (0.527 vs 0.522 actual in 2024;
0.523 vs 0.543 in 2025). All 4,859 games × 500 simulations were mechanically legal (**0 illegal
states, 0 non-terminating games**) and reproducible under seed. Critically, **D3 adds genuine
game-level value over a generic-baseball baseline in both seasons** (`D3_GAME_LEVEL_VALUE_
CONFIRMED`): lower winner Brier, lower log loss, and lower total-run CRPS than G0. This is a
credible oracle upper-bound baseline; the single highest-value next step is projected-participation
integration.

## 2. Why Phase 5D Matters

This is the first genuine game-level probabilistic validation. It answers whether the proven PA +
transition + kernel stack, given the correct historical participants, yields whole-game
distributions good enough to justify building a prospective forecasting simulator. The answer is
yes — under oracle participation.

## 3. Parent Authorities

`MLB_GAME_REPLAY_ENGINE_V1` (READY), `MLB_BASE_OUT_TRANSITION_MODEL_V1` (READY, model SHA
`4f312af6…3459e4`), `D3_PROBABILISTIC_PA_PROVIDER_V1` (READY), `MLB_HISTORICAL_PARTICIPANT_
REPLAY_PROVIDER_V1` (READY), `MLB_GAME_INITIALIZATION_CONTRACT_V1` (READY), Phase 5C entry gates
`MONTE_CARLO_ENTRY_GATES_PASSED`. None retrained or modified. The whole-game engine decomposes the
D3 multinomial-logistic predictor for speed but reproduces the governed softmax to machine
precision (max abs difference 3.9e-16 vs the provider).

## 4. Oracle Participant Limitation

**Prominent, not hidden.** Participants are keyed to the batting team's plate-appearance ordinal
from the actual game — the k-th time a team bats it faces the batter/pitcher it actually faced on
its k-th PA (replaying the real order, substitutions, and pitcher changes by PA ordinal); beyond
history the order continues from the starting nine and the last actual pitcher is retained. Actual
substitutions/pitcher changes occurred partly in reaction to the real game state, so this is an
**oracle upper bound**, likely optimistic relative to prospective participation. Phase 5D
performance therefore reflects **simulator + PA + transition quality under oracle participation**,
not deployable pregame quality.

## 5. Monte Carlo Contract

See `docs/contracts/MLB_WHOLE_GAME_MONTE_CARLO_V1.md`. Per simulation: initialize (inning 1, top,
0 outs, bases empty, 0-0); resolve oracle batter/pitcher; D3 eight-class PA probability; sample PA
outcome; Phase 5B transition distribution; sample legal transition; apply through the kernel
semantics; advance batting order; MLB terminal rules (home skips the bottom when leading after a
regulation top; walk-off; extras with the automatic runner on second); 200-PA watchdog. Aggregate
outputs only — no per-PA persistence.

## 6. RNG / Reproducibility

One lineage per game (master seed → `SHA-256(game_id)` → independent PA-sample and transition
generators; fixed-size per-step draws). Same seed + authorities + game reproduces the identical
sample; a different seed diverges. Verified in tests and across reruns.

## 7. Pilot Convergence

Stratified 200-game pilot (100/season across month and actual-total). Drift is negligible by 500
simulations:

| sims/game | mean total | home-win prob | total CRPS | Δ total vs prev | Δ home-win | Δ CRPS |
| --- | --- | --- | --- | --- | --- | --- |
| 100 | 8.978 | 0.5295 | 2.536 | — | — | — |
| 250 | 8.953 | 0.5346 | 2.500 | 0.025 | 0.0051 | 0.036 |
| 500 | 8.949 | 0.5308 | 2.477 | 0.0033 | 0.0038 | 0.0235 |
| 1000 | 8.958 | 0.5325 | 2.475 | 0.0083 | 0.0018 | 0.0018 |

500→1000 moves mean total by 0.008 runs, home-win by 0.0018, CRPS by 0.0018 — all negligible.
**Development standard = 500 simulations/game** (§81). 0 illegal / 0 non-terminating at every count.

## 8. Compute Performance

~4.4 games/second at 500 sims (≈2,200 game-simulations/second). D3 logit evaluation is the main
cost; the decomposed predictor plus lockstep batching makes it tractable. One game ×1,000 sims
would be ~0.45 s. Memory is modest (per-game contribution arrays discarded after each game); the
persisted artifact is a single aggregate JSON.

## 9. Full Historical Population

Eligible and simulated: **2024 = 2,429 games, 2025 = 2,430 games (4,859 total)**, 0 skipped. Each
at 500 simulations. Full G1 backtest ≈18 min; G0 baseline ≈14 min.

## 10. Simulation Legality

Across all 4,859 games × 500 simulations (plus the pilot's convergence sweep with per-PA legality
checking): **0 illegal states, 0 duplicated/lost runners, 0 non-terminating games, 0 watchdog
triggers, 0 exceptions.** Transition legality is guaranteed by the Phase 5B model (illegal mass 0)
and confirmed by the pilot's per-PA `is_legal` audit.

## 11. Actual vs Simulated Scoring

| | 2024 | 2025 |
| --- | --- | --- |
| actual runs/team | 4.39 | 4.45 |
| simulated runs/team | 4.60 | 4.39 |
| actual mean total | 8.79 | 8.90 |
| simulated mean total | 9.19 | 8.79 |
| **total-run bias** | **+0.41** | **−0.11** |
| total-run MAE | 3.40 | 3.54 |
| total-run RMSE | 4.25 | 4.51 |

Mean scoring is close and the small bias flips sign across seasons — no strong systematic
scoring error.

## 12. Home / Away Scoring

2024 away bias +0.17, home bias +0.24; 2025 away bias −0.01, home bias −0.10. The modest 2024
positive total bias is split roughly evenly between home and away, not concentrated on one side.

## 13. Total Runs

Total-run bias +0.41 (2024) / −0.11 (2025); MAE 3.40 / 3.54; RMSE 4.25 / 4.51. The large MAE
relative to the small bias reflects genuine game-to-game variance the simulator cannot anticipate
per game (it does not know which specific game will be a blowout or a pitchers' duel), not a
centering error.

## 14. Run Differential

Run-differential MAE 3.31 (2024) / 3.43 (2025); bias +0.06 / −0.09 (essentially unbiased); RMSE
4.26 / 4.46.

## 15. CRPS / Distributional Accuracy

Total-run CRPS **2.361** (2024) / **2.489** (2025) — computed with the fair empirical estimator
(`E|X−y| − ½E|X−X′|`, sorted identity, validated against a brute-force reference). Away-runs CRPS
1.68 / 1.77; home-runs CRPS 1.61 / 1.66. D3 beats the G0 baseline on total-run CRPS in both
seasons (§28).

## 16. Prediction-Interval Coverage (total runs)

| nominal | 2024 observed | 2025 observed | mean width (2024) |
| --- | --- | --- | --- |
| 50% | 56.1% | 55.8% | 5.8 |
| 80% | 84.3% | 82.8% | 11.0 |
| 90% | 93.2% | 90.7% | 14.0 |
| 95% | 96.2% | 94.5% | 16.6 |

Coverage is close to nominal — slightly conservative (intervals a touch wide) in 2024, near-exact
in 2025. This is strong distributional calibration and the authoritative dispersion diagnostic:
the per-game predictive distributions are neither meaningfully under- nor over-dispersed.

## 17. Winner Probability (diagnostic only)

Home-win Brier **0.2326** (2024) / **0.2364** (2025); log loss 0.657 / 0.665. Both beat a
coin-flip and beat the base-rate baseline (§28). This is a game-distribution diagnostic — **no
moneyline, run-line, total, closing odds, CLV, edge, or ROI** were retrieved or computed.

## 18. Winner Calibration

ECE 0.053 (2024) / 0.035 (2025). Simulator-favorite bands (own probability only) are monotonic
and directionally well-calibrated but somewhat under-confident:

| sim-favorite band | 2024 observed fav-win | 2025 observed fav-win |
| --- | --- | --- |
| 0.50–0.55 | 0.512 | 0.523 |
| 0.55–0.60 | 0.603 | 0.631 |
| 0.60–0.65 | 0.711 | 0.660 |
| 0.65–0.70 | 0.761 | 0.746 |
| 0.70+ | 0.813 | 0.848 |

The simulator's stronger favorites win more often than it predicts — headroom for sharpness, not a
calibration failure.

## 19. Home-Field Sanity

Actual home-win rate 0.522 (2024) / 0.543 (2025); simulated 0.527 / 0.523. 2024 matches almost
exactly; 2025 slightly understates home advantage (−0.020). Home scoring is not systematically
inflated. No home-field correction was added (§61).

## 20. Score Bias

Total-run residual (simulated mean − actual): mean +0.41 / −0.11; run-differential residual mean
+0.06 / −0.09. The simulator is neither consistently high nor low across seasons, and neither
compressed nor dispersed at the margin.

## 21. Distribution Shape

Simulated predictive-marginal std (law of total variance) vs actual total-run std: **4.40 vs 4.31
(ratio 1.02, 2024)**, **4.30 vs 4.59 (ratio 0.94, 2025)**. Both classify **`WELL_SHAPED`**. Actual
total P99 = 21 (2024) / 22 (2025); the matched marginal std indicates the upper tail is reasonably
represented.

## 22. Temporal Stability

Results are stable across 2024 and 2025: total bias small and sign-flipping, CRPS 2.36 vs 2.49,
winner Brier 0.233 vs 0.236, coverage close to nominal in both, D3 value confirmed in both. No
season-specific failure. No corrections were tuned on 2025 (§60).

## 23. Extra Innings

The engine samples extra innings with the automatic runner on second at each half start beyond
regulation and always terminates (0 non-terminating across 2.4M game-simulations; watchdog never
triggered). Simulated extra-inning games occur and resolve legally.

## 24. Starter/Bullpen Diagnostics

Not decomposed further here: under oracle mode the pitcher faced at each batting-team PA ordinal is
the actual one, so bullpen usage is replayed by ordinal. Prospective bullpen realism is a Phase 5E
concern, not a Phase 5D defect. (Retrospective bullpen-heavy segmentation deferred to avoid
low-value post-outcome slicing.)

## 25. Score-Tail Diagnostics

The simulated marginal matches actual dispersion (ratio 1.02 / 0.94) and covers the 95% interval
(96.2% / 94.5%), so the game-level tails are not systematically too light or too heavy. What the
simulator cannot do is anticipate *which specific game* lands in the tail (see §27).

## 26. Contact-Quality Hypothesis

Phase 4F found severe PA misses dominated by HR/DOUBLE/TRIPLE/OTHER_REACH predicted as BIP_OUT, and
raised premium contact-quality priority. **At the game level that weakness is muted:** marginal
dispersion is well-matched, interval coverage is near-nominal, and the upper tail is covered. The
simulator does **not** systematically under-disperse or under-cover high-scoring games at the
margin. It does under-predict games that actually finished ≥12 total runs (retrospective bias −5.4
/ −6.2), but that is regression to the mean (§27), not marginal tail-miss. **Premium contact-quality
priority is therefore `MEDIUM` — the game-level evidence is weaker than the PA-level Phase 4F signal
implied**, and does not by itself justify raising premium data to top priority.

## 27. Game-Level Error Concentration

Worst 1% of games carry ~5% of total-run CRPS, worst 10% ~27–29%, worst 20% ~43–46% — moderately
concentrated, not extreme. Error is broad, driven by inherent per-game variance. Segmenting by
actual total (RETROSPECTIVE_DIAGNOSTIC_ONLY): ≤5-run games over-predicted by ~+5, 6–8 by ~+2, 9–11
near zero, 12+ under-predicted by ~−5 to −6. This fan pattern is **regression to the league mean**:
the simulator predicts near-average for every game because, given participants alone, it cannot
know a specific game's realized scoring environment. It is largely irreducible under this design
and is not a centering or dispersion defect (the marginal and coverage are correct).

## 28. Internal Baseline Comparison (G0 vs G1)

G0 = the same kernel/transitions/oracle participants driven by a fixed league-average (2023)
eight-class PA distribution; G1 = D3-driven. Same games, same simulation count.

| metric | G0 2024 | **G1 2024** | G0 2025 | **G1 2025** |
| --- | --- | --- | --- | --- |
| winner Brier | 0.2510 | **0.2326** | 0.2501 | **0.2364** |
| winner log loss | 0.695 | **0.657** | 0.693 | **0.665** |
| total-run CRPS | 2.408 | **2.361** | 2.545 | **2.489** |
| run-diff MAE | 3.536 | **3.307** | 3.608 | **3.429** |

D3 beats the generic-baseball baseline on every metric in both seasons.

## 29. D3 Game-Level Value

**`D3_GAME_LEVEL_VALUE_CONFIRMED`.** D3's batter/pitcher cumulative state propagates into
measurably better whole-game winner and score-distribution accuracy than generic baseball
frequencies. This is separate from and complements D3's PA-level challenger status; D3 is not
promoted on this study alone (§44).

## 30. Compute Readiness

**`REALTIME_SLATE_READY`.** One game ×500 sims ≈0.23 s; a 15-game slate ×500 ≈3–4 s; full 2024
season ≈9 min; full 2025 ≈9 min; full 2024–25 backtest ≈18 min (G1). Runtime shares: D3 logits
dominate, transition sampling and kernel updates are cheap. A live slate simulates in seconds; no
optimization is required at this stage.

## 31. Product Interpretation

The simulator currently knows well: **aggregate scoring level, run dispersion, and home-win rate**
— i.e. the shape of the total-runs and run-differential distributions and the balance of a game.
It knows poorly: **which specific game will be extreme** (game-conditional scoring environment).
Architecturally, a totals market would lean on the (well-shaped) total-run distribution, a run-line
market on the (unbiased, well-covered) run-differential distribution, and a moneyline on the
(calibrated but under-confident) winner distribution; player-prop markets would require player-level
outputs the current aggregate engine does not emit. **No betting probabilities against any lines
were computed.**

## 32. Prospective Gaps

To become a true pregame simulator (ranked by launch criticality): (1) confirmed/projected lineup
feed; (2) probable-starter feed; (3) bullpen availability/workload; (4) injuries/scratches; (5)
current player-state refresh; (6) game-time park/weather where relevant; (7) premium contact-quality
if later justified; (8) model bundle/export; (9) prospective monitoring. None built here.

## 33. Live-Update Architecture Note

Documented, not implemented: a future in-game update path is game-state change → resolve current
batter/pitcher → rescore D3 (or the future PA provider) → sample the transition distribution →
re-run remaining-game simulations from the current state. That is how, e.g., a first-inning pitcher
removal would update the forecast. No live feeds or in-game orchestration exist.

## 34. Failure Register

| weakness | Impact | Repeatability 24/25 | Pregame detectability | Data availability | Ease of correction | Launch relevance |
| --- | --- | --- | --- | --- | --- | --- |
| cannot anticipate game-specific scoring environment (regression to mean) | 3 | 5 | 2 | 2 | 2 | 3 |
| winner under-confidence on strong favorites | 2 | 5 | 4 | 4 | 3 | 3 |
| 2025 slight home-advantage understatement | 2 | 2 | 3 | 4 | 4 | 2 |
| 2024 slight positive total-run bias | 2 | 2 | 3 | 4 | 4 | 2 |
| oracle participation optimism (no prospective participants) | 5 | 5 | 5 | 4 | 3 | 5 |

The dominant launch-relevant gap is **prospective participation** (oracle optimism), not a
mechanics, calibration, or scoring defect.

## 35. Simulator Readiness Decision

**`WHOLE_GAME_SIMULATOR_RESEARCH_BASELINE_READY`.** All criteria met: every simulation mechanically
legal; reproducible; acceptable termination; stable Monte Carlo convergence; score distributions
realistic (well-shaped, near-nominal coverage); game-level metrics computed; temporally stable; clear
limitations; no hidden leakage beyond the explicitly labeled historical-oracle design. This is
**not** production-, betting-, live-, or AISP-export-ready.

## 36. Exact Phase 5E Recommendation

**Option A — Projected Participation Integration (single #1 priority).** Replace oracle participants
with the Milestone B lineup / starter-duration / bullpen-usage research components and re-run the
same backtest (P0 oracle → P1 lineup → P2 +starter → P3 +bullpen), measuring how much of the
credible oracle performance survives what ASP can actually know before a game. Rationale: the oracle
baseline is credible and D3 game-level value is confirmed, so the PA model is not the bottleneck; the
product cannot know actual participants prospectively; and the game-level contact-quality signal is
only MEDIUM. Secondary ranking: **B** premium contact-quality (raise only if projected participation
reveals tail/variance gaps traceable to contact quality) > **C** residual calibration (only a small,
stable bias exists; not worth a layer yet) > **E/F** improved PA model / E6 (D3 already adds value;
data/participation limits dominate) > **D** prospective live feed (follows model value, not before).
`PARTICIPATION_ABLATION_READY`.

## Executive Benchmark (§79)

| | 2024 | 2025 |
| --- | --- | --- |
| games | 2,429 | 2,430 |
| sims/game | 500 | 500 |
| actual runs/team | 4.39 | 4.45 |
| simulated runs/team | 4.60 | 4.39 |
| actual total runs | 8.79 | 8.90 |
| simulated total runs | 9.19 | 8.79 |
| total-run bias | +0.41 | −0.11 |
| total-run MAE | 3.40 | 3.54 |
| total-run RMSE | 4.25 | 4.51 |
| total-run CRPS | 2.361 | 2.489 |
| run-diff MAE | 3.31 | 3.43 |
| 50% coverage | 0.561 | 0.558 |
| 80% coverage | 0.843 | 0.828 |
| 90% coverage | 0.932 | 0.907 |
| 95% coverage | 0.962 | 0.945 |
| home-win Brier | 0.2326 | 0.2364 |
| home-win log loss | 0.657 | 0.665 |
| home-win ECE | 0.053 | 0.035 |
| actual home-win rate | 0.522 | 0.543 |
| mean simulated home-win prob | 0.527 | 0.523 |
| simulation legality failures | 0 | 0 |
| runtime | ~9 min | ~9 min |

## Baseline Value (§80)

| metric | G0 (generic) 2024 | G1 (D3) 2024 | G0 2025 | G1 2025 |
| --- | --- | --- | --- | --- |
| winner Brier | 0.2510 | **0.2326** | 0.2501 | **0.2364** |
| winner log loss | 0.6951 | **0.6574** | 0.6934 | **0.6655** |
| total-run CRPS | 2.408 | **2.361** | 2.545 | **2.489** |
| run-diff MAE | 3.536 | **3.307** | 3.608 | **3.429** |

## Executive Questions (§63)

1. **Legal and reproducible?** Yes — 0 illegal / 0 non-terminating over 2.4M game-sims; seed-reproducible.
2. **Sims/game needed?** 500 (drift to 1000 negligible).
3. **Scoring match?** Close — total bias +0.41 / −0.11; well-shaped dispersion.
4. **Systematically high/low?** No — small, sign-flipping bias.
5. **Variance too narrow/wide?** Well-matched (std ratio 1.02 / 0.94); coverage near nominal.
6. **Upper tails captured?** Yes at the margin (95% coverage 96% / 95%; matched marginal std).
7. **Total-runs CRPS?** 2.361 (2024) / 2.489 (2025).
8. **Run-differential error?** MAE 3.31 / 3.43, essentially unbiased.
9. **Intervals calibrated?** Yes — 50/80/90/95 close to nominal.
10. **Home-winner Brier?** 0.2326 / 0.2364.
11. **Home-winner log loss?** 0.657 / 0.665.
12. **Home-win calibrated?** Yes at aggregate; slightly under-confident on strong favorites.
13. **D3 game-level value over baseline?** Yes — confirmed on all metrics, both seasons.
14. **Stable 2024↔2025?** Yes.
15. **Errors concentrated?** Broad — worst 10% ≈27–29% of CRPS.
16. **High-scoring/contact games dominate residuals?** No dominance at the margin; 12+ under-prediction is retrospective regression.
17. **Premium contact-quality priority rise?** No — stays MEDIUM; game-level evidence weaker than PA-level.
18. **Projected-participation integration justified?** Yes — it is the #1 next step.
19. **Research baseline ready?** Yes — `WHOLE_GAME_SIMULATOR_RESEARCH_BASELINE_READY`.
20. **Single highest-value Phase 5E task?** Projected participation integration (Option A).
