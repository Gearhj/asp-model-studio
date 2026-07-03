import { loadExperiments } from "./experimentTracking";
import { inferLocalProblemType, loadLocalDataset } from "./localDataset";
import { loadProjectContext } from "./projectContext";

type RankedModel = {
  key: string;
  name: string;
  task?: "classification" | "regression" | "anomaly";
  auc?: number;
  pr_auc?: number;
  accuracy?: number;
  f1?: number;
  mae?: number;
  mse?: number;
  rmse?: number;
  r2?: number;
  adjusted_r2?: number;
};

type EvaluationCurves = {
  metrics?: {
    precision?: number;
    recall?: number;
    f1?: number;
    auc?: number;
    pr_auc?: number;
    mae?: number;
    mse?: number;
    rmse?: number;
    r2?: number;
    adjusted_r2?: number;
  };
  confusion?: number[][];
};

export type ExecutiveSummary = {
  headline: string;
  productionReadiness: "Production candidate" | "Validation candidate" | "Research only";
  overview: string;
  stats: { label: string; value: string }[];
  strongestPredictors: string[];
  keyRisks: string[];
  recommendedNextSteps: string[];
};

function formatNumber(value: unknown, digits = 4) {
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric.toFixed(digits) : "-";
}

function formatPercent(value: unknown, digits = 2) {
  const numeric = Number(value);
  return Number.isFinite(numeric) ? `${(numeric * 100).toFixed(digits)}%` : "-";
}

function displayModelName(name: string | undefined) {
  return (name || "No champion selected").replace(/\s*\(k\s*=\s*\d+\)/i, "");
}

function eventRateForTarget(rows: Record<string, unknown>[], target: string | null) {
  if (!target || !rows.length) return null;
  const values = rows.map((row) => row[target]).filter((value) => value !== null && value !== undefined && String(value).trim() !== "");
  if (!values.length) return null;
  const numeric = values.map((value) => Number(value));
  const numericCount = numeric.filter(Number.isFinite).length;
  if (numericCount / values.length >= 0.8) {
    const positives = numeric.filter((value) => value === 1).length;
    const zeros = numeric.filter((value) => value === 0).length;
    if (positives + zeros >= values.length * 0.8) return positives / Math.max(1, positives + zeros);
  }
  const counts = new Map<string, number>();
  values.forEach((value) => counts.set(String(value), (counts.get(String(value)) ?? 0) + 1));
  const sorted = Array.from(counts.values()).sort((a, b) => a - b);
  return sorted.length > 1 ? sorted[0] / values.length : null;
}

function topPredictors(modelKey: string | null) {
  const experiments = loadExperiments();
  const champion = experiments.find((experiment) => experiment.champion);
  const selected = modelKey ? experiments.find((experiment) => experiment.modelKey === modelKey) : null;
  const source = selected ?? champion ?? experiments[0];
  return (source?.featureImportance ?? [])
    .slice()
    .sort((a, b) => Math.abs(Number(b.importance ?? 0)) - Math.abs(Number(a.importance ?? 0)))
    .slice(0, 5)
    .map((row) => row.feature);
}

function classifyReadiness({
  problemType,
  selectedModel,
  curves,
  eventRate,
  riskCount,
}: {
  problemType: "classification" | "regression" | null;
  selectedModel: RankedModel | null;
  curves: EvaluationCurves | null;
  eventRate: number | null;
  riskCount: number;
}): ExecutiveSummary["productionReadiness"] {
  const metrics = curves?.metrics ?? selectedModel ?? {};
  if (!selectedModel || riskCount >= 4) return "Research only";
  if (problemType === "regression") {
    const r2 = Number(metrics.r2 ?? selectedModel.r2);
    const rmse = Number(metrics.rmse ?? selectedModel.rmse);
    if (Number.isFinite(r2) && r2 >= 0.65 && Number.isFinite(rmse)) return "Validation candidate";
    return "Research only";
  }
  const auc = Number(metrics.auc ?? selectedModel.auc);
  const prAuc = Number(metrics.pr_auc ?? selectedModel.pr_auc);
  const f1 = Number(metrics.f1 ?? selectedModel.f1);
  if (eventRate !== null && eventRate < 0.01 && (!Number.isFinite(prAuc) || prAuc < Math.max(0.05, eventRate * 4))) {
    return "Research only";
  }
  if ((Number.isFinite(auc) && auc >= 0.75) || (Number.isFinite(f1) && f1 >= 0.5)) return "Validation candidate";
  return "Research only";
}

export function buildExecutiveSummary(selectedModel: RankedModel | null, curves: EvaluationCurves | null): ExecutiveSummary {
  const dataset = loadLocalDataset();
  const context = loadProjectContext();
  const problemType = inferLocalProblemType(dataset);
  const eventRate = eventRateForTarget(dataset?.rows ?? [], dataset?.target ?? null);
  const predictors = topPredictors(selectedModel?.key ?? null);
  const metrics = curves?.metrics ?? selectedModel ?? {};
  const risks: string[] = [];
  const nextSteps: string[] = [];

  if (!dataset?.rows.length) risks.push("No active development dataset is available in the browser session.");
  if (!context.businessObjective.trim()) risks.push("The business objective is not fully documented.");
  if (problemType === "classification" && eventRate !== null && eventRate < 0.01) {
    risks.push("This is a rare-event model; accuracy can overstate true effectiveness.");
    nextSteps.push("Review PR-AUC, recall, lift, calibration, and threshold performance before champion approval.");
  }
  if (context.regulatoryEnvironment.some((item) => ["Fair Lending", "FCRA", "ECOA"].includes(item))) {
    risks.push("Fair lending, adverse-action, and proxy-risk review are required before production use.");
    nextSteps.push("Complete fairness review and document protected-class proxy risk, exclusions, and reason-code support.");
  }
  if (context.interpretabilityRequirement === "high" && selectedModel && !/logistic|linear|tree|ebm/i.test(selectedModel.name)) {
    risks.push("The selected model may be harder to explain than the project interpretability requirement suggests.");
    nextSteps.push("Compare against transparent challenger models and document the performance-versus-interpretability tradeoff.");
  }
  if (context.deploymentExpectation === "real-time API" && selectedModel && /knn|svm|neural|mlp/i.test(selectedModel.name)) {
    risks.push("The selected model may require latency review for real-time deployment.");
    nextSteps.push("Benchmark scoring latency and verify the full preprocessing pipeline can run in production.");
  }
  if (!predictors.length) {
    risks.push("Feature importance evidence is not yet captured for the selected model.");
    nextSteps.push("Run interpretation diagnostics and confirm the strongest predictors are intuitive and stable.");
  }
  if (!nextSteps.length) {
    nextSteps.push("Move to model interpretation and confirm feature importance, sensitivity, RFE, stability, and governance documentation.");
  }
  nextSteps.push("Score TEST and OOT datasets and review performance stability before final model packaging.");

  const readiness = classifyReadiness({ problemType, selectedModel, curves, eventRate, riskCount: risks.length });
  const primaryMetric = context.primarySuccessMetric || (problemType === "regression" ? "RMSE / MAE / R-squared" : "AUC / PR-AUC / lift");
  const secondaryMetrics = context.secondaryMetrics || (problemType === "regression" ? "Residual bias and prediction stability" : "Precision, recall, F1, KS, calibration");
  const monitoringCadence =
    context.monitoringCadence === "custom"
      ? context.monitoringCadenceCustom || "Custom"
      : context.monitoringCadence;
  const champion = displayModelName(selectedModel?.name);
  const overview =
    readiness === "Validation candidate"
      ? `The current run has produced a credible ${champion} candidate for validation review. Leadership should treat this as ready for deeper model risk, stability, and governance review rather than immediate production release.`
      : readiness === "Production candidate"
        ? `The current run appears directionally suitable for production planning, subject to validation, controls, monitoring, and governance approval.`
        : `The current run should be treated as research only until the open risks are resolved and validation evidence is strengthened.`;

  return {
    headline: `${champion} evaluation summary`,
    productionReadiness: readiness,
    overview,
    stats: [
      { label: "Model ID #", value: context.modelId || "Required" },
      { label: "Dataset size", value: dataset?.rows.length ? dataset.rows.length.toLocaleString() : "-" },
      { label: "Target", value: dataset?.target ?? "-" },
      { label: "Event rate", value: problemType === "classification" ? formatPercent(eventRate) : "Not applicable" },
      { label: "Champion model", value: champion },
      { label: "Primary metric", value: primaryMetric },
      { label: "Secondary metrics", value: secondaryMetrics },
      { label: "Monitoring cadence", value: monitoringCadence },
      { label: "Monitoring metrics", value: context.monitoringMetrics.length ? context.monitoringMetrics.join(", ") : "Not selected" },
      { label: "AUC", value: formatNumber(metrics.auc) },
      { label: "PR-AUC", value: formatNumber(metrics.pr_auc) },
      { label: "RMSE", value: formatNumber(metrics.rmse) },
      { label: "R-squared", value: formatNumber(metrics.r2) },
    ],
    strongestPredictors: predictors.length ? predictors : ["Not available yet"],
    keyRisks: risks.length ? risks : ["No major blocking risks identified from the available artifacts."],
    recommendedNextSteps: nextSteps,
  };
}
