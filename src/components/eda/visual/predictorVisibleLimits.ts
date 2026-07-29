export const PREDICTOR_VISIBLE_LIMIT_BREAKPOINTS = [
  12, 24, 40, 60,
] as const;

export const DEFAULT_PREDICTOR_VISIBLE_LIMIT = 24;

type PredictorLimitStorage = {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
};

function normalizedCount(value: number) {
  if (!Number.isFinite(value)) return 0;
  return Math.max(0, Math.floor(value));
}

/**
 * Builds a strictly increasing set of selector values. The final value is the
 * exact available predictor count (bounded at 60), so capped labels can never
 * collapse into duplicate options such as Top 21 / Top 21 / Top 21.
 */
export function buildPredictorVisibleLimitOptions(
  predictorCount: number,
  maximum = 60,
) {
  const boundedCount = Math.min(
    normalizedCount(predictorCount),
    normalizedCount(maximum),
  );
  if (boundedCount === 0) return [];
  return [
    ...PREDICTOR_VISIBLE_LIMIT_BREAKPOINTS.filter(
      (value) => value < boundedCount && value <= maximum,
    ),
    boundedCount,
  ];
}

export function resolvePredictorVisibleLimit(
  requestedLimit: number | null | undefined,
  predictorCount: number,
  preferredLimit = DEFAULT_PREDICTOR_VISIBLE_LIMIT,
) {
  const options = buildPredictorVisibleLimitOptions(predictorCount);
  if (!options.length) return 0;
  const requested = Number(requestedLimit);
  const desired = Number.isFinite(requested)
    ? Math.max(1, Math.floor(requested))
    : preferredLimit;
  return options.reduce((closest, option) => {
    const optionDistance = Math.abs(option - desired);
    const closestDistance = Math.abs(closest - desired);
    return optionDistance < closestDistance ||
      (optionDistance === closestDistance && option < closest)
      ? option
      : closest;
  }, options[0]);
}

export function predictorVisibleLimitStorageKey(
  datasetVersion?: string,
  target?: string,
) {
  const context = [datasetVersion, target]
    .map((value) =>
      encodeURIComponent(String(value ?? "unavailable").trim().toLowerCase()),
    )
    .join(":");
  return `atlas-eda-predictor-visible-limit-v1:${context}`;
}

export function loadPersistedPredictorVisibleLimit(
  storage: PredictorLimitStorage | null | undefined,
  storageKey: string,
  predictorCount: number,
) {
  try {
    const raw = storage?.getItem(storageKey);
    return resolvePredictorVisibleLimit(
      raw === null || raw === undefined ? undefined : Number(raw),
      predictorCount,
    );
  } catch {
    return resolvePredictorVisibleLimit(undefined, predictorCount);
  }
}

export function persistPredictorVisibleLimit(
  storage: PredictorLimitStorage | null | undefined,
  storageKey: string,
  limit: number,
) {
  const normalized = normalizedCount(limit);
  if (!storage || normalized === 0) return false;
  try {
    storage.setItem(storageKey, String(normalized));
    return true;
  } catch {
    return false;
  }
}
