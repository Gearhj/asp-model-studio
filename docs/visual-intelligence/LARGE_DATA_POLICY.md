# Visual Intelligence Large-Data Policy

Source of truth: `src/visual-intelligence/largeDataPolicy.ts`.

| Row count | Strategy | Rendering | Notes |
|---|---|---|---|
| ≤ 2,000 | `direct-svg` | SVG-safe, every point rendered | D3 overlays cheap at this scale |
| 2,001–25,000 | `canvas` | Forces ECharts `renderer: "canvas"` | SVG DOM node count becomes the bottleneck first |
| 25,001–100,000 | `aggregate` | Pre-aggregated only (histogram bins, decile summaries) | Raw points are never rendered; DuckDB-Wasm or one streaming pass computes the aggregate |
| > 100,000 | `server-query` | Refused client-side | Requires a server-side query or an honest "unsupported" state |

## Rules enforced in code

1. **Never spread a large array into `Math.min`/`Math.max`/a constructor/a function call.** `safeMinMax()` is a linear scan; verified against a 200,000-element array in `tests/visualIntelligenceCore.test.mjs` (this is the exact defect class that crashed Predictive Modeling Stage B.7's scored-output rendering — call-stack overflow past ~100k–500k spread arguments depending on the JS engine).
2. **No unnecessary full-row copies.** `streamingMeanStd` (Welford's algorithm) computes mean/variance in one pass without building an intermediate squared-deviation array.
3. **Registered Dataset Library data is never auto-loaded.** The Data Access Layer only ever requests a server-bounded sample (`GET /api/data/get_sample?max_rows=`); nothing in this architecture fetches a full `data_full.csv`.
4. **Sampling is disclosed, never silent.** `VisualDataSourceMeta.sampled` is populated by every Data Access Layer fetcher; `sampleForDirectRender()` always sets `sampled: true` when it reduces a result via `reservoirSample()` (uniform selection probability, verified in tests).
5. **Selection accuracy under sampling.** `reservoirSample()` uses the standard reservoir algorithm (each source row has equal probability of appearing in the sample regardless of source size) rather than head-N truncation, which would bias toward whatever order the backend happened to return rows in.

## What this phase measured

See `PERFORMANCE_REPORT.md` for concrete timings at the row counts actually available in this repository's seeded test data (~2,477–4,128 rows per partition). A synthetic 100,000-row measurement was not generated as a committed repository artifact (stop condition: do not commit large generated datasets) — the thresholds above are implemented and unit-tested, but 100k-row *rendering* timing is a Phase 2 follow-up using an ephemeral, non-committed fixture.
