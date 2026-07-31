import { DATASET_API_BASE } from "./datasetLibrary";
import {
  assertExactDatasetIdentity,
  requireCanonicalDatasetIdentity,
  type CanonicalDatasetIdentity,
} from "./datasetIdentity";
import type { CreditRiskContext, CreditRiskEvidenceChecklist, FinancialDomain, RegulatoryRelevance } from "./financialServicesEvidence";
import { saveEvidenceToDatabase, updateEvidenceInDatabase } from "./serverPersistence";

export type EvidenceType =
  | "dataset"
  | "sql_query"
  | "sql_result"
  | "eda"
  | "missing_values"
  | "outliers"
  | "feature_engineering"
  | "vif"
  | "model_training"
  | "model_selection"
  | "evaluation"
  | "model_diagnostics"
  | "chart"
  | "notebook"
  | "documentation"
  | "governance"
  | "decision"
  | "export"
  | "optimization_decision_charter"
  | "optimization_input_bundle"
  | "optimization_data_profile"
  | "optimization_route_normalization"
  | "optimization_formulation_readiness"
  | "optimization_objective"
  | "optimization_decision_variables"
  | "optimization_constraints"
  | "optimization_solver_configuration"
  | "optimization_baseline"
  | "optimization_scenarios"
  | "optimization_solver_run"
  | "optimization_solution"
  | "optimization_sensitivity"
  | "optimization_validation"
  | "optimization_recommendation"
  | "optimization_implementation_plan"
  | "optimization_monitoring_plan"
  | "optimization_documentation_package"
  | "optimization_reproducibility_code"
  | "optimization_code_reproducibility";

export type EvidenceStatus = "draft" | "ready" | "needs_review" | "accepted" | "deprecated";
export type EvidenceImportance = "low" | "medium" | "high" | "critical";

export type EvidenceCanonicalLineage = CanonicalDatasetIdentity & {
  lineage_contract: "canonical_dataset_version";
} & Record<string, unknown>;

export type EvidenceItem = {
  evidenceId: string;
  lineage_contract?: "canonical_dataset_version";
  project_id?: string;
  dataset_id?: string;
  dataset_version_id?: string;
  projectId?: string;
  projectName?: string;
  evidenceType: EvidenceType;
  title: string;
  summary: string;
  sourcePage?: string;
  sourceRoute?: string;
  artifactType?: string;
  artifactId?: string;
  datasetIds: string[];
  modelIds: string[];
  documentIds: string[];
  notebookIds: string[];
  supportsSections: string[];
  tags: string[];
  financialDomain?: FinancialDomain | "";
  financialTechnique?: string;
  regulatoryRelevance?: RegulatoryRelevance;
  creditRiskContext?: CreditRiskContext;
  status: EvidenceStatus;
  importance: EvidenceImportance;
  qualityScore?: number;
  createdAt?: string;
  capturedAt?: string;
  updatedAt?: string;
  createdBy?: string;
  workflowStep?: string;
  sourceRunReference?: string;
  lineage?: EvidenceCanonicalLineage | Record<string, unknown>;
  payload?: Record<string, unknown>;
  governance?: Record<string, unknown>;
};

export type EvidenceCoverage = {
  projectId: string;
  workflowType?: string;
  totalEvidence: number;
  readyEvidence: number;
  needsReviewEvidence: number;
  coverageScore: number;
  categories: Array<{ category: string; count: number; ready: number; status: "ready" | "missing" | "needs_review" | string }>;
  warnings: string[];
  missingRecommended: string[];
  financialServices?: {
    suggestedDomain?: { domain: string; label: string; confidence: number };
    creditRisk?: CreditRiskEvidenceChecklist;
    placeholders?: Record<string, string>;
  };
};

export type EvidenceGraphNode = {
  id: string;
  label: string;
  kind?: string;
  type: string;
  status?: string;
  importance?: string;
  sourcePage?: string;
  evidenceId?: string;
  x?: number;
  y?: number;
  metadata?: Record<string, unknown>;
};

export type EvidenceGraphEdge = {
  id: string;
  source: string;
  target: string;
  from?: string;
  to?: string;
  label: string;
  type: string;
};

export type EvidenceGraphPayload = {
  nodes: EvidenceGraphNode[];
  edges: EvidenceGraphEdge[];
};

export const EVIDENCE_TYPES: EvidenceType[] = [
  "dataset",
  "sql_query",
  "sql_result",
  "eda",
  "missing_values",
  "outliers",
  "feature_engineering",
  "vif",
  "model_training",
  "model_selection",
  "evaluation",
  "model_diagnostics",
  "chart",
  "notebook",
  "documentation",
  "governance",
  "decision",
  "export",
  "optimization_decision_charter",
  "optimization_input_bundle",
  "optimization_data_profile",
  "optimization_route_normalization",
  "optimization_formulation_readiness",
  "optimization_objective",
  "optimization_decision_variables",
  "optimization_constraints",
  "optimization_solver_configuration",
  "optimization_baseline",
  "optimization_scenarios",
  "optimization_solver_run",
  "optimization_solution",
  "optimization_sensitivity",
  "optimization_validation",
  "optimization_recommendation",
  "optimization_implementation_plan",
  "optimization_monitoring_plan",
  "optimization_documentation_package",
  "optimization_reproducibility_code",
  "optimization_code_reproducibility",
];

export const FINANCIAL_SERVICES_TAGS = [
  "credit_risk",
  "fraud",
  "aml",
  "marketing",
  "profitability",
  "model_risk",
  "fair_lending",
  "underwriting",
  "portfolio_management",
  "monitoring",
  "governance",
];

export const DOCUMENTATION_SECTION_OPTIONS = [
  "Executive Summary",
  "Business Objective",
  "Data Sources",
  "Data Quality",
  "Population Definition",
  "Target Definition",
  "Feature Engineering",
  "Candidate Models",
  "Champion Model",
  "Performance Summary",
  "Model Diagnostics",
  "Interpretability Notes",
  "Fair Lending / Compliance Considerations",
  "Monitoring Recommendations",
  "Decision Journal Appendix",
  "Appendix",
];

async function jsonFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${DATASET_API_BASE}${path}`, {
    credentials: "include",
    ...init,
    headers: {
      ...(init?.body instanceof FormData ? {} : { "Content-Type": "application/json" }),
      ...(init?.headers ?? {}),
    },
  });
  const payload = await response.json().catch(() => null);
  if (!response.ok || payload?.ok === false) {
    throw new Error(payload?.detail ?? payload?.error ?? `ATLAS evidence request failed with HTTP ${response.status}.`);
  }
  return payload as T;
}

function queryString(filters: Record<string, string | undefined>) {
  const params = new URLSearchParams();
  Object.entries(filters).forEach(([key, value]) => {
    if (value) params.set(key, value);
  });
  const text = params.toString();
  return text ? `?${text}` : "";
}

export function evidenceQualityScore(item: Partial<EvidenceItem>) {
  const checks = [
    Boolean(item.sourcePage || item.sourceRoute),
    Boolean(item.projectId),
    Boolean(item.datasetIds?.length),
    Boolean(item.summary),
    Boolean(item.lineage && Object.keys(item.lineage).length),
    Boolean(item.supportsSections?.length),
    Boolean(item.governance && Object.keys(item.governance).length),
  ];
  return Math.round((checks.filter(Boolean).length / checks.length) * 100);
}

export function recommendedStatusFromQuality(score: number): EvidenceStatus {
  if (score >= 85) return "ready";
  if (score < 55) return "needs_review";
  return "draft";
}

export async function listEvidence(filters: Record<string, string | undefined> = {}) {
  const payload = await jsonFetch<{ ok: true; items: EvidenceItem[]; count: number }>(`/evidence${queryString(filters)}`);
  return payload.items;
}

export async function createEvidence(input: Partial<EvidenceItem>) {
  const canonicalClaimed =
    input.lineage_contract === "canonical_dataset_version" ||
    Boolean(input.project_id || input.dataset_id || input.dataset_version_id);
  const canonical = canonicalClaimed
    ? requireCanonicalDatasetIdentity(input, "Evidence create request")
    : null;
  const payload = await jsonFetch<{ ok: true; evidence: EvidenceItem }>("/evidence", {
    method: "POST",
    body: JSON.stringify(input),
  });
  if (canonical) {
    assertExactDatasetIdentity(
      canonical,
      payload.evidence,
      "Evidence persistence response",
    );
  }
  if (payload.evidence.projectId) void saveEvidenceToDatabase(payload.evidence.projectId, payload.evidence as unknown as Record<string, unknown>);
  return payload.evidence;
}

export async function updateEvidence(evidenceId: string, input: Partial<EvidenceItem>) {
  const payload = await jsonFetch<{ ok: true; evidence: EvidenceItem }>(`/evidence/${encodeURIComponent(evidenceId)}`, {
    method: "PUT",
    body: JSON.stringify(input),
  });
  if (payload.evidence.projectId) {
    void updateEvidenceInDatabase(payload.evidence.projectId, evidenceId, payload.evidence as unknown as Record<string, unknown>);
  }
  return payload.evidence;
}

export async function deleteEvidence(evidenceId: string) {
  return jsonFetch<{ ok: true; deleted: boolean }>(`/evidence/${encodeURIComponent(evidenceId)}`, { method: "DELETE" });
}

export async function getEvidence(evidenceId: string) {
  const payload = await jsonFetch<{ ok: true; evidence: EvidenceItem }>(`/evidence/${encodeURIComponent(evidenceId)}`);
  return payload.evidence;
}

export async function getProjectEvidence(projectId: string) {
  const payload = await jsonFetch<{ ok: true; items: EvidenceItem[]; count: number }>(`/evidence/project/${encodeURIComponent(projectId)}`);
  return payload.items;
}

export async function getDatasetEvidence(datasetId: string) {
  const payload = await jsonFetch<{ ok: true; items: EvidenceItem[]; count: number }>(`/evidence/dataset/${encodeURIComponent(datasetId)}`);
  return payload.items;
}

export async function getEvidenceGraph(projectId?: string) {
  const payload = await jsonFetch<{ ok: true; graph: EvidenceGraphPayload }>(`/evidence/graph${projectId ? `?projectId=${encodeURIComponent(projectId)}` : ""}`);
  return payload.graph;
}

export async function getEvidenceCoverage(projectId: string) {
  const payload = await jsonFetch<{ ok: true; coverage: EvidenceCoverage }>(`/evidence/coverage/${encodeURIComponent(projectId)}`);
  return payload.coverage;
}

export async function autoCaptureEvidence(input: { projectId?: string; projectName?: string }) {
  const payload = await jsonFetch<{ ok: true; items: EvidenceItem[]; count: number }>("/evidence/auto-capture", {
    method: "POST",
    body: JSON.stringify(input),
  });
  return payload.items;
}

export async function exportEvidencePack(projectId?: string) {
  const response = await fetch(`${DATASET_API_BASE}/evidence/export/excel`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ projectId }),
  });
  if (!response.ok) throw new Error("ATLAS could not export the evidence pack.");
  return response.blob();
}
