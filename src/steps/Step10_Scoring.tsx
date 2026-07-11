import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import StepPythonPanel from "../components/StepPythonPanel";
import { useWorkflowStore } from "../state/useWorkflowStore";
import { registerScoredDataset } from "../lib/modelDiagnostics";

const API_BASE =
  (import.meta.env.VITE_API_BASE as string | undefined)?.replace(/\/$/, "") ||
  "http://127.0.0.1:8001/api";

type Status = "pass" | "warning" | "fail";
type ScoredSplit = "train" | "test" | "oot";
type ScoreResult = {
  ok: boolean;
  task?: "classification" | "regression";
  error?: string;
  dataset_type?: string;
  rows?: number;
  target_column?: string | null;
  model?: { name?: string; feature_count?: number; features?: string[]; target?: string };
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
  scored_rows?: Array<Record<string, unknown>>;
  scored_columns?: string[];
  scored_row_scope?: "full_scored_output" | "scoring_response_preview" | string;
  preview?: { row: number; score: number; adjusted_score?: number; prediction: number; actual?: number | string | null; [key: string]: unknown }[];
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

async function scoreDevelopmentSplit(
  datasetType: "train" | "test",
  options: { correctionMethod: string; originalPrior: string; modelPrior: string }
) {
  const params = new URLSearchParams({
    dataset_type: datasetType,
    model: "final",
    correction_method: options.correctionMethod,
  });
  const originalPriorValue = Number(options.originalPrior);
  const modelPriorValue = Number(options.modelPrior);
  if (options.originalPrior.trim() && Number.isFinite(originalPriorValue)) params.set("original_prior", String(originalPriorValue));
  if (options.modelPrior.trim() && Number.isFinite(modelPriorValue)) params.set("model_prior", String(modelPriorValue));
  const res = await fetch(`${API_BASE}/score/development-split?${params.toString()}`, { method: "POST" });
  if (!res.ok) throw new Error(`Development split scoring failed (${res.status})`);
  const data = (await res.json()) as ScoreResult;
  if (!data.ok) throw new Error(data.error ?? "Development split scoring failed.");
  return data;
}

export default function Step10Scoring() {
  const projectId = useWorkflowStore((state) => state.projectId);
  const projectName = useWorkflowStore((state) => state.projectName);
  const [testResult, setTestResult] = useState<ScoreResult | null>(null);
  const [trainResult, setTrainResult] = useState<ScoreResult | null>(null);
  const [ootResult, setOotResult] = useState<ScoreResult | null>(null);
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState<"train" | "test" | "oot" | "">("");
  const [correctionMethod, setCorrectionMethod] = useState("none");
  const [originalPrior, setOriginalPrior] = useState("");
  const [modelPrior, setModelPrior] = useState("");
  const [problemType, setProblemType] = useState<"classification" | "regression">("classification");
  const [registeredScoredDataset, setRegisteredScoredDataset] = useState<{ datasetId: string; versionId?: string; split: ScoredSplit } | null>(null);

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

  async function handleDevelopmentSplit(datasetType: "train") {
    setMessage("");
    setLoading(datasetType);
    try {
      const data = await scoreDevelopmentSplit(datasetType, { correctionMethod, originalPrior, modelPrior });
      setTrainResult(data);
    } catch (err: any) {
      setMessage(err?.message ?? "Development split scoring failed.");
    } finally {
      setLoading("");
    }
  }

  async function registerResult(result: ScoreResult, datasetType: ScoredSplit, datasetName?: string) {
    const task = result.task ?? problemType;
    const targetColumn = result.target_column || result.model?.target || (task === "regression" ? detectTargetColumn(result) : undefined);
    const rows = buildScoredRegistrationRows(result, task, targetColumn, datasetType);
    if (!rows.length) {
      setMessage("No scored preview rows are available to register.");
      return;
    }
    const payload = await registerScoredDataset({
      projectId,
      projectName,
      datasetType,
      task,
      modelName: result.model?.name ?? "Final Model",
      datasetName: datasetName?.trim() || `${projectName || "ATLAS Project"} - ${datasetType.toUpperCase()} Scored Output`,
      targetColumn: targetColumn || undefined,
      actualColumn: task === "regression" ? targetColumn || "actual" : "actual",
      scoreColumn: task === "regression" ? undefined : "score",
      predictionColumn: task === "regression" ? "predicted_value" : "prediction",
      residualColumn: task === "regression" ? "atlas_residual" : undefined,
      absResidualColumn: task === "regression" ? "atlas_abs_residual" : undefined,
      squaredResidualColumn: task === "regression" ? "atlas_squared_residual" : undefined,
      rows,
      metadata: {
        split: datasetType.toUpperCase(),
        targetColumn,
        actualColumn: task === "regression" ? targetColumn || "actual" : "actual",
        predictionColumn: task === "regression" ? "predicted_value" : "prediction",
        residualColumn: task === "regression" ? "atlas_residual" : undefined,
        absResidualColumn: task === "regression" ? "atlas_abs_residual" : undefined,
        squaredResidualColumn: task === "regression" ? "atlas_squared_residual" : undefined,
        sourceRows: result.rows,
        registeredRows: rows.length,
        rowScope: result.scored_row_scope ?? (result.scored_rows?.length ? "full_scored_output" : "scoring_response_preview"),
        scoredColumns: result.scored_columns,
        columnRoles: detectRegistrationRoles(Object.keys(rows[0] ?? {}), task),
        scoreSummary: result.score_summary,
        metrics: result.metrics,
        stability: { psi: result.psi, vsiScope: result.vsi_scope },
        diagnosticsAvailable: task === "regression"
          ? ["Residual Diagnostics", "Actual vs Predicted", "Prediction Distribution", "Segment Performance"]
          : ["Lift / Decile", "Calibration", "Score Distribution", "Segment Performance"],
      },
    });
    const versionId = payload.dataset.latestVersion?.versionId;
    setRegisteredScoredDataset({ datasetId: payload.dataset.datasetId, versionId, split: datasetType });
    setMessage(`Scored ${datasetType.toUpperCase()} dataset registered.`);
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
        <PozzoloPriorCorrectionCard
          correctionMethod={correctionMethod}
          originalPrior={originalPrior}
          modelPrior={modelPrior}
          result={testResult ?? trainResult ?? ootResult}
        />
      </section>}

      {problemType === "regression" && (
        <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
          <h2 className="text-base font-semibold text-slate-950">Pozzolo Prior Correction / Undersampling Calibration</h2>
          <p className="mt-2 text-sm leading-6 text-slate-600">
            Pozzolo correction is classification-only and does not apply to regression predictions.
          </p>
        </section>
      )}

      <div className="grid gap-5">
        <DevelopmentSplitCard
          title="TRAIN Scored Output"
          description="Score the fitted development TRAIN split and register it for model diagnostics."
          loading={loading === "train"}
          onScore={() => handleDevelopmentSplit("train")}
          result={trainResult}
          problemType={problemType}
          datasetType="train"
          onRegister={registerResult}
          suggestedDatasetName={`${projectName || "ATLAS Project"} - TRAIN Scored Output`}
        />
        <UploadCard
          title="External Validation Dataset / TEST Scored Output"
          description="Upload a CSV with the same feature schema. If the target column is present, performance metrics are calculated."
          loading={loading === "test"}
          onFile={(file) => handleFile(file, "test")}
          result={testResult}
          problemType={problemType}
          datasetType="test"
          onRegister={registerResult}
          suggestedDatasetName={`${projectName || "ATLAS Project"} - TEST Scored Output`}
        />
        <UploadCard
          title="Out-of-Time Dataset / OOT Scored Output"
          description="Upload a CSV from a later time window. PSI and VSI use the uploaded External Validation dataset as reference when available."
          loading={loading === "oot"}
          onFile={(file) => handleFile(file, "oot")}
          result={ootResult}
          showStability
          problemType={problemType}
          datasetType="oot"
          onRegister={registerResult}
          suggestedDatasetName={`${projectName || "ATLAS Project"} - OOT Scored Output`}
        />
      </div>
      {registeredScoredDataset && (
        <div className="rounded-xl border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-900">
          <div className="font-semibold">Scored {registeredScoredDataset.split.toUpperCase()} dataset registered.</div>
          <div className="mt-1">The full scored output is now available in Dataset Library, Model Diagnostics, and Chart Studio.</div>
          <div className="mt-3 flex flex-wrap gap-2">
            <Link className="rounded-lg bg-emerald-700 px-3 py-2 text-xs font-semibold text-white" to={`/model-diagnostics?datasetId=${registeredScoredDataset.datasetId}${registeredScoredDataset.versionId ? `&versionId=${registeredScoredDataset.versionId}` : ""}`}>
              Open in Model Diagnostics
            </Link>
            <Link className="rounded-lg border border-emerald-300 bg-white px-3 py-2 text-xs font-semibold text-emerald-900" to="/datasets">
              Open Dataset Library
            </Link>
            <Link className="rounded-lg border border-emerald-300 bg-white px-3 py-2 text-xs font-semibold text-emerald-900" to={`/chart-studio?datasetId=${registeredScoredDataset.datasetId}`}>
              Open in Chart Studio
            </Link>
          </div>
          <Link className="sr-only" to={`/model-diagnostics?datasetId=${registeredScoredDataset.datasetId}`}>
            Open Model Diagnostics
          </Link>
        </div>
      )}

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
  datasetType,
  onRegister,
  suggestedDatasetName,
}: {
  title: string;
  description: string;
  loading: boolean;
  onFile: (file: File | undefined) => void;
  result: ScoreResult | null;
  showStability?: boolean;
  problemType: "classification" | "regression";
  datasetType: "test" | "oot";
  onRegister: (result: ScoreResult, datasetType: ScoredSplit, datasetName?: string) => Promise<void>;
  suggestedDatasetName: string;
}) {
  const [datasetName, setDatasetName] = useState(suggestedDatasetName);
  useEffect(() => setDatasetName(suggestedDatasetName), [suggestedDatasetName]);
  const targetColumn = result?.target_column || result?.model?.target || (result ? detectTargetColumn(result) : undefined);
  const registrationRows = result ? buildScoredRegistrationRows(result, result.task ?? problemType, targetColumn, datasetType) : [];
  const columnsAvailable = registrationRows[0] ? Object.keys(registrationRows[0]) : [];
  const detectedRoles = detectRegistrationRoles(columnsAvailable, result?.task ?? problemType);
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
          <div className="rounded-2xl border border-blue-200 bg-blue-50 p-4 text-sm text-blue-950 shadow-sm">
            <div className="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
              <div className="max-w-3xl">
                <div className="text-xs font-semibold uppercase tracking-wide text-blue-700">Register Full Scored Output</div>
                <h3 className="mt-1 text-lg font-semibold text-blue-950">Register Scored Output</h3>
                <p className="mt-1 text-xs leading-5 text-blue-800">
                  ATLAS will register the full original scoring rows plus predictions, target values when present, residuals, split, and diagnostic fields.
                </p>
              </div>
              <button
                type="button"
                onClick={() => onRegister(result, datasetType, datasetName)}
                className="rounded-lg bg-slate-950 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-slate-800"
              >
                Save Scored Output to Dataset Library
              </button>
            </div>
            <div className="mt-4 grid gap-3 lg:grid-cols-[minmax(220px,1.2fr)_repeat(3,minmax(120px,0.6fr))]">
              <label className="grid gap-1">
                <span className="text-[11px] font-semibold uppercase text-blue-700">Dataset name</span>
                <input className="rounded-lg border border-blue-200 bg-white px-3 py-2 text-sm text-slate-950" value={datasetName} onChange={(event) => setDatasetName(event.target.value)} />
              </label>
              <Stat label="Rows Available" value={String(registrationRows.length)} />
              <Stat label="Columns Available" value={String(columnsAvailable.length)} />
              <Stat label="Task" value={(result.task ?? problemType).toUpperCase()} />
            </div>
            <div className="mt-3 grid gap-2 md:grid-cols-4">
              <RoleChip label="Score" value={detectedRoles.score} />
              <RoleChip label="Prediction" value={detectedRoles.prediction} />
              <RoleChip label="Actual" value={detectedRoles.actual} />
              <RoleChip label="Residual" value={detectedRoles.residual} />
            </div>
            <ScoredReadinessChecks columns={columnsAvailable} result={result} problemType={result.task ?? problemType} />
            <div className="mt-3 flex flex-wrap gap-2">
              <Link className="rounded-lg border border-blue-200 bg-white px-3 py-2 text-xs font-semibold text-blue-900" to="/datasets">Open Dataset Library</Link>
              <Link className="rounded-lg border border-blue-200 bg-white px-3 py-2 text-xs font-semibold text-blue-900" to="/model-diagnostics">Open Model Diagnostics</Link>
              <Link className="rounded-lg border border-blue-200 bg-white px-3 py-2 text-xs font-semibold text-blue-900" to="/chart-studio">Open in Chart Studio</Link>
            </div>
          </div>
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

function DevelopmentSplitCard({
  title,
  description,
  loading,
  onScore,
  result,
  problemType,
  datasetType,
  onRegister,
  suggestedDatasetName,
}: {
  title: string;
  description: string;
  loading: boolean;
  onScore: () => void;
  result: ScoreResult | null;
  problemType: "classification" | "regression";
  datasetType: "train";
  onRegister: (result: ScoreResult, datasetType: ScoredSplit, datasetName?: string) => Promise<void>;
  suggestedDatasetName: string;
}) {
  const [datasetName, setDatasetName] = useState(suggestedDatasetName);
  useEffect(() => setDatasetName(suggestedDatasetName), [suggestedDatasetName]);
  const targetColumn = result?.target_column || result?.model?.target || (result ? detectTargetColumn(result) : undefined);
  const registrationRows = result ? buildScoredRegistrationRows(result, result.task ?? problemType, targetColumn, datasetType) : [];
  const columnsAvailable = registrationRows[0] ? Object.keys(registrationRows[0]) : [];
  const detectedRoles = detectRegistrationRoles(columnsAvailable, result?.task ?? problemType);
  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h2 className="text-base font-semibold text-slate-950">{title}</h2>
          <p className="mt-1 text-sm text-slate-600">{description}</p>
        </div>
        <button type="button" onClick={onScore} disabled={loading} className="rounded-md bg-indigo-600 px-3 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-60">
          {loading ? "Scoring..." : "Score TRAIN"}
        </button>
      </div>
      {result ? (
        <ScoredRegistrationPanel
          result={result}
          problemType={problemType}
          datasetType={datasetType}
          datasetName={datasetName}
          setDatasetName={setDatasetName}
          registrationRows={registrationRows}
          columnsAvailable={columnsAvailable}
          detectedRoles={detectedRoles}
          onRegister={() => onRegister(result, datasetType, datasetName)}
        />
      ) : (
        <div className="mt-5 rounded-xl border border-dashed border-slate-300 bg-slate-50 p-5 text-sm text-slate-600">
          Score the development TRAIN split to make a governed TRAIN scored-output dataset available for diagnostics, Chart Studio, and monitoring comparisons.
        </div>
      )}
    </section>
  );
}

function ScoredRegistrationPanel({
  result,
  problemType,
  datasetType,
  datasetName,
  setDatasetName,
  registrationRows,
  columnsAvailable,
  detectedRoles,
  onRegister,
}: {
  result: ScoreResult;
  problemType: "classification" | "regression";
  datasetType: ScoredSplit;
  datasetName: string;
  setDatasetName: (value: string) => void;
  registrationRows: Array<Record<string, unknown>>;
  columnsAvailable: string[];
  detectedRoles: ReturnType<typeof detectRegistrationRoles>;
  onRegister: () => void;
}) {
  const targetColumn = result.target_column || result.model?.target || detectTargetColumn(result) || "Not detected";
  return (
    <div className="mt-5 space-y-5">
      <div className="rounded-2xl border border-blue-200 bg-blue-50 p-4 text-sm text-blue-950 shadow-sm">
        <div className="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
          <div className="max-w-3xl">
            <div className="text-xs font-semibold uppercase tracking-wide text-blue-700">Register Full Scored Output</div>
            <h3 className="mt-1 text-lg font-semibold text-blue-950">Register {datasetType.toUpperCase()} Scored Output</h3>
            <p className="mt-1 text-xs leading-5 text-blue-800">
              ATLAS will register the full original scoring rows plus predictions, target values when present, residuals, split, and diagnostic fields.
            </p>
          </div>
          <button
            type="button"
            onClick={onRegister}
            className="rounded-lg bg-slate-950 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-slate-800"
          >
            Register Scored Dataset
          </button>
        </div>
        <div className="mt-4 grid gap-3 lg:grid-cols-[minmax(220px,1.2fr)_repeat(4,minmax(110px,0.6fr))]">
          <label className="grid gap-1">
            <span className="text-[11px] font-semibold uppercase text-blue-700">Dataset name</span>
            <input className="rounded-lg border border-blue-200 bg-white px-3 py-2 text-sm text-slate-950" value={datasetName} onChange={(event) => setDatasetName(event.target.value)} />
          </label>
          <Stat label="Rows Available" value={String(registrationRows.length)} />
          <Stat label="Columns Available" value={String(columnsAvailable.length)} />
          <Stat label="Target Column" value={String(targetColumn)} />
          <Stat label="Task" value={(result.task ?? problemType).toUpperCase()} />
        </div>
        <div className="mt-3 grid gap-2 md:grid-cols-4">
          <RoleChip label="Score" value={detectedRoles.score} />
          <RoleChip label="Prediction" value={detectedRoles.prediction} />
          <RoleChip label="Actual" value={detectedRoles.actual} />
          <RoleChip label="Residual" value={detectedRoles.residual} />
        </div>
        <ScoredReadinessChecks columns={columnsAvailable} result={result} problemType={result.task ?? problemType} />
        <div className="mt-3 flex flex-wrap gap-2">
          <Link className="rounded-lg border border-blue-200 bg-white px-3 py-2 text-xs font-semibold text-blue-900" to="/datasets">Open Dataset Library</Link>
          <Link className="rounded-lg border border-blue-200 bg-white px-3 py-2 text-xs font-semibold text-blue-900" to="/model-diagnostics">Open Model Diagnostics</Link>
          <Link className="rounded-lg border border-blue-200 bg-white px-3 py-2 text-xs font-semibold text-blue-900" to="/chart-studio">Open in Chart Studio</Link>
        </div>
      </div>
      <div className="grid gap-3 sm:grid-cols-4">
        <Stat label="Rows" value={String(result.rows ?? "-")} />
        <Stat label={problemType === "regression" ? "Min Prediction" : "Min Score"} value={format(result.score_summary?.min)} />
        <Stat label={problemType === "regression" ? "Mean Prediction" : "Mean Score"} value={format(result.score_summary?.mean)} />
        <Stat label={problemType === "regression" ? "Max Prediction" : "Max Score"} value={format(result.score_summary?.max)} />
      </div>
      {problemType === "regression" && <RegressionScoreVisual result={result} />}
      <Preview rows={result.preview ?? []} problemType={problemType} />
    </div>
  );
}

function buildScoredRegistrationRows(result: ScoreResult, task?: string, targetColumn?: string | null, split?: ScoredSplit) {
  if (Array.isArray(result.scored_rows) && result.scored_rows.length) {
    return result.scored_rows.map((row, index) => ({
      ...(row.row === undefined ? { row: index + 1 } : {}),
      ...row,
      split: row.split ?? split?.toUpperCase(),
    }));
  }
  return (result.preview ?? []).map((row) => {
    if (task === "regression") {
      const predicted = Number(row.score);
      const actualRaw = targetColumn ? row[targetColumn] ?? row.actual : row.actual;
      const actual = typeof actualRaw === "number" ? actualRaw : Number(actualRaw);
      const hasActual = Number.isFinite(actual);
      const residual = hasActual && Number.isFinite(predicted) ? actual - predicted : null;
      return {
        row: row.row,
        split: split?.toUpperCase(),
        ...(targetColumn && hasActual ? { [targetColumn]: actual } : {}),
        actual: hasActual ? actual : null,
        predicted_value: row.score,
        prediction: row.score,
        atlas_residual: residual,
        atlas_abs_residual: residual == null ? null : Math.abs(residual),
        atlas_squared_residual: residual == null ? null : residual * residual,
        atlas_percent_error: residual == null || !hasActual || actual === 0 ? null : residual / actual,
      };
    }
    return {
      row: row.row,
      split: split?.toUpperCase(),
      ...(row.actual !== undefined ? { actual: row.actual } : {}),
      score: row.score,
      adjusted_score: row.adjusted_score,
      prediction: row.prediction,
    };
  });
}

function detectRegistrationRoles(columns: string[], task?: string) {
  const lower = new Map(columns.map((column) => [column.toLowerCase(), column]));
  const find = (names: string[]) => names.map((name) => lower.get(name.toLowerCase())).find(Boolean) ?? null;
  return {
    score: task === "regression" ? null : find(["score", "adjusted_score", "probability"]),
    prediction: find(["predicted_value", "prediction", "predicted", "y_pred"]),
    actual: find(["actual", "target", "class", "observed", "y_true", "MedHouseVal"]),
    residual: find(["atlas_residual", "residual", "error"]),
  };
}

function detectTargetColumn(result: ScoreResult) {
  const source = result.scored_rows?.[0] ?? result.preview?.[0] ?? {};
  const ignored = new Set(["row", "score", "adjusted_score", "prediction", "predicted_value", "actual", "atlas_residual", "atlas_abs_residual", "atlas_squared_residual", "atlas_percent_error", "split"]);
  return Object.keys(source).find((key) => !ignored.has(key));
}

function isPredictionOnlyScoredOutput(columns: string[]) {
  if (!columns.length) return false;
  const allowed = new Set(["row", "score", "adjusted_score", "prediction", "predicted_value", "actual", "atlas_residual", "atlas_abs_residual", "atlas_squared_residual", "atlas_percent_error", "split"]);
  return columns.every((column) => allowed.has(column.toLowerCase()));
}

function ScoredReadinessChecks({ columns, result, problemType }: { columns: string[]; result: ScoreResult; problemType?: string }) {
  const lower = new Set(columns.map((column) => column.toLowerCase()));
  const predictionOnly = isPredictionOnlyScoredOutput(columns);
  const targetColumn = result.target_column || result.model?.target || detectTargetColumn(result);
  const checks = [
    { label: "Feature columns preserved", ok: !predictionOnly && columns.length > 6 },
    { label: "Target column detected", ok: Boolean(targetColumn && lower.has(String(targetColumn).toLowerCase()) || lower.has("actual")) },
    { label: "Prediction column", ok: lower.has("predicted_value") || lower.has("prediction") || lower.has("score") },
    { label: "Residual columns", ok: problemType === "classification" || (lower.has("atlas_residual") && lower.has("atlas_abs_residual") && lower.has("atlas_squared_residual")) },
  ];
  return (
    <div className="mt-3">
      {predictionOnly && (
        <div className="mb-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs leading-5 text-amber-900">
          Warning: this scored output contains predictions only. Full diagnostic registration requires original feature columns and target values.
        </div>
      )}
      <div className="grid gap-2 md:grid-cols-4">
        {checks.map((check) => (
          <div key={check.label} className={`rounded-lg border px-3 py-2 text-xs ${check.ok ? "border-emerald-200 bg-emerald-50 text-emerald-900" : "border-amber-200 bg-amber-50 text-amber-900"}`}>
            <div className="font-semibold uppercase">{check.label}</div>
            <div className="mt-1">{check.ok ? "Yes" : "Needs review"}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

function RoleChip({ label, value }: { label: string; value: string | null }) {
  return (
    <div className={`rounded-lg border px-3 py-2 text-xs ${value ? "border-emerald-200 bg-emerald-50 text-emerald-900" : "border-slate-200 bg-white text-slate-500"}`}>
      <div className="font-semibold uppercase">{label}</div>
      <div className="mt-1 truncate" title={value ?? "Not detected"}>{value ?? "Not detected"}</div>
    </div>
  );
}

function PozzoloPriorCorrectionCard({
  correctionMethod,
  originalPrior,
  modelPrior,
  result,
}: {
  correctionMethod: string;
  originalPrior: string;
  modelPrior: string;
  result: ScoreResult | null;
}) {
  const pi = Number(originalPrior || result?.probability_correction?.original_prior || result?.probability_correction?.default_original_prior);
  const piS = Number(modelPrior || result?.probability_correction?.model_prior || result?.probability_correction?.default_model_prior);
  const alpha = Number.isFinite(pi) && Number.isFinite(piS) && pi > 0 && pi < 1 && piS > 0 && piS < 1
    ? (pi / (1 - pi)) / (piS / (1 - piS))
    : null;
  const originalMean = result?.score_summary?.mean ?? null;
  const correctedMean = result?.adjusted_score_summary?.mean ?? null;
  const actualRows = result?.preview?.filter((row) => row.actual !== undefined) ?? [];
  const brier = actualRows.length
    ? actualRows.reduce((sum, row) => {
        const actual = Number(row.actual);
        const raw = Number(row.score);
        return Number.isFinite(actual) && Number.isFinite(raw) ? sum + (raw - actual) ** 2 : sum;
      }, 0) / actualRows.length
    : null;
  return (
    <div className="mt-5 rounded-xl border border-blue-200 bg-blue-50 p-4">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <h2 className="text-base font-semibold text-blue-950">Pozzolo Prior Correction / Undersampling Calibration</h2>
          <p className="mt-1 text-xs leading-5 text-blue-800">
            Use this when a classification model was trained on a sampled or balanced class distribution and probabilities need to be moved back to the target population event rate.
          </p>
        </div>
        <span className={`rounded-full border px-3 py-1 text-xs font-semibold ${correctionMethod === "none" ? "border-slate-200 bg-white text-slate-600" : "border-emerald-200 bg-emerald-50 text-emerald-800"}`}>
          {correctionMethod === "none" ? "Not applied" : "Applied"}
        </span>
      </div>
      <div className="mt-3 grid gap-3 xl:grid-cols-[1.2fr_0.8fr]">
        <div className="rounded-lg bg-white p-3 text-xs leading-6 text-slate-800">
          <div className="font-semibold">alpha = [pi / (1 - pi)] / [pi_s / (1 - pi_s)]</div>
          <div className="font-semibold">p_corrected = (alpha * p_s) / (1 - p_s + alpha * p_s)</div>
          <div className="mt-2 text-slate-600">
            p_corrected = [p_s * pi * (1 - pi_s)] / [p_s * pi * (1 - pi_s) + (1 - p_s) * (1 - pi) * pi_s]
          </div>
        </div>
        <div className="grid gap-2 sm:grid-cols-2">
          <Stat label="Sample training event rate pi_s" value={format(piS)} />
          <Stat label="Target population event rate pi" value={format(pi)} />
          <Stat label="Correction factor alpha" value={format(alpha)} />
          <Stat label="Mean original probability" value={format(originalMean)} />
          <Stat label="Mean corrected probability" value={format(correctedMean)} />
          <Stat label="Brier before / after" value={brier == null ? "-" : `${format(brier)} / ${format(brier)}`} />
        </div>
      </div>
    </div>
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
