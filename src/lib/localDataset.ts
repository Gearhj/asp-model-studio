import { getCachedProjectId } from "./activeProjectContext";
import { getCachedUserId } from "./authSession";

export type LocalDataset = {
  headers: string[];
  rows: Record<string, unknown>[];
  target: string | null;
  selected_columns: string[];
  problem_type?: "classification" | "regression";
  registered_row_count?: number;
  browser_data_complete?: boolean;
  /** Canonical Dataset Library asset identifier returned by the backend. */
  dataset_id?: string;
  /** Canonical immutable Dataset Library version identifier returned by the backend. */
  dataset_version_id?: string;
  /**
   * @deprecated Compatibility-only field for old browser snapshots. It is not
   * canonical identity and must never be promoted to dataset_version_id.
   */
  dataset_version?: string;
  event_value?: unknown;
  non_event_value?: unknown;
  original_target_label?: string;
  split_columns?: string[];
  system_columns?: string[];
  prohibited_columns?: string[];
  dataset_library?: {
    datasetId: string;
    versionId: string;
    datasetName: string;
    datasetRole?: string;
    sourceType?: string;
    rowCount?: number;
    columnCount?: number;
    linkedAt?: string;
  };
  data_access?: import("./enterpriseDataAccess").DataAccessMetadata;
  data_quality?: import("./enterpriseDataAccess").DataQualitySummary;
};

// Browser dataset storage contract (Predictive Modeling Repair Stage 6.2 --
// ATLAS_MODELING_STATE_ISOLATION_PLAN.md documents the equivalent backend
// problem for DATASTORE/RESULTS; this is the frontend counterpart for the
// one piece of modeling state the browser itself caches).
//
// Root cause fixed here: the dataset cache used to live under one single,
// unscoped sessionStorage key ("modeling-tool-dataset"). Any project opened
// in the same browser tab -- including a brand-new project, which never
// wrote anything for the prior project to be overwritten -- would read
// whatever the previous project last wrote there. Scoping the key by
// (userId, projectId) makes that structurally impossible: a new/different
// project resolves a key that was never written, so it naturally sees an
// honest empty state instead of another project's cached rows.
//
// sessionStorage is already scoped to one browsing context (tab) by the
// browser itself, so this key format is not trying to solve cross-tab
// leakage (the browser already prevents that) -- it solves same-tab,
// sequential project/user switching within one SPA session.
const KEY_PREFIX = "atlas:modeling-dataset";
const LEGACY_STORAGE_KEY = "modeling-tool-dataset";
const MAX_LOCAL_ROWS = 5000;
const FALLBACK_USER_ID = "anonymous";

let legacyKeyQuarantined = false;

export function buildProjectDatasetStorageKey(userId: string, projectId: string): string {
  const safeUserId = userId || FALLBACK_USER_ID;
  const safeProjectId = projectId || "unassigned";
  return `${KEY_PREFIX}:${safeUserId}:${safeProjectId}`;
}

/**
 * Discard the legacy unscoped key on first use after the Stage 6.2 upgrade.
 * Never maps its contents into any project -- a stale unscoped snapshot has
 * no reliable (user, project) identity, so the only safe move is to drop it.
 */
export function clearLegacyUnscopedDatasetState() {
  if (typeof sessionStorage === "undefined") return;
  const hadLegacyState = sessionStorage.getItem(LEGACY_STORAGE_KEY) !== null;
  if (!hadLegacyState) return;
  sessionStorage.removeItem(LEGACY_STORAGE_KEY);
  if (!legacyKeyQuarantined) {
    legacyKeyQuarantined = true;
    // eslint-disable-next-line no-console
    console.debug(
      "[ATLAS] Discarded an obsolete unscoped modeling-dataset cache from before the browser dataset-state isolation repair. It was not applied to any project."
    );
  }
}

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
    registered_row_count: Number.isFinite(Number(dataset.registered_row_count)) ? Number(dataset.registered_row_count) : dataset.rows.length,
    browser_data_complete: dataset.browser_data_complete === true,
    dataset_id: typeof dataset.dataset_id === "string" && dataset.dataset_id.trim() ? dataset.dataset_id.trim() : undefined,
    dataset_version_id:
      typeof dataset.dataset_version_id === "string" && dataset.dataset_version_id.trim()
        ? dataset.dataset_version_id.trim()
        : undefined,
    dataset_version: typeof dataset.dataset_version === "string" ? dataset.dataset_version : undefined,
    event_value: dataset.event_value,
    non_event_value: dataset.non_event_value,
    original_target_label: typeof dataset.original_target_label === "string" ? dataset.original_target_label : undefined,
    split_columns: uniqueStrings(dataset.split_columns ?? []),
    system_columns: uniqueStrings(dataset.system_columns ?? []),
    prohibited_columns: uniqueStrings(dataset.prohibited_columns ?? []),
    dataset_library: dataset.dataset_library,
    data_access: dataset.data_access,
    data_quality: dataset.data_quality,
  };
}

export function saveProjectDataset(userId: string, projectId: string, dataset: LocalDataset) {
  clearLegacyUnscopedDatasetState();
  const normalizedDataset = normalizeSelectedDataset(dataset) ?? dataset;
  const compactDataset = {
    ...normalizedDataset,
    rows: normalizedDataset.rows.slice(0, MAX_LOCAL_ROWS),
    browser_data_complete:
      normalizedDataset.browser_data_complete === true &&
      normalizedDataset.rows.length <= MAX_LOCAL_ROWS &&
      normalizedDataset.rows.length === (normalizedDataset.registered_row_count ?? normalizedDataset.rows.length),
  };

  try {
    sessionStorage.setItem(buildProjectDatasetStorageKey(userId, projectId), JSON.stringify(compactDataset));
    return compactDataset.rows.length === dataset.rows.length ? "full" : "sample";
  } catch {
    return "failed";
  }
}

export function loadProjectDataset(userId: string, projectId: string): LocalDataset | null {
  clearLegacyUnscopedDatasetState();
  if (typeof sessionStorage === "undefined") return null;
  const raw = sessionStorage.getItem(buildProjectDatasetStorageKey(userId, projectId));
  if (!raw) return null;

  try {
    const parsed = JSON.parse(raw) as Partial<LocalDataset>;
    return normalizeSelectedDataset(parsed);
  } catch {
    return null;
  }
}

export function clearProjectDataset(userId: string, projectId: string) {
  if (typeof sessionStorage === "undefined") return;
  sessionStorage.removeItem(buildProjectDatasetStorageKey(userId, projectId));
}

/** Sweep every user's scoped snapshot for one project -- used on project deletion, where the deleting caller's identity isn't necessarily the only identity that ever cached this project's data (e.g. a collaborator). */
export function clearProjectDatasetEverywhere(projectId: string) {
  if (typeof sessionStorage === "undefined" || !projectId) return;
  const suffix = `:${projectId}`;
  const keys = Array.from({ length: sessionStorage.length }, (_, index) => sessionStorage.key(index)).filter(
    (key): key is string => Boolean(key?.startsWith(`${KEY_PREFIX}:`) && key.endsWith(suffix))
  );
  keys.forEach((key) => sessionStorage.removeItem(key));
}

/** Clear every project snapshot cached under one user -- used on sign-out so the next signed-in identity in this tab can never read a prior user's cache. */
export function clearUserDatasetState(userId: string) {
  if (typeof sessionStorage === "undefined" || !userId) return;
  const prefix = `${KEY_PREFIX}:${userId}:`;
  const keys = Array.from({ length: sessionStorage.length }, (_, index) => sessionStorage.key(index)).filter(
    (key): key is string => Boolean(key?.startsWith(prefix))
  );
  keys.forEach((key) => sessionStorage.removeItem(key));
}

function ambientUserId(): string {
  return getCachedUserId() || FALLBACK_USER_ID;
}

function ambientProjectId(): string {
  return getCachedProjectId();
}

/**
 * Ambient-scope convenience wrappers -- resolve the current (userId,
 * projectId) the same way the backend's authorize_modeling_scope() resolves
 * ACTIVE_PROJECT_ID (server/core/modeling_scope.py), so the ~20 existing
 * Predictive Modeling call sites that read loadLocalDataset() do not each
 * need to be rewritten to thread userId/projectId through manually. Nothing
 * outside this module touches sessionStorage's raw key directly either way.
 */
export function saveLocalDataset(dataset: LocalDataset) {
  return saveProjectDataset(ambientUserId(), ambientProjectId(), dataset);
}

export function loadLocalDataset(): LocalDataset | null {
  return loadProjectDataset(ambientUserId(), ambientProjectId());
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

export function localDatasetVersion(dataset: LocalDataset | null): string {
  if (!dataset) return "";
  const selected = [...(dataset.selected_columns ?? [])].sort().join(",");
  const target = dataset.target ?? "";
  const problemType = dataset.problem_type ?? inferLocalProblemType(dataset) ?? "";
  return [
    target,
    problemType,
    dataset.rows.length,
    dataset.headers.length,
    selected.length,
    selected.slice(0, 240),
  ].join("|");
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
