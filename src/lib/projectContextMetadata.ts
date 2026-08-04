import type {
  AuthoritativeProjectContextReadiness,
  AuthoritativeProjectReadyContext,
} from "./authoritativeProjectContext";
import type { ProjectContext } from "./projectContext";

export const PROJECT_METADATA_REFRESH_STATUSES = [
  "idle",
  "saving",
  "refreshing",
  "saved",
  "error",
] as const;

export type ProjectMetadataRefreshStatus =
  (typeof PROJECT_METADATA_REFRESH_STATUSES)[number];

export type ProjectMetadataUpdateSource =
  | "user_save"
  | "background_verification";

export type ProjectMetadataUpdate = {
  projectId: string;
  projectRevision: string;
  requestId: string;
  projectName: string;
  modelId: string;
  changedFields: string[];
  source: ProjectMetadataUpdateSource;
  savedAt: string;
  actorUserId: string;
  requestSequence: number;
  projectContext: ProjectContext;
};

export type ProjectContextUpdatedEventDetail = {
  project_id: string;
  project_revision: string;
  request_id: string;
  changed_fields: string[];
  source: "user_save";
  saved_at: string;
};

export type ProjectMetadataUpdateDisposition =
  | "applied"
  | "duplicate"
  | "stale_revision"
  | "stale_sequence"
  | "wrong_project"
  | "wrong_user"
  | "identity_not_ready";

export type ProjectMetadataUpdateResult = {
  disposition: ProjectMetadataUpdateDisposition;
  readiness: AuthoritativeProjectContextReadiness;
  requestSequence: number;
};

export function registerProjectMetadataEvent(
  emittedKeys: Set<string>,
  update: ProjectMetadataUpdate,
): boolean {
  if (update.source !== "user_save" || !update.requestId) return false;
  const scope = `${update.actorUserId}:${update.projectId}`;
  const requestKey = `request:${scope}:${update.requestId}`;
  const revisionKey = `revision:${scope}:${update.projectRevision}`;
  if (emittedKeys.has(requestKey) || emittedKeys.has(revisionKey)) return false;
  emittedKeys.add(requestKey);
  emittedKeys.add(revisionKey);
  return true;
}

export function projectContextUpdatedEventDetail(
  update: ProjectMetadataUpdate,
): ProjectContextUpdatedEventDetail | null {
  if (update.source !== "user_save" || !update.requestId) return null;
  return {
    project_id: update.projectId,
    project_revision: update.projectRevision,
    request_id: update.requestId,
    changed_fields: [...update.changedFields],
    source: "user_save",
    saved_at: update.savedAt,
  };
}

function revisionOrdinal(value: string): number | null {
  const text = String(value || "").trim();
  if (!text) return null;
  const numericPrefix = text.match(/^(\d{10,})/)?.[1];
  if (numericPrefix) {
    const parsed = Number(numericPrefix);
    if (Number.isSafeInteger(parsed)) return parsed;
  }
  const parsedDate = Date.parse(text);
  return Number.isFinite(parsedDate) ? parsedDate : null;
}

export function compareProjectMetadataRevisions(
  currentRevision: string,
  incomingRevision: string,
): "same" | "older" | "newer" | "unknown" {
  const current = String(currentRevision || "").trim();
  const incoming = String(incomingRevision || "").trim();
  if (current && incoming && current === incoming) return "same";
  if (!current && incoming) return "newer";
  if (!incoming) return "unknown";
  const currentOrdinal = revisionOrdinal(current);
  const incomingOrdinal = revisionOrdinal(incoming);
  if (currentOrdinal == null || incomingOrdinal == null) return "unknown";
  // Different opaque suffixes can represent distinct writes in the same
  // millisecond. Exact equality was handled above; equal ordinals are not a
  // safe duplicate signal.
  if (incomingOrdinal === currentOrdinal) return "unknown";
  return incomingOrdinal < currentOrdinal ? "older" : "newer";
}

export function changedProjectContextFields(
  previous: Record<string, unknown> | null,
  next: Record<string, unknown>,
): string[] {
  if (!previous) return Object.keys(next).sort();
  const keys = new Set([...Object.keys(previous), ...Object.keys(next)]);
  return [...keys]
    .filter((key) => JSON.stringify(previous[key]) !== JSON.stringify(next[key]))
    .sort();
}

export function applyProjectMetadataUpdate(input: {
  readiness: AuthoritativeProjectContextReadiness;
  update: ProjectMetadataUpdate;
  currentUserId: string;
  lastRequestSequence: number;
}): ProjectMetadataUpdateResult {
  const { readiness, update } = input;
  if (readiness.status !== "ready") {
    return {
      disposition: "identity_not_ready",
      readiness,
      requestSequence: input.lastRequestSequence,
    };
  }
  if (
    update.projectId !== readiness.routeProjectId
    || update.projectId !== readiness.project.projectId
  ) {
    return {
      disposition: "wrong_project",
      readiness,
      requestSequence: input.lastRequestSequence,
    };
  }
  if (!input.currentUserId || update.actorUserId !== input.currentUserId) {
    return {
      disposition: "wrong_user",
      readiness,
      requestSequence: input.lastRequestSequence,
    };
  }
  const comparison = compareProjectMetadataRevisions(
    readiness.project.metadataRevision,
    update.projectRevision,
  );
  if (comparison === "same") {
    return {
      disposition: "duplicate",
      readiness,
      // A rejected revision must not move the sequence high-water mark. The
      // sequence guard is only a fallback for otherwise incomparable revisions.
      requestSequence: input.lastRequestSequence,
    };
  }
  if (comparison === "older") {
    return {
      disposition: "stale_revision",
      readiness,
      requestSequence: input.lastRequestSequence,
    };
  }
  if (
    comparison === "unknown"
    && update.requestSequence <= input.lastRequestSequence
  ) {
    return {
      disposition: "stale_sequence",
      readiness,
      requestSequence: input.lastRequestSequence,
    };
  }

  const next: AuthoritativeProjectReadyContext = {
    ...readiness,
    project: {
      ...readiness.project,
      projectName: update.projectName || readiness.project.projectName,
      modelId: update.modelId || readiness.project.modelId,
      metadataRevision: update.projectRevision,
      metadataSavedAt: update.savedAt || readiness.project.metadataSavedAt,
      projectContext: update.projectContext,
      updatedAt: update.savedAt || readiness.project.updatedAt,
    },
    message: "The exact authorized project identity is ready; project metadata is current.",
  };
  return {
    disposition: "applied",
    readiness: next,
    requestSequence: update.requestSequence,
  };
}
