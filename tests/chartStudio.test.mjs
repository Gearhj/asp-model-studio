import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const root = process.cwd();
const read = (file) => fs.readFileSync(path.join(root, file), "utf8");

const chartStudio = read("src/steps/ChartStudio.tsx");
const chartLib = read("src/lib/chartStudio.ts");
const app = read("src/apps/ModelingApp.tsx");
const sidebar = read("src/components/Sidebar.tsx");
const router = read("server/charts/chart_router.py");
const store = read("server/charts/chart_store.py");
const main = read("server/main.py");
const diagnostics = read("server/datasets/dataset_registry.py");
const datasetDetail = read("src/steps/DatasetDetail.tsx");
const projectOverview = read("src/steps/ProjectOverview.tsx");
const packageJson = JSON.parse(read("package.json"));

assert.match(app, /path="\/chart-studio"/, "Chart Studio route must be registered.");
assert.match(sidebar, /Chart Studio/, "Sidebar must include Chart Studio.");
assert.equal(packageJson.scripts["test:chart-studio"], "node tests/chartStudio.test.mjs", "package script must run Chart Studio tests.");

for (const label of ["ATLAS Chart Studio", "Graph Gallery", "Preview Canvas", "Data Roles", "Chart Properties", "ATLAS Chart Interpretation", "Generated Code", "Saved Charts", "Export Package"]) {
  assert.match(chartStudio, new RegExp(label), `Chart Studio should render ${label}.`);
}

for (const galleryTab of ["Basic", "Grouped", "Analytical", "Custom", "Matrix", "Panels"]) {
  assert.match(chartStudio, new RegExp(`family: "${galleryTab}"`), `Chart Studio should include the ${galleryTab} gallery tab.`);
}

for (const chartType of ["bar", "line", "scatter", "histogram", "box", "correlation_heatmap", "pareto", "waterfall", "control", "dual_axis", "sankey"]) {
  assert.match(chartStudio, new RegExp(chartType), `Chart Studio should support ${chartType}.`);
}

for (const advancedChartType of ["step", "density", "stacked_bar", "heatmap", "grouped_line", "panel_time", "comparison_panels", "scatter_matrix", "correlation_matrix", "pair_plot", "residual_diagnostic", "lift_decile", "forecast", "survival", "means", "data_profile", "data_profile_matrix", "grouped_bar", "grouped_box", "grouped_scatter", "panel_category", "small_multiples"]) {
  assert.match(chartStudio, new RegExp(`id: "${advancedChartType}".*implemented: true`, "s"), `Advanced chart ${advancedChartType} should be working.`);
}

for (const chartLabel of ["Scatter Plot", "Line Plot", "Histogram", "Box Plot", "Bar Chart", "Correlation Heatmap", "Pareto", "Waterfall", "Control Chart", "Dual Axis", "Sankey"]) {
  assert.match(chartStudio, new RegExp(chartLabel), `Chart Studio should expose ${chartLabel} in the graph gallery.`);
}

for (const advancedLabel of ["Step Plot", "Density Plot", "Stacked Bar", "Heatmap", "Grouped Line", "Panel by Time", "Comparison Panels", "Scatter Matrix", "Correlation Matrix", "Pair Plot", "Residual Diagnostics", "Lift / Decile", "Forecast", "Survival", "Means Plot", "Data Profile", "Data Profile Matrix", "Grouped Bar", "Grouped Box Plot", "Grouped Scatter", "Panel by Category", "Small Multiples"]) {
  assert.match(chartStudio, new RegExp(advancedLabel), `Chart Studio should expose ${advancedLabel}.`);
}

assert.match(chartStudio, /ChartThumbnail/, "Chart Studio must render visual chart thumbnails.");
assert.match(chartStudio, /Best for/, "Chart Studio cards should show best-for guidance.");
assert.match(chartStudio, /Working/, "Chart Studio should label implemented charts as Working.");
assert.match(chartStudio, /Coming soon/, "Chart Studio should label disabled chart cards as Coming soon.");
for (const comingSoonReason of [
  "custom renderer infrastructure is not implemented yet",
  "user-defined visual encodings require a custom role-mapping engine",
  "governed saved template infrastructure is not implemented yet",
]) {
  assert.match(chartStudio, new RegExp(comingSoonReason), `Coming-soon messaging should explain: ${comingSoonReason}`);
}
assert.match(chartStudio, /disabled=\{!chart\.implemented\}/, "Coming-soon chart cards should be disabled.");
assert.match(chartStudio, /setChartType\(chart\.id\)/, "Chart card selection should update the active chart.");
assert.match(chartStudio, /chartAvailability/, "Chart Studio should use explicit availability statuses.");
assert.match(chartStudio, /Needs roles/, "Chart availability should distinguish missing roles.");
assert.match(chartStudio, /Needs category/, "Chart availability should distinguish missing category data.");
assert.match(chartStudio, /Needs source and target/, "Chart availability should distinguish missing flow roles.");
assert.match(chartStudio, /Needs data/, "Chart availability should distinguish missing dataset data.");
assert.match(chartStudio, /Unsupported by current data/, "Chart availability should distinguish unsupported current data.");
assert.match(chartStudio, /Only true Coming soon charts should be disabled.|disabled=\{!chart\.implemented\}/, "Working charts should remain clickable even when roles are incomplete.");

for (const role of ["Category", "Measure", "X numeric", "Y numeric", "Numeric variable", "Source", "Target", "Weight"]) {
  assert.match(chartStudio, new RegExp(role), `Chart Studio should expose ${role} role assignment.`);
}

for (const advancedRole of ["Actual value", "Predicted value", "Score / probability", "Actual outcome", "Positive class value", "Time / order variable", "Forecast horizon", "Duration / time-to-event", "Event indicator", "Panel variable"]) {
  assert.match(chartStudio, new RegExp(advancedRole), `Chart Studio should expose ${advancedRole}.`);
}

for (const roleGuidance of ["Categorical fields", "Numeric fields as discrete categories", "Binned numeric fields", "Generated fields", "None"]) {
  assert.match(chartStudio, new RegExp(roleGuidance), `Role dropdowns should include ${roleGuidance}.`);
}

assert.match(chartStudio, /Enable numeric binning for category roles/, "Chart Studio should expose numeric-binning controls.");
assert.match(chartStudio, /Number of bins/, "Chart Studio should expose bin-count controls.");
assert.match(chartStudio, /Bin method/, "Chart Studio should expose bin-method controls.");
assert.match(chartStudio, /"quantiles"/, "Binned numeric role labels should render.");
assert.match(chartStudio, /binnedRoleValue\(numeric\[0\]\)/, "All-numeric datasets should default category roles to binned numeric fields.");
assert.match(chartStudio, /MedInc_band|_band/, "Generated binned role names should use the _band suffix.");
assert.match(chartStudio, /prepareBinnedRows/, "Chart preview should prepare generated binned fields.");
assert.match(chartStudio, /preserveOrder/, "Binned bar charts should preserve band order where appropriate.");
assert.match(chartStudio, /Select roles to preview this chart/, "Preview canvas should show friendly incomplete-role messaging.");

for (const computeFn of ["residualDiagnosticRows", "liftDecileRows", "forecastRows", "survivalRows", "dataProfileRows", "groupedSegmentRows", "panelRows"]) {
  assert.match(chartStudio, new RegExp(computeFn), `Chart Studio should compute ${computeFn}.`);
}

for (const previewComponent of ["ResidualDiagnosticsPreview", "LiftDecilePreview", "ForecastPreview", "SurvivalPreview", "DataProfilePreview", "GroupedBarPreview", "PanelPreview"]) {
  assert.match(chartStudio, new RegExp(previewComponent), `Chart Studio should render ${previewComponent}.`);
}

assert.match(chartStudio, /Chart Studio v1 uses Dataset Library preview\/sample rows/, "Chart Studio must disclose preview-row usage.");
assert.match(chartStudio, /This interpretation is based on Dataset Library preview\/sample rows/, "Interpretations must include preview-row caution.");
assert.match(chartStudio, /Generated Code/, "Generated code section must exist.");
assert.match(chartStudio, /Python/, "Python chart code must be shown.");
assert.match(chartStudio, /SQL/, "SQL chart data-prep code must be shown.");
assert.match(chartStudio, /SAS-compatible/, "SAS-compatible chart code must be shown.");
assert.match(chartStudio, /Run Python/, "Generated Code should expose Run Python.");
assert.match(chartStudio, /Run SQL on Preview/, "Generated Code should expose Run SQL on Preview.");
assert.match(chartStudio, /Run R \/ Validate R Template/, "Generated Code should expose R execution or validation.");
assert.match(chartStudio, /Run SAS-Compatible Code/, "Generated Code should expose SAS-compatible execution.");
assert.match(chartStudio, /Reset to Generated Code/, "Generated Code should expose reset-to-generated behavior.");
assert.match(chartStudio, /Save Code Snippet/, "Generated Code should allow saving snippets.");
assert.match(chartStudio, /Export Result to Excel/, "Generated Code execution results should export to Excel.");
assert.match(chartStudio, /CodeExecutionResult/, "Generated Code should render an execution result panel.");
assert.match(chartStudio, /runUserPython/, "Chart Studio should reuse the Python execution endpoint.");
assert.match(chartStudio, /runAnalyticsPreviewSql/, "Chart Studio should reuse the SQL preview endpoint.");
assert.match(chartStudio, /runUserR/, "Chart Studio should reuse the R execution endpoint.");
assert.match(chartStudio, /runUserSasCompatible/, "Chart Studio should reuse the SAS-compatible endpoint.");
assert.match(chartStudio, /exportAnalyticsResultExcel/, "Chart Studio should reuse result Excel export.");
assert.match(chartStudio, /saveAnalyticsInsight/, "Chart Studio should save code snippets as analytics insights.");
assert.match(chartStudio, /codeForTab/, "Generated code should use tabbed code selection.");
assert.match(chartStudio, /pd\.qcut/, "Generated Python should include pd.qcut for binned numeric roles.");
assert.match(chartStudio, /dplyr::ntile/, "Generated R should include ntile for binned numeric roles.");
assert.match(chartStudio, /proc rank/i, "Generated SAS-compatible code should include PROC RANK for binned numeric roles.");
assert.match(chartStudio, /Exact .* syntax depends on the production SQL engine/, "Generated SQL should explain binned preview behavior.");
assert.match(chartStudio, /ATLAS Residual Diagnostics/, "Generated code should support residual diagnostics.");
assert.match(chartStudio, /ATLAS Lift \/ Decile/, "Generated code should support lift and decile analysis.");
assert.match(chartStudio, /ATLAS Simple Forecast Preview/, "Generated code should support simple forecast previews.");
assert.match(chartStudio, /Basic Kaplan-Meier style survival preview/, "Generated code should support v1 survival preview.");
assert.match(chartStudio, /ATLAS Data Profile/, "Generated code should support data profile output.");
assert.match(chartStudio, /Save Chart as Insight/, "Save chart action must exist.");
assert.match(chartStudio, /Export Chart Data to Excel/, "Excel export action must exist.");
assert.match(chartStudio, /Dataset Type/, "Chart Studio should expose dataset type filtering.");
assert.match(chartStudio, /Scored Outputs/, "Chart Studio should expose a Scored Outputs dataset filter.");
assert.match(chartStudio, /Register Scored Output to Dataset Library|Scored outputs appear here/, "Chart Studio should document the scored-output integration path.");

assert.match(chartLib, /\/charts\/insights/, "Chart lib must use chart insights endpoint.");
assert.match(chartLib, /\/charts\/export\/excel/, "Chart lib must use chart Excel endpoint.");
assert.match(router, /@router\.get\("\/charts\/insights"\)/, "Backend must list chart insights.");
assert.match(router, /@router\.post\("\/charts\/insights"\)/, "Backend must save chart insights.");
assert.match(router, /@router\.post\("\/charts\/export\/excel"\)/, "Backend must export chart data to Excel.");
assert.match(router, /Summary/, "Excel export must include Summary sheet content.");
assert.match(router, /Chart Data/, "Excel export must include Chart Data sheet.");
assert.match(router, /Role Assignments/, "Excel export must include Role Assignments sheet.");
assert.match(router, /Generated Code/, "Excel export must include Generated Code sheet.");
assert.match(router, /Interpretation/, "Excel export must include Interpretation sheet.");
assert.match(store, /chart_studio/, "Chart store must persist chart_studio analysis type.");
assert.match(store, /chart_diagnostics/, "Chart store must expose diagnostics.");
assert.match(main, /chart_router/, "Server main must import Chart Studio router.");
assert.match(main, /Chart Studio/, "Server main must include Chart Studio router tag.");
assert.match(diagnostics, /chart_diagnostics/, "System diagnostics must include Chart Studio diagnostics.");

assert.match(datasetDetail, /Saved Analytics Insights and Chart Insights/, "Dataset Detail must display chart insights.");
assert.match(datasetDetail, /\/chart-studio/, "Dataset Detail should link to Chart Studio.");
assert.match(projectOverview, /Project Analytics Insights and Chart Insights/, "Project Overview must display chart insights.");
assert.match(projectOverview, /chart_studio/, "Project Overview should route chart insights to Chart Studio.");

console.log("Chart Studio Phase 9G static tests passed.");
