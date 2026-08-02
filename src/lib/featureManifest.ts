import {
  assertExactDatasetIdentity,
  type CanonicalDatasetIdentity,
} from "./datasetIdentity";

const API_BASE =
  (import.meta.env.VITE_API_BASE as string | undefined)?.replace(/\/$/, "") ||
  "http://127.0.0.1:8001/api";

export type FeatureOrigin =
  | "original"
  | "interaction"
  | "polynomial"
  | "numeric_bin"
  | "categorical_rule"
  | "arithmetic"
  | "date-derived"
  | "encoding-output"
  | "other";

export type FeatureManifestRow = {
  project_id: string;
  dataset_id: string;
  dataset_version_id: string;
  feature_id: string;
  feature_name: string;
  display_name: string;
  origin: FeatureOrigin;
  source_features: string[];
  transformation_type: string;
  formula_or_rule: string;
  output_datatype: string;
  creation_status: "available" | "planned" | "created" | "failed";
  materialization_status: "source" | "not_materialized" | "materialized" | "stale" | "failed";
  pipeline_status: string;
  eligibility_status: "eligible" | "excluded";
  leakage_status: string;
  selected: boolean;
  exclusion_reason: string;
  created_at: string;
  created_by: string;
  transformation_version: string;
  dataset_version: string;
  profile_scope: string;
  summary_statistics: Record<string, unknown>;
  evidence_reference?: string | null;
  config: Record<string, any>;
  user_rationale: string;
};

export type PipelineStep = {
  step_id?: string;
  transformation_type: string;
  selected_features: string[];
  config: Record<string, unknown>;
  enabled: boolean;
  fit_scope?: "training_only";
  status?: string;
};

export type FeatureManifest = {
  ok: boolean;
  project_id: string;
  dataset_id: string;
  dataset_version_id: string;
  manifest_version: string;
  manifest_hash: string;
  /** Compatibility alias; the backend must derive it from dataset_version_id. */
  dataset_version: string;
  features: FeatureManifestRow[];
  pipeline_steps: PipelineStep[];
  created_at: string;
  updated_at: string;
  validation_status: "required" | "passed" | "failed";
  validated_at?: string | null;
  materialization_status: "not_materialized" | "current" | "stale" | "failed";
  materialization_hash: string;
  materialized_manifest_hash: string;
  materialized_at?: string | null;
  confirmation_status: "required" | "confirmed";
  confirmed_manifest_hash: string;
  confirmed_at?: string | null;
  preview_hash: string;
  execution_history: Array<{
    stage: string;
    status: string;
    manifest_hash: string;
    detail: string;
    recorded_at: string;
    [key: string]: unknown;
  }>;
  split_status: "not_created" | "current" | "stale";
  persistence_status?: "not_persisted" | "persisted";
  definition_checksum?: string;
  predictor_authorization?: {
    target?: string | null;
    authorized_predictors: string[];
    excluded_predictors: Record<string, string>;
    target_source_excluded: string[];
    selected_predictors?: string[];
  };
};

export type FeatureDraft = Pick<FeatureManifestRow,
  "feature_name" | "origin" | "source_features" | "transformation_type" | "formula_or_rule" | "output_datatype" | "selected" | "exclusion_reason" | "user_rationale"
> & {
  feature_id?: string;
  display_name?: string;
  config: Record<string, any>;
};

export type FeaturePreview = {
  ok: boolean;
  project_id: string;
  dataset_id: string;
  dataset_version_id: string;
  dataset_version: string;
  scope: "rendered_sample";
  manifest_hash: string;
  preview_hash: string;
  registered_row_count: number;
  preview_row_count: number;
  columns: string[];
  created_features: string[];
  rows: Record<string, unknown>[];
};

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    credentials: "include",
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
  const payload = await response.json().catch(() => null);
  if (!response.ok || payload?.ok === false) {
    const operation = path.split("?")[0].split("/").filter(Boolean).at(-1) ?? "request";
    const detail =
      payload?.detail ?? payload?.error ?? "The backend did not provide a safe error detail.";
    throw new Error(
      `Feature ${operation} failed with HTTP ${response.status}: ${detail}`,
    );
  }
  return payload as T;
}

function identityQuery(identity: CanonicalDatasetIdentity) {
  const query = new URLSearchParams({
    project_id: identity.project_id,
    expected_dataset_id: identity.dataset_id,
    expected_dataset_version_id: identity.dataset_version_id,
  });
  return query.toString();
}

function verifyIdentity<T extends {
  project_id?: unknown;
  dataset_id?: unknown;
  dataset_version_id?: unknown;
  dataset_version?: unknown;
}>(identity: CanonicalDatasetIdentity, payload: T, context: string): T {
  assertExactDatasetIdentity(identity, payload, context);
  return payload;
}

export async function getFeatureManifest(identity: CanonicalDatasetIdentity) {
  const payload = await request<FeatureManifest>(
    `/features/manifest?${identityQuery(identity)}`,
  );
  return verifyIdentity(identity, payload, "Feature Manifest response");
}

export async function saveFeatureManifest(
  identity: CanonicalDatasetIdentity,
  features: FeatureDraft[],
  pipelineSteps: PipelineStep[],
) {
  const payload = await request<FeatureManifest>("/features/manifest", {
    method: "POST",
    body: JSON.stringify({
      project_id: identity.project_id,
      dataset_id: identity.dataset_id,
      dataset_version_id: identity.dataset_version_id,
      dataset_version: identity.dataset_version_id,
      features,
      pipeline_steps: pipelineSteps,
    }),
  });
  return verifyIdentity(identity, payload, "Saved Feature Manifest response");
}

export async function previewFeaturePlan(
  identity: CanonicalDatasetIdentity,
  features: FeatureDraft[],
  previewLimit = 20,
  signal?: AbortSignal,
  manifestVersion = "",
) {
  const payload = await request<FeaturePreview>("/features/preview", {
    method: "POST",
    signal,
    body: JSON.stringify({
      project_id: identity.project_id,
      dataset_id: identity.dataset_id,
      dataset_version_id: identity.dataset_version_id,
      dataset_version: identity.dataset_version_id,
      features,
      preview_limit: previewLimit,
      manifest_version: manifestVersion,
    }),
  });
  return verifyIdentity(identity, payload, "Feature preview response");
}

export async function materializeFeatureManifest(
  identity: CanonicalDatasetIdentity,
  manifestVersion: string,
  previewHash = "",
) {
  const payload = await request<{
    ok: boolean;
    project_id: string;
    dataset_id: string;
    dataset_version_id: string;
    manifest_version: string;
    manifest_hash: string;
    materialization_hash: string;
    materialized_manifest_hash: string;
    materialization_status: "current";
    dataset_version: string;
    row_count: number;
    original_feature_count: number;
    engineered_feature_count: number;
    materialized_features: string[];
    selected_features: string[];
    duration_ms: number;
  }>("/features/materialize", {
    method: "POST",
    body: JSON.stringify({
      project_id: identity.project_id,
      dataset_id: identity.dataset_id,
      dataset_version_id: identity.dataset_version_id,
      dataset_version: identity.dataset_version_id,
      manifest_version: manifestVersion,
      preview_hash: previewHash,
    }),
  });
  return verifyIdentity(identity, payload, "Feature materialization response");
}

export async function confirmFeatureManifest(
  identity: CanonicalDatasetIdentity,
  manifestVersion: string,
  materializationHash: string,
) {
  const payload = await request<FeatureManifest>("/features/confirm", {
    method: "POST",
    body: JSON.stringify({
      project_id: identity.project_id,
      dataset_id: identity.dataset_id,
      dataset_version_id: identity.dataset_version_id,
      dataset_version: identity.dataset_version_id,
      manifest_version: manifestVersion,
      materialization_hash: materializationHash,
    }),
  });
  return verifyIdentity(identity, payload, "Feature confirmation response");
}

export async function removeFeature(
  identity: CanonicalDatasetIdentity,
  featureId: string,
) {
  const payload = await request<FeatureManifest>(
    `/features/${encodeURIComponent(featureId)}?${identityQuery(identity)}`,
    { method: "DELETE" },
  );
  return verifyIdentity(identity, payload, "Feature removal response");
}
