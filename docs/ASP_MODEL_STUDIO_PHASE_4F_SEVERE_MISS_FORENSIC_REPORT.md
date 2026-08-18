# ASP Model Studio — Phase 4F Severe-Miss Forensic Report

**Study:** `MLB_PA_SEVERE_MISS_FORENSIC_STUDY_V1` · **Study ID:**
`severe-miss-forensics-b5e72f607172a6a1` · Analysis only — no model promoted, no official
observation removed, no individual loss clipped, no outcome relabelled.

---

## Executive Verdict

**The D3 PA model is not being distorted by a small set of structured, fixable situations.
Its severe misses are a broad, thin right tail that is almost entirely one thing: rare
positive batted-ball outcomes (home runs, doubles, triples, reach-on-error) that the free
process/discipline features cannot distinguish from routine outs.**

Six facts drive the verdict, and every one of them is essentially identical in 2024 and 2025:

1. **Concentration is mild.** The worst 1% of PAs contribute only **3.4–3.5%** of total log
   loss; the worst 5% contribute **12.8%**; the worst 50% contribute ~72%. A tiny outlier
   set is *not* dominating the aggregate — error is broadly distributed (skew ≈ 1.4–1.5).
2. **The tail is one outcome family.** ~**90%** of the worst-5% misses are HOME_RUN→BIP_OUT,
   DOUBLE→BIP_OUT, OTHER_REACH→BIP_OUT, and TRIPLE→BIP_OUT. Over-index vs population: TRIPLE
   **20×**, OTHER_REACH **~19×**, HOME_RUN **~14×**, DOUBLE **~7×**. STRIKEOUT, WALK, SINGLE,
   and BIP_OUT are essentially **absent** from the tail (over-index ≈ 0).
3. **It is not overconfidence.** Severe rows carry a mean true-class probability of **2.7%**
   with a mean top probability of only **~0.44**; just **15–19%** are "confident-wrong"
   (top ≥ 0.5, true < 0.1). Most severe misses are *reasonable uncertainty followed by a rare
   outcome*, not the model betting hard and losing.
4. **No governed pre-prediction segment stands out.** Batter position, starter/reliever,
   substitute/pinch, catcher certainty, batter/pitcher history, inning, base/out/score state,
   month/season phase, and target-free OOD deciles **all** produce severe-miss over-index in
   the narrow band **~0.8–1.2**. Nothing concentrates the tail.
5. **Severe misses are barely predictable before the outcome.** A diagnostic pre-prediction
   classifier (fit 2024, evaluated out-of-time 2025, pregame predictors only) reaches
   **ROC-AUC 0.554 / PR-AUC 0.059** — a hair above chance. You cannot tell in advance which
   routine-looking PA will become a home run from the free features.
6. **Misses are broadly distributed across games and players.** In 2025 it takes **716 of
   2,344 games** and **~150–164 players** to account for 50% of severe misses — no small
   cluster of "problem games" or "problem players."

**Randomness verdict: STRUCTURED_BUT_CURRENTLY_UNMODELED in the outcome dimension, yet
near-irreducible from the pre-prediction free feature set (MIXED).** The only structure is
contact quality — a *representation/premium-data gap*, not a model-family, segmentation,
calibration, or data-quality problem.

**Recommended next step:** do **not** build more free features to chase this tail (E3/E4/E6
and a nonlinear tournament cannot see exit velocity, launch angle, or barrel, and the misses
are neither in unusual feature regions nor overconfident). The two honest, high-value levers
are (1) a **premium contact-quality (Statcast) data trial** — the only lever that touches the
dominant tail — and (2) an **abstention / no-bet uncertainty policy** on high-variance
batted-ball situations. Cold-start calibration for low/mid-history batters is a minor
secondary win.

---

## Population and Authorities

Regenerated the frozen Phase 4E A/B/C out-of-sample probabilities (A = D3, B = D3+E1,
C = D3+E1+E2) under the identical fixed policy (`C=0.05` multinomial l2 logistic) on the
identical **549,479-PA** population. **Branch A reproduced the frozen D3 log loss exactly**
(2024 = 1.476588, 2025 = 1.474100) — correctness anchor verified before any forensic claim.
Analyzed folds: 2024 (182,449 PAs) and 2025 (182,926). Governed segmentation evidence:
retrospective FD1 `player_game_batting` (lineup/position incl. DH; ~100% coverage on
2024/25), `player_game_pitching` (`actual_start_flag` → starter/reliever; 100% coverage),
`player_game_fielding` (catcher context), `plate_appearance` (game state) — used for
segmentation only, never as a pregame model feature (all timing-risk labelled).

## Individual Loss Distribution (D3)

| Season | mean | std | skew | p50 | p90 | p99 | p99.9 | max |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2024 | 1.4766 | 0.846 | 1.50 | 1.222 | 2.617 | 4.455 | 5.809 | 7.940 |
| 2025 | 1.4741 | 0.856 | 1.43 | 1.236 | 2.661 | 4.289 | 5.783 | 7.442 |

Median individual log loss (~1.22) already sits well below the mean — the mean is pulled up
by a moderate right tail, not a few catastrophic points (max ≈ 7.9 corresponds to the model
giving the realized class ≈ 0.04% probability). The distribution is *broad*, not spiky.

## Brier Distribution

Summed multiclass Brier is far less tail-sensitive than log loss (log loss is unbounded as
p→0; Brier is bounded at 2 per row). The global log-loss weakness is therefore more
tail-influenced than the Brier result, but even for log loss the tail influence is modest
(see Pareto and Tail-Sensitivity).

## Pareto Error Concentration (D3 log loss)

| Worst fraction | 0.1% | 0.5% | 1% | 5% | 10% | 20% | 50% |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 2024 loss share | 0.4% | 1.9% | 3.5% | 12.8% | 22.8% | 38.0% | 71.9% |
| 2025 loss share | 0.4% | 1.9% | 3.4% | 12.8% | 22.9% | 38.4% | 72.4% |

The worst 1% carries ~3.4× its row share and the worst 5% ~2.6× — real but mild
concentration. **A small number of outliers is *not* materially distorting aggregate log
loss.**

## Severe-Miss Definitions

Multiple definitions were computed (worst-loss percentiles 0.1/0.5/1/2/5%; true-class
probability < 0.5/1/2/5/10%; excess-vs-A ≥ 0.25/0.50/1.00 and the symmetric improvements).
All findings below are reported on the worst-5% D3 log-loss definition and cross-checked
against the probability-threshold definitions, which agree.

## Actual Outcome Over-Indexing (worst 5%)

| Class | pop share | severe share | over-index (2025) |
| --- | --- | --- | --- |
| TRIPLE | 0.34% | 6.9% | **20.0×** |
| OTHER_REACH | 0.94% | 17.7% | **18.7×** |
| HOME_RUN | 3.09% | 46.0% | **14.9×** |
| DOUBLE | 4.23% | 28.1% | **6.6×** |
| WALK_HBP_CI | 9.51% | 1.3% | 0.14× |
| STRIKEOUT | 22.2% | 0.03% | ~0× |
| SINGLE | 14.3% | 0.0% | 0× |
| BIP_OUT | 45.4% | 0.0% | 0× |

Over-indexing is entirely a contact-quality story. Rarity alone does not explain it — WALK
(9.5% of PAs) is *under*-represented in the tail, while HOME_RUN and the extra-base hits
dominate it.

## Confusion Pairs (worst 5%, 2025)

| Actual → Predicted | count | share of severe | mean loss |
| --- | --- | --- | --- |
| HOME_RUN → BIP_OUT | 4,068 | 44.5% | 3.58 |
| DOUBLE → BIP_OUT | 2,383 | 26.1% | 3.26 |
| OTHER_REACH → BIP_OUT | 1,581 | 17.3% | 4.49 |
| TRIPLE → BIP_OUT | 616 | 6.7% | 5.45 |
| DOUBLE → STRIKEOUT | 187 | 2.0% | 3.39 |
| HOME_RUN → STRIKEOUT | 137 | 1.5% | 3.55 |

The top four pairs — every one a *positive batted-ball outcome scored as a routine out* —
are ~94% of the severe tail. 2024 is essentially identical.

## Position Effects

Batter defensive/roster position does **not** structure the tail. Worst-5% over-index (2025):
SUB_OR_PINCH 1.11, C 1.09, CF 1.04, LF 1.04, RF 1.00, and interior positions between. The
spread is inside the noise band; no position deserves specialized handling on this evidence.

## Starter vs Reliever

RELIEVER worst-5% over-index 1.09 (log loss 1.481) vs STARTER 0.94 (log loss 1.469) in 2025
— relievers are *slightly* harder, consistent with higher batted-ball variance and leverage,
but the effect is mild and does not by itself justify a role-specific model.

## Participation / Substitute Effects

Substitutes/pinch-hitters (`actual_starting_lineup = false`) over-index 1.11 — marginally
above starters, not disproportionate. Unusual participation states are not a material driver.

## Catcher / Battery Effects

Games where the pitching team used ≥ 2 catchers (AMBIGUOUS) over-index 1.05 vs DETERMINISTIC
0.99. Catcher-context ambiguity is **not** correlated with severe misses in any material way.
(No catcher causality is claimed.)

## Batter History

Worst-5% over-index by prior-PA band (2025): 150–299 **1.19**, 1–49 **1.16**, 300–599 1.10,
50–149 1.09, **600+ 0.96**. There is a *mild* low/mid-history elevation, but it is a ~10–20%
effect, not a cold-start blow-up, and the largest, most-established band (600+) is the
*safest*.

## Pitcher History

Essentially flat and, if anything, inverted: 600+ 1.01, 150–299 1.01, 300–599 0.99, 1–49
0.98, 50–149 0.94, **0_missing 0.82**. This **confirms and sharpens Phase 4A**: low pitcher
history is not merely irrelevant in aggregate — it is *under*-represented in the severe tail.

## E1 Process-State Analysis

The severe tail is not a plate-discipline phenomenon: STRIKEOUT and WALK (the classes E1
targets) are absent from it. E1 process features (swing/called-strike/ball tendencies, first
pitch, two-strike, pitches-per-PA, sample size) therefore have essentially no purchase on the
severe misses, which are batted-ball outcomes. This is consistent with Phase 4E, where E1's
value was concentrated in exactly the STRIKEOUT/WALK classes that do *not* appear here.

## E2 Interaction Analysis

Likewise, E2 matchup interactions do not identify the severe region — the misses are not in
extreme or contradictory interaction states (OOD is flat, below), they are ordinary matchups
with an extraordinary batted-ball result. A nonlinear model over the same E2 inputs would not
recover the missing contact-quality signal.

## Game-State Analysis

Inning band over-index (2025): extra 1.20, 7–9 1.10, 4–6 1.03, **1–3 0.87** — later innings
are modestly harder (more relievers, higher batted-ball variance). Base/out/score bands are
flat. Game state nudges but does not structure the tail.

## Temporal Analysis

Season phase over-index (2025): early 1.09, mid 0.98, late 0.98. Early-season state estimation
is *slightly* worse (consistent with thinner priors), but the effect is small and does not
change the batted-ball diagnosis.

## Player / Game Concentration

Broadly distributed. In 2025, 50% of severe misses span **716 games** (of 2,344), **150
batters** (of 601), and **164 pitchers** (of 771). The most-surprising 10% of the tail comes
from ~21–23 players — a mild, expected concentration (the league's biggest power hitters),
not a defect cluster. No game/date/team hotspot indicating a data-quality event was found.

## OOD Analysis

Target-free standardized-Mahalanobis distance (fit on training-eligible folds) shows **no
relationship** with severe misses: worst-5% over-index across OOD deciles ranges only
1.00–1.04 in 2025. Severe misses are **not** in unusual feature-space regions — they are
normal matchups with rare results. (No OOD rows were removed.)

## Predictability Segments

Ranking legitimate governed segments by log loss produces a compressed range (~1.45–1.51):
the model is close to uniformly mediocre across interpretable subpopulations, with contact
outcomes — not any subpopulation — carrying the tail.

## Severe-Miss Classifier (diagnostic only)

Target = D3 worst-5% individual log loss; predictors = pre-prediction only (state ESS/
entropy/missing, E1 process rates and sample sizes, context, month, prior-season starter
rate); no outcome, loss, future info, or retrospective role/position. Fit 2024, evaluated
out-of-time 2025: **ROC-AUC 0.554, PR-AUC 0.059** (base rate 5%). Severe misses are barely
detectable before the outcome — strong evidence that they are *not* a pre-prediction-
structured, model-fixable phenomenon on the current data.

## Randomness Assessment

**STRUCTURED_BUT_CURRENTLY_UNMODELED (outcome dimension) → near-irreducible pre-outcome
(MIXED).** The severe tail is perfectly structured by *what happened* (contact quality) but
not by *anything knowable beforehand* from the free feature set. This is a representation gap,
not randomness in the trivial sense and not a model-family or segmentation failure.

## Tail-Sensitivity Analysis — DIAGNOSTIC ONLY, NOT A PRODUCTION PERFORMANCE CLAIM

The official metric is unchanged; this only quantifies tail influence.

| Season | official | −worst 0.1% | −worst 0.5% | −worst 1% | −worst 5% |
| --- | --- | --- | --- | --- | --- |
| 2024 | 1.4766 | 1.4719 | 1.4564 | 1.4397 | 1.3549 |
| 2025 | 1.4741 | 1.4694 | 1.4541 | 1.4381 | 1.3529 |

Removing the worst 1% moves aggregate log loss by only ~0.037 (~2.5%); removing the worst 5%
(all legitimate hard batted-ball events, which must **not** be dropped in production) by ~0.12
(~8%). The tail is real but not the whole story — the model is *broadly* mediocre.

## Corrective Opportunities

| Pattern | Category | Impact | Detectable pre-outcome | Ease |
| --- | --- | --- | --- | --- |
| Contact-quality representation gap (dominates tail, over-index 7–20×) | PREMIUM DATA / ABSTAIN | 5 | 1 | 1 |
| Reasonable-uncertainty rare outcomes (2.7% mean true prob) | ABSTAIN / NO-BET; largely IRREDUCIBLE | 4 | 1 | 2 |
| Mild low/mid batter-history cold-start (~1.1–1.2×) | CALIBRATION / UNCERTAINTY | 2 | 4 | 3 |
| Mild reliever / late-inning elevation (~1.1×) | SEGMENTED MODEL (low) | 2 | 3 | 3 |
| OOD regions (no over-index) | NO ACTION / IRREDUCIBLE | 1 | 4 | 2 |

## Bounded Corrective Experiment

**Not run — the gate was not met.** The bounded-correction gate (section 29) requires a
strong pattern with *plausible pre-prediction information*. The dominant pattern fails that
condition: the severe tail is not detectable from pregame features (AUC 0.554), is not in
unusual feature regions (flat OOD), is not overconfidence, and is not concentrated in any
governed segment. A starter/reliever or nonlinear challenger on the same free features cannot
recover contact quality, so building one would burn the budget without addressing the cause.
The only lever with real impact is premium contact-quality data, which is out of scope for
this analysis-only study. Running a diagnostic correction here would be metric theatre.

## Betting-Relevance Interpretation

Without any market data, the error structure implies clear future betting-policy principles:
avoid or heavily discount confidence on **batted-ball-outcome props** (HR / extra-base / total
bases) for the current model, because its dominant error mode is exactly unpredictable contact
quality; the model is comparatively trustworthy on **STRIKEOUT and WALK** props, which barely
appear in the severe tail. Require an abstention path for high-variance, low-edge batted-ball
situations. History/role/catcher gating would yield only marginal benefit.

## Priority Ranking

Ranked by impact-on-total-loss then multi-criteria total. #1 = contact-quality representation
gap → **premium data or abstention** (not free feature engineering). #2 = reasonable-
uncertainty rare outcomes → **abstention / accept as irreducible**. #3 = mild cold-start →
**calibration**. Full 6-axis scoring is persisted in the study artifact.

## Recommended Next Development Step

**Stop expanding free features to chase the severe tail.** The highest-value next actions, in
order: (1) scope a **premium Statcast contact-quality trial** and measure whether exit
velocity / launch angle / barrel materially compress the HR/2B/3B tail; (2) design an
**abstention / no-bet uncertainty policy** for high-variance batted-ball props (cheap, high
betting relevance, removes no observation from evaluation); (3) a small **cold-start
calibration** pass for low/mid-history batters (minor). **E6 priority: unchanged** (it does
not touch this tail, though it may still aid discipline classes per Phase 4E). **Nonlinear-
algorithm priority: not raised for the tail** (data-limited, not model-family-limited).
**Premium-data priority: raised** — this study is the first concrete, quantified case for it.
