// ONE dataset action model, shared by Card View and Detailed View.
//
// PROVEN ROOT CAUSE guarded here: the Dataset Library rendered its actions as
// inline JSX in TWO independent places -- `DatasetDetailTable` (9 actions) and
// the card grid (3 actions). Nothing connected them, so the view toggle changed
// available FUNCTIONALITY rather than only presentation: a user had to switch to
// Detailed View to reach SQL Data Studio, Analytics, Chart Studio, Model
// Diagnostics, Link to Project, or Export.
//
// Both views now derive from `buildDatasetActions()`. Adding an action here adds
// it to both views; there is no second place to update.
//
// AUTHORIZATION NOTE (read this before changing `datasetCapability`):
// the capability returned here is a PRESENTATION HINT ONLY. It mirrors the
// server's `user_can_access` (server/datasets/dataset_registry.py:148-157) so the
// UI can disable an action the caller demonstrably cannot perform, instead of
// offering it and failing at the API. It is NOT authorization. The backend
// re-checks every mutation via `require_dataset(..., write=True)` and remains the
// only authority. Never widen this to *grant* anything.
import type { AtlasUser, DatasetSummary } from "./datasetLibrary";

export type DatasetActionId =
  | "open"
  | "link-project"
  | "sql-studio"
  | "analytics"
  | "chart-studio"
  | "model-diagnostics"
  | "share"
  | "export-metadata"
  | "archive";

/** Where the action appears in Card View. Detailed View renders every action. */
export type DatasetActionPlacement = "primary" | "overflow";

/** Icon identity, resolved to a component at render time so this module stays
 *  framework-free and directly testable under Node. */
export type DatasetActionIcon =
  | "open"
  | "link"
  | "sql"
  | "table"
  | "chart"
  | "diagnostics"
  | "share"
  | "download"
  | "archive";

/** Handler-backed actions name their handler; the view supplies the function. */
export type DatasetActionHandlerId = "link-project" | "share" | "export-metadata" | "archive";

export type DatasetCapability = "read" | "write";

export type DatasetAction = {
  id: DatasetActionId;
  label: string;
  icon: DatasetActionIcon;
  tooltip: string;
  accessibleLabel: string;
  placement: DatasetActionPlacement;
  destructive: boolean;
  requiresConfirmation: boolean;
  /** Present only when `requiresConfirmation` is true. */
  confirmationMessage: string | null;
  requiredCapability: DatasetCapability;
  enabled: boolean;
  /** Plain-language reason shown as the tooltip when `enabled` is false. */
  disabledReason: string | null;
  /** Navigation target, or null for handler-backed actions. */
  navigateTo: string | null;
  /** Handler identity, or null for navigation actions. */
  handlerId: DatasetActionHandlerId | null;
};

export type DatasetActionContext = {
  currentUser: AtlasUser | null;
  /** The project a "Link to Current Project" action would target. */
  currentProjectId: string | null;
  /** Injected so the model does not import the diagnostics module. */
  isScoredOutput: boolean;
  /**
   * Whether the server's project list includes `currentProjectId`.
   *
   * `false` is a PROVEN negative: the authorized `GET /api/projects` endpoint
   * filters per row, so a project absent from it is one this caller cannot
   * reach -- linking would be refused. `null` means "not determined yet", and
   * the action stays enabled so the backend can answer for itself.
   *
   * This never GRANTS anything. The server re-checks
   * `user_can_access_project(project_id, write=True)` on every link.
   */
  canAccessCurrentProject: boolean | null;
};

/** The server's own wording, mirrored so the UI explains the real reason. */
export const PROJECT_LINK_DENIED_REASON = "You do not have access to link datasets to this project.";

/**
 * Mirrors server/datasets/dataset_registry.py:148-157 `user_can_access`.
 *
 * PRESENTATION HINT ONLY -- see the module header. The server is authoritative.
 */
export function datasetCapability(dataset: DatasetSummary, user: AtlasUser | null): DatasetCapability {
  if (!user) return "read";
  if (user.role === "admin") return "write";
  if (dataset.ownerUserId && dataset.ownerUserId === user.userId) return "write";
  const grants = dataset.access ?? [];
  const writeRoles = new Set(["owner", "editor"]);
  return grants.some((grant) => grant.userId === user.userId && writeRoles.has(grant.role)) ? "write" : "read";
}

/** A dataset with no registered version has no data to open in a studio. */
function hasVersion(dataset: DatasetSummary): boolean {
  return Boolean(dataset.latestVersion?.versionId);
}

const NO_VERSION_REASON = "This dataset has no registered version yet, so there is no data to open.";
const READ_ONLY_REASON = "You have read-only access to this dataset.";
const ARCHIVED_REASON = "This dataset is already archived.";

/**
 * The complete authorized action set for one dataset and one user.
 *
 * Both views call this and render the SAME array. An action that is unavailable
 * is returned with `enabled: false` and a `disabledReason` rather than being
 * omitted, so the two views cannot drift into showing different capabilities --
 * that divergence is the defect this module exists to prevent.
 *
 * Actions that do not apply at all (Model Diagnostics on a non-scored dataset)
 * are omitted entirely, in both views equally.
 */
export function buildDatasetActions(dataset: DatasetSummary, context: DatasetActionContext): DatasetAction[] {
  const capability = datasetCapability(dataset, context.currentUser);
  const canWrite = capability === "write";
  const versioned = hasVersion(dataset);
  const archived = Boolean(dataset.archived);
  const id = dataset.datasetId;
  const name = dataset.name;

  const actions: DatasetAction[] = [];

  // --- Primary: the three actions a user reaches most often -----------------
  actions.push({
    id: "open",
    label: "Open",
    icon: "open",
    tooltip: "Open dataset",
    accessibleLabel: `Open ${name}`,
    placement: "primary",
    destructive: false,
    requiresConfirmation: false,
    confirmationMessage: null,
    requiredCapability: "read",
    enabled: true,
    disabledReason: null,
    navigateTo: `/datasets/${id}`,
    handlerId: null,
  });

  actions.push({
    id: "link-project",
    label: "Link to Project",
    icon: "link",
    tooltip: "Link to current project",
    accessibleLabel: `Link ${name} to the current project`,
    placement: "primary",
    destructive: false,
    requiresConfirmation: false,
    confirmationMessage: null,
    requiredCapability: "read",
    // Order matters: report the FIRST real blocker, most specific first.
    enabled: versioned && Boolean(context.currentProjectId) && context.canAccessCurrentProject !== false,
    disabledReason: !versioned
      ? "This dataset has no registered version to link."
      : !context.currentProjectId
        ? "No project is currently open."
        : context.canAccessCurrentProject === false
          ? PROJECT_LINK_DENIED_REASON
          : null,
    navigateTo: null,
    handlerId: "link-project",
  });

  actions.push({
    id: "sql-studio",
    label: "Open in SQL Data Studio",
    icon: "sql",
    tooltip: "Open in SQL Data Studio",
    accessibleLabel: `Open ${name} in SQL Data Studio`,
    placement: "primary",
    destructive: false,
    requiresConfirmation: false,
    confirmationMessage: null,
    requiredCapability: "read",
    enabled: versioned,
    disabledReason: versioned ? null : NO_VERSION_REASON,
    navigateTo: `/sql-data-studio?datasetId=${id}`,
    handlerId: null,
  });

  // --- Overflow: everything else, still fully labelled ----------------------
  actions.push({
    id: "analytics",
    label: "Open in Analytics",
    icon: "table",
    tooltip: "Open in Analytics",
    accessibleLabel: `Open ${name} in Analytics`,
    placement: "overflow",
    destructive: false,
    requiresConfirmation: false,
    confirmationMessage: null,
    requiredCapability: "read",
    enabled: versioned,
    disabledReason: versioned ? null : NO_VERSION_REASON,
    navigateTo: `/analytics?datasetId=${id}`,
    handlerId: null,
  });

  actions.push({
    id: "chart-studio",
    label: "Open in Chart Studio",
    icon: "chart",
    tooltip: "Open in Chart Studio",
    accessibleLabel: `Open ${name} in Chart Studio`,
    placement: "overflow",
    destructive: false,
    requiresConfirmation: false,
    confirmationMessage: null,
    requiredCapability: "read",
    enabled: versioned,
    disabledReason: versioned ? null : NO_VERSION_REASON,
    navigateTo: `/chart-studio?datasetId=${id}`,
    handlerId: null,
  });

  // Only meaningful for scored outputs -- omitted (not disabled) elsewhere,
  // matching the pre-existing Detailed View condition.
  if (context.isScoredOutput) {
    actions.push({
      id: "model-diagnostics",
      label: "Open in Model Diagnostics",
      icon: "diagnostics",
      tooltip: "Open in Model Diagnostics",
      accessibleLabel: `Open ${name} in Model Diagnostics`,
      placement: "overflow",
      destructive: false,
      requiresConfirmation: false,
      confirmationMessage: null,
      requiredCapability: "read",
      enabled: versioned,
      disabledReason: versioned ? null : NO_VERSION_REASON,
      navigateTo: `/model-diagnostics?datasetId=${id}`,
      handlerId: null,
    });
  }

  actions.push({
    id: "share",
    label: "Share",
    icon: "share",
    tooltip: "Share Dataset",
    accessibleLabel: `Share Dataset: ${name}`,
    placement: "overflow",
    destructive: false,
    requiresConfirmation: false,
    confirmationMessage: null,
    requiredCapability: "write",
    enabled: canWrite,
    disabledReason: canWrite ? null : READ_ONLY_REASON,
    navigateTo: null,
    handlerId: "share",
  });

  actions.push({
    id: "export-metadata",
    label: "Export Metadata",
    icon: "download",
    tooltip: "Export metadata",
    accessibleLabel: `Export ${name} metadata`,
    placement: "overflow",
    destructive: false,
    requiresConfirmation: false,
    confirmationMessage: null,
    requiredCapability: "read",
    enabled: true,
    disabledReason: null,
    navigateTo: null,
    handlerId: "export-metadata",
  });

  actions.push({
    id: "archive",
    label: "Archive Dataset",
    icon: "archive",
    tooltip: "Archive dataset",
    accessibleLabel: `Archive ${name}`,
    placement: "overflow",
    destructive: true,
    requiresConfirmation: true,
    // Preserved verbatim from the pre-existing confirmation so behaviour is
    // identical and both views now share the one string.
    confirmationMessage: `Delete "${name}" from the Dataset Library? ATLAS will archive the record so governance history remains intact.`,
    requiredCapability: "write",
    enabled: canWrite && !archived,
    disabledReason: archived ? ARCHIVED_REASON : canWrite ? null : READ_ONLY_REASON,
    navigateTo: null,
    handlerId: "archive",
  });

  return actions;
}

/** Card View's directly-visible actions. */
export function primaryDatasetActions(actions: DatasetAction[]): DatasetAction[] {
  return actions.filter((action) => action.placement === "primary");
}

/** Card View's "More Actions" menu contents. */
export function overflowDatasetActions(actions: DatasetAction[]): DatasetAction[] {
  return actions.filter((action) => action.placement === "overflow");
}

/** Stable identity list, used by the parity tests and by the e2e walkthrough. */
export function datasetActionIds(actions: DatasetAction[]): DatasetActionId[] {
  return actions.map((action) => action.id);
}
