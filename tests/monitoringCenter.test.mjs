import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const read = (path) => readFile(new URL(`../${path}`, import.meta.url), "utf8");
const [
  packageJsonText,
  migration,
  repository,
  service,
  templates,
  router,
  api,
  center,
  detail,
  modelingApp,
  sidebar,
  overview,
  registry,
  registryDetail,
  dashboard,
  registryService,
  serverMain,
] = await Promise.all([
  read("package.json"),
  read("server/persistence/migrations/0008_monitoring_production_control.sql"),
  read("server/persistence/repositories/monitoring_repository.py"),
  read("server/monitoring/monitoring_service.py"),
  read("server/monitoring/monitoring_templates.py"),
  read("server/monitoring/router.py"),
  read("src/lib/monitoringApi.ts"),
  read("src/steps/MonitoringCenter.tsx"),
  read("src/steps/MonitoringPlanDetail.tsx"),
  read("src/apps/ModelingApp.tsx"),
  read("src/components/Sidebar.tsx"),
  read("src/steps/ProjectOverview.tsx"),
  read("src/steps/RegistryPage.tsx"),
  read("src/steps/RegistryAssetDetail.tsx"),
  read("src/steps/ManagementDashboard.tsx"),
  read("server/registry/registry_service.py"),
  read("server/main.py"),
]);

test("Monitoring migration creates production control tables and indexes", () => {
  for (const table of [
    "monitoring_plans",
    "monitoring_metrics",
    "monitoring_runs",
    "monitoring_observations",
    "monitoring_alerts",
    "monitoring_actions",
    "monitoring_baselines",
    "monitoring_events",
  ]) {
    assert.match(migration, new RegExp(`CREATE TABLE IF NOT EXISTS ${table}`));
  }
  for (const indexName of ["idx_monitoring_plans_project", "idx_monitoring_alerts_project", "idx_monitoring_observations_run"]) {
    assert.ok(migration.includes(indexName), `Missing monitoring index ${indexName}`);
  }
  assert.match(repository, /class MonitoringRepository/);
});

test("Monitoring service records governed audit, evidence, notification, event, and decision outputs", () => {
  for (const call of ["self._audit", "self._event", "self._evidence", "self._notify", "self.persistence.decisions.upsert"]) {
    assert.ok(service.includes(call), `Missing service call ${call}`);
  }
  for (const action of ["monitoring_plan_created", "monitoring_plan_activated", "monitoring_alert_accepted_risk", "monitoring_revalidation_review"]) {
    assert.ok(service.includes(action), `Missing monitoring action ${action}`);
  }
  assert.doesNotMatch(detail, /sampleObservedValue|completeMonitoringRun\(created\.run/);
});

test("Monitoring templates cover required workflow families and metric categories", () => {
  for (const workflow of ["predictive_modeling", "credit_risk", "optimization", "time_series_forecasting", "llm_generative_ai", "experimentation", "generic"]) {
    assert.ok(templates.includes(workflow), `Missing monitoring workflow template ${workflow}`);
  }
  for (const metric of ["AUC", "PSI", "Approval rate", "Realized objective value", "MAPE", "Hallucination rate", "Conversion rate"]) {
    assert.ok(templates.includes(metric), `Missing monitoring metric ${metric}`);
  }
});

test("Monitoring API routes and frontend client expose plans, metrics, runs, observations, alerts, actions, and templates", () => {
  assert.match(serverMain, /include_router\(monitoring_router/);
  for (const route of [
    "/monitoring/summary",
    "/monitoring/plans",
    "/monitoring/projects/{project_id}/create-plan",
    "/monitoring/projects/{project_id}/plan",
    "/monitoring/plans/{monitoring_plan_id}/metrics",
    "/monitoring/runs/{monitoring_run_id}/observations",
    "/monitoring/alerts/{alert_id}/create-validation-finding",
    "/monitoring/templates",
  ]) {
    assert.ok(router.includes(route), `Missing monitoring backend route ${route}`);
  }
  for (const path of ["/api/monitoring/summary", "/api/monitoring/plans", "/create-plan", "/seed-from-template", "/accept-risk"]) {
    assert.ok(api.includes(path), `Missing monitoring client path ${path}`);
  }
});

test("Monitoring Center and detail routes are registered and available from Management navigation", () => {
  for (const path of ["/monitoring", "/monitoring/:monitoringPlanId", "/project-monitoring/:projectId"]) {
    assert.ok(modelingApp.includes(`path="${path}"`), `Missing route ${path}`);
  }
  assert.match(sidebar, />Monitoring Center</);
  assert.match(center, /ATLAS Monitoring Center/);
  assert.match(detail, /Monitoring Plan/);
  assert.match(detail, /ShareResourceDialog/);
});

test("Monitoring is integrated into Project Overview, Registry, Registry Detail, and Management Dashboard", () => {
  for (const token of ["Production Monitoring", "Create monitoring plan", "Start monitoring run", "Open Monitoring Center"]) {
    assert.ok(overview.includes(token), `Project Overview missing ${token}`);
  }
  for (const label of ["Monitoring", "Open alerts", "Last monitoring run", "Next monitoring due"]) {
    assert.ok(registry.includes(label), `Registry missing monitoring column ${label}`);
  }
  assert.match(registryDetail, /Production control/);
  assert.match(registryDetail, /Create Monitoring Plan/);
  for (const label of ["Assets under monitoring", "Missing monitoring plans", "Open monitoring alerts", "Revalidation triggers"]) {
    assert.ok(dashboard.includes(label), `Management Dashboard missing ${label}`);
  }
  for (const field of ["monitoring_open_alert_count", "last_monitoring_run_at", "next_monitoring_due_at"]) {
    assert.ok(registryService.includes(field), `Registry service missing monitoring rollup ${field}`);
  }
});

test("Monitoring visible copy contains no mojibake em dash and no fake production language", () => {
  for (const source of [center, detail, overview, registry, registryDetail, dashboard]) {
    assert.doesNotMatch(source, /â€”/);
    assert.doesNotMatch(source, /fake production|demo production/i);
  }
});

test("Monitoring command is registered", () => {
  const packageJson = JSON.parse(packageJsonText);
  assert.equal(packageJson.scripts["test:monitoring-center"], "node tests/monitoringCenter.test.mjs && .\\.venv\\Scripts\\python.exe tests\\monitoring_backend_test.py");
});
