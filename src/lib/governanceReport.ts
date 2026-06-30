import { loadDecisionJournal, type DecisionJournalEntry } from "./decisionJournal";
import { loadExperiments, type ExperimentRecord, type ExperimentMetricSet } from "./experimentTracking";
import { inferLocalProblemType, loadLocalDataset } from "./localDataset";
import { loadProjectContext, summarizeRegulatoryContext } from "./projectContext";
import { loadDataAccessMetadata } from "./enterpriseDataAccess";
import { BRAND } from "../config/brand";

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

function readJson<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(key);
    if (!raw) return fallback;
    const parsed = JSON.parse(raw);
    return parsed ?? fallback;
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

function formatList(items: string[], fallback = "None documented") {
  const clean = items.map((item) => item.trim()).filter(Boolean);
  if (!clean.length) return fallback;
  return clean.map((item) => `- ${item}`).join("\n");
}

function formatObject(value: unknown, fallback = "None documented") {
  if (!value || (typeof value === "object" && !Object.keys(value as Record<string, unknown>).length)) {
    return fallback;
  }
  return JSON.stringify(value, null, 2);
}

function selectChampion(experiments: ExperimentRecord[]) {
  return experiments.find((experiment) => experiment.champion) ?? experiments[0] ?? null;
}

function metricLines(metrics: ExperimentMetricSet | undefined) {
  if (!metrics) return "No performance metrics captured.";
  const labels: [keyof ExperimentMetricSet, string, number][] = [
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
  return [
    "| Feature | Importance | Direction | Source |",
    "|---|---:|---:|---|",
    ...rows.map(
      (row) =>
        `| ${escapeMarkdown(row.feature)} | ${formatNumber(row.importance)} | ${formatNumber(row.direction)} | ${escapeMarkdown(row.source ?? "-")} |`
    ),
  ].join("\n");
}

function formatCandidateModels(experiments: ExperimentRecord[]) {
  if (!experiments.length) return "No model experiments captured.";
  return [
    "| Model | Champion | AUC | PR-AUC | F1 | RMSE | MAE | R-squared | Runtime |",
    "|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ...experiments.slice(0, 25).map((experiment) =>
      [
        escapeMarkdown(experiment.modelType),
        experiment.champion ? "Yes" : "No",
        formatNumber(experiment.metrics.auc),
        formatNumber(experiment.metrics.pr_auc),
        formatNumber(experiment.metrics.f1),
        formatNumber(experiment.metrics.rmse),
        formatNumber(experiment.metrics.mae),
        formatNumber(experiment.metrics.r2),
        `${Math.round(experiment.runtimeMs / 1000)}s`,
      ].join(" | ").replace(/^/, "| ").replace(/$/, " |")
    ),
  ].join("\n");
}

function formatDecisionAppendix(entries: DecisionJournalEntry[]) {
  if (!entries.length) return "No decision journal entries captured.";
  return [
    "| Timestamp | Step | Action | Subject | Previous | New | Follow Status | Rationale |",
    "|---|---|---|---|---|---|---|---|",
    ...entries.slice(0, 200).map((entry) =>
      [
        entry.timestamp,
        entry.workflowStep,
        entry.actionType,
        entry.subject,
        entry.previousValue,
        entry.newValue,
        entry.followStatus,
        entry.userReason || "",
      ]
        .map(escapeMarkdown)
        .join(" | ")
        .replace(/^/, "| ")
        .replace(/$/, " |")
    ),
  ].join("\n");
}

function formatExperimentAppendix(experiments: ExperimentRecord[]) {
  if (!experiments.length) return "No experiment records captured.";
  return experiments
    .slice(0, 50)
    .map((experiment, index) =>
      [
        `${index + 1}. ${experiment.modelType}`,
        `   - Experiment ID: ${experiment.experimentId}`,
        `   - Timestamp: ${experiment.timestamp}`,
        `   - Dataset version: ${experiment.datasetVersion}`,
        `   - Selected features: ${experiment.selectedFeatures.length}`,
        `   - Balancing: ${experiment.balancingMethod}`,
        `   - Split strategy: ${experiment.splitStrategy}`,
        `   - Hyperparameters: ${JSON.stringify(experiment.hyperparameters ?? {})}`,
        `   - Champion: ${experiment.champion ? "Yes" : "No"}`,
        `   - Notes: ${experiment.notes || "-"}`,
      ].join("\n")
    )
    .join("\n\n");
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
  const experiments = loadExperiments();
  const decisions = loadDecisionJournal();
  const champion = selectChampion(experiments);
  const problemType = inferLocalProblemType(dataset);
  const missingStrategies = readJson<Record<string, unknown>>("modeling-tool-missing-config", {});
  const outlierMethods = readJson<Record<string, unknown>>("modeling-tool-outlier-methods", {});
  const balanceMethod = localStorage.getItem("balanceMethod") ?? "Not documented";
  const balanceRatio = localStorage.getItem("balanceRatio") ?? "";
  const splitStrategy = localStorage.getItem("splitStrategy") ?? "Not documented";
  const kFolds = localStorage.getItem("kFolds") ?? "";
  const dataAccess = loadDataAccessMetadata() ?? dataset?.data_access ?? null;
  const dataQuality = dataset?.data_quality ?? null;
  const excludedFeatures = decisions
    .filter((entry) => entry.actionType === "feature_inclusion_changed" && /false|exclude|removed|no/i.test(entry.newValue))
    .map((entry) => entry.subject);

  const sections: Omit<GovernanceSection, "number">[] = [
    {
      title: "Executive Summary",
      content: [
        `Project: ${safe(context.projectName)}`,
        `Generated: ${new Date().toISOString()}`,
        `Model type: ${safe(context.modelType)}`,
        `Problem type: ${safe(problemType ?? dataset?.problem_type)}`,
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
        `Dataset version: ${safe(dataAccess?.version)}`,
        `Dataset hash: ${safe(dataAccess?.hash)}`,
        `Sampling approach: ${safe(dataAccess?.samplingMethod)} ${safe(dataAccess?.samplingDetail, "")}`,
        `Rows currently available in browser sample: ${dataset?.rows.length ?? 0}`,
        `Columns: ${dataset?.headers.length ?? 0}`,
        `Selected features: ${dataset?.selected_columns?.length ?? 0}`,
        `Dataset versions in experiments: ${formatList([...new Set(experiments.map((experiment) => experiment.datasetVersion))])}`,
        "",
        "Lineage:",
        dataAccess?.lineage?.length ? dataAccess.lineage.map((item) => `- ${item}`).join("\n") : "Not documented",
        "",
        "Data quality:",
        dataQuality
          ? [
              `- Duplicate rows: ${dataQuality.duplicateRows}`,
              `- Potential leakage columns: ${dataQuality.potentialLeakageColumns.join(", ") || "None detected"}`,
              `- High missing fields: ${dataQuality.missing.slice(0, 5).map((row) => `${row.column} ${formatNumber(row.percent * 100, 2)}%`).join(", ") || "None detected"}`,
            ].join("\n")
          : "Not documented",
      ].join("\n"),
    },
    { title: "Observation Window", content: safe(context.observationWindow) },
    { title: "Performance Window", content: safe(context.performanceWindow) },
    { title: "Exclusions", content: formatList(excludedFeatures, "No feature exclusions were captured in the decision journal.") },
    { title: "Missing Value Strategy", content: formatObject(missingStrategies, "No missing-value strategy was captured.") },
    { title: "Outlier Strategy", content: formatObject(outlierMethods, "No outlier strategy was captured.") },
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
      content: [`Method: ${balanceMethod}`, balanceRatio ? `Balance ratio: ${balanceRatio}` : "", problemType === "regression" ? "Balancing is not applicable to regression targets." : ""]
        .filter(Boolean)
        .join("\n"),
    },
    {
      title: "Train/Test or Cross-Validation Strategy",
      content: [`Split strategy: ${splitStrategy}`, kFolds ? `Cross-validation folds: ${kFolds}` : ""].filter(Boolean).join("\n"),
    },
    { title: "Candidate Models", content: formatCandidateModels(experiments) },
    {
      title: "Champion Model",
      content: champion
        ? [
            `Model: ${champion.modelType}`,
            `Experiment ID: ${champion.experimentId}`,
            `Dataset version: ${champion.datasetVersion}`,
            `Calibration status: ${champion.calibrationStatus}`,
            `Interpretability score: ${champion.interpretability}`,
            `Hyperparameters:\n${formatObject(champion.hyperparameters, "{}")}`,
          ].join("\n")
        : "No champion model selected.",
    },
    { title: "Performance Summary", content: metricLines(champion?.metrics) },
    { title: "Confusion Matrix", content: formatConfusionMatrix(champion?.confusionMatrix) },
    { title: "ROC and PR Summary", content: formatCurveSummary(champion) },
    {
      title: "Lift / Decile Analysis",
      content:
        champion?.metrics.lift !== undefined
          ? `Top captured lift: ${formatNumber(champion.metrics.lift, 2)}\nDecile tables should be retained from the Evaluation or Scoring pages as validation evidence.`
          : "No lift or decile analysis captured. This is expected for regression models.",
    },
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
    ...sections.flatMap((section) => [`## ${section.number}. ${section.title}`, "", section.content, ""]),
  ].join("\n");
}

export function renderGovernanceHtml(title: string, generatedAt: string, sections: GovernanceSection[], wordCompatible = false) {
  const sectionHtml = sections
    .map(
      (section) => `
        <section>
          <h2>${section.number}. ${escapeHtml(section.title)}</h2>
          <pre>${escapeHtml(section.content)}</pre>
        </section>`
    )
    .join("\n");

  return `<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <title>${escapeHtml(title)}</title>
  <style>
    body { margin: 32px; color: #0f172a; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Arial, sans-serif; line-height: 1.45; }
    h1 { margin: 0 0 4px; font-size: 28px; }
    .meta { color: #64748b; margin-bottom: 28px; }
    section { break-inside: avoid; border-top: 1px solid #dbe3ef; padding: 18px 0; }
    h2 { margin: 0 0 10px; font-size: 18px; }
    pre { white-space: pre-wrap; font-family: inherit; font-size: 13px; margin: 0; }
    table { border-collapse: collapse; width: 100%; margin: 8px 0; }
    th, td { border: 1px solid #dbe3ef; padding: 6px 8px; text-align: left; }
    @media print { body { margin: 0.5in; } }
  </style>
</head>
<body${wordCompatible ? ' class="word-compatible"' : ""}>
  <h1>${escapeHtml(BRAND.productName)}</h1>
  <div class="meta"><strong>${escapeHtml(BRAND.productSubtitle)}</strong><br />${escapeHtml(BRAND.shortDescription)}</div>
  <h2>${escapeHtml(title)}</h2>
  <div class="meta">Generated: ${escapeHtml(generatedAt)}</div>
  ${sectionHtml}
</body>
</html>`;
}

export function buildGovernanceReport(): GovernanceReport {
  const context = loadProjectContext();
  const generatedAt = new Date().toISOString();
  const title = `${context.projectName || "Model"} Governance Report`;
  const sections = buildSections();
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
