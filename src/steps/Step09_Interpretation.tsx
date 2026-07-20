import React, { useEffect, useMemo, useRef, useState } from "react";
import StepShell from "../components/StepShell";
import { AtlasAttentionPanel, type AtlasWorkflowMetric } from "../components/ui/AtlasWorkflow";
import { logDecision } from "../lib/decisionJournal";
import { inferLocalProblemType, loadLocalDataset, localDatasetVersion } from "../lib/localDataset";
import { loadInterpretationCandidates } from "../lib/interpretationCandidates";
import { useWorkflowStore } from "../state/useWorkflowStore";

const QUERY_API_BASE =
  typeof window !== "undefined" ? new URLSearchParams(window.location.search).get("apiBase")?.replace(/\/$/, "") : undefined;
const API_BASE =
  QUERY_API_BASE ||
  (import.meta.env.VITE_API_BASE as string | undefined)?.replace(/\/$/, "") ||
  "http://127.0.0.1:8001/api";
const RFE_CACHE_KEY = "modeling-tool-rfe-cache";
const LOCAL_SELECTED_INTERPRETATION_MODEL_KEY = "modeling-tool-selected-interpretation-model";
const SHOW_LINEAR_REGRESSION_DEBUG = true;
const RFE_TIMEOUT_MS = 30000;

type RankedRow = { key: string; name: string; task?: "classification" | "regression" | "anomaly"; auc?: number; pr_auc?: number; rmse?: number; mae?: number; r2?: number; adjusted_r2?: number };
type ImportanceRow = { feature: string; importance: number; source?: string; direction?: number };
type AnalysisMeta = { method: string; sampleCount: number | null };
type DetailResponse = {
  ok: boolean;
  kind?: "equation" | "tree" | "generic";
  model_type?: "classification" | "regression";
  intercept?: number;
  coefficients?: RegressionCoefficientRow[];
  inference_available?: boolean;
  inference_message?: string;
  model_fit?: LinearModelFitSummary;
  debug?: ArtifactDebug;
  tree_text?: string;
  message?: string;
  error?: string;
};
type ArtifactDebug = {
  selected_model_key?: string;
  requested_project_id?: string;
  requested_dataset_version?: string;
  requested_target?: string;
  requested_problem_type?: string;
  returned_model_key?: string;
  returned_project_id?: string;
  returned_dataset_version?: string;
  returned_target?: string;
  returned_problem_type?: string;
  training_run_id?: string;
  artifact_has_metadata?: boolean;
};
type RegressionCoefficientRow = {
  variable?: string;
  feature: string;
  coefficient: number;
  standardized_coefficient?: number | null;
  standardized_weight?: number | null;
  standard_error?: number | null;
  t_statistic?: number | null;
  p_value?: number | null;
  ci_lower?: number | null;
  ci_upper?: number | null;
  confidence_interval_lower?: number | null;
  confidence_interval_upper?: number | null;
  direction?: number;
  absolute_rank?: number;
  odds_ratio?: number | null;
};
type LinearModelFitSummary = {
  dependent_variable?: string;
  model_type?: string;
  r2?: number;
  adjusted_r2?: number;
  rmse?: number;
  mae?: number;
  mse?: number;
  n_observations?: number;
  n_predictors?: number;
  residual_df?: number;
  residual_standard_error?: number;
  f_statistic?: number | null;
  prob_f_statistic?: number | null;
  aic?: number | null;
  bic?: number | null;
  log_likelihood?: number | null;
  condition_number?: number | null;
};
type CurveRow = { value: string | number; label?: string; prediction: number };
type SensitivityRow = { scenario: string; prediction: number; delta: number };
type SensitivitySummaryRow = {
  feature: string;
  baseline: number;
  baseline_prediction?: number;
  negative_scenario_prediction?: number | null;
  positive_scenario_prediction?: number | null;
  max_abs_delta: number;
  worst_scenario: string;
  worst_prediction: number;
  worst_delta: number;
  largest_scenario?: string;
  delta?: number;
  direction?: string;
  direction_explanation?: string;
  special_value_note?: string;
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
  prediction_value?: number;
  model_type?: "classification" | "regression";
};
type TreeEdge = { source: number; target: number; label: string };
type TreeResponse = { ok: boolean; nodes?: TreeNode[]; edges?: TreeEdge[]; error?: string; model_type?: "classification" | "regression" };

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
  const res = await fetch(url, { credentials: "include" });
  if (!res.ok) throw new Error(`Request failed (${res.status})`);
  const payload = (await res.json()) as T & { ok?: boolean; error?: string };
  if (payload && typeof payload === "object" && payload.ok === false) throw new Error(payload.error || "The requested analysis is unavailable.");
  return payload as T;
}

async function getJsonWithTimeout<T>(url: string, timeoutMs: number, timeoutMessage: string): Promise<T> {
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), timeoutMs);
  try {
    const res = await fetch(url, { signal: controller.signal, credentials: "include" });
    if (!res.ok) throw new Error(`Request failed (${res.status})`);
    const payload = (await res.json()) as T & { ok?: boolean; error?: string };
    if (payload && typeof payload === "object" && payload.ok === false) throw new Error(payload.error || "The requested analysis is unavailable.");
    return payload as T;
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw new Error(timeoutMessage);
    throw error;
  } finally {
    window.clearTimeout(timer);
  }
}

function isKnnModel(model?: RankedRow, fallbackKey = "") {
  return /knn|nearest/i.test(`${model?.key ?? fallbackKey} ${model?.name ?? ""}`);
}

function isLinearRegressionModel(model?: RankedRow, fallbackKey = "") {
  const text = `${model?.key ?? fallbackKey} ${model?.name ?? ""}`.toLowerCase();
  return /linear regression|linreg|linear_regression/.test(text) && !/logistic|svm|support/.test(text);
}

function isRfeUnsupportedModel(model?: RankedRow, fallbackKey = "") {
  return /knn|nearest|svm|support vector|isolation|anomaly|autoregression|outlier|elliptic|covariance/i.test(`${model?.key ?? fallbackKey} ${model?.name ?? ""}`);
}

function isArtifactContextError(message: string) {
  return /artifact (?:does not match|is not scoped|is missing)|training run does not match|returned key/i.test(message);
}

function displayModelName(model?: RankedRow, fallbackKey = "") {
  if (isKnnModel(model, fallbackKey)) return "K-Nearest Neighbors";
  return model?.name ?? fallbackKey;
}

export default function Step09_Interpretation() {
  const projectId = useWorkflowStore((state) => state.projectId);
  const projectName = useWorkflowStore((state) => state.projectName);
  const getNextStepPath = useWorkflowStore((state) => state.getNextStepPath);
  const [models, setModels] = useState<RankedRow[]>([]);
  const [modelsLoading, setModelsLoading] = useState(true);
  const [selectedModel, setSelectedModel] = useState("");
  const [selectedFeature, setSelectedFeature] = useState("");
  const [importance, setImportance] = useState<ImportanceRow[]>([]);
  const [importanceMeta, setImportanceMeta] = useState<AnalysisMeta>({ method: "", sampleCount: null });
  const [shapMeta, setShapMeta] = useState<AnalysisMeta>({ method: "", sampleCount: null });
  const [explanationLoading, setExplanationLoading] = useState(false);
  const [explanationErrors, setExplanationErrors] = useState<{ importance?: string; shap?: string }>({});
  const [artifactContextError, setArtifactContextError] = useState("");
  const [details, setDetails] = useState<DetailResponse | null>(null);
  const [hyperparameters, setHyperparameters] = useState<HyperparameterRow[]>([]);
  const [pdp, setPdp] = useState<CurveRow[]>([]);
  const [sensitivity, setSensitivity] = useState<SensitivityRow[]>([]);
  const [effectLoading, setEffectLoading] = useState(false);
  const [effectError, setEffectError] = useState("");
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
  const requestedEvaluationModel = useMemo(
    () => (typeof window !== "undefined" ? new URLSearchParams(window.location.search).get("model") ?? "" : ""),
    []
  );
  const explanationSequence = useRef(0);
  const effectSequence = useRef(0);
  const selectedModelRow = models.find((model) => model.key === selectedModel) ?? models[0];
  const activeProblemType = inferLocalProblemType(loadLocalDataset());
  const selectedModelIsRegression =
    activeProblemType === "regression" ||
    selectedModelRow?.task === "regression" ||
    (selectedModelRow?.rmse !== undefined && selectedModelRow?.auc === undefined);
  const selectedModelIsLinearRegression = selectedModelIsRegression && isLinearRegressionModel(selectedModelRow, selectedModel);
  const selectedModelIsKnn = !selectedModelIsRegression && isKnnModel(selectedModelRow, selectedModel);
  const rfeUnsupportedMessage = isRfeUnsupportedModel(selectedModelRow, selectedModel)
    ? "RFE is not available for the selected model. Select a linear, tree, or estimator-compatible model."
    : "";
  const rfeIsRegression = rfeMetric === "rmse" || (!rfeMetric && selectedModelIsRegression);
  const rfeSelectedCount = rfeRows.filter((row) => row.rank <= rfeKeep).length;
  const rfeRemovedCount = Math.max(0, rfeRows.length - rfeSelectedCount);
  const canRunRfe = Boolean(selectedModel) && !rfeRunning && !rfeUnsupportedMessage && !artifactContextError;
  const interpretationContextQuery = useMemo(() => {
    const dataset = loadLocalDataset();
    const params = new URLSearchParams();
    params.set("project_id", projectId);
    params.set("dataset_version", dataset?.dataset_version || localDatasetVersion(dataset));
    params.set("target", dataset?.target ?? "");
    params.set("problem_type", inferLocalProblemType(dataset) ?? "");
    return params.toString();
  }, [projectId]);
  const rfeCacheScope = useMemo(
    () => `${projectId}:${interpretationContextQuery}:${selectedModel}`,
    [interpretationContextQuery, projectId, selectedModel]
  );

  const exportModel = (format: "json" | "jar") => {
    if (format === "jar") {
      setMessage("JAR export is not available for the current Python/scikit-learn pipeline. Use the JSON manifest for governed review, or add an approved ONNX/skops export path for runtime scoring.");
      return;
    }
    window.location.href = `${API_BASE}/model/export?model=final&format=json`;
  };

  useEffect(() => {
    getJson<{ ok: boolean; summary?: { problem_type?: string; ranked?: RankedRow[] }; context_error?: string }>(
      `${API_BASE}/train/last?${interpretationContextQuery}`
    )
      .then((data) => {
        if (data.context_error) setMessage(data.context_error);
        const ranked = (data.summary?.ranked ?? []).filter((row: any) => row.champion_eligible !== false && row.kind !== "anomaly");
        const candidateKeys = new Set(loadInterpretationCandidates(projectId).map((candidate) => candidate.key));
        const selectedCandidates = ranked.filter((row) => candidateKeys.has(row.key));
        setModels(selectedCandidates);
        const savedSelection = sessionStorage.getItem(LOCAL_SELECTED_INTERPRETATION_MODEL_KEY);
        const requestedSelection = selectedCandidates.find((row) => row.key === requestedEvaluationModel)?.key;
        setSelectedModel(requestedSelection ?? selectedCandidates.find((row) => row.key === savedSelection)?.key ?? selectedCandidates[0]?.key ?? "");
      })
      .catch((err) => setMessage(String(err?.message ?? err)))
      .finally(() => setModelsLoading(false));
    getJson<{ ok: boolean; ready: boolean; metadata?: Record<string, unknown> }>(`${API_BASE}/model/final/status`)
      .then((data) => {
        const dataset = loadLocalDataset();
        const expectedVersion = dataset?.dataset_version || localDatasetVersion(dataset);
        const metadata = data.metadata ?? {};
        const sameDataset = !metadata.dataset_version || String(metadata.dataset_version) === expectedVersion;
        const sameProject = !metadata.project_id || String(metadata.project_id) === projectId;
        if (data.ready && sameDataset && sameProject) {
          setFinalModelReady(true);
          setFinalModelStatus("success");
          setFinalModelMessage(`Restored saved final model: ${String(metadata.name ?? "governed final artifact")}.`);
          void loadFinalDiagnostics().catch(() => undefined);
        }
      })
      .catch(() => undefined);
  // The active project controls artifact isolation; model selection changes in the next effect.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId]);

  useEffect(() => {
    if (!selectedModel) return;
    const sequence = explanationSequence.current + 1;
    explanationSequence.current = sequence;
    setMessage("");
    setTreeStructure(null);
    setExplanationLoading(true);
    setExplanationErrors({});
    setArtifactContextError("");
    setImportance([]);
    setShapRows([]);
    setPdp([]);
    setSensitivity([]);
    setSelectedFeature("");
    Promise.allSettled([
      getJson<{ ok: boolean; rows?: ImportanceRow[]; method?: string; sample_count?: number; error?: string }>(
        `${API_BASE}/interpretation/importance?model=${encodeURIComponent(selectedModel)}&${interpretationContextQuery}`
      ),
      getJson<DetailResponse>(
        `${API_BASE}/interpretation/details?model=${encodeURIComponent(selectedModel)}&${interpretationContextQuery}`
      ),
      getJson<{ ok: boolean; rows?: HyperparameterRow[] }>(
        `${API_BASE}/interpretation/hyperparameters?model=${encodeURIComponent(selectedModel)}&${interpretationContextQuery}`
      ),
      getJson<{ ok: boolean; rows?: ImportanceRow[]; method?: string; sample_count?: number }>(
        `${API_BASE}/interpretation/shap?model=${encodeURIComponent(selectedModel)}&${interpretationContextQuery}`
      ),
    ])
      .then(([importanceResult, detailsResult, hyperparameterResult, shapResult]) => {
        if (explanationSequence.current !== sequence) return;
        const importanceRes = importanceResult.status === "fulfilled" ? importanceResult.value : null;
        const detailsRes = detailsResult.status === "fulfilled" ? detailsResult.value : null;
        const hyperparameterRes = hyperparameterResult.status === "fulfilled" ? hyperparameterResult.value : null;
        const shapRes = shapResult.status === "fulfilled" ? shapResult.value : null;
        const rows = importanceRes?.rows ?? [];
        const nextShapRows = shapRes?.rows ?? [];
        const failures = [importanceResult, detailsResult, hyperparameterResult, shapResult]
          .filter((result) => result.status === "rejected")
          .map((result) => String((result as PromiseRejectedResult).reason?.message ?? (result as PromiseRejectedResult).reason));
        const contextFailure = failures.find(isArtifactContextError) ?? "";
        if (contextFailure) {
          setArtifactContextError(contextFailure);
          setImportance([]);
          setShapRows([]);
          setSelectedFeature("");
          setDetails({ ok: false, error: contextFailure });
          setHyperparameters([]);
          setExplanationErrors({ importance: contextFailure, shap: contextFailure });
          setMessage(contextFailure);
          setBoundary(null);
          return;
        }
        setImportance(rows);
        setImportanceMeta({ method: importanceRes?.method ?? "", sampleCount: importanceRes?.sample_count ?? null });
        setDetails(detailsRes ?? { ok: false, error: detailsResult.status === "rejected" ? String(detailsResult.reason?.message ?? detailsResult.reason) : "Model details are unavailable." });
        setHyperparameters(hyperparameterRes?.rows ?? []);
        setShapRows(nextShapRows);
        setShapMeta({ method: shapRes?.method ?? "", sampleCount: shapRes?.sample_count ?? null });
        setExplanationErrors({
          importance: importanceResult.status === "rejected" ? String(importanceResult.reason?.message ?? importanceResult.reason) : undefined,
          shap: shapResult.status === "rejected" ? String(shapResult.reason?.message ?? shapResult.reason) : undefined,
        });
        const firstFeature = rows[0]?.feature ?? nextShapRows[0]?.feature ?? "";
        setSelectedFeature(firstFeature.replace(/^.*__/, ""));
        if (failures.length) setMessage(Array.from(new Set(failures)).join(" "));
        const cachedRfe = loadRfeCache(rfeCacheScope);
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
        if (detailsRes?.kind === "tree") {
          getJson<TreeResponse>(
            `${API_BASE}/eval/tree?model=${encodeURIComponent(selectedModel)}&max_depth=4&${interpretationContextQuery}`
          )
            .then((treeRes) => setTreeStructure(treeRes))
            .catch((err) => setTreeStructure({ ok: false, error: String(err?.message ?? err) }));
        }
      })
      .catch((err) => {
        if (explanationSequence.current === sequence) setMessage(String(err?.message ?? err));
      })
      .finally(() => {
        if (explanationSequence.current === sequence) setExplanationLoading(false);
      });
  }, [selectedModel, interpretationContextQuery, rfeCacheScope]);

  useEffect(() => {
    if (!selectedModel || !selectedFeature || artifactContextError) return;
    const sequence = effectSequence.current + 1;
    effectSequence.current = sequence;
    setEffectLoading(true);
    setEffectError("");
    setPdp([]);
    setSensitivity([]);
    Promise.allSettled([
      getJson<{ ok: boolean; rows?: CurveRow[] }>(
        `${API_BASE}/interpretation/pdp?model=${encodeURIComponent(selectedModel)}&feature=${encodeURIComponent(selectedFeature)}&${interpretationContextQuery}`
      ),
      getJson<{ ok: boolean; rows?: SensitivityRow[] }>(
        `${API_BASE}/interpretation/sensitivity?model=${encodeURIComponent(selectedModel)}&feature=${encodeURIComponent(selectedFeature)}&${interpretationContextQuery}`
      ),
    ])
      .then(([pdpResult, sensitivityResult]) => {
        if (effectSequence.current !== sequence) return;
        const pdpRes = pdpResult.status === "fulfilled" ? pdpResult.value : null;
        const sensitivityRes = sensitivityResult.status === "fulfilled" ? sensitivityResult.value : null;
        setPdp(pdpRes?.rows ?? []);
        setSensitivity(sensitivityRes?.rows ?? []);
        const failures = [pdpResult, sensitivityResult]
          .filter((result) => result.status === "rejected")
          .map((result) => String((result as PromiseRejectedResult).reason?.message ?? (result as PromiseRejectedResult).reason));
        if (failures.length) setEffectError(Array.from(new Set(failures)).join(" "));
      })
      .finally(() => {
        if (effectSequence.current === sequence) setEffectLoading(false);
      });
  }, [selectedModel, selectedFeature, interpretationContextQuery, artifactContextError]);

  useEffect(() => {
    if (!selectedModel || artifactContextError) {
      setBoundary(null);
      return;
    }
    const params = new URLSearchParams({ model: selectedModel });
    if (boundaryX) params.set("x_feature", boundaryX);
    if (boundaryY) params.set("y_feature", boundaryY);
    const contextParams = new URLSearchParams(interpretationContextQuery);
    contextParams.forEach((value, key) => params.set(key, value));
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
  }, [selectedModel, boundaryX, boundaryY, interpretationContextQuery, artifactContextError]);

  const featureOptions = useMemo(
    () => Array.from(new Set([...importance, ...shapRows].map((row) => row.feature.replace(/^.*__/, "")))),
    [importance, shapRows]
  );

  const runRfe = () => {
    if (!selectedModel || rfeRunning) return;
    if (rfeUnsupportedMessage) {
      setRfeError(rfeUnsupportedMessage);
      setMessage(rfeUnsupportedMessage);
      return;
    }
    setRfeRunning(true);
    setMessage("Running RFE with timeout protection. ATLAS limits feature elimination requests so the workflow cannot remain stuck.");
    setRfeError("");
    getJsonWithTimeout<RfeResult>(
      `${API_BASE}/interpretation/rfe?model=${encodeURIComponent(selectedModel)}&keep=${rfeKeep}&${interpretationContextQuery}`,
      RFE_TIMEOUT_MS,
      "RFE timed out after 30 seconds. Try a smaller feature set or select a linear, tree, or estimator-compatible model."
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
        saveRfeCache(rfeCacheScope, data, nextKeep);
      })
      .catch((err) => {
        const text = String(err?.message ?? err);
        setRfeError(`RFE could not complete: ${text}`);
        setMessage(`RFE could not complete: ${text}`);
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
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          model: selectedModel,
          keep: rfeKeep,
          ...Object.fromEntries(new URLSearchParams(interpretationContextQuery)),
        }),
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

  const heroMetrics: AtlasWorkflowMetric[] = [
    { label: "Project", value: projectName },
    { label: "Candidate Models", value: models.length.toLocaleString(), tone: models.length ? "info" : "warning" },
    { label: "Selected Model", value: displayModelName(selectedModelRow, selectedModel) || "Not selected" },
    { label: "Problem Type", value: selectedModelIsRegression ? "Regression" : "Classification" },
    { label: "Importance Drivers", value: importance.length.toLocaleString(), tone: importance.length ? "success" : "warning" },
    { label: "RFE Status", value: rfeRows.length ? `${rfeSelectedCount} retained` : "Not run", tone: rfeRows.length ? "info" : "warning" },
    { label: "Final Artifact", value: finalModelReady ? "Saved" : "Required", tone: finalModelReady ? "success" : "warning" },
  ];

  if (modelsLoading) {
    return <StepShell title="Step 9: Model Interpretation and Final Model" subtitle="Loading governed model artifacts and explanation contracts." variant="modeling" heroMetrics={heroMetrics} nextLabel="Confirm Final Model and Continue to Scoring" nextDisabled><div className="atlas-workflow-section flex min-h-64 items-center justify-center text-sm text-slate-600">Loading trained model artifacts...</div></StepShell>;
  }

  if (!models.length) {
    return (
      <StepShell title="Step 9: Model Interpretation and Final Model" subtitle="Explain a supervised candidate, run RFE, and save the governed final artifact used by Scoring." variant="modeling" heroMetrics={heroMetrics} nextLabel="Confirm Final Model and Continue to Scoring" nextDisabled nextDisabledReason="Train at least one supervised model before Interpretation.">
        <AtlasAttentionPanel title="No models selected for Interpretation" tone="warning">Return to Evaluation and select one or more trained supervised models. Selected candidates are required before interpretation, RFE, and final-model review.</AtlasAttentionPanel>
      </StepShell>
    );
  }

  return (
    <StepShell
      title="Step 9: Model Interpretation and Final Model"
      subtitle="Explain candidate behavior, inspect marginal response, run recursive feature elimination, and save the exact final artifact that Scoring will use."
      variant="modeling"
      eyebrow="Predictive Modeling Workflow"
      heroMetrics={heroMetrics}
      nextPath={getNextStepPath("step09")}
      nextDisabled={!finalModelReady}
      nextDisabledReason="Run RFE and save the governed final model before continuing to Scoring."
      nextLabel="Confirm Final Model and Continue to Scoring"
      nextStatusLine="Scoring will use the saved final-model artifact and its retained feature contract."
    >
    <div className="w-full space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4 rounded-2xl border border-slate-200 bg-slate-50 p-4">
        <div>
          <div className="text-xs font-semibold uppercase tracking-wide text-blue-700">Interpretation workspace</div>
          <h2 className="mt-1 text-lg font-semibold text-slate-950">Candidate explanation and final-model control</h2>
          <p className="mt-1 text-sm text-gray-600">
            Every panel is tied to the selected trained artifact, governed holdout, and current dataset version.
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
                actionType: "workflow_setting_changed",
                subject: "Interpretation model under review",
                previousValue: selectedModel,
                newValue: e.target.value,
              });
              sessionStorage.setItem(LOCAL_SELECTED_INTERPRETATION_MODEL_KEY, e.target.value);
              setSelectedModel(e.target.value);
            }}
          >
            {models.map((model) => (
              <option key={model.key} value={model.key}>
                {displayModelName(model, model.key)}
              </option>
            ))}
          </select>
        </label>
      </div>

      {message && <div className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900">{message}</div>}

      {SHOW_LINEAR_REGRESSION_DEBUG && selectedModelIsLinearRegression && (
        <LinearRegressionDebugPanel details={details} />
      )}

      <section className="rounded-2xl border border-gray-200 bg-white p-4">
        <h2 className="text-sm font-semibold">Model-Specific Explanation</h2>
        {selectedModelIsKnn ? (
          <KnnClassifierInterpretation hyperparameters={hyperparameters} selectedName={displayModelName(selectedModelRow, selectedModel)} />
        ) : (
          <ModelDetails details={details} tree={treeStructure} forceRegression={selectedModelIsLinearRegression} />
        )}
      </section>

      <section className="rounded-2xl border border-gray-200 bg-white p-4">
        <h2 className="text-sm font-semibold">Final Hyperparameter Settings</h2>
        <HyperparameterTable rows={hyperparameters} />
      </section>

      {selectedModelIsRegression && (
        <section className="rounded-2xl border border-blue-200 bg-blue-50 p-4">
          <div className="text-xs font-semibold uppercase tracking-wide text-blue-700">Regression Interpretation Focus</div>
          <h2 className="mt-1 text-lg font-semibold text-slate-950">Use feature effects before projected surfaces</h2>
          <p className="mt-1 text-sm leading-6 text-slate-700">
            ATLAS prioritizes model behavior evidence that maps directly to features and predictions. Projected surfaces are kept as an advanced diagnostic because PCA or two-feature projections can make observations appear outside the visible response domain.
          </p>
          <div className="mt-4 grid gap-3 md:grid-cols-4">
            <FocusCard title="Top Drivers" text="Feature importance ranks variables by predictive contribution." />
            <FocusCard title="Direction" text="SHAP-style bars show whether a driver increases or decreases predictions." />
            <FocusCard title="Nonlinear Effects" text="PDP and sensitivity show whether response changes are linear or curved." />
            <FocusCard title="Reduced Set" text="RFE tests whether a smaller final feature set preserves holdout performance." />
          </div>
        </section>
      )}

      {!selectedModelIsRegression && <section className="rounded-2xl border border-gray-200 bg-white p-4">
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
      </section>}

      <div className="grid gap-6 lg:grid-cols-2">
        <section className="rounded-2xl border border-gray-200 bg-white p-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h2 className="text-sm font-semibold">Feature Importance</h2>
            <AnalysisScopeBadge loading={explanationLoading} meta={importanceMeta} />
          </div>
          <p className="mt-1 text-xs text-gray-500">
            {selectedModelIsRegression
              ? "Appropriate for regression: ranks variables by contribution to predictive accuracy."
              : "Ranks variables by contribution to model performance."}
          </p>
          {explanationErrors.importance ? <AnalysisError text={explanationErrors.importance} /> : <BarTable rows={importance} valueKey="importance" color="indigo" loading={explanationLoading} />}
        </section>
        <section className="rounded-2xl border border-gray-200 bg-white p-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h2 className="text-sm font-semibold">SHAP Summary</h2>
            <AnalysisScopeBadge loading={explanationLoading} meta={shapMeta} />
          </div>
          <p className="mt-1 text-xs text-gray-500">
            {selectedModelIsRegression
              ? "Appropriate for regression: estimates how each feature changes predicted target values on holdout records."
              : "Model-agnostic replacement impact on held-out predictions. This differs from native feature importance."}
          </p>
          {explanationErrors.shap ? <AnalysisError text={explanationErrors.shap} /> : <BarTable rows={shapRows} valueKey="importance" color="teal" loading={explanationLoading} />}
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
          <select className="rounded-md border px-3 py-2 text-sm disabled:bg-slate-100 disabled:text-slate-500" value={selectedFeature} disabled={!featureOptions.length || explanationLoading} onChange={(e) => setSelectedFeature(e.target.value)}>
            {!featureOptions.length ? <option value="">No explained feature available</option> : null}
            {featureOptions.map((feature) => (
              <option key={feature} value={feature}>{feature}</option>
            ))}
          </select>
        </div>
        {effectError ? <AnalysisError text={effectError} /> : null}
        <div className="mt-4 grid gap-4 lg:grid-cols-2">
          <LineChart title={selectedModelIsRegression ? "Partial Dependence: Predicted Target" : "Partial Dependence Plot"} rows={pdp} feature={selectedFeature} loading={effectLoading} />
          <SensitivityTable rows={sensitivity} loading={effectLoading} />
        </div>
      </section>

      {selectedModelIsRegression && (
        <details className="rounded-2xl border border-gray-200 bg-white p-4">
          <summary className="cursor-pointer text-sm font-semibold text-slate-900">
            Advanced: Projected Prediction Surface
          </summary>
          <p className="mt-2 text-xs leading-5 text-slate-500">
            Regression response surfaces can be useful for directional inspection, but they reduce the model to two features and should not be treated as the primary interpretation artifact. Use feature importance, SHAP-style summaries, PDP, sensitivity, and RFE first.
          </p>
          <div className="mt-4 flex flex-wrap gap-2">
            <select className="rounded-md border px-3 py-2 text-sm" value={boundaryX} onChange={(e) => setBoundaryX(e.target.value)}>
              {(boundary?.numeric_features ?? []).map((feature) => <option key={feature} value={feature}>{feature}</option>)}
            </select>
            <select className="rounded-md border px-3 py-2 text-sm" value={boundaryY} onChange={(e) => setBoundaryY(e.target.value)}>
              {(boundary?.numeric_features ?? []).filter((feature) => feature !== boundaryX).map((feature) => <option key={feature} value={feature}>{feature}</option>)}
            </select>
          </div>
          <DecisionBoundaryChart boundary={boundary} />
        </details>
      )}

      <section className="rounded-2xl border border-gray-200 bg-white p-4">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h2 className="text-sm font-semibold">Recursive Feature Elimination</h2>
            <p className="mt-1 text-xs text-gray-500">
              {rfeIsRegression
                ? "Runs backward elimination and recommends the smallest retained feature count that is effectively tied with the best holdout RMSE."
                : "Runs backward elimination and recommends the smallest retained feature count that is effectively tied with the best holdout AUC."}
            </p>
            <p className="mt-2 text-xs leading-5 text-slate-600">
              ATLAS uses a bounded {rfeIsRegression ? "linear" : "logistic"} surrogate for fast, reproducible elimination, then refits the selected estimator family on the retained features when you save the final model.
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
                Running RFE with timeout protection...
              </div>
            )}
            <button
              className="rounded-md bg-indigo-600 px-3 py-2 text-sm font-medium text-white transition hover:bg-indigo-700 active:scale-95 disabled:cursor-not-allowed disabled:bg-indigo-300 disabled:active:scale-100"
              disabled={!canRunRfe}
              onClick={runRfe}
              title={canRunRfe ? "Run recursive feature elimination for the governed training split." : rfeUnsupportedMessage || "Select a supported supervised model before running RFE."}
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
        {rfeUnsupportedMessage && !rfeRunning && (
          <div className="mt-3 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs leading-5 text-amber-900">
            {rfeUnsupportedMessage}
          </div>
        )}
        {!canRunRfe && !rfeRunning && !rfeRows.length && (
          <div className="mt-3 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs leading-5 text-amber-900">
            {rfeUnsupportedMessage
              ? "Select another model to run RFE, or use KNN diagnostics without recursive elimination."
              : "RFE requires a selected supervised candidate and a current governed training split."}
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
              Save the RFE-selected final model first, then export a governed deployment manifest and metadata.
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <button
              className="rounded-md bg-indigo-600 px-3 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:cursor-not-allowed disabled:bg-indigo-300"
              disabled={!finalModelReady}
              onClick={() => exportModel("json")}
              title={finalModelReady ? "Download final model package" : "Save as Final Model first"}
            >
              Download Final Manifest
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

    </div>
    </StepShell>
  );
}

function FocusCard({ title, text }: { title: string; text: string }) {
  return (
    <div className="rounded-xl border border-blue-100 bg-white p-3">
      <div className="text-sm font-semibold text-slate-900">{title}</div>
      <p className="mt-1 text-xs leading-5 text-slate-600">{text}</p>
    </div>
  );
}

function ModelDetails({ details, tree, forceRegression = false }: { details: DetailResponse | null; tree: TreeResponse | null; forceRegression?: boolean }) {
  if (!details) return <div className="mt-3 text-sm text-gray-500">Loading model details...</div>;
  if (!details.ok) return <div className="mt-3 text-sm text-rose-700">{details.error}</div>;
  if (details.kind === "equation" && (details.model_type === "regression" || forceRegression)) {
    return (
      <div className="mt-3 space-y-4">
        <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
          <div className="flex flex-col gap-3 border-b border-slate-100 pb-4 lg:flex-row lg:items-start lg:justify-between">
            <div>
              <div className="text-xs font-semibold uppercase tracking-wide text-blue-700">Linear Regression Statistical Output</div>
              <h3 className="mt-1 text-lg font-semibold text-slate-950">OLS-style coefficient inference</h3>
              <p className="mt-1 max-w-3xl text-sm leading-6 text-slate-600">
                Standard regression output for the fitted Linear Regression pipeline. Inference is computed from the transformed design matrix used by the trained model.
              </p>
            </div>
            <span className={`rounded-full px-3 py-1 text-xs font-semibold ${details.inference_available ? "bg-emerald-100 text-emerald-700" : "bg-amber-100 text-amber-800"}`}>
              {details.inference_available ? "Inference available" : "Inference limited"}
            </span>
          </div>
          <LinearRegressionEquation intercept={details.intercept} rows={details.coefficients ?? []} />
          <LinearModelFitSummaryCard fit={details.model_fit} />
          <CoefficientTable rows={details.coefficients ?? []} isRegression />
          {!details.inference_available && (
            <div className="mt-3 rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">
              {details.inference_message ?? "Statistical inference unavailable for this fitted pipeline."}
            </div>
          )}
          <LinearRegressionInterpretationReadout rows={details.coefficients ?? []} />
        </section>
        <BarTable rows={(details.coefficients ?? []).map((row) => ({ feature: row.feature, importance: row.coefficient, source: "coefficient" }))} valueKey="importance" color="indigo" />
      </div>
    );
  }
  if (details.kind === "equation") {
    return (
      <div className="mt-3 space-y-4">
        <div className="rounded-xl border border-indigo-100 bg-indigo-50 p-4">
          <div className="text-xs font-semibold uppercase tracking-wide text-indigo-700">Logistic Regression Coefficients</div>
          <h3 className="mt-1 text-base font-semibold text-slate-950">Odds ratios and log-odds direction</h3>
          <p className="mt-1 text-sm leading-6 text-slate-700">
            Logistic Regression estimates how each feature changes the log-odds of the positive class. Odds ratios above 1 increase event odds; below 1 reduce event odds, holding other features constant.
          </p>
          <div className="mt-3 rounded-lg bg-white p-3 font-mono text-xs">logit(p) = {details.intercept?.toFixed(4)} + sum(coef x feature)</div>
        </div>
        <CoefficientTable rows={details.coefficients ?? []} isRegression={false} />
        <BarTable rows={(details.coefficients ?? []).map((row) => ({ feature: row.feature, importance: row.coefficient, source: row.odds_ratio ? `OR ${row.odds_ratio.toFixed(3)}` : "coefficient" }))} valueKey="importance" color="indigo" />
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

function KnnClassifierInterpretation({ hyperparameters, selectedName }: { hyperparameters: HyperparameterRow[]; selectedName: string }) {
  const getParam = (patterns: RegExp[]) =>
    hyperparameters.find((row) => patterns.some((pattern) => pattern.test(`${row.parameter} ${row.value}`)))?.value;
  const kValue = getParam([/n_neighbors/i, /^k$/i, /\bk\b/i]) ?? "k not available";
  const metric = getParam([/metric/i, /distance/i]) ?? "distance metric not available";
  const weights = getParam([/weight/i]) ?? "weights not available";
  return (
    <div className="mt-3 space-y-4">
      <section className="rounded-2xl border border-blue-200 bg-blue-50 p-4">
        <div className="text-xs font-semibold uppercase tracking-wide text-blue-700">KNN Model Interpretation</div>
        <h3 className="mt-1 text-lg font-semibold text-slate-950">{selectedName || "KNN Classifier"}</h3>
        <p className="mt-1 text-sm leading-6 text-slate-700">
          K-Nearest Neighbors classifies each record from the labels of nearby records in feature space. Interpretation should focus on preprocessing, distance behavior, class balance, and local neighbor evidence rather than global coefficients.
        </p>
        <div className="mt-4 grid gap-3 md:grid-cols-3">
          <FocusCard title="k value" text={kValue} />
          <FocusCard title="Distance metric" text={metric} />
          <FocusCard title="Neighbor weights" text={weights} />
        </div>
      </section>
      <section className="rounded-2xl border border-slate-200 bg-white p-4">
        <h3 className="text-sm font-semibold text-slate-900">Classifier-Specific Guidance</h3>
        <div className="mt-3 grid gap-3 md:grid-cols-2">
          <FocusCard title="Feature scaling dependency" text="KNN is distance based. Standardization or comparable feature scales are usually required before relying on the classifier." />
          <FocusCard title="Nearest-neighbor caveats" text="Local neighborhoods can be unstable in sparse, high-dimensional, or imbalanced data. Review recall, PR-AUC, lift, and calibration." />
          <FocusCard title="Classification performance" text="Use holdout classification metrics and threshold analysis. Accuracy alone is not sufficient for rare-event targets." />
          <FocusCard title="Local explanation guidance" text="Explain individual predictions by showing the nearest neighbor mix, distances, and observed class labels when available." />
        </div>
      </section>
    </div>
  );
}

function LinearRegressionDebugPanel({ details }: { details: DetailResponse | null }) {
  const debug = details?.debug ?? {};
  const rows = [
    ["Selected model key", debug.selected_model_key],
    ["Returned model key", debug.returned_model_key],
    ["Requested problem type", debug.requested_problem_type],
    ["Returned problem type", debug.returned_problem_type],
    ["Requested target", debug.requested_target],
    ["Returned target", debug.returned_target],
    ["Requested dataset version", debug.requested_dataset_version],
    ["Returned dataset version", debug.returned_dataset_version],
    ["Training run ID", debug.training_run_id],
    ["Inference available", details?.inference_available ? "Yes" : "No"],
    ["Inference reason", details?.inference_message || details?.error],
  ];
  return (
    <details className="rounded-2xl border border-slate-200 bg-slate-50 p-4">
      <summary className="cursor-pointer text-sm font-semibold text-slate-900">Linear Regression Debug</summary>
      <div className="mt-3 grid gap-2 md:grid-cols-2">
        {rows.map(([label, value]) => (
          <div key={label} className="rounded-lg border border-slate-200 bg-white px-3 py-2">
            <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">{label}</div>
            <div className="mt-1 break-all font-mono text-xs text-slate-800">{String(value ?? "Not returned")}</div>
          </div>
        ))}
      </div>
    </details>
  );
}

function CoefficientTable({ rows, isRegression }: { rows: RegressionCoefficientRow[]; isRegression: boolean }) {
  const topRows = rows.slice(0, 12);
  if (!topRows.length) {
    return <div className="rounded-xl border border-slate-200 bg-white p-4 text-sm text-slate-500">No coefficient details are available.</div>;
  }
  return (
    <div className="overflow-x-auto rounded-xl border border-slate-200 bg-white">
      <div className="border-b border-slate-200 bg-slate-50 px-4 py-3">
        <h3 className="text-sm font-semibold text-slate-900">{isRegression ? "Coefficient Inference Table" : "Coefficient / Odds Ratio Table"}</h3>
        <p className="mt-1 text-xs text-slate-500">
          {isRegression ? "Largest absolute coefficients from the fitted linear model." : "Largest absolute log-odds coefficients from the fitted classifier."}
        </p>
      </div>
      <table className={`${isRegression ? "min-w-[1120px]" : ""} w-full text-sm`}>
        <thead className="bg-white text-left text-xs uppercase tracking-wide text-slate-500">
          <tr>
            <th className="px-4 py-2">{isRegression ? "Variable" : "Feature"}</th>
            <th className="px-4 py-2">Coefficient</th>
            {isRegression && <th className="px-4 py-2">Std Error</th>}
            {isRegression && <th className="px-4 py-2">t Value</th>}
            {isRegression && <th className="px-4 py-2">p Value</th>}
            {isRegression && <th className="px-4 py-2">95% CI Lower</th>}
            {isRegression && <th className="px-4 py-2">95% CI Upper</th>}
            {isRegression && <th className="px-4 py-2">Standardized Weight</th>}
            <th className="px-4 py-2">Direction</th>
            {isRegression && <th className="px-4 py-2">Rank</th>}
            {!isRegression && <th className="px-4 py-2">Odds Ratio</th>}
          </tr>
        </thead>
        <tbody>
          {topRows.map((row) => (
            <tr key={row.feature} className="border-t border-slate-100 odd:bg-slate-50/50">
              <td className="px-4 py-2 font-medium text-slate-800">{row.variable ?? row.feature}</td>
              <td className="px-4 py-2 font-mono text-slate-700">{row.coefficient.toFixed(5)}</td>
              {isRegression && <td className="px-4 py-2 font-mono text-slate-700">{formatOptional(row.standard_error, 5)}</td>}
              {isRegression && <td className="px-4 py-2 font-mono text-slate-700">{formatOptional(row.t_statistic, 3)}</td>}
              {isRegression && <td className="px-4 py-2 font-mono text-slate-700">{formatPValue(row.p_value)}</td>}
              {isRegression && <td className="px-4 py-2 font-mono text-slate-700">{formatOptional(row.confidence_interval_lower ?? row.ci_lower, 5)}</td>}
              {isRegression && <td className="px-4 py-2 font-mono text-slate-700">{formatOptional(row.confidence_interval_upper ?? row.ci_upper, 5)}</td>}
              {isRegression && <td className="px-4 py-2 font-mono text-slate-700">{formatOptional(row.standardized_weight ?? row.standardized_coefficient, 5)}</td>}
              <td className={`px-4 py-2 font-semibold ${row.coefficient >= 0 ? "text-emerald-700" : "text-rose-700"}`}>
                {row.coefficient >= 0 ? "Positive" : "Negative"}
              </td>
              {isRegression && <td className="px-4 py-2 font-mono text-slate-700">{row.absolute_rank ?? "-"}</td>}
              {!isRegression && <td className="px-4 py-2 font-mono text-slate-700">{row.odds_ratio ? row.odds_ratio.toFixed(4) : "-"}</td>}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function LinearRegressionEquation({ intercept, rows }: { intercept?: number; rows: RegressionCoefficientRow[] }) {
  const topTerms = rows.slice(0, 6);
  const allTerms = rows;
  const termText = (row: RegressionCoefficientRow) => `${row.coefficient >= 0 ? "+" : "-"} ${Math.abs(row.coefficient).toFixed(5)}*${row.feature}`;
  return (
    <div className="mt-4 rounded-xl border border-indigo-100 bg-indigo-50 p-4">
      <div className="text-xs font-semibold uppercase tracking-wide text-indigo-700">Regression Equation</div>
      <div className="mt-2 rounded-lg bg-white p-3 font-mono text-xs leading-5 text-slate-800">
        y_hat = {formatOptional(intercept, 5)} {topTerms.map(termText).join(" ")}
        {allTerms.length > topTerms.length ? " + ..." : ""}
      </div>
      {allTerms.length > topTerms.length && (
        <details className="mt-2 rounded-lg border border-indigo-100 bg-white p-3">
          <summary className="cursor-pointer text-xs font-semibold text-indigo-700">Show full fitted equation</summary>
          <div className="mt-2 max-h-40 overflow-auto font-mono text-xs leading-5 text-slate-700">
            y_hat = {formatOptional(intercept, 5)} {allTerms.map(termText).join(" ")}
          </div>
        </details>
      )}
    </div>
  );
}

function LinearModelFitSummaryCard({ fit }: { fit?: LinearModelFitSummary }) {
  const rows = [
    ["Dependent variable", fit?.dependent_variable || "Not available"],
    ["Model type", fit?.model_type || "Linear Regression"],
    ["Number of observations", fit?.n_observations?.toLocaleString() ?? "Not available"],
    ["Number of predictors", fit?.n_predictors?.toLocaleString() ?? "Not available"],
    ["Degrees of freedom residual", fit?.residual_df?.toLocaleString() ?? "Not available"],
    ["R-squared", formatAvailable(fit?.r2, 4)],
    ["Adjusted R-squared", formatAvailable(fit?.adjusted_r2, 4)],
    ["RMSE", formatAvailable(fit?.rmse, 4)],
    ["MAE", formatAvailable(fit?.mae, 4)],
    ["MSE", formatAvailable(fit?.mse, 4)],
    ["Residual Std. Error", formatAvailable(fit?.residual_standard_error, 4)],
    ["F-statistic", formatAvailable(fit?.f_statistic, 4)],
    ["Prob(F-statistic)", formatPValue(fit?.prob_f_statistic, "Not available")],
    ["AIC", formatAvailable(fit?.aic, 4)],
    ["BIC", formatAvailable(fit?.bic, 4)],
    ["Log-likelihood", formatAvailable(fit?.log_likelihood, 4)],
    ["Condition number", formatAvailable(fit?.condition_number, 4)],
  ];
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4">
      <h3 className="text-sm font-semibold text-slate-900">Model Fit Summary</h3>
      <div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
        {rows.map(([label, value]) => (
          <div key={label} className="rounded-lg border border-slate-100 bg-slate-50 px-3 py-2">
            <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">{label}</div>
            <div className="mt-1 font-mono text-sm font-semibold text-slate-900">{value}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

function LinearRegressionInterpretationReadout({ rows }: { rows: RegressionCoefficientRow[] }) {
  const strongest = rows.find((row) => Number.isFinite(row.coefficient));
  if (!strongest) return null;
  return (
    <div className="rounded-xl border border-emerald-200 bg-emerald-50 p-4 text-sm leading-6 text-emerald-950">
      <div className="font-semibold">Diagnostic Notes</div>
      <p className="mt-1">
        ATLAS readout: Review coefficient signs, p-values, confidence intervals, and standardized weights to understand which variables materially contribute to the fitted linear regression model. P-values are statistical inference estimates for the fitted design matrix and should be interpreted with model assumptions in mind.
      </p>
      <p className="mt-1">
        {strongest.feature} has a {strongest.coefficient >= 0 ? "positive" : "negative"} coefficient, meaning predicted target values {strongest.coefficient >= 0 ? "increase" : "decrease"} as {strongest.feature} increases, holding other transformed features constant. Review p-values and confidence intervals to determine which coefficients are statistically reliable.
      </p>
    </div>
  );
}

function formatOptional(value: number | null | undefined, digits = 4) {
  return typeof value === "number" && Number.isFinite(value) ? value.toFixed(digits) : "-";
}

function formatAvailable(value: number | null | undefined, digits = 4) {
  return typeof value === "number" && Number.isFinite(value) ? value.toFixed(digits) : "Not available";
}

function formatPValue(value: number | null | undefined, fallback = "-") {
  if (typeof value !== "number" || !Number.isFinite(value)) return fallback;
  return value < 0.0001 ? "<0.0001" : value.toFixed(4);
}

function DecisionTreeExplanation({ tree }: { tree: TreeResponse }) {
  const nodes = tree.nodes ?? [];
  const edges = tree.edges ?? [];
  const isRegressionTree = tree.model_type === "regression" || nodes.some((node) => node.model_type === "regression");
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
        <MetricTile label={isRegressionTree ? "Root Prediction" : "Root Event Rate"} value={isRegressionTree ? formatNumber(root?.prediction_value, 4) : `${((root?.positive_rate ?? 0) * 100).toFixed(1)}%`} tone="amber" />
      </div>
      <DecisionTreeSvg nodes={nodes} edges={edges} />
      <div className="rounded-xl border border-slate-200 bg-white p-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <h3 className="text-sm font-semibold text-slate-900">Terminal Decision Rules</h3>
            <p className="mt-1 text-xs text-slate-500">{isRegressionTree ? "Largest terminal segments from the fitted regressor, sorted by sample count." : "Largest terminal segments from the fitted tree, sorted by sample count."}</p>
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
                <div className={`rounded-full px-2.5 py-1 text-xs font-semibold ${isRegressionTree ? "bg-indigo-100 text-indigo-700" : rule.positiveRate >= 0.5 ? "bg-rose-100 text-rose-700" : "bg-blue-100 text-blue-700"}`}>
                  {isRegressionTree ? `Prediction ${formatNumber(rule.predictionValue, 4)}` : `${(rule.positiveRate * 100).toFixed(1)}% event rate`}
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
  const isRegressionTree = nodes.some((node) => node.model_type === "regression");
  const predictionValues = nodes.map((node) => node.prediction_value).filter((value): value is number => typeof value === "number" && Number.isFinite(value));
  const minPrediction = predictionValues.length ? Math.min(...predictionValues) : 0;
  const maxPrediction = predictionValues.length ? Math.max(...predictionValues) : 1;
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
          <p className="mt-1 text-xs text-slate-500">
            {isRegressionTree ? "Node color deepens as predicted target values increase." : "Blue nodes are lower event-rate segments; amber/red nodes are higher event-rate segments."}
          </p>
        </div>
        <div className="flex flex-wrap gap-2 text-[11px] font-medium">
          <span className="rounded-full bg-blue-100 px-2 py-1 text-blue-700">{isRegressionTree ? "Lower prediction" : "Low rate"}</span>
          <span className="rounded-full bg-amber-100 px-2 py-1 text-amber-700">Middle</span>
          <span className="rounded-full bg-rose-100 px-2 py-1 text-rose-700">{isRegressionTree ? "Higher prediction" : "High rate"}</span>
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
          const normalizedPrediction = (typeof node.prediction_value === "number" && Number.isFinite(node.prediction_value))
            ? (node.prediction_value - minPrediction) / (maxPrediction - minPrediction || 1)
            : node.positive_rate;
          return (
            <g key={node.id}>
              <rect x={nx} y={ny} width={nodeW} height={nodeH} rx={12} fill={fillForRate(normalizedPrediction)} stroke={strokeForRate(normalizedPrediction)} strokeWidth={1.4} />
              <text x={nx + 12} y={ny + 19} className="fill-slate-900 text-[11px] font-semibold">
                {node.leaf ? `Leaf: ${truncateTreeLabel(node.prediction, 17)}` : truncateTreeLabel(`${node.feature} <= ${formatThreshold(node.threshold)}`, 23)}
              </text>
              <text x={nx + 12} y={ny + 40} className="fill-slate-700 text-[10px]">
                {isRegressionTree ? `Pred ${formatNumber(node.prediction_value, 4)}` : `Event rate ${(node.positive_rate * 100).toFixed(1)}%`}
              </text>
              <text x={nx + 12} y={ny + 56} className="fill-slate-600 text-[10px]">
                Samples {node.samples.toLocaleString()}
              </text>
              <rect x={nx + 12} y={ny + 64} width={nodeW - 24} height={5} rx={2.5} fill="#e2e8f0" />
              <rect x={nx + 12} y={ny + 64} width={(nodeW - 24) * Math.min(1, Math.max(0, normalizedPrediction))} height={5} rx={2.5} fill={normalizedPrediction >= 0.5 ? "#e11d48" : "#2563eb"} opacity={0.85} />
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
  const rules: { id: number; prediction: string; predictionValue?: number; positiveRate: number; samples: number; conditions: string[] }[] = [];

  function walk(node: TreeNode, conditions: string[]) {
    const outgoing = childEdges.get(node.id) ?? [];
    if (node.leaf || !outgoing.length) {
      rules.push({
        id: node.id,
        prediction: node.prediction,
        predictionValue: node.prediction_value,
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

function AnalysisScopeBadge({ loading, meta }: { loading: boolean; meta: AnalysisMeta }) {
  const label = loading
    ? "Computing holdout evidence"
    : meta.method
      ? `${meta.method}${meta.sampleCount ? ` | ${meta.sampleCount.toLocaleString()} rows` : ""}`
      : "Governed holdout";
  return <span className={`rounded-full border px-2.5 py-1 text-[10px] font-semibold uppercase tracking-wide ${loading ? "border-blue-200 bg-blue-50 text-blue-700" : "border-slate-200 bg-slate-50 text-slate-600"}`}>{label}</span>;
}

function AnalysisError({ text }: { text: string }) {
  return <div className="mt-3 rounded-xl border border-amber-200 bg-amber-50 px-3 py-3 text-xs leading-5 text-amber-950">{text}</div>;
}

function BarTable({ rows, valueKey, color = "indigo", loading = false }: { rows: ImportanceRow[]; valueKey: "importance"; color?: "indigo" | "teal"; loading?: boolean }) {
  if (loading) {
    return <div className="mt-4 space-y-3" aria-label="Loading explanation evidence">{Array.from({ length: 7 }, (_, index) => <div key={index} className="grid animate-pulse grid-cols-[140px_1fr_60px] items-center gap-3"><span className="h-3 rounded bg-slate-200" /><span className="h-2 rounded bg-slate-100" /><span className="h-3 rounded bg-slate-100" /></div>)}</div>;
  }
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
      {!top.length && <div className="rounded-xl border border-slate-200 bg-slate-50 px-3 py-4 text-sm text-gray-500">No importance rows were returned for this trained artifact. Retrain the selected supervised model if its estimator does not expose compatible explanation evidence.</div>}
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

function LineChart({ title, rows, feature, loading = false }: { title: string; rows: CurveRow[]; feature: string; loading?: boolean }) {
  if (loading) return <div className="flex h-[260px] animate-pulse items-center justify-center rounded-xl bg-slate-100 text-sm font-medium text-slate-500">Computing partial dependence on the governed holdout...</div>;
  if (!rows.length) return <div className="flex h-[260px] items-center justify-center rounded-xl border border-slate-200 bg-slate-50 px-6 text-center text-sm text-gray-500">Select a compatible explained feature to generate partial dependence.</div>;
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

function SensitivityTable({ rows, loading = false }: { rows: SensitivityRow[]; loading?: boolean }) {
  if (loading) return <div className="flex h-[260px] animate-pulse items-center justify-center rounded-xl bg-slate-100 text-sm font-medium text-slate-500">Computing scenario sensitivity...</div>;
  if (!rows.length) return <div className="flex h-[260px] items-center justify-center rounded-xl border border-slate-200 bg-slate-50 px-6 text-center text-sm text-gray-500">Sensitivity scenarios will appear after a compatible feature is selected.</div>;
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
            <th className="py-2 pr-4">Negative Scenario Prediction</th>
            <th className="py-2 pr-4">Positive Scenario Prediction</th>
            <th className="py-2 pr-4">Baseline Prediction</th>
            <th className="py-2 pr-4">Largest Scenario</th>
            <th className="py-2 pr-4">Delta</th>
            <th className="py-2 pr-4">Direction</th>
            <th className="py-2">Relative Impact</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const delta = row.delta ?? row.worst_delta;
            return (
              <tr key={row.feature} className="border-t align-top">
                <td className="py-2 pr-4 font-medium text-gray-800">
                  {row.feature}
                  {row.special_value_note && <div className="mt-1 max-w-xs text-[11px] font-normal leading-4 text-amber-700">{row.special_value_note}</div>}
                </td>
                <td className="py-2 pr-4">{row.negative_scenario_prediction == null ? "-" : row.negative_scenario_prediction.toFixed(4)}</td>
                <td className="py-2 pr-4">{row.positive_scenario_prediction == null ? "-" : row.positive_scenario_prediction.toFixed(4)}</td>
                <td className="py-2 pr-4">{(row.baseline_prediction ?? row.baseline).toFixed(4)}</td>
                <td className="py-2 pr-4">{row.largest_scenario ?? row.worst_scenario}</td>
                <td className={`py-2 pr-4 ${delta >= 0 ? "text-emerald-700" : "text-rose-700"}`}>
                  {delta.toFixed(4)}
                </td>
                <td className="max-w-xs py-2 pr-4 text-xs leading-5 text-slate-700">
                  {row.direction_explanation || (delta >= 0 ? "Increasing this feature increases predicted bad risk." : "Increasing this feature decreases predicted bad risk.")}
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
            );
          })}
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
