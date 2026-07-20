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
const datasetLibrary = read("src/steps/DatasetLibrary.tsx");
const datasetDetail = read("src/steps/DatasetDetail.tsx");
const packageJson = JSON.parse(read("package.json"));

assert.equal(packageJson.scripts["test:sql-data-studio"], "node tests/sqlDataStudio.test.mjs");

assert.match(app, /SqlDataStudio/);
assert.match(app, /path="\/sql-data-studio"/);
assert.match(sidebar, /SQL Data Studio/);
assert.match(sidebar, /to="\/sql-data-studio"/);

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
  "SQL Assistant",
  "Data Source",
  "Dataset Library Preview",
  "SQL Results",
  "Compact IDE shell",
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
  "Connector not configured in this local build",
  "SELECT *",
  "Financial Services SQL Tasks",
  "Selected Template Preview",
  "Customer / Account Analytics",
  "Credit Risk",
  "Fraud / AML",
  "Marketing / Campaigns",
  "Model Development",
  "Monitoring",
  "Data Quality",
  "Demo Dataset Examples",
  "Customer 360 summary",
  "Delinquency rate by segment",
  "High-risk transaction review",
  "Campaign population waterfall",
  "Train/Test/OOT population summary",
  "Monthly score distribution",
  "Null rate by column",
  "REG_TRAIN income band profile",
  "CLASS_TRAIN rare-event summary",
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
].forEach((snippet) => assert.ok(page.includes(snippet), `SQL Studio page missing ${snippet}`));

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
assert.equal((page.match(/<textarea/g) ?? []).length, 1, "SQL Studio should expose one central editor textarea");
assert.equal((page.match(/label="Run Preview"/g) ?? []).length, 1, "SQL Studio should expose one primary Run Preview action");
assert.equal((page.match(/label="Register Result"/g) ?? []).length, 1, "Register action should open the compact registration panel");
assert.ok(page.indexOf("Financial Services SQL Tasks") > page.indexOf('assistantTab === "financial"'), "Financial tasks should render inside the Assistant financial tab");
assert.ok(page.indexOf("Data Source") > page.indexOf('objectExplorerTab === "tables"'), "Data Source should render inside Object Explorer tables tab");
assert.ok(page.indexOf("Selected Template Preview") > page.indexOf('assistantTab === "financial"'), "Template preview should render as auxiliary Assistant content");
assert.match(page, /Ctrl\+Enter run preview/);
assert.match(page, /Ctrl\+S save query/);
assert.match(page, /Ctrl\+Shift\+F format SQL/);
assert.match(page, /lineCount/);
assert.match(page, /formatSql/);
assert.match(page, /QueryHistoryPanel/);
assert.match(page, /deleteSavedQuery/);
assert.match(page, /Duplicate/);
assert.match(page, /Rename/);

[
  "validateSql",
  "runSqlPreview",
  "listSavedSqlQueries",
  "saveSqlQuery",
  "deleteSqlQuery",
  "registerSqlResult",
  "exportSqlResultExcel",
  "safeSqlAlias",
].forEach((snippet) => assert.ok(lib.includes(snippet), `SQL Studio lib missing ${snippet}`));

assert.match(datasetLibrary, /SQL Results/);
assert.match(datasetLibrary, /SQL Result/);
assert.match(datasetLibrary, /sql-data-studio/);
assert.match(datasetDetail, /SQL Data Studio Lineage/);
assert.match(datasetDetail, /Registered Query/);
assert.match(datasetDetail, /Source Datasets/);

console.log("SQL Data Studio Phase 12 smoke checks passed.");
