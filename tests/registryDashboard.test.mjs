import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const read = (path) => readFile(new URL(`../${path}`, import.meta.url), "utf8");
const [
  modelingApp,
  sidebar,
  registryApi,
  dashboard,
  registry,
  detail,
  overview,
  serverMain,
  registryRouter,
  registryService,
  evidenceHelper,
  evidenceContract,
  packageJsonText,
] = await Promise.all([
  read("src/apps/ModelingApp.tsx"),
  read("src/components/Sidebar.tsx"),
  read("src/lib/registryApi.ts"),
  read("src/steps/ManagementDashboard.tsx"),
  read("src/steps/RegistryPage.tsx"),
  read("src/steps/RegistryAssetDetail.tsx"),
  read("src/steps/ProjectOverview.tsx"),
  read("server/main.py"),
  read("server/registry/router.py"),
  read("server/registry/registry_service.py"),
  read("src/lib/persistedEvidenceStatus.ts"),
  read("shared/evidence_status_contract.json"),
  read("package.json"),
]);

test("Management routes and full-width workspace are registered", () => {
  assert.match(modelingApp, /path="\/management-dashboard" element=\{<ManagementDashboard/);
  assert.match(modelingApp, /path="\/registry" element=\{<RegistryPage/);
  assert.match(modelingApp, /path="\/registry\/:projectId" element=\{<RegistryAssetDetail/);
  assert.match(modelingApp, /location\.pathname\.startsWith\("\/registry\/"\)/);
});

test("Sidebar has one consolidated Management navigation group", () => {
  assert.match(sidebar, /<NavGroup label="Management">/);
  for (const label of ["Management Dashboard", "Model / Decision Registry", "Validation Queue", "Model Evidence Center", "Audit Log"]) {
    assert.match(sidebar, new RegExp(`>${label}<`));
  }
  assert.equal((sidebar.match(/to="\/model-evidence-center"/g) ?? []).length, 1);
  assert.equal((sidebar.match(/to="\/audit"/g) ?? []).length, 1);
});

test("Registry client exposes every persisted backend endpoint", () => {
  for (const path of ["/registry/assets", "/registry/summary", "/registry/actions", "/registry/activity", "/registry/owners"]) {
    assert.ok(registryApi.includes(path), `Missing registry client path ${path}`);
  }
  assert.match(registryApi, /X-ATLAS-USER-ID|persistenceRequest/);
  assert.match(registryApi, /credentials:|persistenceRequest/);
});

test("Management Dashboard renders real portfolio rollups and empty states", () => {
  for (const call of ["getRegistrySummary", "getRegistryAssets", "getRegistryActions", "getRegistryActivity", "getRegistryOwners"]) {
    assert.match(dashboard, new RegExp(`${call}\\(`));
  }
  for (const label of ["Total assets", "Active development", "Ready for review", "Validation complete", "Evidence ready", "Documentation ready", "Open actions", "Recent activity"]) {
    assert.ok(dashboard.includes(label), `Missing dashboard metric ${label}`);
  }
  assert.match(dashboard, /Lifecycle distribution/);
  assert.match(dashboard, /Analytical asset mix/);
  assert.match(dashboard, /Portfolio owners/);
  assert.match(dashboard, /Open governance actions/);
  assert.match(dashboard, /No open governance actions/);
  assert.doesNotMatch(dashboard, /mock|fixture|demo asset/i);
});

test("Registry inventory exposes required filters, statuses, and actions", () => {
  for (const filter of ["asset_type", "workflow_type", "lifecycle_status", "owner_user_id", "evidence_status", "documentation_status", "validation_status", "search"]) {
    assert.ok(registry.includes(filter), `Missing registry filter ${filter}`);
  }
  for (const label of ["Name", "Type", "Workflow / Template", "Owner", "Lifecycle", "Evidence", "Documentation", "Validation", "Recommendation", "Implementation", "Last activity", "Actions"]) {
    assert.ok(registry.includes(label), `Missing registry column ${label}`);
  }
  assert.match(registry, /\/registry\/\$\{encodeURIComponent\(asset\.project_id\)\}/);
  assert.match(registry, /to="\/projects\/open"/);
  assert.match(registry, /to="\/model-evidence-center"/);
  assert.match(registry, /No assets match these filters/);
});

test("Registry detail renders traceable asset lifecycle records", () => {
  for (const title of [
    "Asset summary",
    "Lifecycle derivation",
    "Persisted asset timeline",
    "Evidence readiness",
    "Documentation readiness",
    "Latest analytical runs",
    "Recommendation and implementation",
    "Export artifacts",
    "Open governance actions",
    "Recent audit trail",
  ]) assert.ok(detail.includes(title), `Missing detail section ${title}`);
  for (const optimizationMetric of ["total_cost", "demand_fulfilled", "active_routes", "scenario_count", "validation_score"]) {
    assert.ok(registryService.includes(optimizationMetric), `Missing optimization metric ${optimizationMetric}`);
  }
  assert.match(detail, /lifecycle_derivation\.matched_rule/);
  assert.match(detail, /missing_required_types/);
  assert.match(detail, /No analytical runs persisted/);
  assert.match(detail, /No governed exports persisted/);
});

test("Project Overview uses the canonical registry service", () => {
  assert.match(overview, /getRegistryAsset\(projectId\)/);
  assert.match(overview, /getRegistryAssets\(\{ search: projectName/);
  assert.match(overview, /title="Registry Status"/);
  for (const field of ["lifecycle_status", "evidence_status", "documentation_status", "validation_status", "recommendation_status", "implementation_status", "open_action_count", "last_activity_at"]) {
    assert.ok(overview.includes(field), `Project Overview is missing registry field ${field}`);
  }
  assert.match(overview, /\/registry\/\$\{encodeURIComponent\(registryDetail\.asset\.project_id\)\}/);
});

test("Backend routes and shared evidence readiness contract are canonical", () => {
  assert.match(serverMain, /include_router\(registry_router, prefix="\/api"/);
  for (const route of ["/assets", "/assets/{project_id}", "/summary", "/actions", "/activity", "/owners"]) {
    assert.ok(registryRouter.includes(route), `Missing backend route ${route}`);
  }
  assert.match(evidenceHelper, /evidence_status_contract\.json/);
  assert.match(registryService, /evidence_status_contract\.json/);
  const contract = JSON.parse(evidenceContract);
  assert.deepEqual(Object.keys(contract), ["generated", "captured", "ready", "approved", "stale", "rejected"]);
});

test("Registry UI visible copy contains no em dash", () => {
  for (const source of [dashboard, registry, detail]) assert.doesNotMatch(source, /—/);
});

test("Registry dashboard command is registered", () => {
  const packageJson = JSON.parse(packageJsonText);
  assert.equal(packageJson.scripts["test:registry-dashboard"], "node tests/registryDashboard.test.mjs && .\\.venv\\Scripts\\python.exe tests\\registry_backend_test.py");
});
