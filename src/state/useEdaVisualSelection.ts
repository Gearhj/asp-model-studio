import { create } from "zustand";

export type EdaSelectionSource =
  | "distribution"
  | "quantile"
  | "correlation"
  | "vif"
  | "pairwise"
  | "relationship3d"
  | "keyboard"
  | "input";

export type EdaNumericRange = {
  feature: string;
  min: number;
  max: number;
  source: EdaSelectionSource;
};

export type EdaQuantileSelection = {
  feature: string;
  label: string;
  index: number;
  min: number;
  max: number;
};

export type EdaPinnedPair = {
  a: string;
  b: string;
  correlation?: number | null;
};

export type EdaRelationshipAxes = {
  x: string | null;
  y: string | null;
  z: string | null;
};

export type EdaRelationshipMode = "2d" | "density" | "3d";

export type EdaVisualHover =
  | { kind: "variable"; variable: string; source: EdaSelectionSource }
  | { kind: "pair"; pair: EdaPinnedPair; source: EdaSelectionSource }
  | { kind: "range"; range: EdaNumericRange; source: EdaSelectionSource }
  | null;

type EdaVisualSelectionState = {
  scopeKey: string | null;
  selectedVariable: string | null;
  selectedRange: EdaNumericRange | null;
  selectedQuantile: EdaQuantileSelection | null;
  pinnedPair: EdaPinnedPair | null;
  vifVariable: string | null;
  relationshipAxes: EdaRelationshipAxes;
  relationshipMode: EdaRelationshipMode;
  hover: EdaVisualHover;
  setScope: (scopeKey: string) => void;
  setSelectedVariable: (variable: string | null, source?: EdaSelectionSource) => void;
  setSelectedRange: (range: EdaNumericRange | null) => void;
  setSelectedQuantile: (quantile: EdaQuantileSelection | null) => void;
  pinPair: (pair: EdaPinnedPair | null) => void;
  setVifVariable: (variable: string | null) => void;
  setRelationshipAxes: (axes: Partial<EdaRelationshipAxes>) => void;
  setRelationshipMode: (mode: EdaRelationshipMode) => void;
  setHover: (hover: EdaVisualHover) => void;
  /** Clears transient and pinned analysis state while preserving the active
   * variable so switching EDA tabs does not unexpectedly change context. */
  clearSelection: () => void;
  reset: () => void;
};

const EMPTY_SELECTION = {
  selectedVariable: null,
  selectedRange: null,
  selectedQuantile: null,
  pinnedPair: null,
  vifVariable: null,
  relationshipAxes: { x: null, y: null, z: null },
  relationshipMode: "2d" as EdaRelationshipMode,
  hover: null,
} as const;

export const useEdaVisualSelection = create<EdaVisualSelectionState>((set) => ({
  scopeKey: null,
  ...EMPTY_SELECTION,

  setScope: (scopeKey) =>
    set((state) =>
      state.scopeKey === scopeKey
        ? state
        : {
            scopeKey,
            ...EMPTY_SELECTION,
          },
    ),

  setSelectedVariable: (selectedVariable, source = "input") =>
    set((state) => {
      if (selectedVariable === state.selectedVariable) return { selectedVariable };
      const preserveLinkedRange =
        source === "correlation" ||
        source === "vif" ||
        source === "pairwise" ||
        source === "relationship3d";
      return {
        selectedVariable,
        selectedRange: preserveLinkedRange ? state.selectedRange : null,
        selectedQuantile: preserveLinkedRange ? state.selectedQuantile : null,
        hover: null,
      };
    }),

  setSelectedRange: (selectedRange) =>
    set({
      selectedRange,
      selectedQuantile: null,
    }),

  setSelectedQuantile: (selectedQuantile) =>
    set({
      selectedQuantile,
      selectedRange: selectedQuantile
        ? {
            feature: selectedQuantile.feature,
            min: Math.min(selectedQuantile.min, selectedQuantile.max),
            max: Math.max(selectedQuantile.min, selectedQuantile.max),
            source: "quantile",
          }
        : null,
    }),

  pinPair: (pinnedPair) =>
    set((state) => ({
      pinnedPair,
      relationshipAxes: pinnedPair
        ? {
            x: pinnedPair.a,
            y: pinnedPair.b,
            z:
              state.relationshipAxes.z === pinnedPair.a ||
              state.relationshipAxes.z === pinnedPair.b
                ? null
                : state.relationshipAxes.z,
          }
        : state.relationshipAxes,
      hover: null,
    })),

  setVifVariable: (vifVariable) =>
    set((state) => ({
      vifVariable,
      selectedVariable: vifVariable,
      relationshipAxes: {
        x: vifVariable,
        y: state.relationshipAxes.y === vifVariable ? null : state.relationshipAxes.y,
        z: state.relationshipAxes.z === vifVariable ? null : state.relationshipAxes.z,
      },
      hover: null,
    })),

  setRelationshipAxes: (axes) =>
    set((state) => {
      const relationshipAxes = { ...state.relationshipAxes, ...axes };
      return {
        relationshipAxes,
        selectedVariable:
          axes.x !== undefined ? axes.x : state.selectedVariable,
        hover: null,
      };
    }),

  setRelationshipMode: (relationshipMode) => set({ relationshipMode }),

  setHover: (hover) => set({ hover }),

  clearSelection: () =>
    set((state) => ({
      selectedVariable: state.selectedVariable,
      selectedRange: null,
      selectedQuantile: null,
      pinnedPair: null,
      vifVariable: null,
      relationshipAxes: { x: null, y: null, z: null },
      relationshipMode: "2d",
      hover: null,
    })),

  reset: () =>
    set({
      scopeKey: null,
      ...EMPTY_SELECTION,
    }),
}));
