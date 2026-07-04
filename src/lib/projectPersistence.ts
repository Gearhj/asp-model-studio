import type { WorkflowStep } from "../config/workflows";
import type { WorkflowProjectSnapshot } from "../state/useWorkflowStore";

export const PROJECT_SAVE_STATUS_EVENT = "atlas-project-save-status";

const LOCAL_PROJECTS_KEY = "atlas-local-projects";
const PROJECT_SNAPSHOT_KEY_PREFIX = "atlas-project-snapshot:";
const WORKFLOW_NODE_PREFIX = "atlas-workflow-node-state:";
const DATASET_KEY = "modeling-tool-dataset";
const TRAINING_SUMMARY_KEY = "modeling-tool-training-summary";

const SNAPSHOT_LOCAL_KEYS = [
  "modeling-tool-project-context",
  "modeling-tool-data-access-metadata",
  "modeling-tool-dataset-versions",
  "modeling-tool-bureau-metadata",
  "modeling-tool-bureau-special-value-treatments",
  "modeling-tool-missing-config",
  "modeling-tool-outlier-methods",
  "modeling-tool-user-python-code",
  "modeling-tool-user-python-code-by-step",
  "modeling-tool-mlflow-lite-experiments",
  "modeling-tool-decision-journal",
  "modeling-tool-mode",
  "modeling-tool-challenge-mode",
  "splitStrategy",
  "balanceMethod",
  "balanceRatio",
  "kFolds",
];

const SNAPSHOT_SESSION_KEYS = [DATASET_KEY, TRAINING_SUMMARY_KEY];

export type ProjectSaveStatus =
  | "saving"
  | "saved"
  | "unsaved"
  | "save_failed"
  | "restored"
  | "partial_restore";

export type ProjectSaveStatusDetail = {
  status: ProjectSaveStatus;
  message: string;
  projectId?: string;
  savedAt?: string;
  snapshotBytes?: number;
  restoreWarnings?: string[];
};

export type PersistedProjectLocalState = {
  schemaVersion: 1;
  savedAt: string;
  localStorage: Record<string, unknown>;
  sessionStorage: Record<string, unknown>;
  workflowNodeStates: Record<string, unknown>;
  datasetPreview?: {
    headers: string[];
    target: string | null;
    selected_columns: string[];
    problem_type?: "classification" | "regression";
    rowCount: number;
    previewRows: Record<string, unknown>[];
    data_access?: unknown;
    data_quality?: unknown;
    artifactStatus: "preview_restored_requires_reload" | "not_available";
  };
  missingArtifacts: string[];
  storageEstimateBytes: number;
};

export function emitProjectSaveStatus(detail: ProjectSaveStatusDetail) {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new CustomEvent<ProjectSaveStatusDetail>(PROJECT_SAVE_STATUS_EVENT, { detail }));
}

function readJson(raw: string | null) {
  if (!raw) return undefined;
  try {
    return JSON.parse(raw);
  } catch {
    return undefined;
  }
}

function stringify(value: unknown) {
  return JSON.stringify(value);
}

export function estimateBytes(value: unknown) {
  const text = typeof value === "string" ? value : stringify(value);
  if (typeof TextEncoder !== "undefined") return new TextEncoder().encode(text).length;
  return text.length * 2;
}

function downsample<T>(rows: T[] | undefined, max = 80): T[] {
  if (!Array.isArray(rows)) return [];
  if (rows.length <= max) return rows;
  const step = Math.ceil(rows.length / max);
  return rows.filter((_, index) => index % step === 0).slice(0, max);
}

function compactExperiment(experiment: any) {
  if (!experiment || typeof experiment !== "object") return experiment;
  return {
    ...experiment,
    rocData: downsample(experiment.rocData, 60),
    prData: downsample(experiment.prData, 60),
    featureImportance: Array.isArray(experiment.featureImportance) ? experiment.featureImportance.slice(0, 30) : experiment.featureImportance,
    confusionMatrix: experiment.confusionMatrix,
    metrics: experiment.metrics,
    notes: experiment.notes,
  };
}

function histogram(values: number[], bins: Array<{ label: string; min: number; max: number }>) {
  return bins.map((bin) => ({
    label: bin.label,
    value: values.filter((value) => value >= bin.min && value < bin.max).length,
  }));
}

function compactSimulationResults(results: any) {
  if (!results || typeof results !== "object") return results;
  const iterations = Array.isArray(results.powerByIteration) ? results.powerByIteration : [];
  const powerValues = iterations.map((row: any) => Number(row?.achievedPower)).filter(Number.isFinite);
  const liftValues = iterations.map((row: any) => Number(row?.estimatedLift)).filter(Number.isFinite);
  const trueLift = Number(results.inputs?.minimumDetectableLift ?? 0);
  const convergenceCurve =
    results.convergenceCurve ??
    Array.from({ length: Math.min(10, Math.max(1, powerValues.length)) }, (_, index) => {
      const end = Math.max(1, Math.round(((index + 1) / 10) * powerValues.length));
      const slice = powerValues.slice(0, end);
      return { x: end, y: slice.reduce((sum: number, value: number) => sum + value, 0) / Math.max(1, slice.length) };
    });

  return {
    ...results,
    powerByIteration: [],
    powerDistribution:
      results.powerDistribution ??
      histogram(powerValues, [
        { label: "0-20%", min: 0, max: 0.2 },
        { label: "20-40%", min: 0.2, max: 0.4 },
        { label: "40-60%", min: 0.4, max: 0.6 },
        { label: "60-80%", min: 0.6, max: 0.8 },
        { label: "80-100%", min: 0.8, max: 1.01 },
      ]),
    liftDistribution:
      results.liftDistribution ??
      histogram(liftValues, [
        { label: "Below 0", min: -Infinity, max: 0 },
        { label: "0-50%", min: 0, max: trueLift * 0.5 },
        { label: "50-100%", min: trueLift * 0.5, max: trueLift },
        { label: "100-150%", min: trueLift, max: trueLift * 1.5 },
        { label: "150%+", min: trueLift * 1.5, max: Infinity },
      ]),
    convergenceCurve: downsample(convergenceCurve, 80),
    intervalPreview: downsample(results.intervalPreview, 80),
    powerCurve: downsample(results.powerCurve, 80),
    scenarioSensitivity: downsample(results.scenarioSensitivity, 20),
    riskDrivers: downsample(results.riskDrivers, 20),
    outcomeBreakdown: results.outcomeBreakdown,
  };
}

function compactWorkflowNodeState(value: any) {
  if (!value || typeof value !== "object") return value;
  const { analysisSnapshot, ...rest } = value;
  return {
    ...rest,
    simulationResults: compactSimulationResults(rest.simulationResults),
  };
}

function compactValueForKey(key: string, value: unknown) {
  if (key === "modeling-tool-decision-journal" && Array.isArray(value)) {
    return value.slice(0, 100).map((entry) => ({
      timestamp: entry?.timestamp,
      workflowStep: entry?.workflowStep,
      actionType: entry?.actionType,
      subject: entry?.subject,
      previousValue: entry?.previousValue,
      newValue: entry?.newValue,
      followStatus: entry?.followStatus,
      userReason: entry?.userReason,
    }));
  }
  if (key === "modeling-tool-mlflow-lite-experiments" && Array.isArray(value)) {
    return value.slice(0, 60).map(compactExperiment);
  }
  if (key === "modeling-tool-dataset-versions" && Array.isArray(value)) {
    return value.slice(0, 25);
  }
  if (key === DATASET_KEY && value && typeof value === "object") {
    const dataset = value as any;
    return {
      ...dataset,
      rows: Array.isArray(dataset.rows) ? dataset.rows.slice(0, 100) : [],
      rowCount: Array.isArray(dataset.rows) ? dataset.rows.length : dataset.rowCount ?? 0,
      artifactStatus: "preview_restored_requires_reload",
    };
  }
  if (key === TRAINING_SUMMARY_KEY && value && typeof value === "object") {
    const summary = value as any;
    return {
      ...summary,
      ranked: Array.isArray(summary.ranked) ? summary.ranked.slice(0, 25) : summary.ranked,
    };
  }
  return value;
}

function readStorageKeys(storage: Storage | undefined, keys: string[]) {
  const values: Record<string, unknown> = {};
  if (!storage) return values;
  for (const key of keys) {
    const parsed = readJson(storage.getItem(key));
    if (parsed !== undefined) values[key] = compactValueForKey(key, parsed);
  }
  return values;
}

function collectWorkflowNodeStates(projectId: string) {
  const states: Record<string, unknown> = {};
  if (typeof localStorage === "undefined") return states;
  const prefix = `${WORKFLOW_NODE_PREFIX}${projectId}:`;
  for (let index = 0; index < localStorage.length; index += 1) {
    const key = localStorage.key(index) ?? "";
    if (!key.startsWith(prefix)) continue;
    const parsed = readJson(localStorage.getItem(key));
    if (parsed !== undefined) states[key.slice(prefix.length)] = compactWorkflowNodeState(parsed);
  }
  return states;
}

function datasetPreviewFromSession(sessionValues: Record<string, unknown>) {
  const dataset = sessionValues[DATASET_KEY] as any;
  if (!dataset || typeof dataset !== "object") return undefined;
  const rows = Array.isArray(dataset.rows) ? dataset.rows : [];
  return {
    headers: Array.isArray(dataset.headers) ? dataset.headers : [],
    target: dataset.target ?? null,
    selected_columns: Array.isArray(dataset.selected_columns) ? dataset.selected_columns : [],
    problem_type: dataset.problem_type,
    rowCount: Number(dataset.rowCount ?? rows.length) || rows.length,
    previewRows: rows.slice(0, 100),
    data_access: dataset.data_access,
    data_quality: dataset.data_quality,
    artifactStatus: "preview_restored_requires_reload" as const,
  };
}

export function buildPersistedProjectState(projectId: string): PersistedProjectLocalState | undefined {
  if (typeof localStorage === "undefined" || typeof sessionStorage === "undefined") return undefined;
  const localValues = readStorageKeys(localStorage, SNAPSHOT_LOCAL_KEYS);
  const sessionValues = readStorageKeys(sessionStorage, SNAPSHOT_SESSION_KEYS);
  const workflowNodeStates = collectWorkflowNodeStates(projectId);
  const datasetPreview = datasetPreviewFromSession(sessionValues);
  const missingArtifacts: string[] = [];
  if (datasetPreview?.previewRows?.length) {
    missingArtifacts.push("Raw dataset rows are not persisted in browser projects. Reload source data before retraining or scoring.");
  }
  const snapshot = {
    schemaVersion: 1 as const,
    savedAt: new Date().toISOString(),
    localStorage: localValues,
    sessionStorage: sessionValues,
    workflowNodeStates,
    datasetPreview,
    missingArtifacts,
    storageEstimateBytes: 0,
  };
  snapshot.storageEstimateBytes = estimateBytes(snapshot);
  return snapshot;
}

export function attachPersistedProjectState(snapshot: WorkflowProjectSnapshot): WorkflowProjectSnapshot {
  return {
    ...snapshot,
    persistedLocalState: buildPersistedProjectState(snapshot.projectId),
  };
}

function deleteCurrentWorkflowNodeStates(projectId: string) {
  if (typeof localStorage === "undefined") return;
  const prefix = `${WORKFLOW_NODE_PREFIX}${projectId}:`;
  const keys = Array.from({ length: localStorage.length }, (_, index) => localStorage.key(index)).filter(
    (key): key is string => Boolean(key?.startsWith(prefix))
  );
  keys.forEach((key) => localStorage.removeItem(key));
}

function restoreStorageValues(storage: Storage | undefined, keys: string[], values: Record<string, unknown>) {
  if (!storage) return;
  keys.forEach((key) => storage.removeItem(key));
  Object.entries(values).forEach(([key, value]) => {
    if (value !== undefined) storage.setItem(key, stringify(value));
  });
}

export function restoreProjectSnapshotArtifacts(snapshot: WorkflowProjectSnapshot) {
  const persisted = snapshot.persistedLocalState as PersistedProjectLocalState | undefined;
  const warnings: string[] = [];
  if (!persisted) {
    warnings.push("This project has no compact browser artifact snapshot. Workflow progress was restored, but page-level inputs may need review.");
    emitProjectSaveStatus({
      status: "partial_restore",
      projectId: snapshot.projectId,
      message: "Project progress restored. Some page artifacts were not available in the saved snapshot.",
      restoreWarnings: warnings,
    });
    return warnings;
  }

  try {
    restoreStorageValues(typeof localStorage === "undefined" ? undefined : localStorage, SNAPSHOT_LOCAL_KEYS, persisted.localStorage ?? {});
    restoreStorageValues(typeof sessionStorage === "undefined" ? undefined : sessionStorage, SNAPSHOT_SESSION_KEYS, persisted.sessionStorage ?? {});
    deleteCurrentWorkflowNodeStates(snapshot.projectId);
    if (typeof localStorage !== "undefined") {
      Object.entries(persisted.workflowNodeStates ?? {}).forEach(([stepId, value]) => {
        localStorage.setItem(`${WORKFLOW_NODE_PREFIX}${snapshot.projectId}:${stepId}`, stringify(compactWorkflowNodeState(value)));
      });
    }
    warnings.push(...(persisted.missingArtifacts ?? []));
    if (typeof window !== "undefined") {
      window.dispatchEvent(new CustomEvent("atlas-workflow-node-updated"));
      window.dispatchEvent(new CustomEvent("atlas-dataset-updated"));
      window.dispatchEvent(new CustomEvent("decision-journal-updated"));
      window.dispatchEvent(new CustomEvent("experiment-tracking-updated"));
    }
    emitProjectSaveStatus({
      status: warnings.length ? "partial_restore" : "restored",
      projectId: snapshot.projectId,
      savedAt: persisted.savedAt,
      snapshotBytes: persisted.storageEstimateBytes,
      message: warnings.length ? "Project restored with compact artifacts. Reload source data before heavy modeling tasks." : "Project restored from browser snapshot.",
      restoreWarnings: warnings,
    });
  } catch (error) {
    warnings.push(error instanceof Error ? error.message : "Unknown restore error.");
    emitProjectSaveStatus({
      status: "partial_restore",
      projectId: snapshot.projectId,
      message: "Project progress restored, but artifact restore encountered an error.",
      restoreWarnings: warnings,
    });
  }
  return warnings;
}

export function compactProjectForStorage<T extends { snapshot: WorkflowProjectSnapshot }>(project: T): T {
  const persisted = project.snapshot.persistedLocalState as PersistedProjectLocalState | undefined;
  if (!persisted) return project;
  return {
    ...project,
    snapshot: {
      ...project.snapshot,
      persistedLocalState: {
        ...persisted,
        localStorage: {
          ...persisted.localStorage,
          "modeling-tool-decision-journal": Array.isArray(persisted.localStorage["modeling-tool-decision-journal"])
            ? (persisted.localStorage["modeling-tool-decision-journal"] as unknown[]).slice(0, 50)
            : persisted.localStorage["modeling-tool-decision-journal"],
          "modeling-tool-mlflow-lite-experiments": Array.isArray(persisted.localStorage["modeling-tool-mlflow-lite-experiments"])
            ? (persisted.localStorage["modeling-tool-mlflow-lite-experiments"] as unknown[]).slice(0, 30)
            : persisted.localStorage["modeling-tool-mlflow-lite-experiments"],
        },
        sessionStorage: {
          ...persisted.sessionStorage,
          [DATASET_KEY]: compactValueForKey(DATASET_KEY, persisted.sessionStorage[DATASET_KEY]),
        },
      },
    },
  };
}

export function thinProjectForStorage<T extends { snapshot: WorkflowProjectSnapshot }>(project: T): T {
  const persisted = project.snapshot.persistedLocalState as PersistedProjectLocalState | undefined;
  const warning =
    "Detailed page artifacts were not embedded in the Recent Projects registry because browser storage quota was reached. Workflow progress is preserved; reload source data or rerun heavy artifacts if needed.";
  return {
    ...project,
    snapshot: {
      ...project.snapshot,
      persistedLocalState: persisted
        ? {
            schemaVersion: 1 as const,
            savedAt: persisted.savedAt,
            localStorage: {},
            sessionStorage: {},
            workflowNodeStates: {},
            datasetPreview: persisted.datasetPreview
              ? {
                  ...persisted.datasetPreview,
                  previewRows: [],
                  artifactStatus: "preview_restored_requires_reload" as const,
                }
              : undefined,
            missingArtifacts: Array.from(new Set([...(persisted.missingArtifacts ?? []), warning])),
            storageEstimateBytes: 0,
          }
        : undefined,
      restoreWarnings: Array.from(new Set([...(project.snapshot.restoreWarnings ?? []), warning])),
    },
  };
}

export function projectPersistenceDebug(projectId: string, workflowSteps: WorkflowStep[]) {
  const registryRaw = typeof localStorage === "undefined" ? "" : localStorage.getItem(LOCAL_PROJECTS_KEY) ?? "";
  const registry = readJson(registryRaw);
  const currentProject = Array.isArray(registry) ? registry.find((project: any) => project?.projectId === projectId) : null;
  const separatedSnapshot =
    typeof localStorage === "undefined" ? undefined : readJson(localStorage.getItem(`${PROJECT_SNAPSHOT_KEY_PREFIX}${projectId}`));
  const snapshot = currentProject?.snapshot ?? separatedSnapshot;
  const persisted = snapshot?.persistedLocalState as PersistedProjectLocalState | undefined;
  const localKeys =
    typeof localStorage === "undefined"
      ? []
      : Array.from({ length: localStorage.length }, (_, index) => localStorage.key(index)).filter((key): key is string => Boolean(key));
  const sessionKeys =
    typeof sessionStorage === "undefined"
      ? []
      : Array.from({ length: sessionStorage.length }, (_, index) => sessionStorage.key(index)).filter((key): key is string => Boolean(key));
  const workflowStateKeys = localKeys.filter((key) => key.startsWith(`${WORKFLOW_NODE_PREFIX}${projectId}:`));
  const savedStepIds = new Set(workflowStateKeys.map((key) => key.split(":").pop() ?? ""));
  const missingWorkflowSteps = workflowSteps.filter((step) => !savedStepIds.has(step.id)).map((step) => step.label);
  return {
    projectId,
    snapshotBytes: snapshot ? estimateBytes(snapshot) : 0,
    lastSavedAt: currentProject?.lastModified ?? persisted?.savedAt ?? "",
    restoreStatus: persisted ? (persisted.missingArtifacts?.length ? "Partial restore expected" : "Complete compact restore available") : "No compact artifact snapshot",
    missingArtifacts: persisted?.missingArtifacts ?? [],
    registryBytes: estimateBytes(registryRaw),
    localStorageKeys: localKeys,
    sessionStorageKeys: sessionKeys,
    workflowStepsSaved: workflowStateKeys.length,
    workflowStepKeys: workflowStateKeys,
    missingWorkflowSteps,
    datasetPreviewAvailable: sessionKeys.includes(DATASET_KEY),
    trainingSummaryAvailable: sessionKeys.includes(TRAINING_SUMMARY_KEY),
    storageUsageBytes: estimateBytes(localKeys.map((key) => [key, localStorage.getItem(key)])),
  };
}
