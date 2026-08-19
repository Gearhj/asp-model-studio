// Governed data preview of the plate-appearance modeling matrix. Reused by the guided workflow
// Step 2 (Baseball Data Evidence) and the cockpit Step 02 (Data & Population) so the scientist
// actually SEES the data before modeling. Bounded (≤50 rows), auth+project scoped via the shared
// API client; no file-path access, no synthetic rows.
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Database, Table2, ListTree, ExternalLink } from "lucide-react";
import { getJSON } from "../../lib/api";
import type { DataPreview } from "./cockpitApi";
import { Card, MetricCard, Segmented, Pill, BarChart, fmt } from "./cockpitUi";

const ROLE_TONE: Record<string, "rose" | "cyan" | "violet" | "amber" | "slate" | "emerald"> = {
  TARGET: "rose", TIME: "cyan", GROUPING: "violet", IDENTIFIER: "amber", FEATURE: "emerald", EXCLUDED: "slate",
};

function shortId(v: any): string {
  const s = String(v ?? "");
  if (s.length <= 14) return s;
  return `${s.slice(0, 6)}…${s.slice(-4)}`;
}

export default function DataPreviewPanel({ title = "Data preview", showWarehouseLink = true }: { title?: string; showWarehouseLink?: boolean }) {
  const [season, setSeason] = useState<string>("all");
  const [sample, setSample] = useState<"head" | "random">("head");
  const [search, setSearch] = useState("");
  const [state, setState] = useState<{ status: string; data?: DataPreview; error?: string }>({ status: "loading" });

  useEffect(() => {
    let alive = true;
    setState({ status: "loading" });
    const q = new URLSearchParams({ limit: "25", sample });
    if (season !== "all") q.set("season", season);
    getJSON<DataPreview>(`/cockpit/data-preview?${q.toString()}`)
      .then((d) => alive && setState({ status: "ready", data: d }))
      .catch((e) => alive && setState({ status: "error", error: String(e) }));
    return () => { alive = false; };
  }, [season, sample]);

  if (state.status === "error") {
    const is404 = /\b404\b/.test(state.error || "");
    return (
      <Card title={title} icon={Database}>
        <div className="rounded-xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-800">
          <div className="font-semibold">Could not load the data preview.</div>
          <p className="mt-1">{is404 ? "The modeling API returned 404 — the backend likely needs a restart to load the /api/cockpit routes." : "The backend may be unavailable; confirm it is running and reload."}</p>
          <p className="mt-2 font-mono text-xs text-rose-500">{state.error}</p>
        </div>
      </Card>
    );
  }
  const d = state.data;
  const cols = d ? (search ? d.previewColumns.filter((c) => c.toLowerCase().includes(search.toLowerCase())) : d.previewColumns) : [];
  const schema = d ? (search ? d.schema.filter((s) => s.name.toLowerCase().includes(search.toLowerCase())) : d.schema) : [];

  return (
    <Card title={title} description="The governed plate-appearance modeling matrix — real registered rows, bounded to 25." icon={Database}
      action={showWarehouseLink ? <Link to="/data-warehouse?from=mlb-workflow&step=2" className="inline-flex items-center gap-1.5 rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-xs font-semibold text-slate-700 hover:bg-slate-50">Open Full Data Warehouse <ExternalLink size={13} /></Link> : null}>
      {!d ? (
        <div className="flex items-center gap-3 py-6 text-sm text-slate-500"><span className="h-4 w-4 animate-spin rounded-full border-2 border-slate-300 border-t-cyan-600" /> Loading governed rows…</div>
      ) : (
        <div className="space-y-4">
          {/* profile */}
          <div className="grid gap-3 sm:grid-cols-3 lg:grid-cols-6">
            <MetricCard label="Rows" value={fmt.int(d.totalRows)} detail={d.grain.replace("_", " ").toLowerCase()} />
            <MetricCard label="Columns" value={String(d.columns)} detail={`${d.numericFeatureColumns} num · ${d.categoricalFeatureColumns} cat`} />
            <MetricCard label="Seasons" value={d.seasons.join(", ")} />
            <MetricCard label="Target" value="8-class PA" detail={d.target} />
            <MetricCard label="Feature missing" value={fmt.pct(d.featureMissingPct)} />
            <MetricCard label="Matrix" value="Feature view" detail="MLB_PA_V1" />
          </div>

          {/* dev/val/frozen split */}
          <div className="grid gap-2 sm:grid-cols-3">
            {d.splitCounts.map((s) => (
              <div key={s.season} className="rounded-xl border border-slate-200 bg-slate-50 p-3">
                <div className="flex items-center justify-between"><span className="text-sm font-semibold text-slate-900">{s.season}</span>
                  <Pill label={s.role.replace("_", " ")} tone={s.role === "frozen_final" ? "rose" : s.role === "validation" ? "amber" : "emerald"} /></div>
                <div className="mt-1 text-lg font-semibold tabular-nums text-slate-900">{fmt.int(s.rows)}</div>
              </div>
            ))}
          </div>

          {/* target distribution */}
          <div>
            <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">Target distribution{d.season ? ` · ${d.season}` : ""}</div>
            <BarChart categories={d.targetDistribution.map((t) => t.class)} values={d.targetDistribution.map((t) => t.share)} height={180} valueFmt={(v) => fmt.pct(v)} />
          </div>

          {/* controls */}
          <div className="flex flex-wrap items-end gap-3">
            <div><div className="mb-1 text-xs font-semibold uppercase text-slate-500">Season</div>
              <Segmented value={season} onChange={setSeason} options={[{ value: "all", label: "All" }, { value: "2023", label: "2023" }, { value: "2024", label: "2024" }, { value: "2025", label: "2025" }]} /></div>
            <div><div className="mb-1 text-xs font-semibold uppercase text-slate-500">Sample</div>
              <Segmented value={sample} onChange={setSample as any} options={[{ value: "head", label: "First 25" }, { value: "random", label: "Random" }]} /></div>
            <label className="flex flex-col gap-1 text-xs"><span className="font-semibold uppercase text-slate-500">Column search</span>
              <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="filter columns" className="rounded-lg border border-slate-300 px-2.5 py-1.5 text-sm" /></label>
          </div>

          {/* row preview */}
          <div>
            <div className="mb-1 flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-slate-500"><Table2 size={13} /> {d.rows.length} rows ({d.sample})</div>
            <div className="max-h-96 overflow-auto rounded-lg border border-slate-200">
              <table className="w-full min-w-[900px] text-left text-xs">
                <thead className="sticky top-0 bg-slate-50"><tr>{cols.map((c) => <th key={c} className="border-b border-slate-200 px-2 py-1.5 font-semibold text-slate-600">{c.replace("_canonical_player_uuid", "_uuid")}</th>)}</tr></thead>
                <tbody>{d.rows.map((row, i) => (
                  <tr key={i} className="hover:bg-cyan-50/40">{cols.map((c) => (
                    <td key={c} className={`whitespace-nowrap border-b border-slate-100 px-2 py-1 tabular-nums ${c === "outcome" ? "font-semibold text-slate-900" : "text-slate-600"}`} title={String(row[c] ?? "")}>
                      {c.includes("uuid") || c === "game_id" ? shortId(row[c]) : row[c] === null ? <span className="text-slate-300">null</span> : String(row[c])}
                    </td>))}</tr>))}</tbody>
              </table>
            </div>
          </div>

          {/* schema under disclosure */}
          <details className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-3">
            <summary className="cursor-pointer text-sm font-semibold text-slate-700"><span className="inline-flex items-center gap-1.5"><ListTree size={14} /> Schema &amp; column roles ({schema.length})</span></summary>
            <div className="mt-3 max-h-80 overflow-auto">
              <table className="w-full min-w-[560px] text-left text-xs">
                <thead className="sticky top-0 bg-slate-50"><tr>{["Column", "Type", "Role", "Missing %", "Example"].map((h) => <th key={h} className="border-b border-slate-200 px-2 py-1.5 font-semibold text-slate-500">{h}</th>)}</tr></thead>
                <tbody>{schema.map((s) => (
                  <tr key={s.name}><td className="border-b border-slate-100 px-2 py-1.5 font-semibold text-slate-800">{s.name}</td>
                    <td className="border-b border-slate-100 px-2 py-1.5 text-slate-500">{s.type}</td>
                    <td className="border-b border-slate-100 px-2 py-1.5"><Pill label={s.role} tone={ROLE_TONE[s.role] || "slate"} /></td>
                    <td className="border-b border-slate-100 px-2 py-1.5 tabular-nums">{fmt.pct(s.missingPct)}</td>
                    <td className="max-w-40 truncate border-b border-slate-100 px-2 py-1.5 text-slate-500" title={String(s.example ?? "")}>{s.example === null ? "—" : String(s.example)}</td></tr>))}</tbody>
              </table>
            </div>
          </details>
          <p className="text-xs text-slate-500">{d.note}</p>
        </div>
      )}
    </Card>
  );
}
