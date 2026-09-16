# MLB Governed Player Prior Engine V1 — Implementation Report

This report records the governed, target-free preprocessing authority implemented for the exact project **MLB 2026 Current-Data Challenger v2 — Deliberate Development**. It is a preprocessing deliverable only. No predictive model was fit, no score or calibration was produced, no policy was adopted, no feature set was registered, and final OOT remained locked and unopened.

## 1. Starting branch/HEAD

- Branch: `codex/mlb-feature-treatment-spec-v1`
- HEAD: `3b7cad59930cdfe5e14cf401774a40a256ff69fc`
- Starting status contained only the two preserved untracked user files: `ASP_MLB_Feature_Treatment_Specification.xlsx` and `docs/PHASE_7D3_CODEX_FINAL_SILVER_READINESS_REPORT.md`. Neither was changed, staged, moved, or deleted.

## 2. Final branch/HEAD

- Branch: `codex/mlb-governed-prior-engine-v1`
- Code HEAD before this documentation commit: `340e5e5824041f096639efd36c8d0a5fc636c347`
- Delivery HEAD: the local documentation commit containing this report; the exact SHA is recorded in the final task response because a commit cannot contain its own identity.

## 3. Main HEAD

- `main`: `924db29511f93909f9d785855bfa056775443690`
- `main` was not checked out, modified, rebased, or rewritten.

## 4. Target project ID

- Project ID: `asp-mtlozhdx`
- Exact name: `MLB 2026 Current-Data Challenger v2 — Deliberate Development`

## 5. Current Gold identity

- Dataset: `gold-table:gold_mlb_current_pa_v1`
- Physical manifest SHA-256: `67de02ce19738b29953341151640fb69244b764b0e532b687ab6bacedbb3f758`
- Contextual manifest SHA-256: `4c228116951a3505d6a5d955f00cd2b92b35b1ccb85c7c69d11d77828485320e`
- Source registration: `sports-dataset-current-statcast-03ca6dab30e760b2`
- Source manifest: `03ca6dab30e760b2b86b65308090c2d358a67127cc34dfde7a75fc198c3ba84c`
- Development: 683,662 rows, 2023-03-30 through 2026-08-13.
- Locked final OOT: 14,067 rows, 2026-08-14 through 2026-08-27; not opened.
- Split authority: `sports-forecast-contract:asp-mtlozhdx:v1:sha256:352e3438d7ddbafab988132befc7d42e50d73acba0628f653ccdb38b98a1ece8`.

## 6. Prior-blocker count before

The accepted V2 draft had **24** prior-related blockers: 23 `HIERARCHICAL_PRIOR_PLUS_INDICATOR` recommendations and one `ROLE_OR_LEAGUE_PRIOR_PLUS_INDICATOR` recommendation (`pitcher_last250_avg_fastball_velocity`). The two exposure encodings were evidence inputs, not additional prior blockers.

## 7. Exact 24 prior-blocked features

The table records the required inventory, method, indicator, exposure, new status, and exact fail-closed reason. At task start every row's executable status was `BLOCKED_REQUIRES_PRIOR_AUTHORITY`. All 24 are `CORE_GOLD_48` features whose registered primary missing reason is `NO_PRIOR_HISTORY`; missing percentages come from the accepted treatment authority.

| Feature | Side / statistic | Missing % | Indicator(s) | Exposure authority | Governed method | Result / exact remaining blocker |
|---|---|---:|---|---|---|---|
| `pitcher_whip` | Pitcher / non-Bernoulli rate | 10.806509649505 | `pitcher_prior_missing` | Prior IPouts / 3, plus BB and H; unavailable | `GAMMA_POISSON_COMPONENT_SHRINKAGE_REQUIRED` | BLOCKED — WHIP requires prior IPouts plus BB and H; BFP is not its denominator and those sufficient statistics are not materialized in Current Gold. |
| `pitcher_era9` | Pitcher / non-Bernoulli rate | 10.806509649505 | `pitcher_prior_missing` | Prior IPouts and ER; unavailable | `GAMMA_POISSON_COMPONENT_SHRINKAGE_REQUIRED` | BLOCKED — ERA9 requires prior IPouts and ER; BFP is not its denominator and those sufficient statistics are not materialized in Current Gold. |
| `pitcher_so_per_bfp` | Pitcher / bounded proportion | 10.798318467313 | `pitcher_prior_missing` | Exact prior-season BFP from registered `expm1(pitcher_log1p_bfp)` with integer validation | `BETA_BINOMIAL_EMPIRICAL_BAYES` | `READY_GOVERNED_PRIOR_V1` |
| `pitcher_hr_per_bfp` | Pitcher / bounded proportion | 10.798318467313 | `pitcher_prior_missing` | Exact prior-season BFP from registered `expm1(pitcher_log1p_bfp)` with integer validation | `BETA_BINOMIAL_EMPIRICAL_BAYES` | `READY_GOVERNED_PRIOR_V1` |
| `pitcher_hbp_per_bfp` | Pitcher / bounded proportion | 10.798318467313 | `pitcher_prior_missing` | Exact prior-season BFP from registered `expm1(pitcher_log1p_bfp)` with integer validation | `BETA_BINOMIAL_EMPIRICAL_BAYES` | `READY_GOVERNED_PRIOR_V1` |
| `pitcher_gs_per_g` | Pitcher / bounded proportion | 10.798318467313 | `pitcher_prior_missing` | Exact games and games started; unavailable | `BETA_BINOMIAL_EMPIRICAL_BAYES_REQUIRES_G` | BLOCKED — GS/G requires exact prior games and games-started counts; BFP is invalid and neither count is materialized. |
| `pitcher_bb_per_bfp` | Pitcher / bounded proportion | 10.798318467313 | `pitcher_prior_missing` | Exact prior-season BFP from registered `expm1(pitcher_log1p_bfp)` with integer validation | `BETA_BINOMIAL_EMPIRICAL_BAYES` | `READY_GOVERNED_PRIOR_V1` |
| `batter_so_per_pa` | Batter / bounded proportion | 7.723845994073 | `batter_prior_missing` | Exact prior-season PA from registered `expm1(batter_log1p_pa)` with integer validation | `BETA_BINOMIAL_EMPIRICAL_BAYES` | `READY_GOVERNED_PRIOR_V1` |
| `batter_slg` | Batter / non-Bernoulli rate | 7.723845994073 | `batter_prior_missing` | Exact AB and total-base components; unavailable | `DIRICHLET_MULTINOMIAL_COMPONENT_SHRINKAGE_REQUIRED` | BLOCKED — SLG requires exact at-bats and total-base components; prior PA is not its denominator and the sufficient statistics are not materialized. |
| `batter_obp` | Batter / bounded proportion | 7.723845994073 | `batter_prior_missing` | Exact AB+BB+HBP+SF; unavailable | `BETA_BINOMIAL_EMPIRICAL_BAYES_REQUIRES_OBP_OPPORTUNITIES` | BLOCKED — prior PA includes sacrifice hits and cannot replace the unmaterialized OBP denominator. |
| `batter_hr_per_pa` | Batter / bounded proportion | 7.723845994073 | `batter_prior_missing` | Exact prior-season PA from registered `expm1(batter_log1p_pa)` with integer validation | `BETA_BINOMIAL_EMPIRICAL_BAYES` | `READY_GOVERNED_PRIOR_V1` |
| `batter_bb_hbp_per_pa` | Batter / bounded proportion | 7.723845994073 | `batter_prior_missing` | Exact prior-season PA from registered `expm1(batter_log1p_pa)` with integer validation | `BETA_BINOMIAL_EMPIRICAL_BAYES` | `READY_GOVERNED_PRIOR_V1` |
| `batter_avg` | Batter / bounded proportion | 7.723845994073 | `batter_prior_missing` | Exact AB and hits; unavailable | `BETA_BINOMIAL_EMPIRICAL_BAYES_REQUIRES_AB` | BLOCKED — AVG requires exact at-bats and hits; prior PA is not its denominator and at-bats are not materialized. |
| `pitcher_last250_avg_fastball_velocity` | Pitcher / continuous mean | 1.043059289532 | `pitcher_last250_insufficient`, `pitcher_last250_velocity_missing` | Eligible fastball count and within-window variance; unavailable | `NORMAL_NORMAL_REQUIRES_FASTBALL_COUNT_AND_VARIANCE` | BLOCKED — BF count is not a velocity-observation count. |
| `pitcher_last250_whiff_rate` | Pitcher / bounded proportion | 1.003712360786 | `pitcher_last250_insufficient`, `pitcher_last250_whiff_missing` | Exact classifiable-swing count; unavailable | `BETA_BINOMIAL_REQUIRES_SWING_COUNT` | BLOCKED — BF count is not the denominator and swing count is not materialized. |
| `pitcher_last250_walk_rate` | Pitcher / bounded proportion | 1.002688463012 | `pitcher_last250_insufficient` | Exact `pitcher_last250_bf_count`, integer validated | `BETA_BINOMIAL_EMPIRICAL_BAYES` | `READY_GOVERNED_PRIOR_V1` |
| `pitcher_last250_strikeout_rate` | Pitcher / bounded proportion | 1.002688463012 | `pitcher_last250_insufficient` | Exact `pitcher_last250_bf_count`, integer validated | `BETA_BINOMIAL_EMPIRICAL_BAYES` | `READY_GOVERNED_PRIOR_V1` |
| `pitcher_last250_offspeed_usage` | Pitcher / bounded proportion | 1.002688463012 | `pitcher_last250_insufficient` | Exact all-pitch opportunity count; unavailable | `DIRICHLET_MULTINOMIAL_REQUIRES_PITCH_COUNT` | BLOCKED — BF count is not the denominator and pitch count is not materialized. |
| `pitcher_last250_fastball_usage` | Pitcher / bounded proportion | 1.002688463012 | `pitcher_last250_insufficient` | Exact all-pitch opportunity count; unavailable | `DIRICHLET_MULTINOMIAL_REQUIRES_PITCH_COUNT` | BLOCKED — BF count is not the denominator and pitch count is not materialized. |
| `pitcher_last250_breaking_usage` | Pitcher / bounded proportion | 1.002688463012 | `pitcher_last250_insufficient` | Exact all-pitch opportunity count; unavailable | `DIRICHLET_MULTINOMIAL_REQUIRES_PITCH_COUNT` | BLOCKED — BF count is not the denominator and pitch count is not materialized. |
| `batter_last100_whiff_rate` | Batter / bounded proportion | 0.191176341525 | `batter_last100_insufficient`, `batter_last100_whiff_missing` | Exact classifiable-swing count; unavailable | `BETA_BINOMIAL_REQUIRES_SWING_COUNT` | BLOCKED — PA count is not the denominator and swing count is not materialized. |
| `batter_last100_contact_rate` | Batter / bounded proportion | 0.191176341525 | `batter_last100_insufficient`, `batter_last100_whiff_missing` | Exact classifiable-swing count; unavailable | `BETA_BINOMIAL_REQUIRES_SWING_COUNT` | BLOCKED — PA count is not the denominator and swing count is not materialized. |
| `batter_last100_walk_hbp_rate` | Batter / bounded proportion | 0.190444985973 | `batter_last100_insufficient` | Exact `batter_last100_pa_count`, integer validated | `BETA_BINOMIAL_EMPIRICAL_BAYES` | `READY_GOVERNED_PRIOR_V1` |
| `batter_last100_strikeout_rate` | Batter / bounded proportion | 0.190444985973 | `batter_last100_insufficient` | Exact `batter_last100_pa_count`, integer validated | `BETA_BINOMIAL_EMPIRICAL_BAYES` | `READY_GOVERNED_PRIOR_V1` |

All 24 belong to `CORE_GOLD_48`. For ready bindings, `rate × trials` must reconstruct an integer event numerator within `1e-6`; otherwise transformation fails closed as a computation failure. No nearby but semantically wrong denominator is substituted.

## 8. Exact prior method per feature

The **Governed method** column in Section 7 is the canonical per-feature method map. Eleven exact-denominator bounded proportions use Beta-Binomial empirical Bayes. The other 13 retain the method that would be scientifically required—Gamma-Poisson component shrinkage, Dirichlet-Multinomial component shrinkage, Normal-Normal shrinkage, or Beta-Binomial with the statistic-specific missing opportunity count—and remain blocked.

## 9. Player/role/league hierarchy

The executable hierarchy is **player history → global MLB population**. The design records the role layer as `NOT_AVAILABLE_IN_CURRENT_GOLD_NOT_INVENTED`: Current Gold has no governed point-in-time role/archetype taxonomy, so V1 does not infer one. A true rookie therefore falls to the fold-fitted MLB league prior, not a fabricated role cluster. Role-prior use in diagnostics is exactly zero.

## 10. Exposure authority per feature

The **Exposure authority** column in Section 7 is the exact binding map. Executable denominators are only registered, integer-validated prior-season BFP/PA or exact bounded-window BF/PA counts. Every unavailable statistic-specific denominator remains named and blocked; PA/BFP is never substituted by proximity.

## 11. Decay authority

- Annual state: `NO_DECAY_ANNUAL_STATE_SOURCE_AGE_NOT_MATERIALIZED`. The latest eligible prior-season state is preserved across season boundaries; exact observation age is not present, so V1 refuses to fabricate a 365- or 730-day decay.
- Rolling state: `NO_ADDITIONAL_DECAY_ALREADY_RECENCY_BOUNDED_WINDOW` for the registered last-250-BF and last-100-PA histories.
- `decay_weight` is 1 for valid posterior rows and `observation_age_days` is null because exact age is unavailable.

## 12. Prior-strength estimation

Each ready feature is fitted only from the caller-supplied chronological training partition. The population unit is each player's latest valid state at or before the training cutoff. The mean is a Jeffreys-stabilized pooled event rate. The between-player component is the unweighted sample variance minus mean binomial sampling variance. Method-of-moments concentration supplies feature-specific prior strength, with a training-player median-exposure fallback when underidentified and a training-player exposure-p95 upper bound. Validation performance and final OOT never select prior strength.

## 13. Posterior formula

For each executable bounded proportion, with prior `Beta(alpha, beta)`, exact observed successes `x`, and exact trials `n`:

```text
posterior_alpha = alpha + x
posterior_beta  = beta + n - x
posterior_mean  = posterior_alpha / (posterior_alpha + posterior_beta)
posterior_var   = posterior_alpha * posterior_beta
                  / ((posterior_alpha + posterior_beta)^2
                     * (posterior_alpha + posterior_beta + 1))
```

This is algebraically equivalent to `(prior_strength × prior_mean + n × raw_rate) / (prior_strength + n)`. Alpha and beta remain positive; domain, denominator, and integer-numerator checks fail closed.

## 14. Continuous-feature shrinkage formula

The declared continuous family is normal-normal weighting, conceptually `mu_post = (w_prior × mu_prior + w_observed × x_bar) / (w_prior + w_observed)`, with feature-specific observation count and variance. No continuous V1 feature is marked executable: fastball velocity lacks eligible-fastball count and within-window variance, while ERA9 and WHIP lack their required component sufficient statistics. The engine records their exact required methods and leaves them blocked instead of manufacturing weights.

## 15. Reliability formula

`posterior_reliability = observed_effective_n / (prior_strength + observed_effective_n)`, constrained to `[0, 1]`. Zero exposure is prior-dominated (`0`); increasing valid exposure approaches `1`. This is preprocessing reliability, not model confidence.

## 16. Point-in-time guarantees

- Row-level player state is consumed from registered Current Gold histories whose lineage is `source.gameDate < target.gameDate`; same-date/current-PA outcomes are excluded upstream.
- Target columns are neither required nor scanned. Changing/removing the current-row outcome cannot change that row's prior outputs.
- Every transform row requires a valid date and V1 rejects any date after 2026-08-13.
- An earlier row depends only on its materialized pre-row player history plus a frozen training-authorized population prior; appending or changing later transform rows does not alter it.
- Population fitting and row history are distinct: population parameters may use all evidence authorized inside the training partition, while each row's player-specific evidence remains strictly pre-row. No validation or OOT evidence is admitted to that fit.

## 17. Fold-local guarantees

For each chronological fold: fit population hyperparameters on training rows only, freeze the content-addressed fitted authority, then transform training/validation scientific values with that frozen authority. Rows after the supplied cutoff are excluded before any feature, exposure, indicator, player ID, or missing-reason values are read. Tests prove validation mutations do not affect fitted parameters. Non-tree bindings require an explicit training-row scaler checksum; tree bindings declare no scaler. The five benchmark folds are timing evidence only and do not register or replace the project's split authority.

## 18. Cross-season handling

The registered annual fields already carry latest eligible prior-season evidence, so an established player is not reset to league average on Opening Day. V1 preserves that evidence without decay because source age is unavailable. Later-season rows are excluded by the fitting cutoff before feature values are read, and tests show future-season rows cannot alter an earlier-cutoff fit.

## 19. True-rookie handling

The supported states are `ESTABLISHED_HISTORY`, `PRIOR_SEASON_ONLY`, `SPARSE_HISTORY`, `TRUE_COLD_START`, `SOURCE_UNAVAILABLE`, and `COMPUTATION_FAILURE`. `ROLE_CHANGE` is deliberately absent because no governed point-in-time role evidence exists. True cold start requires a registered indicator plus exact numeric zero exposure; it receives the MLB population posterior with reliability 0. A missing exposure is never silently converted to zero merely because a rolling insufficient-history flag is present.

## 20. Source-unavailable separation

Explicit source reasons, unavailable components, and a missing rate beside positive source exposure produce `SOURCE_UNAVAILABLE` and `NONE_FAIL_CLOSED`. They do not receive a player/league posterior. The fitted population excludes explicit source-failure states even if an anomalous numeric value is present.

## 21. Computation-failure separation

Explicit `COMPUTATION_FAILURE`, invalid/inconsistent numerics, a finite rate with absent/nonpositive exposure, noninteger recovered trials, or a noninteger reconstructed event numerator produce `COMPUTATION_FAILURE`. These rows receive no posterior and cannot masquerade as rookies. The live development evidence contains 168 computation-failure feature cells across 56 rows.

## 22. Derived feature identities

Each of the 11 ready raw features is retained and receives a governed `__prior_v1` family with 17 outputs: posterior mean, effective N, prior strength, posterior strength, posterior variance, posterior standard deviation, posterior reliability, history state, prior level, observed successes, observed trials, prior alpha, prior beta, posterior alpha, posterior beta, decay weight, and observation age days. Lineage binds raw feature, exposure, player ID, history cutoff/window, population authority, decay, treatment specification, project, and Gold identities. These are registered preprocessing outputs only; no model feature set was registered.

## 23. Prior authority identity/checksum

- Authority ID: `MLB_PLAYER_STATE_PRIOR_AUTHORITY_V1:sha256:a363331fc47083bf5aaac07c437f2998ea21650b78538d2a69e258851812ff43`
- Authority checksum: `a363331fc47083bf5aaac07c437f2998ea21650b78538d2a69e258851812ff43`
- Configuration checksum: `52f31ef8384697812083a7271b4bbf5d96a6a28b9a30809f80abcbd198536c5e`
- Final-development fitted ID: `MLB_PLAYER_STATE_FITTED_PRIOR_V1:FINAL_DEVELOPMENT_ONLY:sha256:0bca065ce19a1e5b3820cebb82b4ba2658f0691097c023ef6744973efe74202a`
- Stable science artifact SHA-256: `afe4ebdae76ef5c9429637c0b01007d464ca3b921092e92fa6486c3e3e2a139b` (89,512 bytes).
- An identical scientific rerun reproduced the exact artifact SHA; run-specific timings were separated into performance receipt `e6c19c2a8ab128cf0e06a012eba5b46d6fcf7b39805966e3a528d76a2226a20f` (2,452 bytes).

## 24. Treatment-specification identity before and after recompilation

- Before: `MLB_FEATURE_TREATMENT_SPEC_V1:sha256:2e0d40f6337a20d9e4cccf98c08d3460a32545b7d29035b50a69d4c49e8703df` in combined DRAFT `stage3-feature-treatment-spec-c2829651e7314a818d8cde1230cdaaf4`.
- Deterministic governed-prior compilation: `MLB_FEATURE_TREATMENT_SPEC_V1:sha256:2cc3aaecbd8663a932f5088845e76e15b2f5461bc918fe17254684a92048cafe`.
- Saved governed-prior combined DRAFT: `stage3-feature-treatment-spec-22e4a89375cf43c58febe23f94f727bf`, v3, content SHA-256 `d30525df3bbe05fc1bf1a8907b245143f5de9b62fe422e09b904f5a9d8c0af32`.
- Linked outlier DRAFT: `stage3-outlier-policy-262359558da4445193d6a115af4ba5cd`, SHA-256 `a2e7819f92dbc90481ea8b0faa4fe8689e567944be7413cb195437e11e573ec1`.
- Linked missing-value DRAFT: `stage3-imputation-policy-81821f7e4e0b426ca6665239aea36dae`, SHA-256 `73796e25c3f7868b814ee9816a575c1a74ccc94864c5f3876feb4d5be0e70116`.
- The old combined, outlier, and missing-value v2 drafts remain immutable with their original IDs, checksums, creation time, counts, and event history. The browser save appended exactly one v3 combined record and its two linked child-policy drafts; a later project autosave was idempotent and created no v4. All six child policies and all three combined specifications remain DRAFT, with zero adopted records.

## 25. Prior blockers cleared

**11 of 24** became `READY_GOVERNED_PRIOR_V1`: `pitcher_so_per_bfp`, `pitcher_hr_per_bfp`, `pitcher_hbp_per_bfp`, `pitcher_bb_per_bfp`, `batter_so_per_pa`, `batter_hr_per_pa`, `batter_bb_hbp_per_pa`, `pitcher_last250_walk_rate`, `pitcher_last250_strikeout_rate`, `batter_last100_walk_hbp_rate`, and `batter_last100_strikeout_rate`.

## 26. Prior blockers remaining

**13 of 24** remain blocked: `pitcher_whip`, `pitcher_era9`, `pitcher_gs_per_g`, `batter_slg`, `batter_obp`, `batter_avg`, `pitcher_last250_avg_fastball_velocity`, `pitcher_last250_whiff_rate`, `pitcher_last250_offspeed_usage`, `pitcher_last250_fastball_usage`, `pitcher_last250_breaking_usage`, `batter_last100_whiff_rate`, and `batter_last100_contact_rate`. Their exact missing sufficient statistics appear in the inventory table.

## 27. Remaining unrelated blockers

The 24 unrelated blockers remain intentionally unresolved: semantic/calendar 2, interaction recomputation 8, and rivalry authority 14. Together with the 13 remaining prior blockers, the recompiled policy has 37 blockers. Execution summary: 240 workbook features, 14 additional held closed, 184 ready (including 11 governed-prior-ready), 22 explicit fallback, 37 blocked, 121 automatic retain, 6 automatic exclude, and 2 semantic review. `canAdopt` remains false.

## 28. Diagnostic counts

Diagnostics are target-free and development-only over 683,662 rows and 11 ready features.

| Evidence | Count |
|---|---:|
| Rows using player history | 683,646 |
| Rows using a role prior | 0 |
| Rows using the league prior | 119,947 |
| True-cold-start rows | 119,947 |
| Computation-failure cells / rows present | 168 / 56 |
| Established-history cells / rows present | 2,430,624 / 677,102 |
| Prior-season-only cells / rows present | 4,331,923 / 677,026 |
| Sparse-history cells / rows present | 287,710 / 137,957 |
| True-cold-start cells / rows present | 469,857 / 119,947 |
| Player+league cells | 7,050,257 |
| League-only cells | 469,857 |
| Fail-closed cells | 168 |

- Reliability quantiles p0/p25/p50/p75/p90/p100: `0`, `0.4895760131`, `0.7049425170`, `0.8218766575`, `0.9082997688`, `0.9627046690`.
- Effective-N quantiles p0/p25/p50/p75/p90/p100: `0`, `100`, `250`, `436`, `649`, `886`.
- Posterior-minus-raw quantiles p0/p25/p50/p75/p90/p100: `-0.9011765893`, `-0.0050941776`, `0.0004160064`, `0.0061447294`, `0.0155341581`, `0.2454026370`.
- Per-feature state, reliability, adjustment-by-month, and adjustment-by-state maps are persisted in the stable science artifact.

## 29. Performance timings

The final repeat measured development-only preprocessing; timings are operational receipts and are excluded from scientific content identity.

| Scope | Train / validation rows | Fit ms | Transform ms |
|---|---:|---:|---:|
| Benchmark fold 1 | 115,383 / 112,062 | 2,101.905 | 1,374.686 |
| Benchmark fold 2 | 227,445 / 114,707 | 3,944.419 | 1,112.612 |
| Benchmark fold 3 | 342,152 / 111,819 | 3,965.209 | 944.000 |
| Benchmark fold 4 | 453,971 / 115,448 | 5,509.968 | 952.263 |
| Benchmark fold 5 | 569,419 / 114,243 | 6,623.470 | 985.804 |

- Development scan: 717.162 ms.
- Final-development population fit: 7,882.776 ms.
- Full development diagnostics: 20,296.136 ms.
- Input frame: 296,025,778 bytes.
- Process working set before / after scan / peak observed at phase boundaries: 198,823,936 / 706,580,480 / 832,221,184 bytes. This is an honest sampled-boundary measurement, not an instrumented high-water mark.
- Science artifact / performance receipt: 89,512 / 2,452 bytes.

## 30. Tests and exact results

- Integrated backend authority/spec/treatments/feature-engineering gate: **56 passed in 44.24s**, 0 failures, no pytest warnings.
- Frontend treatment and feature-engineering contract suites: **30/30 passed in 196.6933 ms**, 0 failed/skipped/cancelled/todo.
- TypeScript + modeling production build: `npm run build:modeling` — PASS; 2,336 modules transformed and production bundle built in 37.23s. Non-blocking baseline-data, mixed static/dynamic import, and large-chunk warnings remain.
- `git diff --check`: pass; only an informational Windows LF→CRLF working-copy warning was emitted before the normalization fix was committed.
- Coverage includes deterministic bindings and identities; idempotence; training/validation/OOT isolation; target independence; later-row and future-season isolation; annual/rolling/cold/sparse/source/failure states; numeric domains; non-tree scaler evidence; canonical family values; no model fit; immutable old drafts/artifact/Gold/OOT; and UI/read-only contracts.

## 31. Browser acceptance

**PASS** in the authenticated Codex in-app browser at both 1920×1080 and 1024×768. The transient sign-in failure was resolved by running the canonical application launcher against the configured security database; the existing authenticated session then opened exact project `asp-mtlozhdx` without inspecting or changing credentials.

- Outliers: clean responsive layout; development 683,662 and final OOT 14,067 locked; exact prior authority and 11 READY / 13 BLOCKED visible; `No statistical detector` and `No treatment — retain` remain selected; no IQR selection; combined v3 DRAFT visible; adoption disabled.
- Missing Values: clean responsive layout; exact prior authority, method, hierarchy, reliability/uncertainty, and 11 READY / 13 BLOCKED visible; legitimate cold start remains distinct from source/computation failure; semantic/calendar, interaction-recomputation, and rivalry blockers remain explicit; combined v3 DRAFT visible; adoption disabled and Feature Engineering progression held closed.
- Feature Engineering: clean responsive layout; governed preprocessing panel exposes the authority ID, method, hierarchy, 11 READY / 13 BLOCKED / 24 governed rows, draft identity, and posterior/effective-sample-size/reliability/uncertainty output contract; the page explicitly performs no fit, tune, registration, or adoption; candidate registration is disabled, registered feature-set count remains zero, and model activity remains 0 fit / 0 promoted.
- Only the authorized new DRAFT save was exercised. No adopt, register, fit, tune, score, calibrate, promote, or final-OOT control was exercised. The browser was returned to its default viewport and left open on the exact project.

## 32. Historical artifact verification

- Artifact ID: `stage3-executable-artifact-11dc936dcf9d558fe3d8f0a179615b19`.
- Before SHA-256: `58ddf83092c2e91fde4c61c35f16c8cc5a3702d3a4da8f9f9164f2eab5641f6b`.
- After SHA-256: `58ddf83092c2e91fde4c61c35f16c8cc5a3702d3a4da8f9f9164f2eab5641f6b`.
- Size: 36,207 bytes. It remains an earlier-project `RESEARCH_CHALLENGER`, `NOT_PROMOTED`; no new authority was attached retroactively.

## 33. Current Gold mutation count

**0**. Science evidence records `goldRowsMutated=0` and `sourceRowsMutated=0`; the evaluator is a required-column, development-only scanner.

## 34. Final-OOT access count

**0 rows opened/read; 0 targets accessed**. Scanner columns contain no target, dates are hard-bounded at 2026-08-13, diagnostics record `targetRead=false`, and authority evidence records `finalOotRowsOpened=0`.

## 35. Model fit count

**0 predictive model fits**. The six recorded fits are preprocessing-only (five timing folds plus final development prior authority).

## 36. Score count

**0**.

## 37. Calibration count

**0**.

## 38. Promotion count

**0**. No treatment policy was adopted and no feature set was registered.

## 39. Files changed

1. `scripts/evaluate_mlb_player_prior_authority.py`
2. `server/sports_current_statcast/stage3_feature_treatment_spec.py`
3. `server/sports_current_statcast/stage3_player_prior_authority.py`
4. `server/sports_current_statcast/stage3_treatments.py`
5. `src/sports/cockpit/ProjectBoundFeatureEngineering.tsx`
6. `src/sports/cockpit/ProjectBoundMissingStudio.tsx`
7. `src/sports/cockpit/TreatmentStudioShell.tsx`
8. `src/sports/cockpit/projectFeatureSplitApi.ts`
9. `src/sports/cockpit/projectTreatmentApi.ts`
10. `tests/sportsStage3FeatureSplitFrontend.test.mjs`
11. `tests/sportsStage3TreatmentStudiosFrontend.test.mjs`
12. `tests/sports_stage3_feature_treatment_spec_test.py`
13. `tests/sports_stage3_player_prior_authority_test.py`
14. `docs/MLB_GOVERNED_PLAYER_PRIOR_ENGINE_V1_IMPLEMENTATION_REPORT.md`

No migration was necessary. The two preserved untracked user files are not part of this list.

## 40. Commits created

1. `ba4328cc5586d4688c5330f6c46e17cd2485d0a5` — `feat(stage3): add governed MLB player prior authority`
2. `e739db77cf9d48677e9da2e93d392ee0f3bf0f3e` — `feat(stage3): integrate governed cold-start prior policy`
3. `06da8ef6ada71909f0e0bf31153c28618ad675f4` — `feat(ui): expose governed prior audit evidence`
4. `32be0f5b20d8803d7870b03a8999af4fdca76f59` — `test(stage3): prove governed prior isolation and contracts`
5. `340e5e5824041f096639efd36c8d0a5fc636c347` — `fix(stage3): stabilize prior implementation identity`
6. Documentation commit containing this report — exact SHA recorded in the final task response.

## 41. Pushes performed

**0**. All work remains local.

## 42. Remaining decisions for James

1. Decide whether to materialize and govern the exact sufficient statistics required by the 13 remaining prior features: IPouts/BB/H/ER; G/GS; AB/hits/OBP opportunities/total-base components; eligible-fastball count/variance; swing counts; and pitch counts.
2. Decide whether a future Current Gold revision should register a point-in-time role taxonomy. V1 correctly uses global MLB fallback because no governed role authority exists today.
3. Resolve the 24 unrelated semantic/calendar, interaction-recomputation, and rivalry-authority blockers before considering adoption.
4. In a separately authorized future task, decide which governed derived outputs enter a model feature set and then run model selection. This task deliberately registered neither a feature set nor a model.
5. Keep final OOT sealed until a separately approved, frozen candidate and evaluation package are ready.

Final implementation status: `MLB_GOVERNED_PRIOR_ENGINE_PARTIALLY_READY`.
