import { useEffect, useMemo, useState } from "react";
import type { CanonicalDatasetIdentity } from "./datasetIdentity";
import {
  resolveExactPromotedModelIdentity,
  type ExactPromotedModelIdentity,
  type PromotedModelStatusMetadata,
} from "./implementationMonitoringIdentity";
import { buildFinalModelStatusQuery } from "./scoringContinuation";

const QUERY_API_BASE =
  typeof window !== "undefined"
    ? new URLSearchParams(window.location.search).get("apiBase")?.replace(/\/$/, "")
    : undefined;
const API_BASE =
  QUERY_API_BASE
  || (import.meta.env.VITE_API_BASE as string | undefined)?.replace(/\/$/, "")
  || "http://127.0.0.1:8001/api";

type State = {
  status: "idle" | "loading" | "ready" | "error";
  identity: ExactPromotedModelIdentity | null;
  error: string;
};

const IDLE: State = { status: "idle", identity: null, error: "" };

export function useExactPromotedModelIdentity(input: {
  projectId: string;
  userId: string;
  datasetIdentity: CanonicalDatasetIdentity | null;
  target: string;
}) {
  const { projectId, userId, datasetIdentity, target } = input;
  const exactScope = useMemo(() => ({
    projectId: projectId.trim(),
    userId: userId.trim(),
    datasetId: datasetIdentity?.dataset_id.trim() ?? "",
    datasetVersionId: datasetIdentity?.dataset_version_id.trim() ?? "",
    target: target.trim(),
  }), [datasetIdentity?.dataset_id, datasetIdentity?.dataset_version_id, projectId, target, userId]);
  const [state, setState] = useState<State>(IDLE);

  useEffect(() => {
    const { datasetId, datasetVersionId } = exactScope;
    if (!exactScope.projectId || !exactScope.userId || !datasetId || !datasetVersionId || !exactScope.target) {
      setState({
        status: "error",
        identity: null,
        error: "This workflow step requires the exact authenticated project, dataset version, target, and promoted model.",
      });
      return;
    }

    const controller = new AbortController();
    setState({ status: "loading", identity: null, error: "" });
    const query = buildFinalModelStatusQuery({
      projectId: exactScope.projectId,
      datasetId,
      datasetVersionId,
      target: exactScope.target,
    });
    fetch(`${API_BASE}/model/final/status?${query.toString()}`, {
      credentials: "include",
      signal: controller.signal,
    })
      .then(async (response) => {
        if (!response.ok) {
          throw new Error(`Promoted-model status failed (HTTP ${response.status}).`);
        }
        return response.json() as Promise<{
          ready?: boolean;
          metadata?: PromotedModelStatusMetadata | null;
        }>;
      })
      .then((response) => {
        if (controller.signal.aborted) return;
        const resolution = resolveExactPromotedModelIdentity(response, {
          projectId: exactScope.projectId,
          datasetId,
          datasetVersion: datasetVersionId,
          target: exactScope.target,
        });
        setState(resolution.ready
          ? { status: "ready", identity: resolution.identity, error: "" }
          : { status: "error", identity: null, error: resolution.error });
      })
      .catch((error) => {
        if (controller.signal.aborted) return;
        setState({
          status: "error",
          identity: null,
          error: error instanceof Error ? error.message : "Promoted-model status is unavailable.",
        });
      });

    return () => controller.abort();
  }, [exactScope]);

  return state;
}
