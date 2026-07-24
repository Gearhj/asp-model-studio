# Query Planner Decision Matrix

Source of truth: `server/analytics/query_planner.py`'s `plan()` and `decision_matrix_summary()` (also exposed live at `GET /api/analytics/diagnostics/planner`).

| Operation | Rule |
|---|---|
| `schema` | Always metadata-only (Polars lazy schema or in-memory column list) — never a row scan, regardless of source size. |
| `row_count`, `column_profile`, `histogram`, `quantiles`, `grouped_summary`, `category_frequency` | DuckDB pushdown when file-backed (CSV/Parquet) — scans the file, never materializes it fully in Python memory. Bounded pandas when in-memory (workspace/evaluation-result), **rejected** above `pandas_fallback_max_rows` (default 50,000) with guidance to register the dataset to the Dataset Library. |
| `scatter_sample`, `hexbin` | Bounded stratified/reservoir sample or a hexbin density grid — result cardinality is capped at `max_scatter_points` regardless of source size; a 100M-row source and a 100-row source both produce a bounded result. |
| `threshold_curve`, `confusion_matrix_at_threshold` | A bounded threshold table (default up to `max_histogram_bins` points) is computed once from a bounded sample; a single-threshold confusion matrix is recomputed from the same bounded sample without rescanning the source. |
| `regression_diagnostics`, `residual_distribution`, `qq_points`, `error_by_target_band` | Full-population aggregate metrics (MAE/MSE/RMSE/R²) computed from the resolved source; row-level shapes (histograms, Q-Q points, band summaries) computed from a bounded extraction, never the raw full source. |
| `top_outliers` | Authorized bounded rows only — hard row cap (`max_result_rows`), never unbounded. |
| `bounded_rows` | Hard limit + optional sort, rejected outright if the requested limit exceeds `max_result_rows` (no silent truncation to a different number than requested — the caller must ask for pagination explicitly). |
| `psi`, `vsi` | Implemented in `engines/pandas_engine.py` but **not yet wired** through the single-source query contract — see the ADR's "Known limitations" (needs two resolved sources: a baseline and a comparison partition). |
| Any operation against an external distributed engine | Never selectable — `list_configured_engines()` (not a hardcoded list) is checked by the planner and always returns `[]` in this phase; see `distributed_engine_interface.py`. |

## The central rule: result cardinality, not source cardinality

The planner's guardrails (`_AGGREGATE_OPERATIONS` result-size warnings, `BOUNDED_ROWS`'s hard rejection, the scatter/hexbin point cap) are all keyed on **requested result size**, independent of how large the underlying source is. Concretely:

- A 20-bin histogram over a 100,000,000-row Parquet file: **valid**, routed to DuckDB pushdown, produces a 20-row result regardless of source size.
- A request for 2,000,000 raw scatter points: **capped/sampled** to `max_scatter_points` (default 5,000) regardless of whether the source has 10,000 or 10,000,000 rows.
- A `bounded_rows` request for more than `max_result_rows` (default 5,000): **rejected outright** (422), not silently truncated — the caller must paginate or reduce the request.

## Verified with real fixtures

This matrix was validated directly against 1M-row and 5M-row synthetic Parquet fixtures and a 500-column/1000-column wide-schema fixture — see `docs/architecture/PERFORMANCE_REPORT.md` for the measured numbers each row in this table produced.
