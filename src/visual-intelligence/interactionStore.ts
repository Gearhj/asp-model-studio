// ATLAS Visual Intelligence Foundation -- linked interaction store.
//
// Holds the transient UI state that must stay linked across a prototype's
// multiple charts (active filters, selected rows/range, comparison partition,
// classification threshold, visible overlays, selected observation/band).
// Scoped by (authenticatedUserId, projectId, visualizationId) so two
// visualization instances -- or the same visualization in two different
// projects/tabs -- never share state (Phase M security requirement: two tabs
// with different projects remain isolated; project switching clears filters).
import { create } from "zustand";
import type * as echarts from "echarts/core";

export type InteractionScope = { userId: string; projectId: string; visualizationId: string };

export type InteractionState = {
  scope: InteractionScope | null;
  activeFilters: Record<string, unknown>;
  selectedRowIds: string[];
  selectedRange: { field: string; min?: number; max?: number } | null;
  comparisonPartition: "test" | "oot" | null;
  classificationThreshold: number;
  visibleOverlays: string[];
  activePartition: "train" | "test" | "oot";
  selectedObservationId: string | null;
  selectedTargetBand: number | null;
  /** Visual Intelligence Production Integration, Phase B/I: the live ECharts instance
   *  for this scope's primary chart, set via EChartsPanel's onChartReady -- lets a
   *  production wrapper (VisualAnalysisPanel) offer "Export Chart" without each
   *  prototype needing to know about export UI itself. Not persisted/serialized. */
  chartInstance: echarts.ECharts | null;

  setScope: (scope: InteractionScope) => void;
  setFilter: (key: string, value: unknown) => void;
  setSelectedRange: (range: InteractionState["selectedRange"]) => void;
  setComparisonPartition: (partition: InteractionState["comparisonPartition"]) => void;
  setClassificationThreshold: (threshold: number) => void;
  toggleOverlay: (overlayId: string) => void;
  setActivePartition: (partition: InteractionState["activePartition"]) => void;
  setSelectedObservation: (id: string | null) => void;
  setSelectedTargetBand: (band: number | null) => void;
  setChartInstance: (instance: echarts.ECharts | null) => void;
  reset: () => void;
};

const DEFAULTS = {
  activeFilters: {},
  selectedRowIds: [],
  selectedRange: null,
  comparisonPartition: null,
  classificationThreshold: 0.5,
  visibleOverlays: ["mean", "median"],
  activePartition: "train" as const,
  selectedObservationId: null,
  selectedTargetBand: null,
};

export const useInteractionStore = create<InteractionState>((set) => ({
  scope: null,
  chartInstance: null,
  ...DEFAULTS,

  setScope: (scope) =>
    set((state) => {
      // A new scope (different user/project/visualization instance) always resets
      // interaction state -- filters/thresholds/selections from a different
      // project's chart must never bleed into this one.
      const sameScope = state.scope && state.scope.userId === scope.userId && state.scope.projectId === scope.projectId && state.scope.visualizationId === scope.visualizationId;
      if (sameScope) return { scope };
      return { scope, ...DEFAULTS, chartInstance: null };
    }),
  setChartInstance: (instance) => set({ chartInstance: instance }),
  setFilter: (key, value) => set((state) => ({ activeFilters: { ...state.activeFilters, [key]: value } })),
  setSelectedRange: (range) => set({ selectedRange: range }),
  setComparisonPartition: (partition) => set({ comparisonPartition: partition }),
  setClassificationThreshold: (threshold) => set({ classificationThreshold: Math.min(1, Math.max(0, threshold)) }),
  toggleOverlay: (overlayId) =>
    set((state) => ({
      visibleOverlays: state.visibleOverlays.includes(overlayId)
        ? state.visibleOverlays.filter((id) => id !== overlayId)
        : [...state.visibleOverlays, overlayId],
    })),
  setActivePartition: (partition) => set({ activePartition: partition, selectedRange: null, selectedObservationId: null }),
  setSelectedObservation: (id) => set({ selectedObservationId: id }),
  setSelectedTargetBand: (band) => set({ selectedTargetBand: band }),
  reset: () => set((state) => ({ ...DEFAULTS, scope: state.scope })),
}));
