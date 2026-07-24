// ATLAS Visual Intelligence Foundation -- reusable Visualization Specification.
//
// A VisualizationSpec is a serializable description of "what is this chart
// showing and how is it currently configured" -- it is NOT a snapshot of the
// underlying data. Saving a spec never implies the raw rows or an ephemeral
// scoring result were persisted; only the spec's own small JSON is durable.
import type { ProblemType, ScoringPartition, VisualDatasetReference } from "./types";

export type ChartType =
  | "histogram" | "density" | "scatter" | "line" | "bar"
  | "residual-vs-fitted" | "qq-plot" | "confusion-matrix" | "roc" | "pr-curve";

export type StatisticalOverlay = "mean" | "median" | "percentile" | "identity-line" | "zero-residual-line" | "reference-line";

export type VisualizationSpec = {
  visualizationId: string;
  chartType: ChartType;
  title: string;
  analyticalPurpose: string;
  datasetReference: VisualDatasetReference;
  datasetVersion?: string;
  problemType: ProblemType | null;
  target: string | null;
  modelId: string | null;
  partition: ScoringPartition | null;
  xVariable: string | null;
  yVariable: string | null;
  colorVariable: string | null;
  filters: Record<string, unknown>;
  selectedSegment: { field: string; min?: number; max?: number; categories?: string[] } | null;
  threshold: number | null;
  binning: { count: number; strategy: "equal-width" | "equal-frequency" } | null;
  statisticalOverlays: StatisticalOverlay[];
  comparisonPartitions: ScoringPartition[];
  linkedViews: string[];
  annotations: Array<{ id: string; text: string; x?: number; y?: number }>;
  samplingState: { sampled: boolean; sampleSize?: number; totalRows?: number };
  aggregationState: { method: "none" | "server-aggregate" | "duckdb-wasm" | "client-sample"; durationMs?: number };
  exportState: { lastExportedAt?: string; format?: "png" | "svg" | "csv" };
  accessibilityDescription: string;
  reducedMotionPreference: boolean;
  createdAt: string;
  updatedAt: string;
};

export const EPHEMERAL_SCORING_NOTICE =
  "This view depends on an unregistered scoring result and may not survive a refresh.";

export const REGISTER_SCORED_DATASET_ACTION_LABEL = "Register Scored Dataset";

export function newVisualizationSpec(partial: Pick<VisualizationSpec, "visualizationId" | "chartType" | "title" | "analyticalPurpose" | "datasetReference" | "problemType"> & Partial<VisualizationSpec>): VisualizationSpec {
  const now = new Date().toISOString();
  return {
    target: null,
    modelId: null,
    partition: null,
    xVariable: null,
    yVariable: null,
    colorVariable: null,
    filters: {},
    selectedSegment: null,
    threshold: null,
    binning: null,
    statisticalOverlays: [],
    comparisonPartitions: [],
    linkedViews: [],
    annotations: [],
    samplingState: { sampled: false },
    aggregationState: { method: "none" },
    exportState: {},
    accessibilityDescription: partial.title,
    reducedMotionPreference: typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches === true,
    createdAt: now,
    updatedAt: now,
    ...partial,
  };
}
