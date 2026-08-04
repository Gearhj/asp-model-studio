import type { LocalDataset } from "./localDataset";
import {
  assertExactDatasetIdentity,
  requireLocalDatasetCanonicalIdentity,
} from "./datasetIdentity";

const API_BASE =
  (import.meta.env.VITE_API_BASE as string | undefined)?.replace(/\/$/, "") ||
  "http://127.0.0.1:8001/api";

export type FeatureProfileScope =
  | "development_population"
  | "full_dataset"
  | "complete_browser_dataset"
  | "preview_profile";

export type FeatureProfileRow = {
  selected: boolean;
  predictor: string;
  role: string;
  datatype: string;
  iv: number | null;
  ivStrength: string | null;
  correlationWithTarget: number | null;
  correlationStrength: string | null;
  associationStatus: "evaluated" | "not_evaluated";
  missingCount: number;
  missingPercent: number;
  distinctCount: number;
  mean: number | null;
  standardDeviation: number | null;
  minimum: number | null;
  firstQuartile: number | null;
  median: number | null;
  thirdQuartile: number | null;
  maximum: number | null;
  leakageStatus: "eligible" | "locked";
  eligibilityStatus: "eligible" | "excluded";
  exclusionReason: string;
  origin?: string;
  sourceFeatures?: string[];
  transformationType?: string;
  formulaOrRule?: string;
  materializationStatus?: string;
  featureId?: string | null;
  featureManifestVersion?: string | null;
};

export type FeatureProfileResponse = {
  ok: boolean;
  project_id?: string;
  dataset_id?: string;
  dataset_version_id?: string;
  /** Compatibility alias; authoritative backend responses derive it from dataset_version_id. */
  dataset_version?: string;
  profileScope: FeatureProfileScope;
  profiledRowCount: number;
  registeredRowCount: number;
  problemType: "classification" | "regression";
  target: string;
  eventValue?: unknown;
  selectedColumns: string[];
  features: FeatureProfileRow[];
  featureManifestVersion?: string | null;
  analytical_scope?: string;
  population_id?: string;
  population_count?: number;
  partition_id?: string;
  partition_revision?: number;
  holdout_excluded?: boolean;
  source_checksum?: string;
  actor?: string;
  timestamp?: string;
  warning?: string;
};

function isMissing(value: unknown) {
  return value === null || value === undefined || String(value).trim() === "";
}

function numericValues(rows: Record<string, unknown>[], column: string) {
  return rows.map((row) => Number(row[column])).filter(Number.isFinite);
}

function quantile(values: number[], percentile: number) {
  if (!values.length) return null;
  const sorted = [...values].sort((a, b) => a - b);
  return sorted[Math.max(0, Math.min(sorted.length - 1, Math.floor((sorted.length - 1) * percentile)))];
}

function normalize(value: unknown) {
  return String(value ?? "").trim().toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "");
}

export function predictorEligibility(column: string, dataset: LocalDataset) {
  if (column === dataset.target) return { role: "target", reason: "Target column" };
  if (dataset.original_target_label && column === dataset.original_target_label) {
    return { role: "original_target_label", reason: "Original target-label field" };
  }
  if (dataset.split_columns?.includes(column) || /(^|_)(split|fold|partition|sample_role)($|_)/i.test(column)) {
    return { role: "split_indicator", reason: "Split or fold indicator" };
  }
  if (dataset.system_columns?.includes(column) || /(^|_)(atlas|system|row)(_id|_key|_metadata)?($|_)/i.test(column)) {
    return { role: "system_metadata", reason: "System metadata field" };
  }
  if (dataset.prohibited_columns?.includes(column)) {
    return { role: "prohibited", reason: "Explicitly prohibited variable" };
  }
  const targetAlias = normalize(dataset.target);
  const columnAlias = normalize(column);
  if (targetAlias && (columnAlias === targetAlias || columnAlias.startsWith(`${targetAlias}_`))) {
    return { role: "target_derived", reason: "Target-derived field" };
  }
  if (/target|outcome|future|post[_ ]|label|response/i.test(column)) {
    return { role: "potential_leakage", reason: "Potential post-outcome or target-derived field" };
  }
  return { role: "eligible", reason: "" };
}

export function profileFeaturesInBrowser(
  dataset: LocalDataset,
  rows: Record<string, unknown>[],
  scope: Extract<FeatureProfileScope, "complete_browser_dataset" | "preview_profile">,
): FeatureProfileResponse {
  const problemType = dataset.problem_type ?? "classification";
  // Browser rows do not prove Analysis Partition membership. Keep this fallback
  // structural-only; all target association must come from an exact backend
  // development-population materialization with the sealed holdout excluded.
  const eventValue = dataset.event_value ?? null;
  const selected = new Set(dataset.selected_columns ?? []);
  const features = dataset.headers.map((column): FeatureProfileRow => {
    const eligibility = predictorEligibility(column, dataset);
    const eligible = eligibility.role === "eligible";
    const values = rows.map((row) => row[column]);
    const numbers = numericValues(rows, column);
    const numeric = numbers.length / Math.max(values.filter((value) => !isMissing(value)).length, 1) >= 0.8;
    const average = numbers.length ? numbers.reduce((sum, value) => sum + value, 0) / numbers.length : null;
    const variance = average === null || numbers.length < 2 ? null : numbers.reduce((sum, value) => sum + (value - average) ** 2, 0) / (numbers.length - 1);
    return {
      selected: eligible && selected.has(column),
      predictor: column,
      role: eligibility.role,
      datatype: numeric ? "numeric" : "categorical",
      iv: null,
      ivStrength: null,
      correlationWithTarget: null,
      correlationStrength: null,
      associationStatus: "not_evaluated",
      missingCount: values.filter(isMissing).length,
      missingPercent: values.length ? values.filter(isMissing).length / values.length : 0,
      distinctCount: new Set(values.filter((value) => !isMissing(value)).map(String)).size,
      mean: average,
      standardDeviation: variance === null ? null : Math.sqrt(variance),
      minimum: numbers.length ? Math.min(...numbers) : null,
      firstQuartile: quantile(numbers, 0.25),
      median: quantile(numbers, 0.5),
      thirdQuartile: quantile(numbers, 0.75),
      maximum: numbers.length ? Math.max(...numbers) : null,
      leakageStatus: eligible ? "eligible" : "locked",
      eligibilityStatus: eligible ? "eligible" : "excluded",
      exclusionReason: eligibility.reason,
    };
  });
  return {
    ok: true,
    profileScope: scope,
    profiledRowCount: rows.length,
    registeredRowCount: dataset.registered_row_count ?? rows.length,
    problemType,
    target: dataset.target ?? "",
    eventValue,
    selectedColumns: dataset.selected_columns,
    features,
    warning:
      "Browser rows provide structural statistics only. Target-directed evidence is withheld until the backend verifies the exact development population and excludes the sealed holdout.",
  };
}

export async function fetchFullFeatureProfile(dataset: LocalDataset, projectId: string): Promise<FeatureProfileResponse> {
  const identity = requireLocalDatasetCanonicalIdentity(
    projectId,
    dataset,
    "Feature profiling dataset identity",
  );
  const response = await fetch(`${API_BASE}/data/feature-profile`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      project_id: projectId,
      expected_dataset_id: identity.dataset_id,
      expected_dataset_version_id: identity.dataset_version_id,
      dataset_version: identity.dataset_version_id,
      target: dataset.target,
      event_value: dataset.event_value,
      non_event_value: dataset.non_event_value,
      selected_columns: dataset.selected_columns,
      problem_type: dataset.problem_type,
    }),
  });
  const payload = await response.json().catch(() => null);
  if (!response.ok || !payload?.ok) throw new Error(payload?.detail ?? "Full-dataset predictor profiling is unavailable.");
  assertExactDatasetIdentity(identity, payload, "Full-dataset feature profile response");
  return payload as FeatureProfileResponse;
}

export function featureMetric(row: FeatureProfileRow, problemType: "classification" | "regression") {
  return problemType === "regression" ? row.correlationWithTarget : row.iv;
}
