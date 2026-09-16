# PA hierarchy: implemented mechanics, real comparison not yet eligible

This is a bounded successor to the PA gate in `MLB_STARTER_SURVIVAL_HIERARCHY_DECLARATION_V1.json`, SHA-256 `51b886ecb20137ea7e8ab0ce1abb8601c3f86df0dfe77dae95d07d8ca01bcc9d`. It does not change frozen V18, the eight-class target, the original 56-PA hold, or the sealed August 14–27, 2026 Final OOT partition.

## Outcome of the later-cohort check

**The real A/B/C comparison is blocked by the missing shared feature-history chronology certificate, not by absence of source completion evidence.** No real PA candidate fits or comparative performance calculations were run.

The outcome-free inventory authenticated all five frozen estimator and fitted-preprocessing artifacts, their nominal estimator/prior/wave-1/wave-2/semantic/interaction cutoffs, the registered split, and the existing physically isolated identity-only Development projection. It also examined two new, explicitly retrospective comparison possibilities without reading candidate targets or predictions:

| Reference and proposed window | PAs before certification | Games before certification | Certified comparison PAs |
|---|---:|---:|---:|
| Frozen fold 1; March 20–May 20, 2024 | 53,244 | 709 | 0 |
| Frozen fold 2; August 29–September 29, 2024 | 31,710 | 423 | 0 |

These windows were chosen from dates and known completion intervals, not model performance. Zero known-date diagnostic flags within these windows is not a certificate that every rolling or context feature is chronologically valid. The counts are possible coverage, not fitted or evaluated sample sizes.

The raw reference uses identity calibration: no fitted final calibrator is applied, and no calibration observations enter that identity transformation. The nominal fitted information ends on October 1, 2023 for fold 1 and July 6, 2024 for fold 2. Later calendar windows can remove the known direct fold-2 training-label availability crossing; they do not repair the official-date ordering of historical last-100/last-250 inputs or establish all recursive feature dependencies. Matching 246 raw, 273 treated and ordered encoded dimensions alone cannot establish that lineage.

### New source-identity finding

The safe original 2023 Gold bridge was matched exactly to the FD1 timing-only evidence for `NYN202309280`: **61 canonical PA identities map to all 61 retained source PA identities; zero mismatches; all are in innings 1–8; zero voided ninth-inning PAs are present.** This corrects any suggestion that the frozen model necessarily trained on those voided ninth-inning events.

The raw comments explicitly put the voided ninth-inning events in comments and describe the reversion to the eighth inning. They do not provide an observed publication timestamp for the reversion. Derived `final_available_date` and event-occurrence dates are not silently promoted into such timestamps. This identity finding resolves one specific concern; it does not by itself certify every frozen fitted input or later query vector.

For `BOS202406260`, supported local completion metadata confirms the June 26/August 26 split. At least 55 of its 70 PAs, those in innings 3 onward, occurred after the nominal July 6 fold-2 training cutoff; the source also locates resumption within inning 2. This is the established direct training-label crossing. Other folds retain historical feature-lineage concerns, not a claim that all their training labels cross their respective cutoffs.

## Smallest remaining repair

Use the now-established canonical/source PA bridge and safe 2023/2024 event-occurrence/completion evidence to rebuild and certify only the shared affected histories, including the ordering needed by last-100/last-250 and context features. Resolve or explicitly exclude same-day or resumed ordering when it changes a window. Establish the actual information bound of the frozen fitted estimator and every fitted preprocessing state, then freeze one exact later matched cohort and feature contract before real B/C fitting.

Using repaired inputs only for B/C would mix architectural change with input repair; using known official-date misordering for every arm would not satisfy the requested timing-valid common-input comparison. If frozen fitted-state information cannot be certified under an explicit conservative historical-reconstruction assumption, a separately authorized repaired historical reference is needed. No replacement V18 was trained here. This is not proof that every later retrospective comparison is impossible.

## Executable B/C implementation

`server/sports_current_statcast/mlb_pa_hierarchy_research.py` implements:

- The unchanged class order: `STRIKEOUT`, `WALK_HBP_CI`, `HOME_RUN`, `SINGLE`, `DOUBLE`, `TRIPLE`, `BIP_OUT`, `OTHER_REACH`.
- OUT-class indices 0/6 and NON-OUT-class indices 1/2/3/4/5/7. These are families of terminal labels, not assertions about actual runner advancement or outs; the transition engine retains those responsibilities.
- B: one binary root, multiplied by training-only smoothed conditional class frequencies.
- C: the exact same fitted root, multiplied by a learned two-class or six-class conditional head. Soft multiplication preserves every class and sums to one; there is no hard routing.
- Explicit half-count-per-class regularization, absent/one-class branch treatment, no oversampling, no preprocessor refit, and exact ordered-feature checks. Candidate fitting fails closed without a declared eligible training authority.
- Eight-class NLL decomposition into root plus relevant conditional-head NLL. Conditional family means and all-PA-weighted contributions are kept separate. A common floor and normalization are applied to a scoring copy, never to saved V18 predictions.
- Full fitted object/preprocessor/feature-contract/fixture persistence, content-addressed hashes, trusted-hash reload and exact prediction comparison. Calibration is honestly marked identity/not fitted.

## Focused verification and accounting

Four focused synthetic tests passed in the supported Windows execution context. They cover probability mapping, loss decomposition and nonmutation, exact shared-root behavior, feature ordering, artifact reload, unauthorized-fit rejection and absent classes.

The single successful synthetic fitted-fixture test trained three small synthetic classifier heads in total: one root and two conditional heads. B/C each reloaded a 16-row fixture with **zero mismatches across 128 probabilities**; reload performed zero fits. These are parser/model-mechanics checks, not baseball accuracy evidence. Real PA candidate fits: **0**. Real comparison rows: **0**. Provider calls, sealed/mixed-2026 payload reads, AISP writes and V18 refits: **0**. Earlier pytest attempts failed during temporary-directory setup and did not start estimator fits; unrelated warnings were left unchanged.

## Evidence

- Final immutable gate: `outputs/mlb-starter-survival-hierarchical-pa-v1/pa-eligibility/sha256/37e3fcb056899420d0000be6f0f61f9567d1ccccb05fe0da7033d6a3c4554531/eligibility-review.json`; SHA-256 `37e3fcb056899420d0000be6f0f61f9567d1ccccb05fe0da7033d6a3c4554531`, 29,489 bytes. The initial review is preserved and referenced as predecessor.
- FD1 timing-only evidence: `outputs/mlb-starter-survival-hierarchical-pa-v1/duration-data/sha256/9d12bb87e31b77c4f088705dd15a713c0b29795fcd9e7e2d32aac4b41420fbc4/timing-only-evidence.json`; SHA-256 `5f4ecc0bdf5ec1476952f2081be62d75b03e20a9a8cd60e96e72f525618fff52`.
- Reproduction command: `.venv\Scripts\python.exe scripts/inventory_mlb_pa_hierarchy_eligibility.py`.
- Focused tests: `tests/test_mlb_pa_hierarchy_research.py`.

Independent starter-duration results may proceed. No real PA or four-arm game-level improvement is claimed from this component.
