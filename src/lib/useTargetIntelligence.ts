// EDA Target Intelligence -- panel state.
//
// Two deliberately different lifecycles:
//
//   useTargetAssessment    loads automatically, because class balance IS the
//                          Target tab's headline and it resolves from the
//                          already-cached exact aggregate.
//   useTargetByPredictor   NEVER loads automatically. It is a scan, and Part G
//                          requires it to be on-demand -- the analyst selects a
//                          predictor and presses Run Analysis.
//
// Both reject stale results: a response may only update state if the identity it
// was issued for is still the identity the panel wants, so changing target,
// predictor, dataset, version, or project cannot be overwritten by an in-flight
// response for the previous selection.
import { useCallback, useEffect, useRef, useState } from "react";
import {
  buildTargetAssessmentKey,
  buildTargetByPredictorKey,
  fetchTargetAssessment,
  fetchTargetByPredictor,
  listTargetFindings,
  peekTargetAssessment,
  peekTargetByPredictor,
  type TargetAssessmentRequest,
  type TargetByPredictorRequest,
  type TargetFindingScope,
} from "./targetIntelligenceApi";
import type { TargetAssessmentResult, TargetByPredictorResult, TargetFinding } from "./targetIntelligence";

export type QueryPhase = "idle" | "queued" | "running" | "cached" | "ready" | "unsupported" | "failed";

export type TargetAssessmentState = {
  phase: QueryPhase;
  result: TargetAssessmentResult | null;
  error: string | null;
  elapsedMs: number;
};

const IDLE_ASSESSMENT: TargetAssessmentState = { phase: "idle", result: null, error: null, elapsedMs: 0 };

export function useTargetAssessment(request: TargetAssessmentRequest | null): TargetAssessmentState & { retry: () => void } {
  const [state, setState] = useState<TargetAssessmentState>(IDLE_ASSESSMENT);
  const [attempt, setAttempt] = useState(0);
  const activeKeyRef = useRef<string | null>(null);
  const key = request ? buildTargetAssessmentKey(request) : null;

  useEffect(() => {
    if (!request || !key) {
      activeKeyRef.current = null;
      setState(IDLE_ASSESSMENT);
      return undefined;
    }
    activeKeyRef.current = key;

    const cached = peekTargetAssessment(request);
    if (cached) {
      setState({ phase: cached.supported ? "cached" : "unsupported", result: cached, error: null, elapsedMs: 0 });
      return undefined;
    }

    // Deliberately no AbortController.
    //
    // `fetchTargetAssessment` de-duplicates by identity, so several callers can
    // share ONE in-flight promise. Aborting on effect cleanup rejected that
    // shared promise for every joiner -- and under StrictMode the immediate
    // re-run joins the promise its own cleanup just aborted, sees an AbortError,
    // correctly ignores it as "not my result", and then waits forever. The panel
    // sat in "resolving" and never reached the governed state.
    //
    // Staleness is already handled correctly by `activeKeyRef`: a response for a
    // superseded identity is ignored on arrival. Letting the request finish is
    // also strictly better, because its result populates the immutable cache.
    const startedAt = performance.now();
    let settled = false;

    setState({ phase: "queued", result: null, error: null, elapsedMs: 0 });
    const runningTimer = window.setTimeout(() => {
      if (!settled && activeKeyRef.current === key) {
        setState((current) => (current.phase === "queued" ? { ...current, phase: "running" } : current));
      }
    }, 150);
    const elapsedTimer = window.setInterval(() => {
      if (!settled && activeKeyRef.current === key) {
        setState((current) =>
          current.phase === "running" || current.phase === "queued"
            ? { ...current, elapsedMs: performance.now() - startedAt }
            : current
        );
      }
    }, 250);

    fetchTargetAssessment(request)
      .then((result) => {
        settled = true;
        if (activeKeyRef.current !== key) return;
        setState({
          phase: result.supported ? (result.cached ? "cached" : "ready") : "unsupported",
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
          error: error instanceof Error ? error.message : "The target assessment could not be calculated.",
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
    };
    // `key` is the complete identity of the request.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, attempt]);

  const retry = useCallback(() => setAttempt((value) => value + 1), []);
  return { ...state, retry };
}

export type TargetByPredictorState = {
  phase: QueryPhase;
  result: TargetByPredictorResult | null;
  error: string | null;
  elapsedMs: number;
  /** The identity the current result belongs to, so a changed selection can
   *  visibly invalidate it rather than showing the previous predictor's chart. */
  resultKey: string | null;
};

const IDLE_PREDICTOR: TargetByPredictorState = {
  phase: "idle",
  result: null,
  error: null,
  elapsedMs: 0,
  resultKey: null,
};

export function useTargetByPredictor(): TargetByPredictorState & {
  run: (request: TargetByPredictorRequest) => void;
  reset: () => void;
} {
  const [state, setState] = useState<TargetByPredictorState>(IDLE_PREDICTOR);
  const activeKeyRef = useRef<string | null>(null);

  // No AbortController here either -- see the note in `useTargetAssessment`.
  // The shared deduped promise must not be cancelled on behalf of one caller;
  // `activeKeyRef` is what rejects a superseded result.
  useEffect(
    () => () => {
      activeKeyRef.current = null;
    },
    []
  );

  const reset = useCallback(() => {
    activeKeyRef.current = null;
    setState(IDLE_PREDICTOR);
  }, []);

  const run = useCallback((request: TargetByPredictorRequest) => {
    const key = buildTargetByPredictorKey(request);
    activeKeyRef.current = key;

    const cached = peekTargetByPredictor(request);
    if (cached) {
      setState({ phase: "cached", result: cached, error: null, elapsedMs: 0, resultKey: key });
      return;
    }

    const startedAt = performance.now();
    let settled = false;

    setState({ phase: "queued", result: null, error: null, elapsedMs: 0, resultKey: null });
    const runningTimer = window.setTimeout(() => {
      if (!settled && activeKeyRef.current === key) {
        setState((current) => (current.phase === "queued" ? { ...current, phase: "running" } : current));
      }
    }, 150);

    fetchTargetByPredictor(request)
      .then((result) => {
        settled = true;
        if (activeKeyRef.current !== key) return; // stale: a newer selection is active
        setState({
          phase: result.supported ? (result.cached ? "cached" : "ready") : "unsupported",
          result,
          error: null,
          elapsedMs: performance.now() - startedAt,
          resultKey: key,
        });
      })
      .catch((error: unknown) => {
        settled = true;
        if (activeKeyRef.current !== key) return;
        if (error instanceof DOMException && error.name === "AbortError") return;
        setState({
          phase: "failed",
          result: null,
          error: error instanceof Error ? error.message : "The target-by-predictor analysis could not be completed.",
          elapsedMs: performance.now() - startedAt,
          resultKey: null,
        });
      })
      .finally(() => window.clearTimeout(runningTimer));
  }, []);

  return { ...state, run, reset };
}

export type TargetFindingsState = {
  findings: TargetFinding[];
  legacyFindings: TargetFinding[];
  loading: boolean;
  error: string | null;
};

export function useTargetFindings(scope: TargetFindingScope | null): TargetFindingsState & {
  reload: () => void;
  apply: (finding: TargetFinding) => void;
} {
  const [findings, setFindings] = useState<TargetFinding[]>([]);
  const [legacyFindings, setLegacyFindings] = useState<TargetFinding[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  // Scope mode and workspace fingerprint are part of the identity: switching to
  // a different uploaded dataset (or from draft to governed) is a different
  // query, so the previous dataset's findings are dropped rather than lingering.
  const key = scope
    ? [
        scope.projectId,
        scope.scopeMode ?? "",
        scope.datasetId ?? "",
        scope.versionId ?? "",
        scope.workspaceFingerprint ?? "",
        scope.target ?? "",
      ].join("|")
    : null;
  const activeKeyRef = useRef<string | null>(null);

  useEffect(() => {
    if (!scope || !key) {
      activeKeyRef.current = null;
      setFindings([]);
      setLegacyFindings([]);
      return undefined;
    }
    activeKeyRef.current = key;
    const controller = new AbortController();
    // Clear immediately: a scope change must never leave the previous scope's
    // findings on screen while the new query is in flight.
    setFindings([]);
    setLegacyFindings([]);
    setLoading(true);
    setError(null);
    listTargetFindings(scope, controller.signal)
      .then((listing) => {
        if (activeKeyRef.current !== key) return;
        setFindings(listing.findings);
        setLegacyFindings(listing.legacyFindings);
      })
      .catch((cause: unknown) => {
        if (activeKeyRef.current !== key) return;
        if (cause instanceof DOMException && cause.name === "AbortError") return;
        setError(cause instanceof Error ? cause.message : "Target findings could not be loaded.");
      })
      .finally(() => {
        if (activeKeyRef.current === key) setLoading(false);
      });
    return () => controller.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, attempt]);

  const reload = useCallback(() => setAttempt((value) => value + 1), []);
  const apply = useCallback((finding: TargetFinding) => {
    setFindings((current) => {
      const index = current.findIndex((item) => item.targetFindingId === finding.targetFindingId);
      if (index === -1) return [finding, ...current];
      const next = [...current];
      next[index] = finding;
      return next;
    });
  }, []);

  return { findings, legacyFindings, loading, error, reload, apply };
}
