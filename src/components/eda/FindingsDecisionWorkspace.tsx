import React, { useMemo, useState } from "react";
import {
  AlertTriangle,
  ArrowDownUp,
  CheckCircle2,
  ChevronRight,
  ClipboardCheck,
  FileClock,
  FileSearch,
  Filter,
  GitBranch,
  Info,
  ListChecks,
  Save,
  Search,
  ShieldCheck,
  Sparkles,
  XCircle,
} from "lucide-react";
import {
  AtlasAttentionPanel,
  AtlasWorkflowSection,
} from "../ui/AtlasWorkflow";
import { logDecision } from "../../lib/decisionJournal";
import {
  EDA_CARRY_FORWARD_DESTINATIONS,
  EDA_FINDING_CATEGORIES,
  EDA_FINDING_SEVERITIES,
  generateEdaFindings,
  resolveFindingDecision,
  type EdaCarryForwardDestination,
  type EdaFinding,
  type EdaFindingCategory,
  type EdaFindingDecision,
  type EdaFindingDisposition,
  type EdaFindingSections,
  type EdaFindingSeverity,
  type EdaFindingsReviewState,
  type EdaTransformationOption,
} from "../../lib/edaFindings";
import {
  applyBulkParentDisposition,
  buildOptionalReviewerDraft,
  decisionRequiresRationale,
  evaluateFindingsCompletionEligibility,
  generateEdaParentFindings,
  resolveParentFindingDecision,
  summarizeFindingGovernance,
  type EdaParentFinding,
} from "../../lib/edaFindingGovernance";

type FindingStatusFilter = "all" | EdaFindingDisposition;
type FindingSort =
  | "importance"
  | "severity"
  | "category"
  | "variable";

export type FindingsDecisionWorkspaceProps = {
  sections: EdaFindingSections;
  state: EdaFindingsReviewState;
  onChange: (next: EdaFindingsReviewState) => void;
  onSave: () => void;
  message?: string;
  reviewerDisplayName?: string;
  documentationStatus?: "draft" | "ready_for_confirmation" | "confirmed" | "stale";
  "data-testid"?: string;
};

const severityOrder: Record<EdaFindingSeverity, number> = {
  high: 3,
  moderate: 2,
  info: 1,
};

const severityStyles: Record<EdaFindingSeverity, string> = {
  high: "border-rose-200 bg-rose-50 text-rose-800",
  moderate: "border-amber-200 bg-amber-50 text-amber-800",
  info: "border-blue-200 bg-blue-50 text-blue-800",
};

const dispositionStyles: Record<EdaFindingDisposition, string> = {
  unresolved: "border-slate-200 bg-slate-100 text-slate-700",
  accepted: "border-emerald-200 bg-emerald-50 text-emerald-800",
  rejected: "border-rose-200 bg-rose-50 text-rose-800",
  deferred: "border-amber-200 bg-amber-50 text-amber-800",
  documented: "border-blue-200 bg-blue-50 text-blue-800",
  no_action_required: "border-cyan-200 bg-cyan-50 text-cyan-800",
  not_applicable: "border-violet-200 bg-violet-50 text-violet-800",
};

function normalized(value: string) {
  return value.trim().toLowerCase();
}

function FindingBadge({
  children,
  className,
}: {
  children: React.ReactNode;
  className: string;
}) {
  return (
    <span
      className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] font-semibold ${className}`}
    >
      {children}
    </span>
  );
}

function SummaryMetric({
  label,
  value,
  tone,
}: {
  label: string;
  value: number;
  tone: "slate" | "rose" | "amber" | "emerald" | "blue";
}) {
  const tones = {
    slate: "border-slate-200 bg-white text-slate-950",
    rose: "border-rose-200 bg-rose-50 text-rose-950",
    amber: "border-amber-200 bg-amber-50 text-amber-950",
    emerald: "border-emerald-200 bg-emerald-50 text-emerald-950",
    blue: "border-blue-200 bg-blue-50 text-blue-950",
  };
  return (
    <div className={`rounded-lg border px-3 py-2.5 ${tones[tone]}`}>
      <div className="text-[11px] font-semibold uppercase tracking-wide opacity-70">
        {label}
      </div>
      <div className="mt-1 text-xl font-bold tabular-nums">
        {value.toLocaleString()}
      </div>
    </div>
  );
}

function dispositionIcon(disposition: EdaFindingDisposition) {
  if (disposition === "accepted") {
    return <CheckCircle2 size={14} aria-hidden="true" />;
  }
  if (disposition === "rejected") {
    return <XCircle size={14} aria-hidden="true" />;
  }
  return <FileClock size={14} aria-hidden="true" />;
}

function findingMatches(
  item: EdaFinding,
  decision: EdaFindingDecision,
  search: string,
  category: "all" | EdaFindingCategory,
  severity: "all" | EdaFindingSeverity,
  status: FindingStatusFilter,
) {
  const term = normalized(search);
  const haystack = normalized(
    [
      item.title,
      item.category,
      item.affectedVariables.join(" "),
      item.metricLabel,
      item.metricValue,
      item.analyticalBasis,
    ].join(" "),
  );
  return (
    (!term || haystack.includes(term)) &&
    (category === "all" || item.category === category) &&
    (severity === "all" || item.severity === severity) &&
    (status === "all" || decision.disposition === status)
  );
}

function sortFindings(
  left: EdaFinding,
  right: EdaFinding,
  sort: FindingSort,
) {
  if (sort === "severity") {
    return (
      severityOrder[right.severity] - severityOrder[left.severity] ||
      right.importance - left.importance
    );
  }
  if (sort === "category") {
    return (
      left.category.localeCompare(right.category) ||
      right.importance - left.importance
    );
  }
  if (sort === "variable") {
    return (
      (left.affectedVariables[0] ?? "~").localeCompare(
        right.affectedVariables[0] ?? "~",
      ) || right.importance - left.importance
    );
  }
  return (
    right.importance - left.importance ||
    left.title.localeCompare(right.title)
  );
}

function FindingDetail({
  item,
  decision,
  onDecision,
}: {
  item: EdaFinding;
  decision: EdaFindingDecision;
  onDecision: (next: EdaFindingDecision) => void;
}) {
  const isHighIv = item.iv !== undefined && item.iv !== null && item.iv >= 0.5;
  return (
    <div
      className="rounded-xl border border-slate-200 bg-white shadow-sm"
      data-testid="eda-finding-detail"
      data-finding-id={item.id}
    >
      <div className="border-b border-slate-200 px-4 py-3">
        <div className="flex flex-wrap items-center gap-2">
          <FindingBadge className={severityStyles[item.severity]}>
            {item.severity}
          </FindingBadge>
          <FindingBadge className="border-slate-200 bg-slate-50 text-slate-700">
            {item.category}
          </FindingBadge>
          <FindingBadge className={dispositionStyles[decision.disposition]}>
            {dispositionIcon(decision.disposition)}
            <span className="ml-1">{decision.disposition}</span>
          </FindingBadge>
        </div>
        <h3 className="mt-2 text-lg font-bold leading-6 text-slate-950">
          {item.title}
        </h3>
        {item.affectedVariables.length ? (
          <div className="mt-2 flex flex-wrap gap-1.5" aria-label="Affected variables">
            {item.affectedVariables.map((variable) => (
              <code
                key={variable}
                className="rounded bg-slate-100 px-1.5 py-0.5 text-xs font-semibold text-slate-800"
              >
                {variable}
              </code>
            ))}
          </div>
        ) : (
          <p className="mt-2 text-xs text-slate-500">
            Population-level finding; no single variable is implied.
          </p>
        )}
      </div>

      <div className="space-y-4 p-4">
        {isHighIv ? (
          <div
            className="rounded-lg border border-violet-200 bg-violet-50 p-3"
            data-testid="eda-high-iv-review-signal"
          >
            <div className="flex items-center gap-2 text-sm font-bold text-violet-950">
              <ShieldCheck size={16} aria-hidden="true" />
              High IV is a review signal—not automatic leakage
            </div>
            <dl className="mt-3 grid gap-2 text-xs sm:grid-cols-2">
              <div>
                <dt className="font-semibold text-violet-700">IV</dt>
                <dd className="mt-0.5 text-violet-950">
                  {item.iv?.toLocaleString(undefined, {
                    maximumFractionDigits: 3,
                  })}
                </dd>
              </div>
              <div>
                <dt className="font-semibold text-violet-700">
                  Target-source status
                </dt>
                <dd className="mt-0.5 text-violet-950">
                  {item.targetSourceStatus === "not_target_source"
                    ? "Not a governed target source"
                    : item.targetSourceStatus ?? "Review"}
                </dd>
              </div>
              <div>
                <dt className="font-semibold text-violet-700">
                  Event-rate shape
                </dt>
                <dd className="mt-0.5 text-violet-950">
                  {item.eventRateShape ?? "Not available"}
                </dd>
              </div>
              <div>
                <dt className="font-semibold text-violet-700">Monotonicity</dt>
                <dd className="mt-0.5 text-violet-950">
                  {item.monotonicity ?? "Not classified"}
                </dd>
              </div>
            </dl>
            <p className="mt-2 text-xs leading-5 text-violet-900">
              <strong>Leakage evidence:</strong>{" "}
              {item.leakageEvidence ??
                "No deterministic leakage evidence is present in this finding."}
            </p>
          </div>
        ) : null}

        <dl className="grid gap-3 text-sm sm:grid-cols-2">
          <div className="rounded-lg border border-slate-200 bg-slate-50 p-3 sm:col-span-2">
            <dt className="text-xs font-semibold uppercase tracking-wide text-slate-500">
              Analytical basis
            </dt>
            <dd className="mt-1 leading-6 text-slate-800">
              {item.analyticalBasis}
            </dd>
          </div>
          <div className="rounded-lg border border-slate-200 p-3">
            <dt className="text-xs font-semibold uppercase tracking-wide text-slate-500">
              {item.metricLabel}
            </dt>
            <dd className="mt-1 font-bold tabular-nums text-slate-950">
              {item.metricValue}
            </dd>
          </div>
          <div className="rounded-lg border border-slate-200 p-3">
            <dt className="text-xs font-semibold uppercase tracking-wide text-slate-500">
              Suggested destination
            </dt>
            <dd className="mt-1 font-bold text-slate-950">
              {item.downstreamDestination}
            </dd>
          </div>
          <div className="rounded-lg border border-slate-200 p-3 sm:col-span-2">
            <dt className="text-xs font-semibold uppercase tracking-wide text-slate-500">
              Recommended review action
            </dt>
            <dd className="mt-1 leading-6 text-slate-800">
              {item.recommendedAction}
            </dd>
          </div>
        </dl>

        <div className="rounded-lg border border-blue-200 bg-blue-50 p-3">
          <div className="text-xs font-semibold uppercase tracking-wide text-blue-700">
            Evidence references
          </div>
          <ul className="mt-2 space-y-1 text-xs text-blue-950">
            {item.evidenceReferences.map((reference) => (
              <li key={reference} className="font-mono">
                {reference}
              </li>
            ))}
          </ul>
          <p className="mt-2 text-xs leading-5 text-blue-900">
            <strong>Documentation impact:</strong> {item.documentationImpact}
          </p>
        </div>

        <div
          className="rounded-lg border border-blue-200 bg-blue-50 p-3 text-xs leading-5 text-blue-900"
          data-child-evidence-immutable="true"
        >
          This child record is immutable analytical evidence. Record a
          disposition on its parent finding group above; child evidence cannot
          be individually accepted, rejected, deferred, or altered.
        </div>

        <div
          hidden
          aria-hidden="true"
          className="rounded-lg border border-slate-300 bg-slate-50 p-3"
          data-testid="eda-finding-review-controls"
        >
          <div className="flex items-center gap-2 text-sm font-bold text-slate-950">
            <ClipboardCheck size={16} aria-hidden="true" />
            Reviewer disposition
          </div>
          <div className="mt-3 grid gap-3 sm:grid-cols-2">
            <label>
              <span className="atlas-label">Decision</span>
              <select
                className="atlas-input mt-1"
                value={decision.disposition}
                onChange={(event) =>
                  onDecision({
                    ...decision,
                    disposition: event.target.value as EdaFindingDisposition,
                  })
                }
                data-testid="eda-finding-disposition"
              >
                <option value="unresolved">Unresolved—keep open</option>
                <option value="accepted">
                  Accept as a draft recommendation
                </option>
                <option value="rejected">Reject recommendation</option>
              </select>
            </label>
            <label>
              <span className="atlas-label">Carry-forward destination</span>
              <select
                className="atlas-input mt-1"
                value={decision.destination}
                onChange={(event) =>
                  onDecision({
                    ...decision,
                    destination: event.target
                      .value as EdaCarryForwardDestination,
                  })
                }
                data-testid="eda-finding-destination"
              >
                {EDA_CARRY_FORWARD_DESTINATIONS.map((destination) => (
                  <option key={destination} value={destination}>
                    {destination}
                  </option>
                ))}
              </select>
            </label>
            <label className="sm:col-span-2">
              <span className="atlas-label">Suggested transformation</span>
              <select
                className="atlas-input mt-1"
                value={decision.transformation}
                onChange={(event) =>
                  onDecision({
                    ...decision,
                    transformation: event.target
                      .value as EdaTransformationOption,
                  })
                }
                data-testid="eda-finding-transformation"
              >
                {item.suggestedTransformations.map((transformation) => (
                  <option key={transformation} value={transformation}>
                    {transformation}
                  </option>
                ))}
              </select>
            </label>
            <label className="sm:col-span-2">
              <span className="atlas-label">Decision rationale</span>
              <textarea
                className="atlas-input mt-1 min-h-24"
                value={decision.rationale}
                onChange={(event) =>
                  onDecision({ ...decision, rationale: event.target.value })
                }
                placeholder="Explain why this recommendation is accepted, rejected, or remains open."
                data-testid="eda-finding-rationale"
              />
            </label>
          </div>
          {decision.disposition !== "unresolved" &&
          !decision.rationale.trim() ? (
            <div
              className="mt-2 flex items-start gap-2 rounded-md border border-amber-200 bg-amber-50 px-2.5 py-2 text-xs leading-5 text-amber-900"
              role="status"
              data-testid="eda-finding-rationale-required"
            >
              <AlertTriangle
                size={14}
                className="mt-0.5 shrink-0"
                aria-hidden="true"
              />
              This disposition is recorded, but its rationale remains a
              documentation gap until completed.
            </div>
          ) : null}
          <div className="mt-3 flex items-start gap-2 text-xs leading-5 text-slate-600">
            <Info size={14} className="mt-0.5 shrink-0" aria-hidden="true" />
            Accepted items become governed draft recommendations. Findings never
            mutate values, drop fields, remove rows, or navigate into a
            downstream treatment step.
          </div>
        </div>
      </div>
    </div>
  );
}

function ParentFindingDetail({
  parent,
  decision,
  onDecision,
}: {
  parent: EdaParentFinding;
  decision: EdaFindingDecision;
  onDecision: (next: EdaFindingDecision) => void;
}) {
  const needsRationale = decisionRequiresRationale(
    parent,
    decision.disposition,
  );
  return (
    <article
      className="rounded-xl border border-slate-200 bg-white shadow-sm"
      data-testid="eda-parent-finding-detail"
      data-parent-id={parent.parentId}
      data-requirement={parent.requirement}
    >
      <header className="border-b border-slate-200 px-4 py-3">
        <div className="flex flex-wrap items-center gap-2">
          <FindingBadge className={severityStyles[parent.severity]}>
            {parent.severity}
          </FindingBadge>
          <FindingBadge className="border-slate-200 bg-slate-50 text-slate-700">
            {parent.requirement}
          </FindingBadge>
          <FindingBadge className={dispositionStyles[decision.disposition]}>
            {dispositionIcon(decision.disposition)}
            <span className="ml-1">
              {decision.disposition.replace(/_/g, " ")}
            </span>
          </FindingBadge>
        </div>
        <h3 className="mt-2 text-lg font-bold text-slate-950">
          {parent.title}
        </h3>
        <p className="mt-1 text-xs leading-5 text-slate-600">
          {parent.childIds.length} immutable analytical record
          {parent.childIds.length === 1 ? "" : "s"} grouped for one reviewer
          decision.
        </p>
      </header>

      <div className="space-y-4 p-4">
        <div
          className="rounded-lg border border-blue-200 bg-blue-50 p-3"
          data-testid="eda-parent-child-evidence"
          data-child-evidence-immutable="true"
        >
          <div className="text-xs font-semibold uppercase tracking-wide text-blue-800">
            Immutable child evidence
          </div>
          <ul className="mt-2 max-h-56 space-y-2 overflow-y-auto">
            {parent.childEvidence.map((child) => (
              <li
                key={child.id}
                className="rounded-md border border-blue-100 bg-white px-3 py-2"
              >
                <div className="text-sm font-semibold text-slate-950">
                  {child.title}
                </div>
                <div className="mt-0.5 text-xs text-slate-600">
                  {child.metricLabel}: {child.metricValue}
                  {child.affectedVariables.length
                    ? ` · ${child.affectedVariables.join(", ")}`
                    : ""}
                </div>
                <code className="mt-1 block text-[10px] text-slate-500">
                  {child.id}
                </code>
              </li>
            ))}
          </ul>
        </div>

        <div
          className="rounded-lg border border-slate-300 bg-slate-50 p-3"
          data-testid="eda-parent-finding-review-controls"
        >
          <div className="grid gap-3 sm:grid-cols-2">
            <label>
              <span className="atlas-label">Governed disposition</span>
              <select
                className="atlas-input mt-1"
                value={decision.disposition}
                onChange={(event) =>
                  onDecision({
                    ...decision,
                    disposition: event.target.value as EdaFindingDisposition,
                  })
                }
                data-testid="eda-parent-finding-disposition"
              >
                {parent.allowedDispositions.map((value) => (
                  <option key={value} value={value}>
                    {{
                      unresolved: "Keep open / unresolved",
                      accepted: "Accept",
                      rejected: "Reject",
                      deferred: "Defer",
                      documented: "Documented",
                      no_action_required: "No action required",
                      not_applicable: "Not applicable",
                    }[value]}
                  </option>
                ))}
              </select>
            </label>
            <label>
              <span className="atlas-label">
                Downstream destination (optional)
              </span>
              <select
                className="atlas-input mt-1"
                value={decision.destination}
                onChange={(event) =>
                  onDecision({
                    ...decision,
                    destination: event.target
                      .value as EdaCarryForwardDestination | "",
                  })
                }
                data-testid="eda-parent-finding-destination"
              >
                <option value="">No carry-forward destination</option>
                {EDA_CARRY_FORWARD_DESTINATIONS.map((destination) => (
                  <option key={destination} value={destination}>
                    {destination}
                  </option>
                ))}
              </select>
            </label>
            <label className="sm:col-span-2">
              <span className="atlas-label">
                Reviewer rationale{needsRationale ? " (required)" : ""}
              </span>
              <textarea
                className="atlas-input mt-1 min-h-24"
                value={decision.rationale}
                onChange={(event) =>
                  onDecision({ ...decision, rationale: event.target.value })
                }
                placeholder="Explain the governed disposition. Rejections, deferrals, blocker resolutions, high-severity acceptances, and bulk actions require rationale."
                data-testid="eda-parent-finding-rationale"
              />
            </label>
          </div>
          {needsRationale && !decision.rationale.trim() ? (
            <div
              className="mt-2 rounded-md border border-amber-200 bg-amber-50 p-2 text-xs text-amber-900"
              role="status"
              data-testid="eda-parent-rationale-required"
            >
              This disposition is not completion-eligible until rationale is
              recorded.
            </div>
          ) : null}
          <p className="mt-3 text-xs leading-5 text-slate-600">
            This decision creates documentation and, when selected, a draft
            downstream recommendation. It cannot remove rows, drop predictors,
            transform values, change the split, mutate the feature manifest, or
            navigate automatically.
          </p>
        </div>
      </div>
    </article>
  );
}

export default function FindingsDecisionWorkspace({
  sections,
  state,
  onChange,
  onSave,
  message = "",
  reviewerDisplayName,
  documentationStatus = "draft",
  "data-testid": duplicateDecisionTestId = "eda-duplicate-decision",
}: FindingsDecisionWorkspaceProps) {
  const [search, setSearch] = useState("");
  const [category, setCategory] = useState<"all" | EdaFindingCategory>("all");
  const [severity, setSeverity] = useState<"all" | EdaFindingSeverity>("all");
  const [status, setStatus] = useState<FindingStatusFilter>("all");
  const [sort, setSort] = useState<FindingSort>("importance");
  const [selectedId, setSelectedId] = useState<string>("");
  const [selectedParentId, setSelectedParentId] = useState<string>("");
  const [duplicateMessage, setDuplicateMessage] = useState("");
  const [bulkFamily, setBulkFamily] = useState("");
  const [bulkDisposition, setBulkDisposition] =
    useState<EdaFindingDisposition>("documented");
  const [bulkRationale, setBulkRationale] = useState("");
  const [bulkDestination, setBulkDestination] =
    useState<EdaCarryForwardDestination | "">("");
  const [bulkMessage, setBulkMessage] = useState("");

  const inventory = useMemo(() => generateEdaFindings(sections), [sections]);
  const parentFindings = useMemo(
    () => generateEdaParentFindings(sections),
    [sections],
  );
  const governance = useMemo(
    () => summarizeFindingGovernance(parentFindings, state),
    [parentFindings, state],
  );
  const completionEligibility = useMemo(
    () => evaluateFindingsCompletionEligibility(parentFindings, state),
    [parentFindings, state],
  );
  const filtered = useMemo(
    () =>
      inventory
        .filter((item) =>
          findingMatches(
            item,
            resolveFindingDecision(item, state),
            search,
            category,
            severity,
            status,
          ),
        )
        .sort((left, right) => sortFindings(left, right, sort)),
    [category, inventory, search, severity, sort, state, status],
  );
  const selected =
    filtered.find((item) => item.id === selectedId) ??
    filtered[0] ??
    null;
  const selectedParent =
    parentFindings.find((item) => item.parentId === selectedParentId) ??
    parentFindings[0] ??
    null;
  const duplicateFinding = inventory.find((item) =>
    item.title.toLowerCase().includes("duplicate"),
  );
  const duplicateTreatment = state.duplicateTreatment ?? "review";
  const acceptedParents = parentFindings
    .map((parent) => ({
      parent,
      decision: resolveParentFindingDecision(parent, state),
    }))
    .filter(({ decision }) =>
      ["accepted", "deferred"].includes(decision.disposition),
    );
  const latestDecisionAt = Object.values(state.findingDecisions ?? {})
    .map((decision) => decision.updatedAt ?? "")
    .filter(Boolean)
    .sort()
    .at(-1);

  function updateFindingDecision(
    item: EdaFinding,
    decision: EdaFindingDecision,
  ) {
    onChange({
      ...state,
      findingDecisions: {
        ...(state.findingDecisions ?? {}),
        [item.id]: {
          ...decision,
          updatedAt: new Date().toISOString(),
        },
      },
    });
  }

  function updateParentDecision(
    parent: EdaParentFinding,
    decision: EdaFindingDecision,
  ) {
    onChange({
      ...state,
      parentDecisions: {
        ...(state.parentDecisions ?? {}),
        [parent.parentId]: {
          ...decision,
          updatedAt: new Date().toISOString(),
        },
      },
    });
  }

  function applyBulkDisposition() {
    try {
      const next = applyBulkParentDisposition({
        parents: parentFindings,
        state,
        family: bulkFamily,
        disposition: bulkDisposition,
        rationale: bulkRationale,
        destination: bulkDestination,
        actor: reviewerDisplayName || "Authenticated reviewer",
      });
      onChange(next);
      setBulkMessage(
        `Bulk disposition recorded for ${bulkFamily.replace(/_/g, " ")}.`,
      );
    } catch (error) {
      setBulkMessage(
        error instanceof Error ? error.message : "Bulk disposition failed.",
      );
    }
  }

  function generateReviewerDraft() {
    const draft = buildOptionalReviewerDraft(parentFindings, state);
    onChange({
      ...state,
      overallConclusion: draft.overallConclusion,
      commentary: draft.commentary,
      reviewerDraftGeneratedAt: draft.generatedAt,
      reviewerDraftNonApproving: true,
    });
  }

  function saveDuplicateDecision() {
    logDecision({
      workflowStep: "Exploratory Data Analysis",
      actionType: "workflow_setting_changed",
      subject: "Duplicate row treatment",
      previousValue: "review",
      newValue: duplicateTreatment,
      systemRecommendation:
        "Confirm whether duplicate records represent repeated observations or ingestion duplication before downstream modeling.",
      userReason:
        duplicateTreatment === "exclude"
          ? "Reviewer selected duplicate-row exclusion for downstream preprocessing."
          : "Reviewer recorded duplicate-row handling decision.",
    });
    onChange({
      ...state,
      duplicateTreatment,
      duplicateDecisionSavedAt: new Date().toISOString(),
    });
    setDuplicateMessage("Duplicate-row decision recorded.");
  }

  return (
    <div
      className="space-y-4"
      data-testid="eda-findings-decision-workspace"
      data-non-mutating="true"
    >
      <AtlasWorkflowSection
        eyebrow="Governed analytical conclusions"
        title="EDA Executive Summary"
        description="ATLAS consolidates evidence already loaded across EDA. Automated signals begin as open review items; only an analyst can accept or reject a recommendation."
        tone="info"
      >
        <div
          className="grid gap-2 sm:grid-cols-2 xl:grid-cols-5"
          data-testid="eda-findings-executive-summary"
        >
          <SummaryMetric
            label="Parent findings"
            value={parentFindings.length}
            tone="slate"
          />
          <SummaryMetric
            label="Child evidence"
            value={governance.child_evidence_count}
            tone="blue"
          />
          <SummaryMetric
            label="Required unresolved"
            value={governance.unresolved_parent_finding_count}
            tone="amber"
          />
          <SummaryMetric
            label="Eligible parents"
            value={governance.eligible_parent_finding_count}
            tone="emerald"
          />
          <SummaryMetric
            label="Draft actions"
            value={acceptedParents.length}
            tone="slate"
          />
        </div>
        <div className="mt-3 flex flex-wrap items-center gap-2 text-xs text-slate-600">
          <span className="inline-flex items-center gap-1 rounded-full border border-slate-200 bg-white px-2 py-1">
            <FileSearch size={13} aria-hidden="true" />
            Evidence from {Object.keys(sections).length} loaded EDA section
            {Object.keys(sections).length === 1 ? "" : "s"}
          </span>
          <span className="inline-flex items-center gap-1 rounded-full border border-slate-200 bg-white px-2 py-1">
            <ShieldCheck size={13} aria-hidden="true" />
            Documentation: {documentationStatus.replace(/_/g, " ")}
          </span>
          <span className="inline-flex items-center gap-1 rounded-full border border-slate-200 bg-white px-2 py-1">
            <Sparkles size={13} aria-hidden="true" />
            No treatment applied
          </span>
          <span
            className={`inline-flex items-center gap-1 rounded-full border px-2 py-1 ${
              completionEligibility.eligible
                ? "border-emerald-200 bg-emerald-50 text-emerald-800"
                : "border-amber-200 bg-amber-50 text-amber-900"
            }`}
            data-testid="eda-findings-completion-eligibility"
          >
            <ListChecks size={13} aria-hidden="true" />
            {completionEligibility.eligible
              ? "All required parent findings are eligible"
              : `${completionEligibility.blockers.length} completion blocker${completionEligibility.blockers.length === 1 ? "" : "s"}`}
          </span>
        </div>
      </AtlasWorkflowSection>

      <section
        className="grid gap-4 xl:grid-cols-[minmax(320px,0.75fr)_minmax(560px,1.25fr)]"
        aria-label="Decision-oriented parent findings"
        data-testid="eda-parent-findings-workspace"
      >
        <div className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
          <div className="border-b border-slate-200 bg-slate-50 px-4 py-3">
            <h2 className="text-base font-bold text-slate-950">
              Parent Finding Groups
            </h2>
            <p className="mt-1 text-xs leading-5 text-slate-600">
              Make one governed decision per analytical family. Every child
              record remains immutable and visible for audit.
            </p>
          </div>
          <ul className="max-h-[620px] divide-y divide-slate-200 overflow-y-auto">
            {parentFindings.map((parent) => {
              const decision = resolveParentFindingDecision(parent, state);
              const active = selectedParent?.parentId === parent.parentId;
              return (
                <li key={parent.parentId}>
                  <button
                    type="button"
                    className={`w-full px-4 py-3 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-blue-600 ${
                      active ? "bg-blue-50" : "bg-white hover:bg-slate-50"
                    }`}
                    onClick={() => setSelectedParentId(parent.parentId)}
                    aria-current={active ? "true" : undefined}
                    data-parent-id={parent.parentId}
                    data-parent-family={parent.family}
                    data-parent-requirement={parent.requirement}
                    data-parent-disposition={decision.disposition}
                  >
                    <span className="flex items-start justify-between gap-3">
                      <span className="min-w-0">
                        <span className="flex flex-wrap gap-1.5">
                          <FindingBadge
                            className={dispositionStyles[decision.disposition]}
                          >
                            {decision.disposition.replace(/_/g, " ")}
                          </FindingBadge>
                          {parent.family ===
                          "stability_segments_unavailable" ? (
                            <FindingBadge className="border-violet-200 bg-violet-50 text-violet-800">
                              N/A
                            </FindingBadge>
                          ) : null}
                        </span>
                        <span className="mt-1.5 block text-sm font-bold text-slate-950">
                          {parent.title}
                        </span>
                        <span className="mt-1 block text-xs text-slate-600">
                          {parent.childIds.length} immutable child record
                          {parent.childIds.length === 1 ? "" : "s"} · {parent.requirement}
                        </span>
                      </span>
                      <ChevronRight
                        size={16}
                        className="mt-1 shrink-0 text-slate-400"
                        aria-hidden="true"
                      />
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
        </div>
        {selectedParent ? (
          <ParentFindingDetail
            parent={selectedParent}
            decision={resolveParentFindingDecision(selectedParent, state)}
            onDecision={(decision) =>
              updateParentDecision(selectedParent, decision)
            }
          />
        ) : (
          <AtlasAttentionPanel title="No parent findings are available" tone="info">
            Load governed EDA artifacts to create the decision-oriented finding
            groups.
          </AtlasAttentionPanel>
        )}
      </section>

      <AtlasWorkflowSection
        eyebrow="Controlled family action"
        title="Bulk Disposition"
        description="Apply one auditable disposition to the selected finding family. Actor, timestamp, parent IDs, child IDs, prior states, rationale, and destination are persisted in the governed completion record."
        tone="neutral"
      >
        <div
          className="grid gap-3 lg:grid-cols-[1fr_180px_1fr_1.5fr_auto] lg:items-end"
          data-testid="eda-findings-bulk-disposition"
        >
          <label>
            <span className="atlas-label">Finding family</span>
            <select
              className="atlas-input mt-1"
              value={bulkFamily}
              onChange={(event) => setBulkFamily(event.target.value)}
            >
              <option value="">Select family</option>
              {governance.finding_groups.map((group) => (
                <option key={group.family} value={group.family}>
                  {group.title} ({group.child_count})
                </option>
              ))}
            </select>
          </label>
          <label>
            <span className="atlas-label">Disposition</span>
            <select
              className="atlas-input mt-1"
              value={bulkDisposition}
              onChange={(event) =>
                setBulkDisposition(
                  event.target.value as EdaFindingDisposition,
                )
              }
            >
              <option value="accepted">Accept</option>
              <option value="rejected">Reject</option>
              <option value="deferred">Defer</option>
              <option value="documented">Documented</option>
              <option value="no_action_required">No action required</option>
              <option value="not_applicable">Not applicable</option>
            </select>
          </label>
          <label>
            <span className="atlas-label">Destination (optional)</span>
            <select
              className="atlas-input mt-1"
              value={bulkDestination}
              onChange={(event) =>
                setBulkDestination(
                  event.target.value as EdaCarryForwardDestination | "",
                )
              }
            >
              <option value="">No destination</option>
              {EDA_CARRY_FORWARD_DESTINATIONS.map((destination) => (
                <option key={destination} value={destination}>
                  {destination}
                </option>
              ))}
            </select>
          </label>
          <label>
            <span className="atlas-label">Bulk-action rationale</span>
            <input
              className="atlas-input mt-1"
              value={bulkRationale}
              onChange={(event) => setBulkRationale(event.target.value)}
              placeholder="Required for every bulk action"
            />
          </label>
          <button
            type="button"
            className="atlas-primary-button"
            onClick={applyBulkDisposition}
            disabled={!bulkFamily || !bulkRationale.trim()}
          >
            Apply to family
          </button>
        </div>
        {bulkMessage ? (
          <p className="mt-2 text-sm text-slate-700" role="status">
            {bulkMessage}
          </p>
        ) : null}
      </AtlasWorkflowSection>

      <section
        className="grid gap-4 xl:grid-cols-[minmax(360px,0.8fr)_minmax(520px,1.2fr)]"
        aria-label="Immutable child analytical evidence"
      >
        <div
          className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm"
          data-testid="eda-findings-inventory"
        >
          <div className="border-b border-slate-200 bg-slate-50 px-4 py-3">
            <div className="flex items-center justify-between gap-3">
              <div>
                <h2 className="text-base font-bold text-slate-950">
                  Findings Inventory
                </h2>
                <p
                  className="mt-0.5 text-xs text-slate-600"
                  role="status"
                  aria-live="polite"
                >
                  Showing {filtered.length.toLocaleString()} of{" "}
                  {inventory.length.toLocaleString()}
                </p>
              </div>
              <Filter size={17} className="text-slate-500" aria-hidden="true" />
            </div>
            <label className="relative mt-3 block">
              <span className="sr-only">Search findings or variables</span>
              <Search
                size={15}
                className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-400"
                aria-hidden="true"
              />
              <input
                className="atlas-input w-full pl-9"
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                placeholder="Search finding, variable, or metric"
                data-testid="eda-findings-search"
              />
            </label>
            <div className="mt-2 grid grid-cols-2 gap-2">
              <label>
                <span className="sr-only">Filter by category</span>
                <select
                  className="atlas-input"
                  value={category}
                  onChange={(event) =>
                    setCategory(
                      event.target.value as "all" | EdaFindingCategory,
                    )
                  }
                  data-testid="eda-findings-category-filter"
                >
                  <option value="all">All categories</option>
                  {EDA_FINDING_CATEGORIES.map((item) => (
                    <option key={item} value={item}>
                      {item}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                <span className="sr-only">Filter by severity</span>
                <select
                  className="atlas-input"
                  value={severity}
                  onChange={(event) =>
                    setSeverity(
                      event.target.value as "all" | EdaFindingSeverity,
                    )
                  }
                  data-testid="eda-findings-severity-filter"
                >
                  <option value="all">All severity</option>
                  {EDA_FINDING_SEVERITIES.map((item) => (
                    <option key={item} value={item}>
                      {item[0].toUpperCase()}
                      {item.slice(1)}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                <span className="sr-only">Filter by review status</span>
                <select
                  className="atlas-input"
                  value={status}
                  onChange={(event) =>
                    setStatus(event.target.value as FindingStatusFilter)
                  }
                  data-testid="eda-findings-status-filter"
                >
                  <option value="all">All status</option>
                  <option value="unresolved">Unresolved</option>
                  <option value="accepted">Accepted</option>
                  <option value="rejected">Rejected</option>
                </select>
              </label>
              <label className="relative">
                <span className="sr-only">Sort findings</span>
                <ArrowDownUp
                  size={14}
                  className="pointer-events-none absolute left-3 top-1/2 z-10 -translate-y-1/2 text-slate-400"
                  aria-hidden="true"
                />
                <select
                  className="atlas-input pl-8"
                  value={sort}
                  onChange={(event) =>
                    setSort(event.target.value as FindingSort)
                  }
                  data-testid="eda-findings-sort"
                >
                  <option value="importance">Importance</option>
                  <option value="severity">Severity</option>
                  <option value="category">Category</option>
                  <option value="variable">Variable</option>
                </select>
              </label>
            </div>
          </div>

          <div className="max-h-[760px] overflow-y-auto">
            {filtered.length ? (
              <ul className="divide-y divide-slate-200">
                {filtered.map((item) => {
                  const decision = resolveFindingDecision(item, state);
                  const active = selected?.id === item.id;
                  return (
                    <li key={item.id}>
                      <button
                        type="button"
                        className={`w-full px-4 py-3 text-left transition-colors motion-reduce:transition-none focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-blue-600 ${
                          active
                            ? "bg-blue-50"
                            : "bg-white hover:bg-slate-50"
                        }`}
                        onClick={() => setSelectedId(item.id)}
                        aria-current={active ? "true" : undefined}
                        data-finding-id={item.id}
                        data-finding-category={item.category}
                        data-finding-severity={item.severity}
                        data-finding-disposition={decision.disposition}
                      >
                        <span className="flex items-start justify-between gap-3">
                          <span className="min-w-0">
                            <span className="flex flex-wrap items-center gap-1.5">
                              <FindingBadge
                                className={severityStyles[item.severity]}
                              >
                                {item.severity}
                              </FindingBadge>
                              <FindingBadge
                                className={
                                  dispositionStyles[decision.disposition]
                                }
                              >
                                {decision.disposition}
                              </FindingBadge>
                            </span>
                            <span className="mt-1.5 block text-sm font-bold leading-5 text-slate-950">
                              {item.title}
                            </span>
                            <span className="mt-1 block truncate text-xs text-slate-600">
                              {item.affectedVariables.length
                                ? item.affectedVariables.join(", ")
                                : item.category}
                              {" · "}
                              {item.metricLabel}: {item.metricValue}
                            </span>
                          </span>
                          <ChevronRight
                            size={16}
                            className={`mt-1 shrink-0 ${
                              active ? "text-blue-700" : "text-slate-400"
                            }`}
                            aria-hidden="true"
                          />
                        </span>
                      </button>
                    </li>
                  );
                })}
              </ul>
            ) : (
              <div className="p-6 text-center">
                <FileSearch
                  size={24}
                  className="mx-auto text-slate-400"
                  aria-hidden="true"
                />
                <p className="mt-2 text-sm font-semibold text-slate-800">
                  No findings match these filters
                </p>
                <button
                  type="button"
                  className="mt-2 text-xs font-semibold text-blue-700 underline-offset-2 hover:underline"
                  onClick={() => {
                    setSearch("");
                    setCategory("all");
                    setSeverity("all");
                    setStatus("all");
                  }}
                >
                  Clear filters
                </button>
              </div>
            )}
          </div>
        </div>

        {selected ? (
          <FindingDetail
            item={selected}
            decision={resolveFindingDecision(selected, state)}
            onDecision={(decision) =>
              updateFindingDecision(selected, decision)
            }
          />
        ) : (
          <AtlasAttentionPanel title="No governed findings are available" tone="info">
            Open the relevant EDA analysis tabs first. ATLAS creates this
            inventory only from sections that have returned governed aggregate
            evidence.
          </AtlasAttentionPanel>
        )}
      </section>

      <div className="grid gap-4 xl:grid-cols-2">
        <AtlasWorkflowSection
          eyebrow="Analyst-controlled guidance"
          title="Suggested Transformations"
          description="Suggestions are derived from the finding’s evidence. The analyst must accept, reject, or leave each item unresolved."
          tone="neutral"
          className="h-full"
        >
          <div
            className="space-y-2"
            data-testid="eda-suggested-transformations"
          >
            {inventory
              .filter(
                (item) =>
                  item.suggestedTransformations.some(
                    (option) => option !== "No transformation",
                  ),
              )
              .slice(0, 8)
              .map((item) => {
                const decision = resolveFindingDecision(item, state);
                return (
                  <button
                    type="button"
                    key={item.id}
                    className="flex w-full items-center justify-between gap-3 rounded-lg border border-slate-200 bg-white px-3 py-2.5 text-left hover:border-blue-300 hover:bg-blue-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-600"
                    onClick={() => setSelectedId(item.id)}
                  >
                    <span className="min-w-0">
                      <span className="block truncate text-sm font-semibold text-slate-900">
                        {item.affectedVariables[0] ?? item.title}
                      </span>
                      <span className="mt-0.5 block truncate text-xs text-slate-600">
                        {decision.transformation} · {item.metricLabel}:{" "}
                        {item.metricValue}
                      </span>
                    </span>
                    <FindingBadge
                      className={dispositionStyles[decision.disposition]}
                    >
                      {decision.disposition}
                    </FindingBadge>
                  </button>
                );
              })}
            {!inventory.some((item) =>
              item.suggestedTransformations.some(
                (option) => option !== "No transformation",
              ),
            ) ? (
              <p className="text-sm text-slate-600">
                No evidence-based transformation suggestion is available from
                the loaded sections.
              </p>
            ) : null}
          </div>
        </AtlasWorkflowSection>

        <AtlasWorkflowSection
          eyebrow="Governed downstream handoff"
          title="Carry-Forward Queue"
          description="Accepted items are persisted as draft recommendations for the named destination. No transformation or dataset mutation occurs here."
          tone="info"
          className="h-full"
        >
          <div
            className="space-y-2"
            data-testid="eda-carry-forward-queue"
            data-carry-forward-mode="draft_recommendation"
            data-mutation-applied="false"
          >
            {acceptedParents.length ? (
              acceptedParents.map(({ parent, decision }) => (
                <div
                  key={parent.parentId}
                  className="rounded-lg border border-blue-200 bg-blue-50 p-3"
                >
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="text-sm font-bold text-blue-950">
                      {parent.title}
                    </div>
                    <FindingBadge className="border-blue-300 bg-white text-blue-800">
                      <GitBranch size={12} className="mr-1" aria-hidden="true" />
                      {decision.destination}
                    </FindingBadge>
                  </div>
                  <p className="mt-1 text-xs leading-5 text-blue-900">
                    {decision.disposition === "deferred"
                      ? "Deferred draft recommendation"
                      : "Draft recommendation"}
                    : {decision.transformation}.{" "}
                    {decision.rationale ||
                      "Reviewer rationale has not yet been recorded."}
                  </p>
                </div>
              ))
            ) : (
              <div className="rounded-lg border border-dashed border-slate-300 bg-slate-50 p-4 text-sm text-slate-600">
                The queue is empty. Accept an individual finding to create a
                governed draft recommendation.
              </div>
            )}
          </div>
        </AtlasWorkflowSection>
      </div>

      {duplicateFinding ? (
        <AtlasWorkflowSection
          eyebrow="Legacy workflow preserved"
          title="Duplicate Row Decision"
          description="Record how exact duplicates should be handled before downstream preprocessing and model training."
          tone="warning"
          className="eda-primary-analysis"
        >
          {/* Compatibility marker: data-testid="eda-duplicate-decision" is
              the default; Step02 may pass the same literal explicitly. */}
          <div
            data-testid={duplicateDecisionTestId}
            data-decision={duplicateTreatment}
          >
            <div className="grid gap-4 lg:grid-cols-[1fr_auto] lg:items-end">
              <label>
                <span className="atlas-label">Duplicate row action</span>
                <select
                  className="atlas-input mt-1"
                  value={duplicateTreatment}
                  onChange={(event) =>
                    onChange({
                      ...state,
                      duplicateTreatment: event.target
                        .value as NonNullable<
                        EdaFindingsReviewState["duplicateTreatment"]
                      >,
                      duplicateDecisionSavedAt: undefined,
                    })
                  }
                >
                  <option value="review">
                    Review before downstream treatment
                  </option>
                  <option value="exclude">
                    Exclude duplicate rows before downstream modeling
                  </option>
                  <option value="keep">
                    Keep duplicate rows as repeated observations
                  </option>
                </select>
                <span className="mt-1 block text-xs text-slate-600">
                  This records the EDA decision. Dataset mutation occurs only
                  through later governed preprocessing evidence.
                </span>
              </label>
              <button
                type="button"
                className="atlas-primary-button"
                onClick={saveDuplicateDecision}
              >
                Save duplicate-row decision
              </button>
            </div>
            {duplicateMessage ? (
              <div className="mt-3 text-sm font-medium text-emerald-700">
                {duplicateMessage}
              </div>
            ) : null}
          </div>
        </AtlasWorkflowSection>
      ) : null}

      <AtlasWorkflowSection
        eyebrow="Reviewer record"
        title="Conclusion and Status"
        description="Completion requires an expert conclusion, commentary, eligible required parent dispositions, and an Accepted or Accepted with Conditions status. A generated draft is optional, editable, and never approving."
        tone="neutral"
      >
        <div
          className="grid gap-4 lg:grid-cols-[1fr_1fr_240px]"
          data-testid="eda-findings-reviewer-record"
        >
          <label className="block">
            <span className="atlas-label">Overall analytical conclusion</span>
            <textarea
              className="atlas-input mt-1 min-h-28"
              value={state.overallConclusion ?? ""}
              onChange={(event) =>
                onChange({ ...state, overallConclusion: event.target.value })
              }
              placeholder="Summarize the population, target, strongest signals, constraints, and readiness."
            />
          </label>
          <label className="block">
            <span className="atlas-label">Reviewer commentary</span>
            <textarea
              className="atlas-input mt-1 min-h-28"
              value={state.commentary}
              onChange={(event) =>
                onChange({ ...state, commentary: event.target.value })
              }
              placeholder="Record exceptions, open questions, and review priorities."
            />
          </label>
          <div className="space-y-3">
            <label className="block">
              <span className="atlas-label">Overall EDA status</span>
              <select
                className="atlas-input mt-1"
                value={state.status}
                onChange={(event) =>
                  onChange({
                    ...state,
                    status: event.target
                      .value as EdaFindingsReviewState["status"],
                  })
                }
              >
                {/* "Accepted for carry-forward" was the legacy universal gate.
                    Accepted now records only the overall reviewer conclusion;
                    parent dispositions independently control carry-forward. */}
                <option value="draft">Draft</option>
                <option value="under_review">Under Review</option>
                <option value="accepted">Accepted</option>
                <option value="accepted_with_conditions">
                  Accepted with Conditions
                </option>
                <option value="rejected">Rejected</option>
              </select>
            </label>
            <dl className="rounded-lg border border-slate-200 bg-slate-50 p-3 text-xs">
              <div>
                <dt className="font-semibold text-slate-500">Reviewer</dt>
                <dd className="mt-0.5 text-slate-900">
                  {reviewerDisplayName ||
                    "Authenticated reviewer recorded at save"}
                </dd>
              </div>
              <div className="mt-2">
                <dt className="font-semibold text-slate-500">Last decision</dt>
                <dd className="mt-0.5 text-slate-900">
                  {latestDecisionAt
                    ? new Date(latestDecisionAt).toLocaleString()
                    : "No individual decision recorded"}
                </dd>
              </div>
            </dl>
          </div>
        </div>
        <div className="mt-4 grid gap-4 lg:grid-cols-2">
          <label>
            <span className="atlas-label">
              Required conditions (one per line)
            </span>
            <textarea
              className="atlas-input mt-1 min-h-20"
              value={(state.requiredConditions ?? []).join("\n")}
              onChange={(event) =>
                onChange({
                  ...state,
                  requiredConditions: event.target.value
                    .split("\n")
                    .map((value) => value.trim())
                    .filter(Boolean),
                })
              }
              placeholder="Required when status is Accepted with Conditions"
            />
          </label>
          <label>
            <span className="atlas-label">
              Open nonblocking items (one per line)
            </span>
            <textarea
              className="atlas-input mt-1 min-h-20"
              value={(state.openNonblockingItems ?? []).join("\n")}
              onChange={(event) =>
                onChange({
                  ...state,
                  openNonblockingItems: event.target.value
                    .split("\n")
                    .map((value) => value.trim())
                    .filter(Boolean),
                })
              }
              placeholder="Optional items that do not block EDA completion"
            />
          </label>
        </div>
        <div className="mt-4 flex flex-wrap items-center gap-2">
          <button
            type="button"
            className="atlas-secondary-button"
            onClick={generateReviewerDraft}
            data-testid="eda-generate-reviewer-draft"
          >
            <Sparkles size={15} aria-hidden="true" /> Generate Reviewer Draft
          </button>
          <button
            type="button"
            className="atlas-primary-button"
            onClick={onSave}
          >
            <Save size={15} aria-hidden="true" /> Save to Evidence Center
          </button>
          {state.reviewerDraftGeneratedAt ? (
            <span
              className="rounded-full border border-violet-200 bg-violet-50 px-2 py-1 text-xs font-semibold text-violet-800"
              data-generated-draft-non-approving="true"
            >
              Generated draft · editable · non-approving
            </span>
          ) : null}
          {message ? (
            <span className="text-sm text-slate-600" role="status">
              {message}
            </span>
          ) : null}
        </div>
      </AtlasWorkflowSection>

      <details className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-600">
        <summary className="cursor-pointer font-semibold text-slate-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-600">
          Roadmap: Population Selection and Eligibility Waterfall
        </summary>
        <p className="mt-2 leading-5">
          Deferred from this phase. EDA treats the registered governed dataset
          as the modeling-eligible population; no eligibility filters,
          exclusions, holdout, or out-of-time waterfall is implemented here.
        </p>
      </details>
    </div>
  );
}
