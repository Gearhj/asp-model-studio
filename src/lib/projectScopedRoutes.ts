import {
  projectIdFromScopedPathname,
  scopedWorkflowPath,
  stepIdFromScopedPathname,
} from "./authoritativeProjectContext";

const PREDICTIVE_STEP_ID = /^step(?:0[0-9]|1[0-3])$/i;
const PREDICTIVE_COMPATIBILITY_STEP_ID = /^step01b$/i;
const UNTITLED_PROJECT_NAME = "untitled atlas project";

function pathnameAndSuffix(value: string) {
  const target = String(value || "").trim();
  const suffixIndex = target.search(/[?#]/);
  return suffixIndex < 0
    ? { pathname: target, suffix: "" }
    : { pathname: target.slice(0, suffixIndex), suffix: target.slice(suffixIndex) };
}

function directWorkflowStepId(pathname: string): string | null {
  const match = String(pathname || "").match(/^\/?(step(?:0[0-9]|1[0-3])|step01b)\/?$/i);
  return match?.[1]?.toLowerCase() ?? null;
}

/**
 * Return the canonical, project-relative workflow route for either a legacy
 * `/stepXX` URL or a project-scoped URL. Non-workflow paths are unchanged.
 */
export function normalizeWorkflowRoute(pathname: string): string {
  const pathOnly = pathnameAndSuffix(pathname).pathname || "/";
  const scopedStep = stepIdFromScopedPathname(pathOnly)
    ?? String(pathOnly).match(/^\/projects\/[^/]+\/(step01b)(?:\/|$)/i)?.[1]?.toLowerCase()
    ?? null;
  const stepId = scopedStep ?? directWorkflowStepId(pathOnly);
  return stepId ? `/${stepId}` : pathOnly;
}

export function workflowStepIdFromPathname(pathname: string): string | null {
  const normalized = normalizeWorkflowRoute(pathname).replace(/^\//, "");
  return PREDICTIVE_STEP_ID.test(normalized) || PREDICTIVE_COMPATIBILITY_STEP_ID.test(normalized)
    ? normalized.toLowerCase()
    : null;
}

export function isPredictiveWorkflowPath(pathname: string): boolean {
  return workflowStepIdFromPathname(pathname) !== null;
}

/** Scope only Predictive Modeling workflow targets; preserve query/hash. */
export function projectWorkflowRoute(projectId: string, targetPath: string): string {
  const { pathname, suffix } = pathnameAndSuffix(targetPath);
  const stepId = workflowStepIdFromPathname(pathname);
  if (!stepId) return targetPath;
  return `${scopedWorkflowPath(projectId, `/${stepId}`)}${suffix}`;
}

/**
 * Browser state may nominate one exact legacy-route candidate, but it may not
 * manufacture authority from the default Untitled project.
 */
export function hasExactLegacyProjectCandidate(input: {
  projectId?: string | null;
  projectName?: string | null;
  projectType?: string | null;
}): boolean {
  const projectId = String(input.projectId || "").trim();
  const projectName = String(input.projectName || "").trim();
  return Boolean(
    projectId
    && projectName
    && projectName.toLowerCase() !== UNTITLED_PROJECT_NAME
    && (!input.projectType || input.projectType === "predictive-modeling"),
  );
}

/**
 * Resolve a workflow navigation target without ever selecting a project from a
 * list. An explicit route project wins; otherwise the one exact current-store
 * candidate may be used for legacy compatibility.
 */
export function projectWorkflowNavigationPath(input: {
  targetPath: string;
  routeProjectId?: string | null;
  projectId?: string | null;
  projectName?: string | null;
  projectType?: string | null;
  fallbackPath?: string;
}): string {
  if (!isPredictiveWorkflowPath(input.targetPath)) return input.targetPath;
  const routeProjectId = String(input.routeProjectId || "").trim();
  if (routeProjectId) return projectWorkflowRoute(routeProjectId, input.targetPath);
  if (hasExactLegacyProjectCandidate(input)) {
    return projectWorkflowRoute(String(input.projectId), input.targetPath);
  }
  return input.fallbackPath || "/projects/open";
}

export function scopedProjectIdForPathname(pathname: string): string | null {
  const authoritativeProjectId = projectIdFromScopedPathname(pathname);
  if (authoritativeProjectId) return authoritativeProjectId;
  const compatibilityMatch = String(pathname || "").match(
    /^\/projects\/([^/]+)\/step01b(?:\/|$)/i,
  );
  if (!compatibilityMatch?.[1]) return null;
  try {
    const decoded = decodeURIComponent(compatibilityMatch[1]).trim();
    return decoded && !decoded.includes("/") && !["new", "open"].includes(decoded.toLowerCase())
      ? decoded
      : null;
  } catch {
    return null;
  }
}
