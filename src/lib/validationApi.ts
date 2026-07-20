import { persistenceRequest } from "./serverPersistence";

export type ValidationCase = {
  validation_id: string;
  project_id: string;
  project_name?: string;
  asset_type: string;
  validation_template_id: string;
  status: string;
  business_status_label: string;
  risk_tier: string | null;
  assigned_validator_user_id: string | null;
  assigned_validator_name: string | null;
  submitted_by: string | null;
  submitted_at: string | null;
  review_started_at: string | null;
  review_completed_at: string | null;
  final_disposition: string | null;
  final_score: number | null;
  next_review_date: string | null;
  summary: string | null;
  created_at: string;
  updated_at: string;
  open_finding_count?: number;
  finding_count?: number;
  asset?: Record<string, any>;
};

export type ValidationChecklistItem = {
  checklist_item_id: string;
  validation_id: string;
  item_key: string;
  category: string;
  item_label: string;
  item_description: string | null;
  status: string;
  result: string | null;
  evidence_reference: string | null;
  reviewer_notes: string | null;
};

export type ValidationFinding = {
  finding_id: string;
  category: string;
  severity: string;
  status: string;
  title: string;
  description: string | null;
  remediation_owner: string | null;
  remediation_due_date: string | null;
};

export type ValidationChallenge = {
  challenge_id: string;
  challenge_type: string;
  status: string;
  title: string;
  challenge_question: string | null;
  validator_position: string | null;
  severity: string | null;
  responses: ValidationResponse[];
};

export type ValidationResponse = {
  response_id: string;
  response_text: string;
  responder_name: string | null;
  status: string;
  created_at: string;
};

export type ValidationEvent = {
  event_id: string;
  event_type: string;
  title: string;
  summary: string | null;
  user_id: string | null;
  created_at: string;
};

export type ValidationDetail = {
  case: ValidationCase;
  project: Record<string, any>;
  registry: Record<string, any> | null;
  checklist: ValidationChecklistItem[];
  findings: ValidationFinding[];
  challenges: ValidationChallenge[];
  approvals: Record<string, any>[];
  events: ValidationEvent[];
  summary: Record<string, number>;
};

export type ValidationSummary = {
  total_cases: number;
  submitted: number;
  in_review: number;
  returned: number;
  approved: number;
  rejected: number;
  open_findings: number;
  cases_by_status: Record<string, number>;
};

export async function getValidationQueue(filters: { status?: string; project_id?: string; assigned_validator_user_id?: string; limit?: number } = {}) {
  const params = new URLSearchParams();
  Object.entries(filters).forEach(([key, value]) => {
    if (value !== undefined && value !== null && String(value).trim()) params.set(key, String(value));
  });
  const query = params.toString();
  return persistenceRequest<{ ok: boolean; cases: ValidationCase[]; total: number }>(`/validation/queue${query ? `?${query}` : ""}`, { method: "GET" });
}

export async function getValidationSummary() {
  const payload = await persistenceRequest<{ ok: boolean; summary: ValidationSummary }>("/validation/summary", { method: "GET" });
  return payload.summary;
}

export async function getValidationCase(validationId: string) {
  return persistenceRequest<{ ok: boolean } & ValidationDetail>(`/validation/cases/${encodeURIComponent(validationId)}`, { method: "GET" });
}

export async function getProjectValidation(projectId: string) {
  return persistenceRequest<{ ok: boolean; project: Record<string, any>; case: ValidationCase | null; registry: Record<string, any> | null; eligible: boolean }>(
    `/validation/project/${encodeURIComponent(projectId)}`,
    { method: "GET" },
  );
}

export async function submitProjectValidation(projectId: string, payload: Record<string, unknown> = {}) {
  return persistenceRequest<{ ok: boolean } & ValidationDetail>(`/validation/project/${encodeURIComponent(projectId)}/submit`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function startValidationReview(validationId: string) {
  return persistenceRequest<{ ok: boolean } & ValidationDetail>(`/validation/cases/${encodeURIComponent(validationId)}/start-review`, { method: "POST" });
}

export async function updateValidationCase(validationId: string, payload: Record<string, unknown>) {
  return persistenceRequest<{ ok: boolean } & ValidationDetail>(`/validation/cases/${encodeURIComponent(validationId)}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export async function updateValidationChecklist(validationId: string, itemKey: string, payload: Record<string, unknown>) {
  return persistenceRequest<{ ok: boolean } & ValidationDetail>(`/validation/cases/${encodeURIComponent(validationId)}/checklist/${encodeURIComponent(itemKey)}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export async function createValidationFinding(validationId: string, payload: Record<string, unknown>) {
  return persistenceRequest<{ ok: boolean } & ValidationDetail>(`/validation/cases/${encodeURIComponent(validationId)}/findings`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function createValidationChallenge(validationId: string, payload: Record<string, unknown>) {
  return persistenceRequest<{ ok: boolean } & ValidationDetail>(`/validation/cases/${encodeURIComponent(validationId)}/challenges`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function createValidationResponse(validationId: string, challengeId: string, payload: Record<string, unknown>) {
  return persistenceRequest<{ ok: boolean } & ValidationDetail>(`/validation/cases/${encodeURIComponent(validationId)}/challenges/${encodeURIComponent(challengeId)}/responses`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function createValidationApproval(validationId: string, payload: Record<string, unknown>) {
  return persistenceRequest<{ ok: boolean } & ValidationDetail>(`/validation/cases/${encodeURIComponent(validationId)}/approvals`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}
