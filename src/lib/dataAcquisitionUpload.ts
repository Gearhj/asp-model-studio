export const DEFAULT_BROWSER_UPLOAD_LIMIT_BYTES = 25 * 1024 * 1024;
export const DEFAULT_BROWSER_MAX_ROWS = 250_000;
export const DEFAULT_BROWSER_MAX_COLUMNS = 500;

export const BROWSER_PARSE_EXTENSIONS = new Set(["csv", "txt", "json"]);
export const BACKEND_CSV_IMPORT_EXTENSIONS = new Set(["csv", "txt"]);
export const RECOGNIZED_UPLOAD_EXTENSIONS = new Set([
  "csv",
  "txt",
  "json",
  "xlsx",
  "xls",
  "parquet",
  "feather",
  "sas7bdat",
  "pkl",
  "pickle",
  "zip",
]);

export type UploadDecision =
  | { mode: "browser"; extension: string; message: string }
  | { mode: "backend"; extension: string; message: string }
  | { mode: "recognized_unsupported"; extension: string; message: string }
  | { mode: "invalid"; extension: string; message: string };

export type BackendImportPayload = {
  ok?: boolean;
  rows?: unknown;
  row_count?: unknown;
  rows_loaded?: unknown;
  total_rows?: unknown;
  n_rows?: unknown;
  cols?: unknown;
  columns?: unknown;
  headers?: unknown;
  target?: unknown;
  selected_columns?: unknown;
  sample_rows?: unknown;
  preview_rows?: unknown;
  max_upload_mb?: unknown;
  filename?: unknown;
};

export type NormalizedBackendImport = {
  headers: string[];
  previewRows: Record<string, unknown>[];
  rowCount: number;
  columnCount: number;
  target: string;
  selectedColumns: string[];
  filename: string;
};

export type SelectedDatasetViewInput = {
  headers: string[];
  rows: Record<string, unknown>[];
  selectedColumns: string[];
  target?: string | null;
};

export type SelectedDatasetView = {
  headers: string[];
  rows: Record<string, unknown>[];
  selectedColumns: string[];
};

export function formatUploadBytes(bytes: number) {
  if (!Number.isFinite(bytes) || bytes < 0) return "unknown size";
  const mb = bytes / 1024 / 1024;
  return `${mb.toFixed(mb >= 10 ? 1 : 2)} MB`;
}

export function uploadExtension(fileName: string) {
  return (fileName.split(".").pop() ?? "").trim().toLowerCase();
}

export function guessTargetFromHeaders(headers: string[]) {
  return (
    headers.find((header) => /^(target|label|class|bad|default|fraud|response|outcome|event)$/i.test(header)) ??
    headers.find((header) => /target|label|outcome/i.test(header)) ??
    ""
  );
}

export function getUploadDecision(input: {
  fileName: string;
  fileSize: number;
  browserLimitBytes?: number;
}): UploadDecision {
  const extension = uploadExtension(input.fileName);
  const browserLimitBytes = input.browserLimitBytes ?? DEFAULT_BROWSER_UPLOAD_LIMIT_BYTES;

  if (!RECOGNIZED_UPLOAD_EXTENSIONS.has(extension)) {
    return {
      mode: "invalid",
      extension,
      message: `.${extension || "unknown"} is not an allowed project data file type. Upload CSV, JSON, Excel, Parquet, Feather, SAS, Pickle, or ZIP.`,
    };
  }

  if (input.fileSize > browserLimitBytes) {
    if (BACKEND_CSV_IMPORT_EXTENSIONS.has(extension)) {
      return {
        mode: "backend",
        extension,
        message: `This ${formatUploadBytes(input.fileSize)} file exceeds the browser preview limit, so ATLAS will import it through the backend and show a governed preview sample.`,
      };
    }
    return {
      mode: "recognized_unsupported",
      extension,
      message: `${extension.toUpperCase()} files are recognized, but large-file backend import currently supports CSV and TXT only. Convert this file to CSV or use the Python Loader.`,
    };
  }

  if (BROWSER_PARSE_EXTENSIONS.has(extension)) {
    return {
      mode: "browser",
      extension,
      message: "ATLAS will parse this file in the browser preview.",
    };
  }

  return {
    mode: "recognized_unsupported",
    extension,
    message: `${extension.toUpperCase()} files are recognized but require backend parser support before they can be loaded into the browser preview.`,
  };
}

function asStringArray(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value
    .map((item) => {
      if (typeof item === "string") return item;
      if (item && typeof item === "object" && "name" in item) return String((item as { name: unknown }).name ?? "");
      return String(item ?? "");
    })
    .map((item) => item.trim())
    .filter(Boolean);
}

function asRecords(value: unknown): Record<string, unknown>[] {
  if (!Array.isArray(value)) return [];
  return value.filter((row): row is Record<string, unknown> => !!row && typeof row === "object" && !Array.isArray(row));
}

function asPositiveNumber(...values: unknown[]) {
  for (const value of values) {
    const numeric = Number(value);
    if (Number.isFinite(numeric) && numeric >= 0) return numeric;
  }
  return 0;
}

export function normalizeBackendImportResponse(payload: BackendImportPayload): NormalizedBackendImport {
  const previewRows = asRecords(payload.sample_rows ?? payload.preview_rows);
  const headers =
    asStringArray(payload.headers).length > 0
      ? asStringArray(payload.headers)
      : asStringArray(payload.columns).length > 0
        ? asStringArray(payload.columns)
        : Array.from(new Set(previewRows.flatMap((row) => Object.keys(row))));
  const rowCount = asPositiveNumber(payload.row_count, payload.rows_loaded, payload.total_rows, payload.n_rows, payload.rows, previewRows.length);
  const columnCount = asPositiveNumber(payload.cols, headers.length);
  const target = typeof payload.target === "string" && headers.includes(payload.target) ? payload.target : guessTargetFromHeaders(headers);
  const selectedColumns = asStringArray(payload.selected_columns).filter((column) => headers.includes(column) && column !== target);

  return {
    headers,
    previewRows,
    rowCount,
    columnCount,
    target,
    selectedColumns: selectedColumns.length ? selectedColumns : headers.filter((header) => header !== target),
    filename: typeof payload.filename === "string" ? payload.filename : "",
  };
}

function uniqueStrings(values: string[]) {
  const seen = new Set<string>();
  return values.filter((value) => {
    const key = String(value ?? "").trim();
    if (!key || seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

export function buildSelectedDatasetView(input: SelectedDatasetViewInput): SelectedDatasetView {
  const headers = uniqueStrings(input.headers.map(String));
  const headerSet = new Set(headers);
  const target = input.target && headerSet.has(input.target) ? input.target : "";
  const requestedFeatures = uniqueStrings(input.selectedColumns.map(String)).filter(
    (column) => headerSet.has(column) && column !== target
  );
  const selectedColumns = requestedFeatures.length
    ? requestedFeatures
    : headers.filter((header) => header !== target);
  const persistedHeaders = target ? [...selectedColumns, target] : [...selectedColumns];

  const rows = input.rows.map((row) => {
    const filtered: Record<string, unknown> = {};
    persistedHeaders.forEach((column) => {
      filtered[column] = row[column];
    });
    return filtered;
  });

  return {
    headers: persistedHeaders,
    rows,
    selectedColumns,
  };
}

export function backendImportFailureMessage(errorMessage: string, maxUploadMb?: number) {
  const limitText = Number.isFinite(maxUploadMb) ? ` The current backend upload limit is ${maxUploadMb} MB.` : "";
  return `Backend import failed: ${errorMessage || "ATLAS could not load this file."}${limitText} Use a smaller CSV, increase ATLAS_MAX_UPLOAD_BYTES, or use SQL/Python Loader.`;
}

export function dataAcquisitionDisabledReason(input: {
  isImporting: boolean;
  hasHeaders: boolean;
  hasTarget: boolean;
  importError?: string | null;
}) {
  if (input.isImporting) return "ATLAS is still importing the dataset through the backend.";
  if (!input.hasHeaders) {
    return input.importError ? "Resolve the data import error before continuing." : "Load a dataset or save source metadata before continuing.";
  }
  if (!input.hasTarget) return "Select the target variable before continuing.";
  return "";
}
