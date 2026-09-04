# MLB Remaining Feature Authority — Wave 1 Implementation Report

**Report date:** 2026-09-04

**Implementation branch:** `codex/mlb-remaining-feature-authority-wave1`

**Isolated worktree:** `C:\Users\james\asp-model-studio\.tmp\asp-remaining-feature-authority-wave1`

## Executive status

Wave 1 implementation is complete on the isolated branch. Two independent full-data builds now reproduce the exact same canonical manifest and object hashes; verification-only replay and immutable inactive registration also pass. The implementation publishes content-addressed sufficient-statistic evidence, resolves the remaining MLB feature-authority states without overstating estimator readiness, seals FINAL_OOT, and preserves the most restrictive combined source rights.

This report deliberately does **not** describe the work as “12 blockers cleared.” With an exact verified companion authority, the reconciliation is:

| Authority state | Count | Wave 1 meaning |
| --- | ---: | --- |
| `READY_GOVERNED_PRIOR_V1` | 11 | Exact estimator already implemented, training-fold fitted, transformable, tested, and content-addressed |
| `BINDING_READY_REQUIRES_WAVE2_ENGINE` | 10 | Exact component binding is verified, but the required estimator is not implemented |
| `RETIRED_NONSELECTABLE_BY_SCIENTIFIC_DECISION` | 3 | Scientific decision is resolved; definitions and audit evidence remain preserved |
| Still blocked by missing evidence | 0 | No component-evidence gap remains when the exact companion is supplied |

Wave 1 has not registered a model feature set, adopted a treatment or policy, fitted or tuned a predictive model, scored a model, calculated challenger lift, opened FINAL_OOT, or promoted a model. The one permitted combined treatment specification was created as `DRAFT`, its two linked policies are also `DRAFT`, and exact replay performed zero writes.

## 1. Verified coherent base lineage

Wave 1 was not based mechanically on the earlier `33cd85fa5074efeec3077036baea9c8b2ef86bdf` checkpoint. The repository lineage was inspected before the worktree was created.

| Item | Verified value |
| --- | --- |
| Exact Wave 1 base | `09006653b3f1714574a88efca8650d4f967ab3cd` |
| Base branch | `codex/mlb-interaction-authority-v1` |
| Earlier checkpoint | `33cd85fa5074efeec3077036baea9c8b2ef86bdf` |
| Lineage result | `33cd85f…` is an ancestor of `0900665…` |
| `main` reference at worktree creation | `924db29511f93909f9d785855bfa056775443690` |

The selected base is the latest verified coherent descendant containing:

- `MLB_FEATURE_TREATMENT_SPEC_V1`;
- `MLB_PLAYER_STATE_PRIOR_AUTHORITY_V1`;
- the completed interaction-recomputation authority; and
- the associated persistence, tests, and UI contracts.

The Wave 1 implementation consumes that interaction authority as inherited work. It neither reproduces nor omits it.

## 2. Implementation commits

The implementation is split into four reviewable commits:

1. `fb84096` — `feat(mlb): publish governed sufficient-statistics companion`
2. `597f80b` — `feat(stage3): govern remaining MLB prior feature states`
3. `7cadce1` — `test(mlb): prove Wave 1 authority and leakage gates`
4. `876fc21` — `fix(mlb): make velocity moments reproducible`

The implementation code head before this report-only commit is `876fc2132e1c55c65a55e8c6e8b77e709f0897d7`. The report commit's object ID is supplied in the final handoff; a content-addressed Git commit cannot truthfully embed its own final SHA.

## 3. Implemented files and contracts

### Companion publication and source projections

- `server/sports_current_statcast/gold.py`
- `server/sports_gold/features.py`
- `server/sports_current_statcast/sufficient_stats.py`
- `scripts/build_current_sufficient_stats.py`

These changes implement the immutable sufficient-statistics companion, development-only source projections, exact point-in-time aggregation, content-addressed partitions and manifest, verification-only replay, and inactive registry integration.

The publisher authenticates the frozen upstream Current Silver and Current Gold authorities before and after the build. Runtime resolution authenticates the top registration plus its partition, physical-schema, rights, limitations, and validation content. The binding authority is reconstructed from authenticated artifacts and must match registered metadata exactly. Re-signed tampering of the schema hash, validation-evidence hash, or required-column contract fails closed.

### Stage 3 authority and execution gates

- `server/sports_current_statcast/stage3_player_prior_authority.py`
- `server/sports_current_statcast/stage3_feature_treatment_spec.py`
- `server/sports_current_statcast/stage3_feature_engineering.py`

The Stage 3 compiler now distinguishes executable prior engines from evidence-only Wave 2 bindings and resolved retirements. Non-executable bindings expose no derived executable outputs. Feature engineering applies an intrinsic current-authority gate, so a missing or stale DRAFT cannot make a Wave 2, retired, or evidence-blocked feature executable. Direct feature-set registration revalidates the current authority.

### UI contract

- `src/sports/cockpit/projectTreatmentApi.ts`
- `src/sports/cockpit/projectFeatureSplitApi.ts`
- `src/sports/cockpit/TreatmentStudioShell.tsx`
- `src/sports/cockpit/ProjectBoundFeatureEngineering.tsx`

The UI treats the exact authority status as controlling, even if a contradictory legacy boolean is present. It renders executable, Wave 2, retired, and blocked states distinctly, preserves their rationales, and renders inactive core rows unchecked.

### Added or expanded verification

- `tests/current_statcast_sufficient_stats_test.py`
- `tests/phase7b2/test_gold_v1.py`
- `tests/sports_stage3_player_prior_authority_test.py`
- `tests/sports_stage3_feature_treatment_spec_test.py`
- `tests/sports_stage3_feature_engineering_test.py`
- `tests/sportsStage3FeatureSplitFrontend.test.mjs`
- `tests/sportsStage3TreatmentStudiosFrontend.test.mjs`

## 4. Canonical reproducible full-data publication receipt

### Immutable identity

| Field | Verified value |
| --- | --- |
| Dataset ID | `gold-table:gold_mlb_current_pa_sufficient_stats_v1` |
| Manifest contract | `MLB_CURRENT_STATCAST_SUFFICIENT_STATS_V1` |
| Manifest SHA-256 | `98673b65dc5eab61e39b16d1313c27bbb2cf908c525f80db579cb07a5cfdab33` |
| Physical-schema SHA-256 | `8d5eb7f1318a4eed4642080b7ee3b445653401615d9ae44290a7b8b3ea85fb8f` |
| Validation-evidence SHA-256 | `4a9209aa7e6850d2b3e2ec721514790c47fcc2c4f7072d2302183ff18a740fe7` |
| Current Silver manifest authority | `fcfb95724f2cc44ae45555897365497c538f5ea6303fe041dd4afa9697c62d2a` |
| Current Gold manifest authority | `67de02ce19738b29953341151640fb69244b764b0e532b687ab6bacedbb3f758` |
| Deterministic build A | `C:\Users\james\asp-model-studio\.tmp\wave1-companion-deterministic-a` |
| Deterministic build B / production root | `C:\Users\james\asp-data-staging\mlb-current-statcast-gold-v1` |
| Companion locator SHA-256 | `52cecd4e32d0df2b829b424deb93b5bd529aed07bda33441905f6b95ed940d32` |
| A/B reproducibility | Exact manifest bytes and ordered object hashes matched |
| Verify-only replay | Passed against the canonical production locator |

### Content-addressed partitions

| Role / season | Rows | Bytes | Object SHA-256 |
| --- | ---: | ---: | --- |
| DEVELOPMENT_SELECTION / 2023 | 182,072 | 9,247,956 | `e58caddb54382037690d04b899a1c2f194a0089e0b73af6c0bbe2dfdcb2659d9` |
| DEVELOPMENT_SELECTION / 2024 | 180,711 | 9,230,338 | `8eaf2e551ac8bc19211188817485f76e47bdb98dd510c3506b131aa45a1b4515` |
| DEVELOPMENT_SELECTION / 2025 | 182,847 | 9,356,136 | `247687f7855132c13e860f9155c6334e3ec9f838b221e3003bce02ba6d6db851` |
| DEVELOPMENT_SELECTION / 2026 through 2026-08-13 | 138,032 | 7,096,981 | `0dfad075fad4ff197833f60e1a0eb49287bc6c7aab475019d5a0d7de47bddf45` |
| FINAL_OOT_SEALED / 2026-08-14 through 2026-08-27 | 14,067 | 212,106 | `350ff402906ede4f39ae164c39719a84c3514529ffdc65deebcab8cf0cf139ba` |

Total rows are 697,729: 683,662 development rows and 14,067 sealed FINAL_OOT identity rows.

### Determinism incident, root cause, and correction

The initial dry manifest `0a9364aa5c67b32fe912fab5e39ad540ccc697c38c545d2e8b92f20788b4450e` and the first production-attempt manifest `f6279b6e3fbceab7dab0adc3f9404770dbe36b6741a8fcc12ac67f24568679c9` did not match. Both were stopped before registration and are superseded, unregistered evidence; neither is an accepted authority.

The audit localized every data difference to low-order floating-point bits in only:

- `pitcher_last250_fastball_velocity_sum`; and
- `pitcher_last250_fastball_velocity_sumsq`.

Row identities, integer counts, missingness, schema, rights, validation semantics, FINAL_OOT sealing, and all other payload fields were unchanged. The root cause was order-dependent parallel floating-point group reduction: mathematically identical source values could be accumulated in a different order across execution layouts.

Commit `876fc21` replaces those parallel moment reductions with a stable reducer. It filters the original finite `float64` fastball velocities, sorts by immutable `canonicalPaId` and velocity value, and applies a fixed contiguous `numpy.add.reduceat` order to both the values and their squared values. Source precision is retained; there is no quantization, decimal rounding, truncation, or integer coercion.

Post-fix audit coverage includes:

- an adversarial velocity permutation whose ordinary sequential sum differs by one ULP, asserting exact hexadecimal equality for sum and sum-of-squares;
- reversed source ordering;
- reversed multi-file input ordering;
- single-thread versus eight-thread Polars execution; and
- two independent full-data builds whose manifest bytes and five ordered object hashes are identical.

The canonical authority is therefore `98673b65dc5eab61e39b16d1313c27bbb2cf908c525f80db579cb07a5cfdab33`. The sealed FINAL_OOT object remained byte-identical throughout the incident and correction.

### Exact non-null and null accounting

The manifest contains 29 measured sufficient-statistic fields plus two `*_eligible_from_season` lineage fields. Counts below are exact and apply independently to every field named in each group.

| Field group | Fields | Development non-null | Development null | FINAL_OOT null | All-row null |
| --- | ---: | ---: | ---: | ---: | ---: |
| Batter annual components and eligibility | 11 | 630,913 | 52,749 | 14,067 | 66,816 |
| Pitcher annual components and eligibility | 8 | 609,838 | 73,824 | 14,067 | 87,891 |
| Batter last-100 counts | 2 | 683,662 | 0 | 14,067 | 14,067 |
| Pitcher last-250 counts and velocity aggregates | 10 | 683,662 | 0 | 14,067 | 14,067 |

The groups contain:

- Batter annual: `batter_prior_ab`, `batter_prior_h`, `batter_prior_2b`, `batter_prior_3b`, `batter_prior_hr`, `batter_prior_bb`, `batter_prior_hbp`, `batter_prior_sf`, `batter_prior_sh`, `batter_prior_so`, `batter_prior_eligible_from_season`.
- Pitcher annual: `pitcher_prior_ipouts`, `pitcher_prior_h`, `pitcher_prior_bb`, `pitcher_prior_hbp`, `pitcher_prior_bfp`, `pitcher_prior_g`, `pitcher_prior_gs`, `pitcher_prior_eligible_from_season`.
- Batter last-100: `batter_last100_swing_count`, `batter_last100_whiff_count`.
- Pitcher last-250: `pitcher_last250_pitch_count`, `pitcher_last250_swing_count`, `pitcher_last250_whiff_count`, `pitcher_last250_fastball_count`, `pitcher_last250_breaking_count`, `pitcher_last250_offspeed_count`, `pitcher_last250_other_or_unclassified_pitch_count`, `pitcher_last250_fastball_velocity_count`, `pitcher_last250_fastball_velocity_sum`, `pitcher_last250_fastball_velocity_sumsq`.

Annual missingness matches the existing Current Gold `*_prior_missing` flags exactly. Rolling fields are materialized for every development row; valid histories may legitimately have zero opportunities. The manifest records those zeros separately from nulls.

Observed development zero counts are:

```text
batter_last100_swing_count                           1,307
batter_last100_whiff_count                           1,765
batter_prior_2b                                     14,257
batter_prior_3b                                    228,199
batter_prior_ab                                         56
batter_prior_bb                                      6,736
batter_prior_eligible_from_season                        0
batter_prior_h                                       3,247
batter_prior_hbp                                    74,958
batter_prior_hr                                     33,465
batter_prior_sf                                     99,054
batter_prior_sh                                    435,470
batter_prior_so                                        698
pitcher_last250_breaking_count                      13,116
pitcher_last250_fastball_count                       7,131
pitcher_last250_fastball_velocity_count              7,131
pitcher_last250_fastball_velocity_sum                7,131
pitcher_last250_fastball_velocity_sumsq              7,131
pitcher_last250_offspeed_count                      72,895
pitcher_last250_other_or_unclassified_pitch_count  244,403
pitcher_last250_pitch_count                          6,855
pitcher_last250_swing_count                          6,862
pitcher_last250_whiff_count                          7,841
pitcher_prior_bb                                     4,135
pitcher_prior_bfp                                        0
pitcher_prior_eligible_from_season                       0
pitcher_prior_g                                          0
pitcher_prior_gs                                   186,480
pitcher_prior_h                                      1,460
pitcher_prior_hbp                                   86,768
pitcher_prior_ipouts                                    56
```

## 5. Exact physical dtypes

The manifest records every physical field and its nullability. Its exact schema is summarized below.

| Fields | Physical dtype | Nullable |
| --- | --- | --- |
| `canonicalPaId` | `string` | No |
| `game_date` | `date32[day]` | Yes; deliberately null for FINAL_OOT |
| `season` | `int16` | Yes; deliberately null for FINAL_OOT |
| `datasetRole`, `materialization_status` | `string` | No |
| `materialization_reason` | `string` | Yes |
| All event, exposure, pitch-composition, swing, whiff, and velocity-observation counts | `int64` | Yes |
| `batter_prior_eligible_from_season`, `pitcher_prior_eligible_from_season` | `int16` | Yes |
| `pitcher_last250_fastball_velocity_sum`, `pitcher_last250_fastball_velocity_sumsq` | Arrow/Parquet `double` (`float64`) | Yes |

The dtype validation result is `PASS_EXACT_PHYSICAL_INT64_AND_INT16` for integer fields and `PASS_FLOAT64_NO_ROUNDING_OR_TRUNCATION` for the two velocity aggregates. The velocity sum and sum-of-squares are never truncated, rounded, or coerced to integers.

## 6. Point-in-time and pitch-composition reconciliation

Annual histories select the latest eligible season satisfying season `<= Y - 1`. Rolling histories require `source.gameDate < target.gameDate`; same-date games are excluded.

The pitcher pitch denominator includes every pitch. The residual category is persisted as:

```text
pitcher_last250_other_or_unclassified_pitch_count
  = pitcher_last250_pitch_count
  - pitcher_last250_fastball_count
  - pitcher_last250_breaking_count
  - pitcher_last250_offspeed_count
```

The build verifies both:

```text
pitcher_last250_other_or_unclassified_pitch_count >= 0

fastball_count
+ breaking_count
+ offspeed_count
+ other_or_unclassified_pitch_count
= pitch_count
```

The validation receipt is `PASS_FULL_FOUR_CELL_COMPOSITION`. Future Dirichlet-Multinomial estimation must consume the full four-cell composition and cannot silently discard unclassified or unmatched pitches.

## 7. Scientific equivalence evidence

The canonical publication reconstructed and compared 12 existing Current Gold development features. Maximum absolute error was `1.1368683772161603e-13`, below the frozen `1e-6` tolerance. All exact count/rate reconstructions were zero-error except the expected floating-point velocity reduction at that maximum.

`pitcher_era9` was deliberately not reconstructed. `batter_obp` and `batter_last100_contact_rate` were reconstructed only as retained QA evidence for their resolved scientific retirements; neither becomes selectable.

No outcome or target was used in the build:

- declared target columns: `[]`;
- Current Gold target columns read: `[]`;
- Current Gold outcome rows read: `0`.

## 8. FINAL_OOT sealing evidence

FINAL_OOT is carried only to preserve one-to-one immutable publication identity. The sealed partition contains 14,067 rows and permits non-null values only for `canonicalPaId`, `datasetRole`, `materialization_status`, and `materialization_reason`.

For every FINAL_OOT row:

- `materialization_status = UNMATERIALIZED`;
- `materialization_reason = FINAL_OOT_SEALED`;
- `game_date`, `season`, all 29 measured statistic fields, and both eligibility fields are null;
- no outcome or target is read;
- no annual or rolling statistic is computed; and
- no prior feature is transformed.

The immutable audit counters are:

| Counter | Value |
| --- | ---: |
| FINAL_OOT identity rows carried | 14,067 |
| FINAL_OOT PA source rows read | 0 |
| FINAL_OOT pitch source rows read | 0 |
| FINAL_OOT payload rows read | 0 |
| FINAL_OOT statistic rows computed | 0 |
| FINAL_OOT rows transformed | 0 |

No OOT feature payload became accessible during either canonical build, verification replay, or registration.

## 9. Four-way feature-authority reconciliation

### Fully executable after Wave 1 evidence resolution — 11

These retain `READY_GOVERNED_PRIOR_V1` because their exact prior estimator is already implemented, fitted from training-fold authority, transformable, tested, and content-addressed:

- `pitcher_so_per_bfp`
- `pitcher_hr_per_bfp`
- `pitcher_hbp_per_bfp`
- `pitcher_bb_per_bfp`
- `batter_so_per_pa`
- `batter_hr_per_pa`
- `batter_bb_hbp_per_pa`
- `pitcher_last250_walk_rate`
- `pitcher_last250_strikeout_rate`
- `batter_last100_walk_hbp_rate`
- `batter_last100_strikeout_rate`

### Binding-ready, estimator still required in Wave 2 — 10

These expose validated component bindings under `BINDING_READY_REQUIRES_WAVE2_ENGINE`. They remain non-executable and non-selectable, publish no derived executable output family, and retain an explicit raw-field hold decision:

| Feature | Required Wave 2 estimator |
| --- | --- |
| `pitcher_whip` | `GAMMA_POISSON_COMPONENT_SHRINKAGE` |
| `pitcher_gs_per_g` | `DIRICHLET_MULTINOMIAL_EMPIRICAL_BAYES` |
| `batter_slg` | `DIRICHLET_MULTINOMIAL_COMPONENT_SHRINKAGE` |
| `batter_avg` | `DIRICHLET_MULTINOMIAL_COMPONENT_SHRINKAGE` |
| `pitcher_last250_avg_fastball_velocity` | `NORMAL_NORMAL_EMPIRICAL_BAYES` |
| `pitcher_last250_whiff_rate` | `DIRICHLET_MULTINOMIAL_EMPIRICAL_BAYES` |
| `pitcher_last250_offspeed_usage` | `DIRICHLET_MULTINOMIAL_EMPIRICAL_BAYES` |
| `pitcher_last250_fastball_usage` | `DIRICHLET_MULTINOMIAL_EMPIRICAL_BAYES` |
| `pitcher_last250_breaking_usage` | `DIRICHLET_MULTINOMIAL_EMPIRICAL_BAYES` |
| `batter_last100_whiff_rate` | `DIRICHLET_MULTINOMIAL_EMPIRICAL_BAYES` |

Publishing these components does not implement any of those estimators.

### Retired by resolved scientific decision — 3

The following fields are `RETIRED_NONSELECTABLE_BY_SCIENTIFIC_DECISION`:

- `pitcher_era9`
- `batter_obp`
- `batter_last100_contact_rate`

They remain non-executable, non-selectable, and excluded from feature sets. Their registered definitions, component mappings, retirement rationales, and historical audit evidence remain preserved. Their raw-field decision is `DROP_RAW_FIELD_RETIRED_NONSELECTABLE_BY_SCIENTIFIC_DECISION`; their derived-output contract is empty.

### Still blocked by missing evidence — 0

With the exact companion authority present, no feature remains in the missing-evidence bucket. Without an authenticated companion, the fail-closed reconciliation remains 11 executable / 0 Wave 2 binding-ready / 3 retired / 10 missing-evidence blocked.

Under the valid companion contract, the compiler contract tests report 219 total-ready fields and 16 remaining blockers: 2 semantic blockers plus 14 rivalry blockers. `canAdopt` remains false.

## 10. Effective rights authority

The companion combines FD1/Chadwick, SABR Lahman, and MLB Statcast-derived evidence. Its effective authority uses `INTERSECTION_MOST_RESTRICTIVE_APPLICABLE_SOURCE_AUTHORITY`; it never presents the companion as more permissive than any source registration.

| Right | Effective result |
| --- | --- |
| Status | `GOVERNED_LOCAL_RESEARCH_ONLY` |
| Allowed uses | `LOCAL_PRIVATE_MODEL_DEVELOPMENT`, `READ_ONLY_REGISTRATION` |
| Attribution | Required; Chadwick, SABR Lahman, and MLB Advanced Media / Baseball Savant obligations retained |
| Commercial rights | `UNCLEAR_REQUIRES_REVIEW` |
| Raw/public redistribution | Prohibited under the effective intersection |
| Unreviewed commercial redistribution | Prohibited |

The manifest preserves each source authority separately, including Chadwick attribution and transformation disclosure, SABR Lahman CC BY-SA 3.0 attribution and transformation disclosure, and Statcast’s `GOVERNED_LOCAL_RESEARCH_ONLY` status with explicit commercial-rights review.

## 11. No model or policy decision

The canonical manifest is evidence-only and non-selectable:

| Manifest control | Value |
| --- | --- |
| Status | `COMPANION_EVIDENCE_COMPLETE_NONSELECTABLE` |
| `modelEligible` | `false` |
| `workspaceActivationEligible` | `false` |
| Feature sets registered | 0 |
| Policies adopted | 0 |
| Models fitted | 0 |
| Models calibrated | 0 |
| Models scored | 0 |
| Models promoted | 0 |

The companion CLI has no model, policy-adoption, feature-set, scoring, evaluation, or promotion operation.

## 12. Test and independent-audit evidence

The final independent code audit signed off against all nine Wave 1 clarifications after the identified blockers were corrected.

| Verification | Result |
| --- | --- |
| Final related backend audit after the determinism correction | 102 passed |
| Independent focused backend code audit | 71 passed |
| Final focused frontend audit | 33 passed |
| TypeScript compilation | `npx tsc -b` passed |
| Broader focused backend run | 109 passed |
| Final integrity subset | 14 passed |
| Deterministic velocity-moment regression | Adversarial order, reversed order, multi-file order, and 1-thread/8-thread exact-hex checks passed |
| Full-data reproducibility | Independent A/B builds produced the same manifest and five object hashes |
| Current Statcast PA plus Gold Stage 2 review regressions | 7 passed, 1 skipped because the optional local project-persistence authority was absent |
| Modeling production build | Passed; 2,336 modules transformed |

`npm run test:sports-product` reported 10 passing and 5 failing static-contract checks. All five failures pre-existed this branch and are unrelated to the changed files. They concern legacy text tokens in:

- `HowToChoose.tsx` (`Start here` copy);
- `src/sports/index.ts` (`Version history`);
- `src/sports/cockpit/ProjectDataReview.tsx` (`data-quality`);
- `src/sports/cockpit/SportsProjectCockpit.tsx` (`locked downstream state`); and
- `src/sports/cockpit/stage3.ts` (`compact workflow rail`).

These baseline failures are disclosed rather than relabeled as Wave 1 passes.

## 13. Production publication and immutable registration

The production locator selects canonical manifest `98673b65dc5eab61e39b16d1313c27bbb2cf908c525f80db579cb07a5cfdab33`, and verification-only replay passed. A second clean full-data build produced the same manifest bytes and ordered object list as production.

### Frozen source-Gold rehash

Current Gold was rehashed before and after companion publication. Every authority byte remained unchanged:

| Frozen Current Gold object | SHA-256 |
| --- | --- |
| `current.json` locator | `a9258ebd3c4d51b2638173f55e5f26dc43df71c9bc67ce26277a7c17cebc6878` |
| Manifest | `67de02ce19738b29953341151640fb69244b764b0e532b687ab6bacedbb3f758` |
| 2023 object | `d3be5d47bc5a50e81e9fdf253a828ea43223b9a2dd6dc43851f198e4fbb926df` |
| 2024 object | `a9b86250209061c8a31a815f7bdbbf3a78f817e908c07d581f75a957d8ddc833` |
| 2025 object | `4c4af8a20b2b5f9b88d63753eff128a71f29117f8b28f3d647112a5b031721d4` |
| 2026 object | `dae01549bf60070e220cbf6b65625a010352a38c54f831d96237d3d4d42a5230` |

### Registration and idempotence receipt

| Field | Verified value |
| --- | --- |
| Registration ID | `sports-dataset-sufficient-stats-98673b65dc5eab61` |
| Dataset version ID | `gold-table:gold_mlb_current_pa_sufficient_stats_v1:sha256:98673b65dc5eab61e39b16d1313c27bbb2cf908c525f80db579cb07a5cfdab33` |
| First registration | `CREATED`; 13 writes |
| Exact re-registration | `REUSED`; 0 writes |
| Validation status | `VALID` |
| Active | `false` |
| Rights status | `GOVERNED_LOCAL_RESEARCH_ONLY` |
| Registered rows / bytes | 697,729 / 35,143,517 |
| Child records | 5 partitions, 1 schema, 3 source-right authorities, 3 limitations |
| Runtime binding checksum | `dbee3d1f5f414e3edd28cee10cd563189438be1bc9c9e852f88c962a5a8f5287` |

The 13 writes are fully reconciled by one registration, five partitions, one schema, three source-right authorities, and three limitations. The registration remained inactive, so it did not activate a dataset or make the evidence model-eligible.

Registry counts and SHA3-256 snapshots changed only where the new immutable registration required them:

| Registry table | Rows before → after | SHA3-256 before | SHA3-256 after |
| --- | ---: | --- | --- |
| `sports_dataset_registrations` | 5 → 6 | `9820ff029363ba2002177652dec707e7010dc17b5c538de6821fe28e59ecf602` | `c6f0aa2105154d9317f2d00203c24af9104c276aa0b4eee441973e1af04d33ad` |
| `sports_dataset_partitions` | 1,117 → 1,122 | `004e4b1a46f768d1c22c49c689d1cf22c1b1d8f3ad13183e9fe2c55162919365` | `769e3bdf8ebd1e58e57c4c4f3486a3730f9f8e5c09aa8219c61a0f95101fdce1` |
| `sports_dataset_schemas` | 95 → 96 | `672c2f9fd99499dbfeff4571f1079c6b3c81fdb419d963840068735a91035f46` | `085cf182430e6c4a03a15d590c61c40059c72cc63f2b7b63c7f216a22eb624cd` |
| `sports_dataset_rights` | 16 → 19 | `9688ead4db1126ae96aa980828f1b794d5dea35a43dbe33fcbccad95473c7a8e` | `a376f68218088b5a101340250df40c69db15e70b5e6e45afced8f2bd3c78341e` |
| `sports_dataset_limitations` | 29 → 32 | `05d9d26b09d3f063a428199363a418ff2e54dc1184dcc0555ab8135448794e84` | `031641c546745a0e6523d5bc610362255f805477a33f4a99298691e10f303f83` |

The other 49 snapshotted tables were byte-logically unchanged by initial registration. On exact replay, all 54 snapshotted tables retained their post-registration counts and digests. `sports_dataset_query_audit` remained at zero rows.

### Live authority resolution

Runtime resolution reconstructed and authenticated binding authority `MLB_SUFFICIENT_STATISTICS_BINDING_AUTHORITY_V1:sha256:dbee3d1f5f414e3edd28cee10cd563189438be1bc9c9e852f88c962a5a8f5287` from the inactive immutable registration.

The live four-way result is 11 executable / 10 binding-ready for Wave 2 / 3 scientifically retired / 0 missing-evidence blocked. The live compiler reports `totalReady=219`, `blockers=16`, and `canAdopt=false`.

## 14. Signed-in Stage 3 DRAFT receipt

The signed-in browser validation used the standard same-origin `/api` frontend path against the exact Wave 1 code at `876fc2132e1c55c65a55e8c6e8b77e709f0897d7`. The authenticated user menu showed the expected local administrator identity before any treatment mutation. The updated UI rendered the four-state result as 11 executable / 10 Wave 2 / 3 retired / 0 missing-evidence blocked, exposed the exact manifest below, and kept the adoption control disabled.

| Control | Verified receipt |
| --- | --- |
| Project | `asp-mtlozhdx` |
| Authority key | `03ca6dab30e760b2b86b65308090c2d358a67127cc34dfde7a75fc198c3ba84c:67de02ce19738b29953341151640fb69244b764b0e532b687ab6bacedbb3f758:4c228116951a3505d6a5d955f00cd2b92b35b1ccb85c7c69d11d77828485320e:af3e10a6d62537a57c2513a9ed6e96d44e5c7d5a6fdcf845a9fcb097ed8afe41` |
| Pre-DRAFT specification manifest | `077619a904c4c5c68dc00c451545927c1763f07b835681e95aecc9d9e882a292` |
| Draft gate | `canCreateDraft=true` |
| Adoption gate | `canAdopt=false`; UI control disabled; adopt endpoint not called |
| Combined specification | `stage3-feature-treatment-spec-06154e576ec9474580540f6cca287a17` · version 6 · `DRAFT` |
| Combined specification content SHA-256 | `0b50bfebd1ada3c2b191c963d0d91f1e1c5b1e9968efd84e06903e60b9c474d3` |
| Linked outlier policy | `stage3-outlier-policy-7a9cba6a30b64e73bae613b720ea5805` · version 6 · `DRAFT` · content `d00c081eef1939cc4f0398bb0ed0ba14e9c7cd75c8d5f538aad4d2e623c3a62c` |
| Linked imputation policy | `stage3-imputation-policy-1721c0822d744ca69ecc2c9d82841de4` · version 6 · `DRAFT` · content `bfefb931d756409b30620fb43c51d08699e3aa3ad5cf30d1f0f1583db0bcc089` |
| Exact replay | Reused all three IDs and checksums; created zero rows |

The first action produced only the expected append-only DRAFT delta:

| Table | Global rows | Project rows | Read-only schema-plus-row SHA3-256 before | SHA3-256 after |
| --- | ---: | ---: | --- | --- |
| `stage3_treatment_policy_versions` | 17 → 19 | 10 → 12 | `556a400b53b160bf0b9048706aa82cfb1d048fe916680ddf00ac20ed9d6b7c43` | `6070ce2a5467f54d0ebb99826811e92281c8649ebd1b11e6a23dab7e70ce0ada` |
| `stage3_treatment_policy_events` | 28 → 32 | 20 → 24 | `42a374d7d939b2264dd34d30d0a7a2bd3d1bc41a026ad86a51bcf53dedc2062f` | `39f2eac25792974bd21622aa62c37c32830f55a0cba2f16d3166a90fbb8f5560` |
| `stage3_feature_treatment_spec_versions` | 5 → 6 | 5 → 6 | `95958d6c1b41c4cf7e22248f9f9c77c751d0fb482f0614480476d2b5a8abf7a1` | `0c86778b15ddb04cb27745c78259696ed19f2ae706303b1a89c74c747fa905fb` |
| `stage3_feature_treatment_spec_events` | 5 → 6 | 5 → 6 | `704229dff3d284371a73d6f565ffacb86f4e08116d63020b876f5cc575261d89` | `75232e8aef594990b772a758405ac68afe207b4d27fc908693c59567f435eb19` |

The four new policy events are one outlier `DRAFT_UPDATED` and, for imputation, one each of `DRAFT_UPDATED`, `SOURCE_FAILURE_OVERRIDE_SELECTED`, and `VARIABLE_DROP_SELECTED`. The specification event is one `DRAFT_REVISED`.

Every version-6 `adopted_from` field is null. Project-level adopted treatment-policy and specification counts remain zero. Three unrelated historical adopted policy rows elsewhere in the database remained unchanged; Wave 1 did not create or modify them. Global adopted specification count remains zero.

Fifty of the 54 protected tables retained exact count and logical digest through the first DRAFT action. The five companion registry tables, project dataset links and activation tables, feature-set tables, model tables, scoring tables, run tables, and holdout-exposure tables were among those unchanged. After exact replay, all 54 protected tables matched the post-first-action counts and digests byte-logically.

The persisted manifest audit remains all-zero for preprocessing fits, feature sets registered, model fits, calibrations, scores, game-scoring jobs, provider calls, promotions, source/Gold mutations, historical artifact mutations, and FINAL_OOT rows opened. FINAL_OOT remains `LOCKED_UNOPENED`, 14,067 identity rows, zero access count, and `targetsAccessed=false`.

The isolated validation launch returned `WAVE1_SIDECAR_LAUNCHED_VERIFIED`: frontend `127.0.0.1:5275` was PID 50620, the backend wrapper was PID 54020, and backend listener `127.0.0.1:8102` was PID 51988. The protected primary identities remained frontend `127.0.0.1:5274` PID 33060 and backend `127.0.0.1:8101` PID 44536. Authentication was proven by `POST /api/auth/login` HTTP 200 followed by `GET /api/auth/me` HTTP 200 before either of the two DRAFT POSTs; the sidecar used the frontend's same-origin `/api` proxy. Its backend log contained exactly two DRAFT calls and no adoption-route match.

Cleanup returned `WAVE1_SIDECAR_CLEANUP_VERIFIED`: PIDs 50620, 54020, and 51988 were absent, ports 5275 and 8102 were free, and the transient launch receipt was absent. The user tab was returned to the authenticated primary dashboard; primary PIDs 33060 and 44536 were unchanged and both primary health URLs returned HTTP 200.

## 15. Final repository closure

| Repository control | Final value |
| --- | --- |
| Wave 1 branch | `codex/mlb-remaining-feature-authority-wave1` |
| Wave 1 isolated worktree | `C:\Users\james\asp-model-studio\.tmp\asp-remaining-feature-authority-wave1` |
| Verified coherent base | `09006653b3f1714574a88efca8650d4f967ab3cd` |
| Audited implementation head before report-only commit | `876fc2132e1c55c65a55e8c6e8b77e709f0897d7` |
| `main` reference | `924db29511f93909f9d785855bfa056775443690` — unchanged |
| Protected primary checkout | `codex/mlb-governed-prior-engine-v1` at `33cd85fa5074efeec3077036baea9c8b2ef86bdf` — unchanged |
| Push / merge | None performed |

The two pre-existing untracked user files in the protected primary checkout remain untracked and byte-preserved:

| User file | Bytes | SHA-256 |
| --- | ---: | --- |
| `ASP_MLB_Feature_Treatment_Specification.xlsx` | 99,432 | `0e2d5f2b0d495c941ae97fb84c216f0b5ccdfe904519db0acb616d1543a66679` |
| `docs/PHASE_7D3_CODEX_FINAL_SILVER_READINESS_REPORT.md` | 32,734 | `72c5a70d12a61f04ffdebfb2d3a5a11b17236b29abd0d9d36fd035ddd12593a6` |

The final handoff records the report-only commit ID, post-commit clean status, and final `git diff --check` result. Those values are intentionally recorded after creating the content-addressed commit rather than guessed inside the commit that contains this report.
