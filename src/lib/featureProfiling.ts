import type { LocalDataset } from "./localDataset";

const API_BASE =
  (import.meta.env.VITE_API_BASE as string | undefined)?.replace(/\/$/, "") ||
  "http://127.0.0.1:8001/api";

export type FeatureProfileScope = "full_dataset" | "complete_browser_dataset" | "preview_profile";

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
  profileScope: FeatureProfileScope;
  profiledRowCount: number;
  registeredRowCount: number;
  problemType: "classification" | "regression";
  target: string;
  eventValue?: unknown;
  selectedColumns: string[];
  features: FeatureProfileRow[];
  featureManifestVersion?: string | null;
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

function eventValueFor(dataset: LocalDataset, rows: Record<string, unknown>[]) {
  if (dataset.event_value !== undefined && dataset.event_value !== null && String(dataset.event_value) !== "") {
    return dataset.event_value;
  }
  if (!dataset.target) return null;
  const values = rows.map((row) => row[dataset.target as string]).filter((value) => !isMissing(value));
  return values.find((value) => String(value) === "1") ?? null;
}

function informationValue(rows: Record<string, unknown>[], column: string, target: string, eventValue: unknown) {
  if (!rows.length || eventValue === null || eventValue === undefined) return null;
  const valid = rows.filter((row) => !isMissing(row[target]));
  const targetValues = new Set(valid.map((row) => String(row[target])));
  if (targetValues.size !== 2) return null;
  const featureNumbers = numericValues(valid, column);
  const numeric = featureNumbers.length / Math.max(valid.length, 1) >= 0.8;
  const breaks = numeric && new Set(featureNumbers).size > 10
    ? Array.from({ length: 9 }, (_, index) => quantile(featureNumbers, (index + 1) / 10)).filter((value): value is number => value !== null)
    : [];
  const categoryCounts = new Map<string, number>();
  if (!numeric) {
    valid.forEach((row) => {
      const key = isMissing(row[column]) ? "__MISSING__" : String(row[column]);
      categoryCounts.set(key, (categoryCounts.get(key) ?? 0) + 1);
    });
  }
  const topCategories = new Set([...categoryCounts.entries()].sort((a, b) => b[1] - a[1]).slice(0, 50).map(([key]) => key));
  const bucketFor = (value: unknown) => {
    if (isMissing(value)) return "__MISSING__";
    if (!numeric) return topCategories.has(String(value)) ? String(value) : "__OTHER__";
    const number = Number(value);
    if (!Number.isFinite(number)) return "__MISSING__";
    const index = breaks.findIndex((boundary) => number <= boundary);
    return index < 0 ? `bin_${breaks.length}` : `bin_${index}`;
  };
  const buckets = new Map<string, { event: number; nonEvent: number }>();
  valid.forEach((row) => {
    const key = bucketFor(row[column]);
    const bucket = buckets.get(key) ?? { event: 0, nonEvent: 0 };
    if (String(row[target]) === String(eventValue)) bucket.event += 1;
    else bucket.nonEvent += 1;
    buckets.set(key, bucket);
  });
  const totalEvent = [...buckets.values()].reduce((sum, bucket) => sum + bucket.event, 0);
  const totalNonEvent = [...buckets.values()].reduce((sum, bucket) => sum + bucket.nonEvent, 0);
  if (!totalEvent || !totalNonEvent) return null;
  const smoothing = 0.5;
  const denominatorEvent = totalEvent + smoothing * buckets.size;
  const denominatorNonEvent = totalNonEvent + smoothing * buckets.size;
  let iv = 0;
  buckets.forEach((bucket) => {
    const eventDistribution = (bucket.event + smoothing) / denominatorEvent;
    const nonEventDistribution = (bucket.nonEvent + smoothing) / denominatorNonEvent;
    iv += (eventDistribution - nonEventDistribution) * Math.log(eventDistribution / nonEventDistribution);
  });
  return Number.isFinite(iv) ? Math.max(0, iv) : null;
}

function correlation(rows: Record<string, unknown>[], column: string, target: string) {
  const pairs = rows
    .map((row) => [Number(row[column]), Number(row[target])])
    .filter(([x, y]) => Number.isFinite(x) && Number.isFinite(y));
  if (pairs.length < 3) return null;
  const meanX = pairs.reduce((sum, pair) => sum + pair[0], 0) / pairs.length;
  const meanY = pairs.reduce((sum, pair) => sum + pair[1], 0) / pairs.length;
  const numerator = pairs.reduce((sum, pair) => sum + (pair[0] - meanX) * (pair[1] - meanY), 0);
  const denominator = Math.sqrt(pairs.reduce((sum, pair) => sum + (pair[0] - meanX) ** 2, 0)) * Math.sqrt(pairs.reduce((sum, pair) => sum + (pair[1] - meanY) ** 2, 0));
  const value = numerator / denominator;
  return Number.isFinite(value) ? value : null;
}

function strength(value: number | null, problemType: "classification" | "regression") {
  if (value === null) return "Not Evaluated";
  const magnitude = Math.abs(value);
  if (problemType === "regression") return magnitude < 0.05 ? "Very Weak" : magnitude < 0.15 ? "Weak" : magnitude < 0.3 ? "Moderate" : "Strong";
  return magnitude < 0.02 ? "Not Predictive" : magnitude < 0.1 ? "Weak" : magnitude < 0.3 ? "Medium" : magnitude < 0.5 ? "Strong" : "Very Strong";
}

export function profileFeaturesInBrowser(
  dataset: LocalDataset,
  rows: Record<string, unknown>[],
  scope: Exclude<FeatureProfileScope, "full_dataset">,
): FeatureProfileResponse {
  if (!dataset.target) throw new Error("Select a target before profiling predictors.");
  const problemType = dataset.problem_type ?? "classification";
  const eventValue = eventValueFor(dataset, rows);
  const selected = new Set(dataset.selected_columns ?? []);
  const features = dataset.headers.map((column): FeatureProfileRow => {
    const eligibility = predictorEligibility(column, dataset);
    const eligible = eligibility.role === "eligible";
    const values = rows.map((row) => row[column]);
    const numbers = numericValues(rows, column);
    const numeric = numbers.length / Math.max(values.filter((value) => !isMissing(value)).length, 1) >= 0.8;
    const metric = !eligible
      ? null
      : problemType === "regression"
        ? numeric ? correlation(rows, column, dataset.target as string) : null
        : informationValue(rows, column, dataset.target as string, eventValue);
    const average = numbers.length ? numbers.reduce((sum, value) => sum + value, 0) / numbers.length : null;
    const variance = average === null || numbers.length < 2 ? null : numbers.reduce((sum, value) => sum + (value - average) ** 2, 0) / (numbers.length - 1);
    return {
      selected: eligible && selected.has(column),
      predictor: column,
      role: eligibility.role,
      datatype: numeric ? "numeric" : "categorical",
      iv: problemType === "classification" ? metric : null,
      ivStrength: problemType === "classification" ? strength(metric, problemType) : null,
      correlationWithTarget: problemType === "regression" ? metric : null,
      correlationStrength: problemType === "regression" ? strength(metric, problemType) : null,
      associationStatus: metric === null ? "not_evaluated" : "evaluated",
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
    target: dataset.target,
    eventValue,
    selectedColumns: dataset.selected_columns,
    features,
    warning: scope === "preview_profile" ? "Predictor statistics are based on preview rows and are not full-dataset evidence." : undefined,
  };
}

export async function fetchFullFeatureProfile(dataset: LocalDataset): Promise<FeatureProfileResponse> {
  const response = await fetch(`${API_BASE}/data/feature-profile`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      target: dataset.target,
      event_value: dataset.event_value,
      non_event_value: dataset.non_event_value,
      selected_columns: dataset.selected_columns,
      problem_type: dataset.problem_type,
    }),
  });
  const payload = await response.json().catch(() => null);
  if (!response.ok || !payload?.ok) throw new Error(payload?.detail ?? "Full-dataset predictor profiling is unavailable.");
  return payload as FeatureProfileResponse;
}

export function featureMetric(row: FeatureProfileRow, problemType: "classification" | "regression") {
  return problemType === "regression" ? row.correlationWithTarget : row.iv;
}
