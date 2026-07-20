# ATLAS Time Series and LLM Real Workflow UI Report

## Executive Summary

This build replaces the rejected generic placeholder rendering for Time Series & Forecasting and LLM / Generative AI with dedicated workflow page components, workflow shells, demo data definitions, and page-specific reproducibility code. Both workflows now have distinct headers, page structures, controls, visuals, evidence keys, and code blocks.

## Why the Prior Approach Was Insufficient

The prior implementation had correct taxonomy and step labels, but Time Series and LLM still rendered through `WorkflowPlaceholderStep.tsx`. That made the pages structurally repetitive and too generic for first-class analytical workflows. The user could not see a meaningful difference between Time Series profile, backtest, forecast, diagnostics, LLM source review, prompt design, RAG, safety, or human-review pages.

## Architecture Change

`src/features/experimental-design/pages/ExperimentalDesignWorkflowPage.tsx` now routes:

- `time_series_forecasting` to `src/workflows/time-series/TimeSeriesWorkflowPage.tsx`
- `llm_generative_ai` to `src/workflows/llm/LlmWorkflowPage.tsx`
- all other unbuilt workflow IDs to `WorkflowPlaceholderStep.tsx`

Dedicated Time Series files:

- `TimeSeriesWorkflowShell.tsx`
- 12 Time Series step components
- `timeSeriesTypes.ts`
- `timeSeriesDemoData.ts`
- `timeSeriesCodeTemplates.ts`

Dedicated LLM files:

- `LlmWorkflowShell.tsx`
- 12 LLM step components
- `llmTypes.ts`
- `llmDemoData.ts`
- `llmCodeTemplates.ts`

## Time Series Page-by-Page UI Changes

- Project Context: forecast charter, governance boundary, study goal cards, financial-services examples.
- Data Acquisition: source mapping, date/time parsing, target mapping, time coverage timeline, missing timestamp calendar.
- Time Series Profile: target over time line chart, Rolling mean and rolling volatility, seasonality, ACF, anomalies.
- Feature & Calendar Design: Feature lineage table, lag heatmap, Future-known driver gate.
- Backtest Design: Backtest fold timeline, horizon policy, fold table, temporal validation.
- Model Configuration: Candidate model cards for baseline, statistical, ML, and anomaly candidates.
- Train & Backtest: Backtest preview mode, Fold-by-fold metrics, comparison table, run record.
- Forecast Results: champion summary, Prediction interval fan chart, forecast horizon table.
- Diagnostics & Stability: Residual autocorrelation, residual stability, anomaly timeline, segment error heatmap.
- Scenario & Stress Testing: Base vs stressed forecast and stress comparison table.
- Recommendation & Monitoring Plan: recommendation banner, Monitoring threshold table, reforecast triggers.
- Documentation: Time Series documentation package, evidence inventory, governed exports.

## LLM Page-by-Page UI Changes

- Use Case & Risk: Allowed/prohibited behavior matrix, risk matrix, human-review boundary.
- Sources: Source inventory table, sensitive content review, freshness and coverage.
- Task & Schema: Output schema preview, label map, refusal and escalation behavior.
- Prompt: Prompt component editor, token/risk panel, version history.
- RAG: Document-to-chunk retrieval pipeline, chunk distribution, retrieval preview.
- Evaluation Dataset: Evaluation coverage matrix, golden cases, adversarial cases.
- LLM Evaluation: Hallucination/citation matrix, groundedness, refusal correctness, classification metrics.
- Safety: Safety risk heatmap, mitigation checklist, compliance controls.
- Human Review: Human review workflow diagram, sampling strategy, override process.
- Deployment: Version and change-control summary, deployment boundary, monitoring thresholds.
- Recommendation: Required controls checklist, residual risks, approval conditions.
- Documentation: LLM governance package, prompt/source registries, exports.

## Visual Differentiation

The dedicated shells use distinct visual centers instead of one repeated body. Time Series uses line charts, fan charts, timelines, heatmaps, model cards, and monitoring tables. LLM uses source tables, schema previews, prompt editors, RAG pipeline graphics, evaluation scorecards, safety heatmaps, and human review tables.

## Code and Reproducibility Differentiation

Each workflow step has its own code template. Time Series includes time parsing, resampling, ACF, lag features, rolling-origin backtesting, model queues, forecast export, diagnostics, scenario stress, monitoring, and documentation package code. LLM includes use-case boundaries, source registration, schema validation, prompt versioning, RAG configuration, evaluation sets, safety review, human review, deployment monitoring, recommendation, and governance package code.

## Tests Added or Strengthened

- `tests/timeSeriesForecasting.test.mjs` now verifies dedicated routing, no generic placeholder primary renderer, required Time Series phrases, evidence keys, financial-services diagnostics, and non-predictive-modeling headers.
- `tests/llmWorkflow.test.mjs` now verifies dedicated routing, no generic placeholder primary renderer, required LLM phrases, evidence keys, safety/evaluation/retrieval content, and non-predictive-modeling headers.

## Tests Run

- `npx tsc -b`
- `npm run build`
- `npm run test:workflow-library`
- `npm run test:time-series-forecasting`
- `npm run test:llm-workflow`
- `npm run test:project-types`
- `npm run test:workflow-navigation-state`
- `npm run test:open-project`
- `npm run test:persistence`
- `npm run test:dataset-library`
- `npm run test:model-documentation`
- `npm run test:evidence-graph`
- `npm run test:credit-risk-studio`
- `npm run test:optimization`
- `npm run test:user-management`
- `npm run test:registry-dashboard`
- `npm run test:validation-center`
- `npm run test:sqlite-persistence`
- `npm run test:regression`

## Test Results

All tests listed above passed. `node --test` direct invocation was blocked by Windows sandbox process spawning, so the repository npm-script pattern was used for focused tests.

## Manual Acceptance Notes

The implementation addresses the rejected architecture by removing Time Series and LLM from the generic placeholder renderer path. Browser-level manual QA remains recommended after sync to confirm the visual layouts match expectations in the live ATLAS shell.

## Known Limitations

The new pages are front-end workflow surfaces with deterministic, backend-ready preview visualizations and controls. Backend execution for full Time Series backtests and LLM evaluation is represented as explicit preview/manual-template modes where the service is not yet connected.

## No Fake Analytics Introduced

No fabricated model results were introduced. Where backend execution is unavailable, the UI labels the state as preview or manual evaluation template and provides governance-ready structure rather than claiming completed analytics.

## Source Workspace Confirmation

All edits were made in the source workspace:

`C:\Users\james\ds-workflow-starter`

## Sync Confirmation

`npm run sync:atlas` was run after final validation to sync this source workspace to the clean ATLAS copy:

`C:\Users\james\Projects\ATLAS\atlas-app`
