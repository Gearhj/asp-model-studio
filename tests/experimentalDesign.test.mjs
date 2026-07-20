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
const workflows = await importTypeScriptModule(new URL("../src/config/workflows.ts", import.meta.url));
const workflowSource = await readFile(new URL("../src/config/workflows.ts", import.meta.url), "utf8");
const experimentalWorkflowSource = await readFile(new URL("../src/steps/WorkflowPlaceholderStep.tsx", import.meta.url), "utf8");
const copilotSource = await readFile(new URL("../src/components/CopilotCard.tsx", import.meta.url), "utf8");

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
      "Sample Size": { numeric: { baselineRate: 10, expectedLift: 20, alpha: 5, power: 80, sampleSize: 25000, samplePlanConfirmed: 1 } },
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

test("run plan analysis carries forward Monte Carlo summary evidence", () => {
  const analysis = design.buildExperimentalDesignAnalysis({
    stepLabel: "Experiment Run Plan",
    currentState: {},
    nodeStates: {
      Levels: { objective: twoByTwoText },
      "Sample Size": { numeric: { baselineRate: 10, expectedLift: 20, alpha: 5, power: 80, sampleSize: 25000, samplePlanConfirmed: 1 } },
      "Monte Carlo Simulation": {
        simulationResults: {
          meanPower: 0.942,
          wrongWinnerRate: 0.042,
          recommendedAction: "Proceed",
        },
      },
    },
  });
  assert.equal(analysis.kpis.find((kpi) => kpi.label === "MC Readiness")?.value, "Proceed");
  assert.equal(analysis.kpis.find((kpi) => kpi.label === "Wrong Winner")?.value, "4.2%");
  assert.equal(analysis.interpretation.includes("Monte Carlo validation is Proceed"), true);
});

test("experimental design workflow routes progress to the correct next step", () => {
  const workflow = workflows.getWorkflowDefinition("experimental-design");
  assert.equal(workflow.steps.find((step) => step.label === "Monte Carlo Simulation")?.route, "/workflow/experimental-design/8");
  assert.equal(workflow.steps[7].label, "Monte Carlo Simulation");
  assert.equal(workflow.steps[8].label, "Experiment Run Plan");
  assert.equal(workflow.steps[9].label, "ANOVA");
  assert.equal(workflow.steps[10].label, "Optimization");
  assert.equal(workflow.steps[11].label, "Documentation");
  assert.equal(workflow.steps[11].route, "/workflow/experimental-design/12");
  assert.equal(workflow.steps[12], undefined);
  assert.match(workflowSource, /question: "How will we execute and monitor the experiment\?"/);
});

test("experimental design pages keep planning assumptions separate from observed evidence", () => {
  assert.match(experimentalWorkflowSource, /ATLAS suggestions remain optional and are never treated as user-confirmed evidence/);
  assert.match(experimentalWorkflowSource, /Analysis specification/);
  assert.match(experimentalWorkflowSource, /It does not invent F statistics, p-values, effect sizes, or residual diagnostics/);
  assert.match(experimentalWorkflowSource, /Planning scenario only/);
  assert.match(experimentalWorkflowSource, /Decision State" value="Evidence required/);
  assert.doesNotMatch(experimentalWorkflowSource, /const autosaveLabels = new Set/);
});

test("project context requires an explicit experimental data strategy and never invents acquisition evidence", () => {
  for (const expected of [
    "Data Strategy and Acquisition",
    "Prospective collection",
    "Existing data",
    "Hybrid",
    "Completed experiment",
    "Dataset Library version",
    "Upload dataset",
    "Required analytical schema",
    "Experimental unit ID",
    "Primary response",
    "Data lineage and provenance",
    "Data quality and reconciliation plan",
    "Confirm Data Strategy",
    "Designed experiments often begin before a dataset exists.",
    "Best used for:",
    "Confirmed evidence only",
    "Confirm a prospective capture plan or governed dataset strategy before continuing to Research Question.",
    "Complete the confirmed Project Context before continuing.",
    "population and experimental unit",
    "operational constraints",
    "governance and approval requirements",
    "experiment family",
    "primary response or evidence metric",
  ]) {
    assert.match(experimentalWorkflowSource, new RegExp(expected.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")), `Missing Experimental Design data-strategy artifact: ${expected}`);
  }

  const projectContextStart = experimentalWorkflowSource.indexOf("function ProjectContextPage");
  const projectContextEnd = experimentalWorkflowSource.indexOf("function ResearchQuestionPage", projectContextStart);
  const projectContextSource = experimentalWorkflowSource.slice(projectContextStart, projectContextEnd);
  assert.doesNotMatch(projectContextSource, /\|\| 25000/);
  assert.doesNotMatch(projectContextSource, /const population = Math\.max\(1, Math\.round\(state\.numeric\.sampleSize/);
});

test("experimental design does not silently create a factor hierarchy", () => {
  const normalizeStart = experimentalWorkflowSource.indexOf("function normalizeDesignFactors");
  const normalizeEnd = experimentalWorkflowSource.indexOf("function factorComplexity", normalizeStart);
  const normalizeSource = experimentalWorkflowSource.slice(normalizeStart, normalizeEnd);
  assert.match(normalizeSource, /return factors\.slice\(0, 5\)\.map/);
  assert.doesNotMatch(normalizeSource, /Pricing Strategy|Contact Channel/);

  const levelsStart = experimentalWorkflowSource.indexOf("function levelsFactors");
  const levelsEnd = experimentalWorkflowSource.indexOf("function LevelsDesignBuilder", levelsStart);
  const levelsSource = experimentalWorkflowSource.slice(levelsStart, levelsEnd);
  assert.match(levelsSource, /return sharedParseFactorHierarchy\(state\.objective\)/);
  assert.doesNotMatch(levelsSource, /sharedDeriveSuggestedFactors/);
  assert.doesNotMatch(levelsSource, /Current Pricing|Personalized Pricing|Email|SMS/);
});

test("incomplete experimental designs never publish default study results", () => {
  const analysis = design.buildExperimentalDesignAnalysis({
    stepLabel: "Factors",
    currentState: { numeric: { factorCount: 3, averageLevels: 2, sampleSize: 1000, power: 80 } },
    nodeStates: {},
  });
  assert.equal(analysis.kpis.find((kpi) => kpi.label === "Factors")?.value, "TBD");
  assert.equal(analysis.kpis.find((kpi) => kpi.label === "Treatment Cells")?.value, "TBD");
  assert.equal(analysis.kpis.find((kpi) => kpi.label === "Total Sample")?.value, "TBD");
  assert.equal(analysis.kpis.find((kpi) => kpi.label === "Power")?.value, "TBD");
  assert.match(analysis.warnings.join(" "), /Confirmed factors and levels are required/);

  const levelsOnly = design.buildExperimentalDesignAnalysis({
    stepLabel: "Levels",
    currentState: { objective: twoByTwoText },
    nodeStates: { Levels: { objective: twoByTwoText } },
  });
  assert.equal(levelsOnly.kpis.find((kpi) => kpi.label === "Treatment Cells")?.value, "4");
  assert.equal(levelsOnly.kpis.find((kpi) => kpi.label === "Sample Per Cell")?.value, "TBD");
  assert.equal(levelsOnly.kpis.find((kpi) => kpi.label === "Power")?.value, "TBD");
});

test("downstream experimental tools block on missing confirmed levels", () => {
  assert.match(experimentalWorkflowSource, /Randomization requires a confirmed treatment matrix/);
  assert.match(experimentalWorkflowSource, /Power planning requires confirmed factors and levels/);
  assert.match(experimentalWorkflowSource, /Monte Carlo simulation requires a confirmed design/);
  assert.match(experimentalWorkflowSource, /ANOVA specification requires confirmed factors and levels/);

  const anovaStart = experimentalWorkflowSource.indexOf("function generatedAnovaPlan");
  const anovaEnd = experimentalWorkflowSource.indexOf("function journeyForLabel", anovaStart);
  const anovaSource = experimentalWorkflowSource.slice(anovaStart, anovaEnd);
  assert.match(anovaSource, /Response ~ \[confirm factors and levels first\]/);
  assert.doesNotMatch(anovaSource, /factorName: String\.fromCharCode/);
  assert.doesNotMatch(anovaSource, /Level \$\{levelIndex \+ 1\}/);

  const guideStart = copilotSource.indexOf("function buildFactorGuideSummary");
  const guideEnd = copilotSource.indexOf("export default function CopilotCard", guideStart);
  const guideSource = copilotSource.slice(guideStart, guideEnd);
  assert.match(guideSource, /value: "TBD"/);
  assert.doesNotMatch(guideSource, /Pricing Strategy|Contact Channel/);
});
