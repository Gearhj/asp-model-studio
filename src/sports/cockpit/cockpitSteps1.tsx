// Cockpit workflow steps 01–08: Objective, Data & Population, Profile, Outliers, Missing,
// Feature Engineering, Segmentation, Temporal Split.
import { useMemo, useState } from "react";
import {
  Target, Database, ScanSearch, TriangleAlert, CircleSlash, Wand2, Boxes, CalendarClock,
  X, ArrowUpDown, Check,
} from "lucide-react";
import {
  useEndpoint, usePost, useCockpitStore, ALL_FEATURES,
  type Objective, type Population, type Profile, type FeatureDetail, type OutlierSummary,
  type MissingSummary, type TemporalSplit, type FeatureCatalog,
  type EngineeredSpec, type EngineeredProfile, type AblationResult,
} from "./cockpitApi";
import {
  Card, Pill, MetricCard, Button, Segmented, NumberField, LoadGate, BarChart, Histogram,
  BeforeAfter, LineChart, ScatterClusters, fmt,
} from "./cockpitUi";
import DataPreviewPanel from "./DataPreviewPanel";

const ROLE_TONE: Record<string, "cyan" | "violet" | "amber"> = { context: "cyan", batter: "violet", pitcher: "amber" };

// ============================================================ 01 Objective
export function ObjectiveStep() {
  const obj = useEndpoint<Objective>("/cockpit/objective");
  const { notes, setNote, markSaved, savedSteps } = useCockpitStore();
  return (
    <LoadGate state={obj}>
      {obj.data && (
        <div className="space-y-5">
          <div className="grid gap-3 sm:grid-cols-4">
            <MetricCard label="Objective" value="PA Outcome" detail="8-class multinomial" />
            <MetricCard label="Prediction unit" value="Plate Appearance" detail={fmt.int(obj.data.totalRows) + " PAs"} />
            <MetricCard label="Downstream use" value="Game Simulator" detail="Whole-game Monte Carlo" />
            <MetricCard label="Champion" value="D3 · C4" detail={obj.data.champion.family} />
          </div>
          <Card title="Target class distribution" description="Frozen eight-class order. Class imbalance is severe — BIP_OUT dominates; TRIPLE is rare." icon={Target}>
            <BarChart
              categories={obj.data.targetDistribution.map((d) => d.class)}
              values={obj.data.targetDistribution.map((d) => d.share)}
              valueFmt={(v) => fmt.pct(v)}
              height={240}
            />
            <div className="mt-3 overflow-x-auto">
              <table className="w-full min-w-[560px] text-left text-xs">
                <thead><tr className="text-slate-500">{["Class", "Count", "Share"].map((h) => <th key={h} className="border-b border-slate-200 px-2 py-1.5 font-semibold">{h}</th>)}</tr></thead>
                <tbody>{obj.data.targetDistribution.map((d) => (
                  <tr key={d.class}><td className="border-b border-slate-100 px-2 py-1.5 font-semibold text-slate-800">{d.class}</td>
                    <td className="border-b border-slate-100 px-2 py-1.5 tabular-nums">{fmt.int(d.count)}</td>
                    <td className="border-b border-slate-100 px-2 py-1.5 tabular-nums">{fmt.pct(d.share, 2)}</td></tr>))}</tbody>
              </table>
            </div>
          </Card>
          <div className="grid gap-4 lg:grid-cols-2">
            <Card title="Current champion of record" description="Registered D3 candidate C4 (frozen evidence)." icon={Target}>
              <div className="grid grid-cols-2 gap-3 text-sm">
                <RefBlock title="2024 validation" m={obj.data.champion.reference.val2024} />
                <RefBlock title="2025 frozen final" m={obj.data.champion.reference.frozen2025} />
              </div>
              <div className="mt-3 flex flex-wrap gap-2">
                <Pill label={obj.data.champion.status} tone="emerald" />
                <Pill label={`${obj.data.champion.featureCount} features`} />
                <Pill label={obj.data.maturity} tone="cyan" />
              </div>
            </Card>
            <Card title="Research hypothesis" description="Editable rationale carried with cockpit experiments." icon={Target}
              action={<Button size="sm" tone={savedSteps.objective ? "ghost" : "primary"} onClick={() => markSaved("objective")}>{savedSteps.objective ? "Saved ✓" : "Save objective"}</Button>}>
              <textarea value={notes.hypothesis ?? "Can a scientist-tuned challenger (feature selection, outlier/missing policy, or an alternate family) beat the D3 C4 champion on 2024 validation and, more importantly, improve the whole-game simulator?"}
                onChange={(e) => setNote("hypothesis", e.target.value)}
                className="h-40 w-full resize-none rounded-lg border border-slate-300 p-3 text-sm text-slate-800 focus:border-cyan-500 focus:outline-none" />
              <p className="mt-2 text-xs text-slate-500">Dataset authority: {obj.data.datasetAuthority.registration} · {obj.data.datasetAuthority.featureView}</p>
            </Card>
          </div>
        </div>
      )}
    </LoadGate>
  );
}
function RefBlock({ title, m }: { title: string; m: { logLoss: number; brierScore: number; topLabelEce: number } }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-slate-50 p-3">
      <div className="text-xs font-semibold uppercase text-slate-500">{title}</div>
      <div className="mt-1 space-y-0.5 text-slate-700"><div>Log loss <b className="tabular-nums">{fmt.n(m.logLoss)}</b></div>
        <div>Brier <b className="tabular-nums">{fmt.n(m.brierScore)}</b></div><div>ECE <b className="tabular-nums">{fmt.n(m.topLabelEce)}</b></div></div>
    </div>
  );
}

// ============================================================ 02 Data & Population
export function DataPopulationStep() {
  const pop = useEndpoint<Population>("/cockpit/population");
  return (
    <LoadGate state={pop}>
      {pop.data && (
        <div className="space-y-5">
          <div className="grid gap-3 sm:grid-cols-4">
            <MetricCard label="Total PAs" value={fmt.int(pop.data.totalRows)} detail="2023–2025" />
            <MetricCard label="Candidate predictors" value={String(pop.data.candidatePredictors)} detail="governed feature view" />
            <MetricCard label="Development" value={fmt.int(pop.data.perSeason.find((s) => s.role === "development")?.rows)} detail="2023" />
            <MetricCard label="Frozen final" value={fmt.int(pop.data.perSeason.find((s) => s.role === "frozen_final")?.rows)} detail="2025 · protected" />
          </div>
          <Card title="Season populations" description="Real governed row / game / player counts per season." icon={Database}>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[620px] text-left text-sm">
                <thead><tr className="text-slate-500">{["Season", "Role", "Plate appearances", "Games", "Batters"].map((h) => <th key={h} className="border-b border-slate-200 px-3 py-2 text-xs font-semibold uppercase">{h}</th>)}</tr></thead>
                <tbody>{pop.data.perSeason.map((s) => (
                  <tr key={s.season}><td className="border-b border-slate-100 px-3 py-2 font-semibold text-slate-900">{s.season}</td>
                    <td className="border-b border-slate-100 px-3 py-2"><Pill label={s.role.replace("_", " ")} tone={s.role === "frozen_final" ? "rose" : s.role === "validation" ? "amber" : "emerald"} /></td>
                    <td className="border-b border-slate-100 px-3 py-2 tabular-nums">{fmt.int(s.rows)}</td>
                    <td className="border-b border-slate-100 px-3 py-2 tabular-nums">{fmt.int(s.games)}</td>
                    <td className="border-b border-slate-100 px-3 py-2 tabular-nums">{fmt.int(s.batters)}</td></tr>))}</tbody>
              </table>
            </div>
          </Card>
          <div className="grid gap-4 lg:grid-cols-2">
            <Card title="Population funnel" description="Source PAs → resolved feature view → development population." icon={Database}>
              <div className="space-y-2">
                {pop.data.waterfall.map((w, i) => {
                  const pctW = (w.rows / (pop.data!.waterfall[0]?.rows || 1)) * 100;
                  return (
                    <div key={i}>
                      <div className="flex items-center justify-between text-xs"><span className="font-semibold text-slate-700">{w.stage}</span><span className="tabular-nums text-slate-500">{fmt.int(w.rows)}</span></div>
                      <div className="mt-1 h-6 overflow-hidden rounded bg-slate-100"><div className={`h-full ${w.kind === "final" ? "bg-cyan-600" : w.kind === "source" ? "bg-slate-800" : "bg-slate-400"}`} style={{ width: `${pctW}%` }} /></div>
                    </div>
                  );
                })}
              </div>
            </Card>
            <Card title="Temporal policy & known limitations" description="Development / validation / frozen governance." icon={CalendarClock}>
              <div className="flex flex-wrap gap-2">
                <Pill label={`Dev ${pop.data.temporalPolicy.development.join(",")}`} tone="emerald" />
                <Pill label={`Val ${pop.data.temporalPolicy.validation}`} tone="amber" />
                <Pill label={`Frozen ${pop.data.temporalPolicy.frozenFinal}`} tone="rose" />
              </div>
              <ul className="mt-3 space-y-2 text-xs text-slate-600">
                {pop.data.knownLimitations.map((l, i) => <li key={i} className="flex gap-2"><span className="mt-1 h-1.5 w-1.5 shrink-0 rounded-full bg-amber-400" />{l}</li>)}
              </ul>
            </Card>
          </div>
          <DataPreviewPanel title="Modeling matrix preview" showWarehouseLink={false} />
        </div>
      )}
    </LoadGate>
  );
}

// ============================================================ 03 Data Profile / Predictor Screening
export function ProfileStep() {
  const prof = useEndpoint<Profile>("/cockpit/profile");
  const { config, toggleFeature } = useCockpitStore();
  const [sort, setSort] = useState<{ key: string; dir: 1 | -1 }>({ key: "maxIv", dir: -1 });
  const [detail, setDetail] = useState<string | null>(null);

  const rows = useMemo(() => {
    if (!prof.data) return [];
    const val = (r: any) => ({ name: r.name, missingPct: r.missingPct, outlierCount: r.outlierCount, maxIv: r.iv.maxIv, meanIv: r.iv.meanIv, mi: r.mi, drift: r.drift ?? 0 } as any)[sort.key];
    return [...prof.data.features].sort((a, b) => (val(a) > val(b) ? sort.dir : val(a) < val(b) ? -sort.dir : 0));
  }, [prof.data, sort]);

  const Th = ({ k, label }: { k: string; label: string }) => (
    <th className="cursor-pointer border-b border-slate-200 px-2 py-2 text-xs font-semibold uppercase text-slate-500 hover:text-slate-900"
      onClick={() => setSort((s) => ({ key: k, dir: s.key === k ? (s.dir === 1 ? -1 : 1) : -1 }))}>
      <span className="inline-flex items-center gap-1">{label}<ArrowUpDown size={11} className={sort.key === k ? "text-cyan-600" : "text-slate-300"} /></span>
    </th>
  );

  return (
    <LoadGate state={prof}>
      {prof.data && (
        <div className="space-y-4">
          <div className="grid gap-3 sm:grid-cols-4">
            <MetricCard label="Predictors profiled" value={String(prof.data.features.length)} detail="all candidate features" />
            <MetricCard label="Selected" value={String(config.features.length)} detail="in experiment feature set" />
            <MetricCard label="IV method" value="1-vs-rest WOE" detail="development deciles" />
            <MetricCard label="MI sample" value={fmt.int(prof.data.miSampleRows)} detail="dev rows (bounded)" />
          </div>
          <Card title="Predictor screening" description="Sort by any column. Click a feature for detail. Include/exclude toggles the experiment feature set." icon={ScanSearch}>
            <div className="max-h-[540px] overflow-auto rounded-lg border border-slate-200">
              <table className="w-full min-w-[860px] text-left text-xs">
                <thead className="sticky top-0 bg-slate-50">
                  <tr>
                    <th className="border-b border-slate-200 px-2 py-2 text-xs font-semibold uppercase text-slate-500">Feature</th>
                    <th className="border-b border-slate-200 px-2 py-2 text-xs font-semibold uppercase text-slate-500">Role</th>
                    <Th k="missingPct" label="Miss%" /><Th k="outlierCount" label="Outliers" />
                    <Th k="maxIv" label="Max IV" /><Th k="meanIv" label="Mean IV" /><Th k="mi" label="MI" /><Th k="drift" label="Drift" />
                    <th className="border-b border-slate-200 px-2 py-2 text-xs font-semibold uppercase text-slate-500">Include</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r) => {
                    const included = config.features.includes(r.name);
                    return (
                      <tr key={r.name} className="hover:bg-cyan-50/40">
                        <td className="border-b border-slate-100 px-2 py-1.5"><button className="font-semibold text-slate-800 hover:text-cyan-700 hover:underline" onClick={() => setDetail(r.name)}>{r.name}</button>
                          <span className="ml-1 text-[10px] uppercase text-slate-400">{r.kind}</span></td>
                        <td className="border-b border-slate-100 px-2 py-1.5"><Pill label={r.role} tone={ROLE_TONE[r.role]} /></td>
                        <td className="border-b border-slate-100 px-2 py-1.5 tabular-nums">{fmt.pct(r.missingPct)}</td>
                        <td className="border-b border-slate-100 px-2 py-1.5 tabular-nums">{fmt.int(r.outlierCount)}</td>
                        <td className="border-b border-slate-100 px-2 py-1.5 tabular-nums font-semibold text-slate-900">{fmt.n(r.iv.maxIv, 3)}<span className="ml-1 text-[10px] text-slate-400">{r.iv.maxIvClass?.slice(0, 3)}</span></td>
                        <td className="border-b border-slate-100 px-2 py-1.5 tabular-nums">{fmt.n(r.iv.meanIv, 3)}</td>
                        <td className="border-b border-slate-100 px-2 py-1.5 tabular-nums">{fmt.n(r.mi, 4)}</td>
                        <td className="border-b border-slate-100 px-2 py-1.5 tabular-nums">{fmt.n(r.drift, 2)}</td>
                        <td className="border-b border-slate-100 px-2 py-1.5">
                          <button onClick={() => toggleFeature(r.name)} className={`inline-flex h-5 w-5 items-center justify-center rounded border ${included ? "border-cyan-600 bg-cyan-600 text-white" : "border-slate-300 bg-white"}`}>
                            {included ? <Check size={13} /> : null}
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            <p className="mt-2 text-xs text-slate-500">{prof.data.ivMethod}. IV is screening evidence, not automatic inclusion.</p>
          </Card>
          {detail && <FeatureDetailDrawer name={detail} onClose={() => setDetail(null)} />}
        </div>
      )}
    </LoadGate>
  );
}

function FeatureDetailDrawer({ name, onClose }: { name: string; onClose: () => void }) {
  const d = useEndpoint<FeatureDetail>(`/cockpit/profile/feature/${name}`, [name]);
  return (
    <div className="fixed inset-0 z-40 flex justify-end bg-slate-900/30" onClick={onClose}>
      <div className="h-full w-full max-w-2xl overflow-y-auto bg-white shadow-2xl" onClick={(e) => e.stopPropagation()}>
        <div className="sticky top-0 flex items-center justify-between border-b border-slate-200 bg-white px-5 py-3">
          <div><h3 className="font-semibold text-slate-950">{name}</h3><p className="text-xs text-slate-500">{d.data?.role} · {d.data?.kind}</p></div>
          <button onClick={onClose} className="rounded-lg p-1.5 text-slate-500 hover:bg-slate-100"><X size={18} /></button>
        </div>
        <div className="space-y-4 p-5">
          <LoadGate state={d}>
            {d.data && (<>
              {d.data.histogram.length > 0 && <div><div className="mb-1 text-xs font-semibold uppercase text-slate-500">Distribution</div><Histogram bins={d.data.histogram} /></div>}
              {Object.keys(d.data.yoyHistogram).length > 0 && d.data.histogram.length > 0 && (
                <div><div className="mb-1 text-xs font-semibold uppercase text-slate-500">Year-over-year distribution</div>
                  <LineChart categories={d.data.histogram.map((_, i) => String(i))}
                    series={Object.entries(d.data.yoyHistogram).map(([yr, arr], i) => ({ name: yr, data: arr as number[], color: ["#0891b2", "#f59e0b", "#e11d48"][i % 3] }))} height={160} /></div>
              )}
              <div className="grid gap-3 sm:grid-cols-2">
                <div className="rounded-lg border border-slate-200 p-3"><div className="text-xs font-semibold uppercase text-slate-500">Missingness</div><div className="mt-1 text-2xl font-semibold tabular-nums text-slate-900">{fmt.pct(d.data.missingPct)}</div><div className="text-xs text-slate-500">{fmt.int(d.data.missing)} rows</div></div>
                <div className="rounded-lg border border-slate-200 p-3"><div className="text-xs font-semibold uppercase text-slate-500">Max-IV class</div><div className="mt-1 text-lg font-semibold text-slate-900">{d.data.iv.maxIvClass}</div><div className="text-xs text-slate-500">IV {fmt.n(d.data.iv.maxIv, 3)}</div></div>
              </div>
              {d.data.box && (
                <div className="rounded-lg border border-slate-200 p-3 text-xs"><div className="mb-1 font-semibold uppercase text-slate-500">Five-number summary</div>
                  <div className="grid grid-cols-5 gap-2 tabular-nums text-slate-700">
                    {[["min", d.data.box.min], ["q1", d.data.box.q1], ["med", d.data.box.median], ["q3", d.data.box.q3], ["max", d.data.box.max]].map(([k, v]) => <div key={k as string}><div className="text-slate-400">{k}</div><div className="font-semibold">{fmt.n(v as number, 2)}</div></div>)}
                  </div></div>
              )}
              <div><div className="mb-1 text-xs font-semibold uppercase text-slate-500">Target-conditioned mean (development)</div>
                <BarChart categories={d.data.targetConditioned.map((t) => t.class)} values={d.data.targetConditioned.map((t) => t.mean ?? 0)} height={180} valueFmt={(v) => fmt.n(v, 3)} /></div>
              {d.data.ivBins.length > 0 && (
                <div><div className="mb-1 text-xs font-semibold uppercase text-slate-500">Event rate by IV bin · {d.data.ivBinsMaxClass}</div>
                  <BarChart categories={d.data.ivBins.map((b) => `b${b.bin}`)} values={d.data.ivBins.map((b) => b.eventRate)} height={160} color="#7c3aed" valueFmt={(v) => fmt.pct(v)} /></div>
              )}
            </>)}
          </LoadGate>
        </div>
      </div>
    </div>
  );
}

// ============================================================ 04 Outliers
export function OutliersStep() {
  const { config, setOutlierPolicy, markSaved, savedSteps } = useCockpitStore();
  const [method, setMethod] = useState(config.outlierPolicy.globalMethod === "none" ? "iqr" : config.outlierPolicy.globalMethod);
  const [k, setK] = useState(config.outlierPolicy.params?.k ?? 3);
  const post = usePost<OutlierSummary>();
  const preview = () => post.run("/cockpit/outliers", { policy: { globalMethod: method, params: { k }, overrides: {} } });
  const save = () => { setOutlierPolicy({ globalMethod: method, params: { k }, overrides: {} }); markSaved("outliers"); };

  return (
    <div className="space-y-4">
      <Card title="Outlier treatment" description="Fitted fold-local on development (2023) only. Preview before saving. Binary/categorical variables are never capped." icon={TriangleAlert}
        action={<Pill label="FOLD-LOCAL PREPROCESSING" tone="cyan" />}>
        <div className="flex flex-wrap items-end gap-4">
          <div><div className="mb-1 text-xs font-semibold uppercase text-slate-500">Global method</div>
            <Segmented value={method} onChange={setMethod as any} options={[
              { value: "iqr", label: "IQR" }, { value: "mad", label: "Robust Z / MAD" }, { value: "zscore", label: "Standard Z" }, { value: "percentile", label: "Winsorize" }, { value: "none", label: "None" }]} /></div>
          {(method === "iqr" || method === "mad" || method === "zscore") && <div className="w-28"><NumberField label="k" value={k} step={0.5} onChange={setK} /></div>}
          <Button onClick={preview} tone="dark">{post.status === "loading" ? "Computing…" : "Preview"}</Button>
          <Button onClick={save} tone={savedSteps.outliers ? "ghost" : "primary"}>{savedSteps.outliers ? "Saved ✓" : "Save outlier policy"}</Button>
        </div>
      </Card>
      {post.status === "loading" && <Card title="Computing…" ><div className="py-6"><div className="flex justify-center"><span className="h-6 w-6 animate-spin rounded-full border-2 border-slate-300 border-t-cyan-600" /></div></div></Card>}
      {post.data && (
        <>
          <div className="grid gap-3 sm:grid-cols-4">
            <MetricCard label="Observations" value={fmt.int(post.data.totalObservations)} detail="development rows" />
            <MetricCard label="Features analyzed" value={String(post.data.featuresAnalyzed)} detail="continuous only" />
            <MetricCard label="With outliers" value={String(post.data.featuresWithOutliers)} />
            <MetricCard label="Values flagged" value={fmt.int(post.data.totalFlagged)} detail={fmt.pct(post.data.flaggedPct, 2)} />
          </div>
          {post.data.features.filter((f) => f.flagged > 0).map((f) => (
            <Card key={f.feature} title={f.feature} description={`${f.method.toUpperCase()} · ${fmt.int(f.flagged)} flagged (${fmt.pct(f.flaggedPct, 2)}) · [${fmt.n(f.beforeMin, 2)}, ${fmt.n(f.beforeMax, 2)}] → [${fmt.n(f.afterMin, 2)}, ${fmt.n(f.afterMax, 2)}]`}>
              <BeforeAfter before={f.beforeHistogram} after={f.afterHistogram} />
            </Card>
          ))}
        </>
      )}
    </div>
  );
}

// ============================================================ 05 Missing Values
export function MissingStep() {
  const { config, setMissingPolicy, markSaved, savedSteps } = useCockpitStore();
  const [method, setMethod] = useState(config.missingPolicy.globalMethod);
  const [indicator, setIndicator] = useState(!!config.missingPolicy.addIndicator);
  const post = usePost<MissingSummary>();
  const preview = () => post.run("/cockpit/missing", { policy: { globalMethod: method, addIndicator: indicator, overrides: {} } });
  const save = () => { setMissingPolicy({ globalMethod: method, addIndicator: indicator, overrides: {} }); markSaved("missing"); };

  return (
    <div className="space-y-4">
      <Card title="Missing-value treatment" description="Comes after outliers. Fill statistics are learned fold-local on development. An optional indicator column preserves the missingness signal." icon={CircleSlash}
        action={<Pill label="FOLD-LOCAL PREPROCESSING" tone="cyan" />}>
        <div className="flex flex-wrap items-end gap-4">
          <div><div className="mb-1 text-xs font-semibold uppercase text-slate-500">Global method</div>
            <Segmented value={method} onChange={setMethod as any} options={[
              { value: "median", label: "Median" }, { value: "mean", label: "Mean" }, { value: "most_frequent", label: "Most frequent" }, { value: "constant", label: "Constant 0" }, { value: "none", label: "No imputation" }]} /></div>
          <label className="flex items-center gap-2 text-xs font-semibold text-slate-600"><input type="checkbox" checked={indicator} onChange={(e) => setIndicator(e.target.checked)} className="h-4 w-4 rounded border-slate-300" />Add missing indicator</label>
          <Button onClick={preview} tone="dark">{post.status === "loading" ? "Computing…" : "Preview"}</Button>
          <Button onClick={save} tone={savedSteps.missing ? "ghost" : "primary"}>{savedSteps.missing ? "Saved ✓" : "Save missing policy"}</Button>
        </div>
      </Card>
      {post.data && (
        <>
          <div className="grid gap-3 sm:grid-cols-3">
            <MetricCard label="Features with missingness" value={String(post.data.featuresWithMissing)} />
            <MetricCard label="Total missing values" value={fmt.int(post.data.totalMissing)} />
            <MetricCard label="Rows affected" value={fmt.int(post.data.rowsAffected)} detail={fmt.pct(post.data.rowsAffected / 549479)} />
          </div>
          <Card title="Missingness by feature and season" description="Prior-season player state is unavailable for debut players." icon={CircleSlash}>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[720px] text-left text-xs">
                <thead><tr className="text-slate-500">{["Feature", "Role", "Missing", "Miss%", "Method", "Indicator", "2023", "2024", "2025"].map((h) => <th key={h} className="border-b border-slate-200 px-2 py-2 font-semibold uppercase">{h}</th>)}</tr></thead>
                <tbody>{post.data.features.filter((f) => f.missing > 0).map((f) => (
                  <tr key={f.feature}><td className="border-b border-slate-100 px-2 py-1.5 font-semibold text-slate-800">{f.feature}</td>
                    <td className="border-b border-slate-100 px-2 py-1.5"><Pill label={f.role} tone={ROLE_TONE[f.role]} /></td>
                    <td className="border-b border-slate-100 px-2 py-1.5 tabular-nums">{fmt.int(f.missing)}</td>
                    <td className="border-b border-slate-100 px-2 py-1.5 tabular-nums font-semibold">{fmt.pct(f.missingPct)}</td>
                    <td className="border-b border-slate-100 px-2 py-1.5">{f.method}</td>
                    <td className="border-b border-slate-100 px-2 py-1.5">{f.indicator ? "yes" : "—"}</td>
                    {["2023", "2024", "2025"].map((y) => <td key={y} className="border-b border-slate-100 px-2 py-1.5 tabular-nums text-slate-500">{fmt.pct(f.bySeason[y])}</td>)}</tr>))}</tbody>
              </table>
            </div>
          </Card>
        </>
      )}
    </div>
  );
}

// ============================================================ 06 Feature Engineering
export function FeatureEngineeringStep() {
  const cat = useEndpoint<FeatureCatalog>("/cockpit/feature-catalog");
  const { config, setFeatures } = useCockpitStore();
  const engineered = config.engineeredFeatures || [];
  return (
    <div className="space-y-4">
      <Card title="Selected feature set" description={`${config.features.length} predictors selected (${ALL_FEATURES.length} base + ${engineered.length} engineered).`} icon={Wand2}
        action={<div className="flex gap-2"><Button size="sm" tone="ghost" onClick={() => setFeatures([...ALL_FEATURES])}>Base all</Button><Button size="sm" tone="ghost" onClick={() => setFeatures(ALL_FEATURES.filter((f) => f.startsWith("batter_") || f.startsWith("pitcher_")))}>Priors only</Button></div>}>
        <div className="flex flex-wrap gap-1.5">
          {ALL_FEATURES.map((f) => {
            const on = config.features.includes(f);
            return <button key={f} onClick={() => useCockpitStore.getState().toggleFeature(f)}
              className={`rounded-md border px-2 py-1 text-xs font-medium ${on ? "border-cyan-600 bg-cyan-50 text-cyan-800" : "border-slate-200 bg-white text-slate-400 line-through"}`}>{f}</button>;
          })}
          {engineered.map((e) => (
            <button key={e.name} onClick={() => useCockpitStore.getState().removeEngineered(e.name)}
              className="rounded-md border border-violet-500 bg-violet-50 px-2 py-1 text-xs font-medium text-violet-800">{e.name} ✕</button>
          ))}
        </div>
      </Card>
      <FeatureBuilder />
      <AblationPanel />
      <LoadGate state={cat}>
        {cat.data && (
          <Card title="Sports feature catalog" description="Available governed families plus an honestly-labeled roadmap." icon={Boxes}>
            <div className="grid gap-3 md:grid-cols-3">
              {cat.data.available.map((a) => (
                <div key={a.family} className="rounded-xl border border-emerald-200 bg-emerald-50/50 p-3">
                  <div className="flex items-center justify-between"><div className="text-sm font-semibold text-slate-900">{a.family}</div><Pill label="AVAILABLE" tone="emerald" /></div>
                  <div className="mt-2 text-[11px] leading-5 text-slate-600">{a.features.join(", ")}</div>
                </div>
              ))}
            </div>
          </Card>
        )}
      </LoadGate>
    </div>
  );
}

const KINDS = [
  { id: "arithmetic", label: "Arithmetic (a op b)" },
  { id: "ratio", label: "Ratio (a / b)" },
  { id: "interaction", label: "Interaction (a × b)" },
  { id: "log", label: "Log1p(a)" },
  { id: "power", label: "Power (a^p)" },
  { id: "bin", label: "Quantile bin" },
  { id: "indicator", label: "Indicator (a > t)" },
  { id: "calendar", label: "Calendar" },
];

function FeatureBuilder() {
  const store = useCockpitStore();
  const [name, setName] = useState("");
  const [kind, setKind] = useState("arithmetic");
  const [a, setA] = useState("batter_obp");
  const [b, setB] = useState("pitcher_whip");
  const [op, setOp] = useState("sub");
  const [threshold, setThreshold] = useState(0.3);
  const [exponent, setExponent] = useState(2);
  const [bins, setBins] = useState(5);
  const [subkind, setSubkind] = useState("month");
  const profile = usePost<EngineeredProfile>();

  const spec = (): EngineeredSpec => {
    if (kind === "calendar") return { name: name || `cal_${subkind}`, kind, params: { subkind } };
    if (kind === "log") return { name: name || `log_${a}`, kind, inputs: [a] };
    if (kind === "power") return { name: name || `${a}_pow`, kind, inputs: [a], params: { exponent } };
    if (kind === "bin") return { name: name || `${a}_bin`, kind, inputs: [a], params: { bins } };
    if (kind === "indicator") return { name: name || `${a}_hi`, kind, inputs: [a], params: { threshold } };
    if (kind === "ratio" || kind === "interaction") return { name: name || `${a}_${kind[0]}_${b}`, kind, inputs: [a, b] };
    return { name: name || `${a}_${op}_${b}`, kind, inputs: [a, b], params: { op } };
  };
  const doProfile = () => profile.run("/cockpit/feature/profile", spec());
  const add = () => { store.addEngineered(spec()); profile.reset(); setName(""); };

  const oneInput = ["log", "power", "bin", "indicator"].includes(kind);
  const twoInput = ["arithmetic", "ratio", "interaction"].includes(kind);
  return (
    <Card title="Create experiment feature" description="Build a real derived feature. It profiles instantly (IV/MI/missing/simulator-availability) and serializes into the experiment." icon={Wand2}
      action={<Pill label="TEMPORALLY SAFE" tone="emerald" />}>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <label className="flex flex-col gap-1 text-xs"><span className="font-semibold uppercase text-slate-500">Kind</span>
          <select value={kind} onChange={(e) => setKind(e.target.value)} className="rounded-lg border border-slate-300 px-2 py-1.5 text-sm">{KINDS.map((k) => <option key={k.id} value={k.id}>{k.label}</option>)}</select></label>
        {(oneInput || twoInput) && <label className="flex flex-col gap-1 text-xs"><span className="font-semibold uppercase text-slate-500">Input a</span>
          <select value={a} onChange={(e) => setA(e.target.value)} className="rounded-lg border border-slate-300 px-2 py-1.5 text-sm">{ALL_FEATURES.map((f) => <option key={f} value={f}>{f}</option>)}</select></label>}
        {twoInput && <label className="flex flex-col gap-1 text-xs"><span className="font-semibold uppercase text-slate-500">Input b</span>
          <select value={b} onChange={(e) => setB(e.target.value)} className="rounded-lg border border-slate-300 px-2 py-1.5 text-sm">{ALL_FEATURES.map((f) => <option key={f} value={f}>{f}</option>)}</select></label>}
        {kind === "arithmetic" && <label className="flex flex-col gap-1 text-xs"><span className="font-semibold uppercase text-slate-500">Op</span>
          <select value={op} onChange={(e) => setOp(e.target.value)} className="rounded-lg border border-slate-300 px-2 py-1.5 text-sm">{["add", "sub", "mul", "div"].map((o) => <option key={o} value={o}>{o}</option>)}</select></label>}
        {kind === "calendar" && <label className="flex flex-col gap-1 text-xs"><span className="font-semibold uppercase text-slate-500">Calendar</span>
          <select value={subkind} onChange={(e) => setSubkind(e.target.value)} className="rounded-lg border border-slate-300 px-2 py-1.5 text-sm">{["month", "day_of_week", "week_of_year", "days_since_season_start"].map((o) => <option key={o} value={o}>{o}</option>)}</select></label>}
        {kind === "indicator" && <NumberField label="threshold" value={threshold} step={0.05} onChange={setThreshold} />}
        {kind === "power" && <NumberField label="exponent" value={exponent} step={0.5} onChange={setExponent} />}
        {kind === "bin" && <NumberField label="bins" value={bins} step={1} onChange={setBins} />}
        <label className="flex flex-col gap-1 text-xs"><span className="font-semibold uppercase text-slate-500">Name (optional)</span>
          <input value={name} onChange={(e) => setName(e.target.value)} placeholder={spec().name} className="rounded-lg border border-slate-300 px-2 py-1.5 text-sm" /></label>
      </div>
      <div className="mt-3 flex gap-3">
        <Button onClick={doProfile} tone="dark">{profile.status === "loading" ? "Profiling…" : "Profile feature"}</Button>
        <Button onClick={add} tone="primary">Add to experiment</Button>
      </div>
      {profile.data && (
        <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <MetricCard label="Max IV" value={fmt.n(profile.data.iv.maxIv, 3)} detail={profile.data.iv.maxIvClass || ""} />
          <MetricCard label="MI" value={fmt.n(profile.data.mi, 4)} />
          <MetricCard label="Missing" value={fmt.pct(profile.data.missingPct)} />
          <MetricCard label="Drift" value={fmt.n(profile.data.drift, 3)} />
          <div className="sm:col-span-2 lg:col-span-4 rounded-lg border border-slate-200 bg-slate-50 p-3 text-xs">
            <span className="font-semibold text-slate-600">Simulator availability:</span> <span className="text-slate-700">{profile.data.simulatorAvailability}</span>
            <span className="ml-3 font-semibold text-slate-600">Sample:</span> <span className="tabular-nums text-slate-500">{profile.data.sampleValues.map((v) => fmt.n(v, 2)).join(", ")}</span>
          </div>
        </div>
      )}
    </Card>
  );
}

function AblationPanel() {
  const config = useCockpitStore((s) => s.config);
  const engineered = config.engineeredFeatures || [];
  const post = usePost<AblationResult>();
  const run = () => post.run("/cockpit/feature/ablation", {
    baseConfig: { features: [...ALL_FEATURES], family: config.family === "logistic" ? "logistic" : "logistic", hyperparameters: { C: 1.0 } },
    addFeatures: engineered.map((e) => e.name),
    addEngineered: engineered,
  });
  const VT: Record<string, any> = { VALUE_CONFIRMED: "emerald", VALUE_MARGINAL: "amber", NO_MATERIAL_VALUE: "slate", NEGATIVE_VALUE: "rose" };
  return (
    <Card title="Feature ablation" description="Controlled CONTROL vs CHALLENGER test: base 22 features vs base + your engineered features, same logistic pipeline. No Claude required." icon={Wand2}
      action={<Button size="sm" onClick={run} disabled={post.status === "loading" || engineered.length === 0} tone="dark">{post.status === "loading" ? "Ablating…" : "Run ablation"}</Button>}>
      {engineered.length === 0 ? <p className="text-sm text-slate-500">Create at least one engineered feature above to run an ablation.</p> : (
        <p className="text-xs text-slate-500">Testing added features: {engineered.map((e) => e.name).join(", ")}</p>
      )}
      {post.data && (
        <div className="mt-3 space-y-3">
          <div className="flex items-center gap-3"><Pill label={post.data.verdict.replace(/_/g, " ")} tone={VT[post.data.verdict]} />
            <span className="text-sm text-slate-600">{post.data.control.features} → {post.data.challenger.features} features</span></div>
          <div className="overflow-x-auto"><table className="w-full min-w-[520px] text-left text-sm">
            <thead><tr className="text-slate-500">{["", "Control (base)", "Challenger (+feat)", "Δ"].map((h) => <th key={h} className="border-b border-slate-200 px-3 py-2 text-xs font-semibold uppercase">{h}</th>)}</tr></thead>
            <tbody>
              <tr><td className="border-b border-slate-100 px-3 py-2 font-medium">2024 log loss</td>
                <td className="border-b border-slate-100 px-3 py-2 tabular-nums text-slate-500">{fmt.n(post.data.control.val2024.logLoss)}</td>
                <td className="border-b border-slate-100 px-3 py-2 tabular-nums font-semibold">{fmt.n(post.data.challenger.val2024.logLoss)}</td>
                <td className={`border-b border-slate-100 px-3 py-2 tabular-nums ${post.data.delta2024.logLoss < 0 ? "text-emerald-600" : "text-rose-600"}`}>{fmt.signed(post.data.delta2024.logLoss, 5)}</td></tr>
              <tr><td className="border-b border-slate-100 px-3 py-2 font-medium">2025 log loss</td>
                <td className="border-b border-slate-100 px-3 py-2 tabular-nums text-slate-500">{fmt.n(post.data.control.frozen2025.logLoss)}</td>
                <td className="border-b border-slate-100 px-3 py-2 tabular-nums font-semibold">{fmt.n(post.data.challenger.frozen2025.logLoss)}</td>
                <td className={`border-b border-slate-100 px-3 py-2 tabular-nums ${post.data.delta2025.logLoss < 0 ? "text-emerald-600" : "text-rose-600"}`}>{fmt.signed(post.data.delta2025.logLoss, 5)}</td></tr>
            </tbody>
          </table></div>
        </div>
      )}
    </Card>
  );
}

// ============================================================ 07 Player Segmentation
export function SegmentationStep() {
  const [population, setPopulation] = useState<"BATTERS" | "PITCHERS">("BATTERS");
  const summary = useEndpoint<any>(`/cockpit/segmentation/summary?population=${population}`, [population]);
  const km = usePost<any>();
  const pca = usePost<any>();
  const grid = usePost<any>();
  const stab = usePost<any>();
  const [dimX, setDimX] = useState("batter_hr_per_pa");
  const [dimY, setDimY] = useState("batter_so_per_pa");
  const feats: string[] = summary.data?.candidateFeatures || [];
  const runK = () => km.run("/cockpit/segmentation/kmeans", { population, kMin: 2, kMax: 8 }).then((r: any) => {
    pca.run("/cockpit/segmentation/pca", { population, k: r.recommendedK });
    stab.run("/cockpit/segmentation/stability", { population, k: r.recommendedK });
  });
  const runGrid = () => grid.run("/cockpit/segmentation/grid", { population, dimX, dimY });
  return (
    <div className="space-y-4">
      <Card title="Player segmentation — exploratory workbench" description="Research-only: do natural batter/pitcher archetypes exist? Fitted on development player state. It never changes the PA model and creates no per-player boosts." icon={Boxes}
        action={<Pill label="RESEARCH ONLY" tone="violet" />}>
        <div className="flex flex-wrap items-end gap-4">
          <div><div className="mb-1 text-xs font-semibold uppercase text-slate-500">Population</div>
            <Segmented value={population} onChange={(v) => setPopulation(v as any)} options={[{ value: "BATTERS", label: "Batters" }, { value: "PITCHERS", label: "Pitchers" }]} /></div>
          {summary.data && <div className="text-sm text-slate-600">{summary.data.players} players · {summary.data.candidateFeatures.length} features</div>}
          <Button onClick={runK} tone="dark" disabled={km.status === "loading"}>{km.status === "loading" ? "Clustering…" : "▶ Run K-means (K=2–8)"}</Button>
        </div>
      </Card>
      {km.data && (
        <>
          <Card title="Cluster diagnostics" description={km.data.recommendationRationale} icon={Boxes}
            action={<Pill label={`Recommended K=${km.data.recommendedK}`} tone="cyan" />}>
            <LineChart categories={km.data.results.map((r: any) => `K${r.k}`)}
              series={[{ name: "Silhouette (↑)", data: km.data.results.map((r: any) => r.silhouette), color: "#0891b2" },
                       { name: "Davies-Bouldin (↓)", data: km.data.results.map((r: any) => r.daviesBouldin), color: "#e11d48" }]} height={200} />
            <p className="mt-2 text-xs text-slate-500">{km.data.note}</p>
          </Card>
          <div className="grid gap-4 lg:grid-cols-2">
            {pca.data && <Card title="PCA cluster map" description={`PC1 ${fmt.pct(pca.data.explainedVariance[0])} + PC2 ${fmt.pct(pca.data.explainedVariance[1])} of variance.`} icon={Boxes}>
              <ScatterClusters points={pca.data.points} />
            </Card>}
            {stab.data && <Card title="Temporal cluster stability" description="2024 players projected onto 2023-fitted centroids." icon={Boxes}>
              <div className="flex items-center gap-4">
                <MetricCard label="Same cluster 2023→2024" value={stab.data.sameClusterPct != null ? fmt.pct(stab.data.sameClusterPct) : "—"} detail={`${stab.data.commonPlayers} common players`} />
              </div>
              <p className="mt-2 text-xs text-slate-500">{stab.data.note}</p>
            </Card>}
          </div>
          {pca.data && <Card title="Cluster profiles" description="Mean prior-state characteristics per cluster (interpret, then label)." icon={Boxes}>
            <div className="overflow-x-auto"><table className="w-full min-w-[720px] text-left text-xs">
              <thead><tr className="text-slate-500"><th className="border-b border-slate-200 px-2 py-1.5 font-semibold uppercase">Cluster</th><th className="border-b border-slate-200 px-2 py-1.5 font-semibold uppercase">Players</th>{feats.map((f) => <th key={f} className="border-b border-slate-200 px-2 py-1.5 font-semibold">{f.replace(population === "BATTERS" ? "batter_" : "pitcher_", "")}</th>)}</tr></thead>
              <tbody>{pca.data.profiles.map((p: any) => (
                <tr key={p.cluster}><td className="border-b border-slate-100 px-2 py-1.5 font-semibold">C{p.cluster}</td><td className="border-b border-slate-100 px-2 py-1.5 tabular-nums">{p.players}</td>
                  {feats.map((f) => <td key={f} className="border-b border-slate-100 px-2 py-1.5 tabular-nums text-slate-600">{fmt.n(p.centroid[f], 3)}</td>)}</tr>))}</tbody>
            </table></div>
          </Card>}
        </>
      )}
      <Card title="3×3 grid designer" description="Interpretable segmentation on two derived dimensions with development-only tercile boundaries." icon={Boxes}
        action={<Button size="sm" tone="dark" onClick={runGrid} disabled={grid.status === "loading"}>{grid.status === "loading" ? "Building…" : "Build grid"}</Button>}>
        <div className="flex flex-wrap items-end gap-3">
          <label className="flex flex-col gap-1 text-xs"><span className="font-semibold uppercase text-slate-500">Dimension X</span>
            <select value={dimX} onChange={(e) => setDimX(e.target.value)} className="rounded-lg border border-slate-300 px-2 py-1.5 text-sm">{feats.map((f) => <option key={f} value={f}>{f}</option>)}</select></label>
          <label className="flex flex-col gap-1 text-xs"><span className="font-semibold uppercase text-slate-500">Dimension Y</span>
            <select value={dimY} onChange={(e) => setDimY(e.target.value)} className="rounded-lg border border-slate-300 px-2 py-1.5 text-sm">{feats.map((f) => <option key={f} value={f}>{f}</option>)}</select></label>
        </div>
        {grid.data && (
          <div className="mt-4">
            <div className="grid grid-cols-3 gap-1.5" style={{ maxWidth: 420 }}>
              {["HIGH", "MED", "LOW"].map((yl) => ["LOW", "MED", "HIGH"].map((xl) => {
                const cell = grid.data.cells.find((c: any) => c.x === xl && c.y === yl);
                const share = cell?.paShare || 0;
                return <div key={`${xl}-${yl}`} className="rounded-lg border border-slate-200 p-2 text-center" style={{ background: `rgba(8,145,178,${Math.min(share * 4, 0.6)})` }}>
                  <div className="text-[10px] font-semibold uppercase text-slate-500">{xl}·{yl}</div>
                  <div className="text-lg font-semibold tabular-nums text-slate-900">{cell?.players ?? 0}</div>
                  <div className="text-[10px] text-slate-500">{fmt.pct(share)} PA</div>
                </div>;
              }))}
            </div>
            <p className="mt-2 text-xs text-slate-500">X = {grid.data.dimX} (→ LOW/MED/HIGH), Y = {grid.data.dimY} (↑). Boundaries: {grid.data.boundaryScope}. Grid is exploratory until predictive-tested via ablation.</p>
          </div>
        )}
      </Card>
    </div>
  );
}

// ============================================================ 08 Temporal Split
export function TemporalSplitStep() {
  const split = useEndpoint<TemporalSplit>("/cockpit/temporal-split");
  return (
    <LoadGate state={split}>
      {split.data && (
        <div className="space-y-4">
          <Card title="Temporal split policy" description="Sports-native. The default governed pattern trains on 2023, validates on 2024, and reserves 2025 as the frozen final." icon={CalendarClock}
            action={<Pill label={split.data.policy.replace(/_/g, " ")} tone="cyan" />}>
            <div className="flex flex-wrap gap-2">
              {split.data.supported.map((s) => (
                <div key={s.id} className={`rounded-lg border px-3 py-2 text-xs ${s.active ? "border-cyan-600 bg-cyan-50" : "border-slate-200 bg-white"}`}>
                  <div className="font-semibold text-slate-800">{s.label}{s.active ? " ·active" : ""}</div>
                  {s.warning ? <div className="mt-0.5 text-[11px] font-semibold text-rose-600">{s.warning}</div> : <div className="mt-0.5 text-[11px] text-slate-500">{s.recommended ? "recommended" : "available"}</div>}
                </div>
              ))}
            </div>
          </Card>
          <Card title="Fold timeline" description="Row counts per fold." icon={CalendarClock}>
            <div className="space-y-2">
              {split.data.folds.map((f) => (
                <div key={f.role} className="flex items-center gap-3">
                  <div className="w-28 text-xs font-semibold uppercase text-slate-500">{f.role.replace("_", " ")}</div>
                  <div className="flex-1"><div className="h-8 overflow-hidden rounded-lg"><div className={`flex h-full items-center px-3 text-xs font-semibold text-white ${f.role === "frozen_final" ? "bg-rose-500" : f.role === "validation" ? "bg-amber-500" : "bg-emerald-600"}`} style={{ width: `${(f.rows / 185000) * 100}%` }}>{f.seasons.join(",")} · {fmt.int(f.rows)}</div></div></div>
                </div>
              ))}
            </div>
          </Card>
          <Card title="Leakage guards" description="Fail-closed temporal integrity." icon={CalendarClock}>
            <div className="grid gap-2 sm:grid-cols-2">
              {split.data.leakageGuards.map((g) => (
                <div key={g.guard} className="flex items-center justify-between gap-2 rounded-lg border border-emerald-200 bg-emerald-50/50 px-3 py-2">
                  <span className="text-xs font-medium text-slate-700">{g.guard}</span><Pill label={g.status.replace(/_/g, " ")} tone="emerald" />
                </div>
              ))}
            </div>
          </Card>
        </div>
      )}
    </LoadGate>
  );
}
