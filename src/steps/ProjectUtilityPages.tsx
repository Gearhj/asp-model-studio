import { Link, useNavigate } from "react-router-dom";
import type React from "react";
import { useEffect, useMemo, useRef, useState } from "react";
import { AlertTriangle, Calendar, Copy, Database, Download, FileArchive, FileInput, FolderOpen, FolderPlus, HardDrive, List, Pencil, Plus, RefreshCw, Save, Search, Settings2, Table2, Trash2 } from "lucide-react";
import BrandLogo from "../components/BrandLogo";
import {
  compactBrowserProjectStorage,
  currentWorkflowStage,
  deleteLocalProject,
  duplicateLocalProject,
  formatProjectDate,
  getLocalProjectsRegistryStatus,
  getProjectStorageDiagnostics,
  getProjectPersistenceDebug,
  importLocalProject,
  loadLocalProjects,
  migrateLegacyLocalProjects,
  projectProgress,
  recoverCurrentProjectToRegistry,
  repairLocalProjectsRegistry,
  renameLocalProject,
  saveProjectSnapshotFromState,
  type LocalProjectRecord,
  type LocalProjectsRegistryStatus,
  upsertProjectSnapshot,
  upsertProjectFromState,
  workflowLabel,
} from "../lib/localProjects";
import { validateProjectImport } from "../lib/projectImportValidation";
import {
  buildRecoveryReport,
  deepRecoveryScan,
  snapshotFromRecoveryCandidate,
  type ProjectRecoveryCandidate,
} from "../lib/projectRecovery";
import { useWorkflowStore } from "../state/useWorkflowStore";
import { getWorkflowDefinition, type ProjectType } from "../config/workflows";
import {
  deleteProjectFromDatabase,
  getProjectFromDatabase,
  getProjectWorkflowStateFromDatabase,
  listProjectsFromDatabase,
} from "../lib/serverPersistence";
import {
  createProjectRegistryLoadController,
  formatProjectRegistryLoadError,
  initialProjectRegistryLoadState,
  isProjectRegistryAbortError,
  validateProjectRegistryResponse,
  type ProjectRegistryLoadController,
} from "../lib/projectRegistryLoadState";
import { normalizeOptimizationTemplateId, storeOptimizationTemplateId } from "../config/optimizationTemplates";
import { deriveEffectiveWorkflowView } from "../lib/workflowEffectiveState";
import { projectWorkflowRoute } from "../lib/projectScopedRoutes";

const OPEN_PROJECT_VIEW_MODE_KEY = "atlas-open-project-view-mode";
// Effective readiness is held only after an authenticated backend fetch.
// Imported/browser metadata may preserve history, but it cannot grant validity.
const authoritativeWorkflowReadinessByProject = new Map<string, unknown>();

type ViewMode = "card" | "detail";
type ProjectSortKey = "projectName" | "projectType" | "task" | "target" | "progress" | "lastModified" | "created" | "recoveryStatus";
type SortDirection = "asc" | "desc";

function readSavedViewMode(key: string, fallback: ViewMode = "detail"): ViewMode {
  if (typeof localStorage === "undefined") return fallback;
  const saved = localStorage.getItem(key);
  return saved === "card" || saved === "detail" ? saved : fallback;
}

function mergeProjectRecords(local: LocalProjectRecord[], backend: LocalProjectRecord[]) {
  const merged = new Map(backend.map((project) => [project.projectId, project]));
  local.forEach((project) => {
    const persisted = merged.get(project.projectId);
    merged.set(project.projectId, persisted ? {
      ...project,
      ...persisted,
      backendMetadata: {
        ...(project.backendMetadata ?? {}),
        ...(persisted.backendMetadata ?? {}),
      },
      snapshot: {
        ...project.snapshot,
        ...persisted.snapshot,
        templateId: persisted.snapshot.templateId || project.snapshot.templateId,
        // A browser snapshot may enrich presentation, but it cannot replace
        // durable workflow history or canonical identity returned by backend.
        workflowSteps: persisted.snapshot.workflowSteps,
        currentStepId: persisted.snapshot.currentStepId,
        hasDataset: persisted.snapshot.hasDataset,
        datasetIdentity: persisted.snapshot.datasetIdentity,
      },
    } : project);
  });
  return [...merged.values()];
}

function databaseProjectRecord(
  project: Record<string, any>,
  workflowState: Record<string, any> | null = null,
): LocalProjectRecord {
  const projectId = String(project.projectId);
  if (workflowState) authoritativeWorkflowReadinessByProject.set(projectId, workflowState);
  const workflowId = String(project.workflowType || "predictive-modeling");
  const workflow = getWorkflowDefinition(workflowId);
  const completed = new Set(
    Array.isArray(workflowState?.historicalCompletedSteps)
      ? workflowState.historicalCompletedSteps.map(String)
      : Array.isArray(workflowState?.completedSteps)
        ? workflowState.completedSteps.map(String)
        : [],
  );
  const persistedStatuses = workflowState?.workflowStatus?.steps ?? {};
  const workflowSteps = workflow.steps.map((step) => ({
    ...step,
    status: completed.has(step.id) || persistedStatuses[step.id] === "complete"
      ? "complete" as const
      : persistedStatuses[step.id] === "skipped"
        ? "skipped" as const
        : persistedStatuses[step.id] === "in_progress"
          ? "in_progress" as const
          : "pending" as const,
  }));
  const metadata = project.metadata && typeof project.metadata === "object" ? project.metadata : {};
  const snapshot = {
    projectId,
    modelId: String(metadata.modelId || ""),
    projectName: String(project.projectName || "Untitled ATLAS Project"),
    projectType: String(project.projectType || workflow.projectType) as ProjectType,
    workflowId,
    templateId: project.templateId ? String(project.templateId) : undefined,
    workflowSteps,
    currentStepId: String(
      workflowState?.currentStepId
      || workflowSteps.find((step) => step.status !== "complete")?.id
      || workflowSteps[workflowSteps.length - 1]?.id
      || "",
    ),
    hasDataset: Boolean(metadata.hasDataset),
    datasetIdentity: workflowState?.workflowStatus?.datasetIdentity ?? null,
    restoreWarnings: [
      "Restored from the ATLAS backend registry. Large governed artifacts remain in SQLite and linked source storage.",
    ],
  };
  return {
    projectId,
    modelId: snapshot.modelId,
    projectName: snapshot.projectName,
    projectType: snapshot.projectType,
    workflowId,
    createdAt: String(project.createdAt || project.updatedAt || new Date().toISOString()),
    lastModified: String(project.updatedAt || project.createdAt || new Date().toISOString()),
    source: "database" as const,
    restoreStatus: "Backend Registry",
    backendMetadata: {
      ...metadata,
      workflowReadiness: workflowState,
    },
    snapshot,
  } satisfies LocalProjectRecord;
}

async function loadDatabaseProjects(signal: AbortSignal): Promise<LocalProjectRecord[]> {
  const payloadProjects = await listProjectsFromDatabase(signal);
  const projects = validateProjectRegistryResponse<Record<string, any>>(payloadProjects);
  authoritativeWorkflowReadinessByProject.clear();
  return projects.map((project) => databaseProjectRecord(project));
}

function databaseProjectRecordWithWorkflowState(
  record: LocalProjectRecord,
  workflowState: Record<string, any> | null,
): LocalProjectRecord {
  if (workflowState) authoritativeWorkflowReadinessByProject.set(record.projectId, workflowState);
  else authoritativeWorkflowReadinessByProject.delete(record.projectId);
  const workflow = getWorkflowDefinition(record.workflowId);
  const completed = new Set(
    Array.isArray(workflowState?.historicalCompletedSteps)
      ? workflowState.historicalCompletedSteps.map(String)
      : Array.isArray(workflowState?.completedSteps)
        ? workflowState.completedSteps.map(String)
        : [],
  );
  const persistedStatuses = workflowState?.workflowStatus?.steps ?? {};
  const workflowSteps = workflow.steps.map((step) => ({
    ...step,
    status: completed.has(step.id) || persistedStatuses[step.id] === "complete"
      ? "complete" as const
      : persistedStatuses[step.id] === "skipped"
        ? "skipped" as const
        : persistedStatuses[step.id] === "in_progress"
          ? "in_progress" as const
          : "pending" as const,
  }));
  return {
    ...record,
    backendMetadata: {
      ...(record.backendMetadata ?? {}),
      workflowReadiness: workflowState,
    },
    snapshot: {
      ...record.snapshot,
      workflowSteps,
      currentStepId: String(
        workflowState?.currentStepId
        || workflowSteps.find((step) => step.status !== "complete")?.id
        || workflowSteps[workflowSteps.length - 1]?.id
        || "",
      ),
      datasetIdentity: workflowState?.workflowStatus?.datasetIdentity ?? null,
    },
  };
}

function backendWorkflowReadiness(project: LocalProjectRecord) {
  return authoritativeWorkflowReadinessByProject.get(project.projectId) ?? null;
}

function projectEffectiveWorkflow(project: LocalProjectRecord) {
  return deriveEffectiveWorkflowView({
    workflowSteps: project.snapshot.workflowSteps,
    projectType: project.snapshot.projectType,
    datasetIdentity: project.snapshot.datasetIdentity,
    backendState: backendWorkflowReadiness(project),
  });
}

async function enrichDatabaseProjectWorkflows(
  records: LocalProjectRecord[],
  signal: AbortSignal,
): Promise<LocalProjectRecord[]> {
  if (records.length === 0) return records;

  // Workflow progress is useful launcher enrichment, but it is not the
  // authoritative project registry. Keep it bounded and failure-isolated so a
  // single stale/missing project state cannot discard a valid project list.
  const enriched = [...records];
  let nextIndex = 0;
  const workerCount = Math.min(8, records.length);
  await Promise.all(Array.from({ length: workerCount }, async () => {
    while (nextIndex < records.length) {
      if (signal.aborted) {
        const abortError = new Error("Project registry load was superseded.");
        abortError.name = "AbortError";
        throw abortError;
      }
      const index = nextIndex;
      nextIndex += 1;
      try {
        const workflowState = await getProjectWorkflowStateFromDatabase(records[index].projectId, signal);
        enriched[index] = databaseProjectRecordWithWorkflowState(records[index], workflowState);
      } catch (error) {
        if (signal.aborted || isProjectRegistryAbortError(error)) throw error;
        enriched[index] = records[index];
      }
    }
  }));
  return enriched;
}

type OpenProjectProps = {
  onSessionExpired?: () => void;
};

export function OpenProject({ onSessionExpired }: OpenProjectProps = {}) {
  const navigate = useNavigate();
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const [projects, setProjects] = useState<LocalProjectRecord[]>([]);
  const [backendProjects, setBackendProjects] = useState<LocalProjectRecord[]>([]);
  const [importMessage, setImportMessage] = useState("");
  const [registryLoadState, setRegistryLoadState] = useState(
    () => initialProjectRegistryLoadState<LocalProjectRecord>(),
  );
  const registryLoaderRef = useRef<ProjectRegistryLoadController<LocalProjectRecord> | null>(null);
  const handledAuthenticationRequestRef = useRef(0);
  if (!registryLoaderRef.current) {
    registryLoaderRef.current = createProjectRegistryLoadController<LocalProjectRecord>({
      loadProjects: loadDatabaseProjects,
      onStateChange: setRegistryLoadState,
    });
  }
  const [registryStatus, setRegistryStatus] = useState<LocalProjectsRegistryStatus>(() => ({
    ok: true,
    corrupted: false,
    message: "",
    projectCount: 0,
    validProjects: [],
  }));
  const loadProjectSnapshot = useWorkflowStore((state) => state.loadProjectSnapshot);
  const workflowState = useWorkflowStore((state) => ({
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
  }));
  const activeProjectId = workflowState.projectId;
  const setProjectName = useWorkflowStore((state) => state.setProjectName);
  const resetProject = useWorkflowStore((state) => state.reset);
  const [diagnostics, setDiagnostics] = useState(() => getProjectStorageDiagnostics(workflowState.projectId, workflowState.workflowSteps));
  const [viewMode, setViewMode] = useState<ViewMode>(() => readSavedViewMode(OPEN_PROJECT_VIEW_MODE_KEY, "detail"));
  const [projectFilter, setProjectFilter] = useState("all");
  const [projectQuery, setProjectQuery] = useState("");
  const [projectSort, setProjectSort] = useState<{ key: ProjectSortKey; direction: SortDirection }>({ key: "lastModified", direction: "desc" });
  const [recoveryCandidates, setRecoveryCandidates] = useState<ProjectRecoveryCandidate[]>([]);
  const [selectedRecoveryIds, setSelectedRecoveryIds] = useState<Set<string>>(() => new Set());
  const [recoveryScanning, setRecoveryScanning] = useState(false);
  const [recoveryActions, setRecoveryActions] = useState<string[]>([]);

  const refreshProjectLauncher = () => {
    const status = getLocalProjectsRegistryStatus();
    const nextProjects = loadLocalProjects();
    setRegistryStatus(status);
    setProjects(mergeProjectRecords(nextProjects, backendProjects));
    setViewMode((current) => (nextProjects.length > 6 ? "detail" : current));
    setDiagnostics(getProjectStorageDiagnostics(workflowState.projectId, workflowState.workflowSteps));
  };

  const setProjectViewMode = (mode: ViewMode) => {
    setViewMode(mode);
    if (typeof localStorage !== "undefined") localStorage.setItem(OPEN_PROJECT_VIEW_MODE_KEY, mode);
  };

  useEffect(() => {
    const status = getLocalProjectsRegistryStatus();
    setRegistryStatus(status);
    if (status.corrupted) {
      setProjects(mergeProjectRecords(status.validProjects, backendProjects));
      setImportMessage(status.message);
      return;
    }
    try {
      const migration = migrateLegacyLocalProjects();
      refreshProjectLauncher();
      if (migration.migrated > 0) {
        setImportMessage(`Recovered ${migration.migrated} browser-saved project${migration.migrated === 1 ? "" : "s"} from legacy ATLAS storage.`);
      }
    } catch (error) {
      setProjects(mergeProjectRecords(loadLocalProjects(), backendProjects));
      setImportMessage(error instanceof Error ? `Open Project loaded, but project registry maintenance failed: ${error.message}` : "Open Project loaded, but project registry maintenance failed.");
    }
    // Keep the launcher route resilient even when registry migration fails.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const loader = registryLoaderRef.current;
    if (!loader) return undefined;
    void loader.load();
    return () => loader.dispose();
  }, []);

  useEffect(() => {
    if (registryLoadState.status !== "success") return undefined;
    const requestId = registryLoadState.requestId;
    const records = registryLoadState.projects;
    const controller = new AbortController();
    void enrichDatabaseProjectWorkflows(records, controller.signal)
      .then((enriched) => {
        if (controller.signal.aborted) return;
        setRegistryLoadState((current) => (
          current.status === "success" && current.requestId === requestId
            ? { ...current, projects: enriched }
            : current
        ));
      })
      .catch((error) => {
        if (!controller.signal.aborted && !isProjectRegistryAbortError(error)) {
          // Enrichment is deliberately non-authoritative. The valid list stays
          // rendered even if a late workflow-progress read cannot complete.
        }
      });
    return () => controller.abort();
    // The request identity starts one enrichment pass. Updating its project
    // records must not recursively start another pass.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [registryLoadState.requestId, registryLoadState.status]);

  useEffect(() => {
    const backendRecords = registryLoadState.status === "success" ? registryLoadState.projects : [];
    setBackendProjects(backendRecords);
    setProjects((current) => {
      const browserProjects = current.filter((project) => project.source !== "database");
      return mergeProjectRecords(browserProjects, backendRecords);
    });

    if (
      registryLoadState.status === "error"
      && registryLoadState.error?.kind === "authentication"
      && handledAuthenticationRequestRef.current !== registryLoadState.requestId
    ) {
      handledAuthenticationRequestRef.current = registryLoadState.requestId;
      onSessionExpired?.();
    }
  }, [onSessionExpired, registryLoadState]);

  const retryProjectRegistry = () => {
    void registryLoaderRef.current?.load();
  };

  const displayProjects = useMemo(() => {
    const needle = projectQuery.trim().toLowerCase();
    const filteredProjects = projects.filter((project) => {
      const effective = projectEffectiveWorkflow(project);
      const progress = projectProgress(effective.effectiveWorkflowSteps);
      const currentStage = currentWorkflowStage(effective.effectiveWorkflowSteps, effective.effectiveCurrentStepId);
      const linkedDatasets = inferLinkedDatasets(project);
      const storageLocation = inferProjectStorageLocation(project);
      const recoveryStatus = inferProjectRecoveryStatus(project);
      const text = [
        project.projectName,
        project.modelId,
        project.projectType,
        project.workflowId,
        workflowLabel(project.projectType, project.workflowId),
        inferProjectTask(project),
        inferProjectTarget(project),
        linkedDatasets,
        storageLocation,
        recoveryStatus,
        project.restoreStatus,
        currentStage?.label,
      ]
        .filter(Boolean)
        .join(" ")
        .toLowerCase();
      const matchesSearch = !needle || text.includes(needle);
      const task = inferProjectTask(project);
      const filterMatches =
        projectFilter === "all" ||
        (projectFilter === "predictive" && project.projectType === "predictive-modeling") ||
        (projectFilter === "experimental" && project.projectType === "experimental-design") ||
        (projectFilter === "regression" && task === "regression") ||
        (projectFilter === "classification" && task === "classification") ||
        (projectFilter === "recovered" && /recover|shell|partial/i.test(`${project.restoreStatus ?? ""} ${project.snapshot?.restoreWarnings?.join(" ") ?? ""}`)) ||
        (projectFilter === "incomplete" && progress.complete < progress.total);
      return matchesSearch && filterMatches;
    });
    return [...filteredProjects].sort((a, b) => {
      const compare = compareProjectRows(a, b, projectSort.key);
      return projectSort.direction === "asc" ? compare : -compare;
    });
  }, [projectFilter, projectQuery, projectSort, projects]);

  const toggleProjectSort = (key: ProjectSortKey) => {
    setProjectSort((current) => ({
      key,
      direction: current.key === key && current.direction === "asc" ? "desc" : "asc",
    }));
  };

  const openProject = async (project: LocalProjectRecord) => {
    const selectedProjectId = String(project.projectId || "").trim();
    if (!selectedProjectId) {
      setImportMessage("ATLAS could not open this project because its exact project ID is missing.");
      return;
    }
    setImportMessage(`Verifying authorization for ${project.projectName}...`);
    try {
      const [projectPayload, workflowReadiness] = await Promise.all([
        getProjectFromDatabase(selectedProjectId),
        getProjectWorkflowStateFromDatabase(selectedProjectId),
      ]);
      const returnedProjectId = String(projectPayload?.projectId ?? projectPayload?.project_id ?? "").trim();
      if (returnedProjectId !== selectedProjectId) {
        throw new Error("The authorized project response did not match the selected project ID.");
      }

      const authorizedProject = databaseProjectRecord(projectPayload, workflowReadiness);
      if (authorizedProject.snapshot.templateId) {
        storeOptimizationTemplateId(
          authorizedProject.projectId,
          normalizeOptimizationTemplateId(authorizedProject.snapshot.templateId),
        );
      }
      const optimizationState = authorizedProject.backendMetadata?.optimizationState;
      if (authorizedProject.snapshot.templateId === "transportation_logistics" && optimizationState && typeof optimizationState === "object") {
        localStorage.setItem(`atlas-optimization-transportation:${authorizedProject.projectId}`, JSON.stringify(optimizationState));
      }

      const effective = projectEffectiveWorkflow(authorizedProject);
      const relativeRoute = authorizedProject.projectType === "predictive-modeling"
        ? "/step00"
        : currentWorkflowStage(
            effective.effectiveWorkflowSteps,
            effective.effectiveCurrentStepId,
          )?.route || "/project-overview";
      if (authorizedProject.projectType !== "predictive-modeling") {
        // Compatibility only: non-predictive workflows do not yet have the
        // project-scoped provider. Predictive routes never hydrate from this
        // browser snapshot; their route ID starts a second race-safe backend read.
        loadProjectSnapshot(authorizedProject.snapshot);
      }
      const route = authorizedProject.projectType === "predictive-modeling"
        ? projectWorkflowRoute(selectedProjectId, relativeRoute)
        : relativeRoute;
      navigate(route);
      window.scrollTo({ top: 0, behavior: "smooth" });
    } catch (error) {
      setImportMessage(
        error instanceof Error
          ? `ATLAS could not open the exact authorized project: ${error.message}`
          : "ATLAS could not open the exact authorized project.",
      );
    }
  };

  const repairRegistry = () => {
    try {
      const result = repairLocalProjectsRegistry();
      refreshProjectLauncher();
      setImportMessage(result.message);
    } catch (error) {
      setImportMessage(error instanceof Error ? `Recent Projects repair failed: ${error.message}` : "Recent Projects repair failed.");
    }
  };

  const recoverActiveProject = () => {
    try {
      const result = recoverCurrentProjectToRegistry(useWorkflowStore.getState());
      refreshProjectLauncher();
      setImportMessage(result.message);
    } catch (error) {
      setImportMessage(error instanceof Error ? `Current project recovery failed: ${error.message}` : "Current project recovery failed.");
    }
  };

  const rebuildRecentProjectsIndex = () => {
    try {
      const repaired = repairLocalProjectsRegistry();
      const recovered = recoverCurrentProjectToRegistry(useWorkflowStore.getState());
      refreshProjectLauncher();
      setImportMessage(`${repaired.message} ${recovered.message}`);
    } catch (error) {
      setImportMessage(error instanceof Error ? `Recent Projects rebuild failed: ${error.message}` : "Recent Projects rebuild failed.");
    }
  };

  const compactProjectStorage = () => {
    const result = compactBrowserProjectStorage(workflowState.projectId);
    refreshProjectLauncher();
    setImportMessage(result.message);
  };

  const exportCurrentProjectBackup = () => {
    const snapshot = useWorkflowStore.getState();
    const backup = {
      exportedAt: new Date().toISOString(),
      exportType: "atlas-current-project-backup",
      snapshot,
    };
    const blob = new Blob([JSON.stringify(backup, null, 2)], { type: "application/json;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `${(workflowState.projectName || "atlas-project").replace(/[^a-z0-9]+/gi, "-").replace(/^-|-$/g, "").toLowerCase() || "atlas-project"}-backup.atlas`;
    anchor.click();
    URL.revokeObjectURL(url);
    setImportMessage("Current project backup exported from active workflow state.");
  };

  const exportProjectBackup = (project: LocalProjectRecord) => {
    const blob = new Blob([JSON.stringify(project, null, 2)], { type: "application/json;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `${project.projectName.replace(/[^a-z0-9]+/gi, "-").replace(/^-|-$/g, "").toLowerCase() || "atlas-project"}.atlas`;
    anchor.click();
    URL.revokeObjectURL(url);
    setImportMessage(`Exported backup for "${project.projectName}".`);
  };

  const runDeepRecoveryScan = async () => {
    setRecoveryScanning(true);
    setImportMessage("");
    try {
      const result = await deepRecoveryScan(loadLocalProjects());
      setRecoveryCandidates(result.candidates);
      setRecoveryActions((actions) => [...actions, `Deep recovery scan found ${result.candidates.length} candidate project${result.candidates.length === 1 ? "" : "s"}.`]);
      setImportMessage(
        `Deep Recovery Scan found ${result.candidates.length} project candidate${result.candidates.length === 1 ? "" : "s"}. ${
          result.errors.length ? `Warnings: ${result.errors.join(" ")}` : "Review and select projects to recover."
        }`
      );
    } catch (error) {
      setImportMessage(error instanceof Error ? `Deep Recovery Scan failed: ${error.message}` : "Deep Recovery Scan failed.");
    } finally {
      setRecoveryScanning(false);
    }
  };

  const toggleRecoveryCandidate = (candidateId: string) => {
    setSelectedRecoveryIds((current) => {
      const next = new Set(current);
      if (next.has(candidateId)) next.delete(candidateId);
      else next.add(candidateId);
      return next;
    });
  };

  const recoverSelectedProjects = () => {
    const selected = recoveryCandidates.filter((candidate) => selectedRecoveryIds.has(candidate.candidateId));
    if (!selected.length) {
      setImportMessage("Select one or more recovery candidates first.");
      return;
    }
    const actions: string[] = [];
    for (const candidate of selected) {
      const snapshot = candidate.snapshot ?? snapshotFromRecoveryCandidate(candidate);
      const record = upsertProjectSnapshot(snapshot, "browser");
      if (record) actions.push(`Recovered ${candidate.name} as Recent Project ${record.projectId}.`);
      else actions.push(`Skipped ${candidate.name}; it did not contain enough project metadata to recover.`);
    }
    setRecoveryActions((previous) => [...previous, ...actions]);
    setSelectedRecoveryIds(new Set());
    refreshProjectLauncher();
    setImportMessage(actions.join(" "));
  };

  const exportRecoveryReport = () => {
    const report = buildRecoveryReport(recoveryCandidates, recoveryActions);
    const blob = new Blob([report], { type: "text/markdown;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = "PROJECT_RECOVERY_SCAN_REPORT.md";
    anchor.click();
    URL.revokeObjectURL(url);
    setImportMessage("Project recovery scan report exported.");
  };

  const duplicateProject = (event: React.MouseEvent, project: LocalProjectRecord) => {
    event.stopPropagation();
    const { projects: nextProjects, duplicate } = duplicateLocalProject(project.projectId);
    setProjects(mergeProjectRecords(nextProjects, backendProjects));
    if (duplicate) setImportMessage(`Duplicated "${project.projectName}".`);
  };

  const renameProject = (event: React.MouseEvent, project: LocalProjectRecord) => {
    event.stopPropagation();
    const nextName = window.prompt("Rename project", project.projectName);
    if (!nextName || !nextName.trim()) return;
    const nextProjects = renameLocalProject(project.projectId, nextName);
    setProjects(mergeProjectRecords(nextProjects, backendProjects));
    if (project.projectId === activeProjectId) setProjectName(nextName.trim());
    setImportMessage(`Renamed project to "${nextName.trim()}".`);
  };

  const removeProject = async (event: React.MouseEvent, project: LocalProjectRecord) => {
    event.stopPropagation();
    const confirmed = window.confirm(`Delete "${project.projectName}"? This removes the project workspace and its saved workflow records. Dataset Library assets and source data files are retained.`);
    if (!confirmed) return;
    let databaseWarning = "";
    try {
      await deleteProjectFromDatabase(project.projectId);
    } catch (error) {
      databaseWarning = error instanceof Error
        ? ` Browser cleanup completed, but the backend record could not be removed: ${error.message}`
        : " Browser cleanup completed, but the backend record could not be removed.";
    }
    const remainingBackend = backendProjects.filter((record) => record.projectId !== project.projectId);
    setBackendProjects(remainingBackend);
    setProjects(mergeProjectRecords(deleteLocalProject(project.projectId), remainingBackend));
    if (project.projectId === activeProjectId) resetProject();
    setImportMessage(`Deleted "${project.projectName}".${databaseWarning}`);
  };

  const importProjectFile = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    try {
      const parsed = JSON.parse(await file.text());
      const validation = validateProjectImport(parsed);
      if (!validation.ok) {
        setImportMessage(`Import rejected: ${validation.errors.join(" ")}`);
        return;
      }
      const imported = importLocalProject(parsed);
      if (!imported) {
        setImportMessage("The selected file does not look like an ATLAS project export.");
        return;
      }
      setProjects(mergeProjectRecords(loadLocalProjects(), backendProjects));
      setImportMessage(`Imported "${imported.projectName}".${validation.warnings.length ? ` ${validation.warnings.join(" ")}` : ""}`);
    } catch {
      setImportMessage("Could not import that file. Select a valid ATLAS project JSON export.");
    }
  };

  const shouldAutoExpandRecoveryTools =
    projects.length === 0 ||
    registryStatus.volatileFallback ||
    Boolean(diagnostics.lastRegistryWriteError) ||
    registryStatus.corrupted ||
    recoveryCandidates.length > 0;

  const projectRegistryIsLoading = registryLoadState.status === "idle" || registryLoadState.status === "loading";
  const projectListSection = projects.length === 0 && projectRegistryIsLoading ? (
    <section
      data-testid="project-registry-loading"
      className="rounded-xl border border-slate-200/80 bg-white/90 p-8 text-center shadow-sm"
    >
      <div className="text-sm font-semibold text-slate-800">Loading ATLAS projects…</div>
      <p className="mt-2 text-sm text-slate-500">Reading the authenticated project registry.</p>
    </section>
  ) : projects.length === 0 ? (
    <div data-testid="project-registry-empty">
      <EmptyProjects />
    </div>
  ) : (
    <section data-testid="project-registry-list" className="space-y-3">
      <div className="flex flex-col gap-3 rounded-xl border border-slate-200/80 bg-white/90 p-4 shadow-sm lg:flex-row lg:items-end lg:justify-between">
        <div>
          <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500">Browser Projects</h2>
          <p className="mt-1 text-sm text-slate-600">These projects are stored in this browser and do not require a manual export to reopen.</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <label className="flex min-w-[260px] items-center gap-2 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2">
            <Search size={15} className="text-slate-500" />
            <input
              className="w-full bg-transparent text-sm outline-none"
              placeholder="Search project, target, dataset, or type"
              value={projectQuery}
              onChange={(event) => setProjectQuery(event.target.value)}
            />
          </label>
          <select
            value={projectFilter}
            onChange={(event) => setProjectFilter(event.target.value)}
            className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-semibold text-slate-700 shadow-sm"
          >
            <option value="all">All</option>
            <option value="predictive">Predictive Modeling</option>
            <option value="experimental">Experimental Design</option>
            <option value="regression">Regression</option>
            <option value="classification">Classification</option>
            <option value="recovered">Recovered</option>
            <option value="incomplete">Incomplete</option>
          </select>
          <div className="inline-flex rounded-lg border border-slate-300 bg-white p-1 shadow-sm">
            <button type="button" onClick={() => setProjectViewMode("card")} className={`inline-flex items-center gap-1 rounded-md px-2 py-1.5 text-xs font-semibold ${viewMode === "card" ? "bg-slate-950 text-white" : "text-slate-600 hover:bg-slate-50"}`}>
              <List size={13} />
              Card View
            </button>
            <button type="button" onClick={() => setProjectViewMode("detail")} className={`inline-flex items-center gap-1 rounded-md px-2 py-1.5 text-xs font-semibold ${viewMode === "detail" ? "bg-slate-950 text-white" : "text-slate-600 hover:bg-slate-50"}`}>
              <Table2 size={13} />
              Detailed View
            </button>
          </div>
        </div>
      </div>
      {viewMode === "detail" ? (
        <EnterpriseProjectTable
          projects={displayProjects}
          activeProjectId={activeProjectId}
          onOpen={openProject}
          onDuplicate={duplicateProject}
          onRename={renameProject}
          onDelete={removeProject}
          onExport={exportProjectBackup}
          sort={projectSort}
          onSort={toggleProjectSort}
        />
      ) : (
        <div className="grid gap-4 xl:grid-cols-2 2xl:grid-cols-3">
          {displayProjects.map((project) => (
            <ProjectCard
              key={project.projectId}
              project={project}
              isActive={project.projectId === activeProjectId}
              onOpen={openProject}
              onDuplicate={duplicateProject}
              onRename={renameProject}
              onDelete={removeProject}
            />
          ))}
        </div>
      )}
      {displayProjects.length === 0 && (
        <div className="rounded-xl border border-dashed border-slate-300 bg-white p-6 text-center text-sm text-slate-600">
          No projects match the current search and filters.
        </div>
      )}
    </section>
  );

  return (
    <div className="w-full space-y-5">
      <section className="rounded-xl border border-slate-200/80 bg-white/90 p-5 shadow-sm">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div>
            <BrandLogo size="md" variant="light" showSubtitle className="mb-4" />
            <div className="flex items-center gap-2">
              <FolderOpen size={20} className="text-blue-600" />
              <h1 className="text-xl font-semibold text-slate-950">Recent Projects</h1>
            </div>
            <p className="mt-1 max-w-3xl text-sm leading-6 text-slate-600">
              Browser-saved projects appear below automatically. Use file import only for exported .atlas or .json project packages.
            </p>
          </div>
          <div className="grid gap-2 sm:grid-cols-3 lg:min-w-[520px]">
            <button
              type="button"
              onClick={() => fileInputRef.current?.click()}
              className="inline-flex items-center justify-center gap-2 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-semibold text-slate-700 shadow-sm hover:bg-slate-50"
            >
              <FolderOpen size={16} />
              Open Local Project...
            </button>
            <button
              type="button"
              onClick={() => fileInputRef.current?.click()}
              className="inline-flex items-center justify-center gap-2 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-semibold text-slate-700 shadow-sm hover:bg-slate-50"
            >
              <FileInput size={16} />
              Import Project...
            </button>
            <Link
              to="/projects/new"
              className="inline-flex items-center justify-center gap-2 rounded-lg bg-slate-950 px-3 py-2 text-sm font-semibold text-white shadow-sm hover:bg-slate-800"
            >
              <Plus size={16} />
              Create New Project
            </Link>
          </div>
        </div>
        <input ref={fileInputRef} type="file" accept="application/json,.json,.atlas" className="hidden" onChange={importProjectFile} />
        {registryStatus.corrupted && (
          <div className="mt-4 rounded-lg border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-950">
            <div className="font-semibold">Recent Projects index needs repair</div>
            <p className="mt-1">{registryStatus.message}</p>
            <button
              type="button"
              onClick={repairRegistry}
              className="mt-3 inline-flex items-center gap-2 rounded-lg bg-amber-900 px-3 py-2 text-sm font-semibold text-white shadow-sm hover:bg-amber-800"
            >
              <RefreshCw size={15} />
              Repair Recent Projects
            </button>
          </div>
        )}
        <div
          data-testid="project-registry-status"
          data-state={registryLoadState.status}
          aria-live="polite"
        >
          {projectRegistryIsLoading && (
            <div className="mt-4 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-700">
              Loading the authenticated ATLAS project registry…
            </div>
          )}
          {registryLoadState.status === "error" && registryLoadState.error && (
            <div
              data-testid="project-registry-error"
              data-error-kind={registryLoadState.error.kind}
              role="alert"
              className="mt-4 rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-950"
            >
              <div className="flex items-start gap-3">
                <AlertTriangle size={18} className="mt-0.5 shrink-0" />
                <div className="min-w-0 flex-1">
                  <div className="font-semibold">
                    {registryLoadState.error.kind === "authentication"
                      ? "ATLAS sign-in required"
                      : registryLoadState.error.kind === "authorization"
                        ? "Project registry access denied"
                        : registryLoadState.error.kind === "response"
                          ? "Project registry response could not be used"
                          : "Project registry request failed"}
                  </div>
                  <p className="mt-1">{formatProjectRegistryLoadError(registryLoadState.error)}</p>
                  <button
                    type="button"
                    data-testid="project-registry-retry"
                    onClick={retryProjectRegistry}
                    className="mt-3 inline-flex items-center gap-2 rounded-lg border border-rose-300 bg-white px-3 py-2 text-sm font-semibold text-rose-950 shadow-sm hover:bg-rose-100"
                  >
                    <RefreshCw size={15} />
                    Retry project registry
                  </button>
                </div>
              </div>
            </div>
          )}
          {registryLoadState.status === "success" && (
            <span className="sr-only">Project registry loaded successfully.</span>
          )}
          {registryLoadState.status === "empty" && (
            <span className="sr-only">Project registry loaded successfully with no projects.</span>
          )}
        </div>
        {false && (projects.length === 0 || registryStatus.volatileFallback || diagnostics.lastRegistryWriteError) && (
          <div className="mt-4 rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-950">
            <div className="flex items-start gap-3">
              <AlertTriangle size={18} className="mt-0.5 shrink-0" />
              <div className="min-w-0 flex-1">
                <div className="font-semibold">Project Recovery</div>
                <p className="mt-1 leading-6">
                  {projects.length === 0
                    ? `No Recent Projects cards are registered, but the active workflow is "${workflowState.projectName || "Untitled ATLAS Project"}". Recover it before closing the browser.`
                    : "Recent Projects is available, but browser storage reported a registry warning. Export a backup or compact storage if saves continue to warn."}
                </p>
                <div className="mt-3 flex flex-wrap gap-2">
                  <button type="button" onClick={recoverActiveProject} className="inline-flex items-center gap-2 rounded-lg bg-amber-900 px-3 py-2 text-sm font-semibold text-white shadow-sm hover:bg-amber-800">
                    <RefreshCw size={15} />
                    Recover Current Project
                  </button>
                  <button type="button" onClick={exportCurrentProjectBackup} className="inline-flex items-center gap-2 rounded-lg border border-amber-300 bg-white px-3 py-2 text-sm font-semibold text-amber-950 shadow-sm hover:bg-amber-100">
                    <Download size={15} />
                    Export Current Project Backup
                  </button>
                  <button type="button" onClick={rebuildRecentProjectsIndex} className="inline-flex items-center gap-2 rounded-lg border border-amber-300 bg-white px-3 py-2 text-sm font-semibold text-amber-950 shadow-sm hover:bg-amber-100">
                    <RefreshCw size={15} />
                    Rebuild Recent Projects Index
                  </button>
                  <button type="button" onClick={compactProjectStorage} className="inline-flex items-center gap-2 rounded-lg border border-amber-300 bg-white px-3 py-2 text-sm font-semibold text-amber-950 shadow-sm hover:bg-amber-100">
                    <HardDrive size={15} />
                    Compact Browser Project Storage
                  </button>
                </div>
              </div>
            </div>
          </div>
        )}
        {importMessage && <div className="mt-4 rounded-lg border border-blue-200 bg-blue-50 px-3 py-2 text-sm text-blue-900">{importMessage}</div>}
      </section>

      {projectListSection}

      <details open={shouldAutoExpandRecoveryTools} className="rounded-xl border border-slate-200/80 bg-white/90 p-5 shadow-sm">
        <summary className="cursor-pointer list-none">
          <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <div className="flex items-center gap-2">
                <RefreshCw size={18} className="text-blue-700" />
                <h2 className="text-base font-semibold text-slate-950">Advanced Recovery Tools</h2>
              </div>
              <p className="mt-1 text-sm leading-6 text-slate-600">
                Recovery and storage diagnostics stay collapsed during normal use. Open this section only to repair Recent Projects, scan orphaned projects, or troubleshoot browser storage.
              </p>
            </div>
            <span className="rounded-full border border-slate-200 bg-slate-50 px-3 py-1 text-xs font-semibold text-slate-600">
              {shouldAutoExpandRecoveryTools ? "Attention needed" : "Collapsed by default"}
            </span>
          </div>
        </summary>
        <div className="mt-5 space-y-5">
        {(projects.length === 0 || registryStatus.volatileFallback || diagnostics.lastRegistryWriteError) && (
          <section className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-950">
            <div className="flex items-start gap-3">
              <AlertTriangle size={18} className="mt-0.5 shrink-0" />
              <div className="min-w-0 flex-1">
                <div className="font-semibold">Project Recovery</div>
                <p className="mt-1 leading-6">
                  {projects.length === 0
                    ? `No Recent Projects cards are registered, but the active workflow is "${workflowState.projectName || "Untitled ATLAS Project"}". Recover it before closing the browser.`
                    : "Recent Projects is available, but browser storage reported a registry warning. Export a backup or compact storage if saves continue to warn."}
                </p>
                <div className="mt-3 flex flex-wrap gap-2">
                  <button type="button" onClick={recoverActiveProject} className="inline-flex items-center gap-2 rounded-lg bg-amber-900 px-3 py-2 text-sm font-semibold text-white shadow-sm hover:bg-amber-800">
                    <RefreshCw size={15} />
                    Recover Current Project
                  </button>
                  <button type="button" onClick={exportCurrentProjectBackup} className="inline-flex items-center gap-2 rounded-lg border border-amber-300 bg-white px-3 py-2 text-sm font-semibold text-amber-950 shadow-sm hover:bg-amber-100">
                    <Download size={15} />
                    Export Current Project Backup
                  </button>
                  <button type="button" onClick={rebuildRecentProjectsIndex} className="inline-flex items-center gap-2 rounded-lg border border-amber-300 bg-white px-3 py-2 text-sm font-semibold text-amber-950 shadow-sm hover:bg-amber-100">
                    <RefreshCw size={15} />
                    Rebuild Recent Projects Index
                  </button>
                  <button type="button" onClick={compactProjectStorage} className="inline-flex items-center gap-2 rounded-lg border border-amber-300 bg-white px-3 py-2 text-sm font-semibold text-amber-950 shadow-sm hover:bg-amber-100">
                    <HardDrive size={15} />
                    Compact Browser Project Storage
                  </button>
                </div>
              </div>
            </div>
          </section>
        )}
      <section className="rounded-xl border border-slate-200/80 bg-white/90 p-5 shadow-sm">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
          <div>
            <div className="flex items-center gap-2">
              <Database size={18} className="text-blue-700" />
              <h2 className="text-base font-semibold text-slate-950">Project Storage Diagnostics</h2>
            </div>
            <p className="mt-1 text-sm leading-6 text-slate-600">
              This checks whether Recent Projects is using durable browser storage or a temporary recovery index after a quota warning.
            </p>
          </div>
          <button type="button" onClick={refreshProjectLauncher} className="inline-flex items-center justify-center gap-2 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-semibold text-slate-700 shadow-sm hover:bg-slate-50">
            <RefreshCw size={15} />
            Refresh Diagnostics
          </button>
        </div>
        <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-4">
          <MetaCard label="Registry status" value={diagnostics.registryOk ? "OK" : "Needs attention"} />
          <MetaCard label="Registry size" value={`${Math.round(diagnostics.registryBytes / 1024).toLocaleString()} KB`} />
          <MetaCard label="Storage usage" value={`${Math.round(diagnostics.storageUsageBytes / 1024).toLocaleString()} KB`} />
          <MetaCard label="Recovery fallback" value={diagnostics.volatileFallback ? "Active this session" : "Not active"} />
        </div>
        {diagnostics.lastRegistryWriteError && (
          <div className="mt-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-950">
            {diagnostics.lastRegistryWriteError}
          </div>
        )}
        <div className="mt-4 rounded-lg border border-slate-200 bg-slate-50 p-3">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">Largest Browser Storage Keys</h3>
          <div className="mt-2 grid gap-2 text-xs text-slate-700">
            {diagnostics.largestKeys.length ? (
              diagnostics.largestKeys.map((item) => (
                <div key={item.key} className="flex items-center justify-between gap-4 rounded-md bg-white px-2 py-1.5">
                  <span className="min-w-0 truncate font-mono" title={item.key}>{item.key}</span>
                  <span className="shrink-0 font-semibold">{Math.round(item.bytes / 1024).toLocaleString()} KB</span>
                </div>
              ))
            ) : (
              <div className="rounded-md bg-white px-2 py-1.5 text-slate-500">No browser storage keys detected.</div>
            )}
          </div>
        </div>
      </section>

      <section className="rounded-xl border border-slate-200/80 bg-white/90 p-5 shadow-sm">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
          <div>
            <div className="flex items-center gap-2">
              <RefreshCw size={18} className="text-blue-700" />
              <h2 className="text-base font-semibold text-slate-950">Deep Recovery Scan</h2>
            </div>
            <p className="mt-1 max-w-3xl text-sm leading-6 text-slate-600">
              Scan browser storage, backend project registry artifacts, Dataset Library links, and server artifacts for unregistered projects. Select candidates before recovery.
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <button type="button" onClick={runDeepRecoveryScan} className="inline-flex items-center gap-2 rounded-lg bg-slate-950 px-3 py-2 text-sm font-semibold text-white shadow-sm hover:bg-slate-800">
              <Search size={15} />
              Scan Browser Storage
            </button>
            <button type="button" onClick={runDeepRecoveryScan} className="inline-flex items-center gap-2 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-semibold text-slate-700 shadow-sm hover:bg-slate-50">
              <HardDrive size={15} />
              Scan Server Artifacts
            </button>
            <button type="button" onClick={runDeepRecoveryScan} className="inline-flex items-center gap-2 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-semibold text-slate-700 shadow-sm hover:bg-slate-50">
              <Database size={15} />
              Scan Dataset Links
            </button>
            <button type="button" onClick={recoverSelectedProjects} className="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-3 py-2 text-sm font-semibold text-white shadow-sm hover:bg-blue-700">
              <RefreshCw size={15} />
              Recover Selected Projects
            </button>
            <button type="button" onClick={exportRecoveryReport} className="inline-flex items-center gap-2 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-semibold text-slate-700 shadow-sm hover:bg-slate-50">
              <Download size={15} />
              Export Recovery Report
            </button>
          </div>
        </div>
        {recoveryScanning && <div className="mt-4 rounded-lg border border-blue-200 bg-blue-50 px-3 py-2 text-sm text-blue-900">Scanning storage sources...</div>}
        {recoveryCandidates.length > 0 && <RecoveryCandidateTable candidates={recoveryCandidates} selectedIds={selectedRecoveryIds} onToggle={toggleRecoveryCandidate} />}
      </section>

        </div>
      </details>

      {false && (projects.length === 0 ? (
        <EmptyProjects />
      ) : (
        <section className="space-y-3">
          <div className="flex flex-col gap-3 rounded-xl border border-slate-200/80 bg-white/90 p-4 shadow-sm lg:flex-row lg:items-end lg:justify-between">
            <div>
              <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500">Browser Projects</h2>
              <p className="mt-1 text-sm text-slate-600">These projects are stored in this browser and do not require a manual export to reopen.</p>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <label className="flex min-w-[260px] items-center gap-2 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2">
                <Search size={15} className="text-slate-500" />
                <input
                  className="w-full bg-transparent text-sm outline-none"
                  placeholder="Search project, target, dataset, or type"
                  value={projectQuery}
                  onChange={(event) => setProjectQuery(event.target.value)}
                />
              </label>
              <select
                value={projectFilter}
                onChange={(event) => setProjectFilter(event.target.value)}
                className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-semibold text-slate-700 shadow-sm"
              >
                <option value="all">All</option>
                <option value="predictive">Predictive Modeling</option>
                <option value="experimental">Experimental Design</option>
                <option value="regression">Regression</option>
                <option value="classification">Classification</option>
                <option value="recovered">Recovered</option>
                <option value="incomplete">Incomplete</option>
              </select>
              <div className="inline-flex rounded-lg border border-slate-300 bg-white p-1 shadow-sm">
                <button type="button" onClick={() => setViewMode("card")} className={`inline-flex items-center gap-1 rounded-md px-2 py-1.5 text-xs font-semibold ${viewMode === "card" ? "bg-slate-950 text-white" : "text-slate-600 hover:bg-slate-50"}`}>
                  <List size={13} />
                  Card View
                </button>
                <button type="button" onClick={() => setViewMode("detail")} className={`inline-flex items-center gap-1 rounded-md px-2 py-1.5 text-xs font-semibold ${viewMode === "detail" ? "bg-slate-950 text-white" : "text-slate-600 hover:bg-slate-50"}`}>
                  <Table2 size={13} />
                  Detailed View
                </button>
              </div>
            </div>
          </div>
          {viewMode === "detail" ? (
            <ProjectDetailTable
              projects={displayProjects}
              activeProjectId={activeProjectId}
              onOpen={openProject}
              onDuplicate={duplicateProject}
              onRename={renameProject}
              onDelete={removeProject}
              onExport={exportProjectBackup}
            />
          ) : (
          <div className="grid gap-4 xl:grid-cols-2 2xl:grid-cols-3">
            {displayProjects.map((project) => (
              <ProjectCard
                key={project.projectId}
                project={project}
                isActive={project.projectId === activeProjectId}
                onOpen={openProject}
                onDuplicate={duplicateProject}
                onRename={renameProject}
                onDelete={removeProject}
              />
            ))}
          </div>
          )}
          {displayProjects.length === 0 && (
            <div className="rounded-xl border border-dashed border-slate-300 bg-white p-6 text-center text-sm text-slate-600">
              No projects match the current search and filters.
            </div>
          )}
        </section>
      ))}
    </div>
  );
}

function ProjectCard({
  project,
  isActive,
  onOpen,
  onDuplicate,
  onRename,
  onDelete,
}: {
  project: LocalProjectRecord;
  isActive: boolean;
  onOpen: (project: LocalProjectRecord) => void;
  onDuplicate: (event: React.MouseEvent, project: LocalProjectRecord) => void;
  onRename: (event: React.MouseEvent, project: LocalProjectRecord) => void;
  onDelete: (event: React.MouseEvent, project: LocalProjectRecord) => void;
}) {
  const effective = projectEffectiveWorkflow(project);
  const progress = projectProgress(effective.effectiveWorkflowSteps);
  const currentStage = currentWorkflowStage(effective.effectiveWorkflowSteps, effective.effectiveCurrentStepId);
  const label = workflowLabel(project.projectType, project.workflowId);

  return (
    <article
      role="button"
      tabIndex={0}
      onClick={() => onOpen(project)}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") onOpen(project);
      }}
      className="group cursor-pointer rounded-xl border border-slate-200/80 bg-white/90 p-5 shadow-sm transition hover:-translate-y-0.5 hover:border-blue-200 hover:shadow-md"
    >
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="truncate text-base font-semibold text-slate-950">{project.projectName}</h2>
            {isActive && <span className="rounded-full bg-blue-50 px-2 py-1 text-[11px] font-semibold uppercase tracking-wide text-blue-700">Current</span>}
            <span className="rounded-full bg-slate-100 px-2 py-1 text-[11px] font-semibold uppercase tracking-wide text-slate-600">
                    {project.source === "imported"
                      ? "Imported"
                      : project.source === "database"
                        ? "ATLAS database"
                        : "Browser saved"}
            </span>
          </div>
          <p className="mt-1 text-sm text-slate-600">{label}</p>
        </div>
        {project.modelId && (
          <span className="rounded-lg border border-slate-200 bg-slate-50 px-2.5 py-1.5 text-xs font-semibold text-slate-700">
            ID {project.modelId}
          </span>
        )}
      </div>

      <div className="mt-4 rounded-lg border border-slate-200 bg-slate-50 p-3">
        <div className="flex items-center justify-between gap-3 text-xs font-semibold uppercase tracking-wide text-slate-500">
          <span>{progress.complete} of {progress.total} steps complete</span>
          <span>{progress.percent}%</span>
        </div>
        <div className="mt-2 h-2 overflow-hidden rounded-full bg-slate-200">
          <div className="h-full rounded-full bg-blue-600 transition-all" style={{ width: `${progress.percent}%` }} />
        </div>
        <div className="mt-3 grid gap-2 text-sm text-slate-700 sm:grid-cols-2">
          <Meta label="Current stage" value={currentStage?.label ?? "Not started"} />
          <Meta label="Workflow type" value={project.projectType.replace(/-/g, " ")} />
        </div>
      </div>

      <div className="mt-4 grid gap-2 text-xs text-slate-500 sm:grid-cols-2">
        <div className="flex items-center gap-2">
          <Calendar size={14} />
          <span>Created {formatProjectDate(project.createdAt)}</span>
        </div>
        <div className="flex items-center gap-2">
          <Calendar size={14} />
          <span>Modified {formatProjectDate(project.lastModified)}</span>
        </div>
      </div>

      <div className="mt-4 flex flex-wrap gap-2">
        <button
          type="button"
          onClick={(event) => {
            event.stopPropagation();
            onOpen(project);
          }}
          className="inline-flex items-center gap-2 rounded-lg bg-slate-950 px-3 py-2 text-sm font-semibold text-white shadow-sm hover:bg-slate-800"
        >
          <FolderOpen size={15} />
          Open
        </button>
        <CardButton icon={<Copy size={15} />} label="Duplicate" onClick={(event) => onDuplicate(event, project)} />
        <CardButton icon={<Pencil size={15} />} label="Rename" onClick={(event) => onRename(event, project)} />
        <CardButton icon={<Trash2 size={15} />} label="Delete" onClick={(event) => onDelete(event, project)} danger />
      </div>
    </article>
  );
}

function EnterpriseProjectTable({
  projects,
  activeProjectId,
  onOpen,
  onDuplicate,
  onRename,
  onDelete,
  onExport,
  sort,
  onSort,
}: {
  projects: LocalProjectRecord[];
  activeProjectId: string;
  onOpen: (project: LocalProjectRecord) => void;
  onDuplicate: (event: React.MouseEvent, project: LocalProjectRecord) => void;
  onRename: (event: React.MouseEvent, project: LocalProjectRecord) => void;
  onDelete: (event: React.MouseEvent, project: LocalProjectRecord) => void;
  onExport: (project: LocalProjectRecord) => void;
  sort: { key: ProjectSortKey; direction: SortDirection };
  onSort: (key: ProjectSortKey) => void;
}) {
  return (
    <div className="min-w-0 overflow-x-auto rounded-xl border border-slate-200 bg-white shadow-sm">
      <table className="min-w-[940px] w-full table-fixed text-left text-sm">
        <thead className="sticky top-0 z-10 bg-slate-100 text-[11px] uppercase tracking-wide text-slate-500">
          <tr>
            <SortableProjectHeader label="Project Name" sortKey="projectName" activeSort={sort} onSort={onSort} />
            <SortableProjectHeader label="Project Type" sortKey="projectType" activeSort={sort} onSort={onSort} />
            <th className="px-3 py-3">Current Stage</th>
            <SortableProjectHeader label="Progress" sortKey="progress" activeSort={sort} onSort={onSort} />
            <th className="px-3 py-3">Linked Datasets</th>
            <SortableProjectHeader label="Last Modified" sortKey="lastModified" activeSort={sort} onSort={onSort} />
            <SortableProjectHeader label="Recovery Status" sortKey="recoveryStatus" activeSort={sort} onSort={onSort} />
            <th className="sticky right-0 z-20 border-l border-slate-200 bg-slate-100 px-3 py-3 shadow-[-8px_0_12px_-12px_rgba(15,23,42,0.45)]">Actions</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {projects.map((project) => {
            const effective = projectEffectiveWorkflow(project);
            const progress = projectProgress(effective.effectiveWorkflowSteps);
            const currentStage = currentWorkflowStage(effective.effectiveWorkflowSteps, effective.effectiveCurrentStepId);
            const percent = progress.total ? Math.round((progress.complete / progress.total) * 100) : 0;
            const linkedDatasets = inferLinkedDatasets(project);
            return (
              <tr key={project.projectId} className={project.projectId === activeProjectId ? "bg-blue-50/70" : "odd:bg-white even:bg-slate-50/60"}>
                <td className="w-[22%] px-3 py-2">
                  <div className="truncate font-semibold text-slate-950" title={project.projectName}>{project.projectName}</div>
                  <div className="truncate text-xs text-slate-500" title={`${inferProjectTask(project) || "No task"} | ${inferProjectTarget(project) || "No target"}`}>
                    {project.modelId ? `Model ${project.modelId}` : project.projectId} | {inferProjectTask(project) || "No task"} | {inferProjectTarget(project) || "No target"}
                  </div>
                </td>
                <td className="w-[13%] px-3 py-2 capitalize text-slate-700">{workflowLabel(project.projectType, project.workflowId)}</td>
                <td className="w-[15%] px-3 py-2 text-slate-700">{currentStage?.label ?? "Not started"}</td>
                <td className="px-3 py-2">
                  <div className="text-xs font-semibold text-slate-700">{progress.complete} / {progress.total} steps</div>
                  <div className="mt-1 h-1.5 w-24 overflow-hidden rounded-full bg-slate-200">
                    <div className="h-full rounded-full bg-blue-600" style={{ width: `${percent}%` }} />
                  </div>
                  <div className="mt-0.5 text-[11px] text-slate-500">{percent}%</div>
                </td>
                <td className="w-[16%] px-3 py-2 text-slate-700">
                  <span className="line-clamp-2" title={linkedDatasets}>{linkedDatasets}</span>
                </td>
                <td className="w-[11%] px-3 py-2 text-slate-700">{formatProjectDate(project.lastModified)}</td>
                <td className="px-3 py-2">
                  <span className="rounded-full bg-slate-100 px-2 py-1 text-xs font-semibold text-slate-700">
                    {inferProjectRecoveryStatus(project)}
                  </span>
                </td>
                <td className={`sticky right-0 z-10 border-l border-slate-200 px-3 py-2 shadow-[-8px_0_12px_-12px_rgba(15,23,42,0.45)] ${project.projectId === activeProjectId ? "bg-blue-50" : "bg-white"}`}>
                  <div className="flex items-center justify-end gap-1">
                    <button type="button" title="Open project" aria-label={`Open ${project.projectName}`} onClick={() => onOpen(project)} className="rounded-md bg-slate-950 p-2 text-white hover:bg-slate-800"><FolderOpen size={15} /></button>
                    <button type="button" title="Duplicate project" aria-label={`Duplicate ${project.projectName}`} onClick={(event) => onDuplicate(event, project)} className="rounded-md border border-slate-300 bg-white p-2 text-slate-700 hover:bg-slate-50"><Copy size={15} /></button>
                    <button type="button" title="Rename project" aria-label={`Rename ${project.projectName}`} onClick={(event) => onRename(event, project)} className="rounded-md border border-slate-300 bg-white p-2 text-slate-700 hover:bg-slate-50"><Pencil size={15} /></button>
                    <button type="button" title="Export project backup" aria-label={`Export ${project.projectName} backup`} onClick={() => onExport(project)} className="rounded-md border border-slate-300 bg-white p-2 text-slate-700 hover:bg-slate-50"><Download size={15} /></button>
                    <button type="button" title="Delete project" aria-label={`Delete ${project.projectName}`} onClick={(event) => void onDelete(event, project)} className="rounded-md border border-red-200 bg-white p-2 text-red-700 hover:bg-red-50"><Trash2 size={15} /></button>
                  </div>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function SortableProjectHeader({
  label,
  sortKey,
  activeSort,
  onSort,
}: {
  label: string;
  sortKey: ProjectSortKey;
  activeSort: { key: ProjectSortKey; direction: SortDirection };
  onSort: (key: ProjectSortKey) => void;
}) {
  const active = activeSort.key === sortKey;
  return (
    <th className="px-3 py-3">
      <button type="button" onClick={() => onSort(sortKey)} className="inline-flex items-center gap-1 font-semibold hover:text-slate-900">
        {label}
        <span className="text-[10px]">{active ? (activeSort.direction === "asc" ? "▲" : "▼") : "↕"}</span>
      </button>
    </th>
  );
}

function ProjectDetailTable({
  projects,
  activeProjectId,
  onOpen,
  onDuplicate,
  onRename,
  onDelete,
  onExport,
}: {
  projects: LocalProjectRecord[];
  activeProjectId: string;
  onOpen: (project: LocalProjectRecord) => void;
  onDuplicate: (event: React.MouseEvent, project: LocalProjectRecord) => void;
  onRename: (event: React.MouseEvent, project: LocalProjectRecord) => void;
  onDelete: (event: React.MouseEvent, project: LocalProjectRecord) => void;
  onExport: (project: LocalProjectRecord) => void;
}) {
  return (
    <div className="overflow-x-auto rounded-xl border border-slate-200 bg-white shadow-sm">
      <table className="min-w-[1180px] w-full text-left text-sm">
        <thead className="sticky top-0 bg-slate-100 text-[11px] uppercase tracking-wide text-slate-500">
          <tr>
            <th className="px-3 py-3">Project Name</th>
            <th className="px-3 py-3">Type</th>
            <th className="px-3 py-3">Task</th>
            <th className="px-3 py-3">Target</th>
            <th className="px-3 py-3">Linked Datasets</th>
            <th className="px-3 py-3">Last Modified</th>
            <th className="px-3 py-3">Created</th>
            <th className="px-3 py-3">Storage Location</th>
            <th className="px-3 py-3">Recovery Status</th>
            <th className="px-3 py-3">Actions</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {projects.map((project) => {
            const effective = projectEffectiveWorkflow(project);
            const progress = projectProgress(effective.effectiveWorkflowSteps);
            const currentStage = currentWorkflowStage(effective.effectiveWorkflowSteps, effective.effectiveCurrentStepId);
            return (
              <tr key={project.projectId} className={project.projectId === activeProjectId ? "bg-blue-50/70" : "odd:bg-white even:bg-slate-50/60"}>
                <td className="px-3 py-3">
                  <div className="font-semibold text-slate-950">{project.projectName}</div>
                  <div className="text-xs text-slate-500">
                    {project.modelId ? `Model ID ${project.modelId} · ` : ""}
                    {progress.complete} of {progress.total} steps · {currentStage?.label ?? "Not started"}
                  </div>
                </td>
                <td className="px-3 py-3 capitalize text-slate-700">{workflowLabel(project.projectType, project.workflowId)}</td>
                <td className="px-3 py-3 capitalize text-slate-700">{inferProjectTask(project) || "-"}</td>
                <td className="px-3 py-3 text-slate-700">{inferProjectTarget(project) || "-"}</td>
                <td className="px-3 py-3 text-slate-700">{inferLinkedDatasets(project)}</td>
                <td className="px-3 py-3 text-slate-700">{formatProjectDate(project.lastModified)}</td>
                <td className="px-3 py-3 text-slate-700">{formatProjectDate(project.createdAt)}</td>
                <td className="px-3 py-3 capitalize text-slate-700">{project.source ?? "browser"}</td>
                <td className="px-3 py-3">
                  <span className="rounded-full bg-slate-100 px-2 py-1 text-xs font-semibold text-slate-700">
                    {project.restoreStatus || (project.snapshot?.restoreWarnings?.length ? "Recovered / review needed" : "Registered")}
                  </span>
                </td>
                <td className="px-3 py-3">
                  <div className="flex flex-wrap gap-1.5">
                    <button type="button" onClick={() => onOpen(project)} className="rounded-md bg-slate-950 px-2 py-1 text-xs font-semibold text-white">Open</button>
                    <button type="button" onClick={(event) => onDuplicate(event, project)} className="rounded-md border border-slate-300 bg-white px-2 py-1 text-xs font-semibold text-slate-700">Duplicate</button>
                    <button type="button" onClick={(event) => onRename(event, project)} className="rounded-md border border-slate-300 bg-white px-2 py-1 text-xs font-semibold text-slate-700">Rename</button>
                    <button type="button" onClick={() => onExport(project)} className="rounded-md border border-slate-300 bg-white px-2 py-1 text-xs font-semibold text-slate-700">Export Backup</button>
                    <button type="button" onClick={(event) => onDelete(event, project)} className="rounded-md border border-red-200 bg-white px-2 py-1 text-xs font-semibold text-red-700">Delete</button>
                  </div>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function RecoveryCandidateTable({
  candidates,
  selectedIds,
  onToggle,
}: {
  candidates: ProjectRecoveryCandidate[];
  selectedIds: Set<string>;
  onToggle: (candidateId: string) => void;
}) {
  return (
    <div className="mt-4 overflow-x-auto rounded-xl border border-slate-200">
      <table className="min-w-[980px] w-full text-left text-sm">
        <thead className="bg-slate-100 text-[11px] uppercase tracking-wide text-slate-500">
          <tr>
            <th className="px-3 py-3">Recover</th>
            <th className="px-3 py-3">Project</th>
            <th className="px-3 py-3">Type</th>
            <th className="px-3 py-3">Task</th>
            <th className="px-3 py-3">Target</th>
            <th className="px-3 py-3">Linked Datasets</th>
            <th className="px-3 py-3">Completeness</th>
            <th className="px-3 py-3">Source</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {candidates.map((candidate) => (
            <tr key={candidate.candidateId} className="odd:bg-white even:bg-slate-50/60">
              <td className="px-3 py-3">
                <input type="checkbox" checked={selectedIds.has(candidate.candidateId)} onChange={() => onToggle(candidate.candidateId)} />
              </td>
              <td className="px-3 py-3">
                <div className="font-semibold text-slate-950">{candidate.name}</div>
                <div className="text-xs text-slate-500">{candidate.projectId}</div>
              </td>
              <td className="px-3 py-3 capitalize text-slate-700">{candidate.projectType.replace(/-/g, " ")}</td>
              <td className="px-3 py-3 capitalize text-slate-700">{candidate.taskType || "-"}</td>
              <td className="px-3 py-3 text-slate-700">{candidate.target || "-"}</td>
              <td className="px-3 py-3 text-slate-700">{candidate.linkedDatasets.map((dataset) => dataset.name || dataset.datasetId).filter(Boolean).join(", ") || "-"}</td>
              <td className="px-3 py-3">
                <span className="rounded-full bg-amber-50 px-2 py-1 text-xs font-semibold text-amber-800">{candidate.completeness}</span>
              </td>
              <td className="px-3 py-3 text-xs text-slate-600">{candidate.sourceLocation}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function inferProjectTask(project: LocalProjectRecord) {
  const text = `${project.projectName} ${project.workflowId} ${project.projectType} ${project.snapshot?.restoreWarnings?.join(" ") ?? ""}`.toLowerCase();
  if (project.projectType === "experimental-design") return "experimental design";
  if (text.includes("regression") || text.includes("home prices") || text.includes("medhouse")) return "regression";
  if (text.includes("classification") || text.includes("fraud") || text.includes("class")) return "classification";
  return project.projectType === "predictive-modeling" ? "predictive" : "";
}

function inferProjectTarget(project: LocalProjectRecord) {
  const text = `${project.projectName} ${project.snapshot?.restoreWarnings?.join(" ") ?? ""}`.toLowerCase();
  if (text.includes("medhouse")) return "MedHouseVal";
  if (text.includes("class") || text.includes("fraud")) return "Class";
  return "";
}

function inferLinkedDatasets(project: LocalProjectRecord) {
  const text = `${project.projectName} ${project.snapshot?.restoreWarnings?.join(" ") ?? ""}`.toLowerCase();
  if (text.includes("regression") || text.includes("home prices") || text.includes("medhouse")) return "REG_TRAIN, REG_TEST, REG_OOT";
  if (text.includes("classification") || text.includes("fraud") || text.includes("class")) return "CLASS_TRAIN, CLASS_TEST, CLASS_OOT";
  return project.snapshot?.hasDataset ? "Linked dataset" : "-";
}

function inferProjectStorageLocation(project: LocalProjectRecord) {
  const restoreText = `${project.restoreStatus ?? ""} ${project.snapshot?.restoreWarnings?.join(" ") ?? ""}`.toLowerCase();
  if (restoreText.includes("server artifact")) return "Server Artifact";
  if (restoreText.includes("backend")) return "Backend Registry";
  if (restoreText.includes("recover")) return "Recovered";
  if (project.source === "imported") return "Imported";
  if (project.source === "database") return "Backend Registry";
  return "Browser";
}

function inferProjectRecoveryStatus(project: LocalProjectRecord) {
  const restoreText = `${project.restoreStatus ?? ""} ${project.snapshot?.restoreWarnings?.join(" ") ?? ""}`.toLowerCase();
  if (restoreText.includes("dataset-linked shell")) return "Dataset-linked shell";
  if (restoreText.includes("partial")) return "Partial";
  if (restoreText.includes("recover")) return "Recovered";
  if (project.snapshot?.restoreWarnings?.length) return "Needs review";
  return project.restoreStatus || "Complete";
}

function compareProjectRows(a: LocalProjectRecord, b: LocalProjectRecord, key: ProjectSortKey) {
  const progressA = projectProgress(projectEffectiveWorkflow(a).effectiveWorkflowSteps);
  const progressB = projectProgress(projectEffectiveWorkflow(b).effectiveWorkflowSteps);
  const values: Record<ProjectSortKey, [string | number, string | number]> = {
    projectName: [a.projectName, b.projectName],
    projectType: [workflowLabel(a.projectType, a.workflowId), workflowLabel(b.projectType, b.workflowId)],
    task: [inferProjectTask(a), inferProjectTask(b)],
    target: [inferProjectTarget(a), inferProjectTarget(b)],
    progress: [
      progressA.total ? progressA.complete / progressA.total : 0,
      progressB.total ? progressB.complete / progressB.total : 0,
    ],
    lastModified: [Date.parse(a.lastModified || "") || 0, Date.parse(b.lastModified || "") || 0],
    created: [Date.parse(a.createdAt || "") || 0, Date.parse(b.createdAt || "") || 0],
    recoveryStatus: [inferProjectRecoveryStatus(a), inferProjectRecoveryStatus(b)],
  };
  const [left, right] = values[key];
  if (typeof left === "number" && typeof right === "number") return left - right;
  return String(left).localeCompare(String(right), undefined, { sensitivity: "base", numeric: true });
}

function Meta({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">{label}</div>
      <div className="mt-0.5 capitalize text-slate-900">{value}</div>
    </div>
  );
}

function CardButton({ icon, label, onClick, danger = false }: { icon: React.ReactNode; label: string; onClick: (event: React.MouseEvent) => void; danger?: boolean }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`inline-flex items-center gap-2 rounded-lg border px-3 py-2 text-sm font-semibold shadow-sm ${
        danger
          ? "border-red-200 bg-white text-red-700 hover:bg-red-50"
          : "border-slate-300 bg-white text-slate-700 hover:bg-slate-50"
      }`}
    >
      {icon}
      {label}
    </button>
  );
}

function EmptyProjects() {
  return (
    <section className="rounded-xl border border-dashed border-slate-300 bg-white/80 p-8 text-center shadow-sm">
      <div className="mx-auto flex h-20 w-20 items-center justify-center rounded-2xl bg-blue-50 text-blue-700">
        <FolderPlus size={36} />
      </div>
      <h2 className="mt-4 text-lg font-semibold text-slate-950">No local projects yet</h2>
      <p className="mx-auto mt-2 max-w-2xl text-sm leading-6 text-slate-600">
        Create your first ATLAS project or import a project JSON export. Once a project exists, it will appear here as a reusable workspace card.
      </p>
      <Link
        to="/projects/new"
        className="mt-5 inline-flex items-center gap-2 rounded-lg bg-slate-950 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-slate-800"
      >
        <Plus size={16} />
        Create New Project
      </Link>
    </section>
  );
}

export function ExportsPage() {
  return (
    <UtilityPage
      icon={<FileArchive size={20} />}
      title="Exports"
      description="Use Governance, Notebook, Decision Journal, Experiment Comparison, and Model Development Document exports from the Current Project tools."
      actionLabel="Open Governance Report"
      actionPath="/governance-report"
    />
  );
}

export function SettingsPage() {
  const workflowState = useWorkflowStore((state) => ({
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
  }));
  const [debug, setDebug] = useState(() => getProjectPersistenceDebug(workflowState.projectId, workflowState.workflowSteps));
  const [message, setMessage] = useState("");

  const refresh = () => setDebug(getProjectPersistenceDebug(workflowState.projectId, workflowState.workflowSteps));

  const saveNow = () => {
    try {
      saveProjectSnapshotFromState(useWorkflowStore.getState());
      setMessage("Project snapshot saved successfully.");
      refresh();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "ATLAS could not save the current project snapshot.");
    }
  };

  const exportCurrentProject = () => {
    const project = loadLocalProjects().find((item) => item.projectId === workflowState.projectId);
    if (!project) {
      setMessage("Save the current project before exporting.");
      return;
    }
    const blob = new Blob([JSON.stringify(project, null, 2)], { type: "application/json;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `${project.projectName.replace(/[^a-z0-9]+/gi, "-").replace(/^-|-$/g, "").toLowerCase() || "atlas-project"}.atlas`;
    anchor.click();
    URL.revokeObjectURL(url);
  };

  const repairIndex = () => {
    const migration = migrateLegacyLocalProjects();
    upsertProjectFromState(useWorkflowStore.getState());
    setMessage(`Recent Projects repaired. ${migration.migrated} legacy project${migration.migrated === 1 ? "" : "s"} recovered.`);
    refresh();
  };

  const clearCurrentProjectCache = () => {
    const confirmed = window.confirm("Clear cached workflow-node artifacts for the current project? This does not delete the Recent Project card.");
    if (!confirmed || typeof localStorage === "undefined") return;
    const prefix = `atlas-workflow-node-state:${workflowState.projectId}:`;
    const keys = Array.from({ length: localStorage.length }, (_, index) => localStorage.key(index)).filter(
      (key): key is string => Boolean(key?.startsWith(prefix))
    );
    keys.forEach((key) => localStorage.removeItem(key));
    setMessage(`Cleared ${keys.length} workflow-node cache entr${keys.length === 1 ? "y" : "ies"} for this project.`);
    refresh();
  };

  return (
    <div className="w-full space-y-5">
      <section className="rounded-xl border border-slate-200/80 bg-white/90 p-5 shadow-sm">
        <BrandLogo size="md" variant="light" showSubtitle className="mb-3" />
        <div className="flex items-center gap-2">
          <Settings2 size={20} />
          <h1 className="text-xl font-semibold text-slate-950">Settings</h1>
        </div>
        <p className="mt-1 max-w-3xl text-sm leading-6 text-slate-600">
          Global ATLAS settings will live here. Challenge Mode and workflow-specific settings are currently available inside Atlas Guide and each workflow step.
        </p>
      </section>

      <section className="rounded-xl border border-slate-200/80 bg-white/90 p-5 shadow-sm">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
          <div>
            <div className="flex items-center gap-2">
              <Database size={18} className="text-blue-700" />
              <h2 className="text-base font-semibold text-slate-950">Security and User Context</h2>
            </div>
            <p className="mt-1 text-sm leading-6 text-slate-600">
              ATLAS now uses authenticated backend identity for dataset ownership, project access, audit logging, and governance actions.
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Link to="/account" className="rounded-lg bg-slate-950 px-3 py-2 text-sm font-semibold text-white shadow-sm hover:bg-slate-800">
              Open Account
            </Link>
            <Link to="/admin/users" className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-semibold text-slate-700 shadow-sm hover:bg-slate-50">
              User Administration
            </Link>
            <Link to="/audit" className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-semibold text-slate-700 shadow-sm hover:bg-slate-50">
              Audit Log
            </Link>
          </div>
        </div>
      </section>

      <section className="rounded-xl border border-slate-200/80 bg-white/90 p-5 shadow-sm">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
          <div>
            <div className="flex items-center gap-2">
              <Database size={18} className="text-blue-700" />
              <h2 className="text-base font-semibold text-slate-950">Project Persistence Debug</h2>
            </div>
            <p className="mt-1 text-sm leading-6 text-slate-600">
              Inspect the browser snapshot used by Recent Projects. Use this if a project does not reopen with expected page inputs.
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <button type="button" onClick={saveNow} className="inline-flex items-center gap-2 rounded-lg bg-slate-950 px-3 py-2 text-sm font-semibold text-white shadow-sm hover:bg-slate-800">
              <Save size={15} />
              Save Now
            </button>
            <button type="button" onClick={exportCurrentProject} className="inline-flex items-center gap-2 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-semibold text-slate-700 shadow-sm hover:bg-slate-50">
              <Download size={15} />
              Export Project
            </button>
            <button type="button" onClick={repairIndex} className="inline-flex items-center gap-2 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-semibold text-slate-700 shadow-sm hover:bg-slate-50">
              <RefreshCw size={15} />
              Repair Recent Projects
            </button>
            <button type="button" onClick={clearCurrentProjectCache} className="inline-flex items-center gap-2 rounded-lg border border-red-200 bg-white px-3 py-2 text-sm font-semibold text-red-700 shadow-sm hover:bg-red-50">
              <Trash2 size={15} />
              Clear Local Project Cache
            </button>
          </div>
        </div>
        {message && <div className="mt-4 rounded-lg border border-blue-200 bg-blue-50 px-3 py-2 text-sm text-blue-900">{message}</div>}
        <div className="mt-4 grid gap-3 lg:grid-cols-4">
          <MetaCard label="Project ID" value={debug.projectId} />
          <MetaCard label="Snapshot size" value={`${Math.round(debug.snapshotBytes / 1024).toLocaleString()} KB`} />
          <MetaCard label="Last saved" value={debug.lastSavedAt ? formatProjectDate(debug.lastSavedAt) : "Not saved"} />
          <MetaCard label="Restore status" value={debug.restoreStatus} />
          <MetaCard label="Registry size" value={`${Math.round(debug.registryBytes / 1024).toLocaleString()} KB`} />
          <MetaCard label="Workflow steps saved" value={`${debug.workflowStepsSaved}`} />
          <MetaCard label="Storage usage" value={`${Math.round(debug.storageUsageBytes / 1024).toLocaleString()} KB`} />
          <MetaCard label="Dataset preview" value={debug.datasetPreviewAvailable ? "Available" : "Missing"} />
          <MetaCard label="Training summary" value={debug.trainingSummaryAvailable ? "Available" : "Missing"} />
          <MetaCard label="Missing node states" value={`${debug.missingWorkflowSteps.length}`} />
          <MetaCard label="Current step" value={workflowState.currentStepId} />
        </div>
        <div className="mt-4 grid gap-4 lg:grid-cols-2">
          <DebugList title="Local Storage Keys" items={debug.localStorageKeys} />
          <DebugList title="Session Storage Keys" items={debug.sessionStorageKeys} />
          <DebugList title="Workflow Node Keys" items={debug.workflowStepKeys} />
          <DebugList title="Missing Artifacts" items={debug.missingArtifacts} empty="No missing large artifacts recorded for the saved snapshot." />
          <DebugList title="Missing Workflow Artifacts" items={debug.missingWorkflowSteps} empty="All workflow node artifacts currently have saved keys." />
        </div>
      </section>
    </div>
  );
}

function MetaCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2">
      <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">{label}</div>
      <div className="mt-1 truncate text-sm font-semibold text-slate-950" title={value}>
        {value}
      </div>
    </div>
  );
}

function DebugList({ title, items, empty = "None" }: { title: string; items: string[]; empty?: string }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-slate-50 p-3">
      <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">{title}</h3>
      <div className="mt-2 max-h-40 overflow-auto rounded-md bg-white p-2 font-mono text-[11px] leading-5 text-slate-700">
        {items.length ? items.map((item) => <div key={item} className="break-all">{item}</div>) : <div className="font-sans text-slate-500">{empty}</div>}
      </div>
    </div>
  );
}

function UtilityPage({
  icon,
  title,
  description,
  actionLabel,
  actionPath,
}: {
  icon: React.ReactNode;
  title: string;
  description: string;
  actionLabel: string;
  actionPath: string;
}) {
  return (
    <div className="w-full space-y-5">
      <section className="rounded-xl border border-slate-200/80 bg-white/90 p-5 shadow-sm">
        <BrandLogo size="md" variant="light" showSubtitle className="mb-3" />
        <div className="flex items-center gap-2">
          {icon}
          <h1 className="text-xl font-semibold text-slate-950">{title}</h1>
        </div>
        <p className="mt-1 max-w-3xl text-sm leading-6 text-slate-600">{description}</p>
        <Link to={actionPath} className="mt-4 inline-flex rounded-lg bg-slate-950 px-3 py-2 text-sm font-semibold text-white shadow-sm hover:bg-slate-800">
          {actionLabel}
        </Link>
      </section>
    </div>
  );
}
