# ASP Model Studio — Phase 5B Empirical Base-Out / Runner-Advancement Transition Model

**Contract:** `MLB_BASE_OUT_TRANSITION_MODEL_V1` · Simulation component, not a PA model, game
forecast, betting model, or Monte Carlo result.

---

## 1. Executive Verdict

**`BASE_OUT_TRANSITION_MODEL_READY`.** The empirical conditional transition model learns a
legal, temporally-stable distribution over `(outs_added, base_mask_after, runs_scored)` given
`(PA outcome, outs, base state)`. Out-of-time one-step backtest: **2024 log loss 0.2266 /
2025 frozen 0.2280** (drift 0.0014), top-1 91.1% / top-2 96.9%, base-mask-after accuracy
91.2%, outs-added 97.5%, inning-ending 98.7%, runs-scored MAE 0.027. **Illegal probability
mass is exactly 0** and a 50,000-transition stochastic stress test produced **0 illegal
states, 0 duplicated runners, 0 lost runners**. Fallback to the legal prior is **0%** (L0
exact 97.0%, HOME_RUN deterministic 3.0%). The provider integrates cleanly with the proven
kernel and is reproducible under seed. This unblocks the simulator; it is **not** a game
forecaster.

## 2. Why This Component Is Launch-Critical

The eight-class PA target cannot deterministically update runners and outs (a SINGLE with a
runner on second may score him, hold him at third, or throw him out). The simulator therefore
needs `P(next state | PA outcome, base state, outs)`. This model is that bridge between a
sampled PA outcome and the deterministic game kernel.

## 3. Parent Replay Authority

`MLB_GAME_REPLAY_ENGINE_V1` (`GAME_REPLAY_ENGINE_READY`), whose governed `play_transition`
before/after semantics this model consumes unchanged.

## 4. Dataset / Source Authorities

FD1 dataset `sports-dataset-1b58d5d1def2c9b7`, manifest `1b58d5d1…`, family `play_transition`
(949,217 plays; 913,349 eligible eight-class PAs). No new data.

## 5. Temporal Population

Development 2021–2023 (547,556 legal PAs); validation 2024 (182,300); frozen 2025 (182,764).
2025 was not used for policy selection.

## 6. Transition Target

Canonical `(outs_added, base_mask_after, runs_scored)`. On the third out the half-inning ends,
the source clears the bases (`base_mask_after = 0`) and surviving runners are stranded.

## 7. Eight-Class Event Mapping

`pa_outcome` is already the frozen eight-class label; 35,868 non-PA marker rows excluded.
913,349 eligible PAs; **99.92% satisfy the single-PA runner-conservation invariant**; the
0.08% residual (729 rows — multi-play/source quirks) are excluded from fitting and evaluation
with reason. No event family was silently discarded.

## 8. Transition Taxonomy

192 primary cells (8 outcomes × 3 outs × 8 base states); 785 distinct legal transitions
observed; 19 sparse cells (< 20 dev samples). Cell density is high (median ≈ 1,055 samples).

## 9. Deterministic Mechanical Rules

`HOME_RUN` is deterministic (verified 100% across all base/out states): bases clear, outs
unchanged, `runs = occupied runners + batter`. `STRIKEOUT` (98.9% ordinary) and `WALK_HBP_CI`
(99.6% forced-advance) are low-entropy but kept empirical to capture legal exceptions.

## 10. Empirical Transition Model

Champion **T0** = empirical conditional distribution `P(transition | outcome, outs, base)`
fit on development seasons only. Context challengers (inning/score) were **not** implemented:
T0 exhibits no limitation warranting them — the residual uncertainty is irreducible mechanical
ambiguity (BIP_OUT/SINGLE with runners), which inning/score context does not resolve.
Simplicity is retained.

## 11. Smoothing Policy

Dirichlet(α = 0.5) pseudocounts spread over the enumerated legal transition set of each cell,
so unseen-but-legal transitions receive small positive probability; illegal transitions
receive exactly zero. Pseudocounts are principled (uniform over the legal set), not arbitrary.

## 12. Legality Constraints

A transition is legal iff `outs_before ∈ {0,1,2}`, `outs_added ≥ 0`, `runs ≥ 0`,
`outs_before+outs_added ≤ 3`, `base_mask_after ∈ 0..7`, and runner conservation holds
(inning-continues → `popcount(before)+1 == popcount(after)+runs+outs_added` with a valid
forward runner assignment where runners may hold or advance but never pass; inning-ends →
`base_mask_after == 0` and stranded `= popcount(before)+1 − outs_added − runs ≥ 0`). Verified
illegal probability mass = **0** across all cells.

## 13. Fallback Hierarchy

`L0_EXACT → L1_OUTCOME_OUTS → L2_OUTCOME → L3_LEGAL_PRIOR`, each filtered to transitions legal
for the current base state. 2024 usage: L0 97.0%, HOME_RUN-deterministic 3.0%, L1 0.02%, L2
0.007%, **L3 0.0%**. 2025 usage is essentially identical.

## 14. 2024 Results

log loss 0.2266 · Brier 0.1182 · top-1 0.9110 · top-2 0.9694 · runs MAE 0.0265 · outs-added
0.9751 · base-mask-after 0.9116 · inning-ending 0.9865 · mean entropy 0.236.

## 15. 2025 Frozen Results

log loss 0.2280 · Brier 0.1188 · top-1 0.9105 · top-2 0.9681 · runs MAE 0.0265 · outs-added
0.9754 · base-mask-after 0.9112 · inning-ending 0.9863. Drift vs 2024 is negligible (0.0014).

## 16. Outcome-Family Results (2024 transition log loss)

| Outcome | log loss | top-1 |
| --- | --- | --- |
| HOME_RUN | 0.0000 | 1.000 |
| WALK_HBP_CI | 0.0272 | 0.996 |
| STRIKEOUT | 0.0556 | 0.989 |
| TRIPLE | 0.1244 | 0.986 |
| BIP_OUT | 0.2578 | 0.886 |
| DOUBLE | 0.3544 | 0.864 |
| SINGLE | 0.4882 | 0.821 |
| OTHER_REACH | 1.0190 | 0.662 |

Uncertainty concentrates where baseball is genuinely ambiguous: OTHER_REACH (errors /
interference / dropped-third-strike reaches), then SINGLE/DOUBLE runner advancement, then
BIP_OUT out-subtypes (ordinary out / double play / fielder's choice / sacrifice).

## 17. Base/Out Cell Results

Highest-loss cells (2024) are BIP_OUT with a runner on first (outs 0/1, base 1/3) and SINGLE
with runners — mean cell log loss 0.7–1.5, no catastrophic cell. These are the mechanically
ambiguous situations (double-play vs advance vs force), exactly where simulation variance
legitimately originates.

## 18. Runs-Scored Validation

Runs-scored MAE 0.0265 (2024) / 0.0265 (2025); the mode transition predicts runs exactly on
the vast majority of PAs. Performance is best on STRIKEOUT/HOME_RUN (deterministic runs) and
softest on SINGLE/OTHER_REACH (runner-scoring uncertainty).

## 19. Multi-Out Validation

Double-play-class transitions (`outs_added = 2`) are represented per cell (e.g., BIP_OUT with a
runner on first assigns > 20% to the double play) and are legal — the simulator can end an
inning correctly from a double-play-like transition. Outs-added accuracy is 97.5%.

## 20. Error Forensics

The largest errors are concentrated in BIP_OUT-with-runner and SINGLE-with-runner cells
(runner-advancement ambiguity), not in sparse cells or fallback. No new feature family is
proposed — these are irreducible mechanical distributions the simulator should sample, not
predict deterministically.

## 21. Error Concentration

Diagnostic only: worst 1% of PAs carry 19.9% of transition log loss, worst 5% carry 51.7%,
worst 10% carry 76.1%. Uncertainty is moderately concentrated in the ambiguous mechanical
cells rather than diffuse; no difficult transitions were removed.

## 22. Transition Entropy

Mean per-PA entropy 0.236. Deterministic/stochastic share (2024): mechanically deterministic
3.0% (HR), empirically-stochastic low-entropy 75.4%, high-entropy 21.6%, fallback 0.0%.

## 23. Stochastic Stress Test

1,000 sequences × 50 sampled transitions = 50,000 through the deterministic kernel: **0
illegal states, 0 duplicated runners, 0 lost runners, 0 outs violations**. Runner identities
apply forward without duplication or loss (stranded runners handled at inning end).

## 24. Reproducibility

Same (state, outcome, model, seed) reproduces the same sampled transition; a different seed
yields alternative legal paths in stochastic cells. Verified.

## 25. Artifact / Registry Evidence

Data-only JSON model artifact (19,845 bytes, `sha256:4f312af6…`, format
`JSON_DATA_ONLY_NO_PICKLE` — no executable serialization, per the security audit). Registered
as an authority-gated `phase4.baseOutTransition` projection with the full metric inventory,
parent replay authority, dataset authority, deterministic-rule inventory, legality result,
and readiness status. No placeholder or whole-game-forecast metrics.

## 26. Simulation-Kernel Integration

The empirical provider implements the `RunnerAdvanceProvider` seam: `state + sampled PA
outcome → sampled legal transition → deterministic kernel → valid next state`. Single-step and
short-sequence integration are proven; the kernel is unchanged.

## 27. Known Limitations

One-step provider only; conditioned on outcome/outs/base with no inning/score/park/handedness
context (T0, simplest defensible); 0.08% of governed PAs (multi-play/source quirks) excluded;
READY means transition mechanics are trustworthy for simulation, not that a forecaster or
Monte Carlo exists.

## 28. Phase 5C Interface

Next, a `ProbabilisticPAOutcomeProvider` returns the eight-class probability vector from
batter/pitcher/game state; the `SimulationEngine` composes `PAOutcomeProvider +
RunnerAdvanceProvider` over the unchanged deterministic kernel. **D3 adapter (design only):**
a probabilistic PA provider would pin the exact D3 model authority, class order,
preprocessing authority, batter/pitcher state, invocation game state, and missing-history
handling; no D3 inference in simulation yet, no D3 modification. **Participation providers
(design only):** the Milestone B Lineup/Starter/Bullpen components are retrospective research
evidence — they do not provide prospective confirmed participants; a prospective feed is not
built here.

## 29. Monte Carlo Entry Gates

Before whole-game Monte Carlo may begin: (1) replay engine READY ✅; (2) base-out transition
model READY ✅; (3) legal stochastic stress test passes ✅; (4) reproducibility passes ✅;
(5) D3 probabilistic PA provider adapter validated ⛔; (6) historical participant replay
provider available ⛔; (7) game-initialization contract defined ⛔; (8) game terminal rules
verified ✅ (Phase 5A); (9) model/transition authorities pinned ✅; (10) no unresolved
state-corruption defect ✅. Gates 5–7 remain.

## 30. Exact Next Launch-Critical Step

Build the **D3 probabilistic PA-outcome provider adapter** (Phase 5C) — the last missing input
before the first whole-game Monte Carlo on the already-proven kernel + transition model — then
a historical game-level backtest. Premium contact-quality, E6, and the algorithm tournament
remain lower priority (they improve PA quality, not simulator readiness). Monte Carlo, game
calibration, residual layer, prospective feed, and ASP export remain NOT_CONFIGURED.
