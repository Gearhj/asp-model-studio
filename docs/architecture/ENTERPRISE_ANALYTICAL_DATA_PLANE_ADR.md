# ATLAS Enterprise Analytical Compute and Visualization Data Plane — ADR

Status: Accepted (Phase 1 foundation). This document supersedes the prior assumption (Visual Intelligence Foundation Phase 1) that large datasets should be loaded into the browser or analyzed primarily with DuckDB-Wasm.

## 1. Current-state inventory (Phase A)

Before this phase, ATLAS's analytical execution paths were:

| # | Concern | Finding |
|---|---|---|
| 1 | Workspace-upload storage | In-memory pandas DataFrame in `DATASTORE` (`server/core/dataset_store.py`), scoped by `(user_id, project_id)`. Bounded by `ATLAS_MAX_UPLOAD_ROWS=500,000`, `ATLAS_MAX_UPLOAD_COLUMNS=750`, `ATLAS_MAX_UPLOAD_BYTES=250MB` (`server/main.py`). |
| 2 | Dataset Library storage | JSON registry (`server/artifacts/datasets/registry.json`) + per-version directories holding `data_full.csv`/`data_sample.csv`/`profile.json`/`preview.json` (`server/datasets/dataset_registry.py`). |
| 3 | Dataset version artifact formats | CSV only, before this phase. |
| 4 | CSV reading paths | `pandas.read_csv` throughout (`main.py`, `dataset_registry.py`, `metadata_router.py`). |
| 5 | `data_full.csv` usage | Read in full by `activate_dataset_version` (loads entire file into a pandas DataFrame server-side, then into `DATASTORE`) — the exact "load the whole dataset" pattern this phase must stop being the only path for analytical queries. |
| 6 | Preview/sample APIs | `GET /api/data/get_sample?max_rows=` (bounded, default 5,000), dataset version `preview.json` (small, precomputed). |
| 7 | `DATASTORE` memory behavior | One pandas DataFrame per `(user, project)` scope, never evicted, no size cap beyond upload limits. |
| 8 | Scoring payload behavior | Ephemeral — TRAIN/TEST/OOT scoring results live only in `Step10_Scoring.tsx`'s React state; no backend persistence (Known Constraint carried over from Visual Intelligence Phase 1). |
| 9 | Evaluation payload behavior | `RESULTS.get_last_summary()` — small, in-memory, one training run's `raw.<model>.y_true/y_score` arrays. |
| 10 | TEST/OOT payload behavior | Same as #8 — client-side only. |
| 11 | Checkpoint interactions | `session_checkpoint.py` snapshots `DATASTORE`/`RESULTS` scopes to a small JSON file; large DataFrames are NOT checkpointed (already excluded by design prior to this phase). |
| 12 | Existing SQL execution paths | `POST /api/analytics/sql/run` (`server/analytics/analytics_router.py`) — accepts arbitrary client SQL text against sqlite3-loaded preview rows, an unrelated pre-existing AnalyticsWorkbench feature (not touched by this phase). |
| 13 | Existing Python execution paths | `StepPythonPanel`/notebook export generate read-only reproducibility code; not a live execution engine. |
| 14 | Backend pandas usage | Pervasive — the primary and, before this phase, only general-purpose in-process dataframe engine. |
| 15 | NumPy usage | Pervasive, used directly and via pandas/scikit-learn. |
| 16 | DuckDB usage (before this phase) | None server-side. Browser-side only, via DuckDB-Wasm (Visual Intelligence Foundation Phase 1). |
| 17 | Polars usage | None. |
| 18 | Arrow usage | None server-side (DuckDB-Wasm uses Arrow internally in the browser). |
| 19 | Parquet usage | None. |
| 20 | Response-size limits | Ad hoc per-endpoint (e.g. `get_sample`'s `max_rows`); no unified policy before this phase. |
| 21 | Upload-size limits | See #1. |
| 22 | Browser preview limits | 5,000 rows (`get_sample`), smaller for `preview.json`. |
| 23 | Query timeout behavior | None for analytical/aggregation endpoints before this phase (training jobs have their own timeout handling, unrelated). |
| 24 | Cancellation behavior | Training jobs only (`training_job_service.py`); no analytical-query cancellation existed. |
| 25 | Background-job infrastructure | `TrainingJobService` — in-process dict of jobs keyed by job_id, `threading.Thread` execution, `threading.Event` cancellation. This phase's async query lifecycle (`query_service.py`) directly mirrors this proven pattern. |
| 26 | Caching infrastructure | `workspace_service.py`'s own sha256-keyed EDA cache; no shared/reusable cache utility existed. |
| 27 | Authorization boundaries | `authorize_modeling_scope` (workspace), `require_dataset`/`user_can_access` (Dataset Library), `user_can_access_project` (project-level) — all reused unchanged by this phase's `artifact_resolver.py`. |
| 28 | Audit logging | `audit_event()` (`server/security/security_store.py`), used throughout; reused unchanged for query audit. |
| 29 | Concurrency assumptions | None enforced for analytical work before this phase; training jobs have no explicit per-user concurrency cap either. |
| 30 | Resource/memory controls | Upload limits only (#1); nothing governed in-process pandas operation memory/time before this phase. |

**Scale risk identified:** `activate_dataset_version` (`server/datasets/dataset_router.py`) reads an entire registered CSV into pandas on every activation, with no row-count ceiling beyond the original upload limits. For a dataset near the 500,000-row upload cap, this is already a multi-second, full-memory-materializing operation with no engine alternative, no sampling, and no timeout. This is the concrete instance of the problem this phase's query planner is built to avoid repeating for new analytical/visualization work.

## 2. Core architectural principle

```
Enterprise data source
  → authorized server-side query planner (query_planner.py)
  → execution engine or source pushdown (DuckDB / Polars / bounded pandas)
  → bounded aggregate, sample, or result set (AnalyticalQueryResponse)
  → browser visualization (Visual Intelligence Data Access Layer)
```

Visualizations query this data plane. They do not load the enterprise dataset into the browser. DuckDB-Wasm remains available client-side as a bounded accelerator for already-fetched, already-bounded extracts (Visual Intelligence Phase 1's Distribution Explorer use case) — it is never the primary computation engine for enterprise-scale data.

## 3. Query planner responsibilities

`server/analytics/query_planner.py`'s `plan()` chooses a strategy from `PlannerInputs`, which include operation type, whether the source is file-backed, file format, selected-column count, and **requested result cardinality** — not source row count alone. A 20-bin histogram over a 100M-row Parquet file is valid DuckDB pushdown; a request for 2 million raw scatter points is capped/sampled regardless of source size. See `docs/architecture/QUERY_PLANNER_DECISION_MATRIX.md`.

## 4. Execution-engine selection — IMPLEMENTED NOW

- **Server-side DuckDB** (`engines/duckdb_engine.py`): the default for every pure-aggregate operation (`schema`, `row_count`, `column_profile`, `histogram`, `quantiles`, `grouped_summary`, `category_frequency`) against a file-backed source (CSV or Parquet), via `read_parquet`/`read_csv_auto` — DuckDB scans the file, it does not require the file to fit in Python process memory. Also used to extract a **bounded** sample (`bounded_sql_sample`, `bounded_rows`) before row-level shaping.
- **Polars** (`engines/polars_engine.py`): lazy schema retrieval and profiling for wide tables (`get_schema_paginated`, `lightweight_column_profile`, `deep_column_profile`, `top_feature_summary`) — chosen specifically because `LazyFrame.collect_schema()` inspects structure without planning or executing a query, which is measurably useful at the 500–1,000 column scale (see Performance Report).
- **pandas fallback** (`engines/pandas_engine.py`): used for row-level statistical shaping (regression diagnostics, threshold curves, residual distributions, Q-Q points, error-by-band, PSI/VSI) that operate on an already-bounded extract, never the full source. `query_planner.py` explicitly rejects an in-memory pandas aggregate request above `LIMITS.pandas_fallback_max_rows` (default 50,000), directing the caller to register the dataset to the Dataset Library so it becomes file-backed and DuckDB-eligible instead.

## 5. Source pushdown

Implemented for local file sources only in this phase (DuckDB's `read_parquet`/`read_csv_auto` against server-resolved, allowlisted paths). External source-database pushdown (a live warehouse connection) is **extension-ready, not implemented** — see §7.

## 6. Distributed-engine extension points — EXTENSION-READY, NOT IMPLEMENTED

`server/analytics/distributed_engine_interface.py` defines a `Protocol` (`DistributedEngineConnector`) and an `UnimplementedConnector` base class whose every method raises `NotImplementedError`. `CONNECTOR_REGISTRY` is empty. `list_configured_engines()` — called by the planner and the diagnostics endpoint, never hardcoded — always returns `[]` today. No Spark/Databricks/Snowflake/BigQuery/Redshift/SQL Server/Oracle/Teradata connector exists; none is claimed as available anywhere in API responses. See `docs/architecture/EXECUTION_ENGINE_GUIDE.md`.

## 7. Arrow interchange

PyArrow is installed and used directly by `parquet_service.py` (streaming CSV→Parquet materialization via `pyarrow.csv`/`pyarrow.parquet`, never loading the full CSV into a single pandas DataFrame first). Arrow IPC as a wire response format for bounded tabular results (Phase F item 8) is **not implemented this phase** — JSON remains the only response encoding; see §24 "Known limitations."

## 8. Parquet as preferred registered analytical format

`materialize_parquet_for_version()` (`server/analytics/parquet_service.py`) is an **explicit, on-demand** action (`POST /api/analytics/datasets/{id}/versions/{id}/materialize-parquet`) — registering or uploading a dataset never automatically triggers Parquet conversion (stop condition #8). When a version has a materialized `analyticalParquetPath`, `artifact_resolver.py` prefers it over the CSV for query execution; the CSV remains the artifact of record and is never deleted or modified.

## 9. CSV as ingestion and export format

Unchanged — CSV remains ATLAS's upload/registration/export format throughout. This phase adds Parquet as an *additional*, optional, on-demand analytical representation, never a replacement.

## 10. Exact versus approximate computation

`AnalyticalQueryResponse.exact`/`.approximate` are always populated. Quantiles default to DuckDB's `APPROX_QUANTILE` (t-digest) unless `approximationPolicy=exact_required`, in which case `QUANTILE_CONT` (exact, O(n log n) sort) is used instead — both are implemented and were benchmarked directly against the 1M/5M-row fixtures (see Performance Report).

## 11. Aggregate versus sample versus row-level result

Every response's `meta` (`sampled`, `sampleMethod`, `resultRowCount` vs `sourceRowCount`) makes this explicit. See `docs/architecture/SAMPLING_AND_APPROXIMATION_POLICY.md`.

## 12. Asynchronous query lifecycle

`query_service.py`'s `JOBS` store mirrors `TrainingJobService`: in-process dict keyed by `queryId`, `threading.Event` per job for best-effort cancellation, `threading.Thread` for operations `is_heavy()` flags. Fast/bounded operations (the large majority) complete inline in the same request/response cycle rather than round-tripping through queued/polling needlessly.

## 13. Caching

`server/analytics/result_cache.py` — an in-process, per-worker, dict-based bounded cache (500 entries, 2MB/entry cap, 300s default TTL), consistent with the rest of ATLAS's in-process state (`DATASTORE`/`RESULTS`/`TRAINING_JOBS` are all in-process dicts; no external cache service — e.g. Redis — is configured anywhere in this repository, and Phase K explicitly says not to introduce one). **Known limitation:** not shared across multiple worker processes in a multi-process deployment — see §24.

## 14. Cancellation

`POST /api/analytics/queries/{query_id}/cancel` sets a `threading.Event`; the background thread checks it both before and after `execute_query()` runs and marks the job `cancelled` rather than `completed` if set. This is best-effort (a DuckDB query already mid-execution is not force-killed mid-scan in this phase — see §24), matching the same honesty standard `TrainingJobService` already uses for training-job cancellation.

## 15. Timeout behavior

`resource_governance.Deadline` provides a wall-clock deadline helper; `AnalyticalQueryRequest.timeoutSeconds` is capped at `LIMITS.max_query_duration_seconds`. DuckDB connections do not yet have a hard per-query kill timer wired to this deadline in this phase (see §24) — the deadline is enforced at the planner/dispatch boundary today, not mid-scan.

## 16. Resource governance

`server/analytics/resource_governance.py` — all limits environment-variable-overridable (`ATLAS_ANALYTICS_*`), covering result rows/bytes, selected columns, histogram bins, group cardinality, scatter points, concurrent queries per user/project, query duration, DuckDB memory/thread limits, pandas fallback row ceiling. See `docs/architecture/RESOURCE_GOVERNANCE_GUIDE.md`.

## 17. Authorization

Every query re-authorizes server-side via the exact same functions the rest of ATLAS already uses (`authorize_modeling_scope`, `require_dataset`, `user_can_access_project`) — `artifact_resolver.py` is the single choke point, and no client-supplied path or ownership claim is ever trusted. See `docs/architecture/QUERY_SECURITY_GUIDE.md`.

## 18. Lineage

Parquet materialization preserves `datasetId`/`versionId`/schema/target/row count/source lineage untouched — it only *adds* `analyticalParquetPath`/`sourceChecksumSha256`/`parquetRowCount` fields to the existing version metadata, never replacing or removing any existing field.

## 19. Query audit

Every query execution and every denial calls `audit_event()` with `queryId`, operation, engine, pushdown, exact/approximate, sample method, duration, cache status, dataset/version identity — never raw row values. See `docs/architecture/QUERY_AUDIT_GUIDE.md`.

## 20. Result identity

`AnalyticalQueryResponse.queryId`/`sourceIdentity`/`datasetId`/`versionId`/`partition`/`modelId`/`scoringRunId` together identify what a result actually represents; `queryId` is server-generated (client may supply `clientRequestId` for its own correlation, never trusted as `queryId` itself).

## 21. Concurrency

`resource_governance.CONCURRENCY` tracks in-flight queries per `(user_id)` and `(project_id)` with a lock-protected dict; `try_acquire`/`release` are called around every query, including the async path, and released on project deletion (`persistence_router.py`).

## 22. Failure recovery

Any engine exception during async execution is caught and recorded as `status=failed` with the error message (never a hung "running" job forever) — mirrors `TrainingJobService`'s own failure-isolation pattern.

## 23. Browser data boundaries / DuckDB-Wasm's limited role

Unchanged from Visual Intelligence Phase 1's architecture except for priority: the Data Access Layer now prefers server aggregate → server sample → cached result → bounded browser calculation → DuckDB-Wasm (only for already-local, already-bounded extracts) → honest unsupported state. DuckDB-Wasm is never activated merely because a row count exceeds a fixed threshold. See §"Phase N" in the final report and `docs/architecture/VISUAL_INTELLIGENCE_INTEGRATION_GUIDE.md`.

## 24. Known limitations (honest, not implemented this phase)

- **Arrow IPC wire format**: not implemented; all responses are JSON. Recommended Phase 2 work for large bounded tabular results where JSON overhead is measurable.
- **Multi-process cache sharing**: the result cache is per-worker-process; a multi-process/multi-node deployment would need a shared cache (Redis or similar) to get cross-process hit rates. Not built here — Phase K explicitly says not to introduce a new external cache service in this phase.
- **Mid-scan cancellation**: `cancel` prevents a queued/not-yet-started job from running and prevents a completed background result from being surfaced, but does not send an interrupt into an already-executing DuckDB query. DuckDB queries in this phase's fixtures complete in well under a second to a few seconds (see Performance Report), so this gap is low-risk at measured scale but should be revisited before very large (multi-minute) query support is promised.
- **PSI/VSI end-to-end wiring**: `pandas_engine.psi()`/`vsi()` are implemented and unit-tested against two explicit series, but are not wired through the single-source `AnalyticalQueryRequest` contract, because they conceptually need two resolved sources (a baseline partition and a comparison partition), and ATLAS's TEST/OOT scoring results have no durable backend retrieval path yet (unchanged Known Constraint from Visual Intelligence Phase 1). Documented, not faked.
- **Distributed engines**: see §6.
