import React, { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import StepPythonPanel from "../components/StepPythonPanel";
import { logDecision } from "../lib/decisionJournal";
import { useWorkflowStore } from "../state/useWorkflowStore";

const API_BASE =
  (import.meta.env.VITE_API_BASE as string | undefined)?.replace(/\/$/, "") ||
  "http://127.0.0.1:8001/api";

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
  const [recommendedCount, setRecommendedCount] = useState<number | null>(null);
  const [bestRfeCount, setBestRfeCount] = useState<number | null>(null);
  const [bestRfeAuc, setBestRfeAuc] = useState<number | null>(null);
  const [bestRfeRmse, setBestRfeRmse] = useState<number | null>(null);
  const [rfeAucTolerance, setRfeAucTolerance] = useState<number | null>(null);
  const [rfeRmseTolerance, setRfeRmseTolerance] = useState<number | null>(null);
  const [boundary, setBoundary] = useState<BoundaryResponse | null>(null);
  const [boundaryX, setBoundaryX] = useState("");
  const [boundaryY, setBoundaryY] = useState("");
  const [message, setMessage] = useState("");
  const [finalModelMessage, setFinalModelMessage] = useState("");
  const [finalModelStatus, setFinalModelStatus] = useState<"success" | "error" | "">("");
  const [savingFinalModel, setSavingFinalModel] = useState(false);
  const [finalModelReady, setFinalModelReady] = useState(false);
  const isRegression = models.some((model) => model.task === "regression" || model.rmse !== undefined);

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
        setRfeRows([]);
        setRfeCurve([]);
        setRecommendedCount(null);
        setBestRfeCount(null);
        setBestRfeAuc(null);
        setBestRfeRmse(null);
        setRfeAucTolerance(null);
        setRfeRmseTolerance(null);
        setFinalModelReady(false);
        setFinalDiagnosticsReady(false);
        setFinalModelMessage("");
        setFinalModelStatus("");
        setFinalSensitivityRows([]);
        setVifRows([]);
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
        setRfeKeep(data.recommended_count ?? data.best_count ?? rfeKeep);
      })
      .catch((err) => setMessage(String(err?.message ?? err)))
      .finally(() => setRfeRunning(false));
  };

  useEffect(() => {
    if (!selectedModel) return;
    runRfe();
  }, [selectedModel]);

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
        <ModelDetails details={details} />
      </section>

      <section className="rounded-2xl border border-gray-200 bg-white p-4">
        <h2 className="text-sm font-semibold">Final Hyperparameter Settings</h2>
        <HyperparameterTable rows={hyperparameters} />
      </section>

      <section className="rounded-2xl border border-gray-200 bg-white p-4">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h2 className="text-sm font-semibold">{isRegression ? "Prediction Response Surface" : "Decision Boundary"}</h2>
            <p className="mt-1 text-xs text-gray-500">
              {isRegression
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
            {isRegression
              ? "Appropriate for regression: ranks variables by contribution to predictive accuracy."
              : "Ranks variables by contribution to model performance."}
          </p>
          <BarTable rows={importance} valueKey="importance" color="indigo" />
        </section>
        <section className="rounded-2xl border border-gray-200 bg-white p-4">
          <h2 className="text-sm font-semibold">SHAP Summary</h2>
          <p className="mt-1 text-xs text-gray-500">
            {isRegression
              ? "Appropriate for regression: estimates how each feature changes predicted target values on holdout records."
              : "Model-agnostic replacement impact on held-out predictions. This differs from native feature importance."}
          </p>
          <BarTable rows={shapRows} valueKey="importance" color="teal" />
        </section>
      </div>

      <section className="rounded-2xl border border-gray-200 bg-white p-4">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h2 className="text-sm font-semibold">{isRegression ? "Prediction Drivers" : "PDP / Sensitivity"}</h2>
            <p className="mt-1 text-xs text-gray-500">
              {isRegression
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
          <LineChart title={isRegression ? "Partial Dependence: Predicted Target" : "Partial Dependence Plot"} rows={pdp} feature={selectedFeature} />
          <SensitivityTable rows={sensitivity} />
        </div>
      </section>

      <section className="rounded-2xl border border-gray-200 bg-white p-4">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h2 className="text-sm font-semibold">Recursive Feature Elimination</h2>
            <p className="mt-1 text-xs text-gray-500">
              {isRegression
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
        {recommendedCount && bestRfeCount && bestRfeAuc !== null && (
          <div className="mt-3 rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-700">
            Best RFE point: {bestRfeCount} features at AUC {bestRfeAuc.toFixed(4)}. Recommended count uses a {((rfeAucTolerance ?? 0.001) * 100).toFixed(2)} percentage-point AUC tolerance.
          </div>
        )}
        {recommendedCount && bestRfeCount && bestRfeRmse !== null && (
          <div className="mt-3 rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-700">
            Best RFE point: {bestRfeCount} features at RMSE {bestRfeRmse.toFixed(4)}. Recommended count uses a {rfeRmseTolerance?.toFixed(4) ?? "small"} RMSE tolerance.
          </div>
        )}
        <RfeCurveChart rows={rfeCurve} selectedCount={rfeKeep} recommendedCount={recommendedCount} onSelectCount={setRfeKeep} isRegression={isRegression} />
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

      {!isRegression && <section className="rounded-2xl border border-gray-200 bg-white p-4">
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

      {!isRegression && <section className="rounded-2xl border border-gray-200 bg-white p-4">
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
            markComplete("step09");
            navigate("/step10");
          }}
        >
          Mark Complete & Next Step
        </button>
      </div>
    </div>
  );
}

function ModelDetails({ details }: { details: DetailResponse | null }) {
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
    return <pre className="mt-3 max-h-[360px] overflow-auto rounded-lg bg-slate-950 p-4 text-xs text-slate-100">{details.tree_text}</pre>;
  }
  return <div className="mt-3 text-sm text-gray-600">{details.message}</div>;
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
  const metricValues = rows.map((row) => isRegression ? (row.display_rmse ?? row.rmse ?? 0) : (row.display_auc ?? row.auc ?? 0));
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
          const chartMetric = isRegression ? (row.display_rmse ?? row.rmse ?? 0) : (row.display_auc ?? row.auc ?? 0);
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
