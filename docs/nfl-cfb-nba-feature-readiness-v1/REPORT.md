# NFL, CFB and NBA data-science readiness V1

## Executive disposition

The current systems have credible chronological team-level foundations, but none of the four bounded additive feature treatments passed the frozen research gate. The correct action is to retain the current baselines and advance one narrower, source-aware experiment per sport. This is a negative but useful result: more indicators or direct arithmetic interactions do not substitute for new information or a properly fitted opponent-strength process.

| Sport | Bound population | Current feature contract | Reused-later baseline | Challenger result | Next dependency |
|---|---:|---:|---|---|---|
| NFL | 6,695 games, 1999-2024 | 197 | 2023/2024 score MAE 7.57/7.23; log loss 0.656/0.618; binary Brier 0.232/0.214 | Missingness, cold-start, direct EPA matchup and combined blocks all failed | Fit offensive/defensive pass/run EPA team effects inside each origin; personnel/weather remain source-gated |
| CFB | 7,744 games, 2014-2024 | 35 | 2023/2024 score MAE 9.29/9.27; margin MAE 13.04/13.51 | Cold-start delta -0.010 score MAE, interval crosses zero; direct matchup block effectively zero | Effective-dated conference identity plus chronological schedule-strength adjustment |
| NBA | 6,952 games, audit seasons 2020-2025 | 78 | 2024/2025 score MAE 9.31/9.28; Elo log loss 0.616/0.617 | Missingness, cold-start, rest-density and combined blocks all failed | Timestamped team boxes for possessions, pace and efficiency |

These results use previously inspected historical evidence. Development roles were NFL 2022, CFB 2021-22 and NBA audit seasons 2021-23. Reused diagnostic roles were NFL/CFB 2023-24 and NBA 2024-25. They are not untouched OOT. Historical data was reconstructed later from finalized records, so point-in-time calculations enforce target exclusion but do not certify original source publication vintages.

## What was built

The branch adds a hash-gated, no-network analysis runner that rejects altered inputs, duplicate game identities, calendar-2026 rows, and retained CFB/NBA feature dates at or after the target. It profiles population, missingness, target distributions, team identities, temporal drift, feature associations, cold-start coverage, residuals and reliability. It builds a machine-readable feature registry, missingness hierarchy, injury-readiness matrix and Generation 2 roadmap.

The bounded screen keeps each existing model family: the NFL fixed XGBoost score recipe, CFB Ridge alpha 100 and NBA Ridge alpha 100. The baseline is compared with explicit missingness indicators, support-aware cold-start features, one sport-specific supported context block, and their combination. Preprocessors and transformations are fit inside each earlier-season origin. Paired uncertainty resamples calendar weeks, never simulation draws.

Thirty static figures cover per-sport population, missingness, target landmarks, feature associations, drift, cold-start coverage, feature availability, residuals, calibration and experiment deltas. Machine-readable results are in `DATA_QUALITY_SCORECARDS.json`, `FEATURE_REGISTRIES.json`, `EXPERIMENT_RESULTS.json` and the supporting contracts in this directory.

## Shared data-quality findings

No duplicate game IDs or missing targets were found. The bound projections contain 197 NFL, 35 CFB and 78 NBA model features. CFB has no null cells because treatment occurred upstream; that is not proof every value was observed. It prevents the downstream audit from distinguishing source absence from an imputed fallback, so future feature stores must retain observed/imputed provenance.

NFL contains 20,631 missing feature cells. `game_type`, `roof` and `surface` are entirely null in this projection; several season-to-date efficiency fields are missing in roughly 6% of rows. NBA contains 2,258 missing cells, concentrated in early rolling variability. No impossible values remain after applying semantic checks that allow signed differences.

The largest numerical drift is partly expected time/support movement rather than automatic model failure. NFL cumulative prior-game counts have PSI above 4.5. NBA league cumulative means/history counts have PSI above 9. CFB drift is modest, led by prior-total shrinkage at 0.125. These features need age/support interpretation and monitoring; deleting them based on PSI alone would be unjustified.

## Experiment results

Candidate-minus-baseline deltas are lower-is-better. Intervals are paired 95% calendar-week block-bootstrap intervals over reused later evidence.

| Sport / block | Score MAE delta | Margin MAE delta | Total MAE delta | Frozen gate |
|---|---:|---:|---:|---|
| NFL missingness | +0.016 [-0.006, +0.038] | +0.017 [-0.031, +0.067] | +0.056 [+0.007, +0.104] | Fail |
| NFL cold start | +0.010 [-0.016, +0.036] | +0.018 [-0.041, +0.079] | +0.013 [-0.047, +0.066] | Fail |
| NFL direct EPA matchup | +0.021 [-0.002, +0.043] | +0.026 [-0.022, +0.075] | +0.048 [-0.002, +0.099] | Fail |
| CFB cold start | -0.010 [-0.032, +0.011] | -0.007 [-0.074, +0.069] | +0.001 [-0.042, +0.045] | Fail |
| CFB direct matchup | +0.0002 [-0.0001, +0.0005] | +0.0002 [-0.0003, +0.0007] | +0.0003 [-0.0002, +0.0007] | Fail |
| NBA missingness | +0.001 [-0.007, +0.011] | -0.005 [-0.018, +0.006] | +0.018 [-0.008, +0.058] | Fail |
| NBA cold start | -0.003 [-0.007, +0.001] | +0.004 [-0.001, +0.009] | -0.008 [-0.019, +0.004] | Fail |
| NBA rest-density | +0.003 [-0.007, +0.018] | +0.012 [-0.013, +0.050] | +0.006 [-0.005, +0.018] | Fail |

CFB's missingness block is identical to baseline because the projection has no null cells. Combined blocks also failed for all sports. These are feature-block comparisons on reused historical evidence, not promotion decisions.

## Missingness and cold start

The common treatment contract classifies structural, source-era, not-yet-observed, identity/unmatched and anomalous states, with legitimate zero kept separate. Imputation is fold-local and hierarchical: earlier team-season evidence, prior-season team evidence, then the training-league median. An indicator is retained whenever an imputation path is used. Zero is never the generic fallback.

Cold-start weight is `n / (n + 5)`, where `n` is earlier current-season support when that field exists. The experiment revealed an NFL contract gap: `prior_games` does not isolate early current-season support, and no reused 2023/24 row fell below five under that definition. CFB exposes the clearest cold-start population: 38.3% and 39.5% of 2023/24 games had at least one team below five current-season games. NBA rates were 6.6% and 6.3%. The tested shrinkage did not pass, so these policies remain research specifications.

## Injury and personnel readiness

None of the three bound populations contains revisioned, timestamped pregame injury or participation evidence. Actual snaps, minutes, starters and inactive states observed after cutoff cannot be substituted. The required contract is canonical player/team identity; source publication, retrieval and effective times; status vocabulary; revision lineage; expected participation or scenario probability; and source payload digest. The exact sport-specific gaps appear in `INJURY_AVAILABILITY_MATRIX.json`.

## Recommended sequence

1. **NFL:** fit schedule-aware offensive and defensive pass/run EPA team effects using only earlier games. The direct arithmetic contrast tested here was not useful; the next experiment needs a real opponent-adjustment estimator. Freeze the family and shrinkage on Development, then reuse 2023-24 once. Do not add injuries, weather or a new model family in the same test.
2. **CFB:** add effective-dated conference membership and fit chronological schedule strength. Preserve raw missingness and provenance before considering roster/recruiting features.
3. **NBA:** bind a governed team-box population and add possession, pace, shooting, rebounding and turnover efficiency. Player availability comes later through prospective timestamped capture.

The known NBA paired-residual joint baseline's excess one-point-margin behavior remains a distribution issue: prior work measured 7.78% simulated one-point mass versus 4.01% observed. Its close-score correction did not materially improve energy score and remains unselected. This study did not rerun or alter that work.

## Authority and operational status

This branch grants no model, forecast, scheduler, exchange, decision or wagering authority. It made zero provider or sportsbook calls, downloaded zero bytes, spent USD 0, wrote nothing to AISP or the exchange, and did not read sealed or Final OOT evidence. Deployed owners and all existing artifacts remain unchanged.
