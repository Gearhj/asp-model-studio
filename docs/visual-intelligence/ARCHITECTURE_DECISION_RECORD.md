# ATLAS Visual Intelligence Foundation — Architecture Decision Record

Status: Accepted (Phase 1). Scope: architecture + three contained prototypes only — no existing chart was replaced, and Evaluation/Interpretation/Scoring were not redesigned.

## Why ECharts for routine production rendering

ATLAS already had zero chart libraries besides bare D3 (`d3@7.9.0`, used directly for three hand-built SVG components). Apache ECharts (Apache-2.0 license, no CDN dependency, self-hosted via npm) gives ATLAS a production-grade charting layer with built-in Canvas rendering (required at scale — see Large-Data Policy), responsive resize, tooltip/legend/theme systems, and an accessible declarative option API, without hand-building axis scales, tick formatting, or hit-testing for every new chart. `echarts-for-react` wraps it for React lifecycle safety. This is now the default for any new production chart.

## Why D3 is limited to analytical interaction and overlays

D3 remains installed and is still used for ATLAS's three existing bespoke SVG charts (unchanged this phase). For *new* work, D3 is deliberately scoped down to what ECharts doesn't express well: precisely-positioned statistical reference lines (mean/median/percentile/identity/zero-residual) computed from real data, draggable thresholds with pixel-exact coordinate math, and brush selection. `src/visual-intelligence/d3Overlays.tsx` renders these as a transparent SVG layer positioned over an ECharts canvas — D3 never owns the base chart or application state.

## Why DuckDB-Wasm is used selectively

DuckDB-Wasm is the heaviest new dependency (a ~35–40MB WASM binary, split into its own lazy-loaded chunk — see Performance section). It is used **only** for the one case that needs ad hoc SQL-shaped aggregation over already-fetched, already-bounded browser data: the Distribution Explorer's selected-segment statistics above the direct-render row threshold (`largeDataPolicy.ts`'s `AGGREGATE_MAX` boundary). Below that threshold, a plain streaming JS pass is cheaper and avoids paying DuckDB-Wasm's cold-start cost at all. Prototypes 2 and 3 never touch DuckDB-Wasm — their data (a single model's training-run arrays) is small enough that direct computation is always correct and fast.

## Why React owns application state

Every prototype is a React component; ECharts and D3 are rendering targets, not state owners. The linked-interaction store (`interactionStore.ts`, Zustand) holds cross-chart state (thresholds, selections, active partition) so React remains the single source of truth for "what is currently selected," with ECharts/D3 as pure renderers of that state.

## Project and user isolation

Every Data Access Layer fetch (`dataAccessLayer.ts`) goes through existing backend-authorized endpoints (`authorize_modeling_scope` on the server) via `credentials: "include"` — the browser-side layer adds no authorization of its own and cannot bypass backend checks. The `VisualIntelligenceProvider` clears DuckDB-Wasm table registrations and resets the interaction store on every `projectId` change (see `VisualIntelligenceContext.tsx`), and `isStaleResult()` rejects an async result whose captured reference no longer matches the current project/dataset/model — closing the "stale query from Project A updates Project B" risk explicitly.

## Pinning datasetId/versionId

`VisualDatasetReference` (`types.ts`) is the only identity a visualization is allowed to resolve data against — never a dataset or model *name*. `referencesMatch()` performs field-by-field comparison, treating an absent field on either side as "not asserted" rather than "matches anything," so a partially-specified reference can still catch a genuine mismatch on the fields it does assert.

## Scoring partitions and ephemeral vs. registered data

`VisualSourceType` distinguishes `workspace` / `registered` / `scoring-session` / `evaluation-result` / `interpretation-result` / `derived` / `server-aggregate`. Every `VisualDataResult` carries `meta.ephemeral: boolean` and the UI is required to disclose it (`EPHEMERAL_SCORING_NOTICE` in `visualizationSpec.ts`). Concretely, this phase's prototypes use `evaluation-result` (`/train/last`'s raw arrays) for Prototypes 2 and 3 because it is the only backend-durable-for-the-session evaluation data available — TEST/OOT scoring results are genuine ephemeral React state on the Scoring page with **no backend retrieval endpoint** (Known Constraint #1/#2), so the prototypes honestly demonstrate against TRAIN only and do not fabricate TEST/OOT persistence.

## When data stays server-side vs. copied into browser memory

`fetchWorkspaceRows()` requests a **server-bounded** sample (`GET /api/data/get_sample?max_rows=`) — the backend caps the row count, not the browser. `fetchTrainingEvaluationResult()` pulls the already-small `raw.<model>.y_true`/`y_score` arrays from `/train/last` (one model's worth of rows, not the full registered dataset). A registered Dataset Library asset's `data_full.csv` is never automatically fetched into the browser by this architecture — only `get_sample`-style bounded previews.

## Aggregation and sampling at scale

See `docs/visual-intelligence/LARGE_DATA_POLICY.md`. In short: ≤2,000 rows render directly (SVG-safe); ≤25,000 force Canvas; ≤100,000 are aggregated (never rendered as raw points); above that, only a server-side query or an honest refusal is permitted. `safeMinMax`/`streamingMeanStd`/`streamingMedian` never spread an array into a function call, closing the exact defect class that crashed Predictive Modeling Stage B.7's scored-output rendering.

## Raw observation identity

`RegressionRow`/`ClassificationRow` carry a `rowId` (currently the row's index within its source array — stable for the lifetime of one fetched result, not across refetches). The Regression Diagnostic Explorer's cross-chart brush selection uses this id to highlight the same observations across linked views.

## Rejecting stale scoring state

`acceptOrRejectContext()` and `isStaleResult()` both compare a captured `VisualDatasetReference` against the currently active one before a result is allowed to update the UI — an in-flight request that resolves after the user has switched project/model is discarded rather than rendered.
