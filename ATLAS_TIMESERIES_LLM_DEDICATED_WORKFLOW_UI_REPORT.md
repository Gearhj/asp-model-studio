# ATLAS Time Series and LLM Dedicated Workflow UI Report

## 1. Executive summary

The Time Series & Forecasting and LLM / Generative AI workflows have been revised away from the rejected repeated scaffold. The workflows now use dedicated step components, named page-specific controls, differentiated primary workspaces, workflow-specific evidence types, and regression tests that fail if the generic body pattern returns.

## 2. Why the previous repeated layout was rejected

The prior pass repeated the same body shape across pages: dark hero, status cards, a generic Workflow Controls block, generic Recommended default dropdowns, one visual panel, repeated cards, and the same footer. That made the workflows feel like placeholders instead of real analytical workspaces. The new pass removes that generic control block and replaces it with workflow-specific planning or analytical controls.

## 3. Architecture changes

Time Series and LLM continue to route through dedicated workflow pages from `ExperimentalDesignWorkflowPage.tsx`. They do not use `WorkflowPlaceholderStep` as their main renderer. Each workflow has a lightweight shell for shared chrome, but page content is now selected through distinct workspace components and dedicated step wrappers instead of a generic placeholder page body.

## 4. Components created

Time Series dedicated step files are present:

- `TimeSeriesProjectContext.tsx`
- `TimeSeriesDataAcquisition.tsx`
- `TimeSeriesProfile.tsx`
- `TimeSeriesFeatureCalendarDesign.tsx`
- `TimeSeriesBacktestDesign.tsx`
- `TimeSeriesModelConfiguration.tsx`
- `TimeSeriesTrainBacktest.tsx`
- `TimeSeriesForecastResults.tsx`
- `TimeSeriesDiagnosticsStability.tsx`
- `TimeSeriesScenarioStress.tsx`
- `TimeSeriesRecommendationMonitoring.tsx`
- `TimeSeriesDocumentation.tsx`

LLM canonical step files are present and used by `LlmWorkflowPage.tsx`:

- `LlmUseCaseRiskContext.tsx`
- `LlmDataKnowledgeSources.tsx`
- `LlmTaskOutputSchema.tsx`
- `LlmPromptInstructionDesign.tsx`
- `LlmRetrievalRagConfiguration.tsx`
- `LlmEvaluationDataset.tsx`
- `LlmEvaluation.tsx`
- `LlmSafetyComplianceReview.tsx`
- `LlmHumanReviewQualityControl.tsx`
- `LlmDeploymentMonitoringPlan.tsx`
- `LlmRecommendationApproval.tsx`
- `LlmDocumentation.tsx`

Older LLM alias files remain in the folder for compatibility, but the canonical page list now uses the requested file names.

## 5. Time Series page-by-page UI changes

- Project Context: forecast charter controls with study goal, horizon, frequency, entity grain, governance context, and intended use.
- Data Acquisition: dataset registration, time-index mapping, time coverage timeline, missing timestamp calendar, and data mapping table.
- Time Series Profile: diagnostic workspace with target-over-time, rolling mean, anomaly markers, seasonality, autocorrelation, and lag relationship content.
- Feature & Calendar Design: feature lineage, lag and calendar features, future-known driver gate, and lag correlation heatmap.
- Backtest Design: timeline-first rolling-origin layout with fold timeline and validation controls.
- Model Configuration: candidate model cards for baseline, statistical, machine-learning, and anomaly options.
- Train & Backtest: backtest preview mode is clearly labeled when no backend run record exists, with fold table and comparison results.
- Forecast Results: forecast fan chart, horizon table, interval controls, entity selection, and export controls.
- Diagnostics & Stability: residual and stability diagnostics, residual ACF, error by horizon, anomaly timeline, and segment/entity heatmap references.
- Scenario & Stress Testing: scenario builder, base vs stressed forecast, stress comparison table, and named financial stress controls.
- Recommendation & Monitoring: recommendation controls, monitoring threshold table, reforecast triggers, owner and cadence fields.
- Documentation: documentation package, evidence inventory, report map, and governed export controls.

## 6. LLM page-by-page UI changes

- Use Case & Risk Context: risk boundary controls, customer impact, allowed/prohibited behavior, sensitive data, and human review.
- Data & Knowledge Sources: source upload and registration, inventory table, freshness, permitted use, and sensitivity controls.
- Task Design & Output Schema: task type, JSON schema, citation requirement, refusal behavior, and escalation controls.
- Prompt & Instruction Design: system instruction editor, developer instruction editor, user prompt template editor, examples, token estimate, and conflict panel.
- Retrieval / RAG Configuration: document-to-chunk pipeline, chunking strategy, embedding label, Top-k, reranking, retrieval preview, and citation preview.
- Evaluation Dataset: golden test set builder, coverage matrix, test cases, adversarial cases, and rubric references.
- LLM Evaluation: manual evaluation template when no backend is present, hallucination/citation matrix, metrics, and error examples table.
- Safety, Compliance & Red-Team Review: safety risk heatmap, prompt injection, leakage, privacy, UDAAP, fair lending, and red-team checklist.
- Human Review & Quality Control: sampling strategy, review rate, override process, workflow diagram, and quality threshold.
- Deployment & Monitoring Plan: deployment boundary, version/change control, monitoring thresholds, and incident escalation.
- Recommendation & Approval: recommendation banner, required controls checklist, residual risks, and approval conditions.
- Documentation: governance package, prompt registry, source registry, evaluation evidence, safety evidence, and exports.

## 7. Controls removed or replaced

The repeated `Workflow Controls` section has been removed from visible Time Series and LLM workflow sources. Generic `Recommended default` dropdowns were replaced with named options such as Rolling origin, Expanding window, Fixed length chunking, Paragraph chunking, Risk-based review, Low-confidence review, and All customer-impacting outputs. Where backend execution is not connected, the UI now uses labels such as `Preview configuration`, `Planning control`, `Backtest preview mode`, or `Manual evaluation template`.

## 8. Visual differentiation

The workflows now use differentiated visual centers: time coverage timeline, heatmaps, line charts, rolling-origin timeline, model cards, fold metrics, forecast fan chart, scenario comparison, source inventory, schema preview, prompt editor, RAG pipeline, scorecard tables, safety heatmap, review workflow, and monitoring threshold tables. The pages no longer rely on one repeated diagnostic chart structure.

## 9. Tests added to prevent repeated scaffold regression

Regression tests were strengthened in:

- `tests/timeSeriesForecasting.test.mjs`
- `tests/llmWorkflow.test.mjs`

The tests fail if Time Series or LLM reintroduce repeated `Workflow Controls`, repeated `Recommended default` values, `WorkflowPlaceholderStep` as the main renderer, or `Predictive Modeling Workflow` copy. Positive tests now assert required Time Series and LLM page-specific phrases such as Time coverage timeline, Missing timestamp calendar, Fold table, Residual ACF, System instruction editor, Document-to-chunk pipeline, Top-k, Retrieval preview, Hallucination/citation matrix, and Red-team checklist.

## 10. Tests run

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

## 11. Test results

All validation commands passed. The build completed with existing Vite chunk-size and browser-data freshness warnings only. No failing tests remain in the requested validation list.

## 12. Manual acceptance notes

Manual source review confirms:

- Time Series pages no longer use the generic placeholder renderer.
- LLM pages no longer use the generic placeholder renderer.
- The rejected generic `Workflow Controls` block is not present in the dedicated workflow source.
- Named controls now match page purpose.
- Preview-only or planning-only states are explicitly labeled.

## 13. Known limitations

Some pages remain UI-level analytical workspaces until their backend services are connected. The UI explicitly avoids claiming real backend execution for those states. Time Series backtest execution is labeled as preview mode unless a backend run record exists. LLM evaluation is labeled as a manual evaluation template unless an approved LLM evaluation backend is connected.

## 14. Confirmation that no fake analytics were introduced

No fake analytics were introduced. Demonstrative charts and tables are presented as workflow planning, preview configuration, or manual-template states where backend execution is not wired. The implementation does not claim a real forecast model, real LLM run, or real evaluation result without a backend run record.

## 15. Confirmation that source workspace was used

All changes were made in the source workspace:

`C:\Users\james\ds-workflow-starter`

## 16. Confirmation that npm run sync:atlas was run

`npm run sync:atlas` was run successfully after validation and report creation. The clean synced copy target is:

`C:\Users\james\Projects\ATLAS\atlas-app`
