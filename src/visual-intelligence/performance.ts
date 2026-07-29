export type EdaPerformanceEvent =
  | "initial-page-shell"
  | "first-useful-chart"
  | "full-tab-readiness"
  | "chart-update"
  | "brush-response"
  | "3d-activation"
  | "predictor-landscape-ready"
  | "interaction-response"
  | "distribution-explorer-ready";

export function recordEdaPerformance(
  name: EdaPerformanceEvent,
  startedAt: number,
  metadata: Record<string, unknown> = {},
): number {
  if (typeof window === "undefined" || typeof performance === "undefined") return 0;
  const durationMs = Math.max(0, performance.now() - startedAt);
  const markName = name.endsWith("-ready")
    ? `atlas-eda-${name}`
    : `atlas-eda-${name}-ready`;
  performance.mark(markName);
  window.dispatchEvent(
    new CustomEvent("atlas:eda-performance", {
      detail: {
        name,
        durationMs,
        ...metadata,
        recordedAt: new Date().toISOString(),
      },
    }),
  );
  return durationMs;
}
