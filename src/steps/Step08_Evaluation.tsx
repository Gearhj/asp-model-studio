import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  Activity,
  ArrowRight,
  BarChart3,
  BrainCircuit,
  Check,
  GitCompareArrows,
  LineChart,
  RefreshCw,
  Scale,
  ShieldCheck,
  Target,
  Trash2,
  TrendingUp,
} from "lucide-react";
import StepShell from "../components/StepShell";
import { type AtlasWorkflowMetric } from "../components/ui/AtlasWorkflow";
import { logDecision } from "../lib/decisionJournal";
import VisualAnalysisPanel from "../visual-intelligence/production/VisualAnalysisPanel";
import ClassificationDecisionExplorer from "../visual-intelligence/prototypes/ClassificationDecisionExplorer";
import RegressionDiagnosticExplorer from "../visual-intelligence/prototypes/RegressionDiagnosticExplorer";
import { inferLocalProblemType, loadLocalDataset } from "../lib/localDataset";
import { requireLocalDatasetCanonicalIdentity, type CanonicalDatasetIdentity } from "../lib/datasetIdentity";
import {
  candidateMatchesDataset,
  candidateRequestParams,
  loadInterpretationCandidates,
  requireInterpretationCandidate,
  saveInterpretationCandidates,
  type InterpretationCandidate,
} from "../lib/interpretationCandidates";
import {
  formatSelectionSource,
  lockedDecisionMatchesCandidate,
  parseLockedSelectionDecision,
  rankVerifiedSelectionCandidates,
  resolvePromotionReadiness,
  selectionMetricLabel,
  verifiedSelectionMetric,
  type GovernedEvaluationPackage,
  type LockedSelectionDecision,
  type SelectionMetricEvidence,
} from "../lib/selectionProvenance";
import { useWorkflowStore } from "../state/useWorkflowStore";
import { projectWorkflowRoute } from "../lib/projectScopedRoutes";

const QUERY_API_BASE =
  typeof window !== "undefined" ? new URLSearchParams(window.location.search).get("apiBase")?.replace(/\/$/, "") : undefined;
const API_BASE =
  QUERY_API_BASE ||
  (import.meta.env.VITE_API_BASE as string | undefined)?.replace(/\/$/, "") ||
  "http://127.0.0.1:8001/api";

type Task = "classification" | "regression" | "anomaly";
type RankedRow = {
  key: string;
  name: string;
  candidate_id?: string;
  training_job_id?: string;
  training_run_id?: string;
  project_id?: string;
  dataset_id?: string;
  dataset_version_id?: string;
  target?: string;
  feature_manifest_version?: string;
  validation_design_id?: string;
  validation_design_version?: string;
  split_id?: string;
  candidate_contract?: Record<string, unknown>;
  task?: Task;
  kind?: string;
  champion_eligible?: boolean;
  auc?: number;
  pr_auc?: number;
  accuracy?: number;
  precision?: number;
  recall?: number;
  f1?: number;
  ks?: number;
  gini?: number;
  mae?: number;
  mse?: number;
  rmse?: number;
  r2?: number;
  adjusted_r2?: number;
  runtime_ms?: number;
  search_runtime_ms?: number;
  calibration_applied?: boolean;
  calibration_method?: string;
  best_score?: number;
  best_params?: Record<string, unknown>;
  selection_metric?: SelectionMetricEvidence | Record<string, unknown> | null;
  selection_integrity_status?: string;
  holdout_isolation_status?: string;
};

type Curves = {
  ok: boolean;
  task?: "classification" | "regression";
  error?: string;
  metrics?: Record<string, number | null | undefined>;
  roc?: { fpr: number[]; tpr: number[] };
  pr?: { precision: number[]; recall: number[] };
  confusion?: number[][];
  residuals?: { points?: Array<{ actual: number; predicted: number; residual: number }> };
};

type ThresholdMetrics = {
  threshold: number;
  predicted_positives: number;
  review_volume: number;
  precision: number;
  recall: number;
  false_positives: number;
  false_negatives: number;
  true_positives: number;
  true_negatives: number;
  fraud_capture: number;
  false_positive_rate: number;
  f1: number;
  expected_alert_rate: number;
  confusion: number[][];
};

type DecileRow = {
  decile: number;
  n: number;
  positives: number;
  event_rate: number;
  lift: number;
  cumulative_positives: number;
  capture_rate: number;
  population_rate: number;
  min_score: number;
  max_score: number;
  mean_score: number;
};

type CommandCenter = {
  ok: boolean;
  error?: string;
  evaluation_package_id?: string;
  evaluation_package?: GovernedEvaluationPackage;
  candidate_id?: string;
  training_run_id?: string;
  project_id?: string;
  dataset_id?: string;
  dataset_version_id?: string;
  evaluation_role?: string;
  test_status?: string;
  oot_status?: string;
  observation_count?: number;
  event_count?: number;
  event_rate?: number;
  final_holdout_role?: "reporting_only";
  candidate_decision_id?: string;
  selection_integrity_status?: string;
  isolation_status?: string;
  holdout_isolation_status?: string;
  package_integrity_status?: string;
  final_holdout_status?: string;
  first_opened_at?: string;
  selection_evidence?: Record<string, unknown>;
  selection_evidence_json?: Record<string, unknown>;
  final_holdout_evidence?: Record<string, unknown>;
  final_holdout_evidence_json?: Record<string, unknown>;
  holdout_exposure?: Record<string, unknown>;
  holdout_exposure_status?: string;
  threshold?: ThresholdMetrics;
  presets?: Record<string, number>;
  threshold_policy?: {
    active_threshold: number;
    active_source: string;
    governed_threshold: number;
    governed_source: string;
    final_holdout_role: "reporting_only";
    recommendations_derived_from_final_holdout: false;
  };
  lift?: {
    base_rate: number;
    deciles: DecileRow[];
    top_capture: Record<string, { rows: number; events: number; capture_rate: number; lift: number }>;
  };
  calibration?: {
    rows: Array<{ predicted: number; observed: number; n: number }>;
    brier_score: number;
    slope: number | null;
    intercept: number | null;
    method: string;
    prevalence_correction: string;
  };
  stability?: {
    internal_validation_status: string;
    internal_validation_score?: number | null;
    test_metrics?: Record<string, number | null | undefined>;
    oot_metrics?: Record<string, number | null | undefined> | null;
  };
};

type TreeNode = {
  id: number;
  depth: number;
  x: number;
  leaf: boolean;
  feature?: string;
  threshold?: number | null;
  samples: number;
  positive_rate: number;
  prediction: string;
};
type TreeResponse = { ok: boolean; nodes?: TreeNode[]; edges?: Array<{ source: number; target: number; label: string }>; error?: string };
type KnnResponse = {
  ok: boolean;
  error?: string;
  points?: Array<{ x: number; y: number; class: number; prediction: number }>;
  grid?: Array<{ x: number; y: number; prediction: number; region?: number }>;
  x_domain?: [number, number];
  y_domain?: [number, number];
  neighbor_count?: number;
  sample_size?: number;
};
type ImportanceResponse = {
  ok: boolean;
  error?: string;
  evaluation_package_id?: string;
  method?: string;
  sample_count?: number;
  rows?: Array<{ feature: string; importance: number; direction?: number; source?: string }>;
};
type DetailResponse = {
  ok: boolean;
  error?: string;
  evaluation_package_id?: string;
  kind?: string;
  intercept?: number;
  coefficients?: Array<{ feature: string; coefficient: number; odds_ratio?: number | null }>;
  message?: string;
};
type HyperparameterResponse = { ok: boolean; evaluation_package_id?: string; rows?: Array<{ parameter: string; value: string }>; best_score?: number | null };

async function getJson<T>(url: string): Promise<T> {
  const response = await fetch(url, { credentials: "include" });
  const text = await response.text();
  let payload: any = null;
  try {
    payload = text ? JSON.parse(text) : null;
  } catch {
    payload = { ok: false, error: text || `Request failed (${response.status})` };
  }
  if (!response.ok) throw new Error(payload?.error || payload?.detail || `Request failed (${response.status})`);
  return payload as T;
}

function candidateFromRow(model: RankedRow): InterpretationCandidate {
  const frozen = model.candidate_contract ?? {};
  const frozenText = (key: string) => (typeof frozen[key] === "string" ? frozen[key] as string : undefined);
  return requireInterpretationCandidate({
    ...frozen,
    ...model,
    target: model.target ?? frozenText("target") ?? frozenText("target_name"),
    feature_manifest_version:
      model.feature_manifest_version ?? frozenText("feature_manifest_version") ?? frozenText("feature_manifest_hash"),
    validation_design_version:
      model.validation_design_version ?? frozenText("validation_design_version"),
    key: model.key,
    name: model.name,
    task: model.task ?? frozenText("problem_type") as Task | undefined,
    selectedAt: new Date().toISOString(),
  });
}

function exactCandidateRows(rows: RankedRow[], identity: CanonicalDatasetIdentity): RankedRow[] {
  return rows.filter((row) => {
    try {
      return candidateMatchesDataset(candidateFromRow(row), identity);
    } catch {
      return false;
    }
  });
}

function formatMetric(value?: number | null, digits = 4) {
  return typeof value === "number" && Number.isFinite(value) ? value.toFixed(digits) : "Not available";
}

function formatPercent(value?: number | null) {
  return typeof value === "number" && Number.isFinite(value) ? `${(value * 100).toFixed(1)}%` : "Not available";
}

function formatThresholdSource(value?: string) {
  const labels: Record<string, string> = {
    platform_governed_default: "Platform governed default",
    frozen_validation: "Frozen validation policy",
    frozen_cross_validation: "Frozen cross-validation policy",
    frozen_governed: "Frozen governance policy",
    frozen_user_deployment: "Frozen user-selected deployment policy",
    user_supplied_reporting_value: "User-supplied deployment value (reporting only)",
  };
  return labels[String(value ?? "")] ?? "Governed candidate contract";
}

function cleanModelName(name: string) {
  return name.replace(/\s*\(k\s*=\s*\d+\)/i, "");
}

function isAnomaly(model: RankedRow) {
  return model.task === "anomaly" || model.kind === "anomaly" || model.champion_eligible === false;
}

function modelFamily(model: RankedRow | null) {
  const value = `${model?.key ?? ""} ${model?.name ?? ""}`.toLowerCase();
  if (/decision.?tree/.test(value)) return "Decision Tree";
  if (/random.?forest|extra.?trees/.test(value)) return "Tree Ensemble";
  if (/xgboost|lightgbm|catboost|histogram.?gradient|boosting/.test(value)) return "Gradient Boosting";
  if (/knn|nearest/.test(value)) return "K-Nearest Neighbors";
  if (/svm|support.?vector/.test(value)) return "Support Vector Machine";
  if (/naive.?bayes|gaussian.?nb/.test(value)) return "Gaussian Naive Bayes";
  if (/neural|mlp/.test(value)) return "Neural Network";
  if (/logistic|sgd/.test(value)) return "Linear Classifier";
  if (/anomaly|isolation|outlier|covariance|one.?class/.test(value)) return "Anomaly Diagnostic";
  return "Supervised Estimator";
}

function interpretability(model: RankedRow) {
  const family = modelFamily(model);
  if (["Decision Tree", "Linear Classifier", "Gaussian Naive Bayes"].includes(family)) return "High";
  if (["K-Nearest Neighbors", "Support Vector Machine", "Tree Ensemble"].includes(family)) return "Medium";
  return "Low";
}

function objectValue(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null;
}

function normalizeEvaluationPackage(command: CommandCenter | null): GovernedEvaluationPackage | null {
  if (!command) return null;
  const nested = objectValue(command.evaluation_package) ?? {};
  return {
    ...command,
    ...nested,
    evaluation_package_id:
      nested.evaluation_package_id ?? command.evaluation_package_id,
    candidate_id: nested.candidate_id ?? command.candidate_id,
    training_run_id: nested.training_run_id ?? command.training_run_id,
    candidate_decision_id:
      nested.candidate_decision_id ?? command.candidate_decision_id,
    selection_integrity_status:
      nested.selection_integrity_status ?? command.selection_integrity_status,
    isolation_status:
      nested.isolation_status ??
      nested.holdout_isolation_status ??
      command.isolation_status ??
      command.holdout_isolation_status,
    selection_evidence:
      nested.selection_evidence ??
      nested.selection_evidence_json ??
      command.selection_evidence ??
      command.selection_evidence_json,
    final_holdout_evidence:
      nested.final_holdout_evidence ??
      nested.final_holdout_evidence_json ??
      command.final_holdout_evidence ??
      command.final_holdout_evidence_json,
    holdout_exposure:
      nested.holdout_exposure ?? command.holdout_exposure ?? {
        status: nested.final_holdout_status ?? command.final_holdout_status,
        first_opened_at: nested.first_opened_at ?? command.first_opened_at,
        candidate_decision_id:
          nested.candidate_decision_id ?? command.candidate_decision_id,
        evaluation_package_id:
          nested.evaluation_package_id ?? command.evaluation_package_id,
      },
  };
}

function holdoutMetrics(evaluationPackage: GovernedEvaluationPackage | null) {
  const evidence = objectValue(evaluationPackage?.final_holdout_evidence);
  return objectValue(evidence?.metrics) ?? {};
}

function statusPill(label: string, tone: "good" | "warn" | "neutral" = "neutral") {
  const style = tone === "good" ? "border-emerald-200 bg-emerald-50 text-emerald-800" : tone === "warn" ? "border-amber-200 bg-amber-50 text-amber-800" : "border-slate-200 bg-slate-50 text-slate-600";
  return <span className={`inline-flex rounded-full border px-2 py-0.5 text-[11px] font-semibold ${style}`}>{label}</span>;
}

export default function Step08Evaluation() {
  const navigate = useNavigate();
  const projectId = useWorkflowStore((state) => state.projectId);
  const projectName = useWorkflowStore((state) => state.projectName);
  const localDataset = loadLocalDataset();
  let activeIdentity: CanonicalDatasetIdentity | null = null;
  let identityError = "";
  try {
    activeIdentity = requireLocalDatasetCanonicalIdentity(projectId, localDataset, "Evaluation dataset identity");
  } catch (error) {
    identityError = error instanceof Error ? error.message : "Evaluation dataset identity is unavailable.";
  }
  const identityScope = activeIdentity
    ? `${activeIdentity.project_id}:${activeIdentity.dataset_id}:${activeIdentity.dataset_version_id}`
    : "";
  const [models, setModels] = useState<RankedRow[] | null>(null);
  const [selectionDecision, setSelectionDecision] =
    useState<LockedSelectionDecision | null>(null);
  const [selectedCandidateId, setSelectedCandidateId] = useState("");
  const [curves, setCurves] = useState<Curves | null>(null);
  const [command, setCommand] = useState<CommandCenter | null>(null);
  const [details, setDetails] = useState<DetailResponse | null>(null);
  const [importance, setImportance] = useState<ImportanceResponse | null>(null);
  const [hyperparameters, setHyperparameters] = useState<HyperparameterResponse | null>(null);
  const [tree, setTree] = useState<TreeResponse | null>(null);
  const [knn, setKnn] = useState<KnnResponse | null>(null);
  const [comparison, setComparison] = useState<InterpretationCandidate[]>([]);
  const [message, setMessage] = useState("");
  const [loadingDiagnostics, setLoadingDiagnostics] = useState(false);
  const [backendProblemType, setBackendProblemType] = useState<"classification" | "regression" | null>(null);

  // Backend truth (train/last's own problem_type) is authoritative and must win over the
  // browser's local dataset cache, which is a convenience cache scoped to the current tab's
  // session (Predictive Modeling Repair Stage 6.2) and is legitimately empty whenever this
  // page is opened fresh -- e.g. a reviewer opening an already-trained project in a new
  // session, or after a tab/browser restart. Falling back to loadLocalDataset() only when
  // the backend hasn't answered yet previously caused every such session to silently default
  // to "classification" and render the wrong analytical framing for a regression project
  // (confirmed defect, Regression Stage B audit).
  const problemType = backendProblemType ?? inferLocalProblemType(localDataset) ?? "classification";
  const supervised = useMemo(() => (models ?? []).filter((model) => !isAnomaly(model)), [models]);
  const anomalyModels = useMemo(() => (models ?? []).filter(isAnomaly), [models]);
  const selectionMetricName = selectionDecision?.selection_metric.name ?? "";
  const ordered = useMemo(
    () => selectionMetricName
      ? rankVerifiedSelectionCandidates(
          supervised,
          selectionMetricName,
          ["rmse", "mae", "mse"].includes(selectionMetricName),
        )
      : [],
    [selectionMetricName, supervised]
  );
  const topCandidates = ordered.slice(0, 3);
  const selectedModel = supervised.find((model) => model.candidate_id === selectedCandidateId) ?? null;
  const selectedCandidate = selectedModel ? candidateFromRow(selectedModel) : null;
  const lockedCandidateReady = lockedDecisionMatchesCandidate(
    selectionDecision,
    selectedModel,
  );
  const evaluationPackage = normalizeEvaluationPackage(command);
  const promotionReadiness = resolvePromotionReadiness(
    selectedModel,
    selectionDecision,
    evaluationPackage,
  );
  const exactEvaluationPackageId =
    promotionReadiness.ready &&
    activeIdentity &&
    command?.ok === true &&
    command.project_id === activeIdentity.project_id &&
    command.dataset_id === activeIdentity.dataset_id &&
    command.dataset_version_id === activeIdentity.dataset_version_id
      ? promotionReadiness.evaluationPackageId
      : "";
  const finalMetrics = holdoutMetrics(evaluationPackage);
  const holdoutExposure = objectValue(evaluationPackage?.holdout_exposure);
  const finalHoldoutEvidence = objectValue(
    evaluationPackage?.final_holdout_evidence,
  );
  const comparisonKeys = useMemo(() => new Set(comparison.map((candidate) => candidate.candidate_id)), [comparison]);

  useEffect(() => {
    if (!activeIdentity) {
      setModels([]);
      setComparison([]);
      setSelectionDecision(null);
      setSelectedCandidateId("");
      setMessage(identityError);
      return;
    }
    setComparison(loadInterpretationCandidates(activeIdentity));
    const context = new URLSearchParams({
      project_id: activeIdentity.project_id,
      dataset_id: activeIdentity.dataset_id,
      dataset_version_id: activeIdentity.dataset_version_id,
    });
    const decisionContext = new URLSearchParams({
      project_id: activeIdentity.project_id,
      expected_dataset_id: activeIdentity.dataset_id,
      expected_dataset_version_id: activeIdentity.dataset_version_id,
    });
    Promise.all([
      getJson<{ ok: boolean; summary?: { ranked?: RankedRow[]; problem_type?: string } }>(`${API_BASE}/train/last?${context.toString()}`),
      getJson<{ ok: boolean; decision?: Record<string, unknown> | null }>(`${API_BASE}/model/train/decision?${decisionContext.toString()}`),
    ])
      .then(([response, decisionResponse]) => {
        const rows = response.summary?.ranked ?? [];
        const actual = exactCandidateRows(rows, activeIdentity);
        setModels(actual);
        const reportedProblemType = response.summary?.problem_type;
        setBackendProblemType(reportedProblemType === "regression" || reportedProblemType === "classification" ? reportedProblemType : null);
        const locked = parseLockedSelectionDecision(
          decisionResponse.decision,
        );
        const lockedRow = locked
          ? actual.find(
              (row) =>
                row.candidate_id === locked.selected_candidate_id &&
                row.training_run_id === locked.training_run_id &&
                lockedDecisionMatchesCandidate(locked, row),
            )
          : null;
        if (locked && lockedRow) {
          setSelectionDecision(locked);
          setSelectedCandidateId(locked.selected_candidate_id);
        } else {
          setSelectionDecision(null);
          setSelectedCandidateId("");
        }
        if (rows.length && !actual.length) {
          setMessage("Training results were found, but none contain a complete exact-candidate lineage contract. Retrain under the current governed dataset version.");
        } else if (!locked || !lockedRow) {
          setMessage(
            "Evaluation remains sealed until Model Training returns one exact locked candidate decision with verified non-holdout selection evidence.",
          );
        }
      })
      .catch((error) => {
        setModels([]);
        setSelectionDecision(null);
        setSelectedCandidateId("");
        setMessage(String(error?.message ?? error));
      });
  // identityScope changes only when the exact registered dataset version changes.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [identityScope]);

  useEffect(() => {
    if (
      !selectedCandidate ||
      !selectionDecision ||
      !lockedCandidateReady ||
      !exactEvaluationPackageId
    ) return;
    setLoadingDiagnostics(true);
    setCurves(null);
    setDetails(null);
    setImportance(null);
    setHyperparameters(null);
    setTree(null);
    setKnn(null);
    const family = modelFamily(selectedModel);
    const governedParams = candidateRequestParams(selectedCandidate);
    governedParams.set("candidate_decision_id", selectionDecision.decision_id);
    governedParams.set("evaluation_package_id", exactEvaluationPackageId);
    const candidateQuery = governedParams.toString();
    const curvesRequest = getJson<Curves>(`${API_BASE}/eval/curves?${candidateQuery}`).then(setCurves).catch((error) => {
      setCurves({ ok: false, error: String(error?.message ?? error) });
    });
    const interpretationRequest = exactEvaluationPackageId
      ? (() => {
        const interpretationParams = candidateRequestParams(selectedCandidate);
        interpretationParams.set("candidate_decision_id", selectionDecision.decision_id);
        interpretationParams.set("evaluation_package_id", exactEvaluationPackageId);
        const interpretationQuery = interpretationParams.toString();
        return Promise.allSettled([
          getJson<DetailResponse>(`${API_BASE}/interpretation/details?${interpretationQuery}`),
          getJson<ImportanceResponse>(`${API_BASE}/interpretation/importance?${interpretationQuery}`),
          getJson<HyperparameterResponse>(`${API_BASE}/interpretation/hyperparameters?${interpretationQuery}`),
        ]).then(([detailResult, importanceResult, parameterResult]) => {
          const exactResponse = <T extends { evaluation_package_id?: string },>(result: PromiseSettledResult<T>) =>
            result.status === "fulfilled" && result.value.evaluation_package_id === exactEvaluationPackageId
              ? result.value
              : null;
          const exactDetails = exactResponse(detailResult);
          const exactImportance = exactResponse(importanceResult);
          const exactParameters = exactResponse(parameterResult);
          setDetails(exactDetails ?? { ok: false, error: "Interpretation details did not match the completed evaluation package." });
          setImportance(exactImportance ?? { ok: false, error: "Feature importance did not match the completed evaluation package." });
          setHyperparameters(exactParameters ?? { ok: false, rows: [] });
        });
      })()
      : Promise.resolve();
    const common = Promise.allSettled([curvesRequest, interpretationRequest]);
    const specific = family === "Decision Tree"
      ? getJson<TreeResponse>(`${API_BASE}/eval/tree?max_depth=4&${candidateQuery}`).then(setTree).catch((error) => setTree({ ok: false, error: String(error?.message ?? error) }))
      : family === "K-Nearest Neighbors"
        ? getJson<KnnResponse>(`${API_BASE}/eval/knn_clusters?max_points=900&${candidateQuery}`).then(setKnn).catch((error) => setKnn({ ok: false, error: String(error?.message ?? error) }))
        : Promise.resolve();
    Promise.allSettled([common, specific]).finally(() => setLoadingDiagnostics(false));
  // selectedCandidateId addresses one frozen candidate contract; display key is never an identity fallback.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [identityScope, selectedCandidateId, exactEvaluationPackageId, selectionDecision?.decision_id]);

  useEffect(() => {
    if (!selectedCandidate || !selectionDecision || !lockedCandidateReady) {
      setCommand(null);
      return;
    }
    setCommand(null);
    const timer = window.setTimeout(() => {
      const params = candidateRequestParams(selectedCandidate);
      params.set("candidate_decision_id", selectionDecision.decision_id);
      getJson<CommandCenter>(`${API_BASE}/eval/command_center?${params.toString()}`)
        .then(setCommand)
        .catch((error) => setCommand({ ok: false, error: String(error?.message ?? error) }));
    }, 120);
    return () => window.clearTimeout(timer);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [problemType, selectedCandidateId, selectionDecision?.decision_id, lockedCandidateReady]);

  function selectForReview(model: RankedRow) {
    const candidate = candidateFromRow(model);
    if (
      !selectionDecision ||
      candidate.candidate_id !== selectionDecision.selected_candidate_id ||
      candidate.training_run_id !== selectionDecision.training_run_id
    ) {
      setMessage(
        "The final holdout can be opened only for the exact candidate locked in Model Training. Comparison rows remain selection evidence only.",
      );
      return;
    }
    setSelectedCandidateId(candidate.candidate_id);
    logDecision({
      workflowStep: "Evaluation",
      actionType: "workflow_setting_changed",
      subject: "Model under review",
      previousValue: selectedCandidateId,
      newValue: candidate.candidate_id,
      systemRecommendation: "Review comparative performance, operating policy, model-specific evidence, and stability before final selection.",
    });
    window.requestAnimationFrame(() => document.getElementById("interactive-model-explorer")?.scrollIntoView({ behavior: "smooth", block: "start" }));
  }

  function setComparisonState(next: InterpretationCandidate[]) {
    if (!activeIdentity) {
      setMessage(identityError || "The exact registered dataset version is unavailable.");
      return;
    }
    const limited = next.slice(0, 4);
    saveInterpretationCandidates(activeIdentity, limited);
    setComparison(limited);
  }

  function toggleComparison(model: RankedRow) {
    if (isAnomaly(model)) return;
    let candidate: InterpretationCandidate;
    try {
      candidate = candidateFromRow(model);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "This candidate has incomplete lineage and cannot be selected.");
      return;
    }
    const exists = comparisonKeys.has(candidate.candidate_id);
    if (!exists && comparison.length >= 4) {
      setMessage("The comparison tray supports up to four supervised candidates. Remove a model before adding another.");
      return;
    }
    const next = exists
      ? comparison.filter((row) => row.candidate_id !== candidate.candidate_id)
      : [...comparison, candidate];
    setComparisonState(next);
    logDecision({
      workflowStep: "Evaluation",
      actionType: exists ? "evaluation_candidate_removed" : "evaluation_candidate_selected",
      subject: model.name,
      previousValue: exists ? "in comparison" : "not in comparison",
      newValue: exists ? "not in comparison" : "in comparison",
    });
  }

  function openInterpretation(model: RankedRow, candidates = comparison) {
    const candidate = candidateFromRow(model);
    if (
      candidate.candidate_id !== selectedCandidate?.candidate_id ||
      candidate.candidate_id !== selectionDecision?.selected_candidate_id ||
      candidate.training_run_id !== selectionDecision?.training_run_id ||
      !exactEvaluationPackageId
    ) {
      setSelectedCandidateId(candidate.candidate_id);
      setMessage("Complete the backend Evaluation review for this exact candidate before opening Interpretation.");
      return;
    }
    const existing = candidates.some((row) => row.candidate_id === candidate.candidate_id);
    const next = existing ? candidates : [...candidates, candidate].slice(-4);
    setComparisonState(next);
    navigate(projectWorkflowRoute(projectId, `/step09?candidate_id=${encodeURIComponent(candidate.candidate_id)}&training_run_id=${encodeURIComponent(candidate.training_run_id)}&candidate_decision_id=${encodeURIComponent(selectionDecision.decision_id)}&evaluation_package_id=${encodeURIComponent(exactEvaluationPackageId)}&compare=${encodeURIComponent(next.map((row) => row.candidate_id).join(","))}`));
  }

  function openComparison() {
    if (selectedModel && exactEvaluationPackageId) openInterpretation(selectedModel, comparison);
    else setMessage("Select and complete Evaluation for one exact candidate before opening Interpretation.");
  }

  const heroMetrics: AtlasWorkflowMetric[] = [
    { label: "Project", value: projectName || "Current project" },
    { label: "Supervised Candidates", value: String(supervised.length) },
    { label: "Selection Metric", value: selectionDecision ? selectionMetricLabel(selectionDecision.selection_metric) : "Locked decision required", tone: selectionDecision ? "success" : "warning" },
    { label: "Final Holdout", value: exactEvaluationPackageId ? "Evaluated · reporting only" : selectionDecision ? "Sealed / pending" : "Sealed", tone: exactEvaluationPackageId ? "success" : "warning" },
    { label: "OOT", value: command?.oot_status ?? "Not loaded", tone: "warning" },
    { label: "Comparison Tray", value: `${comparison.length}/4` },
  ];

  if (models === null) {
    return <StepShell title="Step 8: Evaluation Command Center" subtitle="Loading persisted model evidence." variant="modeling" heroMetrics={heroMetrics} nextDisabled><LoadingPanel text="Loading trained-model artifacts..." /></StepShell>;
  }

  if (!models.length || !supervised.length || !selectionDecision || !ordered.length) {
    return (
      <StepShell title="Step 8: Evaluation Command Center" subtitle="A locked candidate with verified selection evidence is required." variant="modeling" heroMetrics={heroMetrics} nextDisabled nextDisabledReason="Lock one exact candidate from verified training/CV evidence before Evaluation.">
        <Unavailable title="Final holdout remains sealed" text={message || "Return to Model Training, rank candidates from verified non-holdout evidence, and lock one exact candidate decision."} />
      </StepShell>
    );
  }

  const leader = ordered[0];
  const active = selectedModel;
  const metricLabel = selectionMetricLabel(selectionDecision.selection_metric);
  const selectionMetricValue = active
    ? verifiedSelectionMetric(active, selectionMetricName)?.value
    : undefined;
  const finalMetricKey = problemType === "regression" ? "rmse" : "pr_auc";
  const finalMetricValue = typeof finalMetrics[finalMetricKey] === "number"
    ? finalMetrics[finalMetricKey] as number
    : undefined;

  return (
    <StepShell
      title="Step 8: Evaluation Command Center"
      subtitle="Compare real fitted artifacts and review final-holdout reporting without tuning against the holdout or implying final approval."
      variant="modeling"
      heroMetrics={heroMetrics}
      nextLabel="Continue to Interpretation Review"
      nextDisabled={!selectedModel || !exactEvaluationPackageId}
      nextDisabledReason={promotionReadiness.reason}
      nextStatusLine={exactEvaluationPackageId ? `Evaluation package ${exactEvaluationPackageId} verifies selection integrity, candidate lock, and final-holdout isolation.` : promotionReadiness.reason}
      onNextClick={() => openComparison()}
      showDeveloperTools={false}
    >
      <div className="space-y-5" data-testid="evaluation-command-center">
        {message ? <div className="rounded-md border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">{message}</div> : null}

        <section className="overflow-hidden rounded-md border border-slate-800 bg-slate-950 text-white" data-testid="atlas-performance-summary">
          <div className="grid gap-6 p-6 xl:grid-cols-[1.5fr_1fr]">
            <div>
              <div className="text-xs font-semibold uppercase text-emerald-300">A. ATLAS Performance Summary</div>
              <h2 className="mt-2 text-2xl font-semibold">{cleanModelName(leader.name)} led the locked selection ranking</h2>
              <p className="mt-3 max-w-3xl text-sm leading-6 text-slate-300">
                This order is frozen from {formatSelectionSource(selectionDecision.selection_metric.source)} evidence before final-holdout exposure. Final-holdout results below are reporting-only and cannot change the candidate decision.
              </p>
              <div className="mt-5 flex flex-wrap gap-2">
                {statusPill(`Provisional Leader: ${cleanModelName(leader.name)}`, "good")}
                {statusPill(`TEST: ${command?.test_status ?? "Pending"}`, command?.ok ? "good" : "warn")}
                {statusPill(`OOT: ${command?.oot_status ?? "Not loaded"}`, "warn")}
              </div>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <DarkStat label="Selection metric" value={metricLabel} />
              <DarkStat label="Selection value" value={formatMetric(verifiedSelectionMetric(leader, selectionMetricName)?.value)} />
              <DarkStat label="Candidate decision" value={selectionDecision.decision_id} />
              <DarkStat label="Final holdout" value={exactEvaluationPackageId ? "Evaluated · reporting only" : "Sealed / pending"} />
            </div>
          </div>
          <div className="grid border-t border-slate-800 bg-slate-900/70 md:grid-cols-3">
            <SummaryBand label="Selection result" value={`${cleanModelName(leader.name)} led on ${metricLabel}; the locked candidate is ${selectionDecision.selected_candidate_id}.`} />
            <SummaryBand label="Unresolved risk" value={command?.oot_status === "Not loaded" ? "OOT evidence has not been loaded." : "Review calibration and degradation flags."} />
            <SummaryBand label="Recommended action" value="Compare 2-4 candidates before final Interpretation and RFE." />
          </div>
        </section>

        <section className="rounded-md border border-blue-200 bg-blue-50 p-5" data-testid="selection-evidence">
          <SectionHeading
            eyebrow="B. Selection Evidence"
            title="Candidate decision frozen before holdout exposure"
            description="This is the only evidence allowed to rank candidates. It comes from the governed training partition and cannot be replaced by final-holdout performance."
          />
          <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <MetricTile label="Candidate decision" value={selectionDecision.decision_id} />
            <MetricTile label="Locked candidate" value={selectionDecision.selected_candidate_id} />
            <MetricTile label="Locked at" value={selectionDecision.selection_locked_at} />
            <MetricTile label="Ranking snapshot" value={selectionDecision.selection_ranking_snapshot_hash} />
            <MetricTile label={metricLabel} value={formatMetric(selectionDecision.selection_metric.value)} />
            <MetricTile label="Selection partition" value={selectionDecision.selection_metric.partition_id} />
            <MetricTile label="Fold definition" value={selectionDecision.selection_metric.fold_definition_id || "Governed validation partition"} />
            <MetricTile label="Fold summary" value={`${selectionDecision.selection_metric.fold_count} folds · σ ${formatMetric(selectionDecision.selection_metric.standard_deviation)}`} />
          </div>
        </section>

        <section className="rounded-md border border-emerald-200 bg-emerald-50 p-5" data-testid="final-holdout-evidence">
          <SectionHeading
            eyebrow="C. Final-Holdout Evidence"
            title="Reporting-only evidence remains separate"
            description="The final holdout is opened only for the locked candidate. Its metrics cannot reorder the leaderboard, replace the decision, tune a threshold, or select features."
          />
          <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <MetricTile label="Exposure status" value={String(holdoutExposure?.status ?? "sealed")} />
            <MetricTile label="First opened" value={String(holdoutExposure?.first_opened_at ?? "Not opened")} />
            <MetricTile label="Evaluation package" value={exactEvaluationPackageId || "Pending"} />
            <MetricTile label="Evidence role" value={String(finalHoldoutEvidence?.role ?? "reporting_only")} />
            <MetricTile label={`${problemType === "regression" ? "RMSE" : "PR-AUC"} · final holdout`} value={formatMetric(finalMetricValue)} />
            <MetricTile label="Isolation status" value={String(evaluationPackage?.isolation_status ?? "Pending")} />
            <MetricTile label="Selection integrity" value={String(evaluationPackage?.selection_integrity_status ?? "Pending")} />
            <MetricTile label="Recommendations" value={command?.threshold_policy?.recommendations_derived_from_final_holdout === false ? "Not derived from holdout" : "Pending verification"} />
          </div>
        </section>

        <section className="rounded-md border border-blue-200 bg-blue-50 p-5" data-testid="top-candidate-comparison">
          <SectionHeading eyebrow="D. Selection Ranking Snapshot" title="The strongest supervised candidates" description="Cards summarize verified selection evidence only. Final-holdout metrics never appear in or alter this ranking." />
          <div className="mt-4 grid gap-4 xl:grid-cols-3">
            {topCandidates.map((model, index) => (
              <CandidateCard
                key={model.key}
                model={model}
                rank={index + 1}
                active={model.candidate_id === selectedCandidateId}
                compared={comparisonKeys.has(model.candidate_id ?? "")}
                selectionMetricName={selectionMetricName}
                locked={model.candidate_id === selectionDecision.selected_candidate_id}
                canInterpret={model.candidate_id === selectedCandidate?.candidate_id && Boolean(exactEvaluationPackageId)}
                onReview={() => selectForReview(model)}
                onCompare={() => toggleComparison(model)}
                onInterpret={() => openInterpretation(model)}
              />
            ))}
          </div>
        </section>

        <section id="interactive-model-explorer" className="rounded-md border border-slate-200 bg-white p-5" data-testid="interactive-model-explorer">
          <div className="flex flex-wrap items-end justify-between gap-4">
            <SectionHeading eyebrow="E. Locked Candidate Explorer" title="Model-specific final-holdout review" description="Diagnostics are opened only for the exact locked candidate and completed Evaluation package. Candidate comparison never opens another holdout." />
            <label className="grid min-w-72 gap-1 text-sm">
              <span className="text-xs font-semibold uppercase text-slate-500">Model under review</span>
              <select className="rounded-md border border-slate-300 bg-slate-50 px-3 py-2 font-semibold" value={selectedCandidateId} disabled>
                {selectedModel ? <option value={selectedModel.candidate_id}>{cleanModelName(selectedModel.name)} · locked</option> : <option value="">Locked decision required</option>}
              </select>
            </label>
          </div>
          {!active ? <Unavailable title="Select a candidate for review" text="Choose an exact governed candidate. ATLAS will not infer one from leaderboard order or algorithm name." /> : <>
          <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <MetricTile label={`${metricLabel} · selection`} value={formatMetric(selectionMetricValue)} />
            <MetricTile label={`${problemType === "regression" ? "RMSE" : "PR-AUC"} · final holdout`} value={formatMetric(finalMetricValue)} />
            {problemType === "regression" ? (
              <>
                <MetricTile label="Final-holdout MAE" value={formatMetric(finalMetrics.mae as number | undefined)} />
                <MetricTile label="Final-holdout R-squared" value={formatMetric(finalMetrics.r2 as number | undefined)} />
              </>
            ) : (
              <>
                <MetricTile label="Final-holdout ROC-AUC" value={formatMetric(finalMetrics.roc_auc as number | undefined)} />
                <MetricTile label="Final-holdout recall" value={formatMetric(finalMetrics.recall as number | undefined)} />
              </>
            )}
          </div>
          {loadingDiagnostics ? <LoadingPanel text={`Loading diagnostics for ${cleanModelName(active.name)}...`} /> : null}
          {!loadingDiagnostics && curves?.ok && problemType === "classification" ? (
            <div className="mt-4 grid gap-4 xl:grid-cols-3">
              <ChartCard title="ROC Curve" badge="TEST holdout"><CurveChart x={curves.roc?.fpr ?? []} y={curves.roc?.tpr ?? []} xLabel="False positive rate" yLabel="True positive rate" color="#2563eb" diagonal /></ChartCard>
              <ChartCard title="Precision-Recall Curve" badge="TEST holdout"><CurveChart x={curves.pr?.recall ?? []} y={curves.pr?.precision ?? []} xLabel="Recall" yLabel="Precision" color="#0f766e" /></ChartCard>
              <ChartCard title={`Confusion Matrix @ ${formatMetric(command?.threshold?.threshold, 3)}`} badge="Active policy"><ConfusionMatrix matrix={command?.threshold?.confusion ?? curves.confusion ?? []} /></ChartCard>
            </div>
          ) : null}
          {!loadingDiagnostics && curves && !curves.ok ? <Unavailable title="Common diagnostics unavailable" text={curves.error ?? "The backend did not return a fitted holdout artifact for this model."} /> : null}
          {!loadingDiagnostics ? <ModelSpecificDiagnostic model={active} details={details} importance={importance} hyperparameters={hyperparameters} tree={tree} knn={knn} /> : null}
          </>}
        </section>

        <section className="rounded-md border border-slate-200 bg-white p-5" data-testid="visual-intelligence-evaluation">
          <SectionHeading
            eyebrow="C2. Visual Intelligence"
            title={problemType === "regression" ? "Regression Diagnostic Explorer" : "Classification Decision Explorer"}
            description="Select a durable TRAIN/TEST/OOT scoring run to inspect bounded diagnostics. Final-holdout evidence is reporting-only and never selects or optimizes a threshold."
          />
          <div className="mt-4">
            {problemType === "regression" ? (
              <VisualAnalysisPanel analysisType="regression" title="Regression Diagnostic Explorer" expectedProblemType="regression">
                <RegressionDiagnosticExplorer />
              </VisualAnalysisPanel>
            ) : (
              <VisualAnalysisPanel analysisType="classification" title="Classification Decision Explorer" expectedProblemType="classification">
                <ClassificationDecisionExplorer />
              </VisualAnalysisPanel>
            )}
          </div>
        </section>

        {problemType === "classification" ? (
          <section className="rounded-md border border-indigo-200 bg-indigo-50 p-5" data-testid="threshold-operating-policy">
            <SectionHeading eyebrow="D. Threshold Reporting" title="Report the frozen governed deployment threshold" description="The final holdout is reporting-only. ATLAS does not derive, optimize, or recommend a threshold from these labels or scores; validation/CV thresholds appear only when frozen in the candidate contract." />
            <div className="mt-4 grid gap-5 xl:grid-cols-[330px_minmax(0,1fr)]">
              <div className="rounded-md border border-indigo-200 bg-white p-4">
                <div className="text-xs font-semibold uppercase text-slate-500">Reported deployment threshold</div>
                <div className="mt-2 font-mono text-3xl font-semibold text-indigo-700">{command?.threshold?.threshold?.toFixed(3) ?? "—"}</div>
                <div className="mt-4 space-y-2 text-xs leading-5 text-slate-600">
                  <p><span className="font-semibold text-slate-800">Source:</span> {formatThresholdSource(command?.threshold_policy?.active_source)}</p>
                  <p>This value is governed before final-holdout reporting. Change it only through an approved validation/CV or deployment-policy workflow.</p>
                  <p className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-amber-900">Final-holdout metrics below are evidence reports, not threshold recommendations.</p>
                </div>
              </div>
              <div>
                {command?.ok && command.threshold ? (
                  <ThresholdDashboard
                    curves={curves}
                    lift={command.lift}
                    metrics={command.threshold}
                  />
                ) : (
                  <Unavailable title="Threshold diagnostics unavailable" text={command?.error ?? "Waiting for real holdout scores."} />
                )}
              </div>
            </div>
            {command?.ok && command.lift ? <LiftGainCapture lift={command.lift} /> : null}
          </section>
        ) : null}

        <section className="rounded-md border border-slate-200 bg-white p-5" data-testid="dataset-performance">
          <SectionHeading eyebrow="E. Dataset Performance" title="Evaluation roles remain distinct" description="Development diagnostics, independent TEST evidence, and OOT evidence are never blended." />
          <div className="mt-4 grid gap-4 lg:grid-cols-3">
            <DatasetRoleCard title="Internal Validation" role="Model selection evidence" status={lockedCandidateReady ? "Verified" : "Unavailable"} metrics={[{ label: metricLabel, value: formatMetric(selectionMetricValue) }, { label: "Source", value: formatSelectionSource(selectionDecision.selection_metric.source) }]} tone="slate" />
            <DatasetRoleCard title="TEST" role="Final holdout - reporting only" status={exactEvaluationPackageId ? "Evaluated" : "Sealed"} metrics={[{ label: problemType === "regression" ? "RMSE" : "PR-AUC", value: formatMetric(finalMetricValue) }, { label: "Evaluation package", value: exactEvaluationPackageId || "Not opened" }]} tone="blue" />
            <DatasetRoleCard title="OOT" role="Out-of-time stability evaluation" status={command?.oot_status ?? "Not loaded"} metrics={[{ label: "Performance", value: "Not evaluated" }, { label: "Degradation", value: "Not evaluated" }]} tone="amber" />
          </div>
        </section>

        <section className="rounded-md border border-emerald-200 bg-emerald-50 p-5" data-testid="stability-calibration">
          <SectionHeading eyebrow="F. Stability and Calibration" title="Probability quality and evidence degradation" description="Calibration below is reporting-only final-holdout evidence. It cannot affect candidate selection, feature selection, or threshold tuning. OOT metrics remain unavailable until an OOT artifact is loaded." />
          <div className="mt-4 grid gap-4 xl:grid-cols-[1.35fr_1fr]">
            <ChartCard title="Reliability Curve" badge="Predicted vs observed">
              {command?.calibration?.rows?.length ? <CalibrationChart rows={command.calibration.rows} /> : <Unavailable title="Calibration unavailable" text={command?.error ?? "No classification calibration rows were returned."} compact />}
            </ChartCard>
            <div className="grid gap-3 sm:grid-cols-2">
              <MetricTile label="Brier score" value={formatMetric(command?.calibration?.brier_score)} />
              <MetricTile label="Calibration method" value={command?.calibration?.method ?? active?.calibration_method ?? "Not applied"} />
              <MetricTile label="Calibration slope" value={formatMetric(command?.calibration?.slope)} />
              <MetricTile label="Calibration intercept" value={formatMetric(command?.calibration?.intercept)} />
              <MetricTile label="TEST role" value={exactEvaluationPackageId ? "Reporting only" : "Sealed"} />
              <MetricTile label="OOT role" value={command?.oot_status ?? "Not loaded"} />
            </div>
          </div>
        </section>

        <section className="rounded-md border border-slate-200 bg-white p-5" data-testid="full-leaderboard">
          <div className="flex flex-wrap items-end justify-between gap-3">
            <SectionHeading eyebrow="G. Frozen Selection Ranking" title="Verified supervised candidates" description="This table is ordered only by the locked non-holdout selection metric. Final-holdout values never appear in or alter the ranking." />
            <div>{statusPill(`${ordered.length} verified candidates`)}</div>
          </div>
          <div className="mt-4 overflow-x-auto rounded-md border border-slate-200">
            <table className="min-w-[980px] w-full text-sm">
              <thead className="bg-slate-100 text-left text-[11px] font-semibold uppercase text-slate-600">
                <tr><th className="px-3 py-3">Rank</th><th className="px-3 py-3">Model</th><th className="px-3 py-3">Family</th><th className="px-3 py-3">Selection metric</th><th className="px-3 py-3">Source</th><th className="px-3 py-3">Fold evidence</th><th className="px-3 py-3">Decision</th><th className="px-3 py-3">Actions</th></tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {ordered.map((model, index) => <LeaderboardRow key={model.candidate_id} model={model} rank={index + 1} active={model.candidate_id === selectedCandidateId} compared={comparisonKeys.has(model.candidate_id ?? "")} selectionMetricName={selectionMetricName} locked={model.candidate_id === selectionDecision.selected_candidate_id} canInterpret={model.candidate_id === selectedCandidate?.candidate_id && Boolean(exactEvaluationPackageId)} onReview={() => selectForReview(model)} onCompare={() => toggleComparison(model)} onInterpret={() => openInterpretation(model)} />)}
              </tbody>
            </table>
          </div>
          {anomalyModels.length ? <AnomalyDiagnostics models={anomalyModels} /> : null}
        </section>

        <section className="rounded-md border border-violet-200 bg-violet-50 p-5" data-testid="interpretation-comparison-tray">
          <div className="flex flex-wrap items-end justify-between gap-3">
            <SectionHeading eyebrow="H. Interpretation Comparison Tray" title="Persistent candidate review set" description="Keep two to four candidates for side-by-side Interpretation. A single candidate can still be opened directly." />
            <div className="flex gap-2"><button type="button" className="atlas-secondary-button" onClick={() => setComparisonState([])} disabled={!comparison.length}><Trash2 size={15} /> Clear Comparison</button><button type="button" className="atlas-primary-button" onClick={openComparison} disabled={!selectedModel || !exactEvaluationPackageId}><GitCompareArrows size={15} /> Open Reviewed Candidate</button></div>
          </div>
          <div className="mt-4 grid gap-3 xl:grid-cols-2">
            {comparison.map((candidate) => {
              const model = supervised.find((row) => row.candidate_id === candidate.candidate_id);
              if (!model) return null;
              const rank = ordered.findIndex((row) => row.candidate_id === candidate.candidate_id) + 1;
              return <ComparisonRow key={candidate.candidate_id} model={model} rank={rank} selectionMetricName={selectionMetricName} locked={candidate.candidate_id === selectionDecision.selected_candidate_id} canInterpret={candidate.candidate_id === selectedCandidate?.candidate_id && Boolean(exactEvaluationPackageId)} onRemove={() => toggleComparison(model)} onOpen={() => openInterpretation(model)} />;
            })}
            {!comparison.length ? <div className="col-span-full rounded-md border border-dashed border-violet-300 bg-white p-8 text-center text-sm text-slate-600">Add candidates from the cards or leaderboard. No model will be automatically selected or approved.</div> : null}
          </div>
        </section>
      </div>
    </StepShell>
  );
}

function SectionHeading({ eyebrow, title, description }: { eyebrow: string; title: string; description: string }) {
  return <div><div className="text-[11px] font-semibold uppercase text-blue-700">{eyebrow}</div><h2 className="mt-1 text-lg font-semibold text-slate-950">{title}</h2><p className="mt-1 max-w-4xl text-sm leading-6 text-slate-600">{description}</p></div>;
}

function DarkStat({ label, value }: { label: string; value: string }) {
  return <div className="rounded-md border border-slate-700 bg-slate-900 px-3 py-3"><div className="text-[10px] font-semibold uppercase text-slate-400">{label}</div><div className="mt-1 text-sm font-semibold text-white">{value}</div></div>;
}

function SummaryBand({ label, value }: { label: string; value: string }) {
  return <div className="border-slate-800 px-5 py-4 md:border-r"><div className="text-[10px] font-semibold uppercase text-slate-500">{label}</div><div className="mt-1 text-sm text-slate-200">{value}</div></div>;
}

function MetricTile({ label, value }: { label: string; value: string }) {
  return <div className="min-w-0 rounded-md border border-slate-200 bg-white px-3 py-3"><div className="text-[10px] font-semibold uppercase text-slate-500">{label}</div><div className="mt-1 break-words text-base font-semibold text-slate-950">{value}</div></div>;
}

function CandidateCard({ model, rank, active, compared, selectionMetricName, locked, canInterpret, onReview, onCompare, onInterpret }: { model: RankedRow; rank: number; active: boolean; compared: boolean; selectionMetricName: string; locked: boolean; canInterpret: boolean; onReview: () => void; onCompare: () => void; onInterpret: () => void }) {
  const metric = verifiedSelectionMetric(model, selectionMetricName)!;
  return <article className={`rounded-md border bg-white p-5 shadow-sm ${active ? "border-blue-500 ring-2 ring-blue-100" : "border-blue-200"}`} data-model-key={model.key}>
    <div className="flex items-start justify-between gap-3"><div><div className="text-[11px] font-semibold uppercase text-blue-700">Frozen selection rank {rank}</div><h3 className="mt-1 text-lg font-semibold text-slate-950">{cleanModelName(model.name)}</h3><div className="mt-1 text-xs text-slate-500">{modelFamily(model)} | Interpretability {interpretability(model)}</div></div>{locked ? statusPill("Locked Candidate", "good") : rank === 1 ? statusPill("Selection Leader", "good") : statusPill("Selection Challenger")}</div>
    <div className="mt-4 grid grid-cols-2 gap-2"><MetricTile label={selectionMetricLabel(metric)} value={formatMetric(metric.value)} /><MetricTile label="Standard deviation" value={formatMetric(metric.standard_deviation)} /><MetricTile label="Fold evidence" value={metric.fold_count ? `${metric.fold_count} folds` : "Governed validation"} /><MetricTile label="Selection partition" value={metric.partition_id} /><MetricTile label="Threshold source" value={metric.threshold_source} /><MetricTile label="Calibration source" value={metric.calibration_source} /></div>
    <div className="mt-4 flex flex-wrap gap-2"><button type="button" className="atlas-secondary-button" onClick={onReview} disabled={!locked} title={locked ? "Open final-holdout Evaluation for the locked candidate." : "Final-holdout access is restricted to the locked candidate."}><Activity size={15} /> {locked ? "Review Locked Candidate" : "Selection Evidence Only"}</button><button type="button" className="atlas-secondary-button" onClick={onCompare}>{compared ? <Check size={15} /> : <GitCompareArrows size={15} />}{compared ? "Remove from Comparison" : "Add to Comparison"}</button><button type="button" className="atlas-primary-button" onClick={onInterpret} disabled={!canInterpret} title={canInterpret ? "Open this exact evaluated candidate." : "Only the locked candidate with a verified Evaluation package can continue."}>Open Interpretation <ArrowRight size={15} /></button></div>
  </article>;
}

function ChartCard({ title, badge, children }: { title: string; badge?: string; children: React.ReactNode }) {
  return <div className="rounded-md border border-slate-200 bg-white p-4"><div className="mb-3 flex items-center justify-between gap-2"><h3 className="text-sm font-semibold text-slate-950">{title}</h3>{badge ? statusPill(badge) : null}</div>{children}</div>;
}

function CurveChart({ x, y, xLabel, yLabel, color, diagonal = false }: { x: number[]; y: number[]; xLabel: string; yLabel: string; color: string; diagonal?: boolean }) {
  if (!x.length || !y.length) return <Unavailable title="Curve unavailable" text="The fitted artifact did not provide this curve." compact />;
  const width = 520, height = 270, pad = 42;
  const sx = (value: number) => pad + Math.max(0, Math.min(1, value)) * (width - pad * 1.35);
  const sy = (value: number) => height - pad - Math.max(0, Math.min(1, value)) * (height - pad * 1.35);
  const points = x.map((value, index) => `${sx(value)},${sy(y[index] ?? 0)}`).join(" ");
  return <svg viewBox={`0 0 ${width} ${height}`} className="h-[250px] w-full" role="img" aria-label={`${yLabel} by ${xLabel}`}><rect width={width} height={height} rx="6" fill="#f8fafc" />{[0, .25, .5, .75, 1].map((tick) => <g key={tick}><line x1={sx(tick)} y1={pad / 2} x2={sx(tick)} y2={height - pad} stroke="#e2e8f0" /><line x1={pad} y1={sy(tick)} x2={width - pad / 2} y2={sy(tick)} stroke="#e2e8f0" /><text x={sx(tick)} y={height - 22} textAnchor="middle" fontSize="10" fill="#64748b">{tick.toFixed(2)}</text></g>)}{diagonal ? <line x1={sx(0)} y1={sy(0)} x2={sx(1)} y2={sy(1)} stroke="#94a3b8" strokeDasharray="5 5" /> : null}<polyline points={points} fill="none" stroke={color} strokeWidth="3" strokeLinejoin="round" /><text x={width / 2} y={height - 5} textAnchor="middle" fontSize="11" fill="#475569">{xLabel}</text><text x="13" y={height / 2} textAnchor="middle" fontSize="11" fill="#475569" transform={`rotate(-90 13 ${height / 2})`}>{yLabel}</text></svg>;
}

function ConfusionMatrix({ matrix }: { matrix: number[][] }) {
  if (matrix.length !== 2) return <Unavailable title="Confusion matrix unavailable" text="No active-threshold confusion matrix was returned." compact />;
  const cells = [{ label: "True Negative", value: matrix[0]?.[0] ?? 0, tone: "border-emerald-200 bg-emerald-50" }, { label: "False Positive", value: matrix[0]?.[1] ?? 0, tone: "border-amber-200 bg-amber-50" }, { label: "False Negative", value: matrix[1]?.[0] ?? 0, tone: "border-rose-200 bg-rose-50" }, { label: "True Positive", value: matrix[1]?.[1] ?? 0, tone: "border-emerald-200 bg-emerald-50" }];
  return <div className="grid h-[250px] grid-cols-2 gap-2">{cells.map((cell) => <div key={cell.label} className={`flex flex-col justify-between rounded-md border p-3 ${cell.tone}`}><div className="text-xs font-semibold text-slate-700">{cell.label}</div><div className="text-3xl font-semibold text-slate-950">{cell.value.toLocaleString()}</div></div>)}</div>;
}

function ModelSpecificDiagnostic({ model, details, importance, hyperparameters, tree, knn }: { model: RankedRow; details: DetailResponse | null; importance: ImportanceResponse | null; hyperparameters: HyperparameterResponse | null; tree: TreeResponse | null; knn: KnnResponse | null }) {
  const family = modelFamily(model);
  return <div className="mt-5 rounded-md border border-slate-200 bg-slate-50 p-4" data-testid={`model-specific-${family.toLowerCase().replace(/[^a-z]+/g, "-")}`}><div className="flex flex-wrap items-center justify-between gap-2"><div><div className="text-[11px] font-semibold uppercase text-violet-700">Model-Specific Evaluation</div><h3 className="mt-1 text-base font-semibold text-slate-950">{family} diagnostics</h3></div>{statusPill(importance?.method ?? "Fitted artifact")}</div>
    {family === "Decision Tree" ? <DecisionTreeDiagnostic tree={tree} /> : null}
    {family === "K-Nearest Neighbors" ? <KnnDiagnostic knn={knn} parameters={hyperparameters?.rows ?? []} /> : null}
    {family === "Linear Classifier" || family === "Support Vector Machine" ? <CoefficientDiagnostic details={details} parameters={hyperparameters?.rows ?? []} family={family} /> : null}
    {["Tree Ensemble", "Gradient Boosting", "Gaussian Naive Bayes", "Neural Network", "Supervised Estimator"].includes(family) ? <ImportanceDiagnostic response={importance} family={family} parameters={hyperparameters?.rows ?? []} /> : null}
  </div>;
}

function DecisionTreeDiagnostic({ tree }: { tree: TreeResponse | null }) {
  if (!tree) return <LoadingPanel text="Loading fitted decision tree..." />;
  if (!tree.ok || !tree.nodes?.length) return <Unavailable title="Decision Tree diagnostic unavailable" text={tree.error ?? "The selected artifact is not a fitted decision tree."} />;
  const nodes = tree.nodes, edges = tree.edges ?? [], width = 920, height = Math.max(280, (Math.max(...nodes.map((node) => node.depth)) + 1) * 110), nodeWidth = 145, nodeHeight = 62;
  const point = (node: TreeNode) => ({ x: 40 + node.x * (width - 80), y: 45 + node.depth * 105 });
  const byId = new Map(nodes.map((node) => [node.id, node]));
  return <div className="mt-4"><div className="grid gap-3 sm:grid-cols-3"><MetricTile label="Rendered nodes" value={String(nodes.length)} /><MetricTile label="Leaf nodes" value={String(nodes.filter((node) => node.leaf).length)} /><MetricTile label="Displayed depth" value={String(Math.max(...nodes.map((node) => node.depth)))} /></div><div className="mt-3 overflow-x-auto rounded-md border bg-white p-2"><svg viewBox={`0 0 ${width} ${height}`} className="min-w-[780px] w-full" role="img" aria-label="Decision Tree visualization">{edges.map((edge) => { const source = byId.get(edge.source), target = byId.get(edge.target); if (!source || !target) return null; const a = point(source), b = point(target); return <g key={`${edge.source}-${edge.target}`}><line x1={a.x} y1={a.y + nodeHeight / 2} x2={b.x} y2={b.y - nodeHeight / 2} stroke="#94a3b8" /><text x={(a.x + b.x) / 2} y={(a.y + b.y) / 2} fontSize="10" fill="#64748b">{edge.label}</text></g>; })}{nodes.map((node) => { const p = point(node); return <g key={node.id}><rect x={p.x - nodeWidth / 2} y={p.y - nodeHeight / 2} width={nodeWidth} height={nodeHeight} rx="6" fill={node.leaf ? "#ecfdf5" : "#eff6ff"} stroke={node.leaf ? "#10b981" : "#3b82f6"} /><text x={p.x} y={p.y - 10} textAnchor="middle" fontSize="10" fontWeight="600" fill="#0f172a">{node.leaf ? `Leaf: ${node.prediction}` : `${node.feature} <= ${formatMetric(node.threshold, 2)}`}</text><text x={p.x} y={p.y + 7} textAnchor="middle" fontSize="9" fill="#475569">n={node.samples.toLocaleString()} | event {formatPercent(node.positive_rate)}</text></g>; })}</svg></div></div>;
}

function KnnDiagnostic({ knn, parameters }: { knn: KnnResponse | null; parameters: Array<{ parameter: string; value: string }> }) {
  if (!knn) return <LoadingPanel text="Loading KNN neighborhood evidence..." />;
  if (!knn.ok || !knn.points?.length) return <Unavailable title="KNN diagnostic unavailable" text={knn.error ?? "No fitted neighborhood coordinates were returned."} />;
  const width = 900, height = 360, pad = 40, [xmin, xmax] = knn.x_domain ?? [Math.min(...knn.points.map((p) => p.x)), Math.max(...knn.points.map((p) => p.x))], [ymin, ymax] = knn.y_domain ?? [Math.min(...knn.points.map((p) => p.y)), Math.max(...knn.points.map((p) => p.y))];
  const sx = (v: number) => pad + ((v - xmin) / (xmax - xmin || 1)) * (width - pad * 1.5), sy = (v: number) => height - pad - ((v - ymin) / (ymax - ymin || 1)) * (height - pad * 1.5);
  return <div className="mt-4"><div className="grid gap-3 sm:grid-cols-3"><MetricTile label="Selected K" value={String(knn.neighbor_count ?? parameters.find((row) => /neighbor/i.test(row.parameter))?.value ?? "Not recorded")} /><MetricTile label="Displayed sample" value={(knn.sample_size ?? knn.points.length).toLocaleString()} /><MetricTile label="Projection" value="Governed PCA view" /></div><div className="mt-3 rounded-md border bg-white p-2"><svg viewBox={`0 0 ${width} ${height}`} className="h-[360px] w-full" role="img" aria-label="KNN decision region and neighborhood visualization"><rect width={width} height={height} fill="#f8fafc" />{knn.grid?.map((cell, index) => <circle key={index} cx={sx(cell.x)} cy={sy(cell.y)} r="6" fill={cell.prediction ? "#fed7aa" : "#dbeafe"} opacity="0.45" />)}{knn.points.map((point, index) => <circle key={index} cx={sx(point.x)} cy={sy(point.y)} r="3.1" fill={point.class ? "#ea580c" : "#2563eb"} stroke={point.prediction ? "#7c2d12" : "#1e3a8a"} strokeWidth="1" opacity="0.78" />)}<text x={width / 2} y={height - 8} textAnchor="middle" fontSize="11" fill="#475569">Governed PCA component 1</text><text x="12" y={height / 2} textAnchor="middle" fontSize="11" fill="#475569" transform={`rotate(-90 12 ${height / 2})`}>Governed PCA component 2</text></svg></div></div>;
}

function CoefficientDiagnostic({ details, parameters, family }: { details: DetailResponse | null; parameters: Array<{ parameter: string; value: string }>; family: string }) {
  const rows = details?.coefficients?.slice(0, 12) ?? [];
  if (!details) return <LoadingPanel text={`Loading ${family} coefficient evidence...`} />;
  if (!details.ok || !rows.length) return <Unavailable title={`${family} coefficient diagnostic unavailable`} text={details.error ?? details.message ?? "The fitted estimator did not expose a coefficient vector."} />;
  const max = Math.max(...rows.map((row) => Math.abs(row.coefficient)), 1e-9);
  return <div className="mt-4 grid gap-4 xl:grid-cols-[1.4fr_1fr]"><div className="rounded-md border bg-white p-4"><div className="text-sm font-semibold">Coefficient direction and magnitude</div><div className="mt-3 space-y-2">{rows.map((row) => <div key={row.feature} className="grid grid-cols-[180px_minmax(0,1fr)_76px] items-center gap-3 text-xs"><div className="truncate font-medium" title={row.feature}>{row.feature}</div><div className="relative h-4 rounded bg-slate-100"><div className={`absolute top-0 h-4 rounded ${row.coefficient >= 0 ? "left-1/2 bg-blue-500" : "right-1/2 bg-rose-500"}`} style={{ width: `${Math.abs(row.coefficient) / max * 50}%` }} /><div className="absolute left-1/2 top-0 h-4 w-px bg-slate-500" /></div><div className="text-right font-mono">{row.coefficient.toFixed(4)}</div></div>)}</div></div><div className="rounded-md border bg-white p-4"><MetricTile label="Intercept" value={formatMetric(details.intercept)} /><div className="mt-3 text-sm font-semibold">Regularization and fit</div><div className="mt-2 space-y-2">{parameters.slice(0, 8).map((row) => <div key={row.parameter} className="flex justify-between gap-3 border-b pb-1 text-xs"><span className="text-slate-500">{row.parameter}</span><span className="font-semibold">{row.value}</span></div>)}</div></div></div>;
}

function ImportanceDiagnostic({ response, family, parameters }: { response: ImportanceResponse | null; family: string; parameters: Array<{ parameter: string; value: string }> }) {
  const rows = response?.rows?.slice(0, 12) ?? [];
  if (!response) return <LoadingPanel text={`Loading ${family} fitted-artifact importance...`} />;
  if (!response.ok || !rows.length) return <Unavailable title={`${family} diagnostic unavailable`} text={response.error ?? `The fitted ${family} artifact does not expose a supported model-specific diagnostic.`} />;
  const max = Math.max(...rows.map((row) => Math.abs(row.importance)), 1e-9);
  const title = family === "Gaussian Naive Bayes" ? "Feature likelihood contribution proxy" : family === "Neural Network" ? "Holdout permutation sensitivity" : "Feature importance from fitted artifact";
  return <div className="mt-4 grid gap-4 xl:grid-cols-[1.4fr_1fr]"><div className="rounded-md border bg-white p-4"><div className="text-sm font-semibold">{title}</div><div className="mt-3 space-y-2">{rows.map((row) => <div key={row.feature} className="grid grid-cols-[180px_minmax(0,1fr)_72px] items-center gap-3 text-xs"><div className="truncate font-medium" title={row.feature}>{row.feature}</div><div className="h-3 rounded bg-slate-100"><div className="h-3 rounded bg-violet-500" style={{ width: `${Math.abs(row.importance) / max * 100}%` }} /></div><div className="text-right font-mono">{row.importance.toFixed(4)}</div></div>)}</div></div><div className="rounded-md border bg-white p-4"><MetricTile label="Method" value={response.method ?? "Fitted artifact"} /><div className="mt-3 grid gap-2">{parameters.slice(0, 7).map((row) => <div key={row.parameter} className="flex justify-between gap-3 border-b pb-1 text-xs"><span className="text-slate-500">{row.parameter}</span><span className="font-semibold">{row.value}</span></div>)}</div></div></div>;
}

function ThresholdDashboard({
  metrics,
  curves,
  lift,
}: {
  metrics: ThresholdMetrics;
  curves: Curves | null;
  lift?: NonNullable<CommandCenter["lift"]>;
}) {
  return <div data-testid="threshold-live-metrics" className="space-y-4">
    <div className="grid gap-4 xl:grid-cols-[1.05fr_1.05fr_0.9fr]">
      <ChartCard title="Probability of Event Distribution" badge={`Threshold ${metrics.threshold.toFixed(3)}`}>
        <ProbabilityDistributionChart lift={lift} threshold={metrics.threshold} />
      </ChartCard>
      <ChartCard title="Final Holdout ROC" badge="Reporting only">
        <InteractiveRocChart curves={curves} metrics={metrics} />
      </ChartCard>
      <ChartCard title={`Confusion Matrix @ ${metrics.threshold.toFixed(3)}`} badge="Reporting only">
        <ConfusionMatrix matrix={metrics.confusion} />
      </ChartCard>
    </div>
    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
      <MetricTile label={`Precision @ ${metrics.threshold.toFixed(3)}`} value={formatPercent(metrics.precision)} />
      <MetricTile label={`Recall @ ${metrics.threshold.toFixed(3)}`} value={formatPercent(metrics.recall)} />
      <MetricTile label={`F1 @ ${metrics.threshold.toFixed(3)}`} value={formatMetric(metrics.f1)} />
      <MetricTile label={`False-positive rate @ ${metrics.threshold.toFixed(3)}`} value={formatPercent(metrics.false_positive_rate)} />
      <MetricTile label="Fraud capture" value={formatPercent(metrics.fraud_capture)} />
      <MetricTile label="Predicted positives" value={metrics.predicted_positives.toLocaleString()} />
      <MetricTile label="Review volume" value={metrics.review_volume.toLocaleString()} />
      <MetricTile label="False positives" value={metrics.false_positives.toLocaleString()} />
      <MetricTile label="False negatives" value={metrics.false_negatives.toLocaleString()} />
      <MetricTile label="Expected alert rate" value={formatPercent(metrics.expected_alert_rate)} />
    </div>
  </div>;
}

function ProbabilityDistributionChart({ lift, threshold }: { lift?: NonNullable<CommandCenter["lift"]>; threshold: number }) {
  const rows = lift?.deciles?.slice().sort((a, b) => a.mean_score - b.mean_score) ?? [];
  if (!rows.length) {
    return <Unavailable title="Score distribution unavailable" text="No validation score bands were returned for this model." compact />;
  }
  const width = 520;
  const height = 275;
  const pad = 42;
  const maxN = Math.max(...rows.map((row) => row.n), 1);
  const minScore = Math.min(0, ...rows.map((row) => Number.isFinite(row.min_score) ? row.min_score : row.mean_score));
  const maxScore = Math.max(1, ...rows.map((row) => Number.isFinite(row.max_score) ? row.max_score : row.mean_score));
  const xForScore = (value: number) => pad + ((value - minScore) / (maxScore - minScore || 1)) * (width - pad * 1.5);
  const barWidth = ((width - pad * 1.5) / rows.length) * 0.78;
  const chartBottom = height - pad;
  const chartTop = 26;
  const chartHeight = chartBottom - chartTop;
  const thresholdX = xForScore(threshold);
  return <svg viewBox={`0 0 ${width} ${height}`} className="h-[260px] w-full" role="img" aria-label="Probability distribution by event outcome">
    <rect width={width} height={height} rx="6" fill="#f8fafc" />
    {[0, 0.25, 0.5, 0.75, 1].map((tick) => <g key={tick}>
      <line x1={pad} y1={chartBottom - tick * chartHeight} x2={width - 28} y2={chartBottom - tick * chartHeight} stroke="#e2e8f0" />
      <text x={22} y={chartBottom - tick * chartHeight + 3} textAnchor="middle" fontSize="9" fill="#64748b">{Math.round(tick * maxN).toLocaleString()}</text>
    </g>)}
    {rows.map((row, index) => {
      const x = xForScore(row.mean_score) - barWidth / 2;
      const totalHeight = (row.n / maxN) * chartHeight;
      const positiveHeight = (row.positives / maxN) * chartHeight;
      const negativeHeight = Math.max(0, totalHeight - positiveHeight);
      return <g key={row.decile}>
        <rect x={x} y={chartBottom - negativeHeight} width={barWidth} height={negativeHeight} rx="2" fill="#93c5fd" opacity="0.85" />
        <rect x={x} y={chartBottom - totalHeight} width={barWidth} height={positiveHeight} rx="2" fill="#f97316" opacity="0.9" />
        {index % 3 === 0 ? <text x={x + barWidth / 2} y={height - 15} textAnchor="middle" fontSize="9" fill="#64748b">{row.mean_score.toFixed(2)}</text> : null}
      </g>;
    })}
    <line x1={thresholdX} y1={chartTop} x2={thresholdX} y2={chartBottom} stroke="#0f172a" strokeWidth="2" />
    <text x={Math.min(width - 80, Math.max(80, thresholdX))} y={18} textAnchor="middle" fontSize="10" fontWeight="700" fill="#0f172a">Threshold {threshold.toFixed(3)}</text>
    <text x={width / 2} y={height - 2} textAnchor="middle" fontSize="10" fill="#475569">Predicted probability of event</text>
    <text x="13" y={height / 2} textAnchor="middle" fontSize="10" fill="#475569" transform={`rotate(-90 13 ${height / 2})`}>Records</text>
    <g transform={`translate(${width - 155} 34)`}>
      <rect width="10" height="10" fill="#93c5fd" /><text x="16" y="9" fontSize="10" fill="#475569">Non-event</text>
      <rect x="76" width="10" height="10" fill="#f97316" /><text x="92" y="9" fontSize="10" fill="#475569">Event</text>
    </g>
  </svg>;
}

function InteractiveRocChart({ curves, metrics }: { curves: Curves | null; metrics: ThresholdMetrics }) {
  const width = 520;
  const height = 275;
  const pad = 42;
  const fpr = curves?.roc?.fpr ?? [];
  const tpr = curves?.roc?.tpr ?? [];
  const sourcePoints = fpr.length && tpr.length
    ? fpr.map((value, index) => ({ fpr: clamp01(value), tpr: clamp01(tpr[index] ?? 0), threshold: clampThreshold(1 - value) }))
    : [];
  const points = sourcePoints.length
    ? sourcePoints
    : [{ fpr: 0, tpr: 0, threshold: 0.99 }, { fpr: metrics.false_positive_rate, tpr: metrics.recall, threshold: metrics.threshold }, { fpr: 1, tpr: 1, threshold: 0.01 }];
  const sorted = points.slice().sort((a, b) => a.fpr - b.fpr);
  const sx = (value: number) => pad + clamp01(value) * (width - pad * 1.35);
  const sy = (value: number) => height - pad - clamp01(value) * (height - pad * 1.35);
  const active = sorted.reduce((best, point) => {
    const distance = Math.hypot(point.fpr - metrics.false_positive_rate, point.tpr - metrics.recall);
    const bestDistance = Math.hypot(best.fpr - metrics.false_positive_rate, best.tpr - metrics.recall);
    return distance < bestDistance ? point : best;
  }, sorted[0]);
  const line = sorted.map((point) => `${sx(point.fpr)},${sy(point.tpr)}`).join(" ");
  return <svg viewBox={`0 0 ${width} ${height}`} className="h-[260px] w-full select-none" role="img" aria-label="Final holdout ROC reporting curve">
    <rect width={width} height={height} rx="6" fill="#f8fafc" />
    {[0, 0.25, 0.5, 0.75, 1].map((tick) => <g key={tick}>
      <line x1={sx(tick)} y1={pad / 2} x2={sx(tick)} y2={height - pad} stroke="#e2e8f0" />
      <line x1={pad} y1={sy(tick)} x2={width - pad / 2} y2={sy(tick)} stroke="#e2e8f0" />
      <text x={sx(tick)} y={height - 22} textAnchor="middle" fontSize="10" fill="#64748b">{tick.toFixed(2)}</text>
    </g>)}
    <line x1={sx(0)} y1={sy(0)} x2={sx(1)} y2={sy(1)} stroke="#94a3b8" strokeDasharray="5 5" />
    <polyline points={line} fill="none" stroke="#0f766e" strokeWidth="3" strokeLinejoin="round" />
    <line x1={sx(active.fpr)} y1={sy(0)} x2={sx(active.fpr)} y2={sy(active.tpr)} stroke="#334155" strokeDasharray="4 4" />
    <line x1={sx(0)} y1={sy(active.tpr)} x2={sx(active.fpr)} y2={sy(active.tpr)} stroke="#334155" strokeDasharray="4 4" />
    <circle cx={sx(active.fpr)} cy={sy(active.tpr)} r="7" fill="#ffffff" stroke="#0f766e" strokeWidth="3" />
    <text x={Math.min(width - 140, sx(active.fpr) + 12)} y={Math.max(18, sy(active.tpr) - 10)} fontSize="10" fontWeight="700" fill="#0f172a">FPR {formatPercent(active.fpr)} | TPR {formatPercent(active.tpr)}</text>
    <text x={width / 2} y={height - 5} textAnchor="middle" fontSize="11" fill="#475569">False positive rate</text>
    <text x="13" y={height / 2} textAnchor="middle" fontSize="11" fill="#475569" transform={`rotate(-90 13 ${height / 2})`}>True positive rate</text>
  </svg>;
}

function clamp01(value: number) {
  return Math.max(0, Math.min(1, Number.isFinite(value) ? value : 0));
}

function clampThreshold(value: number) {
  return Math.max(0.01, Math.min(0.99, Number.isFinite(value) ? value : 0.5));
}

function LiftGainCapture({ lift }: { lift: NonNullable<CommandCenter["lift"]> }) {
  const points = lift.deciles.map((row) => ({ x: row.population_rate, capture: row.capture_rate, gain: row.capture_rate, cumulativeLift: row.population_rate ? row.capture_rate / row.population_rate : 0 }));
  return <div className="mt-5 rounded-md border border-indigo-200 bg-white p-4" data-testid="lift-gain-capture"><div className="flex items-center justify-between"><div><div className="text-xs font-semibold uppercase text-indigo-700">Lift, Gain, and Capture</div><h3 className="mt-1 text-base font-semibold">Population concentration analysis</h3></div>{statusPill(`Natural event rate ${formatPercent(lift.base_rate)}`)}</div><div className="mt-4 grid gap-4 xl:grid-cols-3"><ChartCard title="Cumulative Lift"><SimpleAnalyticChart points={points.map((row) => ({ x: row.x, y: row.cumulativeLift }))} color="#4f46e5" yLabel="Lift" /></ChartCard><ChartCard title="Cumulative Gain"><SimpleAnalyticChart points={points.map((row) => ({ x: row.x, y: row.gain }))} color="#0f766e" yLabel="Gain" /></ChartCard><ChartCard title="Capture Curve"><SimpleAnalyticChart points={points.map((row) => ({ x: row.x, y: row.capture }))} color="#ea580c" yLabel="Capture" /></ChartCard></div><div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">{Object.entries(lift.top_capture).map(([label, row]) => <div key={label} className="rounded-md border border-slate-200 bg-slate-50 p-3"><div className="text-[10px] font-semibold uppercase text-slate-500">Top {label}</div><div className="mt-1 text-lg font-semibold">{formatPercent(row.capture_rate)} captured</div><div className="mt-1 text-xs text-slate-600">Lift {row.lift.toFixed(2)} | {row.events.toLocaleString()} events</div></div>)}</div><div className="mt-4 max-h-72 overflow-auto rounded-md border"><table className="w-full text-xs"><thead className="sticky top-0 bg-slate-100 text-left uppercase text-slate-600"><tr><th className="px-3 py-2">Decile</th><th className="px-3 py-2">Rows</th><th className="px-3 py-2">Events</th><th className="px-3 py-2">Event rate</th><th className="px-3 py-2">Lift</th><th className="px-3 py-2">Capture</th><th className="px-3 py-2">Mean score</th></tr></thead><tbody>{lift.deciles.map((row) => <tr key={row.decile} className="border-t"><td className="px-3 py-2 font-semibold">{row.decile}</td><td className="px-3 py-2">{row.n.toLocaleString()}</td><td className="px-3 py-2">{row.positives.toLocaleString()}</td><td className="px-3 py-2">{formatPercent(row.event_rate)}</td><td className="px-3 py-2">{row.lift.toFixed(2)}</td><td className="px-3 py-2">{formatPercent(row.capture_rate)}</td><td className="px-3 py-2">{row.mean_score.toFixed(4)}</td></tr>)}</tbody></table></div></div>;
}

function SimpleAnalyticChart({ points, color, yLabel }: { points: Array<{ x: number; y: number }>; color: string; yLabel: string }) {
  if (!points.length) return <Unavailable title="Chart unavailable" text="No decile evidence was returned." compact />;
  const width = 420, height = 220, pad = 38, maxY = Math.max(1, ...points.map((p) => p.y));
  const sx = (v: number) => pad + v * (width - pad * 1.4), sy = (v: number) => height - pad - (v / maxY) * (height - pad * 1.5);
  const line = [`${sx(0)},${sy(0)}`, ...points.map((point) => `${sx(point.x)},${sy(point.y)}`)].join(" ");
  return <svg viewBox={`0 0 ${width} ${height}`} className="h-[210px] w-full"><rect width={width} height={height} rx="6" fill="#f8fafc" /><line x1={pad} y1={height - pad} x2={width - 16} y2={height - pad} stroke="#94a3b8" /><line x1={pad} y1={15} x2={pad} y2={height - pad} stroke="#94a3b8" /><polyline points={line} fill="none" stroke={color} strokeWidth="3" /><text x={width / 2} y={height - 7} textAnchor="middle" fontSize="10" fill="#475569">Population fraction</text><text x="12" y={height / 2} textAnchor="middle" fontSize="10" fill="#475569" transform={`rotate(-90 12 ${height / 2})`}>{yLabel}</text></svg>;
}

function DatasetRoleCard({ title, role, status, metrics, tone }: { title: string; role: string; status: string; metrics: Array<{ label: string; value: string }>; tone: "slate" | "blue" | "amber" }) {
  const style = tone === "blue" ? "border-blue-200 bg-blue-50" : tone === "amber" ? "border-amber-200 bg-amber-50" : "border-slate-200 bg-slate-50";
  return <article className={`rounded-md border p-4 ${style}`}><div className="flex items-start justify-between gap-2"><div><div className="text-xs font-semibold uppercase text-slate-600">{role}</div><h3 className="mt-1 text-lg font-semibold text-slate-950">{title}</h3></div>{statusPill(status, /available/i.test(status) && !/not/i.test(status) ? "good" : "warn")}</div><div className="mt-4 grid grid-cols-2 gap-2">{metrics.map((metric) => <MetricTile key={metric.label} label={metric.label} value={metric.value} />)}</div></article>;
}

function CalibrationChart({ rows }: { rows: Array<{ predicted: number; observed: number; n: number }> }) {
  return <CurveChart x={rows.map((row) => row.predicted)} y={rows.map((row) => row.observed)} xLabel="Mean predicted probability" yLabel="Observed event rate" color="#059669" diagonal />;
}

function LeaderboardRow({ model, rank, active, compared, selectionMetricName, locked, canInterpret, onReview, onCompare, onInterpret }: { model: RankedRow; rank: number; active: boolean; compared: boolean; selectionMetricName: string; locked: boolean; canInterpret: boolean; onReview: () => void; onCompare: () => void; onInterpret: () => void }) {
  const metric = verifiedSelectionMetric(model, selectionMetricName)!;
  const actions = <div className="flex gap-1"><button type="button" className="atlas-icon-button" title={locked ? "Review locked candidate" : "Final holdout is restricted to the locked candidate"} onClick={onReview} disabled={!locked}><Activity size={15} /></button><button type="button" className={`atlas-icon-button ${compared ? "text-emerald-700" : ""}`} title={compared ? "Remove from Comparison" : "Add selection evidence to Comparison"} onClick={onCompare}>{compared ? <Check size={15} /> : <GitCompareArrows size={15} />}</button><button type="button" className="atlas-icon-button" title={canInterpret ? "Open Interpretation" : "Complete Evaluation for the locked candidate before Interpretation"} onClick={onInterpret} disabled={!canInterpret}><ArrowRight size={15} /></button></div>;
  return <tr className={active ? "bg-blue-50" : "bg-white"}>
    <td className="px-3 py-3 font-semibold">{rank}</td>
    <td className="px-3 py-3"><div className="font-semibold text-slate-950">{cleanModelName(model.name)}</div>{rank === 1 ? <div className="mt-1 text-[10px] font-semibold uppercase text-emerald-700">Frozen selection leader</div> : null}</td>
    <td className="px-3 py-3 text-slate-600">{modelFamily(model)}</td>
    <td className="px-3 py-3"><div className="font-mono font-semibold">{formatMetric(metric.value)}</div><div className="text-[10px] uppercase text-slate-500">{metric.name}</div></td>
    <td className="px-3 py-3 text-slate-600">{formatSelectionSource(metric.source)}<div className="text-[10px] text-slate-500">{metric.partition_id}</div></td>
    <td className="px-3 py-3 text-slate-600">{metric.fold_count ? `${metric.fold_count} folds` : "Governed validation"}<div className="text-[10px] text-slate-500">std. dev. {formatMetric(metric.standard_deviation)}</div></td>
    <td className="px-3 py-3">{locked ? statusPill("Locked", "good") : statusPill("Challenger")}</td>
    <td className="px-3 py-3">{actions}</td>
  </tr>;
}

function AnomalyDiagnostics({ models }: { models: RankedRow[] }) {
  return <div className="mt-5 rounded-md border border-amber-200 bg-amber-50 p-4" data-testid="supplemental-anomaly-diagnostics"><div className="flex items-center gap-2"><ShieldCheck size={17} className="text-amber-700" /><div><div className="text-xs font-semibold uppercase text-amber-700">Supplemental Anomaly Diagnostics</div><h3 className="text-base font-semibold text-slate-950">Targetless models remain separate and are never champion-eligible</h3></div></div><div className="mt-3 grid gap-3 md:grid-cols-2">{models.map((model) => <div key={model.key} className="rounded-md border border-amber-200 bg-white p-3"><div className="font-semibold">{cleanModelName(model.name)}</div><div className="mt-1 text-xs text-slate-600">Supervised benchmark metrics are shown only when recorded. This model cannot enter the Interpretation comparison tray or be treated as a provisional leader.</div><div className="mt-2 flex gap-2">{statusPill("Diagnostic only", "warn")}{statusPill(`ROC-AUC ${formatMetric(model.auc)}`)}</div></div>)}</div></div>;
}

function ComparisonRow({ model, rank, selectionMetricName, locked, canInterpret, onRemove, onOpen }: { model: RankedRow; rank: number; selectionMetricName: string; locked: boolean; canInterpret: boolean; onRemove: () => void; onOpen: () => void }) {
  const metric = verifiedSelectionMetric(model, selectionMetricName)!;
  const metricTiles = <><MiniMetric label={metric.name} value={formatMetric(metric.value)} /><MiniMetric label="Selection source" value={formatSelectionSource(metric.source)} /><MiniMetric label="Selection partition" value={metric.partition_id} /><MiniMetric label="Fold evidence" value={metric.fold_count ? `${metric.fold_count} folds` : "Governed validation"} /><MiniMetric label="Std. deviation" value={formatMetric(metric.standard_deviation)} /><MiniMetric label="Threshold source" value={metric.threshold_source} /><MiniMetric label="Calibration source" value={metric.calibration_source} /><MiniMetric label="Decision" value={locked ? "Locked candidate" : "Challenger"} /></>;
  return <article className="rounded-md border border-violet-200 bg-white p-4"><div className="flex items-start justify-between gap-2"><div><div className="text-[10px] font-semibold uppercase text-violet-700">Frozen selection rank {rank}</div><h3 className="mt-1 font-semibold text-slate-950">{cleanModelName(model.name)}</h3></div><button type="button" className="atlas-icon-button" title="Remove from Comparison" onClick={onRemove}><Trash2 size={15} /></button></div><div className="mt-3 grid grid-cols-4 gap-2 text-xs">{metricTiles}</div><button type="button" className="atlas-primary-button mt-3" onClick={onOpen} disabled={!canInterpret} title={canInterpret ? "Open the exact evaluated locked candidate." : "Final-holdout Interpretation is restricted to the locked candidate with a verified Evaluation package."}>Open Interpretation <ArrowRight size={15} /></button></article>;
}

function MiniMetric({ label, value }: { label: string; value: string }) {
  return <div className="min-w-0 rounded bg-slate-50 p-2"><div className="text-[9px] font-semibold uppercase text-slate-500">{label}</div><div className="mt-0.5 truncate font-semibold" title={value}>{value}</div></div>;
}

function LoadingPanel({ text }: { text: string }) {
  return <div className="mt-4 flex min-h-28 items-center justify-center gap-2 rounded-md border border-slate-200 bg-slate-50 text-sm text-slate-600"><RefreshCw size={16} className="animate-spin" />{text}</div>;
}

function Unavailable({ title, text, compact = false }: { title: string; text: string; compact?: boolean }) {
  return <div className={`rounded-md border border-dashed border-slate-300 bg-slate-50 p-4 ${compact ? "min-h-40" : "mt-4 min-h-28"}`}><div className="font-semibold text-slate-800">{title}</div><p className="mt-1 text-sm leading-5 text-slate-600">{text}</p></div>;
}
