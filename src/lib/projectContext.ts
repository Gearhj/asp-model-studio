export type ModelType =
  | "fraud"
  | "credit risk"
  | "marketing response"
  | "attrition"
  | "approval"
  | "collections"
  | "AML/KYC"
  | "generic classification"
  | "regression";

export type PredictiveModelTypeSelection =
  | "Generic Binary Classification"
  | "Fraud Classification"
  | "Transaction Fraud Classification"
  | "Application Fraud Classification"
  | "Identity Fraud Classification"
  | "Account Takeover Classification"
  | "First-Party Fraud Classification"
  | "Credit Risk Classification"
  | "Customer Response Classification"
  | "Attrition Classification"
  | "Other Binary Classification"
  | "Regression";

export type AcceptedProjectContextAiDraft = {
  field: string;
  action: string;
  text: string;
  acceptedAt: string;
  acceptedBy?: string;
};

export type RegulatoryEnvironment =
  | "SR 11-7"
  | "OCC"
  | "Fair Lending"
  | "FCRA"
  | "ECOA"
  | "GDPR"
  | "HIPAA"
  | "internal governance"
  | "none";

export type InterpretabilityRequirement = "low" | "medium" | "high";
export type DeploymentExpectation = "research only" | "batch scoring" | "real-time API" | "monitoring only";
export type MonitoringCadence = "daily" | "weekly" | "monthly" | "quarterly" | "annually" | "custom";

export type ProjectContextCriterion = {
  id: string;
  metric: string;
  threshold: string;
  direction: "increase" | "decrease" | "maintain" | "qualitative";
  dataset: string;
  rationale: string;
  status: "Proposed" | "Confirmed" | "Not Yet Defined";
  owner: string;
};

export type ProjectContextRisk = {
  id: string;
  title: string;
  description: string;
  affectedUse: string;
  measurement: string;
  tolerance: string;
  control: string;
  monitoring: string;
  owner: string;
  documentationNote: string;
};

export type ProjectContextValidationFinding = {
  severity: "Blocking" | "Important" | "Advisory";
  section: string;
  message: string;
  why: string;
  action: string;
  downstream: string;
  mdd: string;
};

export type FraudProjectContextDetails = {
  analyticalFamily: string;
  modelSubtype: string;
  developmentType: string;
  deploymentMode: string;
  approvedUses: string;
  prohibitedUses: string;
  primaryModelUsers: string;
  outputConsumers: string;
  decisionSupported: string;
  degreeOfAutomation: string;
  humanReviewRequired: string;
  overrideAuthority: string;
  scoringFrequency: string;
  expectedScoringVolume: string;
  implementationPlatform: string;
  downstreamSystem: string;
  targetColumnName: string;
  positiveClassValue: string;
  negativeClassValue: string;
  positiveEventDefinition: string;
  negativeEventDefinition: string;
  labelSource: string;
  labelCreationMethod: string;
  eventDateDefinition: string;
  labelMaturityPeriod: string;
  outcomeFinalizationRule: string;
  fraudOutcomeType: string;
  unresolvedOutcomeTreatment: string;
  reversalDisputeTreatment: string;
  targetExclusions: string;
  labelQualityControls: string;
  potentialLabelBias: string;
  potentialTargetLeakage: string;
  targetNarrative: string;
  unitOfObservation: string;
  eligiblePopulation: string;
  inclusionRules: string;
  exclusionRules: string;
  product: string;
  channel: string;
  geography: string;
  customerAccountScope: string;
  transactionApplicationScope: string;
  populationStartDate: string;
  populationEndDate: string;
  populationLimitations: string;
  knownSelectionEffects: string;
  expectedProductionPopulation: string;
  populationNarrative: string;
  observationStartDate: string;
  observationEndDate: string;
  observationDateDefinition: string;
  lookbackPeriod: string;
  observationPattern: string;
  performanceStartRule: string;
  performanceEndRule: string;
  performanceDuration: string;
  labelMaturityLag: string;
  outcomeFinalizationDateRule: string;
  stabilityPeriod: string;
  embargoPeriod: string;
  dataAvailabilityLag: string;
  trainDatasetPlanned: string;
  testDatasetPlanned: string;
  ootDatasetPlanned: string;
  validationDesign: string;
  testDatasetRole: string;
  ootDatasetRole: string;
  ootTimePeriod: string;
  crossValidationPlanned: string;
  crossValidationMethod: string;
  governingEvaluationDataset: string;
  governingSelectionMetric: string;
  championSelectionRule: string;
  datasetIndependenceAssumption: string;
  leakagePreventionStrategy: string;
  stakeholders: Record<string, string>;
  reviewRequirements: Record<string, string>;
  risks: ProjectContextRisk[];
  successCriteria: ProjectContextCriterion[];
  validationFindings: ProjectContextValidationFinding[];
  validationUpdatedAt?: string;
  completedAt?: string;
};

export type ProjectContext = {
  modelId: string;
  projectName: string;
  businessObjective: string;
  modelType: ModelType;
  targetDefinition: string;
  populationDefinition: string;
  observationWindow: string;
  performanceWindow: string;
  falsePositiveCost: string;
  falseNegativeCost: string;
  regulatoryEnvironment: RegulatoryEnvironment[];
  intendedModelUse: string;
  primarySuccessMetric: string;
  secondaryMetrics: string;
  interpretabilityRequirement: InterpretabilityRequirement;
  deploymentExpectation: DeploymentExpectation;
  implementationOwner: string;
  implementationTargetDate: string;
  implementationEnvironment: string;
  implementationNotes: string;
  monitoringCadence: MonitoringCadence;
  monitoringCadenceCustom: string;
  monitoringMetrics: string[];
  monitoringNotes: string;
  modelTypeSelection: PredictiveModelTypeSelection;
  modelingMissionSummary: string;
  acceptedAiDrafts: AcceptedProjectContextAiDraft[];
  completionStatus: "draft" | "complete";
  completedAt?: string;
  completedBy?: string;
  updatedBy?: string;
  fraudDetails: FraudProjectContextDetails;
  updatedAt?: string;
};

export const PROJECT_CONTEXT_KEY = "modeling-tool-project-context";

export function scopedProjectContextKey(projectId: string, userId: string) {
  return `${PROJECT_CONTEXT_KEY}:${encodeURIComponent(userId || "anonymous")}:${encodeURIComponent(projectId || "unassigned")}`;
}

export const modelTypeOptions: ModelType[] = [
  "fraud",
  "credit risk",
  "marketing response",
  "attrition",
  "approval",
  "collections",
  "AML/KYC",
  "generic classification",
  "regression",
];

export const predictiveModelTypeOptions: PredictiveModelTypeSelection[] = [
  "Generic Binary Classification",
  "Fraud Classification",
  "Transaction Fraud Classification",
  "Application Fraud Classification",
  "Identity Fraud Classification",
  "Account Takeover Classification",
  "First-Party Fraud Classification",
  "Credit Risk Classification",
  "Customer Response Classification",
  "Attrition Classification",
  "Other Binary Classification",
  // Stage REG-A fix (REG-A-D1): the predictive-modeling Project Context could
  // only describe a project as some flavor of classification -- the ModelType
  // union has supported "regression" all along, but no selectable option
  // mapped to it, so a continuous-target project was forced to carry a
  // classification identity from Step00 onward.
  "Regression",
];

export function canonicalModelType(selection: PredictiveModelTypeSelection): ModelType {
  if (/regression/i.test(selection)) return "regression";
  if (/credit risk/i.test(selection)) return "credit risk";
  if (/customer response/i.test(selection)) return "marketing response";
  if (/attrition/i.test(selection)) return "attrition";
  if (/fraud|account takeover/i.test(selection)) return "fraud";
  return "generic classification";
}

export function professionalModelType(modelType: ModelType, subtype?: string): PredictiveModelTypeSelection {
  if (predictiveModelTypeOptions.includes(subtype as PredictiveModelTypeSelection)) {
    return subtype as PredictiveModelTypeSelection;
  }
  if (modelType === "regression") return "Regression";
  if (modelType === "fraud") return "Fraud Classification";
  if (modelType === "credit risk") return "Credit Risk Classification";
  if (modelType === "marketing response") return "Customer Response Classification";
  if (modelType === "attrition") return "Attrition Classification";
  return "Generic Binary Classification";
}

function professionalDeploymentMode(value?: string) {
  const normalized = String(value ?? "").trim();
  if (["Research", "Development", "Validation", "Limited Pilot", "Production Candidate", "Production"].includes(normalized)) return normalized;
  if (normalized === "Research Only") return "Research";
  if (normalized === "Pilot") return "Limited Pilot";
  if (normalized === "Advisory") return "Validation";
  if (normalized === "Not Yet Determined") return "Development";
  return normalized || "Development";
}

export const regulatoryOptions: RegulatoryEnvironment[] = [
  "SR 11-7",
  "OCC",
  "Fair Lending",
  "FCRA",
  "ECOA",
  "GDPR",
  "HIPAA",
  "internal governance",
  "none",
];

export const monitoringCadenceOptions: MonitoringCadence[] = [
  "daily",
  "weekly",
  "monthly",
  "quarterly",
  "annually",
  "custom",
];

export const classificationMonitoringMetricOptions = [
  "AUC",
  "KS",
  "PR-AUC",
  "Precision",
  "Recall",
  "F1",
  "Lift",
  "Calibration",
  "PSI",
  "VSI",
] as const;

export const regressionMonitoringMetricOptions = [
  "RMSE",
  "MAE",
  "MAPE",
  "R-squared",
  "Adjusted R-squared",
  "Mean Residual",
  "PSI",
  "VSI",
] as const;

export function defaultMonitoringMetricsForModelType(modelType: ModelType) {
  return modelType === "regression" ? ["RMSE", "MAE", "MAPE", "R-squared", "Adjusted R-squared", "PSI", "VSI"] : ["AUC", "KS", "PSI", "VSI"];
}

export function monitoringMetricOptionsForModelType(modelType: ModelType) {
  return modelType === "regression" ? regressionMonitoringMetricOptions : classificationMonitoringMetricOptions;
}

export const defaultProjectContext: ProjectContext = {
  modelId: "",
  projectName: "",
  businessObjective: "",
  modelType: "generic classification",
  targetDefinition: "",
  populationDefinition: "",
  observationWindow: "",
  performanceWindow: "",
  falsePositiveCost: "",
  falseNegativeCost: "",
  regulatoryEnvironment: ["internal governance"],
  intendedModelUse: "",
  primarySuccessMetric: "",
  secondaryMetrics: "",
  interpretabilityRequirement: "medium",
  deploymentExpectation: "research only",
  implementationOwner: "",
  implementationTargetDate: "",
  implementationEnvironment: "",
  implementationNotes: "",
  monitoringCadence: "monthly",
  monitoringCadenceCustom: "",
  monitoringMetrics: defaultMonitoringMetricsForModelType("generic classification"),
  monitoringNotes: "",
  modelTypeSelection: "Generic Binary Classification",
  modelingMissionSummary: "",
  acceptedAiDrafts: [],
  completionStatus: "draft",
  fraudDetails: {
    analyticalFamily: "Binary Classification", modelSubtype: "Generic Fraud Classification", developmentType: "New Development", deploymentMode: "Development",
    approvedUses: "", prohibitedUses: "", primaryModelUsers: "", outputConsumers: "", decisionSupported: "", degreeOfAutomation: "Not Yet Determined", humanReviewRequired: "To be determined", overrideAuthority: "", scoringFrequency: "", expectedScoringVolume: "", implementationPlatform: "", downstreamSystem: "",
    targetColumnName: "", positiveClassValue: "", negativeClassValue: "", positiveEventDefinition: "", negativeEventDefinition: "", labelSource: "", labelCreationMethod: "", eventDateDefinition: "", labelMaturityPeriod: "", outcomeFinalizationRule: "", fraudOutcomeType: "", unresolvedOutcomeTreatment: "", reversalDisputeTreatment: "", targetExclusions: "", labelQualityControls: "", potentialLabelBias: "", potentialTargetLeakage: "", targetNarrative: "",
    unitOfObservation: "Transaction", eligiblePopulation: "", inclusionRules: "", exclusionRules: "", product: "", channel: "", geography: "", customerAccountScope: "", transactionApplicationScope: "", populationStartDate: "", populationEndDate: "", populationLimitations: "", knownSelectionEffects: "", expectedProductionPopulation: "", populationNarrative: "",
    observationStartDate: "", observationEndDate: "", observationDateDefinition: "", lookbackPeriod: "", observationPattern: "Snapshot", performanceStartRule: "", performanceEndRule: "", performanceDuration: "", labelMaturityLag: "", outcomeFinalizationDateRule: "", stabilityPeriod: "", embargoPeriod: "", dataAvailabilityLag: "",
    trainDatasetPlanned: "Yes", testDatasetPlanned: "Yes", ootDatasetPlanned: "Yes", validationDesign: "Separate TRAIN / TEST / OOT", testDatasetRole: "In-Time Holdout", ootDatasetRole: "Out-of-Time Validation", ootTimePeriod: "", crossValidationPlanned: "No", crossValidationMethod: "", governingEvaluationDataset: "TEST", governingSelectionMetric: "", championSelectionRule: "", datasetIndependenceAssumption: "", leakagePreventionStrategy: "",
    stakeholders: {}, reviewRequirements: {}, risks: [], successCriteria: [], validationFindings: [],
  },
};

export function loadProjectContext(projectId = "", userId = ""): ProjectContext {
  if (typeof localStorage === "undefined") return defaultProjectContext;
  try {
    const key = projectId && userId
      ? scopedProjectContextKey(projectId, userId)
      : PROJECT_CONTEXT_KEY;
    const raw = localStorage.getItem(key);
    if (!raw) return defaultProjectContext;
    const parsed = JSON.parse(raw) as Partial<ProjectContext>;
    const fraudDetails = { ...defaultProjectContext.fraudDetails, ...(parsed.fraudDetails ?? {}), deploymentMode: professionalDeploymentMode(parsed.fraudDetails?.deploymentMode), stakeholders: parsed.fraudDetails?.stakeholders ?? {}, reviewRequirements: parsed.fraudDetails?.reviewRequirements ?? {}, risks: Array.isArray(parsed.fraudDetails?.risks) ? parsed.fraudDetails.risks : [], successCriteria: Array.isArray(parsed.fraudDetails?.successCriteria) ? parsed.fraudDetails.successCriteria : [], validationFindings: Array.isArray(parsed.fraudDetails?.validationFindings) ? parsed.fraudDetails.validationFindings : [] };
    const modelType = parsed.modelType ?? defaultProjectContext.modelType;
    const completedAt = parsed.completedAt ?? fraudDetails.completedAt;
    return {
      ...defaultProjectContext,
      ...parsed,
      modelType,
      modelTypeSelection: predictiveModelTypeOptions.includes(parsed.modelTypeSelection as PredictiveModelTypeSelection)
        ? parsed.modelTypeSelection as PredictiveModelTypeSelection
        : professionalModelType(modelType, fraudDetails.modelSubtype),
      modelingMissionSummary: typeof parsed.modelingMissionSummary === "string" ? parsed.modelingMissionSummary : "",
      acceptedAiDrafts: Array.isArray(parsed.acceptedAiDrafts) ? parsed.acceptedAiDrafts : [],
      completionStatus: parsed.completionStatus === "complete" || Boolean(completedAt) ? "complete" : "draft",
      completedAt,
      monitoringMetrics:
        Array.isArray(parsed.monitoringMetrics) && parsed.monitoringMetrics.length
          ? parsed.monitoringMetrics
          : defaultMonitoringMetricsForModelType(modelType),
      regulatoryEnvironment:
        Array.isArray(parsed.regulatoryEnvironment) && parsed.regulatoryEnvironment.length
          ? parsed.regulatoryEnvironment
          : defaultProjectContext.regulatoryEnvironment,
      fraudDetails,
    };
  } catch {
    return defaultProjectContext;
  }
}

export function saveProjectContext(
  context: ProjectContext,
  projectId = "",
  userId = "",
) {
  const next: ProjectContext = {
    ...defaultProjectContext,
    ...context,
    updatedAt: new Date().toISOString(),
  };
  const key = projectId && userId
    ? scopedProjectContextKey(projectId, userId)
    : PROJECT_CONTEXT_KEY;
  localStorage.setItem(key, JSON.stringify(next));
  return next;
}

export function hasGovernanceRegulation(context: ProjectContext) {
  return context.regulatoryEnvironment.some((item) =>
    ["SR 11-7", "OCC", "Fair Lending", "FCRA", "ECOA", "internal governance"].includes(item)
  );
}

export function summarizeRegulatoryContext(context: ProjectContext) {
  if (!context.regulatoryEnvironment.length || context.regulatoryEnvironment.includes("none")) {
    return "No formal regulatory environment selected.";
  }
  return context.regulatoryEnvironment.join(", ");
}
