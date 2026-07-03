# ATLAS Performance Audit

Audit date: 2026-07-03  
Scope: local performance review from code inspection and user-reported behavior.

## Executive Summary

The main performance risks are browser-side storage and rendering of large datasets, chart-heavy EDA pages, large all-in-one Experimental Design component rendering, Monte Carlo simulation persistence, and model evaluation artifacts. Recent work has added sampling and compaction in several places, but ATLAS still needs a formal performance budget and project-scoped storage cleanup.

## Performance Hotspots

| Area | Risk | Current mitigation | Recommendation |
|---|---|---|---|
| Data Acquisition | Browser parses CSV/JSON and keeps up to 5,000 rows in session storage. | Row cap and preview rows. | Stream/parse large files in backend or worker. Store only metadata plus small preview in browser. |
| EDA | Pairwise plots and correlation heatmaps can be expensive on wide datasets. | Sampling controls, top numeric feature limits. | Add virtualization, async rendering, web worker for correlations, and progressive loading. |
| Missing Values / Outliers | Full feature tables can grow wide/long. | Pagination on outliers. | Add virtualized tables and debounce global strategy updates. |
| Feature Engineering | Preview transformation can re-run across rows/features. | Preview uses small sample. | Memoize transformed preview and hide advanced sections until needed. |
| Model Training | Backend training can run multiple algorithms and grid search. | Grid search levels and max parallel setting. | Add job status polling, cancel button, server-side queue, and per-model runtime display. |
| Evaluation | Decision boundary, KNN regions, tree visualizations, SHAP-style importance can be heavy. | Sampling exists in backend evaluation service. | Cache evaluation artifacts per experiment; lazy-load charts below fold. |
| RFE | Repeated fitting across retained feature counts can be slow. | Backend service calculates. | Show progress, allow max feature cap, cache final RFE per experiment. |
| Scoring | TEST/OOT uploads and PSI/VSI can be large. | Summaries and preview tables. | Server-side chunked scoring, no full scored rows in browser by default. |
| Monte Carlo | Simulations can create large arrays and quota errors. | Compaction path exists. | Persist only seed, assumptions, summaries, and chart aggregates. Use IndexedDB/backend for full iterations. |
| Reports | Governance/model docs can include large tables and appendices. | Tables are HTML-rendered and scrollable. | Add report size limit and executive/full export modes. |

## Browser Storage Performance

| Storage | Current cap/behavior | Risk |
|---|---|---|
| `modeling-tool-dataset` | 5,000 rows in session storage | Can still be large for wide datasets. |
| `modeling-tool-mlflow-lite-experiments` | Up to 100 compact records | Could exceed quota with notes/artifacts. |
| `modeling-tool-decision-journal` | Up to 1,000 entries | Long projects can become heavy. |
| `atlas-workflow-node-state` | Per project/step evidence; simulation results compacted in places | LocalStorage quota errors if compaction misses a field. |
| `.runtime/workflow_checkpoint.pkl` | Full backend data, splits, models | Can become large and slow startup. |

Recommended target:

- Browser storage per project under 2 MB.
- Active dataset preview under 500 KB.
- Decision journal visible list under 50 entries.
- Experiment records compacted to summary artifacts only.
- Full data/model artifacts stored backend-side or exported explicitly.

## EDA Performance

Current code uses:

- `samplePct` on EDA page.
- Local rows sampled by slicing.
- Correlation limited to 20 numeric columns.
- Pairwise limited to 4 numeric features.
- Backend EDA samples up to 20,000 rows and pairplot samples to 2,000.

Recommended improvements:

1. Add warning when dataset is wide and only top columns are shown.
2. Use variance/information value/target relevance to choose displayed numeric columns.
3. Move correlation computation to backend for large datasets.
4. Add "Generate full profile" as an explicit long-running task.
5. Cache EDA results by dataset hash.

## Experimental Design Performance

`WorkflowPlaceholderStep.tsx` is very large and renders many page-specific layouts. This increases the chance that one page state change causes excessive rerenders.

Recommended component split:

```text
src/features/experimental-design/
  analysis/
  components/
  pages/
    ProjectContextPage.tsx
    ResearchQuestionPage.tsx
    FactorsPage.tsx
    LevelsPage.tsx
    BlockingPage.tsx
    RandomizationPage.tsx
    SampleSizePage.tsx
    MonteCarloPage.tsx
    RunPlanPage.tsx
    AnovaPage.tsx
    OptimizationPage.tsx
    DocumentationPage.tsx
```

Benefits:

- Smaller rerender boundaries.
- Easier page-level testing.
- Clearer source-of-truth analysis object.
- Less risk of blank layout holes from shared container styles.

## Backend Performance

Current backend uses an in-memory singleton `DATASTORE` and `RESULTS`, with pickle checkpoint on startup/shutdown moments. This is fine for one local project but not for multi-project or hosted use.

Risks:

- Training large datasets blocks request lifecycle.
- Multiple concurrent training calls can mutate shared `DATASTORE`/`RESULTS`.
- Checkpoint pickle size grows with data and model artifacts.
- Startup load can slow down if `.runtime/workflow_checkpoint.pkl` is large.

Recommended next steps:

1. Add server-side job IDs for training, scoring, and simulation.
2. Store per-project/session state separately.
3. Add artifact size limits to checkpoint.
4. Use file/database object store for large artifacts.
5. Add runtime metrics: queue time, fit time, scoring time, memory estimate.

## Build and Bundle Performance

The current Vite package includes multiple apps in one source tree. `vite.config.ts` has Rollup inputs for both `index.html` and `guitarist.html`. Even if code splitting handles some assets, shared package scope increases build complexity.

Recommendations:

- Split ATLAS from Greatest Guitarist and tracker/STELA after copy-first migration.
- Keep ATLAS in its own package.
- Move STELA/tracker and guitarist into separate package roots if still active.
- Add bundle analyzer after restructure.

## Performance Test Plan

| Test | Dataset/Scenario | Pass criteria |
|---|---|---|
| Data upload | 50,000 rows, 50 columns | UI remains responsive; preview appears; backend receives full rows or clear sample warning. |
| Wide EDA | 5,000 rows, 200 numeric columns | Heatmap and pairwise render within 3 seconds or show queued state. |
| Missing/outliers | 200 features | Tables remain scrollable; global strategy update under 1 second. |
| Model training | 4 models, quick grid | UI shows progress; no duplicate submissions; summary populates. |
| RFE | 50 features | Progress or loading visible; no frozen UI. |
| Monte Carlo | 10,000 iterations | No localStorage quota error; only summary/aggregates persisted. |
| Governance export | Full project | HTML opens without raw Markdown table dumps; report under reasonable size. |

## Priority Performance Fixes

1. Project-scope and compact all localStorage data.
2. Split Experimental Design pages out of `WorkflowPlaceholderStep.tsx`.
3. Add backend jobs for training/scoring/simulation.
4. Add EDA result caching by dataset hash.
5. Add storage usage diagnostics to Settings.

