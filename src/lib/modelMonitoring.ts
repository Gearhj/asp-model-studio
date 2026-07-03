import { loadProjectContext, type ProjectContext } from "./projectContext";

export type ProductionModelStatus = "green" | "yellow" | "red";

export type ProductionModel = {
  modelId: string;
  modelName: string;
  owner: string;
  modelType: string;
  deployedAt: string;
  monitoringCadence: string;
  metrics: { name: string; value: string; status: ProductionModelStatus; trend: "stable" | "improving" | "deteriorating" }[];
  complianceIssues: string[];
  lastReviewedAt: string;
};

export type ModelEscalation = {
  modelId: string;
  modelName: string;
  severity: "high" | "medium" | "low";
  reason: string;
  owner: string;
  action: string;
};

function monthsBetween(startIso: string, end = new Date()) {
  const start = new Date(startIso);
  if (Number.isNaN(start.getTime())) return 0;
  return (end.getFullYear() - start.getFullYear()) * 12 + (end.getMonth() - start.getMonth());
}

function cadenceLabel(context: ProjectContext) {
  return context.monitoringCadence === "custom"
    ? context.monitoringCadenceCustom || "custom"
    : context.monitoringCadence;
}

function statusRank(status: ProductionModelStatus) {
  if (status === "red") return 3;
  if (status === "yellow") return 2;
  return 1;
}

export function loadProductionModels(): ProductionModel[] {
  const context = loadProjectContext();
  const currentProjectModel =
    context.modelId || context.projectName
      ? [
          {
            modelId: context.modelId || "Current",
            modelName: context.projectName || "Current ATLAS Project",
            owner: context.implementationOwner || "Not assigned",
            modelType: context.modelType,
            deployedAt: context.implementationTargetDate || "",
            monitoringCadence: cadenceLabel(context),
            metrics: (context.monitoringMetrics.length ? context.monitoringMetrics : ["AUC", "KS", "PSI", "VSI"]).map((metric) => ({
              name: metric,
              value: "Pending",
              status: "yellow" as const,
              trend: "stable" as const,
            })),
            complianceIssues: context.implementationEnvironment ? [] : ["Implementation environment not documented"],
            lastReviewedAt: "",
          },
        ]
      : [];

  return [
    ...currentProjectModel,
    {
      modelId: "15211",
      modelName: "Portfolio Attrition Model",
      owner: "Retention Analytics",
      modelType: "attrition",
      deployedAt: "2024-09-15",
      monitoringCadence: "monthly",
      metrics: [
        { name: "AUC", value: "0.742", status: "yellow", trend: "deteriorating" },
        { name: "KS", value: "0.318", status: "yellow", trend: "deteriorating" },
        { name: "PSI", value: "0.18", status: "yellow", trend: "deteriorating" },
        { name: "VSI", value: "2 red variables", status: "red", trend: "deteriorating" },
      ],
      complianceIssues: [],
      lastReviewedAt: "2026-06-15",
    },
    {
      modelId: "14877",
      modelName: "Credit Line Increase Model",
      owner: "Credit Risk Modeling",
      modelType: "credit risk",
      deployedAt: "2023-10-01",
      monitoringCadence: "quarterly",
      metrics: [
        { name: "AUC", value: "0.691", status: "red", trend: "deteriorating" },
        { name: "KS", value: "0.241", status: "red", trend: "deteriorating" },
        { name: "PSI", value: "0.29", status: "red", trend: "deteriorating" },
        { name: "VSI", value: "5 red variables", status: "red", trend: "deteriorating" },
      ],
      complianceIssues: ["Fair lending review overdue"],
      lastReviewedAt: "2026-03-31",
    },
    {
      modelId: "16004",
      modelName: "Loss Forecast Model",
      owner: "Finance Analytics",
      modelType: "regression",
      deployedAt: "2025-04-20",
      monitoringCadence: "monthly",
      metrics: [
        { name: "RMSE", value: "0.431", status: "green", trend: "stable" },
        { name: "MAE", value: "0.287", status: "green", trend: "stable" },
        { name: "MAPE", value: "8.4%", status: "green", trend: "stable" },
        { name: "PSI", value: "0.06", status: "green", trend: "stable" },
        { name: "VSI", value: "All pass", status: "green", trend: "stable" },
      ],
      complianceIssues: [],
      lastReviewedAt: "2026-06-01",
    },
  ];
}

export function buildEscalationQueue(models = loadProductionModels()): ModelEscalation[] {
  const escalations: ModelEscalation[] = [];
  models.forEach((model) => {
    const ageMonths = monthsBetween(model.deployedAt);
    if (ageMonths >= 18) {
      escalations.push({
        modelId: model.modelId,
        modelName: model.modelName,
        severity: "high",
        reason: `Model age is ${ageMonths} months; exceeds 18-month review threshold.`,
        owner: model.owner,
        action: "Schedule full model review or redevelopment assessment.",
      });
    }

    const worstMetric = model.metrics.slice().sort((a, b) => statusRank(b.status) - statusRank(a.status))[0];
    if (worstMetric?.status === "red") {
      escalations.push({
        modelId: model.modelId,
        modelName: model.modelName,
        severity: "high",
        reason: `${worstMetric.name} is in the red zone (${worstMetric.value}).`,
        owner: model.owner,
        action: "Open monitoring exception and assign remediation owner.",
      });
    } else if (worstMetric?.status === "yellow" && worstMetric.trend === "deteriorating") {
      escalations.push({
        modelId: model.modelId,
        modelName: model.modelName,
        severity: "medium",
        reason: `${worstMetric.name} is trending toward breach (${worstMetric.value}).`,
        owner: model.owner,
        action: "Review next monitoring cycle and prepare mitigation plan.",
      });
    }

    model.complianceIssues.forEach((issue) =>
      escalations.push({
        modelId: model.modelId,
        modelName: model.modelName,
        severity: "high",
        reason: issue,
        owner: model.owner,
        action: "Escalate to model governance and compliance owner.",
      })
    );
  });
  return escalations;
}
