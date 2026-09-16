# MLB Player-State Prior Wave 2 Implementation Report

Final verdict: `MLB_PLAYER_STATE_PRIOR_WAVE2_READY`.

This report records the content-addressed, fold-local empirical-Bayes implementation for the ten Wave 2 MLB player-state prior bindings. Wave 2 publishes estimator definitions, five chronological fitted-fold authorities, a distinct final-development fitted authority, diagnostics, performance evidence, executable preprocessing bindings, and a new treatment DRAFT. It does not register a model feature set, adopt a policy, fit or score a predictive model, calculate challenger lift, promote a model, or open final OOT.

## 1. Starting worktree/branch/HEAD

- Worktree: `C:\Users\james\asp-model-studio\.tmp\asp-player-prior-wave2`
- Branch: `codex/mlb-player-prior-wave2`
- Verified starting HEAD: `64a74be89b029adc013e118b14aad75e3ddc0232`
- Starting lineage: `codex/mlb-remaining-feature-authority-wave1`

The start commit was selected only after verifying that it was the latest coherent descendant containing `MLB_FEATURE_TREATMENT_SPEC_V1`, `MLB_PLAYER_STATE_PRIOR_AUTHORITY_V1`, the completed interaction-recomputation authority, and their persistence, test, and UI contracts. No interaction authority was independently reproduced or omitted, and the lineage was not ambiguous.

## 2. Final branch/HEAD

- Final branch: `codex/mlb-player-prior-wave2`
- Implementation/test HEAD at the report-generation boundary: `f88f011c88c11ea6c51f6ea4c197ac30fda083cb`

The final delivery HEAD is the documentation commit that contains this report and is stated in the delivery response. A Git commit cannot embed its own SHA-1 in its contents without changing that SHA-1.

## 3. Main HEAD

- Repository main HEAD observed during execution: `924db29511f93909f9d785855bfa056775443690`
- The isolated branch was intentionally based on the verified coherent descendant in section 1, not assumed from main and not assumed from the older `33cd85fa5074efeec3077036baea9c8b2ef86bdf` reference.
- The protected primary checkout and its user-owned untracked files were not modified.

## 4. Project, Gold, and companion identities

| Authority | Identity |
| --- | --- |
| Project | `asp-mtlozhdx` |
| Gold manifest checksum | `67de02ce19738b29953341151640fb69244b764b0e532b687ab6bacedbb3f758` |
| Wave 1 sufficient-statistics companion checksum | `98673b65dc5eab61e39b16d1313c27bbb2cf908c525f80db579cb07a5cfdab33` |
| Companion validation receipt | `cced6892ce10420a5a9d7b2bbf32bea551578ab71daf9f51ec4b3e7bb2394037` |
| Companion physical-schema checksum | `8d5eb7f1318a4eed4642080b7ee3b445653401615d9ae44290a7b8b3ea85fb8f` |
| Companion validation-evidence checksum | `4a9209aa7e6850d2b3e2ec721514790c47fcc2c4f7072d2302183ff18a740fe7` |
| Companion inactive registration | `sports-dataset-sufficient-stats-98673b65dc5eab61` |
| Companion binding authority | `MLB_SUFFICIENT_STATISTICS_BINDING_AUTHORITY_V1:sha256:dbee3d1f5f414e3edd28cee10cd563189438be1bc9c9e852f88c962a5a8f5287` |
| Companion-extended Wave 1 prior authority | `MLB_PLAYER_STATE_PRIOR_AUTHORITY_V1:sha256:9e5a265fe6af876dd5facb9f5f0425f887e34508730eb273abe347a279e676bd` |

The companion contains 697,729 keyed rows: 683,662 development rows and 14,067 sealed final-OOT rows. Its row-identity checksum is `4be4b0ec6517d0a2b43f478c1da7d526c5fab160681c2167b7918a1fdfb7e3cc`.

## 5. Companion authentication result

Authentication passed before fitting or publication. The evaluator verified the receipt, Gold identity, companion identity, binding contract, physical schema, five partition files and their hashes, row identity, validation evidence, source registrations, rights, and limitations. Missing or tampered companion inputs fail closed.

The effective rights are the most-restrictive intersection of FD1/Lahman and Statcast-derived authorities: `GOVERNED_LOCAL_RESEARCH_ONLY`, with `LOCAL_PRIVATE_MODEL_DEVELOPMENT` and read-only registration use, retained attribution obligations, explicit commercial-rights review, and no redistribution or resale.

The V2 parent preserves the companion publication's limitations verbatim. Its sentence “Evidence publication only; Wave 2 estimators are not implemented here” is source-scoped: “here” means the immutable Wave 1 sufficient-statistics companion, not this fitted V2 authority. Component publication alone remains non-executable; V2 execution is attested only by the content-addressed fitted fold and final-development authorities listed below.

## 6. Exact ten bindings

| Feature | Shared science family | Wave 2 status |
| --- | --- | --- |
| `pitcher_whip` | `PITCHER_PRIOR_WHIP_COMPONENTS` | `READY_GOVERNED_PRIOR_V2` |
| `pitcher_gs_per_g` | `PITCHER_GS_APPEARANCE` | `READY_GOVERNED_PRIOR_V2` |
| `batter_slg` | `BATTER_PRIOR_AB_OUTCOME_COMPOSITION` | `READY_GOVERNED_PRIOR_V2` |
| `batter_avg` | `BATTER_PRIOR_AB_OUTCOME_COMPOSITION` | `READY_GOVERNED_PRIOR_V2` |
| `pitcher_last250_avg_fastball_velocity` | `PITCHER_LAST250_FASTBALL_VELOCITY` | `READY_GOVERNED_PRIOR_V2` |
| `pitcher_last250_whiff_rate` | `PITCHER_LAST250_WHIFF` | `READY_GOVERNED_PRIOR_V2` |
| `pitcher_last250_fastball_usage` | `PITCHER_LAST250_PITCH_COMPOSITION` | `READY_GOVERNED_PRIOR_V2` |
| `pitcher_last250_breaking_usage` | `PITCHER_LAST250_PITCH_COMPOSITION` | `READY_GOVERNED_PRIOR_V2` |
| `pitcher_last250_offspeed_usage` | `PITCHER_LAST250_PITCH_COMPOSITION` | `READY_GOVERNED_PRIOR_V2` |
| `batter_last100_whiff_rate` | `BATTER_LAST100_WHIFF` | `READY_GOVERNED_PRIOR_V2` |

The list is exact: no additional binding was promoted to V2, every listed binding is preprocessing-executable, and every raw source feature remains nonselectable and not default-selected.

## 7. Estimator family by binding

| Binding(s) | Implemented estimator family |
| --- | --- |
| `pitcher_gs_per_g` | `BETA_BINOMIAL_OR_TWO_CELL_DIRICHLET_EMPIRICAL_BAYES` |
| `pitcher_last250_whiff_rate` | `BETA_BINOMIAL_OR_TWO_CELL_DIRICHLET_EMPIRICAL_BAYES` |
| `batter_last100_whiff_rate` | `BETA_BINOMIAL_OR_TWO_CELL_DIRICHLET_EMPIRICAL_BAYES` |
| Three pitcher pitch-usage bindings | `DIRICHLET_MULTINOMIAL_EMPIRICAL_BAYES`, one shared four-cell fit |
| `batter_avg`, `batter_slg` | `DIRICHLET_MULTINOMIAL_EMPIRICAL_BAYES`, one shared five-cell fit |
| `pitcher_whip` | `GAMMA_POISSON_COMPONENT_SHRINKAGE` |
| `pitcher_last250_avg_fastball_velocity` | `NORMAL_NORMAL_EMPIRICAL_BAYES` |

This realizes all required Wave 2 method families. Publication of sufficient-statistic components alone is never treated as estimator execution.

## 8. Mathematical formulation by family

- Two-cell/Beta-Binomial: with fitted prior mean `mu` and concentration `kappa`, `alpha = mu*kappa`, `beta = (1-mu)*kappa`, posterior mean is `(alpha+x)/(alpha+beta+n)`, and reliability is `n/(n+kappa)`.
- Dirichlet-Multinomial: for full composition `x_1..x_K`, fitted mean vector `pi`, and concentration `kappa`, `alpha_k = kappa*pi_k`; posterior mean is `(alpha_k+x_k)/(kappa+n)`. Posterior component variances and covariances are retained as audit outputs.
- Batting composition uses the five mutually exclusive AB outcomes single, double, triple, home run, and out. Posterior `AVG` is the sum of the four hit probabilities; posterior `SLG` is `p_1B + 2*p_2B + 3*p_3B + 4*p_HR`.
- Pitch composition uses fastball, breaking, offspeed, and `other_or_unclassified` cells. The residual is `pitch_count-fastball_count-breaking_count-offspeed_count`, must be nonnegative, and completes the simplex exactly.
- Gamma-Poisson components: hits and walks are independently shrunk against outs exposure with `lambda | x,E ~ Gamma(alpha+x, beta+E)`. Posterior WHIP is reconstructed as `3*(posterior_hits_per_out + posterior_walks_per_out)`; BFP and HBP are not substituted into the registered formula.
- Normal-Normal: fastball velocity uses float64 `n`, `sum`, and `sumsq`; a fitted population center, between-player variance, and pooled within-player variance determine the precision-weighted posterior mean and variance. No clipping, integer coercion, or hidden rounding is applied.

## 9. Prior-fitting population unit

The fitting unit is `LATEST_VALID_PLAYER_STATE_AT_OR_BEFORE_TRAINING_CUTOFF`, scoped exactly to each fold's training rows. The deduplication key is `familyId/playerId/game_date`. Exact same-day duplicates collapse deterministically; conflicting same-day states fail closed. Stable ordering is applied before taking the latest eligible day per player.

Annual statistics use the latest eligible annual state rather than summing repeated plate-appearance copies or adding states across seasons. Rolling statistics likewise use the latest eligible state. Sparse or zero-evidence players receive the fitted league prior with reliability zero; source failure and computation failure remain distinct states.

## 10. Fold-local authority

Five chronological validation folds were fitted independently. For every fold, the prior hyperparameters were learned only from that fold's training population; validation sufficient statistics were not used in fitting. Each fitted-fold artifact binds its fold membership checksum, cutoff, family definitions, source authorities, output contracts, and fitted parameters.

A separate final-development authority was fitted only after the five validation authorities. It is not a reuse or relabeling of a validation-fold fit.

## 11. Point-in-time authority

For every transformed development row, eligible annual and rolling source state satisfies `source.gameDate < target.gameDate`; same-date games are excluded. Tests cover ordering, repeated state copies, duplicate handling, latest-season selection, zero evidence, and addition of future-season rows.

Final OOT is sealed. Its immutable keys may be carried only to preserve one-to-one publication identity. The evaluator does not read OOT outcomes or targets, compute annual or rolling sufficient statistics, transform prior features, or expose payload. New sufficient-statistic payload columns remain `NULL`/`UNMATERIALIZED` with reason `FINAL_OOT_SEALED`.

## 12. Two-cell prior results

| Family | Prior mean | Prior strength | Fitted states | Zero/cold rows | Median effective N | Median reliability |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Batter last-100 whiff | 0.2520324962722776 | 47.4277460839332 | 985 | 1,307 zero-opportunity | 184 | 0.7950645638 |
| Pitcher last-250 whiff | 0.22942866508954318 | 53.283211806836746 | 1,348 | 6,862 zero-opportunity | 456 | 0.8953760686 |
| Pitcher GS/appearance | 0.21991523975528898 | 0.17773978252511324 | 1,134 | 73,824 cold rows | 25 | 0.9929405982 |

All three families recorded zero source failures and zero computation failures.

## 13. Pitch-composition prior results

- Fitted four-cell prior mean, in fastball/breaking/offspeed/other order: `[0.5517913916884929, 0.31132082889027574, 0.13189861474882186, 0.004989164672409472]`.
- Concentration: `8.782261881834607`.
- Fitted states: 1,348; zero-opportunity rows: 6,855.
- Median reliability: `0.9909627267`; median residual posterior: `0.0011423029251794318`.
- Maximum observed posterior simplex error: `4.440892098500626e-16`.
- Source failures and computation failures: zero.

The three published usage features come from one shared four-cell posterior. The residual category is never silently discarded.

## 14. Batting-composition prior results

- Fitted five-cell prior mean: `[0.1587859111293076, 0.047466498109720034, 0.0037949255739675287, 0.03345999047078626, 0.7564926747162186]`.
- Concentration: `210`.
- Fitted states: 847; cold rows: 52,749; zero-opportunity rows: 56.
- Posterior `AVG` median: `0.2448120202880839`.
- Posterior `SLG` median: `0.40110547925487`.
- Composition violations, source failures, and computation failures: zero.

`batter_avg` and `batter_slg` are derived from one shared posterior rather than fitted independently.

## 15. WHIP-component prior results

- Fitted league hits/out: `0.3108656191502638`.
- Fitted league walks/out: `0.11907935787622667`.
- Prior-equivalent outs: `7.369919560999729`.
- Fitted states: 1,134; cold rows: 73,824.
- Median posterior WHIP: `1.2897215780438196`; median reliability: `0.9628475952`.
- Source failures: zero; computation failures: 56, retained explicitly rather than silently imputed.

The registered hits-plus-walks per inning formulation is preserved exactly. BFP and HBP are explicitly absent from the estimator.

## 16. Velocity prior results

- Fitted population mean: `93.32983784785058`.
- Between-player variance: `43.256667270891825`.
- Pooled within-player variance: `3.5969744306672866`.
- Fitted states: 1,332; `n=0` rows: 7,131; `n=1` rows: 78.
- Raw range: `49` to `101.82964601769906`.
- Posterior range: `51.35476103385057` to `101.82808259974665`.
- Median reliability: `0.9998376158`; source and computation failures: zero.

Velocity sum and sum-of-squares are physically recorded as float64. The implementation performs no clipping and preserves their precision through fitting and transformation.

## 17. Output contracts

Every one of the ten target bindings exposes compact model-candidate outputs for posterior mean, `log1p(effective_n)`, posterior reliability, and posterior standard deviation. `pitcher_whip` additionally exposes hits-per-out and walks-per-out posterior means so its registered component construction remains inspectable.

The recommended ablation bundle for every binding is posterior mean plus `log1p(effective_n)` plus reliability. No output is automatically added to a model feature set, and no output is default-selected.

## 18. Model-candidate versus audit-only outputs

Model-candidate outputs are the compact posterior summaries named in section 17. Audit-only outputs include raw effective N, prior strength, posterior variance, history state, prior level, formula ID, family ID, posterior component alphas/variances/covariances, WHIP component shapes/rates/variances, and velocity sample mean/variance/centered sum of squares.

The UI labels these roles separately. Raw Wave 1 sufficient-statistic fields remain nonselectable, while the V2 derived outputs are advertised only through the executable preprocessing contract. This prevents accidental use of raw counts or high-dimensional audit payloads as default predictors.

## 19. Prior authority ID/checksum

| Object | Identity/checksum | Artifact checksum | Bytes |
| --- | --- | --- | ---: |
| V2 authority | `MLB_PLAYER_STATE_PRIOR_AUTHORITY_V2:sha256:9d9cfaf34f87be67f7d3ab2b8b024d83a6fc5e8abe0dde8de7be0866f1b8366e` | `bac2d184d88b0a7b2b395951d7b8b7d50f493ea967539f6c75110ef9e5534bec` | 10,728 |
| Definition | `ee80dae2687051bcc02786e7ad1ec7ccc50a8f2583ca7857a05db679b12b5045` | `f888bb4b6d3be988e3a52c57d80f48230a9c7e399c451623286ce854143a0044` | 90,410 |
| Fold contract | `cd72058500333f9fae8dcb11867dbc674a015f2c84585ccb3cd81bf62c437d31` | `0377749ebcc4c58c8ba6d4b2d8e8cfbe6fcfbc9bdf755d762f70b3f2b3e04a46` | 4,069 |
| Configuration | `e015e967f27908a1f70d26b4adbec25954f471f710a0a6b62230114d5ea1dd8a` | Bound in authority | — |
| Output contracts | `19cb923fafcfa98d946f9702b9e34f95bcee5516992d8e70818af3115431c102` | Bound in authority | — |
| Diagnostics | References the final fitted checksum | `5a97618d0be4b56e5cd32de22f5938fd5ed5af082ae22ad6a9becf7440f1f591` | 19,180 |
| Performance receipt | References the V2 authority and bundle | `3f5b64f2099fe8d28446345e93f5d9a102e2170f5253dc3f6ba5815aa6ee3a1a` | 8,278 |

Ten science manifests total 200,343 bytes. Every filename/content checksum was reverified after the deterministic replay.

## 20. Fitted fold IDs/checksums

| Fold | Train rows/games and range | Validation rows/games and range | Membership checksums (train/validation) | Fitted identity checksum / artifact checksum |
| --- | --- | --- | --- | --- |
| F1 | 182,072 / 2,406; 2023-03-30..2023-10-01 | 99,782 / 1,330; 2024-03-20..2024-07-06 | `5f7e50e71920b851b9654e021304c02e2023251f7a97b0257914c9a0ebc8cd35` / `0cf728f7f2b3aaf33cb62344edffb9426f98e36155378ed9ebccb6cd4f204d2f` | `0d35d54561459534e73edb7a63271e133b64782a6ed459838a37f19243fbf4c6` / `1bf9054416d3618042a23253f9d9dca16125135fa74b6971a315e1be4ac0c50f` |
| F2 | 281,854 / 3,736; through 2024-07-06 | 100,269 / 1,338; 2024-07-07..2025-04-15 | `2af8f8fa19853cf93f8d709bfa76987fc0a15207168badc782c339048b566cb7` / `7b2ccfa5f705868bb3ea0f5d901a6b7e505d7e0249b216b14d88da4e60bbd3de` | `6d0b453ec2cb1eaaa8044918ff3d13f3e883bf725407c16af92c17cc1b533c15` / `bcb41a0cc33a61953250a241088acbc228094f080275e4465b10874802eee66b` |
| F3 | 382,123 / 5,074; through 2025-04-15 | 99,968 / 1,327; 2025-04-16..2025-07-27 | `7174bc88118c89dbd01e3395d843b18bd783381c6999762d8e504955945be137` / `d8b7e61097369fc4977fe734641f3a796ba0f4d361ca63ec37e0ff4d11a8f517` | `13aa1f8c2e14db935250b84be5c297e15654d619627563503c4bb50323356d6c` / `e32f0003da5a9c6a7202590bfc618192900ec38e7ba795a9d770587caa92ff43` |
| F4 | 482,091 / 6,401; through 2025-07-27 | 100,304 / 1,327; 2025-07-28..2026-05-01 | `0148ee79963167bcd270fb33b5bb4edba388cafcd3c27faa431029d509e7fdd4` / `0767f73760b494a13a2ded893fec939948d7fcc11d6529141d35fcbac65e2f0d` | `5b5524d092cc7868fd5c32750a6d8555783a989c559adeeeb3bad9b36b69f3e4` / `019e819401d34133d03507b0409f1f371ae7a481e9d04f3442f6c00a17f7c106` |
| F5 | 582,395 / 7,728; through 2026-05-01 | 101,267 / 1,342; 2026-05-02..2026-08-13 | `f8855e33f8cb4a2b5639a1093af6a8be5cbb64321b45ef63ff04ec00968d69d8` / `a46bf49da732a0cb58806f29af734dda05a12c1348846bf3fdb0fea9624e3cf3` | `599ad47c6ec704d349f4c766260070d4d423b27ddee404cb33ebb98b1608f2af` / `abc475107302781f9eb2fad17ad6261eef43a7a180880426ed96e4581b7f4658` |

The exact fitted IDs are:

- `MLB_PLAYER_STATE_FITTED_PRIOR_V2:GOVERNED_CHRONOLOGICAL_FOLD_1:sha256:0d35d54561459534e73edb7a63271e133b64782a6ed459838a37f19243fbf4c6`
- `MLB_PLAYER_STATE_FITTED_PRIOR_V2:GOVERNED_CHRONOLOGICAL_FOLD_2:sha256:6d0b453ec2cb1eaaa8044918ff3d13f3e883bf725407c16af92c17cc1b533c15`
- `MLB_PLAYER_STATE_FITTED_PRIOR_V2:GOVERNED_CHRONOLOGICAL_FOLD_3:sha256:13aa1f8c2e14db935250b84be5c297e15654d619627563503c4bb50323356d6c`
- `MLB_PLAYER_STATE_FITTED_PRIOR_V2:GOVERNED_CHRONOLOGICAL_FOLD_4:sha256:5b5524d092cc7868fd5c32750a6d8555783a989c559adeeeb3bad9b36b69f3e4`
- `MLB_PLAYER_STATE_FITTED_PRIOR_V2:GOVERNED_CHRONOLOGICAL_FOLD_5:sha256:599ad47c6ec704d349f4c766260070d4d423b27ddee404cb33ebb98b1608f2af`

Fold checksums are respectively `aa1a507bda1b87428510a3446e6521a96ef7c2f88773fa5fe22092bcd521654f`, `c5926c125745dff449b1589089792a84362b816ebed9b06c28a4aa4758cb59ae`, `b30185d560a9ba9cdced51ddf6242d98ef8e118377de4782f580a248e44c2cdf`, `c4d0189593bdfb8d706d15682d70156d80123bfaa46de610b03a958f6c73c9e2`, and `04ab7c075864a49cbe533b6a69ed4478720f5299c2fe06b5e26e88512d5d9b3c`. Every fitted child manifest's `fitEvidence` records `validationFeatureValuesReadForFit=false`, `finalOotRowsRead=0`, and `targetColumnsRead=[]`.

## 21. Final-development fitted ID/checksum

- Final-development range: 2023-03-30 through 2026-08-13.
- Population: 683,662 rows and 9,070 games.
- Fold checksum: `2fa4d1fb42ec009e73f9c1aeb5cbc319c9f3c8ac564795256ba9cd3384a50c57`.
- Membership checksum: `252b0b8a9fc00cdcd4f6fcdb32e7bd57f9bbf140ccaefbf775acffe9903200cf`.
- Fitted ID: `MLB_PLAYER_STATE_FITTED_PRIOR_V2:FINAL_DEVELOPMENT:sha256:5ae0f9f560f83935e1f89440657ac4080afc33ac3318c3c2c8e50656a9eee526`.
- Fitted artifact checksum: `8bac5e6afbf625fdc4f1ff86acde36994a54ab9ad60afac45e1a3ab0b0857ede` (12,570 bytes).

Adding future-season rows leaves the exact fitted artifact unchanged, not merely numerically close, because excluded-row audit identity is derived from the fixed signed development population.

## 22. Treatment DRAFT before/after

| State | Specification ID | Manifest checksum | Content checksum |
| --- | --- | --- | --- |
| Before, V6 | `stage3-feature-treatment-spec-06154e576ec9474580540f6cca287a17` | `077619a904c4c5c68dc00c451545927c1763f07b835681e95aecc9d9e882a292` | `0b50bfebd1ada3c2b191c963d0d91f1e1c5b1e9968efd84e06903e60b9c474d3` |
| Current, V8 | `stage3-feature-treatment-spec-df0a0d98784d4de6b30c4dcc1a7aef8a` | `9e38ab918d216cd25d85c58248a589aeca2f12cad447b8469f9770aa47e4479b` | `d155cb7a14a0e12af792e525411bdc8d7cd66a6fc1b20d37aefb4541fd349251` |

V8 links outlier DRAFT `stage3-outlier-policy-e5db3b7e5f1743438a139b61fa9e7b0f` (`95481905e1ba51322997206e9acae4564293e53c408fb89541064413131d632b`) and imputation DRAFT `stage3-imputation-policy-d98230536b3a4779a97c1d7153bba8b3` (`34f1f28a8df45b500014a8176fab16bec6b006f35070395efae05eb74e3c0bb8`). All remain DRAFT and unadopted.

An intermediate V7 DRAFT was append-only published before future-season source-identity hardening: `stage3-feature-treatment-spec-7e2dbe9d1344477aa49d8d98e5e29828`, manifest `0fff0db9314aa261c4b82a3e91cde2b3adf6c9229557a41b2c30ded0eabed5e4`, content `496f71ce494fa30224f702288008d2e45487d9806d7b5f8821eb69426c9ebc02`. It is preserved as immutable history rather than deleted or hidden; V8 is the single current science-binding DRAFT. This operational audit note is not a feature blocker.

## 23. Binding-ready count before/after

- Before Wave 2: 10 fields had validated bindings but still required a Wave 2 estimator engine.
- After Wave 2: 0 fields remain in `BINDING_READY_REQUIRES_WAVE2_ENGINE`.
- Reconciliation: all exact components were authenticated, all required estimators were implemented and fitted under training-only authority, and all ten fields moved to `READY_GOVERNED_PRIOR_V2`.

No feature was called executable merely because component sufficient statistics existed.

## 24. Executable count before/after

- Before: 11 prior features executable under the inherited V1 authority; 0 under V2.
- After: 11 inherited V1 executable features plus 10 V2 executable features, for 21 total executable prior features.
- The ten V2 raw source fields remain nonselectable; execution occurs through their governed posterior output contracts.

## 25. Retired count

Exactly three fields remain `RETIRED_NONSELECTABLE_BY_SCIENTIFIC_DECISION`:

- `pitcher_era9`
- `batter_obp`
- `batter_last100_contact_rate`

Their definitions, metadata, and audit evidence are preserved. None is placed in a feature set, and none is counted as an unresolved evidence blocker.

## 26. Remaining blockers

Missing-evidence prior blockers after Wave 2: zero.

Sixteen adoption blockers remain outside the ten Wave 2 prior bindings:

- Two semantic authorities: `doubleheader_game_number` still requires schedule PIT timestamps/invariant evidence, and `holiday_name` still requires a registered effective-dated calendar.
- Fourteen rivalry fields retain proposed mappings that have not received scientific approval.

The compiler presents three blocker reason classes, while the exact execution accounting is 16 blocked fields. These blockers keep policy adoption closed but do not make a fitted Wave 2 prior incomplete.

## 27. canAdopt state

`canAdopt=false` for the current V8 treatment DRAFT. The UI and API both fail closed and display the remaining semantic and rivalry blockers. Wave 2 does not attempt to resolve them, bypass them, or reinterpret a DRAFT as adopted policy.

## 28. Diagnostics

The diagnostics artifact records fitted population size, cold/zero-evidence states, posterior ranges, effective sample size, reliability, posterior uncertainty, source failures, computation failures, composition constraints, and exact target-column access.

Key integrity outcomes:

- `targetColumnsRead=[]` for every family.
- All OOT read counters are zero.
- Pitch and batting posterior compositions satisfy their full simplexes; pitch maximum floating-point error is `4.440892098500626e-16`.
- Velocity has no clipping and preserves float64 source moments.
- Source failures are zero for every family; the 56 WHIP computation failures are explicitly surfaced.
- Sparse/zero evidence is represented as league-prior output with reliability zero, not confused with source or computation failure.

## 29. Performance

| Phase | Duration |
| --- | ---: |
| Authentication | 5,815.711 ms |
| Companion scan | 683.983 ms |
| Gold projection | 490.903 ms |
| Fold fits F1..F5 | 3,149.770 / 4,722.423 / 6,652.753 / 7,734.165 / 9,867.814 ms |
| Final-development fit | 10,892.401 ms |
| Full-development transform | 7,369.176 ms |
| Diagnostics | 13,249.735 ms |

Final family fit/transform milliseconds were: batter whiff `957.162/711.074`, batting composition `1318.385/1933.917`, GS `813.689/736.856`, velocity `951.365/759.846`, pitch composition `1149.407/1519.497`, pitcher whiff `1020.371/743.909`, and WHIP `852.713/832.129`.

The 565,388,606-byte input frame produced 125,793,808 full-development derived cells. Sampled RSS rose from 196,206,592 to 1,354,952,704 bytes. Computation is vectorized/grouped and does not iterate Python once per plate-appearance row.

## 30. Backend tests

The final backend suite completed with `143 passed in 72.61s`. It covers estimator numerics, leakage and fold locality, same-day duplicate/conflict behavior, ordering, latest-season state selection, future-season exact fitted-artifact identity, sparse evidence, missing companion failure, manifest and physical-partition tampering, physical dtypes, composition residuals, OOT sealing, artifact publication, treatment integration, and inherited-authority immutability checks.

Earlier sandboxed attempts showed 88 passes plus 55 setup errors caused by Windows ACL denial in `C:\Users\james\AppData\Local\Temp\pytest-of-james`; these were temporary-directory setup failures, not assertion failures. The authoritative rerun outside that restricted temp context is the 143-pass result above.

Full-workflow immutability is established by the live evaluator's before/after hashes and normalized replay. The focused unit test snapshots inherited assets specifically around companion authentication; this narrower test scope is stated explicitly rather than overstated.

## 31. Frontend tests

The two focused frontend suites completed with 33 passes total:

- Feature/split frontend: 15 passed.
- Treatment-studio frontend: 18 passed.

They prove fail-closed readiness, exact V1/V2/binding-ready/retired/evidence-blocked counts, nonselection of raw prior fields, compact candidate/audit output separation, long-identity wrapping, missing-studio behavior, no generic-median treatment for bound priors, no blanket-IQR treatment, and disabled adoption while blockers remain.

## 32. TypeScript/build

`npm run build:modeling` passed. Vite transformed 2,336 modules and completed the production build in 24.25 seconds. Only pre-existing chunk-size/browser-data informational warnings were emitted. Relevant Python modules also passed `py_compile`, and `git diff --check` passed with only line-ending conversion notices.

## 33. Browser acceptance

The final V2 authority `9d9cfaf34f87be67f7d3ab2b8b024d83a6fc5e8abe0dde8de7be0866f1b8366e` and V8 DRAFT were loaded through an isolated local backend/frontend pair. Missing, Outliers, and Feature Engineering were inspected at exact 1920x1080 and 1024x768 viewports.

- At 1920x1080, document `clientWidth` and `scrollWidth` were both 1905; no horizontal overflow occurred.
- At 1024x768, document `clientWidth` and `scrollWidth` were both 1009; no horizontal overflow occurred.
- Treatment cards remained within the viewport (`left=111`, `right=980` at 1024); the feature card remained within it (`left=94`, `right=997`).
- Feature Engineering displayed 11 V1 executable, 10 V2 executable, 0 binding-ready, 3 retired, and 0 evidence-blocked; model activity stayed zero, OOT remained locked, registration stayed disabled, and candidate versus audit outputs were distinct.
- Missing displayed exact V2 families, effective N/reliability, retired fields, blockers, and disabled adoption without offering generic-median treatment for governed priors.
- Outliers displayed prior shrinkage, did not apply blanket IQR, and confirmed no velocity clipping.

The temporary 5275/8102 services were stopped, the viewport override was reset, and the acceptance tab was closed. The user's service on port 5274 was not interrupted.

## 34. Gold/companion/artifact checksums before/after

Before/after live-evaluator hashes were byte-identical for all inherited authorities:

| Asset | SHA-256 before and after |
| --- | --- |
| Gold manifest | `67de02ce19738b29953341151640fb69244b764b0e532b687ab6bacedbb3f758` |
| Wave 1 companion | `98673b65dc5eab61e39b16d1313c27bbb2cf908c525f80db579cb07a5cfdab33` |
| V1 pointer | `b8e352eda90f07c46a05f58f2de0a49c4c7484e6cbfdccc1ba53a14fd0b2c3c2` |
| V1 referenced object | `afe4ebdae76ef5c9429637c0b01007d464ca3b921092e92fa6486c3e3e2a139b` |
| Nested original V1 authority | `a363331fc47083bf5aaac07c437f2998ea21650b78538d2a69e258851812ff43` |
| Historical executable manifest | `58ddf83092c2e91fde4c61c35f16c8cc5a3702d3a4da8f9f9164f2eab5641f6b` |
| Historical model | `d5172c60e335a8c5d21e9d0e5bf0f0e7b65a7f271e8e8429ba7796db9ff86630` |
| Historical OOF | `65cb26ece9f4434ca5fd3babce2ea07e601447b8d8b7075ad8c224ca2291f21a` |
| Historical preprocessor | `c22793446d9a8b09ece87f0320132bc8b1d44ed2349c579fc4ea84c5460f63eb` |
| Historical fixture | `a0b657f2298eef3ac71f1f5dab4accd5396944354251d9ab94645f8409e03259` |
| Historical receipt | `7fe5d84a702bbf2465990a4b1d8650fbab73d25798413a32373cf1974ab7456d` |

The normalized second Wave 2 replay returned exit code 0, `scienceObjectWrites=0`, and `currentPointerChanged=false`. All ten V2 science objects were rehashed successfully.

## 35. OOT access

Final OOT remained closed throughout authentication, fold fitting, final-development fitting, transformation, diagnostics, DRAFT compilation, testing, and UI acceptance. Outcome reads, target reads, annual-statistic computations, rolling-statistic computations, prior transformations, and payload exposures were all zero. OOT rows retain only immutable publication identity and explicit `FINAL_OOT_SEALED`/unmaterialized state.

## 36. Model activity

All Wave 2/project-scoped prohibited activity counters are zero: predictive-model fits, tuning, scoring, calibration, challenger-lift calculations, model-feature-set registrations, policy adoptions, promotions, OOT opens, source mutations, and historical-artifact mutations. Wave 2 publishes preprocessing science and a DRAFT only. Database run records belonging to other projects are outside this accounting.

## 37. Files changed

Implementation and evaluation:

- `scripts/evaluate_mlb_player_prior_authority_v2.py`
- `server/sports_current_statcast/stage3_player_prior_artifact_store_v2.py`
- `server/sports_current_statcast/stage3_player_prior_authority_v2.py`
- `server/sports_current_statcast/stage3_player_prior_resolution_v2.py`
- `server/sports_current_statcast/stage3_prior_estimators_v2.py`
- `server/sports_current_statcast/stage3_feature_engineering.py`
- `server/sports_current_statcast/stage3_feature_treatment_spec.py`
- `server/sports_current_statcast/stage3_treatments.py`

Frontend:

- `src/sports/cockpit/ProjectBoundFeatureEngineering.tsx`
- `src/sports/cockpit/ProjectBoundMissingStudio.tsx`
- `src/sports/cockpit/ProjectBoundOutlierStudio.tsx`
- `src/sports/cockpit/TreatmentStudioShell.tsx`
- `src/sports/cockpit/projectFeatureSplitApi.ts`
- `src/sports/cockpit/projectTreatmentApi.ts`

Tests and report:

- `tests/sports_stage3_player_prior_authority_v2_test.py`
- `tests/sports_stage3_prior_estimators_v2_test.py`
- `tests/sports_stage3_treatments_test.py`
- `tests/sportsStage3FeatureSplitFrontend.test.mjs`
- `tests/sportsStage3TreatmentStudiosFrontend.test.mjs`
- `docs/MLB_PLAYER_STATE_PRIOR_WAVE2_IMPLEMENTATION_REPORT.md`

## 38. Commits

- `6e26c19` — `feat(stage3): add governed Wave 2 empirical-Bayes engine`
- `3f86530` — `feat(stage3): integrate Wave 2 prior authority`
- `f88f011` — `test(stage3): prove Wave 2 leakage and numeric integrity`
- Documentation commit containing this report — exact final SHA is stated in the delivery response.

The commits are local, logically separated, and descend from the verified Wave 1 authority head.

## 39. Pushes

No branch, commit, tag, artifact, database, or report was pushed to a remote. All work remains local in `codex/mlb-player-prior-wave2`. The live database changes are limited to append-only DRAFT publication/audit records; there was no adoption.

The final normalized V8 replay made no new database rows: project specification versions 8→8 and specification events 8→8; database-wide policy versions 23→23 and policy events 40→40. The corresponding project-scoped policy counts were 16→16 and 32→32.

## 40. Remaining James decisions

No James decision is required to accept the Wave 2 implementation as ready. The exact verdict is `MLB_PLAYER_STATE_PRIOR_WAVE2_READY`.

Future, separate decisions remain before treatment adoption: supply the doubleheader schedule PIT authority, register an effective-dated holiday calendar, approve or reject the fourteen rivalry mappings, and then explicitly review/adopt a treatment policy. James may also choose a future schema revision that separates inherited source limitations from parent-authority limitations; the current provenance-scoped wording is accurate and does not alter any immutable identity.

Final four-way status reconciliation:

| Status | Count | Outcome |
| --- | ---: | --- |
| Fully executable prior features | 21 | 11 inherited V1 plus 10 new V2 |
| Validated binding awaiting Wave 2 estimator | 0 | All ten implemented and fitted |
| Scientifically retired | 3 | Preserved, nonselectable, not blockers |
| Blocked by missing prior evidence | 0 | Cleared without opening OOT |
