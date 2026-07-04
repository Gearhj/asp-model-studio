// src/steps/Step06_Train.tsx

import React, { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { logDecision } from "../lib/decisionJournal";
import { recordTrainingExperiments } from "../lib/experimentTracking";
import { inferLocalProblemType, loadLocalDataset } from "../lib/localDataset";
import { saveActiveProjectBeforeNavigation } from "../lib/localProjects";
import { useWorkflowStore } from "../state/useWorkflowStore";
import StepPythonPanel from "../components/StepPythonPanel";

const API_BASE =
  import.meta.env.VITE_API_BASE?.replace(/\/$/, "") || "http://127.0.0.1:8001/api";
const LOCAL_TRAINING_SUMMARY_KEY = "modeling-tool-training-summary";
const LOCAL_TRAINING_CONFIG_KEY = "modeling-tool-training-config";

type Status = "idle" | "pending" | "done" | "error";

type AvailabilityResponse = {
  ok: boolean;
  availability?: Record<string, boolean>;
  labels?: Record<string, string>;
  error?: string;
};

type TrainResponse = {
  ok?: boolean;
  status?: string;
  models?: string[];
  rows?: number;
  error?: string;
  detail?: string;
  summary?: {
    problem_type?: ProblemType;
    ranked?: RankedRow[];
    failed?: { key: string; name?: string; error?: string }[];
  };
  // backend may also persist a summary, but we read that via /train/last
};

type ProblemType = "classification" | "regression";

// Shape of rows returned by /train/last -> summary.ranked
type RankedRow = {
  key: string;
  name: string;
  task?: ProblemType | "anomaly";
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
  best_score?: number | null;
};

// ---------------------------------------------------------------------------
// Model catalogue
// ---------------------------------------------------------------------------

type ModelKey =
  | "logreg"
  | "dtree"
  | "ebm"
  | "rf"
  | "xgb"
  | "cat"
  | "lgbm"
  | "knn"
  | "linsvm"
  | "iso"
  | "autoreg"
  | "mlp"
  | "linreg"
  | "rf_reg"
  | "xgb_reg"
  | "lgbm_reg"
  | "cat_reg";

type ModelDef = {
  key: ModelKey;
  label: string;
  tooltip?: string;
  requiresBackendPackage?: boolean;
};

type GroupDef = {
  id: string;
  title: string;
  task: ProblemType | "classification";
  models: ModelDef[];
};

const MODEL_GROUPS: GroupDef[] = [
  {
    id: "transparent",
    title: "Transparent Models",
    task: "classification",
    models: [
      { key: "logreg", label: "Logistic Regression", tooltip: "Transparent baseline for classification. Use when interpretability, odds ratios, or regulatory review matter." },
      { key: "dtree", label: "Decision Tree", tooltip: "Rule-based classifier. Use when simple split logic is valuable and modest performance tradeoffs are acceptable." },
      { key: "ebm", label: "Explainable Boosting Machine (EBM)", tooltip: "Interpretable boosting model. Use when you need nonlinear performance with clear feature-shape explanations." },
    ],
  },
  {
    id: "ensemble",
    title: "Ensemble Models (Black Box)",
    task: "classification",
    models: [
      { key: "rf", label: "Random Forest", tooltip: "Robust ensemble baseline. Use when nonlinear feature interactions are likely and interpretability is secondary." },
      { key: "xgb", label: "XGBoost", tooltip: "Gradient-boosted trees. Use for high-performing challenger models with careful validation and tuning." },
      { key: "cat", label: "CatBoost", tooltip: "Boosting model with strong categorical handling. Use when categorical predictors are important." },
      { key: "lgbm", label: "LightGBM", tooltip: "Fast gradient boosting. Use for larger tabular datasets and challenger benchmarking." },
    ],
  },
  {
    id: "distance",
    title: "Distance Based",
    task: "classification",
    models: [
      { key: "knn", label: "K-Nearest Neighbors", tooltip: "Distance-based classifier. Use when local similarity is meaningful and features are scaled." },
      { key: "linsvm", label: "Linear SVM (Calibrated)", tooltip: "Margin-based linear classifier. Use with many standardized features and calibration for probabilities." },
    ],
  },
  {
    id: "anomaly",
    title: "Anomaly Detection Models",
    task: "classification",
    models: [
      { key: "iso", label: "Isolation Forest (Anomaly)", tooltip: "Unsupervised anomaly detector. Use as a supplemental rare-pattern screen, not as a standard supervised champion." },
      { key: "autoreg", label: "Autoregression (Anomaly)", tooltip: "Time-aware anomaly baseline. Use when sequential behavior or monitoring drift is central." },
    ],
  },
  {
    id: "nn",
    title: "Neural Network",
    task: "classification",
    models: [{ key: "mlp", label: "Neural Net (MLP)", tooltip: "Feed-forward neural network. Use as a black-box challenger when sample size and governance controls are sufficient." }],
  },
  {
    id: "regression-transparent",
    title: "Regression Models",
    task: "regression",
    models: [
      { key: "linreg", label: "Linear Regression", tooltip: "Transparent regression baseline. Use when coefficients, residuals, and auditability matter." },
      { key: "rf_reg", label: "Random Forest Regressor", tooltip: "Nonlinear ensemble regressor. Use when interactions are likely and prediction accuracy matters." },
      { key: "xgb_reg", label: "XGBoost Regressor", tooltip: "Gradient-boosted regression model. Use as a high-performance challenger with tuning." },
      { key: "lgbm_reg", label: "LightGBM Regressor", tooltip: "Fast boosted regression model. Use for larger tabular data and challenger benchmarking." },
      { key: "cat_reg", label: "CatBoost Regressor", tooltip: "Boosted regression model with categorical support. Use when categorical features carry signal." },
    ],
  },
];

const DEFAULT_SELECTION: Partial<Record<ModelKey, boolean>> = {
  logreg: true,
  rf: true,
  xgb: false,
  cat: false,
  lgbm: false,
};

const DEFAULT_REGRESSION_SELECTION: Partial<Record<ModelKey, boolean>> = {
  linreg: true,
  rf_reg: true,
  xgb_reg: false,
  lgbm_reg: false,
  cat_reg: false,
};

type TrainingUiState = {
  problem_type?: ProblemType | null;
  selected_map?: Partial<Record<ModelKey, boolean>>;
  grid_search?: boolean;
  search_depth?: "quick" | "balanced" | "thorough";
  calibration?: boolean;
  max_parallel_models?: number;
  use_pca?: boolean;
};

const gridSearchGuidance: Record<"quick" | "balanced" | "thorough", string> = {
  quick: "Definition: small parameter search. Use for fast baseline comparison or when runtime matters. Example: first challenger benchmark.",
  balanced: "Definition: moderate parameter search. Use when selecting a serious champion and runtime is acceptable.",
  thorough: "Definition: deeper parameter search. Use when final performance matters and compute time is justified by governance impact.",
};

const ALL_MODEL_KEYS = MODEL_GROUPS.flatMap((group) => group.models.map((model) => model.key));
const OPTIONAL_MODEL_KEYS = new Set<ModelKey>(["ebm", "xgb", "cat", "lgbm", "linsvm", "iso", "autoreg", "mlp", "xgb_reg", "lgbm_reg", "cat_reg"]);

function readTrainingUiState(): TrainingUiState {
  if (typeof localStorage === "undefined") return {};
  try {
    const parsed = JSON.parse(localStorage.getItem(LOCAL_TRAINING_CONFIG_KEY) || "{}") as TrainingUiState;
    return parsed && typeof parsed === "object" ? parsed : {};
  } catch {
    return {};
  }
}

function normalizeSelectedMap(map: unknown): Partial<Record<ModelKey, boolean>> | null {
  if (!map || typeof map !== "object") return null;
  const normalized: Partial<Record<ModelKey, boolean>> = {};
  ALL_MODEL_KEYS.forEach((key) => {
    if (Object.prototype.hasOwnProperty.call(map, key)) {
      normalized[key] = Boolean((map as Record<string, unknown>)[key]);
    }
  });
  return Object.keys(normalized).length ? normalized : null;
}

function buildDefaultSelected(problemType: ProblemType | null) {
  const init = Object.fromEntries(ALL_MODEL_KEYS.map((key) => [key, false])) as Record<ModelKey, boolean>;
  const defaults = problemType === "regression" ? DEFAULT_REGRESSION_SELECTION : DEFAULT_SELECTION;
  (Object.keys(defaults) as ModelKey[]).forEach((key) => {
    init[key] = !!defaults[key];
  });
  return init;
}

function buildInitialSelected(problemType: ProblemType | null) {
  const saved = readTrainingUiState();
  const savedMap = normalizeSelectedMap(saved.selected_map);
  const init = buildDefaultSelected(problemType);
  if (savedMap && (!saved.problem_type || !problemType || saved.problem_type === problemType)) {
    ALL_MODEL_KEYS.forEach((key) => {
      if (Object.prototype.hasOwnProperty.call(savedMap, key)) {
        init[key] = !!savedMap[key];
      }
    });
  }
  return init;
}

function coercePositiveInt(value: unknown, fallback: number) {
  const numeric = Number(value);
  return Number.isFinite(numeric) && numeric > 0 ? Math.floor(numeric) : fallback;
}

function inferTarget(headers: string[], current?: string | null) {
  if (current && headers.includes(current)) return current;
  return (
    headers.find((h) => /^(fraud|label|target|class|y|bad|default|outcome|response|event)$/i.test(h)) ??
    headers.find((h) => /target/i.test(h)) ??
    headers[headers.length - 1] ??
    ""
  );
}

function inferProblemTypeFromLocalDataset(): ProblemType | null {
  const localDataset = loadLocalDataset();
  const explicitType = inferLocalProblemType(localDataset);
  if (explicitType) return explicitType;
  if (!localDataset?.rows.length) return null;
  const target = inferTarget(localDataset.headers, localDataset.target);
  if (!target) return null;

  const values = localDataset.rows
    .map((row) => row[target])
    .filter((value) => value !== null && value !== undefined && String(value).trim() !== "");
  if (!values.length) return null;

  const numericValues = values.map((value) => Number(value));
  const numericCount = numericValues.filter((value) => Number.isFinite(value)).length;
  const uniqueCount = new Set(values.map((value) => String(value))).size;
  if (numericCount / values.length >= 0.9 && uniqueCount > 10) return "regression";
  return "classification";
}

// ---------------------------------------------------------------------------
// Small UI helpers
// ---------------------------------------------------------------------------

function StatusPill({ status }: { status: Status }) {
  if (status === "pending") {
    return (
      <span className="ml-2 inline-flex items-center rounded-full border border-indigo-200 bg-indigo-50 px-2 py-0.5 text-xs font-medium text-indigo-700">
        Pending…
      </span>
    );
  }
  if (status === "done") {
    return (
      <span className="ml-2 inline-flex items-center rounded-full border border-emerald-200 bg-emerald-50 px-2 py-0.5 text-xs font-medium text-emerald-700">
        Done
      </span>
    );
  }
  if (status === "error") {
    return (
      <span className="ml-2 inline-flex items-center rounded-full border border-rose-200 bg-rose-50 px-2 py-0.5 text-xs font-medium text-rose-700">
        Error
      </span>
    );
  }
  return null;
}

function Toggle({
  checked,
  disabled,
  onChange,
}: {
  checked: boolean;
  disabled?: boolean;
  onChange: () => void;
}) {
  const base =
    "relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-150 ease-in-out";
  const enabled = checked ? "bg-indigo-600" : "bg-gray-200";
  const knob =
    "pointer-events-none inline-block h-4 w-4 transform rounded-full bg-white shadow ring-0 transition duration-150 ease-in-out" +
    (checked ? " translate-x-4" : " translate-x-0");

  return (
    <button
      type="button"
      onClick={disabled ? undefined : onChange}
      className={`${base} ${enabled} ${disabled ? "opacity-40 cursor-not-allowed" : ""}`}
    >
      <span className="sr-only">Toggle</span>
      <span className={knob} />
    </button>
  );
}

function formatParams(params?: Record<string, unknown> | null) {
  if (!params || !Object.keys(params).length) return "-";
  return Object.entries(params)
    .map(([key, value]) => `${key}: ${String(value)}`)
    .join(", ");
}

function formatMetric(value?: number, digits = 4) {
  return typeof value === "number" && Number.isFinite(value) ? value.toFixed(digits) : "-";
}

function displayModelName(name: string) {
  return name.replace(/\s*\(k\s*=\s*\d+\)/i, "");
}

function saveLocalTrainingSummary(summary: { ranked?: RankedRow[]; problem_type?: ProblemType } | undefined) {
  if (!summary?.ranked?.length) return;
  try {
    sessionStorage.setItem(
      LOCAL_TRAINING_SUMMARY_KEY,
      JSON.stringify({
        problem_type: summary.problem_type,
        ranked: summary.ranked.slice(0, 25),
        saved_at: new Date().toISOString(),
      })
    );
  } catch {
    // Evaluation can still read from the backend if session storage is unavailable.
  }
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export default function Step06_Train() {
  const navigate = useNavigate();
  const markComplete = useWorkflowStore((state) => state.markComplete);
  const initialProblemType = inferProblemTypeFromLocalDataset();
  const savedTrainingUiState = readTrainingUiState();

  const [kFolds, setKFolds] = useState<number>(5);
  const [maxParallel, setMaxParallel] = useState<number>(() => coercePositiveInt(savedTrainingUiState.max_parallel_models, 2));
  const [calibrate, setCalibrate] = useState<boolean>(() => savedTrainingUiState.calibration ?? true);
  const [usePCA, setUsePCA] = useState<boolean>(() => savedTrainingUiState.use_pca ?? false);
  const [useGridSearch, setUseGridSearch] = useState<boolean>(() => savedTrainingUiState.grid_search ?? false);
  const [gridSearchLevel, setGridSearchLevel] = useState<"quick" | "balanced" | "thorough">(
    () => savedTrainingUiState.search_depth ?? "quick"
  );

  const [selected, setSelected] = useState<Record<ModelKey, boolean>>(() => {
    return buildInitialSelected(initialProblemType);
  });

  const [status, setStatus] = useState<Record<ModelKey, Status>>(
    () =>
      Object.fromEntries(ALL_MODEL_KEYS.map((key) => [key, "idle"])) as Record<ModelKey, Status>
  );

  const [availability, setAvailability] = useState<Partial<Record<ModelKey, boolean>>>({});
  const [availabilityLoaded, setAvailabilityLoaded] = useState(false);
  const [labels, setLabels] = useState<Partial<Record<ModelKey, string>>>({});
  const [isTraining, setIsTraining] = useState(false);
  const [message, setMessage] = useState<string | null>(
    "Models are trained on the full development dataset. Classification runs show AUC/PR-AUC/F1; regression runs show RMSE/MAE/R-squared. Detailed diagnostics appear in Step 8: Evaluation."
  );

  // NEW: summary of last training run (metrics per model)
  const [summary, setSummary] = useState<RankedRow[] | null>(null);
  const [problemType, setProblemType] = useState<ProblemType | null>(() => initialProblemType);

  const visibleGroups = useMemo(
    () => MODEL_GROUPS.filter((group) => !problemType || group.task === problemType),
    [problemType]
  );
  const visibleModelKeys = useMemo(
    () => new Set(visibleGroups.flatMap((group) => group.models.map((model) => model.key))),
    [visibleGroups]
  );

  const selectedModels = useMemo(
    () => (Object.keys(selected) as ModelKey[]).filter((k) => selected[k] && visibleModelKeys.has(k)),
    [selected, visibleModelKeys]
  );
  const selectableModelKeys = useMemo(() => {
    const keys = new Set<ModelKey>();
    visibleGroups.forEach((group) => {
      group.models.forEach((model) => {
        keys.add(model.key);
      });
    });
    return keys;
  }, [visibleGroups]);
  const canGoToEvaluation =
    !isTraining &&
    selectedModels.every((model) => status[model] !== "pending") &&
    (Object.values(status).some((value) => value === "done") || (summary?.length ?? 0) > 0) &&
    (summary?.length ?? 0) > 0;

  const isRegressionSummary =
    problemType === "regression" ||
    (!problemType &&
      !!summary?.some(
        (row) =>
          row.task === "regression" ||
          typeof row.rmse === "number" ||
          typeof row.mae === "number" ||
          typeof row.r2 === "number"
      ));

  useEffect(() => {
    try {
      const modelLabels = Object.fromEntries(
        selectedModels.map((key) => {
          const def = MODEL_GROUPS.flatMap((group) => group.models).find((model) => model.key === key);
          return [key, displayModelName(labels[key] ?? def?.label ?? key)];
        })
      );
      localStorage.setItem(
        LOCAL_TRAINING_CONFIG_KEY,
        JSON.stringify({
          problem_type: problemType,
          selected_map: selected,
          selected_models: selectedModels,
          selected_model_labels: modelLabels,
          grid_search: useGridSearch,
          search_depth: gridSearchLevel,
          calibration: calibrate,
          max_parallel_models: maxParallel,
          use_pca: usePCA,
          training_summary: summary?.slice(0, 25) ?? [],
          updated_at: new Date().toISOString(),
        })
      );
    } catch {
      // Training configuration remains visible in the UI if browser persistence is unavailable.
    }
  }, [problemType, selected, selectedModels, labels, useGridSearch, gridSearchLevel, calibrate, maxParallel, usePCA, summary]);

  const toggleModelSelection = (model: ModelDef) => {
    logDecision({
      workflowStep: "Model Training",
      actionType: "model_selected",
      subject: model.label,
      previousValue: selected[model.key] ? "selected" : "not selected",
      newValue: !selected[model.key] ? "selected" : "not selected",
    });
    setSelected((prev) => ({ ...prev, [model.key]: !prev[model.key] }));
  };

  // -------------------------------------------------------------------------
  // Helper: fetch last training summary from backend
  // -------------------------------------------------------------------------

  async function fetchLastSummary() {
    const localProblemType = inferProblemTypeFromLocalDataset();
    try {
      const res = await fetch(`${API_BASE}/train/last`);
      if (!res.ok) {
        setSummary([]);
        return;
      }
      const j = await res.json();
      const ranked = j?.summary?.ranked;
      if (Array.isArray(ranked)) {
        setSummary(ranked as RankedRow[]);
        const nextProblemType =
          j?.summary?.problem_type ??
          (ranked.some((row: RankedRow) => row.task === "regression" || row.rmse !== undefined)
            ? "regression"
            : ranked.length
              ? "classification"
              : null);
        if (
          localProblemType &&
          nextProblemType &&
          localProblemType !== nextProblemType
        ) {
          setSummary([]);
          setProblemType(localProblemType);
          setMessage(
            `Loaded a ${localProblemType} dataset. Prior ${nextProblemType} training results were cleared from this view; train the selected ${localProblemType} models to refresh the leaderboard.`
          );
          return;
        }
        if (nextProblemType === "classification" || nextProblemType === "regression") {
          setProblemType(nextProblemType);
        }
      } else {
        setSummary([]);
      }
    } catch {
      // don't blow up UI if summary is missing
      setSummary([]);
    }
  }

  // Load any existing last-run summary on mount (optional)
  useEffect(() => {
    fetchLastSummary();
  }, []);

  useEffect(() => {
    const refreshProblemType = () => {
      const nextProblemType = inferProblemTypeFromLocalDataset();
      if (!nextProblemType) return;
      setProblemType(nextProblemType);
      setSummary([]);
      setMessage(`Loaded a ${nextProblemType} dataset. Train the selected ${nextProblemType} models to refresh the leaderboard.`);
    };
    window.addEventListener("atlas-dataset-updated", refreshProblemType);
    window.addEventListener("storage", refreshProblemType);
    refreshProblemType();
    return () => {
      window.removeEventListener("atlas-dataset-updated", refreshProblemType);
      window.removeEventListener("storage", refreshProblemType);
    };
  }, []);

  useEffect(() => {
    if (!problemType) return;

    const defaults =
      problemType === "regression" ? DEFAULT_REGRESSION_SELECTION : DEFAULT_SELECTION;
    const saved = readTrainingUiState();
    const savedMap = normalizeSelectedMap(saved.selected_map);
    const hasSavedSelectionForProblem = !!savedMap && (!saved.problem_type || saved.problem_type === problemType);
    const allowedKeys = new Set(
      MODEL_GROUPS.filter((group) => group.task === problemType).flatMap((group) =>
        group.models.map((model) => model.key)
      )
    );

    setSelected((prev) => {
      if (hasSavedSelectionForProblem) {
        const next = { ...buildDefaultSelected(problemType) };
        (Object.keys(next) as ModelKey[]).forEach((key) => {
          next[key] = allowedKeys.has(key) && !!savedMap?.[key];
        });
        return next;
      }
      const hasAllowedSelection = (Object.keys(prev) as ModelKey[]).some(
        (key) => allowedKeys.has(key) && prev[key]
      );
      const next = { ...prev };
      (Object.keys(next) as ModelKey[]).forEach((key) => {
        if (!allowedKeys.has(key)) next[key] = false;
      });
      if (!hasAllowedSelection) {
        (Object.keys(defaults) as ModelKey[]).forEach((key) => {
          next[key] = !!defaults[key];
        });
      }
      return next;
    });
  }, [problemType]);

  // -------------------------------------------------------------------------
  // Load model availability / labels
  // -------------------------------------------------------------------------

  useEffect(() => {
    let alive = true;

    fetch(`${API_BASE}/models/availability`)
      .then((res) => res.json() as Promise<AvailabilityResponse>)
      .then((j) => {
        if (!alive) return;
        if (!j.ok) {
          setMessage(j.error ?? "Could not load model availability from the backend.");
          return;
        }

        const avail = (j.availability ?? {}) as Record<ModelKey, boolean>;
        const lbls = (j.labels ?? {}) as Record<ModelKey, string>;
        setAvailability(avail);
        setAvailabilityLoaded(true);
        setLabels(lbls);
        setMessage("Backend reports algorithm availability successfully. Training will fit real models.");
      })
      .catch((err) => {
        if (!alive) return;
        setAvailabilityLoaded(false);
        setMessage(
          "Backend model availability is unavailable. Core model toggles remain selectable, but training requires the FastAPI backend on port 8001."
        );
      });

    return () => {
      alive = false;
    };
  }, []);

  // -------------------------------------------------------------------------
  // Training
  // -------------------------------------------------------------------------

  async function ensureBackendDataset() {
    try {
      const columnsRes = await fetch(`${API_BASE}/columns`);
      if (columnsRes.ok) {
        const columnsJson = await columnsRes.json();
        if (Array.isArray(columnsJson?.columns) && columnsJson.columns.length > 0 && columnsJson?.target) {
          return true;
        }
      }
    } catch {
      // Fall through and try the browser cache.
    }

    const localDataset = loadLocalDataset();
    if (!localDataset?.rows.length) return false;

    setMessage("Backend dataset was empty. Reloading the browser preview sample before training. For full rare-event training, return to Data Acquisition and re-send the full uploaded file.");
    const target = inferTarget(localDataset.headers, localDataset.target);
    const syncRes = await fetch(`${API_BASE}/data/set_sample`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...localDataset, target }),
    });

    if (!syncRes.ok) return false;
    const syncJson = await syncRes.json().catch(() => null);
    return Boolean(syncJson?.ok);
  }

  async function startTraining() {
    setMessage(null);
    const startedAt = performance.now();

    const models = selectedModels;
    if (!models.length) {
      setMessage("Please select at least one model to train.");
      return;
    }

    // mark as pending
    setStatus((prev) => {
      const next = { ...prev };
      models.forEach((m) => {
        next[m] = "pending";
      });
      return next;
    });

    setIsTraining(true);

    try {
      const datasetReady = await ensureBackendDataset();
      if (!datasetReady) {
        setMessage("No dataset is loaded. Return to Data Acquisition and load a dataset first.");
        setSummary([]);
        setStatus((prev) => {
          const next = { ...prev };
          models.forEach((m) => {
            next[m] = "error";
          });
          return next;
        });
        return;
      }

      const trainSelected = () =>
        fetch(`${API_BASE}/model/train`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            models,
            k_folds: kFolds,
            max_parallel: maxParallel,
            calibrate,
            use_pca: usePCA,
            grid_search: useGridSearch,
            grid_search_level: gridSearchLevel,
          }),
        });

      let res = await trainSelected();

      if (!res.ok) {
        const firstError = await res.clone().json().catch(() => null);
        const detail = String(firstError?.detail ?? firstError?.error ?? "");
        if (/No dataset is loaded/i.test(detail)) {
          const reloaded = await ensureBackendDataset();
          if (reloaded) {
            res = await trainSelected();
          }
        }
      }

      let j: TrainResponse = {};
      try {
        j = (await res.json()) as TrainResponse;
      } catch {
        // response without JSON body
      }

      const ok = res.ok && (j.ok ?? true);

      if (!ok) {
        const errMsg =
          j.error ??
          j.detail ??
          (res.status === 400
            ? "Training request rejected by backend."
            : `Training failed (HTTP ${res.status}).`);
        setMessage(errMsg);
        setSummary([]);
        setStatus((prev) => {
          const next = { ...prev };
          models.forEach((m) => {
            next[m] = "error";
          });
          return next;
        });
        return;
      }

      const trainedKeys = new Set((j.summary?.ranked ?? []).map((row) => row.key));
      const failedRows = j.summary?.failed ?? [];
      const failedKeys = new Set(failedRows.map((row) => row.key));

      setStatus((prev) => {
        const next = { ...prev };
        (Object.keys(next) as ModelKey[]).forEach((key) => {
          if (trainedKeys.has(key)) {
            next[key] = "done";
          } else if (failedKeys.has(key)) {
            next[key] = "error";
          } else if (models.includes(key)) {
            next[key] = "idle";
          }
        });
        return next;
      });

      const responseProblemType = j.summary?.problem_type;
      if (responseProblemType === "classification" || responseProblemType === "regression") {
        setProblemType(responseProblemType);
      }
      setSummary((j.summary?.ranked ?? []) as RankedRow[]);
      saveLocalTrainingSummary(j.summary);

      const rowsInfo = j.rows ? ` on ${j.rows.toLocaleString()} rows` : "";
      const statusInfo = j.status ? ` (status: ${j.status})` : "";
      setMessage(
        failedRows.length
          ? `Training completed${rowsInfo}${statusInfo}. ${trainedKeys.size} model(s) fit successfully; ${failedRows.length} model(s) failed. Metrics below are calculated from fitted backend models.`
          : `Training completed${rowsInfo}${statusInfo}. Metrics below are calculated from fitted backend models.`
      );

      const fittedRanked = (j.summary?.ranked ?? []) as RankedRow[];
      if (fittedRanked.length) {
        void recordTrainingExperiments({
            apiBase: API_BASE,
            ranked: fittedRanked,
            selectedModelKeys: models,
            runtimeMs: performance.now() - startedAt,
            calibrated: calibrate,
            trainingSettings: {
              k_folds: kFolds,
              max_parallel: maxParallel,
              calibrate,
              use_pca: usePCA,
              grid_search: useGridSearch,
              grid_search_level: gridSearchLevel,
            },
          })
          .then((records) => {
          setMessage((current) => `${current ?? ""} Created ${records.length} experiment record(s).`);
          })
          .catch((err) => {
          console.error("Experiment capture failed:", err);
          setMessage((current) => `${current ?? ""} Experiment capture failed; training results are still available.`);
          });
      }

      // Keep the just-completed backend response as the authoritative table state.
      // A stale /train/last response can briefly clear the summary and disable Evaluation.
    } catch (err: any) {
      setMessage(
        `Training backend is unavailable. Start the FastAPI backend on port 8001 and try again. Details: ${String(
          err?.message ?? err
        )}`
      );
      setSummary([]);
      setStatus((prev) => {
        const next = { ...prev };
        models.forEach((m) => {
          next[m] = "error";
        });
        return next;
      });
    } finally {
      setIsTraining(false);
    }
  }

  // -------------------------------------------------------------------------
  // Render
  // -------------------------------------------------------------------------

  return (
    <div className="w-full space-y-6">
      <div className="rounded-2xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800">
        <div className="font-semibold">
          Front-end: <span className="font-mono">Step06_Train.tsx</span>{" "}
          <span className="mx-1">·</span> Backend: <span className="font-mono">/api/model/train</span>{" "}
          on port <span className="font-mono">8001</span>
        </div>
        <div className="mt-1">
          This step submits real training jobs to the FastAPI backend and persists metrics for Step
          8: Evaluation.
        </div>
      </div>

      <h1 className="text-2xl font-semibold">Step 7: Model Training</h1>

      {/* Split configuration */}
      <div className="rounded-2xl border border-gray-200 bg-white p-4 shadow-sm">
        <div className="flex items-center justify-between">
          <div>
            <div className="text-sm font-semibold text-gray-800">
              Data split configuration from Balancing &amp; Split
            </div>
            <div className="mt-1 text-xs text-gray-500">
              These settings control backend training behavior. Split and fold choices are managed in the prior step.
            </div>
          </div>
          <div className="text-xs rounded-full border border-indigo-100 bg-indigo-50 px-3 py-1 text-indigo-700">
            {problemType === "regression" ? "Regression" : "Classification"}
          </div>
        </div>

        <div className="mt-4 grid gap-4 md:grid-cols-3">
          <div className="space-y-1">
            <label className="block text-xs font-medium text-gray-700">Max parallel models</label>
            <input
              type="number"
              min={1}
              max={16}
              value={maxParallel}
              onChange={(e) => {
                const next = Math.max(1, Math.min(16, Number(e.target.value) || 1));
                logDecision({
                  workflowStep: "Model Training",
                  actionType: "workflow_setting_changed",
                  subject: "Max parallel models",
                  previousValue: maxParallel,
                  newValue: next,
                });
                setMaxParallel(next);
              }}
              className="w-full rounded-md border border-gray-300 px-2 py-1.5 text-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
            />
            <p className="text-[11px] text-gray-500">
              Hint: set higher on beefy boxes; lower on laptops.
            </p>
          </div>

          <div className="flex items-center space-x-2">
            <input
              id="calibrate"
              type="checkbox"
              checked={calibrate}
              onChange={(e) => {
                logDecision({
                  workflowStep: "Model Training",
                  actionType: "workflow_setting_changed",
                  subject: "Calibrate probabilities",
                  previousValue: calibrate,
                  newValue: e.target.checked,
                });
                setCalibrate(e.target.checked);
              }}
              className="h-4 w-4 rounded border-gray-300 text-indigo-600 focus:ring-indigo-500"
            />
            <label htmlFor="calibrate" className="text-xs font-medium text-gray-700">
              Calibrate probabilities
            </label>
          </div>

          <div className="flex items-center space-x-2">
            <input
              id="usePCA"
              type="checkbox"
              checked={usePCA}
              onChange={(e) => {
                logDecision({
                  workflowStep: "Model Training",
                  actionType: "workflow_setting_changed",
                  subject: "Use PCA",
                  previousValue: usePCA,
                  newValue: e.target.checked,
                });
                setUsePCA(e.target.checked);
              }}
              className="h-4 w-4 rounded border-gray-300 text-indigo-600 focus:ring-indigo-500"
            />
            <label htmlFor="usePCA" className="text-xs font-medium text-gray-700">
              Use PCA (distance based)
            </label>
          </div>
        </div>

        <div className="mt-4 grid gap-4 border-t border-gray-100 pt-4 md:grid-cols-[minmax(220px,1fr)_220px_minmax(0,2fr)]">
          <div className="flex items-center space-x-2">
            <input
              id="useGridSearch"
              type="checkbox"
              checked={useGridSearch}
              onChange={(e) => {
                logDecision({
                  workflowStep: "Model Training",
                  actionType: "hyperparameter_search_changed",
                  subject: "Grid search enabled",
                  previousValue: useGridSearch,
                  newValue: e.target.checked,
                });
                setUseGridSearch(e.target.checked);
              }}
              className="h-4 w-4 rounded border-gray-300 text-indigo-600 focus:ring-indigo-500"
            />
            <label htmlFor="useGridSearch" className="text-xs font-medium text-gray-700">
              Use grid search for hyperparameters
            </label>
          </div>
          <label className="grid gap-1 text-xs font-medium text-gray-700">
            Search depth
            <select
              value={gridSearchLevel}
              disabled={!useGridSearch}
              title={useGridSearch ? "Choose how many candidate hyperparameter combinations to test." : "Enable grid search to choose a search depth."}
              onChange={(e) => {
                logDecision({
                  workflowStep: "Model Training",
                  actionType: "hyperparameter_search_changed",
                  subject: "Grid search depth",
                  previousValue: gridSearchLevel,
                  newValue: e.target.value,
                });
                setGridSearchLevel(e.target.value as "quick" | "balanced" | "thorough");
              }}
              className="rounded-md border border-gray-300 px-2 py-1.5 text-sm disabled:bg-gray-100 disabled:text-gray-400"
            >
              <option value="quick">Quick</option>
              <option value="balanced">Balanced</option>
              <option value="thorough">Thorough</option>
            </select>
            <span className="text-[11px] font-normal leading-4 text-slate-500">{gridSearchGuidance[gridSearchLevel]}</span>
          </label>
          <p className="self-end text-[11px] text-gray-500">
            {useGridSearch
              ? "Grid search tests a capped set of model-specific parameter combinations using the task metric, then fits the best estimator for evaluation and interpretation."
              : "Grid search is off. Models train with governed defaults; enable it when challenger performance or hyperparameter sensitivity matters."}
          </p>
        </div>

        <div className="mt-4 rounded-xl border border-slate-200 bg-slate-50 p-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Training Queue</div>
              <div className="mt-1 text-sm font-medium text-slate-900">
                {selectedModels.length ? `${selectedModels.length} model${selectedModels.length === 1 ? "" : "s"} selected` : "No models selected"}
              </div>
            </div>
            <div className="text-xs text-slate-500">
              Disabled toggles indicate optional libraries unavailable in the current backend environment.
            </div>
          </div>
          <div className="mt-3 flex flex-wrap gap-2">
            {selectedModels.length ? selectedModels.map((key) => {
              const def = MODEL_GROUPS.flatMap((group) => group.models).find((model) => model.key === key);
              return (
                <span key={key} className="rounded-full border border-indigo-100 bg-indigo-50 px-3 py-1 text-xs font-medium text-indigo-700">
                  {displayModelName(labels[key] ?? def?.label ?? key)}
                </span>
              );
            }) : (
              <span className="rounded-full border border-amber-200 bg-amber-50 px-3 py-1 text-xs font-medium text-amber-800">
                Select at least one model before training.
              </span>
            )}
          </div>
        </div>

        <div className="mt-4 flex items-center gap-2">
          <button
            type="button"
            onClick={startTraining}
            disabled={isTraining || selectedModels.length === 0}
            className="inline-flex items-center rounded-md bg-indigo-600 px-3 py-1.5 text-sm font-medium text-white shadow-sm hover:bg-indigo-700 disabled:cursor-not-allowed disabled:bg-indigo-300"
          >
            {isTraining ? "Training…" : "Train Selected"}
          </button>
          <button
            type="button"
            onClick={() => window.location.reload()}
            className="inline-flex items-center rounded-md border border-gray-300 bg-white px-3 py-1.5 text-sm font-medium text-gray-700 shadow-sm hover:bg-gray-50"
          >
            Refresh
          </button>
        </div>
      </div>

      {/* Model groups */}
      <div className="space-y-4">
        {visibleGroups.map((group) => (
          <div
            key={group.id}
            className="rounded-2xl border border-gray-200 bg-white p-4 shadow-sm"
          >
            <div className="mb-2 text-sm font-semibold text-gray-800">{group.title}</div>
            <div className="grid gap-3 md:grid-cols-2">
              {group.models.map((m) => {
                const optionalUnavailable = availabilityLoaded && OPTIONAL_MODEL_KEYS.has(m.key) && availability[m.key] === false;
                const enabled = selectableModelKeys.has(m.key);
                const label = (labels[m.key as ModelKey] ?? m.label).replace(/\s*\(k\s*=\s*\d+\)/i, "");
                const isChecked = selected[m.key];

                return (
                  <div
                    key={m.key}
                    className="flex items-center justify-between rounded-lg border border-gray-100 bg-gray-50 px-3 py-2"
                  >
                    <div className="flex flex-col">
                      <div className="flex items-center text-sm font-medium text-gray-800">
                        {label}
                        <StatusPill status={status[m.key]} />
                      </div>
                      <div className="text-[11px] leading-4 text-gray-500">{m.tooltip ?? "Select this candidate model when it aligns with the project objective and validation plan."}</div>
                    </div>
                    <Toggle
                      checked={isChecked}
                      disabled={!enabled || isTraining}
                      onChange={() => toggleModelSelection(m)}
                    />
                    {optionalUnavailable && (
                      <span className="ml-2 text-[11px] font-medium text-amber-600" title="ATLAS will include this model in the request. If the backend package is unavailable, the model will be reported as failed without blocking other selected models.">
                        package warning
                      </span>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        ))}
      </div>

      <StepPythonPanel />

      {/* Summary + metrics table */}
      <div className="rounded-2xl border border-gray-200 bg-white p-4 shadow-sm">
        <div className="mb-2 text-sm font-semibold text-gray-800">Summary</div>
        <p className="text-xs text-gray-600">
          After training, this table shows basic performance metrics for each model from the latest
          run. Detailed diagnostics (lift, SHAP, PDP, stability) will appear in Step 8.
        </p>

        {/* Metrics table */}
        {summary === null && (
          <div className="mt-3 text-xs text-gray-500">No training run loaded yet.</div>
        )}

        {summary !== null && summary.length === 0 && (
          <div className="mt-3 text-xs text-gray-500">
            No metrics available for the last run. This can happen if training failed or if the
            backend is not running.
          </div>
        )}

        {summary !== null && summary.length > 0 && (
          <div className="mt-3 overflow-x-auto">
            <table className="min-w-full text-xs">
              <thead>
                <tr className="text-left text-[11px] text-gray-500 border-b">
                  <th className="py-1 pr-4">Model</th>
                  {isRegressionSummary ? (
                    <>
                      <th className="py-1 pr-4">RMSE</th>
                      <th className="py-1 pr-4">MAE</th>
                      <th className="py-1 pr-4">R-squared</th>
                      <th className="py-1 pr-4">Adj. R-squared</th>
                      <th className="py-1 pr-4">MSE</th>
                    </>
                  ) : (
                    <>
                      <th className="py-1 pr-4">AUC</th>
                      <th className="py-1 pr-4">PR-AUC</th>
                      <th className="py-1 pr-4">Accuracy</th>
                      <th className="py-1 pr-4">F1</th>
                    </>
                  )}
                  <th className="py-1 pr-4">Best Params</th>
                </tr>
              </thead>
              <tbody>
                {summary.map((m) => (
                  <tr key={m.key} className="border-t">
                    <td className="py-1 pr-4">{displayModelName(m.name)}</td>
                    {isRegressionSummary ? (
                      <>
                        <td className="py-1 pr-4">{formatMetric(m.rmse)}</td>
                        <td className="py-1 pr-4">{formatMetric(m.mae)}</td>
                        <td className="py-1 pr-4">{formatMetric(m.r2)}</td>
                        <td className="py-1 pr-4">{formatMetric(m.adjusted_r2)}</td>
                        <td className="py-1 pr-4">{formatMetric(m.mse)}</td>
                      </>
                    ) : (
                      <>
                    <td className="py-1 pr-4">
                      {typeof m.auc === "number" ? m.auc.toFixed(4) : "—"}
                    </td>
                    <td className="py-1 pr-4">
                      {typeof m.pr_auc === "number" ? m.pr_auc.toFixed(4) : "—"}
                    </td>
                    <td className="py-1 pr-4">
                      {typeof m.accuracy === "number" ? m.accuracy.toFixed(4) : "—"}
                    </td>
                    <td className="py-1 pr-4">
                      {typeof m.f1 === "number" ? m.f1.toFixed(4) : "—"}
                    </td>
                      </>
                    )}
                    <td
                      className="max-w-[280px] truncate py-1 pr-4 text-gray-600"
                      title={formatParams(m.best_params)}
                    >
                      {formatParams(m.best_params)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {message && (
          <div className="mt-3 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900">
            {message}
          </div>
        )}

        <div className="mt-4 flex justify-end">
          <button
            type="button"
            disabled={!canGoToEvaluation}
            onClick={() => {
              if (!canGoToEvaluation) return;
              try {
                markComplete("step07");
                const saveResult = saveActiveProjectBeforeNavigation(useWorkflowStore.getState());
                if (!saveResult.ok) {
                  setMessage(`${saveResult.message} ATLAS will continue to Evaluation; reopen may restore only workflow progress.`);
                }
                navigate("/step08");
                window.requestAnimationFrame(() => window.scrollTo({ top: 0, left: 0, behavior: "auto" }));
              } catch (error) {
                setMessage(error instanceof Error ? error.message : "ATLAS could not save the training summary before evaluation.");
              }
            }}
            className="inline-flex items-center rounded-md bg-emerald-600 px-3 py-1.5 text-sm font-medium text-white shadow-sm hover:bg-emerald-700 disabled:cursor-not-allowed disabled:bg-gray-300 disabled:text-gray-500 disabled:shadow-none"
          >
            Go to Evaluation
          </button>
        </div>
      </div>
    </div>
  );
}

