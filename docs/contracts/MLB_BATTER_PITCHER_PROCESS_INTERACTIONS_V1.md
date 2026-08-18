# MLB_BATTER_PITCHER_PROCESS_INTERACTIONS_V1 — Governed Contract (E2)

**Type:** Feature family / materialization (bounded batter × pitcher matchup
interactions). **Not** a model. **Phase:** Phase 4D (E2). Trains nothing, evaluates
nothing, uses no target, claims no predictive improvement. Class order and target
unchanged.

---

## 1. Purpose & parent authority

E2 represents batter-versus-pitcher **matchup structure** that additive player
features cannot express, as a **pure row-local transform** of the governed E1
process features (`MLB_PITCH_SEQUENCE_PROCESS_FEATURES_V1`). E2 does not read raw
`pitch_sequence` or FD1 rows; it consumes the content-addressed E1 feature artifact
after **SHA-verifying** it against E1's recorded authority (mismatch ⇒ stop, no
substitution).

- Parent E1 materialization `pitch-sequence-features-ae7eadd6ade83f28`, feature SHA
  `7017c3c88ca96d77…`, 568,935 rows, seasons 2023–2025.
- Dataset authority: registration `sports-dataset-1b58d5d1def2c9b7`, manifest
  `1b58d5d1…` (verified against the active registration).

## 2. Leakage & temporal inheritance

E2 inherits E1's strict prior-date safety unchanged: each E2 row is a deterministic
function of the same E1 row's prior-date-safe batter and pitcher states (target PA
and same-date PAs already excluded upstream). No raw future/source lookup occurs
during E2 construction. Because E2 is column-wise over E1 rows, **output row count ==
input row count** (no merge, no fan-out) — asserted at build time and in tests.

## 3. Allowed transforms

Row-local, no fitting: product, absolute difference, cross-product of two named
fields, `log1p` sample-size combinations, min. **Not** allowed (deferred to model
folds): PCA, learned embeddings, target encoding, clustering, learned normalization,
league-relative contrasts requiring fitting (marked `MODEL_FOLD_DERIVED`).

## 4. Feature set (bounded; 25 features, hard max 60)

By family (all from E1 cumulative window unless suffixed `_trail30`):

- **strikeout:** `bp_swinging_strike_product`, `bp_swinging_strike_absdiff`,
  `bp_called_strike_product`, `bp_two_strike_product`.
- **walk:** `bp_ball_rate_product`, `bp_ball_rate_absdiff`,
  `bp_pitches_per_pa_product`, `bp_pitches_per_pa_absdiff`,
  `batter_patience_x_pitcher_command` (batter called-strike rate × pitcher ball rate).
- **first_pitch:** `bp_first_pitch_strike_product`, `bp_first_pitch_strike_absdiff`.
- **contact:** `bp_in_play_product`, `bp_in_play_absdiff`, `bp_foul_product`.
- **sample:** `bp_log_sample_product` (log1p×log1p prior PAs), `bp_min_log_sample`,
  `both_process_low_sample`, `both_process_missing`, `both_process_history_present`,
  `batter_process_missing`, `pitcher_process_missing`.
- **recent_form (trailing-30d):** `bp_swinging_strike_product_trail30`,
  `bp_ball_rate_product_trail30`, `bp_first_pitch_strike_product_trail30`,
  `bp_two_strike_product_trail30`.

The full 25 × 25 = 625 Cartesian product is deliberately **not** generated.

## 5. Null / missingness behaviour

E2 preserves E1 missingness honestly: a product/abs-diff of a null input is **null**
(no global-average imputation in the materialized family; learned imputation belongs
in model folds). Indicators derived from E1's `missing_history` / `low_sample`
(`both_process_*`, `batter/pitcher_process_missing`) are 0/1 and never null.

## 6. Sample-size fields

Reliability is carried by `bp_log_sample_product`, `bp_min_log_sample`,
`both_process_low_sample`, and the missing indicators — a small-sample matchup is
never presented as equivalent to a large-sample one.

## 7. Distribution & redundancy audit (predictor-only)

Per-feature per-season count/coverage/mean/std/min/p01/p05/p25/median/p75/p95/p99/max;
plus near-constant detection, exact-duplicate detection, and high |Pearson| pairs
(≥0.95, sampled). **No target, no supervised selection, no 2025 labels.** Only
structurally useless features (constants / exact duplicates) may be dropped, with a
documented reason.

## 8. Absolute exclusions

No model training/evaluation/log-loss/Brier/calibration/bootstrap; no target-based
feature selection; no archetypes/clustering; no handedness/platoon acquisition; no
premium/Statcast; no class/target change; no simulator.

## 9. E6 / archetype handoff (design only)

A future governed **E6** companion (bats L/R/S, throws L/R, primary position,
optional age/debut) would segment these interactions by platoon quadrant
(LHB-vs-LHP, LHB-vs-RHP, RHB-vs-LHP, RHB-vs-RHP, switch-hitter effective side). A
future **archetype** study should use E1 process states + E2 matchup structure + E6
platoon rather than static annual features. Neither is acquired or built here.

## 10. Artifact storage & version identity

Content-addressed zstd Parquet under ignored runtime storage
(`.runtime/asp-model-studio/sports-phase4/process-interactions/`), logical URI
`asp-model-studio-runtime://sports-phase4/process-interactions/...`; **never
committed**. Identity = contract SHA + parent E1 authority (materialization ID +
feature SHA) + dataset authority + code revision → `materializationId`.

## 11. Terminal statuses

`PROCESS_INTERACTIONS_READY` / `PROCESS_INTERACTIONS_PARTIALLY_READY` /
`PROCESS_INTERACTIONS_BLOCKED`, decided from row-count preservation + feature
integrity (no exact duplicates / near-constants). READY means the interaction family
is materialized and integrity-checked — **not** that any effect is proven predictive.

## 12. Implementation

`server/sports_phase4/process_interactions_run.py`,
`scripts/run_mlb_process_interactions.py`,
`tests/sports_phase4_process_interactions_test.py`.
