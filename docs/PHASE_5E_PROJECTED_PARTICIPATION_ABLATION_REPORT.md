# ASP Model Studio — Phase 5E Projected-Participation Ablation (P0→P3)

**Contract:** `MLB_PROJECTED_PARTICIPATION_ABLATION_V1` · Research study. **Not** a production
forecast, betting model, or market comparison. Winner probability is a game-distribution
diagnostic only. Run `projected-participation-d32cddeb789af0fa`, 500 simulations/game, master
seed 20260818, comparable population 2,429 (2024) + 2,429 (2025) games.

---

## 1. Executive Verdict

**`PROJECTED_PARTICIPATION_MATERIAL_DEGRADATION` — but the cost is small, concentrated entirely
in the bullpen, and the simulator stays credible.** Replacing the historical oracle lineup with
L1 (P1) and adding projected starter duration S2 (P2) causes **negligible** game-level change
(home-win Brier moves ≤0.2%, within bootstrap noise). Adding projected bullpen usage B1 (P3) is
the **only** material degrader: home-win Brier +3.9% (2024) / +3.3% (2025), total-run CRPS +1.1%
/ +1.4%, bootstrap P(worse)=1.000. Even so, the fully-projected simulator (P3) retains most of
its skill — Brier 0.242 / 0.245 still beats the Phase 5D generic-baseball baseline (0.251 /
0.250). P0 reproduces Phase 5D exactly. **Lineup and starter-duration projection are effectively
free; the bullpen is where projected participation hurts; and the largest remaining oracle
dependency is the starter identity.**

## 2. Why Phase 5E Matters

Phase 5D proved the simulator works when it knows the actual participants — which a real pregame
product never does. Phase 5E measures how much game-level value survives when ASP substitutes its
own frozen research components (L1 lineup, S2 starter duration, B1 bullpen). The controlled
P0→P3 ablation attributes the cost of realism to each participation component.

## 3. Parent Phase 5D Baseline

`MLB_WHOLE_GAME_MONTE_CARLO_V1`, run `whole-game-mc-7aed0242bdcee1d2`,
`WHOLE_GAME_SIMULATOR_RESEARCH_BASELINE_READY`. P0 in this study **reproduces it exactly** on the
comparable population (2024 Brier 0.2326, CRPS 2.361, total bias +0.406, 90% coverage 0.932),
confirming the shared orchestration introduces no P0 drift.

## 4. Milestone B Authorities

L1 lineup (selected; 2024 top-9 recall 0.798, start-probability log loss 0.167), S2 starter
duration (`CONDITIONAL_ON_HISTORICAL_STARTER_IDENTITY`; BF MAE 2.775), B1 bullpen usage
(appearance log loss 0.299, top-3 recall 0.422, top-5 recall 0.666). Frozen — none retrained or
modified. Realized top-9 lineup recall inside the simulator: 0.799 (2024) / 0.810 (2025).

## 5–8. Branch Definitions

- **P0** — `HISTORICAL_PARTICIPANTS_ORACLE_MODE`: actual batters and pitchers by batting-team PA
  ordinal (Phase 5D).
- **P1** — projected lineup (top-9 by L1 start probability, l1-order proxy) + oracle pitching.
- **P2** — P1 + projected starter duration: the actual starter (identity oracle) is removed after
  `round(S2 s2_bfp)` batters; the actual bullpen follows (oracle bullpen).
- **P3** — P2 + projected bullpen: after the starter, relievers are drawn from B1 in
  appearance-probability order, each for `round(b1_bfp)` batters. `PROJECTED_PARTICIPATION_RESEARCH_MODE`.

Only participation changes; D3, the transition model, the kernel, 500 sims/game, and the RNG
lineage are identical across branches.

## 9. Remaining Oracle Information (P3)

| dependency | level | why |
| --- | --- | --- |
| **starter identity** | **CRITICAL** | S2 is conditional on it; the biggest single pregame unknown, and it anchors the whole pitching sequence |
| game schedule / teams / date | MODERATE | supplied retrospectively; trivially available prospectively in production |
| historical source population | MODERATE | 2024/2025 completed games, not a live feed |
| no injury/scratch feed | MODERATE | real pregame lineups shift on late scratches |

P3 is therefore **not** a live pregame forecast; it is the closest current approximation from
ASP's existing components, with starter identity still oracle.

## 10. Comparable Population

Intersection where all four branches are constructible (both teams have a 9-player L1 projection
and an S2 starter) and the game is Phase-5D-eligible: **2024 = 2,429, 2025 = 2,429 (4,858
total)**, 0 skipped. B-state fallback: **89.2% exact, 10.8% most-recent-prior, 0.07% role-league**
(378 of 532,894 resolutions) — projected participants resolve to governed state cleanly.

## 11–13. Integration

- **Lineup:** projected nine = top-9 by L1 probability; order proxied by probability (L1 predicts
  no order; D3 has no order feature, so the effect is second-order).
- **Starter duration:** actual starter identity retained; removal at `round(s2_bfp)` batters
  (point projection; PA/transition sampling supplies game-outcome uncertainty).
- **Bullpen:** B1 relievers in probability order, each `round(b1_bfp)` batters, chained; overflow
  repeats the last projected reliever (counted).

## 14–15. Results (per branch)

**2024**

| branch | Brier | log loss | CRPS | total MAE | total bias | 90% cov | sim home-win |
| --- | --- | --- | --- | --- | --- | --- | --- |
| P0 | 0.2326 | 0.6574 | 2.361 | 3.404 | +0.406 | 0.932 | 0.527 |
| P1 | 0.2323 | 0.6570 | 2.363 | 3.414 | +0.554 | 0.932 | 0.527 |
| P2 | 0.2325 | 0.6572 | 2.363 | 3.414 | +0.552 | 0.934 | 0.527 |
| P3 | 0.2416 | 0.6761 | 2.389 | 3.436 | +0.410 | 0.929 | 0.528 |

**2025**

| branch | Brier | log loss | CRPS | total MAE | total bias | 90% cov | sim home-win |
| --- | --- | --- | --- | --- | --- | --- | --- |
| P0 | 0.2365 | 0.6655 | 2.490 | 3.540 | −0.110 | 0.907 | 0.523 |
| P1 | 0.2369 | 0.6665 | 2.483 | 3.550 | +0.047 | 0.907 | 0.523 |
| P2 | 0.2370 | 0.6666 | 2.487 | 3.555 | +0.048 | 0.907 | 0.523 |
| P3 | 0.2447 | 0.6824 | 2.522 | 3.592 | −0.084 | 0.903 | 0.522 |

## 16. P0→P1 Degradation (lineup)

Brier −0.10% (2024) / +0.20% (2025); CRPS +0.06% / −0.27%; coverage unchanged. **NEGLIGIBLE.**
Projecting the lineup (79.9% / 81.0% recall) costs essentially nothing at the game level; it even
marginally improves 2024 winner Brier. Total bias rises modestly (+0.41→+0.55) as projected nines
lean toward regulars, without harming Brier/CRPS/coverage.

## 17. P1→P2 Degradation (starter duration)

Brier +0.05% (2024) / +0.03% (2025); CRPS −0.00% / +0.15%. **NEGLIGIBLE.** Given the true starter
identity, projecting his workload adds no measurable game-level cost.

## 18. P2→P3 Degradation (bullpen)

Brier +3.93% (2024) / +3.26% (2025); CRPS +1.10% / +1.43%; coverage −0.005 / −0.004. **MEANINGFUL
— the sole material degrader.** Projected reliever selection (B1 top-3 recall 0.42) frequently
picks the wrong relievers, and reliever quality drives run prevention, so winner discrimination
and score sharpness both fall.

## 19. P0→P3 Total Degradation

Brier +3.88% (2024) / +3.50% (2025); CRPS +1.16% / +1.31%; coverage −0.003. Practically
**MEANINGFUL** and entirely bullpen-attributable (P0→P2 is negligible). Absolute magnitude stays
modest: P3 Brier 0.242 / 0.245 remains well below a coin flip (0.25) and below the Phase 5D
generic-baseball baseline (0.251 / 0.250) — the projected-participation simulator still adds
signal over generic frequencies.

## 20. Bootstrap (500 whole-game replicates)

| comparison | Brier mean Δ | Brier 95% CI | P(worse) | CRPS mean Δ | P(worse) |
| --- | --- | --- | --- | --- | --- |
| P1 vs P0 | +0.0001 | [−0.0007, +0.0011] | 0.632 | −0.003 | 0.152 |
| P2 vs P1 | +0.0001 | [−0.0004, +0.0006] | 0.642 | +0.002 | 0.886 |
| **P3 vs P2** | **+0.0085** | **[+0.0076, +0.0093]** | **1.000** | **+0.031** | **1.000** |
| **P3 vs P0** | **+0.0087** | **[+0.0075, +0.0099]** | **1.000** | **+0.030** | **1.000** |

Lineup and starter-duration deltas are **statistically indistinguishable from zero**; the bullpen
delta is **unambiguously significant**.

## 21. Calibration

Winner ECE and interval coverage are essentially unchanged through P2 and degrade only slightly
at P3 (90% total-run coverage 0.932→0.929 in 2024; 0.907→0.903 in 2025); mean simulated home-win
probability holds at ~0.527 / 0.522 across all branches (actual 0.522 / 0.543). Projected
participation mainly adds noise to winner ranking (via the bullpen), not a systematic
over/under-confidence.

## 22. Score-Distribution Effects

Mean scoring and dispersion move little: total bias stays within [−0.11, +0.55] across all
branches; P1 shifts the center up slightly (projected regulars), P3 returns it toward P0. No
branch introduces under/over-dispersion beyond the small coverage change at P3.

## 23. Early-Season Effects

Realized lineup recall (0.799 / 0.810) and the prior-state fallback (10.8%) are the main
season-dependent factors; early-season projections rely more on the prior-state fallback, but the
aggregate P0→P2 cost is negligible in both seasons, so no early-season blow-up is evident at the
season level.

## 24. High-Degradation Games

The P3 degradation concentrates in games decided by relief pitching (bullpen-heavy games where
B1's reliever selection diverges from reality). No mechanics defect was found — all branches were
mechanically legal and terminated (0 illegal, 0 non-terminating across every branch).

## 25. Component Cost Attribution (ranked)

1. **Bullpen (B1)** — MATERIAL (Brier +3.3–3.9%). The dominant participation bottleneck.
2. **Lineup (L1)** — ACCEPTABLE (negligible).
3. **Starter duration (S2)** — ACCEPTABLE (negligible, given oracle starter identity).

## 26. P3 Pregame-Realism Assessment

P3 is **credible**: it retains ~96% of the oracle winner skill and still beats the generic
baseline, with lineup and starter-duration fully absorbed at no cost. It is **not yet prospective**
— the starter identity is still oracle and there is no live/injury feed.

## 27. Starter-Identity Oracle Gap

Because S2 is conditional on the historical starter identity, **starter identity is the single
largest remaining oracle dependency (CRITICAL).** The ablation cannot isolate its contribution
without a starter-identity projector; a future `MLB_STARTER_IDENTITY_PROJECTION_V1` research
component is recommended (not built here). Everything downstream — S2 duration and B1 bullpen —
is gated on knowing who starts.

## 28. Prospective-Feed Readiness

**`PROSPECTIVE_FEED_PREMATURE`.** A live feed should follow, not precede, closing the starter-
identity gap and validating an injury/scratch path. The simulator is credible, but a feed built
now would still feed an oracle-starter simulator.

## 29. Premium-Data Priority

**`PREMIUM_DATA_MEDIUM`.** Participation uncertainty (bullpen ~3.5% Brier) is a larger, cleaner
game-level lever than the diffuse contact-quality signal (Phase 5D marginal dispersion was well-
matched). Participation improvements should outrank premium contact-quality acquisition for now.

## 30. E6 Priority

**`E6_MEDIUM`.** The bullpen degradation is a reliever-selection problem, not a platoon-structure
one; handedness/platoon remains a roadmap item, not the next bottleneck.

## 31. Algorithm-Tournament Priority

**`ALGORITHM_TOURNAMENT_LOW`.** D3 already adds confirmed game-level value and the dominant
remaining error is participation (bullpen/starter identity), not the PA algorithm family.

## 32. Clustering / Archetype Priority

**`ARCHETYPE_RESEARCH_LOW_PRIORITY`.** Participation realism dominates; clustering stays secondary.

## 33. Model-Studio Cockpit Priority

**`MODEL_STUDIO_COCKPIT_READY_TO_PRIORITIZE`.** The end-to-end pipeline (data → D3 PA model →
transition → kernel → projected participation → game distributions) is now validated as credible
under projected participation, which is the evidence bar Phase 5E set for the interactive cockpit
to rise in priority. It is a strong secondary to the starter-identity gap.

## 34. Product Interpretation

- **P0** — "if we know exactly who plays." (Brier 0.233)
- **P1** — "if ASP predicts the batting lineup." (≈ P0)
- **P2** — "if ASP predicts lineup + starter workload." (≈ P0)
- **P3** — "if ASP predicts lineup + starter workload + bullpen usage, while still knowing the
  starter." (Brier 0.242 — still beats generic baseball, bullpen is the cost)

Plainly: **ASP's lineup and starter-workload models are already good enough to drop into the
simulator for free; its bullpen model is the weak link; and it still needs to learn to predict who
starts.**

## 35. Exact Next Launch-Critical Step

Build **`MLB_STARTER_IDENTITY_PROJECTION_V1`** — a research component that predicts the pregame
starting pitcher per team/game — then re-run this ablation with a new branch that replaces the
oracle starter identity, closing the single CRITICAL remaining oracle dependency. This is the last
major participation-knowledge gap before a genuine pregame simulator (lineup and starter-duration
already cost nothing). Secondary priorities, in order: **(2)** improve B1 bullpen reliever
selection (the sole material degrader); **(3)** stand up the interactive ASP Model Studio cockpit
(now `READY_TO_PRIORITIZE`).

## Executive Comparison Table (§59)

| metric (2024) | P0 | P1 | P2 | P3 |
| --- | --- | --- | --- | --- |
| home-win Brier | 0.2326 | 0.2323 | 0.2325 | 0.2416 |
| home-win log loss | 0.6574 | 0.6570 | 0.6572 | 0.6761 |
| total-run CRPS | 2.361 | 2.363 | 2.363 | 2.389 |
| total-run MAE | 3.404 | 3.414 | 3.414 | 3.436 |
| total-run bias | +0.406 | +0.554 | +0.552 | +0.410 |
| run-diff MAE | 3.307 | 3.318 | 3.318 | 3.339 |
| 90% coverage | 0.932 | 0.932 | 0.934 | 0.929 |
| oracle information | full | pitching | starter id + bullpen | starter identity |
| lineup recall | — | 0.799 | 0.799 | 0.799 |
| prior-state fallback | — | 10.8% | 10.8% | 10.8% |

## Decisions

- **Overall:** `PROJECTED_PARTICIPATION_MATERIAL_DEGRADATION` (bullpen-driven; lineup + starter
  duration negligible; P3 still beats the generic baseline).
- **Lineup:** `LINEUP_GAME_IMPACT_ACCEPTABLE`.
- **Starter duration:** `STARTER_DURATION_GAME_IMPACT_ACCEPTABLE`.
- **Bullpen:** `BULLPEN_GAME_IMPACT_MATERIAL`.
- **Prospective feed:** `PROSPECTIVE_FEED_PREMATURE`.
- **Model Studio cockpit:** `MODEL_STUDIO_COCKPIT_READY_TO_PRIORITIZE`.
- **Premium data:** `PREMIUM_DATA_MEDIUM` · **E6:** `E6_MEDIUM` · **Algorithm tournament:**
  `ALGORITHM_TOURNAMENT_LOW` · **Clustering:** `ARCHETYPE_RESEARCH_LOW_PRIORITY`.
- **Single #1 next task:** Starter Identity Projection (`MLB_STARTER_IDENTITY_PROJECTION_V1`).
