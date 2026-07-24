# Visual Intelligence — Component and Data Access Guide

## Visualization Specification guide

`src/visual-intelligence/visualizationSpec.ts` defines `VisualizationSpec` — a serializable description of a chart's current configuration (chart type, dataset reference, axes, filters, threshold, binning, overlays, sampling/aggregation state, accessibility description). `newVisualizationSpec()` builds one with sane defaults, auto-detecting `prefers-reduced-motion`.

**Critical rule:** saving a spec never implies the underlying raw data or an ephemeral scoring result was persisted — only the spec's own small JSON is durable. Any spec built from `sourceType: "scoring-session"` data must show `EPHEMERAL_SCORING_NOTICE` ("This view depends on an unregistered scoring result and may not survive a refresh.") and, where the product supports it, a `REGISTER_SCORED_DATASET_ACTION_LABEL` ("Register Scored Dataset") action. No new scoring-history backend was built this phase (stop condition #9) — this is intentionally metadata-only.

## ECharts vs. D3 decision guide

| Use ECharts when... | Use D3 when... |
|---|---|
| It's a standard chart type (bar, scatter, line, histogram) | You need a statistical reference line positioned from real computed data (mean/median/percentile/identity/zero-residual) |
| You want built-in tooltip/legend/axis/theme handling | You need a draggable threshold with pixel-exact coordinate math |
| Data volume needs Canvas rendering (see Large-Data Policy) | You need brush-selection with custom coordinate inversion |
| The interaction is "hover, click a series, zoom" (native ECharts toolbox/brush features) | The interaction is genuinely bespoke and ECharts has no equivalent option |

In practice: ECharts renders the base chart; D3 (`d3Overlays.tsx`) draws a transparent, absolutely-positioned SVG layer on top for the analytical extras. Prototype 3 additionally uses ECharts' own native `brush`/`toolbox` components for 2D rectangular selection on scatter plots (routine ECharts feature, not bespoke — appropriate to use directly rather than reimplementing in D3).

## Data Access Layer guide

`src/visual-intelligence/dataAccessLayer.ts` is the **only** place a component may decide "where does this chart's data come from." Current fetchers:

- `fetchWorkspaceRows(reference, { maxRows })` — server-bounded workspace sample via `GET /api/data/get_sample`.
- `fetchTrainingEvaluationResult(reference, modelKey)` — the most recent training run's raw actual/prediction arrays via `GET /api/train/last`.
- `computeSegmentAggregate(reference, rows, field, range, positiveValue)` — chooses DuckDB-Wasm or a client streaming pass based on `chooseRenderStrategy(rows.length)`.
- `isStaleResult(startedFor, currentContext)` — guards against a stale async result updating a newer selection.
- `sampleForDirectRender(rows, sampleSize)` — reservoir-samples with disclosure for callers that must render individual points above the aggregate threshold.
- `clearVisualDataForProject(projectId)` — DuckDB-Wasm + cleanup entry point, called by `VisualIntelligenceProvider`.

Every fetcher returns `{ reference, meta, rows }` where `meta: VisualDataSourceMeta` always states `source`, `rowsAvailable`, `totalSourceRows`, `sampled`, `freshAsOf`, `ephemeral`, and `aggregationMethod` — components must render this, not assume.

## Component usage example

```tsx
import { VisualIntelligenceProvider, useVisualIntelligenceContext } from "src/visual-intelligence/VisualIntelligenceContext";
import { fetchWorkspaceRows } from "src/visual-intelligence/dataAccessLayer";
import EChartsPanel from "src/visual-intelligence/EChartsPanel";

function MyChart() {
  const { baseReference, problemType } = useVisualIntelligenceContext();
  const [rows, setRows] = useState(null);
  useEffect(() => {
    if (!baseReference) return;
    fetchWorkspaceRows(baseReference, { maxRows: 5000 }).then((r) => setRows(r.rows));
  }, [baseReference]);
  // ...build an EChartsOption from rows, pass to <EChartsPanel option={...} ariaLabel="..." />
}

// Mount once per page, above every chart that needs it:
<VisualIntelligenceProvider><MyChart /></VisualIntelligenceProvider>
```

Every chart renders through `EChartsPanel` (`state="loading"|"empty"|"error"|"unsupported"|"ready"`), never a raw `echarts.init()` call, so lifecycle/ARIA/reduced-motion/export are handled once.
