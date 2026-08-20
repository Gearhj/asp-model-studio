// Phase 7A.1 — server-authorized Gen-3 run plan + execution binding (additive; does not redesign the
// Model Laboratory). The scientist selects an EXACT immutable dataset version from the server catalog;
// selection becomes a server-issued binding; a run authority carries every contract/content digest; the
// server validates fail-closed, executes on the exact object (never the sealed 2025 object), and the
// result echoes the same authority (UI = SERVER = TRAINING = RESULT).
import { useEffect, useState } from "react";
import { Database, ShieldCheck, Lock, Play, CheckCircle2, TriangleAlert, Loader2 } from "lucide-react";
import { getJSON, postJSON } from "../../lib/api";

type CatalogEntry = {
  datasetVersionId: string; label: string; generation: string; status: string; selectable: boolean;
  logicalContentSha256: string; seasons: number[]; developmentSeasons: number[]; validationSeason: number | null;
  sealedSeasons: number[]; rows: number; featureCount?: number; target: string;
};
type Binding = { bindingId: string; datasetVersionId: string; datasetContentSha256: string; generation: string;
  developmentSeasons: number[]; validationSeason: number; sealedSeasons: number[];
  targetContractId: string; temporalContractId: string; preprocessingContractId: string; featureContractId: string };
type Authority = { runAuthorityId: string; canonicalEffectiveConfigSha256: string; modelFamily: string };
type Evidence = {
  experimentRunId: string; runAuthorityId: string; canonicalEffectiveConfigSha256: string;
  datasetVersionId: string; datasetContentSha256: string; generation: string; developmentSeasons: number[];
  developmentRows: number; validationSeason: number; validationRows: number; seasonsInObject: number[];
  sealedSeasonsLoaded: number[]; modelFamily: string; convergence: any; metrics: Record<string, number>;
  runtimeSeconds: number;
};

const short = (s?: string) => (s ? s.slice(0, 12) + "…" : "—");
const FAMILIES = [{ id: "governed_logistic", label: "Governed multinomial logistic" }, { id: "governed_hgb", label: "Governed HGB (deterministic)" }];

export default function Gen3AuthorityPanel({ projectId }: { projectId: string }) {
  const [catalog, setCatalog] = useState<CatalogEntry[]>([]);
  const [versionId, setVersionId] = useState("");
  const [family, setFamily] = useState("governed_hgb");
  const [binding, setBinding] = useState<Binding | null>(null);
  const [authority, setAuthority] = useState<Authority | null>(null);
  const [result, setResult] = useState<Evidence | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [activated, setActivated] = useState(false);

  useEffect(() => {
    (async () => {
      try {
        await postJSON("/cockpit/gen3/register", {}); // idempotent registration
        const res = await getJSON<{ datasets: CatalogEntry[] }>("/cockpit/gen3/catalog");
        setCatalog(res.datasets);
        const first = res.datasets.find((d) => d.selectable);
        if (first) setVersionId(first.datasetVersionId);
      } catch (e) { setError(String(e)); }
    })();
  }, []);

  const entry = catalog.find((d) => d.datasetVersionId === versionId) || null;
  const reset = () => { setBinding(null); setAuthority(null); setResult(null); setActivated(false); };

  const bind = async () => {
    setBusy("bind"); setError(null); reset();
    try { setBinding(await postJSON<Binding>("/cockpit/gen3/bind", { projectId, datasetVersionId: versionId })); }
    catch (e) { setError(String(e)); } finally { setBusy(null); }
  };
  const authorizeAndRun = async () => {
    if (!binding) return;
    setBusy("run"); setError(null); setResult(null); setActivated(false);
    try {
      const au = await postJSON<Authority>("/cockpit/gen3/run-authority", { projectId, bindingId: binding.bindingId, modelFamily: family });
      setAuthority(au);
      setResult(await postJSON<Evidence>("/cockpit/gen3/execute", { projectId, runAuthorityId: au.runAuthorityId }));
    } catch (e) { setError(String(e)); } finally { setBusy(null); }
  };
  const activate = async () => {
    if (!result) return;
    setBusy("activate"); setError(null);
    try { await postJSON("/cockpit/gen3/activate", { projectId, runId: result.experimentRunId }); setActivated(true); }
    catch (e) { setError(String(e)); } finally { setBusy(null); }
  };

  const echoVerified = !!(result && authority && result.runAuthorityId === authority.runAuthorityId &&
    result.canonicalEffectiveConfigSha256 === authority.canonicalEffectiveConfigSha256);

  return (
    <section className="rounded-2xl border border-slate-800 bg-slate-950 p-4 text-white">
      <div className="flex items-center gap-2 text-[10px] font-semibold uppercase tracking-[0.16em] text-cyan-300">
        <ShieldCheck size={14} /> Server-authorized run · UI = server = training = result
      </div>
      <h3 className="mt-1 text-lg font-semibold">Gen-3 dataset authority &amp; execution</h3>

      {/* Dataset version selection from the server catalog (Gate 2/3) */}
      <div className="mt-3 grid gap-2 sm:grid-cols-[1fr_auto_auto]">
        <select value={versionId} onChange={(e) => { setVersionId(e.target.value); reset(); }}
          className="rounded-lg border border-white/20 bg-white/10 px-3 py-2 text-sm">
          {catalog.map((d) => (
            <option key={d.datasetVersionId} value={d.datasetVersionId} disabled={!d.selectable}>
              {d.label} {d.selectable ? "" : "· SEALED / restricted"}
            </option>
          ))}
        </select>
        <select value={family} onChange={(e) => setFamily(e.target.value)} className="rounded-lg border border-white/20 bg-white/10 px-3 py-2 text-sm">
          {FAMILIES.map((f) => <option key={f.id} value={f.id}>{f.label}</option>)}
        </select>
        <button onClick={bind} disabled={!entry?.selectable || busy === "bind"}
          className="inline-flex items-center gap-1.5 rounded-lg bg-cyan-500 px-3.5 py-2 text-sm font-semibold text-slate-950 hover:bg-cyan-400 disabled:opacity-50">
          {busy === "bind" ? <Loader2 size={14} className="animate-spin" /> : <Database size={14} />} Select &amp; bind (server)
        </button>
      </div>

      {error && <div className="mt-3 rounded-lg border border-rose-400/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-200"><TriangleAlert size={12} className="mr-1 inline" />{error}</div>}

      {/* Run plan (Gate 10) — server binding authority */}
      {binding && entry && (
        <div className="mt-4 rounded-xl border border-white/15 bg-white/5 p-4">
          <div className="flex items-center justify-between">
            <div className="text-xs font-semibold uppercase tracking-wide text-cyan-200">Run plan</div>
            <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-bold uppercase ${binding ? "bg-emerald-600 text-white" : "bg-amber-500 text-white"}`}>
              <CheckCircle2 size={11} /> Run authority: {binding ? "verified" : "pending"}
            </span>
          </div>
          <div className="mt-2 grid gap-2 text-xs sm:grid-cols-2 lg:grid-cols-3">
            <F label="Dataset" value={entry.label} />
            <F label="Version" value={binding.datasetVersionId.split(":")[0]} />
            <F label="Content SHA" value={short(binding.datasetContentSha256)} mono />
            <F label="Target" value={`${binding.targetContractId ? "outcome · 8-class" : entry.target}`} />
            <F label="Development" value={`${binding.developmentSeasons.join(", ")}`} />
            <F label="Validation" value={`${binding.validationSeason} · ${entry.rows ? "" : ""}182,449 rows`} />
            <F label="Sealed OOT" value={`${binding.sealedSeasons.join(", ") || "—"} · LOCKED`} />
            <F label="Features" value={`${entry.featureCount ?? 22} governed base`} />
            <F label="Preprocessing" value="fold-mean impute + standardize" />
            <F label="Temporal contract" value={short(binding.temporalContractId?.split(":").pop())} mono />
          </div>
          <button onClick={authorizeAndRun} disabled={busy === "run"}
            className="mt-3 inline-flex items-center gap-1.5 rounded-lg bg-emerald-500 px-4 py-2 text-sm font-semibold text-slate-950 hover:bg-emerald-400 disabled:opacity-50">
            {busy === "run" ? <Loader2 size={14} className="animate-spin" /> : <Play size={14} />} Authorize &amp; run (2024 validation; 2025 sealed)
          </button>
        </div>
      )}

      {/* Result authority echo (Gate 11) */}
      {result && (
        <div className="mt-4 rounded-xl border border-emerald-400/30 bg-emerald-400/5 p-4">
          <div className="flex flex-wrap items-center gap-2">
            <span className="inline-flex items-center gap-1.5 rounded-full bg-emerald-600 px-2.5 py-0.5 text-[11px] font-bold uppercase text-white">
              <ShieldCheck size={12} /> {echoVerified ? "Authority verified" : "Echo mismatch"}
            </span>
            <span className="inline-flex items-center gap-1 text-[11px] text-emerald-200"><Lock size={11} /> 2025 not loaded ({result.sealedSeasonsLoaded.length === 0 ? "confirmed" : "VIOLATION"})</span>
          </div>
          <div className="mt-2 grid gap-2 text-xs sm:grid-cols-2 lg:grid-cols-3">
            <F label="Experiment run" value={short(result.experimentRunId)} mono />
            <F label="Run authority" value={short(result.runAuthorityId)} mono />
            <F label="Config fingerprint" value={short(result.canonicalEffectiveConfigSha256)} mono />
            <F label="Generation" value={result.generation} />
            <F label="Development" value={`${result.developmentSeasons.join(", ")} · ${result.developmentRows.toLocaleString()} rows`} />
            <F label="Validation 2024" value={`${result.validationRows.toLocaleString()} rows`} />
            <F label="Seasons in object" value={result.seasonsInObject.join(", ")} />
            <F label="Val log loss" value={result.metrics.logLoss?.toFixed(6)} />
            <F label="Top-1" value={result.metrics.top1Accuracy?.toFixed(4)} />
          </div>
          <button onClick={activate} disabled={busy === "activate" || activated}
            className="mt-3 inline-flex items-center gap-1.5 rounded-lg border border-white/25 px-3.5 py-2 text-sm font-semibold text-white hover:bg-white/10 disabled:opacity-50">
            {activated ? <><CheckCircle2 size={14} className="text-emerald-300" /> Activated for review</> : "Activate candidate for review"}
          </button>
        </div>
      )}
    </section>
  );
}

function F({ label, value, mono }: { label: string; value?: string; mono?: boolean }) {
  return (
    <div className="rounded-lg border border-white/10 bg-white/5 px-2.5 py-1.5">
      <div className="text-[9px] font-semibold uppercase text-slate-400">{label}</div>
      <div className={`mt-0.5 font-semibold ${mono ? "font-mono text-[11px]" : ""}`}>{value ?? "—"}</div>
    </div>
  );
}
