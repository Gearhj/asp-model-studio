# NFL uncertainty/mean-separation repair — research report

Completed study: 2026-09-10T02:07:43.456622+00:00. Run `b64fe738b9774e4559f9f15184f81d978a864d27c0a103fe7e8e6e54f6e0795e`. Research shadow; not promoted; no wagering or AISP execution authority.

## Scientific conclusion

The fixed primary RESIDUAL/48h has **higher raw log loss than saved M1** over the matched 1,408 Development games: ΔLL 0.0047 [-0.0042, 0.0134]. Under the equivalent chronological calibration recipe, its log loss is **lower than calibrated M1**: ΔLL -0.0013 [-0.0106, 0.0079]. These exploratory season/week-block intervals do not establish prospective superiority. No raw/calibrated winner is selected. Correctness repair does not imply better prediction or coverage. M1 and all superseded/withheld artifacts remain retained.

## What was wrong, and where it mattered

Six uncertainty-only fields entered predecessor score means: home/away passer posterior SD, prior-season gap and missing-season count. Replay of saved sufficient statistics identified `2002_01_DAL_HOU` (2002-09-08): HOU had no eligible prior team rows. The source-start fallback `season − 1999` produced gap 3 and missing-count 2. This is an unseen-team counter, **not verification that HOU had two missing historical seasons**. Each frozen training system contained this one nonzero home count; the final training set had 6,729 zeros and one value 2. Away counts were all zero.

For each of the 16 original current events, home missing-count 1 became a standardized value near 41.009. Its saved linear term contributed 8.561123 home points and -5.569739 away points, or **14.130862 home-margin points**. All ten validation systems were affected: missing counts were zero but centering created a constant term; passer SD was nonzero throughout, season gaps varied, and HGB split on uncertainty-only fields. Their combined linear terms ranged approximately −3.985 to +4.353 historical margin points. Attribution is not causal refit impact: correlated coefficients, residuals and mixtures change.

DYNAMIC means never used these fields. Its distributions still used the old variance heuristic: posterior variance, arbitrary `1 + gap²` multiplication and residual-reference adjustment. Historical validation’s gap multiplier was always 1, unlike the current regime. The repair reuses DYNAMIC means, replaces uncertainty laws and refits ten learned outer systems plus the final system. [Exact historical/current impact trace](<C:/Users/james/asp-model-studio/outputs/nfl-current-state-cold-start-v2/uncertainty-repair-v1/diagnostics/sha256/f140d1e4328593e758197a378acfb133091b0502585d6897b63fdbdcdb46c1ae/diagnostic.json>).

## Treatment, fitting and limits

The 52 mean inputs are 44 home/away reconstructed football-rate/score estimates plus each side’s historical passer EPA mean, effective passer exposure, prior-game count and current-game count. Six uncertainty-only fields and rate posterior SD metadata are excluded from means. Measured exposure/continuity remain legitimate state inputs. This does not assert that deleting actual historical observations leaves reconstructed ability estimates unchanged. No generic median/mode replacement is introduced; unknown evidence differs from observed zero. The passer layer is pass-attempt-weighted prior `passer_player_id` usage, not independently verified historical QB position or a known target starter.

DYNAMIC is scoring-only; HIERARCHICAL uses the 52-field Ridge correction and RESIDUAL adds fixed small HGB corrections. Retention/architecture/seeds are inherited. Ensemble weights/diversity use earlier OOF only, otherwise hierarchical warmup.

Each component’s variance law is a nonnegative least-squares regression of inner chronological holdout squared score error on an intercept, score posterior variance, passer posterior variance and missing-age count. Home/away share coefficients. Fixed previous-season-observation dropout supplies one paired case with equal normal/dropout weights, not independent new games. The gap coefficient requires independent design rank, not merely positive gap cases. Only observations are dropped; inner prior parameters and mean-model parameters stay frozen. This does not validate missing training data, historical vintages or two-year estimator staleness.

Paired centered inner residuals supply the joint shape. Nonnegative projection and balanced integer rounding preserve means within 0.5/draw count. Latent and constrained-draw variance are distinct. This is not a legal scoring-path engine or full Bayesian parameter posterior; uncertainty is not presumed calibrated.

## Evidence and matched evaluation

The source cohort has 6,988 games from 1999–2024, with 1999 source-only warmup (258 games) and training targets from 2000. Outer validation is 2020–24, 1,408 identical games at each lag. The three schedule-derived semantic rows absent from eligible reconstructed play evidence are `1999_01_BAL_STL`, `2000_03_SD_KC`, `2000_06_BUF_MIA`. They are not manufactured into exposure evidence; 2020–24 membership is unchanged.

Historical estimates are `RETROSPECTIVE_RECONSTRUCTED_AS_OF`, not archived point-in-time vintages. Availability uses the next-day noon New York conservative completion upper bound plus 48/72h and strict whole-slate cutoffs, not an observed release time. Late corrections remain unidentified; 72h sensitivity does not estimate them. Sealed 2025-season payloads and target starter/injury/weather/current numeric roster inputs are excluded.

Saved M1 shares outcomes, not the 48/72h retraining or availability recipe. Compare raw/raw and calibrated/calibrated. Fixed multinomial logit on log probabilities (C=1, earlier OOF seasons only) is not selected after outcomes. No earlier OOF or fewer than three classes means labeled raw warmup. Calibration changes outcome probabilities only—not scores, bias, MAE or intervals—and is not applied to current publication.

Saved repaired calibration warmup seasons: 2020. Completed evaluation calibrator fits: 32; current-publication calibrator fits: 0.

## Primary 48h results

DYN/HIER/RES/ENS are repaired components. `raw` is uncalibrated; `cal` uses earlier OOF. Lower LL/Brier is better; Brier sums three classes. Bias = prediction minus actual; positive margin favors home. Slash-separated metrics are **home / away / margin / total**; Full is the 2020–24 regular-season and postseason cohort, not regular-season games alone.

| Series | Cohort | N | LL | Brier | Bias H/A/M/T | MAE H/A/M/T |
| --- | --- | --- | --- | --- | --- | --- |
| M1 raw | Week 1 | 80 | 0.7406 | 0.4970 | 0.21 / -0.67 / 0.88 / -0.46 | 7.23 / 6.97 / 9.94 / 9.83 |
| M1 cal | Week 1 | 80 | 0.7566 | 0.4987 | 0.21 / -0.67 / 0.88 / -0.46 | 7.23 / 6.97 / 9.94 / 9.83 |
| DYN raw | Week 1 | 80 | 0.7350 | 0.4905 | 1.57 / -0.57 / 2.13 / 1.00 | 7.14 / 6.89 / 9.83 / 9.81 |
| DYN cal | Week 1 | 80 | 0.7341 | 0.4797 | 1.57 / -0.57 / 2.13 / 1.00 | 7.14 / 6.89 / 9.83 / 9.81 |
| HIER raw | Week 1 | 80 | 0.7361 | 0.4842 | 0.39 / -0.02 / 0.41 / 0.37 | 7.08 / 6.91 / 9.70 / 9.76 |
| HIER cal | Week 1 | 80 | 0.7364 | 0.4760 | 0.39 / -0.02 / 0.41 / 0.37 | 7.08 / 6.91 / 9.70 / 9.76 |
| RES raw | Week 1 | 80 | 0.7452 | 0.4880 | 0.28 / -0.11 / 0.40 / 0.17 | 7.15 / 6.97 / 9.75 / 9.84 |
| RES cal | Week 1 | 80 | 0.7467 | 0.4827 | 0.28 / -0.11 / 0.40 / 0.17 | 7.15 / 6.97 / 9.75 / 9.84 |
| ENS raw | Week 1 | 80 | 0.7407 | 0.4849 | 0.37 / -0.07 / 0.44 / 0.30 | 7.09 / 6.92 / 9.72 / 9.78 |
| ENS cal | Week 1 | 80 | 0.7434 | 0.4818 | 0.37 / -0.07 / 0.44 / 0.30 | 7.09 / 6.92 / 9.72 / 9.78 |
| M1 raw | Weeks 1–4 | 319 | 0.7096 | 0.4735 | -0.09 / -0.69 / 0.59 / -0.78 | 7.23 / 7.29 / 9.88 / 10.22 |
| M1 cal | Weeks 1–4 | 319 | 0.6937 | 0.4707 | -0.09 / -0.69 / 0.59 / -0.78 | 7.23 / 7.29 / 9.88 / 10.22 |
| DYN raw | Weeks 1–4 | 319 | 0.7260 | 0.4912 | 0.54 / -0.75 / 1.29 / -0.21 | 7.32 / 7.33 / 10.27 / 10.33 |
| DYN cal | Weeks 1–4 | 319 | 0.7044 | 0.4839 | 0.54 / -0.75 / 1.29 / -0.21 | 7.32 / 7.33 / 10.27 / 10.33 |
| HIER raw | Weeks 1–4 | 319 | 0.7154 | 0.4771 | -0.56 / -0.25 / -0.31 / -0.80 | 7.23 / 7.35 / 9.98 / 10.24 |
| HIER cal | Weeks 1–4 | 319 | 0.7074 | 0.4785 | -0.56 / -0.25 / -0.31 / -0.80 | 7.23 / 7.35 / 9.98 / 10.24 |
| RES raw | Weeks 1–4 | 319 | 0.7182 | 0.4792 | -0.60 / -0.34 / -0.26 / -0.94 | 7.25 / 7.41 / 10.02 / 10.29 |
| RES cal | Weeks 1–4 | 319 | 0.7003 | 0.4768 | -0.60 / -0.34 / -0.26 / -0.94 | 7.25 / 7.41 / 10.02 / 10.29 |
| ENS raw | Weeks 1–4 | 319 | 0.7177 | 0.4783 | -0.55 / -0.29 / -0.26 / -0.84 | 7.23 / 7.37 / 10.00 / 10.24 |
| ENS cal | Weeks 1–4 | 319 | 0.6990 | 0.4755 | -0.55 / -0.29 / -0.26 / -0.84 | 7.23 / 7.37 / 10.00 / 10.24 |
| M1 raw | Full | 1408 | 0.6749 | 0.4488 | -0.17 / -0.08 / -0.10 / -0.25 | 7.47 / 7.43 / 10.07 / 10.63 |
| M1 cal | Full | 1408 | 0.6653 | 0.4529 | -0.17 / -0.08 / -0.10 / -0.25 | 7.47 / 7.43 / 10.07 / 10.63 |
| DYN raw | Full | 1408 | 0.7001 | 0.4705 | 0.17 / -0.28 / 0.45 / -0.11 | 7.64 / 7.56 / 10.44 / 10.68 |
| DYN cal | Full | 1408 | 0.6819 | 0.4707 | 0.17 / -0.28 / 0.45 / -0.11 | 7.64 / 7.56 / 10.44 / 10.68 |
| HIER raw | Full | 1408 | 0.6792 | 0.4519 | -0.78 / -0.04 / -0.73 / -0.82 | 7.59 / 7.40 / 10.15 / 10.65 |
| HIER cal | Full | 1408 | 0.6660 | 0.4537 | -0.78 / -0.04 / -0.73 / -0.82 | 7.59 / 7.40 / 10.15 / 10.65 |
| RES raw | Full | 1408 | 0.6796 | 0.4519 | -0.84 / -0.13 / -0.71 / -0.97 | 7.60 / 7.43 / 10.18 / 10.67 |
| RES cal | Full | 1408 | 0.6640 | 0.4518 | -0.84 / -0.13 / -0.71 / -0.97 | 7.60 / 7.43 / 10.18 / 10.67 |
| ENS raw | Full | 1408 | 0.6793 | 0.4518 | -0.78 / -0.08 / -0.70 / -0.86 | 7.59 / 7.40 / 10.15 / 10.65 |
| ENS cal | Full | 1408 | 0.6643 | 0.4533 | -0.78 / -0.08 / -0.70 / -0.86 | 7.59 / 7.40 / 10.15 / 10.65 |

### Coverage and home-outcome calibration

Coverage is observed inclusion in the raw 90% interval, not a calibration claim. Unavailable M1 intervals stay unavailable. Home intercept/slope are descriptive one-vs-rest diagnostics (ideal 0/1); unsupported/failed estimates remain unavailable. Home p/rate compare mean prediction with observed wins; ties stay separate.

| Series | Cohort | 90% coverage H/A/M/T | Home ECE | Home p | Home rate | Intercept | Slope |
| --- | --- | --- | --- | --- | --- | --- | --- |
| M1 raw | Week 1 | unavailable | 0.1688 | 0.5092 | 0.4875 | -0.0851 | 0.7871 |
| M1 cal | Week 1 | unavailable | 0.0715 | 0.4878 | 0.4875 | -0.0190 | 0.6813 |
| DYN raw | Week 1 | 0.950 / 0.938 / 0.900 / 0.950 | 0.1094 | 0.5488 | 0.4875 | -0.4440 | 1.9511 |
| DYN cal | Week 1 | 0.950 / 0.938 / 0.900 / 0.950 | 0.0778 | 0.5025 | 0.4875 | -0.0658 | 1.1687 |
| HIER raw | Week 1 | 0.938 / 0.938 / 0.900 / 0.950 | 0.1007 | 0.4945 | 0.4875 | -0.0379 | 0.7813 |
| HIER cal | Week 1 | 0.938 / 0.938 / 0.900 / 0.950 | 0.0735 | 0.4975 | 0.4875 | -0.0482 | 0.8742 |
| RES raw | Week 1 | 0.938 / 0.938 / 0.900 / 0.950 | 0.0856 | 0.4951 | 0.4875 | -0.0399 | 0.7327 |
| RES cal | Week 1 | 0.938 / 0.938 / 0.900 / 0.950 | 0.0662 | 0.5009 | 0.4875 | -0.0608 | 0.8163 |
| ENS raw | Week 1 | 0.938 / 0.938 / 0.900 / 0.950 | 0.0706 | 0.4963 | 0.4875 | -0.0436 | 0.7769 |
| ENS cal | Week 1 | 0.938 / 0.938 / 0.900 / 0.950 | 0.0502 | 0.5006 | 0.4875 | -0.0600 | 0.8390 |
| M1 raw | Weeks 1–4 | unavailable | 0.0322 | 0.5273 | 0.4953 | -0.1310 | 0.9176 |
| M1 cal | Weeks 1–4 | unavailable | 0.0442 | 0.5080 | 0.4953 | -0.0522 | 0.7818 |
| DYN raw | Weeks 1–4 | 0.928 / 0.915 / 0.903 / 0.922 | 0.0743 | 0.5498 | 0.4953 | -0.3393 | 1.5564 |
| DYN cal | Weeks 1–4 | 0.928 / 0.915 / 0.903 / 0.922 | 0.0364 | 0.5037 | 0.4953 | -0.0337 | 0.8575 |
| HIER raw | Weeks 1–4 | 0.934 / 0.922 / 0.906 / 0.934 | 0.0492 | 0.5003 | 0.4953 | -0.0221 | 0.7406 |
| HIER cal | Weeks 1–4 | 0.934 / 0.922 / 0.906 / 0.934 | 0.0431 | 0.5037 | 0.4953 | -0.0363 | 0.7048 |
| RES raw | Weeks 1–4 | 0.934 / 0.915 / 0.906 / 0.934 | 0.0466 | 0.5024 | 0.4953 | -0.0283 | 0.7192 |
| RES cal | Weeks 1–4 | 0.934 / 0.915 / 0.906 / 0.934 | 0.0458 | 0.5059 | 0.4953 | -0.0429 | 0.7461 |
| ENS raw | Weeks 1–4 | 0.934 / 0.922 / 0.906 / 0.931 | 0.0358 | 0.5023 | 0.4953 | -0.0286 | 0.7337 |
| ENS cal | Weeks 1–4 | 0.934 / 0.922 / 0.906 / 0.931 | 0.0519 | 0.5028 | 0.4953 | -0.0330 | 0.7848 |
| M1 raw | Full | unavailable | 0.0298 | 0.5324 | 0.5384 | 0.0297 | 0.9761 |
| M1 cal | Full | unavailable | 0.0374 | 0.5170 | 0.5384 | 0.1024 | 0.8140 |
| DYN raw | Full | 0.903 / 0.916 / 0.895 / 0.897 | 0.0453 | 0.5502 | 0.5384 | -0.1862 | 1.7015 |
| DYN cal | Full | 0.903 / 0.916 / 0.895 / 0.897 | 0.0378 | 0.5028 | 0.5384 | 0.1528 | 0.9145 |
| HIER raw | Full | 0.907 / 0.918 / 0.894 / 0.907 | 0.0271 | 0.5141 | 0.5384 | 0.1144 | 0.8660 |
| HIER cal | Full | 0.907 / 0.918 / 0.894 / 0.907 | 0.0326 | 0.5159 | 0.5384 | 0.1034 | 0.8964 |
| RES raw | Full | 0.905 / 0.911 / 0.897 / 0.907 | 0.0243 | 0.5151 | 0.5384 | 0.1117 | 0.8502 |
| RES cal | Full | 0.905 / 0.911 / 0.897 / 0.907 | 0.0317 | 0.5176 | 0.5384 | 0.0994 | 0.8678 |
| ENS raw | Full | 0.906 / 0.918 / 0.898 / 0.906 | 0.0263 | 0.5153 | 0.5384 | 0.1097 | 0.8685 |
| ENS cal | Full | 0.906 / 0.918 / 0.898 / 0.906 | 0.0393 | 0.5150 | 0.5384 | 0.1066 | 0.9133 |

### Matched primary loss differences

ΔLL = RES/48h minus reference; negative favors RES. The 2,000 whole-season/week block resamples are exploratory; crossing zero does not establish a difference. Complete comparisons remain in the result JSON.

| Comparison | Cohort | N | Blocks | ΔLL [95% interval] |
| --- | --- | --- | --- | --- |
| raw − M1 raw | Week 1 | 80 | 5 | 0.0046 [-0.0149, 0.0240] |
| raw − M1 raw | Weeks 1–4 | 319 | 20 | 0.0085 [-0.0177, 0.0308] |
| raw − M1 raw | Full | 1408 | 109 | 0.0047 [-0.0042, 0.0134] |
| cal − M1 cal | Week 1 | 80 | 5 | -0.0098 [-0.0214, 0.0072] |
| cal − M1 cal | Weeks 1–4 | 319 | 20 | 0.0067 [-0.0161, 0.0270] |
| cal − M1 cal | Full | 1408 | 109 | -0.0013 [-0.0106, 0.0079] |
| raw − DYN raw | Week 1 | 80 | 5 | 0.0102 [-0.0311, 0.0574] |
| raw − DYN raw | Weeks 1–4 | 319 | 20 | -0.0079 [-0.0370, 0.0204] |
| raw − DYN raw | Full | 1408 | 109 | -0.0205 [-0.0331, -0.0068] |
| cal − DYN cal | Week 1 | 80 | 5 | 0.0126 [-0.0216, 0.0511] |
| cal − DYN cal | Weeks 1–4 | 319 | 20 | -0.0041 [-0.0253, 0.0181] |
| cal − DYN cal | Full | 1408 | 109 | -0.0179 [-0.0280, -0.0072] |

## 72h sensitivity

| Component | 48h raw LL | 72h raw LL | 72h − 48h ΔLL [95% interval] | Changed games | Mean absolute Δp |
| --- | --- | --- | --- | --- | --- |
| DYN | 0.7001 | 0.6982 | -0.0019 [-0.0068, 0.0017] | 1408/1408 | 0.012000 |
| HIER | 0.6792 | 0.6810 | 0.0018 [-0.0029, 0.0061] | 1407/1408 | 0.018934 |
| RES | 0.6796 | 0.6775 | -0.0021 [-0.0083, 0.0034] | 1408/1408 | 0.025564 |
| ENS | 0.6793 | 0.6786 | -0.0007 [-0.0064, 0.0045] | 1407/1408 | 0.022117 |

This is the fixed availability sensitivity, not selection. Complete 72h early-season raw/cal metrics remain in the result.

## Final uncertainty parameters versus actual coverage

Parameters below are final through-2024 estimates, not the outer-fold coverage measured above. Order: intercept / score posterior variance / passer posterior variance / missing-age count. Nonnegative does not mean calibrated.

| Component | NNLS coefficients | Normal games | Dropout cases | Rank | Explicit gap |
| --- | --- | --- | --- | --- | --- |
| DYN | 88.472674 / 0.000000 / 0.000000 / 0.000000 | 285 | 285 | 4 | design estimable; fitted 0.000000 |
| HIER | 85.459667 / 0.000000 / 0.000000 / 0.000000 | 285 | 285 | 4 | design estimable; fitted 0.000000 |
| RES | 85.432888 / 0.000000 / 0.000000 / 0.000000 | 285 | 285 | 4 | design estimable; fitted 0.000000 |

Final ensemble residual weight: 0.391739; disposition: `EARLIER_OOF_ONLY_WEIGHT_FITTED`. Weak dropout support or poor coverage is not resolved by calling variance a posterior.

## Completion, verification and current delivery

Actual completed mean-estimator fits: 66; separate variance fits: 33; separate applied evaluation-calibrator fits: 32. Completed outer systems: 10; final model reload verifications: 1. Study runtime: 2440.31 seconds. Diagnostic calibration accounting: `{"insufficientClassSupport":170,"optimizerStarts":544,"optimizerSuccesses":544}`. Starts/completions reconcile with saved receipts; eleven system and all evaluation-calibrator hashes were checked without loading models.

Every outer verification records zero uncertainty-to-mean changes, zero DYNAMIC-mean changes and zero reload differences. Largest Week-1 training/current feature discrepancy: 0. These are fixed fixtures, not an exhaustive proof.

11 focused checks passed: 8 new repair checks and 3 directly relevant existing UI/registration checks. Distinct model/study/publication/UI-registration counts: 4 / 2 / 2 / 3. [Executed commands and scope](<C:/Users/james/asp-model-studio/outputs/nfl-current-state-cold-start-v2/uncertainty-repair-v1/focused-test-receipt.json>); no full repository suite or new evaluation by this report.

The completed repaired handoff contains 60 forecasts for 15 events; 1 saved skip records: `{"KICKOFF_REACHED_BEFORE_REPAIRED_INFERENCE":1}`. Published at 2026-09-10T02:09:09.578772+00:00, using the actual execution clock and 5,000 score draws per forecast. At/after-kickoff events are skipped, never backdated. Inputs end with the 2024 season; 2025 is sealed. Roster/depth context has **NONE numerically incorporated**; no confirmed target starter is claimed. Classification: `HISTORICAL_PRIOR_BASELINE`, not fully current roster-informed forecasts. Future numeric 2026 incorporation is not established.

Actual final-model mean/distribution-mean perturbation mismatches: 0; pregame/orientation-checked forecasts: 60; maximum published mean quantization error: 0.00009888 points. Fresh-clock rerun reused 60 common objects with 0 mismatches. Registration rerun: `NO_OP`. The former CURRENT pointer is preserved. Market comparison: `NOT_RUN_IN_BOUNDED_UNCERTAINTY_REPAIR` (no new quote/decision-study authority). No M1 promotion, old-artifact deletion, wagering action or AISP write.

Exact saved import instruction for the separately versioned research objects:

> Verify checksums/byte counts and import the separate NFL_CURRENT_STATE_*_V2_REPAIRED historical-prior research forecasts and precomputed score distributions. Preserve all prior engines, forecasts and withholding receipts. No model execution, promotion, wagering authority, or current-starter/injury/weather-input claim is permitted.

## Forward archive: actual owner and persistence

Observed local configuration: `archive-nfl-forward-evidence`, status `ACTIVE`, cadence every six hours, owner `JAMES\james`, shell identity `james\james`. Configuration path: `C:\Users\james\.codex\automations\archive-nfl-forward-evidence\automation.toml`; SHA-256 `0215f0cc6437f5ef21e3b4bfe4ae843b70afb0c17b855384ec053ddf4e077dc1`. Command: `.\.venv\Scripts\python.exe -m scripts.archive_nfl_forward_vintages` in `C:\Users\james\asp-model-studio`. Observed heartbeat ownership is not a dedicated service/run-as guarantee.

Persistence after closure/reboot is a filesystem inference, not a reboot test. No archiving occurs with the app closed or computer off. Reopen the same profile, preserve project/interpreter access and verify active status after reboot; startup/catch-up are not guaranteed. This matches the [official scheduled-task operating requirement](https://learn.chatgpt.com/docs/automations?surface=app). Only existing authorized local snapshots are archived—no provider refresh or backdating. Archival begins now, not retrospectively.

## Complete evidence and handoff

[Complete numerical results](<C:/Users/james/asp-model-studio/outputs/nfl-current-state-cold-start-v2/uncertainty-repair-v1/runs/b64fe738b9774e4559f9f15184f81d978a864d27c0a103fe7e8e6e54f6e0795e/result.json>); [Delivery and test receipt](<C:/Users/james/asp-model-studio/outputs/nfl-current-state-cold-start-v2/uncertainty-repair-v1/deliveries/sha256/40ea4aaceb14b72f954dafaeb404b6cbe76922dc0274ba400023fd3f39641d88/delivery.json>); [Frozen repair protocol](<C:/Users/james/asp-model-studio/outputs/nfl-current-state-cold-start-v2/uncertainty-repair-v1/methodology-contract.json>); [Final fitted metadata](<C:/Users/james/asp-model-studio/outputs/nfl-current-state-cold-start-v2/uncertainty-repair-v1/runs/b64fe738b9774e4559f9f15184f81d978a864d27c0a103fe7e8e6e54f6e0795e/final-through2024-lag48/fitted-state.json>); [Exact repaired import handoff](<C:/Users/james/asp-model-studio/outputs/nfl-current-state-cold-start-v2/uncertainty-repair-v1/current-publication/handoffs/sha256/9c2e10c70fdb0696a4304830cc0cd38a611d946c3ad814a2017986b66923144c/handoff.json>); [Archive operating receipt](<C:/Users/james/asp-model-studio/outputs/nfl-current-state-cold-start-v2/uncertainty-repair-v1/archive-automation-operating-requirements.json>). Manifest: exact input/model hashes and generator identity. Rendering makes no model/source reads, fits, evaluations, forecasts or provider calls (models are hashed as opaque bytes only).

This bounded repair ends with the saved scientific result, even if it loses. **Stop NFL expansion; retain M1 and prior/withheld artifacts, and return to MLB only under the next authorized task.**
