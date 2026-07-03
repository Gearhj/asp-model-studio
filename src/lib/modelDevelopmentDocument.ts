import { loadDecisionJournal, materialDecisionSummary, type DecisionJournalEntry } from "./decisionJournal";
import { loadExperiments, type ExperimentMetricSet, type ExperimentRecord } from "./experimentTracking";
import { buildGovernanceReport } from "./governanceReport";
import { sanitizeReportHtml } from "./htmlSanitizer";
import { inferLocalProblemType, loadLocalDataset } from "./localDataset";
import { getNotebookSections } from "./notebookExport";
import { loadProjectContext, summarizeRegulatoryContext } from "./projectContext";
import { summarizeBureauHandling, treatmentLabels } from "./creditBureau";
import { loadDataAccessMetadata } from "./enterpriseDataAccess";
import { buildReportReadiness } from "./reportReadiness";
import { BRAND } from "../config/brand";
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

function readJson<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(key);
    if (!raw) return fallback;
    return (JSON.parse(raw) as T) ?? fallback;
  } catch {
    return fallback;
  }
}

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

function selectChampion(experiments: ExperimentRecord[]) {
  return experiments.find((experiment) => experiment.champion) ?? experiments[0] ?? null;
}

function metricLines(metrics: ExperimentMetricSet | undefined) {
  if (!metrics) return "No model performance metrics captured.";
  const rows: [keyof ExperimentMetricSet, string, number][] = [
    ["auc", "AUC", 4],
    ["pr_auc", "PR-AUC", 4],
    ["precision", "Precision", 4],
    ["recall", "Recall", 4],
    ["f1", "F1", 4],
    ["ks", "KS", 4],
    ["lift", "Lift", 2],
    ["rmse", "RMSE", 4],
    ["mae", "MAE", 4],
    ["mse", "MSE", 4],
    ["r2", "R-squared", 4],
    ["adjusted_r2", "Adjusted R-squared", 4],
  ];
  const available = rows
    .filter(([key]) => metrics[key] !== undefined && metrics[key] !== null)
    .map(([key, label, digits]) => `- ${label}: ${formatNumber(metrics[key], digits)}`);
  if (metrics.calibration !== undefined) available.push(`- Calibration: ${safe(metrics.calibration)}`);
  return available.length ? available.join("\n") : "No model performance metrics captured.";
}

function formatCandidateModels(experiments: ExperimentRecord[]) {
  if (!experiments.length) return "No experiment records have been captured.";
  return professionalTableHtml(
    ["Model", "Champion", "AUC", "PR-AUC", "F1", "RMSE", "MAE", "R-squared", "Runtime"],
    experiments.slice(0, 30).map((experiment) => [
      experiment.modelType,
      experiment.champion ? "Yes" : "No",
      formatNumber(experiment.metrics.auc),
      formatNumber(experiment.metrics.pr_auc),
      formatNumber(experiment.metrics.f1),
      formatNumber(experiment.metrics.rmse),
      formatNumber(experiment.metrics.mae),
      formatNumber(experiment.metrics.r2),
      `${Math.round((experiment.runtimeMs ?? 0) / 1000)}s`,
    ]),
    { wide: true, badgeColumns: ["Champion"] }
  );
}

function formatFeatureImportance(champion: ExperimentRecord | null) {
  const rows = champion?.featureImportance?.slice(0, 20) ?? [];
  if (!rows.length) return "No feature importance artifact has been captured for the champion experiment.";
  return professionalTableHtml(
    ["Feature", "Importance", "Direction", "Source"],
    rows.map((row) => [row.feature, formatNumber(row.importance), formatNumber(row.direction), row.source ?? "-"]),
    { compact: true }
  );
}

function formatDecisions(entries: DecisionJournalEntry[]) {
  return decisionJournalTimelineHtml(entries);
}

function formatExperimentAppendix(experiments: ExperimentRecord[]) {
  if (!experiments.length) return "No experiment records have been captured.";
  return experiments
    .slice(0, 80)
    .map((experiment, index) =>
      [
        `${index + 1}. ${experiment.modelType}`,
        `   - Experiment ID: ${experiment.experimentId}`,
        `   - Timestamp: ${experiment.timestamp}`,
        `   - Dataset version: ${experiment.datasetVersion}`,
        `   - Selected features: ${experiment.selectedFeatures.length}`,
        `   - Balancing method: ${experiment.balancingMethod}`,
        `   - Split strategy: ${experiment.splitStrategy}`,
        `   - Hyperparameters: ${JSON.stringify(experiment.hyperparameters ?? {})}`,
        `   - Metrics: ${JSON.stringify(experiment.metrics ?? {})}`,
        `   - Champion: ${experiment.champion ? "Yes" : "No"}`,
        `   - Notes: ${experiment.notes || "-"}`,
      ].join("\n")
    )
    .join("\n\n");
}

function formatBureauHandling() {
  const summary = summarizeBureauHandling();
  if (!summary.profiles.length && !summary.decisions.length) {
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

  return [
    `Detected profiles: ${summary.profiles.length}`,
    `Documented treatment decisions: ${summary.decisions.length}`,
    "",
    "| Variable | Value | Bureau Definition | Count | Percent | Special Event Rate | Regular Event Rate | Treatment | Rationale |",
    "|---|---|---|---:|---:|---:|---:|---|---|",
    ...rows,
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
  if (!champion) return "No champion experiment selected.";
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

function buildSections(mode: ModelDevelopmentDocumentMode): ModelDevelopmentDocumentSection[] {
  const context = loadProjectContext();
  const dataset = loadLocalDataset();
  const problemType = inferLocalProblemType(dataset) ?? dataset?.problem_type ?? "Not documented";
  const experiments = filterExperimentsForProblem(loadExperiments(), String(problemType));
  const decisions = loadDecisionJournal();
  const champion = selectChampion(experiments);
  const materialDecisions = materialDecisionSummary(decisions);
  const readiness = buildReportReadiness({ problemType: String(problemType), experiments, champion, decisions, dataset, context });
  const governance = buildGovernanceReport();
  const missingStrategies = readJson<Record<string, unknown>>("modeling-tool-missing-config", {});
  const outlierMethods = readJson<Record<string, unknown>>("modeling-tool-outlier-methods", {});
  const balanceMethod = localStorage.getItem("balanceMethod") ?? "Not documented";
  const splitStrategy = localStorage.getItem("splitStrategy") ?? "Not documented";
  const balanceRatio = localStorage.getItem("balanceRatio") ?? "";
  const selectedFeatures = dataset?.selected_columns ?? [];
  const dataAccess = loadDataAccessMetadata() ?? dataset?.data_access ?? null;
  const dataQuality = dataset?.data_quality ?? null;

  const sections: Omit<ModelDevelopmentDocumentSection, "number">[] = [
    {
      title: "Cover Page",
      content: [
        `Model ID #: ${safe(context.modelId, "Required but not documented")}`,
        `Project: ${safe(context.projectName, "Untitled model development project")}`,
        `Model name: ${safe(champion?.modelType, "Not selected")}`,
        `Model owner: ${safe(context.implementationOwner)}`,
        `Generated: ${new Date().toISOString()}`,
        "Version: Draft 1.0",
        `Development environment: ${BRAND.productName} local workbench`,
        `Prepared for: Consumer Lending AI/ML model development`,
        `Document type: Model Development Document`,
        `Problem type: ${safe(problemType)}`,
        `Champion model: ${safe(champion?.modelType, "No champion selected")}`,
      ].join("\n"),
    },
    {
      title: "Executive Summary",
      content: [
        `Business objective: ${safe(context.businessObjective)}`,
        `Target: ${safe(dataset?.target)}`,
        `Rows in browser sample: ${dataset?.rows.length ?? 0}`,
        `Selected features: ${selectedFeatures.length}`,
        `Champion model: ${safe(champion?.modelType, "No champion selected")}`,
        `Primary success metric: ${safe(context.primarySuccessMetric)}`,
        "",
        metricLines(champion?.metrics),
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
    {
      title: "Material Decision Summary",
      content: materialDecisions.length
        ? formatDecisions(materialDecisions)
        : "No material decision journal entries have been captured yet. Continue using workflow controls so champion selection, preprocessing, split, balancing, and final-model decisions are logged.",
    },
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
        `False positive cost: ${safe(context.falsePositiveCost)}`,
        `False negative cost: ${safe(context.falseNegativeCost)}`,
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
        `Dataset ID: ${safe(dataAccess?.datasetId)}`,
        `Dataset version: ${safe(dataAccess?.version)}`,
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
              `- Duplicate rows: ${dataQuality.duplicateRows}`,
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
      title: "Feature Engineering",
      content:
        "Feature engineering selections are captured in the workflow state and decision journal. Review generated variables, scaling, encodings, interactions, bins, and rule-based categorical features in the notebook export.",
    },
    {
      title: "Train/Test and Balancing Strategy",
      content: [
        `Split strategy: ${safe(splitStrategy)}`,
        `Balancing method: ${safe(balanceMethod)}`,
        `Balance ratio: ${safe(balanceRatio, "Not documented or not applicable")}`,
      ].join("\n"),
    },
    { title: "Candidate Models", content: formatCandidateModels(experiments) },
    { title: "Model Performance", content: metricLines(champion?.metrics) },
    {
      title: "Model Interpretation",
      content: [
        "Feature importance and SHAP-style summaries are appropriate for both classification and regression when interpreted as model behavior evidence, not causal proof.",
        "",
        formatFeatureImportance(champion),
      ].join("\n"),
    },
    {
      title: "Model Selection Rationale",
      content: [
        `Champion model: ${safe(champion?.modelType, "No champion selected")}`,
        champion
          ? "Document the reason this champion is preferred, including performance, interpretability, operational constraints, policy needs, and validation readiness."
          : "Promote an experiment to champion before finalizing this section.",
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

  if (mode !== "executive") {
    sections.push({ title: "Decision Journal Appendix", content: formatDecisions(decisions) });
    sections.push({ title: "Experiment Appendix", content: formatExperimentAppendix(experiments) });
  }

  if (mode === "technical") {
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

export function buildModelDevelopmentDocument(mode: ModelDevelopmentDocumentMode = "governance"): ModelDevelopmentDocument {
  const context = loadProjectContext();
  const generatedAt = new Date().toISOString();
  const title = `${safe(context.projectName, "Model")} Model Development Document`;
  const sections = buildSections(mode);
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
