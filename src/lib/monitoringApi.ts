import { DATASET_API_BASE } from "./datasetLibrary";

async function monitoringFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${DATASET_API_BASE}${path}`, {
    credentials: "include",
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
  });
  const payload = await response.json().catch(() => null);
  if (!response.ok || payload?.ok === false) {
    throw new Error(payload?.detail ?? payload?.error ?? `ATLAS monitoring request failed with HTTP ${response.status}.`);
  }
  return payload as T;
}

export const monitoringPlanStatusLabels: Record<string, string> = { draft: "Draft", active: "Active", paused: "Paused", retired: "Retired" };
export const monitoringRunStatusLabels: Record<string, string> = { draft: "Draft", running: "Running", completed: "Completed", failed: "Failed", cancelled: "Cancelled" };
export const monitoringObservationStatusLabels: Record<string, string> = { pass: "Pass", warning: "Warning", breach: "Breach", not_available: "Not Available" };
export const monitoringAlertStatusLabels: Record<string, string> = { open: "Open", acknowledged: "Acknowledged", in_remediation: "In Remediation", resolved: "Resolved", accepted_risk: "Accepted Risk", closed: "Closed" };
export const monitoringSeverityLabels: Record<string, string> = { low: "Low", medium: "Medium", high: "High", critical: "Critical" };

export function monitoringStatusTone(value?: string) {
  const key = String(value || "").toLowerCase();
  if (["active", "completed", "pass", "resolved", "closed"].includes(key)) return "success";
  if (["warning", "acknowledged", "in_remediation", "medium", "paused"].includes(key)) return "warning";
  if (["breach", "failed", "high", "critical", "open"].includes(key)) return "danger";
  return "info";
}

export type MonitoringPlan = {
  monitoring_plan_id: string;
  project_id: string;
  project_name?: string;
  asset_type?: string;
  workflow_type?: string;
  template_id?: string;
  plan_name: string;
  plan_status: string;
  monitoring_owner_user_id?: string;
  monitoring_owner_name?: string;
  business_owner_name?: string;
  monitoring_cadence?: string;
  first_monitoring_date?: string;
  next_monitoring_date?: string;
  production_start_date?: string;
  monitoring_scope?: string;
  data_source_ref?: string;
  notes?: string;
  created_at?: string;
  updated_at?: string;
  last_run_at?: string;
  latest_run_status?: string;
  overall_status?: string;
  open_alert_count?: number;
  high_critical_alert_count?: number;
};

export type MonitoringMetric = {
  monitoring_metric_id: string;
  monitoring_plan_id: string;
  project_id: string;
  metric_name: string;
  metric_category: string;
  metric_definition?: string;
  metric_direction?: string;
  warning_threshold?: number | null;
  breach_threshold?: number | null;
  lower_warning_threshold?: number | null;
  lower_breach_threshold?: number | null;
  unit?: string;
  cadence?: string;
  owner_user_id?: string;
  status?: string;
};

export type MonitoringRun = {
  monitoring_run_id: string;
  monitoring_plan_id: string;
  project_id: string;
  run_name?: string;
  run_status: string;
  run_period_start?: string;
  run_period_end?: string;
  executed_at?: string;
  completed_at?: string;
  summary?: string;
  overall_status?: string;
  breach_count?: number;
  warning_count?: number;
  evidence_ref?: string;
};

export type MonitoringObservation = {
  observation_id: string;
  monitoring_run_id: string;
  monitoring_metric_id: string;
  project_id: string;
  metric_name: string;
  observed_value?: number;
  baseline_value?: number;
  comparison_value?: number;
  status: string;
  threshold_used?: string;
  interpretation?: string;
  period_start?: string;
  period_end?: string;
  created_at?: string;
};

export type MonitoringAlert = {
  alert_id: string;
  monitoring_run_id?: string;
  monitoring_plan_id?: string;
  project_id: string;
  alert_type: string;
  severity: string;
  status: string;
  title: string;
  description?: string;
  metric_name?: string;
  observed_value?: number;
  threshold_value?: number;
  owner_user_id?: string;
  owner_name?: string;
  due_date?: string;
  created_at?: string;
  updated_at?: string;
};

export type MonitoringAction = {
  action_id: string;
  alert_id?: string;
  monitoring_plan_id?: string;
  project_id: string;
  action_type: string;
  title: string;
  description?: string;
  owner_user_id?: string;
  status: string;
  due_date?: string;
  completed_at?: string;
};

export type MonitoringEvent = {
  event_id: string;
  monitoring_plan_id?: string;
  monitoring_run_id?: string;
  project_id?: string;
  event_type: string;
  title: string;
  summary?: string;
  created_at: string;
};

export type MonitoringSummary = {
  active_plans: number;
  total_plans: number;
  runs_this_period: number;
  open_alerts: number;
  high_critical_alerts: number;
  breaches: number;
  warnings: number;
  next_reviews_due: number;
  actions_open: number;
  plans_by_status: Record<string, number>;
  alerts_by_severity: Record<string, number>;
  breaches_by_workflow_type: Record<string, number>;
  recent_events: MonitoringEvent[];
  latest_alerts: MonitoringAlert[];
};

export type MonitoringPlanDetail = {
  plan: MonitoringPlan;
  metrics: MonitoringMetric[];
  runs: MonitoringRun[];
  observations: MonitoringObservation[];
  alerts: MonitoringAlert[];
  actions: MonitoringAction[];
  events: MonitoringEvent[];
  baselines: Array<Record<string, unknown>>;
};

export type MonitoringTemplate = {
  template_id: string;
  label: string;
  metrics: Array<Partial<MonitoringMetric>>;
};

export async function getMonitoringSummary() {
  return (await monitoringFetch<{ summary: MonitoringSummary }>("/api/monitoring/summary")).summary;
}

export async function listMonitoringPlans(params: Record<string, string | number | undefined> = {}) {
  const query = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== "") query.set(key, String(value));
  });
  return monitoringFetch<{ items: MonitoringPlan[]; total: number }>(`/api/monitoring/plans${query.toString() ? `?${query}` : ""}`);
}

export async function getMonitoringPlan(planId: string) {
  return monitoringFetch<MonitoringPlanDetail>(`/api/monitoring/plans/${encodeURIComponent(planId)}`);
}

export async function getProjectMonitoringPlan(projectId: string) {
  return monitoringFetch<MonitoringPlanDetail>(`/api/monitoring/projects/${encodeURIComponent(projectId)}/plan`);
}

export async function createProjectMonitoringPlan(projectId: string, payload: Record<string, unknown> = {}) {
  return monitoringFetch<MonitoringPlanDetail>(`/api/monitoring/projects/${encodeURIComponent(projectId)}/create-plan`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function updateMonitoringPlan(planId: string, payload: Record<string, unknown>) {
  return monitoringFetch<MonitoringPlanDetail>(`/api/monitoring/plans/${encodeURIComponent(planId)}`, {
    method: "PUT",
    body: JSON.stringify(payload),
  });
}

export async function activateMonitoringPlan(planId: string) {
  return monitoringFetch<MonitoringPlanDetail>(`/api/monitoring/plans/${encodeURIComponent(planId)}/activate`, { method: "POST" });
}

export async function pauseMonitoringPlan(planId: string) {
  return monitoringFetch<MonitoringPlanDetail>(`/api/monitoring/plans/${encodeURIComponent(planId)}/pause`, { method: "POST" });
}

export async function retireMonitoringPlan(planId: string) {
  return monitoringFetch<MonitoringPlanDetail>(`/api/monitoring/plans/${encodeURIComponent(planId)}/retire`, { method: "POST" });
}

export async function seedMonitoringMetrics(planId: string) {
  return monitoringFetch<MonitoringPlanDetail>(`/api/monitoring/plans/${encodeURIComponent(planId)}/metrics/seed-from-template`, { method: "POST" });
}

export async function addMonitoringMetric(planId: string, payload: Partial<MonitoringMetric>) {
  return monitoringFetch<{ metric: MonitoringMetric }>(`/api/monitoring/plans/${encodeURIComponent(planId)}/metrics`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function createMonitoringRun(planId: string, payload: Record<string, unknown> = {}) {
  return monitoringFetch<{ run: MonitoringRun }>(`/api/monitoring/plans/${encodeURIComponent(planId)}/runs`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function startMonitoringRun(runId: string) {
  return monitoringFetch<{ run: MonitoringRun }>(`/api/monitoring/runs/${encodeURIComponent(runId)}/start`, { method: "POST" });
}

export async function completeMonitoringRun(runId: string, observations: Array<Record<string, unknown>>, summary?: string) {
  return monitoringFetch<MonitoringPlanDetail>(`/api/monitoring/runs/${encodeURIComponent(runId)}/complete`, {
    method: "POST",
    body: JSON.stringify({ observations, summary }),
  });
}

export async function listMonitoringAlerts(params: Record<string, string | number | undefined> = {}) {
  const query = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== "") query.set(key, String(value));
  });
  return monitoringFetch<{ alerts: MonitoringAlert[] }>(`/api/monitoring/alerts${query.toString() ? `?${query}` : ""}`);
}

export async function createMonitoringAlert(payload: Partial<MonitoringAlert> & { project_id: string; title: string }) {
  return monitoringFetch<{ alert: MonitoringAlert }>("/api/monitoring/alerts", { method: "POST", body: JSON.stringify(payload) });
}

export async function acknowledgeMonitoringAlert(alertId: string) {
  return monitoringFetch<{ alert: MonitoringAlert }>(`/api/monitoring/alerts/${encodeURIComponent(alertId)}/acknowledge`, { method: "POST" });
}

export async function resolveMonitoringAlert(alertId: string, resolution_notes = "") {
  return monitoringFetch<{ alert: MonitoringAlert }>(`/api/monitoring/alerts/${encodeURIComponent(alertId)}/resolve`, {
    method: "POST",
    body: JSON.stringify({ resolution_notes }),
  });
}

export async function acceptMonitoringRisk(alertId: string, resolution_notes = "") {
  return monitoringFetch<{ alert: MonitoringAlert }>(`/api/monitoring/alerts/${encodeURIComponent(alertId)}/accept-risk`, {
    method: "POST",
    body: JSON.stringify({ resolution_notes }),
  });
}

export async function createRevalidationReview(alertId: string) {
  return monitoringFetch(`/api/monitoring/alerts/${encodeURIComponent(alertId)}/create-validation-finding`, { method: "POST" });
}

export async function getMonitoringTemplates() {
  return monitoringFetch<{ templates: MonitoringTemplate[] }>("/api/monitoring/templates");
}
