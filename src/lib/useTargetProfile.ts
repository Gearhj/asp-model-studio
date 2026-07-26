// Governed target-dependent profiling -- panel state.
//
// Two deliberately separate phases, because Part L requires the target and
// quality summary to be visible before every predictor's Information Value has
// been computed:
//
//   phase 1  include_iv = false  -> quality + target mapping, fast
//   phase 2  include_iv = true   -> the same plus per-predictor IV
//
// Both phases share one analytical identity. A response is applied only if the
// identity it was issued for is still the identity the page wants, so changing
// the dataset, version, target, or EVENT MAPPING cannot be overwritten by an
// in-flight response for the previous mapping.
import { useCallback, useEffect, useRef, useState } from "react";
import {
  buildTargetProfileKey,
  fetchTargetProfile,
  peekTargetProfile,
  ProfileUnavailableError,
  type FullArtifactMissingError,
  type TargetProfileRequest,
  type TargetProfileResult,
} from "./governedProfile";

export type ProfilePhase = "idle" | "quality" | "iv" | "ready" | "failed" | "artifact_missing";

export type TargetProfileState = {
  phase: ProfilePhase;
  /** Quality-only result, available before IV completes. */
  quality: TargetProfileResult | null;
  /** Full result including per-predictor IV. */
  profile: TargetProfileResult | null;
  error: string | null;
  /** Set when a legacy version has no complete artifact, so the UI can offer
   *  the documented recovery actions instead of dead-ending. */
  artifactMissing: FullArtifactMissingError | null;
  ivLoading: boolean;
  elapsedMs: number;
};

const IDLE: TargetProfileState = {
  phase: "idle",
  quality: null,
  profile: null,
  error: null,
  artifactMissing: null,
  ivLoading: false,
  elapsedMs: 0,
};

export function useTargetProfile(request: TargetProfileRequest | null): TargetProfileState & { retry: () => void } {
  const [state, setState] = useState<TargetProfileState>(IDLE);
  const [attempt, setAttempt] = useState(0);
  const activeKeyRef = useRef<string | null>(null);
  // Identity WITHOUT the includeIv flag: both phases belong to one selection.
  const key = request ? buildTargetProfileKey({ ...request, includeIv: true }) : null;

  useEffect(() => {
    if (!request || !key || !request.target) {
      activeKeyRef.current = null;
      setState(IDLE);
      return undefined;
    }
    activeKeyRef.current = key;

    const cached = peekTargetProfile({ ...request, includeIv: true });
    if (cached) {
      setState({ ...IDLE, phase: "ready", quality: cached, profile: cached });
      return undefined;
    }

    const controller = new AbortController();
    const startedAt = performance.now();
    // Any previous mapping's numbers are cleared immediately -- a stale result
    // must never linger on screen while a new mapping is being computed.
    setState({ ...IDLE, phase: "quality", ivLoading: true });

    (async () => {
      try {
        const quality = await fetchTargetProfile({ ...request, includeIv: false }, { signal: controller.signal });
        if (activeKeyRef.current !== key) return;
        setState((current) => ({ ...current, phase: "iv", quality, elapsedMs: performance.now() - startedAt }));

        const profile = await fetchTargetProfile({ ...request, includeIv: true }, { signal: controller.signal });
        if (activeKeyRef.current !== key) return;
        setState({
          phase: "ready",
          quality: profile,
          profile,
          error: null,
          artifactMissing: null,
          ivLoading: false,
          elapsedMs: performance.now() - startedAt,
        });
      } catch (error: unknown) {
        if (activeKeyRef.current !== key) return;
        if (error instanceof DOMException && error.name === "AbortError") return;
        const unavailable = error instanceof ProfileUnavailableError ? error : null;
        setState({
          phase: unavailable?.isLegacyArtifactMissing ? "artifact_missing" : "failed",
          quality: null,
          profile: null,
          // There is no browser fallback. A failure is shown as a failure.
          error: error instanceof Error ? error.message : "Target-dependent profiling failed.",
          artifactMissing: unavailable?.isLegacyArtifactMissing ? unavailable.detail : null,
          ivLoading: false,
          elapsedMs: performance.now() - startedAt,
        });
      }
    })();

    return () => {
      controller.abort();
    };
    // `key` is the complete analytical identity, including the event mapping.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, attempt]);

  const retry = useCallback(() => setAttempt((value) => value + 1), []);
  return { ...state, retry };
}
