// Durable Project Context persistence.
//
// Root cause of the reported loss (Phase A):
//   Step00_ProjectContext's `update`/`updateDetail`/`updateModelType`/
//   `acceptAiDraft`/`acceptBoundaryDraft` helpers only called `setContext(...)`
//   -- pure React state. The single persistence path, `persistDraft()`, was
//   reachable from exactly two places: "Mark Page Complete" and "Continue to
//   Data Acquisition". Leaving the page by any other route (sidebar link, Open
//   Project, refresh, back/forward) discarded every keystroke, because nothing
//   had ever been written -- not to the backend and not even to localStorage.
//
//   Compounding it, hydration was `useState(() => loadProjectContext())`, which
//   reads ONE global unscoped localStorage key ("modeling-tool-project-context").
//   The page never fetched backend state, so content that HAD been saved by
//   Continue was still not restored on reopen, and two different projects shared
//   one browser key.
//
// This module makes the backend project record authoritative and adds the
// hydrate / debounced-autosave / flush lifecycle the page was missing.
import { defaultProjectContext, type ProjectContext } from "./projectContext";

const API_BASE =
  (import.meta.env?.VITE_API_BASE as string | undefined)?.replace(/\/$/, "") ||
  "http://127.0.0.1:8001/api";

/** Bumped when the persisted shape changes in a way that needs migration. */
export const PROJECT_CONTEXT_SCHEMA_VERSION = 2;

export type SaveStatus =
  | "idle"
  | "unsaved"
  | "saving"
  | "saved"
  | "failed"
  | "offline"
  | "conflict";

export type HydrationResult = {
  context: ProjectContext | null;
  revision: string;
  /** True when the backend held no Project Context yet (genuinely new project). */
  isNew: boolean;
};

export type SaveResult =
  | { ok: true; revision: string }
  | { ok: false; reason: "conflict" | "offline" | "error"; message: string; revision?: string };

/** Project-scoped convenience cache. Never authoritative -- only used to offer a
 *  local draft back to the user when the backend is unreachable. The previous
 *  single global key let one project read another's context. */
export function draftCacheKey(projectId: string): string {
  return `atlas:project-context-draft:${projectId || "unassigned"}`;
}

export function readDraftCache(projectId: string): { context: ProjectContext; savedAt: string } | null {
  try {
    const raw = localStorage.getItem(draftCacheKey(projectId));
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (!parsed?.context) return null;
    return parsed;
  } catch {
    return null;
  }
}

export function writeDraftCache(projectId: string, context: ProjectContext): void {
  try {
    localStorage.setItem(
      draftCacheKey(projectId),
      JSON.stringify({ context, savedAt: new Date().toISOString() })
    );
  } catch {
    // A full or unavailable localStorage must never break the authoritative save.
  }
}

export function clearDraftCache(projectId: string): void {
  try {
    localStorage.removeItem(draftCacheKey(projectId));
  } catch {
    // ignore
  }
}

/**
 * Merges a persisted payload onto the defaults.
 *
 * Legacy/partial projects (Phase E/10) simply lack keys; every absent field
 * falls back to its default rather than erroring. `fraudDetails` is merged one
 * level deep because that is where the governance narrative fields live.
 */
export function migrateStoredContext(stored: unknown): ProjectContext | null {
  if (!stored || typeof stored !== "object") return null;
  const parsed = stored as Partial<ProjectContext>;
  return {
    ...defaultProjectContext,
    ...parsed,
    fraudDetails: {
      ...defaultProjectContext.fraudDetails,
      ...(parsed.fraudDetails ?? {}),
    },
    acceptedAiDrafts: Array.isArray(parsed.acceptedAiDrafts) ? parsed.acceptedAiDrafts : [],
    monitoringMetrics: Array.isArray(parsed.monitoringMetrics) && parsed.monitoringMetrics.length
      ? parsed.monitoringMetrics
      : defaultProjectContext.monitoringMetrics,
    regulatoryEnvironment: Array.isArray(parsed.regulatoryEnvironment) && parsed.regulatoryEnvironment.length
      ? parsed.regulatoryEnvironment
      : defaultProjectContext.regulatoryEnvironment,
  };
}

/**
 * True when a context carries no analyst-entered narrative content.
 *
 * Compares against the defaults rather than testing for blankness: some fields
 * ship with non-empty placeholders (e.g. `humanReviewRequired` defaults to
 * "To be determined"), so a pristine form is not literally blank. Used to
 * guarantee an untouched form never overwrites stored content.
 */
export function isEmptyContext(context: ProjectContext | null | undefined): boolean {
  if (!context) return true;
  const topLevel: (keyof ProjectContext)[] = [
    "businessObjective",
    "intendedModelUse",
    "targetDefinition",
    "populationDefinition",
    "observationWindow",
    "performanceWindow",
    "modelingMissionSummary",
  ];
  const governance: (keyof ProjectContext["fraudDetails"])[] = [
    "approvedUses",
    "prohibitedUses",
    "humanReviewRequired",
    "overrideAuthority",
  ];

  const changedTopLevel = topLevel.some((key) => {
    const value = String(context[key] ?? "").trim();
    return value !== "" && value !== String(defaultProjectContext[key] ?? "").trim();
  });
  if (changedTopLevel) return false;

  const changedGovernance = governance.some((key) => {
    const value = String(context.fraudDetails?.[key] ?? "").trim();
    return value !== "" && value !== String(defaultProjectContext.fraudDetails[key] ?? "").trim();
  });
  return !changedGovernance;
}

/** Fetches the authoritative Project Context for a project. */
export async function hydrateProjectContext(projectId: string): Promise<HydrationResult> {
  if (!projectId) return { context: null, revision: "", isNew: true };

  const response = await fetch(`${API_BASE}/projects/${encodeURIComponent(projectId)}`, {
    credentials: "include",
  });
  if (response.status === 404) return { context: null, revision: "", isNew: true };
  if (!response.ok) {
    throw new Error(`Project Context could not be loaded (HTTP ${response.status}).`);
  }
  const payload = await response.json().catch(() => null);
  const metadata = payload?.project?.metadata ?? {};
  const stored = metadata.projectContext;
  const revision = String(metadata.projectContextRevision ?? metadata.projectContextSavedAt ?? "");

  const context = migrateStoredContext(stored);
  return { context, revision, isNew: !context };
}

/**
 * Writes Project Context to the authoritative backend record.
 *
 * `expectedRevision` is the revision this client last read. When the stored
 * revision has moved on, the write is refused as a conflict instead of silently
 * clobbering a newer edit from another tab.
 */
export async function saveProjectContextToBackend(input: {
  projectId: string;
  context: ProjectContext;
  expectedRevision: string;
  validationStatus: string;
  signal?: AbortSignal;
}): Promise<SaveResult> {
  const { projectId, context, expectedRevision, validationStatus, signal } = input;
  if (!projectId) {
    return { ok: false, reason: "error", message: "No active project is selected." };
  }

  // Read-before-write conflict check. The project record has no ETag, so the
  // stored revision is compared explicitly.
  try {
    const current = await hydrateProjectContext(projectId);
    if (current.revision && expectedRevision && current.revision !== expectedRevision) {
      return {
        ok: false,
        reason: "conflict",
        message: "This project was updated elsewhere. Reload the latest version or keep your draft.",
        revision: current.revision,
      };
    }
  } catch {
    // A failed pre-check must not block the save; the write below reports the
    // real outcome.
  }

  const revision = `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
  try {
    const response = await fetch(`${API_BASE}/projects/${encodeURIComponent(projectId)}`, {
      method: "PUT",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      signal,
      body: JSON.stringify({
        projectName: context.projectName || "Untitled ATLAS Project",
        projectType: "predictive-modeling",
        workflowType: "predictive-modeling",
        metadata: {
          modelId: context.modelId,
          projectContext: context,
          projectContextValidationStatus: validationStatus,
          projectContextSavedAt: new Date().toISOString(),
          projectContextRevision: revision,
          projectContextSchemaVersion: PROJECT_CONTEXT_SCHEMA_VERSION,
        },
      }),
    });
    if (!response.ok) {
      const detail = await response.json().catch(() => null);
      return {
        ok: false,
        reason: response.status >= 500 ? "offline" : "error",
        message: detail?.detail ?? `Project Context save failed (HTTP ${response.status}).`,
      };
    }
    return { ok: true, revision };
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") {
      return { ok: false, reason: "error", message: "Save superseded by a newer change." };
    }
    return {
      ok: false,
      reason: "offline",
      message: "ATLAS could not reach the server. Your draft is kept locally and will be retried.",
    };
  }
}

/** Stable comparison so unchanged values are never re-saved. */
export function contextFingerprint(context: ProjectContext): string {
  return JSON.stringify({
    ...context,
    // Volatile fields must not make an otherwise-unchanged context look dirty.
    updatedAt: undefined,
  });
}
