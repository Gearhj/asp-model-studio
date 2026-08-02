import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  Clock3,
  Database,
  FileCheck2,
  GitCompareArrows,
  History,
  Link2,
  RefreshCw,
  ShieldCheck,
  Target,
} from "lucide-react";
import {
  EDA_DOCUMENTATION_SECTION_KEYS,
  getEdaDocumentationState,
  subscribeEdaDocumentationUpdates,
  type EdaDocumentationConfirmationSummary,
  type EdaDocumentationEvidenceReference,
  type EdaDocumentationRecord,
  type EdaDocumentationSectionKey,
  type EdaDocumentationState,
  type EdaDocumentationStatus,
} from "../../lib/edaDocumentationApi";
import { loadLocalDataset } from "../../lib/localDataset";
import { requireLocalDatasetCanonicalIdentity } from "../../lib/datasetIdentity";

const UPSTREAM_REFRESH_EVENTS = [
  "atlas-dataset-updated",
  "atlas-project-context-updated",
  "atlas-workflow-node-updated",
  "atlas-eda-code-context-updated",
] as const;

const STATUS_PRESENTATION: Record<
  EdaDocumentationStatus,
  { label: string; tone: string; icon: typeof Clock3; explanation: string }
> = {
  draft: {
    label: "Draft \u00b7 not approved",
    tone: "border-amber-200 bg-amber-50 text-amber-800",
    icon: Clock3,
    explanation:
      "EDA documentation is available as a working draft. It is not approved for the Model Development Document.",
  },
  ready_for_confirmation: {
    label: "Ready for confirmation",
    tone: "border-blue-200 bg-blue-50 text-blue-800",
    icon: FileCheck2,
    explanation:
      "The governed EDA draft is ready, but it will remain pending until EDA is confirmed.",
  },
  confirmed: {
    label: "Confirmed",
    tone: "border-emerald-200 bg-emerald-50 text-emerald-800",
    icon: CheckCircle2,
    explanation:
      "The Model Development Document is linked to the frozen, approved EDA snapshot shown below.",
  },
  stale: {
    label: "Stale after upstream change",
    tone: "border-rose-200 bg-rose-50 text-rose-800",
    icon: AlertTriangle,
    explanation:
      "The last approved EDA snapshot is preserved, but it no longer matches the active governed lineage. Reconfirmation is required.",
  },
};

const UNVERIFIED_PRESENTATION = {
  label: "Status unverified",
  tone: "border-orange-200 bg-orange-50 text-orange-900",
  icon: AlertTriangle,
  explanation:
    "ATLAS could not verify the current EDA documentation state. Content below is the last successfully loaded snapshot and must not be treated as current until refresh succeeds.",
};

type Props = {
  projectId: string;
};

export default function EdaDocumentationLiveLink({ projectId }: Props) {
  const [state, setState] = useState<EdaDocumentationState | null>(null);
  const [loading, setLoading] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState("");
  const requestRef = useRef<AbortController | null>(null);

  const refresh = useCallback(
    async (silent = false) => {
      if (!projectId) return;
      requestRef.current?.abort();
      const controller = new AbortController();
      requestRef.current = controller;
      if (silent) setRefreshing(true);
      else setLoading(true);
      try {
        const identity = requireLocalDatasetCanonicalIdentity(
          projectId,
          loadLocalDataset(),
          "EDA documentation dataset identity",
        );
        const next = await getEdaDocumentationState(
          projectId,
          identity,
          controller.signal
        );
        if (!controller.signal.aborted) {
          setState(next);
          setError("");
        }
      } catch (requestError) {
        if (
          !controller.signal.aborted &&
          !(
            requestError instanceof DOMException &&
            requestError.name === "AbortError"
          )
        ) {
          setError(
            requestError instanceof Error
              ? requestError.message
              : "ATLAS could not load the governed EDA documentation state."
          );
        }
      } finally {
        if (!controller.signal.aborted) {
          setLoading(false);
          setRefreshing(false);
        }
      }
    },
    [projectId]
  );

  useEffect(() => {
    setState(null);
    setError("");
    if (!projectId) return;
    void refresh();

    const unsubscribeDocumentationUpdates =
      subscribeEdaDocumentationUpdates((detail) => {
      if (!detail?.project_id || detail.project_id === projectId) {
        void refresh(true);
      }
      });
    const handleUpstreamUpdate = () => void refresh(true);
    const handleVisibility = () => {
      if (document.visibilityState === "visible") void refresh(true);
    };

    UPSTREAM_REFRESH_EVENTS.forEach((eventName) =>
      window.addEventListener(eventName, handleUpstreamUpdate)
    );
    document.addEventListener("visibilitychange", handleVisibility);
    const poll = window.setInterval(() => {
      if (document.visibilityState === "visible") void refresh(true);
    }, 30_000);

    return () => {
      window.clearInterval(poll);
      requestRef.current?.abort();
      unsubscribeDocumentationUpdates();
      UPSTREAM_REFRESH_EVENTS.forEach((eventName) =>
        window.removeEventListener(eventName, handleUpstreamUpdate)
      );
      document.removeEventListener("visibilitychange", handleVisibility);
    };
  }, [projectId, refresh]);

  if (!projectId) {
    return (
      <section
        className="rounded-2xl border border-dashed border-slate-300 bg-white p-5"
        data-testid="eda-documentation-live-link"
      >
        <h2 className="text-base font-semibold text-slate-950">
          EDA documentation live link
        </h2>
        <p className="mt-2 text-sm leading-6 text-slate-600">
          Select a project to review its approved EDA documentation and lineage.
        </p>
      </section>
    );
  }

  const statusUnverified = Boolean(error && state);
  const presentation = statusUnverified
    ? UNVERIFIED_PRESENTATION
    : STATUS_PRESENTATION[state?.status ?? "draft"];
  const StatusIcon = presentation.icon;
  const changedSections = state
    ? findChangedSections(state.draft, state.current_approved)
    : [];

  return (
    <section
      className="overflow-hidden rounded-2xl border border-indigo-200 bg-white shadow-sm"
      data-testid="eda-documentation-live-link"
    >
      <header className="border-b border-indigo-100 bg-gradient-to-r from-indigo-950 via-slate-950 to-slate-900 px-5 py-5 text-white">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div>
            <div className="flex items-center gap-2 text-indigo-200">
              <Link2 size={17} aria-hidden="true" />
              <span className="text-xs font-semibold uppercase tracking-[0.16em]">
                Governed live connection
              </span>
            </div>
            <h2 className="mt-2 text-xl font-semibold">
              EDA documentation live link
            </h2>
            <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-200">
              Model Development Documentation reads the canonical EDA record
              directly. Approved content is frozen; later draft changes remain
              separate until reconfirmed.
            </p>
          </div>
          <button
            type="button"
            onClick={() => void refresh(true)}
            disabled={loading || refreshing}
            className="inline-flex min-h-10 items-center justify-center gap-2 rounded-lg border border-white/20 bg-white/10 px-3 py-2 text-sm font-semibold text-white transition hover:bg-white/15 disabled:cursor-wait disabled:opacity-60"
          >
            <RefreshCw
              size={15}
              className={refreshing ? "animate-spin motion-reduce:animate-none" : ""}
              aria-hidden="true"
            />
            Refresh EDA link
          </button>
        </div>
      </header>

      <div className="space-y-5 p-5">
        {loading && !state ? (
          <div
            className="rounded-xl border border-slate-200 bg-slate-50 p-5 text-sm text-slate-600"
            role="status"
          >
            {"Loading governed EDA documentation\u2026"}
          </div>
        ) : null}

        {error ? (
          <div
            className="flex flex-col gap-3 rounded-xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-900 sm:flex-row sm:items-center sm:justify-between"
            role="alert"
          >
            <span>
              {error}
              {state
                ? " Showing the last successfully loaded snapshot with status unverified."
                : ""}
            </span>
            <button
              type="button"
              onClick={() => void refresh()}
              className="rounded-lg border border-rose-300 bg-white px-3 py-2 font-semibold"
            >
              Try again
            </button>
          </div>
        ) : null}

        {state ? (
          <>
            <div
              className={`rounded-xl border p-4 ${presentation.tone}`}
              aria-live="polite"
              data-testid="eda-documentation-status"
            >
              <div className="flex items-start gap-3">
                <StatusIcon size={20} className="mt-0.5 shrink-0" aria-hidden="true" />
                <div>
                  <div className="font-semibold">{presentation.label}</div>
                  <p className="mt-1 text-sm leading-6">
                    {presentation.explanation}
                  </p>
                </div>
              </div>
            </div>

            <LineagePanel state={state} unverified={statusUnverified} />

            <div className="grid gap-5 2xl:grid-cols-2">
              <ApprovedDocumentation
                record={state.current_approved}
                stale={state.status === "stale"}
                unverified={statusUnverified}
              />
              <DraftDocumentation
                record={state.draft}
                approved={state.current_approved}
                changedSections={changedSections}
                status={state.status}
              />
            </div>

            <ConfirmationHistory history={state.history} />
          </>
        ) : null}
      </div>
    </section>
  );
}

function LineagePanel({
  state,
  unverified,
}: {
  state: EdaDocumentationState;
  unverified: boolean;
}) {
  const lineage = state.source_lineage;
  return (
    <section
      className="rounded-xl bg-slate-950 p-4 text-white"
      aria-labelledby="eda-source-lineage-title"
    >
      <div className="flex items-center gap-2">
        <Database size={17} className="text-indigo-300" aria-hidden="true" />
        <h3 id="eda-source-lineage-title" className="text-sm font-semibold">
          {unverified ? "Last verified source lineage" : "Active source lineage"}
        </h3>
      </div>
      <dl className="mt-3 grid gap-x-5 gap-y-3 sm:grid-cols-2 xl:grid-cols-5">
        <LineageValue label="Dataset" value={lineage.dataset_id} />
        <LineageValue label="Version" value={lineage.dataset_version} />
        <LineageValue label="Target" value={lineage.target} icon={<Target size={13} />} />
        <LineageValue
          label="Predictor manifest"
          value={lineage.predictor_manifest_id}
        />
        <LineageValue label="Project" value={lineage.project_id} />
      </dl>
    </section>
  );
}

function LineageValue({
  label,
  value,
  icon,
}: {
  label: string;
  value?: string;
  icon?: React.ReactNode;
}) {
  return (
    <div className="min-w-0">
      <dt className="flex items-center gap-1 text-[11px] font-semibold uppercase tracking-wide text-slate-400">
        {icon}
        {label}
      </dt>
      <dd
        className="mt-1 truncate font-mono text-xs text-slate-100"
        title={value || "Not available"}
      >
        {value || "Not available"}
      </dd>
    </div>
  );
}

function ApprovedDocumentation({
  record,
  stale,
  unverified,
}: {
  record: EdaDocumentationRecord | null;
  stale: boolean;
  unverified: boolean;
}) {
  return (
    <section
      className="min-w-0 rounded-xl border border-emerald-200 bg-emerald-50/40 p-4"
      aria-labelledby="approved-eda-documentation-title"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <ShieldCheck
              size={18}
              className={stale ? "text-rose-700" : "text-emerald-700"}
              aria-hidden="true"
            />
            <h3
              id="approved-eda-documentation-title"
              className="text-base font-semibold text-slate-950"
            >
              Current approved EDA documentation
            </h3>
          </div>
          <p className="mt-1 text-xs leading-5 text-slate-600">
            Immutable confirmation snapshot used by the Model Development
            Document.
          </p>
        </div>
        <span
          className={`rounded-full border px-2.5 py-1 text-xs font-semibold ${
            unverified
              ? "border-orange-200 bg-orange-50 text-orange-900"
              : stale
              ? "border-rose-200 bg-rose-50 text-rose-800"
              : record
                ? "border-emerald-200 bg-emerald-100 text-emerald-800"
                : "border-slate-200 bg-white text-slate-600"
          }`}
        >
          {unverified
            ? "Snapshot \u00b7 status unverified"
            : stale
              ? "Preserved \u00b7 stale"
              : record
                ? "Approved"
                : "No approval"}
        </span>
      </div>

      {!record ? (
        <div className="mt-4 rounded-lg border border-dashed border-slate-300 bg-white p-4 text-sm leading-6 text-slate-600">
          No approved EDA snapshot exists yet. Draft content is clearly marked
          as not approved until Confirm EDA and Continue succeeds.
        </div>
      ) : (
        <>
          {stale ? (
            <div className="mt-4 rounded-lg border border-rose-200 bg-rose-50 p-3 text-sm text-rose-900">
              <div className="font-semibold">Reconfirmation required</div>
              <p className="mt-1 leading-5">
                {record.stale_reason ||
                  "The approved snapshot no longer matches the active upstream context."}
              </p>
              {record.stale_at ? (
                <p className="mt-1 text-xs">
                  Marked stale {formatDateTime(record.stale_at)}
                </p>
              ) : null}
              {record.mdd_staleness?.changed_source_fields?.length ? (
                <div className="mt-3">
                  <div className="text-xs font-semibold uppercase tracking-wide">
                    Changed source fields
                  </div>
                  <ul className="mt-1 space-y-1 text-xs">
                    {record.mdd_staleness.changed_source_fields.map((field) => (
                      <li key={field}>
                        <code>{field}</code>
                      </li>
                    ))}
                  </ul>
                  <p className="mt-2 text-xs">
                    {record.mdd_staleness.analytical_staleness
                      ? "Analytical staleness: governed source evidence changed."
                      : "Narrative-only staleness: analytical evidence remains unchanged."}
                  </p>
                </div>
              ) : null}
              <button
                type="button"
                className="mt-3 rounded-md border border-rose-300 bg-white px-3 py-2 text-xs font-semibold text-rose-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-rose-600"
                onClick={() =>
                  document
                    .getElementById("eda-documentation-draft")
                    ?.scrollIntoView({ behavior: "smooth", block: "start" })
                }
              >
                Review stale documentation
              </button>
            </div>
          ) : null}
          <RecordMetadata record={record} />
          <GovernanceSummary record={record} />
          <DocumentationSections
            record={record}
            heading="Approved section content"
          />
          <EvidenceReferences references={record.evidence_references} />
        </>
      )}
    </section>
  );
}

function DraftDocumentation({
  record,
  approved,
  changedSections,
  status,
}: {
  record: EdaDocumentationRecord | null;
  approved: EdaDocumentationRecord | null;
  changedSections: EdaDocumentationSectionKey[];
  status: EdaDocumentationStatus;
}) {
  const changedLineage = findChangedLineage(record, approved);
  return (
    <section
      id="eda-documentation-draft"
      className="min-w-0 rounded-xl border border-amber-200 bg-amber-50/40 p-4"
      aria-labelledby="draft-eda-documentation-title"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <GitCompareArrows
              size={18}
              className="text-amber-700"
              aria-hidden="true"
            />
            <h3
              id="draft-eda-documentation-title"
              className="text-base font-semibold text-slate-950"
            >
              Draft changes
            </h3>
          </div>
          <p className="mt-1 text-xs leading-5 text-slate-600">
            Live analytical content waiting for confirmation; it never silently
            replaces the approved snapshot.
          </p>
        </div>
        <span className="rounded-full border border-amber-200 bg-amber-100 px-2.5 py-1 text-xs font-semibold text-amber-900">
          Not approved
        </span>
      </div>

      {!record ? (
        <div className="mt-4 rounded-lg border border-dashed border-amber-300 bg-white p-4 text-sm leading-6 text-slate-600">
          No EDA documentation draft is available. Return to EDA to prepare the
          governed analysis for confirmation.
        </div>
      ) : (
        <>
          <div className="mt-4 rounded-lg border border-amber-200 bg-white p-3">
            <div className="text-xs font-semibold uppercase tracking-wide text-amber-800">
              Documentation impact
            </div>
            <div className="mt-1 text-sm font-semibold text-slate-950">
              {approved
                ? changedSections.length || changedLineage.length
                  ? `${changedSections.length} section change${changedSections.length === 1 ? "" : "s"} \u00b7 ${changedLineage.length} lineage change${changedLineage.length === 1 ? "" : "s"}`
                  : "No section content differences detected"
                : `${EDA_DOCUMENTATION_SECTION_KEYS.length} sections pending first approval`}
            </div>
            {changedSections.length ? (
              <div className="mt-2 flex flex-wrap gap-1.5">
                {changedSections.map((section) => (
                  <span
                    key={section}
                    className="rounded-full bg-amber-100 px-2 py-1 text-[11px] font-semibold text-amber-900"
                  >
                    {sectionLabel(section)}
                  </span>
                ))}
              </div>
            ) : null}
            {changedLineage.length ? (
              <div className="mt-2 flex flex-wrap gap-1.5">
                {changedLineage.map((field) => (
                  <span
                    key={field}
                    className="rounded-full border border-rose-200 bg-rose-50 px-2 py-1 text-[11px] font-semibold text-rose-800"
                  >
                    Lineage {"\u00b7"} {humanize(field)}
                  </span>
                ))}
              </div>
            ) : null}
            {status === "stale" ? (
              <p className="mt-2 text-xs leading-5 text-rose-800">
                The approved version remains visible for audit history, but this
                draft must be reconfirmed against the active lineage.
              </p>
            ) : null}
          </div>
          <RecordMetadata record={record} draft />
          <GovernanceSummary record={record} />
          <DocumentationSections
            record={record}
            heading="Draft section content"
            changedSections={changedSections}
          />
          <EvidenceReferences
            references={record.evidence_references}
            heading="Draft evidence references"
          />
        </>
      )}
    </section>
  );
}

function RecordMetadata({
  record,
  draft = false,
}: {
  record: EdaDocumentationRecord;
  draft?: boolean;
}) {
  const items = [
    {
      label: "Project ID",
      value: record.project_id,
      technical: true,
    },
    {
      label: "Dataset ID",
      value: record.dataset_id,
      technical: true,
    },
    {
      label: "Dataset Version",
      value: record.dataset_version,
      technical: true,
    },
    {
      label: "Target",
      value: record.target,
      technical: false,
    },
    {
      label: "Predictor manifest",
      value: record.predictor_manifest_id,
      technical: true,
    },
    {
      label: "EDA analysis",
      value: record.eda_analysis_version,
      technical: true,
    },
    {
      label: draft ? "Draft status" : "Documentation version",
      value: draft
        ? record.reviewer_status || "Not approved"
        : record.documentation_version,
      technical: !draft,
    },
    ...(!draft
      ? [
          {
            label: "Confirmation ID",
            value: record.confirmation_id,
            technical: true,
          },
        ]
      : []),
    {
      label: draft ? "Last updated" : "Confirmed",
      value: draft
        ? formatDateTime(record.updated_at || record.created_at)
        : formatDateTime(record.confirmed_at),
    },
    {
      label: draft ? "Reviewer status" : "Confirmed by",
      value: draft
        ? record.reviewer_status
        : record.confirmed_by_display_name || record.confirmed_by,
    },
  ];
  return (
    <dl className="mt-4 grid gap-2 sm:grid-cols-2">
      {items.map((item) => (
        <div key={item.label} className="rounded-lg bg-white px-3 py-2">
          <dt className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">
            {item.label}
          </dt>
          <dd
            className={`mt-1 break-words text-xs text-slate-800 ${
              item.technical ? "font-mono" : ""
            }`}
          >
            {item.value || "Not available"}
          </dd>
        </div>
      ))}
    </dl>
  );
}

function GovernanceSummary({ record }: { record: EdaDocumentationRecord }) {
  return (
    <div className="mt-4 grid gap-2 sm:grid-cols-2">
      <div className="rounded-lg border border-slate-200 bg-white p-3">
        <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">
          Target-source exclusions
        </div>
        <div className="mt-1 text-sm leading-6 text-slate-800">
          {record.target_source_exclusions?.length
            ? record.target_source_exclusions.join(", ")
            : "No exclusions recorded"}
        </div>
      </div>
      <div className="rounded-lg border border-slate-200 bg-white p-3">
        <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">
          Duplicate decision
        </div>
        <div className="mt-1 text-sm leading-6 text-slate-800">
          {record.duplicate_decision || "No duplicate decision recorded"}
        </div>
      </div>
      {record.unresolved_blocking_findings?.length ? (
        <div className="rounded-lg border border-rose-200 bg-rose-50 p-3 sm:col-span-2">
          <div className="text-[11px] font-semibold uppercase tracking-wide text-rose-700">
            Unresolved blocking findings
          </div>
          <ul className="mt-1 list-disc space-y-1 pl-4 text-sm leading-6 text-rose-900">
            {record.unresolved_blocking_findings.map((finding, index) => (
              <li key={`${finding}-${index}`}>{finding}</li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}

function DocumentationSections({
  record,
  heading,
  changedSections = [],
}: {
  record: EdaDocumentationRecord;
  heading: string;
  changedSections?: EdaDocumentationSectionKey[];
}) {
  return (
    <div className="mt-4">
      <h4 className="text-xs font-semibold uppercase tracking-wide text-slate-600">
        {heading}
      </h4>
      <div className="mt-2 space-y-2">
        {EDA_DOCUMENTATION_SECTION_KEYS.map((sectionKey, index) => (
          <details
            key={sectionKey}
            className="group rounded-lg border border-slate-200 bg-white"
            open={index === 0}
          >
            <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-3 py-2 text-sm font-semibold text-slate-900">
              <span>{sectionLabel(sectionKey)}</span>
              {changedSections.includes(sectionKey) ? (
                <span className="rounded-full bg-amber-100 px-2 py-0.5 text-[10px] uppercase tracking-wide text-amber-900">
                  Changed
                </span>
              ) : null}
            </summary>
            <div className="border-t border-slate-100 px-3 py-3">
              <DocumentationValue
                value={record.sections?.[sectionKey]}
                depth={0}
              />
            </div>
          </details>
        ))}
      </div>
    </div>
  );
}

function DocumentationValue({
  value,
  depth,
}: {
  value: unknown;
  depth: number;
}) {
  if (value === null || value === undefined || value === "") {
    return <span className="text-sm italic text-slate-500">Not documented</span>;
  }
  if (typeof value === "boolean") {
    return <span className="text-sm text-slate-800">{value ? "Yes" : "No"}</span>;
  }
  if (typeof value === "string" || typeof value === "number") {
    return (
      <span className="break-words text-sm leading-6 text-slate-800">
        {String(value)}
      </span>
    );
  }
  if (Array.isArray(value)) {
    if (!value.length) {
      return <span className="text-sm italic text-slate-500">None recorded</span>;
    }
    return (
      <ul className="space-y-1.5 pl-4 text-sm text-slate-800">
        {value.slice(0, 12).map((item, index) => (
          <li key={index} className="list-disc">
            <DocumentationValue value={item} depth={depth + 1} />
          </li>
        ))}
        {value.length > 12 ? (
          <li className="list-none text-xs text-slate-500">
            + {value.length - 12} additional item
            {value.length - 12 === 1 ? "" : "s"}
          </li>
        ) : null}
      </ul>
    );
  }
  if (typeof value === "object") {
    const entries = Object.entries(value as Record<string, unknown>);
    if (!entries.length) {
      return <span className="text-sm italic text-slate-500">None recorded</span>;
    }
    if (depth >= 2) {
      return (
        <span className="text-sm leading-6 text-slate-800">
          {entries
            .slice(0, 6)
            .map(([key, item]) => `${humanize(key)}: ${compactValue(item)}`)
            .join(" \u00b7 ")}
        </span>
      );
    }
    return (
      <dl className="space-y-2">
        {entries.slice(0, 16).map(([key, item]) => (
          <div
            key={key}
            className="grid gap-0.5 sm:grid-cols-[minmax(120px,0.4fr)_minmax(0,1fr)] sm:gap-3"
          >
            <dt className="text-xs font-semibold text-slate-500">
              {humanize(key)}
            </dt>
            <dd className="min-w-0">
              <DocumentationValue value={item} depth={depth + 1} />
            </dd>
          </div>
        ))}
      </dl>
    );
  }
  return <span className="text-sm text-slate-800">{String(value)}</span>;
}

function EvidenceReferences({
  references,
  heading = "Approved evidence links",
}: {
  references: EdaDocumentationEvidenceReference[];
  heading?: string;
}) {
  return (
    <div className="mt-4">
      <h4 className="text-xs font-semibold uppercase tracking-wide text-slate-600">
        {heading}
      </h4>
      {!references?.length ? (
        <p className="mt-2 rounded-lg border border-dashed border-slate-300 bg-white p-3 text-xs leading-5 text-slate-500">
          No evidence references were recorded for this version.
        </p>
      ) : (
        <ul className="mt-2 space-y-2">
          {references.map((reference, index) => {
            const item = reference;
            const href = evidenceCenterHref(item);
            const label = item.title || item.evidence_id || `Evidence ${index + 1}`;
            return (
              <li
                key={`${item.evidence_id || label}-${index}`}
                className="rounded-lg border border-slate-200 bg-white px-3 py-2"
              >
                <div className="flex items-start gap-2">
                  <Link2
                    size={14}
                    className="mt-0.5 shrink-0 text-indigo-700"
                    aria-hidden="true"
                  />
                  <div className="min-w-0">
                    {href ? (
                      <a
                        href={href}
                        target="_blank"
                        rel="noreferrer"
                        className="break-words text-xs font-semibold text-indigo-700 underline-offset-2 hover:underline"
                      >
                        {String(label)}
                      </a>
                    ) : (
                      <div className="break-words text-xs font-semibold text-slate-800">
                        {String(label)}
                      </div>
                    )}
                    <div className="mt-0.5 flex flex-wrap gap-x-2 text-[11px] text-slate-500">
                      {item.evidence_type ? (
                        <span>{String(item.evidence_type)}</span>
                      ) : null}
                      {item.evidence_id ? (
                        <span className="font-mono">
                          {String(item.evidence_id)}
                        </span>
                      ) : null}
                    </div>
                  </div>
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

function ConfirmationHistory({
  history,
}: {
  history: EdaDocumentationConfirmationSummary[];
}) {
  return (
    <section
      className="rounded-xl border border-slate-200 bg-slate-50 p-4"
      aria-labelledby="eda-confirmation-history-title"
    >
      <div className="flex items-center gap-2">
        <History size={17} className="text-indigo-700" aria-hidden="true" />
        <h3
          id="eda-confirmation-history-title"
          className="text-sm font-semibold text-slate-950"
        >
          EDA confirmation history
        </h3>
      </div>
      {!history?.length ? (
        <p className="mt-3 text-sm leading-6 text-slate-600">
          No EDA confirmations have been recorded for this project.
        </p>
      ) : (
        <ol className="mt-3 grid gap-3 lg:grid-cols-2 2xl:grid-cols-3">
          {history.slice(0, 12).map((item, index) => (
            <li
              key={`${item.confirmation_id}-${index}`}
              className="rounded-lg border border-slate-200 bg-white p-3"
            >
              <div className="flex items-start justify-between gap-2">
                <span className="font-mono text-xs font-semibold text-slate-900">
                  {item.documentation_version}
                </span>
                <span className="text-[10px] font-semibold uppercase tracking-wide text-slate-500">
                  {item.status || "confirmed"}
                </span>
              </div>
              <div className="mt-2 text-xs text-slate-700">
                {formatDateTime(item.confirmed_at)}
              </div>
              <div className="mt-1 text-xs text-slate-600">
                Confirmed by{" "}
                {item.confirmed_by_display_name ||
                  item.confirmed_by ||
                  "Unknown reviewer"}
              </div>
              <div
                className="mt-2 truncate font-mono text-[11px] text-slate-500"
                title={item.confirmation_id}
              >
                {item.confirmation_id}
              </div>
            </li>
          ))}
        </ol>
      )}
      {history.length > 12 ? (
        <p className="mt-3 text-xs text-slate-500">
          Showing 12 of {history.length} immutable confirmations.
        </p>
      ) : null}
    </section>
  );
}

export function findChangedSections(
  draft: EdaDocumentationRecord | null,
  approved: EdaDocumentationRecord | null
) {
  if (!draft) return [];
  if (!approved) return [...EDA_DOCUMENTATION_SECTION_KEYS];
  return EDA_DOCUMENTATION_SECTION_KEYS.filter(
    (key) =>
      stableSerialize(draft.sections?.[key]) !==
      stableSerialize(approved.sections?.[key])
  );
}

function findChangedLineage(
  draft: EdaDocumentationRecord | null,
  approved: EdaDocumentationRecord | null
) {
  if (!draft || !approved) return [];
  const keys = [
    "dataset_id",
    "dataset_version",
    "target",
    "predictor_manifest_id",
    "eda_analysis_version",
  ] as const;
  return keys.filter((key) => draft[key] !== approved[key]);
}

function stableSerialize(value: unknown): string {
  if (Array.isArray(value)) {
    return `[${value.map((item) => stableSerialize(item)).join(",")}]`;
  }
  if (value && typeof value === "object") {
    return `{${Object.entries(value as Record<string, unknown>)
      .sort(([left], [right]) => left.localeCompare(right))
      .map(([key, item]) => `${JSON.stringify(key)}:${stableSerialize(item)}`)
      .join(",")}}`;
  }
  return JSON.stringify(value) ?? "undefined";
}

function safeEvidenceHref(value: unknown) {
  if (typeof value !== "string" || !value.trim()) return "";
  const href = value.trim();
  if (href.startsWith("//") || href.startsWith("/\\")) return "";
  if (href.startsWith("/")) return href;
  try {
    const parsed = new URL(href);
    return ["http:", "https:"].includes(parsed.protocol) ? parsed.href : "";
  } catch {
    return "";
  }
}

function evidenceCenterHref(reference: EdaDocumentationEvidenceReference) {
  const evidenceId = String(reference.evidence_id || "").trim();
  if (evidenceId) {
    return `/model-evidence-center?evidenceId=${encodeURIComponent(evidenceId)}`;
  }
  return safeEvidenceHref(reference.uri);
}

function sectionLabel(key: EdaDocumentationSectionKey) {
  if (key === "stability_and_segments") return "Stability and Segments";
  return humanize(key);
}

function humanize(value: string) {
  return value
    .replace(/_/g, " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function compactValue(value: unknown) {
  if (value === null || value === undefined || value === "") return "Not documented";
  if (Array.isArray(value)) return `${value.length} item${value.length === 1 ? "" : "s"}`;
  if (typeof value === "object") return `${Object.keys(value).length} field${Object.keys(value).length === 1 ? "" : "s"}`;
  return String(value);
}

function formatDateTime(value?: string) {
  if (!value) return "Not available";
  const timestamp = new Date(value);
  if (Number.isNaN(timestamp.getTime())) return value;
  return timestamp.toLocaleString(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  });
}
