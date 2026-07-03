import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import ts from "typescript";

async function importTypeScriptModule(path) {
  const source = await readFile(path, "utf8");
  const transpiled = ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.ES2022,
      target: ts.ScriptTarget.ES2022,
    },
  }).outputText;
  return import(`data:text/javascript;charset=utf-8,${encodeURIComponent(transpiled)}`);
}

const design = await importTypeScriptModule(new URL("../src/lib/experimentalDesign.ts", import.meta.url));

const twoByTwoText = `
Pricing Strategy
• Current Pricing
• Personalized Pricing

Contact Channel
• Email
• SMS
`;

test("2 factors x 2 levels produces 4 treatment cells", () => {
  const factors = design.parseFactorHierarchy(twoByTwoText);
  assert.equal(factors.length, 2);
  assert.equal(design.treatmentCellCount(factors), 4);
  assert.equal(design.fullFactorialModelDf(factors), 3);
});

test("3 factors x 2 levels produces 8 treatment cells", () => {
  const factors = design.parseFactorHierarchy(`
Pricing Strategy
• Current Pricing
• Personalized Pricing

Contact Channel
• Email
• SMS

Timing
• Morning
• Evening
`);
  assert.equal(factors.length, 3);
  assert.equal(design.treatmentCellCount(factors), 8);
  assert.equal(design.fullFactorialModelDf(factors), 7);
  assert.deepEqual(Object.keys(design.generateTreatmentMatrix(factors)[0]), ["cell", "Pricing Strategy", "Contact Channel", "Timing"]);
});

test("levels are not promoted into independent factors", () => {
  const factors = design.parseFactorHierarchy(twoByTwoText);
  assert.deepEqual(factors, [
    { factorName: "Pricing Strategy", levels: ["Current Pricing", "Personalized Pricing"] },
    { factorName: "Contact Channel", levels: ["Email", "SMS"] },
  ]);
});

test("treatment matrix uses factor names as columns", () => {
  const factors = design.parseFactorHierarchy(twoByTwoText);
  assert.deepEqual(Object.keys(design.generateTreatmentMatrix(factors)[0]), ["cell", "Pricing Strategy", "Contact Channel"]);
  assert.deepEqual(design.generateTreatmentMatrix(factors), [
    { cell: "T1", "Pricing Strategy": "Current Pricing", "Contact Channel": "Email" },
    { cell: "T2", "Pricing Strategy": "Current Pricing", "Contact Channel": "SMS" },
    { cell: "T3", "Pricing Strategy": "Personalized Pricing", "Contact Channel": "Email" },
    { cell: "T4", "Pricing Strategy": "Personalized Pricing", "Contact Channel": "SMS" },
  ]);
});

test("ANOVA terms use factor names only", () => {
  const factors = design.parseFactorHierarchy(twoByTwoText);
  const terms = design.generateFullFactorialTerms(factors);
  assert.deepEqual(terms, ["Pricing Strategy", "Contact Channel", "Pricing Strategy × Contact Channel"]);
  assert.equal(terms.some((term) => /Current Pricing|Personalized Pricing|Email|SMS/.test(term)), false);
});

test("analysis object uses factor hierarchy for KPIs and report evidence", () => {
  const analysis = design.buildExperimentalDesignAnalysis({
    stepLabel: "ANOVA",
    currentState: { objective: "Response Rate", numeric: { baselineRate: 10, expectedLift: 20, alpha: 5, power: 80, sampleSize: 25000 } },
    nodeStates: {
      Levels: { objective: twoByTwoText },
      "Sample Size": { numeric: { baselineRate: 10, expectedLift: 20, alpha: 5, power: 80, sampleSize: 25000 } },
    },
  });
  assert.equal(analysis.stepLabel, "ANOVA");
  assert.equal(analysis.kpis.find((kpi) => kpi.label === "Factors")?.value, "2");
  assert.equal(analysis.kpis.find((kpi) => kpi.label === "Treatment Cells")?.value, "4");
  assert.equal(analysis.evidenceTables.some((table) => table.title === "Generated ANOVA Terms"), true);
  assert.equal(analysis.interpretation.includes("model term"), true);
});

test("sample size plan is derived from treatment cells", () => {
  const plan = design.experimentalSampleSizePlan(
    { numeric: { baselineRate: 10, expectedLift: 20, alpha: 5, power: 80, sampleSize: 25000 } },
    4
  );
  assert.equal(plan.treatmentCells, 4);
  assert.equal(plan.total, plan.perCell * 4);
  assert.equal(plan.plannedPerCell, 6250);
  assert.equal(plan.plannedTotal, 25000);
  assert.equal(plan.expectedPower >= 0.79, true);
});
