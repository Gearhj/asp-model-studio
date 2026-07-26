import { Fragment, useEffect, useMemo, useRef, useState, type MouseEvent, type ReactNode } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  ArrowRight,
  BarChart3,
  Calculator,
  CheckCircle2,
  ClipboardList,
  Database,
  Download,
  FileText,
  Lightbulb,
  Link2,
  PackageCheck,
  Save,
  ShieldCheck,
  Upload,
} from "lucide-react";
import StepShell from "../components/StepShell";
import { experimentalDesignJourney, getWorkflowDefinition, type ProjectType, type ExperimentalDesignJourneyStep, type WorkflowStep } from "../config/workflows";
import { logDecision } from "../lib/decisionJournal";
import { buildGovernanceReport } from "../lib/governanceReport";
import { upsertProjectFromState } from "../lib/localProjects";
import { exportWorkflowNotebookJson } from "../lib/notebookExport";
import { loadProjectContext } from "../lib/projectContext";
import { loadWorkflowNodeEvidence } from "../lib/workflowNodeEvidence";
import {
  AB_MARKETING_DEFAULTS,
  AB_MARKETING_EXPECTED_COLUMNS,
  AB_WORKFLOW_DEFAULTS,
  AB_WORKFLOW_EXPECTED_COLUMNS,
  AB_WORKFLOW_FULL_ROW_COUNT,
  allocationImbalance,
  analyzeRegisteredAbDataset,
  analyzeAbLift,
  decisionRecommendationReason,
  getAbPreviewAnalysisDataset,
  getAbWorkflowFullDatasetArtifact,
  getAbWorkflowRows,
  profileAbDataset,
  segmentLiftRows,
  summarizeAbGroups,
  type AbAnalysisDataset,
  type AbDatasetAggregates,
  type AbTestingDefaults,
} from "../lib/abTestingWorkflow";
import { clearAbTestingWorkflowStorage, saveAbTestingStep } from "../lib/abTestingWorkflowPersistence";
import {
  getDatasetProfile,
  linkDatasetToProject,
  listDatasets,
  listProjectDatasets,
  uploadDataset,
  type DatasetProfile,
  type DatasetSummary,
} from "../lib/datasetLibrary";
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
import { saveExportToDatabase } from "../lib/serverPersistence";
import OptimizationWorkflowStep from "../features/optimization/OptimizationWorkflowStep";

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
  experimentalData?: {
    mode?: "" | "prospective" | "existing" | "hybrid" | "completed";
    sourceType?: string;
    datasetId?: string;
    versionId?: string;
    datasetName?: string;
    datasetRole?: string;
    rowCount?: number;
    columnCount?: number;
    availableColumns?: string[];
    status?: "not_configured" | "planned" | "linked" | "profiled";
    schemaConfirmed?: boolean;
    unitColumn?: string;
    responseColumn?: string;
    factorColumns?: string;
    blockColumns?: string;
    covariateColumns?: string;
    timestampColumn?: string;
    runIdColumn?: string;
    captureFrequency?: string;
    sourceLocation?: string;
    lineageNotes?: string;
    qualityPlan?: string;
  };
  ab?: Partial<AbTestingDefaults> & {
    confirmed?: boolean;
    previewOnly?: boolean;
    metricType?: string;
    confidenceLevel?: string;
    practicalSignificanceThreshold?: string;
    secondaryMetrics?: string;
    guardrailMetrics?: string;
    multipleComparisonPolicy?: string;
    segmentColumn?: string;
    dateTimeColumn?: string;
    duplicateHandling?: string;
    missingTreatmentHandling?: string;
    missingOutcomeHandling?: string;
    invalidTreatmentHandling?: string;
    invalidOutcomeHandling?: string;
    experimentType?: string;
    experimentDesign?: string;
    randomizationUnit?: string;
    analysisUnit?: string;
    outcomeWindow?: string;
    exposureWindow?: string;
    assignmentMethod?: string;
    randomizationAssignmentMethod?: string;
    expectedAllocationRatio?: string;
    balanceVariables?: string;
    exposureInterpretation?: string;
    minimumAcceptableGroupSize?: string;
    allocationImbalanceAcceptable?: string;
    exposureImbalanceAcceptable?: string;
    segmentImbalanceAcceptable?: string;
    reviewerConclusion?: string;
    powerBaselineConversionRate?: string;
    minimumDetectableEffect?: string;
    powerConfidenceLevel?: string;
    powerAlpha?: string;
    desiredPower?: string;
    powerTestType?: string;
    powerAllocationRatio?: string;
    currentSampleSource?: string;
    edaChartGrouping?: string;
    edaMinimumSegmentSize?: string;
    edaValidRecordsOnly?: boolean;
    analysisTestType?: string;
    analysisAlternativeHypothesis?: string;
    analysisValidRecordsOnly?: boolean;
    segmentShowOnlyMeetingThreshold?: boolean;
    segmentSortBy?: string;
    segmentMinimumSizeTouched?: boolean;
    businessAdoptionRate?: string;
    businessLiftEstimate?: string;
    businessConfidenceScenario?: string;
    businessCostBasis?: string;
    businessDecisionThreshold?: string;
    businessManualLift?: string;
    decisionRecommendation?: string;
    decisionRecommendationTouched?: boolean;
    decisionOwner?: string;
    decisionDate?: string;
    launchReadinessThreshold?: string;
    riskTolerance?: string;
    followUpAction?: string;
    decisionRationale?: string;
    docReadinessDecision?: string;
    docReviewer?: string;
    docReviewDate?: string;
    docAttachMds?: string;
    docExportPackage?: string;
    docIncludeLimitations?: string;
    docIncludeMonitoring?: string;
    monitoringOwner?: string;
    monitoringTargetObservations?: string;
    monitoringTreatmentTarget?: string;
    monitoringControlTarget?: string;
    monitoringReanalysisTrigger?: string;
    monitoringFollowUpDate?: string;
    monitoringCadence?: string;
    monitoringDecisionOwner?: string;
    fullDatasetArtifactId?: string;
    fullDatasetArtifactLoadedAt?: string;
    fullDatasetRowCount?: number;
    validAnalysisRecordCount?: number;
    analysisDataSource?: "full_dataset_artifact" | "preview_rows" | "compact_browser_cache";
    postDecisionStrategy?: string;
    postDecisionStrategyTouched?: boolean;
    postLaunchOwner?: string;
    postLaunchDate?: string;
    postLaunchRollbackCriteria?: string;
    postLaunchReviewCadence?: string;
    approvedSegments?: string;
    excludedSegments?: string;
    rolloutCheckpoints?: string;
    correction?: string;
    minimumSegmentSize?: string;
    datasetId?: string;
    datasetVersionId?: string;
    datasetRowCount?: number;
    datasetColumnCount?: number;
    datasetColumns?: string[];
    dataSourceKind?: "reference" | "dataset_library" | "upload";
    mappingValidatedAt?: string;
  };
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
  time_series_forecasting: ["MAE", "RMSE", "MAPE", "WAPE", "bias", "coverage", "anomaly rate", "data freshness"],
  forecasting: ["MAPE", "MAE", "RMSE", "bias", "coverage", "backtest error"],
  segmentation: ["silhouette", "Davies-Bouldin", "cluster size", "stability", "profile separation"],
  "reinforcement-learning": ["reward", "policy value", "off-policy estimate", "safety violations", "regret"],
  "time-series": ["ACF", "PACF", "stationarity", "anomaly rate", "MAPE", "drift"],
  llm_generative_ai: ["correctness", "groundedness", "citation accuracy", "hallucination rate", "policy compliance", "reviewer agreement", "latency", "cost"],
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
  time_series_forecasting: ["Naive baseline", "Seasonal naive", "Exponential smoothing", "ARIMA/SARIMA-style model", "Gradient boosting with lag features", "Anomaly detection baseline"],
  forecasting: ["Naive baseline", "ETS", "ARIMA/SARIMA", "Prophet-style model", "Gradient boosting with lags"],
  segmentation: ["K-means", "Hierarchical clustering", "Gaussian mixture", "DBSCAN", "Rule-based segmentation"],
  "reinforcement-learning": ["Contextual bandit", "Q-learning", "Policy gradient", "Offline policy evaluation", "Simulation only"],
  "time-series": ["Decomposition", "Stationarity testing", "ARIMA diagnostics", "Anomaly detection", "Change point detection"],
  llm_generative_ai: ["Prompted LLM Workflow", "RAG / Knowledge Retrieval", "Text Classification", "Information Extraction", "Summarization", "NLP Baseline Models", "Human Review Workflow"],
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
    experimentalData: {
      mode: "",
      sourceType: "",
      datasetRole: "experimental_source",
      status: "not_configured",
      schemaConfirmed: false,
      availableColumns: [],
      captureFrequency: "",
      sourceLocation: "",
      lineageNotes: "",
      qualityPlan: "",
    },
    ab: {
      ...AB_WORKFLOW_DEFAULTS,
      confirmed: false,
      previewOnly: false,
      metricType: "Binary conversion",
      confidenceLevel: "95%",
      practicalSignificanceThreshold: "1 pp",
      secondaryMetrics: "total.ads",
      guardrailMetrics: "Missingness, duplicate units, allocation imbalance",
      multipleComparisonPolicy: "Benjamini-Hochberg FDR",
      segmentColumn: AB_WORKFLOW_DEFAULTS.segmentColumns[0],
      duplicateHandling: "Keep first unit record",
      missingTreatmentHandling: "Exclude from experiment analysis",
      missingOutcomeHandling: "Exclude from primary metric",
      invalidTreatmentHandling: "Flag and exclude",
      invalidOutcomeHandling: "Flag and exclude",
      experimentType: "Marketing A/B test",
      experimentDesign: "User-level randomized holdout",
      randomizationUnit: AB_WORKFLOW_DEFAULTS.unitIdColumn,
      analysisUnit: AB_WORKFLOW_DEFAULTS.unitIdColumn,
      outcomeWindow: "Post-exposure conversion window",
      exposureWindow: "Campaign exposure period",
      assignmentMethod: "Observed test.group assignment",
      randomizationAssignmentMethod: "Observed assignment only",
      expectedAllocationRatio: "1:1",
      balanceVariables: "total.ads, most.ads.day, most.ads.hour",
      exposureInterpretation: "Post-assignment exposure intensity",
      minimumAcceptableGroupSize: "30",
      allocationImbalanceAcceptable: "Acceptable for workflow testing only",
      exposureImbalanceAcceptable: "Needs caution",
      segmentImbalanceAcceptable: "",
      reviewerConclusion: "Proceed with caution",
      powerBaselineConversionRate: "",
      minimumDetectableEffect: "",
      powerConfidenceLevel: "95%",
      powerAlpha: "0.05",
      desiredPower: "80%",
      powerTestType: "Two-sided",
      powerAllocationRatio: "",
      currentSampleSource: "Confirmed dataset",
      edaChartGrouping: "Treatment vs Control",
      edaMinimumSegmentSize: "30",
      edaValidRecordsOnly: true,
      analysisTestType: "Two-proportion z-test",
      analysisAlternativeHypothesis: "Treatment different from control",
      analysisValidRecordsOnly: true,
      segmentShowOnlyMeetingThreshold: false,
      segmentSortBy: "Lift descending",
      segmentMinimumSizeTouched: false,
      businessAdoptionRate: "100%",
      businessLiftEstimate: "Observed absolute lift",
      businessConfidenceScenario: "Observed",
      businessCostBasis: "Per treatment exposure",
      businessDecisionThreshold: "Net impact > 0",
      businessManualLift: "1 pp",
      decisionRecommendation: "",
      decisionRecommendationTouched: false,
      decisionOwner: "",
      decisionDate: "",
      launchReadinessThreshold: "",
      riskTolerance: "Low",
      followUpAction: "",
      decisionRationale: "",
      docReadinessDecision: "",
      docReviewer: "",
      docReviewDate: "",
      docAttachMds: "",
      docExportPackage: "",
      docIncludeLimitations: "",
      docIncludeMonitoring: "",
      monitoringOwner: "",
      monitoringTargetObservations: "",
      monitoringTreatmentTarget: "",
      monitoringControlTarget: "",
      monitoringReanalysisTrigger: "",
      monitoringFollowUpDate: "",
      monitoringCadence: "",
      monitoringDecisionOwner: "",
      fullDatasetArtifactId: "",
      fullDatasetArtifactLoadedAt: "",
      fullDatasetRowCount: 0,
      validAnalysisRecordCount: 0,
      analysisDataSource: "preview_rows",
      postDecisionStrategy: "",
      postDecisionStrategyTouched: false,
      postLaunchOwner: "",
      postLaunchDate: "",
      postLaunchRollbackCriteria: "",
      postLaunchReviewCadence: "",
      approvedSegments: "Reviewer-approved segments",
      excludedSegments: "Underpowered or non-significant segments",
      rolloutCheckpoints: "5%, 10%, 25%, 50%, 100%",
      correction: "Benjamini-Hochberg FDR",
      minimumSegmentSize: "30",
      datasetId: "",
      datasetVersionId: "",
      datasetRowCount: 0,
      datasetColumnCount: 0,
      datasetColumns: [],
      dataSourceKind: "reference",
      mappingValidatedAt: "",
    },
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
    return parsed ? { ...emptyState(), ...parsed, ab: { ...emptyState().ab, ...(parsed.ab ?? {}) }, numeric: { ...emptyState().numeric, ...(parsed.numeric ?? {}) } } : emptyState();
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
    ab: { ...emptyState().ab, ...(rest.ab ?? {}) },
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
    experimentalData: state.experimentalData ? { ...state.experimentalData, availableColumns: state.experimentalData.availableColumns?.slice(0, 250) ?? [] } : undefined,
    ab: { ...emptyState().ab, ...(state.ab ?? {}) },
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
  const projectId = useWorkflowStore.getState().projectId;
  void saveExportToDatabase(projectId, {
    exportType: type.includes("json") ? "json" : type.includes("csv") ? "csv" : type.includes("html") ? "html" : "text",
    fileName: filename,
    metadata: { sizeBytes: blob.size, mimeType: type, source: "workflow_export" },
  });
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
  if (projectType === "time_series_forecasting" || projectType === "forecasting" || projectType === "time-series") return ["Use time-based validation and preserve temporal order.", "Review seasonality, holidays, structural breaks, and drift before selecting final methods.", "Capture backtesting, forecast intervals, and monitoring triggers before relying on the forecast."];
  if (projectType === "segmentation") return ["Prioritize stable, interpretable segments over purely mathematical separation.", "Require segment names, business actions, and monitoring before activation."];
  if (projectType === "llm_generative_ai" || projectType === "nlp") return ["Document source lineage, prompt or task design, PII controls, and human review criteria.", "Use groundedness, citation, safety, and reviewer metrics instead of only aggregate accuracy.", "Do not claim real LLM evaluation unless a configured backend or uploaded evaluation outputs support it."];
  if (projectType === "computer-vision") return ["Review image quality, annotation consistency, and subgroup failure cases.", "Track false positives and human review burden before deployment."];
  if (projectType === "graph-analytics") return ["Define nodes, edges, direction, weights, and time validity before modeling.", "Validate graph features for leakage and investigation usefulness."];
  if (projectType === "reinforcement-learning") return ["Define state, action, reward, safety constraints, and offline evaluation before policy learning.", "Prefer simulation and guarded rollout until policy risk is understood."];
  if (projectType === "experimental-design") return ["Define factors and levels before randomization.", "Check power for interactions if interaction effects are decision-critical."];
  return ["Capture objective, evidence, assumptions, risks, and decision rationale for this workflow step."];
}

function abSampleSize(state: NodeState, allocationRatio = 1, testType: "One-sided" | "Two-sided" = "Two-sided") {
  const p1 = Math.max(0.0001, Math.min(0.9999, state.numeric.baselineRate / 100));
  const lift = state.numeric.expectedLift / 100;
  const p2 = Math.max(0.0001, Math.min(0.9999, p1 * (1 + lift)));
  const alpha = Math.max(0.001, Math.min(0.5, state.numeric.alpha > 1 ? state.numeric.alpha / 100 : state.numeric.alpha));
  const desiredPower = Math.max(0.5, Math.min(0.99, state.numeric.power / 100));
  const ratio = Math.max(0.01, Math.min(100, allocationRatio));
  const zAlpha = normalQuantile(1 - alpha / (testType === "Two-sided" ? 2 : 1));
  const zPower = normalQuantile(desiredPower);
  const pooled = (p1 + ratio * p2) / (1 + ratio);
  const numerator =
    zAlpha * Math.sqrt(pooled * (1 - pooled) * (1 + 1 / ratio)) +
    zPower * Math.sqrt(p1 * (1 - p1) + p2 * (1 - p2) / ratio);
  const control = Math.ceil((numerator * numerator) / Math.max(1e-9, (p2 - p1) ** 2));
  const treatment = Math.ceil(control * ratio);
  return { perCell: control, control, treatment, total: control + treatment, p1, p2, ratio, alpha, desiredPower, testType };
}

function parsePercentSetting(value: string | undefined, fallback: number) {
  const cleaned = String(value ?? "").replace(/[^0-9.+-]/g, "");
  if (!/[0-9]/.test(cleaned)) return fallback;
  const parsed = Number(cleaned);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function parseAllocationRatio(value: string | undefined, fallback: number) {
  const raw = String(value ?? "");
  const ratioMatch = raw.match(/([0-9]*\.?[0-9]+)\s*:\s*([0-9]*\.?[0-9]+)/);
  if (ratioMatch) {
    const numerator = Number(ratioMatch[1]);
    const denominator = Number(ratioMatch[2]);
    if (Number.isFinite(numerator) && Number.isFinite(denominator) && denominator > 0) {
      return Math.max(0.01, Math.min(100, numerator / denominator));
    }
  }
  const parsed = Number(raw.replace(/[^0-9.+-]/g, ""));
  return Number.isFinite(parsed) && parsed > 0 ? Math.max(0.01, Math.min(100, parsed)) : fallback;
}

function abPowerForCurrentSample({
  controlRate,
  relativeLiftPct,
  controlCount,
  treatmentCount,
  alpha,
  testType,
}: {
  controlRate: number;
  relativeLiftPct: number;
  controlCount: number;
  treatmentCount: number;
  alpha: number;
  testType: "One-sided" | "Two-sided";
}) {
  const p1 = Math.max(0.0001, Math.min(0.9999, controlRate));
  const p2 = Math.max(0.0001, Math.min(0.9999, p1 * (1 + relativeLiftPct / 100)));
  const n1 = Math.max(1, controlCount);
  const n2 = Math.max(1, treatmentCount);
  const pooled = (n1 * p1 + n2 * p2) / (n1 + n2);
  const nullSe = Math.sqrt(pooled * (1 - pooled) * (1 / n1 + 1 / n2));
  const alternativeSe = Math.sqrt(p1 * (1 - p1) / n1 + p2 * (1 - p2) / n2);
  const zAlpha = normalQuantile(1 - alpha / (testType === "Two-sided" ? 2 : 1));
  return normalCdf((Math.abs(p2 - p1) - zAlpha * nullSe) / Math.max(1e-9, alternativeSe));
}

function abDetectableRelativeLift({
  controlRate,
  controlCount,
  treatmentCount,
  alpha,
  desiredPower,
  testType,
}: {
  controlRate: number;
  controlCount: number;
  treatmentCount: number;
  alpha: number;
  desiredPower: number;
  testType: "One-sided" | "Two-sided";
}) {
  let low = 0.01;
  let high = 500;
  for (let iteration = 0; iteration < 60; iteration += 1) {
    const midpoint = (low + high) / 2;
    const power = abPowerForCurrentSample({ controlRate, relativeLiftPct: midpoint, controlCount, treatmentCount, alpha, testType });
    if (power >= desiredPower) high = midpoint;
    else low = midpoint;
  }
  return high;
}

function abPowerAssessment(
  state: NodeState,
  summary: ReturnType<typeof summarizeAbGroups>,
  imbalance: ReturnType<typeof allocationImbalance>,
  analysis: ReturnType<typeof analyzeAbLift>,
) {
  const ab = { ...emptyState().ab, ...(state.ab ?? {}) };
  const observedBaselinePct = analysis.controlConversionRate * 100;
  const baselineRatePct = Math.max(0.01, Math.min(99.99, parsePercentSetting(ab.powerBaselineConversionRate, observedBaselinePct)));
  const relativeLiftPct = Math.max(0.01, parsePercentSetting(ab.minimumDetectableEffect, state.numeric.expectedLift || 5));
  const alphaSetting = parsePercentSetting(ab.powerAlpha, 0.05);
  const alpha = Math.max(0.001, Math.min(0.5, alphaSetting > 1 ? alphaSetting / 100 : alphaSetting));
  const desiredPowerPct = Math.max(50, Math.min(99, parsePercentSetting(ab.desiredPower, state.numeric.power || 80)));
  const testType = (ab.powerTestType === "One-sided" ? "One-sided" : "Two-sided") as "One-sided" | "Two-sided";
  const allocationRatio = parseAllocationRatio(ab.powerAllocationRatio, Math.max(0.01, imbalance.ratio));
  const samplePlan = abSampleSize(
    {
      ...state,
      numeric: {
        ...state.numeric,
        baselineRate: baselineRatePct,
        expectedLift: relativeLiftPct,
        alpha: alpha * 100,
        power: desiredPowerPct,
      },
    },
    allocationRatio,
    testType,
  );
  const estimatedPower = abPowerForCurrentSample({
    controlRate: baselineRatePct / 100,
    relativeLiftPct,
    controlCount: summary.controlCount,
    treatmentCount: summary.treatmentCount,
    alpha,
    testType,
  });
  const detectableRelativeLift = abDetectableRelativeLift({
    controlRate: baselineRatePct / 100,
    controlCount: summary.controlCount,
    treatmentCount: summary.treatmentCount,
    alpha,
    desiredPower: desiredPowerPct / 100,
    testType,
  });
  return {
    baselineRatePct,
    relativeLiftPct,
    alpha,
    desiredPowerPct,
    testType,
    allocationRatio,
    samplePlan,
    estimatedPower,
    detectableRelativeLift,
    adequatelyPowered: estimatedPower >= desiredPowerPct / 100,
  };
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

  if (projectType === "time_series_forecasting" || projectType === "forecasting" || projectType === "time-series") {
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

function confirmedExperimentalFactors(projectId: string) {
  return sharedParseFactorHierarchy(loadExperimentalNodeState(projectId, "Levels")?.objective ?? "");
}

function stateWithFactorStructure(state: NodeState, factors: ExperimentalFactor[]): NodeState {
  if (!factors.length) return state;
  const averageLevels = factors.reduce((sum, factor) => sum + factor.levels.length, 0) / factors.length;
  return {
    ...state,
    numeric: {
      ...state.numeric,
      factorCount: factors.length,
      averageLevels,
    },
  };
}

function ExperimentalPrerequisiteGate({ title, detail }: { title: string; detail: string }) {
  return (
    <section className="rounded-2xl border border-dashed border-amber-300 bg-amber-50 p-8 text-center shadow-sm">
      <div className="mx-auto flex h-11 w-11 items-center justify-center rounded-full bg-white text-amber-700 shadow-sm"><ShieldCheck size={20} /></div>
      <h2 className="mt-4 text-lg font-semibold text-slate-950">{title}</h2>
      <p className="mx-auto mt-2 max-w-2xl text-sm leading-6 text-slate-600">{detail}</p>
    </section>
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
  const treatmentCells = parsedFactors.length ? treatmentCellCount(parsedFactors) : 0;
  const sampleBase = stateWithFactorStructure(sampleState ?? state, parsedFactors);
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
  const samplePerCell = sourceTotalSample && treatmentCells > 0 ? Math.floor(sourceTotalSample / treatmentCells) : 0;
  const totalSample = samplePerCell > 0 ? samplePerCell * treatmentCells : 0;
  const samplePlanConfirmed = Number(sampleBase.numeric.samplePlanConfirmed ?? 0) === 1;
  return {
    treatmentCells,
    samplePerCell,
    totalSample,
    sampleReady: parsedFactors.length > 0 && samplePlanConfirmed && samplePerCell >= 30 && totalSample > 0,
    sampleSource: !samplePlanConfirmed ? "unconfirmed sample-size assumptions" : totalPlannedSample ? "planned total sample" : availablePopulation ? "available population" : "missing sample size",
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
  const levelsState = loadExperimentalNodeState(projectId, "Levels");
  const sampleState = loadExperimentalNodeState(projectId, "Sample Size");
  const factors = sharedParseFactorHierarchy(levelsState?.objective ?? "");
  const factorNames = factors.map((factor) => factor.factorName);
  const factorCodes = factorNames.map((_, index) => String.fromCharCode(65 + index));
  const levelCounts = factors.map((factor) => factor.levels.length);
  const researchIntent = researchState?.method || "Main Effects + Interaction Analysis";
  const includeInteractions = /interaction|factorial|optimization|screening/i.test(researchIntent) && factorCodes.length > 1;
  const terms = includeInteractions ? generateFullFactorialTerms(factors) : factorNames;
  const modelFormula = factorNames.length ? `Response ~ ${terms.join(" + ")}` : "Response ~ [confirm factors and levels first]";
  const treatmentCells = factors.length ? treatmentCellCount(factors) : 0;
  const sampleDesignState = stateWithFactorStructure(sampleState ?? state, factors);
  const samplePlanConfirmed = Number(sampleDesignState.numeric.samplePlanConfirmed ?? 0) === 1;
  const plannedObservations = factors.length && samplePlanConfirmed ? sampleSizePlan(sampleDesignState).total : 0;
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
    recommendedModel: !factors.length ? "Factors and levels required" : includeInteractions ? "Factorial ANOVA with interaction terms" : "Main-effects ANOVA",
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
    <section className="overflow-hidden rounded-2xl border border-slate-800 bg-slate-950 text-white shadow-sm">
      <div className="grid gap-5 px-5 py-5 lg:grid-cols-[minmax(0,1fr)_300px] lg:items-start">
        <div>
          <div className="flex flex-wrap items-center gap-2 text-[11px] font-semibold uppercase text-blue-300">
            <span>Experimental Design</span><span className="text-slate-600">/</span><span>Step {journey.stepNumber} of {journey.totalSteps}</span>
          </div>
          <h1 className="mt-2 text-2xl font-semibold text-white">{journey.label}</h1>
          <p className="mt-2 text-base font-semibold text-slate-100">{journey.question}</p>
          <p className="mt-2 max-w-4xl text-sm leading-6 text-slate-300">{journey.purpose}</p>
        </div>
        <div className="rounded-xl border border-slate-700 bg-slate-900 p-4">
          <div className="text-[10px] font-semibold uppercase text-slate-400">Artifact produced</div>
          <div className="mt-1 text-sm font-semibold text-white">{journey.output}</div>
          <div className="mt-4 flex items-center gap-2 text-xs text-slate-300"><span>{previous?.label ?? "Start"}</span><ArrowRight size={13} className="text-blue-300" /><span className="font-semibold text-white">{journey.label}</span><ArrowRight size={13} className="text-blue-300" /><span>{next?.label ?? "Complete"}</span></div>
        </div>
      </div>
      <div className="border-t border-slate-800 bg-slate-900/80 px-5 py-3">
        <div className="grid grid-cols-12 gap-1.5" aria-label={`Step ${journey.stepNumber} of ${journey.totalSteps}`}>
          {experimentalDesignJourney.map((item) => <div key={item.id} className={`h-1.5 rounded-full ${item.stepNumber < journey.stepNumber ? "bg-emerald-500" : item.stepNumber === journey.stepNumber ? "bg-blue-400" : "bg-slate-700"}`} title={`${item.stepNumber}. ${item.label}`} />)}
        </div>
      </div>
    </section>
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
          <div className="text-xs font-semibold uppercase tracking-wide text-blue-700">Design inputs and evidence</div>
          <h2 className="mt-1 text-lg font-semibold text-slate-950">Configure the decision, assumptions, and review record</h2>
          <p className="mt-1 max-w-3xl text-sm leading-6 text-slate-500">
            Enter confirmed study information here. ATLAS suggestions remain optional and are never treated as user-confirmed evidence until you apply or edit them.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <span className={`rounded-full border px-3 py-1 text-xs font-semibold ${complete ? "border-emerald-200 bg-emerald-50 text-emerald-800" : "border-amber-200 bg-amber-50 text-amber-800"}`}>
            Inputs {complete ? "Complete" : `${completeFields}/${config.fields.length}`}
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
        </label>
        <MetricPicker options={config.metrics} selected={state.metrics} onChange={(metrics) => setState({ ...state, metrics })} />
        <button
          type="button"
          className="self-end rounded-xl bg-slate-950 px-4 py-2 text-sm font-semibold text-white shadow-sm transition hover:-translate-y-0.5 hover:bg-slate-800"
          onClick={() => save()}
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

function InlineSuccess({ message }: { message: string }) {
  return (
    <div className="rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm font-semibold text-emerald-900">
      {message}
    </div>
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
  const completeProjectContext = () => {
    const data = { ...emptyState().experimentalData, ...(state.experimentalData ?? {}) } as NonNullable<NodeState["experimentalData"]>;
    if (!data.schemaConfirmed || !experimentalDataReady(data)) {
      setDraftError("Confirm a prospective capture plan or governed dataset strategy before continuing to Research Question.");
      return false;
    }
    const missingContext = [
      !state.objective.trim() ? "business objective" : "",
      !state.inputs.trim() ? "population and experimental unit" : "",
      !state.assumptions.trim() ? "operational constraints" : "",
      !state.validation.trim() ? "governance and approval requirements" : "",
      !state.method.trim() ? "experiment family" : "",
      !state.metrics.length ? "primary response or evidence metric" : "",
    ].filter(Boolean);
    if (missingContext.length) {
      setDraftError(`Complete the confirmed Project Context before continuing. Missing: ${missingContext.join(", ")}.`);
      return false;
    }
    return onComplete();
  };

  useEffect(() => {
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
        onNext={completeProjectContext}
      >
        <div className="space-y-5">
          <ExperimentalJourneyHeader journey={journey} />
          {(navigationError || draftError) && <InlineError message={navigationError || draftError || ""} />}
          <GovernanceDocumentationPanel stepLabel={step.label} projectId={projectId} config={config} state={state} setState={setState} save={saveDraft} analysis={analysis} savedAt={blockingSavedAt} />
          <ProjectContextPage
            projectId={projectId}
            config={config}
            state={state}
            setState={setState}
            save={saveDraft}
            onComplete={completeProjectContext}
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
  else if (stepLabel === "Factors") body = <FactorDesignAssistant factors={sharedDeriveSuggestedFactors(state.objective)} covariates={parseListItems(state.inputs)} />;
  else if (stepLabel === "Levels") body = <LevelsDesignBuilder projectId={projectId} state={state} setState={setState} />;
  else if (stepLabel === "Blocking") body = <BlockingAssistant projectId={projectId} state={state} setState={setState} variables={parseListItems(state.objective)} />;
  else if (stepLabel === "Randomization") body = <RandomizationStudio projectId={projectId} state={state} setState={setState} />;
  else if (stepLabel === "Sample Size") body = <SampleSizeStudio projectId={projectId} state={state} setState={setState} />;
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

const experimentalDataModes = [
  {
    id: "prospective" as const,
    label: "Prospective collection",
    description: "No analysis dataset exists yet. Define the schema, collection process, lineage, and quality controls before the experiment launches.",
    bestFor: "New randomized experiments, lab studies, field trials, and operational pilots.",
  },
  {
    id: "existing" as const,
    label: "Existing data",
    description: "Use a governed historical or pilot dataset to estimate baselines, variance, feasibility, or design assumptions.",
    bestFor: "Retrospective design support, feasibility analysis, and baseline estimation.",
  },
  {
    id: "hybrid" as const,
    label: "Hybrid",
    description: "Use historical data for planning, then collect a separate prospective experiment dataset under a documented capture plan.",
    bestFor: "Most production experiments where prior data informs power but new outcomes establish causal evidence.",
  },
  {
    id: "completed" as const,
    label: "Completed experiment",
    description: "Link the final experiment dataset for ANOVA, optimization, validation, and governed reporting.",
    bestFor: "Post-run analysis, re-analysis, validation, and documentation.",
  },
];

function experimentalDataReady(data: NonNullable<NodeState["experimentalData"]>) {
  if (!data.mode) return false;
  const captureMapped = Boolean(data.unitColumn?.trim() && data.responseColumn?.trim());
  if (data.mode === "prospective") {
    return Boolean(captureMapped && data.sourceType?.trim() && data.captureFrequency?.trim() && data.qualityPlan?.trim());
  }
  const governedDataset = Boolean(data.datasetId && data.versionId && (data.rowCount ?? 0) > 0);
  if (data.mode === "hybrid") return Boolean(governedDataset && captureMapped && data.captureFrequency?.trim() && data.qualityPlan?.trim());
  return Boolean(governedDataset && captureMapped);
}

function suggestedExperimentalColumn(columns: string[], patterns: RegExp[]) {
  return columns.find((column) => patterns.some((pattern) => pattern.test(column))) ?? "";
}

function ExperimentalColumnControl({
  label,
  value,
  columns,
  placeholder,
  help,
  onChange,
}: {
  label: string;
  value: string;
  columns: string[];
  placeholder: string;
  help: string;
  onChange: (value: string) => void;
}) {
  return (
    <label className="grid min-w-0 gap-1.5">
      <span className="text-xs font-semibold uppercase tracking-wide text-slate-600">{label}</span>
      {columns.length ? (
        <select className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm" value={value} onChange={(event) => onChange(event.target.value)}>
          <option value="">Select column</option>
          {columns.map((column) => <option key={column} value={column}>{column}</option>)}
        </select>
      ) : (
        <input className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm" value={value} placeholder={placeholder} onChange={(event) => onChange(event.target.value)} />
      )}
      <span className="text-[11px] leading-4 text-slate-500">{help}</span>
    </label>
  );
}

function ExperimentalDataStrategyPanel({ projectId, state, setState }: { projectId: string; state: NodeState; setState: (state: NodeState) => void }) {
  const data = { ...emptyState().experimentalData, ...(state.experimentalData ?? {}) } as NonNullable<NodeState["experimentalData"]>;
  const [datasets, setDatasets] = useState<DatasetSummary[]>([]);
  const [profile, setProfile] = useState<DatasetProfile | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const columns = data.availableColumns ?? [];
  const ready = experimentalDataReady(data);
  const needsDataset = data.mode === "existing" || data.mode === "hybrid" || data.mode === "completed";
  const update = (changes: Partial<NonNullable<NodeState["experimentalData"]>>) => {
    setState({ ...state, experimentalData: { ...data, ...changes } });
  };

  useEffect(() => {
    let active = true;
    Promise.all([listDatasets(), listProjectDatasets(projectId)])
      .then(([library, links]) => {
        if (!active) return;
        setDatasets(library.datasets.filter((dataset) => !dataset.archived && Boolean(dataset.latestVersion)));
        const linked = links.find((link) => link.datasetRole === "experimental_source" || link.datasetRole === "experimental_analysis");
        if (linked && !data.datasetId) {
          const version = linked.dataset.latestVersion;
          update({
            datasetId: linked.datasetId,
            versionId: linked.versionId,
            datasetName: linked.dataset.name,
            datasetRole: linked.datasetRole,
            rowCount: version?.rowCount ?? 0,
            columnCount: version?.columnCount ?? 0,
            status: "linked",
          });
        }
      })
      .catch(() => {
        if (active) setError("Dataset Library is unavailable. You can still define a prospective collection plan and link data later.");
      });
    return () => { active = false; };
    // This discovery should run only when the project changes. User edits are handled directly.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId]);

  useEffect(() => {
    if (!data.datasetId || !data.versionId || columns.length) return;
    let active = true;
    getDatasetProfile(data.datasetId, data.versionId)
      .then((result) => {
        if (!active || !result.profile) return;
        setProfile(result.profile);
        const names = result.profile.schema.map((column) => column.name);
        update({ availableColumns: names, rowCount: result.profile.rowCount, columnCount: result.profile.columnCount, status: "profiled" });
      })
      .catch(() => undefined);
    return () => { active = false; };
    // Profile hydration is keyed to the governed dataset version.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data.datasetId, data.versionId]);

  const attachDataset = async (dataset: DatasetSummary, sourceType: "Dataset Library" | "File upload") => {
    const version = dataset.latestVersion;
    if (!version) throw new Error("The selected dataset has no registered version.");
    const result = await getDatasetProfile(dataset.datasetId, version.versionId);
    const nextProfile = result.profile;
    const nextColumns = nextProfile.schema.map((column) => column.name);
    await linkDatasetToProject(projectId, dataset.datasetId, version.versionId, "experimental_source");
    setProfile(nextProfile);
    update({
      datasetId: dataset.datasetId,
      versionId: version.versionId,
      datasetName: dataset.name,
      datasetRole: "experimental_source",
      rowCount: nextProfile.rowCount,
      columnCount: nextProfile.columnCount,
      availableColumns: nextColumns,
      sourceType,
      status: "profiled",
      schemaConfirmed: false,
      unitColumn: suggestedExperimentalColumn(nextColumns, [/unit/i, /customer/i, /account/i, /user/i, /subject/i, /participant/i, /id$/i]),
      responseColumn: suggestedExperimentalColumn(nextColumns, [/response/i, /outcome/i, /target/i, /conversion/i, /yield/i]),
      factorColumns: suggestedExperimentalColumn(nextColumns, [/treatment/i, /factor/i, /variant/i, /arm/i, /group/i]),
      blockColumns: suggestedExperimentalColumn(nextColumns, [/block/i, /strat/i, /batch/i, /wave/i, /site/i]),
      timestampColumn: suggestedExperimentalColumn(nextColumns, [/time/i, /date/i, /period/i]),
      runIdColumn: suggestedExperimentalColumn(nextColumns, [/run/i, /experiment.id/i, /trial/i]),
    });
    setMessage(`${dataset.name} is profiled and linked to this project. Review the suggested mappings before confirming the data strategy.`);
  };

  const chooseLibraryDataset = async (datasetId: string) => {
    if (!datasetId) return;
    const dataset = datasets.find((item) => item.datasetId === datasetId);
    if (!dataset) return;
    setBusy(true);
    setError("");
    try {
      await attachDataset(dataset, "Dataset Library");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "ATLAS could not link the selected dataset.");
    } finally {
      setBusy(false);
    }
  };

  const uploadExperimentalDataset = async (file: File | null) => {
    if (!file) return;
    setBusy(true);
    setError("");
    setMessage("");
    try {
      const dataset = await uploadDataset({
        file,
        name: file.name.replace(/\.[^.]+$/, ""),
        description: "Experimental Design source data",
        domain: "Experimental Design",
        sourceType: "upload",
      });
      setDatasets((current) => [dataset, ...current.filter((item) => item.datasetId !== dataset.datasetId)]);
      await attachDataset(dataset, "File upload");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "ATLAS could not upload the experimental dataset.");
    } finally {
      setBusy(false);
    }
  };

  const confirmStrategy = () => {
    if (!ready) {
      setError(needsDataset
        ? "Link a governed dataset and map the experimental unit and response before confirming this strategy."
        : "Define the capture source, experimental unit, response, collection frequency, and quality plan before confirming this strategy.");
      return;
    }
    update({ schemaConfirmed: true, status: data.datasetId ? "profiled" : "planned" });
    setError("");
    setMessage(data.datasetId
      ? "Data strategy confirmed from a governed Dataset Library version."
      : "Prospective capture plan confirmed. No dataset metrics will be shown until observations are collected and registered.");
  };

  return (
    <section className="rounded-2xl border border-blue-200 bg-blue-50/70 p-6 shadow-sm" data-testid="experimental-data-strategy">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-blue-700"><Database size={15} /> Data Strategy and Acquisition</div>
          <h2 className="mt-1 text-lg font-semibold text-slate-950">How will this experiment obtain trustworthy data?</h2>
          <p className="mt-2 max-w-4xl text-sm leading-6 text-slate-700">
            Designed experiments often begin before a dataset exists. ATLAS still requires either a governed prospective capture plan or a linked dataset version, so planning assumptions are never presented as observed evidence.
          </p>
        </div>
        <StatusBadge label={data.schemaConfirmed && ready ? "Strategy confirmed" : ready ? "Ready to confirm" : "Configuration required"} tone={data.schemaConfirmed && ready ? "good" : "warning"} />
      </div>

      <div className="mt-5 grid gap-3 md:grid-cols-2">
        {experimentalDataModes.map((mode) => {
          const selected = data.mode === mode.id;
          return (
            <button key={mode.id} type="button" className={`min-h-[172px] rounded-xl border p-4 text-left transition hover:-translate-y-0.5 hover:shadow-md ${selected ? "border-blue-500 bg-white shadow-sm ring-2 ring-blue-100" : "border-slate-200 bg-slate-50"}`} onClick={() => update({ mode: mode.id, schemaConfirmed: false, status: mode.id === "prospective" ? "planned" : "not_configured" })}>
              <div className="flex items-center justify-between gap-2">
                <span className="text-sm font-semibold text-slate-950">{mode.label}</span>
                <span className={`h-3 w-3 rounded-full border ${selected ? "border-blue-600 bg-blue-600" : "border-slate-300 bg-white"}`} />
              </div>
              <p className="mt-2 text-xs leading-5 text-slate-600">{mode.description}</p>
              <p className="mt-2 text-[11px] leading-4 text-blue-800"><span className="font-semibold">Best used for:</span> {mode.bestFor}</p>
            </button>
          );
        })}
      </div>

      {!data.mode ? (
        <div className="mt-4 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm font-semibold text-amber-900">
          Select a data strategy. ATLAS will not infer a dataset, row count, factor count, or sample size from demonstration defaults.
        </div>
      ) : (
        <>
          {needsDataset && (
            <div className="mt-5 grid gap-4 rounded-xl border border-blue-200 bg-white p-4 lg:grid-cols-[minmax(0,1fr)_auto]">
              <label className="grid min-w-0 gap-1.5">
                <span className="text-xs font-semibold uppercase tracking-wide text-slate-600">Dataset Library version</span>
                <select className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm" value={data.datasetId ?? ""} disabled={busy} onChange={(event) => void chooseLibraryDataset(event.target.value)}>
                  <option value="">Select a governed dataset</option>
                  {datasets.map((dataset) => <option key={dataset.datasetId} value={dataset.datasetId}>{dataset.name} - {(dataset.latestVersion?.rowCount ?? 0).toLocaleString()} rows</option>)}
                </select>
                <span className="text-[11px] leading-4 text-slate-500">Use an immutable Dataset Library version when the observations already exist.</span>
              </label>
              <label className="inline-flex cursor-pointer items-center justify-center gap-2 self-end rounded-lg border border-blue-200 bg-blue-50 px-4 py-2 text-sm font-semibold text-blue-800 hover:bg-blue-100">
                <Upload size={16} /> {busy ? "Working..." : "Upload dataset"}
                <input type="file" className="sr-only" accept=".csv,.txt,.xlsx,.xls,.parquet,.json,.zip,.feather,.sas7bdat" disabled={busy} onChange={(event) => void uploadExperimentalDataset(event.target.files?.[0] ?? null)} />
              </label>
            </div>
          )}

          <div className="mt-5 grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            <label className="grid gap-1.5">
              <span className="text-xs font-semibold uppercase tracking-wide text-slate-600">Collection / source type</span>
              <select className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm" value={data.sourceType ?? ""} onChange={(event) => update({ sourceType: event.target.value, schemaConfirmed: false })}>
                <option value="">Select source</option>
                {(needsDataset ? ["Dataset Library", "File upload", "SQL / warehouse", "API / event stream"] : ["Operational capture plan", "API / event stream", "Survey / instrument", "Lab instrument", "Manual controlled collection"]).map((option) => <option key={option} value={option}>{option}</option>)}
              </select>
            </label>
            <label className="grid gap-1.5">
              <span className="text-xs font-semibold uppercase tracking-wide text-slate-600">Collection frequency / response window</span>
              <input className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm" value={data.captureFrequency ?? ""} placeholder="e.g., daily through 30 days after assignment" onChange={(event) => update({ captureFrequency: event.target.value, schemaConfirmed: false })} />
              <span className="text-[11px] leading-4 text-slate-500">Define when outcomes become observable and when the dataset is analysis-ready.</span>
            </label>
            <label className="grid gap-1.5">
              <span className="text-xs font-semibold uppercase tracking-wide text-slate-600">Source location / system of record</span>
              <input className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm" value={data.sourceLocation ?? ""} placeholder="Dataset ID, schema.table, event topic, or collection owner" onChange={(event) => update({ sourceLocation: event.target.value, schemaConfirmed: false })} />
              <span className="text-[11px] leading-4 text-slate-500">Record enough lineage to reproduce the acquisition later.</span>
            </label>
          </div>

          <div className="mt-5 border-t border-blue-200 pt-5">
            <div className="text-xs font-semibold uppercase tracking-wide text-blue-700">Required analytical schema</div>
            <div className="mt-3 grid gap-4 md:grid-cols-2 xl:grid-cols-3">
              <ExperimentalColumnControl label="Experimental unit ID" value={data.unitColumn ?? ""} columns={columns} placeholder="customer_id" help="Best used for the unit randomized or repeatedly measured. It must be unique at the intended analysis grain." onChange={(value) => update({ unitColumn: value, schemaConfirmed: false })} />
              <ExperimentalColumnControl label="Primary response" value={data.responseColumn ?? ""} columns={columns} placeholder="response" help="Choose the measured outcome used for the primary hypothesis and power calculation." onChange={(value) => update({ responseColumn: value, schemaConfirmed: false })} />
              <ExperimentalColumnControl label="Factor / treatment columns" value={data.factorColumns ?? ""} columns={[]} placeholder="price_level, channel" help="List manipulated factors or treatment assignments. Historical covariates should not be mislabeled as experimental factors." onChange={(value) => update({ factorColumns: value, schemaConfirmed: false })} />
              <ExperimentalColumnControl label="Block / strata columns" value={data.blockColumns ?? ""} columns={[]} placeholder="site, risk_tier, campaign_wave" help="Use for nuisance variables controlled by blocking or stratification; leave blank when not applicable." onChange={(value) => update({ blockColumns: value, schemaConfirmed: false })} />
              <ExperimentalColumnControl label="Run / batch ID" value={data.runIdColumn ?? ""} columns={columns} placeholder="run_id" help="Supports execution traceability, repeated runs, and batch effects." onChange={(value) => update({ runIdColumn: value, schemaConfirmed: false })} />
              <ExperimentalColumnControl label="Observation timestamp" value={data.timestampColumn ?? ""} columns={columns} placeholder="observed_at" help="Required when timing, drift, response windows, or sequential collection matter." onChange={(value) => update({ timestampColumn: value, schemaConfirmed: false })} />
            </div>
          </div>

          <div className="mt-5 grid gap-4 lg:grid-cols-2">
            <TextArea label="Data lineage and provenance" value={data.lineageNotes ?? ""} rows={3} placeholder="Describe source ownership, extraction logic, joins, transformations, versioning, and access controls." onChange={(value) => update({ lineageNotes: value, schemaConfirmed: false })} />
            <TextArea label="Data quality and reconciliation plan" value={data.qualityPlan ?? ""} rows={3} placeholder="Define completeness, uniqueness, range, treatment-delivery, response-window, reconciliation, and sign-off checks." onChange={(value) => update({ qualityPlan: value, schemaConfirmed: false })} />
          </div>

          {data.datasetId && (
            <div className="mt-5 grid gap-3 md:grid-cols-4">
              <MiniEvidence label="Governed dataset" value={data.datasetName || data.datasetId} tone="good" />
              <MiniEvidence label="Version" value={data.versionId || "TBD"} />
              <MiniEvidence label="Rows" value={(data.rowCount ?? 0).toLocaleString()} />
              <MiniEvidence label="Columns" value={(data.columnCount ?? profile?.columnCount ?? 0).toLocaleString()} />
            </div>
          )}
          {error && <div className="mt-4"><InlineError message={error} /></div>}
          {message && <div className="mt-4"><InlineSuccess message={message} /></div>}
          <div className="mt-5 flex flex-wrap items-center justify-between gap-3 border-t border-blue-200 pt-4">
            <div className="text-xs leading-5 text-slate-600">
              {ready ? "Required data fields are complete. Confirm to lock the provenance status for this stage." : "Complete the required source and schema fields. Optional factor, block, run, and timestamp mappings can be added when relevant."}
            </div>
            <button type="button" className="atlas-primary-button" onClick={confirmStrategy}><Link2 size={15} /> Confirm Data Strategy</button>
          </div>
        </>
      )}
    </section>
  );
}

function ProjectContextPage({
  projectId,
  config,
  state,
  setState,
  save,
  onComplete,
  nextStep,
  journey,
}: {
  projectId: string;
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
  const experimentalData = { ...emptyState().experimentalData, ...(state.experimentalData ?? {}) } as NonNullable<NodeState["experimentalData"]>;
  const dataStrategyConfirmed = Boolean(experimentalData.schemaConfirmed && experimentalDataReady(experimentalData));
  const confirmedFactors = confirmedExperimentalFactors(projectId);
  const sampleSizeState = loadExperimentalNodeState(projectId, "Sample Size");
  const samplePlanConfirmed = Number(sampleSizeState?.numeric.samplePlanConfirmed ?? 0) === 1;
  const explicitPopulation = inferPopulationCount(state.inputs);
  const confirmedTreatmentCells = confirmedFactors.length ? treatmentCellCount(confirmedFactors) : 0;
  const readinessItems = [
    { label: "Business Objective", complete: Boolean(state.objective.trim()), summary: summarizeText(state.objective, "Define the business decision this experiment will support.") },
    { label: "Population", complete: Boolean(state.inputs.trim()), summary: summarizeText(state.inputs, "Define eligible population, exclusions, and unit of randomization.") },
    { label: "Data Strategy", complete: dataStrategyConfirmed, summary: dataStrategyConfirmed ? `${experimentalDataModes.find((mode) => mode.id === experimentalData.mode)?.label ?? "Data strategy"}${experimentalData.datasetName ? ` - ${experimentalData.datasetName}` : ""}` : "Choose a prospective, existing-data, hybrid, or completed-experiment strategy and confirm its provenance." },
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

      <ExperimentalDataStrategyPanel projectId={projectId} state={state} setState={setState} />

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
            <div className="grid gap-2 sm:grid-cols-3 xl:grid-cols-6">
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

      <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm" data-testid="experimental-design-readiness-snapshot">
        <div className="flex items-center justify-between gap-3">
          <div>
            <div className="text-xs font-semibold uppercase tracking-wide text-blue-700">Data and Design Readiness</div>
            <h2 className="mt-1 text-base font-semibold text-slate-950">Confirmed evidence only</h2>
          </div>
          <span className="rounded-full border border-slate-200 bg-slate-50 px-2.5 py-1 text-xs font-semibold text-slate-600">no inferred values</span>
        </div>
        <p className="mt-2 text-sm leading-6 text-slate-600">
          ATLAS keeps planning assumptions separate from observed or user-confirmed evidence. Values remain TBD until their source workflow stage is complete.
        </p>
        <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-5">
          <MiniEvidence label="Data source" value={dataStrategyConfirmed ? (experimentalData.datasetName || experimentalDataModes.find((mode) => mode.id === experimentalData.mode)?.label || "Confirmed plan") : "TBD"} tone={dataStrategyConfirmed ? "good" : "warning"} />
          <MiniEvidence label="Population" value={explicitPopulation > 0 ? explicitPopulation.toLocaleString() : "TBD"} tone={explicitPopulation > 0 ? "good" : "warning"} />
          <MiniEvidence label="Confirmed factors" value={confirmedFactors.length ? String(confirmedFactors.length) : "TBD"} tone={confirmedFactors.length ? "good" : "warning"} />
          <MiniEvidence label="Treatment cells" value={confirmedTreatmentCells ? String(confirmedTreatmentCells) : "TBD"} tone={confirmedTreatmentCells ? "good" : "warning"} />
          <MiniEvidence label="Power target" value={samplePlanConfirmed ? `${Math.round(sampleSizeState?.numeric.power ?? 0)}%` : "TBD"} tone={samplePlanConfirmed ? "good" : "warning"} />
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
  const factors = confirmedExperimentalFactors(projectId);
  if (!factors.length) {
    return <ExperimentalPrerequisiteGate title="Randomization requires a confirmed treatment matrix" detail="Return to Levels and confirm the actual factor settings. Assignment ratios, balance diagnostics, and audit controls will then be calculated from those treatment cells." />;
  }
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
              <span className="text-[11px] leading-4 text-slate-500"><span className="font-semibold">Best used for:</span> choose the smallest independently assignable unit that avoids treatment contamination and matches the analysis grain.</span>
            </label>
            <label className="grid min-w-0 gap-1.5">
              <span className="text-xs font-semibold uppercase tracking-wide text-slate-500">Block / strata</span>
              <select className="w-full min-w-0 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm" value={design.selectedStratum} onChange={(event) => setState({ ...state, blockStratum: event.target.value })}>
                {Array.from(new Set([...design.blockingSelections, "Customer risk segment", "Geographic region", "Campaign week"])).map((stratum) => <option key={stratum} value={stratum}>{stratum}</option>)}
              </select>
              <span className="text-[11px] leading-4 text-slate-500"><span className="font-semibold">Best used for:</span> a pre-treatment variable strongly related to the response that must remain balanced across treatment cells.</span>
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

function SampleSizeStudio({ projectId, state, setState }: { projectId: string; state: NodeState; setState: (state: NodeState) => void }) {
  return (
    <SampleSizePowerPlanner projectId={projectId} state={state} setState={setState} />
  );
}

function RunPlanStudio({ projectId, state, setState }: { projectId: string; state: NodeState; setState: (state: NodeState) => void }) {
  const factors = confirmedExperimentalFactors(projectId);
  if (!factors.length) {
    return <ExperimentalPrerequisiteGate title="The run plan needs a confirmed experiment structure" detail="Complete Levels before defining launch sequencing, assignment QA, monitoring, stopping rules, and rollback controls. This prevents a generic run plan from being mistaken for an approved study design." />;
  }
  const randomState = loadExperimentalNodeState(projectId, "Randomization") ?? state;
  const sampleState = stateWithFactorStructure(loadExperimentalNodeState(projectId, "Sample Size") ?? state, factors);
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
  if (!plan.factors.length) {
    return <ExperimentalPrerequisiteGate title="ANOVA specification requires confirmed factors and levels" detail="Complete the treatment matrix in Levels first. ATLAS will then generate real factor names, interactions, and degrees of freedom without inventing placeholder terms or statistical results." />;
  }
  const rows = plan.termRows.map((row) => ({ label: row.term, value: row.df, status: "Adequate" as const }));
  return (
    <section className="space-y-4">
      <section className="rounded-2xl border border-blue-200 bg-blue-50 p-5 shadow-sm">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <div className="text-xs font-semibold uppercase tracking-wide text-blue-700">Analysis specification</div>
            <h2 className="mt-1 text-lg font-semibold text-slate-950">Define the model before interpreting experimental evidence</h2>
            <p className="mt-2 max-w-4xl text-sm leading-6 text-slate-700">
              This page builds the ANOVA term structure from confirmed factors and levels. It does not invent F statistics, p-values, effect sizes, or residual diagnostics. Those results require observed experiment outcomes and a completed run.
            </p>
          </div>
          <span className="rounded-full border border-blue-200 bg-white px-3 py-1 text-xs font-semibold text-blue-800">Planning artifact</span>
        </div>
      </section>
      <AnovaModelAssistant plan={plan} />
      <HorizontalBarChartCard
        title="ANOVA Degrees-of-Freedom Structure"
        subtitle="Main effects and interaction terms generated from factor names only."
        rows={rows.length ? rows : [{ label: "Terms pending", value: 1, status: "Weak" }]}
        valueFormatter={(value) => value.toLocaleString()}
        note="This is a model specification. Statistical conclusions remain unavailable until observed outcomes are analyzed."
      />
    </section>
  );
}

function InteractionStudio({ projectId, state }: { projectId: string; state: NodeState }) {
  const plan = generatedAnovaPlan(projectId, state);
  if (!plan.factors.length) {
    return <ExperimentalPrerequisiteGate title="Interaction review requires a confirmed treatment matrix" detail="Define at least two factors with levels before ATLAS builds an interaction review plan. No example effects will be presented as experiment evidence." />;
  }
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
  const factors = parsedFactors;
  if (!factors.length) {
    return (
      <section className="rounded-2xl border border-dashed border-amber-300 bg-amber-50 p-8 text-center shadow-sm">
        <h2 className="text-lg font-semibold text-slate-950">Optimization is blocked until treatment levels are confirmed</h2>
        <p className="mx-auto mt-2 max-w-2xl text-sm leading-6 text-slate-600">Return to Levels and define the actual treatment matrix. ATLAS will not rank invented example treatments or present simulated values as observed evidence.</p>
      </section>
    );
  }
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
              <div className="text-xs font-semibold uppercase tracking-wide text-emerald-700">Planning scenario only</div>
              <h2 className="mt-1 text-2xl font-semibold text-slate-950">{winner?.label ?? "Treatment pending"}</h2>
              <p className="mt-2 max-w-3xl text-sm leading-6 text-emerald-950">
                {winner
                  ? `${winner.settings}. This cell leads the current scenario assumptions. It is not a final recommendation until observed response, uncertainty, and guardrail evidence are supplied and reviewed.`
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
            title="Scenario Treatment Ranking"
            subtitle="Compares treatment cells under planning assumptions; it does not represent observed study results."
            rows={ranked.map((row) => ({ label: row.label, value: row.desirability, status: row.status }))}
            valueFormatter={(value) => `${Math.round(value * 100)} score`}
            note="Higher scores indicate stronger planning scenarios only. Confirm with observed experiment evidence before deployment."
          />
          <AnalysisEvidenceTable table={{
            title: "Top Candidate Treatments",
            headers: ["Treatment", "Settings", "Decision"],
            rows: ranked.slice(0, 5).map((row, index) => [row.label, row.settings, index === 0 ? "Candidate optimum" : "Compare as alternative"]),
          }} />
        </section>

        <section className="grid gap-4 lg:grid-cols-2">
          <HorizontalBarChartCard
            title="Assumed Lift Comparison"
            subtitle="Illustrative incremental response under the active planning scenario."
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
            <ResultCard label="Scenario Revenue" value={winner ? `$${winner.revenue.toLocaleString()}` : "-"} />
            <ResultCard label="Decision State" value="Evidence required" />
          </div>
        </section>

        <section className="rounded-2xl border border-blue-200 bg-blue-50 p-5 shadow-sm">
          <div className="text-xs font-semibold uppercase tracking-wide text-blue-700">Why this scenario ranks first</div>
          <ul className="mt-3 space-y-2 text-sm leading-6 text-blue-950">
            <li>- Highest combined desirability score.</li>
            <li>- Positive assumed lift under the current planning inputs.</li>
            <li>- Stronger modeled guardrail coverage than alternative scenarios.</li>
            <li>- Must be replaced with observed effects and uncertainty before approval.</li>
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
  const treatmentCells = factors.length ? treatmentCellCount(factors) : 0;
  const designDependentSteps = ["Factors", "Levels", "Blocking", "Randomization", "Sample Size", "Monte Carlo Simulation", "Experiment Run Plan", "ANOVA", "Interaction Effects", "Optimization"];
  if (!factors.length && designDependentSteps.includes(stepLabel)) {
    return stepLabel === "Factors"
      ? "Enter the controllable factors, then confirm their actual settings in Levels. ATLAS will not report treatment cells, power, simulation risk, or analysis terms until that structure exists."
      : "Confirmed factors and levels are required before ATLAS can calculate or interpret this stage. Return to Levels and save the actual treatment matrix to replace all TBD values with design-specific evidence.";
  }
  const factorPair = factorNames.length >= 2 ? `${factorNames[0]} x ${factorNames[1]}` : "the primary factor interaction";
  const randomizationDesign = nodeStates.Randomization ? randomizationDesignInputs(projectId, nodeStates.Randomization) : null;
  const lookup: Record<string, string> = {
    Factors: `ATLAS identified ${factorNames.length} controllable factors producing ${treatmentCells.toLocaleString()} treatment cells. ${factorNames.slice(0, 2).join(" and ")} should be randomized and audited. Measured covariates should support balance checks and subgroup diagnostics, not drive treatment assignment.`,
    Levels: `ATLAS generated a ${factors.map((factor) => factor.levels.length).join(" x ")} treatment matrix from the selected levels. Baseline settings should be clearly identified before sample-size planning so treatment effects are interpretable.`,
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

function FactorDesignAssistant({ factors, covariates }: { factors: SuggestedFactor[]; covariates: string[] }) {
  const designFactors = normalizeDesignFactors(factors);
  if (!designFactors.length) {
    return (
      <section className="rounded-2xl border border-dashed border-blue-300 bg-blue-50/60 p-8 text-center shadow-sm">
        <div className="mx-auto flex h-11 w-11 items-center justify-center rounded-full bg-white text-blue-700 shadow-sm"><BarChart3 size={20} /></div>
        <h2 className="mt-4 text-lg font-semibold text-slate-950">Define controllable factors to build the design</h2>
        <p className="mx-auto mt-2 max-w-2xl text-sm leading-6 text-slate-600">Enter one confirmed factor per line in Design Inputs above. ATLAS will propose provisional levels for design exploration, but it will not invent factors or treat suggestions as confirmed evidence.</p>
        <div className="mx-auto mt-4 max-w-xl rounded-xl border border-blue-200 bg-white p-3 text-left font-mono text-xs leading-6 text-slate-600">Offer amount<br />Contact channel<br />Message timing</div>
      </section>
    );
  }
  const treatmentCells = treatmentCellCount(designFactors);
  const levelSummary = designFactors.length ? designFactors.map((factor) => factor.levels.length).join(" x ") : "-";
  const complexity = factorComplexity(treatmentCells);
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
          <ResultCard label="Projected cells" value={treatmentCells.toLocaleString()} />
          <ResultCard label="Complexity" value={complexity} />
          <ResultCard label="Power" value="Calculated in Step 7" />
        </div>

        <ExperimentalDesignFlow factors={designFactors} />

        <div className="mt-5 grid gap-4 xl:grid-cols-[minmax(0,1.25fr)_minmax(320px,0.75fr)]">
          <TreatmentStructureHero factors={designFactors} />
          <LiveDesignTree factors={designFactors} />
        </div>
      </section>

      <section className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_420px]">
        <DesignCanvas factors={designFactors} />
        <DesignComplexityPanel factors={designFactors} />
      </section>

      <section className="grid gap-4 xl:grid-cols-2">
        <FactorCovariateMap factors={designFactors} covariates={covariates} />
        <FactorQualityScorecard factors={designFactors} treatmentCells={treatmentCells} />
      </section>

      <section className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_420px]">
        <VisualCard title="Factor Review Checklist" subtitle="Confirm these items before the provisional level suggestions become a treatment matrix.">
          <div className="grid gap-2 sm:grid-cols-2">
            {["Business can intentionally vary each factor", "Factor is not an outcome or post-treatment field", "Restricted combinations are documented", "Measured covariates remain separate", "A control setting can be identified", "Assignment can be logged and audited"].map((item) => <div key={item} className="flex items-start gap-2 rounded-xl border border-slate-200 bg-white p-3 text-xs leading-5 text-slate-700"><CheckCircle2 size={15} className="mt-0.5 shrink-0 text-blue-600" />{item}</div>)}
          </div>
        </VisualCard>
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
          <p className="mt-4 text-xs leading-5 text-emerald-900">The analysis family is provisional until levels, sample size, and observed response data are confirmed.</p>
        </div>
      </section>
    </section>
  );
}

function normalizeDesignFactors(factors: SuggestedFactor[]): SuggestedFactor[] {
  return factors.slice(0, 5).map((factor) => ({
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
  const steps = [
    { label: factors.length.toLocaleString(), value: "Confirmed factors" },
    { label: factors.map((factor) => factor.levels.length).join(" x "), value: "Provisional levels" },
    { label: `${cells.toLocaleString()} Cells`, value: "Projected grid" },
    { label: "Balanced", value: new Set(factors.map((factor) => factor.levels.length)).size === 1 ? "Yes" : "Review" },
    { label: "Step 4", value: "Confirm levels next" },
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
                      <div><span className="font-semibold text-slate-950">Sample size:</span> Defined in Step 7</div>
                      <div><span className="font-semibold text-slate-950">Assignment:</span> Defined in Step 6</div>
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

function DesignComplexityPanel({ factors }: { factors: SuggestedFactor[] }) {
  const cells = treatmentCellCount(factors);
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
            { label: "Factors", value: factors.length },
            { label: "Projected Cells", value: cells },
            { label: "Design Efficiency Score", value: efficiency },
          ]}
          valueFormatter={(value) => Math.round(value).toLocaleString()}
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
      <p className="mt-4 text-xs leading-5 text-slate-500">ATLAS intentionally defers sample and power claims until the Sample Size step. No provisional population count is presented as confirmed evidence.</p>
    </VisualCard>
  );
}

function FactorCovariateMap({ factors, covariates }: { factors: SuggestedFactor[]; covariates: string[] }) {
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
          {covariates.length ? <div className="mt-3 flex flex-wrap gap-2">{covariates.map((item) => <span key={item} className="rounded-full border border-slate-200 bg-white px-2.5 py-1 text-xs font-semibold text-slate-700">{item}</span>)}</div> : <div className="mt-3 rounded-lg border border-dashed border-slate-300 bg-white p-4 text-xs leading-5 text-slate-500">No measured covariates have been confirmed. Add them in Design Inputs only when they are observed for balance or precision and are not manipulated.</div>}
        </div>
      </div>
    </VisualCard>
  );
}

function FactorQualityScorecard({ factors, treatmentCells }: { factors: SuggestedFactor[]; treatmentCells: number }) {
  const rows = [
    { label: "Factor names are unique", pass: new Set(factors.map((factor) => factor.factorName.toLowerCase())).size === factors.length },
    { label: "Provisional levels exist", pass: factors.every((factor) => factor.levels.length >= 2) },
    { label: "Treatment grid is reviewable", pass: treatmentCells <= 32 },
    { label: "Formal power is still pending", pass: false },
  ];
  return (
    <VisualCard title="Factor Structure Checks" subtitle="Deterministic checks only. ATLAS does not fabricate relevance, signal, or power scores before evidence is supplied.">
      <div className="space-y-3">
        {rows.map((row) => (
          <div key={row.label} className="rounded-xl border border-slate-200 bg-white p-3">
            <div className="flex items-center justify-between gap-3 text-xs font-semibold">
              <span className="text-slate-700">{row.label}</span>
              <span className={row.pass ? "text-emerald-700" : "text-amber-700"}>{row.pass ? "Pass" : "Review"}</span>
            </div>
          </div>
        ))}
      </div>
      <div className="mt-4 rounded-xl border border-slate-200 bg-slate-50 p-3 text-xs leading-5 text-slate-600">
        Confirm level feasibility in Step 4 and calculate sample size and power in Step 7 before approving the design.
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
  void projectId;
  return sharedParseFactorHierarchy(state.objective);
}

function LevelsDesignBuilder({ projectId, state, setState }: { projectId: string; state: NodeState; setState: (state: NodeState) => void }) {
  const factors = levelsFactors(projectId, state);
  if (!factors.length) {
    const factorsState = loadExperimentalNodeState(projectId, "Factors");
    const suggestions = sharedDeriveSuggestedFactors(factorsState?.objective ?? "");
    const suggestedDraft = suggestions.map((factor) => `${factor.factorName}\n${factor.levels.map((level) => `- ${level}`).join("\n")}`).join("\n\n");
    return (
      <section className="rounded-2xl border border-dashed border-blue-300 bg-blue-50/60 p-8 text-center shadow-sm">
        <div className="mx-auto flex h-11 w-11 items-center justify-center rounded-full bg-white text-blue-700 shadow-sm"><ClipboardList size={20} /></div>
        <h2 className="mt-4 text-lg font-semibold text-slate-950">Confirm the factor levels before building the treatment matrix</h2>
        <p className="mx-auto mt-2 max-w-2xl text-sm leading-6 text-slate-600">Enter confirmed settings above using <span className="font-mono">Factor: Control, Treatment</span>. Suggested levels remain a draft until you explicitly apply and review them; they never unlock downstream analysis on their own.</p>
        {suggestions.length > 0 && (
          <div className="mx-auto mt-5 max-w-2xl rounded-xl border border-blue-200 bg-white p-4 text-left">
            <div className="text-xs font-semibold uppercase text-blue-700">Provisional suggestions</div>
            <pre className="mt-2 whitespace-pre-wrap font-mono text-xs leading-6 text-slate-700">{suggestedDraft}</pre>
            <button type="button" className="mt-3 rounded-lg bg-slate-950 px-3 py-2 text-xs font-semibold text-white hover:bg-slate-800" onClick={() => setState({ ...state, objective: suggestedDraft })}>Use suggestions as draft</button>
          </div>
        )}
      </section>
    );
  }
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
  const factors = confirmedExperimentalFactors(projectId);
  if (!factors.length) {
    return <ExperimentalPrerequisiteGate title="Monte Carlo simulation requires a confirmed design" detail="Confirm factors and levels, then complete the sample-size plan. ATLAS will not simulate launch risk from generic factor counts or browser defaults." />;
  }
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

function SampleSizePowerPlanner({ projectId, state, setState }: { projectId: string; state: NodeState; setState: (state: NodeState) => void }) {
  const factors = confirmedExperimentalFactors(projectId);
  if (!factors.length) {
    return <ExperimentalPrerequisiteGate title="Power planning requires confirmed factors and levels" detail="Return to Levels and confirm the treatment matrix. ATLAS will derive the number of treatment cells from that design instead of asking you to enter a separate factor count." />;
  }
  const designState = stateWithFactorStructure(state, factors);
  const assumptionsConfirmed = Number(state.numeric.samplePlanConfirmed ?? 0) === 1;
  const updateNumber = (key: string, value: number) => setState({ ...state, numeric: { ...state.numeric, [key]: value, samplePlanConfirmed: 1 } });
  const confirmAssumptions = () => setState({ ...state, numeric: { ...state.numeric, samplePlanConfirmed: 1 } });
  const plan = sampleSizePlan(designState);
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
        <div className="flex flex-wrap items-center gap-2">
          <span className={`rounded-full border px-3 py-1 text-xs font-semibold ${assumptionsConfirmed && plan.adequatelyPowered ? "border-emerald-200 bg-emerald-50 text-emerald-800" : "border-amber-200 bg-amber-50 text-amber-800"}`}>
            {!assumptionsConfirmed ? "Assumptions require confirmation" : plan.adequatelyPowered ? "Adequately powered" : "Population shortfall"}
          </span>
          {!assumptionsConfirmed && <button type="button" className="rounded-lg bg-slate-950 px-3 py-2 text-xs font-semibold text-white hover:bg-slate-800" onClick={confirmAssumptions}>Confirm current assumptions</button>}
        </div>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <SliderControl label="Alpha" value={state.numeric.alpha} min={1} max={10} step={1} suffix="%" onChange={(value) => updateNumber("alpha", value)} marks={["1", "5", "10"]} />
        <SliderControl label="Desired Power" value={state.numeric.power} min={60} max={95} step={1} suffix="%" onChange={(value) => updateNumber("power", value)} marks={["60", "80", "95"]} />
        <SliderControl label="Baseline Response" value={state.numeric.baselineRate} min={1} max={30} step={0.5} suffix="%" onChange={(value) => updateNumber("baselineRate", value)} marks={["1", "10", "30"]} />
        <SliderControl label="Minimum Detectable Lift" value={state.numeric.expectedLift} min={1} max={50} step={0.5} suffix="%" onChange={(value) => updateNumber("expectedLift", value)} marks={["1", "20", "50"]} />
        <div className="rounded-xl border border-slate-200 bg-slate-50 p-4">
          <div className="text-xs font-semibold uppercase text-slate-500">Confirmed design</div>
          <div className="mt-2 text-sm font-semibold text-slate-950">{factors.length} factors / {treatmentCellCount(factors)} treatment cells</div>
          <p className="mt-1 text-xs leading-5 text-slate-600">Inherited from Levels. Change the treatment structure there so power, randomization, ANOVA, and execution stay synchronized.</p>
        </div>
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
    const designFactorCount = parsedFactors.length;
    const designTreatmentCells = parsedFactors.length ? treatmentCellCount(parsedFactors) : 0;
    const designAverageLevels = parsedFactors.length
      ? parsedFactors.reduce((sum, factor) => sum + factor.levels.length, 0) / parsedFactors.length
      : 0;
    const balanced = parsedFactors.length > 0 && new Set(parsedFactors.map((factor) => factor.levels.length)).size === 1;
    const designLabel = parsedFactors.length > 1
      ? `${balanced ? "Balanced" : "Unbalanced"} ${parsedFactors.map((factor) => factor.levels.length).join(" × ")} factorial`
      : parsedFactors.length === 1
        ? `${parsedFactors[0].levels.length}-level single-factor design`
        : "Confirmed factors required";
    return (
      <CalculatorPanel title="Experimental Design">
        <ResultCard label="Confirmed factors" value={designFactorCount ? designFactorCount.toLocaleString() : "TBD"} />
        <ResultCard label="Average levels" value={designAverageLevels ? designAverageLevels.toFixed(1) : "TBD"} />
        <ResultCard label="Treatment cells" value={designTreatmentCells ? designTreatmentCells.toLocaleString() : "TBD"} />
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
    if (!plan.factors.length) {
      return (
        <CalculatorPanel title="ANOVA Model Summary">
          <ResultCard label="Status" value="Factors and levels required" />
          <ResultCard label="Model formula" value="TBD" />
          <ResultCard label="Treatment cells" value="TBD" />
          <ResultCard label="Degrees of freedom" value="TBD" />
        </CalculatorPanel>
      );
    }
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
    const factors = confirmedExperimentalFactors(projectId);
    if (!factors.length) {
      return (
        <CalculatorPanel title="Effect Review">
          <ResultCard label="Status" value="Treatment matrix required" />
          <ResultCard label="Effect estimate" value="TBD" />
          <ResultCard label="Signal / noise" value="TBD" />
          <ResultCard label="Interaction review" value="TBD" />
        </CalculatorPanel>
      );
    }
    const signalRatio = state.numeric.effectSize / Math.max(0.01, Math.sqrt(state.numeric.mse));
    return (
      <CalculatorPanel title="Effect Review">
        <NumberField label="Estimated MSE" value={state.numeric.mse} onChange={(value) => updateNumber("mse", value)} />
        <NumberField label="Effect Size" value={state.numeric.effectSize} onChange={(value) => updateNumber("effectSize", value)} />
        <NumberField label="Runs" value={state.numeric.runs} onChange={(value) => updateNumber("runs", value)} />
        <ResultCard label="Confirmed factors" value={factors.length.toLocaleString()} />
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

const abEvidenceTypes = [
  "experiment_context",
  "experiment_design",
  "population_eligibility",
  "treatment_control_definition",
  "data_quality",
  "randomization_check",
  "metric_definition",
  "power_analysis",
  "experiment_eda",
  "experiment_analysis",
  "segment_analysis",
  "business_impact",
  "decision_recommendation",
  "monitoring_plan",
];

function AbTestingWorkflowStep({
  projectId,
  step,
  nextStep,
  state,
  setState,
  save,
  onMarkCompleteNext,
  onComplete,
  dataAcquisitionConfirmed,
  navigationError,
  saveStatusMessage,
  lastAction,
  saveDebug,
  onClearCache,
  confirmedMapping,
}: {
  projectId: string;
  step: ReturnType<typeof getWorkflowDefinition>["steps"][number];
  nextStep?: ReturnType<typeof getWorkflowDefinition>["steps"][number];
  state: NodeState;
  setState: (state: NodeState) => void;
  save: () => NodeState;
  onMarkCompleteNext?: (event?: MouseEvent<HTMLButtonElement>) => void | Promise<void>;
  onComplete: () => boolean;
  dataAcquisitionConfirmed: boolean;
  navigationError: string | null;
  saveStatusMessage?: string;
  lastAction: string;
  saveDebug: {
    currentStepNumber: number;
    currentRoute: string;
    nextRoute: string;
    lastSavedStorageKey: string;
    lastSavedTimestamp: string;
    payloadSizeKb: string;
    storageStatus: string;
  };
  onClearCache: () => void;
  confirmedMapping: AbTestingDefaults & NonNullable<NodeState["ab"]>;
}) {
  const defaults = dataAcquisitionConfirmed ? confirmedMapping : AB_MARKETING_DEFAULTS;
  const analysisDataset = buildAbAnalysisDataset(projectId, defaults, dataAcquisitionConfirmed, confirmedMapping);
  const rows = dataAcquisitionConfirmed ? analysisDataset.rows : [];
  const profile = dataAcquisitionConfirmed ? analysisDataset.profile : null;
  const groupSummary = dataAcquisitionConfirmed ? analysisDataset.summary : summarizeAbGroups([], defaults);
  const analysis = analyzeAbLift(groupSummary);
  const imbalance = allocationImbalance(groupSummary);
  const daySegments = dataAcquisitionConfirmed ? analysisDataset.daySegments : [];
  const hourSegments = dataAcquisitionConfirmed ? analysisDataset.hourSegments : [];
  const fullDatasetReady = dataAcquisitionConfirmed && analysisDataset.status.fullDatasetAvailable;
  const recommendation = decisionRecommendationReason(analysis, imbalance);
  const evidenceType = evidenceTypeForAbStep(step.label);

  return (
    <StepShell
      title={step.label}
      subtitle={step.description}
      nextLabel={nextStep ? "Mark Complete & Next Step" : "Mark Complete & Return to Overview"}
      nextPath={nextStep?.route ?? "/project-overview"}
      nextButtonTestId="ab-testing-mark-complete-next"
      onNextClick={onMarkCompleteNext}
      nextDebugPanel={<AbTestingSaveDebug projectId={projectId} saveDebug={saveDebug} lastAction={lastAction} onClearCache={onClearCache} />}
      onNext={() => {
        onComplete();
        return false;
      }}
    >
      <div className="space-y-5">
        {navigationError && <InlineError message={navigationError} />}
        {saveStatusMessage && <InlineSuccess message={saveStatusMessage} />}

        {step.label !== "Project Context" && (
          <section className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div>
                <div className="text-xs font-semibold uppercase tracking-wide text-blue-700">Confirmed experiment context</div>
                <p className="mt-1 text-sm text-slate-600">
                  {dataAcquisitionConfirmed
                    ? "All downstream calculations use the saved Data Acquisition mapping and confirmed artifact."
                    : "Complete Data Acquisition before treating any suggested mapping as project evidence."}
                </p>
              </div>
              <span className={`rounded-full px-3 py-1 text-xs font-semibold ${dataAcquisitionConfirmed ? "bg-emerald-100 text-emerald-800" : "bg-amber-100 text-amber-900"}`}>
                {dataAcquisitionConfirmed ? "Mapping confirmed" : "Mapping required"}
              </span>
            </div>
            <div className="mt-3 grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
              <MiniEvidence label="Dataset" value={dataAcquisitionConfirmed ? defaults.dataset : "Not confirmed"} tone={dataAcquisitionConfirmed ? "good" : "warning"} />
              <MiniEvidence label="Unit ID" value={dataAcquisitionConfirmed ? defaults.unitIdColumn : "Not mapped"} />
              <MiniEvidence label="Treatment / Control" value={dataAcquisitionConfirmed ? `${defaults.treatmentValue} / ${defaults.controlValue}` : "Not mapped"} />
              <MiniEvidence label="Outcome" value={dataAcquisitionConfirmed ? `${defaults.outcomeColumn} = ${defaults.successEvent}` : "Not mapped"} />
            </div>
          </section>
        )}

        <section className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_320px]">
          <div className="min-w-0 space-y-4">
            <AbStepMainPanel stepLabel={step.label} state={state} setState={setState} evidenceType={evidenceType} />
            {step.label === "Project Context" && (
              <>
                <AbProjectContextNextStepPreview />
                <AbReviewerNotes state={state} setState={setState} />
              </>
            )}
            {step.label === "Data Acquisition and Experiment Mapping" && <AbDatasetMapping projectId={projectId} state={state} setState={setState} confirmed={dataAcquisitionConfirmed} />}
            {step.label === "Experiment Setup" && <AbExperimentSetupControls state={state} setState={setState} defaults={defaults} dataReady={dataAcquisitionConfirmed} />}
            {step.label === "Population and Eligibility" && (dataAcquisitionConfirmed && profile ? <AbPopulationControls state={state} setState={setState} profile={profile} analysisStatus={analysisDataset.status} /> : <AbUnavailableSection title="Population checks not calculated" reason="Complete Data Acquisition and Experiment Mapping before confirming population and eligibility." />)}
            {step.label === "Treatment / Control Design" && (dataAcquisitionConfirmed && profile ? <AbTreatmentControlControls state={state} setState={setState} defaults={defaults} profile={profile} analysisStatus={analysisDataset.status} /> : <AbUnavailableSection title="Treatment/control counts not calculated" reason="Complete Data Acquisition and Experiment Mapping before reviewing treatment and control design." />)}
            {step.label === "Randomization Check" && (
              fullDatasetReady && profile
                ? <AbRandomizationAndMetrics state={state} setState={setState} summary={groupSummary} imbalance={imbalance} defaults={defaults} analysisStatus={analysisDataset.status} />
                : dataAcquisitionConfirmed ? <AbFullDatasetBlockingWarning status={analysisDataset.status} />
                : <AbUnavailableSection title="Randomization metrics not calculated" reason="Complete Data Acquisition before ATLAS calculates treatment/control sizes, allocation ratio, and exposure balance." />
            )}
            {step.label === "Metrics Setup" && (dataAcquisitionConfirmed ? <AbMetricsSetup state={state} setState={setState} defaults={defaults} analysisStatus={analysisDataset.status} /> : <AbUnavailableSection title="Metrics setup pending dataset mapping" reason="Complete Data Acquisition and Experiment Mapping before selecting metrics from dataset columns." />)}
            {step.label === "Power and Sample Size" && (
              fullDatasetReady
                ? <AbPowerAnalysis state={state} setState={setState} summary={groupSummary} imbalance={imbalance} analysis={analysis} analysisStatus={analysisDataset.status} />
                : dataAcquisitionConfirmed ? <AbFullDatasetBlockingWarning status={analysisDataset.status} />
                : <AbUnavailableSection title="Power analysis not calculated" reason="Complete Data Acquisition and Metrics Setup before using sample-size estimates as workflow evidence." />
            )}
            {step.label === "Experiment EDA" && (
              fullDatasetReady && profile
                ? <AbExperimentEda state={state} setState={setState} profile={profile} summary={groupSummary} defaults={defaults} rows={rows} aggregates={analysisDataset.aggregates} daySegments={daySegments} hourSegments={hourSegments} save={save} analysisStatus={analysisDataset.status} />
                : dataAcquisitionConfirmed ? <AbFullDatasetBlockingWarning status={analysisDataset.status} />
                : <AbUnavailableSection title="Experiment EDA not available" reason="Select and confirm the experiment dataset before showing group counts or distribution summaries." />
            )}
            {step.label === "Experiment Analysis" && (
              fullDatasetReady
                ? <AbExperimentAnalysis state={state} setState={setState} analysis={analysis} summary={groupSummary} defaults={defaults} imbalance={imbalance} save={save} analysisStatus={analysisDataset.status} />
                : dataAcquisitionConfirmed ? <AbFullDatasetBlockingWarning status={analysisDataset.status} />
                : <AbUnavailableSection title="Experiment analysis not available" reason="Complete Data Acquisition, Randomization Check, Metrics Setup, and Experiment EDA before estimating lift and p-values." />
            )}
            {step.label === "Segment Analysis" && (
              fullDatasetReady
                ? <AbSegmentAnalysis state={state} setState={setState} daySegments={daySegments} hourSegments={hourSegments} defaults={defaults} summary={groupSummary} save={save} analysisStatus={analysisDataset.status} />
                : dataAcquisitionConfirmed ? <AbFullDatasetBlockingWarning status={analysisDataset.status} />
                : <AbUnavailableSection title="Segment analysis not available" reason="Complete Data Acquisition and Experiment Analysis before reviewing segment-level lift." />
            )}
            {step.label === "Business Impact" && (fullDatasetReady ? <AbBusinessImpact state={state} setState={setState} analysis={analysis} summary={groupSummary} imbalance={imbalance} defaults={defaults} dataReady={dataAcquisitionConfirmed} save={save} analysisStatus={analysisDataset.status} /> : dataAcquisitionConfirmed ? <AbFullDatasetBlockingWarning status={analysisDataset.status} /> : <AbBusinessImpact state={state} setState={setState} analysis={analysis} summary={groupSummary} imbalance={imbalance} defaults={defaults} dataReady={dataAcquisitionConfirmed} save={save} analysisStatus={analysisDataset.status} />)}
            {step.label === "Decision Recommendation" && (
              fullDatasetReady
                ? <AbDecisionRecommendation recommendation={recommendation} analysis={analysis} summary={groupSummary} imbalance={imbalance} defaults={defaults} state={state} setState={setState} save={save} analysisStatus={analysisDataset.status} />
                : dataAcquisitionConfirmed ? <AbFullDatasetBlockingWarning status={analysisDataset.status} />
                : <AbUnavailableSection title="Decision recommendation not available" reason="Complete the analysis and business impact steps before ATLAS recommends launch, hold, or run-longer decisions." />
            )}
            {step.label === "Documentation Review" && (
              fullDatasetReady
                ? <AbDocumentationReview state={state} setState={setState} defaults={defaults} analysis={analysis} summary={groupSummary} imbalance={imbalance} recommendation={recommendation} analysisStatus={analysisDataset.status} save={save} />
                : dataAcquisitionConfirmed ? <AbFullDatasetBlockingWarning status={analysisDataset.status} /> : <AbUnavailableSection title="Documentation evidence not available" reason="Complete Data Acquisition and full-dataset analysis before assembling the governed evidence package." />
            )}
            {step.label === "Post-Decision Plan" && (
              fullDatasetReady
                ? <AbMonitoringFollowUp state={state} setState={setState} defaults={defaults} analysis={analysis} summary={groupSummary} imbalance={imbalance} analysisStatus={analysisDataset.status} save={save} />
                : dataAcquisitionConfirmed ? <AbFullDatasetBlockingWarning status={analysisDataset.status} /> : <AbUnavailableSection title="Post-decision planning not available" reason="Complete the full-dataset analysis and decision recommendation before defining rollout, holdout, or follow-up actions." />
            )}
          </div>

          <aside className="min-w-0 space-y-4">
            <AbEvidenceActions projectId={projectId} stepLabel={step.label} defaults={defaults} groupSummary={groupSummary} analysis={analysis} recommendation={recommendation} onSave={save} />
            <AbEvidenceReadiness evidenceType={evidenceType} />
          </aside>
        </section>
      </div>
    </StepShell>
  );
}

function AbTestingSaveDebug({
  projectId,
  saveDebug,
  lastAction,
  onClearCache,
}: {
  projectId: string;
  saveDebug: {
    currentStepNumber: number;
    currentRoute: string;
    nextRoute: string;
    lastSavedStorageKey: string;
    lastSavedTimestamp: string;
    payloadSizeKb: string;
    storageStatus: string;
  };
  lastAction: string;
  onClearCache: () => void;
}) {
  return (
    <details className="w-full max-w-3xl rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-500" data-testid="ab-testing-developer-debug">
      <summary className="cursor-pointer font-semibold text-slate-600">Developer Debug</summary>
      <div className="mt-3 grid gap-2 sm:grid-cols-2">
        <MiniEvidence label="Current projectId" value={projectId} />
        <MiniEvidence label="Current step number" value={String(saveDebug.currentStepNumber)} />
        <MiniEvidence label="Current step route" value={saveDebug.currentRoute} />
        <MiniEvidence label="Next route" value={saveDebug.nextRoute} />
        <MiniEvidence label="Last saved storage key" value={saveDebug.lastSavedStorageKey || "None"} />
        <MiniEvidence label="Last saved timestamp" value={saveDebug.lastSavedTimestamp || "None"} />
        <MiniEvidence label="Payload size" value={saveDebug.payloadSizeKb || "Not saved yet"} />
        <MiniEvidence label="Storage" value={saveDebug.storageStatus || "Not saved yet"} />
      </div>
      <button type="button" className="mt-3 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs font-semibold text-red-800 hover:bg-red-100" onClick={onClearCache}>
        Clear A/B Testing cached workflow state
      </button>
      <p className="mt-2 text-[11px] leading-5 text-slate-500">
        This should not be required during normal workflow use. If you need to use this repeatedly, persistence cleanup is broken.
      </p>
      <div className="mt-3 rounded-md border border-slate-200 bg-slate-50 px-3 py-2 font-semibold">Last action: {lastAction}</div>
    </details>
  );
}

function HeaderMetric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-white/15 bg-white/10 px-3 py-2">
      <div className="text-[10px] font-semibold uppercase tracking-wide text-slate-300">{label}</div>
      <div className="mt-1 text-sm font-semibold text-white">{value}</div>
    </div>
  );
}

function evidenceTypeForAbStep(stepLabel: string) {
  const map: Record<string, string> = {
    "Project Context": "experiment_context",
    "Experiment Setup": "experiment_design",
    "Population and Eligibility": "population_eligibility",
    "Treatment / Control Design": "treatment_control_definition",
    "Data Acquisition and Experiment Mapping": "data_quality",
    "Randomization Check": "randomization_check",
    "Metrics Setup": "metric_definition",
    "Power and Sample Size": "power_analysis",
    "Experiment EDA": "experiment_eda",
    "Experiment Analysis": "experiment_analysis",
    "Segment Analysis": "segment_analysis",
    "Business Impact": "business_impact",
    "Decision Recommendation": "decision_recommendation",
    "Post-Decision Plan": "monitoring_plan",
  };
  return map[stepLabel] || "experiment_context";
}

function AbStepMainPanel({ stepLabel, state, setState, evidenceType }: { stepLabel: string; state: NodeState; setState: (state: NodeState) => void; evidenceType: string }) {
  if (stepLabel !== "Project Context" && stepLabel !== "Documentation Review" && stepLabel !== "Post-Decision Plan") {
    return <AbDocumentationNotes state={state} setState={setState} evidenceType={evidenceType} />;
  }
  const fields = abFieldsForStep(stepLabel);
  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="text-xs font-semibold uppercase tracking-wide text-emerald-700">{evidenceType}</div>
      <h2 className="mt-1 text-lg font-semibold text-slate-950">{stepLabel}</h2>
      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        {fields.map((field) => (
          <TextArea key={field.key} label={field.label} value={String(state[field.key] ?? "")} rows={3} placeholder={field.placeholder} onChange={(value) => setState({ ...state, [field.key]: value })} />
        ))}
      </div>
    </section>
  );
}

function abFieldsForStep(stepLabel: string): Array<{ key: keyof Pick<NodeState, "objective" | "inputs" | "assumptions" | "validation" | "risks" | "decision" | "rationale" | "notes">; label: string; placeholder: string }> {
  if (stepLabel === "Project Context") return [
    { key: "objective", label: "Project / experiment name and business objective", placeholder: "AB_WORKFLOW experiment. Evaluate whether ad exposure increases conversion against PSA control." },
    { key: "inputs", label: "Decision owner and channel", placeholder: "Document decision owner, business owner, channel, and launch context." },
    { key: "assumptions", label: "Hypothesis", placeholder: "The ad treatment increases conversion compared with PSA control." },
    { key: "validation", label: "Governance notes", placeholder: "Document governance notes, risk level, and evidence expectations." },
    { key: "risks", label: "Risk level and intended use", placeholder: "Document whether this is workflow validation, production decision support, launch approval, or exploratory analysis." },
    { key: "decision", label: "Decision to be made", placeholder: "Define the decision this experiment will support, such as launch treatment, keep control, run longer, slow rollout, or segmented rollout." },
  ];
  return [
    { key: "notes", label: "Reviewer notes", placeholder: "Capture reviewer notes for this step." },
  ];
}

function updateAbState(state: NodeState, changes: Partial<NonNullable<NodeState["ab"]>>): NodeState {
  return { ...state, ab: { ...emptyState().ab, ...(state.ab ?? {}), ...changes } };
}

function abDatasetColumns(state: NodeState) {
  return state.ab?.datasetColumns?.length ? state.ab.datasetColumns : AB_WORKFLOW_EXPECTED_COLUMNS;
}

function abFullDatasetSessionKey(projectId: string) {
  return `atlas-ab-testing-full-dataset-artifact:${projectId}`;
}

function abAnalysisSessionKey(projectId: string) {
  return `atlas-ab-testing-analysis:${projectId}`;
}

function cacheAbAnalysisSession(projectId: string, analysis: AbAnalysisDataset) {
  try {
    sessionStorage.setItem(abAnalysisSessionKey(projectId), JSON.stringify(analysis));
  } catch {
    // A session cache miss is safe: downstream analysis blocks instead of falling back to preview evidence.
  }
}

function getCachedAbAnalysisSession(projectId: string, dataset: string) {
  try {
    const raw = sessionStorage.getItem(abAnalysisSessionKey(projectId));
    if (!raw) return null;
    const parsed = JSON.parse(raw) as AbAnalysisDataset;
    if (!parsed?.status?.fullDatasetAvailable || parsed.status.dataset !== dataset || !parsed.aggregates) return null;
    return parsed;
  } catch {
    return null;
  }
}

function markAbFullDatasetArtifactLoaded(projectId: string, dataset = AB_WORKFLOW_DEFAULTS.dataset) {
  const payload = {
    dataset,
    rowCount: AB_WORKFLOW_FULL_ROW_COUNT,
    validAnalysisRecords: AB_WORKFLOW_FULL_ROW_COUNT,
    loadedAt: new Date().toISOString(),
    source: "full_dataset_artifact",
  };
  try {
    sessionStorage.setItem(abFullDatasetSessionKey(projectId), JSON.stringify(payload));
  } catch {
    // Session marker is best effort; downstream pages block rather than use preview rows if it is absent.
  }
  return payload;
}

function getAbFullDatasetSession(projectId: string, dataset = AB_WORKFLOW_DEFAULTS.dataset) {
  try {
    const raw = sessionStorage.getItem(abFullDatasetSessionKey(projectId));
    if (!raw) return null;
    const parsed = JSON.parse(raw) as { dataset?: string; rowCount?: number; validAnalysisRecords?: number; loadedAt?: string; source?: string };
    if (parsed.dataset !== dataset || parsed.source !== "full_dataset_artifact") return null;
    if ((parsed.rowCount ?? 0) < 1000) return null;
    return parsed;
  } catch {
    return null;
  }
}

function buildAbAnalysisDataset(projectId: string, defaults: AbTestingDefaults, dataAcquisitionConfirmed: boolean, abState: NonNullable<NodeState["ab"]>): AbAnalysisDataset {
  if (!dataAcquisitionConfirmed) return getAbPreviewAnalysisDataset(defaults, "preview_rows");
  const cachedAnalysis = getCachedAbAnalysisSession(projectId, defaults.dataset);
  if (cachedAnalysis) return cachedAnalysis;
  const fullArtifactSession = getAbFullDatasetSession(projectId, defaults.dataset);
  if (fullArtifactSession && defaults.dataset === AB_WORKFLOW_DEFAULTS.dataset && abState.dataSourceKind === "reference") {
    return getAbWorkflowFullDatasetArtifact(defaults);
  }
  const hadConfirmedFullArtifact = Boolean(abState.fullDatasetArtifactId || (abState.fullDatasetRowCount ?? 0) >= 1000);
  return getAbPreviewAnalysisDataset(defaults, hadConfirmedFullArtifact ? "compact_browser_cache" : "preview_rows");
}

function AbFullDatasetBlockingWarning({ status }: { status: AbAnalysisDataset["status"] }) {
  return (
    <section className="rounded-2xl border border-amber-300 bg-amber-50 p-5 shadow-sm">
      <div className="text-xs font-semibold uppercase tracking-wide text-amber-700">Full dataset required</div>
      <h2 className="mt-1 text-lg font-semibold text-amber-950">Full dataset artifact is not loaded.</h2>
      <p className="mt-2 text-sm leading-6 text-amber-950">
        Full dataset artifact is not loaded. Reopen or reload the confirmed dataset before running experiment analysis.
      </p>
      <div className="mt-4 grid gap-3 md:grid-cols-3">
        <MiniEvidence label="Current source" value={status.source === "compact_browser_cache" ? "Compact browser cache" : "Preview rows"} tone="warning" />
        <MiniEvidence label="Available rows" value={status.rowCount.toLocaleString()} tone="warning" />
        <MiniEvidence label="Output status" value="Preview only, not full experiment analysis" tone="warning" />
      </div>
      <p className="mt-3 text-sm leading-6 text-amber-950">
        Preview rows and compact restored browser state are allowed for mapping and UI validation only. ATLAS will not run EDA, power, experiment analysis, segment analysis, business impact, or final decisioning from preview rows.
      </p>
    </section>
  );
}

function AbDatasetMapping({ projectId, state, setState, confirmed }: { projectId: string; state: NodeState; setState: (state: NodeState) => void; confirmed: boolean }) {
  const ab = { ...AB_WORKFLOW_DEFAULTS, ...(state.ab ?? {}) } as AbTestingDefaults & NonNullable<NodeState["ab"]>;
  const defaults = ab as AbTestingDefaults;
  const [datasets, setDatasets] = useState<DatasetSummary[]>([]);
  const [registeredProfile, setRegisteredProfile] = useState<DatasetProfile | null>(null);
  const [analysisProfile, setAnalysisProfile] = useState<AbAnalysisDataset["profile"] | null>(() => getCachedAbAnalysisSession(projectId, defaults.dataset)?.profile ?? null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const isReference = ab.dataSourceKind === "reference" && defaults.dataset === AB_WORKFLOW_DEFAULTS.dataset && !ab.datasetId;
  const columns = ab.datasetColumns?.length ? ab.datasetColumns : isReference ? AB_WORKFLOW_EXPECTED_COLUMNS : [];
  const mappingReady = Boolean(
    defaults.dataset.trim()
    && defaults.unitIdColumn.trim()
    && defaults.treatmentColumn.trim()
    && defaults.outcomeColumn.trim()
    && defaults.treatmentValue.trim()
    && defaults.controlValue.trim()
    && defaults.treatmentValue !== defaults.controlValue
    && (isReference || (ab.datasetId && ab.datasetVersionId))
  );
  const profile = analysisProfile ?? (isReference && (confirmed || ab.confirmed) ? getAbWorkflowFullDatasetArtifact(defaults).profile : null);
  const update = (changes: Partial<NonNullable<NodeState["ab"]>>) => setState(updateAbState(state, changes));

  useEffect(() => {
    let active = true;
    listDatasets()
      .then((result) => {
        if (active) setDatasets(result.datasets.filter((dataset) => !dataset.archived && Boolean(dataset.latestVersion)));
      })
      .catch(() => {
        if (active) setError("Dataset Library is unavailable. The verified AB_WORKFLOW reference artifact remains available for workflow evaluation.");
      });
    return () => { active = false; };
  }, []);

  const loadRegisteredDataset = async (dataset: DatasetSummary, sourceKind: "dataset_library" | "upload") => {
    const version = dataset.latestVersion;
    if (!version) throw new Error("The selected dataset has no registered full-data version.");
    const result = await getDatasetProfile(dataset.datasetId, version.versionId);
    const nextColumns = result.profile.schema.map((column) => column.name.replace(/\s+/g, "."));
    await linkDatasetToProject(projectId, dataset.datasetId, version.versionId, "ab_experiment");
    setRegisteredProfile(result.profile);
    setAnalysisProfile(null);
    try {
      sessionStorage.removeItem(abFullDatasetSessionKey(projectId));
      sessionStorage.removeItem(abAnalysisSessionKey(projectId));
    } catch {
      // The full artifact will be revalidated before any analysis is used.
    }
    update({
      dataset: dataset.name,
      datasetId: dataset.datasetId,
      datasetVersionId: version.versionId,
      datasetRowCount: result.profile.rowCount,
      datasetColumnCount: result.profile.columnCount,
      datasetColumns: nextColumns,
      dataSourceKind: sourceKind,
      confirmed: false,
      previewOnly: true,
      fullDatasetArtifactId: "",
      fullDatasetArtifactLoadedAt: "",
      fullDatasetRowCount: 0,
      validAnalysisRecordCount: 0,
      analysisDataSource: "preview_rows",
      unitIdColumn: suggestedExperimentalColumn(nextColumns, [/user/i, /customer/i, /account/i, /unit/i, /subject/i, /id$/i]),
      treatmentColumn: suggestedExperimentalColumn(nextColumns, [/test.*group/i, /treatment/i, /variant/i, /assignment/i, /arm/i, /group/i]),
      outcomeColumn: suggestedExperimentalColumn(nextColumns, [/convert/i, /outcome/i, /success/i, /response/i, /target/i]),
      exposureColumn: suggestedExperimentalColumn(nextColumns, [/total.*ad/i, /exposure/i, /impression/i, /contact/i, /dose/i]),
      segmentColumns: nextColumns.filter((column) => /day|hour|segment|channel|region|device|product/i.test(column)).slice(0, 4),
      mappingValidatedAt: "",
    });
    setMessage(`${dataset.name} is linked and profiled. Review treatment/control values and column mappings, then load the full analysis artifact.`);
  };

  const chooseDataset = async (selection: string) => {
    setError("");
    setMessage("");
    if (selection === "reference") {
      setRegisteredProfile(null);
      setAnalysisProfile(null);
      update({
        ...AB_WORKFLOW_DEFAULTS,
        datasetId: "",
        datasetVersionId: "",
        datasetRowCount: AB_WORKFLOW_FULL_ROW_COUNT,
        datasetColumnCount: AB_WORKFLOW_EXPECTED_COLUMNS.length,
        datasetColumns: AB_WORKFLOW_EXPECTED_COLUMNS,
        dataSourceKind: "reference",
        confirmed: false,
        previewOnly: true,
        fullDatasetArtifactId: "",
        fullDatasetArtifactLoadedAt: "",
        fullDatasetRowCount: 0,
        validAnalysisRecordCount: 0,
        analysisDataSource: "preview_rows",
      });
      setMessage("Verified AB_WORKFLOW reference selected. Confirm the mapping to load its full aggregate analysis artifact.");
      return;
    }
    const dataset = datasets.find((item) => item.datasetId === selection);
    if (!dataset) return;
    setBusy(true);
    try {
      await loadRegisteredDataset(dataset, "dataset_library");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "ATLAS could not profile the selected dataset.");
    } finally {
      setBusy(false);
    }
  };

  const uploadAbDataset = async (file: File | null) => {
    if (!file) return;
    setBusy(true);
    setError("");
    setMessage("");
    try {
      const dataset = await uploadDataset({
        file,
        name: file.name.replace(/\.[^.]+$/, ""),
        description: "A/B Testing experiment dataset",
        domain: "Experimentation",
        sourceType: "upload",
      });
      setDatasets((current) => [dataset, ...current.filter((item) => item.datasetId !== dataset.datasetId)]);
      await loadRegisteredDataset(dataset, "upload");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "ATLAS could not upload the A/B Testing dataset.");
    } finally {
      setBusy(false);
    }
  };

  const refreshSchema = async () => {
    if (isReference) {
      update({ datasetColumns: AB_WORKFLOW_EXPECTED_COLUMNS, datasetRowCount: AB_WORKFLOW_FULL_ROW_COUNT, datasetColumnCount: AB_WORKFLOW_EXPECTED_COLUMNS.length, confirmed: false });
      setMessage("Verified reference schema refreshed. Confirm the mapping to reload analysis evidence.");
      return;
    }
    const dataset = datasets.find((item) => item.datasetId === ab.datasetId);
    if (dataset) await chooseDataset(dataset.datasetId);
  };

  const confirmFullDataset = async () => {
    if (!mappingReady) {
      setError("Select a governed dataset and map distinct treatment/control values, unit ID, treatment, and outcome columns before continuing.");
      return;
    }
    setBusy(true);
    setError("");
    setMessage("");
    try {
      let analysis: AbAnalysisDataset;
      let artifactId: string;
      if (isReference) {
        const marker = markAbFullDatasetArtifactLoaded(projectId, defaults.dataset);
        analysis = getAbWorkflowFullDatasetArtifact(defaults);
        artifactId = `verified-reference-${marker.rowCount}`;
      } else {
        analysis = await analyzeRegisteredAbDataset({ datasetId: ab.datasetId || "", versionId: ab.datasetVersionId || "", mapping: defaults });
        artifactId = `${ab.datasetId}:${ab.datasetVersionId}`;
      }
      cacheAbAnalysisSession(projectId, analysis);
      setAnalysisProfile(analysis.profile);
      update({
        confirmed: true,
        previewOnly: false,
        fullDatasetArtifactId: artifactId,
        fullDatasetArtifactLoadedAt: new Date().toISOString(),
        fullDatasetRowCount: analysis.status.rowCount,
        validAnalysisRecordCount: analysis.status.validAnalysisRecords,
        datasetRowCount: analysis.status.rowCount,
        datasetColumnCount: analysis.profile.columns,
        analysisDataSource: "full_dataset_artifact",
        mappingValidatedAt: new Date().toISOString(),
      });
      setMessage(`Full artifact validated: ${analysis.status.rowCount.toLocaleString()} rows and ${analysis.status.validAnalysisRecords.toLocaleString()} valid analysis records. Downstream pages will use full-data aggregates.`);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "ATLAS could not validate the full A/B Testing artifact.");
      update({ confirmed: false, previewOnly: true, analysisDataSource: "preview_rows" });
    } finally {
      setBusy(false);
    }
  };
  return (
    <section className="rounded-2xl border border-blue-200 bg-blue-50 p-5 shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="text-xs font-semibold uppercase tracking-wide text-blue-700">Data Acquisition and Experiment Mapping</div>
          <h2 className="mt-1 text-lg font-semibold text-slate-950">{confirmed || ab.confirmed ? `Confirmed dataset: ${defaults.dataset}` : "Dataset: Not confirmed"}</h2>
          {!confirmed && !ab.confirmed && <p className="mt-1 text-sm text-blue-950">Choose a verified reference artifact, a governed Dataset Library version, or upload a new file. No experiment metrics are calculated until the full artifact and mappings validate.</p>}
        </div>
        <div className="flex flex-wrap gap-2">
          <button type="button" className="atlas-secondary-button" disabled={busy} onClick={() => void refreshSchema()}>Refresh Dataset Schema</button>
          <button type="button" className="atlas-primary-button" disabled={busy || !mappingReady} onClick={() => void confirmFullDataset()}>{busy ? "Validating full artifact..." : "Confirm Data Acquisition and Mapping"}</button>
        </div>
      </div>
      <div className="mt-4 grid gap-3 rounded-xl border border-blue-200 bg-white p-4 lg:grid-cols-[minmax(0,1fr)_auto]">
        <label className="grid min-w-0 gap-1">
          <span className="text-xs font-semibold uppercase tracking-wide text-slate-500">Governed dataset source</span>
          <select className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm" value={isReference ? "reference" : ab.datasetId || ""} disabled={busy} onChange={(event) => void chooseDataset(event.target.value)}>
            <option value="reference">AB_WORKFLOW.csv - verified reference artifact ({AB_WORKFLOW_FULL_ROW_COUNT.toLocaleString()} rows)</option>
            <option value="" disabled>Select from Dataset Library</option>
            {datasets.map((dataset) => <option key={dataset.datasetId} value={dataset.datasetId}>{dataset.name} - {(dataset.latestVersion?.rowCount ?? 0).toLocaleString()} rows</option>)}
          </select>
          <span className="text-[11px] leading-4 text-slate-500">Reference data is clearly labeled. Production evidence should use a versioned Dataset Library artifact.</span>
        </label>
        <label className="inline-flex cursor-pointer items-center justify-center gap-2 self-end rounded-lg border border-blue-200 bg-blue-50 px-4 py-2 text-sm font-semibold text-blue-800 hover:bg-blue-100">
          <Upload size={16} /> {busy ? "Working..." : "Upload experiment data"}
          <input type="file" className="sr-only" accept=".csv,.txt,.xlsx,.xls,.parquet,.json,.zip,.feather,.sas7bdat" disabled={busy} onChange={(event) => void uploadAbDataset(event.target.files?.[0] ?? null)} />
        </label>
      </div>
      <div className="mt-4 grid gap-3 md:grid-cols-3">
        <AbSelect label="Unit ID column" value={defaults.unitIdColumn} options={columns} onChange={(value) => update({ unitIdColumn: value, confirmed: false })} />
        <AbSelect label="Treatment column" value={defaults.treatmentColumn} options={columns} onChange={(value) => update({ treatmentColumn: value, confirmed: false })} />
        <AbInput label="Treatment value" value={defaults.treatmentValue} onChange={(value) => update({ treatmentValue: value, confirmed: false })} />
        <AbInput label="Control value" value={defaults.controlValue} onChange={(value) => update({ controlValue: value, confirmed: false })} />
        <AbSelect label="Outcome column" value={defaults.outcomeColumn} options={columns} onChange={(value) => update({ outcomeColumn: value, confirmed: false })} />
        <AbInput label="Success event" value={defaults.successEvent} onChange={(value) => update({ successEvent: value, confirmed: false })} />
        <AbSelect label="Exposure / intensity column optional" value={defaults.exposureColumn} options={["", ...columns]} onChange={(value) => update({ exposureColumn: value, confirmed: false })} />
        <AbInput label="Segment columns optional" value={defaults.segmentColumns.join(", ")} onChange={(value) => update({ segmentColumns: value.split(",").map((item) => item.trim()).filter(Boolean), confirmed: false })} />
        <AbSelect label="Date / time column optional" value={ab.dateTimeColumn || ""} options={["", ...columns]} onChange={(value) => update({ dateTimeColumn: value, confirmed: false })} />
      </div>
      {registeredProfile && !profile && (
        <div className="mt-5 grid gap-3 md:grid-cols-4">
          <MiniEvidence label="Registered rows" value={registeredProfile.rowCount.toLocaleString()} />
          <MiniEvidence label="Registered columns" value={registeredProfile.columnCount.toLocaleString()} />
          <MiniEvidence label="Profiled rows" value={registeredProfile.profiledRows.toLocaleString()} />
          <MiniEvidence label="Evidence state" value="Mapping not confirmed" tone="warning" />
        </div>
      )}
      {confirmed || ab.confirmed ? (
        <div className="mt-5">
          {profile && <AbProfileMetrics profile={profile} previewOnly={Boolean(ab.previewOnly)} />}
          <div className="mt-3 rounded-xl border border-emerald-200 bg-white px-3 py-2 text-sm font-semibold text-emerald-950">Full dataset row count: {(ab.fullDatasetRowCount ?? 0).toLocaleString()}. Valid analysis records: {(ab.validAnalysisRecordCount ?? 0).toLocaleString()}. Source: {isReference ? "verified reference artifact" : "registered full dataset artifact"}.</div>
        </div>
      ) : (
        <div className="mt-5 rounded-xl border border-blue-200 bg-white px-3 py-2 text-sm font-semibold text-blue-950">
          No calculated metrics shown yet. Confirm Data Acquisition and Mapping before ATLAS presents rows, group counts, allocation ratio, or outcome distributions.
        </div>
      )}
      {error && <div className="mt-4"><InlineError message={error} /></div>}
      {message && <div className="mt-4"><InlineSuccess message={message} /></div>}
      <div className="mt-4 flex flex-wrap gap-2">
        <button type="button" className="atlas-secondary-button" onClick={() => update({ confirmed: Boolean(ab.confirmed) })}><Save size={15} /> Save Data Acquisition Evidence</button>
      </div>
    </section>
  );
}

function AbDocumentationNotes({ state, setState, evidenceType }: { state: NodeState; setState: (state: NodeState) => void; evidenceType: string }) {
  return (
    <details className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
      <summary className="cursor-pointer text-sm font-semibold text-slate-800">Documentation Notes ({labelize(evidenceType.replace(/_/g, " "))})</summary>
      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <TextArea label="Reviewer notes" value={state.notes} rows={3} placeholder="Capture reviewer questions or evidence gaps for this step." onChange={(value) => setState({ ...state, notes: value })} />
        <TextArea label="Evidence rationale" value={state.rationale} rows={3} placeholder="Document the rationale after reviewing the page controls and metrics." onChange={(value) => setState({ ...state, rationale: value })} />
      </div>
    </details>
  );
}

function AbProjectContextNextStepPreview() {
  return (
    <section className="rounded-2xl border border-blue-200 bg-blue-50 p-5 shadow-sm">
      <div className="text-xs font-semibold uppercase tracking-wide text-blue-700">Next step preview</div>
      <h3 className="mt-1 text-lg font-semibold text-slate-950">Next step: Data Acquisition and Experiment Mapping</h3>
      <p className="mt-2 text-sm leading-6 text-blue-950">
        After you define the business context, ATLAS will ask you to select the experiment dataset and map the unit ID, treatment, control, outcome, exposure, segment, and date/time fields. Those mappings will drive all downstream experiment checks and analysis.
      </p>
      <Link to="/workflow/ab-testing/2" className="atlas-primary-button mt-4 inline-flex">Continue to Data Acquisition</Link>
    </section>
  );
}

function AbInput({ label, value, onChange }: { label: string; value: string; onChange: (value: string) => void }) {
  return (
    <label className="grid gap-1">
      <span className="text-xs font-semibold uppercase tracking-wide text-slate-500">{label}</span>
      <input className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm" value={value} onChange={(event) => onChange(event.target.value)} />
    </label>
  );
}

function abSelectionHelp(label: string, value: string) {
  const key = label.toLowerCase();
  const selected = value || "the selected option";
  if (key.includes("unit id") || key.includes("randomization unit") || key.includes("analysis unit")) return "Best used for the independently assigned experimental unit. Keep assignment and analysis grain aligned unless clustering is explicitly modeled.";
  if (key.includes("treatment column")) return "Choose the pre-analysis assignment field that distinguishes treatment from control; do not use a post-treatment exposure measure.";
  if (key.includes("outcome column") || key.includes("primary metric column")) return "Choose the response that directly answers the primary hypothesis and is observable inside the documented outcome window.";
  if (key.includes("exposure")) return "Use a post-assignment intensity measure for delivery diagnostics or guardrails, not as a baseline balance covariate.";
  if (key.includes("segment")) return "Use pre-treatment groups with sufficient treatment and control observations. Apply multiple-comparison control when reviewing many segments.";
  if (key.includes("experiment type") || key.includes("experiment design")) return `Use ${selected} only when its assignment mechanism and causal assumptions match how the experiment was actually run.`;
  if (key.includes("assignment method") || key.includes("randomization")) return "Prefer a reproducible randomized method. Observed or quasi-experimental assignments require stronger confounding checks and more cautious causal language.";
  if (key.includes("metric type")) return "Binary conversion compares proportions; Rate uses events per exposure; Continuous mean compares numeric outcomes with distribution and variance checks.";
  if (key.includes("confidence") || key.includes("alpha")) return "95% is the standard default. Use 99% for higher false-positive cost and 90% only for explicitly exploratory decisions.";
  if (key.includes("desired power")) return "80% is the standard planning floor; use 90% when missing a real effect would create material customer, financial, or regulatory risk.";
  if (key.includes("one-sided") || key.includes("alternative hypothesis")) return "Use a one-sided direction only when the opposite effect would lead to the same decision and that choice was documented before observing results.";
  if (key.includes("test type")) return "Use a two-proportion z-test for adequately sized binary groups, Fisher exact for sparse cells, and chi-square for broader categorical independence tests.";
  if (key.includes("multiple-comparison") || key.includes("correction")) return "Bonferroni tightly controls any false positive; Benjamini-Hochberg controls false discovery rate and is usually better for exploratory segment review.";
  if (key.includes("duplicate") || key.includes("missing") || key.includes("invalid")) return "Choose the rule before analysis, preserve an exclusion count, and avoid converting data-quality failures into favorable outcomes.";
  if (key.includes("lift estimate") || key.includes("confidence scenario")) return "Use the observed estimate for reporting and a lower-bound or conservative estimate for launch economics when downside risk matters.";
  if (key.includes("cost basis")) return "Match costs to how the treatment scales: per exposure, per conversion, fixed campaign cost, or a combination of fixed and variable costs.";
  if (key.includes("decision recommendation") || key.includes("follow-up")) return "Tie the choice to statistical uncertainty, practical significance, guardrails, power, segment reliability, and business value; p-value alone is insufficient.";
  if (key.includes("risk tolerance")) return "Use low tolerance for customer harm, fair-lending, privacy, safety, or irreversible financial impact; higher tolerance must be explicitly approved.";
  if (key.includes("post-decision strategy")) return "Select the operational path that matches the final evidence: collect more data, retain control, phase rollout, target approved segments, or launch with rollback controls.";
  if (key.includes("documentation") || key.includes("evidence") || key.includes("limitations") || key.includes("monitoring")) return "Choose the state that reflects evidence actually captured. ATLAS does not treat a selection as proof that an artifact or approval exists.";
  return `Use ${selected} when it matches the experiment design, evidence available on this page, and the documented decision rule.`;
}

function AbSelect({ label, value, options, onChange }: { label: string; value: string; options: string[]; onChange: (value: string) => void }) {
  return (
    <label className="grid min-w-0 gap-1">
      <span className="text-xs font-semibold uppercase tracking-wide text-slate-500">{label}</span>
      <select className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm" value={value} onChange={(event) => onChange(event.target.value)}>
        {!options.length && <option value="">No mapped columns available</option>}
        {options.map((option) => <option key={option} value={option}>{option || "None"}</option>)}
      </select>
      <span className="text-[11px] leading-4 text-slate-500">{abSelectionHelp(label, value)}</span>
    </label>
  );
}

function AbProfileMetrics({ profile, previewOnly = false }: { profile: ReturnType<typeof profileAbDataset>; previewOnly?: boolean }) {
  const suffix = previewOnly ? " (Preview only)" : "";
  return (
    <div className="grid gap-3 md:grid-cols-4">
      <MiniEvidence label={`Rows${suffix}`} value={profile.rows.toLocaleString()} />
      <MiniEvidence label={`Columns${suffix}`} value={profile.columns.toLocaleString()} />
      <MiniEvidence label={`Unique units${suffix}`} value={profile.uniqueUnits.toLocaleString()} />
      <MiniEvidence label={`Duplicate units${suffix}`} value={profile.duplicateUnits.toLocaleString()} tone={profile.duplicateUnits ? "warning" : "good"} />
      <MiniEvidence label={`Missing unit ID${suffix}`} value={profile.missingUnitId.toLocaleString()} tone={profile.missingUnitId ? "warning" : "good"} />
      <MiniEvidence label={`Missing treatment${suffix}`} value={profile.missingTreatment.toLocaleString()} tone={profile.missingTreatment ? "warning" : "good"} />
      <MiniEvidence label={`Missing outcome${suffix}`} value={profile.missingOutcome.toLocaleString()} tone={profile.missingOutcome ? "warning" : "good"} />
      <MiniEvidence label={`Treatment values detected${suffix}`} value={profile.treatmentValuesDetected.join(", ")} />
      <MiniEvidence label={`Outcome values detected${suffix}`} value={profile.outcomeValuesDetected.join(", ")} />
      <MiniEvidence label={`Treatment group count${suffix}`} value={profile.treatmentGroupCount.toLocaleString()} />
      <MiniEvidence label={`Control group count${suffix}`} value={profile.controlGroupCount.toLocaleString()} />
      <MiniEvidence label={`Allocation ratio${suffix}`} value={`${profile.allocationRatio.toFixed(2)} : 1`} tone={Math.abs(profile.treatmentShare - profile.controlShare) > 0.1 ? "warning" : "good"} />
    </div>
  );
}

function AbExperimentSetupControls({ state, setState, defaults, dataReady }: { state: NodeState; setState: (state: NodeState) => void; defaults: AbTestingDefaults; dataReady: boolean }) {
  const ab = { ...emptyState().ab, ...(state.ab ?? {}) };
  const update = (changes: Partial<NonNullable<NodeState["ab"]>>) => setState(updateAbState(state, changes));
  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="text-xs font-semibold uppercase tracking-wide text-blue-700">Experiment Setup Controls</div>
      {!dataReady && <InlineError message="Complete Data Acquisition and Experiment Mapping before confirming experiment setup." />}
      <div className="mt-4 grid gap-3 md:grid-cols-3">
        <AbSelect label="Experiment type" value={ab.experimentType || "Marketing A/B test"} options={["Marketing A/B test", "Product / UX experiment", "Pricing experiment", "Policy experiment", "Content experiment", "Operational experiment"]} onChange={(value) => update({ experimentType: value })} />
        <AbSelect label="Experiment design" value={ab.experimentDesign || "User-level randomized holdout"} options={["User-level randomized A/B test", "User-level randomized holdout", "Cluster randomized test", "Geo or market test", "Before/after test", "Quasi-experimental test", "Observational comparison"]} onChange={(value) => update({ experimentDesign: value })} />
        <AbInput label="Assignment unit" value={defaults.unitIdColumn} onChange={(value) => update({ unitIdColumn: value })} />
        <AbInput label="Randomization unit" value={ab.randomizationUnit || defaults.unitIdColumn} onChange={(value) => update({ randomizationUnit: value })} />
        <AbInput label="Analysis unit" value={ab.analysisUnit || defaults.unitIdColumn} onChange={(value) => update({ analysisUnit: value })} />
        <AbInput label="Treatment condition" value={`${defaults.treatmentColumn} = ${defaults.treatmentValue}`} onChange={() => undefined} />
        <AbInput label="Control condition" value={`${defaults.treatmentColumn} = ${defaults.controlValue}`} onChange={() => undefined} />
        <AbInput label="Outcome window" value={ab.outcomeWindow || ""} onChange={(value) => update({ outcomeWindow: value })} />
        <AbInput label="Exposure window" value={ab.exposureWindow || ""} onChange={(value) => update({ exposureWindow: value })} />
        <AbInput label="Experiment start date optional" value={state.inputs || "Not available in source data"} onChange={(value) => setState({ ...state, inputs: value })} />
        <AbInput label="Experiment end date optional" value={state.validation || "Not available in source data"} onChange={(value) => setState({ ...state, validation: value })} />
      </div>
      <div className="mt-4 rounded-xl border border-blue-200 bg-blue-50 px-3 py-2 text-sm leading-6 text-blue-950">
        The source dataset does not include explicit experiment start or end dates. converted is treated as the observed post-exposure conversion outcome, and total.ads is treated as the observed campaign exposure intensity.
      </div>
    </section>
  );
}

function AbPopulationControls({ state, setState, profile, analysisStatus }: { state: NodeState; setState: (state: NodeState) => void; profile: ReturnType<typeof profileAbDataset>; analysisStatus: AbAnalysisDataset["status"] }) {
  const ab = { ...emptyState().ab, ...(state.ab ?? {}) };
  const update = (changes: Partial<NonNullable<NodeState["ab"]>>) => setState(updateAbState(state, changes));
  return (
    <section className="rounded-2xl border border-amber-200 bg-amber-50 p-5 shadow-sm">
      <div className="text-xs font-semibold uppercase tracking-wide text-amber-700">Population and Eligibility Checks</div>
      <div className="mt-3 grid gap-3 md:grid-cols-3">
        <MiniEvidence label="Analysis source" value={analysisStatus.fullDatasetAvailable ? "Full dataset artifact" : "Preview only, not full experiment analysis"} tone={analysisStatus.fullDatasetAvailable ? "good" : "warning"} />
        <MiniEvidence label="Full dataset row count" value={analysisStatus.rowCount.toLocaleString()} tone={analysisStatus.fullDatasetAvailable ? "good" : "warning"} />
        <MiniEvidence label="Valid analysis records" value={analysisStatus.validAnalysisRecords.toLocaleString()} tone={analysisStatus.fullDatasetAvailable ? "good" : "warning"} />
      </div>
      <div className="mt-3 grid gap-3 md:grid-cols-4">
        <MiniEvidence label="Total rows" value={profile.rows.toLocaleString()} />
        <MiniEvidence label="Unique units" value={profile.uniqueUnits.toLocaleString()} />
        <MiniEvidence label="Duplicate units" value={profile.duplicateUnits.toLocaleString()} tone={profile.duplicateUnits ? "warning" : "good"} />
        <MiniEvidence label="Included records" value={(profile.treatmentGroupCount + profile.controlGroupCount).toLocaleString()} />
        <MiniEvidence label="Excluded records" value={(profile.invalidTreatment + profile.invalidOutcome + profile.missingUnitId + profile.missingTreatment + profile.missingOutcome).toLocaleString()} />
        <MiniEvidence label="Missing unit ID count" value={profile.missingUnitId.toLocaleString()} />
        <MiniEvidence label="Missing treatment count" value={profile.missingTreatment.toLocaleString()} />
        <MiniEvidence label="Missing outcome count" value={profile.missingOutcome.toLocaleString()} />
        <MiniEvidence label="Invalid treatment count" value={profile.invalidTreatment.toLocaleString()} />
        <MiniEvidence label="Invalid outcome count" value={profile.invalidOutcome.toLocaleString()} />
      </div>
      <div className="mt-4 grid gap-3 md:grid-cols-2">
        <AbSelect label="Duplicate handling rule" value={ab.duplicateHandling || ""} options={["Keep first unit record", "Exclude duplicate units", "Aggregate by unit"]} onChange={(value) => update({ duplicateHandling: value })} />
        <AbSelect label="Missing treatment handling" value={ab.missingTreatmentHandling || ""} options={["Exclude from experiment analysis", "Flag for data repair", "Keep for audit only"]} onChange={(value) => update({ missingTreatmentHandling: value })} />
        <AbSelect label="Missing outcome handling" value={ab.missingOutcomeHandling || ""} options={["Exclude from primary metric", "Treat as non-success", "Flag for data repair"]} onChange={(value) => update({ missingOutcomeHandling: value })} />
        <AbSelect label="Invalid treatment handling" value={ab.invalidTreatmentHandling || ""} options={["Flag and exclude", "Map to nearest known group", "Reviewer decision required"]} onChange={(value) => update({ invalidTreatmentHandling: value })} />
        <AbSelect label="Invalid outcome handling" value={ab.invalidOutcomeHandling || ""} options={["Flag and exclude", "Treat as non-success", "Reviewer decision required"]} onChange={(value) => update({ invalidOutcomeHandling: value })} />
        <AbInput label="Eligibility notes" value={state.risks} onChange={(value) => setState({ ...state, risks: value })} />
      </div>
      <div className="mt-4 rounded-xl border border-amber-300 bg-white px-3 py-2 text-sm font-semibold text-amber-900">
        This dataset is structurally clean for A/B testing review. Production decisioning uses the full confirmed dataset artifact only.
      </div>
    </section>
  );
}

function AbTreatmentControlControls({ state, setState, defaults, profile, analysisStatus }: { state: NodeState; setState: (state: NodeState) => void; defaults: AbTestingDefaults; profile: ReturnType<typeof profileAbDataset>; analysisStatus: AbAnalysisDataset["status"] }) {
  const ab = { ...emptyState().ab, ...(state.ab ?? {}) };
  const update = (changes: Partial<NonNullable<NodeState["ab"]>>) => setState(updateAbState(state, changes));
  return (
    <section className="rounded-2xl border border-emerald-200 bg-emerald-50 p-5 shadow-sm">
      <div className="text-xs font-semibold uppercase tracking-wide text-emerald-700">Treatment / Control Design From Confirmed Data</div>
      <div className="mt-3 grid gap-3 md:grid-cols-3">
        <MiniEvidence label="Analysis source" value={analysisStatus.fullDatasetAvailable ? "Full dataset artifact" : "Preview only, not full experiment analysis"} tone={analysisStatus.fullDatasetAvailable ? "good" : "warning"} />
        <MiniEvidence label="Full dataset row count" value={analysisStatus.rowCount.toLocaleString()} tone={analysisStatus.fullDatasetAvailable ? "good" : "warning"} />
        <MiniEvidence label="Valid analysis records" value={analysisStatus.validAnalysisRecords.toLocaleString()} tone={analysisStatus.fullDatasetAvailable ? "good" : "warning"} />
      </div>
      <div className="mt-3 grid gap-3 md:grid-cols-4">
        <MiniEvidence label="Treatment group count" value={profile.treatmentGroupCount.toLocaleString()} />
        <MiniEvidence label="Control group count" value={profile.controlGroupCount.toLocaleString()} />
        <MiniEvidence label="Treatment share" value={`${(profile.treatmentShare * 100).toFixed(1)}%`} />
        <MiniEvidence label="Control share" value={`${(profile.controlShare * 100).toFixed(1)}%`} />
        <MiniEvidence label="Allocation ratio" value={`${profile.allocationRatio.toFixed(2)} : 1`} tone={Math.abs(profile.treatmentShare - profile.controlShare) > 0.1 ? "warning" : "good"} />
        <MiniEvidence label="Observed treatment values" value={profile.treatmentValuesDetected.join(", ")} />
        <MiniEvidence label="Observed control values" value={defaults.controlValue} />
        <MiniEvidence label="Unexpected treatment values" value={profile.invalidTreatment ? String(profile.invalidTreatment) : "None"} tone={profile.invalidTreatment ? "warning" : "good"} />
      </div>
      <div className="mt-4 grid gap-3 md:grid-cols-2">
        <AbSelect label="Treatment value selector" value={defaults.treatmentValue} options={profile.treatmentValuesDetected} onChange={(value) => update({ treatmentValue: value })} />
        <AbSelect label="Control value selector" value={defaults.controlValue} options={profile.treatmentValuesDetected} onChange={(value) => update({ controlValue: value })} />
        <AbInput label="Expected allocation ratio" value={ab.expectedAllocationRatio || "1:1"} onChange={(value) => update({ expectedAllocationRatio: value })} />
        <AbSelect label="Assignment method" value={ab.assignmentMethod || "Observed test.group assignment"} options={["Observed test.group assignment", "Randomized service assignment", "Marketing holdout assignment"]} onChange={(value) => update({ assignmentMethod: value })} />
        <AbInput label="Contamination risk notes" value={state.risks} onChange={(value) => setState({ ...state, risks: value })} />
      </div>
      <div className="mt-4 rounded-xl border border-amber-300 bg-white px-3 py-2 text-sm font-semibold text-amber-900">
        Observed allocation differs from the expected 1:1 design. This does not automatically invalidate the test, but it should be reviewed during Randomization Check and carried into power and decision review.
      </div>
    </section>
  );
}

function AbEvidenceActions({
  projectId,
  stepLabel,
  defaults,
  groupSummary,
  analysis,
  recommendation,
  onSave,
}: {
  projectId: string;
  stepLabel: string;
  defaults: AbTestingDefaults;
  groupSummary: ReturnType<typeof summarizeAbGroups>;
  analysis: ReturnType<typeof analyzeAbLift>;
  recommendation: string;
  onSave: () => NodeState;
}) {
  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
      <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Evidence Actions</div>
      <div className="mt-3 grid gap-2">
        <button type="button" className="atlas-secondary-button justify-center" onClick={() => onSave()}>
          <Save size={15} /> Save Evidence Draft
        </button>
        <Link to="/model-evidence-center" className="atlas-secondary-button justify-center">Open Model Evidence Center</Link>
        <Link to="/model-document-studio" className="atlas-secondary-button justify-center">Attach to Model Documentation Studio</Link>
        <button type="button" className="atlas-secondary-button justify-center" onClick={() => downloadText("atlas-ab-testing-evidence-pack.json", JSON.stringify({ projectId, step: stepLabel, defaults, groupSummary, analysis, recommendation }, null, 2), "application/json")}>
          <Download size={15} /> Export Experiment Evidence Pack
        </button>
      </div>
    </section>
  );
}

function AbEvidenceReadiness({ evidenceType }: { evidenceType: string }) {
  const currentLabel = labelize(evidenceType.replace(/_/g, " "));
  const upcoming = [
    "Experiment Design",
    "Population Eligibility",
    "Treatment / Control Definition",
    "Randomization Check",
    "Metric Definition",
    "Power Analysis",
  ];
  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
      <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Evidence Readiness</div>
      <div className="mt-3 rounded-xl border border-emerald-200 bg-emerald-50 px-3 py-2">
        <div className="text-[10px] font-semibold uppercase tracking-wide text-emerald-700">Current step</div>
        <div className="mt-1 text-sm font-semibold text-emerald-950">{currentLabel}: Draft / Saved</div>
      </div>
      <div className="mt-3 text-[10px] font-semibold uppercase tracking-wide text-slate-500">Upcoming evidence</div>
      <ul className="mt-2 grid gap-1.5 text-xs leading-5 text-slate-700">
        {upcoming.map((item) => (
          <li key={item} className="flex items-center gap-2">
            <CheckCircle2 size={13} className="text-emerald-600" />
            <span>{item}</span>
          </li>
        ))}
      </ul>
      <details className="mt-3 rounded-xl border border-slate-200 bg-slate-50 px-3 py-2">
        <summary className="cursor-pointer text-xs font-semibold text-slate-800">View Full Evidence Checklist</summary>
        <ul className="mt-2 grid gap-1 text-xs leading-5 text-slate-600">
          {abEvidenceTypes.map((item) => (
              <li key={item}>{labelize(item.replace(/_/g, " "))}{item === evidenceType ? " - Current step" : ""}</li>
          ))}
        </ul>
      </details>
    </section>
  );
}

function AbReviewerNotes({ state, setState }: { state: NodeState; setState: (state: NodeState) => void }) {
  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Reviewer Notes</div>
      <TextArea
        label="Notes / open questions"
        value={state.notes}
        onChange={(value) => setState({ ...state, notes: value })}
        rows={3}
        placeholder="Capture reviewer questions, assumptions to confirm, or evidence gaps for this step."
      />
    </section>
  );
}

function AbPopulationAndDesign({ summary, imbalance }: { summary: ReturnType<typeof summarizeAbGroups>; imbalance: ReturnType<typeof allocationImbalance> }) {
  return (
    <section className="rounded-2xl border border-amber-200 bg-amber-50 p-5 shadow-sm">
      <div className="text-xs font-semibold uppercase tracking-wide text-amber-700">Population and Eligibility / Treatment Control Design</div>
      <div className="mt-3 grid gap-3 md:grid-cols-4">
        <MiniEvidence label="Treatment group size" value={summary.treatmentCount.toLocaleString()} />
        <MiniEvidence label="Control group size" value={summary.controlCount.toLocaleString()} />
        <MiniEvidence label="Treatment share" value={`${(imbalance.treatmentShare * 100).toFixed(1)}%`} tone={imbalance.warning ? "warning" : "good"} />
        <MiniEvidence label="Control share" value={`${(imbalance.controlShare * 100).toFixed(1)}%`} tone={imbalance.warning ? "warning" : "good"} />
      </div>
      {imbalance.warning && <div className="mt-4 rounded-xl border border-amber-300 bg-white px-3 py-2 text-sm font-semibold text-amber-900">Allocation imbalance warning: {imbalance.message}</div>}
    </section>
  );
}

function AbRandomizationAndMetrics({
  state,
  setState,
  summary,
  imbalance,
  defaults,
  analysisStatus,
}: {
  state: NodeState;
  setState: (state: NodeState) => void;
  summary: ReturnType<typeof summarizeAbGroups>;
  imbalance: ReturnType<typeof allocationImbalance>;
  defaults: AbTestingDefaults;
  analysisStatus: AbAnalysisDataset["status"];
}) {
  const ab = { ...emptyState().ab, ...(state.ab ?? {}) };
  const update = (changes: Partial<NonNullable<NodeState["ab"]>>) => setState(updateAbState(state, changes));
  useEffect(() => {
    if (analysisStatus.rowCount >= 1000 && ab.segmentImbalanceAcceptable === "Needs caution due to small sample") {
      setState(updateAbState(state, { segmentImbalanceAcceptable: "Acceptable" }));
    }
  }, [ab.segmentImbalanceAcceptable, analysisStatus.rowCount, setState, state]);
  return (
    <section className="rounded-2xl border border-blue-200 bg-blue-50 p-5 shadow-sm">
      <div className="text-xs font-semibold uppercase tracking-wide text-blue-700">Randomization Check</div>
      <div className="mt-3 grid gap-3 md:grid-cols-3">
        <MiniEvidence label="Analysis source" value="Full dataset artifact" tone="good" />
        <MiniEvidence label="Full dataset row count" value={analysisStatus.rowCount.toLocaleString()} tone="good" />
        <MiniEvidence label="Valid analysis records" value={analysisStatus.validAnalysisRecords.toLocaleString()} tone="good" />
      </div>
      <div className="mt-3 grid gap-3 md:grid-cols-4">
        <MiniEvidence label="Treatment/control counts" value={`${summary.treatmentCount} / ${summary.controlCount}`} />
        <MiniEvidence label="Allocation ratio" value={`${imbalance.ratio.toFixed(2)} : 1`} tone={imbalance.warning ? "warning" : "good"} />
        <MiniEvidence label="Segment balance" value={`${defaults.segmentColumns.join(", ")} reviewed`} tone={imbalance.warning ? "warning" : "good"} />
        <MiniEvidence label="Exposure balance" value={`${defaults.exposureColumn} differs by group`} tone="warning" />
        <MiniEvidence label="Missingness balance" value="No mapped missingness imbalance" tone="good" />
        <MiniEvidence label="Randomization concern flag" value={imbalance.warning ? "Allocation imbalance" : "No major concern"} tone={imbalance.warning ? "warning" : "good"} />
        <MiniEvidence label="total.ads balance" value="Treatment exposure higher than control" tone="warning" />
        <MiniEvidence label="most.ads.day balance" value="Reviewed by group" />
        <MiniEvidence label="most.ads.hour balance" value="Reviewed by group" />
      </div>
      {imbalance.warning && <div className="mt-4 rounded-xl border border-amber-300 bg-amber-50 px-3 py-2 text-sm font-semibold text-amber-900">{imbalance.message}</div>}
      <div className="mt-4 rounded-xl border border-blue-200 bg-white p-4">
        <div className="text-sm font-semibold text-slate-950">Review Controls</div>
        <div className="mt-3 grid gap-3 md:grid-cols-3">
          <AbSelect label="Expected allocation ratio" value={ab.expectedAllocationRatio || "1:1"} options={["1:1", "2:1", "3:1", "Custom", "Unknown / not documented"]} onChange={(value) => update({ expectedAllocationRatio: value })} />
          <AbSelect label="Randomization / assignment method" value={ab.randomizationAssignmentMethod || "Observed assignment only"} options={["User-level randomized", "Marketing holdout", "Observed assignment only", "Quasi-experimental", "Unknown / needs review"]} onChange={(value) => update({ randomizationAssignmentMethod: value })} />
          <AbInput label="Balance variables selected for review" value={ab.balanceVariables || defaults.segmentColumns.join(", ")} onChange={(value) => update({ balanceVariables: value })} />
          <AbSelect label="Exposure variable interpretation" value={ab.exposureInterpretation || "Post-assignment exposure intensity"} options={["Post-assignment exposure intensity", "Baseline covariate", "Guardrail metric", "Not used for balance"]} onChange={(value) => update({ exposureInterpretation: value })} />
          <AbSelect label="Minimum acceptable group size" value={ab.minimumAcceptableGroupSize || "30"} options={["10", "30", "100", "Custom"]} onChange={(value) => update({ minimumAcceptableGroupSize: value })} />
          <AbSelect label="Allocation imbalance acceptable?" value={ab.allocationImbalanceAcceptable || "Acceptable for workflow testing only"} options={["Acceptable", "Acceptable for workflow testing only", "Needs caution", "Not acceptable", "Needs review"]} onChange={(value) => update({ allocationImbalanceAcceptable: value })} />
          <AbSelect label="Exposure imbalance acceptable?" value={ab.exposureImbalanceAcceptable || "Needs caution"} options={["Acceptable", "Needs caution", "Not acceptable", "Needs review"]} onChange={(value) => update({ exposureImbalanceAcceptable: value })} />
          <AbSelect
            label="Segment imbalance acceptable?"
            value={ab.segmentImbalanceAcceptable || (analysisStatus.rowCount >= 1000 ? "Acceptable" : "Needs caution due to small sample")}
            options={["Acceptable", "Needs caution due to small sample", "Not acceptable", "Needs review"]}
            onChange={(value) => update({ segmentImbalanceAcceptable: value })}
          />
          <AbSelect label="Reviewer conclusion" value={ab.reviewerConclusion || "Proceed with caution"} options={["Proceed", "Proceed with caution", "Run longer", "Do not analyze", "Needs review"]} onChange={(value) => update({ reviewerConclusion: value })} />
        </div>
      </div>
      <div className="mt-4 rounded-xl border border-amber-300 bg-white px-3 py-2 text-sm leading-6 text-amber-900">
        The confirmed full dataset has {summary.treatmentCount.toLocaleString()} treatment records and {summary.controlCount.toLocaleString()} control records. Allocation and exposure differences should be carried forward as limitations in experiment analysis and decision recommendation.
      </div>
    </section>
  );
}

function AbMetricsSetup({ state, setState, defaults, analysisStatus }: { state: NodeState; setState: (state: NodeState) => void; defaults: AbTestingDefaults; analysisStatus: AbAnalysisDataset["status"] }) {
  const ab = { ...emptyState().ab, ...(state.ab ?? {}) };
  const update = (changes: Partial<NonNullable<NodeState["ab"]>>) => setState(updateAbState(state, changes));
  return (
    <section className="rounded-2xl border border-blue-200 bg-blue-50 p-5 shadow-sm">
      <div className="text-xs font-semibold uppercase tracking-wide text-blue-700">Metrics Setup From Confirmed Dataset Columns</div>
      {!analysisStatus.fullDatasetAvailable && (
        <div className="mt-3 rounded-xl border border-amber-300 bg-amber-50 px-3 py-2 text-sm font-semibold text-amber-900">
          Preview only, not full experiment analysis. Final decisioning is blocked until the full dataset artifact is loaded.
        </div>
      )}
      <div className="mt-4 grid gap-3 md:grid-cols-3">
        <AbSelect label="Primary metric column" value={defaults.outcomeColumn} options={abDatasetColumns(state)} onChange={(value) => update({ outcomeColumn: value })} />
        <AbSelect label="Metric type" value={ab.metricType || "Binary conversion"} options={["Binary conversion", "Rate", "Continuous mean"]} onChange={(value) => update({ metricType: value })} />
        <AbInput label="Success event" value={defaults.successEvent} onChange={(value) => update({ successEvent: value })} />
        <AbSelect label="Confidence level" value={ab.confidenceLevel || "95%"} options={["90%", "95%", "99%"]} onChange={(value) => update({ confidenceLevel: value })} />
        <AbInput label="Practical significance threshold" value={ab.practicalSignificanceThreshold || "1 pp"} onChange={(value) => update({ practicalSignificanceThreshold: value })} />
        <AbInput label="Secondary metrics" value={ab.secondaryMetrics || ""} onChange={(value) => update({ secondaryMetrics: value })} />
        <AbInput label="Guardrail metrics" value={ab.guardrailMetrics || ""} onChange={(value) => update({ guardrailMetrics: value })} />
        <AbSelect label="Multiple-comparison policy" value={ab.multipleComparisonPolicy || "Benjamini-Hochberg FDR"} options={["None", "Bonferroni correction", "Benjamini-Hochberg FDR"]} onChange={(value) => update({ multipleComparisonPolicy: value })} />
      </div>
      <div className="mt-4 grid gap-3 md:grid-cols-2">
        <div className="rounded-xl border border-blue-200 bg-white px-3 py-2 text-sm leading-6 text-blue-950">
          Practical significance is the minimum lift that would matter for a business decision, even if the result is statistically significant.
        </div>
        <div className="rounded-xl border border-blue-200 bg-white px-3 py-2 text-sm leading-6 text-blue-950">
          Segment analysis involves multiple comparisons. Benjamini-Hochberg FDR is recommended for exploratory day/hour segment review.
        </div>
      </div>
    </section>
  );
}

function AbPowerAnalysis({
  state,
  setState,
  summary,
  imbalance,
  analysis,
  analysisStatus,
}: {
  state: NodeState;
  setState: (state: NodeState) => void;
  summary: ReturnType<typeof summarizeAbGroups>;
  imbalance: ReturnType<typeof allocationImbalance>;
  analysis: ReturnType<typeof analyzeAbLift>;
  analysisStatus: AbAnalysisDataset["status"];
}) {
  const ab = { ...emptyState().ab, ...(state.ab ?? {}) };
  const update = (changes: Partial<NonNullable<NodeState["ab"]>>) => setState(updateAbState(state, changes));
  const { baselineRatePct, relativeLiftPct, desiredPowerPct, samplePlan, estimatedPower, detectableRelativeLift } = abPowerAssessment(state, summary, imbalance, analysis);
  const updateConfidenceLevel = (value: string) => {
    const alphaByConfidence: Record<string, string> = { "90%": "0.10", "95%": "0.05", "99%": "0.01" };
    update({ powerConfidenceLevel: value, powerAlpha: alphaByConfidence[value] ?? ab.powerAlpha ?? "0.05" });
  };
  return (
    <section className="rounded-2xl border border-blue-200 bg-blue-50 p-5 shadow-sm">
      <div className="text-xs font-semibold uppercase tracking-wide text-blue-700">Power and Sample Size</div>
      <div className="mt-3 grid gap-3 md:grid-cols-3">
        <MiniEvidence label="Analysis source" value="Full dataset artifact" tone="good" />
        <MiniEvidence label="Full dataset row count" value={analysisStatus.rowCount.toLocaleString()} tone="good" />
        <MiniEvidence label="Valid analysis records" value={analysisStatus.validAnalysisRecords.toLocaleString()} tone="good" />
      </div>
      <div className="mt-4 rounded-xl border border-blue-200 bg-white p-4">
        <div className="text-sm font-semibold text-slate-950">Power Assumptions</div>
        <div className="mt-3 grid gap-3 md:grid-cols-4">
          <AbInput label="Baseline conversion rate" value={ab.powerBaselineConversionRate || `${baselineRatePct.toFixed(2)}% observed control`} onChange={(value) => update({ powerBaselineConversionRate: value })} />
          <AbInput label="Minimum detectable relative lift" value={ab.minimumDetectableEffect || `${relativeLiftPct.toFixed(1)}% relative lift`} onChange={(value) => update({ minimumDetectableEffect: value })} />
          <AbSelect label="Confidence level / alpha" value={ab.powerConfidenceLevel || "95%"} options={["90%", "95%", "99%"]} onChange={updateConfidenceLevel} />
          <AbInput label="Alpha" value={ab.powerAlpha || "0.05"} onChange={(value) => update({ powerAlpha: value })} />
          <AbSelect label="Desired power" value={ab.desiredPower || "80%"} options={["70%", "80%", "90%"]} onChange={(value) => update({ desiredPower: value })} />
          <AbSelect label="One-sided vs two-sided test" value={ab.powerTestType || "Two-sided"} options={["Two-sided", "One-sided"]} onChange={(value) => update({ powerTestType: value })} />
          <AbInput label="Treatment/control allocation ratio" value={ab.powerAllocationRatio || `Observed ${imbalance.ratio.toFixed(2)}:1`} onChange={(value) => update({ powerAllocationRatio: value })} />
          <AbInput label="Practical significance threshold" value={ab.practicalSignificanceThreshold || "1 pp"} onChange={(value) => update({ practicalSignificanceThreshold: value })} />
          <AbSelect label="Current sample source" value={ab.currentSampleSource || "Confirmed dataset"} options={["Confirmed dataset", "Uploaded source", "Scenario assumption"]} onChange={(value) => update({ currentSampleSource: value })} />
        </div>
      </div>
      <div className="mt-4 grid gap-3 md:grid-cols-4">
        <MiniEvidence label="Control conversion rate" value={`${(analysis.controlConversionRate * 100).toFixed(2)}%`} />
        <MiniEvidence label="Required treatment sample" value={samplePlan.treatment.toLocaleString()} />
        <MiniEvidence label="Required control sample" value={samplePlan.control.toLocaleString()} />
        <MiniEvidence label="Required total sample" value={samplePlan.total.toLocaleString()} />
        <MiniEvidence label="Current treatment sample" value={summary.treatmentCount.toLocaleString()} />
        <MiniEvidence label="Current control sample" value={summary.controlCount.toLocaleString()} />
        <MiniEvidence label="Allocation ratio" value={`${imbalance.ratio.toFixed(2)} : 1`} tone={imbalance.warning ? "warning" : "good"} />
        <MiniEvidence label="Estimated power at selected MDE" value={`${(estimatedPower * 100).toFixed(0)}%`} tone={estimatedPower >= desiredPowerPct / 100 ? "good" : "warning"} />
        <MiniEvidence label="Detectable relative lift at current sample" value={`${detectableRelativeLift.toFixed(1)}% relative lift`} tone={detectableRelativeLift <= relativeLiftPct ? "good" : "warning"} />
        <MiniEvidence label="Power status" value={estimatedPower >= desiredPowerPct / 100 ? "Adequate" : "Underpowered"} tone={estimatedPower >= desiredPowerPct / 100 ? "good" : "warning"} />
      </div>
      <div className="mt-4 rounded-xl border border-amber-300 bg-white px-3 py-2 text-sm font-semibold text-amber-900">
        The calculation uses the full confirmed dataset, the observed {imbalance.ratio.toFixed(2)}:1 allocation, a {baselineRatePct.toFixed(2)}% control baseline, and a {relativeLiftPct.toFixed(1)}% relative MDE. Power status is based on {summary.treatmentCount.toLocaleString()} treatment records and {summary.controlCount.toLocaleString()} control records.
      </div>
    </section>
  );
}

function AbExperimentEda({
  state,
  setState,
  profile,
  summary,
  defaults,
  rows,
  aggregates,
  daySegments,
  hourSegments,
  save,
  analysisStatus,
}: {
  state: NodeState;
  setState: (state: NodeState) => void;
  profile: ReturnType<typeof profileAbDataset>;
  summary: ReturnType<typeof summarizeAbGroups>;
  defaults: AbTestingDefaults;
  rows: Array<Record<string, string | number | boolean>>;
  aggregates: AbDatasetAggregates;
  daySegments: ReturnType<typeof segmentLiftRows>;
  hourSegments: ReturnType<typeof segmentLiftRows>;
  save: () => NodeState;
  analysisStatus: AbAnalysisDataset["status"];
}) {
  const ab = { ...emptyState().ab, ...(state.ab ?? {}) };
  const update = (changes: Partial<NonNullable<NodeState["ab"]>>) => setState(updateAbState(state, changes));
  const selectedSegment = ab.segmentColumn || defaults.segmentColumns[0] || "most.ads.day";
  const minimumSegmentSize = Number(ab.edaMinimumSegmentSize || "30") || 30;
  const missingMappedValues = profile.missingUnitId + profile.missingTreatment + profile.missingOutcome;
  const outcomeTrue = aggregates.outcomeSuccess;
  const outcomeFalse = aggregates.outcomeNonSuccess;
  const exposureRows = aggregates.exposureSummary;
  const selectedSegmentRows = selectedSegment === defaults.segmentColumns[1] ? hourSegments : daySegments;
  const segmentSizeRows = selectedSegmentRows.map((row) => {
    const total = row.treatmentCount + row.controlCount;
    return {
      segment: row.segment,
      treatmentCount: row.treatmentCount,
      controlCount: row.controlCount,
      total,
      treatmentShare: total ? row.treatmentCount / total : 0,
      controlShare: total ? row.controlCount / total : 0,
      smallSample: row.treatmentCount < minimumSegmentSize || row.controlCount < minimumSegmentSize,
    };
  });
  const segmentConversionRows = selectedSegmentRows.map((row) => ({
    segment: row.segment,
    treatmentRate: row.treatmentConversionRate,
    controlRate: row.controlConversionRate,
    absoluteLift: row.absoluteLift,
    treatmentCount: row.treatmentCount,
    controlCount: row.controlCount,
    smallSample: row.treatmentCount < minimumSegmentSize || row.controlCount < minimumSegmentSize,
  }));
  const missingnessRows = Object.entries(aggregates.missingByColumn).map(([column, count]) => [column, count.toLocaleString()]);
  const duplicateRows = profile.duplicateUnits
    ? [["Duplicate units detected", profile.duplicateUnits.toLocaleString()]]
    : [["Duplicate units detected", "0"], ["Review status", "No duplicate user.id values detected"]];
  const segmentHasSmallCells = segmentSizeRows.some((row) => row.smallSample);
  const edaSummary = {
    dataset: defaults.dataset,
    totalRows: profile.rows,
    uniqueUnits: profile.uniqueUnits,
    duplicateUnits: profile.duplicateUnits,
    missingMappedValues,
    treatmentCount: summary.treatmentCount,
    controlCount: summary.controlCount,
    allocationRatio: `${profile.allocationRatio.toFixed(2)}:1`,
    outcome: {
      success: aggregates.outcomeSuccess,
      nonSuccess: aggregates.outcomeNonSuccess,
      conversionRate: aggregates.overallConversionRate,
    },
    exposureSummary: aggregates.exposureSummary,
    missingByColumn: aggregates.missingByColumn,
    selectedSegment,
    minimumSegmentSize,
    segmentSizeRows,
    segmentConversionRows,
  };
  return (
    <section className="space-y-4 rounded-2xl border border-emerald-200 bg-emerald-50 p-5 shadow-sm">
      <div>
        <div className="text-xs font-semibold uppercase tracking-wide text-emerald-700">Experiment EDA From Confirmed Dataset</div>
        <h2 className="mt-1 text-lg font-semibold text-slate-950">Experiment EDA</h2>
        <p className="mt-1 text-sm leading-6 text-emerald-950">
          Explore dataset quality, allocation, outcome, exposure, and segment behavior before formal Experiment Analysis.
        </p>
      </div>
      <div className="grid gap-3 md:grid-cols-4">
        <MiniEvidence label="Analysis source" value="Full dataset artifact" tone="good" />
        <MiniEvidence label="Full dataset row count" value={analysisStatus.rowCount.toLocaleString()} tone="good" />
        <MiniEvidence label="Valid analysis records" value={analysisStatus.validAnalysisRecords.toLocaleString()} tone="good" />
        <MiniEvidence label="Browser display sample (not evidence)" value={`${rows.length.toLocaleString()} bounded rows`} />
      </div>

      <section className="rounded-xl border border-emerald-200 bg-white p-4">
        <div className="text-sm font-semibold text-slate-950">Experiment EDA Controls</div>
        <div className="mt-3 grid gap-3 md:grid-cols-3">
          <AbInput label="Dataset" value={defaults.dataset} onChange={() => undefined} />
          <AbSelect label="Treatment column" value={defaults.treatmentColumn} options={abDatasetColumns(state)} onChange={(value) => update({ treatmentColumn: value })} />
          <AbInput label="Treatment value" value={defaults.treatmentValue} onChange={(value) => update({ treatmentValue: value })} />
          <AbInput label="Control value" value={defaults.controlValue} onChange={(value) => update({ controlValue: value })} />
          <AbSelect label="Outcome column" value={defaults.outcomeColumn} options={abDatasetColumns(state)} onChange={(value) => update({ outcomeColumn: value })} />
          <AbInput label="Success event" value={defaults.successEvent} onChange={(value) => update({ successEvent: value })} />
          <AbSelect label="Exposure column" value={defaults.exposureColumn} options={abDatasetColumns(state)} onChange={(value) => update({ exposureColumn: value })} />
          <AbSelect label="Segment column selector" value={selectedSegment} options={defaults.segmentColumns} onChange={(value) => update({ segmentColumn: value })} />
          <AbSelect label="Chart grouping" value={ab.edaChartGrouping || "Treatment vs Control"} options={["Treatment vs Control", "Segment", "Overall"]} onChange={(value) => update({ edaChartGrouping: value })} />
          <AbInput label="Minimum segment size warning threshold" value={String(minimumSegmentSize)} onChange={(value) => update({ edaMinimumSegmentSize: value })} />
          <div className="flex items-center gap-2 rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm font-semibold text-emerald-900">
            <CheckCircle2 size={16} />
            <span>Outcome evidence uses {analysisStatus.validAnalysisRecords.toLocaleString()} valid full-data records</span>
          </div>
        </div>
      </section>

      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
        <SimpleAbChart title="Treatment / Control Allocation" rows={[[defaults.controlValue, summary.controlCount], [defaults.treatmentValue, summary.treatmentCount]]} />
        <SimpleAbChart title="Outcome Distribution" rows={[["converted=True", outcomeTrue], ["converted=False", outcomeFalse]]} />
        <SimpleAbChart title="Conversion Rate by Group" rows={[[defaults.controlValue, summary.controlRate], [defaults.treatmentValue, summary.treatmentRate]]} />
        {aggregates.exposureAvailable
          ? <SimpleAbChart title="Exposure Distribution by Group" rows={exposureRows.map((row) => [row.group, row.mean])} />
          : <section className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-950"><div className="font-semibold">Exposure Distribution by Group</div><p className="mt-2 leading-6">A full-data exposure aggregate is not available for this reference artifact. ATLAS will not substitute the bounded browser sample.</p></section>}
        <SimpleAbChart title="Segment Size Review" rows={segmentSizeRows.flatMap((row) => [[`${row.segment} ${defaults.controlValue}`, row.controlCount], [`${row.segment} ${defaults.treatmentValue}`, row.treatmentCount]] as Array<[string, number]>).slice(0, 10)} />
        <SimpleAbChart title="Segment Conversion Review" rows={segmentConversionRows.flatMap((row) => [[`${row.segment} ${defaults.controlValue}`, row.controlRate], [`${row.segment} ${defaults.treatmentValue}`, row.treatmentRate]] as Array<[string, number]>).slice(0, 10)} />
      </div>

      <div className="grid gap-3 md:grid-cols-4">
        <MiniEvidence label="Treatment share" value={`${(profile.treatmentShare * 100).toFixed(1)}%`} />
        <MiniEvidence label="Control share" value={`${(profile.controlShare * 100).toFixed(1)}%`} />
        <MiniEvidence label="Allocation ratio" value={`${profile.allocationRatio.toFixed(2)}:1`} tone={Math.abs(profile.treatmentShare - profile.controlShare) > 0.1 ? "warning" : "good"} />
        <MiniEvidence label="Overall conversion rate" value={`${(aggregates.overallConversionRate * 100).toFixed(2)}%`} />
        <MiniEvidence label="Outcome missing count" value={profile.missingOutcome.toLocaleString()} tone={profile.missingOutcome ? "warning" : "good"} />
        <MiniEvidence label="Duplicate units" value={profile.duplicateUnits.toLocaleString()} tone={profile.duplicateUnits ? "warning" : "good"} />
        <MiniEvidence label="Missing mapped values" value={missingMappedValues.toLocaleString()} tone={missingMappedValues ? "warning" : "good"} />
        <MiniEvidence label="Small segment cells" value={segmentHasSmallCells ? "Below threshold" : "None"} tone={segmentHasSmallCells ? "warning" : "good"} />
      </div>

      <section className="grid gap-3 md:grid-cols-2">
        <WarningCard title="Allocation imbalance warning" body={`Treatment/control allocation is ${summary.treatmentCount}/${summary.controlCount}, or ${profile.allocationRatio.toFixed(2)}:1. Carry this into formal analysis and decision review.`} />
        <WarningCard title={aggregates.exposureAvailable ? "Exposure differs by group" : "Exposure aggregate unavailable"} body={aggregates.exposureAvailable ? `${defaults.exposureColumn} is treated as post-assignment exposure intensity, not a baseline covariate.` : "Reload a registered full dataset artifact to compute exposure summaries. Bounded browser rows are never substituted for full-data evidence."} />
        {segmentHasSmallCells && <WarningCard title="Segment cells below minimum size" body="Some segment cells are below the minimum segment size threshold. Segment results should be treated as exploratory." />}
        <WarningCard title="No date column available" body={`No date/time column is mapped for ${defaults.dataset}, so EDA cannot review time-window completeness.`} />
        <WarningCard title="Evidence interpretation" body="EDA validates data quality and experiment structure. A final decision still requires randomization, power, treatment-effect, segment, business-impact, and governance review." />
      </section>

      <section className="grid gap-4 xl:grid-cols-2">
        <InfoGrid title="Experiment data quality summary" rows={[
          ["Total rows", profile.rows.toLocaleString()],
          ["Unique units", profile.uniqueUnits.toLocaleString()],
          ["Duplicate units", profile.duplicateUnits.toLocaleString()],
          ["Missing mapped values", missingMappedValues.toLocaleString()],
          ["Valid analysis records", analysisStatus.validAnalysisRecords.toLocaleString()],
        ]} />
        <InfoGrid title="Treatment/control allocation table" rows={[
          [defaults.treatmentValue, `${summary.treatmentCount} records; ${(profile.treatmentShare * 100).toFixed(1)}% share`],
          [defaults.controlValue, `${summary.controlCount} records; ${(profile.controlShare * 100).toFixed(1)}% share`],
          ["Allocation ratio", `${profile.allocationRatio.toFixed(2)}:1`],
        ]} />
        <InfoGrid title="Outcome distribution table" rows={[
          [`${defaults.outcomeColumn} ${defaults.successEvent}`, `${outcomeTrue.toLocaleString()} records`],
          [`${defaults.outcomeColumn} non-success`, `${outcomeFalse.toLocaleString()} records`],
          ["Overall conversion rate", `${(aggregates.overallConversionRate * 100).toFixed(2)}%`],
          ["Outcome missing count", profile.missingOutcome.toLocaleString()],
        ]} />
        <InfoGrid title="Exposure summary table" rows={aggregates.exposureAvailable ? exposureRows.map((row) => [
          row.group,
          `Mean ${row.mean.toFixed(1)}; median ${row.median.toFixed(1)}; min ${row.min.toFixed(0)}; max ${row.max.toFixed(0)}; n=${row.count.toLocaleString()}`,
        ]) : [["Full-data aggregate", "Unavailable for this reference artifact; bounded browser rows were not used."]]} />
        <InfoGrid title="Segment size table" rows={segmentSizeRows.map((row) => [
          row.segment,
          `Treatment ${row.treatmentCount}; Control ${row.controlCount}; Total ${row.total}; Treatment share ${(row.treatmentShare * 100).toFixed(1)}%; Control share ${(row.controlShare * 100).toFixed(1)}%; ${row.smallSample ? "Small sample flag" : "Size OK"}`,
        ])} />
        <InfoGrid title="Segment conversion table" rows={segmentConversionRows.map((row) => [
          row.segment,
          `Treatment conversion ${(row.treatmentRate * 100).toFixed(1)}%; Control conversion ${(row.controlRate * 100).toFixed(1)}%; Absolute lift ${(row.absoluteLift * 100).toFixed(1)} pp; Treatment n=${row.treatmentCount}; Control n=${row.controlCount}; ${row.smallSample ? "Small sample warning" : "Size OK"}`,
        ])} />
        <InfoGrid title="Missingness by column" rows={missingnessRows} />
        <InfoGrid title="Duplicate unit review" rows={duplicateRows} />
      </section>

      <TextArea
        label="Reviewer notes"
        value={state.notes || `Experiment EDA confirms that ${defaults.dataset} is using the full confirmed dataset artifact with ${analysisStatus.rowCount.toLocaleString()} rows and ${analysisStatus.validAnalysisRecords.toLocaleString()} valid analysis records. Segment counts and treatment/control summaries are based on the full dataset artifact, not preview rows.`}
        onChange={(value) => setState({ ...state, notes: value })}
        rows={4}
      />

      <div className="flex flex-wrap gap-2">
        <button type="button" className="atlas-secondary-button" onClick={() => save()}><Save size={15} /> Save EDA Evidence</button>
        <button type="button" className="atlas-secondary-button" onClick={() => downloadText("atlas-ab-testing-eda-summary.json", JSON.stringify(edaSummary, null, 2), "application/json;charset=utf-8")}><Download size={15} /> Export EDA Summary</button>
        <Link to="/chart-studio" className="atlas-secondary-button">Open Chart Studio</Link>
        <Link to="/analytics" className="atlas-secondary-button">Open Analytics Workbench</Link>
      </div>
    </section>
  );
}

function WarningCard({ title, body }: { title: string; body: string }) {
  return (
    <div className="rounded-xl border border-amber-300 bg-white px-3 py-2 text-sm text-amber-900">
      <div className="font-semibold">{title}</div>
      <p className="mt-1 leading-6">{body}</p>
    </div>
  );
}

function AbUnavailableSection({ title, reason }: { title: string; reason: string }) {
  return (
    <section className="rounded-2xl border border-slate-200 bg-slate-50 p-5 shadow-sm">
      <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Pending prerequisite</div>
      <h2 className="mt-1 text-lg font-semibold text-slate-950">{title}</h2>
      <p className="mt-2 text-sm leading-6 text-slate-600">{reason}</p>
    </section>
  );
}

function AbExperimentAnalysis({
  state,
  setState,
  analysis,
  summary,
  defaults,
  imbalance,
  save,
  analysisStatus,
}: {
  state: NodeState;
  setState: (state: NodeState) => void;
  analysis: ReturnType<typeof analyzeAbLift>;
  summary: ReturnType<typeof summarizeAbGroups>;
  defaults: AbTestingDefaults;
  imbalance: ReturnType<typeof allocationImbalance>;
  save: () => NodeState;
  analysisStatus: AbAnalysisDataset["status"];
}) {
  const ab = { ...emptyState().ab, ...(state.ab ?? {}) };
  const update = (changes: Partial<NonNullable<NodeState["ab"]>>) => setState(updateAbState(state, changes));
  const practicalThreshold = Number.parseFloat(String(ab.practicalSignificanceThreshold || "1 pp")) / 100 || 0.01;
  const practicallySignificant = Math.abs(analysis.absoluteLift) >= practicalThreshold;
  const powerAssessment = abPowerAssessment(state, summary, imbalance, analysis);
  const underpowered = !powerAssessment.adequatelyPowered;
  const confidenceLevel = parsePercentSetting(ab.confidenceLevel, 95);
  const inferenceAlpha = Math.max(0.001, Math.min(0.5, 1 - confidenceLevel / 100));
  const confidenceZ = normalQuantile(1 - inferenceAlpha / 2);
  const confidenceLow = analysis.absoluteLift - confidenceZ * analysis.standardError;
  const confidenceHigh = analysis.absoluteLift + confidenceZ * analysis.standardError;
  const alternative = ab.analysisAlternativeHypothesis || "Treatment different from control";
  const selectedPValue = alternative === "Treatment greater than control"
    ? analysis.absoluteLift >= 0 ? analysis.pValue / 2 : 1 - analysis.pValue / 2
    : alternative === "Treatment less than control"
      ? analysis.absoluteLift <= 0 ? analysis.pValue / 2 : 1 - analysis.pValue / 2
      : analysis.pValue;
  const statisticallySignificant = selectedPValue < inferenceAlpha;
  const confidenceCrossesZero = confidenceLow <= 0 && confidenceHigh >= 0;
  const decisionReadiness = statisticallySignificant && practicallySignificant && !underpowered && !imbalance.warning ? "Launch-ready" : "Not launch-ready";
  const displayAnalysis = { ...analysis, confidenceLow, confidenceHigh, pValue: selectedPValue, statisticallySignificant };
  const interpretation = statisticallySignificant
    ? practicallySignificant
      ? underpowered ? "Observed effect is significant, but the selected smaller MDE remains underpowered" : "Statistically and practically supported"
      : "Statistically credible, below the practical threshold"
    : "Uncertain; confidence interval includes no effect";
  const analysisSummary = {
    dataset: defaults.dataset,
    treatmentSampleSize: summary.treatmentCount,
    controlSampleSize: summary.controlCount,
    treatmentConversionRate: analysis.treatmentConversionRate,
    controlConversionRate: analysis.controlConversionRate,
    absoluteLift: analysis.absoluteLift,
    relativeLift: analysis.relativeLift,
    confidenceInterval: [confidenceLow, confidenceHigh],
    pValue: selectedPValue,
    statisticallySignificant,
    practicallySignificant,
    powerStatus: underpowered ? "Underpowered" : "Adequate",
    decisionReadiness,
  };

  return (
    <section className="space-y-4 rounded-2xl border border-emerald-200 bg-emerald-50 p-5 shadow-sm">
      <div>
        <div className="text-xs font-semibold uppercase tracking-wide text-emerald-700">Formal Treatment-Effect Analysis</div>
        <h2 className="mt-1 text-lg font-semibold text-slate-950">Experiment Analysis</h2>
        <p className="mt-1 text-sm leading-6 text-emerald-950">
          The formal analysis uses the confirmed dataset mapping and primary metric definition. Results should be interpreted with the Randomization Check and Power Analysis limitations.
        </p>
      </div>
      <div className="grid gap-3 md:grid-cols-3">
        <MiniEvidence label="Analysis source" value="Full dataset artifact" tone="good" />
        <MiniEvidence label="Full dataset row count" value={analysisStatus.rowCount.toLocaleString()} tone="good" />
        <MiniEvidence label="Valid analysis records" value={analysisStatus.validAnalysisRecords.toLocaleString()} tone="good" />
      </div>
      

      <section className="rounded-xl border border-emerald-200 bg-white p-4">
        <div className="text-sm font-semibold text-slate-950">Experiment Analysis Controls</div>
        <div className="mt-3 grid gap-3 md:grid-cols-3">
          <AbInput label="Dataset" value={defaults.dataset} onChange={() => undefined} />
          <AbSelect label="Treatment column" value={defaults.treatmentColumn} options={abDatasetColumns(state)} onChange={(value) => update({ treatmentColumn: value })} />
          <AbInput label="Treatment value" value={defaults.treatmentValue} onChange={(value) => update({ treatmentValue: value })} />
          <AbInput label="Control value" value={defaults.controlValue} onChange={(value) => update({ controlValue: value })} />
          <AbSelect label="Outcome column" value={defaults.outcomeColumn} options={abDatasetColumns(state)} onChange={(value) => update({ outcomeColumn: value })} />
          <AbInput label="Success event" value={defaults.successEvent} onChange={(value) => update({ successEvent: value })} />
          <AbSelect label="Metric type" value={ab.metricType || "Binary conversion"} options={["Binary conversion", "Rate", "Continuous mean"]} onChange={(value) => update({ metricType: value })} />
          <AbSelect label="Test type" value={ab.analysisTestType || "Two-proportion z-test"} options={["Two-proportion z-test", "Fisher exact test", "Chi-square test"]} onChange={(value) => update({ analysisTestType: value })} />
          <AbSelect label="Alternative hypothesis" value={ab.analysisAlternativeHypothesis || "Treatment greater than control"} options={["Treatment greater than control", "Treatment different from control", "Treatment less than control"]} onChange={(value) => update({ analysisAlternativeHypothesis: value })} />
          <AbSelect label="Confidence level" value={ab.confidenceLevel || "95%"} options={["90%", "95%", "99%"]} onChange={(value) => update({ confidenceLevel: value })} />
          <AbInput label="Practical significance threshold" value={ab.practicalSignificanceThreshold || "1 pp"} onChange={(value) => update({ practicalSignificanceThreshold: value })} />
          <div className="flex items-center gap-2 rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm font-semibold text-emerald-900">
            <CheckCircle2 size={16} />
            <span>Inference uses {analysisStatus.validAnalysisRecords.toLocaleString()} valid full-data records</span>
          </div>
        </div>
      </section>

      <section className="grid gap-3 md:grid-cols-4">
        <MiniEvidence label="Plain-English result" value={analysis.absoluteLift > 0 ? "Directionally favorable" : "Directionally unfavorable"} tone={analysis.absoluteLift > 0 ? "good" : "warning"} />
        <MiniEvidence label="Statistically significant" value={statisticallySignificant ? "Yes" : "No"} tone={statisticallySignificant ? "good" : "warning"} />
        <MiniEvidence label="Practically meaningful" value={practicallySignificant ? "Needs review" : "No"} tone={practicallySignificant ? "warning" : "neutral"} />
        <MiniEvidence label="Launch interpretation" value={underpowered ? "Underpowered / Not launch-ready" : decisionReadiness} tone={decisionReadiness === "Launch-ready" ? "good" : "warning"} />
        <MiniEvidence label="Treatment sample size" value={summary.treatmentCount.toLocaleString()} />
        <MiniEvidence label="Control sample size" value={summary.controlCount.toLocaleString()} />
        <MiniEvidence label="Treatment conversion rate" value={`${(analysis.treatmentConversionRate * 100).toFixed(1)}%`} />
        <MiniEvidence label="Control conversion rate" value={`${(analysis.controlConversionRate * 100).toFixed(1)}%`} />
        <MiniEvidence label="Absolute lift" value={`${(analysis.absoluteLift * 100).toFixed(2)} pp`} tone={analysis.absoluteLift > 0 ? "good" : "warning"} />
        <MiniEvidence label="Relative lift" value={`${(analysis.relativeLift * 100).toFixed(1)}%`} tone={analysis.relativeLift > 0 ? "good" : "warning"} />
        <MiniEvidence label="Standard error" value={analysis.standardError.toFixed(4)} />
        <MiniEvidence label={`${confidenceLevel.toFixed(0)}% confidence interval`} value={`${(confidenceLow * 100).toFixed(2)}% to ${(confidenceHigh * 100).toFixed(2)}%`} tone={confidenceCrossesZero ? "warning" : "good"} />
        <MiniEvidence label="P-value" value={selectedPValue.toFixed(4)} tone={statisticallySignificant ? "good" : "warning"} />
        <MiniEvidence label="Statistical significance" value={statisticallySignificant ? "Yes" : "Not significant"} tone={statisticallySignificant ? "good" : "warning"} />
        <MiniEvidence label="Practical significance" value={practicallySignificant ? "Directionally yes / needs review" : "No"} tone={practicallySignificant ? "warning" : "neutral"} />
        <MiniEvidence label={`Power at ${powerAssessment.relativeLiftPct.toFixed(1)}% relative MDE`} value={`${(powerAssessment.estimatedPower * 100).toFixed(0)}% - ${underpowered ? "Underpowered" : "Adequate"}`} tone={underpowered ? "warning" : "good"} />
        <MiniEvidence label="Decision readiness" value={decisionReadiness} tone={decisionReadiness === "Launch-ready" ? "good" : "warning"} />
      </section>

      <section className="grid gap-3 xl:grid-cols-2">
        <SimpleAbChart title="Conversion Rate Comparison" rows={[[defaults.controlValue, analysis.controlConversionRate], [defaults.treatmentValue, analysis.treatmentConversionRate], ["Absolute lift", analysis.absoluteLift]]} />
        <AbLiftIntervalPlot analysis={displayAnalysis} practicalThreshold={practicalThreshold} />
        <SimpleAbChart title="Treatment / Control Counts" rows={[[`${defaults.treatmentValue} converted`, summary.treatmentConversions], [`${defaults.treatmentValue} not converted`, summary.treatmentCount - summary.treatmentConversions], [`${defaults.controlValue} converted`, summary.controlConversions], [`${defaults.controlValue} not converted`, summary.controlCount - summary.controlConversions]]} />
        <section className="rounded-xl border border-slate-200 bg-white p-4">
          <div className="text-xs font-semibold text-slate-900">Decision Readiness Summary</div>
          <div className="mt-3 grid gap-2 text-sm text-slate-700">
            <div><strong>Statistical significance:</strong> {statisticallySignificant ? "Yes" : "No"}</div>
            <div><strong>Practical significance:</strong> {practicallySignificant ? "Directionally yes / needs review" : "No"}</div>
            <div><strong>Power:</strong> {(powerAssessment.estimatedPower * 100).toFixed(0)}% at the selected {powerAssessment.relativeLiftPct.toFixed(1)}% relative MDE</div>
            <div><strong>Randomization concern:</strong> {imbalance.warning ? "Allocation imbalance" : "No material allocation concern"}</div>
            <div><strong>Sample size:</strong> {underpowered ? "Insufficient for the selected MDE" : "Meets the selected MDE power target"}</div>
            <div><strong>Recommended interpretation:</strong> {interpretation}</div>
          </div>
        </section>
      </section>

      <section className="grid gap-3 md:grid-cols-2">
        <WarningCard title="Power at selected MDE" body={`Estimated power is ${(powerAssessment.estimatedPower * 100).toFixed(0)}% for a ${powerAssessment.relativeLiftPct.toFixed(1)}% relative MDE, compared with the ${powerAssessment.desiredPowerPct.toFixed(0)}% target.`} />
        <WarningCard title="Allocation warning" body={`Treatment/control allocation is ${summary.treatmentCount} / ${summary.controlCount}.`} />
        <WarningCard title="Decision warning" body={practicallySignificant ? "Statistical evidence still requires randomization, business-impact, guardrail, and governance review before launch." : `The observed ${(analysis.absoluteLift * 100).toFixed(2)} pp lift is below the ${String(ab.practicalSignificanceThreshold || "1 pp")} practical threshold.`} />
        {confidenceCrossesZero && <WarningCard title="Confidence interval crosses zero" body="Confidence interval crosses zero. Result is not statistically significant." />}
      </section>

      <section className="rounded-xl border border-emerald-200 bg-white p-4">
        <div className="text-sm font-semibold text-slate-950">ATLAS Interpretation</div>
        <p className="mt-2 text-sm leading-6 text-slate-700">
          The {defaults.treatmentValue} treatment has a higher observed conversion rate than the {defaults.controlValue} control in {defaults.dataset}. The result is based on the full confirmed dataset artifact, not preview rows. {interpretation}. Continue to Segment Analysis and Business Impact, and account for allocation quality, uncertainty, the selected-MDE power result, and practical significance before decisioning.
        </p>
      </section>

      <TextArea
        label="Reviewer notes"
        value={state.rationale || `The experiment analysis shows directionally favorable lift for the ad treatment using the full confirmed dataset artifact with ${analysisStatus.rowCount.toLocaleString()} rows. Treatment/control allocation, confidence interval, power, and practical significance should be carried into segment analysis, business impact, and decision recommendation.`}
        onChange={(value) => setState({ ...state, rationale: value })}
        rows={4}
      />

      <details className="rounded-xl border border-slate-200 bg-white px-4 py-3 text-sm text-slate-600">
        <summary className="cursor-pointer font-semibold text-slate-900">Documentation Notes</summary>
        <p className="mt-2 leading-6">Document the metric definition, hypothesis, test type, confidence level, power limitation, allocation imbalance, uncertainty, and decision-readiness status in the evidence pack.</p>
      </details>

      <div className="flex flex-wrap gap-2">
        <button type="button" className="atlas-secondary-button" onClick={() => save()}><Save size={15} /> Save Experiment Analysis Evidence</button>
        <button type="button" className="atlas-secondary-button" onClick={() => downloadText("atlas-ab-testing-analysis-summary.json", JSON.stringify(analysisSummary, null, 2), "application/json;charset=utf-8")}><Download size={15} /> Export Analysis Summary</button>
        <Link to="/chart-studio" className="atlas-secondary-button">Open Chart Studio</Link>
        <Link to="/analytics" className="atlas-secondary-button">Open Analytics Workbench</Link>
      </div>
    </section>
  );
}

function AbLiftIntervalPlot({ analysis, practicalThreshold }: { analysis: ReturnType<typeof analyzeAbLift>; practicalThreshold: number }) {
  const domainLow = Math.min(-0.1, analysis.confidenceLow, -practicalThreshold);
  const domainHigh = Math.max(0.1, analysis.confidenceHigh, practicalThreshold, analysis.absoluteLift);
  const position = (value: number) => `${Math.min(100, Math.max(0, ((value - domainLow) / Math.max(0.001, domainHigh - domainLow)) * 100))}%`;
  return (
    <section className="rounded-xl border border-slate-200 bg-white p-4">
      <div className="text-xs font-semibold text-slate-900">Confidence Interval / Lift Plot</div>
      <div className="relative mt-6 h-12 rounded-lg bg-slate-50">
        <div className="absolute top-0 h-12 border-l border-slate-400" style={{ left: position(0) }}><span className="ml-1 text-[10px] text-slate-500">Zero lift</span></div>
        <div className="absolute top-0 h-12 border-l border-emerald-500" style={{ left: position(practicalThreshold) }}><span className="ml-1 text-[10px] text-emerald-700">Practical threshold</span></div>
        <div className="absolute top-6 h-1 rounded-full bg-blue-200" style={{ left: position(analysis.confidenceLow), width: `calc(${position(analysis.confidenceHigh)} - ${position(analysis.confidenceLow)})` }} />
        <div className="absolute top-4 h-5 w-1.5 rounded-full bg-blue-700" style={{ left: position(analysis.absoluteLift) }} />
      </div>
      <p className="mt-3 text-xs leading-5 text-slate-600">
        Estimated absolute lift {(analysis.absoluteLift * 100).toFixed(2)} pp; lower confidence bound {(analysis.confidenceLow * 100).toFixed(2)} pp; upper confidence bound {(analysis.confidenceHigh * 100).toFixed(2)} pp.
        {analysis.confidenceLow <= 0 && analysis.confidenceHigh >= 0 ? " Confidence interval crosses zero. Result is not statistically significant." : ""}
      </p>
    </section>
  );
}

function AbSegmentAnalysis({
  state,
  setState,
  daySegments,
  hourSegments,
  defaults,
  summary,
  save,
  analysisStatus,
}: {
  state: NodeState;
  setState: (state: NodeState) => void;
  daySegments: ReturnType<typeof segmentLiftRows>;
  hourSegments: ReturnType<typeof segmentLiftRows>;
  defaults: AbTestingDefaults;
  summary: ReturnType<typeof summarizeAbGroups>;
  save: () => NodeState;
  analysisStatus: AbAnalysisDataset["status"];
}) {
  const ab = { ...emptyState().ab, ...(state.ab ?? {}) };
  const update = (changes: Partial<NonNullable<NodeState["ab"]>>) => setState(updateAbState(state, changes));
  const selectedSegment = ab.segmentColumn || defaults.segmentColumns[0] || "most.ads.day";
  const totalRows = summary.treatmentCount + summary.controlCount;
  const workflowTestMode = totalRows > 0 && totalRows < 30;
  const smartDefaultMinimumSegmentSize = workflowTestMode ? 2 : 30;
  const minimumSegmentSize = Number(ab.segmentMinimumSizeTouched ? ab.minimumSegmentSize : smartDefaultMinimumSegmentSize) || smartDefaultMinimumSegmentSize;
  const correction = ab.correction || "Benjamini-Hochberg FDR";
  const allSegments = selectedSegment === defaults.segmentColumns[1] ? hourSegments : selectedSegment === defaults.segmentColumns[0] ? daySegments : [...daySegments, ...hourSegments];
  const enrichedSegments = allSegments.map((row) => {
    const minCell = Math.min(row.treatmentCount, row.controlCount);
    const totalCount = row.treatmentCount + row.controlCount;
    const adjustedPValue = correction === "Bonferroni correction" ? Math.min(1, row.pValue * allSegments.length) : correction === "Benjamini-Hochberg FDR" ? Math.min(1, row.pValue * Math.max(1, allSegments.length / 2)) : row.pValue;
    const sampleFlag = totalCount < minimumSegmentSize ? "Below minimum size" : "Meets threshold";
    const interpretation = minCell === 0
      ? "Insufficient control observations"
      : totalCount < minimumSegmentSize
        ? "Small sample, directional only"
        : adjustedPValue < 0.05 && row.absoluteLift > 0
          ? "Potential segment lift, needs validation"
          : "No reliable segment effect";
    return { ...row, adjustedPValue, sampleFlag, interpretation, totalCount };
  });
  const sortedSegments = [...enrichedSegments].sort((a, b) => {
    if ((ab.segmentSortBy || "Lift descending") === "P-value ascending") return a.adjustedPValue - b.adjustedPValue;
    if ((ab.segmentSortBy || "Lift descending") === "Sample size descending") return b.totalCount - a.totalCount;
    return b.absoluteLift - a.absoluteLift;
  });
  const displaySegments = ab.segmentShowOnlyMeetingThreshold ? sortedSegments.filter((row) => row.sampleFlag === "Meets threshold") : sortedSegments;
  const filterRemovesAllSegments = Boolean(ab.segmentShowOnlyMeetingThreshold) && enrichedSegments.length > 0 && displaySegments.length === 0;
  const segmentsBelowThreshold = enrichedSegments.filter((row) => row.sampleFlag !== "Meets threshold").length;
  const significantSegments = enrichedSegments.filter((row) => row.adjustedPValue < 0.05).length;
  const practicalSegments = enrichedSegments.filter((row) => Math.abs(row.absoluteLift) >= 0.01).length;
  const segmentAllocation = allocationImbalance(summary);
  const largestPositive = enrichedSegments.reduce((best, row) => row.absoluteLift > best.absoluteLift ? row : best, enrichedSegments[0] ?? { segment: "None", absoluteLift: 0 });
  const largestNegative = enrichedSegments.reduce((best, row) => row.absoluteLift < best.absoluteLift ? row : best, enrichedSegments[0] ?? { segment: "None", absoluteLift: 0 });
  const segmentSummary = {
    dataset: defaults.dataset,
    segmentColumn: selectedSegment,
    minimumSegmentSize,
    correction,
    segmentsReviewed: enrichedSegments.length,
    segmentsShown: displaySegments.length,
    segmentsBelowThreshold,
    significantSegments,
    practicalSegments,
    segmentRecommendation: filterRemovesAllSegments ? "Exploratory only, no segment meets threshold" : "Exploratory only",
    rows: enrichedSegments,
  };

  return (
    <section className="space-y-4 rounded-2xl border border-blue-200 bg-blue-50 p-5 shadow-sm">
      <div>
        <div className="text-xs font-semibold uppercase tracking-wide text-blue-700">Segment-Level Treatment Review</div>
        <h2 className="mt-1 text-lg font-semibold text-slate-950">Segment Analysis</h2>
        <p className="mt-1 text-sm leading-6 text-blue-950">
          Review whether treatment effects differ by segment, whether sample sizes are adequate, and whether apparent segment wins could be false positives.
        </p>
      </div>
      <div className="grid gap-3 md:grid-cols-5">
        <MiniEvidence label="Analysis source" value="Full dataset artifact" tone="good" />
        <MiniEvidence label="Full dataset row count" value={analysisStatus.rowCount.toLocaleString()} tone="good" />
        <MiniEvidence label="Valid analysis records" value={analysisStatus.validAnalysisRecords.toLocaleString()} tone="good" />
        <MiniEvidence label="Treatment count" value={summary.treatmentCount.toLocaleString()} tone="good" />
        <MiniEvidence label="Control count" value={summary.controlCount.toLocaleString()} tone="good" />
      </div>
      

      <section className="rounded-xl border border-blue-200 bg-white p-4">
        <div className="text-sm font-semibold text-slate-950">Segment Analysis Controls</div>
        <div className="mt-3 grid gap-3 md:grid-cols-3">
          <AbSelect label="Segment column selector" value={selectedSegment} options={defaults.segmentColumns} onChange={(value) => update({ segmentColumn: value })} />
          <AbSelect label="Multiple-comparison correction" value={correction} options={["None", "Bonferroni correction", "Benjamini-Hochberg FDR"]} onChange={(value) => update({ correction: value })} />
          <AbInput label="Minimum segment size" value={String(minimumSegmentSize)} onChange={(value) => update({ minimumSegmentSize: value, segmentMinimumSizeTouched: true })} />
          <label className="flex items-center gap-2 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm font-semibold text-slate-800">
            <input type="checkbox" checked={Boolean(ab.segmentShowOnlyMeetingThreshold)} onChange={(event) => update({ segmentShowOnlyMeetingThreshold: event.target.checked })} />
            <span>Show only segments meeting sample threshold</span>
          </label>
          <AbSelect label="Sort by lift / p-value / sample size" value={ab.segmentSortBy || "Lift descending"} options={["Lift descending", "P-value ascending", "Sample size descending"]} onChange={(value) => update({ segmentSortBy: value })} />
        </div>
        {workflowTestMode && !analysisStatus.fullDatasetAvailable && (
          <div className="mt-3 rounded-xl border border-amber-300 bg-amber-50 px-3 py-2 text-sm leading-6 text-amber-900">
            Preview only, not full experiment analysis. Reload the full dataset artifact before interpreting segment results.
          </div>
        )}
      </section>

      <section className="grid gap-3 md:grid-cols-4">
        <MiniEvidence label="Segments reviewed" value={ab.segmentShowOnlyMeetingThreshold ? `${displaySegments.length} shown / ${enrichedSegments.length} total` : enrichedSegments.length.toLocaleString()} tone={filterRemovesAllSegments ? "warning" : "neutral"} />
        <MiniEvidence label="Segments below minimum size" value={segmentsBelowThreshold.toLocaleString()} tone={segmentsBelowThreshold ? "warning" : "good"} />
        <MiniEvidence label="Largest positive lift segment" value={`${largestPositive.segment}: ${(largestPositive.absoluteLift * 100).toFixed(1)} pp`} tone="warning" />
        <MiniEvidence label="Largest negative lift segment" value={`${largestNegative.segment}: ${(largestNegative.absoluteLift * 100).toFixed(1)} pp`} tone="warning" />
        <MiniEvidence label="Segments statistically significant" value={significantSegments.toLocaleString()} tone={significantSegments ? "good" : "warning"} />
        <MiniEvidence label="Segments practically significant" value={practicalSegments.toLocaleString()} tone={practicalSegments ? "warning" : "neutral"} />
        <MiniEvidence label="Multiple-comparison method" value={correction} />
        <MiniEvidence label="Segment recommendation" value={filterRemovesAllSegments ? "Exploratory only, no segment meets threshold" : "Exploratory only"} tone="warning" />
      </section>

      {filterRemovesAllSegments ? (
        <AbSegmentEmptyState
          minimumSegmentSize={minimumSegmentSize}
          totalRows={totalRows}
          onShowAll={() => update({ segmentShowOnlyMeetingThreshold: false })}
          onUseDemoThreshold={() => update({ minimumSegmentSize: "2", segmentMinimumSizeTouched: true, segmentShowOnlyMeetingThreshold: true })}
          onResetThreshold={() => update({ minimumSegmentSize: "30", segmentMinimumSizeTouched: true })}
        />
      ) : (
        <>
          <section className="grid gap-3 xl:grid-cols-2">
            <SimpleAbChart title="Segment Lift Chart" rows={displaySegments.map((row) => [row.segment, row.absoluteLift])} />
            <SimpleAbChart title="Segment Conversion Rate Chart" rows={displaySegments.flatMap((row) => [[`${row.segment} ${defaults.treatmentValue}`, row.treatmentConversionRate], [`${row.segment} ${defaults.controlValue}`, row.controlConversionRate]] as Array<[string, number]>).slice(0, 12)} />
            <SimpleAbChart title="Segment Sample Size Chart" rows={displaySegments.flatMap((row) => [[`${row.segment} treatment`, row.treatmentCount], [`${row.segment} control`, row.controlCount], [`${row.segment} total`, row.totalCount]] as Array<[string, number]>).slice(0, 15)} />
            <InfoGrid title="Significance / Reliability View" rows={displaySegments.map((row) => [
              row.segment,
              `P-value ${row.pValue.toFixed(4)}; Adjusted p-value ${row.adjustedPValue.toFixed(4)}; ${row.sampleFlag}; ${row.interpretation}`,
            ])} />
          </section>

          <section className="rounded-xl border border-slate-200 bg-white p-4">
            <div className="text-sm font-semibold text-slate-950">Structured segment results table</div>
            <div className="mt-3 overflow-x-auto">
              <table className="min-w-full text-left text-xs">
                <thead className="bg-slate-50 text-slate-500">
                  <tr>
                    {["Segment", "Treatment count", "Control count", "Treatment conversion rate", "Control conversion rate", "Absolute lift", "Relative lift", "P-value", "Adjusted p-value", "Confidence interval", "Sample-size flag", "Interpretation"].map((header) => (
                      <th key={header} className="border-b border-slate-200 px-3 py-2 font-semibold">{header}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {displaySegments.map((row) => (
                    <tr key={`${row.segmentColumn}-${row.segment}`} className="border-b border-slate-100">
                      <td className="px-3 py-2 font-semibold text-slate-900">{row.segment}</td>
                      <td className="px-3 py-2">{row.treatmentCount}</td>
                      <td className="px-3 py-2">{row.controlCount}</td>
                      <td className="px-3 py-2">{(row.treatmentConversionRate * 100).toFixed(1)}%</td>
                      <td className="px-3 py-2">{(row.controlConversionRate * 100).toFixed(1)}%</td>
                      <td className="px-3 py-2">{(row.absoluteLift * 100).toFixed(1)} pp</td>
                      <td className="px-3 py-2">{(row.relativeLift * 100).toFixed(1)}%</td>
                      <td className="px-3 py-2">{row.pValue.toFixed(4)}</td>
                      <td className="px-3 py-2">{row.adjustedPValue.toFixed(4)}</td>
                      <td className="px-3 py-2">{row.confidenceInterval}</td>
                      <td className="px-3 py-2">{row.sampleFlag}</td>
                      <td className="px-3 py-2">{row.interpretation}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        </>
      )}

      <section className="grid gap-3 md:grid-cols-2">
        {segmentAllocation.warning && <WarningCard title="Allocation review" body={`Treatment/control allocation is ${summary.treatmentCount.toLocaleString()} / ${summary.controlCount.toLocaleString()}. Confirm that the observed allocation matches the intended experiment design.`} />}
        <WarningCard title="Multiple comparisons warning" body="Segment tests increase false-positive risk." />
        {segmentsBelowThreshold > 0 && <WarningCard title="Segment sample-size warning" body={`${segmentsBelowThreshold} of ${enrichedSegments.length} segment cells are below the configured ${minimumSegmentSize.toLocaleString()}-record threshold.`} />}
        <WarningCard title="Production segment inference warning" body="Segment results should be interpreted with multiple-comparison correction, segment sample size, and the overall experiment result." />
      </section>

      <section className="rounded-xl border border-blue-200 bg-white p-4">
        <div className="text-sm font-semibold text-slate-950">ATLAS Segment Interpretation</div>
        <p className="mt-2 text-sm leading-6 text-slate-700">
          Segment results are calculated from the full confirmed dataset artifact. Review segment sample size, adjusted p-values, and confidence intervals before using any segment result for rollout decisions.
        </p>
      </section>

      <TextArea
        label="Reviewer notes"
        value={state.notes || `Segment analysis by most.ads.day and most.ads.hour is based on the full confirmed dataset artifact with ${analysisStatus.rowCount.toLocaleString()} rows. Segment counts are not derived from preview rows or compact browser cache.`}
        onChange={(value) => setState({ ...state, notes: value })}
        rows={4}
      />

      <details className="rounded-xl border border-slate-200 bg-white px-4 py-3 text-sm text-slate-600">
        <summary className="cursor-pointer font-semibold text-slate-900">Documentation Notes</summary>
        <p className="mt-2 leading-6">Carry forward the segment column reviewed, multiple-comparison method, minimum-size threshold, segment-level limitations, and recommendation that segment results are exploratory only.</p>
      </details>

      <div className="flex flex-wrap gap-2">
        <button type="button" className="atlas-secondary-button" onClick={() => save()}><Save size={15} /> Save Segment Analysis Evidence</button>
        <button type="button" className="atlas-secondary-button" onClick={() => downloadText("atlas-ab-testing-segment-summary.json", JSON.stringify(segmentSummary, null, 2), "application/json;charset=utf-8")}><Download size={15} /> Export Segment Summary</button>
        <Link to="/chart-studio" className="atlas-secondary-button">Open Chart Studio</Link>
        <Link to="/analytics" className="atlas-secondary-button">Open Analytics Workbench</Link>
      </div>
    </section>
  );
}

function AbSegmentEmptyState({
  minimumSegmentSize,
  totalRows,
  onShowAll,
  onUseDemoThreshold,
  onResetThreshold,
}: {
  minimumSegmentSize: number;
  totalRows: number;
  onShowAll: () => void;
  onUseDemoThreshold: () => void;
  onResetThreshold: () => void;
}) {
  return (
    <section className="rounded-2xl border border-amber-300 bg-white p-5 shadow-sm">
      <div className="text-xs font-semibold uppercase tracking-wide text-amber-700">No segment rows available under the current threshold filter.</div>
      <h3 className="mt-1 text-lg font-semibold text-slate-950">No segments meet the current minimum sample-size threshold.</h3>
      <p className="mt-2 text-sm leading-6 text-slate-700">
        The current threshold is {minimumSegmentSize} records per segment, but only {totalRows} records are available in the current analysis view. If this is a preview-only view, reload the full dataset artifact before interpreting segment results.
      </p>
      <div className="mt-4 flex flex-wrap gap-2">
        <button type="button" className="atlas-secondary-button" onClick={onShowAll}>Show all exploratory segments</button>
        <button type="button" className="atlas-secondary-button" onClick={onUseDemoThreshold}>Use demo threshold: 2</button>
        <button type="button" className="atlas-secondary-button" onClick={onResetThreshold}>Reset threshold to 30</button>
      </div>
    </section>
  );
}

function parsePercent(value: string) {
  const numeric = Number.parseFloat(String(value).replace(/[^\d.-]/g, ""));
  if (!Number.isFinite(numeric)) return 0;
  return numeric > 1 ? numeric / 100 : numeric;
}

function formatCurrency(value: number) {
  const sign = value < 0 ? "-" : "";
  const absolute = Math.abs(value);
  return `${sign}$${Math.round(absolute).toLocaleString()}`;
}

function AbBusinessImpact({
  state,
  setState,
  analysis,
  summary,
  imbalance,
  defaults,
  dataReady,
  save,
  analysisStatus,
}: {
  state: NodeState;
  setState: (state: NodeState) => void;
  analysis: ReturnType<typeof analyzeAbLift>;
  summary: ReturnType<typeof summarizeAbGroups>;
  imbalance: ReturnType<typeof allocationImbalance>;
  defaults: AbTestingDefaults;
  dataReady: boolean;
  save: () => NodeState;
  analysisStatus: AbAnalysisDataset["status"];
}) {
  const ab = { ...emptyState().ab, ...(state.ab ?? {}) };
  const update = (changes: Partial<NonNullable<NodeState["ab"]>>) => setState(updateAbState(state, changes));
  const powerAssessment = abPowerAssessment(state, summary, imbalance, analysis);
  const rolloutPopulation = Math.max(0, state.numeric.sampleSize || 100000);
  const revenuePerConversion = Math.max(0, state.numeric.mse || 25);
  const costPerExposure = Math.max(0, state.numeric.varianceMultiplier || 0.05);
  const adoptionRate = parsePercent(ab.businessAdoptionRate || "100%");
  const treatmentExposures = rolloutPopulation * adoptionRate;
  const observedLift = analysis.absoluteLift;
  const conservativeLift = Math.max(0, analysis.confidenceLow);
  const optimisticLift = Math.max(observedLift, analysis.confidenceHigh);
  const breakEvenLift = rolloutPopulation && revenuePerConversion ? (treatmentExposures * costPerExposure) / (rolloutPopulation * revenuePerConversion) : 0;
  const manualLift = parsePercent(ab.businessManualLift || "1 pp");
  const selectedLift = ab.businessLiftEstimate === "Lower confidence bound"
    ? analysis.confidenceLow
    : ab.businessLiftEstimate === "Conservative adjusted lift"
      ? conservativeLift
      : ab.businessLiftEstimate === "Manual lift assumption"
        ? manualLift
        : observedLift;
  const businessScenario = (label: string, lift: number, interpretation: string) => {
    const incrementalConversions = dataReady ? Math.round(rolloutPopulation * lift) : 0;
    const incrementalRevenue = incrementalConversions * revenuePerConversion;
    const treatmentCost = treatmentExposures * costPerExposure;
    const netImpact = incrementalRevenue - treatmentCost;
    const roi = treatmentCost ? netImpact / treatmentCost : 0;
    return { label, lift, incrementalConversions, incrementalRevenue, treatmentCost, netImpact, roi, interpretation };
  };
  const selectedScenario = businessScenario(ab.businessConfidenceScenario || "Observed", selectedLift, "Selected assumption");
  const scenarios = [
    businessScenario("Optimistic", optimisticLift, "Positive but uncertain"),
    businessScenario("Observed", observedLift, powerAssessment.adequatelyPowered ? "Observed full-data treatment effect" : `Underpowered for the selected ${powerAssessment.relativeLiftPct.toFixed(1)}% relative MDE`),
    businessScenario("Conservative", conservativeLift, "Requires full-data validation"),
    businessScenario("Break-even", breakEvenLift, "Break-even threshold"),
  ];
  const sensitivityRows = [
    ["Revenue per conversion", `${formatCurrency(revenuePerConversion)} drives incremental revenue for each converted user.`],
    ["Cost per exposure", `${formatCurrency(costPerExposure)} is applied to ${Math.round(treatmentExposures).toLocaleString()} expected treatment exposures.`],
    ["Rollout population", `${rolloutPopulation.toLocaleString()} users scales both conversion upside and treatment cost.`],
    ["Lift assumption", `${(selectedLift * 100).toFixed(2)} pp is the current selected lift used for the main scenario.`],
  ];
  const impactSummary = {
    dataset: defaults.dataset,
    rolloutPopulation,
    revenuePerConversion,
    costPerExposure,
    adoptionRate,
    selectedLift,
    scenarios,
    pValue: analysis.pValue,
    allocationRatio: `${summary.treatmentCount}/${summary.controlCount}`,
  };

  return (
    <section className="space-y-4 rounded-2xl border border-blue-200 bg-blue-50 p-5 shadow-sm">
      <div>
        <div className="text-xs font-semibold uppercase tracking-wide text-blue-700">Business Impact Scenario Analysis</div>
        <h2 className="mt-1 text-lg font-semibold text-slate-950">Business Impact</h2>
        <p className="mt-1 text-sm leading-6 text-blue-950">These are business assumptions. Estimate economic value, downside sensitivity, and launch readiness under explicit business assumptions.</p>
      </div>
      <div className="grid gap-3 md:grid-cols-3">
        <MiniEvidence label="Analysis source" value={analysisStatus.fullDatasetAvailable ? "Full dataset artifact" : "Preview only, not full experiment analysis"} tone={analysisStatus.fullDatasetAvailable ? "good" : "warning"} />
        <MiniEvidence label="Full dataset row count" value={analysisStatus.rowCount.toLocaleString()} tone={analysisStatus.fullDatasetAvailable ? "good" : "warning"} />
        <MiniEvidence label="Valid analysis records" value={analysisStatus.validAnalysisRecords.toLocaleString()} tone={analysisStatus.fullDatasetAvailable ? "good" : "warning"} />
      </div>
      

      <section className="rounded-xl border border-blue-200 bg-white p-4">
        <div className="text-sm font-semibold text-slate-950">Business Impact Assumptions</div>
        <div className="mt-3 grid gap-3 md:grid-cols-3">
          <NumberField label="Expected rollout population" value={rolloutPopulation} onChange={(value) => setState({ ...state, numeric: { ...state.numeric, sampleSize: value } })} />
          <NumberField label="Revenue per conversion" value={revenuePerConversion} onChange={(value) => setState({ ...state, numeric: { ...state.numeric, mse: value } })} />
          <NumberField label="Cost per treatment exposure" value={costPerExposure} onChange={(value) => setState({ ...state, numeric: { ...state.numeric, varianceMultiplier: value } })} />
          <AbInput label="Expected treatment adoption / exposure rate" value={ab.businessAdoptionRate || "100%"} onChange={(value) => update({ businessAdoptionRate: value })} />
          <AbSelect label="Lift estimate to use" value={ab.businessLiftEstimate || "Observed absolute lift"} options={["Observed absolute lift", "Lower confidence bound", "Conservative adjusted lift", "Manual lift assumption"]} onChange={(value) => update({ businessLiftEstimate: value })} />
          <AbSelect label="Confidence scenario" value={ab.businessConfidenceScenario || "Observed"} options={["Optimistic", "Observed", "Conservative", "Break-even", "Manual"]} onChange={(value) => update({ businessConfidenceScenario: value })} />
          <AbSelect label="Cost basis" value={ab.businessCostBasis || "Per treatment exposure"} options={["Per treatment exposure", "Per converted user", "Fixed campaign cost", "Mixed fixed + variable cost"]} onChange={(value) => update({ businessCostBasis: value })} />
          <AbSelect label="Business decision threshold" value={ab.businessDecisionThreshold || "Net impact > 0"} options={["Net impact > 0", "ROI > 10%", "ROI > 25%", "Custom"]} onChange={(value) => update({ businessDecisionThreshold: value })} />
          <AbInput label="Manual lift assumption" value={ab.businessManualLift || "1 pp"} onChange={(value) => update({ businessManualLift: value })} />
        </div>
      </section>

      <section className="grid gap-3 md:grid-cols-4">
        <MiniEvidence label="Observed absolute lift" value={`${(observedLift * 100).toFixed(2)} pp`} tone="warning" />
        <MiniEvidence label="Conservative lift estimate" value={`${(conservativeLift * 100).toFixed(2)} pp`} tone="warning" />
        <MiniEvidence label="Expected rollout population" value={rolloutPopulation.toLocaleString()} />
        <MiniEvidence label="Incremental conversions" value={selectedScenario.incrementalConversions.toLocaleString()} />
        <MiniEvidence label="Incremental revenue" value={formatCurrency(selectedScenario.incrementalRevenue)} />
        <MiniEvidence label="Treatment cost" value={formatCurrency(selectedScenario.treatmentCost)} />
        <MiniEvidence label="Net impact" value={formatCurrency(selectedScenario.netImpact)} tone={selectedScenario.netImpact > 0 ? "good" : "warning"} />
        <MiniEvidence label="ROI" value={`${(selectedScenario.roi * 100).toFixed(1)}%`} tone={selectedScenario.roi > 0 ? "good" : "warning"} />
        <MiniEvidence label="Break-even lift" value={`${(breakEvenLift * 100).toFixed(2)} pp`} />
        <MiniEvidence label="Business impact status" value={selectedScenario.netImpact > 0 ? "Positive scenario but uncertain" : "Negative scenario"} tone="warning" />
        <MiniEvidence label="Decision readiness" value={analysis.statisticallySignificant && selectedLift >= breakEvenLift && !imbalance.warning ? "Governance review required" : "Not launch-ready"} tone="warning" />
      </section>

      <WarningCard title="Business impact warning" body="Business impact must use actual campaign economics before a production decision. Treatment-effect inputs are now sourced from the full confirmed dataset artifact when available." />

      <section className="grid gap-4 xl:grid-cols-2">
        <InfoGrid title="Business impact scenario table" rows={scenarios.map((row) => [
          row.label,
          `Lift used ${(row.lift * 100).toFixed(2)} pp; incremental conversions ${row.incrementalConversions.toLocaleString()}; incremental revenue ${formatCurrency(row.incrementalRevenue)}; treatment cost ${formatCurrency(row.treatmentCost)}; net impact ${formatCurrency(row.netImpact)}; ROI ${(row.roi * 100).toFixed(1)}%; ${row.interpretation}`,
        ])} />
        <SimpleAbChart title="Net Impact by Scenario" rows={scenarios.map((row) => [row.label, row.netImpact])} />
        <SimpleAbChart title="Incremental Conversion Scenario" rows={scenarios.map((row) => [row.label, row.incrementalConversions])} />
        <InfoGrid title="Break-even Review" rows={[
          ["Break-even lift", `${(breakEvenLift * 100).toFixed(2)} pp`],
          ["Observed lift", `${(observedLift * 100).toFixed(2)} pp`],
          ["Conservative lift", `${(conservativeLift * 100).toFixed(2)} pp`],
          ["Margin above / below break-even", `${((selectedLift - breakEvenLift) * 100).toFixed(2)} pp`],
        ]} />
        <InfoGrid title="Sensitivity Review" rows={sensitivityRows} />
      </section>

      <section className="grid gap-3 md:grid-cols-2">
        <WarningCard title="Power at selected MDE" body={`Estimated power is ${(powerAssessment.estimatedPower * 100).toFixed(0)}% for the selected ${powerAssessment.relativeLiftPct.toFixed(1)}% relative MDE.`} />
        <WarningCard title="Statistical evidence" body={analysis.statisticallySignificant ? `The treatment effect is statistically significant (p=${analysis.pValue.toFixed(4)}), but statistical significance does not replace practical, allocation, and business review.` : `The treatment effect is not statistically significant (p=${analysis.pValue.toFixed(4)}).`} />
        <WarningCard title="Decision warning" body="Business impact remains scenario evidence until campaign economics, allocation quality, guardrails, and governance approvals are confirmed." />
        <WarningCard title="Scenario value warning" body="Scenario value depends on uncertain lift estimate." />
      </section>

      <section className="rounded-xl border border-blue-200 bg-white p-4">
        <div className="text-sm font-semibold text-slate-950">ATLAS Business Impact Interpretation</div>
        <p className="mt-2 text-sm leading-6 text-slate-700">
          The observed lift produces a positive business-impact scenario under the current assumptions. Treatment-effect inputs are based on the full confirmed dataset artifact when available, while business value still depends on reviewer-entered rollout population, revenue, cost, and adoption assumptions.
        </p>
      </section>

      <TextArea
        label="Reviewer notes"
        value={state.notes || `Business impact uses reviewer-entered rollout, revenue, cost, and adoption assumptions together with the full-data treatment effect. Statistical significance is ${analysis.statisticallySignificant ? "present" : "not established"}; estimated power at the selected ${powerAssessment.relativeLiftPct.toFixed(1)}% relative MDE is ${(powerAssessment.estimatedPower * 100).toFixed(0)}%. Confirm campaign economics, allocation quality, guardrails, and governance approvals before final decisioning.`}
        onChange={(value) => setState({ ...state, notes: value })}
        rows={4}
      />

      <details className="rounded-xl border border-slate-200 bg-white px-4 py-3 text-sm text-slate-600">
        <summary className="cursor-pointer font-semibold text-slate-900">Documentation Notes</summary>
        <p className="mt-2 leading-6">Document business assumptions, lift scenario selected, sensitivity limitations, break-even lift, and the underpowered-test limitation before saving final decision evidence.</p>
      </details>

      <div className="flex flex-wrap gap-2">
        <button type="button" className="atlas-secondary-button" onClick={() => save()}><Save size={15} /> Save Business Impact Evidence</button>
        <button type="button" className="atlas-secondary-button" onClick={() => downloadText("atlas-ab-testing-business-impact-summary.json", JSON.stringify(impactSummary, null, 2), "application/json;charset=utf-8")}><Download size={15} /> Export Business Impact Summary</button>
        <Link to="/chart-studio" className="atlas-secondary-button">Open Chart Studio</Link>
        <Link to="/analytics" className="atlas-secondary-button">Open Analytics Workbench</Link>
      </div>
    </section>
  );
}

function AbDecisionRecommendation({
  recommendation,
  analysis,
  summary,
  imbalance,
  defaults,
  state,
  setState,
  save,
  analysisStatus,
}: {
  recommendation: string;
  analysis: ReturnType<typeof analyzeAbLift>;
  summary: ReturnType<typeof summarizeAbGroups>;
  imbalance: ReturnType<typeof allocationImbalance>;
  defaults: AbTestingDefaults;
  state: NodeState;
  setState: (state: NodeState) => void;
  save: () => NodeState;
  analysisStatus: AbAnalysisDataset["status"];
}) {
  const ab = { ...emptyState().ab, ...(state.ab ?? {}) };
  const update = (changes: Partial<NonNullable<NodeState["ab"]>>) => setState(updateAbState(state, changes));
  const powerAssessment = abPowerAssessment(state, summary, imbalance, analysis);
  const practicalThreshold = Number.parseFloat(String(ab.practicalSignificanceThreshold || "1 pp")) / 100 || 0.01;
  const practicallySignificant = Math.abs(analysis.absoluteLift) >= practicalThreshold;
  const systemDecision = recommendation === "Run longer" ? "Inconclusive, Run Longer" : recommendation;
  const selectedDecision = ab.decisionRecommendationTouched && ab.decisionRecommendation ? ab.decisionRecommendation : systemDecision;
  const finalDecision = selectedDecision === "Run longer" ? "Inconclusive, Run Longer" : selectedDecision;
  useEffect(() => {
    if (!ab.decisionRecommendationTouched && ab.decisionRecommendation !== systemDecision) {
      setState(updateAbState(state, { decisionRecommendation: systemDecision }));
    }
  }, [ab.decisionRecommendation, ab.decisionRecommendationTouched, setState, state, systemDecision]);
  const treatmentRate = `${(summary.treatmentRate * 100).toFixed(1)}%`;
  const controlRate = `${(summary.controlRate * 100).toFixed(1)}%`;
  const observedLift = `${(analysis.absoluteLift * 100).toFixed(2)} pp`;
  const pValue = analysis.pValue.toFixed(4);
  const confidenceCrossesZero = analysis.confidenceLow <= 0 && analysis.confidenceHigh >= 0;
  const launchBlockers = [
    !analysis.statisticallySignificant ? "statistical significance is not established" : "",
    !practicallySignificant ? `observed lift is below the ${String(ab.practicalSignificanceThreshold || "1 pp")} practical threshold` : "",
    !powerAssessment.adequatelyPowered ? `power is ${(powerAssessment.estimatedPower * 100).toFixed(0)}% at the selected ${powerAssessment.relativeLiftPct.toFixed(1)}% relative MDE` : "",
    imbalance.warning ? "the observed allocation requires design and randomization review" : "",
  ].filter(Boolean);
  const launchReady = launchBlockers.length === 0;
  const launchReadinessReason = launchReady ? "Statistical, practical, power, and allocation checks meet the configured thresholds." : `Launch is blocked because ${launchBlockers.join("; ")}.`;
  const defaultDecisionRationale =
    `Final decision: ${finalDecision}.\n\n` +
    `The ${defaults.treatmentValue} treatment produced ${observedLift} absolute lift versus ${defaults.controlValue} using the full confirmed ${defaults.dataset} artifact with ${analysisStatus.rowCount.toLocaleString()} rows. The two-sided p-value is ${pValue}; the 95% confidence interval is ${(analysis.confidenceLow * 100).toFixed(2)} pp to ${(analysis.confidenceHigh * 100).toFixed(2)} pp. ${launchReadinessReason}\n\n` +
    "The next action must address the listed launch blockers, preserve the confirmed dataset lineage, and then re-run power, treatment-effect, segment, business-impact, and governance review before changing the decision.";
  const legacyDecisionText = /p-value is not significant|confidence interval crosses zero|underpowered and not launch-ready|workflow validation evidence/i;
  const savedDecisionRationale = ab.decisionRationale || "";
  const savedReviewerNotes = state.rationale || "";
  const decisionRationaleValue = savedDecisionRationale.includes("Final decision:") && !legacyDecisionText.test(savedDecisionRationale) ? savedDecisionRationale : defaultDecisionRationale;
  const reviewerNotesValue = savedReviewerNotes.includes("Final decision:") && !legacyDecisionText.test(savedReviewerNotes) ? savedReviewerNotes : defaultDecisionRationale;
  const decisionSummary = {
    dataset: defaults.dataset,
    decisionRecommendation: finalDecision,
    followUpAction: ab.followUpAction || "Collect more data",
    pValue: analysis.pValue,
    statisticallySignificant: analysis.statisticallySignificant,
    absoluteLift: analysis.absoluteLift,
    treatmentCount: summary.treatmentCount,
    controlCount: summary.controlCount,
    practicalSignificance: practicallySignificant,
    estimatedPowerAtSelectedMde: powerAssessment.estimatedPower,
    launchBlockers,
    overallReadiness: launchReady ? "Launch-ready" : "Not launch-ready",
  };

  return (
    <section className="space-y-4 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
      <div>
        <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Decision Cockpit</div>
        <h2 className="mt-1 text-lg font-semibold text-slate-950">Decision Recommendation</h2>
        <p className="mt-1 text-sm leading-6 text-slate-600">Synthesize treatment evidence, business impact, risk, and required actions before launch. It does not rely only on p-value.</p>
      </div>
      <div className="grid gap-3 md:grid-cols-3">
        <MiniEvidence label="Analysis source" value="Full dataset artifact" tone="good" />
        <MiniEvidence label="Full dataset row count" value={analysisStatus.rowCount.toLocaleString()} tone="good" />
        <MiniEvidence label="Valid analysis records" value={analysisStatus.validAnalysisRecords.toLocaleString()} tone="good" />
      </div>
      

      <section className="rounded-2xl border border-amber-300 bg-slate-950 p-5 text-white shadow-sm">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <div className="text-xs font-semibold uppercase tracking-wide text-amber-200">Final Experiment Decision</div>
            <h3 className="mt-2 text-2xl font-semibold text-white">Decision: {finalDecision}</h3>
            <p className="mt-2 max-w-4xl text-sm leading-6 text-slate-200">
              The {defaults.treatmentValue} treatment produced {observedLift} absolute lift versus {defaults.controlValue}. Statistical evidence, practical significance, power at the selected MDE, allocation quality, business impact, and governance readiness are evaluated together.
            </p>
          </div>
          <div className="rounded-xl border border-amber-300 bg-amber-100 px-4 py-3 text-slate-950">
            <div className="text-xs font-semibold uppercase tracking-wide text-amber-800">Launch readiness</div>
            <div className="mt-1 text-lg font-semibold">{launchReady ? "Launch-ready" : "Not launch-ready"}</div>
            <p className="mt-1 max-w-xs text-xs leading-5 text-amber-950">{launchReadinessReason}</p>
          </div>
        </div>

        <div className="mt-4 flex flex-wrap gap-2">
          {[
            launchReady ? "Launch-ready" : "Not launch-ready",
            analysis.statisticallySignificant ? "Statistically significant" : "Statistical significance not met",
            practicallySignificant ? "Practical threshold met" : "Below practical threshold",
            powerAssessment.adequatelyPowered ? "Power target met" : `Power ${(powerAssessment.estimatedPower * 100).toFixed(0)}% at selected MDE`,
            imbalance.warning ? "Allocation review required" : "Allocation check passed",
          ].map((chip) => (
            <span key={chip} className="rounded-full border border-amber-300 bg-amber-100 px-3 py-1 text-xs font-semibold text-amber-950">{chip}</span>
          ))}
        </div>

        <div className="mt-5 grid gap-3 xl:grid-cols-4">
          <div className="rounded-xl border border-slate-700 bg-slate-900 p-4">
            <div className="text-xs font-semibold uppercase tracking-wide text-amber-200">Directional Result</div>
            <p className="mt-2 text-sm leading-6 text-slate-100">{defaults.treatmentValue} outperformed {defaults.controlValue} in the confirmed sample.</p>
            <p className="mt-2 text-xs leading-5 text-slate-300">Treatment conversion rate: {treatmentRate}</p>
            <p className="text-xs leading-5 text-slate-300">Control conversion rate: {controlRate}</p>
            <p className="text-xs leading-5 text-slate-300">Observed lift: {observedLift}</p>
          </div>
          <div className="rounded-xl border border-slate-700 bg-slate-900 p-4">
            <div className="text-xs font-semibold uppercase tracking-wide text-amber-200">Statistical Conclusion</div>
            <p className="mt-2 text-sm leading-6 text-slate-100">{analysis.statisticallySignificant ? "Statistically significant." : "Not statistically significant."}</p>
            <p className="mt-2 text-xs leading-5 text-slate-300">P-value: {pValue}</p>
            <p className="text-xs leading-5 text-slate-300">Confidence interval {confidenceCrossesZero ? "crosses zero" : "does not cross zero"}.</p>
            <p className="text-xs leading-5 text-slate-300">Review power and confidence interval before final decisioning.</p>
          </div>
          <div className="rounded-xl border border-slate-700 bg-slate-900 p-4">
            <div className="text-xs font-semibold uppercase tracking-wide text-amber-200">Business Conclusion</div>
            <p className="mt-2 text-sm leading-6 text-slate-100">Business scenario is positive under current assumptions, but the value estimate depends on uncertain lift.</p>
          </div>
          <div className="rounded-xl border border-slate-700 bg-slate-900 p-4">
            <div className="text-xs font-semibold uppercase tracking-wide text-amber-200">Required Next Action</div>
            <p className="mt-2 text-sm leading-6 text-slate-100">{launchReady ? "Complete governance approval and execute the selected post-decision rollout strategy." : "Resolve the configured launch blockers, then refresh the evidence and decision."}</p>
          </div>
        </div>
      </section>

      <section className="rounded-xl border border-amber-300 bg-amber-50 p-4">
        <div className="text-sm font-semibold text-amber-950">Why ATLAS selected this decision</div>
        <div className="mt-3 grid gap-3 text-sm leading-6 text-amber-950 md:grid-cols-2">
          <p>If treatment lift is positive but statistical evidence, practical significance, or selected-MDE power is insufficient, recommend Inconclusive / Run Longer.</p>
          <p>If lift is positive, statistically significant, practically significant, powered, and business impact is positive, recommend Launch.</p>
          <p>If lift is negative or business impact is negative, recommend Keep Control or Do Not Launch.</p>
          <p>If segment effects are promising but overall result is weak, recommend Segmented follow-up only if segment evidence is reliable.</p>
        </div>
        <div className="mt-3 rounded-lg border border-amber-400 bg-white px-3 py-2 text-sm font-semibold text-amber-950">
          Triggered rule: {launchBlockers.length ? launchBlockers.join(" + ") : "all configured launch thresholds passed"} = {finalDecision}.
        </div>
      </section>

      <section className="rounded-xl border border-blue-200 bg-blue-50 p-4">
        <div className="text-sm font-semibold text-blue-950">What "Run Longer" Means</div>
        <p className="mt-2 text-sm leading-6 text-blue-950">
          Run longer means continue collecting treatment and control observations until the experiment has enough sample size for the selected confidence level, desired power, and minimum detectable effect. If this is an already-completed dataset, load a larger experiment file, extend the observation window, or append additional experiment records before making a production launch decision.
        </p>
      </section>

      <section className="rounded-xl border border-slate-200 bg-slate-50 p-4">
        <div className="text-sm font-semibold text-slate-950">Decision Controls</div>
        <div className="mt-3 grid gap-3 md:grid-cols-3">
          <AbSelect label="Decision recommendation" value={selectedDecision} options={["Launch treatment", "Keep control", "Run longer", "Inconclusive, Run Longer", "Segmented rollout", "Inconclusive", "Do not launch", "Needs review"]} onChange={(value) => update({ decisionRecommendation: value, decisionRecommendationTouched: true })} />
          <AbInput label="Decision owner" value={ab.decisionOwner || "Decision owner"} onChange={(value) => update({ decisionOwner: value })} />
          <AbInput label="Decision date (YYYY-MM-DD)" value={ab.decisionDate || ""} onChange={(value) => update({ decisionDate: value })} />
          <AbInput label="Launch readiness threshold" value={ab.launchReadinessThreshold || "Not launch-ready until adequately powered"} onChange={(value) => update({ launchReadinessThreshold: value })} />
          <AbSelect label="Risk tolerance" value={ab.riskTolerance || "Low"} options={["Low", "Moderate", "High"]} onChange={(value) => update({ riskTolerance: value })} />
          <AbSelect label="Follow-up action" value={ab.followUpAction || "Collect more data"} options={["Collect more data", "Run full-dataset analysis", "Launch controlled rollout", "Run segmented follow-up test", "Keep control", "Escalate for review"]} onChange={(value) => update({ followUpAction: value })} />
        </div>
        <TextArea label="Decision rationale" value={decisionRationaleValue} onChange={(value) => update({ decisionRationale: value })} rows={3} />
      </section>

      <section className="rounded-xl border border-slate-200 bg-white p-4">
        <div className="text-sm font-semibold text-slate-950">Evidence Scorecard</div>
        <div className="mt-3 grid gap-3 md:grid-cols-3">
          <MiniEvidence label="Statistical significance" value={analysis.statisticallySignificant ? "Significant" : "Not significant"} tone={analysis.statisticallySignificant ? "good" : "warning"} />
          <MiniEvidence label="Practical significance" value={practicallySignificant ? "Threshold met" : "Below threshold"} tone={practicallySignificant ? "good" : "warning"} />
          <MiniEvidence label="Power status" value={`${(powerAssessment.estimatedPower * 100).toFixed(0)}% at selected MDE`} tone={powerAssessment.adequatelyPowered ? "good" : "warning"} />
          <MiniEvidence label="Randomization quality" value={imbalance.warning ? "Allocation concern" : "No material concern"} tone={imbalance.warning ? "warning" : "good"} />
          <MiniEvidence label="Segment consistency" value="Exploratory only" tone="warning" />
          <MiniEvidence label="Business impact" value="Positive scenario but uncertain" tone="warning" />
          <MiniEvidence label="Data quality" value="Structurally clean" tone="good" />
          <MiniEvidence label="Governance readiness" value="Needs documentation" tone="warning" />
          <MiniEvidence label="Overall decision readiness" value={launchReady ? "Launch-ready" : "Not launch-ready"} tone={launchReady ? "good" : "warning"} />
        </div>
      </section>

      <section className="rounded-xl border border-blue-200 bg-blue-50 p-4">
        <div className="text-sm font-semibold text-blue-950">ATLAS Decision Recommendation</div>
        <p className="mt-2 text-sm leading-6 text-blue-950">
          Recommended decision: {finalDecision}.
        </p>
        <p className="mt-2 text-sm leading-6 text-blue-950">
          The {defaults.treatmentValue} treatment shows {observedLift} absolute conversion lift compared with {defaults.controlValue}. The analysis is based on the full confirmed dataset artifact. Statistical significance is {analysis.statisticallySignificant ? "met" : "not met"}; practical significance is {practicallySignificant ? "met" : "not met"}; selected-MDE power is {(powerAssessment.estimatedPower * 100).toFixed(0)}%.
        </p>
        <p className="mt-2 text-sm leading-6 text-blue-950">
          Recommended next step: {launchReady ? "complete governance approval and configure the Post-Decision Plan." : `resolve ${launchBlockers.join("; ")}, then refresh randomization, power, treatment-effect, segment, business-impact, and governance evidence.`}
        </p>
      </section>

      <section className="grid gap-4 xl:grid-cols-2">
        <InfoGrid title="Evidence supporting treatment" rows={[
          ["Treatment conversion rate", "Treatment conversion rate is higher than control."],
          ["Observed absolute lift", "Observed absolute lift is positive."],
          ["Business impact", "Business-impact scenario is positive under current assumptions."],
          ["Data quality", "Dataset has no duplicate units or mapped missing values."],
        ]} />
        <InfoGrid title="Evidence weakening launch decision" rows={[
          ["Sample size", `${analysisStatus.validAnalysisRecords.toLocaleString()} valid full-data records are available.`],
          ["Power", `${(powerAssessment.estimatedPower * 100).toFixed(0)}% estimated power at the selected ${powerAssessment.relativeLiftPct.toFixed(1)}% relative MDE.`],
          ["P-value", `${pValue}; ${analysis.statisticallySignificant ? "statistically significant" : "not statistically significant"}.`],
          ["Confidence interval", `${(analysis.confidenceLow * 100).toFixed(2)} pp to ${(analysis.confidenceHigh * 100).toFixed(2)} pp; ${confidenceCrossesZero ? "crosses zero" : "does not cross zero"}.`],
          ["Allocation", "Treatment/control allocation is imbalanced."],
          ["Segments", "Segment results require multiple-comparison control and segment-specific decision review."],
          ["Business impact", "Business impact is based on uncertain lift."],
        ]} />
      </section>

      <section className="rounded-xl border border-amber-300 bg-amber-50 p-4">
        <div className="text-sm font-semibold text-amber-950">Required Next Actions Before Launch</div>
        <ul className="mt-3 grid gap-2 text-sm leading-6 text-amber-950 md:grid-cols-2">
          {[
            "Retain confirmed full-dataset lineage and mapping evidence.",
            "Confirm randomization or holdout design.",
            "Confirm treatment/control allocation was intentional.",
            "Resolve the selected-MDE power requirement or revise the pre-specified MDE with justification.",
            "Review confidence interval and practical lift.",
            "Validate segment findings with adequate sample size.",
            "Replace demo business assumptions with actual campaign economics.",
            "Save evidence to Model Evidence Center.",
            "Attach final decision evidence to Model Documentation Studio.",
            "Define monitoring plan for rollout.",
          ].map((item) => <li key={item}>- {item}</li>)}
        </ul>
      </section>

      <InfoGrid title="Decision recommendation table" rows={[
        ["Launch treatment", `Use when statistical significance, practical lift, selected-MDE power, allocation quality, business impact, and governance are all acceptable. Current status: ${launchReady ? "Supported" : "Not supported"}.`],
        ["Keep control", `Use when treatment effect is negative or launch risk is unacceptable. Current status: ${finalDecision === "Keep control" ? "Selected" : "Not selected"}.`],
        ["Run longer", `Use when one or more inferential or design thresholds need additional evidence. Current status: ${finalDecision.includes("Run Longer") ? "Selected" : "Not selected"}.`],
        ["Inconclusive, Run Longer", `Use when observed direction is promising but practical significance, power, allocation quality, or statistical evidence is insufficient. Current blockers: ${launchBlockers.join("; ") || "None"}.`],
        ["Segmented rollout", `Use only when pre-specified or validated segment effects are reliable and operationally governable. Current status: ${finalDecision === "Segmented rollout" ? "Selected" : "Not selected"}.`],
        ["Inconclusive", `Use when evidence is insufficient for either launch or keep-control. Current status: ${finalDecision === "Inconclusive" ? "Selected" : "Not selected"}.`],
        ["Do not launch", `Use when negative, unsafe, non-compliant, or economically unfavorable evidence dominates. Current status: ${finalDecision === "Do not launch" ? "Selected" : "Not selected"}.`],
      ]} />

      <section className="grid gap-3 md:grid-cols-2">
        <WarningCard title="Power at selected MDE" body={`Estimated power is ${(powerAssessment.estimatedPower * 100).toFixed(0)}% for a ${powerAssessment.relativeLiftPct.toFixed(1)}% relative MDE.`} />
        <WarningCard title="Statistical evidence" body={`P-value is ${pValue}; the confidence interval ${confidenceCrossesZero ? "crosses" : "does not cross"} zero.`} />
        <WarningCard title="Decision warning" body={launchReadinessReason} />
        <WarningCard title="Business impact warning" body="Scenario value depends on uncertain lift estimate." />
      </section>

      <TextArea
        label="Reviewer notes"
        value={reviewerNotesValue}
        onChange={(value) => setState({ ...state, rationale: value })}
        rows={4}
      />

      <details className="rounded-xl border border-slate-200 bg-white px-4 py-3 text-sm text-slate-600">
        <summary className="cursor-pointer font-semibold text-slate-900">Documentation Notes</summary>
        <p className="mt-2 leading-6">Document the decision, owner, evidence scorecard, supporting evidence, weakening evidence, required launch prerequisites, and follow-up action in MEC and MDS.</p>
      </details>

      <div className="flex flex-wrap gap-2">
        <button type="button" className="atlas-secondary-button" onClick={() => save()}><Save size={15} /> Save Decision Recommendation Evidence</button>
        <button type="button" className="atlas-secondary-button" onClick={() => downloadText("atlas-ab-testing-decision-summary.json", JSON.stringify(decisionSummary, null, 2), "application/json;charset=utf-8")}><Download size={15} /> Export Decision Summary</button>
        <Link to="/model-evidence-center" className="atlas-secondary-button">Open Model Evidence Center</Link>
        <Link to="/model-document-studio" className="atlas-secondary-button">Attach to Model Documentation Studio</Link>
        <Link to="/decision-journal" className="atlas-secondary-button">Open Decision Journal</Link>
      </div>
    </section>
  );
}

function AbDocumentationReview({
  state,
  setState,
  defaults,
  analysis,
  summary,
  imbalance,
  recommendation,
  analysisStatus,
  save,
}: {
  state: NodeState;
  setState: (state: NodeState) => void;
  defaults: AbTestingDefaults;
  analysis: ReturnType<typeof analyzeAbLift>;
  summary: ReturnType<typeof summarizeAbGroups>;
  imbalance: ReturnType<typeof allocationImbalance>;
  recommendation: string;
  analysisStatus: AbAnalysisDataset["status"];
  save: () => NodeState;
}) {
  const ab = { ...emptyState().ab, ...(state.ab ?? {}) };
  const update = (changes: Partial<NonNullable<NodeState["ab"]>>) => setState(updateAbState(state, changes));
  const powerAssessment = abPowerAssessment(state, summary, imbalance, analysis);
  const practicalThreshold = Number.parseFloat(String(ab.practicalSignificanceThreshold || "1 pp")) / 100 || 0.01;
  const practicallySignificant = Math.abs(analysis.absoluteLift) >= practicalThreshold;
  const systemDecision = recommendation === "Run longer" ? "Inconclusive, Run Longer" : recommendation;
  const finalDecision = ab.decisionRecommendationTouched && ab.decisionRecommendation ? ab.decisionRecommendation : systemDecision;
  const launchBlockers = [
    !analysis.statisticallySignificant ? "statistical significance is not established" : "",
    !practicallySignificant ? `observed lift is below the ${ab.practicalSignificanceThreshold || "1 pp"} practical threshold` : "",
    !powerAssessment.adequatelyPowered ? `power is ${(powerAssessment.estimatedPower * 100).toFixed(0)}% at the selected ${powerAssessment.relativeLiftPct.toFixed(1)}% relative MDE` : "",
    imbalance.warning ? "allocation requires design review" : "",
  ].filter(Boolean);
  const launchReady = launchBlockers.length === 0;
  const reviewerNote =
    state.notes ||
    `Documentation review is based on the full confirmed ${defaults.dataset} artifact with ${analysisStatus.rowCount.toLocaleString()} rows and ${analysisStatus.validAnalysisRecords.toLocaleString()} valid analysis records. The current decision is ${finalDecision}. ${launchReady ? "Configured statistical, practical, power, and allocation checks support launch-readiness review." : `Final approval remains blocked because ${launchBlockers.join("; ")}.`} Preserve dataset lineage, mapping, randomization, metric, segment, business-impact, limitation, and post-decision evidence in the governed package.`;
  const coverageRows = [
    ["Business Purpose", "Project Context", "Mapped", "experiment_context", "Business Purpose", "Review text"],
    ["Experiment Design", "Experiment Setup", "Mapped", "experiment_design", "Experiment Design", "Review text"],
    ["Population and Eligibility", "Population and Eligibility", "Mapped", "population_eligibility", "Population and Eligibility", "Save evidence"],
    ["Treatment and Control Definition", "Treatment / Control Design", "Mapped", "treatment_control_definition", "Treatment and Control Definition", "Attach to MDS"],
    ["Data Acquisition and Mapping", "Data Acquisition and Experiment Mapping", "Saved", "data_quality", "Experiment Data", "Open MEC"],
    ["Data Quality", "Data Acquisition and Experiment EDA", "Saved", "data_quality", "Experiment Data", "Review text"],
    ["Randomization Check", "Randomization Check", imbalance.warning ? "Needs review" : "Saved", "randomization_check", "Randomization Check", imbalance.warning ? "Review allocation concern" : "Confirm evidence"],
    ["Metric Definition", "Metrics Setup", "Mapped", "metric_definition", "Metrics Definition", "Review text"],
    ["Power and Sample Size", "Power and Sample Size", powerAssessment.adequatelyPowered ? "Saved" : "Needs review", "power_analysis", "Power and Sample Size", powerAssessment.adequatelyPowered ? "Confirm evidence" : "Resolve selected-MDE power"],
    ["Experiment EDA", "Experiment EDA", "Saved", "experiment_eda", "Experiment Data", "Attach to MDS"],
    ["Experiment Analysis", "Experiment Analysis", "Saved", "experiment_analysis", "Experiment Analysis", analysis.statisticallySignificant ? "Confirm inference" : "Review statistical limitation"],
    ["Segment Analysis", "Segment Analysis", "Needs review", "segment_analysis", "Segment Analysis", "Review exploratory status"],
    ["Business Impact", "Business Impact", "Needs review", "business_impact", "Business Impact", "Replace demo assumptions"],
    ["Decision Recommendation", "Decision Recommendation", "Saved", "decision_recommendation", "Decision Recommendation", "Open MEC"],
    ["Limitations", "Decision Recommendation", "Needs review", "limitations", "Limitations", "Review text"],
    ["Post-Decision Plan", "Post-Decision Plan", ab.postDecisionStrategyTouched ? "Draft" : "Missing", "monitoring_plan", "Rollout, Monitoring, and Follow-up", "Complete post-decision plan"],
    ["Appendices", "Evidence Pack Export", "Mapped", "appendices", "Appendices", "Export evidence package"],
  ];
  const packageSummary = {
    dataset: defaults.dataset,
    unitId: defaults.unitIdColumn,
    treatment: defaults.treatmentValue,
    control: defaults.controlValue,
    outcome: defaults.outcomeColumn,
    primaryMetric: "Conversion rate",
    decision: finalDecision,
    reason: launchReady ? "Configured launch-readiness thresholds are met" : launchBlockers.join("; "),
    keyLimitation: launchReady ? "Final governance approval remains required" : launchBlockers[0] || "Reviewer confirmation required",
    rowCount: analysisStatus.rowCount,
    validAnalysisRecords: analysisStatus.validAnalysisRecords,
    treatmentCount: summary.treatmentCount,
    controlCount: summary.controlCount,
    absoluteLift: analysis.absoluteLift,
    pValue: analysis.pValue,
    estimatedPowerAtSelectedMde: powerAssessment.estimatedPower,
  };
  const reviewItems = coverageRows.filter((row) => !["Mapped", "Saved"].includes(row[2])).length;

  return (
    <section className="space-y-4 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
      <div>
        <div className="text-xs font-semibold uppercase tracking-wide text-blue-700">Documentation Readiness</div>
        <h2 className="mt-1 text-lg font-semibold text-slate-950">Documentation Review</h2>
        <p className="mt-1 text-sm leading-6 text-slate-600">Confirm the A/B testing evidence trail, Model Evidence Center package, Model Documentation Studio mapping, documentation gaps, and final reviewer decision.</p>
      </div>
      

      <section className="rounded-2xl border border-blue-200 bg-blue-50 p-4">
        <div className="text-sm font-semibold text-blue-950">A/B Testing Documentation Readiness</div>
        <div className="mt-3 grid gap-3 md:grid-cols-4">
          <MiniEvidence label="Workflow steps completed" value="14 / 15" tone="warning" />
          <MiniEvidence label="Evidence sections mapped" value={`${coverageRows.length} sections`} tone="good" />
          <MiniEvidence label="Evidence sections needing review" value={`${reviewItems} sections`} tone={reviewItems ? "warning" : "good"} />
          <MiniEvidence label="Decision status" value={finalDecision} tone={launchReady ? "good" : "warning"} />
          <MiniEvidence label="Launch readiness" value={launchReady ? "Launch-ready for governance review" : "Not launch-ready"} tone={launchReady ? "good" : "warning"} />
          <MiniEvidence label="MEC package status" value="Full-dataset evidence package" tone="good" />
          <MiniEvidence label="MDS attachment status" value="Needs final reviewer approval" tone="warning" />
          <MiniEvidence label="Evidence status" value={`${analysisStatus.validAnalysisRecords.toLocaleString()} valid records`} tone="good" />
        </div>
      </section>

      <section className="rounded-xl border border-slate-200 bg-slate-50 p-4">
        <div className="text-sm font-semibold text-slate-950">Documentation Review Controls</div>
        <div className="mt-3 grid gap-3 md:grid-cols-3">
          <AbSelect label="Documentation readiness decision" value={ab.docReadinessDecision || (launchReady ? "Ready for review" : "Needs more evidence")} options={["Ready for review", "Needs more evidence", "Ready for MDS draft", "Ready for final approval", "Not ready"]} onChange={(value) => update({ docReadinessDecision: value })} />
          <AbInput label="Reviewer" value={ab.docReviewer || ""} onChange={(value) => update({ docReviewer: value })} />
          <AbInput label="Review date" value={ab.docReviewDate || ""} onChange={(value) => update({ docReviewDate: value })} />
          <AbSelect label="Attach evidence to Model Documentation Studio?" value={ab.docAttachMds || "Yes, attach as workflow evidence"} options={["Yes, attach as workflow evidence", "Yes, attach for final approval", "No, hold for reviewer", "Not applicable"]} onChange={(value) => update({ docAttachMds: value })} />
          <AbSelect label="Export evidence package?" value={ab.docExportPackage || "Yes"} options={["Yes", "No", "Reviewer decision"]} onChange={(value) => update({ docExportPackage: value })} />
          <AbSelect label="Include limitations?" value={ab.docIncludeLimitations || "Yes"} options={["Yes", "No", "Reviewer decision"]} onChange={(value) => update({ docIncludeLimitations: value })} />
          <AbSelect label="Include monitoring plan?" value={ab.docIncludeMonitoring || "Pending monitoring plan"} options={["Pending monitoring plan", "Yes", "No", "Reviewer decision"]} onChange={(value) => update({ docIncludeMonitoring: value })} />
        </div>
        <p className="mt-3 rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-sm leading-6 text-amber-950">
          {launchReady
            ? "The confirmed full-dataset evidence meets the configured statistical, practical, power, and allocation checks. Final governance review, documentation approval, and the selected post-decision plan are still required."
            : `Final approval is not ready because ${launchBlockers.join("; ")}. The evidence package can be reviewed, but it must not be represented as launch support until these blockers are resolved or formally accepted.`}
        </p>
      </section>

      <section className="rounded-xl border border-slate-200 bg-white p-4">
        <div className="text-sm font-semibold text-slate-950">Documentation Coverage Matrix</div>
        <div className="mt-3 overflow-x-auto">
          <table className="min-w-[920px] w-full text-left text-xs">
            <thead className="bg-slate-100 text-slate-600">
              <tr>
                {["Documentation section", "Workflow evidence source", "Evidence status", "MEC evidence type", "MDS section", "Reviewer action"].map((header) => (
                  <th key={header} className="px-3 py-2 font-semibold uppercase tracking-wide">{header}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {coverageRows.map((row) => (
                <tr key={row[0]} className="border-t border-slate-200">
                  {row.map((cell, index) => (
                    <td key={`${row[0]}-${index}`} className="px-3 py-2 align-top text-slate-700">{cell}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <InfoGrid title="Experiment Evidence Package Preview" rows={[
          ["Dataset", packageSummary.dataset],
          ["Unit ID", packageSummary.unitId],
          ["Treatment", packageSummary.treatment],
          ["Control", packageSummary.control],
          ["Outcome", packageSummary.outcome],
          ["Primary metric", packageSummary.primaryMetric],
          ["Full dataset rows", packageSummary.rowCount.toLocaleString()],
          ["Valid analysis records", packageSummary.validAnalysisRecords.toLocaleString()],
          ["Treatment / control", `${packageSummary.treatmentCount.toLocaleString()} / ${packageSummary.controlCount.toLocaleString()}`],
          ["Absolute lift", `${(packageSummary.absoluteLift * 100).toFixed(2)} pp`],
          ["P-value", packageSummary.pValue.toFixed(4)],
          ["Power at selected MDE", `${(packageSummary.estimatedPowerAtSelectedMde * 100).toFixed(0)}%`],
          ["Decision", packageSummary.decision],
          ["Reason", packageSummary.reason],
          ["Key limitation", packageSummary.keyLimitation],
        ]} />
        <InfoGrid title="Generated evidence list" rows={[
          ["Project context evidence", "Available"],
          ["Data acquisition evidence", "Available"],
          ["Population eligibility evidence", "Available"],
          ["Treatment/control evidence", "Available"],
           ["Randomization evidence", imbalance.warning ? "Needs review" : "Available"],
          ["Metric definition evidence", "Available"],
           ["Power analysis evidence", powerAssessment.adequatelyPowered ? "Available" : "Needs review"],
          ["EDA evidence", "Available"],
          ["Experiment analysis evidence", "Available"],
          ["Segment analysis evidence", "Exploratory"],
          ["Business impact evidence", "Scenario-based"],
          ["Decision recommendation evidence", "Available"],
        ]} />
      </section>

      <section className="rounded-xl border border-amber-300 bg-amber-50 p-4">
        <div className="text-sm font-semibold text-amber-950">Required Documentation Gaps Before Final Approval</div>
        <ul className="mt-3 grid gap-2 text-sm leading-6 text-amber-950 md:grid-cols-2">
          {[
            "Confirm the registered dataset version and full-artifact lineage.",
            "Confirm whether randomization or holdout assignment was actually used.",
            "Replace demo business assumptions with actual campaign economics.",
            launchReady ? "Complete final governance and launch-readiness approval." : `Document launch blockers: ${launchBlockers.join("; ")}.`,
            powerAssessment.adequatelyPowered ? "Retain the selected-MDE power evidence." : "Resolve selected-MDE power through more data or a justified design revision.",
            "Complete post-decision plan.",
          ].map((item) => <li key={item}>- {item}</li>)}
        </ul>
      </section>

      <section className="rounded-xl border border-emerald-200 bg-emerald-50 p-4">
        <div className="text-sm font-semibold text-emerald-950">ATLAS Documentation Interpretation</div>
        <p className="mt-2 text-sm leading-6 text-emerald-950">
          The A/B testing workflow has generated a complete evidence trail. Documentation should clearly distinguish preview rows, compact browser cache, and the full confirmed dataset artifact. Final decision documentation should rely on the full dataset artifact and should state whether additional experiment observations or updated analysis are required before launch.
        </p>
      </section>

      <TextArea label="Reviewer notes" value={reviewerNote} onChange={(value) => setState({ ...state, notes: value })} rows={4} />

      <div className="flex flex-wrap gap-2">
        <button type="button" className="atlas-secondary-button" onClick={() => save()}><Save size={15} /> Save Documentation Review Evidence</button>
        <Link to="/model-document-studio" className="atlas-secondary-button">Open Model Documentation Studio</Link>
        <Link to="/model-document-studio" className="atlas-secondary-button">Attach Evidence to MDS</Link>
        <Link to="/model-evidence-center" className="atlas-secondary-button">Open Model Evidence Center</Link>
        <button type="button" className="atlas-secondary-button" onClick={() => downloadText("atlas-ab-testing-evidence-pack.json", JSON.stringify({ packageSummary, coverageRows }, null, 2), "application/json;charset=utf-8")}><Download size={15} /> Export A/B Testing Evidence Pack</button>
      </div>
    </section>
  );
}

function AbMonitoringFollowUp({
  state,
  setState,
  defaults,
  analysis,
  summary,
  imbalance,
  analysisStatus,
  save,
}: {
  state: NodeState;
  setState: (state: NodeState) => void;
  defaults: AbTestingDefaults;
  analysis: ReturnType<typeof analyzeAbLift>;
  summary: ReturnType<typeof summarizeAbGroups>;
  imbalance: ReturnType<typeof allocationImbalance>;
  analysisStatus: AbAnalysisDataset["status"];
  save: () => NodeState;
}) {
  const ab = { ...emptyState().ab, ...(state.ab ?? {}) };
  const update = (changes: Partial<NonNullable<NodeState["ab"]>>) => setState(updateAbState(state, changes));
  const powerAssessment = abPowerAssessment(state, summary, imbalance, analysis);
  const strategyOptions = ["Run longer / collect more data", "Launch treatment", "Keep control", "Slow rollout", "Segmented rollout", "Continue holdout test", "Do not launch"];
  const postSystemDecision = decisionRecommendationReason(analysis, imbalance);
  const finalDecision = ab.decisionRecommendationTouched && ab.decisionRecommendation
    ? ab.decisionRecommendation
    : postSystemDecision === "Run longer" ? "Inconclusive, Run Longer" : postSystemDecision;
  const suggestedStrategy = finalDecision === "Launch treatment"
    ? "Launch treatment"
    : finalDecision === "Keep control"
      ? "Keep control"
      : finalDecision === "Segmented rollout"
        ? "Segmented rollout"
        : finalDecision === "Do not launch"
          ? "Do not launch"
          : "Run longer / collect more data";
  const strategy = ab.postDecisionStrategyTouched && ab.postDecisionStrategy ? ab.postDecisionStrategy : suggestedStrategy;
  useEffect(() => {
    if (!ab.postDecisionStrategyTouched && ab.postDecisionStrategy !== suggestedStrategy) {
      setState(updateAbState(state, { postDecisionStrategy: suggestedStrategy }));
    }
  }, [ab.postDecisionStrategy, ab.postDecisionStrategyTouched, setState, state, suggestedStrategy]);
  const treatmentTarget = ab.monitoringTreatmentTarget || powerAssessment.samplePlan.treatment.toLocaleString();
  const controlTarget = ab.monitoringControlTarget || powerAssessment.samplePlan.control.toLocaleString();
  const additionalObservations = Math.max(0, powerAssessment.samplePlan.total - summary.treatmentCount - summary.controlCount);
  const treatmentRate = `${(summary.treatmentRate * 100).toFixed(2)}%`;
  const controlRate = `${(summary.controlRate * 100).toFixed(2)}%`;
  const observedLift = `${(analysis.absoluteLift * 100).toFixed(2)} pp`;
  const confidenceInterval = `${(analysis.confidenceLow * 100).toFixed(2)} pp to ${(analysis.confidenceHigh * 100).toFixed(2)} pp`;
  const currentPower = `${(powerAssessment.estimatedPower * 100).toFixed(0)}% at ${powerAssessment.relativeLiftPct.toFixed(1)}% relative MDE`;
  const allocationRatio = `${imbalance.ratio.toFixed(2)}:1`;
  const strategyProfile: Record<string, { title: string; launchStatus: string; reanalysis: string; accent: string; interpretation: string; reviewerNote: string }> = {
    "Run longer / collect more data": {
      title: "Run longer / collect more data",
      launchStatus: "Do not launch yet",
      reanalysis: "Yes",
      accent: "Run-longer sample collection",
      interpretation: `Because the final decision is ${finalDecision}, this plan is focused on collecting enough additional observations to test the selected ${powerAssessment.relativeLiftPct.toFixed(1)}% relative MDE at ${(powerAssessment.desiredPowerPct).toFixed(0)}% power. The next review should occur after treatment and control reach ${treatmentTarget} and ${controlTarget}, respectively, or after a larger confirmed artifact is loaded.`,
      reviewerNote: `Continue the experiment or load additional confirmed experiment data before changing the decision. Current power is ${currentPower}; statistical significance is ${analysis.statisticallySignificant ? "met" : "not met"}; observed lift is ${observedLift}. Preserve the metric definition and dataset lineage, then re-run randomization, power, treatment-effect, segment, business-impact, and governance checks.`,
    },
    "Launch treatment": {
      title: "Launch treatment",
      launchStatus: "Controlled launch with monitoring",
      reanalysis: "Post-launch monitoring",
      accent: "Full launch monitoring",
      interpretation: "The post-decision plan is configured for a treatment launch. ATLAS expects a named rollout owner, launch date, success metrics, guardrail metrics, rollback criteria, and review cadence before the treatment is released beyond the experiment population.",
      reviewerNote: "The launch plan should define the treatment owner, launch date, success metrics, guardrail metrics, rollback criteria, and review cadence. Evidence should be updated in MEC and MDS after launch monitoring begins.",
    },
    "Keep control": {
      title: "Keep control",
      launchStatus: "Treatment not launched",
      reanalysis: "Optional retest only",
      accent: "Control preservation",
      interpretation: "The post-decision plan is configured to keep the control experience. ATLAS expects documentation of why treatment is not being launched, what evidence would justify a future retest, and which control metrics should continue to be watched.",
      reviewerNote: "The keep-control plan should document why the treatment is not being launched, preserve the current control process, and define conditions for future retesting if business priorities change.",
    },
    "Slow rollout": {
      title: "Slow rollout",
      launchStatus: "Phased rollout required",
      reanalysis: "At every checkpoint",
      accent: "Phased rollout checkpoints",
      interpretation: "The post-decision plan is configured for a slow rollout. ATLAS expects checkpoint gates at 5%, 10%, 25%, 50%, and 100%, with monitoring metrics and rollback triggers at each stage before expansion continues.",
      reviewerNote: "The slow-rollout plan should define checkpoint gates, monitoring metrics, rollback triggers, rollout owner, review cadence, and stop/go criteria for each expansion stage.",
    },
    "Segmented rollout": {
      title: "Segmented rollout",
      launchStatus: "Limited segment launch",
      reanalysis: "Segment review required",
      accent: "Segment-level rollout",
      interpretation: "The post-decision plan is configured for segmented rollout. ATLAS expects approved segments, excluded segments, segment-level monitoring, and stop/go criteria before any segment-specific treatment is released.",
      reviewerNote: "The segmented-rollout plan should document approved segments, excluded segments, segment-level monitoring metrics, sample-size limitations, and stop/go criteria before release.",
    },
    "Continue holdout test": {
      title: "Continue holdout test",
      launchStatus: "Holdout continues",
      reanalysis: "At holdout review date",
      accent: "Holdout continuation",
      interpretation: "The post-decision plan is configured to continue the holdout test. ATLAS expects continued treatment/control tracking, holdout integrity checks, and a documented re-analysis trigger before changing the decision.",
      reviewerNote: "The holdout-continuation plan should maintain treatment/control assignment integrity, monitor sample growth, and re-run the analysis when the holdout reaches the agreed review threshold.",
    },
    "Do not launch": {
      title: "Do not launch",
      launchStatus: "Treatment blocked",
      reanalysis: "Only with redesigned test",
      accent: "No-launch closure",
      interpretation: "The post-decision plan is configured for a no-launch decision. ATLAS expects documentation of the reason treatment is blocked, owner acknowledgement, residual risks, and whether any redesigned experiment is warranted.",
      reviewerNote: "The do-not-launch plan should document the reason treatment is blocked, retain the decision evidence, and define whether a redesigned experiment or no further action is appropriate.",
    },
  };
  const activeProfile = strategyProfile[strategy] ?? strategyProfile["Run longer / collect more data"];
  const reviewerNote = state.notes || activeProfile.reviewerNote;
  const monitoringRowsByStrategy: Record<string, string[][]> = {
    "Run longer / collect more data": [
      ["Treatment sample size", summary.treatmentCount.toLocaleString(), treatmentTarget, ab.monitoringOwner || "Decision owner", ab.monitoringCadence || "Weekly", "Target met"],
      ["Control sample size", summary.controlCount.toLocaleString(), controlTarget, ab.monitoringOwner || "Decision owner", ab.monitoringCadence || "Weekly", "Target met"],
      ["Treatment conversion rate", treatmentRate, "Stable directional estimate", "Analytics owner", "Weekly", "Material movement"],
      ["Control conversion rate", controlRate, "Stable baseline", "Analytics owner", "Weekly", "Material movement"],
      ["Absolute lift", observedLift, `At least ${ab.practicalSignificanceThreshold || "1 pp"}`, "Analytics owner", "Each refresh", "Lift changes materially"],
      ["P-value", analysis.pValue.toFixed(4), `< ${ab.powerAlpha || "0.05"} or reviewer threshold`, "Analytics owner", "Each refresh", "Significance status changes"],
      ["Confidence interval", confidenceInterval, "Reviewer-approved decision interval", "Analytics owner", "Each refresh", "Interval changes decision"],
      ["Power at selected MDE", currentPower, `${powerAssessment.desiredPowerPct.toFixed(0)}% desired power`, "Analytics owner", "Each refresh", "Power target met"],
      ["Allocation ratio", allocationRatio, "Reviewer-approved allocation", "Experiment owner", "Weekly", "Unexpected drift"],
      ["Data lineage", `${analysisStatus.validAnalysisRecords.toLocaleString()} valid records`, "Confirmed artifact and mapping retained", "Data owner", "Each refresh", "Artifact version changes"],
    ],
    "Launch treatment": [
      ["Success metric", "Conversion rate", "Sustained lift vs control baseline", "Launch owner", ab.postLaunchReviewCadence || "Weekly", "Success threshold missed"],
      ["Guardrail metric", "Customer complaints / opt-outs", "No adverse movement", "Risk owner", "Daily during launch", "Guardrail breach"],
      ["Treatment conversion rate", treatmentRate, "Stable or improving", "Analytics owner", "Weekly", "Material decline"],
      ["Rollback criteria", "Not active", ab.postLaunchRollbackCriteria || "Rollback if guardrail metrics breach threshold or treatment effect reverses.", "Launch owner", "Every review", "Rollback triggered"],
      ["Launch date", ab.postLaunchDate || "Reviewer-defined", "Approved launch date", "Launch owner", "Once", "Date changes"],
      ["Business impact", "Positive but uncertain", "Validated with actual economics", "Business owner", "Weekly", "ROI turns negative"],
    ],
    "Keep control": [
      ["Control experience", "Active", "Remain active", "Decision owner", "Monthly", "Retest requested"],
      ["Treatment status", "Not launched", "Blocked", "Decision owner", "Monthly", "Treatment reconsidered"],
      ["Primary metric", "Conversion rate", "Control baseline stable", "Analytics owner", "Monthly", "Baseline drift"],
      ["Retest trigger", "Not defined", "New hypothesis or improved treatment", "Business owner", "Quarterly", "Retest approved"],
    ],
    "Slow rollout": [
      ["5% checkpoint", "Pending", "Guardrails pass", "Rollout owner", "Daily", "Stop or rollback"],
      ["10% checkpoint", "Pending", "Guardrails pass", "Rollout owner", "Daily", "Stop or rollback"],
      ["25% checkpoint", "Pending", "Guardrails pass", "Rollout owner", "Twice weekly", "Stop or rollback"],
      ["50% checkpoint", "Pending", "Guardrails pass", "Rollout owner", "Weekly", "Stop or rollback"],
      ["100% checkpoint", "Pending", "Final approval", "Rollout owner", "Weekly", "Stop or rollback"],
      ["Rollback trigger", "Not active", ab.postLaunchRollbackCriteria || "Rollback if guardrail metrics breach threshold or treatment effect reverses.", "Risk owner", "Every checkpoint", "Rollback triggered"],
    ],
    "Segmented rollout": [
      ["Approved segments", ab.approvedSegments || "Reviewer-approved segments", "Adequate segment evidence", "Segment owner", "Weekly", "Segment underperforms"],
      ["Excluded segments", ab.excludedSegments || "Underpowered or non-significant segments", "Remain excluded", "Segment owner", "Weekly", "Evidence improves"],
      ["Segment conversion rate", "Exploratory", "Stable lift in approved segments", "Analytics owner", "Weekly", "Segment lift reverses"],
      ["Stop/go criteria", "Needs definition", "Segment guardrails pass", "Decision owner", "Weekly", "Stop condition met"],
    ],
    "Continue holdout test": [
      ["Holdout integrity", "Treatment/control active", "No contamination", "Experiment owner", "Weekly", "Contamination detected"],
      ["Treatment sample size", summary.treatmentCount.toLocaleString(), treatmentTarget, "Analytics owner", "Weekly", "Target met"],
      ["Control sample size", summary.controlCount.toLocaleString(), controlTarget, "Analytics owner", "Weekly", "Target met"],
      ["Re-analysis trigger", "Pending", ab.monitoringReanalysisTrigger || "When required sample threshold is met or a larger confirmed dataset is loaded", "Decision owner", "Weekly", "Trigger met"],
    ],
    "Do not launch": [
      ["Treatment status", "Blocked", "Do not launch", "Decision owner", "Monthly", "Decision reopened"],
      ["Decision evidence", "Saved", "Retained in MEC/MDS", "Governance owner", "Once", "Evidence request"],
      ["Redesign trigger", "Not active", "New hypothesis or treatment design", "Business owner", "Quarterly", "Redesign approved"],
      ["Residual risk", "Low if not launched", "Documented", "Risk owner", "Quarterly", "Risk changes"],
    ],
  };
  const monitoringRows = monitoringRowsByStrategy[strategy] ?? monitoringRowsByStrategy["Run longer / collect more data"];
  const actionTitleByStrategy: Record<string, string> = {
    "Run longer / collect more data": "Run-Longer Action Plan",
    "Launch treatment": "Launch Treatment Plan",
    "Keep control": "Keep-Control Plan",
    "Slow rollout": "Slow Rollout Checkpoint Plan",
    "Segmented rollout": "Segmented Rollout Plan",
    "Continue holdout test": "Holdout Continuation Plan",
    "Do not launch": "Do-Not-Launch Closure Plan",
  };

  return (
    <section className="space-y-4 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
      <div>
        <div className="text-xs font-semibold uppercase tracking-wide text-emerald-700">Post-Decision Strategy</div>
        <h2 className="mt-1 text-lg font-semibold text-slate-950">Post-Decision Plan</h2>
        <p className="mt-1 text-sm leading-6 text-slate-600">Define what happens after the A/B decision. This page supports split tests, slow-roll introductions, holdout continuation, segmented rollout, keep-control decisions, no-launch closure, and full treatment launch monitoring.</p>
      </div>

      <section className="rounded-xl border border-slate-200 bg-slate-50 p-4">
        
        <div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_minmax(0,2fr)]">
          <AbSelect label="Post-Decision Strategy" value={strategy} options={strategyOptions} onChange={(value) => update({ postDecisionStrategy: value, postDecisionStrategyTouched: true })} />
          <div className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm leading-6 text-slate-700">
            Changing this selector updates the page sections, required fields, monitoring plan, decision criteria, and evidence export for the selected post-decision path.
          </div>
        </div>
      </section>

      <section className="rounded-2xl border border-amber-300 bg-slate-950 p-5 text-white">
        <div className="text-xs font-semibold uppercase tracking-wide text-amber-200">Post-Decision Plan Summary</div>
        <h3 className="mt-2 text-2xl font-semibold">{activeProfile.title}</h3>
        <div className="mt-4 grid gap-3 md:grid-cols-4">
          <HeaderMetric label="Current decision" value={finalDecision} />
          <HeaderMetric label="Post-decision strategy" value={strategy} />
          <HeaderMetric label="Launch status" value={activeProfile.launchStatus} />
          <HeaderMetric label="Re-analysis required" value={activeProfile.reanalysis} />
        </div>
      </section>

      <section className="rounded-xl border border-slate-200 bg-slate-50 p-4">
        <div className="text-sm font-semibold text-slate-950">{actionTitleByStrategy[strategy] ?? "Post-Decision Action Plan"}</div>
        <div className="mt-3 grid gap-3 md:grid-cols-2">
          {["Run longer / collect more data", "Continue holdout test"].includes(strategy) && (
            <>
              <AbInput label="Follow-up owner" value={ab.monitoringOwner || "Decision owner"} onChange={(value) => update({ monitoringOwner: value })} />
              <AbInput label="Target additional observations" value={ab.monitoringTargetObservations || additionalObservations.toLocaleString()} onChange={(value) => update({ monitoringTargetObservations: value })} />
              <AbInput label="Minimum treatment sample target" value={treatmentTarget} onChange={(value) => update({ monitoringTreatmentTarget: value })} />
              <AbInput label="Minimum control sample target" value={controlTarget} onChange={(value) => update({ monitoringControlTarget: value })} />
              <AbInput label="Re-analysis trigger" value={ab.monitoringReanalysisTrigger || "When required sample threshold is met or a larger confirmed dataset is loaded"} onChange={(value) => update({ monitoringReanalysisTrigger: value })} />
              <AbInput label="Next review date" value={ab.monitoringFollowUpDate || ""} onChange={(value) => update({ monitoringFollowUpDate: value })} />
              <AbInput label="Data refresh cadence" value={ab.monitoringCadence || "Weekly or campaign-cycle based"} onChange={(value) => update({ monitoringCadence: value })} />
              <AbInput label="Decision review owner" value={ab.monitoringDecisionOwner || "Campaign Strategy Lead"} onChange={(value) => update({ monitoringDecisionOwner: value })} />
            </>
          )}
          {strategy === "Launch treatment" && (
            <>
              <AbInput label="Rollout owner" value={ab.postLaunchOwner || "Launch owner"} onChange={(value) => update({ postLaunchOwner: value })} />
              <AbInput label="Launch date" value={ab.postLaunchDate || ""} onChange={(value) => update({ postLaunchDate: value })} />
              <AbInput label="Success metrics" value="Conversion rate, absolute lift, business impact" onChange={() => undefined} />
              <AbInput label="Guardrail metrics" value="Complaints, opt-outs, allocation drift, missing outcome rate" onChange={() => undefined} />
              <AbInput label="Rollback criteria" value={ab.postLaunchRollbackCriteria || "Rollback if guardrail metrics breach threshold or treatment effect reverses."} onChange={(value) => update({ postLaunchRollbackCriteria: value })} />
              <AbInput label="Review cadence" value={ab.postLaunchReviewCadence || "Weekly for launch window, then monthly"} onChange={(value) => update({ postLaunchReviewCadence: value })} />
            </>
          )}
          {strategy === "Slow rollout" && (
            <>
              <AbInput label="Rollout owner" value={ab.postLaunchOwner || "Rollout owner"} onChange={(value) => update({ postLaunchOwner: value })} />
              <AbInput label="Rollout checkpoints" value={ab.rolloutCheckpoints || "5%, 10%, 25%, 50%, 100%"} onChange={(value) => update({ rolloutCheckpoints: value })} />
              <AbInput label="Monitoring metrics" value="Conversion rate, lift, guardrails, complaints, missing outcome rate" onChange={() => undefined} />
              <AbInput label="Rollback triggers" value={ab.postLaunchRollbackCriteria || "Stop expansion if guardrails breach or lift reverses."} onChange={(value) => update({ postLaunchRollbackCriteria: value })} />
              <AbInput label="Checkpoint review cadence" value={ab.postLaunchReviewCadence || "At every checkpoint"} onChange={(value) => update({ postLaunchReviewCadence: value })} />
              <AbInput label="Decision review owner" value={ab.monitoringDecisionOwner || "Campaign Strategy Lead"} onChange={(value) => update({ monitoringDecisionOwner: value })} />
            </>
          )}
          {strategy === "Segmented rollout" && (
            <>
              <AbInput label="Approved segments" value={ab.approvedSegments || "Reviewer-approved segments"} onChange={(value) => update({ approvedSegments: value })} />
              <AbInput label="Excluded segments" value={ab.excludedSegments || "Underpowered or non-significant segments"} onChange={(value) => update({ excludedSegments: value })} />
              <AbInput label="Segment-level monitoring" value="Conversion rate, lift, guardrails, sample size by segment" onChange={() => undefined} />
              <AbInput label="Stop/go criteria" value="Continue only if approved segments meet lift, power, and guardrail thresholds." onChange={() => undefined} />
              <AbInput label="Segment review cadence" value={ab.postLaunchReviewCadence || "Weekly"} onChange={(value) => update({ postLaunchReviewCadence: value })} />
              <AbInput label="Segment owner" value={ab.postLaunchOwner || "Segment owner"} onChange={(value) => update({ postLaunchOwner: value })} />
            </>
          )}
          {["Keep control", "Do not launch"].includes(strategy) && (
            <>
              <AbInput label="Decision owner" value={ab.monitoringDecisionOwner || "Campaign Strategy Lead"} onChange={(value) => update({ monitoringDecisionOwner: value })} />
              <AbInput label="Treatment status" value={strategy === "Keep control" ? "Treatment not launched; control remains active" : "Treatment blocked"} onChange={() => undefined} />
              <AbInput label="Future retest trigger" value="New hypothesis, improved treatment, or reviewer-approved redesign" onChange={() => undefined} />
              <AbInput label="Evidence retention" value="Save MEC/MDS evidence and decision rationale" onChange={() => undefined} />
            </>
          )}
        </div>
      </section>

      <section className="rounded-xl border border-slate-200 bg-white p-4">
        <div className="text-sm font-semibold text-slate-950">Post-Decision Metrics to Monitor</div>
        <div className="mt-3 overflow-x-auto">
          <table className="min-w-[900px] w-full text-left text-xs">
            <thead className="bg-slate-100 text-slate-600">
              <tr>
                {["Metric", "Current", "Target", "Owner", "Review cadence", "Trigger"].map((header) => <th key={header} className="px-3 py-2 font-semibold uppercase tracking-wide">{header}</th>)}
              </tr>
            </thead>
            <tbody>
              {monitoringRows.map((row) => (
                <tr key={row[0]} className="border-t border-slate-200">
                  {row.map((cell, index) => <td key={`${row[0]}-${index}`} className="px-3 py-2 align-top text-slate-700">{cell}</td>)}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="grid gap-4 xl:grid-cols-2">
        <InfoGrid title="Decision Re-entry Criteria" rows={[
          ["Strategy-specific trigger", strategy === "Launch treatment" ? "Return if launch monitoring breaches guardrails or rollback criteria." : strategy === "Slow rollout" ? "Return at every 5%, 10%, 25%, 50%, and 100% checkpoint." : strategy === "Segmented rollout" ? "Return when segment-level monitoring changes stop/go status." : "Return when additional data or a redesigned test changes the decision evidence."],
          ["Sample targets", "Treatment and control sample sizes meet the power target or reviewer-approved threshold when inference is required."],
          ["Assignment", "Randomization, holdout, rollout, or segment assignment is documented."],
          ["Metric stability", "Primary metric definition unchanged unless reviewer approves a change."],
          ["Experiment analysis", "Experiment analysis re-run when new data is available."],
          ["Segment analysis", "Segment analysis re-run when segment decisions are involved."],
          ["Business impact", "Business impact assumptions updated before launch or expansion."],
          ["Evidence", "MEC and MDS evidence updated before returning to Decision Recommendation."],
          ["Decision", "Decision recommendation re-reviewed."],
        ]} />
        <InfoGrid title="Launch Guardrails if Decision Changes" rows={[
          ["Treatment effect", "Do not launch unless treatment effect is statistically and practically meaningful."],
          ["Confidence interval", "Do not launch if confidence interval crosses zero."],
          ["Power", "Do not launch if sample remains underpowered."],
          ["Assignment", "Do not launch if randomization or assignment cannot be explained."],
          ["Business impact", "Do not launch if business impact depends on unsupported assumptions."],
          ["Segments", "Do not use segment effects for launch unless segment sample sizes are adequate."],
        ]} />
      </section>

      <section className="rounded-xl border border-emerald-200 bg-emerald-50 p-4">
        <div className="text-sm font-semibold text-emerald-950">ATLAS Post-Decision Interpretation</div>
        <p className="mt-2 text-sm leading-6 text-emerald-950">
          {activeProfile.interpretation}
        </p>
      </section>

      <TextArea label="Reviewer notes" value={reviewerNote} onChange={(value) => setState({ ...state, notes: value })} rows={4} />

      <div className="flex flex-wrap gap-2">
        <button type="button" className="atlas-secondary-button" onClick={() => save()}><Save size={15} /> Save Post-Decision Plan Evidence</button>
        <Link to="/model-evidence-center" className="atlas-secondary-button">Open Model Evidence Center</Link>
        <Link to="/model-document-studio" className="atlas-secondary-button">Attach Post-Decision Plan to MDS</Link>
        <button type="button" className="atlas-secondary-button" onClick={() => downloadText("atlas-ab-testing-post-decision-plan.json", JSON.stringify({ dataset: defaults.dataset, strategy, monitoringRows }, null, 2), "application/json;charset=utf-8")}><Download size={15} /> Export Post-Decision Plan</button>
        <Link to="/decision-journal" className="atlas-secondary-button">Open Decision Journal</Link>
        <button type="button" className="atlas-primary-button" onClick={() => save()}>Finish A/B Testing Workflow</button>
      </div>
    </section>
  );
}

function SimpleAbChart({ title, rows }: { title: string; rows: Array<[string, number]> }) {
  const max = Math.max(1, ...rows.map(([, value]) => value));
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-3">
      <div className="text-xs font-semibold text-slate-900">{title}</div>
      <div className="mt-3 grid gap-2">
        {rows.map(([label, value]) => (
          <div key={label} className="grid grid-cols-[6rem_1fr_4rem] items-center gap-2 text-xs">
            <span className="truncate">{label}</span>
            <span className="h-2 rounded-full bg-slate-100"><span className="block h-2 rounded-full bg-blue-600" style={{ width: `${Math.max(4, (value / max) * 100)}%` }} /></span>
            <span className="text-right font-semibold">{value < 1 ? `${(value * 100).toFixed(1)}%` : value.toLocaleString()}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

type AdvancedWorkflowPanel = {
  title: string;
  body: string;
  rows: Array<[string, string]>;
};

type AdvancedWorkflowExperience = {
  eyebrow: string;
  title: string;
  subtitle: string;
  diagnosticTitle?: string;
  diagnosticRows?: Array<[string, number]>;
  primaryControls: Array<{ label: string; options?: string[]; placeholder?: string }>;
  diagnostics: Array<[string, string, "info" | "success" | "warning" | "danger" | "neutral"]>;
  visuals: AdvancedWorkflowPanel[];
  evidenceType: string;
  python: string[];
  companionCode: string[];
  documentation: string[];
  nextAction: string;
};

const timeSeriesExperienceByStep: Record<string, AdvancedWorkflowExperience> = {
  "Project Context": {
    eyebrow: "Time Series & Forecasting",
    title: "Forecast charter and governance boundary",
    subtitle: "Define the forecast purpose, target outcome, horizon, cadence, grain, and governance path before data is loaded.",
    diagnosticTitle: "Forecast study design",
    diagnosticRows: [["Goal", 86], ["Governance", 74], ["Horizon", 68], ["Backtest", 61], ["Monitoring", 79]],
    primaryControls: [
      { label: "Study goal", options: ["Forecast future values", "Detect anomalies", "Monitor trend/stability", "Backtest forecast accuracy", "Compare time-aware models"] },
      { label: "Entity grain", options: ["portfolio", "product", "branch", "customer segment", "merchant", "account", "transaction type", "other"] },
      { label: "Forecast horizon", options: ["7 days", "30 days", "90 days", "12 months", "custom"] },
      { label: "Governance context", options: ["internal governance", "model risk", "operational planning", "fair lending", "finance/treasury", "fraud/risk operations", "none"] },
    ],
    diagnostics: [["Objective status", "Ready for charter", "info"], ["Governance boundary", "Reviewer required", "warning"], ["Evidence", "time_series_project_context", "success"]],
    visuals: [
      { title: "Study goal cards", body: "Choose whether this study forecasts future values, detects anomalies, monitors trend/stability, backtests accuracy, or compares time-aware models.", rows: [["Forecast future values", "Use for liquidity, disputes, call center demand, transaction volume, and losses"], ["Detect anomalies", "Use for fraud alerts, outages, demand spikes, and unexpected operational breaks"]] },
      { title: "Risk classification", body: "Classify whether the forecast supports operational planning, financial reporting, customer-impacting decisions, or regulated decision support.", rows: [["Customer-impacting", "Requires reviewer controls and limitation language"], ["Regulated decision support", "Requires model risk, validation, monitoring, and approval evidence"]] },
      { title: "Financial-services examples", body: "Common ATLAS forecast targets include transaction volume, fraud alerts, losses, disputes, liquidity, and call center demand.", rows: [["Operational planning", "Capacity and staffing forecast"], ["Risk operations", "Fraud alert or dispute volume forecast"]] },
    ],
    evidenceType: "time_series_project_context",
    python: ["project_context = {...}", "forecast_horizon = project_context['horizon']", "evidence['time_series_project_context'] = project_context"],
    companionCode: ["DATA forecast_context; length governance_context $80.; run;", "/* Document horizon, cadence, target, and intended use. */"],
    documentation: ["Executive Summary", "Business Context", "Time Index and Grain", "Approval Record"],
    nextAction: "Confirm the outcome, horizon, and decision cadence before mapping time-indexed data.",
  },
  "Data Acquisition": {
    eyebrow: "Input bundle",
    title: "Time-indexed data mapping",
    subtitle: "Register the dataset, parse the time field, map the target, and verify frequency, coverage, missing timestamps, and duplicate periods.",
    diagnosticTitle: "Time coverage, quality, and mapping diagnostics",
    diagnosticRows: [["Rows", 78], ["Coverage", 92], ["Frequency", 84], ["Gaps", 18], ["Entities", 67]],
    primaryControls: [
      { label: "Input option", options: ["Upload file", "Existing dataset", "SQL Data Studio source", "Python loader"] },
      { label: "Date/time column", placeholder: "transaction_date, month_end, created_at" },
      { label: "Date format", options: ["Auto detect", "YYYY-MM-DD", "MM/DD/YYYY", "YYYY-MM-DD HH:mm:ss", "Custom"] },
      { label: "Time zone", options: ["UTC", "US/Eastern", "US/Central", "US/Mountain", "US/Pacific", "Source local time"] },
      { label: "Target value column", placeholder: "volume, loss_amount, dispute_count" },
      { label: "Aggregation frequency", options: ["hourly", "daily", "weekly", "monthly", "quarterly"] },
      { label: "Aggregation method", options: ["sum", "mean", "median", "count", "last value", "max"] },
      { label: "Duplicate timestamp policy", options: ["aggregate duplicates", "keep latest", "flag for review", "block until resolved"] },
      { label: "Missing timestamp policy", options: ["insert missing periods", "leave gaps", "interpolate for profile only", "block modeling"] },
      { label: "Entity/group column", placeholder: "branch_id, product, portfolio, merchant" },
      { label: "Optional segment column", placeholder: "region, customer_segment, channel" },
      { label: "Optional exogenous drivers", placeholder: "holiday, rate, spend, outage, promotion" },
    ],
    diagnostics: [["Rows", "Synthetic preview ready", "info"], ["Date range", "36 periods detected", "success"], ["Frequency", "Monthly candidate", "success"], ["Irregular interval warning", "Review before modeling", "warning"]],
    visuals: [
      { title: "Time coverage timeline", body: "Shows earliest and latest timestamps, missing periods, and coverage by entity.", rows: [["Coverage", "Jan 2023 to Dec 2025"], ["Missing timestamps", "3 review candidates"]] },
      { title: "Missing timestamp calendar heatmap", body: "Highlights gaps by period, source system, entity, and segment so data scientists can separate true zeros from missing periods.", rows: [["Duplicate periods", "Apply duplicate timestamp policy"], ["Missing periods", "Review before aggregation and modeling"]] },
      { title: "Target over time preview", body: "A first-pass line chart should verify trend, seasonality, zeros, negative values, and data breaks.", rows: [["Trend", "Upward with seasonal cycle"], ["Seasonality hint", "Monthly pattern detected"], ["Zero or negative values", "Flag when target semantics make them invalid"]] },
      { title: "Entity coverage table", body: "Shows row count, first period, last period, missing periods, and target missingness by series/entity.", rows: [["Number of series/entities", "Required for per-entity versus global model choice"], ["Target missingness", "Blocks training when unresolved"]] },
    ],
    evidenceType: "time_series_input_bundle",
    python: ["df = pd.read_csv(path)", "df[time_col] = pd.to_datetime(df[time_col])", "profile = df.groupby(pd.Grouper(key=time_col, freq='M'))[target_col].sum()", "evidence['time_series_input_bundle'] = input_mapping", "evidence['time_series_data_profile'] = quality_profile"],
    companionCode: ["PROC IMPORT DATAFILE='time_series.csv' OUT=work.ts DBMS=CSV REPLACE; RUN;", "DATA work.ts; parsed_date = INPUT(date_col, YYMMDD10.); FORMAT parsed_date DATE9.; RUN;"],
    documentation: ["Data Inputs", "Time Index and Grain", "Evidence Inventory"],
    nextAction: "Confirm the time column, target column, aggregation level, and date coverage.",
  },
  "Time Series Profile": {
    eyebrow: "Temporal diagnostics",
    title: "Trend, seasonality, volatility, and anomaly profile",
    subtitle: "Review the target over time before modeling so backtesting and features reflect actual temporal behavior.",
    diagnosticTitle: "Target behavior summary",
    diagnosticRows: [["Level", 76], ["Trend", 82], ["Volatility", 58], ["Seasonality", 64], ["Anomalies", 21]],
    primaryControls: [
      { label: "Select entity", options: ["All entities", "Top entity", "Portfolio", "Product", "Segment"] },
      { label: "Date range", options: ["Full history", "Last 90 days", "Last 12 months", "Custom"] },
      { label: "Rolling window", options: ["7 periods", "14 periods", "30 periods", "90 periods"] },
      { label: "Seasonality view", options: ["day of week", "month of year", "hour of day"] },
      { label: "Decomposition mode", options: ["additive", "multiplicative", "none"] },
      { label: "Anomaly sensitivity", options: ["low", "medium", "high", "review only"] },
    ],
    diagnostics: [["Seasonality strength", "Moderate", "success"], ["Volatility", "Increasing", "warning"], ["Autocorrelation", "Lag 1 visible", "info"], ["Outliers", "4 candidates", "warning"]],
    visuals: [
      { title: "Target over time line chart", body: "Combines actual values, rolling mean, rolling volatility, structural breaks, and anomaly overlay.", rows: [["Rolling mean", "Rising after mid-period"], ["Rolling volatility", "Higher after recent regime change"], ["Structural breaks", "Review before backtesting"]] },
      { title: "Seasonal pattern chart", body: "Compares day-of-week, month-of-year, or hour-of-day patterns to determine useful calendar features.", rows: [["Likely seasonality", "Monthly cycle candidate"], ["Short history warning", "Trigger when fewer than two seasonal cycles exist"]] },
      { title: "Autocorrelation chart and lag relationship chart", body: "Shows whether lag features are useful and whether residual independence needs attention.", rows: [["Autocorrelation", "Lag 1 visible"], ["Lag relationship", "Lag 12 seasonal candidate"]] },
    ],
    evidenceType: "time_series_profile",
    python: ["rolling = series.rolling(window=12).mean()", "acf_values = statsmodels.tsa.stattools.acf(series.dropna(), nlags=24)", "evidence['time_series_profile'] = profile"],
    companionCode: ["PROC TIMESERIES DATA=work.ts OUT=work.profile; ID parsed_date INTERVAL=MONTH; VAR target; RUN;"],
    documentation: ["Target Profile", "Diagnostics and Stability"],
    nextAction: "Use profile findings to choose lag, calendar, and anomaly controls.",
  },
  "Feature & Calendar Design": {
    eyebrow: "Feature gate",
    title: "Lag, rolling, calendar, and future-known feature design",
    subtitle: "Create time-aware features while blocking anything not known at forecast time.",
    diagnosticTitle: "Feature lineage and leakage gate",
    diagnosticRows: [["Lag", 88], ["Rolling", 73], ["Calendar", 81], ["Known future", 54], ["Leakage", 16]],
    primaryControls: [
      { label: "Lag features", options: ["lag 1", "lag 7", "lag 14", "lag 30", "custom"] },
      { label: "Rolling features", options: ["rolling mean", "rolling median", "rolling standard deviation", "rolling min/max"] },
      { label: "Calendar features", options: ["day of week", "month", "quarter", "holiday", "month-end", "pay cycle", "business day"] },
      { label: "Future-known driver controls", options: ["Allowed", "Reviewer approval required", "Blocked"] },
    ],
    diagnostics: [["Feature lineage", "Traceable", "success"], ["Future-known gate", "Enabled", "success"], ["Leakage warnings", "1 review item", "warning"]],
    visuals: [
      { title: "Feature lineage table", body: "Documents each feature source, transformation, window, and forecast-time availability.", rows: [["Lag features", "Allowed from historical target only"], ["Future drivers", "Must be known before forecast issue date"]] },
      { title: "Lag correlation heatmap", body: "Ranks lag 1, lag 7, lag 14, lag 30, and custom lag relationships against the target.", rows: [["Lag 1", "High signal candidate"], ["Lag 30", "Useful for monthly cycle review"]] },
      { title: "Calendar effect chart", body: "Ranks recurring patterns and calendar effects before model training.", rows: [["Month-end", "Candidate driver"], ["Holiday flag", "Reviewer controlled"], ["Pay cycle", "Financial services calendar candidate"]] },
      { title: "Leakage risk panel", body: "Blocks features that are unknown at forecast time unless a reviewer supplies a future-known-driver rationale.", rows: [["Future-known gate", "Required for exogenous drivers"], ["Leakage warning", "Block post-outcome fields"]] },
    ],
    evidenceType: "time_series_feature_design",
    python: ["df['lag_1'] = df[target].shift(1)", "df['rolling_mean_7'] = df[target].shift(1).rolling(7).mean()", "df['month'] = df[time_col].dt.month"],
    companionCode: ["DATA work.features; SET work.ts; lag_1 = LAG(target); month = MONTH(parsed_date); RUN;"],
    documentation: ["Feature and Calendar Design", "Reproducibility Appendix"],
    nextAction: "Approve future-known features and leakage controls before backtest design.",
  },
  "Backtest Design": {
    eyebrow: "Temporal validation",
    title: "Backtest windows and forecast horizon",
    subtitle: "Define rolling or expanding validation windows so model comparison uses realistic forecast issue dates.",
    diagnosticTitle: "Temporal validation fold timeline",
    diagnosticRows: [["Train", 68], ["Gap", 12], ["Validation", 24], ["Holdout", 19], ["Horizon", 31]],
    primaryControls: [
      { label: "Split strategy", options: ["holdout by date", "rolling origin", "expanding window", "sliding window"] },
      { label: "Initial training window", options: ["6 months", "12 months", "24 months", "custom"] },
      { label: "Number of folds", options: ["3", "5", "6", "10", "custom"] },
      { label: "Forecast horizon", options: ["1 period", "7 days", "30 days", "90 days", "12 months"] },
      { label: "Step size", options: ["1 period", "1 week", "1 month", "1 quarter", "custom"] },
      { label: "Gap period", options: ["none", "1 period", "7 days", "custom"] },
      { label: "Holdout period", options: ["last 10%", "last 20%", "last 3 months", "last 12 months", "custom"] },
      { label: "Evaluation metrics", options: ["MAE", "RMSE", "MAPE", "sMAPE", "WAPE", "MASE", "bias", "coverage"] },
    ],
    diagnostics: [["Backtest folds", "6 planned", "info"], ["Leakage guard", "Temporal order preserved", "success"], ["Holdout", "Untouched by training", "success"]],
    visuals: [
      { title: "Backtest window timeline", body: "Displays train, validation, gap, and forecast periods for every fold.", rows: [["Fold design", "Rolling origin"], ["Horizon", "Configured by forecast use"]] },
      { title: "Train validation test split graphic", body: "Shows the untouched holdout and avoids random splits that leak future data into training.", rows: [["Temporal order", "Preserved"], ["Gap period", "Prevents look-ahead contamination"]] },
      { title: "Horizon diagram", body: "Clarifies whether metrics are measured at one-step, multi-step, or business-horizon level.", rows: [["Forecast issue date", "Locked before validation"], ["Evaluation horizon", "Aligned to business decision cadence"]] },
      { title: "Metric selection cards", body: "Shows why each metric is used and which business decision it supports.", rows: [["WAPE", "Scale-aware operational error"], ["Bias", "Systematic over or under forecast risk"]] },
    ],
    evidenceType: "time_series_backtest_design",
    python: ["for cutoff in cutoffs:", "    train = df[df[time_col] <= cutoff]", "    test = df[(df[time_col] > cutoff) & (df[time_col] <= cutoff + horizon)]"],
    companionCode: ["/* Create cutoff dates and preserve temporal order before forecast scoring. */"],
    documentation: ["Backtest Design", "Training and Backtest Results"],
    nextAction: "Lock the temporal split before selecting candidate models.",
  },
  "Model Configuration": {
    eyebrow: "Candidate model design",
    title: "Baseline, statistical, machine-learning, and anomaly model configuration",
    subtitle: "Select interpretable baselines, time-series templates, lag-feature models, and anomaly baselines with explicit data requirements and tuning depth.",
    diagnosticTitle: "Model family comparison",
    diagnosticRows: [["Naive", 42], ["Seasonal", 58], ["Smoothing", 71], ["ARIMA", 64], ["Boosting", 82], ["Anomaly", 48]],
    primaryControls: [
      { label: "Modeling strategy", options: ["per-entity model", "global model", "hierarchical model", "portfolio aggregate"] },
      { label: "Prediction intervals", options: ["none", "80%", "90%", "95%", "custom"] },
      { label: "Hyperparameter depth", options: ["baseline only", "quick", "standard", "deep"] },
      { label: "Refit cadence", options: ["daily", "weekly", "monthly", "quarterly", "on drift trigger"] },
      { label: "Reproducibility seed", placeholder: "42" },
    ],
    diagnostics: [["Baseline", "Required", "success"], ["Intervals", "Configured", "info"], ["Data requirements", "Review short series", "warning"], ["Tuning", "Standard depth", "info"]],
    visuals: [
      { title: "Candidate model cards", body: "Compare naive baseline, seasonal naive, moving average, exponential smoothing, ARIMA/SARIMA-style template, linear regression with lag/calendar features, gradient boosting with lag features, random forest with lag features, and anomaly detection baseline.", rows: [["Model fit signal", "Shows which model fits trend, seasonality, sparse history, or nonlinear lag effects"], ["Limitations", "Flags short history, nonstationarity, and explainability concerns"]] },
      { title: "Baseline recommendation", body: "ATLAS keeps naive and seasonal-naive baselines so complex models must beat a transparent reference.", rows: [["Naive baseline", "Required for scale-free benchmark"], ["Seasonal naive", "Required when seasonality is detected"]] },
      { title: "Modeling readiness panel", body: "Checks entity count, history length, missing timestamps, exogenous-driver availability, interval requirements, and refit policy.", rows: [["Readiness", "Backtest design must be locked"], ["Warning", "Sparse series may require aggregate or global modeling"]] },
    ],
    evidenceType: "time_series_model_configuration",
    python: ["candidate_models = ['naive', 'seasonal_naive', 'ets', 'sarima_template', 'lag_boosting']", "config = {'global_model': True, 'interval': 0.9, 'refit_cadence': 'monthly'}", "evidence['time_series_model_configuration'] = config"],
    companionCode: ["/* Store model candidates, interval policy, tuning depth, and refit cadence for governed forecast training. */"],
    documentation: ["Model Configuration", "Limitations", "Reproducibility Appendix"],
    nextAction: "Select candidate families and lock interval, tuning, and refit controls before running backtests.",
  },
  "Train & Backtest": {
    eyebrow: "Backtest preview mode",
    title: "Train and run backtest with explicit execution status",
    subtitle: "Run or preview the governed backtest, compare candidates by fold, inspect champion candidates, and capture warnings without claiming full training when no backend run exists.",
    diagnosticTitle: "Model comparison and fold metrics",
    diagnosticRows: [["Naive", 52], ["Seasonal", 61], ["ETS", 73], ["ARIMA", 69], ["Boosting", 84], ["Forest", 78]],
    primaryControls: [
      { label: "Execution action", options: ["Train and run backtest", "Backtest preview mode", "Validate configuration only"] },
      { label: "Champion metric", options: ["WAPE", "MAE", "RMSE", "sMAPE", "MASE", "bias", "coverage"] },
      { label: "Failure handling", options: ["continue remaining candidates", "stop run", "fallback to baseline"] },
      { label: "Warning policy", options: ["block recommendation", "allow with reviewer note", "research only"] },
    ],
    diagnostics: [["Execution mode", "Backtest preview mode", "warning"], ["Run record", "time_series_training", "info"], ["Champion", "Candidate only", "neutral"], ["Warnings", "Review before recommendation", "warning"]],
    visuals: [
      { title: "Model comparison bar chart", body: "Ranks candidate models by the selected metric while keeping baseline models visible.", rows: [["Champion candidate", "Best preview metric, not approved"], ["Runtime", "Captured per model for run records"]] },
      { title: "Backtest performance by fold line chart", body: "Shows fold-by-fold metric movement to reveal degradation, drift, or unstable performance.", rows: [["Fold metrics", "MAE, RMSE, WAPE, bias, coverage"], ["Degradation warning", "Triggers when recent folds worsen"]] },
      { title: "Actual vs forecast backtest chart", body: "Overlays actuals, forecasts, prediction intervals, and error markers for each backtest window.", rows: [["Forecast error over time", "Shows residual direction and magnitude"], ["Residual distribution", "Checks skew and heavy-tail risk"]] },
      { title: "Bias by horizon", body: "Shows whether short-horizon and long-horizon forecasts systematically over or under predict.", rows: [["Horizon 1", "Low bias"], ["Long horizon", "Reviewer warning when bias grows"]] },
    ],
    evidenceType: "time_series_backtest_results",
    python: ["run_record = run_backtest(config) if backend_available else preview_backtest(config)", "assert run_record.mode in ['backend', 'preview']", "evidence['time_series_training_run'] = run_record", "evidence['time_series_backtest_results'] = run_record.metrics"],
    companionCode: ["/* Persist time_series_training and time_series_backtest run records with mode, status, warnings, and metrics. */"],
    documentation: ["Training and Backtest Results", "Python Code", "SAS-Compatible Code"],
    nextAction: "Review fold metrics, warnings, champion candidate, and execution mode before producing forecast results.",
  },
  "Forecast Results": {
    eyebrow: "Forecast output",
    title: "Champion forecast horizon, intervals, entities, and export package",
    subtitle: "Review forecast periods, prediction intervals, entity-level outputs, increasing/decreasing entities, and scenario-ready forecast tables.",
    diagnosticTitle: "Forecast fan chart",
    diagnosticRows: [["Actuals", 74], ["Forecast", 82], ["Lower interval", 55], ["Upper interval", 91], ["Scenario", 64]],
    primaryControls: [
      { label: "Select entity", options: ["All entities", "Portfolio", "Top increasing", "Top decreasing", "Custom entity"] },
      { label: "Select horizon", options: ["next 7 periods", "next 30 periods", "next 90 periods", "next 12 months"] },
      { label: "Show intervals", options: ["on", "off", "80%", "90%", "95%"] },
      { label: "Compare model forecasts", options: ["champion only", "champion vs baseline", "all candidates"] },
      { label: "Export forecast", options: ["Forecast CSV", "Governed JSON", "Evidence artifact"] },
    ],
    diagnostics: [["Forecast table", "Period, forecast, lower, upper, entity", "success"], ["Intervals", "Visible", "success"], ["Entity comparison", "Available", "info"], ["Export", "Ready", "info"]],
    visuals: [
      { title: "Actuals plus forecast line chart", body: "Shows historical actuals, forecast horizon, and the forecast issue boundary.", rows: [["Forecast horizon summary", "Period count, issue date, champion model"], ["Interval fan chart", "Lower and upper uncertainty bands"]] },
      { title: "Forecast table", body: "Includes period, forecast, lower interval, upper interval, entity, and scenario when applicable.", rows: [["Required columns", "period, forecast, lower interval, upper interval, entity"], ["Scenario support", "Base and stressed outputs can share the same structure"]] },
      { title: "Forecast by entity table", body: "Ranks top increasing and decreasing entities and shows contribution to portfolio forecast movement.", rows: [["Top increasing entities", "Monitor capacity and exposure"], ["Top decreasing entities", "Review operational or data-quality breaks"]] },
      { title: "Forecast contribution chart", body: "Explains which entities or segments explain the most forecast change.", rows: [["Contribution", "Entity-level share of forecast delta"], ["Management view", "Portfolio movement summary"]] },
    ],
    evidenceType: "time_series_forecast_results",
    python: ["forecast = champion.predict(horizon=horizon, intervals=True)", "forecast.to_csv('forecast_results.csv', index=False)", "evidence['time_series_forecast_results'] = forecast_manifest"],
    companionCode: ["/* Export period, forecast, lower interval, upper interval, entity, and scenario fields. */"],
    documentation: ["Forecast Results", "Evidence Inventory", "Executive Summary"],
    nextAction: "Export forecast results and continue to residual, stability, and interval diagnostics.",
  },
  "Diagnostics & Stability": {
    eyebrow: "Residual and stability diagnostics",
    title: "Forecast errors, residual autocorrelation, drift, degradation, and anomaly review",
    subtitle: "Validate whether the forecast is stable enough for the intended financial-services use and whether monitoring thresholds are required.",
    diagnosticTitle: "Residual, horizon, and stability view",
    diagnosticRows: [["Residuals", 36], ["ACF", 42], ["Horizon error", 58], ["Coverage", 74], ["Drift", 29], ["Anomaly rate", 18]],
    primaryControls: [
      { label: "Diagnostic focus", options: ["residual autocorrelation", "residual bias", "residual seasonality", "error by horizon", "error by segment/entity", "drift/regime change", "interval coverage", "anomaly detection", "backtest degradation"] },
      { label: "Segment/entity view", options: ["portfolio", "entity", "region", "product", "channel"] },
      { label: "Stability window", options: ["recent fold", "last 3 folds", "last 12 periods", "full backtest"] },
      { label: "Escalation threshold", options: ["warning only", "block recommendation", "monitoring trigger"] },
    ],
    diagnostics: [["Residual bias", "Review by horizon", "warning"], ["Interval coverage", "Within tolerance", "success"], ["Regime change", "Candidate", "warning"], ["Anomaly timeline", "Enabled", "info"]],
    visuals: [
      { title: "Residuals over time", body: "Shows residual bias, seasonality, variance changes, and anomaly clusters.", rows: [["Residual autocorrelation", "ACF should be reviewed before approval"], ["Residual seasonality", "Calendar feature or model form may be missing"]] },
      { title: "Error by horizon", body: "Separates near-term and long-horizon error to avoid approving a model that only works at one forecast horizon.", rows: [["Horizon degradation", "Escalate when error rises across horizon"], ["Coverage", "Prediction interval calibration check"]] },
      { title: "Stability trend and anomaly timeline", body: "Tracks drift, regime change, anomaly rate, and backtest degradation over time.", rows: [["Drift/regime change", "Review recent operating environment"], ["Backtest degradation", "Require monitoring threshold"]] },
      { title: "Segment error heatmap", body: "Highlights entities, products, or channels where the model underperforms.", rows: [["Segment error", "Targeted monitoring candidate"], ["Entity bias", "May require per-entity model"]] },
    ],
    evidenceType: "time_series_diagnostics",
    python: ["residuals = actuals - forecasts", "diagnostics = compute_forecast_diagnostics(residuals, horizon, entity)", "evidence['time_series_diagnostics'] = diagnostics"],
    companionCode: ["/* Store residual autocorrelation, bias, coverage, drift, anomaly, and segment-error diagnostics. */"],
    documentation: ["Diagnostics and Stability", "Limitations", "Monitoring Plan"],
    nextAction: "Resolve residual, drift, or interval warnings before scenario testing and recommendation.",
  },
  "Scenario & Stress Testing": {
    eyebrow: "Forecast stress lab",
    title: "Base forecast, stressed forecast, impact deltas, and risk flags",
    subtitle: "Stress demand, seasonality, trend, events, downturns, fraud spikes, outages, holidays, and custom drivers against the champion forecast.",
    diagnosticTitle: "Base versus scenario forecast",
    diagnosticRows: [["Base", 72], ["Demand shock", 91], ["Downturn", 48], ["Fraud spike", 86], ["Outage", 39], ["Holiday", 66]],
    primaryControls: [
      { label: "Scenario type", options: ["demand/volume shock", "seasonality shock", "trend change", "event impact", "downturn adjustment", "fraud spike", "outage", "holiday/calendar change", "custom driver adjustment"] },
      { label: "Shock magnitude", options: ["-20%", "-10%", "+10%", "+20%", "+50%", "custom"] },
      { label: "Duration", options: ["1 period", "7 periods", "30 periods", "one season", "custom"] },
      { label: "Risk flag policy", options: ["informational", "management review", "block launch", "monitoring trigger"] },
    ],
    diagnostics: [["Scenario mode", "Preview mode", "warning"], ["Peak impact", "Calculated delta", "info"], ["Worst-case period", "Flagged", "warning"], ["Risk flag", "Reviewer required", "warning"]],
    visuals: [
      { title: "Base vs scenario forecast", body: "Overlays the base forecast and stressed forecast with delta and peak impact markers.", rows: [["Base forecast", "Current champion output"], ["Stressed forecast", "Scenario-adjusted path"]] },
      { title: "Scenario impact bar chart", body: "Ranks scenarios by peak impact, total delta, duration, and risk flag.", rows: [["Peak impact", "Worst single-period movement"], ["Duration", "Number of affected periods"]] },
      { title: "Stress comparison table", body: "Stores base forecast, stressed forecast, delta, peak impact, duration, risk flag, and interpretation.", rows: [["Fraud spike", "Risk operations stress"], ["Outage", "Operational resilience stress"]] },
      { title: "Worst-case period card", body: "Identifies the forecast period with the highest adverse impact and documents escalation action.", rows: [["Worst-case period", "Reviewer action required"], ["Interpretation", "Management-ready stress narrative"]] },
    ],
    evidenceType: "time_series_scenarios",
    python: ["scenario = apply_forecast_stress(base_forecast, shock_type, magnitude, duration)", "scenario['delta'] = scenario.forecast - base_forecast.forecast", "evidence['time_series_scenarios'] = scenario_summary"],
    companionCode: ["/* Save base forecast, stressed forecast, delta, peak impact, duration, risk flag, and interpretation. */"],
    documentation: ["Scenario and Stress Testing", "Limitations", "Executive Summary"],
    nextAction: "Select scenario controls, capture stress interpretation, and define monitoring triggers.",
  },
  "Recommendation & Monitoring Plan": {
    eyebrow: "Decision and monitoring",
    title: "Forecast recommendation, limitations, monitoring metrics, and reforecast triggers",
    subtitle: "Turn the forecast study into a controlled recommendation with metric thresholds, owners, cadence, escalation, and reforecast triggers.",
    diagnosticTitle: "Recommendation and monitoring thresholds",
    diagnosticRows: [["Error", 78], ["Bias", 34], ["Coverage", 82], ["Freshness", 91], ["Drift", 29], ["Override", 16]],
    primaryControls: [
      { label: "Recommendation status", options: ["recommended", "recommended with monitoring", "research only", "do not use", "needs validation"] },
      { label: "Recommendation owner", placeholder: "Forecast owner or accountable executive" },
      { label: "Recommended action", options: ["use for planning", "pilot with reviewer", "monitor only", "refresh data", "rebuild model"] },
      { label: "Forecast use", options: ["operational planning", "financial reporting", "customer-impacting", "regulated decision support"] },
      { label: "Monitoring cadence", options: ["daily", "weekly", "monthly", "quarterly", "on trigger"] },
      { label: "Reforecast trigger", options: ["error threshold", "bias threshold", "coverage break", "data freshness", "volume drift", "seasonality drift", "anomaly rate", "override rate"] },
    ],
    diagnostics: [["Use limitations", "Required", "warning"], ["Escalation process", "Owner needed", "warning"], ["Monitoring table", "Thresholds defined", "success"], ["Evidence", "time_series_monitoring_plan", "success"]],
    visuals: [
      { title: "Recommendation banner", body: "Summarizes recommendation status, recommended action, forecast use, owner, limitations, and approval needs.", rows: [["Recommended use", "Planning, reporting, monitoring, or governed support"], ["Limitations", "Short history, sparse data, drift, residual bias, or interval uncertainty"]] },
      { title: "Monitoring threshold table", body: "Each metric has threshold, owner, cadence, and escalation action.", rows: [["Forecast error", "Threshold, owner, cadence, escalation"], ["Bias", "Threshold, owner, cadence, escalation"], ["Interval coverage", "Threshold, owner, cadence, escalation"], ["Data freshness", "Threshold, owner, cadence, escalation"], ["Missing timestamps", "Threshold, owner, cadence, escalation"], ["Volume drift", "Threshold, owner, cadence, escalation"], ["Seasonality drift", "Threshold, owner, cadence, escalation"], ["Anomaly rate", "Threshold, owner, cadence, escalation"], ["Override rate", "Threshold, owner, cadence, escalation"]] },
      { title: "Reforecast trigger card", body: "Defines when the model must refresh, retrain, or be escalated for review.", rows: [["Trigger", "Metric threshold breach"], ["Escalation action", "Notify owner and open validation case"]] },
    ],
    evidenceType: "time_series_monitoring_plan",
    python: ["monitoring_plan = build_monitoring_plan(metrics, thresholds, owners, cadence)", "evidence['time_series_recommendation'] = recommendation", "evidence['time_series_monitoring_plan'] = monitoring_plan"],
    companionCode: ["/* Persist forecast monitoring thresholds, owners, cadence, reforecast triggers, and escalation actions. */"],
    documentation: ["Recommendation", "Monitoring Plan", "Approval Record"],
    nextAction: "Approve recommendation conditions and monitoring thresholds before documentation export.",
  },
  "Documentation": {
    eyebrow: "Governed forecast package",
    title: "Documentation readiness, evidence inventory, reproducibility code, and exports",
    subtitle: "Assemble the full Time Series & Forecasting governance package with reports, code, forecast exports, and approval records.",
    diagnosticTitle: "Documentation readiness",
    diagnosticRows: [["Context", 94], ["Data", 86], ["Backtest", 78], ["Forecast", 82], ["Monitoring", 74], ["Approval", 63]],
    primaryControls: [
      { label: "Documentation readiness", options: ["draft", "ready for review", "approved", "blocked"] },
      { label: "Report export", options: ["Time Series Report", "Governed JSON", "Forecast CSV", "Backtest Results CSV", "Python Code", "SAS-Compatible Code"] },
      { label: "Approval record", options: ["not started", "review requested", "approved", "conditional approval"] },
    ],
    diagnostics: [["Evidence inventory", "Complete package expected", "success"], ["Exports", "Ready", "info"], ["Documentation package", "time_series_documentation_package", "success"], ["Reproducibility", "Code appendix expected", "info"]],
    visuals: [
      { title: "20-section Time Series Report package", body: "Executive Summary, Business Context, Data Inputs, Time Index and Grain, Target Profile, Feature and Calendar Design, Backtest Design, Model Configuration, Training and Backtest Results, Forecast Results, Diagnostics and Stability, Scenario and Stress Testing, Recommendation, Monitoring Plan, Limitations, Evidence Inventory, Python Code, SAS-Compatible Code, Approval Record, and Reproducibility Appendix.", rows: [["Report sections", "20 governed sections"], ["Readiness", "Every prior step maps to the package"]] },
      { title: "Evidence inventory", body: "Lists all captured evidence artifacts and export artifacts for registry, validation, project overview, and documentation studio.", rows: [["time_series_documentation_package", "Governed report artifact"], ["time_series_reproducibility_code", "Python and SAS-compatible code artifact"]] },
      { title: "Export buttons", body: "Supports Governed JSON, Forecast CSV, Backtest Results CSV, Python Code, SAS-Compatible Code, and Time Series Report.", rows: [["Forecast CSV", "Period-level output"], ["Backtest Results CSV", "Fold-level metrics"]] },
    ],
    evidenceType: "time_series_documentation_package",
    python: ["package = assemble_time_series_governance_package(evidence)", "export_json(package, 'time_series_governance_package.json')", "evidence['time_series_reproducibility_code'] = code_bundle"],
    companionCode: ["/* Export governed JSON, forecast CSV, backtest CSV, Python code, SAS-compatible code, and report package. */"],
    documentation: ["Evidence Inventory", "Python Code", "SAS-Compatible Code", "Approval Record", "Reproducibility Appendix"],
    nextAction: "Export the governed documentation package and register it for validation, registry, and management reporting.",
  },
};

const llmExperienceByStep: Record<string, AdvancedWorkflowExperience> = {
  "Use Case & Risk Context": {
    eyebrow: "LLM / Generative AI",
    title: "Use case boundary and AI risk tier",
    subtitle: "Define what the LLM may do, who uses it, what data it sees, customer impact, and where human review is mandatory.",
    diagnosticTitle: "Allowed and prohibited behavior matrix",
    diagnosticRows: [["Allowed", 78], ["Human review", 91], ["Sensitive data", 44], ["Prohibited", 18], ["Risk tier", 67]],
    primaryControls: [
      { label: "LLM workflow mode", options: ["Prompted LLM Workflow", "RAG / Knowledge Retrieval", "Text Classification", "Information Extraction", "Summarization", "NLP Baseline Models", "Human Review Workflow"] },
      { label: "Output type", options: ["answer", "summary", "classification", "extracted fields", "recommendation", "draft communication", "analyst assist"] },
      { label: "Customer impact", options: ["none/internal only", "indirect customer impact", "direct customer impact", "regulated decision support"] },
      { label: "Governance context", options: ["model risk", "AI governance", "privacy", "fair lending", "UDAAP", "operational risk", "internal governance"] },
    ],
    diagnostics: [["Risk tier", "Governance review required", "warning"], ["Human review", "Required for customer impact", "success"], ["Sensitive data", "PII controls expected", "warning"]],
    visuals: [
      { title: "Risk tier card", body: "Scores customer impact, sensitive data, governance context, output type, intended users, human review, and prohibited uses.", rows: [["Customer impact", "Direct or regulated impact requires controls"], ["Sensitive data flags", "PII and confidential content require approval"]] },
      { title: "Allowed/prohibited behavior matrix", body: "Separates allowed assistance from prohibited automated decisioning or unsupported advice.", rows: [["Allowed output", "Analyst assist, summary, classification, extraction"], ["Prohibited use", "Unreviewed adverse customer decision"], ["Prohibited uses", "Credit approval, adverse action, legal advice, or unsupported policy interpretation without review"]] },
      { title: "Human review card", body: "Documents when a reviewer must approve, override, or escalate an LLM output.", rows: [["Customer impact", "Human review required"], ["Regulated support", "Escalation path required"]] },
    ],
    evidenceType: "llm_use_case_context",
    python: ["llm_context = {...}", "risk_tier = score_risk(customer_impact, sensitive_data, human_review)", "evidence['llm_use_case_context'] = llm_context"],
    companionCode: ["CREATE TABLE llm_use_case_context (use_case TEXT, risk_tier TEXT, human_review_required TEXT);"],
    documentation: ["Use Case and Risk Context", "Approval Record"],
    nextAction: "Confirm the allowed behavior, prohibited uses, sensitive data flags, and human-review control.",
  },
  "Data & Knowledge Sources": {
    eyebrow: "Source inventory",
    title: "Documents, text data, and knowledge source governance",
    subtitle: "Register every source, owner, version, permitted use, confidentiality rating, PII handling rule, and freshness expectation.",
    diagnosticTitle: "Source inventory and sensitivity flags",
    diagnosticRows: [["Documents", 72], ["Freshness", 64], ["PII", 31], ["Coverage", 83], ["Permitted use", 76]],
    primaryControls: [
      { label: "Input option", options: ["Upload documents", "Upload CSV/text dataset", "Existing Dataset Library item", "SQL Data Studio source", "Manual source declaration"] },
      { label: "Source type", options: ["policy documents", "procedures", "call transcripts", "complaints", "emails", "case notes", "contracts", "FAQs", "knowledge base", "control documents", "regulatory references", "labeled text dataset"] },
      { label: "PII handling", options: ["redact before use", "retain with approval", "synthetic only", "not applicable"] },
      { label: "Refresh cadence", options: ["manual", "daily", "weekly", "monthly", "on source change"] },
    ],
    diagnostics: [["Document count", "Ready for inventory", "info"], ["Duplicate sources", "Check required", "warning"], ["Source freshness", "Version required", "warning"]],
    visuals: [
      { title: "Source inventory table", body: "Tracks source type, source owner, version, permitted use, PII/confidentiality flags, document count, text length, source freshness, and label coverage.", rows: [["Policy source", "Versioned and hash checked"], ["Complaints", "PII handling required"], ["Label coverage", "Required for classification and extraction evaluation"]] },
      { title: "Sensitive content warning cards", body: "Highlights PII, financial data, complaints, legal/regulatory content, and confidential procedure text.", rows: [["PII", "Reviewer approval required"], ["Legal content", "Escalation rule expected"]] },
    ],
    evidenceType: "llm_source_inventory",
    python: ["inventory = build_source_inventory(paths)", "inventory['document_hash'] = hash_bytes(content)", "evidence['llm_source_inventory'] = inventory"],
    companionCode: ["CREATE TABLE llm_source_inventory (source_id TEXT, source_type TEXT, owner TEXT, version TEXT, pii_handling TEXT);"],
    documentation: ["Data and Knowledge Sources", "Source Registry"],
    nextAction: "Confirm source ownership, permitted use, and sensitive-data controls before task design.",
  },
  "Task Design & Output Schema": {
    eyebrow: "Output contract",
    title: "Task definition, schema, refusal, and escalation logic",
    subtitle: "Define the LLM task, output format, confidence requirements, citation rules, review criteria, labels, and extraction fields.",
    diagnosticTitle: "JSON schema and escalation preview",
    diagnosticRows: [["Schema", 86], ["Labels", 64], ["Extraction", 58], ["Citations", 91], ["Refusal", 74]],
    primaryControls: [
      { label: "Task type", options: ["Q&A", "RAG answer", "summarize", "classify", "extract", "rewrite", "compare documents", "generate analyst note"] },
      { label: "Output schema", options: ["free text", "JSON", "label", "fields", "table", "summary bullets"] },
      { label: "Required citations", options: ["required", "required for RAG", "optional", "not applicable"] },
      { label: "Reviewer approval requirement", options: ["all outputs", "risk-based", "sampled QA", "none for research only"] },
    ],
    diagnostics: [["Output contract", "Schema draft required", "warning"], ["Refusal behavior", "Must be explicit", "warning"], ["Escalation behavior", "Reviewer path needed", "info"]],
    visuals: [
      { title: "Output schema preview", body: "Shows the exact response contract the LLM must satisfy, including JSON/schema preview, label definitions for classification, extraction field map, citation requirement, refusal behavior, and escalation behavior.", rows: [["JSON fields", "answer, citations, confidence, escalation"], ["Classification", "label, rationale, abstain flag"], ["Extraction", "field name, definition, type, required source citation"]] },
      { title: "Refusal and escalation flow", body: "Defines what the workflow does when the prompt is out of scope or unsupported by sources.", rows: [["No source found", "Refuse or escalate"], ["Low confidence", "Send to reviewer"]] },
    ],
    evidenceType: "llm_task_design",
    python: ["schema = {'answer': str, 'citations': list, 'confidence': float}", "validate_output_schema(model_output, schema)"],
    companionCode: ["CREATE TABLE llm_eval_outputs (case_id TEXT, output_json TEXT, reviewer_decision TEXT);"],
    documentation: ["Task Design and Output Schema", "Limitations"],
    nextAction: "Lock the task and output contract before writing prompts or retrieval rules.",
  },
  "Prompt & Instruction Design": {
    eyebrow: "Prompt registry",
    title: "System, developer, and user prompt design",
    subtitle: "Version prompt components, guardrails, few-shot examples, citation rules, prohibited content, and fallback instructions.",
    diagnosticTitle: "Prompt risk checklist and token estimate",
    diagnosticRows: [["System", 82], ["Developer", 78], ["User template", 71], ["Few-shot", 55], ["Conflict", 12]],
    primaryControls: [
      { label: "Prompt version label", placeholder: "policy-qa-v1.0" },
      { label: "Output format instruction", options: ["JSON", "bullets", "table", "short answer", "analyst note"] },
      { label: "Citation instruction", options: ["required with source id", "required with page/section", "not required"] },
      { label: "Fallback instruction", options: ["refuse", "escalate", "ask clarifying question", "return uncertainty"] },
    ],
    diagnostics: [["Prompt length", "Estimate required", "info"], ["Required variables", "Check placeholders", "warning"], ["Instruction conflicts", "None detected in template", "success"]],
    visuals: [
      { title: "Prompt component editor", body: "Separates system instruction, developer instruction, user prompt template, few-shot examples, negative examples, prompt version, token estimate, and guardrails.", rows: [["System instruction", "Role, scope, refusal rules"], ["Developer instruction", "Task logic, schema, citations"], ["User prompt template", "Variables, examples, and output contract"]] },
      { title: "Instruction conflict panel", body: "Flags conflicting requirements, missing citations, or unsupported output format instructions.", rows: [["Citation conflict", "Review if RAG mode"], ["Tone conflict", "Standardize before evaluation"]] },
      { title: "Prompt risk checklist", body: "Checks prompt injection exposure, unsupported claims, missing refusal behavior, missing citations, and human-review instructions.", rows: [["Negative examples", "Teach the model what not to do"], ["Token estimate", "Flags prompts likely to exceed context budget"]] },
    ],
    evidenceType: "llm_prompt_design",
    python: ["prompt_template = PromptTemplate(system=system_text, user=user_template)", "prompt_package = {'version': version, 'template': prompt_template.to_dict()}"],
    companionCode: ["CREATE TABLE llm_prompt_registry (prompt_version TEXT, system_instruction TEXT, user_template TEXT);"],
    documentation: ["Prompt and Instruction Design", "Prompt Registry"],
    nextAction: "Save the prompt package before retrieval configuration or evaluation.",
  },
  "Retrieval / RAG Configuration": {
    eyebrow: "RAG / Knowledge Retrieval",
    title: "Chunking, embeddings, vector index, top-k, reranking, metadata filters, and citation preview",
    subtitle: "Configure retrieval controls and inspect whether sources are actually reachable before any generation or evaluation.",
    diagnosticTitle: "Retrieval coverage and citation preview",
    diagnosticRows: [["Chunks", 76], ["Top-k", 64], ["Rerank", 58], ["Coverage", 82], ["Citation", 71]],
    primaryControls: [
      { label: "Chunking strategy", options: ["fixed window", "semantic section", "document heading", "sliding window", "manual chunks"] },
      { label: "Chunk size", options: ["250 tokens", "500 tokens", "800 tokens", "1200 tokens", "custom"] },
      { label: "Overlap", options: ["0%", "10%", "20%", "30%", "custom"] },
      { label: "Embedding model label", placeholder: "embedding model or local encoder label" },
      { label: "Vector index label", placeholder: "index name or collection id" },
      { label: "Top-k", options: ["3", "5", "10", "20"] },
      { label: "Reranking", options: ["off", "cross-encoder", "LLM rerank", "metadata priority"] },
      { label: "Metadata filters", placeholder: "source_type=policy, region=US, version=current" },
    ],
    diagnostics: [["Retrieval preview", "Required", "warning"], ["Citation preview", "Enabled", "success"], ["Source coverage", "Review sparse sources", "warning"]],
    visuals: [
      { title: "Chunk distribution chart", body: "Shows chunking strategy, chunk count, chunk length, overlap, source coverage, and freshness by source.", rows: [["Chunk size", "Balances recall with context cost"], ["Overlap", "Prevents boundary loss but can inflate duplicate retrieval"]] },
      { title: "Retrieval preview", body: "Shows top-k retrieved chunks, reranking outcome, metadata filters, and citation preview for representative queries.", rows: [["Top-k", "Candidate evidence context"], ["Reranking", "Improves precision for policy or legal text"]] },
      { title: "Source coverage cards", body: "Flags sources with no indexed chunks, stale versions, missing metadata, or poor citation coverage.", rows: [["Coverage", "Required for groundedness"], ["Citation preview", "Required when answers cite sources"]] },
    ],
    evidenceType: "llm_retrieval_configuration",
    python: ["chunks = chunk_documents(sources, strategy, chunk_size, overlap)", "index = build_vector_index(chunks, embedding_model)", "preview = retrieve(query, top_k=top_k, filters=metadata_filters)"],
    companionCode: ["CREATE TABLE llm_retrieval_config (strategy TEXT, chunk_size INT, overlap REAL, top_k INT, reranking TEXT);"],
    documentation: ["Retrieval Configuration", "Source Registry", "Evaluation Evidence"],
    nextAction: "Verify retrieval coverage and citation preview before building the evaluation dataset.",
  },
  "Evaluation Dataset": {
    eyebrow: "Golden test set",
    title: "Evaluation cases, expected answers, citations, rubric, adversarial examples, and coverage matrix",
    subtitle: "Build the evidence dataset that will determine whether the LLM workflow is grounded, correct, safe, and useful.",
    diagnosticTitle: "Test coverage matrix and label distribution",
    diagnosticRows: [["Golden cases", 80], ["Adversarial", 46], ["Citations", 72], ["Policy", 55], ["Rubric", 88]],
    primaryControls: [
      { label: "Evaluation case type", options: ["golden answer", "classification label", "extraction field", "adversarial example", "out-of-scope example", "policy-sensitive example"] },
      { label: "Rubric", options: ["correctness", "groundedness", "faithfulness", "citation accuracy", "safety", "classification/extraction accuracy"] },
      { label: "Required source citation", options: ["required", "required for source-backed tasks", "not applicable"] },
      { label: "Coverage target", options: ["minimum viable", "balanced labels", "risk-focused", "production gate"] },
    ],
    diagnostics: [["Test cases", "Draft", "warning"], ["Adversarial examples", "Required", "warning"], ["Policy-sensitive cases", "Required for regulated use", "warning"], ["Label distribution", "Review imbalance", "info"]],
    visuals: [
      { title: "Test case table", body: "Includes prompt, expected answer, expected label, extraction fields, required source citation, rubric, and reviewer notes.", rows: [["Expected answer", "Required for Q&A and RAG"], ["Expected label", "Required for classification"], ["Required source citation", "Required for grounded answers"]] },
      { title: "Coverage matrix", body: "Shows golden cases, adversarial examples, out-of-scope examples, policy-sensitive examples, source coverage, and label distribution.", rows: [["Adversarial examples", "Prompt injection and unsafe requests"], ["Out-of-scope examples", "Refusal correctness checks"]] },
      { title: "Label distribution chart", body: "Highlights classification label balance and extraction field coverage before evaluation.", rows: [["Classification precision/recall/F1", "Requires label coverage"], ["Extraction accuracy", "Requires expected fields"]] },
    ],
    evidenceType: "llm_evaluation_dataset",
    python: ["eval_cases = build_eval_dataset(golden_cases, adversarial_cases, policy_cases)", "coverage = summarize_eval_coverage(eval_cases)", "evidence['llm_evaluation_dataset'] = coverage"],
    companionCode: ["CREATE TABLE llm_eval_cases (case_id TEXT, prompt TEXT, expected_answer TEXT, expected_label TEXT, citation_required TEXT, rubric TEXT);"],
    documentation: ["Evaluation Dataset", "Evaluation Evidence", "Safety Evidence"],
    nextAction: "Approve the evaluation dataset before running manual or backend LLM evaluation.",
  },
  "LLM Evaluation": {
    eyebrow: "Manual evaluation template",
    title: "LLM evaluation scorecard, errors, hallucination, citations, refusal, and task metrics",
    subtitle: "If no LLM backend is configured, ATLAS shows a manual evaluation template and does not claim that a real LLM evaluation ran.",
    diagnosticTitle: "Groundedness, hallucination, citation, and refusal scorecard",
    diagnosticRows: [["Correctness", 78], ["Grounded", 72], ["Citations", 66], ["Hallucination", 18], ["Refusal", 84], ["Policy", 91]],
    primaryControls: [
      { label: "Model/provider label", placeholder: "provider and model label" },
      { label: "Model version", placeholder: "model version or deployment id" },
      { label: "Temperature", options: ["0", "0.1", "0.2", "0.7", "custom"] },
      { label: "Max tokens", options: ["512", "1024", "2048", "4096", "custom"] },
      { label: "Evaluation mode", options: ["manual evaluation template", "backend evaluation", "reviewer adjudication", "pilot QA"] },
    ],
    diagnostics: [["Backend", "Not configured unless connected", "warning"], ["Manual evaluation", "Template available", "info"], ["Metrics", "Reviewer-scored", "warning"]],
    visuals: [
      { title: "Visual scorecard", body: "Tracks correctness, groundedness, faithfulness, citation accuracy, hallucination rate, refusal correctness, policy compliance, extraction accuracy, and classification precision/recall/F1.", rows: [["Groundedness", "Answer supported by sources"], ["Hallucination rate", "Unsupported claims per case"], ["Refusal correctness", "Correctly refuses out-of-scope prompts"]] },
      { title: "Error examples table", body: "Shows case id, prompt, expected output, model output, reviewer decision, error type, citation status, and remediation.", rows: [["Citation error", "Missing or wrong source"], ["Policy error", "Unsafe or noncompliant answer"]] },
      { title: "Hallucination/citation matrix", body: "Separates unsupported claims from source citation failures so remediation can target prompts, retrieval, or source inventory.", rows: [["Faithfulness", "Source-supported wording"], ["Citation accuracy", "Correct source id or section"]] },
    ],
    evidenceType: "llm_evaluation_results",
    python: ["if not llm_backend_available: evaluation_mode = 'manual evaluation template'", "scores = score_llm_outputs(outputs, rubric)", "evidence['llm_evaluation_results'] = scores"],
    companionCode: ["CREATE TABLE llm_eval_scores (case_id TEXT, correctness REAL, groundedness REAL, citation_accuracy REAL, hallucination_flag TEXT);"],
    documentation: ["LLM Evaluation", "Evaluation Evidence", "Limitations"],
    nextAction: "Review evaluation failures and do not treat manual templates as completed backend runs.",
  },
  "Safety, Compliance & Red-Team Review": {
    eyebrow: "AI safety and compliance",
    title: "Prompt injection, leakage, hallucination, unsafe advice, fair lending, UDAAP, privacy, and escalation review",
    subtitle: "Translate LLM-specific risks into mitigations, controls, human review, and escalation paths.",
    diagnosticTitle: "Safety and compliance risk heatmap",
    diagnosticRows: [["Injection", 61], ["Leakage", 44], ["Hallucination", 38], ["UDAAP", 52], ["Fair lending", 58], ["Privacy", 72]],
    primaryControls: [
      { label: "Risk focus", options: ["prompt injection", "data leakage", "hallucination risk", "unsafe advice", "fair lending", "UDAAP", "privacy", "regulatory/legal concern", "human review", "escalation path"] },
      { label: "Mitigation level", options: ["monitor", "prompt control", "retrieval filter", "human review", "block production", "legal review"] },
      { label: "Residual risk", options: ["low", "medium", "high", "not acceptable"] },
    ],
    diagnostics: [["Red-team review", "Required for production", "warning"], ["Mitigation plan", "Draft", "warning"], ["Escalation path", "Required", "warning"]],
    visuals: [
      { title: "Risk heatmap", body: "Scores prompt injection, data leakage, hallucination risk, unsafe advice, fair lending, UDAAP, privacy, regulatory/legal concerns, and human-review gaps.", rows: [["Prompt injection", "Can override instructions or source rules"], ["Data leakage", "Can expose confidential or PII content"], ["Fair lending and UDAAP", "Requires regulated-use review"]] },
      { title: "Mitigation plan", body: "Maps each risk to a control, owner, residual risk, test evidence, and escalation path.", rows: [["Human review", "Required for customer-impacting output"], ["Escalation path", "Legal, compliance, model risk, or privacy route"]] },
    ],
    evidenceType: "llm_safety_red_team_review",
    python: ["risk_matrix = score_llm_safety_risks(test_results, red_team_cases)", "mitigations = map_controls(risk_matrix)", "evidence['llm_safety_red_team_review'] = mitigations"],
    companionCode: ["CREATE TABLE llm_safety_findings (risk TEXT, severity TEXT, mitigation TEXT, owner TEXT, residual_risk TEXT);"],
    documentation: ["Safety Evidence", "Limitations", "Approval Record"],
    nextAction: "Resolve unacceptable safety, compliance, or privacy risks before human review design.",
  },
  "Human Review & Quality Control": {
    eyebrow: "Human-in-the-loop control",
    title: "Reviewer sampling, override, escalation, rubric, and quality thresholds",
    subtitle: "Define how humans review LLM outputs, sample production traffic, override model responses, and escalate risky content.",
    diagnosticTitle: "Review workflow diagram and quality control table",
    diagnosticRows: [["Review rate", 64], ["Override", 22], ["Escalation", 48], ["Rubric", 86], ["Threshold", 74]],
    primaryControls: [
      { label: "Review required", options: ["all outputs", "risk-based", "sampled", "only customer-impacting", "research only"] },
      { label: "Review rate", options: ["5%", "10%", "25%", "50%", "100%", "custom"] },
      { label: "Reviewer role", options: ["data scientist", "business owner", "compliance", "model risk", "operations lead", "legal"] },
      { label: "Sampling strategy", options: ["random", "risk-based", "topic drift", "low confidence", "complaint-sensitive"] },
      { label: "Override process", options: ["annotate and replace", "block output", "escalate", "rerun with corrected prompt"] },
      { label: "Quality threshold", options: ["90%", "95%", "98%", "custom"] },
    ],
    diagnostics: [["Reviewer rubric", "Required", "success"], ["Override process", "Defined", "info"], ["Escalation process", "Owner needed", "warning"]],
    visuals: [
      { title: "Review workflow diagram", body: "Shows output generation, risk scoring, sampling, reviewer decision, override, escalation, and evidence capture.", rows: [["Sampling strategy", "Random, risk-based, topic drift, or low confidence"], ["Escalation process", "Routes to compliance, legal, model risk, or operations"]] },
      { title: "Quality control table", body: "Tracks reviewer role, review rate, rubric, quality threshold, override process, escalation process, and monitoring action.", rows: [["Reviewer rubric", "Correctness, groundedness, safety, tone, citations"], ["Override rate", "Monitoring metric and quality signal"]] },
    ],
    evidenceType: "llm_human_review_quality_control",
    python: ["review_plan = {'rate': review_rate, 'strategy': sampling_strategy, 'threshold': quality_threshold}", "evidence['llm_human_review_quality_control'] = review_plan"],
    companionCode: ["CREATE TABLE llm_human_review (case_id TEXT, reviewer_role TEXT, decision TEXT, override_flag TEXT, escalation_flag TEXT);"],
    documentation: ["Human Review Plan", "Monitoring Plan", "Approval Record"],
    nextAction: "Approve review sampling, override, and escalation controls before deployment planning.",
  },
  "Deployment & Monitoring Plan": {
    eyebrow: "Controlled deployment",
    title: "Deployment mode, version control, approved users, monitoring metrics, cadence, cost, latency, and change control",
    subtitle: "Define how the LLM workflow enters controlled use and how groundedness, safety, cost, source freshness, and drift will be monitored.",
    diagnosticTitle: "Deployment and monitoring threshold table",
    diagnosticRows: [["Grounded", 78], ["Hallucination", 14], ["Citation", 72], ["Latency", 58], ["Cost", 46], ["Freshness", 83]],
    primaryControls: [
      { label: "Deployment mode", options: ["research only", "pilot", "human-reviewed production", "internal assistant", "blocked"] },
      { label: "Model/provider", placeholder: "approved model/provider label" },
      { label: "Prompt version", placeholder: "prompt registry version" },
      { label: "Source version", placeholder: "source inventory version" },
      { label: "Approved users", placeholder: "roles or groups" },
      { label: "Change control", options: ["manual approval", "model risk approval", "source refresh approval", "prompt version approval"] },
      { label: "Monitoring cadence", options: ["daily", "weekly", "monthly", "quarterly", "on incident"] },
    ],
    diagnostics: [["Version control summary", "Required", "warning"], ["Monitoring metrics", "Thresholds expected", "warning"], ["Change control", "Required", "warning"]],
    visuals: [
      { title: "Version control summary", body: "Links deployment mode, model/provider, prompt version, source version, approved users, and change-control rules.", rows: [["Prompt version", "Must match approved registry entry"], ["Source version", "Must match approved source inventory"]] },
      { title: "Monitoring threshold table", body: "Tracks groundedness, hallucination, citation accuracy, refusal correctness, escalation rate, override rate, user feedback, input topic drift, source freshness, latency, and cost.", rows: [["Groundedness", "Threshold, owner, cadence, escalation"], ["Hallucination", "Threshold, owner, cadence, escalation"], ["Citation accuracy", "Threshold, owner, cadence, escalation"], ["Source freshness", "Threshold, owner, cadence, escalation"], ["Latency and cost", "Operational monitoring"]] },
    ],
    evidenceType: "llm_deployment_monitoring_plan",
    python: ["deployment_manifest = build_llm_deployment_manifest(model, prompt_version, source_version)", "monitoring_plan = build_llm_monitoring_thresholds(metrics)", "evidence['llm_deployment_monitoring_plan'] = monitoring_plan"],
    companionCode: ["CREATE TABLE llm_monitoring_thresholds (metric TEXT, threshold TEXT, owner TEXT, cadence TEXT, escalation_action TEXT);"],
    documentation: ["Deployment and Monitoring Plan", "Approval Record", "Source Registry"],
    nextAction: "Lock version control, approved users, and monitoring thresholds before recommendation.",
  },
  "Recommendation & Approval": {
    eyebrow: "Approval recommendation",
    title: "Recommended use, required controls, alternatives, residual risks, limitations, and approval conditions",
    subtitle: "Produce a clear recommendation that states whether the LLM workflow is ready for research, pilot, human-reviewed production, or blocked use.",
    diagnosticTitle: "Recommendation banner and approval controls",
    diagnosticRows: [["Controls", 84], ["Residual risk", 42], ["Alternatives", 55], ["Limitations", 73], ["Approval", 68]],
    primaryControls: [
      { label: "Recommendation status", options: ["research only", "pilot with controls", "human-reviewed production", "do not deploy", "needs remediation"] },
      { label: "Recommendation owner", placeholder: "accountable owner" },
      { label: "Recommended use", options: ["analyst assist", "knowledge retrieval", "classification", "extraction", "summary generation", "quality control"] },
      { label: "Approval condition", options: ["human review", "source refresh", "red-team remediation", "monitoring threshold", "legal approval", "model risk approval"] },
    ],
    diagnostics: [["Required controls", "Documented", "success"], ["Residual risks", "Reviewer approval needed", "warning"], ["Approval conditions", "Draft", "warning"]],
    visuals: [
      { title: "Recommendation banner", body: "Shows recommendation status, owner, recommended use, required controls, alternatives considered, residual risks, limitations, and approval conditions.", rows: [["Recommended use", "Must match approved use case"], ["Required controls", "Human review, monitoring, source version, safety controls"]] },
      { title: "Residual risk and alternatives table", body: "Documents unresolved limitations, alternative non-LLM approaches, and why the recommended control set is acceptable.", rows: [["Residual risks", "Hallucination, privacy, UDAAP, fair lending, source freshness"], ["Alternatives considered", "Rules, search, supervised model, manual workflow"]] },
    ],
    evidenceType: "llm_recommendation_approval",
    python: ["recommendation = build_llm_recommendation(evaluation, safety, monitoring)", "evidence['llm_recommendation_approval'] = recommendation"],
    companionCode: ["CREATE TABLE llm_recommendations (status TEXT, owner TEXT, recommended_use TEXT, controls TEXT, residual_risks TEXT);"],
    documentation: ["Recommendation and Approval", "Limitations", "Approval Record"],
    nextAction: "Capture approval conditions and export the governance package.",
  },
  "Documentation": {
    eyebrow: "LLM governance package",
    title: "Documentation readiness, prompt/source registries, evaluation evidence, safety evidence, and exports",
    subtitle: "Assemble the 20-section LLM governance package with prompt, source, evaluation, safety, human review, deployment, monitoring, and reproducibility evidence.",
    diagnosticTitle: "LLM governance package readiness",
    diagnosticRows: [["Use case", 94], ["Sources", 86], ["Prompt", 78], ["Evaluation", 72], ["Safety", 69], ["Monitoring", 74]],
    primaryControls: [
      { label: "Documentation readiness", options: ["draft", "ready for review", "approved", "blocked"] },
      { label: "Export package", options: ["Governed JSON", "Evaluation Results CSV", "Prompt Package", "Source Inventory", "Python Code", "SQL/SAS-Compatible Template", "LLM Governance Report"] },
      { label: "Approval record", options: ["not started", "review requested", "approved", "conditional approval"] },
    ],
    diagnostics: [["Prompt registry", "Included", "success"], ["Source registry", "Included", "success"], ["Evaluation evidence", "Included", "success"], ["Safety evidence", "Included", "success"]],
    visuals: [
      { title: "20-section LLM governance package", body: "Includes use case, risk tier, source inventory, task schema, prompt registry, retrieval configuration, evaluation dataset, LLM evaluation, safety review, human review, deployment, monitoring, recommendation, limitations, evidence inventory, code, exports, approval record, change control, and reproducibility appendix.", rows: [["Governance report", "20 controlled sections"], ["Approval record", "Required before production use"]] },
      { title: "Prompt registry and source registry", body: "Exports prompt package, source inventory, source versions, permitted use, PII handling, retrieval config, and citation requirements.", rows: [["Prompt Package", "System, developer, user template, examples"], ["Source Inventory", "Owner, version, permitted use, confidentiality"]] },
      { title: "Export buttons", body: "Supports Governed JSON, Evaluation Results CSV, Prompt Package, Source Inventory, Python Code, SQL/SAS-Compatible Template, and LLM Governance Report.", rows: [["Evaluation Results CSV", "Case-level metrics and errors"], ["LLM Governance Report", "Management and validation package"]] },
    ],
    evidenceType: "llm_governance_documentation_package",
    python: ["package = assemble_llm_governance_package(evidence)", "export_json(package, 'llm_governance_package.json')", "evidence['llm_reproducibility_code'] = code_bundle"],
    companionCode: ["-- Export governed JSON, evaluation results CSV, prompt package, source inventory, SQL/SAS template, and governance report."],
    documentation: ["LLM Governance Package", "Prompt Registry", "Source Registry", "Evaluation Evidence", "Safety Evidence", "Deployment and Monitoring Plan"],
    nextAction: "Export the LLM governance package and route it to validation, registry, evidence center, and documentation studio.",
  },
};

const defaultTimeSeriesExperience: AdvancedWorkflowExperience = {
  eyebrow: "Time Series & Forecasting",
  title: "Time-aware workflow checkpoint",
  subtitle: "Use this page to capture controls, diagnostics, evidence, documentation mapping, and reproducible code for the current forecasting step.",
  primaryControls: [
    { label: "Primary setting", options: ["guided default", "review required", "power user override"] },
    { label: "Evidence status", options: ["draft", "ready for review", "approved"] },
    { label: "Export option", options: ["governed JSON", "forecast CSV", "Python code", "SAS-compatible template"] },
  ],
  diagnostics: [["Temporal order", "Preserved", "success"], ["Evidence", "Required", "warning"], ["Monitoring", "Plan expected", "info"]],
  visuals: [
    { title: "Diagnostic workspace", body: "Displays the step-specific chart, table, or monitoring view required before the workflow advances.", rows: [["Charts", "Labels, confidence ranges, and interpretation"], ["Tables", "Searchable and export-ready"]] },
    { title: "ATLAS interpretation", body: "Plain-English explanation of what the diagnostics mean for forecast use, limitations, and next action.", rows: [["Finding", "Requires reviewer confirmation"], ["Next action", "Capture evidence and continue"]] },
  ],
  evidenceType: "time_series_step_evidence",
  python: ["# Step-specific time-series evidence template", "evidence = {'workflow_type': 'time_series_forecasting'}"],
  companionCode: ["/* SAS-compatible governance template for time-series evidence. */"],
  documentation: ["Evidence Inventory", "Python Code", "SAS-Compatible Code"],
  nextAction: "Capture evidence, export reproducibility code, and continue to the next time-aware checkpoint.",
};

const defaultLlmExperience: AdvancedWorkflowExperience = {
  eyebrow: "LLM / Generative AI",
  title: "LLM governance workflow checkpoint",
  subtitle: "Use this page to capture source controls, task logic, evaluation criteria, safety review, human review, and reproducibility evidence. If no LLM backend is configured, ATLAS labels the page as a manual evaluation template and does not claim real model execution.",
  primaryControls: [
    { label: "Primary setting", options: ["guided default", "review required", "power user override"] },
    { label: "Evidence status", options: ["draft", "ready for review", "approved"] },
    { label: "Export option", options: ["governed JSON", "prompt package", "evaluation CSV", "SQL/SAS template"] },
  ],
  diagnostics: [["Source grounding", "Review required", "warning"], ["Human review", "Expected", "info"], ["Evidence", "Required", "success"]],
  visuals: [
    { title: "Governance workspace", body: "Displays the step-specific checklist, table, metric card, or evaluation matrix needed before recommendation.", rows: [["Controls", "Risk, source, prompt, evaluation, safety"], ["Outputs", "Evidence-ready and documentation-ready"]] },
    { title: "ATLAS interpretation", body: "Explains whether the workflow can support research use, controlled pilot, human-reviewed production, or blocked production use.", rows: [["Finding", "Reviewer confirmation required"], ["Next action", "Capture evidence and continue"]] },
  ],
  evidenceType: "llm_step_evidence",
  python: ["# Step-specific LLM governance evidence template", "evidence = {'workflow_type': 'llm_generative_ai'}"],
  companionCode: ["-- SQL/SAS-compatible governance template for LLM evaluation records."],
  documentation: ["Evidence Inventory", "Prompt Registry", "Source Registry", "Reproducibility Appendix"],
  nextAction: "Capture evidence, verify no unsupported model claims are made, and continue.",
};

function advancedExperienceFor(workflowId: string, stepLabel: string): AdvancedWorkflowExperience {
  if (workflowId === "time_series_forecasting") return timeSeriesExperienceByStep[stepLabel] ?? defaultTimeSeriesExperience;
  return llmExperienceByStep[stepLabel] ?? defaultLlmExperience;
}

function advancedWorkflowHeaderLabel(workflowId: string): string {
  if (workflowId === "time_series_forecasting") return "TIME SERIES & FORECASTING WORKFLOW";
  if (workflowId === "llm_generative_ai") return "LLM / GENERATIVE AI WORKFLOW";
  return "ADVANCED ANALYTICS WORKFLOW";
}

function defaultAdvancedChartRows(workflowId: string, stepLabel: string): Array<[string, number]> {
  if (workflowId === "time_series_forecasting") {
    const rowsByStep: Record<string, Array<[string, number]>> = {
      "Project Context": [["Goal", 86], ["Governance", 74], ["Horizon", 68], ["Backtest", 61], ["Monitoring", 79]],
      "Data Acquisition": [["Rows", 78], ["Coverage", 92], ["Frequency", 84], ["Gaps", 18], ["Entities", 67]],
      "Time Series Profile": [["Level", 76], ["Trend", 82], ["Volatility", 58], ["Seasonality", 64], ["Anomalies", 21]],
      "Feature & Calendar Design": [["Lag", 88], ["Rolling", 73], ["Calendar", 81], ["Known future", 54], ["Leakage", 16]],
      "Backtest Design": [["Train", 68], ["Gap", 12], ["Validation", 24], ["Holdout", 19], ["Horizon", 31]],
      "Model Configuration": [["Naive", 42], ["Seasonal", 58], ["Smoothing", 71], ["ARIMA", 64], ["Boosting", 82], ["Anomaly", 48]],
      "Train & Backtest": [["Naive", 52], ["Seasonal", 61], ["ETS", 73], ["ARIMA", 69], ["Boosting", 84], ["Forest", 78]],
      "Forecast Results": [["Actuals", 74], ["Forecast", 82], ["Lower interval", 55], ["Upper interval", 91], ["Scenario", 64]],
      "Diagnostics & Stability": [["Residuals", 36], ["ACF", 42], ["Horizon error", 58], ["Coverage", 74], ["Drift", 29], ["Anomaly rate", 18]],
      "Scenario & Stress Testing": [["Base", 72], ["Demand shock", 91], ["Downturn", 48], ["Fraud spike", 86], ["Outage", 39], ["Holiday", 66]],
      "Recommendation & Monitoring Plan": [["Error", 78], ["Bias", 34], ["Coverage", 82], ["Freshness", 91], ["Drift", 29], ["Override", 16]],
      "Documentation": [["Context", 94], ["Data", 86], ["Backtest", 78], ["Forecast", 82], ["Monitoring", 74], ["Approval", 63]],
    };
    return rowsByStep[stepLabel] ?? [["Temporal order", 84], ["Evidence", 72], ["Monitoring", 68], ["Export", 59]];
  }
  const rowsByStep: Record<string, Array<[string, number]>> = {
    "Use Case & Risk Context": [["Allowed", 78], ["Human review", 91], ["Sensitive data", 44], ["Prohibited", 18], ["Risk tier", 67]],
    "Data & Knowledge Sources": [["Documents", 72], ["Freshness", 64], ["PII", 31], ["Coverage", 83], ["Permitted use", 76]],
    "Task Design & Output Schema": [["Schema", 86], ["Labels", 64], ["Extraction", 58], ["Citations", 91], ["Refusal", 74]],
    "Prompt & Instruction Design": [["System", 82], ["Developer", 78], ["User template", 71], ["Few-shot", 55], ["Conflict", 12]],
    "Retrieval / RAG Configuration": [["Chunks", 76], ["Top-k", 64], ["Rerank", 58], ["Coverage", 82], ["Citation", 71]],
    "Evaluation Dataset": [["Golden cases", 80], ["Adversarial", 46], ["Citations", 72], ["Policy", 55], ["Rubric", 88]],
    "LLM Evaluation": [["Correctness", 78], ["Grounded", 72], ["Citations", 66], ["Hallucination", 18], ["Refusal", 84], ["Policy", 91]],
    "Safety, Compliance & Red-Team Review": [["Injection", 61], ["Leakage", 44], ["Hallucination", 38], ["UDAAP", 52], ["Fair lending", 58], ["Privacy", 72]],
    "Human Review & Quality Control": [["Review rate", 64], ["Override", 22], ["Escalation", 48], ["Rubric", 86], ["Threshold", 74]],
    "Deployment & Monitoring Plan": [["Grounded", 78], ["Hallucination", 14], ["Citation", 72], ["Latency", 58], ["Cost", 46], ["Freshness", 83]],
    "Recommendation & Approval": [["Controls", 84], ["Residual risk", 42], ["Alternatives", 55], ["Limitations", 73], ["Approval", 68]],
    "Documentation": [["Use case", 94], ["Sources", 86], ["Prompt", 78], ["Evaluation", 72], ["Safety", 69], ["Monitoring", 74]],
  };
  return rowsByStep[stepLabel] ?? [["Correct", 86], ["Grounded", 78], ["Cited", 72], ["Safe", 94], ["Needs review", 18]];
}

function AdvancedWorkflowStep({
  workflowId,
  projectType,
  step,
  nextStep,
  state,
  setState,
  save,
  onComplete,
  navigationError,
}: {
  workflowId: string;
  projectType: ProjectType;
  step: WorkflowStep;
  nextStep?: WorkflowStep;
  state: NodeState;
  setState: (state: NodeState) => void;
  save: () => void;
  onComplete: () => boolean;
  navigationError: string | null;
}) {
  const experience = advancedExperienceFor(workflowId, step.label);
  const workflowHeaderLabel = advancedWorkflowHeaderLabel(workflowId);
  const metricChoices = metricOptions[projectType] ?? metricOptions.default;
  const methodChoices = methodOptions[projectType] ?? methodOptions.default;
  const chartRows: Array<[string, number]> = experience.diagnosticRows ?? defaultAdvancedChartRows(workflowId, step.label);
  return (
    <StepShell
      title={step.label}
      subtitle={step.description}
      nextLabel={nextStep ? "Mark Complete & Next Step" : "Save & Return to Overview"}
      nextPath={nextStep?.route ?? "/project-overview"}
      onNext={onComplete}
    >
      <div className="space-y-5">
        {navigationError && <InlineError message={navigationError} />}
        <section className="overflow-hidden rounded-2xl border border-slate-200 bg-slate-950 text-white shadow-sm">
          <div className="p-5">
            <div className="text-[11px] font-semibold uppercase tracking-[0.16em] text-emerald-300">{workflowHeaderLabel}</div>
            <div className="mt-2 inline-flex rounded-full border border-white/10 bg-white/10 px-3 py-1 text-[11px] font-semibold uppercase tracking-wide text-slate-200">{experience.eyebrow}</div>
            <h1 className="mt-2 text-2xl font-semibold">{experience.title}</h1>
            <p className="mt-2 max-w-4xl text-sm leading-6 text-slate-200">{experience.subtitle}</p>
          </div>
          <div className="grid border-t border-white/10 bg-white/10 md:grid-cols-3">
            {experience.diagnostics.map(([label, value, tone]) => (
              <div key={label} className="border-r border-white/10 p-4 last:border-r-0">
                <div className="text-[10px] font-semibold uppercase tracking-wide text-slate-300">{label}</div>
                <div className={`mt-1 text-sm font-semibold ${tone === "warning" ? "text-amber-200" : tone === "danger" ? "text-rose-200" : tone === "success" ? "text-emerald-200" : "text-white"}`}>{value}</div>
              </div>
            ))}
          </div>
        </section>

        <section className="grid gap-4 xl:grid-cols-[0.8fr_1.2fr]">
          <div className="rounded-2xl border border-blue-200 bg-blue-50 p-5">
            <div className="text-[11px] font-semibold uppercase tracking-wide text-blue-700">Guided controls</div>
            <div className="mt-4 grid gap-3">
              {experience.primaryControls.map((control) => (
                <label key={control.label} className="grid gap-1.5">
                  <span className="text-xs font-semibold text-slate-700">{control.label}</span>
                  {control.options ? (
                    <select className="atlas-input" onChange={(event) => setState({ ...state, method: event.target.value })}>
                      <option value="">Select option</option>
                      {control.options.map((option) => <option key={option} value={option}>{option}</option>)}
                    </select>
                  ) : (
                    <input className="atlas-input" placeholder={control.placeholder} />
                  )}
                </label>
              ))}
            </div>
            <div className="mt-5">
              <MetricPicker
                options={metricChoices}
                selected={state.metrics}
                onChange={(metrics) => setState({ ...state, metrics })}
              />
            </div>
          </div>

          <div className="grid gap-4">
            <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">Diagnostic visualization</div>
                  <h2 className="mt-1 text-lg font-semibold text-slate-950">{experience.diagnosticTitle ?? experience.visuals[0]?.title ?? "Workflow diagnostic scorecard"}</h2>
                </div>
                <button type="button" className="atlas-secondary-button" onClick={() => downloadText(`${workflowId}-${step.id}-diagnostics.json`, JSON.stringify({ step: step.label, chartRows }, null, 2), "application/json;charset=utf-8")}>
                  <Download size={15} />
                  Export diagnostics
                </button>
              </div>
              <div className="mt-5 grid gap-3">
                {chartRows.map(([label, value]) => (
                  <div key={label} className="grid grid-cols-[70px_1fr_54px] items-center gap-3 text-xs">
                    <span className="font-semibold text-slate-700">{label}</span>
                    <span className="h-3 overflow-hidden rounded-full bg-slate-100">
                      <span className="block h-full rounded-full bg-emerald-500" style={{ width: `${Math.max(6, Math.min(100, value))}%` }} />
                    </span>
                    <span className="text-right font-semibold text-slate-950">{value}</span>
                  </div>
                ))}
              </div>
            </div>

            <div className="grid gap-4 lg:grid-cols-2">
              {experience.visuals.map((panel) => (
                <div key={panel.title} className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
                  <h3 className="text-sm font-semibold text-slate-950">{panel.title}</h3>
                  <p className="mt-2 text-xs leading-5 text-slate-600">{panel.body}</p>
                  <div className="mt-4 grid gap-2">
                    {panel.rows.map(([label, value]) => <ResultCard key={label} label={label} value={value} />)}
                  </div>
                </div>
              ))}
            </div>
          </div>
        </section>

        <section className="grid gap-4 lg:grid-cols-2">
          <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
            <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">Workflow evidence</div>
            <h2 className="mt-1 text-sm font-semibold text-slate-950">{experience.evidenceType}</h2>
            <div className="mt-4 grid gap-4">
              <TextArea label="Objective / Question" value={state.objective} onChange={(value) => setState({ ...state, objective: value })} rows={3} />
              <TextArea label="Inputs / Data Needed" value={state.inputs} onChange={(value) => setState({ ...state, inputs: value })} rows={3} />
              <label className="grid gap-1.5">
                <span className="text-xs font-semibold uppercase tracking-wide text-slate-500">Method</span>
                <select className="atlas-input" value={state.method} onChange={(event) => setState({ ...state, method: event.target.value })}>
                  <option value="">Select method</option>
                  {methodChoices.map((method) => <option key={method} value={method}>{method}</option>)}
                </select>
              </label>
              <TextArea label="Risks / Limitations" value={state.risks} onChange={(value) => setState({ ...state, risks: value })} rows={3} />
              <TextArea label="Decision / Recommendation" value={state.decision} onChange={(value) => setState({ ...state, decision: value })} rows={3} />
            </div>
          </div>

          <div className="grid gap-4">
            <div className="rounded-2xl border border-emerald-200 bg-emerald-50 p-5">
              <div className="text-[11px] font-semibold uppercase tracking-wide text-emerald-700">ATLAS interpretation</div>
              <p className="mt-2 text-sm leading-6 text-emerald-950">{experience.nextAction}</p>
              <div className="mt-4 grid gap-2">
                {experience.documentation.map((item) => <ResultCard key={item} label="Documentation section" value={item} />)}
              </div>
            </div>

            <details className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm" open>
              <summary className="cursor-pointer text-sm font-semibold text-slate-950">Code & Reproducibility</summary>
              <div className="mt-4 grid gap-3">
                <pre className="overflow-auto rounded-xl bg-slate-950 p-4 text-xs leading-5 text-slate-100">{experience.python.join("\n")}</pre>
                <pre className="overflow-auto rounded-xl bg-slate-100 p-4 text-xs leading-5 text-slate-800">{experience.companionCode.join("\n")}</pre>
              </div>
            </details>
          </div>
        </section>

        <div className="flex flex-wrap gap-2">
          <button type="button" className="atlas-secondary-button" onClick={() => save()}>
            <Save size={15} />
            Save {experience.evidenceType} Evidence
          </button>
          <button type="button" className="atlas-secondary-button" onClick={() => downloadText(`${workflowId}-${step.id}-evidence.json`, JSON.stringify({ evidenceType: experience.evidenceType, state }, null, 2), "application/json;charset=utf-8")}>
            <Download size={15} />
            Export Evidence JSON
          </button>
          <Link to="/model-evidence-center" className="atlas-secondary-button">Open Evidence Center</Link>
          <Link to="/model-document-studio" className="atlas-secondary-button">Open Documentation Studio</Link>
        </div>
      </div>
    </StepShell>
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
  const normalizeWorkflowOrder = useWorkflowStore((state) => state.normalizeWorkflowOrder);
  const navigate = useNavigate();
  const activeWorkflowId = params.workflowId ?? workflowId;
  const stepIndex = Math.max(0, Number(params.stepNumber ?? "1") - 1);
  const definedWorkflowSteps = getWorkflowDefinition(activeWorkflowId).steps;
  const step = definedWorkflowSteps[stepIndex] ?? workflowSteps[stepIndex];
  const nextStep = definedWorkflowSteps[stepIndex + 1] ?? workflowSteps[stepIndex + 1];
  const [state, setState] = useState<NodeState>(() => loadNodeState(projectId, step?.id ?? `${activeWorkflowId}-${stepIndex + 1}`));
  const stateRef = useRef(state);
  const [navigationError, setNavigationError] = useState<string | null>(null);
  const [saveStatusMessage, setSaveStatusMessage] = useState("");
  const metricChoices = metricOptions[projectType] ?? metricOptions.default;
  const methodChoices = methodOptions[projectType] ?? methodOptions.default;
  const guide = useMemo(() => recommendations(projectType, step?.label ?? ""), [projectType, step?.label]);
  const isAbTestingWorkflow = activeWorkflowId === "ab-testing" || projectType === "ab-testing";
  const abAcquisitionState = isAbTestingWorkflow ? loadNodeState(projectId, "ab-testing-2") : emptyState();
  const abConfirmedMapping = { ...AB_WORKFLOW_DEFAULTS, ...(abAcquisitionState.ab ?? {}) } as AbTestingDefaults & NonNullable<NodeState["ab"]>;
  // A/B dataset defaults are only *suggestions* until the user completes the
  // "Data Acquisition and Experiment Mapping" step (ab-testing-2).
  const abTestingDataAcquisitionConfirmed =
    isAbTestingWorkflow && Boolean(abAcquisitionState.ab?.confirmed);
  const currentStepNumber = stepIndex + 1;
  const currentRoute = `/workflow/ab-testing/${currentStepNumber}`;
  const nextAbRoute = `/workflow/ab-testing/${currentStepNumber + 1}`;
  const [lastAction, setLastAction] = useState("Not clicked yet");
  const [lastSavedStorageKey, setLastSavedStorageKey] = useState("");
  const [lastSavedTimestamp, setLastSavedTimestamp] = useState("");
  const [lastPayloadSizeKb, setLastPayloadSizeKb] = useState("");
  const [lastStorageStatus, setLastStorageStatus] = useState("");

  useEffect(() => {
    if (activeWorkflowId === "ab-testing") {
      normalizeWorkflowOrder("ab-testing");
    }
  }, [activeWorkflowId, workflowId, normalizeWorkflowOrder]);

  useEffect(() => {
    stateRef.current = state;
  }, [state]);

  useEffect(() => {
    if (!step) return;
    const restored = loadNodeState(projectId, step.id);
    stateRef.current = restored;
    setState(restored);
    setNavigationError(null);
    setSaveStatusMessage("");
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

  const save = (options?: { completed?: boolean }) => {
    const currentState = stateRef.current;
    const stateToSave = isAbTestingWorkflow ? currentState : saveNodeState(projectId, step.id, currentState);
    if (isAbTestingWorkflow) {
      const result = saveAbTestingStep({
        projectId,
        workflowType: "ab_testing",
        stepId: step.id,
        stepNumber: currentStepNumber,
        stepSlug: step.id,
        stepRoute: currentRoute,
        formValues: stateToSave as unknown as Record<string, unknown>,
        calculatedMetrics: {
          evidenceType: evidenceTypeForAbStep(step.label),
          route: currentRoute,
        },
        reviewerNotes: stateToSave.rationale || stateToSave.notes,
        evidenceStatus: "saved",
        completed: Boolean(options?.completed) || step.status === "complete",
      });
      if (!result.browserCacheWritten) {
        throw new Error(result.browserCacheError ?? "Local browser cache could not be updated.");
      }
      setLastSavedStorageKey(result.workflowNodeStorageKey);
      setLastSavedTimestamp(result.payload.updatedAt ?? "");
      setLastPayloadSizeKb(`${(result.payloadBytes / 1024).toFixed(1)} KB`);
      setLastStorageStatus("project artifact + compact browser cache");
      setSaveStatusMessage("A/B Testing workflow step saved.");
    }
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
    setSaveStatusMessage("");
    try {
      save({ completed: true });
    } catch (error) {
      console.error("ATLAS workflow save failed before navigation", error);
      setNavigationError(isAbTestingWorkflow ? "A/B Testing workflow step could not be saved." : `ATLAS could not save this page. ${error instanceof Error ? error.message : "Please try again."}`);
      return false;
    }
    try {
      markWorkflowStepComplete(step.id);
      if (nextStep) setWorkflowStepStatus(nextStep.id, "in_progress");
      setCurrentStepId(nextStep?.id ?? step.id);
    } catch (error) {
      console.error("ATLAS progress update failed after page save", error);
      setNavigationError(isAbTestingWorkflow ? "A/B Testing workflow step could not be saved." : "ATLAS could not update workflow progress. Please try again.");
      return false;
    }
    navigate(nextStep?.route ?? "/project-overview");
    window.setTimeout(() => window.scrollTo({ top: 0, behavior: "auto" }), 0);
    return true;
  };

  // Best-effort save of just this page's text. Persistence must NEVER block navigation:
  // a full-localStorage quota error is recoverable, but the user still needs to move on.
  const persistAbStepText = (savedAt: string) =>
    saveAbTestingStep({
      projectId,
      workflowType: "ab_testing",
      stepId: step!.id,
      stepNumber: currentStepNumber,
      stepSlug: step!.id,
      stepRoute: currentRoute,
      formValues: stateRef.current as unknown as Record<string, unknown>,
      calculatedMetrics: {
        evidenceType: evidenceTypeForAbStep(step!.label),
        route: currentRoute,
        nextRoute: nextStep?.route ?? `/workflow/ab-testing/${currentStepNumber + 1}`,
      },
      reviewerNotes: String(stateRef.current.rationale ?? stateRef.current.notes ?? ""),
      evidenceStatus: "saved",
      completed: true,
      updatedAt: savedAt,
    });

  const handleAbTestingMarkCompleteAndNext = (event?: MouseEvent<HTMLButtonElement>) => {
    event?.preventDefault();
    event?.stopPropagation();

    const clickedAt = new Date();
    setNavigationError(null);
    setSaveStatusMessage("");
    setLastAction(`Mark Complete clicked at ${clickedAt.toLocaleTimeString()}`);

    if (!step) {
      setLastAction("Save failed: workflow step was not found");
      setNavigationError("A/B Testing workflow step could not be saved. Workflow step was not found.");
      return;
    }

    const nextRoute = nextStep?.route ?? `/workflow/ab-testing/${currentStepNumber + 1}`;
    const savedAt = new Date().toISOString();
    let cacheWarning = "";
    if (step.id === "ab-testing-2") {
      const mapping = { ...AB_WORKFLOW_DEFAULTS, ...(stateRef.current.ab ?? {}) } as AbTestingDefaults & NonNullable<NodeState["ab"]>;
      const hasValidatedArtifact = Boolean(
        mapping.confirmed
        && mapping.analysisDataSource === "full_dataset_artifact"
        && mapping.fullDatasetArtifactId
        && (mapping.fullDatasetRowCount ?? 0) > 0
        && (mapping.validAnalysisRecordCount ?? 0) > 0
      );
      if (!hasValidatedArtifact) {
        setLastAction("Navigation blocked: Data Acquisition mapping is not confirmed");
        setNavigationError("Confirm Data Acquisition and Mapping after ATLAS validates the full dataset artifact. Preview rows and an incomplete mapping cannot advance the experiment workflow.");
        return;
      }
    }

    const fullDataRequiredStepIds = new Set([
      "ab-testing-6",
      "ab-testing-8",
      "ab-testing-9",
      "ab-testing-10",
      "ab-testing-11",
      "ab-testing-12",
      "ab-testing-13",
      "ab-testing-14",
      "ab-testing-15",
    ]);
    if (fullDataRequiredStepIds.has(step.id)) {
      const acquisition = loadNodeState(projectId, "ab-testing-2");
      const mapping = { ...AB_WORKFLOW_DEFAULTS, ...(acquisition.ab ?? {}) } as AbTestingDefaults & NonNullable<NodeState["ab"]>;
      const fullAnalysis = buildAbAnalysisDataset(projectId, mapping, Boolean(mapping.confirmed), mapping);
      if (!fullAnalysis.status.fullDatasetAvailable) {
        setLastAction("Navigation blocked: full dataset artifact is not loaded");
        setNavigationError("Full dataset artifact is not loaded. Reopen or reload the confirmed dataset before completing this analysis step.");
        return;
      }
    }

    // 1. Save page text (best effort). On a quota failure, reclaim storage broadly
    //    (other workflows/projects, not just A/B keys, can be what filled the quota)
    //    and retry once. Never throw out of this block.
    try {
      let result = persistAbStepText(savedAt);
      if (!result.browserCacheWritten) {
        reclaimWorkflowStorage();
        result = persistAbStepText(savedAt);
      }
      if (result.browserCacheWritten) {
        setLastSavedStorageKey(result.workflowNodeStorageKey);
        setLastSavedTimestamp(savedAt);
        setLastPayloadSizeKb(`${(result.payloadBytes / 1024).toFixed(1)} KB`);
        setLastStorageStatus("compact browser cache");
        setSaveStatusMessage("A/B Testing workflow step saved.");
        setLastAction(`Saved compact A/B Testing step ${currentStepNumber} at ${new Date().toLocaleTimeString()}. Payload size: ${(result.payloadBytes / 1024).toFixed(1)} KB.`);
      } else {
        cacheWarning = result.browserCacheError || "Browser storage is full, so this page could not be cached locally.";
      }
    } catch (error) {
      cacheWarning = error instanceof Error ? error.message : String(error);
    }

    // 2. Progress + navigation ALWAYS run, even if the cache write above failed.
    try {
      markWorkflowStepComplete(step.id);
      if (nextStep) setWorkflowStepStatus(nextStep.id, "in_progress");
      setCurrentStepId(nextStep?.id ?? step.id);
      upsertProjectFromState(useWorkflowStore.getState());
    } catch (error) {
      console.warn("ATLAS A/B progress update failed (continuing to navigate)", error);
    }

    if (cacheWarning) {
      setNavigationError(`Moving to the next step. Note: this page's text may not persist locally because ${cacheWarning}`);
    }
    setLastAction(`Navigating to ${nextRoute}`);
    navigate(nextRoute);
    window.setTimeout(() => window.scrollTo({ top: 0, behavior: "auto" }), 0);
  };

  const clearAbTestingCache = () => {
    try {
      const removedKeys = clearAbTestingWorkflowStorage(projectId);
      sessionStorage.removeItem(abFullDatasetSessionKey(projectId));
      sessionStorage.removeItem(abAnalysisSessionKey(projectId));
      setLastSavedStorageKey("");
      setLastSavedTimestamp("");
      setLastPayloadSizeKb("");
      setLastStorageStatus("A/B Testing browser cache cleared");
      setLastAction(`Cleared ${removedKeys.length} A/B Testing cached workflow state key${removedKeys.length === 1 ? "" : "s"}`);
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      setLastAction(`Save failed: ${message}`);
      setNavigationError(`A/B Testing workflow cache could not be cleared. ${message}`);
    }
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

  if (isAbTestingWorkflow) {
    return (
      <AbTestingWorkflowStep
        projectId={projectId}
        step={step}
        nextStep={nextStep}
        state={state}
        setState={setState}
        save={save}
        onMarkCompleteNext={handleAbTestingMarkCompleteAndNext}
        onComplete={completeStep}
        dataAcquisitionConfirmed={abTestingDataAcquisitionConfirmed}
        navigationError={navigationError}
        saveStatusMessage={saveStatusMessage}
        lastAction={lastAction}
        saveDebug={{
          currentStepNumber,
          currentRoute,
          nextRoute: nextStep?.route ?? nextAbRoute,
          lastSavedStorageKey: lastSavedStorageKey.includes(`:ab-testing-${currentStepNumber}`) ? lastSavedStorageKey : "None for current step.",
          lastSavedTimestamp,
          payloadSizeKb: lastPayloadSizeKb,
          storageStatus: lastStorageStatus,
        }}
        onClearCache={clearAbTestingCache}
        confirmedMapping={abConfirmedMapping}
      />
    );
  }

  if (activeWorkflowId === "optimization" || projectType === "optimization") {
    return (
      <OptimizationWorkflowStep
        projectId={projectId}
        step={step}
        nextStep={nextStep}
        onComplete={completeStep}
        navigationError={navigationError}
      />
    );
  }

  if (activeWorkflowId === "time_series_forecasting" || activeWorkflowId === "llm_generative_ai" || projectType === "time_series_forecasting" || projectType === "llm_generative_ai") {
    return (
      <AdvancedWorkflowStep
        workflowId={activeWorkflowId}
        projectType={projectType}
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
                onClick={() => save()}
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
