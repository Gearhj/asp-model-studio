import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import {
  Activity,
  AlertTriangle,
  BrainCircuit,
  CheckCircle2,
  ChevronDown,
  CircleStop,
  Clock3,
  Cpu,
  Filter,
  Gauge,
  GitCompareArrows,
  Layers3,
  LockKeyhole,
  LoaderCircle,
  MemoryStick,
  Play,
  RefreshCw,
  RotateCcw,
  Search,
  ShieldCheck,
  SlidersHorizontal,
  Target,
  Timer,
  Trophy,
  Trash2,
  XCircle,
} from "lucide-react";
import StepShell from "../components/StepShell";
import {
  AtlasAttentionPanel,
  AtlasDataScopeBadge,
  AtlasExecutionStatus,
  AtlasStatusStrip,
  AtlasWorkflowSection,
  type AtlasWorkflowMetric,
} from "../components/ui/AtlasWorkflow";
import { createEvidence } from "../lib/evidenceGraph";
import { me } from "../lib/auth";
import {
  assertExactDatasetIdentity,
  buildCanonicalEvidenceEnvelope,
  canonicalDatasetStorageKey,
  requireLocalDatasetCanonicalIdentity,
  type CanonicalDatasetIdentity,
} from "../lib/datasetIdentity";
import { getFeatureManifest, type FeatureManifest } from "../lib/featureManifest";
import { loadLocalDataset } from "../lib/localDataset";
import { logDecision } from "../lib/decisionJournal";
import { recordTrainingExperiments } from "../lib/experimentTracking";
import { useWorkflowStore } from "../state/useWorkflowStore";

const API_BASE =
  (import.meta.env.VITE_API_BASE as string | undefined)?.replace(/\/$/, "") ||
  "http://127.0.0.1:8001/api";
const ACTIVE_JOB_KEY = "modeling-tool-active-training-job";
const TRAINING_CONFIG_KEY = "modeling-tool-training-config";

type ProblemType = "classification" | "regression";
type CandidateStrategy =
  | "transparent_baseline"
  | "interpretable_challenger"
  | "nonlinear_benchmark"
  | "performance_challenger"
  | "full_research_bench"
  | "custom_portfolio";
type JobState = "queued" | "preparing" | "running" | "complete" | "failed" | "cancelled" | "interrupted";
type ModelState = JobState;

type ModelDefinition = {
  key: string;
  label: string;
  family: string;
  task: ProblemType;
  purpose: string;
  bestUse: string;
  interpretability: "High" | "Medium" | "Low";
  scaling: string;
  categorical: string;
  probability: string;
  kind?: "supervised" | "anomaly";
};

const MODEL_DEFINITIONS: ModelDefinition[] = [
  { key: "logreg", label: "Logistic Regression", family: "Transparent Models", task: "classification", purpose: "Auditable probability baseline with coefficient evidence.", bestUse: "Regulated classification and scorecard comparison", interpretability: "High", scaling: "Applied in pipeline", categorical: "Encoded", probability: "Native" },
  { key: "ridge_clf", label: "Ridge Classifier", family: "Transparent Models", task: "classification", purpose: "Regularized linear classifier with stable coefficient direction and calibrated scores.", bestUse: "Auditable broad-feature baseline when predictors are correlated", interpretability: "High", scaling: "Required", categorical: "Encoded", probability: "Calibrated" },
  { key: "dtree", label: "Decision Tree", family: "Transparent Models", task: "classification", purpose: "Compact nonlinear rules with reviewable decision paths.", bestUse: "Segment logic and transparent challenger analysis", interpretability: "High", scaling: "Not required", categorical: "Encoded", probability: "Native" },
  { key: "ebm", label: "Explainable Boosting Machine", family: "Transparent Models", task: "classification", purpose: "Interpretable boosted effects for nonlinear relationships.", bestUse: "Performance with feature-shape explainability", interpretability: "High", scaling: "Applied in pipeline", categorical: "Encoded", probability: "Native" },
  { key: "lda", label: "Linear Discriminant Analysis", family: "Transparent Models", task: "classification", purpose: "Linear class-separation benchmark with simple discriminant assumptions.", bestUse: "Fast transparent baseline when classes separate roughly linearly", interpretability: "High", scaling: "Required", categorical: "Encoded", probability: "Native" },
  { key: "gnb", label: "Gaussian Naive Bayes", family: "Probabilistic Models", task: "classification", purpose: "Fast probabilistic benchmark under conditional-independence assumptions.", bestUse: "High-dimensional screening and transparent benchmark comparisons", interpretability: "High", scaling: "Applied in pipeline", categorical: "Encoded", probability: "Native" },
  { key: "bernoulli_nb", label: "Bernoulli Naive Bayes", family: "Probabilistic Models", task: "classification", purpose: "Fast probability benchmark for binary or indicator-style features.", bestUse: "Sparse flags, binary indicators, and rapid screening", interpretability: "High", scaling: "Applied in pipeline", categorical: "Encoded", probability: "Native" },
  { key: "qda", label: "Quadratic Discriminant Analysis", family: "Probabilistic Models", task: "classification", purpose: "Probabilistic classifier with class-specific covariance structure.", bestUse: "Small-to-midsize benchmarks where class shapes differ", interpretability: "Medium", scaling: "Required", categorical: "Encoded", probability: "Native" },
  { key: "sgd_log", label: "SGD Logistic Classifier", family: "Transparent Models", task: "classification", purpose: "Elastic-net logistic learning designed for broad or high-volume feature matrices.", bestUse: "Fast scalable linear challenger with regularization", interpretability: "High", scaling: "Required", categorical: "Encoded", probability: "Native" },
  { key: "histgb", label: "Histogram Gradient Boosting", family: "Tree and Ensemble Models", task: "classification", purpose: "Efficient native histogram boosting with nonlinear interaction capacity.", bestUse: "Strong scikit-learn tabular challenger without optional libraries", interpretability: "Medium", scaling: "Applied in pipeline", categorical: "Encoded", probability: "Native" },
  { key: "rf", label: "Random Forest", family: "Tree and Ensemble Models", task: "classification", purpose: "Robust nonlinear benchmark across interactions and mixed signal.", bestUse: "Stable challenger and feature-importance benchmark", interpretability: "Medium", scaling: "Not required", categorical: "Encoded", probability: "Native" },
  { key: "extra_trees", label: "Extra Trees", family: "Tree and Ensemble Models", task: "classification", purpose: "Highly randomized trees for a fast nonlinear variance-reduction benchmark.", bestUse: "Interaction-heavy tabular challenger and importance benchmark", interpretability: "Medium", scaling: "Not required", categorical: "Encoded", probability: "Native" },
  { key: "xgb", label: "XGBoost", family: "Tree and Ensemble Models", task: "classification", purpose: "Regularized gradient boosting for high-performing tabular models.", bestUse: "Performance-focused challenger with careful tuning", interpretability: "Low", scaling: "Not required", categorical: "Encoded", probability: "Native" },
  { key: "cat", label: "CatBoost", family: "Tree and Ensemble Models", task: "classification", purpose: "Boosted learner with strong nonlinear tabular performance.", bestUse: "Categorical-rich challenger benchmarking", interpretability: "Low", scaling: "Not required", categorical: "Encoded", probability: "Native" },
  { key: "lgbm", label: "LightGBM", family: "Tree and Ensemble Models", task: "classification", purpose: "Efficient gradient boosting for larger modeling populations.", bestUse: "Fast challenger search on broad feature sets", interpretability: "Low", scaling: "Not required", categorical: "Encoded", probability: "Native" },
  { key: "knn", label: "K-Nearest Neighbors", family: "Distance and Margin Models", task: "classification", purpose: "Local-neighborhood benchmark on standardized predictors.", bestUse: "Similarity-based benchmark on moderate data", interpretability: "Medium", scaling: "Required", categorical: "Encoded", probability: "Native" },
  { key: "linsvm", label: "Linear SVM", family: "Distance and Margin Models", task: "classification", purpose: "Calibrated linear margin model for high-dimensional spaces.", bestUse: "Sparse or broad standardized feature sets", interpretability: "Medium", scaling: "Required", categorical: "Encoded", probability: "Calibrated" },
  { key: "iso", label: "Isolation Forest", family: "Unsupervised Anomaly Detection", task: "classification", kind: "anomaly", purpose: "Fits without a target and isolates rare multivariate patterns.", bestUse: "Targetless anomaly screening and supplemental fraud evidence", interpretability: "Low", scaling: "Applied in pipeline", categorical: "Encoded", probability: "Anomaly score" },
  { key: "autoreg", label: "Local Outlier Factor", family: "Unsupervised Anomaly Detection", task: "classification", kind: "anomaly", purpose: "Fits without a target and compares local density with neighboring observations.", bestUse: "Local-pattern anomaly screening on bounded samples", interpretability: "Medium", scaling: "Required", categorical: "Encoded", probability: "Anomaly score" },
  { key: "oneclass_svm", label: "One-Class SVM", family: "Unsupervised Anomaly Detection", task: "classification", kind: "anomaly", purpose: "Fits a nonlinear boundary around normal observations without target labels.", bestUse: "Novelty detection on standardized moderate-size datasets", interpretability: "Low", scaling: "Required", categorical: "Encoded", probability: "Anomaly score" },
  { key: "elliptic", label: "Robust Covariance", family: "Unsupervised Anomaly Detection", task: "classification", kind: "anomaly", purpose: "Fits a robust covariance envelope without a target variable.", bestUse: "Low-dimensional, approximately elliptical financial populations", interpretability: "Medium", scaling: "Required", categorical: "Encoded", probability: "Anomaly score" },
  { key: "mlp", label: "Feedforward Neural Network (MLP)", family: "Neural Models", task: "classification", purpose: "Flexible nonlinear multilayer perceptron for sufficiently large tabular samples.", bestUse: "Black-box challenger with governance controls", interpretability: "Low", scaling: "Required", categorical: "Encoded", probability: "Native" },
  { key: "fnn", label: "Deep Feedforward Network", family: "Neural Models", task: "classification", purpose: "Deeper multilayer perceptron for nonlinear tabular interactions.", bestUse: "Large tabular samples after transparent and ensemble baselines", interpretability: "Low", scaling: "Required", categorical: "Encoded", probability: "Native" },
  { key: "tensorflow_dnn", label: "TensorFlow Deep Neural Network", family: "Neural Models", task: "classification", purpose: "TensorFlow-backed dense neural network for production-grade deep-learning experiments.", bestUse: "GPU-enabled research environments and large-scale benchmarks", interpretability: "Low", scaling: "Required", categorical: "Encoded", probability: "Native" },
  { key: "cnn", label: "Convolutional Neural Network (CNN)", family: "Neural Models", task: "classification", purpose: "Convolutional architecture for image, signal, or spatial feature tensors.", bestUse: "Computer vision, spatial grids, or engineered tensor inputs", interpretability: "Low", scaling: "Required", categorical: "Encoded", probability: "Native" },
  { key: "rnn_lstm", label: "Recurrent Neural Network (LSTM)", family: "Neural Models", task: "classification", purpose: "Sequential neural architecture for ordered events and temporal behavior.", bestUse: "Transaction sequences, behavioral streams, or time-ordered histories", interpretability: "Low", scaling: "Required", categorical: "Encoded", probability: "Native" },
  { key: "linreg", label: "Linear Regression", family: "Transparent Models", task: "regression", purpose: "Auditable continuous-outcome baseline with coefficient evidence.", bestUse: "Regulated regression and benchmark interpretation", interpretability: "High", scaling: "Applied in pipeline", categorical: "Encoded", probability: "Not applicable" },
  { key: "ridge_reg", label: "Ridge Regression", family: "Transparent Models", task: "regression", purpose: "L2-regularized linear model for correlated predictors and stable coefficients.", bestUse: "Regulated continuous outcomes with multicollinearity", interpretability: "High", scaling: "Required", categorical: "Encoded", probability: "Not applicable" },
  { key: "elastic_reg", label: "Elastic Net Regression", family: "Transparent Models", task: "regression", purpose: "Combined L1/L2 regularization for sparse, correlated feature sets.", bestUse: "Feature-constrained continuous-outcome models", interpretability: "High", scaling: "Required", categorical: "Encoded", probability: "Not applicable" },
  { key: "sgd_reg", label: "SGD Regressor", family: "Transparent Models", task: "regression", purpose: "Scalable iterative linear regression for high-volume datasets.", bestUse: "Fast large-population continuous-outcome benchmark", interpretability: "High", scaling: "Required", categorical: "Encoded", probability: "Not applicable" },
  { key: "dt_reg", label: "Decision Tree Regressor", family: "Transparent Models", task: "regression", purpose: "Reviewable nonlinear rules for continuous outcomes.", bestUse: "Transparent nonlinear segment effects", interpretability: "High", scaling: "Not required", categorical: "Encoded", probability: "Not applicable" },
  { key: "rf_reg", label: "Random Forest Regressor", family: "Tree and Ensemble Models", task: "regression", purpose: "Robust nonlinear benchmark for continuous targets.", bestUse: "Stable ensemble challenger", interpretability: "Medium", scaling: "Not required", categorical: "Encoded", probability: "Not applicable" },
  { key: "extra_trees_reg", label: "Extra Trees Regressor", family: "Tree and Ensemble Models", task: "regression", purpose: "Randomized tree ensemble for nonlinear continuous outcomes.", bestUse: "Fast interaction-rich regression challenger", interpretability: "Medium", scaling: "Not required", categorical: "Encoded", probability: "Not applicable" },
  { key: "histgb_reg", label: "Histogram Gradient Boosting Regressor", family: "Tree and Ensemble Models", task: "regression", purpose: "Efficient histogram boosting for nonlinear continuous outcomes.", bestUse: "Strong native tabular regression benchmark", interpretability: "Medium", scaling: "Applied in pipeline", categorical: "Encoded", probability: "Not applicable" },
  { key: "ebm_reg", label: "Explainable Boosting Regressor", family: "Transparent Models", task: "regression", purpose: "Interpretable additive boosting for nonlinear continuous-outcome relationships.", bestUse: "Shape-based explainable regression when the optional EBM library is installed", interpretability: "High", scaling: "Applied in pipeline", categorical: "Encoded", probability: "Not applicable" },
  { key: "xgb_reg", label: "XGBoost Regressor", family: "Tree and Ensemble Models", task: "regression", purpose: "Regularized boosted regression for tabular data.", bestUse: "Performance-focused regression challenger", interpretability: "Low", scaling: "Not required", categorical: "Encoded", probability: "Not applicable" },
  { key: "lgbm_reg", label: "LightGBM Regressor", family: "Tree and Ensemble Models", task: "regression", purpose: "Efficient boosted regression for larger populations.", bestUse: "Fast regression challenger search", interpretability: "Low", scaling: "Not required", categorical: "Encoded", probability: "Not applicable" },
  { key: "cat_reg", label: "CatBoost Regressor", family: "Tree and Ensemble Models", task: "regression", purpose: "Boosted regression for mixed tabular predictors.", bestUse: "Categorical-rich regression challenger", interpretability: "Low", scaling: "Not required", categorical: "Encoded", probability: "Not applicable" },
];

const MODEL_SUITE_PRESETS = [
  {
    key: "audit_core",
    title: "Audit-Ready Core",
    description: "Transparent, fast, governance-friendly baselines for regulated review.",
    models: {
      classification: ["logreg", "ridge_clf", "dtree", "sgd_log", "gnb", "bernoulli_nb"],
      regression: ["linreg", "ridge_reg", "elastic_reg", "sgd_reg", "dt_reg", "ebm_reg"],
    },
  },
  {
    key: "balanced_bench",
    title: "Balanced Challenger Bench",
    description: "A practical benchmark mixing explainable baselines with strong tabular challengers.",
    models: {
      classification: ["logreg", "ridge_clf", "dtree", "sgd_log", "gnb", "bernoulli_nb", "rf", "extra_trees", "xgb", "lgbm", "linsvm"],
      regression: ["linreg", "ridge_reg", "elastic_reg", "dt_reg", "rf_reg", "extra_trees_reg", "histgb_reg", "xgb_reg", "lgbm_reg"],
    },
  },
  {
    key: "research_bench",
    title: "Full Research Bench",
    description: "The full eligible library for model discovery and challenger documentation.",
    models: {
      classification: MODEL_DEFINITIONS.filter((model) => model.task === "classification").map((model) => model.key),
      regression: MODEL_DEFINITIONS.filter((model) => model.task === "regression").map((model) => model.key),
    },
  },
] as const;

const CANDIDATE_STRATEGIES: Array<{
  key: CandidateStrategy;
  title: string;
  description: string;
  interpretability: string;
  models: Record<ProblemType, string[]>;
}> = [
  {
    key: "transparent_baseline",
    title: "Transparent baseline",
    description: "Fast, auditable linear and compact-rule anchors.",
    interpretability: "Highest",
    models: {
      classification: ["logreg", "ridge_clf", "dtree"],
      regression: ["linreg", "ridge_reg", "dt_reg"],
    },
  },
  {
    key: "interpretable_challenger",
    title: "Interpretable challenger",
    description: "Adds explainable nonlinear and probabilistic challengers.",
    interpretability: "High",
    models: {
      classification: ["logreg", "dtree", "ebm", "gnb"],
      regression: ["linreg", "dt_reg", "ebm_reg", "elastic_reg"],
    },
  },
  {
    key: "nonlinear_benchmark",
    title: "Nonlinear benchmark",
    description: "Reviewable baseline plus robust tree ensembles.",
    interpretability: "Mixed",
    models: {
      classification: ["logreg", "dtree", "rf", "extra_trees", "histgb"],
      regression: ["linreg", "dt_reg", "rf_reg", "extra_trees_reg", "histgb_reg"],
    },
  },
  {
    key: "performance_challenger",
    title: "Performance challenger",
    description: "Strong tabular boosted models alongside an audit anchor.",
    interpretability: "Mixed to low",
    models: {
      classification: ["logreg", "ebm", "rf", "xgb", "lgbm", "cat"],
      regression: ["linreg", "ebm_reg", "rf_reg", "xgb_reg", "lgbm_reg", "cat_reg"],
    },
  },
  {
    key: "full_research_bench",
    title: "Full research bench",
    description: "Every eligible library candidate; highest workload.",
    interpretability: "Mixed",
    models: {
      classification: MODEL_DEFINITIONS.filter((model) => model.task === "classification").map((model) => model.key),
      regression: MODEL_DEFINITIONS.filter((model) => model.task === "regression").map((model) => model.key),
    },
  },
  {
    key: "custom_portfolio",
    title: "Custom portfolio",
    description: "Reviewer-curated candidates using portfolio filters.",
    interpretability: "Reviewer controlled",
    models: { classification: [], regression: [] },
  },
];

type RankedResult = {
  key: string;
  name: string;
  task?: ProblemType;
  auc?: number | null;
  pr_auc?: number | null;
  precision?: number | null;
  recall?: number | null;
  f1?: number | null;
  ks?: number | null;
  gini?: number | null;
  rmse?: number | null;
  mae?: number | null;
  mse?: number | null;
  r2?: number | null;
  adjusted_r2?: number | null;
  best_params?: Record<string, unknown> | null;
  search_runtime_ms?: number;
  calibration_applied?: boolean;
  calibration_method?: string | null;
  runtime_ms?: number;
  candidate_champion?: boolean;
  candidate_status?: string;
  kind?: "supervised" | "anomaly";
  champion_eligible?: boolean;
  target_usage?: string;
};

type ModelCompatibility = { compatible: boolean; reason: string };
type Preflight = {
  ok: boolean;
  ready: boolean;
  blocking_errors: string[];
  warnings: string[];
  project_id: string;
  dataset_id: string;
  dataset_version_id: string;
  dataset_version: string;
  target: string;
  event_value?: unknown;
  non_event_value?: unknown;
  problem_type: ProblemType;
  train_rows: number;
  test_rows: number;
  train_events?: number | null;
  test_events?: number | null;
  train_event_rate?: number | null;
  test_event_rate?: number | null;
  selected_features: string[];
  selected_original_features: string[];
  engineered_features: string[];
  missing_features: string[];
  feature_manifest_version: string;
  split_id: string;
  split_status: string;
  split_configuration: Record<string, any>;
  validation_design_id: string;
  validation_design_version: string;
  validation_design: Record<string, any>;
  cv_design: Record<string, any>;
  fold_architecture: Record<string, any>;
  evaluation_population_role?: string;
  test_reference?: Record<string, any> | null;
  oot_reference?: Record<string, any> | null;
  balancing_configuration: Record<string, any>;
  optional_library_status: Record<string, { available: boolean; reason: string; label: string }>;
  model_compatibility: Record<string, ModelCompatibility>;
  calibration_compatibility: Record<string, ModelCompatibility>;
  cross_validation_compatibility: {
    compatible: boolean;
    owned_by_validation_design?: boolean;
    method?: string;
    requested_folds: number;
    effective_folds: number;
    minimum_class_count?: number | null;
    read_only?: boolean;
  };
  estimated_memory_mb: number;
  recommended_parallelism: number;
  backend_status: string;
  worker_status: string;
  duration_ms: number;
};

type ModelExecution = {
  status: ModelState;
  state: ModelState;
  queued_at?: string;
  started_at?: string | null;
  completed_at?: string | null;
  runtime_ms?: number;
  current_stage?: string;
  message?: string;
  warning?: string | null;
  user_error?: string | null;
  technical_error?: string | null;
  traceback_reference?: string | null;
  best_parameters?: Record<string, unknown> | null;
  search_summary?: Record<string, unknown> | null;
  current_fold?: number | null;
  current_tuning_candidate?: number | null;
  fold_progress_available?: boolean;
  result?: RankedResult;
};

type TrainingJob = {
  ok?: boolean;
  job_id: string;
  project_id: string;
  dataset_id: string;
  dataset_version_id: string;
  overall_status: JobState;
  created_at: string;
  started_at?: string | null;
  completed_at?: string | null;
  requested_models: string[];
  completed_count: number;
  finished_count?: number;
  total_count: number;
  current_models: string[];
  queued_models?: string[];
  completed_models?: string[];
  per_model_status: Record<string, ModelExecution>;
  per_model_history?: Record<string, Array<{ state: ModelState; at: string; stage: string; message?: string }>>;
  partial_results?: RankedResult[];
  partial_ranked_results: RankedResult[];
  failed_models: Array<{ key: string; name: string; error: string; technical_error?: string; traceback_reference?: string }>;
  user_message?: string;
  message: string;
  developer_details?: Array<Record<string, unknown>>;
  runtime_ms: number;
  cancellation_requested: boolean;
  max_parallel_honored: number;
  input_feature_names?: string[];
  trained_feature_names: string[];
  engineered_feature_names?: string[];
  feature_manifest_version?: string;
  split_id?: string;
  validation_design_id?: string;
  validation_design_version?: string;
  estimated_fits?: number;
  dataset_version?: string;
  n_features: number;
  summary?: {
    ranked?: RankedResult[];
    trained_feature_names?: string[];
    runtime_ms?: number;
    project_id?: string;
    dataset_id?: string;
    dataset_version_id?: string;
  } | null;
};

type Availability = { ok: boolean; availability: Record<string, boolean>; labels: Record<string, string> };
type SplitStatus = {
  ok: boolean;
  project_id: string;
  dataset_id: string;
  dataset_version_id: string;
  status: "not_created" | "current" | "stale";
  split_id?: string;
  config?: Record<string, any>;
  validation_design_id?: string;
  validation_design_version?: string;
  validation_design?: Record<string, any>;
  cv_design?: {
    method?: string;
    fold_count?: number;
    repeats?: number;
    tuning_scope?: string;
    approved?: boolean;
  };
  balancing_policy?: Record<string, any>;
  selected_features?: string[];
  dataset_version?: string;
  target?: string;
  test_reference?: Record<string, any> | null;
  oot_reference?: Record<string, any> | null;
  evaluation_population_role?: string;
};

type ModelSelectionDecision = {
  decision_id: string;
  project_id: string;
  dataset_id: string;
  dataset_version_id: string;
  dataset_version?: string;
  training_job_id: string;
  champion_model: string;
  challenger_models: string[];
  status: "proposed" | "approved" | "rejected";
  primary_metric: string;
  rationale: string;
  metric_justification?: string;
  interpretability_justification?: string;
  calibration_considerations?: string;
  fairness_validation_prerequisites?: string;
  deployment_constraints?: string;
  reviewer_notes?: string;
  actor?: { display_name?: string };
  decided_at?: string;
};

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    credentials: "include",
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
  const payload = await response.json().catch(() => null);
  if (!response.ok || payload?.ok === false) throw new Error(payload?.detail ?? payload?.error ?? `ATLAS request failed with HTTP ${response.status}.`);
  return payload as T;
}

function readConfig(identity: CanonicalDatasetIdentity | null) {
  if (!identity) return {} as Record<string, any>;
  try {
    return JSON.parse(
      localStorage.getItem(
        canonicalDatasetStorageKey(TRAINING_CONFIG_KEY, identity),
      ) || "{}",
    ) as Record<string, any>;
  } catch {
    return {};
  }
}

function hasSavedSelectionForProblem(config: Record<string, any>, problemType: ProblemType) {
  const hasCurrentSelection = Array.isArray(config.selectedModels);
  const hasLegacySelection = !!config.selected_map && typeof config.selected_map === "object";
  return (hasCurrentSelection || hasLegacySelection) && (!config.problem_type || config.problem_type === problemType);
}

function buildInitialSelected(config: Record<string, any>, problemType: ProblemType) {
  const allowed = new Set(MODEL_DEFINITIONS.filter((model) => model.task === problemType).map((model) => model.key));
  if (hasSavedSelectionForProblem(config, problemType)) {
    const saved = Array.isArray(config.selectedModels)
      ? config.selectedModels.map(String)
      : Object.entries(config.selected_map as Record<string, unknown>).filter(([, selected]) => selected === true).map(([key]) => key);
    return [...new Set(saved)].filter((key) => allowed.has(key));
  }
  return problemType === "regression" ? ["linreg", "dt_reg", "rf_reg"] : ["logreg", "dtree", "rf"];
}

function readActiveJobId(identity: CanonicalDatasetIdentity | null) {
  if (!identity) return "";
  try {
    const value = JSON.parse(localStorage.getItem(ACTIVE_JOB_KEY) || "null");
    return (
      typeof value?.jobId === "string" &&
      value?.projectId === identity.project_id &&
      value?.datasetId === identity.dataset_id &&
      value?.datasetVersionId === identity.dataset_version_id
    )
      ? value.jobId
      : "";
  } catch {
    return "";
  }
}

function metricValue(row: RankedResult, metric: string) {
  const value = row[metric as keyof RankedResult];
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function formatMetric(value: number | null | undefined, digits = 4) {
  return typeof value === "number" && Number.isFinite(value) ? value.toFixed(digits) : "N/A";
}

function formatPercent(value: number | null | undefined) {
  return typeof value === "number" && Number.isFinite(value) ? `${(value * 100).toFixed(3)}%` : "N/A";
}

function cleanModelLabel(label: string | null | undefined) {
  if (!label) return "";
  return label
    .replace(/\s*\(k=7\)\s*/gi, "")
    .replace(/^Neural Net \(MLP\)$/i, "Feedforward Neural Network (MLP)")
    .trim();
}

function modelLabel(key: string, labels: Record<string, string>) {
  return cleanModelLabel(labels[key] ?? MODEL_DEFINITIONS.find((item) => item.key === key)?.label ?? key) || key;
}

export default function Step07ModelTraining() {
  const dataset = loadLocalDataset();
  const projectId = useWorkflowStore((state) => state.projectId);
  const projectName = useWorkflowStore((state) => state.projectName);
  const getNextStepPath = useWorkflowStore((state) => state.getNextStepPath);
  let datasetIdentity: CanonicalDatasetIdentity | null = null;
  let datasetIdentityError = "";
  try {
    datasetIdentity = requireLocalDatasetCanonicalIdentity(
      projectId,
      dataset,
      "Model Training dataset identity",
    );
  } catch (cause) {
    datasetIdentityError =
      cause instanceof Error
        ? cause.message
        : "Model Training requires an exact registered Dataset Library version.";
  }
  const persisted = readConfig(datasetIdentity);
  const [manifest, setManifest] = useState<FeatureManifest | null>(null);
  const [splitStatus, setSplitStatus] = useState<SplitStatus | null>(null);
  const [availability, setAvailability] = useState<Record<string, boolean>>({});
  const [labels, setLabels] = useState<Record<string, string>>({});
  const [problemType, setProblemType] = useState<ProblemType>(dataset?.problem_type ?? "classification");
  const [selectedModels, setSelectedModels] = useState<string[]>(() => buildInitialSelected(persisted, dataset?.problem_type ?? "classification"));
  const [kFolds, setKFolds] = useState(5);
  const [candidateStrategy, setCandidateStrategy] = useState<CandidateStrategy>(
    persisted.candidateStrategy ?? "transparent_baseline",
  );
  const [modelSearch, setModelSearch] = useState("");
  const [familyFilter, setFamilyFilter] = useState("all");
  const [interpretabilityFilter, setInterpretabilityFilter] = useState("all");
  const [selectedOnly, setSelectedOnly] = useState(false);
  const [recommendedOnly, setRecommendedOnly] = useState(false);
  const [compactPortfolio, setCompactPortfolio] = useState(true);
  const [maxParallel, setMaxParallel] = useState(Number(persisted.maxParallel ?? 2));
  const [calibrate, setCalibrate] = useState(Boolean(persisted.calibrate ?? false));
  const [gridSearch, setGridSearch] = useState(Boolean(persisted.gridSearch ?? false));
  const [gridSearchLevel, setGridSearchLevel] = useState<"quick" | "balanced" | "thorough">(persisted.gridSearchLevel ?? "quick");
  const [primaryMetric, setPrimaryMetric] = useState(persisted.primaryMetric ?? (dataset?.problem_type === "regression" ? "rmse" : "pr_auc"));
  const [preflight, setPreflight] = useState<Preflight | null>(null);
  const [preflightSignature, setPreflightSignature] = useState("");
  const [preflightLoading, setPreflightLoading] = useState(false);
  const [job, setJob] = useState<TrainingJob | null>(null);
  const [activeJobId, setActiveJobId] = useState(() =>
    readActiveJobId(datasetIdentity),
  );
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [sortMetric, setSortMetric] = useState(primaryMetric);
  const [requestUser, setRequestUser] = useState("");
  const [largeJobConfirmed, setLargeJobConfirmed] = useState(false);
  const [championModel, setChampionModel] = useState("");
  const [challengerModels, setChallengerModels] = useState<string[]>([]);
  const [selectionRationale, setSelectionRationale] = useState("");
  const [metricJustification, setMetricJustification] = useState("");
  const [interpretabilityJustification, setInterpretabilityJustification] =
    useState("");
  const [calibrationConsiderations, setCalibrationConsiderations] =
    useState("");
  const [fairnessPrerequisites, setFairnessPrerequisites] = useState("");
  const [deploymentConstraints, setDeploymentConstraints] = useState("");
  const [reviewerNotes, setReviewerNotes] = useState("");
  const [selectionDecision, setSelectionDecision] =
    useState<ModelSelectionDecision | null>(null);
  const [decisionSaving, setDecisionSaving] = useState(false);
  const finalizedJobs = useRef(new Set<string>());

  const availableDefinitions = useMemo(() => MODEL_DEFINITIONS.filter((model) => model.task === problemType), [problemType]);
  const selectedDefinitions = useMemo(() => availableDefinitions.filter((model) => selectedModels.includes(model.key)), [availableDefinitions, selectedModels]);
  const recommendedModelKeys = useMemo(
    () =>
      new Set(
        CANDIDATE_STRATEGIES.find((strategy) => strategy.key === candidateStrategy)
          ?.models[problemType] ?? [],
      ),
    [candidateStrategy, problemType],
  );
  const visibleDefinitions = useMemo(() => {
    const normalized = modelSearch.trim().toLowerCase();
    return availableDefinitions.filter((model) => {
      if (selectedOnly && !selectedModels.includes(model.key)) return false;
      if (recommendedOnly && !recommendedModelKeys.has(model.key)) return false;
      if (familyFilter !== "all" && model.family !== familyFilter) return false;
      if (
        interpretabilityFilter !== "all" &&
        model.interpretability !== interpretabilityFilter
      ) return false;
      if (
        normalized &&
        !`${model.label} ${model.family} ${model.purpose} ${model.bestUse}`
          .toLowerCase()
          .includes(normalized)
      ) return false;
      return true;
    });
  }, [
    availableDefinitions,
    familyFilter,
    interpretabilityFilter,
    modelSearch,
    recommendedModelKeys,
    recommendedOnly,
    selectedModels,
    selectedOnly,
  ]);
  const compatibleModelKeys = useMemo(() => {
    return new Set(
      availableDefinitions
        .filter((model) => {
          if (availability[model.key] === false) return false;
          const compatibility = preflight?.model_compatibility?.[model.key];
          if (compatibility && !compatibility.compatible) return false;
          return true;
        })
        .map((model) => model.key)
    );
  }, [availableDefinitions, availability, preflight?.model_compatibility]);
  const selectedFeatures = useMemo(() => (manifest?.features ?? []).filter((feature) => feature.selected && feature.eligibility_status === "eligible"), [manifest]);
  const engineeredFeatures = useMemo(() => selectedFeatures.filter((feature) => feature.origin !== "original"), [selectedFeatures]);
  const tuningCandidateCount = gridSearch
    ? { quick: 4, balanced: 8, thorough: 12 }[gridSearchLevel]
    : 1;
  const estimatedFits =
    selectedModels.length * Math.max(1, kFolds) * tuningCandidateCount +
    (calibrate && problemType === "classification"
      ? selectedModels.length * Math.max(1, kFolds)
      : 0);
  const largeJob = estimatedFits >= 160;
  const cvConfigured =
    Number(splitStatus?.cv_design?.fold_count ?? 0) >= 2 &&
    splitStatus?.cv_design?.method !== "none";

  const requestPayload = useMemo(() => ({
    models: selectedModels,
    k_folds: kFolds,
    max_parallel: maxParallel,
    calibrate: problemType === "classification" && calibrate,
    use_pca: false,
    grid_search: gridSearch,
    grid_search_level: gridSearchLevel,
    model_params:
      splitStatus?.balancing_policy?.class_weight_policy === "balanced"
        ? Object.fromEntries(
            selectedModels.map((key) => [key, { class_weight: "balanced" }]),
          )
        : {},
    project_id: projectId,
    dataset_id: datasetIdentity?.dataset_id ?? "",
    dataset_version_id: datasetIdentity?.dataset_version_id ?? "",
    dataset_version: datasetIdentity?.dataset_version_id ?? "",
    target: dataset?.target ?? "",
    problem_type: problemType,
    event_value: dataset?.event_value,
    non_event_value: dataset?.non_event_value,
    feature_manifest_version: manifest?.manifest_hash ?? "",
    split_id: splitStatus?.split_id ?? "",
    validation_design_id: splitStatus?.validation_design_id ?? "",
    validation_design_version: splitStatus?.validation_design_version ?? "",
    selected_original_features: selectedFeatures.filter((feature) => feature.origin === "original").map((feature) => feature.feature_name),
    selected_engineered_features: engineeredFeatures.map((feature) => feature.feature_name),
    preprocessing_pipeline: manifest?.pipeline_steps ?? [],
    random_seed: Number(splitStatus?.config?.random_seed ?? 42),
    primary_metric: primaryMetric,
    candidate_strategy: candidateStrategy,
    large_job_confirmed: largeJobConfirmed,
    user: requestUser,
    requested_at: new Date().toISOString(),
  }), [calibrate, candidateStrategy, dataset?.event_value, dataset?.non_event_value, dataset?.target, datasetIdentity?.dataset_id, datasetIdentity?.dataset_version_id, engineeredFeatures, gridSearch, gridSearchLevel, kFolds, largeJobConfirmed, manifest?.manifest_hash, manifest?.pipeline_steps, maxParallel, primaryMetric, problemType, projectId, requestUser, selectedFeatures, selectedModels, splitStatus?.balancing_policy?.class_weight_policy, splitStatus?.config?.random_seed, splitStatus?.split_id, splitStatus?.validation_design_id, splitStatus?.validation_design_version]);
  const currentSignature = useMemo(() => JSON.stringify({ ...requestPayload, requested_at: "" }), [requestPayload]);
  const preflightCurrent = !!preflight && preflightSignature === currentSignature;

  useEffect(() => {
    if (!datasetIdentity) return;
    const selected_map = Object.fromEntries(MODEL_DEFINITIONS.map((model) => [model.key, selectedModels.includes(model.key)]));
    localStorage.setItem(
      canonicalDatasetStorageKey(TRAINING_CONFIG_KEY, datasetIdentity),
      JSON.stringify({ problem_type: problemType, candidateStrategy, selectedModels, selected_models: selectedModels, selected_map, maxParallel, calibrate, gridSearch, gridSearchLevel, primaryMetric }),
    );
  }, [calibrate, candidateStrategy, gridSearch, gridSearchLevel, maxParallel, primaryMetric, problemType, selectedModels, datasetIdentity?.dataset_id, datasetIdentity?.dataset_version_id]);

  useEffect(() => {
    setLargeJobConfirmed(false);
  }, [calibrate, gridSearch, gridSearchLevel, kFolds, selectedModels]);

  useEffect(() => {
    let active = true;
    if (!datasetIdentity) {
      setError(datasetIdentityError);
      setLoading(false);
      setActiveJobId("");
      return () => {
        active = false;
      };
    }
    const activeIdentity = datasetIdentity;
    const splitStatusQuery = new URLSearchParams({
      project_id: projectId,
      expected_dataset_id: activeIdentity.dataset_id,
      expected_dataset_version_id: activeIdentity.dataset_version_id,
    });
    const trainingArtifactQuery = new URLSearchParams({
      project_id: projectId,
      dataset_id: activeIdentity.dataset_id,
      dataset_version_id: activeIdentity.dataset_version_id,
    });
    const decisionQuery = new URLSearchParams({
      project_id: projectId,
      expected_dataset_id: activeIdentity.dataset_id,
      expected_dataset_version_id: activeIdentity.dataset_version_id,
    });
    void me().then((response) => {
      if (active) setRequestUser(response.user.email || response.user.displayName || response.user.userId);
    }).catch(() => undefined);
    Promise.all([
      getFeatureManifest(activeIdentity),
      requestJson<SplitStatus>(
        `/balancing_split/status?${splitStatusQuery.toString()}`,
      ),
      requestJson<Availability>(`/models/availability?project_id=${encodeURIComponent(projectId)}`),
      requestJson<{ ok: boolean; summary?: TrainingJob["summary"] }>(
        `/train/last?${trainingArtifactQuery.toString()}`,
      ).catch(() => ({ ok: true, summary: null })),
      requestJson<{
        ok: boolean;
        project_id: string;
        dataset_id: string;
        dataset_version_id: string;
        decision?: ModelSelectionDecision | null;
      }>(`/model/train/decision?${decisionQuery.toString()}`).catch(() => ({
        ok: true,
        project_id: activeIdentity.project_id,
        dataset_id: activeIdentity.dataset_id,
        dataset_version_id: activeIdentity.dataset_version_id,
        decision: null,
      })),
    ]).then(([nextManifest, nextSplit, modelAvailability, last, decisionResponse]) => {
      if (!active) return;
      assertExactDatasetIdentity(
        activeIdentity,
        nextSplit,
        "Model Training Validation Design response",
      );
      setManifest(nextManifest);
      setSplitStatus(nextSplit);
      const inheritedFolds = Number(nextSplit.cv_design?.fold_count ?? 0);
      setKFolds(inheritedFolds >= 2 ? inheritedFolds : 2);
      if (
        inheritedFolds < 2 ||
        !nextSplit.cv_design?.method ||
        nextSplit.cv_design.method === "none"
      ) setGridSearch(false);
      setAvailability(modelAvailability.availability ?? {});
      setLabels(modelAvailability.labels ?? {});
      assertExactDatasetIdentity(
        activeIdentity,
        decisionResponse,
        "Model-selection decision response",
      );
      if (decisionResponse.decision) {
        assertExactDatasetIdentity(
          activeIdentity,
          decisionResponse.decision,
          "Saved model-selection decision",
        );
        setSelectionDecision(decisionResponse.decision);
        setChampionModel(decisionResponse.decision.champion_model);
        setChallengerModels(decisionResponse.decision.challenger_models ?? []);
        setSelectionRationale(decisionResponse.decision.rationale ?? "");
        setMetricJustification(decisionResponse.decision.metric_justification ?? "");
        setInterpretabilityJustification(decisionResponse.decision.interpretability_justification ?? "");
        setCalibrationConsiderations(decisionResponse.decision.calibration_considerations ?? "");
        setFairnessPrerequisites(decisionResponse.decision.fairness_validation_prerequisites ?? "");
        setDeploymentConstraints(decisionResponse.decision.deployment_constraints ?? "");
        setReviewerNotes(decisionResponse.decision.reviewer_notes ?? "");
      }
      const lastSummaryCurrent =
        !!last.summary?.ranked?.length &&
        (() => {
          try {
            assertExactDatasetIdentity(
              activeIdentity,
              last.summary ?? {},
              "Restored training summary",
            );
            return true;
          } catch {
            return false;
          }
        })();
      if (lastSummaryCurrent && last.summary?.ranked?.length) {
        setJob((current) => current ?? ({
          job_id: "last-completed-run",
          project_id: activeIdentity.project_id,
          dataset_id: activeIdentity.dataset_id,
          dataset_version_id: activeIdentity.dataset_version_id,
          overall_status: "complete", created_at: "", requested_models: [], completed_count: last.summary!.ranked!.length, total_count: last.summary!.ranked!.length, current_models: [], per_model_status: {}, partial_ranked_results: last.summary!.ranked!, failed_models: [], message: "Last completed training run", runtime_ms: 0, cancellation_requested: false, max_parallel_honored: 1, trained_feature_names: [], n_features: nextManifest.features.filter((row) => row.selected).length, summary: last.summary,
        }));
      }
      if (dataset?.problem_type) setProblemType(dataset.problem_type);
    }).catch((cause) => active && setError(cause instanceof Error ? cause.message : "Model Training could not load its governed contract."))
      .finally(() => active && setLoading(false));
    if (!activeJobId) {
      requestJson<{ ok: boolean; jobs: TrainingJob[] }>(`/model/train/jobs/active?project_id=${encodeURIComponent(projectId)}`).then((response) => {
        const latest = response.jobs?.find((candidate) => {
          try {
            assertExactDatasetIdentity(
              activeIdentity,
              candidate,
              "Active training job",
            );
            return true;
          } catch {
            return false;
          }
        });
        if (active && latest) {
          setActiveJobId(latest.job_id);
          setJob(latest);
          localStorage.setItem(
            ACTIVE_JOB_KEY,
            JSON.stringify({
              jobId: latest.job_id,
              projectId,
              datasetId: activeIdentity.dataset_id,
              datasetVersionId: activeIdentity.dataset_version_id,
            }),
          );
        }
      }).catch(() => undefined);
    }
    return () => { active = false; };
  }, [
    activeJobId,
    dataset?.problem_type,
    datasetIdentity?.dataset_id,
    datasetIdentity?.dataset_version_id,
    projectId,
  ]);

  async function runPreflight() {
    if (!datasetIdentity) {
      setError(datasetIdentityError);
      throw new Error(datasetIdentityError);
    }
    setPreflightLoading(true);
    setError("");
    try {
      const result = await requestJson<Preflight>("/model/train/preflight", { method: "POST", body: JSON.stringify(requestPayload) });
      assertExactDatasetIdentity(
        datasetIdentity,
        result,
        "Model Training preflight response",
      );
      setPreflight(result);
      setPreflightSignature(currentSignature);
      if (result.recommended_parallelism < maxParallel) setMaxParallel(result.recommended_parallelism);
      setMessage(result.ready ? "Training preflight passed. The selected models are ready for governed execution." : "Training preflight found blocking issues.");
      return result;
    } catch (cause) {
      const text = cause instanceof Error ? cause.message : "Training preflight failed.";
      setError(text);
      throw new Error(text);
    } finally {
      setPreflightLoading(false);
    }
  }

  useEffect(() => {
    if (!manifest || !splitStatus || !selectedModels.length || activeJobId) return;
    void runPreflight().catch(() => undefined);
    // The signature already captures all training inputs.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [manifest?.manifest_hash, splitStatus?.split_id, splitStatus?.validation_design_version]);

  useEffect(() => {
    if (!activeJobId) return;
    let cancelled = false;
    let timeout = 0;
    async function poll() {
      try {
        const current = await requestJson<TrainingJob>(`/model/train/jobs/${encodeURIComponent(activeJobId)}?project_id=${encodeURIComponent(projectId)}`);
        if (cancelled) return;
        if (!datasetIdentity) {
          throw new Error(datasetIdentityError);
        }
        assertExactDatasetIdentity(
          datasetIdentity,
          current,
          "Polled training job",
        );
        setJob(current);
        setError("");
        if (["complete", "failed", "cancelled", "interrupted"].includes(current.overall_status)) {
          localStorage.removeItem(ACTIVE_JOB_KEY);
          setActiveJobId("");
          if (current.overall_status === "complete" && current.partial_ranked_results.length && !finalizedJobs.current.has(current.job_id)) {
            finalizedJobs.current.add(current.job_id);
            const trackingRows = current.partial_ranked_results.map((row) => ({
              ...row,
              task: row.task,
              auc: row.auc ?? undefined,
              pr_auc: row.pr_auc ?? undefined,
              f1: row.f1 ?? undefined,
              rmse: row.rmse ?? undefined,
              mae: row.mae ?? undefined,
              mse: row.mse ?? undefined,
              r2: row.r2 ?? undefined,
              adjusted_r2: row.adjusted_r2 ?? undefined,
            }));
            void recordTrainingExperiments({
              apiBase: API_BASE,
              datasetIdentity,
              trainingJobId: current.job_id,
              ranked: trackingRows,
              selectedModelKeys: current.requested_models,
              trainingSettings: requestPayload,
              runtimeMs: current.runtime_ms,
              calibrated: calibrate,
            }).catch((cause) => {
              setError(
                `Training completed, but experiment evidence persistence failed: ${
                  cause instanceof Error ? cause.message : "Unknown persistence failure."
                }`,
              );
            });
          }
          return;
        }
        timeout = window.setTimeout(poll, 750);
      } catch (cause) {
        if (cancelled) return;
        setError(`Connection to training job ${activeJobId} was lost. ${cause instanceof Error ? cause.message : "Retry required."}`);
        setJob((current) => current ? { ...current, overall_status: "interrupted", message: "Connection lost. Retry required." } : current);
        localStorage.removeItem(ACTIVE_JOB_KEY);
        setActiveJobId("");
      }
    }
    void poll();
    return () => { cancelled = true; window.clearTimeout(timeout); };
  }, [activeJobId, calibrate, projectId, requestPayload]);

  async function startTraining(
    overrideModels?: string[],
    retryParentJobId = "",
  ) {
    if (!datasetIdentity) {
      setError(datasetIdentityError);
      return;
    }
    const launchModels = overrideModels?.length
      ? [...new Set(overrideModels)]
      : selectedModels;
    if (!launchModels.length) {
      setError("Select at least one model before training.");
      return;
    }
    setError("");
    try {
      const launchPayload = {
        ...requestPayload,
        models: launchModels,
        retry_parent_job_id: retryParentJobId,
      };
      const check =
        !overrideModels && preflightCurrent
          ? preflight
          : await requestJson<Preflight>("/model/train/preflight", {
              method: "POST",
              body: JSON.stringify(launchPayload),
            });
      if (check) {
        assertExactDatasetIdentity(
          datasetIdentity,
          check,
          "Model Training preflight response",
        );
      }
      if (!check?.ready) throw new Error("Resolve every blocking preflight issue before creating a training job.");
      const created = await requestJson<TrainingJob>("/model/train/jobs", { method: "POST", body: JSON.stringify(launchPayload) });
      assertExactDatasetIdentity(
        datasetIdentity,
        created,
        "Created training job",
      );
      const queued: TrainingJob = created.per_model_status ? created : {
        ...created,
        overall_status: "queued",
        completed_count: 0,
        total_count: launchModels.length,
        current_models: [],
        requested_models: launchModels,
        per_model_status: Object.fromEntries(launchModels.map((key) => [key, { status: "queued", state: "queued", current_stage: "Waiting for local worker" }])),
        partial_ranked_results: [],
        failed_models: [],
        message: "Training job queued.",
        runtime_ms: 0,
        cancellation_requested: false,
        max_parallel_honored: check.recommended_parallelism,
        trained_feature_names: check.selected_features,
        n_features: check.selected_features.length,
      };
      setJob(queued);
      setActiveJobId(created.job_id);
      localStorage.setItem(
        ACTIVE_JOB_KEY,
        JSON.stringify({
          jobId: created.job_id,
          projectId,
          datasetId: datasetIdentity.dataset_id,
          datasetVersionId: datasetIdentity.dataset_version_id,
        }),
      );
      logDecision({ workflowStep: "Model Training", actionType: "workflow_setting_changed", subject: retryParentJobId ? "Failed model retry job created" : "Training job created", previousValue: retryParentJobId || null, newValue: { jobId: created.job_id, models: launchModels, splitId: check.split_id, validationDesignVersion: check.validation_design_version, featureManifestVersion: check.feature_manifest_version }, systemRecommendation: "Train only after the governed preflight and Validation Design binding pass.", followStatus: "followed" });
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "ATLAS could not create the training job.");
    }
  }

  async function retryFailedModels() {
    const failedKeys = (job?.failed_models ?? []).map((failure) => failure.key);
    if (!failedKeys.length || !job) return;
    setSelectedModels(failedKeys);
    setCandidateStrategy("custom_portfolio");
    setPreflight(null);
    await startTraining(failedKeys, job.job_id);
  }

  async function cancelTraining() {
    if (!activeJobId) return;
    try {
      const current = await requestJson<TrainingJob>(`/model/train/jobs/${encodeURIComponent(activeJobId)}/cancel?project_id=${encodeURIComponent(projectId)}`, { method: "POST" });
      if (!datasetIdentity) throw new Error(datasetIdentityError);
      assertExactDatasetIdentity(
        datasetIdentity,
        current,
        "Cancelled training job response",
      );
      setJob(current);
      if (["complete", "failed", "cancelled", "interrupted"].includes(current.overall_status)) {
        localStorage.removeItem(ACTIVE_JOB_KEY);
        setActiveJobId("");
      }
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "ATLAS could not cancel the training job.");
    }
  }

  async function cancelQueuedModels() {
    if (!activeJobId) return;
    try {
      const current = await requestJson<TrainingJob>(
        `/model/train/jobs/${encodeURIComponent(activeJobId)}/cancel-queued?project_id=${encodeURIComponent(projectId)}`,
        { method: "POST" },
      );
      if (!datasetIdentity) throw new Error(datasetIdentityError);
      assertExactDatasetIdentity(
        datasetIdentity,
        current,
        "Cancel-queued training job response",
      );
      setJob(current);
      setMessage(current.user_message ?? current.message);
    } catch (cause) {
      setError(
        cause instanceof Error
          ? cause.message
          : "ATLAS could not cancel queued models.",
      );
    }
  }

  async function saveModelSelectionDecision(
    status: "proposed" | "approved",
  ) {
    if (!job || job.overall_status !== "complete") {
      setError("Complete the governed training job before recording a model decision.");
      return;
    }
    if (!datasetIdentity) {
      setError(datasetIdentityError);
      return;
    }
    const activeIdentity = datasetIdentity;
    if (!championModel) {
      setError("Select one champion candidate.");
      return;
    }
    if (selectionRationale.trim().length < 10) {
      setError("Record a substantive champion/challenger rationale before saving.");
      return;
    }
    setDecisionSaving(true);
    setError("");
    try {
      const response = await requestJson<{
        ok: boolean;
        decision: ModelSelectionDecision;
      }>("/model/train/decision", {
        method: "POST",
        body: JSON.stringify({
          project_id: projectId,
          dataset_id: activeIdentity.dataset_id,
          dataset_version_id: activeIdentity.dataset_version_id,
          dataset_version: activeIdentity.dataset_version_id,
          training_job_id: job.job_id,
          validation_design_id: splitStatus?.validation_design_id ?? "",
          validation_design_version:
            splitStatus?.validation_design_version ?? "",
          champion_model: championModel,
          challenger_models: challengerModels,
          status,
          primary_metric: primaryMetric,
          rationale: selectionRationale.trim(),
          metric_justification: metricJustification.trim(),
          interpretability_justification:
            interpretabilityJustification.trim(),
          calibration_considerations: calibrationConsiderations.trim(),
          fairness_validation_prerequisites: fairnessPrerequisites.trim(),
          deployment_constraints: deploymentConstraints.trim(),
          reviewer_notes: reviewerNotes.trim(),
        }),
      });
      assertExactDatasetIdentity(
        activeIdentity,
        response.decision,
        "Saved model-selection decision",
      );
      setSelectionDecision(response.decision);
      setMessage(
        `${status === "approved" ? "Approved" : "Proposed"} champion/challenger decision ${response.decision.decision_id} was bound to job ${job.job_id}.`,
      );
      logDecision({
        workflowStep: "Model Training",
        actionType: "champion_model_selected",
        subject: modelLabel(championModel, labels),
        previousValue: selectionDecision?.champion_model ?? "none",
        newValue: {
          champion: championModel,
          challengers: challengerModels,
          status,
        },
        systemRecommendation:
          "Treat leaderboard rank as decision support, never automatic champion approval.",
        followStatus: "followed",
        userReason: selectionRationale.trim(),
      });
    } catch (cause) {
      setError(
        cause instanceof Error
          ? cause.message
          : "The governed model decision could not be saved.",
      );
    } finally {
      setDecisionSaving(false);
    }
  }

  function toggleModel(key: string) {
    setCandidateStrategy("custom_portfolio");
    setSelectedModels((current) => current.includes(key) ? current.filter((item) => item !== key) : [...current, key]);
    setPreflight(null);
    logDecision({ workflowStep: "Model Training", actionType: "model_selected", subject: modelLabel(key, labels), previousValue: selectedModels, newValue: selectedModels.includes(key) ? selectedModels.filter((item) => item !== key) : [...selectedModels, key] });
  }

  function applyModelSuite(keys: readonly string[]) {
    const allowed = new Set(availableDefinitions.map((model) => model.key));
    const next = keys.filter((key) => allowed.has(key) && compatibleModelKeys.has(key));
    setSelectedModels([...new Set(next)]);
    setPreflight(null);
  }

  function applyCandidateStrategy(strategy: CandidateStrategy) {
    setCandidateStrategy(strategy);
    if (strategy === "custom_portfolio") {
      setPreflight(null);
      return;
    }
    const definition = CANDIDATE_STRATEGIES.find((item) => item.key === strategy);
    const allowed = new Set(availableDefinitions.map((model) => model.key));
    const next = (definition?.models[problemType] ?? []).filter(
      (key) => allowed.has(key) && compatibleModelKeys.has(key),
    );
    setSelectedModels([...new Set(next)]);
    setPreflight(null);
  }

  const results = useMemo(() => {
    const rows = [...(job?.partial_ranked_results ?? job?.summary?.ranked ?? [])];
    const ascending = ["rmse", "mae", "mse"].includes(sortMetric);
    return rows.sort((left, right) => {
      const a = metricValue(left, sortMetric);
      const b = metricValue(right, sortMetric);
      if (a === null) return 1;
      if (b === null) return -1;
      return ascending ? a - b : b - a;
    });
  }, [job?.partial_ranked_results, job?.summary?.ranked, sortMetric]);
  const championEligibleResults = results.filter((row) => row.champion_eligible !== false && row.kind !== "anomaly");
  useEffect(() => {
    const eligibleKeys = championEligibleResults.map((row) => row.key);
    if (!eligibleKeys.length) return;
    const resolvedChampion =
      championModel && eligibleKeys.includes(championModel)
        ? championModel
        : eligibleKeys[0];
    if (resolvedChampion !== championModel) setChampionModel(resolvedChampion);
    setChallengerModels((current) => {
      const valid = current.filter(
        (key) => eligibleKeys.includes(key) && key !== resolvedChampion,
      );
      if (valid.length) return valid;
      return eligibleKeys
        .filter((key) => key !== resolvedChampion)
        .slice(0, 2);
    });
  }, [
    championEligibleResults.map((row) => row.key).join("|"),
    championModel,
  ]);
  const finishedCount = job?.finished_count ?? Object.values(job?.per_model_status ?? {}).filter((state) => ["complete", "failed", "cancelled", "interrupted"].includes(state.status)).length;
  const progress = job?.total_count ? Math.round((finishedCount / job.total_count) * 100) : 0;
  const jobActive = !!job && ["queued", "preparing", "running"].includes(job.overall_status);
  const readiness = preflightCurrent && preflight?.ready;
  const trainActionBlocked =
    jobActive ||
    preflightLoading ||
    !datasetIdentity ||
    !selectedModels.length ||
    !manifest ||
    !splitStatus ||
    splitStatus.status !== "current" ||
    loading ||
    (largeJob && !largeJobConfirmed);
  const trainActionLabel = jobActive
    ? "Training in progress"
    : preflightLoading
      ? "Validating selection"
      : readiness
        ? "Train Selected Models"
        : "Validate & Train Selected Models";

  const heroMetrics: AtlasWorkflowMetric[] = [
    { label: "Project", value: projectName },
    { label: "Target", value: dataset?.target ?? "Not confirmed", tone: dataset?.target ? "neutral" : "warning" },
    { label: "Problem Type", value: problemType },
    { label: "Governed Features", value: selectedFeatures.length.toLocaleString() },
    { label: "Engineered", value: engineeredFeatures.length.toLocaleString(), tone: engineeredFeatures.length ? "info" : "neutral" },
    { label: "Validation", value: splitStatus?.status === "current" ? splitStatus.validation_design_version ?? "Current design" : "Action required", tone: splitStatus?.status === "current" ? "success" : "warning" },
    { label: "Selected Models", value: selectedModels.length.toLocaleString() },
    { label: "Training Job", value: job?.overall_status ?? "Not started", tone: job?.overall_status === "complete" ? "success" : job?.overall_status === "failed" ? "danger" : jobActive ? "info" : "neutral" },
  ];

  async function completeStep() {
    if (!datasetIdentity) {
      setError(datasetIdentityError);
      return false;
    }
    if (
      !championEligibleResults.length ||
      job?.overall_status !== "complete" ||
      selectionDecision?.training_job_id !== job.job_id
    ) return false;
    await createEvidence({
      ...buildCanonicalEvidenceEnvelope(datasetIdentity, {
        manifestVersion: preflight?.feature_manifest_version,
        splitId: preflight?.split_id,
        validationDesignId: preflight?.validation_design_id,
        validationDesignVersion: preflight?.validation_design_version,
        jobId: job.job_id,
        modelDecisionId: selectionDecision.decision_id,
      }),
      projectName,
      evidenceType: "model_training",
      title: "Governed Model Training Run",
      summary: `${results.length} model(s) completed under job ${job.job_id}. ${modelLabel(selectionDecision.champion_model, labels)} is proposed—not approved—as champion with ${selectionDecision.challenger_models.length} governed challenger(s).`,
      sourcePage: "Model Training",
      sourceRoute: "/step07",
      modelIds: championEligibleResults.map((row) => row.key),
      documentIds: [],
      notebookIds: [],
      supportsSections: ["Candidate Models", "Model Selection Rationale", "Development Test and OOT Data"],
      tags: ["predictive_modeling", "training_job", "candidate_models"],
      status: job.failed_models.length ? "needs_review" : "ready",
      importance: "high",
      payload: { job, configuration: requestPayload, modelDecision: selectionDecision },
    });
    return true;
  }

  if (loading) {
    return <StepShell title="Step 7: Model Training" subtitle="Train governed transparent and challenger models." variant="modeling" heroMetrics={heroMetrics} nextDisabled><div className="atlas-workflow-section flex min-h-64 items-center justify-center"><LoaderCircle size={32} className="animate-spin text-blue-500" /></div></StepShell>;
  }

  return (
    <StepShell
      title=""
      hideHeader
      variant="modeling"
      eyebrow="Predictive Modeling Workflow"
      heroMetrics={heroMetrics}
      nextPath={getNextStepPath("step07")}
      nextDisabled={
        !datasetIdentity ||
        job?.overall_status !== "complete" ||
        !championEligibleResults.length ||
        selectionDecision?.training_job_id !== job?.job_id}
      nextDisabledReason={
        job?.overall_status !== "complete" || !championEligibleResults.length
          ? "Complete at least one supervised, champion-eligible model before continuing to Evaluation."
          : "Record a governed champion/challenger proposal before continuing."
      }
      nextLabel="Confirm Model Training and Continue"
      nextStatusLine={selectionDecision?.training_job_id === job?.job_id ? "Training evidence, the candidate leaderboard, and the proposed decision are ready for downstream Evaluation. No champion is approved automatically." : "A governed champion/challenger proposal is required. Final approval remains in downstream Evaluation / Validation."}
      onNext={completeStep}
    >
      <div className="space-y-4">
        {error ? <AtlasAttentionPanel title="Model Training requires attention" tone="danger">{error}</AtlasAttentionPanel> : null}
        {message ? <div className="rounded-lg border border-blue-200 bg-blue-50 px-4 py-3 text-sm text-blue-950">{message}</div> : null}

        <TrainingMissionControl
          projectName={projectName}
          target={dataset?.target ?? ""}
          problemType={problemType}
          trainRows={preflight?.train_rows}
          validationRows={preflight?.test_rows}
          testAvailable={!!splitStatus?.test_reference}
          ootAvailable={!!splitStatus?.oot_reference}
          featureCount={selectedFeatures.length}
          engineeredCount={engineeredFeatures.length}
          cvLabel={validationDesignLabel(splitStatus)}
          primaryMetric={primaryMetric}
          selectedModels={selectedModels.length}
          jobState={job?.overall_status ?? "not started"}
          readiness={preflightCurrent ? !!preflight?.ready : splitStatus?.status === "current"}
          estimatedFits={estimatedFits}
          estimatedMemory={preflight?.estimated_memory_mb}
          blockers={preflight?.blocking_errors.length ?? 0}
          warnings={preflight?.warnings.length ?? 0}
        />

        <AtlasWorkflowSection
          eyebrow="Read-only governed handoff"
          title="Locked Inputs"
          description="Model Training consumes these approved contracts exactly as handed off. Edit them only on their source workflow page; any change invalidates preflight and downstream documentation."
          tone="neutral"
          action={<span className="inline-flex items-center gap-1 text-xs font-semibold text-emerald-700"><LockKeyhole size={14} /> Contract locked</span>}
        >
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4" data-testid="locked-training-inputs">
            <LockedInputCard title="Feature manifest" value={manifest?.manifest_hash ?? "Unavailable"} detail={`${selectedFeatures.length} selected · ${engineeredFeatures.length} engineered`} href="/step05" />
            <LockedInputCard title="Target contract" value={dataset?.target ?? "Unavailable"} detail={`${problemType} · target/source exclusion enforced`} href="/step01" />
            <LockedInputCard title="Validation Design" value={splitStatus?.validation_design_version ?? "Unavailable"} detail={validationDesignLabel(splitStatus)} href="/step06" />
            <LockedInputCard title="Balancing policy" value={String(splitStatus?.balancing_policy?.method ?? "none").replace(/_/g, " ")} detail={`${String(splitStatus?.balancing_policy?.scope ?? "training_population_only").replace(/_/g, " ")} · class weights ${String(splitStatus?.balancing_policy?.class_weight_policy ?? "none")}`} href="/step06" />
            <LockedInputCard title="Preprocessing pipeline" value={`${manifest?.pipeline_steps.length ?? 0} learned step(s)`} detail={(manifest?.pipeline_steps.map((step) => String(step.config?.method ?? step.transformation_type)).join(" · ") || "No learned transformations")} href="/step05" />
            <LockedInputCard title="Dataset version" value={datasetIdentity?.dataset_version_id ?? "Unavailable"} detail={datasetIdentity?.dataset_id ?? "Return to Data Acquisition"} href="/step01" />
            <LockedInputCard title="Excluded fields" value={`${(manifest?.predictor_authorization?.target_source_excluded ?? []).length + 1} protected`} detail={[dataset?.target, ...(manifest?.predictor_authorization?.target_source_excluded ?? [])].filter(Boolean).join(" · ")} href="/step05" />
            <LockedInputCard title="CV configuration" value={`${splitStatus?.cv_design?.method?.replace(/_/g, " ") ?? "none"} · ${splitStatus?.cv_design?.fold_count ?? 0} folds`} detail="Read-only; owned by Validation Design" href="/step06" testId="validation-contract-readonly" />
          </div>
        </AtlasWorkflowSection>

        <AtlasWorkflowSection
          eyebrow="Governed execution gate"
          title="Training Readiness"
          description="ATLAS validates the full split, exact feature contract, target classes, runtime dependencies, calibration, and cross-validation before a job can be created."
          tone={preflightCurrent ? preflight?.ready ? "success" : "warning" : "info"}
          action={<div className="flex items-center gap-2"><AtlasDataScopeBadge scope="full_dataset" rows={preflight?.train_rows && preflight?.test_rows ? preflight.train_rows + preflight.test_rows : dataset?.registered_row_count} /><button type="button" className="atlas-secondary-button" disabled={preflightLoading || jobActive || !selectedModels.length} onClick={() => void runPreflight()}>{preflightLoading ? <LoaderCircle size={15} className="animate-spin" /> : <RefreshCw size={15} />} Run Preflight</button></div>}
        >
          <AtlasStatusStrip items={[
            { label: "Dataset", state: preflight?.dataset_version_id ? "complete" : "blocked", detail: preflight?.dataset_version_id ?? "Unavailable" },
            { label: "Target", state: preflight?.target ? "complete" : "blocked", detail: preflight?.target ?? "Missing" },
            { label: "Feature contract", state: preflight?.missing_features?.length ? "blocked" : preflight?.selected_features?.length ? "complete" : "pending", detail: preflight ? `${preflight.selected_features.length} exact predictors` : "Not checked" },
            { label: "Validation split", state: preflight?.split_status === "current" ? "complete" : "blocked", detail: preflight?.split_id ?? "Not current" },
            { label: "Backend", state: preflight?.backend_status === "ready" ? "complete" : "blocked", detail: preflight?.backend_status ?? "Not checked" },
            { label: "Workers", state: preflight?.worker_status === "ready" ? "complete" : "pending", detail: preflight ? `${preflight.recommended_parallelism} recommended` : "Not checked" },
          ]} />
          {preflight ? <div className="mt-4 grid gap-2 sm:grid-cols-2 xl:grid-cols-6">
            <Metric label="Train rows" value={preflight.train_rows.toLocaleString()} />
            <Metric label="Holdout rows" value={preflight.test_rows.toLocaleString()} />
            <Metric label="Train events" value={preflight.train_events?.toLocaleString() ?? "N/A"} />
            <Metric label="Holdout events" value={preflight.test_events?.toLocaleString() ?? "N/A"} />
            <Metric label="Train event rate" value={formatPercent(preflight.train_event_rate)} />
            <Metric label="Estimated memory" value={`${preflight.estimated_memory_mb.toLocaleString()} MB`} />
            <Metric label="Preflight" value={`${preflight.duration_ms.toLocaleString()} ms`} />
          </div> : null}
          {preflight?.blocking_errors.length ? <div className="mt-4 space-y-2">{preflight.blocking_errors.map((item) => <div key={item} className="flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-900"><XCircle size={16} className="mt-0.5 shrink-0" />{item}</div>)}</div> : null}
          {preflight?.warnings.length ? <details className="mt-4 rounded-lg border border-amber-200 bg-amber-50 p-3"><summary className="cursor-pointer text-sm font-semibold text-amber-950">{preflight.warnings.length} preflight warning(s)</summary><ul className="mt-2 space-y-1 text-sm text-amber-900">{preflight.warnings.map((item) => <li key={item}>{item}</li>)}</ul></details> : null}
        </AtlasWorkflowSection>

        <AtlasWorkflowSection eyebrow="Model and tuning configuration" title="Execution Policy" description="Set ranking objective, tuning depth, calibration, and bounded local runtime before starting the governed training job." tone="info">
          <div className="grid gap-4 xl:grid-cols-[1.35fr_0.65fr]">
            <div className="rounded-xl border border-blue-200 bg-white p-4 shadow-sm">
              <div className="flex items-center gap-2 text-sm font-semibold text-slate-950"><SlidersHorizontal size={16} className="text-blue-700" /> Objective and search strategy</div>
              <p className="mt-1 text-xs leading-5 text-slate-600">Choose the metric and hyperparameter depth that will rank candidate models. Evaluation and governance still approve the champion downstream.</p>
              <div className="mt-4 grid gap-3 lg:grid-cols-3">
                <label><span className="atlas-label">Primary ranking metric</span><select className="atlas-input" value={primaryMetric} onChange={(event) => { setPrimaryMetric(event.target.value); setSortMetric(event.target.value); }}>{problemType === "classification" ? <><option value="pr_auc">PR-AUC</option><option value="auc">ROC-AUC</option><option value="ks">KS</option><option value="f1">F1</option><option value="recall">Recall</option></> : <><option value="rmse">RMSE</option><option value="mae">MAE</option><option value="r2">R-squared</option></>}</select><span className="mt-1 block text-xs text-slate-500">Ranking supports review; it does not approve a champion.</span></label>
                <label className="rounded-xl border border-blue-200 bg-blue-50 p-3"><span className="flex items-center gap-2 text-sm font-semibold text-slate-900"><input type="checkbox" checked={gridSearch} disabled={jobActive || !cvConfigured} onChange={(event) => { setGridSearch(event.target.checked); setPreflight(null); }} /> Hyperparameter search</span><p className="mt-1 text-xs text-blue-900">{cvConfigured ? "Tuning is constrained to the approved training-population folds." : "Unavailable because Validation Design contains no approved CV architecture."}</p><select className="atlas-input mt-3" disabled={!gridSearch || jobActive || !cvConfigured} value={gridSearchLevel} onChange={(event) => { setGridSearchLevel(event.target.value as typeof gridSearchLevel); setPreflight(null); }}><option value="quick">Quick</option><option value="balanced">Balanced</option><option value="thorough">Thorough</option></select></label>
                <label className="rounded-xl border border-emerald-200 bg-emerald-50 p-3"><span className="flex items-center gap-2 text-sm font-semibold text-slate-900"><input type="checkbox" checked={calibrate} disabled={problemType === "regression" || jobActive} onChange={(event) => { setCalibrate(event.target.checked); setPreflight(null); }} /> Probability calibration</span><p className="mt-1 text-xs leading-5 text-emerald-900">Applied only to compatible supervised classifiers with event-count-safe folds.</p></label>
              </div>
            </div>
            <div className="rounded-xl border border-slate-200 bg-slate-50 p-4 shadow-sm">
              <div className="flex items-center gap-2 text-sm font-semibold text-slate-950"><Cpu size={16} className="text-slate-700" /> Runtime guardrails</div>
              <p className="mt-1 text-xs leading-5 text-slate-600">ATLAS caps local work so the UI stays responsive and completed models remain available if a run is stopped.</p>
              <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-1">
                <div className="rounded-lg border border-emerald-200 bg-emerald-50 p-3" data-testid="inherited-cross-validation"><span className="atlas-label">Cross-validation folds · read-only</span><div className="mt-1 flex items-center gap-2 text-sm font-semibold text-slate-950"><LockKeyhole size={14} className="text-emerald-700" />{cvConfigured ? `${splitStatus?.cv_design?.method?.replace(/_/g, " ")} · ${kFolds} folds` : "No approved CV design"}</div><span className="mt-1 block text-xs leading-5 text-slate-600">Inherited from {splitStatus?.validation_design_version ?? "Validation Design"}. Model Training cannot redefine folds.</span></div>
                <label><span className="atlas-label">Parallel model workers</span><input className="atlas-input" type="number" min="1" max="4" value={maxParallel} disabled={jobActive} onChange={(event) => { setMaxParallel(Math.max(1, Math.min(4, Number(event.target.value) || 1))); setPreflight(null); }} /><span className="mt-1 block text-xs text-slate-500">Actual concurrency is capped by preflight.</span></label>
              </div>
            </div>
          </div>
        </AtlasWorkflowSection>

        <AtlasWorkflowSection
          eyebrow="Guided program design"
          title="Candidate Strategy"
          description="Choose the modeling posture first. ATLAS uses the approved validation folds to estimate workload; every strategy remains reviewer-controlled and can be refined as a custom portfolio."
          tone="info"
        >
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3" data-testid="candidate-strategy-selector">
            {CANDIDATE_STRATEGIES.map((strategy) => {
              const keys = strategy.models[problemType].filter((key) =>
                availableDefinitions.some((model) => model.key === key),
              );
              return (
                <button
                  key={strategy.key}
                  type="button"
                  className={`rounded-xl border p-4 text-left transition ${
                    candidateStrategy === strategy.key
                      ? "border-blue-600 bg-blue-50 shadow-sm ring-1 ring-blue-200"
                      : "border-slate-200 bg-white hover:border-blue-300 hover:bg-blue-50/40"
                  }`}
                  disabled={jobActive}
                  onClick={() => applyCandidateStrategy(strategy.key)}
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="text-sm font-semibold text-slate-950">{strategy.title}</div>
                    <span className="rounded-full bg-slate-100 px-2 py-1 text-[10px] font-bold text-slate-600">
                      {strategy.key === "custom_portfolio" ? selectedModels.length : keys.length} models
                    </span>
                  </div>
                  <p className="mt-2 text-xs leading-5 text-slate-600">{strategy.description}</p>
                  <div className="mt-3 grid grid-cols-2 gap-2 text-[10px] text-slate-600">
                    <span><strong>Interpretability:</strong> {strategy.interpretability}</span>
                    <span><strong>CV workload:</strong> {Math.max(1, keys.length || selectedModels.length) * Math.max(1, kFolds)} base fits</span>
                    <span><strong>Encoding:</strong> governed pipeline</span>
                    <span><strong>Governance:</strong> {strategy.key.includes("performance") || strategy.key.includes("research") ? "Higher" : "Moderate"}</span>
                  </div>
                </button>
              );
            })}
          </div>
        </AtlasWorkflowSection>

        <AtlasWorkflowSection eyebrow="Candidate algorithms" title="Model Portfolio" description="Algorithm Selection is now a searchable, filterable governed catalog. Selected cards use ATLAS blue; unavailable libraries remain visible with a reason. Diagnostic anomaly models stay outside champion eligibility." tone="info">
          <div className="space-y-5">
            <div className="rounded-xl border border-slate-200 bg-slate-50 p-4" data-testid="model-portfolio-filters">
              <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-[1.4fr_1fr_0.8fr_auto_auto_auto]">
                <label><span className="atlas-label">Search models</span><span className="relative block"><Search size={15} className="pointer-events-none absolute left-3 top-2.5 text-slate-400" /><input className="atlas-input pl-9" value={modelSearch} onChange={(event) => setModelSearch(event.target.value)} placeholder="Name, family, purpose, or best use" /></span></label>
                <label><span className="atlas-label">Model family</span><select className="atlas-input" value={familyFilter} onChange={(event) => setFamilyFilter(event.target.value)}><option value="all">All families</option>{[...new Set(availableDefinitions.map((model) => model.family))].map((family) => <option key={family} value={family}>{family}</option>)}</select></label>
                <label><span className="atlas-label">Interpretability</span><select className="atlas-input" value={interpretabilityFilter} onChange={(event) => setInterpretabilityFilter(event.target.value)}><option value="all">All levels</option><option value="High">High</option><option value="Medium">Medium</option><option value="Low">Low</option></select></label>
                <label className="mt-5 flex items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs font-semibold text-slate-700"><input type="checkbox" checked={selectedOnly} onChange={(event) => setSelectedOnly(event.target.checked)} />Selected only</label>
                <label className="mt-5 flex items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs font-semibold text-slate-700"><input type="checkbox" checked={recommendedOnly} onChange={(event) => setRecommendedOnly(event.target.checked)} />Recommended</label>
                <button type="button" className="atlas-secondary-button mt-5" onClick={() => setCompactPortfolio((current) => !current)}><Filter size={14} />{compactPortfolio ? "Expanded cards" : "Compact cards"}</button>
              </div>
              <div className="mt-3 grid gap-2 sm:grid-cols-4">
                <Metric label="Catalog" value={availableDefinitions.length} />
                <Metric label="Visible" value={visibleDefinitions.length} />
                <Metric label="Selected" value={selectedModels.length} tone={selectedModels.length ? "success" : "warning"} />
                <Metric label="Unavailable" value={availableDefinitions.filter((model) => availability[model.key] === false).length} />
              </div>
            </div>
            <div className="grid gap-3 lg:grid-cols-3">
              {MODEL_SUITE_PRESETS.map((suite) => {
                const suiteKeys = suite.models[problemType].filter((key) => availableDefinitions.some((model) => model.key === key));
                const selectedCount = suiteKeys.filter((key) => selectedModels.includes(key)).length;
                const fullySelected = suiteKeys.length > 0 && selectedCount === suiteKeys.length;
                return (
                  <button key={suite.key} type="button" className={`rounded-xl border p-4 text-left transition ${fullySelected ? "border-blue-500 bg-blue-50 shadow-sm" : "border-slate-200 bg-white hover:border-blue-300 hover:bg-blue-50/50"}`} disabled={jobActive || !suiteKeys.length} onClick={() => { setCandidateStrategy("custom_portfolio"); setSelectedModels(suiteKeys); setPreflight(null); }}>
                    <div className="flex items-start justify-between gap-3">
                      <div><div className="text-sm font-semibold text-slate-950">{suite.title}</div><p className="mt-1 text-xs leading-5 text-slate-600">{suite.description}</p></div>
                      <span className="rounded-full border border-blue-200 bg-blue-50 px-2 py-1 text-[10px] font-semibold uppercase text-blue-800">{suiteKeys.length} models</span>
                    </div>
                    <div className="mt-3 text-xs font-semibold text-blue-800">{selectedCount} selected | Select suite</div>
                  </button>
                );
              })}
            </div>
            {problemType === "classification" ? (
              <AtlasAttentionPanel title="Unsupervised anomaly models fit without a target" tone="info">
                Isolation Forest, Local Outlier Factor, One-Class SVM, and Robust Covariance do not use the target during fitting. In this supervised project, ATLAS uses the target only to benchmark their anomaly scores after fitting. They remain diagnostic models and are never eligible for champion selection.
              </AtlasAttentionPanel>
            ) : null}
            {[...new Set(visibleDefinitions.map((model) => model.family))].map((family) => (
              <div key={family}>
                <h3 className="text-sm font-semibold text-slate-950">{family}</h3>
                <div className="mt-2 grid gap-3 lg:grid-cols-2">
                  {visibleDefinitions.filter((model) => model.family === family).map((model) => {
                    const libraryAvailable = availability[model.key] !== false;
                    const compatibility = preflight?.model_compatibility?.[model.key];
                    const enabled = libraryAvailable && compatibility?.compatible !== false;
                    const selected = selectedModels.includes(model.key);
                    const execution = job?.per_model_status?.[model.key];
                    const displayLabel = cleanModelLabel(model.label);
                    const unavailableCopy = model.key === "ebm"
                      ? "Explainable Boosting Machine requires the optional interpret package. Install or enable that backend dependency to train EBM."
                      : `${displayLabel} library is not installed or could not initialize.`;
                    return <ModelCard key={model.key} model={model} selected={selected} enabled={enabled} unavailableReason={!libraryAvailable ? unavailableCopy : compatibility?.reason} execution={execution} tuning={gridSearch ? `${gridSearchLevel} search` : "Governed defaults"} onToggle={() => toggleModel(model.key)} disabled={jobActive} compact={compactPortfolio} recommended={recommendedModelKeys.has(model.key)} />;
                  })}
                </div>
              </div>
            ))}
            {!visibleDefinitions.length ? <div className="rounded-xl border border-dashed border-slate-300 bg-slate-50 p-8 text-center text-sm text-slate-500">No models match the active portfolio filters.</div> : null}
          </div>
        </AtlasWorkflowSection>

        <AtlasWorkflowSection
          eyebrow="Executable modeling program"
          title="Training Plan"
          description="Review the complete workload before execution. Counts are estimates based on selected candidates, approved folds, tuning depth, calibration, and available workers."
          tone={largeJob && !largeJobConfirmed ? "warning" : "info"}
          action={<span className="inline-flex items-center gap-1 text-xs font-semibold text-slate-700"><Gauge size={14} />{estimatedFits.toLocaleString()} estimated fits</span>}
        >
          <TrainingPlanVisual
            selectedModels={selectedDefinitions}
            folds={kFolds}
            cvMethod={splitStatus?.cv_design?.method ?? "none"}
            tuningDepth={gridSearch ? gridSearchLevel : "governed defaults"}
            tuningCandidates={tuningCandidateCount}
            calibration={calibrate && problemType === "classification"}
            workers={maxParallel}
            estimatedFits={estimatedFits}
            estimatedMemoryMb={preflight?.estimated_memory_mb}
            estimatedRuntimeSeconds={estimateRuntimeSeconds(estimatedFits, maxParallel)}
          />
          <div className="mt-4 grid gap-2 sm:grid-cols-3">
            <div className="rounded-lg border border-slate-200 bg-slate-50 p-3 text-xs leading-5 text-slate-600"><strong className="text-slate-900">Queue order</strong><br />Transparent baselines first, then interpretable challengers, ensembles, optional neural models, and diagnostics.</div>
            <div className="rounded-lg border border-slate-200 bg-slate-50 p-3 text-xs leading-5 text-slate-600"><strong className="text-slate-900">Cancellation policy</strong><br />Kill unfinished work; completed model metrics and artifacts remain persisted. Queued models are cancelled immediately.</div>
            <div className="rounded-lg border border-slate-200 bg-slate-50 p-3 text-xs leading-5 text-slate-600"><strong className="text-slate-900">Resource policy</strong><br />Local concurrency is capped by preflight memory and CPU recommendations; no silent distributed execution.</div>
          </div>
          {largeJob ? (
            <label className={`mt-4 flex items-start gap-3 rounded-xl border p-4 ${largeJobConfirmed ? "border-emerald-200 bg-emerald-50" : "border-amber-300 bg-amber-50"}`}>
              <input className="mt-1" type="checkbox" checked={largeJobConfirmed} onChange={(event) => setLargeJobConfirmed(event.target.checked)} />
              <span className="text-sm leading-6 text-slate-800"><strong>Explicit large-job confirmation required.</strong> I reviewed the {estimatedFits.toLocaleString()} estimated fits, runtime, memory, queue, and cancellation behavior.</span>
            </label>
          ) : null}
        </AtlasWorkflowSection>

        <div className="sticky bottom-24 z-10 rounded-lg border border-blue-300 bg-white/95 p-4 shadow-xl shadow-slate-900/15 backdrop-blur-xl">
          <div className="flex flex-col gap-3 xl:flex-row xl:items-center xl:justify-between">
            <div className="min-w-0">
              <div className="flex items-center gap-2 text-sm font-semibold text-slate-950"><BrainCircuit size={17} className="text-blue-700" /> Selected Model Bench <span className="text-blue-700">{selectedModels.length}</span></div>
              <div className="mt-2 flex flex-wrap gap-1.5">{selectedDefinitions.length ? selectedDefinitions.map((model) => <span key={model.key} className="rounded-full border border-blue-200 bg-blue-50 px-2.5 py-1 text-xs font-semibold text-blue-800">{modelLabel(model.key, labels)}</span>) : <span className="text-sm text-amber-800">Select at least one compatible model.</span>}</div>
              <div className="mt-2 text-xs text-slate-500">{gridSearch ? `${gridSearchLevel} tuning` : "Governed defaults"} | {kFolds} inherited fold(s) | {estimatedFits.toLocaleString()} estimated fits | {calibrate ? "Calibration requested where compatible" : "No added calibration"} | {maxParallel} requested worker(s) | {readiness ? "Preflight current" : "Preflight will run when training starts"}</div>
            </div>
            <div className="flex flex-wrap gap-2">
              <button type="button" className="atlas-secondary-button" disabled={jobActive || !selectedModels.length} onClick={() => { setSelectedModels([]); setPreflight(null); }}><Trash2 size={15} /> Clear all</button>
              {jobActive ? <button type="button" className="atlas-destructive-button" title="Cancel Training" onClick={() => void cancelTraining()}><CircleStop size={15} /> Kill unfinished</button> : null}
              <button type="button" className="atlas-primary-button min-w-60" disabled={trainActionBlocked} onClick={() => void startTraining()}><Play size={16} /> {trainActionLabel}</button>
            </div>
          </div>
          {!trainActionBlocked && !readiness ? <div className="mt-3 border-t border-blue-100 pt-3 text-xs font-medium text-blue-800">ATLAS will validate the current split, feature contract, selected algorithms, dependencies, and runtime policy, then start the job without requiring a separate preflight action.</div> : null}
        </div>

        <AtlasWorkflowSection eyebrow="Background execution" title="Live Training" description="Each selected model reports its own preparation, fit, completion, cancellation, or failure state." tone={job?.overall_status === "complete" ? "success" : job?.overall_status === "failed" ? "danger" : jobActive ? "info" : "neutral"} action={<div className="flex flex-wrap items-center gap-2"><AtlasExecutionStatus state={job?.overall_status ?? "idle"} label={job ? `Job ${job.overall_status}` : "No active job"} detail={job?.job_id} />{jobActive && Object.values(job?.per_model_status ?? {}).some((state) => state.status === "queued") ? <button type="button" className="atlas-secondary-button" onClick={() => void cancelQueuedModels()}><CircleStop size={15} /> Cancel queued only</button> : null}{jobActive ? <button type="button" className="atlas-destructive-button" onClick={() => void cancelTraining()}><CircleStop size={15} /> Kill unfinished</button> : null}</div>}>
          {job ? <>
            <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-8">
              <Metric label="Job ID" value={job.job_id} />
              <Metric label="Started" value={job.started_at ? new Date(job.started_at).toLocaleTimeString() : "Queued"} />
              <Metric label="Finished" value={`${finishedCount} / ${job.total_count}`} />
              <Metric label="Successful" value={job.completed_count} tone={job.completed_count ? "success" : "neutral"} />
              <Metric label="Failed" value={job.failed_models.length} tone={job.failed_models.length ? "warning" : "neutral"} />
              <Metric label="Running" value={Object.values(job.per_model_status).filter((state) => state.status === "running" || state.status === "preparing").length} />
              <Metric label="Queued" value={Object.values(job.per_model_status).filter((state) => state.status === "queued").length} />
              <Metric label="Canceled" value={Object.values(job.per_model_status).filter((state) => state.status === "cancelled").length} />
              <Metric label="Workers" value={job.max_parallel_honored} />
              <Metric label="Runtime" value={`${(job.runtime_ms / 1000).toFixed(1)} s`} />
            </div>
            <div className="mt-4"><div className="flex justify-between text-xs font-semibold text-slate-600"><span>{job.user_message ?? job.message}</span><span>{progress}%</span></div><div className="mt-2 h-2 overflow-hidden rounded bg-slate-100"><div className="h-full bg-blue-600 transition-all" style={{ width: `${progress}%` }} /></div></div>
            <div className="mt-4 grid gap-3 lg:grid-cols-2">{job.requested_models.map((key) => <ExecutionCard key={key} label={modelLabel(key, labels)} status={job.per_model_status[key]} history={job.per_model_history?.[key]} />)}</div>
            <div className="mt-4 grid gap-2 sm:grid-cols-3">
              <Metric label="Resource utilization" value={`${job.max_parallel_honored} / ${maxParallel} worker slots`} />
              <Metric label="Memory envelope" value={preflight ? `${preflight.estimated_memory_mb.toLocaleString()} MB estimated` : "Pending preflight"} />
              <Metric label="Persistence rule" value="Metrics persisted + artifacts persisted before complete" tone={job.overall_status === "complete" ? "success" : "neutral"} />
            </div>
          </> : <div className="flex min-h-36 items-center justify-center text-sm text-slate-500">Run preflight, select compatible models, and start a governed training job.</div>}
        </AtlasWorkflowSection>

        <AtlasWorkflowSection eyebrow="Partial and final results" title="Candidate Leaderboard" description="Results appear as models finish. The leading metric identifies a candidate only; governance review and downstream evaluation remain required." tone="neutral" action={<label className="flex items-center gap-2 text-xs font-semibold text-slate-600">Sort by <select className="atlas-input w-32" value={sortMetric} onChange={(event) => setSortMetric(event.target.value)}>{problemType === "classification" ? <><option value="pr_auc">PR-AUC</option><option value="auc">ROC-AUC</option><option value="ks">KS</option><option value="f1">F1</option><option value="recall">Recall</option></> : <><option value="rmse">RMSE</option><option value="mae">MAE</option><option value="r2">R-squared</option></>}</select></label>}>
          <CandidateLeaderboard results={results} problemType={problemType} sortMetric={sortMetric} />
          {job?.failed_models.length ? <details className="mt-4 rounded-lg border border-red-200 bg-red-50 p-3"><summary className="cursor-pointer text-sm font-semibold text-red-950">{job.failed_models.length} model failure(s)</summary><div className="mt-3 flex justify-end"><button type="button" className="atlas-secondary-button" disabled={jobActive} onClick={() => void retryFailedModels()}><RotateCcw size={14} />Retry failed models</button></div><div className="mt-3 space-y-2">{job.failed_models.map((failure) => <div key={failure.key} className="rounded-lg border border-red-200 bg-white p-3"><div className="font-semibold text-red-950">{failure.name}</div><div className="mt-1 text-sm text-red-900">{failure.error}</div>{failure.technical_error ? <details className="mt-2"><summary className="cursor-pointer text-xs font-semibold text-slate-600">Technical details</summary><pre className="mt-2 overflow-auto whitespace-pre-wrap rounded bg-slate-950 p-3 text-xs text-slate-100">{failure.technical_error}\nReference: {failure.traceback_reference}</pre></details> : null}</div>)}</div></details> : null}
        </AtlasWorkflowSection>

        <AtlasWorkflowSection
          eyebrow="Governed analyst decision"
          title="Champion / Challenger Review"
          description="Select a proposed champion and challengers, then document the decision basis. No champion is approved automatically. Not approved until Evaluation and governance review; final approval remains downstream in Evaluation / Validation."
          tone={selectionDecision?.training_job_id === job?.job_id ? "success" : "info"}
          action={selectionDecision ? <span className="rounded-full border border-blue-200 bg-blue-50 px-3 py-1 text-xs font-semibold uppercase text-blue-800">{selectionDecision.status}</span> : undefined}
        >
          {!championEligibleResults.length ? (
            <AtlasAttentionPanel title="Candidate evidence required" tone="warning">Complete at least one supervised, champion-eligible model before proposing a champion or challenger.</AtlasAttentionPanel>
          ) : (
            <div className="grid gap-4 xl:grid-cols-[0.75fr_1.25fr]">
              <div className="space-y-3">
                <label><span className="atlas-label">Proposed champion</span><select className="atlas-input mt-1" value={championModel} onChange={(event) => { const next = event.target.value; setChampionModel(next); setChallengerModels((current) => current.filter((key) => key !== next)); }}>{championEligibleResults.map((row) => <option key={row.key} value={row.key}>{cleanModelLabel(row.name)} · {formatMetric(metricValue(row, primaryMetric))} {primaryMetric.replace(/_/g, " ")}</option>)}</select></label>
                <div>
                  <div className="atlas-label">Proposed challenger(s)</div>
                  <div className="mt-1 space-y-1 rounded-lg border border-slate-200 bg-white p-3">
                    {championEligibleResults.filter((row) => row.key !== championModel).map((row) => <label key={row.key} className="flex items-center justify-between gap-3 text-xs text-slate-700"><span className="flex items-center gap-2"><input type="checkbox" checked={challengerModels.includes(row.key)} onChange={(event) => setChallengerModels((current) => event.target.checked ? [...new Set([...current, row.key])] : current.filter((key) => key !== row.key))} />{cleanModelLabel(row.name)}</span><span className="font-mono">{formatMetric(metricValue(row, primaryMetric))}</span></label>)}
                  </div>
                </div>
                <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs leading-5 text-amber-950"><strong>Status flow:</strong> Candidate → Proposed → Under review → Approved / Rejected / Superseded. This page stops at Proposed.</div>
              </div>
              <div className="grid gap-3 md:grid-cols-2">
                <DecisionTextArea label="Decision rationale" value={selectionRationale} onChange={setSelectionRationale} placeholder="Why this champion/challenger configuration is appropriate." required />
                <DecisionTextArea label="Metric justification" value={metricJustification} onChange={setMetricJustification} placeholder={`Why ${primaryMetric.replace(/_/g, " ")} is decision-relevant and what secondary metrics qualify it.`} />
                <DecisionTextArea label="Interpretability justification" value={interpretabilityJustification} onChange={setInterpretabilityJustification} placeholder="Explain transparency, complexity, and governance tradeoffs." />
                <DecisionTextArea label="Calibration considerations" value={calibrationConsiderations} onChange={setCalibrationConsiderations} placeholder="Probability quality, calibration method, or downstream calibration needs." />
                <DecisionTextArea label="Fairness / validation prerequisites" value={fairnessPrerequisites} onChange={setFairnessPrerequisites} placeholder="Required segment, fairness, stability, OOT, or stress validation." />
                <DecisionTextArea label="Deployment constraints" value={deploymentConstraints} onChange={setDeploymentConstraints} placeholder="Latency, dependencies, monitoring, retraining, or platform constraints." />
                <label className="md:col-span-2"><span className="atlas-label">Reviewer notes</span><textarea className="atlas-input mt-1 min-h-20 w-full" value={reviewerNotes} onChange={(event) => setReviewerNotes(event.target.value)} placeholder="Open questions, review assignments, and downstream conditions." /></label>
                <div className="flex flex-wrap justify-end gap-2 md:col-span-2">
                  <button type="button" className="atlas-primary-button" disabled={decisionSaving || !job || job.overall_status !== "complete" || selectionRationale.trim().length < 10} onClick={() => void saveModelSelectionDecision("proposed")}>{decisionSaving ? <LoaderCircle size={15} className="animate-spin" /> : <Trophy size={15} />}Save governed proposal</button>
                </div>
              </div>
            </div>
          )}
        </AtlasWorkflowSection>

        <AtlasWorkflowSection
          eyebrow="Governed record"
          title="Evidence and Documentation"
          description="The approved Validation Design, portfolio, tuning and calibration policies, runtime, job IDs, candidate metrics, failures, proposal rationale, and artifact lineage flow live into the MDD and Evidence Center."
          tone="neutral"
        >
          <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-5">
            <Metric label="Validation Design" value={splitStatus?.validation_design_version ?? "Unavailable"} />
            <Metric label="Training job" value={job?.job_id ?? "Not started"} />
            <Metric label="Model metrics" value={results.length} tone={results.length ? "success" : "warning"} />
            <Metric label="Decision proposal" value={selectionDecision?.decision_id ?? "Required"} tone={selectionDecision ? "success" : "warning"} />
            <Metric label="MDD status" value={selectionDecision?.training_job_id === job?.job_id ? "Live draft current" : job?.overall_status === "complete" ? "Draft needs proposal" : "Draft"} />
          </div>
        </AtlasWorkflowSection>
      </div>
    </StepShell>
  );
}

function validationDesignLabel(status: SplitStatus | null) {
  if (!status?.validation_design) return "Validation Design unavailable";
  const strategy = String(status.validation_design.strategy ?? "approved design")
    .replace(/_/g, " ");
  const method = String(status.cv_design?.method ?? "none").replace(/_/g, " ");
  const folds = Number(status.cv_design?.fold_count ?? 0);
  return folds >= 2 ? `${strategy} · ${method} ${folds}-fold` : strategy;
}

function estimateRuntimeSeconds(estimatedFits: number, workers: number) {
  return Math.max(5, Math.round((estimatedFits * 2.5) / Math.max(1, workers)));
}

function TrainingMissionControl({
  projectName,
  target,
  problemType,
  trainRows,
  validationRows,
  testAvailable,
  ootAvailable,
  featureCount,
  engineeredCount,
  cvLabel,
  primaryMetric,
  selectedModels,
  jobState,
  readiness,
  estimatedFits,
  estimatedMemory,
  blockers,
  warnings,
}: {
  projectName: string;
  target: string;
  problemType: ProblemType;
  trainRows?: number;
  validationRows?: number;
  testAvailable: boolean;
  ootAvailable: boolean;
  featureCount: number;
  engineeredCount: number;
  cvLabel: string;
  primaryMetric: string;
  selectedModels: number;
  jobState: string;
  readiness: boolean;
  estimatedFits: number;
  estimatedMemory?: number;
  blockers: number;
  warnings: number;
}) {
  const score = blockers ? 35 : readiness ? 100 : 72;
  return (
    <section className="overflow-hidden rounded-2xl border border-slate-800 bg-slate-950 text-white shadow-xl" data-testid="training-mission-control">
      <div className="grid lg:grid-cols-[minmax(0,1fr)_220px]">
        <div className="p-5">
          <div className="flex flex-wrap items-center gap-2 text-[10px] font-bold uppercase tracking-[0.16em] text-cyan-300">
            <BrainCircuit size={15} />
            Step 7 · Model Training
          </div>
          <div className="mt-2 flex flex-wrap items-end justify-between gap-3">
            <div>
              <h1 className="text-2xl font-semibold tracking-tight">Training Mission Control</h1>
              <p className="mt-1 text-sm text-slate-300">Turn the governed workflow into an executable modeling program.</p>
            </div>
            <span className={`rounded-full border px-3 py-1 text-xs font-bold uppercase ${jobState === "complete" ? "border-emerald-400/50 bg-emerald-500/20 text-emerald-200" : jobState === "running" ? "border-blue-400/50 bg-blue-500/20 text-blue-200" : "border-slate-600 bg-slate-900 text-slate-300"}`}>{jobState}</span>
          </div>
          <div className="mt-5 grid gap-2 sm:grid-cols-2 xl:grid-cols-5">
            <MissionMetric label="Project" value={projectName} />
            <MissionMetric label="Target" value={target || "Not confirmed"} />
            <MissionMetric label="Problem type" value={problemType} />
            <MissionMetric label="Training rows" value={trainRows?.toLocaleString() ?? "Preflight"} />
            <MissionMetric label="Holdout / TEST rows" value={validationRows?.toLocaleString() ?? "Preflight"} />
            <MissionMetric label="TEST / OOT" value={`${testAvailable ? "TEST ready" : "No TEST"} · ${ootAvailable ? "OOT ready" : "No OOT"}`} />
            <MissionMetric label="Features" value={`${featureCount} total · ${engineeredCount} engineered`} />
            <MissionMetric label="CV strategy" value={cvLabel} />
            <MissionMetric label="Primary metric" value={primaryMetric.replace(/_/g, " ")} />
            <MissionMetric label="Selected models" value={selectedModels.toLocaleString()} />
            <MissionMetric label="Estimated runtime" value={`~${Math.ceil(estimateRuntimeSeconds(estimatedFits, 2) / 60)} min planning estimate`} />
            <MissionMetric label="Estimated memory" value={estimatedMemory == null ? "Preflight" : `${estimatedMemory.toLocaleString()} MB`} />
            <MissionMetric label="Estimated fits" value={estimatedFits.toLocaleString()} />
            <MissionMetric label="Warnings" value={warnings.toLocaleString()} />
            <MissionMetric label="Blockers" value={blockers.toLocaleString()} />
          </div>
        </div>
        <div className="flex flex-col items-center justify-center border-t border-slate-800 bg-slate-900/70 p-5 lg:border-l lg:border-t-0">
          <div className="relative flex h-32 w-32 items-center justify-center rounded-full" style={{ background: `conic-gradient(${score === 100 ? "#34d399" : "#60a5fa"} ${score * 3.6}deg, #334155 0deg)` }}>
            <div className="flex h-24 w-24 flex-col items-center justify-center rounded-full bg-slate-950">
              <span className="text-2xl font-bold">{score}%</span>
              <span className="text-[9px] font-bold uppercase tracking-wide text-slate-400">readiness</span>
            </div>
          </div>
          <div className={`mt-3 text-center text-xs font-semibold ${readiness ? "text-emerald-300" : blockers ? "text-rose-300" : "text-blue-300"}`}>
            {readiness ? "Ready for governed execution" : blockers ? `${blockers} blocker(s) require action` : "Preflight confirmation pending"}
          </div>
        </div>
      </div>
    </section>
  );
}

function MissionMetric({ label, value }: { label: string; value: string }) {
  return <div className="min-w-0 rounded-lg border border-slate-800 bg-slate-900/80 p-2.5"><div className="text-[9px] font-bold uppercase tracking-wide text-slate-500">{label}</div><div className="mt-1 truncate text-xs font-semibold text-slate-100" title={value}>{value}</div></div>;
}

function LockedInputCard({ title, value, detail, href, testId }: { title: string; value: string; detail: string; href: string; testId?: string }) {
  return (
    <a href={href} className="group rounded-xl border border-slate-200 bg-white p-4 transition hover:border-blue-300 hover:bg-blue-50/30" data-testid={testId}>
      <div className="flex items-center justify-between gap-2"><span className="text-[10px] font-bold uppercase tracking-wide text-slate-500">{title}</span><LockKeyhole size={13} className="text-emerald-600" /></div>
      <div className="mt-2 truncate text-sm font-semibold text-slate-950" title={value}>{value}</div>
      <div className="mt-1 line-clamp-2 text-xs leading-5 text-slate-600">{detail || "No additional configuration"}</div>
      <div className="mt-3 text-[10px] font-bold text-blue-700 group-hover:underline">Open source contract →</div>
    </a>
  );
}

function TrainingPlanVisual({
  selectedModels,
  folds,
  cvMethod,
  tuningDepth,
  tuningCandidates,
  calibration,
  workers,
  estimatedFits,
  estimatedMemoryMb,
  estimatedRuntimeSeconds,
}: {
  selectedModels: ModelDefinition[];
  folds: number;
  cvMethod: string;
  tuningDepth: string;
  tuningCandidates: number;
  calibration: boolean;
  workers: number;
  estimatedFits: number;
  estimatedMemoryMb?: number;
  estimatedRuntimeSeconds: number;
}) {
  const stages = [
    { label: "Candidates", value: `${selectedModels.length} models`, icon: BrainCircuit },
    { label: "Validation", value: `${folds} folds · ${cvMethod.replace(/_/g, " ")}`, icon: GitCompareArrows },
    { label: "Tuning", value: `${tuningCandidates} candidate set(s) · ${tuningDepth}`, icon: SlidersHorizontal },
    { label: "Calibration", value: calibration ? `${selectedModels.length * folds} additional fits` : "Not requested", icon: Target },
    { label: "Workers", value: `${workers} requested`, icon: Cpu },
    { label: "Persist", value: "Metrics + artifacts", icon: ShieldCheck },
  ];
  return (
    <div data-testid="training-plan-visual">
      <div className="grid gap-2 md:grid-cols-3 xl:grid-cols-6">
        {stages.map(({ label, value, icon: Icon }, index) => <div key={label} className="relative rounded-xl border border-blue-200 bg-blue-50/50 p-3"><div className="flex items-center justify-between"><Icon size={15} className="text-blue-700" /><span className="text-[9px] font-bold text-slate-400">{index + 1}</span></div><div className="mt-2 text-[10px] font-bold uppercase text-slate-500">{label}</div><div className="mt-1 text-xs font-semibold leading-5 text-slate-900">{value}</div></div>)}
      </div>
      <div className="mt-4 rounded-xl border border-slate-800 bg-slate-950 p-4 text-white">
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
          <PlanEquation value={selectedModels.length} label="models" />
          <PlanEquation value={`× ${folds}`} label="CV folds" />
          <PlanEquation value={`× ${tuningCandidates}`} label="tuning candidates" />
          <PlanEquation value={calibration ? `+ ${selectedModels.length * folds}` : "+ 0"} label="calibration fits" />
          <PlanEquation value={`= ${estimatedFits}`} label="estimated total fits" highlight />
        </div>
        <div className="mt-4 grid gap-2 sm:grid-cols-3">
          <div className="flex items-center gap-2 text-xs text-slate-300"><Timer size={14} className="text-cyan-300" />~{Math.ceil(estimatedRuntimeSeconds / 60)} min planning estimate</div>
          <div className="flex items-center gap-2 text-xs text-slate-300"><MemoryStick size={14} className="text-cyan-300" />{estimatedMemoryMb == null ? "Memory pending preflight" : `${estimatedMemoryMb.toLocaleString()} MB estimated`}</div>
          <div className="flex items-center gap-2 text-xs text-slate-300"><Layers3 size={14} className="text-cyan-300" />{workers} local worker(s), bounded</div>
        </div>
      </div>
    </div>
  );
}

function PlanEquation({ value, label, highlight = false }: { value: string | number; label: string; highlight?: boolean }) {
  return <div className={`rounded-lg border p-3 ${highlight ? "border-cyan-400/50 bg-cyan-500/20" : "border-slate-800 bg-slate-900"}`}><div className="text-lg font-bold">{value}</div><div className="mt-1 text-[10px] uppercase tracking-wide text-slate-400">{label}</div></div>;
}

function DecisionTextArea({ label, value, onChange, placeholder, required = false }: { label: string; value: string; onChange: (value: string) => void; placeholder: string; required?: boolean }) {
  return <label><span className="atlas-label">{label}{required ? " *" : ""}</span><textarea className="atlas-input mt-1 min-h-24 w-full" value={value} onChange={(event) => onChange(event.target.value)} placeholder={placeholder} /></label>;
}

function modelComplexity(definition?: ModelDefinition) {
  if (!definition) return "Review";
  if (definition.interpretability === "High") return "Low";
  if (definition.interpretability === "Medium") return "Moderate";
  return "High";
}

function CandidateComparisonVisuals({ candidates, problemType, primaryMetric }: { candidates: RankedResult[]; problemType: ProblemType; primaryMetric: string }) {
  const definitions = new Map(MODEL_DEFINITIONS.map((definition) => [definition.key, definition]));
  const primaryValues = candidates.map((row) => metricValue(row, primaryMetric)).filter((value): value is number => value !== null);
  const minPrimary = primaryValues.length ? Math.min(...primaryValues) : 0;
  const maxPrimary = primaryValues.length ? Math.max(...primaryValues) : 1;
  const ascending = ["rmse", "mae", "mse"].includes(primaryMetric);
  const score = (row: RankedResult) => {
    const value = metricValue(row, primaryMetric);
    if (value === null || maxPrimary === minPrimary) return 0.5;
    return ascending ? (maxPrimary - value) / (maxPrimary - minPrimary) : (value - minPrimary) / (maxPrimary - minPrimary);
  };
  const interp = (row: RankedResult) => ({ High: 0.85, Medium: 0.55, Low: 0.25 }[definitions.get(row.key)?.interpretability ?? "Low"]);
  const maxRuntime = Math.max(1, ...candidates.map((row) => Number(row.runtime_ms ?? 0)));
  return (
    <div className="grid gap-3 xl:grid-cols-2" data-testid="candidate-comparison-visuals">
      <ComparisonPlot title="Performance versus Interpretability frontier" xLabel="Interpretability →" yLabel="Performance ↑">
        {candidates.map((row, index) => <PlotPoint key={row.key} x={interp(row)} y={score(row)} label={`${index + 1}`} title={cleanModelLabel(row.name)} tone={index === 0 ? "blue" : "slate"} />)}
      </ComparisonPlot>
      <div className="rounded-xl border border-slate-200 bg-white p-4">
        <div className="text-sm font-semibold text-slate-950">Compact multi-metric profile</div>
        <div className="mt-4 space-y-3">{candidates.slice(0, 5).map((row) => {
          const metrics = problemType === "classification" ? [row.auc, row.pr_auc, row.ks, row.f1] : [row.r2, row.rmse == null ? null : 1 / (1 + row.rmse), row.mae == null ? null : 1 / (1 + row.mae)];
          return <div key={row.key}><div className="flex justify-between text-[10px] font-semibold text-slate-600"><span>{cleanModelLabel(row.name)}</span><span>{formatMetric(metricValue(row, primaryMetric))}</span></div><div className="mt-1 grid grid-cols-4 gap-1">{metrics.map((value, index) => <div key={index} className="h-2 overflow-hidden rounded bg-slate-100"><div className="h-full rounded bg-violet-500" style={{ width: `${Math.max(1, Math.min(100, Number(value ?? 0) * 100))}%` }} /></div>)}</div></div>;
        })}</div>
      </div>
      <ComparisonPlot title="Calibration treatment versus discrimination" xLabel="Discrimination →" yLabel="Calibration treatment ↑">
        {candidates.map((row, index) => <PlotPoint key={row.key} x={problemType === "classification" ? Number(row.auc ?? score(row)) : score(row)} y={row.calibration_applied ? 0.82 : 0.28} label={`${index + 1}`} title={`${cleanModelLabel(row.name)} · ${row.calibration_applied ? "calibrated" : "not calibrated"}`} tone={row.calibration_applied ? "emerald" : "slate"} />)}
      </ComparisonPlot>
      <ComparisonPlot title="Runtime versus performance" xLabel="Faster ← runtime → slower" yLabel="Performance ↑">
        {candidates.map((row, index) => <PlotPoint key={row.key} x={Number(row.runtime_ms ?? 0) / maxRuntime} y={score(row)} label={`${index + 1}`} title={`${cleanModelLabel(row.name)} · ${((row.runtime_ms ?? 0) / 1000).toFixed(1)} s`} tone={index === 0 ? "blue" : "amber"} />)}
      </ComparisonPlot>
      <div className="rounded-xl border border-slate-200 bg-white p-4 xl:col-span-2">
        <div className="text-sm font-semibold text-slate-950">Champion / Challenger Decision Matrix</div>
        <div className="mt-3 overflow-auto"><table className="atlas-table min-w-[760px]"><thead><tr><th>Candidate</th><th>Performance</th><th>Interpretability</th><th>Complexity</th><th>Calibration</th><th>Runtime</th><th>Decision signal</th></tr></thead><tbody>{candidates.slice(0, 8).map((row, index) => { const definition = definitions.get(row.key); return <tr key={row.key}><td className="font-semibold">{cleanModelLabel(row.name)}</td><td>{formatMetric(metricValue(row, primaryMetric))}</td><td>{definition?.interpretability ?? "Review"}</td><td>{modelComplexity(definition)}</td><td>{row.calibration_applied ? "Applied" : "Not applied"}</td><td>{typeof row.runtime_ms === "number" ? `${(row.runtime_ms / 1000).toFixed(1)} s` : "N/A"}</td><td>{index === 0 ? "Metric leader · proposal review" : definition?.interpretability === "High" ? "Governance challenger" : "Performance challenger"}</td></tr>; })}</tbody></table></div>
      </div>
    </div>
  );
}

function ComparisonPlot({ title, xLabel, yLabel, children }: { title: string; xLabel: string; yLabel: string; children: ReactNode }) {
  return <div className="rounded-xl border border-slate-200 bg-white p-4"><div className="text-sm font-semibold text-slate-950">{title}</div><div className="relative mt-4 h-44 rounded-lg border border-slate-200 bg-[linear-gradient(to_right,#e2e8f0_1px,transparent_1px),linear-gradient(to_bottom,#e2e8f0_1px,transparent_1px)] bg-[size:25%_25%]"><div className="absolute inset-3">{children}</div><div className="absolute bottom-1 left-1/2 -translate-x-1/2 text-[9px] font-semibold text-slate-500">{xLabel}</div><div className="absolute left-1 top-1 text-[9px] font-semibold text-slate-500">{yLabel}</div></div></div>;
}

function PlotPoint({ x, y, label, title, tone }: { x: number; y: number; label: string; title: string; tone: "blue" | "slate" | "emerald" | "amber" }) {
  const classes = { blue: "bg-blue-600 text-white", slate: "bg-slate-600 text-white", emerald: "bg-emerald-600 text-white", amber: "bg-amber-500 text-slate-950" };
  return <span className={`absolute flex h-6 w-6 -translate-x-1/2 translate-y-1/2 items-center justify-center rounded-full text-[9px] font-bold shadow ${classes[tone]}`} style={{ left: `${8 + Math.max(0, Math.min(1, x)) * 84}%`, bottom: `${8 + Math.max(0, Math.min(1, y)) * 80}%` }} title={title}>{label}</span>;
}

function CandidateLeaderboard({ results, problemType, sortMetric }: { results: RankedResult[]; problemType: ProblemType; sortMetric: string }) {
  const candidates = results.filter((row) => row.champion_eligible !== false && row.kind !== "anomaly");
  const diagnostics = results.filter((row) => row.champion_eligible === false || row.kind === "anomaly");
  const primaryLabels: Record<string, string> = { pr_auc: "PR-AUC", auc: "ROC-AUC", ks: "KS", f1: "F1", recall: "Recall", rmse: "RMSE", mae: "MAE", r2: "R-squared" };
  const primaryLabel = primaryLabels[sortMetric] ?? sortMetric.replace(/_/g, " ");
  const values = candidates.map((row) => metricValue(row, sortMetric)).filter((value): value is number => value !== null);
  const minimum = values.length ? Math.min(...values) : 0;
  const maximum = values.length ? Math.max(...values) : 0;
  const ascending = ["rmse", "mae", "mse"].includes(sortMetric);
  const rankWidth = (row: RankedResult, index: number) => {
    const value = metricValue(row, sortMetric);
    if (value === null) return 0;
    if (maximum === minimum) return Math.max(35, 100 - index * 8);
    const normalized = ascending ? (maximum - value) / (maximum - minimum) : (value - minimum) / (maximum - minimum);
    return 35 + normalized * 65;
  };

  if (!results.length) return <div className="flex min-h-40 items-center justify-center rounded-xl border border-dashed border-slate-300 bg-slate-50 text-sm text-slate-500">No model results are available yet.</div>;

  return (
    <div className="space-y-4">
      <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
        <Metric label="Candidate models" value={candidates.length} tone={candidates.length ? "success" : "warning"} />
        <Metric label="Current leader" value={candidates[0]?.name ? cleanModelLabel(candidates[0].name) : "No eligible candidate"} />
        <Metric label={`Leading ${primaryLabel}`} value={formatMetric(metricValue(candidates[0] ?? ({} as RankedResult), sortMetric))} />
        <Metric label="Targetless diagnostics" value={diagnostics.length} />
      </div>
      {candidates.length ? (
        <CandidateComparisonVisuals
          candidates={candidates}
          problemType={problemType}
          primaryMetric={sortMetric}
        />
      ) : null}

      {candidates.length ? (
        <div className="overflow-auto rounded-xl border border-slate-200 bg-white shadow-sm">
          <table className="w-full min-w-[1080px] border-separate border-spacing-0 text-xs">
            <thead className="sticky top-0 z-20 bg-slate-950 text-white shadow-sm"><tr><th className="sticky left-0 z-30 min-w-64 border-b border-slate-800 bg-slate-950 px-4 py-3 text-left text-[10px] font-semibold uppercase tracking-wide text-slate-200">Ranked candidate</th><th className="min-w-44 border-b border-slate-800 px-4 py-3 text-left text-[10px] font-semibold uppercase tracking-wide text-slate-200">{primaryLabel}</th><th className="min-w-48 border-b border-slate-800 px-4 py-3 text-left text-[10px] font-semibold uppercase tracking-wide text-slate-200">{problemType === "classification" ? "Discrimination" : "Error"}</th><th className="min-w-48 border-b border-slate-800 px-4 py-3 text-left text-[10px] font-semibold uppercase tracking-wide text-slate-200">{problemType === "classification" ? "Operating metrics" : "Model fit"}</th><th className="min-w-40 border-b border-slate-800 px-4 py-3 text-left text-[10px] font-semibold uppercase tracking-wide text-slate-200">Probability treatment</th><th className="min-w-28 border-b border-slate-800 px-4 py-3 text-left text-[10px] font-semibold uppercase tracking-wide text-slate-200">Runtime</th><th className="min-w-52 border-b border-slate-800 px-4 py-3 text-left text-[10px] font-semibold uppercase tracking-wide text-slate-200">Review state</th></tr></thead>
            <tbody>{candidates.map((row, index) => {
              const definition = MODEL_DEFINITIONS.find((model) => model.key === row.key);
              return (
                <tr key={row.key} className={`${index === 0 ? "bg-blue-50/80" : "even:bg-slate-50/70"} group hover:bg-blue-50`}>
                  <td className={`sticky left-0 z-10 border-b border-slate-100 px-4 py-3 ${index === 0 ? "bg-blue-50 group-hover:bg-blue-50" : "bg-white group-even:bg-slate-50 group-hover:bg-blue-50"}`}><div className="flex items-center gap-3"><span className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-xs font-bold ${index === 0 ? "bg-blue-700 text-white" : "border border-slate-200 bg-white text-slate-700"}`}>{index + 1}</span><div><div className="font-semibold text-slate-950">{cleanModelLabel(row.name)}</div><div className="mt-1 flex flex-wrap gap-1.5"><span className="rounded-full border border-slate-200 bg-white px-2 py-0.5 text-[10px] font-semibold text-slate-600">{definition?.family ?? "Model"}</span><span className="rounded-full border border-slate-200 bg-white px-2 py-0.5 text-[10px] font-semibold text-slate-600">{definition?.interpretability ?? "Review"} interpretability</span><span className="rounded-full border border-slate-200 bg-white px-2 py-0.5 text-[10px] font-semibold text-slate-600">{modelComplexity(definition)} complexity</span></div></div></div></td>
                  <td className="border-b border-slate-100 px-4 py-3"><div className="font-mono text-base font-semibold text-slate-950">{formatMetric(metricValue(row, sortMetric))}</div><div className="mt-2 h-1.5 overflow-hidden rounded-full bg-slate-100"><div className="h-full rounded-full bg-blue-600" style={{ width: `${rankWidth(row, index)}%` }} /></div><div className="mt-1 text-[10px] uppercase text-slate-500">{ascending ? "Lower is better" : "Higher is better"}</div></td>
                  {problemType === "classification" ? <><td className="border-b border-slate-100 px-4 py-3"><LeaderboardMetricGrid rows={[["ROC-AUC", row.auc], ["PR-AUC", row.pr_auc], ["KS", row.ks]]} /></td><td className="border-b border-slate-100 px-4 py-3"><LeaderboardMetricGrid rows={[["Precision", row.precision], ["Recall", row.recall], ["F1", row.f1]]} /></td></> : <><td className="border-b border-slate-100 px-4 py-3"><LeaderboardMetricGrid rows={[["RMSE", row.rmse], ["MAE", row.mae]]} /></td><td className="border-b border-slate-100 px-4 py-3"><LeaderboardMetricGrid rows={[["R-squared", row.r2], ["Adjusted", row.adjusted_r2]]} /></td></>}
                  <td className="border-b border-slate-100 px-4 py-3">{row.calibration_applied ? <span className="inline-flex rounded-full border border-emerald-200 bg-emerald-50 px-2.5 py-1 text-[10px] font-semibold uppercase text-emerald-800">{row.calibration_method ?? "Applied"}</span> : <span className="inline-flex rounded-full border border-slate-200 bg-slate-100 px-2.5 py-1 text-[10px] font-semibold uppercase text-slate-600">Not applied</span>}</td>
                  <td className="border-b border-slate-100 px-4 py-3 font-mono font-semibold text-slate-800">{typeof row.runtime_ms === "number" ? `${(row.runtime_ms / 1000).toFixed(1)} s` : "N/A"}</td>
                  <td className="border-b border-slate-100 px-4 py-3"><span className={`inline-flex rounded-full border px-2.5 py-1 text-[10px] font-semibold uppercase ${index === 0 ? "border-blue-200 bg-blue-50 text-blue-800" : "border-slate-200 bg-slate-100 text-slate-700"}`}>{row.candidate_status ?? (row.candidate_champion ? "Candidate leader" : "Challenger")}</span><div className="mt-1.5 text-[11px] leading-4 text-slate-500"><strong>Governance:</strong> candidate evidence persisted.<br /><strong>Approval:</strong> not approved until downstream Evaluation / Validation.</div></td>
                </tr>
              );
            })}</tbody>
          </table>
        </div>
      ) : <AtlasAttentionPanel title="No champion-eligible model has completed" tone="warning">Targetless anomaly diagnostics cannot become the supervised champion. Complete at least one compatible supervised model.</AtlasAttentionPanel>}

      {diagnostics.length ? (
        <details className="rounded-xl border border-violet-200 bg-violet-50/60">
          <summary className="cursor-pointer list-none px-4 py-3"><div className="flex items-center justify-between gap-3"><div><div className="text-sm font-semibold text-violet-950">Targetless diagnostic runs</div><div className="mt-1 text-xs text-violet-800">Supplemental anomaly evidence is reported separately and is never ranked as the supervised champion.</div></div><span className="rounded-full border border-violet-200 bg-white px-2.5 py-1 text-xs font-semibold text-violet-800">{diagnostics.length}</span></div></summary>
          <div className="grid gap-2 border-t border-violet-200 p-4 md:grid-cols-2">{diagnostics.map((row) => <div key={row.key} className="rounded-lg border border-violet-200 bg-white p-3"><div className="flex items-start justify-between gap-3"><div><div className="text-sm font-semibold text-slate-950">{cleanModelLabel(row.name)}</div><div className="mt-1 text-xs text-slate-500">{row.target_usage ?? "Target not used"}</div></div><span className="rounded-full bg-violet-100 px-2 py-1 text-[10px] font-semibold uppercase text-violet-800">Diagnostic only</span></div><div className="mt-3 text-xs text-slate-600">Runtime <span className="font-mono font-semibold text-slate-900">{typeof row.runtime_ms === "number" ? `${(row.runtime_ms / 1000).toFixed(1)} s` : "N/A"}</span></div></div>)}</div>
        </details>
      ) : null}
    </div>
  );
}

function LeaderboardMetricGrid({ rows }: { rows: Array<[string, number | null | undefined]> }) {
  return <div className="grid grid-cols-3 gap-2">{rows.map(([label, value]) => <div key={label} className="min-w-0"><div className="truncate text-[9px] font-semibold uppercase text-slate-500" title={label}>{label}</div><div className="mt-0.5 font-mono font-semibold text-slate-900">{formatMetric(value)}</div></div>)}</div>;
}

function ModelCard({ model, selected, enabled, unavailableReason, execution, tuning, onToggle, disabled, compact, recommended }: { model: ModelDefinition; selected: boolean; enabled: boolean; unavailableReason?: string; execution?: ModelExecution; tuning: string; onToggle: () => void; disabled: boolean; compact: boolean; recommended: boolean }) {
  const successful = execution?.status === "complete";
  const failed = execution?.status === "failed";
  const classes = successful ? "border-emerald-300 bg-emerald-50" : failed ? "border-red-300 bg-red-50" : selected ? "border-blue-600 bg-blue-50" : "border-slate-200 bg-white";
  return <div className={`rounded-lg border p-4 ${classes} ${!enabled ? "opacity-70" : ""}`}><div className="flex items-start justify-between gap-3"><div className="min-w-0"><div className="flex flex-wrap items-center gap-2"><h4 className="text-sm font-semibold text-slate-950">{cleanModelLabel(model.label)}</h4>{recommended ? <span className="rounded-full bg-blue-100 px-2 py-0.5 text-[10px] font-bold uppercase text-blue-800">Recommended</span> : null}{model.kind === "anomaly" ? <span className="rounded-full border border-violet-200 bg-violet-50 px-2 py-0.5 text-[10px] font-semibold uppercase text-violet-800">Targetless fit | diagnostic only</span> : null}{execution ? <MiniStatus state={execution.status} /> : null}</div><p className="mt-1 text-xs leading-5 text-slate-600">{model.purpose}</p></div><label className="relative inline-flex shrink-0 items-center"><input type="checkbox" className="peer sr-only" checked={selected} disabled={disabled || !enabled} onChange={onToggle} /><span className="h-6 w-11 rounded-full bg-slate-300 after:absolute after:left-0.5 after:top-0.5 after:h-5 after:w-5 after:rounded-full after:bg-white after:transition peer-checked:bg-blue-600 peer-checked:after:translate-x-5 peer-disabled:cursor-not-allowed" /></label></div>{!enabled ? <div className="mt-3 flex items-start gap-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900"><AlertTriangle size={14} className="mt-0.5 shrink-0" />{unavailableReason ?? "This model is not compatible with the active project."}</div> : compact ? <div className="mt-3 flex flex-wrap gap-1.5 text-[10px] font-semibold text-slate-600"><span className="rounded-full bg-slate-100 px-2 py-1">{model.interpretability} interpretability</span><span className="rounded-full bg-slate-100 px-2 py-1">{model.scaling}</span><span className="rounded-full bg-slate-100 px-2 py-1">{tuning}</span></div> : <div className="mt-3 grid grid-cols-2 gap-x-4 gap-y-2 text-xs text-slate-600"><div><b className="text-slate-800">Best use:</b> {model.bestUse}</div><div><b className="text-slate-800">Interpretability:</b> {model.interpretability}</div><div><b className="text-slate-800">Scaling:</b> {model.scaling}</div><div><b className="text-slate-800">Categorical:</b> {model.categorical}</div><div><b className="text-slate-800">Probability:</b> {model.probability}</div><div><b className="text-slate-800">Tuning:</b> {tuning}</div></div>}</div>;
}

function ExecutionCard({ label, status, history }: { label: string; status?: ModelExecution; history?: Array<{ state: ModelState; at: string; stage: string; message?: string }> }) {
  const state = status?.status ?? "queued";
  return <div className={`rounded-lg border p-4 ${state === "complete" ? "border-emerald-200 bg-emerald-50" : state === "failed" ? "border-red-200 bg-red-50" : state === "running" || state === "preparing" ? "border-blue-300 bg-blue-50" : "border-slate-200 bg-white"}`}><div className="flex items-center justify-between gap-2"><div className="font-semibold text-slate-950">{label}</div><MiniStatus state={state} /></div><div className="mt-2 text-sm text-slate-700">{status?.current_stage ?? "Waiting for worker"}</div><div className="mt-1 text-xs text-slate-500">{status?.message ?? "Queued for training."}{typeof status?.runtime_ms === "number" && status.runtime_ms > 0 ? ` Runtime ${(status.runtime_ms / 1000).toFixed(1)} s.` : ""}</div>{state === "running" && status?.fold_progress_available === false ? <div className="mt-2 rounded-md border border-blue-200 bg-white/70 px-2 py-1 text-[10px] text-blue-900">Per-fold and tuning-candidate callbacks are unavailable from this estimator; ATLAS reports the approved batch plan and final persisted search summary.</div> : null}{status?.warning ? <div className="mt-2 text-xs font-medium text-amber-800">{status.warning}</div> : null}{history?.length ? <details className="mt-3"><summary className="cursor-pointer text-xs font-semibold text-slate-600">Execution history</summary><ol className="mt-2 space-y-1 border-l border-slate-300 pl-3 text-xs text-slate-600">{history.map((item, index) => <li key={`${item.at}-${index}`}><b>{item.state}</b> | {item.stage} | {new Date(item.at).toLocaleTimeString()}</li>)}</ol></details> : null}</div>;
}

function MiniStatus({ state }: { state: ModelState }) {
  const config: Record<ModelState, { icon: typeof Clock3; label: string; classes: string }> = {
    queued: { icon: Clock3, label: "Queued", classes: "bg-slate-100 text-slate-700" },
    preparing: { icon: LoaderCircle, label: "Preparing", classes: "bg-blue-100 text-blue-800" },
    running: { icon: Activity, label: "Running", classes: "bg-blue-100 text-blue-800" },
    complete: { icon: CheckCircle2, label: "Complete", classes: "bg-emerald-100 text-emerald-800" },
    failed: { icon: XCircle, label: "Failed", classes: "bg-red-100 text-red-800" },
    cancelled: { icon: CircleStop, label: "Cancelled", classes: "bg-slate-100 text-slate-700" },
    interrupted: { icon: AlertTriangle, label: "Interrupted", classes: "bg-amber-100 text-amber-900" },
  };
  const selected = config[state];
  const Icon = selected.icon;
  return <span className={`inline-flex items-center gap-1 rounded-full px-2 py-1 text-[10px] font-semibold uppercase ${selected.classes}`}><Icon size={12} className={state === "preparing" || state === "running" ? "animate-spin" : ""} />{selected.label}</span>;
}

function Metric({ label, value, tone = "neutral" }: { label: string; value: string | number; tone?: "neutral" | "success" | "warning" }) {
  const classes = tone === "success" ? "border-emerald-200 bg-emerald-50" : tone === "warning" ? "border-amber-200 bg-amber-50" : "border-slate-200 bg-slate-50";
  return <div className={`min-w-0 rounded-lg border p-3 ${classes}`}><div className="text-[10px] font-semibold uppercase text-slate-500">{label}</div><div className="mt-1 truncate text-sm font-semibold text-slate-950" title={String(value)}>{value}</div></div>;
}
