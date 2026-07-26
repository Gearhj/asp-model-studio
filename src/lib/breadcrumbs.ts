// Route-derived breadcrumbs.
//
// Root cause this replaces (ModelingApp.tsx:80):
//
//   const currentStep = workflowSteps.find(
//     (step) => step.status !== "complete" && step.status !== "skipped"
//   ) ?? workflowSteps[workflowSteps.length - 1];
//
// The trail's last segment was the first INCOMPLETE workflow step, not the page
// the user was on. Once Project Context and Data Acquisition were marked
// complete, "current step" resolved to EDA, so Open Project, Project Context,
// and Data Acquisition all displayed ".../ EDA". The eyebrow above it was the
// literal placeholder string "ATLAS / Current Project / Current Workflow".
//
// Breadcrumbs are now a pure function of the ACTIVE ROUTE plus project identity.
// Workflow completion state is never consulted.

export type Crumb = {
  label: string;
  href?: string;
  /** The page the user is actually on. Rendered with aria-current="page". */
  current?: boolean;
};

/** Route -> user-facing page name. Implementation route names (step00, step01)
 *  are never displayed. */
const ROUTE_LABELS: Record<string, string> = {
  "/dashboard": "Atlas Home",
  "/projects/open": "Open Project",
  "/projects/new": "New Project",
  "/step00": "Project Context",
  "/step01": "Data Acquisition",
  "/step01b": "Credit Bureau Data Review",
  "/step02": "Exploratory Data Analysis",
  "/step03": "Outliers",
  "/step04": "Missing Values",
  "/step05": "Feature Engineering",
  "/step06": "Balance & Split",
  "/step07": "Model Training",
  "/step08": "Evaluation",
  "/step09": "Interpretation",
  "/step10": "Scoring",
  "/step11": "Model Development Document",
  "/journal": "Decision Journal",
  "/experiments": "Experiment Comparison",
  "/governance-report": "Governance Report",
  "/datasets": "Dataset Library",
  "/settings": "Settings",
  "/exports": "Exports",
};

/** Routes that belong to the project workflow rather than to project management. */
const WORKFLOW_ROUTE = /^\/step\d+/;

/** Project-management routes: these are NOT inside a project's workflow, so they
 *  must not display a project name or a workflow segment. */
const PROJECT_MANAGEMENT_ROUTES = new Set(["/projects/open", "/projects/new", "/dashboard"]);

export function routePageLabel(pathname: string): string {
  if (ROUTE_LABELS[pathname]) return ROUTE_LABELS[pathname];
  // Longest-prefix match so nested routes still resolve to their page.
  const match = Object.keys(ROUTE_LABELS)
    .filter((route) => pathname.startsWith(route))
    .sort((a, b) => b.length - a.length)[0];
  return match ? ROUTE_LABELS[match] : "Workflow";
}

/**
 * Builds the breadcrumb trail for the active route.
 *
 * @param pathname   the ACTIVE route -- the only thing that decides the page.
 * @param projectName current project identity, preserved across the workflow.
 * @param workflowLabel human-readable workflow name (e.g. "Predictive Modeling").
 */
export function buildBreadcrumbs(input: {
  pathname: string;
  projectName?: string | null;
  workflowLabel?: string | null;
}): Crumb[] {
  const pathname = input.pathname || "/";
  const page = routePageLabel(pathname);

  if (PROJECT_MANAGEMENT_ROUTES.has(pathname)) {
    // ATLAS / Projects / Open Project -- no project or workflow segment,
    // because the user has not entered a project's workflow yet.
    if (pathname === "/dashboard") {
      return [{ label: "ATLAS", href: "/dashboard" }, { label: page, current: true }];
    }
    return [
      { label: "ATLAS", href: "/dashboard" },
      { label: "Projects" },
      { label: page, current: true },
    ];
  }

  const projectName = (input.projectName || "").trim();
  const workflowLabel = (input.workflowLabel || "").trim();
  const trail: Crumb[] = [{ label: "ATLAS", href: "/dashboard" }];
  if (projectName) trail.push({ label: projectName });
  if (WORKFLOW_ROUTE.test(pathname) && workflowLabel) trail.push({ label: workflowLabel });
  trail.push({ label: page, current: true });
  return trail;
}

/** Plain-text rendering, used by tests and the accessible label. */
export function breadcrumbText(crumbs: Crumb[]): string {
  return crumbs.map((crumb) => crumb.label).join(" / ");
}
