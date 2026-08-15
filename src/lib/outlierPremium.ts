export type OutlierPreviewMethod =
  | "None"
  | "1.5 IQR capping"
  | "Winsorization 1 / 99"
  | "Percentile capping 5 / 95"
  | "Log1p"
  | "Robust scaling"
  | "Custom bounds";

export type OutlierMethodComparison = {
  method: OutlierPreviewMethod;
  applicable: boolean;
  retainedRows: number;
  changedValues: number;
  minimum: number | null;
  maximum: number | null;
  median: number | null;
  iqr: number | null;
  distortionWarning: string;
  rankOrder: "preserved" | "ties introduced" | "not applicable";
  previewValues: number[];
};

export type HistogramPair = {
  minimum: number;
  maximum: number;
  before: number[];
  after: number[];
};

export type CappingPreviewMethod = {
  method: string;
  lower_threshold: number;
  upper_threshold: number;
};

function finiteValues(values: number[]) {
  return values.filter((value) => Number.isFinite(value)).sort((a, b) => a - b);
}

function quantile(sorted: number[], probability: number) {
  if (!sorted.length) return null;
  const position = (sorted.length - 1) * probability;
  const lower = Math.floor(position);
  const upper = Math.ceil(position);
  if (lower === upper) return sorted[lower];
  return sorted[lower] + (sorted[upper] - sorted[lower]) * (position - lower);
}

function describe(values: number[]) {
  const sorted = finiteValues(values);
  const q25 = quantile(sorted, 0.25);
  const q75 = quantile(sorted, 0.75);
  return {
    minimum: sorted[0] ?? null,
    maximum: sorted.at(-1) ?? null,
    median: quantile(sorted, 0.5),
    iqr: q25 == null || q75 == null ? null : q75 - q25,
  };
}

function cap(values: number[], lower: number, upper: number) {
  return values.map((value) => Math.max(lower, Math.min(upper, value)));
}

function comparison(
  method: OutlierPreviewMethod,
  original: number[],
  transformed: number[],
  applicable: boolean,
  warning: string,
  rankOrder: OutlierMethodComparison["rankOrder"],
): OutlierMethodComparison {
  const changedValues = applicable
    ? transformed.reduce(
        (count, value, index) => count + (value !== original[index] ? 1 : 0),
        0,
      )
    : 0;
  return {
    method,
    applicable,
    retainedRows: original.length,
    changedValues,
    ...describe(applicable ? transformed : original),
    distortionWarning: warning,
    rankOrder: applicable ? rankOrder : "not applicable",
    previewValues: applicable ? transformed : original,
  };
}

export function buildOutlierMethodComparisons(
  values: number[],
  customBounds?: { lower: number | null; upper: number | null },
) {
  const original = finiteValues(values);
  if (!original.length) return [] as OutlierMethodComparison[];
  const q01 = quantile(original, 0.01) ?? original[0];
  const q05 = quantile(original, 0.05) ?? original[0];
  const q25 = quantile(original, 0.25) ?? original[0];
  const q75 = quantile(original, 0.75) ?? original.at(-1)!;
  const q95 = quantile(original, 0.95) ?? original.at(-1)!;
  const q99 = quantile(original, 0.99) ?? original.at(-1)!;
  const spread = q75 - q25;
  const iqrLower = q25 - 1.5 * spread;
  const iqrUpper = q75 + 1.5 * spread;
  const customApplicable =
    typeof customBounds?.lower === "number" &&
    Number.isFinite(customBounds.lower) &&
    typeof customBounds?.upper === "number" &&
    Number.isFinite(customBounds.upper) &&
    customBounds.lower < customBounds.upper;
  const nonnegative = original[0] >= 0;
  const median = quantile(original, 0.5) ?? 0;
  const robustSpread = spread || 1;

  return [
    comparison(
      "None",
      original,
      original,
      true,
      "No treatment; observed tail values are preserved.",
      "preserved",
    ),
    comparison(
      "1.5 IQR capping",
      original,
      cap(original, iqrLower, iqrUpper),
      true,
      "Moderate tails are capped; verify business plausibility before applying.",
      "ties introduced",
    ),
    comparison(
      "Winsorization 1 / 99",
      original,
      cap(original, q01, q99),
      true,
      "Only the rendered extreme tails change.",
      "ties introduced",
    ),
    comparison(
      "Percentile capping 5 / 95",
      original,
      cap(original, q05, q95),
      true,
      "Aggressive capping can compress meaningful credit-risk separation.",
      "ties introduced",
    ),
    comparison(
      "Log1p",
      original,
      nonnegative ? original.map((value) => Math.log1p(value)) : original,
      nonnegative,
      nonnegative
        ? "Scale changes substantially; coefficients must be interpreted on the transformed scale."
        : "Unavailable because negative ordinary values are present.",
      "preserved",
    ),
    comparison(
      "Robust scaling",
      original,
      original.map((value) => (value - median) / robustSpread),
      true,
      "Preview only. Learned scaling belongs in the training-only pipeline.",
      "preserved",
    ),
    comparison(
      "Custom bounds",
      original,
      customApplicable
        ? cap(original, customBounds!.lower!, customBounds!.upper!)
        : original,
      customApplicable,
      customApplicable
        ? "Reviewer-defined bounds require documented business rationale."
        : "Enter a valid lower and upper bound to compare.",
      "ties introduced",
    ),
  ];
}

export function buildCommonHistogramPair(
  beforeValues: number[],
  afterValues: number[],
  binCount = 24,
): HistogramPair {
  const before = finiteValues(beforeValues);
  const after = finiteValues(afterValues);
  const combined = [...before, ...after];
  const minimum = combined.length ? Math.min(...combined) : 0;
  const maximum = combined.length ? Math.max(...combined) : 1;
  const width = (maximum - minimum) / Math.max(binCount, 1) || 1;
  const bins = (values: number[]) => {
    const result = Array.from({ length: binCount }, () => 0);
    values.forEach((value) => {
      const index = Math.min(
        binCount - 1,
        Math.max(0, Math.floor((value - minimum) / width)),
      );
      result[index] += 1;
    });
    return result;
  };
  return { minimum, maximum, before: bins(before), after: bins(after) };
}

/**
 * Applies the selected backend-authoritative capping thresholds to a bounded
 * rendering sample. Full-population counts and cutoffs still come from the
 * backend; this helper only makes the visual before/after comparison faithful
 * to the selected method.
 */
export function applyOutlierPreviewTreatment(
  values: number[],
  method: CappingPreviewMethod,
) {
  const original = values.filter((value) => Number.isFinite(value));
  if (method.method === "NONE") return original;
  return original.map((value) =>
    Math.max(
      method.lower_threshold,
      Math.min(method.upper_threshold, value),
    ),
  );
}

export function outlierBurdenTone(rate: number) {
  if (rate >= 0.1) return "danger";
  if (rate >= 0.03) return "warning";
  if (rate > 0) return "info";
  return "neutral";
}
