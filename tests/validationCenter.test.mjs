import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const read = (path) => readFile(new URL(`../${path}`, import.meta.url), "utf8");
const [
  packageJsonText,
  serverMain,
  migration,
  repository,
  router,
  service,
  templates,
  validationApi,
  queuePage,
  detailPage,
  modelingApp,
  sidebar,
  dashboard,
  registryDetail,
  projectOverview,
  registryService,
] = await Promise.all([
  read("package.json"),
  read("server/main.py"),
  read("server/persistence/migrations/0005_validation_center.sql"),
  read("server/persistence/repositories/validation_repository.py"),
  read("server/validation/router.py"),
  read("server/validation/validation_service.py"),
  read("server/validation/validation_templates.py"),
  read("src/lib/validationApi.ts"),
  read("src/steps/ValidationQueue.tsx"),
  read("src/steps/ValidationCaseDetail.tsx"),
  read("src/apps/ModelingApp.tsx"),
  read("src/components/Sidebar.tsx"),
  read("src/steps/ManagementDashboard.tsx"),
  read("src/steps/RegistryAssetDetail.tsx"),
  read("src/steps/ProjectOverview.tsx"),
  read("server/registry/registry_service.py"),
]);

test("Validation persistence creates the required SQLite tables", () => {
  for (const table of [
    "validation_cases",
    "validation_findings",
    "validation_checklist_items",
    "validation_challenges",
    "validation_responses",
    "validation_approvals",
    "validation_case_events",
  ]) {
    assert.match(migration, new RegExp(`CREATE TABLE IF NOT EXISTS ${table}`));
  }
  assert.match(repository, /class ValidationRepository/);
  assert.match(repository, /upsert_case/);
  assert.match(repository, /create_event/);
});

test("Validation API exposes intake, queue, case, challenge, response, checklist, approval, and summary endpoints", () => {
  assert.match(serverMain, /include_router\(validation_router, prefix="\/api"/);
  for (const route of [
    "/queue",
    "/summary",
    "/project/{project_id}",
    "/project/{project_id}/submit",
    "/cases/{validation_id}",
    "/start-review",
    "/checklist/{item_key}",
    "/findings",
    "/challenges",
    "/responses",
    "/approvals",
  ]) {
    assert.ok(router.includes(route), `Missing validation route ${route}`);
  }
});

test("Validation service records audit, events, and decision journal for major events", () => {
  for (const call of ["self._event", "self._audit", "self._decision"]) {
    assert.ok(service.includes(call), `Missing service recording call ${call}`);
  }
  for (const action of ["validation.submitted", "validation.review_started", "validation.approval_recorded"]) {
    assert.ok(service.includes(action), `Missing validation major event ${action}`);
  }
  assert.match(service, /No validation record exists|create_or_submit_case/);
});

test("Validation templates cover required workflow types without default fake cases", () => {
  for (const template of ["optimization", "predictive_modeling", "ab_testing", "experimental_design", "time_series_forecasting", "llm_generative_ai", "generic"]) {
    assert.ok(templates.includes(template), `Missing template ${template}`);
  }
  assert.doesNotMatch(service, /demo validation|fake validation|sample case/i);
  assert.match(queuePage, /No validation cases submitted/);
});

test("Frontend routes and client are registered", () => {
  for (const path of ["/validation", "/validation/:validationId", "/project-validation/:projectId"]) {
    assert.ok(modelingApp.includes(`path="${path}"`), `Missing route ${path}`);
  }
  for (const apiPath of ["/validation/queue", "/validation/summary", "/validation/project/", "/start-review", "/approvals"]) {
    assert.ok(validationApi.includes(apiPath), `Missing validation client path ${apiPath}`);
  }
});

test("Sidebar and dashboard expose validation management without duplicating core links", () => {
  assert.match(sidebar, />Validation Queue</);
  assert.equal((sidebar.match(/to="\/model-evidence-center"/g) ?? []).length, 1);
  assert.equal((sidebar.match(/to="\/audit"/g) ?? []).length, 1);
  for (const label of ["Validation queue", "In review", "Returned", "Validation findings", "Approved cases"]) {
    assert.ok(dashboard.includes(label), `Dashboard missing ${label}`);
  }
});

test("Registry and Project Overview link to validation intake", () => {
  assert.match(registryDetail, /\/project-validation\/\$\{encodeURIComponent\(asset\.project_id\)\}/);
  assert.match(projectOverview, /\/project-validation\/\$\{encodeURIComponent\(registryDetail\.asset\.project_id\)\}/);
  assert.match(registryDetail, /Validation & Challenge Center/);
  assert.match(projectOverview, /Open Validation Queue/);
});

test("Registry service consumes validation cases for status, findings, actions, lifecycle, and timeline", () => {
  for (const token of ["validation_case", "validation_findings", "validation_events", "validation_needed", "validation_findings_open", "Approved with Conditions"]) {
    assert.ok(registryService.includes(token), `Registry integration missing ${token}`);
  }
});

test("Validation UI visible copy contains no em dash", () => {
  for (const source of [queuePage, detailPage, dashboard, registryDetail, projectOverview]) {
    assert.doesNotMatch(source, /—/);
  }
});

test("Validation command is registered", () => {
  const packageJson = JSON.parse(packageJsonText);
  assert.equal(packageJson.scripts["test:validation-center"], "node tests/validationCenter.test.mjs && .\\.venv\\Scripts\\python.exe tests\\validation_backend_test.py");
});
