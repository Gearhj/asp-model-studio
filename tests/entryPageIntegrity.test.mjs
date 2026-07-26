// Predictive Modeling entry pages -- route context and guide truthfulness.
//
// Guards the two defects proven in this phase:
//   A. the breadcrumb's last segment was the first INCOMPLETE workflow step,
//      not the active route, so completed early steps made every page read
//      ".../ EDA";
//   B. the Atlas Guide's "N% confidence" badge averaged per-item constants that
//      were hardcoded at each recommendation site -- nothing measured them.
import assert from "node:assert/strict";
import { mkdir, readFile, rm, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import test from "node:test";
import ts from "typescript";

const ROOT = new URL("..", import.meta.url);
const TMP_DIR = fileURLToPath(new URL("../.tmp/entry-page-tests", import.meta.url));

async function transpile(sourcePath, outputName) {
  const source = await readFile(new URL(sourcePath, ROOT), "utf8");
  const output = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.ES2022, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  const outPath = path.join(TMP_DIR, outputName);
  await mkdir(path.dirname(outPath), { recursive: true });
  await writeFile(outPath, output, "utf8");
  return import(pathToFileURL(outPath).href);
}

await rm(TMP_DIR, { recursive: true, force: true });
const crumbs = await transpile("src/lib/breadcrumbs.ts", "breadcrumbs.js");

const modelingApp = await readFile(new URL("src/apps/ModelingApp.tsx", ROOT), "utf8");
const copilot = await readFile(new URL("src/components/CopilotCard.tsx", ROOT), "utf8");
const profileService = await readFile(new URL("server/preprocessing/governed_profile_service.py", ROOT), "utf8");

// --- Part A: route-derived breadcrumbs -------------------------------------

test("1-3. each entry page reports its own route", () => {
  const project = { projectName: "Credit Card Transaction Fraud Model - TEST", workflowLabel: "Predictive Modeling" };

  const open = crumbs.buildBreadcrumbs({ pathname: "/projects/open", ...project });
  assert.equal(crumbs.breadcrumbText(open), "ATLAS / Projects / Open Project");

  const context = crumbs.buildBreadcrumbs({ pathname: "/step00", ...project });
  assert.equal(
    crumbs.breadcrumbText(context),
    "ATLAS / Credit Card Transaction Fraud Model - TEST / Predictive Modeling / Project Context"
  );

  const acquisition = crumbs.buildBreadcrumbs({ pathname: "/step01", ...project });
  assert.equal(
    crumbs.breadcrumbText(acquisition),
    "ATLAS / Credit Card Transaction Fraud Model - TEST / Predictive Modeling / Data Acquisition"
  );
});

test("4. no entry page shows EDA in its breadcrumb", () => {
  const project = { projectName: "Fraud", workflowLabel: "Predictive Modeling" };
  for (const pathname of ["/projects/open", "/step00", "/step01"]) {
    const trail = crumbs.breadcrumbText(crumbs.buildBreadcrumbs({ pathname, ...project }));
    assert.doesNotMatch(trail, /EDA|Exploratory/, `${pathname} must not display EDA`);
  }
  // The EDA route itself still resolves correctly.
  assert.match(
    crumbs.breadcrumbText(crumbs.buildBreadcrumbs({ pathname: "/step02", ...project })),
    /Exploratory Data Analysis$/
  );
});

test("breadcrumbs never expose implementation route names", () => {
  for (const pathname of ["/step00", "/step01", "/step02", "/step06", "/step11"]) {
    const trail = crumbs.breadcrumbText(crumbs.buildBreadcrumbs({ pathname, projectName: "P", workflowLabel: "W" }));
    assert.doesNotMatch(trail, /step\d/i, `${pathname} leaked its route name`);
  }
});

test("project-management routes carry no project or workflow segment", () => {
  const trail = crumbs.buildBreadcrumbs({
    pathname: "/projects/open",
    projectName: "Fraud",
    workflowLabel: "Predictive Modeling",
  });
  assert.deepEqual(trail.map((crumb) => crumb.label), ["ATLAS", "Projects", "Open Project"]);
});

test("the active page is marked with aria-current semantics", () => {
  const trail = crumbs.buildBreadcrumbs({ pathname: "/step01", projectName: "P", workflowLabel: "W" });
  const current = trail.filter((crumb) => crumb.current);
  assert.equal(current.length, 1, "exactly one crumb is the current page");
  assert.equal(current[0].label, "Data Acquisition");
  assert.match(modelingApp, /aria-current="page"/);
  assert.match(modelingApp, /aria-label="Breadcrumb"/);
  assert.match(modelingApp, /data-testid="atlas-breadcrumb"/);
});

test("the breadcrumb is derived from the route, not workflow completion", () => {
  assert.match(modelingApp, /pathname: location\.pathname/, "the active route must drive the trail");
  // The old derivation is still used for progress, but must not feed the trail.
  const header = modelingApp.slice(modelingApp.indexOf("<nav"), modelingApp.indexOf("</nav>"));
  assert.doesNotMatch(header, /currentStep/, "workflow completion state must not appear in the breadcrumb");
});

// --- Part B: truthful guide basis ------------------------------------------

test("7. the unexplained confidence percentage is removed", () => {
  assert.doesNotMatch(copilot, /\{confidence\}% confidence/, "the decorative badge must be gone");
  assert.doesNotMatch(copilot, /function confidenceScore/, "the averaging of hardcoded constants must be gone");
  assert.match(copilot, /data-testid="guide-basis-badge"/);
  assert.match(copilot, /guideBasisLabel/);
});

test("the guide reports a truthful, non-numeric basis", async () => {
  // Transpiling CopilotCard is impractical (heavy React imports), so the pure
  // label function's contract is asserted from its implementation text.
  assert.match(copilot, /return "Rule-based";/);
  assert.match(copilot, /Rule-based - \$\{items\.length\} detected condition/);
  // No percentage is reconstructed anywhere in the badge path.
  const badge = copilot.slice(copilot.indexOf('data-testid="guide-basis-badge"') - 400, copilot.indexOf('data-testid="guide-basis-badge"') + 400);
  assert.doesNotMatch(badge, /%/, "the basis badge must not render a percentage");
});

// --- Part H: the target is not a predictor ---------------------------------

test("12. the target is excluded from predictor near-zero-variance findings", () => {
  assert.match(
    profileService,
    /if distinct <= 1 and str\(column\) != target:/,
    "a constant-column finding must skip the target"
  );
  assert.match(
    profileService,
    /if str\(column\) in constant_columns or str\(column\) == target:/,
    "a near-zero-variance finding must skip the target"
  );
  assert.match(profileService, /"targetExcludedFromPredictorFindings"/, "the exclusion must be disclosed, not silent");
});

test("the target remains part of Target Health", () => {
  // Event counts, prevalence, and target missingness still come from the target.
  for (const key of ['"eventCount"', '"nonEventCount"', '"eventRate"', '"targetMissingCount"', '"targetDistinctCount"']) {
    assert.ok(profileService.includes(key), `${key} must remain in the quality response`);
  }
});
