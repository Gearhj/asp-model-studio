# Visual Intelligence Foundation — Performance and Bundle Report (Phase 1)

## Package versions

| Package | Version | License | Notes |
|---|---|---|---|
| `d3` | 7.9.0 (already present) | ISC | unchanged |
| `@types/d3` | 7.4.3 (new) | MIT | replaces a blanket `declare module "d3";` ambient `any` shim that previously widened every d3 import in the codebase to `any` — removed; see "Defects found" |
| `echarts` | 6.1.0 (installed at 5.6.0, upgraded during this stage) | Apache-2.0 | upgraded to close a moderate XSS advisory (GHSA-fgmj-fm8m-jvvx) affecting `<6.1.0`; `echarts-for-react@3.0.6` resolved cleanly against it, no forced/legacy-peer-deps install needed |
| `echarts-for-react` | 3.0.6 (new) | MIT | not used directly in Phase 1 (a hand-built `EChartsPanel` wrapper was built instead for finer lifecycle/ARIA control); kept installed as it remains a reasonable Phase 2 option |
| `@duckdb/duckdb-wasm` | 1.32.0 (new) | MIT | dynamically imported, not statically bundled |

All licenses are permissive (ISC/MIT/Apache-2.0) and compatible with enterprise commercial use; none require source disclosure or copyleft obligations.

## npm audit

Before this stage: 10 vulnerabilities (1 low, 1 moderate, 8 high), all pre-existing in transitive dependencies (`vite`, `rollup`, `react-router`, `postcss`, `minimatch`, `picomatch`, `brace-expansion`, `@babel/core`).
After this stage: 9 vulnerabilities (1 low, 8 high) — the moderate `echarts` XSS advisory was resolved by the 5.6.0→6.1.0 upgrade described above. **Zero new vulnerabilities were introduced** by the newly added packages. The remaining 9 are unrelated to this stage's changes and were not auto-fixed (`npm audit fix --force` was not run, per instructions).

## Bundle impact

- `main-*.js` (app shell, loaded on every page): **~547KB**, unchanged before/after this stage — confirms Visual Intelligence code is fully absent from the unrelated-page startup bundle.
- `VisualIntelligenceLab-*.js` (lazy-loaded only at `/visual-intelligence-lab`): **797KB (269KB gzipped)** — contains ECharts, D3, the three prototypes, and the shared architecture, but NOT DuckDB-Wasm (see below).
- DuckDB-Wasm assets (lazy-loaded only when a query actually needs it, via dynamic `import("@duckdb/duckdb-wasm")` inside `duckdbService.ts`'s `initialize()`):
  - `duckdb-mvp-*.wasm`: 39.4MB (8.78MB gzipped)
  - `duckdb-eh-*.wasm`: 34.2MB (7.71MB gzipped)
  - `duckdb-browser-mvp.worker-*.js`: 845KB
  - `duckdb-browser-eh.worker-*.js`: 773KB
  - `duckdb-browser-*.js` (glue): 199KB (46.6KB gzipped)

These are real numbers from `npm run build`'s Rollup output, not estimates. Splitting DuckDB-Wasm into its own dynamic import (rather than a static one) was a deliberate mid-stage fix — the initial static import put all of the above inside the 990KB `VisualIntelligenceLab` chunk; after the fix it dropped to 797KB and DuckDB's assets became independently fetched only on first real query.

## Timing measurements (this environment: Vite dev server, no production CDN/caching)

| Scenario | Measurement | Source |
|---|---|---|
| DuckDB-Wasm cold start (first query in a session) | ~25–35 seconds | Playwright test needed a 45s poll timeout; a fixed 2.5s wait was confirmed insufficient by direct reproduction |
| DuckDB-Wasm warm query (same session, subsequent queries) | Sub-second | Manual observation during Playwright test iteration |
| Classification Decision Explorer full render + threshold interaction | ~20 seconds end to end (Playwright) | includes page nav, tab switch, chart render, threshold change, metric recompute |
| Regression Diagnostic Explorer full render (5 linked charts) | Included in the ~36s combined 2-test Playwright run | qualitative: no perceptible lag once data arrived |
| `tsc -b` (full project) | Clean, no reported duration issue | — |
| `npm run build` | ~44–68 seconds (varied by run) | full production build including all unrelated pages |

## Row-count scale measurements

This repository's actual seeded test data caps out at **2,477 rows** (regression TRAIN split) and **4,128 rows** (REG_TEST/REG_OOT). All three prototypes were exercised against this real data — comfortably inside the `direct-svg`/`canvas` render-strategy bands (`largeDataPolicy.ts`), never reaching the `aggregate` or `server-query` bands in this stage's actual usage.

**25,000-row and 100,000-row behavior was not measured against a committed fixture** (stop condition: do not commit large generated datasets). The threshold logic itself (`chooseRenderStrategy`, `safeMinMax`, `streamingMeanStd`) is unit-tested against a 200,000-element synthetic array in `tests/visualIntelligenceCore.test.mjs` to confirm it does not crash at that scale (the exact defect class — spreading a large array into `Math.min`/`Math.max` — that caused Predictive Modeling Stage B.7's real production crash). Full end-to-end rendering timing at 25k/100k rows is a Phase 2 recommendation, using an ephemeral (not committed) generated fixture.

## Lower-powered-device concerns

Not measured directly (no such device available in this environment). The DuckDB-Wasm cold-start cost (~25-35s on a capable dev machine) is a legitimate concern on slower hardware/networks — this is the primary reason DuckDB-Wasm is scoped to *only* the one use case that needs it (Distribution Explorer segment aggregation above 2,000 rows) rather than used broadly.

## Whether server aggregation is required at particular scales

Yes, above 100,000 rows per this stage's explicit large-data policy (`SERVER_QUERY_REQUIRED_ABOVE`) — the architecture refuses client-side handling entirely past that point and requires a server-side aggregate endpoint, which does not yet exist for arbitrary ad hoc queries (only the specific existing endpoints like `/train/last`, `/data/get_sample` are available). Building a general server-side aggregation endpoint for Visual Intelligence is a Phase 2 recommendation.
