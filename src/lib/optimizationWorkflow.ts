import { DATASET_API_BASE } from "./datasetLibrary";

export type OptimizationVariable = {
  name: string;
  objectiveCoefficient: number;
  lowerBound: number;
  upperBound: number | null;
  integer: boolean;
  riskCoefficient: number;
  costCoefficient?: number;
  group: string;
};

export type OptimizationConstraint = {
  id: string;
  name: string;
  coefficients: Record<string, number>;
  sense: "<=" | ">=" | "=";
  rhs: number;
  category: "Capacity" | "Budget" | "Risk" | "Policy" | "Service" | "Regulatory" | "Other";
  hard: boolean;
};

export type OptimizationDatasetMapping = {
  itemColumn: string;
  objectiveColumn: string;
  lowerBoundColumn: string;
  upperBoundColumn: string;
  costColumn: string;
  riskColumn: string;
  groupColumn: string;
};

export type OptimizationProfile = {
  datasetId: string;
  versionId: string;
  datasetName: string;
  fullArtifact: boolean;
  rowCount: number;
  columnCount: number;
  columns: string[];
  resolvedMapping: Record<keyof OptimizationDatasetMapping, string | null>;
  validOptimizationRows: number;
  duplicateItems: number;
  numericSummary: Array<{
    column: string;
    validCount: number;
    missingCount: number;
    mean: number | null;
    minimum: number | null;
    maximum: number | null;
  }>;
  candidateVariables: OptimizationVariable[];
  warnings: string[];
};

export type OptimizationSolveResult = {
  success: boolean;
  solverSuccess: boolean;
  feasible: boolean;
  status: "optimal" | "review_required";
  solverStatus: number;
  message: string;
  method: string;
  direction: "Maximize" | "Minimize";
  objectiveValue: number;
  riskAdjustedObjective: number;
  baselineObjective: number;
  baselineGrossObjective: number;
  improvement: number;
  riskPenaltyCost: number;
  runtimeMs: number;
  iterations: number;
  optimalityGap: number | null;
  decisionCount: number;
  constraintCount: number;
  bindingConstraintCount: number;
  decisions: Array<{
    name: string;
    value: number;
    lowerBound: number;
    upperBound: number | null;
    objectiveContribution: number;
    riskContribution: number;
    integer: boolean;
    group: string;
  }>;
  constraints: Array<{
    name: string;
    sense: "<=" | ">=" | "=";
    lhs: number;
    rhs: number;
    slack: number;
    binding: boolean;
    feasible: boolean;
  }>;
};

export type TransportationBundleRole = "transportationCost" | "demand" | "supplyMax" | "transportCapacity" | "inventoryCost";

export type TransportationDatasetReference = {
  datasetId: string;
  versionId?: string;
};

export type TransportationInputBundle = Record<TransportationBundleRole, TransportationDatasetReference>;

export type TransportationTableProfile = {
  role: TransportationBundleRole;
  label: string;
  datasetId?: string;
  versionId?: string;
  datasetName?: string;
  fileName?: string;
  rowCount?: number;
  columnCount?: number;
  columns?: string[];
  fullArtifact: boolean;
  keyColumns: string[];
  valueColumns: string[];
  missingValues: number;
  duplicateKeys: number;
  invalidValues: number;
  schemaConfidence: number;
  profileStatus: "ready" | "review" | "blocked";
  evidenceStatus: "capturable" | "needs_review";
};

export type TransportationRoute = {
  route_id: string;
  supplier: string;
  customer: string;
  transportation_cost: number | null;
  demand: number | null;
  supply_max: number | null;
  transport_capacity: number | null;
  inventory_cost: number | null;
  total_unit_cost: number | null;
  lower_bound: number;
  upper_bound: number | null;
  variable_name: string;
  active: boolean;
  source_tables: string[];
};

export type TransportationFormulation = {
  template: "transportation_logistics";
  formulationId: string;
  formulationVersion: string;
  normalizationHash: string;
  fullArtifact: boolean;
  inputTables: TransportationTableProfile[];
  resolvedMapping: Record<string, string | string[]>;
  customers: Array<{ customer: string; demand: number }>;
  suppliers: Array<{ supplier: string; supply_max: number | null; transport_capacity: number | null; inventory_cost: number | null }>;
  routes: TransportationRoute[];
  variables: Array<OptimizationVariable & { supplier: string; customer: string; transportationCost: number; inventoryCost: number; totalUnitCost: number; active: boolean }>;
  constraints: Array<OptimizationConstraint & { constraintType: string; sourceTable: string; entity: string }>;
  inspector: {
    variableIndex: string[];
    objectiveVector: number[];
    lowerBounds: number[];
    upperBounds: Array<number | null>;
    equalityConstraintCount: number;
    inequalityConstraintCount: number;
    equalityConstraintNames: string[];
    inequalityConstraintNames: string[];
    equalityRhs: number[];
    inequalityRhs: number[];
    nonZeroEqualityCoefficients: number;
    nonZeroInequalityCoefficients: number;
  };
  objective: { direction: "Minimize"; name: string; unit: string; horizon: string; expression: string; plainEnglish: string };
  metrics: {
    customerCount: number;
    supplierCount: number;
    routeCount: number;
    decisionVariableCount: number;
    demandConstraintCount: number;
    supplyConstraintCount: number;
    transportConstraintCount: number;
    nonNegativityBoundCount: number;
    routeUpperBoundCount: number;
    totalDemand: number;
    totalSupplyMax: number;
    totalTransportCapacity: number;
    missingRouteCosts: number;
    negativeRouteCosts: number;
    duplicateRoutes: number;
    customersWithoutDemand: number;
    suppliersWithoutSupply: number;
    suppliersWithoutCapacity: number;
    suppliersWithoutInventoryCost: number;
    inventoryCostSupplied: boolean;
  };
  readinessChecks: Array<{ id: string; label: string; status: "pass" | "warning" | "fail"; detail: string }>;
  formulationReady: boolean;
  formulationStatus: string;
  warnings: string[];
};

export type TransportationDecisionRow = {
  variableName: string;
  supplier: string;
  customer: string;
  quantity: number;
  transportationCost: number;
  inventoryCost: number;
  totalUnitCost: number;
  costContribution: number;
  lowerBound: number;
  upperBound: number | null;
  reducedCost: number | null;
  status: "active" | "unused";
};

export type TransportationConstraintResult = {
  constraintId: string;
  constraintName: string;
  constraintType: "demand" | "supply" | "transport_capacity" | string;
  category: string;
  entity: string;
  lhs: number;
  sense: "<=" | ">=" | "=";
  rhs: number;
  slack: number;
  binding: boolean;
  feasible: boolean;
  shadowPrice: number | null;
  sourceTable: string;
};

export type TransportationSolveResult = {
  runId: string;
  solutionId: string | null;
  formulationId: string;
  solverStatus: string;
  solverStatusCode: number;
  solverMessage: string;
  solverFeasible: boolean;
  formulationValid: boolean;
  businessValidityStatus: "valid" | "invalid";
  decisionReadiness: "ready" | "blocked";
  success: boolean;
  objectiveValue: number | null;
  totalCost: number | null;
  demandFulfilled: number;
  totalDemand: number;
  unmetDemand: number;
  activeRoutes: number;
  totalRoutes: number;
  runtimeMs: number;
  iterations?: number;
  optimalityGap: number | null;
  decisionVector: TransportationDecisionRow[];
  allocationMatrix: Array<{ customer: string; allocations: Record<string, number> }>;
  constraintResults: TransportationConstraintResult[];
  demandConstraintResults: TransportationConstraintResult[];
  supplyConstraintResults: TransportationConstraintResult[];
  transportConstraintResults: TransportationConstraintResult[];
  bindingConstraints: TransportationConstraintResult[];
  shadowPrices: Array<{ constraintName: string; constraintType: string; shadowPrice: number | null; available: boolean }>;
  supplierUtilization: Array<{ supplier: string; used: number; supplyMax: number; transportCapacity: number; effectiveCapacity: number; supplyUtilization: number; transportUtilization: number; bindingLimit: string }>;
  customerFulfillment: Array<{ customer: string; demand: number; supplied: number; unmet: number; fulfillmentRate: number }>;
  costBreakdown: {
    bySupplier: Array<{ supplier: string; cost: number }>;
    byCustomer: Array<{ customer: string; cost: number }>;
    byRoute: TransportationDecisionRow[];
  };
  baseline: { totalCost: number; unmetDemand: number; quantities: Record<string, number> };
  improvementVersusBaseline: number | null;
  residualTransportCapacity: number;
  warnings: string[];
  errors: string[];
};

export type TransportationScenario = {
  id: string;
  name: string;
  demandMultiplier: number;
  supplyMultiplier: number;
  capacityMultiplier: number;
  routeCostMultiplier: number;
  inventoryCostMultiplier: number;
  note: string;
};

export type TransportationScenarioAnalysis = {
  available: boolean;
  message?: string;
  baseRunId?: string;
  baseResult?: TransportationSolveResult;
  results: Array<{
    scenarioId: string;
    scenarioName: string;
    note: string;
    parameters: Omit<TransportationScenario, "id" | "name" | "note">;
    solverStatus: string;
    businessValidityStatus: string;
    totalCost: number | null;
    costChangeVersusBase: number | null;
    costChangePercent: number | null;
    demandFulfilled: number;
    totalDemand: number;
    unmetDemand: number;
    activeRoutes: number;
    allocationTurnover: number;
    bindingConstraintCount: number;
    bindingConstraintChanges: string[];
    supplierUtilization: TransportationSolveResult["supplierUtilization"];
    feasible: boolean;
    businessValid: boolean;
    evidenceStatus: string;
    warnings: string[];
    errors: string[];
  }>;
  scenarioCount: number;
  validScenarioCount: number;
  infeasibleScenarioCount: number;
};

export type TransportationSensitivity = {
  available: boolean;
  baseRunId: string;
  baseTotalCost: number;
  perturbationPercent: number;
  rows: Array<{
    driver: string;
    direction: string;
    multiplier: number;
    baseTotalCost: number;
    perturbedTotalCost: number | null;
    costChange: number | null;
    costChangePercent: number | null;
    activeRouteChange: number;
    allocationTurnover: number;
    bindingConstraintChanges: string[];
    demandFulfilled: number;
    unmetDemand: number;
    feasible: boolean;
    businessValid: boolean;
  }>;
  tornado: TransportationSensitivity["rows"];
  shadowPrices: TransportationSolveResult["shadowPrices"];
  shadowPriceStatus: string;
  allocationTurnover: Array<{ driver: string; direction: string; turnover: number }>;
  demandStress: TransportationSensitivity["rows"];
  capacityStress: TransportationSensitivity["rows"];
  conclusion: string;
  fragileAreas: string[];
};

export type TransportationValidation = {
  checks: Array<{ id: string; label: string; passed: boolean; status: string; evidence: string; requiresConfirmation: boolean }>;
  score: number;
  passedCount: number;
  totalCount: number;
  mathematicalSuccess: boolean;
  governanceAcceptance: boolean;
  recommendationAllowed: boolean;
  status: string;
  blockers: string[];
  warnings: string[];
};

export type TransportationGeneratedCode = {
  generatorVersion?: string;
  stage: string;
  formulationId: string;
  python: { code: string; runtimeStatus: string; language: string };
  sas: { code: string; runtimeStatus: string; language: string };
  references: { normalizationHash: string; variableCount: number; constraintCount: number };
};

export const TRANSPORTATION_CODE_GENERATOR_VERSION = "transportation-codegen-v2";

export const DEFAULT_TRANSPORTATION_SCENARIOS: TransportationScenario[] = [
  { id: "base", name: "Base Case", demandMultiplier: 1, supplyMultiplier: 1, capacityMultiplier: 1, routeCostMultiplier: 1, inventoryCostMultiplier: 1, note: "Current confirmed planning assumptions." },
  { id: "demand-surge", name: "Demand Surge", demandMultiplier: 1.15, supplyMultiplier: 1, capacityMultiplier: 1, routeCostMultiplier: 1, inventoryCostMultiplier: 1, note: "Tests 15 percent higher demand with current capacity." },
  { id: "capacity-stress", name: "Capacity Stress", demandMultiplier: 1, supplyMultiplier: 0.9, capacityMultiplier: 0.85, routeCostMultiplier: 1, inventoryCostMultiplier: 1, note: "Tests reduced supply and transport throughput." },
  { id: "transport-cost-increase", name: "Transport Cost Increase", demandMultiplier: 1, supplyMultiplier: 1, capacityMultiplier: 1, routeCostMultiplier: 1.25, inventoryCostMultiplier: 1, note: "Tests a 25 percent increase in route costs." },
  { id: "severe-disruption", name: "Severe Disruption", demandMultiplier: 1.1, supplyMultiplier: 0.85, capacityMultiplier: 0.75, routeCostMultiplier: 1.3, inventoryCostMultiplier: 1.1, note: "Combined demand, capacity, and cost stress." },
];

async function optimizationFetch<T>(path: string, body: unknown): Promise<T> {
  const response = await fetch(`${DATASET_API_BASE}${path}`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const payload = await response.json().catch(() => null);
  if (!response.ok || payload?.ok === false) {
    throw new Error(payload?.detail ?? payload?.error ?? `Optimization request failed with HTTP ${response.status}.`);
  }
  return payload as T;
}

export async function profileOptimizationDataset(input: {
  datasetId: string;
  versionId?: string;
  mapping: OptimizationDatasetMapping;
}) {
  const payload = await optimizationFetch<{ ok: true; profile: OptimizationProfile }>("/optimization/profile", input);
  return payload.profile;
}

export async function solveOptimization(input: {
  direction: "Maximize" | "Minimize";
  method: "Linear programming (LP)" | "Mixed-integer programming (MILP)" | "Risk-adjusted nonlinear";
  variables: OptimizationVariable[];
  constraints: OptimizationConstraint[];
  tolerance: number;
  timeLimitSeconds: number;
  riskPenalty: number;
}) {
  const payload = await optimizationFetch<{ ok: true; result: OptimizationSolveResult }>("/optimization/solve", {
    ...input,
    constraints: input.constraints.map(({ id: _id, category: _category, hard: _hard, ...constraint }) => constraint),
  });
  return payload.result;
}

type TransportationRequestInput = {
  bundle: TransportationInputBundle;
  mapping?: Record<string, string>;
  routeOverrides?: Record<string, boolean>;
  customConstraints?: Array<{
    id: string;
    name: string;
    coefficients: Record<string, number>;
    sense: "<=" | ">=" | "=";
    rhs: number;
    category?: string;
  }>;
  solver?: { method?: string; tolerance?: number; timeLimitSeconds?: number };
};

export async function formulateTransportation(input: TransportationRequestInput) {
  return optimizationFetch<{ ok: true; formulation: TransportationFormulation; code: TransportationGeneratedCode }>("/optimization/transportation/formulate", input);
}

export async function solveTransportation(input: TransportationRequestInput) {
  return optimizationFetch<{ ok: true; formulation: TransportationFormulation; result: TransportationSolveResult }>("/optimization/transportation/solve", input);
}

export async function analyzeTransportationScenarios(input: TransportationRequestInput & { scenarios: TransportationScenario[] }) {
  return optimizationFetch<{ ok: true; formulation: TransportationFormulation; analysis: TransportationScenarioAnalysis }>("/optimization/transportation/scenarios", input);
}

export async function analyzeTransportationSensitivity(input: TransportationRequestInput & { perturbationPercent: number }) {
  return optimizationFetch<{ ok: true; formulation: TransportationFormulation; analysis: TransportationSensitivity }>("/optimization/transportation/sensitivity", input);
}

export async function validateTransportation(input: TransportationRequestInput & { confirmations: Record<string, boolean> }) {
  return optimizationFetch<{
    ok: true;
    formulation: TransportationFormulation;
    result: TransportationSolveResult;
    scenarios: TransportationScenarioAnalysis;
    sensitivity: TransportationSensitivity;
    validation: TransportationValidation;
  }>("/optimization/transportation/validate", input);
}

export async function generateTransportationCode(input: TransportationRequestInput & { stage: string }) {
  const payload = await optimizationFetch<{ ok: true; code: TransportationGeneratedCode }>("/optimization/transportation/code", input);
  return payload.code;
}

export async function prepareTransportationEvidence(input: TransportationRequestInput & {
  stage: string;
  projectId: string;
  user?: string;
  decisionNotes?: string;
  chartMetadata?: Array<Record<string, unknown>>;
}) {
  const payload = await optimizationFetch<{ ok: true; evidence: Record<string, unknown> }>("/optimization/transportation/evidence", input);
  return payload.evidence;
}

export function optimizationReadiness(input: {
  variables: OptimizationVariable[];
  constraints: OptimizationConstraint[];
  result?: OptimizationSolveResult | null;
  profile?: OptimizationProfile | null;
}) {
  const bounded = input.variables.filter((variable) => variable.upperBound !== null && variable.upperBound >= variable.lowerBound).length;
  const configured = input.variables.filter((variable) => variable.name.trim() && Number.isFinite(variable.objectiveCoefficient)).length;
  return {
    configuredVariables: configured,
    boundedVariables: bounded,
    constraintCount: input.constraints.length,
    hasFullData: Boolean(input.profile?.fullArtifact),
    solved: Boolean(input.result?.solverSuccess),
    feasible: Boolean(input.result?.feasible),
  };
}

export function formatOptimizationNumber(value: number | null | undefined, digits = 2) {
  if (value === null || value === undefined || !Number.isFinite(value)) return "Not available";
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: digits }).format(value);
}
