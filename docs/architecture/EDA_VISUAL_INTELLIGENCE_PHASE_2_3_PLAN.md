# EDA Visual Intelligence — Phase 2 and Phase 3 Architecture Plan

Status: Proposed
Date: 2026-07-27
Scope: Predictive Modeling, Exploratory Data Analysis only

## 1. Purpose

This document defines the component, state, data, performance, accessibility, and test architecture for the second and third phases of the ATLAS EDA Visual Intelligence program.

It assumes Phase 1 owns and finishes only the shared foundations and first upgraded views:

- shared chart-motion tokens and reduced-motion behavior;
- the full-population Predictor Distribution Explorer;
- shared EDA visual-selection state;
- the interactive correlation matrix;
- animated VIF risk bars; and
- target-source enforcement for every EDA surface touched by Phase 1.

Phase 2 and Phase 3 must build on those primitives. They must not create a second motion system, selection store, data-access path, export format, or predictor-authorization rule.

## 2. Current integration anchors

The current filesystem establishes these integration points:

- `src/steps/Step02_EDA.tsx` owns the six EDA tabs, lazy section requests, predictor selection, relationship selection, and the existing inline histogram, correlation, VIF, and pairwise renderers.
- `server/eda/workspace_service.py` produces the governed Overview, Target, Predictors, Relationships, Stability, and Findings section payloads.
- `server/eda/eda_router.py` authorizes EDA requests and exposes the workspace and compatibility routes.
- `src/visual-intelligence/EChartsPanel.tsx` owns ECharts lifecycle, resize, renderer choice, status states, and chart export access.
- `src/visual-intelligence/d3Overlays.tsx` contains reusable D3 reference-line and brush concepts.
- `src/visual-intelligence/interactionStore.ts` is a general Visual Intelligence store, but its current single-visualization scope is not a substitute for an EDA-wide, cross-tab selection context.
- `src/components/eda/TargetIntelligenceWorkspace.tsx` and `src/components/eda/TargetByPredictorPanel.tsx` already provide server-aggregated target analysis and must be extended rather than duplicated.
- The Enterprise Analytical Data Plane is the preferred execution path for bounded aggregation and governed artifact scans. Browser DuckDB is a fallback for already-resident, already-bounded data only.

The current static `CorrelationGrid`, `VifBarChart`, `PairwiseMatrix`, `MiniHistogramValues`, and `ScatterCell` functions in `Step02_EDA.tsx` are migration points. Phase 2 and Phase 3 should extract replacements into focused components rather than expanding the step file further.

## 3. Phase boundary

| Capability | Phase 1 | Phase 2 | Phase 3 |
| --- | --- | --- | --- |
| Shared motion and reduced motion | Complete | Reuse | Reuse |
| Predictor distribution and range brush | Complete | Link pairwise/target findings | Link advanced cross-filters |
| Correlation matrix | Complete | Add correlated-feature network | Feed advanced relationship modes |
| VIF | Animated risk view | Contributor detail, decision capture, non-mutating reduction simulation | Optional integration with advanced feature scenarios |
| Pairwise | Existing bounded builder retained | Linked brushing, density, overlays, pinned points, exact-state export | Cross-filter with 3D and stability views |
| Target visuals | Existing Target workspace retained | Animated balance, prevalence, confidence interval, predictor-band linking | Cross-filter by time/segment |
| Findings | Existing decision/evidence behavior retained | Visual findings summary and before/after evidence surface | Cross-filtered evidence comparisons |
| 3D/PCA | Explicitly excluded | Explicitly excluded | 2D/hexbin/3D/PCA relationship explorer |
| Stability/segments | Honest existing empty state retained | Honest existing empty state retained | Governed time/segment visual suite |
| Advanced cross-filtering | Range/variable/pair foundations only | Pairwise and target linking | Time, segment, pairwise, 3D, and findings coordination |

## 4. Architectural rules

1. The browser receives bounded aggregates or explicitly bounded row samples, never an enterprise-scale predictor column.
2. The backend is authoritative for target, event mapping, eligible predictors, target-source exclusions, row counts, and population/subset labels.
3. `bad_flag` is never an eligible predictor and a deterministic source such as `RiskPerformance` is rejected before analysis, not merely hidden in a selector.
4. Hover state is temporary. Pinned selections survive tab changes until cleared or invalidated by a dataset/target change.
5. A visual filter never mutates `DATASTORE`, a feature manifest, a workflow decision, or a registered dataset.
6. Any action that changes a governed workflow decision requires a separate explicit confirmation path.
7. All charts use the Phase 1 motion tokens and the same reactive reduced-motion hook.
8. Expensive visual modes are loaded only when selected and do not execute on initial EDA entry.
9. Every chart has a textual summary and a table or export alternative.
10. Exported evidence records the exact visual state, source identity, population scope, sample disclosure, and target-source exclusions.

## 5. Component architecture

### 5.1 Shared EDA shell

Phase 1 should leave an EDA-scoped provider around the tab content. Phase 2 and Phase 3 extend that provider; they do not add nested stores with competing scopes.

Proposed files:

- `src/components/eda/visual/EDAVisualSelectionContext.tsx`
- `src/components/eda/visual/EDAVisualScopeBadge.tsx`
- `src/components/eda/visual/EDAChartActions.tsx`
- `src/components/eda/visual/EDAChartStatus.tsx`
- `src/components/eda/visual/EDADataTableAlternative.tsx`
- `src/components/eda/visual/edaVisualTypes.ts`

Responsibilities:

- reset visual state when project, dataset version/fingerprint, target, or feature-manifest version changes;
- distinguish `hover` from `pinned`;
- expose one `Clear selection` action;
- announce pinned-selection changes through an ARIA live region;
- label all metrics as full population or selected subset;
- serialize current state for PNG/CSV/JSON/evidence export; and
- reject updates whose response scope does not match the current scope.

### 5.2 Phase 2 components

#### Correlated-feature network

Proposed file: `src/components/eda/visual/CorrelatedFeatureNetwork.tsx`

Inputs:

- Phase 1 correlation columns and matrix;
- current absolute-correlation threshold;
- current matrix ordering;
- pinned variable/pair; and
- VIF rows.

Behavior:

- derive links from the already bounded correlation matrix;
- encode absolute correlation as link width and sign through color plus dash/marker treatment;
- allow drag without changing analytical values;
- highlight neighbors on hover;
- pin a variable on click;
- keep threshold and selected variables synchronized with the matrix; and
- export node positions only as presentation state, separate from analytical state.

Rendering policy:

- SVG is acceptable up to 50 nodes and a bounded link count;
- thresholding must occur before marks are created;
- do not render a complete graph;
- use deterministic initial positions so screenshots are stable; and
- stop force simulation before the chart reports `ready-for-capture`.

#### Linked pairwise explorer

Proposed files:

- `src/components/eda/visual/PairwisePlotBuilder.tsx`
- `src/components/eda/visual/PairwiseCell.tsx`
- `src/components/eda/visual/PairwisePointDetails.tsx`

Behavior:

- preserve the six-variable hard cap;
- use the correlation matrix’s pinned pair as the default pairwise selection;
- highlight points matching the Phase 1 predictor-range selection;
- allow rectangular brushing and pinned point details;
- provide scatter and density modes;
- animate diagonal histograms with Phase 1 motion primitives;
- offer optional regression/LOESS overlays only when the server returns the required bounded coefficients/curve;
- expose reset and exact-state export; and
- display returned rows, source population rows, sampling method, seed, and class counts.

Canvas is the default for dense cells. SVG is reserved for small samples and overlays. Point identity must come from a backend-issued opaque stable row key; the browser must not invent identity from array position.

#### Target visual upgrade

Proposed files:

- `src/components/eda/visual/TargetBalanceVisual.tsx`
- `src/components/eda/visual/TargetPrevalenceGauge.tsx`
- `src/components/eda/visual/TargetPredictorBandChart.tsx`

These components extend `TargetIntelligenceWorkspace`; they do not create another Target tab or issue a second IV calculation.

Behavior:

- animate class counts, prevalence, and confidence intervals;
- preserve explicit positive and negative class labels;
- label the full-population denominator;
- synchronize a selected target-predictor band with the Phase 1 histogram range;
- use the existing Wilson interval and target-intelligence contracts;
- transition when the governed event definition changes; and
- state rare/common-event context without converting signal strength into a leakage verdict.

#### Visual findings surface

Proposed files:

- `src/components/eda/visual/EDAFindingSummary.tsx`
- `src/components/eda/visual/EDAFindingComparison.tsx`
- `src/components/eda/visual/EDAFindingEvidenceLink.tsx`

The visual surface sits above the existing Findings decision controls. It summarizes, but does not replace:

- duplicate records;
- target-source exclusions;
- unusually strong IV review;
- material multicollinearity;
- bureau special-value treatment;
- unresolved reviewer decisions; and
- downstream destination/status.

Before/after visuals are allowed only when both states have explicit dataset/feature-manifest identities. They must never imply that an unconfirmed preview is the governed post-treatment state.

#### VIF contributor and reduction review

Proposed files:

- `src/components/eda/visual/VifRelationshipDetail.tsx`
- `src/components/eda/visual/VifReductionSimulator.tsx`

The simulator is non-mutating. It may:

- nominate one temporary removal candidate;
- request a backend recomputation or explicitly labeled estimate;
- compare current and simulated VIF values; and
- capture a proposed retain/drop/combine decision.

It may not alter selected predictors until a separate reviewer confirmation is submitted through the governed feature-decision workflow.

### 5.3 Phase 3 components

#### Relationship explorer

Proposed files:

- `src/components/eda/visual/RelationshipExplorer.tsx`
- `src/components/eda/visual/Scatter2DView.tsx`
- `src/components/eda/visual/HexbinDensityView.tsx`
- `src/components/eda/visual/Scatter3DView.tsx`
- `src/components/eda/visual/PcaProjectionView.tsx`

Modes:

- 2D scatter;
- hexbin/density;
- 3D scatter; and
- PCA 3D projection when valid.

Rules:

- 2D is the default;
- selected x/y/z variables survive mode changes;
- 3D code and its renderer dependency are dynamically imported only after explicit activation;
- a bounded-sample badge remains visible in 3D;
- camera reset is deterministic;
- target color, optional size, opacity, hull, and density controls are explicit;
- a 2D/table alternative is always available; and
- PCA is computed on the backend from authorized predictors with returned explained-variance metadata.

The implementation should evaluate ECharts GL at the Phase 3 dependency gate. No Phase 1 or Phase 2 code should add a 3D dependency speculatively.

#### Stability and segment suite

Proposed files:

- `src/components/eda/visual/StabilityVisualSuite.tsx`
- `src/components/eda/visual/EventRateTrend.tsx`
- `src/components/eda/visual/PopulationVolumeTrend.tsx`
- `src/components/eda/visual/DriftHeatmap.tsx`
- `src/components/eda/visual/CohortRibbon.tsx`
- `src/components/eda/visual/SegmentTreemap.tsx`
- `src/components/eda/visual/SmallMultipleTrends.tsx`
- `src/components/eda/visual/BeforeAfterComparison.tsx`

The suite mounts only when the backend returns an explicitly governed time or segment field. It must preserve the current honest empty state when neither exists.

No numeric column may be guessed as a date, and no arbitrary high-cardinality category may be treated as a business segment.

#### Advanced cross-filter coordinator

Proposed file: `src/components/eda/visual/useEDACrossFilterCoordinator.ts`

Responsibilities:

- translate pinned visual state into an immutable query specification;
- debounce brush/date-range updates;
- cancel superseded requests;
- reject stale scope identities;
- update aggregate consumers independently;
- never make one chart wait for another chart; and
- preserve the difference between full-population metrics and selected-subset metrics.

## 6. Linked-state evolution

The store remains transient UI state. It is serializable for evidence/export but not written into the workflow dataset.

```ts
type EDAVisualScope = {
  userId: string;
  projectId: string;
  datasetVersion: string;
  datasetFingerprint: string;
  featureManifestVersion: string | null;
  target: string;
  eventValue: unknown;
};

type EDAVisualSelection = {
  selectedVariable: string | null;
  selectedRange: { variable: string; min: number; max: number } | null;
  selectedQuantile: { variable: string; index: number; min: number; max: number } | null;
  pinnedPair: { x: string; y: string } | null;
  selectedVifVariable: string | null;

  // Phase 2 additions
  selectedPointIds: string[];
  selectedNetworkNode: string | null;
  selectedFindingIds: string[];
  pairwiseBrush: { x: string; y: string; x0: number; x1: number; y0: number; y1: number } | null;

  // Phase 3 additions
  timeRange: { field: string; start: string; end: string } | null;
  segmentValues: { field: string; values: string[] } | null;
  relationshipMode: "scatter2d" | "hexbin" | "scatter3d" | "pca3d";
  camera3d: { alpha: number; beta: number; distance: number } | null;
};

type EDAVisualHover = {
  variable: string | null;
  pair: { x: string; y: string } | null;
  pointId: string | null;
  findingId: string | null;
};
```

State rules:

- hover never overwrites a pinned selection;
- `Clear selection` clears selection but preserves display preferences such as threshold and mode;
- changing target or dataset identity clears all selection and cached view results;
- a selected quantile sets the corresponding numeric range;
- a histogram range highlights but does not remove nonmatching pairwise points unless the user explicitly enables subset mode;
- clicking a correlated pair updates x/y but not the governed feature list;
- selecting a VIF variable highlights its correlation partners;
- time and segment filters apply only to consumers that declare support; and
- every derived metric carries `metricScope: "full_population" | "selected_subset"`.

## 7. Backend data contracts

All Phase 2 and Phase 3 requests must include or resolve:

- `project_id`;
- current target and event mapping;
- immutable dataset/version identity or workspace fingerprint;
- feature-manifest version when available; and
- only server-authorized predictor names.

Every response must include:

- `scope_identity`;
- `row_count` for the source population;
- `analyzed_row_count`;
- `metric_scope`;
- `exact` and `sampled`;
- sampling method, limit, seed, and class counts when sampled;
- `target_source_excluded`;
- `duration_ms`;
- stable calculation/version identifiers; and
- bounded payload-size metadata.

### 7.1 Pairwise sample contract

Proposed endpoint: `POST /api/eda/relationship-sample`

Request:

```json
{
  "project_id": "project-id",
  "features": ["x", "y", "z"],
  "target": "bad_flag",
  "limit": 5000,
  "sampling": { "method": "stratified", "seed": 42 },
  "filters": []
}
```

Response:

```json
{
  "ok": true,
  "features": ["x", "y", "z"],
  "rows": [{ "rowKey": "opaque", "x": 1.2, "y": 3.4, "z": 5.6, "targetClass": "1" }],
  "populationRows": 6275,
  "returnedRows": 5000,
  "sampled": true,
  "samplingMethod": "stratified",
  "samplingSeed": 42,
  "classCounts": [{ "class": "1", "count": 2600 }, { "class": "0", "count": 2400 }],
  "targetSourceExcluded": ["RiskPerformance"],
  "scopeIdentity": "opaque",
  "durationMs": 18
}
```

The server rejects the target, deterministic target sources, split/system fields, and predictors outside the authorized manifest.

### 7.2 VIF simulation contract

Proposed endpoint: `POST /api/eda/vif/simulate`

The request names one temporary candidate and a baseline scope identity. The response contains baseline/recomputed values, affected relationships, calculation method, sample/exact disclosure, and no mutation token. A stale baseline scope is rejected.

### 7.3 PCA projection contract

Proposed endpoint: `POST /api/eda/pca-projection`

The server:

- validates 3–25 authorized numeric predictors;
- applies an explicitly reported missing-value policy;
- standardizes using returned center/scale parameters;
- fits PCA deterministically;
- returns at most the governed point limit;
- returns explained variance by component; and
- never includes a target-source field in either fit or projection.

### 7.4 Stability aggregate contract

Proposed endpoint: `POST /api/eda/stability/aggregate`

The request can reference only server-declared `date_candidates` and `segment_candidates`. The response contains bounded time buckets/segments, population counts, event counts/rates, drift statistics, suppressed-small-cell flags, and explicit baseline/comparison periods.

## 8. Performance strategy

### 8.1 Request execution

- Do not compute Phase 2/3 views on initial EDA entry.
- Mount a phase component only when its tab and mode are active.
- Use one request key per source scope, mode, authorized variable set, and filter set.
- Abort superseded predictor, brush, threshold, pair, date, and segment requests.
- Deduplicate identical in-flight requests.
- Prefer server/DuckDB aggregation for full-population summaries.
- Use Polars/DuckDB scans for immutable artifacts and bounded pandas only where the planner permits.
- Browser DuckDB may process only data that is already bounded and disclosed.

### 8.2 Rendering limits

| View | Default renderer | Hard policy |
| --- | --- | --- |
| Correlation network | SVG | Maximum 50 visible nodes; links thresholded before render |
| Pairwise scatter | Canvas | Maximum 6 variables and 5,000 returned rows |
| Pairwise density/hexbin | Canvas | Render bounded bins, not raw enterprise rows |
| 2D scatter | Canvas | Bounded sample or server density |
| 3D scatter/PCA | WebGL | Explicit activation; bounded sample indicator always visible |
| Trends/small multiples | Canvas/SVG | Bounded time buckets and segment count |
| Treemap | Canvas/SVG | Server-capped segment cardinality with disclosed `Other` |

### 8.3 Diagnostics

Record, without exposing data values:

- page shell ready;
- first useful chart;
- active tab ready;
- chart update;
- brush-to-metric response;
- network stabilization;
- pairwise mode switch;
- 3D module download and activation;
- stability query duration; and
- export-ready state.

Diagnostics should use `performance.mark`/`performance.measure` in the browser and `duration_ms` plus engine/cache metadata on the server.

## 9. Accessibility

Every Phase 2/3 view must provide:

- an accessible title and concise text summary;
- keyboard-accessible controls with visible focus;
- a table or downloadable data alternative;
- high-contrast-safe encodings;
- shape, dash, label, or position in addition to color;
- reactive reduced-motion behavior;
- keyboard equivalents for drag and brush actions;
- an announced pinned-selection state;
- a deterministic `Clear selection`;
- no auto-rotating or looping 3D motion; and
- a 2D/table alternative for every 3D view.

Network nodes must be reachable in a logical order, with neighbor count and strongest relationships in their accessible names. Pairwise brushing must have numeric x/y range controls. Treemap and ribbon views require equivalent ranked tables.

## 10. Export and evidence

Each export specification should contain:

```ts
type EDAVisualEvidenceState = {
  schemaVersion: string;
  chartType: string;
  sourceScope: EDAVisualScope;
  metricScope: "full_population" | "selected_subset";
  authorizedVariables: string[];
  targetSourceExcluded: string[];
  selection: EDAVisualSelection;
  display: Record<string, unknown>;
  sample: null | {
    populationRows: number;
    returnedRows: number;
    method: string;
    seed: number | null;
  };
  generatedAt: string;
};
```

PNG capture must wait for the component’s explicit final-render signal. JSON/CSV exports must contain the same filter, ordering, threshold, and scope represented in the image. Network drag positions and 3D camera state are presentation metadata, not analytical evidence.

## 11. Test gates

### 11.1 Phase 2 frontend/unit

- network link derivation, sign encoding, thresholding, and deterministic ordering;
- hover versus pinned network state;
- correlation/VIF/network selection synchronization;
- pairwise hard cap;
- linked histogram-range highlighting;
- rectangular brush and keyboard-equivalent ranges;
- density/scatter switch without losing variables;
- pinned point details;
- target-band-to-histogram linking;
- VIF simulation remaining non-mutating;
- findings severity/filter state;
- reduced-motion final state;
- export-state round trip; and
- target-source names absent from every selector and serialized state.

### 11.2 Phase 2 backend

- unauthorized and cross-project requests rejected;
- target and deterministic target source rejected as relationship variables;
- sampling deterministic for a fixed seed;
- sample/class counts reconcile;
- VIF simulation does not mutate `DATASTORE` or a manifest;
- stale scope identity rejected;
- payload/cardinality limits enforced; and
- no duplicate analytical request for one UI action.

### 11.3 Phase 3 frontend/unit

- 2D/hexbin/3D/PCA switching preserves variables;
- 3D loads only after activation;
- camera reset is deterministic;
- selected time range and segment propagate only to supported charts;
- before/after labels remain explicit;
- honest empty state when no governed time/segment field exists;
- keyboard and table alternatives for 3D, treemap, ribbon, and network;
- cross-filter cancellation and stale-result rejection; and
- reduced motion disables camera/mark transitions without changing final state.

### 11.4 Phase 3 backend

- PCA excludes target, target sources, and unauthorized predictors;
- PCA output is deterministic and explained variance reconciles;
- time/segment requests accept only governed candidates;
- small-cell suppression rules are applied consistently;
- PSI/drift baselines and comparison periods are explicit;
- filters do not mutate source data;
- sample/aggregate limits are enforced; and
- project/dataset/manifest scope changes invalidate cache entries.

### 11.5 Browser acceptance

Run Playwright at:

- 1366 × 768;
- 1536 × 864; and
- 1920 × 1080.

For each phase verify:

- no uncaught page errors;
- no horizontal page overflow;
- active charts remain usable after resize;
- screenshot capture occurs after final-render state;
- reduced-motion screenshots contain the same final analytical state;
- no unexpected requests occur for unopened tabs/modes; and
- target-source fields never appear in controls, tooltips, tables, exports, or request payloads.

## 12. Explicit exclusions from Phase 1

The following work must not be pulled into the Phase 1 implementation:

- correlated-feature network;
- network force layout, drag, or neighbor navigation;
- pairwise linked brushing, density mode, LOESS/regression overlays, and pinned point details;
- target balance/prevalence visual redesign beyond compatibility with shared selection;
- visual Findings summary and before/after comparison;
- VIF reduction simulation and governed retain/drop/combine decision workflow;
- 3D scatter, ECharts GL, PCA projection, hulls, and density surfaces;
- time/segment trend, drift heatmap, cohort ribbon, treemap, and small-multiple suite;
- advanced multi-filter coordination across time, segment, pairwise, 3D, and findings;
- Arrow IPC or another wire-format migration;
- broad Feature Engineering, Balance/Split, training-matrix, or scoring-schema remediation; and
- changes to Outliers or automatic variable removal.

Phase 1 may leave typed extension points for these capabilities, but it must not add dormant controls, speculative dependencies, placeholder analytical claims, or background requests for them.

## 13. Delivery order

### Phase 2

1. Extend the Phase 1 selection/evidence schema.
2. Harden and test the bounded relationship-sample contract.
3. Add the correlated-feature network.
4. Replace the inline pairwise renderer with the linked builder.
5. Upgrade Target visuals using existing target-intelligence results.
6. Add VIF relationship detail and non-mutating simulation.
7. Add the visual Findings summary.
8. Complete performance, accessibility, export, and browser gates.

### Phase 3

1. Add the advanced cross-filter coordinator and aggregate contract.
2. Add 2D scatter and hexbin modes.
3. Pass the explicit 3D dependency/renderer gate, then lazy-load 3D.
4. Add governed PCA projection.
5. Add time and segment aggregate contracts.
6. Add trend, drift, cohort, treemap, and small-multiple views.
7. Add before/after comparisons and cross-filtered evidence.
8. Complete performance, accessibility, export, and browser gates.

No phase is complete until target-source exclusion, scope labeling, reduced motion, exact-state export, and stale-result protection pass at both unit and browser levels.

## 14. Deferred roadmap: Population Selection and Eligibility Waterfall

Population selection is intentionally outside the current EDA acceptance phase.
Until this roadmap item is implemented, ATLAS treats the registered governed
dataset as the modeling-eligible population and does not imply that eligibility
rules were evaluated inside EDA.

A future governed design may reconcile:

- source population;
- eligibility filters and business-rule exclusions;
- records missing required fields;
- duplicate-record disposition;
- final modeling population; and
- holdout and out-of-time populations.

That future workflow must preserve explicit row-count reconciliation, reasons for
every exclusion, versioned evidence, and reviewer approval. No placeholder
controls or population mutations are added to the current EDA page.
