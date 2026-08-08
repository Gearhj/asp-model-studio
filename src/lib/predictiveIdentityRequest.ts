export type PredictiveIdentityRequestGuard = {
  signal: AbortSignal;
  generation: number;
  currentGeneration: () => number;
};

export type PredictiveIdentityRequestResult =
  | "completed"
  | "cancelled"
  | "failed";

export function predictiveIdentityRequestIsCurrent(
  guard: PredictiveIdentityRequestGuard,
): boolean {
  return !guard.signal.aborted
    && guard.generation === guard.currentGeneration();
}

/**
 * Consume a route-hydration request so cleanup cancellation can never become
 * an unhandled rejection. Only an error from the still-current request is
 * published; superseded generations are deliberately silent.
 */
export async function settlePredictiveIdentityRequest(
  request: () => Promise<void>,
  guard: PredictiveIdentityRequestGuard,
  publishActiveError: (error: unknown) => void,
): Promise<PredictiveIdentityRequestResult> {
  try {
    await request();
    return predictiveIdentityRequestIsCurrent(guard)
      ? "completed"
      : "cancelled";
  } catch (error) {
    if (!predictiveIdentityRequestIsCurrent(guard)) {
      return "cancelled";
    }
    publishActiveError(error);
    return "failed";
  }
}
