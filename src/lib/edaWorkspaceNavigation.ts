export const EDA_WORKSPACE_TABS = [
  "overview",
  "target",
  "predictors",
  "relationships",
  "stability",
  "findings",
] as const;

export type EdaWorkspaceTab = (typeof EDA_WORKSPACE_TABS)[number];

export type EdaTabBadge = {
  kind: "complete" | "review" | "unresolved" | "na" | "pending";
  label: string;
  count?: number;
};

type StorageReader = Pick<Storage, "getItem">;
type StorageWriter = Pick<Storage, "setItem">;

type FindingRecord = Record<string, unknown>;

const ELIGIBLE_FINDING_DISPOSITIONS = new Set([
  "accept",
  "accepted",
  "accepted_with_conditions",
  "reject",
  "rejected",
  "defer",
  "deferred",
  "documented",
  "no_action_required",
  "not_applicable",
]);

const INFORMATIONAL_SEVERITIES = new Set([
  "info",
  "informational",
  "not_applicable",
]);

function normalizeToken(value: unknown) {
  return String(value ?? "")
    .trim()
    .toLowerCase()
    .replace(/[\s-]+/g, "_");
}

function records(value: unknown): FindingRecord[] {
  return Array.isArray(value)
    ? value.filter(
        (item): item is FindingRecord =>
          Boolean(item) && typeof item === "object" && !Array.isArray(item),
      )
    : [];
}

function finiteCount(value: unknown): number | null {
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed >= 0
    ? Math.trunc(parsed)
    : null;
}

export function isEdaWorkspaceTab(value: unknown): value is EdaWorkspaceTab {
  return EDA_WORKSPACE_TABS.includes(value as EdaWorkspaceTab);
}

export function edaTabStorageKey(scope: {
  projectId?: string | null;
  datasetId?: string | null;
  datasetVersionId?: string | null;
}) {
  const encode = (value: string | null | undefined) =>
    encodeURIComponent(String(value ?? "unresolved").trim() || "unresolved");
  return [
    "atlas:eda:active-tab:v1",
    encode(scope.projectId),
    encode(scope.datasetId),
    encode(scope.datasetVersionId),
  ].join(":");
}

export function readEdaWorkspaceTab(input: {
  search?: string;
  storage?: StorageReader | null;
  storageKey?: string;
  fallback?: EdaWorkspaceTab;
}): EdaWorkspaceTab {
  const fallback = input.fallback ?? "overview";
  try {
    const fromRoute = new URLSearchParams(input.search ?? "").get("edaTab");
    if (isEdaWorkspaceTab(fromRoute)) return fromRoute;
  } catch {
    // A malformed query must not prevent the EDA workspace from opening.
  }
  try {
    const stored =
      input.storage && input.storageKey
        ? input.storage.getItem(input.storageKey)
        : null;
    return isEdaWorkspaceTab(stored) ? stored : fallback;
  } catch {
    return fallback;
  }
}

export function persistEdaWorkspaceTab(input: {
  tab: EdaWorkspaceTab;
  storage?: StorageWriter | null;
  storageKey?: string;
  currentUrl?: string;
}) {
  try {
    if (input.storage && input.storageKey) {
      input.storage.setItem(input.storageKey, input.tab);
    }
  } catch {
    // View persistence is helpful but never an analytical blocker.
  }
  if (!input.currentUrl) return "";
  try {
    const url = new URL(input.currentUrl, "http://atlas.local");
    url.searchParams.set("edaTab", input.tab);
    return `${url.pathname}${url.search}${url.hash}`;
  } catch {
    return "";
  }
}

export function tabForKeyboardNavigation(
  current: EdaWorkspaceTab,
  key: string,
): EdaWorkspaceTab | null {
  const currentIndex = EDA_WORKSPACE_TABS.indexOf(current);
  if (key === "Home") return EDA_WORKSPACE_TABS[0];
  if (key === "End") return EDA_WORKSPACE_TABS[EDA_WORKSPACE_TABS.length - 1];
  if (key !== "ArrowRight" && key !== "ArrowLeft") return null;
  const direction = key === "ArrowRight" ? 1 : -1;
  const nextIndex =
    (currentIndex + direction + EDA_WORKSPACE_TABS.length) %
    EDA_WORKSPACE_TABS.length;
  return EDA_WORKSPACE_TABS[nextIndex];
}

function parentFindingRows(payload: Record<string, unknown> | undefined) {
  if (!payload) return [];
  for (const key of [
    "parent_findings",
    "finding_groups",
    "required_parent_findings",
  ]) {
    const rows = records(payload[key]);
    if (rows.length) return rows;
  }
  return [];
}

function findingDisposition(
  row: FindingRecord,
  decisions: Record<string, unknown>,
) {
  const id = String(
    row.parent_finding_id ?? row.parent_id ?? row.finding_id ?? row.id ?? "",
  );
  const decision =
    id && decisions[id] && typeof decisions[id] === "object"
      ? (decisions[id] as FindingRecord)
      : {};
  return normalizeToken(
    decision.disposition ??
      decision.status ??
      row.reviewer_disposition ??
      row.disposition ??
      row.status,
  );
}

function findingDecisionRecord(
  row: FindingRecord,
  decisions: Record<string, unknown>,
) {
  const id = String(
    row.parent_finding_id ?? row.parent_id ?? row.finding_id ?? row.id ?? "",
  );
  return id && decisions[id] && typeof decisions[id] === "object"
    ? (decisions[id] as FindingRecord)
    : {};
}

function findingRequiresDisposition(row: FindingRecord) {
  if (row.requires_disposition === false || row.required === false) return false;
  const requirement = normalizeToken(row.requirement);
  if (
    requirement === "informational" ||
    requirement === "not_applicable" ||
    requirement === "no_action_required"
  ) {
    return false;
  }
  const disposition = normalizeToken(
    row.reviewer_disposition ?? row.disposition ?? row.status,
  );
  if (
    disposition === "not_applicable" ||
    disposition === "no_action_required" ||
    disposition === "documented"
  ) {
    return false;
  }
  return !INFORMATIONAL_SEVERITIES.has(
    normalizeToken(row.severity ?? row.priority ?? row.finding_type),
  );
}

export function requiredUnresolvedParentFindingCount(input: {
  payload?: Record<string, unknown>;
  decisions?: Record<string, unknown>;
  fallbackFindings?: FindingRecord[];
}) {
  const payload = input.payload ?? {};
  for (const key of [
    "required_unresolved_parent_count",
    "unresolved_required_parent_count",
    "unresolved_parent_finding_count",
  ]) {
    const explicit = finiteCount(payload[key]);
    if (explicit !== null) return explicit;
  }
  const decisions = input.decisions ?? {};
  const authoritativeParents = parentFindingRows(payload);
  const candidateRows = authoritativeParents.length
    ? authoritativeParents
    : input.fallbackFindings ?? [];
  const unresolved = new Set<string>();
  for (const [index, row] of candidateRows.entries()) {
    if (!findingRequiresDisposition(row)) continue;
    const disposition = findingDisposition(row, decisions);
    const decision = findingDecisionRecord(row, decisions);
    const rationale = String(
      decision.rationale ??
        decision.reviewer_rationale ??
        row.rationale ??
        row.reviewer_rationale ??
        "",
    ).trim();
    const requiresRationale =
      normalizeToken(row.requirement) === "blocker" ||
      normalizeToken(row.severity ?? row.priority) === "high" ||
      disposition === "rejected" ||
      disposition === "deferred";
    if (
      ELIGIBLE_FINDING_DISPOSITIONS.has(disposition) &&
      (!requiresRationale || Boolean(rationale))
    ) {
      continue;
    }
    unresolved.add(
      String(
        row.parent_finding_id ??
          row.parent_id ??
          row.finding_id ??
          row.id ??
          `fallback-${index}`,
      ),
    );
  }
  return unresolved.size;
}

function explicitReviewCount(payload: Record<string, unknown> | undefined) {
  if (!payload) return 0;
  for (const value of [
    payload.required_review_count,
    payload.review_count,
    (payload.summary as FindingRecord | undefined)?.review_count,
  ]) {
    const parsed = finiteCount(value);
    if (parsed !== null) return parsed;
  }
  return 0;
}

export function buildEdaTabBadges(input: {
  loadedTabs: Iterable<EdaWorkspaceTab>;
  sectionPayloads?: Partial<Record<EdaWorkspaceTab, Record<string, unknown>>>;
  unresolvedParentFindings: number;
  governedFieldAvailabilityKnown: boolean;
  hasGovernedTimeFields: boolean;
  hasGovernedSegmentFields: boolean;
}): Record<EdaWorkspaceTab, EdaTabBadge> {
  const loaded = new Set(input.loadedTabs);
  const payloads = input.sectionPayloads ?? {};
  const badge = (tab: EdaWorkspaceTab): EdaTabBadge => {
    if (tab === "stability") {
      if (
        input.governedFieldAvailabilityKnown &&
        !input.hasGovernedTimeFields &&
        !input.hasGovernedSegmentFields
      ) {
        return { kind: "na", label: "N/A" };
      }
    }
    if (tab === "findings") {
      if (input.unresolvedParentFindings > 0) {
        return {
          kind: "unresolved",
          label: `${input.unresolvedParentFindings} unresolved`,
          count: input.unresolvedParentFindings,
        };
      }
      return loaded.has(tab)
        ? { kind: "complete", label: "Complete" }
        : { kind: "pending", label: "Pending" };
    }
    const reviewCount = explicitReviewCount(payloads[tab]);
    if (reviewCount > 0) {
      return {
        kind: "review",
        label: `${reviewCount} review`,
        count: reviewCount,
      };
    }
    return loaded.has(tab)
      ? { kind: "complete", label: "Complete" }
      : { kind: "pending", label: "Pending" };
  };
  return Object.fromEntries(
    EDA_WORKSPACE_TABS.map((tab) => [tab, badge(tab)]),
  ) as Record<EdaWorkspaceTab, EdaTabBadge>;
}

export type EdaCompletionBlocker = {
  id: string;
  message: string;
  destination?: EdaWorkspaceTab;
};

export function isEdaOverallStatusEligible(value: unknown) {
  const status = normalizeToken(value);
  return status === "accepted" || status === "accepted_with_conditions";
}

export function summarizeEdaCompletionBlockers(
  blockers: EdaCompletionBlocker[],
) {
  if (!blockers.length) {
    return {
      text: "All required findings have governed dispositions. EDA is ready to confirm.",
      destination: undefined,
      count: 0,
    };
  }
  if (blockers.length === 1) {
    return {
      text: blockers[0].message,
      destination: blockers[0].destination,
      count: 1,
    };
  }
  const findingsBlocker = blockers.find(
    (blocker) => blocker.id === "required-parent-findings",
  );
  return {
    text: `${blockers.length} completion requirements remain. ${blockers
      .slice(0, 2)
      .map((blocker) => blocker.message)
      .join(" ")}`,
    destination: findingsBlocker?.destination ?? blockers[0].destination,
    count: blockers.length,
  };
}
