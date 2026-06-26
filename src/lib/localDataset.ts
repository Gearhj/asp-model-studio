export type LocalDataset = {
  headers: string[];
  rows: Record<string, unknown>[];
  target: string | null;
  selected_columns: string[];
};

const STORAGE_KEY = "modeling-tool-dataset";
const MAX_LOCAL_ROWS = 5000;

export function saveLocalDataset(dataset: LocalDataset) {
  const compactDataset = {
    ...dataset,
    rows: dataset.rows.slice(0, MAX_LOCAL_ROWS),
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
    if (!Array.isArray(parsed.headers) || !Array.isArray(parsed.rows)) return null;
    return {
      headers: parsed.headers,
      rows: parsed.rows as Record<string, unknown>[],
      target: parsed.target ?? null,
      selected_columns: parsed.selected_columns ?? parsed.headers.filter((header) => header !== parsed.target),
    };
  } catch {
    return null;
  }
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
