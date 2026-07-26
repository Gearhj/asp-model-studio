// Target Distribution panel state -- loads independently of the rest of Data
// Acquisition. Nothing here waits on full quality profiling, predictor
// profiling, missingness analysis, or browser preview preparation.
import { useCallback, useEffect, useRef, useState } from "react";
import {
  buildTargetDistributionKey,
  fetchTargetDistribution,
  peekCachedTargetDistribution,
  type TargetDistributionRequest,
  type TargetDistributionResult,
} from "./targetDistributionApi";

export type TargetDistributionPhase =
  | "idle"
  | "queued"
  | "running"
  | "cached"
  | "exact"
  | "sampled"
  | "unsupported"
  | "failed";

export type TargetDistributionState = {
  phase: TargetDistributionPhase;
  result: TargetDistributionResult | null;
  error: string | null;
  elapsedMs: number;
};

const IDLE: TargetDistributionState = { phase: "idle", result: null, error: null, elapsedMs: 0 };

function phaseForResult(result: TargetDistributionResult, servedFromClientCache: boolean): TargetDistributionPhase {
  if (!result.supported) return "unsupported";
  if (servedFromClientCache || result.cached) return "cached";
  return result.resolution === "sampled" ? "sampled" : "exact";
}

/**
 * @param request identity of the aggregate, or null when no registered dataset
 *        version + target is selected yet (the panel then stays idle and the
 *        caller can fall back to a locally computed distribution).
 */
export function useTargetDistribution(request: TargetDistributionRequest | null): TargetDistributionState & {
  retry: () => void;
  calculateExact: () => void;
} {
  const [state, setState] = useState<TargetDistributionState>(IDLE);
  const [forceExact, setForceExact] = useState(false);
  const [attempt, setAttempt] = useState(0);

  // Guards every asynchronous completion: a response may only update state if the
  // identity it was issued for is still the identity the panel wants. Changing
  // project, dataset, version, or target therefore cannot be overwritten by an
  // in-flight response for the previous selection.
  const activeKeyRef = useRef<string | null>(null);

  const effectiveRequest: TargetDistributionRequest | null = request
    ? { ...request, forceExact: forceExact || request.forceExact }
    : null;
  const key = effectiveRequest ? buildTargetDistributionKey(effectiveRequest) : null;

  useEffect(() => {
    if (!effectiveRequest || !key) {
      activeKeyRef.current = null;
      setState(IDLE);
      return undefined;
    }

    activeKeyRef.current = key;

    // A previously resolved immutable aggregate paints synchronously -- no
    // spinner, no request.
    const cached = peekCachedTargetDistribution(effectiveRequest);
    if (cached) {
      setState({ phase: phaseForResult(cached, true), result: cached, error: null, elapsedMs: 0 });
      return undefined;
    }

    const controller = new AbortController();
    const startedAt = performance.now();
    let settled = false;

    setState({ phase: "queued", result: null, error: null, elapsedMs: 0 });
    // Queued becomes running once the request is actually in flight; the short
    // delay keeps a cache-fast response from flashing two states.
    const runningTimer = window.setTimeout(() => {
      if (!settled && activeKeyRef.current === key) {
        setState((current) => (current.phase === "queued" ? { ...current, phase: "running" } : current));
      }
    }, 150);

    // Unobtrusive elapsed-time text, only while the query is genuinely running.
    const elapsedTimer = window.setInterval(() => {
      if (!settled && activeKeyRef.current === key) {
        setState((current) =>
          current.phase === "running" || current.phase === "queued"
            ? { ...current, elapsedMs: performance.now() - startedAt }
            : current
        );
      }
    }, 250);

    fetchTargetDistribution(effectiveRequest, { signal: controller.signal })
      .then((result) => {
        settled = true;
        if (activeKeyRef.current !== key) return; // stale: a newer identity is active
        setState({
          phase: phaseForResult(result, false),
          result,
          error: null,
          elapsedMs: performance.now() - startedAt,
        });
      })
      .catch((error: unknown) => {
        settled = true;
        if (activeKeyRef.current !== key) return;
        if (error instanceof DOMException && error.name === "AbortError") return;
        setState({
          phase: "failed",
          result: null,
          error: error instanceof Error ? error.message : "The target distribution could not be calculated.",
          elapsedMs: performance.now() - startedAt,
        });
      })
      .finally(() => {
        window.clearTimeout(runningTimer);
        window.clearInterval(elapsedTimer);
      });

    return () => {
      settled = true;
      window.clearTimeout(runningTimer);
      window.clearInterval(elapsedTimer);
      controller.abort();
    };
    // `key` is the complete identity of the request, so it is the only dependency
    // that should retrigger a query. `attempt` forces an explicit retry.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, attempt]);

  const retry = useCallback(() => setAttempt((value) => value + 1), []);
  const calculateExact = useCallback(() => {
    setForceExact(true);
    setAttempt((value) => value + 1);
  }, []);

  return { ...state, retry, calculateExact };
}
