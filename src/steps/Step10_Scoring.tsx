import { useEffect, useMemo, useState, type ReactNode } from "react";
import { Activity, BarChart3, Code2, Database, LockKeyhole, Save, ShieldCheck, UploadCloud } from "lucide-react";
import { Link } from "react-router-dom";
import StepShell from "../components/StepShell";
import StepPythonPanel from "../components/StepPythonPanel";
import { AtlasAttentionPanel, type AtlasWorkflowMetric } from "../components/ui/AtlasWorkflow";
import { createEvidence } from "../lib/evidenceGraph";
import { useWorkflowStore } from "../state/useWorkflowStore";
import { registerScoredDataset } from "../lib/modelDiagnostics";
import { inferLocalProblemType, loadLocalDataset } from "../lib/localDataset";
import { requireLocalDatasetCanonicalIdentity } from "../lib/datasetIdentity";
import { resolveFinalModelReadiness } from "../lib/finalModelReadiness";
import {
  buildExactScoringHistoryFilters,
  buildFinalModelStatusQuery,
  eligibleDurableScoringPartitions,
  resolveCanonicalScoringDatasetVersion,
  resolveFinalModelVersionDisplay,
  type ExactScoringContinuationContext,
} from "../lib/scoringContinuation";
import { archiveScoringRun, listScoringRuns, type ScoringRunSummary } from "../scoring-runs/scoringRunClient";
import { getCachedUserId } from "../lib/authSession";
import RunComparePanel from "../visual-intelligence/production/RunComparePanel";
import RegisterScoredDatasetButton from "../visual-intelligence/production/RegisterScoredDatasetButton";
import { projectWorkflowRoute } from "../lib/projectScopedRoutes";

const QUERY_API_BASE =
  typeof window !== "undefined" ? new URLSearchParams(window.location.search).get("apiBase")?.replace(/\/$/, "") : undefined;
const API_BASE =
  QUERY_API_BASE ||
  (import.meta.env.VITE_API_BASE as string | undefined)?.replace(/\/$/, "") ||
  "http://127.0.0.1:8001/api";

type Status = "pass" | "warning" | "fail";
type ScoredSplit = "train" | "test" | "oot";
type FinalModelMetadata = {
  name?: string;
  source_model?: string;
  source_estimator_class?: string;
  final_estimator_class?: string;
  feature_selection_method?: string;
  feature_count?: number;
  features?: string[];
  problem_type?: "classification" | "regression";
  project_id?: string;
  dataset_id?: string;
  training_dataset_id?: string;
  dataset_version_id?: string;
  training_dataset_version_id?: string;
  dataset_version?: string;
  target?: string;
  target_name?: string;
  holdout_auc?: number | null;
  holdout_rmse?: number | null;
  final_model_version?: string;
  preprocessing_pipeline?: string;
  calibration_method?: string;
  modeled_event_rate?: number | null;
  natural_event_rate?: number | null;
  artifact_hash?: string;
  model_id?: string;
  modelId?: string;
  model_version_id?: string;
  modelVersionId?: string;
};
type ScoreResult = {
  ok: boolean;
  task?: "classification" | "regression";
  error?: string;
  dataset_type?: string;
  dataset_identity?: string;
  dataset_version?: string;
  period?: { column?: string; start?: string; end?: string };
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
  stability_reference?: "uploaded_test" | "development_split" | "development_train";
  scored_rows?: Array<Record<string, unknown>>;
  scored_columns?: string[];
  scored_row_scope?: "full_scored_output" | "scoring_response_preview" | string;
  preview?: { row: number; score: number; adjusted_score?: number; prediction: number; actual?: number | string | null; [key: string]: unknown }[];
  /** Persistent Scoring Runs, Phase G: present when this score action was durably
   *  persisted server-side. Absent (undefined) means persistence failed silently
   *  behind the scenes -- the scoring result itself is still shown, unaffected. */
  scoringRunId?: string;
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

/** Persistent Scoring Runs, Phase G/Phase F: a read-only history panel proving
 *  scoring results now survive a browser refresh -- unlike testResult/trainResult/
 *  ootResult above (plain React state, still lost on refresh, unchanged this
 *  phase per "Do not redesign Predictive Modeling pages"), this list is fetched
 *  fresh from the durable backend on every mount, so it is refresh-proof by
 *  construction. Each row links into the Visual Intelligence Lab pinned to that
 *  run (Phase G integration). */
function ScoringHistoryPanel({
  exactContext,
  onArchive,
}: {
  exactContext: ExactScoringContinuationContext | null;
  onArchive?: () => void;
}) {
  const [runs, setRuns] = useState<ScoringRunSummary[]>([]);
  const [loading, setLoading] = useState(false);
  const [showArchived, setShowArchived] = useState(false);
  const [compareIds, setCompareIds] = useState<string[]>([]);
  const [showCompare, setShowCompare] = useState(false);
  const [busyRunId, setBusyRunId] = useState<string | null>(null);
  const [scopeError, setScopeError] = useState("");
  const userId = getCachedUserId() ?? "anonymous";
  const projectId = exactContext?.projectId ?? "";

  function refresh() {
    if (!exactContext) {
      setRuns([]);
      setLoading(false);
      setScopeError("Exact scoring-history identity is unavailable. Project-wide history was not loaded.");
      return;
    }
    let filters;
    try {
      filters = buildExactScoringHistoryFilters(exactContext, {
        limit: 20,
        includeArchived: showArchived,
      });
    } catch (error) {
      setRuns([]);
      setLoading(false);
      setScopeError(error instanceof Error ? error.message : "Exact scoring-history identity is unavailable.");
      return;
    }
    setScopeError("");
    setLoading(true);
    listScoringRuns(exactContext.projectId, filters)
      .then((result) => setRuns(result))
      .catch(() => setRuns([]))
      .finally(() => setLoading(false));
  }

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [exactContext, showArchived]);

  async function handleArchive(scoringRunId: string) {
    setBusyRunId(scoringRunId);
    try {
      await archiveScoringRun(scoringRunId);
      onArchive?.();
      refresh();
    } finally {
      setBusyRunId(null);
    }
  }

  if (scopeError) {
    return (
      <section
        className="rounded-md border border-amber-200 bg-amber-50 p-4 text-sm text-amber-950"
        data-testid="scoring-history-scope-unavailable"
        role="alert"
      >
        <h3 className="font-semibold">Scoring History unavailable</h3>
        <p className="mt-1 text-xs">{scopeError}</p>
      </section>
    );
  }

  if (!loading && runs.length === 0 && !showArchived) return null;

  return (
    <section className="rounded-md border border-slate-200 bg-white p-4" data-testid="scoring-history-panel">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-sm font-semibold text-slate-900">Scoring History (durable)</h3>
        <label className="flex items-center gap-1.5 text-xs text-slate-600">
          <input type="checkbox" checked={showArchived} onChange={(event) => setShowArchived(event.target.checked)} /> Show archived
        </label>
      </div>
      <p className="mt-1 text-xs text-slate-600">
        Every scoring run above is persisted the moment it completes -- including failed attempts, with an honest reason. This list
        survives a refresh and reopening the project because it is read from the server, not from this page's session state.
      </p>
      {runs.length === 0 ? (
        <p className="mt-3 text-xs text-slate-500">
          No scoring runs {showArchived ? "" : "(non-archived) "}exist yet for this project. Score TRAIN, TEST, or OOT above to create one.
        </p>
      ) : (
        <ul className="mt-3 divide-y divide-slate-100 text-sm">
          {runs.map((run) => {
            const context = {
              authenticatedUserId: userId,
              projectId,
              problemType: run.problemType,
              target: run.target,
              datasetId: run.datasetId ?? undefined,
              datasetVersionId: run.datasetVersionId ?? undefined,
              modelId: run.modelId ?? undefined,
              featureManifestVersion: undefined,
              scoringRunId: run.scoringRunId,
              partition: run.partition,
              sourceType: "scoring-session" as const,
              readOnly: false,
              evidenceEnabled: true,
              registrationEnabled: run.status === "completed",
            };
            return (
              <li key={run.scoringRunId} className="flex flex-wrap items-center justify-between gap-2 py-2" data-testid="scoring-history-row">
                <span className="flex flex-wrap items-center gap-2">
                  <input
                    type="checkbox"
                    aria-label={`Select ${run.scoringRunId} for comparison`}
                    checked={compareIds.includes(run.scoringRunId)}
                    onChange={(event) => setCompareIds(event.target.checked ? [...compareIds, run.scoringRunId] : compareIds.filter((id) => id !== run.scoringRunId))}
                  />
                  <span className="font-semibold uppercase text-slate-800">{run.partition}</span>
                  <span className={`rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase ${run.status === "completed" ? "bg-emerald-100 text-emerald-800" : run.status === "failed" ? "bg-rose-100 text-rose-800" : "bg-slate-100 text-slate-700"}`}>{run.status}</span>
                  {run.archivedAt ? <span className="rounded bg-slate-200 px-1.5 py-0.5 text-[10px] font-semibold uppercase text-slate-600">archived</span> : null}
                  {run.registrationStatus === "registered" ? <span className="rounded bg-indigo-100 px-1.5 py-0.5 text-[10px] font-semibold uppercase text-indigo-800">registered</span> : null}
                  <span className="text-slate-500">
                    {run.modelId ?? "model"} -- {run.rowCount?.toLocaleString() ?? "-"} rows -- {new Date(run.createdAt).toLocaleString()}
                  </span>
                  {run.status === "failed" ? <span className="text-rose-700" data-testid="scoring-run-failure-reason">{run.errorMessage ?? "Scoring failed for an unspecified reason."}</span> : null}
                </span>
                <span className="flex flex-wrap items-center gap-2">
                  {run.status === "completed" ? (
                    <>
                      <Link className="text-xs font-semibold text-blue-700 hover:underline" to={projectWorkflowRoute(projectId, `/step08?scoringRunId=${encodeURIComponent(run.scoringRunId)}`)}>
                        Open Analysis
                      </Link>
                      <Link className="text-xs font-semibold text-blue-700 hover:underline" to={`/visual-intelligence-lab?scoringRunId=${encodeURIComponent(run.scoringRunId)}`}>
                        View in Lab
                      </Link>
                      <RegisterScoredDatasetButton context={context} />
                    </>
                  ) : null}
                  {!run.archivedAt ? (
                    <button type="button" className="text-xs font-semibold text-slate-600 hover:underline disabled:opacity-40" disabled={busyRunId === run.scoringRunId} onClick={() => handleArchive(run.scoringRunId)}>
                      Archive
                    </button>
                  ) : null}
                </span>
              </li>
            );
          })}
        </ul>
      )}
      <div className="mt-3 flex items-center gap-2">
        <button type="button" className="atlas-secondary-button text-xs" onClick={() => setShowCompare((v) => !v)} disabled={compareIds.length < 2}>
          Compare {compareIds.length > 0 ? `(${compareIds.length})` : ""} Selected Runs
        </button>
      </div>
      {showCompare ? <div className="mt-3"><RunComparePanel projectId={projectId} anchorRunId={compareIds[0] ?? null} /></div> : null}
    </section>
  );
}

async function uploadScore(
  file: File,
  projectId: string,
  datasetType: "test" | "oot",
  options: { correctionMethod: string; originalPrior: string; modelPrior: string }
) {
  const body = new FormData();
  body.append("file", file);
  const params = new URLSearchParams({
    project_id: projectId,
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
    credentials: "include",
    body,
  });
  if (!res.ok) throw new Error(`Scoring failed (${res.status})`);
  const data = (await res.json()) as ScoreResult;
  if (!data.ok) throw new Error(data.error ?? "Scoring failed.");
  return data;
}

async function scoreDevelopmentSplit(
  projectId: string,
  datasetType: "train" | "test",
  options: { correctionMethod: string; originalPrior: string; modelPrior: string }
) {
  const params = new URLSearchParams({
    project_id: projectId,
    dataset_type: datasetType,
    model: "final",
    correction_method: options.correctionMethod,
  });
  const originalPriorValue = Number(options.originalPrior);
  const modelPriorValue = Number(options.modelPrior);
  if (options.originalPrior.trim() && Number.isFinite(originalPriorValue)) params.set("original_prior", String(originalPriorValue));
  if (options.modelPrior.trim() && Number.isFinite(modelPriorValue)) params.set("model_prior", String(modelPriorValue));
  const res = await fetch(`${API_BASE}/score/development-split?${params.toString()}`, { method: "POST", credentials: "include" });
  if (!res.ok) throw new Error(`Development split scoring failed (${res.status})`);
  const data = (await res.json()) as ScoreResult;
  if (!data.ok) throw new Error(data.error ?? "Development split scoring failed.");
  return data;
}

export default function Step10Scoring() {
  const projectId = useWorkflowStore((state) => state.projectId);
  const projectName = useWorkflowStore((state) => state.projectName);
  const getNextStepPath = useWorkflowStore((state) => state.getNextStepPath);
  const [testResult, setTestResult] = useState<ScoreResult | null>(null);
  const [trainResult, setTrainResult] = useState<ScoreResult | null>(null);
  const [ootResult, setOotResult] = useState<ScoreResult | null>(null);
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState<"train" | "test" | "oot" | "">("");
  const [correctionMethod, setCorrectionMethod] = useState("none");
  const [originalPrior, setOriginalPrior] = useState("");
  const [modelPrior, setModelPrior] = useState("");
  const [problemType, setProblemType] = useState<"classification" | "regression">("classification");
  const [finalModelReady, setFinalModelReady] = useState<boolean | null>(null);
  const [finalModelMetadata, setFinalModelMetadata] = useState<FinalModelMetadata>({});
  const [finalModelError, setFinalModelError] = useState("");
  const [durableScoredPartitions, setDurableScoredPartitions] = useState<ScoredSplit[]>([]);
  const [scoringHistoryRevision, setScoringHistoryRevision] = useState(0);
  const [registeredScoredDataset, setRegisteredScoredDataset] = useState<{ datasetId: string; versionId?: string; split: ScoredSplit } | null>(null);

  useEffect(() => {
    // Ignore responses that resolve after projectId changed or the component unmounted, so an
    // out-of-order response for a previous project can never overwrite the current view.
    let stale = false;
    const dataset = loadLocalDataset();
    let expectedIdentity;
    try {
      expectedIdentity = requireLocalDatasetCanonicalIdentity(
        projectId,
        dataset,
        "Final-model scoring dataset identity",
      );
    } catch (error) {
      setFinalModelReady(false);
      setFinalModelMetadata({});
      setFinalModelError(
        error instanceof Error
          ? error.message
          : "The exact registered dataset identity is unavailable.",
      );
      return () => {
        stale = true;
      };
    }
    const expectedTarget = dataset?.target?.trim() ?? "";
    let finalModelStatusQuery;
    try {
      finalModelStatusQuery = buildFinalModelStatusQuery({
        projectId,
        datasetId: expectedIdentity.dataset_id,
        datasetVersionId: expectedIdentity.dataset_version_id,
        target: expectedTarget,
      });
    } catch (error) {
      setFinalModelReady(false);
      setFinalModelMetadata({});
      setFinalModelError(
        error instanceof Error ? error.message : "The exact final-model identity is unavailable.",
      );
      return () => {
        stale = true;
      };
    }
    const expectedProblemType = inferLocalProblemType(dataset);
    const trainingContext = new URLSearchParams({
      project_id: projectId,
      dataset_id: expectedIdentity.dataset_id,
      dataset_version_id: expectedIdentity.dataset_version_id,
      target: expectedTarget,
      problem_type: expectedProblemType ?? "",
    });
    fetch(`${API_BASE}/model/final/status?${finalModelStatusQuery.toString()}`, { credentials: "include" })
      .then(async (res) => {
        if (!res.ok) throw new Error(`Final-model status failed (${res.status}).`);
        return res.json();
      })
      .then((data) => {
        if (stale) return;
        const view = resolveFinalModelReadiness<FinalModelMetadata>(data, {
          projectId,
          datasetId: expectedIdentity.dataset_id,
          datasetVersion: expectedIdentity.dataset_version_id,
          target: expectedTarget,
        });
        setFinalModelReady(view.ready);
        setFinalModelMetadata(view.metadata);
        setFinalModelError(view.error);
        if (view.metadata.problem_type === "regression") {
          setProblemType("regression");
          setCorrectionMethod("none");
        }
      })
      .catch((error) => {
        if (stale) return;
        setFinalModelReady(false);
        setFinalModelError(error instanceof Error ? error.message : "Final-model status is unavailable.");
      });
    fetch(`${API_BASE}/train/last?${trainingContext.toString()}`, { credentials: "include" })
      .then((res) => res.json())
      .then((data) => {
        if (stale) return;
        const ranked = data?.summary?.ranked ?? [];
        if (data?.summary?.problem_type === "regression" || ranked.some((row: any) => row.task === "regression")) {
          setProblemType("regression");
          setCorrectionMethod("none");
        }
      })
      .catch(() => {});
    return () => {
      stale = true;
    };
  }, [projectId]);

  const exactScoringContext = useMemo<ExactScoringContinuationContext | null>(() => {
    const datasetId = finalModelMetadata.training_dataset_id ?? finalModelMetadata.dataset_id ?? "";
    const datasetVersionId = resolveCanonicalScoringDatasetVersion(finalModelMetadata);
    const target = finalModelMetadata.target_name ?? finalModelMetadata.target ?? "";
    const modelVersionId = finalModelMetadata.model_version_id ?? finalModelMetadata.modelVersionId ?? "";
    if (!projectId || !datasetId || !datasetVersionId || !target || !modelVersionId) return null;
    return { projectId, datasetId, datasetVersionId, target, modelVersionId };
  }, [
    finalModelMetadata.dataset_id,
    finalModelMetadata.dataset_version_id,
    finalModelMetadata.modelVersionId,
    finalModelMetadata.model_version_id,
    finalModelMetadata.target,
    finalModelMetadata.target_name,
    finalModelMetadata.training_dataset_id,
    finalModelMetadata.training_dataset_version_id,
    projectId,
  ]);

  useEffect(() => {
    let stale = false;
    if (!finalModelReady || !exactScoringContext) {
      setDurableScoredPartitions([]);
      return () => {
        stale = true;
      };
    }
    listScoringRuns(projectId, {
      datasetId: exactScoringContext.datasetId,
      datasetVersionId: exactScoringContext.datasetVersionId,
      modelVersionId: exactScoringContext.modelVersionId,
      target: exactScoringContext.target,
      status: "completed",
      limit: 200,
    })
      .then((runs) => {
        if (!stale) {
          setDurableScoredPartitions(
            eligibleDurableScoringPartitions(runs, exactScoringContext),
          );
        }
      })
      .catch(() => {
        if (!stale) setDurableScoredPartitions([]);
      });
    return () => {
      stale = true;
    };
  }, [
    exactScoringContext,
    finalModelReady,
    projectId,
    scoringHistoryRevision,
    trainResult?.scoringRunId,
    testResult?.scoringRunId,
    ootResult?.scoringRunId,
  ]);

  async function handleFile(file: File | undefined, datasetType: "test" | "oot") {
    if (!file) return;
    setMessage("");
    setLoading(datasetType);
    try {
      const data = await uploadScore(file, projectId, datasetType, { correctionMethod, originalPrior, modelPrior });
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
      const data = await scoreDevelopmentSplit(projectId, datasetType, { correctionMethod, originalPrior, modelPrior });
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
      // Visual Intelligence Production Integration, Phase K: cross-links this
      // registration back to its durable ScoringRun, when this result came from one.
      scoringRunId: result.scoringRunId,
    });
    const versionId = payload.dataset.latestVersion?.versionId;
    setRegisteredScoredDataset({ datasetId: payload.dataset.datasetId, versionId, split: datasetType });
    setMessage(`Scored ${datasetType.toUpperCase()} dataset registered.`);
  }

  async function saveStabilityArtifact(destination: "evidence" | "monitoring") {
    const available = [
      testResult ? { split: "TEST", result: testResult } : null,
      ootResult ? { split: "OOT", result: ootResult } : null,
    ].filter(Boolean) as Array<{ split: "TEST" | "OOT"; result: ScoreResult }>;
    if (!available.length) {
      setMessage("Score TEST or OOT before saving stability evidence.");
      return;
    }
    const canonicalDatasetVersion = resolveCanonicalScoringDatasetVersion(finalModelMetadata);
    if (
      !exactScoringContext ||
      !canonicalDatasetVersion ||
      canonicalDatasetVersion !== exactScoringContext.datasetVersionId
    ) {
      setMessage("The exact promoted training dataset version is unavailable or contradictory. No scoring evidence was created.");
      return;
    }
    const failed = available.some(({ result }) => result.psi?.status === "fail" || result.vsi?.some((row) => row.status === "fail"));
    try {
      await createEvidence({
        projectId,
        projectName,
        evidenceType: "model_diagnostics",
        title: destination === "monitoring" ? "Final Model Stability Monitoring Baseline" : "Final Model Scoring Stability Evidence",
        summary: `${available.map(({ split }) => split).join(" and ")} stability diagnostics for ${finalModelMetadata.name ?? "the governed final model"}.`,
        sourcePage: "Final Model Scoring",
        sourceRoute: "/step10",
        datasetIds: [canonicalDatasetVersion],
        modelIds: [finalModelMetadata.source_model ?? finalModelMetadata.name ?? "final_model"],
        documentIds: [],
        notebookIds: [],
        supportsSections: destination === "monitoring" ? ["Model Monitoring", "Performance Monitoring", "Data Drift"] : ["Model Validation", "Stability Analysis", "Scoring"],
        tags: ["predictive_modeling", "final_model", "psi", "vsi", destination],
        status: failed ? "needs_review" : "ready",
        importance: "high",
        lineage: {
          finalModelVersion: finalModelMetadata.final_model_version,
          artifactHash: finalModelMetadata.artifact_hash,
          datasetVersion: canonicalDatasetVersion,
          reference: "development_train",
        },
        payload: {
          destination,
          generatedAt: new Date().toISOString(),
          datasets: available.map(({ split, result }) => ({
            split,
            rows: result.rows,
            predictionPsi: result.psi,
            variableStability: result.vsi,
            vsiScope: result.vsi_scope,
            reference: result.stability_reference,
          })),
        },
      });
      setMessage(destination === "monitoring" ? "Stability baseline added to the monitoring evidence plan." : "Scoring stability evidence saved to the Model Evidence Center.");
    } catch (cause) {
      setMessage(cause instanceof Error ? cause.message : "Stability evidence could not be saved.");
    }
  }

  // A rendered response is not durable proof.  Continue only after the new
  // scoring run can be read back through the exact-identity history query.
  const scoredOutputCount = durableScoredPartitions.length;
  const proposedPolicy = readProposedOperatingPolicy(projectId);
  const estimatorClass = finalModelMetadata.source_estimator_class ?? finalModelMetadata.final_estimator_class;
  const estimatorLabel = estimatorClass === "Pipeline" && finalModelMetadata.name
    ? `${finalModelMetadata.name} pipeline`
    : estimatorClass ?? "Not available";
  const modelFamilyLabel = estimatorClass === "Pipeline" && finalModelMetadata.name
    ? finalModelMetadata.name
    : estimatorClass ?? "Not recorded";
  const heroMetrics: AtlasWorkflowMetric[] = [
    { label: "Project", value: projectName },
    { label: "Final Model", value: finalModelMetadata.name ?? (finalModelReady ? "Saved artifact" : "Required"), tone: finalModelReady ? "success" : "warning" },
    { label: "Estimator", value: estimatorLabel },
    { label: "Retained Features", value: finalModelMetadata.feature_count?.toLocaleString() ?? "-" },
    { label: "Problem Type", value: problemType === "regression" ? "Regression" : "Classification" },
    { label: "Scored Outputs", value: scoredOutputCount.toLocaleString(), tone: scoredOutputCount ? "info" : "warning" },
    { label: "OOT Stability", value: ootResult?.psi ? `${ootResult.psi.status.toUpperCase()} | ${ootResult.psi.value.toFixed(3)}` : "Not evaluated" },
  ];

  if (finalModelReady === null) {
    return <StepShell title="Step 10: Final Model Scoring" subtitle="Loading the governed final-model contract established in Interpretation." variant="modeling" heroMetrics={heroMetrics} nextLabel="Confirm Scoring and Continue to Documentation" nextDisabled><div className="atlas-workflow-section flex min-h-56 items-center justify-center text-sm text-slate-600">Loading final-model artifact...</div></StepShell>;
  }

  if (!finalModelReady) {
    return (
      <StepShell title="Step 10: Final Model Scoring" subtitle="Score TRAIN, External Validation, and Out-of-Time populations only after Interpretation saves the verified final artifact." variant="modeling" heroMetrics={heroMetrics} nextLabel="Confirm Scoring and Continue to Documentation" nextDisabled nextDisabledReason="Run RFE and save the final model in Interpretation before scoring.">
        <AtlasAttentionPanel title="A verified final model is required" tone="warning">
          {finalModelError || "Scoring is intentionally blocked because no saved RFE final-model artifact is available for this project."} <Link className="font-semibold underline" to={projectWorkflowRoute(projectId, "/step09")}>Return to Interpretation</Link>.
        </AtlasAttentionPanel>
      </StepShell>
    );
  }

  return (
    <StepShell
      title="Step 10: Final Model Scoring"
      subtitle={problemType === "regression" ? "Score governed TRAIN, External Validation, and Out-of-Time datasets with the saved final model, then compare prediction accuracy and stability." : "Score governed TRAIN, External Validation, and Out-of-Time datasets with the saved final model, then compare discrimination, lift, calibration, and stability."}
      variant="modeling"
      heroMetrics={heroMetrics}
      nextPath={getNextStepPath("step10")}
      nextDisabled={!scoredOutputCount}
      nextDisabledReason="Score at least one governed TRAIN, External Validation, or OOT population before continuing."
      nextLabel="Confirm Scoring and Continue to Documentation"
      nextStatusLine={`${scoredOutputCount} scored output${scoredOutputCount === 1 ? "" : "s"} available for documentation and monitoring.`}
      showDeveloperTools={false}
    >
      <div className="w-full space-y-7" data-testid="scoring-command-center">
        <section className="overflow-hidden rounded-md border border-slate-800 bg-slate-950 text-white" data-testid="final-model-scoring-contract">
          <div className="border-b border-slate-700 px-5 py-4">
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div>
                <div className="flex items-center gap-2 text-xs font-semibold uppercase text-emerald-300"><LockKeyhole size={15} /> A. Governed Final-Model Scoring Contract</div>
                <h2 className="mt-2 text-xl font-semibold">{finalModelMetadata.name ?? "Saved final model"}</h2>
                <p className="mt-1 max-w-3xl text-sm leading-6 text-slate-300">Read-only artifact identity, preprocessing, calibration, operating policy, and retained-feature lineage established before scoring.</p>
              </div>
              <span className="rounded-full border border-emerald-400/40 bg-emerald-400/10 px-3 py-1 text-xs font-semibold text-emerald-200">Verified artifact</span>
            </div>
          </div>
          <div className="grid gap-px bg-slate-700 sm:grid-cols-2 xl:grid-cols-4">
            <ContractMetric label="Model version" value={resolveFinalModelVersionDisplay(finalModelMetadata)} />
            <ContractMetric label="Model family" value={modelFamilyLabel} />
            <ContractMetric label="Retained features" value={String(finalModelMetadata.feature_count ?? finalModelMetadata.features?.length ?? "-")} />
            <ContractMetric label="Selection method" value={finalModelMetadata.feature_selection_method ?? "Saved in Interpretation"} />
            <ContractMetric label="Preprocessing" value={finalModelMetadata.preprocessing_pipeline ?? "Persisted training pipeline"} />
            <ContractMetric label="Calibration" value={finalModelMetadata.calibration_method ?? (problemType === "classification" ? "Model-native / not recorded" : "Not applicable")} />
            <ContractMetric label="Proposed threshold" value={typeof proposedPolicy?.threshold === "number" ? proposedPolicy.threshold.toFixed(3) : "No proposed policy"} />
            <ContractMetric label="Natural event rate" value={formatRate(finalModelMetadata.natural_event_rate)} />
          </div>
          <details className="border-t border-slate-700 px-5 py-3 text-sm">
            <summary className="cursor-pointer font-semibold text-slate-200">Feature manifest, hashes, and lineage</summary>
            <div className="mt-3 grid gap-3 text-xs text-slate-300 lg:grid-cols-3">
              <div><span className="font-semibold text-slate-100">Artifact hash:</span> {finalModelMetadata.artifact_hash ?? "Not recorded"}</div>
              <div><span className="font-semibold text-slate-100">Training dataset version:</span> {resolveCanonicalScoringDatasetVersion(finalModelMetadata) || "Not recorded"}</div>
              <div><span className="font-semibold text-slate-100">Source candidate:</span> {finalModelMetadata.source_model ?? "Not recorded"}</div>
              <div className="lg:col-span-3"><span className="font-semibold text-slate-100">Features:</span> {finalModelMetadata.features?.length ? finalModelMetadata.features.join(", ") : "No retained-feature manifest was returned."}</div>
            </div>
          </details>
        </section>

        {message && <div className="rounded-md border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-950">{message}</div>}

        <ScoringHistoryPanel
          key={[
            trainResult?.scoringRunId ?? "",
            testResult?.scoringRunId ?? "",
            ootResult?.scoringRunId ?? "",
          ].join("|")}
          exactContext={exactScoringContext}
          onArchive={() => setScoringHistoryRevision((revision) => revision + 1)}
        />

        {problemType === "classification" ? (
          <section className="border-l-4 border-indigo-500 bg-indigo-50/60 px-5 py-4">
            <div className="flex flex-wrap items-end gap-4">
              <label className="grid gap-1 text-sm">
                <span className="text-xs font-semibold uppercase text-indigo-700">Scoring probability scale</span>
                <select className="rounded-md border border-indigo-200 bg-white px-3 py-2" value={correctionMethod} onChange={(event) => setCorrectionMethod(event.target.value)}>
                  <option value="none">Raw model probabilities</option>
                  <option value="prior_odds">Prior odds correction / Pozzolo-style</option>
                </select>
              </label>
              <label className="grid gap-1 text-sm"><span className="text-xs font-semibold uppercase text-indigo-700">Natural event prior</span><input className="w-40 rounded-md border border-indigo-200 bg-white px-3 py-2" value={originalPrior} onChange={(event) => setOriginalPrior(event.target.value)} placeholder="Auto-detect" /></label>
              <label className="grid gap-1 text-sm"><span className="text-xs font-semibold uppercase text-indigo-700">Modeled event prior</span><input className="w-40 rounded-md border border-indigo-200 bg-white px-3 py-2" value={modelPrior} onChange={(event) => setModelPrior(event.target.value)} placeholder="Auto-detect" /></label>
              <p className="max-w-lg text-xs leading-5 text-indigo-900">Apply prior correction only when training changed class prevalence. Every scored population uses the same governed choice in this session.</p>
            </div>
            <PozzoloPriorCorrectionCard correctionMethod={correctionMethod} originalPrior={originalPrior} modelPrior={modelPrior} result={testResult ?? trainResult ?? ootResult} />
          </section>
        ) : null}

        <section className="border-l-4 border-slate-500 bg-slate-50 px-4 py-5" data-testid="train-scoring-zone">
          <ScoringZoneHeader code="B" icon={<Database size={17} />} title="TRAIN Scoring - Development Diagnostics" description="Score the governed development population to establish the reference distribution. TRAIN is diagnostic evidence, not independent performance evidence." status={trainResult ? `${trainResult.rows?.toLocaleString() ?? "-"} rows scored` : "Awaiting score run"} />
          <DevelopmentSplitCard title="Development TRAIN output" description="Use the fitted TRAIN split already held by the backend. No re-upload is required." loading={loading === "train"} onScore={() => handleDevelopmentSplit("train")} result={trainResult} problemType={problemType} datasetType="train" onRegister={registerResult} suggestedDatasetName={`${projectName || "ATLAS Project"} - TRAIN Scored Output`} showRegistration={false} />
        </section>

        <section className="border-l-4 border-blue-600 bg-blue-50/50 px-4 py-5" data-testid="test-scoring-zone">
          <ScoringZoneHeader code="C" icon={<UploadCloud size={17} />} title="TEST Scoring - Independent In-Time Evaluation" description="Score an independent validation population and calculate performance plus drift against development TRAIN when the target is present." status={testResult ? `${testResult.rows?.toLocaleString() ?? "-"} rows scored` : "External dataset required"} />
          <UploadCard title="External Validation Dataset / TEST Scored Output" description="Upload a CSV with the final-model feature schema. Performance metrics are calculated only when the governed target is present." loading={loading === "test"} onFile={(file) => handleFile(file, "test")} result={testResult} problemType={problemType} datasetType="test" onRegister={registerResult} suggestedDatasetName={`${projectName || "ATLAS Project"} - TEST Scored Output`} showRegistration={false} />
        </section>

        <section className="border-l-4 border-amber-500 bg-amber-50/50 px-4 py-5" data-testid="oot-scoring-zone">
          <ScoringZoneHeader code="D" icon={<Activity size={17} />} title="OOT Scoring - Out-of-Time Stability Evaluation" description="Score a later time window to test temporal transportability. Prediction PSI and feature VSI use development TRAIN as the governed reference." status={ootResult ? `${ootResult.rows?.toLocaleString() ?? "-"} rows scored` : "Later-period dataset required"} />
          <UploadCard title="Out-of-Time Dataset / OOT Scored Output" description="Upload a later-period CSV with the final-model feature schema. ATLAS keeps OOT separate from TEST for transparent temporal validation." loading={loading === "oot"} onFile={(file) => handleFile(file, "oot")} result={ootResult} problemType={problemType} datasetType="oot" onRegister={registerResult} suggestedDatasetName={`${projectName || "ATLAS Project"} - OOT Scored Output`} showRegistration={false} />
        </section>

        <section className="rounded-md border border-slate-200 bg-white p-5" data-testid="cross-dataset-performance">
          <ScoringZoneHeader code="E" icon={<BarChart3 size={17} />} title="Cross-Dataset Performance" description="Compare actual metrics across the scored populations. Empty cells mean the backend could not evaluate that metric, usually because the target was absent." status={`${scoredOutputCount}/3 populations available`} />
          <CrossDatasetPerformance problemType={problemType} trainResult={trainResult} testResult={testResult} ootResult={ootResult} />
        </section>

        <section className="rounded-md border border-emerald-200 bg-emerald-50/40 p-5" data-testid="stability-command-center">
          <ScoringZoneHeader code="F" icon={<ShieldCheck size={17} />} title="Stability Command Center" description="Prediction PSI and Variable Stability Index compare TEST and OOT to development TRAIN. Pass/warning/fail statuses are backend-calculated from real scored populations." status={stabilityStatus(testResult, ootResult)} />
          <StabilityCommandCenter trainResult={trainResult} testResult={testResult} ootResult={ootResult} problemType={problemType} onSaveEvidence={() => void saveStabilityArtifact("evidence")} onAddMonitoring={() => void saveStabilityArtifact("monitoring")} />
        </section>

        <section className="rounded-md border border-blue-200 bg-blue-50/40 p-5" data-testid="scored-output-registration">
          <ScoringZoneHeader code="G" icon={<Save size={17} />} title="Scored Output Registration" description="Register full scored rows and diagnostic columns only after reviewing the scoring results above." status={registeredScoredDataset ? `${registeredScoredDataset.split.toUpperCase()} registered` : "No output registered this session"} />
          <RegistrationCommandCenter projectName={projectName} problemType={problemType} trainResult={trainResult} testResult={testResult} ootResult={ootResult} onRegister={registerResult} />
          {registeredScoredDataset ? <RegisteredOutputNotice record={registeredScoredDataset} /> : null}
        </section>

        <section className="border-t border-slate-300 pt-5" data-testid="scoring-developer-tools">
          <ScoringZoneHeader code="H" icon={<Code2 size={17} />} title="Developer Tools and Reproducibility" description="Inspect generated code and preserve governed custom-code changes after the analytical review is complete." status="Collapsed by default" />
          <StepPythonPanel />
        </section>
      </div>
    </StepShell>
  );
}

type ProposedOperatingPolicy = {
  model?: string;
  threshold?: number;
  reviewCapacity?: number;
  metrics?: Record<string, unknown>;
  savedAt?: string;
};

function readProposedOperatingPolicy(projectId: string): ProposedOperatingPolicy | null {
  try {
    const raw = localStorage.getItem(`atlas-proposed-operating-policy:${projectId}`);
    return raw ? JSON.parse(raw) as ProposedOperatingPolicy : null;
  } catch {
    return null;
  }
}

function formatRate(value?: number | null) {
  return typeof value === "number" && Number.isFinite(value) ? `${(value * 100).toFixed(2)}%` : "Not recorded";
}

function ContractMetric({ label, value }: { label: string; value: string }) {
  return <div className="min-h-20 bg-slate-900 px-4 py-3"><div className="text-[10px] font-semibold uppercase text-slate-400">{label}</div><div className="mt-1 text-sm font-semibold leading-5 text-white">{value}</div></div>;
}

function ScoringZoneHeader({ code, icon, title, description, status }: { code: string; icon: ReactNode; title: string; description: string; status: string }) {
  return (
    <div className="mb-4 flex flex-wrap items-start justify-between gap-4">
      <div className="max-w-4xl">
        <div className="flex items-center gap-2 text-xs font-semibold uppercase text-blue-700">{icon} {code}. Scoring command center</div>
        <h2 className="mt-1 text-lg font-semibold text-slate-950">{title}</h2>
        <p className="mt-1 text-sm leading-6 text-slate-600">{description}</p>
      </div>
      <span className="rounded-full border border-slate-200 bg-white px-3 py-1 text-xs font-semibold text-slate-700">{status}</span>
    </div>
  );
}

function metricNumber(result: ScoreResult | null, key: string) {
  const value = result?.metrics?.[key];
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function topDecileValue(result: ScoreResult | null, key: "lift" | "capture_rate") {
  const rows = result?.lift ?? [];
  const top = rows.find((row) => row.decile === 1) ?? rows[0];
  const value = top?.[key];
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function displayMetric(value: number | null, digits = 4) {
  return value == null ? "-" : value.toFixed(digits);
}

function displayDelta(reference: number | null, comparison: number | null) {
  if (reference == null || comparison == null) return "-";
  const delta = comparison - reference;
  return `${delta >= 0 ? "+" : ""}${delta.toFixed(4)}`;
}

function CrossDatasetPerformance({ problemType, trainResult, testResult, ootResult }: { problemType: "classification" | "regression"; trainResult: ScoreResult | null; testResult: ScoreResult | null; ootResult: ScoreResult | null }) {
  const populations = [
    { label: "TRAIN", result: trainResult, color: "#475569" },
    { label: "TEST", result: testResult, color: "#2563eb" },
    { label: "OOT", result: ootResult, color: "#d97706" },
  ];
  const metrics = problemType === "classification"
    ? [
        { label: "ROC-AUC", value: (result: ScoreResult | null) => metricNumber(result, "auc") },
        { label: "PR-AUC", value: (result: ScoreResult | null) => metricNumber(result, "pr_auc") },
        { label: "Accuracy (context only)", value: (result: ScoreResult | null) => metricNumber(result, "accuracy"), muted: true },
        { label: "Precision", value: (result: ScoreResult | null) => metricNumber(result, "precision") },
        { label: "Recall", value: (result: ScoreResult | null) => metricNumber(result, "recall") },
        { label: "F1", value: (result: ScoreResult | null) => metricNumber(result, "f1") },
        { label: "KS", value: (result: ScoreResult | null) => metricNumber(result, "ks") },
        { label: "Top-decile lift", value: (result: ScoreResult | null) => topDecileValue(result, "lift") },
        { label: "Top-decile capture", value: (result: ScoreResult | null) => topDecileValue(result, "capture_rate") },
        { label: "Brier score", value: (result: ScoreResult | null) => metricNumber(result, "brier_score") },
        { label: "Mean score", value: (result: ScoreResult | null) => result?.score_summary?.mean ?? null },
        { label: "Event rate", value: (result: ScoreResult | null) => metricNumber(result, "event_rate") },
      ]
    : [
        { label: "RMSE", value: (result: ScoreResult | null) => metricNumber(result, "rmse") },
        { label: "MAE", value: (result: ScoreResult | null) => metricNumber(result, "mae") },
        { label: "R-squared", value: (result: ScoreResult | null) => metricNumber(result, "r2") },
        { label: "Adjusted R-squared", value: (result: ScoreResult | null) => metricNumber(result, "adjusted_r2") },
        { label: "Mean prediction", value: (result: ScoreResult | null) => result?.score_summary?.mean ?? null },
      ];
  if (!populations.some(({ result }) => result)) return <EmptyScoringState text="Score at least one population to populate the comparison table and metric movement visual." />;
  return (
    <div className="space-y-5">
      <div className="overflow-x-auto rounded-md border border-slate-200">
        <table className="min-w-[860px] w-full text-sm">
          <thead className="bg-slate-950 text-left text-xs uppercase text-slate-200"><tr><th className="px-4 py-3">Metric</th><th className="px-4 py-3">TRAIN <span className="block text-[9px] font-normal normal-case text-slate-400">Development diagnostics</span></th><th className="px-4 py-3">TEST</th><th className="px-4 py-3">OOT</th><th className="px-4 py-3">TEST change</th><th className="px-4 py-3">OOT change</th></tr></thead>
          <tbody>{metrics.map((metric) => {
            const train = metric.value(trainResult), test = metric.value(testResult), oot = metric.value(ootResult);
            return <tr key={metric.label} className={`border-t border-slate-200 ${"muted" in metric && metric.muted ? "bg-slate-50 text-slate-500" : "bg-white"}`}><td className="px-4 py-3 font-semibold">{metric.label}</td><td className="px-4 py-3 font-mono">{displayMetric(train)}</td><td className="px-4 py-3 font-mono">{displayMetric(test)}</td><td className="px-4 py-3 font-mono">{displayMetric(oot)}</td><td className="px-4 py-3 font-mono">{displayDelta(train, test)}</td><td className="px-4 py-3 font-mono">{displayDelta(train, oot)}</td></tr>;
          })}</tbody>
        </table>
      </div>
      <MetricMovementChart problemType={problemType} populations={populations} />
      {problemType === "regression" && (testResult || ootResult) ? <RegressionScoringComparison testResult={testResult} ootResult={ootResult} /> : null}
    </div>
  );
}

function MetricMovementChart({ problemType, populations }: { problemType: "classification" | "regression"; populations: Array<{ label: string; result: ScoreResult | null; color: string }> }) {
  const definitions = problemType === "classification"
    ? [{ label: "ROC-AUC", key: "auc" }, { label: "PR-AUC", key: "pr_auc" }, { label: "KS", key: "ks" }]
    : [{ label: "RMSE", key: "rmse" }, { label: "MAE", key: "mae" }, { label: "R-squared", key: "r2" }];
  return (
    <div className="rounded-md border border-slate-200 bg-slate-50 p-4">
      <div className="text-sm font-semibold text-slate-900">Metric movement by population</div>
      <div className="mt-4 grid gap-5 lg:grid-cols-3">
        {definitions.map((definition) => {
          const values = populations.map(({ result }) => metricNumber(result, definition.key));
          const max = Math.max(...values.filter((value): value is number => value != null), 0.0001);
          return <div key={definition.key}><div className="text-xs font-semibold uppercase text-slate-500">{definition.label}</div><div className="mt-3 space-y-2">{populations.map(({ label, result, color }) => { const value = metricNumber(result, definition.key); return <div key={label} className="grid grid-cols-[42px_1fr_58px] items-center gap-2 text-xs"><span className="font-semibold text-slate-600">{label}</span><div className="h-2.5 rounded-sm bg-slate-200"><div className="h-2.5 rounded-sm" style={{ width: value == null ? "0%" : `${Math.max(3, Math.min(100, (value / max) * 100))}%`, backgroundColor: color }} /></div><span className="font-mono text-right">{displayMetric(value, 3)}</span></div>; })}</div></div>;
        })}
      </div>
    </div>
  );
}

function stabilityStatus(testResult: ScoreResult | null, ootResult: ScoreResult | null) {
  const rows = [testResult?.psi, ootResult?.psi].filter(Boolean) as Array<{ status: Status }>;
  if (!rows.length) return "Awaiting TEST or OOT";
  if (rows.some((row) => row.status === "fail")) return "Review required";
  if (rows.some((row) => row.status === "warning")) return "Warning";
  return "Within tolerance";
}

function StabilityCommandCenter({ trainResult, testResult, ootResult, problemType, onSaveEvidence, onAddMonitoring }: { trainResult: ScoreResult | null; testResult: ScoreResult | null; ootResult: ScoreResult | null; problemType: "classification" | "regression"; onSaveEvidence: () => void; onAddMonitoring: () => void }) {
  const comparisons = [{ label: "TRAIN vs TEST", result: testResult }, { label: "TRAIN vs OOT", result: ootResult }];
  const available = comparisons.some(({ result }) => result?.psi || result?.vsi?.length);
  return (
    <div className="space-y-5">
      {!available ? <EmptyScoringState text="Score TEST or OOT to calculate prediction PSI and feature-level VSI against development TRAIN." /> : (
        <div className="grid gap-5 xl:grid-cols-2">
          {comparisons.map(({ label, result }) => <div key={label} className="rounded-md border border-slate-200 bg-white p-4"><div className="flex items-center justify-between gap-3"><h3 className="font-semibold text-slate-950">{label}</h3>{result?.psi ? <span className={`rounded-full border px-2.5 py-1 text-xs font-semibold uppercase ${statusClass(result.psi.status)}`}>{result.psi.status}</span> : null}</div>{result?.psi ? <div className="mt-4 grid gap-3 sm:grid-cols-3"><Stat label="Prediction PSI" value={result.psi.value.toFixed(4)} /><Stat label="VSI features" value={String(result.vsi?.length ?? 0)} /><Stat label="Reference" value="Development TRAIN" /></div> : <div className="mt-4 text-sm text-slate-500">This population has not been scored with a valid development reference.</div>}</div>)}
        </div>
      )}
      {available ? <><ScoreDistributionComparison trainResult={trainResult} testResult={testResult} ootResult={ootResult} problemType={problemType} /><CombinedVsiTable testResult={testResult} ootResult={ootResult} /></> : null}
      <div className="flex flex-wrap items-center justify-between gap-3 border-t border-emerald-200 pt-4">
        <p className="text-xs leading-5 text-slate-600">Thresholds: pass below 0.10, warning from 0.10 to below 0.25, fail at 0.25 or above. Evidence records the exact backend values and reference population.</p>
        <div className="flex flex-wrap gap-2"><button type="button" className="atlas-secondary-button" onClick={onSaveEvidence} disabled={!available}><Save size={15} /> Save as Evidence</button><button type="button" className="atlas-primary-button" onClick={onAddMonitoring} disabled={!available}><Activity size={15} /> Add to Monitoring Plan</button></div>
      </div>
    </div>
  );
}

function scoredValues(result: ScoreResult | null) {
  if (!result) return [];
  const source = result.scored_rows?.length ? result.scored_rows : result.preview ?? [];
  return source.map((row) => {
    const candidate = row.adjusted_score ?? row.score ?? row.predicted_value;
    const value = typeof candidate === "number" ? candidate : Number(candidate);
    return Number.isFinite(value) ? value : null;
  }).filter((value): value is number => value != null);
}

function ScoreDistributionComparison({ trainResult, testResult, ootResult, problemType }: { trainResult: ScoreResult | null; testResult: ScoreResult | null; ootResult: ScoreResult | null; problemType: "classification" | "regression" }) {
  const series = useMemo(() => [
    { label: "TRAIN", color: "#475569", values: scoredValues(trainResult) },
    { label: "TEST", color: "#2563eb", values: scoredValues(testResult) },
    { label: "OOT", color: "#d97706", values: scoredValues(ootResult) },
  ], [trainResult, testResult, ootResult]);
  const all = series.flatMap((item) => item.values);
  if (!all.length) return null;
  // Linear scan instead of Math.min(...all)/Math.max(...all): spreading the
  // full scored output (100k+ values per population) as arguments overflows
  // the JS call stack (RangeError) and white-screened the whole Scoring page
  // for real-sized datasets (Stage B.7 defect B7-D1).
  let min = Infinity, max = -Infinity;
  for (const value of all) {
    if (value < min) min = value;
    if (value > max) max = value;
  }
  const span = Math.max(max - min, 1e-9), bins = 18;
  const distributions = series.map((item) => {
    const counts = Array.from({ length: bins }, () => 0);
    item.values.forEach((value) => { counts[Math.min(bins - 1, Math.max(0, Math.floor(((value - min) / span) * bins)))] += 1; });
    const total = Math.max(1, item.values.length);
    return { ...item, shares: counts.map((count) => count / total) };
  });
  const peak = Math.max(...distributions.flatMap((item) => item.shares), 0.001);
  const width = 820, height = 270, left = 52, right = 18, top = 24, bottom = 42;
  const x = (index: number) => left + (index / Math.max(1, bins - 1)) * (width - left - right);
  const y = (value: number) => top + (1 - value / peak) * (height - top - bottom);
  return (
    <div className="rounded-md border border-slate-200 bg-white p-4" data-testid="score-distribution-comparison">
      <div className="flex flex-wrap items-start justify-between gap-3"><div><div className="text-xs font-semibold uppercase text-emerald-700">Score shift</div><h3 className="mt-1 font-semibold text-slate-950">{problemType === "regression" ? "Prediction" : "Score"} distribution comparison</h3><p className="mt-1 text-xs text-slate-500">Curves use the full scored output returned by the backend when available.</p></div><div className="flex gap-3 text-xs">{distributions.map((item) => <span key={item.label} className="flex items-center gap-1"><span className="h-2.5 w-2.5 rounded-sm" style={{ backgroundColor: item.color }} />{item.label}</span>)}</div></div>
      <div className="mt-3 overflow-x-auto"><svg viewBox={`0 0 ${width} ${height}`} className="min-w-[720px] w-full" role="img" aria-label={`${problemType === "regression" ? "Prediction" : "Score"} distribution comparison across TRAIN TEST and OOT`}><line x1={left} y1={height - bottom} x2={width - right} y2={height - bottom} stroke="#94a3b8" /><line x1={left} y1={top} x2={left} y2={height - bottom} stroke="#94a3b8" />{distributions.filter((item) => item.values.length).map((item) => <polyline key={item.label} points={item.shares.map((value, index) => `${x(index)},${y(value)}`).join(" ")} fill="none" stroke={item.color} strokeWidth="3" strokeLinejoin="round" />)}<text x={left} y={height - 16} className="fill-slate-500 text-[11px]">{min.toFixed(3)}</text><text x={width - right} y={height - 16} textAnchor="end" className="fill-slate-500 text-[11px]">{max.toFixed(3)}</text><text x={width / 2} y={height - 8} textAnchor="middle" className="fill-slate-600 text-[11px]">{problemType === "regression" ? "Predicted value" : "Score / probability"}</text><text x={14} y={height / 2} transform={`rotate(-90 14 ${height / 2})`} textAnchor="middle" className="fill-slate-600 text-[11px]">Share of population</text></svg></div>
    </div>
  );
}

function CombinedVsiTable({ testResult, ootResult }: { testResult: ScoreResult | null; ootResult: ScoreResult | null }) {
  const test = new Map((testResult?.vsi ?? []).map((row) => [row.feature, row]));
  const oot = new Map((ootResult?.vsi ?? []).map((row) => [row.feature, row]));
  const features = [...new Set([...test.keys(), ...oot.keys()])].map((feature) => ({ feature, test: test.get(feature), oot: oot.get(feature) })).sort((a, b) => Math.max(b.test?.value ?? -1, b.oot?.value ?? -1) - Math.max(a.test?.value ?? -1, a.oot?.value ?? -1)).slice(0, 20);
  if (!features.length) return null;
  const rank = (testStatus?: Status, ootStatus?: Status): Status => testStatus === "fail" || ootStatus === "fail" ? "fail" : testStatus === "warning" || ootStatus === "warning" ? "warning" : "pass";
  return (
    <div className="rounded-md border border-slate-200 bg-white p-4" data-testid="combined-variable-stability-index">
      <div className="flex flex-wrap items-start justify-between gap-3"><div><div className="text-xs font-semibold uppercase text-emerald-700">Variable Stability Index</div><h3 className="mt-1 font-semibold text-slate-950">Top unstable retained variables</h3><p className="mt-1 text-xs text-slate-500">Ranked by the largest observed shift across TEST and OOT.</p></div><Link className="atlas-secondary-button" to="/model-diagnostics">Distribution drill-down</Link></div>
      <div className="mt-4 max-h-96 overflow-auto rounded-md border border-slate-200"><table className="w-full min-w-[660px] text-sm"><thead className="sticky top-0 bg-slate-950 text-left text-xs uppercase text-slate-200"><tr><th className="px-3 py-2">Rank</th><th className="px-3 py-2">Feature</th><th className="px-3 py-2">TRAIN vs TEST VSI</th><th className="px-3 py-2">TRAIN vs OOT VSI</th><th className="px-3 py-2">Status</th></tr></thead><tbody>{features.map((row, index) => { const status = rank(row.test?.status, row.oot?.status); return <tr key={row.feature} className="border-t border-slate-200"><td className="px-3 py-2 font-semibold">{index + 1}</td><td className="px-3 py-2 font-medium text-slate-950">{row.feature}</td><td className="px-3 py-2 font-mono">{row.test?.value.toFixed(4) ?? "-"}</td><td className="px-3 py-2 font-mono">{row.oot?.value.toFixed(4) ?? "-"}</td><td className="px-3 py-2"><span className={`rounded-full border px-2 py-1 text-[10px] font-semibold uppercase ${statusClass(status)}`}>{status}</span></td></tr>; })}</tbody></table></div>
    </div>
  );
}

function RegistrationCommandCenter({ projectName, problemType, trainResult, testResult, ootResult, onRegister }: { projectName: string; problemType: "classification" | "regression"; trainResult: ScoreResult | null; testResult: ScoreResult | null; ootResult: ScoreResult | null; onRegister: (result: ScoreResult, datasetType: ScoredSplit, datasetName?: string) => Promise<void> }) {
  const [names, setNames] = useState<Record<ScoredSplit, string>>({ train: `${projectName || "ATLAS Project"} - TRAIN Scored Output`, test: `${projectName || "ATLAS Project"} - TEST Scored Output`, oot: `${projectName || "ATLAS Project"} - OOT Scored Output` });
  const [busy, setBusy] = useState<ScoredSplit | "">("");
  useEffect(() => setNames({ train: `${projectName || "ATLAS Project"} - TRAIN Scored Output`, test: `${projectName || "ATLAS Project"} - TEST Scored Output`, oot: `${projectName || "ATLAS Project"} - OOT Scored Output` }), [projectName]);
  const rows = [{ split: "train" as const, result: trainResult }, { split: "test" as const, result: testResult }, { split: "oot" as const, result: ootResult }];
  async function register(split: ScoredSplit, result: ScoreResult) { setBusy(split); try { await onRegister(result, split, names[split]); } finally { setBusy(""); } }
  return (
    <div className="space-y-3">
      {rows.map(({ split, result }) => <div key={split} className="grid gap-3 rounded-md border border-blue-100 bg-white p-3 lg:grid-cols-[90px_minmax(220px,1fr)_repeat(3,minmax(90px,0.45fr))_auto] lg:items-center"><div className="font-semibold text-slate-950">{split.toUpperCase()}</div><label className="grid gap-1"><span className="text-[10px] font-semibold uppercase text-slate-500">Registered dataset name</span><input className="rounded-md border border-slate-200 px-3 py-2 text-sm" value={names[split]} onChange={(event) => setNames((current) => ({ ...current, [split]: event.target.value }))} /></label><RegistrationFact label="Rows" value={result?.rows?.toLocaleString() ?? "Not scored"} /><RegistrationFact label="Columns" value={String(result?.scored_columns?.length ?? 0)} /><RegistrationFact label="Scope" value={result?.scored_row_scope === "full_scored_output" ? "Full output" : result ? "Preview" : "-"} /><button type="button" className="atlas-primary-button justify-center" disabled={!result || busy !== ""} onClick={() => result && void register(split, result)}>{busy === split ? "Registering..." : "Register"}</button></div>)}
      <div className="flex flex-wrap gap-2 pt-2"><Link className="atlas-secondary-button" to="/datasets"><Database size={15} /> Dataset Library</Link><Link className="atlas-secondary-button" to="/model-diagnostics"><Activity size={15} /> Model Diagnostics</Link><Link className="atlas-secondary-button" to="/chart-studio"><BarChart3 size={15} /> Chart Studio</Link></div>
      <p className="text-xs text-slate-500">Registration preserves the full scored rows returned by the backend, the final-model name, task, target role, score/prediction fields, residuals where applicable, and stability metadata.</p>
    </div>
  );
}

function RegistrationFact({ label, value }: { label: string; value: string }) { return <div><div className="text-[10px] font-semibold uppercase text-slate-500">{label}</div><div className="mt-1 text-sm font-semibold text-slate-800">{value}</div></div>; }

function RegisteredOutputNotice({ record }: { record: { datasetId: string; versionId?: string; split: ScoredSplit } }) {
  return <div className="mt-4 rounded-md border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-950"><div className="font-semibold">Scored {record.split.toUpperCase()} output registered</div><div className="mt-1">The dataset is available for diagnostics, charts, lineage, and monitoring.</div><div className="mt-3 flex flex-wrap gap-2"><Link className="atlas-primary-button" to={`/model-diagnostics?datasetId=${record.datasetId}${record.versionId ? `&versionId=${record.versionId}` : ""}`}>Open Model Diagnostics</Link><Link className="atlas-secondary-button" to={`/chart-studio?datasetId=${record.datasetId}`}>Open Chart Studio</Link></div></div>;
}

function EmptyScoringState({ text }: { text: string }) { return <div className="rounded-md border border-dashed border-slate-300 bg-slate-50 px-4 py-8 text-center text-sm text-slate-600">{text}</div>; }

function UploadCard({
  title,
  description,
  loading,
  onFile,
  result,
  showStability = false,
  showRegistration = true,
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
  showRegistration?: boolean;
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
    <section className="rounded-md border border-slate-200 bg-white p-5 shadow-sm">
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
          {showRegistration ? <div className="rounded-md border border-blue-200 bg-blue-50 p-4 text-sm text-blue-950">
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
          </div> : null}
          <div className="grid gap-3 sm:grid-cols-4">
            <Stat label="Rows" value={String(result.rows ?? "-")} />
            <Stat label={problemType === "regression" ? "Min Prediction" : "Min Score"} value={format(result.score_summary?.min)} />
            <Stat label={problemType === "regression" ? "Mean Prediction" : "Mean Score"} value={format(result.score_summary?.mean)} />
            <Stat label={problemType === "regression" ? "Max Prediction" : "Max Score"} value={format(result.score_summary?.max)} />
          </div>
          <div className="grid gap-3 sm:grid-cols-3">
            <RegistrationFact label="Dataset identity" value={result.dataset_identity ?? `${datasetType.toUpperCase()} uploaded dataset`} />
            <RegistrationFact label="Version / hash" value={result.dataset_version ?? "Not returned"} />
            <RegistrationFact label="Evaluation period" value={result.period?.start && result.period?.end ? `${result.period.start.slice(0, 10)} to ${result.period.end.slice(0, 10)}` : datasetType === "oot" ? "No date column detected" : "In-time validation"} />
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
  showRegistration = true,
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
  showRegistration?: boolean;
}) {
  const [datasetName, setDatasetName] = useState(suggestedDatasetName);
  useEffect(() => setDatasetName(suggestedDatasetName), [suggestedDatasetName]);
  const targetColumn = result?.target_column || result?.model?.target || (result ? detectTargetColumn(result) : undefined);
  const registrationRows = result ? buildScoredRegistrationRows(result, result.task ?? problemType, targetColumn, datasetType) : [];
  const columnsAvailable = registrationRows[0] ? Object.keys(registrationRows[0]) : [];
  const detectedRoles = detectRegistrationRoles(columnsAvailable, result?.task ?? problemType);
  return (
    <section className="rounded-md border border-slate-200 bg-white p-5 shadow-sm">
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
          showRegistration={showRegistration}
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
  showRegistration = true,
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
  showRegistration?: boolean;
}) {
  const targetColumn = result.target_column || result.model?.target || detectTargetColumn(result) || "Not detected";
  return (
    <div className="mt-5 space-y-5">
      {showRegistration ? <div className="rounded-md border border-blue-200 bg-blue-50 p-4 text-sm text-blue-950">
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
      </div> : null}
      <div className="grid gap-3 sm:grid-cols-4">
        <Stat label="Rows" value={String(result.rows ?? "-")} />
        <Stat label={problemType === "regression" ? "Min Prediction" : "Min Score"} value={format(result.score_summary?.min)} />
        <Stat label={problemType === "regression" ? "Mean Prediction" : "Mean Score"} value={format(result.score_summary?.mean)} />
        <Stat label={problemType === "regression" ? "Max Prediction" : "Max Score"} value={format(result.score_summary?.max)} />
      </div>
      <div className="grid gap-3 sm:grid-cols-3"><RegistrationFact label="Dataset identity" value={result.dataset_identity ?? "Governed development TRAIN split"} /><RegistrationFact label="Dataset version" value={result.dataset_version ?? "Not returned"} /><RegistrationFact label="Evidence role" value="Development diagnostics" /></div>
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
