import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const read = (path) => readFile(new URL(`../${path}`, import.meta.url), "utf8");
const [workflows, routeWrapper, shell, demoData, workflowPage, dataAcquisition, timeSeriesProfile, modelingDepthPages, codeTemplates, templates, registryService] = await Promise.all([
  read("src/config/workflows.ts"),
  read("src/features/experimental-design/pages/ExperimentalDesignWorkflowPage.tsx"),
  read("src/workflows/time-series/TimeSeriesWorkflowShell.tsx"),
  read("src/workflows/time-series/timeSeriesDemoData.ts"),
  read("src/workflows/time-series/TimeSeriesWorkflowPage.tsx"),
  read("src/workflows/time-series/TimeSeriesDataAcquisition.tsx"),
  read("src/workflows/time-series/TimeSeriesProfile.tsx"),
  read("src/workflows/time-series/TimeSeriesModelingDepthPages.tsx"),
  read("src/workflows/time-series/timeSeriesCodeTemplates.ts"),
  read("server/validation/validation_templates.py"),
  read("server/registry/registry_service.py"),
]);

const expectedSteps = [
  "Project Context",
  "Data Acquisition",
  "Time Series Profile",
  "Feature & Calendar Design",
  "Backtest Design",
  "Model Configuration",
  "Train & Backtest",
  "Forecast Results",
  "Diagnostics & Stability",
  "Scenario & Stress Testing",
  "Recommendation & Monitoring Plan",
  "Documentation",
];

test("Time Series & Forecasting workflow exists with expected step order", () => {
  assert.match(workflows, /id: "time_series_forecasting"/);
  assert.match(workflows, /label: "Time Series & Forecasting"/);
  let lastIndex = -1;
  for (const label of expectedSteps) {
    const index = workflows.indexOf(`["${label}"`);
    assert.notEqual(index, -1, `Missing Time Series step: ${label}`);
    assert.ok(index > lastIndex, `Time Series step is out of order: ${label}`);
    lastIndex = index;
  }
});

test("Time Series Feature and Calendar Design is a real feature-building workspace", () => {
  for (const token of [
    "Lag feature builder",
    "Add lag feature",
    "lag_1",
    "lag_7",
    "lag_14",
    "lag_30",
    "Rolling feature builder",
    "Add rolling feature",
    "rolling_mean_7",
    "rolling_std_30",
    "Calendar feature controls",
    "holiday flag",
    "business day",
    "Future-known driver gate",
    "future_balance",
    "blocked",
    "Feature lineage table",
    "leakage status",
    "Lag correlation heatmap",
    "Calendar effect chart",
    "time_series_feature_design",
    "PROC SQL self-joins",
  ]) {
    assert.ok(modelingDepthPages.includes(token), `Missing Feature & Calendar Design token ${token}`);
  }
});

test("Time Series Backtest Design provides governed temporal validation choices", () => {
  for (const token of [
    "Validation strategy selector",
    "Holdout by date",
    "Rolling origin",
    "Expanding window",
    "Sliding window",
    "Grouped entity holdout",
    "Backtest preview only",
    "Backtest timeline",
    "training period, gap period, validation/forecast period, untouched holdout",
    "Fold table",
    "train start",
    "gap start/end",
    "forecast start",
    "Governing metric selector",
    "WAPE",
    "MASE helps compare across series",
    "MAPE can be unstable",
    "Random split is not valid for forecasting",
    "time_series_backtest_design",
  ]) {
    assert.ok(modelingDepthPages.includes(token), `Missing Backtest Design token ${token}`);
  }
});

test("Time Series Model Configuration supports champion and challenger contest setup", () => {
  for (const token of [
    "Champion/challenger model selection board",
    "Naive",
    "Seasonal Naive",
    "Moving Average",
    "Exponential Smoothing / ETS",
    "ARIMA",
    "SARIMA",
    "SARIMAX",
    "Linear Regression with lag/calendar features",
    "Random Forest",
    "Gradient Boosting",
    "Governing performance metric",
    "Selected model queue",
    "champion candidate",
    "challenger",
    "diagnostic only",
    "Prediction interval confidence",
    "Tuning depth",
    "ARIMA/SARIMA p/d/q guidance",
    "candidate p/q guidance",
    "suggested starting value",
    "time_series_model_configuration",
  ]) {
    assert.ok(modelingDepthPages.includes(token), `Missing Model Configuration token ${token}`);
  }
});

test("Time Series Train and Backtest has preview-safe professional outputs", () => {
  for (const token of [
    "Train selected models and run backtest",
    "ready",
    "queued",
    "running",
    "complete",
    "failed",
    "preview mode",
    "Model comparison table",
    "Fold-by-fold metrics",
    "Horizon-level metrics",
    "Actual vs forecast by fold",
    "Residual distribution",
    "Forecast error over time",
    "Bias by horizon",
    "selected champion",
    "time_series_training",
    "time_series_backtest",
    "time_series_backtest_results",
    "No fake training claims",
    "Preview mode, no real fit claimed",
  ]) {
    assert.ok(modelingDepthPages.includes(token), `Missing Train & Backtest token ${token}`);
  }
});

test("Time Series Forecast Results has champion forecast review and exports", () => {
  for (const token of [
    "Champion model",
    "Actual plus forecast chart with prediction interval band",
    "historical actuals, forecast line, lower interval, upper interval",
    "Forecast table",
    "lower interval",
    "upper interval",
    "Entity-level forecast summary",
    "top increasing",
    "top decreasing",
    "highest uncertainty",
    "sparse-history",
    "Business interpretation",
    "Export forecast CSV",
    "Export chart",
    "Export governed JSON",
    "Export documentation-ready summary",
    "time_series_forecast_results",
  ]) {
    assert.ok(modelingDepthPages.includes(token), `Missing Forecast Results token ${token}`);
  }
});

test("Time Series professional output standard is represented across modeling depth pages", () => {
  for (const token of [
    "X-axis",
    "Y-axis",
    "Legend",
    "ATLAS interpretation",
    "Export diagnostics",
    "Export CSV",
    "Data scope",
    "Documentation mapping",
    "documentation_ready",
  ]) {
    assert.ok(modelingDepthPages.includes(token), `Missing professional output token ${token}`);
  }
  assert.ok(!modelingDepthPages.includes("Recommended default"), "Time Series modeling pages must not use generic Recommended default dropdowns");
  assert.ok(!modelingDepthPages.includes("Predictive Modeling Workflow"), "Time Series modeling pages must not say Predictive Modeling Workflow");
});

test("Time Series workflow routes through dedicated components, not generic placeholder pages", () => {
  assert.match(routeWrapper, /workflowId === "time_series_forecasting"/);
  assert.match(routeWrapper, /TimeSeriesWorkflowPage/);
  assert.match(routeWrapper, /WorkflowPlaceholderStep/);
  assert.ok(!workflowPage.includes("WorkflowPlaceholderStep"), "Time Series page must not import the generic placeholder renderer");
  assert.ok(!shell.includes("WorkflowPlaceholderStep"), "Time Series shell must not render the generic placeholder body");
});

test("Time Series pages include code, visuals, evidence, and financial-services diagnostics", () => {
  for (const token of [
    "timeSeriesPages",
    "TIME SERIES & FORECASTING WORKFLOW",
    "Code & Reproducibility",
    "time_series_project_context",
    "time_series_input_bundle",
    "time_series_profile",
    "time_series_feature_design",
    "time_series_backtest_design",
    "time_series_model_configuration",
    "time_series_backtest_results",
    "time_series_forecast_results",
    "time_series_diagnostics",
    "time_series_scenarios",
    "time_series_monitoring_plan",
    "time_series_documentation_package",
    "Forecast Charter and Governance Boundary",
    "Fraud",
    "Backtest",
  ]) {
    assert.ok(`${shell}\n${demoData}`.includes(token), `Missing Time Series renderer token ${token}`);
  }
});

test("Time Series pages expose page-specific analytical controls and visual centers", () => {
  for (const token of [
    "TIME SERIES & FORECASTING WORKFLOW",
    "Date/time column",
    "Frequency",
    "Missing timestamp policy",
    "Time coverage timeline",
    "Missing timestamp calendar",
    "Rolling window",
    "rolling volatility",
    "seasonality",
    "Autocorrelation and lag relationship",
    "Lag features",
    "Rolling features",
    "Calendar features",
    "Future-known driver controls",
    "Future-known driver gate",
    "Rolling origin",
    "Forecast horizon",
    "Gap period",
    "Rolling-origin timeline",
    "Candidate model cards",
    "Naive baseline",
    "Seasonal naive",
    "Model comparison chart",
    "Backtest preview mode",
    "Forecast horizon table",
    "lower interval",
    "upper interval",
    "Residual ACF",
    "error by horizon",
    "stability",
    "anomaly timeline",
    "Base vs scenario forecast",
    "Monitoring threshold table",
    "Time Series Report",
  ]) {
    assert.ok(`${shell}\n${demoData}`.includes(token), `Missing Time Series page-specific token ${token}`);
  }
  assert.ok(!`${shell}\n${demoData}`.includes("Synthetic forecast preview"), "Time Series pages should not reuse the old synthetic forecast preview title");
});

test("Time Series dedicated pages include the required unique acceptance phrases", () => {
  for (const token of [
    "Time coverage timeline",
    "Missing timestamp calendar",
    "Target over time line chart",
    "Rolling mean and rolling volatility",
    "Feature lineage table",
    "Future-known driver gate",
    "Backtest fold timeline",
    "Candidate model cards",
    "Fold-by-fold metrics",
    "Prediction interval fan chart",
    "Residual autocorrelation",
    "Base vs stressed forecast",
    "Monitoring threshold table",
    "Time Series documentation package",
  ]) {
    assert.ok(`${shell}\n${demoData}`.includes(token), `Missing required Time Series acceptance phrase ${token}`);
  }
  assert.ok(!demoData.includes("Predictive Modeling Workflow"), "Time Series page data should not use the Predictive Modeling Workflow header");
});

test("Time Series pages are structurally differentiated", () => {
  const layouts = [...demoData.matchAll(/layout: "([^"]+)"/g)].map((match) => match[1]);
  const titles = [...demoData.matchAll(/^    title: "([^"]+)"/gm)].map((match) => match[1]);
  assert.equal(layouts.length, 12, "Time Series should define one layout per workflow step");
  assert.equal(titles.length, 12, "Time Series should define one title per workflow step");
  assert.ok(new Set(layouts).size >= 10, "Time Series pages should not reuse one repeated chart structure");
  assert.ok(new Set(titles).size === 12, "Time Series pages should not reuse one repeated diagnostic title");
});

test("Time Series pages do not reuse the rejected generic controls scaffold", () => {
  const workflowSource = `${shell}\n${demoData}\n${workflowPage}`;
  assert.equal((workflowSource.match(/Workflow Controls/g) ?? []).length, 0, "Time Series must not render the generic Workflow Controls block");
  assert.ok((workflowSource.match(/Recommended default/g) ?? []).length <= 3, "Time Series must not contain repeated generic Recommended default dropdown values");
  assert.ok(!workflowPage.includes("WorkflowPlaceholderStep"), "WorkflowPlaceholderStep must not be the Time Series main renderer");
  assert.ok(!demoData.includes("Predictive Modeling Workflow"), "Time Series pages must not say Predictive Modeling Workflow");
});

test("Time Series named workspaces cover required positive page checks", () => {
  const workflowSource = `${shell}\n${demoData}`;
  for (const token of [
    "Time coverage timeline",
    "Missing timestamp calendar",
    "Data mapping table",
    "Target over time line chart",
    "Rolling mean",
    "Autocorrelation",
    "Lag relationship",
    "Rolling-origin timeline",
    "Fold table",
    "Candidate model cards",
    "Prediction interval fan chart",
    "Residual ACF",
    "Error by horizon",
  ]) {
    assert.ok(workflowSource.includes(token), `Missing required Time Series positive check ${token}`);
  }
});

test("Time Series registry classification and validation template exist", () => {
  assert.match(registryService, /forecasting_study/);
  assert.match(registryService, /time_series_forecasting/);
  assert.match(templates, /TIME_SERIES_ITEMS/);
  assert.match(templates, /"time_series_forecasting"/);
  for (const item of ["time_index", "temporal_split", "feature_calendar", "diagnostics", "monitoring", "reproducibility"]) {
    assert.ok(templates.includes(item), `Missing Time Series validation item ${item}`);
  }
});

test("Time Series Data Acquisition uses governed Dataset Library and upload registration", () => {
  for (const token of [
    "Dataset Library",
    "Upload and Register",
    "listDatasets",
    "uploadDataset",
    "getDatasetProfile",
    "getDatasetPreview",
    "linkDatasetToProject",
    "listProjectDatasets",
  ]) {
    assert.ok(dataAcquisition.includes(token), `Missing real data acquisition token ${token}`);
  }
  assert.ok(!shell.includes('label="Input source"'), "Rejected cosmetic Input Source dropdown must not remain in the generic Time Series shell");
  assert.ok(!shell.includes("transaction_date"), "Generic Time Series shell must not carry fake mapping columns");
});

test("Time Series Data Acquisition maps real schema columns and recognizes Store Item Demand", () => {
  for (const token of [
    "profile?.schema.map",
    "preview?.columns",
    "inferMapping",
    "date",
    "store",
    "item",
    "sales",
    "Store Item Demand schema recognized",
    "Daily",
    "Sum",
    "90 days",
    "WAPE",
    "MAE",
    "RMSE",
    "Bias",
  ]) {
    assert.ok(dataAcquisition.includes(token), `Missing schema mapping or Store Item Demand token ${token}`);
  }
  assert.ok(dataAcquisition.includes("entityColumns") && dataAcquisition.includes("exogenousDriverColumns"), "Time Series mapping must support entity grain and exogenous drivers");
});

test("Time Series Data Acquisition does not duplicate required visual and mapping panels", () => {
  for (const phrase of ["Time coverage timeline", "Missing timestamp calendar heatmap", "Data mapping table"]) {
    assert.equal((dataAcquisition.match(new RegExp(phrase, "g")) ?? []).length, 1, `${phrase} should appear once on the real Data Acquisition page`);
  }
  assert.equal((dataAcquisition.match(/Recommended default/g) ?? []).length, 0, "Time Series Data Acquisition must not show generic Recommended default values");
});

test("Time Series Data Acquisition confirm persists workflow state, evidence, decision journal, and registry-visible bundle", () => {
  for (const token of [
    "saveProjectToDatabase",
    "saveEvidenceToDatabase",
    "saveDecisionToDatabase",
    "logDecision",
    "workflow_state",
    "time_series_input_bundle",
    "audit_log",
    "registry_evidence_update",
    "markWorkflowStepComplete",
    "setWorkflowStepStatus",
  ]) {
    assert.ok(dataAcquisition.includes(token), `Missing persistence token ${token}`);
  }
});

test("Time Series Data Acquisition code panel is page-specific and SAS-compatible", () => {
  assert.ok(`${dataAcquisition}\n${codeTemplates}`.includes("atlas.dataset_library.load_dataset"), "Data Acquisition code must load from Dataset Library");
  assert.ok(`${dataAcquisition}\n${codeTemplates}`.includes("PROC TIMESERIES"), "Data Acquisition code must include SAS-compatible time-series outline");
  assert.ok(`${dataAcquisition}\n${codeTemplates}`.includes("time_series_input_bundle"), "Data Acquisition code must save the input bundle artifact");
});

test("Time Series Data Acquisition keeps Dataset Library active for selected registered datasets", () => {
  assert.ok(dataAcquisition.includes('const activeSource = selectedDataset ? "Dataset Library" : sourceMode'), "A selected registered dataset must make Dataset Library the active source");
  assert.ok(dataAcquisition.includes('active={activeSource === "Dataset Library"}'), "Dataset Library card must reflect the selected dataset source");
  assert.ok(dataAcquisition.includes('active={sourceMode === "Upload and Register" && !selectedDataset}'), "Upload and Register must not remain visually selected while a Dataset Library asset is active");
  assert.ok(dataAcquisition.includes('Active source: Dataset Library'), "Selected dataset panel must show the visible active source");
});

test("Time Series Data Acquisition shows selected dataset summary and scoped profile language", () => {
  for (const token of [
    "Selected Dataset Summary",
    "datasetId",
    "Version / hash",
    "Source type",
    "Profile scope",
    "Selected date column",
    "Selected target column",
    "Selected entity grain",
    "Selected frequency",
    "Full dataset profile",
    "Sampled backend profile",
    "Browser preview profile",
    "full time coverage is not available from the current Dataset Library profile",
  ]) {
    assert.ok(dataAcquisition.includes(token), `Missing selected dataset or profile-scope token ${token}`);
  }
  assert.ok(!dataAcquisition.includes("Registered dataset profile and preview"), "Data Acquisition must not use ambiguous full-profile language for preview rows");
});

test("Time Series Data Acquisition computes multi-series entity diagnostics from date plus entity grain", () => {
  for (const token of [
    "periodEntityKeys",
    "duplicateCheckGrain",
    "Duplicate period check:",
    "date/time column",
    "distinctStores",
    "distinctItems",
    "distinctSeries",
    "Shortest series length",
    "Longest series length",
    "Sparse series count",
    "Recent coverage warning",
    "Preview-based multi-series diagnostics",
  ]) {
    assert.ok(dataAcquisition.includes(token), `Missing entity grain diagnostic token ${token}`);
  }
  assert.ok(dataAcquisition.includes("mapping.entityColumns.join(\" + \")"), "Entity diagnostics must present store + item as a combined grain");
});

test("Time Series Data Acquisition labels missing timestamp gaps by scope", () => {
  for (const token of [
    "missingGapScope",
    "entity-level gaps by",
    "global date gaps",
    "Full dataset",
    "Sampled backend",
    "Browser preview",
    "Missing timestamp gaps:",
  ]) {
    assert.ok(dataAcquisition.includes(token), `Missing missing-gap scope token ${token}`);
  }
});

test("Time Series Profile computes diagnostics from the confirmed input bundle", () => {
  for (const token of [
    "readBundle",
    "atlas-time-series-data-acquisition",
    "dateColumn",
    "targetColumn",
    "entityColumns",
    "aggregationFrequency",
    "aggregationMethod",
    "selectedEntity",
    "entitySeriesPoints",
    "rollingMean",
    "rollingStd",
    "detectAnomalies",
    "autocorrelation",
    "seasonalRows",
    "time_series_profile",
    "saveEvidenceToDatabase",
  ]) {
    assert.ok(timeSeriesProfile.includes(token), `Missing dynamic Time Series Profile token ${token}`);
  }
  assert.ok(!timeSeriesProfile.includes("LineChartMock"), "Time Series Profile must not use the placeholder line chart");
});

test("Time Series Profile exposes required diagnostic outputs and controls", () => {
  for (const token of [
    "Actual",
    "Rolling mean",
    "Anomaly",
    "Date / period",
    "Target value",
    "Rolling volatility diagnostics",
    "High-volatility periods",
    "Seasonality diagnostics",
    "Month-of-year pattern",
    "Short-history warning",
    "Autocorrelation diagnostics",
    "[1, 7, 14, 30]",
    "Anomaly diagnostics",
    "Top anomalous periods",
    "Diagnostic summary table",
    "observationCount",
    "trendDirection",
    "seasonalityStrength",
    "lagSignal",
    "volatilityStatus",
    "anomalyCount",
  ]) {
    assert.ok(timeSeriesProfile.includes(token), `Missing visible Time Series Profile diagnostic token ${token}`);
  }
});
