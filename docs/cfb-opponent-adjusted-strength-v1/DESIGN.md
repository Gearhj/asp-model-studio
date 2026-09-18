# CFB opponent-adjusted offense/defense — frozen research design

Hypothesis: jointly estimated score-level offense and defense, adjusted for opposing team strength and venue, contain incremental predictive information beyond Gen1's 35 chronological features, especially when same-season support is limited. Support-aware updates may improve the transition from a pooled prior-season estimate to current evidence.

This is not the rejected cluster residual-offset correction (EXP-064), opener/gap residual-variance adjustment (EXP-065), or NFL pass/rush EPA feature screen (EXP-050). It estimates a different response, CFB team scores, with explicit opponent effects and a controlled support update. No clustering, gap variance adjustment, additional model family, imputation search, clipping search, roster, recruiting, injury or conference-data acquisition is included.

## Scope and source

Private reconstructed historical research only, as admitted by `outputs/cfb-gen1-v1/SOURCE_REVIEW.md`. Read `data/admitted-games.parquet` using a season filter before conversion: Development <=2022 first; reused 2023–2025 only after the selection receipt is frozen. No 2026 outcomes, protected MLB payloads, provider requests, paid data, production changes or consumer writes.

Historical primary games are final FBS/FBS regular-season weeks 1–14 under the retained baseline eligibility. Warmup 2014–2015, point OOF 2016, distribution Development 2017–2022, reused Validation 2023–2024, secondary reused assessment 2025. The latter three seasons are already inspected evidence, never untouched holdouts. Evaluation games must be identical for every arm; unavailable distributions are omitted jointly, with counts disclosed.

## Chronology and baseline

There are no genuine historical completion/availability clocks in this source. A final result is usable for same-season feature construction only if the retained source declares final with both scores and its kickoff is at least 48 hours before the target's UTC-date origin. This is an explicit reconstruction embargo assumption, NOT a manufactured completion timestamp or certified historical availability claim. All games on a UTC date share the same eligible history. Retained same-team spacing is greater than 48 hours; verify that the original feature recipe passes this gate and reconciles rather than assuming it. Fail closed on any violation.

Use the exact Gen1 35-feature construction and separate median-imputer / StandardScaler / Ridge(alpha=100) models for margin and total. Refit at each season origin using only earlier primary final games. Never use the fitted through-2025 artifact backward. Save and compare these newly fitted baseline predictions against retained point OOF outputs. Historical joint distributions use the corrected strictly-earlier-season OOF paired residual donor law, minimum 500 donors, unchanged 10,000-draw sampler, floor, stochastic rounding and tie-conditioning. All arms share donor game IDs and random seeds, but use their own honest OOF residuals.

Winner guardrails use joint-derived home-win probabilities. Separately fit the margin logistic calibration at each season origin on that arm's earlier-season OOF predictions and outcomes. The saved all-Development calibrator is not used. Neither calibration nor residual distributions use the target season. Elo remains a separate baseline diagnostic.

## Compact comparison and tuning limits

- Baseline: exact chronological Gen1 method with the stated research history gate and corrected donors.
- A: append two features (strength-implied margin and total) to Gen1's fixed 35 features. Strength is a joint Gaussian partial-pooling estimate `team score = league mean + offense(team) + defense-allowed(opponent) + signed venue`. Earlier complete seasons estimate global nuisance parameters and prior-season effects; a team's immediately preceding-season pooled effects transfer with fixed coefficient 2/3. Missing prior-season support resets team effects to zero, with explicit support metadata.
- B: identical representation and estimator, with per-team prior precision `lambda / (1 + eligible_current_games / 4)` instead of A's constant lambda. No current evidence means the same prior; accumulating eligible games earns greater weight.
- Ablations U_A and U_B: same support, prior, venue, Ridge integration and residual law, but estimate own scoring/conceding effects without opposing-team effects. A versus U_A and B versus U_B isolate opponent adjustment; B versus A and U_B versus U_A isolate dynamic shrinkage. Ablations cannot win selection.

Only `lambda in {4,12}` is searched. All other settings above are fixed. Each Development season uses lambda selected by the lowest mean earlier Development joint energy averaged across A and B; require at least two earlier scored seasons, otherwise default 12. Ties within 0.005 energy choose stronger shrinkage 12. This nested procedure prevents later Development evidence from choosing a parameter for an earlier prediction. For the candidate-grid scoring used to select lambda, each fixed-lambda procedure has its own prior-season OOF residuals. The reported nested A/B procedures have their own actually chosen earlier-origin residuals. U_A/U_B use the same selected lambda and are not tuned independently.

After Development, freeze lambda from all 2017–2022 candidate-grid evidence, then freeze A or B using nested Development energy; prefer A when B's advantage is less than 0.02. Reused 2023–2025 cannot change these choices. Each later season still refits coefficients, preprocessing, prior effects, calibration and residual donors using only that origin's earlier data; fixed design/hyperparameters do not change. Total search is four adjusted configurations, two structurally matched ablations, one baseline; no post-result variants.

## Metrics, subgroup and uncertainty

Primary: mean joint energy score in home/away score units. Guardrails: joint winner log loss and binary home-win Brier; margin and total CRPS. Report home/away/pooled score, margin and total MAE and RMSE, signed bias, joint 80/90% coverage and widths, and calibrated-margin winner scores separately.

Predeclared low-support group: scheduled week <=3 OR either team has fewer than two eligible current-season primary games at the shared UTC-date origin. Report both the union and its opener/zero-prior-support components; no favorable subgroup routing. Report all seasons, including 2020 separately, and ordinary-support complement.

Effects are paired challenger minus baseline on common games. Use 2,000 paired calendar-week block bootstrap resamples stratified by season, retaining whole games and all arms within blocks. Show 95% percentile intervals overall and for the predeclared subgroup; simulation draws are numerical integration samples, never independent observations. The intervals are diagnostic on reused evidence and are not multiplicity-adjusted. Use the same bootstrap resamples across arms/metrics. Report sample and block counts; subgroup inference requires >=100 later games and >=15 blocks.

## Practical advancement gate, fixed before fitting

Only the Development-frozen A/B candidate can qualify for a proposed prospective shadow study. It must improve nested Development energy by >=0.05; improve reused 2023–2024 energy by >=0.10 and have paired 95% upper bound below zero; improve energy in both 2023 and 2024; and worsen secondary 2025 energy by no more than 0.05. Reused Validation guardrail degradations must be <=0.005 log loss, <=0.002 Brier, and <=0.05 for each CRPS. The low-support union must have mean energy degradation <=0.05 and upper95 <=0.15 with adequate support; otherwise no broad shadow recommendation. Report failures literally. 2025 cannot rescue failed Validation.

A promising pass earns only a proposed frozen prospective shadow study. An imprecise benefit below this gate can justify refining exactly one supported component, with a new future design; it cannot justify another sweep here. If effects are materially harmful or unsupported, drop this representation. Production champion, publishers, policy and authority remain unchanged.

## Deliverables

Retain design/configuration hashes before fitting; fold artifacts and strength snapshots; source bindings and gate accounting; common-population predictions, per-game score rows and paired effects; frozen selection receipt before later outcomes; comparison table; standalone scientific diagnostic figures; reproducible runner, focused chronology/estimation tests and independent methodology/result checks. Fitted data/artifacts remain private outside Git. Source-only worktree: `C:\Users\james\asp-model-studio-source-cfb-strength`; branch `codex/cfb-opponent-adjusted-strength-v1`.
