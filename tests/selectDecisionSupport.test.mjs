import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import ts from "typescript";

async function importTypeScriptModule(path) {
  const source = await readFile(path, "utf8");
  const transpiled = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.ES2022, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  return import(`data:text/javascript;charset=utf-8,${encodeURIComponent(transpiled)}`);
}

const support = await importTypeScriptModule(new URL("../src/lib/selectDecisionSupport.ts", import.meta.url));
const providerSource = await readFile(new URL("../src/components/AtlasSelectDecisionSupport.tsx", import.meta.url), "utf8");
const appSource = await readFile(new URL("../src/apps/ModelingApp.tsx", import.meta.url), "utf8");
const workflowSource = await readFile(new URL("../src/steps/WorkflowPlaceholderStep.tsx", import.meta.url), "utf8");

test("all named Experimental Design choices have curated definition, use case, and example", () => {
  for (const value of support.experimentalDesignGuidanceValues) {
    assert.equal(support.hasCuratedSelectionGuidance(value), true, `Missing curated guidance for ${value}`);
    const guidance = support.getSelectionGuidance({ label: "Experimental Design", value });
    assert.ok(guidance.definition.length > 30, `${value} needs a useful definition`);
    assert.ok(guidance.useWhen.length > 30, `${value} needs a useful best-used-when explanation`);
    assert.ok(guidance.example.length > 20, `${value} needs a concrete example`);
  }
});

test("dynamic dataset, column, metric, and method selects receive role-aware fallback guidance", () => {
  const cases = [
    ["Optimization dataset", "Portfolio Capacity 2026", "governed analytical data source"],
    ["Target column", "default_flag", "Maps"],
    ["Primary metric", "PR-AUC", "selected Primary metric"],
    ["Solver method", "Custom decomposition", "Configures"],
  ];
  for (const [label, value, expected] of cases) {
    const guidance = support.getSelectionGuidance({ label, value, options: [value, "Alternative"] });
    assert.ok(guidance.definition.includes(expected), `${label} should use a role-aware fallback`);
    assert.ok(guidance.useWhen.length > 20);
    assert.ok(guidance.example.length > 20);
  }
});

test("global select decision support intercepts every native select and supports option comparison", () => {
  assert.match(providerSource, /document\.addEventListener\("focusin"/);
  assert.match(providerSource, /document\.addEventListener\("change"/);
  assert.match(providerSource, /target instanceof HTMLSelectElement/);
  assert.match(providerSource, /Compare available options/);
  assert.match(providerSource, /Definition:/);
  assert.match(providerSource, /Best used when:/);
  assert.match(providerSource, /Example:/);
  assert.match(appSource, /<AtlasSelectDecisionSupport \/>/);
});

test("Experimental Design inline dropdown descriptions use the shared registry", () => {
  assert.match(workflowSource, /getSelectionGuidance\(\{ label: "Experimental design selection", value \}\)/);
  for (const label of ["Experiment family", "Analysis \/ design intent", "Factor strategy", "Level coding"]) {
    assert.match(workflowSource, new RegExp(label.replace("/", "\\/")));
  }
});
