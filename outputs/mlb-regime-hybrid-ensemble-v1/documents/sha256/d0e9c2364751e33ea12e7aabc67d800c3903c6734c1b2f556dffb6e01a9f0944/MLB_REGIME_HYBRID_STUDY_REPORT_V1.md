# MLB regime, specialist and ensemble research report

Study: `mlb-regime-hybrid-20260910-v1`. Completed September 10, 2026.

## Scientific conclusion

**Retain V18. Preserve a useful research ensemble requiring prospective evidence. Do not request Final OOT yet.**

The five-architecture study found a small, temporally consistent PA-level improvement from a capped combination of the accepted V18 forecasts and the existing random forest. Its fitted weights are approximately **89.2035% V18, 10.7965% RF, and 0% residual-specialist system**. This is evidence for global-model diversification, not evidence that clusters or specialists improve prediction. Membership corrections, interactions, residual specialists and the soft mixture of experts all worsened later-Development total log loss. No additional configurations were selected using that later period.

The ensemble improves calibrated log loss by 0.0002583 (about 0.0175%) and Brier score by 0.00005477. Gains occur in all four evaluation months and all eight supported hard-cluster slices. However, calibration is not uniformly better by class, the temporal interval has limited independent blocks, and historical game mechanics are not a prospective game-forecast validation. Current shadow publication is unsupported by the available local future-game inputs.

MLB policies, official forecasts, V18 prospective evidence, positions, settlements, wagering authority and AISP remain unchanged. Final OOT, August 14–27, 2026, was never unsealed or read.

## Baseline and population

The user's corrected authority supersedes the original attachment's incompatible target/2025-OOT description. The exact accepted class order is:

`STRIKEOUT, WALK_HBP_CI, HOME_RUN, SINGLE, DOUBLE, TRIPLE, BIP_OUT, OTHER_REACH`.

2025 is Development. V18 treatment is specification `stage3-feature-treatment-spec-711fbb376e9a4d419f826de593195638`, manifest `4d158e01a4a7d84fe6e7641f61edf0e9848f1775e025a2cec6c29cda22d479f3`. Its 246 raw inputs, 273 treated inputs, fitted semantic priors and original fold-local encoders are preserved. No generic median/mode replacement was introduced.

All five frozen V18 estimators reproduced their saved probabilities **bitwise exactly on 494,432 matched PAs from 6,570 complete games**: zero mismatches and maximum absolute difference 0. Folds 1–4 also reproduce complete registered encoded-matrix digests. No baseline estimator was fitted.

This is not a claim that all 501,539 registered OOF rows were reconstructed. A 2026 physical Parquet row group mixes 6,960 Development PAs with sealed OOT payload. That entire mixed group was not read. Another 147 PAs on its boundary date were excluded to preserve complete games/dates. Thus 7,107 PAs/94 games are excluded from both models, and evaluation ends August 6. The byte-restricted reader admits only approved whole Development column chunks and metadata; forbidden read-ahead is zero padded without reading the underlying file. Zero Final OOT payload bytes were accessed. The frozen 56-row outcome-independent eligibility hold remains unchanged.

| V18 fold | PAs | Games | Raw log loss | Raw Brier | Role in this study |
|---|---:|---:|---:|---:|---|
| 1 | 99,780 | 1,330 | 1.48031670 | 0.70370204 | Discovery |
| 2 | 100,267 | 1,338 | 1.48008851 | 0.70557208 | Discovery |
| 3 | 99,926 | 1,327 | 1.46651796 | 0.70019972 | Specialist fitting |
| 4 | 100,302 | 1,327 | 1.47508765 | 0.70459619 | Chronologically partitioned gate/calibration/selection |
| 5, safe subset | 94,157 | 1,248 | 1.47250033 | 0.70173716 | Frozen later-Development evaluation |

The safe eligible Development cache contains 676,499 PAs. Discovery uses 2024–2025; evaluation uses 2026. Cluster fitting uses 182,067 PAs from 2023, prior to all comparison windows. Original target, game and team IDs reconcile exactly; 30 canonical teams are represented.

## Chronology and bounded computation

| Role | Dates | PAs | Games |
|---|---|---:|---:|
| Error discovery | 2024-03-20–2025-04-15 | 200,047 | 2,668 |
| Specialist/offset fitting | 2025-04-16–2025-07-27 | 99,926 | 1,327 |
| Gate/ensemble fitting | 2025-07-28–2025-09-15 | 50,366 | 667 |
| Forecast temperature fitting | 2025-09-16–2026-04-05 | 23,688 | 316 |
| Model selection | 2026-04-06–2026-05-01 | 26,248 | 344 |
| Frozen evaluation | 2026-05-02–2026-08-06 | 94,157 | 1,248 |

All role boundaries are date- and game-atomic. Each downstream correction consumes genuine rolling V18 OOF probabilities. Cluster transformations are frozen in the earliest training period and reused, not refitted on validation. Within-2023 cluster stability compares earlier training prefixes on a later 2023 reference set, conditional on the outer 2023 semantic preprocessing. It is not a full end-to-end nested preprocessing stability estimate. The fifth fold is untouched by this study's selection, but was used in earlier V18 research; it is not independent Final OOT.

Two cluster methods (robust K-means and robust scaling/PCA/regularized diagonal GMM), two counts (2/3), two training prefixes and one final winner per domain produced 36 clustering fit starts/completions, 36 scaler fits and 16 PCA fits. Six correction/gate/ensemble fits and seven chronological forecast-temperature fits completed. No HGB/RF predictive estimator was refitted. The bounded study execution took 134.57 seconds, excluding baseline reconstruction, diagnostics, authoring and review. Diagnostic calibration regressions are descriptive evaluations, not fitted forecast calibrators or additional predictive candidates.

## Cluster findings and missing categories

All four supported domains selected robust K-means with two clusters. The listed ARI measures training-prefix assignment agreement, not future predictive usefulness. Counts below are supported hard assignments in the 94,157-PA later-Development population. Soft effective sample sizes are supplied separately in the machine-readable profiles and can exceed a hard slice's count.

| Domain | Main distinction actually discovered | ARI | Hard counts |
|---|---|---:|---|
| Batter | Established/reliable process priors versus sparse, uncertain history | 0.99169 | 82,798 / 11,359 |
| Pitcher | Lower versus higher prior reliability and starter-role proportion | 0.94706 | 18,381 / 75,651; 125 unsupported |
| Team context | Lower travel/continuous play versus greater travel and rest | 0.95943 | 80,728 / 13,429 |
| Matchup/context | Primarily calendar/day-game structure, with handedness/platoon inputs | 1.00000 | 30,340 / 63,817 |

These are PA-weighted state clusters, not permanent player labels, pure pitch-style clusters or team-strength rankings. Exposure/uncertainty dominates the player splits. Calendar structure dominates the matchup split. **No authoritative bullpen-availability cluster was discovered:** travel/rest is explicitly not a substitute. No manager, defense/speed, roof/weather or ABS effect was invented.

## Where V18 misses

Four regimes qualified before specialist fitting: `PITCHER_1`, `TEAM_REST_TRAVEL_0`, `BATTER_1`, and `MATCHUP_CONTEXT_0`. Each showed underprediction of `BIP_OUT` in the two discovery seasons and both discovery folds. The weakest seasonal residuals were +0.00651, +0.00647, +0.00614 and +0.00591 respectively (observed minus predicted).

Qualification required at least two seasons, effective sample size 1,000 and 100 games in each, identical sign across seasons/folds, and absolute seasonal bias at least 0.003. At most four distinct clusters were admitted. Importantly, the sparse-batter fold-2 residual was only +0.0000483: same direction does not mean a strong recurring fold-level effect. Full fold-by-fold residuals and subsequent persistence are preserved in the diagnostics supplement. Later specialist performance does not establish a transferable correction.

| Regime | Fold 1 BIP_OUT bias | Fold 2 | Fold 3 | Fold 4 | Fold 5 |
|---|---:|---:|---:|---:|---:|
| PITCHER_1 | +0.013141 | +0.002299 | +0.002217 | −0.000336 | −0.001525 |
| TEAM_REST_TRAVEL_0 | +0.011054 | +0.002127 | +0.001413 | −0.001486 | −0.001500 |
| BATTER_1 | +0.018385 | +0.000048 | +0.007960 | +0.005454 | −0.003295 |
| MATCHUP_CONTEXT_0 | +0.014231 | +0.002940 | +0.000862 | −0.001024 | +0.000320 |

These are fixed soft-membership-weighted observed-minus-raw-V18 residuals. Three of four have reversed sign by the evaluation fold; the remaining regime is much weaker and reversed in fold 4. The historical failure hypothesis therefore did not persist reliably as the original rolling V18 models changed.

| Supported hard regime | Evaluation PAs | Calibrated V18 LL | Standalone residual-system LL | Selected ensemble LL |
|---|---:|---:|---:|---:|
| BATTER_0 | 82,798 | 1.472878 | 1.473011 | 1.472646 |
| BATTER_1 | 11,359 | 1.469599 | 1.469562 | 1.469151 |
| PITCHER_0 | 18,381 | 1.492045 | 1.492142 | 1.491781 |
| PITCHER_1 | 75,651 | 1.467915 | 1.468032 | 1.467659 |
| TEAM_REST_TRAVEL_0 | 80,728 | 1.472683 | 1.472793 | 1.472408 |
| TEAM_REST_TRAVEL_1 | 13,429 | 1.471276 | 1.471403 | 1.471121 |
| MATCHUP_CONTEXT_0 | 30,340 | 1.463233 | 1.463295 | 1.463052 |
| MATCHUP_CONTEXT_1 | 63,817 | 1.476880 | 1.477016 | 1.476585 |

The standalone residual system improves only the sparse-batter hard slice, not the total system. Inside/outside metrics for all four qualified specialists and the soft gate, plus Brier, class calibration and uncertainty, are supplied separately; ensemble success is never attributed to those specialists.

## Matched later-Development comparison

Every row below uses the same 94,157 PAs/1,248 games, with each model's temperature fitted on the same earlier calibration segment. Brier is the sum of eight squared class errors, averaged per PA. Lower is better.

| Architecture | Calibrated log loss | Calibrated Brier | Log-loss change vs calibrated V18 |
|---|---:|---:|---:|
| V18 | 1.47248245 | 0.70174248 | 0 |
| Global class-offset control | 1.47255800 | 0.70178575 | +0.00007555 |
| Cluster-membership correction | 1.47255659 | 0.70175556 | +0.00007414 |
| Registered cluster interactions | 1.47271549 | 0.70179712 | +0.00023304 |
| Residual specialists | 1.47259457 | 0.70176276 | +0.00011212 |
| Soft mixture of experts | 1.47250706 | 0.70174785 | +0.00002461 |
| V18/RF/residual ensemble, residual weight 0 | **1.47222418** | **0.70168771** | **−0.00025827** |

The raw-to-raw comparison also favors the selected ensemble: log loss 1.47222603 versus 1.47250033, Brier 0.70168721 versus 0.70173716. Thus the result is not merely an unfair calibrated-versus-raw comparison. The full comparison matrix preserves selection and evaluation, raw and calibrated outputs. Cluster-membership and interaction candidates are bounded probability-offset architectures, not separately refitted augmented HGB trees.

The mean maximum per-class raw ensemble adjustment is 0.00327325 (0.327 percentage points); maximum is 0.030. All evaluation PAs receive a nonzero ensemble adjustment. Residual and gate systems also have broad soft influence, not sparse hard routing. The raw cap is before temperature calibration and is not a post-calibration cap.

## Uncertainty, concentration and calibration

The ensemble's paired game-clustered 95% Development interval for log-loss change is **[−0.0003480, −0.0001754]**; for Brier **[−0.00008722, −0.00002143]**. A four-calendar-week moving-block bootstrap gives log-loss interval **[−0.0003312, −0.0001800]**. There are 15 observed weeks but only three nonoverlapping full four-week blocks, so that temporal interval has limited-block uncertainty. Separate batter, pitcher and team-role bootstrap sensitivities retain a negative aggregate interval; they are not one joint dependence guarantee or promotion test. All use 1,000 deterministic replicates.

Monthly log-loss changes are May −0.00018145 (30,340 PAs), June −0.00022956 (29,854), July −0.00033070 (28,030), August −0.00045332 (5,933). Removing the strongest contributing month, batting team or hard cluster leaves improvements of −0.00022756, −0.00024500 and −0.00015500. These outcome-informed removals are exploratory robustness summaries, not new selection opportunities. Regime and cold-start intervals, sample sizes and full class-calibration diagnostics are in the diagnostics artifact; overlapping clusters must not be summed as independent populations.

Calibration is mixed, not uniformly preserved. Class slopes move closer to 1 for HR (0.770→0.816), singles (0.848→0.883), doubles (0.646→0.708), triples (0.659→0.720), BIP outs (0.979→0.993), and OTHER_REACH (0.673→0.739). Strikeout slope moves 1.063→1.077; WALK_HBP_CI 0.987→1.033. The combined walk class's Brier and marginal bias worsen. HR marginal underprediction grows despite improved slope/Brier. Rare-class counts are 356 triples and 759 OTHER_REACH; coarse reliability bins and those diagnostic slopes are not definitive rare-event calibration proof. Per-class intercepts, slopes, ten-bin reliability tables, entropy, spread and observed/predicted rates remain available.

Cold/sparse subgroup calibrated log-loss changes are −0.00024647 for no batter prior (8,551 PAs), −0.00009309 for no pitcher prior (7,925), −0.00064195 for low batter rolling history (4,981), and −0.00025042 for low pitcher rolling history (14,262). No-batter-prior Brier slightly worsens. These flags do not establish rookie, promotion, trade, role-change or return-from-absence identities. V18 priors were preserved, not ablated; neither these comparisons nor zero generic fallback proves their causal benefit.

## Baseball mechanics and market evidence

The unchanged accepted transition model (training cutoff July 27, 2025) and common simulation seeds were used for 20 date/ID-selected later-Development games, 500 simulations per branch per game. Both branches completed coherently with zero illegal states and zero termination failures. Top-half PAs are away offense, bottom-half PAs home offense, verified against governed encoding.

This is explicitly **ORACLE_MECHANICS_SENSITIVITY_NONPREGAME**. Historical observed PA membership and side-averaged probabilities do not reconstruct pregame lineups, substitutions or state-dependent player heterogeneity. It is not an evaluation of the full prospective V18 lineup engine and cannot establish predictive game skill.

Descriptive V18→ensemble mechanics results: home-win log loss 0.643952→0.642908; Brier 0.225915→0.225371; home run bias +0.0297→+0.0304; away run bias +0.5687→+0.5868; margin MAE 3.6402→3.6690; total MAE 4.5426→4.5584. Nominal 90% total coverage is 80% for both; margin coverage is 90%→85%. These mixed 20-game summaries and joint-score distributions are retained, not presented as evidence of superior pregame forecasts. First-five and market-line outcome claims are unavailable.

No valid historical time-matched two-sided sportsbook cohort was established. There is no market-relative skill or wagering-edge result. The forward contract requires identical event/team/book/market/period/line, contemporaneous opposing quotes, quote observed-at and source-as-of timestamps, forecast cutoff before event start, quote/forecast ages and common horizon, plus outcome provenance. No sportsbook provider was called.

## Current evidence and next action

Both sides' historical bullpen-workload and pregame-temperature missingness flags equal 1 for every safe OOF/evaluation PA. Other missingness counts and seven source-family limitations are recorded in the source supplement. Without paired supported/unavailable sources, their causal error impact is not identifiable. The next source-specific experiments would require timestamped bullpen usage/availability, pregame starter workload and lineup vintages, current Statcast, weather/roof snapshots, defense/baserunning evidence and governed ABS features; none were fabricated or added here.

Only the prior September 8 local slate was available: 13 already-published V18 games and two original skips, all now in the past. No legitimate new current shadow forecasts were produced. Additional blocker: the frozen RF OOF is valid for this Development comparison, but the earlier V14 prior-treatment parameters needed for complete current RF-input reconstruction were not recovered. The correction object alone is not a deployable full current ensemble.

**Exact next AISP action:** retain existing official models/policies and positions. Treat this publication as nonexecuting research evidence only. Review/archive the research manifest and forward join contract; do not import it as official forecasts or execute the joblib model. Continue the existing prospective timestamp archive. A future bounded assignment must first resolve the RF's frozen preprocessing/current-input reproduction and supply pre-kickoff next-slate evidence. Do not unseal Final OOT for that work.

## Delivery and verification

The publication contains the original completed run, an immutable reporting/diagnostics supplement, cluster specification/assignments, five-fold OOF error atlas, fitted correction/cluster artifacts, eligibility/gate contract, raw/calibrated comparison matrix, regime and calibration evidence, source restrictions, forward contract, editable review workbook, model card and checksums/byte counts. The original run's `specialistLogLoss` field actually stored total selected-ensemble error; that evidence is preserved, while the publication explicitly relabels it and supplies actual standalone-specialist error separately.

All seven raw prediction branches reproduced bitwise on reload. Focused checks cover sealed physical reads, chronology/IDs, probability normalization/caps/unsupported fallback and deployed-gradient consistency, simulator orientation/identity, metric uncertainty, authenticated research registration and artifact checksums. No broad suite, additional model search, provider integration or AISP write occurred. Workbook review uses editable flat rows, explicit actual-method labels and formula-computed log-loss changes.

Source code started from `dd96fd5a3046350535eefc26cb1c24f6fb8fa48b` on `codex/nfl-current-state-cold-start-v2`. Study work is committed separately on `codex/mlb-regime-hybrid-ensemble-v1`; final commit and publication identities are given in the delivery receipt.
