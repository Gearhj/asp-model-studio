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
const experimentalWorkflowSource = await readFile(new URL("../src/features/experimental-design/pages/ExperimentalDesignWorkflowPage.tsx", import.meta.url), "utf8");
const experimentalApiSource = await readFile(new URL("../src/lib/experimentalDesignApi.ts", import.meta.url), "utf8");
const experimentalVisualsSource = await readFile(new URL("../src/features/experimental-design/components/ExperimentalDesignVisuals.tsx", import.meta.url), "utf8");
const experimentalBackendSource = await readFile(new URL("../server/experimental_design/service.py", import.meta.url), "utf8");
const experimentalRouterSource = await readFile(new URL("../server/experimental_design/router.py", import.meta.url), "utf8");

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
  assert.equal(workflow.steps.find((step) => step.label === "Simulation & Operating Characteristics")?.route, "/workflow/experimental-design/9");
  assert.equal(workflow.steps[4].label, "Design Selection");
  assert.equal(workflow.steps[5].label, "Power & Sample Size");
  assert.equal(workflow.steps[6].label, "Design Matrix & Alias Review");
  assert.equal(workflow.steps[7].label, "Randomization & Run Plan");
  assert.equal(workflow.steps[9].label, "Execution & Analysis");
  assert.equal(workflow.steps[10].label, "Optimization & Recommendation");
  assert.equal(workflow.steps[11].label, "Documentation & Evidence");
  assert.equal(workflow.steps[11].route, "/workflow/experimental-design/12");
  assert.equal(workflow.steps[12], undefined);
  assert.match(workflowSource, /nextQuestion: "What exact runs and effects does the design support\?"/);
});

test("active route uses a dedicated backend-authoritative workspace", () => {
  assert.match(experimentalWorkflowSource, /if \(workflowId === "experimental-design"\) return <ExperimentalDesignWorkspace \/>/);
  assert.match(experimentalWorkflowSource, /getExperimentalStudy\(projectId\)/);
  assert.match(experimentalWorkflowSource, /saveExperimentalStudy\(projectId, contract/);
  assert.match(experimentalWorkflowSource, /Study v\{study\.currentVersion\}/);
  assert.match(experimentalWorkflowSource, /Backend current/);
  assert.doesNotMatch(experimentalWorkflowSource, /localStorage|sessionStorage/);
  assert.match(experimentalApiSource, /credentials: "same-origin"/);
});

test("workflow exposes compact identity, blockers, and a permanently available progression action", () => {
  for (const expected of [
    "Experimental Design",
    "Step {activeStepNumber} of 12",
    "Open blockers",
    "Contract blockers through this step",
    "What this page changes",
    "Version history",
    "Save draft",
    "Save & continue",
    "Save final study",
  ]) {
    assert.match(experimentalWorkflowSource, new RegExp(expected.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")), `Missing Experimental Design data-strategy artifact: ${expected}`);
  }
  assert.match(experimentalWorkflowSource, /fixed inset-x-0 bottom-0/);
  assert.match(experimentalWorkflowSource, /setWorkflowStepStatus\(journeyStep\.id, "complete"\)/);
});

test("design choice is advisory and requires attributable analyst confirmation", () => {
  assert.match(experimentalWorkflowSource, /ATLAS narrows the eligible choices but never selects a design on the analyst’s behalf/);
  assert.match(experimentalWorkflowSource, /analystConfirmed: false/);
  assert.match(experimentalWorkflowSource, /I confirm this design family and its stated estimability tradeoffs/);
  assert.match(experimentalBackendSource, /analystDecisionRequired/);
  assert.match(experimentalBackendSource, /experimental_design_family_selection/);
  assert.match(experimentalBackendSource, /design_confirmation_required/);
});

test("analytical operations are backend-generated, version-bound, and invalidated downstream", () => {
  for (const expected of [
    "calculateExperimentalPower",
    "generateExperimentalDesign",
    "randomizeExperimentalDesign",
    "createExperimentalSimulation",
    "analyzeExperimentalObservations",
    "captureExperimentalDocumentation",
  ]) assert.match(experimentalWorkflowSource, new RegExp(expected));
  assert.match(experimentalBackendSource, /contract_hash/);
  assert.match(experimentalBackendSource, /designVersion/);
  assert.match(experimentalBackendSource, /invalidatedArtifacts/);
  assert.match(experimentalBackendSource, /MAX_DESIGN_RUNS = 1024/);
  assert.match(experimentalBackendSource, /MAX_SIMULATION_ITERATIONS = 20_000/);
  assert.match(experimentalBackendSource, /interrupt_active_jobs/);
});

test("simulation and analysis never confuse planned, simulated, and observed evidence", () => {
  assert.match(experimentalWorkflowSource, /SYNTHETIC TEST INPUT — not operational experiment evidence/);
  assert.match(experimentalWorkflowSource, /ATLAS will not infer observed results from simulations/);
  assert.match(experimentalWorkflowSource, /No observed analysis exists\. ATLAS will not fabricate/);
  assert.match(experimentalBackendSource, /scope": "simulated_operating_characteristics"/);
  assert.match(experimentalBackendSource, /status": "observed_analysis"/);
  assert.match(experimentalBackendSource, /At least four finite observed responses/);
});

test("D3 visuals have semantic table counterparts and accessible SVG labels", () => {
  assert.match(experimentalVisualsSource, /import \* as d3 from "d3"/);
  for (const visual of ["FactorStructureMap", "PowerCurveChart", "DesignMatrixChart", "AliasMap", "EffectParetoChart", "ResidualPlot"]) {
    assert.match(experimentalVisualsSource, new RegExp(`function ${visual}`));
  }
  assert.match(experimentalVisualsSource, /role="img"/);
  assert.match(experimentalVisualsSource, /useReducedMotion/);
  assert.match(experimentalWorkflowSource, /function ExactTable/);
  assert.match(experimentalWorkflowSource, /Semantic design matrix/);
  assert.match(experimentalWorkflowSource, /Exact randomized execution order/);
  assert.match(experimentalWorkflowSource, /ANOVA table/);
  assert.match(experimentalWorkflowSource, /Exact power sensitivity results/);
  assert.match(experimentalWorkflowSource, /type="search"/);
  assert.match(experimentalWorkflowSource, /aria-sort=/);
  assert.match(experimentalWorkflowSource, /Export CSV/);
  assert.match(experimentalWorkflowSource, /URL\.createObjectURL/);
});

test("every Experimental Design endpoint requires authenticated project scope authorization", () => {
  const endpointCount = (experimentalRouterSource.match(/@router\./g) || []).length;
  const authorizationCount = (experimentalRouterSource.match(/authorize_modeling_scope/g) || []).length - 1;
  assert.equal(endpointCount, 12);
  assert.equal(authorizationCount, endpointCount);
  assert.match(experimentalRouterSource, /Depends\(require_user\)/);
  assert.doesNotMatch(experimentalRouterSource, /anonymous|allow_missing/);
});
