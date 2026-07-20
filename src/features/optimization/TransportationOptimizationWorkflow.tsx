import { useEffect, useMemo, useRef, useState, type ChangeEvent, type ReactNode } from "react";
import {
  AlertTriangle,
  Braces,
  CheckCircle2,
  ClipboardCheck,
  Code2,
  Database,
  Download,
  FileJson,
  FileSpreadsheet,
  FileText,
  Gauge,
  GitBranch,
  LoaderCircle,
  PackageCheck,
  Play,
  Plus,
  RefreshCw,
  Save,
  Scale,
  Settings2,
  ShieldCheck,
  Sparkles,
  Trash2,
  Upload,
} from "lucide-react";
import StepShell from "../../components/StepShell";
import { CodeWorkspacePanel } from "../../components/code/CodeWorkspacePanel";
import {
  AtlasAttentionPanel,
  AtlasDataScopeBadge,
  AtlasStatusStrip,
  AtlasWorkflowSection,
} from "../../components/ui/AtlasWorkflow";
import type { WorkflowStep } from "../../config/workflows";
import {
  OPTIMIZATION_TEMPLATE_REGISTRY,
  getOptimizationTemplateInputRoles,
  type OptimizationTemplateId,
} from "../../config/optimizationTemplates";
import { runUserPython, type CodeRunResult } from "../../lib/codeExecution";
import {
  getDatasetProfile,
  linkDatasetToProject,
  listDatasets,
  uploadDataset,
  type DatasetSummary,
} from "../../lib/datasetLibrary";
import { createEvidence, type EvidenceType } from "../../lib/evidenceGraph";
import { logDecision } from "../../lib/decisionJournal";
import { USER_STEP_PYTHON_CODE_KEY, USER_STEP_SAS_CODE_KEY } from "../../lib/notebookExport";
import {
  queueOptimizationStateDatabaseSave,
  saveDocumentationPackageToDatabase,
  saveEvidenceToDatabase,
  saveExportToDatabase,
  saveRunToDatabase,
} from "../../lib/serverPersistence";
import {
  DEFAULT_TRANSPORTATION_MONITORING_THRESHOLDS,
  TRANSPORTATION_EVIDENCE_STAGES,
  TRANSPORTATION_OPTIMIZATION_STORAGE_PREFIX,
  deriveOptimizationEvidenceSummary,
  optimizationDocumentationSectionCount,
  optimizationStageGenerated,
  type OptimizationExportKind,
  type OptimizationExportRecord,
  type OptimizationMonitoringThreshold,
  type OptimizationEvidenceStage,
} from "../../lib/transportationOptimizationEvidence";
import { useWorkflowStore } from "../../state/useWorkflowStore";
import {
  DEFAULT_TRANSPORTATION_SCENARIOS,
  analyzeTransportationScenarios,
  analyzeTransportationSensitivity,
  formulateTransportation,
  formatOptimizationNumber,
  generateTransportationCode,
  solveTransportation,
  TRANSPORTATION_CODE_GENERATOR_VERSION,
  validateTransportation,
  type TransportationBundleRole,
  type TransportationFormulation,
  type TransportationGeneratedCode,
  type TransportationInputBundle,
  type TransportationScenario,
  type TransportationScenarioAnalysis,
  type TransportationSensitivity,
  type TransportationSolveResult,
  type TransportationValidation,
} from "../../lib/optimizationWorkflow";
import {
  ConstraintReadinessChart,
  CostContributionChart,
  CustomerFulfillmentChart,
  DemandCapacityChart,
  InputBundleCompletenessChart,
  ObjectiveDistributionChart,
  ResultKpi,
  RouteMatrixChart,
  ScenarioComparisonChart,
  SensitivityTornadoChart,
  SupplierUtilizationChart,
  TransportationLifecycleMap,
  formatTransportationPercent,
  formatTransportationValue,
} from "./TransportationVisuals";

export type OptimizationInputStrategy = OptimizationTemplateId;

type Props = {
  projectId: string;
  step: WorkflowStep;
  nextStep?: WorkflowStep;
  onComplete: () => boolean;
  navigationError?: string | null;
  onStrategyChange: (strategy: OptimizationInputStrategy) => void;
};

type CustomConstraint = {
  id: string;
  name: string;
  formula: string;
  coefficients: Record<string, number>;
  sense: "<=" | ">=" | "=";
  rhs: number;
  category: string;
};

type TransportationState = {
  templateId: OptimizationTemplateId;
  decisionTitle: string;
  decisionOwner: string;
  businessObjective: string;
  population: string;
  decisionCadence: string;
  governanceBoundary: string;
  bundle: TransportationInputBundle;
  mapping: Record<string, string>;
  formulation: TransportationFormulation | null;
  formulationConfirmed: boolean;
  routeOverrides: Record<string, boolean>;
  routeExclusionRationales: Record<string, string>;
  customConstraints: CustomConstraint[];
  constraintApprovals: Record<string, boolean>;
  executableRulesValidated: boolean;
  objectiveName: string;
  objectiveUnit: string;
  horizon: string;
  baselineDescription: string;
  method: string;
  tolerance: number;
  timeLimitSeconds: number;
  scenarios: TransportationScenario[];
  scenarioAnalysis: TransportationScenarioAnalysis | null;
  result: TransportationSolveResult | null;
  perturbationPercent: number;
  sensitivity: TransportationSensitivity | null;
  validationConfirmations: Record<string, boolean>;
  validation: TransportationValidation | null;
  validationNotes: string;
  recommendation: string;
  recommendationOwner: string;
  recommendationStatus: "Draft" | "Recommended" | "Approved" | "Returned" | "Rejected";
  alternatives: string;
  residualRisks: string;
  implementationOwner: string;
  effectiveDate: string;
  operatingCadence: string;
  routeExceptionProcess: string;
  fallbackPlan: string;
  monitoringMetrics: string;
  monitoringCadence: string;
  monitoringThresholds: OptimizationMonitoringThreshold[];
  reoptimizationTrigger: string;
  reconciliationProcess: string;
  reviewer: string;
  approvalDate: string;
  code: TransportationGeneratedCode | null;
  userPythonByStep: Record<string, string>;
  userSasByStep: Record<string, string>;
  evidenceByStep: Record<string, string>;
  exportArtifacts: Partial<Record<OptimizationExportKind, OptimizationExportRecord>>;
  generatedReport: string;
  generatedReportAt: string;
  studyCompleted: boolean;
  completedAt: string;
  evidencePackageReference: string;
  savedAt: string;
};

type BusyAction = "datasets" | "upload" | "formulate" | "solve" | "scenarios" | "sensitivity" | "validation" | "code" | "evidence" | "export" | "report" | "";

const STORAGE_PREFIX = TRANSPORTATION_OPTIMIZATION_STORAGE_PREFIX;
const TRANSPORTATION_TEMPLATE = OPTIMIZATION_TEMPLATE_REGISTRY.transportation_logistics;
const TRANSPORTATION_ROLE_CONFIG = getOptimizationTemplateInputRoles(TRANSPORTATION_TEMPLATE.template_id)
  .filter((role) => Boolean(role.bundle_key))
  .map((role) => ({ ...role, bundle_key: role.bundle_key as TransportationBundleRole }));
const REQUIRED_TRANSPORTATION_ROLES = TRANSPORTATION_ROLE_CONFIG
  .filter((role) => role.requirement === "required")
  .map((role) => role.bundle_key);
const OPTIONAL_TRANSPORTATION_ROLES = TRANSPORTATION_ROLE_CONFIG
  .filter((role) => role.requirement === "optional")
  .map((role) => role.bundle_key);
const EMPTY_BUNDLE: TransportationInputBundle = {
  transportationCost: { datasetId: "", versionId: "" },
  demand: { datasetId: "", versionId: "" },
  supplyMax: { datasetId: "", versionId: "" },
  transportCapacity: { datasetId: "", versionId: "" },
  inventoryCost: { datasetId: "", versionId: "" },
};

const STEP_EVIDENCE_STAGE = [
  "decision_charter",
  "input_bundle",
  "formulation_readiness",
  "objective",
  "decision_variables",
  "constraints",
  "solver_configuration",
  "scenarios",
  "solution",
  "sensitivity",
  "validation",
  "recommendation",
  "implementation_plan",
  "code_reproducibility",
];

const DOCUMENTATION_SECTIONS = [
  "Executive Summary",
  "Business Decision",
  "Data Inputs",
  "Formulation Readiness",
  "Objective Function",
  "Decision Variables",
  "Constraints",
  "Solver Configuration",
  "Baseline and Scenarios",
  "Optimization Results",
  "Sensitivity and Tradeoffs",
  "Validation",
  "Recommendation",
  "Implementation Plan",
  "Monitoring Plan",
  "Limitations",
  "Approvals",
  "Reproducibility Appendix",
  "Python Code",
  "SAS-Compatible Code",
];

function initialState(): TransportationState {
  return {
    templateId: "transportation_logistics",
    decisionTitle: "",
    decisionOwner: "",
    businessObjective: "",
    population: "",
    decisionCadence: "One-time decision",
    governanceBoundary: "",
    bundle: structuredClone(EMPTY_BUNDLE),
    mapping: {},
    formulation: null,
    formulationConfirmed: false,
    routeOverrides: {},
    routeExclusionRationales: {},
    customConstraints: [],
    constraintApprovals: {},
    executableRulesValidated: false,
    objectiveName: "Minimize total cash distribution cost",
    objectiveUnit: "Total distribution cost per planning period",
    horizon: "One planning period",
    baselineDescription: "Current operating allocation using approved route availability and capacity assumptions.",
    method: "Linear programming (LP)",
    tolerance: 1e-7,
    timeLimitSeconds: 30,
    scenarios: DEFAULT_TRANSPORTATION_SCENARIOS.map((row) => ({ ...row })),
    scenarioAnalysis: null,
    result: null,
    perturbationPercent: 10,
    sensitivity: null,
    validationConfirmations: {},
    validation: null,
    validationNotes: "",
    recommendation: "",
    recommendationOwner: "",
    recommendationStatus: "Draft",
    alternatives: "",
    residualRisks: "",
    implementationOwner: "",
    effectiveDate: "",
    operatingCadence: "One-time execution",
    routeExceptionProcess: "",
    fallbackPlan: "",
    monitoringMetrics: "Realized demand, actual shipped quantity, route cost variance, supplier utilization, transport utilization, unmet demand, override rate, exception count, late deliveries, and cost overrun.",
    monitoringCadence: "Daily during execution; monthly model review",
    monitoringThresholds: DEFAULT_TRANSPORTATION_MONITORING_THRESHOLDS.map((row) => ({ ...row })),
    reoptimizationTrigger: "",
    reconciliationProcess: "",
    reviewer: "",
    approvalDate: "",
    code: null,
    userPythonByStep: {},
    userSasByStep: {},
    evidenceByStep: {},
    exportArtifacts: {},
    generatedReport: "",
    generatedReportAt: "",
    studyCompleted: false,
    completedAt: "",
    evidencePackageReference: "",
    savedAt: "",
  };
}

function loadState(projectId: string): TransportationState {
  try {
    const parsed = JSON.parse(localStorage.getItem(`${STORAGE_PREFIX}:${projectId}`) || "null") as Partial<TransportationState> | null;
    if (!parsed) return initialState();
    const formulation = parsed.formulation ?? null;
    const downstreamAnalyticalProof = Boolean(
      parsed.result?.success
      || parsed.scenarioAnalysis
      || parsed.sensitivity
      || parsed.validation,
    );
    const inferredConstraintApprovals = downstreamAnalyticalProof && formulation?.constraints.length
      ? Object.fromEntries(formulation.constraints.map((constraint) => [constraint.name, true]))
      : {};
    return {
      ...initialState(),
      ...parsed,
      templateId: "transportation_logistics",
      bundle: { ...structuredClone(EMPTY_BUNDLE), ...(parsed.bundle ?? {}) },
      formulation,
      formulationConfirmed: Boolean(parsed.formulationConfirmed || (downstreamAnalyticalProof && formulation?.formulationReady)),
      scenarios: parsed.scenarios?.length ? parsed.scenarios : DEFAULT_TRANSPORTATION_SCENARIOS.map((row) => ({ ...row })),
      validationConfirmations: parsed.validationConfirmations ?? {},
      routeOverrides: parsed.routeOverrides ?? {},
      routeExclusionRationales: parsed.routeExclusionRationales ?? {},
      customConstraints: parsed.customConstraints ?? [],
      constraintApprovals: { ...inferredConstraintApprovals, ...(parsed.constraintApprovals ?? {}) },
      executableRulesValidated: Boolean(parsed.executableRulesValidated || (downstreamAnalyticalProof && formulation?.constraints.length)),
      userPythonByStep: parsed.userPythonByStep ?? {},
      userSasByStep: parsed.userSasByStep ?? {},
      evidenceByStep: parsed.evidenceByStep ?? {},
      monitoringThresholds: parsed.monitoringThresholds?.length ? parsed.monitoringThresholds : DEFAULT_TRANSPORTATION_MONITORING_THRESHOLDS.map((row) => ({ ...row })),
      exportArtifacts: parsed.exportArtifacts ?? {},
      generatedReport: parsed.generatedReport ?? "",
      generatedReportAt: parsed.generatedReportAt ?? "",
    };
  } catch {
    return initialState();
  }
}

const TRANSPORTATION_CHARTER_FIELDS: Array<keyof TransportationState> = [
  "decisionTitle",
  "decisionOwner",
  "businessObjective",
  "population",
  "decisionCadence",
  "governanceBoundary",
];

export function invalidateTransportationOptimizationState(projectId: string, nextTemplateId: OptimizationTemplateId) {
  try {
    const saved = JSON.parse(localStorage.getItem(`${STORAGE_PREFIX}:${projectId}`) || "null") as Partial<TransportationState> | null;
    if (!saved) return;
    const reset = initialState();
    for (const field of TRANSPORTATION_CHARTER_FIELDS) {
      if (saved[field] !== undefined) (reset as Record<string, unknown>)[field] = saved[field] as unknown;
    }
    reset.templateId = nextTemplateId;
    localStorage.setItem(`${STORAGE_PREFIX}:${projectId}`, JSON.stringify(reset));
  } catch {
    localStorage.removeItem(`${STORAGE_PREFIX}:${projectId}`);
  }
}

function persistState(projectId: string, state: TransportationState) {
  const compact = { ...state, savedAt: new Date().toISOString() };
  localStorage.setItem(`${STORAGE_PREFIX}:${projectId}`, JSON.stringify(compact));
  window.dispatchEvent(new CustomEvent("atlas-workflow-node-updated"));
  return compact;
}

function fieldClass() {
  return "w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-950 outline-none transition focus:border-blue-500 focus:ring-2 focus:ring-blue-100 disabled:bg-slate-100";
}

function mappingConfidence(value: number | undefined) {
  if (value === undefined || !Number.isFinite(value)) return "Needs Review";
  const normalized = value > 1 ? value / 100 : value;
  if (normalized >= 0.9) return "High";
  if (normalized >= 0.75) return "Medium";
  if (normalized >= 0.5) return "Low";
  return "Needs Review";
}

function fileRole(fileName: string): TransportationBundleRole | null {
  const name = fileName.toLowerCase().replace(/[^a-z0-9]+/g, "_");
  if ((name.includes("transportation") || name.includes("transport")) && name.includes("cost")) return "transportationCost";
  if (name.includes("inventory") || name.includes("handling")) return "inventoryCost";
  if (name.includes("demand")) return "demand";
  if (name.includes("supply")) return "supplyMax";
  if (name.includes("capacity")) return "transportCapacity";
  return null;
}

function parseFormula(formula: string, variables: string[]) {
  const allowed = new Set(variables);
  return formula.split(",").reduce<Record<string, number>>((output, token) => {
    const [rawName, rawValue] = token.split("=");
    const name = rawName?.trim();
    const value = Number(rawValue);
    if (name && allowed.has(name) && Number.isFinite(value)) output[name] = value;
    return output;
  }, {});
}

function downloadFile(fileName: string, content: string, type = "application/json") {
  const url = URL.createObjectURL(new Blob([content], { type }));
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = fileName;
  anchor.click();
  URL.revokeObjectURL(url);
}

function persistenceRunId(projectId: string, runType: string, sourceId?: string) {
  const suffix = sourceId || `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
  return `${projectId}:${runType}:${suffix}`;
}

function persistenceEvidenceId(projectId: string, stage: string) {
  return `optimization-${projectId}-${stage}`;
}

async function contentHash(content: string) {
  if (globalThis.crypto?.subtle) {
    const bytes = new TextEncoder().encode(content);
    const digest = await globalThis.crypto.subtle.digest("SHA-256", bytes);
    return Array.from(new Uint8Array(digest)).map((value) => value.toString(16).padStart(2, "0")).join("");
  }
  let hash = 2166136261;
  for (let index = 0; index < content.length; index += 1) hash = Math.imul(hash ^ content.charCodeAt(index), 16777619);
  return `fnv1a-${(hash >>> 0).toString(16).padStart(8, "0")}`;
}

function allocationCsv(state: TransportationState) {
  const headers = ["supplier", "customer", "variable_name", "quantity", "transport_cost", "inventory_cost", "total_unit_cost", "cost_contribution", "status", "reduced_cost"];
  const rows = state.result?.decisionVector.map((row) => [row.supplier, row.customer, row.variableName, row.quantity, row.transportationCost, row.inventoryCost, row.totalUnitCost, row.costContribution, row.status, row.reducedCost ?? ""]) ?? [];
  return [headers, ...rows]
    .map((row) => row.map((value) => `"${String(value).replace(/"/g, '""')}"`).join(","))
    .join("\n");
}

function governedOptimizationPackage(projectId: string, projectName: string, modelId: string, state: TransportationState) {
  const generatedAt = new Date().toISOString();
  const formulation = state.formulation;
  return {
    schemaVersion: "atlas.optimization.transportation.v1",
    projectMetadata: {
      projectId,
      modelId,
      projectName,
      workflow: "optimization",
      selectedTemplate: "transportation_logistics",
      templateLabel: "Transportation / Logistics",
      generatedAt,
    },
    businessDecision: {
      title: state.decisionTitle,
      owner: state.decisionOwner,
      objective: state.businessObjective,
      population: state.population,
      cadence: state.decisionCadence,
      governanceBoundary: state.governanceBoundary,
    },
    inputBundle: {
      references: state.bundle,
      sourceFiles: formulation?.inputTables.map((row) => row.fileName || row.datasetName || row.datasetId || row.role) ?? [],
      tables: formulation?.inputTables.map((row) => ({
        role: row.role,
        datasetId: row.datasetId,
        versionId: row.versionId,
        fileName: row.fileName,
        rowCount: row.rowCount,
        columnCount: row.columnCount,
        detectedKeys: row.keyColumns,
        valueColumns: row.valueColumns,
        fullArtifact: row.fullArtifact,
        profileStatus: row.profileStatus,
      })) ?? [],
      detectedMapping: formulation?.resolvedMapping ?? state.mapping,
      normalizedRouteSummary: formulation ? {
        customerCount: formulation.metrics.customerCount,
        supplierCount: formulation.metrics.supplierCount,
        routeCount: formulation.metrics.routeCount,
        missingRouteCosts: formulation.metrics.missingRouteCosts,
        duplicateRoutes: formulation.metrics.duplicateRoutes,
      } : null,
      normalizationHash: formulation?.normalizationHash,
    },
    formulation: formulation ? {
      formulationId: formulation.formulationId,
      formulationVersion: formulation.formulationVersion,
      objective: formulation.objective,
      variableDefinitions: formulation.variables,
      routeTable: formulation.routes,
      constraintGroups: {
        demand: formulation.constraints.filter((row) => row.constraintType === "demand"),
        supply: formulation.constraints.filter((row) => row.constraintType === "supply"),
        transportCapacity: formulation.constraints.filter((row) => row.constraintType === "transport_capacity"),
        custom: formulation.constraints.filter((row) => !["demand", "supply", "transport_capacity"].includes(row.constraintType)),
      },
      bounds: formulation.variables.map((row) => ({ variableName: row.name, lowerBound: row.lowerBound, upperBound: row.upperBound, active: row.active })),
      metrics: formulation.metrics,
      readinessChecks: formulation.readinessChecks,
    } : null,
    solver: {
      configuration: { method: state.method, tolerance: state.tolerance, timeLimitSeconds: state.timeLimitSeconds },
      result: state.result,
      decisionVector: state.result?.decisionVector ?? [],
    },
    scenarios: state.scenarioAnalysis,
    sensitivity: state.sensitivity,
    validation: state.validation,
    recommendation: {
      status: state.recommendationStatus,
      owner: state.recommendationOwner,
      recommendedAction: state.recommendation,
      alternativesConsidered: state.alternatives,
      residualRisksAndLimitations: state.residualRisks,
    },
    implementationPlan: {
      owner: state.implementationOwner,
      effectiveDate: state.effectiveDate,
      operatingCadence: state.operatingCadence,
      routeExceptionProcess: state.routeExceptionProcess,
      fallbackPlan: state.fallbackPlan,
      reoptimizationTrigger: state.reoptimizationTrigger,
      reconciliationProcess: state.reconciliationProcess,
    },
    monitoringPlan: {
      metrics: state.monitoringMetrics,
      cadence: state.monitoringCadence,
      thresholds: state.monitoringThresholds,
    },
    documentation: {
      sections: DOCUMENTATION_SECTIONS,
      populatedSections: optimizationDocumentationSectionCount(state),
      reviewer: state.reviewer,
      approvalDate: state.approvalDate,
      generatedReportAt: state.generatedReportAt,
      studyCompleted: state.studyCompleted,
    },
    evidence: {
      references: state.evidenceByStep,
      packageReference: state.evidencePackageReference,
      exports: state.exportArtifacts,
    },
    timestamps: {
      exportedAt: generatedAt,
      savedAt: state.savedAt,
      completedAt: state.completedAt,
    },
  };
}

function buildOptimizationReport(projectId: string, projectName: string, state: TransportationState) {
  const formulation = state.formulation;
  const result = state.result;
  const sensitivityRows = state.sensitivity?.rows ?? [];
  const largestDriver = sensitivityRows.length
    ? [...sensitivityRows].sort((a, b) => Math.abs(b.costChange ?? 0) - Math.abs(a.costChange ?? 0))[0]?.driver
    : "Not available";
  const inputRows = formulation?.inputTables.map((row) => `- ${row.label}: ${row.fileName || row.datasetName || row.datasetId || "Not available"}; ${row.rowCount ?? 0} rows; ${row.columnCount ?? 0} columns; ${row.profileStatus}.`).join("\n") || "- No governed input bundle is available.";
  const constraints = formulation
    ? `Demand constraints: ${formulation.metrics.demandConstraintCount}. Supply constraints: ${formulation.metrics.supplyConstraintCount}. Transport capacity constraints: ${formulation.metrics.transportConstraintCount}. Non-negativity bounds: ${formulation.metrics.nonNegativityBoundCount}.`
    : "No route-level constraint set is available.";
  const scenarios = state.scenarioAnalysis?.results.map((row) => `- ${row.scenarioName}: ${row.businessValid ? `business-valid, total cost ${formatTransportationValue(row.totalCost)}` : `infeasible, unmet demand ${formatTransportationValue(row.unmetDemand, 0)}`}.`).join("\n") || "- Scenario analysis has not been run.";
  const validation = state.validation?.checks.map((row) => `- ${row.label}: ${row.passed ? "Passed" : "Not passed"}. ${row.evidence}`).join("\n") || "- Validation has not been run.";
  const thresholds = state.monitoringThresholds.map((row) => `- ${row.metric}: ${row.threshold}; owner ${row.owner}; cadence ${row.cadence}; escalation ${row.escalation}; status ${row.status}.`).join("\n");
  return [
    `# Transportation / Logistics Optimization Report`,
    "",
    `Project: ${projectName || "Optimization Project"}`,
    `Project ID: ${projectId}`,
    `Generated: ${new Date().toISOString()}`,
    "",
    "## 1. Executive Summary",
    `The saved transportation solution is ${result?.success ? "business-valid" : "not ready"}. Total logistics cost is ${formatTransportationValue(result?.totalCost)}. Demand fulfilled is ${formatTransportationValue(result?.demandFulfilled, 0)} of ${formatTransportationValue(result?.totalDemand, 0)}, with ${formatTransportationValue(result?.unmetDemand, 0)} unmet demand and ${result?.activeRoutes ?? 0} active routes out of ${result?.totalRoutes ?? formulation?.metrics.routeCount ?? 0}.`,
    "",
    "## 2. Business Decision",
    `${state.decisionTitle}\n\nOwner: ${state.decisionOwner}.\n\n${state.businessObjective}`,
    "",
    "## 3. Data Inputs",
    inputRows,
    `\nNormalization hash: ${formulation?.normalizationHash || "Not available"}.`,
    "",
    "## 4. Formulation Readiness",
    `Status: ${formulation?.formulationStatus || "Not available"}. ${formulation?.readinessChecks.map((row) => `${row.label}: ${row.status}.`).join(" ") || ""}`,
    "",
    "## 5. Objective Function",
    `${formulation?.objective.expression || state.objectiveName}. Unit: ${state.objectiveUnit}. Horizon: ${state.horizon}. ${formulation?.objective.plainEnglish || ""}`,
    "",
    "## 6. Decision Variables",
    `${formulation?.metrics.decisionVariableCount ?? 0} continuous supplier-to-customer route variables were generated. Active route overrides and exclusion rationales are retained in the governed package.`,
    "",
    "## 7. Constraints",
    constraints,
    "",
    "## 8. Solver Configuration",
    `Method: ${state.method}. Tolerance: ${state.tolerance}. Time limit: ${state.timeLimitSeconds} seconds. Solver status: ${result?.solverStatus || "Not run"}.`,
    "",
    "## 9. Baseline and Scenarios",
    scenarios,
    "",
    "## 10. Optimization Results",
    `Total cost: ${formatTransportationValue(result?.totalCost)}. Demand fulfilled: ${formatTransportationValue(result?.demandFulfilled, 0)} / ${formatTransportationValue(result?.totalDemand, 0)}. Unmet demand: ${formatTransportationValue(result?.unmetDemand, 0)}. Active routes: ${result?.activeRoutes ?? 0} / ${result?.totalRoutes ?? 0}. Binding constraints: ${result?.bindingConstraints.length ?? 0}.`,
    "",
    "## 11. Sensitivity and Tradeoffs",
    `${state.sensitivity?.conclusion || "Sensitivity has not been run."} Largest tested driver: ${largestDriver}.`,
    "",
    "## 12. Validation",
    `Validation score: ${state.validation?.score ?? 0}%. Recommendation gate: ${state.validation?.recommendationAllowed ? "Open" : "Blocked"}.\n\n${validation}`,
    "",
    "## 13. Recommendation",
    `Status: ${state.recommendationStatus}. Owner: ${state.recommendationOwner}.\n\n${state.recommendation}\n\nAlternatives considered: ${state.alternatives}`,
    "",
    "## 14. Implementation Plan",
    `Owner: ${state.implementationOwner}. Effective date: ${state.effectiveDate || "Not scheduled"}. Operating cadence: ${state.operatingCadence}.\n\nRoute exception process: ${state.routeExceptionProcess}\n\nFallback plan: ${state.fallbackPlan}\n\nReconciliation: ${state.reconciliationProcess}`,
    "",
    "## 15. Monitoring Plan",
    `${thresholds}\n\nRe-optimization trigger: ${state.reoptimizationTrigger}`,
    "",
    "## 16. Limitations",
    state.residualRisks || "No residual risks and limitations were documented.",
    "",
    "## 17. Approvals",
    `Final reviewer: ${state.reviewer || "Pending"}. Approval date: ${state.approvalDate || "Pending"}. Recommendation owner: ${state.recommendationOwner || "Pending"}.`,
    "",
    "## 18. Reproducibility Appendix",
    `Formulation ID: ${formulation?.formulationId || "Not available"}. Normalization hash: ${formulation?.normalizationHash || "Not available"}. Solver run: ${result?.runId || "Not available"}. Scenario runs: ${state.scenarioAnalysis?.scenarioCount ?? 0}. Sensitivity run: ${state.sensitivity?.baseRunId || "Not available"}.`,
    "",
    "## 19. Python Code",
    "```python",
    state.code?.python.code || "# Python code is not available.",
    "```",
    "",
    "## 20. SAS-Compatible Code",
    "Template-only mode. Execute in a licensed SAS environment or adapt through SASPy.",
    "```sas",
    state.code?.sas.code || "/* SAS-compatible code is not available. */",
    "```",
    "",
  ].join("\n");
}

function optimizationArtifactPayload(stage: OptimizationEvidenceStage, state: TransportationState) {
  const formulation = state.formulation;
  const result = state.result;
  const base = {
    stage,
    capturedAt: new Date().toISOString(),
    formulationId: formulation?.formulationId,
    formulationVersion: formulation?.formulationVersion,
    normalizationHash: formulation?.normalizationHash,
    solutionId: result?.solutionId,
    runId: result?.runId,
  };
  const payloads: Record<OptimizationEvidenceStage, Record<string, unknown>> = {
    decision_charter: { decisionTitle: state.decisionTitle, decisionOwner: state.decisionOwner, businessObjective: state.businessObjective, population: state.population, decisionCadence: state.decisionCadence, governanceBoundary: state.governanceBoundary },
    input_bundle: { bundle: state.bundle, inputTables: formulation?.inputTables, resolvedMapping: formulation?.resolvedMapping, routeSummary: formulation?.metrics },
    route_normalization: { normalizationHash: formulation?.normalizationHash, normalizedRoutes: formulation?.routes, resolvedMapping: formulation?.resolvedMapping, readinessChecks: formulation?.readinessChecks },
    formulation_readiness: { formulationStatus: formulation?.formulationStatus, formulationReady: formulation?.formulationReady, readinessChecks: formulation?.readinessChecks },
    objective: { objectiveName: state.objectiveName, objectiveUnit: state.objectiveUnit, horizon: state.horizon, objective: formulation?.objective },
    decision_variables: { variables: formulation?.variables, routes: formulation?.routes, routeOverrides: state.routeOverrides, exclusionRationales: state.routeExclusionRationales },
    constraints: { constraints: formulation?.constraints, approvals: state.constraintApprovals, executableRulesValidated: state.executableRulesValidated, customConstraints: state.customConstraints },
    solver_configuration: { method: state.method, tolerance: state.tolerance, timeLimitSeconds: state.timeLimitSeconds, variableCount: formulation?.metrics.decisionVariableCount, constraintCount: formulation?.constraints.length },
    scenarios: { scenarios: state.scenarios, analysis: state.scenarioAnalysis },
    solution: { result, decisionVector: result?.decisionVector, constraintResults: result?.constraintResults },
    sensitivity: { sensitivity: state.sensitivity, perturbationPercent: state.perturbationPercent },
    validation: { validation: state.validation, confirmations: state.validationConfirmations, notes: state.validationNotes },
    recommendation: { status: state.recommendationStatus, owner: state.recommendationOwner, recommendedAction: state.recommendation, alternativesConsidered: state.alternatives, residualRisksAndLimitations: state.residualRisks },
    implementation_plan: { owner: state.implementationOwner, effectiveDate: state.effectiveDate, operatingCadence: state.operatingCadence, routeExceptionProcess: state.routeExceptionProcess, fallbackPlan: state.fallbackPlan, reconciliationProcess: state.reconciliationProcess },
    monitoring_plan: { metrics: state.monitoringMetrics, cadence: state.monitoringCadence, thresholds: state.monitoringThresholds, reoptimizationTrigger: state.reoptimizationTrigger },
    documentation_package: { sections: DOCUMENTATION_SECTIONS, populatedSections: optimizationDocumentationSectionCount(state), generatedReportAt: state.generatedReportAt, reviewer: state.reviewer, approvalDate: state.approvalDate },
    code_reproducibility: {
      pythonCodeReference: state.exportArtifacts.python_code?.evidenceId || state.evidenceByStep.code_reproducibility || "Embedded in optimization package",
      sasCompatibleCodeReference: state.exportArtifacts.sas_code?.evidenceId || state.evidenceByStep.code_reproducibility || "Embedded in optimization package",
      formulationHash: formulation?.formulationId,
      normalizationHash: formulation?.normalizationHash,
      solverMethod: state.method,
      solverParameters: { tolerance: state.tolerance, timeLimitSeconds: state.timeLimitSeconds },
      routeVariableCount: formulation?.metrics.decisionVariableCount ?? 0,
      constraintCount: formulation?.constraints.length ?? 0,
      scenarioRunCount: state.scenarioAnalysis?.scenarioCount ?? 0,
      sensitivityRunReference: state.sensitivity?.baseRunId,
      pythonRuntimeStatus: state.code?.python.runtimeStatus,
      sasRuntimeStatus: state.code?.sas.runtimeStatus,
    },
  };
  return { ...base, ...payloads[stage] };
}

function evidenceArtifactId(state: TransportationState, stage: OptimizationEvidenceStage) {
  const root = state.result?.solutionId || state.formulation?.formulationId || "charter";
  return `${root}:${stage}`;
}

function codeStorageWrite(key: string, stepKey: string, value: string) {
  try {
    const parsed = JSON.parse(localStorage.getItem(key) || "{}") as Record<string, string>;
    localStorage.setItem(key, JSON.stringify({ ...parsed, [stepKey]: value }));
  } catch {
    localStorage.setItem(key, JSON.stringify({ [stepKey]: value }));
  }
}

export default function TransportationOptimizationWorkflow({ projectId, step, nextStep, onComplete, navigationError, onStrategyChange }: Props) {
  const stepNumber = Number(step.id.split("-").pop() || "1");
  const projectName = useWorkflowStore((workflowState) => workflowState.projectName);
  const modelId = useWorkflowStore((workflowState) => workflowState.modelId);
  const workflowSteps = useWorkflowStore((workflowState) => workflowState.workflowSteps);
  const [state, setState] = useState<TransportationState>(() => loadState(projectId));
  const stateRef = useRef(state);
  const [datasets, setDatasets] = useState<DatasetSummary[]>([]);
  const [busy, setBusy] = useState<BusyAction>("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [codeResult, setCodeResult] = useState<CodeRunResult | null>(null);

  const update = (patch: Partial<TransportationState>) => setState((current) => {
    const next = { ...current, ...patch };
    stateRef.current = next;
    return next;
  });
  const requestInput = useMemo(() => ({
    bundle: state.bundle,
    mapping: state.mapping,
    routeOverrides: state.routeOverrides,
    customConstraints: state.customConstraints.map(({ formula: _formula, ...constraint }) => constraint),
    solver: { method: state.method, tolerance: state.tolerance, timeLimitSeconds: state.timeLimitSeconds },
  }), [state.bundle, state.mapping, state.routeOverrides, state.customConstraints, state.method, state.tolerance, state.timeLimitSeconds]);

  useEffect(() => {
    if (!state.formulation || state.code?.generatorVersion === TRANSPORTATION_CODE_GENERATOR_VERSION) return;
    let cancelled = false;
    void generateTransportationCode({ ...requestInput, stage: "formulation" })
      .then((code) => {
        if (!cancelled) update({ code });
      })
      .catch((refreshError) => console.warn("ATLAS transportation code refresh failed", refreshError));
    return () => { cancelled = true; };
  }, [state.formulation?.formulationId, state.code?.generatorVersion, requestInput]);

  useEffect(() => {
    stateRef.current = state;
    const timer = window.setTimeout(() => {
      try {
        const compact = persistState(projectId, state);
        queueOptimizationStateDatabaseSave(projectId, compact as unknown as Record<string, unknown>, { projectName });
      } catch (saveError) { console.warn("ATLAS transportation autosave failed", saveError); }
    }, 250);
    return () => window.clearTimeout(timer);
  }, [projectId, projectName, state]);

  useEffect(() => {
    let active = true;
    setBusy("datasets");
    listDatasets()
      .then((payload) => { if (active) setDatasets(payload.datasets); })
      .catch((datasetError) => { if (active) setError(datasetError instanceof Error ? datasetError.message : "Datasets could not be loaded."); })
      .finally(() => { if (active) setBusy(""); });
    return () => { active = false; };
  }, []);

  const resetAnalyticalState = (patch: Partial<TransportationState> = {}) => update({
    formulation: null,
    formulationConfirmed: false,
    scenarioAnalysis: null,
    result: null,
    sensitivity: null,
    validation: null,
    executableRulesValidated: false,
    recommendationStatus: "Draft",
    studyCompleted: false,
    completedAt: "",
    evidencePackageReference: "",
    code: null,
    evidenceByStep: stateRef.current.evidenceByStep.decision_charter
      ? { decision_charter: stateRef.current.evidenceByStep.decision_charter }
      : {},
    exportArtifacts: {},
    generatedReport: "",
    generatedReportAt: "",
    ...patch,
  });

  const persistRunRecord = async (
    runType: string,
    parameters: Record<string, unknown>,
    metrics: Record<string, unknown>,
    artifacts: Record<string, unknown>,
    sourceId?: string,
  ) => {
    const timestamp = new Date().toISOString();
    await saveRunToDatabase(projectId, {
      runId: persistenceRunId(projectId, runType, sourceId),
      runType,
      workflowType: "optimization",
      status: "complete",
      startedAt: timestamp,
      completedAt: timestamp,
      parameters,
      metrics,
      artifacts,
    });
  };

  const persistStageEvidence = async (
    stage: OptimizationEvidenceStage,
    current: TransportationState,
    status: "generated" | "captured" | "ready" | "approved" | "stale" | "rejected" = "generated",
  ) => {
    const definition = TRANSPORTATION_EVIDENCE_STAGES.find((row) => row.stage === stage);
    if (!definition) return false;
    const timestamp = new Date().toISOString();
    return saveEvidenceToDatabase(projectId, {
      evidenceId: persistenceEvidenceId(projectId, stage),
      workflowType: "optimization",
      stepId: `optimization-${definition.stepNumber}`,
      artifactType: definition.evidenceType,
      status,
      title: `Transportation Optimization: ${definition.label}`,
      summary: `${definition.label} was ${status} from the governed Transportation / Logistics workflow.`,
      sourceRef: `/workflow/optimization/${definition.stepNumber}`,
      artifactHash: stage === "solution" ? current.result?.solutionId : current.formulation?.normalizationHash,
      createdAt: timestamp,
      capturedAt: status === "captured" || status === "ready" || status === "approved" ? timestamp : undefined,
      approvedAt: status === "approved" ? timestamp : undefined,
      payload: optimizationArtifactPayload(stage, current),
    });
  };

  const recordOptimizationDecision = (
    workflowStep: string,
    subject: string,
    previousValue: unknown,
    newValue: unknown,
    userReason: string,
    owner = stateRef.current.decisionOwner,
  ) => logDecision({
    workflowStep,
    actionType: "workflow_setting_changed",
    subject,
    previousValue,
    newValue,
    systemRecommendation: "Retain material optimization choices with their accountable owner, source result, and governance rationale.",
    followStatus: "followed",
    userReason,
    owner,
  });

  const assignDataset = (role: TransportationBundleRole, datasetId: string) => {
    const dataset = datasets.find((row) => row.datasetId === datasetId);
    resetAnalyticalState({
      bundle: {
        ...state.bundle,
        [role]: { datasetId, versionId: dataset?.latestVersion?.versionId ?? "" },
      },
    });
  };

  const registerFile = async (role: TransportationBundleRole, file: File) => {
    const dataset = await uploadDataset({ file, name: file.name.replace(/\.[^.]+$/, ""), domain: "Optimization", sourceType: "Transportation input bundle" });
    const versionId = dataset.latestVersion?.versionId ?? "";
    await linkDatasetToProject(projectId, dataset.datasetId, versionId, `optimization_${role}`);
    setDatasets((current) => [dataset, ...current.filter((row) => row.datasetId !== dataset.datasetId)]);
    return { role, dataset, reference: { datasetId: dataset.datasetId, versionId } };
  };

  const uploadRole = async (role: TransportationBundleRole, event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    setBusy("upload"); setError(""); setMessage("");
    try {
      const registered = await registerFile(role, file);
      resetAnalyticalState({ bundle: { ...state.bundle, [role]: registered.reference } });
      setMessage(`${registered.dataset.name} registered as ${TRANSPORTATION_ROLE_CONFIG.find((row) => row.bundle_key === role)?.display_name}.`);
    } catch (uploadError) {
      setError(uploadError instanceof Error ? uploadError.message : "Input table upload failed.");
    } finally { setBusy(""); }
  };

  const uploadBundle = async (event: ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(event.target.files ?? []);
    event.target.value = "";
    if (!files.length) return;
    const classified = files.map((file) => ({ file, role: fileRole(file.name) })).filter((row): row is { file: File; role: TransportationBundleRole } => Boolean(row.role));
    if (!classified.length) { setError("ATLAS could not classify the selected files. Include demand, supply, capacity, transportation cost, or inventory cost in each file name."); return; }
    setBusy("upload"); setError(""); setMessage("");
    try {
      const registered = await Promise.all(classified.map((row) => registerFile(row.role, row.file)));
      const bundle = { ...state.bundle };
      registered.forEach((row) => { bundle[row.role] = row.reference; });
      resetAnalyticalState({ bundle });
      setMessage(`${registered.length} transportation input tables registered and assigned.`);
    } catch (uploadError) {
      setError(uploadError instanceof Error ? uploadError.message : "One or more input tables could not be registered.");
    } finally { setBusy(""); }
  };

  const autoAssignRegistered = () => {
    const bundle = { ...state.bundle };
    let count = 0;
    datasets.forEach((dataset) => {
      const role = fileRole(`${dataset.name} ${dataset.latestVersion?.originalFilename ?? ""}`);
      if (role && !bundle[role].datasetId) {
        bundle[role] = { datasetId: dataset.datasetId, versionId: dataset.latestVersion?.versionId ?? "" };
        count += 1;
      }
    });
    resetAnalyticalState({ bundle });
    setMessage(count ? `${count} registered input table${count === 1 ? "" : "s"} matched by governed file name.` : "No additional registered files matched the template-defined input roles.");
  };

  const buildFormulation = async () => {
    setBusy("formulate"); setError(""); setMessage("");
    try {
      const payload = await formulateTransportation(requestInput);
      const current = {
        ...stateRef.current,
        formulation: payload.formulation,
        formulationConfirmed: false,
        constraintApprovals: {},
        executableRulesValidated: false,
        code: payload.code,
        scenarioAnalysis: null,
        result: null,
        sensitivity: null,
        validation: null,
      } as TransportationState;
      update(current);
      const inputTables = payload.formulation.inputTables;
      await persistRunRecord(
        "optimization_input_normalization",
        { templateId: current.templateId, mapping: payload.formulation.resolvedMapping },
        {
          customers: payload.formulation.metrics.customerCount,
          suppliers: payload.formulation.metrics.supplierCount,
          route_count: payload.formulation.metrics.routeCount,
          required_inputs_loaded: REQUIRED_TRANSPORTATION_ROLES.filter((role) => current.bundle[role]?.datasetId).length,
          optional_inputs_loaded: OPTIONAL_TRANSPORTATION_ROLES.filter((role) => current.bundle[role]?.datasetId).length,
          missing_route_costs: payload.formulation.metrics.missingRouteCosts,
          duplicate_keys: Math.max(payload.formulation.metrics.duplicateRoutes, ...inputTables.map((table) => table.duplicateKeys ?? 0)),
          total_demand: payload.formulation.metrics.totalDemand,
          total_supply_max: payload.formulation.metrics.totalSupplyMax,
          total_transport_capacity: payload.formulation.metrics.totalTransportCapacity,
        },
        {
          input_file_names: inputTables.map((table) => table.fileName || table.datasetName || table.datasetId),
          normalized_route_table_reference: `${payload.formulation.formulationId}:routes`,
          normalization_hash: payload.formulation.normalizationHash,
        },
        payload.formulation.formulationId,
      );
      await Promise.all([
        persistStageEvidence("input_bundle", current),
        persistStageEvidence("route_normalization", current),
        persistStageEvidence("formulation_readiness", current),
      ]);
      recordOptimizationDecision("Optimization Data Acquisition", "Transportation input bundle confirmed", "Unconfirmed", "Confirmed and normalized", `${inputTables.length} governed input tables produced ${payload.formulation.metrics.routeCount} normalized routes.`);
      recordOptimizationDecision("Optimization Formulation", "Formulation strategy selected", "Unbuilt", `${current.method} transportation formulation`, `Formulation ${payload.formulation.formulationId} uses normalization hash ${payload.formulation.normalizationHash}.`);
      setMessage(`Normalized ${payload.formulation.metrics.routeCount} routes across ${payload.formulation.metrics.customerCount} customers and ${payload.formulation.metrics.supplierCount} suppliers.`);
    } catch (formulationError) {
      setError(formulationError instanceof Error ? formulationError.message : "Transportation formulation could not be built.");
    } finally { setBusy(""); }
  };

  const runSolve = async () => {
    setBusy("solve"); setError(""); setMessage("");
    try {
      const payload = await solveTransportation(requestInput);
      const current = { ...stateRef.current, formulation: payload.formulation, result: payload.result, sensitivity: null, validation: null } as TransportationState;
      update(current);
      await persistRunRecord(
        "optimization_solver",
        { method: current.method, tolerance: current.tolerance, time_limit_seconds: current.timeLimitSeconds },
        {
          solver_status: payload.result.solverStatus,
          business_validity: payload.result.businessValidityStatus,
          total_cost: payload.result.totalCost,
          demand_fulfilled: payload.result.demandFulfilled,
          total_demand: payload.result.totalDemand,
          unmet_demand: payload.result.unmetDemand,
          active_routes: payload.result.activeRoutes,
          total_routes: payload.result.totalRoutes,
          binding_constraints: payload.result.bindingConstraints.length,
          runtime_ms: payload.result.runtimeMs,
          optimality_gap: payload.result.optimalityGap,
        },
        {
          decision_vector: payload.result.decisionVector,
          allocation_matrix: payload.result.allocationMatrix,
          constraint_diagnostics: payload.result.constraintResults,
          formulation_hash: payload.result.formulationId,
          normalization_hash: payload.formulation.normalizationHash,
        },
        payload.result.runId,
      );
      await Promise.all([
        persistStageEvidence("solver_configuration", current),
        persistStageEvidence("solution", current),
      ]);
      if (payload.result.success) recordOptimizationDecision("Optimization Solver", "Solver result accepted", "No accepted solution", payload.result.solutionId || payload.result.runId, `Business-valid ${payload.result.solverStatus} solution fulfilled ${payload.result.demandFulfilled} of ${payload.result.totalDemand} demand units.`);
      setMessage(payload.result.success ? `Business-valid optimum found. Demand fulfilled: ${formatTransportationValue(payload.result.demandFulfilled, 0)} of ${formatTransportationValue(payload.result.totalDemand, 0)}.` : "Solver execution completed, but the result is not business-valid.");
    } catch (solveError) {
      setError(solveError instanceof Error ? solveError.message : "Transportation solve failed.");
    } finally { setBusy(""); }
  };

  const runScenarios = async () => {
    setBusy("scenarios"); setError(""); setMessage("");
    try {
      const payload = await analyzeTransportationScenarios({ ...requestInput, scenarios: state.scenarios });
      const current = { ...stateRef.current, formulation: payload.formulation, scenarioAnalysis: payload.analysis, result: payload.analysis.baseResult ?? stateRef.current.result, validation: null } as TransportationState;
      update(current);
      const costs = payload.analysis.results.map((row) => row.totalCost).filter((value): value is number => value != null && Number.isFinite(value));
      const severe = payload.analysis.results.find((row) => row.scenarioId === "severe-disruption" || /severe/i.test(row.scenarioName));
      await persistRunRecord(
        "optimization_scenarios",
        { scenarios: current.scenarios },
        {
          scenario_count: payload.analysis.scenarioCount,
          feasible_count: payload.analysis.validScenarioCount,
          infeasible_count: payload.analysis.infeasibleScenarioCount,
          base_cost: payload.analysis.baseResult?.totalCost ?? null,
          worst_case_cost: costs.length ? Math.max(...costs) : null,
          severe_disruption_status: severe ? (severe.businessValid ? "business_valid" : "infeasible") : "not_configured",
        },
        { scenario_results: payload.analysis.results },
      );
      await persistStageEvidence("scenarios", current);
      setMessage(`${payload.analysis.scenarioCount} transportation scenarios completed; ${payload.analysis.infeasibleScenarioCount} infeasible stress case${payload.analysis.infeasibleScenarioCount === 1 ? "" : "s"} identified.`);
    } catch (scenarioError) {
      setError(scenarioError instanceof Error ? scenarioError.message : "Scenario analysis failed.");
    } finally { setBusy(""); }
  };

  const runSensitivity = async () => {
    setBusy("sensitivity"); setError(""); setMessage("");
    try {
      const payload = await analyzeTransportationSensitivity({ ...requestInput, perturbationPercent: state.perturbationPercent });
      const current = { ...stateRef.current, formulation: payload.formulation, sensitivity: payload.analysis, validation: null } as TransportationState;
      update(current);
      const sorted = [...payload.analysis.rows].sort((a, b) => Math.abs(b.costChange ?? 0) - Math.abs(a.costChange ?? 0));
      const impactFor = (pattern: RegExp) => sorted.find((row) => pattern.test(row.driver))?.costChange ?? null;
      await persistRunRecord(
        "optimization_sensitivity",
        { perturbation_percent: payload.analysis.perturbationPercent },
        {
          top_driver: sorted[0]?.driver ?? null,
          top_driver_cost_impact: sorted[0]?.costChange ?? null,
          route_cost_impact: impactFor(/route|transport.*cost/i),
          transport_capacity_impact: impactFor(/transport.*capacity|capacity/i),
          supplier_supply_impact: impactFor(/supplier|supply/i),
        },
        {
          tornado_results: payload.analysis.tornado,
          perturbation_diagnostics: payload.analysis.rows,
          marginal_values: payload.analysis.shadowPrices,
        },
      );
      await persistStageEvidence("sensitivity", current);
      setMessage(`Sensitivity completed across ${payload.analysis.rows.length} real logistics perturbations.`);
    } catch (sensitivityError) {
      setError(sensitivityError instanceof Error ? sensitivityError.message : "Sensitivity analysis failed.");
    } finally { setBusy(""); }
  };

  const runValidation = async () => {
    setBusy("validation"); setError(""); setMessage("");
    try {
      const payload = await validateTransportation({ ...requestInput, confirmations: state.validationConfirmations });
      const current = { ...stateRef.current, formulation: payload.formulation, result: payload.result, scenarioAnalysis: payload.scenarios, sensitivity: payload.sensitivity, validation: payload.validation } as TransportationState;
      update(current);
      const checkStatus = (pattern: RegExp) => payload.validation.checks.find((check) => pattern.test(`${check.id} ${check.label}`))?.passed ?? false;
      await persistRunRecord(
        "optimization_validation",
        { confirmations: current.validationConfirmations },
        {
          validation_score: payload.validation.score,
          mathematical_checks_status: payload.validation.mathematicalSuccess ? "passed" : "failed",
          evidence_completeness: checkStatus(/evidence|reproduc/i),
          implementation_readiness: checkStatus(/implementation|operational/i),
          independent_review: checkStatus(/independent|review/i),
          gate_status: payload.validation.recommendationAllowed ? "open" : "blocked",
        },
        { validator_notes: current.validationNotes, validation_checklist: payload.validation.checks },
      );
      await persistStageEvidence("validation", current);
      recordOptimizationDecision("Optimization Validation", "Validation completed", "Not run", `${payload.validation.score}% | ${payload.validation.recommendationAllowed ? "Gate open" : "Gate blocked"}`, payload.validation.blockers.length ? payload.validation.blockers.join("; ") : "All required validation checks passed.", current.reviewer || current.decisionOwner);
      setMessage(`Validation score: ${payload.validation.score}%. Recommendation gate is ${payload.validation.recommendationAllowed ? "open" : "blocked"}.`);
    } catch (validationError) {
      setError(validationError instanceof Error ? validationError.message : "Validation failed.");
    } finally { setBusy(""); }
  };

  const setRouteActive = (routeId: string, active: boolean) => {
    const routeOverrides = { ...state.routeOverrides, [routeId]: active };
    const formulation = state.formulation ? {
      ...state.formulation,
      routes: state.formulation.routes.map((route) => route.route_id === routeId ? { ...route, active, upper_bound: active ? null : 0 } : route),
      variables: state.formulation.variables.map((variable) => {
        const route = state.formulation?.routes.find((item) => item.variable_name === variable.name);
        return route?.route_id === routeId ? { ...variable, active, upperBound: active ? null : 0 } : variable;
      }),
      metrics: { ...state.formulation.metrics, routeUpperBoundCount: Object.values(routeOverrides).filter((value) => !value).length },
    } : null;
    update({ routeOverrides, formulation, scenarioAnalysis: null, result: null, sensitivity: null, validation: null, formulationConfirmed: false, executableRulesValidated: false, studyCompleted: false });
  };

  const addCustomConstraint = () => {
    const first = state.formulation?.variables[0]?.name ?? "";
    update({ customConstraints: [...state.customConstraints, { id: `custom-${Date.now()}`, name: `Custom policy ${state.customConstraints.length + 1}`, formula: first ? `${first}=1` : "", coefficients: first ? { [first]: 1 } : {}, sense: "<=", rhs: 0, category: "Policy" }], formulationConfirmed: false, executableRulesValidated: false, result: null });
  };

  const setCustomConstraint = (index: number, patch: Partial<CustomConstraint>) => {
    const variables = state.formulation?.variables.map((row) => row.name) ?? [];
    update({
      customConstraints: state.customConstraints.map((row, rowIndex) => {
        if (rowIndex !== index) return row;
        const next = { ...row, ...patch };
        if (patch.formula !== undefined) next.coefficients = parseFormula(patch.formula, variables);
        return next;
      }),
      formulationConfirmed: false,
      executableRulesValidated: false,
      result: null,
      scenarioAnalysis: null,
      sensitivity: null,
      validation: null,
    });
  };

  const applyCharter = () => update({
    decisionTitle: "Minimize total supplier-to-customer cash distribution cost while satisfying all customer demand and respecting supplier supply and transportation-capacity limits.",
    decisionOwner: "Operations planning owner",
    businessObjective: "Determine the least-cost allocation of cash or logistics capacity from available supplier locations to customer demand locations. Satisfy all demand, avoid exceeding supplier limits, respect transportation capacity, and produce a reproducible allocation plan for operational review.",
    population: "Five supplier locations and six customer demand locations. Each customer has a required demand quantity. Each supplier has maximum supply, transportation capacity, inventory or handling cost, and route-specific transportation cost.",
    governanceBoundary: "Operational feasibility, cost minimization, capacity limits, fulfillment requirements, reproducibility controls, exception management, and documented solver evidence.",
  });

  const generateRecommendation = () => {
    const result = state.result;
    if (!result?.success) return;
    const feasibleScenarios = state.scenarioAnalysis?.validScenarioCount ?? 0;
    const totalScenarios = state.scenarioAnalysis?.scenarioCount ?? 0;
    const severeDisruption = state.scenarioAnalysis?.results.find((row) => !row.businessValid)?.scenarioName ?? "No infeasible stress case";
    const largestSensitivityDriver = state.sensitivity?.rows.length
      ? [...state.sensitivity.rows].sort((a, b) => Math.abs(b.costChange ?? 0) - Math.abs(a.costChange ?? 0))[0]?.driver
      : "Not available";
    const capacityRespected = result.constraintResults.every((row) => row.feasible);
    const patch: Partial<TransportationState> = {
      recommendation: `Approve the optimized cash and logistics distribution plan for the selected planning period. The solution fulfills ${formatTransportationValue(result.demandFulfilled, 0)} of ${formatTransportationValue(result.totalDemand, 0)} demand units across ${state.formulation?.metrics.customerCount ?? 0} demand locations. Total optimized distribution cost is ${formatTransportationValue(result.totalCost)}. The plan uses ${result.activeRoutes} of ${result.totalRoutes} supplier-customer routes, and supplier and transportation capacity are ${capacityRespected ? "respected" : "not fully respected"}. Scenario coverage is ${feasibleScenarios} of ${totalScenarios} feasible. ${severeDisruption} is the infeasible stress case requiring contingency planning. ${largestSensitivityDriver} is the largest tested sensitivity driver. Implementation should proceed only after operations confirms route availability, cost assumptions, exception handling, monitoring ownership, and fallback controls.`,
      recommendationOwner: state.recommendationOwner || state.decisionOwner,
      recommendationStatus: "Recommended",
      alternatives: `Retain the current operating allocation, execute a partial allocation using only the lowest-risk routes, or rerun the model after refreshing demand, supply, transport-capacity, and route-cost assumptions. These alternatives preserve operational flexibility but may increase total cost or reduce resilience compared with the validated optimum.`,
      residualRisks: `Residual risks include supplier or route unavailability, demand variance, transport-capacity deterioration, route-cost changes, execution overrides, and conditions resembling the ${state.scenarioAnalysis?.results.find((row) => !row.businessValid)?.scenarioName ?? "most severe disruption"} scenario. Monitor these risks against the implementation thresholds and rerun the model when a trigger is breached.`,
    };
    update(patch);
    const current = { ...stateRef.current, ...patch } as TransportationState;
    void persistStageEvidence("recommendation", current);
    recordOptimizationDecision("Optimization Recommendation", "Recommendation moved to Recommended", state.recommendationStatus, "Recommended", `Recommendation is based on business-valid solution ${result.solutionId || result.runId}, validation score ${state.validation?.score ?? 0}%, and ${totalScenarios} scenario runs.`, current.recommendationOwner);
  };

  const validateExecutableRules = async () => {
    setBusy("formulate"); setError(""); setMessage("");
    try {
      const payload = await formulateTransportation(requestInput);
      const approvals = Object.fromEntries(payload.formulation.constraints.map((row) => [row.name, Boolean(state.constraintApprovals[row.name])]));
      const current = { ...stateRef.current, formulation: payload.formulation, code: payload.code, constraintApprovals: approvals, executableRulesValidated: payload.formulation.formulationReady, result: null, scenarioAnalysis: null, sensitivity: null, validation: null } as TransportationState;
      update(current);
      await persistStageEvidence("constraints", current);
      if (payload.formulation.formulationReady) recordOptimizationDecision("Optimization Constraints", "Generated rules approved", "Pending executable validation", "Approved and executable", `${payload.formulation.constraints.length} governed constraints validated against formulation ${payload.formulation.formulationId}.`);
      setMessage(payload.formulation.formulationReady ? "Executable demand, supply, transport-capacity, custom-policy, and route-bound rules validated." : "Executable rule validation identified blockers. Review the readiness evidence before continuing.");
    } catch (validationError) {
      update({ executableRulesValidated: false });
      setError(validationError instanceof Error ? validationError.message : "Executable rule validation failed.");
    } finally { setBusy(""); }
  };

  const generateImplementationPlan = () => {
    if (!state.result?.success) return;
    const patch: Partial<TransportationState> = {
      implementationOwner: state.implementationOwner || state.recommendationOwner || state.decisionOwner,
      routeExceptionProcess: "If a recommended supplier-to-customer route is unavailable, delayed, or operationally blocked, operations should record the exception, identify the affected supplier, customer, quantity, and reason, and use the approved fallback route or rerun the optimization with updated route availability and capacity assumptions. Exceptions should be reconciled against the optimized allocation plan before closeout.",
      fallbackPlan: "If the optimized allocation cannot be executed as approved, use the most recent feasible allocation plan as the fallback. If demand, supplier capacity, transport capacity, or route availability materially changes, rerun the Transportation / Logistics optimization before execution. For urgent disruptions, prioritize full demand coverage using available approved routes, then document cost variance and capacity exceptions.",
      monitoringMetrics: "Realized demand, actual shipped quantity, route cost variance, supplier utilization, transport utilization, unmet demand, override rate, exception count, late deliveries, failed deliveries, and cost overrun.",
      monitoringCadence: "Daily during execution; final reconciliation after completion",
      monitoringThresholds: state.monitoringThresholds.length ? state.monitoringThresholds : DEFAULT_TRANSPORTATION_MONITORING_THRESHOLDS.map((row) => ({ ...row })),
      reoptimizationTrigger: "Rerun the optimization if realized demand changes by more than 10%, transport capacity changes by more than 10%, a supplier becomes unavailable, a route is blocked, route costs materially change, unmet demand occurs, or scenario conditions resemble the infeasible severe-disruption case.",
      reconciliationProcess: "After execution, compare the approved allocation plan with actual shipped quantities, route usage, costs, exceptions, and unmet demand. Document variances by supplier, customer, and route. Confirm whether all demand was fulfilled, whether capacity limits were respected, and whether actual cost remained within the approved tolerance. Capture lessons learned and update assumptions before the next optimization cycle.",
    };
    update(patch);
    const current = { ...stateRef.current, ...patch } as TransportationState;
    void Promise.all([
      persistStageEvidence("implementation_plan", current),
      persistStageEvidence("monitoring_plan", current),
    ]);
    recordOptimizationDecision("Optimization Implementation", "Implementation plan completed", "Incomplete", "Plan complete", `Implementation owner ${current.implementationOwner} is accountable for route exceptions, fallback execution, reconciliation, monitoring, and re-optimization triggers.`, current.implementationOwner);
  };

  const captureOneOptimizationEvidence = async (
    stage: OptimizationEvidenceStage,
    current: TransportationState,
    status: "ready" | "accepted" = "ready",
  ) => {
    const definition = TRANSPORTATION_EVIDENCE_STAGES.find((row) => row.stage === stage);
    if (!definition) throw new Error(`Unknown optimization evidence stage: ${stage}.`);
    const capturedAt = new Date().toISOString();
    const evidence = await createEvidence({
      evidenceId: persistenceEvidenceId(projectId, stage),
      projectId,
      projectName,
      evidenceType: definition.evidenceType as EvidenceType,
      title: `Transportation Optimization: ${definition.label}`,
      summary: `${current.decisionTitle || "Transportation optimization"}. ${definition.label} evidence captured from the governed transportation workflow.`,
      sourcePage: `Optimization Step ${definition.stepNumber}`,
      sourceRoute: `/workflow/optimization/${definition.stepNumber}`,
      workflowStep: `${definition.stepNumber}. ${definition.label}`,
      sourceRunReference: current.result?.runId || current.formulation?.formulationId || projectId,
      artifactType: definition.evidenceType,
      artifactId: evidenceArtifactId(current, stage),
      datasetIds: current.formulation?.inputTables.map((row) => row.datasetId).filter((value): value is string => Boolean(value)) ?? [],
      modelIds: [],
      documentIds: stage === "documentation_package" ? [current.evidencePackageReference || `${projectId}:optimization-report`] : [],
      notebookIds: [],
      supportsSections: stage === "documentation_package" ? DOCUMENTATION_SECTIONS : definition.sections,
      tags: ["optimization", "transportation", stage, status === "accepted" ? "approved" : "captured"],
      status,
      importance: ["solution", "validation", "recommendation", "documentation_package"].includes(stage) ? "critical" : "high",
      capturedAt,
      lineage: {
        projectId,
        formulationId: current.formulation?.formulationId,
        normalizationHash: current.formulation?.normalizationHash,
        solutionId: current.result?.solutionId,
        runId: current.result?.runId,
      },
      payload: optimizationArtifactPayload(stage, current),
      governance: {
        accountableOwner: stage === "recommendation" ? current.recommendationOwner : current.decisionOwner,
        reviewer: current.reviewer,
        approvalDate: current.approvalDate,
        businessValidityStatus: current.result?.businessValidityStatus,
      },
    });
    await persistStageEvidence(stage, current, status === "accepted" ? "approved" : "ready");
    return evidence;
  };

  const persistReproducibilityExport = async (current: TransportationState) => {
    const generatedAt = new Date().toISOString();
    const fileName = `atlas-optimization-reproducibility-${projectId}.json`;
    const content = JSON.stringify(optimizationArtifactPayload("code_reproducibility", current));
    const artifactHash = await contentHash(content);
    await saveExportToDatabase(projectId, {
      exportId: `${projectId}:reproducibility_evidence`,
      exportType: "reproducibility_evidence",
      fileName,
      artifactHash,
      metadata: {
        delivery: "evidence_reference",
        clientOnly: true,
        fileExists: false,
        byteCount: new Blob([content], { type: "application/json" }).size,
        mimeType: "application/json",
        evidenceId: persistenceEvidenceId(projectId, "code_reproducibility"),
        formulationId: current.formulation?.formulationId,
        normalizationHash: current.formulation?.normalizationHash,
        solutionId: current.result?.solutionId,
        generatedAt,
      },
    });
  };

  const persistDocumentationPackage = async (current: TransportationState, status: "draft" | "ready" | "complete") => {
    const completedSections = optimizationDocumentationSectionCount(current);
    const now = new Date().toISOString();
    await saveDocumentationPackageToDatabase(projectId, {
      packageId: `${projectId}:optimization_study`,
      packageType: "optimization_study",
      status,
      readinessScore: status === "complete" ? 100 : Math.round((completedSections / DOCUMENTATION_SECTIONS.length) * 100),
      sectionCount: DOCUMENTATION_SECTIONS.length,
      completedSectionCount: status === "complete" ? DOCUMENTATION_SECTIONS.length : completedSections,
      createdAt: current.generatedReportAt || now,
      updatedAt: now,
      payload: {
        ...governedOptimizationPackage(projectId, projectName, modelId, current),
        report: current.generatedReport,
        sectionReadiness: DOCUMENTATION_SECTIONS.map((section, index) => ({
          index: index + 1,
          section,
          status: index < (status === "complete" ? DOCUMENTATION_SECTIONS.length : completedSections) ? "complete" : "pending",
        })),
        approvals: { reviewer: current.reviewer, approvalDate: current.approvalDate, recommendationStatus: current.recommendationStatus },
        reproducibilityAppendix: optimizationArtifactPayload("code_reproducibility", current),
      },
    });
  };

  const captureOptimizationEvidencePackage = async (current: TransportationState, final = false) => {
    const definitions = TRANSPORTATION_EVIDENCE_STAGES.filter((row) => optimizationStageGenerated(current, row.stage));
    const captured: Array<readonly [OptimizationEvidenceStage, string]> = [];
    for (const definition of definitions) {
      const evidence = await captureOneOptimizationEvidence(definition.stage, current, final && definition.stage === "documentation_package" ? "accepted" : "ready");
      captured.push([definition.stage, evidence.evidenceId] as const);
    }
    return Object.fromEntries(captured) as Record<string, string>;
  };

  const recordExport = async (
    kind: OptimizationExportKind,
    fileName: string,
    content: string,
    mimeType: string,
    evidenceType: EvidenceType = "export",
    supportsSections: string[] = ["Reproducibility Appendix"],
  ) => {
    const current = stateRef.current;
    const generatedAt = new Date().toISOString();
    const byteCount = new Blob([content], { type: mimeType }).size;
    const evidence = await createEvidence({
      evidenceId: persistenceEvidenceId(projectId, `export-${kind}`),
      projectId,
      projectName,
      evidenceType,
      title: `Transportation Optimization Export: ${fileName}`,
      summary: `${fileName} was generated from the current governed transportation formulation and solver state.`,
      sourcePage: "Optimization Documentation",
      sourceRoute: "/workflow/optimization/14",
      workflowStep: "14. Documentation",
      sourceRunReference: current.result?.runId || current.formulation?.formulationId || projectId,
      artifactType: `optimization_export_${kind}`,
      artifactId: `${projectId}:${kind}`,
      datasetIds: current.formulation?.inputTables.map((row) => row.datasetId).filter((value): value is string => Boolean(value)) ?? [],
      modelIds: [], documentIds: [], notebookIds: [],
      supportsSections,
      tags: ["optimization", "transportation", "export", kind],
      status: "ready",
      importance: kind === "optimization_report" ? "critical" : "high",
      capturedAt: generatedAt,
      lineage: { formulationId: current.formulation?.formulationId, normalizationHash: current.formulation?.normalizationHash, solutionId: current.result?.solutionId },
      payload: { fileName, mimeType, byteCount, generatedAt, kind },
      governance: { accountableOwner: current.recommendationOwner || current.decisionOwner, reviewer: current.reviewer },
    });
    const artifactHash = await contentHash(content);
    const exportType = kind === "sas_code" ? "sas_compatible_code" : kind;
    await saveExportToDatabase(projectId, {
      exportId: `${projectId}:${exportType}`,
      exportType,
      fileName,
      artifactHash,
      metadata: {
        delivery: "browser_download",
        clientOnly: true,
        fileExists: false,
        mimeType,
        byteCount,
        evidenceId: evidence.evidenceId,
        formulationId: current.formulation?.formulationId,
        normalizationHash: current.formulation?.normalizationHash,
        solutionId: current.result?.solutionId,
        generatedAt,
      },
    });
    const record: OptimizationExportRecord = {
      kind,
      fileName,
      artifactReference: `${kind}:${generatedAt}`,
      evidenceId: evidence.evidenceId,
      generatedAt,
      byteCount,
      status: "ready",
    };
    update({ exportArtifacts: { ...stateRef.current.exportArtifacts, [kind]: record } });
    downloadFile(fileName, content, mimeType);
    setMessage(`${fileName} generated and recorded as evidence ${evidence.evidenceId}.`);
    return record;
  };

  const exportAllocationCsv = async () => {
    setBusy("export"); setError(""); setMessage("");
    try {
      if (!stateRef.current.result?.decisionVector.length) throw new Error("Run a business-valid optimization before exporting the allocation.");
      await recordExport("allocation_csv", `atlas-transportation-allocation-${projectId}.csv`, allocationCsv(stateRef.current), "text/csv", "export", ["Optimization Results", "Implementation Plan"]);
    } catch (exportError) { setError(exportError instanceof Error ? exportError.message : "Allocation export failed."); }
    finally { setBusy(""); }
  };

  const exportGovernedPackage = async () => {
    setBusy("export"); setError(""); setMessage("");
    try {
      const content = JSON.stringify(governedOptimizationPackage(projectId, projectName, modelId, stateRef.current), null, 2);
      await recordExport("governed_json", `atlas-transportation-optimization-${projectId}.json`, content, "application/json", "export", DOCUMENTATION_SECTIONS);
    } catch (exportError) { setError(exportError instanceof Error ? exportError.message : "Governed package export failed."); }
    finally { setBusy(""); }
  };

  const exportPythonCode = async () => {
    setBusy("export"); setError(""); setMessage("");
    try {
      if (!stateRef.current.formulation) throw new Error("Build the transportation formulation before exporting Python code.");
      const generated = await generateTransportationCode({ ...requestInput, stage: "export" });
      update({ code: generated });
      await recordExport("python_code", `atlas-transportation-${projectId}.py`, generated.python.code, "text/x-python", "export", ["Python Code", "Reproducibility Appendix"]);
    } catch (exportError) { setError(exportError instanceof Error ? exportError.message : "Python export failed."); }
    finally { setBusy(""); }
  };

  const exportSasCode = async () => {
    setBusy("export"); setError(""); setMessage("");
    try {
      if (!stateRef.current.formulation) throw new Error("Build the transportation formulation before exporting SAS-compatible code.");
      const generated = await generateTransportationCode({ ...requestInput, stage: "export" });
      update({ code: generated });
      await recordExport("sas_code", `atlas-transportation-${projectId}.sas`, generated.sas.code, "text/plain", "export", ["SAS-Compatible Code", "Reproducibility Appendix"]);
    } catch (exportError) { setError(exportError instanceof Error ? exportError.message : "SAS-compatible export failed."); }
    finally { setBusy(""); }
  };

  const generateOptimizationReport = async () => {
    setBusy("report"); setError(""); setMessage("");
    try {
      const generatedAt = new Date().toISOString();
      const reportState = { ...stateRef.current, generatedReportAt: generatedAt };
      const report = buildOptimizationReport(projectId, projectName, reportState);
      const withReport = { ...reportState, generatedReport: report };
      stateRef.current = withReport;
      setState(withReport);
      const record = await recordExport("optimization_report", `atlas-optimization-report-${projectId}.md`, report, "text/markdown", "optimization_documentation_package", DOCUMENTATION_SECTIONS);
      const patch: Partial<TransportationState> = {
        generatedReport: report,
        generatedReportAt: generatedAt,
        evidenceByStep: { ...stateRef.current.evidenceByStep, documentation_package: record.evidenceId || "" },
        evidencePackageReference: record.evidenceId || stateRef.current.evidencePackageReference,
      };
      update(patch);
      const current = { ...stateRef.current, ...patch } as TransportationState;
      await Promise.all([
        persistStageEvidence("documentation_package", current, "ready"),
        persistDocumentationPackage(current, optimizationDocumentationSectionCount(current) === 20 ? "ready" : "draft"),
      ]);
    } catch (reportError) { setError(reportError instanceof Error ? reportError.message : "Optimization report generation failed."); }
    finally { setBusy(""); }
  };

  const completeOptimizationStudy = async () => {
    setBusy("evidence"); setError(""); setMessage("");
    try {
      const current = stateRef.current;
      const blocked = transportationStepGate(14, current);
      if (blocked) throw new Error(blocked);
      if (!current.formulation || !current.result) throw new Error("Evidence package is incomplete.");
      const completedAt = new Date().toISOString();
      const finalState = { ...current, studyCompleted: true, completedAt };
      const evidenceByStep = { ...current.evidenceByStep, ...(await captureOptimizationEvidencePackage(finalState, true)) };
      const packageReference = evidenceByStep.documentation_package || current.evidencePackageReference;
      const completed = { ...finalState, evidenceByStep, evidencePackageReference: packageReference };
      setState(completed);
      stateRef.current = completed;
      persistState(projectId, completed);
      queueOptimizationStateDatabaseSave(projectId, completed as unknown as Record<string, unknown>, { projectName, delayMs: 0 });
      await Promise.all([
        persistDocumentationPackage(completed, "complete"),
        persistStageEvidence("documentation_package", completed, "approved"),
        persistStageEvidence("code_reproducibility", completed, "approved"),
        persistReproducibilityExport(completed),
      ]);
      logDecision({
        workflowStep: "Optimization Documentation",
        actionType: "workflow_setting_changed",
        subject: "Transportation Optimization Study",
        previousValue: current.studyCompleted ? "Complete" : "In progress",
        newValue: "Complete | Audit package ready | Documentation finalized",
        systemRecommendation: "Complete the study only after validation, recommendation ownership, implementation planning, reproducibility evidence, final report inspection, and final review are documented.",
        followStatus: "followed",
        userReason: `Completed by ${current.reviewer} on ${completedAt}; approval date ${current.approvalDate}; evidence package ${packageReference}.`,
        owner: current.reviewer,
      });
      setMessage(`Optimization study completed. ${Object.keys(evidenceByStep).length} governed evidence references are available.`);
      return onComplete();
    } finally { setBusy(""); }
  };

  const captureRemainingEvidence = async () => {
    setBusy("evidence"); setError(""); setMessage("");
    try {
      const references = await captureOptimizationEvidencePackage(stateRef.current);
      update({
        evidenceByStep: { ...stateRef.current.evidenceByStep, ...references },
        evidencePackageReference: references.documentation_package || stateRef.current.evidencePackageReference,
      });
      if (references.code_reproducibility) await persistReproducibilityExport(stateRef.current);
      if (references.documentation_package) {
        await persistDocumentationPackage(
          stateRef.current,
          optimizationDocumentationSectionCount(stateRef.current) === 20 ? "ready" : "draft",
        );
      }
      setMessage(`${Object.keys(references).length} generated optimization artifacts are captured and ready in Model Evidence Center.`);
    } catch (evidenceError) { setError(evidenceError instanceof Error ? evidenceError.message : "Optimization evidence capture failed."); }
    finally { setBusy(""); }
  };

  const captureEvidence = async (stage = STEP_EVIDENCE_STAGE[stepNumber - 1]) => {
    setBusy("evidence"); setError(""); setMessage("");
    try {
      const normalizedStage = stage as OptimizationEvidenceStage;
      if (!optimizationStageGenerated(stateRef.current, normalizedStage)) throw new Error(`Complete the ${stage.replace(/_/g, " ")} workflow state before capturing its evidence.`);
      const evidence = await captureOneOptimizationEvidence(normalizedStage, stateRef.current);
      update({ evidenceByStep: { ...stateRef.current.evidenceByStep, [normalizedStage]: evidence.evidenceId } });
      if (normalizedStage === "code_reproducibility") await persistReproducibilityExport(stateRef.current);
      if (normalizedStage === "documentation_package") {
        await persistDocumentationPackage(
          stateRef.current,
          optimizationDocumentationSectionCount(stateRef.current) === 20 ? "ready" : "draft",
        );
      }
      setMessage(`${stage.replace(/_/g, " ")} evidence captured as ${evidence.evidenceId}.`);
    } catch (evidenceError) {
      setError(evidenceError instanceof Error ? evidenceError.message : "Evidence capture failed.");
    } finally { setBusy(""); }
  };

  const runCode = async () => {
    const code = state.userPythonByStep[String(stepNumber)] || state.code?.python.code || "";
    if (!code) return;
    setBusy("code"); setCodeResult(null);
    try { setCodeResult(await runUserPython({ code, projectId, workflowStep: `optimization-${stepNumber}`, context: { formulationId: state.formulation?.formulationId } })); }
    finally { setBusy(""); }
  };

  const saveCodeToNotebook = (language: "python" | "sas") => {
    const key = `optimization-${projectId}-step-${stepNumber}`;
    const code = language === "python" ? state.userPythonByStep[String(stepNumber)] || state.code?.python.code || "" : state.userSasByStep[String(stepNumber)] || state.code?.sas.code || "";
    codeStorageWrite(language === "python" ? USER_STEP_PYTHON_CODE_KEY : USER_STEP_SAS_CODE_KEY, key, code);
    setMessage(`${language === "python" ? "Python" : "SAS-compatible"} code added to the governed notebook export.`);
  };

  const validationCount = state.validation?.passedCount ?? 0;
  const completedThrough = workflowSteps.reduce((count, workflowStep) => (
    count === Number(workflowStep.id.split("-").pop() || "0") - 1 && workflowStep.status === "complete"
      ? count + 1
      : count
  ), 0);
  const disabledReason = transportationStepGate(stepNumber, state);
  const heroMetrics = [
    { label: "Template", value: "Transportation", detail: "Multi-table LP", tone: "info" as const },
    { label: "Routes", value: state.formulation?.metrics.routeCount ?? 0, detail: state.formulation ? `${state.formulation.metrics.supplierCount} suppliers x ${state.formulation.metrics.customerCount} customers` : "Not normalized", tone: state.formulation?.formulationReady ? "success" as const : "neutral" as const },
    { label: "Demand", value: state.formulation ? formatTransportationValue(state.formulation.metrics.totalDemand, 0) : "Not loaded", detail: state.result ? `${formatTransportationValue(state.result.demandFulfilled, 0)} fulfilled` : "Awaiting solve", tone: state.result?.success ? "success" as const : "neutral" as const },
    { label: "Decision status", value: state.result?.decisionReadiness ?? "Not solved", detail: state.result?.businessValidityStatus ?? "Business validity pending", tone: state.result?.success ? "success" as const : state.result ? "danger" as const : "neutral" as const },
  ];

  const pageContext: PageContext = {
    projectId, stepNumber, state, update, datasets, busy, requestInput,
    onStrategyChange, assignDataset, uploadRole, uploadBundle, autoAssignRegistered,
    buildFormulation, runSolve, runScenarios, runSensitivity, runValidation,
    setRouteActive, addCustomConstraint, setCustomConstraint, applyCharter,
    validateExecutableRules, generateRecommendation, generateImplementationPlan,
    exportAllocationCsv, exportGovernedPackage, exportPythonCode, exportSasCode,
    generateOptimizationReport, captureRemainingEvidence, captureEvidence,
  };
  const currentEvidenceStage = STEP_EVIDENCE_STAGE[stepNumber - 1];
  const resultEvidenceStages = new Set(["solution", "sensitivity", "validation", "recommendation"]);
  const evidenceDisabled = busy === "evidence" || (stepNumber > 1 && !state.formulation) || (resultEvidenceStages.has(currentEvidenceStage) && !state.result?.success);

  return (
    <StepShell
      title={`Step ${stepNumber}: ${step.label}`}
      subtitle={step.description}
      eyebrow="ATLAS Decision Science / Transportation Optimization"
      variant="modeling"
      heroMetrics={heroMetrics}
      nextLabel={stepNumber === 3 ? "Confirm and Continue to Objective Function" : nextStep ? `Continue to ${nextStep.label}` : "Complete Optimization Study"}
      nextPath={nextStep?.route ?? "/project-overview"}
      nextDisabled={Boolean(disabledReason)}
      nextDisabledReason={disabledReason}
      onNext={async () => {
        if (stepNumber === 14) return completeOptimizationStudy();
        const compact = persistState(projectId, stateRef.current);
        queueOptimizationStateDatabaseSave(projectId, compact as unknown as Record<string, unknown>, { projectName, delayMs: 0 });
        const generatedStages = TRANSPORTATION_EVIDENCE_STAGES.filter(
          (definition) => definition.stepNumber === stepNumber && optimizationStageGenerated(stateRef.current, definition.stage),
        );
        await Promise.all(generatedStages.map((definition) => persistStageEvidence(definition.stage, stateRef.current)));
        return onComplete();
      }}
    >
      <div className="space-y-4">
        <TransportationLifecycleMap currentStep={stepNumber} completedThrough={completedThrough} evidenceSteps={[...new Set(TRANSPORTATION_EVIDENCE_STAGES.filter((definition) => state.evidenceByStep[definition.stage]).map((definition) => definition.stepNumber))]} />
        <AtlasStatusStrip label="Transportation decision status" items={[
          { label: "Input bundle", state: state.formulation?.fullArtifact ? "complete" : "pending", detail: `${REQUIRED_TRANSPORTATION_ROLES.filter((role) => state.bundle[role]?.datasetId).length}/${REQUIRED_TRANSPORTATION_ROLES.length} required` },
          { label: "Formulation", state: state.formulation?.formulationReady ? "complete" : state.formulation ? "warning" : "pending", detail: state.formulation ? `${state.formulation.metrics.decisionVariableCount} route variables` : "Not built" },
          { label: "Solution", state: state.result?.success ? "complete" : state.result ? "blocked" : "pending", detail: state.result?.businessValidityStatus ?? "Not solved" },
          { label: "Validation", state: state.validation?.recommendationAllowed ? "complete" : validationCount ? "warning" : "pending", detail: state.validation ? `${state.validation.score}%` : "Not run" },
        ]} />
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-slate-200 bg-white px-4 py-3 shadow-sm">
          <div><div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Evidence checkpoint</div><div className="mt-0.5 text-sm text-slate-700">Capture the governed {currentEvidenceStage.replace(/_/g, " ")} artifact for this workflow stage.</div></div>
          <button type="button" disabled={evidenceDisabled} onClick={() => void captureEvidence(currentEvidenceStage)} className="atlas-secondary-button inline-flex items-center gap-2"><ShieldCheck size={15} /> {state.evidenceByStep[currentEvidenceStage] ? "Recapture stage evidence" : "Capture stage evidence"}</button>
        </div>
        {(error || navigationError) && <AtlasAttentionPanel title="Optimization action required" tone="danger">{error || navigationError}</AtlasAttentionPanel>}
        {message && <div className="flex items-start gap-2 rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-950"><CheckCircle2 size={17} className="mt-0.5 shrink-0" />{message}</div>}
        {renderPage(pageContext)}
        <TransportationCodePanel
          projectId={projectId}
          stepNumber={stepNumber}
          state={state}
          update={update}
          busy={busy}
          codeResult={codeResult}
          runCode={runCode}
          saveCodeToNotebook={saveCodeToNotebook}
          exportPythonCode={exportPythonCode}
          exportSasCode={exportSasCode}
          captureEvidence={() => void captureEvidence("code_reproducibility")}
        />
      </div>
    </StepShell>
  );
}

type PageContext = {
  projectId: string;
  stepNumber: number;
  state: TransportationState;
  update: (patch: Partial<TransportationState>) => void;
  datasets: DatasetSummary[];
  busy: BusyAction;
  requestInput: {
    bundle: TransportationInputBundle;
    mapping: Record<string, string>;
    routeOverrides: Record<string, boolean>;
    customConstraints: Array<Omit<CustomConstraint, "formula">>;
    solver: { method: string; tolerance: number; timeLimitSeconds: number };
  };
  onStrategyChange: (strategy: OptimizationInputStrategy) => void;
  assignDataset: (role: TransportationBundleRole, datasetId: string) => void;
  uploadRole: (role: TransportationBundleRole, event: ChangeEvent<HTMLInputElement>) => Promise<void>;
  uploadBundle: (event: ChangeEvent<HTMLInputElement>) => Promise<void>;
  autoAssignRegistered: () => void;
  buildFormulation: () => Promise<void>;
  runSolve: () => Promise<void>;
  runScenarios: () => Promise<void>;
  runSensitivity: () => Promise<void>;
  runValidation: () => Promise<void>;
  validateExecutableRules: () => Promise<void>;
  setRouteActive: (routeId: string, active: boolean) => void;
  addCustomConstraint: () => void;
  setCustomConstraint: (index: number, patch: Partial<CustomConstraint>) => void;
  applyCharter: () => void;
  generateRecommendation: () => void;
  generateImplementationPlan: () => void;
  exportAllocationCsv: () => Promise<void>;
  exportGovernedPackage: () => Promise<void>;
  exportPythonCode: () => Promise<void>;
  exportSasCode: () => Promise<void>;
  generateOptimizationReport: () => Promise<void>;
  captureRemainingEvidence: () => Promise<void>;
  captureEvidence: (stage?: string) => Promise<void>;
};

function renderPage(context: PageContext) {
  if (context.stepNumber === 1) return <ContextPage context={context} />;
  if (context.stepNumber === 2) return <InputBundlePage context={context} />;
  if (context.stepNumber === 3) return <ReadinessPage context={context} />;
  if (context.stepNumber === 4) return <ObjectivePage context={context} />;
  if (context.stepNumber === 5) return <VariablesPage context={context} />;
  if (context.stepNumber === 6) return <ConstraintsPage context={context} />;
  if (context.stepNumber === 7) return <SolverPage context={context} />;
  if (context.stepNumber === 8) return <ScenariosPage context={context} />;
  if (context.stepNumber === 9) return <OptimizePage context={context} />;
  if (context.stepNumber === 10) return <SensitivityPage context={context} />;
  if (context.stepNumber === 11) return <ValidationPage context={context} />;
  if (context.stepNumber === 12) return <RecommendationPage context={context} />;
  if (context.stepNumber === 13) return <ImplementationPage context={context} />;
  return <DocumentationPage context={context} />;
}

function StrategySelector({ selected, onChange }: { selected: OptimizationInputStrategy; onChange: (strategy: OptimizationInputStrategy) => void }) {
  const rows = Object.values(OPTIMIZATION_TEMPLATE_REGISTRY);
  return <div className="grid gap-3 lg:grid-cols-3">{rows.map((row) => {
    const active = selected === row.template_id;
    return <button key={row.template_id} type="button" onClick={() => onChange(row.template_id)} className={`min-h-28 rounded-lg border p-4 text-left transition ${active ? "border-blue-500 bg-blue-50 shadow-sm ring-2 ring-blue-100" : "border-slate-200 bg-white hover:border-blue-300 hover:bg-slate-50"}`}><div className="flex items-center justify-between gap-3"><span className="font-semibold text-slate-950">{row.display_name}</span>{active && <CheckCircle2 size={17} className="text-blue-600" />}</div><p className="mt-2 text-xs leading-5 text-slate-600">{row.short_description}</p><div className="mt-3 text-[10px] font-semibold uppercase tracking-wide text-slate-500">{row.required_input_roles.length} required | {row.optional_input_roles.length} optional</div></button>;
  })}</div>;
}

function ContextPage({ context }: { context: PageContext }) {
  const { state, update, onStrategyChange, applyCharter, captureEvidence, busy } = context;
  return <div className="space-y-4">
    <AtlasWorkflowSection eyebrow="Input strategy" title="Choose the optimization formulation" description="The selected template controls required datasets, variable grain, constraints, solver checks, scenarios, and evidence." tone="info"><StrategySelector selected={state.templateId} onChange={onStrategyChange} /></AtlasWorkflowSection>
    <div className="grid gap-4 xl:grid-cols-[1.2fr_0.8fr]">
      <AtlasWorkflowSection eyebrow="Decision charter" title="Define the operational decision" description="A defensible optimization starts with the decision, accountable owner, scope, cadence, and non-negotiable governance boundary." tone="neutral" action={<button type="button" className="atlas-secondary-button inline-flex items-center gap-2" onClick={applyCharter}><Sparkles size={15} /> Apply transportation charter</button>}>
        <div className="grid gap-4 md:grid-cols-2"><TextField label="Optimization decision" value={state.decisionTitle} onChange={(value) => update({ decisionTitle: value })} /><TextField label="Decision owner" value={state.decisionOwner} onChange={(value) => update({ decisionOwner: value })} /><TextArea label="Business objective" value={state.businessObjective} onChange={(value) => update({ businessObjective: value })} /><TextArea label="Eligible population / scope" value={state.population} onChange={(value) => update({ population: value })} /><SelectField label="Decision cadence" value={state.decisionCadence} options={["One-time decision", "Daily", "Weekly", "Monthly", "Quarterly", "Event triggered"]} onChange={(value) => update({ decisionCadence: value })} guidance="Choose the cadence at which operations can refresh inputs and implement a new allocation." /><TextArea label="Governance boundary" value={state.governanceBoundary} onChange={(value) => update({ governanceBoundary: value })} /></div>
      </AtlasWorkflowSection>
      <AtlasWorkflowSection eyebrow="Decision standard" title="Required proof" tone="success"><Checklist items={["The objective represents the real operational cost.", "Demand is enforced as an equality unless shortage is explicitly approved.", "Supply and transportation limits are executable constraints.", "The allocation is nonnegative, reproducible, and business-valid.", "Stress results, sensitivity, ownership, and fallback controls are documented."]} /><button type="button" disabled={busy === "evidence" || !state.decisionTitle} onClick={() => void captureEvidence("decision_charter")} className="atlas-secondary-button mt-4 inline-flex items-center gap-2"><Save size={15} /> Capture decision charter</button></AtlasWorkflowSection>
    </div>
  </div>;
}

function InputBundlePage({ context }: { context: PageContext }) {
  const { state, datasets, busy, assignDataset, uploadRole, uploadBundle, autoAssignRegistered, buildFormulation, update } = context;
  const profileByRole = new Map((state.formulation?.inputTables ?? []).map((row) => [row.role, row]));
  const labels = Object.fromEntries(datasets.map((dataset) => [dataset.datasetId, `${dataset.name} (${dataset.latestVersion?.rowCount.toLocaleString() ?? 0} rows)`]));
  const requiredAssigned = REQUIRED_TRANSPORTATION_ROLES.filter((role) => Boolean(state.bundle[role]?.datasetId)).length;
  const optionalAssigned = OPTIONAL_TRANSPORTATION_ROLES.filter((role) => Boolean(state.bundle[role]?.datasetId)).length;
  const inventorySupplied = Boolean(state.bundle.inventoryCost?.datasetId);
  return <div className="space-y-4">
    <AtlasWorkflowSection eyebrow="Active optimization template" title={TRANSPORTATION_TEMPLATE.display_name} description="Build a governed supplier-to-customer allocation from a route cost matrix, customer demand, supplier supply maximum, transport capacity, and optional inventory or handling cost." tone="success">
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        <div className="rounded-lg border border-emerald-200 bg-white p-3"><Meta label="Decision grain" value={TRANSPORTATION_TEMPLATE.expected_decision_grain} /></div>
        <div className="rounded-lg border border-emerald-200 bg-white p-3"><Meta label="Objective" value={`${TRANSPORTATION_TEMPLATE.default_objective_direction}: ${TRANSPORTATION_TEMPLATE.guide_context.objective}`} /></div>
        <div className="rounded-lg border border-emerald-200 bg-white p-3"><Meta label="Default solver" value={TRANSPORTATION_TEMPLATE.default_solver} /></div>
        <div className="rounded-lg border border-emerald-200 bg-white p-3"><Meta label="Generated rules" value={TRANSPORTATION_TEMPLATE.generated_constraint_groups.join(", ")} /></div>
      </div>
      <p className="mt-3 text-sm leading-6 text-emerald-950">This template creates supplier-to-customer route variables, demand fulfillment constraints, supplier supply constraints, transport-capacity constraints, and transportation-specific scenario and sensitivity outputs.</p>
    </AtlasWorkflowSection>
    <div className="grid gap-4 xl:grid-cols-[1.45fr_0.55fr]">
      <AtlasWorkflowSection eyebrow="Governed input bundle" title="Assign template-defined input roles" description="Four full registered artifacts are required. Inventory or handling cost is optional. Full-artifact browser previews are not used to formulate, solve, stress, validate, or evidence this decision." tone="info" action={<div className="flex flex-wrap gap-2"><button type="button" onClick={autoAssignRegistered} className="atlas-secondary-button inline-flex items-center gap-2"><RefreshCw size={15} /> Match registered files</button><label className="atlas-primary-button inline-flex cursor-pointer items-center gap-2"><Upload size={15} /> Upload all input files<input type="file" accept=".csv,.txt" multiple className="hidden" onChange={(event) => void uploadBundle(event)} /></label></div>}>
        <div className="grid gap-3 md:grid-cols-2">
          {TRANSPORTATION_ROLE_CONFIG.map((roleDefinition) => {
            const role = roleDefinition.bundle_key;
            const reference = state.bundle[role];
            const selected = datasets.find((row) => row.datasetId === reference.datasetId);
            const profile = profileByRole.get(role);
            const ready = Boolean(reference.datasetId);
            const missingOptional = roleDefinition.requirement === "optional" && !ready;
            return <article key={role} className={`rounded-lg border p-4 ${profile?.profileStatus === "ready" ? "border-emerald-200 bg-emerald-50/60" : ready ? "border-blue-200 bg-blue-50/50" : missingOptional ? "border-slate-200 bg-slate-50" : "border-amber-200 bg-amber-50/50"}`}>
              <div className="flex items-start justify-between gap-3"><div><div className="flex flex-wrap items-center gap-2"><h3 className="text-sm font-semibold text-slate-950">{roleDefinition.display_name}</h3><span className={`rounded-md border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${roleDefinition.requirement === "required" ? "border-blue-200 bg-blue-50 text-blue-800" : "border-slate-200 bg-white text-slate-600"}`}>{roleDefinition.requirement}</span></div><p className="mt-2 text-xs leading-5 text-slate-600">{roleDefinition.purpose}</p></div>{ready ? <CheckCircle2 size={18} className="shrink-0 text-emerald-600" /> : roleDefinition.requirement === "required" ? <AlertTriangle size={18} className="shrink-0 text-amber-600" /> : <Database size={18} className="shrink-0 text-slate-400" />}</div>
              <div className="mt-3 rounded-md border border-slate-200 bg-white/80 p-3"><div className="text-[10px] font-semibold uppercase tracking-wide text-slate-500">Accepted shapes</div><ul className="mt-1 grid gap-1 text-xs leading-5 text-slate-700">{roleDefinition.accepted_shapes.map((shape) => <li key={shape}>- {shape}</li>)}</ul></div>
              <div className="mt-3 grid gap-2"><select aria-label={`${roleDefinition.display_name} selected dataset`} className={fieldClass()} value={reference.datasetId} onChange={(event) => assignDataset(role, event.target.value)}><option value="">Select registered dataset</option>{datasets.map((dataset) => <option key={dataset.datasetId} value={dataset.datasetId}>{labels[dataset.datasetId]}</option>)}</select><label className="inline-flex cursor-pointer items-center gap-2 text-xs font-semibold text-blue-700"><Upload size={14} /> Upload only this input role<input type="file" accept=".csv,.txt" className="hidden" onChange={(event) => void uploadRole(role, event)} /></label></div>
              <dl className="mt-3 grid grid-cols-2 gap-2 border-t border-slate-200 pt-3 text-xs"><Meta label="Input role" value={roleDefinition.role_id} /><Meta label="Selected dataset" value={selected?.name ?? "Not assigned"} /><Meta label="Rows" value={(profile?.rowCount ?? selected?.latestVersion?.rowCount)?.toLocaleString() ?? "Not loaded"} /><Meta label="Columns" value={profile?.columnCount ?? selected?.latestVersion?.columnCount ?? "Not loaded"} /><Meta label="Detected keys" value={profile?.keyColumns.join(", ") || roleDefinition.detected_key_hints.join(", ")} /><Meta label="Mapping confidence" value={mappingConfidence(profile?.schemaConfidence)} /><Meta label="Validation" value={profile?.profileStatus ?? (ready ? "Pending normalization" : roleDefinition.requirement === "required" ? "Required" : "Optional")} /><Meta label="Evidence role" value={roleDefinition.evidence_role} /><Meta label="Evidence status" value={profile?.evidenceStatus.replace(/_/g, " ") ?? "Not captured"} /></dl>
            </article>;
          })}
        </div>
        {!inventorySupplied && <div className="mt-4 rounded-lg border border-blue-200 bg-blue-50 px-4 py-3 text-sm leading-6 text-blue-950">Inventory or handling cost was not supplied. The objective will use route transportation cost only.</div>}
        <div className="mt-4 flex items-center justify-between gap-4 border-t border-slate-200 pt-4"><p className="text-sm text-slate-600">{requiredAssigned} of {REQUIRED_TRANSPORTATION_ROLES.length} required inputs assigned. {optionalAssigned} of {OPTIONAL_TRANSPORTATION_ROLES.length} optional inputs assigned. Normalization creates one decision variable for every valid supplier-customer route.</p><button type="button" disabled={busy === "formulate" || requiredAssigned !== REQUIRED_TRANSPORTATION_ROLES.length} onClick={() => void buildFormulation()} className="atlas-primary-button inline-flex shrink-0 items-center gap-2">{busy === "formulate" ? <LoaderCircle size={16} className="animate-spin" /> : <GitBranch size={16} />} Normalize and validate bundle</button></div>
      </AtlasWorkflowSection>
      <InputBundleCompletenessChart bundle={state.bundle} template={TRANSPORTATION_TEMPLATE} roles={TRANSPORTATION_ROLE_CONFIG} evidenceCaptured={Boolean(state.evidenceByStep.input_bundle)} />
    </div>
    {state.formulation && <><AtlasWorkflowSection eyebrow="Normalization summary" title="Governed route model created" tone="success"><KpiGrid rows={[["Customers", state.formulation.metrics.customerCount], ["Suppliers", state.formulation.metrics.supplierCount], ["Routes created", state.formulation.metrics.routeCount], ["Required inputs loaded", `${requiredAssigned} of ${REQUIRED_TRANSPORTATION_ROLES.length}`], ["Optional inputs loaded", `${optionalAssigned} of ${OPTIONAL_TRANSPORTATION_ROLES.length}`], ["Missing route costs", state.formulation.metrics.missingRouteCosts], ["Duplicate keys", state.formulation.metrics.duplicateRoutes], ["Ready for formulation", state.formulation.formulationReady ? "Yes" : "No"]]} /></AtlasWorkflowSection><RouteMatrixChart formulation={state.formulation} mode="cost" activeOverrides={state.routeOverrides} exclusionRationales={state.routeExclusionRationales} /><AtlasWorkflowSection eyebrow="Detected mapping" title="Template-specific mapping controls" description="ATLAS detected these keys and values. Override a field only when source naming is ambiguous." tone="neutral"><div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">{Object.entries(state.formulation.resolvedMapping).filter(([, value]) => typeof value === "string").map(([key, value]) => <SelectField key={key} label={key.replace(/([A-Z])/g, " $1")} value={state.mapping[key] || String(value)} options={state.formulation?.inputTables.flatMap((row) => row.columns ?? []) ?? []} onChange={(next) => update({ mapping: { ...state.mapping, [key]: next }, formulation: null, formulationConfirmed: false })} guidance="Use the detected column unless domain knowledge confirms a different business key or value field." />)}</div></AtlasWorkflowSection></>}
  </div>;
}

function ReadinessPage({ context }: { context: PageContext }) {
  const { state, update, buildFormulation, busy } = context;
  const formulation = state.formulation;
  if (!formulation) return <EmptyState title="Route-level formulation is not available" body="Return to Data Acquisition, assign the four required template inputs, and normalize the input bundle." action={<button type="button" onClick={() => void buildFormulation()} className="atlas-primary-button">Build formulation</button>} />;
  const passCount = formulation.readinessChecks.filter((check) => check.status === "pass").length;
  const generatedObjects = `${formulation.metrics.decisionVariableCount} variables, ${formulation.constraints.length} constraints`;
  return <div className="space-y-4">
    <AtlasWorkflowSection eyebrow="Governed formulation gate" title="Confirm the normalized transportation input bundle" description="Confirm the normalized transportation input bundle before ATLAS creates the mathematical objective, decision variables, and generated constraints." tone={formulation.formulationReady ? "success" : "danger"} action={<AtlasDataScopeBadge scope="full_dataset" rows={formulation.metrics.routeCount} />}>
      <p className="mb-4 max-w-4xl text-sm leading-6 text-slate-700">This checkpoint verifies that the registered source tables form one coherent transportation network. It does not approve the objective or business rules yet.</p>
      <div className="grid gap-3 md:grid-cols-3">
        <ResultKpi label="Input completeness" value={formulation.fullArtifact ? "4 required artifacts" : "Blocked"} detail={`${formulation.inputTables.length} registered table profiles`} tone={formulation.fullArtifact ? "success" : "danger"} />
        <ResultKpi label="Feasibility" value={formulation.formulationReady ? "Ready" : "Review required"} detail={`${passCount} of ${formulation.readinessChecks.length} checks pass`} tone={formulation.formulationReady ? "success" : "danger"} />
        <ResultKpi label="Objects generated next" value={generatedObjects} detail="Objective, variables, and constraint groups" tone="neutral" />
      </div>
      <div className="mt-4 grid gap-2 md:grid-cols-2">{formulation.readinessChecks.map((check) => <div key={check.id} className={`flex items-start gap-2 rounded-lg border px-3 py-3 text-sm ${check.status === "pass" ? "border-emerald-200 bg-emerald-50 text-emerald-900" : check.status === "warning" ? "border-amber-200 bg-amber-50 text-amber-900" : "border-red-200 bg-red-50 text-red-900"}`}>{check.status === "pass" ? <CheckCircle2 size={16} className="mt-0.5 shrink-0" /> : <AlertTriangle size={16} className="mt-0.5 shrink-0" />}<div><div className="font-semibold">{check.label}</div><div className="mt-1 text-xs leading-5 opacity-80">{check.detail}</div></div></div>)}</div>
      <label className={`mt-4 flex cursor-pointer items-start gap-3 rounded-lg border p-4 ${state.formulationConfirmed ? "border-emerald-300 bg-emerald-50" : "border-blue-200 bg-blue-50"}`}><input type="checkbox" checked={state.formulationConfirmed} disabled={!formulation.formulationReady} onChange={(event) => update({ formulationConfirmed: event.target.checked })} className="mt-1 h-4 w-4 accent-emerald-600" /><span><span className="block font-semibold text-slate-950">Confirm formulation-ready inputs</span><span className="mt-1 block text-sm leading-6 text-slate-600">I confirm the normalized transportation input bundle and reviewed source versions, detected mappings, normalized routes, totals, missing values, duplicates, and aggregate feasibility evidence.</span></span></label>
    </AtlasWorkflowSection>
    <div className="grid gap-4 xl:grid-cols-2"><DemandCapacityChart formulation={formulation} /><ConstraintReadinessChart formulation={formulation} /></div>
  </div>;
}

function ObjectivePage({ context }: { context: PageContext }) {
  const { state, update } = context; const f = state.formulation;
  if (!f) return <MissingFormulation />;
  const inventorySupplied = Boolean(state.bundle.inventoryCost?.datasetId);
  const unitCosts = f.routes.map((route) => route.total_unit_cost).filter((value): value is number => typeof value === "number");
  const lowCost = unitCosts.length ? Math.min(...unitCosts) : 0;
  const highCost = unitCosts.length ? Math.max(...unitCosts) : 0;
  const expression = inventorySupplied
    ? "min sum(supplier, customer) x_supplier_customer * (transportation_cost_supplier_customer + inventory_cost_supplier)"
    : "min sum(supplier, customer) x_supplier_customer * transportation_cost_supplier_customer";
  return <div className="space-y-4">
    <div className="grid gap-4 xl:grid-cols-[1fr_0.8fr]">
      <AtlasWorkflowSection eyebrow="Template-aware objective" title="Minimize total cash distribution cost" description={inventorySupplied ? "The objective is assembled from route-level transportation cost plus supplier inventory or handling cost." : "The optional inventory or handling cost input was not supplied, so the objective uses route transportation cost only."} tone="info">
        <div className="grid gap-4 md:grid-cols-2"><TextField label="Objective name" value={state.objectiveName} onChange={(value) => update({ objectiveName: value })} /><TextField label="Objective unit" value={state.objectiveUnit} onChange={(value) => update({ objectiveUnit: value })} /><TextField label="Optimization horizon" value={state.horizon} onChange={(value) => update({ horizon: value })} /><TextArea label="Current-state baseline" value={state.baselineDescription} onChange={(value) => update({ baselineDescription: value })} /></div>
      </AtlasWorkflowSection>
      <AtlasWorkflowSection eyebrow="Mathematical expression" title="Route-level minimization" tone="success">
        <div className="mb-3 inline-flex rounded-full border border-emerald-300 bg-emerald-100 px-3 py-1 text-xs font-bold uppercase text-emerald-800">Minimize</div>
        <div className="rounded-lg border border-emerald-200 bg-emerald-50 p-4 font-mono text-sm leading-7 text-emerald-950">{expression}</div>
        <p className="mt-3 text-sm leading-6 text-slate-700">{f.objective.plainEnglish}</p>
        <dl className="mt-3 grid gap-2 text-xs"><Meta label="Route cost source" value="Route cost matrix" /><Meta label="Inventory cost source" value={inventorySupplied ? "Inventory or handling cost table" : "Not supplied; defaulted to 0"} /><Meta label="Total unit cost" value={inventorySupplied ? "Transportation cost + supplier inventory or handling cost" : "Transportation cost only"} /></dl>
      </AtlasWorkflowSection>
    </div>
    <div className="grid gap-4 xl:grid-cols-[1.2fr_0.8fr]">
      <AtlasWorkflowSection eyebrow="Coefficient evidence" title="Objective coefficient preview"><DataTable headers={["Supplier", "Customer", "Transport cost", "Inventory cost", "Total unit cost", "Variable"]} rows={f.routes.map((route) => [route.supplier, route.customer, formatTransportationValue(route.transportation_cost), formatTransportationValue(route.inventory_cost), formatTransportationValue(route.total_unit_cost), route.variable_name])} /></AtlasWorkflowSection>
      <div className="space-y-3"><ObjectiveDistributionChart formulation={f} /><div className="rounded-lg border border-blue-200 bg-blue-50 p-4 text-sm leading-6 text-blue-950"><strong>ATLAS interpretation:</strong> Route unit costs range from {formatTransportationValue(lowCost)} to {formatTransportationValue(highCost)}. Lower-cost routes are likely to be favored unless supplier supply or transport-capacity constraints bind.</div></div>
    </div>
  </div>;
}

function VariablesPage({ context }: { context: PageContext }) {
  const { state, update, setRouteActive } = context; const f = state.formulation;
  if (!f) return <MissingFormulation />;
  const active = f.routes.filter((route) => state.routeOverrides[route.route_id] !== false).length;
  const excluded = f.routes.length - active;
  return <div className="space-y-4"><AtlasWorkflowSection eyebrow="Route-level variable contract" title={`Review ${f.metrics.routeCount} continuous shipment decisions`} description="Each supplier-to-customer route is a nonnegative continuous quantity. Excluding a route changes the feasible network and requires a documented rationale." tone="info"><KpiGrid rows={[["Suppliers", f.metrics.supplierCount], ["Customers", f.metrics.customerCount], ["Eligible routes", f.metrics.routeCount], ["Active routes", active], ["Excluded routes", excluded], ["Continuous variables", f.metrics.routeCount], ["Integer variables", 0], ["Non-negativity bounds", f.metrics.nonNegativityBoundCount]]} /></AtlasWorkflowSection><RouteMatrixChart formulation={f} mode="variables" activeOverrides={state.routeOverrides} exclusionRationales={state.routeExclusionRationales} /><AtlasWorkflowSection eyebrow="Executable variable table" title="Route decisions and coefficient lineage" description="Active route selections propagate to constraints, solve, scenarios, sensitivity, evidence, and documentation."><DataTable headers={["Use", "Variable", "Supplier", "Customer", "Lower", "Upper", "Type", "Transport", "Inventory", "Unit cost", "Source tables", "Status"]} rows={f.routes.map((route) => [<input key={route.route_id} aria-label={`Use ${route.variable_name}`} type="checkbox" checked={state.routeOverrides[route.route_id] !== false} onChange={(event) => setRouteActive(route.route_id, event.target.checked)} className="h-4 w-4 accent-blue-600" />, route.variable_name, route.supplier, route.customer, route.lower_bound, state.routeOverrides[route.route_id] === false ? 0 : "No route cap", "Continuous", formatTransportationValue(route.transportation_cost), formatTransportationValue(route.inventory_cost), formatTransportationValue(route.total_unit_cost), route.source_tables.join(", "), state.routeOverrides[route.route_id] === false ? "Excluded" : "Ready"]) } /></AtlasWorkflowSection>{excluded > 0 && <AtlasWorkflowSection eyebrow="Required exclusion evidence" title="Document every excluded route" tone={excludedRouteRationalesComplete(state) ? "success" : "warning"}><div className="grid gap-3 md:grid-cols-2">{f.routes.filter((route) => state.routeOverrides[route.route_id] === false).map((route) => <label key={route.route_id} className="rounded-lg border border-amber-200 bg-amber-50 p-3"><span className="text-sm font-semibold text-slate-950">{route.supplier} to {route.customer} | {route.variable_name}</span><textarea rows={3} value={state.routeExclusionRationales[route.route_id] ?? ""} onChange={(event) => update({ routeExclusionRationales: { ...state.routeExclusionRationales, [route.route_id]: event.target.value } })} placeholder="Required: explain the operational, policy, data-quality, or route-availability reason for exclusion." className={`${fieldClass()} mt-2`} /></label>)}</div></AtlasWorkflowSection>}</div>;
}

function ConstraintsPage({ context }: { context: PageContext }) {
  const { state, addCustomConstraint, setCustomConstraint, update, validateExecutableRules, busy } = context; const f = state.formulation;
  if (!f) return <MissingFormulation />;
  const resultByConstraint = new Map((state.result?.constraintResults ?? []).map((row) => [row.constraintName, row]));
  const approvedCount = f.constraints.filter((row) => state.constraintApprovals[row.name]).length;
  const setApproval = (name: string, approved: boolean) => update({
    constraintApprovals: { ...state.constraintApprovals, [name]: approved },
  });
  const groups = [
    { title: "Customer demand fulfillment", type: "demand", description: "Every customer must receive exactly its governed demand quantity. These equalities prevent shortages and over-allocation." },
    { title: "Supplier supply maximum", type: "supply", description: "Total shipments from each supplier cannot exceed the supplier maximum recorded in the supply input table." },
    { title: "Transport capacity", type: "transport_capacity", description: "Total shipments from each supplier cannot exceed available transport throughput, even when physical supply is higher." },
  ];
  return <div className="space-y-4">
    <div className="grid gap-4 xl:grid-cols-[0.8fr_1.2fr]">
      <ConstraintReadinessChart formulation={f} />
      <AtlasWorkflowSection eyebrow="Executable policy" title="Generated business rules" description="Demand, supply, and transport constraints are built from the governed bundle. Reviewer approval confirms the business interpretation without changing coefficients." tone={approvedCount === f.constraints.length ? "success" : "warning"} action={<button type="button" className="atlas-secondary-button" onClick={() => update({ constraintApprovals: Object.fromEntries(f.constraints.map((row) => [row.name, true])) })}>Approve all generated rules</button>}>
        <KpiGrid rows={[["Demand equalities", f.metrics.demandConstraintCount], ["Supply limits", f.metrics.supplyConstraintCount], ["Transport limits", f.metrics.transportConstraintCount], ["Bounds", f.metrics.nonNegativityBoundCount], ["Custom rules", state.customConstraints.length], ["Reviewer approved", `${approvedCount} / ${f.constraints.length}`]]} />
      </AtlasWorkflowSection>
    </div>
    {groups.map((group) => <AtlasWorkflowSection key={group.type} eyebrow="Generated constraint group" title={group.title} description={group.description}>
      <DataTable headers={["Approve", "Entity", "Formula", "Sense", "RHS", "Source", "Slack after solve", "Status"]} rows={f.constraints.filter((row) => row.constraintType === group.type).map((row) => {
        const result = resultByConstraint.get(row.name);
        return [
          <input key={row.name} type="checkbox" aria-label={`Approve ${row.name}`} checked={Boolean(state.constraintApprovals[row.name])} onChange={(event) => setApproval(row.name, event.target.checked)} className="h-4 w-4 accent-emerald-600" />,
          row.entity,
          <details key={`${row.name}-formula`}><summary className="cursor-pointer font-semibold text-blue-700">{Object.keys(row.coefficients).length} route coefficients</summary><div className="mt-2 max-w-xl whitespace-normal rounded-md bg-slate-50 p-2 font-mono text-[11px] leading-5">{Object.entries(row.coefficients).map(([name, coefficient]) => `${coefficient} * ${name}`).join(" + ")} {row.sense} {formatTransportationValue(row.rhs)}</div></details>,
          row.sense,
          formatTransportationValue(row.rhs),
          row.sourceTable,
          result ? formatTransportationValue(result.slack, 3) : "After solve",
          state.constraintApprovals[row.name] ? "Reviewer approved" : "Review required",
        ];
      })} />
    </AtlasWorkflowSection>)}
    <AtlasWorkflowSection eyebrow="Generated constraint group" title="Non-negativity bounds" description="Route shipment quantities cannot be negative.">
      <DataTable headers={["Variable", "Lower bound", "Upper bound", "Type", "Source", "Status"]} rows={f.routes.map((route) => [route.variable_name, route.lower_bound, state.routeOverrides[route.route_id] === false ? 0 : "No route cap", "Continuous", route.source_tables.join(", "), state.routeOverrides[route.route_id] === false ? "Excluded route" : "Executable bound"])} />
    </AtlasWorkflowSection>
    <AtlasWorkflowSection eyebrow="Advanced formulation" title="Optional custom constraints" description="Use variable=coefficient pairs separated by commas. Example: x_Supplier1_Customer1=1, x_Supplier2_Customer1=1. These are executable rules; rationale belongs in review notes." tone="neutral" action={<button type="button" onClick={addCustomConstraint} className="atlas-secondary-button inline-flex items-center gap-2"><Plus size={15} /> Add custom rule</button>}>
      {state.customConstraints.length ? <div className="grid gap-3">{state.customConstraints.map((constraint, index) => <div key={constraint.id} className="grid gap-3 rounded-lg border border-slate-200 bg-slate-50 p-3 lg:grid-cols-[1fr_2fr_100px_120px_40px]"><input className={fieldClass()} value={constraint.name} onChange={(event) => setCustomConstraint(index, { name: event.target.value })} /><input className={fieldClass()} value={constraint.formula} onChange={(event) => setCustomConstraint(index, { formula: event.target.value })} /><select className={fieldClass()} value={constraint.sense} onChange={(event) => setCustomConstraint(index, { sense: event.target.value as CustomConstraint["sense"] })}><option>&lt;=</option><option>&gt;=</option><option>=</option></select><input type="number" className={fieldClass()} value={constraint.rhs} onChange={(event) => setCustomConstraint(index, { rhs: Number(event.target.value) })} /><button type="button" title="Remove custom rule" onClick={() => update({ customConstraints: state.customConstraints.filter((_, row) => row !== index), formulationConfirmed: false })} className="rounded-md p-2 text-red-700 hover:bg-red-50"><Trash2 size={16} /></button></div>)}</div> : <p className="text-sm text-slate-600">No custom rules. The generated transportation formulation is complete without manual coefficient entry.</p>}
      <div className="mt-4 rounded-lg border border-blue-200 bg-blue-50 px-4 py-3 text-sm leading-6 text-blue-950">Generated constraints were sourced from the demand, supply maximum, and transport capacity input tables and approved before solve.</div><div className="mt-4 flex flex-wrap items-center justify-between gap-3"><span className={`text-sm font-semibold ${state.executableRulesValidated ? "text-emerald-700" : "text-amber-800"}`}>{state.executableRulesValidated ? "Executable rules validated" : "Executable validation required after approvals"}</span><button type="button" disabled={busy === "formulate" || approvedCount !== f.constraints.length} onClick={() => void validateExecutableRules()} className="atlas-primary-button inline-flex items-center gap-2"><RefreshCw size={15} /> Validate executable rules</button></div>
    </AtlasWorkflowSection>
  </div>;
}

function SolverPage({ context }: { context: PageContext }) {
  const { state, update } = context; const f = state.formulation;
  if (!f) return <MissingFormulation />;
  const payloadPreview = JSON.stringify({
    method: "highs",
    objective: "minimize",
    variableCount: f.inspector.variableIndex.length,
    equalityRows: f.inspector.equalityConstraintCount,
    inequalityRows: f.inspector.inequalityConstraintCount,
    tolerance: state.tolerance,
    timeLimitSeconds: state.timeLimitSeconds,
  }, null, 2);
  return <div className="space-y-4">
    <div className="grid gap-4 xl:grid-cols-[1fr_0.8fr]">
      <AtlasWorkflowSection eyebrow="Solver configuration" title="HiGHS linear programming" description="Continuous route quantities, a linear cost objective, and linear equality and capacity rules make LP the appropriate default." tone="info">
        <div className="grid gap-4 md:grid-cols-3"><SelectField label="Solver method" value={state.method} options={["Linear programming (LP)"]} onChange={(value) => update({ method: value, result: null })} guidance="Use LP when route quantities are continuous and all objective and constraint terms are linear." /><NumberField label="Tolerance" value={state.tolerance} step={0.0000001} onChange={(value) => update({ tolerance: value, result: null })} /><NumberField label="Time limit (seconds)" value={state.timeLimitSeconds} onChange={(value) => update({ timeLimitSeconds: value, result: null })} /></div>
        <div className="mt-4 rounded-lg border border-blue-200 bg-blue-50 p-4 text-sm leading-6 text-blue-950"><strong>Reproducibility:</strong> SciPy HiGHS, deterministic route order, formulation {f.formulationId}, normalization hash {f.normalizationHash.slice(0, 16)}, tolerance {state.tolerance}, time limit {state.timeLimitSeconds} seconds.</div>
      </AtlasWorkflowSection>
      <AtlasWorkflowSection eyebrow="Formulation gate" title={f.formulationReady ? "Ready to solve" : "Formulation incomplete"} tone={f.formulationReady ? "success" : "danger"}><KpiGrid rows={[["Method", "Linear programming"], ["Route variables", f.metrics.routeCount], ["Demand constraints", f.metrics.demandConstraintCount], ["Supply constraints", f.metrics.supplyConstraintCount], ["Transport constraints", f.metrics.transportConstraintCount], ["Bounds", f.metrics.nonNegativityBoundCount], ["Objective", "Minimize total cost"], ["Time limit", `${state.timeLimitSeconds}s`]]} />{!f.formulationReady && <AtlasAttentionPanel title="Solve blocked" tone="danger">Formulation incomplete. The solver is configured, but the model is not ready to run.</AtlasAttentionPanel>}</AtlasWorkflowSection>
    </div>
    <AtlasWorkflowSection eyebrow="Method selection help" title="Choose the formulation class that matches the decision" description="The current transportation model is linear and continuous, so LP is executable in this workflow.">
      <div className="grid gap-3 md:grid-cols-3">
        <div className="rounded-lg border-2 border-blue-500 bg-blue-50 p-4"><div className="font-semibold text-blue-950">Linear programming (LP)</div><p className="mt-2 text-sm leading-6 text-blue-900">Continuous route quantities with a linear cost objective and linear demand, supply, and capacity constraints. Selected for this study.</p></div>
        <div className="rounded-lg border border-slate-200 bg-white p-4"><div className="font-semibold text-slate-950">Mixed-integer programming (MIP)</div><p className="mt-2 text-sm leading-6 text-slate-600">Use for integer units, yes/no decisions, fixed charges, minimum shipment sizes, or route activation. Not required by the current formulation.</p></div>
        <div className="rounded-lg border border-slate-200 bg-white p-4"><div className="font-semibold text-slate-950">Nonlinear optimization</div><p className="mt-2 text-sm leading-6 text-slate-600">Use for supported nonlinear risk penalties, response curves, or nonlinear objectives. This local transportation solver does not claim nonlinear execution.</p></div>
      </div>
    </AtlasWorkflowSection>
    <details className="rounded-lg border border-slate-200 bg-white">
      <summary className="cursor-pointer px-4 py-3 text-sm font-semibold text-slate-900">Advanced formulation inspector: objective vector, constraints, bounds, and solver payload (optional)</summary>
      <div className="space-y-4 border-t border-slate-200 p-4">
        <div className="grid gap-4 lg:grid-cols-2"><DataTable headers={["Vector", "Size", "Preview"]} rows={[["Variable index", f.inspector.variableIndex.length, f.inspector.variableIndex.slice(0, 8).join(", ")], ["Objective c", f.inspector.objectiveVector.length, f.inspector.objectiveVector.slice(0, 8).map((value) => formatTransportationValue(value)).join(", ")], ["Equality RHS", f.inspector.equalityRhs.length, f.inspector.equalityRhs.join(", ")], ["Inequality RHS", f.inspector.inequalityRhs.length, f.inspector.inequalityRhs.join(", ")], ["Lower bounds", f.inspector.lowerBounds.length, f.inspector.lowerBounds.slice(0, 8).join(", ")], ["Upper bounds", f.inspector.upperBounds.length, f.inspector.upperBounds.slice(0, 8).map((value) => value ?? "None").join(", ")]]} /><KpiGrid rows={[["Equality rows", f.inspector.equalityConstraintCount], ["Inequality rows", f.inspector.inequalityConstraintCount], ["Equality nonzeros", f.inspector.nonZeroEqualityCoefficients], ["Inequality nonzeros", f.inspector.nonZeroInequalityCoefficients]]} /></div>
        <div className="grid gap-4 lg:grid-cols-2"><div><div className="mb-2 text-xs font-semibold uppercase text-slate-500">Constraint names</div><div className="max-h-44 overflow-auto rounded-lg bg-slate-950 p-3 font-mono text-xs leading-6 text-slate-100">Equality: {f.inspector.equalityConstraintNames.join(", ")}<br />Inequality: {f.inspector.inequalityConstraintNames.join(", ")}</div></div><div><div className="mb-2 text-xs font-semibold uppercase text-slate-500">Solver payload preview</div><pre className="max-h-44 overflow-auto rounded-lg bg-slate-950 p-3 text-xs leading-5 text-slate-100">{payloadPreview}</pre></div></div>
      </div>
    </details>
  </div>;
}

function ScenariosPage({ context }: { context: PageContext }) {
  const { state, update, runScenarios, busy } = context; const f = state.formulation;
  if (!f) return <MissingFormulation />;
  const setScenario = (index: number, patch: Partial<TransportationScenario>) => update({ scenarios: state.scenarios.map((row, rowIndex) => rowIndex === index ? { ...row, ...patch } : row), scenarioAnalysis: null, validation: null });
  const analysis = state.scenarioAnalysis;
  const feasibleNames = analysis?.results.filter((row) => row.businessValid).map((row) => row.scenarioName) ?? [];
  const infeasibleRows = analysis?.results.filter((row) => !row.businessValid) ?? [];
  return <div className="space-y-4">
    <AtlasWorkflowSection eyebrow="Transportation stress design" title="Baseline and operational scenarios" description="Stress demand, supply, transport capacity, route costs, and inventory costs independently or together." tone="info" action={<button type="button" disabled={busy === "scenarios" || !f.formulationReady} onClick={() => void runScenarios()} className="atlas-primary-button inline-flex items-center gap-2">{busy === "scenarios" ? <LoaderCircle size={16} className="animate-spin" /> : <Play size={16} />} Run transportation scenarios</button>}>
      <div className="overflow-x-auto"><table className="min-w-[1120px] w-full text-sm"><thead className="bg-slate-950 text-left text-[10px] uppercase tracking-wide text-slate-200"><tr>{["Scenario", "Demand %", "Supply %", "Transport Capacity %", "Route Cost %", "Inventory Cost %", "Scenario note"].map((header) => <th key={header} className="px-3 py-3">{header}</th>)}</tr></thead><tbody className="divide-y divide-slate-100">{state.scenarios.map((scenario, index) => <tr key={scenario.id} className="align-top"><td className="px-3 py-3 font-semibold text-slate-950">{scenario.name}</td>{(["demandMultiplier", "supplyMultiplier", "capacityMultiplier", "routeCostMultiplier", "inventoryCostMultiplier"] as const).map((key) => <td key={key} className="px-3 py-2"><input type="number" min="0" step="5" className={`${fieldClass()} min-w-24`} value={Math.round(scenario[key] * 100)} onChange={(event) => setScenario(index, { [key]: Number(event.target.value) / 100 })} /></td>)}<td className="px-3 py-2"><textarea rows={2} className={`${fieldClass()} min-w-72 resize-y whitespace-normal`} value={scenario.note} onChange={(event) => setScenario(index, { note: event.target.value })} /></td></tr>)}</tbody></table></div>
    </AtlasWorkflowSection>
    {analysis ? <>
      <ScenarioComparisonChart analysis={analysis} />
      <AtlasWorkflowSection eyebrow="Scenario interpretation" title={`${analysis.validScenarioCount} feasible and ${analysis.infeasibleScenarioCount} infeasible cases`} tone={analysis.infeasibleScenarioCount ? "warning" : "success"}>
        <p className="text-sm leading-6 text-slate-700">{feasibleNames.length ? `${feasibleNames.join(", ")} remain feasible with no business-validity shortfall.` : "No tested scenario remained business-valid."} {infeasibleRows.length ? `${infeasibleRows.map((row) => row.scenarioName).join(", ")} require contingency planning because governed demand cannot be fulfilled under the stressed network.` : "All tested scenarios remain feasible."}</p>
      </AtlasWorkflowSection>
      {infeasibleRows.length > 0 && <AtlasWorkflowSection eyebrow="Infeasibility diagnosis" title="Why stressed scenarios fail" tone="danger"><div className="grid gap-3 md:grid-cols-2">{infeasibleRows.map((row) => { const scenario = state.scenarios.find((item) => item.id === row.scenarioId); return <div key={row.scenarioId} className="rounded-lg border border-red-200 bg-red-50 p-4"><div className="font-semibold text-red-950">{row.scenarioName}</div><div className="mt-3 grid grid-cols-2 gap-2 text-xs"><Meta label="Stressed demand" value={formatTransportationValue(f.metrics.totalDemand * (scenario?.demandMultiplier ?? 1), 0)} /><Meta label="Stressed supply" value={formatTransportationValue(f.metrics.totalSupplyMax * (scenario?.supplyMultiplier ?? 1), 0)} /><Meta label="Stressed transport capacity" value={formatTransportationValue(f.metrics.totalTransportCapacity * (scenario?.capacityMultiplier ?? 1), 0)} /><Meta label="Shortfall / unmet" value={formatTransportationValue(row.unmetDemand, 0)} /></div><p className="mt-3 text-xs leading-5 text-red-900">Business validity is invalid because the stressed network cannot fulfill all {formatTransportationValue(row.totalDemand, 0)} demand units. {row.errors.join(" ") || row.warnings.join(" ") || "Available supply or transport capacity is insufficient for governed demand."}</p></div>; })}</div></AtlasWorkflowSection>}
      <AtlasWorkflowSection eyebrow="Scenario evidence" title="Stress results"><DataTable headers={["Scenario", "Solver", "Business validity", "Total cost", "Change", "Demand fulfilled", "Unmet", "Active routes", "Binding", "Evidence"]} rows={analysis.results.map((row) => [row.scenarioName, row.solverStatus, row.businessValidityStatus, formatTransportationValue(row.totalCost), formatTransportationValue(row.costChangeVersusBase), `${formatTransportationValue(row.demandFulfilled, 0)} / ${formatTransportationValue(row.totalDemand, 0)}`, formatTransportationValue(row.unmetDemand, 0), row.activeRoutes, row.bindingConstraintCount, row.businessValid ? "Evidence ready" : "Evidence blocked: infeasible scenario"])} /></AtlasWorkflowSection>
    </> : <EmptyState title="Scenarios have not been run" body="Scenario analysis requires a valid route-level formulation with demand, supply, and transport-capacity constraints." />}
  </div>;
}

function OptimizePage({ context }: { context: PageContext }) {
  const { state, runSolve, busy, exportAllocationCsv } = context; const f = state.formulation;
  if (!f) return <MissingFormulation />;
  const result = state.result;
  const bindingTransportSuppliers = result?.bindingConstraints.filter((row) => row.constraintType === "transport_capacity").map((row) => row.entity) ?? [];
  return <div className="space-y-4">
    <AtlasWorkflowSection eyebrow="Governed solver execution" title="Optimize the route allocation" description="ATLAS accepts a result only when solver feasibility, formulation validity, and operational business validity all pass." tone={result?.success ? "success" : "info"} action={<button type="button" disabled={busy === "solve" || !f.formulationReady} onClick={() => void runSolve()} className="atlas-primary-button inline-flex items-center gap-2">{busy === "solve" ? <LoaderCircle size={16} className="animate-spin" /> : <Play size={16} />} Run optimization</button>}>
      {result ? <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5"><ResultKpi label="Solver status" value={result.solverStatus} detail={result.solverMessage} tone={result.solverFeasible ? "success" : "danger"} /><ResultKpi label="Business validity" value={result.businessValidityStatus} detail={result.decisionReadiness} tone={result.success ? "success" : "danger"} /><ResultKpi label="Total cost" value={formatTransportationValue(result.totalCost)} detail={`Baseline ${formatTransportationValue(result.baseline.totalCost)}`} tone={result.success ? "success" : "danger"} /><ResultKpi label="Demand fulfilled" value={`${formatTransportationValue(result.demandFulfilled, 0)} / ${formatTransportationValue(result.totalDemand, 0)}`} detail={`Unmet ${formatTransportationValue(result.unmetDemand, 0)}`} tone={result.unmetDemand <= 1e-6 ? "success" : "danger"} /><ResultKpi label="Active routes" value={`${result.activeRoutes} / ${result.totalRoutes}`} detail={`${result.bindingConstraints.length} binding constraints`} /></div> : <p className="text-sm text-slate-600">No solver run has been recorded for the current formulation.</p>}
      {result?.errors.length ? <div className="mt-4"><AtlasAttentionPanel title="Business-validity failure" tone="danger">{result.errors.join(" ")}</AtlasAttentionPanel></div> : null}
    </AtlasWorkflowSection>
    {result ? <>
      <AtlasWorkflowSection eyebrow="Solver interpretation" title={result.success ? "Business-valid allocation found" : "Allocation is not ready for decisioning"} tone={result.success ? "success" : "danger"}><p className="text-sm leading-7 text-slate-700">ATLAS found {result.success ? "a valid" : "an invalid"} allocation with total logistics cost {formatTransportationValue(result.totalCost)}. {formatTransportationValue(result.demandFulfilled, 0)} of {formatTransportationValue(result.totalDemand, 0)} demand units are fulfilled with {formatTransportationValue(result.unmetDemand, 0)} unmet. The solution uses {result.activeRoutes} of {result.totalRoutes} available routes. {bindingTransportSuppliers.length ? `Transport capacity is binding for ${bindingTransportSuppliers.join(" and ")}, meaning these suppliers are fully utilized from a transportation-throughput perspective. Additional transport capacity may reduce total cost if demand remains similar.` : "No supplier transport-capacity limit is binding in the current basis."}</p></AtlasWorkflowSection>
      <div className="grid gap-4 xl:grid-cols-2"><RouteMatrixChart formulation={f} result={result} mode="allocation" /><SupplierUtilizationChart result={result} /><CustomerFulfillmentChart result={result} /><CostContributionChart result={result} /></div>
      <AtlasWorkflowSection eyebrow="Route-level decision vector" title="Optimized allocation and cost contribution" action={<button type="button" onClick={exportAllocationCsv} className="atlas-secondary-button inline-flex items-center gap-2"><FileSpreadsheet size={15} /> Export Allocation CSV</button>}>
        <div className="mb-3 rounded-lg border border-blue-200 bg-blue-50 p-3 text-xs leading-5 text-blue-950"><strong>Reduced cost:</strong> Indicates how much a currently unused route's unit cost would need to improve before the solver would use it, assuming the current basis remains valid.</div>
        <DataTable headers={["Supplier", "Customer", "Quantity", "Transport", "Inventory", "Unit cost", "Cost contribution", "Reduced cost", "Status"]} rows={result.decisionVector.map((row) => [row.supplier, row.customer, formatTransportationValue(row.quantity, 3), formatTransportationValue(row.transportationCost), formatTransportationValue(row.inventoryCost), formatTransportationValue(row.totalUnitCost), formatTransportationValue(row.costContribution), formatTransportationValue(row.reducedCost, 4), row.status])} />
      </AtlasWorkflowSection>
      <AtlasWorkflowSection eyebrow="Constraint diagnostics" title="Slack, binding rules, and marginal values">
        <div className="mb-3 rounded-lg border border-violet-200 bg-violet-50 p-3 text-xs leading-5 text-violet-950"><strong>Shadow price:</strong> Estimates how the objective would change if a constraint right-hand side changed by one unit, within the valid sensitivity range. For a minimization problem, a negative capacity shadow price can indicate that relaxing the capacity constraint may reduce total cost.</div>
        <DataTable headers={["Constraint", "Type", "LHS", "Sense", "RHS", "Slack", "Binding", "Shadow price", "Source"]} rows={result.constraintResults.map((row) => [row.constraintName, row.constraintType, formatTransportationValue(row.lhs), row.sense, formatTransportationValue(row.rhs), formatTransportationValue(row.slack), row.binding ? "Yes" : "No", row.shadowPrice === null ? "Unavailable" : formatTransportationValue(row.shadowPrice, 4), row.sourceTable])} />
      </AtlasWorkflowSection>
    </> : <EmptyState title="No optimized allocation" body="Run the business-valid route-level formulation. ATLAS will block all-zero or placeholder outcomes." />}
  </div>;
}

function SensitivityPage({ context }: { context: PageContext }) {
  const { state, update, runSensitivity, busy } = context;
  if (!state.formulation) return <MissingFormulation />;
  const analysis = state.sensitivity;
  const driverMagnitude = (driver: string) => Math.max(...(analysis?.rows.filter((row) => row.driver === driver).map((row) => Math.abs(row.costChange ?? 0)) ?? [0]));
  const rankedDrivers = analysis ? [...new Set(analysis.rows.map((row) => row.driver))].sort((a, b) => driverMagnitude(b) - driverMagnitude(a)) : [];
  const demandIncrease = analysis?.rows.find((row) => row.driver.toLowerCase().includes("demand") && row.direction.toLowerCase().includes("increase"));
  const demandDecrease = analysis?.rows.find((row) => row.driver.toLowerCase().includes("demand") && row.direction.toLowerCase().includes("decrease"));
  const supplyImpact = analysis?.rows.filter((row) => row.driver.toLowerCase().includes("supply")).reduce((sum, row) => sum + Math.abs(row.costChange ?? 0), 0) ?? 0;
  return <div className="space-y-4">
    <AtlasWorkflowSection eyebrow="Real logistics drivers" title="Sensitivity and tradeoffs" description="Perturb route cost, inventory cost, demand, supplier supply, and transportation capacity around the saved business-valid solution." tone="info" action={<button type="button" disabled={busy === "sensitivity" || !state.result?.success} onClick={() => void runSensitivity()} className="atlas-primary-button inline-flex items-center gap-2">{busy === "sensitivity" ? <LoaderCircle size={16} className="animate-spin" /> : <Gauge size={16} />} Run sensitivity analysis</button>}><div className="max-w-xs"><NumberField label="Perturbation percent" value={state.perturbationPercent} onChange={(value) => update({ perturbationPercent: value, sensitivity: null, validation: null })} /></div>{!state.result?.success && <div className="mt-4"><AtlasAttentionPanel title="Sensitivity blocked" tone="danger">Sensitivity analysis unavailable because the current solution is not business-valid.</AtlasAttentionPanel></div>}</AtlasWorkflowSection>
    {analysis ? <>
      <SensitivityTornadoChart analysis={analysis} />
      <AtlasWorkflowSection eyebrow="ATLAS interpretation" title="What moves logistics cost" tone="success"><p className="text-sm leading-7 text-slate-700">{rankedDrivers[0] ?? "The tested inputs"} is the largest tested cost driver{rankedDrivers[1] ? `, followed by ${rankedDrivers[1]}` : ""}. A {analysis.perturbationPercent}% demand increase changes optimized cost by {formatTransportationValue(demandIncrease?.costChange)}, while a {analysis.perturbationPercent}% demand decrease changes cost by {formatTransportationValue(demandDecrease?.costChange)}. {supplyImpact <= 1e-7 ? "Supplier supply changes have no cost impact in this range, indicating that supply maximums are not the active bottleneck. Transport capacity is the tighter operating limit where its constraints bind." : `Supplier supply movement changes cost by ${formatTransportationValue(supplyImpact)} across the tested directions.`}</p></AtlasWorkflowSection>
      <div className="grid gap-4 xl:grid-cols-2">
        <AtlasWorkflowSection eyebrow="Perturbation diagnostics" title="Cost and allocation movement"><div className="mb-3 grid gap-2 text-xs sm:grid-cols-2"><div className="rounded-lg border border-slate-200 bg-slate-50 p-3"><strong>Route change:</strong> Counts how many supplier-customer routes become active or inactive compared with the base solution.</div><div className="rounded-lg border border-slate-200 bg-slate-50 p-3"><strong>Turnover:</strong> Measures how much allocation volume moved to different routes under the perturbation.</div></div><DataTable headers={["Driver", "Direction", "Cost change", "Cost change %", "Route change", "Turnover", "Unmet", "Valid"]} rows={analysis.rows.map((row) => [row.driver, row.direction, formatTransportationValue(row.costChange), formatTransportationPercent(row.costChangePercent), row.activeRouteChange, formatTransportationValue(row.allocationTurnover, 2), formatTransportationValue(row.unmetDemand, 1), row.businessValid ? "Yes" : "No"])} /></AtlasWorkflowSection>
        <AtlasWorkflowSection eyebrow="LP marginal values" title="Binding constraint shadow prices" description="Shadow price estimates the local change in the minimized objective when a constraint right-hand side increases by one unit, while the current basis remains valid."><DataTable headers={["Constraint", "Type", "Shadow price", "Availability"]} rows={analysis.shadowPrices.map((row) => [row.constraintName, row.constraintType, row.available ? formatTransportationValue(row.shadowPrice, 4) : "Unavailable", row.available ? "Available" : "Not returned"])} /></AtlasWorkflowSection>
      </div>
      {supplyImpact <= 1e-7 && <div className="rounded-lg border border-blue-200 bg-blue-50 p-4 text-sm leading-6 text-blue-950"><strong>Supplier supply sensitivity:</strong> Supplier supply perturbations did not affect total cost because supplier supply maximums have slack under the current solution. Transport capacity, not supply availability, is the tighter operating limit.</div>}
    </> : <EmptyState title="Sensitivity has not been run" body="Save a business-valid allocation first, then test real cost, demand, supply, and capacity drivers." />}
  </div>;
}

function ValidationPage({ context }: { context: PageContext }) {
  const { state, update, runValidation, busy } = context;
  const confirmations = [
    ["evidenceCompleteness", "Evidence completeness", "Confirmed by the model developer, documentation owner, or evidence package owner after required source versions, formulation, solver, scenarios, sensitivity, and recommendation artifacts are retained."],
    ["implementationReadiness", "Implementation readiness", "Confirmed by the accountable operations owner or implementation owner after execution, exception handling, reconciliation, and monitoring responsibilities are defined."],
    ["independentReview", "Independent review", "Confirmed by a reviewer independent of development after challenging the formulation, assumptions, solver result, scenarios, sensitivity, and recommendation."],
  ];
  const unchecked = confirmations.filter(([key]) => !state.validationConfirmations[key]).map(([, label]) => label);
  const noteTemplate = "Validation completed for walkthrough or review purposes. The formulation uses the Transportation / Logistics template, 30 route-level decision variables, demand fulfillment constraints, supplier supply constraints, transport-capacity constraints, and non-negativity bounds. The solver produced a business-valid allocation with all demand fulfilled and no unmet demand. Scenario and sensitivity outputs were reviewed. Remaining implementation readiness should be confirmed by the accountable operations owner before production use.";
  return <div className="space-y-4">
    <AtlasWorkflowSection eyebrow="Validation flow" title="Mathematical checks to recommendation gate" description="Mathematical success can pass while governance acceptance remains pending." tone="info"><div className="grid gap-2 md:grid-cols-5">{["Mathematical checks", "Evidence checks", "Operational readiness", "Independent challenge", "Recommendation gate"].map((label, index) => <div key={label} className={`rounded-lg border p-3 text-center text-xs font-semibold ${index === 0 && state.result?.success ? "border-emerald-300 bg-emerald-50 text-emerald-800" : index === 4 && state.validation?.recommendationAllowed ? "border-emerald-300 bg-emerald-50 text-emerald-800" : "border-slate-200 bg-white text-slate-700"}`}>{index + 1}. {label}</div>)}</div></AtlasWorkflowSection>
    <AtlasWorkflowSection eyebrow="Two-layer validation" title="Separate mathematical success from governance acceptance" description="ATLAS derives analytical checks from real results. Governance confirmations remain unchecked until an accountable validator actively records them." tone={state.validation?.recommendationAllowed ? "success" : "warning"} action={<button type="button" disabled={busy === "validation" || !state.result?.success} onClick={() => void runValidation()} className="atlas-primary-button inline-flex items-center gap-2">{busy === "validation" ? <LoaderCircle size={16} className="animate-spin" /> : <ClipboardCheck size={16} />} Run validation scorecard</button>}>
      <div className="grid gap-3 md:grid-cols-3">{confirmations.map(([key, label, description]) => <label key={key} className={`cursor-pointer rounded-lg border p-4 ${state.validationConfirmations[key] ? "border-emerald-300 bg-emerald-50" : "border-slate-200 bg-white"}`}><div className="flex items-start gap-3"><input type="checkbox" checked={Boolean(state.validationConfirmations[key])} onChange={(event) => update({ validationConfirmations: { ...state.validationConfirmations, [key]: event.target.checked }, validation: null })} className="mt-1 h-4 w-4 accent-emerald-600" /><span><span className="block text-sm font-semibold text-slate-950">{label}</span><span className="mt-1 block text-xs leading-5 text-slate-600">{description}</span></span></div></label>)}</div>
      {unchecked.length > 0 && <div className="mt-4 rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm text-amber-950"><strong>Recommendation gate blocked by:</strong> {unchecked.join(", ")}.</div>}
      <div className="mt-4"><TextArea label="Validator notes" value={state.validationNotes} onChange={(value) => update({ validationNotes: value })} /></div>
      <div className="mt-3 flex flex-wrap items-center justify-between gap-3 rounded-lg border border-blue-200 bg-blue-50 p-3"><p className="max-w-4xl text-xs leading-5 text-blue-950"><strong>Suggested validator note:</strong> {noteTemplate}</p><button type="button" onClick={() => update({ validationNotes: noteTemplate, validation: null })} className="atlas-secondary-button shrink-0">Use suggested note</button></div>
    </AtlasWorkflowSection>
    {state.validation ? <AtlasWorkflowSection eyebrow="Validation scorecard" title={`${state.validation.score}% complete`} tone={state.validation.recommendationAllowed ? "success" : "warning"}><div className="grid gap-2 md:grid-cols-2">{state.validation.checks.map((check) => <div key={check.id} className={`flex gap-2 rounded-lg border px-3 py-3 ${check.passed ? "border-emerald-200 bg-emerald-50" : "border-amber-200 bg-amber-50"}`}>{check.passed ? <CheckCircle2 size={16} className="mt-0.5 shrink-0 text-emerald-700" /> : <AlertTriangle size={16} className="mt-0.5 shrink-0 text-amber-700" />}<div><div className="text-sm font-semibold text-slate-950">{check.label}</div><div className="mt-1 text-xs text-slate-600">{check.evidence}</div></div></div>)}</div><div className="mt-4 grid gap-3 sm:grid-cols-3"><ResultKpi label="Mathematical success" value={state.validation.mathematicalSuccess ? "Pass" : "Fail"} tone={state.validation.mathematicalSuccess ? "success" : "danger"} /><ResultKpi label="Governance acceptance" value={state.validation.governanceAcceptance ? "Confirmed" : "Pending"} tone={state.validation.governanceAcceptance ? "success" : "warning"} /><ResultKpi label="Recommendation gate" value={state.validation.recommendationAllowed ? "Open" : "Blocked"} tone={state.validation.recommendationAllowed ? "success" : "danger"} /></div></AtlasWorkflowSection> : <EmptyState title="Validation scorecard is not available" body="Complete a business-valid solve, transportation scenarios, sensitivity, and active reviewer confirmations." />}
  </div>;
}

function RecommendationPage({ context }: { context: PageContext }) {
  const { state, update, generateRecommendation } = context; const result = state.result;
  if (!result?.success) return <EmptyState title="A business-valid solution is required" body="Recommendation cannot be finalized from an invalid formulation, infeasible solve, or zero-allocation placeholder." />;
  const canAdvance = Boolean(state.validation?.recommendationAllowed);
  const scenarioCount = state.scenarioAnalysis?.scenarioCount ?? 0;
  const feasibleScenarioCount = state.scenarioAnalysis?.validScenarioCount ?? 0;
  const infeasibleScenarioCount = state.scenarioAnalysis?.infeasibleScenarioCount ?? 0;
  const largestSensitivityDriver = state.sensitivity?.rows.length ? [...state.sensitivity.rows].sort((a, b) => Math.abs(b.costChange ?? 0) - Math.abs(a.costChange ?? 0))[0]?.driver : "Not available";
  return <div className="space-y-4">
    {canAdvance && <AtlasWorkflowSection eyebrow="ATLAS recommendation" title="Recommendation: Approve optimized allocation for operational implementation" tone="success"><p className="text-sm leading-7 text-slate-700">ATLAS recommends implementing the optimized transportation plan because it fulfills all demand, respects supply and transport-capacity limits, passes validation, and remains feasible across {feasibleScenarioCount} of {scenarioCount} tested scenarios. {infeasibleScenarioCount ? `${infeasibleScenarioCount} infeasible disruption scenario requires contingency planning.` : "No tested scenario was infeasible."}</p></AtlasWorkflowSection>}
    <AtlasWorkflowSection eyebrow="Decision recommendation" title="Translate the allocation into an accountable action" description="Management receives the fulfillment, cost, route, capacity, scenario, sensitivity, and limitation story without inspecting solver vectors." tone={canAdvance ? "success" : "warning"} action={<button type="button" onClick={generateRecommendation} className="atlas-secondary-button inline-flex items-center gap-2"><Sparkles size={15} /> Generate result-based draft</button>}>
      <div className="grid gap-4 md:grid-cols-2"><SelectField label="Recommendation status" value={state.recommendationStatus} options={["Draft", "Recommended", "Approved", "Returned", "Rejected"]} onChange={(value) => update({ recommendationStatus: canAdvance ? value as TransportationState["recommendationStatus"] : "Draft" })} guidance="Draft: analyst editing. Recommended: analyst supports implementation. Approved: accountable owner accepted. Returned: changes requested. Rejected: do not implement." /><TextField label="Recommendation owner" value={state.recommendationOwner} onChange={(value) => update({ recommendationOwner: value })} /><div className="md:col-span-2"><TextArea label="Recommended action" value={state.recommendation} onChange={(value) => update({ recommendation: value })} rows={9} documentEditor /></div><TextArea label="Alternatives considered" value={state.alternatives} onChange={(value) => update({ alternatives: value })} rows={7} documentEditor /><TextArea label="Residual risks and limitations" value={state.residualRisks} onChange={(value) => update({ residualRisks: value })} rows={7} documentEditor /></div>
      {!canAdvance && <div className="mt-4"><AtlasAttentionPanel title="Finalization blocked">Complete the validation scorecard before moving the recommendation beyond Draft.</AtlasAttentionPanel></div>}
    </AtlasWorkflowSection>
    <div className="grid gap-4 xl:grid-cols-[0.8fr_1.2fr]"><AtlasWorkflowSection eyebrow="Management summary" title="Decision at a glance" tone="success"><KpiGrid rows={[["Recommendation", state.recommendationStatus], ["Total cost", formatTransportationValue(result.totalCost)], ["Demand fulfilled", `${formatTransportationValue(result.demandFulfilled, 0)} / ${formatTransportationValue(result.totalDemand, 0)}`], ["Unmet demand", formatTransportationValue(result.unmetDemand, 0)], ["Active routes", `${result.activeRoutes} of ${result.totalRoutes}`], ["Capacity respected", result.constraintResults.every((row) => row.feasible) ? "Yes" : "No"], ["Scenario coverage", `${feasibleScenarioCount} of ${scenarioCount} feasible`], ["Infeasible scenarios", infeasibleScenarioCount], ["Largest sensitivity driver", largestSensitivityDriver], ["Implementation risk", infeasibleScenarioCount ? "Contingency plan required" : "Standard controls"]]} /></AtlasWorkflowSection><AtlasWorkflowSection eyebrow="Largest allocation routes" title="Operational plan"><DataTable headers={["Supplier", "Customer", "Quantity", "Unit cost", "Cost contribution"]} rows={[...result.decisionVector].filter((row) => row.quantity > 1e-7).sort((a, b) => b.quantity - a.quantity).slice(0, 12).map((row) => [row.supplier, row.customer, formatTransportationValue(row.quantity, 2), formatTransportationValue(row.totalUnitCost), formatTransportationValue(row.costContribution)])} /></AtlasWorkflowSection></div>
  </div>;
}

function ImplementationPage({ context }: { context: PageContext }) {
  const { state, update, exportAllocationCsv, exportGovernedPackage, exportPythonCode, exportSasCode, generateImplementationPlan } = context;
  const result = state.result;
  const updateThreshold = (id: string, patch: Partial<OptimizationMonitoringThreshold>) => update({ monitoringThresholds: state.monitoringThresholds.map((row) => row.id === id ? { ...row, ...patch } : row) });
  return <div className="space-y-4">
    <AtlasWorkflowSection eyebrow="Implementation plan" title="Execute approved transportation allocation" description="Turn the approved route-level decision into controlled operating instructions." tone={implementationPlanReady(state) ? "success" : "info"} action={<button type="button" disabled={!result?.success} onClick={generateImplementationPlan} className="atlas-secondary-button inline-flex items-center gap-2"><Sparkles size={15} /> Generate implementation plan</button>}>
      <p className="text-sm leading-7 text-slate-700">ATLAS recommends operational execution of the approved allocation plan for the current planning period. The plan fulfills {formatTransportationValue(result?.demandFulfilled, 0)} of {formatTransportationValue(result?.totalDemand, 0)} demand units, uses {result?.activeRoutes ?? 0} active supplier-customer routes, respects supply and transport-capacity limits, and requires monitoring of route exceptions, realized cost, demand variance, and capacity utilization.</p>
    </AtlasWorkflowSection>
    <AtlasWorkflowSection eyebrow="Operationalization" title="Implementation and monitoring plan" description="Translate the approved route allocation into controlled execution, exception handling, reconciliation, fallback, and re-optimization controls." tone="info"><div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3"><TextField label="Implementation owner" value={state.implementationOwner} onChange={(value) => update({ implementationOwner: value })} /><TextField label="Effective date" type="date" value={state.effectiveDate} onChange={(value) => update({ effectiveDate: value })} /><SelectField label="Operating cadence" value={state.operatingCadence} options={["One-time execution", "Daily", "Weekly", "Monthly", "Event triggered"]} onChange={(value) => update({ operatingCadence: value })} guidance="Align execution to the frequency at which demand, route cost, and capacity inputs can be reconciled." /><TextArea label="Route exception process" value={state.routeExceptionProcess} onChange={(value) => update({ routeExceptionProcess: value })} /><TextArea label="Fallback plan" value={state.fallbackPlan} onChange={(value) => update({ fallbackPlan: value })} /><TextArea label="Monitoring metrics" value={state.monitoringMetrics} onChange={(value) => update({ monitoringMetrics: value })} /><TextField label="Monitoring cadence" value={state.monitoringCadence} onChange={(value) => update({ monitoringCadence: value })} /><TextArea label="Re-optimization trigger" value={state.reoptimizationTrigger} onChange={(value) => update({ reoptimizationTrigger: value })} /><TextArea label="Reconciliation process" value={state.reconciliationProcess} onChange={(value) => update({ reconciliationProcess: value })} /></div></AtlasWorkflowSection>
    <AtlasWorkflowSection eyebrow="Implementation controls" title="Operational monitoring thresholds" description="Each trigger has an accountable owner, operating cadence, escalation action, and lifecycle status." tone="success">
      <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white"><table className="min-w-[1180px] w-full border-collapse text-sm"><thead className="bg-slate-950 text-left text-[10px] uppercase tracking-wide text-slate-200"><tr>{["Metric", "Trigger threshold", "Owner", "Cadence", "Escalation action", "Status"].map((header) => <th key={header} className="px-3 py-3">{header}</th>)}</tr></thead><tbody className="divide-y divide-slate-100">{state.monitoringThresholds.map((row) => <tr key={row.id} className="align-top hover:bg-blue-50/30"><td className="px-3 py-3 font-semibold text-slate-950">{row.metric}</td><td className="p-2"><input aria-label={`${row.metric} trigger threshold`} className={fieldClass()} value={row.threshold} onChange={(event) => updateThreshold(row.id, { threshold: event.target.value })} /></td><td className="p-2"><input aria-label={`${row.metric} owner`} className={fieldClass()} value={row.owner} onChange={(event) => updateThreshold(row.id, { owner: event.target.value })} /></td><td className="p-2"><input aria-label={`${row.metric} cadence`} className={fieldClass()} value={row.cadence} onChange={(event) => updateThreshold(row.id, { cadence: event.target.value })} /></td><td className="p-2"><textarea aria-label={`${row.metric} escalation action`} rows={2} className={`${fieldClass()} min-w-64 resize-y`} value={row.escalation} onChange={(event) => updateThreshold(row.id, { escalation: event.target.value })} /></td><td className="p-2"><select aria-label={`${row.metric} status`} className={fieldClass()} value={row.status} onChange={(event) => updateThreshold(row.id, { status: event.target.value as OptimizationMonitoringThreshold["status"] })}>{["Active", "Draft", "Paused"].map((status) => <option key={status}>{status}</option>)}</select></td></tr>)}</tbody></table></div>
      <div className="mt-4 flex flex-wrap gap-2"><button type="button" disabled={!result?.success || context.busy === "export"} onClick={() => void exportAllocationCsv()} className="atlas-secondary-button inline-flex items-center gap-2"><FileSpreadsheet size={15} /> Export Allocation CSV</button><button type="button" disabled={context.busy === "export"} onClick={() => void exportGovernedPackage()} className="atlas-secondary-button inline-flex items-center gap-2"><FileJson size={15} /> Export Formulation JSON</button>{state.code && <><button type="button" disabled={context.busy === "export"} onClick={() => void exportPythonCode()} className="atlas-secondary-button inline-flex items-center gap-2"><Code2 size={15} /> Export Python Reproducibility Code</button><button type="button" disabled={context.busy === "export"} onClick={() => void exportSasCode()} className="atlas-secondary-button inline-flex items-center gap-2"><Braces size={15} /> Export SAS-Compatible Template</button></>}</div>
    </AtlasWorkflowSection>
  </div>;
}

function DocumentationPage({ context }: { context: PageContext }) {
  const { state, update, exportGovernedPackage, exportAllocationCsv, exportPythonCode, exportSasCode, generateOptimizationReport, captureRemainingEvidence, captureEvidence, busy } = context;
  const formulation = state.formulation;
  const result = state.result;
  const sectionReady = (index: number) => TRANSPORTATION_EVIDENCE_STAGES.some((definition) => definition.sections.includes(DOCUMENTATION_SECTIONS[index]) && optimizationStageGenerated(state, definition.stage));
  const readyCount = optimizationDocumentationSectionCount(state);
  const analyticalReady = readyCount === DOCUMENTATION_SECTIONS.length;
  const evidenceSummary = deriveOptimizationEvidenceSummary(state);
  const exportRows = Object.values(state.exportArtifacts).filter((row): row is OptimizationExportRecord => Boolean(row));
  const documentationGroups = [
    ["Executive and Business Context", [0, 1]],
    ["Data and Formulation", [2, 3, 4, 5, 6]],
    ["Solver and Results", [7, 9]],
    ["Scenarios and Sensitivity", [8, 10]],
    ["Validation and Recommendation", [11, 12, 15, 16]],
    ["Implementation and Monitoring", [13, 14]],
    ["Reproducibility and Code", [17, 18, 19]],
  ] as const;
  const largestSensitivityDriver = state.sensitivity?.rows.length ? [...state.sensitivity.rows].sort((a, b) => Math.abs(b.costChange ?? 0) - Math.abs(a.costChange ?? 0))[0]?.driver : "not available";
  const packageSummary = `This package documents a Transportation / Logistics optimization study that produced a ${result?.success ? "business-valid" : "pending"} route allocation. The final solution fulfills ${formatTransportationValue(result?.demandFulfilled, 0)} of ${formatTransportationValue(result?.totalDemand, 0)} demand units, uses ${result?.activeRoutes ?? 0} of ${result?.totalRoutes ?? formulation?.metrics.routeCount ?? 0} routes, respects supply and transport-capacity limits, and has total logistics cost ${formatTransportationValue(result?.totalCost)}. Scenario analysis reviewed ${state.scenarioAnalysis?.scenarioCount ?? 0} cases, including ${state.scenarioAnalysis?.infeasibleScenarioCount ?? 0} infeasible disruption scenario${state.scenarioAnalysis?.infeasibleScenarioCount === 1 ? "" : "s"}. Sensitivity analysis identified ${largestSensitivityDriver} as the largest tested cost driver.`;
  return <div className="space-y-4">
    <AtlasWorkflowSection eyebrow="Final audit review" title="Final Optimization Study Package" description="Review analytical validity, decision ownership, implementation readiness, reproducibility, and final approval before closing the study." tone={analyticalReady ? "success" : "warning"}>
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4"><ResultKpi label="Documentation readiness" value={`${readyCount} of 20`} tone={analyticalReady ? "success" : "warning"} /><ResultKpi label="Solution status" value={result?.success ? "Business-valid" : "Pending"} tone={result?.success ? "success" : "danger"} /><ResultKpi label="Validation score" value={`${state.validation?.score ?? 0}%`} tone={state.validation?.recommendationAllowed ? "success" : "warning"} /><ResultKpi label="Recommendation" value={state.recommendationStatus} tone={state.recommendationStatus !== "Draft" ? "success" : "warning"} /><ResultKpi label="Implementation" value={implementationPlanReady(state) ? "Plan complete" : "Incomplete"} tone={implementationPlanReady(state) ? "success" : "warning"} /><ResultKpi label="Evidence package" value={evidenceSummary.packageReady ? "Ready" : evidenceSummary.statusLabel} tone={evidenceSummary.packageReady ? "success" : "warning"} /><ResultKpi label="Final reviewer" value={state.reviewer || "Pending"} /><ResultKpi label="Approval date" value={state.approvalDate || "Pending"} /></div>
      <div className="mt-4 rounded-lg border border-blue-200 bg-blue-50 p-4 text-sm leading-7 text-blue-950">{packageSummary}</div>
    </AtlasWorkflowSection>
    <div className="grid gap-4 xl:grid-cols-[0.65fr_1.35fr]">
      <AtlasWorkflowSection eyebrow="Final approval" title="Accountable review record" tone={state.reviewer && state.approvalDate ? "success" : "warning"}><div className="grid gap-3"><TextField label="Final reviewer" value={state.reviewer} onChange={(value) => update({ reviewer: value })} /><TextField label="Approval date" type="date" value={state.approvalDate} onChange={(value) => update({ approvalDate: value })} /></div><p className="mt-3 text-xs leading-5 text-slate-600">Final reviewer should be the accountable reviewer or approver for the completed optimization package. Approval date records when the package was accepted for study completion.</p></AtlasWorkflowSection>
      <AtlasWorkflowSection eyebrow="Documentation Studio mapping" title="Grouped optimization decision report"><div className="grid gap-4 lg:grid-cols-2">{documentationGroups.map(([group, indexes]) => <div key={group} className="rounded-lg border border-slate-200 bg-slate-50 p-3"><div className="mb-2 text-xs font-bold uppercase text-slate-600">{group}</div><div className="space-y-2">{indexes.map((index) => { const ready = sectionReady(index); return <div key={DOCUMENTATION_SECTIONS[index]} className={`flex items-center gap-2 rounded-md border px-3 py-2 text-sm ${ready ? "border-emerald-200 bg-emerald-50 text-emerald-900" : "border-slate-200 bg-white text-slate-600"}`}>{ready ? <CheckCircle2 size={15} /> : <AlertTriangle size={15} />}{index + 1}. {DOCUMENTATION_SECTIONS[index]}</div>; })}</div></div>)}</div></AtlasWorkflowSection>
    </div>
    <AtlasWorkflowSection eyebrow="Evidence and export" title="Governed package actions" description="Invalid zero-allocation results, placeholder scenarios, and generic sensitivity cannot be captured as final evidence." tone="info">
      <div className="mb-4 rounded-lg border border-slate-200 bg-white p-4"><div className="flex flex-wrap items-center justify-between gap-3"><div><div className="text-sm font-semibold text-slate-950">{evidenceSummary.statusLabel}</div><p className="mt-1 text-xs leading-5 text-slate-600">{evidenceSummary.generatedCount} generated, {evidenceSummary.capturedCount} captured, {evidenceSummary.readyCount} ready, and {evidenceSummary.records.filter((row) => row.approved).length} approved across {evidenceSummary.requiredCount} governed artifacts.</p></div><button type="button" disabled={busy === "evidence"} onClick={() => void captureRemainingEvidence()} className="atlas-secondary-button inline-flex items-center gap-2"><ShieldCheck size={15} /> {evidenceSummary.actionLabel}</button></div></div>
      <div className="flex flex-wrap gap-2"><button type="button" disabled={busy === "export"} onClick={() => void exportGovernedPackage()} className="atlas-primary-button inline-flex items-center gap-2"><Download size={15} /> Export Governed JSON</button><button type="button" disabled={!result?.success || busy === "export"} onClick={() => void exportAllocationCsv()} className="atlas-secondary-button inline-flex items-center gap-2"><FileSpreadsheet size={15} /> Export Allocation CSV</button><button type="button" disabled={busy === "evidence" || !formulation} onClick={() => void captureEvidence("code_reproducibility")} className="atlas-secondary-button inline-flex items-center gap-2"><PackageCheck size={15} /> Capture Reproducibility Evidence</button><button type="button" disabled={busy === "report" || !analyticalReady} onClick={() => void generateOptimizationReport()} className="atlas-secondary-button inline-flex items-center gap-2"><FileText size={15} /> Generate Optimization Report</button>{state.code && <><button type="button" disabled={busy === "export"} onClick={() => void exportPythonCode()} className="atlas-secondary-button inline-flex items-center gap-2"><Code2 size={15} /> Export Python Code</button><button type="button" disabled={busy === "export"} onClick={() => void exportSasCode()} className="atlas-secondary-button inline-flex items-center gap-2"><Braces size={15} /> Export SAS-Compatible Code</button></>}</div>
      <div className="mt-4"><DataTable headers={["Artifact", "Generated", "Captured", "Ready", "Reference"]} rows={evidenceSummary.records.map((row) => [row.label, row.generated ? "Yes" : "No", row.captured ? "Yes" : "No", row.ready ? "Ready" : row.generated ? "Evidence generated, not captured" : "Pending", row.reference || "Not captured"])} /></div>
      <div className="mt-4"><DataTable headers={["Export", "Status", "Generated", "Bytes", "Evidence reference"]} rows={exportRows.map((row) => [row.fileName, row.status, new Date(row.generatedAt).toLocaleString(), row.byteCount.toLocaleString(), row.evidenceId || row.artifactReference])} /></div>
    </AtlasWorkflowSection>
    {state.generatedReport && <AtlasWorkflowSection eyebrow="Audit package preview" title="View Generated Report" description={`Markdown report generated ${state.generatedReportAt ? new Date(state.generatedReportAt).toLocaleString() : "for this project"}. Inspect all 20 sections before completing the study.`} tone="success"><details className="rounded-lg border border-slate-200 bg-white" open><summary className="flex cursor-pointer items-center gap-2 px-4 py-3 text-sm font-semibold text-slate-950"><FileText size={16} className="text-blue-600" /> Preview Optimization Report</summary><pre className="max-h-[720px] overflow-auto whitespace-pre-wrap border-t border-slate-200 bg-slate-950 p-5 text-xs leading-6 text-slate-100">{state.generatedReport}</pre></details></AtlasWorkflowSection>}
  </div>;
}

function TransportationCodePanel({ stepNumber, state, update, busy, codeResult, runCode, saveCodeToNotebook, exportPythonCode, exportSasCode, captureEvidence }: { projectId: string; stepNumber: number; state: TransportationState; update: (patch: Partial<TransportationState>) => void; busy: BusyAction; codeResult: CodeRunResult | null; runCode: () => Promise<void>; saveCodeToNotebook: (language: "python" | "sas") => void; exportPythonCode: () => Promise<void>; exportSasCode: () => Promise<void>; captureEvidence: () => void }) {
  const generatedPython = state.code?.python.code ?? "# Complete the transportation input bundle and build the route-level formulation to generate executable Python code.";
  const generatedSas = state.code?.sas.code ?? "/* Complete the transportation input bundle to generate a SAS-compatible PROC OPTMODEL template. */";
  const python = state.userPythonByStep[String(stepNumber)] ?? generatedPython;
  const sas = state.userSasByStep[String(stepNumber)] ?? generatedSas;
  return <details className="rounded-lg border border-slate-200 bg-white shadow-sm"><summary className="flex cursor-pointer items-center gap-2 px-4 py-3 text-sm font-semibold text-slate-950"><Code2 size={16} className="text-blue-600" /> Code & Reproducibility <span className="ml-auto text-xs font-normal text-slate-500">Python executable | SAS-compatible template</span></summary><div className="border-t border-slate-200 p-4"><CodeWorkspacePanel languages={[{ language: "python", label: "Python", supportBadge: state.code?.python.runtimeStatus ?? "Pending formulation", generatedCode: generatedPython, userCode: python, setUserCode: (value) => update({ userPythonByStep: { ...state.userPythonByStep, [String(stepNumber)]: value } }), note: "Executable SciPy HiGHS formulation using the normalized route model and exact confirmed coefficients.", runLabel: "Run Python", canRun: Boolean(state.formulation), running: busy === "code", result: codeResult, onRun: () => void runCode(), onCopy: () => void navigator.clipboard.writeText(python), onSave: () => saveCodeToNotebook("python") }, { language: "sas", label: "SAS-compatible", supportBadge: state.code?.sas.runtimeStatus ?? "Template-only", generatedCode: generatedSas, userCode: sas, setUserCode: (value) => update({ userSasByStep: { ...state.userSasByStep, [String(stepNumber)]: value } }), note: "PROC OPTMODEL template for execution in a licensed SAS environment. ATLAS does not present this as locally executed unless a supported runtime is connected.", runLabel: "Template only", canRun: false, onCopy: () => void navigator.clipboard.writeText(sas), onSave: () => saveCodeToNotebook("sas") }]} /><div className="mt-4 flex flex-wrap gap-2"><button type="button" disabled={!state.code?.python.code || busy === "export"} onClick={() => void exportPythonCode()} className="atlas-secondary-button inline-flex items-center gap-2"><Download size={15} /> Export Python</button><button type="button" disabled={!state.code?.sas.code || busy === "export"} onClick={() => void exportSasCode()} className="atlas-secondary-button inline-flex items-center gap-2"><Download size={15} /> Export SAS template</button><button type="button" onClick={() => saveCodeToNotebook("python")} className="atlas-secondary-button inline-flex items-center gap-2"><Plus size={15} /> Add to notebook</button><button type="button" disabled={!state.formulation || busy === "evidence"} onClick={captureEvidence} className="atlas-secondary-button inline-flex items-center gap-2"><ShieldCheck size={15} /> Capture code as evidence</button></div></div></details>;
}

function excludedRouteRationalesComplete(state: TransportationState) {
  const excluded = state.formulation?.routes.filter((route) => state.routeOverrides[route.route_id] === false) ?? [];
  return excluded.every((route) => Boolean(state.routeExclusionRationales[route.route_id]?.trim()));
}

function implementationPlanReady(state: TransportationState) {
  const thresholdsReady = state.monitoringThresholds.length >= 8 && state.monitoringThresholds.every((row) => row.metric.trim() && row.threshold.trim() && row.owner.trim() && row.cadence.trim() && row.escalation.trim());
  return Boolean(state.implementationOwner.trim() && state.routeExceptionProcess.trim() && state.fallbackPlan.trim() && state.monitoringMetrics.trim() && state.monitoringCadence.trim() && state.reoptimizationTrigger.trim() && state.reconciliationProcess.trim() && thresholdsReady);
}

function evidencePackageReady(state: TransportationState) {
  return deriveOptimizationEvidenceSummary(state).packageReady;
}

function documentationDisabledReason(state: TransportationState) {
  if (!state.reviewer.trim()) return "Enter final reviewer.";
  if (!state.approvalDate) return "Enter approval date.";
  if (state.recommendationStatus === "Draft") return "Recommendation remains Draft.";
  if (!state.validation?.recommendationAllowed || state.validation.score < 100) return "Validation score is incomplete.";
  if (!implementationPlanReady(state)) return "Implementation plan is incomplete.";
  if (!evidencePackageReady(state)) return "Evidence package is incomplete.";
  if (!state.generatedReport.trim()) return "Generate and inspect the Optimization Report before completing the study.";
  return "";
}

function transportationStepGate(stepNumber: number, state: TransportationState) {
  if (stepNumber === 1 && (!state.decisionTitle.trim() || !state.businessObjective.trim() || !state.decisionOwner.trim() || !state.population.trim() || !state.governanceBoundary.trim())) return "Define the decision, owner, objective, scope, and governance boundary.";
  if (stepNumber === 2 && (!state.formulation?.fullArtifact || !state.formulation.formulationReady)) return "Register all four required full artifacts and normalize a valid transportation formulation.";
  if (stepNumber === 3 && (!state.formulation?.formulationReady || !state.formulationConfirmed)) return "Review all readiness checks and confirm formulation-ready inputs.";
  if (stepNumber === 4 && (!state.objectiveName.trim() || !state.objectiveUnit.trim() || !state.horizon.trim())) return "Confirm the route-level cost objective, unit, and planning horizon.";
  if (stepNumber === 5 && !state.formulation?.routes.some((route) => state.routeOverrides[route.route_id] !== false)) return "Retain at least one active route variable.";
  if (stepNumber === 5 && !excludedRouteRationalesComplete(state)) return "Enter an exclusion rationale for every excluded route.";
  if (stepNumber === 6 && ((state.formulation?.metrics.demandConstraintCount ?? 0) === 0 || (state.formulation?.metrics.transportConstraintCount ?? 0) === 0)) return "Generate demand, supply, and transport-capacity constraints.";
  if (stepNumber === 6 && state.formulation?.constraints.some((row) => !state.constraintApprovals[row.name])) return "Review and approve every generated demand, supply, and transport-capacity rule.";
  if (stepNumber === 6 && !state.executableRulesValidated) return "Validate the executable rules after approving all generated constraints.";
  if (stepNumber === 7 && (!state.formulation?.formulationReady || state.method !== "Linear programming (LP)")) return "Complete formulation checks and retain the supported LP solver configuration.";
  if (stepNumber === 8 && !state.scenarioAnalysis?.results.length) return "Run all configured transportation scenarios.";
  if (stepNumber === 9 && !state.result?.success) return "Run the solver and obtain a business-valid, nonzero allocation.";
  if (stepNumber === 10 && !state.sensitivity?.available) return "Run sensitivity on the saved business-valid solution.";
  if (stepNumber === 11 && !state.validation?.recommendationAllowed) return "Pass mathematical checks and actively confirm governance acceptance.";
  if (stepNumber === 12 && (!state.recommendation.trim() || !state.recommendationOwner.trim() || state.recommendationStatus === "Draft")) return "Select a non-draft recommendation status and enter a recommendation owner.";
  if (stepNumber === 13 && !implementationPlanReady(state)) return "Define implementation ownership, exceptions, fallback, monitoring, re-optimization, and reconciliation.";
  if (stepNumber === 14) return documentationDisabledReason(state);
  return "";
}

function MissingFormulation() { return <EmptyState title="Route-level formulation is not available" body="Return to Data Acquisition and normalize the required transportation input bundle." />; }
function EmptyState({ title, body, action }: { title: string; body: string; action?: ReactNode }) { return <div className="flex min-h-52 flex-col items-center justify-center rounded-lg border border-dashed border-slate-300 bg-slate-50 px-6 py-8 text-center"><Database size={27} className="text-blue-600" /><div className="mt-3 font-semibold text-slate-950">{title}</div><p className="mt-1 max-w-xl text-sm leading-6 text-slate-600">{body}</p>{action && <div className="mt-4">{action}</div>}</div>; }
function Meta({ label, value }: { label: string; value: ReactNode }) { return <div className="min-w-0"><dt className="text-[9px] font-semibold uppercase tracking-wide text-slate-500">{label}</dt><dd className="mt-0.5 break-words font-semibold text-slate-800">{value}</dd></div>; }
function TextField({ label, value, onChange, type = "text" }: { label: string; value: string; onChange: (value: string) => void; type?: string }) { return <label className="grid content-start gap-1.5"><span className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">{label}</span><input type={type} className={fieldClass()} value={value} onChange={(event) => onChange(event.target.value)} onInput={type === "date" ? (event) => onChange(event.currentTarget.value) : undefined} /></label>; }
function TextArea({ label, value, onChange, rows = 4, documentEditor = false }: { label: string; value: string; onChange: (value: string) => void; rows?: number; documentEditor?: boolean }) { return <label className="grid content-start gap-1.5"><span className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">{label}</span><textarea rows={rows} className={`${fieldClass()} resize-y ${documentEditor ? "min-h-40 bg-white leading-6 shadow-inner" : ""}`} value={value} onChange={(event) => onChange(event.target.value)} />{documentEditor && <span className="text-right text-[10px] text-slate-400">{value.trim() ? value.trim().split(/\s+/).length : 0} words</span>}</label>; }
function NumberField({ label, value, onChange, step = 1 }: { label: string; value: number; onChange: (value: number) => void; step?: number }) { return <label className="grid content-start gap-1.5"><span className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">{label}</span><input type="number" step={step} className={fieldClass()} value={value} onChange={(event) => onChange(Number(event.target.value))} /></label>; }
function SelectField({ label, value, options, onChange, guidance }: { label: string; value: string; options: string[]; onChange: (value: string) => void; guidance?: string }) { return <label className="grid content-start gap-1.5"><span className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">{label}</span><select data-guidance-label={label} className={fieldClass()} value={value} onChange={(event) => onChange(event.target.value)}>{options.map((option) => <option key={option} value={option}>{option}</option>)}</select>{guidance && <span className="text-[11px] leading-4 text-slate-500"><strong className="text-slate-700">Best used when:</strong> {guidance}</span>}</label>; }
function Checklist({ items }: { items: string[] }) { return <ul className="grid gap-3 text-sm leading-6 text-slate-700">{items.map((item) => <li key={item} className="flex items-start gap-2"><ShieldCheck size={16} className="mt-1 shrink-0 text-emerald-600" /><span>{item}</span></li>)}</ul>; }
function KpiGrid({ rows }: { rows: Array<[string, ReactNode]> }) { return <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">{rows.map(([label, value]) => <div key={label} className="rounded-lg border border-slate-200 bg-white p-3"><div className="text-[10px] font-semibold uppercase tracking-wide text-slate-500">{label}</div><div className="mt-1 break-words text-sm font-bold text-slate-950">{value}</div></div>)}</div>; }
function DataTable({ headers, rows }: { headers: string[]; rows: Array<Array<ReactNode>> }) { return <div className="max-h-[540px] overflow-auto rounded-lg border border-slate-200"><table className="min-w-full border-collapse text-sm"><thead className="sticky top-0 z-[1] bg-slate-950 text-left text-[10px] uppercase tracking-wide text-slate-200"><tr>{headers.map((header) => <th key={header} className="whitespace-nowrap px-3 py-3">{header}</th>)}</tr></thead><tbody className="divide-y divide-slate-100 bg-white">{rows.length ? rows.map((row, index) => <tr key={index} className="hover:bg-blue-50/40">{row.map((value, column) => <td key={`${index}-${column}`} className="whitespace-nowrap px-3 py-2.5 text-slate-700 first:font-semibold first:text-slate-950">{value}</td>)}</tr>) : <tr><td colSpan={headers.length} className="px-4 py-8 text-center text-slate-500">No evidence rows available.</td></tr>}</tbody></table></div>; }
