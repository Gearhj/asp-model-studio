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
const analyticsExportUtils = read("server/analytics/export_utils.py");
const analyticsStore = read("server/analytics/analytics_store.py");
const pythonExecution = read("server/python_execution.py");
const main = read("server/main.py");
const app = read("src/apps/ModelingApp.tsx");
const sidebar = read("src/components/Sidebar.tsx");
const workbench = read("src/steps/AnalyticsWorkbench.tsx");
const workbenchLib = read("src/lib/analyticsWorkbench.ts");
const codeExecutionLib = read("src/lib/codeExecution.ts");
const codeWorkspacePanel = read("src/components/code/CodeWorkspacePanel.tsx");
const codeLanguageTabs = read("src/components/code/CodeLanguageTabs.tsx");
const codeExecutionResult = read("src/components/code/CodeExecutionResult.tsx");
const sasCompatible = read("server/code_execution/sas_compatible.py");
const datasetDetail = read("src/steps/DatasetDetail.tsx");
const projectOverview = read("src/steps/ProjectOverview.tsx");
const datasetRegistry = read("server/datasets/dataset_registry.py");
const sasRuntimeConfig = read("server/artifacts/config/sas_runtime.json");
const sasRuntimeExample = read("server/artifacts/config/sas_runtime.example.json");
const rootRequirements = read("requirements.txt");
const serverRequirements = read("server/requirements.txt");

[
  '@router.get("/analytics/insights")',
  '@router.post("/analytics/insights")',
  '@router.get("/analytics/insights/{insight_id}")',
  '@router.delete("/analytics/insights/{insight_id}")',
  '@router.post("/analytics/audit-run")',
  '@router.post("/analytics/sql/run")',
  '@router.get("/analytics/diagnostics")',
  '@router.post("/analytics/export/excel")',
  '@router.post("/analytics/export/word")',
  '@router.post("/analytics/export/powerpoint")',
  '@router.post("/analytics/export/result/excel")',
].forEach((snippet) => assert(analyticsRouter.includes(snippet), `Missing analytics endpoint: ${snippet}`));

assert(analyticsExportUtils.includes("build_excel_export") && analyticsExportUtils.includes("openpyxl"), "Excel export utility must use openpyxl.");
assert(analyticsExportUtils.includes("build_result_excel_export") && analyticsExportUtils.includes("column_explorer") && analyticsExportUtils.includes("sas_compatible_result"), "Module-level Excel result export utility is missing required result types.");
assert(analyticsExportUtils.includes("build_word_export") && analyticsExportUtils.includes("Document"), "Word export utility must use python-docx.");
assert(analyticsExportUtils.includes("build_powerpoint_export") && analyticsExportUtils.includes("Presentation"), "PowerPoint export utility must use python-pptx.");
assert(rootRequirements.includes("openpyxl") && rootRequirements.includes("python-docx") && rootRequirements.includes("python-pptx"), "Root requirements must include Office export dependencies.");
assert(serverRequirements.includes("openpyxl") && serverRequirements.includes("python-docx") && serverRequirements.includes("python-pptx"), "Server requirements must include Office export dependencies.");

assert(main.includes("analytics_router") && main.includes("Analytics Workbench"), "Analytics router is not registered in server/main.py.");
assert(analyticsStore.includes("server/artifacts") || analyticsStore.includes("ANALYTICS_ROOT"), "Analytics insights must be stored as backend artifacts.");
assert(analyticsStore.includes("require_dataset(dataset_id)"), "Analytics store must enforce Dataset Library ACLs.");
assert(analyticsStore.includes("analytics.insight.saved") && analyticsStore.includes("analytics.insight.deleted"), "Analytics insight audit events are missing.");
assert(analyticsStore.includes("analytics.access.denied"), "Analytics denied access audit event is missing.");
assert(datasetRegistry.includes("analytics_diagnostics"), "System diagnostics must include analytics checks.");
assert(analyticsStore.includes("analytics_sql_preview") && analyticsStore.includes("analytics_r_template") && analyticsStore.includes("analytics_sas_compatible"), "System diagnostics must include SQL, R, and SAS-compatible workspace checks.");

assert(app.includes("AnalyticsWorkbench") && app.includes('path="/analytics"'), "Analytics Workbench route is not registered.");
assert(sidebar.includes("Analytics Workbench") && sidebar.includes('to="/analytics"'), "Sidebar is missing Analytics Workbench navigation.");
assert(workbench.includes("Business Question"), "Workbench is missing business-question capture.");
assert(workbench.includes("Save Business Question"), "Business question save action is missing.");
assert(workbench.includes("Clean Up Question") && workbench.includes("ATLAS_LLM_ENDPOINT") && !workbench.includes("ATALS"), "Business question cleanup action or ATLAS spelling is wrong.");
assert(pythonExecution.includes('@router.post("/llm/cleanup-question")') && codeExecutionLib.includes("/llm/cleanup-question") && pythonExecution.includes('"source": "deterministic"'), "LLM cleanup endpoint/client must provide deterministic fallback.");
assert(workbench.includes("Generate Analysis Plan"), "Analysis plan generation action is missing.");
assert(workbench.includes("analysis_plan_generated"), "Analysis plan audit event is missing.");
assert(workbench.includes("Insight Assistant"), "Workbench is missing the Insight Assistant.");
assert(codeWorkspacePanel.includes("Multi-Language Code Workspace") && codeLanguageTabs.includes("Python") && codeLanguageTabs.includes("SQL") && codeLanguageTabs.includes("SAS"), "Shared multi-language Code Workspace tabs are missing.");
assert(workbench.includes("CodeWorkspacePanel") && workbench.includes('language: "python"') && workbench.includes('language: "sql"') && workbench.includes('language: "r"') && workbench.includes('language: "sas"'), "Analytics Workbench must expose Python, SQL, R, and SAS tabs.");
assert(codeWorkspacePanel.includes("activeLanguage") && codeWorkspacePanel.includes("onActiveLanguageChange"), "Code Workspace must support external active-language control.");
assert(workbench.includes("Run User Python") && codeExecutionLib.includes("/python/run"), "Workbench Python integration is missing.");
assert(workbench.includes("context:") && workbench.includes("preview_rows") && workbench.includes("primary_preview_rows"), "Workbench does not pass dataset preview rows into Python execution context.");
assert(workbench.includes("ATLAS Analytics Workbench Python smoke test passed."), "Workbench Python smoke test text is missing.");
assert(pythonExecution.includes("ATLAS_CODE_SANDBOX_COMMAND") && pythonExecution.includes("execution_env()") && pythonExecution.includes("pd.DataFrame(preview_rows)"), "Python execution must require a sandbox and create df from preview_rows.");
assert(pythonExecution.includes('@router.get("/python/diagnostics")') && codeExecutionLib.includes("/python/diagnostics"), "Python diagnostics endpoint/client is missing.");
assert(pythonExecution.includes("rscriptDetected") && pythonExecution.includes("saspyInstalled"), "R/SAS execution diagnostics are missing.");
assert(pythonExecution.includes('@router.post("/code/r/run")') && codeExecutionLib.includes("/code/r/run"), "R execution endpoint/client is missing.");
assert(pythonExecution.includes('@router.post("/code/sas/run")') && codeExecutionLib.includes("/code/sas/run"), "SAS execution endpoint/client is missing.");
assert(pythonExecution.includes('@router.post("/code/sas-compatible/run")') && codeExecutionLib.includes("/code/sas-compatible/run"), "SAS-compatible execution endpoint/client is missing.");
assert(pythonExecution.includes('@router.get("/code/sas/diagnostics")') && codeExecutionLib.includes("/code/sas/diagnostics"), "SAS diagnostics endpoint/client is missing.");
assert(pythonExecution.includes('@router.post("/code/sas/settings")') && codeExecutionLib.includes("/code/sas/settings"), "SAS settings endpoint/client is missing.");
assert(pythonExecution.includes('@router.post("/code/sas/test-connection")') && codeExecutionLib.includes("/code/sas/test-connection"), "SAS connection test endpoint/client is missing.");
assert(pythonExecution.includes("Rscript") && pythonExecution.includes("atlas_preview.csv") && pythonExecution.includes("read.csv"), "R execution must use Rscript and temporary preview CSV.");
assert(pythonExecution.includes("SASsession") && pythonExecution.includes("df2sd") && pythonExecution.includes("sasExecutionAvailable"), "SAS execution must use SASPy only when configured.");
assert(pythonExecution.includes("ATLAS_SAS_CFGNAME") && pythonExecution.includes("ATLAS_SAS_CFGFILE") && pythonExecution.includes("ATLAS_SAS_EXECUTION_MODE"), "SAS diagnostics must check ATLAS SAS environment variables.");
assert(pythonExecution.includes("sascfg_personal.py") && pythonExecution.includes("sascfg.py") && pythonExecution.includes("server/artifacts/config"), "SAS diagnostics must detect common and project SASPy config locations.");
assert(pythonExecution.includes("SAS template validated") && codeExecutionResult.includes("Template validation guidance"), "SAS template validation must be neutral guidance, not a red execution failure.");
assert(sasRuntimeConfig.includes('"executionMode": "template_only"') && sasRuntimeConfig.includes('"lastConnectionOk": false'), "Default SAS runtime config must start in template-only mode.");
assert(sasRuntimeExample.includes('"cfgname": "winlocal"') && sasRuntimeExample.includes('"executionMode": "saspy_config"'), "SAS runtime example config is missing practical SASPy guidance.");
assert(workbench.includes("cleanPythonStderr") && codeExecutionResult.includes("Execution completed with warnings"), "Workbench must suppress non-fatal Python bootstrap stderr and label real warnings clearly.");
assert(workbench.includes("Generated SQL") || codeWorkspacePanel.includes("Generated"), "SQL workspace is missing.");
assert(workbench.includes("Logical ATLAS reference:") && workbench.includes("FROM REG_TRAIN") || workbench.includes("executableTableName"), "Generated SQL must use executable preview table names and keep logical references in comments.");
assert(workbench.includes("Run SQL on Preview") && workbench.includes("SqlResultPanel"), "SQL workspace must execute preview SELECT queries and render result tables.");
assert(workbenchLib.includes("/analytics/sql/run") && analyticsRouter.includes("sqlite3.connect") && analyticsRouter.includes("Only a single SELECT statement is allowed"), "SQLite preview SQL endpoint or unsafe statement controls are missing.");
assert(analyticsRouter.includes("INSERT") && analyticsRouter.includes("DROP") && analyticsRouter.includes("ALTER") && analyticsRouter.includes("PRAGMA"), "Unsafe SQL keyword blocking is incomplete.");
assert(workbench.includes("R execution is not configured on this machine") && workbench.includes("buildRTemplate") && workbench.includes("library(dplyr)"), "R template/status support is missing.");
assert(workbench.includes("ATLAS SAS-Compatible, no SAS license required") && workbench.includes("buildSasTemplate") && workbench.includes("proc contents") && workbench.includes("proc means") && workbench.includes("proc corr") && workbench.includes("proc print"), "SAS-compatible template/status support is missing.");
assert(workbench.includes("Code Runtime Configuration") && workbench.includes("Refresh Runtime Diagnostics") && workbench.includes("Rscript") && workbench.includes("SASPy") && workbench.includes("SAS-Compatible Engine"), "Runtime diagnostics UI is missing.");
assert(workbench.includes("Advanced: Licensed SAS Bridge") && workbench.includes("Optional SASPy Runtime Setup") && workbench.includes("Save SAS Runtime Settings") && workbench.includes("Test SAS Connection") && workbench.includes("Reset to Template Only"), "Optional licensed SAS bridge controls are missing.");
assert(workbench.includes("Template only") && workbench.includes("SASPy configured session") && workbench.includes("External SAS export only"), "SAS execution mode choices are missing.");
assert(workbench.includes("Local SAS") && workbench.includes("Remote SAS server") && workbench.includes("SAS Studio / Viya") && workbench.includes("Export only"), "SAS setup guidance by environment is missing.");
assert(workbench.includes("Run SAS-Compatible Code") && workbench.includes("SAS-compatible") && workbench.includes("No SAS license is required"), "SAS tab must default to SAS-compatible execution.");
assert(codeExecutionResult.includes("SAS-compatible execution succeeded") && codeExecutionResult.includes("Unsupported SAS statements") && codeExecutionResult.includes("TRANSLATED PYTHON"), "SAS-compatible results must render tables, warnings, and translated Python.");
assert(sasCompatible.includes("def run_sas_compatible") && sasCompatible.includes("PROC CONTENTS") && sasCompatible.includes("PROC MEANS") && sasCompatible.includes("PROC FREQ") && sasCompatible.includes("PROC CORR") && sasCompatible.includes("PROC PRINT") && sasCompatible.includes("PROC SQL") && sasCompatible.includes("PROC RANK"), "SAS-compatible parser must support the v1 PROC set.");
assert(sasCompatible.includes("pd.qcut") && sasCompatible.includes("sqlite3.connect") && sasCompatible.includes("Unsupported statement detected"), "SAS-compatible execution must support rank, SQL, and partial unsupported warnings.");
assert(workbench.includes("rResult") && workbench.includes("sasResult") && !workbench.includes("{sqlResult && <SqlResultPanel"), "Language-specific result state is not scoped correctly.");
assert(workbench.includes("Add Comparison / Join Dataset"), "Secondary dataset selector is missing.");
assert(workbench.includes("joinType") && workbench.includes("merge(") && workbench.includes("JOIN"), "Join template generation is missing.");
assert(workbench.includes("saveAnalyticsInsight") && workbench.includes("listAnalyticsInsights"), "Workbench is missing saved-insight integration.");
assert(workbench.includes("generatedPython") && workbench.includes("generatedSql") && workbench.includes("generatedR") && workbench.includes("generatedSas") && workbench.includes("businessQuestion"), "Saved insight payload must include question, Python, SQL, R, SAS, and dataset context.");
assert(workbench.includes("Histogram") && workbench.includes("Group Comparison") && workbench.includes("Correlation"), "Workbench is missing required analytical modules.");
assert(workbench.includes("Data Quality Review"), "Workbench is missing data quality review.");
assert(workbench.includes("Recommended Analyses for This Question"), "Business-question-driven recommended analyses are missing.");
assert(workbench.includes("Pivot Table Builder") && workbench.includes("buildPivot") && workbench.includes("PivotTable"), "Pivot Table Builder implementation is missing.");
assert(workbench.includes("Auto-bin numeric row fields into quantiles") && workbench.includes("Auto-bin numeric column fields into quantiles") && workbench.includes("autoBinColumns") && workbench.includes("pd.qcut") && workbench.includes("Save Pivot as Insight"), "Pivot row/column binning, generated Python, or save action is missing.");
assert(workbench.includes("pivot_table") && workbench.includes("pivotConfig") && workbench.includes("pivotPreview"), "Saved pivot insight payload is incomplete.");
assert(workbench.includes("-- Pivot Table Builder template") && workbench.includes("GROUP BY") && workbench.includes("COUNT(*) AS n") && workbench.includes("aggregation.replace"), "Generated SQL must include executable pivot template guidance.");
assert(codeWorkspacePanel.includes("Save {current.label} as Insight") && workbench.includes('saveCodeInsight("python"') && workbench.includes('saveCodeInsight("sas"'), "Language-specific code snippet save actions are missing.");
assert(workbench.includes("workTable") && workbench.includes("Table available as:"), "Generated SAS must include WORK preview table guidance.");
assert(workbench.includes("Use Generated Code") && workbench.includes('(["python", "sql", "r", "sas"] as CodeLanguage[])') && workbench.includes("useGeneratedCode(language)"), "Insight Assistant must expose compact Python/SQL/R/SAS generated-code actions.");
assert(workbench.includes("setActiveCodeLanguage(language)") && workbench.includes("setUser(config.generated)"), "Generated-code actions must switch tabs and load generated code.");
assert(workbench.includes("SAS-compatible") && workbench.includes("code snippet") && workbench.includes("languageLabel") && workbench.includes("userEditedCode") && workbench.includes("generatedCode"), "Saved code snippets must record active language metadata.");
assert(workbench.includes("SavedFindingItem") && workbench.includes("SAS-compatible") && workbench.includes("filterInsights") && workbench.includes("insightFilter"), "Saved Findings must display language badges and filters.");
assert(workbench.includes("buildExportPayload") && workbench.includes("generatedPython") && workbench.includes("generatedSql") && workbench.includes("generatedR") && workbench.includes("generatedSas") && workbench.includes("activeLanguage") && workbench.includes("activeCode"), "Export insight payload must include all four language code fields.");
assert(workbenchLib.includes("exportAnalyticsPackage") && workbenchLib.includes("/analytics/export/") && workbenchLib.includes("response.blob()"), "Analytics Workbench must expose binary Office export downloads.");
assert(workbenchLib.includes("exportAnalyticsResultExcel") && workbenchLib.includes("/analytics/export/result/excel"), "Analytics Workbench must expose module-level Excel result downloads.");
assert(workbench.includes("Export Analysis") && workbench.includes("Export Code Workspace Result") && workbench.includes("SavedFindingExportMenu"), "Analytics Workbench must expose export actions in assistant, code workspace, and saved findings.");
assert(workbench.includes('resultType="column_explorer"') && workbench.includes('resultType="target_relationship"') && workbench.includes('resultType="group_comparison"') && workbench.includes('resultType="data_quality"') && workbench.includes('resultType="pivot"'), "Column Explorer, Target Relationship, Group Comparison, Data Quality, and Pivot modules must have Export to Excel actions.");
assert(workbench.includes("sas_compatible_result") && workbench.includes("python_result") && workbench.includes("r_result") && workbench.includes("sql_result"), "Code execution result Excel export types are missing.");
assert(workbench.includes("Export to Excel") && workbench.includes("Export to Word") && workbench.includes("Export to PowerPoint"), "Full report exports must keep explicit Excel, Word, and PowerPoint labels.");
assert(!workbench.includes("Export pivot analysis"), "Pivot module must not expose report-level Word/PowerPoint export controls.");
assert(workbench.includes("downloadExport") && workbench.includes('downloadExport("excel"') || workbench.includes('onExport("excel")'), "Analytics Workbench Excel export action is missing.");
assert(workbench.includes("pivotRows") && workbench.includes("sqlResult") && workbench.includes("sasResult") && workbench.includes("pythonResult") && workbench.includes("rResult"), "Office export payload must include pivot, SQL, SAS-compatible, Python, and R outputs.");

assert(pythonExecution.includes("context: Dict[str, Any]") && pythonExecution.includes("preview_rows = ATLAS_CONTEXT.get"), "Python execution endpoint does not inject preview_rows context.");

assert(workbenchLib.includes("/analytics/insights") && workbenchLib.includes("/analytics/audit-run"), "Analytics frontend API client is incomplete.");
assert(datasetDetail.includes("Saved Analytics Insights") && datasetDetail.includes("listAnalyticsInsights"), "Dataset Detail must show saved analytics insights.");
assert(projectOverview.includes("Project Analytics Insights") && projectOverview.includes("listAnalyticsInsights"), "Project Overview must show project-linked analytics insights.");

console.log("Analytics Workbench v1 static checks passed.");
