import assert from "node:assert/strict";
import { existsSync } from "node:fs";
import { mkdir, readFile, rm, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import test from "node:test";
import ts from "typescript";

const ROOT = new URL("..", import.meta.url);
const TMP_DIR = fileURLToPath(new URL("../.tmp/phase4-tests", import.meta.url));

async function transpileSource(sourcePath, outputPath) {
  const source = await readFile(new URL(sourcePath, ROOT), "utf8");
  let output = ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.ES2022,
      target: ts.ScriptTarget.ES2022,
    },
  }).outputText;
  output = output.replace(/from\s+["'](\.{1,2}\/[^"']+)["']/g, (match, specifier) => {
    if (specifier.endsWith(".js") || specifier.endsWith(".json")) return match;
    return match.replace(specifier, `${specifier}.js`);
  });
  await mkdir(path.dirname(outputPath), { recursive: true });
  await writeFile(outputPath, output, "utf8");
}

async function compileTestModules() {
  await rm(TMP_DIR, { recursive: true, force: true });
  await transpileSource("src/lib/htmlSanitizer.ts", path.join(TMP_DIR, "src/lib/htmlSanitizer.js"));
  await transpileSource("src/lib/reportReadiness.ts", path.join(TMP_DIR, "src/lib/reportReadiness.js"));
  return {
    htmlSanitizer: await import(pathToFileURL(path.join(TMP_DIR, "src/lib/htmlSanitizer.js")).href),
    reportReadiness: await import(pathToFileURL(path.join(TMP_DIR, "src/lib/reportReadiness.js")).href),
  };
}

const modules = await compileTestModules();

test("Experimental Design feature boundary exposes requested page modules", () => {
  const pages = [
    "ProjectContextPage.tsx",
    "ResearchQuestionPage.tsx",
    "FactorsPage.tsx",
    "LevelsPage.tsx",
    "BlockingPage.tsx",
    "RandomizationPage.tsx",
    "SampleSizePage.tsx",
    "MonteCarloPage.tsx",
    "RunPlanPage.tsx",
    "AnovaPage.tsx",
    "OptimizationPage.tsx",
    "DocumentationPage.tsx",
  ];
  pages.forEach((page) => {
    assert.equal(existsSync(fileURLToPath(new URL(`../src/features/experimental-design/pages/${page}`, import.meta.url))), true);
  });
});

test("report readiness identifies missing champion evidence", () => {
  const summary = modules.reportReadiness.buildReportReadiness({
    problemType: "classification",
    experiments: [],
    champion: null,
    decisions: [],
    dataset: { target: "Class", selected_columns: ["Amount"], rows: [] },
    context: { businessObjective: "Detect fraud.", targetDefinition: "Confirmed fraud." },
  });
  assert.equal(summary.ready, false);
  assert.equal(summary.missingEvidence.some((item) => item.includes("Champion model")), true);
});

test("report sanitizer removes unsafe HTML while preserving safe report markup", () => {
  const sanitized = modules.htmlSanitizer.sanitizeReportHtml(
    '<div class="atlas-table-card" onclick="bad()"><a href="javascript:alert(1)">x</a><script>alert(1)</script></div>'
  );
  assert.equal(sanitized.includes("script"), false);
  assert.equal(sanitized.includes("onclick"), false);
  assert.equal(sanitized.includes("javascript:"), false);
  assert.equal(sanitized.includes("atlas-table-card"), true);
});
