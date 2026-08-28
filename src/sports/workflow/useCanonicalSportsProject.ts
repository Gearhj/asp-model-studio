import { useEffect, useState } from "react";
import { useWorkflowStore } from "../../state/useWorkflowStore";
import { saveSportsProjectMetadata } from "../sportsConfig";
import { loadPersistedSportsProject } from "../sportsProjectPersistence";
import { sanitizeSportsAuthorityMessage } from "./sportsAuthorityErrors";

export type CanonicalSportsProjectStatus = "loading" | "ready" | "error";

/**
 * Reconcile a project-scoped route with the durable sports-project record.
 * The route ID wins; a stale browser store is replaced only by the exact
 * backend project carrying that same ID.
 */
export function useCanonicalSportsProject(
  projectId: string,
  stateProjectId: string,
) {
  const [status, setStatus] = useState<CanonicalSportsProjectStatus>("loading");
  const [error, setError] = useState("");

  useEffect(() => {
    if (!projectId) {
      setStatus("error");
      setError("No canonical sports-project ID is present in this route.");
      return;
    }
    const controller = new AbortController();
    setStatus("loading");
    setError("");
    void loadPersistedSportsProject(projectId, controller.signal)
      .then((persisted) => {
        if (controller.signal.aborted) return;
        if (persisted.snapshot.projectId !== projectId) {
          throw new Error("The backend returned a different sports-project identity.");
        }
        if (persisted.sportsMetadata) saveSportsProjectMetadata(persisted.sportsMetadata);
        useWorkflowStore.getState().loadProjectSnapshot(persisted.snapshot);
        setStatus("ready");
      })
      .catch((caught) => {
        if (controller.signal.aborted) return;
        setStatus("error");
        setError(caught instanceof Error
          ? sanitizeSportsAuthorityMessage(caught.message)
          : "The sports project could not be reconciled with backend persistence.");
      });
    return () => controller.abort();
  }, [projectId, stateProjectId]);

  return { status, error };
}
