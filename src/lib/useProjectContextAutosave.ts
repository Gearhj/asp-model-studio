// Project Context autosave lifecycle: hydrate -> debounced save -> flush.
//
// The page previously persisted only on "Continue" / "Mark Page Complete", so
// any other way of leaving lost every keystroke. This hook makes persistence a
// property of editing rather than of pressing a particular button.
import { useCallback, useEffect, useRef, useState } from "react";
import type { ProjectContext } from "./projectContext";
import {
  contextFingerprint,
  hydrateProjectContext,
  isEmptyContext,
  readDraftCache,
  saveProjectContextToBackend,
  writeDraftCache,
  type SaveStatus,
} from "./projectContextPersistence";

const DEBOUNCE_MS = 800;

export type AutosaveState = {
  status: SaveStatus;
  lastSavedAt: string;
  message: string;
  hydrated: boolean;
  hydrating: boolean;
};

export function useProjectContextAutosave(input: {
  projectId: string;
  context: ProjectContext;
  validationStatus: string;
  /** Applies hydrated backend content to the page's own state. */
  onHydrated: (context: ProjectContext) => void;
  enabled?: boolean;
}) {
  const { projectId, context, validationStatus, onHydrated, enabled = true } = input;

  const [state, setState] = useState<AutosaveState>({
    status: "idle",
    lastSavedAt: "",
    message: "",
    hydrated: false,
    hydrating: true,
  });

  const revisionRef = useRef("");
  const savedFingerprintRef = useRef<string | null>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const inFlightRef = useRef<AbortController | null>(null);
  // Monotonic sequence: a slower earlier save may never apply its result over a
  // newer one (Phase F minimum requirement).
  const sequenceRef = useRef(0);
  const appliedSequenceRef = useRef(0);
  const latestContextRef = useRef(context);
  latestContextRef.current = context;
  const hydratedRef = useRef(false);

  // ---- Hydration ---------------------------------------------------------
  useEffect(() => {
    if (!enabled || !projectId) {
      setState((current) => ({ ...current, hydrating: false, hydrated: true }));
      hydratedRef.current = true;
      return undefined;
    }
    let alive = true;
    hydratedRef.current = false;
    setState((current) => ({ ...current, hydrating: true, hydrated: false, status: "idle" }));

    hydrateProjectContext(projectId)
      .then((result) => {
        if (!alive) return;
        revisionRef.current = result.revision;
        if (result.context) {
          // Backend content wins over an empty form. A non-empty local draft is
          // only preserved when the backend genuinely has nothing.
          onHydrated(result.context);
          savedFingerprintRef.current = contextFingerprint(result.context);
          setState({
            status: "saved",
            lastSavedAt: result.revision ? new Date().toISOString() : "",
            message: "Loaded from ATLAS database.",
            hydrated: true,
            hydrating: false,
          });
        } else {
          // Nothing stored yet: offer an unsent local draft back if one exists.
          const cached = readDraftCache(projectId);
          if (cached && !isEmptyContext(cached.context)) {
            onHydrated(cached.context);
            savedFingerprintRef.current = null;
            setState({
              status: "unsaved",
              lastSavedAt: "",
              message: "Recovered an unsaved local draft. It will be saved automatically.",
              hydrated: true,
              hydrating: false,
            });
          } else {
            savedFingerprintRef.current = null;
            setState({ status: "idle", lastSavedAt: "", message: "", hydrated: true, hydrating: false });
          }
        }
        hydratedRef.current = true;
      })
      .catch(() => {
        if (!alive) return;
        const cached = readDraftCache(projectId);
        if (cached && !isEmptyContext(cached.context)) onHydrated(cached.context);
        setState({
          status: "offline",
          lastSavedAt: "",
          message: "ATLAS could not load saved Project Context. Editing is disabled until it loads.",
          hydrated: false,
          hydrating: false,
        });
      });

    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId, enabled]);

  // ---- Save --------------------------------------------------------------
  const performSave = useCallback(
    async (toSave: ProjectContext): Promise<boolean> => {
      const fingerprint = contextFingerprint(toSave);
      if (fingerprint === savedFingerprintRef.current) return true; // nothing changed

      inFlightRef.current?.abort();
      const controller = new AbortController();
      inFlightRef.current = controller;
      const sequence = ++sequenceRef.current;

      setState((current) => ({ ...current, status: "saving", message: "" }));
      // The local convenience copy is written first so a crash mid-save still
      // leaves something recoverable.
      writeDraftCache(projectId, toSave);

      const result = await saveProjectContextToBackend({
        projectId,
        context: toSave,
        expectedRevision: revisionRef.current,
        validationStatus,
        signal: controller.signal,
      });

      // A superseded save must never report over a newer one.
      if (sequence < appliedSequenceRef.current) return result.ok;
      appliedSequenceRef.current = sequence;

      if (result.ok) {
        revisionRef.current = result.revision;
        savedFingerprintRef.current = fingerprint;
        setState({
          status: "saved",
          lastSavedAt: new Date().toISOString(),
          message: "",
          hydrated: true,
          hydrating: false,
        });
        return true;
      }

      setState({
        status: result.reason === "conflict" ? "conflict" : result.reason === "offline" ? "offline" : "failed",
        lastSavedAt: state.lastSavedAt,
        message: result.message,
        hydrated: true,
        hydrating: false,
      });
      return false;
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [projectId, validationStatus]
  );

  // ---- Debounced autosave on change --------------------------------------
  useEffect(() => {
    if (!enabled || !projectId || !hydratedRef.current) return undefined;
    const fingerprint = contextFingerprint(context);
    if (fingerprint === savedFingerprintRef.current) return undefined;

    setState((current) =>
      current.status === "saving" ? current : { ...current, status: "unsaved" }
    );

    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = setTimeout(() => {
      void performSave(latestContextRef.current);
    }, DEBOUNCE_MS);

    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [context, enabled, projectId, performSave]);

  /** Immediate save: field blur, Continue, and ATLAS-controlled navigation. */
  const flush = useCallback(async (): Promise<boolean> => {
    if (!enabled || !projectId || !hydratedRef.current) return true;
    if (timerRef.current) clearTimeout(timerRef.current);
    return performSave(latestContextRef.current);
  }, [enabled, projectId, performSave]);

  const retry = useCallback(() => {
    void performSave(latestContextRef.current);
  }, [performSave]);

  /** Discards the local draft and reloads authoritative content (conflict path). */
  const reloadLatest = useCallback(async () => {
    const result = await hydrateProjectContext(projectId);
    if (result.context) {
      revisionRef.current = result.revision;
      onHydrated(result.context);
      savedFingerprintRef.current = contextFingerprint(result.context);
      setState({
        status: "saved",
        lastSavedAt: new Date().toISOString(),
        message: "Reloaded the latest saved version.",
        hydrated: true,
        hydrating: false,
      });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId, onHydrated]);

  /** Overwrites the newer stored content with this tab's draft, after the user
   *  explicitly chooses to. */
  const keepMyDraft = useCallback(async () => {
    const latest = await hydrateProjectContext(projectId).catch(() => null);
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
      writeDraftCache(projectId, latestContextRef.current);
    };
    window.addEventListener("pagehide", handler);
    window.addEventListener("beforeunload", handler);
    return () => {
      window.removeEventListener("pagehide", handler);
      window.removeEventListener("beforeunload", handler);
    };
  }, [enabled, projectId]);

  return { ...state, flush, retry, reloadLatest, keepMyDraft };
}
