# Corrected MLB HGB: single authorized recovery

## Scope and immutable identities

This is the one recovery explicitly authorized by James on 2026-09-07. It does not retry, overwrite, or relabel the prior failed attempt. No additional configuration, random forest, feature expansion, calibration fitting, Final OOT access, promotion, export, deployment, merge, or AISP modification is authorized.

- Preserved implementation base: `227f1a814377a47f5e4defb570b22ca53bdc0faa`.
- Recovery ID: `mlb-corrected-hgb-recovery-1-9aeb4b17dfa344ed86d888f55a51c7d5`.
- Recovery study checksum: `cb835f9be3d66e49d2681e0af25dfff9275e0e42faff4db8fada229f3e1015d2`.
- Recovery job: `stage3-model-job-e2b3550ade1e4b809e4c92be03e991a2`.
- Failed predecessor study: `94ce59613407da613b40c1fb7357e148b1053fc064977eeec6efb32acea7e4d0`.
- Failed predecessor job: `stage3-model-job-86b72c0cee694779bb3cab64eb28cc45`.
- Failed run receipt: `cf308ac9f910073a170f5ab6fa5e4adfd969b2eed2ec8e5ff3d17c54ee77cbc8`.
- Failed candidate receipt: `f9abd8c13bc57d741d6d2758e4491d002684147758e2b9c9d5717ca93067ffea`.

The recovery records are under `.runtime/asp-model-studio/stage3-model-laboratory/corrected-hgb-recovery-1/`. Its immutable study contains the predecessor file hashes and decoded terminal-job checksum, authority verification, exact masks, four-worker execution probe, and a content-addressed complete source-byte snapshot of the observational recovery coordinator/telemetry. The original study folder and failure reports are not modified.

## Authority verified before fitting

| Authority | Frozen identity / result |
| --- | --- |
| Adopted treatment | V18, `stage3-feature-treatment-spec-711fbb376e9a4d419f826de593195638` |
| Treatment manifest | `4d158e01a4a7d84fe6e7641f61edf0e9848f1775e025a2cec6c29cda22d479f3` |
| Feature set | `stage3-feature-set-486aefc6482f46ddac2bed94b210e05d` |
| Model schema | `357cdf0176098217f51e0451433921e33bf8ebb94f5cbef21898ba53d45212ad` |
| Inputs before categorical encoding | 273: 218 original source slots plus 55 required Wave 1 prior outputs |
| Registered chronological split | `stage3-split-contract-53bb07e31caa444b8246e260ba7761e0` |
| Split checksum | `46a2f98ac5e96120855c70489fcd642883e84d9719037ecc44d4760b993b7846` |
| Eligibility policy | `8a28ee325505a657fa5cffa30a6278c9e10c82a01983516c29c701b2c12dcd61` |
| Actual final-V18 eligibility checksum | `6ab78797090c2a3ca80267f34ef7304591557a8f1e36c7455e2d8a27fea96873` |

All seven V18-bound implementation files match their registered normalized-LF source hashes. No bound file was edited for recovery. The separate observational wrapper verifies the actual candidate entry, full registered fold dictionaries and split identity, target class order, actual eligibility masks, prepared 273-column treatment payload, complete effective estimator parameters and fold seed, and four-worker native pools immediately before each original HGB fit. It does not replace the estimator, transform, or fit algorithm.

Both the read-only preparation check and the launch recheck independently scanned Development with target loading disabled. The entire eligibility receipt matched the preserved final-V18 receipt, not just its counts.

| Fold | Registered training | Eligible training | Training held | Registered validation | Eligible validation | Validation held |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 182,072 | 182,067 | 5 | 99,782 | 99,780 | 2 |
| 2 | 281,854 | 281,847 | 7 | 100,269 | 100,267 | 2 |
| 3 | 382,123 | 382,114 | 9 | 99,968 | 99,926 | 42 |
| 4 | 482,091 | 482,040 | 51 | 100,304 | 100,302 | 2 |
| 5 | 582,395 | 582,342 | 53 | 101,267 | 101,264 | 3 |

Development: 683,662 source observations, 56 held, 683,606 eligible. Validation windows: 501,590 original V14 observations, 51 held, 501,539 common observations. These actual pre-fit mask counts also passed the completed exact-ID OOF reconciliation: no corrected-only IDs, and the 51 baseline-only IDs exactly match the frozen hold ledger. No count discrepancy was found. The known-zero-opportunity reason and hold remain unchanged. Final OOT's 14,067 rows remain sealed.

## Provisional preprocessing evidence

All five previous preflight receipts remain under their original provisional manifest `48de9ecbe2932fedd33cbce401dc4478a00d5a41b4d327a4d14152764c41807c` and `UNREGISTERED_CORRECTED_PREFLIGHT_ONLY` identity. Their observable model schema, policy, held immutable IDs, eligible row counts, and chronological fold definitions match V18. The historical receipts do not embed their source-code bytes, and that provisional manifest was not registered; exact historical source-byte identity is not proven. They are not final-V18 predictive fits or full model-reload evidence. The recovery finalizer separately compares completed V18 validation-matrix digests, encoded widths, and shared branch counters with these preserved receipts.

## Bounded execution and accounting

Execution uses `C:/Users/james/asp-model-studio/.venv/Scripts/python.exe` through the supported `require_escalated` Windows approval mechanism. No access control, ACL, resource limit, or rejection was bypassed. Before launch, the failed coordinator PID 61036 and its descendant process tree were absent, there were no active project model jobs, and no model-development locks existed. No process was killed and no lock was reclaimed.

Exact saved HGB configuration: learning rate 0.03; 500 iterations; 31 leaf nodes; unlimited max depth; minimum 50 observations per leaf; L2 1.0; early stopping disabled. Base seed 20260906, fold seed base plus fold number. One candidate, five scheduled slots, four native workers, unchanged target and evaluation definitions.

`submission-intent.json` is exclusively created and flushed before the one enqueue. Existing intent or recovery batch identity prevents a second enqueue. `fit-events.jsonl` is exclusively created, append-only, flushed, and hash-chained. Starts, returned fits, completed folds, and exception tracebacks are separate events. `fit-accounting.json` is generated from that authenticated event sequence after terminal completion. The finalizer cannot infer actual starts from scheduler counters.

The failed predecessor had five scheduled slots, zero completed folds, and **unknown actual estimator-call starts** because that instrumentation did not exist. Its scheduler's five failed slots are not evidence of five calls.

Prelaunch verification: 62 combined synthetic tests passed, including the actual Model Lab evaluation/encoding/construction path with estimator fit/predict stubbed. This testing is not sports-model fitted evidence. Separate subsequent finalizer tests also verify that an internally checksummed accounting summary cannot disagree with the event sequence.

## Completion report

**The single recovery completed successfully on 2026-09-07. V18 did not demonstrate better aggregate predictive performance than V14.**

The [complete comparison report](C:/Users/james/asp-model-studio/outputs/mlb-corrected-treatment/corrected-hgb-recovery-1-comparison-12bfbc8c4a17a7ef45ec102ef3cb7ca8a9e03b395d0941eed51c98ec3bdf699d.md) and [machine-readable evidence](C:/Users/james/asp-model-studio/outputs/mlb-corrected-treatment/corrected-hgb-recovery-1-comparison-12bfbc8c4a17a7ef45ec102ef3cb7ca8a9e03b395d0941eed51c98ec3bdf699d.json) have result checksum `12bfbc8c4a17a7ef45ec102ef3cb7ca8a9e03b395d0941eed51c98ec3bdf699d`. Finalization loaded saved Development OOF predictions and compared them without fitting any model or accessing OOT. These content-addressed reports remain unchanged; the interpretation and next-step qualification below supplement their numeric evidence.

| Population / metric | V14 | V18 | V18 minus V14 |
| --- | ---: | ---: | ---: |
| Matched 501,539 PAs: log loss | 1.474558302223 | 1.474589538657 | +0.000031236434 |
| Matched: summed Brier | 0.703052769842 | 0.703065382852 | +0.000012613010 |
| Matched: macro one-vs-rest AUC | 0.577313970537 | 0.576922795089 | -0.000391175448 |
| Matched: ECE | 0.004687402244 | 0.004589942163 | -0.000097460081 |
| Original V14 501,590 PAs: log loss | 1.474542677496 | Not applicable | Not a matched comparison |

V18's log loss and Brier point estimates are slightly worse, its AUC is lower, and its ECE is slightly better. The paired, PA-weighted game-cluster bootstrap uses 6,664 games, 2,000 resamples, and seed 20260907. Its aggregate log-loss-difference 95% interval is `[-0.000211973146, +0.000281453522]`. It includes zero; this is neither evidence of superiority nor proof of equivalence/noninferiority. The report also preserves all per-fold metrics, original V14 per-fold metrics, per-class metrics, and reliability bins.

### Predefined subgroup qualification risks

| Predefined subgroup | PAs | Games | Log-loss difference | Nominal 95% interval |
| --- | ---: | ---: | ---: | --- |
| Batter true cold start | 37,828 | 4,950 | +0.000709195 | [-0.000161063, +0.001566600] |
| Pitcher true cold start | 49,629 | 3,527 | +0.000700577 | [-0.000045072, +0.001469978] |
| Either player true cold start | 83,174 | 5,734 | +0.000684925 | [+0.000097594, +0.001276869] |
| Batting no prior game | 3,385 | 47 | +0.004772394 | [+0.000649408, +0.009224756] |
| Fielding no prior game | 3,386 | 47 | +0.005317160 | [+0.001214285, +0.009788363] |
| Either team no prior game | 3,535 | 47 | +0.005001590 | [+0.001043780, +0.009284087] |

All six point estimates are worse. The either-player group and all three team no-history groups have positive nominal intervals. The groups overlap, their intervals are not multiplicity-adjusted, and team results have only 47 game clusters. These are qualification risks requiring review, not six independent findings or permission for another experiment. No hold was changed, and the 56 unresolved known-zero-opportunity observations were not treated as cold starts.

### Artifacts, branch coverage, runtime, and preservation

- Scheduled slots: **5**. Authenticated actual estimator-fit starts: **5**; returned fits: **5**; completed folds: **5**; failures: **0**. No retry or sixth full-Development fit occurred. The previous failed attempt still has unknown actual fit starts and zero completed folds.
- Actual model-run runtime: **7,685.875 seconds (128.098 minutes)**. Coordinator elapsed time: **7,699.339 seconds (128.322 minutes)**. Per-fit UTC durations and separately labeled post-fit completion work are in the report; neither is confused with CPU time or pure artifact-reload time.
- Recovery run: `stage3-model-development-run-8ff1e0a505da4482a0a67386754e28ff`, receipt `95d4f0199aff4698f187311266c30670c4a95a66802cfd87ab96f1e120fd66bb`. Candidate: `stage3-candidate-83f50e93af5946198c8df4602e08d7b8`, receipt `6d0b84a01afab4db343d92e985280a41669e12222a73aca0a2df3e0f880259b2`.
- All five folds saved complete prior and semantic parameter payloads, fitted categorical encoding, local research model artifacts, and implementing source bytes. Full validation transforms and predictions were reloaded with **zero refits**. Maximum absolute prediction difference was **3.3306690738754696e-16**; transformed validation digests matched exactly. Each artifact's immutable reference is in the comparison report.
- All **64 recorded semantic branches** and **21 priors** cover **501,539** eligible validation PAs each. All PAs receive the **55 required Wave 1 channels** before categorical expansion. Training counts remain per fold because expanding prefixes overlap. Per-feature counts are not summed as distinct affected observations.
- The report distinguishes raw-source changes from proven V14 representation changes, native missingness from median imputation, observed branches from synthetic rejection tests, and newly fitted V1 parameters from unrecovered historical V14 parameter payloads. The 22 approved exclusions remain unchanged; no optional Wave 2 channels or deferred ablations were added.
- All five V18 validation-matrix digests, encoded widths (432, 434, 435, 435, 436), and shared branch counters are observably compatible with the original provisional preflight receipts. Those receipts retain their provisional identities and remain distinct from these new final-V18 fitted artifacts. Historical provisional source-byte identity is still not proven.
- Independent read-only provenance QA recomputed the full 24-event hash chain, reconciled the accounting checksum `0dd78be7c01f32f5db87ba381ac06fee43fc301da33a5b354544a84f3d7a303d`, and verified every preserved predecessor file plus the original failed job's decoded state unchanged. V18-bound source hashes, exact parameters, fold seeds, populations, and four-worker pools match the launch authority.
- Independent statistical QA recomputed all four headline metrics from saved OOF artifacts and regenerated the 2,000 paired game-cluster bootstrap draws, reproducing the reported interval. Exact-ID coverage, subgroup metrics/counts/intervals, reliability-bin totals, and per-fold evidence reconciled without discrepancy. This audit did not load models, generate predictions, refit, or access OOT.
- Final synthetic recovery/report regression suite: **65 passed**. Seven undefined-AUC warnings come only from a deliberately single-class synthetic fixture with stubbed estimator fitting; no sports fit was added by testing or finalization.

### Recommended next governed step

Prepare the challenger-finalization qualification decision from this frozen evidence: explicitly review the aggregate no-clear-improvement result, cold/no-history regressions, runtime cost, artifact reproducibility, and the unresolved 56-row eligibility limitation. Record whether those limitations are acceptable for the intended research challenger scope; this run does not itself make that decision. Keep V14 as the historical comparison baseline, retain the corrected treatment authority, and do not reinstate incorrect treatment paths to recover a metric.

No new tuning, calibration fit, ablation, eligibility change, or OOT opening is initiated or implied. After the challenger-finalization decision, proceed to separately authorized bet-readiness analysis. This task stops at the completed comparison: **Final OOT sealed, no champion declaration, promotion, production export, deployment, merge, or AISP modification.**
