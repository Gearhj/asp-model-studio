import { type PointerEvent, useEffect, useMemo, useState } from "react";
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
import { inferLocalProblemType, loadLocalDataset } from "../lib/localDataset";
import {
  loadInterpretationCandidates,
  saveInterpretationCandidates,
  type InterpretationCandidate,
} from "../lib/interpretationCandidates";
import { useWorkflowStore } from "../state/useWorkflowStore";

const QUERY_API_BASE =
  typeof window !== "undefined" ? new URLSearchParams(window.location.search).get("apiBase")?.replace(/\/$/, "") : undefined;
const API_BASE =
  QUERY_API_BASE ||
  (import.meta.env.VITE_API_BASE as string | undefined)?.replace(/\/$/, "") ||
  "http://127.0.0.1:8001/api";
const LOCAL_TRAINING_SUMMARY_KEY = "modeling-tool-training-summary";
const LOCAL_SELECTED_INTERPRETATION_MODEL_KEY = "modeling-tool-selected-interpretation-model";

type Task = "classification" | "regression" | "anomaly";
type RankedRow = {
  key: string;
  name: string;
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
  evaluation_role?: string;
  test_status?: string;
  oot_status?: string;
  observation_count?: number;
  event_count?: number;
  event_rate?: number;
  threshold?: ThresholdMetrics;
  presets?: Record<string, number>;
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
  method?: string;
  sample_count?: number;
  rows?: Array<{ feature: string; importance: number; direction?: number; source?: string }>;
};
type DetailResponse = {
  ok: boolean;
  error?: string;
  kind?: string;
  intercept?: number;
  coefficients?: Array<{ feature: string; coefficient: number; odds_ratio?: number | null }>;
  message?: string;
};
type HyperparameterResponse = { ok: boolean; rows?: Array<{ parameter: string; value: string }>; best_score?: number | null };

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

function loadLocalRanked(): RankedRow[] {
  try {
    const parsed = JSON.parse(sessionStorage.getItem(LOCAL_TRAINING_SUMMARY_KEY) || "{}") as { ranked?: RankedRow[] };
    return Array.isArray(parsed.ranked) ? parsed.ranked : [];
  } catch {
    return [];
  }
}

function formatMetric(value?: number | null, digits = 4) {
  return typeof value === "number" && Number.isFinite(value) ? value.toFixed(digits) : "Not available";
}

function formatPercent(value?: number | null) {
  return typeof value === "number" && Number.isFinite(value) ? `${(value * 100).toFixed(1)}%` : "Not available";
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

function governingValue(model: RankedRow, problemType: "classification" | "regression") {
  return problemType === "regression" ? -(model.rmse ?? Number.POSITIVE_INFINITY) : model.pr_auc ?? Number.NEGATIVE_INFINITY;
}

function statusPill(label: string, tone: "good" | "warn" | "neutral" = "neutral") {
  const style = tone === "good" ? "border-emerald-200 bg-emerald-50 text-emerald-800" : tone === "warn" ? "border-amber-200 bg-amber-50 text-amber-800" : "border-slate-200 bg-slate-50 text-slate-600";
  return <span className={`inline-flex rounded-full border px-2 py-0.5 text-[11px] font-semibold ${style}`}>{label}</span>;
}

export default function Step08Evaluation() {
  const navigate = useNavigate();
  const projectId = useWorkflowStore((state) => state.projectId);
  const projectName = useWorkflowStore((state) => state.projectName);
  const [models, setModels] = useState<RankedRow[] | null>(null);
  const [selectedKey, setSelectedKey] = useState("");
  const [curves, setCurves] = useState<Curves | null>(null);
  const [command, setCommand] = useState<CommandCenter | null>(null);
  const [details, setDetails] = useState<DetailResponse | null>(null);
  const [importance, setImportance] = useState<ImportanceResponse | null>(null);
  const [hyperparameters, setHyperparameters] = useState<HyperparameterResponse | null>(null);
  const [tree, setTree] = useState<TreeResponse | null>(null);
  const [knn, setKnn] = useState<KnnResponse | null>(null);
  const [threshold, setThreshold] = useState(0.5);
  const [reviewCapacity, setReviewCapacity] = useState(10);
  const [comparison, setComparison] = useState<InterpretationCandidate[]>(() => loadInterpretationCandidates(projectId));
  const [message, setMessage] = useState("");
  const [loadingDiagnostics, setLoadingDiagnostics] = useState(false);

  const problemType = inferLocalProblemType(loadLocalDataset()) ?? "classification";
  const supervised = useMemo(() => (models ?? []).filter((model) => !isAnomaly(model)), [models]);
  const anomalyModels = useMemo(() => (models ?? []).filter(isAnomaly), [models]);
  const ordered = useMemo(
    () => supervised.slice().sort((a, b) => governingValue(b, problemType) - governingValue(a, problemType)),
    [problemType, supervised]
  );
  const topCandidates = ordered.slice(0, 3);
  const selectedModel = supervised.find((model) => model.key === selectedKey) ?? supervised[0] ?? null;
  const comparisonKeys = useMemo(() => new Set(comparison.map((candidate) => candidate.key)), [comparison]);

  useEffect(() => {
    setComparison(loadInterpretationCandidates(projectId));
    getJson<{ ok: boolean; summary?: { ranked?: RankedRow[] } }>(`${API_BASE}/train/last`)
      .then((response) => {
        const rows = response.summary?.ranked ?? [];
        const actual = rows.length ? rows : loadLocalRanked();
        setModels(actual);
        const saved = sessionStorage.getItem(`atlas-evaluation-review:${projectId}`) || "";
        setSelectedKey(actual.some((model) => model.key === saved && !isAnomaly(model)) ? saved : actual.find((model) => !isAnomaly(model))?.key ?? "");
      })
      .catch((error) => {
        const local = loadLocalRanked();
        setModels(local);
        setSelectedKey(local.find((model) => !isAnomaly(model))?.key ?? "");
        setMessage(local.length ? "Backend Evaluation service is unavailable. Showing persisted training metrics; detailed diagnostics remain unavailable." : String(error?.message ?? error));
      });
  }, [projectId]);

  useEffect(() => {
    if (!selectedKey) return;
    sessionStorage.setItem(`atlas-evaluation-review:${projectId}`, selectedKey);
    setLoadingDiagnostics(true);
    setCurves(null);
    setDetails(null);
    setImportance(null);
    setHyperparameters(null);
    setTree(null);
    setKnn(null);
    const family = modelFamily(selectedModel);
    const common = Promise.allSettled([
      getJson<Curves>(`${API_BASE}/eval/curves?model=${encodeURIComponent(selectedKey)}`),
      getJson<DetailResponse>(`${API_BASE}/interpretation/details?model=${encodeURIComponent(selectedKey)}`),
      getJson<ImportanceResponse>(`${API_BASE}/interpretation/importance?model=${encodeURIComponent(selectedKey)}`),
      getJson<HyperparameterResponse>(`${API_BASE}/interpretation/hyperparameters?model=${encodeURIComponent(selectedKey)}`),
    ]).then(([curveResult, detailResult, importanceResult, parameterResult]) => {
      setCurves(curveResult.status === "fulfilled" ? curveResult.value : { ok: false, error: String(curveResult.reason?.message ?? curveResult.reason) });
      setDetails(detailResult.status === "fulfilled" ? detailResult.value : { ok: false, error: String(detailResult.reason?.message ?? detailResult.reason) });
      setImportance(importanceResult.status === "fulfilled" ? importanceResult.value : { ok: false, error: String(importanceResult.reason?.message ?? importanceResult.reason) });
      setHyperparameters(parameterResult.status === "fulfilled" ? parameterResult.value : { ok: false, rows: [] });
    });
    const specific = family === "Decision Tree"
      ? getJson<TreeResponse>(`${API_BASE}/eval/tree?model=${encodeURIComponent(selectedKey)}&max_depth=4`).then(setTree).catch((error) => setTree({ ok: false, error: String(error?.message ?? error) }))
      : family === "K-Nearest Neighbors"
        ? getJson<KnnResponse>(`${API_BASE}/eval/knn_clusters?model=${encodeURIComponent(selectedKey)}&max_points=900`).then(setKnn).catch((error) => setKnn({ ok: false, error: String(error?.message ?? error) }))
        : Promise.resolve();
    Promise.allSettled([common, specific]).finally(() => setLoadingDiagnostics(false));
  }, [projectId, selectedKey]);

  useEffect(() => {
    if (!selectedKey || problemType !== "classification") {
      setCommand(null);
      return;
    }
    const timer = window.setTimeout(() => {
      getJson<CommandCenter>(`${API_BASE}/eval/command_center?model=${encodeURIComponent(selectedKey)}&threshold=${threshold}&review_capacity=${reviewCapacity / 100}`)
        .then(setCommand)
        .catch((error) => setCommand({ ok: false, error: String(error?.message ?? error) }));
    }, 120);
    return () => window.clearTimeout(timer);
  }, [problemType, reviewCapacity, selectedKey, threshold]);

  function selectForReview(model: RankedRow) {
    setSelectedKey(model.key);
    logDecision({
      workflowStep: "Evaluation",
      actionType: "workflow_setting_changed",
      subject: "Model under review",
      previousValue: selectedKey,
      newValue: model.key,
      systemRecommendation: "Review comparative performance, operating policy, model-specific evidence, and stability before final selection.",
    });
    window.requestAnimationFrame(() => document.getElementById("interactive-model-explorer")?.scrollIntoView({ behavior: "smooth", block: "start" }));
  }

  function setComparisonState(next: InterpretationCandidate[]) {
    const limited = next.slice(0, 4);
    saveInterpretationCandidates(projectId, limited);
    setComparison(limited);
  }

  function toggleComparison(model: RankedRow) {
    if (isAnomaly(model)) return;
    const exists = comparisonKeys.has(model.key);
    if (!exists && comparison.length >= 4) {
      setMessage("The comparison tray supports up to four supervised candidates. Remove a model before adding another.");
      return;
    }
    const next = exists
      ? comparison.filter((candidate) => candidate.key !== model.key)
      : [...comparison, { key: model.key, name: model.name, task: model.task, selectedAt: new Date().toISOString() }];
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
    const existing = candidates.some((candidate) => candidate.key === model.key);
    const next = existing ? candidates : [...candidates, { key: model.key, name: model.name, task: model.task, selectedAt: new Date().toISOString() }].slice(-4);
    setComparisonState(next);
    sessionStorage.setItem(LOCAL_SELECTED_INTERPRETATION_MODEL_KEY, model.key);
    navigate(`/step09?model=${encodeURIComponent(model.key)}&compare=${encodeURIComponent(next.map((candidate) => candidate.key).join(","))}`);
  }

  function openComparison() {
    const first = supervised.find((model) => model.key === comparison[0]?.key);
    if (!first) return;
    openInterpretation(first, comparison);
  }

  function applyPreset(key: string) {
    const value = command?.presets?.[key];
    if (typeof value === "number" && Number.isFinite(value)) setThreshold(value);
  }

  function saveProposedPolicy() {
    if (!command?.threshold) return;
    localStorage.setItem(`atlas-proposed-operating-policy:${projectId}`, JSON.stringify({
      modelKey: selectedKey,
      threshold: command.threshold.threshold,
      reviewCapacity: reviewCapacity / 100,
      metrics: command.threshold,
      savedAt: new Date().toISOString(),
      status: "proposed",
    }));
    setMessage(`Proposed operating policy saved at threshold ${command.threshold.threshold.toFixed(3)}. It has not been approved or applied.`);
  }

  const heroMetrics: AtlasWorkflowMetric[] = [
    { label: "Project", value: projectName || "Current project" },
    { label: "Supervised Candidates", value: String(supervised.length) },
    { label: "Governing Metric", value: problemType === "regression" ? "RMSE" : "PR-AUC" },
    { label: "TEST", value: command?.test_status ?? "Pending diagnostics", tone: command?.ok ? "success" : "warning" },
    { label: "OOT", value: command?.oot_status ?? "Not loaded", tone: "warning" },
    { label: "Comparison Tray", value: `${comparison.length}/4` },
  ];

  if (models === null) {
    return <StepShell title="Step 8: Evaluation Command Center" subtitle="Loading persisted model evidence." variant="modeling" heroMetrics={heroMetrics} nextDisabled><LoadingPanel text="Loading trained-model artifacts..." /></StepShell>;
  }

  if (!models.length || !supervised.length) {
    return (
      <StepShell title="Step 8: Evaluation Command Center" subtitle="A completed supervised training run is required." variant="modeling" heroMetrics={heroMetrics} nextDisabled nextDisabledReason="Train at least one supervised model before Evaluation.">
        <Unavailable title="No supervised evaluation artifacts" text="Return to Model Training, fit at least one champion-eligible supervised candidate, and then reopen Evaluation." />
      </StepShell>
    );
  }

  const leader = ordered[0];
  const active = selectedModel ?? leader;
  const metricLabel = problemType === "regression" ? "RMSE" : "PR-AUC";
  const metricValue = problemType === "regression" ? active.rmse : active.pr_auc;

  return (
    <StepShell
      title="Step 8: Evaluation Command Center"
      subtitle="Compare real fitted artifacts, test operating tradeoffs, and choose candidates for deeper Interpretation without implying final approval."
      variant="modeling"
      heroMetrics={heroMetrics}
      nextLabel="Continue to Interpretation Review"
      nextDisabled={!comparison.length}
      nextDisabledReason="Add at least one supervised model to the Interpretation comparison tray."
      nextStatusLine={`${comparison.length} interpretation candidate${comparison.length === 1 ? "" : "s"} preserved for the next review.`}
      onNextClick={() => openComparison()}
      showDeveloperTools={false}
    >
      <div className="space-y-5" data-testid="evaluation-command-center">
        {message ? <div className="rounded-md border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">{message}</div> : null}

        <section className="overflow-hidden rounded-md border border-slate-800 bg-slate-950 text-white" data-testid="atlas-performance-summary">
          <div className="grid gap-6 p-6 xl:grid-cols-[1.5fr_1fr]">
            <div>
              <div className="text-xs font-semibold uppercase text-emerald-300">A. ATLAS Performance Summary</div>
              <h2 className="mt-2 text-2xl font-semibold">{cleanModelName(leader.name)} is the current {metricLabel} leader</h2>
              <p className="mt-3 max-w-3xl text-sm leading-6 text-slate-300">
                Final model selection remains pending interpretation, operating-threshold review, TEST/OOT comparison, and governance review. No candidate has been automatically approved.
              </p>
              <div className="mt-5 flex flex-wrap gap-2">
                {statusPill(`Provisional Leader: ${cleanModelName(leader.name)}`, "good")}
                {statusPill(`TEST: ${command?.test_status ?? "Pending"}`, command?.ok ? "good" : "warn")}
                {statusPill(`OOT: ${command?.oot_status ?? "Not loaded"}`, "warn")}
              </div>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <DarkStat label="Governing metric" value={metricLabel} />
              <DarkStat label="Leader value" value={formatMetric(problemType === "regression" ? leader.rmse : leader.pr_auc)} />
              <DarkStat label="Strongest evidence" value="Governed holdout" />
              <DarkStat label="Next review" value="Interpretability + policy" />
            </div>
          </div>
          <div className="grid border-t border-slate-800 bg-slate-900/70 md:grid-cols-3">
            <SummaryBand label="What performed best" value={`${cleanModelName(leader.name)} currently leads on ${metricLabel}.`} />
            <SummaryBand label="Unresolved risk" value={command?.oot_status === "Not loaded" ? "OOT evidence has not been loaded." : "Review calibration and degradation flags."} />
            <SummaryBand label="Recommended action" value="Compare 2-4 candidates before final Interpretation and RFE." />
          </div>
        </section>

        <section className="rounded-md border border-blue-200 bg-blue-50 p-5" data-testid="top-candidate-comparison">
          <SectionHeading eyebrow="B. Top Candidate Comparison" title="The strongest supervised candidates" description="Prominent cards summarize persisted training and holdout metrics. Rank is provisional and never constitutes approval." />
          <div className="mt-4 grid gap-4 xl:grid-cols-3">
            {topCandidates.map((model, index) => (
              <CandidateCard
                key={model.key}
                model={model}
                rank={index + 1}
                active={model.key === selectedKey}
                compared={comparisonKeys.has(model.key)}
                testStatus="Available"
                ootStatus="Not loaded"
                onReview={() => selectForReview(model)}
                onCompare={() => toggleComparison(model)}
                onInterpret={() => openInterpretation(model)}
              />
            ))}
          </div>
        </section>

        <section id="interactive-model-explorer" className="rounded-md border border-slate-200 bg-white p-5" data-testid="interactive-model-explorer">
          <div className="flex flex-wrap items-end justify-between gap-4">
            <SectionHeading eyebrow="C. Interactive Model Explorer" title="Model-specific analytical review" description="Changing the model updates every common and family-specific diagnostic from the fitted artifact." />
            <label className="grid min-w-72 gap-1 text-sm">
              <span className="text-xs font-semibold uppercase text-slate-500">Model under review</span>
              <select className="rounded-md border border-slate-300 bg-white px-3 py-2 font-semibold" value={selectedKey} onChange={(event) => setSelectedKey(event.target.value)}>
                {supervised.map((model) => <option key={model.key} value={model.key}>{cleanModelName(model.name)}</option>)}
              </select>
            </label>
          </div>
          <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <MetricTile label={metricLabel} value={formatMetric(metricValue)} />
            <MetricTile label="ROC-AUC" value={formatMetric(active.auc)} />
            <MetricTile label="Recall" value={formatMetric(curves?.metrics?.recall as number | undefined)} />
            <MetricTile label="Precision" value={formatMetric(curves?.metrics?.precision as number | undefined)} />
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
        </section>

        {problemType === "classification" ? (
          <section className="rounded-md border border-indigo-200 bg-indigo-50 p-5" data-testid="threshold-operating-policy">
            <SectionHeading eyebrow="D. Threshold and Operating Policy" title="Test operating tradeoffs before proposing a policy" description="Threshold changes are temporary. Metrics and the confusion matrix always display the active threshold." />
            <div className="mt-4 grid gap-5 xl:grid-cols-[330px_minmax(0,1fr)]">
              <div className="rounded-md border border-indigo-200 bg-white p-4">
                <label className="grid gap-2 text-sm font-semibold">
                  <span className="flex justify-between"><span>Decision threshold</span><span className="font-mono text-indigo-700">{threshold.toFixed(3)}</span></span>
                  <input aria-label="Decision threshold" type="range" min="0.01" max="0.99" step="0.01" value={threshold} onChange={(event) => setThreshold(Number(event.target.value))} />
                </label>
                <label className="mt-4 grid gap-1 text-sm">
                  <span className="font-semibold">Review capacity</span>
                  <div className="flex items-center gap-2"><input className="w-24 rounded-md border px-3 py-2" type="number" min="0.1" max="100" step="0.5" value={reviewCapacity} onChange={(event) => setReviewCapacity(Number(event.target.value))} /><span>% of population</span></div>
                </label>
                <div className="mt-4 grid grid-cols-2 gap-2">
                  <PresetButton label="Maximize F1" onClick={() => applyPreset("maximize_f1")} />
                  <PresetButton label="Target Recall" onClick={() => applyPreset("target_recall")} />
                  <PresetButton label="Target Precision" onClick={() => applyPreset("target_precision")} />
                  <PresetButton label="Review Capacity" onClick={() => applyPreset("review_capacity")} />
                  <PresetButton label="Governed Threshold" onClick={() => applyPreset("current_governed")} />
                  <PresetButton label="Custom" onClick={() => undefined} active />
                </div>
                <button type="button" className="atlas-primary-button mt-4 w-full" onClick={saveProposedPolicy} disabled={!command?.threshold}>Save as Proposed Operating Policy</button>
                <p className="mt-2 text-xs leading-5 text-slate-500">Saving records a proposed policy only. It does not approve or apply the threshold.</p>
              </div>
              <div>
                {command?.ok && command.threshold ? (
                  <ThresholdDashboard
                    curves={curves}
                    lift={command.lift}
                    metrics={command.threshold}
                    onThresholdChange={setThreshold}
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
            <DatasetRoleCard title="Internal Validation" role="Model development evidence" status={active.best_score != null ? "Available" : "Not recorded"} metrics={[{ label: "Search score", value: formatMetric(active.best_score) }, { label: "Scope", value: "Training only" }]} tone="slate" />
            <DatasetRoleCard title="TEST" role="Governed holdout evaluation" status={command?.test_status ?? (curves?.ok ? "Available" : "Not available")} metrics={[{ label: metricLabel, value: formatMetric(metricValue) }, { label: "Observations", value: command?.observation_count?.toLocaleString() ?? "Not available" }]} tone="blue" />
            <DatasetRoleCard title="OOT" role="Out-of-time stability evaluation" status={command?.oot_status ?? "Not loaded"} metrics={[{ label: "Performance", value: "Not evaluated" }, { label: "Degradation", value: "Not evaluated" }]} tone="amber" />
          </div>
        </section>

        <section className="rounded-md border border-emerald-200 bg-emerald-50 p-5" data-testid="stability-calibration">
          <SectionHeading eyebrow="F. Stability and Calibration" title="Probability quality and evidence degradation" description="Calibration is computed from real governed holdout scores. OOT metrics remain unavailable until an OOT artifact is loaded." />
          <div className="mt-4 grid gap-4 xl:grid-cols-[1.35fr_1fr]">
            <ChartCard title="Reliability Curve" badge="Predicted vs observed">
              {command?.calibration?.rows?.length ? <CalibrationChart rows={command.calibration.rows} /> : <Unavailable title="Calibration unavailable" text={command?.error ?? "No classification calibration rows were returned."} compact />}
            </ChartCard>
            <div className="grid gap-3 sm:grid-cols-2">
              <MetricTile label="Brier score" value={formatMetric(command?.calibration?.brier_score)} />
              <MetricTile label="Calibration method" value={command?.calibration?.method ?? active.calibration_method ?? "Not applied"} />
              <MetricTile label="Calibration slope" value={formatMetric(command?.calibration?.slope)} />
              <MetricTile label="Calibration intercept" value={formatMetric(command?.calibration?.intercept)} />
              <MetricTile label="TEST role" value={command?.test_status ?? "Not available"} />
              <MetricTile label="OOT role" value={command?.oot_status ?? "Not loaded"} />
            </div>
          </div>
        </section>

        <section className="rounded-md border border-slate-200 bg-white p-5" data-testid="full-leaderboard">
          <div className="flex flex-wrap items-end justify-between gap-3">
            <SectionHeading eyebrow="G. Full Leaderboard" title="All supervised candidates" description="Use row actions to review evidence, open Interpretation directly, or manage the persistent comparison tray." />
            <div>{statusPill(`${supervised.length} supervised candidates`)}</div>
          </div>
          <div className="mt-4 overflow-x-auto rounded-md border border-slate-200">
            <table className="min-w-[1120px] w-full text-sm">
              <thead className="bg-slate-100 text-left text-[11px] font-semibold uppercase text-slate-600"><tr><th className="px-3 py-3">Rank</th><th className="px-3 py-3">Model</th><th className="px-3 py-3">Family</th><th className="px-3 py-3">PR-AUC</th><th className="px-3 py-3">ROC-AUC</th><th className="px-3 py-3">Recall</th><th className="px-3 py-3">Precision</th><th className="px-3 py-3">KS</th><th className="px-3 py-3">Calibration</th><th className="px-3 py-3">Actions</th></tr></thead>
              <tbody className="divide-y divide-slate-100">
                {ordered.map((model, index) => <LeaderboardRow key={model.key} model={model} rank={index + 1} active={model.key === selectedKey} compared={comparisonKeys.has(model.key)} onReview={() => selectForReview(model)} onCompare={() => toggleComparison(model)} onInterpret={() => openInterpretation(model)} />)}
              </tbody>
            </table>
          </div>
          {anomalyModels.length ? <AnomalyDiagnostics models={anomalyModels} /> : null}
        </section>

        <section className="rounded-md border border-violet-200 bg-violet-50 p-5" data-testid="interpretation-comparison-tray">
          <div className="flex flex-wrap items-end justify-between gap-3">
            <SectionHeading eyebrow="H. Interpretation Comparison Tray" title="Persistent candidate review set" description="Keep two to four candidates for side-by-side Interpretation. A single candidate can still be opened directly." />
            <div className="flex gap-2"><button type="button" className="atlas-secondary-button" onClick={() => setComparisonState([])} disabled={!comparison.length}><Trash2 size={15} /> Clear Comparison</button><button type="button" className="atlas-primary-button" onClick={openComparison} disabled={comparison.length < 2}><GitCompareArrows size={15} /> Compare Selected Models</button></div>
          </div>
          <div className="mt-4 grid gap-3 xl:grid-cols-2">
            {comparison.map((candidate) => {
              const model = supervised.find((row) => row.key === candidate.key);
              if (!model) return null;
              const rank = ordered.findIndex((row) => row.key === model.key) + 1;
              return <ComparisonRow key={model.key} model={model} rank={rank} onRemove={() => toggleComparison(model)} onOpen={() => openInterpretation(model)} />;
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

function CandidateCard({ model, rank, active, compared, testStatus, ootStatus, onReview, onCompare, onInterpret }: { model: RankedRow; rank: number; active: boolean; compared: boolean; testStatus: string; ootStatus: string; onReview: () => void; onCompare: () => void; onInterpret: () => void }) {
  return <article className={`rounded-md border bg-white p-5 shadow-sm ${active ? "border-blue-500 ring-2 ring-blue-100" : "border-blue-200"}`} data-model-key={model.key}>
    <div className="flex items-start justify-between gap-3"><div><div className="text-[11px] font-semibold uppercase text-blue-700">Provisional rank {rank}</div><h3 className="mt-1 text-lg font-semibold text-slate-950">{cleanModelName(model.name)}</h3><div className="mt-1 text-xs text-slate-500">{modelFamily(model)} | Interpretability {interpretability(model)}</div></div>{rank === 1 ? statusPill("Metric Leader", "good") : statusPill("Interpretation Candidate")}</div>
    <div className="mt-4 grid grid-cols-3 gap-2"><MetricTile label="PR-AUC" value={formatMetric(model.pr_auc)} /><MetricTile label="ROC-AUC" value={formatMetric(model.auc)} /><MetricTile label="KS" value={formatMetric(model.ks)} /><MetricTile label="Recall" value={formatMetric(model.recall)} /><MetricTile label="Precision" value={formatMetric(model.precision)} /><MetricTile label="F1" value={formatMetric(model.f1)} /></div>
    <div className="mt-3 grid grid-cols-2 gap-2 text-xs"><div className="rounded-md bg-slate-50 p-2"><span className="text-slate-500">Calibration</span><div className="mt-1 font-semibold">{model.calibration_method || (model.calibration_applied ? "Applied" : "Not applied")}</div></div><div className="rounded-md bg-slate-50 p-2"><span className="text-slate-500">Runtime</span><div className="mt-1 font-semibold">{model.runtime_ms != null ? `${(model.runtime_ms / 1000).toFixed(1)} s` : "Not recorded"}</div></div><div className="rounded-md bg-blue-50 p-2"><span className="text-blue-600">TEST</span><div className="mt-1 font-semibold text-blue-950">{testStatus}</div></div><div className="rounded-md bg-amber-50 p-2"><span className="text-amber-700">OOT</span><div className="mt-1 font-semibold text-amber-950">{ootStatus}</div></div></div>
    <div className="mt-4 flex flex-wrap gap-2"><button type="button" className="atlas-secondary-button" onClick={onReview}><Activity size={15} /> Review Model</button><button type="button" className="atlas-secondary-button" onClick={onCompare}>{compared ? <Check size={15} /> : <GitCompareArrows size={15} />}{compared ? "Remove from Comparison" : "Add to Comparison"}</button><button type="button" className="atlas-primary-button" onClick={onInterpret}>Open Interpretation <ArrowRight size={15} /></button></div>
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

function PresetButton({ label, onClick, active = false }: { label: string; onClick: () => void; active?: boolean }) {
  return <button type="button" className={`rounded-md border px-2 py-2 text-xs font-semibold ${active ? "border-indigo-300 bg-indigo-50 text-indigo-800" : "border-slate-200 bg-white text-slate-700 hover:border-indigo-300"}`} onClick={onClick}>{label}</button>;
}

function ThresholdDashboard({
  metrics,
  curves,
  lift,
  onThresholdChange,
}: {
  metrics: ThresholdMetrics;
  curves: Curves | null;
  lift?: NonNullable<CommandCenter["lift"]>;
  onThresholdChange: (threshold: number) => void;
}) {
  return <div data-testid="threshold-live-metrics" className="space-y-4">
    <div className="grid gap-4 xl:grid-cols-[1.05fr_1.05fr_0.9fr]">
      <ChartCard title="Probability of Event Distribution" badge={`Threshold ${metrics.threshold.toFixed(3)}`}>
        <ProbabilityDistributionChart lift={lift} threshold={metrics.threshold} />
      </ChartCard>
      <ChartCard title="Interactive ROC Operating Point" badge="Click or drag">
        <InteractiveRocChart curves={curves} metrics={metrics} onThresholdChange={onThresholdChange} />
      </ChartCard>
      <ChartCard title={`Confusion Matrix @ ${metrics.threshold.toFixed(3)}`} badge="Live">
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

function InteractiveRocChart({ curves, metrics, onThresholdChange }: { curves: Curves | null; metrics: ThresholdMetrics; onThresholdChange: (threshold: number) => void }) {
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
  const selectPoint = (event: PointerEvent<SVGSVGElement>) => {
    const rect = event.currentTarget.getBoundingClientRect();
    const viewX = ((event.clientX - rect.left) / rect.width) * width;
    const viewY = ((event.clientY - rect.top) / rect.height) * height;
    const fprAtPointer = clamp01((viewX - pad) / (width - pad * 1.35));
    const tprAtPointer = clamp01((height - pad - viewY) / (height - pad * 1.35));
    const nearest = sorted.reduce((best, point) => {
      const distance = Math.hypot(point.fpr - fprAtPointer, point.tpr - tprAtPointer);
      const bestDistance = Math.hypot(best.fpr - fprAtPointer, best.tpr - tprAtPointer);
      return distance < bestDistance ? point : best;
    }, active);
    onThresholdChange(Number(nearest.threshold.toFixed(2)));
  };
  return <svg viewBox={`0 0 ${width} ${height}`} className="h-[260px] w-full cursor-crosshair select-none" role="img" aria-label="Interactive ROC curve" onPointerDown={selectPoint} onPointerMove={(event) => { if (event.buttons === 1) selectPoint(event); }}>
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

function LeaderboardRow({ model, rank, active, compared, onReview, onCompare, onInterpret }: { model: RankedRow; rank: number; active: boolean; compared: boolean; onReview: () => void; onCompare: () => void; onInterpret: () => void }) {
  return <tr className={active ? "bg-blue-50" : "bg-white"}><td className="px-3 py-3 font-semibold">{rank}</td><td className="px-3 py-3"><div className="font-semibold text-slate-950">{cleanModelName(model.name)}</div>{rank === 1 ? <div className="mt-1 text-[10px] font-semibold uppercase text-emerald-700">Current metric leader</div> : null}</td><td className="px-3 py-3 text-slate-600">{modelFamily(model)}</td><td className="px-3 py-3 font-mono">{formatMetric(model.pr_auc)}</td><td className="px-3 py-3 font-mono">{formatMetric(model.auc)}</td><td className="px-3 py-3 font-mono">{formatMetric(model.recall)}</td><td className="px-3 py-3 font-mono">{formatMetric(model.precision)}</td><td className="px-3 py-3 font-mono">{formatMetric(model.ks)}</td><td className="px-3 py-3">{model.calibration_method || (model.calibration_applied ? "Applied" : "Not applied")}</td><td className="px-3 py-3"><div className="flex gap-1"><button type="button" className="atlas-icon-button" title="Review Model" onClick={onReview}><Activity size={15} /></button><button type="button" className={`atlas-icon-button ${compared ? "text-emerald-700" : ""}`} title={compared ? "Remove from Comparison" : "Add to Comparison"} onClick={onCompare}>{compared ? <Check size={15} /> : <GitCompareArrows size={15} />}</button><button type="button" className="atlas-icon-button" title="Open Interpretation" onClick={onInterpret}><ArrowRight size={15} /></button></div></td></tr>;
}

function AnomalyDiagnostics({ models }: { models: RankedRow[] }) {
  return <div className="mt-5 rounded-md border border-amber-200 bg-amber-50 p-4" data-testid="supplemental-anomaly-diagnostics"><div className="flex items-center gap-2"><ShieldCheck size={17} className="text-amber-700" /><div><div className="text-xs font-semibold uppercase text-amber-700">Supplemental Anomaly Diagnostics</div><h3 className="text-base font-semibold text-slate-950">Targetless models remain separate and are never champion-eligible</h3></div></div><div className="mt-3 grid gap-3 md:grid-cols-2">{models.map((model) => <div key={model.key} className="rounded-md border border-amber-200 bg-white p-3"><div className="font-semibold">{cleanModelName(model.name)}</div><div className="mt-1 text-xs text-slate-600">Supervised benchmark metrics are shown only when recorded. This model cannot enter the Interpretation comparison tray or be treated as a provisional leader.</div><div className="mt-2 flex gap-2">{statusPill("Diagnostic only", "warn")}{statusPill(`ROC-AUC ${formatMetric(model.auc)}`)}</div></div>)}</div></div>;
}

function ComparisonRow({ model, rank, onRemove, onOpen }: { model: RankedRow; rank: number; onRemove: () => void; onOpen: () => void }) {
  return <article className="rounded-md border border-violet-200 bg-white p-4"><div className="flex items-start justify-between gap-2"><div><div className="text-[10px] font-semibold uppercase text-violet-700">Provisional rank {rank}</div><h3 className="mt-1 font-semibold text-slate-950">{cleanModelName(model.name)}</h3></div><button type="button" className="atlas-icon-button" title="Remove from Comparison" onClick={onRemove}><Trash2 size={15} /></button></div><div className="mt-3 grid grid-cols-4 gap-2 text-xs"><MiniMetric label="PR-AUC" value={formatMetric(model.pr_auc)} /><MiniMetric label="ROC-AUC" value={formatMetric(model.auc)} /><MiniMetric label="Recall" value={formatMetric(model.recall)} /><MiniMetric label="Precision" value={formatMetric(model.precision)} /><MiniMetric label="KS" value={formatMetric(model.ks)} /><MiniMetric label="Calibration" value={model.calibration_method || "Not applied"} /><MiniMetric label="TEST" value="Available" /><MiniMetric label="OOT" value="Not loaded" /></div><button type="button" className="atlas-primary-button mt-3" onClick={onOpen}>Open Interpretation <ArrowRight size={15} /></button></article>;
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
