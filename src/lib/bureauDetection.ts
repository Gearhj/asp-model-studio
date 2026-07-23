import {
  BUREAU_METADATA_KEY,
  BUREAU_TREATMENT_KEY,
  loadBureauMetadata,
  loadBureauTreatmentDecisions,
  type BureauMetadataRow,
} from "./creditBureau";

const API_BASE =
  (import.meta.env.VITE_API_BASE as string | undefined)?.replace(/\/$/, "") ||
  "http://127.0.0.1:8001/api";

export const BUREAU_REVIEW_KEY = "atlas-predictive-bureau-review-v2";

export type BureauDeclaration = "auto" | "contains" | "does_not_contain" | "manual_review";
export type BureauHandling =
  | "preserve_informative"
  | "convert_to_missing"
  | "convert_to_category"
  | "documented_domain_mapping"
  | "exclude_variable"
  | "leave_unchanged"
  | "custom";

export type BureauReviewDecision = {
  variable: string;
  value: number;
  handling: BureauHandling;
  rationale: string;
  updatedAt: string;
};

export type BureauDetectionVariable = {
  variable: string;
  confidence: number;
  reasons: string[];
  datatype: string;
  special_value_count: number;
  special_value_frequency: number;
  likely_bureau: boolean;
  special_values: Array<{
    value: number;
    definition: string;
    count: number;
    frequency: number;
    event_rate: number | null;
    regular_event_rate: number | null;
    event_rate_delta: number | null;
    recommended_handling: string;
  }>;
};

export type BureauDetectionResponse = {
  ok: boolean;
  scope: "full_dataset";
  row_count: number;
  target: string | null;
  event_value: unknown;
  detected: boolean;
  confidence: number;
  manual_declaration: BureauDeclaration;
  reasons: string[];
  likely_variable_count: number;
  variables_with_special_values: number;
  variables: BureauDetectionVariable[];
  metadata_source: string;
  reviewed_at: string;
};

export type BureauReviewState = {
  declaration: BureauDeclaration;
  rationale: string;
  decisions: BureauReviewDecision[];
};

function mapLegacyHandling(treatment: string): BureauHandling {
  if (treatment === "convert_to_missing") return "convert_to_missing";
  if (treatment === "exclude_variable") return "exclude_variable";
  if (treatment === "group_special_values") return "convert_to_category";
  if (treatment === "impute_bureau_equivalent") return "documented_domain_mapping";
  if (treatment === "keep_as_is") return "leave_unchanged";
  return "preserve_informative";
}

export function loadBureauReviewState(): BureauReviewState {
  try {
    const parsed = JSON.parse(localStorage.getItem(BUREAU_REVIEW_KEY) || "null");
    if (parsed && Array.isArray(parsed.decisions)) return parsed;
  } catch {
    // Fall through to compatibility migration.
  }
  const legacy = loadBureauTreatmentDecisions();
  return {
    declaration: "auto",
    rationale: "",
    decisions: legacy.map((row) => ({
      variable: row.variableName,
      value: row.value,
      handling: mapLegacyHandling(row.treatment),
      rationale: row.rationale,
      updatedAt: row.updatedAt,
    })),
  };
}

export function saveBureauReviewState(state: BureauReviewState) {
  localStorage.setItem(BUREAU_REVIEW_KEY, JSON.stringify(state));
  window.dispatchEvent(new CustomEvent("bureau-review-updated"));
}

export function bureauMetadata(): BureauMetadataRow[] {
  return loadBureauMetadata();
}

export async function fetchBureauDetection(input: {
  projectId: string;
  target?: string;
  eventValue?: unknown;
  state: BureauReviewState;
  metadata?: BureauMetadataRow[];
  signal?: AbortSignal;
}) {
  const response = await fetch(`${API_BASE}/data/bureau-detection`, {
    method: "POST",
    credentials: "include",
    signal: input.signal,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      project_id: input.projectId,
      target: input.target || undefined,
      event_value: input.eventValue,
      manual_declaration: input.state.declaration,
      metadata: input.metadata ?? bureauMetadata(),
      treatment_selections: input.state.decisions,
      reviewer_rationale: input.state.rationale,
    }),
  });
  const payload = await response.json().catch(() => null);
  if (!response.ok || !payload?.ok) {
    throw new Error(payload?.detail ?? payload?.error ?? "Credit bureau detection is unavailable.");
  }
  return payload as BureauDetectionResponse;
}

export const bureauCompatibilityKeys = [BUREAU_METADATA_KEY, BUREAU_TREATMENT_KEY, BUREAU_REVIEW_KEY];

