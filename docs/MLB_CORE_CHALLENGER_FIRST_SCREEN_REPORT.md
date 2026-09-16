# MLB Core Challenger — First Development Screen Report

Status: **Development-only screen complete; two candidates approved only for bounded tuning.** No champion was selected, no model was promoted or exported, and Final OOT remained sealed.

Project: `asp-mtlozhdx` — **MLB 2026 Current-Data Challenger v2 — Deliberate Development**  
Starting Git HEAD: `711c41e23b340cd859528ba3cbd8c5e2b573f912`  
Implementation commit: the commit containing this report; its exact HEAD is reported in the delivery handoff because a commit cannot content-address itself.  
Decision: `MLB_CORE_CHALLENGER_FIRST_SCREEN_DECISION`  
Decision receipt SHA-256: `7591e3994e7cf4094a5fd841d8b43fcaf1f6d372cd16b8551169079761b6322a`

## 1. Target and model contract

The project-level forecast contract is `sports-forecast-contract:asp-mtlozhdx:v1:sha256:352e3438d7ddbafab988132befc7d42e50d73acba0628f653ccdb38b98a1ece8`. Its primary product target remains `JOINT_SCORE_DISTRIBUTION`, with intended outputs `JOINT_SCORE_DISTRIBUTION`, `HOME_WIN_PROBABILITY`, `EIGHT_CLASS_PA_OUTCOME`, `RUN_DIFFERENTIAL`, and `TOTAL_RUNS`.

This bounded screen evaluates only the governed plate-appearance component `EIGHT_CLASS_PA_OUTCOME`. The prediction unit is one plate appearance; row identity is `canonicalPaId`; grouping identity is `canonicalGameId`; target field is `outcome`; task type is eight-class probabilistic classification. Ordered classes are:

1. `STRIKEOUT`
2. `WALK_HBP_CI`
3. `HOME_RUN`
4. `SINGLE`
5. `DOUBLE`
6. `TRIPLE`
7. `BIP_OUT`
8. `OTHER_REACH`

Development prevalence was: `BIP_OUT` 308,513 (45.1265%), `STRIKEOUT` 153,309 (22.4247%), `SINGLE` 96,978 (14.1851%), `WALK_HBP_CI` 66,017 (9.6564%), `DOUBLE` 29,249 (4.2783%), `HOME_RUN` 21,061 (3.0806%), `OTHER_REACH` 6,016 (0.8800%), and `TRIPLE` 2,519 (0.3685%). The largest-to-smallest class ratio is 122.47. Maximum season-to-season change in largest-class share is 1.2115 percentage points; the minimum rare-class season count is 494 (2026). The screen therefore treats accuracy and macro-F1 as diagnostics, not selection metrics.

No same-project governed model receipt matching this feature/treatment/split contract existed at screen start. The historical rushed pilot was excluded. The only baseline is fold-training prevalence.

## 2. Treatment identity and immutable ancestry

The immutable predecessor remains V8:

- Specification ID: `stage3-feature-treatment-spec-df0a0d98784d4de6b30c4dcc1a7aef8a`
- Manifest SHA-256: `9e38ab918d216cd25d85c58248a589aeca2f12cad447b8469f9770aa47e4479b`
- Compiler SHA-256: `06a6d26e09dc6695289f71de0a709de2fbac6f9890c57ebb115bd0d24339beb4`

The scientific deferral and Core construction produced append-only intermediate receipts while transitive-derived bindings were audited. The definitive adopted combined successor is immutable V14:

- Specification ID: `stage3-feature-treatment-spec-cd6c877bc9474fa7ab2b716209321d78`
- Receipt/content SHA-256: `74071f88294f299de33a990e655481ee8b778e0f91bdfc79bc67a4ab7d6010eb`
- Manifest SHA-256: `ba36557bb986f87be40dc18a4a669f4e5d4f979becf2d0e70fda5226f15f544d`
- Authority key: `MLB_FEATURE_TREATMENT_SPEC_V1:sha256:ba36557bb986f87be40dc18a4a669f4e5d4f979becf2d0e70fda5226f15f544d`

V8 was neither edited nor reinterpreted. V14 binds the approved Wave 1/2 prior engines, scientific retirement decisions, exact adopted outlier/missing treatment, and fail-closed transitive exclusions. Superseded intermediate Core registrations remain immutable history and carry no evidence into the definitive screen.

## 3. Core feature inventory, priors, missingness, and leakage controls

The Core feature set contains 218 predictors:

| Family | Count |
|---|---:|
| Core Gold 48 eligible fields | 45 |
| Calendar | 23 |
| Rest/travel | 54 |
| Circadian | 30 |
| Division/repeat-opponent context | 14 |
| Governed interactions | 12 |
| Missingness indicators | 40 |
| **Total** | **218** |

The 14 included division/repeat-opponent fields are not the unresolved explicit rivalry fields listed in §4. In addition to the exact 16-source-field ledger, eleven dependent bindings are transitively excluded: `is_doubleheader`, `batting_doubleheader_today`, `fielding_doubleheader_today`, both doubleheader×short-rest interactions, `is_holiday`, `is_holiday_eve`, both home×holiday interactions, and both holiday-calendar-missing indicators. `fielding_doubleheader_yesterday` and `batting_doubleheader_yesterday` remain because they use completed prior-day game evidence rather than the unresolved target-game schedule sequence. `holiday_region` remains as venue-region metadata and does not assert holiday NONE-versus-UNKNOWN semantics. All identifiers, targets, post-outcome fields, retired fields, deferred-context fields, source-unavailable fields, and coverage-blocked fields are excluded before model-matrix construction.

Twenty-one player-state predictors execute as fold-local governed posterior means. Wave 1 beta-binomial features are `pitcher_so_per_bfp`, `pitcher_hr_per_bfp`, `pitcher_hbp_per_bfp`, `pitcher_bb_per_bfp`, `batter_so_per_pa`, `batter_hr_per_pa`, `batter_bb_hbp_per_pa`, `pitcher_last250_walk_rate`, `pitcher_last250_strikeout_rate`, `batter_last100_walk_hbp_rate`, and `batter_last100_strikeout_rate`.

Wave 2 features are:

- `GAMMA_POISSON_COMPONENT_SHRINKAGE`: `pitcher_whip`.
- `BETA_BINOMIAL_OR_TWO_CELL_DIRICHLET_EMPIRICAL_BAYES`: `pitcher_gs_per_g`, `pitcher_last250_whiff_rate`, `batter_last100_whiff_rate`.
- `DIRICHLET_MULTINOMIAL_EMPIRICAL_BAYES`: `batter_slg`, `batter_avg`, `pitcher_last250_offspeed_usage`, `pitcher_last250_fastball_usage`, `pitcher_last250_breaking_usage`.
- `NORMAL_NORMAL_EMPIRICAL_BAYES`: `pitcher_last250_avg_fastball_velocity`.

Three features remain preserved but nonselectable under `RETIRED_NONSELECTABLE_BY_SCIENTIFIC_DECISION`: `pitcher_era9`, `batter_obp`, and `batter_last100_contact_rate`.

Highest governed raw gaps are `pitcher_whip` at 10.8065%, other annual pitcher priors at approximately 10.7983%, annual batter priors at approximately 7.7238%, and rolling priors near 1%. At least one prior family is cold-started for 178,400 rows (26.0948%); those rows remain modelable through fold-local posterior treatment plus explicit indicators. No included field has 25% or greater missingness. Three included categoricals are low-cardinality: `holiday_region` (27 levels), `game_day_of_week` (7), and `season_phase` (3), all with 0% missingness. Identifier columns are not predictors.

The full Development profile finds 25 exact-constant predictors. Three are `matchup_pitcher_hand_missing`, `matchup_batter_hand_missing`, and `matchup_batter_bats_switch`; the other 22 are paired batting/fielding indicators for team-home-timezone missing, team-alignment missing, recent-bullpen-workload missing, previous-venue-altitude missing, previous-game-end-time missing, previous-game-end missing, pregame-temperature missing, current-venue-timezone missing, current-venue-coordinates missing, current-venue-altitude missing, and current-start missing. At a diagnostic—not policy—threshold of 99.5% dominant-value share, five additional fields are near-constant: batting and fielding `early_start_after_eastward_travel`, batting and fielding `circadian_early_east_component`, and `batter_last100_whiff_missing`. There are no high-cardinality one-hot fields above 50 levels. These fields are disclosed rather than silently rewriting immutable V4; exact constants contribute no fitted signal, while any reduced tuning set must be a new content-addressed descendant.

There is no feature-construction row loss. Selection is allow-list based, all derived dependencies are checked, and all preprocessing/prior fitting is restricted to each training fold before validation transformation.

## 4. Exact 16-field contextual deferral ledger

Decision `MLB_CORE_CHALLENGER_CONTEXT_DEFERRAL_V1` sets all 16 fields to `DEFERRED_CONTEXT_AUTHORITY`, with `executable=false`, `preprocessingExecutable=false`, `selectable=false`, `rawFeatureSelectable=false`, and `transitivelyReachable=false` for dense and tree-native paths.

| Field | Preserved scientific reason | Core status |
|---|---|---|
| `doubleheader_game_number` | Pregame schedule authority does not preserve original knowledge timestamps or an independently verified `{0,1,2}` scheduled-order invariant. | Deferred; no value, imputation, transform, or reachability |
| `holiday_name` | Holiday rules are embedded code, not a separately sourced, registered, effective-dated venue-region calendar; null cannot distinguish verified non-holiday from unknown. | Deferred; derived holiday indicator is also unreachable |
| `batting_rivalry_pair` | Rivalry-pair mapping is proposed, not approved source authority. | Deferred and unreachable |
| `batting_rivalry_game` | Depends on unapproved batting rivalry-pair authority. | Deferred and unreachable |
| `batting_home_rivalry_game` | Depends on unapproved rivalry authority and home interaction. | Deferred and unreachable |
| `batting_friday_night_home_rivalry` | Depends on unapproved rivalry authority plus temporal/home parents. | Deferred and unreachable |
| `batting_weekend_home_rivalry` | Depends on unapproved rivalry authority plus temporal/home parents. | Deferred and unreachable |
| `batting_home_x_rivalry` | Depends on unapproved rivalry authority and home parent. | Deferred and unreachable |
| `batting_rivalry_mapping_missing` | Would encode the unresolved mapping authority itself. | Deferred and unreachable |
| `fielding_rivalry_pair` | Rivalry-pair mapping is proposed, not approved source authority. | Deferred and unreachable |
| `fielding_rivalry_game` | Depends on unapproved fielding rivalry-pair authority. | Deferred and unreachable |
| `fielding_home_rivalry_game` | Depends on unapproved rivalry authority and home interaction. | Deferred and unreachable |
| `fielding_friday_night_home_rivalry` | Depends on unapproved rivalry authority plus temporal/home parents. | Deferred and unreachable |
| `fielding_weekend_home_rivalry` | Depends on unapproved rivalry authority plus temporal/home parents. | Deferred and unreachable |
| `fielding_home_x_rivalry` | Depends on unapproved rivalry authority and home parent. | Deferred and unreachable |
| `fielding_rivalry_mapping_missing` | Would encode the unresolved mapping authority itself. | Deferred and unreachable |

Definitions, formulas, source references, and audit evidence are preserved for a later contextual-authority wave. None is approved, populated, imputed, transformed, selected, or available through a parent/child interaction.

## 5. Adopted outlier and missing-data policies

Outlier policy `stage3-outlier-policy-ee0b39ba63104e778a42a30c33286b08` (SHA-256 `988096cef12579f1e4fffc700a510a9d34771928e28000d605939c18775cc196`) adopts global `NO_STATISTICAL_DETECTION` and treatment `RETAIN`. Any estimator-specific thresholds are training-fold fitting rules, never globally learned clipping authority.

Missing-data policy `stage3-imputation-policy-d0635213679c4f3394f93f7ec8332067` (SHA-256 `a674e9d0b4940806fca46df1dd1952d13c1efee232cfb30f28898bcc24535882`) adopts `RETAIN_WITH_INDICATOR`. The 21 player-state priors use their governed empirical-Bayes transforms. Other supported transforms are fit only on the current training fold, then applied to its validation fold. Deferred, retired, source-unavailable, and coverage-blocked fields receive no fallback.

## 6. Content-addressed authority identities and rights

- Dataset version: `asp.mlb.statcast.current-pa.v1:partition-authority-sha256:6e134d8726587ad88d0807effb6e6b12ad39f39b99acb7f523ae6ae98155df34`
- Source manifest: `03ca6dab30e760b2b86b65308090c2d358a67127cc34dfde7a75fc198c3ba84c`
- Gold manifest: `67de02ce19738b29953341151640fb69244b764b0e532b687ab6bacedbb3f758`
- Context manifest: `4c228116951a3505d6a5d955f00cd2b92b35b1ccb85c7c69d11d77828485320e`
- Review digest: `af3e10a6d62537a57c2513a9ed6e96d44e5c7d5a6fdcf845a9fcb097ed8afe41`
- Feature set: `stage3-feature-set-88778f53db6b42d2815ac04e3e7e55e5`, key `MLB_CORE_CHALLENGER_V4`, SHA-256 `f144e186b29a4fb885050921b75decd45dab64c9badc7226b4d72ad99cced2e6`
- Split: `stage3-split-contract-87fdac0b668d4c9b862a2fd8f0760342`, version 8, SHA-256 `8f2a3559548e6d5cb2a9abc4d4030216e2fd4e7e16c52351450588465b63f70d`
- Wave 1 prior: `MLB_PLAYER_STATE_PRIOR_AUTHORITY_V1:sha256:9e5a265fe6af876dd5facb9f5f0425f887e34508730eb273abe347a279e676bd`
- Wave 2 prior: `MLB_PLAYER_STATE_PRIOR_AUTHORITY_V2:sha256:9d9cfaf34f87be67f7d3ab2b8b024d83a6fc5e8abe0dde8de7be0866f1b8366e`
- Five-fold prior contract: `MLB_PLAYER_STATE_PRIOR_FIVE_FOLD_CONTRACT_V1:sha256:cd72058500333f9fae8dcb11867dbc674a015f2c84585ccb3cd81bf62c437d31`

Effective rights are the intersection of FD1/Lahman and MLB Statcast authority: `GOVERNED_LOCAL_RESEARCH_ONLY`, permitted use `LOCAL_PRIVATE_MODEL_DEVELOPMENT`, attribution obligations retained, and explicit commercial-rights review required.

## 7. Development population and chronological folds

Development contains 683,662 plate appearances in 9,070 games from 2023-03-30 through 2026-08-13. The expanding-window split is deterministic, grouped by game, chronological, and five-fold. Its validation union contains 501,590 rows.

| Fold | Training rows / games | Training through | Validation rows / games | Validation interval |
|---:|---:|---|---:|---|
| 1 | 182,072 / 2,406 | 2023-10-01 | 99,782 / 1,330 | 2024-03-20–2024-07-06 |
| 2 | 281,854 / 3,736 | 2024-07-06 | 100,269 / 1,338 | 2024-07-07–2025-04-15 |
| 3 | 382,123 / 5,074 | 2025-04-15 | 99,968 / 1,327 | 2025-04-16–2025-07-27 |
| 4 | 482,091 / 6,401 | 2025-07-27 | 100,304 / 1,327 | 2025-07-28–2026-05-01 |
| 5 | 582,395 / 7,728 | 2026-05-01 | 101,267 / 1,342 | 2026-05-02–2026-08-13 |

## 8. Candidate screen, configurations, and resources

The fixed screen used seed `20260906` and exactly five families:

| Family | Fixed configuration |
|---|---|
| Fold prevalence baseline | Training-fold class prevalence; no model features |
| Multinomial logistic | `C=1`, `class_weight=null`, `solver=lbfgs`, `max_iter=1000`, `tol=0.001` |
| Histogram gradient boosting | `early_stopping=false`, `l2_regularization=1`, `learning_rate=0.07`, `max_depth=null`, `max_iter=300`, `max_leaf_nodes=31`, `min_samples_leaf=20` |
| Random forest | `bootstrap=true`, `class_weight=null`, `max_depth=24`, `max_features=sqrt`, `min_samples_leaf=5`, `n_estimators=300` |
| SGD classifier | `alpha=0.0001`, `class_weight=null`, `l1_ratio=0.15`, `loss=log_loss`, `max_iter=1000`, `penalty=l2`, `tol=0.001` |

The definitive run is `stage3-model-development-run-528b2e67164141e7b9806418ffddf420`; its immutable receipt SHA-256 is `26606356fbc9dbb1d405d6232141a1985497d6690226b483e2110d6e447c9438`. It saw 14.74 GiB available at admission, planned at most two candidate workers, admitted one, and elapsed 8,689.139 seconds. High-memory tree families ran exclusively with four native workers; other families used one native worker. Fold-local preprocessing and all 21 governed prior estimators were refit for every fold. All scalable candidates used the complete Development population; no sampled result appears in the comparison.

## 9. Aggregate and per-fold results

Primary selection metric is mean five-fold OOF multiclass log loss. Lower log loss, Brier, and ECE are better; higher AUC, macro-F1, and accuracy are better.

| Family | Status | Log loss | Brier | ECE | Macro OVR AUC | Macro-F1 | Accuracy | LL fold SD | Worst fold LL | Runtime |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Fold prevalence | Complete | 1.496372 | 0.711931 | 0.005744 | 0.500539 | 0.078064 | 0.454032 | 0.003839 | 1.500829 | 5.912 s |
| Multinomial logistic | Complete, warning | 1.494583 | 0.711523 | **0.003831** | 0.523847 | 0.078090 | 0.454042 | 0.004071 | 1.499006 | 3,123.953 s |
| Histogram gradient boosting | Complete | **1.477275** | **0.703874** | 0.006664 | **0.573257** | **0.094113** | 0.454748 | 0.005945 | 1.484557 | 2,938.393 s |
| Random forest | Complete | 1.479794 | 0.704554 | 0.009170 | 0.556634 | 0.083446 | **0.454883** | 0.004477 | 1.484786 | 1,949.769 s |
| SGD classifier | Failed | — | — | — | — | — | — | — | — | 576.846 s |

| Family | Fold | Log loss | Brier | ECE | AUC | Macro-F1 | Accuracy | Runtime ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Baseline | 1 | 1.497639 | 0.710997 | 0.012461 | 0.500000 | 0.078309 | 0.456104 | 228 |
| Baseline | 2 | 1.500829 | 0.713728 | 0.001586 | 0.500000 | 0.077543 | 0.449640 | 241 |
| Baseline | 3 | 1.489420 | 0.709351 | 0.010486 | 0.500000 | 0.078645 | 0.458957 | 220 |
| Baseline | 4 | 1.498234 | 0.713957 | 0.000384 | 0.500000 | 0.077617 | 0.450261 | 235 |
| Baseline | 5 | 1.495730 | 0.711615 | 0.004633 | 0.500000 | 0.078204 | 0.455212 | 233 |
| Logistic | 1 | 1.496293 | 0.710616 | 0.011791 | 0.521618 | 0.078436 | 0.456154 | 284,120 |
| Logistic | 2 | 1.499006 | 0.713274 | 0.001112 | 0.525494 | 0.077543 | 0.449640 | 439,965 |
| Logistic | 3 | 1.486994 | 0.708864 | 0.007664 | 0.523240 | 0.078645 | 0.458957 | 582,590 |
| Logistic | 4 | 1.496242 | 0.713422 | 0.003668 | 0.524976 | 0.077617 | 0.450261 | 757,185 |
| Logistic | 5 | 1.494366 | 0.711424 | 0.001525 | 0.521737 | 0.078204 | 0.455212 | 1,051,893 |
| HGB | 1 | 1.484557 | 0.704888 | 0.012101 | 0.571848 | 0.097237 | 0.454691 | 469,451 |
| HGB | 2 | 1.483111 | 0.706329 | 0.007560 | 0.573674 | 0.094699 | 0.450139 | 458,723 |
| HGB | 3 | 1.469177 | 0.701035 | 0.005719 | 0.573264 | 0.092072 | 0.459897 | 550,213 |
| HGB | 4 | 1.477220 | 0.705324 | 0.006426 | 0.575239 | 0.093573 | 0.451687 | 665,342 |
| HGB | 5 | 1.472371 | 0.701809 | 0.003436 | 0.578236 | 0.092551 | 0.457316 | 787,937 |
| Random forest | 1 | 1.483330 | 0.704567 | 0.018005 | 0.555774 | 0.084301 | 0.456996 | 153,140 |
| Random forest | 2 | 1.484786 | 0.706683 | 0.008878 | 0.560040 | 0.083415 | 0.450209 | 254,935 |
| Random forest | 3 | 1.472149 | 0.701832 | 0.009657 | 0.558128 | 0.082940 | 0.459417 | 365,218 |
| Random forest | 4 | 1.480769 | 0.706193 | 0.005586 | 0.555146 | 0.083410 | 0.451497 | 488,654 |
| Random forest | 5 | 1.477946 | 0.703497 | 0.003942 | 0.553252 | 0.083088 | 0.456309 | 681,398 |

## 10. Baseline comparisons

HGB improves mean log loss by 0.019097 (1.276% relative) and summed Brier by 0.008058 against prevalence. Random forest improves mean log loss by 0.016579 (1.108% relative) and Brier by 0.007377. Logistic improves log loss by only 0.001789 (0.1196% relative) and Brier by 0.000409, while failing to converge in every fold. Accuracy stays near the dominant-class baseline for every model, showing why probabilistic quality and discrimination—not raw accuracy—are the meaningful screen evidence.

## 11. Calibration, discrimination, and temporal stability

HGB is the strongest discriminator (macro OVR AUC 0.573257) and has the best log loss/Brier, but its log-loss fold SD (0.005945) is the largest of the completed families; its worst fold is fold 1 at 1.484557. Random forest is slightly less discriminative (0.556634) and less well calibrated overall (ECE 0.009170), but more stable by log-loss SD (0.004477). Logistic has the lowest aggregate ECE (0.003831) but materially weak discrimination and unresolved convergence, so its apparent calibration does not make it tuning-eligible. Calibration bands, per-class calibration errors, confusion matrices, and one-vs-rest lift are retained in each candidate receipt and exposed in Model Lab. The rare `TRIPLE` and `OTHER_REACH` classes require special attention in tuning because aggregate ECE can conceal weak rare-class reliability.

## 12. Failed runs, warnings, and repair evidence

The definitive run is immutable `PARTIAL`: four candidates completed, while SGD candidate `stage3-candidate-89f0ee522e884042a9c573fa2278a2eb` failed closed with `MODEL_LAB_PROBABILITY_RECONCILIATION_FAILED`. Its first validation probability matrix was 99,782 × 8 but contained non-finite values, so the configuration records five failed fits and publishes no OOF artifact or metric. Logistic completed but emitted `ConvergenceWarning` in all five folds after reaching the 1,000-iteration limit; it remains evidence, not a clean tuning candidate.

During the transitive-reachability audit, a superseded 223-feature job (`stage3-model-development-run-35b7c69a12234020baa145a4c1d6856e`, receipt `4b1275a59aeef3bd1c6fd3b0d521afe3f208726c1c741966e0b3f256f32a2faf`) was cancelled before tree and SGD execution. Its baseline and logistic receipts remain immutable but are authority-incompatible and contribute no final comparison evidence. Earlier 229-feature mechanical screen and repair receipts likewise remain immutable historical audit records and are not reused. The definitive 218-feature run completed both tree families without infrastructure failure.

## 13. Candidate disposition and finalist receipt

| Candidate | Fingerprint | Disposition | Reason |
|---|---|---|---|
| HGB | `stage3-candidate-spec-14098e08fb874d91048e1388094e69f66e47c6140aeab1e2f0b52f0b619348bc` | `ADVANCE_TO_TUNING` | Best clean log loss/Brier and AUC |
| Random forest | `stage3-candidate-spec-2015b6c4960574ae193ac1835fdf9b0ff620879b21b5a944b45350ffc14fe275` | `ADVANCE_TO_TUNING` | Second-best clean log loss; lower fold SD than HGB |
| Fold prevalence | `stage3-candidate-spec-bb5fefb7a8fa53e12220a52498379eb67992e2da172d48141ac5492f63da29c6` | `RETAIN_AS_BASELINE` | Required null comparator |
| Multinomial logistic | `stage3-candidate-spec-f30a7e01deeafdafffe38481be575a5eea9667e9994f638ec7bbe3e9a69b4114` | `NEEDS_REPAIR` | Five convergence warnings; negligible baseline gain |
| SGD classifier | `stage3-candidate-spec-b56f693975e9fd20af6d23d5d9d7844c4f65ff0c8146dbba3a2211f91acfb345` | `NEEDS_REPAIR` | Non-finite probabilities; no valid OOF result |

The corresponding immutable attempt/receipt pairs are baseline `stage3-candidate-77f17488eed340a89ba72e31ec6b55db` / `766182b0ba52d38e2c1c49f4c39d65298e12d52620984632a3084606a8c104f9`; logistic `stage3-candidate-2c427da2abbd4b58b37068006a70dec5` / `a5e96e97a8bc1f177502b21c0ed08c932f5a042bc51fd136273b287676757bfb`; HGB `stage3-candidate-ee1f09e6f64a437ebe769ae1707cc2ff` / `ff89053a20c09477dcc0c4b55cda9bb370f681b70e81698bab5250135f4d7bc0`; random forest `stage3-candidate-bdd79199b63a4f2886dd8d411a1f0a06` / `4f11884645baf00f17396219b72ff1508b5a89a7df2cbd2a02585e6993dbb80e`; and SGD `stage3-candidate-89f0ee522e884042a9c573fa2278a2eb` / `8a501f93c151e32f7a325b89f3c12e54e0fb2a66ceb5e42c9b351887435c04f7`.

Finalist selection ID is `stage3-finalist-selection-d48eb677c91c4b6eb26e72ce61d590f9`; receipt SHA-256 is `257277764fd71481700812fdabcded0677655085d34b710c2e35da7c7a9eb8a1`. Decision receipt SHA-256 is `7591e3994e7cf4094a5fd841d8b43fcaf1f6d372cd16b8551169079761b6322a`. These receipts supersede mechanical reconciliation selections and select exactly HGB and random forest. `championSelected=false`, `promotionStatus=NOT_PROMOTED`, and `exportStatus=NOT_EXPORTED`. No candidate is classified `DROP_AFTER_SCREEN` because the only other challengers require repair rather than a clean scientific rejection.

## 14. Final OOT seal and OOF artifacts

Final OOT contains 14,067 rows from 2026-08-14 through 2026-08-27 and remains `LOCKED_UNOPENED`. The screen records `finalOotTargetAccessed=false`, `finalOotScored=false`, and no feature-payload access. No model, transform, tuning decision, metric, chart, or OOF file contains Final OOT evidence.

All completed Development OOF artifacts use schema `SPORTS_STAGE3_DEVELOPMENT_OOF_PREDICTIONS_V1`, seed `20260906`, scope `FIVE_FOLD_OOF_DEVELOPMENT_ONLY`, 501,590 rows, 11 columns, and content-addressed Parquet identity:

| Family | Evaluation digest | Parquet SHA-256 |
|---|---|---|
| Baseline | `b940443…` | `7b015cb711c762c17a030324d07e5515b9c3769121d63fab286c6bc0007899e5` |
| Logistic | `49e0e3c…` | `f9725026c0bdd9c6d2ed6cc0428e3b1150692285ba4555fb94a2d0bdcd20c812` |
| HGB | `11c04f7…` | `396270314f6688d28333789837db5e8733040459244be848feef5700341d43c9` |
| Random forest | `09e1107…` | `f317b0aed433b2f6de2c3d4d1287540cee6fd89ac94a1f5a2fe1fdbbe4e06a6f` |

The stored bytes were rehashed and the Parquet metadata/row counts independently verified after the run.

## 15. Model Lab UI evidence

Model Lab now binds the selected project, dataset, component target, adopted treatment, Core feature set, chronological split, algorithms, job/run progress, sortable results (including ROC-AUC), comparison chart, calibration evidence, fold/runtime details, warnings/failures, immutable identities, and the governed next step. Browser-verification evidence is [the terminal Model Lab screen](mlb_core_challenger/screenshots/model-lab-results.jpg) and [the finalized Candidate Evaluation screen](mlb_core_challenger/screenshots/candidate-evaluation.jpg).

## 16. Verification results

- Combined focused treatment, feature-engineering, eligibility, execution, and candidate-evaluation Python suite: **71 passed** (10 dependency deprecation warnings).
- Focused Model Lab frontend suite: **15 passed**.
- Production frontend build: **passed**, 2,337 modules transformed. Non-blocking warnings: stale Browserslist database, chunk-size advisory, and an existing static/dynamic import advisory.
- Python compilation of changed implementation and scripts: **passed**.
- Git whitespace/error check: **passed**; line-ending notices only.

No focused failure was waived, weakened, or silently rewritten.

## 17. Changed implementation surface and version control

The change is confined to governed Stage 3 treatment persistence/compiler logic, model eligibility/engineering, development execution and candidate evaluation, three bounded operator scripts, existing Model Lab UI/API types, focused tests, the scientific-decision registry, this report, and browser evidence. Runtime receipts, OOF files, and the database remain local governed artifacts and are not committed. The unrelated untracked `docs/AI_SPORTS_PREDICTOR_PROJECT_MANAGEMENT_HANDOFF_2026-09-06.md` is explicitly excluded from the commit.

Changed implementation files are:

- Persistence and modeling: `server/persistence/repositories/stage3_treatment_repository.py`, `server/sports_current_statcast/stage3_candidate_evaluation.py`, `stage3_feature_engineering.py`, `stage3_feature_treatment_spec.py`, `stage3_model_eligibility.py`, `stage3_model_jobs.py`, and `stage3_model_laboratory.py` under `server/sports_current_statcast/`.
- Scientific decision and operators: `server/sports_current_statcast/mlb_core_challenger_decision_v1.json`; `scripts/register_mlb_core_challenger.py`; `scripts/run_mlb_core_challenger_screen.py`; `scripts/finalize_mlb_core_challenger_screen.py`.
- Model Lab UI: `src/sports/cockpit/ProjectBoundModelLab.tsx`, `ProjectCandidateComparison.tsx`, and `projectModelLabApi.ts`.
- Focused tests: `tests/sportsStage3ProjectBoundModelLabFrontend.test.mjs`, `sports_stage3_candidate_evaluation_test.py`, `sports_stage3_feature_engineering_test.py`, `sports_stage3_feature_treatment_spec_test.py`, and `sports_stage3_project_model_laboratory_test.py`.
- Evidence: this report plus `docs/mlb_core_challenger/screenshots/model-lab-results.jpg` and `candidate-evaluation.jpg`.

The delivery handoff records the exact final Git HEAD after the commit is created.

## 18. Single next step

Run **bounded tuning of only the two or three candidates classified `ADVANCE_TO_TUNING` by the definitive screen** under the same immutable dataset, target, V14 treatment, 218-feature Core set, five-fold chronological split, seed discipline, fold-local preprocessing/prior fitting, primary log-loss selection rule, calibration/stability diagnostics, rights boundary, and sealed Final OOT. This next step is refinement only: it still must not select a champion, open Final OOT, promote, or export a model.
