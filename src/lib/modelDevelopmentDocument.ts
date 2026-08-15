import { loadDecisionJournal, type DecisionJournalEntry } from "./decisionJournal";
import { loadExperiments, type ExperimentMetricSet, type ExperimentRecord } from "./experimentTracking";
import { buildGovernanceReport } from "./governanceReport";
import { sanitizeReportHtml } from "./htmlSanitizer";
import type { LocalDataset } from "./localDataset";
import { getNotebookSections } from "./notebookExport";
import { loadProjectContext, summarizeRegulatoryContext } from "./projectContext";
import { getProblemType, type AtlasProblemType } from "./problemType";
import { summarizeBureauHandling, treatmentLabels } from "./creditBureau";
import { loadBureauReviewState } from "./bureauDetection";
import { buildReportReadiness } from "./reportReadiness";
import { BRAND } from "../config/brand";
import {
  assertExactDatasetIdentity,
  requireLocalDatasetCanonicalIdentity,
  type CanonicalDatasetIdentity,
} from "./datasetIdentity";
import type { ExactPromotedModelIdentity } from "./implementationMonitoringIdentity";
import { resolveModelDocumentationChampion } from "./modelDocumentationChampion";
import {
  atlasReportStyles,
  decisionJournalTimelineHtml,
  objectTableHtml,
  professionalTableHtml,
  renderReportContentHtml,
} from "./reportFormatting";

export type ModelDevelopmentDocumentSection = {
  number: number;
  title: string;
  content: string;
};

export type ModelDevelopmentDocument = {
  title: string;
  generatedAt: string;
  fileBaseName: string;
  mode: ModelDevelopmentDocumentMode;
  sections: ModelDevelopmentDocumentSection[];
  markdown: string;
  html: string;
  wordHtml: string;
};

export type ModelDevelopmentDocumentMode = "executive" | "governance" | "technical";

export type ModelDevelopmentDocumentOptions = {
  includeFullDecisionJournalAppendix?: boolean;
  projectId?: string;
  authenticatedUserId?: string;
  dataset?: LocalDataset | null;
  datasetIdentity?: CanonicalDatasetIdentity | null;
  target?: string;
  promotedModelIdentity?: ExactPromotedModelIdentity | null;
};

function safe(value: unknown, fallback = "Not documented") {
  if (value === null || value === undefined || value === "") return fallback;
  return String(value);
}

function formatNumber(value: unknown, digits = 4) {
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric.toFixed(digits) : "-";
}

function escapeMarkdown(value: unknown) {
  return String(value ?? "")
    .replace(/\|/g, "\\|")
    .replace(/\n/g, " ");
}

function escapeHtml(value: unknown) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function compactFileName(value: string) {
  const compact = value
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 80);
  return compact || "model-development-document";
}

function recordValue(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function formatPolicyValue(value: unknown) {
  const record = recordValue(value);
  if (!record) return safe(value, "Not documented");
  return Object.entries(record)
    .map(([key, fieldValue]) => `${key}: ${safe(fieldValue, "-")}`)
    .join("; ");
}

type ExecutedPreparation = {
  outlierMethods: Record<string, unknown>;
  outlierGlobalMethod: string;
  outlierRationales: Record<string, string>;
  outlierAnalyticalTypes: Record<string, unknown>;
  missingPolicy: Record<string, unknown>;
  balanceMethod: string;
  splitStrategy: string;
  balanceRatio: string;
  executionLineage: Record<string, unknown>;
};

function summarizeMissingTreatment(stored: Record<string, unknown>) {
  const wrappedConfig = recordValue(stored.config);
  const config = wrappedConfig ?? stored;
  const activeTreatment = safe(
    stored.active_treatment ?? stored.default_strategy,
    "Not documented",
  ).toUpperCase();
  const explicitOverrideNames = Array.isArray(stored.overrideFeatures)
    ? stored.overrideFeatures.map(String)
    : Object.entries(config)
        .filter(([, value]) => {
          const rule = recordValue(value);
          return safe(rule?.strategy, "None") !== "None";
        })
        .map(([feature]) => feature);
  const overrideNames = [...new Set(explicitOverrideNames)].filter(
    (feature) => feature in config,
  );
  const result: Record<string, unknown> = {
    "Active treatment": activeTreatment,
    "Global strategy": wrappedConfig
      ? safe(stored.globalStrategy ?? stored.default_strategy, "None")
      : Object.keys(stored).length
        ? "Per-feature policy"
        : "Not documented",
    "Inherited predictors": Math.max(
      0,
      Object.keys(config).length - overrideNames.length,
    ),
    "Explicit overrides": overrideNames.length,
    "True-null cells": stored.true_null_cell_count ?? "Not documented",
    "Affected predictors": stored.affected_predictor_count ?? "Not documented",
    "Affected rows": stored.affected_row_count ?? "Not documented",
    "Materialization required": stored.materialization_required ?? "Not documented",
    "Processed frame created": stored.processed_frame_created ?? "Not documented",
  };
  if (activeTreatment === "NONE" && stored.zero_null_validated === true) {
    result["Estimator fit status"] = "No imputation estimator was fitted";
    result["Materialization status"] = "No processed frame was created";
  }
  if (safe(stored.globalStrategy, "") === "Constant") {
    result["Global constant"] = safe(
      stored.globalConstant,
      "Required but not documented",
    );
  }
  for (const feature of overrideNames) {
    result[`Override - ${feature}`] = formatPolicyValue(config[feature]);
  }
  return result;
}

function summarizeOutlierTreatment(
  preparation: ExecutedPreparation,
) {
  const methods = preparation.outlierMethods;
  const globalMethod = preparation.outlierGlobalMethod;
  const overrides = Object.entries(methods).filter(
    ([, method]) => safe(method, "USE_GLOBAL") !== "USE_GLOBAL",
  );
  const result: Record<string, unknown> = {
    "Global method": globalMethod,
    "Inherited predictors": Math.max(
      0,
      Object.keys(methods).length - overrides.length,
    ),
    "Explicit overrides": overrides.length,
    "Analytical type / eligibility": preparation.outlierAnalyticalTypes,
  };
  for (const [feature, method] of overrides) {
    result[`Override - ${feature}`] = safe(method);
    const rationale = preparation.outlierRationales[feature];
    if (rationale) {
      result[`Rationale - ${feature}`] = rationale;
    }
  }
  return result;
}

function isRegressionExperiment(experiment: ExperimentRecord) {
  const metricKeys = ["rmse", "mae", "mse", "r2", "adjusted_r2"] as const;
  return /regressor|linear regression|ridge|lasso/i.test(experiment.modelType) || metricKeys.some((key) => experiment.metrics[key] !== undefined);
}

function filterExperimentsForProblem(experiments: ExperimentRecord[], problemType: string) {
  const normalized = problemType.toLowerCase();
  if (normalized.includes("regression")) return experiments.filter(isRegressionExperiment);
  if (normalized.includes("classification")) return experiments.filter((experiment) => !isRegressionExperiment(experiment));
  return experiments;
}

function resolveDocumentDatasetIdentity(
  projectId: string,
  dataset: LocalDataset | null,
) {
  return requireLocalDatasetCanonicalIdentity(
    projectId,
    dataset,
    "Model Development Document dataset identity",
  );
}

function metricLines(metrics: ExperimentMetricSet | undefined, problemType: AtlasProblemType | string = "unknown") {
  if (!metrics) return "No model performance metrics captured.";
  const isRegression = String(problemType).toLowerCase() === "regression";
  const rows: [keyof ExperimentMetricSet, string, number][] = isRegression
    ? [
        ["rmse", "RMSE", 4],
        ["mae", "MAE", 4],
        ["mse", "MSE", 4],
        ["r2", "R-squared", 4],
        ["adjusted_r2", "Adjusted R-squared", 4],
      ]
    : [
        ["auc", "AUC", 4],
        ["pr_auc", "PR-AUC", 4],
        ["precision", "Precision", 4],
        ["recall", "Recall", 4],
        ["f1", "F1", 4],
        ["ks", "KS", 4],
        ["lift", "Lift", 2],
      ];
  const available = rows
    .filter(([key]) => metrics[key] !== undefined && metrics[key] !== null)
    .map(([key, label, digits]) => `- ${label}: ${formatNumber(metrics[key], digits)}`);
  if (!isRegression && metrics.calibration !== undefined) available.push(`- Calibration: ${safe(metrics.calibration)}`);
  return available.length ? available.join("\n") : "No model performance metrics captured.";
}

function formatCandidateModels(
  experiments: ExperimentRecord[],
  problemType: AtlasProblemType | string,
  promotedModel: ExactPromotedModelIdentity,
  supplementaryChampion: ExperimentRecord | null,
) {
  const isRegression = String(problemType).toLowerCase() === "regression";
  const candidateRows: Array<{ experiment: ExperimentRecord | null; champion: boolean }> = experiments.slice(0, 30).map((experiment) => ({
    experiment,
    champion: experiment === supplementaryChampion,
  }));
  if (!supplementaryChampion) {
    candidateRows.unshift({ experiment: null, champion: true });
  }
  if (isRegression) {
    return professionalTableHtml(
      ["Model", "Durable champion", "Model version", "RMSE", "MAE", "MSE", "R-squared", "Adjusted R-squared", "Runtime"],
      candidateRows.map(({ experiment, champion }) => [
        champion ? promotedModel.modelName : experiment?.modelType ?? "Unknown candidate",
        champion ? "Yes" : "No",
        champion ? promotedModel.modelVersionId : "-",
        formatNumber(experiment?.metrics.rmse),
        formatNumber(experiment?.metrics.mae),
        formatNumber(experiment?.metrics.mse),
        formatNumber(experiment?.metrics.r2),
        formatNumber(experiment?.metrics.adjusted_r2),
        experiment ? `${Math.round((experiment.runtimeMs ?? 0) / 1000)}s` : "-",
      ]),
      { wide: true, badgeColumns: ["Durable champion"] }
    );
  }
  return professionalTableHtml(
    ["Model", "Durable champion", "Model version", "AUC", "PR-AUC", "Precision", "Recall", "F1", "KS", "Lift", "Runtime"],
    candidateRows.map(({ experiment, champion }) => [
      champion ? promotedModel.modelName : experiment?.modelType ?? "Unknown candidate",
      champion ? "Yes" : "No",
      champion ? promotedModel.modelVersionId : "-",
      formatNumber(experiment?.metrics.auc),
      formatNumber(experiment?.metrics.pr_auc),
      formatNumber(experiment?.metrics.precision),
      formatNumber(experiment?.metrics.recall),
      formatNumber(experiment?.metrics.f1),
      formatNumber(experiment?.metrics.ks),
      formatNumber(experiment?.metrics.lift, 2),
      experiment ? `${Math.round((experiment.runtimeMs ?? 0) / 1000)}s` : "-",
    ]),
    { wide: true, badgeColumns: ["Durable champion"] }
  );
}

function formatFeatureImportance(champion: ExperimentRecord | null) {
  const rows = champion?.featureImportance?.slice(0, 20) ?? [];
  if (!rows.length) return "No project-scoped browser diagnostic matches the exact promoted model; use the durable evaluation and interpretation evidence package.";
  return professionalTableHtml(
    ["Feature", "Importance", "Direction", "Source"],
    rows.map((row) => [row.feature, formatNumber(row.importance), formatNumber(row.direction), row.source ?? "-"]),
    { compact: true }
  );
}

function formatDecisions(entries: DecisionJournalEntry[]) {
  return decisionJournalTimelineHtml(entries);
}

function materialDecisionArea(entry: DecisionJournalEntry) {
  const text = `${entry.workflowStep} ${entry.subject} ${entry.actionType}`.toLowerCase();
  if (/target/.test(text)) return "Target selected";
  if (/dataset|data acquisition|import/.test(text)) return "Dataset linked";
  if (/feature/.test(text)) return "Feature set finalized";
  if (/missing|outlier|preprocess/.test(text)) return "Preprocessing selected";
  if (/split|holdout|k-fold|kfold/.test(text)) return "Split selected";
  if (/model|train/.test(text)) return "Models trained";
  if (/champion/.test(text)) return "Champion selected";
  if (/final/.test(text)) return "Final model saved";
  if (/scor|stability/.test(text)) return "Scoring reviewed";
  if (/monitor/.test(text)) return "Monitoring plan selected";
  if (/implementation/.test(text)) return "Implementation readiness";
  return entry.subject || entry.workflowStep || "Material decision";
}

function formatMaterialDecisionTable(entries: DecisionJournalEntry[]) {
  if (!entries.length) {
    return "No material decision journal entries have been captured yet. Continue using workflow controls so champion selection, preprocessing, split, balancing, and final-model decisions are logged.";
  }
  return professionalTableHtml(
    ["Decision Area", "Final Decision", "Evidence", "Owner / Source", "Timestamp"],
    entries.slice(0, 15).map((entry) => [
      materialDecisionArea(entry),
      safe(entry.newValue, "Not documented"),
      safe(entry.systemRecommendation, "Captured from ATLAS workflow state"),
      entry.followStatus === "overrode" ? `User override: ${safe(entry.userReason, "No rationale captured")}` : "ATLAS workflow / Decision Journal",
      entry.timestamp,
    ]),
    { wide: true }
  );
}

const predictiveMaterialActionTypes = new Set<string>([
  "project_created",
  "project_context_updated",
  "target_variable_selected",
  "feature_inclusion_changed",
  "outlier_method_selected",
  "missing_value_strategy_selected",
  "balancing_method_selected",
  "split_strategy_selected",
  "model_selected",
  "models_trained",
  "champion_model_selected",
  "final_model_saved",
  "scoring_reviewed",
  "monitoring_plan_selected",
  "implementation_readiness_decision",
]);

function summarizeMaterialReportDecisions(entries: DecisionJournalEntry[], maxEntries = 15) {
  const excludedText = /autosave|save draft|page visit|visited|toggle testing|python smoke|run user python|copy code|expanded|collapsed/i;
  const excludedStep = /experimental design|monte carlo|anova|randomization|blocking|levels|factors|research question/i;
  const seen = new Set<string>();
  const summarized: DecisionJournalEntry[] = [];

  for (const entry of entries) {
    const actionType = String(entry.actionType ?? "");
    const workflowStep = String(entry.workflowStep ?? "");
    const subject = String(entry.subject ?? "");
    const combined = `${workflowStep} ${subject} ${entry.previousValue ?? ""} ${entry.newValue ?? ""} ${entry.userReason ?? ""}`;

    if (excludedStep.test(workflowStep) || excludedText.test(combined)) continue;
    if (!predictiveMaterialActionTypes.has(actionType) && !/target|feature|preprocess|outlier|missing|split|balance|train|champion|final model|scor|monitor|implementation/i.test(combined)) {
      continue;
    }

    const key = `${workflowStep.toLowerCase()}::${actionType.toLowerCase()}::${subject.toLowerCase()}`;
    if (seen.has(key)) continue;
    seen.add(key);
    summarized.push(entry);
    if (summarized.length >= maxEntries) break;
  }

  return summarized;
}

function collapsedAuditAppendix(entries: DecisionJournalEntry[]) {
  if (!entries.length) return "No decision journal entries have been captured.";
  return [
    '<details class="atlas-callout">',
    '<summary><strong>Full Audit Appendix</strong> - expand to review captured decision journal events.</summary>',
    '<div class="atlas-spacer"></div>',
    decisionJournalTimelineHtml(entries.slice(0, 100)),
    "</details>",
  ].join("\n");
}

function formatExperimentAppendix(experiments: ExperimentRecord[]) {
  if (!experiments.length) return "No experiment records have been captured.";
  return professionalTableHtml(
    ["Experiment ID", "Timestamp", "Model", "Champion", "Project ID", "Dataset ID", "Dataset Version ID", "Features", "Preprocessing", "Metrics", "Notes"],
    experiments.slice(0, 80).map((experiment) => [
      experiment.experimentId,
      experiment.timestamp,
      experiment.modelType,
      experiment.champion ? "Yes" : "No",
      experiment.project_id,
      experiment.dataset_id,
      experiment.dataset_version_id,
      experiment.selectedFeatures.length,
      [`Balancing: ${experiment.balancingMethod}`, `Split: ${experiment.splitStrategy}`].join("; "),
      metricLines(experiment.metrics, isRegressionExperiment(experiment) ? "regression" : "classification").replace(/\n/g, "; ").replace(/^- /g, ""),
      experiment.notes || "-",
    ]),
    { wide: true, badgeColumns: ["Champion"] }
  );
}

function formatBureauHandling() {
  const summary = summarizeBureauHandling();
  const governedReview = loadBureauReviewState();
  if (
    !summary.profiles.length &&
    !summary.decisions.length &&
    !governedReview.variableDefaults.length &&
    !governedReview.decisions.length
  ) {
    return "No credit bureau special value profiles or treatment decisions have been captured.";
  }

  const decisionByKey = new Map(summary.decisions.map((decision) => [`${decision.variableName}::${decision.value}`, decision]));
  const rows = summary.profiles.slice(0, 100).map((profile) => {
    const decision = decisionByKey.get(`${profile.variableName}::${profile.value}`);
    return [
      escapeMarkdown(profile.variableName),
      escapeMarkdown(profile.value),
      escapeMarkdown(profile.label),
      `${profile.count}`,
      formatNumber(profile.percent * 100, 2) + "%",
      formatNumber(profile.eventRate),
      formatNumber(profile.regularEventRate),
      escapeMarkdown(treatmentLabels[decision?.treatment ?? profile.recommendedTreatment]),
      escapeMarkdown(decision?.rationale || profile.recommendationReason),
    ].join(" | ").replace(/^/, "| ").replace(/$/, " |");
  });

  const governedHandlingLabels: Record<string, string> = {
    preserve_informative: "Leave value unchanged (governed special code)",
    convert_to_missing: "Treat as missing for imputation",
    convert_to_category: "Create special-value indicator (dummy variable)",
    documented_domain_mapping: "Impute with a valid governed value",
    exclude_variable: "Exclude feature from modeling",
    leave_unchanged: "Leave value unchanged",
    custom: "Custom treatment (requires rationale)",
  };
  const governedRows = [
    ...governedReview.variableDefaults.map((decision) => [
      decision.variable,
      "Variable default",
      governedHandlingLabels[decision.handling] ?? decision.handling,
      decision.rationale || "Governed variable-level policy",
      decision.updatedAt,
    ]),
    ...governedReview.decisions.map((decision) => [
      decision.variable,
      `Override: ${decision.value}`,
      governedHandlingLabels[decision.handling] ?? decision.handling,
      decision.rationale || "Rationale required",
      decision.updatedAt,
    ]),
  ];

  return [
    `Detected profiles: ${summary.profiles.length}`,
    `Documented treatment decisions: ${summary.decisions.length}`,
    `Governed review status: ${governedReview.status}`,
    `Evidence status: ${governedReview.evidenceStatus}`,
    "",
    "| Variable | Value | Bureau Definition | Count | Percent | Special Event Rate | Regular Event Rate | Treatment | Rationale |",
    "|---|---|---|---:|---:|---:|---:|---|---|",
    ...rows,
    "",
    professionalTableHtml(
      ["Variable", "Policy scope", "Handling", "Rationale", "Updated"],
      governedRows,
      { wide: true, badgeColumns: ["Policy scope"] },
    ),
  ].join("\n");
}

function formatPythonAppendix() {
  const sections = getNotebookSections();
  const sectionList = sections.map((section, index) => `${index + 1}. ${section.title}`).join("\n");
  return [
    "The notebook export reproduces the visual workflow with markdown explanations, generated Python code, user-edited Python code where captured, output placeholders, and decision journal notes.",
    "",
    "Notebook sections:",
    sectionList || "No notebook sections generated.",
  ].join("\n");
}

function formatConfusionOrResidual(champion: ExperimentRecord | null) {
  if (!champion) return "No project-scoped browser diagnostic matches the exact promoted model; use its durable evaluation package for performance evidence.";
  if (champion.confusionMatrix?.length) {
    const matrix = champion.confusionMatrix;
    const tn = matrix[0]?.[0] ?? 0;
    const fp = matrix[0]?.[1] ?? 0;
    const fn = matrix[1]?.[0] ?? 0;
    const tp = matrix[1]?.[1] ?? 0;
    return [
      "| Actual / Predicted | Predicted 0 | Predicted 1 |",
      "|---|---:|---:|",
      `| Actual 0 | ${tn} | ${fp} |`,
      `| Actual 1 | ${fn} | ${tp} |`,
    ].join("\n");
  }
  return "For regression models, confusion matrix, ROC, and PR curves are not applicable. Use residual diagnostics, RMSE, MAE, MSE, R-squared, adjusted R-squared, prediction stability, and actual-versus-predicted plots.";
}

function buildSections(
  mode: ModelDevelopmentDocumentMode,
  options: ModelDevelopmentDocumentOptions = {}
): ModelDevelopmentDocumentSection[] {
  const projectId = String(options.projectId ?? "").trim();
  const authenticatedUserId = String(options.authenticatedUserId ?? "").trim();
  const dataset = options.dataset ?? null;
  if (!projectId || !authenticatedUserId || !dataset || !options.datasetIdentity) {
    throw new Error(
      "Model Development Documentation requires an authenticated project-scoped dataset context.",
    );
  }
  const context = loadProjectContext(projectId, authenticatedUserId);
  const datasetIdentity = resolveDocumentDatasetIdentity(projectId, dataset);
  assertExactDatasetIdentity(
    options.datasetIdentity,
    datasetIdentity,
    "Model Development Document project-scoped dataset identity",
  );
  const problemType = getProblemType(context, dataset);
  const experiments = filterExperimentsForProblem(
    loadExperiments(datasetIdentity),
    String(problemType),
  );
  const championResolution = resolveModelDocumentationChampion({
    projectId,
    datasetIdentity,
    target: options.target ?? dataset.target ?? "",
    promotedModelIdentity: options.promotedModelIdentity ?? null,
    experiments,
  });
  if (!championResolution.ready || !championResolution.identity) {
    throw new Error(championResolution.error || "The exact promoted champion is unavailable.");
  }
  const promotedChampion = championResolution.identity;
  const champion = championResolution.supplementaryExperiment;
  const executedSteps = recordValue(champion?.preprocessingSteps);
  if (
    !executedSteps ||
    executedSteps.authority !== "backend_governed_training_execution" ||
    Number(executedSteps.preprocessingContractVersion ?? 0) !== 2
  ) {
    throw new Error(
      "Model Development Documentation requires the backend-executed preprocessing v2 lineage for the exact champion.",
    );
  }
  const outlierPolicy = recordValue(executedSteps.outlierPolicy) ?? {};
  const missingPolicy = recordValue(executedSteps.missingPolicy) ?? {};
  const validationExecutionPolicy =
    recordValue(executedSteps.validationExecutionPolicy) ?? {};
  const modelGovernedPreprocessing =
    recordValue(executedSteps.modelGovernedPreprocessing) ?? {};
  const foldLocalExecution =
    recordValue(executedSteps.foldLocalExecution) ?? {};
  const outlierConfig = recordValue(outlierPolicy.config) ?? {};
  const rationaleRecord = recordValue(outlierPolicy.rationales) ?? {};
  const preparation: ExecutedPreparation = {
    outlierMethods: outlierConfig,
    outlierGlobalMethod: safe(outlierPolicy.global_method, "NONE"),
    outlierRationales: Object.fromEntries(
      Object.entries(rationaleRecord).map(([key, value]) => [key, String(value ?? "")]),
    ),
    outlierAnalyticalTypes:
      recordValue(outlierPolicy.analytical_types) ?? {},
    missingPolicy,
    balanceMethod: safe(
      validationExecutionPolicy.balancing_method,
      "none",
    ),
    splitStrategy: "Sealed Analysis Partition with approved Validation Design",
    balanceRatio: safe(
      validationExecutionPolicy.minority_share,
      "Not applicable",
    ),
    executionLineage: {
      Authority: executedSteps.authority,
      "Preprocessing contract version": executedSteps.preprocessingContractVersion,
      "Preprocessing policy ID": executedSteps.preprocessingPolicyId,
      "Preprocessing policy revision": executedSteps.preprocessingPolicyRevision,
      "Preprocessing policy hash": executedSteps.preprocessingPolicyHash,
      "Fold-local training execution": foldLocalExecution,
      "Candidate/model preprocessing execution": modelGovernedPreprocessing,
      "Final holdout parameter influence": false,
    },
  };
  const decisions = loadDecisionJournal();
  const materialDecisions = summarizeMaterialReportDecisions(decisions);
  const readiness = buildReportReadiness({
    problemType: String(problemType),
    experiments,
    champion,
    promotedChampion,
    decisions,
    dataset,
    context,
  });
  const governance = buildGovernanceReport();
  const missingStrategies = summarizeMissingTreatment(
    preparation.missingPolicy,
  );
  const outlierMethods = summarizeOutlierTreatment(preparation);
  const balanceMethod = preparation.balanceMethod;
  const splitStrategy = preparation.splitStrategy;
  const balanceRatio = preparation.balanceRatio;
  const selectedFeatures = dataset?.selected_columns ?? [];
  const dataAccess = dataset?.data_access ?? null;
  const dataQuality = dataset?.data_quality ?? null;

  const sections: Omit<ModelDevelopmentDocumentSection, "number">[] = [
    {
      title: "Cover Page",
      content: [
        `Model ID #: ${safe(context.modelId, "Required but not documented")}`,
        `Project: ${safe(context.projectName, "Untitled model development project")}`,
        `Model name: ${promotedChampion.modelName}`,
        `Model owner: ${safe(context.implementationOwner)}`,
        `Generated: ${new Date().toISOString()}`,
        "Version: Draft 1.0",
        `Development environment: ${BRAND.productName} local workbench`,
        `Prepared for: Consumer Lending AI/ML model development`,
        `Document type: Model Development Document`,
        `Project ID: ${safe(projectId)}`,
        `Dataset ID: ${safe(datasetIdentity?.dataset_id)}`,
        `Dataset version: ${safe(datasetIdentity?.dataset_version_id)}`,
        `Final model ID: ${promotedChampion.modelId}`,
        `Final model version ID: ${promotedChampion.modelVersionId}`,
        `Final candidate ID: ${promotedChampion.candidateId}`,
        `Final training run ID: ${promotedChampion.trainingRunId}`,
        `Problem type: ${safe(problemType)}`,
        `Champion model: ${promotedChampion.modelName}`,
      ].join("\n"),
    },
    {
      title: "Executive Summary",
      content: [
        `Business objective: ${safe(context.businessObjective)}`,
        `Target: ${safe(dataset?.target)}`,
        `Rows in browser sample: ${dataset?.rows.length ?? 0}`,
        `Selected features: ${selectedFeatures.length}`,
        `Champion model: ${promotedChampion.modelName}`,
        `Final model version ID: ${promotedChampion.modelVersionId}`,
        `Final candidate ID: ${promotedChampion.candidateId}`,
        `Final training run ID: ${promotedChampion.trainingRunId}`,
        `Dataset ID: ${safe(datasetIdentity?.dataset_id)}`,
        `Dataset version: ${safe(datasetIdentity?.dataset_version_id)}`,
        `Primary success metric: ${safe(context.primarySuccessMetric)}`,
        "",
        metricLines(champion?.metrics, problemType),
      ].join("\n"),
    },
    {
      title: "Report Readiness Checklist",
      content: [
        readiness.ready
          ? "All core evidence needed for a model development document is present."
          : "The report can be generated, but missing evidence should be resolved before validation approval.",
        "",
        professionalTableHtml(
          ["Evidence Area", "Status", "Notes"],
          readiness.checklist.map((item) => [item.item, item.status, item.evidence]),
          { badgeColumns: ["Status"] }
        ),
        readiness.missingEvidence.length ? `Missing evidence:\n${readiness.missingEvidence.map((item) => `- ${item}`).join("\n")}` : "",
      ].filter(Boolean).join("\n"),
    },
    ...(mode === "executive"
      ? []
      : [
          {
            title: "Material Decision Summary",
            content: formatMaterialDecisionTable(materialDecisions),
          },
        ]),
    {
      title: "Business Context",
      content: [
        `Model type: ${safe(context.modelType)}`,
        `Intended use: ${safe(context.intendedModelUse)}`,
        `Deployment expectation: ${safe(context.deploymentExpectation)}`,
        `Implementation environment: ${safe(context.implementationEnvironment)}`,
        `Target implementation date: ${safe(context.implementationTargetDate)}`,
        `Interpretability requirement: ${safe(context.interpretabilityRequirement)}`,
        `Regulatory environment: ${summarizeRegulatoryContext(context)}`,
        `${problemType === "regression" ? "Overprediction cost" : "False positive cost"}: ${safe(context.falsePositiveCost)}`,
        `${problemType === "regression" ? "Underprediction cost" : "False negative cost"}: ${safe(context.falseNegativeCost)}`,
      ].join("\n"),
    },
    {
      title: "Model Implementation",
      content: [
        `Implementation owner: ${safe(context.implementationOwner)}`,
        `Target implementation date: ${safe(context.implementationTargetDate)}`,
        `Implementation environment: ${safe(context.implementationEnvironment)}`,
        `Implementation notes: ${safe(context.implementationNotes)}`,
      ].join("\n"),
    },
    {
      title: "Data Description",
      content: [
        `Primary source: ${safe(dataAccess?.sourceLabel, "Uploaded dataset in the modeling workbench")}`,
        `Source type: ${safe(dataAccess?.sourceType)}`,
        `Connection: ${safe(dataAccess?.connectionName)}`,
        `Database: ${safe(dataAccess?.database)}`,
        `Schema: ${safe(dataAccess?.schema)}`,
        `SQL query: ${safe(dataAccess?.sqlQuery)}`,
        `Import date: ${safe(dataAccess?.importedAt)}`,
        `Dataset ID: ${safe(datasetIdentity?.dataset_id)}`,
        `Dataset Library ID: ${safe(datasetIdentity?.dataset_id)}`,
        `Dataset Library version: ${safe(datasetIdentity?.dataset_version_id)}`,
        `Dataset Library name: ${safe(dataset?.dataset_library?.datasetName)}`,
        `Dataset Library role: ${safe(dataset?.dataset_library?.datasetRole)}`,
        `Dataset version: ${safe(datasetIdentity?.dataset_version_id)}`,
        `Access metadata ID: ${safe(dataAccess?.accessMetadataId)}`,
        `Dataset hash: ${safe(dataAccess?.hash)}`,
        `Sampling approach: ${safe(dataAccess?.samplingMethod)} ${safe(dataAccess?.samplingDetail, "")}`,
        `Population definition: ${safe(context.populationDefinition)}`,
        `Observation window: ${safe(context.observationWindow)}`,
        `Performance window: ${safe(context.performanceWindow)}`,
        `Columns: ${dataset?.headers.length ?? 0}`,
        `Selected feature list: ${selectedFeatures.length ? selectedFeatures.join(", ") : "Not documented"}`,
        "",
        "Data lineage:",
        dataAccess?.lineage?.length ? dataAccess.lineage.map((item) => `- ${item}`).join("\n") : "Not documented",
        "",
        "Data quality summary:",
        dataQuality
          ? [
              dataQuality.duplicateContract
                ? `- Exact duplicates: ${dataQuality.duplicateContract.redundant_duplicate_rows} redundant rows beyond the retained ${dataQuality.duplicateContract.keep_semantics} occurrence; ${dataQuality.duplicateContract.duplicate_participant_rows} participant rows across ${dataQuality.duplicateContract.duplicate_group_count} groups; scope ${dataQuality.duplicateContract.scope}; target ${dataQuality.duplicateContract.target_included ? "included" : "excluded"}.`
                : `- Exact duplicates: backend definition unavailable; browser value ${dataQuality.duplicateRows} is non-authoritative.`,
              `- Constant columns: ${dataQuality.constantColumns.join(", ") || "None detected"}`,
              `- Potential leakage columns: ${dataQuality.potentialLeakageColumns.join(", ") || "None detected"}`,
              `- High missing fields: ${dataQuality.missing.slice(0, 5).map((row) => `${row.column} ${formatNumber(row.percent * 100, 2)}%`).join(", ") || "None detected"}`,
            ].join("\n")
          : "Not documented",
      ].join("\n"),
    },
    { title: "Credit Bureau Data Handling", content: formatBureauHandling() },
    {
      title: "EDA",
      content:
        "Exploratory analysis is captured in the workbench EDA page and notebook export. Review target distribution, variable summary, pairwise plots, correlations, and any fields with unusual distributions before final validation.",
    },
    { title: "Missing Value Treatment", content: objectTableHtml(missingStrategies, "No missing value strategy captured.") },
    { title: "Outlier Treatment", content: objectTableHtml(outlierMethods, "No outlier strategy captured.") },
    {
      title: "Preprocessing Execution and Holdout Isolation",
      content: objectTableHtml(
        preparation.executionLineage,
        "No backend-governed preprocessing execution lineage was captured.",
      ),
    },
    {
      title: "Feature Engineering",
      content:
        "Feature engineering selections are captured in the workflow state and decision journal. Review generated variables, scaling, encodings, interactions, bins, and rule-based categorical features in the notebook export.",
    },
    {
      title: "Train/Test and Balancing Strategy",
      content: [
        `Split strategy: ${safe(splitStrategy)}`,
        problemType === "regression" ? "Balancing method: Not applicable for continuous-target regression." : `Balancing method: ${safe(balanceMethod)}`,
        problemType === "regression" ? "Balance ratio: Not applicable for continuous-target regression." : `Balance ratio: ${safe(balanceRatio, "Not documented or not applicable")}`,
      ].join("\n"),
    },
    {
      title: "Candidate Models",
      content: formatCandidateModels(
        experiments,
        problemType,
        promotedChampion,
        champion,
      ),
    },
    { title: "Model Performance", content: metricLines(champion?.metrics, problemType) },
    {
      title: "Model Interpretation",
      content: [
        "Feature importance and SHAP-style summaries are appropriate for both classification and regression when interpreted as model behavior evidence, not causal proof.",
        /linear regression/i.test(promotedChampion.modelName)
          ? "Linear Regression champion: include the coefficient table, coefficient-weight chart, intercept, and any preprocessing assumptions in the validation package. ATLAS does not report p-values unless a statistical inference estimator provides them."
          : "",
        /decision tree regressor/i.test(promotedChampion.modelName)
          ? "Decision Tree Regressor champion: include the rule table, root split, terminal leaves, tree depth, and most important decision paths in the validation package."
          : "",
        "",
        formatFeatureImportance(champion),
      ].filter(Boolean).join("\n"),
    },
    {
      title: "Model Selection Rationale",
      content: [
        `Champion model: ${promotedChampion.modelName}`,
        `Durable model version: ${promotedChampion.modelVersionId}`,
        `Exact candidate: ${promotedChampion.candidateId}`,
        `Exact training run: ${promotedChampion.trainingRunId}`,
        "Document the reason this champion is preferred, including performance, interpretability, operational constraints, policy needs, and validation readiness.",
        "",
        formatConfusionOrResidual(champion),
      ].join("\n"),
    },
    {
      title: "Limitations and Risks",
      content: [
        "Document known limitations before model validation.",
        "- Potential data drift or population drift between development and production.",
        "- Proxy, fairness, or adverse-action concerns for regulated lending use cases.",
        "- Stability of special credit bureau values and missingness patterns over time.",
        "- Calibration and threshold risk if the training sample was balanced.",
      ].join("\n"),
    },
    {
      title: "Monitoring Recommendations",
      content: [
        `Monitoring cadence: ${
          context.monitoringCadence === "custom"
            ? safe(context.monitoringCadenceCustom, "Custom cadence not documented")
            : safe(context.monitoringCadence)
        }`,
        `Selected monitoring metrics: ${context.monitoringMetrics.length ? context.monitoringMetrics.join(", ") : "Not selected"}`,
        `Monitoring notes: ${safe(context.monitoringNotes)}`,
        "",
        "Recommended monitoring:",
        "- Score distribution PSI and feature VSI by production batch.",
        "- Data-quality monitoring for missing, special bureau, and out-of-range values.",
        "- Performance monitoring against actual outcomes when available.",
        "- Fair lending and reason-code review when applicable.",
        "- Champion/challenger review cadence aligned to governance requirements.",
      ].join("\n"),
    },
  ];

  if (mode === "governance") {
    sections.push({
      title: "Decision Journal Appendix",
      content: formatMaterialDecisionTable(materialDecisions),
    });
    sections.push({ title: "Experiment Appendix", content: formatExperimentAppendix(experiments) });
  }

  if (mode === "technical") {
    if (options.includeFullDecisionJournalAppendix) {
      sections.push({ title: "Full Audit Appendix", content: collapsedAuditAppendix(decisions) });
    }
    sections.push({ title: "Experiment Appendix", content: formatExperimentAppendix(experiments) });
    sections.push({
      title: "Python / Reproducibility Appendix",
      content: [formatPythonAppendix(), "", "Governance report sections generated in parallel:", governance.sections.map((section) => `- ${section.number}. ${section.title}`).join("\n")].join("\n"),
    });
  }

  return sections.map((section, index) => ({ ...section, number: index + 1 }));
}

function renderMarkdown(title: string, generatedAt: string, sections: ModelDevelopmentDocumentSection[]) {
  return [
    `# ${BRAND.productName}`,
    "",
    `## ${BRAND.productSubtitle}`,
    "",
    BRAND.shortDescription,
    "",
    `### ${title}`,
    "",
    `Generated: ${generatedAt}`,
    "",
    `<style>${atlasReportStyles()}</style>`,
    "",
    ...sections.flatMap((section) => [`## ${section.number}. ${section.title}`, "", renderReportContentHtml(section.content), ""]),
  ].join("\n");
}

function renderHtml(title: string, generatedAt: string, sections: ModelDevelopmentDocumentSection[]) {
  const body = sections
    .map(
      (section) => `
        <section>
          <h2>${section.number}. ${escapeHtml(section.title)}</h2>
          ${renderReportContentHtml(section.content)}
        </section>`
    )
    .join("\n");
  return sanitizeReportHtml(`<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <title>${escapeHtml(title)}</title>
  <style>
    body { background: #f8fafc; margin: 36px; }
    ${atlasReportStyles()}
  </style>
</head>
<body>
<main class="atlas-report">
  <h1>${escapeHtml(BRAND.productName)}</h1>
  <p><strong>${escapeHtml(BRAND.productSubtitle)}</strong></p>
  <p>${escapeHtml(BRAND.shortDescription)}</p>
  <h2>${escapeHtml(title)}</h2>
  <p>Generated: ${escapeHtml(generatedAt)}</p>
  ${body}
</main>
</body>
</html>`);
}

export function buildModelDevelopmentDocument(
  mode: ModelDevelopmentDocumentMode = "governance",
  options: ModelDevelopmentDocumentOptions = {}
): ModelDevelopmentDocument {
  const context = loadProjectContext(
    String(options.projectId ?? "").trim(),
    String(options.authenticatedUserId ?? "").trim(),
  );
  const generatedAt = new Date().toISOString();
  const title = `${safe(context.projectName, "Model")} Model Development Document`;
  const sections = buildSections(mode, options);
  const markdown = renderMarkdown(title, generatedAt, sections);
  const html = renderHtml(title, generatedAt, sections);

  return {
    title,
    generatedAt,
    fileBaseName: compactFileName(`${title}-${mode}`),
    mode,
    sections,
    markdown,
    html,
    wordHtml: html,
  };
}
