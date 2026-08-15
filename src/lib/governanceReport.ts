import { loadDecisionJournal, type DecisionJournalEntry } from "./decisionJournal";
import { loadExperiments, type ExperimentRecord, type ExperimentMetricSet } from "./experimentTracking";
import { loadLocalDataset } from "./localDataset";
import { loadProjectContext, summarizeRegulatoryContext } from "./projectContext";
import { getProblemType, type AtlasProblemType } from "./problemType";
import { BRAND } from "../config/brand";
import { getWorkflowDefinition } from "../config/workflows";
import { useWorkflowStore } from "../state/useWorkflowStore";
import { loadWorkflowNodeEvidence, summarizeWorkflowNodeEvidence } from "./workflowNodeEvidence";
import { buildExperimentalDesignAnalysis, type ExperimentalDesignNodeState } from "./experimentalDesign";
import {
  requireLocalDatasetCanonicalIdentity,
} from "./datasetIdentity";
import {
  atlasReportStyles,
  decisionJournalTimelineHtml,
  objectTableHtml,
  professionalTableHtml,
  renderReportContentHtml,
  sectionSummaryHtml,
} from "./reportFormatting";

export type GovernanceSection = {
  number: number;
  title: string;
  content: string;
};

export type GovernanceReport = {
  title: string;
  generatedAt: string;
  fileBaseName: string;
  sections: GovernanceSection[];
  markdown: string;
  html: string;
  wordHtml: string;
};

function safe(value: unknown, fallback = "Not documented") {
  if (value === null || value === undefined || value === "") return fallback;
  return String(value);
}

function recordValue(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function backendExecutedPreparation(champion: ExperimentRecord | null) {
  const steps = recordValue(champion?.preprocessingSteps);
  const exact = Boolean(
    steps &&
      steps.authority === "backend_governed_training_execution" &&
      Number(steps.preprocessingContractVersion ?? 0) === 2 &&
      String(steps.preprocessingPolicyId ?? "").trim() &&
      String(steps.preprocessingPolicyHash ?? "").trim(),
  );
  if (!exact || !steps) {
    const unavailable = {
      "Execution status":
        "Unavailable — no exact backend-governed preprocessing v2 execution is linked to the champion.",
    };
    return {
      status: "unavailable",
      missingStrategies: unavailable,
      outlierMethods: unavailable,
      balanceMethod: "Not available from backend execution lineage",
      balanceRatio: "Not available from backend execution lineage",
      splitStrategy: "Not available from backend execution lineage",
      kFolds: "",
      lineage: unavailable,
    };
  }

  const outlierPolicy = recordValue(steps.outlierPolicy) ?? {};
  const missingPolicy = recordValue(steps.missingPolicy) ?? {};
  const validation = recordValue(steps.validationExecutionPolicy) ?? {};
  const modelExecution = recordValue(steps.modelGovernedPreprocessing) ?? {};
  const foldExecution = recordValue(steps.foldLocalExecution) ?? {};
  return {
    status: "exact_backend_execution",
    missingStrategies: missingPolicy,
    outlierMethods: {
      "Global method": safe(outlierPolicy.global_method, "NONE"),
      "Feature methods": recordValue(outlierPolicy.config) ?? {},
      "Analytical types": recordValue(outlierPolicy.analytical_types) ?? {},
      "Override rationales": recordValue(outlierPolicy.rationales) ?? {},
    },
    balanceMethod: safe(validation.balancing_method, "none"),
    balanceRatio: safe(validation.minority_share, "Not applicable"),
    splitStrategy: "Sealed Analysis Partition with approved Validation Design",
    kFolds: safe(
      foldExecution.governed_fold_count ?? validation.fold_count,
      "",
    ),
    lineage: {
      Authority: steps.authority,
      "Preprocessing contract version": steps.preprocessingContractVersion,
      "Preprocessing policy ID": steps.preprocessingPolicyId,
      "Preprocessing policy revision": steps.preprocessingPolicyRevision,
      "Preprocessing policy hash": steps.preprocessingPolicyHash,
      "Fold-local execution": foldExecution,
      "Model preprocessing execution": modelExecution,
    },
  };
}

function formatNumber(value: unknown, digits = 4) {
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric.toFixed(digits) : "-";
}

function formatList(items: string[], fallback = "None documented") {
  const clean = items.map((item) => item.trim()).filter(Boolean);
  if (!clean.length) return fallback;
  return clean.map((item) => `- ${item}`).join("\n");
}

function formatObject(value: unknown, fallback = "None documented") {
  return objectTableHtml(value, fallback);
}

function selectChampion(experiments: ExperimentRecord[]) {
  return experiments.find((experiment) => experiment.champion) ?? null;
}

function isRegressionExperiment(experiment: ExperimentRecord) {
  return /regressor|linear regression|ridge|lasso/i.test(experiment.modelType) ||
    ["rmse", "mae", "mse", "r2", "adjusted_r2"].some((key) => experiment.metrics[key as keyof ExperimentMetricSet] !== undefined);
}

function filterExperimentsForProblem(experiments: ExperimentRecord[], problemType: AtlasProblemType | string) {
  return String(problemType).toLowerCase() === "regression"
    ? experiments.filter(isRegressionExperiment)
    : experiments.filter((experiment) => !isRegressionExperiment(experiment));
}

function resolveGovernanceDatasetIdentity(
  projectId: string,
  dataset: ReturnType<typeof loadLocalDataset>,
) {
  return requireLocalDatasetCanonicalIdentity(
    projectId,
    dataset,
    "Governance report dataset identity",
  );
}

function metricLines(metrics: ExperimentMetricSet | undefined, problemType: AtlasProblemType | string = "unknown") {
  if (!metrics) return "No performance metrics captured.";
  const isRegression = String(problemType).toLowerCase() === "regression";
  const labels: [keyof ExperimentMetricSet, string, number][] = isRegression
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
  const rows = labels
    .filter(([key]) => metrics[key] !== undefined && metrics[key] !== null)
    .map(([key, label, digits]) => `- ${label}: ${formatNumber(metrics[key], digits)}`);
  if (metrics.calibration !== undefined) rows.push(`- Calibration: ${safe(metrics.calibration)}`);
  return rows.length ? rows.join("\n") : "No performance metrics captured.";
}

function formatConfusionMatrix(matrix: number[][] | undefined) {
  if (!matrix?.length) return "No confusion matrix captured. This is expected for regression models.";
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

function formatCurveSummary(champion: ExperimentRecord | null) {
  if (!champion) return "No champion experiment selected.";
  const isClassification = champion.metrics.auc !== undefined || champion.rocData || champion.prData;
  if (!isClassification) return "ROC and PR summaries are not applicable to regression models.";
  return [
    `- ROC-AUC: ${formatNumber(champion.metrics.auc)}`,
    `- PR-AUC: ${formatNumber(champion.metrics.pr_auc)}`,
    `- KS: ${formatNumber(champion.metrics.ks)}`,
    `- ROC points captured: ${champion.rocData?.fpr?.length ?? 0}`,
    `- PR points captured: ${champion.prData?.precision?.length ?? 0}`,
  ].join("\n");
}

function formatFeatureImportance(champion: ExperimentRecord | null) {
  const rows = champion?.featureImportance?.slice(0, 20) ?? [];
  if (!rows.length) return "No feature importance was captured for the champion experiment.";
  return professionalTableHtml(
    ["Feature", "Importance", "Direction", "Source"],
    rows.map((row) => [row.feature, formatNumber(row.importance), formatNumber(row.direction), row.source ?? "-"]),
    { compact: true }
  );
}

function formatCandidateModels(experiments: ExperimentRecord[], problemType: AtlasProblemType | string) {
  if (!experiments.length) return "No model experiments captured.";
  const isRegression = String(problemType).toLowerCase() === "regression";
  if (isRegression) {
    return professionalTableHtml(
      ["Model", "Champion", "RMSE", "MAE", "MSE", "R-squared", "Adjusted R-squared", "Runtime"],
      experiments.slice(0, 25).map((experiment) => [
        experiment.modelType,
        experiment.champion ? "Yes" : "No",
        formatNumber(experiment.metrics.rmse),
        formatNumber(experiment.metrics.mae),
        formatNumber(experiment.metrics.mse),
        formatNumber(experiment.metrics.r2),
        formatNumber(experiment.metrics.adjusted_r2),
        `${Math.round(experiment.runtimeMs / 1000)}s`,
      ]),
      { wide: true, badgeColumns: ["Champion"] }
    );
  }
  return professionalTableHtml(
    ["Model", "Champion", "AUC", "PR-AUC", "Precision", "Recall", "F1", "KS", "Lift", "Runtime"],
    experiments.slice(0, 25).map((experiment) => [
      experiment.modelType,
      experiment.champion ? "Yes" : "No",
      formatNumber(experiment.metrics.auc),
      formatNumber(experiment.metrics.pr_auc),
      formatNumber(experiment.metrics.precision),
      formatNumber(experiment.metrics.recall),
      formatNumber(experiment.metrics.f1),
      formatNumber(experiment.metrics.ks),
      formatNumber(experiment.metrics.lift, 2),
      `${Math.round(experiment.runtimeMs / 1000)}s`,
    ]),
    { wide: true, badgeColumns: ["Champion"] }
  );
}

function formatDecisionAppendix(entries: DecisionJournalEntry[]) {
  return decisionJournalTimelineHtml(entries);
}

function formatExperimentAppendix(experiments: ExperimentRecord[]) {
  if (!experiments.length) return "No experiment records captured.";
  return professionalTableHtml(
    ["Experiment ID", "Timestamp", "Model", "Champion", "Project ID", "Dataset ID", "Dataset Version ID", "Features", "Balancing", "Split Strategy", "Notes"],
    experiments.slice(0, 50).map((experiment) => [
      experiment.experimentId,
      experiment.timestamp,
      experiment.modelType,
      experiment.champion ? "Yes" : "No",
      experiment.project_id,
      experiment.dataset_id,
      experiment.dataset_version_id,
      experiment.selectedFeatures.length,
      experiment.balancingMethod,
      experiment.splitStrategy,
      experiment.notes || "-",
    ]),
    { wide: true, badgeColumns: ["Champion"] }
  );
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
  return value
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 80);
}

function buildSections(): GovernanceSection[] {
  const context = loadProjectContext();
  const dataset = loadLocalDataset();
  const projectId = useWorkflowStore.getState().projectId;
  const datasetIdentity = resolveGovernanceDatasetIdentity(projectId, dataset);
  const problemType = getProblemType(context, dataset);
  const experiments = filterExperimentsForProblem(
    loadExperiments(datasetIdentity),
    problemType,
  );
  const decisions = loadDecisionJournal();
  const champion = selectChampion(experiments);
  const preparation = backendExecutedPreparation(champion);
  const missingStrategies = preparation.missingStrategies;
  const outlierMethods = preparation.outlierMethods;
  const balanceMethod = preparation.balanceMethod;
  const balanceRatio = preparation.balanceRatio;
  const splitStrategy = preparation.splitStrategy;
  const kFolds = preparation.kFolds;
  const dataAccess = dataset?.data_access ?? null;
  const dataQuality = dataset?.data_quality ?? null;
  const excludedFeatures = decisions
    .filter((entry) => entry.actionType === "feature_inclusion_changed" && /false|exclude|removed|no/i.test(entry.newValue))
    .map((entry) => entry.subject);

  const sections: Omit<GovernanceSection, "number">[] = [
    {
      title: "Executive Summary",
      content: [
        `Model ID #: ${safe(context.modelId, "Required but not documented")}`,
        `Project: ${safe(context.projectName)}`,
        `Generated: ${new Date().toISOString()}`,
        `Model type: ${safe(context.modelType)}`,
        `Problem type: ${safe(problemType)}`,
        `Champion model: ${safe(champion?.modelType, "No champion selected")}`,
        `Primary success metric: ${safe(context.primarySuccessMetric)}`,
        `Regulatory environment: ${summarizeRegulatoryContext(context)}`,
        "",
        champion
          ? `The current champion is ${champion.modelType}. The report uses the project context, decision journal, experiment records, local dataset metadata, and captured evaluation artifacts.`
          : "No champion model has been selected yet. Complete model training and promote a champion before this report is finalized.",
      ].join("\n"),
    },
    { title: "Business Objective", content: safe(context.businessObjective) },
    { title: "Model Purpose", content: `Model type: ${safe(context.modelType)}\nPurpose: ${safe(context.intendedModelUse)}` },
    { title: "Intended Use", content: `${safe(context.intendedModelUse)}\nDeployment expectation: ${safe(context.deploymentExpectation)}` },
    {
      title: "Model Implementation",
      content: [
        `Implementation owner: ${safe(context.implementationOwner)}`,
        `Target implementation date: ${safe(context.implementationTargetDate)}`,
        `Implementation environment: ${safe(context.implementationEnvironment)}`,
        `Implementation notes: ${safe(context.implementationNotes)}`,
      ].join("\n"),
    },
    { title: "Population Definition", content: safe(context.populationDefinition) },
    { title: "Target Definition", content: `${safe(context.targetDefinition)}\nTarget variable: ${safe(dataset?.target)}` },
    {
      title: "Data Sources",
      content: [
        `Primary source: ${safe(dataAccess?.sourceLabel, "Uploaded dataset in the modeling workbench")}`,
        `Source type: ${safe(dataAccess?.sourceType)}`,
        `Connection: ${safe(dataAccess?.connectionName)}`,
        `Database: ${safe(dataAccess?.database)}`,
        `Schema: ${safe(dataAccess?.schema)}`,
        `SQL query: ${safe(dataAccess?.sqlQuery)}`,
        `Import date: ${safe(dataAccess?.importedAt)}`,
        `Project ID: ${safe(datasetIdentity?.project_id)}`,
        `Dataset ID: ${safe(datasetIdentity?.dataset_id)}`,
        `Dataset Library ID: ${safe(datasetIdentity?.dataset_id)}`,
        `Dataset Library version: ${safe(datasetIdentity?.dataset_version_id)}`,
        `Dataset Library name: ${safe(dataset?.dataset_library?.datasetName)}`,
        `Access metadata ID: ${safe(dataAccess?.accessMetadataId)}`,
        `Dataset hash: ${safe(dataAccess?.hash)}`,
        `Sampling approach: ${safe(dataAccess?.samplingMethod)} ${safe(dataAccess?.samplingDetail, "")}`,
        `Rows currently available in browser sample: ${dataset?.rows.length ?? 0}`,
        `Columns: ${dataset?.headers.length ?? 0}`,
        `Selected features: ${dataset?.selected_columns?.length ?? 0}`,
        `Dataset versions in current problem-type experiments: ${formatList([...new Set(experiments.map((experiment) => experiment.dataset_version_id))])}`,
        "",
        "Lineage:",
        dataAccess?.lineage?.length ? dataAccess.lineage.map((item) => `- ${item}`).join("\n") : "Not documented",
        "",
        "Data quality:",
        dataQuality
          ? [
              dataQuality.duplicateContract
                ? `- Exact duplicates: ${dataQuality.duplicateContract.redundant_duplicate_rows} redundant rows beyond the retained ${dataQuality.duplicateContract.keep_semantics} occurrence; ${dataQuality.duplicateContract.duplicate_participant_rows} participant rows across ${dataQuality.duplicateContract.duplicate_group_count} groups; scope ${dataQuality.duplicateContract.scope}; target ${dataQuality.duplicateContract.target_included ? "included" : "excluded"}.`
                : `- Exact duplicates: backend definition unavailable; browser value ${dataQuality.duplicateRows} is non-authoritative.`,
              `- Potential leakage columns: ${dataQuality.potentialLeakageColumns.join(", ") || "None detected"}`,
              `- High missing fields: ${dataQuality.missing.slice(0, 5).map((row) => `${row.column} ${formatNumber(row.percent * 100, 2)}%`).join(", ") || "None detected"}`,
            ].join("\n")
          : "Not documented",
      ].join("\n"),
    },
    { title: "Observation Window", content: safe(context.observationWindow) },
    { title: "Performance Window", content: safe(context.performanceWindow) },
    { title: "Exclusions", content: formatList(excludedFeatures, "No feature exclusions were captured in the decision journal.") },
    { title: "Outlier Strategy", content: formatObject(outlierMethods, "No outlier strategy was captured.") },
    { title: "Missing Value Strategy", content: formatObject(missingStrategies, "No missing-value strategy was captured.") },
    {
      title: "Preprocessing Execution Lineage",
      content: formatObject(
        preparation.lineage,
        "No backend-governed preprocessing execution is linked to the champion.",
      ),
    },
    {
      title: "Feature Engineering",
      content: [
        `Selected features: ${dataset?.selected_columns?.length ?? 0}`,
        formatList(dataset?.selected_columns ?? [], "No selected feature list available."),
        "",
        "Feature engineering decisions should be reviewed in the Decision Journal appendix when interactions, binning, encodings, or custom code are used.",
      ].join("\n"),
    },
    {
      title: "Balancing Strategy",
      content: problemType === "regression"
        ? "Balancing is not applicable to continuous-target regression. Validate target distribution alignment with holdout or cross-validation diagnostics."
        : [`Method: ${balanceMethod}`, balanceRatio ? `Balance ratio: ${balanceRatio}` : ""].filter(Boolean).join("\n"),
    },
    {
      title: "Train/Test or Cross-Validation Strategy",
      content: [`Split strategy: ${splitStrategy}`, kFolds ? `Cross-validation folds: ${kFolds}` : ""].filter(Boolean).join("\n"),
    },
    { title: "Candidate Models", content: formatCandidateModels(experiments, problemType) },
    {
      title: "Champion Model",
      content: champion
        ? [
            `Model: ${champion.modelType}`,
            `Experiment ID: ${champion.experimentId}`,
            `Project ID: ${champion.project_id}`,
            `Dataset ID: ${champion.dataset_id}`,
            `Dataset version: ${champion.dataset_version_id}`,
            `Calibration status: ${champion.calibrationStatus}`,
            `Interpretability score: ${champion.interpretability}`,
            `Hyperparameters:\n${formatObject(champion.hyperparameters, "{}")}`,
          ].join("\n")
        : "No champion model selected.",
    },
    { title: "Performance Summary", content: metricLines(champion?.metrics, problemType) },
    ...(problemType === "regression"
      ? [
          {
            title: "Residual and Prediction Error Summary",
            content:
              "Regression governance should rely on RMSE, MAE, MSE, R-squared, adjusted R-squared, residual diagnostics, prediction stability, and actual-versus-predicted plots. Confusion matrix, ROC, PR, KS, and lift are not applicable to continuous targets.",
          },
        ]
      : [
          { title: "Confusion Matrix", content: formatConfusionMatrix(champion?.confusionMatrix) },
          { title: "ROC and PR Summary", content: formatCurveSummary(champion) },
          {
            title: "Lift / Decile Analysis",
            content:
              champion?.metrics.lift !== undefined
                ? `Top captured lift: ${formatNumber(champion.metrics.lift, 2)}\nDecile tables should be retained from the Evaluation or Scoring pages as validation evidence.`
                : "No lift or decile analysis captured.",
          },
        ]),
    { title: "Feature Importance", content: formatFeatureImportance(champion) },
    {
      title: "Interpretability Notes",
      content: [
        `Interpretability requirement: ${safe(context.interpretabilityRequirement)}`,
        `Champion interpretability score: ${safe(champion?.interpretability, "No champion selected")}`,
        "Review feature importance, SHAP-style summaries, PDP/sensitivity analysis, and VIF where available. For high-governance consumer lending models, document whether drivers are intuitive, stable, explainable, and operationally available.",
      ].join("\n"),
    },
    {
      title: "Model Limitations",
      content: [
        "Documented limitations should be reviewed and expanded before validation sign-off.",
        "- Browser-local artifacts may not represent a controlled production model registry.",
        "- Stability evidence depends on available TEST and OOT scoring datasets.",
        "- Performance may degrade if production population, policy, channel mix, or data quality shifts.",
        "- Proxy and fairness risks require separate review for protected class impact where applicable.",
      ].join("\n"),
    },
    {
      title: "Fair Lending / Compliance Considerations",
      content: [
        `Regulatory context: ${summarizeRegulatoryContext(context)}`,
        context.regulatoryEnvironment.includes("Fair Lending") || context.regulatoryEnvironment.includes("ECOA") || context.regulatoryEnvironment.includes("FCRA")
          ? "Fair lending and adverse action review should be completed before production use. Evaluate protected-class proxy risk, disparate impact, explainability, reason code suitability, and policy alignment."
          : "No explicit fair lending regulation was selected. Consumer lending use cases should still assess proxy risk, explainability, and model governance expectations.",
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
        `Selected monitoring metrics: ${formatList(context.monitoringMetrics, "No monitoring metrics selected.")}`,
        "",
        "- Monitor score PSI and feature VSI/PSI on scheduled production batches.",
        "- Track champion performance against the declared primary and secondary metrics.",
        "- Reassess calibration, lift, and threshold performance after policy or population shifts.",
        "- Review missingness, outlier rates, reject/ineligible populations, and feature availability.",
        "- Maintain decision journal and experiment lineage for material model changes.",
      ].join("\n"),
    },
    { title: "Decision Journal Appendix", content: formatDecisionAppendix(decisions) },
    { title: "Experiment Appendix", content: formatExperimentAppendix(experiments) },
  ];

  return sections.map((section, index) => ({ ...section, number: index + 1 }));
}

export function renderGovernanceMarkdown(title: string, generatedAt: string, sections: GovernanceSection[]) {
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

export function renderGovernanceHtml(title: string, generatedAt: string, sections: GovernanceSection[], wordCompatible = false) {
  const sectionHtml = sections
    .map(
      (section) => `
        <section>
          <h2>${section.number}. ${escapeHtml(section.title)}</h2>
          ${renderReportContentHtml(section.content)}
        </section>`
    )
    .join("\n");

  return `<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <title>${escapeHtml(title)}</title>
  <style>
    body { background: #f8fafc; margin: 32px; }
    ${atlasReportStyles()}
  </style>
</head>
<body${wordCompatible ? ' class="word-compatible"' : ""}>
<main class="atlas-report">
  <h1>${escapeHtml(BRAND.productName)}</h1>
  <div class="meta"><strong>${escapeHtml(BRAND.productSubtitle)}</strong><br />${escapeHtml(BRAND.shortDescription)}</div>
  <h2>${escapeHtml(title)}</h2>
  <div class="meta">Generated: ${escapeHtml(generatedAt)}</div>
  ${sectionHtml}
</main>
</body>
</html>`;
}

export function buildGovernanceReport(): GovernanceReport {
  const context = loadProjectContext();
  const workflowState = useWorkflowStore.getState();
  const workflow = getWorkflowDefinition(workflowState.workflowId);
  const generatedAt = new Date().toISOString();
  const title = `${context.projectName || workflowState.projectName || workflow.label} Governance Report`;
  const sections = workflowState.projectType === "predictive-modeling" ? buildSections() : buildWorkflowPlaceholderSections(workflowState, workflow);
  const fileBaseName = `${compactFileName(context.projectName || "model")}-governance-report`;
  return {
    title,
    generatedAt,
    fileBaseName,
    sections,
    markdown: renderGovernanceMarkdown(title, generatedAt, sections),
    html: renderGovernanceHtml(title, generatedAt, sections),
    wordHtml: renderGovernanceHtml(title, generatedAt, sections, true),
  };
}

function buildWorkflowPlaceholderSections(
  workflowState: ReturnType<typeof useWorkflowStore.getState>,
  workflow: ReturnType<typeof getWorkflowDefinition>
): GovernanceSection[] {
  const context = loadProjectContext();
  const decisions = loadDecisionJournal();
  const evidence = loadWorkflowNodeEvidence(workflowState.projectId, workflowState.workflowSteps);
  const nodeStates = Object.fromEntries(
    evidence.map((row) => [
      row.stepLabel,
      {
        objective: row.objective,
        inputs: row.inputs,
        assumptions: row.assumptions,
        method: row.method,
        metrics: row.metrics,
        validation: row.validation,
        risks: row.risks,
        decision: row.decision,
        rationale: row.rationale,
        notes: row.notes,
        numeric: row.numeric,
        simulationResults: row.simulationResults,
      } satisfies ExperimentalDesignNodeState,
    ])
  );
  const analysisSnapshots =
    workflow.projectType === "experimental-design"
      ? workflow.steps.map((step) =>
          buildExperimentalDesignAnalysis({
            stepLabel: step.label,
            currentState: nodeStates[step.label],
            nodeStates,
          })
        )
      : evidence.map((row) => row.analysisSnapshot).filter((snapshot): snapshot is NonNullable<typeof snapshot> => Boolean(snapshot));
  const evidenceByStep = new Map(evidence.map((row) => [row.stepId, row]));
  const statusForWorkflowStep = (step: ReturnType<typeof getWorkflowDefinition>["steps"][number]) => {
    const stored = workflowState.workflowSteps.find((item) => item.id === step.id)?.status ?? "pending";
    const row = evidenceByStep.get(step.id);
    const hasEvidence = Boolean(
      row &&
        ([row.objective, row.inputs, row.assumptions, row.method, row.validation, row.risks, row.decision, row.rationale, row.notes].some((value) => value?.trim()) ||
          (row.metrics?.length ?? 0) > 0 ||
          row.simulationResults ||
          row.analysisSnapshot)
    );
    if (stored === "skipped") return "skipped";
    if (stored === "complete" || hasEvidence) return "complete";
    return "pending";
  };
  const sections: Omit<GovernanceSection, "number">[] = [
    {
      title: "Executive Summary",
      content: [
        `Model ID #: ${safe(context.modelId, "Required but not documented")}`,
        `Project: ${safe(context.projectName || workflowState.projectName)}`,
        `Workflow: ${workflow.label}`,
        `Project Type: ${workflowState.projectType.replace(/-/g, " ")}`,
        `Purpose: ${safe(context.businessObjective)}`,
        "This is a workflow-aware placeholder report. Detailed analytical evidence will be populated as workflow-specific tooling is implemented.",
      ].join("\n"),
    },
    {
      title: "Workflow Definition",
      content: [
        sectionSummaryHtml(
          "Workflow Status Summary",
          `${workflow.steps.length} workflow stages define the ${workflow.label} journey. Status badges identify completed, skipped, and pending governance nodes.`
        ),
        professionalTableHtml(
          ["Step", "Description", "Status"],
          workflow.steps.map((step, index) => [
            `${index + 1}. ${step.label}`,
            step.description,
            statusForWorkflowStep(step),
          ]),
          { badgeColumns: ["Status"] }
        ),
      ].join("\n"),
    },
    {
      title: "Project Context",
      content: [
        `Target / Outcome Definition: ${safe(context.targetDefinition)}`,
        `Population Definition: ${safe(context.populationDefinition)}`,
        `Observation Window: ${safe(context.observationWindow)}`,
        `Performance Window: ${safe(context.performanceWindow)}`,
        `Intended Use: ${safe(context.intendedModelUse)}`,
        `Regulatory Environment: ${summarizeRegulatoryContext(context)}`,
      ].join("\n"),
    },
    {
      title: "Implementation and Monitoring",
      content: [
        `Implementation owner: ${safe(context.implementationOwner)}`,
        `Implementation target date: ${safe(context.implementationTargetDate)}`,
        `Implementation environment: ${safe(context.implementationEnvironment)}`,
        `Monitoring cadence: ${
          context.monitoringCadence === "custom"
            ? safe(context.monitoringCadenceCustom, "Custom cadence not documented")
            : safe(context.monitoringCadence)
        }`,
        `Monitoring metrics: ${context.monitoringMetrics.length ? context.monitoringMetrics.join(", ") : "None selected"}`,
        `Monitoring notes: ${safe(context.monitoringNotes)}`,
      ].join("\n"),
    },
    {
      title: "Workflow Evidence Status",
      content: workflow.steps
        .map((step) => {
          const status = statusForWorkflowStep(step);
          return `- ${step.label}: ${status === "complete" ? "Complete" : status === "skipped" ? "Skipped" : "Pending"}`;
        })
        .join("\n"),
    },
    {
      title: "Workflow Analytics Summary",
      content: analysisSnapshots.length
        ? [
            sectionSummaryHtml(
              "Analysis Object Summary",
              `${analysisSnapshots.length} workflow analysis object${analysisSnapshots.length === 1 ? "" : "s"} were captured. The live workflow and this report use the same executive insight, KPI, warning, and recommendation payloads.`
            ),
            professionalTableHtml(
              ["Step", "Executive Insight", "Primary KPIs", "Warnings", "Recommended Next Step"],
              analysisSnapshots.map((analysis) => [
                analysis.stepLabel,
                analysis.executiveInsight,
                analysis.kpis.slice(0, 4).map((kpi) => `${kpi.label}: ${kpi.value}`).join("; "),
                analysis.warnings.length ? analysis.warnings.join("; ") : "None",
                analysis.recommendedNextSteps[0] ?? "-",
              ]),
              { wide: true }
            ),
          ].join("\n")
        : "No workflow analysis snapshots have been saved yet. Save each workflow node to persist synchronized analytical evidence for the report.",
    },
    {
      title: "Workflow Node Evidence",
      content: summarizeWorkflowNodeEvidence(evidence),
    },
    {
      title: "Governance Considerations",
      content: [
        "- Document all assumptions, exclusions, and user overrides.",
        "- Preserve source data lineage and versioning for reproducibility.",
        "- Capture decision rationale for material workflow choices.",
        "- Define monitoring and implementation criteria before production use.",
      ].join("\n"),
    },
    { title: "Decision Journal Appendix", content: formatDecisionAppendix(decisions) },
  ];
  return sections.map((section, index) => ({ ...section, number: index + 1 }));
}
