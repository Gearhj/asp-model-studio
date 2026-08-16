import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const root = process.cwd();
const read = (file) => fs.readFileSync(path.join(root, file), "utf8");

const page = read("src/steps/SqlDataStudio.tsx");
const lib = read("src/lib/sqlDataStudio.ts");
const app = read("src/apps/ModelingApp.tsx");
const sidebar = read("src/components/Sidebar.tsx");
const main = read("server/main.py");
const router = read("server/sql_studio/sql_router.py");
const engine = read("server/sql_studio/sql_engine.py");
const store = read("server/sql_studio/sql_store.py");
// The legacy SQL Data Studio hand-off remains a supported alias while normal
// navigation exposes the working sports-native surface as SQL Lab.
const datasetLibrary = read("src/steps/DatasetLibrary.tsx") + "\n" + read("src/lib/datasetActions.ts");
const datasetDetail = read("src/steps/DatasetDetail.tsx");
const packageJson = JSON.parse(read("package.json"));

assert.equal(packageJson.scripts["test:sql-data-studio"], "node tests/sqlDataStudio.test.mjs");

assert.match(app, /SqlDataStudio/);
assert.match(app, /path="\/sql-lab"[^\n]+<SqlDataStudio/);
assert.match(app, /path="\/sql-data-studio"[^\n]+Navigate to="\/sql-lab"/);
assert.match(sidebar, /label: "SQL Lab"/);
assert.match(sidebar, /to: "\/sql-lab"/);

assert.match(main, /sql_studio_router/);
assert.match(main, /include_router\(sql_studio_router/);

[
  '@router.post("/sql-studio/run-preview")',
  '@router.post("/sql-studio/validate")',
  '@router.post("/sql-studio/queries")',
  '@router.get("/sql-studio/queries")',
  '@router.get("/sql-studio/queries/{query_id}")',
  '@router.delete("/sql-studio/queries/{query_id}")',
  '@router.post("/sql-studio/register-result")',
  '@router.post("/sql-studio/export/excel")',
].forEach((snippet) => assert.ok(router.includes(snippet), `Missing SQL Studio endpoint ${snippet}`));

assert.match(engine, /sqlite3\.connect\(":memory:"\)/);
assert.match(engine, /read_version_artifact/);
assert.match(engine, /require_dataset/);
assert.match(engine, /BLOCKED_SQL/);
assert.match(engine, /LIMIT/);
assert.match(store, /SQL_STUDIO_ROOT/);
assert.match(store, /"sql_studio"/);
assert.match(store, /QUERIES_DIR/);
assert.match(store, /audit_event/);

[
  "Object Explorer",
  "SQL Lab",
  "Sports research IDE",
  "Sports SQL Assistant",
  "Data Source",
  "Dataset Library Preview",
  "SQL Results",
  "Tables, Saved Queries, SQL Results, Connectors",
  "Focus Mode",
  "Validate",
  "Run Preview",
  "Format",
  "Save Query",
  "Register Result",
  "Export",
  "Results",
  "Schema",
  "Register Result Form",
  "No external sports warehouse is connected",
  "SELECT *",
  "Sports Research SQL Patterns",
  "Selected Template Preview",
  "Sports Data Profiling",
  "Game & Team Analysis",
  "Player & Participation",
  "Event & Drive Analysis",
  "Temporal Integrity",
  "Model Development",
  "Forward Monitoring",
  "Data Quality",
  "Dataset row count",
  "Sports identity overview",
  "Games by team",
  "Player appearance coverage",
  "Event taxonomy",
  "Plate-appearance outcome coverage",
  "Drive outcome distribution",
  "Forecast cutoff integrity",
  "Calibration table input",
  "Forecast volume over time",
  "Required identity missingness",
  "Source-version control total",
  "Column Mapping",
  "Required columns",
  "Replace editor SQL",
  "Append to editor SQL",
  "Messages",
  "Query History",
  "Lineage",
  "Governance Controls",
  "Read-only SELECT only",
  "Preview/sample-row execution only",
  "Review source rights, identity coverage, and point-in-time integrity",
].forEach((snippet) => assert.ok(page.includes(snippet), `SQL Lab page missing ${snippet}`));

[
  "Financial Services SQL Tasks",
  "Customer / Account Analytics",
  "Credit Risk",
  "Fraud / AML",
  "Marketing / Campaigns",
  "Demo Dataset Examples",
  "Customer 360 summary",
  "REG_TRAIN income band profile",
  "CLASS_TRAIN rare-event summary",
].forEach((snippet) => assert.ok(!page.includes(snippet), `SQL Lab still exposes removed finance-era copy: ${snippet}`));

assert.match(page, /className="grid min-h-\[560px\] gap-3 bg-teal-50\/50 p-3"/);
assert.match(page, /height: "calc\(100vh - 170px\)"/);
assert.match(page, /gridTemplateColumns: focusMode \? "minmax\(700px, 1fr\)" : "260px minmax\(520px, 1fr\) 320px"/);
assert.match(page, /gridTemplateRows: focusMode \? "minmax\(0, 1fr\) 280px" : "minmax\(0, 1fr\) 260px"/);
assert.match(page, /grid-rows-\[auto_auto_minmax\(0,1fr\)\]/);
assert.match(page, /col-start-1 row-start-1 row-span-2/);
assert.match(page, /col-start-3 row-start-1/);
assert.match(page, /col-start-2 col-span-2/);
assert.match(page, /grid-rows-\[auto_minmax\(0,1fr\)\]/);
assert.match(page, /objectExplorerTab/);
assert.match(page, /expandedCategory/);
assert.match(page, /focusMode/);
assert.match(page, /showRegisterPanel/);
assert.match(page, /setShowRegisterPanel\(true\)/);
assert.equal((page.match(/<textarea/g) ?? []).length, 1, "SQL Lab should expose one central editor textarea");
assert.equal((page.match(/label="Run Preview"/g) ?? []).length, 1, "SQL Lab should expose one primary Run Preview action");
assert.equal((page.match(/label="Register Result"/g) ?? []).length, 1, "Register action should open the compact registration panel");
assert.ok(page.indexOf("Sports Research SQL Patterns") > page.indexOf('assistantTab === "sports"'), "Sports patterns should render inside the Assistant sports tab");
assert.ok(page.indexOf("Data Source") > page.indexOf('objectExplorerTab === "tables"'), "Data Source should render inside Object Explorer tables tab");
assert.ok(page.indexOf("Selected Template Preview") > page.indexOf('assistantTab === "sports"'), "Template preview should render as auxiliary Assistant content");
assert.match(page, /Ctrl\+Enter run preview/);
assert.match(page, /Ctrl\+S save query/);
assert.match(page, /Ctrl\+Shift\+F format SQL/);
assert.match(page, /lineCount/);
assert.match(page, /formatSql/);
assert.match(page, /QueryHistoryPanel/);
assert.match(page, /deleteSavedQuery/);
assert.match(page, /Duplicate/);
assert.match(page, /Rename/);
assert.match(page, /const SPORTS_TEMPLATES: SqlTemplate\[\]/);
assert.match(page, /const TEMPLATE_CATEGORIES: TemplateCategory\[\]/);
assert.match(page, /const COLUMN_MAPPINGS = \[/);
assert.match(page, /label: "Game ID"/);
assert.match(page, /label: "Player ID"/);
assert.match(page, /label: "Event \/ play ID"/);
assert.match(page, /label: "Drive ID"/);
assert.match(page, /label: "Forecast timestamp"/);
assert.match(page, /label: "Source-available timestamp"/);
assert.match(page, /label: "Forecast probability \/ score"/);
assert.match(page, /FROM SPORTS_DATASET/);
assert.match(page, /sourcePage: "SQL Lab"/);
assert.match(page, /sourceRoute: "\/sql-lab"/);
assert.match(page, /asp-model-studio-sql-lab-result\.xlsx/);
assert.match(page, /asp-model-studio-sql-definition-lineage\.json/);

[
  "listDatasets",
  "getDatasetProfile",
  "validateSql",
  "runSqlPreview",
  "listSavedSqlQueries",
  "saveSqlQuery",
  "deleteSqlQuery",
  "registerSqlResult",
  "exportSqlResultExcel",
  "createEvidence",
  "downloadBlob",
  "readHistory",
  "writeHistory",
].forEach((snippet) => assert.ok(page.includes(snippet), `SQL Lab page missing retained working machinery ${snippet}`));

[
  "validateSql",
  "runSqlPreview",
  "listSavedSqlQueries",
  "saveSqlQuery",
  "deleteSqlQuery",
  "registerSqlResult",
  "exportSqlResultExcel",
  "safeSqlAlias",
].forEach((snippet) => assert.ok(lib.includes(snippet), `SQL Lab library missing ${snippet}`));

assert.match(datasetLibrary, /SQL Results/);
assert.match(datasetLibrary, /SQL Result/);
assert.match(datasetLibrary, /sql-data-studio/);
assert.match(datasetDetail, /SQL Data Studio Lineage/);
assert.match(datasetDetail, /Registered Query/);
assert.match(datasetDetail, /Source Datasets/);

console.log("Sports-native SQL Lab source contract checks passed.");
