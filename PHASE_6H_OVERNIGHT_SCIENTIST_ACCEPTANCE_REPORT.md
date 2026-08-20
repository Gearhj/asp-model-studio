# Phase 6H — Overnight Scientist Acceptance Report

**Repository:** asp-model-studio · **Branch:** phase5-game-replay-foundation
**Starting HEAD:** 6a98466 · **Ending HEAD:** *(this commit)*
**Run window:** 2026-08-19 23:35 → 2026-08-20 (local) · **Method:** the real cockpit backend modules
(`engine` / `modeling` / `segmentation` / `features_builder`) driven directly with bounded settings, plus
live authenticated API verification. Every challenger trained with `persist=False`; the registered
D3/C4 champion and the experiment registry were never written.

---

## 1. Executive verdict

ASP Model Studio behaves as a **coherent end-to-end scientific modeling environment**, not a set of
disconnected screens. Eight model families train against a shared, leakage-guarded pipeline; preprocessing
choices demonstrably propagate to the estimator; engineered features, segmentation, temporal policies,
tuning, and autopilot all execute against real data with honest, reproducible metrics. The frozen 2025
season is provably excluded from every fit/tune/selection path, and multiclass metrics reproduce
independently to <1e-4.

Two **P2** defects were found and repaired (both narrow, both regression-tested); one **P3** was reviewed
and accepted as a defensive default. **No P0/P1 defects.** The dominant scientific finding is not a
platform defect: the governed 22-feature view has **very weak separating power** for the 8-class PA
outcome — every family clusters at val log loss ≈ 1.484 (~0.45 top-1, macro-F1 ~0.08–0.10), essentially
tied with the champion. This matches the prior Phase-4F "severe-miss is a contact-quality / premium-data
gap" conclusion.

**Overall model-development readiness: SCIENTIST TESTING READY.**

---

## 2. Exact repo / branch / HEAD

- Branch `phase5-game-replay-foundation`, starting HEAD `6a98466` (Phase 6G.2).
- Backend restarted after the two code fixes; **`/api/health` = 200, login = 200** post-restart.

---

## 3. Authority snapshot (Part A — verified from engine, not display text)

| Item | Value |
|---|---|
| Selected dataset | `asp.mlb.open-data.fd1` (MLB FD1 Gen-2 PA feature view) |
| Registered source seasons | 2021, 2022, 2023, 2024, 2025 |
| Target | `outcome` · MULTICLASS_CLASSIFICATION · 8 classes · 0 missing |
| Class order | STRIKEOUT, WALK_HBP_CI, HOME_RUN, SINGLE, DOUBLE, TRIPLE, BIP_OUT, OTHER_REACH |
| Development | 2023 (`DEV_SEASON`) · 184,104 rows |
| Validation | 2024 (`VAL_SEASON`) · 182,449 rows |
| Frozen final | 2025 (`FROZEN_SEASON`) · 182,926 rows |
| Candidate predictors | 22 governed features (no target, no identifiers) |
| Registered champion | D3 · C4 (logistic); in-pipeline reproduction val logLoss **1.48411**, brier 0.7067, ECE 0.0120 |

**Season-role check (from `population_payload().sourceEvidence`):**
`2021 = PRIOR_HISTORY · 2022 = PRIOR_HISTORY · 2023 = DEVELOPMENT · 2024 = VALIDATION · 2025 = FROZEN_FINAL` ✅

---

## 4. Model zoo (Part C) — 8 families, all trained on 2023, evaluated on 2024

Baseline config each: all 22 features, outliers=none, missing=median. Frozen 2025 rows used in fitting = **0** (all runs carry `leakageGuards.frozenSeasonExcludedFromFitting=True`).

| Family | Val logLoss | Δ vs D3/C4 | Brier | ECE | Top-1 | Macro-F1 | Fit s | Expanded |
|---|---|---|---|---|---|---|---|---|
| SVM (LinearSVC+sigmoid) | 1.48381 | −0.00031 | 0.7065 | 0.0118 | 0.4516 | 0.0883 | 42.0 | 32 |
| Logistic (multinomial) | 1.48425 | +0.00014 | 0.7068 | 0.0117 | 0.4516 | 0.0897 | 6.0 | 32 |
| MLP (64,32) | 1.48628 | +0.00217 | 0.7067 | 0.0104 | 0.4526 | 0.0904 | 18.6 | 32 |
| Random Forest | 1.48637 | +0.00226 | 0.7069 | 0.0143 | 0.4529 | 0.0801 | 16.5 | 32 |
| Extra Trees | 1.48649 | +0.00238 | 0.7076 | 0.0152 | 0.4525 | 0.0779 | 14.4 | 32 |
| HistGradientBoosting | 1.48804 | +0.00392 | 0.7073 | 0.0141 | 0.4518 | 0.0898 | 6.4 | 32 |
| XGBoost | 1.49407 | +0.00996 | 0.7093 | 0.0140 | 0.4498 | 0.0956 | 44.4 | 32 |
| LightGBM | 1.50269 | +0.01858 | 0.7109 | 0.0139 | 0.4487 | 0.0969 | 19.6 | 32 |

All 8 families are **runtime-available** (xgboost & lightgbm confirmed installed). Distinct config hashes →
distinct experiment IDs. No new champion promoted. Boosting families are *worse* than the linear baseline
here — a legitimate consequence of weak, near-linear feature signal, not a defect.

---

## 5. Preprocessing matrix (Part D)

Logistic, 22 features, varying outlier/missing policy. **7/7 configs produced distinct experiment IDs.**

| Config | Expanded feats | Val logLoss |
|---|---|---|
| none + median | 32 | 1.48425 |
| IQR 1.5 + median | 32 | 1.48294 |
| z-score 3 + median | 32 | 1.48311 |
| MAD 3 + median | 32 | 1.48292 |
| winsor 1–99 + median | 32 | 1.48320 |
| none + mean | 32 | 1.48428 |
| none + median + **indicators ON** | **49** | 1.48426 |

- Outlier policies **change the transformed data and the metric** (all clipping variants slightly improve val
  logLoss vs none) — policies reach the estimator. ✅
- Missing indicators expand the training matrix **32 → 49** columns. ✅
- **Fold-local proof:** `pitcher_era9` impute fill == dev-2023 median exactly (matchesDevOnly=True); the
  IQR bounds are computed from dev-only percentiles; transforming the frozen mask never mutates fitted state. ✅

---

## 6. Feature engineering (Part E)

All 8 kinds materialize and profile correctly (dev-2023 IV / MI / missingness / drift / histogram):

| Feature | Kind | Max OVR IV | MI | Missing% |
|---|---|---|---|---|
| eng_slg_x_hr | interaction | 0.0674 | 0.01684 | 7.7% |
| eng_high_hr | indicator | 0.0415 | 0.00108 | 0.0% |
| eng_k_to_bb | ratio | 0.0406 | 0.01031 | 8.5% |
| eng_slg_sq | power | 0.0394 | 0.01516 | 7.7% |
| eng_obp_plus_slg | arithmetic | 0.0311 | 0.01536 | 7.7% |
| eng_log_pa | log1p | 0.0220 | 0.00762 | 7.7% |
| eng_month | calendar | 0.0115 | 0.00160 | 0.0% |
| eng_era_bin | quantile-bin | 0.0071 | 0.00175 | 0.0% |

**Compare Base vs Engineered Features** (corrected path, control 22 → challenger 23/30):

| Added | Δ val logLoss | Δ frozen logLoss | Verdict |
|---|---|---|---|
| eng_log_pa | −0.000141 | +0.000040 | VALUE_MARGINAL |
| eng_k_to_bb | −0.000095 | −0.000073 | NO_MATERIAL_VALUE |
| eng_slg_x_hr | +0.000037 | −0.000100 | VALUE_MARGINAL |
| eng_slg_sq | +0.000096 | −0.000127 | VALUE_MARGINAL |
| (arith/era_bin/high_hr/month) | +0.00002…+0.00007 | ~0 | NO_MATERIAL_VALUE |
| **All 8 together (→30 feats)** | **−0.000020** | +0.000115 | NO_MATERIAL_VALUE |

**Best engineered result:** `eng_log_pa` (val −0.000141) — negligible; not production-meaningful. Consistent
with the weak-signal finding. Divide-by-zero uses a safe-div guard; invalid transforms fail with `CockpitError`.

---

## 7. Feature-selection / signal consistency (Part F)

- An 8-feature subset fitted through `Preprocessor` yields exactly those columns in the expanded matrix; the
  14 excluded features **do not leak** into the training matrix (`excludedFeaturesLeakedIntoMatrix = []`). ✅
- Indicators-on expands the same subset's matrix (14 → more columns). ✅
- **Multiclass IV semantics validated:** `batter_so_per_pa` has 8 per-class OVR-IV entries; `maxIv` (0.0722,
  class STRIKEOUT) equals `max(perClass)`; `meanIv` equals `mean(perClass)`. OVR IV is treated as a
  per-class screening signal, not binary IV. ✅

---

## 8. Segmentation (Part G)

| Approach | Batters | Pitchers |
|---|---|---|
| **K-means** recommended K | 2 (== argmax exploratory score) | 2 (== argmax) |
| K-means score weights sum | 1.000 | 1.000 |
| **DBSCAN** recommendation | MOSTLY_ONE_CLUSTER_PLUS_OUTLIERS (noise 5.7%) | MOSTLY_ONE_CLUSTER_PLUS_OUTLIERS (noise 6.3%) |
| DBSCAN noise handling | noise = cluster −1, never forced into an archetype ✅ | ✅ |
| **3×3 grid** top pair | so_per_pa × hr_per_pa (GQS 0.855) | so_per_bfp × bb_per_bfp (GQS 0.841) |
| Grid score == documented formula | True | True |
| Grid suggestions ranked desc | True | True |

K-means recommended-K reproduces the documented weighted composite exactly (Σ weights·components, rounded to
3 dp) for every K = 2..8. DBSCAN eps sweep (0.6×/1.0×/1.5× suggested, min_samples 3/5/10) keeps noise
unassigned. **G4 (segmentation → predictive value):** the platform does not currently convert clusters into
challenger features via an automated path; the grid UI itself states clusters are "exploratory until
predictive-tested via ablation." No predictive segmentation feature was invented.

---

## 9. Temporal policy (Part H) — frozen-2025 protection

| Policy | Folds | Leakage status | 2025 in any training fold? |
|---|---|---|---|
| SEASON_HOLDOUT | 1 | FROZEN_2025_PROTECTED | No (matches governed contract) |
| ROLLING_ORIGIN | 2 | FROZEN_2025_PROTECTED | No — 2025 fold is `FROZEN_EVAL_ONLY` |
| EXPANDING_WINDOW | 2 | FROZEN_2025_PROTECTED | No — 2025 fold is `FROZEN_EVAL_ONLY` |
| DATE_HOLDOUT | 1 | FROZEN_2025_PROTECTED | No (partitions dev-2023 only) |
| RANDOM | 1 | TEMPORAL_ORDER_NOT_PRESERVED (researchOnly=True) | No |

**Absolute requirement met: 2025 is never a training/tuning/selection fold in any policy.** Date-holdout at
2023-05-01 / 07-01 / 09-01 each partitions the 2023 dev season (train+val = 184,104). *(Fix: invalid /
out-of-window boundary dates now raise instead of yielding a val-empty fold — see Defect 6H-2.)*

## 10. Temporal visualization consistency (Part I)
Backend fold roles, row counts, and the frozen note are internally consistent (training `seasons`/`rows`,
validation `season`/`rows`, `frozen` block, `leakageStatus`). No case observed where a policy's declared
role diverged from its fold membership.

---

## 11. Hyperparameter results (Part J)

Bounded sweeps via the real experiment path; selection uses 2024 validation only.

| Family | Best-by-val | Val logLoss | Distinct trial IDs | Best-by-frozen differs? |
|---|---|---|---|---|
| Logistic (C ∈ .05/.2/1/3) | C=0.05 | 1.48415 | Yes | Yes |
| Random Forest (3 configs) | 200/d12/leaf50 | 1.48637 | Yes | No |
| HistGB (3 configs) | 300/lr.05/l2=1 | 1.48407 | Yes | No |

Trials genuinely differ; best is chosen on validation; frozen never participates in selection. Tuned HGB
(1.48407) edges the reproduced champion (1.48411) by 4e-5 — within noise; **not promoted.**

## 12. Autopilot (Part K)

| Budget | Candidates | Best | Beats champion (2024)? | Runtime | Selection basis |
|---|---|---|---|---|---|
| quick | 2 | Logistic C=0.05 | No | 16.4 s | 2024 validation only |
| standard | 4 | Logistic C=0.05 | No | 47.8 s | 2024 validation only |

Autopilot launches multiple candidates into an honest leaderboard, is bounded per budget, states "2024
validation only" in its limitations, and does not touch the champion or manual experiments.

---

## 13. Persistence (Part M)
Executable evidence at the store/persistence layer: dataset selection and target confirmation live in the
project-scoped autosave `notes` slice (`cockpitStorageKey(projectId)`), which is snapshotted and rehydrated
before paint. The 6G.2 + 6E.4 frontend suites assert the durable slices (config, notes, engineeredProfiles,
savedSteps, labSuite, activeStep) and project A/B key isolation. **Not re-verified via live browser
automation** (unavailable this session) — asserted at source + unit-test level, consistent with prior phases.

## 14. Leakage / model-risk audit (Part N)
- Target `outcome` is **not** in the feature list. ✅
- No identifier columns (`game_id/batter_id/pitcher_id/game_pk/player_id`) in the feature list. ✅
- `Preprocessor` fits all statistics on **dev-2023 only**; transforming the frozen mask leaves fitted state
  byte-identical (`stateUnchangedByFrozen=True`) and produces finite output. ✅
- IV / MI / correlation are computed on the development fold; validation/frozen appear only as descriptive
  out-of-time evidence. ✅
- `bin` quantile edges are fit on dev-only (`dev_mask`), so engineered binning cannot see 2024/2025. ✅

## 15. Metrics verification (Part R)
Independent recomputation from the logistic model's val-2024 probabilities:

| Metric | Engine | Independent | Match |
|---|---|---|---|
| Log loss | 1.484253 | 1.484253 | ✅ (<1e-4) |
| Top-1 accuracy | — | — | ✅ (<1e-6) |
| Macro-F1 | — | — | ✅ (<1e-6) |
| Brier (mean summed one-vs-all sq err) | — | — | ✅ (<1e-4) |

Probability rows sum to 1.0 (atol 1e-6) across all 182,449 val rows; all **8** classes present; class order
matches the frozen taxonomy.

## 16. Performance / stability (Part P)
Section runtimes (single process, n_jobs=-1 for tree/boosting): model zoo 205 s (8 families), preprocessing
50 s (7 fits), feature-engineering 134 s, tuning 148 s, autopilot 64 s, segmentation 3.6 s, temporal 0.3 s,
metrics 7.6 s, adversarial 7.7 s. No memory growth, orphan processes, DB locks, or duplicate-run loops
observed. Champion baseline is cached (fit once). Feature-profile is disk-cached (version-keyed).

---

## 17. Defect register (Part T)

| ID | Sev | Page/System | Symptom | Root cause | Scientific impact | Repro | Fix | Test | Status |
|---|---|---|---|---|---|---|---|---|---|
| 6H-1 | **P2** | Feature Eng · Compare Base vs Engineered | `run_ablation` given `addEngineered` specs but no `addFeatures` names left the engineered column materialized-but-unused → challenger==control, Δ=0, "NO_MATERIAL_VALUE" | challenger `features` list didn't include engineered names derived from specs | A programmatic ablation could silently under-report engineered value (the live UI passes `addFeatures` too, so the app path was unaffected) | `run_ablation({baseConfig, addEngineered:[spec]})` → challenger 22 == control 22 | Derive names from `addEngineered` specs, dedupe into challenger features | `test_ablation_uses_engineered_feature_from_specs_only_and_dedupes_names` | **Fixed** |
| 6H-2 | **P2** | Temporal Split · DATE_HOLDOUT | An invalid/out-of-window boundary date returned a degenerate fold (train 184,104 / **val 0**) with HTTP 200 instead of failing | boundary date passed through unvalidated | A silent empty-validation fold could mislead a date-based experiment | preview `DATE_HOLDOUT` with `"not-a-date"`, `"2024-07-01"`, `"2022-01-01"` | Parse + range-check the date; raise `CockpitError` (surfaces as 422) unless within the 2023 dev window | `test_date_holdout_rejects_invalid_or_out_of_window_dates` | **Fixed** |
| 6H-3 | P3 | Model Lab · run_experiment | An explicit empty `features:[]` silently falls back to all 22 features (`[] or ALL_FEATURES`) rather than erroring | defensive-default `or` semantics | Minimal — UI never sends empty; a stricter guard risks callers relying on omission→default | `run_experiment({features:[]})` returns a full 22-feature run | **Accepted, not fixed** (documented) | — | Accepted |
| 6H-4 | — | Segmentation · DBSCAN | eps ≤ 0 does not error | intentional clamp to suggested eps | None — graceful fallback to the suggested eps (1.913), 1 cluster + 5.7% noise | `run_dbscan(eps=0)` returns clamped result | No change (correct behavior) | covered by campaign | Not a defect |

**No P0 (integrity/security) or P1 (major functional) defects were found.**

## 18. Repairs made
- `server/sports_cockpit/modeling.py` — `run_ablation` now includes engineered-feature names from
  `addEngineered` specs in the challenger feature set (deduped), so spec-only callers get a real comparison.
- `server/sports_cockpit/engine.py` — `temporal_split_preview` DATE_HOLDOUT validates the boundary date
  (parseable and inside the 2023 development window) and raises `CockpitError` otherwise.

## 19. Tests added
`tests/sports_cockpit_phase6h_test.py` — **16 tests** codifying the guarantees exercised above: 8-family
availability, config-hash identity + indicator propagation, dev-only fold-local preprocessing,
frozen-never-in-training across all 5 policies, date-holdout dev-only partition, every engineered kind
materializes/profiles, invalid-spec rejection, the two fixes (6H-1, 6H-2), K-means/DBSCAN/grid formulae,
autopilot bounded + validation-only, probabilities-sum-to-1 + independent-metric reproduction, and
target/identifier exclusion.

## 20. Tests executed
- **Backend:** `sports_cockpit_phase6h` 16 passed; regression `sports_cockpit_phase6f` + `phase6g1` 18 passed.
- **Frontend:** cockpit6g2 (12), cockpit6g1 (10), cockpitModelLab (12), paModelingCockpit (16),
  cockpitFeatureUi (14), cockpitNavAndPopulation (9) — all pass.
- **TypeScript** `tsc -b` clean · **production build** clean · **py_compile** (engine, modeling) OK.
- **Live:** backend restarted; `/api/health`=200, login=200; DATE_HOLDOUT valid=200, invalid=422 (fix live).

---

## Readiness ratings (Part V) — 1–5

| Dimension | Rating | Notes |
|---|---|---|
| Scientific correctness | 5 | Metrics reproduce independently; leakage guards enforced |
| Data authority | 5 | Roles verified from engine; single governed dataset; target authority explicit |
| Temporal integrity | 5 | Frozen 2025 excluded from every fit/tune/selection fold; invalid dates now rejected |
| Preprocessing | 5 | Fold-local dev-only; policies provably propagate; indicators expand matrix |
| Feature engineering | 4 | All 8 kinds work + honest ablation; 6H-1 spec-only no-op fixed; weak real signal |
| Segmentation | 4 | Formulae transparent + reproducible; predictive-value path is manual, not automated |
| Model Laboratory | 5 | 8 families train with distinct hashes; honest leaderboard; no auto-promotion |
| Hyperparameter tuning | 4 | Real bounded sweeps, val-only selection; no dedicated endpoint (sweeps via run) |
| Persistence | 4 | Store/notes durable + project-scoped; not re-verified via live browser this session |
| Auditability | 5 | Config hashes, leakage guards, reproducible metrics, cached champion |
| UX clarity | 4 | 6G.2 authority flow solid; ablation label clarified; date-picker should bound input |
| Performance / stability | 5 | Bounded runtimes, no leaks/orphans/locks |

**OVERALL MODEL-DEVELOPMENT READINESS: SCIENTIST TESTING READY.**

---

## Remaining limitations
- The governed 22-feature view has **weak separating power** for the 8-class PA outcome (all families ≈
  1.484 val logLoss, macro-F1 ~0.08–0.10). Meaningful gains likely require premium contact-quality data
  (consistent with Phase-4F). This is a data/feature reality, not a platform defect.
- Segmentation → predictive-feature conversion is manual (no automated cluster-feature challenger).
- Hyperparameter tuning is realized as bounded experiment sweeps, not a dedicated optimizer endpoint.
- Persistence and full click-through were validated at API/store/test level; **no browser automation** was
  available this session.

## Recommended next scientist actions
1. Treat premium contact-quality / batted-ball features as the highest-leverage next investment.
2. Keep logistic (or SVM) as the reference; boosting does not help on the current features.
3. If pursuing segmentation value, add an explicit cluster-membership challenger feature and ablate it.
4. Constrain the DATE_HOLDOUT date picker in the UI to the 2023 dev window (backend now enforces it).
5. Do **not** promote any 6H challenger — none materially beats D3/C4 on validation.

---

### Guarantees (this campaign)
- **Frozen 2025:** used in fitting/tuning/selection = **0 rows / 0 folds** across all families, policies,
  sweeps, and autopilot; every experiment carries `frozenSeasonExcludedFromFitting=True`; preprocessor state
  is byte-identical before/after a frozen transform.
- **D3/C4 champion:** never retrained, overwritten, or modified; used only as a read-only in-pipeline
  reference baseline. All challengers ran `persist=False`; the experiment registry was not written.
- **Target/authority:** target `outcome` unchanged; development authority (2023) unchanged; 2021/2022 never
  added as Gen-2 target rows; no data fabricated; no auth/isolation weakened; no push; main untouched.
