import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import StepPythonPanel from "../components/StepPythonPanel";
import { useWorkflowStore } from "../state/useWorkflowStore";
import { upsertProjectFromState } from "../lib/localProjects";

const API_BASE =
  (import.meta.env.VITE_API_BASE as string | undefined)?.replace(/\/$/, "") ||
  "http://127.0.0.1:8001/api";

type Status = "pass" | "warning" | "fail";
type ScoreResult = {
  ok: boolean;
  task?: "classification" | "regression";
  error?: string;
  dataset_type?: string;
  rows?: number;
  model?: { name?: string; feature_count?: number; features?: string[] };
  score_summary?: { min: number | null; mean: number | null; max: number | null };
  adjusted_score_summary?: { min: number | null; mean: number | null; max: number | null };
  probability_correction?: {
    method?: string;
    original_prior?: number | null;
    model_prior?: number | null;
    default_original_prior?: number | null;
    default_model_prior?: number | null;
  };
  metrics?: Record<string, any>;
  scoring_diagnostics?: {
    model_feature_count?: number;
    matched_feature_count?: number;
    missing_features?: string[];
    prediction_std?: number | null;
    constant_prediction?: boolean;
  };
  lift?: LiftRow[];
  psi?: { name: string; value: number; status: Status };
  vsi?: { feature: string; value: number; status: Status }[];
  vsi_scope?: "model_features" | "all_common_features";
  stability_reference?: "uploaded_test" | "development_split";
  preview?: { row: number; score: number; adjusted_score?: number; prediction: number }[];
};
type LiftRow = {
  decile: number;
  n: number;
  positives: number;
  event_rate: number;
  lift: number;
  cumulative_positives: number;
  capture_rate: number;
  min_score: number;
  max_score: number;
  mean_score: number;
};

function statusClass(status?: Status) {
  if (status === "pass") return "border-emerald-200 bg-emerald-50 text-emerald-900";
  if (status === "warning") return "border-amber-200 bg-amber-50 text-amber-900";
  if (status === "fail") return "border-rose-200 bg-rose-50 text-rose-900";
  return "border-slate-200 bg-slate-50 text-slate-900";
}

function format(value: unknown) {
  return typeof value === "number" && Number.isFinite(value) ? value.toFixed(4) : "-";
}

async function uploadScore(
  file: File,
  datasetType: "test" | "oot",
  options: { correctionMethod: string; originalPrior: string; modelPrior: string }
) {
  const body = new FormData();
  body.append("file", file);
  const params = new URLSearchParams({
    dataset_type: datasetType,
    model: "final",
    correction_method: options.correctionMethod,
  });
  const originalPriorValue = Number(options.originalPrior);
  const modelPriorValue = Number(options.modelPrior);
  if (options.originalPrior.trim() && Number.isFinite(originalPriorValue)) params.set("original_prior", String(originalPriorValue));
  if (options.modelPrior.trim() && Number.isFinite(modelPriorValue)) params.set("model_prior", String(modelPriorValue));
  const res = await fetch(`${API_BASE}/score/upload?${params.toString()}`, {
    method: "POST",
    body,
  });
  if (!res.ok) throw new Error(`Scoring failed (${res.status})`);
  const data = (await res.json()) as ScoreResult;
  if (!data.ok) throw new Error(data.error ?? "Scoring failed.");
  return data;
}

export default function Step10Scoring() {
  const navigate = useNavigate();
  const markComplete = useWorkflowStore((state) => state.markComplete);
  const [testResult, setTestResult] = useState<ScoreResult | null>(null);
  const [ootResult, setOotResult] = useState<ScoreResult | null>(null);
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState<"test" | "oot" | "">("");
  const [correctionMethod, setCorrectionMethod] = useState("none");
  const [originalPrior, setOriginalPrior] = useState("");
  const [modelPrior, setModelPrior] = useState("");
  const [problemType, setProblemType] = useState<"classification" | "regression">("classification");
  const [navigationError, setNavigationError] = useState("");

  useEffect(() => {
    fetch(`${API_BASE}/train/last`)
      .then((res) => res.json())
      .then((data) => {
        const ranked = data?.summary?.ranked ?? [];
        if (data?.summary?.problem_type === "regression" || ranked.some((row: any) => row.task === "regression")) {
          setProblemType("regression");
          setCorrectionMethod("none");
        }
      })
      .catch(() => {});
  }, []);

  async function handleFile(file: File | undefined, datasetType: "test" | "oot") {
    if (!file) return;
    setMessage("");
    setLoading(datasetType);
    try {
      const data = await uploadScore(file, datasetType, { correctionMethod, originalPrior, modelPrior });
      if (!originalPrior && typeof data.probability_correction?.default_original_prior === "number") {
        setOriginalPrior(String(data.probability_correction.default_original_prior));
      }
      if (!modelPrior && typeof data.probability_correction?.default_model_prior === "number") {
        setModelPrior(String(data.probability_correction.default_model_prior));
      }
      if (datasetType === "test") setTestResult(data);
      else setOotResult(data);
    } catch (err: any) {
      setMessage(err?.message ?? "Scoring failed.");
    } finally {
      setLoading("");
    }
  }

  async function handleContinue() {
    try {
      setNavigationError("");
      markComplete("step10");
      await upsertProjectFromState(useWorkflowStore.getState());
      navigate("/step11");
      window.scrollTo({ top: 0, left: 0 });
    } catch (error: any) {
      setNavigationError(error?.message ?? "ATLAS could not save this step before navigating.");
    }
  }

  return (
    <div className="w-full space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-slate-950">Step 10: Final Model Scoring</h1>
        <p className="mt-1 text-sm text-slate-600">
          {problemType === "regression"
            ? "Score External Validation and Out-of-Time datasets using the saved final model. Out-of-Time scoring calculates prediction stability and VSI for input features."
            : "Score External Validation and Out-of-Time datasets using the saved final model. Out-of-Time scoring calculates score PSI and VSI for input features."}
        </p>
      </div>

      {message && <div className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900">{message}</div>}

      {problemType === "classification" && <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
        <div className="flex flex-wrap items-end gap-4">
          <label className="grid gap-1 text-sm">
            <span className="text-xs font-semibold uppercase text-slate-500">Probability Scale</span>
            <select className="rounded-md border border-slate-300 px-3 py-2" value={correctionMethod} onChange={(event) => setCorrectionMethod(event.target.value)}>
              <option value="none">Raw model probabilities</option>
              <option value="prior_odds">Prior odds correction / Pozzolo-style</option>
            </select>
          </label>
          <label className="grid gap-1 text-sm">
            <span className="text-xs font-semibold uppercase text-slate-500">Original Prior</span>
            <input className="w-36 rounded-md border border-slate-300 px-3 py-2" value={originalPrior} onChange={(event) => setOriginalPrior(event.target.value)} placeholder="auto" />
          </label>
          <label className="grid gap-1 text-sm">
            <span className="text-xs font-semibold uppercase text-slate-500">Model Prior</span>
            <input className="w-36 rounded-md border border-slate-300 px-3 py-2" value={modelPrior} onChange={(event) => setModelPrior(event.target.value)} placeholder="auto" />
          </label>
          <p className="max-w-xl text-xs text-slate-500">
            Use prior correction when the training sample was balanced and you want scores back on the original event-rate scale.
          </p>
        </div>
      </section>}

      <div className="grid gap-5 lg:grid-cols-2">
        <UploadCard
          title="External Validation Dataset"
          description="Upload a CSV with the same feature schema. If the target column is present, performance metrics are calculated."
          loading={loading === "test"}
          onFile={(file) => handleFile(file, "test")}
          result={testResult}
          problemType={problemType}
        />
        <UploadCard
          title="Out-of-Time Dataset"
          description="Upload a CSV from a later time window. PSI and VSI use the uploaded External Validation dataset as reference when available."
          loading={loading === "oot"}
          onFile={(file) => handleFile(file, "oot")}
          result={ootResult}
          showStability
          problemType={problemType}
        />
      </div>

      {problemType === "regression" && (testResult || ootResult) && (
        <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
          <h2 className="text-base font-semibold text-slate-950">Regression Scoring Comparison</h2>
          <p className="mt-1 text-sm text-slate-600">
            Compare prediction distributions, performance metrics, and feature drift between External Validation and Out-of-Time data.
          </p>
          <RegressionScoringComparison testResult={testResult} ootResult={ootResult} />
        </section>
      )}

      <StepPythonPanel />

      <div className="pb-10 flex flex-col items-center gap-3">
        {navigationError && (
          <div className="w-full max-w-2xl rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-800">
            {navigationError}
          </div>
        )}
        <button
          className="rounded-xl bg-indigo-600 px-5 py-3 text-white shadow-sm"
          onClick={handleContinue}
        >
          Mark Complete & Build Document
        </button>
      </div>
    </div>
  );
}

function UploadCard({
  title,
  description,
  loading,
  onFile,
  result,
  showStability = false,
  problemType,
}: {
  title: string;
  description: string;
  loading: boolean;
  onFile: (file: File | undefined) => void;
  result: ScoreResult | null;
  showStability?: boolean;
  problemType: "classification" | "regression";
}) {
  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h2 className="text-base font-semibold text-slate-950">{title}</h2>
          <p className="mt-1 text-sm text-slate-600">{description}</p>
        </div>
        <label className="rounded-md bg-indigo-600 px-3 py-2 text-sm font-medium text-white hover:bg-indigo-700">
          {loading ? "Scoring..." : "Upload CSV"}
          <input className="hidden" type="file" accept=".csv,text/csv" disabled={loading} onChange={(event) => onFile(event.target.files?.[0])} />
        </label>
      </div>

      {result && (
        <div className="mt-5 space-y-5">
          <div className="grid gap-3 sm:grid-cols-4">
            <Stat label="Rows" value={String(result.rows ?? "-")} />
            <Stat label={problemType === "regression" ? "Min Prediction" : "Min Score"} value={format(result.score_summary?.min)} />
            <Stat label={problemType === "regression" ? "Mean Prediction" : "Mean Score"} value={format(result.score_summary?.mean)} />
            <Stat label={problemType === "regression" ? "Max Prediction" : "Max Score"} value={format(result.score_summary?.max)} />
          </div>
          {problemType === "regression" && (
            <RegressionScoreVisual result={result} />
          )}
          {problemType === "classification" && result.probability_correction?.method && result.probability_correction.method !== "none" && (
            <div className="grid gap-3 sm:grid-cols-4">
              <Stat label="Adj Min" value={format(result.adjusted_score_summary?.min)} />
              <Stat label="Adj Mean" value={format(result.adjusted_score_summary?.mean)} />
              <Stat label="Adj Max" value={format(result.adjusted_score_summary?.max)} />
              <Stat label="Original Prior" value={format(result.probability_correction.original_prior)} />
            </div>
          )}

          {result.scoring_diagnostics?.constant_prediction && (
            <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
              <div className="font-semibold">Constant prediction warning</div>
              <div className="mt-1">
                The final model produced nearly identical predictions for every row. Matched{" "}
                {result.scoring_diagnostics.matched_feature_count ?? 0} of{" "}
                {result.scoring_diagnostics.model_feature_count ?? 0} model features.
              </div>
              {!!result.scoring_diagnostics.missing_features?.length && (
                <div className="mt-1 text-xs">
                  Missing model features: {result.scoring_diagnostics.missing_features.slice(0, 8).join(", ")}
                  {result.scoring_diagnostics.missing_features.length > 8 ? "..." : ""}
                </div>
              )}
            </div>
          )}

          {result.metrics && (
            <div>
              <h3 className="text-sm font-semibold text-slate-800">Performance Metrics</h3>
              <div className="mt-2 grid gap-2 sm:grid-cols-3">
                {Object.entries(result.metrics)
                  .filter(([key]) => key !== "confusion")
                  .map(([key, value]) => <Stat key={key} label={key.toUpperCase()} value={format(value)} />)}
              </div>
            </div>
          )}

          {problemType === "classification" && <LiftTable rows={result.lift ?? []} />}

          {showStability && result.psi && (
            <div>
              <h3 className="text-sm font-semibold text-slate-800">Stability Summary</h3>
              <div className={`mt-2 rounded-xl border px-4 py-3 ${statusClass(result.psi.status)}`}>
                <div className="text-xs font-semibold uppercase">{problemType === "regression" ? "Prediction PSI" : "PSI Score Distribution"}</div>
                <div className="mt-1 text-2xl font-semibold">{result.psi.value.toFixed(4)}</div>
                <div className="mt-1 text-xs">{result.psi.status.toUpperCase()}</div>
              </div>
              <div className="mt-2 text-xs text-slate-500">
                VSI scope: {result.vsi_scope === "model_features" ? "saved final model features" : "all common uploaded features"}
              </div>
              <div className="mt-1 text-xs text-slate-500">
                Stability reference: {result.stability_reference === "uploaded_test" ? "uploaded External Validation dataset" : "development split"}
              </div>
              <StabilityTable rows={result.vsi ?? []} />
            </div>
          )}

          <Preview rows={result.preview ?? []} problemType={problemType} />
        </div>
      )}
    </section>
  );
}

function RegressionScoreVisual({ result }: { result: ScoreResult }) {
  const predictions = (result.preview ?? []).map((row) => row.score).filter(Number.isFinite);
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-3">
      <div className="mb-2 text-sm font-semibold text-slate-800">Prediction Distribution Preview</div>
      <PredictionHistogram values={predictions} />
      <div className="mt-3 rounded-lg border border-slate-200 bg-slate-50 p-3 text-xs leading-5 text-slate-600">
        <span className="font-semibold text-slate-800">ATLAS readout: </span>
        This chart shows prediction spread and central tendency. A very narrow distribution can indicate underfit, missing features, or a scoring schema issue.
      </div>
      {result.metrics && (
        <div className="mt-3 grid gap-2 sm:grid-cols-3">
          {["rmse", "mae", "r2", "adjusted_r2", "mean_residual", "mean_abs_residual"].map((metric) => (
            result.metrics?.[metric] !== undefined ? <Stat key={metric} label={metric.toUpperCase()} value={format(result.metrics[metric])} /> : null
          ))}
        </div>
      )}
    </div>
  );
}

function RegressionScoringComparison({ testResult, ootResult }: { testResult: ScoreResult | null; ootResult: ScoreResult | null }) {
  const metricKeys = ["rmse", "mae", "mse", "r2", "adjusted_r2", "mean_residual"];
  const topVsi = [...(ootResult?.vsi ?? [])].sort((a, b) => b.value - a.value).slice(0, 8);
  return (
    <div className="mt-4 grid gap-5 xl:grid-cols-[minmax(0,1.2fr)_minmax(320px,0.8fr)]">
      <div className="rounded-xl border border-slate-200 bg-slate-50 p-4">
        <div className="text-sm font-semibold text-slate-800">Performance Comparison</div>
        <PerformanceMiniBars testResult={testResult} ootResult={ootResult} />
        <div className="mt-3 overflow-hidden rounded-xl border border-slate-200 bg-white">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-left text-xs uppercase text-slate-500">
              <tr><th className="px-3 py-2">Metric</th><th className="px-3 py-2">External Validation</th><th className="px-3 py-2">OOT</th><th className="px-3 py-2">Delta</th></tr>
            </thead>
            <tbody>
              {metricKeys.map((key) => {
                const testValue = Number(testResult?.metrics?.[key]);
                const ootValue = Number(ootResult?.metrics?.[key]);
                const delta = Number.isFinite(testValue) && Number.isFinite(ootValue) ? ootValue - testValue : NaN;
                return (
                  <tr key={key} className="border-t">
                    <td className="px-3 py-2 font-medium uppercase">{key}</td>
                    <td className="px-3 py-2">{format(testValue)}</td>
                    <td className="px-3 py-2">{format(ootValue)}</td>
                    <td className={`px-3 py-2 ${Number.isFinite(delta) && Math.abs(delta) > 0.1 ? "text-amber-700" : "text-slate-700"}`}>{format(delta)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
      <div className="rounded-xl border border-slate-200 bg-slate-50 p-4">
        <div className="text-sm font-semibold text-slate-800">Top Feature Drift by VSI</div>
        <p className="mt-1 text-xs text-slate-500">Thresholds: pass &lt; 0.10, warning 0.10-0.25, fail &gt;= 0.25.</p>
        <div className="mt-3 space-y-2">
          {topVsi.length ? topVsi.map((row) => (
            <div key={row.feature} className="grid grid-cols-[120px_minmax(0,1fr)_56px] items-center gap-2 text-xs">
              <div className="truncate font-medium" title={row.feature}>{row.feature}</div>
              <div className="relative h-3 rounded-full bg-white">
                <div className="absolute top-[-2px] h-4 border-l border-amber-500" style={{ left: "40%" }} title="Warning threshold 0.10" />
                <div className="absolute top-[-2px] h-4 border-l border-rose-500" style={{ left: "100%" }} title="Fail threshold 0.25" />
                <div className={`h-full rounded-full ${row.status === "fail" ? "bg-rose-500" : row.status === "warning" ? "bg-amber-500" : "bg-emerald-500"}`} style={{ width: `${Math.min(100, (row.value / 0.25) * 100)}%` }} />
              </div>
              <div className="text-right font-semibold">{row.value.toFixed(3)}</div>
            </div>
          )) : <div className="text-sm text-slate-500">Upload an OOT dataset to calculate VSI.</div>}
        </div>
        {topVsi.length > 0 && (
          <div className="mt-3 rounded-lg border border-slate-200 bg-white p-3 text-xs leading-5 text-slate-600">
            <span className="font-semibold text-slate-800">ATLAS readout: </span>
            {topVsi.filter((row) => row.status === "fail").length
              ? `${topVsi.filter((row) => row.status === "fail").length} top drift variables exceed the fail threshold. Review these drivers before production scoring.`
              : "Top drift variables are below the fail threshold; continue monitoring warning-level variables."}
          </div>
        )}
      </div>
    </div>
  );
}

function PerformanceMiniBars({ testResult, ootResult }: { testResult: ScoreResult | null; ootResult: ScoreResult | null }) {
  const metrics = ["rmse", "mae", "r2"];
  const rows = metrics.map((metric) => ({
    metric,
    test: Number(testResult?.metrics?.[metric]),
    oot: Number(ootResult?.metrics?.[metric]),
  }));
  const max = Math.max(1e-6, ...rows.flatMap((row) => [row.test, row.oot].filter(Number.isFinite)));
  return (
    <div className="mt-3 rounded-xl border border-slate-200 bg-white p-3">
      <div className="text-xs font-semibold uppercase text-slate-500">Metric comparison bars</div>
      <div className="mt-3 space-y-2">
        {rows.map((row) => (
          <div key={row.metric} className="grid grid-cols-[64px_minmax(0,1fr)_70px] items-center gap-2 text-xs">
            <div className="font-semibold uppercase text-slate-600">{row.metric}</div>
            <div className="space-y-1">
              <div className="h-2 rounded-full bg-slate-100"><div className="h-full rounded-full bg-blue-500" style={{ width: `${Number.isFinite(row.test) ? Math.max(2, (row.test / max) * 100) : 0}%` }} /></div>
              <div className="h-2 rounded-full bg-slate-100"><div className="h-full rounded-full bg-teal-500" style={{ width: `${Number.isFinite(row.oot) ? Math.max(2, (row.oot / max) * 100) : 0}%` }} /></div>
            </div>
            <div className="text-right text-slate-600">EV/OOT</div>
          </div>
        ))}
      </div>
    </div>
  );
}

function PredictionHistogram({ values }: { values: number[] }) {
  const width = 520;
  const height = 230;
  const pad = 44;
  if (!values.length) return <div className="flex h-[160px] items-center justify-center text-sm text-slate-500">Prediction preview is not available.</div>;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const bins = 18;
  const counts = new Array(bins).fill(0);
  values.forEach((value) => {
    const index = Math.max(0, Math.min(bins - 1, Math.floor(((value - min) / (max - min || 1)) * bins)));
    counts[index] += 1;
  });
  const maxCount = Math.max(1, ...counts);
  const plotWidth = width - pad * 1.4;
  const plotHeight = height - pad * 1.5;
  const barWidth = plotWidth / bins;
  const y = (value: number) => height - pad - (value / maxCount) * plotHeight;
  const x = (value: number) => pad + ((value - min) / (max - min || 1)) * plotWidth;
  const meanPrediction = values.reduce((sum, value) => sum + value, 0) / Math.max(values.length, 1);
  const xTicks = Array.from({ length: 5 }, (_, index) => min + ((max - min) * index) / 4);
  const yTicks = Array.from({ length: 4 }, (_, index) => (maxCount * index) / 3);
  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="h-[230px] w-full rounded-xl bg-slate-50">
      {yTicks.map((tick) => (
        <g key={`pred-y-${tick}`}>
          <line x1={pad} y1={y(tick)} x2={width - pad / 2} y2={y(tick)} stroke="#e2e8f0" />
          <text x={pad - 8} y={y(tick) + 4} textAnchor="end" className="fill-slate-500 text-[10px]">{Math.round(tick)}</text>
        </g>
      ))}
      <line x1={pad} y1={height - pad} x2={width - pad / 2} y2={height - pad} stroke="#cbd5e1" />
      <line x1={pad} y1={pad / 2} x2={pad} y2={height - pad} stroke="#cbd5e1" />
      {counts.map((count, index) => {
        const x = pad + index * barWidth;
        const barY = y(count);
        return <rect key={index} x={x + 1} y={barY} width={Math.max(2, barWidth - 2)} height={height - pad - barY} rx={3} fill="#2563eb" opacity={0.75} />;
      })}
      <line x1={x(meanPrediction)} x2={x(meanPrediction)} y1={pad / 2} y2={height - pad} stroke="#dc2626" strokeWidth={2} strokeDasharray="5 5" />
      <text x={x(meanPrediction) + 4} y={pad / 2 + 12} className="fill-rose-700 text-[10px]">Mean</text>
      {xTicks.map((tick) => (
        <g key={`pred-x-${tick}`}>
          <line x1={x(tick)} x2={x(tick)} y1={height - pad} y2={height - pad + 5} stroke="#94a3b8" />
          <text x={x(tick)} y={height - pad + 18} textAnchor="middle" className="fill-slate-500 text-[10px]">{tick.toFixed(3)}</text>
        </g>
      ))}
      <text x={width / 2} y={height - 7} textAnchor="middle" className="fill-slate-600 text-[11px]">Predicted value</text>
      <text x={14} y={height / 2} textAnchor="middle" transform={`rotate(-90 14 ${height / 2})`} className="fill-slate-600 text-[11px]">Records</text>
    </svg>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-slate-100 bg-slate-50 p-3">
      <div className="text-[11px] font-semibold uppercase text-slate-500">{label}</div>
      <div className="mt-1 text-lg font-semibold text-slate-950">{value}</div>
    </div>
  );
}

function StabilityTable({ rows }: { rows: { feature: string; value: number; status: Status }[] }) {
  if (!rows.length) return <div className="mt-3 text-sm text-slate-500">No VSI rows were calculated.</div>;
  return (
    <div className="mt-3 overflow-hidden rounded-xl border border-slate-200">
      <table className="w-full text-sm">
        <thead className="bg-slate-50 text-left text-xs uppercase text-slate-500">
          <tr><th className="px-3 py-2">Feature</th><th className="px-3 py-2">VSI</th><th className="px-3 py-2">Status</th></tr>
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

function LiftTable({ rows }: { rows: LiftRow[] }) {
  if (!rows.length) return null;
  return (
    <div>
      <h3 className="text-sm font-semibold text-slate-800">Lift by Decile</h3>
      <div className="mt-2 max-h-72 overflow-auto rounded-xl border border-slate-200">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 text-left text-xs uppercase text-slate-500">
            <tr>
              <th className="px-3 py-2">Decile</th>
              <th className="px-3 py-2">N</th>
              <th className="px-3 py-2">Positives</th>
              <th className="px-3 py-2">Event Rate</th>
              <th className="px-3 py-2">Lift</th>
              <th className="px-3 py-2">Capture</th>
              <th className="px-3 py-2">Mean Score</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.decile} className="border-t">
                <td className="px-3 py-2">{row.decile}</td>
                <td className="px-3 py-2">{row.n.toLocaleString()}</td>
                <td className="px-3 py-2">{row.positives.toLocaleString()}</td>
                <td className="px-3 py-2">{row.event_rate.toFixed(4)}</td>
                <td className="px-3 py-2">{row.lift.toFixed(2)}</td>
                <td className="px-3 py-2">{row.capture_rate.toFixed(4)}</td>
                <td className="px-3 py-2">{row.mean_score.toFixed(5)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function Preview({ rows, problemType }: { rows: { row: number; score: number; adjusted_score?: number; prediction: number }[]; problemType: "classification" | "regression" }) {
  if (!rows.length) return null;
  const hasAdjusted = rows.some((row) => typeof row.adjusted_score === "number" && Math.abs((row.adjusted_score ?? row.score) - row.score) > 1e-9);
  return (
    <div>
      <h3 className="text-sm font-semibold text-slate-800">{problemType === "regression" ? "Prediction Preview" : "Score Preview"}</h3>
      <div className="mt-2 max-h-64 overflow-auto rounded-xl border border-slate-200">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 text-left text-xs uppercase text-slate-500">
            <tr><th className="px-3 py-2">Row</th><th className="px-3 py-2">{problemType === "regression" ? "Prediction" : "Score"}</th>{hasAdjusted && <th className="px-3 py-2">Adjusted</th>}{problemType === "classification" && <th className="px-3 py-2">Label</th>}</tr>
          </thead>
          <tbody>{rows.map((row) => <tr key={row.row} className="border-t"><td className="px-3 py-2">{row.row}</td><td className="px-3 py-2">{row.score.toFixed(5)}</td>{hasAdjusted && <td className="px-3 py-2">{typeof row.adjusted_score === "number" ? row.adjusted_score.toFixed(5) : "-"}</td>}{problemType === "classification" && <td className="px-3 py-2">{row.prediction}</td>}</tr>)}</tbody>
        </table>
      </div>
    </div>
  );
}
