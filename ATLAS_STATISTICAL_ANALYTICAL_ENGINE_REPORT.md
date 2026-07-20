# ATLAS Statistical & Analytical Engine

## Executive Summary

ATLAS now includes a reusable, persisted Statistical & Analytical Engine. It is an internal service surfaced inside existing workflows, beginning with Time Series Profile. No standalone Studio, main workflow, or sidebar destination was added.

## Architecture

- `server/analytics_engine/` separates data resolution, calculation modules, result construction, deterministic interpretations, persistence adapters, and API routing.
- `src/api/analyticsEngine.ts`, `src/types/analyticsEngine.ts`, and `src/components/analytics/` provide reusable client and presentation primitives.
- `server/analytics_engine/registry.py` defines the supported governed analysis types.
- `server/analytics_engine/code_generation.py` supplies dataset-reference-aware Python starters and SAS-compatible implementation guidance.

## Result and Chart Contracts

Every calculation returns a structured analytical result with identifiers, lineage, parameters, statistics, tables, charts, diagnostics, warnings, interpretations, evidence, documentation, validation, monitoring, and reproducibility metadata. Chart and table payloads are bounded to chart-ready subsets of at most 2,000 rows. ATLAS retains references and summaries, not complete datasets, in analytical persistence.

## SQLite Persistence

Migration `server/persistence/migrations/0009_analytics_engine.sql` creates persisted analytical runs, results, tables, charts, and interpretations with project, status, dataset, analysis type, and run indexes. `AnalyticsRepository` is exposed through `PersistenceService`.

## Implemented Analytics

- Descriptive and data quality: numeric and categorical profiles, missingness, distributions, correlations, outliers, duplicate and quality diagnostics.
- Classification: threshold, ROC/PR, lift/gain, calibration, confusion matrix, decile, KS, and segment-aware diagnostics where configured.
- Regression: fit metrics, residual summaries, actual-versus-predicted and residual diagnostics, target-band error, VIF where feature inputs are supplied.
- Time series: real aggregate and panel profiles, rolling mean/volatility, anomalies, duplicate periods, missing periods, ACF/PACF, entity summaries, and short-history warnings.
- Forecasting: paired actual/forecast metrics, interval coverage when supplied, and backtest result routing.
- Experimentation, optimization, LLM evaluation, segments, and fairness diagnostics are registered through the same result contract.

## Workflow and Platform Integration

Time Series Profile calls the new `/api/analytics-engine/time-series/profile` route and renders persisted governed statistics, tables, chart-ready data, and interpretations. The engine exposes authenticated routes for descriptive, quality, classification, regression, time series, forecasting, experimentation, optimization, LLM, segment, and fairness analysis. Evidence, documentation, validation, and monitoring adapters produce structured integration payloads without duplicating source data.

## Access Control and Audit

The analytical router requires the established ATLAS user dependency. Completed project-bound analytical runs and cancellations create audit records. Evidence capture uses the existing evidence persistence service. Existing Dataset Library references are resolved by the dataset adapter before calculations run.

## Tests

Added `tests/analytics_engine_backend_test.py` and `tests/analyticsEngine.test.mjs`, exercised through `npm run test:analytics-engine`.

Passed during implementation:

- `npx tsc -b`
- `npm run build`
- `npm run test:analytics-engine`
- `npm run test:persistence`
- `npm run test:time-series-forecasting`
- `npm run test:sqlite-persistence`
- `npm run test:optimization`
- `npm run test:regression`
- `npm run test:monitoring-center`
- `npm run test:validation-center`
- Python compilation for `server/analytics_engine`

## Known Limitations

- ADF and KPSS are explicitly marked unavailable in the current runtime rather than fabricated. Time Series Profile still provides real trend, rolling, ACF, PACF, anomaly, and short-history diagnostics.
- The engine has the initial Time Series Profile UI integration. Additional page-level presentation integrations for Forecast Evaluation, Predictive Evaluation, Optimization, Evidence Center, and Documentation Studio should be implemented incrementally using the existing client and adapters.
- Browser acceptance testing was not run in this implementation session. The full requested regression matrix has not been exhausted; the passing suites above cover the engine's persistence, time-series, optimization, monitoring, validation, and core predictive workflow contracts.

## Confirmation

- No fabricated analytical output or random statistics were introduced.
- No new Studio, workflow, or sidebar destination was created.
- All source changes were made in `C:\Users\james\ds-workflow-starter`.
- `npm run sync:atlas` is run after the requested suite completes.
