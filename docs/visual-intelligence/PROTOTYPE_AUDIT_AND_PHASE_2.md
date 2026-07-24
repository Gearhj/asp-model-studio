# Visual Intelligence Foundation — Prototype Audit, Known Limitations, and Phase 2 Recommendation

## Prototype audit summary

All three prototypes are mounted at `/visual-intelligence-lab` (lazy-loaded, tabbed, does not touch Evaluation/Interpretation/Scoring) and were verified against real trained-model data through the real UI via Playwright (`tests/e2e/visual-intelligence-lab.spec.ts`, 2/2 passing).

| Prototype | Real data used | Verified working | Known gaps |
|---|---|---|---|
| Interactive Distribution Explorer | Workspace dataset via `GET /api/data/get_sample` | Histogram, mean/median/percentile overlays, numeric cutoff → segment metrics via DuckDB-Wasm/streaming fallback, reset | No keyboard-only equivalent for the drag-brush yet beyond the numeric min/max inputs (inputs exist and work, but a dedicated arrow-key stepper was not built) |
| Classification Decision Explorer | `/train/last` raw actual/score arrays (TRAIN partition) | Score distribution with positive/negative overlays, draggable + numeric threshold, confusion matrix, precision/recall/specificity/F1/alert-rate, independently-recomputed ROC AUC | TEST/OOT partition comparison honestly unavailable (Known Constraint #1/#2) rather than fabricated |
| Regression Diagnostic Explorer | `/train/last` raw actual/score arrays (TRAIN partition) | Actual-vs-predicted, residuals-vs-fitted (both with 2D ECharts brush selection), residual histogram, Q-Q plot, absolute-error-by-target-band, segment metrics (MAE/MSE/RMSE/R²/mean&median residual/median absolute error/prediction & actual ranges) | Same TEST/OOT limitation; small-segment R² correctly shows a caution state instead of a misleading number |

Both prototypes correctly **refuse** to render when the active project's problem type doesn't match (`data-testid="wrong-problem-type"`), verified live: opening the Classification Decision Explorer against a regression project shows an honest refusal rather than misleading output, and vice versa.

## Independent verification performed

- Regression: MAE/MSE/RMSE/R² are computed directly from the raw actual/prediction arrays in the browser (not merely displayed from a single trusted backend field) — this mirrors the same independent-recomputation pattern established in the Regression Stage B audit.
- Classification: ROC AUC is computed via an exact Mann-Whitney U statistic from the raw arrays, independently of any backend-reported AUC value, and is explicitly kept out of the threshold-dependent recompute path (it must not change when the user drags the threshold).
- `tests/visualIntelligenceCore.test.mjs` (12 tests) independently verifies the large-data policy math (mean/median/min-max/reservoir sampling) and the adapter logic (residual sign convention, context-mismatch rejection, problem-type assertion).

## Regression/classification terminology isolation — verified live

Both Playwright tests scan the fully-rendered DOM text for cross-contamination:
- Regression Diagnostic Explorer: zero classification-only terms found (confusion matrix, precision, recall, specificity, F1, ROC AUC, positive class, alert rate).
- Classification Decision Explorer: zero regression-only terms found (RMSE, R-squared, residual, Q-Q plot, actual vs. predicted, MAE).

## Known limitations regarding ephemeral scoring results

TEST/OOT scoring results exist only in the Scoring page's own React session state and have no backend retrieval endpoint (Known Constraint #1/#2, confirmed unchanged from the Regression Stage B audit). This phase's prototypes work around that honestly by using `/train/last`'s TRAIN-partition arrays instead of fabricating TEST/OOT data — but this means the "TRAIN/TEST/OOT comparison" and "Prediction PSI"/"VSI" capabilities the original brief describes are **not yet demonstrated** in these prototypes; they would require either (a) a live Scoring session's in-memory data passed into the prototype as a prop, or (b) the scoring-history persistence recommendation below.

## Recommendation for future scoring-history persistence

A minimal backend record (project_id, model_id, partition, scoring_run_id, timestamp, and either the small summary metrics or a pointer to a registered dataset if the user chose to register) would let Visual Intelligence show real TEST/OOT diagnostics without requiring the user to keep the Scoring page's tab open. This was explicitly out of scope for Phase 1 (stop condition #9: do not build a large new scoring persistence subsystem) but is the single highest-leverage backend change for Visual Intelligence Phase 2's regression/classification diagnostic value.

## Phase 2 recommendation

1. Wire a live Scoring-session payload (when available) into the Regression Diagnostic Explorer and Classification Decision Explorer as an optional prop, so TEST/OOT comparison works whenever a user has an open Scoring session — without waiting on the scoring-history backend work above.
2. Add a dedicated "Initializing local query engine..." loading state distinct from "Unavailable" for the DuckDB-Wasm cold-start window (see `DUCKDB_LIFECYCLE_AND_SECURITY.md`).
3. Measure 25,000-row and 100,000-row rendering behavior with an ephemeral (non-committed) generated fixture.
4. Consider splitting `echarts` itself (currently ~797KB in the lazy `VisualIntelligenceLab` chunk) further by tree-shaking unused chart/series types once the prototype set stabilizes.
5. Extend the keyboard-accessible equivalent for the Distribution Explorer's brush beyond the existing numeric min/max inputs (e.g. arrow-key stepping with a visible focus indicator on the brush handles themselves).
6. Revisit whether `echarts-for-react` (installed, currently unused in favor of the hand-built `EChartsPanel`) should replace the hand-built wrapper, or be removed if the hand-built wrapper's finer lifecycle control remains preferred.
