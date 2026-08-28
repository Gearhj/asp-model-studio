// Stage 2 — Baseball Data Evidence. Detects the already-registered governed FD1 dataset and lets
// the scientist bind (reference) it to this project. Binding is a local project→dataset reference:
// no data copy, no duplicate registration, no change to immutable authority.
import { Link } from "react-router-dom";
import { CheckCircle2, Database, ExternalLink, TriangleAlert } from "lucide-react";
import type { ActiveSportsDataset } from "../sportsEvidenceApi";
import { saveBinding } from "./workflowState";
import DataPreviewPanel from "../cockpit/DataPreviewPanel";

export function DatasetBindingPanel({
  projectId, dataset, datasetStatus, bound, onBound,
}: {
  projectId: string;
  dataset: ActiveSportsDataset | null;
  datasetStatus: string;
  bound: boolean;
  onBound: () => void;
}) {

  if (datasetStatus === "error") {
    return (
      <section className="rounded-2xl border border-rose-200 bg-rose-50 p-6">
        <div className="flex items-center gap-2 text-rose-800"><TriangleAlert size={18} /><span className="font-semibold">Unable to load registered evidence.</span></div>
        <p className="mt-1 text-sm text-rose-900">The registration service could not be read. This is not the same as “no dataset”.</p>
        <button onClick={() => window.location.reload()} className="mt-3 rounded-lg border border-rose-300 bg-white px-3 py-2 text-sm font-semibold text-rose-800">Retry</button>
      </section>
    );
  }
  if (!dataset) {
    return (
      <section className="sports-panel p-6">
        <div className="flex items-center gap-2 text-slate-700"><Database size={18} /><span className="font-semibold">No registered MLB dataset is available.</span></div>
        <p className="mt-1 text-sm text-slate-600">Register a governed MLB dataset in the Data Warehouse, then return to bind it here.</p>
        <Link to="/data-warehouse" className="sports-dark-button mt-3">Open Data Warehouse <ExternalLink size={15} /></Link>
      </section>
    );
  }

  // Bind and advance immediately — no interstitial confirmation screen.
  const doBind = () => {
    saveBinding({
      projectId,
      registrationId: dataset.registrationId,
      datasetId: dataset.datasetId,
      datasetVersionId: dataset.datasetVersionId,
      manifestSha: dataset.manifestSha,
      seasons: dataset.seasons,
      boundAt: new Date().toISOString(),
    });
    onBound();
  };

  if (bound) {
    return (
      <div className="space-y-4">
        <section className="rounded-2xl border border-emerald-200 bg-emerald-50 p-6">
          <div className="flex items-center gap-2 text-emerald-800"><CheckCircle2 size={20} /><span className="text-lg font-semibold">Dataset bound to this project</span></div>
          <div className="mt-3 grid gap-2 text-sm text-emerald-900 sm:grid-cols-2">
            <Fact label="Dataset" value={`${dataset.datasetId} · ${dataset.validationStatus}`} />
            <Fact label="Season coverage" value={dataset.seasons.join(", ")} />
            <Fact label="Rights" value={dataset.rightsStatus || "Local private research"} />
            <Fact label="Manifest authority" value={`${dataset.manifestSha.slice(0, 16)}…`} />
          </div>
          <p className="mt-3 text-xs text-emerald-800">This project references the governed dataset. No data was copied and no duplicate registration was created.</p>
        </section>
        <DataPreviewPanel title="Your selected data" />
      </div>
    );
  }

  return (
    <section className="sports-panel p-5 sm:p-6">
      <div className="rounded-2xl border border-cyan-200 bg-gradient-to-br from-cyan-50 to-white p-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <div className="text-xs font-semibold uppercase tracking-wide text-cyan-700">Available registered dataset</div>
            <div className="mt-1 text-xl font-semibold text-slate-950">{dataset.datasetId}</div>
            <div className="mt-1 text-sm text-slate-600">{dataset.league} · {dataset.sport}</div>
          </div>
          <span className="sports-status sports-status--green">{dataset.validationStatus}</span>
        </div>
        <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <Stat label="Seasons" value={`${dataset.seasons[0]}–${dataset.seasons.slice(-1)[0]}`} />
          <Stat label="Games" value={fmtInt(dataset.totals?.games)} />
          <Stat label="Plate appearances" value={fmtInt(dataset.totals?.plateAppearances)} />
          <Stat label="Rights" value={dataset.rightsStatus || "Local private"} />
        </div>
      </div>
      <div className="mt-5 flex flex-wrap gap-3">
        <button onClick={doBind} className="sports-primary-button">Use This Registered Dataset</button>
        <Link to="/data-warehouse?from=mlb-workflow&step=2" className="sports-dark-button"><Database size={16} /> Inspect in Data Warehouse</Link>
      </div>
      <p className="mt-3 text-xs text-slate-500">Binding references the immutable dataset for this project. No data is copied; no new registration is created.</p>
    </section>
  );
}

function fmtInt(v: number | undefined) {
  return v === undefined || v === null ? "—" : Math.round(v).toLocaleString();
}
function Stat({ label, value }: { label: string; value: string }) {
  return <div className="rounded-xl border border-slate-200 bg-white p-3"><div className="text-xs font-semibold uppercase tracking-wide text-slate-500">{label}</div><div className="mt-1 text-lg font-semibold tabular-nums text-slate-900">{value}</div></div>;
}
function Fact({ label, value }: { label: string; value: string }) {
  return <div><span className="font-semibold">{label}:</span> {value}</div>;
}
