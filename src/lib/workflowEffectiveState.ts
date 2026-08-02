import type {
  ProjectType,
  WorkflowStep,
  WorkflowStepStatus,
} from "../config/workflows";
import type { CanonicalDatasetIdentity } from "./datasetIdentity";

export type EffectiveWorkflowStep = WorkflowStep & {
  lineageStatus?: string;
  effectiveReason?: string;
};

export type EffectiveWorkflowView = {
  authoritative: boolean;
  identityValidity: string;
  historicalCompletedSteps: string[];
  effectiveCompletedSteps: string[];
  effectiveWorkflowSteps: EffectiveWorkflowStep[];
  effectiveCurrentStepId: string;
};

export type EffectiveWorkflowInput = {
  workflowSteps: WorkflowStep[];
  projectType: ProjectType;
  datasetIdentity?: CanonicalDatasetIdentity | null;
  backendState?: unknown;
};

const EFFECTIVE_STATUSES = new Set<WorkflowStepStatus>([
  "pending",
  "in_progress",
  "complete",
  "skipped",
]);

const CURRENT_IDENTITY_STATES = new Set([
  "current",
  "valid",
  "ready",
  "verified",
]);

function record(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null;
}

function first(recordValue: Record<string, unknown> | null, ...keys: string[]) {
  if (!recordValue) return undefined;
  for (const key of keys) {
    if (Object.prototype.hasOwnProperty.call(recordValue, key)) return recordValue[key];
  }
  return undefined;
}

function identifiers(value: unknown) {
  return Array.isArray(value)
    ? [...new Set(value.map(String).map((item) => item.trim()).filter(Boolean))]
    : [];
}

function normalizeStatus(value: unknown): WorkflowStepStatus | null {
  const normalized = String(value ?? "").trim().toLowerCase();
  if (normalized === "completed") return "complete";
  return EFFECTIVE_STATUSES.has(normalized as WorkflowStepStatus)
    ? normalized as WorkflowStepStatus
    : null;
}

function stepEntry(value: unknown) {
  const entry = record(value);
  if (!entry) {
    const primitive = String(value ?? "").trim().toLowerCase();
    return {
      status: normalizeStatus(value),
      lineageStatus: ["stale", "invalid", "blocked", "unresolved", "unauthorized", "contradictory"].includes(primitive)
        ? primitive
        : "",
      reason: "",
    };
  }
  const lineageStatus = String(
    first(entry, "lineageStatus", "lineage_status", "validity", "identityValidity", "identity_validity") ?? "",
  ).trim().toLowerCase();
  return {
    status: normalizeStatus(
      first(entry, "effectiveStatus", "effective_status", "status"),
    ),
    lineageStatus,
    reason: String(first(entry, "reason", "lineageReason", "lineage_reason") ?? "").trim(),
  };
}

function downstreamOfProjectContext(stepId: string) {
  return stepId !== "step00";
}

function identityIsCurrent(identityValidity: string) {
  return CURRENT_IDENTITY_STATES.has(identityValidity.trim().toLowerCase());
}

function canonicalIdentityAvailable(identity: CanonicalDatasetIdentity | null | undefined) {
  return Boolean(
    identity?.project_id?.trim()
      && identity?.dataset_id?.trim()
      && identity?.dataset_version_id?.trim(),
  );
}

function backendDatasetIdentity(workflowStatus: Record<string, unknown> | null) {
  const value = record(first(workflowStatus, "datasetIdentity", "dataset_identity"));
  if (!value) return null;
  const projectId = String(first(value, "project_id", "projectId") ?? "").trim();
  const datasetId = String(first(value, "dataset_id", "datasetId") ?? "").trim();
  const versionId = String(first(value, "dataset_version_id", "datasetVersionId") ?? "").trim();
  return projectId && datasetId && versionId
    ? { project_id: projectId, dataset_id: datasetId, dataset_version_id: versionId }
    : null;
}

function activationRevision(value: unknown) {
  const revision = typeof value === "number"
    ? value
    : typeof value === "string" && /^\d+$/.test(value.trim())
      ? Number(value.trim())
      : Number.NaN;
  return Number.isSafeInteger(revision) && revision >= 1 ? revision : null;
}

function sameIdentity(
  left: CanonicalDatasetIdentity | null | undefined,
  right: CanonicalDatasetIdentity | null | undefined,
) {
  return Boolean(
    left
      && right
      && left.project_id === right.project_id
      && left.dataset_id === right.dataset_id
      && left.dataset_version_id === right.dataset_version_id,
  );
}

function firstIncomplete(steps: WorkflowStep[], preferred?: string) {
  if (preferred && steps.some((step) => step.id === preferred)) return preferred;
  return steps.find((step) => step.status !== "complete" && step.status !== "skipped")?.id
    ?? steps[steps.length - 1]?.id
    ?? "step00";
}

/**
 * Converts backend reconciliation into the only progress view that may drive
 * Predictive Modeling navigation. Historical completions remain untouched,
 * while absent or non-current identity fails dataset-dependent steps closed.
 */
export function deriveEffectiveWorkflowView(input: EffectiveWorkflowInput): EffectiveWorkflowView {
  const backend = record(input.backendState);
  const workflowStatus = record(first(backend, "workflowStatus", "workflow_status"));
  const rawEffectiveSteps = first(workflowStatus, "effectiveSteps", "effective_steps")
    ?? first(backend, "effectiveSteps", "effective_steps");
  const effectiveStepsRecord = record(rawEffectiveSteps);
  const rawEffectiveCompleted = first(backend, "effectiveCompletedSteps", "effective_completed_steps")
    ?? first(workflowStatus, "effectiveCompletedSteps", "effective_completed_steps");
  const rawEffectiveCurrent = first(backend, "effectiveCurrentStepId", "effective_current_step_id")
    ?? first(workflowStatus, "effectiveCurrentStepId", "effective_current_step_id");
  const rawIdentityValidity = first(workflowStatus, "identityValidity", "identity_validity")
    ?? first(backend, "identityValidity", "identity_validity");
  const authoritative = rawEffectiveCompleted !== undefined
    || rawEffectiveCurrent !== undefined
    || rawIdentityValidity !== undefined
    || rawEffectiveSteps !== undefined;
  const identityValidityRecord = record(rawIdentityValidity);
  const identityValidity = String(
    first(identityValidityRecord, "status", "validity")
      ?? rawIdentityValidity
      ?? "unverified",
  ).trim().toLowerCase() || "unverified";
  const rawHistoricalCompleted = first(backend, "historicalCompletedSteps", "historical_completed_steps")
    ?? first(workflowStatus, "historicalCompletedSteps", "historical_completed_steps")
    ?? first(backend, "completedSteps", "completed_steps");
  const historicalCompletedSteps = rawHistoricalCompleted === undefined
    ? input.workflowSteps
        .filter((step) => step.status === "complete" || step.status === "skipped")
        .map((step) => step.id)
    : identifiers(rawHistoricalCompleted);
  const completed = new Set(identifiers(rawEffectiveCompleted));
  const isPredictive = input.projectType === "predictive-modeling";
  const authoritativeIdentity = backendDatasetIdentity(workflowStatus);
  const activeRevision = activationRevision(input.datasetIdentity?.activation_revision);
  const workflowRevision = activationRevision(
    first(identityValidityRecord, "activationRevision", "activation_revision"),
  );
  const currentIdentity = identityIsCurrent(identityValidity)
    && canonicalIdentityAvailable(input.datasetIdentity)
    && sameIdentity(input.datasetIdentity, authoritativeIdentity)
    && activeRevision !== null
    && workflowRevision === activeRevision;

  const effectiveWorkflowSteps: EffectiveWorkflowStep[] = input.workflowSteps.map((step) => {
    const parsed = stepEntry(effectiveStepsRecord?.[step.id]);
    // `effectiveCompletedSteps` is the authoritative grant.  A status object
    // can explain a step or mark it in progress, but cannot independently
    // promote a browser-injected or stale step to complete/skipped.
    let status: WorkflowStepStatus = completed.has(step.id)
      ? parsed.status === "skipped" ? "skipped" : "complete"
      : parsed.status === "in_progress" ? "in_progress" : "pending";

    if (!authoritative && isPredictive) status = "pending";
    if (!authoritative && !isPredictive) status = step.status ?? "pending";
    if (
      isPredictive
      && downstreamOfProjectContext(step.id)
      && (!authoritative || !currentIdentity)
    ) {
      status = "pending";
    }
    if (["stale", "invalid", "blocked", "unresolved", "unauthorized", "contradictory"].includes(parsed.lineageStatus)) {
      status = "pending";
    }

    return {
      ...step,
      status,
      ...(parsed.lineageStatus ? { lineageStatus: parsed.lineageStatus } : {}),
      ...(parsed.reason ? { effectiveReason: parsed.reason } : {}),
    };
  });

  const effectiveCompletedSteps = effectiveWorkflowSteps
    .filter((step) => step.status === "complete" || step.status === "skipped")
    .map((step) => step.id);
  const requestedCurrent = typeof rawEffectiveCurrent === "string" ? rawEffectiveCurrent.trim() : "";
  const hasHistoricalDatasetWork = historicalCompletedSteps.some((stepId) => stepId !== "step00")
    || input.workflowSteps.some((step) => step.id !== "step00" && (step.status === "complete" || step.status === "skipped"));
  const failClosedReactivationStep = isPredictive && !currentIdentity && hasHistoricalDatasetWork
    ? "step01"
    : "";

  return {
    authoritative,
    identityValidity,
    historicalCompletedSteps,
    effectiveCompletedSteps,
    effectiveWorkflowSteps,
    effectiveCurrentStepId: firstIncomplete(
      effectiveWorkflowSteps,
      failClosedReactivationStep || requestedCurrent,
    ),
  };
}

export function effectiveProjectProgress(steps: WorkflowStep[]) {
  const total = Math.max(1, steps.length);
  const complete = steps.filter((step) => step.status === "complete" || step.status === "skipped").length;
  return { complete, total, percent: Math.round((complete / total) * 100) };
}
