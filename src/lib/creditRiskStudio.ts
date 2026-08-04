import { DATASET_API_BASE } from "./datasetLibrary";
import type { EvidenceItem } from "./evidenceGraph";

export const PRODUCT_TYPES = ["Mortgage", "Auto", "Credit Card", "Personal Loan", "Portfolio", "Generic"];
export const MODEL_PURPOSES = [
  "Application Underwriting",
  "Account Management",
  "Portfolio Management",
  "Collections",
  "Line Assignment",
  "Pricing",
  "Monitoring",
];
export const TARGET_EVENTS = ["Default", "90+ DPD", "60+ DPD", "30+ DPD", "Charge-off", "Bankruptcy", "Loss", "Fraud", "Approval", "Response", "Attrition"];
export const TTC_PIT_OPTIONS = ["Through-the-Cycle", "Point-in-Time", "Hybrid", "Not Selected"];
export const VARIABLE_ROLES = [
  "Target",
  "Original Target Label / Excluded",
  "Split Indicator / Excluded",
  "Bureau",
  "Application",
  "Customer",
  "Behavioral",
  "Account",
  "Collateral",
  "Income",
  "Employment",
  "Geography",
  "Protected / Sensitive",
  "Excluded",
  "Unknown",
];

export type CreditRiskStatus = "Ready" | "Needs Review" | "Missing" | "Not Applicable";

export type CreditRiskVariableMapping = {
  variable: string;
  role: string;
  source: string;
  include: boolean;
  notes?: string;
};

export type CreditRiskModelingApproach = "scorecard" | "ml" | "compare_both";

export type CreditRiskMonotonicConstraint = {
  variable: string;
  expectedDirection: string;
  constraint: string;
  rationale: string;
  reviewerNote?: string;
};

export type CreditRiskChampionDecision = {
  selectedModelId?: string;
  selectedModelType?: string;
  reason?: string;
  reviewerNotes?: string;
  decidedAt?: string;
};

export type CreditRiskProfile = {
  profileId?: string;
  projectId: string;
  projectName?: string;
  datasetId?: string;
  datasetVersionId?: string;
  productType?: string;
  modelPurpose?: string;
  targetEvent?: string;
  targetColumn?: string;
  eventValue?: string;
  nonEventValue?: string;
  originalTargetLabelColumn?: string;
  splitColumn?: string;
  validationDatasetId?: string;
  ootDatasetId?: string;
  ootType?: string;
  targetSummary?: CreditRiskTargetSummary;
  targetWindow?: string;
  observationWindow?: string;
  performanceWindow?: string;
  modelType?: string;
  ttcPitAssumption?: string;
  regulatoryContext?: string[];
  goodDefinition?: string;
  badDefinition?: string;
  indeterminateDefinition?: string;
  performanceWindowStart?: string;
  performanceWindowEnd?: string;
  observationSnapshotDate?: string;
  outcomeSourceTable?: string;
  exclusionRules?: string;
  censoringNotes?: string;
  variableMappings?: CreditRiskVariableMapping[];
  featureReview?: Record<string, unknown>;
  scorecardScaling?: {
    scorecardStyleModel?: boolean;
    pdo?: number;
    baseScore?: number;
    baseOdds?: string;
    factor?: number;
    offset?: number;
    scoreDirection?: string;
    minScore?: number;
    maxScore?: number;
    oddsCalibrationApproach?: string;
    referencePopulation?: string;
    notes?: string;
  };
  explainability?: Record<string, unknown>;
  decisionStrategy?: Record<string, unknown>;
  monitoring?: Record<string, unknown>;
  readiness?: Record<string, CreditRiskStatus>;
  readinessScore?: number;
  selectedModelingApproach?: CreditRiskModelingApproach;
  scorecardModelId?: string;
  mlModelId?: string;
  championModelId?: string;
  championModelType?: "scorecard" | "ml";
  scorecardStatus?: CreditRiskStatus | string;
  mlStatus?: CreditRiskStatus | string;
  comparisonStatus?: CreditRiskStatus | string;
  championDecisionStatus?: CreditRiskStatus | string;
  monotonicConstraints?: CreditRiskMonotonicConstraint[];
  championDecision?: CreditRiskChampionDecision;
  edaStatus?: CreditRiskStatus;
  screeningStatus?: CreditRiskStatus;
  woeIvStatus?: CreditRiskStatus;
  scorecardModelStatus?: CreditRiskStatus;
  pdoStatus?: CreditRiskStatus;
  validationStatus?: CreditRiskStatus;
  cutoffStrategyStatus?: CreditRiskStatus;
  adverseActionStatus?: CreditRiskStatus;
  monitoringStatus?: CreditRiskStatus;
  evidenceStatus?: CreditRiskStatus;
  createdAt?: string;
  updatedAt?: string;
};

export type CreditRiskSpecialValueProfile = {
  variable: string;
  countMinus7: number;
  countMinus8: number;
  countMinus9: number;
  specialValueCount: number;
  specialValueRate: number;
  recommendedTreatment: string;
};

export type DevelopmentScopeMetadata = {
  analytical_scope?: "development_population";
  analysis_scope?: "development_population";
  target_directed_scope?: "development_population";
  population_id?: string;
  population_count?: number;
  partition_id?: string;
  partition_revision?: number;
  analysis_partition_id?: string;
  analysis_partition_revision?: number;
  development_partition_id?: string;
  sealed_holdout_partition_id?: string;
  holdout_excluded?: boolean;
  source_checksum?: string;
  actor?: string;
  timestamp?: string;
};

export type ExactCreditRiskIdentity = {
  projectId: string;
  datasetId: string;
  datasetVersionId: string;
  targetColumn?: string;
};

export type CreditRiskTargetSummary = DevelopmentScopeMetadata & {
  projectId: string;
  datasetId: string;
  datasetVersionId: string;
  datasetName?: string;
  targetColumn: string;
  eventValue: string;
  nonEventValue?: string;
  scope: "development_population";
  rowCount: number;
  profiledRows: number;
  totalRows: number;
  structuralRowCount?: number;
  goodCount: number;
  badCount: number;
  badRate: number;
  indeterminateCount: number;
  missingTargetCount: number;
  fullDatasetAvailable: boolean;
  message?: string;
  specialValueProfile: CreditRiskSpecialValueProfile[];
};

export type CreditRiskMlTrainRequest = {
  projectId: string;
  datasetId: string;
  datasetVersionId: string;
  targetColumn: string;
  eventValue: string | number | boolean;
  selectedVariables: string[];
  modelType: string;
  trainValidationSplit: number;
  classWeight?: string;
  calibrationMethod?: string;
  monotonicConstraints?: CreditRiskMonotonicConstraint[];
  evaluationMetric?: string;
};

export type CreditRiskMlModel = DevelopmentScopeMetadata & {
  modelId: string;
  projectId: string;
  datasetId: string;
  datasetVersionId: string;
  targetColumn: string;
  eventValue: string | number | boolean;
  modelType: string;
  selectedVariables: string[];
  rowCount: number;
  eventRate: number;
  metrics: {
    auc?: number | null;
    ks?: number | null;
    gini?: number | null;
    logLoss?: number | null;
    prAuc?: number | null;
  };
  featureImportance: Array<{ feature: string; importance: number; direction?: string }>;
  scoreDistribution: Array<Record<string, unknown>>;
  decileLift: Array<Record<string, unknown>>;
  calibrationTable: Array<Record<string, unknown>>;
  warnings?: string[];
  generatedAt?: string;
  updatedAt?: string;
};

export type WoeIvBin = {
  binId: string;
  label: string;
  lowerBound?: number | null;
  upperBound?: number | null;
  categoryValues?: string[];
  totalCount: number;
  goodCount: number;
  badCount: number;
  badRate: number;
  populationPct: number;
  distGood: number;
  distBad: number;
  woe: number;
  ivContribution: number;
  smoothingApplied?: boolean;
  manualOverride?: boolean;
  reviewerNote?: string;
};

export type WoeIvVariableSummary = {
  variable: string;
  variableType: "numeric" | "categorical" | string;
  iv: number;
  predictiveStrength: string;
  monotonicity: string;
  missingRate: number;
  distinctCount: number;
  binCount: number;
  status: "ready" | "needs_review" | string;
  recommendation: string;
  warnings: string[];
  bins: WoeIvBin[];
};

export type WoeIvAnalysis = DevelopmentScopeMetadata & {
  analysisId: string;
  projectId: string;
  datasetId: string;
  datasetVersionId: string;
  datasetName?: string;
  targetColumn: string;
  eventValue: string | number | boolean;
  rowCount: number;
  eventCount: number;
  nonEventCount: number;
  eventRate: number;
  settings: WoeIvRunRequest;
  variableSummaries: WoeIvVariableSummary[];
  generatedCode?: Record<string, string>;
  evidenceIds?: string[];
  warnings?: string[];
  generatedAt?: string;
  updatedAt?: string;
};

export type WoeIvRunRequest = {
  projectId: string;
  datasetId: string;
  datasetVersionId: string;
  targetColumn: string;
  eventValue: string | number | boolean;
  predictorColumns: string[];
  binningMethod: "quantile" | "equal_width" | "tree" | "monotonic" | string;
  maxBins: number;
  minBinPct: number;
  smoothing: number;
  excludeMissingFromBins?: boolean;
};

export type WoeIvManualBin = {
  binId?: string;
  label: string;
  lowerBound?: number | null;
  upperBound?: number | null;
  categoryValues?: string[];
  isMissingBin?: boolean;
  manualOverride?: boolean;
  reviewerNote?: string;
};

export type ScorecardTrainRequest = {
  projectId: string;
  datasetId: string;
  datasetVersionId: string;
  targetColumn: string;
  eventValue: string | number | boolean;
  woeAnalysisId?: string;
  selectedVariables: string[];
  trainValidationSplit: number;
  crossValidationFolds: number;
  modelType: string;
  regularization: string;
  regularizationC: number;
  classWeight?: string | null;
  trainRawBaseline?: boolean;
  pdo: number;
  baseScore: number;
  baseOdds: string;
  scoreDirection: string;
  minScore?: number;
  maxScore?: number;
  averageBalance?: number;
  lossGivenDefault?: number;
  revenuePerBookedAccount?: number;
  operationalApprovalTarget?: number;
  maximumBadRate?: number;
};

export type ScorecardModel = DevelopmentScopeMetadata & {
  modelId: string;
  projectId: string;
  datasetId: string;
  datasetVersionId: string;
  targetColumn: string;
  eventValue: string | number | boolean;
  modelType: string;
  woeAnalysisId?: string;
  selectedVariables: string[];
  transformSummary: Record<string, unknown>;
  coefficients: Array<{ variable: string; coefficient: number }>;
  intercept: number;
  pdoSettings: {
    pdo: number;
    baseScore: number;
    baseOdds: string;
    scoreDirection: string;
    factor: number;
    offset: number;
    minScore?: number;
    maxScore?: number;
  };
  metrics: {
    auc?: number | null;
    ks?: number | null;
    gini?: number | null;
    logLoss?: number | null;
    eventRate?: number;
    validationRows?: number;
    trainRows?: number;
  };
  scorecardPoints: Array<Record<string, unknown>>;
  scoreDistribution: Array<Record<string, unknown>>;
  liftTable: Array<Record<string, unknown>>;
  ksTable: Array<Record<string, unknown>>;
  cutoffTable: Array<Record<string, unknown>>;
  selectedCutoff?: number;
  generatedCode?: Record<string, string>;
  evidenceIds?: string[];
  warnings?: string[];
  champion?: boolean;
  createdAt?: string;
  updatedAt?: string;
};

function scopeValue(record: Record<string, unknown>, ...keys: string[]) {
  for (const key of keys) {
    const value = record[key];
    if (value !== undefined && value !== null && String(value).trim() !== "") return value;
  }
  return undefined;
}

/**
 * Target-directed Credit Risk evidence is accepted only when the backend binds
 * it to the exact project + registered dataset version and proves an exact
 * development-population materialization. Browser rows and project-only
 * "latest" artifacts are never accepted as substitutes.
 */
export function assertExactDevelopmentScope<T>(
  artifact: T,
  expected: ExactCreditRiskIdentity,
  label = "Credit Risk artifact",
): T {
  if (!artifact || typeof artifact !== "object") {
    throw new Error(`${label} is missing.`);
  }
  const record = artifact as Record<string, unknown>;
  const actualProjectId = String(scopeValue(record, "projectId", "project_id") ?? "");
  const actualDatasetId = String(scopeValue(record, "datasetId", "dataset_id") ?? "");
  const actualDatasetVersionId = String(scopeValue(record, "datasetVersionId", "dataset_version_id") ?? "");
  const actualTarget = String(scopeValue(record, "targetColumn", "target_column", "target") ?? "");
  const analyticalScope = String(
    scopeValue(record, "analytical_scope", "analysis_scope", "target_directed_scope", "scope") ?? "",
  );
  const partitionId = String(
    scopeValue(record, "partition_id", "analysis_partition_id", "analysisPartitionId") ?? "",
  );
  const partitionRevision = Number(
    scopeValue(record, "partition_revision", "analysis_partition_revision", "analysisPartitionRevision"),
  );
  const populationId = String(
    scopeValue(record, "population_id", "development_population_id", "developmentPopulationId") ?? "",
  );
  const populationCount = Number(scopeValue(record, "population_count", "development_row_count", "rowCount"));
  const holdoutExcluded = scopeValue(record, "holdout_excluded", "holdoutExcluded");
  const sourceChecksum = String(scopeValue(record, "source_checksum", "sourceChecksum") ?? "");
  const actor = String(scopeValue(record, "actor") ?? "");
  const timestamp = String(scopeValue(record, "timestamp") ?? "");

  if (
    actualProjectId !== expected.projectId ||
    actualDatasetId !== expected.datasetId ||
    actualDatasetVersionId !== expected.datasetVersionId
  ) {
    throw new Error(`${label} does not match the exact project and registered dataset version.`);
  }
  if (expected.targetColumn && actualTarget !== expected.targetColumn) {
    throw new Error(`${label} does not match the exact target contract.`);
  }
  if (analyticalScope !== "development_population") {
    throw new Error(`${label} is not verified development-population evidence.`);
  }
  if (!partitionId || !Number.isInteger(partitionRevision) || partitionRevision <= 0) {
    throw new Error(`${label} is missing a current Analysis Partition identity and revision.`);
  }
  if (!populationId || !Number.isInteger(populationCount) || populationCount <= 0) {
    throw new Error(`${label} is missing verified development membership.`);
  }
  if (holdoutExcluded !== true) {
    throw new Error(`${label} does not prove that the sealed final holdout was excluded.`);
  }
  if (!sourceChecksum || !actor || !timestamp) {
    throw new Error(`${label} is missing required scope lineage metadata.`);
  }
  return artifact;
}

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
    throw new Error(payload?.detail ?? payload?.error ?? `ATLAS credit risk request failed with HTTP ${response.status}.`);
  }
  return payload as T;
}

export async function getCreditRiskProfile(profileId?: string) {
  const path = profileId ? `/credit-risk/profile?profileId=${encodeURIComponent(profileId)}` : "/credit-risk/profile";
  const payload = await jsonFetch<{ ok: true; profile: CreditRiskProfile | null }>(path);
  return payload.profile;
}

export async function getCreditRiskProfileForProject(projectId: string) {
  const payload = await jsonFetch<{ ok: true; profile: CreditRiskProfile | null }>(`/credit-risk/profile/project/${encodeURIComponent(projectId)}`);
  return payload.profile;
}

export async function saveCreditRiskProfile(profile: CreditRiskProfile) {
  const path = profile.profileId ? `/credit-risk/profile/${encodeURIComponent(profile.profileId)}` : "/credit-risk/profile";
  const payload = await jsonFetch<{ ok: true; profile: CreditRiskProfile }>(path, {
    method: profile.profileId ? "PUT" : "POST",
    body: JSON.stringify(profile),
  });
  return payload.profile;
}

export async function computeCreditRiskReadiness(profile: CreditRiskProfile) {
  const payload = await jsonFetch<{ ok: true; readiness: { score: number; items: Array<{ section: string; status: CreditRiskStatus }> } }>("/credit-risk/readiness", {
    method: "POST",
    body: JSON.stringify(profile),
  });
  return payload.readiness;
}

export async function saveCreditRiskEvidence(profile: CreditRiskProfile, technique: string, label: string, supportsSections?: string[]) {
  const payload = await jsonFetch<{ ok: true; evidence: EvidenceItem }>("/credit-risk/evidence", {
    method: "POST",
    body: JSON.stringify({ profile, technique, label, supportsSections }),
  });
  return payload.evidence;
}

export async function exportCreditRiskProfileExcel(profile: CreditRiskProfile) {
  const response = await fetch(`${DATASET_API_BASE}/credit-risk/export/excel`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(profile),
  });
  if (!response.ok) throw new Error(`ATLAS credit risk export failed with HTTP ${response.status}.`);
  return response.blob();
}

export async function runWoeIvAnalysis(request: WoeIvRunRequest) {
  const payload = await jsonFetch<{ ok: true; analysis: WoeIvAnalysis }>("/credit-risk/woe-iv/run", {
    method: "POST",
    body: JSON.stringify(request),
  });
  return assertExactDevelopmentScope(payload.analysis, request, "WOE / IV analysis");
}

export async function getCreditRiskDatasetSummary(input: {
  projectId: string;
  datasetId: string;
  datasetVersionId: string;
  targetColumn: string;
  eventValue?: string;
  nonEventValue?: string;
}) {
  const payload = await jsonFetch<{ ok: true; summary: CreditRiskTargetSummary }>("/credit-risk/dataset-summary", {
    method: "POST",
    body: JSON.stringify(input),
  });
  return assertExactDevelopmentScope(payload.summary, input, "Credit Risk target summary");
}

export async function getWoeIvAnalysis(analysisId: string) {
  const payload = await jsonFetch<{ ok: true; analysis: WoeIvAnalysis }>(`/credit-risk/woe-iv/${encodeURIComponent(analysisId)}`);
  return payload.analysis;
}

export async function getLatestWoeIvAnalysisForProject(projectId: string, expected?: ExactCreditRiskIdentity) {
  if (!expected || expected.projectId !== projectId) {
    throw new Error("WOE / IV recovery requires the exact project and registered dataset version.");
  }
  const payload = await jsonFetch<{ ok: true; analysis: WoeIvAnalysis | null }>(`/credit-risk/woe-iv/project/${encodeURIComponent(projectId)}`);
  return payload.analysis
    ? assertExactDevelopmentScope(payload.analysis, expected, "Recovered WOE / IV analysis")
    : null;
}

export async function saveWoeIvAnalysis(analysis: WoeIvAnalysis) {
  const payload = await jsonFetch<{ ok: true; analysis: WoeIvAnalysis }>("/credit-risk/woe-iv/save", {
    method: "POST",
    body: JSON.stringify({ analysis }),
  });
  return payload.analysis;
}

export async function applyManualWoeBins(analysisId: string, variable: string, bins: WoeIvManualBin[], allowNumericGaps = false) {
  const payload = await jsonFetch<{ ok: true; analysis: WoeIvAnalysis }>("/credit-risk/woe-iv/apply-manual-bins", {
    method: "POST",
    body: JSON.stringify({ analysisId, variable, bins, allowNumericGaps }),
  });
  return payload.analysis;
}

export async function saveWoeIvEvidence(analysisId: string, technique = "woe_iv", label = "WOE / IV Analysis Evidence") {
  const payload = await jsonFetch<{ ok: true; evidence: EvidenceItem }>("/credit-risk/woe-iv/save-evidence", {
    method: "POST",
    body: JSON.stringify({ analysisId, technique, label }),
  });
  return payload.evidence;
}

export async function generateWoeIvCode(request: WoeIvRunRequest) {
  const payload = await jsonFetch<{ ok: true; generatedCode: Record<string, string> }>("/credit-risk/woe-iv/generate-code", {
    method: "POST",
    body: JSON.stringify(request),
  });
  return payload.generatedCode;
}

export async function exportWoeIvExcel(analysisId: string) {
  const response = await fetch(`${DATASET_API_BASE}/credit-risk/woe-iv/export/excel`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ analysisId }),
  });
  if (!response.ok) throw new Error(`ATLAS WOE / IV export failed with HTTP ${response.status}.`);
  return response.blob();
}

export async function trainScorecardModel(request: ScorecardTrainRequest) {
  const payload = await jsonFetch<{ ok: true; model: ScorecardModel }>("/credit-risk/scorecard/train", {
    method: "POST",
    body: JSON.stringify(request),
  });
  return assertExactDevelopmentScope(payload.model, request, "Scorecard model");
}

export async function getLatestScorecardForProject(projectId: string, expected?: ExactCreditRiskIdentity) {
  if (!expected || expected.projectId !== projectId) {
    throw new Error("Scorecard recovery requires the exact project and registered dataset version.");
  }
  const payload = await jsonFetch<{ ok: true; model: ScorecardModel | null }>(`/credit-risk/scorecard/project/${encodeURIComponent(projectId)}`);
  return payload.model
    ? assertExactDevelopmentScope(payload.model, expected, "Recovered scorecard model")
    : null;
}

export async function saveScorecardEvidence(modelId: string, technique = "scorecard_modeling", label = "Scorecard Model Evidence") {
  const payload = await jsonFetch<{ ok: true; evidence: EvidenceItem }>("/credit-risk/scorecard/save-evidence", {
    method: "POST",
    body: JSON.stringify({ modelId, technique, label }),
  });
  return payload.evidence;
}

export async function generateScorecardCode(request: ScorecardTrainRequest) {
  const payload = await jsonFetch<{ ok: true; generatedCode: Record<string, string> }>("/credit-risk/scorecard/generate-code", {
    method: "POST",
    body: JSON.stringify(request),
  });
  return payload.generatedCode;
}

export async function registerScorecardModel(modelId: string, champion = true) {
  const payload = await jsonFetch<{ ok: true; model: ScorecardModel }>("/credit-risk/scorecard/register-model", {
    method: "POST",
    body: JSON.stringify({ modelId, champion }),
  });
  return payload.model;
}

export async function exportScorecardExcel(modelId: string) {
  const response = await fetch(`${DATASET_API_BASE}/credit-risk/scorecard/export/excel`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ modelId }),
  });
  if (!response.ok) throw new Error(`ATLAS scorecard export failed with HTTP ${response.status}.`);
  return response.blob();
}

export async function trainCreditRiskMlModel(request: CreditRiskMlTrainRequest) {
  const payload = await jsonFetch<{ ok: true; model: CreditRiskMlModel }>("/credit-risk/ml/train", {
    method: "POST",
    body: JSON.stringify(request),
  });
  return assertExactDevelopmentScope(payload.model, request, "Credit Risk ML model");
}

export async function getCreditRiskMlModel(modelId: string) {
  const payload = await jsonFetch<{ ok: true; model: CreditRiskMlModel }>(`/credit-risk/ml/${encodeURIComponent(modelId)}`);
  return payload.model;
}

export async function getLatestCreditRiskMlModelForProject(projectId: string, expected?: ExactCreditRiskIdentity) {
  if (!expected || expected.projectId !== projectId) {
    throw new Error("Credit Risk ML recovery requires the exact project and registered dataset version.");
  }
  const payload = await jsonFetch<{ ok: true; model: CreditRiskMlModel | null }>(`/credit-risk/ml/project/${encodeURIComponent(projectId)}`);
  return payload.model
    ? assertExactDevelopmentScope(payload.model, expected, "Recovered Credit Risk ML model")
    : null;
}

export async function saveCreditRiskMlEvidence(modelId: string, technique = "ml_underwriting", label = "AI/ML Underwriting Evidence") {
  const payload = await jsonFetch<{ ok: true; evidence: EvidenceItem }>("/credit-risk/ml/save-evidence", {
    method: "POST",
    body: JSON.stringify({ modelId, technique, label }),
  });
  return payload.evidence;
}

export async function runCreditRiskChampionComparison(profile: CreditRiskProfile, scorecardModel?: ScorecardModel | null, mlModel?: CreditRiskMlModel | null) {
  const payload = await jsonFetch<{ ok: true; comparison: Record<string, unknown> }>("/credit-risk/champion-comparison/run", {
    method: "POST",
    body: JSON.stringify({ profile, scorecardModel, mlModel }),
  });
  return payload.comparison;
}

export async function saveCreditRiskChampionDecision(profile: CreditRiskProfile, decision: CreditRiskChampionDecision) {
  const payload = await jsonFetch<{ ok: true; decision: CreditRiskChampionDecision; profile: CreditRiskProfile }>("/credit-risk/champion-comparison/save-decision", {
    method: "POST",
    body: JSON.stringify({ profile, decision }),
  });
  return payload;
}

export async function saveCreditRiskChampionEvidence(profile: CreditRiskProfile, label = "Champion / Challenger Evidence") {
  const payload = await jsonFetch<{ ok: true; evidence: EvidenceItem }>("/credit-risk/champion-comparison/save-evidence", {
    method: "POST",
    body: JSON.stringify({ profile, label }),
  });
  return payload.evidence;
}

export function scorecardPreview(input: CreditRiskProfile["scorecardScaling"]) {
  const pdo = Number(input?.pdo);
  const baseScore = Number(input?.baseScore);
  const odds = parseBaseOdds(input?.baseOdds || "");
  if (!Number.isFinite(pdo) || !Number.isFinite(baseScore) || !Number.isFinite(odds) || odds <= 0) return { factor: undefined, offset: undefined };
  const factor = pdo / Math.log(2);
  const offset = baseScore - factor * Math.log(odds);
  return { factor, offset };
}

function parseBaseOdds(value: string) {
  const match = value.match(/([0-9.]+)\s*:?\s*1?/);
  return match ? Number(match[1]) : Number(value);
}
