import { getJSON, postJSON } from "./api";

export type AuditResult = {
  criteria_results?: boolean[];
  failed_criteria?: string[];
  friction_detected?: boolean;
  friction_cause?: string[];
  compliance?: number;
  note?: string;
  change_next_turn?: string;
  error?: string | null;
  [key: string]: unknown;
};

export type StelaRow = {
  id: string;
  dataset_id: string;
  dataset: string;
  conversation_id: string;
  turn_id: number;
  intent?: string;
  category?: string;
  user_message: string;
  original_assistant_response: string;
  original_response?: string;
  stela_assistant_response: string;
  stela_response?: string;
  original_audit: AuditResult;
  stela_audit: AuditResult;
  comparison: Record<string, unknown>;
  metadata?: Record<string, unknown>;
  stela_state_vector_seed?: Record<string, unknown>;
  stela_context_packet?: Record<string, unknown>;
  original_compliance?: number;
  stela_compliance?: number;
  compliance_delta?: number;
  original_friction?: boolean;
  stela_friction?: boolean;
  friction_delta?: number;
  failed_criteria_original?: string[];
  failed_criteria_stela?: string[];
  token_delta?: number;
  outcome?: "improved" | "unchanged" | "worsened" | "unknown";
};

export type DatasetSummary = {
  id: string;
  label: string;
  rows: number;
  original_average_compliance: number;
  stela_average_compliance: number;
  average_compliance_lift: number;
  average_friction_change: number;
  improved: number;
  unchanged: number;
  worsened: number;
  average_token_change: number;
  errors: {
    generation: number;
    original_audit: number;
    stela_audit: number;
  };
};

export type StelaDashboardData = {
  source_note: string;
  run: {
    name: string;
    primary_result: boolean;
    status: string;
    strong_status: string;
    status_reason: string;
  };
  combined: {
    status: string;
    rows: number;
    original_average_compliance: number;
    stela_average_compliance: number;
    average_compliance_lift: number;
    average_friction_change: number;
    improved: number;
    unchanged: number;
    worsened: number;
    worsened_rate: number;
    generation_errors: number;
    original_audit_errors: number;
    stela_audit_errors: number;
    average_token_change: number;
    datasets: DatasetSummary[];
  };
  rows: StelaRow[];
  worsened_rows: StelaRow[];
  history: Array<{
    version: string;
    title: string;
    role: string;
    summary: string;
  }>;
};

export type StelaAnalytics = {
  outcome_distribution: Array<{
    outcome: "improved" | "unchanged" | "worsened";
    count: number;
    percentage: number;
  }>;
  compliance_lift_distribution: Array<{
    label: string;
    count: number;
    percentage: number;
  }>;
  friction_movement: {
    reduced: number;
    unchanged: number;
    increased: number;
  };
  intent_category_performance: Array<{
    label: string;
    row_count: number;
    average_original_compliance?: number;
    average_stela_compliance?: number;
    average_lift?: number;
    worsened_count: number;
    worsened_rate: number;
    average_token_change?: number;
  }>;
  token_efficiency: {
    average_token_change?: number;
    stela_shorter_count: number;
    stela_longer_count: number;
    stela_same_count: number;
    by_dataset: Array<{
      dataset_id: string;
      dataset: string;
      average_token_change?: number;
    }>;
    by_outcome: Array<{
      outcome: string;
      average_token_change?: number;
    }>;
  };
  failure_criteria: Array<{
    failed_criterion: string;
    original_count: number;
    stela_count: number;
    worsened_row_count: number;
    example_conversation_id?: string;
  }>;
};

export type SimulationRequest = {
  row_id?: string | null;
  user_message?: string;
  original_response?: string;
  dataset?: string;
  domain?: string;
  intent?: string;
  category?: string;
  notes?: string;
  state_vector: {
    compliance_risk: number;
    customer_distress: number;
    fraud_risk: number;
    account_sensitivity: number;
  };
  toggles: {
    authenticated_session: boolean;
    account_info_available: boolean;
    transfer_action: boolean;
    customer_distressed: boolean;
    high_regulatory_sensitivity: boolean;
    minimize_friction: boolean;
    require_human_escalation: boolean;
  };
  behavioral_objective:
    | "maximize_compliance"
    | "minimize_friction"
    | "balanced"
    | "shortest_acceptable_response"
    | "escalation_first"
    | "customer_retention_sensitive";
};

export type SimulationResponse = {
  risk_posture: "low" | "medium" | "high";
  planning_frame: string;
  behavioral_imperatives: string[];
  response_style: string;
  expected_friction: "low" | "medium" | "high";
  expected_compliance_risk: "low" | "medium" | "high";
  response_sketch: string;
  delta_summary: {
    compliance_risk: string;
    friction: string;
    escalation_likelihood: string;
    customer_experience: string;
    reason: string;
  };
  note: string;
  selected_row?: StelaRow;
};

export function loadStelaV04() {
  return getJSON<StelaDashboardData>("/stela/v04");
}

export function loadStelaV04Summary() {
  return getJSON<Pick<StelaDashboardData, "source_note" | "run" | "combined" | "history">>("/stela/v04/summary");
}

export function loadStelaRows() {
  return getJSON<StelaRow[]>("/stela/v04/rows");
}

export function loadStelaRow(rowId: string) {
  return getJSON<StelaRow>(`/stela/v04/rows/${encodeURIComponent(rowId)}`);
}

export function loadStelaAnalytics() {
  return getJSON<StelaAnalytics>("/stela/v04/analytics");
}

export function loadStelaWorsenedRows() {
  return getJSON<StelaRow[]>("/stela/v04/worsened");
}

export function simulateStela(request: SimulationRequest) {
  return postJSON<SimulationResponse>("/stela/v04/simulate", request);
}
