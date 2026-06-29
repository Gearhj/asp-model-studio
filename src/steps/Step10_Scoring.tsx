import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useWorkflowStore } from "../state/useWorkflowStore";

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

  return (
    <div className="mx-auto max-w-[1200px] space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-slate-950">Step 10: Final Model Scoring</h1>
        <p className="mt-1 text-sm text-slate-600">
          {problemType === "regression"
            ? "Score holdout TEST and OOT datasets using the saved final model. OOT scoring calculates prediction stability and VSI for input features."
            : "Score holdout TEST and OOT datasets using the saved final model. OOT scoring calculates PSI for the score and VSI for input features."}
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
          title="Holdout TEST Dataset"
          description="Upload a CSV with the same feature schema. If the target column is present, performance metrics are calculated."
          loading={loading === "test"}
          onFile={(file) => handleFile(file, "test")}
          result={testResult}
          problemType={problemType}
        />
        <UploadCard
          title="Out-of-Time OOT Dataset"
          description="Upload a CSV from a later time window. PSI and VSI use the uploaded TEST dataset as reference when available."
          loading={loading === "oot"}
          onFile={(file) => handleFile(file, "oot")}
          result={ootResult}
          showStability
          problemType={problemType}
        />
      </div>

      <div className="pb-10 flex justify-center">
        <button
          className="rounded-xl bg-indigo-600 px-5 py-3 text-white shadow-sm"
          onClick={() => {
            markComplete("step10");
            navigate("/dashboard");
          }}
        >
          Mark Complete & Return to Dashboard
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
                <div className="text-xs font-semibold uppercase">{problemType === "regression" ? "PSI Prediction Distribution" : "PSI Score Distribution"}</div>
                <div className="mt-1 text-2xl font-semibold">{result.psi.value.toFixed(4)}</div>
                <div className="mt-1 text-xs">{result.psi.status.toUpperCase()}</div>
              </div>
              <div className="mt-2 text-xs text-slate-500">
                VSI scope: {result.vsi_scope === "model_features" ? "saved final model features" : "all common uploaded features"}
              </div>
              <div className="mt-1 text-xs text-slate-500">
                Stability reference: {result.stability_reference === "uploaded_test" ? "uploaded TEST dataset" : "development split"}
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
