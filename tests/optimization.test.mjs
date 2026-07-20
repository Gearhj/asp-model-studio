import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const workflows = await readFile(new URL("../src/config/workflows.ts", import.meta.url), "utf8");
const templateRegistry = await readFile(new URL("../src/config/optimizationTemplates.ts", import.meta.url), "utf8");
const component = await readFile(new URL("../src/features/optimization/OptimizationWorkflowStep.tsx", import.meta.url), "utf8");
const transportation = await readFile(new URL("../src/features/optimization/TransportationOptimizationWorkflow.tsx", import.meta.url), "utf8");
const visuals = await readFile(new URL("../src/features/optimization/TransportationVisuals.tsx", import.meta.url), "utf8");
const copilot = await readFile(new URL("../src/components/CopilotCard.tsx", import.meta.url), "utf8");
const api = await readFile(new URL("../src/lib/optimizationWorkflow.ts", import.meta.url), "utf8");
const dispatcher = await readFile(new URL("../src/steps/WorkflowPlaceholderStep.tsx", import.meta.url), "utf8");
const backend = await readFile(new URL("../server/optimization/optimization_service.py", import.meta.url), "utf8");
const transportationBackend = await readFile(new URL("../server/optimization/transportation_template_service.py", import.meta.url), "utf8");
const inputBundleBackend = await readFile(new URL("../server/optimization/input_bundle_service.py", import.meta.url), "utf8");
const transportationSolver = await readFile(new URL("../server/optimization/solver_service.py", import.meta.url), "utf8");
const router = await readFile(new URL("../server/optimization/optimization_router.py", import.meta.url), "utf8");
const documentation = await readFile(new URL("../server/model_documentation/documentation_store.py", import.meta.url), "utf8");
const evidenceTypes = await readFile(new URL("../server/evidence/evidence_types.py", import.meta.url), "utf8");
const overview = await readFile(new URL("../src/steps/ProjectOverview.tsx", import.meta.url), "utf8");
const evidenceModel = await readFile(new URL("../src/lib/transportationOptimizationEvidence.ts", import.meta.url), "utf8");
const persistedEvidenceStatus = await readFile(new URL("../src/lib/persistedEvidenceStatus.ts", import.meta.url), "utf8");
const evidenceCenter = await readFile(new URL("../src/steps/EvidenceGraph.tsx", import.meta.url), "utf8");
const evidenceStore = await readFile(new URL("../server/evidence/evidence_store.py", import.meta.url), "utf8");
const codegen = await readFile(new URL("../server/optimization/codegen_service.py", import.meta.url), "utf8");
const sidebar = await readFile(new URL("../src/components/Sidebar.tsx", import.meta.url), "utf8");
const demoBanner = await readFile(new URL("../src/components/PrivateDemoBanner.tsx", import.meta.url), "utf8");
const testerGuide = await readFile(new URL("../PRIVATE_TESTER_GUIDE.md", import.meta.url), "utf8");
const viteConfig = await readFile(new URL("../vite.config.ts", import.meta.url), "utf8");

const expectedSteps = [
  "Project Context",
  "Data Acquisition",
  "Formulation Readiness",
  "Objective Function",
  "Decision Variables",
  "Constraints & Business Rules",
  "Solver Configuration",
  "Baseline & Scenarios",
  "Optimize",
  "Sensitivity & Tradeoffs",
  "Validation",
  "Decision Recommendation",
  "Implementation & Monitoring",
  "Documentation",
];

test("Optimization is an official ordered 14-stage workflow", () => {
  const optimizationStart = workflows.indexOf('id: "optimization"');
  assert.ok(optimizationStart >= 0);
  let previous = optimizationStart;
  for (const label of expectedSteps) {
    const index = workflows.indexOf(`["${label}"`, optimizationStart);
    assert.ok(index > previous, `${label} is missing or out of order`);
    previous = index;
  }
  assert.match(dispatcher, /<OptimizationWorkflowStep/);
});

test("Optimization supports governed data acquisition and full-artifact profiling", () => {
  assert.match(component, /Select governed dataset/);
  assert.match(component, /Upload/);
  assert.match(component, /Profile full dataset & materialize variables/);
  assert.match(component, /Browser preview rows are never treated as optimization evidence/);
  assert.match(api, /\/optimization\/profile/);
  assert.match(backend, /data_full\.csv/);
  assert.match(backend, /fullArtifact/);
});

test("Optimization template registry defines generic, transportation, and manual contracts", () => {
  for (const templateId of ["generic_single_table", "transportation_logistics", "manual_formulation"]) {
    assert.match(templateRegistry, new RegExp(`${templateId}: \\{`));
    assert.match(templateRegistry, new RegExp(`template_id: "${templateId}"`));
  }
  for (const field of [
    "display_name",
    "short_description",
    "applicable_use_cases",
    "required_input_roles",
    "optional_input_roles",
    "expected_decision_grain",
    "default_objective_direction",
    "default_solver",
    "generated_variable_type",
    "generated_constraint_groups",
    "scenario_controls",
    "chart_outputs",
    "evidence_types",
  ]) assert.match(templateRegistry, new RegExp(field));
  assert.match(templateRegistry, /required_input_roles: \["candidate_decision_table"\]/);
  assert.match(templateRegistry, /optional_input_roles: \["constraint_table", "baseline_table", "scenario_table"\]/);
  assert.match(templateRegistry, /required_input_roles: \[\]/);
  assert.match(templateRegistry, /optional_input_roles: \["approved_coefficients", "approved_constraints"\]/);
});

test("Data Acquisition renders inputs from selected template metadata", () => {
  assert.match(component, /Object\.values\(OPTIMIZATION_TEMPLATE_REGISTRY\)/);
  assert.match(component, /getOptimizationTemplateInputRoles\(strategy\)/);
  assert.match(component, /inputRoles\.map/);
  assert.match(component, /role\.accepted_shapes\.map/);
  assert.match(component, /role\.evidence_role/);
  assert.match(component, /TransportationOptimizationWorkflow/);
  assert.match(transportation, /getOptimizationTemplateInputRoles\(TRANSPORTATION_TEMPLATE\.template_id\)/);
  assert.match(transportation, /TRANSPORTATION_ROLE_CONFIG\.map/);
  assert.match(transportation, /browser previews are not used to formulate, solve, stress, validate, or evidence/);
  assert.match(transportationBackend, /Transportation input bundle is incomplete/);
});

test("Transportation template requires four inputs and treats inventory as optional", () => {
  assert.match(templateRegistry, /required_input_roles: \["route_costs", "demand", "supply_maximum", "transport_capacity"\]/);
  assert.match(templateRegistry, /optional_input_roles: \["inventory_or_handling_cost"\]/);
  assert.match(inputBundleBackend, /TRANSPORTATION_REQUIRED_INPUT_ROLES = \([\s\S]*"transportCapacity"/);
  assert.doesNotMatch(inputBundleBackend.match(/TRANSPORTATION_REQUIRED_INPUT_ROLES = \([\s\S]*?\n\)/)?.[0] ?? "", /inventoryCost/);
  assert.match(inputBundleBackend, /TRANSPORTATION_OPTIONAL_INPUT_ROLES = \([\s\S]*"inventoryCost"/);
  assert.match(transportation, /of \{REQUIRED_TRANSPORTATION_ROLES\.length\} required inputs assigned/);
  assert.match(transportation, /of \{OPTIONAL_TRANSPORTATION_ROLES\.length\} optional inputs assigned/);
  assert.match(transportation, /Inventory or handling cost was not supplied\. The objective will use route transportation cost only\./);
  assert.match(transportationBackend, /inventory_cost": \(inventory_lookup\.get\(key\) or \{\}\)\.get\("value"\) if inventory_supplied else 0\.0/);
  assert.match(visuals, /required inputs assigned/);
  assert.match(visuals, /optional inputs assigned/);
});

test("Route costs advertise and normalize wide and long shapes", () => {
  assert.match(templateRegistry, /Wide matrix: customers as rows, suppliers as columns/);
  assert.match(templateRegistry, /Long route table: supplier, customer, route_cost/);
  assert.match(transportationBackend, /long_route_format/);
  assert.match(transportationBackend, /route_cost_lookup/);
  assert.match(transportationBackend, /costShape/);
});

test("Template changes invalidate stale analytical state and migrate legacy template IDs", () => {
  assert.match(templateRegistry, /generic: "generic_single_table"/);
  assert.match(templateRegistry, /transportation: "transportation_logistics"/);
  assert.match(templateRegistry, /manual: "manual_formulation"/);
  assert.match(templateRegistry, /readStoredOptimizationTemplateId/);
  assert.match(templateRegistry, /LEGACY_OPTIMIZATION_TEMPLATE_STORAGE_PREFIX/);
  assert.match(component, /invalidateGenericOptimizationState\(props\.projectId, next\)/);
  assert.match(component, /invalidateTransportationOptimizationState\(props\.projectId, next\)/);
  assert.match(component, /<GenericOptimizationWorkflowStep key=\{strategy\}/);
  assert.match(component, /index === 0 \? "complete" : index === 1 \? "in_progress" : "pending"/);
  assert.match(component, /const reset = initialState\(\)/);
  assert.match(transportation, /export function invalidateTransportationOptimizationState/);
  for (const staleField of ["formulation", "result", "scenarioAnalysis", "sensitivity", "validation", "recommendation", "implementationOwner", "code", "evidenceByStep"]) {
    assert.match(transportation, new RegExp(`${staleField}:`));
  }
});

test("Atlas Guide identifies Optimization without a regression target", () => {
  assert.match(copilot, /const isOptimization = workflowState\.projectType === "optimization"/);
  assert.match(copilot, /problemType: isOptimization \? null/);
  assert.match(copilot, /<OptimizationGuideContext context=\{context\}/);
  assert.match(copilot, /label="Task" value=\{template\.guide_context\.task\}/);
  assert.match(copilot, /label="Target" value=\{template\.guide_context\.target\}/);
  assert.match(templateRegistry, /task: "Transportation \/ logistics optimization"/);
  assert.match(templateRegistry, /target: "Not applicable"/);
  assert.match(templateRegistry, /objective: "Minimize total logistics cost"/);
  assert.match(templateRegistry, /solver: "Linear programming"/);
});

test("Transportation formulation is route-level and generates governed business constraints", () => {
  for (const phrase of [
    "continuous shipment decisions",
    "Objective coefficient preview",
    "Customer demand fulfillment",
    "Supplier supply maximum",
    "Transport capacity",
    "Route-level decision vector",
  ]) assert.match(transportation, new RegExp(phrase));
  assert.match(transportation, /Source tables/);
  assert.match(transportation, /Approve all generated rules/);
  assert.match(transportation, /Review and approve every generated demand/);
  assert.match(transportationBackend, /variable_name/);
  assert.match(transportationBackend, /constraintType.*demand/);
  assert.match(transportationBackend, /constraintType.*supply/);
  assert.match(transportationBackend, /constraintType.*transport_capacity/);
});

test("Transportation execution exposes real solve, scenario, sensitivity, and validity evidence", () => {
  for (const path of ["formulate", "solve", "scenarios", "sensitivity", "validate", "code", "evidence"]) {
    assert.match(router, new RegExp(`/optimization/transportation/${path}`));
    assert.match(api, new RegExp(`/optimization/transportation/${path}`));
  }
  assert.match(transportationSolver, /linprog/);
  assert.match(transportationSolver, /zero-allocation solution/);
  assert.match(transportationSolver, /businessValidityStatus/);
  for (const visual of ["RouteMatrixChart", "SupplierUtilizationChart", "CustomerFulfillmentChart", "ScenarioComparisonChart", "SensitivityTornadoChart"]) {
    assert.match(visuals, new RegExp(`function ${visual}|export function ${visual}`));
  }
});

test("Optimization evidence, documentation, and management reporting are first-class", () => {
  assert.match(evidenceTypes, /optimization_decision_charter/);
  assert.match(evidenceTypes, /optimization_reproducibility_code/);
  assert.match(documentation, /optimization_decision_report/);
  assert.match(documentation, /SAS-Compatible Code/);
  assert.match(overview, /Transportation Optimization Management Summary/);
  assert.match(overview, /Business Validity/);
  assert.match(overview, /Scenario Coverage/);
});

test("Optimization exposes executable formulation, scenario, sensitivity, validation, and outcome evidence", () => {
  for (const phrase of [
    "Decision variable contract",
    "Constraints and non-negotiable business rules",
    "Run optimization",
    "Run scenarios",
    "Run sensitivity analysis",
    "Validation controls",
    "Decision recommendation",
    "Implementation and monitoring plan",
    "Export governed JSON",
  ]) assert.match(component, new RegExp(phrase));
  assert.match(api, /\/optimization\/solve/);
  assert.match(backend, /linprog/);
  assert.match(backend, /milp/);
  assert.match(backend, /method="SLSQP"/);
  assert.match(backend, /bindingConstraintCount/);
  assert.match(backend, /optimalityGap/);
});

test("Optimization progression is blocked until analytical evidence exists", () => {
  assert.match(component, /A full-artifact profile is required/);
  assert.match(component, /Run the solver and obtain a feasible optimal result/);
  assert.match(component, /Run coefficient sensitivity analysis/);
  assert.match(component, /Evidence at least five validation controls/);
  assert.match(component, /Define implementation ownership, monitoring, re-optimization, and fallback controls/);
});

test("Modeling-mode API proxy targets the FastAPI service that owns optimization routes", () => {
  assert.match(viteConfig, /VITE_API_PROXY_TARGET\s*\|\|\s*"http:\/\/127\.0\.0\.1:8001"/);
  assert.match(api, /DATASET_API_BASE/);
  assert.match(api, /\/optimization\/solve/);
});

test("Final approval date commits through native date input events", () => {
  assert.match(component, /onInput=\{type === "date"/);
  assert.match(component, /Record the final reviewer and approval date/);
});

test("Transportation navigation and lifecycle layout remain explicit", () => {
  assert.match(transportation, /nextPath=\{nextStep\?\.route \?\? "\/project-overview"\}/);
  assert.match(visuals, /gridTemplateColumns: `repeat\(\$\{TRANSPORTATION_STAGE_LABELS\.length\}, minmax\(70px, 1fr\)\)`/);
  assert.doesNotMatch(visuals, /grid-cols-14/);
});

test("Optimization Guide branches to page-aware transportation guidance before generic project-context advice", () => {
  const branch = copilot.indexOf('context.projectType === "optimization"');
  const staleGenericAdvice = copilot.indexOf('title: "Complete the project context first"');
  assert.ok(branch >= 0 && branch < staleGenericAdvice);
  assert.match(copilot, /function buildOptimizationRecommendations/);
  for (const page of expectedSteps) assert.match(copilot, new RegExp(`"${page.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}"`));
  assert.match(copilot, /Transportation \/ Logistics/);
  assert.match(copilot, /Stage state/);
  assert.match(copilot, /Routes/);
});

test("Transportation final polish preserves the governed input and formulation gates", () => {
  const polishSource = `${transportation}\n${visuals}`;
  for (const copy of [
    "Upload all input files",
    "Upload only this input role",
    "Required inputs complete",
    "Optional inputs complete",
    "Ready to normalize",
    "Evidence captured",
    "Mapping confidence",
    "Normalization summary",
    "Confirm and Continue to Objective Function",
    "I confirm the normalized transportation input bundle",
    "Generated constraints were sourced from the demand, supply maximum, and transport capacity input tables and approved before solve.",
  ]) assert.match(polishSource, new RegExp(copy.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
  assert.match(transportation, /exclusion rationale/i);
  assert.match(transportation, /Executable rules validated/);
  assert.match(visuals, /Darker blue = higher total unit cost/);
  assert.match(visuals, /Lighter blue = lower total unit cost/);
  assert.match(visuals, /Route inspection/);
});

test("Objective, solver, scenario, optimize, and sensitivity pages explain real analytical outputs", () => {
  for (const copy of [
    "Minimize total cash distribution cost",
    "ATLAS interpretation:",
    "Advanced formulation inspector: objective vector, constraints, bounds, and solver payload (optional)",
    "Variable index",
    "Equality RHS",
    "Inequality RHS",
    "Demand %",
    "Transport Capacity %",
    "Evidence blocked: infeasible scenario",
    "Solver interpretation",
    "Reduced cost:",
    "Shadow price:",
    "What moves logistics cost",
    "Supplier supply sensitivity:",
  ]) assert.match(transportation, new RegExp(copy.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
  assert.match(visuals, /Total logistics cost by scenario/);
  assert.match(visuals, /Change in total logistics cost/);
  assert.match(visuals, /Orange = cost increase/);
  assert.match(visuals, /Green = cost decrease/);
});

test("Validation, recommendation, implementation, and documentation use explicit governed completion logic", () => {
  const governedSource = `${transportation}\n${evidenceModel}`;
  for (const copy of [
    "Confirmed by the model developer, documentation owner, or evidence package owner",
    "Confirmed by the accountable operations owner or implementation owner",
    "Confirmed by a reviewer independent of development",
    "Mathematical success can pass while governance acceptance remains pending.",
    "Recommendation: Approve optimized allocation for operational implementation",
    "Rejected",
    "Select a non-draft recommendation status and enter a recommendation owner.",
    "Generate implementation plan",
    "Demand variance",
    "Override rate",
    "Export Python Reproducibility Code",
    "Final Optimization Study Package",
    "Capture Reproducibility Evidence",
    "Generate Optimization Report",
    "Complete | Audit package ready | Documentation finalized",
  ]) assert.match(governedSource, new RegExp(copy.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
  assert.match(transportation, /logDecision\(/);
  assert.match(transportation, /createEvidence\(/);
  assert.match(transportation, /Enter final reviewer\./);
  assert.match(transportation, /Enter approval date\./);
  assert.match(transportation, /Recommendation remains Draft\./);
  assert.match(transportation, /Implementation plan is incomplete\./);
  assert.match(transportation, /Evidence package is incomplete\./);
});

test("Optimization evidence readiness is one strict shared contract", () => {
  for (const surface of [overview, transportation, sidebar, copilot]) {
    assert.match(surface, /deriveOptimizationEvidenceSummary|optimizationWorkflowStepStatus|TRANSPORTATION_EVIDENCE_STAGES/);
  }
  assert.match(evidenceModel, /const allGenerated = records\.every/);
  assert.match(evidenceModel, /const allCaptured = records\.every/);
  assert.match(evidenceModel, /allGenerated && allCaptured/);
  assert.match(evidenceModel, /summarizeOptimizationEvidenceRecords/);
  assert.match(persistedEvidenceStatus, /generated: 0\.25/);
  assert.match(persistedEvidenceStatus, /captured: 0\.5/);
  assert.match(persistedEvidenceStatus, /ready: 0\.75/);
  assert.match(persistedEvidenceStatus, /approved: 1/);
  assert.match(persistedEvidenceStatus, /No governed evidence recorded/);
  assert.match(evidenceModel, /Evidence package ready/);
  assert.match(overview, /Open Evidence Package|actionLabel/);
  assert.match(overview, /Capture Remaining Evidence|actionLabel/);
});

test("Optimization evidence package capture is serialized for file-backed registry consistency", () => {
  assert.match(transportation, /for \(const definition of definitions\)/);
  assert.doesNotMatch(transportation, /Promise\.all\(definitions\.map/);
});

test("Optimization Project Overview exposes the full dynamic management summary", () => {
  for (const label of [
    "Project ID", "Project Name", "Template", "Solver", "Objective", "Total Cost", "Demand Fulfilled",
    "Unmet Demand", "Active Routes", "Route Variables", "Demand Constraints", "Supply Constraints",
    "Transport Capacity Constraints", "Scenario Coverage", "Infeasible Stress Case", "Validation Score",
    "Recommendation", "Implementation", "Evidence Package", "Documentation", "Business Validity",
  ]) assert.match(overview, new RegExp(label));
  assert.match(overview, /value=\{projectId\}/);
  assert.match(overview, /optimizationSummary\?\.result\?\.totalCost/);
  assert.match(overview, /optimizationSummary\?\.scenarioAnalysis/);
});

test("Optimization exports are governed, downloadable, and content-complete", () => {
  for (const action of ["Export Governed JSON", "Export Allocation CSV", "Export Python Code", "Export SAS-Compatible Code", "Generate Optimization Report", "Capture Reproducibility Evidence"]) {
    assert.match(transportation, new RegExp(action));
  }
  for (const field of ["supplier", "customer", "variable_name", "quantity", "transport_cost", "inventory_cost", "total_unit_cost", "cost_contribution", "status", "reduced_cost"]) {
    assert.match(transportation, new RegExp(field));
  }
  for (const key of ["projectMetadata", "inputBundle", "detectedMapping", "normalizationHash", "variableDefinitions", "constraintGroups", "decisionVector", "scenarios", "sensitivity", "validation", "recommendation", "implementationPlan", "monitoringPlan", "documentation", "evidence", "timestamps"]) {
    assert.match(transportation, new RegExp(key));
  }
  assert.match(transportation, /recordExport\(/);
  assert.match(transportation, /downloadFile\(fileName, content, mimeType\)/);
  assert.match(transportation, /generated and recorded as evidence/);
  assert.match(transportation, /exportArtifacts/);
});

test("Optimization report exposes all 20 inspectable audit sections", () => {
  const sections = [
    "Executive Summary", "Business Decision", "Data Inputs", "Formulation Readiness", "Objective Function",
    "Decision Variables", "Constraints", "Solver Configuration", "Baseline and Scenarios", "Optimization Results",
    "Sensitivity and Tradeoffs", "Validation", "Recommendation", "Implementation Plan", "Monitoring Plan",
    "Limitations", "Approvals", "Reproducibility Appendix", "Python Code", "SAS-Compatible Code",
  ];
  sections.forEach((section, index) => assert.match(transportation, new RegExp(`## ${index + 1}\\. ${section.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}`)));
  assert.match(transportation, /View Generated Report/);
  assert.match(transportation, /Preview Optimization Report/);
  assert.match(transportation, /Inspect all 20 sections before completing the study/);
});

test("Optimization Evidence Center shows audit metadata and exact artifact categories", () => {
  const expectedTypes = [
    "optimization_decision_charter", "optimization_input_bundle", "optimization_formulation_readiness",
    "optimization_objective", "optimization_decision_variables", "optimization_constraints",
    "optimization_solver_configuration", "optimization_scenarios", "optimization_solution",
    "optimization_sensitivity", "optimization_validation", "optimization_recommendation",
    "optimization_implementation_plan", "optimization_monitoring_plan", "optimization_documentation_package",
    "optimization_reproducibility_code",
  ];
  for (const type of expectedTypes) {
    assert.match(evidenceModel + evidenceTypes + evidenceStore, new RegExp(type));
  }
  for (const field of ["Artifact type", "Reference ID", "Workflow step", "Created", "Captured", "Source data / run"]) {
    assert.match(evidenceCenter, new RegExp(field));
  }
  assert.match(evidenceCenter, /Optimization Evidence/);
  assert.match(evidenceStore, /workflowType": "optimization"/);
});

test("Generated reproducibility code reconstructs the transportation study", () => {
  assert.match(transportation, /generateTransportationCode\(\{ \.\.\.requestInput, stage: "export" \}\)/);
  assert.match(transportation, /TRANSPORTATION_CODE_GENERATOR_VERSION/);
  for (const phrase of [
    "normalize_wide_route_costs", "load_governed_transportation_inputs", "total_unit_cost", "A_eq", "A_ub",
    "bounds", "linprog", "method=\"highs\"", "demand_fulfillment", "supplier_utilization",
    "shadow_price", "solve_variant", "scenarios", "sensitivity", "allocation.to_csv", "evidence",
  ]) assert.match(codegen, new RegExp(phrase));
  for (const phrase of ["PROC IMPORT", "PROC TRANSPOSE", "PROC SQL", "PROC OPTMODEL", "DemandFulfillment", "SupplyMaximum", "TransportCapacity", "PROC EXPORT", "template-only"]) {
    assert.match(codegen, new RegExp(phrase, "i"));
  }
  assert.doesNotMatch(codegen, /LogisticRegression|RandomForestClassifier|predict_proba/);
});

test("Workflow status legend and side navigation use the shared meanings", () => {
  for (const phrase of [
    "The user is viewing or working on this step.", "The step's required workflow state is complete.",
    "The step is complete and its governed evidence artifact is captured or ready.",
    "The step has not been completed.", "The step cannot continue because required upstream state is missing.",
  ]) assert.match(visuals, new RegExp(phrase.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
  assert.match(sidebar, /optimizationWorkflowStepStatus/);
  assert.match(overview, /optimizationWorkflowStepStatus/);
  assert.match(transportation, /workflowState\.workflowSteps/);
  assert.match(transportation, /workflowStep\.status === "complete"/);
  assert.doesNotMatch(transportation, /function transportationCompletedThrough/);
});

test("Completed legacy optimization studies restore confirmation markers from real downstream evidence", () => {
  assert.match(transportation, /downstreamAnalyticalProof/);
  assert.match(transportation, /parsed\.result\?\.success/);
  assert.match(transportation, /inferredConstraintApprovals/);
  assert.match(transportation, /formulationConfirmed: Boolean\(parsed\.formulationConfirmed/);
  assert.match(transportation, /executableRulesValidated: Boolean\(parsed\.executableRulesValidated/);
});

test("Recommendation, monitoring, and completion controls remain reviewable", () => {
  assert.match(transportation, /rows=\{9\} documentEditor/);
  assert.match(transportation, /rows=\{7\} documentEditor/);
  assert.match(transportation, /min-h-40/);
  for (const column of ["Metric", "Trigger threshold", "Owner", "Cadence", "Escalation action", "Status"]) assert.match(transportation, new RegExp(column));
  assert.match(evidenceModel, /DEFAULT_TRANSPORTATION_MONITORING_THRESHOLDS/);
  assert.match(evidenceModel, /Demand variance/);
  assert.match(evidenceModel, /Cost overrun/);
  assert.match(transportation, /Enter final reviewer\./);
  assert.match(transportation, /Enter approval date\./);
  assert.match(transportation, /Recommendation remains Draft\./);
});

test("Private tester mode warns about sensitive data and captures feedback", () => {
  assert.match(demoBanner, /Private ATLAS demo\. Use synthetic or non-sensitive data only\./);
  assert.match(demoBanner, /VITE_DEMO_MODE/);
  assert.match(demoBanner, /new URLSearchParams\(location\.search\)\.get\("demo"\) === "1"/);
  assert.match(demoBanner, /atlas-private-demo-feedback/);
  assert.match(demoBanner, /saveDemoFeedbackToDatabase/);
  assert.match(demoBanner, /Save Feedback/);
  assert.match(testerGuide, /Use synthetic or non-sensitive data only/);
  assert.match(testerGuide, /\?demo=1/);
});

test("Optimization visible copy does not introduce em dashes", () => {
  assert.doesNotMatch(transportation, /[—–]/);
  assert.doesNotMatch(visuals, /[—–]/);
});
