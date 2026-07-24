# DuckDB-Wasm Lifecycle and Security Guide

Source: `src/visual-intelligence/duckdb/duckdbService.ts`.

## Lifecycle

1. **Lazy, dynamic import.** `@duckdb/duckdb-wasm` is imported with `await import(...)` inside `initialize()`, not statically at module load. This puts it in its own Rollup chunk, separate from the Visual Intelligence Lab bundle itself — confirmed by build output: `duckdb-mvp-*.wasm` (39.4MB), `duckdb-eh-*.wasm` (34.2MB), and two worker JS files (770–845KB) all appear as independent chunks, fetched only when `initialize()` actually runs.
2. **Self-hosted assets, not CDN.** The four DuckDB-Wasm assets (mvp/eh wasm + their workers) are imported via Vite's `?url` suffix directly from the installed npm package and served from ATLAS's own origin. There is no `<script src="https://cdn...">` tag and no runtime fetch to a third-party host.
3. **Worker-isolated.** `duckdb.selectBundle()` picks the best-supported bundle for the browser, a `Worker` is constructed from the bundle's worker URL, and `AsyncDuckDB` wraps it — every query executes off the main thread.
4. **Single shared connection.** `getConnection()` lazily creates one `AsyncDuckDBConnection` and reuses it; `runQuery()` always uses `conn.prepare(sql)` plus parameter binding for any user-controlled value.
5. **Teardown.** `clearProjectTables(projectId)` drops every table whose scoped name starts with that project's prefix — called by `dataAccessLayer.clearVisualDataForProject()`, itself called by `VisualIntelligenceProvider` on every `projectId` change (project switch) and available for sign-out. `disposeDuckDb()` fully closes the connection and terminates the underlying `AsyncDuckDB`/worker for a complete teardown.

## Security boundaries

- **No ambient authorization of its own.** `duckdbService.ts` never reads cookies, calls the backend, or resolves identity. The only way data enters it is `registerTable(projectId, tableName, rows)`, and every caller of that function is the Data Access Layer, which only supplies rows already fetched through an `authorize_modeling_scope`-gated backend endpoint. This means DuckDB-Wasm cannot be used as an authorization bypass — it has nothing to bypass with, by construction.
- **No file access, no network, no remote extensions.** The default browser DuckDB-Wasm build has no filesystem or network I/O surface. This service never calls `LOAD`/`INSTALL` for any extension and never opens a remote HTTP-backed table.
- **Identifier safety.** Table names are built as `t_${projectId}__${tableName}`, with both components stripped to `[a-zA-Z0-9_]` before ever reaching SQL text (defense in depth — `projectId` is a backend-issued id, not free client text, but this removes any doubt).
- **Parameterization.** `runQuery(sql, params)` passes `params` through DuckDB's own prepared-statement binding; no caller string-concatenates a user-supplied *value* into SQL text. (Column/table *identifiers* are not parameterizable in SQL by design — see the note in `computeSegmentAggregate()` about why the field name comes from a fixed, developer-controlled selector, not arbitrary user text.)

## What copies of raw data exist in browser memory, and when they're removed

| Copy | Created by | Removed by |
|---|---|---|
| Fetched workspace rows (JS array, up to 5,000 rows) | `fetchWorkspaceRows()` | Garbage-collected when the Distribution Explorer unmounts or refetches (React state) |
| DuckDB-Wasm table (`t_<project>__distribution_source`) | `registerTable()`, only when row count exceeds `DIRECT_RENDER_MAX` | `clearProjectTables(projectId)` on project switch; `disposeDuckDb()` on full teardown |
| Training evaluation rows (`y_true`/`y_score` arrays, one model) | `fetchTrainingEvaluationResult()` | Garbage-collected on component unmount/refetch (React state) |

No raw row data is ever written to `localStorage` by this module (Phase M requirement).

## First-query cost (measured)

The first DuckDB-Wasm query in a session pays the full cost of fetching and instantiating the ~35–40MB WASM binary. In this environment (Vite dev server, no production caching headers configured), this took **~25–35 seconds** end to end the first time (measured via the Playwright test needing a 45s poll timeout where a fixed 2.5s wait was insufficient). Subsequent queries in the same session are near-instant (module cached in memory). See `PERFORMANCE_REPORT.md`.

**UX finding (not fixed this phase):** the Distribution Explorer's segment-metric tiles show "Unavailable" during this cold-start window, which is visually indistinguishable from a genuine no-data state. A dedicated "Initializing local query engine..." loading state is recommended for Phase 2.
