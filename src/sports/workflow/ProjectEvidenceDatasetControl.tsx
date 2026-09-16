import { useEffect, useMemo, useState } from "react";
import { CheckCircle2, Database, RefreshCw, TriangleAlert } from "lucide-react";
import type { ActiveSportsDataset, RefreshableEvidenceState } from "../sportsEvidenceApi";
import type { ProjectSportsEvidenceState } from "./projectDatasetLinkage";
import { sportsAuthorityPresentation } from "./sportsAuthorityErrors";
import { invalidateStage2DataReview } from "./workflowState";

export function ProjectEvidenceDatasetControl({
  authority,
  catalog,
  onLinked,
}: {
  authority: ProjectSportsEvidenceState;
  catalog: RefreshableEvidenceState<ActiveSportsDataset[]>;
  onLinked: () => void | Promise<void>;
}) {
  const datasets = catalog.status === "ready"
    ? catalog.data.filter((item) => {
        if (item.compatibleWorkflowIds?.length) return item.compatibleWorkflowIds.includes("mlb-forecasting");
        return item.league.trim().toUpperCase() === "MLB";
      })
    : [];
  const initialRegistrationId = authority.linkage?.registrationId
    || datasets.find((item) => item.active)?.registrationId
    || datasets[0]?.registrationId
    || "";
  const [selectedRegistrationId, setSelectedRegistrationId] = useState(initialRegistrationId);
  const [actionError, setActionError] = useState("");
  const selected = useMemo(
    () => datasets.find((item) => item.registrationId === selectedRegistrationId) ?? null,
    [datasets, selectedRegistrationId],
  );

  useEffect(() => {
    if (authority.linkage?.registrationId) {
      setSelectedRegistrationId(authority.linkage.registrationId);
    } else if (!selectedRegistrationId && initialRegistrationId) {
      setSelectedRegistrationId(initialRegistrationId);
    }
  }, [authority.linkage?.registrationId, initialRegistrationId, selectedRegistrationId]);

  async function linkSelected() {
    if (!selectedRegistrationId || authority.status === "saving") return;
    setActionError("");
    try {
      const priorRegistrationId = authority.linkage?.registrationId ?? null;
      const nextLinkage = await authority.select(selectedRegistrationId);
      if (priorRegistrationId !== selectedRegistrationId) {
        invalidateStage2DataReview(nextLinkage.projectId);
      }
      await onLinked();
    } catch (caught) {
      setActionError(caught instanceof Error ? caught.message : "The evidence dataset could not be linked to this project.");
    }
  }

  const presentation = authority.errorCode ? sportsAuthorityPresentation(authority.errorCode, authority.error || "") : null;
  const cannotSelect = authority.errorCode === "PROJECT_NOT_REGISTERED" || authority.errorCode === "BACKEND_UNAVAILABLE";

  return (
    <section className="rounded-2xl border border-cyan-200 bg-cyan-50/50 p-5" aria-label="Project evidence dataset">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-cyan-800"><Database size={15} /> Project evidence dataset</div>
          <p className="mt-1 text-sm leading-6 text-slate-700">Choose the exact registered Data Warehouse evidence for this project. This does not change the workspace dataset used by other projects.</p>
        </div>
        {authority.status === "ready" ? <span className="sports-status sports-status--green"><CheckCircle2 size={13} /> LINKED</span> : null}
      </div>

      {authority.status === "loading" ? <p className="mt-4 text-sm text-slate-600">Resolving the project-scoped evidence link…</p> : null}
      {presentation && authority.status !== "loading" ? (
        <div className="mt-4 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-950" role="status" data-authority-error-code={authority.errorCode}>
          <div className="flex items-center gap-2 font-semibold"><TriangleAlert size={16} /> {presentation.title}</div>
          <p className="mt-1 leading-6">{presentation.message}</p>
        </div>
      ) : null}

      {authority.linkage ? (
        <dl className="mt-4 grid gap-3 rounded-xl border border-emerald-200 bg-white p-4 text-sm sm:grid-cols-2 lg:grid-cols-4">
          <Fact label="Dataset" value={authority.linkage.datasetId} />
          <Fact label="Registration" value={authority.linkage.registrationId} />
          <Fact label="Earliest evidence" value={authority.linkage.coverage.earliestDate} />
          <Fact label="Latest evidence" value={authority.linkage.coverage.latestDate} />
        </dl>
      ) : null}

      {catalog.status === "loading" ? <p className="mt-4 text-sm text-slate-600">Loading registered evidence datasets…</p> : null}
      {catalog.status === "error" ? (
        <div className="mt-4 rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-900" role="alert">
          <b>Registered dataset catalog unavailable.</b> {catalog.error}
          <button type="button" onClick={catalog.refresh} className="ml-3 inline-flex items-center gap-1 font-semibold underline"><RefreshCw size={13} /> Retry</button>
        </div>
      ) : null}
      {catalog.status === "empty" ? <p className="mt-4 rounded-xl border border-slate-200 bg-white p-4 text-sm text-slate-600">No governed sports dataset registration is available. Register one in the Data Warehouse first.</p> : null}

      {datasets.length ? (
        <div className="mt-4 grid gap-3 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-end">
          <label className="flex min-w-0 flex-col gap-1.5">
            <span className="text-xs font-semibold uppercase tracking-wide text-slate-600">Registered evidence dataset</span>
            <select value={selectedRegistrationId} onChange={(event) => setSelectedRegistrationId(event.target.value)} className="wf-input">
              {datasets.map((item) => (
                <option key={item.registrationId} value={item.registrationId}>
                  {item.datasetId} · {item.dateCoverage ? `${item.dateCoverage.earliestDate} through ${item.dateCoverage.latestDate}` : item.registrationId}
                </option>
              ))}
            </select>
          </label>
          <button
            type="button"
            onClick={() => void linkSelected()}
            disabled={!selected || cannotSelect || authority.status === "saving" || selected.registrationId === authority.linkage?.registrationId}
            className="sports-primary-button disabled:cursor-not-allowed disabled:opacity-50"
          >
            <Database size={16} /> {authority.status === "saving" ? "Linking…" : selected?.registrationId === authority.linkage?.registrationId ? "Evidence dataset selected" : "Select evidence dataset"}
          </button>
        </div>
      ) : null}
      {selected ? <p className="mt-2 break-all text-xs text-slate-500">Selected registration: {selected.registrationId}</p> : null}
      {actionError ? <p className="mt-3 rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-sm font-semibold text-rose-800" role="alert">{actionError}</p> : null}
    </section>
  );
}

function Fact({ label, value }: { label: string; value: string }) {
  return <div className="min-w-0"><dt className="text-xs font-semibold uppercase tracking-wide text-slate-500">{label}</dt><dd className="mt-1 break-all font-semibold text-slate-900">{value}</dd></div>;
}
