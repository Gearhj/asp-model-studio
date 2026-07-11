import fs from "node:fs";
import path from "node:path";

const root = process.cwd();
const read = (file) => fs.readFileSync(path.join(root, file), "utf8");

function assert(condition, message) {
  if (!condition) {
    console.error(`FAIL: ${message}`);
    process.exitCode = 1;
  } else {
    console.log(`PASS: ${message}`);
  }
}

const packageJson = JSON.parse(read("package.json"));
const app = read("src/apps/ModelingApp.tsx");
const sidebar = read("src/components/Sidebar.tsx");
const page = read("src/steps/NotebookStudio.tsx");
const lib = read("src/lib/notebookStudio.ts");
const main = read("server/main.py");
const router = read("server/notebooks/notebook_router.py");
const store = read("server/notebooks/notebook_store.py");
const exporter = read("server/notebooks/notebook_export.py");
const docsStore = read("server/model_documentation/documentation_store.py");
const datasetDetail = read("src/steps/DatasetDetail.tsx");
const analytics = read("src/steps/AnalyticsWorkbench.tsx");
const sqlStudio = read("src/steps/SqlDataStudio.tsx");
const chartStudio = read("src/steps/ChartStudio.tsx");
const modelDocs = read("src/steps/ModelDocumentationStudio.tsx");

assert(packageJson.scripts["test:notebook-studio"] === "node tests/notebookStudio.test.mjs", "package script exists");
assert(app.includes("import NotebookStudio") && app.includes('path="/notebook-studio"'), "Notebook Studio route is registered");
assert(app.includes('"/notebook-studio"') && app.includes("isFullWidthStudioRoute"), "Notebook Studio uses full-width studio shell");
assert(sidebar.includes("Notebook Studio") && sidebar.includes('to="/notebook-studio"'), "sidebar contains Notebook Studio");

for (const text of [
  "Phase 13D",
  "Default Code Language",
  "New Code cells use",
  "Assistant output language",
  "Generate Code Cell",
  "Generate Chart Cell",
  "Generate Markdown Findings",
  "Code:",
  "Language:",
  "Advanced: Show all languages",
  "Notebook Library",
  "Dataset Context",
  "Notebook Canvas",
  "Governance Controls",
  "Add Cell From Template",
  "Notebook Outputs",
  "Notebook Assistant",
  "Local deterministic assistant. Connect ATLAS_LLM_ENDPOINT",
  "Ask ATLAS",
  "Fix with ATLAS",
  "Insert as New Cell",
  "Replace Current Cell",
  "Continue on error",
  "Running cell",
  "+ Add Cell",
  "In [",
  "Out [",
  "Preview",
  "Add below",
  "Clear output",
  "Visualize Result",
  "Download PNG",
  "Attach Chart to Documentation",
  "Register Table as Dataset",
  "Export Table to Excel",
  "No chart image was captured",
  "Send table to Chart Studio",
  "Run All",
  "Run",
  "Save Notebook",
  "Export .ipynb",
  "Export HTML",
  "Attach Notebook Output to Documentation",
  "Local development execution only",
  "Preview/sample rows only",
  "No SAS license required",
]) {
  assert(page.includes(text), `page contains "${text}"`);
}

for (const cellType of ["markdown", "python", "sql", "r", "sas_compatible"]) {
  assert(page.includes(cellType) || lib.includes(cellType), `supports ${cellType} cells`);
}

for (const endpoint of [
  "/notebooks",
  "/notebooks/{notebook_id}",
  "/notebooks/{notebook_id}/run-cell",
  "/notebooks/{notebook_id}/run-all",
  "/notebooks/{notebook_id}/export/ipynb",
  "/notebooks/{notebook_id}/export/html",
  "/notebooks/{notebook_id}/attach-to-documentation",
]) {
  assert(router.includes(endpoint), `backend exposes ${endpoint}`);
}

assert(main.includes("notebook_router") && main.includes('tags=["Notebook Studio"]'), "backend router is registered");
assert(router.includes("run_python_request") && router.includes("run_preview_sql") && router.includes("run_r") && router.includes("run_sas_compatible_endpoint"), "all code execution paths are wired");
assert(store.includes("MAX_OUTPUT_ROWS") && store.includes("MAX_OUTPUT_IMAGES") && store.includes("compact_images") && store.includes("notebook_index.json"), "notebook persistence is compact and indexed");
assert(exporter.includes('"nbformat": 4') && exporter.includes("display_data") && exporter.includes("image/png") && exporter.includes("build_html"), "ipynb and HTML export builders include rich outputs");
assert(docsStore.includes("Notebook Studio") && docsStore.includes("list_notebook_evidence"), "notebook evidence is available to documentation");
assert(lib.includes("CELL_TEMPLATE_SNIPPETS") && lib.includes("Correlation Heatmap") && lib.includes("Box Plot") && lib.includes("Residual Plot") && lib.includes("PROC CONTENTS"), "expanded code templates are available");
assert(lib.includes("defaultCodeLanguage") && lib.includes("NotebookCodeLanguage") && lib.includes("cellKind") && lib.includes("language?"), "notebook object model supports default language and code cell metadata");
assert(lib.includes("normalizeNotebook") && lib.includes("firstCodeLanguage") && lib.includes("effectiveCellLanguage"), "existing notebook migration preserves code language and order");
assert(lib.includes("createCodeCell") && lib.includes("defaultSourceForCell"), "Code cells are created from selected language defaults");
assert(page.includes("Default Code Language") && page.includes("NOTEBOOK_CODE_LANGUAGES.map"), "default code language selector is rendered");
assert(page.includes("addNotebookCell(\"markdown\")") && page.includes("addNotebookCell(\"code\")"), "primary add controls use Markdown and Code");
assert(!page.includes("CELL_TYPES.map"), "primary workflow no longer renders separate language add buttons");
assert(page.includes("visibleTemplates") && page.includes("Advanced: Show all languages"), "templates filter by selected language with advanced override");
assert(page.includes("Assistant output language") && page.includes("defaultCodeLanguage"), "Notebook Assistant follows selected language");
assert(page.includes("updateCellLanguage") && page.includes("Language:"), "code cell language override is available");
assert(router.includes("defaultCodeLanguage"), "backend persists notebook default code language");
assert(router.includes("captureImages=True"), "Python notebook cells request image capture");
const pythonExecution = read("server/python_execution.py");
assert(pythonExecution.includes("ATLAS_IMAGE_OUTPUTS_JSON"), "Python execution captures matplotlib images");
assert(pythonExecution.includes("def atlas_display") && pythonExecution.includes("ATLAS_TABLE_OUTPUTS_JSON"), "atlas_display table helper is wired");
assert(page.includes("cellRefs") && page.includes("scrollIntoView") && page.includes("setPendingFocusCellId"), "new cells focus or scroll into view");
assert(page.includes("ASSISTANT_QUICK_PROMPTS") && page.includes("deterministicAssistantSuggestion"), "deterministic Notebook Assistant is wired");

assert(datasetDetail.includes("Open Notebook Studio"), "Dataset Detail links to Notebook Studio");
assert(analytics.includes("Send to Notebook Studio"), "Analytics Workbench links to Notebook Studio");
assert(sqlStudio.includes("Send Query to Notebook Studio"), "SQL Data Studio links to Notebook Studio");
assert(chartStudio.includes("Send Chart Evidence to Notebook Studio"), "Chart Studio links to Notebook Studio");
assert(modelDocs.includes("Notebook outputs") && modelDocs.includes("Pull Notebook Studio Evidence"), "Model Documentation Studio surfaces notebook evidence");

if (process.exitCode) {
  console.error("Notebook Studio smoke checks failed.");
  process.exit(process.exitCode);
}

console.log("Notebook Studio smoke checks passed.");
