# ASP Model Studio Phase 2–3 MLB Baseline Report

Status date: 2026-08-16
Approved starting branch: `main`
Approved starting commit: `5ea918f2a5e8e9285214b6883e1ed247ae608d92`
Exchange contract: `SPORTS_DATASET_MANIFEST_V1`
Dataset: `asp.mlb.open-data.fd1`

Milestone A: **PASSED AND REGISTERED**

Milestone B: **BLOCKED_IDENTITY_BRIDGE_REQUIRED**

Authenticated protected-page inspection: **DEFERRED — explicitly waived for the Milestone A checkpoint commit only**

This report separates completed package, persistence, and automated verification from the deferred authenticated browser inspection. The waiver does not authorize an authentication bypass and does not apply to Milestone B. No unavailable or blocked result is represented as complete.

## Executive Result

The approved MLB FD1 exchange passed an independent, package-only integrity audit. The audit reproduced both governing hashes, validated the exact 335-file inventory, checked all 329 Parquet files byte-for-byte and by footer metadata, and reconciled all 3,738,096 rows and the three governed populations without error.

Milestone A status: **PASSED AND REGISTERED**. The approved exchange is registered metadata-only in the live target-local database, and the governed MLB project and exact folds persist. The owner explicitly waived authenticated protected-page browser acceptance for the Milestone A checkpoint commit only. Manual inspection remains deferred.

Milestone B, First Plate-Appearance Model, is **BLOCKED_IDENTITY_BRIDGE_REQUIRED before feature materialization or model fitting**. Plate-appearance batter and pitcher identifiers are Retrosheet-namespaced strings, while `player_prior` is keyed by unrelated canonical UUIDs. The immutable package contains no physical, manifest-bound bridge between those namespaces. Exact Y−1 joins produced zero matches in every modeling season. Training through an inferred or external crosswalk would violate the package-only boundary and the explicit stop condition that Y−1 prior logic must be proven. FD1 validated exactly as published and did not fail; the blocker is a missing row-level interoperability companion required by Model Studio.

No provider or external-network call was made. HTTP traffic was limited to target-local loopback health and browser checks. No exchange file was written or modified. No derived feature view, prediction file, model, calibration artifact, bootstrap result, or model registry entry was created.

- Candidate models trained: **0**
- Model registry entries created: **0**
- Performance results: **none**
- Calibration results: **none**
- Bootstrap results: **none**

## Exchange Package Registration

The approved package has the following verified identity:

- Manifest ID: `sports-dataset-manifest:sha256:1b58d5d1def2c9b79041472974e93bc9a0f4c5317210099c1b1ee531fbfe8b49`
- Semantic manifest SHA-256: `1b58d5d1def2c9b79041472974e93bc9a0f4c5317210099c1b1ee531fbfe8b49`
- Partition authority SHA-256: `8dec143b06622af068665b9fd1ad419a0353e76f0e0083b4c3459b8fce3cb437`
- Dataset version ID: `asp.mlb.open-data.fd1:sha256:1b58d5d1def2c9b79041472974e93bc9a0f4c5317210099c1b1ee531fbfe8b49`
- Package ID: `sha256-1b58d5d1def2c9b79041472974e93bc9a0f4c5317210099c1b1ee531fbfe8b49`
- Publisher: AI Sports Predictor
- Sport and league: Baseball, MLB
- Evidence cutoff: 2026-08-15
- Published at: 2026-08-16T05:21:08.171241Z

The application must map this identity through administrator-controlled `ASP_MODEL_EXCHANGE_ROOT` configuration and expose only logical `asp-model-exchange://...` URIs. The physical package path must not be persisted in browser-facing records or rendered in ordinary pages.

Application registration status: **VALID**. The supported target-local CLI registered `sports-dataset-1b58d5d1def2c9b7` with the neutral registering identity `target-local-administrator`. A second complete validation returned the same registration and project IDs with 329 cache hits, zero misses, and database counts unchanged at one registration and one project, proving live idempotent reuse.

The earlier `6c6cde` metadata revision is not the audited package. Focused automated testing confirms that the consumer rejects the superseded revision fail closed.

## Manifest and Partition Validation

The manifest was parsed as strict UTF-8 JSON with duplicate-key and non-finite-number rejection. Semantic identity was independently reproduced by deep-copying the manifest, removing exactly `manifest_id`, `manifest_sha256`, `dataset_version_id`, `package_id`, and `published_at`, then serializing compact canonical JSON with lexicographically sorted object keys and preserved Unicode.

Partition authority was independently reproduced from the all-field partition objects sorted by `package_relative_uri` and serialized using the same canonical JSON rules.

The package inventory is exact:

- 335 total files
- 329 Parquet files
- Six metadata files: `sports-dataset-manifest.json`, `schema-registry.json`, `source-rights.json`, `attribution.md`, `README.md`, and `validation-report.json`
- 3,738,096 total rows
- 337,421,353 Parquet bytes
- Ten logical data families
- 33 physical schema variants

Every Parquet entry passed package-relative path safety, root-containment resolution, reparse/symlink inspection, detectable hard-link inspection, byte-count validation, SHA-256 validation, footer row-count validation, ordered physical-schema comparison, and physical-schema-fingerprint reproduction. No undeclared or missing file was found.

The README-bound validation report SHA-256 is `48854d42ab97ac174877f05ea9a84e22ebd54ec3ead2af34e444f562ff09c5cf`.

Family totals independently reconciled as follows:

| Family | Files | Rows | Parquet bytes |
|---|---:|---:|---:|
| bullpen_usage | 36 | 80,314 | 9,902,702 |
| pitch_sequence | 36 | 943,682 | 80,347,024 |
| plate_appearance | 36 | 913,349 | 79,421,951 |
| play_transition | 36 | 949,217 | 88,260,346 |
| player_game_batting | 36 | 356,498 | 30,584,501 |
| player_game_fielding | 36 | 332,159 | 27,997,674 |
| player_game_pitching | 36 | 104,610 | 10,736,025 |
| player_prior | 5 | 21,823 | 2,512,357 |
| starter_usage | 36 | 24,296 | 4,558,900 |
| weather | 36 | 12,148 | 3,099,873 |

Season totals independently reconciled as follows:

| Season | Files | Rows | Parquet bytes |
|---|---:|---:|---:|
| 2021 | 64 | 748,340 | 67,816,145 |
| 2022 | 64 | 743,193 | 66,913,662 |
| 2023 | 73 | 751,208 | 68,021,023 |
| 2024 | 64 | 746,538 | 67,201,261 |
| 2025 | 64 | 748,817 | 67,469,262 |

Independent validation errors: **0**.

## Source Rights and Limitations

The package permits only:

- local/private model development;
- internal derived analytics; and
- read-only registration.

It prohibits public bulk download, public raw redistribution, raw data resale, and unreviewed commercial redistribution. The application must not offer a public raw-data download.

The six source-right controls are:

- `RETROSHEET`: used for primary event and governance evidence; required attribution applies.
- `CHADWICK_PERSONS_REGISTER`: used for identity evidence; ODC Attribution obligations apply.
- `SABR_LAHMAN_MODERN_MLB`: used for chronological player priors and identity support; CC BY-SA 3.0 obligations apply.
- `NOAA_NCEI_LCDV2_ZERO_USE`: zero use and no download in FD1.
- `OPEN_METEO_FREE_HOSTED_ZERO_USE`: zero use and no request in FD1.
- `LAHMAN_SEAMHEADS_NEGRO_LEAGUES_EXCLUDED`: excluded and not used; separate upstream rights remain unresolved.

The evidence does not include a multi-season Statcast corpus, pitch velocity, spin, movement, location, launch metrics, barrel or hard-hit measures, xwOBA, tracking defense, runner speed, historical odds, or CLV. Actual historical lineups, starters, reliever use, play state, and untimestamped actual weather carry timing risk and are not strict pregame predictors. Retrospective validation is not prospective proof.

FD1's manifest and data passed their frozen contract. The manifest reports 100% exact primary player-reference coverage and binds identity-coverage and mapping-lineage evidence, while intentionally exporting neither the source PostgreSQL database nor the full identity staging table. The package rows therefore do not carry the row-level canonical join required by this consumer: all primary plate-appearance rows have `canonical_identity_resolved=false`, and the referenced identity evidence bytes are absent from the package. This is not an FD1 data-integrity failure. The missing interoperability artifact is a compact, source-version-bound active-player identity bridge. The UI must distinguish **manifest-reported identity coverage** from **package-bound prior-join authority** and must not represent the latter as complete.

## Dataset Registration

The metadata-only registry should persist the exact manifest, partitions, schema variants, populations, folds, rights, and limitations. It must not import the 3.7 million data rows. Registration must be unique by manifest identity and idempotent.

Verified warehouse facts available for display are:

- seasons 2021–2025;
- 12,148 games;
- 913,349 plate appearances;
- 949,217 transitions;
- 24,296 starter-duration targets;
- 80,314 bullpen appearances;
- 21,823 player-prior rows;
- 329 partitions; and
- package validation status `VALID`.

Migration `0029_sports_dataset_registry.sql` is applied in the live target-local database. Persistence contains one registration, 329 partition metadata records, ten schemas, three populations, two folds, six rights controls, twelve limitations, and one governed project. All 329 partition references are distinct `asp-model-exchange://` logical URIs, zero contain a Windows or `file:` path, and no package data row was imported into SQLite.

## Project and Forecast Contract

The governed project to create or idempotently reuse is `MLB Gen-2 Free-Data Baseline` with:

- Sport: Baseball
- League: MLB
- Development period: 2023–2025
- Prior history: 2021–2022
- Forecast lifecycle: Pregame — Final
- Primary target: Plate-Appearance Outcome
- Secondary targets: Joint Score Distribution, Home Win Probability, Run Differential, Total Runs, and Player Outcome Distribution
- Baseline population: Strict Deployable
- Upper-bound research population: Enhanced Research
- Research purpose: Establish the first leakage-safe player-event baseline for the MLB Gen-2 forecasting system.

The target-local registry created `sports-project-mlb-fd1-1b58d5d1def2` exactly once and bound it to registration `sports-dataset-1b58d5d1def2c9b7`. Its governed configuration, twelve workflow evidence states, two exact folds, and structured `MLB_PA_FEATURE_VIEW_V1` blocker persist in SQLite. Browser reload evidence remains unavailable without an authenticated owner session; no reload success is claimed. The identity stage is `BLOCKED`, not complete.

## Population Definitions

Independent evaluation of the frozen population predicates produced:

| Population | Rows | Governing use |
|---|---:|---|
| strict_deployable | 1,460,755 | Primary-season targets or safely laggable rows after timing-risk exclusions; all feature use still requires temporal proof. |
| enhanced_research | 785,808 | Primary-season actual lineup, starter, reliever, play-state, and untimestamped-weather evidence isolated from strict deployment. |
| prior_only | 1,491,533 | All 2021–2022 history rows, retained for prior construction and prohibited as primary 2023–2025 target rows. |

The counts sum exactly to 3,738,096. Evaluation precedence is `prior_only`, then `enhanced_research`, then `strict_deployable`.

## Temporal Folds

The two frozen retrospective rolling-origin folds are:

| Fold | Development | Validation | Training PA rows | Validation PA rows |
|---|---|---|---:|---:|
| `train-2023-validate-2024` | 2023-03-30 through 2023-10-01 | 2024-03-20 through 2024-09-30 | 184,104 | 182,449 |
| `train-through-2024-validate-2025` | 2023-03-30 through 2024-09-30 | 2025-03-18 through 2025-09-28 | 366,553 | 182,926 |

The target rows contain 2,430 games in 2023, 2,429 in 2024, and 2,430 in 2025. Plate-appearance IDs are unique within each season. The 2025 season is the second frozen retrospective rolling-origin validation season, not an untouched holdout.

Same-date game grouping and the absence of future dates still require automated fold tests in the application implementation.

## Feature Eligibility Audit

The exact target field is `outcome`. `game_id`, `game_date`, `plate_appearance_id`, `batter_id`, and `pitcher_id` may be used only for grouping, temporal control, identity linkage, or artifact lineage.

The immutable probability-vector order is:

1. `STRIKEOUT`
2. `WALK_HBP_CI`
3. `HOME_RUN`
4. `SINGLE`
5. `DOUBLE`
6. `TRIPLE`
7. `BIP_OUT`
8. `OTHER_REACH`

The plate-appearance schema contains `inning`, `top_bottom`, `outs_before`, `base_mask_before`, `visiting_score_before`, and `home_score_before`, but every one is explicitly classified `RETROSPECTIVE_ACTUAL_NOT_PREGAME_SAFE`. They are therefore excluded from the strict baseline. No batter-side or pitcher-hand field exists in either `plate_appearance` or `player_prior`.

Target and result exclusions include `terminal_play_id`, `terminal_play_number`, `source_terminal_token`, `outcome`, `outs_after`, `base_mask_after`, and `runs_scored`. Provenance, checksum, source-version, partition, manifest, game, and player identifiers are excluded as predictors. All 549,479 primary target rows have `strict_same_game_pregame_eligible=false` and `target_only_not_pregame_feature=true`.

Potential Y−1 prior fields exist in `player_prior`:

- Join and guard fields: `canonical_player_id`, `season`, `eligible_from_season`, `domain`, `official_date`, `same_season_predictor_eligible`, `timing_classification`.
- Batter metrics: `2B`, `3B`, `AB`, `BB`, `CS`, `G`, `GIDP`, `H`, `HBP`, `HR`, `IBB`, `R`, `RBI`, `SB`, `SF`, `SH`, `SO`.
- Pitcher metrics: `BB`, `BFP`, `BK`, `CG`, `ER`, `G`, `GF`, `GIDP`, `GS`, `H`, `HBP`, `HR`, `IBB`, `IPouts`, `L`, `R`, `SF`, `SH`, `SHO`, `SO`, `SV`, `W`, `WP`.

The JSON metrics are valid and finite. Batter and pitcher domains have one row per canonical player, season, and domain. `same_season_predictor_eligible` is false throughout. If a valid identity bridge becomes available, only exposure-aware rates and training-fold-derived imputations should be used, with explicit missing-batter-prior and missing-pitcher-prior indicators.

The blocking join audit used exact membership, not fuzzy names or inferred identifiers. It built season/domain sets from `player_prior.canonical_player_id` where `eligible_from_season` equals the target season, then scanned every 2023–2025 plate-appearance partition and tested `batter_id` against the BATTING set and `pitcher_id` against the PITCHING set.

| Target season | Eligible batter priors | Eligible pitcher priors | Batter joins | Pitcher joins | Both joins |
|---|---:|---:|---:|---:|---:|
| 2023 | 1,495 | 871 | 0 / 184,104 | 0 / 184,104 | 0 |
| 2024 | 1,457 | 863 | 0 / 182,449 | 0 / 182,449 | 0 |
| 2025 | 1,454 | 855 | 0 / 182,926 | 0 / 182,926 | 0 |

The mismatch is structural. Plate appearances use values such as `retrosheet:player:matej003` in namespace `RETROSHEET`; priors use UUID `canonical_player_id` values, retain a separate `lahman_player_id`, and have a physically null `player_id` field.

## Feature View

`MLB_PA_FEATURE_VIEW_V1` was **not materialized**. No derived Parquet or other experiment-local data was written.

The frozen FD1 package inventory contains no row-level identity bridge. The manifest references an `active_identity_evidence` logical artifact outside the package, but a digest and aggregate evidence claim cannot reconstruct row-level mappings. A separately immutable `SPORTS_IDENTITY_BRIDGE_V1` companion bound to the FD1 manifest can supply that consumer authority without altering FD1. Accessing an unregistered source to fill the gap would violate the authorized input boundary.

Once unblocked, a deterministic view would join each target season only to a prior record whose `eligible_from_season` equals that target season, derive batter and pitcher rate features from fixed metric allowlists, fit all missing-value treatment and scaling on the training segment only, preserve IDs solely for grouping and lineage, and write outputs only beneath ignored target-local runtime storage. That plan remains unexecuted.

## Candidate Models

Candidate models trained: **0**. The feature contract could not pass its identity gate.

| Candidate | Intended definition | Status |
|---|---|---|
| 0 | Training-period global class frequency | Not run; insufficient alone to satisfy Milestone B |
| 1 | Eligible batter Y−1 priors | BLOCKED by zero authoritative joins |
| 2 | Eligible pitcher Y−1 priors | BLOCKED by zero authoritative joins |
| 3 | Combined multinomial logistic baseline | BLOCKED by zero authoritative joins and absence of safe handedness/context fields |

Running Candidate 0 alone would not establish the requested player-event baseline and must not be presented as completion.

## Hyperparameter Selection

No chronological internal 2023 split was created and no regularization value was selected. The bounded `C` grid was not evaluated. No preprocessing was fit, globally or otherwise, and 2025 labels were not touched for tuning.

## 2024 Evaluation

No model predictions or model metrics were produced for 2024. The frozen target population contains 182,449 rows with this observed class distribution:

| Class | Rows |
|---|---:|
| STRIKEOUT | 41,197 |
| WALK_HBP_CI | 17,049 |
| HOME_RUN | 5,453 |
| SINGLE | 25,902 |
| DOUBLE | 7,771 |
| TRIPLE | 697 |
| BIP_OUT | 82,566 |
| OTHER_REACH | 1,814 |

These are descriptive target counts, not evaluation results.

## 2025 Evaluation

No model predictions or model metrics were produced for 2025. The frozen target population contains 182,926 rows with this observed class distribution:

| Class | Rows |
|---|---:|
| STRIKEOUT | 40,645 |
| WALK_HBP_CI | 17,395 |
| HOME_RUN | 5,650 |
| SINGLE | 26,115 |
| DOUBLE | 7,745 |
| TRIPLE | 628 |
| BIP_OUT | 83,020 |
| OTHER_REACH | 1,728 |

These are descriptive target counts, not evaluation results.

## Calibration

Calibration research was not run. No raw reliability plots, top-label calibration curve, classwise calibration errors, probability histograms, temperature parameter, or calibrated metrics exist. There is no basis to claim calibration improved or worsened performance.

## Bootstrap Comparison

The deterministic game-cluster bootstrap was not run. There are no log-loss or multiclass-Brier difference intervals. Plate appearances were not independently bootstrapped.

## Model Decision

Final decision for Milestone B: **BLOCKED_IDENTITY_BRIDGE_REQUIRED**.

The decision is caused by a missing package-bound identity authority, not by model performance. No model registry entry exists. No performance, calibration, or bootstrap decision exists. `RESEARCH_CHALLENGER`, `RESEARCH_BASELINE`, and `REJECTED_BASELINE` are therefore inapplicable. No model may be described as operational, champion, production, approved for betting, or superior to a sportsbook.

## Artifact Lineage

No model-run identity or feature-contract SHA was issued, and none of the required runtime artifacts was created. In particular, there is no preprocessing object, model object, class-order artifact, 2024 or 2025 prediction Parquet, metrics file, calibration file, confusion matrix, bootstrap evidence, lineage record, or model card.

No runtime data, model artifact, Parquet file, database, cache, screenshot, or credential has been committed by this audit.

## Model Graph

The evidence-supported graph currently stops at the identity join:

1. MLB FD1 Dataset Manifest — independently validated and registered `VALID`.
2. Y−1 Batter and Pitcher Prior Join — **BLOCKED**, zero exact joins and no package-bound bridge.
3. `MLB_PA_FEATURE_VIEW_V1` — not created.
4. Multinomial PA Baseline — not trained.
5. Optional Temperature Calibration — not run.
6. Retrospective Evaluation Evidence — not created.

Dynamic player state, lineup model, starter-duration model, bullpen-usage model, base-out simulator, residual model, and forecast bundle remain not configured.

## Runtime and Storage

The package was read in place and remained immutable. The audit used bounded column projections and Parquet footer metadata where possible. It did not copy exchange Parquet into Model Studio storage and did not connect to a provider or the internet.

The target-local validation cache contains 329 root-and-file-bound entries and was reused with 329 hits and zero misses. Registry records and live migration state were verified read-only after two idempotent registrations. Query authorization, cancellation ownership, row limits, memory limits, optional-field union semantics, and audit behavior passed focused tests; the live query-audit table remains empty because no authenticated analytical browser request was made. No derived feature storage or model artifact storage was created. Any future derived data must remain below ignored `.runtime/asp-model-studio/sports-modeling/` storage and be bound to the source manifest, feature-contract SHA, folds, source partitions, code revision, row count, schema, and file checksum.

Audit boundary facts:

- Provider calls: 0
- External network calls: 0 (target-local loopback checks only)
- Exchange writes: 0
- Exchange files copied into Model Studio: 0
- Model artifacts created: 0
- AI Sports Predictor repository accessed: no
- Financial ATLAS accessed: no
- Pushes: none

## Tests

Completed independent read-only audit checks:

- canonical semantic digest reproduction;
- all-field partition authority reproduction;
- exact inventory;
- safe relative paths and root containment;
- file bytes and SHA-256;
- footer row counts;
- ordered physical schemas and fingerprints;
- family and season reconciliation;
- population-predicate reconciliation;
- target class order and fold counts; and
- exact Y−1 identity-join audit.

Completed verification:

- focused sports dataset consumer, registry, access, and feature-authority suite: 33 of 33 passed;
- sports-product frontend suite: 12 of 12 passed;
- persistence migration atomicity suite: 14 of 14 passed, including concurrent startup application;
- authentication containment suite: 15 of 15 passed;
- storage-isolation suite: 24 of 24 passed;
- TypeScript project check: passed;
- production modeling build: passed, 1,661 modules transformed;
- focused Python compilation: passed; and
- `git diff --check`: passed.

A pre-stage allowlist, secret, runtime, and generated-artifact audit passed. The owner expressly waived authenticated protected-page inspection for the Milestone A checkpoint commit only; final staging and commit status are reported in the handoff.

## Browser QA

The live frontend and backend were restarted through `scripts/start-asp-model-studio.ps1 -Start`; health, product identity, production assets, and all ten sports API routes are available on the required ports. An unauthenticated protected-route smoke at 1440×900, 1024×768, and 390×844 correctly redirected `/data-warehouse` to the ASP Model Studio sign-in page. At all three viewports the document width equaled the viewport width, typography remained readable, and the browser console contained no errors. Two focused screenshots were captured beneath ignored runtime storage.

Authenticated inspection of Studio Home, Data Warehouse, project overview, Evidence and Manifest, Temporal Validation, Model Laboratory, Evaluation & Calibration, Model Graph, Registry & Deployment, and the mobile project view is **not complete**. The owner explicitly deferred manual protected-page review and waived it as an acceptance gate for the Milestone A checkpoint commit only. The repository provides no supported reversible QA identity: public registration, bootstrap, and the development-user header are disabled; password-reset routes are non-provisioning stubs; temporary users cannot be deleted; and production-auth E2E tests require a real credential. Authentication was not weakened, no session was injected, and no credential was created or changed.

The accepted UI must show registered counts and charts from real package metadata, label the identity join blocker clearly, keep simulation and export honestly unavailable, avoid finance terminology, avoid physical path disclosure, expose no public raw-data download, and have no blocking console error or horizontal overflow. Screenshots, if taken, must remain outside Git.

## Remaining Gen-2 Components

The first unresolved prerequisite is a manifest-bound `SPORTS_IDENTITY_BRIDGE_V1` companion. Until it exists, the player-prior feature view and all dependent modeling work remain blocked.

After that prerequisite, remaining work includes training the four bounded candidates, chronological hyperparameter selection, frozen 2024 and 2025 evaluation, calibration research, game-cluster bootstrap uncertainty, artifact lineage, registry metadata, and honest UI evidence. Dynamic player state, participation modeling, starter duration, bullpen usage, base-out simulation, residual modeling, forecast bundling, and prospective monitoring remain future phases.

No simulation result, export bundle, or prospective evidence exists.

## Recommended Next Step

Manual protected-page review remains a later owner task and does not block the Milestone A checkpoint commit. Authentication must remain unchanged.

To unblock Milestone B, publish a separate immutable `SPORTS_IDENTITY_BRIDGE_V1` companion bound to FD1 manifest SHA `1b58d5d1def2c9b79041472974e93bc9a0f4c5317210099c1b1ee531fbfe8b49`. Do not modify `SPORTS_DATASET_MANIFEST_V1` or the finalized FD1 package.

The companion should contain the compact active 2021–2025 identity spine with exact, source-version-bound canonical UUID, Retrosheet, Lahman, Chadwick, and available MLBAM identifiers, plus mapping status, confidence, source versions, rights controls, and row checksums. It must prove exact coverage of every 2023–2025 plate-appearance batter and pitcher identifier, joinability to every relevant `player_prior` canonical UUID, and rejection of duplicate or conflicting source identifiers. It must not use name-based or fuzzy matching, and genuine rookies without eligible priors must remain missing-prior cases rather than identity failures.

Register and validate the companion, then resume Milestone B from the existing dataset registration. Do not repeat Milestone A or the complete FD1 hash scan unless an FD1 package file changes. Do not weaken the identity gate, consult a sibling repository, or fit models against an ungoverned crosswalk.
