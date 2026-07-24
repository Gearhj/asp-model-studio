// ATLAS Visual Intelligence Foundation -- explicit large-data policy.
//
// Row-count thresholds that decide how a visualization is allowed to touch
// data. These are deliberately conservative: ATLAS has already hit a real
// production crash from spreading a 100k+-row array into a function call
// (Predictive Modeling Stage B.7's scored-output rendering defect) -- this
// module exists specifically so no new chart repeats that mistake.
export const LARGE_DATA_THRESHOLDS = {
  /** At or below this row count, render every point directly (SVG-safe, D3 overlays cheap). */
  DIRECT_RENDER_MAX: 2_000,
  /** Above DIRECT_RENDER_MAX and at or below this, still render everything but force Canvas
   *  (ECharts renderer: "canvas") instead of SVG -- SVG DOM node count becomes the bottleneck
   *  before computation does. */
  CANVAS_RENDER_MAX: 25_000,
  /** Above CANVAS_RENDER_MAX and at or below this, pre-aggregate (histogram bins, decile
   *  summaries) client-side via a single linear scan or DuckDB-Wasm, then render only the
   *  aggregate -- never the raw points. */
  AGGREGATE_MAX: 100_000,
  /** Above this, refuse client-side handling entirely and require a server-side query or an
   *  honest unsupported state. Matches this stage's own brief ("100,000-row data where
   *  practical without creating unsafe repository artifacts"). */
  SERVER_QUERY_REQUIRED_ABOVE: 100_000,
} as const;

export type RenderStrategy = "direct-svg" | "canvas" | "aggregate" | "server-query" | "unsupported";

export function chooseRenderStrategy(rowCount: number): RenderStrategy {
  if (rowCount <= LARGE_DATA_THRESHOLDS.DIRECT_RENDER_MAX) return "direct-svg";
  if (rowCount <= LARGE_DATA_THRESHOLDS.CANVAS_RENDER_MAX) return "canvas";
  if (rowCount <= LARGE_DATA_THRESHOLDS.AGGREGATE_MAX) return "aggregate";
  return "server-query";
}

/** Linear-scan min/max -- the safe replacement for `Math.min(...array)` /
 *  `Math.max(...array)`, which throws "Maximum call stack size exceeded" past
 *  roughly 100k-500k arguments depending on the JS engine (the exact defect
 *  class this policy exists to prevent). Never spread a large array into a
 *  function call or constructor. */
export function safeMinMax(values: readonly number[]): { min: number; max: number } | null {
  if (values.length === 0) return null;
  let min = values[0];
  let max = values[0];
  for (let i = 1; i < values.length; i += 1) {
    const v = values[i];
    if (v < min) min = v;
    if (v > max) max = v;
  }
  return { min, max };
}

/** Streaming mean/variance (Welford's algorithm) -- one pass, no intermediate
 *  full-size copies (no `.map()` into a squared-deviation array before summing). */
export function streamingMeanStd(values: readonly number[]): { mean: number; std: number; n: number } {
  let n = 0;
  let mean = 0;
  let m2 = 0;
  for (const value of values) {
    n += 1;
    const delta = value - mean;
    mean += delta / n;
    const delta2 = value - mean;
    m2 += delta * delta2;
  }
  const variance = n > 1 ? m2 / (n - 1) : 0;
  return { mean, std: Math.sqrt(variance), n };
}

export function streamingMedian(values: readonly number[]): number | null {
  if (values.length === 0) return null;
  // Sorting is unavoidable for an exact median; this is still safe because it
  // never spreads the array into a call/constructor argument list -- only
  // .slice().sort() (which is O(n log n) but has no argument-count limit).
  const sorted = values.slice().sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 === 0 ? (sorted[mid - 1] + sorted[mid]) / 2 : sorted[mid];
}

export function percentile(values: readonly number[], p: number): number | null {
  if (values.length === 0) return null;
  const sorted = values.slice().sort((a, b) => a - b);
  const index = Math.min(sorted.length - 1, Math.max(0, Math.floor((p / 100) * sorted.length)));
  return sorted[index];
}

/** Reservoir sampling -- preserves selection accuracy (uniform probability per
 *  row) without needing to know the total count in advance and without
 *  holding a second full-size copy while sampling. Used only when a strategy
 *  of "client-sample" has been explicitly chosen and disclosed via
 *  VisualDataSourceMeta.sampled -- never silently. */
export function reservoirSample<T>(source: readonly T[], sampleSize: number, randomFn: () => number = Math.random): T[] {
  if (source.length <= sampleSize) return source.slice();
  const reservoir = source.slice(0, sampleSize);
  for (let i = sampleSize; i < source.length; i += 1) {
    const j = Math.floor(randomFn() * (i + 1));
    if (j < sampleSize) reservoir[j] = source[i];
  }
  return reservoir;
}
