# Execution Engine Guide

## Implemented now

### Server-side DuckDB (`server/analytics/engines/duckdb_engine.py`)
Chosen for every pure-aggregate operation against a file-backed source (CSV/Parquet). A fresh, short-lived connection is opened per query (`open_bounded_connection()`), with `memory_limit`/`threads` set from `resource_governance.LIMITS` immediately, and `autoinstall_known_extensions`/`autoload_known_extensions` disabled so no extension (including `httpfs` for remote URLs) can be pulled in. Files are scanned via `read_parquet`/`read_csv_auto`, never fully loaded before scanning — column pruning and predicate pushdown happen inside DuckDB's own scanner. Filter values are always parameter-bound (`conn.execute(sql, params)`); column/table identifiers are validated against a strict allowlist regex and double-quote-escaped, never taken from arbitrary client text.

### Polars (`server/analytics/engines/polars_engine.py`)
Chosen specifically for wide-table (hundreds-to-thousands of columns) schema retrieval and profiling. `LazyFrame.collect_schema()` inspects structure without planning or executing a query — measurably cheaper than DuckDB's `DESCRIBE` at very wide scale (see Performance Report: 63ms for a 1,000-column schema page vs. requiring a full query plan in DuckDB). Two profile modes are implemented: `lightweight_column_profile` (null count + dtype only) and `deep_column_profile` (full numeric summary) — the wide-table page never auto-runs deep profiling for every column at load.

### pandas fallback (`server/analytics/engines/pandas_engine.py`)
Used only for row-level statistical shaping (regression diagnostics, threshold curves, residual distributions, Q-Q points, error-by-band, PSI/VSI) operating on an already-bounded extract — never the full enterprise-scale source. `query_planner.py` explicitly raises `PlanningRejection` for an in-memory pandas aggregate above `LIMITS.pandas_fallback_max_rows` (default 50,000), directing the caller to register the dataset to the Dataset Library (making it file-backed and DuckDB-eligible) instead of silently attempting an unsafe full-frame pandas operation.

## Extension-ready, not implemented

### Distributed/warehouse connectors (`server/analytics/distributed_engine_interface.py`)
A `Protocol` (`DistributedEngineConnector`) defines the shape a future Spark/Databricks/Snowflake/BigQuery/Redshift/SQL Server/Oracle/Teradata connector would implement: `capabilities()`, `authorize_connection()`, `execute_bounded_aggregate()`, `close()`. `UnimplementedConnector` is a base class whose every method raises `NotImplementedError` — there is no connector today that pretends to work. `CONNECTOR_REGISTRY` is empty; `list_configured_engines()` is the single source of truth the planner and the `/api/analytics/diagnostics/planner` endpoint both call, so nothing in this codebase can silently drift into claiming a distributed engine is available when it isn't.

**Capability negotiation shape for Phase 2:** a real connector would register itself in `CONNECTOR_REGISTRY` keyed by connection type; the planner would gain a new input ("configured external connections for this project's data source") and would choose source-database pushdown only when `capabilities().supports_predicate_pushdown`/`supports_group_by_pushdown`/etc. indicate the requested operation is safe to push down, falling back to DuckDB/Polars otherwise — exactly the same fallback discipline already used between DuckDB and pandas today.

## What was deliberately NOT built this phase

- No query result streaming protocol (results are single JSON responses, bounded by `resource_governance.LIMITS`).
- No multi-node/distributed execution of any kind — single-process, single-machine only.
- No arbitrary SQL acceptance from Visual Intelligence clients (the existing, unrelated `/api/analytics/sql/run` AnalyticsWorkbench feature is untouched and remains a separate, already-scoped feature).
