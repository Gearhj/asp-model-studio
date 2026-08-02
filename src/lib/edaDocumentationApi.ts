import { DATASET_API_BASE } from "./datasetLibrary";
import {
  assertExactDatasetIdentity,
  type CanonicalDatasetIdentity,
} from "./datasetIdentity";

export const EDA_DOCUMENTATION_UPDATED_EVENT = "atlas-eda-documentation-updated";
export const EDA_DOCUMENTATION_BROADCAST_CHANNEL =
  "atlas-eda-documentation-events";
const EDA_DOCUMENTATION_BROWSER_INSTANCE =
  typeof crypto !== "undefined" && typeof crypto.randomUUID === "function"
    ? crypto.randomUUID()
    : `eda-documentation-${Date.now()}-${Math.random().toString(36).slice(2)}`;

export type EdaDocumentationStatus =
  | "draft"
  | "ready_for_confirmation"
  | "confirmed"
  | "stale";

export const EDA_DOCUMENTATION_SECTION_KEYS = [
  "overview",
  "target",
  "predictors",
  "relationships",
  "stability_and_segments",
  "findings",
] as const;

export type EdaDocumentationSectionKey =
  (typeof EDA_DOCUMENTATION_SECTION_KEYS)[number];

export type EdaDocumentationSections = Record<
  EdaDocumentationSectionKey,
  Record<string, unknown>
>;

export type EdaDocumentationEvidenceReference = {
  evidence_id: string;
  title?: string;
  uri?: string;
  checksum?: string;
  evidence_type?: string;
};

export type EdaDocumentationDecision = {
  decision_id: string;
  category: string;
  decision: string;
  rationale: string;
  status: string;
  finding_id?: string;
  parent_id?: string;
  child_ids?: string[];
  finding_family?: string;
  downstream_destination?: string;
  suggested_transformation?: string;
  carry_forward_mode?: "draft_recommendation" | "none";
  mutation_applied?: false;
  evidence_references?: string[];
};

export type EdaDocumentationReviewerRecord = {
  overall_conclusion: string;
  reviewer_commentary: string;
  overall_review_status:
    | "draft"
    | "under_review"
    | "accepted"
    | "accepted_with_conditions"
    | "rejected"
    | "reviewed";
  required_conditions: string[];
  open_nonblocking_items: string[];
  evidence_references: string[];
  mdd_reference?: string | null;
  generated_draft_used?: boolean;
  generated_draft_non_approving?: true | null;
};

export type EdaBulkDispositionAction = {
  action_id: string;
  family: string;
  parent_ids: string[];
  child_ids: string[];
  prior_statuses: Record<string, string>;
  new_status: string;
  rationale: string;
  destination: string | null;
  mutation_applied: false;
};

export type EdaMddStaleness = {
  stale_sections: Array<{
    section: EdaDocumentationSectionKey;
    classification: "analytical" | "narrative_only";
    changed_source_fields: string[];
  }>;
  changed_source_fields: string[];
  analytical_staleness: boolean;
  narrative_only_staleness: boolean;
  review_action: "Review stale documentation";
};

export type EdaCompletionStage = {
  stage:
    | "validate"
    | "persist_reviewer_record"
    | "persist_dispositions"
    | "persist_carry_forward_recommendations"
    | "record_evidence"
    | "update_mdd"
    | "mark_eda_complete";
  status: "completed";
  artifact_count?: number;
};

export type EdaDocumentationPayload = {
  project_id: string;
  dataset_id: string;
  dataset_version_id: string;
  /** Compatibility projection; it must mirror dataset_version_id. */
  dataset_version: string;
  target: string;
  predictor_manifest_id: string;
  eda_analysis_version: string;
  sections: EdaDocumentationSections;
  evidence_references: EdaDocumentationEvidenceReference[];
  decisions: EdaDocumentationDecision[];
  governance_contract_version?: "eda-governance-v2";
  reviewer_record?: EdaDocumentationReviewerRecord;
  bulk_disposition_actions?: EdaBulkDispositionAction[];
  performance_metadata: Record<string, unknown>;
  duplicate_decision?: string | null;
  target_source_exclusions: string[];
  unresolved_blocking_findings: string[];
  reviewer_status: string;
};

export type EdaDocumentationRecord = EdaDocumentationPayload & {
  status?: EdaDocumentationStatus;
  confirmation_id?: string;
  documentation_version?: string;
  confirmed_at?: string;
  confirmed_by?: string;
  confirmed_by_display_name?: string;
  stale_at?: string;
  stale_reason?: string;
  mdd_staleness?: EdaMddStaleness;
  completion_id?: string;
  completion_sequence?: EdaCompletionStage[];
  created_at?: string;
  updated_at?: string;
};

export type EdaDocumentationConfirmationSummary = {
  confirmation_id: string;
  documentation_version: string;
  eda_analysis_version?: string;
  dataset_id?: string;
  dataset_version_id?: string;
  dataset_version?: string;
  target?: string;
  predictor_manifest_id?: string;
  confirmed_at: string;
  confirmed_by: string;
  confirmed_by_display_name?: string;
  status?: EdaDocumentationStatus;
  evidence_ids?: string[];
  stale_at?: string;
  stale_reason?: string;
};

export type EdaDocumentationLineage = {
  project_id: string;
  dataset_id?: string;
  dataset_version_id?: string;
  dataset_version?: string;
  target?: string;
  predictor_manifest_id?: string;
};

export type EdaDocumentationState = {
  ok: boolean;
  project_id: string;
  dataset_id?: string;
  dataset_version_id?: string;
  dataset_version?: string;
  status: EdaDocumentationStatus;
  draft: EdaDocumentationRecord | null;
  current_approved: EdaDocumentationRecord | null;
  history: EdaDocumentationConfirmationSummary[];
  source_lineage: EdaDocumentationLineage;
};

export type EdaDocumentationConfirmationResult = {
  ok?: boolean;
  confirmation_id: string;
  documentation_version: string;
  evidence_ids: string[];
  next_step_eligible: boolean;
  status: EdaDocumentationStatus;
  record: EdaDocumentationRecord;
  idempotent?: boolean;
  completion_id?: string;
  completion_sequence?: EdaCompletionStage[];
};

export type EdaDocumentationUpdateDetail = {
  project_id: string;
  status?: EdaDocumentationStatus;
  confirmation_id?: string;
  documentation_version?: string;
  reason?: string;
};

type EdaDocumentationErrorPayload = {
  detail?: string | { message?: string; detail?: string };
  error?: string;
  message?: string;
};

async function edaDocumentationFetch<T>(
  path: string,
  init?: RequestInit
): Promise<T> {
  const response = await fetch(`${DATASET_API_BASE}${path}`, {
    credentials: "include",
    ...init,
    headers: {
      ...(init?.body ? { "Content-Type": "application/json" } : {}),
      ...(init?.headers ?? {}),
    },
  });
  const payload = (await response.json().catch(() => null)) as
    | EdaDocumentationErrorPayload
    | T
    | null;
  if (!response.ok) {
    if (response.status === 401) {
      throw new Error(
        "Your session is not authenticated. Sign in again to view governed EDA documentation."
      );
    }
    const errorPayload = isRecord(payload)
      ? (payload as EdaDocumentationErrorPayload)
      : null;
    const detail = errorPayload?.detail;
    const message =
      typeof detail === "string"
        ? detail
        : detail?.message ??
          detail?.detail ??
          errorPayload?.error ??
          errorPayload?.message;
    throw new Error(
      message ||
        `ATLAS EDA documentation request failed with HTTP ${response.status}.`
    );
  }
  if (!payload) {
    throw new Error("ATLAS returned an empty EDA documentation response.");
  }
  return payload as T;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function assertEdaDocumentationStateIdentity(
  identity: CanonicalDatasetIdentity,
  state: EdaDocumentationState,
) {
  assertExactDatasetIdentity(
    identity,
    state,
    "EDA documentation state",
  );
  assertExactDatasetIdentity(
    identity,
    state.source_lineage,
    "EDA documentation source lineage",
  );
  for (const [label, record] of [
    ["draft", state.draft],
    ["approved snapshot", state.current_approved],
  ] as const) {
    if (record) {
      assertExactDatasetIdentity(
        identity,
        record,
        `EDA documentation ${label}`,
      );
    }
  }
  return state;
}

export async function getEdaDocumentationState(
  projectId: string,
  identity: CanonicalDatasetIdentity,
  signal?: AbortSignal,
) {
  const query = new URLSearchParams({
    expected_dataset_id: identity.dataset_id,
    expected_dataset_version_id: identity.dataset_version_id,
  });
  const state = await edaDocumentationFetch<EdaDocumentationState>(
    `/eda/documentation/${encodeURIComponent(projectId)}${
      query.size ? `?${query.toString()}` : ""
    }`,
    { signal },
  );
  return assertEdaDocumentationStateIdentity(identity, state);
}

export async function saveEdaDocumentationDraft(
  payload: EdaDocumentationPayload
) {
  const state = await edaDocumentationFetch<EdaDocumentationState>(
    "/eda/documentation/draft",
    {
      method: "POST",
      body: JSON.stringify(payload),
    }
  );
  const verified = assertEdaDocumentationStateIdentity(
    {
      project_id: payload.project_id,
      dataset_id: payload.dataset_id,
      dataset_version_id: payload.dataset_version_id,
    },
    state,
  );
  publishEdaDocumentationUpdate({
    project_id: payload.project_id,
    status: verified.status,
  });
  return verified;
}

export const EDA_LEGACY_CONFIRMATION_ROUTE = "/eda/confirmation";

export async function completeEdaDocumentation(
  payload: EdaDocumentationPayload
) {
  const result =
    await edaDocumentationFetch<EdaDocumentationConfirmationResult>(
      "/eda/completion",
      {
        method: "POST",
        body: JSON.stringify({
          payload,
          expected_analysis_version: payload.eda_analysis_version,
          idempotency_key: [
            "eda-completion",
            payload.project_id,
            payload.dataset_id,
            payload.dataset_version_id,
            payload.eda_analysis_version,
          ].join(":"),
        }),
      }
    );
  assertExactDatasetIdentity(
    {
      project_id: payload.project_id,
      dataset_id: payload.dataset_id,
      dataset_version_id: payload.dataset_version_id,
    },
    result.record,
    "EDA confirmation response",
  );
  publishEdaDocumentationUpdate({
    project_id: payload.project_id,
    status: result.status,
    confirmation_id: result.confirmation_id,
    documentation_version: result.documentation_version,
  });
  return result;
}

// Compatibility export for EDA callers while the governed operation now uses
// the typed /completion transaction rather than the legacy confirmation body.
export const confirmEdaDocumentation = completeEdaDocumentation;

export async function invalidateEdaDocumentation(
  identity: CanonicalDatasetIdentity,
  reason: string,
  upstreamRevision?: string
) {
  const projectId = identity.project_id;
  const state = await edaDocumentationFetch<EdaDocumentationState>(
    `/eda/documentation/${encodeURIComponent(projectId)}/invalidate`,
    {
      method: "POST",
      body: JSON.stringify({
        reason,
        expected_dataset_id: identity.dataset_id,
        expected_dataset_version_id: identity.dataset_version_id,
        ...(upstreamRevision ? { upstream_revision: upstreamRevision } : {}),
      }),
    }
  );
  const verified = assertEdaDocumentationStateIdentity(identity, state);
  publishEdaDocumentationUpdate({
    project_id: projectId,
    status: verified.status,
    reason,
  });
  return verified;
}

export function publishEdaDocumentationUpdate(
  detail: EdaDocumentationUpdateDetail
) {
  if (typeof window === "undefined") return;
  window.dispatchEvent(
    new CustomEvent<EdaDocumentationUpdateDetail>(
      EDA_DOCUMENTATION_UPDATED_EVENT,
      { detail }
    )
  );
  if (typeof BroadcastChannel !== "undefined") {
    try {
      const channel = new BroadcastChannel(
        EDA_DOCUMENTATION_BROADCAST_CHANNEL
      );
      channel.postMessage({
        source_id: EDA_DOCUMENTATION_BROWSER_INSTANCE,
        detail,
      });
      channel.close();
    } catch {
      // The same-window CustomEvent and visibility-aware polling remain active.
    }
  }
}

export function subscribeEdaDocumentationUpdates(
  listener: (detail: EdaDocumentationUpdateDetail) => void
) {
  if (typeof window === "undefined") return () => undefined;

  const handleWindowEvent = (event: Event) => {
    const detail = (event as CustomEvent<unknown>).detail;
    if (isEdaDocumentationUpdateDetail(detail)) listener(detail);
  };
  window.addEventListener(
    EDA_DOCUMENTATION_UPDATED_EVENT,
    handleWindowEvent
  );

  let channel: BroadcastChannel | null = null;
  const handleBroadcast = (event: MessageEvent<unknown>) => {
    if (!isRecord(event.data)) return;
    if (event.data.source_id === EDA_DOCUMENTATION_BROWSER_INSTANCE) return;
    if (isEdaDocumentationUpdateDetail(event.data.detail)) {
      listener(event.data.detail);
    }
  };
  if (typeof BroadcastChannel !== "undefined") {
    try {
      channel = new BroadcastChannel(EDA_DOCUMENTATION_BROADCAST_CHANNEL);
      channel.addEventListener("message", handleBroadcast);
    } catch {
      channel = null;
    }
  }

  return () => {
    window.removeEventListener(
      EDA_DOCUMENTATION_UPDATED_EVENT,
      handleWindowEvent
    );
    if (channel) {
      channel.removeEventListener("message", handleBroadcast);
      channel.close();
    }
  };
}

function isEdaDocumentationUpdateDetail(
  value: unknown
): value is EdaDocumentationUpdateDetail {
  return (
    isRecord(value) &&
    typeof value.project_id === "string" &&
    Boolean(value.project_id.trim())
  );
}
