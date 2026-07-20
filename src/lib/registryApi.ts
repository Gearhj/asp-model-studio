import { persistenceRequest } from "./serverPersistence";

export type RegistryAssetType =
  | "predictive_model"
  | "credit_risk_model"
  | "optimization_study"
  | "experiment"
  | "ab_test"
  | "decision_strategy"
  | "custom_workflow";

export type RegistryLifecycleStatus =
  | "Draft"
  | "Development"
  | "Ready for Review"
  | "Validation"
  | "Recommended"
  | "Approved"
  | "Approved with Conditions"
  | "Implementation Planned"
  | "Implemented"
  | "Monitoring"
  | "Returned"
  | "Rejected"
  | "Retired";

export type RegistryAsset = {
  registry_id: string;
  project_id: string;
  name: string;
  asset_type: RegistryAssetType;
  workflow_type: string;
  template_id: string | null;
  owner_user_id: string | null;
  owner_display_name: string;
  lifecycle_status: RegistryLifecycleStatus;
  risk_tier: string;
  business_purpose: string;
  intended_use: string;
  current_step_id: string | null;
  workflow_completion_percent: number;
  evidence_readiness_percent: number;
  evidence_status: string;
  documentation_readiness_percent: number;
  documentation_status: string;
  validation_status: string;
  validation_score: number | null;
  recommendation_status: string;
  implementation_status: string;
  monitoring_status: string;
  monitoring_open_alert_count?: number;
  last_monitoring_run_at?: string | null;
  next_monitoring_due_at?: string | null;
  latest_run_status: string;
  latest_run_type: string | null;
  latest_run_at: string | null;
  latest_export_at: string | null;
  last_activity_at: string | null;
  created_at: string | null;
  updated_at: string | null;
  next_review_date: string | null;
  open_action_count: number;
  open_finding_count: number;
  tags: string[];
  summary_json: {
    record_counts?: Record<string, number>;
    workflow?: Record<string, unknown>;
    evidence?: RegistryEvidenceSummary;
    documentation?: RegistryDocumentationSummary;
    validation?: Record<string, unknown>;
    recommendation?: Record<string, unknown>;
    implementation?: Record<string, unknown>;
    lifecycle_derivation?: RegistryLifecycleDerivation;
  };
};

export type RegistryEvidenceSummary = {
  total_count: number;
  required_count: number;
  generated_count: number;
  captured_count: number;
  ready_count: number;
  approved_count: number;
  stale_count: number;
  rejected_count: number;
  coverage_score: number;
  package_ready: boolean;
  package_approved: boolean;
  status_label: string;
  display_status: string;
  missing_required_types: string[];
};

export type RegistryDocumentationSummary = {
  readiness_score: number;
  display_status: string;
  package_id: string | null;
  package_type: string | null;
  package_status: string | null;
  section_count: number;
  completed_section_count: number;
  updated_at: string | null;
};

export type RegistryLifecycleDerivation = {
  matched_rule: string;
  reasons: string[];
};

export type RegistryAction = {
  action_id: string;
  project_id: string;
  project_name: string;
  severity: "High" | "Medium" | "Low";
  action_type: string;
  title: string;
  description: string;
  owner: string;
  recommended_next_step: string;
  created_at: string | null;
  source: string;
};

export type RegistryActivity = {
  event_type: string;
  title: string;
  summary: string;
  status: string | null;
  occurred_at: string;
  user_id: string | null;
  user_display_name: string;
  source_id: string | null;
  project_id?: string;
  project_name?: string;
};

export type RegistryOwner = {
  user_id: string;
  display_name: string;
  role: string;
  status: string;
  active_assets: number;
  ready_for_review: number;
  open_actions: number;
  evidence_artifacts: number;
  validation_records: number;
  exports_generated: number;
  recent_activity_count: number;
  last_active_at: string | null;
};

export type RegistrySummary = {
  generated_at: string;
  total_assets: number;
  active_assets: number;
  draft_assets: number;
  ready_for_review: number;
  in_validation: number;
  recommended: number;
  approved: number;
  implementation_planned: number;
  monitoring: number;
  evidence_ready_count: number;
  evidence_incomplete_count: number;
  documentation_ready_count: number;
  documentation_incomplete_count: number;
  validation_complete_count: number;
  validation_pending_count: number;
  open_action_count: number;
  recent_activity_count: number;
  assets_by_type: Record<string, number>;
  assets_by_status: Record<string, number>;
  assets_by_owner: Record<string, number>;
  stale_assets_count: number;
};

export type RegistryRun = {
  run_id: string;
  run_type: string;
  status: string;
  started_at: string | null;
  completed_at: string | null;
  created_by: string | null;
  metrics: Record<string, unknown>;
  has_error: boolean;
};

export type RegistryExport = {
  export_id: string;
  export_type: string;
  file_name: string;
  file_path: string | null;
  storage_mode: string;
  created_by: string | null;
  created_at: string | null;
  artifact_hash: string | null;
};

export type RegistryDecision = {
  decision_id: string;
  decision_type: string;
  title: string;
  summary: string | null;
  status: string;
  owner: string | null;
  created_by: string | null;
  created_at: string | null;
  updated_at: string | null;
  detail: Record<string, unknown>;
};

export type RegistryAuditEvent = {
  audit_id: string;
  project_id: string;
  user_id: string | null;
  user_display_name: string;
  action_type: string;
  entity_type: string | null;
  entity_id: string | null;
  title: string;
  summary: string | null;
  created_at: string;
};

export type RegistryAssetDetail = {
  asset: RegistryAsset;
  evidence_summary: RegistryEvidenceSummary;
  documentation_summary: RegistryDocumentationSummary;
  latest_runs: RegistryRun[];
  exports: RegistryExport[];
  decisions: RegistryDecision[];
  audit_trail: RegistryAuditEvent[];
  lifecycle_timeline: RegistryActivity[];
  open_actions: RegistryAction[];
  lifecycle_derivation: RegistryLifecycleDerivation;
};

export type RegistryFilters = {
  asset_type?: string;
  workflow_type?: string;
  lifecycle_status?: string;
  owner_user_id?: string;
  evidence_status?: string;
  documentation_status?: string;
  validation_status?: string;
  search?: string;
  limit?: number;
  offset?: number;
};

function queryString(values: RegistryFilters) {
  const params = new URLSearchParams();
  Object.entries(values).forEach(([key, value]) => {
    if (value !== undefined && value !== null && String(value).trim() !== "") {
      params.set(key, String(value));
    }
  });
  const query = params.toString();
  return query ? `?${query}` : "";
}

export async function getRegistryAssets(filters: RegistryFilters = {}) {
  return persistenceRequest<{ ok: boolean; assets: RegistryAsset[]; total: number; limit: number; offset: number }>(
    `/registry/assets${queryString(filters)}`,
    { method: "GET" },
  );
}

export async function getRegistryAsset(projectId: string) {
  const payload = await persistenceRequest<{ ok: boolean } & RegistryAssetDetail>(
    `/registry/assets/${encodeURIComponent(projectId)}`,
    { method: "GET" },
  );
  return payload;
}

export async function getRegistrySummary() {
  const payload = await persistenceRequest<{ ok: boolean; summary: RegistrySummary }>("/registry/summary", { method: "GET" });
  return payload.summary;
}

export async function getRegistryActions(filters: { severity?: string; project_id?: string; limit?: number } = {}) {
  const payload = await persistenceRequest<{ ok: boolean; actions: RegistryAction[]; total: number }>(
    `/registry/actions${queryString(filters as RegistryFilters)}`,
    { method: "GET" },
  );
  return payload;
}

export async function getRegistryActivity(filters: { project_id?: string; limit?: number } = {}) {
  const payload = await persistenceRequest<{ ok: boolean; activity: RegistryActivity[]; total: number }>(
    `/registry/activity${queryString(filters as RegistryFilters)}`,
    { method: "GET" },
  );
  return payload;
}

export async function getRegistryOwners() {
  return persistenceRequest<{ ok: boolean; owners: RegistryOwner[]; total: number }>("/registry/owners", { method: "GET" });
}
