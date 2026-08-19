# ASP Model Studio — Phase 5F Starter-Identity Projection + Q0→Q1 Simulator Impact

**Contract:** `MLB_STARTER_IDENTITY_PROJECTION_V1` · Research component. **Not** a production
forecast, betting model, or market comparison. Winner probability is a game-distribution
diagnostic only. Run `starter-identity-e098ded7945ff563`, dev 2021–2023, 500 sims/game.

---

## 1. Executive Verdict

**Starter identity is now projected, and it is cheap.** The candidate-ranking model predicts the
starting pitcher from prior-date rotation cadence alone at **top-1 0.705 (2024) / 0.717 (2025)**
(top-3 0.88, MRR 0.80), beating the best rotation baseline (0.68). Replacing the oracle starter
identity with the projection inside the whole-game simulator costs almost nothing:
**`STARTER_IDENTITY_PROJECTION_ACCEPTABLE`** — home-win Brier +1.04% (2024) / +0.33% (2025),
total-run CRPS +0.45% / +0.02%. A mispredicted starter is almost always a similar-quality
rotation-mate, so a wrong pick moves game-level Brier by only ~0.004. With this, **all four
participation layers (lineup, starter identity, starter duration, bullpen) are projected** and
the fully-projected simulator (Q1 Brier 0.244 / 0.246) **still beats the generic-baseball baseline
(0.251)**: **`PREGAME_RESEARCH_SIMULATOR_READY`**. The last critical participation oracle is closed.

## 2. Why Starter Identity Matters

Phase 5E left starter identity as the single CRITICAL oracle: the simulator was still told who
actually started. A real pregame product never knows that. Phase 5F predicts it from prior
information and measures the exact game-level cost of not knowing.

## 3. Parent Authorities

`MLB_WHOLE_GAME_MONTE_CARLO_V1` (Phase 5E P3 = Q0 baseline), `D3_PROBABILISTIC_PA_PROVIDER_V1`,
`MLB_BASE_OUT_TRANSITION_MODEL_V1` (SHA `4f312af6…3459e4`), Milestone B L1/S2/B1 (frozen), FD1
dataset `sports-dataset-1b58d5d1def2c9b7`. None retrained or modified.

## 4. Target Population

Per team-game, the actual starter = the first pitcher (min play number) that team's pitching side
sends out (governed `play_transition`). 24,146 team-games built across 2021–2025; exactly one
starter each. Team-games with no prior evidence (season's first game) yield no pool and are
excluded (reported, not hidden).

## 5. Candidate Pool

Season-to-date starters ∪ prior-45-day starters — mean 9.1–9.2 candidates. **Coverage 92.6%
(2024) / 92.4% (2025)**; the ~7.5% pool-miss (debut starters, season openers, long-injury
returns) caps achievable top-1 and is reported as a critical metric. The actual starter is never
used to force pool inclusion.

## 6. Temporal Policy

Strictly prior-date features. No target-game starter label, same-game usage, or future
schedule/results. Doubleheaders handled without inventing order (each team-game scored on its own
prior history).

## 7. Features

Rotation-turn proximity (`-|team-games-since-last-start − 5|`), days-turn proximity, team-games
since last start, starts in prior 30 days, season-to-date starts, days since last appearance,
season start frequency, a rotation-rest-band indicator, and a recent-appearance indicator. No
injury status invented; no future schedule used.

## 8. Baselines

S0 most-overdue (top-1 0.645 / 0.650), S1 rotation-order (0.682 / 0.686), S2 start-frequency
(0.107 / 0.093). The model beats the best (S1) in both seasons.

## 9. Retained Model

`STARTER_IDENTITY_RESEARCH_COMPONENT` — a within-team-game candidate-ranking L2 logistic (fit on
2021–2023). It weights rotation-turn proximity and team-games-since-last-start most heavily, and
softmax-normalizes candidate scores within each team-game.

## 10. 2024 Results

Coverage 0.926, top-1 0.705 (0.761 on covered games), top-2 0.840, top-3 0.876, MRR 0.794, mean
9.2 candidates. Log loss 2.766 and Brier 0.441 are dominated by the ~7.5% pool-miss penalty.

## 11. 2025 Frozen Results

Coverage 0.924, top-1 0.717 (0.775 covered), top-2 0.847, top-3 0.882, MRR 0.802. Consistent with
2024 — no tuning on 2025.

## 12. Early-Season Results

Top-1 by month (2024 / 2025): Mar/Apr 0.675 / 0.688, May/Jun 0.764 / 0.763, Jul/Aug 0.682 / 0.714,
Sep/Oct 0.662 / 0.656. Early season is modestly weaker (unsettled rotations) but not catastrophic;
September dips as rosters expand and rotations get irregular.

## 13. Rest-Day Results

Top-1 by team-games since last start (2024 / 2025): **5 → 0.981 / 0.988**, 4 → 0.155 / 0.115,
6 → 0.348 / 0.385, ≤3 → 0.083 / 0.061, 7+ → 0.055 / 0.073. The model **nearly perfectly recovers
the on-cadence rotation turn** (5 team-games); essentially all error is off-cadence starts (spot
starts, skipped turns, doubleheaders, openers, injury-shifted rotations) — exactly the
irreducible part.

## 14. Openers / Irregular Starts

For starts by low-frequency starters (< 10% season start rate — openers / bullpen games / spot
starts; ~1,100 per season), top-1 falls to 0.568 (2024) / 0.617 (2025). These are the genuinely
hard cases and drive most of the pool-miss and off-cadence error.

## 15. Calibration / Uncertainty

Per-game uncertainty (top probability, top1–top2 gap, entropy, candidate count) is retained for a
future uncertainty-sampling policy. Raw ranking quality (top-1/2/3, MRR) is the headline; no
calibration transform was added.

## 16–18. Simulator Integration (Q0 / Q1)

- **Q0** — Phase 5E P3 with `STARTER_IDENTITY_ORACLE`.
- **Q1** — P3 with the **top-1 projected** starter identity; starter duration bound to the
  projected identity (actual S2 when correct; the pitcher's own mean historical batters-faced
  otherwise, median fallback). Lineup (L1) and bullpen (B1) unchanged; D3, transition model,
  kernel, 500 sims/game, RNG lineage identical.

All projected starters resolved to canonical identity (0 missing); D3 state fallback 25.0%
prior-state, 0.09% role-league (higher prior-state share than P3 because projected starters/
lineups on off-dates use prior cumulative state more).

## 19. Comparable Population

2,429 (2024) + 2,429 (2025) comparable games — identical to the Phase 5E P3 population. Q0
reproduces Phase 5E P3 exactly (Brier 0.2416 / 0.2447).

## 20. Game-Level Results

| | Q0 2024 | Q1 2024 | Q0 2025 | Q1 2025 |
| --- | --- | --- | --- | --- |
| home-win Brier | 0.2416 | 0.2441 | 0.2447 | 0.2455 |
| total-run CRPS | 2.389 | 2.399 | 2.522 | 2.522 |
| total-run bias | +0.410 | +0.394 | −0.084 | −0.102 |
| 90% coverage | 0.929 | 0.928 | 0.903 | 0.900 |

## 21. Q1 Degradation

Home-win Brier **+1.04% (2024) / +0.33% (2025)**; total-run CRPS **+0.45% / +0.02%**; coverage
essentially unchanged. Classified **SMALL / NEGLIGIBLE → `STARTER_IDENTITY_PROJECTION_ACCEPTABLE`**.
The starter-correct rate is ~0.71 per team-start, yet the game-level cost is tiny.

## 22. Correct vs Incorrect Starter Games

Games where **both** starters were predicted correctly: Brier 0.2420 (2024) / 0.2435 (2025).
Games with **≥1 wrong** starter: 0.2464 / 0.2478. A wrong starter costs only **~0.004 Brier** —
because the mispredicted starter is almost always a rotation-mate of similar quality, so the D3
pitcher-state difference is small. This is the core reason starter-identity projection is cheap.

## 23. Bootstrap (500 whole-game replicates)

Q1 vs Q0 home-win Brier: mean Δ +0.0016, 95% CI [+0.0007, +0.0025], P(worse)=1.000 — a real but
tiny degradation. Total-run CRPS: mean Δ +0.0057, 95% CI [−0.0000, +0.0107], P(worse)=0.974 —
marginal. Statistically detectable, practically small.

## 24. Remaining Participation Oracle

With starter identity projected, the participation stack is **fully projected** (lineup, starter
identity, starter duration, bullpen). Remaining oracle/assumptions: game schedule / teams / date
(MODERATE — trivially available prospectively), historical source population (MODERATE), and no
injury/scratch or confirmed-lineup feed (MODERATE). No CRITICAL participation oracle remains.

## 25. Pregame Simulator Readiness

**`PREGAME_RESEARCH_SIMULATOR_READY`.** All participation layers projected; Q1 still beats the
generic baseline (0.244 / 0.246 < 0.251); all simulations legal; degradation tolerable; no hidden
historical-participation fallback beyond documented exceptions. This is RESEARCH readiness — not
production, betting, or live readiness (still a historical population, no live/injury feed).

Cumulative participation cost, oracle → full projection (2024 home-win Brier): P0 0.2326 → P3
0.2416 (bullpen-dominated, Phase 5E) → **Q1 0.2441** (+ starter identity). Total +4.9% Brier, of
which the bullpen is ~3.9%, starter identity ~1%, and lineup + starter duration ~0.

## 26. Bullpen Priority

**`BULLPEN_RESEARCH_PRIORITY_HIGH`.** Now that starter identity is closed cheaply, the bullpen
remains the single dominant participation degrader (~3.5–3.9% Brier from Phase 5E) — the largest
remaining prediction-quality lever in the participation stack.

## 27. Prospective Feed Priority

**`PROSPECTIVE_FEED_READY_FOR_INTEGRATION`.** The pregame participation stack is now structurally
credible, so a real pregame schedule / probable-starter / lineup / injury feed would have a
credible model to feed. (Infrastructure should still follow the product decision below.)

## 28. Model Studio Cockpit Priority

**`MODEL_STUDIO_COCKPIT_READY_TO_PRIORITIZE`.** The end-to-end pregame pipeline (data → D3 PA
model → transition → kernel → fully-projected participation → game distributions) is validated as
research-credible — the bar Phase 5E/5F set for the interactive modeling cockpit to rise to a top
priority.

## 29. Premium-Data Priority

**`PREMIUM_DATA_MEDIUM`.** Participation (bullpen) remains a larger, cleaner game-level lever than
the diffuse contact-quality signal; premium data stays medium.

## 30. Clustering Priority

**`CLUSTERING_LOW`.** No evidence elevates exploratory clustering; participation and product
work dominate.

## 31. Algorithm-Tournament Priority

**`ALGORITHM_TOURNAMENT_LOW`.** D3 adds confirmed game-level value; the remaining error is
participation (bullpen) and product usability, not the PA algorithm family.

## 32. E6 Priority

**`E6_MEDIUM`.** Handedness/platoon remains a roadmap item, not the next bottleneck.

## 33. Exact Next Launch-Critical Step

**Build the interactive ASP Model Studio cockpit.** The pregame research simulator is now
end-to-end credible under fully-projected participation, which is the milestone that unlocks the
product goal: a modeling environment where a data scientist controls data, target, feature
engineering, temporal split, model family, hyperparameters, comparison, and simulation impact.
The task's own guidance is to not default to backend modeling once the pregame pipeline is
credible; it is. Secondary priorities, ranked: **(2)** bullpen reliever-selection improvement (the
sole material participation degrader, `BULLPEN_RESEARCH_PRIORITY_HIGH`); **(3)** prospective feed
integration (`READY_FOR_INTEGRATION`).

## Executive Starter Model Table (§55)

| metric | 2024 | 2025 |
| --- | --- | --- |
| team-games evaluated | ~4,858 | ~4,860 |
| candidate-pool coverage | 0.926 | 0.924 |
| top-1 accuracy | 0.705 | 0.717 |
| top-1 (covered) | 0.761 | 0.775 |
| top-2 accuracy | 0.840 | 0.847 |
| top-3 accuracy | 0.876 | 0.882 |
| log loss | 2.766 | 2.769 |
| Brier | 0.441 | 0.431 |
| MRR | 0.794 | 0.802 |
| mean candidate count | 9.2 | 9.1 |
| pool-miss (fallback) rate | 7.4% | 7.6% |

## Simulator Impact Table (§56)

| metric | Q0 2024 | Q1 2024 | rel Δ | Q0 2025 | Q1 2025 | rel Δ |
| --- | --- | --- | --- | --- | --- | --- |
| home-win Brier | 0.2416 | 0.2441 | +1.04% | 0.2447 | 0.2455 | +0.33% |
| total-run CRPS | 2.389 | 2.399 | +0.45% | 2.522 | 2.522 | +0.02% |
| total-run bias | +0.410 | +0.394 | — | −0.084 | −0.102 | — |
| run-diff MAE | 3.339 | 3.345 | +0.2% | 3.469 | 3.474 | +0.1% |
| 90% coverage | 0.929 | 0.928 | −0.001 | 0.903 | 0.900 | −0.003 |

## Decisions

- **Model:** `STARTER_IDENTITY_RESEARCH_COMPONENT`.
- **Simulator:** `STARTER_IDENTITY_PROJECTION_ACCEPTABLE`.
- **Pregame simulator:** `PREGAME_RESEARCH_SIMULATOR_READY`.
- **Bullpen:** `BULLPEN_RESEARCH_PRIORITY_HIGH` · **Prospective feed:** `READY_FOR_INTEGRATION` ·
  **Model Studio cockpit:** `READY_TO_PRIORITIZE` · **Premium data:** `MEDIUM` · **E6:** `MEDIUM`
  · **Algorithm tournament:** `LOW` · **Clustering:** `LOW`.
- **Single #1 next task:** Interactive ASP Model Studio cockpit.
