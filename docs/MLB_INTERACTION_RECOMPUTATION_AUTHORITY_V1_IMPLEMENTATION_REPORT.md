# MLB_INTERACTION_RECOMPUTATION_AUTHORITY_V1 implementation report

## 1. Starting worktree, branch, and HEAD

The verified starting checkout was `C:\Users\james\asp-model-studio`, branch `codex/mlb-governed-prior-engine-v1`, at `33cd85fa5074efeec3077036baea9c8b2ef86bdf`. Its only visible untracked user files were `ASP_MLB_Feature_Treatment_Specification.xlsx` and `docs/PHASE_7D3_CODEX_FINAL_SILVER_READINESS_REPORT.md`; neither was staged, moved, overwritten, or modified. The implementation used the separate physical worktree `C:\Users\james\asp-model-studio\.tmp\asp-interaction-authority-v1` on new branch `codex/mlb-interaction-authority-v1`, isolating it from the original checkout. After an overlapping-edit risk was identified, subagents were stopped from editing this worktree; the primary agent alone made repository edits and subsequent subagent work was read-only review. Repository and live migration heads were both migration `0038` (38 applied migrations). Live persistence was `C:\Users\james\asp-model-studio\.runtime\asp-model-studio\persistence\asp_model_studio.db`.

## 2. Final branch and HEAD

The final implementation branch is `codex/mlb-interaction-authority-v1`. The code-complete HEAD at report evidence freeze is `a48851e0e3e13642c254fefa09221effc1cfcb08`; the required documentation-only commit follows this evidence freeze and is reported with its exact final hash in the delivery response. The original checkout remains on `codex/mlb-governed-prior-engine-v1` at `33cd85fa5074efeec3077036baea9c8b2ef86bdf`.

## 3. Main HEAD

`main` remains unchanged at `924db29511f93909f9d785855bfa056775443690`.

## 4. Project and Gold identities

- Project: `asp-mtlozhdx` — `MLB 2026 Current-Data Challenger v2 — Deliberate Development`.
- Active modeling dataset: `asp.mlb.statcast.current-pa.v1`, version `asp.mlb.statcast.current-pa.v1:partition-authority-sha256:6e134d8726587ad88d0807effb6e6b12ad39f39b99acb7f523ae6ae98155df34`, activation revision 1.
- Registration: `sports-dataset-current-statcast-03ca6dab30e760b2`; source manifest SHA `03ca6dab30e760b2b86b65308090c2d358a67127cc34dfde7a75fc198c3ba84c`.
- Current Gold: `gold-table:gold_mlb_current_pa_v1`; manifest SHA `67de02ce19738b29953341151640fb69244b764b0e532b687ab6bacedbb3f758`.
- Contextual Gold: `gold-table:gold_mlb_current_pa_context_v2`; manifest SHA `4c228116951a3505d6a5d955f00cd2b92b35b1ccb85c7c69d11d77828485320e`.
- Feature-inventory SHA: `1499242d0a4ef7423d821cac2924facb20ec99eb2af1ea4505cacf1bce2d38d1`; review digest `af3e10a6d62537a57c2513a9ed6e96d44e5c7d5a6fdcf845a9fcb097ed8afe41`.
- Development boundary: 683,662 rows, 2023-03-30 through 2026-08-13. Final OOT identity: 14,067 rows, 2026-08-14 through 2026-08-27, `LOCKED_UNOPENED`.

## 5. Treatment DRAFT before

The starting immutable combined DRAFT was `stage3-feature-treatment-spec-22e4a89375cf43c58febe23f94f727bf`, version 3, manifest SHA `2cc3aaecbd8663a932f5088845e76e15b2f5461bc918fe17254684a92048cafe`. It linked outlier DRAFT `stage3-outlier-policy-262359558da4445193d6a115af4ba5cd` and missing-value DRAFT `stage3-imputation-policy-81821f7e4e0b426ca6665239aea36dae`. Its blocker ledger was 13 prior + 8 interaction + 2 semantic/calendar + 14 rivalry = 37, with `canAdopt=false`.

## 6. Exact eight blocker inventory

The eight rows below were enumerated from persisted v3 records whose exact scientific recommendation was `RECOMPUTE_AFTER_PARENT_TREATMENT`; no `_x_` name-pattern selection was used. Every backend identity equals its exact feature name, every family is `INTERACTION`, every pre-change executable status was `BLOCKED`, and every exact pre-change reason was `The current model pipeline does not register parent-first interaction recomputation.` Source lineage was exact team-game schedule/venue authority plus strictly prior-date completed-game context, with same-date history excluded.

1. `fielding_road_trip_length_x_travel`
2. `fielding_prior_extra_innings_x_travel`
3. `fielding_long_travel_x_short_rest`
4. `fielding_eastward_travel_x_early_start`
5. `batting_road_trip_length_x_travel`
6. `batting_prior_extra_innings_x_travel`
7. `batting_long_travel_x_short_rest`
8. `batting_eastward_travel_x_early_start`

## 7. Exact formulas and parents

These are the authority's exact explicit parent-level formula registrations, verified to be semantically identical to the existing inline materializer expressions in `server/sports_current_statcast/contextual_features.py::build_team_game_context` and versioned under `MLB_TEAM_GAME_CONTEXT_FEATURES_V1`; no formula was inferred from a feature name. Parent order is significant and bound into the checksum.

1. `fielding_road_trip_length_x_travel = fielding_road_trip_game_number * fielding_travel_distance_miles`. Ordered parent authorities: `MLB_FEATURE_TREATMENT_PARENT_V1:fielding_road_trip_game_number:sha256:d4061492a18cfa9bf2f9114b04ec0328f94ea16ff82b19581131f350f29470bc`, then `MLB_FEATURE_TREATMENT_PARENT_V1:fielding_travel_distance_miles:sha256:e341427ebddfd8df825c9b26f38e39e9dab8f36208f22408fe1e02ae665e7ba6`.
2. `fielding_prior_extra_innings_x_travel = fielding_previous_game_extra_innings * fielding_travel_distance_miles`. Ordered parent authorities: `MLB_FEATURE_TREATMENT_PARENT_V1:fielding_previous_game_extra_innings:sha256:259fcf4f9e9bbc5e2cfb1995dd1c770c68bd0b47e61d5e02eabcd7f5615c7f0d`, then `MLB_FEATURE_TREATMENT_PARENT_V1:fielding_travel_distance_miles:sha256:e341427ebddfd8df825c9b26f38e39e9dab8f36208f22408fe1e02ae665e7ba6`.
3. `fielding_long_travel_x_short_rest = int(fielding_travel_distance_miles >= 1500) * fielding_short_rest_indicator`. Ordered parent authorities: `MLB_FEATURE_TREATMENT_PARENT_V1:fielding_travel_distance_miles:sha256:e341427ebddfd8df825c9b26f38e39e9dab8f36208f22408fe1e02ae665e7ba6`, then `MLB_FEATURE_TREATMENT_PARENT_V1:fielding_short_rest_indicator:sha256:7132d4ec0c452649d7a2952ea147b3d96473059868894ee92e80e2916f0e9f93`.
4. `fielding_eastward_travel_x_early_start = fielding_eastward_time_zone_change_hours * fielding_early_start_after_eastward_travel`. Ordered parent authorities: `MLB_FEATURE_TREATMENT_PARENT_V1:fielding_eastward_time_zone_change_hours:sha256:3fe3bdea2c654979bf40c33dfb15ba3f332671501b7e952f078cbd7505ce5a3e`, then `MLB_FEATURE_TREATMENT_PARENT_V1:fielding_early_start_after_eastward_travel:sha256:e4507c552f3809a9c07e7ec1366948f787aa48da3d61f50ad5c5297dd7f9d9e2`.
5. `batting_road_trip_length_x_travel = batting_road_trip_game_number * batting_travel_distance_miles`. Ordered parent authorities: `MLB_FEATURE_TREATMENT_PARENT_V1:batting_road_trip_game_number:sha256:afd46dc646dfd3a3e4cd52d4f5ebc5f2e70cae4e6b16b87177ddaf3100390cdf`, then `MLB_FEATURE_TREATMENT_PARENT_V1:batting_travel_distance_miles:sha256:9815a529d8a790903f1b386771f2390871268cb2388f178dd41e9e5a2eba5ece`.
6. `batting_prior_extra_innings_x_travel = batting_previous_game_extra_innings * batting_travel_distance_miles`. Ordered parent authorities: `MLB_FEATURE_TREATMENT_PARENT_V1:batting_previous_game_extra_innings:sha256:6bcbfb234079cf80e3ce59deb250e542f2ab202a86a16598431e4a7842a2a03d`, then `MLB_FEATURE_TREATMENT_PARENT_V1:batting_travel_distance_miles:sha256:9815a529d8a790903f1b386771f2390871268cb2388f178dd41e9e5a2eba5ece`.
7. `batting_long_travel_x_short_rest = int(batting_travel_distance_miles >= 1500) * batting_short_rest_indicator`. Ordered parent authorities: `MLB_FEATURE_TREATMENT_PARENT_V1:batting_travel_distance_miles:sha256:9815a529d8a790903f1b386771f2390871268cb2388f178dd41e9e5a2eba5ece`, then `MLB_FEATURE_TREATMENT_PARENT_V1:batting_short_rest_indicator:sha256:978f3a05c160797bafef3869d26a9d3043aa0a6c56b053a2671498764ae89b95`.
8. `batting_eastward_travel_x_early_start = batting_eastward_time_zone_change_hours * batting_early_start_after_eastward_travel`. Ordered parent authorities: `MLB_FEATURE_TREATMENT_PARENT_V1:batting_eastward_time_zone_change_hours:sha256:cee099092263f452d8c9889c9f4bfc1bd9f7b1884f8838f39c7bd81b17701879`, then `MLB_FEATURE_TREATMENT_PARENT_V1:batting_early_start_after_eastward_travel:sha256:cab74d15116012d9b73cababb2c09c90f09a4228aac14efdc6142eaa5fa3c716`.

Every row is `READY_GOVERNED_INTERACTION_V1`, selectable, PIT `PASS`, and fold-local `PASS`. Parent contracts bind data type, hard domain, missing/outlier policy, source status, forecast availability, paired indicators, and source/computation-failure propagation. Unknown Boolean states fail closed and are never coerced to false or zero; structural zero is applied only under the registered true-no-history rule. Ordinary valid numeric zeros and the registered long-travel predicate may still yield a natural zero.

## 8. Operation-order authority

The one immutable order is:

1. `RESOLVE_SOURCE_IDENTITY_AND_POINT_IN_TIME_ELIGIBILITY`
2. `VALIDATE_PARENT_HARD_SEMANTIC_DOMAINS`
3. `APPLY_FROZEN_TRAINING_FOLD_PARENT_MISSING_TREATMENT`
4. `APPLY_PARENT_PRIOR_OR_STRUCTURAL_ZERO_RULE`
5. `RECOMPUTE_REGISTERED_INTERACTION_DETERMINISTICALLY`
6. `VALIDATE_DERIVED_INTERACTION_DOMAIN`
7. `APPLY_MODEL_FAMILY_ENCODING_OR_TRAINING_ONLY_SCALING`

The compiler prohibits independent interaction imputation and independent interaction capping. Tree paths preserve governed native missing values; dense paths use frozen training-fold contextual medians for eligible continuous parents. Optional scaling is downstream and training-only. Explicit `<parent>__missing_reason` columns are preserved. Missing source becomes `SOURCE_UNAVAILABLE`; malformed, invalid, or infinite present values become `COMPUTATION_FAILURE`; neither is converted into cold start or zero. Validation, later rows, future seasons, current-row outcomes, and final OOT cannot fit or change an earlier authority or interaction value.

## 9. Interaction authority ID and checksum

- Authority ID: `MLB_INTERACTION_RECOMPUTATION_AUTHORITY_V1:sha256:8b15c052356565e2a0f5cfea00d0d565f47b64b4838d028008a2d895bb2d41e3`.
- Authority checksum: `8b15c052356565e2a0f5cfea00d0d565f47b64b4838d028008a2d895bb2d41e3`.
- Configuration checksum: `96a411fda5a582d8ef2e5e970e6d442027d9d72e64b77d5bfa6248647c48169f`.
- Immutable authority-object SHA: `bce4d406e5619a0f9df3dabe1e483df4ec3f877a9e1249275c0375a085bcdeed` (40,929 bytes).
- Compiler: `MLB_FEATURE_TREATMENT_COMPILER_V1`, SHA `5bc190715287b87d302c6ca81509bd94a26037cb6baa008d5b72571742a58abc`.
- Formula-source SHA: `b7fa3e18154876618f7d94c08ba8bc149c549b89a43ca19dd0129f7bdadf4509`.

Formula, parent identity/order, parent-treatment identity, propagation, execution order, model-family resolution, project, Gold, inventory, treatment source, or compiler changes alter content identity.

## 10. Interaction blockers cleared

All eight persisted `RECOMPUTE_AFTER_PARENT_TREATMENT` blockers listed in section 6 were cleared into the exact governed contracts listed in section 7. The final ledger records `interactionBlockersBefore=8`, `interactionBlockersCleared=8`, and `readyGovernedInteraction=8`.

## 11. Interaction blockers remaining

`interactionBlockersRemaining=0` and the authority has `blockedFeatureCount=0`. No row was forced ready: each has an exact literal formula, ordered registered parents, PIT proof, and fold-local execution.

## 12. Exact blocked reasons

The 29 remaining blockers are unrelated to the resolved interaction class.

- `pitcher_whip`: WHIP requires prior IPouts plus BB and H; BFP is not its denominator and those sufficient statistics are not materialized in Current Gold.
- `pitcher_era9`: ERA9 requires prior IPouts and ER; BFP is not its denominator and those sufficient statistics are not materialized in Current Gold.
- `pitcher_gs_per_g`: GS/G requires exact prior games and games-started counts; BFP is not a valid opportunity denominator and neither count is materialized in Current Gold.
- `batter_slg`: SLG requires exact at-bats and total-base components; prior PA is not its denominator and the sufficient statistics are not materialized in Current Gold.
- `batter_obp`: OBP requires AB+BB+HBP+SF opportunities; prior PA also includes sacrifice hits and cannot be substituted for the unmaterialized denominator.
- `batter_avg`: AVG requires exact at-bats and hits; prior PA is not its denominator and at-bats are not materialized in Current Gold.
- `pitcher_last250_avg_fastball_velocity`: Velocity shrinkage requires eligible-fastball count and within-window variance; the materialized BF count is not a velocity observation count.
- `pitcher_last250_whiff_rate`: Pitcher whiff rate requires the exact classifiable-swing count; BF count is not the denominator and swing count is not materialized in Current Gold.
- `pitcher_last250_offspeed_usage`, `pitcher_last250_fastball_usage`, and `pitcher_last250_breaking_usage`: Pitch usage requires the exact all-pitch opportunity count; BF count is not the denominator and pitch count is not materialized in Current Gold.
- `batter_last100_whiff_rate`: Batter whiff rate requires the exact classifiable-swing count; PA count is not the denominator and swing count is not materialized in Current Gold.
- `batter_last100_contact_rate`: Batter contact rate requires the exact classifiable-swing count; PA count is not the denominator and swing count is not materialized in Current Gold.
- `doubleheader_game_number`: Schedule authority `MLB_CURRENT_STATCAST_SCHEDULE_AUTHORITY_V1` does not preserve original pregame knowledge timestamps or an independent `{0,1,2}` doubleheader-sequence invariant tied to scheduled start order.
- `holiday_name`: `US_CA_ON_BASEBALL_CALENDAR_V1` is embedded code rather than a separately registered, sourced, effective-dated holiday calendar; null currently cannot prove `NONE` rather than `UNKNOWN_HOLIDAY` for every venue region.
- Each of the 14 rivalry rows: The accepted contextual inventory contains this rivalry-authority field, but the reviewed workbook contains no recommendation for it. All therefore remain `BLOCKED_NO_APPROVED_EFFECTIVE_DATED_MAPPING`, nonselectable, and treatment-free.

## 13. doubleheader decision and evidence

Decision: retain `doubleheader_game_number` as `BLOCKED_POINT_IN_TIME_UNPROVEN`; cleared 0, remaining 1. Exact source is `MLB_CURRENT_STATCAST_SCHEDULE_AUTHORITY_V1`, SHA `44c43a48dda5895dcc19417a1c51b18ccdaed9dd83b3c1b8d50826e42be69c4d`. The source lacks original pregame knowledge timestamps and an independently registered `{0,1,2}` scheduled-order invariant, so it cannot prove 0 = verified non-doubleheader, 1 = verified first game, and 2 = verified second game without postgame ordering risk. Resolution is `HOLD_UNTIL_PREGAME_SCHEDULE_SEQUENCE_AUTHORITY_IS_REGISTERED`; `MEDIAN_IMPUTATION` is explicitly forbidden.

## 14. holiday decision and evidence

Decision: retain `holiday_name` as `BLOCKED_CALENDAR_AUTHORITY_UNAVAILABLE`; cleared 0, remaining 1. Exact static source is `MLB_CONTEXT_STATIC_AUTHORITY_V1`, SHA `da9740dd90a161202d42ba18d3c89f2569e3711e33b48f86bf3bd0a8a6f2d56d`; embedded rules version is `US_CA_ON_BASEBALL_CALENDAR_V1`. Those rules are not a separately registered, sourced, effective-dated, venue-region and rights-governed calendar, and null cannot prove verified non-holiday. Resolution is `HOLD_UNTIL_EFFECTIVE_DATED_VENUE_REGION_CALENDAR_AUTHORITY_IS_REGISTERED`; `MODE_IMPUTATION` is explicitly forbidden.

## 15. Rivalry-field inventory and recommendations

The read-only audit found exactly 14 absent-from-workbook fields. All use research-only formula evidence from `MLB_TEAM_GAME_CONTEXT_FEATURES_V1_RESEARCH_ONLY_EVIDENCE`, proposed mapping `docs/MLB_RIVALRY_MAPPING_PROPOSAL_V1.json` SHA `5bd1ad26acacdc32a1ad9edb377c72559402e161a32278971e3d07748b588d74`, status `PROPOSED_NOT_APPROVED`, rights `OPERATIONAL_USE_NOT_ESTABLISHED`, no active use, no approved effective-dated PIT mapping, `selectable=false`, and recommendation `KEEP_HELD_CLOSED`.

| Side | Field | Formula evidence | Development missing / coverage | Duplicate or paired indicator |
|---|---|---|---:|---|
| Batting | `batting_rivalry_pair` | `None if mapping_missing else int({team_id, opponent_team_id} in approved_pairs)` | 100% / 0% | duplicates `batting_rivalry_game`; indicator `batting_rivalry_mapping_missing` |
| Batting | `batting_rivalry_game` | `rivalry_pair` | 100% / 0% | duplicates `batting_rivalry_pair`; indicator `batting_rivalry_mapping_missing` |
| Batting | `batting_home_rivalry_game` | `None if rivalry_pair is None else rivalry_pair * int(is_home)` | 100% / 0% | duplicates `batting_home_x_rivalry`; indicator `batting_rivalry_mapping_missing` |
| Batting | `batting_friday_night_home_rivalry` | `None if rivalry_pair is None else rivalry_pair * int(is_home) * int(local_day_of_week == FRIDAY) * int(local_start_hour >= 18)` | 100% / 0% | indicator `batting_rivalry_mapping_missing` |
| Batting | `batting_weekend_home_rivalry` | `None if rivalry_pair is None else rivalry_pair * int(is_home) * int(local_day_of_week in {SATURDAY, SUNDAY})` | 100% / 0% | indicator `batting_rivalry_mapping_missing` |
| Batting | `batting_home_x_rivalry` | `None if rivalry_pair is None else int(is_home) * rivalry_pair` | 100% / 0% | duplicates `batting_home_rivalry_game`; indicator `batting_rivalry_mapping_missing` |
| Batting | `batting_rivalry_mapping_missing` | `int(rivalry_mapping_authority_status != APPROVED)` | 0% / 100% | objective governance-state indicator |
| Fielding | `fielding_rivalry_pair` | `None if mapping_missing else int({team_id, opponent_team_id} in approved_pairs)` | 100% / 0% | duplicates `fielding_rivalry_game`; indicator `fielding_rivalry_mapping_missing` |
| Fielding | `fielding_rivalry_game` | `rivalry_pair` | 100% / 0% | duplicates `fielding_rivalry_pair`; indicator `fielding_rivalry_mapping_missing` |
| Fielding | `fielding_home_rivalry_game` | `None if rivalry_pair is None else rivalry_pair * int(is_home)` | 100% / 0% | duplicates `fielding_home_x_rivalry`; indicator `fielding_rivalry_mapping_missing` |
| Fielding | `fielding_friday_night_home_rivalry` | `None if rivalry_pair is None else rivalry_pair * int(is_home) * int(local_day_of_week == FRIDAY) * int(local_start_hour >= 18)` | 100% / 0% | indicator `fielding_rivalry_mapping_missing` |
| Fielding | `fielding_weekend_home_rivalry` | `None if rivalry_pair is None else rivalry_pair * int(is_home) * int(local_day_of_week in {SATURDAY, SUNDAY})` | 100% / 0% | indicator `fielding_rivalry_mapping_missing` |
| Fielding | `fielding_home_x_rivalry` | `None if rivalry_pair is None else int(is_home) * rivalry_pair` | 100% / 0% | duplicates `fielding_home_rivalry_game`; indicator `fielding_rivalry_mapping_missing` |
| Fielding | `fielding_rivalry_mapping_missing` | `int(rivalry_mapping_authority_status != APPROVED)` | 0% / 100% | objective governance-state indicator |

The 12 substantive constructs are subjective, overlap objective opponent context, and require a curated rivalry table. Season coverage is exactly 0% in 2023, 2024, 2025, and 2026. The two mapping-state indicators are objective but still held because no approved mapping exists; their season coverage is exactly 100% in each season. No rivalry label or treatment was invented.

## 16. New treatment DRAFT identity

The final immutable receipt is `stage3-feature-treatment-spec-c9efc460fee746ce93c7a646c164c116`, version 5, status `DRAFT`, prior receipt `stage3-feature-treatment-spec-d36db95e28b14846a776aecb6d2d0e12`. Its canonical compiled specification is `MLB_FEATURE_TREATMENT_SPEC_V1:sha256:625f9ca9704eebc036b377da0b7b1fa2f13a4587217001a071feda2637deddaf`; persisted `manifest_sha256` is `625f9ca9704eebc036b377da0b7b1fa2f13a4587217001a071feda2637deddaf`, source-content identity is `MLB_FEATURE_TREATMENT_SPEC_V1:sha256:cec8bbe0483ad9bff897ecc97e0af11d9785ad25d481bacac73247858e68699f`, and receipt content SHA is `f4afcb2d11e7d9975148974296fbb19469410766adc3e3632f0448e9d34091f8`.

It links outlier DRAFT `stage3-outlier-policy-88b8143ca03a4053892e325ee1e29d71` (checksum `e1588ef29292fa36b790fdbb3d377fb01dcf8e568364e1ae2475c3a5802364ab`) and missing DRAFT `stage3-imputation-policy-092c34f01a1544ad8983176b1c169617` (checksum `3ca54c970aad0d67abe182b2db0f99eb01a43a86a79f2f2f19756c5d3eb9934c`). The workbook SHA remains `0e2d5f2b0d495c941ae97fb84c216f0b5ccdfe904519db0acb616d1543a66679`.

An immutable v4 intermediate (`stage3-feature-treatment-spec-d36db95e28b14846a776aecb6d2d0e12`, manifest SHA `45a1bd8ddd2dfa636244604dfb588b7885ce297e51c72b70450e6f6b7f5283a7`, receipt content SHA `4cd1ea8c4c0f6984ef7432c86719c2c5ecf63bb0410d659e3f75735b05a56ed9`) was retained rather than rewritten. V5 was scientifically necessary: it added the correct paired `fielding_previous_game_missing` and `batting_previous_game_missing` indicators to the two short-rest parent contracts, changing those parent-treatment identities and moving the interaction authority from `MLB_INTERACTION_RECOMPUTATION_AUTHORITY_V1:sha256:dfd7f0897c065cf6c3218d3724ac4f407d5034710f9d75a77d8e4ffa7d4dcfb3` to the final `8b15c052…41e3` identity, with corresponding bound compiler/configuration changes. The final v5 was saved through the authenticated UI and immediately reapplied. Counts remained exactly 5 combined versions, 5 outlier versions, 5 imputation versions, one `DRAFT_CREATED`, and four `DRAFT_REVISED`, proving the second application created no duplicate.

## 17. Blocker counts before and after

Before: 13 prior + 8 interaction + 2 semantic/calendar + 14 rivalry = 37. After: 13 prior + 0 interaction + 2 semantic/calendar + 14 rivalry = 29. The arithmetic is evidence-derived, not hard-coded. The final execution summary also reports 240 workbook features, 14 additional held-closed backend fields, 219 total ready/selectable rows, and 29 user-review-required blockers.

## 18. canAdopt state

`canAdopt=false`. Both the UI and backend hold adoption closed while any of the 29 blockers remains, and feature-set registration rejects the newest pending combined DRAFT before mutation. No policy was adopted automatically or manually.

## 19. Prior-authority verification

Before and after authority ID/checksum are identical: `MLB_PLAYER_STATE_PRIOR_AUTHORITY_V1:sha256:a363331fc47083bf5aaac07c437f2998ea21650b78538d2a69e258851812ff43`. The final manifest still reports 24 prior-required fields, 11 `READY_GOVERNED_PRIOR_V1`, and the same 13 blocked fields/reasons in section 12. No role taxonomy, denominator, sufficient statistic, or prior output was fabricated.

## 20. Historical-artifact verification

Historical artifact `stage3-executable-artifact-11dc936dcf9d558fe3d8f0a179615b19` remains `EXECUTABLE_RESEARCH_ARTIFACT_MATERIALIZED`, `RESEARCH_CHALLENGER`, and not promoted. Its manifest independently rehashes to the unchanged SHA `58ddf83092c2e91fde4c61c35f16c8cc5a3702d3a4da8f9f9164f2eab5641f6b`, is still 36,207 bytes, and retains last-write UTC `2026-09-03T19:56:24.6985262Z`. Historical-artifact mutations: 0. The new authority was not attached retroactively.

## 21. Gold verification

Current Gold ID and SHA remain `gold-table:gold_mlb_current_pa_v1` and `67de02ce19738b29953341151640fb69244b764b0e532b687ab6bacedbb3f758` before and after. Activation revision remains 1. The authority audit records `goldMutations=0` and all treatment responses record no source/Gold mutation.

## 22. Final-OOT access count

Final OOT remained excluded before feature reads: authority `finalOot.accessCount=0`, performance receipt `finalOotRowsRead=0`, and registration query ledger totals are 0 audit rows, 0 OOT scopes, and 0 returned rows. The 14,067-row OOT identity was bound without opening, fitting, or transforming it.

## 23. Model activity counts

All prohibited activity counts are 0: predictive fits 0, scores 0, calibrations 0, promotions 0, game-scoring jobs 0, feature sets registered 0, Gold mutations 0. Project persistence independently contains 0 feature-set versions, models, model versions, run records, analytical runs, scoring runs, holdout exposures, PA research runs, PA candidates, and PA experiments.

## 24. Performance measurements

The implementation is `VECTORIZED_NUMPY_PANDAS_NO_ROW_LOOPS`. Final performance receipt SHA is `321bef73ed9ba387fd41f0c4f5ef293eaa0486f5548319cd6572cda58198190b` (3,540 bytes); scientific-evidence SHA is `76f241b16153a2f04f3f575c9cc3adba57ee84774a8ee97d14538b1fc7c41c4a` (7,909 bytes).

- Authority compilation: 352.979 ms; development scan: 256.062 ms.
- Full-development fit of parent preprocessing authorities: 21,703.383 ms; full-development transform: 20,677.892 ms over 683,662 rows.
- Fold 1: fit 3,854.090 ms; training+validation transform 6,958.062 ms.
- Fold 2: fit 7,501.218 ms; transform 10,371.867 ms.
- Fold 3: fit 10,732.545 ms; transform 13,615.833 ms.
- Fold 4: fit 14,356.152 ms; transform 17,157.897 ms.
- Fold 5: fit 18,132.426 ms; transform 20,315.700 ms.
- Peak RSS sampled at phase boundaries: 1,153,585,152 bytes. Input frame: 193,476,478 bytes; full transformed frame: 673,518,972 bytes.
- Authority artifact: 40,929 bytes. Predictive model fits during benchmark: 0; final-OOT rows read: 0.

## 25. Tests and exact results

- Relevant backend suite across interaction authority, treatment specification, Feature Engineering overlay, treatments, combined-treatment repository, and prior authority: 81 passed in 46.16 s.
- Final focused authority/specification rerun: 32 passed in 21.32 s; final authority-only rerun: 18 passed.
- Treatment Studio frontend regression: 18/18 passed after adding the authority-readiness mount-race guard.
- Feature/Split frontend regression: 14/14 passed.
- `npm run build:modeling` passed after the final UI fix; its `tsc -b` phase passed, Vite transformed 2,336 modules, and the production modeling bundle completed in 29.26 s. Only existing stale browser-metadata and large-chunk advisory warnings remained.
- Required evidence covers exact persisted enumeration rather than name inference; formulas and ordered parents; parent-first/frozen fold behavior; downstream scaling; no independent median/IQR; source/computation failures; Boolean unknowns; structural zero; validation/later/future/outcome isolation; independent numerical fixtures; deterministic compilation; checksum sensitivity; idempotent reapply; immutable prior/historical/Gold identities; zero OOT/model/registration/scoring activity; forbidden semantic imputations; rivalry nonselectability; DRAFT/adoption gates.
- `git diff --check` passed. No test-cache directories remain in the isolated worktree.

## 26. Browser acceptance

Acceptance used the authenticated exact project through isolated frontend/backend ports 5275/8102. The final v5—not the intermediate v4—was visible and checked.

- At 1920×1080, document client/scroll widths were 1905/1905 on Outliers, Missing Values, and Feature Engineering: no horizontal page overflow.
- At 1024×768, document client/scroll widths were 1009/1009 on all three views: no horizontal page overflow.
- Outliers showed `Policy v5`, exact manifest `625f9ca…ddaf`, no statistical detector, no treatment/blanket IQR capping, all 8 governed interactions, DRAFT identity, and disabled adoption.
- Missing Values showed parent-first contracts, separate source/computation failure and no-history states, 8 before/8 cleared/0 remaining interactions, 2 semantic holds, 13 prior holds, 14 rivalry holds, 29 total blockers, `Policy v5`, and disabled adoption. A mount-time placeholder-authority race found during this pass was fixed and regression-tested before acceptance was repeated.
- Feature Engineering showed the exact `MLB_INTERACTION_RECOMPUTATION_AUTHORITY_V1:sha256:8b15c052…41e3` identity, eight formula/ordered-parent/two-parent-authority/PIT/fold-local cards, zero registered sets, zero fitted models, and a disabled registration button.
- The isolated 5275/8102 listeners were stopped after acceptance. Protected existing listeners 5274 (PID 33060) and 8101 (PID 44536) remained listening.

## 27. Files changed

Fourteen repository files comprise the final delivery (13 implementation/test files plus this report):

- `scripts/evaluate_mlb_interaction_authority.py` (new)
- `server/sports_current_statcast/stage3_interaction_recomputation_authority.py` (new)
- `server/sports_current_statcast/stage3_feature_engineering.py`
- `server/sports_current_statcast/stage3_feature_treatment_spec.py`
- `src/sports/cockpit/ProjectBoundFeatureEngineering.tsx`
- `src/sports/cockpit/TreatmentStudioShell.tsx`
- `src/sports/cockpit/projectFeatureSplitApi.ts`
- `src/sports/cockpit/projectTreatmentApi.ts`
- `tests/sports_stage3_interaction_recomputation_authority_test.py` (new)
- `tests/sports_stage3_feature_engineering_test.py`
- `tests/sports_stage3_feature_treatment_spec_test.py`
- `tests/sportsStage3FeatureSplitFrontend.test.mjs`
- `tests/sportsStage3TreatmentStudiosFrontend.test.mjs`
- `docs/MLB_INTERACTION_RECOMPUTATION_AUTHORITY_V1_IMPLEMENTATION_REPORT.md` (new)

Before this report, the implementation diff from the starting HEAD was 3,998 insertions and 36 deletions across 13 files. The protected workbook still hashes to `0e2d5f2b0d495c941ae97fb84c216f0b5ccdfe904519db0acb616d1543a66679`; the protected prior report still hashes to `72c5a70d12a61f04ffdebfb2d3a5a11b17236b29abd0d9d36fd035ddd12593a6`.

## 28. Commits

Logical local commits at evidence freeze:

1. `05a81e5` — `feat(stage3): add governed interaction recomputation authority`
2. `e89235b` — `feat(stage3): integrate interaction treatment draft`
3. `ce4b718` — `feat(ui): expose governed interaction authority`
4. `bd7c44e` — `test(stage3): prove interaction lineage and leakage isolation`
5. `a48851e` — `fix(ui): wait for treatment authority before loading`
6. Documentation-only commit — `docs: record interaction authority implementation` (exact resulting hash is reported in the delivery response).

No semantic-field commit was created because neither semantic source met the required authority standard.

## 29. Pushes

Pushes: 0. Nothing was pushed, no remote branch was changed, and `main` was not modified.

## 30. Remaining decisions for James

James must decide whether to commission and approve: (1) a pregame-knowledge-timestamped canonical schedule authority with an independent scheduled-order `{0,1,2}` doubleheader invariant; (2) a sourced, effective-dated, venue-region and rights-cleared holiday calendar; (3) registration of the exact sufficient statistics needed by the 13 blocked prior features; and (4) an objective, rights-cleared, effective-dated rivalry mapping or permanent removal of those 14 research-only candidates. Only after those authorities resolve all blockers should James review a new immutable DRAFT and explicitly adopt it. Model fitting, feature-set registration, final-OOT opening, scoring, calibration, promotion, and game scoring remain separate future decisions.
