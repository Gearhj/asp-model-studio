import { loadLocalDataset } from "./localDataset";
import { loadProjectContext } from "./projectContext";

export type AdaptiveRecommendation = {
  route: string;
  kind: "skip" | "simplify" | "warning" | "review" | "default";
  headline: string;
  explanation: string;
  why: string;
  suggestedAction: string;
  confidence: number;
};

function numericValues(values: unknown[]) {
  return values.map((value) => Number(value)).filter(Number.isFinite);
}

function isMissing(value: unknown) {
  return value === null || value === undefined || String(value).trim() === "";
}

function columnKinds(rows: Record<string, unknown>[], headers: string[], target: string | null) {
  return headers
    .filter((header) => header !== target)
    .map((header) => {
      const sample = rows.slice(0, 1000).map((row) => row[header]).filter((value) => !isMissing(value));
      const numeric = sample.length > 0 && numericValues(sample).length / sample.length >= 0.85;
      return { header, numeric };
    });
}

function missingCellCount(rows: Record<string, unknown>[], headers: string[]) {
  let count = 0;
  for (const row of rows) {
    for (const header of headers) {
      if (isMissing(row[header])) count += 1;
    }
  }
  return count;
}

function standardizedFeatureShare(rows: Record<string, unknown>[], numericHeaders: string[]) {
  if (!rows.length || !numericHeaders.length) return 0;
  const standardized = numericHeaders.filter((header) => {
    const nums = numericValues(rows.slice(0, 1000).map((row) => row[header]));
    if (nums.length < 20) return false;
    const mean = nums.reduce((sum, value) => sum + value, 0) / nums.length;
    const variance = nums.reduce((sum, value) => sum + (value - mean) ** 2, 0) / Math.max(1, nums.length - 1);
    const std = Math.sqrt(variance);
    return Math.abs(mean) < 0.25 && std > 0.65 && std < 1.35;
  });
  return standardized.length / Math.max(1, numericHeaders.length);
}

function pcaLikeShare(headers: string[]) {
  if (!headers.length) return 0;
  const pcaLike = headers.filter((header) => /^V\d+$/i.test(header) || /^PC[A]?\d+$/i.test(header));
  return pcaLike.length / headers.length;
}

export function getAdaptiveRecommendations(route: string): AdaptiveRecommendation[] {
  const dataset = loadLocalDataset();
  const context = loadProjectContext();
  if (!dataset?.rows.length) return [];

  const rows = dataset.rows;
  const headers = dataset.headers;
  const target = dataset.target;
  const featureHeaders = headers.filter((header) => header !== target);
  const kinds = columnKinds(rows, headers, target);
  const numericHeaders = kinds.filter((column) => column.numeric).map((column) => column.header);
  const categoricalHeaders = kinds.filter((column) => !column.numeric).map((column) => column.header);
  const standardizedShare = standardizedFeatureShare(rows, numericHeaders);
  const pcaShare = pcaLikeShare(featureHeaders);
  const recommendations: AdaptiveRecommendation[] = [];

  if (route === "/step04" && missingCellCount(rows, headers) === 0) {
    recommendations.push({
      route,
      kind: "skip",
      headline: "Recommended: Skip this step",
      explanation: "No missing values were detected in the browser dataset sample.",
      why: "This target-independent structural check can simplify review, but it is not evidence of governed development membership or holdout scope.",
      suggestedAction: "Mark this step complete as No Action Needed, or keep it open if you expect missingness in scoring data.",
      confidence: 0.96,
    });
  }

  if (route === "/step05" && categoricalHeaders.length === 0) {
    recommendations.push({
      route,
      kind: "simplify",
      headline: "Recommended: Simplify this step",
      explanation: "No categorical predictors were detected, so one-hot encoding and categorical rule setup may not be needed.",
      why: "Removing irrelevant controls keeps the workflow focused and reduces the chance of adding unnecessary transformations.",
      suggestedAction: "Leave encoding set to None unless you intentionally create binned or rule-based categorical features.",
      confidence: 0.91,
    });
  }

  if (route === "/step05" && numericHeaders.length === featureHeaders.length && (standardizedShare >= 0.6 || pcaShare >= 0.5)) {
    recommendations.push({
      route,
      kind: "skip",
      headline: "Recommended: Skip additional scaling",
      explanation:
        pcaShare >= 0.5
          ? "Most feature names look PCA-like or engineered, which usually means the data has already been transformed."
          : "Most numeric features appear standardized with mean near zero and standard deviation near one.",
      why: "Repeated scaling can make lineage harder to explain and may not improve models that already receive standardized inputs.",
      suggestedAction: "Keep scaling set to None unless a selected model specifically requires a new scaling step.",
      confidence: pcaShare >= 0.5 ? 0.93 : 0.84,
    });
  }

  if (context.interpretabilityRequirement === "high" && ["/step07", "/step08", "/step09"].includes(route)) {
    recommendations.push({
      route,
      kind: "default",
      headline: "High interpretability model set recommended",
      explanation: "The project context requires high interpretability.",
      why: "Consumer lending governance often expects transparent drivers, reason-code support, and a clear rationale for any black-box model.",
      suggestedAction: "Prioritize Logistic Regression, Decision Tree, EBM, or monotonic models; use complex models as challengers with documented justification.",
      confidence: 0.89,
    });
  }

  if (context.regulatoryEnvironment.some((item) => ["Fair Lending", "FCRA", "ECOA"].includes(item))) {
    recommendations.push({
      route,
      kind: "review",
      headline: "Fair lending review reminder",
      explanation: `Regulatory context includes ${context.regulatoryEnvironment.join(", ")}.`,
      why: "Fair lending review should address proxy risk, disparate impact, adverse-action explainability, exclusions, and monitoring.",
      suggestedAction: "Document fairness review requirements in the Decision Journal and Governance Report before final model approval.",
      confidence: 0.9,
    });
  }

  if (context.deploymentExpectation === "real-time API" && ["/step07", "/step09", "/step10"].includes(route)) {
    recommendations.push({
      route,
      kind: "warning",
      headline: "Real-time deployment constraint",
      explanation: "The project context indicates real-time API deployment.",
      why: "Slow models or complex preprocessing pipelines can create latency, reliability, and reproducibility risks in production scoring.",
      suggestedAction: "Favor fast scoring models and deterministic preprocessing; benchmark KNN, SVM, large ensembles, and neural networks before promotion.",
      confidence: 0.86,
    });
  }

  return recommendations.filter((recommendation) => recommendation.route === route || recommendation.kind !== "skip").slice(0, 4);
}
