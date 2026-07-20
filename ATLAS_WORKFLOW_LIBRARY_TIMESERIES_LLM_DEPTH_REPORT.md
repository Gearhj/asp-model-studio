# ATLAS Workflow Library Time Series and LLM Depth Report

## Executive Summary

This update converts the approved Time Series & Forecasting and LLM / Generative AI project types from generic placeholder rendering into dedicated ATLAS workflow implementations. The taxonomy changes from the prior build remain intact: Forecasting and Time Series are combined, NLP is replaced by LLM / Generative AI, Segmentation remains an Analytics Workbench pattern, and registry and validation integrations remain in place.

## Prior Scaffold Gap

The rejected implementation had the correct workflow definitions, but the visible pages still rendered through `WorkflowPlaceholderStep.tsx`. That made Time Series & Forecasting and LLM / Generative AI look like repeated generic pages instead of serious data-science workflows.

This build adds dedicated route-level components:

- `src/workflows/time-series/TimeSeriesWorkflowPage.tsx`
- `src/workflows/time-series/TimeSeriesWorkflowShell.tsx`
- 12 Time Series step components and dedicated data/code definition files
- `src/workflows/llm/LlmWorkflowPage.tsx`
- `src/workflows/llm/LlmWorkflowShell.tsx`
- 12 LLM step components and dedicated data/code definition files

`WorkflowPlaceholderStep.tsx` remains available only for generic or unbuilt project types. The shared route wrapper now explicitly routes `time_series_forecasting` and `llm_generative_ai` to their dedicated workflow components.

## Time Series Page-Specific Improvements

The 12 Time Series & Forecasting pages now have distinct purposes, controls, diagnostics, visuals, evidence types, and reproducibility code:

- Project Context: forecast study design, study goal cards, financial-services examples, and risk classification.
- Data Acquisition: source selection, time/date mapping, time zone, frequency, target mapping, duplicate timestamp policy, missing timestamp policy, entity/segment mapping, exogenous drivers, time coverage timeline, missing timestamp heatmap, target preview, and entity coverage.
- Time Series Profile: level, trend, rolling mean, volatility, seasonality, autocorrelation, lag relationships, anomalies, date range, rolling window, decomposition, and anomaly sensitivity.
- Feature & Calendar Design: lag features, rolling features, calendar features, future-known driver gate, feature lineage, lag correlation heatmap, calendar effect chart, and leakage risk panel.
- Backtest Design: holdout by date, rolling origin, expanding window, sliding window, initial training window, folds, horizon, step size, gap period, holdout period, fold timeline, split graphic, horizon diagram, and metric cards.
- Model Configuration: model cards for naive, seasonal naive, moving average, exponential smoothing, ARIMA/SARIMA-style templates, lag-feature regressions, gradient boosting, random forest, and anomaly baseline.
- Train & Backtest: Backtest preview mode, train and run backtest action, execution state, model comparison, fold metrics, actual-versus-forecast chart, residual distribution, and bias by horizon.
- Forecast Results: champion summary, horizon summary, forecast table, interval fan chart, entity tables, top increasing/decreasing entities, and forecast contribution chart.
- Diagnostics & Stability: residual autocorrelation, residual bias, residual seasonality, error by horizon, drift, interval coverage, anomaly timeline, and segment error heatmap.
- Scenario & Stress Testing: demand shock, seasonality shock, trend change, event impact, downturn adjustment, fraud spike, outage, holiday/calendar change, base-versus-stress forecast, delta, peak impact, duration, risk flag, and worst-case period card.
- Recommendation & Monitoring Plan: recommendation status, owner, action, use, limitations, monitoring metrics, thresholds, owners, cadence, escalation, and reforecast triggers.
- Documentation: 20-section Time Series report package, evidence inventory, Governed JSON, Forecast CSV, Backtest Results CSV, Python Code, SAS-Compatible Code, and Time Series Report.

## LLM Page-Specific Improvements

The 12 LLM / Generative AI pages now avoid generic fallback content:

- Use Case & Risk Context: LLM workflow mode, business objective, intended users, output type, customer impact, human review, prohibited uses, sensitive data, governance context, risk tier, and allowed/prohibited behavior matrix.
- Data & Knowledge Sources: source inventory, source type, owner, version, permitted use, PII/confidentiality flags, document count, text length, freshness, label coverage, and sensitive content warnings.
- Task Design & Output Schema: task type, output schema, label definitions, extraction field map, citation requirement, refusal behavior, escalation behavior, and JSON/schema preview.
- Prompt & Instruction Design: system instruction, developer instruction, user prompt template, few-shot examples, negative examples, prompt version, token estimate, conflict warnings, and prompt risk checklist.
- Retrieval / RAG Configuration: chunking strategy, chunk size, overlap, embedding model label, vector index label, top-k, reranking, metadata filters, retrieval preview, chunk distribution chart, citation preview, and source coverage cards.
- Evaluation Dataset: golden cases, expected answers, labels, required citations, rubric, adversarial examples, out-of-scope examples, policy-sensitive examples, coverage matrix, and label distribution.
- LLM Evaluation: manual evaluation template when no LLM backend exists, model/provider label, model version, temperature, max tokens, evaluation mode, groundedness, citation accuracy, hallucination, refusal correctness, policy compliance, extraction accuracy, and classification precision/recall/F1.
- Safety, Compliance & Red-Team Review: prompt injection, data leakage, hallucination risk, unsafe advice, fair lending, UDAAP, privacy, regulatory/legal concern, human review, escalation path, risk heatmap, and mitigation plan.
- Human Review & Quality Control: review required, review rate, reviewer role, sampling strategy, override process, escalation process, reviewer rubric, quality threshold, workflow diagram, and quality control table.
- Deployment & Monitoring Plan: deployment mode, model/provider, prompt version, source version, approved users, change control, monitoring cadence, monitoring metrics, version control summary, and threshold table.
- Recommendation & Approval: recommendation status, owner, recommended use, required controls, alternatives considered, residual risks, limitations, approval conditions, and recommendation banner.
- Documentation: LLM governance package, prompt registry, source registry, evaluation evidence, safety evidence, human review plan, deployment/monitoring plan, and exports.

## Visual Design Improvements

The dedicated shells now show the correct workflow header labels:

- TIME SERIES & FORECASTING WORKFLOW
- LLM / GENERATIVE AI WORKFLOW

The old repeated "Synthetic forecast preview" heading was removed. Each workflow now supplies page-specific controls, evidence keys, visual centers, and reproducibility code. Time Series pages use forecasting-specific charts, fold timelines, heatmaps, model queues, scenario comparisons, and monitoring tables. LLM pages use source inventories, schema previews, prompt editors, RAG pipeline graphics, evaluation scorecards, safety heatmaps, human-review tables, and deployment monitoring controls.

## Evidence, Registry, Validation, and Documentation

The workflows continue to expose registry and validation integration through the existing `forecasting_study`, `time_series_forecasting`, `llm_workflow`, and `llm_generative_ai` configuration paths. The new page definitions include backend-ready evidence keys for Time Series and LLM workflow state, evidence artifacts, documentation packages, export artifacts, and run-record-ready training/backtest references.

## Validation

Focused validation completed:

- `npx tsc -b`
- `npm run test:time-series-forecasting`
- `npm run test:llm-workflow`
- `npm run test:workflow-library`

The Time Series and LLM focused tests now explicitly assert that those workflows do not render through the generic placeholder body. Additional regression validation should be run after this report is synced to the clean ATLAS copy.
