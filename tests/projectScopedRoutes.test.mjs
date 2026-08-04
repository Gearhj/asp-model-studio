import assert from "node:assert/strict";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { randomUUID } from "node:crypto";
import { pathToFileURL } from "node:url";
import test, { after } from "node:test";
import ts from "typescript";

const ROOT = new URL("..", import.meta.url);
const TEMP = await mkdtemp(
  path.join(tmpdir(), `atlas-project-routes-${randomUUID()}-`),
);

async function transpile(sourcePath, outputName, replacements = []) {
  const source = await readFile(new URL(sourcePath, ROOT), "utf8");
  let output = ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.ES2022,
      target: ts.ScriptTarget.ES2022,
      importsNotUsedAsValues: ts.ImportsNotUsedAsValues.Remove,
    },
  }).outputText;
  for (const [pattern, replacement] of replacements) {
    output = output.replace(pattern, replacement);
  }
  const target = path.join(TEMP, outputName);
  await writeFile(target, output, "utf8");
  return target;
}

after(async () => {
  await rm(TEMP, { recursive: true, force: true });
});

await transpile("src/lib/datasetIdentity.ts", "datasetIdentity.mjs");
await transpile("src/config/workflows.ts", "workflows.mjs");
await transpile(
  "src/lib/authoritativeProjectContext.ts",
  "authoritativeProjectContext.mjs",
  [
    [/from\s+["']\.\/datasetIdentity["'];/g, 'from "./datasetIdentity.mjs";'],
    [/from\s+["']\.\.\/config\/workflows["'];/g, 'from "./workflows.mjs";'],
  ],
);
const modulePath = await transpile(
  "src/lib/projectScopedRoutes.ts",
  "projectScopedRoutes.mjs",
  [[
    /from\s+["']\.\/authoritativeProjectContext["'];/g,
    'from "./authoritativeProjectContext.mjs";',
  ]],
);
const routes = await import(pathToFileURL(modulePath).href);

test("every Predictive Modeling step receives the exact encoded project id", () => {
  for (let step = 0; step <= 13; step += 1) {
    const stepId = `step${String(step).padStart(2, "0")}`;
    assert.equal(
      routes.projectWorkflowRoute("project A+regulated", `/${stepId}`),
      `/projects/project%20A%2Bregulated/${stepId}`,
    );
  }
});

test("scoping preserves query and hash suffixes without changing their values", () => {
  assert.equal(
    routes.projectWorkflowRoute(
      "atlas-mrzpau4t",
      "/step01?section=target%20setup&mode=guided#target",
    ),
    "/projects/atlas-mrzpau4t/step01?section=target%20setup&mode=guided#target",
  );
  assert.equal(
    routes.projectWorkflowRoute("atlas-mrzpau4t", "/step01b#special-values"),
    "/projects/atlas-mrzpau4t/step01b#special-values",
  );
});

test("normalization maps scoped steps and predictive slugs to the canonical workflow route", () => {
  assert.equal(
    routes.normalizeWorkflowRoute("/projects/project-a/step02"),
    "/step02",
  );
  assert.equal(
    routes.normalizeWorkflowRoute("/projects/project-a/predictive/data-acquisition"),
    "/step01",
  );
  assert.equal(
    routes.normalizeWorkflowRoute("/projects/project-a/predictive/eda"),
    "/step02",
  );
  assert.equal(routes.normalizeWorkflowRoute("/datasets"), "/datasets");
});

test("an explicit route project always wins over ambient browser state", () => {
  assert.equal(
    routes.projectWorkflowNavigationPath({
      targetPath: "/step02?tab=findings#review",
      routeProjectId: "project-b",
      projectId: "project-a",
      projectName: "Project A",
      projectType: "predictive-modeling",
    }),
    "/projects/project-b/step02?tab=findings#review",
  );
});

test("legacy routing uses only one exact current predictive project", () => {
  assert.equal(
    routes.projectWorkflowNavigationPath({
      targetPath: "/step01?source=library",
      projectId: "project-a",
      projectName: "Authorized Project A",
      projectType: "predictive-modeling",
    }),
    "/projects/project-a/step01?source=library",
  );
});

test("legacy routing never manufactures authority from Untitled or incomplete state", () => {
  for (const candidate of [
    { projectId: "project-a", projectName: "Untitled ATLAS Project", projectType: "predictive-modeling" },
    { projectId: "project-a", projectName: "", projectType: "predictive-modeling" },
    { projectId: "", projectName: "Project A", projectType: "predictive-modeling" },
    { projectId: "project-a", projectName: "Project A", projectType: "optimization" },
  ]) {
    assert.equal(routes.hasExactLegacyProjectCandidate(candidate), false);
    assert.equal(
      routes.projectWorkflowNavigationPath({ targetPath: "/step01", ...candidate }),
      "/projects/open",
    );
  }
});

test("legacy routing has no first, latest, or recently-modified fallback", async () => {
  const source = await readFile(
    new URL("src/lib/projectScopedRoutes.ts", ROOT),
    "utf8",
  );
  assert.doesNotMatch(source, /listProjects|firstProject|latestProject|recentlyModified/i);
  assert.equal(
    routes.projectWorkflowNavigationPath({ targetPath: "/step07" }),
    "/projects/open",
  );
});

test("two route keys remain independent even when the ambient candidate is the other project", () => {
  const projectA = routes.projectWorkflowNavigationPath({
    targetPath: "/step01",
    routeProjectId: "project-a",
    projectId: "project-b",
    projectName: "Project B",
    projectType: "predictive-modeling",
  });
  const projectB = routes.projectWorkflowNavigationPath({
    targetPath: "/step01",
    routeProjectId: "project-b",
    projectId: "project-a",
    projectName: "Project A",
    projectType: "predictive-modeling",
  });
  assert.equal(projectA, "/projects/project-a/step01");
  assert.equal(projectB, "/projects/project-b/step01");
});

test("only explicit project-scoped workflow URLs expose a project id", () => {
  assert.equal(
    routes.scopedProjectIdForPathname("/projects/project-a/step01"),
    "project-a",
  );
  assert.equal(
    routes.scopedProjectIdForPathname("/projects/project%20a/predictive/eda"),
    "project a",
  );
  assert.equal(routes.scopedProjectIdForPathname("/step01"), null);
  assert.equal(routes.scopedProjectIdForPathname("/projects/open/step01"), null);
  assert.equal(routes.scopedProjectIdForPathname("/projects/new/step01"), null);
});

test("non-workflow navigation is never rewritten", () => {
  assert.equal(
    routes.projectWorkflowNavigationPath({
      targetPath: "/datasets?project=project-a",
      routeProjectId: "project-a",
    }),
    "/datasets?project=project-a",
  );
});
