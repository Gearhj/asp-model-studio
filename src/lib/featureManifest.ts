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
  manifest_version: string;
  manifest_hash: string;
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
    throw new Error(payload?.detail ?? payload?.error ?? `ATLAS feature request failed with HTTP ${response.status}.`);
  }
  return payload as T;
}

export function getFeatureManifest(projectId: string) {
  return request<FeatureManifest>(`/features/manifest?project_id=${encodeURIComponent(projectId)}`);
}

export function saveFeatureManifest(projectId: string, features: FeatureDraft[], pipelineSteps: PipelineStep[], datasetVersion = "") {
  return request<FeatureManifest>("/features/manifest", {
    method: "POST",
    body: JSON.stringify({ project_id: projectId, features, pipeline_steps: pipelineSteps, dataset_version: datasetVersion }),
  });
}

export function previewFeaturePlan(
  projectId: string,
  features: FeatureDraft[],
  previewLimit = 20,
  signal?: AbortSignal,
  manifestVersion = "",
) {
  return request<FeaturePreview>("/features/preview", {
    method: "POST",
    signal,
    body: JSON.stringify({
      project_id: projectId,
      features,
      preview_limit: previewLimit,
      manifest_version: manifestVersion,
    }),
  });
}

export function materializeFeatureManifest(projectId: string, manifestVersion: string, previewHash = "") {
  return request<{
    ok: boolean;
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
      project_id: projectId,
      manifest_version: manifestVersion,
      preview_hash: previewHash,
    }),
  });
}

export function confirmFeatureManifest(
  projectId: string,
  manifestVersion: string,
  materializationHash: string,
) {
  return request<FeatureManifest>("/features/confirm", {
    method: "POST",
    body: JSON.stringify({
      project_id: projectId,
      manifest_version: manifestVersion,
      materialization_hash: materializationHash,
    }),
  });
}

export function removeFeature(projectId: string, featureId: string) {
  return request<FeatureManifest>(`/features/${encodeURIComponent(featureId)}?project_id=${encodeURIComponent(projectId)}`, { method: "DELETE" });
}
