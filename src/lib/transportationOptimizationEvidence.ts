import type {
  TransportationFormulation,
  TransportationGeneratedCode,
  TransportationScenarioAnalysis,
  TransportationSensitivity,
  TransportationSolveResult,
  TransportationValidation,
} from "./optimizationWorkflow";
import { summarizeOptimizationEvidenceRecords } from "./persistedEvidenceStatus";

export const TRANSPORTATION_OPTIMIZATION_STORAGE_PREFIX = "atlas-optimization-transportation";

export type OptimizationEvidenceStage =
  | "decision_charter"
  | "input_bundle"
  | "route_normalization"
  | "formulation_readiness"
  | "objective"
  | "decision_variables"
  | "constraints"
  | "solver_configuration"
  | "scenarios"
  | "solution"
  | "sensitivity"
  | "validation"
  | "recommendation"
  | "implementation_plan"
  | "monitoring_plan"
  | "documentation_package"
  | "code_reproducibility";

export type OptimizationExportKind = "governed_json" | "allocation_csv" | "reproducibility_evidence" | "python_code" | "sas_code" | "optimization_report";

export type OptimizationExportRecord = {
  kind: OptimizationExportKind;
  fileName: string;
  artifactReference: string;
  evidenceId?: string;
  generatedAt: string;
  byteCount: number;
  status: "ready" | "failed";
};

export type OptimizationMonitoringThreshold = {
  id: string;
  metric: string;
  threshold: string;
  owner: string;
  cadence: string;
  escalation: string;
  status: "Active" | "Draft" | "Paused";
};

export type TransportationOptimizationSnapshot = {
  templateId?: string;
  decisionTitle?: string;
  decisionOwner?: string;
  businessObjective?: string;
  population?: string;
  objectiveName?: string;
  objectiveUnit?: string;
  horizon?: string;
  method?: string;
  tolerance?: number;
  timeLimitSeconds?: number;
  formulation?: TransportationFormulation | null;
  formulationConfirmed?: boolean;
  constraintApprovals?: Record<string, boolean>;
  executableRulesValidated?: boolean;
  scenarioAnalysis?: TransportationScenarioAnalysis | null;
  result?: TransportationSolveResult | null;
  sensitivity?: TransportationSensitivity | null;
  validation?: TransportationValidation | null;
  recommendation?: string;
  recommendationOwner?: string;
  recommendationStatus?: "Draft" | "Recommended" | "Approved" | "Returned" | "Rejected";
  alternatives?: string;
  residualRisks?: string;
  implementationOwner?: string;
  effectiveDate?: string;
  routeExceptionProcess?: string;
  fallbackPlan?: string;
  monitoringMetrics?: string;
  monitoringCadence?: string;
  monitoringThresholds?: OptimizationMonitoringThreshold[];
  reoptimizationTrigger?: string;
  reconciliationProcess?: string;
  reviewer?: string;
  approvalDate?: string;
  code?: TransportationGeneratedCode | null;
  evidenceByStep?: Partial<Record<OptimizationEvidenceStage | string, string>>;
  exportArtifacts?: Partial<Record<OptimizationExportKind, OptimizationExportRecord>>;
  generatedReport?: string;
  generatedReportAt?: string;
  studyCompleted?: boolean;
  completedAt?: string;
  evidencePackageReference?: string;
  savedAt?: string;
};

export const TRANSPORTATION_EVIDENCE_STAGES: Array<{
  stage: OptimizationEvidenceStage;
  evidenceType: string;
  label: string;
  stepNumber: number;
  sections: string[];
}> = [
  { stage: "decision_charter", evidenceType: "optimization_decision_charter", label: "Decision charter", stepNumber: 1, sections: ["Executive Summary", "Business Decision"] },
  { stage: "input_bundle", evidenceType: "optimization_input_bundle", label: "Input bundle", stepNumber: 2, sections: ["Data Inputs"] },
  { stage: "route_normalization", evidenceType: "optimization_route_normalization", label: "Route normalization", stepNumber: 2, sections: ["Data Inputs", "Formulation Readiness"] },
  { stage: "formulation_readiness", evidenceType: "optimization_formulation_readiness", label: "Formulation readiness", stepNumber: 3, sections: ["Formulation Readiness"] },
  { stage: "objective", evidenceType: "optimization_objective", label: "Objective", stepNumber: 4, sections: ["Objective Function"] },
  { stage: "decision_variables", evidenceType: "optimization_decision_variables", label: "Decision variables", stepNumber: 5, sections: ["Decision Variables"] },
  { stage: "constraints", evidenceType: "optimization_constraints", label: "Constraints", stepNumber: 6, sections: ["Constraints"] },
  { stage: "solver_configuration", evidenceType: "optimization_solver_configuration", label: "Solver configuration", stepNumber: 7, sections: ["Solver Configuration"] },
  { stage: "scenarios", evidenceType: "optimization_scenarios", label: "Scenarios", stepNumber: 8, sections: ["Baseline and Scenarios"] },
  { stage: "solution", evidenceType: "optimization_solution", label: "Solver solution", stepNumber: 9, sections: ["Optimization Results"] },
  { stage: "sensitivity", evidenceType: "optimization_sensitivity", label: "Sensitivity", stepNumber: 10, sections: ["Sensitivity and Tradeoffs"] },
  { stage: "validation", evidenceType: "optimization_validation", label: "Validation", stepNumber: 11, sections: ["Validation"] },
  { stage: "recommendation", evidenceType: "optimization_recommendation", label: "Recommendation", stepNumber: 12, sections: ["Recommendation"] },
  { stage: "implementation_plan", evidenceType: "optimization_implementation_plan", label: "Implementation plan", stepNumber: 13, sections: ["Implementation Plan"] },
  { stage: "monitoring_plan", evidenceType: "optimization_monitoring_plan", label: "Monitoring plan", stepNumber: 13, sections: ["Monitoring Plan"] },
  { stage: "documentation_package", evidenceType: "optimization_documentation_package", label: "Documentation package", stepNumber: 14, sections: ["Approvals", "Limitations"] },
  { stage: "code_reproducibility", evidenceType: "optimization_reproducibility_code", label: "Reproducibility code", stepNumber: 14, sections: ["Reproducibility Appendix", "Python Code", "SAS-Compatible Code"] },
];

export const DEFAULT_TRANSPORTATION_MONITORING_THRESHOLDS: OptimizationMonitoringThreshold[] = [
  { id: "demand_variance", metric: "Demand variance", threshold: "Greater than 10% from planned", owner: "Operations planning owner", cadence: "Daily during execution", escalation: "Rerun optimization or approve an exception", status: "Active" },
  { id: "route_cost_variance", metric: "Route cost variance", threshold: "Greater than 10%", owner: "Logistics cost owner", cadence: "Daily or closeout", escalation: "Investigate the route-cost driver", status: "Active" },
  { id: "supplier_capacity", metric: "Supplier capacity breach", threshold: "Any breach", owner: "Supplier operations owner", cadence: "Daily during execution", escalation: "Stop route allocation or rerun optimization", status: "Active" },
  { id: "transport_capacity", metric: "Transport capacity breach", threshold: "Any breach", owner: "Transportation owner", cadence: "Daily during execution", escalation: "Rerun with updated capacity", status: "Active" },
  { id: "unmet_demand", metric: "Unmet demand", threshold: "Any nonzero unmet demand", owner: "Service-level owner", cadence: "Daily during execution", escalation: "Emergency reallocation or management approval", status: "Active" },
  { id: "override_rate", metric: "Override rate", threshold: "Greater than 5%", owner: "Optimization governance owner", cadence: "Daily during execution", escalation: "Review route exceptions", status: "Active" },
  { id: "route_block", metric: "Material route block", threshold: "Any material route block", owner: "Network operations owner", cadence: "Real time or daily", escalation: "Rerun or use an approved fallback route", status: "Active" },
  { id: "cost_overrun", metric: "Cost overrun", threshold: "Greater than 10%", owner: "Finance owner", cadence: "Closeout", escalation: "Document variance and update assumptions", status: "Active" },
];

export function loadTransportationOptimizationSnapshot(projectId: string): TransportationOptimizationSnapshot | null {
  if (typeof window === "undefined") return null;
  try {
    const parsed = JSON.parse(localStorage.getItem(`${TRANSPORTATION_OPTIMIZATION_STORAGE_PREFIX}:${projectId}`) || "null");
    return parsed && typeof parsed === "object" ? parsed as TransportationOptimizationSnapshot : null;
  } catch {
    return null;
  }
}

export function optimizationImplementationReady(state: TransportationOptimizationSnapshot | null | undefined) {
  if (!state) return false;
  return Boolean(
    state.implementationOwner?.trim()
    && state.routeExceptionProcess?.trim()
    && state.fallbackPlan?.trim()
    && state.monitoringMetrics?.trim()
    && state.monitoringCadence?.trim()
    && state.reoptimizationTrigger?.trim()
    && state.reconciliationProcess?.trim()
    && (state.monitoringThresholds?.length ?? 0) >= 8,
  );
}

export function optimizationDocumentationSectionCount(state: TransportationOptimizationSnapshot | null | undefined) {
  if (!state) return 0;
  const formulation = state.formulation;
  const result = state.result;
  const readiness = [
    Boolean(state.decisionTitle && state.businessObjective),
    Boolean(state.decisionTitle && state.businessObjective),
    Boolean(formulation?.formulationReady),
    Boolean(formulation?.formulationReady),
    Boolean(formulation?.formulationReady),
    Boolean(formulation?.formulationReady),
    Boolean(formulation?.formulationReady),
    Boolean(result?.success),
    Boolean(result?.success && state.scenarioAnalysis),
    Boolean(result?.success),
    Boolean(state.sensitivity?.available),
    Boolean(state.validation),
    Boolean(state.recommendation && state.recommendationStatus !== "Draft"),
    optimizationImplementationReady(state),
    optimizationImplementationReady(state),
    Boolean(state.residualRisks),
    Boolean(state.reviewer && state.approvalDate),
    Boolean(state.code),
    Boolean(state.code?.python.code),
    Boolean(state.code?.sas.code),
  ];
  return readiness.filter(Boolean).length;
}

export function optimizationStageGenerated(state: TransportationOptimizationSnapshot | null | undefined, stage: OptimizationEvidenceStage) {
  if (!state) return false;
  const formulation = state.formulation;
  const constraintsApproved = Boolean(formulation?.constraints.length && formulation.constraints.every((row) => state.constraintApprovals?.[row.name]));
  switch (stage) {
    case "decision_charter": return Boolean(state.decisionTitle && state.businessObjective && state.decisionOwner);
    case "input_bundle": return Boolean(formulation?.fullArtifact);
    case "route_normalization": return Boolean(formulation?.fullArtifact && formulation.normalizationHash && formulation.routes.length);
    case "formulation_readiness": return Boolean(formulation?.formulationReady && state.formulationConfirmed);
    case "objective": return Boolean(formulation?.objective && state.objectiveName && state.objectiveUnit && state.horizon);
    case "decision_variables": return Boolean(formulation?.variables.length);
    case "constraints": return Boolean(constraintsApproved && state.executableRulesValidated);
    case "solver_configuration": return Boolean(state.method && formulation);
    case "scenarios": return Boolean(state.scenarioAnalysis?.results.length);
    case "solution": return Boolean(state.result?.success);
    case "sensitivity": return Boolean(state.sensitivity?.available);
    case "validation": return Boolean(state.validation?.recommendationAllowed);
    case "recommendation": return Boolean(state.recommendation && state.recommendationOwner && state.recommendationStatus !== "Draft");
    case "implementation_plan": return optimizationImplementationReady(state);
    case "monitoring_plan": return Boolean(optimizationImplementationReady(state) && state.monitoringThresholds?.length);
    case "documentation_package": return Boolean(state.studyCompleted || state.generatedReport || optimizationDocumentationSectionCount(state) === 20);
    case "code_reproducibility": return Boolean(state.code?.python.code && state.code?.sas.code);
  }
}

export function deriveOptimizationEvidenceSummary(state: TransportationOptimizationSnapshot | null | undefined) {
  const records = TRANSPORTATION_EVIDENCE_STAGES.map((definition) => {
    const generated = optimizationStageGenerated(state, definition.stage);
    const reference = state?.evidenceByStep?.[definition.stage] || (definition.stage === "documentation_package" ? state?.evidencePackageReference : "") || "";
    const captured = Boolean(reference);
    const approved = Boolean(captured && (state?.studyCompleted || (definition.stage === "validation" && state?.validation?.recommendationAllowed) || (definition.stage === "recommendation" && state?.recommendationStatus === "Approved")));
    return { ...definition, generated, captured, ready: generated && captured, approved, reference };
  });
  const generatedCount = records.filter((row) => row.generated).length;
  const capturedCount = records.filter((row) => row.captured).length;
  const readyCount = records.filter((row) => row.ready).length;
  const requiredCount = records.length;
  const allGenerated = records.every((row) => row.generated);
  const allCaptured = records.every((row) => row.captured);
  const packageReady = Boolean(allGenerated && allCaptured && optimizationDocumentationSectionCount(state) === 20);
  const packageApproved = Boolean(packageReady && state?.studyCompleted && state?.reviewer && state?.approvalDate);
  const sharedSummary = summarizeOptimizationEvidenceRecords(records);
  const coverageScore = packageReady ? 100 : sharedSummary.coverageScore;
  const statusLabel = packageReady ? "Evidence package ready" : sharedSummary.statusLabel;
  return {
    records,
    generatedCount,
    capturedCount,
    readyCount,
    requiredCount,
    coverageScore,
    packageReady,
    packageApproved,
    documentationReady: optimizationDocumentationSectionCount(state) === 20,
    documentationSectionCount: optimizationDocumentationSectionCount(state),
    statusLabel,
    actionLabel: packageReady ? "Open Evidence Package" : capturedCount || generatedCount ? "Capture Remaining Evidence" : "Capture Optimization Evidence",
  };
}

export type OptimizationWorkflowStatus = "Current" | "Evidence" | "Complete" | "Pending" | "Blocked";

export function optimizationWorkflowStepStatus(
  state: TransportationOptimizationSnapshot | null | undefined,
  stepNumber: number,
  options: { current?: boolean; storeComplete?: boolean } = {},
): OptimizationWorkflowStatus {
  if (options.current) return "Current";
  const stepRecords = TRANSPORTATION_EVIDENCE_STAGES
    .filter((row) => row.stepNumber === stepNumber)
    .map((row) => {
      const generated = optimizationStageGenerated(state, row.stage);
      const captured = Boolean(state?.evidenceByStep?.[row.stage]);
      return { generated, captured, ready: generated && captured };
    });
  const evidence = summarizeOptimizationEvidenceRecords(stepRecords);
  if (evidence.capturedCount > 0) return "Evidence";
  if (evidence.totalCount > 0 || options.storeComplete) return "Complete";
  const priorReady = stepNumber === 1 || TRANSPORTATION_EVIDENCE_STAGES.filter((row) => row.stepNumber < stepNumber).every((row) => optimizationStageGenerated(state, row.stage));
  return priorReady ? "Pending" : "Blocked";
}
