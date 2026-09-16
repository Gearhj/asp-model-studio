import { useCallback, useEffect, useState } from "react";
import {
  hydrateForecastContract,
  ForecastContractHttpError,
  putForecastContract,
  type ForecastContractEnvelope,
} from "./forecastContractPersistence";
import type { ForecastContract } from "./workflowState";
import { sanitizeSportsAuthorityMessage, sportsAuthorityErrorCode, type SportsAuthorityErrorCode } from "./sportsAuthorityErrors";

export type ForecastContractLoadStatus = "loading" | "ready" | "saving" | "error";

export type ForecastContractState = ForecastContractEnvelope & {
  status: ForecastContractLoadStatus;
  error: string | null;
  errorCode: SportsAuthorityErrorCode | null;
  refresh: () => Promise<void>;
  register: (contract: ForecastContract) => Promise<ForecastContract>;
};

const emptyEnvelope: ForecastContractEnvelope = { contract: null, history: [], coverage: null, compatibilityDraft: null };

export function useForecastContract(projectId: string): ForecastContractState {
  const [envelope, setEnvelope] = useState<ForecastContractEnvelope>(emptyEnvelope);
  const [status, setStatus] = useState<ForecastContractLoadStatus>("loading");
  const [error, setError] = useState<string | null>(null);
  const [errorCode, setErrorCode] = useState<SportsAuthorityErrorCode | null>(null);

  const load = useCallback(async (signal?: AbortSignal) => {
    if (!projectId) {
      setEnvelope(emptyEnvelope);
      setStatus("ready");
      setError(null);
      setErrorCode(null);
      return;
    }
    setStatus("loading");
    setError(null);
    setErrorCode(null);
    try {
      const next = await hydrateForecastContract(projectId, signal);
      if (signal?.aborted) return;
      setEnvelope(next);
      setStatus("ready");
    } catch (caught) {
      if (signal?.aborted) return;
      setStatus("error");
      setErrorCode(caught instanceof ForecastContractHttpError ? caught.code : sportsAuthorityErrorCode(undefined, null, caught));
      setError(caught instanceof Error ? sanitizeSportsAuthorityMessage(caught.message) : "The forecast contract could not be loaded from the backend.");
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
    setErrorCode(null);
    try {
      const next = await putForecastContract(projectId, envelope.contract?.version ?? 0, draft);
      setEnvelope(next);
      setStatus("ready");
      return next.contract!;
    } catch (caught) {
      const message = caught instanceof Error ? caught.message : "The forecast contract could not be registered.";
      setStatus("ready");
      setErrorCode(caught instanceof ForecastContractHttpError ? caught.code : sportsAuthorityErrorCode(undefined, null, caught));
      setError(sanitizeSportsAuthorityMessage(message));
      throw caught;
    }
  }, [envelope.contract?.version, projectId, status]);

  return { ...envelope, status, error, errorCode, refresh, register };
}
