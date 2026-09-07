import type { CandidateAttempt, CandidateGroup } from "./projectModelLabApi";

const count = (value: unknown): value is number =>
  typeof value === "number" && Number.isSafeInteger(value) && value >= 0;

export function representativeCandidateAttempt(group: CandidateGroup): CandidateAttempt | undefined {
  return group.attempts.find((attempt) =>
    attempt.attemptId === group.representativeAttemptId
    && attempt.runReceiptSha256 === group.immutableEvidenceIdentity
  ) ?? group.attempts.find((attempt) => attempt.status === "COMPLETE") ?? group.attempts[0];
}

/** Receipt-bound input counts before one-hot encoding, never a current-project assumption. */
export function candidateFeatureSummary(group: CandidateGroup): string {
  const attempt = representativeCandidateAttempt(group);
  const model = group.featureCount;
  if (!count(model)) return "Feature counts unavailable";
  const folds = attempt?.folds ?? [];
  const corrected = folds.filter((fold) => fold.preprocessing?.kind === "MLB_SEMANTIC_TREATMENT_V1");
  // The current public DTO preserves fold receipts but not the new top-level
  // physicalSourceFeatureCount. Support either representation without treating
  // the legacy sourceFeatureCount (which may include derived outputs) as physical.
  const explicitSources = [group.physicalSourceFeatureCount, attempt?.physicalSourceFeatureCount]
    .filter((value) => value !== undefined);
  const hasDerivedNames = attempt?.orderedFeatures?.some((name) => name.includes("__prior_v1__")) ?? false;
  const unavailable = `${model} model inputs · source/output breakdown unavailable`;
  if (!corrected.length && !explicitSources.length && !hasDerivedNames) {
    // A failed/partial corrected attempt may have no folds. A bare count does
    // not establish that all its model inputs are physical source features.
    return attempt?.orderedFeatures?.length === model ? `${model} source predictors` : unavailable;
  }
  if (explicitSources.some((value) => !count(value) || value > model)) return unavailable;
  if (corrected.length && corrected.length !== folds.length) return unavailable;
  const sources: number[] = explicitSources as number[];
  for (const fold of corrected) {
    const preprocessing = fold.preprocessing;
    if (!count(preprocessing.actualSourceFeatureCount)
      || preprocessing.actualModelFeatureCount !== model
      || preprocessing.actualSourceFeatureCount > model) return unavailable;
    sources.push(preprocessing.actualSourceFeatureCount);
  }
  if (!sources.length || sources.some((value) => value !== sources[0])) return unavailable;
  const source = sources[0];
  return source === model
    ? `${model} model inputs · ${source} source predictors`
    : `${model} model inputs · ${source} source predictors + ${model - source} added prior outputs`;
}
