export type TrainingPreflightLifecycle =
  | "missing"
  | "stale"
  | "validating"
  | "ready"
  | "blocked";

export type TrainingExecutionState =
  | "idle"
  | "validating"
  | "validation_failed"
  | "start_failed"
  | "acknowledgement_required"
  | "starting"
  | "job_created";

export type TrainingPortfolioEstimate = {
  selectedModelCount: number;
  baseFits: number;
  calibrationFits: number;
  estimatedFits: number;
  estimatedRuntimeSeconds: number;
  estimatedMemoryMb: number;
  largeRun: boolean;
};

export function estimateTrainingPortfolio(input: {
  selectedModelCount: number;
  folds: number;
  tuningCandidates: number;
  calibrationRequested: boolean;
  calibrationModelCount?: number;
  workers: number;
  featureCount: number;
  largeRunThreshold?: number;
}): TrainingPortfolioEstimate {
  const selectedModelCount = Math.max(0, Math.floor(input.selectedModelCount));
  const folds = Math.max(1, Math.floor(input.folds));
  const tuningCandidates = Math.max(1, Math.floor(input.tuningCandidates));
  const workers = Math.max(1, Math.floor(input.workers));
  const featureCount = Math.max(0, Math.floor(input.featureCount));
  const baseFits = selectedModelCount * folds * tuningCandidates;
  const calibrationModelCount = Math.max(
    0,
    Math.min(
      selectedModelCount,
      Math.floor(input.calibrationModelCount ?? selectedModelCount),
    ),
  );
  const calibrationFits = input.calibrationRequested
    ? calibrationModelCount * folds
    : 0;
  const estimatedFits = baseFits + calibrationFits;
  const estimatedRuntimeSeconds = Math.max(
    5,
    Math.round((estimatedFits * 2.5) / workers),
  );
  // This is explicitly a planning estimate. The authoritative value is
  // replaced by the backend preflight when it is current.
  const estimatedMemoryMb = Math.max(
    128,
    Math.round(96 + selectedModelCount * 42 + featureCount * 2 + workers * 48),
  );

  return {
    selectedModelCount,
    baseFits,
    calibrationFits,
    estimatedFits,
    estimatedRuntimeSeconds,
    estimatedMemoryMb,
    largeRun: estimatedFits >= Math.max(1, input.largeRunThreshold ?? 160),
  };
}

export function buildTrainingPreflightSignature(
  payload: Record<string, unknown>,
) {
  return JSON.stringify({
    ...payload,
    // These fields describe the actor or a particular launch attempt, not the
    // technical contract that preflight validated.  Normalizing them keeps a
    // successful authoritative preflight current when the same payload is
    // subsequently wrapped for job creation (which adds an empty retry-parent
    // value) or when the signed-in user's display label finishes hydrating.
    user: "",
    requested_at: "",
    retry_parent_job_id: "",
    large_job_confirmed: false,
    preflight_id: "",
    preflight_state_hash: "",
    idempotency_key: "",
  });
}

export function resolveTrainingPreflightLifecycle(input: {
  hasPreflight: boolean;
  current: boolean;
  loading: boolean;
  ready: boolean;
}): TrainingPreflightLifecycle {
  if (input.loading) return "validating";
  if (!input.hasPreflight) return "missing";
  if (!input.current) return "stale";
  return input.ready ? "ready" : "blocked";
}

export function trainingActionLabel(input: {
  executionState: TrainingExecutionState;
  jobActive: boolean;
  largeRun: boolean;
  acknowledged: boolean;
  preflightReady: boolean;
}) {
  if (input.executionState === "validating") {
    return "Validating selected models...";
  }
  if (input.executionState === "validation_failed") {
    return "Retry validation";
  }
  if (input.executionState === "start_failed") {
    return "Retry governed training";
  }
  if (input.executionState === "acknowledgement_required") {
    return "Acknowledge and Start Governed Training";
  }
  if (input.executionState === "starting") {
    return "Starting governed training...";
  }
  if (input.executionState === "job_created") {
    return "Training job created";
  }
  if (input.jobActive) return "Training in progress";
  if (input.largeRun && !input.acknowledged) return "Validate Selected Models";
  return input.preflightReady
    ? "Start Governed Training"
    : "Validate & Train Selected Models";
}

export type QueuedSave<T> = {
  revision: number;
  value: T;
};

export type BoundedSaveQueue<T, R> = {
  schedule: (value: T) => number;
  flush: () => Promise<void>;
  retry: (save: QueuedSave<T>) => void;
  dispose: () => void;
  hasPending: () => boolean;
};

/**
 * Debounces idle writes and serializes active writes. At most one request is in
 * flight and at most one newer snapshot is retained, so rapid model toggles
 * cannot create overlapping full-portfolio writes.
 */
export function createBoundedSaveQueue<T, R>(input: {
  save: (save: QueuedSave<T>) => Promise<R>;
  debounceMs?: number;
  onQueued?: (save: QueuedSave<T>) => void;
  onSaving?: (save: QueuedSave<T>) => void;
  onSaved?: (save: QueuedSave<T>, result: R) => void;
  onError?: (save: QueuedSave<T>, error: unknown) => void;
}): BoundedSaveQueue<T, R> {
  let revision = 0;
  let pending: QueuedSave<T> | null = null;
  let inFlight = false;
  let disposed = false;
  let timer: ReturnType<typeof setTimeout> | null = null;
  let activeDrain: Promise<void> = Promise.resolve();
  const debounceMs = Math.max(0, input.debounceMs ?? 350);

  const clearTimer = () => {
    if (timer !== null) clearTimeout(timer);
    timer = null;
  };

  const drain = () => {
    if (disposed || inFlight || !pending) return activeDrain;
    clearTimer();
    inFlight = true;
    activeDrain = (async () => {
      while (!disposed && pending) {
        const next = pending;
        pending = null;
        input.onSaving?.(next);
        try {
          const result = await input.save(next);
          if (disposed) return;
          input.onSaved?.(next, result);
        } catch (error) {
          if (disposed) return;
          input.onError?.(next, error);
        }
      }
    })().finally(() => {
      inFlight = false;
    });
    return activeDrain;
  };

  const arm = () => {
    if (disposed || inFlight) return;
    clearTimer();
    timer = setTimeout(() => {
      timer = null;
      void drain();
    }, debounceMs);
  };

  return {
    schedule(value) {
      const save = { revision: ++revision, value };
      pending = save;
      input.onQueued?.(save);
      arm();
      return save.revision;
    },
    async flush() {
      clearTimer();
      // A save can enqueue a newer snapshot while the first request is active.
      // Keep draining until the bounded pending slot is empty.
      while (!disposed && (pending || inFlight)) {
        if (!inFlight) void drain();
        await activeDrain;
      }
    },
    retry(save) {
      if (disposed || save.revision < revision) return;
      revision = Math.max(revision, save.revision);
      pending = save;
      input.onQueued?.(save);
      arm();
    },
    dispose() {
      disposed = true;
      pending = null;
      clearTimer();
    },
    hasPending() {
      return !!pending || inFlight;
    },
  };
}
