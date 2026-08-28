import { useCallback, useEffect, useState } from "react";
import {
  hydrateForecastContract,
  putForecastContract,
  type ForecastContractEnvelope,
} from "./forecastContractPersistence";
import type { ForecastContract } from "./workflowState";

export type ForecastContractLoadStatus = "loading" | "ready" | "saving" | "error";

export type ForecastContractState = ForecastContractEnvelope & {
  status: ForecastContractLoadStatus;
  error: string | null;
  refresh: () => Promise<void>;
  register: (contract: ForecastContract) => Promise<ForecastContract>;
};

const emptyEnvelope: ForecastContractEnvelope = { contract: null, history: [], coverage: null, compatibilityDraft: null };

export function useForecastContract(projectId: string): ForecastContractState {
  const [envelope, setEnvelope] = useState<ForecastContractEnvelope>(emptyEnvelope);
  const [status, setStatus] = useState<ForecastContractLoadStatus>("loading");
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (signal?: AbortSignal) => {
    if (!projectId) {
      setEnvelope(emptyEnvelope);
      setStatus("ready");
      setError(null);
      return;
    }
    setStatus("loading");
    setError(null);
    try {
      const next = await hydrateForecastContract(projectId, signal);
      if (signal?.aborted) return;
      setEnvelope(next);
      setStatus("ready");
    } catch (caught) {
      if (signal?.aborted) return;
      setStatus("error");
      setError(caught instanceof Error ? caught.message : "The forecast contract could not be loaded from the backend.");
    }
  }, [projectId]);

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load]);

  const refresh = useCallback(async () => load(), [load]);

  const register = useCallback(async (draft: ForecastContract) => {
    if (status === "loading" || status === "error") {
      throw new Error("The backend forecast-contract authority is not available.");
    }
    setStatus("saving");
    setError(null);
    try {
      const next = await putForecastContract(projectId, envelope.contract?.version ?? 0, draft);
      setEnvelope(next);
      setStatus("ready");
      return next.contract!;
    } catch (caught) {
      const message = caught instanceof Error ? caught.message : "The forecast contract could not be registered.";
      setStatus("ready");
      setError(message);
      throw caught;
    }
  }, [envelope.contract?.version, projectId, status]);

  return { ...envelope, status, error, refresh, register };
}
