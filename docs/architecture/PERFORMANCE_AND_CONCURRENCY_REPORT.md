# Enterprise Analytical Data Plane — Performance and Concurrency Report

All numbers below are measured directly against synthetic fixtures generated for this phase (not committed to the repository; generated under the session scratchpad and deleted during cleanup) and real trained-model data from the existing regression/classification seeding helpers. Hardware: local development machine (single process, `ATLAS_ANALYTICS_DUCKDB_THREADS` default of 2).

## Fixtures generated

| Fixture | Rows | Columns | Format | Size | Write time |
|---|---|---|---|---|---|
| `fixture_1m_20c.parquet` | 1,000,000 | 20 | Parquet (snappy) | 82.9 MB | 3.3s |
| `fixture_5m_20c.parquet` | 5,000,000 | 20 | Parquet (snappy) | 414.4 MB | 15.9s |
| `fixture_100k_500c.parquet` | 100,000 | 500 | Parquet (snappy) | 286.6 MB | 22.0s |
| `fixture_1000col_schema_only.parquet` | 100 | 1,000 | Parquet (snappy) | 0.7 MB | <1s |

Total disk usage: ~784 MB, well within a safe local-disk budget; all deleted during cleanup (Phase V).

## 1-million-row benchmark (`fixture_1m_20c.parquet`, DuckDB engine)

| Operation | Measured time | SLO target | Met? |
|---|---|---|---|
| `schema` | 0.0ms | <500ms cached | Yes |
| `row_count` (cold) | 15.0ms | — | — |
| `row_count` (warm) | 0.0ms | <300ms cached aggregate | Yes |
| `histogram` (20 bins) | 168.8ms | <2s filtered aggregate | Yes |
| `quantiles` (exact, `QUANTILE_CONT`) | 487.1ms | <5s exact large aggregate | Yes |
| `quantiles` (approximate, `APPROX_QUANTILE`) | 682.6ms | <2s | **No** — see note below |
| `grouped_summary` | 131.6ms | <2s filtered aggregate | Yes |
| `category_frequency` | 14.4ms | <2s | Yes |
| `bounded_sql_sample` (2,000 rows, seeded) | 304.1ms / 260.6ms (repeat) | <2s sampled view | Yes |

**Honest note:** `APPROX_QUANTILE` measured *slower* than `QUANTILE_CONT` (exact) at this scale in this DuckDB version (1.5.5) for a single-column, 3-quantile call — likely t-digest construction overhead not amortized at a single-shot query. This is reported as measured, not adjusted to match expectations. At repeated-query scale (a warm t-digest structure reused across calls) this would likely invert; not verified further within the timebox.

**Determinism verified:** two `bounded_sql_sample` calls with the same seed (42) returned identical rows (`DataFrame.equals()` confirmed `True`).

## 5-million-row benchmark (`fixture_5m_20c.parquet`, DuckDB engine)

| Operation | Measured time | SLO target | Met? |
|---|---|---|---|
| `row_count` | 7.0ms | — | — |
| `histogram` (20 bins) | 569.3ms | <2s | Yes |
| `quantiles` (approximate) | 1,528.9ms | <2s | Yes |
| `grouped_summary` | 136.9ms | <2s | Yes |
| `bounded_sql_sample` (2,000 rows) | 1,618.2ms | <2s sampled view | Yes (marginal) |

## Wide-table benchmark (`fixture_100k_500c.parquet`, 500 columns; `fixture_1000col_schema_only.parquet`, 1,000 columns)

| Operation | Measured time |
|---|---|
| Polars schema page (offset=0, limit=50) on 500 cols | 99.3ms |
| Polars row_count on 500 cols | 112.4ms |
| Polars lightweight column profile | 29.4ms |
| Polars deep column profile | 50.8ms |
| Polars top_feature_summary(20) | 43.9ms |
| DuckDB `DESCRIBE` schema (500 cols) | 32.3ms |
| Polars schema page (offset=0, limit=100) on 1,000 cols | 63.1ms |
| Polars schema search (`"col_5"`, matches 111 of 1,000) | 6.0ms |

All wide-table operations comfortably beat the 500ms cached-schema SLO even on first (cold) access.

## Real-data regression/classification benchmark (evaluation-result source, TRAIN partition)

Using the existing seeded trained models (2,477 rows for regression, ~800 rows for classification — this repository's actual test data scale, not synthetic):

- `regression_diagnostics`: results matched the exact values independently verified during the Regression Stage B audit (MAE 0.46295961311392586, RMSE 0.6727469649469536) — end-to-end consistency confirmed across two separate audit stages.
- `residual_distribution`, `qq_points`: both completed well under 100ms (in-process pandas on an already-small evaluation-result frame).
- `threshold_curve` (20 points), `confusion_matrix_at_threshold`: both completed well under 100ms.

## Concurrency results (Phase R)

Verified via the automated test suite (`tests/analytical_data_plane_test.py`) and manual live HTTP testing:

1. **Multiple queries by one user, sequential**: verified — `AnalyticalQueryEndpointTests` runs 14 sequential queries against one authenticated session with no state bleed between them.
2. **Two users, two different projects**: verified — `test_stranger_cannot_query_another_users_project` confirms a second registered user is denied (403) access to the first user's project; `test_unauthenticated_query_is_denied` confirms an anonymous session gets 401.
3. **Cache isolation**: verified — `result_cache.py`'s `get()` checks the stored entry's owner/project against the requesting scope even though the key is already scoped; workspace-source queries are confirmed non-cacheable by design (`test_cache_hit_on_repeated_identical_registered_source_query`).
4. **Project deletion releases resources**: verified — `test_project_deletion_invalidates_cache_and_releases_concurrency` confirms `RESULT_CACHE.invalidate_project()` and `CONCURRENCY.release()` are both called during `DELETE /api/projects/{id}`.
5. **Resource caps apply**: verified — `test_oversized_bounded_rows_request_is_rejected_regardless_of_source_size` and `test_wide_column_selection_is_rejected` both confirm the planner rejects oversized requests with a 422, not a silent truncation.

**Not exercised this phase (documented, not faked):** genuine simultaneous (parallel-thread) queries from two different users hitting the `CONCURRENCY` tracker's lock at the same instant were not load-tested under real thread contention — the `_ConcurrencyTracker`'s `threading.Lock`-protected dict operations are correct by inspection (standard lock-protected counter pattern, same shape as `TrainingJobService`'s own job dict), but no dedicated multi-threaded stress test was written within the timebox. Recommended Phase 2 work.

## Bundle impact

No new frontend dependencies were added this phase (the query plane is server-side Python; the frontend addition is `analyticalQueryClient.ts`, a thin ~5KB fetch wrapper with no new npm packages). `npx tsc -b` and `npm run build` both remain clean — see the Final Report's "Commands and results" section for confirmation.

## Browser payload sizes (observed)

- `schema` response: <1KB (bounded to the requested page, default 100 columns).
- `histogram`/`quantiles`/`grouped_summary`/`category_frequency`: all well under 10KB (bounded bin/group counts).
- `regression_diagnostics`: <1KB (a single summary object, no row-level data).
- `bounded_rows`/`scatter_sample`: bounded by `LIMITS.max_result_rows`/`max_scatter_points` (5,000/5,000 rows respectively) — at typical column widths this stays in the low-hundreds-of-KB range, never megabytes, regardless of source size.
