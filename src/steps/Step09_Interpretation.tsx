import React, { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import StepPythonPanel from "../components/StepPythonPanel";
import { logDecision } from "../lib/decisionJournal";
import { upsertProjectFromState } from "../lib/localProjects";
import { useWorkflowStore } from "../state/useWorkflowStore";

const API_BASE =
  (import.meta.env.VITE_API_BASE as string | undefined)?.replace(/\/$/, "") ||
  "http://127.0.0.1:8001/api";
const RFE_CACHE_KEY = "modeling-tool-rfe-cache";

type RankedRow = { key: string; name: string; task?: "classification" | "regression" | "anomaly"; auc?: number; pr_auc?: number; rmse?: number; mae?: number; r2?: number; adjusted_r2?: number };
type ImportanceRow = { feature: string; importance: number; source?: string; direction?: number };
type DetailResponse = {
  ok: boolean;
  kind?: "equation" | "tree" | "generic";
  intercept?: number;
  coefficients?: { feature: string; coefficient: number; odds_ratio: number }[];
  tree_text?: string;
  message?: string;
  error?: string;
};
type CurveRow = { value: string | number; label?: string; prediction: number };
type SensitivityRow = { scenario: string; prediction: number; delta: number };
type SensitivitySummaryRow = {
  feature: string;
  baseline: number;
  max_abs_delta: number;
  worst_scenario: string;
  worst_prediction: number;
  worst_delta: number;
};
type VsiRow = { feature: string; value: number; status: "pass" | "warning" | "fail" };
type VifRow = { feature: string; vif: number; tolerance: number; r_squared: number; status: "pass" | "warning" | "fail" };
type RfeRow = { feature: string; selected: boolean; rank: number; importance?: number };
type HyperparameterRow = { parameter: string; value: string };
type RfeCurveRow = {
  feature_count: number;
  auc?: number;
  display_auc?: number;
  marginal_auc?: number | null;
  rmse?: number;
  display_rmse?: number;
  marginal_rmse?: number | null;
  added_feature: string;
  features: string[];
};
type RfeResult = {
  ok: boolean;
  rows?: RfeRow[];
  curve?: RfeCurveRow[];
  recommended_count?: number;
  best_count?: number;
  best_auc?: number;
  auc_tolerance?: number;
  best_rmse?: number;
  rmse_tolerance?: number;
  metric?: "auc" | "rmse";
  task?: "classification" | "regression";
  error?: string;
};
type BoundaryPoint = { x: number; y: number; class: number };
type BoundaryCell = { x: number; y: number; score: number };
type BoundaryResponse = {
  ok: boolean;
  error?: string;
  x_feature?: string;
  y_feature?: string;
  x_domain?: [number, number];
  y_domain?: [number, number];
  resolution?: number;
  grid?: BoundaryCell[];
  points?: BoundaryPoint[];
  numeric_features?: string[];
};
type TreeNode = {
  id: number;
  depth: number;
  x?: number;
  leaf: boolean;
  feature?: string;
  threshold?: number | null;
  samples: number;
  positive_rate: number;
  prediction: string;
};
type TreeEdge = { source: number; target: number; label: string };
type TreeResponse = { ok: boolean; nodes?: TreeNode[]; edges?: TreeEdge[]; error?: string };

type CachedRfeResult = Pick<
  RfeResult,
  "rows" | "curve" | "recommended_count" | "best_count" | "best_auc" | "auc_tolerance" | "best_rmse" | "rmse_tolerance" | "metric" | "task"
> & { keep: number; cachedAt: string };

function loadRfeCache(modelKey: string): CachedRfeResult | null {
  try {
    const parsed = JSON.parse(sessionStorage.getItem(RFE_CACHE_KEY) || "{}");
    const cached = parsed?.[modelKey];
    return cached && typeof cached === "object" ? cached : null;
  } catch {
    return null;
  }
}

function saveRfeCache(modelKey: string, data: RfeResult, keep: number) {
  try {
    const parsed = JSON.parse(sessionStorage.getItem(RFE_CACHE_KEY) || "{}");
    parsed[modelKey] = {
      rows: data.rows ?? [],
      curve: data.curve ?? [],
      recommended_count: data.recommended_count ?? null,
      best_count: data.best_count ?? null,
      best_auc: data.best_auc ?? null,
      auc_tolerance: data.auc_tolerance ?? null,
      best_rmse: data.best_rmse ?? null,
      rmse_tolerance: data.rmse_tolerance ?? null,
      metric: data.metric ?? (data.task === "regression" ? "rmse" : "auc"),
      task: data.task,
      keep,
      cachedAt: new Date().toISOString(),
    };
    sessionStorage.setItem(RFE_CACHE_KEY, JSON.stringify(parsed));
  } catch {
    // RFE can be rerun if session storage is unavailable.
  }
}

async function getJson<T>(url: string): Promise<T> {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`Request failed (${res.status})`);
  return (await res.json()) as T;
}

export default function Step09_Interpretation() {
  const navigate = useNavigate();
  const markComplete = useWorkflowStore((state) => state.markComplete);
  const [models, setModels] = useState<RankedRow[]>([]);
  const [selectedModel, setSelectedModel] = useState("");
  const [selectedFeature, setSelectedFeature] = useState("");
  const [importance, setImportance] = useState<ImportanceRow[]>([]);
  const [details, setDetails] = useState<DetailResponse | null>(null);
  const [hyperparameters, setHyperparameters] = useState<HyperparameterRow[]>([]);
  const [pdp, setPdp] = useState<CurveRow[]>([]);
  const [sensitivity, setSensitivity] = useState<SensitivityRow[]>([]);
  const [finalSensitivityRows, setFinalSensitivityRows] = useState<SensitivitySummaryRow[]>([]);
  const [vifRows, setVifRows] = useState<VifRow[]>([]);
  const [finalDiagnosticsReady, setFinalDiagnosticsReady] = useState(false);
  const [shapRows, setShapRows] = useState<ImportanceRow[]>([]);
  const [rfeKeep, setRfeKeep] = useState(10);
  const [rfeRows, setRfeRows] = useState<RfeRow[]>([]);
  const [rfeCurve, setRfeCurve] = useState<RfeCurveRow[]>([]);
  const [rfeRunning, setRfeRunning] = useState(false);
  const [rfeError, setRfeError] = useState("");
  const [recommendedCount, setRecommendedCount] = useState<number | null>(null);
  const [bestRfeCount, setBestRfeCount] = useState<number | null>(null);
  const [bestRfeAuc, setBestRfeAuc] = useState<number | null>(null);
  const [bestRfeRmse, setBestRfeRmse] = useState<number | null>(null);
  const [rfeAucTolerance, setRfeAucTolerance] = useState<number | null>(null);
  const [rfeRmseTolerance, setRfeRmseTolerance] = useState<number | null>(null);
  const [rfeMetric, setRfeMetric] = useState<"auc" | "rmse" | null>(null);
  const [boundary, setBoundary] = useState<BoundaryResponse | null>(null);
  const [treeStructure, setTreeStructure] = useState<TreeResponse | null>(null);
  const [boundaryX, setBoundaryX] = useState("");
  const [boundaryY, setBoundaryY] = useState("");
  const [message, setMessage] = useState("");
  const [finalModelMessage, setFinalModelMessage] = useState("");
  const [finalModelStatus, setFinalModelStatus] = useState<"success" | "error" | "">("");
  const [savingFinalModel, setSavingFinalModel] = useState(false);
  const [finalModelReady, setFinalModelReady] = useState(false);
  const selectedModelRow = models.find((model) => model.key === selectedModel) ?? models[0];
  const selectedModelIsRegression = selectedModelRow?.task === "regression" || selectedModelRow?.rmse !== undefined;
  const rfeIsRegression = rfeMetric === "rmse" || (!rfeMetric && selectedModelIsRegression);
  const rfeSelectedCount = rfeRows.filter((row) => row.rank <= rfeKeep).length;
  const rfeRemovedCount = Math.max(0, rfeRows.length - rfeSelectedCount);
  const canRunRfe = Boolean(selectedModel) && !rfeRunning && importance.length >= 2;

  const exportModel = (format: "pkl" | "jar") => {
    if (format === "jar") {
      setMessage("JAR export is not available for the current Python/scikit-learn pipeline. Use the PKL bundle for Python deployment, or add an ONNX/PMML export path for JVM scoring.");
      return;
    }
    window.location.href = `${API_BASE}/model/export?model=final&format=pkl`;
  };

  useEffect(() => {
    getJson<{ ok: boolean; summary?: { problem_type?: string; ranked?: RankedRow[] } }>(`${API_BASE}/train/last`)
      .then((data) => {
        const ranked = data.summary?.ranked ?? [];
        setModels(ranked);
        setSelectedModel(ranked[0]?.key ?? "");
      })
      .catch((err) => setMessage(String(err?.message ?? err)));
  }, []);

  useEffect(() => {
    if (!selectedModel) return;
    setMessage("");
    setTreeStructure(null);
    Promise.all([
      getJson<{ ok: boolean; rows?: ImportanceRow[]; error?: string }>(
        `${API_BASE}/interpretation/importance?model=${encodeURIComponent(selectedModel)}`
      ),
      getJson<DetailResponse>(
        `${API_BASE}/interpretation/details?model=${encodeURIComponent(selectedModel)}`
      ),
      getJson<{ ok: boolean; rows?: HyperparameterRow[] }>(
        `${API_BASE}/interpretation/hyperparameters?model=${encodeURIComponent(selectedModel)}`
      ),
      getJson<{ ok: boolean; rows?: ImportanceRow[]; method?: string }>(
        `${API_BASE}/interpretation/shap?model=${encodeURIComponent(selectedModel)}`
      ),
    ])
      .then(([importanceRes, detailsRes, hyperparameterRes, shapRes]) => {
        const rows = importanceRes.rows ?? [];
        setImportance(rows);
        setDetails(detailsRes);
        setHyperparameters(hyperparameterRes.rows ?? []);
        setShapRows(shapRes.rows ?? []);
        setSelectedFeature(rows[0]?.feature?.replace(/^.*__/, "") || "");
        const cachedRfe = loadRfeCache(selectedModel);
        setRfeRows(cachedRfe?.rows ?? []);
        setRfeCurve(cachedRfe?.curve ?? []);
        setRecommendedCount(cachedRfe?.recommended_count ?? null);
        setBestRfeCount(cachedRfe?.best_count ?? null);
        setBestRfeAuc(cachedRfe?.best_auc ?? null);
        setBestRfeRmse(cachedRfe?.best_rmse ?? null);
        setRfeAucTolerance(cachedRfe?.auc_tolerance ?? null);
        setRfeRmseTolerance(cachedRfe?.rmse_tolerance ?? null);
        setRfeMetric(cachedRfe?.metric ?? null);
        if (cachedRfe?.keep) setRfeKeep(cachedRfe.keep);
        setFinalModelReady(false);
        setFinalDiagnosticsReady(false);
        setFinalModelMessage("");
        setFinalModelStatus("");
        setFinalSensitivityRows([]);
        setVifRows([]);
        if (detailsRes.kind === "tree") {
          getJson<TreeResponse>(`${API_BASE}/eval/tree?model=${encodeURIComponent(selectedModel)}&max_depth=4`)
            .then((treeRes) => setTreeStructure(treeRes))
            .catch((err) => setTreeStructure({ ok: false, error: String(err?.message ?? err) }));
        }
      })
      .catch((err) => setMessage(String(err?.message ?? err)));
  }, [selectedModel]);

  useEffect(() => {
    if (!selectedModel || !selectedFeature) return;
    Promise.all([
      getJson<{ ok: boolean; rows?: CurveRow[] }>(
        `${API_BASE}/interpretation/pdp?model=${encodeURIComponent(selectedModel)}&feature=${encodeURIComponent(selectedFeature)}`
      ),
      getJson<{ ok: boolean; rows?: SensitivityRow[] }>(
        `${API_BASE}/interpretation/sensitivity?model=${encodeURIComponent(selectedModel)}&feature=${encodeURIComponent(selectedFeature)}`
      ),
    ])
      .then(([pdpRes, sensitivityRes]) => {
        setPdp(pdpRes.rows ?? []);
        setSensitivity(sensitivityRes.rows ?? []);
      })
      .catch((err) => setMessage(String(err?.message ?? err)));
  }, [selectedModel, selectedFeature]);

  useEffect(() => {
    if (!selectedModel) return;
    const params = new URLSearchParams({ model: selectedModel });
    if (boundaryX) params.set("x_feature", boundaryX);
    if (boundaryY) params.set("y_feature", boundaryY);
    getJson<BoundaryResponse>(`${API_BASE}/interpretation/decision_boundary?${params.toString()}`)
      .then((data) => {
        if (!data.ok) {
          setBoundary(data);
          return;
        }
        setBoundary(data);
        setBoundaryX(data.x_feature ?? "");
        setBoundaryY(data.y_feature ?? "");
      })
      .catch((err) => setMessage(String(err?.message ?? err)));
  }, [selectedModel, boundaryX, boundaryY]);

  const featureOptions = useMemo(
    () => Array.from(new Set(importance.map((row) => row.feature.replace(/^.*__/, "")))),
    [importance]
  );

  const runRfe = () => {
    if (!selectedModel || rfeRunning) return;
    setRfeRunning(true);
    setMessage("");
    setRfeError("");
    getJson<RfeResult>(
      `${API_BASE}/interpretation/rfe?model=${encodeURIComponent(selectedModel)}&keep=${rfeKeep}`
    )
      .then((data) => {
        if (!data.ok) throw new Error(data.error ?? "RFE failed.");
        setRfeRows(data.rows ?? []);
        setRfeCurve(data.curve ?? []);
        setRecommendedCount(data.recommended_count ?? null);
        setBestRfeCount(data.best_count ?? null);
        setBestRfeAuc(data.best_auc ?? null);
        setBestRfeRmse(data.best_rmse ?? null);
        setRfeAucTolerance(data.auc_tolerance ?? null);
        setRfeRmseTolerance(data.rmse_tolerance ?? null);
        setRfeMetric(data.metric ?? (data.task === "regression" ? "rmse" : "auc"));
        const nextKeep = data.recommended_count ?? data.best_count ?? rfeKeep;
        setRfeKeep(nextKeep);
        saveRfeCache(selectedModel, data, nextKeep);
      })
      .catch((err) => {
        const text = String(err?.message ?? err);
        setRfeError(text);
        setMessage(`RFE could not run: ${text}`);
      })
      .finally(() => setRfeRunning(false));
  };

  const loadFinalDiagnostics = async () => {
    const [sensitivityRes, vifRes] = await Promise.all([
      getJson<{ ok: boolean; rows?: SensitivitySummaryRow[]; error?: string }>(
        `${API_BASE}/interpretation/sensitivity_summary?model=final&top_n=12`
      ),
      getJson<{ ok: boolean; rows?: VifRow[]; error?: string }>(
        `${API_BASE}/interpretation/vif?model=final`
      ),
    ]);
    if (!sensitivityRes.ok) throw new Error(sensitivityRes.error ?? "Final-model sensitivity failed.");
    if (!vifRes.ok) throw new Error(vifRes.error ?? "Final-model VIF failed.");
    setFinalSensitivityRows(sensitivityRes.rows ?? []);
    setVifRows(vifRes.rows ?? []);
    setFinalDiagnosticsReady(true);
  };

  const saveRfeFinalModel = async () => {
    setFinalModelMessage("");
    setFinalModelStatus("");
    setSavingFinalModel(true);
    try {
      const res = await fetch(`${API_BASE}/interpretation/rfe/save_final`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ model: selectedModel, keep: rfeKeep }),
      });
      if (!res.ok) throw new Error(`Save failed (${res.status})`);
      const data = await res.json();
      if (!data.ok) throw new Error(data.error ?? "Unable to save final model.");
      setFinalModelMessage(
        `Saved final parsimonious model with ${data.metadata?.feature_count ?? rfeKeep} features.`
      );
      logDecision({
        workflowStep: "Interpretation",
        actionType: "final_model_saved",
        subject: "RFE parsimonious final model",
        previousValue: "candidate",
        newValue: {
          model: selectedModel,
          feature_count: data.metadata?.feature_count ?? rfeKeep,
        },
        followStatus: "followed",
      });
      setFinalModelStatus("success");
      setFinalModelReady(true);
      await loadFinalDiagnostics();
    } catch (err: any) {
      setFinalModelMessage(err?.message ?? "Unable to save final model.");
      setFinalModelStatus("error");
    } finally {
      setSavingFinalModel(false);
    }
  };

  const saveSelectedFinalModel = async () => {
    setFinalModelMessage("");
    setFinalModelStatus("");
    setSavingFinalModel(true);
    try {
      const res = await fetch(`${API_BASE}/model/save_final`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ model: selectedModel }),
      });
      if (!res.ok) throw new Error(`Save failed (${res.status})`);
      const data = await res.json();
      if (!data.ok) throw new Error(data.error ?? "Unable to save final model.");
      setFinalModelMessage(`Saved ${data.metadata?.name ?? selectedModel} as the final model.`);
      logDecision({
        workflowStep: "Interpretation",
        actionType: "final_model_saved",
        subject: "Selected final model",
        previousValue: "candidate",
        newValue: data.metadata?.name ?? selectedModel,
      });
      setFinalModelStatus("success");
      setFinalModelReady(true);
    } catch (err: any) {
      setFinalModelMessage(err?.message ?? "Unable to save final model.");
      setFinalModelStatus("error");
    } finally {
      setSavingFinalModel(false);
    }
  };

  if (!models.length) {
    return (
      <div className="w-full space-y-4">
        <h1 className="text-2xl font-semibold">Step 9: Model Interpretation</h1>
        <div className="rounded-2xl border border-gray-200 bg-white p-4 text-sm text-gray-600">
          Train models first, then return here for interpretation.
        </div>
      </div>
    );
  }

  return (
    <div className="w-full space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold">Step 9: Model Interpretation</h1>
          <p className="mt-1 text-sm text-gray-600">
            Explain model behavior, feature effects, sensitivity, and candidate reduced feature sets.
          </p>
        </div>
        <label className="grid gap-1 text-sm">
          <span className="text-xs font-medium text-gray-600">Model</span>
          <select
            className="rounded-md border px-3 py-2"
            value={selectedModel}
            onChange={(e) => {
              logDecision({
                workflowStep: "Interpretation",
                actionType: "champion_model_selected",
                subject: "Model selected for interpretation",
                previousValue: selectedModel,
                newValue: e.target.value,
              });
              setSelectedModel(e.target.value);
            }}
          >
            {models.map((model) => (
              <option key={model.key} value={model.key}>
                {model.name}
              </option>
            ))}
          </select>
        </label>
      </div>

      {message && <div className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900">{message}</div>}

      <section className="rounded-2xl border border-gray-200 bg-white p-4">
        <h2 className="text-sm font-semibold">Model-Specific Explanation</h2>
        <ModelDetails details={details} tree={treeStructure} />
      </section>

      <section className="rounded-2xl border border-gray-200 bg-white p-4">
        <h2 className="text-sm font-semibold">Final Hyperparameter Settings</h2>
        <HyperparameterTable rows={hyperparameters} />
      </section>

      <section className="rounded-2xl border border-gray-200 bg-white p-4">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h2 className="text-sm font-semibold">{selectedModelIsRegression ? "Prediction Response Surface" : "Decision Boundary"}</h2>
            <p className="mt-1 text-xs text-gray-500">
              {selectedModelIsRegression
                ? "Shows the selected model prediction across two numeric features while holding all other fields at typical values."
                : "Shows the selected model response across two numeric features while holding all other fields at typical values."}
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <select className="rounded-md border px-3 py-2 text-sm" value={boundaryX} onChange={(e) => setBoundaryX(e.target.value)}>
              {(boundary?.numeric_features ?? []).map((feature) => <option key={feature} value={feature}>{feature}</option>)}
            </select>
            <select className="rounded-md border px-3 py-2 text-sm" value={boundaryY} onChange={(e) => setBoundaryY(e.target.value)}>
              {(boundary?.numeric_features ?? []).filter((feature) => feature !== boundaryX).map((feature) => <option key={feature} value={feature}>{feature}</option>)}
            </select>
          </div>
        </div>
        <DecisionBoundaryChart boundary={boundary} />
      </section>

      <div className="grid gap-6 lg:grid-cols-2">
        <section className="rounded-2xl border border-gray-200 bg-white p-4">
          <h2 className="text-sm font-semibold">Feature Importance</h2>
          <p className="mt-1 text-xs text-gray-500">
            {selectedModelIsRegression
              ? "Appropriate for regression: ranks variables by contribution to predictive accuracy."
              : "Ranks variables by contribution to model performance."}
          </p>
          <BarTable rows={importance} valueKey="importance" color="indigo" />
        </section>
        <section className="rounded-2xl border border-gray-200 bg-white p-4">
          <h2 className="text-sm font-semibold">SHAP Summary</h2>
          <p className="mt-1 text-xs text-gray-500">
            {selectedModelIsRegression
              ? "Appropriate for regression: estimates how each feature changes predicted target values on holdout records."
              : "Model-agnostic replacement impact on held-out predictions. This differs from native feature importance."}
          </p>
          <BarTable rows={shapRows} valueKey="importance" color="teal" />
        </section>
      </div>

      <section className="rounded-2xl border border-gray-200 bg-white p-4">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h2 className="text-sm font-semibold">{selectedModelIsRegression ? "Prediction Drivers" : "PDP / Sensitivity"}</h2>
            <p className="mt-1 text-xs text-gray-500">
              {selectedModelIsRegression
                ? "PDP and sensitivity are appropriate for regression: they show how the predicted target value changes as a feature changes."
                : "Select a feature to inspect marginal response and scenario sensitivity."}
            </p>
          </div>
          <select className="rounded-md border px-3 py-2 text-sm" value={selectedFeature} onChange={(e) => setSelectedFeature(e.target.value)}>
            {featureOptions.map((feature) => (
              <option key={feature} value={feature}>{feature}</option>
            ))}
          </select>
        </div>
        <div className="mt-4 grid gap-4 lg:grid-cols-2">
          <LineChart title={selectedModelIsRegression ? "Partial Dependence: Predicted Target" : "Partial Dependence Plot"} rows={pdp} feature={selectedFeature} />
          <SensitivityTable rows={sensitivity} />
        </div>
      </section>

      <section className="rounded-2xl border border-gray-200 bg-white p-4">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h2 className="text-sm font-semibold">Recursive Feature Elimination</h2>
            <p className="mt-1 text-xs text-gray-500">
              {rfeIsRegression
                ? "Runs backward elimination and recommends the smallest retained feature count that is effectively tied with the best holdout RMSE."
                : "Runs backward elimination and recommends the smallest retained feature count that is effectively tied with the best holdout AUC."}
            </p>
          </div>
          <div className="flex items-end gap-2">
            {recommendedCount && (
              <div className="rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-xs font-medium text-emerald-800">
                Recommended: {recommendedCount} features
              </div>
            )}
            {rfeRunning && (
              <div className="rounded-lg border border-indigo-200 bg-indigo-50 px-3 py-2 text-xs font-medium text-indigo-800">
                Running RFE...
              </div>
            )}
            <button
              className="rounded-md bg-indigo-600 px-3 py-2 text-sm font-medium text-white transition hover:bg-indigo-700 active:scale-95 disabled:cursor-not-allowed disabled:bg-indigo-300 disabled:active:scale-100"
              disabled={!canRunRfe}
              onClick={runRfe}
              title={canRunRfe ? "Run recursive feature elimination for the selected model." : "Train a model and load at least two candidate features before running RFE."}
            >
              {rfeRunning ? "Running..." : rfeRows.length ? "Rerun RFE" : "Run RFE"}
            </button>
            <button
              className="rounded-md bg-emerald-600 px-3 py-2 text-sm font-medium text-white transition active:scale-95 active:bg-emerald-700 disabled:cursor-not-allowed disabled:bg-emerald-300 disabled:active:scale-100"
              disabled={!rfeRows.length || savingFinalModel}
              onClick={saveRfeFinalModel}
            >
              {savingFinalModel ? "Saving..." : "Save as Final Model"}
            </button>
          </div>
        </div>
        {finalModelMessage && (
          <div className={`mt-3 rounded-md border px-3 py-2 text-sm ${
            finalModelStatus === "error"
              ? "border-rose-200 bg-rose-50 text-rose-900"
              : "border-emerald-200 bg-emerald-50 text-emerald-900"
          }`}>
            {finalModelMessage}
          </div>
        )}
        {rfeError && (
          <div className="mt-3 rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-900">
            {rfeError}
          </div>
        )}
        {!canRunRfe && !rfeRunning && !rfeRows.length && (
          <div className="mt-3 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs leading-5 text-amber-900">
            RFE requires a selected trained model and at least two loaded feature-importance rows.
            If this stays unavailable, return to Model Training, train the selected model, then reload Interpretation.
          </div>
        )}
        {rfeRows.length > 0 && (
          <div className="mt-3 grid gap-3 md:grid-cols-4">
            <MetricTile label="Retained Features" value={String(rfeSelectedCount)} tone="emerald" />
            <MetricTile label="Removed Features" value={String(rfeRemovedCount)} tone="slate" />
            <MetricTile
              label={rfeIsRegression ? "Best RMSE" : "Best AUC"}
              value={rfeIsRegression ? formatNumber(bestRfeRmse) : formatNumber(bestRfeAuc)}
              tone="indigo"
            />
            <MetricTile
              label="Recommendation"
              value={recommendedCount ? `${recommendedCount} kept` : "Review curve"}
              tone="amber"
            />
          </div>
        )}
        {recommendedCount && bestRfeCount && bestRfeAuc !== null && !rfeIsRegression && (
          <div className="mt-3 rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-700">
            Best RFE point: {bestRfeCount} features at AUC {bestRfeAuc.toFixed(4)}. Recommended count uses a {((rfeAucTolerance ?? 0.001) * 100).toFixed(2)} percentage-point AUC tolerance.
          </div>
        )}
        {recommendedCount && bestRfeCount && bestRfeRmse !== null && rfeIsRegression && (
          <div className="mt-3 rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-700">
            Best RFE point: {bestRfeCount} features at RMSE {bestRfeRmse.toFixed(4)}. Recommended count uses a {rfeRmseTolerance?.toFixed(4) ?? "small"} RMSE tolerance.
          </div>
        )}
        <RfeCurveChart rows={rfeCurve} selectedCount={rfeKeep} recommendedCount={recommendedCount} onSelectCount={setRfeKeep} isRegression={rfeIsRegression} />
        <RfeTable rows={rfeRows} selectedCount={rfeKeep} />
      </section>

      <section className="rounded-2xl border border-gray-200 bg-white p-4">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <h2 className="text-sm font-semibold">Production Export</h2>
            <p className="mt-1 text-xs text-gray-500">
              Save the RFE-selected final model first, then export the fitted preprocessing pipeline, model, and metadata.
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <button
              className="rounded-md bg-indigo-600 px-3 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:cursor-not-allowed disabled:bg-indigo-300"
              disabled={!finalModelReady}
              onClick={() => exportModel("pkl")}
              title={finalModelReady ? "Download final model package" : "Save as Final Model first"}
            >
              Download Final .pkl Bundle
            </button>
            <button
              className="rounded-md border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-600 hover:bg-slate-50"
              onClick={() => exportModel("jar")}
            >
              .jar Info
            </button>
          </div>
        </div>
      </section>

      {!selectedModelIsRegression && <section className="rounded-2xl border border-gray-200 bg-white p-4">
        <h2 className="text-sm font-semibold">Final Model Sensitivity Analysis</h2>
        <p className="mt-1 text-xs text-gray-500">
          Runs after Save as Final Model and ranks prediction shifts only across the selected RFE variables.
        </p>
        {finalDiagnosticsReady ? (
          <SensitivitySummaryTable rows={finalSensitivityRows} />
        ) : (
          <div className="mt-3 rounded-xl bg-slate-50 p-4 text-sm text-gray-500">
            Save a final model from the RFE section to generate final-variable sensitivity.
          </div>
        )}
      </section>}

      {!selectedModelIsRegression && <section className="rounded-2xl border border-gray-200 bg-white p-4">
        <h2 className="text-sm font-semibold">Variance Inflation Factor</h2>
        <p className="mt-1 text-xs text-gray-500">
          Runs after Save as Final Model and checks multicollinearity only among final RFE variables.
        </p>
        {finalDiagnosticsReady ? (
          <VifTable rows={vifRows} />
        ) : (
          <div className="mt-3 rounded-xl bg-slate-50 p-4 text-sm text-gray-500">
            Save a final model from the RFE section to generate VIF diagnostics.
          </div>
        )}
      </section>}

      <StepPythonPanel />

      <div className="pb-10 flex justify-center">
        <button
          className="rounded-xl bg-indigo-600 px-5 py-3 text-white shadow-sm"
          onClick={() => {
            try {
              markComplete("step09");
              upsertProjectFromState(useWorkflowStore.getState());
              navigate("/step10");
              window.requestAnimationFrame(() => window.scrollTo({ top: 0, left: 0, behavior: "auto" }));
            } catch (error) {
              setMessage(error instanceof Error ? error.message : "ATLAS could not save this interpretation step before navigation.");
            }
          }}
        >
          Mark Complete & Next Step
        </button>
      </div>
    </div>
  );
}

function ModelDetails({ details, tree }: { details: DetailResponse | null; tree: TreeResponse | null }) {
  if (!details) return <div className="mt-3 text-sm text-gray-500">Loading model details...</div>;
  if (!details.ok) return <div className="mt-3 text-sm text-rose-700">{details.error}</div>;
  if (details.kind === "equation") {
    return (
      <div className="mt-3">
        <div className="rounded-lg bg-slate-50 p-3 font-mono text-xs">logit(p) = {details.intercept?.toFixed(4)} + Σ(coef × feature)</div>
        <BarTable rows={(details.coefficients ?? []).map((row) => ({ feature: row.feature, importance: row.coefficient, source: `OR ${row.odds_ratio.toFixed(3)}` }))} valueKey="importance" color="indigo" />
      </div>
    );
  }
  if (details.kind === "tree") {
    if (!tree) {
      return <div className="mt-3 rounded-xl bg-slate-50 p-4 text-sm text-gray-500">Loading structured decision tree...</div>;
    }
    if (tree.ok && tree.nodes?.length) {
      return <DecisionTreeExplanation tree={tree} />;
    }
    return (
      <div className="mt-3 space-y-3">
        <div className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">
          {tree.error ?? "Structured decision tree output is unavailable. Showing the backend text export instead."}
        </div>
        <TreeTextFallback text={details.tree_text ?? ""} />
      </div>
    );
  }
  return <div className="mt-3 text-sm text-gray-600">{details.message}</div>;
}

function DecisionTreeExplanation({ tree }: { tree: TreeResponse }) {
  const nodes = tree.nodes ?? [];
  const edges = tree.edges ?? [];
  const root = nodes.find((node) => node.depth === 0) ?? nodes[0];
  const leaves = nodes.filter((node) => node.leaf);
  const maxDepth = Math.max(...nodes.map((node) => node.depth), 0);
  const topLeaves = buildLeafRules(nodes, edges).slice(0, 6);

  return (
    <div className="mt-3 space-y-4">
      <div className="grid gap-3 md:grid-cols-4">
        <MetricTile label="Root Split" value={root?.feature ? `${root.feature} <= ${formatThreshold(root.threshold)}` : "Leaf"} tone="indigo" />
        <MetricTile label="Tree Depth" value={String(maxDepth)} tone="slate" />
        <MetricTile label="Terminal Leaves" value={String(leaves.length)} tone="emerald" />
        <MetricTile label="Root Event Rate" value={`${((root?.positive_rate ?? 0) * 100).toFixed(1)}%`} tone="amber" />
      </div>
      <DecisionTreeSvg nodes={nodes} edges={edges} />
      <div className="rounded-xl border border-slate-200 bg-white p-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <h3 className="text-sm font-semibold text-slate-900">Terminal Decision Rules</h3>
            <p className="mt-1 text-xs text-slate-500">Largest terminal segments from the fitted tree, sorted by sample count.</p>
          </div>
          <div className="rounded-full border border-slate-200 bg-slate-50 px-3 py-1 text-xs font-medium text-slate-600">
            {topLeaves.length} rules shown
          </div>
        </div>
        <div className="mt-3 grid gap-3 lg:grid-cols-2">
          {topLeaves.map((rule) => (
            <div key={rule.id} className="rounded-xl border border-slate-200 bg-slate-50 p-3">
              <div className="flex items-center justify-between gap-3">
                <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Leaf {rule.prediction}</div>
                <div className={`rounded-full px-2.5 py-1 text-xs font-semibold ${rule.positiveRate >= 0.5 ? "bg-rose-100 text-rose-700" : "bg-blue-100 text-blue-700"}`}>
                  {(rule.positiveRate * 100).toFixed(1)}% event rate
                </div>
              </div>
              <div className="mt-2 text-lg font-semibold text-slate-900">{rule.samples.toLocaleString()} records</div>
              <ol className="mt-2 space-y-1 text-xs leading-5 text-slate-700">
                {rule.conditions.length ? rule.conditions.map((condition, index) => <li key={`${rule.id}-${index}`}>{condition}</li>) : <li>No split conditions; root is terminal.</li>}
              </ol>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function DecisionTreeSvg({ nodes, edges }: { nodes: TreeNode[]; edges: TreeEdge[] }) {
  const nodeW = 172;
  const nodeH = 78;
  const xGap = 42;
  const yGap = 122;
  const topPad = 52;
  const sidePad = 44;
  const maxDepth = Math.max(...nodes.map((node) => node.depth), 1);
  const childMap = new Map<number, number[]>();
  edges.forEach((edge) => childMap.set(edge.source, [...(childMap.get(edge.source) ?? []), edge.target]));
  const nodeById = new Map(nodes.map((node) => [node.id, node]));
  const subtreeWidth = new Map<number, number>();

  function measure(nodeId: number): number {
    const children = childMap.get(nodeId) ?? [];
    if (!children.length) {
      subtreeWidth.set(nodeId, nodeW);
      return nodeW;
    }
    const width = Math.max(nodeW, children.reduce((sum, childId) => sum + measure(childId), 0) + xGap * (children.length - 1));
    subtreeWidth.set(nodeId, width);
    return width;
  }

  const root = nodes.find((node) => node.depth === 0) ?? nodes[0];
  const treeWidth = measure(root.id);
  const width = Math.max(980, sidePad * 2 + treeWidth);
  const height = topPad * 2 + (maxDepth + 1) * nodeH + maxDepth * (yGap - nodeH);
  const positions = new Map<number, { x: number; y: number }>();

  function place(nodeId: number, left: number): void {
    const node = nodeById.get(nodeId);
    if (!node) return;
    const currentWidth = subtreeWidth.get(nodeId) ?? nodeW;
    positions.set(nodeId, {
      x: left + currentWidth / 2,
      y: topPad + node.depth * yGap + nodeH / 2,
    });
    let childLeft = left;
    (childMap.get(nodeId) ?? []).forEach((childId) => {
      place(childId, childLeft);
      childLeft += (subtreeWidth.get(childId) ?? nodeW) + xGap;
    });
  }

  place(root.id, (width - treeWidth) / 2);

  return (
    <div className="overflow-auto rounded-2xl border border-slate-200 bg-slate-50 p-4">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold text-slate-900">Decision Path Diagram</h3>
          <p className="mt-1 text-xs text-slate-500">Blue nodes are lower event-rate segments; amber/red nodes are higher event-rate segments.</p>
        </div>
        <div className="flex flex-wrap gap-2 text-[11px] font-medium">
          <span className="rounded-full bg-blue-100 px-2 py-1 text-blue-700">Low rate</span>
          <span className="rounded-full bg-amber-100 px-2 py-1 text-amber-700">Moderate</span>
          <span className="rounded-full bg-rose-100 px-2 py-1 text-rose-700">High rate</span>
        </div>
      </div>
      <svg viewBox={`0 0 ${width} ${height}`} className="rounded-xl bg-white shadow-sm" style={{ minWidth: width }}>
        {edges.map((edge) => {
          const sourcePos = positions.get(edge.source);
          const targetPos = positions.get(edge.target);
          if (!sourcePos || !targetPos) return null;
          const sx = sourcePos.x;
          const sy = sourcePos.y + nodeH / 2;
          const tx = targetPos.x;
          const ty = targetPos.y - nodeH / 2;
          return (
            <g key={`${edge.source}-${edge.target}`}>
              <path d={`M ${sx} ${sy} C ${sx} ${(sy + ty) / 2}, ${tx} ${(sy + ty) / 2}, ${tx} ${ty}`} fill="none" stroke="#94a3b8" strokeWidth={1.6} />
              <rect x={(sx + tx) / 2 - 18} y={(sy + ty) / 2 - 16} width={36} height={18} rx={9} fill="#ffffff" stroke="#cbd5e1" />
              <text x={(sx + tx) / 2} y={(sy + ty) / 2 - 3} textAnchor="middle" className="fill-slate-500 text-[10px] font-semibold">
                {edge.label}
              </text>
            </g>
          );
        })}
        {nodes.map((node) => {
          const position = positions.get(node.id);
          if (!position) return null;
          const nx = position.x - nodeW / 2;
          const ny = position.y - nodeH / 2;
          return (
            <g key={node.id}>
              <rect x={nx} y={ny} width={nodeW} height={nodeH} rx={12} fill={fillForRate(node.positive_rate)} stroke={strokeForRate(node.positive_rate)} strokeWidth={1.4} />
              <text x={nx + 12} y={ny + 19} className="fill-slate-900 text-[11px] font-semibold">
                {node.leaf ? `Leaf: ${truncateTreeLabel(node.prediction, 17)}` : truncateTreeLabel(`${node.feature} <= ${formatThreshold(node.threshold)}`, 23)}
              </text>
              <text x={nx + 12} y={ny + 40} className="fill-slate-700 text-[10px]">
                Event rate {(node.positive_rate * 100).toFixed(1)}%
              </text>
              <text x={nx + 12} y={ny + 56} className="fill-slate-600 text-[10px]">
                Samples {node.samples.toLocaleString()}
              </text>
              <rect x={nx + 12} y={ny + 64} width={nodeW - 24} height={5} rx={2.5} fill="#e2e8f0" />
              <rect x={nx + 12} y={ny + 64} width={(nodeW - 24) * Math.min(1, Math.max(0, node.positive_rate))} height={5} rx={2.5} fill={node.positive_rate >= 0.5 ? "#e11d48" : "#2563eb"} opacity={0.85} />
            </g>
          );
        })}
      </svg>
    </div>
  );
}

function buildLeafRules(nodes: TreeNode[], edges: TreeEdge[]) {
  const childEdges = new Map<number, TreeEdge[]>();
  edges.forEach((edge) => childEdges.set(edge.source, [...(childEdges.get(edge.source) ?? []), edge]));
  const nodeById = new Map(nodes.map((node) => [node.id, node]));
  const root = nodes.find((node) => node.depth === 0) ?? nodes[0];
  const rules: { id: number; prediction: string; positiveRate: number; samples: number; conditions: string[] }[] = [];

  function walk(node: TreeNode, conditions: string[]) {
    const outgoing = childEdges.get(node.id) ?? [];
    if (node.leaf || !outgoing.length) {
      rules.push({
        id: node.id,
        prediction: node.prediction,
        positiveRate: node.positive_rate,
        samples: node.samples,
        conditions,
      });
      return;
    }
    outgoing.forEach((edge) => {
      const child = nodeById.get(edge.target);
      if (!child) return;
      walk(child, [...conditions, splitConditionLabel(node, edge.label)]);
    });
  }

  if (root) walk(root, []);
  return rules.sort((a, b) => b.samples - a.samples);
}

function splitConditionLabel(node: TreeNode, edgeLabel: string) {
  const threshold = formatThreshold(node.threshold);
  const feature = node.feature ?? "split";
  const label = edgeLabel.toLowerCase();
  if (label.includes("yes") || label.includes("true") || label.includes("<=")) return `${feature} <= ${threshold}`;
  if (label.includes("no") || label.includes("false") || label.includes(">")) return `${feature} > ${threshold}`;
  return `${feature}: ${edgeLabel}`;
}

function TreeTextFallback({ text }: { text: string }) {
  const lines = text.split("\n").filter(Boolean).slice(0, 40);
  return (
    <details className="rounded-xl border border-slate-200 bg-white p-4">
      <summary className="cursor-pointer text-sm font-semibold text-slate-800">Show text export</summary>
      <pre className="mt-3 max-h-[280px] overflow-auto rounded-lg bg-slate-50 p-3 text-xs leading-5 text-slate-700">
        {lines.join("\n") || "No text export available."}
      </pre>
    </details>
  );
}

function formatThreshold(value: number | null | undefined) {
  return typeof value === "number" && Number.isFinite(value) ? value.toFixed(3) : "-";
}

function truncateTreeLabel(value: string, maxLength: number) {
  return value.length > maxLength ? `${value.slice(0, Math.max(0, maxLength - 1))}...` : value;
}

function fillForRate(rate: number) {
  if (rate < 0.2) return "#dbeafe";
  if (rate < 0.4) return "#bfdbfe";
  if (rate < 0.6) return "#fef3c7";
  if (rate < 0.8) return "#fed7aa";
  return "#fee2e2";
}

function strokeForRate(rate: number) {
  if (rate < 0.4) return "#2563eb";
  if (rate < 0.6) return "#d97706";
  return "#e11d48";
}

function formatNumber(value: number | null | undefined, digits = 4) {
  return typeof value === "number" && Number.isFinite(value) ? value.toFixed(digits) : "-";
}

function MetricTile({
  label,
  value,
  tone = "slate",
}: {
  label: string;
  value: string;
  tone?: "emerald" | "slate" | "indigo" | "amber";
}) {
  const toneClass =
    tone === "emerald"
      ? "border-emerald-200 bg-emerald-50 text-emerald-900"
      : tone === "indigo"
        ? "border-indigo-200 bg-indigo-50 text-indigo-900"
        : tone === "amber"
          ? "border-amber-200 bg-amber-50 text-amber-900"
          : "border-slate-200 bg-slate-50 text-slate-900";
  return (
    <div className={`rounded-xl border px-3 py-3 ${toneClass}`}>
      <div className="text-[11px] font-semibold uppercase tracking-wide opacity-70">{label}</div>
      <div className="mt-1 text-lg font-semibold">{value}</div>
    </div>
  );
}

function BarTable({ rows, valueKey, color = "indigo" }: { rows: ImportanceRow[]; valueKey: "importance"; color?: "indigo" | "teal" }) {
  const top = rows.slice(0, 15);
  const max = Math.max(...top.map((row) => Math.abs(row[valueKey])), 1e-9);
  const barColor = color === "teal" ? "bg-teal-600" : "bg-indigo-600";
  return (
    <div className="mt-3 space-y-2">
      {top.map((row) => (
        <div key={`${row.feature}-${row.source ?? ""}`} className="grid grid-cols-[180px_1fr_90px] items-center gap-3 text-xs">
          <div className="truncate font-medium text-gray-700">{row.feature}</div>
          <div className="h-2 rounded-full bg-gray-100">
            <div className={`h-2 rounded-full ${barColor}`} style={{ width: `${Math.max(3, (Math.abs(row[valueKey]) / max) * 100)}%` }} />
          </div>
          <div className="text-right text-gray-600">
            {row[valueKey].toFixed(4)}
            {typeof row.direction === "number" && row.direction !== 0 && (
              <span className={row.direction >= 0 ? "ml-1 text-emerald-600" : "ml-1 text-rose-600"}>
                {row.direction >= 0 ? "+" : "-"}
              </span>
            )}
          </div>
        </div>
      ))}
      {!top.length && <div className="text-sm text-gray-500">No importance data available.</div>}
    </div>
  );
}

function DecisionBoundaryChart({ boundary }: { boundary: BoundaryResponse | null }) {
  if (!boundary) return <div className="mt-3 rounded-xl bg-slate-50 p-4 text-sm text-gray-500">Loading decision boundary...</div>;
  if (!boundary.ok) return <div className="mt-3 rounded-xl bg-amber-50 p-4 text-sm text-amber-900">{boundary.error ?? "Decision boundary unavailable."}</div>;
  const grid = boundary.grid ?? [];
  const points = boundary.points ?? [];
  const [xMin, xMax] = boundary.x_domain ?? [0, 1];
  const [yMin, yMax] = boundary.y_domain ?? [0, 1];
  const width = 880;
  const height = 430;
  const pad = 54;
  const plotWidth = width - pad - 24;
  const plotHeight = height - pad - 24;
  const resolution = boundary.resolution ?? 60;
  const cellW = plotWidth / resolution + 0.5;
  const cellH = plotHeight / resolution + 0.5;
  const x = (value: number) => pad + ((value - xMin) / (xMax - xMin || 1)) * plotWidth;
  const y = (value: number) => 18 + ((yMax - value) / (yMax - yMin || 1)) * plotHeight;
  const scores = grid.map((cell) => cell.score).filter(Number.isFinite);
  const scoreMin = scores.length ? Math.max(0, Math.min(...scores)) : 0;
  const scoreMax = scores.length ? Math.min(1, Math.max(...scores)) : 1;
  const scoreRange = Math.max(scoreMax - scoreMin, 1e-9);
  const bandColors = ["#dbeafe", "#bfdbfe", "#fde68a", "#fdba74", "#fecaca"];
  const bandIndex = (score: number) => Math.max(0, Math.min(4, Math.floor(((score - scoreMin) / scoreRange) * 5)));
  const color = (score: number) => {
    if (scoreRange <= 1e-8) return bandColors[0];
    return bandColors[bandIndex(score)];
  };
  const pointColor = (classValue: number) => (classValue ? "#facc15" : "#4c1d95");
  const bandLabel = (index: number) => {
    const low = scoreMin + (scoreRange * index) / 5;
    const high = scoreMin + (scoreRange * (index + 1)) / 5;
    return `${(low * 100).toFixed(1)}-${(high * 100).toFixed(1)}%`;
  };

  return (
    <div className="mt-3 rounded-xl bg-slate-50 p-3">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-3 text-xs text-slate-600">
        <div className="flex flex-wrap items-center gap-2">
          {bandColors.map((fill, index) => (
            <span key={fill} className="inline-flex items-center gap-1">
              <span className="h-2.5 w-4 rounded-sm border border-slate-200" style={{ background: fill }} />
              {bandLabel(index)}
            </span>
          ))}
        </div>
        <div className="flex items-center gap-3">
          <span className="inline-flex items-center gap-1"><span className="h-2.5 w-2.5 rounded-full bg-[#4c1d95]" />Class 0</span>
          <span className="inline-flex items-center gap-1"><span className="h-2.5 w-2.5 rounded-full bg-[#facc15] ring-1 ring-slate-800" />Class 1</span>
        </div>
      </div>
      <svg viewBox={`0 0 ${width} ${height}`} className="h-[430px] w-full rounded-xl bg-white">
        {grid.map((cell, index) => (
          <rect
            key={index}
            x={x(cell.x) - cellW / 2}
            y={y(cell.y) - cellH / 2}
            width={cellW}
            height={cellH}
            fill={color(cell.score)}
            opacity={0.92}
          />
        ))}
        <line x1={pad} y1={height - pad} x2={width - 24} y2={height - pad} stroke="#64748b" />
        <line x1={pad} y1={18} x2={pad} y2={height - pad} stroke="#64748b" />
        {points.map((point, index) => (
          <circle
            key={index}
            cx={x(point.x)}
            cy={y(point.y)}
            r={3.2}
            fill={pointColor(point.class)}
            stroke="#111827"
            strokeWidth={0.8}
            opacity={0.88}
          />
        ))}
        <text x={width / 2} y={height - 12} textAnchor="middle" className="fill-slate-700 text-[11px]">{boundary.x_feature}</text>
        <text x={16} y={height / 2} textAnchor="middle" transform={`rotate(-90 16 ${height / 2})`} className="fill-slate-700 text-[11px]">{boundary.y_feature}</text>
        <text x={pad} y={height - 34} className="fill-slate-500 text-[10px]">{xMin.toFixed(3)}</text>
        <text x={width - 24} y={height - 34} textAnchor="end" className="fill-slate-500 text-[10px]">{xMax.toFixed(3)}</text>
      </svg>
    </div>
  );
}

function HyperparameterTable({ rows }: { rows: HyperparameterRow[] }) {
  if (!rows.length) {
    return <div className="mt-3 text-sm text-gray-500">No grid-search settings were recorded for this model. Default estimator settings are being used.</div>;
  }
  return (
    <div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
      {rows.map((row) => (
        <div key={row.parameter} className="rounded-lg border border-gray-100 bg-slate-50 px-3 py-2">
          <div className="text-[11px] font-semibold uppercase text-gray-500">{row.parameter}</div>
          <div className="mt-1 truncate text-sm text-gray-900" title={row.value}>{row.value}</div>
        </div>
      ))}
    </div>
  );
}

function LineChart({ title, rows, feature }: { title: string; rows: CurveRow[]; feature: string }) {
  if (!rows.length) return <div className="text-sm text-gray-500">No PDP data available.</div>;
  const width = 520;
  const height = 260;
  const pad = 46;
  const values = rows.map((row) => row.prediction);
  const rawMin = Math.min(...values);
  const rawMax = Math.max(...values);
  const spread = Math.max(rawMax - rawMin, 0.001);
  const minY = rawMin - spread * 0.2;
  const maxY = rawMax + spread * 0.2;
  const plotWidth = width - pad - 18;
  const plotHeight = height - pad - 24;
  const x = (index: number) => pad + (index / Math.max(1, rows.length - 1)) * plotWidth;
  const y = (value: number) => 18 + ((maxY - value) / (maxY - minY || 1)) * plotHeight;
  const points = rows.map((row, index) => `${x(index)},${y(row.prediction)}`).join(" ");
  const first = rows[0];
  const last = rows[rows.length - 1];
  return (
    <div>
      <div className="mb-2 text-xs font-semibold text-gray-700">{title}</div>
      <svg viewBox={`0 0 ${width} ${height}`} className="h-[260px] w-full rounded-xl bg-slate-50">
        <line x1={pad} y1={height - pad} x2={width - 18} y2={height - pad} stroke="#cbd5e1" />
        <line x1={pad} y1={18} x2={pad} y2={height - pad} stroke="#cbd5e1" />
        {[0, 0.5, 1].map((tick) => {
          const value = minY + (maxY - minY) * tick;
          const yy = y(value);
          return (
            <g key={tick}>
              <line x1={pad} y1={yy} x2={width - 18} y2={yy} stroke="#e2e8f0" />
              <text x={pad - 8} y={yy + 4} textAnchor="end" className="fill-slate-500 text-[10px]">
                {value.toFixed(3)}
              </text>
            </g>
          );
        })}
        <polyline fill="none" stroke="#4f46e5" strokeWidth="3" points={points} />
        {rows.map((row, index) => (
          <circle key={`${row.label ?? row.value}-${index}`} cx={x(index)} cy={y(row.prediction)} r={3} fill="#4f46e5" />
        ))}
        {first && <text x={pad} y={height - 12} className="fill-slate-500 text-[10px]">{first.label ?? first.value}</text>}
        {last && <text x={width - 18} y={height - 12} textAnchor="end" className="fill-slate-500 text-[10px]">{last.label ?? last.value}</text>}
        <text x={width / 2} y={height - 12} textAnchor="middle" className="fill-slate-600 text-[10px]">{feature}</text>
      </svg>
    </div>
  );
}

function RfeCurveChart({
  rows,
  selectedCount,
  recommendedCount,
  onSelectCount,
  isRegression = false,
}: {
  rows: RfeCurveRow[];
  selectedCount: number;
  recommendedCount: number | null;
  onSelectCount: (count: number) => void;
  isRegression?: boolean;
}) {
  if (!rows.length) {
    return <div className="mt-4 rounded-xl bg-slate-50 p-4 text-sm text-gray-500">Run RFE to generate the {isRegression ? "RMSE" : "AUC"} and marginal-benefit curve.</div>;
  }

  const width = 980;
  const height = 330;
  const pad = 52;
  const metricValues = rows.map((row) => isRegression ? (row.rmse ?? row.display_rmse ?? 0) : (row.auc ?? row.display_auc ?? 0));
  const marginalValues = rows.map((row) => Math.max(0, isRegression ? (row.marginal_rmse ?? 0) : (row.marginal_auc ?? 0)));
  const metricSpread = Math.max(Math.max(...metricValues) - Math.min(...metricValues), 0.001);
  const metricMin = Math.min(...metricValues) - metricSpread * 0.08;
  const metricMax = Math.max(...metricValues) + metricSpread * 0.08;
  const marginalMax = Math.max(...marginalValues, 0.001);
  const plotWidth = width - pad - 24;
  const plotHeight = height - pad - 28;
  const barSlot = plotWidth / rows.length;
  const barWidth = Math.max(6, Math.min(22, barSlot * 0.62));
  const x = (index: number) => pad + index * barSlot + barSlot / 2;
  const yMetric = (value: number) => 18 + ((metricMax - value) / (metricMax - metricMin || 1)) * plotHeight;
  const yMarginal = (value: number) => 18 + ((marginalMax - Math.max(0, value)) / marginalMax) * plotHeight;
  const marginalPoints = rows
    .map((row, index) => `${x(index)},${yMarginal(isRegression ? (row.marginal_rmse ?? 0) : (row.marginal_auc ?? 0))}`)
    .join(" ");

  return (
    <div className="mt-4 rounded-xl bg-slate-50 p-3">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2 text-xs">
        <div className="font-semibold text-gray-700">RFE {isRegression ? "RMSE" : "AUC"} by Feature Count</div>
        <div className="flex gap-3 text-gray-600">
          <span><span className="mr-1 inline-block h-2 w-3 rounded-sm bg-indigo-500" />{isRegression ? "RMSE" : "AUC"}</span>
          <span><span className="mr-1 inline-block h-2 w-3 rounded-sm bg-emerald-500" />Marginal {isRegression ? "RMSE gain" : "AUC"}</span>
          {recommendedCount && <span>Suggested elbow: {recommendedCount} features</span>}
        </div>
      </div>
      <svg viewBox={`0 0 ${width} ${height}`} className="h-[330px] w-full">
        <line x1={pad} y1={height - pad} x2={width - 24} y2={height - pad} stroke="#cbd5e1" />
        <line x1={pad} y1={18} x2={pad} y2={height - pad} stroke="#cbd5e1" />
        {[0, 0.5, 1].map((tick) => {
          const value = metricMin + (metricMax - metricMin) * tick;
          const yy = yMetric(value);
          return (
            <g key={tick}>
              <line x1={pad} y1={yy} x2={width - 24} y2={yy} stroke="#e2e8f0" />
              <text x={pad - 8} y={yy + 4} textAnchor="end" className="fill-slate-500 text-[10px]">{value.toFixed(3)}</text>
            </g>
          );
        })}
        {rows.map((row, index) => {
          const selected = row.feature_count === selectedCount;
          const chartMetric = isRegression ? (row.rmse ?? row.display_rmse ?? 0) : (row.auc ?? row.display_auc ?? 0);
          const barHeight = height - pad - yMetric(chartMetric);
          return (
            <g key={row.feature_count} onClick={() => onSelectCount(row.feature_count)} className="cursor-pointer">
              <rect
                x={x(index) - barWidth / 2}
                y={yMetric(chartMetric)}
                width={barWidth}
                height={barHeight}
                rx={3}
                className={selected ? "fill-indigo-700" : "fill-indigo-500"}
              />
              {row.feature_count === recommendedCount && (
                <line x1={x(index)} y1={18} x2={x(index)} y2={height - pad} stroke="#10b981" strokeDasharray="4 4" />
              )}
              {index % Math.ceil(rows.length / 12) === 0 && (
                <text x={x(index)} y={height - 30} textAnchor="middle" className="fill-slate-500 text-[10px]">{row.feature_count}</text>
              )}
            </g>
          );
        })}
        <polyline fill="none" stroke="#10b981" strokeWidth="3" points={marginalPoints} />
        {rows.map((row, index) => (
          <circle key={`m-${row.feature_count}`} cx={x(index)} cy={yMarginal(isRegression ? (row.marginal_rmse ?? 0) : (row.marginal_auc ?? 0))} r={3} fill="#10b981" />
        ))}
        <text x={width / 2} y={height - 8} textAnchor="middle" className="fill-slate-600 text-[10px]">Number of features retained</text>
      </svg>
    </div>
  );
}

function SensitivityTable({ rows }: { rows: SensitivityRow[] }) {
  return (
    <div>
      <div className="mb-2 text-xs font-semibold text-gray-700">Sensitivity Analysis</div>
      <table className="w-full text-sm">
        <thead><tr className="text-left text-xs text-gray-500"><th className="py-1">Scenario</th><th>Prediction</th><th>Delta</th></tr></thead>
        <tbody>{rows.map((row) => <tr key={row.scenario} className="border-t"><td className="py-1">{row.scenario}</td><td>{row.prediction.toFixed(4)}</td><td className={row.delta >= 0 ? "text-emerald-700" : "text-rose-700"}>{row.delta.toFixed(4)}</td></tr>)}</tbody>
      </table>
    </div>
  );
}

function SensitivitySummaryTable({ rows }: { rows: SensitivitySummaryRow[] }) {
  if (!rows.length) return <div className="mt-3 text-sm text-gray-500">No model-level sensitivity rows are available.</div>;
  const maxDelta = Math.max(...rows.map((row) => row.max_abs_delta), 1e-9);
  return (
    <div className="mt-4 overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-xs text-gray-500">
            <th className="py-2 pr-4">Feature</th>
            <th className="py-2 pr-4">Largest Scenario</th>
            <th className="py-2 pr-4">Prediction</th>
            <th className="py-2 pr-4">Delta</th>
            <th className="py-2">Relative Impact</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.feature} className="border-t">
              <td className="py-2 pr-4 font-medium text-gray-800">{row.feature}</td>
              <td className="py-2 pr-4">{row.worst_scenario}</td>
              <td className="py-2 pr-4">{row.worst_prediction.toFixed(4)}</td>
              <td className={`py-2 pr-4 ${row.worst_delta >= 0 ? "text-emerald-700" : "text-rose-700"}`}>
                {row.worst_delta.toFixed(4)}
              </td>
              <td className="py-2">
                <div className="h-2 rounded-full bg-gray-100">
                  <div
                    className="h-2 rounded-full bg-indigo-600"
                    style={{ width: `${Math.max(3, (row.max_abs_delta / maxDelta) * 100)}%` }}
                  />
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function VsiTable({ rows }: { rows: VsiRow[] }) {
  if (!rows.length) return <div className="mt-3 text-sm text-gray-500">No VSI rows are available.</div>;
  const statusClass = (status: VsiRow["status"]) => {
    if (status === "pass") return "bg-emerald-50 text-emerald-900 border-emerald-100";
    if (status === "warning") return "bg-amber-50 text-amber-900 border-amber-100";
    return "bg-rose-50 text-rose-900 border-rose-100";
  };
  return (
    <div className="mt-4 overflow-x-auto rounded-lg border border-gray-200">
      <table className="w-full text-sm">
        <thead className="bg-slate-50 text-left text-xs uppercase text-slate-500">
          <tr>
            <th className="px-3 py-2">Feature</th>
            <th className="px-3 py-2">VSI</th>
            <th className="px-3 py-2">Status</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.feature} className={`border-t ${statusClass(row.status)}`}>
              <td className="px-3 py-2 font-medium">{row.feature}</td>
              <td className="px-3 py-2">{row.value.toFixed(4)}</td>
              <td className="px-3 py-2 font-semibold uppercase">{row.status}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function VifTable({ rows }: { rows: VifRow[] }) {
  if (!rows.length) return <div className="mt-3 text-sm text-gray-500">VIF requires at least two numeric final-model variables.</div>;
  const statusClass = (status: VifRow["status"]) => {
    if (status === "pass") return "bg-emerald-50 text-emerald-900 border-emerald-100";
    if (status === "warning") return "bg-amber-50 text-amber-900 border-amber-100";
    return "bg-rose-50 text-rose-900 border-rose-100";
  };
  return (
    <div className="mt-4 overflow-x-auto rounded-lg border border-gray-200">
      <table className="w-full text-sm">
        <thead className="bg-slate-50 text-left text-xs uppercase text-slate-500">
          <tr>
            <th className="px-3 py-2">Feature</th>
            <th className="px-3 py-2">VIF</th>
            <th className="px-3 py-2">Tolerance</th>
            <th className="px-3 py-2">R-Squared</th>
            <th className="px-3 py-2">Status</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.feature} className={`border-t ${statusClass(row.status)}`}>
              <td className="px-3 py-2 font-medium">{row.feature}</td>
              <td className="px-3 py-2">{row.vif.toFixed(3)}</td>
              <td className="px-3 py-2">{row.tolerance.toFixed(4)}</td>
              <td className="px-3 py-2">{row.r_squared.toFixed(4)}</td>
              <td className="px-3 py-2 font-semibold uppercase">{row.status}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="border-t bg-white px-3 py-2 text-xs text-slate-500">
        Thresholds: pass &lt; 5, warning 5-10, fail &gt;= 10.
      </div>
    </div>
  );
}

function RfeTable({ rows, selectedCount }: { rows: RfeRow[]; selectedCount: number }) {
  if (!rows.length) return <div className="mt-3 text-sm text-gray-500">Run RFE to rank candidate features.</div>;
  return (
    <table className="mt-4 w-full text-sm">
      <thead><tr className="text-left text-xs text-gray-500"><th className="py-1">Feature</th><th>Selected</th><th>Rank</th><th>Importance</th></tr></thead>
      <tbody>{rows.map((row) => {
        const selected = row.rank <= selectedCount;
        return <tr key={row.feature} className="border-t"><td className="py-1">{row.feature}</td><td>{selected ? "Yes" : "No"}</td><td>{row.rank}</td><td>{typeof row.importance === "number" ? row.importance.toFixed(4) : "-"}</td></tr>;
      })}</tbody>
    </table>
  );
}
