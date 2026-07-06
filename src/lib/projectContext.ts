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
  updatedAt?: string;
};

export const PROJECT_CONTEXT_KEY = "modeling-tool-project-context";

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
};

export function loadProjectContext(): ProjectContext {
  if (typeof localStorage === "undefined") return defaultProjectContext;
  try {
    const raw = localStorage.getItem(PROJECT_CONTEXT_KEY);
    if (!raw) return defaultProjectContext;
    const parsed = JSON.parse(raw) as Partial<ProjectContext>;
    return {
      ...defaultProjectContext,
      ...parsed,
      monitoringMetrics:
        Array.isArray(parsed.monitoringMetrics) && parsed.monitoringMetrics.length
          ? parsed.monitoringMetrics
          : defaultMonitoringMetricsForModelType(parsed.modelType ?? defaultProjectContext.modelType),
      regulatoryEnvironment:
        Array.isArray(parsed.regulatoryEnvironment) && parsed.regulatoryEnvironment.length
          ? parsed.regulatoryEnvironment
          : defaultProjectContext.regulatoryEnvironment,
    };
  } catch {
    return defaultProjectContext;
  }
}

export function saveProjectContext(context: ProjectContext) {
  const next: ProjectContext = {
    ...defaultProjectContext,
    ...context,
    updatedAt: new Date().toISOString(),
  };
  localStorage.setItem(PROJECT_CONTEXT_KEY, JSON.stringify(next));
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
