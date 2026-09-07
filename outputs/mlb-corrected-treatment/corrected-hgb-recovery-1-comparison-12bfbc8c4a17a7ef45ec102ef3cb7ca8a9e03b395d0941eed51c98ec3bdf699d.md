# Corrected MLB treatment — bounded HGB comparison

Status: `COMPLETE`. Study `cb835f9be3d66e49d2681e0af25dfff9275e0e42faff4db8fada229f3e1015d2`.

Treatment V18; 273 source/derived predictors from 218 original source features. Exactly one HGB configuration completed all five chronological fits.

Registered Development remains 683,662 PAs. The frozen, outcome-independent `V1_KNOWN_ZERO_PRIOR_PA_UNSUPPORTED_HISTORY_STATE` policy quarantined 56 Development PAs, including 51 V14 OOF PAs. They were not imputed or relabeled as cold starts. No source rows were deleted.

Original V14 OOF result: 1.474542677496 log loss on 501,590 PAs. Corrected original OOF result: 1.474589538657 on 501,539 PAs. The table below compares both models only on the same 501,539 observations.

| Matched OOF metric | V14 baseline | Corrected | Corrected − V14 |
| --- | ---: | ---: | ---: |
| multiclassLogLoss | 1.474558302223 | 1.474589538657 | 0.000031236434 |
| summedBrier | 0.703052769842 | 0.703065382852 | 0.000012613010 |
| macroOvrRocAuc | 0.577313970537 | 0.576922795089 | -0.000391175448 |
| ece | 0.004687402244 | 0.004589942163 | -0.000097460081 |

The exact 218-source feature order is preserved. HGB estimator native workers: V14 4; corrected 4. Full resource metadata and baseline/current batch scheduling are frozen separately in JSON; identical batch scheduling is not assumed.

Paired game-clustered log-loss difference: 0.000031236434; 95% CI [-0.000211973146, 0.000281453522]. 501,539 matched PAs; 6,664 game clusters; 2,000 resamples, seed 20260907.

Metrics and uncertainty use pooled PA weighting. Training prefixes overlap; reported aggregate treatment-change counts use the disjoint validation folds only.

| Fold | Validation rows | V14 log loss | Corrected log loss | Difference |
| --- | ---: | ---: | ---: | ---: |
| 1 | 99,780 | 1.480076247083 | 1.480316701663 | 0.000240454580 |
| 2 | 100,267 | 1.480138732619 | 1.480088514278 | -0.000050218341 |
| 3 | 99,926 | 1.466775460974 | 1.466517956912 | -0.000257504062 |
| 4 | 100,302 | 1.474877231020 | 1.475087645997 | 0.000210414977 |
| 5 | 101,264 | 1.470959841229 | 1.470973027375 | 0.000013186146 |

| Predefined subgroup | PAs | Games | V14 log loss | Corrected log loss |
| --- | ---: | ---: | ---: | ---: |
| BATTER_TRUE_COLD_START | 37,828 | 4,950 | 1.467846963424 | 1.468556158310 |
| PITCHER_TRUE_COLD_START | 49,629 | 3,527 | 1.489700701609 | 1.490401278885 |
| EITHER_PLAYER_TRUE_COLD_START | 83,174 | 5,734 | 1.480376333025 | 1.481061257527 |
| BATTING_NO_PRIOR_GAME | 3,385 | 47 | 1.475871752238 | 1.480644146623 |
| FIELDING_NO_PRIOR_GAME | 3,386 | 47 | 1.479516794182 | 1.484833953938 |
| EITHER_TEAM_NO_PRIOR_GAME | 3,535 | 47 | 1.477912402361 | 1.482913992615 |

Full per-class AUC/Brier/calibration, confidence reliability bands, subgroup intervals, original-population metrics, and coverage are preserved in the adjacent JSON report.

## Treatment branches and reproducibility

Raw-source→successor counts below are not V14 model-input comparisons: source NULL remaining NULL has zero raw change but differs from V14's median-imputation path.

| Semantic feature with raw-source→successor changes | Raw-source→successor changed PAs |
| --- | ---: |
| batter_log1p_pa | 37,828 |
| batting_cross_country_travel | 3,385 |
| batting_crossed_time_zone | 3,385 |
| batting_crossed_two_or_more_time_zones | 3,385 |
| batting_previous_game_extra_innings | 3,385 |
| batting_repeat_opponent_within_14_days | 201,243 |
| batting_repeat_opponent_within_7_days | 190,670 |
| fielding_cross_country_travel | 3,386 |
| fielding_crossed_time_zone | 3,386 |
| fielding_crossed_two_or_more_time_zones | 3,386 |
| fielding_previous_game_extra_innings | 3,386 |
| fielding_repeat_opponent_within_14_days | 201,243 |
| fielding_repeat_opponent_within_7_days | 190,670 |
| pitcher_log1p_bfp | 49,629 |

| Native-missing feature vs recorded V14 median path | Corrected native-NULL PAs | Proven representation-change PAs |
| --- | ---: | ---: |
| batting_circadian_disruption_score | 3,385 | 3,385 |
| batting_circadian_short_recovery_component | 3,385 | 3,385 |
| batting_circadian_timezone_component | 3,385 | 3,385 |
| batting_days_since_previous_game | 3,385 | 3,385 |
| batting_eastward_time_zone_change_hours | 3,385 | 3,385 |
| batting_eastward_travel_x_early_start | 3,385 | 3,385 |
| batting_hours_since_previous_game_start | 3,385 | 3,385 |
| batting_long_travel_x_short_rest | 3,385 | 3,385 |
| batting_previous_game_innings | 3,385 | 3,385 |
| batting_prior_extra_innings_x_travel | 3,385 | 3,385 |
| batting_road_trip_length_x_travel | 3,385 | 3,385 |
| batting_start_hour_in_previous_venue_time_zone | 3,385 | 3,385 |
| batting_time_zone_change_hours | 3,385 | 3,385 |
| batting_travel_distance_miles | 3,385 | 3,385 |
| batting_westward_time_zone_change_hours | 3,385 | 3,385 |
| fielding_circadian_disruption_score | 3,386 | 3,386 |
| fielding_circadian_short_recovery_component | 3,386 | 3,386 |
| fielding_circadian_timezone_component | 3,386 | 3,386 |
| fielding_days_since_previous_game | 3,386 | 3,386 |
| fielding_eastward_time_zone_change_hours | 3,386 | 3,386 |
| fielding_eastward_travel_x_early_start | 3,386 | 3,386 |
| fielding_hours_since_previous_game_start | 3,386 | 3,386 |
| fielding_long_travel_x_short_rest | 3,386 | 3,386 |
| fielding_previous_game_innings | 3,386 | 3,386 |
| fielding_prior_extra_innings_x_travel | 3,386 | 3,386 |
| fielding_road_trip_length_x_travel | 3,386 | 3,386 |
| fielding_start_hour_in_previous_venue_time_zone | 3,386 | 3,386 |
| fielding_time_zone_change_hours | 3,386 | 3,386 |
| fielding_travel_distance_miles | 3,386 | 3,386 |
| fielding_westward_time_zone_change_hours | 3,386 | 3,386 |

Exact historical median/mode values were not recovered. Reason-aware structural-zero assignments may equal V14's prior fill value; their semantic-authority repair is established, but historical numerical equality is unresolved. Repeat-opponent count→Boolean changes are measured against V14's recorded raw passthrough in JSON.

| Wave 1 raw slot preserved | Raw ≠ successor posterior PAs | True-cold raw NULL retained | Added required columns |
| --- | ---: | ---: | ---: |
| batter_bb_hbp_per_pa | 463,711 | 37,828 | 5 |
| batter_hr_per_pa | 463,711 | 37,828 | 5 |
| batter_last100_strikeout_rate | 500,587 | 952 | 5 |
| batter_last100_walk_hbp_rate | 500,587 | 952 | 5 |
| batter_so_per_pa | 463,711 | 37,828 | 5 |
| pitcher_bb_per_bfp | 451,910 | 49,629 | 5 |
| pitcher_hbp_per_bfp | 451,910 | 49,629 | 5 |
| pitcher_hr_per_bfp | 451,910 | 49,629 | 5 |
| pitcher_last250_strikeout_rate | 496,693 | 4,846 | 5 |
| pitcher_last250_walk_rate | 496,693 | 4,846 | 5 |
| pitcher_so_per_bfp | 451,910 | 49,629 | 5 |

All 501,539 corrected OOF PAs receive the 55 additional required Wave 1 columns before one-hot expansion. Raw/new-posterior differences above are successor evidence, not a reconstructed V14 posterior replay. Per-feature counts overlap and must not be summed as distinct affected PAs.

| Deterministic treatment | Recomputed PAs | Raw-source→successor changed PAs |
| --- | ---: | ---: |
| batting_home_x_friday_night | 501,539 | 0 |
| batting_home_x_weekend | 501,539 | 0 |
| fielding_home_x_friday_night | 501,539 | 0 |
| fielding_home_x_weekend | 501,539 | 0 |
| matchup_platoon_advantage | 501,539 | 0 |

The 15 required-complete future-missing guards recorded 0 missing-rejection activations in the successful validation transforms; zero activations means the guard was not exercised by these recorded inputs. Synthetic rejection tests remain distinct evidence.

Failure paths with zero observed activations remain tested guards; this report does not claim such failures occurred in Development. The JSON retains all per-feature branch counts and prior history-state counts.

All 5 saved transforms/models passed full validation-data/prediction reload without refitting. Runtime: 2.135 hours. Failures: 0.

V1 exact parameters are newly fitted successor evidence, not recovered historical V14 parameters. V2 parameters are the existing exact fold authorities. Parent-only ablations remain explicitly deferred; optional V2 outputs were not added. The 22 approved exclusions remain preserved.

Final OOT: 14,067 rows remain sealed; no access, scoring, calibration, or selection. No champion, promotion, production export, or deployment.

Recommendation: Proceed toward challenger finalization with the corrected preprocessing and this preserved comparison; conduct bet-readiness and qualification analysis next. This is not a promotion or champion declaration.

## Exact artifact references

Corrected run: `95d4f0199aff4698f187311266c30670c4a95a66802cfd87ab96f1e120fd66bb`.
Baseline run: `c9ffcc867a73eac6c287309f34889390dedf8484244c3bf5c2ed20dacecaf635`; candidate `stage3-candidate-acfd57993d1844db95b81512c9a78a29`.
- Fold 1: preprocessing `objects/corrected-preprocessing/sha256/4171306af87bee46e74d2b5141189a5916382967322592243bf71e9eed9cf684.json`; model `objects/research-model/sha256/7ad16b4237df5e3672b093b0d68cda94c73e60cb37f85811262615a3326db0d6.joblib`.
- Fold 2: preprocessing `objects/corrected-preprocessing/sha256/42b442a747127814f535119cbb94351f69136a8aa4cd47982ea7fda6774692e9.json`; model `objects/research-model/sha256/bc048c5dbbeafb1854774fedca94af157dbcbc537b59bbfcd25384e37376b57b.joblib`.
- Fold 3: preprocessing `objects/corrected-preprocessing/sha256/3ae84e4ec75cc596faa2b501c1ff53ce81ea1cc9d8b56df16cfbd789b5fe8ae3.json`; model `objects/research-model/sha256/faaf792ab69055751c41e7d51cc63eb342f2f6724eafd202ec5d6fd489a64433.joblib`.
- Fold 4: preprocessing `objects/corrected-preprocessing/sha256/6931becd2fafd2cca73d009b3d8ca719b3fc328226a5b391e5f202c894e1e78a.json`; model `objects/research-model/sha256/cbc7f3f6c8bcebe4f1c0c1ece64dbc741e2d7af1d0d8d5064294fad0c413291e.joblib`.
- Fold 5: preprocessing `objects/corrected-preprocessing/sha256/21f13e822fcfc204bcbc769f171e4e57379b56c58d7bf330ceb3cc9a0f877df5.json`; model `objects/research-model/sha256/44ec4f457741f1aaeff42b81af1be5fd2712e494709ff1a0a8f0742b88d71c8b.joblib`.

## Recovery provenance and actual fit telemetry

Recovery `mlb-corrected-hgb-recovery-1-9aeb4b17dfa344ed86d888f55a51c7d5` is distinct from preserved failed study `94ce59613407da613b40c1fb7357e148b1053fc064977eeec6efb32acea7e4d0`. No failed-study artifact was overwritten.
V18 manifest: `4d158e01a4a7d84fe6e7641f61edf0e9848f1775e025a2cec6c29cda22d479f3`; model-schema checksum: `357cdf0176098217f51e0451433921e33bf8ebb94f5cbef21898ba53d45212ad`.
Authenticated recovery telemetry: 5 actual estimator-fit starts; 5 actual fit completions; 5 completed folds. Scheduler slot counters remain separate in JSON.
Fit accounting: `C:\Users\james\asp-model-studio\.runtime\asp-model-studio\stage3-model-laboratory\corrected-hgb-recovery-1\fit-accounting.json` (SHA-256 `92be26482906cfa362ac7180625be87edad2c1cb75751e510c6291975b41bb77`). Event log: `C:\Users\james\asp-model-studio\.runtime\asp-model-studio\stage3-model-laboratory\corrected-hgb-recovery-1\fit-events.jsonl` (SHA-256 `c190e1b9ff1305d143a825dc84560093a6e6c379fbbeaa76c623ebac5e37624f`).
Exact preflight authority/worker compatibility references are preserved in JSON. Provisional preflight identities remain provisional; they are not relabeled as fitted V18 model artifacts.
Recorded V18 validation-matrix digest/column-count/branch comparison with the five immutable provisional preflight receipts: `ALL_COMPLETED_FOLDS_OBSERVED_COMPATIBLE`. This compares stored evidence only; no model or transform was fitted or replayed for the comparison.

| Recovery fold | Estimator fit seconds | Post-fit to fold completion seconds |
| --- | ---: | ---: |
| 1 | 716.723 | 105.506 |
| 2 | 984.935 | 108.809 |
| 3 | 1329.281 | 106.970 |
| 4 | 1571.306 | 108.269 |
| 5 | 1882.951 | 108.408 |

UTC wall-clock differences, not CPU time. Post-fit-to-fold-completion includes prediction, metrics, artifact persistence/reload, and other fold completion work; it is not pure reload time. Missing milestones remain NULL, not zero.
Exact fit-start, fit-completion, and fold-completion UTCs and original V14 whole-fold runtimes are preserved in JSON.
Total recovery coordinator elapsed time: 7699.339 seconds, from the separately referenced terminal receipt.
