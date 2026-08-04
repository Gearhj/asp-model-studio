// Project Context autosave lifecycle: hydrate -> debounced save -> flush.
//
// The page previously persisted only on "Continue" / "Mark Page Complete", so
// any other way of leaving lost every keystroke. This hook makes persistence a
// property of editing rather than of pressing a particular button.
import { useCallback, useEffect, useRef, useState } from "react";
import type { ProjectContext } from "./projectContext";
import {
  clearDraftCache,
  contextFingerprint,
  hydrateProjectContext,
  isEmptyContext,
  readDraftCache,
  saveProjectContextToBackend,
  writeDraftCache,
  type SaveStatus,
} from "./projectContextPersistence";
import {
  changedProjectContextFields,
  type ProjectMetadataUpdateSource,
} from "./projectContextMetadata";

const DEBOUNCE_MS = 800;
type InFlightSaveOutcome = "acknowledged" | "failed";

export type AutosaveState = {
  status: SaveStatus;
  lastSavedAt: string;
  message: string;
  hydrated: boolean;
  hydrating: boolean;
  dirty: boolean;
};

export type ProjectContextSaveNotification = {
  projectId: string;
  projectRevision: string;
  requestId: string;
  projectName: string;
  modelId: string;
  changedFields: string[];
  source: ProjectMetadataUpdateSource;
  savedAt: string;
  requestSequence: number;
  projectContext: ProjectContext;
};

export function useProjectContextAutosave(input: {
  projectId: string;
  authenticatedUserId: string;
  context: ProjectContext;
  validationStatus: string;
  /** Applies hydrated backend content to the page's own state. */
  onHydrated: (context: ProjectContext) => void;
  /** Runs once only after the backend acknowledges an actual changed PUT. */
  onSaved?: (notification: ProjectContextSaveNotification) => void;
  enabled?: boolean;
}) {
  const {
    projectId,
    authenticatedUserId,
    context,
    validationStatus,
    onHydrated,
    enabled = true,
  } = input;

  const [state, setState] = useState<AutosaveState>({
    status: "idle",
    lastSavedAt: "",
    message: "",
    hydrated: false,
    hydrating: true,
    dirty: false,
  });

  const revisionRef = useRef("");
  const savedFingerprintRef = useRef<string | null>(null);
  const savedContextRef = useRef<ProjectContext | null>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const inFlightRef = useRef<AbortController | null>(null);
  // Project Context writes are serialized. A request that has reached the
  // backend may commit even when its client-side fetch is aborted, so starting
  // an overlapping PUT would make the authoritative revision unknowable.
  const inFlightFingerprintRef = useRef<string | null>(null);
  const inFlightCompletionRef = useRef<Promise<InFlightSaveOutcome> | null>(null);
  const inFlightSettleRef = useRef<((outcome: InFlightSaveOutcome) => void) | null>(null);
  // Monotonic sequence: a slower earlier save may never apply its result over a
  // newer one (Phase F minimum requirement).
  const sequenceRef = useRef(0);
  const appliedSequenceRef = useRef(0);
  const latestContextRef = useRef(context);
  latestContextRef.current = context;
  const onHydratedRef = useRef(onHydrated);
  onHydratedRef.current = onHydrated;
  const onSavedRef = useRef(input.onSaved);
  onSavedRef.current = input.onSaved;
  const hydratedRef = useRef(false);
  const dirtyRef = useRef(false);
  const scopeGenerationRef = useRef(0);
  const scopeActiveRef = useRef(false);

  // ---- Hydration ---------------------------------------------------------
  useEffect(() => {
    if (!enabled || !projectId || !authenticatedUserId) {
      scopeActiveRef.current = false;
      setState((current) => ({ ...current, hydrating: false, hydrated: true, dirty: false }));
      dirtyRef.current = false;
      hydratedRef.current = true;
      return undefined;
    }
    const scopeGeneration = ++scopeGenerationRef.current;
    scopeActiveRef.current = true;
    let alive = true;
    inFlightRef.current?.abort();
    inFlightSettleRef.current?.("failed");
    inFlightCompletionRef.current = null;
    inFlightSettleRef.current = null;
    revisionRef.current = "";
    savedFingerprintRef.current = null;
    savedContextRef.current = null;
    sequenceRef.current = 0;
    appliedSequenceRef.current = 0;
    inFlightFingerprintRef.current = null;
    hydratedRef.current = false;
    dirtyRef.current = false;
    setState((current) => ({
      ...current,
      hydrating: true,
      hydrated: false,
      status: "idle",
      dirty: false,
    }));

    hydrateProjectContext(projectId)
      .then((result) => {
        if (!alive || scopeGeneration !== scopeGenerationRef.current) return;
        revisionRef.current = result.revision;
        if (result.context) {
          const backendFingerprint = contextFingerprint(result.context);
          const cached = readDraftCache(projectId, authenticatedUserId);
          const cachedFingerprint = cached ? contextFingerprint(cached.context) : "";
          const backendSavedAt = Date.parse(result.savedAt || "");
          const cachedSavedAt = Date.parse(cached?.savedAt || "");
          const cachedIsNewer = Boolean(
            cached
            && !isEmptyContext(cached.context)
            && cachedFingerprint !== backendFingerprint
            && (
              !Number.isFinite(backendSavedAt)
              || (Number.isFinite(cachedSavedAt) && cachedSavedAt > backendSavedAt)
            )
          );
          savedContextRef.current = result.context;
          savedFingerprintRef.current = backendFingerprint;
          if (cachedIsNewer && cached) {
            latestContextRef.current = cached.context;
            onHydratedRef.current(cached.context);
            dirtyRef.current = true;
            setState({
              status: "unsaved",
              lastSavedAt: result.savedAt,
              message: "Recovered a newer unsaved local draft. It will be saved automatically.",
              hydrated: true,
              hydrating: false,
              dirty: true,
            });
          } else {
            latestContextRef.current = result.context;
            onHydratedRef.current(result.context);
            dirtyRef.current = false;
            clearDraftCache(projectId, authenticatedUserId);
            setState({
              status: "saved",
              lastSavedAt: result.savedAt,
              message: "Loaded from ATLAS database.",
              hydrated: true,
              hydrating: false,
              dirty: false,
            });
          }
        } else {
          // Nothing stored yet: offer an unsent local draft back if one exists.
          const cached = readDraftCache(projectId, authenticatedUserId);
          if (cached && !isEmptyContext(cached.context)) {
            onHydratedRef.current(cached.context);
            savedContextRef.current = null;
            savedFingerprintRef.current = null;
            dirtyRef.current = true;
            setState({
              status: "unsaved",
              lastSavedAt: "",
              message: "Recovered an unsaved local draft. It will be saved automatically.",
              hydrated: true,
              hydrating: false,
              dirty: true,
            });
          } else {
            savedFingerprintRef.current = null;
            dirtyRef.current = false;
            setState({ status: "idle", lastSavedAt: "", message: "", hydrated: true, hydrating: false, dirty: false });
          }
        }
        hydratedRef.current = true;
      })
      .catch(() => {
        if (!alive || scopeGeneration !== scopeGenerationRef.current) return;
        const cached = readDraftCache(projectId, authenticatedUserId);
        if (cached && !isEmptyContext(cached.context)) onHydratedRef.current(cached.context);
        dirtyRef.current = Boolean(cached && !isEmptyContext(cached.context));
        setState({
          status: "offline",
          lastSavedAt: "",
          message: "ATLAS could not load saved Project Context. Editing is disabled until it loads.",
          hydrated: false,
          hydrating: false,
          dirty: dirtyRef.current,
        });
      });

    return () => {
      alive = false;
      if (
        dirtyRef.current
        && contextFingerprint(latestContextRef.current) !== savedFingerprintRef.current
      ) {
        writeDraftCache(projectId, authenticatedUserId, latestContextRef.current);
      }
      scopeActiveRef.current = false;
      hydratedRef.current = false;
      if (scopeGenerationRef.current === scopeGeneration) {
        scopeGenerationRef.current += 1;
      }
      sequenceRef.current += 1;
      inFlightRef.current?.abort();
      inFlightSettleRef.current?.("failed");
      inFlightRef.current = null;
      inFlightFingerprintRef.current = null;
      inFlightCompletionRef.current = null;
      inFlightSettleRef.current = null;
      if (timerRef.current) clearTimeout(timerRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [authenticatedUserId, projectId, enabled]);

  // ---- Save --------------------------------------------------------------
  const performSave = useCallback(
    async (toSave: ProjectContext): Promise<boolean> => {
      if (!scopeActiveRef.current || !hydratedRef.current) return false;
      const fingerprint = contextFingerprint(toSave);
      // Coalesce edits behind the active request. Its acknowledgement supplies
      // the only safe revision for the follow-up write.
      const activeSave = inFlightCompletionRef.current;
      if (activeSave) {
        const waitingScopeGeneration = scopeGenerationRef.current;
        dirtyRef.current = true;
        writeDraftCache(projectId, authenticatedUserId, toSave);
        setState((current) => ({ ...current, status: "unsaved", dirty: true }));
        const outcome = await activeSave;
        if (
          outcome === "failed"
          || waitingScopeGeneration !== scopeGenerationRef.current
          || !scopeActiveRef.current
          || !hydratedRef.current
        ) {
          return false;
        }
        return performSave(latestContextRef.current);
      }
      if (fingerprint === savedFingerprintRef.current) return true; // nothing changed
      const scopeGeneration = scopeGenerationRef.current;

      inFlightRef.current?.abort();
      const controller = new AbortController();
      inFlightRef.current = controller;
      inFlightFingerprintRef.current = fingerprint;
      let settleSave!: (outcome: InFlightSaveOutcome) => void;
      const completion = new Promise<InFlightSaveOutcome>((resolve) => {
        settleSave = resolve;
      });
      inFlightCompletionRef.current = completion;
      inFlightSettleRef.current = settleSave;
      const finishSave = (outcome: InFlightSaveOutcome) => {
        if (inFlightCompletionRef.current === completion) {
          inFlightRef.current = null;
          inFlightFingerprintRef.current = null;
          inFlightCompletionRef.current = null;
          inFlightSettleRef.current = null;
        }
        settleSave(outcome);
      };
      const sequence = ++sequenceRef.current;

      dirtyRef.current = true;
      setState((current) => ({ ...current, status: "saving", message: "", dirty: true }));
      // The local convenience copy is written first so a crash mid-save still
      // leaves something recoverable.
      writeDraftCache(projectId, authenticatedUserId, toSave);

      const result = await saveProjectContextToBackend({
        projectId,
        context: toSave,
        expectedRevision: revisionRef.current,
        validationStatus,
        signal: controller.signal,
      });
      // A superseded save must never report over a newer one.
      if (
        scopeGeneration !== scopeGenerationRef.current
        || !scopeActiveRef.current
        || sequence !== sequenceRef.current
        || sequence < appliedSequenceRef.current
      ) {
        finishSave("failed");
        return false;
      }
      appliedSequenceRef.current = sequence;

      if (result.ok) {
        const changedFields = changedProjectContextFields(
          savedContextRef.current as unknown as Record<string, unknown> | null,
          result.context as unknown as Record<string, unknown>,
        );
        const acknowledgedFingerprint = contextFingerprint(result.context);
        revisionRef.current = result.revision;
        savedFingerprintRef.current = acknowledgedFingerprint;
        savedContextRef.current = result.context;
        onSavedRef.current?.({
          projectId: result.projectId,
          projectRevision: result.revision,
          requestId: `project-context-save:${result.projectId}:${result.revision}:${sequence}`,
          projectName: result.projectName,
          modelId: result.modelId,
          changedFields,
          source: result.source,
          savedAt: result.savedAt,
          requestSequence: sequence,
          projectContext: result.context,
        });

        const latestFingerprint = contextFingerprint(latestContextRef.current);
        if (latestFingerprint !== acknowledgedFingerprint) {
          // The response is authoritative for the submitted revision, but it
          // must not clear or report over a newer visible edit. Preserve that
          // edit and immediately serialize a follow-up against this revision.
          dirtyRef.current = true;
          writeDraftCache(projectId, authenticatedUserId, latestContextRef.current);
          setState({
            status: "unsaved",
            lastSavedAt: result.savedAt,
            message: "A newer edit is waiting to be saved.",
            hydrated: true,
            hydrating: false,
            dirty: true,
          });
          finishSave("acknowledged");
          return performSave(latestContextRef.current);
        }

        clearDraftCache(projectId, authenticatedUserId);
        dirtyRef.current = false;
        setState({
          status: "saved",
          lastSavedAt: result.savedAt,
          message: "",
          hydrated: true,
          hydrating: false,
          dirty: false,
        });
        finishSave("acknowledged");
        return true;
      }

      setState((current) => ({
        status: result.reason === "conflict" ? "conflict" : result.reason === "offline" ? "offline" : "failed",
        lastSavedAt: current.lastSavedAt,
        message: result.message,
        hydrated: true,
        hydrating: false,
        dirty: true,
      }));
      finishSave("failed");
      return false;
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [authenticatedUserId, projectId, validationStatus]
  );

  // ---- Debounced autosave on change --------------------------------------
  useEffect(() => {
    if (!enabled || !projectId || !authenticatedUserId || !hydratedRef.current || !scopeActiveRef.current) return undefined;
    const fingerprint = contextFingerprint(context);
    if (fingerprint === savedFingerprintRef.current && !inFlightFingerprintRef.current) {
      if (timerRef.current) clearTimeout(timerRef.current);
      clearDraftCache(projectId, authenticatedUserId);
      dirtyRef.current = false;
      setState((current) => ({
        ...current,
        status: current.hydrated ? "saved" : current.status,
        message: "",
        dirty: false,
      }));
      return undefined;
    }

    setState((current) =>
      current.status === "saving" ? current : { ...current, status: "unsaved", dirty: true }
    );
    dirtyRef.current = true;
    writeDraftCache(projectId, authenticatedUserId, context);

    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = setTimeout(() => {
      void performSave(latestContextRef.current);
    }, DEBOUNCE_MS);

    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [authenticatedUserId, context, enabled, projectId, performSave]);

  /** Immediate save: field blur, Continue, and ATLAS-controlled navigation. */
  const flush = useCallback(async (): Promise<boolean> => {
    if (!enabled || !projectId || !hydratedRef.current || !scopeActiveRef.current) return true;
    if (timerRef.current) clearTimeout(timerRef.current);
    return performSave(latestContextRef.current);
  }, [enabled, projectId, performSave]);

  /** Immediate save of an explicit draft, used by governed completion actions. */
  const saveNow = useCallback(async (toSave: ProjectContext): Promise<boolean> => {
    if (!enabled || !projectId || !hydratedRef.current || !scopeActiveRef.current) return false;
    if (timerRef.current) clearTimeout(timerRef.current);
    const requestedFingerprint = contextFingerprint(toSave);
    latestContextRef.current = toSave;
    const persisted = await performSave(toSave);
    return Boolean(
      persisted
      && requestedFingerprint === savedFingerprintRef.current
      && requestedFingerprint === contextFingerprint(latestContextRef.current)
    );
  }, [enabled, projectId, performSave]);

  /** Adopt an already verified, newer backend metadata revision without
   * treating it as a local edit or issuing a compensating save. */
  const adoptAuthoritativeContext = useCallback((input: {
    context: ProjectContext;
    revision: string;
    savedAt: string;
  }) => {
    if (!input.revision || !projectId || dirtyRef.current || !scopeActiveRef.current) return false;
    if (timerRef.current) clearTimeout(timerRef.current);
    sequenceRef.current += 1;
    inFlightRef.current?.abort();
    inFlightSettleRef.current?.("failed");
    inFlightRef.current = null;
    inFlightFingerprintRef.current = null;
    inFlightCompletionRef.current = null;
    inFlightSettleRef.current = null;
    revisionRef.current = input.revision;
    savedContextRef.current = input.context;
    savedFingerprintRef.current = contextFingerprint(input.context);
    latestContextRef.current = input.context;
    dirtyRef.current = false;
    clearDraftCache(projectId, authenticatedUserId);
    onHydratedRef.current(input.context);
    setState({
      status: "saved",
      lastSavedAt: input.savedAt,
      message: "Refreshed from the acknowledged ATLAS project revision.",
      hydrated: true,
      hydrating: false,
      dirty: false,
    });
    return true;
  }, [authenticatedUserId, projectId]);

  const retry = useCallback(() => {
    void performSave(latestContextRef.current);
  }, [performSave]);

  /** Discards the local draft and reloads authoritative content (conflict path). */
  const reloadLatest = useCallback(async () => {
    const scopeGeneration = scopeGenerationRef.current;
    const result = await hydrateProjectContext(projectId);
    if (scopeGeneration !== scopeGenerationRef.current || !scopeActiveRef.current) return;
    if (result.context) {
      revisionRef.current = result.revision;
      onHydratedRef.current(result.context);
      savedContextRef.current = result.context;
      savedFingerprintRef.current = contextFingerprint(result.context);
      dirtyRef.current = false;
      latestContextRef.current = result.context;
      clearDraftCache(projectId, authenticatedUserId);
      setState({
        status: "saved",
        lastSavedAt: new Date().toISOString(),
        message: "Reloaded the latest saved version.",
        hydrated: true,
        hydrating: false,
        dirty: false,
      });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [authenticatedUserId, projectId]);

  /** Overwrites the newer stored content with this tab's draft, after the user
   *  explicitly chooses to. */
  const keepMyDraft = useCallback(async () => {
    const scopeGeneration = scopeGenerationRef.current;
    const latest = await hydrateProjectContext(projectId).catch(() => null);
    if (scopeGeneration !== scopeGenerationRef.current || !scopeActiveRef.current) return;
    if (latest) revisionRef.current = latest.revision;
    await performSave(latestContextRef.current);
  }, [projectId, performSave]);

  // ---- Unload best-effort -------------------------------------------------
  useEffect(() => {
    if (!enabled || !projectId) return undefined;
    const handler = () => {
      const fingerprint = contextFingerprint(latestContextRef.current);
      if (fingerprint === savedFingerprintRef.current) return;
      // Unload is a last resort, never the primary path: the local cache is
      // written synchronously and the debounced/blur saves do the real work.
      writeDraftCache(projectId, authenticatedUserId, latestContextRef.current);
    };
    window.addEventListener("pagehide", handler);
    window.addEventListener("beforeunload", handler);
    return () => {
      window.removeEventListener("pagehide", handler);
      window.removeEventListener("beforeunload", handler);
    };
  }, [authenticatedUserId, enabled, projectId]);

  return {
    ...state,
    flush,
    saveNow,
    adoptAuthoritativeContext,
    retry,
    reloadLatest,
    keepMyDraft,
  };
}
