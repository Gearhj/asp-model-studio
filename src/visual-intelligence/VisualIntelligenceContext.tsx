// ATLAS Visual Intelligence Foundation -- shared context provider.
//
// Resolves the current (authenticatedUserId, projectId, problemType, target)
// once per mount using the SAME backend-truth-first resolver CopilotCard now
// uses (src/lib/taskContext.ts) -- this is the "one reusable task-context
// resolver" the Phase 0 repair introduced, reused here rather than duplicated
// a third time. Also owns project-switch/sign-out cleanup of DuckDB-Wasm
// registrations and the interaction store (Phase M security requirement).
//
// Persistent Scoring Runs, Phase G: when a `scoringRunId` is present in the
// URL query string, this resolves the base reference from that durable
// ScoringRun (via GET /api/scoring-runs/{id}) instead of live workspace
// state -- and because the id lives in the URL, not React state, a browser
// refresh reloads the exact same run rather than losing it. Falls back to
// live workspace data (previous behavior, unchanged) whenever no
// scoringRunId is present, so existing usage is unaffected.
import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { useWorkflowStore } from "../state/useWorkflowStore";
import { getCachedUserId } from "../lib/authSession";
import { resolveTaskContext } from "../lib/taskContext";
import { getScoringRun } from "../scoring-runs/scoringRunClient";
import { clearVisualDataForProject } from "./dataAccessLayer";
import { useInteractionStore } from "./interactionStore";
import type { ProblemType, VisualDatasetReference } from "./types";
import { usePredictiveIdentity } from "../components/PredictiveIdentityProvider";

export type VisualIntelligenceContextValue = {
  baseReference: VisualDatasetReference | null;
  problemType: ProblemType | null;
  target: string | null;
  loading: boolean;
  /** Set only when the active reference was resolved from a durable ScoringRun
   *  (URL-driven), not live workspace state -- lets the UI show which mode it's in. */
  scoringRunId: string | null;
  /** Switches the active reference to a specific ScoringRun (writes the URL so a
   *  refresh reloads it), or back to live workspace data when passed null. */
  selectScoringRun: (scoringRunId: string | null) => void;
};

const VisualIntelligenceContext = createContext<VisualIntelligenceContextValue>({
  baseReference: null,
  problemType: null,
  target: null,
  loading: true,
  scoringRunId: null,
  selectScoringRun: () => {},
});

export function useVisualIntelligenceContext(): VisualIntelligenceContextValue {
  return useContext(VisualIntelligenceContext);
}

export function scoringRunIdFromUrl(): string | null {
  return new URLSearchParams(window.location.search).get("scoringRunId");
}

/** Sets (or clears, when scoringRunId is null) the URL's scoringRunId param
 *  without a full navigation -- a page refresh re-reads it from the URL, so
 *  this is the mechanism that makes a selected scoring run refresh-durable. */
export function setScoringRunInUrl(scoringRunId: string | null): void {
  const url = new URL(window.location.href);
  if (scoringRunId) url.searchParams.set("scoringRunId", scoringRunId);
  else url.searchParams.delete("scoringRunId");
  window.history.replaceState(null, "", url.toString());
}

export function VisualIntelligenceProvider({ children }: { children: ReactNode }) {
  const projectId = useWorkflowStore((state) => state.projectId);
  const { readiness: identityReadiness } = usePredictiveIdentity();
  const [urlScoringRunId, setUrlScoringRunId] = useState<string | null>(() => scoringRunIdFromUrl());
  const selectScoringRun = (scoringRunId: string | null) => {
    setScoringRunInUrl(scoringRunId);
    setUrlScoringRunId(scoringRunId);
  };

  const [value, setValue] = useState<VisualIntelligenceContextValue>({
    baseReference: null, problemType: null, target: null, loading: true, scoringRunId: null, selectScoringRun,
  });
  const priorProjectId = useRef<string>("");

  // Re-read the URL whenever a sibling component calls setScoringRunInUrl (same-tab
  // navigation doesn't fire popstate, so components that change the URL also call
  // this setter directly via the returned callback below -- see VisualIntelligenceLab).
  useEffect(() => {
    const onPopState = () => setUrlScoringRunId(scoringRunIdFromUrl());
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, []);

  useEffect(() => {
    let cancelled = false;
    const userId = getCachedUserId() ?? "anonymous";

    // Project changed (or first mount): clear any DuckDB-Wasm tables and interaction
    // state left over from the previous project before resolving the new one (Phase M:
    // "Project switching clears DuckDB registrations... Stale queries from Project A
    // cannot update Project B").
    if (priorProjectId.current && priorProjectId.current !== projectId) {
      void clearVisualDataForProject(priorProjectId.current);
    }
    priorProjectId.current = projectId;
    void clearVisualDataForProject(projectId);
    useInteractionStore.getState().reset();
    setValue((current) => ({ ...current, loading: true }));

    if (urlScoringRunId) {
      getScoringRun(urlScoringRunId)
        .then((run) => {
          if (cancelled) return;
          if (run.projectId && run.projectId !== projectId) {
            // Stale/foreign scoring run for this project -- drop it from the URL and
            // fall back to live workspace data rather than silently misattributing it.
            setScoringRunInUrl(null);
            setUrlScoringRunId(null);
            return;
          }
          const reference: VisualDatasetReference = {
            authenticatedUserId: userId,
            projectId,
            sourceType: "scoring-session",
            scoringRunId: run.scoringRunId,
            partition: run.partition,
            modelId: run.modelId ?? undefined,
            problemType: run.problemType ?? undefined,
            target: run.target ?? undefined,
          };
          setValue((current) => ({ ...current, baseReference: reference, problemType: run.problemType, target: run.target, loading: false, scoringRunId: run.scoringRunId }));
        })
        .catch(() => {
          if (cancelled) return;
          setScoringRunInUrl(null);
          setUrlScoringRunId(null);
        });
      return () => {
        cancelled = true;
        void clearVisualDataForProject(projectId);
      };
    }

    const exactIdentity = identityReadiness.status === "ready"
      ? identityReadiness.identity
      : null;
    if (!exactIdentity?.dataset_id || !exactIdentity.dataset_version_id) {
      setValue((current) => ({
        ...current,
        baseReference: null,
        problemType: null,
        target: null,
        loading: false,
        scoringRunId: null,
      }));
      return () => {
        cancelled = true;
        void clearVisualDataForProject(projectId);
      };
    }
    resolveTaskContext(exactIdentity, undefined).then((task) => {
      if (cancelled) return;
      const reference: VisualDatasetReference = {
        authenticatedUserId: userId,
        projectId,
        datasetId: exactIdentity?.dataset_id,
        versionId: exactIdentity?.dataset_version_id,
        sourceType: "workspace",
        problemType: task.problemType ?? undefined,
        target: task.target ?? undefined,
      };
      setValue((current) => ({ ...current, baseReference: reference, problemType: task.problemType, target: task.target, loading: false, scoringRunId: null }));
    });

    return () => {
      cancelled = true;
      void clearVisualDataForProject(projectId);
    };
  }, [
    identityReadiness.identity?.dataset_id,
    identityReadiness.identity?.dataset_version_id,
    identityReadiness.status,
    projectId,
    urlScoringRunId,
  ]);

  return <VisualIntelligenceContext.Provider value={value}>{children}</VisualIntelligenceContext.Provider>;
}
