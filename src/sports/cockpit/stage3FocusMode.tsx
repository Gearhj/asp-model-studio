import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

const STAGE3_FOCUS_MODE_PREFIX = "asp-stage3-focus-mode:";

function storageKey(projectId: string) {
  return `${STAGE3_FOCUS_MODE_PREFIX}${projectId}`;
}

function readPreference(projectId: string): boolean {
  if (!projectId || typeof globalThis.localStorage === "undefined") return true;
  try {
    const stored = globalThis.localStorage.getItem(storageKey(projectId));
    return stored === null ? true : stored !== "false";
  } catch {
    return true;
  }
}

/**
 * Project-scoped preference for the Stage 3 analytical workspace. The global sidebar preference is
 * deliberately separate: Focus Mode temporarily compacts the application shell without changing
 * `asp-sidebar-mode`, so leaving Stage 3 restores the user's ordinary navigation layout.
 */
export function useProjectStage3FocusPreference(projectId: string) {
  const [state, setState] = useState(() => ({ projectId, enabled: readPreference(projectId) }));
  const enabled = state.projectId === projectId ? state.enabled : readPreference(projectId);

  useEffect(() => {
    setState({ projectId, enabled: readPreference(projectId) });
  }, [projectId]);

  const setEnabled = useCallback((next: boolean) => {
    setState({ projectId, enabled: next });
    if (!projectId || typeof globalThis.localStorage === "undefined") return;
    try {
      globalThis.localStorage.setItem(storageKey(projectId), String(next));
    } catch {
      // Focus Mode is a presentation preference. A storage failure must not block the workspace.
    }
  }, [projectId]);

  const toggle = useCallback(() => setEnabled(!enabled), [enabled, setEnabled]);
  return { enabled, setEnabled, toggle };
}

type Stage3FocusModeContextValue = {
  projectId: string;
  stage3SurfaceActive: boolean;
  focusModeEnabled: boolean;
  focusModeActive: boolean;
  setFocusModeEnabled: (next: boolean) => void;
  toggleFocusMode: () => void;
};

const DEFAULT_CONTEXT: Stage3FocusModeContextValue = {
  projectId: "",
  stage3SurfaceActive: false,
  focusModeEnabled: false,
  focusModeActive: false,
  setFocusModeEnabled: () => undefined,
  toggleFocusMode: () => undefined,
};

const Stage3FocusModeContext = createContext<Stage3FocusModeContextValue>(DEFAULT_CONTEXT);

export function Stage3FocusModeProvider({
  projectId,
  stage3SurfaceActive,
  focusModeEnabled,
  setFocusModeEnabled,
  children,
}: {
  projectId: string;
  stage3SurfaceActive: boolean;
  focusModeEnabled: boolean;
  setFocusModeEnabled: (next: boolean) => void;
  children: ReactNode;
}) {
  const toggleFocusMode = useCallback(
    () => setFocusModeEnabled(!focusModeEnabled),
    [focusModeEnabled, setFocusModeEnabled],
  );
  const value = useMemo<Stage3FocusModeContextValue>(() => ({
    projectId,
    stage3SurfaceActive,
    focusModeEnabled,
    focusModeActive: stage3SurfaceActive && focusModeEnabled,
    setFocusModeEnabled,
    toggleFocusMode,
  }), [focusModeEnabled, projectId, setFocusModeEnabled, stage3SurfaceActive, toggleFocusMode]);

  return <Stage3FocusModeContext.Provider value={value}>{children}</Stage3FocusModeContext.Provider>;
}

export function useStage3FocusMode() {
  return useContext(Stage3FocusModeContext);
}
