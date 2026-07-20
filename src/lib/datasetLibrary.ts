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

export async function getDatasetProfile(datasetId: string, versionId?: string) {
  const path = versionId ? `/datasets/${datasetId}/versions/${versionId}/profile` : `/datasets/${datasetId}/profile`;
  const payload = await jsonFetch<{ ok: true; profile: DatasetProfile; dataset?: DatasetSummary; versionId?: string }>(path);
  return payload;
}

export async function getDatasetPreview(datasetId: string, versionId: string) {
  const payload = await jsonFetch<{ ok: true; preview: DatasetPreview }>(`/datasets/${datasetId}/versions/${versionId}/preview`);
  return payload.preview;
}

export async function activateDatasetVersion(datasetId: string, versionId: string) {
  return jsonFetch<{ ok: true; datasetId: string; versionId: string; row_count: number; column_count: number; headers: string[]; selected_columns: string[] }>(
    `/datasets/${datasetId}/versions/${versionId}/activate`,
    { method: "POST" },
  );
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
