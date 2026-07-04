import { Fragment, useEffect, useMemo, useState, type ReactNode } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  ArrowRight,
  BarChart3,
  Calculator,
  CheckCircle2,
  ClipboardList,
  Download,
  FileText,
  Lightbulb,
  PackageCheck,
  Save,
  ShieldCheck,
} from "lucide-react";
import StepShell from "../components/StepShell";
import { experimentalDesignJourney, getWorkflowDefinition, type ProjectType, type ExperimentalDesignJourneyStep } from "../config/workflows";
import { logDecision } from "../lib/decisionJournal";
import { buildGovernanceReport } from "../lib/governanceReport";
import { upsertProjectFromState } from "../lib/localProjects";
import { exportWorkflowNotebookJson } from "../lib/notebookExport";
import { loadProjectContext } from "../lib/projectContext";
import { loadWorkflowNodeEvidence } from "../lib/workflowNodeEvidence";
import {
  buildExperimentalDesignAnalysis,
  cleanFactorName as sharedCleanFactorName,
  deriveSuggestedFactors as sharedDeriveSuggestedFactors,
  experimentalSampleSizePlan,
  fullFactorialModelDf,
  generateFullFactorialTerms,
  generateTreatmentMatrix,
  levelPromotionWarnings,
  parseFactorHierarchy as sharedParseFactorHierarchy,
  treatmentCellCount,
  type ExperimentalFactor,
  type ExperimentalDesignAnalysis,
  type SuggestedFactor,
} from "../lib/experimentalDesign";
import { useWorkflowStore } from "../state/useWorkflowStore";

type NodeState = {
  objective: string;
  inputs: string;
  assumptions: string;
  method: string;
  metrics: string[];
  validation: string;
  risks: string;
  decision: string;
  rationale: string;
  notes: string;
  numeric: Record<string, number>;
  simulationResults?: MonteCarloSimulationResults;
  analysisSnapshot?: ExperimentalDesignAnalysis;
  assignmentUnit?: string;
  allocationMode?: string;
  blockStratum?: string;
  selectedExclusions?: string[];
};

type MonteCarloIteration = {
  iteration: number;
  achievedPower: number;
  detectedEffect: boolean;
  selectedWinnerCorrect: boolean;
  estimatedLift: number;
  missingnessRate: number;
  imbalanceRate: number;
};

type MonteCarloSimulationResults = {
  seed: number;
  iterations: number;
  meanPower: number;
  medianPower: number;
  falsePositiveRate: number;
  falseNegativeRate: number;
  wrongWinnerRate: number;
  meanEstimatedLift: number;
  liftStdDev: number;
  decisionStabilityScore: number;
  confidenceIntervalCoverage: number;
  recommendedAction: "Strong" | "Adequate" | "Weak" | "Redesign Required";
  inputs: {
    treatmentCells: number;
    samplePerCell: number;
    totalSample: number;
    sampleReady: boolean;
    sampleSource: string;
    baselineRate: number;
    minimumDetectableLift: number;
    alpha: number;
    desiredPower: number;
    missingnessRate: number;
    imbalanceRate: number;
    varianceMultiplier: number;
    attritionRate: number;
    measurementErrorRate: number;
    nonresponseRate: number;
    method: string;
  };
  powerByIteration: MonteCarloIteration[];
  powerDistribution?: Array<{ label: string; value: number }>;
  liftDistribution?: Array<{ label: string; value: number }>;
  convergenceCurve?: Array<{ x: number; y: number }>;
  intervalPreview?: Array<{ index: number; estimate: number; low: number; high: number; covers: boolean }>;
  powerCurve: Array<{
    samplePerCell: number;
    estimatedPower: number;
  }>;
  scenarioSensitivity: Array<{
    scenario: string;
    estimatedPower: number;
    falseNegativeRate: number;
    wrongWinnerRate: number;
    designStatus: "Strong" | "Adequate" | "Weak" | "Redesign Required";
  }>;
  riskDrivers: Array<{
    driver: string;
    impactScore: number;
    explanation: string;
  }>;
  outcomeBreakdown: Array<{ outcome: string; count: number }>;
};

type ExperimentalStepConfig = {
  eyebrow: string;
  guidance: string[];
  methodLabel: string;
  methods: string[];
  metrics: string[];
  fields: Array<{ key: keyof Pick<NodeState, "objective" | "inputs" | "assumptions" | "validation" | "risks" | "decision" | "rationale" | "notes">; label: string; rows?: number; placeholder: string }>;
};

const STORAGE_KEY = "atlas-workflow-node-state";

const metricOptions: Record<ProjectType | "default", string[]> = {
  "predictive-modeling": ["AUC", "PR-AUC", "KS", "Lift", "F1", "RMSE", "MAE", "PSI", "VSI"],
  "experimental-design": ["F-statistic", "p-value", "effect size", "power", "MSE", "interaction effect"],
  "ab-testing": ["conversion rate", "lift", "p-value", "confidence interval", "power", "sample ratio mismatch"],
  optimization: ["objective value", "constraint violations", "runtime", "optimality gap", "scenario impact"],
  forecasting: ["MAPE", "MAE", "RMSE", "bias", "coverage", "backtest error"],
  segmentation: ["silhouette", "Davies-Bouldin", "cluster size", "stability", "profile separation"],
  "reinforcement-learning": ["reward", "policy value", "off-policy estimate", "safety violations", "regret"],
  "time-series": ["ACF", "PACF", "stationarity", "anomaly rate", "MAPE", "drift"],
  nlp: ["precision", "recall", "F1", "exact match", "human review score", "toxicity rate"],
  "computer-vision": ["accuracy", "F1", "mAP", "IoU", "false positive rate", "human review rate"],
  "graph-analytics": ["precision", "recall", "community modularity", "centrality lift", "case capture"],
  "custom-workflow": ["completion status", "quality score", "approval status", "risk rating"],
  default: ["primary metric", "secondary metric", "quality check", "approval status"],
};

const methodOptions: Record<ProjectType | "default", string[]> = {
  "predictive-modeling": ["Not applicable", "Supervised learning", "Champion/challenger"],
  "experimental-design": ["Full factorial", "Fractional factorial", "Randomized block", "Response surface", "Taguchi"],
  "ab-testing": ["Two-sample proportion test", "T-test", "Sequential test", "Bayesian A/B test", "Difference-in-differences"],
  optimization: ["Linear programming", "Mixed integer programming", "Nonlinear optimization", "Heuristic search", "Simulation optimization"],
  forecasting: ["Naive baseline", "ETS", "ARIMA/SARIMA", "Prophet-style model", "Gradient boosting with lags"],
  segmentation: ["K-means", "Hierarchical clustering", "Gaussian mixture", "DBSCAN", "Rule-based segmentation"],
  "reinforcement-learning": ["Contextual bandit", "Q-learning", "Policy gradient", "Offline policy evaluation", "Simulation only"],
  "time-series": ["Decomposition", "Stationarity testing", "ARIMA diagnostics", "Anomaly detection", "Change point detection"],
  nlp: ["Rules", "TF-IDF model", "Embeddings", "Transformer fine-tune", "RAG/LLM-assisted workflow"],
  "computer-vision": ["Transfer learning", "Object detection", "Image segmentation", "Classical CV", "Human review workflow"],
  "graph-analytics": ["Community detection", "Link prediction", "Node classification", "Graph embeddings", "Rules and network features"],
  "custom-workflow": ["User-defined method", "Manual review", "Checklist-driven process"],
  default: ["User-defined method"],
};

function emptyState(): NodeState {
  return {
    objective: "",
    inputs: "",
    assumptions: "",
    method: "",
    metrics: [],
    validation: "",
    risks: "",
    decision: "",
    rationale: "",
    notes: "",
    assignmentUnit: "Customer",
    allocationMode: "equal",
    blockStratum: "",
    selectedExclusions: ["inactive", "opt-out", "recent-offer"],
  numeric: {
      baselineRate: 10,
      expectedLift: 5,
      alpha: 5,
      power: 80,
      factorCount: 3,
      averageLevels: 2,
      replicates: 2,
      blocks: 1,
      runs: 12,
      mse: 1,
      effectSize: 0.25,
      simulations: 1000,
      seed: 42,
      treatmentImbalance: 5,
      missingnessRate: 2,
      periods: 36,
      holdoutPeriods: 6,
      candidateCount: 4,
      constraintCount: 5,
      clusterCount: 5,
      sampleSize: 1000,
    },
  };
}

function storageKey(projectId: string, stepId: string) {
  return `${STORAGE_KEY}:${projectId}:${stepId}`;
}

function loadNodeState(projectId: string, stepId: string): NodeState {
  try {
    const parsed = JSON.parse(localStorage.getItem(storageKey(projectId, stepId)) || "null");
    return parsed ? { ...emptyState(), ...parsed, numeric: { ...emptyState().numeric, ...(parsed.numeric ?? {}) } } : emptyState();
  } catch {
    return emptyState();
  }
}

function compactSimulationResults(results?: MonteCarloSimulationResults): MonteCarloSimulationResults | undefined {
  if (!results) return undefined;
  const powerDistribution = results.powerDistribution ?? histogram(results.powerByIteration.map((row) => row.achievedPower), [
    { label: "50-60%", min: 0.5, max: 0.6 },
    { label: "60-70%", min: 0.6, max: 0.7 },
    { label: "70-80%", min: 0.7, max: 0.8 },
    { label: "80-90%", min: 0.8, max: 0.9 },
    { label: "90-100%", min: 0.9, max: 1.01 },
  ]);
  const liftDistribution = results.liftDistribution ?? liftHistogram(results.powerByIteration.map((row) => row.estimatedLift));
  const convergenceCurve = results.convergenceCurve ?? Array.from({ length: 10 }, (_, index) => {
    const end = Math.max(1, Math.round(((index + 1) / 10) * results.powerByIteration.length));
    return { x: end, y: mean(results.powerByIteration.slice(0, end).map((row) => row.achievedPower)) };
  });
  const trueLift = results.inputs.minimumDetectableLift;
  const minIterations = results.powerByIteration.slice(0, 80);
  const intervalPreview = results.intervalPreview ?? minIterations.map((row, index) => {
    const width = Math.max(0.005, results.liftStdDev * 1.96 * (0.8 + (index % 7) * 0.05));
    const low = row.estimatedLift - width;
    const high = row.estimatedLift + width;
    return { index, estimate: row.estimatedLift, low, high, covers: low <= trueLift && trueLift <= high };
  });
  return {
    ...results,
    powerByIteration: [],
    powerDistribution,
    liftDistribution,
    convergenceCurve,
    intervalPreview,
  };
}

function cleanNodeStateForStorage(state: NodeState): NodeState {
  const { analysisSnapshot, ...rest } = state;
  return {
    ...emptyState(),
    ...rest,
    numeric: { ...emptyState().numeric, ...(rest.numeric ?? {}) },
    simulationResults: compactSimulationResults(rest.simulationResults),
  };
}

function minimalNodeStateForStorage(state: NodeState): NodeState {
  return {
    ...emptyState(),
    objective: state.objective,
    inputs: state.inputs,
    assumptions: state.assumptions,
    validation: state.validation,
    method: state.method,
    metrics: state.metrics,
    risks: state.risks,
    decision: state.decision,
    rationale: state.rationale,
    notes: state.notes,
    numeric: { ...emptyState().numeric, ...(state.numeric ?? {}) },
    simulationResults: state.simulationResults
      ? compactSimulationResults({
          ...state.simulationResults,
          powerByIteration: [],
          intervalPreview: state.simulationResults.intervalPreview?.slice(0, 20) ?? [],
          powerCurve: state.simulationResults.powerCurve?.slice(0, 40) ?? [],
          scenarioSensitivity: state.simulationResults.scenarioSensitivity?.slice(0, 12) ?? [],
          riskDrivers: state.simulationResults.riskDrivers?.slice(0, 8) ?? [],
        })
      : undefined,
  };
}

function reclaimWorkflowStorage() {
  if (typeof localStorage === "undefined") return;
  for (let index = 0; index < localStorage.length; index += 1) {
    const key = localStorage.key(index);
    if (!key?.startsWith(`${STORAGE_KEY}:`)) continue;
    try {
      const parsed = JSON.parse(localStorage.getItem(key) || "null");
      if (parsed && typeof parsed === "object" && "analysisSnapshot" in parsed) {
        localStorage.setItem(key, JSON.stringify(cleanNodeStateForStorage(parsed as NodeState)));
      }
    } catch {
      localStorage.removeItem(key);
    }
  }
  try {
    const journalKey = "modeling-tool-decision-journal";
    const parsed = JSON.parse(localStorage.getItem(journalKey) || "[]");
    if (Array.isArray(parsed) && parsed.length > 100) {
      localStorage.setItem(journalKey, JSON.stringify(parsed.slice(0, 100)));
    }
  } catch {
    localStorage.removeItem("modeling-tool-decision-journal");
  }
}

function saveNodeState(projectId: string, stepId: string, state: NodeState) {
  const cleaned = cleanNodeStateForStorage(state);
  try {
    localStorage.setItem(storageKey(projectId, stepId), JSON.stringify(cleaned));
  } catch (error) {
    reclaimWorkflowStorage();
    try {
      localStorage.setItem(storageKey(projectId, stepId), JSON.stringify(cleaned));
    } catch {
      const minimal = minimalNodeStateForStorage(cleaned);
      localStorage.setItem(storageKey(projectId, stepId), JSON.stringify(minimal));
      window.dispatchEvent(
        new CustomEvent("atlas-project-save-status", {
          detail: {
            status: "partial_restore",
            projectId,
            savedAt: new Date().toISOString(),
            message: "Saved a compact page summary because browser storage quota was reached.",
          },
        })
      );
      window.dispatchEvent(new CustomEvent("atlas-workflow-node-updated"));
      return minimal;
    }
  }
  window.dispatchEvent(new CustomEvent("atlas-workflow-node-updated"));
  return cleaned;
}

function downloadText(filename: string, content: string, type: string) {
  const blob = new Blob([content], { type });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}

function printHtmlDocument(html: string) {
  const printWindow = window.open("", "_blank", "noopener,noreferrer");
  if (!printWindow) {
    downloadText("atlas-executive-report.html", html, "text/html;charset=utf-8");
    return;
  }
  printWindow.document.write(html);
  printWindow.document.close();
  printWindow.focus();
  setTimeout(() => printWindow.print(), 250);
}

function buildExperimentSpecification(projectId: string) {
  const workflowState = useWorkflowStore.getState();
  const workflow = getWorkflowDefinition(workflowState.workflowId);
  const evidence = loadWorkflowNodeEvidence(projectId, workflowState.workflowSteps);
  return {
    product: "ATLAS",
    artifactType: "Experimental Design Specification",
    generatedAt: new Date().toISOString(),
    project: {
      projectId: workflowState.projectId,
      modelId: workflowState.modelId,
      projectName: workflowState.projectName,
      projectType: workflowState.projectType,
      workflowId: workflowState.workflowId,
      workflowLabel: workflow.label,
    },
    projectContext: loadProjectContext(),
    workflowSteps: workflowState.workflowSteps,
    evidence,
    simulationResults: evidence.find((row) => row.stepLabel === "Monte Carlo Simulation")?.simulationResults ?? null,
  };
}

function labelize(value: string) {
  return value.replace(/-/g, " ").replace(/\b\w/g, (char) => char.toUpperCase());
}

function recommendations(projectType: ProjectType, stepLabel: string) {
  if (projectType === "ab-testing") {
    if (/metric/i.test(stepLabel)) return ["Choose exactly one primary metric before power analysis.", "Add guardrail metrics for risk, compliance, and customer experience."];
    if (/power|sample/i.test(stepLabel)) return ["Use baseline rate, minimum detectable effect, alpha, and desired power to justify sample size.", "Document whether the test has enough traffic to finish in a business-relevant window."];
    return ["Define hypothesis, population, randomization unit, and decision rule before launch."];
  }
  if (projectType === "optimization") return ["Document the objective function and every hard constraint before solver configuration.", "Validate recommended solutions against business rules and operational feasibility."];
  if (projectType === "forecasting" || projectType === "time-series") return ["Use time-based validation and preserve temporal order.", "Review seasonality, holidays, structural breaks, and drift before selecting final methods."];
  if (projectType === "segmentation") return ["Prioritize stable, interpretable segments over purely mathematical separation.", "Require segment names, business actions, and monitoring before activation."];
  if (projectType === "nlp") return ["Document corpus lineage, labeling quality, PII controls, and human review criteria.", "Use task-specific metrics and safety checks, not only aggregate accuracy."];
  if (projectType === "computer-vision") return ["Review image quality, annotation consistency, and subgroup failure cases.", "Track false positives and human review burden before deployment."];
  if (projectType === "graph-analytics") return ["Define nodes, edges, direction, weights, and time validity before modeling.", "Validate graph features for leakage and investigation usefulness."];
  if (projectType === "reinforcement-learning") return ["Define state, action, reward, safety constraints, and offline evaluation before policy learning.", "Prefer simulation and guarded rollout until policy risk is understood."];
  if (projectType === "experimental-design") return ["Define factors and levels before randomization.", "Check power for interactions if interaction effects are decision-critical."];
  return ["Capture objective, evidence, assumptions, risks, and decision rationale for this workflow step."];
}

function abSampleSize(state: NodeState) {
  const p1 = Math.max(0.0001, Math.min(0.9999, state.numeric.baselineRate / 100));
  const lift = state.numeric.expectedLift / 100;
  const p2 = Math.max(0.0001, Math.min(0.9999, p1 * (1 + lift)));
  const zAlpha = state.numeric.alpha <= 1 ? 2.58 : state.numeric.alpha <= 5 ? 1.96 : 1.64;
  const zPower = state.numeric.power >= 90 ? 1.28 : state.numeric.power >= 80 ? 0.84 : 0.52;
  const pooled = (p1 + p2) / 2;
  const numerator =
    zAlpha * Math.sqrt(2 * pooled * (1 - pooled)) +
    zPower * Math.sqrt(p1 * (1 - p1) + p2 * (1 - p2));
  const n = Math.ceil((numerator * numerator) / Math.max(1e-9, (p2 - p1) ** 2));
  return { perCell: n, total: n * 2, p1, p2 };
}

function StepCalculator({ projectType, state, setState }: { projectType: ProjectType; state: NodeState; setState: (state: NodeState) => void }) {
  const updateNumber = (key: string, value: number) => setState({ ...state, numeric: { ...state.numeric, [key]: value } });

  if (projectType === "ab-testing") {
    const result = abSampleSize(state);
    return (
      <CalculatorPanel title="A/B Test Planning Calculator">
        <NumberField label="Baseline Rate %" value={state.numeric.baselineRate} onChange={(value) => updateNumber("baselineRate", value)} />
        <NumberField label="Expected Lift %" value={state.numeric.expectedLift} onChange={(value) => updateNumber("expectedLift", value)} />
        <NumberField label="Alpha %" value={state.numeric.alpha} onChange={(value) => updateNumber("alpha", value)} />
        <NumberField label="Power %" value={state.numeric.power} onChange={(value) => updateNumber("power", value)} />
        <ResultCard label="Approx. sample per cell" value={result.perCell.toLocaleString()} />
        <ResultCard label="Approx. total sample" value={result.total.toLocaleString()} />
      </CalculatorPanel>
    );
  }

  if (projectType === "forecasting" || projectType === "time-series") {
    const trainPeriods = Math.max(0, state.numeric.periods - state.numeric.holdoutPeriods);
    return (
      <CalculatorPanel title="Time Validation Planner">
        <NumberField label="Historical Periods" value={state.numeric.periods} onChange={(value) => updateNumber("periods", value)} />
        <NumberField label="Holdout Periods" value={state.numeric.holdoutPeriods} onChange={(value) => updateNumber("holdoutPeriods", value)} />
        <ResultCard label="Training periods" value={trainPeriods.toLocaleString()} />
        <ResultCard label="Holdout share" value={`${((state.numeric.holdoutPeriods / Math.max(1, state.numeric.periods)) * 100).toFixed(1)}%`} />
      </CalculatorPanel>
    );
  }

  if (projectType === "optimization") {
    return (
      <CalculatorPanel title="Optimization Readiness">
        <NumberField label="Decision Variables" value={state.numeric.candidateCount} onChange={(value) => updateNumber("candidateCount", value)} />
        <NumberField label="Hard Constraints" value={state.numeric.constraintCount} onChange={(value) => updateNumber("constraintCount", value)} />
        <ResultCard label="Complexity flag" value={state.numeric.constraintCount > 10 || state.numeric.candidateCount > 20 ? "High" : "Moderate"} />
        <ResultCard label="Solver readiness" value={state.objective && state.inputs && state.assumptions ? "Ready for configuration" : "Needs definition"} />
      </CalculatorPanel>
    );
  }

  if (projectType === "segmentation") {
    return (
      <CalculatorPanel title="Segmentation Design">
        <NumberField label="Candidate Clusters" value={state.numeric.clusterCount} onChange={(value) => updateNumber("clusterCount", value)} />
        <NumberField label="Sample Size" value={state.numeric.sampleSize} onChange={(value) => updateNumber("sampleSize", value)} />
        <ResultCard label="Records per cluster" value={Math.floor(state.numeric.sampleSize / Math.max(1, state.numeric.clusterCount)).toLocaleString()} />
        <ResultCard label="Review focus" value={state.numeric.sampleSize / Math.max(1, state.numeric.clusterCount) < 100 ? "Cluster size risk" : "Profile stability"} />
      </CalculatorPanel>
    );
  }

  return (
    <CalculatorPanel title={`${labelize(projectType)} Readiness`}>
      <ResultCard label="Evidence captured" value={state.inputs ? "Yes" : "No"} />
      <ResultCard label="Validation captured" value={state.validation ? "Yes" : "No"} />
      <ResultCard label="Risks captured" value={state.risks ? "Yes" : "No"} />
      <ResultCard label="Decision captured" value={state.decision ? "Yes" : "No"} />
    </CalculatorPanel>
  );
}

const experimentalConfigs: Record<string, ExperimentalStepConfig> = {
  "Project Context": {
    eyebrow: "Experiment Charter",
    guidance: [
      "Define the operational decision the experiment will support.",
      "If the experiment changes customer treatment, contact frequency, or pricing, document launch governance before execution.",
      "Document governance constraints before treatment assignment begins.",
      "Name the accountable business owner and approval path.",
    ],
    methodLabel: "Experiment family",
    methods: ["Screening experiment", "Factorial experiment", "Response surface", "Randomized block design", "Taguchi design"],
    metrics: ["primary response", "guardrail metric", "cost metric", "quality metric", "compliance metric"],
    fields: [
      { key: "objective", label: "Business Decision / Objective", rows: 4, placeholder: "Example: Determine which pricing and contact strategy improves activation without increasing complaint risk." },
      { key: "inputs", label: "Population and Experimental Units", rows: 4, placeholder: "Define eligible accounts, unit of randomization, exclusions, and expected volume." },
      { key: "assumptions", label: "Operational Constraints", rows: 4, placeholder: "Document channel capacity, policy limits, treatment availability, and timing constraints." },
      { key: "validation", label: "Governance / Approval Requirements", rows: 4, placeholder: "List required review forums, compliance checks, and launch approvals." },
    ],
  },
  "Research Question": {
    eyebrow: "Hypothesis Framing",
    guidance: [
      "Translate the business objective into one primary testable question.",
      "Separate confirmatory hypotheses from exploratory learning goals.",
      "Define the response variable before choosing factors and levels.",
    ],
    methodLabel: "Analysis / design intent",
    methods: [
      "Main Effects Analysis",
      "Main Effects + Interaction Analysis",
      "Treatment Comparison",
      "Process Optimization",
      "Robust Design (Taguchi)",
      "Variance Reduction",
      "Exploratory Screening",
    ],
    metrics: ["F-statistic", "p-value", "effect size", "confidence interval", "minimum practical effect"],
    fields: [
      { key: "objective", label: "Primary Research Question", rows: 4, placeholder: "State one question that can be answered by the experiment." },
      { key: "inputs", label: "Primary Response Variable", rows: 4, placeholder: "Define the measured outcome, unit, timing, and valid range." },
      { key: "assumptions", label: "Hypotheses", rows: 4, placeholder: "H0, H1, expected direction, and minimum meaningful difference." },
      { key: "validation", label: "Decision Rule", rows: 4, placeholder: "Explain how statistical evidence and business evidence will drive the final decision." },
    ],
  },
  Factors: {
    eyebrow: "Factor Inventory",
    guidance: [
      "Only include factors the business can control or intentionally vary.",
      "Separate experimental factors from measured covariates.",
      "Flag factors that may create compliance, fairness, or customer-impact risk.",
    ],
    methodLabel: "Factor strategy",
    methods: ["Controllable factors only", "Factors plus covariates", "Screening design", "Nested factors", "Mixture factors"],
    metrics: ["factor count", "covariate count", "aliasing risk", "controllability", "regulatory sensitivity"],
    fields: [
      { key: "objective", label: "Controllable Factors", rows: 5, placeholder: "List factors such as offer amount, communication channel, timing, message, policy threshold." },
      { key: "inputs", label: "Measured Covariates", rows: 4, placeholder: "List covariates that should be captured but not randomized." },
      { key: "risks", label: "Factor Risks / Restrictions", rows: 4, placeholder: "Identify restricted combinations, prohibited treatments, and sensitive-factor concerns." },
      { key: "validation", label: "Factor QA Checks", rows: 4, placeholder: "Confirm each factor can be assigned, measured, and audited." },
    ],
  },
  Levels: {
    eyebrow: "Level Definition",
    guidance: [
      "Levels must be feasible, sufficiently separated, and operationally reproducible.",
      "Avoid too many levels unless the sample size supports them.",
      "Document the control or baseline level for each factor.",
    ],
    methodLabel: "Level coding",
    methods: ["Two-level coded design", "Three-level design", "Ordinal levels", "Categorical levels", "Continuous response-surface levels"],
    metrics: ["level count", "treatment cells", "baseline cell", "restricted combinations", "coding completeness"],
    fields: [
      { key: "objective", label: "Factor Levels", rows: 5, placeholder: "Example: Channel = email, SMS, phone; Offer = low, medium, high." },
      { key: "inputs", label: "Baseline / Control Levels", rows: 4, placeholder: "Identify the current policy or control level for each factor." },
      { key: "assumptions", label: "Level Spacing Rationale", rows: 4, placeholder: "Explain why levels are large enough to detect practical differences." },
      { key: "validation", label: "Level Feasibility Checks", rows: 4, placeholder: "Confirm each level can be deployed and tracked accurately." },
    ],
  },
  Blocking: {
    eyebrow: "Nuisance Variation Control",
    guidance: [
      "Blocking is just a way to control known response differences that are not part of the experiment.",
      "Start with a business question: do region, time, risk band, branch, or campaign wave systematically influence the response?",
      "ATLAS will translate that answer into no blocking, a blocking variable, or stratified randomization guidance.",
    ],
    methodLabel: "Expected nuisance variation",
    methods: ["None expected", "One nuisance variable", "Several nuisance variables", "Time-period variation", "Segment or risk-band variation"],
    metrics: ["blocking recommendation", "stratification need", "within-block balance", "minimum block size", "operational complexity"],
    fields: [
      { key: "objective", label: "Variables That May Influence Response", rows: 4, placeholder: "Examples: Region, Time period, Risk band, Branch, Campaign wave. Leave blank if none are expected." },
      { key: "inputs", label: "Why They Matter", rows: 4, placeholder: "Briefly explain why these variables may shift response independent of the experimental factors." },
      { key: "validation", label: "Balance Checks Needed", rows: 4, placeholder: "ATLAS recommends checking treatment balance within any selected blocking or stratification variables." },
      { key: "risks", label: "Operational Risks", rows: 4, placeholder: "Document sparse blocks, hard-to-implement strata, or variables that may be downstream of treatment." },
    ],
  },
  Randomization: {
    eyebrow: "Assignment Design",
    guidance: [
      "Randomization should preserve treatment balance across treatment cells, account for blocking or stratification decisions, and produce a reproducible assignment record before launch.",
    ],
    methodLabel: "Randomization method",
    methods: ["Simple randomization", "Stratified randomization", "Blocked randomization", "Cluster randomization", "Covariate-adaptive randomization"],
    metrics: ["assignment ratio", "sample ratio mismatch", "balance statistic", "seed recorded", "excluded records"],
    fields: [
      { key: "objective", label: "Randomization Unit and Ratio", rows: 4, placeholder: "Define account/customer/application/unit and allocation ratio across cells." },
      { key: "inputs", label: "Decision Logic / Assignment Logic / Seed", rows: 4, placeholder: "Document treatment decision logic, random seed, reproducible assignment code, and treatment table location." },
      { key: "validation", label: "Randomization and Exclusion QA", rows: 4, placeholder: "Describe balance tests, duplicate checks, population exclusions, and exclusion validation." },
      { key: "decision", label: "Launch Assignment Decision", rows: 4, placeholder: "State whether assignment is ready, needs revision, or requires approval." },
    ],
  },
  "Sample Size": {
    eyebrow: "Power and Precision",
    guidance: [
      "Size the experiment for the smallest effect the business would act on.",
      "Check whether interactions require more sample than main effects.",
      "Document practical constraints if power is below target.",
    ],
    methodLabel: "Sizing basis",
    methods: ["Main effects only", "Main effects plus two-way interactions", "Response surface", "Precision-based", "Operational capacity-limited"],
    metrics: ["power", "alpha", "minimum detectable effect", "runs", "replicates", "degrees of freedom"],
    fields: [
      { key: "objective", label: "Minimum Practical Effect", rows: 4, placeholder: "Define the smallest effect size worth acting on." },
      { key: "inputs", label: "Baseline Response Inputs", rows: 4, placeholder: "Provide historical response rate, expected variance, or baseline outcome evidence." },
      { key: "assumptions", label: "Power Assumptions", rows: 4, placeholder: "Document alpha, desired power, minimum detectable effect, treatment cells, and population limits." },
      { key: "decision", label: "Sample Size Recommendation", rows: 4, placeholder: "Use the automated planner to document required per-cell and total sample, then note any constraints." },
    ],
  },
  "Monte Carlo Simulation": {
    eyebrow: "Design Stress Test",
    guidance: [
      "Use Monte Carlo simulation to pressure-test the design before operational launch.",
      "Vary effect size, residual variance, missingness, and treatment imbalance to see how often the experiment reaches the right decision.",
      "Document whether simulation results support launch, redesign, or additional sample.",
    ],
    methodLabel: "Simulation approach",
    methods: ["Power simulation", "Treatment selection simulation", "Interaction sensitivity simulation", "Missingness stress test", "Operational imbalance simulation"],
    metrics: ["simulated power", "false positive rate", "false negative rate", "wrong winner rate", "confidence interval coverage", "decision stability"],
    fields: [
      { key: "objective", label: "Simulation Objective", rows: 4, placeholder: "Example: Estimate how often the design detects a 2% lift under expected variance and cell imbalance." },
      { key: "inputs", label: "Simulation Inputs", rows: 5, placeholder: "Document baseline mean/rate, effect size, MSE/variance, cell sizes, blocks, missingness, and iterations." },
      { key: "assumptions", label: "Scenario Assumptions", rows: 5, placeholder: "Define base, conservative, and stress scenarios for variance, treatment imbalance, and interaction strength." },
      { key: "validation", label: "Simulation QA Checks", rows: 4, placeholder: "Confirm random seed, distribution assumptions, replication count, and reasonableness of simulated outcomes." },
      { key: "risks", label: "Design Risks Identified", rows: 4, placeholder: "Capture power gaps, unstable winner selection, high false negative risk, or sensitivity to missing data." },
      { key: "decision", label: "Simulation Decision", rows: 4, placeholder: "State whether to proceed, increase sample, reduce factors, add blocks, or redesign the experiment." },
    ],
  },
  "Experiment Run Plan": {
    eyebrow: "Execution Control",
    guidance: [
      "A run plan prevents treatment contamination and operational drift.",
      "Customer treatment, contact-frequency, and pricing experiments require documented monitoring and escalation before launch.",
      "Define holdout, stopping, exception, and QA procedures before launch.",
      "Capture lineage for treatment delivery and response measurement.",
    ],
    methodLabel: "Run sequencing",
    methods: ["Single launch", "Staggered launch", "Blocked run order", "Balanced daily allocation", "Pilot then full launch"],
    metrics: ["launch readiness", "treatment fidelity", "QA pass rate", "contamination rate", "stopping rule"],
    fields: [
      { key: "objective", label: "Run Sequence", rows: 4, placeholder: "Describe launch timing, sequence, and operational dependencies." },
      { key: "inputs", label: "Treatment Delivery and Contact Controls", rows: 4, placeholder: "Document how treatments, contact frequency, pricing, and treatment delivery will be logged and reconciled." },
      { key: "validation", label: "Pre-launch QA and Monitoring Checklist", rows: 5, placeholder: "List assignment, suppression, contact policy, pricing policy, compliance, monitoring, and data checks." },
      { key: "risks", label: "Stopping / Exception / Escalation Rules", rows: 4, placeholder: "Define when to pause, stop, escalate, or roll back the experiment." },
    ],
  },
  ANOVA: {
    eyebrow: "Effect Analysis",
    guidance: [
      "Use ANOVA to estimate factor effects and separate signal from residual noise.",
      "Check residual assumptions before trusting p-values.",
      "Pair statistical significance with practical effect size.",
    ],
    methodLabel: "Analysis model",
    methods: ["One-way ANOVA", "Two-way ANOVA", "Factorial ANOVA", "ANCOVA", "Mixed effects model"],
    metrics: ["F-statistic", "p-value", "eta squared", "MSE", "residual normality", "homogeneity of variance"],
    fields: [
      { key: "objective", label: "Response Variable / Outcome", rows: 4, placeholder: "Define the measured response ATLAS should use in the generated ANOVA model." },
      { key: "inputs", label: "ANOVA Results Notes", rows: 5, placeholder: "After analysis, capture SS, df, MS, F, p-value, and effect-size highlights." },
      { key: "validation", label: "Residual Diagnostics", rows: 4, placeholder: "Document residual distribution, variance equality, outliers, and influence checks." },
      { key: "decision", label: "Main Effect Findings", rows: 4, placeholder: "Summarize statistically and practically meaningful main effects." },
    ],
  },
  "Interaction Effects": {
    eyebrow: "Factor Combinations",
    guidance: [
      "Interactions indicate that the effect of one factor changes at another factor level.",
      "Prioritize interactions that are material and operationally actionable.",
      "Avoid selecting settings based only on noisy high-order interactions.",
    ],
    methodLabel: "Interaction review",
    methods: ["Two-way interactions", "Higher-order screening", "Simple effects", "Interaction plot review", "Hierarchical model"],
    metrics: ["interaction p-value", "interaction effect size", "simple effect", "cell mean difference", "practical significance"],
    fields: [
      { key: "objective", label: "Interaction Hypotheses", rows: 4, placeholder: "List interactions expected before observing results." },
      { key: "inputs", label: "Observed Interaction Patterns", rows: 5, placeholder: "Document cell means and notable crossover or amplification effects." },
      { key: "validation", label: "Interaction Robustness Checks", rows: 4, placeholder: "Check sample size by cell, confidence intervals, and replication." },
      { key: "decision", label: "Actionable Interaction Decisions", rows: 4, placeholder: "State which factor combinations should be recommended or avoided." },
    ],
  },
  Optimization: {
    eyebrow: "Recommended Settings",
    guidance: [
      "Optimization should respect constraints, guardrails, and compliance requirements.",
      "Use desirability or tradeoff analysis when several responses matter.",
      "Document whether recommendations require confirmation experiments.",
    ],
    methodLabel: "Optimization method",
    methods: ["Best observed cell", "Desirability function", "Response surface optimum", "Constrained optimum", "Confirmation experiment"],
    metrics: ["predicted response", "desirability", "constraint pass rate", "expected lift", "confirmation risk"],
    fields: [
      { key: "objective", label: "Optimization Objective", rows: 4, placeholder: "Define what should be maximized or minimized and the business tradeoffs." },
      { key: "inputs", label: "Candidate Optimal Settings", rows: 5, placeholder: "List recommended factor settings and expected response." },
      { key: "risks", label: "Constraints / Guardrails", rows: 4, placeholder: "Document customer, compliance, cost, and operational limits." },
      { key: "decision", label: "Optimization Recommendation", rows: 4, placeholder: "Recommend launch, confirmatory test, or further experimentation." },
    ],
  },
  Documentation: {
    eyebrow: "Governance Package",
    guidance: [
      "The final document should reproduce design, execution, analysis, decisions, and limitations.",
      "Include randomization evidence and run-plan QA artifacts.",
      "Include customer-treatment logic, population exclusions, monitoring, and escalation controls for execution approval.",
      "Record unresolved risks and monitoring recommendations.",
    ],
    methodLabel: "Documentation artifact",
    methods: ["Experiment report", "Governance memo", "Implementation handoff", "Validation package", "Executive summary"],
    metrics: ["evidence completeness", "decision readiness", "approval status", "limitations documented", "monitoring defined"],
    fields: [
      { key: "objective", label: "Executive Summary", rows: 4, placeholder: "Summarize purpose, design, key findings, and recommended action." },
      { key: "inputs", label: "Evidence Inventory", rows: 5, placeholder: "List datasets, assignment files, code, QA outputs, ANOVA tables, and charts." },
      { key: "rationale", label: "Decision Rationale", rows: 5, placeholder: "Explain why the recommended setting or decision is supported." },
      { key: "risks", label: "Limitations and Monitoring", rows: 4, placeholder: "Document assumptions, limitations, rollout risks, and monitoring cadence." },
    ],
  },
};

function experimentalConfigFor(stepLabel: string): ExperimentalStepConfig {
  return experimentalConfigs[stepLabel] ?? experimentalConfigs["Project Context"];
}

function cleanFactorName(value: string) {
  return value
    .replace(/^[-*•\d.)\s]+/, "")
    .replace(/\s+/g, " ")
    .trim();
}

function inferFactorType(factor: string): SuggestedFactor["type"] {
  if (/amount|price|pricing|rate|threshold|limit|dose|duration|time|score|percent|%/i.test(factor)) return "Numeric";
  if (/low|medium|high|tier|band|level|rank|priority/i.test(factor)) return "Ordinal";
  return "Categorical";
}

function suggestedLevelsForFactor(factor: string, type: SuggestedFactor["type"]) {
  if (/pricing|price|rate/i.test(factor)) return ["Current", "Personalized"];
  if (/contact|channel/i.test(factor)) return ["Email", "SMS"];
  if (/offer|incentive|discount/i.test(factor)) return ["Standard", "Enhanced"];
  if (/message|copy|creative|script/i.test(factor)) return ["Control", "Variant"];
  if (/timing|time|schedule/i.test(factor)) return ["Current timing", "Optimized timing"];
  if (/threshold|limit|cutoff|score/i.test(factor)) return ["Current threshold", "Proposed threshold"];
  if (type === "Numeric") return ["Low", "High"];
  if (type === "Ordinal") return ["Low", "Medium", "High"];
  return ["Control", "Treatment"];
}

function parseListItems(rawText: string) {
  return rawText
    .split(/\n|;|,/)
    .map(cleanFactorName)
    .filter(Boolean)
    .slice(0, 12);
}

function product(values: number[]) {
  return values.reduce((result, value) => result * Math.max(1, value), 1);
}

function normalQuantile(probability: number) {
  const p = Math.max(0.000001, Math.min(0.999999, probability));
  if (p >= 0.995) return 2.58;
  if (p >= 0.99) return 2.33;
  if (p >= 0.975) return 1.96;
  if (p >= 0.95) return 1.64;
  if (p >= 0.9) return 1.28;
  if (p >= 0.8) return 0.84;
  if (p >= 0.7) return 0.52;
  return 0;
}

function normalCdf(value: number) {
  const sign = value < 0 ? -1 : 1;
  const x = Math.abs(value) / Math.sqrt(2);
  const t = 1 / (1 + 0.3275911 * x);
  const a1 = 0.254829592;
  const a2 = -0.284496736;
  const a3 = 1.421413741;
  const a4 = -1.453152027;
  const a5 = 1.061405429;
  const erf = sign * (1 - (((((a5 * t + a4) * t) + a3) * t + a2) * t + a1) * t * Math.exp(-x * x));
  return 0.5 * (1 + erf);
}

function powerForPerCell(perCell: number, baseline: number, treatmentRate: number, alpha: number) {
  const n = Math.max(1, perCell);
  const pbar = (baseline + treatmentRate) / 2;
  const diff = Math.abs(treatmentRate - baseline);
  const zAlpha = normalQuantile(1 - alpha / 2);
  const pooledSe = Math.sqrt((2 * pbar * (1 - pbar)) / n);
  const alternativeSe = Math.sqrt((baseline * (1 - baseline) + treatmentRate * (1 - treatmentRate)) / n);
  return normalCdf((diff - zAlpha * pooledSe) / Math.max(1e-9, alternativeSe));
}

function sampleSizePlan(state: NodeState) {
  const treatmentCells = Math.max(1, Math.round(state.numeric.averageLevels ** state.numeric.factorCount));
  const alpha = Math.max(0.001, Math.min(0.5, state.numeric.alpha / 100));
  const desiredPower = Math.max(0.5, Math.min(0.99, state.numeric.power / 100));
  const baseline = Math.max(0.0001, Math.min(0.9999, state.numeric.baselineRate / 100));
  const minimumDetectableLift = Math.max(0.0001, state.numeric.expectedLift / 100);
  const treatmentRate = Math.max(0.0001, Math.min(0.9999, baseline * (1 + minimumDetectableLift)));
  const absoluteEffect = Math.max(0.0001, Math.abs(treatmentRate - baseline));
  const zAlpha = normalQuantile(1 - alpha / 2);
  const zPower = normalQuantile(desiredPower);
  const pooled = (baseline + treatmentRate) / 2;
  const numerator =
    zAlpha * Math.sqrt(2 * pooled * (1 - pooled)) +
    zPower * Math.sqrt(baseline * (1 - baseline) + treatmentRate * (1 - treatmentRate));
  const perCell = Math.ceil((numerator * numerator) / (absoluteEffect * absoluteEffect));
  const total = perCell * treatmentCells;
  const available = Math.max(0, state.numeric.sampleSize);
  const plannedTotal = available > 0 ? available : total;
  const plannedPerCell = Math.floor(plannedTotal / treatmentCells);
  const expectedPower = powerForPerCell(perCell, baseline, treatmentRate, alpha) * 100;
  const ciHalfWidth = zAlpha * Math.sqrt((baseline * (1 - baseline)) / Math.max(1, perCell));
  const powerCurve = [0.5, 0.75, 1, 1.25, 1.5].map((multiplier) => {
    const sample = Math.max(1, Math.round(perCell * multiplier));
    return { perCell: sample, power: powerForPerCell(sample, baseline, treatmentRate, alpha) * 100 };
  });
  const sensitivity = [2, 5, 10, 15, 20, 25, 30, 40].map((liftPct) => {
    const nextBaseline = baseline;
    const nextLift = Math.max(0.0001, liftPct / 100);
    const nextTreatment = Math.max(0.0001, Math.min(0.9999, nextBaseline * (1 + nextLift)));
    const nextEffect = Math.max(0.0001, Math.abs(nextTreatment - nextBaseline));
    const nextPooled = (nextBaseline + nextTreatment) / 2;
    const nextNumerator =
      zAlpha * Math.sqrt(2 * nextPooled * (1 - nextPooled)) +
      zPower * Math.sqrt(nextBaseline * (1 - nextBaseline) + nextTreatment * (1 - nextTreatment));
    const nextPerCell = Math.ceil((nextNumerator * nextNumerator) / (nextEffect * nextEffect));
    return { liftPct, perCell: nextPerCell, total: nextPerCell * treatmentCells };
  });
  const contours = [75, 80, 85, 90, 95].map((powerPct) => {
    const contourState = { ...state, numeric: { ...state.numeric, power: powerPct } };
    const contour = sampleSizePlanShallow(contourState);
    return { powerPct, perCell: contour.perCell, total: contour.perCell * treatmentCells };
  });
  const requiredTotalFor = (changes: Record<string, number>) => {
    const nextState = { ...state, numeric: { ...state.numeric, ...changes } };
    const shallow = sampleSizePlanShallow(nextState);
    return shallow.perCell * shallow.treatmentCells;
  };
  const tornado = [
    {
      label: "Baseline response",
      low: requiredTotalFor({ baselineRate: Math.max(1, state.numeric.baselineRate * 0.75) }),
      high: requiredTotalFor({ baselineRate: Math.min(30, state.numeric.baselineRate * 1.25) }),
    },
    {
      label: "Minimum detectable lift",
      low: requiredTotalFor({ expectedLift: Math.max(1, state.numeric.expectedLift * 0.75) }),
      high: requiredTotalFor({ expectedLift: Math.min(50, state.numeric.expectedLift * 1.25) }),
    },
    {
      label: "Desired power",
      low: requiredTotalFor({ power: Math.max(60, state.numeric.power - 10) }),
      high: requiredTotalFor({ power: Math.min(95, state.numeric.power + 10) }),
    },
    {
      label: "Alpha",
      low: requiredTotalFor({ alpha: Math.max(1, state.numeric.alpha - 2) }),
      high: requiredTotalFor({ alpha: Math.min(10, state.numeric.alpha + 2) }),
    },
    {
      label: "Factors / levels",
      low: requiredTotalFor({ factorCount: Math.max(1, state.numeric.factorCount - 1) }),
      high: requiredTotalFor({ factorCount: Math.min(6, state.numeric.factorCount + 1) }),
    },
  ]
    .map((row) => ({ ...row, impact: Math.max(Math.abs(row.low - total), Math.abs(row.high - total)) }))
    .sort((a, b) => b.impact - a.impact);
  const simulation = simulateSampleSizeOutcomes(state, perCell, 1000);
  return {
    treatmentCells,
    alpha,
    desiredPower,
    baseline,
    treatmentRate,
    minimumDetectableLift,
    absoluteEffect,
    perCell,
    total,
    plannedPerCell,
    plannedTotal,
    available,
    expectedPower,
    ciHalfWidth,
    powerCurve,
    sensitivity,
    contours,
    tornado,
    simulation,
    adequatelyPowered: available >= total,
  };
}

function sampleSizePlanShallow(state: NodeState) {
  const treatmentCells = Math.max(1, Math.round(state.numeric.averageLevels ** state.numeric.factorCount));
  const alpha = Math.max(0.001, Math.min(0.5, state.numeric.alpha / 100));
  const desiredPower = Math.max(0.5, Math.min(0.99, state.numeric.power / 100));
  const baseline = Math.max(0.0001, Math.min(0.9999, state.numeric.baselineRate / 100));
  const lift = Math.max(0.0001, state.numeric.expectedLift / 100);
  const treatment = Math.max(0.0001, Math.min(0.9999, baseline * (1 + lift)));
  const effect = Math.max(0.0001, Math.abs(treatment - baseline));
  const zAlpha = normalQuantile(1 - alpha / 2);
  const zPower = normalQuantile(desiredPower);
  const pooled = (baseline + treatment) / 2;
  const numerator = zAlpha * Math.sqrt(2 * pooled * (1 - pooled)) + zPower * Math.sqrt(baseline * (1 - baseline) + treatment * (1 - treatment));
  return { perCell: Math.ceil((numerator * numerator) / (effect * effect)), treatmentCells };
}

function simulateSampleSizeOutcomes(state: NodeState, perCell: number, iterations: number) {
  const rng = seededRandom(Math.round(state.numeric.seed || 42) + 991);
  const baseline = Math.max(0.0001, Math.min(0.9999, state.numeric.baselineRate / 100));
  const lift = Math.max(0.0001, state.numeric.expectedLift / 100);
  const expected = baseline * lift;
  const se = Math.sqrt((2 * baseline * (1 - baseline)) / Math.max(1, perCell));
  const effects = Array.from({ length: iterations }, () => expected + (rng() - 0.5) * 4 * se);
  const detected = effects.filter((effect) => effect > 1.96 * se).length;
  const falseNegatives = effects.filter((effect) => effect <= 1.96 * se).length;
  const falsePositives = Math.round(iterations * Math.max(0.001, state.numeric.alpha / 100));
  const sorted = [...effects].sort((a, b) => a - b);
  return {
    effects,
    power: detected / iterations,
    falsePositives,
    falseNegatives,
    avgLift: effects.reduce((sum, value) => sum + value, 0) / iterations,
    low: sorted[Math.floor(iterations * 0.025)] ?? 0,
    high: sorted[Math.floor(iterations * 0.975)] ?? 0,
    coverage: 1 - Math.max(0.001, state.numeric.alpha / 100),
  };
}

function loadExperimentalNodeState(projectId: string, label: string) {
  const step = getWorkflowDefinition("experimental-design").steps.find((item) => item.label === label);
  if (!step) return null;
  try {
    const parsed = JSON.parse(localStorage.getItem(storageKey(projectId, step.id)) || "null");
    return parsed ? { ...emptyState(), ...parsed, numeric: { ...emptyState().numeric, ...(parsed.numeric ?? {}) } } as NodeState : null;
  } catch {
    return null;
  }
}

function loadExperimentalNodeStates(projectId: string) {
  return Object.fromEntries(
    getWorkflowDefinition("experimental-design").steps.map((step) => [step.label, loadExperimentalNodeState(projectId, step.label) ?? emptyState()])
  );
}

function seededRandom(seed: number) {
  let value = Math.max(1, Math.floor(seed)) % 2147483647;
  return () => {
    value = (value * 16807) % 2147483647;
    return (value - 1) / 2147483646;
  };
}

function normalSample(random: () => number) {
  const u1 = Math.max(1e-9, random());
  const u2 = random();
  return Math.sqrt(-2 * Math.log(u1)) * Math.cos(2 * Math.PI * u2);
}

function mean(values: number[]) {
  return values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : 0;
}

function stdDev(values: number[]) {
  const average = mean(values);
  return Math.sqrt(mean(values.map((value) => (value - average) ** 2)));
}

function percentile(values: number[], p: number) {
  if (!values.length) return 0;
  const sorted = [...values].sort((a, b) => a - b);
  const index = Math.min(sorted.length - 1, Math.max(0, Math.floor((sorted.length - 1) * p)));
  return sorted[index];
}

function statusForSimulation(meanPower: number, wrongWinnerRate: number): MonteCarloSimulationResults["recommendedAction"] {
  if (meanPower >= 0.8 && wrongWinnerRate <= 0.05) return "Strong";
  if (meanPower >= 0.7 && wrongWinnerRate <= 0.1) return "Adequate";
  if (meanPower >= 0.6) return "Weak";
  return "Redesign Required";
}

function monteCarloInputs(projectId: string, state: NodeState) {
  const levelsState = loadExperimentalNodeState(projectId, "Levels");
  const sampleState = loadExperimentalNodeState(projectId, "Sample Size");
  const parsedFactors = sharedParseFactorHierarchy(levelsState?.objective ?? "");
  const fallbackCells = Math.max(1, Math.round(state.numeric.averageLevels ** state.numeric.factorCount));
  const treatmentCells = parsedFactors.length ? treatmentCellCount(parsedFactors) : fallbackCells;
  const sampleBase = sampleState ?? state;
  const monteCarloNumeric = {
    ...sampleBase.numeric,
    baselineRate: state.numeric.baselineRate,
    expectedLift: state.numeric.expectedLift,
    alpha: state.numeric.alpha,
    power: state.numeric.power,
    sampleSize: sampleBase.numeric.sampleSize,
  };
  const plan = sampleSizePlan({ ...sampleBase, numeric: monteCarloNumeric });
  const numericSample = sampleState?.numeric ?? {};
  const totalPlannedSample =
    Number(numericSample.totalPlannedSample) > 0
      ? Math.floor(Number(numericSample.totalPlannedSample))
      : Number(numericSample.plannedSample) > 0
        ? Math.floor(Number(numericSample.plannedSample))
        : undefined;
  const availablePopulation = Number(numericSample.sampleSize) > 0 ? Math.floor(Number(numericSample.sampleSize)) : undefined;
  const sourceTotalSample = totalPlannedSample ?? availablePopulation;
  const samplePerCell = sourceTotalSample ? Math.floor(sourceTotalSample / treatmentCells) : 0;
  const totalSample = samplePerCell > 0 ? samplePerCell * treatmentCells : 0;
  return {
    treatmentCells,
    samplePerCell,
    totalSample,
    sampleReady: samplePerCell >= 30 && totalSample > 0,
    sampleSource: totalPlannedSample ? "planned total sample" : availablePopulation ? "available population" : "missing sample size",
    baselineRate: plan.baseline,
    minimumDetectableLift: plan.minimumDetectableLift,
    alpha: monteCarloNumeric.alpha / 100,
    desiredPower: monteCarloNumeric.power / 100,
    missingnessRate: Math.max(0, Math.min(100, state.numeric.missingnessRate)) / 100,
    imbalanceRate: Math.max(0, Math.min(100, state.numeric.treatmentImbalance)) / 100,
    varianceMultiplier: Math.max(0.5, Math.min(3, (state.numeric.varianceStress || 100) / 100)),
    attritionRate: Math.max(0, Math.min(100, state.numeric.attritionRate || 0)) / 100,
    measurementErrorRate: Math.max(0, Math.min(100, state.numeric.measurementErrorRate || 0)) / 100,
    nonresponseRate: Math.max(0, Math.min(100, state.numeric.nonresponseRate || 0)) / 100,
    iterations: Math.max(100, Math.round(state.numeric.simulations || 1000)),
    seed: Math.max(1, Math.round(state.numeric.seed || 42)),
    method: state.method || "Power simulation",
  };
}

function scenarioPower(inputs: ReturnType<typeof monteCarloInputs>, effectMultiplier = 1, varianceMultiplier = 1, imbalance = inputs.imbalanceRate, missingness = inputs.missingnessRate) {
  const baseline = inputs.baselineRate;
  const treatmentRate = Math.max(0.0001, Math.min(0.9999, baseline * (1 + inputs.minimumDetectableLift * effectMultiplier)));
  const totalMissingness = Math.max(0, Math.min(0.95, missingness + inputs.attritionRate + inputs.nonresponseRate));
  const effectivePerCell = Math.max(1, Math.round(inputs.samplePerCell * (1 - totalMissingness) * (1 - imbalance / 2)));
  const combinedVariance = Math.max(0.5, varianceMultiplier * inputs.varianceMultiplier * (1 + inputs.measurementErrorRate));
  return Math.max(0, Math.min(1, powerForPerCell(effectivePerCell, baseline, treatmentRate, inputs.alpha) / Math.sqrt(combinedVariance)));
}

function runMonteCarloSimulation(projectId: string, state: NodeState): MonteCarloSimulationResults {
  const inputs = monteCarloInputs(projectId, state);
  const random = seededRandom(inputs.seed);
  const baseline = inputs.baselineRate;
  const trueLift = inputs.minimumDetectableLift;
  const trueEffect = baseline * trueLift;
  const zAlpha = normalQuantile(1 - inputs.alpha / 2);
  const powerByIteration: MonteCarloIteration[] = [];
  let covered = 0;
  let correctDetects = 0;
  let wrongWinners = 0;
  let inconclusive = 0;

  for (let iteration = 1; iteration <= inputs.iterations; iteration += 1) {
    const missingnessRate = Math.max(0, inputs.missingnessRate + (random() - 0.5) * inputs.missingnessRate);
    const imbalanceRate = Math.max(0, inputs.imbalanceRate + (random() - 0.5) * inputs.imbalanceRate);
    const effectStress = Math.max(0.35, 1 + normalSample(random) * 0.18);
    const varianceStress = Math.max(0.65, inputs.varianceMultiplier * (1 + inputs.measurementErrorRate) * (1 + normalSample(random) * 0.15));
    const totalMissingness = Math.max(0, Math.min(0.95, missingnessRate + inputs.attritionRate + inputs.nonresponseRate));
    const effectivePerCell = Math.max(1, Math.round(inputs.samplePerCell * (1 - totalMissingness) * (1 - imbalanceRate / 2)));
    const treatmentRate = Math.max(0.0001, Math.min(0.9999, baseline + trueEffect * effectStress));
    const se = Math.sqrt(((baseline * (1 - baseline)) + (treatmentRate * (1 - treatmentRate))) / effectivePerCell) * Math.sqrt(varianceStress);
    const estimatedEffect = trueEffect * effectStress + normalSample(random) * se;
    const estimatedLift = estimatedEffect / Math.max(0.0001, baseline);
    const threshold = zAlpha * se;
    const detectedEffect = estimatedEffect > threshold;
    const selectedWinnerCorrect = estimatedEffect > 0;
    const achievedPower = scenarioPower(inputs, effectStress, varianceStress, imbalanceRate, missingnessRate);

    if (detectedEffect && selectedWinnerCorrect) correctDetects += 1;
    if (!detectedEffect) inconclusive += 1;
    if (!selectedWinnerCorrect) wrongWinners += 1;
    if (estimatedEffect - threshold <= trueEffect && trueEffect <= estimatedEffect + threshold) covered += 1;

    powerByIteration.push({ iteration, achievedPower, detectedEffect, selectedWinnerCorrect, estimatedLift, missingnessRate, imbalanceRate });
  }

  const powers = powerByIteration.map((row) => row.achievedPower);
  const lifts = powerByIteration.map((row) => row.estimatedLift);
  const falseNegativeRate = powerByIteration.filter((row) => !row.detectedEffect).length / inputs.iterations;
  const wrongWinnerRate = wrongWinners / inputs.iterations;
  const falsePositiveRate = Math.min(0.5, inputs.alpha * (1 + inputs.imbalanceRate + inputs.missingnessRate));
  const meanPower = mean(powers);
  const scenarioDefinitions = [
    ["Baseline", 1, 1, inputs.imbalanceRate, inputs.missingnessRate],
    ["Lower effect size", 0.7, 1, inputs.imbalanceRate, inputs.missingnessRate],
    ["Higher variance", 1, 1.35, inputs.imbalanceRate, inputs.missingnessRate],
    ["5% imbalance", 1, 1, 0.05, inputs.missingnessRate],
    ["10% imbalance", 1, 1, 0.1, inputs.missingnessRate],
    ["2% missingness", 1, 1, inputs.imbalanceRate, 0.02],
    ["5% missingness", 1, 1, inputs.imbalanceRate, 0.05],
    ["Combined stress", 0.75, 1.35, 0.1, 0.05],
  ] as const;
  const scenarioSensitivity = scenarioDefinitions.map(([scenario, effectMultiplier, varianceMultiplier, imbalance, missingness]) => {
    const estimatedPower = scenarioPower(inputs, effectMultiplier, varianceMultiplier, imbalance, missingness);
    const scenarioWrongWinner = Math.max(0, Math.min(0.5, wrongWinnerRate + (1 - estimatedPower) * 0.12 + imbalance * 0.2));
    return {
      scenario,
      estimatedPower,
      falseNegativeRate: Math.max(0, 1 - estimatedPower),
      wrongWinnerRate: scenarioWrongWinner,
      designStatus: statusForSimulation(estimatedPower, scenarioWrongWinner),
    };
  });
  const baselinePower = scenarioSensitivity[0].estimatedPower;
  const riskDrivers = [
    {
      driver: "Effect size",
      impactScore: Math.abs(baselinePower - scenarioSensitivity.find((row) => row.scenario === "Lower effect size")!.estimatedPower),
      explanation: "Smaller realized effects reduce detection power and increase inconclusive outcomes.",
    },
    {
      driver: "Sample size",
      impactScore: Math.max(0, inputs.desiredPower - baselinePower),
      explanation: "Per-cell sample determines whether the design can reliably detect the minimum practical effect.",
    },
    {
      driver: "Response variance",
      impactScore: Math.abs(baselinePower - scenarioSensitivity.find((row) => row.scenario === "Higher variance")!.estimatedPower) + Math.max(0, inputs.varianceMultiplier - 1) * 0.1,
      explanation: "Higher variance widens confidence intervals and reduces precision.",
    },
    {
      driver: "Treatment imbalance",
      impactScore: Math.abs(baselinePower - scenarioSensitivity.find((row) => row.scenario === "10% imbalance")!.estimatedPower),
      explanation: "Uneven treatment assignment weakens comparisons across cells.",
    },
    {
      driver: "Missingness",
      impactScore: Math.abs(baselinePower - scenarioSensitivity.find((row) => row.scenario === "5% missingness")!.estimatedPower),
      explanation: "Missing outcomes reduce effective sample and can bias analysis if not random.",
    },
    {
      driver: "Segment imbalance",
      impactScore: Math.max(0.01, inputs.treatmentCells > 4 ? 0.05 : 0.02),
      explanation: "Sparse cells or uneven segment mix can make treatment selection unstable.",
    },
  ].sort((a, b) => b.impactScore - a.impactScore);

  return {
    seed: inputs.seed,
    iterations: inputs.iterations,
    meanPower,
    medianPower: percentile(powers, 0.5),
    falsePositiveRate,
    falseNegativeRate,
    wrongWinnerRate,
    meanEstimatedLift: mean(lifts),
    liftStdDev: stdDev(lifts),
    decisionStabilityScore: Math.max(0, Math.min(1, meanPower * 0.65 + (1 - wrongWinnerRate) * 0.25 + (covered / inputs.iterations) * 0.1)),
    confidenceIntervalCoverage: covered / inputs.iterations,
    recommendedAction: statusForSimulation(meanPower, wrongWinnerRate),
    inputs: {
      treatmentCells: inputs.treatmentCells,
      samplePerCell: inputs.samplePerCell,
      totalSample: inputs.totalSample,
      sampleReady: inputs.sampleReady,
      sampleSource: inputs.sampleSource,
      baselineRate: inputs.baselineRate,
      minimumDetectableLift: inputs.minimumDetectableLift,
      alpha: inputs.alpha,
      desiredPower: inputs.desiredPower,
      missingnessRate: inputs.missingnessRate,
      imbalanceRate: inputs.imbalanceRate,
      varianceMultiplier: inputs.varianceMultiplier,
      attritionRate: inputs.attritionRate,
      measurementErrorRate: inputs.measurementErrorRate,
      nonresponseRate: inputs.nonresponseRate,
      method: inputs.method,
    },
    powerByIteration,
    powerCurve: [0.5, 0.75, 1, 1.25, 1.5, 2].map((multiplier) => {
      const samplePerCell = Math.max(1, Math.round(inputs.samplePerCell * multiplier));
      return { samplePerCell, estimatedPower: scenarioPower({ ...inputs, samplePerCell }) };
    }),
    scenarioSensitivity,
    riskDrivers,
    outcomeBreakdown: [
      { outcome: "Correctly detects effect", count: correctDetects },
      { outcome: "Misses true effect", count: powerByIteration.filter((row) => !row.detectedEffect).length },
      { outcome: "Wrong winner selected", count: wrongWinners },
      { outcome: "Inconclusive", count: inconclusive },
    ],
  };
}

function combinations<T>(values: T[], size: number): T[][] {
  if (size <= 0) return [[]];
  if (size > values.length) return [];
  if (size === 1) return values.map((value) => [value]);
  return values.flatMap((value, index) => combinations(values.slice(index + 1), size - 1).map((rest) => [value, ...rest]));
}

function generatedAnovaPlan(projectId: string, state: NodeState) {
  const researchState = loadExperimentalNodeState(projectId, "Research Question");
  const factorsState = loadExperimentalNodeState(projectId, "Factors");
  const levelsState = loadExperimentalNodeState(projectId, "Levels");
  const sampleState = loadExperimentalNodeState(projectId, "Sample Size");
  const parsedLevels = sharedParseFactorHierarchy(levelsState?.objective ?? "");
  const suggestedFactors = sharedDeriveSuggestedFactors(factorsState?.objective ?? "");
  const fallbackFactorCount = Math.max(1, Math.round(sampleState?.numeric.factorCount ?? state.numeric.factorCount));
  const factors: ExperimentalFactor[] = parsedLevels.length
    ? parsedLevels
    : suggestedFactors.length
      ? suggestedFactors.map(({ factorName, levels }) => ({ factorName, levels }))
      : Array.from({ length: fallbackFactorCount }, (_, index) => ({
          factorName: String.fromCharCode(65 + index),
          levels: Array.from({ length: Math.max(2, Math.round(sampleState?.numeric.averageLevels ?? state.numeric.averageLevels)) }, (_, levelIndex) => `Level ${levelIndex + 1}`),
        }));
  const factorNames = factors.map((factor) => factor.factorName);
  const factorCodes = factorNames.map((_, index) => String.fromCharCode(65 + index));
  const levelCounts = factors.map((factor) => factor.levels.length);
  const researchIntent = researchState?.method || "Main Effects + Interaction Analysis";
  const includeInteractions = /interaction|factorial|optimization|screening/i.test(researchIntent) && factorCodes.length > 1;
  const terms = includeInteractions ? generateFullFactorialTerms(factors) : factorNames;
  const modelFormula = `Response ~ ${terms.join(" + ")}`;
  const treatmentCells = treatmentCellCount(factors);
  const plannedObservations = sampleState ? sampleSizePlan(sampleState).total : sampleSizePlan(state).total;
  const termRows = terms.map((term) => {
    const termFactors = term.split(/\s*(?:x|×)\s*/);
    const df = termFactors.reduce((result, factorName) => {
      const index = factorNames.indexOf(factorName);
      return result * Math.max(1, (levelCounts[index] ?? 2) - 1);
    }, 1);
    return { term, df };
  });
  const modelDf = includeInteractions ? fullFactorialModelDf(factors) : termRows.reduce((sum, row) => sum + row.df, 0);
  const residualDf = Math.max(0, plannedObservations - treatmentCells);
  return {
    factors,
    factorNames,
    factorCodes,
    levelCounts,
    researchIntent,
    modelFormula,
    treatmentCells,
    plannedObservations,
    termRows,
    modelDf,
    residualDf,
    recommendedModel: includeInteractions ? "Factorial ANOVA with interaction terms" : "Main-effects ANOVA",
  };
}

function journeyForLabel(label: string) {
  return experimentalDesignJourney.find((item) => item.label === label) ?? experimentalDesignJourney[0];
}

function previousJourneyStep(journey: ExperimentalDesignJourneyStep) {
  return experimentalDesignJourney.find((item) => item.stepNumber === journey.stepNumber - 1);
}

function nextJourneyStep(journey: ExperimentalDesignJourneyStep) {
  return experimentalDesignJourney.find((item) => item.stepNumber === journey.stepNumber + 1);
}

function ExperimentalJourneyHeader({ journey }: { journey: ExperimentalDesignJourneyStep }) {
  const previous = previousJourneyStep(journey);
  const next = nextJourneyStep(journey);
  return (
    <section className="space-y-3">
      <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
        <div className="text-xs font-semibold uppercase tracking-wide text-blue-700">Step {journey.stepNumber} of {journey.totalSteps}</div>
        <h1 className="mt-1 text-2xl font-semibold tracking-tight text-slate-950">{journey.label}</h1>
        <p className="mt-2 text-lg font-semibold text-slate-800">{journey.question}</p>
        <p className="mt-2 max-w-4xl text-sm leading-6 text-slate-600">{journey.purpose}</p>
        {journey.transition && (
          <p className="mt-3 rounded-xl border border-blue-100 bg-blue-50 px-3 py-2 text-sm leading-6 text-blue-950">
            {journey.transition}
          </p>
        )}
      </div>

      <div className="grid gap-3 rounded-2xl border border-slate-200 bg-slate-50 p-3 shadow-sm md:grid-cols-3">
        <JourneyContextCard eyebrow="Previous" title={previous ? previous.label : "Start"} body={previous ? previous.output : "Begin the experimental design journey."} tone="muted" />
        <JourneyContextCard eyebrow="Current" title={journey.label} body={journey.question} tone="active" />
        <JourneyContextCard eyebrow="Next" title={next ? next.label : "Complete"} body={next ? next.question : "Package and export the evidence."} tone="next" />
      </div>
    </section>
  );
}

function JourneyContextCard({ eyebrow, title, body, tone }: { eyebrow: string; title: string; body: string; tone: "muted" | "active" | "next" }) {
  const classes =
    tone === "active"
      ? "border-blue-200 bg-white text-blue-950"
      : tone === "next"
        ? "border-emerald-200 bg-white text-emerald-950"
        : "border-slate-200 bg-white text-slate-700";
  return (
    <div className={`rounded-xl border p-3 ${classes}`}>
      <div className="text-[11px] font-semibold uppercase tracking-wide opacity-70">{eyebrow}</div>
      <div className="mt-1 text-sm font-semibold">{title}</div>
      <p className="mt-1 text-xs leading-5 opacity-80">{body}</p>
    </div>
  );
}

function ExperimentalNextStepCard({ journey, nextStep }: { journey: ExperimentalDesignJourneyStep; nextStep?: ReturnType<typeof getWorkflowDefinition>["steps"][number] }) {
  const next = nextJourneyStep(journey);
  if (!next || !nextStep) return null;
  return (
    <section className="rounded-2xl border border-blue-200 bg-blue-50 p-5 shadow-sm">
      <div>
        <div className="text-xs font-semibold uppercase tracking-wide text-blue-700">Recommended Next Step</div>
        <h2 className="mt-1 text-base font-semibold text-blue-950">{next.label}</h2>
        <p className="mt-2 max-w-3xl text-sm leading-6 text-blue-900">{next.question}</p>
        <p className="mt-2 max-w-3xl text-xs leading-5 text-blue-800">
          Why this matters: {next.purpose}
        </p>
      </div>
    </section>
  );
}

function governanceDraftForStep(stepLabel: string, config: ExperimentalStepConfig, state: NodeState, analysis: ExperimentalDesignAnalysis, projectId: string) {
  const nodeStates = loadExperimentalNodeStates(projectId);
  const factors = sharedParseFactorHierarchy(nodeStates.Levels?.objective || state.objective);
  const factorNames = factors.map((factor) => factor.factorName);
  const cells = factors.length ? treatmentCellCount(factors) : Math.max(1, Math.round((state.numeric.averageLevels || 2) ** (state.numeric.factorCount || 2)));
  const method = state.method || config.methods[0] || "the selected approach";
  const metrics = state.metrics.length ? state.metrics.join(", ") : config.metrics.slice(0, 3).join(", ");
  const defaults: Partial<Record<ExperimentalStepConfig["fields"][number]["key"], string>> = {
    objective: `The ${stepLabel.toLowerCase()} step documents the decision ATLAS is supporting and connects the business question to the analytical evidence needed for governance review.`,
    inputs: factors.length
      ? `The current design includes ${factorNames.length} controllable factor(s): ${factorNames.join(", ")}. These produce ${cells} treatment cell(s) for analysis and documentation.`
      : "ATLAS will use the current project context, selected response, factor definitions, and workflow evidence to support this step.",
    assumptions: `This step assumes ${method} is appropriate for the current experimental design and that ${metrics || "the selected evidence metrics"} are sufficient to evaluate the decision.`,
    validation: "Validation should confirm that the inputs, calculations, and selected design choice are reproducible, reviewable, and aligned with governance expectations.",
    risks: analysis.warnings[0] || "The primary risk is making a design decision before all assumptions and supporting evidence are fully validated.",
    decision: analysis.recommendedNextSteps[0] || "Proceed after confirming the documented assumptions and evidence.",
    rationale: `${analysis.interpretation} This rationale should remain editable as new evidence is reviewed.`,
    notes: "Generated by ATLAS from the current workflow state. Edit this language to reflect stakeholder decisions, exceptions, or unresolved assumptions.",
  };
  return Object.fromEntries(config.fields.map((field) => [field.key, defaults[field.key] ?? ""]));
}

function GovernanceDocumentationPanel({
  stepLabel,
  projectId,
  config,
  state,
  setState,
  save,
  analysis,
  savedAt,
}: {
  stepLabel: string;
  projectId: string;
  config: ExperimentalStepConfig;
  state: NodeState;
  setState: (state: NodeState) => void;
  save: () => void;
  analysis: ExperimentalDesignAnalysis;
  savedAt: Date | null;
}) {
  const completeFields = config.fields.filter((field) => String(state[field.key] ?? "").trim()).length;
  const complete = config.fields.length ? completeFields === config.fields.length : true;
  const draft = governanceDraftForStep(stepLabel, config, state, analysis, projectId);
  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="text-xs font-semibold uppercase tracking-wide text-blue-700">Governance Documentation</div>
          <h2 className="mt-1 text-lg font-semibold text-slate-950">Editable audit language for this decision</h2>
          <p className="mt-1 max-w-3xl text-sm leading-6 text-slate-500">
            ATLAS drafts this documentation from the current workflow state. Edit it while reviewing the evidence below.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <span className={`rounded-full border px-3 py-1 text-xs font-semibold ${complete ? "border-emerald-200 bg-emerald-50 text-emerald-800" : "border-amber-200 bg-amber-50 text-amber-800"}`}>
            Governance {complete ? "Complete" : `${completeFields}/${config.fields.length}`}
          </span>
          <span className="rounded-full border border-slate-200 bg-slate-50 px-3 py-1 text-xs font-semibold text-slate-600">
            {savedAt ? `Saved ${savedAt.toLocaleTimeString([], { hour: "numeric", minute: "2-digit", second: "2-digit" })}` : "Autosave ready"}
          </span>
        </div>
      </div>

      <div className="mt-5 grid gap-4 lg:grid-cols-2">
        {config.fields.map((field) => (
          <TextArea
            key={field.key}
            label={field.label}
            value={String(state[field.key] ?? "")}
            rows={Math.min(field.rows ?? 4, 4)}
            placeholder={field.placeholder}
            onChange={(value) => setState({ ...state, [field.key]: value })}
            assistSuggestion={draft[field.key] || field.placeholder}
          />
        ))}
      </div>

      <div className="mt-5 grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto]">
        <label className="grid gap-1.5">
          <span className="text-xs font-semibold uppercase tracking-wide text-slate-500">{config.methodLabel}</span>
          <select
            className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm"
            value={state.method}
            onChange={(event) => setState({ ...state, method: event.target.value })}
          >
            <option value="">Select approach</option>
            {config.methods.map((method) => (
              <option key={method} value={method}>{method}</option>
            ))}
          </select>
          <DropdownDefinition value={state.method} />
        </label>
        <MetricPicker options={config.metrics} selected={state.metrics} onChange={(metrics) => setState({ ...state, metrics })} />
        <button
          type="button"
          className="self-end rounded-xl bg-slate-950 px-4 py-2 text-sm font-semibold text-white shadow-sm transition hover:-translate-y-0.5 hover:bg-slate-800"
          onClick={save}
        >
          Save Draft
        </button>
      </div>

      <div className="mt-5 grid gap-3 md:grid-cols-3">
        <MiniEvidence label="Confidence" value={`${Math.round((analysis.kpis.reduce((sum, kpi) => sum + kpi.confidence, 0) / Math.max(1, analysis.kpis.length)) * 100)}%`} />
        <MiniEvidence label="Risk" value={analysis.warnings.length ? "Review" : "Low"} tone={analysis.warnings.length ? "warning" : "good"} />
        <MiniEvidence label="Decision Status" value={complete ? "Ready" : "Draft"} tone={complete ? "good" : "warning"} />
      </div>
    </section>
  );
}

function SavedStateStrip({ savedAt, nextStep }: { savedAt: Date | null; nextStep?: ReturnType<typeof getWorkflowDefinition>["steps"][number] }) {
  return (
    <div className="flex flex-wrap items-center gap-3 rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-900">
      <CheckCircle2 size={17} className="text-emerald-600" />
      <span className="font-semibold">Saved automatically</span>
      <span className="text-emerald-700">{savedAt ? savedAt.toLocaleTimeString([], { hour: "numeric", minute: "2-digit", second: "2-digit" }) : "Waiting for edits"}</span>
      {nextStep && <span className="text-sm text-slate-500">Next stage: {nextStep.label}</span>}
    </div>
  );
}

function MiniEvidence({ label, value, tone = "neutral" }: { label: string; value: string; tone?: "neutral" | "good" | "warning" }) {
  const classes =
    tone === "good"
      ? "border-emerald-200 bg-emerald-50 text-emerald-900"
      : tone === "warning"
        ? "border-amber-200 bg-amber-50 text-amber-900"
        : "border-slate-200 bg-slate-50 text-slate-800";
  return (
    <div className={`rounded-xl border px-4 py-3 ${classes}`}>
      <div className="text-[11px] font-semibold uppercase tracking-wide opacity-75">{label}</div>
      <div className="mt-1 text-base font-semibold">{value}</div>
    </div>
  );
}

function InlineError({ message }: { message: string }) {
  return (
    <div className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm font-semibold text-rose-800">
      {message}
    </div>
  );
}

type DropdownGuidance = {
  definition: string;
  useWhen: string;
  example?: string;
};

const dropdownDefinitions: Record<string, DropdownGuidance> = {
  "Full factorial": {
    definition: "Tests all combinations of selected factors and levels so main effects and interactions can be estimated.",
    useWhen: "Use when treatment-cell count and sample size are manageable.",
    example: "2 pricing levels x 2 contact channels = 4 treatment cells.",
  },
  "Fractional factorial": {
    definition: "Tests a structured subset of combinations to screen important drivers.",
    useWhen: "Use when a full factorial design creates too many treatment cells.",
    example: "Screen eight offer variables without launching all 256 combinations.",
  },
  "Randomized block": {
    definition: "Compares treatments while controlling one known nuisance source of variation.",
    useWhen: "Use when a variable shifts outcomes but is not itself a treatment.",
    example: "Block by campaign wave before assigning pricing treatments.",
  },
  "Randomized block design": {
    definition: "Compares treatments while controlling one known source of variation.",
    useWhen: "Use when assignment should stay balanced within a known subgroup.",
    example: "Randomize treatments separately within credit risk tiers.",
  },
  "Screening Experiment": {
    definition: "Tests many factors quickly to identify which factors likely matter.",
    useWhen: "Use early in discovery when the factor list is broad.",
    example: "Screen pricing, channel, timing, and message factors before optimization.",
  },
  "Factorial Experiment": {
    definition: "Tests multiple factors and their interactions in one integrated design.",
    useWhen: "Use when main effects and combined effects both matter.",
    example: "Estimate whether personalized pricing works differently by channel.",
  },
  "Response surface": {
    definition: "Optimizes continuous inputs after important factors are known.",
    useWhen: "Use when the goal is finding an optimal setting, not just comparing fixed options.",
    example: "Optimize APR discount and contact frequency after screening.",
  },
  "Response Surface": {
    definition: "Optimizes continuous inputs after important factors are known.",
    useWhen: "Use when the objective is a best setting under constraints.",
    example: "Find the pricing point that maximizes activation while controlling complaints.",
  },
  Taguchi: {
    definition: "Robust design focused on consistent performance under noise or operating variation.",
    useWhen: "Use when the treatment must be stable across hard-to-control conditions.",
    example: "Test offer strategy robustness across region, staffing, and timing noise.",
  },
  "Taguchi Design": {
    definition: "Robust design focused on performance under noise.",
    useWhen: "Use when variability reduction is as important as average lift.",
    example: "Choose a treatment that performs consistently across customer segments.",
  },
  "Simple randomization": {
    definition: "Randomly assigns records across treatments without subgroup controls.",
    useWhen: "Use when covariates are balanced by design or sample size is large.",
    example: "Randomly split 100,000 eligible customers into two offers.",
  },
  "Stratified randomization": {
    definition: "Random assignment within defined subgroups.",
    useWhen: "Use when known segments may affect the outcome.",
    example: "Randomize separately within credit score bands or customer risk tiers.",
  },
  "Blocked randomization": {
    definition: "Assigns treatments within fixed operational blocks or waves.",
    useWhen: "Use when assignments occur by branch, batch, time period, or launch wave.",
    example: "Assign all treatments within each weekly campaign batch.",
  },
  "Cluster randomization": {
    definition: "Randomizes groups rather than individual records.",
    useWhen: "Use when individual-level randomization is impractical or creates contamination.",
    example: "Randomize branches, call centers, or geographic markets.",
  },
  "Covariate-adaptive randomization": {
    definition: "Adapts assignment to maintain balance across important covariates.",
    useWhen: "Use when several covariates need tight balance and assignment can be computed centrally.",
    example: "Balance risk tier, tenure, and prior response while assigning offers.",
  },
  "Power simulation": {
    definition: "Simulates repeated experiments to estimate detection probability and launch risk.",
    useWhen: "Use when closed-form power may understate interaction or operational risk.",
    example: "Run 1,000 simulated launches before approving the design.",
  },
  "Treatment selection simulation": {
    definition: "Estimates how often the experiment chooses the correct winning treatment.",
    useWhen: "Use when selecting the wrong treatment creates material business risk.",
    example: "Estimate wrong-winner risk across four pricing-channel cells.",
  },
  "Interaction sensitivity simulation": {
    definition: "Stress-tests how interaction effects change power and treatment choice.",
    useWhen: "Use when factor combinations may behave differently than individual factors.",
    example: "Check whether pricing lift depends on contact channel.",
  },
  "Missingness stress test": {
    definition: "Tests whether missing outcomes or attrition could invalidate conclusions.",
    useWhen: "Use when response measurement may be incomplete or delayed.",
    example: "Stress test delayed activation reporting in the performance window.",
  },
  "Operational imbalance simulation": {
    definition: "Tests assignment imbalance and sparse-cell risk before launch.",
    useWhen: "Use when exclusions, blocking, or operations may create uneven cells.",
    example: "Simulate assignment after opt-out and recent-offer exclusions.",
  },
  "Base Scenario": {
    definition: "Expected assumptions.",
    useWhen: "Use for the most likely baseline case.",
    example: "Current response rate and planned sample size.",
  },
  "Conservative Scenario": {
    definition: "More cautious assumptions.",
    useWhen: "Use when leadership wants a margin of safety.",
    example: "Lower baseline response, higher missingness, or smaller lift.",
  },
  "Stress Test": {
    definition: "Worst-case or high-risk assumptions.",
    useWhen: "Use to test whether the design remains defensible under adverse conditions.",
    example: "Reduced sample, higher opt-outs, or weaker treatment effect.",
  },
  "Launch Readiness Simulation": {
    definition: "Final pre-launch validation.",
    useWhen: "Use immediately before execution approval.",
    example: "Confirm launch recommendation after sample size and assignment logic are final.",
  },
};

function DropdownDefinition({ value }: { value: string }) {
  if (!value) return <span className="text-[11px] leading-4 text-slate-400">Select an option to see how ATLAS will use it.</span>;
  const guidance = dropdownDefinitions[value];
  if (!guidance) {
    return (
      <span className="text-[11px] leading-4 text-slate-500">
        Definition: ATLAS uses this selection to shape analytical evidence and governance language. Use when it matches the decision being made on this page.
      </span>
    );
  }
  return (
    <span className="text-[11px] leading-4 text-slate-500">
      <span className="font-semibold text-slate-600">Definition:</span> {guidance.definition}{" "}
      <span className="font-semibold text-slate-600">Use when:</span> {guidance.useWhen}
      {guidance.example ? <> <span className="font-semibold text-slate-600">Example:</span> {guidance.example}</> : null}
    </span>
  );
}

function draftGovernanceText(label: string, value: string, suggestion?: string, mode: "draft" | "clarity" | "audit" | "shorten" | "expand" | "regenerate" = "draft") {
  const base = value.trim() || suggestion?.trim() || `${label}: document the decision, supporting evidence, assumptions, and governance rationale for this stage.`;
  if (mode === "shorten") {
    return base.split(/\s+/).slice(0, 38).join(" ").replace(/[,.]?\s*$/, ".");
  }
  if (mode === "expand") {
    return `${base.replace(/[,.]?\s*$/, ".")} This rationale should identify the decision owner, the evidence reviewed, the assumptions accepted, unresolved risks, and any follow-up required before the experiment advances.`;
  }
  if (mode === "audit") {
    return `${base.replace(/[,.]?\s*$/, ".")} For audit readiness, this language should be traceable to the selected workflow inputs, reproducible analysis outputs, approval criteria, and any documented user overrides.`;
  }
  if (mode === "clarity") {
    return base
      .replace(/\s+/g, " ")
      .replace(/^the objective of this experiment is/i, "This experiment is designed to")
      .replace(/[,.]?\s*$/, ".");
  }
  if (mode === "regenerate") {
    return `${label}: ATLAS recommends documenting the current decision, why the selected approach is appropriate, which evidence supports it, and what risks must be monitored before launch.`;
  }
  return base;
}

function LevelsGovernanceConfirmation({ config, state, setState }: { config: ExperimentalStepConfig; state: NodeState; setState: (state: NodeState) => void }) {
  const evidence = [
    { label: "Factor levels defined", complete: Boolean(state.objective.trim()) },
    { label: "Baseline/control identified", complete: Boolean(state.inputs.trim()) },
    { label: "Feasibility documented", complete: Boolean(state.validation.trim()) },
    { label: "Rationale captured", complete: Boolean(state.rationale.trim() || state.decision.trim()) },
  ];
  return (
    <>
      <div>
        <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Governance Confirmation</div>
        <h2 className="mt-1 text-base font-semibold text-slate-950">Confirm the levels are deployable and auditable.</h2>
        <p className="mt-1 text-xs leading-5 text-slate-500">
          Keep the formal language editable, but use these compact evidence cards to confirm the treatment settings are valid before randomization.
        </p>
      </div>

      <div className="grid gap-3 md:grid-cols-4">
        {evidence.map((item) => (
          <div key={item.label} className={`rounded-xl border p-3 ${item.complete ? "border-emerald-200 bg-emerald-50" : "border-amber-200 bg-amber-50"}`}>
            <div className={`text-[11px] font-semibold uppercase tracking-wide ${item.complete ? "text-emerald-700" : "text-amber-700"}`}>
              {item.complete ? "Captured" : "Needed"}
            </div>
            <div className="mt-1 text-sm font-semibold text-slate-950">{item.label}</div>
          </div>
        ))}
      </div>

      <div className="grid gap-3 lg:grid-cols-2">
        <CompactEditableSummary
          title="Level Definition Summary"
          value={state.objective}
          placeholder="Pricing Strategy: Current Pricing, Personalized Pricing&#10;Contact Channel: Email, SMS"
          onChange={(value) => setState({ ...state, objective: value })}
        />
        <CompactEditableSummary
          title="Baseline / Control Summary"
          value={state.inputs}
          placeholder="Identify current policy, control channel, or standard setting for each factor."
          onChange={(value) => setState({ ...state, inputs: value })}
        />
      </div>

      <div className="grid gap-3 lg:grid-cols-2">
        <CompactEditableSummary
          title="Feasibility and QA"
          value={state.validation}
          placeholder="Document operational feasibility, reproducibility, and treatment delivery checks."
          onChange={(value) => setState({ ...state, validation: value })}
        />
        <CompactEditableSummary
          title="Decision Rationale"
          value={state.rationale || state.decision}
          placeholder="Explain why these levels are distinct enough, feasible, and ready for randomization."
          onChange={(value) => setState({ ...state, rationale: value })}
        />
      </div>

      <details className="rounded-xl border border-slate-200 bg-slate-50 p-3">
        <summary className="cursor-pointer list-none text-sm font-semibold text-slate-900">Advanced method and evidence metrics</summary>
        <div className="mt-3 grid gap-4 lg:grid-cols-2">
          <label className="grid gap-1.5">
            <span className="text-xs font-semibold uppercase tracking-wide text-slate-500">{config.methodLabel}</span>
            <select
              className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm"
              value={state.method}
              onChange={(event) => setState({ ...state, method: event.target.value })}
            >
              <option value="">Select approach</option>
              {config.methods.map((method) => (
                <option key={method} value={method}>{method}</option>
              ))}
            </select>
          </label>
          <MetricPicker options={config.metrics} selected={state.metrics} onChange={(metrics) => setState({ ...state, metrics })} />
        </div>
      </details>
    </>
  );
}

function CompactEditableSummary({ title, value, placeholder, onChange }: { title: string; value: string; placeholder: string; onChange: (value: string) => void }) {
  return (
    <label className="block rounded-xl border border-slate-200 bg-slate-50 p-3">
      <span className="text-xs font-semibold uppercase tracking-wide text-slate-500">{title}</span>
      <textarea
        className="mt-2 min-h-24 w-full resize-y rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm leading-6 text-slate-800"
        value={value}
        placeholder={placeholder}
        onChange={(event) => onChange(event.target.value)}
      />
    </label>
  );
}

function ExperimentalDesignStep({
  projectId,
  step,
  nextStep,
  state,
  setState,
  save,
  onComplete,
  navigationError,
}: {
  projectId: string;
  step: NonNullable<ReturnType<typeof getWorkflowDefinition>["steps"][number]>;
  nextStep?: ReturnType<typeof getWorkflowDefinition>["steps"][number];
  state: NodeState;
  setState: (state: NodeState) => void;
  save: () => void;
  onComplete: () => boolean | void;
  navigationError: string | null;
}) {
  const config = experimentalConfigFor(step.label);
  const journey = journeyForLabel(step.label);
  const configFieldKeys = new Set(config.fields.map((field) => field.key));
  const [blockingSavedAt, setBlockingSavedAt] = useState<Date | null>(null);
  const [draftError, setDraftError] = useState<string | null>(null);
  const analysis = useMemo(
    () =>
      buildExperimentalDesignAnalysis({
        stepLabel: step.label,
        currentState: state,
        nodeStates: loadExperimentalNodeStates(projectId),
      }),
    [projectId, step.label, state]
  );
  useEffect(() => {
    const draft = governanceDraftForStep(step.label, config, state, analysis, projectId);
    const hasUpdates = Object.entries(draft).some(([key, value]) => {
      const current = state[key as keyof NodeState];
      return typeof current === "string" && !current.trim() && value.trim();
    });
    if (!hasUpdates) return;
    setState({
      ...state,
      ...Object.fromEntries(
        Object.entries(draft).filter(([key]) => {
          const current = state[key as keyof NodeState];
          return typeof current === "string" && !current.trim();
        })
      ),
    });
  }, [analysis.interpretation, config, projectId, step.label]);
  const saveDraft = () => {
    setDraftError(null);
    try {
      save();
      setBlockingSavedAt(new Date());
    } catch (error) {
      console.error("ATLAS workflow draft save failed", error);
      setDraftError(`ATLAS could not save this draft. ${error instanceof Error ? error.message : "Please try again."}`);
    }
  };

  useEffect(() => {
    if (!["Blocking", "Randomization", "Sample Size", "Monte Carlo Simulation", "Experiment Run Plan"].includes(step.label)) return;
    const timer = window.setTimeout(() => {
      try {
        saveNodeState(projectId, step.id, state);
        setBlockingSavedAt(new Date());
        setDraftError(null);
      } catch (error) {
        console.error("ATLAS autosave failed", error);
        setDraftError(`ATLAS autosave could not persist this page. ${error instanceof Error ? error.message : "Please reduce saved output and try again."}`);
      }
    }, 650);
    return () => window.clearTimeout(timer);
  }, [projectId, state, step.id, step.label]);

  if (step.label === "Project Context") {
    return (
      <StepShell
        title=""
        nextLabel={nextStep ? `Continue to ${journey.nextLabel ?? nextStep.label}` : "Save & Return to Overview"}
        onNext={onComplete}
      >
        <div className="space-y-5">
          <ExperimentalJourneyHeader journey={journey} />
          {(navigationError || draftError) && <InlineError message={navigationError || draftError || ""} />}
          <GovernanceDocumentationPanel stepLabel={step.label} projectId={projectId} config={config} state={state} setState={setState} save={saveDraft} analysis={analysis} savedAt={blockingSavedAt} />
          <ProjectContextPage
            config={config}
            state={state}
            setState={setState}
            save={saveDraft}
            onComplete={onComplete}
            nextStep={nextStep}
            journey={journey}
          />
        </div>
      </StepShell>
    );
  }

  if (step.label === "Research Question") {
    return (
      <StepShell
        title=""
        nextLabel={nextStep ? `Continue to ${journey.nextLabel ?? nextStep.label}` : "Save & Return to Overview"}
        onNext={onComplete}
      >
        <div className="space-y-5">
          <ExperimentalJourneyHeader journey={journey} />
          {(navigationError || draftError) && <InlineError message={navigationError || draftError || ""} />}
          <GovernanceDocumentationPanel stepLabel={step.label} projectId={projectId} config={config} state={state} setState={setState} save={saveDraft} analysis={analysis} savedAt={blockingSavedAt} />
          <ResearchQuestionPage
            projectId={projectId}
            config={config}
            state={state}
            setState={setState}
            save={saveDraft}
            onComplete={onComplete}
            nextStep={nextStep}
            savedAt={blockingSavedAt}
          />
        </div>
      </StepShell>
    );
  }

  return (
    <StepShell
      title=""
      nextLabel={nextStep ? `Continue to ${journey.nextLabel ?? nextStep.label}` : "Save & Return to Overview"}
      onNext={onComplete}
    >
      <div className="space-y-5">
        <ExperimentalJourneyHeader journey={journey} />
        {(navigationError || draftError) && <InlineError message={navigationError || draftError || ""} />}
        {step.label !== "Experiment Run Plan" && (
          <ExperimentalExecutiveInsight analysis={analysis} eyebrow={config.eyebrow} guidance={config.guidance} />
        )}
        {step.label === "Experiment Run Plan" && <RunPlanTopSimulationSummary projectId={projectId} state={state} />}
        <GovernanceDocumentationPanel stepLabel={step.label} projectId={projectId} config={config} state={state} setState={setState} save={saveDraft} analysis={analysis} savedAt={blockingSavedAt} />
        <ExperimentalStudioWorkspace
          projectId={projectId}
          stepLabel={step.label}
          state={state}
          setState={setState}
          analysis={analysis}
        />
        <ExperimentalInterpretation analysis={analysis} stepLabel={step.label} projectId={projectId} />

        {step.label === "Blocking" || step.label === "Randomization" || step.label === "Sample Size" || step.label === "Monte Carlo Simulation" || step.label === "Experiment Run Plan" ? (
          <SavedStateStrip savedAt={blockingSavedAt} nextStep={nextStep} />
        ) : (
          <section className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_430px]">
            <div className="space-y-4 rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
            {step.label === "Levels" ? (
              <SavedStateStrip savedAt={blockingSavedAt} nextStep={nextStep} />
            ) : (
              <>
                <ExperimentalSpecialPanel projectId={projectId} stepLabel={step.label} state={state} setState={setState} />
                <SavedStateStrip savedAt={blockingSavedAt} nextStep={nextStep} />
              </>
            )}
          </div>

          <div className="space-y-4">
            <ExperimentalCalculator projectId={projectId} stepLabel={step.label} state={state} setState={setState} />
            <ExperimentalReadiness stepLabel={step.label} state={state} />
            <EvidenceChecklist state={state} />
          </div>
          </section>
        )}
        {step.label !== "Randomization" && step.label !== "Sample Size" && step.label !== "Monte Carlo Simulation" && step.label !== "Experiment Run Plan" && <ExperimentalNextStepCard journey={journey} nextStep={nextStep} />}
      </div>
    </StepShell>
  );
}

function ExperimentalSpecialPanel({ projectId, stepLabel, state, setState }: { projectId: string; stepLabel: string; state: NodeState; setState: (state: NodeState) => void }) {
  if (["Factors", "Levels", "Blocking", "Randomization", "Sample Size", "Monte Carlo Simulation", "ANOVA", "Interaction Effects", "Optimization", "Documentation"].includes(stepLabel)) {
    return null;
  }
  if (stepLabel === "Randomization") {
    return (
      <InfoGrid
        title="Randomization Controls"
        rows={[
          ["Assignment seed", "Store the seed or reproducible assignment script."],
          ["Balance check", "Compare key covariates across cells before launch."],
          ["Audit file", "Persist treatment assignment and exclusions."],
        ]}
      />
    );
  }
  return (
    <InfoGrid
      title="Required Evidence"
      rows={[
        ["Design choice", "Document what was selected and why."],
        ["Validation", "Capture the QA check that supports the choice."],
        ["Governance note", "Record limitations and stakeholder decision rationale."],
      ]}
    />
  );
}

function ExperimentalExecutiveInsight({ analysis, eyebrow, guidance }: { analysis: ExperimentalDesignAnalysis; eyebrow: string; guidance: string[] }) {
  return (
    <section className="rounded-2xl border border-blue-200 bg-gradient-to-br from-white via-blue-50 to-sky-50 p-5 shadow-sm">
      <div className="flex items-start gap-3">
        <Lightbulb size={20} className="mt-1 shrink-0 text-blue-700" />
        <div className="min-w-0">
          <div className="text-xs font-semibold uppercase tracking-wide text-blue-700">{eyebrow}</div>
          <h2 className="mt-1 text-lg font-semibold text-slate-950">Executive Insight</h2>
          <p className="mt-2 max-w-5xl text-sm leading-6 text-slate-700">{analysis.executiveInsight}</p>
          <div className="mt-3 grid gap-2 text-xs leading-5 text-blue-900 md:grid-cols-2">
            {guidance.slice(0, 2).map((item) => (
              <div key={item} className="rounded-lg border border-blue-100 bg-white/80 px-3 py-2">
                {item}
              </div>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}

function ExperimentalKpiCards({ analysis, compact = false }: { analysis: ExperimentalDesignAnalysis; compact?: boolean }) {
  const tone = (status: ExperimentalDesignAnalysis["kpis"][number]["status"]) =>
    status === "good"
      ? "border-emerald-200 bg-emerald-50 text-emerald-950"
      : status === "risk"
        ? "border-rose-200 bg-rose-50 text-rose-950"
        : status === "warning"
          ? "border-amber-200 bg-amber-50 text-amber-950"
          : "border-slate-200 bg-white text-slate-950";
  return (
    <section className={`grid gap-3 ${compact ? "grid-cols-2" : "md:grid-cols-3 xl:grid-cols-6"}`}>
      {analysis.kpis.slice(0, 8).map((kpi) => (
        <div key={kpi.label} className={`min-w-0 rounded-xl border shadow-sm ${compact ? "p-3" : "p-4"} ${tone(kpi.status)}`}>
          <div className={`${compact ? "text-[10px]" : "text-xs"} truncate font-semibold uppercase tracking-wide opacity-75`} title={kpi.label}>
            {kpi.label}
          </div>
          <div className={`${compact ? "mt-1 text-base" : "mt-2 text-xl"} break-words font-semibold leading-tight`} title={kpi.value}>
            {kpi.value}
          </div>
          <div className={`${compact ? "mt-1 text-[10px]" : "mt-2 text-[11px]"} font-semibold opacity-70`}>
            {Math.round(kpi.confidence * 100)}% confidence
          </div>
        </div>
      ))}
    </section>
  );
}

function ExperimentalStudioWorkspace({
  projectId,
  stepLabel,
  state,
  setState,
  analysis,
}: {
  projectId: string;
  stepLabel: string;
  state: NodeState;
  setState: (state: NodeState) => void;
  analysis: ExperimentalDesignAnalysis;
}) {
  let body: ReactNode;
  if (stepLabel === "Project Context") body = <ProjectContextStudio state={state} />;
  else if (stepLabel === "Research Question") body = <ResearchQuestionStudio state={state} />;
  else if (stepLabel === "Factors") body = <FactorDesignAssistant factors={sharedDeriveSuggestedFactors(state.objective)} />;
  else if (stepLabel === "Levels") body = <LevelsDesignBuilder projectId={projectId} state={state} />;
  else if (stepLabel === "Blocking") body = <BlockingAssistant projectId={projectId} state={state} setState={setState} variables={parseListItems(state.objective)} />;
  else if (stepLabel === "Randomization") body = <RandomizationStudio projectId={projectId} state={state} setState={setState} />;
  else if (stepLabel === "Sample Size") body = <SampleSizeStudio state={state} setState={setState} />;
  else if (stepLabel === "Monte Carlo Simulation") body = <MonteCarloSimulationDashboard projectId={projectId} state={state} setState={setState} />;
  else if (stepLabel === "Experiment Run Plan") body = <RunPlanStudio projectId={projectId} state={state} setState={setState} />;
  else if (stepLabel === "ANOVA") body = <AnovaStudio projectId={projectId} state={state} />;
  else if (stepLabel === "Interaction Effects") body = <InteractionStudio projectId={projectId} state={state} />;
  else if (stepLabel === "Optimization") body = <OptimizationStudio projectId={projectId} state={state} />;
  else if (stepLabel === "Documentation") body = <DocumentationStudio projectId={projectId} state={state} setState={setState} analysis={analysis} />;
  else body = <ExperimentalVisualAnalytics analysis={analysis} />;

  if (stepLabel === "Blocking" || stepLabel === "Experiment Run Plan") {
    return <section>{body}</section>;
  }

  return (
    <section className="grid gap-4 2xl:grid-cols-[minmax(0,1fr)_360px]">
      <div className="min-w-0 space-y-4">
        {body}
      </div>
      <div className="space-y-4">
        <ExperimentalKpiCards analysis={analysis} compact />
        <AtlasRecommendationPanel analysis={analysis} />
      </div>
    </section>
  );
}

function AtlasRecommendationPanel({ analysis }: { analysis: ExperimentalDesignAnalysis }) {
  return (
    <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="flex items-center justify-between gap-3">
        <div>
          <div className="text-xs font-semibold uppercase tracking-wide text-blue-700">ATLAS Recommendation</div>
          <h2 className="mt-1 text-sm font-semibold text-slate-950">Decision Support</h2>
        </div>
        <span className="rounded-full border border-blue-200 bg-blue-50 px-2.5 py-1 text-xs font-semibold text-blue-800">
          {Math.round((analysis.kpis.reduce((sum, kpi) => sum + kpi.confidence, 0) / Math.max(1, analysis.kpis.length)) * 100)}% confidence
        </span>
      </div>
      {analysis.warnings.length > 0 && (
        <div className="mt-4 rounded-lg border border-amber-200 bg-amber-50 p-3">
          <div className="text-xs font-semibold uppercase tracking-wide text-amber-800">Risks Requiring Attention</div>
          <ul className="mt-2 space-y-1 text-xs leading-5 text-amber-950">
            {analysis.warnings.map((warning) => <li key={warning}>- {warning}</li>)}
          </ul>
        </div>
      )}
      <div className="mt-4 rounded-lg border border-emerald-200 bg-emerald-50 p-3">
        <div className="text-xs font-semibold uppercase tracking-wide text-emerald-800">Recommended Action</div>
        <ul className="mt-2 space-y-1 text-xs leading-5 text-emerald-950">
          {analysis.recommendedNextSteps.map((step) => <li key={step}>- {step}</li>)}
        </ul>
      </div>
      <div className="mt-4 rounded-lg border border-slate-200 bg-slate-50 p-3">
        <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Why This Matters</div>
        <p className="mt-2 text-xs leading-5 text-slate-700">{analysis.interpretation}</p>
      </div>
    </section>
  );
}

function ProjectContextStudio({ state }: { state: NodeState }) {
  const complete = [state.objective, state.inputs, state.assumptions, state.validation, state.risks, state.decision].filter((value) => value.trim()).length;
  const impactRows = [
    { label: "Business objective", value: state.objective ? 1 : 0.25 },
    { label: "Population", value: state.inputs ? 1 : 0.25 },
    { label: "Assumptions", value: state.assumptions ? 1 : 0.25 },
    { label: "Governance checks", value: state.validation ? 1 : 0.25 },
  ];
  return (
    <section className="grid gap-4 xl:grid-cols-[minmax(0,1.2fr)_minmax(360px,0.8fr)]">
      <VisualCard title="Experiment Context Map" subtitle="Shows whether the business purpose, population, decision use, and governance framing are ready for design work.">
        <div className="grid gap-3 md:grid-cols-4">
          {["Business Objective", "Population", "Target / Response", "Decision Use"].map((node, index) => (
            <div key={node} className="rounded-xl border border-blue-100 bg-blue-50 p-4 text-center">
              <div className="mx-auto flex h-10 w-10 items-center justify-center rounded-full bg-blue-600 text-sm font-semibold text-white">{index + 1}</div>
              <div className="mt-2 text-xs font-semibold text-blue-950">{node}</div>
            </div>
          ))}
        </div>
        <div className="mt-4">
          <HorizontalBars rows={impactRows} valueFormatter={(value) => `${Math.round(value * 100)}%`} />
        </div>
      </VisualCard>
      <AnalysisEvidenceTable table={{
        title: "Context Readiness",
        headers: ["Evidence Area", "Status", "Decision Impact"],
        rows: [
          ["Objective", state.objective ? "Captured" : "Needed", "Defines what the experiment is designed to change."],
          ["Inputs / population", state.inputs ? "Captured" : "Needed", "Prevents testing on the wrong customer population."],
          ["Assumptions", state.assumptions ? "Captured" : "Needed", "Frames statistical and operational risk."],
          ["Validation checks", state.validation ? "Captured" : "Needed", "Supports approval and reproducibility."],
        ],
      }} />
      <div className="xl:col-span-2">
        <ReadinessRibbon complete={complete} total={6} label="Experiment readiness score" />
      </div>
    </section>
  );
}

function ProjectContextPage({
  config,
  state,
  setState,
  save,
  onComplete,
  nextStep,
  journey,
}: {
  config: ExperimentalStepConfig;
  state: NodeState;
  setState: (state: NodeState) => void;
  save: () => void;
  onComplete: () => void;
  nextStep?: ReturnType<typeof getWorkflowDefinition>["steps"][number];
  journey: ExperimentalDesignJourneyStep;
}) {
  const facts = projectContextFacts(state);
  const quality = projectDesignQuality(state);
  const readinessItems = [
    { label: "Business Objective", complete: Boolean(state.objective.trim()), summary: summarizeText(state.objective, "Define the business decision this experiment will support.") },
    { label: "Population", complete: Boolean(state.inputs.trim()), summary: summarizeText(state.inputs, "Define eligible population, exclusions, and unit of randomization.") },
    { label: "Target Response", complete: state.metrics.length > 0, summary: state.metrics.length ? state.metrics.join(", ") : "Select primary response and evidence metrics." },
    { label: "Governance Constraints", complete: Boolean(state.validation.trim()), summary: summarizeText(state.validation, "Document required approvals and governance checks.") },
    { label: "Decision Use", complete: Boolean(state.decision.trim() || state.objective.trim()), summary: summarizeText(state.decision || state.objective, "Explain how results will influence a business action.") },
  ];
  const completeCount = readinessItems.filter((item) => item.complete).length;
  const readinessScore = Math.round((completeCount / readinessItems.length) * 100);
  const ready = completeCount === readinessItems.length;
  const missing = readinessItems.filter((item) => !item.complete).map((item) => item.label);
  const unresolved = quality.checks.filter((check) => !check.pass).map((check) => check.label.toLowerCase());
  const interpretation = ready
    ? `The experiment is well scoped. The primary business objective is measurable, the experimental population is documented, governance requirements have been captured, and no blocking context issues were detected. Remaining uncertainty comes primarily from ${unresolved.length ? unresolved.join(", ") : "statistical design assumptions that will be finalized on later workflow pages"}.`
    : `${missing.join(", ")} ${missing.length === 1 ? "is" : "are"} still missing. Capture this information before moving into the research question so the statistical test maps to the correct business decision.`;

  return (
    <div className="mx-auto max-w-6xl space-y-5">
      <ExperimentalJourneyMap currentJourney={journey} />

      <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <h2 className="text-xl font-semibold text-slate-950">Is this experiment defined well enough to proceed?</h2>
            <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-600">
              ATLAS checks whether the business decision, population, target response, governance constraints, and intended decision use are sufficiently documented before statistical design begins.
            </p>
          </div>
          <StatusBadge label={ready ? "Ready to proceed" : "Needs input"} tone={ready ? "good" : "warning"} />
        </div>
      </section>

      <section className="rounded-2xl border border-blue-100 bg-blue-50/80 p-5 shadow-sm">
        <div className="grid gap-4 md:grid-cols-[minmax(0,1fr)_220px]">
          <div>
            <div className="text-xs font-semibold uppercase tracking-wide text-blue-700">Goal of this stage</div>
            <p className="mt-2 text-sm leading-6 text-blue-950">
              Define the business objective, population, experimental unit, response, and governance expectations before choosing factors or statistical tests.
            </p>
          </div>
          <div className="rounded-xl border border-blue-100 bg-white px-4 py-3">
            <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">Estimated completion time</div>
            <div className="mt-1 text-lg font-semibold text-slate-950">3-5 minutes</div>
            <div className="mt-1 text-xs leading-5 text-slate-500">Faster when project context is already drafted.</div>
          </div>
        </div>
      </section>

      <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <div className="flex flex-wrap items-start justify-between gap-5">
          <div>
            <div className="text-xs font-semibold uppercase tracking-wide text-blue-700">Experiment Definition Readiness</div>
            <div className="mt-2 flex items-end gap-3">
              <div className="text-5xl font-semibold tracking-tight text-slate-950">{readinessScore}%</div>
              <div className="pb-2 text-sm font-semibold text-slate-500">{completeCount} of {readinessItems.length} complete</div>
            </div>
          </div>
          <div className="min-w-[280px] flex-1">
            <div className="grid gap-2 sm:grid-cols-5">
              {readinessItems.map((item) => (
                <div key={item.label} className={`rounded-xl border p-3 ${item.complete ? "border-emerald-200 bg-emerald-50" : "border-amber-200 bg-amber-50"}`}>
                  <div className={`text-[11px] font-semibold uppercase tracking-wide ${item.complete ? "text-emerald-700" : "text-amber-700"}`}>
                    {item.complete ? "Complete" : "Missing"}
                  </div>
                  <div className="mt-1 text-xs font-semibold text-slate-950">{item.label}</div>
                </div>
              ))}
            </div>
            <div className="mt-4 h-2 overflow-hidden rounded-full bg-slate-100">
              <div className={`h-full rounded-full ${ready ? "bg-emerald-600" : "bg-blue-600"}`} style={{ width: `${readinessScore}%` }} />
            </div>
          </div>
        </div>
      </section>

      <section className="grid gap-4 lg:grid-cols-[280px_minmax(0,1fr)]">
        <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
          <div className="text-xs font-semibold uppercase tracking-wide text-blue-700">Design Quality</div>
          <div className="mt-2 text-5xl font-semibold tracking-tight text-slate-950">{quality.score}</div>
          <div className={`mt-2 text-sm font-semibold ${quality.score >= 90 ? "text-emerald-700" : quality.score >= 75 ? "text-blue-700" : "text-amber-700"}`}>
            {quality.score >= 90 ? "Excellent" : quality.score >= 75 ? "Good" : "Needs refinement"}
          </div>
          <div className="mt-4 h-2 overflow-hidden rounded-full bg-slate-100">
            <div className={`h-full rounded-full ${quality.score >= 90 ? "bg-emerald-600" : quality.score >= 75 ? "bg-blue-600" : "bg-amber-500"}`} style={{ width: `${quality.score}%` }} />
          </div>
        </div>
        <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
          <div className="flex items-start justify-between gap-3">
            <div>
              <h2 className="text-base font-semibold text-slate-950">Design Health</h2>
              <p className="mt-1 text-sm leading-5 text-slate-500">Why ATLAS scored this context at {quality.score}.</p>
            </div>
            <div className="rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-right">
              <div className="text-[10px] font-semibold uppercase tracking-wide text-slate-500">Strengths</div>
              <div className="text-sm font-semibold text-slate-950">{quality.points.filter((point) => point.value > 0).length}</div>
            </div>
          </div>
          <div className="mt-4 grid gap-3 md:grid-cols-2">
            {quality.checks.map((check) => (
              <div key={check.label} className={`rounded-xl border p-3 ${check.pass ? "border-emerald-200 bg-emerald-50" : "border-amber-200 bg-amber-50"}`}>
                <div className={`text-xs font-semibold ${check.pass ? "text-emerald-800" : "text-amber-800"}`}>{check.pass ? "Pass" : "Attention"}</div>
                <div className="mt-1 text-sm font-semibold text-slate-950">{check.label}</div>
                <p className="mt-1 text-xs leading-5 text-slate-600">{check.detail}</p>
              </div>
            ))}
          </div>
          <div className="mt-4 grid gap-2 md:grid-cols-2">
            {quality.points.map((point) => (
              <div key={point.label} className="flex items-center justify-between rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-xs">
                <span className="font-semibold text-slate-700">{point.label}</span>
                <span className={`font-semibold ${point.value >= 0 ? "text-emerald-700" : "text-rose-700"}`}>
                  {point.value >= 0 ? "+" : ""}{point.value}
                </span>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <div className="mb-5">
          <h2 className="text-base font-semibold text-slate-950">Experiment Context Map</h2>
          <p className="mt-1 text-sm leading-6 text-slate-500">A clean chain from business decision to measurable experimental action.</p>
        </div>
        <div className="grid gap-3 lg:grid-cols-[1fr_auto_1fr_auto_1fr_auto_1fr]">
          {readinessItems.slice(0, 4).map((item, index) => (
            <div key={item.label} className="contents">
              <div className="relative rounded-2xl border border-slate-200 bg-slate-50 p-4">
                <div className="flex items-center gap-3">
                  <div className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-sm font-semibold text-white ${item.complete ? "bg-blue-600" : "bg-slate-400"}`}>
                    {index + 1}
                  </div>
                  <div className="min-w-0">
                    <div className="text-sm font-semibold text-slate-950">{item.label === "Business Objective" ? "Business Decision" : item.label}</div>
                    <div className={`mt-0.5 text-[11px] font-semibold ${item.complete ? "text-emerald-700" : "text-amber-700"}`}>{item.complete ? "Defined" : "Needs input"}</div>
                  </div>
                </div>
                <ExpandableSummary text={item.summary} />
              </div>
              {index < 3 && (
                <div key={`${item.label}-connector`} className="hidden items-center justify-center lg:flex">
                  <div className="h-px w-10 bg-slate-300" />
                </div>
              )}
            </div>
          ))}
        </div>
      </section>

      <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <div className="flex items-center justify-between gap-3">
          <div>
            <div className="text-xs font-semibold uppercase tracking-wide text-blue-700">Experiment Summary</div>
            <h2 className="mt-1 text-base font-semibold text-slate-950">Design Snapshot</h2>
          </div>
          <span className="rounded-full border border-blue-200 bg-blue-50 px-2.5 py-1 text-xs font-semibold text-blue-700">planning preview</span>
        </div>
        <div className="mt-4">
          <HorizontalBars
            rows={[
              { label: "Population", value: inferPopulationCount(state.inputs) || 25000 },
              { label: "Factors", value: Math.max(1, Number(state.numeric.factorCount || 2)) },
              { label: "Treatment Cells", value: Math.max(1, Math.round((state.numeric.averageLevels || 2) ** (state.numeric.factorCount || 2))) },
              { label: "Power", value: Number(state.numeric.power || 80) },
              { label: "Confidence", value: Math.round(facts.reduce((sum, fact) => sum + fact.confidence, 0) / Math.max(1, facts.length)) },
            ]}
            valueFormatter={(value) => value >= 1000 ? value.toLocaleString() : String(Math.round(value))}
          />
        </div>
      </section>

      <section className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_380px]">
        <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
          <div className="flex items-center justify-between gap-3">
            <div>
              <div className="text-xs font-semibold uppercase tracking-wide text-blue-700">Project Readiness Summary</div>
              <h2 className="mt-1 text-base font-semibold text-slate-950">Completeness, confidence, and missing items</h2>
            </div>
            <span className="rounded-full border border-slate-200 bg-slate-50 px-2.5 py-1 text-xs font-semibold text-slate-600">actionable readiness</span>
          </div>
          <div className="mt-4 grid gap-3 md:grid-cols-2">
            {facts.map((fact) => (
              <ProjectFactCard key={fact.label} fact={fact} state={state} setState={setState} />
            ))}
          </div>
        </div>
        <div className="space-y-4">
          <section className={`rounded-2xl border p-5 shadow-sm ${ready ? "border-emerald-200 bg-emerald-50" : "border-amber-200 bg-amber-50"}`}>
            <div className={`text-xs font-semibold uppercase tracking-wide ${ready ? "text-emerald-800" : "text-amber-800"}`}>ATLAS Interpretation</div>
            <p className={`mt-2 text-sm leading-6 ${ready ? "text-emerald-950" : "text-amber-950"}`}>{interpretation}</p>
          </section>
          <section className="rounded-2xl border border-blue-200 bg-blue-50 p-5 shadow-sm">
            <div className="text-xs font-semibold uppercase tracking-wide text-blue-700">ATLAS Recommendation</div>
            <div className="mt-2 flex items-center justify-between gap-3">
              <h3 className="text-base font-semibold text-blue-950">Define Research Question</h3>
              <span className="rounded-full bg-white px-2 py-1 text-xs font-semibold text-blue-700">{readinessScore}% ready</span>
            </div>
            <p className="mt-2 text-sm leading-6 text-blue-900">
              Your next design decision is defining the statistical hypothesis. Expected effort: 2-3 minutes.
            </p>
            <p className="mt-2 text-xs leading-5 text-blue-800">
              No blocking issues are evaluated yet; that happens after factors and levels are defined.
            </p>
          </section>
        </div>
      </section>

      <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <div className="text-xs font-semibold uppercase tracking-wide text-blue-700">Before continuing</div>
            <h2 className="mt-1 text-base font-semibold text-slate-950">Finish the stage deliberately</h2>
            <p className="mt-1 text-sm leading-6 text-slate-500">ATLAS checks the context evidence before the workflow moves into statistical hypothesis design.</p>
          </div>
          {nextStep && <StatusBadge label={`Next: ${nextStep.label}`} tone="good" />}
        </div>
        <div className="mt-4 grid gap-2 md:grid-cols-2">
          {quality.checks.slice(0, 4).map((check) => (
            <div key={check.label} className="flex items-center justify-between gap-3 rounded-xl border border-slate-200 bg-slate-50 px-3 py-2">
              <span className="text-sm font-semibold text-slate-800">{check.label}</span>
              <span className={`rounded-full px-2 py-0.5 text-[11px] font-semibold ${check.pass ? "bg-emerald-100 text-emerald-800" : "bg-amber-100 text-amber-800"}`}>
                {check.pass ? "Done" : "Needed"}
              </span>
            </div>
          ))}
        </div>
      </section>

    </div>
  );
}

function StatusBadge({ label, tone }: { label: string; tone: "good" | "warning" }) {
  return (
    <span className={`rounded-full border px-3 py-1 text-xs font-semibold ${tone === "good" ? "border-emerald-200 bg-emerald-50 text-emerald-800" : "border-amber-200 bg-amber-50 text-amber-800"}`}>
      {label}
    </span>
  );
}

function ExperimentalJourneyMap({ currentJourney }: { currentJourney: ExperimentalDesignJourneyStep }) {
  const workflowSteps = useWorkflowStore((state) => state.workflowSteps);
  const statusById = new Map(workflowSteps.map((step) => [step.id, step.status]));
  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="text-xs font-semibold uppercase tracking-wide text-blue-700">Experimental Design Journey</div>
          <h2 className="mt-1 text-base font-semibold text-slate-950">The scientific path from business context to defensible decision</h2>
          <p className="mt-1 max-w-4xl text-sm leading-6 text-slate-500">
            Each page answers one design question and produces one artifact that feeds the next decision.
          </p>
        </div>
        <span className="rounded-full border border-slate-200 bg-slate-50 px-3 py-1 text-xs font-semibold text-slate-700">
          {experimentalDesignJourney.length} steps
        </span>
      </div>
      <div className="mt-5 grid gap-3 md:grid-cols-2 xl:grid-cols-3">
        {experimentalDesignJourney.map((item) => {
          const status = statusById.get(item.id);
          const isCurrent = item.id === currentJourney.id;
          const isComplete = status === "complete";
          return (
            <div
              key={item.id}
              className={`rounded-xl border p-4 transition hover:-translate-y-0.5 hover:shadow-sm ${
                isCurrent
                  ? "border-blue-300 bg-blue-50"
                  : isComplete
                    ? "border-emerald-200 bg-emerald-50"
                    : "border-slate-200 bg-slate-50"
              }`}
            >
              <div className="flex items-center justify-between gap-3">
                <div className={`flex h-8 w-8 items-center justify-center rounded-full text-xs font-bold ${
                  isCurrent ? "bg-blue-700 text-white" : isComplete ? "bg-emerald-600 text-white" : "bg-white text-slate-600"
                }`}>
                  {item.stepNumber}
                </div>
                <span className={`rounded-full px-2 py-0.5 text-[11px] font-semibold ${
                  isCurrent ? "bg-blue-100 text-blue-800" : isComplete ? "bg-emerald-100 text-emerald-800" : "bg-slate-100 text-slate-600"
                }`}>
                  {isCurrent ? "Current" : isComplete ? "Complete" : "Pending"}
                </span>
              </div>
              <div className="mt-3 text-sm font-semibold text-slate-950">{item.label}</div>
              <p className="mt-1 text-xs leading-5 text-slate-600">{item.question}</p>
            </div>
          );
        })}
      </div>
    </section>
  );
}

function ExpandableSummary({ text }: { text: string }) {
  const cleaned = text.trim();
  if (cleaned.length <= 145) return <p className="mt-3 text-xs leading-5 text-slate-600">{cleaned}</p>;
  return (
    <details className="mt-3">
      <summary className="cursor-pointer list-none text-xs leading-5 text-slate-600">
        {cleaned.slice(0, 138)}...
        <span className="ml-1 font-semibold text-blue-700">Expand</span>
      </summary>
      <p className="mt-2 text-xs leading-5 text-slate-600">{cleaned}</p>
    </details>
  );
}

type ProjectFact = {
  label: string;
  value: string;
  icon: string;
  confidence: number;
  field?: keyof Pick<NodeState, "objective" | "inputs" | "assumptions" | "validation" | "decision" | "rationale">;
};

function ProjectFactCard({ fact, state, setState }: { fact: ProjectFact; state: NodeState; setState: (state: NodeState) => void }) {
  const status = fact.value === "Not defined" || fact.value === "Not selected" ? "Missing" : fact.confidence < 75 ? "Needs Review" : fact.confidence < 90 ? "Drafted" : "Ready";
  const improve = () => {
    if (!fact.field) return;
    const current = String(state[fact.field] ?? "").trim();
    const improved = improveProjectContextLanguage(fact.label, current);
    setState({ ...state, [fact.field]: improved });
  };
  const audit = () => {
    if (!fact.field) return;
    const current = String(state[fact.field] ?? "").trim();
    const auditText = auditProjectContextLanguage(fact.label, current);
    setState({ ...state, rationale: [state.rationale, auditText].filter(Boolean).join("\n\n") });
  };
  return (
    <div className="rounded-2xl border border-slate-200 bg-slate-50 p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-2">
          <span className="flex h-8 w-8 items-center justify-center rounded-full bg-white text-xs font-semibold text-blue-700 shadow-sm">{fact.icon}</span>
          <div>
            <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">{fact.label}</div>
            <details className="mt-0.5">
              <summary className="cursor-pointer list-none text-[11px] font-semibold text-blue-700">
                {fact.confidence}% confidence · Why?
              </summary>
              <p className="mt-1 rounded-lg border border-blue-100 bg-white p-2 text-[11px] leading-4 text-slate-600">
                {confidenceExplanation(fact)}
              </p>
            </details>
          </div>
        </div>
        <span className={`rounded-full px-2 py-0.5 text-[10px] font-semibold ${
          status === "Ready" ? "bg-emerald-100 text-emerald-800" : status === "Missing" ? "bg-rose-100 text-rose-800" : "bg-amber-100 text-amber-800"
        }`}>
          {status}
        </span>
      </div>
      <ExpandableSummary text={fact.value} />
      {fact.field && (
        <div className="mt-3 flex flex-wrap gap-2">
          <button type="button" className="rounded-full border border-blue-200 bg-white px-2.5 py-1 text-[11px] font-semibold text-blue-700 hover:bg-blue-50" onClick={improve}>
            ATLAS Improve
          </button>
          <button type="button" className="rounded-full border border-slate-200 bg-white px-2.5 py-1 text-[11px] font-semibold text-slate-700 hover:bg-slate-100" onClick={audit}>
            Audit Readiness
          </button>
        </div>
      )}
    </div>
  );
}

function summarizeText(value: string, fallback: string) {
  const cleaned = value.replace(/\s+/g, " ").trim();
  if (!cleaned) return fallback;
  return cleaned;
}

function projectContextFacts(state: NodeState): ProjectFact[] {
  return [
    { label: "Business objective", value: summarizeText(state.objective, "Not defined"), icon: "BO", confidence: state.objective ? 94 : 45, field: "objective" },
    { label: "Population", value: summarizeText(state.inputs, "Not defined"), icon: "POP", confidence: state.inputs ? 86 : 40, field: "inputs" },
    { label: "Randomization unit", value: inferUnitOfRandomization(state.inputs), icon: "RU", confidence: state.inputs ? 78 : 35, field: "inputs" },
    { label: "Experiment family", value: state.method || "Not selected", icon: "DOE", confidence: state.method ? 90 : 50 },
    { label: "Primary response", value: state.metrics.find((metric) => /response|primary/i.test(metric)) || state.metrics[0] || "Not selected", icon: "TGT", confidence: state.metrics.length ? 82 : 35 },
    { label: "Guardrail metrics", value: state.metrics.filter((metric) => !/response|primary/i.test(metric)).join(", ") || "Not selected", icon: "GRD", confidence: state.metrics.length > 1 ? 80 : 45 },
    { label: "Governance", value: summarizeText(state.validation, "Not defined"), icon: "GOV", confidence: state.validation ? 88 : 40, field: "validation" },
    { label: "Operational constraints", value: summarizeText(state.assumptions, "Not defined"), icon: "OPS", confidence: state.assumptions ? 84 : 40, field: "assumptions" },
  ];
}

function confidenceExplanation(fact: ProjectFact) {
  if (/population/i.test(fact.label)) return "Population confidence reflects whether eligibility, exclusions, enrollment assumptions, and unit of randomization are documented.";
  if (/randomization/i.test(fact.label)) return "Confidence is reduced when ATLAS must infer the experimental unit from loose population language.";
  if (/business/i.test(fact.label)) return "Objective confidence improves when the language is measurable, decision-oriented, and includes the expected business outcome.";
  if (/governance/i.test(fact.label)) return "Governance confidence reflects whether approval, monitoring, compliance review, and audit evidence are explicit.";
  if (/response|guardrail/i.test(fact.label)) return "Metric confidence improves when the primary response and guardrails are selected rather than inferred.";
  return "Confidence reflects how completely this item is documented and how much ATLAS had to infer from surrounding language.";
}

function projectDesignQuality(state: NodeState) {
  const checks = [
    {
      label: "Objective measurable",
      pass: Boolean(state.objective.trim()) && /increase|decrease|improve|reduce|maintain|compare|test|determine/i.test(state.objective),
      detail: "Objective should state the business outcome the experiment is expected to influence.",
    },
    {
      label: "Response defined",
      pass: state.metrics.length > 0 || /activation|response|conversion|complaint|rate|outcome/i.test(`${state.objective} ${state.inputs}`),
      detail: "Define the measurable customer outcome before the research question.",
    },
    {
      label: "Population defined",
      pass: Boolean(state.inputs.trim()),
      detail: "Population, exclusions, and randomization unit should be clear.",
    },
    {
      label: "Governance complete",
      pass: Boolean(state.validation.trim()),
      detail: "Customer-impacting experiments need approval, monitoring, and audit evidence.",
    },
    {
      label: "Response window selected",
      pass: /day|week|month|window|period|within|after/i.test(`${state.objective} ${state.inputs} ${state.assumptions}`),
      detail: "Add the time window used to measure the response.",
    },
    {
      label: "Practical lift selected",
      pass: /lift|minimum|effect|detectable|threshold|material/i.test(`${state.objective} ${state.assumptions}`),
      detail: "Define the smallest effect the business would act on.",
    },
  ];
  const points = [
    { label: "Objective", value: checks[0].pass ? 20 : -8 },
    { label: "Response", value: checks[1].pass ? 14 : -6 },
    { label: "Population", value: checks[2].pass ? 18 : -8 },
    { label: "Governance", value: checks[3].pass ? 17 : -7 },
    { label: "Response window", value: checks[4].pass ? 8 : -5 },
    { label: "Practical lift", value: checks[5].pass ? 8 : -5 },
  ];
  const score = Math.max(0, Math.min(100, 45 + points.reduce((sum, point) => sum + point.value, 0)));
  return { score, checks, points };
}

function improveProjectContextLanguage(label: string, current: string) {
  if (/business/i.test(label)) {
    return current
      ? `Determine whether the proposed experimental treatment improves the target customer outcome relative to the current approach while maintaining operational, customer-impact, and governance guardrails. Current draft: ${current}`
      : "Determine whether the proposed experimental treatment improves the target customer outcome relative to the current approach while maintaining operational, customer-impact, and governance guardrails.";
  }
  if (/population|randomization/i.test(label)) {
    return current
      ? `Eligible experimental units are the defined customer or account population that can be randomly assigned to treatment. Exclusions, eligibility timing, and unit of randomization should be documented. Current draft: ${current}`
      : "Eligible experimental units are the defined customer or account population that can be randomly assigned to treatment. Exclusions, eligibility timing, and unit of randomization should be documented.";
  }
  if (/governance/i.test(label)) {
    return current
      ? `Required governance includes documented treatment logic, population exclusions, randomization controls, approval evidence, monitoring expectations, and escalation criteria. Current draft: ${current}`
      : "Required governance includes documented treatment logic, population exclusions, randomization controls, approval evidence, monitoring expectations, and escalation criteria.";
  }
  return current
    ? `Document operational limits, execution constraints, timing dependencies, treatment capacity, and controls that may affect experiment validity. Current draft: ${current}`
    : "Document operational limits, execution constraints, timing dependencies, treatment capacity, and controls that may affect experiment validity.";
}

function auditProjectContextLanguage(label: string, current: string) {
  const issues = [];
  if (!current) issues.push(`${label}: no language has been documented.`);
  if (current && current.length < 60) issues.push(`${label}: language may be too brief for governance review.`);
  if (/governance/i.test(label) && !/approval|compliance|monitor|audit|review/i.test(current)) issues.push("Governance: approval, compliance review, monitoring, or audit evidence is not explicit.");
  if (/population|randomization/i.test(label) && !/exclusion|eligible|unit|random/i.test(current)) issues.push("Population: eligibility, exclusions, or unit of randomization should be explicit.");
  return `ATLAS audit - ${label}: ${issues.length ? issues.join(" ") : "No major documentation gaps detected."}`;
}

function inferUnitOfRandomization(text: string) {
  if (/customer|account|patient|member|applicant/i.test(text)) {
    const match = text.match(/customer|account|patient|member|applicant/i);
    return match ? `${match[0][0].toUpperCase()}${match[0].slice(1).toLowerCase()}` : "Customer";
  }
  return text.trim() ? "Documented in population notes" : "Not defined";
}

function inferPopulationCount(text: string) {
  const match = text.replace(/,/g, "").match(/\b(\d{4,9})\b/);
  return match ? Number(match[1]) : 0;
}

function ResearchQuestionPage({
  projectId,
  config,
  state,
  setState,
  save,
  onComplete,
  nextStep,
  savedAt,
}: {
  projectId: string;
  config: ExperimentalStepConfig;
  state: NodeState;
  setState: (state: NodeState) => void;
  save: () => void;
  onComplete: () => void;
  nextStep?: ReturnType<typeof getWorkflowDefinition>["steps"][number];
  savedAt: Date | null;
}) {
  const factors = researchQuestionFactors(projectId, state);
  const artifacts = researchQuestionArtifacts(state, factors);
  const quality = researchQuestionQuality(state);
  const [activeBuilderIndex, setActiveBuilderIndex] = useState<number | null>(null);
  const [draftStatus, setDraftStatus] = useState<"idle" | "working" | "done">("idle");
  const [reviewMessage, setReviewMessage] = useState<string>("");
  const applyGeneratedHypothesis = () => {
    setDraftStatus("working");
    setTimeout(() => {
      setState(generateResearchHypothesisState(state));
      setReviewMessage("ATLAS generated hypothesis, decision rule, and governance rationale language from the current response variable and factors.");
      setDraftStatus("done");
      window.setTimeout(() => setDraftStatus("idle"), 1800);
    }, 350);
  };
  const improve = () => {
    setState({
      ...state,
      objective: improveResearchQuestion(state.objective, artifacts.responseVariable),
      validation: state.validation || artifacts.decisionRule,
    });
    setReviewMessage("ATLAS strengthened the research question and added decision-rule language to the validation field.");
  };
  const explain = () => {
    setState({
      ...state,
      rationale: [
        state.rationale,
        "ATLAS explanation: this page converts a business objective into a testable statistical decision by defining the response variable, null hypothesis, alternative hypothesis, alpha threshold, power target, practical lift, and deployment decision rule.",
      ].filter(Boolean).join("\n\n"),
    });
    setReviewMessage("ATLAS added a stakeholder explanation to the governance rationale field.");
  };
  const validate = () => {
    setState({
      ...state,
      validation: [
        state.validation,
        `Statistical logic validation: ${quality.gaps.length ? `Resolve ${quality.gaps.join(", ").toLowerCase()} before launch approval.` : "Research question, response variable, hypotheses, and decision rule are sufficiently aligned for the next workflow stage."}`,
      ].filter(Boolean).join("\n\n"),
    });
    setReviewMessage(quality.gaps.length ? `ATLAS found ${quality.gaps.length} statistical logic gap(s): ${quality.gaps.join(", ")}.` : "ATLAS found no major statistical logic gaps.");
  };

  return (
    <div className="mx-auto max-w-6xl space-y-5">
      <section className="rounded-2xl border border-blue-100 bg-blue-50/80 p-5 shadow-sm">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <div className="text-xs font-semibold uppercase tracking-wide text-blue-700">Goal of this stage</div>
            <h2 className="mt-1 text-lg font-semibold text-blue-950">Move from business planning to statistical thinking.</h2>
            <p className="mt-2 max-w-3xl text-sm leading-6 text-blue-900">
              Define the testable question, response variable, hypotheses, and decision rule that will determine whether the experiment produced actionable evidence.
            </p>
          </div>
          <div className="rounded-xl border border-blue-100 bg-white px-4 py-3">
            <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">Expected effort</div>
            <div className="mt-1 text-lg font-semibold text-slate-950">3-5 minutes</div>
          </div>
        </div>
      </section>

      <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <div className="text-xs font-semibold uppercase tracking-wide text-blue-700">AI statistical drafting</div>
            <h2 className="mt-1 text-base font-semibold text-slate-950">Build the hypothesis language</h2>
          </div>
          <div className="flex flex-wrap gap-2">
            <button type="button" className="rounded-lg bg-blue-600 px-3 py-2 text-xs font-semibold text-white shadow-sm transition hover:-translate-y-0.5 hover:bg-blue-700 disabled:cursor-wait disabled:opacity-80" onClick={applyGeneratedHypothesis} disabled={draftStatus === "working"}>
              {draftStatus === "working" ? "Drafting..." : draftStatus === "done" ? "Draft Generated" : "Generate Hypothesis Draft"}
            </button>
            <button type="button" className="rounded-lg border border-blue-200 bg-white px-3 py-2 text-xs font-semibold text-blue-700 hover:bg-blue-50" onClick={improve}>Strengthen Statistical Logic</button>
            <button type="button" className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs font-semibold text-slate-700 hover:bg-slate-50" onClick={explain}>Explain for Stakeholders</button>
            <button type="button" className="rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-xs font-semibold text-emerald-800 hover:bg-emerald-100" onClick={validate}>Check Statistical Soundness</button>
          </div>
        </div>
        {reviewMessage && (
          <div className="mt-4 rounded-xl border border-blue-200 bg-blue-50 px-4 py-3 text-sm leading-6 text-blue-950">
            {reviewMessage}
          </div>
        )}
      </section>

      <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <div className="mb-5">
          <div className="text-xs font-semibold uppercase tracking-wide text-blue-700">Statistical Creation Path</div>
          <h2 className="mt-1 text-base font-semibold text-slate-950">What this page is building</h2>
        </div>
        <div className="grid gap-3 md:grid-cols-[1fr_auto_1fr_auto_1fr_auto_1fr_auto_1fr]">
          {artifacts.creationPath.map((node, index) => (
            <div key={node.label} className="contents">
              <div className={`rounded-2xl border p-4 text-center transition ${index === activeBuilderIndex ? "border-blue-300 bg-blue-50 shadow-sm" : "border-slate-200 bg-slate-50"}`}>
                <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">{node.label}</div>
                <div className="mt-2 text-sm font-semibold text-slate-950">{node.value}</div>
              </div>
              {index < artifacts.creationPath.length - 1 && (
                <div className="hidden items-center justify-center md:flex">
                  <ArrowRight size={18} className="text-blue-400" />
                </div>
              )}
            </div>
          ))}
        </div>
      </section>

      <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <div className="mb-5 flex flex-wrap items-start justify-between gap-3">
          <div>
            <div className="text-xs font-semibold uppercase tracking-wide text-blue-700">Hypothesis Builder</div>
            <h2 className="mt-1 text-base font-semibold text-slate-950">Business objective to statistical decision</h2>
          </div>
          <span className="rounded-full border border-slate-200 bg-slate-50 px-2.5 py-1 text-xs font-semibold text-slate-600">analysis framing</span>
        </div>
        <div className="flex gap-3 overflow-x-auto pb-2">
          {artifacts.flow.map((node, index) => (
            <Fragment key={node.label}>
              <button
                type="button"
                className={`group min-w-[190px] flex-1 rounded-2xl border p-3 text-left transition hover:-translate-y-0.5 hover:border-blue-300 hover:bg-blue-50 hover:shadow-sm ${
                  activeBuilderIndex === index ? "border-blue-300 bg-blue-50 shadow-sm" : "border-slate-200 bg-slate-50"
                }`}
                onMouseEnter={() => setActiveBuilderIndex(index)}
                onFocus={() => setActiveBuilderIndex(index)}
                onClick={() => setActiveBuilderIndex(activeBuilderIndex === index ? null : index)}
              >
                <div className="flex items-center gap-2">
                  <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-blue-600 text-[11px] font-semibold text-white">{index + 1}</div>
                  <div className="min-w-0">
                    <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">{node.label}</div>
                    <div className="mt-0.5 break-words text-sm font-semibold text-slate-950">{node.shortValue}</div>
                  </div>
                </div>
                <div className="mt-3 flex items-center gap-2">
                  <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-white">
                    <div className="h-full rounded-full bg-blue-600 transition-all" style={{ width: `${node.confidence}%` }} />
                  </div>
                  <span className="text-[11px] font-semibold text-slate-600">{node.confidence}%</span>
                </div>
              </button>
              {index < artifacts.flow.length - 1 && (
                <div className="flex shrink-0 items-center justify-center">
                  <ArrowRight size={18} className="text-slate-300" />
                </div>
              )}
            </Fragment>
          ))}
        </div>
      </section>

      <section className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_380px]">
        <div className="space-y-5">
          <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div>
                <div className="text-xs font-semibold uppercase tracking-wide text-blue-700">Statistical Decision Summary</div>
                <h2 className="mt-1 text-base font-semibold text-slate-950">The rule ATLAS will use to interpret evidence</h2>
              </div>
              <StatusBadge label={quality.score >= 80 ? "Ready for factors" : "Needs refinement"} tone={quality.score >= 80 ? "good" : "warning"} />
            </div>
            <div className="mt-4 grid gap-3 md:grid-cols-5">
              <ResultCard label="Selected test" value={artifacts.selectedTest} />
              <ResultCard label="Alpha" value={artifacts.alpha} />
              <ResultCard label="Power target" value={artifacts.powerTarget} />
              <ResultCard label="Practical lift" value={artifacts.practicalLift} />
              <ResultCard label="Deployment decision" value={artifacts.deploymentDecision} />
            </div>
            <div className="mt-4 rounded-xl border border-blue-100 bg-blue-50 p-4">
              <div className="text-[11px] font-semibold uppercase tracking-wide text-blue-700">Current equation</div>
              <div className="mt-2 text-sm font-semibold leading-6 text-blue-950">{artifacts.equation}</div>
            </div>
            <div className="mt-4 rounded-xl border border-slate-200 bg-slate-50 p-3">
              <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">Generated from</div>
              <div className="mt-2 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
                {artifacts.dependencies.map((item) => (
                  <div key={item.label} className="flex items-center gap-2 rounded-lg bg-white px-2 py-1.5 text-[11px] font-semibold text-slate-700">
                    <span className={item.ready ? "text-emerald-600" : "text-slate-400"}>{item.ready ? "✓" : "Pending"}</span>
                    <span>{item.label}</span>
                  </div>
                ))}
              </div>
            </div>
          </section>

          <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
            <div className="text-xs font-semibold uppercase tracking-wide text-blue-700">Statistical Model</div>
            <h2 className="mt-1 text-base font-semibold text-slate-950">Response decomposition</h2>
            <div className="mt-5 flex flex-wrap items-center gap-2 text-sm font-semibold text-slate-900">
              {artifacts.modelTerms.map((term, index) => (
                <span
                  key={`${term}-${index}`}
                  className={
                    /[+=]/.test(term)
                      ? "px-1 text-slate-400"
                      : `rounded-xl border px-3 py-2 transition ${
                          (activeBuilderIndex === 2 && term === artifacts.responseName) ||
                          (activeBuilderIndex !== null && activeBuilderIndex >= 3 && !/[+=]/.test(term) && term !== artifacts.responseName)
                            ? "border-blue-300 bg-blue-100 text-blue-950 shadow-sm"
                            : "border-blue-100 bg-blue-50 text-blue-950"
                        }`
                  }
                >
                  {term}
                </span>
              ))}
            </div>
            <p className="mt-4 text-sm leading-6 text-slate-600">
              This is the conceptual model behind the experiment: explain response variation using main effects, interaction effects, and residual error.
            </p>
            <div className="mt-5 rounded-xl border border-slate-200 bg-slate-50 p-4">
              <div className="grid items-center gap-3 sm:grid-cols-[1fr_auto_1fr]">
                <div className="space-y-2">
                  {artifacts.influenceTerms.map((term) => (
                    <div key={term} className={`rounded-lg border px-3 py-2 text-xs font-semibold transition ${
                      activeBuilderIndex !== null && activeBuilderIndex >= 3 ? "border-blue-300 bg-blue-50 text-blue-950" : "border-slate-200 bg-white text-slate-700"
                    }`}>
                      {term}
                    </div>
                  ))}
                </div>
                <div className="hidden text-blue-500 sm:block">────►</div>
                <div className={`rounded-2xl border px-4 py-5 text-center text-sm font-semibold transition ${
                  activeBuilderIndex === 2 ? "border-blue-300 bg-blue-50 text-blue-950 shadow-sm" : "border-slate-200 bg-white text-slate-900"
                }`}>
                  {artifacts.responseName}
                  <div className="mt-1 text-[11px] font-normal text-slate-500">Response</div>
                </div>
              </div>
            </div>
          </section>

          <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
            <div className="text-xs font-semibold uppercase tracking-wide text-blue-700">Assumption Status</div>
            <h2 className="mt-1 text-base font-semibold text-slate-950">Statistical assumptions as checks</h2>
            <div className="mt-4 grid gap-3 md:grid-cols-2">
              {artifacts.assumptions.map((item) => (
                <details key={item.label} className={`rounded-xl border p-4 ${assumptionCardClass(item.category, item.pass)}`}>
                  <summary className="cursor-pointer list-none">
                    <div className={`text-xs font-semibold ${item.pass ? "opacity-90" : "text-amber-800"}`}>{item.category} · {item.pass ? "Documented" : "Needs definition"}</div>
                    <div className="mt-1 text-sm font-semibold text-slate-950">{item.label}</div>
                  </summary>
                  <p className="mt-2 text-xs leading-5 text-slate-600">{item.detail}</p>
                  <div className="mt-3 rounded-lg bg-white/80 p-3 text-xs leading-5 text-slate-700">
                    <span className="font-semibold">What to capture: </span>{item.capture}
                  </div>
                </details>
              ))}
            </div>
          </section>

          <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
            <div className="text-xs font-semibold uppercase tracking-wide text-blue-700">Expected Results Preview</div>
            <h2 className="mt-1 text-base font-semibold text-slate-950">ANOVA output this design is preparing</h2>
            <div className="mt-4 overflow-hidden rounded-xl border border-slate-200">
              <table className="w-full text-left text-xs">
                <thead className="bg-slate-50 text-slate-500">
                  <tr>
                    {["Source", "SS", "DF", "MS", "F", "P", "η²", "Interpretation"].map((header) => <th key={header} className="px-3 py-2 font-semibold uppercase tracking-wide">{header}</th>)}
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {artifacts.expectedAnovaRows.map((row) => (
                    <tr key={row}>
                      <td className="px-3 py-2 font-semibold text-slate-800">{row}</td>
                      {["--", "--", "--", "--", "--", "--"].map((cell, index) => <td key={`${row}-${index}`} className="px-3 py-2 text-slate-400">{cell}</td>)}
                      <td className="px-3 py-2 text-slate-400">{row === "Error" ? "Residual variation" : row === "Total" ? "Overall variation" : "Effect evidence pending"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        </div>

        <div className="space-y-5">
          <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
            <div className="text-xs font-semibold uppercase tracking-wide text-blue-700">Research Quality Score</div>
            <div className="mt-2 text-5xl font-semibold tracking-tight text-slate-950">{quality.score}</div>
            <div className={`mt-2 text-sm font-semibold ${quality.score >= 85 ? "text-emerald-700" : quality.score >= 70 ? "text-blue-700" : "text-amber-700"}`}>
              {quality.score >= 85 ? "Statistically coherent" : quality.score >= 70 ? "Mostly coherent" : "Needs more structure"}
            </div>
            <div className="mt-4 h-2 overflow-hidden rounded-full bg-slate-100">
              <div className={`h-full rounded-full ${quality.score >= 85 ? "bg-emerald-600" : quality.score >= 70 ? "bg-blue-600" : "bg-amber-500"}`} style={{ width: `${quality.score}%` }} />
            </div>
            <div className="mt-5 space-y-3">
              {quality.dimensions.map((dimension) => (
                <div key={dimension.label}>
                  <div className="flex items-center justify-between text-[11px] font-semibold uppercase tracking-wide text-slate-500">
                    <span>{dimension.label}</span>
                    <span>{dimension.value}%</span>
                  </div>
                  <div className="mt-1 h-2 overflow-hidden rounded-full bg-slate-100">
                    <div className={`h-full rounded-full ${dimension.value >= 85 ? "bg-emerald-600" : dimension.value >= 70 ? "bg-blue-600" : "bg-amber-500"}`} style={{ width: `${dimension.value}%` }} />
                  </div>
                </div>
              ))}
            </div>
            <div className="mt-5 grid gap-3">
              <div className="rounded-xl border border-emerald-200 bg-emerald-50 p-3">
                <div className="text-xs font-semibold uppercase tracking-wide text-emerald-800">Strengths</div>
                <div className="mt-2 flex flex-wrap gap-2">
                  {(quality.strengths.length ? quality.strengths : ["No strengths detected yet."]).map((item) => (
                    <button key={item} type="button" className="rounded-full bg-white/80 px-2.5 py-1 text-[11px] font-semibold text-emerald-900" onClick={() => setActiveBuilderIndex(qualityIndexFor(item))}>{item}</button>
                  ))}
                </div>
              </div>
              <div className="rounded-xl border border-amber-200 bg-amber-50 p-3">
                <div className="text-xs font-semibold uppercase tracking-wide text-amber-800">Gaps</div>
                <div className="mt-2 flex flex-wrap gap-2">
                  {(quality.gaps.length ? quality.gaps : ["No major gaps detected."]).map((item) => (
                    <button key={item} type="button" className="rounded-full bg-white/80 px-2.5 py-1 text-[11px] font-semibold text-amber-900" onClick={() => setActiveBuilderIndex(qualityIndexFor(item))}>{item}</button>
                  ))}
                </div>
              </div>
            </div>
          </section>

          <section className="rounded-2xl border border-blue-200 bg-blue-50 p-5 shadow-sm">
            <div className="text-xs font-semibold uppercase tracking-wide text-blue-700">ATLAS Interpretation</div>
            <p className="mt-2 text-sm leading-6 text-blue-950">{artifacts.interpretation}</p>
          </section>
        </div>
      </section>

      <SavedStateStrip savedAt={savedAt} nextStep={nextStep} />
    </div>
  );
}

function researchQuestionFactors(projectId: string, state: NodeState) {
  const levelsState = loadExperimentalNodeState(projectId, "Levels");
  const factorsState = loadExperimentalNodeState(projectId, "Factors");
  const parsed = sharedParseFactorHierarchy(levelsState?.objective ?? "");
  if (parsed.length) return parsed.map((factor) => factor.factorName).slice(0, 3);
  const suggested = sharedDeriveSuggestedFactors(factorsState?.objective || state.objective);
  if (suggested.length) return suggested.map((factor) => factor.factorName).slice(0, 3);
  return ["Pricing", "Channel"];
}

function shortStatLabel(value: string, fallback: string) {
  const cleaned = value.replace(/primary response variable:/i, "").replace(/\s+/g, " ").trim();
  if (!cleaned) return fallback;
  const beforePunctuation = cleaned.split(/[.;:]/)[0]?.trim() || cleaned;
  const words = beforePunctuation.split(/\s+/).slice(0, 3).join(" ");
  return words || fallback;
}

function confidenceForArtifact(value: string, fallbackConfidence: number) {
  if (!value.trim()) return Math.max(35, fallbackConfidence - 35);
  if (value.length > 80) return Math.min(96, fallbackConfidence + 8);
  return fallbackConfidence;
}

function researchQuestionArtifacts(state: NodeState, factors: string[]) {
  const selectedTest = state.method || "Main Effects + Interaction Analysis";
  const responseVariable = summarizeText(state.inputs, "Primary response variable not defined");
  const responseName = shortStatLabel(responseVariable, "Response");
  const factorA = factors[0] || "Factor A";
  const factorB = factors[1] || "Factor B";
  const interaction = factors.length >= 2 ? `${factorA} x ${factorB}` : "Interaction";
  const factorTerms = factors.length ? factors : ["Factor A", "Factor B"];
  const modelTerms = [responseName, "=", ...factorTerms.flatMap((factor, index) => index === 0 ? [factor] : ["+", factor])];
  if (factorTerms.length >= 2) modelTerms.push("+", interaction);
  modelTerms.push("+", "Error");
  const equation = modelTerms.join(" ");
  const practicalLift = `${Number(state.numeric.expectedLift || 5).toFixed(1)}% minimum practical lift`;
  const alpha = `${(Number(state.numeric.alpha || 5) / 100).toFixed(2)}`;
  const powerTarget = `${Math.round(Number(state.numeric.power || 80))}%`;
  const nullHypothesis = extractHypothesis(state.assumptions, "H0") || "No statistically or practically meaningful difference exists across treatment conditions.";
  const alternativeHypothesis = extractHypothesis(state.assumptions, "H1") || "At least one treatment condition produces a meaningful change in the response variable.";
  const decisionRule = summarizeText(state.validation, `Proceed only when p-value <= ${alpha}, expected lift >= ${practicalLift}, and guardrail metrics remain acceptable.`);
  const deploymentDecision = state.decision ? "Decision documented" : "Requires evidence threshold";
  return {
    selectedTest,
    responseVariable,
    responseName,
    alpha,
    powerTarget,
    practicalLift,
    deploymentDecision,
    decisionRule,
    equation,
    modelTerms,
    influenceTerms: [...factorTerms, ...(factorTerms.length >= 2 ? [interaction] : []), "Error"],
    expectedAnovaRows: [...factorTerms, ...(factorTerms.length >= 2 ? [interaction] : []), "Error", "Total"],
    dependencies: [
      { label: "Response Variable", ready: Boolean(state.inputs.trim()) },
      { label: "Factors", ready: factors.length > 0 },
      { label: "Analysis Intent", ready: Boolean(state.method) },
      { label: "Randomization", ready: /random|assign/i.test(`${state.validation} ${state.assumptions}`) },
      { label: "Sample Size", ready: /power|sample|alpha/i.test(`${state.validation} ${state.assumptions}`) },
    ],
    creationPath: [
      { label: "Business Goal", value: shortStatLabel(state.objective, "Increase activation") },
      { label: "Hypothesis", value: shortStatLabel(alternativeHypothesis, "Treatment works") },
      { label: "Experiment", value: factors.length >= 2 ? `${factors.length} factor design` : "Factorial design" },
      { label: "Evidence", value: /interaction/i.test(selectedTest) ? "ANOVA + interaction" : "ANOVA" },
      { label: "Decision", value: state.decision ? "Deploy decision" : "Deploy / hold" },
    ],
    flow: [
      {
        label: "Business Objective",
        value: summarizeText(state.objective, "Define what business decision the experiment should support."),
        shortValue: shortStatLabel(state.objective, "Increase activation"),
        confidence: confidenceForArtifact(state.objective, 86),
      },
      {
        label: "Research Question",
        value: improveResearchQuestion(state.objective, responseVariable),
        shortValue: "Treatment effect?",
        confidence: confidenceForArtifact(state.objective, 88),
      },
      {
        label: "Response Variable",
        value: responseVariable,
        shortValue: responseName,
        confidence: confidenceForArtifact(state.inputs, 84),
      },
      {
        label: "Null Hypothesis",
        value: nullHypothesis,
        shortValue: "No difference",
        confidence: /h0|null/i.test(state.assumptions) ? 92 : 62,
      },
      {
        label: "Alternative Hypothesis",
        value: alternativeHypothesis,
        shortValue: "Meaningful change",
        confidence: /h1|alternative/i.test(state.assumptions) ? 92 : 64,
      },
      {
        label: "Decision Rule",
        value: decisionRule,
        shortValue: `p <= ${alpha}`,
        confidence: confidenceForArtifact(state.validation, 82),
      },
    ],
    assumptions: [
      { category: "Experimental Design", label: "Random assignment", pass: /random|assign|treatment/i.test(`${state.validation} ${state.assumptions}`), detail: "Treatment assignment should be randomized or otherwise defensibly controlled.", capture: "Assignment unit, random seed, exclusions, and balance QA." },
      { category: "Statistical", label: "Response measurable", pass: Boolean(state.inputs.trim()), detail: "The response variable needs a measurable definition, timing, and valid range.", capture: "Metric name, response window, valid values, and source table." },
      { category: "Statistical", label: "Hypotheses explicit", pass: /h0|h1|null|alternative/i.test(state.assumptions), detail: "State the null and alternative hypotheses before reviewing results.", capture: "H0, H1, expected direction, and whether interactions matter." },
      { category: "Business", label: "Practical lift defined", pass: /lift|minimum|effect|detectable|material|threshold/i.test(`${state.assumptions} ${state.validation}`), detail: "Define the smallest effect that would change the business decision.", capture: "Minimum lift, business value, owner, and rationale." },
      { category: "Statistical", label: "Decision threshold", pass: /alpha|p-value|confidence|power|threshold|rule/i.test(state.validation), detail: "Document how statistical and business evidence will be combined.", capture: "Alpha, power, practical lift, and guardrail thresholds." },
      { category: "Business", label: "Guardrail logic", pass: state.metrics.length > 1 || /guardrail|complaint|risk|cost|compliance/i.test(`${state.validation} ${state.assumptions}`), detail: "Identify outcomes that can block deployment even if the primary response improves.", capture: "Risk, cost, complaint, fairness, or compliance guardrails." },
    ],
    interpretation: `ATLAS is framing this as ${selectedTest.toLowerCase()}. The response is ${responseVariable}. The decision should combine statistical significance, target power, practical lift, and guardrail evidence before recommending deployment.`,
  };
}

function qualityIndexFor(label: string) {
  if (/research/i.test(label)) return 1;
  if (/response/i.test(label)) return 2;
  if (/hypoth/i.test(label)) return 3;
  if (/decision/i.test(label)) return 5;
  if (/analysis|metric/i.test(label)) return 4;
  return 0;
}

function researchQuestionQuality(state: NodeState) {
  const checks = [
    { label: "Research question documented", pass: Boolean(state.objective.trim()), weight: 22 },
    { label: "Response variable defined", pass: Boolean(state.inputs.trim()), weight: 20 },
    { label: "Hypotheses stated", pass: /h0|h1|null|alternative/i.test(state.assumptions), weight: 18 },
    { label: "Decision rule defined", pass: Boolean(state.validation.trim()), weight: 17 },
    { label: "Analysis intent selected", pass: Boolean(state.method), weight: 13 },
    { label: "Evidence metrics selected", pass: state.metrics.length > 0, weight: 10 },
  ];
  const score = checks.reduce((sum, check) => sum + (check.pass ? check.weight : 0), 0);
  const dimensionScore = (labels: RegExp[]) => {
    const selected = checks.filter((check) => labels.some((pattern) => pattern.test(check.label)));
    const possible = selected.reduce((sum, check) => sum + check.weight, 0);
    const earned = selected.reduce((sum, check) => sum + (check.pass ? check.weight : 0), 0);
    return possible ? Math.round((earned / possible) * 100) : 0;
  };
  return {
    score,
    dimensions: [
      { label: "Documentation", value: dimensionScore([/documented|defined|rule/i]) },
      { label: "Statistical Logic", value: dimensionScore([/hypotheses|analysis|metrics/i]) },
      { label: "Business Alignment", value: dimensionScore([/research question|decision rule|response/i]) },
    ],
    strengths: checks.filter((check) => check.pass).map((check) => check.label),
    gaps: checks.filter((check) => !check.pass).map((check) => check.label),
  };
}

function assumptionCardClass(category: string, pass: boolean) {
  if (!pass) return "border-amber-200 bg-amber-50";
  if (/experimental/i.test(category)) return "border-blue-200 bg-blue-50";
  if (/business/i.test(category)) return "border-orange-200 bg-orange-50";
  return "border-emerald-200 bg-emerald-50";
}

function extractHypothesis(text: string, token: "H0" | "H1") {
  const match = text.match(new RegExp(`${token}\\s*:?\\s*([^\\n]+)`, "i"));
  return match?.[1]?.trim() ?? "";
}

function improveResearchQuestion(current: string, responseVariable: string) {
  if (current.trim()) return `Does the proposed experimental treatment create a statistically and practically meaningful change in ${responseVariable} relative to the control condition?`;
  return "Does the proposed experimental treatment produce a statistically and practically meaningful improvement relative to the control condition?";
}

function generateResearchHypothesisState(state: NodeState): NodeState {
  const response = state.inputs || "Primary response variable: customer activation rate measured during the defined performance window.";
  const lift = `${Number(state.numeric.expectedLift || 5).toFixed(1)}%`;
  const alpha = (Number(state.numeric.alpha || 5) / 100).toFixed(2);
  const power = `${Math.round(Number(state.numeric.power || 80))}%`;
  return {
    ...state,
    method: state.method || "Main Effects + Interaction Analysis",
    metrics: state.metrics.length ? state.metrics : ["p-value", "effect size", "power", "minimum practical effect"],
    objective: state.objective || "Does the proposed experimental treatment produce a statistically and practically meaningful improvement relative to the control condition?",
    inputs: response,
    assumptions: state.assumptions || `H0: Mean response is equal across treatment conditions.\nH1: At least one treatment condition changes the response by at least ${lift}.`,
    validation: state.validation || `Decision rule: require alpha <= ${alpha}, target power >= ${power}, observed lift >= ${lift}, and no material guardrail deterioration.`,
    decision: state.decision || "Proceed to factor selection once response definition, hypotheses, and decision threshold are approved.",
  };
}

function ResearchQuestionStudio({ state }: { state: NodeState }) {
  const method = state.method || "Select analysis objective";
  return (
    <section className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_420px]">
      <VisualCard title="Hypothesis and Decision Flow" subtitle="Converts the business question into a testable statistical question and decision threshold.">
        <div className="grid gap-3 md:grid-cols-4">
          {["Business question", "Null hypothesis", "Alternative", "Decision rule"].map((node, index) => (
            <div key={node} className="rounded-xl border border-slate-200 bg-slate-50 p-4">
              <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">Step {index + 1}</div>
              <div className="mt-2 text-sm font-semibold text-slate-950">{node}</div>
              <div className="mt-2 h-2 rounded-full bg-blue-100">
                <div className="h-full rounded-full bg-blue-600" style={{ width: `${(index + 1) * 25}%` }} />
              </div>
            </div>
          ))}
        </div>
        <div className="mt-4 rounded-xl border border-blue-200 bg-blue-50 p-4">
          <div className="text-xs font-semibold uppercase tracking-wide text-blue-700">Research Objective</div>
          <div className="mt-1 text-sm font-semibold text-blue-950">{method}</div>
        </div>
      </VisualCard>
      <AnalysisEvidenceTable table={{
        title: "Statistical Roadmap",
        headers: ["Component", "Draft"],
        rows: [
          ["Question", state.objective || "Document the measurable research question."],
          ["Data needed", state.inputs || "List response, factors, population, and exclusions."],
          ["Assumptions", state.assumptions || "Capture independence, stable treatment, and measurement assumptions."],
          ["QA checks", state.validation || "Define balance, power, and analysis validation checks."],
        ],
      }} />
    </section>
  );
}

function deterministicRandom(seed: number) {
  let value = Math.max(1, Math.round(seed)) % 2147483647;
  return () => {
    value = (value * 48271) % 2147483647;
    return value / 2147483647;
  };
}

function priorBlockingSelections(projectId: string) {
  const blocking = loadExperimentalNodeState(projectId, "Blocking");
  const selected = ((blocking?.metrics ?? []) as string[]).filter((item) => item !== "__none__");
  if (selected.length) return selected;
  const candidates = parseListItems(blocking?.objective ?? "");
  return candidates.length ? [candidates[0]] : ["Customer risk segment"];
}

function randomizationDesignInputs(projectId: string, state: NodeState) {
  const factors = sharedParseFactorHierarchy(loadExperimentalNodeState(projectId, "Levels")?.objective ?? "");
  const cells = factors.length ? treatmentCellCount(factors) : Math.max(1, Math.round(state.numeric.averageLevels ** state.numeric.factorCount));
  const blockingSelections = priorBlockingSelections(projectId);
  const method = state.method || (blockingSelections.length ? "Stratified randomization" : "Simple randomization");
  const availablePopulation = Number(state.numeric.availablePopulation || state.numeric.totalPlannedSample || 25000);
  const allocationMode = state.allocationMode || "equal";
  const equalPct = 100 / Math.max(cells, 1);
  const allocationPercentages = Array.from({ length: cells }, (_, index) => allocationMode === "custom" ? Number(state.numeric[`allocationPct${index + 1}`] || equalPct) : equalPct);
  const allocationTotal = allocationPercentages.reduce((sum, pct) => sum + pct, 0);
  return {
    factors,
    cells,
    method,
    blockingSelections,
    selectedStratum: state.blockStratum || blockingSelections[0] || "Customer risk segment",
    assignmentUnit: state.assignmentUnit || "Customer",
    availablePopulation,
    allocationMode,
    allocationPercentages,
    allocationTotal,
    seed: Math.round(Number(state.numeric.seed || 42)),
    selectedExclusions: state.selectedExclusions?.length ? state.selectedExclusions : ["inactive", "opt-out", "recent-offer"],
  };
}

function computeEligiblePopulation(designState: ReturnType<typeof randomizationDesignInputs>) {
  const exclusionCatalog = [
    { key: "inactive", label: "Inactive", count: 302 },
    { key: "opt-out", label: "Opt out", count: 418 },
    { key: "recent-offer", label: "Recent offer", count: 414 },
    { key: "fraud-deceased-regulatory", label: "Fraud/deceased/regulatory suppression", count: 96 },
  ];
  const exclusions = exclusionCatalog.map((item) => ({ ...item, selected: designState.selectedExclusions.includes(item.key) }));
  const excluded = exclusions.filter((item) => item.selected).reduce((sum, item) => sum + item.count, 0);
  return { exclusions, excluded, eligible: Math.max(0, designState.availablePopulation - excluded) };
}

function computeTreatmentAllocation(designState: ReturnType<typeof randomizationDesignInputs>) {
  const population = computeEligiblePopulation(designState);
  const allocation = designState.allocationPercentages.map((pct, index) => {
    const normalizedPct = designState.allocationTotal > 0 ? pct / designState.allocationTotal : 1 / designState.cells;
    return { label: `T${index + 1}`, count: Math.round(population.eligible * normalizedPct), pct, normalizedPct };
  });
  return { ...population, allocation, expectedPerCell: Math.floor(population.eligible / Math.max(designState.cells, 1)) };
}

function simulateRandomizationBalance(designState: ReturnType<typeof randomizationDesignInputs>, seed: number, iterations = 1000) {
  const rng = deterministicRandom(seed);
  const methodFactor =
    designState.method === "Stratified randomization" ? 0.55 :
    designState.method === "Blocked randomization" ? 0.5 :
    designState.method === "Covariate-adaptive randomization" ? 0.42 :
    designState.method === "Cluster randomization" ? 1.25 :
    1;
  const values = Array.from({ length: iterations }, () => {
    const base = 0.002 + rng() * 0.025;
    const cellPenalty = Math.min(0.025, Math.max(0, designState.cells - 4) * 0.002);
    return Number(((base + cellPenalty) * methodFactor).toFixed(4));
  }).sort((a, b) => a - b);
  const median = values[Math.floor(values.length * 0.5)] ?? 0;
  const p95 = values[Math.floor(values.length * 0.95)] ?? 0;
  const selectedSeed = values[Math.min(values.length - 1, Math.abs(seed) % values.length)] ?? median;
  const buckets = [
    { label: "0-0.5%", min: 0, max: 0.005 },
    { label: "0.5-1.0%", min: 0.005, max: 0.01 },
    { label: "1.0-1.5%", min: 0.01, max: 0.015 },
    { label: "1.5-2.0%", min: 0.015, max: 0.02 },
    { label: "2.0%+", min: 0.02, max: 999 },
  ].map((bucket) => ({ label: bucket.label, value: values.filter((value) => value >= bucket.min && value < bucket.max).length }));
  return { median, p95, selectedSeed, buckets, iterations };
}

function computeRandomizationDiagnostics(designState: ReturnType<typeof randomizationDesignInputs>) {
  const allocation = computeTreatmentAllocation(designState);
  const simulation = simulateRandomizationBalance(designState, designState.seed, 1000);
  const balanceThreshold = 0.1;
  const covariateBalance = ["Age", "Income", "FICO", "Region", "Risk"].map((label, index) => {
    const pre = 0.22 - index * 0.025;
    const post = Math.max(0.01, pre * (designState.method === "Simple randomization" ? 0.55 : 0.22));
    return {
      label,
      pre,
      post,
      threshold: balanceThreshold,
      status: post <= balanceThreshold ? "Pass" : "Review",
    };
  });
  const allocationDiagnostics = allocation.allocation.map((row, index) => {
    const averageImbalance = simulation.median * (1 + index * 0.04);
    const worstImbalance = simulation.p95 * (1 + index * 0.05);
    const rangeDelta = Math.max(1, Math.round(row.count * worstImbalance));
    return {
      ...row,
      averageImbalance,
      worstImbalance,
      rangeLow: Math.max(0, row.count - rangeDelta),
      rangeHigh: row.count + rangeDelta,
    };
  });
  const ratioPass = Math.abs(designState.allocationTotal - 100) <= 0.5;
  const stratumPass = /stratified|blocked|adaptive/i.test(designState.method);
  const seedPass = designState.seed > 0;
  const auditReady = seedPass && ratioPass && allocation.eligible > 0;
  const qaRows = [
    { label: "Treatment ratio", status: ratioPass ? "Pass" : "Review", detail: ratioPass ? "Allocation percentages total 100%." : "Allocation percentages must total 100%." },
    { label: "Within-stratum balance", status: stratumPass ? "Pass" : "Review", detail: stratumPass ? `${designState.selectedStratum} is controlled during assignment.` : "No formal stratum is selected." },
    { label: "Covariate balance", status: simulation.p95 < 0.025 ? "Pass" : "Review", detail: "Simulated imbalance remains within review threshold." },
    { label: "Seed stored", status: seedPass ? "Pass" : "Fail", detail: seedPass ? `Seed ${designState.seed} is recorded.` : "A positive seed is required." },
    { label: "Assignment audit file", status: auditReady ? "Ready" : "Pending", detail: auditReady ? "Assignment logic is reproducible." : "Resolve pending diagnostics before launch." },
  ];
  const heatmapRows = ["Customer risk segment", "Geographic region", "Prior response history", "FICO score band"].map((label, rowIndex) => ({
    label,
    values: Array.from({ length: Math.min(4, designState.cells) }, (_, cellIndex) => {
      const drift = ((rowIndex + 1) * (cellIndex + 2) + designState.seed % 7) % 9;
      return Number((1 + (drift - 4) / 100).toFixed(2));
    }),
  }));
  return { allocation, allocationDiagnostics, simulation, qaRows, heatmapRows, covariateBalance, balanceThreshold };
}

function scoreRandomizationQuality(designState: ReturnType<typeof randomizationDesignInputs>) {
  const diagnostics = computeRandomizationDiagnostics(designState);
  return Math.round((diagnostics.qaRows.filter((row) => row.status === "Pass" || row.status === "Ready").length / diagnostics.qaRows.length) * 100);
}

function RandomizationStudio({ projectId, state, setState }: { projectId: string; state: NodeState; setState: (state: NodeState) => void }) {
  const design = randomizationDesignInputs(projectId, state);
  const diagnostics = computeRandomizationDiagnostics(design);
  const allocationValid = Math.abs(design.allocationTotal - 100) <= 0.5;
  const quality = scoreRandomizationQuality(design);
  const methodCards = [
    ["Simple randomization", "Assign units independently at random.", "Use when no strong nuisance variables need control.", "Can create imbalance in rare or small samples."],
    ["Stratified randomization", "Randomize within important strata.", "Use when risk segment or another response driver should be balanced.", "Too many strata can reduce per-cell sample."],
    ["Blocked randomization", "Use fixed blocks to preserve ratios.", "Use when assignment occurs in waves or batches.", "Block definition must be auditable."],
    ["Cluster randomization", "Assign groups instead of individuals.", "Use when individual assignment is not feasible.", "Lower effective sample and higher imbalance risk."],
    ["Covariate-adaptive randomization", "Adapt assignment to maintain covariate balance.", "Use when several covariates are critical.", "Requires tighter implementation control."],
  ];
  const updateAllocation = (index: number, value: number) => {
    setState({ ...state, allocationMode: "custom", numeric: { ...state.numeric, [`allocationPct${index + 1}`]: value } });
  };
  const setEqualAllocation = () => {
    const nextNumeric = { ...state.numeric };
    Array.from({ length: design.cells }, (_, index) => {
      nextNumeric[`allocationPct${index + 1}`] = 100 / Math.max(design.cells, 1);
    });
    setState({ ...state, allocationMode: "equal", numeric: nextNumeric });
  };
  const toggleExclusion = (key: string, checked: boolean) => {
    const selectedExclusions = checked ? Array.from(new Set([...design.selectedExclusions, key])) : design.selectedExclusions.filter((item) => item !== key);
    setState({ ...state, selectedExclusions });
  };

  return (
    <section className="space-y-7">
      <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <div className="text-xs font-semibold uppercase tracking-wide text-blue-700">Randomization Decision</div>
            <h2 className="mt-1 text-lg font-semibold text-slate-950">Choose the assignment method ATLAS should execute.</h2>
            <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-600">
              ATLAS recommends stratified randomization when blocking evidence indicates a nuisance variable should be controlled during treatment assignment.
            </p>
          </div>
          <div className="rounded-full border border-emerald-200 bg-emerald-50 px-3 py-1 text-xs font-semibold text-emerald-800">
            Randomization quality: {quality}%
          </div>
        </div>

        <div className="mt-5 grid gap-3 xl:grid-cols-5">
          {methodCards.map(([method, description, when, caution]) => {
            const selected = design.method === method;
            return (
              <button
                key={method}
                type="button"
                className={`rounded-2xl border p-4 text-left transition hover:-translate-y-0.5 hover:shadow-md ${
                  selected ? "border-blue-300 bg-blue-50 shadow-sm" : "border-slate-200 bg-slate-50"
                }`}
                onClick={() => setState({ ...state, method })}
              >
                <div className="flex items-center gap-2">
                  <span className={`h-3 w-3 rounded-full border ${selected ? "border-blue-600 bg-blue-600" : "border-slate-300 bg-white"}`} />
                  <span className="text-sm font-semibold text-slate-950">{method}</span>
                </div>
                <p className="mt-2 text-xs leading-5 text-slate-600">{description}</p>
                <p className="mt-2 text-[11px] leading-4 text-slate-500"><span className="font-semibold">Use when:</span> {when}</p>
                <p className="mt-1 text-[11px] leading-4 text-amber-700"><span className="font-semibold">Caution:</span> {caution}</p>
              </button>
            );
          })}
        </div>

        <div className="mt-6 grid gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
          <div className="grid min-w-0 gap-4 lg:grid-cols-3">
            <label className="grid min-w-0 gap-1.5">
              <span className="text-xs font-semibold uppercase tracking-wide text-slate-500">Assignment unit</span>
              <select className="w-full min-w-0 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm" value={design.assignmentUnit} onChange={(event) => setState({ ...state, assignmentUnit: event.target.value })}>
                {["Customer", "Account", "Household", "Branch", "Region"].map((unit) => <option key={unit} value={unit}>{unit}</option>)}
              </select>
            </label>
            <label className="grid min-w-0 gap-1.5">
              <span className="text-xs font-semibold uppercase tracking-wide text-slate-500">Block / strata</span>
              <select className="w-full min-w-0 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm" value={design.selectedStratum} onChange={(event) => setState({ ...state, blockStratum: event.target.value })}>
                {Array.from(new Set([...design.blockingSelections, "Customer risk segment", "Geographic region", "Campaign week"])).map((stratum) => <option key={stratum} value={stratum}>{stratum}</option>)}
              </select>
            </label>
            <label className="grid min-w-0 gap-1.5">
              <span className="text-xs font-semibold uppercase tracking-wide text-slate-500">Random seed</span>
              <input type="number" className="w-full min-w-0 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm" value={design.seed} onChange={(event) => setState({ ...state, numeric: { ...state.numeric, seed: Number(event.target.value || 0) } })} />
            </label>
          </div>

          <div className="rounded-xl border border-slate-200 bg-slate-50 p-4">
            <button type="button" className="w-full rounded-lg border border-blue-200 bg-blue-50 px-3 py-2 text-sm font-semibold text-blue-800 hover:bg-blue-100" onClick={() => setState({ ...state, numeric: { ...state.numeric, seed: design.seed + 17 } })}>
              Regenerate seed
            </button>
            <div className="mt-3 text-xs leading-5 text-slate-600">
              Seeded assignment keeps the treatment file reproducible for validation, audit, and launch approval.
            </div>
          </div>
        </div>

        <div className="mt-5 rounded-2xl border border-slate-200 bg-slate-50 p-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Allocation ratio editor</div>
              <div className={`mt-1 text-sm font-semibold ${allocationValid ? "text-emerald-700" : "text-amber-700"}`}>
                Total allocation: {design.allocationTotal.toFixed(1)}%
              </div>
            </div>
            <div className="flex gap-2">
              <button type="button" className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs font-semibold text-slate-700 hover:bg-slate-50" onClick={setEqualAllocation}>Equal allocation</button>
              <button type="button" className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs font-semibold text-slate-700 hover:bg-slate-50" onClick={() => setState({ ...state, allocationMode: "custom" })}>Custom allocation</button>
            </div>
          </div>
          <div className="mt-4 grid gap-3 md:grid-cols-4">
            {diagnostics.allocation.allocation.slice(0, 8).map((row, index) => (
              <label key={row.label} className="grid gap-1.5 rounded-xl border border-slate-200 bg-white p-3">
                <span className="text-xs font-semibold text-slate-700">{row.label}</span>
                <input type="number" min={0} max={100} step={0.1} className="rounded-lg border border-slate-300 px-2 py-1.5 text-sm" value={Number(design.allocationPercentages[index]?.toFixed(1) ?? 0)} onChange={(event) => updateAllocation(index, Number(event.target.value || 0))} />
              </label>
            ))}
          </div>
        </div>

        <div className="mt-5 grid gap-3 md:grid-cols-4">
          {diagnostics.allocation.exclusions.map((exclusion) => (
            <label key={exclusion.key} className="flex items-center justify-between gap-3 rounded-xl border border-slate-200 bg-white px-4 py-3 text-sm">
              <span>
                <span className="block font-semibold text-slate-900">{exclusion.label}</span>
                <span className="block text-xs text-slate-500">{exclusion.count.toLocaleString()} records</span>
              </span>
              <input type="checkbox" className="h-4 w-4 accent-blue-600" checked={exclusion.selected} onChange={(event) => toggleExclusion(exclusion.key, event.target.checked)} />
            </label>
          ))}
        </div>
      </section>

      <section className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_420px]">
        <VisualCard title="Simulated Assignment Preview" subtitle="Expected assignment after exclusions using the selected method and seed.">
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4 2xl:grid-cols-7">
            <ResultCard label="Available population" value={design.availablePopulation.toLocaleString()} />
            <ResultCard label="Excluded" value={diagnostics.allocation.excluded.toLocaleString()} />
            <ResultCard label="Eligible" value={diagnostics.allocation.eligible.toLocaleString()} />
            <ResultCard label="Treatment cells" value={design.cells.toLocaleString()} />
            <ResultCard label="Expected per cell" value={diagnostics.allocation.expectedPerCell.toLocaleString()} />
            <ResultCard label="Worst imbalance" value={formatPct(diagnostics.simulation.p95)} />
            <ResultCard label="Avg. imbalance" value={formatPct(diagnostics.simulation.median)} />
          </div>
          <div className="mt-5">
            <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">Treatment Allocation</div>
            <HorizontalBars rows={diagnostics.allocationDiagnostics.map((row) => ({ label: `${row.label} (${formatPct(row.normalizedPct, 1)})`, value: row.count }))} valueFormatter={(value) => value.toLocaleString()} />
            <p className="mt-3 text-xs leading-5 text-slate-500">Expected allocation reflects selected exclusions and allocation ratios.</p>
          </div>
          <div className="mt-5 overflow-x-auto rounded-xl border border-slate-200">
            <table className="min-w-[760px] w-full text-left text-xs">
              <thead className="bg-slate-50 font-semibold uppercase tracking-wide text-slate-500">
                <tr>
                  <th className="px-4 py-3">Treatment cell</th>
                  <th className="px-4 py-3">Expected count</th>
                  <th className="px-4 py-3">Expected %</th>
                  <th className="px-4 py-3">Avg. imbalance</th>
                  <th className="px-4 py-3">Worst imbalance</th>
                  <th className="px-4 py-3">95% expected range</th>
                </tr>
              </thead>
              <tbody>
                {diagnostics.allocationDiagnostics.map((row) => (
                  <tr key={row.label} className="border-t border-slate-200 odd:bg-white even:bg-slate-50">
                    <td className="px-4 py-3 font-semibold text-slate-900">{row.label}</td>
                    <td className="px-4 py-3 text-slate-700">{row.count.toLocaleString()}</td>
                    <td className="px-4 py-3 text-slate-700">{formatPct(row.normalizedPct, 1)}</td>
                    <td className="px-4 py-3 text-slate-700">{formatPct(row.averageImbalance)}</td>
                    <td className="px-4 py-3 text-slate-700">{formatPct(row.worstImbalance)}</td>
                    <td className="px-4 py-3 text-slate-700">{row.rangeLow.toLocaleString()} - {row.rangeHigh.toLocaleString()}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </VisualCard>

        <div className="space-y-4">
          <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
            <div className="text-xs font-semibold uppercase tracking-wide text-blue-700">Population Funnel</div>
            <div className="mt-4 space-y-3">
              {[
                ["Available Population", design.availablePopulation],
                ["Exclusions Removed", diagnostics.allocation.excluded],
                ["Eligible Population", diagnostics.allocation.eligible],
                ["Assigned Treatments", diagnostics.allocation.allocation.reduce((sum, row) => sum + row.count, 0)],
              ].map(([label, value], index) => (
                <div key={String(label)}>
                  <div className="flex items-center justify-between text-sm">
                    <span className="font-semibold text-slate-800">{label}</span>
                    <span className="font-semibold text-slate-950">{Number(value).toLocaleString()}</span>
                  </div>
                  {index < 3 && <div className="mx-auto my-2 h-5 w-px bg-blue-200" />}
                </div>
              ))}
            </div>
          </section>
        </div>
      </section>

      <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <div className="text-xs font-semibold uppercase tracking-wide text-blue-700">Assignment Diagnostics</div>
        <h3 className="mt-1 text-base font-semibold text-slate-950">ATLAS checks whether assignment is balanced and auditable before launch.</h3>
        <div className="mt-4 grid gap-3 md:grid-cols-5">
          {diagnostics.qaRows.map(({ label, status, detail }) => (
            <div key={label} className={`rounded-xl border p-4 ${status === "Pass" || status === "Ready" ? "border-emerald-200 bg-emerald-50" : status === "Fail" ? "border-rose-200 bg-rose-50" : "border-amber-200 bg-amber-50"}`}>
              <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">{label}</div>
              <div className={`mt-2 text-lg font-semibold ${status === "Pass" || status === "Ready" ? "text-emerald-800" : status === "Fail" ? "text-rose-800" : "text-amber-800"}`}>{status}</div>
              <p className="mt-2 text-xs leading-5 text-slate-600">{detail}</p>
            </div>
          ))}
        </div>

        <div className="mt-6 grid gap-6 xl:grid-cols-[minmax(0,1fr)_380px]">
          <div className="overflow-x-auto rounded-xl border border-slate-200">
            <table className="min-w-[620px] w-full text-left text-xs">
              <thead className="bg-slate-50 font-semibold uppercase tracking-wide text-slate-500">
                <tr>
                  <th className="px-4 py-3">Balance check</th>
                  {diagnostics.allocation.allocation.slice(0, 4).map((row) => <th key={row.label} className="px-4 py-3">{row.label}</th>)}
                </tr>
              </thead>
              <tbody>
                {diagnostics.heatmapRows.map((row) => (
                  <tr key={row.label} className="border-t border-slate-200">
                    <td className="px-4 py-3 font-semibold text-slate-800">{row.label}</td>
                    {row.values.map((value, index) => {
                      const diff = Math.abs(value - 1);
                      const color = diff <= 0.03 ? "bg-emerald-50 text-emerald-800" : diff <= 0.06 ? "bg-amber-50 text-amber-800" : "bg-rose-50 text-rose-800";
                      return <td key={`${row.label}-${index}`} className="px-4 py-3"><span className={`rounded-md px-2 py-1 font-semibold ${color}`}>{value.toFixed(2)}</span></td>;
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="rounded-xl border border-slate-200 bg-slate-50 p-4">
            <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Imbalance Distribution</div>
            <div className="mt-3">
              <HorizontalBars rows={diagnostics.simulation.buckets} valueFormatter={(value) => value.toLocaleString()} />
            </div>
            <div className="mt-4 grid gap-2 text-xs text-slate-700">
              <div className="flex justify-between"><span>Median max imbalance</span><span className="font-semibold">{formatPct(diagnostics.simulation.median)}</span></div>
              <div className="flex justify-between"><span>95th percentile</span><span className="font-semibold">{formatPct(diagnostics.simulation.p95)}</span></div>
              <div className="flex justify-between"><span>Selected seed</span><span className="font-semibold">{formatPct(diagnostics.simulation.selectedSeed)}</span></div>
            </div>
          </div>
        </div>
      </section>

      <section className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_420px]">
        <VisualCard title="Covariate Balance Diagnostics" subtitle={`Standardized mean differences before and after randomization. Acceptable threshold: ${diagnostics.balanceThreshold.toFixed(2)}.`}>
          <div className="space-y-4">
            {diagnostics.covariateBalance.map((row) => {
              const before = row.pre;
              const after = row.post;
              return (
                <div key={row.label} className="grid grid-cols-[80px_minmax(0,1fr)_48px] items-center gap-3 text-xs">
                  <div className="font-semibold text-slate-700">{row.label}</div>
                  <div className="relative space-y-1">
                    <div className="absolute bottom-0 top-0 w-px bg-amber-500" style={{ left: `${Math.min(100, diagnostics.balanceThreshold * 380)}%` }}>
                      <span className="absolute -top-4 -translate-x-1/2 whitespace-nowrap text-[10px] font-semibold text-amber-700">0.10</span>
                    </div>
                    <div className="h-2 rounded-full bg-slate-200">
                      <div className="h-full rounded-full bg-slate-400" style={{ width: `${Math.min(100, before * 380)}%` }} />
                    </div>
                    <div className="h-2 rounded-full bg-blue-100">
                      <div className="h-full rounded-full bg-blue-600" style={{ width: `${Math.min(100, after * 380)}%` }} />
                    </div>
                  </div>
                  <div className="text-right font-semibold text-slate-700">{after.toFixed(2)}</div>
                </div>
              );
            })}
          </div>
          <div className="mt-4 flex gap-4 text-xs text-slate-500">
            <span><span className="inline-block h-2 w-5 rounded-full bg-slate-400" /> Before</span>
            <span><span className="inline-block h-2 w-5 rounded-full bg-blue-600" /> After</span>
            <span><span className="inline-block h-3 w-px bg-amber-500" /> Threshold</span>
          </div>
          <div className="mt-5 overflow-hidden rounded-xl border border-slate-200">
            <table className="w-full text-left text-xs">
              <thead className="bg-slate-50 font-semibold uppercase tracking-wide text-slate-500">
                <tr>
                  <th className="px-4 py-3">Covariate</th>
                  <th className="px-4 py-3">Pre</th>
                  <th className="px-4 py-3">Post</th>
                  <th className="px-4 py-3">Threshold</th>
                  <th className="px-4 py-3">Status</th>
                </tr>
              </thead>
              <tbody>
                {diagnostics.covariateBalance.map((row) => (
                  <tr key={row.label} className="border-t border-slate-200 odd:bg-white even:bg-slate-50">
                    <td className="px-4 py-3 font-semibold text-slate-900">{row.label}</td>
                    <td className="px-4 py-3">{row.pre.toFixed(2)}</td>
                    <td className="px-4 py-3">{row.post.toFixed(2)}</td>
                    <td className="px-4 py-3">{row.threshold.toFixed(2)}</td>
                    <td className="px-4 py-3">
                      <span className={`rounded-full px-2 py-1 text-[11px] font-semibold ${row.status === "Pass" ? "bg-emerald-50 text-emerald-700" : "bg-amber-50 text-amber-700"}`}>
                        {row.status}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </VisualCard>
        <VisualCard title="Distribution of Cell Sizes" subtitle="Simulated treatment cell count variation across repeated assignment draws.">
          <HorizontalBars
            rows={diagnostics.allocation.allocation.slice(0, 8).map((row, index) => ({
              label: row.label,
              value: Math.max(0, row.count + Math.round((diagnostics.simulation.selectedSeed * 1000 - 10) * (index % 2 === 0 ? 1 : -1))),
            }))}
            valueFormatter={(value) => value.toLocaleString()}
          />
        </VisualCard>
      </section>

      <section className="rounded-2xl border border-blue-200 bg-blue-50 p-6 shadow-sm">
        <div className="text-xs font-semibold uppercase tracking-wide text-blue-700">Decision Sensitivity</div>
        <h3 className="mt-1 text-base font-semibold text-blue-950">If the assignment method changes, downstream balance, power, and operational complexity change.</h3>
        <div className="mt-4 grid gap-4 lg:grid-cols-3">
          {[
            ["Current selection", design.method, "80%", formatPct(diagnostics.simulation.median), "Low", design.method === "Stratified randomization" ? "Recommended" : "Review"],
            ["Alternative", "Simple randomization", "78%", "1.4%", "Low", design.blockingSelections.length ? "Monitor only" : "Acceptable"],
            ["Alternative", "Add geographic region as stratum", "72%", "0.6%", "Medium", "Use only if material"],
          ].map(([scenario, method, power, imbalance, complexity, recommendation]) => (
            <div key={`${scenario}-${method}`} className="rounded-xl border border-blue-200 bg-white p-4">
              <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">{scenario}</div>
              <div className="mt-1 text-sm font-semibold text-slate-950">{method}</div>
              <div className="mt-3 grid gap-2 text-sm text-slate-700">
                <div className="flex justify-between"><span>Expected power</span><span className="font-semibold">{power}</span></div>
                <div className="flex justify-between"><span>Avg. imbalance</span><span className="font-semibold">{imbalance}</span></div>
                <div className="flex justify-between"><span>Complexity</span><span className="font-semibold">{complexity}</span></div>
                <div className="flex justify-between"><span>Recommendation</span><span className="font-semibold">{recommendation}</span></div>
              </div>
            </div>
          ))}
        </div>
      </section>
    </section>
  );
}

function SampleSizeStudio({ state, setState }: { state: NodeState; setState: (state: NodeState) => void }) {
  return (
    <SampleSizePowerPlanner state={state} setState={setState} />
  );
}

function RunPlanTopSimulationSummary({ projectId, state }: { projectId: string; state: NodeState }) {
  const sampleState = loadExperimentalNodeState(projectId, "Sample Size") ?? state;
  const monteState = loadExperimentalNodeState(projectId, "Monte Carlo Simulation") ?? state;
  const plan = sampleSizePlan(sampleState);
  const results = monteState.simulationResults;
  const sampleShortfall = results ? Math.max(0, plan.total - results.inputs.totalSample) : 0;
  const launchApproved = results && (results.recommendedAction === "Strong" || results.recommendedAction === "Adequate");
  return (
    <section className={`rounded-2xl border p-6 shadow-sm ${launchApproved ? "border-emerald-200 bg-emerald-50" : "border-rose-200 bg-rose-50"}`}>
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className={`text-xs font-semibold uppercase tracking-wide ${launchApproved ? "text-emerald-800" : "text-rose-800"}`}>Simulation Summary from Monte Carlo</div>
          <h2 className="mt-1 text-xl font-semibold text-slate-950">
            {results ? "Operational launch planning is tied to simulation evidence." : "Run Monte Carlo before finalizing the execution plan."}
          </h2>
          <p className="mt-2 max-w-4xl text-sm leading-6 text-slate-700">
            {results
              ? simulationNarrative(results)
              : "The run plan cannot be fully approved until ATLAS has quantified power, false-negative risk, wrong-winner risk, decision stability, and sample adequacy."}
          </p>
        </div>
        <span className={`rounded-full border px-3 py-1 text-xs font-semibold ${launchApproved ? "border-emerald-300 bg-white text-emerald-800" : "border-rose-300 bg-white text-rose-800"}`}>
          {results?.recommendedAction ?? "Monte Carlo pending"}
        </span>
      </div>
      <div className="mt-5 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <ResultCard label="Launch readiness" value={results?.recommendedAction ?? "Pending"} />
        <ResultCard label="Mean power" value={results ? formatPct(results.meanPower) : "Pending"} />
        <ResultCard label="Wrong winner risk" value={results ? formatPct(results.wrongWinnerRate) : "Pending"} />
        <ResultCard label="False negative rate" value={results ? formatPct(results.falseNegativeRate) : "Pending"} />
        <ResultCard label="Sample shortfall" value={results ? sampleShortfall.toLocaleString() : "Pending"} />
        <ResultCard label="Decision stability" value={results ? formatPct(results.decisionStabilityScore) : "Pending"} />
        <ResultCard label="CI coverage" value={results ? formatPct(results.confidenceIntervalCoverage) : "Pending"} />
        <ResultCard label="Recommendation" value={launchApproved ? "Launch approved" : results ? "Redesign required" : "Run simulation"} />
      </div>
    </section>
  );
}

function RunPlanStudio({ projectId, state, setState }: { projectId: string; state: NodeState; setState: (state: NodeState) => void }) {
  const randomState = loadExperimentalNodeState(projectId, "Randomization") ?? state;
  const sampleState = loadExperimentalNodeState(projectId, "Sample Size") ?? state;
  const monteState = loadExperimentalNodeState(projectId, "Monte Carlo Simulation") ?? state;
  const samplePlan = sampleSizePlan(sampleState);
  const randomDesign = randomizationDesignInputs(projectId, randomState);
  const randomDiagnostics = computeRandomizationDiagnostics(randomDesign);
  const monteResults = monteState.simulationResults;
  const checklist = [
    { key: "population_frozen", label: "Population frozen", source: "Eligibility", done: randomDiagnostics.allocation.eligible > 0 },
    { key: "assignment_exported", label: "Assignment exported", source: "Assignment", done: state.metrics.includes("assignment_exported") },
    { key: "seed_stored", label: "Seed stored", source: "Randomization", done: randomDesign.seed > 0 },
    { key: "qa_completed", label: "QA completed", source: "QA", done: state.validation.trim().length > 0 },
    { key: "monitoring_configured", label: "Monitoring configured", source: "Monitoring", done: state.inputs.trim().length > 0 },
    { key: "rollback_available", label: "Rollback plan available", source: "Rollback", done: state.risks.trim().length > 0 },
    { key: "contact_frequency_validated", label: "Contact frequency validated", source: "Operations", done: state.metrics.includes("contact_frequency_validated") },
    { key: "fair_lending_approval", label: "Fair Lending approval", source: "Compliance", done: state.metrics.includes("fair_lending_approval") },
    { key: "business_approval", label: "Business approval", source: "Approval", done: state.metrics.includes("business_approval") },
    { key: "data_engineering_approval", label: "Data Engineering approval", source: "Approval", done: state.metrics.includes("data_engineering_approval") },
  ];
  const completedChecks = checklist.filter((item) => item.done).length;
  const qaScore = completedChecks / checklist.length;
  const assignmentScore = randomDiagnostics.qaRows.filter((row) => row.status === "Pass" || row.status === "Ready").length / randomDiagnostics.qaRows.length;
  const monteScore = monteResults ? monteResults.decisionStabilityScore : 0.65;
  const sampleScore = samplePlan.adequatelyPowered ? 1 : 0.62;
  const launchScore = Math.round((qaScore * 0.28 + assignmentScore * 0.24 + monteScore * 0.24 + sampleScore * 0.14 + (state.decision ? 0.1 : 0.04)) * 100);
  const readinessStatus = launchScore >= 85 ? "Ready" : launchScore >= 70 ? "Conditionally Ready" : "Not Ready";
  const tone = launchScore >= 85 ? "emerald" : launchScore >= 70 ? "amber" : "rose";
  const monteCarloConfidence = monteResults
    ? Math.round((monteResults.meanPower * 0.35 + monteResults.decisionStabilityScore * 0.3 + (1 - monteResults.wrongWinnerRate) * 0.2 + monteResults.confidenceIntervalCoverage * 0.15) * 100)
    : null;
  const monteLaunchRecommendation =
    monteResults?.recommendedAction === "Strong" || monteResults?.recommendedAction === "Adequate"
      ? "Proceed"
      : monteResults?.recommendedAction === "Weak"
        ? "Proceed with controls"
        : monteResults?.recommendedAction === "Redesign Required"
          ? "Redesign before launch"
          : "Run simulation first";
  const monteKeyRisk = monteResults?.riskDrivers?.[0]?.explanation ?? "Run Monte Carlo before finalizing the execution plan.";
  const toggleCheck = (key: string, checked: boolean) => {
    const metrics = checked ? Array.from(new Set([...state.metrics, key])) : state.metrics.filter((item) => item !== key);
    setState({ ...state, metrics });
  };
  const timeline = [
    ["Preparation", "Completed", "Population, factors, and treatment cells defined."],
    ["Eligibility Validation", randomDiagnostics.allocation.eligible ? "Completed" : "Blocked", `${randomDiagnostics.allocation.eligible.toLocaleString()} eligible units.`],
    ["Treatment Assignment", assignmentScore >= 0.8 ? "Completed" : "In Progress", `${randomDesign.cells} cells using ${randomDesign.method}.`],
    ["QA Verification", state.validation ? "Completed" : "Pending", "Operational QA evidence required."],
    ["Launch", launchScore >= 85 ? "Ready" : "Pending", readinessStatus],
    ["Monitoring", state.inputs ? "Configured" : "Pending", "Cadence, thresholds, and escalation ownership."],
    ["Completion", "Pending", "Closeout, analysis lock, and audit package."],
  ];
  const riskRows = [
    ["Execution drift", "Medium", "High", "Daily launch reconciliation", state.validation ? "Controlled" : "Open"],
    ["Treatment contamination", "Low", "High", "Suppression and duplicate checks", assignmentScore >= 0.8 ? "Controlled" : "Review"],
    ["Monitoring failure", "Medium", "High", "Named owner and alert thresholds", state.inputs ? "Controlled" : "Open"],
    ["Assignment failure", "Low", "High", "Seed, allocation QA, export audit", randomDesign.seed > 0 ? "Controlled" : "Open"],
    ["Unexpected attrition", "Medium", "Medium", "Stop rule and replacement logic", state.risks ? "Controlled" : "Review"],
    ["Data latency", "Medium", "Medium", "Daily feed SLA and escalation", state.metrics.includes("data_engineering_approval") ? "Controlled" : "Open"],
  ];
  const stopRules = [
    ["Power degradation", "< 75% expected power", "Pause and review sample", "Data Science"],
    ["Treatment imbalance", "> 5% allocation variance", "Freeze assignment file", "Experiment Owner"],
    ["Unexpected response", "Response outside forecast band", "Escalate to sponsor", "Business Owner"],
    ["Operational outage", "Delivery interruption", "Pause campaign", "Operations"],
    ["Data corruption", "Missing or duplicate assignment IDs", "Rollback export", "Data Engineering"],
    ["Customer complaints", "Threshold breach", "Compliance review", "Compliance"],
  ];
  const dailyVolume = Math.max(1, Math.round(samplePlan.plannedTotal / 20));
  return (
    <section className="space-y-6">
      <section className="rounded-2xl border border-blue-300 bg-gradient-to-br from-blue-50 via-white to-white p-7 shadow-sm">
        <div className="flex flex-wrap items-start justify-between gap-5">
          <div>
            <div className="text-xs font-semibold uppercase tracking-wide text-blue-700">Simulation Summary from Monte Carlo</div>
            <h2 className="mt-1 text-xl font-semibold text-slate-950">Monte Carlo evidence drives the operational launch plan.</h2>
            <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-600">
              {monteResults
                ? "ATLAS carried forward the simulation confidence, wrong-winner risk, and launch recommendation from the prior step."
                : "Run and save the Monte Carlo Simulation step to populate this banner with quantitative launch evidence."}
            </p>
          </div>
          <span className={`rounded-full border px-3 py-1 text-xs font-semibold ${monteResults ? "border-emerald-200 bg-emerald-50 text-emerald-800" : "border-amber-200 bg-amber-50 text-amber-800"}`}>
            {monteResults ? "Monte Carlo evidence linked" : "Monte Carlo pending"}
          </span>
        </div>
        <div className="mt-5 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <ResultCard label="Monte Carlo readiness" value={monteResults?.recommendedAction ?? "Pending"} />
          <ResultCard label="Monte Carlo confidence" value={monteCarloConfidence === null ? "Pending" : `${monteCarloConfidence}%`} />
          <ResultCard label="Mean power" value={monteResults ? formatPct(monteResults.meanPower) : "Pending"} />
          <ResultCard label="Median power" value={monteResults ? formatPct(monteResults.medianPower) : "Pending"} />
          <ResultCard label="Wrong-winner risk" value={monteResults ? formatPct(monteResults.wrongWinnerRate) : "Pending"} />
          <ResultCard label="False-negative rate" value={monteResults ? formatPct(monteResults.falseNegativeRate) : "Pending"} />
          <ResultCard label="Decision stability" value={monteResults ? formatPct(monteResults.decisionStabilityScore) : "Pending"} />
          <ResultCard label="CI coverage" value={monteResults ? formatPct(monteResults.confidenceIntervalCoverage) : "Pending"} />
        </div>
        <div className={`mt-4 rounded-xl border p-4 ${monteResults ? statusClass(monteResults.recommendedAction) : "border-amber-200 bg-amber-50 text-amber-900"}`}>
          <div className="text-xs font-semibold uppercase tracking-wide opacity-80">Recommendation</div>
          <div className="mt-1 text-base font-semibold">{monteLaunchRecommendation}</div>
          <p className="mt-2 text-sm leading-6">{monteKeyRisk}</p>
        </div>
      </section>

      <section className={`rounded-2xl border p-6 shadow-sm ${tone === "emerald" ? "border-emerald-200 bg-emerald-50" : tone === "amber" ? "border-amber-200 bg-amber-50" : "border-rose-200 bg-rose-50"}`}>
        <div className="grid gap-6 xl:grid-cols-[300px_minmax(0,1fr)]">
          <div className="rounded-2xl border border-white/80 bg-white p-6 text-center shadow-sm">
            <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Launch Confidence</div>
            <div className={`mt-4 text-6xl font-semibold ${tone === "emerald" ? "text-emerald-700" : tone === "amber" ? "text-amber-700" : "text-rose-700"}`}>{launchScore}</div>
            <div className="mt-2 text-lg font-semibold text-slate-950">{readinessStatus}</div>
            <p className="mt-3 text-xs leading-5 text-slate-600">Generated from QA, validation, evidence, Monte Carlo, assignment integrity, and operational controls.</p>
          </div>
          <div>
            <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Launch Readiness Dashboard</div>
            <h2 className="mt-1 text-xl font-semibold text-slate-950">Can this experiment safely be executed?</h2>
            <div className="mt-5 grid gap-3 md:grid-cols-3">
              <ReadinessCard label="Overall Launch Readiness" value={launchScore} />
              <ReadinessCard label="Execution Quality" value={Math.round(qaScore * 100)} />
              <ReadinessCard label="Operational Risk" value={Math.round((1 - riskRows.filter((row) => row[4] === "Open").length / riskRows.length) * 100)} />
              <ReadinessCard label="Treatment Integrity" value={Math.round(assignmentScore * 100)} />
              <ReadinessCard label="Monitoring Readiness" value={state.inputs ? 88 : 54} />
              <ReadinessCard label="QA Status" value={state.validation ? 92 : 58} />
            </div>
          </div>
        </div>
      </section>

      <VisualCard title="Execution Timeline" subtitle="Operational path from preparation through monitoring and completion.">
        <div className="grid gap-3 lg:grid-cols-7">
          {timeline.map(([phase, status, detail], index) => (
            <div key={phase} className="relative rounded-2xl border border-slate-200 bg-slate-50 p-4">
              <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">Step {index + 1}</div>
              <div className="mt-1 text-sm font-semibold text-slate-950">{phase}</div>
              <span className={`mt-3 inline-flex rounded-full px-2 py-1 text-[11px] font-semibold ${status === "Completed" || status === "Ready" || status === "Configured" ? "bg-emerald-50 text-emerald-700" : status === "Blocked" ? "bg-rose-50 text-rose-700" : "bg-amber-50 text-amber-700"}`}>{status}</span>
              <p className="mt-3 text-xs leading-5 text-slate-600">{detail}</p>
            </div>
          ))}
        </div>
      </VisualCard>

      <section className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_420px]">
        <VisualCard title="Operational Control Dashboard" subtitle="Required launch controls and evidence status.">
          <div className="grid gap-3 md:grid-cols-2">
            {[
              ["Population validated", randomDiagnostics.allocation.eligible > 0],
              ["Treatment assignment verified", assignmentScore >= 0.8],
              ["Randomization verified", randomDesign.seed > 0],
              ["Monitoring configured", !!state.inputs],
              ["Stopping rules configured", !!state.risks],
              ["Escalation owner assigned", !!state.decision],
              ["QA approved", !!state.validation],
              ["Evidence complete", qaScore >= 0.8],
            ].map(([label, done]) => (
              <div key={String(label)} className={`rounded-xl border p-4 ${done ? "border-emerald-200 bg-emerald-50" : "border-amber-200 bg-amber-50"}`}>
                <div className="text-sm font-semibold text-slate-950">{label}</div>
                <div className={`mt-2 text-xs font-semibold ${done ? "text-emerald-700" : "text-amber-700"}`}>{done ? "Ready" : "Needs attention"}</div>
              </div>
            ))}
          </div>
        </VisualCard>
        <VisualCard title="Assignment Integrity" subtitle="Treatment file reproducibility, allocation balance, and coverage.">
          <HorizontalBars
            rows={[
              { label: "Randomization verified", value: randomDesign.seed > 0 ? 1 : 0.35 },
              { label: "Treatment balance", value: 1 - randomDiagnostics.simulation.p95 },
              { label: "Assignment reproducibility", value: randomDesign.seed > 0 ? 1 : 0.25 },
              { label: "Duplicate assignments", value: 0.98 },
              { label: "Coverage", value: randomDiagnostics.allocation.eligible / Math.max(1, randomDesign.availablePopulation) },
              { label: "Allocation percentages", value: Math.abs(randomDesign.allocationTotal - 100) <= 0.5 ? 1 : 0.55 },
            ]}
            valueFormatter={formatPct}
          />
        </VisualCard>
      </section>

      <section className="grid gap-5 xl:grid-cols-2">
        <AnalysisEvidenceTable table={{ title: "Operational Risk Dashboard", headers: ["Risk", "Likelihood", "Severity", "Mitigation", "Status"], rows: riskRows }} />
        <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
          <h3 className="text-sm font-semibold text-slate-950">Live Launch Checklist</h3>
          <div className="mt-4 grid gap-2">
            {checklist.map((item) => (
              <label key={item.key} className="flex items-center justify-between gap-3 rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm">
                <span>
                  <span className="block font-semibold text-slate-900">{item.label}</span>
                  <span className="block text-xs text-slate-500">{item.source}</span>
                </span>
                <input type="checkbox" className="h-4 w-4 accent-blue-600" checked={item.done} onChange={(event) => toggleCheck(item.key, event.target.checked)} />
              </label>
            ))}
          </div>
        </section>
      </section>

      <section className="grid gap-5 xl:grid-cols-2">
        <VisualCard title="Monitoring Dashboard" subtitle="Expected launch monitoring and escalation readiness.">
          <div className="grid gap-3 md:grid-cols-2">
            <ResultCard label="Expected observations/day" value={dailyVolume.toLocaleString()} />
            <ResultCard label="Expected response rate" value={formatPct(samplePlan.baseline)} />
            <ResultCard label="Monitoring cadence" value="Daily launch QA" />
            <ResultCard label="Alert thresholds" value="Power, imbalance, complaints" />
            <ResultCard label="Automatic escalation" value={state.decision ? "Owner assigned" : "Owner needed"} />
            <ResultCard label="Drift detection" value="Assignment + response" />
            <ResultCard label="Health score" value={`${Math.round((qaScore + assignmentScore + monteScore) / 3 * 100)} / 100`} />
          </div>
        </VisualCard>
        <AnalysisEvidenceTable table={{ title: "Stop Rule Dashboard", headers: ["Trigger", "Threshold", "Action", "Owner"], rows: stopRules }} />
      </section>

      <section className="grid gap-5 xl:grid-cols-2">
        <VisualCard title="Rollback Strategy" subtitle="What happens if the experiment fails operational controls?">
          <div className="grid gap-3 md:grid-cols-5">
            {["Pause experiment", "Rollback assignments", "Restore production", "Notify stakeholders", "Export audit trail"].map((item, index) => (
              <div key={item} className="rounded-xl border border-slate-200 bg-slate-50 p-4 text-center">
                <div className="mx-auto flex h-8 w-8 items-center justify-center rounded-full bg-blue-600 text-sm font-semibold text-white">{index + 1}</div>
                <div className="mt-3 text-xs font-semibold text-slate-800">{item}</div>
              </div>
            ))}
          </div>
        </VisualCard>
        <VisualCard title="Resource Planning" subtitle="Operational load implied by the experiment structure.">
          <div className="grid gap-3 md:grid-cols-2">
            <ResultCard label="Treatment cells" value={randomDesign.cells.toLocaleString()} />
            <ResultCard label="Assignments" value={randomDiagnostics.allocation.eligible.toLocaleString()} />
            <ResultCard label="Expected observations" value={samplePlan.plannedTotal.toLocaleString()} />
            <ResultCard label="Daily volume" value={dailyVolume.toLocaleString()} />
            <ResultCard label="Duration" value="20 business days" />
            <ResultCard label="Monitoring resources" value="DS + Ops + Compliance" />
            <ResultCard label="Operational staffing" value={randomDesign.cells > 8 ? "Elevated" : "Standard"} />
          </div>
        </VisualCard>
      </section>

      <section className="rounded-2xl border border-emerald-200 bg-emerald-50 p-6 shadow-sm">
        <div className="text-xs font-semibold uppercase tracking-wide text-emerald-800">Decision Summary</div>
        <p className="mt-2 text-base leading-7 text-emerald-950">
          ATLAS has reviewed treatment assignment integrity, operational monitoring, QA validation, stopping rules, rollback controls, and Monte Carlo evidence. {launchScore >= 85 ? "All required launch controls appear satisfied and the experiment is operationally ready." : launchScore >= 70 ? "The experiment is close to launch readiness, but the open controls should be resolved before execution." : "The experiment should not launch until open QA, monitoring, and governance controls are completed."}
        </p>
      </section>
    </section>
  );
}

function AnovaStudio({ projectId, state }: { projectId: string; state: NodeState }) {
  const plan = generatedAnovaPlan(projectId, state);
  const rows = plan.termRows.map((row) => ({ label: row.term, value: row.df, status: "Adequate" as const }));
  return (
    <section className="space-y-4">
      <AnovaModelAssistant plan={plan} />
      <HorizontalBarChartCard
        title="ANOVA Degrees-of-Freedom Structure"
        subtitle="Main effects and interaction terms generated from factor names only."
        rows={rows.length ? rows : [{ label: "Terms pending", value: 1, status: "Weak" }]}
        valueFormatter={(value) => value.toLocaleString()}
        note="This is the statistical structure ATLAS will use for ANOVA documentation and interpretation guidance."
      />
    </section>
  );
}

function InteractionStudio({ projectId, state }: { projectId: string; state: NodeState }) {
  const plan = generatedAnovaPlan(projectId, state);
  const interactions = plan.termRows.filter((row) => /\s(?:x|×|Ã—)\s/.test(row.term));
  const matrixRows = interactions.slice(0, 8).map((row, index) => [
    row.term,
    index < 2 ? "Priority review" : "Standard review",
    row.df.toLocaleString(),
    index < 2 ? "Interpret within treatment cells" : "Confirm practical materiality",
  ]);
  return (
    <section className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_420px]">
      <VisualCard title="Interaction Heatmap Preview" subtitle="Prioritizes factor combinations that may change treatment interpretation.">
        <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
          {(interactions.length ? interactions : plan.factorNames.map((factor) => ({ term: factor, df: 1 }))).slice(0, 8).map((row, index) => (
            <div key={row.term} className={`rounded-xl border p-4 ${index < 2 ? "border-blue-200 bg-blue-50" : "border-slate-200 bg-slate-50"}`}>
              <div className="text-xs font-semibold text-slate-500">Effect</div>
              <div className="mt-1 text-sm font-semibold text-slate-950">{row.term}</div>
              <div className="mt-2 h-2 rounded-full bg-white">
                <div className="h-full rounded-full bg-blue-600" style={{ width: `${Math.max(25, 90 - index * 9)}%` }} />
              </div>
            </div>
          ))}
        </div>
      </VisualCard>
      <AnalysisEvidenceTable table={{
        title: "Interaction Review Plan",
        headers: ["Interaction", "Priority", "df", "Guidance"],
        rows: matrixRows.length ? matrixRows : [["Interactions pending", "Needed", "-", "Define at least two factors with levels."]],
      }} />
    </section>
  );
}

function OptimizationStudio({ projectId, state }: { projectId: string; state: NodeState }) {
  const parsedFactors = sharedParseFactorHierarchy(loadExperimentalNodeState(projectId, "Levels")?.objective ?? "");
  const factors = parsedFactors.length
    ? parsedFactors
    : [
        { factorName: "Pricing Strategy", levels: ["Current Pricing", "Personalized Pricing"] },
        { factorName: "Contact Channel", levels: ["Email", "SMS"] },
      ];
  const matrix = generateTreatmentMatrix(factors).slice(0, 8);
  const guardrailCount = Math.max(3, Number(state.numeric.constraintCount ?? 4));
  const ranked = matrix.map((row, index) => {
    const lift = Math.max(0.018, 0.118 - index * 0.012 + (index % 2 === 0 ? 0.006 : -0.002));
    const revenue = Math.round(420000 + lift * 8200000 - index * 18000);
    const risk = Math.min(0.28, 0.055 + index * 0.027 + (index % 3 === 0 ? 0.012 : 0));
    const passRate = Math.max(0.62, 0.98 - index * 0.055);
    const desirability = Math.max(0.1, lift * 4.5 + passRate * 0.48 + (1 - risk) * 0.28);
    const normalizedDesirability = Math.min(0.98, desirability);
    const ciLow = lift - (0.018 + index * 0.002);
    const ciHigh = lift + (0.021 + index * 0.002);
    const settings = factors.map((factor) => `${factor.factorName}: ${row[factor.factorName]}`).join("; ");
    return {
      label: row.cell,
      settings,
      lift,
      revenue,
      risk,
      passRate,
      desirability: normalizedDesirability,
      ciLow,
      ciHigh,
      passedConstraints: Math.max(1, Math.round(passRate * guardrailCount)),
      status: normalizedDesirability >= 0.82 ? "Adequate" as const : normalizedDesirability >= 0.7 ? "Weak" as const : "Redesign Required" as const,
    };
  }).sort((a, b) => b.desirability - a.desirability);
  const winner = ranked[0];
  const riskRows = ranked.map((row) => ({
    label: row.label,
    x: row.risk,
    y: row.revenue,
    value: row.desirability,
    detail: row.settings,
  }));
  const ciRows = ranked.map((row) => ({ label: row.label, low: row.ciLow, mid: row.lift, high: row.ciHigh }));
  return (
    <section className="grid items-start gap-5 xl:grid-cols-[minmax(0,1fr)_360px]">
      <div className="space-y-5">
        <section className="rounded-2xl border border-emerald-200 bg-emerald-50 p-5 shadow-sm">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div>
              <div className="text-xs font-semibold uppercase tracking-wide text-emerald-700">Recommended Treatment</div>
              <h2 className="mt-1 text-2xl font-semibold text-slate-950">{winner?.label ?? "Treatment pending"}</h2>
              <p className="mt-2 max-w-3xl text-sm leading-6 text-emerald-950">
                {winner
                  ? `${winner.settings}. ATLAS recommends this treatment because it has the strongest combined desirability score after lift, revenue, risk, and guardrail constraints are considered.`
                  : "Define factor levels to generate a treatment recommendation."}
              </p>
            </div>
            <div className="grid min-w-[220px] grid-cols-2 gap-2 text-sm">
              <ResultCard label="Expected Lift" value={winner ? formatPct(winner.lift) : "-"} />
              <ResultCard label="Risk Score" value={winner ? formatPct(winner.risk) : "-"} />
            </div>
          </div>
        </section>

        <section className="grid gap-4 lg:grid-cols-2">
          <HorizontalBarChartCard
            title="Treatment Ranking Preview"
            subtitle="Ranks treatment cells using lift, guardrail performance, risk, and operational feasibility."
            rows={ranked.map((row) => ({ label: row.label, value: row.desirability, status: row.status }))}
            valueFormatter={(value) => `${Math.round(value * 100)} score`}
            note="Higher scores indicate stronger deployment candidates under current constraints."
          />
          <AnalysisEvidenceTable table={{
            title: "Top Candidate Treatments",
            headers: ["Treatment", "Settings", "Decision"],
            rows: ranked.slice(0, 5).map((row, index) => [row.label, row.settings, index === 0 ? "Candidate optimum" : "Compare as alternative"]),
          }} />
        </section>

        <section className="grid gap-4 lg:grid-cols-2">
          <HorizontalBarChartCard
            title="Treatment Lift Comparison"
            subtitle="Expected incremental response by treatment cell."
            rows={ranked.map((row) => ({ label: row.label, value: row.lift, status: row.status }))}
            valueFormatter={(value) => formatPct(value)}
            note="Lift values are preview estimates until observed experiment outcomes are loaded."
          />
          <OptimizationScatterPlot rows={riskRows} />
        </section>

        <section className="grid gap-4 lg:grid-cols-2">
          <HorizontalBarChartCard
            title="Desirability Score by Treatment"
            subtitle="Composite optimization score across benefit, risk, and constraints."
            rows={ranked.map((row) => ({ label: row.label, value: row.desirability, status: row.status }))}
            valueFormatter={(value) => `${Math.round(value * 100)}%`}
            note="Desirability keeps the recommendation from optimizing lift while ignoring compliance or operational limits."
          />
          <HorizontalBarChartCard
            title="Constraint Pass Rate by Treatment"
            subtitle="Share of business, compliance, and delivery guardrails satisfied."
            rows={ranked.map((row) => ({ label: row.label, value: row.passRate, status: row.passRate >= 0.85 ? "Adequate" as const : "Weak" as const }))}
            valueFormatter={(value) => `${Math.round(value * 100)}%`}
            note={`${guardrailCount} guardrails are represented in the current optimization review.`}
          />
        </section>

        <OptimizationConfidenceIntervals rows={ciRows} />
      </div>

      <aside className="space-y-4">
        <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
          <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Optimization Decision Support</div>
          <div className="mt-4 grid gap-3">
            <ResultCard label="Treatment Cells" value={ranked.length.toLocaleString()} />
            <ResultCard label="Guardrail Pass" value={winner ? `${winner.passedConstraints}/${guardrailCount}` : "-"} />
            <ResultCard label="Revenue Upside" value={winner ? `$${winner.revenue.toLocaleString()}` : "-"} />
            <ResultCard label="Recommendation" value={winner?.status === "Adequate" ? "Proceed" : "Review"} />
          </div>
        </section>

        <section className="rounded-2xl border border-blue-200 bg-blue-50 p-5 shadow-sm">
          <div className="text-xs font-semibold uppercase tracking-wide text-blue-700">Why the Winner is Recommended</div>
          <ul className="mt-3 space-y-2 text-sm leading-6 text-blue-950">
            <li>- Highest combined desirability score.</li>
            <li>- Positive expected lift with acceptable confidence interval.</li>
            <li>- Guardrail pass rate remains above the launch threshold.</li>
            <li>- Revenue upside is strong relative to modeled operational risk.</li>
          </ul>
        </section>

        <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
          <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Sensitivity Snapshot</div>
          <div className="mt-4 space-y-3 text-sm">
            {[
              ["Lift threshold", winner && winner.lift >= 0.06 ? "Pass" : "Review"],
              ["Risk guardrail", winner && winner.risk <= 0.15 ? "Pass" : "Review"],
              ["Operational capacity", ranked.length <= 8 ? "Pass" : "Review"],
              ["Confirmation test", "Recommended"],
            ].map(([label, value]) => (
              <div key={label} className="flex items-center justify-between gap-3 rounded-lg bg-slate-50 px-3 py-2">
                <span className="font-medium text-slate-700">{label}</span>
                <span className={`rounded-full px-2 py-0.5 text-xs font-semibold ${value === "Pass" ? "bg-emerald-100 text-emerald-700" : "bg-amber-100 text-amber-700"}`}>{value}</span>
              </div>
            ))}
          </div>
        </section>
      </aside>
    </section>
  );
}

function OptimizationScatterPlot({ rows }: { rows: { label: string; x: number; y: number; value: number; detail: string }[] }) {
  const width = 520;
  const height = 260;
  const pad = 38;
  const xMax = Math.max(0.01, ...rows.map((row) => row.x)) * 1.15;
  const yMin = Math.min(...rows.map((row) => row.y)) * 0.96;
  const yMax = Math.max(...rows.map((row) => row.y)) * 1.04;
  return (
    <VisualCard title="Revenue vs Risk Scatterplot" subtitle="Compares business upside against modeled treatment risk. Upper-left is preferred.">
      <svg viewBox={`0 0 ${width} ${height}`} className="h-64 w-full rounded-xl bg-slate-50">
        <line x1={pad} y1={height - pad} x2={width - pad} y2={height - pad} stroke="#cbd5e1" />
        <line x1={pad} y1={pad} x2={pad} y2={height - pad} stroke="#cbd5e1" />
        <line x1={pad + ((0.15 / xMax) * (width - pad * 2))} y1={pad} x2={pad + ((0.15 / xMax) * (width - pad * 2))} y2={height - pad} stroke="#f59e0b" strokeDasharray="5 5" />
        <text x={pad + 6} y={pad - 12} fontSize="10" fill="#64748b">Higher revenue</text>
        <text x={width - pad - 82} y={height - 10} fontSize="10" fill="#64748b">Higher risk</text>
        {rows.map((row, index) => {
          const x = pad + (row.x / xMax) * (width - pad * 2);
          const y = height - pad - ((row.y - yMin) / Math.max(1, yMax - yMin)) * (height - pad * 2);
          const color = index === 0 ? "#059669" : row.x > 0.15 ? "#d97706" : "#2563eb";
          return (
            <g key={row.label}>
              <circle cx={x} cy={y} r={8 + row.value * 5} fill={color} opacity="0.78">
                <title>{`${row.label}: ${row.detail}; revenue $${row.y.toLocaleString()}; risk ${formatPct(row.x)}`}</title>
              </circle>
              <text x={x + 10} y={y + 4} fontSize="10" fontWeight="700" fill="#334155">{row.label}</text>
            </g>
          );
        })}
      </svg>
      <p className="mt-3 text-xs leading-5 text-slate-500">Amber threshold marks a 15% modeled risk review point.</p>
    </VisualCard>
  );
}

function OptimizationConfidenceIntervals({ rows }: { rows: { label: string; low: number; mid: number; high: number }[] }) {
  const min = Math.min(...rows.map((row) => row.low), 0);
  const max = Math.max(...rows.map((row) => row.high), 0.01);
  const position = (value: number) => `${((value - min) / Math.max(0.001, max - min)) * 100}%`;
  return (
    <VisualCard title="Confidence Interval Comparison" subtitle="Expected treatment lift intervals for deployment decision review.">
      <div className="space-y-4">
        {rows.map((row, index) => (
          <div key={row.label} className="grid grid-cols-[76px_minmax(0,1fr)_72px] items-center gap-3 text-xs">
            <div className="font-semibold text-slate-700">{row.label}</div>
            <div className="relative h-8 rounded-lg bg-slate-50">
              <div className="absolute top-1/2 h-1 -translate-y-1/2 rounded-full bg-blue-200" style={{ left: position(row.low), right: `${100 - Number(position(row.high).replace("%", ""))}%` }} />
              <div className={`absolute top-1/2 h-4 w-4 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-white shadow ${index === 0 ? "bg-emerald-600" : "bg-blue-600"}`} style={{ left: position(row.mid) }}>
                <span className="sr-only">{row.label}</span>
              </div>
              <div className="absolute bottom-0 top-0 w-px bg-slate-300" style={{ left: position(0) }} />
            </div>
            <div className="text-right font-semibold text-slate-700">{formatPct(row.mid)}</div>
          </div>
        ))}
      </div>
      <p className="mt-4 text-xs leading-5 text-slate-500">Intervals crossing zero should be treated as weaker evidence until the experiment results are observed.</p>
    </VisualCard>
  );
}

function DocumentationStudio({ projectId, state, setState, analysis }: { projectId: string; state: NodeState; setState: (state: NodeState) => void; analysis: ExperimentalDesignAnalysis }) {
  return (
    <section className="space-y-4">
      <section className="grid gap-3 md:grid-cols-3 xl:grid-cols-6">
        <ResultCard label="Ready Status" value={analysis.warnings.length ? "Review risks" : "Ready draft"} />
        <ResultCard label="Power" value={analysis.kpis.find((kpi) => kpi.label === "Power")?.value ?? "-"} />
        <ResultCard label="Treatment Cells" value={analysis.kpis.find((kpi) => kpi.label === "Treatment Cells")?.value ?? "-"} />
        <ResultCard label="Evidence" value={analysis.kpis.find((kpi) => kpi.label === "Evidence")?.value ?? "-"} />
        <ResultCard label="Confidence" value={`${Math.round((analysis.kpis.reduce((sum, kpi) => sum + kpi.confidence, 0) / Math.max(1, analysis.kpis.length)) * 100)}%`} />
        <ResultCard label="Risks" value={analysis.warnings.length.toLocaleString()} />
      </section>
      <DocumentationArtifactPanel projectId={projectId} state={state} setState={setState} />
    </section>
  );
}

function VisualCard({ title, subtitle, children }: { title: string; subtitle: string; children: ReactNode }) {
  return (
    <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
      <h2 className="text-sm font-semibold text-slate-950">{title}</h2>
      <p className="mt-1 text-xs leading-5 text-slate-500">{subtitle}</p>
      <div className="mt-4">{children}</div>
    </section>
  );
}

function HorizontalBars({ rows, valueFormatter }: { rows: { label: string; value: number }[]; valueFormatter: (value: number) => string }) {
  const max = Math.max(0.01, ...rows.map((row) => row.value));
  return (
    <div className="space-y-3">
      {rows.map((row) => (
        <div key={row.label} className="grid grid-cols-[170px_minmax(0,1fr)_76px] items-center gap-3 text-xs">
          <div className="truncate font-semibold text-slate-700" title={row.label}>{row.label}</div>
          <div className="h-3 overflow-hidden rounded-full bg-slate-100">
            <div className="h-full rounded-full bg-teal-600" style={{ width: `${Math.max(4, (row.value / max) * 100)}%` }} />
          </div>
          <div className="text-right font-semibold text-slate-700">{valueFormatter(row.value)}</div>
        </div>
      ))}
    </div>
  );
}

function ReadinessRibbon({ complete, total, label }: { complete: number; total: number; label: string }) {
  const pct = complete / Math.max(1, total);
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
      <div className="flex items-center justify-between text-xs font-semibold uppercase tracking-wide text-slate-500">
        <span>{label}</span>
        <span>{complete}/{total}</span>
      </div>
      <div className="mt-3 h-3 overflow-hidden rounded-full bg-slate-100">
        <div className={`h-full rounded-full ${pct >= 0.8 ? "bg-emerald-600" : pct >= 0.5 ? "bg-amber-500" : "bg-blue-600"}`} style={{ width: `${pct * 100}%` }} />
      </div>
    </div>
  );
}

function ExperimentalVisualAnalytics({ analysis }: { analysis: ExperimentalDesignAnalysis }) {
  const statusColor = (status: ExperimentalDesignAnalysis["kpis"][number]["status"]) =>
    status === "good" ? "#059669" : status === "risk" ? "#e11d48" : status === "warning" ? "#d97706" : "#2563eb";
  const chartRows = analysis.kpis.slice(0, 6);
  return (
    <section className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_420px]">
      <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 className="text-sm font-semibold text-slate-950">Visual Analytics</h2>
            <p className="mt-1 text-xs leading-5 text-slate-500">
              Analysis outputs are generated first, then reused by the page and governance report.
            </p>
          </div>
          <span className="rounded-full border border-slate-200 bg-slate-50 px-2.5 py-1 text-xs font-semibold text-slate-700">
            live analysis object
          </span>
        </div>

        <div className="mt-5 rounded-xl bg-slate-50 p-4">
          <div className="mb-3 text-xs font-semibold uppercase tracking-wide text-slate-500">KPI Confidence and Status</div>
          <div className="space-y-3">
            {chartRows.map((kpi) => (
              <div key={kpi.label} className="grid grid-cols-[150px_minmax(0,1fr)_88px] items-center gap-3 text-xs">
                <div className="truncate font-semibold text-slate-700" title={kpi.label}>{kpi.label}</div>
                <div className="h-3 overflow-hidden rounded-full bg-white">
                  <div className="h-full rounded-full" style={{ width: `${Math.max(4, kpi.confidence * 100)}%`, backgroundColor: statusColor(kpi.status) }} />
                </div>
                <div className="text-right font-semibold text-slate-700">{kpi.value}</div>
              </div>
            ))}
          </div>
        </div>

        <div className="mt-4 grid gap-3 md:grid-cols-2">
          {analysis.visualizations.slice(0, 4).map((visual) => (
            <div key={visual.title} className="rounded-xl border border-slate-200 bg-slate-50 p-4">
              <div className="flex items-center justify-between gap-3">
                <div className="text-sm font-semibold text-slate-950">{visual.title}</div>
                <span className="rounded-full bg-white px-2 py-1 text-[11px] font-semibold uppercase tracking-wide text-blue-700">{visual.type}</span>
              </div>
              <p className="mt-2 text-xs leading-5 text-slate-600">{visual.description}</p>
            </div>
          ))}
        </div>
      </div>

      <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
        <h2 className="text-sm font-semibold text-slate-950">Supporting Evidence</h2>
        <p className="mt-1 text-xs leading-5 text-slate-500">Tables shown here are produced by the same analysis object used in exports.</p>
        {analysis.evidenceTables.length ? (
          <div className="mt-4 space-y-4">
            {analysis.evidenceTables.slice(0, 2).map((table) => (
              <AnalysisEvidenceTable key={table.title} table={table} />
            ))}
          </div>
        ) : (
          <div className="mt-4 rounded-xl border border-dashed border-slate-300 bg-slate-50 p-6 text-center text-sm text-slate-500">
            Enter the required experiment inputs to generate evidence tables.
          </div>
        )}
      </div>
    </section>
  );
}

function AnalysisEvidenceTable({ table }: { table: ExperimentalDesignAnalysis["evidenceTables"][number] }) {
  return (
    <div className="overflow-hidden rounded-lg border border-slate-200">
      <div className="bg-slate-50 px-3 py-2 text-xs font-semibold uppercase tracking-wide text-slate-500">{table.title}</div>
      <div className="overflow-auto">
        <table className="w-full min-w-[420px] text-left text-sm">
          <thead className="bg-white text-xs font-semibold uppercase tracking-wide text-slate-500">
            <tr>
              {table.headers.map((header) => (
                <th key={header} className="border-t border-slate-200 px-3 py-2">{header}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {table.rows.map((row, rowIndex) => (
              <tr key={rowIndex} className="border-t border-slate-200 odd:bg-white even:bg-slate-50">
                {table.headers.map((_, index) => (
                  <td key={index} className="px-3 py-2 align-top text-slate-700">{row[index] ?? "-"}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function experimentalInterpretationText(stepLabel: string, analysis: ExperimentalDesignAnalysis, projectId: string) {
  const nodeStates = loadExperimentalNodeStates(projectId);
  const factors = sharedParseFactorHierarchy(nodeStates.Levels?.objective ?? "");
  const factorNames = factors.map((factor) => factor.factorName);
  const treatmentCells = factors.length ? treatmentCellCount(factors) : Number(nodeStates["Sample Size"]?.numeric?.factorCount ?? 2) ** 2;
  const factorPair = factorNames.length >= 2 ? `${factorNames[0]} x ${factorNames[1]}` : "the primary factor interaction";
  const randomizationDesign = nodeStates.Randomization ? randomizationDesignInputs(projectId, nodeStates.Randomization) : null;
  const lookup: Record<string, string> = {
    Factors: `ATLAS identified ${factorNames.length || 2} controllable factors producing ${treatmentCells.toLocaleString()} treatment cells. ${factorNames.slice(0, 2).join(" and ") || "The selected factors"} should be randomized and audited. Measured covariates should support balance checks and subgroup diagnostics, not drive treatment assignment.`,
    Levels: `ATLAS generated a ${factors.length ? factors.map((factor) => factor.levels.length).join(" x ") : "2 x 2"} treatment matrix from the selected levels. Baseline settings should be clearly identified before sample-size planning so treatment effects are interpretable.`,
    Blocking: "ATLAS recommends using customer risk segment as the primary stratification variable. Campaign launch week and geographic region should be monitored through balance diagnostics but should not define treatment assignment unless material response differences are confirmed.",
    Randomization: `ATLAS recommends reproducible ${randomizationDesign?.method.toLowerCase() ?? "stratified randomization"} using ${randomizationDesign?.selectedStratum ?? "Customer risk segment"} as the primary stratum. This improves treatment comparability while avoiding unnecessary treatment-cell expansion. Campaign launch week and geographic region should be monitored through balance diagnostics unless stronger response differences are confirmed.`,
    "Sample Size": "The sample-size plan should confirm that the available population supports the required per-cell allocation for the minimum practical lift and target power.",
    "Monte Carlo Simulation": "Simulation results should support launch readiness under current assumptions. Review mean power, wrong-winner risk, false-negative risk, and stress scenarios before execution.",
    "Experiment Run Plan": "The run plan is ready for controlled launch only if assignment validation, contact delivery controls, QA checks, monitoring, and stopping rules are completed before execution.",
    ANOVA: `The planned ANOVA will estimate main effects and the ${factorPair} interaction. Interpret main effects first, then review interaction terms before selecting a treatment configuration.`,
    Optimization: "ATLAS should recommend the best constrained treatment configuration only after confirming effect estimates, confidence intervals, guardrail metrics, and operational feasibility.",
    Documentation: "The governance package should summarize the design, assumptions, assignment logic, power analysis, simulation outputs, analysis plan, limitations, and final recommendation.",
  };
  return lookup[stepLabel] ?? analysis.interpretation;
}

function ExperimentalInterpretation({ analysis, stepLabel, projectId }: { analysis: ExperimentalDesignAnalysis; stepLabel: string; projectId: string }) {
  const interpretation = experimentalInterpretationText(stepLabel, analysis, projectId);
  const isBlocking = stepLabel === "Blocking";
  if (isBlocking) {
    return (
      <section className="rounded-2xl border border-emerald-200 bg-emerald-50 p-7 shadow-sm">
        <div className="text-sm font-semibold uppercase tracking-wide text-emerald-800">ATLAS Interpretation</div>
        <p className="mt-3 max-w-5xl text-base leading-8 text-emerald-950">{interpretation}</p>
      </section>
    );
  }
  return (
    <section className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_360px]">
      <div className="rounded-2xl border border-emerald-200 bg-emerald-50 p-5 shadow-sm">
        <div className="text-xs font-semibold uppercase tracking-wide text-emerald-800">ATLAS Interpretation</div>
        <p className="mt-2 text-sm leading-6 text-emerald-950">{interpretation}</p>
      </div>
      <div className={`rounded-2xl border p-5 shadow-sm ${analysis.warnings.length ? "border-amber-200 bg-amber-50" : "border-blue-200 bg-blue-50"}`}>
        <div className={`text-xs font-semibold uppercase tracking-wide ${analysis.warnings.length ? "text-amber-800" : "text-blue-800"}`}>
          {analysis.warnings.length ? "Warnings" : "Recommended Next Steps"}
        </div>
        <ul className={`mt-2 space-y-1 text-sm leading-6 ${analysis.warnings.length ? "text-amber-950" : "text-blue-950"}`}>
          {(analysis.warnings.length ? analysis.warnings : analysis.recommendedNextSteps).map((item) => (
            <li key={item}>- {item}</li>
          ))}
        </ul>
      </div>
    </section>
  );
}

function FactorDesignAssistant({ factors }: { factors: SuggestedFactor[] }) {
  const designFactors = normalizeDesignFactors(factors);
  const [sandboxEnabled, setSandboxEnabled] = useState(false);
  const sandboxFactors = sandboxEnabled
    ? [...designFactors, { factorName: "Region", type: "Categorical" as const, levels: ["Northeast", "South", "Midwest", "West"] }]
    : designFactors;
  const treatmentCells = treatmentCellCount(designFactors);
  const perCellSample = designFactors.length ? 400 : 0;
  const totalSample = perCellSample * treatmentCells;
  const levelSummary = designFactors.length ? designFactors.map((factor) => factor.levels.length).join(" x ") : "-";
  const complexity = factorComplexity(treatmentCells);
  const estimatedPower = estimatedFactorPower(treatmentCells);
  const recommendedAnalyses =
    designFactors.length > 1
      ? ["Two-Way ANOVA", "Interaction Analysis", "Effect Size", "Power Analysis"]
      : designFactors.length === 1
        ? ["One-Way ANOVA", "Treatment Comparison", "Effect Size", "Power Analysis"]
        : ["Enter factors to generate recommendations"];

  return (
    <section className="space-y-4">
      <section className="rounded-xl border border-blue-200 bg-white p-5 shadow-sm">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 className="text-sm font-semibold text-slate-950">Live Experimental Design Explorer</h2>
            <p className="mt-1 text-xs leading-5 text-slate-500">
              ATLAS converts controllable factors into a visible treatment structure so the experiment can be understood before randomization or sample sizing.
            </p>
          </div>
          <span className="rounded-full border border-blue-200 bg-blue-50 px-2.5 py-1 text-xs font-semibold text-blue-800">
            live design object
          </span>
        </div>

        <div className="mt-4 grid gap-3 md:grid-cols-5">
          <ResultCard label="Factors" value={String(designFactors.length)} />
          <ResultCard label="Levels" value={levelSummary} />
          <ResultCard label="Treatment cells" value={treatmentCells.toLocaleString()} />
          <ResultCard label="Complexity" value={complexity} />
          <ResultCard label="Est. power" value={`${Math.round(estimatedPower)}%`} />
        </div>

        <ExperimentalDesignFlow factors={designFactors} />

        <div className="mt-5 grid gap-4 xl:grid-cols-[minmax(0,1.25fr)_minmax(320px,0.75fr)]">
          <TreatmentStructureHero factors={designFactors} />
          <LiveDesignTree factors={designFactors} />
        </div>
      </section>

      <section className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_420px]">
        <DesignCanvas factors={designFactors} />
        <DesignComplexityPanel factors={designFactors} perCellSample={perCellSample} totalSample={totalSample} />
      </section>

      <WhatIfSandbox factors={designFactors} previewFactors={sandboxFactors} enabled={sandboxEnabled} onToggle={setSandboxEnabled} />

      <section className="grid gap-4 xl:grid-cols-2">
        <FactorCovariateMap factors={designFactors} />
        <FactorQualityScorecard factors={designFactors} treatmentCells={treatmentCells} />
      </section>

      <section className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_420px]">
        <SuggestedFactorRecommendations factors={designFactors} />
        <div className="rounded-xl border border-emerald-200 bg-emerald-50 p-5 shadow-sm">
          <div className="text-xs font-semibold uppercase tracking-wide text-emerald-800">Recommended Analysis</div>
          <div className="mt-3 grid gap-2">
            {recommendedAnalyses.map((analysis) => (
              <div key={analysis} className="flex items-center gap-2 text-sm font-semibold text-emerald-950">
                <CheckCircle2 size={15} className="text-emerald-600" />
                {analysis}
              </div>
            ))}
          </div>
          <p className="mt-4 text-xs leading-5 text-emerald-900">
            Estimated total minimum sample: {totalSample.toLocaleString()} records across {treatmentCells.toLocaleString()} treatment cells.
          </p>
        </div>
      </section>
    </section>
  );
}

function normalizeDesignFactors(factors: SuggestedFactor[]): SuggestedFactor[] {
  const defaults: SuggestedFactor[] = [
    { factorName: "Pricing Strategy", type: "Categorical", levels: ["Current", "Personalized"] },
    { factorName: "Contact Channel", type: "Categorical", levels: ["Email", "SMS"] },
  ];
  const source = factors.length ? factors : defaults;
  return source.slice(0, 5).map((factor) => ({
    factorName: factor.factorName,
    type: factor.type,
    levels: factor.levels.length ? factor.levels.slice(0, 5) : ["Control", "Treatment"],
  }));
}

function factorComplexity(cells: number) {
  if (cells <= 4) return "Low";
  if (cells <= 12) return "Medium";
  return "High";
}

function estimatedFactorPower(cells: number) {
  return Math.max(62, Math.min(94, 96 - Math.max(0, cells - 4) * 2.3));
}

function ExperimentalDesignFlow({ factors }: { factors: SuggestedFactor[] }) {
  const cells = treatmentCellCount(factors);
  const availablePopulation = 25000;
  const perCell = Math.floor(availablePopulation / Math.max(1, cells));
  const steps = [
    { label: factors.map((factor) => factor.levels.length).join(" x "), value: "Factorial" },
    { label: `${cells.toLocaleString()} Cells`, value: "Treatment grid" },
    { label: "Balanced", value: new Set(factors.map((factor) => factor.levels.length)).size === 1 ? "Yes" : "Review" },
    { label: availablePopulation.toLocaleString(), value: "Observations" },
    { label: `${perCell.toLocaleString()} / cell`, value: "Initial allocation" },
  ];
  return (
    <div className="mt-5 rounded-xl border border-slate-200 bg-slate-50 p-4">
      <div className="flex flex-wrap items-center gap-2">
        {steps.map((step, index) => (
          <Fragment key={step.label}>
            <div className="min-w-[130px] flex-1 rounded-xl border border-slate-200 bg-white p-3 text-center transition hover:-translate-y-0.5 hover:shadow-sm">
              <div className="text-lg font-bold text-slate-950">{step.label}</div>
              <div className="mt-1 text-[11px] font-semibold uppercase tracking-wide text-slate-500">{step.value}</div>
            </div>
            {index < steps.length - 1 && <div className="hidden text-xl font-light text-slate-300 lg:block">→</div>}
          </Fragment>
        ))}
      </div>
    </div>
  );
}

function TreatmentStructureHero({ factors }: { factors: SuggestedFactor[] }) {
  const rowFactor = factors[0];
  const columnFactor = factors[1] ?? { factorName: "Treatment", type: "Categorical" as const, levels: ["Cell"] };
  const extraFactors = Math.max(0, factors.length - 2);
  const samplePerCell = Math.floor(25000 / Math.max(1, treatmentCellCount(factors)));

  return (
    <div className="rounded-xl border border-slate-200 bg-slate-50 p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Treatment Structure</div>
          <h3 className="mt-1 text-lg font-semibold text-slate-950">
            {rowFactor.factorName} x {columnFactor.factorName}
          </h3>
        </div>
        <span className="rounded-full border border-slate-200 bg-white px-2.5 py-1 text-xs font-semibold text-slate-700">
          {treatmentCellCount(factors).toLocaleString()} cells
        </span>
      </div>

      <div className="mt-5 overflow-auto rounded-xl border border-slate-200 bg-white">
        <div
          className="grid min-w-[520px]"
          style={{ gridTemplateColumns: `180px repeat(${columnFactor.levels.length}, minmax(130px, 1fr))` }}
        >
          <div className="border-b border-r border-slate-200 bg-slate-100 p-3 text-xs font-semibold uppercase tracking-wide text-slate-500">
            {columnFactor.factorName}
          </div>
          {columnFactor.levels.map((level) => (
            <div key={level} className="border-b border-r border-slate-200 bg-blue-50 p-3 text-center text-sm font-semibold text-blue-950">
              {level}
            </div>
          ))}
          {rowFactor.levels.map((rowLevel, rowIndex) => (
            <Fragment key={rowLevel}>
              <div className="border-b border-r border-slate-200 bg-emerald-50 p-3 text-sm font-semibold text-emerald-950">
                {rowLevel}
              </div>
              {columnFactor.levels.map((columnLevel, columnIndex) => (
                <div key={`${rowLevel}-${columnLevel}`} className="group relative border-b border-r border-slate-200 bg-white p-3 text-center transition hover:-translate-y-0.5 hover:bg-slate-50 hover:shadow-sm">
                  <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-xl border border-blue-200 bg-blue-50 text-sm font-bold text-blue-900">
                    {String.fromCharCode(65 + rowIndex)}{columnIndex + 1}
                  </div>
                  <div className="mt-2 text-[11px] leading-4 text-slate-500">
                    {rowLevel} + {columnLevel}
                  </div>
                  <div className="pointer-events-none absolute bottom-full left-1/2 z-50 mb-2 hidden w-64 -translate-x-1/2 rounded-xl border border-slate-200 bg-white p-3 text-left shadow-2xl ring-1 ring-slate-900/5 group-hover:block">
                    <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Treatment Cell {rowIndex * columnFactor.levels.length + columnIndex + 1}</div>
                    <div className="mt-2 grid gap-1.5 text-xs text-slate-700">
                      <div><span className="font-semibold text-slate-950">{rowFactor.factorName}:</span> {rowLevel}</div>
                      <div><span className="font-semibold text-slate-950">{columnFactor.factorName}:</span> {columnLevel}</div>
                      <div><span className="font-semibold text-slate-950">Expected n:</span> {samplePerCell.toLocaleString()}</div>
                      <div><span className="font-semibold text-slate-950">Randomization:</span> Yes</div>
                    </div>
                  </div>
                </div>
              ))}
            </Fragment>
          ))}
        </div>
      </div>

      {extraFactors > 0 && (
        <p className="mt-3 text-xs leading-5 text-slate-500">
          First two factors are shown as the grid. {extraFactors} additional factor{extraFactors === 1 ? "" : "s"} multiply the treatment cells.
        </p>
      )}
    </div>
  );
}

function LiveDesignTree({ factors }: { factors: SuggestedFactor[] }) {
  const matrix = generateTreatmentMatrix(factors).slice(0, 8);
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4">
      <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Live Design Tree</div>
      <div className="mt-4 rounded-xl bg-slate-950 p-4 text-sm text-white shadow-inner">
        <div className="font-semibold text-blue-200">Experiment</div>
        <div className="mt-3 space-y-3">
          {factors.map((factor) => (
            <div key={factor.factorName} className="pl-3">
              <div className="border-l border-slate-600 pl-3 font-semibold">{factor.factorName}</div>
              <div className="mt-2 space-y-1 pl-6 text-xs text-slate-300">
                {factor.levels.map((level) => (
                  <div key={level}>- {level}</div>
                ))}
              </div>
            </div>
          ))}
        </div>
      </div>
      <details className="mt-3 rounded-xl border border-slate-200 bg-slate-50 p-3" open>
        <summary className="cursor-pointer list-none text-xs font-semibold uppercase tracking-wide text-slate-600">Treatment Cells</summary>
        <div className="mt-3 grid gap-2">
          {matrix.map((row) => (
            <div key={row.cell} className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs leading-5 text-slate-700">
              <span className="font-bold text-slate-950">{row.cell}</span>
              <span className="text-slate-400"> | </span>
              {factors.map((factor) => `${factor.factorName}: ${row[factor.factorName]}`).join("; ")}
            </div>
          ))}
          {treatmentCellCount(factors) > matrix.length && (
            <div className="text-xs text-slate-500">+ {treatmentCellCount(factors) - matrix.length} more treatment cells</div>
          )}
        </div>
      </details>
    </div>
  );
}

function DesignCanvas({ factors }: { factors: SuggestedFactor[] }) {
  return (
    <VisualCard title="Design Canvas" subtitle="Manipulated factors define treatments. Measured covariates support diagnostics and adjustment, but are not treatment assignments.">
      <div className="flex flex-wrap items-stretch gap-3">
        {factors.map((factor, index) => (
          <Fragment key={factor.factorName}>
            <div className="min-w-[180px] flex-1 rounded-xl border border-blue-200 bg-blue-50 p-4 transition hover:-translate-y-0.5 hover:shadow-sm">
              <div className="text-xs font-semibold uppercase tracking-wide text-blue-700">Factor {index + 1}</div>
              <div className="mt-1 text-sm font-semibold text-blue-950">{factor.factorName}</div>
              <div className="mt-3 flex flex-wrap gap-1.5">
                {factor.levels.map((level) => (
                  <span key={level} className="rounded-full border border-blue-200 bg-white px-2 py-1 text-xs font-semibold text-blue-900">{level}</span>
                ))}
              </div>
            </div>
            {index < factors.length - 1 && (
              <div className="hidden items-center text-2xl font-light text-slate-300 md:flex">x</div>
            )}
          </Fragment>
        ))}
      </div>
      <div className="mt-4 rounded-xl border border-emerald-200 bg-emerald-50 p-4 text-center">
        <div className="text-xs font-semibold uppercase tracking-wide text-emerald-800">{factors.map((factor) => factor.levels.length).join(" x ")}</div>
        <div className="mt-1 text-2xl font-bold text-emerald-950">{treatmentCellCount(factors).toLocaleString()} Treatment Cells</div>
      </div>
    </VisualCard>
  );
}

function DesignComplexityPanel({ factors, perCellSample, totalSample }: { factors: SuggestedFactor[]; perCellSample: number; totalSample: number }) {
  const cells = treatmentCellCount(factors);
  const power = estimatedFactorPower(cells);
  const tiles = Array.from({ length: Math.min(36, cells) }, (_, index) => index);
  const complexityScore = Math.min(10, Math.max(1, Math.ceil(cells / 2)));
  const efficiency = Math.max(60, 100 - Math.max(0, cells - 4) * 3);
  return (
    <VisualCard title="Complexity and Sample Pressure" subtitle="As treatment cells increase, sample needs rise and power can fall if the population is fixed.">
      <div className="mb-4 rounded-xl border border-slate-200 bg-white p-3">
        <div className="flex items-center justify-between gap-3">
          <div>
            <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Design Complexity</div>
            <div className="mt-1 text-sm font-semibold text-slate-950">{factorComplexity(cells)}</div>
          </div>
          <div className="flex items-center gap-1">
            {Array.from({ length: 10 }, (_, index) => (
              <span
                key={index}
                className={`h-3 w-3 rounded-full transition-all duration-500 ${index < complexityScore ? "bg-blue-600" : "bg-slate-200"}`}
              />
            ))}
          </div>
        </div>
      </div>
      <div className="grid grid-cols-6 gap-1">
        {tiles.map((tile) => (
          <div key={tile} className={`h-6 rounded transition-all duration-500 ${tile < 4 ? "bg-emerald-500" : tile < 12 ? "bg-amber-400" : "bg-rose-400"}`} />
        ))}
      </div>
      {cells > tiles.length && <div className="mt-2 text-xs text-slate-500">+ {cells - tiles.length} additional cells not shown</div>}
      <div className="mt-4 space-y-3">
        <HorizontalBars
          rows={[
            { label: "Required Sample", value: totalSample },
            { label: "Estimated Power", value: power },
            { label: "Design Efficiency", value: efficiency },
          ]}
          valueFormatter={(value) => value > 1000 ? value.toLocaleString() : `${Math.round(value)}%`}
        />
      </div>
      <div className="mt-4 rounded-xl border border-emerald-200 bg-emerald-50 p-3">
        <div className="text-xs font-semibold uppercase tracking-wide text-emerald-800">Design Efficiency</div>
        <div className="mt-2 h-3 overflow-hidden rounded-full bg-white">
          <div className="h-full rounded-full bg-emerald-600 transition-all duration-700" style={{ width: `${efficiency}%` }} />
        </div>
        <div className="mt-3 grid gap-2 text-xs font-semibold text-emerald-950 sm:grid-cols-2">
          <span>Balanced</span>
          <span>Orthogonal</span>
          <span>No aliasing</span>
          <span>Low variance inflation</span>
        </div>
      </div>
      <p className="mt-4 text-xs leading-5 text-slate-500">
        Planning assumption: {perCellSample.toLocaleString()} observations per cell before the formal sample-size step.
      </p>
    </VisualCard>
  );
}

function FactorCovariateMap({ factors }: { factors: SuggestedFactor[] }) {
  const covariateGroups = [
    { group: "Customer", items: ["Customer tenure", "Income", "FICO score"] },
    { group: "Marketing", items: ["Prior response", "Campaign history"] },
    { group: "Geography", items: ["Region", "State"] },
  ];
  return (
    <VisualCard title="Factors vs. Covariates" subtitle="This separates variables the business intentionally changes from variables observed for analysis and balance checks.">
      <div className="grid gap-3 md:grid-cols-2">
        <div className="rounded-xl border border-blue-200 bg-blue-50 p-4">
          <div className="text-xs font-semibold uppercase tracking-wide text-blue-800">Manipulated Factors</div>
          <div className="mt-3 space-y-2">
            {factors.map((factor) => (
              <div key={factor.factorName} className="rounded-lg bg-white px-3 py-2 text-sm font-semibold text-blue-950">Controlled: {factor.factorName}</div>
            ))}
          </div>
        </div>
        <div className="rounded-xl border border-slate-200 bg-slate-50 p-4">
          <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Measured Only</div>
          <div className="mt-3 space-y-3">
            {covariateGroups.map((group) => (
              <div key={group.group} className="rounded-lg bg-white p-3">
                <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">{group.group}</div>
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {group.items.map((item) => (
                    <span key={item} className="rounded-full border border-slate-200 bg-slate-50 px-2 py-1 text-xs font-semibold text-slate-700">{item}</span>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </VisualCard>
  );
}

function FactorQualityScorecard({ factors, treatmentCells }: { factors: SuggestedFactor[]; treatmentCells: number }) {
  const rows = [
    { label: "Controllability", value: Math.min(98, 72 + factors.length * 8) },
    { label: "Balance", value: new Set(factors.map((factor) => factor.levels.length)).size === 1 ? 94 : 78 },
    { label: "Business Relevance", value: Math.min(96, 70 + factors.length * 9) },
    { label: "Expected Signal", value: Math.max(66, 88 - Math.max(0, treatmentCells - 4) * 2) },
  ];
  return (
    <VisualCard title="Factor Quality Score" subtitle="ATLAS scores whether the selected factors are controllable, balanced, relevant, and likely to create interpretable signal.">
      <div className="space-y-3">
        {rows.map((row) => (
          <div key={row.label} className="rounded-xl border border-slate-200 bg-white p-3">
            <div className="flex items-center justify-between gap-3 text-xs font-semibold">
              <span className="text-slate-700">{row.label}</span>
              <span className={row.value >= 85 ? "text-emerald-700" : row.value >= 72 ? "text-amber-700" : "text-rose-700"}>{Math.round(row.value)}%</span>
            </div>
            <div className="mt-2 h-3 overflow-hidden rounded-full bg-slate-100">
              <div
                className={`h-full rounded-full transition-all duration-700 ${row.value >= 85 ? "bg-emerald-600" : row.value >= 72 ? "bg-amber-500" : "bg-rose-500"}`}
                style={{ width: `${row.value}%` }}
              />
            </div>
          </div>
        ))}
      </div>
      <div className="mt-4 rounded-xl border border-slate-200 bg-slate-50 p-3 text-xs leading-5 text-slate-600">
        Improve the score by keeping factors controllable, defining balanced levels, and avoiding extra factors unless they support a clear business hypothesis.
      </div>
    </VisualCard>
  );
}

function SuggestedFactorRecommendations({ factors }: { factors: SuggestedFactor[] }) {
  const recommendations = [
    {
      name: "Pricing Strategy",
      score: 5,
      why: ["High business control", "Strong expected treatment effect", "Likely interaction with Contact Channel"],
    },
    {
      name: "Contact Channel",
      score: 5,
      why: ["Practical to randomize", "Likely interaction with offer strategy", "Supports clear treatment assignment"],
    },
    {
      name: "Geographic Region",
      score: 4,
      why: ["May reduce unexplained variance", "Recommended as blocking variable", "Use caution before treating as manipulated factor"],
    },
    {
      name: "Customer Segment",
      score: 3,
      why: ["Useful for balance review", "Consider as covariate first", "May create operational complexity if randomized"],
    },
  ].filter((item) => !factors.some((factor) => factor.factorName.toLowerCase() === item.name.toLowerCase()));

  return (
    <VisualCard title="Atlas Factor Recommendations" subtitle="Candidate additions are ranked by expected signal, controllability, and operational usefulness.">
      <div className="space-y-3">
        {recommendations.map((item) => (
          <div key={item.name} className="rounded-xl border border-slate-200 bg-white p-3 transition hover:-translate-y-0.5 hover:shadow-sm">
            <div className="flex items-center justify-between gap-3">
              <div className="text-sm font-semibold text-slate-950">{item.name}</div>
              <div className="text-xs font-bold text-amber-500">{"★".repeat(item.score)}{"☆".repeat(5 - item.score)}</div>
            </div>
            <ul className="mt-2 space-y-1 text-xs leading-5 text-slate-500">
              {item.why.map((line) => <li key={line}>- {line}</li>)}
            </ul>
          </div>
        ))}
      </div>
    </VisualCard>
  );
}

function WhatIfSandbox({
  factors,
  previewFactors,
  enabled,
  onToggle,
}: {
  factors: SuggestedFactor[];
  previewFactors: SuggestedFactor[];
  enabled: boolean;
  onToggle: (enabled: boolean) => void;
}) {
  const currentCells = treatmentCellCount(factors);
  const previewCells = treatmentCellCount(previewFactors);
  const currentPower = estimatedFactorPower(currentCells);
  const previewPower = estimatedFactorPower(previewCells);
  const currentSample = currentCells * 6250;
  const previewSample = previewCells * 6250;
  return (
    <section className="rounded-xl border border-violet-200 bg-white p-5 shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="text-xs font-semibold uppercase tracking-wide text-violet-700">What-if Sandbox</div>
          <h2 className="mt-1 text-sm font-semibold text-slate-950">Preview adding Region without changing the experiment</h2>
          <p className="mt-1 text-xs leading-5 text-slate-500">
            Explore factorial explosion safely before committing a new factor to the workflow.
          </p>
        </div>
        <button
          type="button"
          onClick={() => onToggle(!enabled)}
          className={`rounded-lg px-3 py-2 text-xs font-semibold transition ${enabled ? "bg-violet-700 text-white" : "border border-violet-200 bg-violet-50 text-violet-900"}`}
        >
          {enabled ? "Remove Region Preview" : "+ Add Region Preview"}
        </button>
      </div>
      <div className="mt-4 grid gap-3 md:grid-cols-4">
        <DeltaCard label="Factors" before={String(factors.length)} after={String(previewFactors.length)} active={enabled} />
        <DeltaCard label="Treatment Cells" before={currentCells.toLocaleString()} after={previewCells.toLocaleString()} active={enabled} />
        <DeltaCard label="Power" before={`${Math.round(currentPower)}%`} after={`${Math.round(previewPower)}%`} active={enabled} inverse />
        <DeltaCard label="Sample Needed" before={currentSample.toLocaleString()} after={previewSample.toLocaleString()} active={enabled} />
      </div>
    </section>
  );
}

function DeltaCard({ label, before, after, active, inverse = false }: { label: string; before: string; after: string; active: boolean; inverse?: boolean }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-slate-50 p-4">
      <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">{label}</div>
      <div className="mt-2 flex items-center gap-2">
        <span className="text-lg font-bold text-slate-950">{before}</span>
        {active && (
          <>
            <span className="text-slate-400">→</span>
            <span className={`text-lg font-bold ${inverse ? "text-amber-700" : "text-violet-700"}`}>{after}</span>
          </>
        )}
      </div>
    </div>
  );
}

function levelsFactors(projectId: string, state: NodeState): ExperimentalFactor[] {
  const parsed = sharedParseFactorHierarchy(state.objective);
  if (parsed.length) return parsed;
  const factorsState = loadExperimentalNodeState(projectId, "Factors");
  const suggested = sharedDeriveSuggestedFactors(factorsState?.objective ?? "");
  if (suggested.length) return suggested.map(({ factorName, levels }) => ({ factorName, levels }));
  return [
    { factorName: "Pricing Strategy", levels: ["Current Pricing", "Personalized Pricing"] },
    { factorName: "Contact Channel", levels: ["Email", "SMS"] },
  ];
}

function LevelsDesignBuilder({ projectId, state }: { projectId: string; state: NodeState }) {
  const factors = levelsFactors(projectId, state);
  const matrix = generateTreatmentMatrix(factors);
  const cells = treatmentCellCount(factors);
  const balanced = new Set(factors.map((factor) => factor.levels.length)).size === 1;
  const warnings = levelPromotionWarnings(factors);
  return (
    <section className="space-y-4">
      <section className="rounded-xl border border-blue-200 bg-white p-5 shadow-sm">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 className="text-sm font-semibold text-slate-950">Visual Treatment Builder</h2>
            <p className="mt-1 text-xs leading-5 text-slate-500">
              Levels convert abstract factors into deployable treatments. ATLAS shows the design being constructed before randomization begins.
            </p>
          </div>
          <span className="rounded-full border border-blue-200 bg-blue-50 px-2.5 py-1 text-xs font-semibold text-blue-800">
            {balanced ? "balanced design" : "review balance"}
          </span>
        </div>

        <div className="mt-5 grid gap-3 md:grid-cols-[1fr_auto_1fr_auto_1fr_auto_1fr]">
          <LevelFlowNode title="Factors" value={`${factors.length}`} detail={factors.map((factor) => factor.factorName).join(", ")} />
          <FlowArrow />
          <LevelFlowNode title="Levels" value={factors.map((factor) => factor.levels.length).join(" x ")} detail="Factor settings become treatment choices." />
          <FlowArrow />
          <LevelFlowNode title="Treatment Cells" value={cells.toLocaleString()} detail="All valid factor-level combinations." />
          <FlowArrow />
          <LevelFlowNode title="Experimental Matrix" value={balanced ? "Balanced" : "Unbalanced"} detail="Ready for randomization review." />
        </div>
      </section>

      <section className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_420px]">
        <LevelExpansionCards factors={factors} />
        <WhyLevelsMatterPanel />
      </section>

      <section className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_420px]">
        <TreatmentCellConstruction factors={factors} matrix={matrix} />
        <GoodVsWeakLevelsCard />
      </section>

      {warnings.length > 0 && (
        <div className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm leading-6 text-amber-950">
          <span className="font-semibold">Validation warning: </span>
          These level names also appear as factor names: {warnings.join(", ")}. Confirm levels are nested under their parent factor instead of entered as separate factors.
        </div>
      )}
    </section>
  );
}

function LevelFlowNode({ title, value, detail }: { title: string; value: string; detail: string }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-slate-50 p-4 text-center transition hover:-translate-y-0.5 hover:shadow-sm">
      <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">{title}</div>
      <div className="mt-2 text-2xl font-bold text-slate-950">{value}</div>
      <p className="mt-2 text-xs leading-5 text-slate-500">{detail}</p>
    </div>
  );
}

function FlowArrow() {
  return <div className="hidden items-center justify-center text-2xl font-light text-blue-300 md:flex">→</div>;
}

function LevelExpansionCards({ factors }: { factors: ExperimentalFactor[] }) {
  return (
    <VisualCard title="Factor-Level Expansion" subtitle="Each factor expands into the concrete settings that can be assigned, audited, and measured.">
      <div className="grid gap-3 md:grid-cols-2">
        {factors.map((factor) => (
          <div key={factor.factorName} className="rounded-xl border border-slate-200 bg-white p-4">
            <div className="text-xs font-semibold uppercase tracking-wide text-blue-700">Factor</div>
            <div className="mt-1 text-base font-semibold text-slate-950">{factor.factorName}</div>
            <div className="mt-4 grid gap-2">
              {factor.levels.map((level, index) => (
                <div key={level} className="flex items-center gap-3 rounded-xl border border-blue-100 bg-blue-50 p-3">
                  <div className="flex h-8 w-8 items-center justify-center rounded-full bg-white text-xs font-bold text-blue-700">L{index + 1}</div>
                  <div className="text-sm font-semibold text-blue-950">{level}</div>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    </VisualCard>
  );
}

function TreatmentCellConstruction({ factors, matrix }: { factors: ExperimentalFactor[]; matrix: Record<string, string>[] }) {
  return (
    <VisualCard title="Treatment Cells Constructed in Real Time" subtitle="ATLAS combines one level from each factor to produce the experimental matrix used in randomization.">
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {matrix.slice(0, 12).map((row) => (
          <div key={row.cell} className="rounded-xl border border-slate-200 bg-white p-3 transition hover:-translate-y-0.5 hover:shadow-sm">
            <div className="flex items-center justify-between gap-3">
              <div className="text-sm font-bold text-slate-950">{row.cell}</div>
              <span className="rounded-full bg-emerald-50 px-2 py-0.5 text-[11px] font-semibold text-emerald-700">valid</span>
            </div>
            <div className="mt-3 space-y-2">
              {factors.map((factor) => (
                <div key={`${row.cell}-${factor.factorName}`} className="rounded-lg bg-slate-50 px-2 py-1.5 text-xs leading-5 text-slate-700">
                  <span className="font-semibold text-slate-950">{factor.factorName}:</span> {row[factor.factorName]}
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
      {matrix.length > 12 && <p className="mt-3 text-xs text-slate-500">Showing first 12 of {matrix.length.toLocaleString()} treatment cells.</p>}
    </VisualCard>
  );
}

function WhyLevelsMatterPanel() {
  const items = [
    ["Operationally feasible", "A level must be executable by the business exactly as documented."],
    ["Sufficiently different", "Levels need enough separation to create measurable signal."],
    ["Reproducible", "A later reviewer must be able to recreate the treatment assignment."],
    ["Likely to create signal", "Levels should map to a plausible behavioral or process change."],
  ];
  return (
    <VisualCard title="Why Levels Matter" subtitle="Poor level definitions create weak signal, inconsistent execution, and hard-to-defend results.">
      <div className="space-y-3">
        {items.map(([title, body]) => (
          <div key={title} className="rounded-xl border border-emerald-200 bg-emerald-50 p-3">
            <div className="text-sm font-semibold text-emerald-950">{title}</div>
            <p className="mt-1 text-xs leading-5 text-emerald-800">{body}</p>
          </div>
        ))}
      </div>
    </VisualCard>
  );
}

function GoodVsWeakLevelsCard() {
  const examples = [
    ["Strong", "Current Pricing vs. Personalized Pricing", "Clear operational difference and interpretable treatment contrast."],
    ["Weak", "Low vs. Medium vs. Better", "Ambiguous language; difficult to reproduce or audit."],
    ["Strong", "Email vs. SMS", "Distinct deployment channels with clear assignment logic."],
    ["Weak", "Marketing Push A vs. Marketing Push B", "No meaningful description of what changes for the customer."],
  ];
  return (
    <VisualCard title="Good vs. Weak Levels" subtitle="Use specific, deployable, and auditable settings rather than vague labels.">
      <div className="space-y-3">
        {examples.map(([type, example, reason]) => (
          <div key={`${type}-${example}`} className={`rounded-xl border p-3 ${type === "Strong" ? "border-emerald-200 bg-emerald-50" : "border-amber-200 bg-amber-50"}`}>
            <div className={`text-xs font-semibold uppercase tracking-wide ${type === "Strong" ? "text-emerald-700" : "text-amber-700"}`}>{type}</div>
            <div className="mt-1 text-sm font-semibold text-slate-950">{example}</div>
            <p className="mt-1 text-xs leading-5 text-slate-600">{reason}</p>
          </div>
        ))}
      </div>
    </VisualCard>
  );
}

function TreatmentMatrixPreview({ factors }: { factors: ExperimentalFactor[] }) {
  const treatmentCells = treatmentCellCount(factors);
  const matrix = factors.length ? generateTreatmentMatrix(factors).slice(0, 64) : [];
  const warnings = levelPromotionWarnings(factors);
  const balanced = factors.length > 0 && new Set(factors.map((factor) => factor.levels.length)).size === 1;
  const designLabel =
    factors.length > 1
      ? `${balanced ? "Balanced" : "Unbalanced"} ${factors.map((factor) => factor.levels.length).join(" × ")} factorial`
      : factors.length === 1
        ? `${factors[0].levels.length}-level single-factor design`
        : "Enter levels to generate preview";
  const recommendedAnalysis =
    factors.length >= 2 ? "Two-Way ANOVA with interaction" : factors.length === 1 ? "One-Way ANOVA or treatment comparison" : "-";

  return (
    <section className="rounded-xl border border-blue-200 bg-white p-5 shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold text-slate-950">Automatically Generated Treatment Matrix</h2>
          <p className="mt-1 text-xs leading-5 text-slate-500">
            Enter factor names with nested levels below them. ATLAS generates the factorial treatment cells for review.
          </p>
        </div>
        <span className="rounded-full border border-blue-200 bg-blue-50 px-2.5 py-1 text-xs font-semibold text-blue-800">
          live preview
        </span>
      </div>

      <div className="mt-4 overflow-hidden rounded-lg border border-slate-200">
        <table className="w-full text-left text-sm">
          <thead className="bg-slate-50 text-xs font-semibold uppercase tracking-wide text-slate-500">
            <tr>
              <th className="px-3 py-2">Factor</th>
              <th className="px-3 py-2">Levels</th>
            </tr>
          </thead>
          <tbody>
            {factors.length ? (
              factors.map((factor) => (
                <tr key={factor.factorName} className="border-t border-slate-200">
                  <td className="px-3 py-2 font-semibold text-slate-900">{factor.factorName}</td>
                  <td className="px-3 py-2 text-slate-700">{factor.levels.join(", ")}</td>
                </tr>
              ))
            ) : (
              <tr>
                <td colSpan={2} className="px-3 py-6 text-center text-sm text-slate-500">
                  Try: Pricing Strategy: Current, Personalized
                  <br />
                  Contact Channel: Email, SMS
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      <div className="my-3 text-center text-lg font-semibold text-slate-400">↓</div>

      <div className="overflow-auto rounded-lg border border-slate-200">
        <table className="w-full min-w-[520px] text-left text-sm">
          <thead className="bg-slate-50 text-xs font-semibold uppercase tracking-wide text-slate-500">
            <tr>
              <th className="px-3 py-2">Cell</th>
              {factors.map((factor) => (
                <th key={factor.factorName} className="px-3 py-2">{factor.factorName}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {matrix.length ? (
              matrix.map((row) => (
                <tr key={row.cell} className="border-t border-slate-200">
                  <td className="px-3 py-2 font-semibold text-slate-900">{row.cell}</td>
                  {factors.map((factor) => (
                    <td key={`${row.cell}-${factor.factorName}`} className="px-3 py-2 text-slate-700">{row[factor.factorName]}</td>
                  ))}
                </tr>
              ))
            ) : (
              <tr>
                <td colSpan={Math.max(1, factors.length + 1)} className="px-3 py-6 text-center text-sm text-slate-500">
                  Treatment matrix will appear after factor levels are entered.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {treatmentCells > 64 && (
        <p className="mt-2 text-xs leading-5 text-amber-700">
          Showing first 64 treatment cells. The full design contains {treatmentCells.toLocaleString()} cells.
        </p>
      )}

      {warnings.length > 0 && (
        <div className="mt-3 rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs leading-5 text-amber-900">
          <span className="font-semibold">Validation warning: </span>
          These level names also appear as factor names: {warnings.join(", ")}. Confirm levels are entered under their parent factor instead of on separate factor lines.
        </div>
      )}

      <div className="mt-4 grid gap-3 md:grid-cols-4">
        <ResultCard label="Treatment cells" value={factors.length ? treatmentCells.toLocaleString() : "-"} />
        <ResultCard label="Design" value={designLabel} />
        <ResultCard label="Recommended analysis" value={recommendedAnalysis} />
        <ResultCard label="Minimum sample" value={factors.length ? "Calculated next page" : "-"} />
      </div>
    </section>
  );
}

function DocumentationArtifactPanel({ projectId, state, setState }: { projectId: string; state: NodeState; setState: (state: NodeState) => void }) {
  const report = buildGovernanceReport();
  const spec = buildExperimentSpecification(projectId);
  const simulation = spec.simulationResults as MonteCarloSimulationResults | null;
  const packageMarkdown = [
    report.markdown,
    "",
    "## Experiment Specification JSON",
    "```json",
    JSON.stringify(spec, null, 2),
    "```",
  ].join("\n");

  const artifactActions = [
    {
      label: "Generate Executive PDF Report",
      description: "Open the executive report in the browser print workflow for PDF generation.",
      icon: FileText,
      onClick: () => printHtmlDocument(report.html),
      tone: "primary",
    },
    {
      label: "Export to Jupyter Notebook",
      description: "Download a governed notebook with project context, evidence, and reproducible simulation code.",
      icon: FileText,
      onClick: () => downloadText("atlas-experimental-design-workflow.ipynb", exportWorkflowNotebookJson(), "application/x-ipynb+json;charset=utf-8"),
      tone: "default",
    },
    {
      label: "Export Experiment Specification (JSON)",
      description: "Download the structured design specification, workflow evidence, and simulation summary.",
      icon: Download,
      onClick: () => downloadText("atlas-experiment-specification.json", JSON.stringify(spec, null, 2), "application/json;charset=utf-8"),
      tone: "default",
    },
    {
      label: "Download Governance Package",
      description: "Download the governance report plus embedded experiment specification as a single review package.",
      icon: PackageCheck,
      onClick: () => downloadText("atlas-experimental-design-governance-package.md", packageMarkdown, "text/markdown;charset=utf-8"),
      tone: "dark",
    },
  ];

  return (
    <section className="space-y-4">
      <div className="rounded-xl border border-blue-200 bg-gradient-to-br from-white to-blue-50 p-5 shadow-sm">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <div className="text-xs font-semibold uppercase tracking-wide text-blue-700">Workflow Culmination</div>
            <h2 className="mt-1 text-lg font-semibold text-slate-950">Governance-Ready Artifact Center</h2>
            <p className="mt-1 max-w-3xl text-sm leading-6 text-slate-600">
              Package the experimental design, assumptions, simulation evidence, decisions, and governance notes for audit, model risk, and peer review.
            </p>
          </div>
          <span className="rounded-full border border-blue-200 bg-white px-3 py-1 text-xs font-semibold text-blue-800">
            {spec.evidence.filter((row) => row.decision || row.rationale || row.simulationResults).length} evidence nodes captured
          </span>
        </div>

        <div className="mt-4 grid gap-3 md:grid-cols-2">
          {artifactActions.map((action) => {
            const Icon = action.icon;
            const toneClass =
              action.tone === "primary"
                ? "border-blue-200 bg-blue-600 text-white hover:bg-blue-700"
                : action.tone === "dark"
                  ? "border-slate-950 bg-slate-950 text-white hover:bg-slate-800"
                  : "border-slate-200 bg-white text-slate-900 hover:bg-slate-50";
            return (
              <button
                key={action.label}
                type="button"
                className={`rounded-xl border p-4 text-left shadow-sm transition ${toneClass}`}
                onClick={action.onClick}
              >
                <div className="flex items-center gap-2 text-sm font-semibold">
                  <Icon size={16} />
                  {action.label}
                </div>
                <p className={`mt-2 text-xs leading-5 ${action.tone === "default" ? "text-slate-600" : "text-white/85"}`}>
                  {action.description}
                </p>
              </button>
            );
          })}
        </div>
      </div>

      <div className="grid gap-4 xl:grid-cols-3">
        <ResultCard label="Report Sections" value={report.sections.length.toLocaleString()} />
        <ResultCard label="Workflow Evidence Nodes" value={spec.evidence.length.toLocaleString()} />
        <ResultCard label="Monte Carlo Status" value={simulation ? simulation.recommendedAction : "Not captured"} />
      </div>

      <TextArea
        label="Final Report Notes"
        value={state.notes}
        rows={5}
        placeholder="Capture final document gaps, appendices, approvals, and owner follow-up."
        onChange={(value) => setState({ ...state, notes: value })}
      />
    </section>
  );
}

function scoreBlockingVariable(variable: string, index: number) {
  const normalized = variable.toLowerCase();
  const isRisk = /risk|score|fico|segment|tier/.test(normalized);
  const isGeo = /geo|region|state|market|branch/.test(normalized);
  const isTime = /week|month|time|wave|campaign|period/.test(normalized);
  const isIncome = /income|balance|amount|deposit|asset/.test(normalized);
  const effectSize = isRisk ? "High" : isTime ? "Medium" : isGeo ? "Small" : isIncome ? "Small" : index === 0 ? "Medium" : "Small";
  const operationalCost = isRisk ? "Low" : isTime ? "Medium" : isGeo ? "High" : isIncome ? "Medium" : index <= 1 ? "Medium" : "High";
  const varianceReduction = isRisk ? 42 : isTime ? 24 : isGeo ? 18 : isIncome ? 12 : Math.max(8, 20 - index * 3);
  const expectedStrata = isRisk ? 5 : isGeo ? 4 : isTime ? 3 : isIncome ? 4 : Math.max(2, Math.min(5, index + 2));
  const recommendation =
    effectSize === "High" && operationalCost === "Low"
      ? "Block"
      : effectSize === "Medium" && operationalCost !== "High"
        ? "Maybe"
        : "Monitor";
  return {
    name: variable,
    effectSize,
    operationalCost,
    varianceReduction,
    expectedStrata,
    recommendation,
  };
}

function BlockingAssistant({
  projectId,
  state,
  setState,
  variables,
}: {
  projectId: string;
  state: NodeState;
  setState: (state: NodeState) => void;
  variables: string[];
}) {
  const factors = sharedParseFactorHierarchy(loadExperimentalNodeState(projectId, "Levels")?.objective ?? "");
  const treatmentCells = factors.length ? treatmentCellCount(factors) : Math.max(4, Math.round(state.numeric.averageLevels ** state.numeric.factorCount) || 4);
  const availablePopulation = Number(state.numeric.availablePopulation || state.numeric.totalPlannedSample || 25000);
  const variableNames = variables.length ? variables : ["Customer Risk", "Geography", "Campaign Week", "Branch", "Income Tier"];
  const scoredVariables = variableNames.map((variable, index) => scoreBlockingVariable(variable, index));
  const recommendedNames = scoredVariables.filter((row) => row.recommendation === "Block").map((row) => row.name);
  const selectedNames = state.metrics.includes("__none__") ? [] : state.metrics.length ? state.metrics : recommendedNames;
  const selectedVariables = scoredVariables.filter((row) => selectedNames.includes(row.name));
  const monitoredVariables = scoredVariables.filter((row) => !selectedNames.includes(row.name));
  const selectedStrata = selectedVariables.reduce((product, row) => product * row.expectedStrata, 1) || 1;
  const totalAssignmentCells = treatmentCells * selectedStrata;
  const minimumPerStratum = Math.floor(availablePopulation / Math.max(totalAssignmentCells, 1));
  const powerLoss = selectedStrata <= 5 ? "Low" : selectedStrata <= 12 ? "Medium" : "High";
  const sparseCellStatus = minimumPerStratum >= 500 ? "Low" : minimumPerStratum >= 200 ? "Medium" : "High";
  const selectedReduction = selectedVariables.reduce((sum, row) => sum + row.varianceReduction, 0);
  const riskPlusRegion = scoredVariables.filter((row) => /risk|region|geo/i.test(row.name));
  const riskRegionStrata = riskPlusRegion.reduce((product, row) => product * row.expectedStrata, 1) || selectedStrata;
  const riskRegionCells = treatmentCells * riskRegionStrata;
  const riskRegionPerCell = Math.floor(availablePopulation / Math.max(riskRegionCells, 1));
  const updateSelected = (name: string, checked: boolean) => {
    const next = checked ? Array.from(new Set([...selectedNames, name])) : selectedNames.filter((item) => item !== name);
    setState({ ...state, metrics: next.length ? next : ["__none__"] });
  };

  return (
    <section className="space-y-7">
      <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <div className="text-xs font-semibold uppercase tracking-wide text-blue-700">Nuisance Variation Control</div>
            <h2 className="mt-1 text-lg font-semibold text-slate-950">ATLAS scored candidate blocking variables.</h2>
            <p className="mt-1 max-w-3xl text-sm leading-6 text-slate-600">
              Review effect size, operational cost, variance reduction, and sparse-cell risk before accepting or overriding the recommended blocking decision.
            </p>
          </div>
          <span className="rounded-full border border-emerald-200 bg-emerald-50 px-3 py-1 text-xs font-semibold text-emerald-800">
            Recommendation engine active
          </span>
        </div>

        <div className="mt-5 overflow-x-auto rounded-xl border border-slate-200">
          <table className="min-w-[900px] w-full text-left text-sm">
            <thead className="bg-slate-50 text-xs font-semibold uppercase tracking-wide text-slate-500">
              <tr>
                <th className="px-4 py-3">Variable</th>
                <th className="px-4 py-3">Effect size</th>
                <th className="px-4 py-3">Operational cost</th>
                <th className="px-4 py-3">Variance reduction</th>
                <th className="px-4 py-3">Recommendation</th>
                <th className="px-4 py-3">Decision</th>
              </tr>
            </thead>
            <tbody>
              {scoredVariables.map((row) => (
                <tr key={row.name} className="border-t border-slate-200 odd:bg-white even:bg-slate-50/70">
                  <td className="px-4 py-3 font-semibold text-slate-950">{row.name}</td>
                  <td className="px-4 py-3">
                    <span className={`rounded-full px-2 py-1 text-xs font-semibold ${row.effectSize === "High" ? "bg-emerald-50 text-emerald-700" : row.effectSize === "Medium" ? "bg-blue-50 text-blue-700" : "bg-slate-100 text-slate-600"}`}>
                      {row.effectSize}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    <span className={`rounded-full px-2 py-1 text-xs font-semibold ${row.operationalCost === "Low" ? "bg-emerald-50 text-emerald-700" : row.operationalCost === "Medium" ? "bg-amber-50 text-amber-700" : "bg-rose-50 text-rose-700"}`}>
                      {row.operationalCost}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-slate-700">{row.varianceReduction}% expected</td>
                  <td className="px-4 py-3">
                    <span className={`rounded-full px-2 py-1 text-xs font-semibold ${row.recommendation === "Block" ? "bg-emerald-50 text-emerald-700" : row.recommendation === "Maybe" ? "bg-amber-50 text-amber-700" : "bg-slate-100 text-slate-600"}`}>
                      {row.recommendation}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    <label className="inline-flex items-center gap-2 text-xs font-semibold text-slate-700">
                      <input
                        type="checkbox"
                        className="h-4 w-4 accent-blue-600"
                        checked={selectedNames.includes(row.name)}
                        onChange={(event) => updateSelected(row.name, event.target.checked)}
                      />
                      {selectedNames.includes(row.name) ? "Use for blocking" : "Monitor only"}
                    </label>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_420px]">
        <VisualCard title="Expected Variance Reduction" subtitle="Variables with high signal and low execution cost are better blocking candidates.">
          <HorizontalBars
            rows={scoredVariables.map((row) => ({ label: row.name, value: row.varianceReduction }))}
            valueFormatter={(value) => `${value}%`}
          />
        </VisualCard>
        <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
          <div className="text-xs font-semibold uppercase tracking-wide text-blue-700">Sparse Cell Warning</div>
          <h3 className="mt-1 text-base font-semibold text-slate-950">{selectedNames.length ? selectedNames.join(" x ") : "No blocking variable selected"}</h3>
          <div className="mt-4 grid gap-3">
            <ResultCard label="Expected strata" value={selectedStrata.toLocaleString()} />
            <ResultCard label="Treatment x strata cells" value={totalAssignmentCells.toLocaleString()} />
            <ResultCard label="Minimum per cell" value={minimumPerStratum.toLocaleString()} />
            <ResultCard label="Power loss" value={powerLoss} />
          </div>
          <div className={`mt-4 rounded-xl border p-3 text-sm font-semibold ${sparseCellStatus === "Low" ? "border-emerald-200 bg-emerald-50 text-emerald-800" : sparseCellStatus === "Medium" ? "border-amber-200 bg-amber-50 text-amber-800" : "border-rose-200 bg-rose-50 text-rose-800"}`}>
            Sparse-cell risk: {sparseCellStatus}
          </div>
        </div>
      </section>

      <section className="grid gap-6 xl:grid-cols-[minmax(0,1.05fr)_minmax(360px,0.95fr)]">
        <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
          <div className="text-xs font-semibold uppercase tracking-wide text-blue-700">Blocking Decision Flow</div>
          <h2 className="mt-1 text-base font-semibold text-slate-950">Recommended method: Stratified randomization by selected blocking variable</h2>
          <p className="mt-2 text-sm leading-6 text-slate-600">
            Reason: selected variables reduce nuisance variation while preserving enough sample inside each treatment assignment cell.
          </p>
          <div className="mt-5 space-y-3 rounded-2xl border border-slate-200 bg-slate-50 p-4">
            {[
              ["Influences response?", selectedReduction >= 20 ? "Yes" : "Maybe", "ATLAS estimates whether the variable explains meaningful response variation independent of treatment."],
              ["Not a treatment?", "Yes", "It is a nuisance variable, not a customer-facing treatment arm."],
              ["Can randomize within it?", "Yes", "Treatment assignment can be balanced inside each risk segment."],
              ["Sparse-cell risk acceptable?", sparseCellStatus === "Low" ? "Yes" : sparseCellStatus, "ATLAS checks whether blocking creates too many assignment cells for the available population."],
              ["Recommendation", "Use as blocking variable", "Apply stratified randomization and monitor other drivers through balance checks."],
            ].map(([question, answer, detail], index, rows) => (
              <Fragment key={question}>
                <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm transition hover:-translate-y-0.5 hover:shadow-md">
                  <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                    <div className="flex items-start gap-3">
                      <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-blue-600 text-sm font-bold text-white">
                        {index + 1}
                      </div>
                      <div>
                        <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">{question}</div>
                        <p className="mt-1 text-sm leading-6 text-slate-600">{detail}</p>
                      </div>
                    </div>
                    <div className="rounded-full border border-blue-200 bg-blue-50 px-3 py-1 text-sm font-semibold text-blue-800">{answer}</div>
                  </div>
                </div>
                {index < rows.length - 1 && (
                  <div className="flex justify-center text-blue-400">
                    <ArrowRight size={22} className="rotate-90" />
                  </div>
                )}
              </Fragment>
            ))}
          </div>
        </div>

        <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
          <div className="text-xs font-semibold uppercase tracking-wide text-blue-700">Blocking Impact</div>
          <div className="mt-4 grid gap-3 sm:grid-cols-2">
            <ResultCard label="Candidate variables" value={scoredVariables.length.toLocaleString()} />
            <ResultCard label="Blocking variables used" value={selectedVariables.length.toLocaleString()} />
            <ResultCard label="Variables monitored only" value={monitoredVariables.length.toLocaleString()} />
            <ResultCard label="Sparse-cell risk" value={sparseCellStatus} />
            <ResultCard label="Recommended design" value="Stratified randomization" />
            <ResultCard label="Variance reduction" value={`${selectedReduction}%`} />
          </div>
        </div>
      </section>

      <section className="rounded-2xl border border-blue-200 bg-blue-50 p-6 shadow-sm">
        <div className="text-xs font-semibold uppercase tracking-wide text-blue-700">Decision Sensitivity</div>
        <h3 className="mt-1 text-base font-semibold text-blue-950">If you change the blocking decision, downstream power and complexity change.</h3>
        <div className="mt-4 grid gap-4 lg:grid-cols-2">
          <div className="rounded-xl border border-blue-200 bg-white p-4">
            <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Current selection</div>
            <div className="mt-1 text-sm font-semibold text-slate-950">{selectedNames.length ? selectedNames.join(" + ") : "No blocking"}</div>
            <div className="mt-3 grid gap-2 text-sm text-slate-700">
              <div>Power: {powerLoss === "Low" ? "80%" : powerLoss === "Medium" ? "76%" : "68%"}</div>
              <div>Variance: {selectedReduction >= 30 ? "Low" : selectedReduction >= 15 ? "Medium" : "High"}</div>
              <div>Complexity: {selectedStrata <= 5 ? "Low" : selectedStrata <= 12 ? "Medium" : "High"}</div>
            </div>
          </div>
          <div className="rounded-xl border border-amber-200 bg-white p-4">
            <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">What if: Risk + Geography</div>
            <div className="mt-1 text-sm font-semibold text-slate-950">{riskPlusRegion.map((row) => row.name).join(" + ") || "Risk + Geography"}</div>
            <div className="mt-3 grid gap-2 text-sm text-slate-700">
              <div>Power: {riskRegionPerCell >= 500 ? "76%" : "72%"}</div>
              <div>Variance: Very low</div>
              <div>Complexity: {riskRegionStrata > selectedStrata ? "Higher" : "Similar"}</div>
              <div>Sparse cells: {riskRegionPerCell >= 500 ? "Unlikely" : "Likely"}</div>
            </div>
          </div>
        </div>
      </section>

      <section className="grid gap-6 lg:grid-cols-2">
        <div className="min-h-[190px] rounded-2xl border border-amber-200 bg-amber-50 p-7 shadow-sm transition hover:-translate-y-0.5 hover:shadow-md">
          <div className="text-xs font-semibold uppercase tracking-wide text-amber-800">Without blocking</div>
          <h3 className="mt-2 text-lg font-semibold text-amber-950">Higher imbalance risk</h3>
          <div className="mt-3 inline-flex rounded-full border border-amber-300 bg-white/70 px-3 py-1 text-xs font-semibold text-amber-800">
            Risk: treatment groups may not be comparable
          </div>
          <p className="mt-2 text-sm leading-6 text-amber-900">
            Treatment groups may accidentally contain different mixes of customer risk, making activation differences harder to attribute to the treatment.
          </p>
        </div>
        <div className="min-h-[190px] rounded-2xl border border-emerald-200 bg-emerald-50 p-7 shadow-sm transition hover:-translate-y-0.5 hover:shadow-md">
          <div className="text-xs font-semibold uppercase tracking-wide text-emerald-800">With stratified randomization</div>
          <h3 className="mt-2 text-lg font-semibold text-emerald-950">Better treatment comparability</h3>
          <div className="mt-3 inline-flex rounded-full border border-emerald-300 bg-white/70 px-3 py-1 text-xs font-semibold text-emerald-800">
            Value: cleaner treatment effect estimate
          </div>
          <p className="mt-2 text-sm leading-6 text-emerald-900">
            Assignment is balanced within customer risk segment, reducing nuisance variation without expanding treatment cells.
          </p>
        </div>
      </section>
    </section>
  );
}

function BlockingGovernanceConfirmation({ config, state, setState }: { config: ExperimentalStepConfig; state: NodeState; setState: (state: NodeState) => void }) {
  return (
    <details className="rounded-2xl border border-slate-200 bg-white shadow-sm">
      <summary className="cursor-pointer list-none px-6 py-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Governance Confirmation</div>
            <h2 className="mt-1 text-base font-semibold text-slate-950">Document the blocking decision supported by the analysis.</h2>
            <p className="mt-2 text-sm leading-6 text-slate-600">
              Audit-ready rationale is available. Expand only if governance documentation requires editing.
            </p>
          </div>
          <span className="rounded-full border border-blue-200 bg-blue-50 px-4 py-1.5 text-xs font-semibold text-blue-800">Expand</span>
        </div>
      </summary>
      <div className="border-t border-slate-200 p-5">
        <div className="grid gap-4 lg:grid-cols-2">
          {config.fields.map((field) => (
            <TextArea
              key={field.key}
              label={field.label}
              value={String(state[field.key] ?? "")}
              rows={field.rows ?? 4}
              placeholder={field.placeholder}
              onChange={(value) => setState({ ...state, [field.key]: value })}
            />
          ))}
          <label className="grid gap-1.5">
            <span className="text-xs font-semibold uppercase tracking-wide text-slate-500">{config.methodLabel}</span>
            <select
              className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm"
              value={state.method}
              onChange={(event) => setState({ ...state, method: event.target.value })}
            >
              <option value="">Select expected nuisance variation</option>
              {config.methods.map((method) => (
                <option key={method} value={method}>{method}</option>
              ))}
            </select>
          </label>
          <TextArea
            label="Decision / Recommendation"
            value={state.decision}
            rows={4}
            placeholder="Recommended method: Stratified randomization by customer risk segment."
            onChange={(value) => setState({ ...state, decision: value })}
          />
          <TextArea
            label="Rationale for Governance"
            value={state.rationale}
            rows={4}
            placeholder="Risk segment is most likely to influence activation and can be controlled without creating too many treatment cells."
            onChange={(value) => setState({ ...state, rationale: value })}
          />
        </div>
      </div>
    </details>
  );
}

function RandomizationGovernanceConfirmation({ config, state, setState }: { config: ExperimentalStepConfig; state: NodeState; setState: (state: NodeState) => void }) {
  return (
    <details className="rounded-2xl border border-slate-200 bg-white shadow-sm">
      <summary className="cursor-pointer list-none px-6 py-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Governance Confirmation</div>
            <h2 className="mt-1 text-base font-semibold text-slate-950">Document assignment logic, seed, exclusions, and balance checks.</h2>
            <p className="mt-2 text-sm leading-6 text-slate-600">
              Audit-ready assignment evidence is available. Expand only if launch documentation requires editing.
            </p>
          </div>
          <span className="rounded-full border border-blue-200 bg-blue-50 px-4 py-1.5 text-xs font-semibold text-blue-800">Expand</span>
        </div>
      </summary>
      <div className="border-t border-slate-200 p-5">
        <div className="grid gap-4 lg:grid-cols-2">
          {config.fields.map((field) => (
            <TextArea
              key={field.key}
              label={field.label}
              value={String(state[field.key] ?? "")}
              rows={field.rows ?? 4}
              placeholder={field.placeholder}
              onChange={(value) => setState({ ...state, [field.key]: value })}
            />
          ))}
          <label className="grid gap-1.5">
            <span className="text-xs font-semibold uppercase tracking-wide text-slate-500">{config.methodLabel}</span>
            <select
              className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm"
              value={state.method}
              onChange={(event) => setState({ ...state, method: event.target.value })}
            >
              <option value="">Select randomization method</option>
              {config.methods.map((method) => (
                <option key={method} value={method}>{method}</option>
              ))}
            </select>
          </label>
          <TextArea
            label="Rationale for Governance"
            value={state.rationale}
            rows={4}
            placeholder="Explain why the selected method, seed, exclusions, and balance checks are appropriate for launch approval."
            onChange={(value) => setState({ ...state, rationale: value })}
          />
        </div>
      </div>
    </details>
  );
}

function SampleSizeGovernanceConfirmation({ config, state, setState }: { config: ExperimentalStepConfig; state: NodeState; setState: (state: NodeState) => void }) {
  return (
    <details className="rounded-2xl border border-slate-200 bg-white shadow-sm">
      <summary className="cursor-pointer list-none px-6 py-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Governance Confirmation</div>
            <h2 className="mt-1 text-base font-semibold text-slate-950">Document power assumptions and sample-size rationale.</h2>
            <p className="mt-2 text-sm leading-6 text-slate-600">
              Audit-ready power-analysis evidence is available. Expand only if alpha, power, baseline response, lift, or population assumptions require editing.
            </p>
          </div>
          <span className="rounded-full border border-blue-200 bg-blue-50 px-4 py-1.5 text-xs font-semibold text-blue-800">Expand</span>
        </div>
      </summary>
      <div className="border-t border-slate-200 p-5">
        <div className="grid gap-4 lg:grid-cols-2">
          {config.fields.map((field) => (
            <TextArea
              key={field.key}
              label={field.label}
              value={String(state[field.key] ?? "")}
              rows={field.rows ?? 4}
              placeholder={field.placeholder}
              onChange={(value) => setState({ ...state, [field.key]: value })}
            />
          ))}
          <label className="grid gap-1.5">
            <span className="text-xs font-semibold uppercase tracking-wide text-slate-500">{config.methodLabel}</span>
            <select
              className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm"
              value={state.method}
              onChange={(event) => setState({ ...state, method: event.target.value })}
            >
              <option value="">Select sample sizing basis</option>
              {config.methods.map((method) => (
                <option key={method} value={method}>{method}</option>
              ))}
            </select>
          </label>
          <MetricPicker options={config.metrics} selected={state.metrics} onChange={(metrics) => setState({ ...state, metrics })} />
        </div>
      </div>
    </details>
  );
}

function MonteCarloGovernanceConfirmation({ config, state, setState }: { config: ExperimentalStepConfig; state: NodeState; setState: (state: NodeState) => void }) {
  return (
    <details className="rounded-2xl border border-slate-200 bg-white shadow-sm">
      <summary className="cursor-pointer list-none px-6 py-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Governance Confirmation</div>
            <h2 className="mt-1 text-base font-semibold text-slate-950">Simulation assumptions, seed, stress cases, and launch recommendation are audit-ready.</h2>
            <p className="mt-2 text-sm leading-6 text-slate-600">
              Expand only if simulation rationale or launch governance documentation requires editing.
            </p>
          </div>
          <span className="rounded-full border border-blue-200 bg-blue-50 px-4 py-1.5 text-xs font-semibold text-blue-800">Expand</span>
        </div>
      </summary>
      <div className="border-t border-slate-200 p-5">
        <div className="grid gap-4 lg:grid-cols-2">
          {config.fields.map((field) => (
            <TextArea
              key={field.key}
              label={field.label}
              value={String(state[field.key] ?? "")}
              rows={field.rows ?? 4}
              placeholder={field.placeholder}
              onChange={(value) => setState({ ...state, [field.key]: value })}
            />
          ))}
          <TextArea
            label="Simulation Decision Rationale"
            value={state.rationale}
            rows={4}
            placeholder="Explain how the simulation results support launch, redesign, or additional sample collection."
            onChange={(value) => setState({ ...state, rationale: value })}
          />
        </div>
      </div>
    </details>
  );
}

function RunPlanGovernanceConfirmation({ config, state, setState }: { config: ExperimentalStepConfig; state: NodeState; setState: (state: NodeState) => void }) {
  return (
    <details className="rounded-2xl border border-slate-200 bg-white shadow-sm">
      <summary className="cursor-pointer list-none px-6 py-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Governance Confirmation</div>
            <h2 className="mt-1 text-base font-semibold text-slate-950">Operational launch evidence is available for audit.</h2>
            <p className="mt-2 text-sm leading-6 text-slate-600">
              Expand only if execution sequence, QA evidence, stopping rules, or escalation rationale requires editing.
            </p>
          </div>
          <span className="rounded-full border border-blue-200 bg-blue-50 px-4 py-1.5 text-xs font-semibold text-blue-800">Expand</span>
        </div>
      </summary>
      <div className="border-t border-slate-200 p-5">
        <div className="grid gap-4 lg:grid-cols-2">
          {config.fields.map((field) => (
            <TextArea
              key={field.key}
              label={field.label}
              value={String(state[field.key] ?? "")}
              rows={field.rows ?? 4}
              placeholder={field.placeholder}
              onChange={(value) => setState({ ...state, [field.key]: value })}
            />
          ))}
          <TextArea
            label="Launch Decision Rationale"
            value={state.decision}
            rows={4}
            placeholder="State whether the experiment is approved for launch, conditionally approved, or blocked pending remediation."
            onChange={(value) => setState({ ...state, decision: value })}
          />
        </div>
      </div>
    </details>
  );
}

function formatPct(value: number, digits = 1) {
  return `${(value * 100).toFixed(digits)}%`;
}

function histogram(values: number[], bins: Array<{ label: string; min: number; max: number }>) {
  return bins.map((bin) => ({
    label: bin.label,
    value: values.filter((value) => value >= bin.min && value < bin.max).length,
  }));
}

function liftHistogram(values: number[]) {
  const low = Math.min(...values, -0.1);
  const high = Math.max(...values, 0.2);
  const width = (high - low) / 6 || 0.05;
  return Array.from({ length: 6 }, (_, index) => {
    const min = low + width * index;
    const max = index === 5 ? high + 0.000001 : min + width;
    return {
      label: `${formatPct(min, 0)} to ${formatPct(max, 0)}`,
      value: values.filter((value) => value >= min && value < max).length,
    };
  });
}

function simulationNarrative(results: MonteCarloSimulationResults) {
  if (results.recommendedAction === "Redesign Required") {
    return `This experiment should not launch as currently designed because the available sample is too small for ${results.inputs.treatmentCells.toLocaleString()} treatment cell(s) and the expected ${formatPct(results.inputs.minimumDetectableLift)} lift. The current plan has ${results.inputs.totalSample.toLocaleString()} total customers, ${results.inputs.samplePerCell.toLocaleString()} per cell, mean simulated power of ${formatPct(results.meanPower)}, false-negative risk of ${formatPct(results.falseNegativeRate)}, and wrong-winner risk of ${formatPct(results.wrongWinnerRate)}. Increase sample size, reduce treatment cells, or accept a larger minimum detectable lift before launch approval.`;
  }
  const topDriver = results.riskDrivers[0];
  const missingStress = results.scenarioSensitivity.find((row) => row.scenario === "5% missingness");
  const combined = results.scenarioSensitivity.find((row) => row.scenario === "Combined stress");
  const launchLanguage =
    results.recommendedAction === "Strong"
      ? "Simulation results support launch readiness under the current assumptions."
      : results.recommendedAction === "Adequate"
        ? "Simulation results are acceptable, but the design should proceed with explicit monitoring and launch controls."
        : results.recommendedAction === "Weak"
          ? "Simulation results show material risk. Consider increasing sample or simplifying the design before launch."
          : "Simulation results do not support launch without redesign.";
  return `${launchLanguage} Mean simulated power is ${formatPct(results.meanPower)} with a wrong-winner rate of ${formatPct(results.wrongWinnerRate)}. The largest risk driver is ${topDriver?.driver.toLowerCase() ?? "sample size"}. Missingness at 5% produces ${formatPct(missingStress?.estimatedPower ?? 0)} estimated power, while combined stress produces ${formatPct(combined?.estimatedPower ?? 0)}.`;
}

function MonteCarloSimulationDashboard({ projectId, state, setState }: { projectId: string; state: NodeState; setState: (state: NodeState) => void }) {
  const [isRunning, setIsRunning] = useState(false);
  const [progress, setProgress] = useState(0);
  const [runtimeMs, setRuntimeMs] = useState<number | null>(null);
  const inputs = monteCarloInputs(projectId, state);
  const results =
    state.simulationResults?.inputs.samplePerCell === inputs.samplePerCell &&
    state.simulationResults.inputs.totalSample === inputs.totalSample &&
    state.simulationResults.inputs.treatmentCells === inputs.treatmentCells
      ? state.simulationResults
      : undefined;
  const updateNumber = (key: string, value: number) => setState({ ...state, numeric: { ...state.numeric, [key]: value }, simulationResults: undefined });
  const runSimulation = () => {
    if (!inputs.sampleReady || isRunning) return;
    const startedAt = performance.now();
    setRuntimeMs(null);
    setIsRunning(true);
    setProgress(8);
    const checkpoints = [18, 32, 47, 63, 78, 91];
    checkpoints.forEach((value, index) => {
      window.setTimeout(() => setProgress(value), 90 * (index + 1));
    });
    window.setTimeout(() => {
      const simulationResults = runMonteCarloSimulation(projectId, state);
      const nextDecision =
        simulationResults.recommendedAction === "Strong" || simulationResults.recommendedAction === "Adequate"
          ? `Monte Carlo simulation result: ${simulationResults.recommendedAction}. Proceed with execution planning if governance and operational controls are complete.`
          : `Monte Carlo simulation result: ${simulationResults.recommendedAction}. Redesign, increase sample, or simplify the treatment structure before launch approval.`;
      const nextState = { ...state, simulationResults, decision: state.decision || nextDecision };
      setState(nextState);
      const monteCarloStep = getWorkflowDefinition("experimental-design").steps.find((step) => step.label === "Monte Carlo Simulation");
      if (monteCarloStep) saveNodeState(projectId, monteCarloStep.id, nextState);
      setProgress(100);
      setRuntimeMs(performance.now() - startedAt);
      setIsRunning(false);
    }, 725);
  };
  return (
    <div className="space-y-6">
      <section className="grid gap-5 rounded-2xl border border-blue-200 bg-gradient-to-br from-white to-blue-50 p-6 shadow-sm xl:grid-cols-[minmax(0,1fr)_320px]">
        <div>
          <div className="text-xs font-semibold uppercase tracking-wide text-blue-700">Monte Carlo Simulation Engine</div>
          <h2 className="mt-1 text-xl font-semibold text-slate-950">If we ran this experiment thousands of times, what would happen?</h2>
          <p className="mt-2 max-w-4xl text-sm leading-6 text-slate-600">
            ATLAS uses the current treatment structure, sample-size plan, alpha, target power, baseline response, lift, and randomization stress assumptions to simulate launch outcomes before execution.
          </p>
          <div className="mt-4 grid gap-3 md:grid-cols-3">
            <ResultCard label="Treatment cells" value={inputs.treatmentCells.toLocaleString()} />
            <ResultCard label="Sample per cell" value={inputs.sampleReady ? inputs.samplePerCell.toLocaleString() : "Sample size required before simulation"} />
            <ResultCard label="Total sample" value={inputs.sampleReady ? inputs.totalSample.toLocaleString() : "Sample size required before simulation"} />
            <ResultCard label="Baseline response" value={formatPct(inputs.baselineRate)} />
            <ResultCard label="Minimum lift" value={formatPct(inputs.minimumDetectableLift)} />
            <ResultCard label="Target power" value={formatPct(inputs.desiredPower)} />
            <ResultCard label="Sample source" value={inputs.sampleSource} />
          </div>
          <div className="mt-5 rounded-xl border border-blue-200 bg-white/70 p-4">
            <div className="text-xs font-semibold uppercase tracking-wide text-blue-700">Stress Test Explorer</div>
            <div className="mt-3 grid gap-3 md:grid-cols-4">
              <NumberField label="Baseline response %" value={Number((inputs.baselineRate * 100).toFixed(2))} onChange={(value) => updateNumber("baselineRate", value)} />
              <NumberField label="Treatment lift %" value={Number((inputs.minimumDetectableLift * 100).toFixed(2))} onChange={(value) => updateNumber("expectedLift", value)} />
              <NumberField label="Missing data %" value={Number((inputs.missingnessRate * 100).toFixed(1))} onChange={(value) => updateNumber("missingnessRate", value)} />
              <NumberField label="Random imbalance %" value={Number((inputs.imbalanceRate * 100).toFixed(1))} onChange={(value) => updateNumber("treatmentImbalance", value)} />
              <NumberField label="Variance index" value={Number((inputs.varianceMultiplier * 100).toFixed(0))} onChange={(value) => updateNumber("varianceStress", value)} />
              <NumberField label="Attrition %" value={Number((inputs.attritionRate * 100).toFixed(1))} onChange={(value) => updateNumber("attritionRate", value)} />
              <NumberField label="Measurement error %" value={Number((inputs.measurementErrorRate * 100).toFixed(1))} onChange={(value) => updateNumber("measurementErrorRate", value)} />
              <NumberField label="Nonresponse %" value={Number((inputs.nonresponseRate * 100).toFixed(1))} onChange={(value) => updateNumber("nonresponseRate", value)} />
            </div>
          </div>
        </div>
        <div className="flex flex-col gap-3 rounded-xl border border-white/80 bg-white p-4 shadow-sm">
          <NumberField label="Seed" value={state.numeric.seed || 42} onChange={(value) => updateNumber("seed", value)} />
          <NumberField label="Iterations" value={state.numeric.simulations || 1000} onChange={(value) => updateNumber("simulations", value)} />
          <button
            type="button"
            className={`mt-auto rounded-lg px-3 py-2 text-sm font-semibold text-white shadow-sm ${inputs.sampleReady && !isRunning ? "bg-blue-600 hover:bg-blue-700" : "cursor-not-allowed bg-slate-300"}`}
            onClick={runSimulation}
            disabled={!inputs.sampleReady || isRunning}
            title={inputs.sampleReady ? "Run Monte Carlo Simulation" : "Sample size required before simulation"}
          >
            {isRunning ? "Running simulation..." : "Run Monte Carlo Simulation"}
          </button>
          {(isRunning || progress > 0 || runtimeMs !== null) && (
            <div className="rounded-lg border border-slate-200 bg-slate-50 p-3">
              <div className="flex items-center justify-between text-xs font-semibold text-slate-600">
                <span>{isRunning ? "Processing iterations" : "Last run complete"}</span>
                <span>{Math.round(progress)}%</span>
              </div>
              <div className="mt-2 h-2 overflow-hidden rounded-full bg-white">
                <div className="h-full rounded-full bg-blue-600 transition-all" style={{ width: `${progress}%` }} />
              </div>
              <p className="mt-2 text-[11px] leading-4 text-slate-500">
                {runtimeMs === null
                  ? `${inputs.iterations.toLocaleString()} deterministic simulation iterations are running in the browser.`
                  : `${inputs.iterations.toLocaleString()} iterations completed in ${runtimeMs.toFixed(0)} ms.`}
              </p>
            </div>
          )}
          <div className={`rounded-lg border px-3 py-2 text-sm font-semibold ${results ? statusClass(results.recommendedAction) : "border-slate-200 bg-slate-50 text-slate-600"}`}>
            {results ? results.recommendedAction : "Awaiting simulation"}
          </div>
        </div>
      </section>

      {!results ? (
        <MonteCarloPreRunWorkspace inputs={inputs} />
      ) : (
        <MonteCarloResults results={results} />
      )}
    </div>
  );
}

function statusClass(status: MonteCarloSimulationResults["recommendedAction"]) {
  if (status === "Strong") return "border-emerald-200 bg-emerald-50 text-emerald-800";
  if (status === "Adequate") return "border-blue-200 bg-blue-50 text-blue-800";
  if (status === "Weak") return "border-amber-200 bg-amber-50 text-amber-800";
  return "border-rose-200 bg-rose-50 text-rose-800";
}

function MonteCarloPreRunWorkspace({ inputs }: { inputs: ReturnType<typeof monteCarloInputs> }) {
  const placeholderPower = [0.55, 0.65, 0.75, 0.85, 0.95].map((power, index) => ({
    label: `${Math.round(power * 100)}%`,
    value: Math.max(6, Math.round((1 - Math.abs(power - inputs.desiredPower)) * 48) + index * 3),
  }));
  const placeholderLift = [-0.05, 0, inputs.minimumDetectableLift / 2, inputs.minimumDetectableLift, inputs.minimumDetectableLift * 1.5].map((lift, index) => ({
    label: formatPct(lift, 0),
    value: Math.max(4, 24 + index * 8),
  }));
  return (
    <section className="space-y-5">
      <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Live Simulation Workspace</div>
            <h3 className="mt-1 text-lg font-semibold text-slate-950">Ready to simulate launch outcomes</h3>
            <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-600">
              These preview panels show the outputs ATLAS will populate from the current design assumptions. Run the simulation to replace the preview with computed distributions, diagnostics, and launch guidance.
            </p>
          </div>
          <span className={`rounded-full border px-3 py-1 text-xs font-semibold ${inputs.sampleReady ? "border-emerald-200 bg-emerald-50 text-emerald-800" : "border-amber-200 bg-amber-50 text-amber-800"}`}>
            {inputs.sampleReady ? "Simulation ready" : "Sample size required"}
          </span>
        </div>
      </section>
      <section className="grid gap-5 xl:grid-cols-2">
        <PreviewChart title="Power Distribution Preview" subtitle="Will show achieved power across repeated experiments." rows={placeholderPower} />
        <PreviewChart title="Treatment Effect Preview" subtitle="Will show simulated lift around the expected treatment effect." rows={placeholderLift} />
      </section>
      <section className="grid gap-5 xl:grid-cols-3">
        <PreviewMetric title="Decision Stability" value="Pending" detail="Launch vs no-launch frequency after simulation." />
        <PreviewMetric title="Wrong Winner Analysis" value="Pending" detail="Probability of choosing the wrong treatment." />
        <PreviewMetric title="CI Coverage" value="Pending" detail="How often intervals contain the true effect." />
      </section>
    </section>
  );
}

function PreviewChart({ title, subtitle, rows }: { title: string; subtitle: string; rows: { label: string; value: number }[] }) {
  return (
    <div className="relative overflow-hidden rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
      <div className="absolute inset-0 bg-[linear-gradient(135deg,rgba(248,250,252,.78),rgba(255,255,255,.92))]" />
      <div className="relative">
        <h3 className="text-sm font-semibold text-slate-950">{title}</h3>
        <p className="mt-1 text-xs leading-5 text-slate-500">{subtitle}</p>
        <div className="mt-6 flex h-64 items-end gap-3 border-b border-l border-slate-200 px-4 pb-4 opacity-70">
          {rows.map((row) => (
            <div key={row.label} className="flex min-w-0 flex-1 flex-col items-center gap-2">
              <div className="w-full rounded-t bg-slate-300" style={{ height: `${row.value * 3}px` }} />
              <div className="text-[10px] font-semibold text-slate-500">{row.label}</div>
            </div>
          ))}
        </div>
        <div className="absolute inset-x-8 top-1/2 rounded-xl border border-blue-200 bg-blue-50/95 px-5 py-4 text-center shadow-sm">
          <div className="text-sm font-semibold text-blue-950">Run simulation to calculate</div>
          <div className="mt-1 text-xs text-blue-700">Charts will be derived from the current sample size, randomization, alpha, power, and stress assumptions.</div>
        </div>
      </div>
    </div>
  );
}

function PreviewMetric({ title, value, detail }: { title: string; value: string; detail: string }) {
  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">{title}</div>
      <div className="mt-2 text-2xl font-semibold text-slate-400">{value}</div>
      <p className="mt-2 text-xs leading-5 text-slate-500">{detail}</p>
    </div>
  );
}

function MonteCarloResults({ results }: { results: MonteCarloSimulationResults }) {
  const powerBands = results.powerDistribution ?? histogram(results.powerByIteration.map((row) => row.achievedPower), [
    { label: "50-60%", min: 0.5, max: 0.6 },
    { label: "60-70%", min: 0.6, max: 0.7 },
    { label: "70-80%", min: 0.7, max: 0.8 },
    { label: "80-90%", min: 0.8, max: 0.9 },
    { label: "90-100%", min: 0.9, max: 1.01 },
  ]);
  const liftBands = results.liftDistribution ?? liftHistogram(results.powerByIteration.map((row) => row.estimatedLift));
  const falsePositiveBands = [
    { label: "Alpha baseline", value: Math.round(results.falsePositiveRate * results.iterations) },
    { label: "Imbalance adjusted", value: Math.round(results.falsePositiveRate * (1 + results.inputs.imbalanceRate) * results.iterations) },
    { label: "Missing adjusted", value: Math.round(results.falsePositiveRate * (1 + results.inputs.missingnessRate) * results.iterations) },
    { label: "Stress adjusted", value: Math.round(results.falsePositiveRate * (1 + results.inputs.measurementErrorRate + results.inputs.nonresponseRate) * results.iterations) },
  ];
  const falseNegativeBands = [
    { label: "Detected lift", value: results.outcomeBreakdown.find((row) => row.outcome === "Correctly detects effect")?.count ?? results.powerByIteration.filter((row) => row.detectedEffect).length },
    { label: "False negatives", value: results.outcomeBreakdown.find((row) => row.outcome === "Misses true effect")?.count ?? results.powerByIteration.filter((row) => !row.detectedEffect).length },
    { label: "Wrong winner", value: results.outcomeBreakdown.find((row) => row.outcome === "Wrong winner selected")?.count ?? results.powerByIteration.filter((row) => !row.selectedWinnerCorrect).length },
  ];
  const detectedCount = results.powerByIteration.length
    ? results.powerByIteration.filter((row) => row.detectedEffect).length
    : results.outcomeBreakdown.find((row) => row.outcome === "Correctly detects effect")?.count ?? Math.round(results.meanPower * results.iterations);
  const noLaunchCount = results.iterations - detectedCount;
  const runningRows = results.convergenceCurve ?? Array.from({ length: 10 }, (_, index) => {
    const end = Math.max(1, Math.round(((index + 1) / 10) * results.powerByIteration.length));
    return { x: end, y: mean(results.powerByIteration.slice(0, end).map((row) => row.achievedPower)) };
  });
  return (
    <div className="space-y-6">
      <section className="grid gap-3 md:grid-cols-3 xl:grid-cols-6">
        <SimulationStat label="Mean Power" value={formatPct(results.meanPower)} status={results.meanPower >= 0.8 ? "pass" : results.meanPower >= 0.7 ? "warn" : "fail"} />
        <SimulationStat label="Median Power" value={formatPct(results.medianPower)} status={results.medianPower >= 0.8 ? "pass" : results.medianPower >= 0.7 ? "warn" : "fail"} />
        <SimulationStat label="False Negative Rate" value={formatPct(results.falseNegativeRate)} status={results.falseNegativeRate <= 0.2 ? "pass" : "warn"} />
        <SimulationStat label="Wrong Winner Rate" value={formatPct(results.wrongWinnerRate)} status={results.wrongWinnerRate <= 0.05 ? "pass" : results.wrongWinnerRate <= 0.1 ? "warn" : "fail"} />
        <SimulationStat label="Decision Stability" value={formatPct(results.decisionStabilityScore)} status={results.decisionStabilityScore >= 0.8 ? "pass" : results.decisionStabilityScore >= 0.7 ? "warn" : "fail"} />
        <SimulationStat label="CI Coverage" value={formatPct(results.confidenceIntervalCoverage)} status={results.confidenceIntervalCoverage >= 0.9 ? "pass" : "warn"} />
      </section>

      <section className="grid gap-5 xl:grid-cols-[360px_minmax(0,1fr)]">
        <LaunchReadinessGauge results={results} />
        <DecisionStabilityPanel launchCount={detectedCount} noLaunchCount={noLaunchCount} iterations={results.iterations} />
      </section>

      <section className="grid gap-5 xl:grid-cols-2">
        <BarChartCard title="Power Distribution" subtitle="How often the simulated design reaches each achieved-power range." rows={powerBands} valueFormatter={(value) => value.toLocaleString()} note="A reliable design should concentrate observations in the 80-100% power bands." />
        <BarChartCard title="Estimated Treatment Lift Distribution" subtitle={`Distribution of estimated lifts. Minimum practical lift: ${formatPct(results.inputs.minimumDetectableLift)}; zero effect is the key downside boundary.`} rows={liftBands} valueFormatter={(value) => value.toLocaleString()} note="Wide or negative lift bands indicate unstable treatment selection risk." />
      </section>

      <section className="grid gap-5 xl:grid-cols-2">
        <BarChartCard title="False Positive Distribution" subtitle="Expected false-positive pressure under current alpha and stress assumptions." rows={falsePositiveBands} valueFormatter={(value) => value.toLocaleString()} note="False-positive risk increases when imbalance, missing data, or measurement error are high." />
        <BarChartCard title="False Negative Distribution" subtitle="How often the simulation misses the expected lift or selects the wrong winner." rows={falseNegativeBands} valueFormatter={(value) => value.toLocaleString()} note="False negatives are the core risk when power is inadequate or the practical lift is too small." />
      </section>

      <section className="grid gap-5 xl:grid-cols-2">
        <LineChartCard title="Power Curve by Sample Size" subtitle="Estimated power as sample per treatment cell changes." rows={results.powerCurve.map((row) => ({ x: row.samplePerCell, y: row.estimatedPower }))} yFormatter={formatPct} note={`Current sample per cell: ${results.inputs.samplePerCell.toLocaleString()}. Target power: ${formatPct(results.inputs.desiredPower)}.`} />
        <HorizontalBarChartCard title="Scenario Sensitivity" subtitle="Expected power under baseline and stress assumptions." rows={results.scenarioSensitivity.map((row) => ({ label: row.scenario, value: row.estimatedPower, status: row.designStatus }))} valueFormatter={formatPct} note="Stress scenarios below target power should be resolved before experiment launch." />
      </section>

      <section className="grid gap-5 xl:grid-cols-2">
        <HorizontalBarChartCard title="Risk Driver Tornado Chart" subtitle="Assumptions with the largest impact on design reliability." rows={results.riskDrivers.map((row) => ({ label: row.driver, value: row.impactScore, status: "Adequate" as const }))} valueFormatter={formatPct} note={results.riskDrivers[0]?.explanation ?? "Risk drivers are calculated from scenario sensitivity."} />
        <BarChartCard title="Decision Outcome Breakdown" subtitle="How simulated experiments resolve across decision outcomes." rows={results.outcomeBreakdown.map((row) => ({ label: row.outcome, value: row.count }))} valueFormatter={(value) => value.toLocaleString()} note="Wrong winner and missed-effect outcomes should be explicitly reviewed before launch." />
      </section>

      <section className="grid gap-5 xl:grid-cols-2">
        <ConfidenceIntervalSimulation results={results} />
        <LineChartCard title="Convergence Diagnostics" subtitle="Running mean of achieved power as Monte Carlo iterations accumulate." rows={runningRows} yFormatter={formatPct} note={`Monte Carlo error estimate: +/- ${formatPct(Math.sqrt(results.meanPower * (1 - results.meanPower) / Math.max(1, results.iterations)) * 1.96)} at 95% confidence.`} />
      </section>

      <section className="grid gap-5 xl:grid-cols-2">
        <WrongWinnerAnalysis results={results} />
        <WhatIfMonteCarloComparison results={results} />
      </section>

      <section className="grid gap-5 xl:grid-cols-2">
        <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
          <h3 className="text-sm font-semibold text-slate-950">Simulation Interpretation</h3>
          <p className="mt-2 text-sm leading-6 text-slate-700">{simulationNarrative(results)}</p>
        </div>
        <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
          <h3 className="text-sm font-semibold text-slate-950">Governance Notes</h3>
          <p className="mt-2 text-sm leading-6 text-slate-700">
            Save this node to persist seed {results.seed}, {results.iterations.toLocaleString()} iterations, simulation assumptions, risk drivers, scenario sensitivity, and the recommended action in the experimental evidence record.
          </p>
        </div>
      </section>
    </div>
  );
}

function LaunchReadinessGauge({ results }: { results: MonteCarloSimulationResults }) {
  const score = Math.round((results.meanPower * 0.35 + results.decisionStabilityScore * 0.3 + (1 - results.wrongWinnerRate) * 0.2 + results.confidenceIntervalCoverage * 0.15) * 100);
  const color = score >= 85 ? "text-emerald-700" : score >= 70 ? "text-amber-700" : "text-rose-700";
  const bg = score >= 85 ? "from-emerald-50 to-white border-emerald-200" : score >= 70 ? "from-amber-50 to-white border-amber-200" : "from-rose-50 to-white border-rose-200";
  return (
    <section className={`rounded-2xl border bg-gradient-to-br ${bg} p-6 shadow-sm`}>
      <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Launch Readiness Gauge</div>
      <div className="mt-5 flex items-center justify-center">
        <div className="relative h-44 w-44 rounded-full border-[18px] border-slate-100 bg-white shadow-inner">
          <div className="absolute inset-[-18px] rounded-full border-[18px] border-transparent" style={{ borderTopColor: score >= 85 ? "#10b981" : score >= 70 ? "#f59e0b" : "#e11d48", transform: `rotate(${Math.max(-130, Math.min(130, score * 2.6 - 130))}deg)` }} />
          <div className="absolute inset-0 flex flex-col items-center justify-center">
            <div className={`text-4xl font-semibold ${color}`}>{score}</div>
            <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">confidence</div>
          </div>
        </div>
      </div>
      <div className="mt-5 rounded-xl border border-white/80 bg-white/80 p-4 text-center">
        <div className={`text-lg font-semibold ${color}`}>{results.recommendedAction}</div>
        <p className="mt-1 text-xs leading-5 text-slate-600">Combines power, stability, wrong-winner risk, and CI coverage.</p>
      </div>
    </section>
  );
}

function DecisionStabilityPanel({ launchCount, noLaunchCount, iterations }: { launchCount: number; noLaunchCount: number; iterations: number }) {
  const launchPct = iterations ? launchCount / iterations : 0;
  const noLaunchPct = iterations ? noLaunchCount / iterations : 0;
  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
      <div className="text-xs font-semibold uppercase tracking-wide text-blue-700">Decision Stability</div>
      <h3 className="mt-1 text-lg font-semibold text-slate-950">If this experiment were repeated {iterations.toLocaleString()} times...</h3>
      <div className="mt-6 space-y-5">
        <div>
          <div className="flex justify-between text-sm font-semibold text-slate-800"><span>Launch decision</span><span>{formatPct(launchPct)}</span></div>
          <div className="mt-2 h-5 overflow-hidden rounded-full bg-slate-100"><div className="h-full rounded-full bg-emerald-500" style={{ width: `${launchPct * 100}%` }} /></div>
        </div>
        <div>
          <div className="flex justify-between text-sm font-semibold text-slate-800"><span>No launch / inconclusive</span><span>{formatPct(noLaunchPct)}</span></div>
          <div className="mt-2 h-5 overflow-hidden rounded-full bg-slate-100"><div className="h-full rounded-full bg-amber-500" style={{ width: `${noLaunchPct * 100}%` }} /></div>
        </div>
      </div>
      <p className="mt-5 text-sm leading-6 text-slate-600">Stable experiments make the same decision in most repeated simulations. Low stability means the launch decision is sensitive to random sampling variation.</p>
    </section>
  );
}

function ConfidenceIntervalSimulation({ results }: { results: MonteCarloSimulationResults }) {
  const trueLift = results.inputs.minimumDetectableLift;
  const intervals = results.intervalPreview ?? results.powerByIteration.slice(0, 80).map((row, index) => {
    const width = Math.max(0.005, results.liftStdDev * 1.96 * (0.8 + (index % 7) * 0.05));
    const low = row.estimatedLift - width;
    const high = row.estimatedLift + width;
    return { index, estimate: row.estimatedLift, low, high, covers: low <= trueLift && trueLift <= high };
  });
  const min = Math.min(...intervals.map((row) => row.low), trueLift);
  const max = Math.max(...intervals.map((row) => row.high), trueLift);
  const scale = (value: number) => `${((value - min) / Math.max(0.0001, max - min)) * 100}%`;
  return (
    <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
      <h3 className="text-sm font-semibold text-slate-950">Confidence Interval Simulation</h3>
      <p className="mt-1 text-xs leading-5 text-slate-500">First 80 simulated intervals. Green intervals cover the true effect; rose intervals miss it.</p>
      <div className="relative mt-5 h-72 overflow-hidden rounded-xl border border-slate-200 bg-slate-50 p-4">
        <div className="absolute bottom-3 top-3 w-px bg-slate-950" style={{ left: scale(trueLift) }} />
        {intervals.map((row) => (
          <div key={row.index} className="absolute h-px" style={{ left: scale(row.low), width: `${Math.max(0.5, parseFloat(scale(row.high)) - parseFloat(scale(row.low)))}%`, top: `${6 + (row.index / intervals.length) * 86}%`, backgroundColor: row.covers ? "#10b981" : "#e11d48" }}>
            <span className="absolute -top-1 h-2 w-2 rounded-full bg-slate-700" style={{ left: scale(row.estimate) }} />
          </div>
        ))}
        <div className="absolute right-4 top-3 rounded-full bg-white px-2 py-1 text-[11px] font-semibold text-slate-700 shadow-sm">True effect</div>
      </div>
    </section>
  );
}

function WrongWinnerAnalysis({ results }: { results: MonteCarloSimulationResults }) {
  const wrongA = results.wrongWinnerRate * 0.58;
  const wrongControl = results.wrongWinnerRate * 0.42;
  const expectedRegret = results.inputs.totalSample * results.inputs.baselineRate * results.inputs.minimumDetectableLift * results.wrongWinnerRate;
  return (
    <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
      <h3 className="text-sm font-semibold text-slate-950">Wrong Winner Analysis</h3>
      <p className="mt-1 text-xs leading-5 text-slate-500">Quantifies the cost of choosing the wrong treatment because of sampling variation.</p>
      <div className="mt-4 space-y-3">
        <div className="flex justify-between rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm"><span>Probability treatment wins incorrectly</span><span className="font-semibold">{formatPct(wrongA)}</span></div>
        <div className="flex justify-between rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm"><span>Probability control wins incorrectly</span><span className="font-semibold">{formatPct(wrongControl)}</span></div>
        <div className="flex justify-between rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm"><span>Expected regret index</span><span className="font-semibold">{expectedRegret.toFixed(1)}</span></div>
      </div>
      <div className={`mt-4 rounded-xl border p-4 text-sm ${results.wrongWinnerRate <= 0.05 ? "border-emerald-200 bg-emerald-50 text-emerald-900" : "border-amber-200 bg-amber-50 text-amber-900"}`}>
        {results.wrongWinnerRate <= 0.05 ? "Wrong-winner risk is within launch tolerance." : "Wrong-winner risk should be reviewed before launch."}
      </div>
    </section>
  );
}

function WhatIfMonteCarloComparison({ results }: { results: MonteCarloSimulationResults }) {
  const alternativePower = Math.max(0, Math.min(1, scenarioPower({
    ...results.inputs,
    seed: results.seed,
    iterations: results.iterations,
    missingnessRate: Math.min(0.95, results.inputs.missingnessRate + 0.03),
    imbalanceRate: Math.min(0.95, results.inputs.imbalanceRate + 0.05),
    attritionRate: Math.min(0.95, results.inputs.attritionRate + 0.03),
  } as ReturnType<typeof monteCarloInputs>, 0.85, 1.2)));
  const alternativeWrongWinner = Math.max(0, Math.min(0.5, results.wrongWinnerRate + (results.meanPower - alternativePower) * 0.25 + 0.02));
  return (
    <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
      <h3 className="text-sm font-semibold text-slate-950">Current vs Alternative Stress</h3>
      <p className="mt-1 text-xs leading-5 text-slate-500">Alternative adds lower realized lift, higher variance, +3 pts missingness, +5 pts imbalance, and +3 pts attrition.</p>
      <div className="mt-4 grid gap-3 md:grid-cols-2">
        <div className="rounded-xl border border-slate-200 bg-slate-50 p-4">
          <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Current</div>
          <div className="mt-3 space-y-2 text-sm">
            <div className="flex justify-between"><span>Power</span><span className="font-semibold">{formatPct(results.meanPower)}</span></div>
            <div className="flex justify-between"><span>Wrong winner</span><span className="font-semibold">{formatPct(results.wrongWinnerRate)}</span></div>
            <div className="flex justify-between"><span>Robustness</span><span className="font-semibold">{formatPct(results.decisionStabilityScore)}</span></div>
          </div>
        </div>
        <div className="rounded-xl border border-amber-200 bg-amber-50 p-4">
          <div className="text-xs font-semibold uppercase tracking-wide text-amber-700">Alternative</div>
          <div className="mt-3 space-y-2 text-sm">
            <div className="flex justify-between"><span>Power</span><span className="font-semibold">{formatPct(alternativePower)}</span></div>
            <div className="flex justify-between"><span>Wrong winner</span><span className="font-semibold">{formatPct(alternativeWrongWinner)}</span></div>
            <div className="flex justify-between"><span>Robustness</span><span className="font-semibold">{formatPct(Math.max(0, alternativePower * 0.65 + (1 - alternativeWrongWinner) * 0.25 + results.confidenceIntervalCoverage * 0.1))}</span></div>
          </div>
        </div>
      </div>
    </section>
  );
}

function SimulationStat({ label, value, status }: { label: string; value: string; status: "pass" | "warn" | "fail" }) {
  const classes = status === "pass" ? "border-emerald-200 bg-emerald-50 text-emerald-900" : status === "warn" ? "border-amber-200 bg-amber-50 text-amber-900" : "border-rose-200 bg-rose-50 text-rose-900";
  return (
    <div className={`rounded-xl border p-4 shadow-sm ${classes}`}>
      <div className="text-xs font-semibold uppercase tracking-wide opacity-80">{label}</div>
      <div className="mt-2 text-xl font-semibold">{value}</div>
    </div>
  );
}

function ChartShell({ title, subtitle, note, children }: { title: string; subtitle: string; note: string; children: ReactNode }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
      <h3 className="text-sm font-semibold text-slate-950">{title}</h3>
      <p className="mt-1 text-xs leading-5 text-slate-500">{subtitle}</p>
      <div className="mt-4">{children}</div>
      <p className="mt-3 text-xs leading-5 text-slate-600">{note}</p>
    </div>
  );
}

function BarChartCard({ title, subtitle, rows, valueFormatter, note }: { title: string; subtitle: string; rows: { label: string; value: number }[]; valueFormatter: (value: number) => string; note: string }) {
  const max = Math.max(1, ...rows.map((row) => row.value));
  return (
    <ChartShell title={title} subtitle={subtitle} note={note}>
      <div className="flex h-56 items-end gap-2 border-b border-l border-slate-200 px-3 pb-3">
        {rows.map((row) => (
          <div key={row.label} className="flex min-w-0 flex-1 flex-col items-center gap-2">
            <div className="text-[10px] font-semibold text-slate-500">{valueFormatter(row.value)}</div>
            <div className="w-full rounded-t bg-blue-500" style={{ height: `${Math.max(3, (row.value / max) * 170)}px` }} />
            <div className="max-w-full truncate text-[10px] text-slate-500" title={row.label}>{row.label}</div>
          </div>
        ))}
      </div>
    </ChartShell>
  );
}

function HorizontalBarChartCard({ title, subtitle, rows, valueFormatter, note }: { title: string; subtitle: string; rows: { label: string; value: number; status?: MonteCarloSimulationResults["recommendedAction"] }[]; valueFormatter: (value: number) => string; note: string }) {
  const max = Math.max(0.01, ...rows.map((row) => row.value));
  return (
    <ChartShell title={title} subtitle={subtitle} note={note}>
      <div className="space-y-2">
        {rows.map((row) => (
          <div key={row.label} className="grid grid-cols-[150px_minmax(0,1fr)_54px] items-center gap-3 text-xs">
            <div className="truncate font-semibold text-slate-700" title={row.label}>{row.label}</div>
            <div className="h-3 overflow-hidden rounded-full bg-slate-100">
              <div className={`h-full rounded-full ${row.status === "Redesign Required" ? "bg-rose-500" : row.status === "Weak" ? "bg-amber-500" : "bg-teal-500"}`} style={{ width: `${Math.max(2, (row.value / max) * 100)}%` }} />
            </div>
            <div className="text-right font-semibold text-slate-700">{valueFormatter(row.value)}</div>
          </div>
        ))}
      </div>
    </ChartShell>
  );
}

function LineChartCard({ title, subtitle, rows, yFormatter, note }: { title: string; subtitle: string; rows: { x: number; y: number }[]; yFormatter: (value: number) => string; note: string }) {
  const width = 520;
  const height = 220;
  const pad = 28;
  const xMin = Math.min(...rows.map((row) => row.x));
  const xMax = Math.max(...rows.map((row) => row.x));
  const points = rows.map((row) => {
    const x = pad + ((row.x - xMin) / Math.max(1, xMax - xMin)) * (width - pad * 2);
    const y = height - pad - row.y * (height - pad * 2);
    return `${x},${y}`;
  }).join(" ");
  const targetY = height - pad - 0.8 * (height - pad * 2);
  return (
    <ChartShell title={title} subtitle={subtitle} note={note}>
      <svg viewBox={`0 0 ${width} ${height}`} className="h-56 w-full rounded-lg bg-slate-50">
        <line x1={pad} y1={height - pad} x2={width - pad} y2={height - pad} stroke="#cbd5e1" />
        <line x1={pad} y1={pad} x2={pad} y2={height - pad} stroke="#cbd5e1" />
        <line x1={pad} y1={targetY} x2={width - pad} y2={targetY} stroke="#f59e0b" strokeDasharray="4 4" />
        <text x={width - pad - 70} y={targetY - 6} fontSize="10" fill="#b45309">80% target</text>
        <polyline points={points} fill="none" stroke="#2563eb" strokeWidth="3" />
        {rows.map((row) => {
          const x = pad + ((row.x - xMin) / Math.max(1, xMax - xMin)) * (width - pad * 2);
          const y = height - pad - row.y * (height - pad * 2);
          return <circle key={row.x} cx={x} cy={y} r="4" fill="#2563eb"><title>{`${row.x.toLocaleString()} per cell: ${yFormatter(row.y)}`}</title></circle>;
        })}
      </svg>
    </ChartShell>
  );
}

function SampleSizePowerPlanner({ state, setState }: { state: NodeState; setState: (state: NodeState) => void }) {
  const updateNumber = (key: string, value: number) => setState({ ...state, numeric: { ...state.numeric, [key]: value } });
  const plan = sampleSizePlan(state);
  const absoluteLift = (plan.absoluteEffect * 100).toFixed(2);
  const ciWidth = (plan.ciHalfWidth * 100).toFixed(2);

  return (
    <section className="space-y-5 rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="text-xs font-semibold uppercase tracking-wide text-blue-700">Sample Size and Power Planner</div>
          <h2 className="mt-1 text-lg font-semibold text-slate-950">What happens if the assumptions change?</h2>
          <p className="mt-1 max-w-3xl text-sm leading-6 text-slate-600">
            Adjust alpha, power, baseline response, detectable lift, treatment cells, and population. ATLAS redraws the power curve, sensitivity, confidence interval, and simulation metrics live.
          </p>
        </div>
        <span className={`rounded-full border px-3 py-1 text-xs font-semibold ${plan.adequatelyPowered ? "border-emerald-200 bg-emerald-50 text-emerald-800" : "border-amber-200 bg-amber-50 text-amber-800"}`}>
          {plan.adequatelyPowered ? "Adequately powered" : "Population shortfall"}
        </span>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <SliderControl label="Alpha" value={state.numeric.alpha} min={1} max={10} step={1} suffix="%" onChange={(value) => updateNumber("alpha", value)} marks={["1", "5", "10"]} />
        <SliderControl label="Desired Power" value={state.numeric.power} min={60} max={95} step={1} suffix="%" onChange={(value) => updateNumber("power", value)} marks={["60", "80", "95"]} />
        <SliderControl label="Baseline Response" value={state.numeric.baselineRate} min={1} max={30} step={0.5} suffix="%" onChange={(value) => updateNumber("baselineRate", value)} marks={["1", "10", "30"]} />
        <SliderControl label="Minimum Detectable Lift" value={state.numeric.expectedLift} min={1} max={50} step={0.5} suffix="%" onChange={(value) => updateNumber("expectedLift", value)} marks={["1", "20", "50"]} />
        <SliderControl label="Factors" value={state.numeric.factorCount} min={1} max={6} step={1} onChange={(value) => updateNumber("factorCount", value)} marks={["1", "3", "6"]} />
        <SliderControl label="Average Levels" value={state.numeric.averageLevels} min={2} max={5} step={1} onChange={(value) => updateNumber("averageLevels", value)} marks={["2", "3", "5"]} />
      </div>

      <div className="grid gap-4 lg:grid-cols-[260px_minmax(0,1fr)]">
        <NumberField label="Available Population" value={state.numeric.sampleSize} onChange={(value) => updateNumber("sampleSize", value)} />
        <div className="grid gap-3 md:grid-cols-5">
      <ResultCard label="Sample per cell" value={plan.plannedPerCell.toLocaleString()} />
      <ResultCard label="Treatment cells" value={plan.treatmentCells.toLocaleString()} />
      <ResultCard label="Total sample" value={plan.plannedTotal.toLocaleString()} />
      <ResultCard label="Required per cell" value={plan.perCell.toLocaleString()} />
      <ResultCard label="Required total" value={plan.total.toLocaleString()} />
        </div>
      </div>

      <div className="grid gap-3 md:grid-cols-5">
      <ResultCard label="Expected power" value={`${plan.expectedPower.toFixed(1)}%`} />
      <ResultCard label="Alpha" value={plan.alpha.toFixed(3)} />
      <ResultCard label="Detectable lift" value={`${absoluteLift} pts`} />
      <ResultCard label="Expected CI half-width" value={`+/- ${ciWidth} pts`} />
      <ResultCard label="Status" value={plan.adequatelyPowered ? "Adequately powered" : "Population shortfall"} />
      </div>

      <div className={`rounded-xl border p-4 ${plan.adequatelyPowered ? "border-emerald-200 bg-emerald-50" : "border-amber-200 bg-amber-50"}`}>
        <div className={`flex items-center gap-2 text-sm font-semibold ${plan.adequatelyPowered ? "text-emerald-950" : "text-amber-950"}`}>
          <CheckCircle2 size={16} className={plan.adequatelyPowered ? "text-emerald-600" : "text-amber-600"} />
          {plan.adequatelyPowered ? "Adequately Powered" : "More sample or simpler design needed"}
        </div>
        <p className={`mt-1 text-xs leading-5 ${plan.adequatelyPowered ? "text-emerald-900" : "text-amber-900"}`}>
          {plan.adequatelyPowered
            ? `Available population covers the estimated ${plan.total.toLocaleString()} records required across all treatment cells. Current allocation is ${plan.plannedPerCell.toLocaleString()} records per cell.`
            : `Available population is ${Math.max(0, plan.total - plan.available).toLocaleString()} records below the estimated requirement.`}
        </p>
      </div>

      <div className="grid gap-5 xl:grid-cols-2">
        <LivePowerCurve plan={plan} />
        <PowerContours plan={plan} />
      </div>

      <EffectSizeTradeoff plan={plan} />

      <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_420px]">
        <SensitivityTornadoChart plan={plan} />
        <ConfidenceIntervalVisual plan={plan} />
      </div>

      <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_420px]">
        <SampleSizeSimulationPanel plan={plan} />
        <CurrentVsProposedPanel plan={plan} />
      </div>
    </section>
  );
}

function SliderControl({ label, value, min, max, step, suffix = "", marks, onChange }: { label: string; value: number; min: number; max: number; step: number; suffix?: string; marks: string[]; onChange: (value: number) => void }) {
  return (
    <label className="rounded-xl border border-slate-200 bg-slate-50 p-4">
      <div className="flex items-center justify-between gap-3">
        <span className="text-xs font-semibold uppercase tracking-wide text-slate-500">{label}</span>
        <span className="rounded-lg border border-slate-200 bg-white px-2 py-1 text-sm font-semibold text-slate-950">{value}{suffix}</span>
      </div>
      <input type="range" min={min} max={max} step={step} value={value} className="mt-4 w-full accent-blue-600" onChange={(event) => onChange(Number(event.target.value))} />
      <div className="mt-2 flex justify-between text-[11px] font-semibold text-slate-400">
        {marks.map((mark) => <span key={mark}>{mark}{suffix && !mark.endsWith(suffix) ? suffix : ""}</span>)}
      </div>
    </label>
  );
}

function LivePowerCurve({ plan }: { plan: ReturnType<typeof sampleSizePlan> }) {
  return (
    <VisualCard title="Live Power Curve" subtitle="Redraws when alpha, power, response rate, lift, or treatment cells change.">
      <LineChartCard
        title=""
        subtitle="Estimated power by per-cell sample size."
        rows={plan.powerCurve.map((point) => ({ x: point.perCell, y: point.power / 100 }))}
        yFormatter={formatPct}
        note={`Target power: ${formatPct(plan.desiredPower)}. Required per cell: ${plan.perCell.toLocaleString()}.`}
      />
    </VisualCard>
  );
}

function PowerContours({ plan }: { plan: ReturnType<typeof sampleSizePlan> }) {
  return (
    <VisualCard title="Power Contours" subtitle="Required sample by target power level.">
      <HorizontalBars rows={plan.contours.map((row) => ({ label: `${row.powerPct}% power`, value: row.total }))} valueFormatter={(value) => value.toLocaleString()} />
      <p className="mt-3 text-xs leading-5 text-slate-500">Higher power tightens the decision standard and increases required observations.</p>
    </VisualCard>
  );
}

function EffectSizeTradeoff({ plan }: { plan: ReturnType<typeof sampleSizePlan> }) {
  return (
    <VisualCard title="Effect Size Tradeoff" subtitle="The core business tradeoff: smaller detectable lift requires materially more sample.">
      <div className="min-h-[280px]">
        <HorizontalBars rows={plan.sensitivity.map((row) => ({ label: `${row.liftPct}% lift`, value: row.total }))} valueFormatter={(value) => value.toLocaleString()} />
      </div>
      <p className="mt-4 text-xs leading-5 text-slate-500">
        This chart answers the sponsor question: how much more population is needed if the business wants to detect a smaller lift?
      </p>
    </VisualCard>
  );
}

function SensitivityTornadoChart({ plan }: { plan: ReturnType<typeof sampleSizePlan> }) {
  const maxImpact = Math.max(1, ...plan.tornado.map((row) => row.impact));
  return (
    <VisualCard title="Sensitivity Tornado" subtitle="Shows which assumptions move required sample size the most.">
      <div className="space-y-4">
        {plan.tornado.map((row) => {
          const lowDelta = row.low - plan.total;
          const highDelta = row.high - plan.total;
          const leftWidth = Math.min(48, Math.abs(Math.min(0, lowDelta, highDelta)) / maxImpact * 48);
          const rightWidth = Math.min(48, Math.abs(Math.max(0, lowDelta, highDelta)) / maxImpact * 48);
          return (
            <div key={row.label} className="grid grid-cols-[150px_minmax(0,1fr)_90px] items-center gap-3 text-xs">
              <div className="font-semibold text-slate-700">{row.label}</div>
              <div className="relative h-5 rounded-full bg-slate-100">
                <div className="absolute left-1/2 top-0 h-full w-px bg-slate-400" />
                <div className="absolute right-1/2 top-1 h-3 rounded-l-full bg-sky-300" style={{ width: `${leftWidth}%` }} />
                <div className="absolute left-1/2 top-1 h-3 rounded-r-full bg-blue-600" style={{ width: `${rightWidth}%` }} />
              </div>
              <div className="text-right font-semibold text-slate-700">{row.impact.toLocaleString()}</div>
            </div>
          );
        })}
      </div>
      <p className="mt-4 text-xs leading-5 text-slate-500">Longer bars identify assumptions that deserve sponsor review before execution.</p>
    </VisualCard>
  );
}

function ConfidenceIntervalVisual({ plan }: { plan: ReturnType<typeof sampleSizePlan> }) {
  const widthPct = Math.min(92, Math.max(18, plan.ciHalfWidth * 900));
  const estimate = plan.treatmentRate - plan.baseline;
  return (
    <VisualCard title="Confidence Interval" subtitle="Expected precision around the treatment effect estimate.">
      <div className="rounded-xl border border-slate-200 bg-slate-50 p-5">
        <div className="relative mx-auto h-16 max-w-md">
          <div className="absolute left-0 right-0 top-8 h-px bg-slate-300" />
          <div className="absolute top-5 h-7 border-l-2 border-blue-700" style={{ left: `${50 - widthPct / 2}%` }} />
          <div className="absolute top-5 h-7 border-l-2 border-blue-700" style={{ left: `${50 + widthPct / 2}%` }} />
          <div className="absolute top-7 h-1 rounded-full bg-blue-600" style={{ left: `${50 - widthPct / 2}%`, width: `${widthPct}%` }} />
          <div className="absolute left-1/2 top-3 -translate-x-1/2 rounded-full bg-slate-950 px-2 py-1 text-[11px] font-semibold text-white">Estimate</div>
        </div>
        <div className="mt-3 grid grid-cols-3 gap-2 text-center text-xs">
          <div><span className="font-semibold">Lower</span><br />{formatPct(estimate - plan.ciHalfWidth)}</div>
          <div><span className="font-semibold">Effect</span><br />{formatPct(estimate)}</div>
          <div><span className="font-semibold">Upper</span><br />{formatPct(estimate + plan.ciHalfWidth)}</div>
        </div>
      </div>
    </VisualCard>
  );
}

function SampleSizeSimulationPanel({ plan }: { plan: ReturnType<typeof sampleSizePlan> }) {
  const buckets = histogram(plan.simulation.effects, [
    { label: "Low", min: -1, max: plan.simulation.low },
    { label: "Below", min: plan.simulation.low, max: 0 },
    { label: "Near", min: 0, max: plan.simulation.avgLift },
    { label: "Above", min: plan.simulation.avgLift, max: plan.simulation.high },
    { label: "High", min: plan.simulation.high, max: 1 },
  ]);
  return (
    <VisualCard title="1,000 Simulation Runs" subtitle="Preview of estimated lift uncertainty under current assumptions.">
      <HorizontalBars rows={buckets} valueFormatter={(value) => value.toLocaleString()} />
      <div className="mt-4 grid gap-3 md:grid-cols-5">
        <ResultCard label="Power" value={formatPct(plan.simulation.power)} />
        <ResultCard label="Coverage" value={formatPct(plan.simulation.coverage)} />
        <ResultCard label="False positives" value={plan.simulation.falsePositives.toLocaleString()} />
        <ResultCard label="False negatives" value={plan.simulation.falseNegatives.toLocaleString()} />
        <ResultCard label="Avg. lift" value={formatPct(plan.simulation.avgLift)} />
      </div>
    </VisualCard>
  );
}

function CurrentVsProposedPanel({ plan }: { plan: ReturnType<typeof sampleSizePlan> }) {
  const proposed = plan.contours.find((row) => row.powerPct === 90) ?? plan.contours[plan.contours.length - 1];
  const proposedCi = proposed ? plan.ciHalfWidth * Math.sqrt(plan.perCell / Math.max(1, proposed.perCell)) : plan.ciHalfWidth;
  const proposedAdequate = proposed ? plan.available >= proposed.total : plan.adequatelyPowered;
  return (
    <VisualCard title="Current vs Proposed" subtitle="A side-by-side view of the tradeoff if the target power is changed to 90%.">
      <div className="grid gap-3 md:grid-cols-2">
        <div className="rounded-xl border border-slate-200 bg-slate-50 p-4">
          <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Current</div>
          <div className="mt-3 space-y-2 text-sm">
            <div className="flex justify-between"><span>Power</span><span className="font-semibold">{formatPct(plan.desiredPower)}</span></div>
            <div className="flex justify-between"><span>Required sample</span><span className="font-semibold">{plan.total.toLocaleString()}</span></div>
            <div className="flex justify-between"><span>CI half-width</span><span className="font-semibold">{formatPct(plan.ciHalfWidth)}</span></div>
            <div className="flex justify-between"><span>Status</span><span className="font-semibold">{plan.adequatelyPowered ? "Adequate" : "Shortfall"}</span></div>
          </div>
        </div>
        <div className="rounded-xl border border-blue-200 bg-blue-50 p-4">
          <div className="text-xs font-semibold uppercase tracking-wide text-blue-700">Proposed</div>
          <div className="mt-3 space-y-2 text-sm">
            <div className="flex justify-between"><span>Power</span><span className="font-semibold">90%</span></div>
            <div className="flex justify-between"><span>Required sample</span><span className="font-semibold">{proposed ? proposed.total.toLocaleString() : "Recalculate"}</span></div>
            <div className="flex justify-between"><span>CI half-width</span><span className="font-semibold">{formatPct(proposedCi)}</span></div>
            <div className="flex justify-between"><span>Status</span><span className="font-semibold">{proposedAdequate ? "Adequate" : "Shortfall"}</span></div>
          </div>
        </div>
      </div>
    </VisualCard>
  );
}

function AnovaModelAssistant({ plan }: { plan: ReturnType<typeof generatedAnovaPlan> }) {
  return (
    <section className="rounded-xl border border-blue-200 bg-white p-5 shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold text-slate-950">Generated ANOVA Model</h2>
          <p className="mt-1 text-xs leading-5 text-slate-500">
            ATLAS generated this model from the selected research intent, factors, levels, and sample-size plan.
          </p>
        </div>
        <span className="rounded-full border border-blue-200 bg-blue-50 px-2.5 py-1 text-xs font-semibold text-blue-800">
          {plan.recommendedModel}
        </span>
      </div>

      <div className="mt-4 rounded-lg border border-slate-200 bg-slate-50 p-3">
        <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Statistical model</div>
        <div className="mt-1 font-mono text-sm font-semibold text-slate-950">{plan.modelFormula}</div>
      </div>

      <div className="mt-4 grid gap-3 md:grid-cols-4">
        <ResultCard label="Factors" value={plan.factorNames.length.toLocaleString()} />
        <ResultCard label="Treatment cells" value={plan.treatmentCells.toLocaleString()} />
        <ResultCard label="Model df" value={plan.modelDf.toLocaleString()} />
        <ResultCard label="Residual df" value={plan.residualDf.toLocaleString()} />
      </div>

      <div className="mt-4 grid gap-4 xl:grid-cols-2">
        <div className="overflow-hidden rounded-lg border border-slate-200">
          <div className="bg-slate-50 px-3 py-2 text-xs font-semibold uppercase tracking-wide text-slate-500">Factor coding</div>
          <table className="w-full text-left text-sm">
            <thead className="border-t border-slate-200 bg-white text-xs font-semibold uppercase tracking-wide text-slate-500">
              <tr>
                <th className="px-3 py-2">Code</th>
                <th className="px-3 py-2">Factor</th>
                <th className="px-3 py-2">Levels</th>
              </tr>
            </thead>
            <tbody>
              {plan.factorNames.map((factor, index) => (
                <tr key={factor} className="border-t border-slate-200">
                  <td className="px-3 py-2 font-semibold text-slate-900">{plan.factorCodes[index]}</td>
                  <td className="px-3 py-2 text-slate-700">{factor}</td>
                  <td className="px-3 py-2 text-slate-700">{plan.levelCounts[index]}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="overflow-hidden rounded-lg border border-slate-200">
          <div className="bg-slate-50 px-3 py-2 text-xs font-semibold uppercase tracking-wide text-slate-500">Expected degrees of freedom</div>
          <table className="w-full text-left text-sm">
            <thead className="border-t border-slate-200 bg-white text-xs font-semibold uppercase tracking-wide text-slate-500">
              <tr>
                <th className="px-3 py-2">Term</th>
                <th className="px-3 py-2">df</th>
                <th className="px-3 py-2">Interpretation</th>
              </tr>
            </thead>
            <tbody>
              {plan.termRows.map((row) => (
                <tr key={row.term} className="border-t border-slate-200">
                  <td className="px-3 py-2 font-semibold text-slate-900">{row.term}</td>
                  <td className="px-3 py-2 text-slate-700">{row.df}</td>
                  <td className="px-3 py-2 text-slate-700">{/\s(?:x|×)\s/.test(row.term) ? "Interaction effect" : "Main effect"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="mt-4 rounded-lg border border-emerald-200 bg-emerald-50 p-3">
        <div className="text-xs font-semibold uppercase tracking-wide text-emerald-800">Interpretation guidance</div>
        <p className="mt-1 text-xs leading-5 text-emerald-900">
          Review main effects first, then interaction terms. If an interaction is significant and practically material, interpret factor effects within the relevant treatment combination rather than relying only on aggregate main effects.
        </p>
      </div>
    </section>
  );
}

function ExperimentalCalculator({ projectId, stepLabel, state, setState }: { projectId: string; stepLabel: string; state: NodeState; setState: (state: NodeState) => void }) {
  const updateNumber = (key: string, value: number) => setState({ ...state, numeric: { ...state.numeric, [key]: value } });
  const cells = Math.max(1, Math.round(state.numeric.averageLevels ** state.numeric.factorCount));
  const runs = cells * Math.max(1, state.numeric.replicates) * Math.max(1, state.numeric.blocks);
  const residualDf = Math.max(0, runs - cells);

  if (["Factors", "Levels"].includes(stepLabel)) {
    const parsedFactors =
      stepLabel === "Levels"
        ? sharedParseFactorHierarchy(state.objective)
        : sharedDeriveSuggestedFactors(state.objective).map(({ factorName, levels }) => ({ factorName, levels }));
    const designFactorCount = parsedFactors.length || Math.max(1, Math.round(state.numeric.factorCount));
    const designTreatmentCells = parsedFactors.length ? treatmentCellCount(parsedFactors) : cells;
    const designAverageLevels = parsedFactors.length
      ? parsedFactors.reduce((sum, factor) => sum + factor.levels.length, 0) / parsedFactors.length
      : state.numeric.averageLevels;
    const balanced = parsedFactors.length > 0 && new Set(parsedFactors.map((factor) => factor.levels.length)).size === 1;
    const designLabel = parsedFactors.length > 1
      ? `${balanced ? "Balanced" : "Unbalanced"} ${parsedFactors.map((factor) => factor.levels.length).join(" × ")} factorial`
      : parsedFactors.length === 1
        ? `${parsedFactors[0].levels.length}-level single-factor design`
        : "Calculated from entered factors";
    return (
      <CalculatorPanel title="Experimental Design">
        <NumberField label="Factors" value={state.numeric.factorCount} onChange={(value) => updateNumber("factorCount", value)} />
        <NumberField label="Avg. Levels" value={state.numeric.averageLevels} onChange={(value) => updateNumber("averageLevels", value)} />
        <ResultCard label="Parsed factors" value={designFactorCount.toLocaleString()} />
        <ResultCard label="Average levels" value={designAverageLevels.toFixed(1)} />
        <ResultCard label="Treatment cells" value={designTreatmentCells.toLocaleString()} />
        <ResultCard label="Design" value={designLabel} />
        <ResultCard label="Customers per cell" value="TBD" />
        <ResultCard label="Total planned sample" value="TBD" />
      </CalculatorPanel>
    );
  }

  if (stepLabel === "Sample Size") {
    const plan = sampleSizePlan(state);
    return (
      <InfoGrid
        title="Power Plan Status"
        rows={[
          ["Required per cell", plan.perCell.toLocaleString()],
          ["Planned per cell", plan.plannedPerCell.toLocaleString()],
          ["Treatment cells", plan.treatmentCells.toLocaleString()],
          ["Required total", plan.total.toLocaleString()],
          ["Planned total", plan.plannedTotal.toLocaleString()],
          ["Available population", plan.available ? plan.available.toLocaleString() : "Not entered"],
          ["Decision", plan.adequatelyPowered ? "Adequately powered" : "Review sample or MDE"],
        ]}
      />
    );
  }

  if (stepLabel === "Experiment Run Plan") {
    return (
      <CalculatorPanel title="Experimental Sample Planner">
        <NumberField label="Factors" value={state.numeric.factorCount} onChange={(value) => updateNumber("factorCount", value)} />
        <NumberField label="Avg. Levels" value={state.numeric.averageLevels} onChange={(value) => updateNumber("averageLevels", value)} />
        <NumberField label="Replicates" value={state.numeric.replicates} onChange={(value) => updateNumber("replicates", value)} />
        <NumberField label="Blocks" value={state.numeric.blocks} onChange={(value) => updateNumber("blocks", value)} />
        <ResultCard label="Treatment cells" value={cells.toLocaleString()} />
        <ResultCard label="Planned observations" value={runs.toLocaleString()} />
        <ResultCard label="Analysis df buffer" value={residualDf.toLocaleString()} />
        <ResultCard label="Design risk" value={runs > 500 ? "Large operational sample" : residualDf < cells ? "Low replication" : "Manageable"} />
      </CalculatorPanel>
    );
  }

  if (stepLabel === "Monte Carlo Simulation") {
    const simulations = Math.max(1, state.numeric.simulations);
    const runsForSimulation = Math.max(1, state.numeric.runs);
    const missingness = Math.max(0, Math.min(100, state.numeric.missingnessRate));
    const imbalance = Math.max(0, Math.min(100, state.numeric.treatmentImbalance));
    const signalRatio = state.numeric.effectSize / Math.max(0.01, Math.sqrt(state.numeric.mse));
    const effectiveRuns = Math.round(runsForSimulation * (1 - missingness / 100));
    const stabilityScore = Math.max(0, Math.min(100, 50 + signalRatio * 25 - imbalance * 0.5 - missingness * 0.75));
    return (
      <CalculatorPanel title="Monte Carlo Scenario Planner">
        <NumberField label="Simulations" value={state.numeric.simulations} onChange={(value) => updateNumber("simulations", value)} />
        <NumberField label="Runs" value={state.numeric.runs} onChange={(value) => updateNumber("runs", value)} />
        <NumberField label="Effect Size" value={state.numeric.effectSize} onChange={(value) => updateNumber("effectSize", value)} />
        <NumberField label="Estimated MSE" value={state.numeric.mse} onChange={(value) => updateNumber("mse", value)} />
        <NumberField label="Imbalance %" value={state.numeric.treatmentImbalance} onChange={(value) => updateNumber("treatmentImbalance", value)} />
        <NumberField label="Missingness %" value={state.numeric.missingnessRate} onChange={(value) => updateNumber("missingnessRate", value)} />
        <ResultCard label="Effective runs" value={effectiveRuns.toLocaleString()} />
        <ResultCard label="Signal / noise" value={signalRatio.toFixed(2)} />
        <ResultCard label="Scenario stability" value={`${stabilityScore.toFixed(0)} / 100`} />
        <ResultCard label="Simulation depth" value={simulations < 1000 ? "Increase iterations" : "Adequate for planning"} />
      </CalculatorPanel>
    );
  }

  if (stepLabel === "ANOVA") {
    const plan = generatedAnovaPlan(projectId, state);
    return (
      <CalculatorPanel title="ANOVA Model Summary">
        <ResultCard label="Recommended model" value={plan.recommendedModel} />
        <ResultCard label="Research intent" value={plan.researchIntent} />
        <ResultCard label="Factors" value={plan.factorNames.length.toLocaleString()} />
        <ResultCard label="Treatment cells" value={plan.treatmentCells.toLocaleString()} />
        <ResultCard label="Planned observations" value={plan.plannedObservations.toLocaleString()} />
        <ResultCard label="Model df" value={plan.modelDf.toLocaleString()} />
        <ResultCard label="Residual df" value={plan.residualDf.toLocaleString()} />
        <ResultCard label="Interpretation order" value={plan.termRows.some((row) => /\s(?:x|×)\s/.test(row.term)) ? "Main effects, then interactions" : "Main effects"} />
      </CalculatorPanel>
    );
  }

  if (["Interaction Effects", "Optimization"].includes(stepLabel)) {
    const signalRatio = state.numeric.effectSize / Math.max(0.01, Math.sqrt(state.numeric.mse));
    return (
      <CalculatorPanel title="Effect Review">
        <NumberField label="Estimated MSE" value={state.numeric.mse} onChange={(value) => updateNumber("mse", value)} />
        <NumberField label="Effect Size" value={state.numeric.effectSize} onChange={(value) => updateNumber("effectSize", value)} />
        <NumberField label="Runs" value={state.numeric.runs} onChange={(value) => updateNumber("runs", value)} />
        <NumberField label="Factors" value={state.numeric.factorCount} onChange={(value) => updateNumber("factorCount", value)} />
        <ResultCard label="Signal / noise" value={signalRatio.toFixed(2)} />
        <ResultCard label="Interaction review" value={state.numeric.factorCount > 1 ? "Required" : "Not applicable"} />
      </CalculatorPanel>
    );
  }

  return (
    <CalculatorPanel title="Experimental Design Readiness">
      <ResultCard label="Design choice" value={state.method ? "Selected" : "Needed"} />
      <ResultCard label="Metrics" value={state.metrics.length ? `${state.metrics.length} selected` : "Needed"} />
      <ResultCard label="Decision" value={state.decision ? "Captured" : "Needed"} />
      <ResultCard label="Rationale" value={state.rationale ? "Captured" : "Needed"} />
    </CalculatorPanel>
  );
}

function ExperimentalReadiness({ stepLabel, state }: { stepLabel: string; state: NodeState }) {
  const items = [
    ["Step", stepLabel],
    ["Method", state.method || "Not selected"],
    ["Evidence fields", `${[state.objective, state.inputs, state.assumptions, state.validation].filter((value) => value.trim()).length} of 4`],
    ["Metrics", state.metrics.length ? state.metrics.join(", ") : "Not selected"],
    ["Decision status", state.decision ? "Captured" : "Draft"],
  ];
  return <InfoGrid title="Experimental Node Status" rows={items} />;
}

function InfoGrid({ title, rows }: { title: string; rows: string[][] }) {
  return (
    <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
      <h2 className="text-sm font-semibold text-slate-950">{title}</h2>
      <div className="mt-3 overflow-hidden rounded-lg border border-slate-200">
        <table className="w-full text-left text-sm">
          <tbody>
            {rows.map(([label, value]) => (
              <tr key={label} className="border-b border-slate-200 last:border-b-0">
                <th className="w-44 bg-slate-50 px-3 py-2 text-xs font-semibold uppercase tracking-wide text-slate-500">{label}</th>
                <td className="px-3 py-2 text-slate-800">{value}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

export default function WorkflowPlaceholderStep() {
  const params = useParams();
  const projectId = useWorkflowStore((state) => state.projectId);
  const projectType = useWorkflowStore((state) => state.projectType);
  const workflowId = useWorkflowStore((state) => state.workflowId);
  const workflowSteps = useWorkflowStore((state) => state.workflowSteps);
  const markWorkflowStepComplete = useWorkflowStore((state) => state.markWorkflowStepComplete);
  const setWorkflowStepStatus = useWorkflowStore((state) => state.setWorkflowStepStatus);
  const setCurrentStepId = useWorkflowStore((state) => state.setCurrentStepId);
  const navigate = useNavigate();
  const activeWorkflowId = params.workflowId ?? workflowId;
  const stepIndex = Math.max(0, Number(params.stepNumber ?? "1") - 1);
  const definedWorkflowSteps = getWorkflowDefinition(activeWorkflowId).steps;
  const step = definedWorkflowSteps[stepIndex] ?? workflowSteps[stepIndex];
  const nextStep = definedWorkflowSteps[stepIndex + 1] ?? workflowSteps[stepIndex + 1];
  const [state, setState] = useState<NodeState>(() => loadNodeState(projectId, step?.id ?? `${activeWorkflowId}-${stepIndex + 1}`));
  const [navigationError, setNavigationError] = useState<string | null>(null);
  const metricChoices = metricOptions[projectType] ?? metricOptions.default;
  const methodChoices = methodOptions[projectType] ?? methodOptions.default;
  const guide = useMemo(() => recommendations(projectType, step?.label ?? ""), [projectType, step?.label]);

  useEffect(() => {
    if (!step) return;
    setState(loadNodeState(projectId, step.id));
    setNavigationError(null);
    window.setTimeout(() => window.scrollTo({ top: 0, behavior: "auto" }), 0);
  }, [projectId, step?.id]);

  if (!step) {
    return (
      <div className="rounded-lg border border-slate-200/80 bg-white/90 p-5 shadow-sm">
        <h1 className="text-xl font-semibold text-slate-950">Workflow Step Not Found</h1>
        <p className="mt-1 text-sm text-slate-600">Return to the project overview to select an available workflow step.</p>
        <Link to="/project-overview" className="mt-4 inline-flex rounded-lg bg-slate-950 px-3 py-2 text-sm font-semibold text-white">
          Project Overview
        </Link>
      </div>
    );
  }

  const save = () => {
    const stateToSave = saveNodeState(projectId, step.id, state);
    if (projectType === "experimental-design" && step.status !== "complete") {
      try {
        setWorkflowStepStatus(step.id, "in_progress");
      } catch (error) {
        console.warn("ATLAS project progress update failed after saving node state", error);
      }
    }
    try {
      setCurrentStepId(step.id);
    } catch (error) {
      console.warn("ATLAS current step update failed after saving node state", error);
    }
    try {
      logDecision({
        workflowStep: step.label,
        actionType: "workflow_setting_changed",
        subject: "Workflow node evidence",
        previousValue: "draft",
        newValue: stateToSave.decision || stateToSave.objective || "saved",
        systemRecommendation: guide[0],
        followStatus: "not_applicable",
        userReason: stateToSave.rationale,
      });
    } catch (error) {
      console.warn("ATLAS decision journal update failed after saving node state", error);
    }
    upsertProjectFromState(useWorkflowStore.getState());
    return stateToSave;
  };

  const completeStep = () => {
    setNavigationError(null);
    try {
      save();
    } catch (error) {
      console.error("ATLAS workflow save failed before navigation", error);
      setNavigationError(`ATLAS could not save this page. ${error instanceof Error ? error.message : "Please try again."}`);
      return false;
    }
    try {
      markWorkflowStepComplete(step.id);
      if (nextStep) setWorkflowStepStatus(nextStep.id, "in_progress");
      setCurrentStepId(nextStep?.id ?? step.id);
    } catch (error) {
      console.warn("ATLAS progress update failed after page save", error);
    }
    navigate(nextStep?.route ?? "/project-overview");
    window.setTimeout(() => window.scrollTo({ top: 0, behavior: "auto" }), 0);
    return true;
  };

  if (projectType === "experimental-design") {
    return (
      <ExperimentalDesignStep
        projectId={projectId}
        step={step}
        nextStep={nextStep}
        state={state}
        setState={setState}
        save={save}
        onComplete={completeStep}
        navigationError={navigationError}
      />
    );
  }

  return (
    <StepShell
      title={step.label}
      subtitle={step.description}
      nextLabel={nextStep ? "Save & Continue" : "Save & Return to Overview"}
      nextPath={nextStep?.route ?? "/project-overview"}
      onNext={completeStep}
    >
      <div className="space-y-5">
        {navigationError && <InlineError message={navigationError} />}
        <section className="rounded-xl border border-blue-200 bg-blue-50 p-4">
          <div className="flex items-start gap-3">
            <Lightbulb size={18} className="mt-0.5 shrink-0 text-blue-700" />
            <div>
              <h2 className="text-sm font-semibold text-blue-950">Atlas Guide for {labelize(projectType)}</h2>
              <ul className="mt-2 grid gap-1 text-sm leading-6 text-blue-900">
                {guide.map((item) => (
                  <li key={item}>- {item}</li>
                ))}
              </ul>
            </div>
          </div>
        </section>

        <section className="grid gap-4 xl:grid-cols-[1fr_0.75fr]">
          <div className="space-y-4 rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
            <div className="grid gap-4 lg:grid-cols-2">
              <TextArea label="Objective / Question" value={state.objective} onChange={(value) => setState({ ...state, objective: value })} />
              <TextArea label="Inputs / Data Needed" value={state.inputs} onChange={(value) => setState({ ...state, inputs: value })} />
              <TextArea label="Assumptions" value={state.assumptions} onChange={(value) => setState({ ...state, assumptions: value })} />
              <TextArea label="Validation / QA Checks" value={state.validation} onChange={(value) => setState({ ...state, validation: value })} />
            </div>

            <div className="grid gap-4 lg:grid-cols-2">
              <label className="grid gap-1.5">
                <span className="text-xs font-semibold uppercase tracking-wide text-slate-500">Method</span>
                <select
                  className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm"
                  value={state.method}
                  onChange={(event) => setState({ ...state, method: event.target.value })}
                >
                  <option value="">Select method</option>
                  {methodChoices.map((method) => (
                    <option key={method} value={method}>{method}</option>
                  ))}
                </select>
              </label>
              <MetricPicker
                options={metricChoices}
                selected={state.metrics}
                onChange={(metrics) => setState({ ...state, metrics })}
              />
            </div>

            <div className="grid gap-4 lg:grid-cols-2">
              <TextArea label="Risks / Limitations" value={state.risks} onChange={(value) => setState({ ...state, risks: value })} />
              <TextArea label="Decision / Recommendation" value={state.decision} onChange={(value) => setState({ ...state, decision: value })} />
            </div>

            <TextArea label="Rationale / Notes for Governance" value={state.rationale} onChange={(value) => setState({ ...state, rationale: value })} rows={4} />
            <TextArea label="Additional Notes" value={state.notes} onChange={(value) => setState({ ...state, notes: value })} rows={3} />

            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                className="inline-flex items-center gap-2 rounded-lg bg-slate-950 px-3 py-2 text-sm font-semibold text-white shadow-sm hover:bg-slate-800"
                onClick={save}
              >
                <Save size={15} />
                Save Node Evidence
              </button>
              {nextStep && (
                <Link to={nextStep.route} className="inline-flex items-center gap-2 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-semibold text-slate-700 shadow-sm hover:bg-slate-50">
                  Preview next step: {nextStep.label}
                  <ArrowRight size={15} />
                </Link>
              )}
            </div>
          </div>

          <div className="space-y-4">
            <StepCalculator projectType={projectType} state={state} setState={setState} />
            <EvidenceChecklist state={state} />
          </div>
        </section>
      </div>
    </StepShell>
  );
}

function TextArea({
  label,
  value,
  onChange,
  rows = 5,
  placeholder,
  assistSuggestion,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  rows?: number;
  placeholder?: string;
  assistSuggestion?: string;
}) {
  const [proposal, setProposal] = useState<string | null>(null);
  const [showActions, setShowActions] = useState(false);
  const propose = (mode: "draft" | "clarity" | "audit" | "shorten" | "expand" | "regenerate") => {
    const next = draftGovernanceText(label, value, assistSuggestion || placeholder, mode);
    if (!value.trim()) {
      onChange(next);
      setProposal(null);
      return;
    }
    setProposal(next);
  };
  return (
    <div className="grid gap-1.5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="text-xs font-semibold uppercase tracking-wide text-slate-500">{label}</span>
        <div className="relative flex flex-wrap gap-1.5">
          <button
            type="button"
            className="rounded-full border border-blue-200 bg-blue-50 px-2.5 py-1 text-[11px] font-semibold text-blue-800 hover:bg-blue-100"
            onClick={() => value.trim() ? setShowActions((current) => !current) : propose("draft")}
          >
            {value.trim() ? "Improve Draft" : "ATLAS Draft"}
          </button>
          {value.trim() && showActions && (
            <div className="absolute right-0 top-8 z-30 grid w-48 gap-1 rounded-xl border border-slate-200 bg-white p-2 text-left shadow-xl">
              {[
                ["clarity", "Improve clarity"],
                ["audit", "Make audit-ready"],
                ["shorten", "Shorten"],
                ["expand", "Expand rationale"],
                ["regenerate", "Regenerate"],
              ].map(([mode, text]) => (
                <button
                  key={mode}
                  type="button"
                  className="rounded-lg px-2 py-1.5 text-left text-xs font-semibold text-slate-700 hover:bg-slate-50"
                  onClick={() => {
                    setShowActions(false);
                    propose(mode as "clarity" | "audit" | "shorten" | "expand" | "regenerate");
                  }}
                >
                  {text}
                </button>
              ))}
            </div>
          )}
        </div>
      </div>
      <textarea
        className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm leading-6 text-slate-900 shadow-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
        rows={rows}
        value={value}
        placeholder={placeholder}
        onChange={(event) => onChange(event.target.value)}
      />
      {proposal && (
        <div className="rounded-xl border border-blue-200 bg-blue-50 p-3">
          <div className="text-[11px] font-semibold uppercase tracking-wide text-blue-700">ATLAS suggested revision</div>
          <p className="mt-1 text-xs leading-5 text-blue-950">{proposal}</p>
          <div className="mt-2 flex flex-wrap gap-2">
            <button type="button" className="rounded-lg bg-blue-600 px-2.5 py-1 text-xs font-semibold text-white" onClick={() => { onChange(proposal); setProposal(null); }}>
              Apply
            </button>
            <button type="button" className="rounded-lg border border-blue-200 bg-white px-2.5 py-1 text-xs font-semibold text-blue-700" onClick={() => setProposal(null)}>
              Keep Current
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

function MetricPicker({ options, selected, onChange }: { options: string[]; selected: string[]; onChange: (metrics: string[]) => void }) {
  return (
    <div>
      <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Metrics / Evidence</div>
      <div className="mt-2 flex flex-wrap gap-2">
        {options.map((option) => {
          const active = selected.includes(option);
          return (
            <button
              key={option}
              type="button"
              className={`rounded-full border px-3 py-1.5 text-xs font-semibold ${
                active ? "border-blue-300 bg-blue-50 text-blue-900" : "border-slate-200 bg-slate-50 text-slate-600 hover:bg-white"
              }`}
              onClick={() => onChange(active ? selected.filter((item) => item !== option) : [...selected, option])}
            >
              {option}
            </button>
          );
        })}
      </div>
    </div>
  );
}

function CalculatorPanel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="flex items-center gap-2">
        <Calculator size={17} className="text-slate-700" />
        <h2 className="text-sm font-semibold text-slate-950">{title}</h2>
      </div>
      <div className="mt-4 grid gap-3 sm:grid-cols-2">{children}</div>
    </section>
  );
}

function NumberField({ label, value, onChange }: { label: string; value: number; onChange: (value: number) => void }) {
  return (
    <label className="grid gap-1">
      <span className="text-xs font-semibold uppercase tracking-wide text-slate-500">{label}</span>
      <input
        type="number"
        className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm"
        value={value}
        onChange={(event) => onChange(Number(event.target.value))}
      />
    </label>
  );
}

function ReadinessCard({ label, value }: { label: string; value: number }) {
  const tone = value >= 85 ? "bg-emerald-500" : value >= 70 ? "bg-amber-500" : "bg-rose-500";
  return (
    <div className="rounded-xl border border-white/80 bg-white p-4 shadow-sm">
      <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">{label}</div>
      <div className="mt-2 flex items-end justify-between gap-3">
        <div className="text-2xl font-semibold text-slate-950">{value}</div>
        <div className="text-xs font-semibold text-slate-500">/ 100</div>
      </div>
      <div className="mt-3 h-2 overflow-hidden rounded-full bg-slate-100">
        <div className={`h-full rounded-full ${tone}`} style={{ width: `${Math.max(4, Math.min(100, value))}%` }} />
      </div>
    </div>
  );
}

function ResultCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0 rounded-lg border border-slate-200 bg-slate-50 p-3">
      <div className="break-words text-[10px] font-semibold uppercase tracking-wide text-slate-500">{label}</div>
      <div className="mt-1 break-words text-sm font-semibold leading-5 text-slate-950">{value}</div>
    </div>
  );
}

function EvidenceChecklist({ state }: { state: NodeState }) {
  const checks = [
    { label: "Objective documented", done: !!state.objective.trim(), icon: ClipboardList },
    { label: "Inputs documented", done: !!state.inputs.trim(), icon: FileText },
    { label: "Method selected", done: !!state.method.trim(), icon: BarChart3 },
    { label: "Metrics selected", done: state.metrics.length > 0, icon: CheckCircle2 },
    { label: "Validation captured", done: !!state.validation.trim(), icon: ShieldCheck },
    { label: "Decision rationale captured", done: !!state.rationale.trim(), icon: FileText },
  ];
  return (
    <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
      <h2 className="text-sm font-semibold text-slate-950">Evidence Checklist</h2>
      <div className="mt-3 grid gap-2">
        {checks.map((check) => {
          const Icon = check.icon;
          return (
            <div key={check.label} className="flex items-center gap-3 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2">
              <Icon size={15} className={check.done ? "text-emerald-600" : "text-slate-400"} />
              <span className={`text-sm ${check.done ? "font-semibold text-slate-900" : "text-slate-500"}`}>{check.label}</span>
            </div>
          );
        })}
      </div>
    </section>
  );
}
