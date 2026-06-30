import { useEffect, useMemo, useState } from "react";
import { useLocation } from "react-router-dom";
import {
  AlertTriangle,
  BrainCircuit,
  CheckCircle2,
  HelpCircle,
  Lightbulb,
  ListChecks,
  ShieldAlert,
} from "lucide-react";
import { getAdaptiveRecommendations } from "../lib/adaptiveWorkflow";
import { logDecision } from "../lib/decisionJournal";
import { loadExperiments, type ExperimentRecord } from "../lib/experimentTracking";
import { inferLocalProblemType, loadLocalDataset } from "../lib/localDataset";
import { loadModelingMode, type ModelingMode } from "../lib/modelingMode";
import { hasGovernanceRegulation, loadProjectContext, type ProjectContext } from "../lib/projectContext";
import { useWorkflowStore } from "../state/useWorkflowStore";

const API_BASE =
  (import.meta.env.VITE_API_BASE as string | undefined)?.replace(/\/$/, "") ||
  "http://127.0.0.1:8001/api";

const OUTLIER_CONFIG_KEY = "modeling-tool-outlier-methods";
const CHALLENGE_MODE_KEY = "modeling-tool-challenge-mode";

type TrainingSummary = {
  problem_type?: "classification" | "regression";
  ranked?: Array<{
    key: string;
    name: string;
    auc?: number;
    pr_auc?: number;
    f1?: number;
    rmse?: number;
    mae?: number;
    r2?: number;
  }>;
};

type CopilotContext = {
  route: string;
  routeLabel: string;
  mode: ModelingMode;
  completedSteps: number;
  problemType: "classification" | "regression" | null;
  rowCount: number;
  target: string | null;
  eventRate: number | null;
  selectedColumnCount: number;
  hasStandardizedVariables: boolean;
  hasPcaLikeNames: boolean;
  amountOutlierFeature: string | null;
  amountOutlierMethod: string | null;
  balanceMethod: string | null;
  splitStrategy: string | null;
  trainingSummary: TrainingSummary | null;
  projectContext: ProjectContext;
};

type CopilotItem = {
  kind: "observation" | "recommendation" | "warning" | "explanation" | "default";
  title: string;
  body: string;
  why: string;
  confidence: number;
};

type ChallengeItem = {
  id: string;
  subject: string;
  title: string;
  body: string;
  recommendation: string;
  why: string;
  confidence: number;
};

function readOutlierConfig() {
  try {
    const parsed = JSON.parse(localStorage.getItem(OUTLIER_CONFIG_KEY) || "{}");
    return parsed && typeof parsed === "object" ? (parsed as Record<string, string>) : {};
  } catch {
    return {};
  }
}

function eventRateForTarget(rows: Record<string, unknown>[], target: string | null) {
  if (!target || !rows.length) return null;
  const values = rows.map((row) => row[target]).filter((value) => value !== null && value !== undefined && String(value).trim() !== "");
  if (!values.length) return null;
  const numeric = values.map((value) => Number(value));
  const numericCount = numeric.filter(Number.isFinite).length;
  if (numericCount / values.length >= 0.8) {
    const positives = numeric.filter((value) => value === 1).length;
    const zeros = numeric.filter((value) => value === 0).length;
    if (positives + zeros >= values.length * 0.8) return positives / Math.max(1, positives + zeros);
  }
  const counts = new Map<string, number>();
  values.forEach((value) => counts.set(String(value), (counts.get(String(value)) ?? 0) + 1));
  const sorted = Array.from(counts.values()).sort((a, b) => a - b);
  return sorted.length > 1 ? sorted[0] / values.length : null;
}

function numericStats(values: unknown[]) {
  const nums = values.map((value) => Number(value)).filter(Number.isFinite);
  if (nums.length < 20) return null;
  const mean = nums.reduce((sum, value) => sum + value, 0) / nums.length;
  const variance = nums.reduce((sum, value) => sum + (value - mean) ** 2, 0) / Math.max(1, nums.length - 1);
  return { mean, std: Math.sqrt(variance) };
}

function detectStandardizedVariables(rows: Record<string, unknown>[], headers: string[], target: string | null) {
  if (!rows.length) return false;
  const numericHeaders = headers.filter((header) => header !== target).slice(0, 30);
  const standardized = numericHeaders.filter((header) => {
    const stats = numericStats(rows.slice(0, 1000).map((row) => row[header]));
    if (!stats) return false;
    return Math.abs(stats.mean) < 0.25 && stats.std > 0.65 && stats.std < 1.35;
  });
  return standardized.length >= Math.max(4, Math.ceil(numericHeaders.length * 0.45));
}

function detectPcaLikeNames(headers: string[], target: string | null) {
  const featureHeaders = headers.filter((header) => header !== target);
  const pcaLike = featureHeaders.filter((header) => /^V\d+$/i.test(header) || /^PC[A]?\d+$/i.test(header));
  return pcaLike.length >= Math.max(4, Math.ceil(featureHeaders.length * 0.35));
}

function routeLabel(pathname: string) {
  const labels: Record<string, string> = {
    "/workbench": "AI Workbench",
    "/experiments": "Experiment Comparison",
    "/journal": "Decision Journal",
    "/governance-report": "Governance Report",
    "/notebook-export": "Notebook Export",
    "/dashboard": "Atlas Home",
    "/step00": "Project Context",
    "/step01": "Data Acquisition",
    "/step01b": "Credit Bureau Data Review",
    "/step02": "EDA",
    "/step03": "Outliers",
    "/step04": "Missing Values",
    "/step05": "Feature Engineering",
    "/step06": "Balance & Split",
    "/step07": "Model Training",
    "/step08": "Evaluation",
    "/step09": "Interpretation",
    "/step10": "Scoring",
    "/step11": "Model Development Document",
  };
  return labels[pathname] ?? "Workflow";
}

function buildContext(route: string, completedSteps: number, trainingSummary: TrainingSummary | null): CopilotContext {
  const dataset = loadLocalDataset();
  const target = dataset?.target ?? null;
  const rows = dataset?.rows ?? [];
  const headers = dataset?.headers ?? [];
  const outlierConfig = readOutlierConfig();
  const amountFeature = Object.keys(outlierConfig).find((feature) => /amount|balance|income|payment|loan/i.test(feature));
  const projectContext = loadProjectContext();

  return {
    route,
    routeLabel: routeLabel(route),
    mode: loadModelingMode(),
    completedSteps,
    problemType: inferLocalProblemType(dataset),
    rowCount: rows.length,
    target,
    eventRate: eventRateForTarget(rows, target),
    selectedColumnCount: dataset?.selected_columns?.length ?? 0,
    hasStandardizedVariables: detectStandardizedVariables(rows, headers, target),
    hasPcaLikeNames: detectPcaLikeNames(headers, target),
    amountOutlierFeature: amountFeature ?? null,
    amountOutlierMethod: amountFeature ? outlierConfig[amountFeature] ?? null : null,
    balanceMethod: localStorage.getItem("balanceMethod"),
    splitStrategy: localStorage.getItem("splitStrategy"),
    trainingSummary,
    projectContext,
  };
}

function metricForComparison(experiment: ExperimentRecord, fallbackMetric?: string) {
  const preferred = fallbackMetric?.toLowerCase() ?? "";
  if (/pr/.test(preferred)) return experiment.metrics.pr_auc;
  if (/f1/.test(preferred)) return experiment.metrics.f1;
  if (/recall/.test(preferred)) return experiment.metrics.recall;
  if (/precision/.test(preferred)) return experiment.metrics.precision;
  if (/rmse/.test(preferred)) return experiment.metrics.rmse === undefined ? undefined : -experiment.metrics.rmse;
  if (/mae/.test(preferred)) return experiment.metrics.mae === undefined ? undefined : -experiment.metrics.mae;
  if (/r-?squared|r2/.test(preferred)) return experiment.metrics.r2;
  return experiment.metrics.auc ?? experiment.metrics.pr_auc ?? experiment.metrics.f1 ?? experiment.metrics.r2;
}

function hasTimeDependencySignal(context: CopilotContext) {
  const dataset = loadLocalDataset();
  const hasTimeColumn = (dataset?.headers ?? []).some((header) => /time|date|month|year|vintage|period|window/i.test(header));
  const hasWindowDefinition = Boolean(context.projectContext.observationWindow || context.projectContext.performanceWindow);
  return hasTimeColumn || hasWindowDefinition || ["fraud", "credit risk", "collections", "AML/KYC"].includes(context.projectContext.modelType);
}

function buildChallengeItems(context: CopilotContext): ChallengeItem[] {
  const challenges: ChallengeItem[] = [];
  const experiments = loadExperiments();
  const primaryMetric = context.projectContext.primarySuccessMetric;

  if (
    context.problemType === "classification" &&
    context.eventRate !== null &&
    context.eventRate < 0.01 &&
    /accuracy/i.test(primaryMetric)
  ) {
    challenges.push({
      id: "rare-event-accuracy",
      subject: "Primary success metric",
      title: "Challenge: Accuracy is likely misleading",
      body: `The event rate is approximately ${(context.eventRate * 100).toFixed(2)}%, but Accuracy is selected as the primary metric.`,
      recommendation: "Use PR-AUC, recall, lift, capture rate, calibration, and threshold analysis as primary rare-event evidence.",
      why: "A model can achieve very high accuracy by predicting the majority class while missing the event cases.",
      confidence: 0.97,
    });
  }

  const champion = experiments.find((experiment) => experiment.champion);
  const randomForest = experiments.find((experiment) => /random forest/i.test(experiment.modelType));
  if (champion && randomForest && /decision tree/i.test(champion.modelType)) {
    const championMetric = metricForComparison(champion, primaryMetric);
    const rfMetric = metricForComparison(randomForest, primaryMetric);
    const materialGap =
      championMetric !== undefined &&
      rfMetric !== undefined &&
      Number.isFinite(championMetric) &&
      Number.isFinite(rfMetric) &&
      rfMetric > championMetric + Math.max(0.02, Math.abs(championMetric) * 0.05);
    if (materialGap) {
      challenges.push({
        id: "decision-tree-underperforms-rf",
        subject: "Champion model",
        title: "Challenge: Champion underperforms a challenger",
        body: `Decision Tree is more interpretable, but Random Forest materially outperforms it on the selected comparison metric.`,
        recommendation: "Document why interpretability, latency, policy, or reason-code needs justify the Decision Tree champion.",
        why: "Model governance needs a clear champion/challenger rationale when a simpler model is selected despite lower performance.",
        confidence: 0.88,
      });
    }
  }

  if (context.amountOutlierFeature && context.amountOutlierMethod && !/none|no action/i.test(context.amountOutlierMethod)) {
    challenges.push({
      id: "amount-outlier-capping",
      subject: context.amountOutlierFeature,
      title: "Challenge: Amount outliers may contain risk signal",
      body: `${context.amountOutlierFeature} uses ${context.amountOutlierMethod} outlier handling.`,
      recommendation: "Confirm that capped amount-like values are data-quality issues rather than valid high-risk behavior.",
      why: "Fraud, credit, balance, income, payment, and transaction tails can be highly predictive.",
      confidence: 0.9,
    });
  }

  if (context.splitStrategy === "holdout" && hasTimeDependencySignal(context)) {
    challenges.push({
      id: "random-split-time-dependent",
      subject: "Split strategy",
      title: "Challenge: Random split may not represent future performance",
      body: "The project or dataset appears time-dependent, but the workflow is using a holdout split.",
      recommendation: "Consider a time-based split or OOT validation to better approximate production scoring.",
      why: "Random splits can leak temporal patterns and overstate performance when policy, population, fraud patterns, or macro conditions drift.",
      confidence: 0.82,
    });
  }

  return challenges.slice(0, 4);
}

export function buildCopilotRecommendations(context: CopilotContext): CopilotItem[] {
  const items: CopilotItem[] = [];
  const champion = context.trainingSummary?.ranked?.[0];

  if (!context.projectContext.projectName.trim() || !context.projectContext.businessObjective.trim()) {
    items.push({
      kind: "recommendation",
      title: "Complete the project context first",
      body: "Define the project name, business objective, intended use, target, population, costs, and governance environment before locking modeling choices.",
      why: "A regulated model cannot be evaluated only as a technical artifact; success metrics, thresholds, explainability, and documentation need to trace back to business use.",
      confidence: 0.97,
    });
  }

  if (!context.rowCount) {
    items.push({
      kind: "recommendation",
      title: "Start by loading the development dataset",
      body: "No active dataset is visible to the Copilot. Load a CSV and select the target before making preprocessing or modeling decisions.",
      why: "Every downstream recommendation depends on the target, sample size, feature schema, and target distribution.",
      confidence: 0.98,
    });
    return items;
  }

  items.push({
    kind: "observation",
    title: `${context.routeLabel} context detected`,
    body: `${context.rowCount.toLocaleString()} cached rows, ${context.selectedColumnCount || "unknown"} selected features, target ${context.target ?? "not selected"}, project type ${context.projectContext.modelType}.`,
    why: "Atlas Guide uses the active workflow state so guidance stays tied to what the user is doing now.",
    confidence: 0.9,
  });

  if (context.mode === "advanced") {
    items.push({
      kind: "recommendation",
      title: "Power-user mode active",
      body: "Use editable Python, experiment comparison, notebook export, and governance reports while keeping the guided workflow state intact.",
      why: "Advanced users need custom logic, but regulated model development still requires traceable decisions and reproducible outputs.",
      confidence: 0.9,
    });
  } else {
    items.push({
      kind: "recommendation",
      title: "Guided mode active",
      body: "Continue through the visual workflow with defaults, explanations, guardrails, and adaptive skip recommendations.",
      why: "Guided progression reduces missed controls while still allowing a user to move into power-user tools when needed.",
      confidence: 0.9,
    });
  }

  if (context.route === "/step00") {
    items.push({
      kind: "explanation",
      title: "Project context becomes the control plane",
      body: "The model type, target definition, population, windows, costs, regulations, and deployment expectation will influence downstream recommendations.",
      why: "This creates a documented line from business purpose to data preparation, model selection, evaluation, interpretation, and production readiness.",
      confidence: 0.95,
    });
  }

  if (context.route === "/step01") {
    items.push({
      kind: "recommendation",
      title: "Capture source metadata with the dataset",
      body: "Use the Data Access module to preserve source type, connection, query, sampling method, dataset version, lineage, and data quality findings before modeling begins.",
      why: "In regulated lending, validation needs to trace the final model dataset back to the governed source and extraction logic.",
      confidence: 0.95,
    });
    if (context.projectContext.regulatoryEnvironment.some((item) => ["Fair Lending", "FCRA", "ECOA", "SR 11-7", "OCC", "internal governance"].includes(item))) {
      items.push({
        kind: "warning",
        title: "Governance environment requires source traceability",
        body: "Document query filters, join logic, sampling, and potential leakage fields before importing the modeling population.",
        why: "Data lineage and reproducible extraction logic are core evidence for model validation and audit review.",
        confidence: 0.92,
      });
    }
  }

  if (context.route === "/step01b") {
    items.push({
      kind: "warning",
      title: "Bureau special values need separate treatment",
      body: "Credit bureau values such as -1, -2, -7, 96, 97, 98, 99, 996, and 999 often mean unavailable, not applicable, thin file, or suppressed rather than ordinary numeric values.",
      why: "Treating bureau special values as normal numbers, simple missing values, or outliers can distort model relationships and create weak documentation for validation.",
      confidence: 0.94,
    });
  }

  if (context.route === "/step11") {
    items.push({
      kind: "recommendation",
      title: "Finalize documentation after champion selection",
      body: "Refresh the model development document after scoring, champion selection, and any rationale edits in the Decision Journal.",
      why: "The document should represent the final governed modeling decision, not an intermediate experiment state.",
      confidence: 0.9,
    });
  }

  if (hasGovernanceRegulation(context.projectContext)) {
    items.push({
      kind: "warning",
      title: "Governance documentation will be expected",
      body: `Selected governance context: ${context.projectContext.regulatoryEnvironment.join(", ")}.`,
      why: "SR 11-7, OCC, Fair Lending, FCRA, ECOA, and internal governance expectations usually require traceable decisions, challenger evidence, stability testing, and explainability.",
      confidence: 0.91,
    });
  }

  if (context.projectContext.regulatoryEnvironment.some((item) => ["Fair Lending", "FCRA", "ECOA"].includes(item))) {
    items.push({
      kind: "recommendation",
      title: "Add fair lending and adverse-action readiness",
      body: "Prioritize interpretable variables, retain reason-code evidence, review protected-class proxy risk, and document exclusions.",
      why: "Consumer lending models tied to credit eligibility or treatment need defensible explanations and disparate-impact review.",
      confidence: 0.9,
    });
  }

  if (context.projectContext.interpretabilityRequirement === "high") {
    items.push({
      kind: "default",
      title: "Suggested model set for high interpretability",
      body: "Include Logistic Regression, Decision Tree, and EBM if available; use nonlinear models as challengers unless performance lift is material.",
      why: "High interpretability requirements usually make variable transparency, monotonic reasoning, and reason-code support more important than marginal metric gains.",
      confidence: 0.86,
    });
  }

  if (context.projectContext.deploymentExpectation === "real-time API") {
    items.push({
      kind: "warning",
      title: "Real-time deployment needs operational checks",
      body: "Keep preprocessing deterministic, monitor latency, export the full pipeline, and validate missing-value behavior on scoring data.",
      why: "Real-time lending decisions fail in production when training transformations are not reproducible at scoring time.",
      confidence: 0.88,
    });
  }

  if (context.projectContext.falsePositiveCost || context.projectContext.falseNegativeCost) {
    items.push({
      kind: "recommendation",
      title: "Use cost-aware threshold review",
      body: "Translate false-positive and false-negative costs into threshold scenarios before final model selection.",
      why: "The best statistical threshold is not always the best business threshold when the two error types have asymmetric cost.",
      confidence: 0.84,
    });
  }

  if (context.projectContext.primarySuccessMetric.trim()) {
    items.push({
      kind: "default",
      title: "Use the declared success metric as the ranking anchor",
      body: `Primary metric: ${context.projectContext.primarySuccessMetric}. Secondary metrics: ${context.projectContext.secondaryMetrics || "not specified"}.`,
      why: "Pre-declaring success metrics reduces hindsight bias when comparing candidate models.",
      confidence: 0.82,
    });
  }

  if (
    context.problemType === "classification" &&
    ((context.eventRate !== null && context.eventRate < 0.01) || ["fraud", "AML/KYC"].includes(context.projectContext.modelType))
  ) {
    items.push({
      kind: "observation",
      title: "Rare-event classification problem",
      body:
        context.eventRate !== null
          ? `The target event rate is approximately ${(context.eventRate * 100).toFixed(2)}%.`
          : `${context.projectContext.modelType} projects often behave like rare-event classification problems.`,
      why: "At this prevalence, a model can look accurate while failing to find the event cases the business cares about.",
      confidence: 0.96,
    });
    items.push({
      kind: "warning",
      title: "Accuracy will be misleading",
      body: "Use PR-AUC, recall, lift, capture rate, and calibration alongside ROC-AUC.",
      why: "Consumer lending adverse outcomes and fraud-like events are often sparse; ranking and threshold behavior matter more than raw accuracy.",
      confidence: 0.95,
    });
    items.push({
      kind: "default",
      title: "Suggested default balancing",
      body: "Try class weights, undersampling, or SMOTE and compare lift/calibration before final model selection.",
      why: "Balancing can improve learning on minority events, but the final score scale still needs calibration and validation.",
      confidence: 0.88,
    });
  }

  if (context.hasStandardizedVariables || context.hasPcaLikeNames) {
    items.push({
      kind: "observation",
      title: "Variables appear standardized or PCA-like",
      body: context.hasPcaLikeNames
        ? "Many feature names look like V1/V2 or PCA components."
        : "Many numeric variables have mean near zero and standard deviation near one.",
      why: "Additional scaling may be unnecessary and can make governance documentation harder if transformations are duplicated.",
      confidence: context.hasPcaLikeNames ? 0.92 : 0.82,
    });
    items.push({
      kind: "recommendation",
      title: "Review scaling before adding more transformations",
      body: "If these are already engineered or PCA-reduced fields, keep a data dictionary and avoid redundant scaling unless a model requires it.",
      why: "Regulated model reviews need traceable transformations and clear explanations of derived variables.",
      confidence: 0.84,
    });
  }

  if (context.amountOutlierMethod) {
    items.push({
      kind: "warning",
      title: "Review amount capping before applying it",
      body: `An amount-like feature has an outlier method selected (${context.amountOutlierMethod}).`,
      why: "Transaction amount, loan amount, income, payment, or balance fields can contain meaningful risk signal in the tails.",
      confidence: 0.86,
    });
  }

  if (context.route === "/step04") {
    items.push({
      kind: "default",
      title: "Suggested imputation defaults",
      body: "Use median for numeric variables, mode or explicit Missing category for categoricals, and document any high-missingness exclusions.",
      why: "Simple, stable imputation is easier to validate and explain in lending model governance.",
      confidence: 0.8,
    });
  }

  if (context.route === "/step07") {
    items.push({
      kind: "recommendation",
      title: "Train interpretable and challenger models",
      body: "Include at least one transparent model and one nonlinear challenger, then compare performance, explainability, and operational complexity.",
      why: "Champion selection should show why the selected model is worth its complexity under model risk review.",
      confidence: 0.87,
    });
  }

  if (context.route === "/step08" && champion) {
    items.push({
      kind: "explanation",
      title: "Champion diagnostics should drive the next decision",
      body: `Current leading model appears to be ${champion.name}. Check threshold behavior, residuals or lift, and stability before interpretation.`,
      why: "The best aggregate metric is not always the safest lending model; diagnostics expose implementation risk.",
      confidence: 0.78,
    });
  }

  if (context.route === "/step09") {
    items.push({
      kind: "recommendation",
      title: "Tie RFE to documentation",
      body: "Use the RFE recommendation as a candidate parsimonious model, then document why retained variables are acceptable and useful.",
      why: "A smaller variable set can reduce governance burden, but only if performance and stability remain defensible.",
      confidence: 0.88,
    });
  }

  if (context.route === "/step10") {
    items.push({
      kind: "warning",
      title: "OOT stability is a production readiness gate",
      body: "Review PSI/VSI and score distribution shifts before accepting final scoring outputs.",
      why: "A model can perform well on holdout data but fail if the OOT population has drifted.",
      confidence: 0.9,
    });
  }

  if (context.problemType === "regression") {
    items.push({
      kind: "recommendation",
      title: "Focus on residual behavior",
      body: "Review RMSE, MAE, R-squared, adjusted R-squared, residual bias, and high-error segments.",
      why: "For continuous lending targets, average error can hide systematic underprediction or overprediction in important segments.",
      confidence: 0.88,
    });
  }

  return items.slice(0, 7);
}

function iconFor(kind: CopilotItem["kind"]) {
  if (kind === "warning") return AlertTriangle;
  if (kind === "recommendation") return ListChecks;
  if (kind === "default") return Lightbulb;
  if (kind === "explanation") return HelpCircle;
  return CheckCircle2;
}

function kindClass(kind: CopilotItem["kind"]) {
  if (kind === "warning") return "border-amber-200 bg-amber-50 text-amber-900";
  if (kind === "recommendation") return "border-blue-200 bg-blue-50 text-blue-900";
  if (kind === "default") return "border-violet-200 bg-violet-50 text-violet-900";
  if (kind === "explanation") return "border-slate-200 bg-slate-50 text-slate-800";
  return "border-emerald-200 bg-emerald-50 text-emerald-900";
}

function confidenceScore(items: CopilotItem[]) {
  if (!items.length) return 0;
  const average = items.reduce((sum, item) => sum + item.confidence, 0) / items.length;
  return Math.round(average * 100);
}

export default function CopilotCard() {
  const location = useLocation();
  const steps = useWorkflowStore((state) => state.steps);
  const [trainingSummary, setTrainingSummary] = useState<TrainingSummary | null>(null);
  const [challengeMode, setChallengeMode] = useState(() => localStorage.getItem(CHALLENGE_MODE_KEY) === "true");
  const [overrideReasons, setOverrideReasons] = useState<Record<string, string>>({});
  const [savedChallenges, setSavedChallenges] = useState<Record<string, string>>({});

  useEffect(() => {
    fetch(`${API_BASE}/train/last`)
      .then((res) => res.json())
      .then((data) => setTrainingSummary(data?.summary ?? null))
      .catch(() => setTrainingSummary(null));
  }, [location.pathname]);

  const completedSteps = Object.entries(steps).filter(([key, status]) => key !== "dashboard" && status === "completed").length;
  const context = buildContext(location.pathname, completedSteps, trainingSummary);
  const challenges = challengeMode ? buildChallengeItems(context) : [];
  const adaptiveItems = getAdaptiveRecommendations(location.pathname).map((recommendation): CopilotItem => ({
    kind: recommendation.kind === "warning" ? "warning" : recommendation.kind === "default" ? "default" : "recommendation",
    title: recommendation.headline,
    body: `${recommendation.explanation} ${recommendation.suggestedAction}`,
    why: recommendation.why,
    confidence: recommendation.confidence,
  }));
  const items = [...adaptiveItems, ...buildCopilotRecommendations(context)].slice(0, 9);
  const confidence = confidenceScore(items);

  const toggleChallengeMode = (enabled: boolean) => {
    setChallengeMode(enabled);
    localStorage.setItem(CHALLENGE_MODE_KEY, String(enabled));
    logDecision({
      workflowStep: context.routeLabel,
      actionType: "workflow_setting_changed",
      subject: "Challenge Mode",
      previousValue: challengeMode ? "enabled" : "disabled",
      newValue: enabled ? "enabled" : "disabled",
      systemRecommendation: "Enable Challenge Mode when model governance should explicitly challenge risky or questionable decisions.",
      followStatus: "not_applicable",
    });
  };

  const saveChallengeResponse = (challenge: ChallengeItem, followStatus: "followed" | "overrode") => {
    const reason = overrideReasons[challenge.id]?.trim() ?? "";
    if (followStatus === "overrode" && !reason) {
      setSavedChallenges((current) => ({ ...current, [challenge.id]: "Override reason required." }));
      return;
    }
    logDecision({
      workflowStep: context.routeLabel,
      actionType: "challenge_response_recorded",
      subject: challenge.subject,
      previousValue: challenge.title,
      newValue: followStatus === "followed" ? "Accepted recommendation" : "Overrode recommendation",
      systemRecommendation: challenge.recommendation,
      followStatus,
      userReason: reason,
    });
    setSavedChallenges((current) => ({
      ...current,
      [challenge.id]: followStatus === "followed" ? "Accepted and saved to Decision Journal." : "Override saved to Decision Journal.",
    }));
  };

  const grouped = {
    observation: items.filter((item) => item.kind === "observation"),
    recommendation: items.filter((item) => item.kind === "recommendation"),
    warning: items.filter((item) => item.kind === "warning"),
    explanation: items.filter((item) => item.kind === "explanation"),
    default: items.filter((item) => item.kind === "default"),
  };

  return (
    <aside className="sticky top-24 max-h-[calc(100vh-7rem)] overflow-auto rounded-lg border border-slate-200/80 bg-white/90 p-4 shadow-sm">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <BrainCircuit size={18} className="text-slate-800" />
            <h2 className="text-sm font-semibold text-slate-950">Atlas Guide Recommendation</h2>
          </div>
          <p className="mt-1 text-xs leading-5 text-slate-500">Rule-based guide. LLM-ready interface.</p>
        </div>
        <div className="rounded-full border border-slate-200 bg-slate-50 px-2 py-1 text-xs font-semibold text-slate-700">
          {confidence}% confidence
        </div>
      </div>

      <label className="mt-4 flex cursor-pointer items-center justify-between gap-3 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2">
        <span>
          <span className="block text-xs font-semibold text-slate-900">Challenge Mode</span>
          <span className="block text-[11px] leading-4 text-slate-500">Challenge risky modeling decisions.</span>
        </span>
        <input
          type="checkbox"
          className="h-4 w-4 accent-slate-950"
          checked={challengeMode}
          onChange={(event) => toggleChallengeMode(event.target.checked)}
        />
      </label>

      <div className="mt-4 grid gap-2">
        <MiniContext label="Project" value={context.projectContext.projectName || "Not defined"} />
        <MiniContext label="Page" value={context.routeLabel} />
        <MiniContext label="Mode" value={context.mode === "advanced" ? "Power User" : "Guided"} />
        <MiniContext label="Task" value={context.problemType ?? context.projectContext.modelType ?? "Unknown"} />
        <MiniContext label="Target" value={context.target ?? "Not selected"} />
      </div>

      {challengeMode && <ChallengeSection challenges={challenges} reasons={overrideReasons} saved={savedChallenges} onReasonChange={setOverrideReasons} onSave={saveChallengeResponse} />}

      <div className="mt-4 space-y-4">
        <CopilotSection title="Observations" items={grouped.observation} />
        <CopilotSection title="Recommended Next Steps" items={grouped.recommendation} />
        <CopilotSection title="Warnings" items={grouped.warning} />
        <CopilotSection title="Explanations" items={grouped.explanation} />
        <CopilotSection title="Suggested Defaults" items={grouped.default} />
      </div>
    </aside>
  );
}

function ChallengeSection({
  challenges,
  reasons,
  saved,
  onReasonChange,
  onSave,
}: {
  challenges: ChallengeItem[];
  reasons: Record<string, string>;
  saved: Record<string, string>;
  onReasonChange: React.Dispatch<React.SetStateAction<Record<string, string>>>;
  onSave: (challenge: ChallengeItem, followStatus: "followed" | "overrode") => void;
}) {
  return (
    <section className="mt-4">
      <div className="flex items-center gap-2">
        <ShieldAlert size={15} className="text-rose-700" />
        <h3 className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">Challenge Mode</h3>
      </div>
      <div className="mt-2 grid gap-2">
        {challenges.length ? (
          challenges.map((challenge) => (
            <article key={challenge.id} className="rounded-lg border border-rose-200 bg-rose-50 p-3 text-rose-950">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="text-xs font-semibold">{challenge.title}</div>
                  <p className="mt-1 text-xs leading-5">{challenge.body}</p>
                  <p className="mt-2 text-[11px] leading-4 opacity-85">
                    <span className="font-semibold">Recommendation: </span>
                    {challenge.recommendation}
                  </p>
                  <p className="mt-1 text-[11px] leading-4 opacity-85">
                    <span className="font-semibold">Why this matters: </span>
                    {challenge.why}
                  </p>
                </div>
                <span className="shrink-0 rounded-full bg-white/70 px-2 py-0.5 text-[11px] font-semibold">
                  {Math.round(challenge.confidence * 100)}%
                </span>
              </div>

              <textarea
                className="mt-3 min-h-16 w-full rounded-lg border border-rose-200 bg-white px-2 py-2 text-xs text-slate-900 shadow-sm"
                value={reasons[challenge.id] ?? ""}
                onChange={(event) =>
                  onReasonChange((current) => ({
                    ...current,
                    [challenge.id]: event.target.value,
                  }))
                }
                placeholder="Override reason, if applicable..."
              />

              <div className="mt-2 flex flex-wrap items-center gap-2">
                <button
                  type="button"
                  className="rounded-lg bg-rose-900 px-2.5 py-1.5 text-xs font-semibold text-white hover:bg-rose-800"
                  onClick={() => onSave(challenge, "followed")}
                >
                  Accept Recommendation
                </button>
                <button
                  type="button"
                  className="rounded-lg border border-rose-300 bg-white px-2.5 py-1.5 text-xs font-semibold text-rose-900 hover:bg-rose-100"
                  onClick={() => onSave(challenge, "overrode")}
                >
                  Override with Reason
                </button>
                {saved[challenge.id] && <span className="text-[11px] font-semibold text-rose-800">{saved[challenge.id]}</span>}
              </div>
            </article>
          ))
        ) : (
          <div className="rounded-lg border border-slate-200 bg-slate-50 p-3 text-xs leading-5 text-slate-600">
            No active challenges for the current workflow state.
          </div>
        )}
      </div>
    </section>
  );
}

function MiniContext({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2">
      <div className="text-[10px] font-semibold uppercase tracking-wide text-slate-500">{label}</div>
      <div className="mt-0.5 truncate text-xs font-semibold text-slate-800" title={value}>
        {value}
      </div>
    </div>
  );
}

function CopilotSection({ title, items }: { title: string; items: CopilotItem[] }) {
  if (!items.length) return null;
  return (
    <section>
      <h3 className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">{title}</h3>
      <div className="mt-2 grid gap-2">
        {items.map((item) => {
          const Icon = iconFor(item.kind);
          return (
            <article key={`${item.kind}-${item.title}`} className={`rounded-lg border p-3 ${kindClass(item.kind)}`}>
              <div className="flex items-start gap-2">
                <Icon size={15} className="mt-0.5 shrink-0" />
                <div className="min-w-0">
                  <div className="text-xs font-semibold">{item.title}</div>
                  <p className="mt-1 text-xs leading-5">{item.body}</p>
                  <p className="mt-2 text-[11px] leading-4 opacity-80">
                    <span className="font-semibold">Why this matters: </span>
                    {item.why}
                  </p>
                </div>
              </div>
            </article>
          );
        })}
      </div>
    </section>
  );
}
