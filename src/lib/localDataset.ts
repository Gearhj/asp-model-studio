export type LocalDataset = {
  headers: string[];
  rows: Record<string, unknown>[];
  target: string | null;
  selected_columns: string[];
  problem_type?: "classification" | "regression";
  data_access?: import("./enterpriseDataAccess").DataAccessMetadata;
  data_quality?: import("./enterpriseDataAccess").DataQualitySummary;
};

const STORAGE_KEY = "modeling-tool-dataset";
const MAX_LOCAL_ROWS = 5000;

function uniqueStrings(values: unknown[]) {
  const seen = new Set<string>();
  return values
    .map((value) => String(value ?? "").trim())
    .filter((value) => {
      if (!value || seen.has(value)) return false;
      seen.add(value);
      return true;
    });
}

function normalizeSelectedDataset(dataset: Partial<LocalDataset>): LocalDataset | null {
  if (!Array.isArray(dataset.headers) || !Array.isArray(dataset.rows)) return null;
  const headers = uniqueStrings(dataset.headers);
  const target = dataset.target && headers.includes(dataset.target) ? dataset.target : null;
  const hasExplicitSelectedColumns = Array.isArray(dataset.selected_columns);
  const selected = uniqueStrings(dataset.selected_columns ?? []).filter(
    (column) => headers.includes(column) && column !== target
  );
  const selectedColumns = hasExplicitSelectedColumns ? selected : headers.filter((header) => header !== target);
  const persistedHeaders = target ? [...selectedColumns, target] : [...selectedColumns];
  const rows = (dataset.rows as Record<string, unknown>[]).map((row) => {
    const filtered: Record<string, unknown> = {};
    persistedHeaders.forEach((header) => {
      filtered[header] = row?.[header];
    });
    return filtered;
  });

  return {
    headers: persistedHeaders,
    rows,
    target,
    selected_columns: selectedColumns,
    problem_type:
      dataset.problem_type === "classification" || dataset.problem_type === "regression"
        ? dataset.problem_type
        : undefined,
    data_access: dataset.data_access,
    data_quality: dataset.data_quality,
  };
}

export function saveLocalDataset(dataset: LocalDataset) {
  const normalizedDataset = normalizeSelectedDataset(dataset) ?? dataset;
  const compactDataset = {
    ...normalizedDataset,
    rows: normalizedDataset.rows.slice(0, MAX_LOCAL_ROWS),
  };

  try {
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify(compactDataset));
    return compactDataset.rows.length === dataset.rows.length ? "full" : "sample";
  } catch {
    return "failed";
  }
}

export function loadLocalDataset(): LocalDataset | null {
  const raw = sessionStorage.getItem(STORAGE_KEY);
  if (!raw) return null;

  try {
    const parsed = JSON.parse(raw) as Partial<LocalDataset>;
    return normalizeSelectedDataset(parsed);
  } catch {
    return null;
  }
}

export function inferLocalProblemType(dataset: LocalDataset | null): "classification" | "regression" | null {
  if (!dataset?.rows.length || !dataset.target) return null;
  if (dataset.problem_type === "classification" || dataset.problem_type === "regression") {
    return dataset.problem_type;
  }

  const values = dataset.rows
    .map((row) => row[dataset.target as string])
    .filter((value) => value !== null && value !== undefined && String(value).trim() !== "");
  if (!values.length) return null;

  const numericCount = values.filter((value) => Number.isFinite(Number(value))).length;
  const uniqueCount = new Set(values.map((value) => String(value))).size;
  if (numericCount / values.length >= 0.9 && uniqueCount > 10) return "regression";
  return "classification";
}

export function inferLocalColumns(dataset: LocalDataset) {
  return dataset.headers.map((name) => {
    const values = dataset.rows.slice(0, 1000).map((row) => row[name]);
    const nonMissing = values.filter((value) => value !== null && value !== undefined && value !== "");
    const numeric =
      nonMissing.length > 0 &&
      nonMissing.filter((value) => Number.isFinite(Number(value))).length / nonMissing.length >= 0.8;

    return {
      name,
      dtype: numeric ? "float64" : "object",
      role: dataset.target === name ? ("target" as const) : ("feature" as const),
    };
  });
}
