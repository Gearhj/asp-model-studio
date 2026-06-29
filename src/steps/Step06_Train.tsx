// src/steps/Step06_Train.tsx

import React, { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { loadLocalDataset } from "../lib/localDataset";
import { useWorkflowStore } from "../state/useWorkflowStore";

const API_BASE =
  import.meta.env.VITE_API_BASE?.replace(/\/$/, "") || "http://127.0.0.1:8001/api";

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
      { key: "logreg", label: "Logistic Regression" },
      { key: "dtree", label: "Decision Tree" },
      { key: "ebm", label: "Explainable Boosting Machine (EBM)" },
    ],
  },
  {
    id: "ensemble",
    title: "Ensemble Models (Black Box)",
    task: "classification",
    models: [
      { key: "rf", label: "Random Forest" },
      { key: "xgb", label: "XGBoost" },
      { key: "cat", label: "CatBoost" },
      { key: "lgbm", label: "LightGBM" },
    ],
  },
  {
    id: "distance",
    title: "Distance Based",
    task: "classification",
    models: [
      { key: "knn", label: "K-Nearest Neighbors" },
      { key: "linsvm", label: "Linear SVM (Calibrated)" },
    ],
  },
  {
    id: "anomaly",
    title: "Anomaly Detection Models",
    task: "classification",
    models: [
      { key: "iso", label: "Isolation Forest (Anomaly)" },
      { key: "autoreg", label: "Autoregression (Anomaly)" },
    ],
  },
  {
    id: "nn",
    title: "Neural Network",
    task: "classification",
    models: [{ key: "mlp", label: "Neural Net (MLP)" }],
  },
  {
    id: "regression-transparent",
    title: "Regression Models",
    task: "regression",
    models: [
      { key: "linreg", label: "Linear Regression" },
      { key: "rf_reg", label: "Random Forest Regressor" },
      { key: "xgb_reg", label: "XGBoost Regressor" },
      { key: "lgbm_reg", label: "LightGBM Regressor" },
      { key: "cat_reg", label: "CatBoost Regressor" },
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

const ALL_MODEL_KEYS = MODEL_GROUPS.flatMap((group) => group.models.map((model) => model.key));

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

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export default function Step06_Train() {
  const navigate = useNavigate();
  const markComplete = useWorkflowStore((state) => state.markComplete);

  const [kFolds, setKFolds] = useState<number>(5);
  const [maxParallel, setMaxParallel] = useState<number>(2);
  const [calibrate, setCalibrate] = useState<boolean>(true);
  const [usePCA, setUsePCA] = useState<boolean>(false);
  const [useGridSearch, setUseGridSearch] = useState<boolean>(false);
  const [gridSearchLevel, setGridSearchLevel] = useState<"quick" | "balanced" | "thorough">("quick");

  const [selected, setSelected] = useState<Record<ModelKey, boolean>>(() => {
    const init = Object.fromEntries(ALL_MODEL_KEYS.map((key) => [key, false])) as Record<
      ModelKey,
      boolean
    >;
    (Object.keys(DEFAULT_SELECTION) as ModelKey[]).forEach((k) => {
      init[k] = !!DEFAULT_SELECTION[k];
    });
    return init;
  });

  const [status, setStatus] = useState<Record<ModelKey, Status>>(
    () =>
      Object.fromEntries(ALL_MODEL_KEYS.map((key) => [key, "idle"])) as Record<ModelKey, Status>
  );

  const [availability, setAvailability] = useState<Partial<Record<ModelKey, boolean>>>({});
  const [labels, setLabels] = useState<Partial<Record<ModelKey, string>>>({});
  const [isTraining, setIsTraining] = useState(false);
  const [message, setMessage] = useState<string | null>(
    "Models are trained on the full development dataset. Classification runs show AUC/PR-AUC/F1; regression runs show RMSE/MAE/R-squared. Detailed diagnostics appear in Step 8: Evaluation."
  );

  // NEW: summary of last training run (metrics per model)
  const [summary, setSummary] = useState<RankedRow[] | null>(null);
  const [problemType, setProblemType] = useState<ProblemType | null>(() => inferProblemTypeFromLocalDataset());

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
  const canGoToEvaluation =
    !isTraining &&
    selectedModels.every((model) => status[model] !== "pending") &&
    (summary?.length ?? 0) > 0;

  const isRegressionSummary =
    problemType === "regression" || !!summary?.some((row) => row.task === "regression" || row.rmse !== undefined);

  // -------------------------------------------------------------------------
  // Helper: fetch last training summary from backend
  // -------------------------------------------------------------------------

  async function fetchLastSummary() {
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
    if (!problemType) return;

    const defaults =
      problemType === "regression" ? DEFAULT_REGRESSION_SELECTION : DEFAULT_SELECTION;
    const allowedKeys = new Set(
      MODEL_GROUPS.filter((group) => group.task === problemType).flatMap((group) =>
        group.models.map((model) => model.key)
      )
    );

    setSelected((prev) => {
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
        setLabels(lbls);
        setMessage("Backend reports algorithm availability successfully. Training will fit real models.");
      })
      .catch((err) => {
        if (!alive) return;
        setMessage(
          "Backend model availability is unavailable. Start the FastAPI backend on port 8001 to train models."
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

    setMessage("Backend dataset was empty. Reloading the uploaded Step 1 data before training.");
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

      const rowsInfo = j.rows ? ` on ${j.rows.toLocaleString()} rows` : "";
      const statusInfo = j.status ? ` (status: ${j.status})` : "";
      setMessage(
        failedRows.length
          ? `Training completed${rowsInfo}${statusInfo}. ${trainedKeys.size} model(s) fit successfully; ${failedRows.length} model(s) failed. Metrics below are calculated from fitted backend models.`
          : `Training completed${rowsInfo}${statusInfo}. Metrics below are calculated from fitted backend models.`
      );

      // NEW: after a successful training run, pull latest summary for table
      await fetchLastSummary();
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
    <div className="max-w-[1100px] mx-auto space-y-6">
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
              Data split configuration: {problemType === "regression" ? "Regression K-Fold" : "Stratified K-Fold"} (K ≤ 5) from Balancing &amp; Split
            </div>
            <div className="mt-1 text-xs text-gray-500">
              These settings only control how the backend fits and evaluates candidate models.
            </div>
          </div>
          <div className="text-xs rounded-full border border-indigo-100 bg-indigo-50 px-3 py-1 text-indigo-700">
            {problemType === "regression" ? "Regression" : "Classification"} · K ≤ 5
          </div>
        </div>

        <div className="mt-4 grid gap-4 md:grid-cols-4">
          <div className="space-y-1">
            <label className="block text-xs font-medium text-gray-700">K (folds)</label>
            <input
              type="number"
              min={2}
              max={5}
              value={kFolds}
              onChange={(e) => setKFolds(Math.max(2, Math.min(5, Number(e.target.value) || 2)))}
              className="w-full rounded-md border border-gray-300 px-2 py-1.5 text-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
            />
            <p className="text-[11px] text-gray-500">Defined in Balancing &amp; Split.</p>
          </div>

          <div className="space-y-1">
            <label className="block text-xs font-medium text-gray-700">Max parallel models</label>
            <input
              type="number"
              min={1}
              max={16}
              value={maxParallel}
              onChange={(e) =>
                setMaxParallel(Math.max(1, Math.min(16, Number(e.target.value) || 1)))
              }
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
              onChange={(e) => setCalibrate(e.target.checked)}
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
              onChange={(e) => setUsePCA(e.target.checked)}
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
              onChange={(e) => setUseGridSearch(e.target.checked)}
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
              onChange={(e) => setGridSearchLevel(e.target.value as "quick" | "balanced" | "thorough")}
              className="rounded-md border border-gray-300 px-2 py-1.5 text-sm disabled:bg-gray-100 disabled:text-gray-400"
            >
              <option value="quick">Quick</option>
              <option value="balanced">Balanced</option>
              <option value="thorough">Thorough</option>
            </select>
          </label>
          <p className="self-end text-[11px] text-gray-500">
            Grid search tests a capped set of model-specific parameter combinations using the task metric, then fits the best estimator for evaluation and interpretation.
          </p>
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
                const enabled = availability[m.key] ?? false;
                const label = labels[m.key as ModelKey] ?? m.label;
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
                      {m.tooltip && (
                        <div className="text-[11px] text-gray-500">{m.tooltip}</div>
                      )}
                    </div>
                    <Toggle
                      checked={isChecked}
                      disabled={!enabled || isTraining}
                      onChange={() =>
                        setSelected((prev) => ({ ...prev, [m.key]: !prev[m.key] }))
                      }
                    />
                  </div>
                );
              })}
            </div>
          </div>
        ))}
      </div>

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
                    <td className="py-1 pr-4">{m.name}</td>
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
              markComplete("step07");
              navigate("/step08");
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
