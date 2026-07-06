import { inferLocalProblemType, loadLocalDataset, type LocalDataset } from "./localDataset";
import { loadProjectContext, type ProjectContext } from "./projectContext";

export type AtlasProblemType = "classification" | "regression" | "unknown";
export type AtlasTargetType = "binary" | "multiclass" | "continuous" | "unknown";

export const classificationMetricSet = [
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

export const regressionMetricSet = [
  "RMSE",
  "MAE",
  "MAPE",
  "R-squared",
  "Adjusted R-squared",
  "PSI",
  "VSI",
] as const;

export function getProblemType(context?: Partial<ProjectContext> | null, dataset?: LocalDataset | null): AtlasProblemType {
  if (context?.modelType === "regression") return "regression";
  const activeDataset = dataset === undefined ? loadLocalDataset() : dataset;
  const inferred = inferLocalProblemType(activeDataset);
  if (inferred === "classification" || inferred === "regression") return inferred;
  const activeContext = context === undefined ? loadProjectContext() : context;
  if (activeContext?.modelType === "regression") return "regression";
  if (activeContext?.modelType) return "classification";
  return "unknown";
}

export function isRegressionProject(context?: Partial<ProjectContext> | null, dataset?: LocalDataset | null) {
  return getProblemType(context, dataset) === "regression";
}

export function isClassificationProject(context?: Partial<ProjectContext> | null, dataset?: LocalDataset | null) {
  return getProblemType(context, dataset) === "classification";
}

export function getTargetType(dataset: LocalDataset | null = loadLocalDataset()): AtlasTargetType {
  if (!dataset?.target || !dataset.rows.length) return "unknown";
  const values = dataset.rows
    .map((row) => row[dataset.target as string])
    .filter((value) => value !== null && value !== undefined && String(value).trim() !== "");
  if (!values.length) return "unknown";
  const numericCount = values.filter((value) => Number.isFinite(Number(value))).length;
  const uniqueCount = new Set(values.map((value) => String(value))).size;
  if (numericCount / values.length >= 0.9 && uniqueCount > 10) return "continuous";
  return uniqueCount <= 2 ? "binary" : "multiclass";
}

export function isBinaryClassificationProject(context?: Partial<ProjectContext> | null, dataset?: LocalDataset | null) {
  const activeDataset = dataset === undefined ? loadLocalDataset() : dataset;
  return getProblemType(context, activeDataset) === "classification" && getTargetType(activeDataset) === "binary";
}

export function getMetricSetForProblemType(problemType: AtlasProblemType | string | null | undefined) {
  return String(problemType).toLowerCase() === "regression"
    ? [...regressionMetricSet]
    : [...classificationMetricSet];
}

export function isRegressionMetricKey(key: string) {
  return ["rmse", "mae", "mape", "mse", "r2", "adjusted_r2", "mean_residual", "mean_abs_residual"].includes(
    key.toLowerCase()
  );
}

export function isClassificationMetricKey(key: string) {
  return ["auc", "pr_auc", "precision", "recall", "f1", "ks", "lift", "accuracy", "calibration"].includes(
    key.toLowerCase()
  );
}
