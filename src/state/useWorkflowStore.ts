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
import { setCachedProjectId } from "../lib/activeProjectContext";
import {
  requireCanonicalDatasetIdentity,
  type CanonicalDatasetIdentity,
} from "../lib/datasetIdentity";
import {
  deriveEffectiveWorkflowView,
  type EffectiveWorkflowStep,
} from "../lib/workflowEffectiveState";
import type { AuthoritativeProjectReadyContext } from "../lib/authoritativeProjectContext";

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
  templateId?: string;
  workflowSteps: WorkflowStep[];
  currentStepId: string;
  hasDataset?: boolean;
  /** Exact, backend-verified Dataset Library binding. Never inferred from hasDataset. */
  datasetIdentity?: CanonicalDatasetIdentity | null;
  projectTools?: ProjectToolState;
  persistedLocalState?: unknown;
  restoreWarnings?: string[];
};

export type WorkflowState = {
  hasDataset: boolean;
  datasetIdentity: CanonicalDatasetIdentity | null;
  projectId: string;
  modelId: string;
  projectName: string;
  projectType: ProjectType;
  workflowId: string;
  workflowSteps: WorkflowStep[];
  currentStepId: string;
  /** Historical completion stays in workflowSteps; these fields are ephemeral backend reconciliation. */
  effectiveWorkflowSteps: EffectiveWorkflowStep[];
  effectiveCurrentStepId: string;
  historicalCompletedSteps: string[];
  effectiveCompletedSteps: string[];
  effectiveIdentityValidity: string;
  effectiveStateAuthoritative: boolean;
  restoreWarnings: string[];
  projectTools: ProjectToolState;

  steps: Record<StepId, StepStatus>;

  order: StepId[];
  paths: Record<StepId, string>;

  setHasDataset: (v: boolean) => void;
  setDatasetIdentity: (identity: CanonicalDatasetIdentity | null) => void;
  setModelId: (modelId: string) => void;
  setProjectName: (name: string) => void;
  setProjectType: (projectType: ProjectType) => void;
  startProjectFromWorkflow: (params: { modelId?: string; projectName?: string; projectType: ProjectType; workflowId?: string; workflowSteps?: WorkflowStep[] }) => void;
  loadProjectSnapshot: (snapshot: WorkflowProjectSnapshot) => void;
  /**
   * Apply one already-verified backend project/workflow/dataset context in a
   * single store update. Unlike browser snapshot loading, this never restores
   * local artifacts and never queues a browser-to-backend mirror.
   */
  applyAuthoritativeProjectContext: (context: AuthoritativeProjectReadyContext) => void;
  /** Update presentation metadata without touching verified workflow or dataset identity. */
  applyAuthoritativeProjectMetadata: (metadata: {
    projectId: string;
    projectName: string;
    modelId: string;
  }) => void;
  setCurrentStepId: (id: string) => void;
  setWorkflowStepStatus: (id: string, status: WorkflowStep["status"]) => void;
  applyAuthoritativeWorkflowState: (backendState: unknown) => void;
  invalidateEffectiveWorkflow: (identityValidity?: string) => void;
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

function normalizeLegacyStepId(stepId: string | undefined, workflowSteps: WorkflowStep[]) {
  if (stepId === "step01b") return "step01";
  if (stepId && workflowSteps.some((step) => step.id === stepId)) return stepId;
  return workflowSteps[0]?.id ?? "step00";
}

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

function normalizedDatasetIdentity(value: unknown, expectedProjectId: string) {
  try {
    const identity = requireCanonicalDatasetIdentity(
      value && typeof value === "object" ? value : null,
      "Persisted workflow dataset identity",
    );
    return identity.project_id === expectedProjectId ? identity : null;
  } catch {
    return null;
  }
}

function effectiveView(
  workflowSteps: WorkflowStep[],
  projectType: ProjectType,
  datasetIdentity: CanonicalDatasetIdentity | null,
  backendState?: unknown,
) {
  return deriveEffectiveWorkflowView({
    workflowSteps,
    projectType,
    datasetIdentity,
    backendState,
  });
}

function effectiveStateFields(view: ReturnType<typeof effectiveView>) {
  return {
    effectiveWorkflowSteps: view.effectiveWorkflowSteps,
    effectiveCurrentStepId: view.effectiveCurrentStepId,
    historicalCompletedSteps: view.historicalCompletedSteps,
    effectiveCompletedSteps: view.effectiveCompletedSteps,
    effectiveIdentityValidity: view.identityValidity,
    effectiveStateAuthoritative: view.authoritative,
  };
}

function snapshotFromState(state: Pick<WorkflowState, "hasDataset" | "datasetIdentity" | "projectId" | "modelId" | "projectName" | "projectType" | "workflowId" | "workflowSteps" | "currentStepId" | "projectTools">): WorkflowProjectSnapshot {
  return {
    hasDataset: state.hasDataset,
    datasetIdentity: state.datasetIdentity,
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
    (set, get) => {
      const initialWorkflowSteps = workflowStepsWithStatus(defaultWorkflow.steps);
      const initialEffective = effectiveView(
        initialWorkflowSteps,
        "predictive-modeling",
        null,
      );
      return ({
      hasDataset: false,
      datasetIdentity: null,
      projectId: projectId(),
      modelId: "",
      projectName: "Untitled ATLAS Project",
      projectType: "predictive-modeling",
      workflowId: defaultWorkflow.id,
      workflowSteps: initialWorkflowSteps,
      currentStepId: defaultWorkflow.steps[0]?.id ?? "step00",
      ...effectiveStateFields(initialEffective),
      restoreWarnings: [],
      projectTools: defaultProjectTools,

      steps: { ...initialSteps },

      order: workflowOrder,

      paths: workflowPaths,

      setHasDataset: (v) => {
        set((state) => ({
          hasDataset: v,
          ...(!v
            ? effectiveStateFields(effectiveView(
                state.workflowSteps,
                state.projectType,
                null,
              ))
            : {}),
        }));
        persistActiveProject(get());
      },

      setDatasetIdentity: (identity) => {
        const projectId = get().projectId;
        const canonical = identity
          ? normalizedDatasetIdentity(identity, projectId)
          : null;
        set((state) => ({
          datasetIdentity: canonical,
          ...effectiveStateFields(effectiveView(
            state.workflowSteps,
            state.projectType,
            canonical,
          )),
        }));
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
            const workflowSteps = workflowStepsWithStatus(workflow.steps, state.steps);
            return {
              projectType,
              workflowId: workflow.id,
              workflowSteps,
              currentStepId: workflow.steps[0]?.id ?? state.currentStepId,
              ...effectiveStateFields(effectiveView(workflowSteps, projectType, state.datasetIdentity)),
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
            const nextWorkflowSteps = workflowStepsWithStatus(workflow.steps, state.steps);
            return {
              projectId: projectId(),
              hasDataset: false,
              datasetIdentity: null,
              modelId: modelId?.trim() ?? state.modelId,
              projectName: projectName?.trim() || "Untitled ATLAS Project",
              projectType,
              workflowId: workflow.id,
              workflowSteps: nextWorkflowSteps,
              currentStepId: workflow.steps[0]?.id ?? "step00",
              restoreWarnings: [],
              ...effectiveStateFields(effectiveView(nextWorkflowSteps, projectType, null)),
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
            const datasetIdentity = normalizedDatasetIdentity(
              snapshot.datasetIdentity,
              snapshot.projectId,
            );
            return {
              hasDataset: Boolean(snapshot.hasDataset ?? state.hasDataset),
              projectId: snapshot.projectId || projectId(),
              datasetIdentity,
              modelId: snapshot.modelId ?? "",
              projectName: snapshot.projectName?.trim() || "Untitled ATLAS Project",
              projectType: snapshot.projectType ?? workflow.projectType,
              workflowId: workflow.id,
              workflowSteps,
              currentStepId: normalizeLegacyStepId(snapshot.currentStepId, workflowSteps),
              projectTools: { ...defaultProjectTools, ...(snapshot.projectTools ?? {}) },
              restoreWarnings,
              // Browser/imported snapshots preserve audit history only. They
              // never carry effective validity into a reopened session.
              ...effectiveStateFields(effectiveView(
                workflowSteps,
                snapshot.projectType ?? workflow.projectType,
                datasetIdentity,
              )),
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
          set((state) => {
            const workflowSteps = state.workflowSteps.map((step) => (step.id === id ? { ...step, status } : step));
            return {
              workflowSteps,
              ...(state.projectType === "predictive-modeling"
                ? {}
                : effectiveStateFields(effectiveView(workflowSteps, state.projectType, state.datasetIdentity))),
            };
          });
          persistActiveProject(get());
        },

      applyAuthoritativeProjectContext: (context) => {
        const project = context.project;
        const backendState = context.workflowState;
        const workflow = getWorkflowDefinition(project.workflowId);
        const workflowStatus = backendState?.workflowStatus ?? backendState?.workflow_status ?? {};
        const backendSteps = workflowStatus?.steps ?? {};
        const historicalCompleted = new Set<string>(
          Array.isArray(backendState?.historicalCompletedSteps)
            ? backendState.historicalCompletedSteps.map(String)
            : Array.isArray(backendState?.completedSteps)
              ? backendState.completedSteps.map(String)
              : [],
        );
        const workflowSteps: WorkflowStep[] = workflow.steps.map((step) => ({
          ...step,
          status: backendSteps[step.id] === "complete" || historicalCompleted.has(step.id)
            ? "complete"
            : backendSteps[step.id] === "skipped"
              ? "skipped"
              : backendSteps[step.id] === "in_progress"
                ? "in_progress"
                : "pending",
        }));
        const datasetIdentity = context.activeDatasetIdentity
          ? normalizedDatasetIdentity(context.activeDatasetIdentity, project.projectId)
          : null;
        const currentStepId = normalizeLegacyStepId(
          String(
            backendState?.effectiveCurrentStepId
            ?? backendState?.currentStepId
            ?? workflowSteps.find((step) => step.status !== "complete" && step.status !== "skipped")?.id
            ?? workflowSteps[0]?.id
            ?? "step00",
          ),
          workflowSteps,
        );
        const legacySteps = { ...initialSteps };
        workflowSteps.forEach((step) => {
          if (step.id in legacySteps) {
            legacySteps[step.id as StepId] = step.status === "complete" || step.status === "skipped"
              ? "completed"
              : step.status === "in_progress"
                ? "in_progress"
                : "pending";
          }
        });
        const view = effectiveView(
          workflowSteps,
          project.projectType,
          datasetIdentity,
          backendState,
        );
        set({
          hasDataset: Boolean(datasetIdentity),
          datasetIdentity,
          projectId: project.projectId,
          modelId: project.modelId,
          projectName: project.projectName,
          projectType: project.projectType,
          workflowId: project.workflowId,
          workflowSteps,
          currentStepId,
          projectTools: { ...defaultProjectTools, ...project.projectTools },
          restoreWarnings: [],
          steps: legacySteps,
          ...effectiveStateFields(view),
        });
      },

      applyAuthoritativeProjectMetadata: (metadata) => {
        if (get().projectId !== metadata.projectId) return;
        set((state) => ({
          projectName: metadata.projectName || state.projectName,
          modelId: metadata.modelId || state.modelId,
        }));
      },

      applyAuthoritativeWorkflowState: (backendState) => {
        set((state) => effectiveStateFields(effectiveView(
          state.workflowSteps,
          state.projectType,
          state.datasetIdentity,
          backendState,
        )));
      },

      invalidateEffectiveWorkflow: (identityValidity = "unverified") => {
        set((state) => {
          const retainedProjectContext = state.effectiveWorkflowSteps.find(
            (step) => step.id === "step00" && (step.status === "complete" || step.status === "skipped"),
          );
          const backendState = {
            historicalCompletedSteps: state.workflowSteps
              .filter((step) => step.status === "complete" || step.status === "skipped")
              .map((step) => step.id),
            effectiveCompletedSteps: retainedProjectContext ? [retainedProjectContext.id] : [],
            effectiveCurrentStepId: state.projectType === "predictive-modeling" ? "step01" : state.currentStepId,
            workflowStatus: {
              identityValidity,
              effectiveSteps: retainedProjectContext
                ? { [retainedProjectContext.id]: retainedProjectContext.status }
                : {},
            },
          };
          return effectiveStateFields(effectiveView(
            state.workflowSteps,
            state.projectType,
            state.datasetIdentity,
            backendState,
          ));
        });
      },

      setStepStatus: (id, s) =>
        {
          set((state) => {
            const workflowSteps: WorkflowStep[] = state.workflowSteps.map((step) =>
              step.id === id ? { ...step, status: s === "completed" ? "complete" as const : s } : step
            );
            return {
              steps: { ...state.steps, [id]: s },
              workflowSteps,
              ...(state.projectType === "predictive-modeling"
                ? {}
                : effectiveStateFields(effectiveView(workflowSteps, state.projectType, state.datasetIdentity))),
            };
          });
          persistActiveProject(get());
        },

      markComplete: (id) =>
        {
          set((state) => {
            const workflowSteps: WorkflowStep[] = state.workflowSteps.map((step) =>
              step.id === id ? { ...step, status: "complete" as const } : step
            );
            return {
              steps: { ...state.steps, [id]: "completed" },
              workflowSteps,
              ...(state.projectType === "predictive-modeling"
                ? {}
                : effectiveStateFields(effectiveView(workflowSteps, state.projectType, state.datasetIdentity))),
            };
          });
          persistActiveProject(get());
        },

      markWorkflowStepComplete: (id) =>
        {
          set((state) => {
            const workflowSteps: WorkflowStep[] = state.workflowSteps.map((step) =>
              step.id === id ? { ...step, status: "complete" as const } : step
            );
            return {
              workflowSteps,
              ...(state.projectType === "predictive-modeling"
                ? {}
                : effectiveStateFields(effectiveView(workflowSteps, state.projectType, state.datasetIdentity))),
            };
          });
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
              effectiveWorkflowSteps: workflowSteps.map((step) => ({
                ...step,
                status: state.effectiveWorkflowSteps.find((effective) => effective.id === step.id)?.status ?? "pending",
              })),
              effectiveCurrentStepId: workflowSteps.some((step) => step.id === state.effectiveCurrentStepId)
                ? state.effectiveCurrentStepId
                : workflowSteps[0]?.id ?? state.effectiveCurrentStepId,
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
        {
          const workflowSteps = workflowStepsWithStatus(defaultWorkflow.steps);
          set({
          hasDataset: false,
          datasetIdentity: null,
          projectId: projectId(),
          modelId: "",
          projectName: "Untitled ATLAS Project",
          projectType: "predictive-modeling",
          workflowId: defaultWorkflow.id,
          workflowSteps,
          currentStepId: defaultWorkflow.steps[0]?.id ?? "step00",
          restoreWarnings: [],
          steps: { ...initialSteps },
          ...effectiveStateFields(effectiveView(workflowSteps, "predictive-modeling", null)),
          });
        },
    });
    },
    {
      name: "ds-workflow-store",
      storage: createJSONStorage(() => sessionStorage),
      version: 8,
      migrate: (persisted: any) => {
        const {
          effectiveWorkflowSteps: _effectiveWorkflowSteps,
          effectiveCurrentStepId: _effectiveCurrentStepId,
          historicalCompletedSteps: _historicalCompletedSteps,
          effectiveCompletedSteps: _effectiveCompletedSteps,
          effectiveIdentityValidity: _effectiveIdentityValidity,
          effectiveStateAuthoritative: _effectiveStateAuthoritative,
          ...historical
        } = persisted ?? {};
        return ({
        ...historical,
        projectId: persisted?.projectId ?? projectId(),
        datasetIdentity: normalizedDatasetIdentity(
          persisted?.datasetIdentity,
          persisted?.projectId ?? "",
        ),
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
        currentStepId: normalizeLegacyStepId(persisted?.currentStepId, Array.isArray(persisted?.workflowSteps) && persisted.workflowSteps.length
          ? mergeWorkflowStepsWithDefinition(persisted.workflowSteps, persisted?.workflowId ?? "predictive-modeling", persisted?.steps ?? {})
          : workflowStepsWithStatus(defaultWorkflow.steps, persisted?.steps ?? {})),
        restoreWarnings: [],
        projectTools: { ...defaultProjectTools, ...(persisted?.projectTools ?? {}) },
        });
      },
      // Effective validity is backend-derived and intentionally ephemeral.
      // Session/local storage may preserve audit history, but can never grant
      // current workflow validity after a reload.
      partialize: (state) => {
        const {
          effectiveWorkflowSteps: _effectiveWorkflowSteps,
          effectiveCurrentStepId: _effectiveCurrentStepId,
          historicalCompletedSteps: _historicalCompletedSteps,
          effectiveCompletedSteps: _effectiveCompletedSteps,
          effectiveIdentityValidity: _effectiveIdentityValidity,
          effectiveStateAuthoritative: _effectiveStateAuthoritative,
          ...persisted
        } = state;
        return persisted;
      },
    }
  )
);

export function selectEffectiveWorkflowSteps(state: WorkflowState) {
  return state.projectType === "predictive-modeling"
    ? state.effectiveWorkflowSteps
    : state.workflowSteps;
}

export function selectEffectiveCurrentStepId(state: WorkflowState) {
  return state.projectType === "predictive-modeling"
    ? state.effectiveCurrentStepId
    : state.currentStepId;
}

// Keep the lightweight ambient projectId cache (src/lib/activeProjectContext.ts)
// in sync so src/lib/localDataset.ts can resolve the active project for its
// scoped sessionStorage key without importing this store module directly
// (Predictive Modeling Repair Stage 6.2 -- see activeProjectContext.ts).
setCachedProjectId(useWorkflowStore.getState().projectId);
useWorkflowStore.subscribe((state) => setCachedProjectId(state.projectId));
