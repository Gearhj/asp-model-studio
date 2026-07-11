import { create } from "zustand";
import { persist, createJSONStorage } from "zustand/middleware";
import {
  getWorkflowDefinition,
  getWorkflowForProjectType,
  type ProjectType,
  type WorkflowStep,
} from "../config/workflows";
import { upsertProjectSnapshot } from "../lib/localProjects";
import { restoreProjectSnapshotArtifacts } from "../lib/projectPersistence";

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
  | "step11"
  | "step12"
  | "step13";

type StepStatus = "pending" | "in_progress" | "completed";
type ProjectToolState = {
  experimentsEnabled: boolean;
  decisionJournalEnabled: boolean;
  governanceEnabled: boolean;
  notebookExportEnabled: boolean;
};

export type WorkflowProjectSnapshot = {
  projectId: string;
  modelId: string;
  projectName: string;
  projectType: ProjectType;
  workflowId: string;
  workflowSteps: WorkflowStep[];
  currentStepId: string;
  hasDataset?: boolean;
  projectTools?: ProjectToolState;
  persistedLocalState?: unknown;
  restoreWarnings?: string[];
};

type WorkflowState = {
  hasDataset: boolean;
  projectId: string;
  modelId: string;
  projectName: string;
  projectType: ProjectType;
  workflowId: string;
  workflowSteps: WorkflowStep[];
  currentStepId: string;
  restoreWarnings: string[];
  projectTools: ProjectToolState;

  steps: Record<StepId, StepStatus>;

  order: StepId[];
  paths: Record<StepId, string>;

  setHasDataset: (v: boolean) => void;
  setModelId: (modelId: string) => void;
  setProjectName: (name: string) => void;
  setProjectType: (projectType: ProjectType) => void;
  startProjectFromWorkflow: (params: { modelId?: string; projectName?: string; projectType: ProjectType; workflowId?: string; workflowSteps?: WorkflowStep[] }) => void;
  loadProjectSnapshot: (snapshot: WorkflowProjectSnapshot) => void;
  setCurrentStepId: (id: string) => void;
  setWorkflowStepStatus: (id: string, status: WorkflowStep["status"]) => void;
  setStepStatus: (id: StepId, s: StepStatus) => void;
  markComplete: (id: StepId) => void;
  markWorkflowStepComplete: (id: string) => void;
  normalizeWorkflowOrder: (workflowId?: string) => void;

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
  step12: "pending",
  step13: "pending",
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
  "step11", // Documentation Review
  "step12", // Model Implementation
  "step13", // Model Monitoring
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
  step12: "/step12",
  step13: "/step13",
};

const defaultWorkflow = getWorkflowDefinition("predictive-modeling");

const defaultProjectTools: ProjectToolState = {
  experimentsEnabled: true,
  decisionJournalEnabled: true,
  governanceEnabled: true,
  notebookExportEnabled: true,
};

function workflowStepsWithStatus(workflowSteps: WorkflowStep[], steps: Partial<Record<StepId, StepStatus>> = {}) {
  return workflowSteps.map((step) => {
    const legacyStatus = steps[step.id as StepId];
    return {
      ...step,
      status: legacyStatus === "completed" ? "complete" : step.status ?? "pending",
    };
  });
}

function mergeWorkflowStepsWithDefinition(persistedSteps: WorkflowStep[] | undefined, workflowId: string, legacySteps: Partial<Record<StepId, StepStatus>> = {}) {
  const definition = getWorkflowDefinition(workflowId);
  const persistedById = new Map((persistedSteps ?? []).map((step) => [step.id, step]));
  return definition.steps.map((step) => {
    const persisted = persistedById.get(step.id);
    const legacyStatus = legacySteps[step.id as StepId];
    return {
      ...step,
      status: persisted?.status ?? (legacyStatus === "completed" ? "complete" : step.status ?? "pending"),
    };
  });
}

function projectId() {
  return `atlas-${Date.now().toString(36)}`;
}

function snapshotFromState(state: Pick<WorkflowState, "hasDataset" | "projectId" | "modelId" | "projectName" | "projectType" | "workflowId" | "workflowSteps" | "currentStepId" | "projectTools">): WorkflowProjectSnapshot {
  return {
    hasDataset: state.hasDataset,
    projectId: state.projectId,
    modelId: state.modelId,
    projectName: state.projectName,
    projectType: state.projectType,
    workflowId: state.workflowId,
    workflowSteps: state.workflowSteps,
    currentStepId: state.currentStepId,
    projectTools: state.projectTools,
  };
}

function persistActiveProject(state: ReturnType<typeof useWorkflowStore.getState>) {
  try {
    upsertProjectSnapshot(snapshotFromState(state), "browser");
  } catch (error) {
    console.warn("ATLAS project autosave failed", error);
  }
}

export const useWorkflowStore = create<WorkflowState>()(
  persist(
    (set, get) => ({
      hasDataset: false,
      projectId: projectId(),
      modelId: "",
      projectName: "Untitled ATLAS Project",
      projectType: "predictive-modeling",
      workflowId: defaultWorkflow.id,
      workflowSteps: workflowStepsWithStatus(defaultWorkflow.steps),
      currentStepId: defaultWorkflow.steps[0]?.id ?? "step00",
      restoreWarnings: [],
      projectTools: defaultProjectTools,

      steps: { ...initialSteps },

      order: workflowOrder,

      paths: workflowPaths,

      setHasDataset: (v) => {
        set({ hasDataset: v });
        persistActiveProject(get());
      },

      setModelId: (modelId) => {
        set({ modelId });
        persistActiveProject(get());
      },

      setProjectName: (name) => {
        set({ projectName: name });
        persistActiveProject(get());
      },

      setProjectType: (projectType) =>
        {
          set((state) => {
            const workflow = getWorkflowForProjectType(projectType);
            return {
              projectType,
              workflowId: workflow.id,
              workflowSteps: workflowStepsWithStatus(workflow.steps, state.steps),
              currentStepId: workflow.steps[0]?.id ?? state.currentStepId,
            };
          });
          persistActiveProject(get());
        },

      startProjectFromWorkflow: ({ modelId, projectName, projectType, workflowId, workflowSteps }) =>
        {
          set((state) => {
            const workflow = workflowSteps
              ? { id: workflowId ?? "custom-workflow", steps: workflowSteps }
              : getWorkflowDefinition(workflowId ?? getWorkflowForProjectType(projectType).id);
            return {
              projectId: projectId(),
              modelId: modelId?.trim() ?? state.modelId,
              projectName: projectName?.trim() || "Untitled ATLAS Project",
              projectType,
              workflowId: workflow.id,
              workflowSteps: workflowStepsWithStatus(workflow.steps, state.steps),
              currentStepId: workflow.steps[0]?.id ?? "step00",
              restoreWarnings: [],
            };
          });
          persistActiveProject(get());
        },

      loadProjectSnapshot: (snapshot) =>
        {
          const restoreWarnings = restoreProjectSnapshotArtifacts(snapshot);
          set((state) => {
            const workflow = getWorkflowDefinition(snapshot.workflowId || getWorkflowForProjectType(snapshot.projectType).id);
            const workflowSteps = Array.isArray(snapshot.workflowSteps) && snapshot.workflowSteps.length
              ? mergeWorkflowStepsWithDefinition(snapshot.workflowSteps, workflow.id, state.steps)
              : workflowStepsWithStatus(workflow.steps, state.steps);
            return {
              hasDataset: Boolean(snapshot.hasDataset ?? state.hasDataset),
              projectId: snapshot.projectId || projectId(),
              modelId: snapshot.modelId ?? "",
              projectName: snapshot.projectName?.trim() || "Untitled ATLAS Project",
              projectType: snapshot.projectType ?? workflow.projectType,
              workflowId: workflow.id,
              workflowSteps,
              currentStepId: snapshot.currentStepId || workflowSteps[0]?.id || "step00",
              projectTools: { ...defaultProjectTools, ...(snapshot.projectTools ?? {}) },
              restoreWarnings,
            };
          });
          persistActiveProject(get());
        },

      setCurrentStepId: (id) => {
        set({ currentStepId: id });
        persistActiveProject(get());
      },

      setWorkflowStepStatus: (id, status) =>
        {
          set((state) => ({
            workflowSteps: state.workflowSteps.map((step) => (step.id === id ? { ...step, status } : step)),
          }));
          persistActiveProject(get());
        },

      setStepStatus: (id, s) =>
        {
          set((state) => ({
            steps: { ...state.steps, [id]: s },
            workflowSteps: state.workflowSteps.map((step) =>
              step.id === id ? { ...step, status: s === "completed" ? "complete" : s } : step
            ),
          }));
          persistActiveProject(get());
        },

      markComplete: (id) =>
        {
          set((state) => ({
            steps: { ...state.steps, [id]: "completed" },
            workflowSteps: state.workflowSteps.map((step) =>
              step.id === id ? { ...step, status: "complete" } : step
            ),
          }));
          persistActiveProject(get());
        },

      markWorkflowStepComplete: (id) =>
        {
          set((state) => ({
            workflowSteps: state.workflowSteps.map((step) =>
              step.id === id ? { ...step, status: "complete" } : step
            ),
          }));
          persistActiveProject(get());
        },

      normalizeWorkflowOrder: (workflowId) =>
        {
          let changed = false;
          set((state) => {
            const workflow = getWorkflowDefinition(workflowId || state.workflowId || getWorkflowForProjectType(state.projectType).id);
            const workflowSteps = mergeWorkflowStepsWithDefinition(state.workflowSteps, workflow.id, state.steps);
            const currentSignature = state.workflowSteps.map((step) => `${step.id}:${step.label}:${step.route}`).join("|");
            const nextSignature = workflowSteps.map((step) => `${step.id}:${step.label}:${step.route}`).join("|");
            changed = currentSignature !== nextSignature || state.workflowId !== workflow.id;
            if (!changed) return state;
            return {
              workflowId: workflow.id,
              projectType: workflow.projectType,
              workflowSteps,
              currentStepId: workflowSteps.some((step) => step.id === state.currentStepId)
                ? state.currentStepId
                : workflowSteps[0]?.id ?? state.currentStepId,
            };
          });
          if (changed) persistActiveProject(get());
        },

      // Restores old expected behavior from your UI
      markCompleteAndNext: (id) => {
        const { markComplete, getNextStepPath } = get();
        markComplete(id);
        return getNextStepPath(id);
      },

      getNextStepPath: (from) => {
        const { order, paths, workflowSteps } = get();
        const activeStep = workflowSteps.find((step) => step.id === from);
        if (activeStep) {
          const idx = workflowSteps.findIndex((step) => step.id === from);
          const next = idx >= 0 && idx < workflowSteps.length - 1 ? workflowSteps[idx + 1] : null;
          if (next) return next.route;
        }
        const idx = order.indexOf(from);
        const nextId =
          idx >= 0 && idx < order.length - 1 ? order[idx + 1] : "dashboard";
        return paths[nextId];
      },

      reset: () =>
        set({
          hasDataset: false,
          projectId: projectId(),
          modelId: "",
          projectName: "Untitled ATLAS Project",
          projectType: "predictive-modeling",
          workflowId: defaultWorkflow.id,
          workflowSteps: workflowStepsWithStatus(defaultWorkflow.steps),
          currentStepId: defaultWorkflow.steps[0]?.id ?? "step00",
          restoreWarnings: [],
          steps: { ...initialSteps },
        }),
    }),
    {
      name: "ds-workflow-store",
      storage: createJSONStorage(() => sessionStorage),
      version: 5,
      migrate: (persisted: any) => ({
        ...persisted,
        projectId: persisted?.projectId ?? projectId(),
        modelId: persisted?.modelId ?? "",
        projectName: persisted?.projectName ?? "Untitled ATLAS Project",
        projectType: persisted?.projectType ?? "predictive-modeling",
        workflowId: persisted?.workflowId ?? "predictive-modeling",
        steps: { ...initialSteps, ...(persisted?.steps ?? {}) },
        order: workflowOrder,
        paths: workflowPaths,
        workflowSteps:
          Array.isArray(persisted?.workflowSteps) && persisted.workflowSteps.length
            ? mergeWorkflowStepsWithDefinition(persisted.workflowSteps, persisted?.workflowId ?? "predictive-modeling", persisted?.steps ?? {})
            : workflowStepsWithStatus(defaultWorkflow.steps, persisted?.steps ?? {}),
        currentStepId: persisted?.currentStepId ?? "step00",
        restoreWarnings: [],
        projectTools: { ...defaultProjectTools, ...(persisted?.projectTools ?? {}) },
      }),
    }
  )
);
