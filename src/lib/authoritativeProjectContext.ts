import { workflowDefinitions, type ProjectType } from "../config/workflows";
import type { ProjectContext } from "./projectContext";
import {
  requireCanonicalDatasetIdentity,
  type CanonicalDatasetIdentity,
} from "./datasetIdentity";

export const AUTHORITATIVE_PROJECT_CONTEXT_STATUSES = [
  "idle",
  "resolving",
  "ready",
  "not_found",
  "unauthorized",
  "workflow_unavailable",
  "identity_unavailable",
  "contradictory",
  "error",
] as const;

export type AuthoritativeProjectContextStatus =
  (typeof AUTHORITATIVE_PROJECT_CONTEXT_STATUSES)[number];

export type AuthoritativeProjectRecord = {
  projectId: string;
  projectName: string;
  projectType: ProjectType;
  workflowId: string;
  modelId: string;
  ownerUserId: string;
  updatedAt: string;
  metadataRevision: string;
  metadataSavedAt: string;
  projectContext: Partial<ProjectContext> | null;
  projectTools: Record<string, boolean>;
};

export type AuthoritativeProjectReadyContext = {
  status: "ready";
  routeProjectId: string;
  project: AuthoritativeProjectRecord;
  workflowState: Record<string, any>;
  activeDatasetIdentity: CanonicalDatasetIdentity | null;
  backendRevision: string;
  loadedAt: string;
  message: string;
};

export type AuthoritativeProjectNonReadyContext = {
  status: Exclude<AuthoritativeProjectContextStatus, "ready">;
  routeProjectId: string;
  project: AuthoritativeProjectRecord | null;
  workflowState: Record<string, any> | null;
  activeDatasetIdentity: CanonicalDatasetIdentity | null;
  backendRevision: string;
  loadedAt: string;
  message: string;
  httpStatus?: number;
};

export type AuthoritativeProjectContextReadiness =
  | AuthoritativeProjectReadyContext
  | AuthoritativeProjectNonReadyContext;

export const IDLE_AUTHORITATIVE_PROJECT_CONTEXT: AuthoritativeProjectNonReadyContext = {
  status: "idle",
  routeProjectId: "",
  project: null,
  workflowState: null,
  activeDatasetIdentity: null,
  backendRevision: "",
  loadedAt: "",
  message: "Open a project-scoped workflow route to resolve project context.",
};

export function resolvingAuthoritativeProjectContext(
  routeProjectId: string,
): AuthoritativeProjectNonReadyContext {
  return {
    ...IDLE_AUTHORITATIVE_PROJECT_CONTEXT,
    status: "resolving",
    routeProjectId,
    message: "Loading project context...",
  };
}

export function failedAuthoritativeProjectContext(input: {
  status: Exclude<AuthoritativeProjectContextStatus, "idle" | "resolving" | "ready">;
  routeProjectId: string;
  message: string;
  httpStatus?: number;
}): AuthoritativeProjectNonReadyContext {
  return {
    ...IDLE_AUTHORITATIVE_PROJECT_CONTEXT,
    status: input.status,
    routeProjectId: input.routeProjectId,
    message: input.message,
    ...(input.httpStatus == null ? {} : { httpStatus: input.httpStatus }),
  };
}

function record(value: unknown): Record<string, any> {
  return value && typeof value === "object" ? value as Record<string, any> : {};
}

function text(...values: unknown[]) {
  for (const value of values) {
    if (typeof value === "string" && value.trim()) return value.trim();
  }
  return "";
}

function normalizeProjectType(value: unknown): ProjectType | null {
  const candidate = text(value);
  return [
    "predictive-modeling",
    "experimental-design",
    "optimization",
    "ab-testing",
    "time-series",
  ].includes(candidate)
    ? candidate as ProjectType
    : null;
}

function workflowDatasetIdentity(workflowState: Record<string, any>) {
  const workflowStatus = record(
    workflowState.workflowStatus ?? workflowState.workflow_status,
  );
  return workflowStatus.datasetIdentity ?? workflowStatus.dataset_identity ?? null;
}

function projectActiveSelection(project: Record<string, any>) {
  return project.activeSelection ?? project.active_selection ?? null;
}

function selectionTriple(value: unknown) {
  const selection = record(value);
  const projectId = text(selection.project_id, selection.projectId);
  const datasetId = text(selection.dataset_id, selection.datasetId);
  const datasetVersionId = text(
    selection.dataset_version_id,
    selection.datasetVersionId,
  );
  return projectId && datasetId && datasetVersionId
    ? { projectId, datasetId, datasetVersionId }
    : null;
}

function sameTriple(
  left: { projectId: string; datasetId: string; datasetVersionId: string },
  right: { projectId: string; datasetId: string; datasetVersionId: string },
) {
  return left.projectId === right.projectId
    && left.datasetId === right.datasetId
    && left.datasetVersionId === right.datasetVersionId;
}

export type ResolveAuthoritativeProjectContextInput = {
  routeProjectId: string;
  projectPayload: unknown;
  workflowState: unknown;
  activeIdentityPayload: unknown;
  requireWorkflow?: boolean;
  requireActiveIdentity?: boolean;
  loadedAt?: string;
};

/**
 * Validate three independently loaded backend authorities before any of them is
 * published to the workflow store. This function never reads browser storage,
 * selects a project, or chooses a dataset version.
 */
export function resolveAuthoritativeProjectContext(
  input: ResolveAuthoritativeProjectContextInput,
): AuthoritativeProjectContextReadiness {
  const routeProjectId = text(input.routeProjectId);
  const project = record(input.projectPayload);
  const returnedProjectId = text(project.projectId, project.project_id);
  if (!routeProjectId || returnedProjectId !== routeProjectId) {
    return failedAuthoritativeProjectContext({
      status: "contradictory",
      routeProjectId,
      message: "The project response does not match the project-scoped URL.",
    });
  }

  const projectName = text(project.projectName, project.project_name);
  const projectType = normalizeProjectType(project.projectType ?? project.project_type);
  const workflowId = text(
    project.workflowType,
    project.workflow_type,
    project.workflowId,
    project.workflow_id,
  );
  if (!projectName || !projectType || !workflowId) {
    return failedAuthoritativeProjectContext({
      status: "contradictory",
      routeProjectId,
      message: "The authorized project record is missing its governed name, type, or workflow identity.",
    });
  }
  const workflowDefinition = workflowDefinitions.find(
    (definition) => definition.id === workflowId,
  );
  if (
    projectType !== "predictive-modeling"
    || workflowDefinition?.projectType !== "predictive-modeling"
  ) {
    return failedAuthoritativeProjectContext({
      status: "contradictory",
      routeProjectId,
      message: "This project-scoped Predictive Modeling route resolved a different project or workflow type.",
    });
  }

  const metadata = record(project.metadata ?? project.metadata_json);
  const modelId = text(metadata.modelId, metadata.model_id, project.modelId, project.model_id);
  const ownerUserId = text(project.ownerUserId, project.owner_user_id);
  if (!modelId || !ownerUserId) {
    return failedAuthoritativeProjectContext({
      status: "contradictory",
      routeProjectId,
      message: "The authorized project record is missing its governed model or owner identity.",
    });
  }
  const normalizedProject: AuthoritativeProjectRecord = {
    projectId: returnedProjectId,
    projectName,
    projectType,
    workflowId,
    modelId,
    ownerUserId,
    updatedAt: text(project.updatedAt, project.updated_at),
    metadataRevision: text(
      metadata.projectContextRevision,
      metadata.project_context_revision,
      metadata.projectContextSavedAt,
      metadata.project_context_saved_at,
      project.updatedAt,
      project.updated_at,
    ),
    metadataSavedAt: text(
      metadata.projectContextSavedAt,
      metadata.project_context_saved_at,
      project.updatedAt,
      project.updated_at,
    ),
    projectContext: (() => {
      const stored = metadata.projectContext ?? metadata.project_context;
      return stored && typeof stored === "object"
        ? stored as Partial<ProjectContext>
        : null;
    })(),
    projectTools: record(metadata.projectTools ?? metadata.project_tools),
  };

  const workflow = record(input.workflowState);
  if (!Object.keys(workflow).length) {
    if (input.requireWorkflow !== false) {
      return {
        ...failedAuthoritativeProjectContext({
          status: "workflow_unavailable",
          routeProjectId,
          message: "Workflow state is unavailable for this authorized project.",
        }),
        project: normalizedProject,
      };
    }
  } else {
    const workflowProjectId = text(workflow.projectId, workflow.project_id);
    if (workflowProjectId !== routeProjectId) {
      return failedAuthoritativeProjectContext({
        status: "contradictory",
        routeProjectId,
        message: "The workflow-state response belongs to a different project.",
      });
    }
    const workflowStatus = record(
      workflow.workflowStatus ?? workflow.workflow_status,
    );
    const workflowStateWorkflowId = text(
      workflowStatus.workflowId,
      workflowStatus.workflow_id,
    );
    const workflowStateProjectType = text(
      workflowStatus.projectType,
      workflowStatus.project_type,
    );
    if (
      (workflowStateWorkflowId && workflowStateWorkflowId !== workflowId)
      || (workflowStateProjectType && workflowStateProjectType !== projectType)
    ) {
      return failedAuthoritativeProjectContext({
        status: "contradictory",
        routeProjectId,
        message: "The project and workflow-state responses identify different governed workflows.",
      });
    }
  }

  let activeDatasetIdentity: CanonicalDatasetIdentity | null = null;
  if (input.activeIdentityPayload) {
    try {
      activeDatasetIdentity = requireCanonicalDatasetIdentity(
        input.activeIdentityPayload as Record<string, unknown>,
        "Authoritative project-context active dataset identity",
      );
    } catch {
      return failedAuthoritativeProjectContext({
        status: "contradictory",
        routeProjectId,
        message: "The active dataset response is missing exact canonical identifiers.",
      });
    }
    if (activeDatasetIdentity.project_id !== routeProjectId) {
      return failedAuthoritativeProjectContext({
        status: "contradictory",
        routeProjectId,
        message: "The active dataset identity belongs to a different project.",
      });
    }
  }

  const persistedIdentity = workflowDatasetIdentity(workflow);
  const activeSelection = projectActiveSelection(project);
  const hasBackendDatasetClaim = Boolean(persistedIdentity || activeSelection);
  if (!activeDatasetIdentity && (input.requireActiveIdentity || hasBackendDatasetClaim)) {
    return {
      ...failedAuthoritativeProjectContext({
        status: "identity_unavailable",
        routeProjectId,
        message: "The project names a governed dataset, but its exact active dataset identity is unavailable.",
      }),
      project: normalizedProject,
      workflowState: Object.keys(workflow).length ? workflow : null,
    };
  }

  if (activeDatasetIdentity) {
    const activeTriple = {
      projectId: activeDatasetIdentity.project_id,
      datasetId: activeDatasetIdentity.dataset_id,
      datasetVersionId: activeDatasetIdentity.dataset_version_id,
    };
    for (const subordinate of [persistedIdentity, activeSelection]) {
      if (!subordinate) continue;
      const triple = selectionTriple(subordinate);
      if (!triple || !sameTriple(activeTriple, triple)) {
        return failedAuthoritativeProjectContext({
          status: "contradictory",
          routeProjectId,
          message: "Project, workflow, and active dataset authorities identify different dataset versions.",
        });
      }
    }
  }

  const loadedAt = input.loadedAt || new Date().toISOString();
  const backendRevision = text(
    workflow.updatedAt,
    workflow.updated_at,
    activeDatasetIdentity?.activation_revision == null
      ? ""
      : String(activeDatasetIdentity.activation_revision),
  );
  return {
    status: "ready",
    routeProjectId,
    project: normalizedProject,
    workflowState: workflow,
    activeDatasetIdentity,
    backendRevision,
    loadedAt,
    message: "The exact authorized project context is ready.",
  };
}

const RESERVED_PROJECT_SEGMENTS = new Set(["new", "open"]);

/** Resolve only explicit project-scoped URLs. Unscoped /stepXX routes return null. */
export function projectIdFromScopedPathname(pathname: string): string | null {
  const match = String(pathname || "").match(/^\/projects\/([^/]+)\/(?:step(?:0[0-9]|1[0-3]|01b)|predictive(?:\/|$))/i);
  if (!match?.[1]) return null;
  try {
    const decoded = decodeURIComponent(match[1]).trim();
    return !decoded || decoded.includes("/") || RESERVED_PROJECT_SEGMENTS.has(decoded.toLowerCase())
      ? null
      : decoded;
  } catch {
    return null;
  }
}

export function stepIdFromScopedPathname(pathname: string): string | null {
  const direct = String(pathname || "").match(/^\/projects\/[^/]+\/(step(?:0[0-9]|1[0-3]|01b))(?:\/|$)/i);
  if (direct?.[1]) return direct[1].toLowerCase();
  const slug = String(pathname || "").match(/^\/projects\/[^/]+\/predictive\/([^/?#]+)/i)?.[1]?.toLowerCase();
  if (!slug) return null;
  return ({
    "project-context": "step00",
    "data-acquisition": "step01",
    eda: "step02",
    outliers: "step03",
    "missing-values": "step04",
    "feature-engineering": "step05",
    "balance-split": "step06",
    "model-training": "step07",
    evaluation: "step08",
    interpretation: "step09",
    scoring: "step10",
    "documentation-review": "step11",
    "model-implementation": "step12",
    "model-monitoring": "step13",
  } as Record<string, string>)[slug] ?? null;
}

export function scopedWorkflowPath(projectId: string, stepPath: string) {
  const step = String(stepPath || "").replace(/^\/+/, "");
  return `/projects/${encodeURIComponent(projectId)}/${step || "step00"}`;
}
