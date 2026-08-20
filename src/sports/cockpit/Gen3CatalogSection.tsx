// Phase 7A.2 — server-catalog-driven dataset authority for Data Warehouse + Data & Population.
// The authoritative modeling datasets come from GET /cockpit/gen3/catalog (never hard-coded). In
// "selection" mode the scientist selects an EXACT immutable version -> the backend creates a project
// binding; the active binding auto-restores on mount (server wins over any local cache). The sealed
// 2025 object is shown as restricted/non-selectable and never exposes analytical distributions.
import { useCallback, useEffect, useState } from "react";
import { Database, ShieldCheck, Lock, CheckCircle2, TriangleAlert, Loader2 } from "lucide-react";
import { getJSON, postJSON } from "../../lib/api";

export type CatalogEntry = {
  datasetVersionId: string; label: string; generation: string; status: string; selectable: boolean;
  logicalContentSha256: string; seasons: number[]; developmentSeasons: number[]; validationSeason: number | null;
  sealedSeasons: number[]; rows: number; featureCount?: number; target: string;
};
export type Binding = {
  bindingId: string; datasetVersionId: string; datasetContentSha256: string; generation: string;
  developmentSeasons: number[]; validationSeason: number; sealedSeasons: number[];
  targetContractId: string; temporalContractId: string; preprocessingContractId: string;
};

const short = (s?: string) => (s ? s.slice(0, 12) + "…" : "—");
const roleRows = (rows: number) => rows.toLocaleString("en-US");

export function useGen3Catalog() {
  const [catalog, setCatalog] = useState<CatalogEntry[]>([]);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    (async () => {
      try {
        // Registration is an explicit build/admin action (A2-06); the UI only READS the server catalog.
        setCatalog((await getJSON<{ datasets: CatalogEntry[] }>("/cockpit/gen3/catalog")).datasets);
      } catch (e) { setError(String(e)); }
    })();
  }, []);
  return { catalog, error };
}

// Server-authoritative active binding with auto-restore (Gate 4). Returns null when the project has none.
export function useActiveBinding(projectId: string) {
  const [binding, setBinding] = useState<Binding | null>(null);
  const [loaded, setLoaded] = useState(false);
  const refresh = useCallback(async () => {
    try {
      setBinding(await getJSON<Binding>(`/cockpit/gen3/binding/${encodeURIComponent(projectId)}`));
    } catch {
      setBinding(null); // 404 = no active binding yet
    } finally { setLoaded(true); }
  }, [projectId]);
  useEffect(() => { refresh(); }, [refresh]);
  return { binding, loaded, refresh, setBinding };
}

function DatasetCard({ e, selectable, onSelect, active, busy }: {
  e: CatalogEntry; selectable: boolean; onSelect?: () => void; active: boolean; busy: boolean;
}) {
  const sealed = e.generation === "GEN3_SEALED";
  return (
    <div className={`rounded-xl border p-4 ${active ? "border-emerald-400 bg-emerald-50/40" : sealed ? "border-slate-300 bg-slate-50" : "border-slate-200 bg-white"}`}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2 text-sm font-semibold text-slate-900"><Database size={15} className="text-cyan-600" /> {e.label}</div>
        <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase ${sealed ? "bg-slate-200 text-slate-600" : "bg-emerald-100 text-emerald-700"}`}>
          {sealed ? <><Lock size={10} /> restricted</> : e.status.replaceAll("_", " ").toLowerCase()}
        </span>
      </div>
      <div className="mt-2 grid gap-1.5 text-xs sm:grid-cols-2 lg:grid-cols-3">
        <Field label="Version / registration" value={e.datasetVersionId.split(":")[0]} />
        <Field label="Content SHA" value={short(e.logicalContentSha256)} mono />
        <Field label="Feature view" value={e.datasetVersionId.startsWith("mlb-pa") ? e.datasetVersionId.split(":")[0] : "—"} />
        <Field label="Rows" value={roleRows(e.rows)} />
        <Field label="Features" value={e.featureCount != null ? `${e.featureCount} governed` : "—"} />
        <Field label="Seasons" value={e.seasons.join(", ")} />
        <Field label="Development" value={e.developmentSeasons.length ? e.developmentSeasons.join(", ") : "—"} />
        <Field label="Validation" value={e.validationSeason ? String(e.validationSeason) : "—"} />
        <Field label="Sealed OOT" value={e.sealedSeasons.length ? `${e.sealedSeasons.join(", ")} · separate` : "—"} />
        <Field label="Target" value={`${e.target} · 8-class`} />
        <Field label="Knowledge time" value="Conditional pre-PA state (governed)" />
        <Field label="Governance" value={sealed ? "SEALED / not selectable" : "GOVERNED research"} />
      </div>
      {sealed && <p className="mt-2 text-[11px] text-amber-700">Sealed 2025 evidence — not selectable for model development; no target distribution or metrics are exposed.</p>}
      {onSelect && (
        <button onClick={onSelect} disabled={!selectable || busy}
          className={`mt-3 inline-flex items-center gap-1.5 rounded-lg px-3.5 py-2 text-sm font-semibold ${active ? "border border-emerald-500 bg-white text-emerald-700" : "bg-cyan-600 text-white hover:bg-cyan-500"} disabled:opacity-50`}>
          {busy ? <Loader2 size={14} className="animate-spin" /> : active ? <CheckCircle2 size={14} /> : <Database size={14} />}
          {active ? "Bound (server authority)" : selectable ? "Select & bind (server)" : "Not selectable"}
        </button>
      )}
    </div>
  );
}

function Field({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="rounded-lg border border-slate-100 bg-slate-50 px-2.5 py-1.5">
      <div className="text-[9px] font-semibold uppercase text-slate-400">{label}</div>
      <div className={`mt-0.5 font-semibold text-slate-800 ${mono ? "font-mono text-[11px]" : ""}`}>{value}</div>
    </div>
  );
}

export default function Gen3CatalogSection({ mode, projectId }: { mode: "warehouse" | "selection"; projectId?: string }) {
  const { catalog, error } = useGen3Catalog();
  const active = useActiveBinding(mode === "selection" ? (projectId || "mlb-gen2") : "");
  const [busy, setBusy] = useState<string | null>(null);
  const [bindError, setBindError] = useState<string | null>(null);

  const select = async (versionId: string) => {
    if (mode !== "selection") return;
    setBusy(versionId); setBindError(null);
    try {
      await postJSON<Binding>("/cockpit/gen3/bind", { projectId: projectId || "mlb-gen2", datasetVersionId: versionId });
      await active.refresh(); // server wins — re-resolve authoritative binding
    } catch (e) { setBindError(String(e)); } finally { setBusy(null); }
  };

  return (
    <section className="sports-panel rounded-2xl border border-slate-200 bg-white p-4 sm:p-5">
      <div className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.16em] text-cyan-700">
        <ShieldCheck size={14} /> {mode === "warehouse" ? "Governed modeling datasets · server catalog" : "Modeling dataset · server authority"}
      </div>
      <h3 className="mt-1 text-lg font-semibold text-slate-950">{mode === "warehouse" ? "Data Warehouse — registered feature views" : "Select the authoritative modeling dataset"}</h3>

      {mode === "selection" && active.loaded && active.binding && (
        <div className="mt-2 flex flex-wrap items-center gap-2 rounded-xl border border-emerald-200 bg-emerald-50 px-3 py-2 text-xs text-emerald-800">
          <span className="inline-flex items-center gap-1.5 rounded-full bg-emerald-600 px-2.5 py-0.5 text-[11px] font-bold uppercase text-white"><CheckCircle2 size={12} /> Active binding restored</span>
          <span>Server authority: <b>{active.binding.datasetVersionId.split(":")[0]}</b> · content {short(active.binding.datasetContentSha256)} · dev {active.binding.developmentSeasons.join(",")} · val {active.binding.validationSeason} · sealed {active.binding.sealedSeasons.join(",") || "—"}</span>
          <span className="ml-auto text-[10px] text-emerald-700">server state wins over local cache</span>
        </div>
      )}
      {error && <p className="mt-2 text-xs text-rose-700"><TriangleAlert size={12} className="mr-1 inline" />catalog unavailable: {error}</p>}
      {bindError && <p className="mt-2 text-xs text-rose-700"><TriangleAlert size={12} className="mr-1 inline" />{bindError}</p>}

      <div className="mt-3 grid gap-3 lg:grid-cols-2">
        {catalog.map((e) => (
          <DatasetCard key={e.datasetVersionId} e={e} selectable={e.selectable}
            active={mode === "selection" && active.binding?.datasetVersionId === e.datasetVersionId}
            busy={busy === e.datasetVersionId}
            onSelect={mode === "selection" && e.selectable ? () => select(e.datasetVersionId) : undefined} />
        ))}
      </div>
    </section>
  );
}
