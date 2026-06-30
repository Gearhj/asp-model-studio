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

export type ProjectContext = {
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

export const defaultProjectContext: ProjectContext = {
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
