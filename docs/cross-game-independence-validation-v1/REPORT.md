# Cross-game independence validation v1

## Disposition

**No examined category is approved for AISP research display under the frozen v1 gate.** The broad unrelated-game samples show little residual correlation, so the evidence does not establish a material need for a slate-level joint model. It does show that multiplying the current raw probabilities can be misleading because single-game calibration error carries into the product, most clearly for NBA, and because several otherwise small-error strata remain too imprecise or fail reliability-band tolerances.

The existing probability contract should therefore remain fail closed. Same-game legs still require paired-draw intersections. Cross-game products must retain the `INDEPENDENCE_ASSUMPTION` label and remain unavailable to consumer display until an eligible category passes a prospective or better timestamp-certified repetition of the frozen gate.

## Population

The study used only retained chronological research ledgers. It did not load MLB data, sealed evidence, or Final OOT outcomes.

| Sport | Admitted evidence | Source games | Dates | Qualification |
|---|---:|---:|---|---|
| CFB | Development-fixed calibrated Ridge assessed on reused 2023–24 Validation | 1,491 | 2023-08-26 to 2024-11-30 | Reused inspected Validation; 81 opener rows have no prior eligible team-state game and use governed priors/defaults |
| NBA | `ridge_a100_rest` Development chronological predictions | 3,538 | 2020-12-22 to 2023-04-09 | Each row records an earlier latest-history date; historical physical publication clocks are absent |
| NFL | M1 raw season-forward OOF predictions | 1,408 | 2020-09-10 to 2025-02-09 | One held-forward season per fold; schedule enrichment reads identity, time, teams and type only |
| **Total** |  | **6,437** |  | 773 distinct dates |

Pair construction yielded 52,405 unique unordered same-date game pairs: 49,548 same-sport, 2,857 cross-sport, 297 involving postseason games, and no observed shared-team pairs. The primary unrelated, regular-season population contains 52,108 pairs, 6,277 games and 664 dates. Pair count is not the independent sample size; all confidence intervals resample whole dates. Its pair-weighted Kish effective slate count is 76.35.

## Frozen practical gate

The design and tolerances were physically frozen before outcomes were loaded. A display category required all of the following:

- at least 500 games, 50 slates and 1,000 pairs;
- absolute raw joint-calibration error at most 2 percentage points;
- relative error at most 10% when mean probability is at least 0.10;
- 95% calibration-interval width at most 5 percentage points;
- absolute Pearson and Spearman residual correlation at most 0.05, with the Pearson interval contained in `[-0.10, 0.10]`;
- at least two supported reliability bands, each with 200 pairs and 20 slates, and each within 3 percentage points.

Two thousand deterministic whole-slate bootstrap resamples used seed `20260916`. Holm adjustment applies to the five residual-correlation tests within each sport-pair family. The practical gate, rather than isolated significance, controls the disposition.

## Main results

Errors below are observed two-home-win frequency minus `p(home A) × p(home B)`. Positive values mean the product was too low. Correlations are pair-weighted Pearson correlations of winner residuals; uncertainty is clustered by date.

| Segment | Games | Dates | Pairs | Kish effective dates | Joint error (95% CI) | Winner residual r (95% CI) | Gate result |
|---|---:|---:|---:|---:|---:|---:|---|
| CFB–CFB | 1,472 | 97 | 29,629 | 26.00 | +0.22 pp (-2.29, +2.90) | -0.0038 (-0.0116, +0.0055) | Fail: CI width 5.20 pp and reliability |
| NBA–NBA | 3,536 | 467 | 13,356 | 313.37 | -3.70 pp (-5.45, -1.85) | -0.0063 (-0.0210, +0.0086) | Fail: calibration and reliability |
| NFL–NFL | 1,191 | 123 | 6,527 | 86.71 | +0.35 pp (-2.25, +3.17) | -0.0117 (-0.0282, +0.0076) | Fail: CI width 5.42 pp and reliability |
| Cross-sport regular | 959 | 101 | 2,596 | 33.00 | +1.10 pp (-2.53, +4.53) | -0.0233 (-0.0548, +0.0092) | Fail: CI width and joint calibration |
| Same-start window | 2,493 | 197 | 10,617 | 47.21 | +0.54 pp (-1.94, +3.05) | -0.0101 (-0.0265, +0.0090) | Fail: reliability |
| Separated starts | 2,496 | 151 | 20,574 | 38.44 | -0.11 pp (-2.42, +2.09) | -0.0037 (-0.0138, +0.0065) | Fail: reliability |
| All unrelated regular | 6,277 | 664 | 52,108 | 76.35 | -0.73 pp (-2.36, +0.99) | -0.0055 (-0.0142, +0.0041) | Fail: reliability |

Margin, total, home-score and away-score residual correlations were also small in the adequately supported sport strata. The largest absolute Pearson estimate among those 15 same-sport estimates was NBA total residual `+0.0143`; all corresponding intervals remained inside the frozen `[-0.10, 0.10]` bound. Holm-adjusted correlation evidence did not identify an isolated same-sport residual dependence.

Raw joint calibration is not a pure dependence test. NBA's single-game home-win probability averaged 58.41% while the observed home-win rate was 55.68%, a -2.73-point marginal residual. That error compounds in two-leg products and is consistent with the -3.70-point NBA joint error even though NBA winner-residual correlation was near zero. CFB's single-game residual was -0.20 points and NFL's was +0.60 points. This separation is why the study does not infer a slate-level dependency model from NBA's raw-product miss.

Favorite/favorite products also warrant caution. Observed-minus-product errors were +2.44 points for CFB, -2.43 for NBA and +2.15 for NFL. A product may be poor because the legs are marginally miscalibrated even when residual dependence is negligible.

## Segment findings

- Exact start-time analysis was available for CFB and NFL. Same-window and separated-start residual dependence was small, but reliability gates failed. NBA exact tip times were absent from the retained Development ledger, so its timing class is `UNKNOWN`.
- Cross-sport coverage consisted only of CFB–NFL (71 pairs, 26 dates) and NBA–NFL (2,525 pairs, 75 dates). CFB–NBA had no overlapping retained dates. The aggregate cross-sport interval was too wide.
- Postseason coverage was 297 pairs over 31 dates and failed sample and precision gates.
- Potential sequential-incentive coverage was 36 NFL pairs over 26 dates and is unsupported.
- No shared-team or MLB doubleheader pair was present. Those categories remain excluded rather than inferred safe.
- No common governed venue, geography, weather-system, injury or roster-dependency fields exist across these ledgers. Those dependencies remain unsupported.
- Totals-event joint calibration was not computed because point expectations are not valid over/under event probabilities.

## Systematic model-error risk

Broad same-date residual correlations do not show strong common-direction errors. Descriptive slate means still reveal model-level biases that a product cannot repair: NBA home-win forecasts averaged 2.73 points too high, while CFB and NFL favorite residuals averaged +1.89 and +1.82 points. The study cannot attribute these to weather, data-source failures or incentives because governed causal fields are absent.

## Recommendation

Keep the current cross-game path research-only and fail closed. Do not add a slate-level joint model from this evidence: adequately supported broad residual correlations are too small to justify it. The next evidence step is prospective collection of exact controlling forecast revisions, physical creation/source-cutoff clocks and explicit dependency metadata. Reapply the already frozen gate without category search or threshold changes.

Machine results are in [RESULTS.json](RESULTS.json), with compact coverage and segment views in [POPULATION_AND_COVERAGE.json](POPULATION_AND_COVERAGE.json) and [SEGMENT_RESULTS.json](SEGMENT_RESULTS.json).

## Integrity and accounting

- Frozen design SHA-256: `5749b2457b52589a612b3a2597341185a5baf9b814d300715ec115a4c8dda87f`
- Final `RESULTS.json` SHA-256: `fafc0b9bd9997e65fa6db209bceb6dacb91943528e136ed23603daf922ffef24`
- Provider calls/bytes/cost: `0 / 0 / $0`
- Sportsbook calls: `0`
- Sealed reads / Final OOT reads: `0 / 0`
- Model runs/promotions: `0 / 0`
- AISP writes / exchange writes: `0 / 0`
