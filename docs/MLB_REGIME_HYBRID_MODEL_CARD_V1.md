# MLB regime hybrid research model card v1

## Identity, use and authority

Study `mlb-regime-hybrid-20260910-v1`, selected saved architecture `RF_RESIDUAL_ENSEMBLE`. Effective fitted ensemble: approximately 0.89203474 V18 + 0.10796526 RF + 0.0 residual system, followed by an anchored per-class radial adjustment cap and chronological temperature scaling. This is a research correction package over rolling frozen global-model probabilities, not a newly trained end-to-end global model or operational forecast.

Use: local private Development research and prospective-contract preparation. Status `RESEARCH_SHADOW`, `NOT_PROMOTED`; wageringAuthority=false; executionAllowedInAISP=false; Final OOT accessed=false. AISP may consume precomputed authorized evidence only. Source-use restrictions are cumulative/most restrictive: LOCAL_PRIVATE_MODEL_DEVELOPMENT, MLB Statcast GOVERNED_LOCAL_RESEARCH_ONLY, attribution required, commercial-rights review required. No policy, staking or deployment authority is conveyed.

## Frozen dependencies

- V18 target order remains STRIKEOUT, WALK_HBP_CI, HOME_RUN, SINGLE, DOUBLE, TRIPLE, BIP_OUT, OTHER_REACH. BB/HBP/catcher-interference are combined; OTHER_REACH remains separate.
- Treatment specification `stage3-feature-treatment-spec-711fbb376e9a4d419f826de593195638`; manifest `4d158e01a4a7d84fe6e7641f61edf0e9848f1775e025a2cec6c29cda22d479f3`.
- Model input schema checksum `357cdf0176098217f51e0451433921e33bf8ebb94f5cbef21898ba53d45212ad`: 246 raw features, 273 semantic fields before saved fold encoding. Exact names/order and source/fitted artifact references are in baseline-reproduction receipt `0abcf4e521c2a59c7c8cd04450e1d57a0c790f306dc571d7866b3650553a3af9`.
- Accepted V18 OOF SHA `b79a80398ef32a13589a8bb66f5e4e9c698b600195de5369886f7fc07f0dc215`.
- RF OOF SHA `b7aefeb898ba1673b66859381d195abdcac43105857ee108ec3081c8bd03ea83`; candidate `stage3-candidate-5a26360c71194c10b2c101d27f253bdf`. Existing 500-tree RF, minimum leaf 20, max-features 0.5, V14 treatment; identical original game/PA/fold/class IDs. Its current preprocessor's V1 prior parameters are an unresolved reconstruction dependency.
- Transition SHA `0e5e480f897ddefa5f9dddbc229a8a43bf29f7b81443c25ece611d9d4032b253`, training end 2025-07-27, unchanged mechanics only.

Load trusted local joblib artifacts only after SHA-256 and byte-count verification. The model package carries target order, clusters, membership basis, offsets, specialists, gate, ensemble weights, all temperatures and selected identity. It does not authorize executing untrusted pickle inputs or bypassing the upstream frozen schema.

## Transform and specialist contract

Four input domains are batter process/exposure, pitcher process/pitch mix/role/exposure, team rest/travel, and handedness/calendar/day-game matchup context. Numerical identities, targets, outcomes, later season aggregates, actual PA state and sportsbook closing prices are excluded from clustering. Each exact feature list is frozen in cluster-specification.json. Semantic priors are reused; no global median/mode imputation is introduced.

Within 2023 training, compare robust-scaled K-means (n_init=3) against robust-scaled PCA retaining 90% variance plus diagonal Gaussian mixture (regularization=0.05, n_init=1), with k=2/3 and fixed seed. Each fit uses at most 30,000 deterministically sampled complete rows. Earlier chronological prefixes are compared on later-2023 assignments; require minimum exposure and 5% mass; maximize ARI, prefer smaller k on ties. All four selected robust K-means k=2. This small method comparison is conditional on the outer 2023 treatment and does not establish long-term cluster invariance.

Soft K-means memberships use a training-distance scale. Missing input domains receive no support. Distance support is full through the training 99th percentile and tapers to zero by twice that threshold. Unsupported domains contribute zero centered memberships. Labels are ordered by training semantic means; labels denote feature states, not immutable people. Soft ESS is (sum w)^2/sum(w^2), not the independent game count.

Failure discovery is limited to V18 OOF folds 1/2. A class/cluster requires two seasons with ESS≥1,000 and ≥100 games each, |seasonal residual|≥0.003, and a consistent nonzero residual sign across both seasons and folds. Select at most four distinct clusters by the weakest-season absolute residual. Runtime membership depends only on supported features, never on realized errors.

Residual corrections are weighted observed-minus-V18 class vectors fitted on fold 3, shrunk with 10,000 zero-residual pseudo-PAs, recentered to zero sum and radially capped at 0.03 per class. Combined expert mass is normalized and mixed 50% with the global forecast. Membership offsets use softmax(log pV18 + centered memberships × coefficients), L2 penalty 0.01, 50% global mix and the same cap. Interactions add predeclared batter×pitcher products and platoon products. The exact deployed capped distribution is the fitting objective; analytical gradient and unsupported global fallback are checked.

The soft gate fits on the first half of fold-4 dates, retaining a 75% global floor. L2=0.01 shrinks its coefficients toward a neutral support-proportional gate, not toward zero expert mass. Convex ensemble weights use the same dates, V18 weight≥0.5 and L2=0.01 toward V18. The fitted residual weight is zero. The global offset-only control separates generic recalibration from cluster-specific mechanisms.

Each branch's scalar temperature is fitted on the next quarter of fold-4 dates, bounded [0.75,1.5]. Last-quarter fold-4 calibrated log loss selects the candidate among branches with Brier no worse than calibrated V18, with V18 as fallback. The exact selected temperature is saved (approximately 1.0010249233). Report raw/raw and calibrated/calibrated. The 0.03 correction cap is pre-temperature only.

## Evaluation and limitations

2025 is Development. August 14–27, 2026 Final OOT is physically sealed. The mixed physical row group and whole boundary date are excluded; 494,432 matched OOF PAs/6,570 games remain, with final evaluation 94,157 PAs/1,248 games through August 6. Baseline parity is exact on that safe population, not a reconstruction claim for the inaccessible 7,107 registered OOF PAs.

Chronological phases and full metrics are in the research report and immutable result. Global models remain rolling original fold estimators. Later-Development evaluation is not independent Final OOT and not a prospective pregame test. No additional fold-5 model choice occurred. Calibration intercept/slope estimates evaluated on held-out outcomes are diagnostics only; they never transform that evaluation's forecasts.

Game and four-week moving-block bootstrap intervals use 1,000 seeded replicates, with separate one-way batter/pitcher/team-role sensitivities. The evaluation has only three complete nonoverlapping four-week blocks. These intervals do not remove historical model-selection dependence, establish joint multiway independence or authorize promotion. Regime diagnostics overlap and are exploratory, not multiplicity-adjusted discovery or reselection.

The ensemble's small PA gain does not establish specialist benefit, uniformly improved class calibration, current evidence freshness, market-relative performance or wagering edge. Earlier bias qualifying a specialist is not proof of persistence; standalone specialists worsen final aggregate error. Rare classes remain underpowered for strong calibration conclusions. No causal prior/missing-family ablation was performed.

Historical mechanics use side-average vectors and observed participant membership: 20 games, 500 simulations each branch, common seeds. They do not preserve full lineup order/substitutions or prospective participant vintages, and are labeled nonpregame oracle sensitivity. Joint scores and moneyline/run distribution diagnostics are available; official game skill, first-five and time-matched market comparisons are unsupported.

Current forecast count is zero. The only saved slate is September 8 and already past; no retroactive forecasts are manufactured. Bullpen availability, current Statcast, starter workload, contemporaneous lineups, roof/weather, defense/speed and ABS sources are absent or insufficient at the required current granularity. A safe-cache missingness supplement quantifies available historical flags, not source freshness or awarded readiness points. Exact RF preprocessing reconstruction and new pre-kickoff evidence are prerequisites to a runnable forward ensemble.

## Reproducibility and next step

The baseline and all seven fitted raw branches reload with maximum probability difference 0; the original predictions, cluster artifacts, prefit/selection contracts, events and receipts are preserved. Source hashes, artifact SHA-256/byte counts, phase masks and excluded IDs are packaged. Large governed observation caches and atlas payloads remain local, referenced by immutable checksums, rather than copied into Git. Committed manifests are not substitutes for backing up those payloads.

Recommendation: retain accepted V18 and existing AISP policy, preserve the selected ensemble as nonexecuting research evidence, and use a separate bounded prospective preparation assignment to resolve only the frozen RF preprocessing and pre-kickoff inputs. No Final OOT access is requested by this study.

Primary method references: [scikit-learn PCA](https://scikit-learn.org/stable/modules/generated/sklearn.decomposition.PCA.html) and [GaussianMixture](https://scikit-learn.org/stable/modules/generated/sklearn.mixture.GaussianMixture.html). These document the reused implementations, not the empirical claims above.
