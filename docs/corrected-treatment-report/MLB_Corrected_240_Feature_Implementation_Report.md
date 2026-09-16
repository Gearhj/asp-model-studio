# MLB corrected treatment: 240-feature before/after implementation report

Prepared September 7, 2026; updated after the preserved failed V18 study attempt. This is an implementation and failure-handoff report, not a completed predictive comparison or proof of empirical improvement.

The [machine-readable report](C:/Users/james/asp-model-studio/docs/corrected-treatment-report/MLB_Corrected_240_Feature_Implementation_Report.json) contains one row for every source feature, preserving its recommendation, original V14 operations and evidence, corrected implementation path, explicit model columns, approval provenance, remaining issue, and pending fitted-fold evidence.

## Study outcome: infrastructure failure before a completed fold

The V18 treatment and feature schema were registered, and all five preprocessing preflights passed. The actual HGB attempt then failed with `[WinError 5] Access is denied` before its first fold completed. It was preserved without retry.

The [run receipt](C:/Users/james/asp-model-studio/.runtime/asp-model-studio/stage3-model-laboratory/objects/sha256/cf308ac9f910073a170f5ab6fa5e4adfd969b2eed2ec8e5ff3d17c54ee77cbc8.json) records `PARTIAL`; the [candidate attempt](C:/Users/james/asp-model-studio/.runtime/asp-model-studio/stage3-model-laboratory/candidate-attempts/objects/sha256/f9abd8c13bc57d741d6d2758e4491d002684147758e2b9c9d5717ca93067ffea.json) records `FAILED` with zero completed folds and no fold results. Both receipt-file hashes were independently verified.

Only fold1 started; folds2–5 were not attempted. The aggregate `failedFits=5` describes the scheduled configuration accounting, not five real failed fit attempts. The actual boosting iteration count was not recorded and must not be inferred. Progress elapsed was111.747 seconds; the run and candidate receipts separately record111,735ms and103,474ms.

Root-agent diagnostics localized a Windows Pipe/permission failure during HGB binning: a synthetic80×4 matrix, one iteration and the same four native workers reproduced it in the restricted environment; the same artificial test passed elevated. That diagnostic is not a real-study retry or evidence of a trained V18 model. Complete identifiers, diagnostics and accounting are in [Study failure state](C:/Users/james/asp-model-studio/docs/corrected-treatment-report/Study_Failure_State.json).

No corrected log loss, Brier, ROC-AUC, calibration results, confidence interval, subgroup predictive metrics, completed V18 predictive-model artifact or full-model replay result is available. Preserve V18 corrections and the saved V14 comparison baseline. The next step is to address this specific execution-environment blocker and obtain explicit authorization for a bounded retry of the same frozen study; do not roll back to the incorrect preprocessing path merely to obtain a result. Final OOT remains sealed and no promotion occurred.

## Accounting and scope

| View | Implemented scope | Approved exclusions | Partial / unresolved |
| --- | ---: | ---: | ---: |
| Original V14 audit, retained unchanged | 137 | 22 | 81 |
| V14 reassessment after the repeat-opponent domain finding | 133 | 22 | 85 |
| Corrected code paths before recorded-run verification | 215 | 22 | 3 with an explicit zero-opportunity row hold |

The corrected count of215 is a code-path assessment, not215 empirically verified fitted bundles. Three additional annual V1 batter-rate paths are implemented for eligible observations but retain an unresolved known-zero-prior-PA state. Their56 shared observations are quarantined under a frozen, outcome-independent rule. The source population is not rewritten.

The revised V14 accounting reflects four newly exposed Boolean-domain gaps among its originally137 implemented classifications. Original audit files, V14 records, experiments and receipts remain historical evidence; this report does not overwrite their claims or invent previously missing fitted parameters.

The source inventory remains240 features, with218 selected and22 approved exclusions. The actual corrected model schema has273 explicit columns before one-hot encoding: the218 source slots plus55 registered V1 outputs. Fourteen additional rivalry deferrals are outside the spreadsheet and are not subtracted again.

### Source and decision identities

- Normalized recommendations: all240×26 source cells match; zero changed recommendation cells. The requested “(1)” filename was absent, while the reconciled Downloads source is identified explicitly.
- Downloads workbook SHA: `c5f941236246442977a88865774903dea0ad37cab1ff1c3514cd6a78af2758e3`.
- Registered workbook SHA: `0e2d5f2b0d495c941ae97fb84c216f0b5ccdfe904519db0acb616d1543a66679`.
- Original audit JSON SHA: `15382f6ae349b2563367fe2a3223c13c991ad8655910cdd290096302f8c67980`.
- V14 manifest SHA: `ba36557bb986f87be40dc18a4a669f4e5d4f979becf2d0e70fda5226f15f544d`.
- User implementation/study authorization SHA: `61046f7c1465733f70623bb74533e050fbca8ed93a8c2fb55346e71afa6f1ae9`.

The successor decision is recorded in [the correction authority](C:/Users/james/asp-model-studio/server/sports_current_statcast/mlb_corrected_treatment_decision_v1.json). Final adopted identities below come from the immutable V18 registration receipt, not a pre-run compiler snapshot.

## Verified registration and preprocessing preflight

Final registration is recorded by [the verified V18 receipt](C:/Users/james/asp-model-studio/.runtime/asp-model-studio/stage3-model-laboratory/objects/corrected-preprocessing/sha256/7e43d29cdecd976465d26bddb30d4f5d67ec0b0d0d2e299981f1d87fef11172c.json):

- TreatmentV18: `stage3-feature-treatment-spec-711fbb376e9a4d419f826de593195638`; manifest `4d158e01a4a7d84fe6e7641f61edf0e9848f1775e025a2cec6c29cda22d479f3`.
- Feature set: `stage3-feature-set-486aefc6482f46ddac2bed94b210e05d`,273 explicit inputs.
- Split: `stage3-split-contract-53bb07e31caa444b8246e260ba7761e0`, split version12.
- The receipt records zero model fits launched by registration, zero Final OOT payload rows read and preserved V14.

V16 remains preserved as an intermediate adoption before the exact-authority loader correction. That correction was completed before any predictive fits. Draft and adoption each allocate immutable versions, so the final post-fix pair producedV18; this does not imply repeated model fitting.

All five complete preprocessing preflight receipts passed. Their file SHA-256 values and the registration receipt's file SHA were independently checked against their CAS filenames, and the compact fields were parsed into [Registration and preflight evidence](C:/Users/james/asp-model-studio/docs/corrected-treatment-report/Registration_and_Preflight_Evidence.json).

| Fold | Training source → eligible | Validation source → eligible | Encoded columns | Evidence |
| --- | ---: | ---: | ---: | --- |
| 1 | 182,072 → 182,067 | 99,782 → 99,780 | 432 | [PASS receipt](C:/Users/james/asp-model-studio/.runtime/asp-model-studio/stage3-model-laboratory/objects/corrected-preprocessing/sha256/e4c4872d2438439ee6b4c8c7d730dd13b9eb7bc8c64b8aa2e54bc2449ec82e84.json) |
| 2 | 281,854 → 281,847 | 100,269 → 100,267 | 434 | [PASS receipt](C:/Users/james/asp-model-studio/.runtime/asp-model-studio/stage3-model-laboratory/objects/corrected-preprocessing/sha256/19836b2464b48a1941af8f58061592d4693f39e8bf2f2643304d27083f9e4dc6.json) |
| 3 | 382,123 → 382,114 | 99,968 → 99,926 | 435 | [PASS receipt](C:/Users/james/asp-model-studio/.runtime/asp-model-studio/stage3-model-laboratory/objects/corrected-preprocessing/sha256/e5bc9efadb8d39337b8a1cea0fa3200bda666d5c2e7662baba42012e56676548.json) |
| 4 | 482,091 → 482,040 | 100,304 → 100,302 | 435 | [PASS receipt](C:/Users/james/asp-model-studio/.runtime/asp-model-studio/stage3-model-laboratory/objects/corrected-preprocessing/sha256/cdf6cda911e1a71323b3b783ac8cc0c1fd7de4b16e131d7dfee03a8ff08c280a.json) |
| 5 | 582,395 → 582,342 | 101,267 → 101,264 | 436 | [PASS receipt](C:/Users/james/asp-model-studio/.runtime/asp-model-studio/stage3-model-laboratory/objects/corrected-preprocessing/sha256/8594d892090ae030ecf8e7ddebcd00e1d27c54d5f9fe430a91e67313b396ed07.json) |

These receipts explicitly use `UNREGISTERED_CORRECTED_PREFLIGHT_ONLY` and provisional treatment manifest `48de9ecbe2932fedd33cbce401dc4478a00d5a41b4d327a4d14152764c41807c`. Each records `PREFLIGHT_PREPROCESSING_ONLY_NOT_A_MODEL_RUN`, zero predictive fits and zero Final OOT rows read. They are preprocessing evidence, not finalV18 predictive-fit receipts or full trained-model reload verification. The differences between273 registered columns and432–436 encoded columns are the fold-local category expansions.

The subsequent real attempt failed before its first completed fold. Training results, finalV18 predictive artifacts, full-model reload verification and empirical comparison are unavailable, not verified by these preserved preflight receipts.

## What changed in the implementation

| Group | Features | Corrected behavior |
| --- | ---: | --- |
| No-prior context | 22 | Validate reason/source flags and domains. HGB permits native missingness only for governed no-history states; the shared non-tree contextual fill is training-only, not another authorized model run. |
| Structural zero | 8 | Zero follows a validated no-prior-game reason, not a median/mode that happens to be zero. |
| Annual exposure | 2 | Zero log1p exposure only for verified absent prior history; preserve reason indicator and reject invalid exposure. |
| Travel interactions | 8 | Treat parents first, recompute existing prescribed formulas and assert transformed-parent equality. No independent product fill. |
| Deterministic interactions | 4 | Recompute home×weekend and home×Friday-night Booleans from valid parents. |
| V1 prior representations | 11 | Preserve valid raw slot and append posterior mean, effective N, reliability, posterior standard deviation and history state using registered output names. |
| V2 prior integration | 10 | Keep exact approved posterior-only scope; disallowed states cannot reach a median. Preserve the separately governed WHIP fallback. |
| Required-complete features | 15 | Enforce domain and future-missing rejection at Model Lab. Rejection is the permitted alternative to reconstructing unavailable evidence. |
| Matchup specification | 1 | Explicitly correct inconsistent player-rate wording to deterministic matchup Boolean; reject unavailable/contradictory handedness. |
| Newly exposed repeat-opponent domain gaps | 4 | Validate the published finite nonnegative integer count and convert `count > 0` to the recommended Boolean. No source rewrite or null fill. |
| Carried-forward core | 133 | Preserve audited source/indicator/simulator scope with the corrected shared validation boundary. Original evidence and prospective-contract qualifications still apply. |

The85 repaired/newly evidenced source-feature gaps are distinct from the133 carried-forward source features. The report does not claim that every recommended statistical diagnostic or every prospective source contract was independently executed.

Implementation entry points are [Model Lab preparation](C:/Users/james/asp-model-studio/server/sports_current_statcast/stage3_model_laboratory.py:1367), [semantic fit/transform](C:/Users/james/asp-model-studio/server/sports_current_statcast/stage3_semantic_treatment.py:223), [corrected prior representation](C:/Users/james/asp-model-studio/server/sports_current_statcast/stage3_corrected_prior_treatment.py:244), [model-matrix validation](C:/Users/james/asp-model-studio/server/sports_current_statcast/stage3_semantic_treatment.py:365), and [explicit model schema](C:/Users/james/asp-model-studio/server/sports_current_statcast/stage3_corrected_treatment_spec.py:57). Line numbers are observed code locations; symbol names in the JSON remain the durable lookup.

### Four repeat-opponent corrections discovered during preflight

The four fields are selected source features, not deferred rivalry mappings. Their workbook rows124,125,191,192 require Boolean `{0,1}`, while [the source construction](C:/Users/james/asp-model-studio/server/sports_current_statcast/contextual_features.py:271) uses sums of matching-opponent prior games and publishes the counts unchanged.

The [target-free physical-domain diagnostic](C:/Users/james/asp-model-studio/docs/corrected-treatment-report/Repeat_Opponent_Count_Diagnostic.json) records:

| Feature window, each batting/fielding field | Physical cells greater than1 | Observed range | Null cells |
| --- | ---: | --- | ---: |
| 7 days | 261,756 | 0–4 | 0 |
| 14 days | 275,046 | 0–7 | 0 |

These are full683,662-row physical-source counts, including the56 separately held observations. They are not disjoint OOF counts, unique affected-row sums, or completed transform counters. The successor rule is `REPEAT_OPPONENT_BOOLEAN`; recorded fold evidence must later supply `booleanDomainRepairRows`, `deterministicRecomputedRows`, and `changedRows`.

## Explicit coverage hold, not imputation

The same56 PAs in `batter_so_per_pa`, `batter_bb_hbp_per_pa`, and `batter_hr_per_pa` have all three raw rates missing, exact numeric `batter_log1p_pa = 0`, and valid `batter_prior_missing = false`. All five corresponding AB-outcome components are known zero, not missing. The existing V1 authority lacks an executable known-zero-opportunity state; its output remains fail-closed. This is not a source outage and is not relabeled genuine cold start.

[The immutable diagnostic](C:/Users/james/asp-model-studio/docs/corrected-treatment-diagnostics/sha256/08b0d20c8339810249bbe55ca92134664be8febda26b6777909514e49ed670fd.json) identifies56 PAs across31 games/16 batters. Counts by year are5,2,46,3 for2023–2026. All other eight V1 features have no diagnosed invalid states, and no disallowed V2 states were found. WHIP's separately governed fallback is preserved.

[The row-eligibility helper](C:/Users/james/asp-model-studio/server/sports_current_statcast/stage3_corrected_eligibility.py:45) returns a Boolean eligibility mask plus immutable per-observation reason evidence. It does not delete source rows, fill values, change history labels or read targets.

| Fold | Held training observations | Held validation observations |
| --- | ---: | ---: |
| 1 | 5 | 2 |
| 2 | 7 | 2 |
| 3 | 9 | 42 |
| 4 | 51 | 2 |
| 5 | 53 | 3 |

Source Development remains683,662 observations with unchanged chronological boundaries. The diagnosed eligible population is683,606, coverage99.9918088178%. Across the five disjoint validation windows,51 observations are held. The study must compare both models on exact matching eligible OOF identities and separately show original V14 metrics on its original population. The registered policy checksum is `8a28ee325505a657fa5cffa30a6278c9e10c82a01983516c29c701b2c12dcd61`.

## Exclusions, optional outputs and deferred work

All22 approved exclusions remain absent: four source-repair exclusions, two coverage-repair exclusions, three scientific retirements, two direct context deferrals and11 dependent context deferrals. The three retirements—`pitcher_era9`, `batter_obp`, `batter_last100_contact_rate`—are resolved scientific decisions, not unresolved blockers. Their definitions and provenance remain available.

V2 auxiliary exposure/reliability/uncertainty outputs are optional later candidates. Their absence is not a missing implementation. No additional V2 candidate was added merely to improve an audit count.

Parent-only ablations for the interaction families are explicitly deferred by the current user request. Correct transformed-parent recomputation is implemented independently of that deferred model-comparison question. No extra ablation fits are implied.

Known-zero-prior-PA treatment remains a scientific gap for the three V1 features on those56 observations. Explicit quarantine contains the gap for this bounded comparison; it does not resolve the missing V1 state definition.

One prospective authority limitation remains: the semantic timezone representation permits legitimate unwrapped offsets above12 hours, while the currently registered interaction authority retains an eastward-parent domain of0–12 hours. All five verified preflight folds passed without an exposed impact. This is not labeled a current-data blocker, and neither the interaction engine nor its registered domain was expanded. Future travel coverage outside that interaction authority is not claimed; an encountered unsupported state must still fail closed.

## Fitted evidence and comparison unavailable after the failed attempt

The source/code changes, synthetic tests and verified five-fold preprocessing preflight establish implementation paths and preflight execution. The provisional receipts carry detailed branch counters, but are not V18 predictive runs. Per-feature completed-V18 changed-row counts, fitted-run branch counters, trained-model artifact references and saved-model reload evidence are unavailable after the infrastructure failure; preflight references are provided separately rather than relabeled final-run evidence.

The persistence path is implemented in [persist and verify](C:/Users/james/asp-model-studio/server/sports_current_statcast/stage3_corrected_preprocessing_artifacts.py:101). Successful saved-artifact reload must be demonstrated by recorded successor evidence. Historical V1 parameter payloads must not be called recovered unless their bytes match the original hashes; newly fitted parameters are new evidence. Original hash-verified V2 artifacts remain identified in the prior audit.

The repeat-opponent repair is covered by the semantic and actual-entry synthetic test suites:60 tests passed in the combined run. That includes synthetic saved-model reload and source-count preservation, not a completed full-Development successor artifact verification. Its rule registration, conversion and per-row counters are at `stage3_semantic_treatment.py` lines89,323 and332–333 at this snapshot.

If an explicitly authorized bounded retry completes, the still-required comparison evidence is:

- Final V18 predictive-fit/candidate receipts tied to the immutable treatment, feature-set, policy and split identities above.
- Five-fold preflight/branch evidence, actual input changes, failure-path exercise counts and explicit coverage receipts.
- Saved preprocessing/prior/model artifact paths and transform/prediction reload equality results.
- Exact original V14 results, paired common-observation log loss/Brier/ROC-AUC, per-fold metrics and established calibration diagnostics.
- Paired game-clustered confidence interval and predefined cold-start/no-history subgroup counts/results.
- Runtime, failures and Final OOT seal evidence.

No empirical improvement, completed corrected fit, successful full trained-model artifact replay, promotion or champion declaration is asserted in this report. Receipt-file content checksum verification is explicitly distinguished from predictive-artifact replay.

## Exhaustive source-feature index

I = original audited implemented; N = missing/materially partial; X = approved exclusion. An “I → N” entry is a newly evidenced correction to the original classification.

After: I* = implemented code path, no completed V18 predictive-fold evidence following infrastructure failure; H = implemented for eligible rows with the explicitly unresolved56-row known-zero-opportunity hold; X = preserved approved exclusion. The JSON supplies the exact recommendation, operations, code references, preflight and failed-study evidence states, and decisions for every row.

| Source row | Feature | V14 audit / reassessed | After | Corrected treatment group |
| --- | --- | --- | --- | --- |
| 2 | `fielding_hours_since_previous_game_end` | X | X | Approved exclusions |
| 3 | `fielding_altitude_change_feet` | X | X | Approved exclusions |
| 4 | `batting_hours_since_previous_game_end` | X | X | Approved exclusions |
| 5 | `batting_altitude_change_feet` | X | X | Approved exclusions |
| 6 | `doubleheader_game_number` | X | X | Approved exclusions |
| 7 | `holiday_name` | X | X | Approved exclusions |
| 8 | `fielding_previous_game_duration_minutes` | X | X | Approved exclusions |
| 9 | `batting_previous_game_duration_minutes` | X | X | Approved exclusions |
| 10 | `pitcher_whip` | N | I* | V2 posterior-only validated integration |
| 11 | `pitcher_era9` | X | X | Approved exclusions |
| 12 | `pitcher_so_per_bfp` | N | I* | V1 raw plus five registered outputs |
| 13 | `pitcher_log1p_bfp` | N | I* | Reason-authorized exposure zero |
| 14 | `pitcher_hr_per_bfp` | N | I* | V1 raw plus five registered outputs |
| 15 | `pitcher_hbp_per_bfp` | N | I* | V1 raw plus five registered outputs |
| 16 | `pitcher_gs_per_g` | N | I* | V2 posterior-only validated integration |
| 17 | `pitcher_bb_per_bfp` | N | I* | V1 raw plus five registered outputs |
| 18 | `batter_so_per_pa` | N | H | V1 raw plus five registered outputs |
| 19 | `batter_slg` | N | I* | V2 posterior-only validated integration |
| 20 | `batter_obp` | X | X | Approved exclusions |
| 21 | `batter_hr_per_pa` | N | H | V1 raw plus five registered outputs |
| 22 | `batter_bb_hbp_per_pa` | N | H | V1 raw plus five registered outputs |
| 23 | `batter_avg` | N | I* | V2 posterior-only validated integration |
| 24 | `batter_log1p_pa` | N | I* | Reason-authorized exposure zero |
| 25 | `pitcher_last250_avg_fastball_velocity` | N | I* | V2 posterior-only validated integration |
| 26 | `pitcher_last250_whiff_rate` | N | I* | V2 posterior-only validated integration |
| 27 | `pitcher_last250_walk_rate` | N | I* | V1 raw plus five registered outputs |
| 28 | `pitcher_last250_strikeout_rate` | N | I* | V1 raw plus five registered outputs |
| 29 | `pitcher_last250_offspeed_usage` | N | I* | V2 posterior-only validated integration |
| 30 | `pitcher_last250_fastball_usage` | N | I* | V2 posterior-only validated integration |
| 31 | `pitcher_last250_breaking_usage` | N | I* | V2 posterior-only validated integration |
| 32 | `fielding_westward_time_zone_change_hours` | N | I* | Reason-aware context/native missingness |
| 33 | `fielding_travel_distance_miles` | N | I* | Reason-aware context/native missingness |
| 34 | `fielding_time_zone_change_hours` | N | I* | Reason-aware context/native missingness |
| 35 | `fielding_start_hour_in_previous_venue_time_zone` | N | I* | Reason-aware context/native missingness |
| 36 | `fielding_road_trip_length_x_travel` | N | I* | Treated-parent travel recomputation |
| 37 | `fielding_prior_extra_innings_x_travel` | N | I* | Treated-parent travel recomputation |
| 38 | `fielding_previous_game_innings` | N | I* | Reason-aware context/native missingness |
| 39 | `fielding_previous_game_extra_innings` | N | I* | Reason-authorized structural zero |
| 40 | `fielding_long_travel_x_short_rest` | N | I* | Treated-parent travel recomputation |
| 41 | `fielding_hours_since_previous_game_start` | N | I* | Reason-aware context/native missingness |
| 42 | `fielding_eastward_travel_x_early_start` | N | I* | Treated-parent travel recomputation |
| 43 | `fielding_eastward_time_zone_change_hours` | N | I* | Reason-aware context/native missingness |
| 44 | `fielding_days_since_previous_game` | N | I* | Reason-aware context/native missingness |
| 45 | `fielding_crossed_two_or_more_time_zones` | N | I* | Reason-authorized structural zero |
| 46 | `fielding_crossed_time_zone` | N | I* | Reason-authorized structural zero |
| 47 | `fielding_cross_country_travel` | N | I* | Reason-authorized structural zero |
| 48 | `fielding_circadian_timezone_component` | N | I* | Reason-aware context/native missingness |
| 49 | `fielding_circadian_short_recovery_component` | N | I* | Reason-aware context/native missingness |
| 50 | `fielding_circadian_disruption_score` | N | I* | Reason-aware context/native missingness |
| 51 | `batting_westward_time_zone_change_hours` | N | I* | Reason-aware context/native missingness |
| 52 | `batting_travel_distance_miles` | N | I* | Reason-aware context/native missingness |
| 53 | `batting_time_zone_change_hours` | N | I* | Reason-aware context/native missingness |
| 54 | `batting_start_hour_in_previous_venue_time_zone` | N | I* | Reason-aware context/native missingness |
| 55 | `batting_road_trip_length_x_travel` | N | I* | Treated-parent travel recomputation |
| 56 | `batting_prior_extra_innings_x_travel` | N | I* | Treated-parent travel recomputation |
| 57 | `batting_previous_game_innings` | N | I* | Reason-aware context/native missingness |
| 58 | `batting_previous_game_extra_innings` | N | I* | Reason-authorized structural zero |
| 59 | `batting_long_travel_x_short_rest` | N | I* | Treated-parent travel recomputation |
| 60 | `batting_hours_since_previous_game_start` | N | I* | Reason-aware context/native missingness |
| 61 | `batting_eastward_travel_x_early_start` | N | I* | Treated-parent travel recomputation |
| 62 | `batting_eastward_time_zone_change_hours` | N | I* | Reason-aware context/native missingness |
| 63 | `batting_days_since_previous_game` | N | I* | Reason-aware context/native missingness |
| 64 | `batting_crossed_two_or_more_time_zones` | N | I* | Reason-authorized structural zero |
| 65 | `batting_crossed_time_zone` | N | I* | Reason-authorized structural zero |
| 66 | `batting_cross_country_travel` | N | I* | Reason-authorized structural zero |
| 67 | `batting_circadian_timezone_component` | N | I* | Reason-aware context/native missingness |
| 68 | `batting_circadian_short_recovery_component` | N | I* | Reason-aware context/native missingness |
| 69 | `batting_circadian_disruption_score` | N | I* | Reason-aware context/native missingness |
| 70 | `batter_last100_whiff_rate` | N | I* | V2 posterior-only validated integration |
| 71 | `batter_last100_contact_rate` | X | X | Approved exclusions |
| 72 | `batter_last100_walk_hbp_rate` | N | I* | V1 raw plus five registered outputs |
| 73 | `batter_last100_strikeout_rate` | N | I* | V1 raw plus five registered outputs |
| 74 | `series_game_number` | N | I* | Required-complete domain/rejection guard |
| 75 | `season_phase` | I | I* | Carried-forward audited core |
| 76 | `pitcher_prior_missing` | I | I* | Carried-forward audited core |
| 77 | `pitcher_prior_bf_count` | I | I* | Carried-forward audited core |
| 78 | `pitcher_last250_whiff_missing` | I | I* | Carried-forward audited core |
| 79 | `pitcher_last250_velocity_missing` | I | I* | Carried-forward audited core |
| 80 | `pitcher_last250_insufficient` | I | I* | Carried-forward audited core |
| 81 | `pitcher_last250_bf_count` | I | I* | Carried-forward audited core |
| 82 | `month_sin` | I | I* | Carried-forward audited core |
| 83 | `month_cos` | I | I* | Carried-forward audited core |
| 84 | `matchup_platoon_advantage` | N | I* | Explicit matchup Boolean correction |
| 85 | `matchup_pitcher_throws_left` | I | I* | Carried-forward audited core |
| 86 | `matchup_pitcher_hand_missing` | I | I* | Carried-forward audited core |
| 87 | `matchup_batter_hand_missing` | I | I* | Carried-forward audited core |
| 88 | `matchup_batter_bats_switch` | I | I* | Carried-forward audited core |
| 89 | `matchup_batter_bats_left` | I | I* | Carried-forward audited core |
| 90 | `local_start_hour_sin` | N | I* | Required-complete domain/rejection guard |
| 91 | `local_start_hour_cos` | N | I* | Required-complete domain/rejection guard |
| 92 | `local_start_hour` | N | I* | Required-complete domain/rejection guard |
| 93 | `is_weekend` | I | I* | Carried-forward audited core |
| 94 | `is_sunday` | I | I* | Carried-forward audited core |
| 95 | `is_series_opener` | I | I* | Carried-forward audited core |
| 96 | `is_series_finale` | I | I* | Carried-forward audited core |
| 97 | `is_saturday` | I | I* | Carried-forward audited core |
| 98 | `is_night_game` | I | I* | Carried-forward audited core |
| 99 | `is_home_opener` | I | I* | Carried-forward audited core |
| 100 | `is_holiday_eve` | X | X | Approved exclusions |
| 101 | `is_holiday` | X | X | Approved exclusions |
| 102 | `is_getaway_day` | I | I* | Carried-forward audited core |
| 103 | `is_friday` | I | I* | Carried-forward audited core |
| 104 | `is_doubleheader` | X | X | Approved exclusions |
| 105 | `is_day_game` | I | I* | Carried-forward audited core |
| 106 | `holiday_region` | I | I* | Carried-forward audited core |
| 107 | `game_month` | I | I* | Carried-forward audited core |
| 108 | `game_day_of_week` | I | I* | Carried-forward audited core |
| 109 | `game_day_of_season` | N | I* | Required-complete domain/rejection guard |
| 110 | `fielding_venue_coordinate_missing` | I | I* | Carried-forward audited core |
| 111 | `fielding_travel_path_missing` | I | I* | Carried-forward audited core |
| 112 | `fielding_travel_distance_last_7_days` | N | I* | Required-complete domain/rejection guard |
| 113 | `fielding_travel_distance_last_3_days` | N | I* | Required-complete domain/rejection guard |
| 114 | `fielding_time_zone_missing` | I | I* | Carried-forward audited core |
| 115 | `fielding_team_home_timezone_missing` | I | I* | Carried-forward audited core |
| 116 | `fielding_team_alignment_missing` | I | I* | Carried-forward audited core |
| 117 | `fielding_start_hour_in_team_home_time_zone` | N | I* | Required-complete domain/rejection guard |
| 118 | `fielding_short_rest_indicator` | I | I* | Carried-forward audited core |
| 119 | `fielding_series_rematch_indicator` | I | I* | Carried-forward audited core |
| 120 | `fielding_same_league_game` | I | I* | Carried-forward audited core |
| 121 | `fielding_same_division` | I | I* | Carried-forward audited core |
| 122 | `fielding_road_trip_game_number` | I | I* | Carried-forward audited core |
| 123 | `fielding_returned_home_after_road_trip` | I | I* | Carried-forward audited core |
| 124 | `fielding_repeat_opponent_within_7_days` | I → N | I* | Newly exposed count-to-Boolean repair |
| 125 | `fielding_repeat_opponent_within_14_days` | I → N | I* | Newly exposed count-to-Boolean repair |
| 126 | `fielding_recent_bullpen_workload_missing` | I | I* | Carried-forward audited core |
| 127 | `fielding_previous_venue_timezone_missing` | I | I* | Carried-forward audited core |
| 128 | `fielding_previous_venue_coordinates_missing` | I | I* | Carried-forward audited core |
| 129 | `fielding_previous_venue_altitude_missing` | I | I* | Carried-forward audited core |
| 130 | `fielding_previous_game_was_home` | I | I* | Carried-forward audited core |
| 131 | `fielding_previous_game_was_away` | I | I* | Carried-forward audited core |
| 132 | `fielding_previous_game_start_missing` | I | I* | Carried-forward audited core |
| 133 | `fielding_previous_game_missing` | I | I* | Carried-forward audited core |
| 134 | `fielding_previous_game_innings_missing` | I | I* | Carried-forward audited core |
| 135 | `fielding_previous_game_end_time_missing` | I | I* | Carried-forward audited core |
| 136 | `fielding_previous_game_end_missing` | I | I* | Carried-forward audited core |
| 137 | `fielding_previous_game_duration_missing` | I | I* | Carried-forward audited core |
| 138 | `fielding_pregame_temperature_missing` | I | I* | Carried-forward audited core |
| 139 | `fielding_played_yesterday` | I | I* | Carried-forward audited core |
| 140 | `fielding_played_two_days_ago` | I | I* | Carried-forward audited core |
| 141 | `fielding_overnight_travel_proxy` | I | I* | Carried-forward audited core |
| 142 | `fielding_morning_body_clock_game` | I | I* | Carried-forward audited core |
| 143 | `fielding_long_rest_indicator` | I | I* | Carried-forward audited core |
| 144 | `fielding_local_body_clock_offset_hours` | N | I* | Required-complete domain/rejection guard |
| 145 | `fielding_late_start_after_westward_travel` | I | I* | Carried-forward audited core |
| 146 | `fielding_interleague_game` | I | I* | Carried-forward audited core |
| 147 | `fielding_home_x_weekend` | N | I* | Deterministic home/calendar recomputation |
| 148 | `fielding_home_x_holiday` | X | X | Approved exclusions |
| 149 | `fielding_home_x_friday_night` | N | I* | Deterministic home/calendar recomputation |
| 150 | `fielding_home_stand_game_number` | I | I* | Carried-forward audited core |
| 151 | `fielding_holiday_calendar_missing` | X | X | Approved exclusions |
| 152 | `fielding_games_last_7_days` | I | I* | Carried-forward audited core |
| 153 | `fielding_games_last_3_days` | I | I* | Carried-forward audited core |
| 154 | `fielding_first_game_of_road_trip` | I | I* | Carried-forward audited core |
| 155 | `fielding_early_start_after_eastward_travel` | I | I* | Carried-forward audited core |
| 156 | `fielding_doubleheader_yesterday` | I | I* | Carried-forward audited core |
| 157 | `fielding_doubleheader_x_short_rest` | X | X | Approved exclusions |
| 158 | `fielding_doubleheader_today` | X | X | Approved exclusions |
| 159 | `fielding_division_game` | I | I* | Carried-forward audited core |
| 160 | `fielding_current_venue_timezone_missing` | I | I* | Carried-forward audited core |
| 161 | `fielding_current_venue_coordinates_missing` | I | I* | Carried-forward audited core |
| 162 | `fielding_current_venue_altitude_missing` | I | I* | Carried-forward audited core |
| 163 | `fielding_current_start_missing` | I | I* | Carried-forward audited core |
| 164 | `fielding_consecutive_road_games` | I | I* | Carried-forward audited core |
| 165 | `fielding_consecutive_game_days` | I | I* | Carried-forward audited core |
| 166 | `fielding_circadian_morning_component` | I | I* | Carried-forward audited core |
| 167 | `fielding_circadian_late_west_component` | I | I* | Carried-forward audited core |
| 168 | `fielding_circadian_early_east_component` | I | I* | Carried-forward audited core |
| 169 | `fielding_circadian_body_clock_component` | N | I* | Required-complete domain/rejection guard |
| 170 | `day_of_week_sin` | I | I* | Carried-forward audited core |
| 171 | `day_of_week_cos` | I | I* | Carried-forward audited core |
| 172 | `context_top_bottom` | I | I* | Carried-forward audited core |
| 173 | `context_outs_before` | I | I* | Carried-forward audited core |
| 174 | `context_inning` | I | I* | Carried-forward audited core |
| 175 | `context_batting_score_diff_before` | I | I* | Carried-forward audited core |
| 176 | `context_base_mask_before` | I | I* | Carried-forward audited core |
| 177 | `batting_venue_coordinate_missing` | I | I* | Carried-forward audited core |
| 178 | `batting_travel_path_missing` | I | I* | Carried-forward audited core |
| 179 | `batting_travel_distance_last_7_days` | N | I* | Required-complete domain/rejection guard |
| 180 | `batting_travel_distance_last_3_days` | N | I* | Required-complete domain/rejection guard |
| 181 | `batting_time_zone_missing` | I | I* | Carried-forward audited core |
| 182 | `batting_team_home_timezone_missing` | I | I* | Carried-forward audited core |
| 183 | `batting_team_alignment_missing` | I | I* | Carried-forward audited core |
| 184 | `batting_start_hour_in_team_home_time_zone` | N | I* | Required-complete domain/rejection guard |
| 185 | `batting_short_rest_indicator` | I | I* | Carried-forward audited core |
| 186 | `batting_series_rematch_indicator` | I | I* | Carried-forward audited core |
| 187 | `batting_same_league_game` | I | I* | Carried-forward audited core |
| 188 | `batting_same_division` | I | I* | Carried-forward audited core |
| 189 | `batting_road_trip_game_number` | I | I* | Carried-forward audited core |
| 190 | `batting_returned_home_after_road_trip` | I | I* | Carried-forward audited core |
| 191 | `batting_repeat_opponent_within_7_days` | I → N | I* | Newly exposed count-to-Boolean repair |
| 192 | `batting_repeat_opponent_within_14_days` | I → N | I* | Newly exposed count-to-Boolean repair |
| 193 | `batting_recent_bullpen_workload_missing` | I | I* | Carried-forward audited core |
| 194 | `batting_previous_venue_timezone_missing` | I | I* | Carried-forward audited core |
| 195 | `batting_previous_venue_coordinates_missing` | I | I* | Carried-forward audited core |
| 196 | `batting_previous_venue_altitude_missing` | I | I* | Carried-forward audited core |
| 197 | `batting_previous_game_was_home` | I | I* | Carried-forward audited core |
| 198 | `batting_previous_game_was_away` | I | I* | Carried-forward audited core |
| 199 | `batting_previous_game_start_missing` | I | I* | Carried-forward audited core |
| 200 | `batting_previous_game_missing` | I | I* | Carried-forward audited core |
| 201 | `batting_previous_game_innings_missing` | I | I* | Carried-forward audited core |
| 202 | `batting_previous_game_end_time_missing` | I | I* | Carried-forward audited core |
| 203 | `batting_previous_game_end_missing` | I | I* | Carried-forward audited core |
| 204 | `batting_previous_game_duration_missing` | I | I* | Carried-forward audited core |
| 205 | `batting_pregame_temperature_missing` | I | I* | Carried-forward audited core |
| 206 | `batting_played_yesterday` | I | I* | Carried-forward audited core |
| 207 | `batting_played_two_days_ago` | I | I* | Carried-forward audited core |
| 208 | `batting_overnight_travel_proxy` | I | I* | Carried-forward audited core |
| 209 | `batting_morning_body_clock_game` | I | I* | Carried-forward audited core |
| 210 | `batting_long_rest_indicator` | I | I* | Carried-forward audited core |
| 211 | `batting_local_body_clock_offset_hours` | N | I* | Required-complete domain/rejection guard |
| 212 | `batting_late_start_after_westward_travel` | I | I* | Carried-forward audited core |
| 213 | `batting_interleague_game` | I | I* | Carried-forward audited core |
| 214 | `batting_home_x_weekend` | N | I* | Deterministic home/calendar recomputation |
| 215 | `batting_home_x_holiday` | X | X | Approved exclusions |
| 216 | `batting_home_x_friday_night` | N | I* | Deterministic home/calendar recomputation |
| 217 | `batting_home_stand_game_number` | I | I* | Carried-forward audited core |
| 218 | `batting_holiday_calendar_missing` | X | X | Approved exclusions |
| 219 | `batting_games_last_7_days` | I | I* | Carried-forward audited core |
| 220 | `batting_games_last_3_days` | I | I* | Carried-forward audited core |
| 221 | `batting_first_game_of_road_trip` | I | I* | Carried-forward audited core |
| 222 | `batting_early_start_after_eastward_travel` | I | I* | Carried-forward audited core |
| 223 | `batting_doubleheader_yesterday` | I | I* | Carried-forward audited core |
| 224 | `batting_doubleheader_x_short_rest` | X | X | Approved exclusions |
| 225 | `batting_doubleheader_today` | X | X | Approved exclusions |
| 226 | `batting_division_game` | I | I* | Carried-forward audited core |
| 227 | `batting_current_venue_timezone_missing` | I | I* | Carried-forward audited core |
| 228 | `batting_current_venue_coordinates_missing` | I | I* | Carried-forward audited core |
| 229 | `batting_current_venue_altitude_missing` | I | I* | Carried-forward audited core |
| 230 | `batting_current_start_missing` | I | I* | Carried-forward audited core |
| 231 | `batting_consecutive_road_games` | I | I* | Carried-forward audited core |
| 232 | `batting_consecutive_game_days` | I | I* | Carried-forward audited core |
| 233 | `batting_circadian_morning_component` | I | I* | Carried-forward audited core |
| 234 | `batting_circadian_late_west_component` | I | I* | Carried-forward audited core |
| 235 | `batting_circadian_early_east_component` | I | I* | Carried-forward audited core |
| 236 | `batting_circadian_body_clock_component` | N | I* | Required-complete domain/rejection guard |
| 237 | `batter_prior_pa_count` | I | I* | Carried-forward audited core |
| 238 | `batter_prior_missing` | I | I* | Carried-forward audited core |
| 239 | `batter_last100_whiff_missing` | I | I* | Carried-forward audited core |
| 240 | `batter_last100_pa_count` | I | I* | Carried-forward audited core |
| 241 | `batter_last100_insufficient` | I | I* | Carried-forward audited core |

## Report boundary

This report was assembled from existing normalized audit evidence and local implementation metadata. No database query, feature/target scan, model fit, scoring, registration, adoption or Final OOT action was performed to create it. Root-agent diagnostic findings are identified separately from recorded training evidence. Existing user artifacts, including the original audit and unrelated project-management handoff, are unchanged.
