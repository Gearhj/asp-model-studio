import {
  assertExactDatasetActivation,
  type CanonicalDatasetIdentity,
} from "./datasetIdentity";

export const DATASET_API_BASE =
  (import.meta.env?.VITE_API_BASE as string | undefined)?.replace(/\/$/, "") ||
  "http://127.0.0.1:8001/api";

export type AtlasUser = {
  userId: string;
  displayName: string;
  email?: string;
  role: "admin" | "user" | string;
  status?: string;
  createdAt?: string;
  updatedAt?: string;
  lastLoginAt?: string;
  lastActiveAt?: string;
  failedLoginCount?: number;
  lockedUntil?: string | null;
  projectCount?: number;
  evidenceCount?: number;
  validationCount?: number;
  exportCount?: number;
};

export type DatasetVersionSummary = {
  versionId: string;
  createdAt: string;
  createdBy?: string;
  originalFilename?: string;
  hash?: string;
  rowCount: number;
  columnCount: number;
  warnings?: string[];
};

export type DatasetSummary = {
  datasetId: string;
  name: string;
  description?: string;
  domain?: string;
  sourceType?: string;
  ownerUserId?: string;
  ownerDisplayName?: string;
  createdAt?: string;
  updatedAt?: string;
  archived?: boolean;
  versionCount: number;
  latestVersion?: DatasetVersionSummary;
  /** Exact immutable version created by a dataset-creation response. */
  created_dataset_version_id?: string;
  /** Camel-case transport alias for created_dataset_version_id. */
  createdDatasetVersionId?: string;
  /** Exact immutable version descriptor created by this response. */
  created_version?: DatasetVersionSummary;
  access?: { userId: string; role: string }[];
  linkedProjects?: { projectId: string; versionId: string; datasetRole: string }[];
  datasetRole?: string;
  sourceInfo?: Record<string, unknown>;
};

export type DatasetProfile = {
  rowCount: number;
  columnCount: number;
  profiledRows: number;
  schema: Array<{
    name: string;
    dtype: string;
    missingPctSample: number;
    distinctSample: number;
    min?: number | null;
    max?: number | null;
    mean?: number | null;
    std?: number | null;
  }>;
  targetCandidates: string[];
  warnings: string[];
  duplicateRowsSample: number;
};

export type DatasetPreview = {
  columns: string[];
  rows: Record<string, unknown>[];
};

export type ProjectDatasetLink = {
  projectId: string;
  datasetId: string;
  versionId: string;
  datasetRole: string;
  linkedAt: string;
  dataset: DatasetSummary;
};

/** Authoritative identity and activated data shape returned by the backend. */
export type DatasetActivationResponse = CanonicalDatasetIdentity & {
  ok: true;
  row_count: number;
  column_count: number;
  headers: string[];
  selected_columns: string[];
  /** Monotonic durable-selection revision committed by the backend. */
  activation_revision: string | number;
  /** Durable project-to-dataset authorization/link record. */
  link: Record<string, unknown> & {
    link_status: "active";
  };
  /** Durable exact active-modeling-version selection. */
  active_selection: Record<string, unknown> & {
    activation_status: "active";
    activation_revision: string | number;
  };
  /** Server-reconciled history/effective validity committed with activation. */
  workflow_effective_state?: unknown;
};

export type WorkspaceDatasetRegistrationResponse =
  CanonicalDatasetIdentity & {
    ok: true;
    dataset: DatasetSummary;
    created_dataset_version_id: string;
    created_version: DatasetVersionSummary;
  };

export type SystemDiagnostics = {
  ok: boolean;
  generatedAt: string;
  currentUser: AtlasUser;
  artifactRoot: string;
  datasetCount: number;
  archivedCount: number;
  projectLinkCount: number;
  checks: Array<{ id: string; label: string; status: "pass" | "warning" | "fail" | string; detail: string }>;
};

async function jsonFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${DATASET_API_BASE}${path}`, {
    credentials: "include",
    ...init,
    headers: {
      ...(init?.body instanceof FormData ? {} : { "Content-Type": "application/json" }),
      ...(init?.headers ?? {}),
    },
  });
  const payload = await response.json().catch(() => null);
  if (!response.ok || payload?.ok === false) {
    throw new Error(payload?.detail ?? payload?.error ?? `ATLAS dataset request failed with HTTP ${response.status}.`);
  }
  return payload as T;
}

export async function listDatasets(includeArchived = false) {
  const payload = await jsonFetch<{ ok: true; datasets: DatasetSummary[]; currentUser: AtlasUser }>(
    `/datasets${includeArchived ? "?include_archived=true" : ""}`
  );
  return payload;
}

export async function getDataset(datasetId: string) {
  const payload = await jsonFetch<{ ok: true; dataset: DatasetSummary & { versions: DatasetVersionSummary[] } }>(`/datasets/${datasetId}`);
  return payload.dataset;
}

export async function uploadDataset(input: { file: File; name?: string; description?: string; domain?: string; sourceType?: string }) {
  const form = new FormData();
  form.append("file", input.file);
  if (input.name) form.append("name", input.name);
  if (input.description) form.append("description", input.description);
  if (input.domain) form.append("domain", input.domain);
  if (input.sourceType) form.append("sourceType", input.sourceType);
  const payload = await jsonFetch<{ ok: true; dataset: DatasetSummary }>("/datasets/upload", {
    method: "POST",
    body: form,
  });
  return payload.dataset;
}

export async function registerDataset(input: { name: string; description?: string; domain?: string; sourceType?: string; sourceInfo?: Record<string, unknown> }) {
  const payload = await jsonFetch<{ ok: true; dataset: DatasetSummary }>("/datasets/register", {
    method: "POST",
    body: JSON.stringify(input),
  });
  return payload.dataset;
}

/** Registers the CURRENT project's already-uploaded workspace dataset (transformed
 * or not) as a durable, versioned Dataset Library asset linked to this project. */
export async function registerWorkspaceDataset(input: { projectId: string; name: string; description?: string; domain?: string; tags?: string[] }) {
  return jsonFetch<WorkspaceDatasetRegistrationResponse>("/datasets/register-workspace", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

/** Reviewable duplicate suggestions for the registration flow -- never used to
 * silently substitute a different asset for the one being registered. */
export async function findSimilarDatasets(input: { name: string; target?: string | null; rowCount?: number; columnCount?: number }) {
  const params = new URLSearchParams({ name: input.name });
  if (input.target) params.set("target", input.target);
  if (input.rowCount != null) params.set("row_count", String(input.rowCount));
  if (input.columnCount != null) params.set("column_count", String(input.columnCount));
  const payload = await jsonFetch<{ ok: true; candidates: DatasetSummary[] }>(`/datasets/similar?${params.toString()}`);
  return payload.candidates;
}

export async function getDatasetProfile(datasetId: string, versionId?: string) {
  const path = versionId ? `/datasets/${datasetId}/versions/${versionId}/profile` : `/datasets/${datasetId}/profile`;
  const payload = await jsonFetch<{ ok: true; profile: DatasetProfile; dataset?: DatasetSummary; versionId?: string }>(path);
  return payload;
}

export async function getDatasetPreview(datasetId: string, versionId: string) {
  const payload = await jsonFetch<{ ok: true; preview: DatasetPreview }>(`/datasets/${datasetId}/versions/${versionId}/preview`);
  return payload.preview;
}

function recordIdentifier(record: Record<string, unknown>, snake: string, camel: string) {
  const value = record[snake] ?? record[camel];
  return typeof value === "string" ? value.trim() : "";
}

function activationRevision(value: unknown, context: string) {
  if (typeof value === "number" && Number.isSafeInteger(value) && value >= 1) return String(value);
  if (typeof value === "string" && value.trim()) {
    const revision = value.trim();
    if (/^\d+$/.test(revision) && Number(revision) >= 1) return revision;
  }
  throw new Error(`${context} did not return a durable activation revision.`);
}

/**
 * Rejects a response that merely hydrated process memory. Dataset activation is
 * complete only after the backend returns the committed authorization link and
 * exact active-version selection from the same durable revision.
 */
export function requireDurableDatasetActivation(
  expected: CanonicalDatasetIdentity,
  response: DatasetActivationResponse,
) {
  const canonical = assertExactDatasetActivation(expected, response);
  const link = response?.link;
  const selection = response?.active_selection;
  if (!link || typeof link !== "object" || link.link_status !== "active") {
    throw new Error("Dataset activation did not return an active durable project-dataset link.");
  }
  if (!selection || typeof selection !== "object" || selection.activation_status !== "active") {
    throw new Error("Dataset activation did not return an active durable dataset-version selection.");
  }

  const linkProjectId = recordIdentifier(link, "project_id", "projectId");
  const linkDatasetId = recordIdentifier(link, "dataset_id", "datasetId");
  const linkVersionId = recordIdentifier(link, "dataset_version_id", "versionId");
  if (linkProjectId !== canonical.project_id || linkDatasetId !== canonical.dataset_id) {
    throw new Error("The durable project-dataset link does not match the requested project and dataset.");
  }
  if (linkVersionId && linkVersionId !== canonical.dataset_version_id) {
    throw new Error("The durable project-dataset link names a different immutable dataset version.");
  }

  assertExactDatasetActivation(canonical, {
    project_id: recordIdentifier(selection, "project_id", "projectId"),
    dataset_id: recordIdentifier(selection, "dataset_id", "datasetId"),
    dataset_version_id: recordIdentifier(selection, "dataset_version_id", "datasetVersionId"),
  });
  const responseRevision = activationRevision(response.activation_revision, "Dataset activation");
  const selectionRevision = activationRevision(selection.activation_revision, "Active dataset selection");
  if (responseRevision !== selectionRevision) {
    throw new Error("Dataset activation returned contradictory durable selection revisions.");
  }
  return {
    canonical: {
      ...canonical,
      activation_revision: Number(responseRevision),
    },
    activationRevision: responseRevision,
  };
}

export async function activateDatasetVersion(datasetId: string, versionId: string, projectId: string) {
  const expected = {
    project_id: projectId,
    dataset_id: datasetId,
    dataset_version_id: versionId,
  };
  const response = await jsonFetch<DatasetActivationResponse>(
    `/datasets/${datasetId}/versions/${versionId}/activate?project_id=${encodeURIComponent(projectId)}`,
    { method: "POST" },
  );
  requireDurableDatasetActivation(expected, response);
  return response;
}

export async function linkDatasetToProject(projectId: string, datasetId: string, versionId: string, datasetRole = "modeling") {
  const payload = await jsonFetch<{ ok: true; link: ProjectDatasetLink }>(`/projects/${projectId}/datasets/link`, {
    method: "POST",
    body: JSON.stringify({ datasetId, versionId, datasetRole }),
  });
  return payload.link;
}

export async function listProjectDatasets(projectId: string) {
  const payload = await jsonFetch<{ ok: true; links: ProjectDatasetLink[] }>(`/projects/${projectId}/datasets`);
  return payload.links;
}

export async function unlinkProjectDataset(projectId: string, datasetId: string) {
  return jsonFetch<{ ok: true; removed: number }>(`/projects/${projectId}/datasets/${datasetId}`, { method: "DELETE" });
}

export async function getUsers() {
  return jsonFetch<{ ok: true; users: AtlasUser[]; currentUser: AtlasUser }>("/users");
}

export type DatasetAccessEntry = {
  user_id?: string;
  userId?: string;
  role: string;
  granted_by?: string;
  granted_at?: string;
};

export async function getDatasetAccess(datasetId: string) {
  return jsonFetch<{ ok: true; access: DatasetAccessEntry[] }>(`/datasets/${datasetId}/access`);
}

export async function grantDatasetAccess(datasetId: string, userId: string, role: string) {
  return jsonFetch<{ ok: true; grant: DatasetAccessEntry }>(`/datasets/${datasetId}/access/grant`, {
    method: "POST",
    body: JSON.stringify({ userId, role }),
  });
}

export async function revokeDatasetAccess(datasetId: string, userId: string) {
  return jsonFetch<{ ok: true; revoked: number }>(`/datasets/${datasetId}/access/revoke`, {
    method: "POST",
    body: JSON.stringify({ userId }),
  });
}

export async function archiveDataset(datasetId: string) {
  const payload = await jsonFetch<{ ok: true; dataset: DatasetSummary }>(`/datasets/${datasetId}/archive`, {
    method: "POST",
  });
  return payload.dataset;
}

export async function getSystemDiagnostics() {
  return jsonFetch<SystemDiagnostics>("/system/diagnostics");
}
