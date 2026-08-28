import assert from "node:assert/strict";
import { after, test } from "node:test";
import { mkdir, readFile, rm, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import ts from "typescript";

const ROOT = new URL("..", import.meta.url);
const TMP = fileURLToPath(new URL("../.tmp/sports-project-persistence-linkage", import.meta.url));

async function transpile(source, output) {
  const code = ts.transpileModule(await readFile(new URL(source, ROOT), "utf8"), {
    compilerOptions: { module: ts.ModuleKind.ES2022, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  await mkdir(path.dirname(output), { recursive: true });
  await writeFile(output, code, "utf8");
}

await rm(TMP, { recursive: true, force: true });
await transpile("src/sports/sportsProjectRoutes.ts", path.join(TMP, "sportsProjectRoutes.js"));
await transpile("src/sports/workflow/sportsAuthorityErrors.ts", path.join(TMP, "sportsAuthorityErrors.js"));
const routes = await import(pathToFileURL(path.join(TMP, "sportsProjectRoutes.js")).href);
const errors = await import(pathToFileURL(path.join(TMP, "sportsAuthorityErrors.js")).href);
after(async () => rm(TMP, { recursive: true, force: true }));

test("route identity is canonical and survives stage navigation", () => {
  assert.equal(routes.canonicalSportsProjectId("server-project", "stale-browser-project"), "server-project");
  assert.equal(routes.canonicalSportsProjectId("", "browser-project"), "browser-project");
  const url = new URL(routes.mlbWorkflowRoute("asp project/1", 2), "http://localhost");
  assert.equal(url.pathname, "/workflows/mlb");
  assert.equal(url.searchParams.get("projectId"), "asp project/1");
  assert.equal(url.searchParams.get("stage"), "2");
});

test("sports authority failures remain distinct and user-facing copy is product-correct", () => {
  assert.equal(errors.sportsAuthorityErrorCode(404, {}), "PROJECT_NOT_REGISTERED");
  assert.equal(errors.sportsAuthorityErrorCode(409, { code: "DATASET_NOT_LINKED" }), "DATASET_NOT_LINKED");
  assert.equal(errors.sportsAuthorityErrorCode(409, { code: "SOURCE_COVERAGE_UNAVAILABLE" }), "SOURCE_COVERAGE_UNAVAILABLE");
  assert.equal(errors.sportsAuthorityErrorCode(422, { code: "SOURCE_COVERAGE_INSUFFICIENT" }), "SOURCE_COVERAGE_INSUFFICIENT");
  assert.equal(errors.sportsAuthorityErrorCode(503, {}), "BACKEND_UNAVAILABLE");
  assert.doesNotMatch(errors.sanitizeSportsAuthorityMessage("ATLAS project was not found in ATLAS persistence."), /ATLAS project|ATLAS persistence/i);
});

const [creation, projects, workflow, canonicalProject, linkage, control, contractPanel, backendStore, workflowStore] = await Promise.all([
  readFile(new URL("src/sports/NewSportsProject.tsx", ROOT), "utf8"),
  readFile(new URL("src/sports/SportsProjects.tsx", ROOT), "utf8"),
  readFile(new URL("src/sports/workflow/GuidedWorkflow.tsx", ROOT), "utf8"),
  readFile(new URL("src/sports/workflow/useCanonicalSportsProject.ts", ROOT), "utf8"),
  readFile(new URL("src/sports/workflow/projectDatasetLinkage.ts", ROOT), "utf8"),
  readFile(new URL("src/sports/workflow/ProjectEvidenceDatasetControl.tsx", ROOT), "utf8"),
  readFile(new URL("src/sports/workflow/ForecastContractPanel.tsx", ROOT), "utf8"),
  readFile(new URL("server/persistence/sports_forecast_contract.py", ROOT), "utf8"),
  readFile(new URL("src/state/useWorkflowStore.ts", ROOT), "utf8"),
]);

test("creation flushes backend persistence before entering a project-scoped workflow", () => {
  const flush = creation.indexOf("await flushProjectDatabaseSave");
  const navigate = creation.indexOf("navigate(workflow.key");
  assert.ok(flush >= 0 && navigate > flush);
  assert.ok(creation.includes("sportsProject: sportsMetadata"));
  assert.ok(creation.includes("mlbWorkflowRoute(state.projectId, 1)"));
  assert.ok(creation.includes("pendingProjectIdRef.current || undefined"));
  assert.ok(creation.includes("pendingProjectIdRef.current = state.projectId"));
  assert.ok(workflowStore.includes("requestedProjectId?.trim() || projectId()"));
});

test("sports projects merge server persistence by canonical ID and reopen exact backend state", () => {
  assert.ok(projects.includes("listProjectsFromDatabase"));
  assert.ok(projects.includes("localById.get(projectId)"));
  assert.ok(projects.includes("loadPersistedSportsProject(projectId)"));
  assert.ok(projects.includes("loadProjectSnapshot(persisted.snapshot)"));
  assert.ok(!projects.includes('project.source === "database" ? persisted.snapshot : project.snapshot'));
  assert.ok(workflow.includes("useCanonicalSportsProject(projectId, stateProjectId)"));
  assert.ok(canonicalProject.includes("loadPersistedSportsProject(projectId, controller.signal)"));
  assert.ok(!canonicalProject.includes("projectId === useWorkflowStore.getState().projectId"));
});

test("evidence selection is project-scoped and does not mutate workspace-active registration", () => {
  assert.ok(linkage.includes("/sports/evidence-dataset"));
  assert.ok(linkage.includes("registrationId"));
  assert.ok(control.includes("Select evidence dataset"));
  assert.ok(control.includes("This does not change the workspace dataset used by other projects."));
  assert.ok(!linkage.includes("/sports/datasets/{registration_id}/activate"));
});

test("sports contract surfaces contain no legacy ATLAS project wording", () => {
  for (const source of [contractPanel, backendStore, workflow, control]) {
    assert.doesNotMatch(source, /ATLAS project|ATLAS persistence|ATLAS project not found/i);
  }
});
