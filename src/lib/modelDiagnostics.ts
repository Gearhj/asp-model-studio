import { DATASET_API_BASE, type DatasetSummary } from "./datasetLibrary";
import type { AtlasAnalyticsInsight } from "./analyticsWorkbench";

async function diagnosticsFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${DATASET_API_BASE}${path}`, {
    credentials: "include",
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
  });
  const payload = await response.json().catch(() => null);
  if (!response.ok || payload?.ok === false) {
    throw new Error(payload?.detail ?? payload?.error ?? `ATLAS diagnostics request failed with HTTP ${response.status}.`);
  }
  return payload as T;
}

export type ScoredColumnRoles = {
  target?: string | null;
  actual?: string | null;
  score?: string | null;
  prediction?: string | null;
  residual?: string | null;
  absResidual?: string | null;
  squaredResidual?: string | null;
  percentError?: string | null;
  decile?: string | null;
  segment?: string | null;
};

export type ModelDiagnosticsResult = {
  ok: boolean;
  dataset: DatasetSummary & { sourceInfo?: Record<string, unknown>; datasetRole?: string };
  versionId: string;
  rowCount: number;
  diagnosticMode?: "classification" | "regression" | "prediction_only" | "unmapped" | string;
  columnRoles: ScoredColumnRoles;
  mappingWarnings?: string[];
  scoreDistribution: { available: boolean; summary: Record<string, number | null>; bins: Array<{ bin: string; count: number }> };
  classificationMetrics?: Record<string, unknown>;
  detailedLiftTable?: Array<Record<string, unknown>>;
  predictionSummary?: { available: boolean; summary: Record<string, number | null>; warnings?: string[] };
  actualDistribution?: { available: boolean; summary: Record<string, number | null>; bins?: Array<{ bin: string; count: number }> };
  topPredictions?: Array<Record<string, unknown>>;
  bottomPredictions?: Array<Record<string, unknown>>;
  largestAbsoluteErrors?: Array<Record<string, unknown>>;
  topOverpredictions?: Array<Record<string, unknown>>;
  topUnderpredictions?: Array<Record<string, unknown>>;
  predictionBandSummary?: Array<Record<string, unknown>>;
  regressionFitSummary?: { available: boolean; summary: Record<string, number | null>; warning?: string };
  populationWaterfall?: Array<Record<string, unknown>>;
  vifAnalysis?: { available: boolean; formula: string; rows: Array<Record<string, unknown>>; warning?: string };
  pozzoloCalibration?: Record<string, unknown>;
  kpiAggregation?: { mode: string; rows: Array<Record<string, unknown>>; recommendation?: string };
  liftDecile: Array<{ decile: number; n: number; eventRate: number | null; lift: number | null; minScore: number | null; maxScore: number | null; meanScore: number | null }>;
  residualDiagnostics: { available: boolean; summary: Record<string, number | null>; histogram?: Array<{ bin: string; count: number }> };
  actualVsPredicted: { available: boolean; summary: Record<string, number | null>; points: Array<{ actual: number | null; predicted: number | null }> };
  calibration: Array<{ bin: number; meanScore: number | null; actualRate: number | null; n: number }>;
  segmentPerformance: Array<Record<string, unknown>>;
  splitComparison?: Array<Record<string, unknown>>;
  generatedCode: { python: string; sql: string; r: string; sas: string };
  limitations: string;
};

export type RegisterScoredDatasetInput = {
  projectId?: string;
  projectName?: string;
  datasetName?: string;
  datasetType: "train" | "test" | "oot" | "external_validation" | "scored";
  task?: "classification" | "regression" | string;
  modelName?: string;
  targetColumn?: string;
  scoreColumn?: string;
  predictionColumn?: string;
  actualColumn?: string;
  residualColumn?: string;
  absResidualColumn?: string;
  squaredResidualColumn?: string;
  decileColumn?: string;
  rows: Array<Record<string, unknown>>;
  metadata?: Record<string, unknown>;
  /** Visual Intelligence Production Integration, Phase K: cross-links this
   *  registration back to its originating durable ScoringRun. */
  scoringRunId?: string;
};

export async function registerScoredDataset(input: RegisterScoredDatasetInput) {
  return diagnosticsFetch<{ ok: true; dataset: DatasetSummary; columnRoles: ScoredColumnRoles }>("/scoring/register-scored-dataset", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export async function runModelDiagnostics(datasetId: string, versionId?: string, overrides?: Partial<ScoredColumnRoles> & { positiveClass?: string }) {
  const params = new URLSearchParams({ datasetId });
  if (versionId) params.set("versionId", versionId);
  Object.entries(overrides ?? {}).forEach(([key, value]) => {
    if (value) params.set(key, String(value));
  });
  return diagnosticsFetch<ModelDiagnosticsResult>(`/model-diagnostics/run?${params.toString()}`);
}

export async function saveModelDiagnosticInsight(input: {
  title: string;
  summary: string;
  datasetId: string;
  versionId: string;
  projectId?: string;
  businessQuestion?: string;
  evidence?: Record<string, unknown>;
}) {
  const payload = await diagnosticsFetch<{ ok: true; insight: AtlasAnalyticsInsight }>("/model-diagnostics/insights", {
    method: "POST",
    body: JSON.stringify(input),
  });
  return payload.insight;
}

export type DiagnosticsExportFormat = "excel" | "word" | "powerpoint";

export async function exportModelDiagnostics(format: DiagnosticsExportFormat, datasetId: string, versionId?: string, overrides?: Partial<ScoredColumnRoles> & { positiveClass?: string }) {
  const params = new URLSearchParams({ datasetId });
  if (versionId) params.set("versionId", versionId);
  Object.entries(overrides ?? {}).forEach(([key, value]) => {
    if (value) params.set(key, String(value));
  });
  const response = await fetch(`${DATASET_API_BASE}/model-diagnostics/export/${format}?${params.toString()}`, {
    credentials: "include",
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => null);
    throw new Error(payload?.detail ?? payload?.error ?? `ATLAS diagnostics export failed with HTTP ${response.status}.`);
  }
  const blob = await response.blob();
  const disposition = response.headers.get("Content-Disposition") ?? "";
  return { blob, filename: filenameFromDisposition(disposition) ?? `atlas-model-diagnostics.${format === "excel" ? "xlsx" : format === "word" ? "docx" : "pptx"}` };
}

export function isScoredOutputDataset(dataset: Pick<DatasetSummary, "name" | "description" | "sourceType" | "linkedProjects"> & { datasetRole?: string; sourceInfo?: Record<string, unknown> }) {
  const role = String(dataset.datasetRole ?? dataset.sourceInfo?.datasetRole ?? "");
  const links = dataset.linkedProjects ?? [];
  const text = [dataset.name, dataset.description, dataset.sourceType, role, ...links.map((link) => link.datasetRole)].filter(Boolean).join(" ").toLowerCase();
  return /\b(scored_output|scored|score output|scoring output|predictions?|probabilit)/.test(text);
}

function filenameFromDisposition(disposition: string) {
  const match = /filename="?([^";]+)"?/i.exec(disposition);
  return match?.[1];
}
