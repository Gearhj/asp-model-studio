// Phase 6E.4 — durable, project-scoped autosave for the PA Modeling Cockpit.
//
// The cockpit's zustand store (feature set, outlier/missing policy + overrides, engineered features and
// their profiles, notes, saved-step decisions, the active experiment result) previously lived only in
// memory and was lost on refresh or navigation. This layer autosaves a bounded snapshot to
// localStorage under a PROJECT-SCOPED key so scientist progress survives navigation, refresh, browser
// restart, and re-login. It mirrors the existing workflow persistence authority (contract / binding /
// adoptions are already localStorage + project-scoped, per Phase 6C). Governed "saved policy" decisions
// remain separate (savedSteps / saveContract); this is the draft-preserving autosave layer.
//
// localStorage is a resilience/cache layer here, consistent with the current sports-workflow system of
// record; an authenticated backend experiment store is future work and is not introduced in this
// increment (it would touch auth/security/DB migrations, explicitly out of scope).
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { useCockpitStore } from "./cockpitApi";

export const COCKPIT_PREFIX = "asp-sports-cockpit:";
export const cockpitStorageKey = (projectId: string) => `${COCKPIT_PREFIX}${projectId}`;

// Only the durable, scientist-authored slices are persisted (not transient fetch state).
export type CockpitSnapshot = {
  version: 1;
  config: any;
  notes: Record<string, string>;
  engineeredProfiles: Record<string, any>;
  savedSteps: Record<string, boolean>;
  labSelected?: string[];
  labTuneSelected?: string[];
  labSuite?: Record<string, any>;
  lastResult?: any;
  lastSim?: any;
  activeStep?: string;
  savedAt: string;
};

export function loadCockpitSnapshot(projectId: string): CockpitSnapshot | null {
  try {
    const raw = localStorage.getItem(cockpitStorageKey(projectId));
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    return parsed && parsed.version === 1 ? (parsed as CockpitSnapshot) : null;
  } catch {
    return null;
  }
}

export function saveCockpitSnapshot(projectId: string, snapshot: Omit<CockpitSnapshot, "version" | "savedAt">): CockpitSnapshot {
  const payload: CockpitSnapshot = { version: 1, savedAt: new Date().toISOString(), ...snapshot };
  localStorage.setItem(cockpitStorageKey(projectId), JSON.stringify(payload));
  return payload;
}

function snapshotFromStore(activeStep: string): Omit<CockpitSnapshot, "version" | "savedAt"> {
  const s = useCockpitStore.getState();
  return {
    config: s.config,
    notes: s.notes,
    engineeredProfiles: s.engineeredProfiles,
    savedSteps: s.savedSteps,
    labSelected: s.labSelected,
    labTuneSelected: s.labTuneSelected,
    labSuite: s.labSuite,
    lastResult: s.lastResult,
    lastSim: s.lastSim,
    activeStep,
  };
}

export type AutosaveStatus = "idle" | "saving" | "saved" | "error";

// Hydrate the store from the project's snapshot on mount, then autosave (debounced) on any change.
// Returns a compact status for the autosave indicator plus a manual retry.
export function useCockpitPersistence(projectId: string, activeStep: string, onRestoreStep: (step: string) => void) {
  const [status, setStatus] = useState<AutosaveStatus>("idle");
  const [lastSavedAt, setLastSavedAt] = useState<string | null>(null);
  const hydratedFor = useRef<string | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const stepRef = useRef(activeStep);
  stepRef.current = activeStep;

  // Hydrate before paint so children render the restored state (no flash of defaults).
  useLayoutEffect(() => {
    if (hydratedFor.current === projectId) return;
    // Gate 6 — clear the previous project's scientific state BEFORE applying this project's snapshot, so a
    // project with no saved snapshot never inherits another project's state from the singleton store.
    useCockpitStore.getState().resetProjectScopedState();
    const snap = loadCockpitSnapshot(projectId);
    if (snap) {
      useCockpitStore.getState().hydrate({
        config: snap.config,
        notes: snap.notes ?? {},
        engineeredProfiles: snap.engineeredProfiles ?? {},
        savedSteps: snap.savedSteps ?? {},
        labSelected: snap.labSelected ?? [],
        labTuneSelected: snap.labTuneSelected ?? [],
        labSuite: snap.labSuite ?? {},
        lastResult: snap.lastResult,
        lastSim: snap.lastSim,
      });
      if (snap.activeStep) onRestoreStep(snap.activeStep);
      setLastSavedAt(snap.savedAt);
      setStatus("saved");
    }
    hydratedFor.current = projectId;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId]);

  const flush = useCallback(() => {
    try {
      const saved = saveCockpitSnapshot(projectId, snapshotFromStore(stepRef.current));
      setLastSavedAt(saved.savedAt);
      setStatus("saved");
    } catch {
      // Never discard in-memory work — surface a warning and allow retry.
      setStatus("error");
    }
  }, [projectId]);

  const schedule = useCallback(() => {
    if (hydratedFor.current !== projectId) return;
    setStatus("saving");
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(flush, 600);
  }, [projectId, flush]);

  // Persist on any store change and on step change.
  useEffect(() => {
    const unsub = useCockpitStore.subscribe(schedule);
    return () => unsub();
  }, [schedule]);

  useEffect(() => {
    if (hydratedFor.current === projectId) schedule();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeStep]);

  return { status, lastSavedAt, retry: flush };
}
