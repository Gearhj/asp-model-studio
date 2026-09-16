// Phase 7A.2 — server-catalog-driven dataset authority for Data Warehouse + Data & Population.
// The authoritative modeling datasets come from GET /cockpit/gen3/catalog (never hard-coded). In
// "selection" mode the scientist selects an EXACT immutable version -> the backend creates a project
// binding; the active binding auto-restores on mount (server wins over any local cache). The sealed
// 2025 object is shown as restricted/non-selectable and never exposes analytical distributions.
import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from "react";
import { Database, ShieldCheck, Lock, CheckCircle2, TriangleAlert, Loader2 } from "lucide-react";
import { getJSON, postJSON } from "../../lib/api";
import { getCachedUserId, subscribeCachedUserId } from "../../lib/authSession";

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

const STATE_MSG: Record<string, string> = {
  LOADING: "Resolving the project's active modeling dataset…",
  NO_BINDING: "No active modeling dataset — select one below.",
  STALE: "The binding changed on the server — reload to get the current authority.",
  UNAUTHENTICATED: "Your session expired — sign in again.",
  UNAUTHORIZED: "You do not have permission to access this project's modeling dataset.",
  NOT_FOUND: "No active modeling dataset — select one below.",
  SERVER_ERROR: "The dataset authority service returned an error — retry shortly.",
  NETWORK_ERROR: "Could not reach the dataset authority service — check your connection.",
  ACTIVE: "Active binding restored.",
};
const STATE_TONE: Record<string, string> = {
  LOADING: "border-slate-200 bg-slate-50 text-slate-600",
  NO_BINDING: "border-amber-200 bg-amber-50 text-amber-800",
  NOT_FOUND: "border-amber-200 bg-amber-50 text-amber-800",
  STALE: "border-amber-300 bg-amber-50 text-amber-900",
  UNAUTHENTICATED: "border-rose-200 bg-rose-50 text-rose-800",
  UNAUTHORIZED: "border-rose-200 bg-rose-50 text-rose-800",
  SERVER_ERROR: "border-rose-200 bg-rose-50 text-rose-800",
  NETWORK_ERROR: "border-rose-200 bg-rose-50 text-rose-800",
  ACTIVE: "border-emerald-200 bg-emerald-50 text-emerald-800",
};

export function useGen3Catalog(projectId: string) {
  const userId = useSyncExternalStore(subscribeCachedUserId, getCachedUserId, () => null);
  const identity = `${userId ?? "anonymous"}:${projectId}`;
  const [state, setState] = useState<{ identity: string; catalog: CatalogEntry[]; error: string | null }>({ identity: "", catalog: [], error: null });
  useEffect(() => {
    let alive = true;
    setState({ identity, catalog: [], error: null });
    if (!projectId.trim() || !userId) {
      setState({ identity, catalog: [], error: "Select a project and sign in to inspect its governed datasets." });
      return;
    }
    (async () => {
      try {
        const result = await getJSON<{ datasets: CatalogEntry[] }>(`/cockpit/gen3/catalog?projectId=${encodeURIComponent(projectId)}`);
        if (alive) setState({ identity, catalog: result.datasets, error: null });
      } catch (error) {
        if (alive) setState({ identity, catalog: [], error: String(error) });
      }
    })();
    return () => { alive = false; };
  }, [projectId, userId, identity]);
  return state.identity === identity ? state : { identity, catalog: [], error: null };
}

// Server-authoritative active binding with auto-restore + an explicit state machine (Gate 4/5). Never
// collapses failures to null and never silently selects a default dataset. Aborts stale in-flight
// requests when the project changes (server state wins over any local cache).
export type BindingState = "LOADING" | "NO_BINDING" | "ACTIVE" | "STALE" | "UNAUTHENTICATED"
  | "UNAUTHORIZED" | "NOT_FOUND" | "SERVER_ERROR" | "NETWORK_ERROR";

function classify(err: unknown): BindingState {
  const m = /failed:\s*(\d+)/.exec(String(err));
  if (!m) return "NETWORK_ERROR";
  const s = Number(m[1]);
  if (s === 401) return "UNAUTHENTICATED";
  if (s === 403) return "UNAUTHORIZED";
  if (s === 404) return "NO_BINDING";
  if (s === 409 || s === 422) return "STALE";
  if (s >= 500) return "SERVER_ERROR";
  return "SERVER_ERROR";
}

export function useActiveBinding(projectId: string) {
  const userId = useSyncExternalStore(subscribeCachedUserId, getCachedUserId, () => null);
  const [binding, setBinding] = useState<Binding | null>(null);
  const [state, setState] = useState<BindingState>("LOADING");
  const reqId = useRef(0);
  const refresh = useCallback(async () => {
    const mine = ++reqId.current;
    setState("LOADING");
    if (!projectId.trim() || !userId) { setBinding(null); setState(userId ? "NO_BINDING" : "UNAUTHENTICATED"); return; }
    try {
      const b = await getJSON<Binding>(`/cockpit/gen3/binding/${encodeURIComponent(projectId)}`);
      if (mine !== reqId.current) return;           // a newer project request superseded this one
      setBinding(b); setState("ACTIVE");
    } catch (e) {
      if (mine !== reqId.current) return;
      setBinding(null); setState(classify(e));       // never a silent null-collapse
    }
  }, [projectId, userId]);
  // Gate 5 — on project switch, immediately clear display state and re-enter LOADING for the new project.
  useEffect(() => { setBinding(null); setState("LOADING"); reqId.current++; refresh(); }, [refresh]);
  return { binding, state, loaded: state !== "LOADING", refresh, setBinding };
}

export type BindingPopulation = {
  generation: string; label: string; datasetVersionId: string; registrationId: string; datasetContentSha256: string;
  target: string; targetClasses: string[]; classCount: number; targetContractId: string;
  developmentSeasons: number[]; developmentRows: number; validationSeason: number; validationRows: number;
  sealedSeasons: number[]; sealedState: string; featureCount: number; registeredRows: number;
  temporalContractId: string; preprocessingContractId: string; knowledgeTimeContractId: string;
  knowledgeTimeSafetyClass: string; featureContractId: string; quarantineTotal?: number;
  waterfall: { stage: string; rows: number; kind: string }[]; seasons: { season: number; role: string; rows: number | null }[];
};

// Gate 1/2/3 — the ACTIVE MODELING DATASET authority, driven entirely by the server active binding
// (never notes/localStorage, never opens the sealed object). Generation-aware; no 2025 distribution.
export function Gen3PopulationPanel({ projectId }: { projectId: string }) {
  const userId = useSyncExternalStore(subscribeCachedUserId, getCachedUserId, () => null);
  return <ProjectPopulationPanel key={`${userId ?? "anonymous"}:${projectId}`} projectId={projectId} userId={userId} />;
}

function ProjectPopulationPanel({ projectId, userId }: { projectId: string; userId: string | null }) {
  const [pop, setPop] = useState<BindingPopulation | null>(null);
  const [state, setState] = useState<BindingState>("LOADING");
  const reqId = useRef(0);
  useEffect(() => {
    const mine = ++reqId.current; setPop(null); setState("LOADING");
    if (!projectId.trim() || !userId) { setState(userId ? "NO_BINDING" : "UNAUTHENTICATED"); return; }
    getJSON<BindingPopulation>(`/cockpit/gen3/population/${encodeURIComponent(projectId)}`)
      .then((p) => { if (mine === reqId.current) { setPop(p); setState("ACTIVE"); } })
      .catch((e) => { if (mine === reqId.current) { setPop(null); setState(classify(e)); } });
    return () => { reqId.current++; };
  }, [projectId, userId]);

  if (state !== "ACTIVE" || !pop) {
    return (
      <section className="rounded-2xl border border-slate-200 bg-white p-4">
        <div className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.16em] text-cyan-700"><Database size={14} /> Active modeling dataset</div>
        <div className={`mt-2 flex items-center gap-2 rounded-xl border px-3 py-2 text-xs ${STATE_TONE[state]}`}>
          {state === "LOADING" ? <Loader2 size={12} className="animate-spin" /> : <TriangleAlert size={12} />}
          <span className="font-semibold">{STATE_MSG[state]}</span>
        </div>
      </section>
    );
  }
  const gen3 = pop.generation === "GEN3";
  return (
    <section className="rounded-2xl border border-cyan-300 bg-cyan-50/40 p-4 sm:p-5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.16em] text-cyan-700"><ShieldCheck size={14} /> Active modeling dataset · server authority</div>
        <span className="inline-flex items-center gap-1 rounded-full bg-cyan-600 px-2.5 py-0.5 text-[10px] font-bold uppercase text-white"><CheckCircle2 size={11} /> {pop.generation}</span>
      </div>
      <h3 className="mt-1 text-lg font-semibold text-slate-950">{pop.label}</h3>
      <div className="mt-3 grid gap-2 text-xs sm:grid-cols-2 lg:grid-cols-4">
        <Field label="Registration / version" value={pop.registrationId} />
        <Field label="Content SHA" value={short(pop.datasetContentSha256)} mono />
        <Field label="Target" value={`${pop.target} · ${pop.classCount}-class`} />
        <Field label="Features" value={`${pop.featureCount} governed`} />
        <Field label="Development" value={pop.developmentSeasons.join(", ")} />
        <Field label="Development rows" value={roleRows(pop.developmentRows)} />
        <Field label="Validation" value={String(pop.validationSeason)} />
        <Field label="Validation rows" value={roleRows(pop.validationRows)} />
        <Field label="Sealed" value={`${pop.sealedSeasons.join(", ")} · ${pop.sealedState}`} />
        <Field label="Knowledge time" value={pop.knowledgeTimeSafetyClass.replaceAll("_", " ").toLowerCase()} />
        <Field label="Preprocessing" value={pop.preprocessingContractId.split(":")[0]} />
        <Field label="Temporal contract" value={short(pop.temporalContractId.split(":").pop())} mono />
        {gen3 && <Field label="Quarantine" value={`${pop.quarantineTotal ?? 0} convention anomalies`} />}
      </div>
      {/* Generation-aware population waterfall (Gate 2) */}
      <div className="mt-3 space-y-1.5">
        {pop.waterfall.map((w) => {
          const max = Math.max(1, ...pop.waterfall.map((x) => x.rows));
          const tone = w.kind === "development" ? "bg-cyan-600" : w.kind === "validation" ? "bg-amber-500" : w.kind === "sealed" ? "bg-rose-400" : "bg-slate-400";
          return (
            <div key={w.stage}>
              <div className="flex items-center justify-between text-[11px]"><span className="font-semibold text-slate-700">{w.stage}</span><span className="tabular-nums text-slate-500">{roleRows(w.rows)}</span></div>
              <div className="mt-0.5 h-4 overflow-hidden rounded bg-white"><div className={`h-full ${tone}`} style={{ width: `${(w.rows / max) * 100}%` }} /></div>
            </div>
          );
        })}
      </div>
      <p className="mt-2 text-[11px] text-slate-500">Season roles: {pop.seasons.map((s) => `${s.season} ${s.role.toLowerCase()}`).join(" · ")}. 2025 is sealed — no development distribution or metric is exposed.</p>
    </section>
  );
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
  const userId = useSyncExternalStore(subscribeCachedUserId, getCachedUserId, () => null);
  return <ProjectCatalogSection key={`${userId ?? "anonymous"}:${projectId ?? ""}:${mode}`} mode={mode} projectId={projectId} userId={userId} />;
}

function ProjectCatalogSection({ mode, projectId, userId }: { mode: "warehouse" | "selection"; projectId?: string; userId: string | null }) {
  const { catalog, error } = useGen3Catalog(projectId ?? "");
  const active = useActiveBinding(mode === "selection" ? (projectId ?? "") : "");
  const mounted = useRef(true);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  const [busy, setBusy] = useState<string | null>(null);
  const [bindError, setBindError] = useState<string | null>(null);
  const [changed, setChanged] = useState<string | null>(null); // Gate 9 — dataset-change invalidation

  const select = async (versionId: string) => {
    if (mode !== "selection" || !projectId?.trim() || !userId || !mounted.current || getCachedUserId() !== userId) return;
    const priorVersion = active.state === "ACTIVE" && active.binding ? active.binding.datasetVersionId : null;
    setBusy(versionId); setBindError(null);
    try {
      await postJSON<Binding>("/cockpit/gen3/bind", { projectId, datasetVersionId: versionId });
      if (!mounted.current || getCachedUserId() !== userId) return;
      await active.refresh(); // server wins — re-resolve authoritative binding
      // Gate 9 — a real dataset change supersedes the prior binding and marks all downstream work stale.
      if (priorVersion && priorVersion !== versionId) setChanged(priorVersion);
    } catch (e) { setBindError(String(e)); } finally { setBusy(null); }
  };

  return (
    <section className="sports-panel rounded-2xl border border-slate-200 bg-white p-4 sm:p-5">
      <div className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.16em] text-cyan-700">
        <ShieldCheck size={14} /> {mode === "warehouse" ? "Governed modeling datasets · server catalog" : "Modeling dataset · server authority"}
      </div>
      <h3 className="mt-1 text-lg font-semibold text-slate-950">{mode === "warehouse" ? "Data Warehouse — registered feature views" : "Select the authoritative modeling dataset"}</h3>

      {mode === "selection" && (
        active.state === "ACTIVE" && active.binding ? (
          <div className="mt-2 flex flex-wrap items-center gap-2 rounded-xl border border-emerald-200 bg-emerald-50 px-3 py-2 text-xs text-emerald-800">
            <span className="inline-flex items-center gap-1.5 rounded-full bg-emerald-600 px-2.5 py-0.5 text-[11px] font-bold uppercase text-white"><CheckCircle2 size={12} /> Active binding restored</span>
            <span>Server authority: <b>{active.binding.datasetVersionId.split(":")[0]}</b> · content {short(active.binding.datasetContentSha256)} · dev {active.binding.developmentSeasons.join(",")} · val {active.binding.validationSeason} · sealed {active.binding.sealedSeasons.join(",") || "—"}</span>
            <span className="ml-auto text-[10px] text-emerald-700">server state wins over local cache</span>
          </div>
        ) : (
          <div className={`mt-2 flex items-center gap-2 rounded-xl border px-3 py-2 text-xs ${STATE_TONE[active.state]}`}>
            {active.state === "LOADING" ? <Loader2 size={12} className="animate-spin" /> : <TriangleAlert size={12} />}
            <span className="font-semibold">{STATE_MSG[active.state]}</span>
            {active.state !== "LOADING" && active.state !== "NO_BINDING" && <span className="ml-auto text-[10px] opacity-80">no dataset is silently selected</span>}
          </div>
        )
      )}
      {error && <p className="mt-2 text-xs text-rose-700"><TriangleAlert size={12} className="mr-1 inline" />catalog unavailable: {error}</p>}
      {bindError && <p className="mt-2 text-xs text-rose-700"><TriangleAlert size={12} className="mr-1 inline" />{bindError}</p>}

      {/* Gate 9 — dataset changed: the prior binding is superseded on the server and all downstream work is stale. */}
      {mode === "selection" && changed && (
        <div className="mt-3 rounded-xl border-2 border-amber-400 bg-amber-50 px-3.5 py-3 text-xs text-amber-900">
          <div className="flex items-center gap-2 font-bold uppercase tracking-wide text-amber-800">
            <TriangleAlert size={14} /> Dataset changed — downstream work marked stale
          </div>
          <p className="mt-1.5 text-amber-800">
            The active binding moved from <b>{changed.split(":")[0]}</b> to <b>{active.binding?.datasetVersionId.split(":")[0]}</b>.
            The server superseded the prior binding; any results produced against it are no longer current.
          </p>
          <p className="mt-1 text-amber-800">
            Affected: <b>Model Laboratory</b> candidates · <b>Autopilot</b> leaderboard · <b>Evaluation</b> active candidate · <b>Calibration / Simulation</b>. Re-run modeling under the new binding.
          </p>
          <button onClick={() => setChanged(null)}
            className="mt-2 inline-flex items-center gap-1.5 rounded-lg border border-amber-500 bg-white px-3 py-1.5 text-[11px] font-semibold text-amber-800 hover:bg-amber-100">
            <CheckCircle2 size={12} /> Review updated data
          </button>
        </div>
      )}

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
