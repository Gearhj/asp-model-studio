import { logDecision } from "./decisionJournal";
import { loadLocalDataset } from "./localDataset";
import { BRAND } from "../config/brand";
import {
  assertExactDatasetIdentity,
  requireCanonicalDatasetIdentity,
  requireLocalDatasetCanonicalIdentity,
  type CanonicalDatasetIdentityInput,
} from "./datasetIdentity";

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
  project_id: string;
  dataset_id: string;
  dataset_version_id: string;
  trainingJobId: string;
  accessMetadataId?: string;
  datasetContentHash?: string;
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
  candidate_champion?: boolean;
  auc?: number;
  pr_auc?: number;
  precision?: number | null;
  recall?: number | null;
  accuracy?: number;
  f1?: number;
  ks?: number | null;
  mae?: number;
  mse?: number;
  rmse?: number;
  r2?: number;
  adjusted_r2?: number;
  best_params?: Record<string, unknown> | null;
  governed_preprocessing?: Record<string, unknown>;
  validation_policy_execution?: Record<string, unknown>;
};

type CaptureInput = {
  datasetIdentity: CanonicalDatasetIdentityInput;
  trainingJobId: string;
  ranked: RankedModel[];
  selectedModelKeys: string[];
  trainingSettings: Record<string, unknown>;
  governedPreprocessingContract: Record<string, unknown>;
  validationExecutionPolicy: Record<string, unknown>;
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

function getCanonicalDatasetContext(identityInput: CanonicalDatasetIdentityInput) {
  const identity = requireCanonicalDatasetIdentity(
    identityInput,
    "Training experiment dataset identity",
  );
  const dataset = loadLocalDataset();
  if (!dataset) {
    throw new Error(
      "Training experiment persistence requires the active canonical local dataset.",
    );
  }
  const localIdentity = requireLocalDatasetCanonicalIdentity(
    identity.project_id,
    dataset,
    "Training experiment local dataset identity",
  );
  assertExactDatasetIdentity(
    identity,
    localIdentity,
    "Training experiment local dataset identity",
  );
  const selectedFeatures = dataset.selected_columns ?? dataset.headers.filter((header) => header !== dataset.target);
  return {
    identity,
    selectedFeatures,
    accessMetadataId:
      typeof dataset.data_access?.accessMetadataId === "string" &&
      dataset.data_access.accessMetadataId.trim()
        ? dataset.data_access.accessMetadataId.trim()
        : undefined,
    datasetContentHash:
      typeof dataset.data_access?.hash === "string" &&
      dataset.data_access.hash.trim()
        ? dataset.data_access.hash.trim()
        : undefined,
  };
}

function requiredText(value: unknown) {
  return typeof value === "string" && value.trim().length > 0;
}

/**
 * Legacy experiment rows used a target-rowCount-hash pseudo-version and had no
 * canonical project/dataset/version triple. They remain stale historical
 * browser data and are never eligible for selection, documentation, or
 * promotion.
 */
export function isCanonicalExperimentRecord(value: unknown): value is ExperimentRecord {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const record = value as Record<string, unknown>;
  if (
    !requiredText(record.experimentId) ||
    !requiredText(record.project_id) ||
    !requiredText(record.dataset_id) ||
    !requiredText(record.dataset_version_id)
  ) {
    return false;
  }
  const compatibilityVersion =
    typeof record.datasetVersion === "string"
      ? record.datasetVersion.trim()
      : "";
  return (
    !compatibilityVersion ||
    compatibilityVersion === String(record.dataset_version_id).trim()
  );
}

export function loadExperiments(
  identityInput?: CanonicalDatasetIdentityInput,
): ExperimentRecord[] {
  const stored = readJson<unknown[]>(EXPERIMENT_TRACKING_KEY, []);
  const canonical = Array.isArray(stored)
    ? stored.filter(isCanonicalExperimentRecord)
    : [];
  if (!identityInput) return canonical;
  const identity = requireCanonicalDatasetIdentity(
    identityInput,
    "Experiment selection dataset identity",
  );
  return canonical.filter(
    (experiment) =>
      experiment.project_id === identity.project_id &&
      experiment.dataset_id === identity.dataset_id &&
      experiment.dataset_version_id === identity.dataset_version_id,
  );
}

export function saveExperiments(experiments: ExperimentRecord[]) {
  if (!experiments.every(isCanonicalExperimentRecord)) {
    throw new Error(
      "Experiment persistence requires an exact canonical project_id, dataset_id, and dataset_version_id.",
    );
  }
  localStorage.setItem(EXPERIMENT_TRACKING_KEY, JSON.stringify(experiments));
  window.dispatchEvent(new CustomEvent("experiment-tracking-updated"));
}

function buildPreprocessingSteps(
  trainingSettings: Record<string, unknown>,
  governedContract: Record<string, unknown>,
  validationExecutionPolicy: Record<string, unknown>,
  modelExecution?: RankedModel,
) {
  const version = Number(governedContract.preprocessing_contract_version ?? 0);
  const policyId = String(governedContract.preprocessing_policy_id ?? "").trim();
  const policyHash = String(governedContract.preprocessing_policy_hash ?? "").trim();
  if (version !== 2 || !policyId || !policyHash) {
    throw new Error(
      "Training experiment persistence requires the backend-authoritative preprocessing v2 contract.",
    );
  }
  const outlierPolicy =
    governedContract.outlier_policy && typeof governedContract.outlier_policy === "object"
      ? (governedContract.outlier_policy as Record<string, unknown>)
      : {};
  const missingPolicy =
    governedContract.missing_policy && typeof governedContract.missing_policy === "object"
      ? (governedContract.missing_policy as Record<string, unknown>)
      : {};
  return {
    authority: "backend_governed_training_execution",
    preprocessingContractVersion: version,
    preprocessingPolicyId: policyId,
    preprocessingPolicyRevision: governedContract.preprocessing_policy_revision,
    preprocessingPolicyHash: policyHash,
    outlierPolicy,
    missingPolicy,
    validationExecutionPolicy,
    modelGovernedPreprocessing: modelExecution?.governed_preprocessing ?? {},
    foldLocalExecution: modelExecution?.validation_policy_execution ?? {},
    trainingSettings,
  };
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

export async function recordTrainingExperiments(input: CaptureInput) {
  const {
    identity,
    selectedFeatures,
    accessMetadataId,
    datasetContentHash,
  } = getCanonicalDatasetContext(input.datasetIdentity);
  const trainingJobId =
    typeof input.trainingJobId === "string" ? input.trainingJobId.trim() : "";
  if (!trainingJobId) {
    throw new Error(
      "Training experiment persistence requires an explicit training job artifact ID.",
    );
  }
  const existing = loadExperiments().map((experiment) =>
    experiment.project_id === identity.project_id &&
    experiment.dataset_id === identity.dataset_id &&
    experiment.dataset_version_id === identity.dataset_version_id
      ? { ...experiment, champion: false }
      : experiment,
  );

  const records = await Promise.all(
    input.ranked
      .filter((model) => input.selectedModelKeys.includes(model.key))
      .map(async (model) => {
        const preprocessingSteps = buildPreprocessingSteps(
          input.trainingSettings,
          input.governedPreprocessingContract,
          input.validationExecutionPolicy,
          model,
        );
        const metrics: ExperimentMetricSet = {
          auc: model.auc,
          pr_auc: model.pr_auc,
          precision: model.precision ?? undefined,
          recall: model.recall ?? undefined,
          f1: model.f1,
          ks: model.ks ?? undefined,
          calibration: input.calibrated ? "calibrated" : "not calibrated",
          rmse: model.rmse,
          mae: model.mae,
          mse: model.mse,
          r2: model.r2,
          adjusted_r2: model.adjusted_r2,
        };

        return {
          experimentId: `${compactTimestamp()}-${model.key}-${hashString(
            `${identity.project_id}:${identity.dataset_id}:${identity.dataset_version_id}:${trainingJobId}:${model.key}:${Math.random()}`,
          )}`,
          timestamp: new Date().toISOString(),
          project_id: identity.project_id,
          dataset_id: identity.dataset_id,
          dataset_version_id: identity.dataset_version_id,
          trainingJobId,
          accessMetadataId,
          datasetContentHash,
          selectedFeatures,
          preprocessingSteps,
          balancingMethod: String(
            input.validationExecutionPolicy.balancing_method ?? "none",
          ),
          splitStrategy: "sealed_analysis_partition_with_approved_validation_design",
          modelKey: model.key,
          modelType: model.name,
          hyperparameters: model.best_params ?? null,
          metrics,
          confusionMatrix: undefined,
          rocData: undefined,
          prData: undefined,
          featureImportance: undefined,
          calibrationStatus: input.calibrated ? "calibrated" : "not calibrated",
          interpretability: interpretabilityScore(model.key, model.name),
          runtimeMs: Math.round(input.runtimeMs / Math.max(1, input.selectedModelKeys.length)),
          champion: false,
          notes: model.candidate_champion
            ? "Training leader under the governed fold-valid selection metric. Final-holdout diagnostics are intentionally absent until candidate lock."
            : "Governed Development/CV candidate; no Evaluation or Interpretation endpoint was called before lock.",
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
    champion:
      promoted &&
      experiment.project_id === promoted.project_id &&
      experiment.dataset_id === promoted.dataset_id &&
      experiment.dataset_version_id === promoted.dataset_version_id
        ? experiment.experimentId === experimentId
        : experiment.champion,
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
    "project_id",
    "dataset_id",
    "dataset_version_id",
    "training_job_id",
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
      experiment.project_id,
      experiment.dataset_id,
      experiment.dataset_version_id,
      experiment.trainingJobId,
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
