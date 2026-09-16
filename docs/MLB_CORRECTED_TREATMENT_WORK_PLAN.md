# MLB corrected-treatment bounded study

Authorized by the user request with SHA-256 `61046f7c1465733f70623bb74533e050fbca8ed93a8c2fb55346e71afa6f1ae9`.

Baseline checkout: `f02e32beb3e2d1ea70508c9cd555d01610d1f2e1`, branch `codex/mlb-governed-prior-engine-v1`. Preserve subsequent audit deliverables, V14, existing experiments and receipts, and the unrelated project-management handoff document.

## Frozen scope

- Correct the audited treatment through the real Model Lab execution path.
- Append an immutable successor treatment and feature/split registration after integration tests pass.
- Run exactly one saved best-HGB configuration across the same five Development folds. No RF, grid, calibration fit, selection search, parent-only ablation, full-development sixth fit, or new model family.
- Keep Final OOT sealed. No production export, promotion, deployment, or AISP changes.
- Preserve a worse result; comparison is descriptive, not authorization for another tuning round.

## Sources

- Downloads specification SHA: `c5f941236246442977a88865774903dea0ad37cab1ff1c3514cd6a78af2758e3`.
- Downloads audit SHA: `2b99078a95120bdbd32ccd5ac68923fc67e5422fe37d52e759a33b49c2f9061e`.
- The pasted request names a `(1)` variant, but only the explicitly attached unsuffixed workbook exists. Its 240-by-26 recommendation table matches the prior verified extraction; file hashes and recommendation cells are distinguished.
- Baseline tuning receipt SHA: `c9ffcc867a73eac6c287309f34889390dedf8484244c3bf5c2ed20dacecaf635`.
- Best HGB candidate: `stage3-candidate-acfd57993d1844db95b81512c9a78a29`, original OOF log loss `1.4745426774960453`.

## Execution sequence

1. Verify source identities and preserve immutable baseline evidence.
2. Implement independent semantic and prior treatment helpers; integrate through Model Lab, including reloadable local research artifacts.
3. Test actual training integration, branch handling, target/validation isolation, schema order, and saved-transform reload with synthetic fixtures.
4. Register/adopt the successor and freeze its exact schema, source identities, five folds, baseline hyperparameters, seeds, and subgroup definitions before expensive fits.
5. Run the five authorized HGB fits once; persist each successful fold and failure evidence append-only.
6. Compare matching OOF observations, paired game-clustered uncertainty, calibration and predefined subgroups. Reconcile treatment changes and observed branch counts.
7. Commit completed code/tests/report. Stop with one bounded recommendation; bet-readiness and qualification analysis remain next.

State at creation: implementation in progress; no successor registration or full-population fit has run.

## Execution checkpoint — September 7, 2026

- All five full-Development preprocessing preflights passed without predictive fits. Encoded feature counts: 432, 434, 435, 435, 436.
- The original 683,662-row source population is preserved. An explicit, target-free policy holds 56 known-zero-prior-PA observations; eligible Development is 683,606 and matching OOF is expected to contain 501,539 observations.
- Four repeat-opponent count fields were found to violate their declared Boolean domain. The successor validates finite nonnegative integer counts and represents them as `count > 0`; historical source data and V14 remain unchanged.
- Final adopted treatment: V18, `stage3-feature-treatment-spec-711fbb376e9a4d419f826de593195638`; manifest `4d158e01a4a7d84fe6e7641f61edf0e9848f1775e025a2cec6c29cda22d479f3`.
- Feature set: `stage3-feature-set-486aefc6482f46ddac2bed94b210e05d`; split: `stage3-split-contract-53bb07e31caa444b8246e260ba7761e0`.
- V16 was preserved as an intermediate registration before the exact-authority loader gained support for authenticated virtual outputs. Draft/adoption events account for separate version increments. No predictive fit used that intermediate registration.
- Frozen study: `94ce59613407da613b40c1fb7357e148b1053fc064977eeec6efb32acea7e4d0`; one configuration, five fits, original source order, seed 20260906 plus fold number, four native HGB threads.
- Submitted exactly once: `stage3-model-job-86b72c0cee694779bb3cab64eb28cc45`. State at this checkpoint: RUNNING, fold 1; no completed model result claimed.
- Focused synthetic tests passed: 33 semantic, 27 actual Model Lab entry, 26 corrected registration/authority, 13 prior representation, 16 study/finalizer. Legacy regression: 59 passed. Frontend contract: 17 passed; TypeScript build passed.
- The old local API process requires a reload to display the newly adopted virtual-output authority. Training has its own coordinator and will not be interrupted for that refresh.

Detailed append-only provenance is indexed in [the registration/preflight report](C:/Users/james/asp-model-studio/docs/corrected-treatment-report/Registration_and_Preflight_Evidence.json). Results, final artifact replay, UI reload and commit remain pending at this checkpoint.

## Terminal outcome — comparison blocked, no retry

The single submitted study ended `PARTIAL` after 111.735 seconds with `[WinError 5] Access is denied`. No fold completed and no corrected model, prediction or real-run replay receipt was produced. The scheduler marks five planned fit slots failed after the one configuration aborts; that is not evidence of five actual fit calls. Only fold 1 was observed started; the failed receipt does not record an iteration count.

An 80-row artificial HGB diagnostic reproduced Windows named-pipe creation failure during histogram binning inside the sandbox. The same synthetic diagnostic passed with reviewed execution outside the sandbox. Neither diagnostic used sports or OOT data. The runner now probes the same threading infrastructure before any future initial submission; it still refuses to reenqueue this terminal study.

The [terminal comparison report](C:/Users/james/asp-model-studio/outputs/mlb-corrected-treatment/corrected-hgb-comparison-58bb89910289c8d38329b1b9e848934c382586dbd749ab37fba2a68a46210eae.md) preserves original V14 metrics and explicitly leaves corrected metrics, matched-observation comparisons, CI, subgroups and real-run reload verification unavailable. The [runtime diagnostic](C:/Users/james/asp-model-studio/docs/corrected-treatment-report/Windows_HGB_Runtime_Diagnostic.json) distinguishes actual receipt evidence from the synthetic reproduction.

V18 remains adopted. The local API was refreshed after the failed coordinator exited, without restarting training or changing the frontend/other services. A read-only recompile matches the adopted V18 manifest exactly. Authentication remains enabled; the API refresh can require a new sign-in. Candidate evidence now separates model inputs from source and derived columns, or reports the breakdown unavailable when the exact fold evidence is absent.

Recommendation: address the Windows execution blocker through one explicitly authorized, append-only recovery attempt of the unchanged five-fold configuration outside the sandbox. Preserve this failed study, V14, V16 and V18; do not retune, open OOT or roll back corrected semantics. Bet-readiness and qualification remain next after the challenger comparison/finalization.

Closeout checks: 124 correction/feature-registration tests passed, including all 27 actual Model Lab integration cases and 18 bounded-study tests. The separate legacy Model Lab/treatment/interaction/tuning suite passed 59 tests. The final two frontend contract suites passed 24 tests, and TypeScript checks passed. Expected synthetic warnings concern deliberately infinite test inputs and single-class AUC fixtures, not live fitted results. API health returned `ok: true`. No source/treatment implementation code changed after final V18 registration; the final read-only compile still returned manifest `4d158e01a4a7d84fe6e7641f61edf0e9848f1775e025a2cec6c29cda22d479f3`.

Changed-file groups: semantic and prior treatment execution; exact derived-output eligibility/registration; Model Lab integration and research-artifact persistence; bounded-study runner/finalizer and Windows runtime probe; Model Lab/Candidate Evaluation count presentation; synthetic regression tests; local API environment-only refresh support; the 240-feature report and terminal diagnostics. The original audit output directory and unrelated project-management handoff remain outside this change set.
