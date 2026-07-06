import { useEffect, useState } from "react";
import { Activity, CheckCircle2, RefreshCw, TriangleAlert, XCircle } from "lucide-react";
import BrandLogo from "../components/BrandLogo";
import { getSystemDiagnostics, type SystemDiagnostics as Diagnostics } from "../lib/datasetLibrary";

export default function SystemDiagnostics() {
  const [diagnostics, setDiagnostics] = useState<Diagnostics | null>(null);
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(false);

  async function refresh() {
    setLoading(true);
    setMessage("");
    try {
      setDiagnostics(await getSystemDiagnostics());
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "ATLAS diagnostics are unavailable.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    refresh();
  }, []);

  return (
    <div className="w-full space-y-5">
      <section className="rounded-xl border border-slate-200/80 bg-white/90 p-5 shadow-sm">
        <BrandLogo size="md" variant="light" showSubtitle className="mb-3" />
        <div className="flex flex-col gap-4 xl:flex-row xl:items-end xl:justify-between">
          <div>
            <div className="flex items-center gap-2">
              <Activity size={21} className="text-blue-700" />
              <h1 className="text-xl font-semibold text-slate-950">System Diagnostics</h1>
            </div>
            <p className="mt-1 max-w-3xl text-sm leading-6 text-slate-600">
              Validate local ATLAS services, dataset registry storage, access-control configuration, and project-dataset link health.
            </p>
          </div>
          <button type="button" onClick={refresh} className="inline-flex items-center gap-2 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-semibold text-slate-700 shadow-sm hover:bg-slate-50">
            <RefreshCw size={16} className={loading ? "animate-spin" : ""} />
            Refresh
          </button>
        </div>
        {message && <div className="mt-4 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-900">{message}</div>}
      </section>

      <section className="grid gap-4 md:grid-cols-4">
        <Metric label="Datasets" value={diagnostics?.datasetCount?.toLocaleString() ?? "-"} />
        <Metric label="Archived" value={diagnostics?.archivedCount?.toLocaleString() ?? "-"} />
        <Metric label="Project Links" value={diagnostics?.projectLinkCount?.toLocaleString() ?? "-"} />
        <Metric label="Current User" value={diagnostics?.currentUser?.displayName ?? "-"} />
      </section>

      <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
        <h2 className="text-base font-semibold text-slate-950">Diagnostic Checks</h2>
        <div className="mt-4 grid gap-3">
          {(diagnostics?.checks ?? []).map((check) => (
            <div key={check.id} className="flex flex-col gap-3 rounded-lg border border-slate-200 bg-slate-50 px-4 py-3 sm:flex-row sm:items-start sm:justify-between">
              <div className="flex items-start gap-3">
                <StatusIcon status={check.status} />
                <div>
                  <div className="text-sm font-semibold text-slate-950">{check.label}</div>
                  <div className="mt-1 text-sm leading-5 text-slate-600">{check.detail}</div>
                </div>
              </div>
              <span className={`rounded-full px-2 py-1 text-xs font-semibold uppercase ${statusClass(check.status)}`}>{check.status}</span>
            </div>
          ))}
          {!diagnostics?.checks?.length && <div className="rounded-lg border border-slate-200 bg-slate-50 p-6 text-center text-sm text-slate-500">No diagnostics loaded.</div>}
        </div>
      </section>

      <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
        <h2 className="text-base font-semibold text-slate-950">Artifact Location</h2>
        <p className="mt-2 break-all rounded-lg bg-slate-950 px-3 py-2 font-mono text-xs text-slate-100">{diagnostics?.artifactRoot ?? "Not available"}</p>
      </section>
    </div>
  );
}

function StatusIcon({ status }: { status: string }) {
  if (status === "pass") return <CheckCircle2 size={18} className="mt-0.5 text-emerald-700" />;
  if (status === "warning") return <TriangleAlert size={18} className="mt-0.5 text-amber-700" />;
  return <XCircle size={18} className="mt-0.5 text-red-700" />;
}

function statusClass(status: string) {
  if (status === "pass") return "bg-emerald-100 text-emerald-800";
  if (status === "warning") return "bg-amber-100 text-amber-800";
  return "bg-red-100 text-red-800";
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-slate-200/80 bg-white/90 p-4 shadow-sm">
      <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">{label}</div>
      <div className="mt-2 truncate text-xl font-semibold text-slate-950" title={value}>{value}</div>
    </div>
  );
}

