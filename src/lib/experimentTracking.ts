import { logDecision } from "./decisionJournal";
import { loadLocalDataset } from "./localDataset";
import { BRAND } from "../config/brand";

export const EXPERIMENT_TRACKING_KEY = "modeling-tool-mlflow-lite-experiments";

export type ExperimentMetricSet = {
  auc?: number;
  pr_auc?: number;
  precision?: number;
  recall?: number;
  f1?: number;
  ks?: number;
  lift?: number;
  calibration?: number | string;
  rmse?: number;
  mae?: number;
  mse?: number;
  r2?: number;
  adjusted_r2?: number;
};

export type ExperimentRecord = {
  experimentId: string;
  timestamp: string;
  datasetHash: string;
  datasetVersion: string;
  selectedFeatures: string[];
  preprocessingSteps: Record<string, unknown>;
  balancingMethod: string;
  splitStrategy: string;
  modelKey: string;
  modelType: string;
  hyperparameters: Record<string, unknown> | null;
  metrics: ExperimentMetricSet;
  confusionMatrix?: number[][];
  rocData?: { fpr: number[]; tpr: number[] };
  prData?: { precision: number[]; recall: number[] };
  featureImportance?: { feature: string; importance: number; direction?: number; source?: string }[];
  calibrationStatus: string;
  interpretability: number;
  runtimeMs: number;
  champion: boolean;
  notes: string;
};

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
  best_params?: Record<string, unknown> | null;
};

type CaptureInput = {
  apiBase: string;
  ranked: RankedModel[];
  selectedModelKeys: string[];
  trainingSettings: Record<string, unknown>;
  runtimeMs: number;
  calibrated: boolean;
};

function readJson<T>(key: string, fallback: T): T {
  try {
    const parsed = JSON.parse(localStorage.getItem(key) || "");
    return parsed ?? fallback;
  } catch {
    return fallback;
  }
}

function hashString(text: string) {
  let hash = 2166136261;
  for (let i = 0; i < text.length; i++) {
    hash ^= text.charCodeAt(i);
    hash = Math.imul(hash, 16777619);
  }
  return (hash >>> 0).toString(16).padStart(8, "0");
}

export function getDatasetVersion() {
  const dataset = loadLocalDataset();
  if (!dataset) return { datasetHash: "no-dataset", datasetVersion: "no-dataset", selectedFeatures: [] as string[] };
  const selectedFeatures = dataset.selected_columns ?? dataset.headers.filter((header) => header !== dataset.target);
  const signature = JSON.stringify({
    headers: dataset.headers,
    target: dataset.target,
    selectedFeatures,
    rows: dataset.rows.length,
    firstRows: dataset.rows.slice(0, 25),
  });
  const datasetHash = hashString(signature);
  return {
    datasetHash,
    datasetVersion: `${dataset.target ?? "target"}-${dataset.rows.length}-${datasetHash}`,
    selectedFeatures,
  };
}

export function loadExperiments(): ExperimentRecord[] {
  return readJson<ExperimentRecord[]>(EXPERIMENT_TRACKING_KEY, []);
}

export function saveExperiments(experiments: ExperimentRecord[]) {
  localStorage.setItem(EXPERIMENT_TRACKING_KEY, JSON.stringify(experiments));
  window.dispatchEvent(new CustomEvent("experiment-tracking-updated"));
}

function buildPreprocessingSteps(trainingSettings: Record<string, unknown>) {
  return {
    outlierMethods: readJson<Record<string, string>>("modeling-tool-outlier-methods", {}),
    missingStrategies: readJson<Record<string, unknown>>("modeling-tool-missing-config", {}),
    splitStrategy: localStorage.getItem("splitStrategy") ?? "holdout",
    balanceMethod: localStorage.getItem("balanceMethod") ?? "none",
    balanceRatio: localStorage.getItem("balanceRatio") ?? "",
    kFolds: localStorage.getItem("kFolds") ?? "",
    trainingSettings,
  };
}

async function getJson<T>(url: string): Promise<T | null> {
  try {
    const response = await fetch(url);
    if (!response.ok) return null;
    return (await response.json()) as T;
  } catch {
    return null;
  }
}

function ksFromRoc(roc?: { fpr: number[]; tpr: number[] }) {
  if (!roc?.fpr?.length || !roc?.tpr?.length) return undefined;
  const n = Math.min(roc.fpr.length, roc.tpr.length);
  let best = 0;
  for (let i = 0; i < n; i++) best = Math.max(best, Math.abs((roc.tpr[i] ?? 0) - (roc.fpr[i] ?? 0)));
  return best;
}

function compactCurve(curve?: { fpr?: number[]; tpr?: number[]; precision?: number[]; recall?: number[] }) {
  if (!curve) return undefined;
  const keys = Object.keys(curve) as Array<keyof typeof curve>;
  const maxLength = Math.max(...keys.map((key) => curve[key]?.length ?? 0), 0);
  if (!maxLength) return undefined;
  const step = Math.max(1, Math.ceil(maxLength / 80));
  const compacted: Record<string, number[]> = {};
  keys.forEach((key) => {
    const values = curve[key] ?? [];
    compacted[key] = values.filter((_, index) => index % step === 0).slice(0, 80);
  });
  return compacted;
}

function interpretabilityScore(modelKey: string, modelName: string) {
  if (/logreg|linreg|linear|logistic/i.test(`${modelKey} ${modelName}`)) return 95;
  if (/dtree|tree|ebm/i.test(`${modelKey} ${modelName}`)) return 82;
  if (/rf|xgb|lgbm|cat/i.test(`${modelKey} ${modelName}`)) return 52;
  if (/knn|svm|mlp/i.test(`${modelKey} ${modelName}`)) return 38;
  return 60;
}

function compactTimestamp() {
  return new Date().toISOString().replace(/\D/g, "").slice(0, 14);
}

async function captureDiagnostics(apiBase: string, modelKey: string) {
  const [curves, importance, deciles] = await Promise.all([
    getJson<{
      ok?: boolean;
      metrics?: ExperimentMetricSet;
      confusion?: number[][];
      roc?: { fpr: number[]; tpr: number[] };
      pr?: { precision: number[]; recall: number[] };
    }>(`${apiBase}/eval/curves?model=${encodeURIComponent(modelKey)}`),
    getJson<{ ok?: boolean; rows?: ExperimentRecord["featureImportance"] }>(
      `${apiBase}/interpretation/importance?model=${encodeURIComponent(modelKey)}`
    ),
    getJson<{ ok?: boolean; rows?: { decile?: number; lift?: number }[] }>(
      `${apiBase}/eval/deciles?model=${encodeURIComponent(modelKey)}`
    ),
  ]);

  const topLift = deciles?.rows?.length
    ? Math.max(...deciles.rows.map((row) => Number(row.lift ?? 0)).filter(Number.isFinite))
    : undefined;

  return {
    curves,
    featureImportance: (importance?.rows ?? []).slice(0, 25),
    topLift,
  };
}

export async function recordTrainingExperiments(input: CaptureInput) {
  const { datasetHash, datasetVersion, selectedFeatures } = getDatasetVersion();
  const preprocessingSteps = buildPreprocessingSteps(input.trainingSettings);
  const existing = loadExperiments().map((experiment) => ({ ...experiment, champion: false }));

  const records = await Promise.all(
    input.ranked
      .filter((model) => input.selectedModelKeys.includes(model.key))
      .map(async (model) => {
        const diagnostics = await captureDiagnostics(input.apiBase, model.key);
        const curveMetrics = diagnostics.curves?.metrics ?? {};
        const metrics: ExperimentMetricSet = {
          auc: curveMetrics.auc ?? model.auc,
          pr_auc: curveMetrics.pr_auc ?? model.pr_auc,
          precision: curveMetrics.precision,
          recall: curveMetrics.recall,
          f1: curveMetrics.f1 ?? model.f1,
          ks: ksFromRoc(diagnostics.curves?.roc),
          lift: diagnostics.topLift,
          calibration: input.calibrated ? "calibrated" : "not calibrated",
          rmse: curveMetrics.rmse ?? model.rmse,
          mae: curveMetrics.mae ?? model.mae,
          mse: curveMetrics.mse ?? model.mse,
          r2: curveMetrics.r2 ?? model.r2,
          adjusted_r2: curveMetrics.adjusted_r2 ?? model.adjusted_r2,
        };

        return {
          experimentId: `${compactTimestamp()}-${model.key}-${hashString(datasetHash + model.key + Math.random())}`,
          timestamp: new Date().toISOString(),
          datasetHash,
          datasetVersion,
          selectedFeatures,
          preprocessingSteps,
          balancingMethod: String(localStorage.getItem("balanceMethod") ?? "none"),
          splitStrategy: String(localStorage.getItem("splitStrategy") ?? "holdout"),
          modelKey: model.key,
          modelType: model.name,
          hyperparameters: model.best_params ?? null,
          metrics,
          confusionMatrix: diagnostics.curves?.confusion,
          rocData: compactCurve(diagnostics.curves?.roc) as ExperimentRecord["rocData"],
          prData: compactCurve(diagnostics.curves?.pr) as ExperimentRecord["prData"],
          featureImportance: diagnostics.featureImportance,
          calibrationStatus: input.calibrated ? "calibrated" : "not calibrated",
          interpretability: interpretabilityScore(model.key, model.name),
          runtimeMs: Math.round(input.runtimeMs / Math.max(1, input.selectedModelKeys.length)),
          champion: false,
          notes: "Candidate model. Champion approval requires Evaluation and governance review.",
        } satisfies ExperimentRecord;
      })
  );

  const next = [...records, ...existing].slice(0, 100);
  saveExperiments(next);
  return records;
}

export function promoteExperimentToChampion(experimentId: string) {
  const experiments = loadExperiments();
  const promoted = experiments.find((experiment) => experiment.experimentId === experimentId);
  const next = experiments.map((experiment) => ({
    ...experiment,
    champion: experiment.experimentId === experimentId,
  }));
  saveExperiments(next);
  if (promoted) {
    logDecision({
      workflowStep: "Experiment Comparison",
      actionType: "champion_model_selected",
      subject: promoted.modelType,
      previousValue: experiments.find((experiment) => experiment.champion)?.experimentId ?? "-",
      newValue: promoted.experimentId,
      systemRecommendation:
        "Promote an experiment only after comparing performance, calibration, interpretability, runtime, and governance fit.",
      followStatus: "unknown",
    });
  }
  return next;
}

export function updateExperimentNotes(experimentId: string, notes: string) {
  const next = loadExperiments().map((experiment) =>
    experiment.experimentId === experimentId ? { ...experiment, notes } : experiment
  );
  saveExperiments(next);
  return next;
}

export function exportExperimentsCsv(experiments: ExperimentRecord[]) {
  const headers = [
    "product",
    "product_subtitle",
    "experiment_id",
    "timestamp",
    "dataset_version",
    "model_type",
    "auc",
    "pr_auc",
    "precision",
    "recall",
    "f1",
    "ks",
    "lift",
    "calibration",
    "interpretability",
    "runtime_ms",
    "champion",
    "notes",
  ];
  const escape = (value: unknown) => `"${String(value ?? "").replace(/"/g, '""')}"`;
  const rows = experiments.map((experiment) =>
    [
      BRAND.productName,
      BRAND.productSubtitle,
      experiment.experimentId,
      experiment.timestamp,
      experiment.datasetVersion,
      experiment.modelType,
      experiment.metrics.auc,
      experiment.metrics.pr_auc,
      experiment.metrics.precision,
      experiment.metrics.recall,
      experiment.metrics.f1,
      experiment.metrics.ks,
      experiment.metrics.lift,
      experiment.calibrationStatus,
      experiment.interpretability,
      experiment.runtimeMs,
      experiment.champion,
      experiment.notes,
    ]
      .map(escape)
      .join(",")
  );
  return [headers.join(","), ...rows].join("\n");
}
