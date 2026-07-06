import fs from "node:fs";
import path from "node:path";

const root = process.cwd();
const read = (file) => fs.readFileSync(path.join(root, file), "utf8");

function assert(condition, message) {
  if (!condition) {
    throw new Error(message);
  }
}

const analyticsRouter = read("server/analytics/analytics_router.py");
const analyticsStore = read("server/analytics/analytics_store.py");
const pythonExecution = read("server/python_execution.py");
const main = read("server/main.py");
const app = read("src/apps/ModelingApp.tsx");
const sidebar = read("src/components/Sidebar.tsx");
const workbench = read("src/steps/AnalyticsWorkbench.tsx");
const workbenchLib = read("src/lib/analyticsWorkbench.ts");
const datasetDetail = read("src/steps/DatasetDetail.tsx");
const projectOverview = read("src/steps/ProjectOverview.tsx");
const datasetRegistry = read("server/datasets/dataset_registry.py");

[
  '@router.get("/analytics/insights")',
  '@router.post("/analytics/insights")',
  '@router.get("/analytics/insights/{insight_id}")',
  '@router.delete("/analytics/insights/{insight_id}")',
  '@router.post("/analytics/audit-run")',
  '@router.get("/analytics/diagnostics")',
].forEach((snippet) => assert(analyticsRouter.includes(snippet), `Missing analytics endpoint: ${snippet}`));

assert(main.includes("analytics_router") && main.includes("Analytics Workbench"), "Analytics router is not registered in server/main.py.");
assert(analyticsStore.includes("server/artifacts") || analyticsStore.includes("ANALYTICS_ROOT"), "Analytics insights must be stored as backend artifacts.");
assert(analyticsStore.includes("require_dataset(dataset_id)"), "Analytics store must enforce Dataset Library ACLs.");
assert(analyticsStore.includes("analytics.insight.saved") && analyticsStore.includes("analytics.insight.deleted"), "Analytics insight audit events are missing.");
assert(analyticsStore.includes("analytics.access.denied"), "Analytics denied access audit event is missing.");
assert(datasetRegistry.includes("analytics_diagnostics"), "System diagnostics must include analytics checks.");

assert(app.includes("AnalyticsWorkbench") && app.includes('path="/analytics"'), "Analytics Workbench route is not registered.");
assert(sidebar.includes("Analytics Workbench") && sidebar.includes('to="/analytics"'), "Sidebar is missing Analytics Workbench navigation.");
assert(workbench.includes("Business Question"), "Workbench is missing business-question capture.");
assert(workbench.includes("Save Business Question"), "Business question save action is missing.");
assert(workbench.includes("Clean Up with ATLAS LLM"), "Business question cleanup action is missing.");
assert(workbench.includes("Generate Analysis Plan"), "Analysis plan generation action is missing.");
assert(workbench.includes("analysis_plan_generated"), "Analysis plan audit event is missing.");
assert(workbench.includes("Insight Assistant"), "Workbench is missing the Insight Assistant.");
assert(workbench.includes("Run User Python") && workbench.includes("/python/run"), "Workbench Python integration is missing.");
assert(workbench.includes("context:") && workbench.includes("preview_rows") && workbench.includes("primary_preview_rows"), "Workbench does not pass dataset preview rows into Python execution context.");
assert(workbench.includes("ATLAS Analytics Workbench Python smoke test passed."), "Workbench Python smoke test text is missing.");
assert(pythonExecution.includes("env=os.environ.copy()") && pythonExecution.includes("pd.DataFrame(preview_rows)"), "Python execution must inherit environment and create df from preview_rows.");
assert(workbench.includes("SQL Workspace") && workbench.includes("Generated SQL") && workbench.includes("User-Edited SQL"), "SQL workspace is missing.");
assert(workbench.includes("atlas_dataset.") && workbench.includes("SQL execution is preview-only in v1"), "Generated SQL logical reference or preview-only message is missing.");
assert(workbench.includes("Validate SQL Template") && workbench.includes("SQL Template Validation"), "SQL workspace must be honest preview/validation UI, not fake execution.");
assert(workbench.includes("Add Comparison / Join Dataset"), "Secondary dataset selector is missing.");
assert(workbench.includes("joinType") && workbench.includes("merge(") && workbench.includes("JOIN"), "Join template generation is missing.");
assert(workbench.includes("saveAnalyticsInsight") && workbench.includes("listAnalyticsInsights"), "Workbench is missing saved-insight integration.");
assert(workbench.includes("generatedPython") && workbench.includes("generatedSql") && workbench.includes("businessQuestion"), "Saved insight payload must include question, Python, SQL, and dataset context.");
assert(workbench.includes("Histogram") && workbench.includes("Group Comparison") && workbench.includes("Correlation"), "Workbench is missing required analytical modules.");
assert(workbench.includes("Data Quality Review"), "Workbench is missing data quality review.");
assert(workbench.includes("Recommended Analyses for This Question"), "Business-question-driven recommended analyses are missing.");
assert(workbench.includes("Pivot Table Builder") && workbench.includes("buildPivot") && workbench.includes("PivotTable"), "Pivot Table Builder implementation is missing.");
assert(workbench.includes("Auto-bin numeric rows into quantiles") && workbench.includes("pd.qcut") && workbench.includes("Save Pivot as Insight"), "Pivot binning, generated Python, or save action is missing.");
assert(workbench.includes("pivot_table") && workbench.includes("pivotConfig") && workbench.includes("pivotPreview"), "Saved pivot insight payload is incomplete.");
assert(workbench.includes("-- Pivot Table Builder template") && workbench.includes("Numeric quantile binning shown conceptually"), "Generated SQL must include pivot template guidance.");

assert(pythonExecution.includes("context: Dict[str, Any]") && pythonExecution.includes("preview_rows = ATLAS_CONTEXT.get"), "Python execution endpoint does not inject preview_rows context.");

assert(workbenchLib.includes("/analytics/insights") && workbenchLib.includes("/analytics/audit-run"), "Analytics frontend API client is incomplete.");
assert(datasetDetail.includes("Saved Analytics Insights") && datasetDetail.includes("listAnalyticsInsights"), "Dataset Detail must show saved analytics insights.");
assert(projectOverview.includes("Project Analytics Insights") && projectOverview.includes("listAnalyticsInsights"), "Project Overview must show project-linked analytics insights.");

console.log("Analytics Workbench v1 static checks passed.");
