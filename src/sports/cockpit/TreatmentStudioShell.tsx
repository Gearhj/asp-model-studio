import {
  createContext,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import {
  AlertTriangle,
  Archive,
  CheckCircle2,
  ChevronDown,
  Download,
  Filter,
  History,
  Lock,
  RotateCcw,
  Save,
  Search,
  ShieldCheck,
  Sparkles,
} from "lucide-react";
import type { CurrentGoldDataReview } from "../workflow/currentGoldDataReview";
import { CockpitDrawer } from "./CockpitDrawer";
import type { ProjectEdaFilters } from "./projectEdaApi";
import type {
  GovernedPriorAuthority,
  QueryStatus,
  TreatmentKind,
  TreatmentPolicy,
  TreatmentPolicyVersion,
  TreatmentSpecificationFeature,
} from "./projectTreatmentApi";
import {
  hasCurrentTreatmentSpecificationDraft,
  useTreatmentSpecification,
} from "./projectTreatmentApi";

export function formatInteger(value: number | null | undefined): string {
  return value === null || value === undefined ? "—" : value.toLocaleString();
}
export function formatPercent(
  value: number | null | undefined,
  digits = 2,
): string {
  return value === null || value === undefined
    ? "—"
    : `${value.toFixed(digits)}%`;
}
export function formatValue(
  value: number | string | null | undefined,
  digits = 4,
): string {
  if (value === null || value === undefined || value === "") return "—";
  return typeof value === "number"
    ? value.toLocaleString(undefined, { maximumFractionDigits: digits })
    : String(value);
}

function canonicalPolicyValue(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(canonicalPolicyValue);
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value as Record<string, unknown>)
        .filter(([, item]) => item !== undefined)
        .sort(([left], [right]) => left.localeCompare(right))
        .map(([key, item]) => [key, canonicalPolicyValue(item)]),
    );
  }
  return value;
}

export function canonicalPolicySignature(value: unknown): string {
  return JSON.stringify(canonicalPolicyValue(value));
}

export function TreatmentMetric({
  label,
  value,
  detail,
  tone = "slate",
}: {
  label: string;
  value: string;
  detail: string;
  tone?: "slate" | "cyan" | "amber" | "rose" | "emerald";
}) {
  const classes = {
    slate: "border-slate-200",
    cyan: "border-cyan-200 bg-cyan-50/40",
    amber: "border-amber-200 bg-amber-50/50",
    rose: "border-rose-200 bg-rose-50/50",
    emerald: "border-emerald-200 bg-emerald-50/40",
  };
  return (
    <div className={`rounded-xl border bg-white p-3 ${classes[tone]}`}>
      <div className="text-[10px] font-semibold uppercase tracking-[0.12em] text-slate-500">
        {label}
      </div>
      <div className="mt-1 text-xl font-semibold tabular-nums text-slate-950">
        {value}
      </div>
      <div className="mt-1 text-[11px] leading-4 text-slate-500">{detail}</div>
    </div>
  );
}

function DevelopmentMultiSelect({
  label,
  values,
  options,
  onChange,
}: {
  label: string;
  values: (string | number)[];
  options: (string | number)[];
  onChange: (values: (string | number)[]) => void;
}) {
  return (
    <details className="relative rounded-lg border border-slate-200 bg-white px-3 py-2">
      <summary className="flex cursor-pointer list-none items-center gap-2 text-xs font-semibold text-slate-700">
        {label}
        <span className="ml-auto rounded-full bg-slate-100 px-2 py-0.5 text-[10px]">
          {values.length || "All"}
        </span>
        <ChevronDown size={12} />
      </summary>
      <div className="absolute left-0 z-40 mt-2 max-h-56 min-w-52 overflow-auto rounded-xl border border-slate-200 bg-white p-2 shadow-xl">
        {options.map((option) => {
          const selected = values.map(String).includes(String(option));
          return (
            <label
              key={String(option)}
              className="flex items-center gap-2 rounded px-2 py-1.5 text-xs hover:bg-slate-50"
            >
              <input
                type="checkbox"
                checked={selected}
                onChange={() =>
                  onChange(
                    selected
                      ? values.filter(
                          (value) => String(value) !== String(option),
                        )
                      : [...values, option],
                  )
                }
              />
              {String(option)}
            </label>
          );
        })}
      </div>
    </details>
  );
}

export type StudioFilterState = {
  filters: ProjectEdaFilters;
  search: string;
  family: string;
  coreScope: "" | "CORE" | "CONTEXTUAL";
  dataType: string;
  severity: string;
  includeAdvanced: boolean;
};

export function TreatmentStudioFilters({
  state,
  setState,
  families,
  dataTypes,
  severities,
  seasons,
  months,
}: {
  state: StudioFilterState;
  setState: (state: StudioFilterState) => void;
  families: string[];
  dataTypes: string[];
  severities: { value: string; label: string }[];
  seasons: number[];
  months: number[];
}) {
  const updateFilter = (name: keyof ProjectEdaFilters, value: unknown) =>
    setState({ ...state, filters: { ...state.filters, [name]: value } });
  return (
    <details
      open
      className="rounded-2xl border border-slate-200 bg-white shadow-sm"
      data-testid="stage3-treatment-filters"
    >
      <summary className="flex cursor-pointer list-none items-center gap-2 px-4 py-3 text-sm font-semibold text-slate-900">
        <Filter size={15} className="text-cyan-700" /> Development-only table
        filters
        <span className="ml-auto text-[10px] font-normal text-slate-500">
          Final OOT is not filterable
        </span>
        <ChevronDown size={14} />
      </summary>
      <div className="grid gap-2 border-t border-slate-100 p-3 sm:grid-cols-2 xl:grid-cols-6">
        <label className="relative xl:col-span-2">
          <Search
            size={13}
            className="absolute left-3 top-2.5 text-slate-400"
          />
          <input
            aria-label="Search treatment variables"
            value={state.search}
            onChange={(event) =>
              setState({ ...state, search: event.target.value })
            }
            placeholder="Search variable or definition"
            className="w-full rounded-lg border border-slate-200 py-2 pl-8 pr-3 text-xs"
          />
        </label>
        <select
          aria-label="Treatment feature family"
          value={state.family}
          onChange={(event) =>
            setState({ ...state, family: event.target.value })
          }
          className="rounded-lg border border-slate-200 px-3 py-2 text-xs"
        >
          <option value="">All feature families</option>
          {families.map((family) => (
            <option key={family}>{family}</option>
          ))}
        </select>
        <select
          aria-label="Treatment core contextual scope"
          value={state.coreScope}
          onChange={(event) =>
            setState({
              ...state,
              coreScope: event.target.value as StudioFilterState["coreScope"],
            })
          }
          className="rounded-lg border border-slate-200 px-3 py-2 text-xs"
        >
          <option value="">Core + contextual</option>
          <option value="CORE">Core Gold-48</option>
          <option value="CONTEXTUAL">Contextual candidates</option>
        </select>
        <select
          aria-label="Treatment data type"
          value={state.dataType}
          onChange={(event) =>
            setState({ ...state, dataType: event.target.value })
          }
          className="rounded-lg border border-slate-200 px-3 py-2 text-xs"
        >
          <option value="">All eligible data types</option>
          {dataTypes.map((item) => (
            <option key={item}>{item}</option>
          ))}
        </select>
        <select
          aria-label="Treatment severity"
          value={state.severity}
          onChange={(event) =>
            setState({ ...state, severity: event.target.value })
          }
          className="rounded-lg border border-slate-200 px-3 py-2 text-xs"
        >
          <option value="">All severities</option>
          {severities.map((item) => (
            <option key={item.value} value={item.value}>
              {item.label}
            </option>
          ))}
        </select>
        <DevelopmentMultiSelect
          label="Season"
          values={state.filters.seasons ?? []}
          options={seasons}
          onChange={(values) => updateFilter("seasons", values.map(Number))}
        />
        <DevelopmentMultiSelect
          label="Month"
          values={state.filters.months ?? []}
          options={months}
          onChange={(values) => updateFilter("months", values.map(Number))}
        />
        <label className="rounded-lg border border-slate-200 px-3 py-2 text-[10px] font-semibold uppercase text-slate-500">
          Start date
          <input
            type="date"
            value={state.filters.startDate ?? ""}
            max="2026-08-13"
            onChange={(event) => updateFilter("startDate", event.target.value)}
            className="mt-1 block w-full text-xs font-normal text-slate-800"
          />
        </label>
        <label className="rounded-lg border border-slate-200 px-3 py-2 text-[10px] font-semibold uppercase text-slate-500">
          End date
          <input
            type="date"
            value={state.filters.endDate ?? ""}
            max="2026-08-13"
            onChange={(event) => updateFilter("endDate", event.target.value)}
            className="mt-1 block w-full text-xs font-normal text-slate-800"
          />
        </label>
        <input
          aria-label="Treatment batting team filter"
          value={state.filters.battingTeam ?? ""}
          onChange={(event) => updateFilter("battingTeam", event.target.value)}
          placeholder="Batting team"
          className="rounded-lg border border-slate-200 px-3 py-2 text-xs"
        />
        <input
          aria-label="Treatment fielding team filter"
          value={state.filters.fieldingTeam ?? ""}
          onChange={(event) => updateFilter("fieldingTeam", event.target.value)}
          placeholder="Fielding team"
          className="rounded-lg border border-slate-200 px-3 py-2 text-xs"
        />
        <label className="flex items-center gap-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs font-semibold text-amber-900">
          <input
            type="checkbox"
            checked={state.includeAdvanced}
            onChange={(event) =>
              setState({ ...state, includeAdvanced: event.target.checked })
            }
          />
          Inspect excluded / advanced fields
        </label>
      </div>
    </details>
  );
}

export function StudioRequestState({
  status,
  error,
  retry,
  unevaluatedLabel = "ANALYSIS NOT YET RUN",
}: {
  status: QueryStatus;
  error: string | null;
  retry: () => void;
  unevaluatedLabel?: string;
}) {
  if (status === "loading" || status === "idle")
    return (
      <div className="flex min-h-44 items-center justify-center rounded-2xl border border-slate-200 bg-white p-6 text-center">
        <div>
          <div className="text-sm font-semibold text-slate-800">
            {unevaluatedLabel}
          </div>
          <p className="mt-1 text-xs text-slate-500">
            Loading the project-bound development-only diagnostic. No
            unevaluated count is represented as zero.
          </p>
        </div>
      </div>
    );
  if (status === "error")
    return (
      <div
        className="rounded-2xl border border-rose-200 bg-rose-50 p-5 text-sm text-rose-900"
        role="alert"
      >
        <AlertTriangle size={18} className="mr-2 inline" />
        <b>Unavailable.</b>{" "}
        {error || "The treatment diagnostic did not complete."}
        <button
          type="button"
          onClick={retry}
          className="ml-3 rounded-lg bg-rose-900 px-3 py-1.5 text-xs font-semibold text-white"
        >
          Retry
        </button>
      </div>
    );
  return null;
}

export function TreatmentDecisionHeader({
  kind,
  status,
  summary,
  children,
}: {
  kind: TreatmentKind;
  status: QueryStatus;
  summary: string;
  children: ReactNode;
}) {
  const notReady = status !== "ready";
  return (
    <section
      className="rounded-2xl border border-cyan-200 bg-gradient-to-br from-cyan-50 via-white to-slate-50 p-5 shadow-sm"
      data-testid={`stage3-${kind}-decision-summary`}
    >
      <div className="flex flex-wrap items-start gap-3">
        <div>
          <div className="text-[10px] font-semibold uppercase tracking-[0.15em] text-cyan-800">
            {kind === "outliers"
              ? "Outlier treatment decision"
              : "Missing-value treatment decision"}
          </div>
          <h2 className="mt-1 text-xl font-semibold text-slate-950">
            {summary}
          </h2>
          <p className="mt-1 max-w-4xl text-xs leading-5 text-slate-600">
            Development-wide values are descriptive previews. Authoritative
            preprocessing parameters are fit inside each chronological training
            fold.
          </p>
        </div>
        <span
          className={`ml-auto rounded-full border px-3 py-1 text-[10px] font-semibold ${notReady ? "border-amber-200 bg-amber-50 text-amber-900" : "border-cyan-200 bg-cyan-50 text-cyan-900"}`}
        >
          {notReady ? "NOT EVALUATED" : "DEVELOPMENT ANALYSIS READY"}
        </span>
      </div>
      <div className="mt-4">{children}</div>
      <p className="mt-3 rounded-lg border border-amber-200 bg-amber-50 p-2.5 text-xs font-semibold leading-5 text-amber-950">
        DESCRIPTIVE PREVIEW — FOLD-LOCAL VALUES WILL DIFFER. Final values are
        fit inside each chronological training fold; validation and final-OOT
        rows never fit their own treatment parameters.
      </p>
    </section>
  );
}

function VersionList({ versions }: { versions: TreatmentPolicyVersion[] }) {
  return versions.length ? (
    <div className="space-y-2">
      {versions.map((version) => (
        <article
          key={`${version.policyVersion}:${version.checksum}`}
          className="rounded-xl border border-slate-200 bg-white p-3"
        >
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-semibold text-slate-900">
              Version {version.policyVersion}
            </span>
            <span
              className={`rounded-full px-2 py-0.5 text-[9px] font-semibold ${version.status === "ADOPTED" ? "bg-emerald-100 text-emerald-800" : version.status === "SUPERSEDED" ? "bg-slate-100 text-slate-600" : "bg-amber-100 text-amber-800"}`}
            >
              {version.status}
            </span>
            <span className="ml-auto text-[10px] text-slate-500">
              {new Date(version.createdAt).toLocaleString()}
            </span>
          </div>
          <p className="mt-1 text-xs text-slate-600">
            {version.globalMethod}
            {version.globalTreatment
              ? ` · ${version.globalTreatment}`
              : ""} · {version.variableCount} variable decisions
          </p>
          <p className="mt-1 break-all font-mono text-[10px] text-slate-400">
            {version.checksum}
          </p>
          <p className="mt-1 text-xs text-slate-500">
            {version.notes || "No scientist note."}
          </p>
        </article>
      ))}
    </div>
  ) : (
    <p className="rounded-xl border border-dashed border-slate-300 p-6 text-center text-sm text-slate-500">
      No saved policy version exists.
    </p>
  );
}

export function TreatmentPolicyActions({
  kind,
  policy,
  notes,
  setNotes,
  saveStatus,
  saveError,
  adoptStatus,
  adoptError,
  hasUnsavedChanges,
  saveDraft,
  adopt,
  reset,
  compare,
  continueLabel,
  onContinue,
}: {
  kind: TreatmentKind;
  policy: TreatmentPolicy | null;
  notes: string;
  setNotes: (value: string) => void;
  saveStatus: QueryStatus;
  saveError: string | null;
  adoptStatus: QueryStatus;
  adoptError: string | null;
  hasUnsavedChanges: boolean;
  saveDraft: () => void;
  adopt: () => void;
  reset: () => void;
  compare: ReactNode;
  continueLabel: string;
  onContinue: () => void;
}) {
  const combinedSpecification = useContext(TreatmentSpecificationContext);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [compareOpen, setCompareOpen] = useState(false);
  const [confirmAdopt, setConfirmAdopt] = useState(false);
  const historyTrigger = useRef<HTMLButtonElement>(null);
  const compareTrigger = useRef<HTMLButtonElement>(null);
  const savedDraftAvailable =
    Boolean(policy?.policyId) && policy?.status === "DRAFT";
  const manualDraftReady = savedDraftAvailable && !hasUnsavedChanges;
  const canAdopt =
    manualDraftReady &&
    combinedSpecification.specificationReady &&
    combinedSpecification.canonicalCanAdopt &&
    !combinedSpecification.hasCombinedDraft;
  const continueBlocked =
    kind === "missing" &&
    (!combinedSpecification.specificationReady ||
      combinedSpecification.blockerCount === null ||
      combinedSpecification.blockerCount > 0);
  useEffect(() => {
    if (hasUnsavedChanges) setConfirmAdopt(false);
    if (combinedSpecification.hasCombinedDraft) setConfirmAdopt(false);
    if (!combinedSpecification.specificationReady) setConfirmAdopt(false);
    if (!combinedSpecification.canonicalCanAdopt) setConfirmAdopt(false);
  }, [
    combinedSpecification.canonicalCanAdopt,
    combinedSpecification.hasCombinedDraft,
    combinedSpecification.specificationReady,
    hasUnsavedChanges,
  ]);
  return (
    <>
      <section
        className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm"
        data-testid={`stage3-${kind}-policy-actions`}
      >
        <div className="flex flex-wrap items-start gap-3">
          <div className="min-w-64 flex-1">
            <div className="text-xs font-semibold uppercase tracking-wide text-slate-700">
              Policy actions
            </div>
            <p className="mt-1 text-xs leading-5 text-slate-500">
              A draft records review decisions. Adoption authorizes later
              fold-local pipeline fitting; it never mutates Gold or fits an
              outcome model.
            </p>
            <textarea
              aria-label={`${kind} policy notes`}
              value={notes}
              onChange={(event) => setNotes(event.target.value)}
              placeholder="Scientist notes and rationale"
              rows={2}
              className="mt-2 w-full rounded-lg border border-slate-200 px-3 py-2 text-xs"
            />
          </div>
          <div className="flex flex-wrap justify-end gap-2">
            <button
              type="button"
              onClick={reset}
              className="inline-flex items-center gap-1 rounded-lg border border-slate-300 px-3 py-2 text-xs font-semibold text-slate-700"
            >
              <RotateCcw size={13} />
              Reset preview
            </button>
            <button
              ref={compareTrigger}
              type="button"
              onClick={() => setCompareOpen(true)}
              className="rounded-lg border border-slate-300 px-3 py-2 text-xs font-semibold text-slate-700"
            >
              Compare to saved policy
            </button>
            <button
              ref={historyTrigger}
              type="button"
              onClick={() => setHistoryOpen(true)}
              className="inline-flex items-center gap-1 rounded-lg border border-slate-300 px-3 py-2 text-xs font-semibold text-slate-700"
            >
              <History size={13} />
              Version history
            </button>
            <button
              type="button"
              onClick={saveDraft}
              disabled={saveStatus === "loading"}
              className="inline-flex items-center gap-1 rounded-lg bg-cyan-800 px-3 py-2 text-xs font-semibold text-white disabled:opacity-50"
            >
              <Save size={13} />
              {saveStatus === "loading"
                ? "Saving…"
                : `Save draft ${kind === "outliers" ? "outlier" : "imputation"} policy`}
            </button>
            {confirmAdopt ? (
              <span className="inline-flex items-center gap-1 rounded-lg border border-amber-300 bg-amber-50 p-1">
                <button
                  type="button"
                  onClick={adopt}
                  disabled={adoptStatus === "loading" || !canAdopt}
                  className="rounded-md bg-emerald-700 px-3 py-1.5 text-xs font-semibold text-white disabled:cursor-not-allowed disabled:opacity-50"
                >
                  Confirm adopt
                </button>
                <button
                  type="button"
                  onClick={() => setConfirmAdopt(false)}
                  className="px-2 text-xs text-slate-600"
                >
                  Cancel
                </button>
              </span>
            ) : (
              <button
                type="button"
                onClick={() => setConfirmAdopt(true)}
                disabled={!canAdopt}
                title={
                  canAdopt
                    ? "Adopt the saved draft"
                    : hasUnsavedChanges
                      ? "Visible controls differ from the saved draft; save these changes before adoption"
                      : combinedSpecification.hasCombinedDraft
                        ? "This policy belongs to a combined specification draft and must be adopted atomically"
                      : !combinedSpecification.canonicalCanAdopt
                        ? "Resolve every canonical feature-treatment blocker before adoption"
                      : "Save a draft policy before adoption"
                }
                className="inline-flex items-center gap-1 rounded-lg bg-emerald-700 px-3 py-2 text-xs font-semibold text-white disabled:cursor-not-allowed disabled:opacity-50"
              >
                <CheckCircle2 size={13} />
                {hasUnsavedChanges
                  ? "Save changes before adoption"
                  : "Adopt for model development"}
              </button>
            )}
            <button
              type="button"
              onClick={onContinue}
              disabled={continueBlocked}
              title={
                continueBlocked
                  ? "Resolve every canonical feature-treatment blocker before continuing to Feature Engineering"
                  : undefined
              }
              className="rounded-lg bg-slate-900 px-3 py-2 text-xs font-semibold text-white disabled:cursor-not-allowed disabled:bg-slate-300"
            >
              {continueLabel}
            </button>
          </div>
        </div>
        {saveError || adoptError ? (
          <div
            role="alert"
            className="mt-3 rounded-lg border border-rose-200 bg-rose-50 p-3 text-xs text-rose-900"
          >
            <b>Policy action failed:</b> {adoptError ?? saveError}
          </div>
        ) : null}
        {!canAdopt && !saveError && !adoptError ? (
          combinedSpecification.hasCombinedDraft ? (
            <div
              role="status"
              data-testid="stage3-combined-draft-atomic-adoption"
              className="mt-3 rounded-lg border border-cyan-200 bg-cyan-50 p-3 text-xs leading-5 text-cyan-950"
            >
              <b>Combined specification draft.</b> Partial {kind} adoption is
              disabled. Use the atomic specification action above so linked
              outlier and missing policies move together.
            </div>
          ) : !combinedSpecification.specificationReady ? (
            <div
              role="status"
              className="mt-3 rounded-lg border border-slate-200 bg-slate-50 p-3 text-xs leading-5 text-slate-700"
            >
              Canonical specification status must load successfully before an
              individual manual draft can be adopted.
            </div>
          ) : hasUnsavedChanges ? (
            <div
              role="alert"
              data-testid="stage3-policy-unsaved-warning"
              className="mt-3 rounded-lg border border-amber-300 bg-amber-50 p-3 text-xs leading-5 text-amber-950"
            >
              <b>Unsaved policy changes.</b> The visible controls no longer
              match the loaded draft. Save this exact configuration before
              adoption; Adopt will never authorize the older draft silently.
            </div>
          ) : (
            <p className="mt-2 text-[10px] text-slate-500">
              Save a draft policy before adoption.
            </p>
          )
        ) : null}
        {continueBlocked ? (
          <div
            role="status"
            data-testid="stage3-feature-engineering-progression-blocked"
            className="mt-3 rounded-lg border border-amber-300 bg-amber-50 p-3 text-xs leading-5 text-amber-950"
          >
            <b>Feature Engineering progression is held closed.</b> Resolve every
            canonical treatment-specification blocker first. The Feature
            Engineering page remains independently inspectable as a read-only
            preview, but no candidate set can be registered without adopted
            treatment authority.
          </div>
        ) : null}
        <div className="mt-3 flex flex-wrap gap-2 border-t border-slate-100 pt-3 text-[10px]">
          <span className="rounded-full bg-slate-900 px-2 py-1 font-semibold text-white">
            {policy?.status ?? "NO TREATMENT ADOPTED"}
          </span>
          <span className="rounded-full border border-slate-200 px-2 py-1">
            Policy version {policy?.policyVersion ?? "—"}
          </span>
          <span className="rounded-full border border-cyan-200 bg-cyan-50 px-2 py-1 text-cyan-900">
            Fold-local fitting rule persisted
          </span>
          <span className="rounded-full border border-amber-200 bg-amber-50 px-2 py-1 text-amber-900">
            No source / Gold mutation
          </span>
        </div>
      </section>
      <CockpitDrawer
        open={historyOpen}
        onClose={() => setHistoryOpen(false)}
        returnFocusRef={historyTrigger}
        title={`${kind === "outliers" ? "Outlier" : "Imputation"} policy version history`}
        description="Immutable project-bound policy versions; adopted edits create a successor rather than overwriting history."
        eyebrow="Audit history"
        widthClassName="max-w-3xl"
        testId={`stage3-${kind}-policy-history`}
      >
        <div className="p-4 sm:p-5">
          <VersionList versions={policy?.versions ?? []} />
        </div>
      </CockpitDrawer>
      <CockpitDrawer
        open={compareOpen}
        onClose={() => setCompareOpen(false)}
        returnFocusRef={compareTrigger}
        title="Compare preview to saved policy"
        description="The current UI preview remains separate from the latest persisted decision."
        eyebrow="Review only"
        widthClassName="max-w-3xl"
        testId={`stage3-${kind}-policy-compare`}
      >
        <div className="p-4 sm:p-5">{compare}</div>
      </CockpitDrawer>
    </>
  );
}

type TreatmentSpecificationContextValue = {
  hasCombinedDraft: boolean;
  specificationReady: boolean;
  canonicalCanAdopt: boolean;
  blockerCount: number | null;
  priorAuthorityByFeature: Record<string, GovernedPriorAuthority>;
};

const TreatmentSpecificationContext =
  createContext<TreatmentSpecificationContextValue>({
  hasCombinedDraft: false,
  specificationReady: false,
  canonicalCanAdopt: false,
  blockerCount: null as number | null,
  priorAuthorityByFeature: {},
  });

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function featurePriorAuthority(
  feature: TreatmentSpecificationFeature,
): GovernedPriorAuthority | null {
  const executionContract = feature.execution_contract;
  const missing = isRecord(executionContract?.missing)
    ? executionContract.missing
    : null;
  const priorAuthority = missing?.priorAuthority;
  return isRecord(priorAuthority)
    ? (priorAuthority as GovernedPriorAuthority)
    : null;
}

function featurePriorAuthorityEntries(
  features: TreatmentSpecificationFeature[],
): Array<[string, GovernedPriorAuthority]> {
  return features.flatMap((feature) => {
    const authority = featurePriorAuthority(feature);
    const featureName = feature.featureName ?? feature.feature;
    return authority && typeof featureName === "string" && featureName
      ? [[featureName, authority]]
      : [];
  });
}

export function useGovernedPriorAuthority(
  featureName: string | null | undefined,
): GovernedPriorAuthority | null {
  const context = useContext(TreatmentSpecificationContext);
  return featureName ? context.priorAuthorityByFeature[featureName] ?? null : null;
}

function priorField(value: unknown, fallback = "Not reported"): string {
  if (typeof value === "string" && value.trim()) return value.trim();
  if (typeof value === "number") return String(value);
  return fallback;
}

function priorHierarchy(value: unknown): string {
  const raw = Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string").join(" → ")
    : priorField(value);
  return raw
    .replace(/\s*(?:->|>)\s*/g, " → ")
    .replaceAll("_", " ")
    .toLowerCase()
    .replace(/\b\w/g, (letter) => letter.toUpperCase())
    .replace(/\bMlb\b/g, "MLB");
}

function priorGateStatus(value: unknown): string {
  if (value === true) return "PASS";
  if (value === false) return "FAIL";
  const status = priorField(value, "NOT REPORTED").toUpperCase();
  return status === "TRUE" ? "PASS" : status === "FALSE" ? "FAIL" : status;
}

function priorDerivedOutputs(
  authority: GovernedPriorAuthority,
  pattern: RegExp,
): string[] {
  return Array.isArray(authority.derivedOutputs)
    ? authority.derivedOutputs.filter(
        (value): value is string => typeof value === "string" && pattern.test(value),
      )
    : [];
}

export function GovernedPriorAuthorityCard({
  authority,
  featureName,
}: {
  authority: GovernedPriorAuthority;
  featureName: string;
}) {
  const status = priorField(authority.status, "NOT REPORTED");
  const ready = status.toUpperCase().includes("READY");
  const effectiveOutputs = priorDerivedOutputs(
    authority,
    /effective|sample|exposure/i,
  );
  const uncertaintyOutputs = priorDerivedOutputs(
    authority,
    /reliab|uncert|variance|standard_deviation|posterior_std/i,
  );
  const allOutputs = Array.isArray(authority.derivedOutputs)
    ? authority.derivedOutputs.filter(
        (value): value is string => typeof value === "string",
      )
    : [];

  return (
    <article
      className={`min-w-0 rounded-xl border p-3 ${
        ready
          ? "border-emerald-200 bg-emerald-50/50"
          : "border-amber-200 bg-amber-50/60"
      }`}
      data-testid={`stage3-governed-prior-${ready ? "ready" : "blocked"}`}
    >
      <div className="flex flex-wrap items-start gap-2">
        <div className="min-w-0 flex-1">
          <div className="break-all font-mono text-[11px] font-semibold text-slate-950">
            {featureName}
          </div>
          <div className="mt-1 break-all text-[10px] text-slate-600">
            {priorField(authority.authorityName)} · {priorField(authority.authorityId)}
          </div>
        </div>
        <span
          className={`rounded-full px-2 py-1 text-[9px] font-bold ${
            ready
              ? "bg-emerald-700 text-white"
              : "border border-amber-300 bg-white text-amber-950"
          }`}
        >
          {status}
        </span>
      </div>
      <dl className="mt-3 grid gap-2 text-[10px] leading-4 sm:grid-cols-2">
        <div>
          <dt className="font-semibold uppercase text-slate-500">Method / hierarchy</dt>
          <dd className="mt-0.5 text-slate-800">
            {priorField(authority.method)} · {priorHierarchy(authority.hierarchy)}
          </dd>
        </div>
        <div>
          <dt className="font-semibold uppercase text-slate-500">Fold-local / PIT</dt>
          <dd className="mt-0.5 font-semibold text-slate-800">
            Fold-local {priorGateStatus(authority.foldLocal)} · PIT {priorGateStatus(authority.pointInTime)}
          </dd>
        </div>
        <div>
          <dt className="font-semibold uppercase text-slate-500">
            Exposure / effective sample size
          </dt>
          <dd className="mt-0.5 break-words text-slate-800">
            <span className="font-mono">{priorField(authority.exposureFeature)}</span>
            {authority.exposureDefinition
              ? ` · ${authority.exposureDefinition}`
              : ""}
            {effectiveOutputs.length
              ? ` · outputs ${effectiveOutputs.join(", ")}`
              : ""}
          </dd>
        </div>
        <div>
          <dt className="font-semibold uppercase text-slate-500">
            Reliability / uncertainty
          </dt>
          <dd className="mt-0.5 break-words text-slate-800">
            {priorField(authority.reliability)}
            {uncertaintyOutputs.length
              ? ` · outputs ${uncertaintyOutputs.join(", ")}`
              : ""}
          </dd>
        </div>
      </dl>
      {allOutputs.length ? (
        <p className="mt-2 break-words rounded-lg bg-white/70 p-2 text-[9px] leading-4 text-slate-600">
          <b>Governed preprocessing outputs:</b> {allOutputs.join(", ")}
        </p>
      ) : null}
      {!ready && authority.blockedReason ? (
        <p className="mt-2 rounded-lg border border-amber-300 bg-white p-2 text-[10px] leading-4 text-amber-950">
          <b>BLOCKED:</b> {authority.blockedReason}
        </p>
      ) : null}
    </article>
  );
}

function specificationValue(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function policyReference(value: Record<string, unknown> | string | null): string {
  if (!value) return "None";
  if (typeof value === "string") return value;
  return String(
    value.policyId ?? value.id ?? value.checksum ?? value.status ?? "Present",
  );
}

function GovernedPriorAuthorityPanel({
  features,
  summary,
}: {
  features: TreatmentSpecificationFeature[];
  summary: GovernedPriorAuthority | null | undefined;
}) {
  const featureAuthorities = featurePriorAuthorityEntries(features);
  const representative = summary ?? featureAuthorities[0]?.[1] ?? null;
  if (!representative) return null;

  const readyCount = featureAuthorities.filter(([, authority]) =>
    priorField(authority.status, "").toUpperCase().includes("READY"),
  ).length;
  const blockedCount = featureAuthorities.length - readyCount;
  const reportedReady =
    typeof summary?.readyFeatureCount === "number"
      ? summary.readyFeatureCount
      : readyCount;
  const reportedBlocked =
    typeof summary?.blockedFeatureCount === "number"
      ? summary.blockedFeatureCount
      : blockedCount;
  const displayRows = featureAuthorities.length
    ? featureAuthorities
    : [["Authority summary", representative] as [string, GovernedPriorAuthority]];

  return (
    <section
      className="mt-3 rounded-xl border border-violet-200 bg-violet-50/30 p-3"
      data-testid="stage3-governed-player-prior-authority"
    >
      <div className="flex flex-wrap items-start gap-3">
        <div className="min-w-0 flex-1">
          <div className="text-[10px] font-semibold uppercase tracking-[0.14em] text-violet-800">
            Governed preprocessing authority
          </div>
          <h3 className="mt-1 break-words text-sm font-semibold text-slate-950">
            {priorField(representative.authorityName)}
          </h3>
          <p className="mt-1 max-w-4xl text-[10px] leading-4 text-slate-600">
            Read-only player-history → governed-fallback contracts. V1 uses the
            global MLB league prior because Current Gold has no governed role
            taxonomy; this page does not fit priors, models, or validation data.
          </p>
        </div>
        <div className="flex flex-wrap gap-1.5 text-[9px] font-semibold">
          <span className="rounded-full bg-emerald-700 px-2 py-1 text-white">
            {reportedReady} READY
          </span>
          <span className="rounded-full border border-amber-300 bg-white px-2 py-1 text-amber-950">
            {reportedBlocked} BLOCKED
          </span>
          <span className="rounded-full border border-violet-200 bg-white px-2 py-1 text-violet-900">
            Fold-local {priorGateStatus(representative.foldLocal)}
          </span>
          <span className="rounded-full border border-violet-200 bg-white px-2 py-1 text-violet-900">
            PIT {priorGateStatus(representative.pointInTime)}
          </span>
        </div>
      </div>
      <div className="mt-3 grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
        <SpecificationFact
          label="Authority ID"
          value={priorField(representative.authorityId)}
          detail="Content-addressed, project-bound preprocessing contract"
          mono
        />
        <SpecificationFact
          label="Method"
          value={priorField(representative.method)}
          detail="No tuning controls are exposed in this review surface"
        />
        <SpecificationFact
          label="Hierarchy"
          value={priorHierarchy(representative.hierarchy)}
          detail="Player evidence shrinks only through declared fallback levels"
        />
        <SpecificationFact
          label="Safety gates"
          value={`Fold-local ${priorGateStatus(representative.foldLocal)} · PIT ${priorGateStatus(representative.pointInTime)}`}
          detail="Training-fold authority only; final OOT remains locked"
        />
      </div>
      <details open className="mt-3 rounded-lg border border-violet-100 bg-white/70 p-2">
        <summary className="cursor-pointer text-[10px] font-semibold text-slate-900">
          Per-feature authority · {displayRows.length}
        </summary>
        <div className="mt-2 grid max-h-[32rem] gap-2 overflow-y-auto lg:grid-cols-2">
          {displayRows.map(([featureName, authority]) => (
            <GovernedPriorAuthorityCard
              key={featureName}
              featureName={featureName}
              authority={authority}
            />
          ))}
        </div>
      </details>
    </section>
  );
}

function TreatmentSpecificationPanel({
  specification,
}: {
  specification: ReturnType<typeof useTreatmentSpecification>;
}) {
  const data = specification.value?.data;
  const currentDraft = hasCurrentTreatmentSpecificationDraft(data);
  const featureColumns = data?.features.length
    ? [...new Set(data.features.flatMap((row) => Object.keys(row)))]
    : [];
  const statusTone =
    data?.reconciliation.status === "READY"
      ? "border-emerald-200 bg-emerald-50 text-emerald-900"
      : data?.reconciliation.status === "READY_WITH_EXPLICIT_FALLBACK" ||
          data?.reconciliation.status === "RECONCILED_WITH_EXPLICIT_HOLDS"
        ? "border-amber-200 bg-amber-50 text-amber-950"
        : "border-rose-200 bg-rose-50 text-rose-950";

  return (
    <section
      className="min-w-0 rounded-2xl border border-cyan-200 bg-white p-4 shadow-sm"
      data-testid="stage3-treatment-specification"
    >
      <div className="flex flex-wrap items-start gap-3">
        <div className="min-w-0 flex-1">
          <div className="text-[10px] font-semibold uppercase tracking-[0.14em] text-cyan-800">
            Canonical feature-treatment authority
          </div>
          <h2 className="mt-1 text-base font-semibold text-slate-950">
            Workbook specification → one linked draft
          </h2>
          <p className="mt-1 max-w-4xl text-xs leading-5 text-slate-600">
            Review exact-name reconciliation, scientific dispositions, and
            executable resolutions before creating linked outlier and missing
            policy drafts. This action never adopts a policy.
          </p>
        </div>
        <button
          type="button"
          disabled={
            !data?.canCreateDraft ||
            specification.draftStatus === "loading" ||
            specification.status !== "ready"
          }
          onClick={() => void specification.createDraft()}
          className="inline-flex items-center gap-1 rounded-lg bg-cyan-800 px-3 py-2 text-xs font-semibold text-white disabled:cursor-not-allowed disabled:opacity-50"
        >
          <Sparkles size={13} />
          {specification.draftStatus === "loading"
            ? "Creating linked draft…"
            : data?.draft
              ? "Reapply / verify canonical spec draft"
              : "Load / apply canonical spec as DRAFT"}
        </button>
        <button
          type="button"
          disabled={
            !data?.canAdopt ||
            !currentDraft ||
            specification.adoptStatus === "loading" ||
            specification.status !== "ready"
          }
          onClick={() => void specification.adoptSpecification()}
          title={
            data?.canAdopt && currentDraft
              ? "Adopt both linked policy drafts atomically"
              : data?.draft && !currentDraft
                ? "Create or reload the current exact manifest draft before adoption"
                : "Resolve every listed blocker before adoption"
          }
          className="inline-flex items-center gap-1 rounded-lg bg-emerald-700 px-3 py-2 text-xs font-semibold text-white disabled:cursor-not-allowed disabled:opacity-50"
        >
          <CheckCircle2 size={13} />
          {specification.adoptStatus === "loading"
            ? "Adopting reviewed specification…"
            : "Adopt reviewed specification"}
        </button>
      </div>

      {specification.status === "loading" ? (
        <p className="mt-3 text-xs text-slate-500">
          Loading the project-bound canonical specification…
        </p>
      ) : null}
      {specification.status === "error" ? (
        <div
          role="alert"
          className="mt-3 flex flex-wrap items-center gap-2 rounded-lg border border-rose-200 bg-rose-50 p-3 text-xs text-rose-950"
        >
          <b>Canonical specification held closed.</b> {specification.error}
          <button
            type="button"
            onClick={specification.retry}
            className="ml-auto rounded border border-rose-300 px-2 py-1 font-semibold"
          >
            Retry
          </button>
        </div>
      ) : null}
      {specification.draftError ? (
        <div
          role="alert"
          className="mt-3 rounded-lg border border-rose-200 bg-rose-50 p-3 text-xs text-rose-950"
        >
          <b>Draft was not created.</b> {specification.draftError}
        </div>
      ) : null}
      {specification.adoptError ? (
        <div
          role="alert"
          className="mt-3 rounded-lg border border-rose-200 bg-rose-50 p-3 text-xs text-rose-950"
        >
          <b>Specification was not adopted.</b> {specification.adoptError}
        </div>
      ) : null}

      {data ? (
        <>
          <div className="mt-3 grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
            <SpecificationFact
              label="Reconciliation"
              value={data.reconciliation.status}
              detail={`${data.reconciliation.exactMatchCount} exact matches · ${data.reconciliation.workbookFeatureCount} workbook / ${data.reconciliation.backendFeatureCount} backend`}
              className={statusTone}
            />
            <SpecificationFact
              label="Manifest checksum"
              value={data.specification.manifestChecksum}
              detail={data.specification.specificationId}
              mono
            />
            <SpecificationFact
              label="Source workbook"
              value={data.specification.sourceWorkbookFilename}
              detail={`SHA-256 ${data.specification.sourceWorkbookSha256}`}
              mono
            />
            <SpecificationFact
              label="Compiler"
              value={data.specification.compilerVersion}
              detail={`${data.features.length} fully inspectable manifest rows`}
            />
          </div>

          <GovernedPriorAuthorityPanel
            features={data.features}
            summary={data.priorAuthority}
          />

          {data.blockers.length ? (
            <div
              role="alert"
              className="mt-3 rounded-lg border border-rose-200 bg-rose-50 p-3 text-xs text-rose-950"
            >
              <b>Adoption blockers:</b>
              <ul className="mt-1 list-disc pl-5">
                {data.blockers.map((blocker) => (
                  <li key={blocker}>{blocker}</li>
                ))}
              </ul>
            </div>
          ) : null}

          <div className="mt-3 grid gap-3 xl:grid-cols-2">
            <details open className="rounded-xl border border-slate-200 p-3">
              <summary className="cursor-pointer text-xs font-semibold text-slate-900">
                Disposition and execution summary
              </summary>
              <div className="mt-3 grid gap-2 sm:grid-cols-2">
                {Object.entries(data.dispositionCounts).map(([label, count]) => (
                  <div
                    key={label}
                    className="flex items-center gap-2 rounded-lg bg-slate-50 px-2 py-1.5 text-[10px]"
                  >
                    <span className="min-w-0 flex-1 break-words font-medium text-slate-700">
                      {label}
                    </span>
                    <b className="tabular-nums text-slate-950">{count}</b>
                  </div>
                ))}
              </div>
              <dl className="mt-3 grid gap-2 sm:grid-cols-2">
                {Object.entries(data.executionSummary).map(([label, value]) => (
                  <div key={label} className="rounded-lg border border-slate-100 p-2">
                    <dt className="text-[9px] font-semibold uppercase text-slate-500">
                      {label}
                    </dt>
                    <dd className="mt-1 break-words text-xs text-slate-800">
                      {specificationValue(value)}
                    </dd>
                  </div>
                ))}
              </dl>
            </details>

            <details open className="rounded-xl border border-slate-200 p-3">
              <summary className="cursor-pointer text-xs font-semibold text-slate-900">
                Prior policies → canonical draft
              </summary>
              <div className="mt-3 grid gap-2 sm:grid-cols-2">
                <SpecificationFact
                  label="Prior outlier policy"
                  value={policyReference(data.priorPolicies.outlier)}
                  detail="Preserved immutable authority"
                  mono
                />
                <SpecificationFact
                  label="Prior missing policy"
                  value={policyReference(data.priorPolicies.missing)}
                  detail="Preserved immutable authority"
                  mono
                />
                <SpecificationFact
                  label="Linked outlier draft"
                  value={
                    data.draft
                      ? policyReference(data.draft.outlierPolicyRef)
                      : "Not created"
                  }
                  detail="Draft only; separate adoption required"
                  mono
                />
                <SpecificationFact
                  label="Linked missing draft"
                  value={
                    data.draft
                      ? policyReference(data.draft.missingPolicyRef)
                      : "Not created"
                  }
                  detail="Draft only; separate adoption required"
                  mono
                />
              </div>
              <p className="mt-3 rounded-lg border border-amber-200 bg-amber-50 p-2 text-[10px] leading-4 text-amber-950">
                {data.draft
                  ? `${data.draft.specificationDraftId} · v${data.draft.version} · ${data.draft.status} · ${data.draft.manifestChecksum}`
                  : "No combined draft is persisted yet."}{" "}
                Adoption remains a separate explicit policy action; canAdopt is
                currently {String(data.canAdopt)}.
              </p>
            </details>
          </div>

          <details className="mt-3 rounded-xl border border-amber-200 bg-amber-50/30 p-3">
            <summary className="cursor-pointer text-xs font-semibold text-slate-900">
              Priority exceptions · {data.exceptions.length}
            </summary>
            <div className="mt-3 max-h-72 space-y-2 overflow-y-auto pr-1">
              {data.exceptions.length ? (
                data.exceptions.map((exception, index) => (
                  <article
                    key={`${specificationValue(exception.featureName ?? exception.feature)}:${index}`}
                    className="rounded-lg border border-amber-100 bg-white p-2"
                  >
                    <div className="font-mono text-[11px] font-semibold text-slate-900">
                      {specificationValue(
                        exception.featureName ?? exception.feature ?? `Exception ${index + 1}`,
                      )}
                    </div>
                    <dl className="mt-1 grid gap-x-3 gap-y-1 sm:grid-cols-2">
                      {Object.entries(exception).map(([label, value]) => (
                        <div key={label} className="min-w-0 text-[10px]">
                          <dt className="inline font-semibold text-slate-500">
                            {label}: {" "}
                          </dt>
                          <dd className="inline break-words text-slate-700">
                            {specificationValue(value)}
                          </dd>
                        </div>
                      ))}
                    </dl>
                  </article>
                ))
              ) : (
                <p className="text-xs text-slate-500">No priority exceptions.</p>
              )}
            </div>
          </details>

          <details className="mt-3 rounded-xl border border-slate-200 p-3">
            <summary className="cursor-pointer text-xs font-semibold text-slate-900">
              Full canonical manifest rows · {data.features.length}
            </summary>
            <div
              role="region"
              aria-label="Full canonical feature treatment manifest"
              tabIndex={0}
              className="mt-3 max-h-[32rem] max-w-full overflow-auto rounded-lg border border-slate-200"
            >
              <table className="min-w-max text-left text-[10px]">
                <caption className="sr-only">
                  Every exact feature-treatment specification row and executable resolution
                </caption>
                <thead className="sticky top-0 z-10 bg-slate-100 uppercase text-slate-500">
                  <tr>
                    {featureColumns.map((column) => (
                      <th key={column} scope="col" className="whitespace-nowrap border-b px-2 py-2">
                        {column}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {data.features.map((feature, index) => (
                    <tr key={`${specificationValue(feature.featureName ?? feature.feature)}:${index}`}>
                      {featureColumns.map((column) => (
                        <td key={column} className="max-w-72 border-b px-2 py-2 align-top">
                          <span className="block max-h-24 overflow-auto whitespace-pre-wrap break-words">
                            {specificationValue(feature[column])}
                          </span>
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </details>
        </>
      ) : null}
    </section>
  );
}

function SpecificationFact({
  label,
  value,
  detail,
  mono = false,
  className = "border-slate-200 bg-slate-50 text-slate-900",
}: {
  label: string;
  value: string;
  detail: string;
  mono?: boolean;
  className?: string;
}) {
  return (
    <div className={`min-w-0 rounded-lg border p-2 ${className}`}>
      <div className="text-[9px] font-semibold uppercase tracking-wide opacity-70">
        {label}
      </div>
      <div
        className={`mt-1 break-all text-xs font-semibold ${mono ? "font-mono" : ""}`}
      >
        {value}
      </div>
      <div className={`mt-1 break-all text-[9px] opacity-70 ${mono ? "font-mono" : ""}`}>
        {detail}
      </div>
    </div>
  );
}

export function TreatmentStudioShell({
  kind,
  projectId,
  authorityKey,
  review,
  title,
  description,
  policy,
  children,
}: {
  kind: TreatmentKind;
  projectId: string;
  authorityKey: string;
  review: CurrentGoldDataReview;
  title: string;
  description: string;
  policy: TreatmentPolicy | null;
  children: ReactNode;
}) {
  const specification = useTreatmentSpecification(
    projectId,
    authorityKey,
    Boolean(projectId && authorityKey),
  );
  const priorAuthorityByFeature = Object.fromEntries(
    featurePriorAuthorityEntries(specification.value?.data.features ?? []),
  );
  return (
    <div
      className="space-y-4"
      data-testid={`stage3-project-bound-${kind}-studio`}
    >
      <section
        className="rounded-2xl border border-slate-200 bg-slate-950 px-4 py-3 text-white shadow-sm"
        data-testid="stage3-treatment-authority-strip"
      >
        <div className="flex flex-wrap items-start gap-3">
          <div>
            <div className="text-[10px] font-semibold uppercase tracking-[0.16em] text-cyan-300">
              Project-bound preparation studio
            </div>
            <h1 className="mt-1 text-lg font-semibold">{title}</h1>
            <p className="mt-1 max-w-4xl text-xs leading-5 text-slate-300">
              {description}
            </p>
          </div>
          <div className="ml-auto flex flex-wrap justify-end gap-1.5 text-[10px]">
            <span className="rounded-full border border-white/20 bg-white/10 px-2 py-1">
              Development {formatInteger(review.matrix.development.rows)}
            </span>
            <span className="inline-flex items-center gap-1 rounded-full border border-amber-300/40 bg-amber-300/10 px-2 py-1 text-amber-100">
              <Lock size={10} />
              Final OOT {formatInteger(review.matrix.finalOot.rows)} LOCKED
            </span>
            <span className="rounded-full border border-cyan-300/40 bg-cyan-300/10 px-2 py-1 text-cyan-100">
              {review.goldAuthority.datasetId}
            </span>
            <span className="inline-flex items-center gap-1 rounded-full border border-emerald-300/40 bg-emerald-300/10 px-2 py-1 text-emerald-100">
              <ShieldCheck size={10} />
              PIT {review.pointInTimeReview.status}
            </span>
            <span className="rounded-full border border-emerald-300/40 bg-emerald-300/10 px-2 py-1 text-emerald-100">
              Leakage {review.leakageGate.status}
            </span>
            <span className="rounded-full border border-white/20 bg-white/10 px-2 py-1">
              {policy?.status ?? "NO TREATMENT ADOPTED"}
            </span>
            <span className="rounded-full border border-white/20 bg-white/10 px-2 py-1">
              Policy v{policy?.policyVersion ?? "—"}
            </span>
          </div>
        </div>
      </section>
      <TreatmentSpecificationContext.Provider
        value={{
          hasCombinedDraft: Boolean(specification.value?.data.draft),
          specificationReady: specification.status === "ready",
          canonicalCanAdopt: specification.value?.data.canAdopt === true,
          blockerCount: specification.value?.data.blockers.length ?? null,
          priorAuthorityByFeature,
        }}
      >
        <TreatmentSpecificationPanel specification={specification} />
        {children}
      </TreatmentSpecificationContext.Provider>
      <section className="rounded-xl border border-slate-200 bg-slate-50 p-3 text-[11px] leading-5 text-slate-600">
        <Archive size={13} className="mr-1 inline" />
        <b>Authority reminder:</b> Current Gold and contextual candidates remain
        immutable. This studio stores fitting rules and versioned decisions
        only; all statistics shown here are development-only descriptive
        evidence.
      </section>
    </div>
  );
}

export function DownloadAggregatedButton({
  onClick,
  disabled,
  label = "Export aggregated table",
}: {
  onClick: () => void;
  disabled?: boolean;
  label?: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className="inline-flex items-center gap-1 rounded-lg border border-slate-300 bg-white px-3 py-2 text-xs font-semibold text-slate-700 disabled:opacity-40"
    >
      <Download size={13} />
      {label}
    </button>
  );
}
