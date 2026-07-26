// Part B: Analysis Scope -- the persistent governance state of this analysis.
//
// This banner is the answer to the defect that motivated the phase: an
// unregistered upload produced results that looked identical to version-pinned
// ones. The scope shown here is ALWAYS the server's answer; this component
// renders it and never derives it.
//
// Deliberate restraint: a draft is a legitimate governance state, not an error.
// Amber, not red; "Workspace Draft Analysis", not a security warning.
import { ArrowRight, DatabaseZap, FileCheck2, LoaderCircle, ShieldCheck, TriangleAlert } from "lucide-react";
import type { AnalysisScope } from "../../lib/targetIntelligence";
import { formatCount } from "../../lib/targetIntelligence";

export type ScopeResolution = "governed" | "draft" | "resolving" | "failed";

export default function AnalysisScopeBanner({
  resolution,
  scope,
  error,
  onRegister,
  onRetry,
  reconciliation,
}: {
  resolution: ScopeResolution;
  scope: AnalysisScope | null;
  error?: string | null;
  /** Takes the user to the existing Data Acquisition registration/link flow.
   *  EDA never implements a second registration system of its own. */
  onRegister: () => void;
  onRetry?: () => void;
  /** Set when the governed rerun disagrees materially with the draft it replaced. */
  reconciliation?: string[] | null;
}) {
  const governed = resolution === "governed" && scope?.mode === "governed_version";

  const tone = governed
    ? "border-emerald-300 bg-emerald-50"
    : resolution === "failed"
      ? "border-red-300 bg-red-50"
      : "border-amber-300 bg-amber-50";
  const accent = governed ? "text-emerald-900" : resolution === "failed" ? "text-red-900" : "text-amber-950";

  return (
    <section
      className={`rounded-xl border-2 p-4 shadow-sm ${tone}`}
      data-testid="analysis-scope-banner"
      data-scope-mode={governed ? "governed_version" : resolution === "resolving" ? "resolving" : "workspace_draft"}
      data-scope-resolution={resolution}
      aria-live="polite"
      role="status"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className={`flex items-center gap-2 text-sm font-bold ${accent}`}>
            {governed ? (
              <ShieldCheck size={17} />
            ) : resolution === "resolving" ? (
              <LoaderCircle size={17} className="animate-spin" />
            ) : resolution === "failed" ? (
              <TriangleAlert size={17} />
            ) : (
              <DatabaseZap size={17} />
            )}
            <span data-testid="analysis-scope-label">
              {governed
                ? "Governed Dataset Version"
                : resolution === "resolving"
                  ? "Resolving Governed Dataset Version"
                  : resolution === "failed"
                    ? "Governed Dataset Version could not be resolved"
                    : "Workspace Draft Analysis"}
            </span>
          </div>

          {/* The disclosure is always visible text -- never tooltip-only. */}
          <p className={`mt-2 max-w-3xl text-sm leading-6 ${accent}`} data-testid="analysis-scope-disclosure">
            {resolution === "resolving"
              ? "The registered dataset version is being resolved. The figures below are still the workspace draft result and are not governed until this completes."
              : resolution === "failed"
                ? error ?? "The registered dataset version could not be resolved, so this analysis is not governed."
                : scope?.disclosure ??
                  "Workspace Draft Analysis. This analysis uses the current full backend workspace population. It is not tied to an immutable dataset version, so it is not eligible for governed evidence or Model Development Document use."}
          </p>
        </div>

        {!governed && resolution !== "resolving" ? (
          <button
            type="button"
            className="atlas-primary-button shrink-0"
            data-testid="analysis-scope-register-cta"
            onClick={onRegister}
          >
            Register or Link a Dataset Version <ArrowRight size={15} />
          </button>
        ) : null}
        {resolution === "failed" && onRetry ? (
          <button type="button" className="atlas-secondary-button shrink-0" data-testid="analysis-scope-retry" onClick={onRetry}>
            Retry
          </button>
        ) : null}
      </div>

      <dl className="mt-3 grid gap-2 sm:grid-cols-2 xl:grid-cols-4" data-testid="analysis-scope-facts">
        {governed ? (
          <>
            <Fact label="Dataset" value={scope?.datasetName || "Not available"} testId="scope-dataset-name" />
            <Fact label="Dataset ID" value={scope?.datasetId || "Not available"} testId="scope-dataset-id" />
            <Fact label="Version ID" value={scope?.datasetVersionId || "Not available"} testId="scope-version-id" />
            <Fact
              label="Version status"
              value={scope?.immutableVersion ? "Immutable / version-pinned" : "Not version-pinned"}
              testId="scope-immutable"
            />
            <Fact label="Population rows" value={formatCount(scope?.populationRows)} testId="scope-population-rows" />
            <Fact
              label="Population coverage"
              value={scope?.sampled ? "Stratified sample" : "Full population"}
              testId="scope-coverage"
            />
            <Fact label="Result state" value={scope?.exact ? "Exact" : "Estimated"} testId="scope-exact" />
            <Fact
              label="Evidence / MDD"
              value={`${scope?.evidenceEligible ? "Evidence eligible" : "Not evidence eligible"} - ${scope?.mddEligible ? "MDD eligible" : "Not MDD eligible"}`}
              testId="scope-eligibility"
            />
          </>
        ) : (
          <>
            <Fact label="Analysis source" value="Full backend workspace population" testId="scope-dataset-name" />
            <Fact label="Dataset version" value="Not version-pinned" testId="scope-version-id" />
            <Fact label="Population rows" value={formatCount(scope?.populationRows)} testId="scope-population-rows" />
            <Fact label="Result state" value={scope?.exact === false ? "Estimated" : "Exact"} testId="scope-exact" />
            <Fact label="Evidence eligibility" value="Not eligible" testId="scope-eligibility" />
            <Fact label="MDD eligibility" value="Not eligible" testId="scope-mdd" />
            <Fact
              label="Workspace identity"
              value={scope?.datasetFingerprint ? `${scope.datasetFingerprint.slice(0, 18)}...` : "Not resolved"}
              testId="scope-workspace-fingerprint"
            />
            <Fact
              label="Invalidated by"
              value="Changing or replacing the workspace dataset"
              testId="scope-invalidation"
            />
          </>
        )}
      </dl>

      {reconciliation && reconciliation.length ? (
        <div
          className="mt-3 rounded-lg border border-amber-400 bg-white px-3 py-2 text-xs text-amber-950"
          data-testid="analysis-scope-reconciliation"
        >
          <div className="flex items-center gap-1 font-semibold">
            <FileCheck2 size={13} /> The registered version does not match the draft result
          </div>
          <ul className="mt-1 list-disc space-y-1 pl-5">
            {reconciliation.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
          <p className="mt-1">
            The governed figures shown below come from the registered version. Review the difference before relying on
            either result.
          </p>
        </div>
      ) : null}
    </section>
  );
}

function Fact({ label, value, testId }: { label: string; value: string; testId?: string }) {
  return (
    <div className="rounded-lg border border-white/70 bg-white px-3 py-2" data-testid={testId}>
      <dt className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">{label}</dt>
      <dd className="mt-0.5 truncate text-sm font-semibold text-slate-900" title={value}>
        {value}
      </dd>
    </div>
  );
}
