# MLB Core Challenger — Compact Leakage-Safe Tuning Study

Status: `COMPLETE — GOVERNED TUNING DECISION FROZEN`

This report closes the Development-only Histogram Gradient Boosting (HGB) and Random Forest (RF) tuning assignment. It creates no champion, finalist, production, promotion, export, deployment, merge, calibration, explanation, feature-refinement, simulation, or Final OOT authority.

## 1. Starting and ending commit

- Starting commit: `c8fa254209eeea15b94d24e056cc63d1500c0da8`.
- Ending implementation/evidence commit: recorded in the final handoff after the commit is created (a Git commit cannot contain its own hash).
- Frozen tuning decision receipt: `c1749dfe477859248dbf88b0cd7af511662be0fd848589a7fa5f943fce96dac2`.
- Complete model-run receipt: `c9ffcc867a73eac6c287309f34889390dedf8484244c3bf5c2ed20dacecaf635`.

## 2. Exact grids evaluated

Signed plan: `stage3-model-plan-0ff4c996e2eeb52859de673a2dfccbc6`; checksum `0ff4c996e2eeb52859de673a2dfccbc68ed74c95cdd59593f029421a10a54fd0`.

| Family | Configuration |
|---|---|
| HGB | `learning_rate=0.03`, `max_iter=500`, `max_leaf_nodes=31`, `max_depth=None`, `min_samples_leaf=50`, `l2_regularization=1.0`, `early_stopping=False` |
| HGB | `learning_rate=0.07`, `max_iter=300`, `max_leaf_nodes=31`, `max_depth=None`, `min_samples_leaf=20`, `l2_regularization=1.0`, `early_stopping=False` (exact first-screen refit) |
| HGB | `learning_rate=0.10`, `max_iter=200`, `max_leaf_nodes=63`, `max_depth=None`, `min_samples_leaf=20`, `l2_regularization=10.0`, `early_stopping=False` |
| RF | `n_estimators=300`, `max_depth=24`, `min_samples_leaf=5`, `max_features=sqrt`, `bootstrap=True`, `class_weight=None` (exact first-screen refit) |
| RF | `n_estimators=500`, `max_depth=None`, `min_samples_leaf=20`, `max_features=0.5`, `bootstrap=True`, `class_weight=None` |

Early stopping was disabled, so no random internal validation split existed. Class weighting remained disabled because no scientific authority was adopted for it. Every learned transformation and empirical-Bayes prior was fitted inside each registered training fold only.

## 3. Total fits and runtime

- Five configurations and 25 official chronological-fold fits completed; failures: 0.
- Complete job: `stage3-model-job-868994bcbea340bfa9f311b909c9ba70`.
- Complete model run: `stage3-model-development-run-eafabbbfcad644a8b151f52ffd7e049a`.
- Observed run runtime: 30,544,776 ms (8 h 29 m 4.776 s).
- Pre-fit estimate: 14,994,027 ms raw and 17,243,131 ms (4 h 47 m 23.131 s) with 15% contingency, below the declared five-hour operational ceiling; therefore no deterministic pre-fit reduction was applied.
- The estimate scaled RF only by tree count. It materially understated the computational cost of `max_features=0.5` versus `sqrt`; the 500-tree RF candidate consumed 17,938,923 ms (4 h 58 m 58.923 s). This variance is an operational limitation, not a result-based reason to prune the completed scientific comparison.
- One initial sandboxed infrastructure attempt is preserved as job `stage3-model-job-0f74167f054543308019f4c971addbb5`, run receipt `4e5547b574f80f0088f6bc2ac37280eeafb54537f5f7cfea72c7b31884ebbd27`. Windows denied process/temp access before any fold completed: 0 completed fits, no metrics, and `usedForSelection=false`. The identical signed plan was then executed with normal Windows process access.

## 4. Null baseline metrics

The immutable class-frequency null had mean five-fold log loss `1.4963720812`, summed multiclass Brier `0.7119314081`, ECE `0.0057444690`, and macro one-versus-rest ROC-AUC `0.5005389548`. Best HGB improved log loss over null by `0.0218294037` (relative `1.458822%`); best RF improved it by `0.0183640919` (relative `1.227241%`).

## 5. First-screen versus tuned metrics

| Family | First-screen LL | Tuned LL | Absolute gain | First AUC | Tuned AUC | First Brier | Tuned Brier | First ECE | Tuned ECE |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| HGB | 1.4772751225 | 1.4745426775 | 0.0027324450 | 0.5732568081 | 0.5773117546 | 0.7038735612 | 0.7030475763 | 0.0066642124 | 0.0046859880 |
| RF | 1.4797935541 | 1.4780079893 | 0.0017855648 | 0.5566344391 | 0.5600701291 | 0.7045542002 | 0.7039786140 | 0.0091704555 | 0.0067931643 |

Both tuned families improved log loss, Brier, ECE, and macro OVR ROC-AUC versus their exact immutable first-screen configurations.

## 6. Five-fold results

| Family | Fold | Validation period | Rows | Log loss | Brier | ECE | Macro OVR AUC | Runtime ms |
|---|---:|---|---:|---:|---:|---:|---:|---:|
| HGB | 1 | 2024-03-20—2024-07-06 | 99,782 | 1.4800739512 | 0.7036905276 | 0.0115767664 | 0.5757677486 | 551,046 |
| HGB | 2 | 2024-07-07—2025-04-15 | 100,269 | 1.4801581927 | 0.7054844558 | 0.0049764250 | 0.5773974624 | 770,829 |
| HGB | 3 | 2025-04-16—2025-07-27 | 99,968 | 1.4666641076 | 0.7002152129 | 0.0039681913 | 0.5770361835 | 966,910 |
| HGB | 4 | 2025-07-28—2026-05-01 | 100,304 | 1.4749103240 | 0.7045267023 | 0.0026953601 | 0.5777422445 | 1,131,371 |
| HGB | 5 | 2026-05-02—2026-08-13 | 101,267 | 1.4709456993 | 0.7013321607 | 0.0008196180 | 0.5824358527 | 1,353,616 |
| RF | 1 | 2024-03-20—2024-07-06 | 99,782 | 1.4813928659 | 0.7039610476 | 0.0158514073 | 0.5591007934 | 1,248,058 |
| RF | 2 | 2024-07-07—2025-04-15 | 100,269 | 1.4832263875 | 0.7062539384 | 0.0070515854 | 0.5608715171 | 2,258,306 |
| RF | 3 | 2025-04-16—2025-07-27 | 99,968 | 1.4701837580 | 0.7010836742 | 0.0064523228 | 0.5635175140 | 3,445,287 |
| RF | 4 | 2025-07-28—2026-05-01 | 100,304 | 1.4794072884 | 0.7057921462 | 0.0037030409 | 0.5588377092 | 4,738,376 |
| RF | 5 | 2026-05-02—2026-08-13 | 101,267 | 1.4758436527 | 0.7028045407 | 0.0021554295 | 0.5586502778 | 6,240,119 |

HGB worst-fold log loss was `1.4801581927` with fold SD `0.0052397324`; RF worst-fold log loss was `1.4832263875` with fold SD `0.0046162759`.

## 7. Calibration and Brier results

Best HGB led on aggregate Brier (`0.7030475763` versus RF `0.7039786140`) and ECE (`0.0046859880` versus RF `0.0067931643`). Calibration improved over each family’s first screen. ECE generally declined in later folds, but this is descriptive Development evidence and not calibration-stage authority.

## 8. Per-class findings

HGB had higher one-versus-rest ROC-AUC in all eight outcome classes: STRIKEOUT `0.60870` vs `0.60538`; WALK_HBP_CI `0.59848` vs `0.58619`; HOME_RUN `0.58968` vs `0.57638`; SINGLE `0.54528` vs `0.54035`; DOUBLE `0.52921` vs `0.52111`; TRIPLE `0.58830` vs `0.53835`; BIP_OUT `0.56242` vs `0.55995`; OTHER_REACH `0.59641` vs `0.55286`. RF had a slightly lower DOUBLE one-vs-rest Brier (`0.04032544` vs HGB `0.04034003`) and lower TRIPLE absolute calibration error (`0.00020956` vs `0.00036304`), but not a class-specific AUC win.

## 9. Game-clustered uncertainty

All paired analyses used 501,590 OOF rows, 6,664 canonical-game clusters, 2,000 paired nonparametric resamples, and seed `20260907`.

- HGB tuning gain (best minus same-run exact first-screen refit): `-0.0027324450`; 95% CI `[-0.0029933446, -0.0024596499]`; SE `0.0001345817`; improvement in all five folds.
- RF tuning gain: `-0.0017855648`; 95% CI `[-0.0020450439, -0.0015294170]`; SE `0.0001328394`; improvement in all five folds.
- HGB minus RF: `-0.0034653118`; 95% CI `[-0.0038827842, -0.0030509715]`; SE `0.0002119757`; HGB had lower loss in all 2,000 resamples.
- HGB-minus-RF fold differences were `-0.0013189`, `-0.0030682`, `-0.0035197`, `-0.0044970`, and `-0.0048980`: consistent across folds, practically material relative to the predeclared `0.0001` threshold, and outside estimated uncertainty. This supports a Development-only difference, not a champion or production claim.

## 10. Probability reconciliation

All ten reported best-model fold matrices passed. Across 501,590 OOF rows per model there were zero non-finite, negative, or above-one values. Maximum absolute row-sum error was `4.44e-16` for HGB and `2.00e-15` for RF, both below tolerance `1e-8`. OOF artifacts include `canonicalPaId`, `canonicalGameId`, fold number, observed class index, and all eight probability columns under content hashes.

## 11. Best configuration in each family

- HGB: `learning_rate=0.03`, `max_iter=500`, 31 leaves, `min_samples_leaf=50`, L2 `1.0`, no early stopping. Candidate receipt `561e3493f950d26b1f8c17b2cc783af1f349452745c01104ec72aaab76bf9e9e`; fingerprint `stage3-candidate-spec-1ec3254db5892cf4c7105c081942286e86b0ee85a78f433540195d978f9fc9af`.
- RF: 500 trees, unlimited depth, `min_samples_leaf=20`, `max_features=0.5`, bootstrap enabled, no class weighting. Candidate receipt `15e7e65f2cf6931fc57b922f3be5fdce1e9244b38b31582d026db7d15cd45440`; fingerprint `stage3-candidate-spec-d3ec6d19d88f05b73dd1f3a0ec8b3a28166b48a06421a03059ea991695373c46`.

## 12. Complexity and runtime tradeoffs

HGB’s best configuration had complexity score 15,500 and runtime 4,782,668 ms. RF’s best had complexity score 64,000 and runtime 17,938,923 ms: about 3.75 times HGB’s runtime for a log loss worse by `0.0034653`. The simpler first-screen RF refit ran in 1,996,110 ms but lost `0.0017856` log loss to the broad forest. Candidate-specific peak memory was not measurable on this Windows host: process instrumentation returned `UNAVAILABLE_ON_HOST` / `OSError`; the receipt preserves that limitation rather than inventing a value.

Probability diversity remained meaningful: mean absolute probability difference `0.01149184`, mean total-variation distance `0.04596736`, and predicted-class disagreement `0.02763213`.

## 13. Advancement decisions

- HGB: `ADVANCE_TO_REFINEMENT`. It leads mean and worst-fold log loss, Brier, ECE, macro AUC, every class AUC, runtime, and the clustered comparison.
- RF: `RETAIN_AS_DIVERSITY_CHALLENGER`. It achieved a consistent material tuning gain and nontrivial probability/predicted-class diversity, although it did not win any class AUC and is substantially more expensive.
- Logistic: `REQUIRES_REPAIR` backlog only—five first-screen convergence warnings at `max_iter=1000`; not repaired or tuned.
- SGD: `REQUIRES_REPAIR` backlog only—first-screen probability reconciliation failed in all five folds; not repaired or tuned.

No feature refinement was executed. These labels are tuning dispositions only.

## 14. UI evidence

Model Laboratory and Candidate Evaluation both render the frozen tuning receipt without starting model activity, with shared null metrics, first screen versus tuned results, exact gains, all five folds, worst fold, dispersion, Brier, ECE, AUC, probability reconciliation, runtime, complexity, exact hyperparameters, status, candidate fingerprint, and immutable run receipt. The log-loss chart uses an explicitly labeled zoomed axis and exact table values so small differences are readable without hiding scale truncation. Finalist selection and downstream analysis controls are held closed once the tuning decision exists.

- [Signed-in Model Laboratory evidence](mlb-core-challenger-tuning-screenshots/model-laboratory.png) — frozen HGB/RF decision, shared null, both dispositions, and sealed Final OOT.
- [Signed-in Candidate Evaluation evidence](mlb-core-challenger-tuning-screenshots/candidate-evaluation.png) — the same content-addressed tuning decision with no finalist or promotion authority.

## 15. Tests and build

- Focused Python preflight: 46 passed.
- Frontend contract preflight: 16 passed.
- Python compilation preflight: passed.
- Production frontend build preflight: passed; only existing bundle-size and stale browser-metadata warnings.
- Post-result focused Python suite: 79 passed with 23 non-failing deprecation/runtime warnings.
- Post-result frontend contract suite: 16 passed.
- Post-result Python compilation: passed.
- Post-result production frontend build: passed; only existing bundle-size and stale browser-metadata warnings.
- Live signed-in UI verification and screenshots: recorded in Section 14 after final capture.

## 16. Final OOT access counters proving it remained sealed

Authority remained Development `683,662` rows, five chronological folds, Treatment V14, 218 predictors, 21 governed priors, 16 deferred fields, three scientific retirements, and Final OOT `14,067` rows. Terminal counters are: `locked=true`, `targetAccessed=false`, `scored=false`, `accessed=false`, and `targetsMaterialized=false`. Clustered analyses separately record `finalOotTargetAccessed=false`. No Final OOT predictions, distributions, or metrics were read.

## 17. Final branch and commit

- Branch: `codex/mlb-governed-prior-engine-v1`.
- Final commit: recorded in the final handoff after commit creation.

## 18. Explicit non-action confirmation

Nothing was promoted, exported, deployed, or merged. No champion, finalist, or production-ready label was assigned. No feature definition, population, fold, target, prior, preprocessing authority, or class weighting policy changed. Feature refinement, calibration, SHAP, recursive feature elimination, simulation integration, and Final OOT remain later governed stages. Work stopped at the frozen tuning decision.
