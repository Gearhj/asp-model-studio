// ATLAS Durable Model Registry -- browser client for /api/models and
// /api/model-versions. This is the ONLY place frontend code should read/write
// durable model identity. Every call is authorized server-side
// (authorize_modeling_scope on every model_registry_service entry point);
// this layer adds no authorization of its own.
export type ModelStatus = "active" | "archived";
export type ApprovalStatus = "unreviewed" | "approved" | "rejected";
export type ValidationStatus = "not_validated" | "in_progress" | "validated" | "failed";
export type DocumentationStatus = "not_documented" | "in_progress" | "documented";

export type Model = {
  modelId: string;
  projectId: string | null;
  name: string;
  problemType: "classification" | "regression" | null;
  status: string;
  ownerUserId: string | null;
  createdAt: string;
  updatedAt: string;
  currentVersionId: string | null;
  currentVersionGeneration?: number;
  archived: boolean | number;
  archivedAt: string | null;
  tags: string[];
  description: string | null;
};

export type ModelVersion = {
  modelVersionId: string;
  modelId: string;
  versionNumber: number;
  trainingRunId: string | null;
  projectId: string | null;
  datasetId: string | null;
  datasetVersionId: string | null;
  featureManifestVersion: string | null;
  candidateId?: string | null;
  validationDesignId?: string | null;
  splitId?: string | null;
  algorithm: string | null;
  algorithmVersion: string | null;
  hyperparameters: Record<string, unknown>;
  trainingParameters: Record<string, unknown>;
  metricsSummary: Record<string, unknown>;
  evaluationSummary: Record<string, unknown>;
  interpretationSummary: Record<string, unknown>;
  artifactReference: string | null;
  artifactFormat: string | null;
  trainingTimestamp: string | null;
  checksum: string | null;
  publicationStatus?: "staging" | "finalized" | "quarantined" | "legacy_invalid";
  lineageStatus?: "verified" | "unresolved" | "invalid";
  quarantineReason?: string | null;
  artifactVerifiedAt?: string | null;
  finalizedAt?: string | null;
  idempotencyKey?: string | null;
  approvalStatus: ApprovalStatus;
  validationStatus: ValidationStatus;
  documentationStatus: DocumentationStatus;
  lineage: Record<string, unknown>;
  archivedAt: string | null;
  createdBy: string | null;
  createdAt: string;
};

const API_BASE =
  (import.meta.env?.VITE_API_BASE as string | undefined)?.replace(/\/$/, "") ||
  "http://127.0.0.1:8001/api";

async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, { credentials: "include" });
  const payload = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = payload?.detail;
    throw new Error(typeof detail === "string" ? detail : `Model registry request failed (${response.status}): ${path}`);
  }
  return payload as T;
}

async function postJson<T>(path: string, body?: unknown): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    credentials: "include",
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  const payload = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = payload?.detail;
    throw new Error(typeof detail === "string" ? detail : `Model registry request failed (${response.status}): ${path}`);
  }
  return payload as T;
}

export async function listModels(projectId: string, filters: { problemType?: string; status?: string; includeArchived?: boolean; limit?: number } = {}): Promise<Model[]> {
  const params = new URLSearchParams({ projectId });
  if (filters.problemType) params.set("problemType", filters.problemType);
  if (filters.status) params.set("status", filters.status);
  if (filters.includeArchived) params.set("includeArchived", "true");
  if (filters.limit) params.set("limit", String(filters.limit));
  const payload = await getJson<{ models: Model[] }>(`/models?${params.toString()}`);
  return payload.models;
}

export async function getModel(modelId: string): Promise<Model> {
  const payload = await getJson<{ model: Model }>(`/models/${encodeURIComponent(modelId)}`);
  return payload.model;
}

export async function listVersions(modelId: string, filters: { algorithm?: string; includeArchived?: boolean } = {}): Promise<ModelVersion[]> {
  const params = new URLSearchParams();
  if (filters.algorithm) params.set("algorithm", filters.algorithm);
  if (filters.includeArchived) params.set("includeArchived", "true");
  const payload = await getJson<{ modelVersions: ModelVersion[] }>(`/models/${encodeURIComponent(modelId)}/versions?${params.toString()}`);
  return payload.modelVersions;
}

export async function getModelVersion(modelVersionId: string): Promise<ModelVersion> {
  const payload = await getJson<{ modelVersion: ModelVersion }>(`/model-versions/${encodeURIComponent(modelVersionId)}`);
  return payload.modelVersion;
}

export async function compareModelVersions(modelVersionIds: string[]): Promise<{ versions: Record<string, unknown>[] }> {
  return getJson(`/model-versions/compare?ids=${modelVersionIds.map(encodeURIComponent).join(",")}`);
}

export async function archiveModel(modelId: string): Promise<Model> {
  const payload = await postJson<{ model: Model }>(`/models/${encodeURIComponent(modelId)}/archive`);
  return payload.model;
}

export async function archiveModelVersion(modelVersionId: string): Promise<ModelVersion> {
  const payload = await postJson<{ modelVersion: ModelVersion }>(`/model-versions/${encodeURIComponent(modelVersionId)}/archive`);
  return payload.modelVersion;
}

export async function getDocumentationBundle(modelVersionId: string): Promise<Record<string, unknown>> {
  return getJson(`/model-versions/${encodeURIComponent(modelVersionId)}/documentation-bundle`);
}
