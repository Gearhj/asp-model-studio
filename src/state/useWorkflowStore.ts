import { create } from "zustand";
import { persist, createJSONStorage } from "zustand/middleware";

type StepId =
  | "dashboard"
  | "step00"
  | "step01"
  | "step01b"
  | "step02"
  | "step03"
  | "step04"
  | "step05"
  | "step06"
  | "step07"
  | "step08"
  | "step09"
  | "step10"
  | "step11";

type StepStatus = "pending" | "in_progress" | "completed";

type WorkflowState = {
  hasDataset: boolean;

  steps: Record<StepId, StepStatus>;

  order: StepId[];
  paths: Record<StepId, string>;

  setHasDataset: (v: boolean) => void;
  setStepStatus: (id: StepId, s: StepStatus) => void;
  markComplete: (id: StepId) => void;

  // NEW: what your UI was calling
  markCompleteAndNext: (id: StepId) => string;

  getNextStepPath: (from: StepId) => string;

  reset: () => void;
};

const initialSteps: Record<StepId, StepStatus> = {
  dashboard: "pending",
  step00: "pending",
  step01: "pending",
  step01b: "pending",
  step02: "pending",
  step03: "pending",
  step04: "pending",
  step05: "pending",
  step06: "pending",
  step07: "pending",
  step08: "pending",
  step09: "pending",
  step10: "pending",
  step11: "pending",
};

const workflowOrder: StepId[] = [
  "dashboard",
  "step00", // Project Context
  "step01", // Data Acquisition
  "step01b", // Credit Bureau Data Review
  "step02", // EDA
  "step03", // Outliers
  "step04", // Missing Values
  "step05", // Feature Engineering
  "step06", // Balancing & Split
  "step07", // Model Training
  "step08", // Evaluation
  "step09", // Model Interpretation
  "step10", // Final Scoring
  "step11", // Model Development Document
];

const workflowPaths: Record<StepId, string> = {
  dashboard: "/dashboard",
  step00: "/step00",
  step01: "/step01",
  step01b: "/step01b",
  step02: "/step02",
  step03: "/step03",
  step04: "/step04",
  step05: "/step05",
  step06: "/step06",
  step07: "/step07",
  step08: "/step08",
  step09: "/step09",
  step10: "/step10",
  step11: "/step11",
};

export const useWorkflowStore = create<WorkflowState>()(
  persist(
    (set, get) => ({
      hasDataset: false,

      steps: { ...initialSteps },

      order: workflowOrder,

      paths: workflowPaths,

      setHasDataset: (v) => set({ hasDataset: v }),

      setStepStatus: (id, s) =>
        set((state) => ({ steps: { ...state.steps, [id]: s } })),

      markComplete: (id) =>
        set((state) => ({ steps: { ...state.steps, [id]: "completed" } })),

      // Restores old expected behavior from your UI
      markCompleteAndNext: (id) => {
        const { markComplete, getNextStepPath } = get();
        markComplete(id);
        return getNextStepPath(id);
      },

      getNextStepPath: (from) => {
        const { order, paths } = get();
        const idx = order.indexOf(from);
        const nextId =
          idx >= 0 && idx < order.length - 1 ? order[idx + 1] : "dashboard";
        return paths[nextId];
      },

      reset: () =>
        set({
          hasDataset: false,
          steps: { ...initialSteps },
        }),
    }),
    {
      name: "ds-workflow-store",
      storage: createJSONStorage(() => sessionStorage),
      version: 2,
      migrate: (persisted: any) => ({
        ...persisted,
        steps: { ...initialSteps, ...(persisted?.steps ?? {}) },
        order: workflowOrder,
        paths: workflowPaths,
      }),
    }
  )
);
