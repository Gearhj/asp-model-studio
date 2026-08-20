// Cockpit workflow steps 01–08: Objective, Data & Population, Profile, Outliers, Missing,
// Feature Engineering, Segmentation, Temporal Split.
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  Target, Database, ScanSearch, TriangleAlert, CircleSlash, Wand2, Boxes, CalendarClock,
  X, ArrowUpDown, Check, Layers, Info, Archive,
} from "lucide-react";
import {
  useEndpoint, usePost, useCockpitStore, ALL_FEATURES,
  type Objective, type Population, type SourceSeasonRow, type Profile, type FeatureProfileRow, type FeatureDetail, type Correlation, type TargetAnalysis, type OutlierSummary, type OutlierEntry,
  type MissingSummary, type MissingEntry, type TemporalSplit, type FeatureCatalog,
  type EngineeredSpec, type EngineeredProfile, type AblationResult,
} from "./cockpitApi";
import {
  Card, Pill, MetricCard, Button, Segmented, NumberField, LoadGate, BarChart, Histogram,
  OutlierHistogramPair, ImputationHistogramPair, FeatureSignalScatter, CorrelationHeatmap, BoxPlotSingle, LineChart, ScatterClusters, fmt,
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
const roleTone = (role: string): "rose" | "amber" | "emerald" | "slate" =>
  /FROZEN/i.test(role) ? "rose" : /VALID/i.test(role) ? "amber" : /DEVELOP/i.test(role) ? "emerald" : "slate";

export function DataPopulationStep() {
  const pop = useEndpoint<Population>("/cockpit/population");
  return <LoadGate state={pop}>{pop.data ? <PopulationBody pop={pop.data} /> : null}</LoadGate>;
}

// Explicit target-variable authority (Phase 6G). The platform RECOMMENDS a target; the scientist
// confirms it. Confirmation persists in the store notes (autosaved). Downstream target-dependent
// analysis is "scientist-approved" only once confirmed.
const TARGET_OPTIONS = [{ value: "outcome", label: "outcome — 8-class plate-appearance result", recommended: true }];
function TargetSelector() {
  const ta = useEndpoint<TargetAnalysis>("/cockpit/target-analysis");
  const { notes, setNote } = useCockpitStore();
  const recommended = "outcome";
  const confirmed = notes["target.confirmed"] || "";
  const selected = notes["target.selected"] || recommended;
  const changedFromConfirmed = confirmed && selected !== confirmed;
  return (
    <section className="sports-panel rounded-2xl border border-slate-200 bg-white p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.14em] text-cyan-700"><Target size={14} /> Target variable</div>
        {confirmed === selected && confirmed ? <Pill label="Confirmed" tone="emerald" /> : <Pill label="Awaiting confirmation" tone="amber" />}
      </div>
      <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <div>
          <div className="text-[11px] font-semibold uppercase text-slate-400">Recommended</div>
          <div className="text-sm font-semibold text-slate-900">{recommended}</div>
          <div className="text-[11px] text-slate-500">categorical outcome field with complete coverage</div>
        </div>
        <label className="flex flex-col gap-1 text-xs"><span className="font-semibold uppercase text-slate-400">Selected target</span>
          <select value={selected} onChange={(e) => setNote("target.selected", e.target.value)} className="rounded-lg border border-slate-300 px-2 py-1.5 text-sm">{TARGET_OPTIONS.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}</select></label>
        <div><div className="text-[11px] font-semibold uppercase text-slate-400">Detected problem</div><div className="text-sm font-semibold text-slate-900">{ta.data ? "Multiclass classification" : "…"}</div><div className="text-[11px] text-slate-500">{ta.data ? `${ta.data.classCount} classes · missing ${ta.data.missing}` : ""}</div></div>
        <div className="flex items-end">
          <button onClick={() => { setNote("target.confirmed", selected); setNote("target.confirmedAt", new Date().toISOString()); }}
            className={`w-full rounded-lg border px-3 py-1.5 text-xs font-semibold ${confirmed === selected ? "border-slate-300 bg-white text-slate-600" : "border-cyan-600 bg-cyan-600 text-white hover:bg-cyan-500"}`}>{confirmed === selected ? "Target confirmed ✓" : "Confirm target"}</button>
        </div>
      </div>
      {changedFromConfirmed && (
        <div className="mt-3 rounded-xl border border-rose-300 bg-rose-50 p-3 text-xs text-rose-800">
          <div className="flex items-center gap-2 font-semibold"><TriangleAlert size={14} /> Changing the target invalidates target-dependent evidence</div>
          <p className="mt-1">Confirming <b>{selected}</b> would invalidate IV / MI, target relationships, engineered-feature target profiles, trained challengers, calibration, and candidate rankings computed under <b>{confirmed}</b>. This never overwrites the registered D3 champion. Re-confirm only as part of a deliberate revised experiment.</p>
        </div>
      )}
      <p className="mt-2 text-[11px] text-slate-500">The platform recommends a target; it does not silently choose one. Downstream target-dependent analysis is scientist-approved once confirmed. For the migrated Gen-2 project the existing registered target is <b>outcome</b>.</p>
    </section>
  );
}

function PopulationBody({ pop }: { pop: Population }) {
  const src = pop.sourceEvidence;
  // Games/batters are only materialized for the modeling seasons (2023–2025).
  const modeling = new Map(pop.perSeason.map((s) => [s.season, s]));
  const seasons: SourceSeasonRow[] = src?.perSeason
    ?? pop.perSeason.map((s) => ({ season: s.season, rows: s.rows, role: s.role.toUpperCase() }));
  const registeredTotal = src?.registeredTotalRows ?? seasons.reduce((a, s) => a + s.rows, 0);
  const modelingTotal = src?.modelingTotalRows ?? pop.totalRows;
  const priorTotal = src?.priorHistoryTotalRows ?? (registeredTotal - modelingTotal);
  return (
    <div className="space-y-5">
      <TargetSelector />
      {/* Two-layer population summary: registered source evidence vs. Gen-2 modeling matrix */}
      <div className="grid gap-3 sm:grid-cols-2">
        <div className="rounded-2xl border border-slate-200 bg-slate-50 p-4">
          <div className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-wide text-slate-500"><Archive size={13} /> Registered source evidence</div>
          <div className="mt-1 text-3xl font-semibold tabular-nums text-slate-900">{fmt.int(registeredTotal)}</div>
          <div className="mt-0.5 text-xs text-slate-500">plate appearances · 2021–2025 · all governed FD1 seasons</div>
        </div>
        <div className="rounded-2xl border border-cyan-200 bg-cyan-50/60 p-4">
          <div className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-wide text-cyan-700"><Layers size={13} /> Gen-2 modeling / evaluation matrix</div>
          <div className="mt-1 text-3xl font-semibold tabular-nums text-slate-900">{fmt.int(modelingTotal)}</div>
          <div className="mt-0.5 text-xs text-slate-500">plate appearances · 2023–2025 · target / training rows</div>
        </div>
      </div>

      <div className="grid gap-3 sm:grid-cols-4">
        <MetricCard label="Development" value={fmt.int(modeling.get(2023)?.rows)} detail="2023 · target season" />
        <MetricCard label="Validation" value={fmt.int(modeling.get(2024)?.rows)} detail="2024" />
        <MetricCard label="Frozen final" value={fmt.int(modeling.get(2025)?.rows)} detail="2025 · protected" />
        <MetricCard label="Candidate predictors" value={String(pop.candidatePredictors)} detail="governed feature view" />
      </div>

      {/* Plain-language explanation of the two-layer population */}
      <div className="rounded-xl border border-slate-200 bg-white p-4">
        <div className="flex items-center gap-2 text-sm font-semibold text-slate-900"><Info size={15} className="text-cyan-600" /> Why aren't 2021–2022 in training?</div>
        <p className="mt-1 text-sm leading-6 text-slate-600">
          ASP has registered plate-appearance evidence beginning in 2021. Under the governed Gen-2 temporal
          contract, <b>2021–2022 are retained as historical evidence for prior construction</b>, <b>2023</b> is
          the development target season, <b>2024</b> is validation, and <b>2025</b> is frozen final evaluation.
          The {fmt.int(priorTotal)} prior-history rows are <b>not discarded</b> — they build temporally valid
          Y−1 player features and are simply not eligible as Gen-2 target/training rows.
        </p>
      </div>

      <Card title="Season populations" description="All five registered seasons. 2021–2022 are prior history; 2023–2025 are the modeling matrix." icon={Database}>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[620px] text-left text-sm">
            <thead><tr className="text-slate-500">{["Season", "Role", "Plate appearances", "Games", "Batters"].map((h) => <th key={h} className="border-b border-slate-200 px-3 py-2 text-xs font-semibold uppercase">{h}</th>)}</tr></thead>
            <tbody>{seasons.map((s) => {
              const m = modeling.get(s.season);
              const prior = roleTone(s.role) === "slate";
              return (
                <tr key={s.season} className={prior ? "bg-slate-50/60" : ""}>
                  <td className="border-b border-slate-100 px-3 py-2 font-semibold text-slate-900">{s.season}</td>
                  <td className="border-b border-slate-100 px-3 py-2"><Pill label={s.role.replace(/_/g, " ")} tone={roleTone(s.role)} /></td>
                  <td className="border-b border-slate-100 px-3 py-2 tabular-nums">{fmt.int(s.rows)}</td>
                  <td className="border-b border-slate-100 px-3 py-2 tabular-nums text-slate-500">{m ? fmt.int(m.games) : "—"}</td>
                  <td className="border-b border-slate-100 px-3 py-2 tabular-nums text-slate-500">{m ? fmt.int(m.batters) : "—"}</td>
                </tr>
              );
            })}</tbody>
          </table>
        </div>
        <p className="mt-2 text-xs text-slate-500">Prior-history seasons are used only to construct temporally valid historical player features. They are not eligible as Gen-2 target / training rows (games / batters are materialized for the modeling matrix only).</p>
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Evidence lineage" description="Registered evidence splits into prior-history and the modeling matrix — nothing is dropped for quality." icon={Database}>
          <div className="space-y-2">
            {pop.waterfall.map((w, i) => {
              const pctW = (w.rows / (pop.waterfall[0]?.rows || 1)) * 100;
              const barColor = w.kind === "final" ? "bg-cyan-700" : w.kind === "retained" ? "bg-cyan-500" : w.kind === "prior" ? "bg-slate-300" : "bg-slate-800";
              return (
                <div key={i}>
                  <div className="flex items-center justify-between text-xs"><span className="font-semibold text-slate-700">{w.stage}</span><span className="tabular-nums text-slate-500">{fmt.int(w.rows)}</span></div>
                  <div className="mt-1 h-6 overflow-hidden rounded bg-slate-100"><div className={`h-full ${barColor}`} style={{ width: `${pctW}%` }} /></div>
                </div>
              );
            })}
          </div>
        </Card>
        <Card title="Temporal policy & known limitations" description="Model policy vs. full source-evidence coverage." icon={CalendarClock}>
          <div className="flex flex-wrap gap-2">
            <Pill label={`Dev ${pop.temporalPolicy.development.join(",")}`} tone="emerald" />
            <Pill label={`Val ${pop.temporalPolicy.validation}`} tone="amber" />
            <Pill label={`Frozen ${pop.temporalPolicy.frozenFinal}`} tone="rose" />
            <Pill label="Evidence 2021–2025" tone="slate" />
          </div>
          <ul className="mt-3 space-y-2 text-xs text-slate-600">
            {pop.knownLimitations.map((l, i) => <li key={i} className="flex gap-2"><span className="mt-1 h-1.5 w-1.5 shrink-0 rounded-full bg-amber-400" />{l}</li>)}
          </ul>
        </Card>
      </div>

      <DataPreviewPanel title="Gen-2 modeling matrix preview" showWarehouseLink={false} />
      <p className="text-xs text-slate-500">2021–2022 source rows are prior-history evidence and therefore do not appear as target rows in this preview.</p>
    </div>
  );
}

// ============================================================ 03 Data Profile — EDA workspace
// Answers "what relationships, distributions, risks and opportunities live inside these predictors?"
// (Data & Population already answers "what am I modeling?"). Development-2023 only for model-dev signal.
const ivTone = (iv: number, thr: number, weak: number): "emerald" | "amber" | "slate" => (iv >= thr ? "emerald" : iv >= weak ? "amber" : "slate");

export function ProfileStep() {
  const prof = useEndpoint<Profile>("/cockpit/profile");
  const corr = useEndpoint<Correlation>("/cockpit/correlation");
  const { config, toggleFeature, notes, setNote } = useCockpitStore();
  const selected = notes["eda.feature"] || "batter_obp";                 // persisted EDA selection
  const setSelected = (f: string) => setNote("eda.feature", f);
  const [sort, setSort] = useState<{ key: string; dir: 1 | -1 }>({ key: "maxIv", dir: -1 });

  const feats = prof.data?.features ?? [];
  const ivThr = prof.data?.ivScreeningThreshold ?? 0.1;
  const ivWeak = prof.data?.ivWeakThreshold ?? 0.02;
  const highIv = feats.filter((f) => f.iv.maxIv >= ivThr).length;
  const highMi = feats.filter((f) => f.mi >= 0.01).length;
  const highDrift = feats.filter((f) => (f.drift ?? 0) >= 0.1).length;
  const missConcern = feats.filter((f) => f.missingPct > 0.05).length;
  const outlierConcern = feats.filter((f) => f.outlierPct >= 0.02).length;

  const rows = useMemo(() => {
    const val = (r: any) => ({ name: r.name, missingPct: r.missingPct, outlierCount: r.outlierCount, maxIv: r.iv.maxIv, mi: r.mi, drift: r.drift ?? 0 } as any)[sort.key];
    return [...feats].sort((a, b) => (val(a) > val(b) ? sort.dir : val(a) < val(b) ? -sort.dir : 0));
  }, [feats, sort]);
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
          <div className="grid gap-3 sm:grid-cols-3 lg:grid-cols-7">
            <MetricCard label="Predictors" value={String(feats.length)} detail="candidate features" />
            <MetricCard label="High-IV" value={String(highIv)} detail={`IV ≥ ${ivThr}`} />
            <MetricCard label="High-MI" value={String(highMi)} detail="MI ≥ 0.01" />
            <MetricCard label="High drift" value={String(highDrift)} detail="drift ≥ 0.1" />
            <MetricCard label="Strong corr pairs" value={corr.data ? String(corr.data.strongPairCount) : "…"} detail={`|r| ≥ ${corr.data?.threshold ?? 0.8}`} />
            <MetricCard label="Missingness" value={String(missConcern)} detail=">5% missing" />
            <MetricCard label="Outlier concern" value={String(outlierConcern)} detail="≥2% flagged" />
          </div>
          <div className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-700">
            Exploratory data analysis on the <b>2023 development</b> fold. IV / MI are one-vs-rest <b>screening signals</b>, not automatic inclusion. Validation 2024 and frozen 2025 appear only as descriptive out-of-time monitoring — never used to fit thresholds or transforms.
          </div>

          <TargetAnalysisSection />

          <FeatureExplorer prof={prof.data} corr={corr.data} selected={selected} setSelected={setSelected} ivThr={ivThr} ivWeak={ivWeak} config={config} toggleFeature={toggleFeature} />

          <Card title="Correlation heatmap — development predictors" icon={ScanSearch}
            description="Pairwise |Pearson correlation| on the 2023 development fold (continuous predictors). Correlation is diagnostic evidence, not automatic exclusion.">
            <LoadGate state={corr}>
              {corr.data && (
                <>
                  <div className="mb-2 flex flex-wrap items-center gap-2 text-xs text-slate-600">
                    <Pill label={`Strong pairs |r| ≥ ${corr.data.threshold}: ${corr.data.strongPairCount}`} tone={corr.data.strongPairCount > 0 ? "amber" : "emerald"} />
                    {corr.data.strongPairs.map((p) => <span key={`${p.a}-${p.b}`} className="rounded bg-slate-100 px-2 py-0.5 font-mono text-[11px] text-slate-600">{shortName(p.a)} ~ {shortName(p.b)} = {fmt.n(p.r, 2)}</span>)}
                  </div>
                  <CorrelationHeatmap features={corr.data.features} matrix={corr.data.matrix} />
                </>
              )}
            </LoadGate>
          </Card>

          <Card title="Predictor screening" icon={ScanSearch}
            description={`Sortable. IV ≥ ${ivThr} is highlighted green (notable screening signal); ${ivWeak}–${ivThr} amber (weak). Click a feature to load it into the explorer above; Include/Exclude stays in sync with Feature Engineering.`}>
            <div className="max-h-[540px] overflow-auto rounded-lg border border-slate-200">
              <table className="w-full min-w-[900px] text-left text-xs">
                <thead className="sticky top-0 bg-slate-50">
                  <tr>
                    <th className="border-b border-slate-200 px-2 py-2 text-xs font-semibold uppercase text-slate-500">Feature</th>
                    <th className="border-b border-slate-200 px-2 py-2 text-xs font-semibold uppercase text-slate-500">Role</th>
                    <Th k="missingPct" label="Miss%" /><Th k="outlierCount" label="Outliers" />
                    <Th k="maxIv" label="IV" /><Th k="mi" label="MI" /><Th k="drift" label="Drift" />
                    <th className="border-b border-slate-200 px-2 py-2 text-xs font-semibold uppercase text-slate-500">Strongest corr</th>
                    <th className="border-b border-slate-200 px-2 py-2 text-xs font-semibold uppercase text-slate-500">Include</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r) => {
                    const included = config.features.includes(r.name);
                    const strong = corr.data?.strongest?.[r.name];
                    const tone = ivTone(r.iv.maxIv, ivThr, ivWeak);
                    return (
                      <tr key={r.name} className={`hover:bg-cyan-50/40 ${selected === r.name ? "bg-cyan-50" : ""}`}>
                        <td className="border-b border-slate-100 px-2 py-1.5"><button className="font-semibold text-slate-800 hover:text-cyan-700 hover:underline" onClick={() => setSelected(r.name)}>{r.name}</button>
                          <span className="ml-1 text-[10px] uppercase text-slate-400">{r.kind}</span></td>
                        <td className="border-b border-slate-100 px-2 py-1.5"><Pill label={r.role} tone={ROLE_TONE[r.role]} /></td>
                        <td className="border-b border-slate-100 px-2 py-1.5 tabular-nums">{fmt.pct(r.missingPct)}</td>
                        <td className="border-b border-slate-100 px-2 py-1.5 tabular-nums">{fmt.int(r.outlierCount)}</td>
                        <td className="border-b border-slate-100 px-2 py-1.5 tabular-nums">
                          <span className={`rounded px-1.5 py-0.5 font-semibold ${tone === "emerald" ? "bg-emerald-100 text-emerald-800" : tone === "amber" ? "bg-amber-50 text-amber-700" : "text-slate-900"}`}>{fmt.n(r.iv.maxIv, 3)}</span>
                          <span className="ml-1 text-[10px] text-slate-400">{r.iv.maxIvClass?.slice(0, 3)}</span></td>
                        <td className="border-b border-slate-100 px-2 py-1.5 tabular-nums">{fmt.n(r.mi, 4)}</td>
                        <td className="border-b border-slate-100 px-2 py-1.5 tabular-nums">{fmt.n(r.drift, 2)}</td>
                        <td className="border-b border-slate-100 px-2 py-1.5 text-[11px] text-slate-500">{strong?.feature ? `${shortName(strong.feature)} ${fmt.n(strong.r, 2)}` : "—"}</td>
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
            <div className="mt-2 flex flex-wrap items-center gap-3 text-xs text-slate-500">
              <span className="inline-flex items-center gap-1"><span className="h-2 w-3 rounded bg-emerald-100" /> IV ≥ {ivThr} notable</span>
              <span className="inline-flex items-center gap-1"><span className="h-2 w-3 rounded bg-amber-50" /> {ivWeak}–{ivThr} weak</span>
              <span>{prof.data.ivMethod}. Screening signal only — not automatic inclusion.</span>
            </div>
          </Card>
        </div>
      )}
    </LoadGate>
  );
}

const shortName = (f: string) => f.replace("batter_", "b·").replace("pitcher_", "p·").replace("context_", "c·");
const EDA_TABS = [{ id: "dist", label: "Distribution" }, { id: "box", label: "Box plot" }, { id: "target", label: "Target relationship" }, { id: "temporal", label: "Temporal stability" }];

const CLASS_COLORS: Record<string, string> = {
  STRIKEOUT: "#e11d48", WALK_HBP_CI: "#f59e0b", HOME_RUN: "#7c3aed", SINGLE: "#0891b2",
  DOUBLE: "#0e7490", TRIPLE: "#059669", BIP_OUT: "#64748b", OTHER_REACH: "#a855f7",
};
const classShort = (c: string) => ({ STRIKEOUT: "K", WALK_HBP_CI: "BB", HOME_RUN: "HR", SINGLE: "1B", DOUBLE: "2B", TRIPLE: "3B", BIP_OUT: "OUT", OTHER_REACH: "ROE" } as Record<string, string>)[c] || c;

// Target analysis for the 8-class PA outcome — gives Data Profile independent value from Data &
// Population. Class distribution + per-season composition (modeling target rows 2023-2025).
function TargetAnalysisSection() {
  const ta = useEndpoint<TargetAnalysis>("/cockpit/target-analysis");
  return (
    <Card title="Target analysis — outcome" icon={Target}
      description="The 8-class plate-appearance outcome. Class distribution and per-season composition over the modeling target rows (2023-2025).">
      <LoadGate state={ta}>
        {ta.data && (
          <div className="space-y-4">
            <div className="grid gap-3 sm:grid-cols-3 lg:grid-cols-6">
              <MetricCard label="Target" value={ta.data.target} detail={ta.data.problemType.replace(/_/g, " ").toLowerCase()} />
              <MetricCard label="Classes" value={String(ta.data.classCount)} detail="ordered taxonomy" />
              <MetricCard label="Missing" value={String(ta.data.missing)} detail="complete coverage" />
              <MetricCard label="Dominant" value={classShort(ta.data.dominantClass.class)} detail={fmt.pct(ta.data.dominantClass.share)} />
              <MetricCard label="Rarest" value={classShort(ta.data.rarestClass.class)} detail={fmt.pct(ta.data.rarestClass.share)} />
              <MetricCard label="Imbalance" value={ta.data.imbalanceRatio != null ? `${fmt.n(ta.data.imbalanceRatio, 0)}×` : "—"} detail="dominant ÷ rarest" />
            </div>

            <div>
              <div className="mb-1 text-[11px] font-semibold uppercase text-slate-400">Overall class distribution</div>
              <BarChart categories={ta.data.overall.map((d) => classShort(d.class))} values={ta.data.overall.map((d) => d.share)} height={200} valueFmt={(v) => fmt.pct(v)} />
            </div>

            <div>
              <div className="mb-1 flex flex-wrap items-center gap-2 text-[11px] font-semibold uppercase text-slate-400">Target composition by season (100% stacked)
                <span className="flex flex-wrap gap-1.5 normal-case">{ta.data.classOrder.map((c) => <span key={c} className="inline-flex items-center gap-1 text-[10px] font-medium text-slate-500"><span className="h-2 w-2 rounded" style={{ background: CLASS_COLORS[c] }} />{classShort(c)}</span>)}</span></div>
              <div className="space-y-1.5">
                {ta.data.perSeason.map((s) => (
                  <div key={s.season} className="flex items-center gap-2">
                    <div className="w-24 text-xs font-semibold text-slate-600">{s.season} <span className="text-[10px] font-normal text-slate-400">{s.season === 2023 ? "dev" : s.season === 2024 ? "val" : "frozen"}</span></div>
                    <div className="flex h-6 flex-1 overflow-hidden rounded">
                      {s.distribution.map((d) => d.share > 0 ? <div key={d.class} title={`${classShort(d.class)} ${(d.share * 100).toFixed(1)}%`} style={{ width: `${d.share * 100}%`, background: CLASS_COLORS[d.class] }} /> : null)}
                    </div>
                  </div>
                ))}
              </div>
              <p className="mt-1.5 text-[11px] text-slate-500">{ta.data.note} Class shares are stable across the modeling seasons — watch for material drift before trusting a season-transfer.</p>
            </div>
          </div>
        )}
      </LoadGate>
    </Card>
  );
}

function FeatureExplorer({ prof, corr, selected, setSelected, ivThr, ivWeak, config, toggleFeature }:
  { prof: Profile; corr: Correlation | undefined; selected: string; setSelected: (f: string) => void; ivThr: number; ivWeak: number; config: any; toggleFeature: (f: string) => void }) {
  const d = useEndpoint<FeatureDetail>(`/cockpit/profile/feature/${selected}`, [selected]);
  const [tab, setTab] = useState("dist");
  const [q, setQ] = useState("");
  const row = prof.features.find((f) => f.name === selected) as FeatureProfileRow | undefined;
  const strong = corr?.strongest?.[selected];
  const list = prof.features.filter((f) => f.name.toLowerCase().includes(q.toLowerCase()));
  const included = config.features.includes(selected);

  return (
    <Card title="Feature Explorer" icon={ScanSearch}
      description="Pick a predictor to explore its distribution, target relationship, and stability. Every chart updates when you choose another feature.">
      <div className="grid gap-4 lg:grid-cols-[210px_minmax(0,1fr)_248px]">
        {/* LEFT — searchable feature list */}
        <div className="min-w-0">
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search predictors…" className="mb-2 w-full rounded-lg border border-slate-300 px-2.5 py-1.5 text-xs" />
          <div className="max-h-[430px] space-y-0.5 overflow-auto rounded-lg border border-slate-200 p-1">
            {list.map((f) => {
              const tone = ivTone(f.iv.maxIv, ivThr, ivWeak);
              return (
                <button key={f.name} onClick={() => setSelected(f.name)}
                  className={`flex w-full items-center justify-between gap-2 rounded-md px-2 py-1.5 text-left text-xs ${selected === f.name ? "bg-slate-900 text-white" : "hover:bg-slate-100"}`}>
                  <span className="min-w-0 flex-1 truncate font-medium">{f.name}</span>
                  <span className={`shrink-0 rounded px-1 text-[10px] font-semibold tabular-nums ${tone === "emerald" ? "bg-emerald-100 text-emerald-800" : tone === "amber" ? "bg-amber-100 text-amber-700" : selected === f.name ? "bg-white/15 text-cyan-200" : "bg-slate-100 text-slate-500"}`}>{fmt.n(f.iv.maxIv, 2)}</span>
                </button>
              );
            })}
          </div>
        </div>

        {/* CENTER — analytical chart tabs */}
        <div className="min-w-0">
          <div className="mb-2 inline-flex flex-wrap gap-1 rounded-lg border border-slate-200 bg-slate-50 p-1">
            {EDA_TABS.map((t) => <button key={t.id} onClick={() => setTab(t.id)} className={`rounded-md px-3 py-1.5 text-xs font-semibold ${tab === t.id ? "bg-slate-900 text-white" : "text-slate-600 hover:bg-white"}`}>{t.label}</button>)}
          </div>
          <div className="rounded-lg border border-slate-200 p-3">
            <LoadGate state={d}>
              {d.data && (
                <>
                  {tab === "dist" && (d.data.histogram.length > 0
                    ? <Histogram bins={d.data.histogram} height={260} />
                    : <p className="py-8 text-center text-sm text-slate-500">Categorical / binary predictor — see target relationship.</p>)}
                  {tab === "box" && (d.data.box
                    ? <BoxPlotSingle box={d.data.box} />
                    : <p className="py-8 text-center text-sm text-slate-500">No box plot for a categorical / binary predictor.</p>)}
                  {tab === "target" && (
                    <div className="space-y-3">
                      <div><div className="mb-1 text-[11px] font-semibold uppercase text-slate-500">Target-conditioned mean by PA outcome (development)</div>
                        <BarChart categories={d.data.targetConditioned.map((t) => t.class)} values={d.data.targetConditioned.map((t) => t.mean ?? 0)} height={210} valueFmt={(v) => fmt.n(v, 3)} /></div>
                      {d.data.ivBins.length > 0 && (
                        <div><div className="mb-1 text-[11px] font-semibold uppercase text-slate-500">Event rate by feature bin · {d.data.ivBinsMaxClass}</div>
                          <BarChart categories={d.data.ivBins.map((b) => `b${b.bin}`)} values={d.data.ivBins.map((b) => b.eventRate)} height={150} color="#7c3aed" valueFmt={(v) => fmt.pct(v)} /></div>)}
                      <p className="text-[11px] text-slate-500">Does this predictor separate the eight PA outcomes? Larger spread across classes ⇒ more separation.</p>
                    </div>
                  )}
                  {tab === "temporal" && (
                    <div className="space-y-2">
                      {Object.keys(d.data.yoyHistogram).length > 0 && d.data.histogram.length > 0
                        ? <LineChart categories={d.data.histogram.map((_, i) => String(i))}
                            series={Object.entries(d.data.yoyHistogram).map(([yr, arr], i) => ({ name: yr, data: arr as number[], color: ["#059669", "#f59e0b", "#e11d48"][i % 3] }))} height={220} />
                        : <p className="py-6 text-center text-sm text-slate-500">Season distribution not available for this predictor.</p>}
                      <div className="rounded-md bg-slate-50 px-3 py-2 text-[11px] text-slate-500"><b className="text-emerald-700">2023 development</b> is the fit signal; <b>2024</b> / <b>2025</b> are out-of-time descriptive monitoring only — never used to fit transforms or thresholds.</div>
                    </div>
                  )}
                </>
              )}
            </LoadGate>
          </div>
        </div>

        {/* RIGHT — feature profile / insights */}
        <div className="min-w-0 space-y-2 text-xs">
          <div className="flex items-center justify-between"><span className="text-sm font-semibold text-slate-900">{selected}</span>{row ? <Pill label={row.role} tone={ROLE_TONE[row.role]} /> : null}</div>
          {row && (
            <>
              <div className="grid grid-cols-2 gap-1.5">
                <Insight label="Type" value={row.kind} />
                <Insight label="Missing" value={fmt.pct(row.missingPct)} />
                <Insight label="Outliers" value={fmt.int(row.outlierCount)} />
                <Insight label="Drift" value={fmt.n(row.drift, 2)} />
                <Insight label="IV" value={fmt.n(row.iv.maxIv, 3)} tone={ivTone(row.iv.maxIv, ivThr, ivWeak)} />
                <Insight label="MI" value={fmt.n(row.mi, 4)} />
              </div>
              <div className="rounded-lg border border-slate-200 p-2">
                <div className="mb-1 text-[10px] font-semibold uppercase text-slate-400">Development summary</div>
                <div className="grid grid-cols-2 gap-x-3 gap-y-0.5 tabular-nums text-slate-600">
                  {[["min", row.min], ["Q1", row.percentiles?.p25], ["median", row.median], ["mean", row.mean], ["Q3", row.percentiles?.p75], ["max", row.max], ["std", row.std]].map(([k, v]) => <div key={k as string} className="flex justify-between"><span className="text-slate-400">{k}</span><span className="font-medium">{fmt.n(v as number, 3)}</span></div>)}
                </div>
              </div>
              <Insight label="Strongest correlation" value={strong?.feature ? `${shortName(strong.feature)} · ${fmt.n(strong.r, 2)}` : "—"} />
              <button onClick={() => toggleFeature(selected)} className={`w-full rounded-lg border px-3 py-1.5 text-xs font-semibold ${included ? "border-slate-300 bg-white text-slate-700 hover:bg-slate-50" : "border-cyan-600 bg-cyan-600 text-white hover:bg-cyan-500"}`}>{included ? "Exclude from experiment" : "Include in experiment"}</button>
            </>
          )}
        </div>
      </div>
    </Card>
  );
}

function Insight({ label, value, tone }: { label: string; value: string; tone?: "emerald" | "amber" | "slate" }) {
  return (
    <div className="rounded-lg border border-slate-200 p-2">
      <div className="text-[10px] font-semibold uppercase text-slate-400">{label}</div>
      <div className={`mt-0.5 font-semibold ${tone === "emerald" ? "text-emerald-700" : tone === "amber" ? "text-amber-700" : "text-slate-900"}`}>{value}</div>
    </div>
  );
}

// ============================================================ 04 Outliers
const OUTLIER_METHODS = [
  { value: "iqr", label: "IQR" }, { value: "mad", label: "Robust Z / MAD" },
  { value: "zscore", label: "Standard Z" }, { value: "percentile", label: "Winsorize" }, { value: "none", label: "None" },
];
const OUTLIER_METHOD_LABELS: Record<string, string> = { iqr: "IQR", mad: "Robust Z (MAD)", zscore: "Standard Z", percentile: "Winsorize", none: "None" };
const methodLabel = (m: string) => OUTLIER_METHOD_LABELS[m] ?? m.toUpperCase();
const paramSummary = (method: string, k: number, lower: number, upper: number) =>
  method === "iqr" ? `multiplier ${k}` : method === "zscore" ? `threshold ${k}σ`
  : method === "mad" ? `threshold ${k}` : method === "percentile" ? `${lower}% / ${upper}%` : "no threshold";

// Method-specific parameter control — replaces the ambiguous generic "K". The label and helper text
// derive from the selected method; Winsorize exposes its actual lower/upper percentiles; None shows none.
function OutlierMethodParams({ method, k, setK, lower, setLower, upper, setUpper }:
  { method: string; k: number; setK: (v: number) => void; lower: number; setLower: (v: number) => void; upper: number; setUpper: (v: number) => void }) {
  if (method === "none") return <div className="self-center text-xs text-slate-500">No threshold parameter — distributions are shown unchanged.</div>;
  if (method === "percentile") return (
    <div className="flex items-start gap-3">
      <div className="w-32"><NumberField label="Lower percentile" value={lower} step={0.5} min={0} onChange={setLower} /><p className="mt-1 text-[11px] leading-4 text-slate-500">Caps values below this development percentile.</p></div>
      <div className="w-32"><NumberField label="Upper percentile" value={upper} step={0.5} min={0} onChange={setUpper} /><p className="mt-1 text-[11px] leading-4 text-slate-500">Caps values above this development percentile.</p></div>
    </div>
  );
  const spec = method === "iqr"
    ? { label: "IQR multiplier", helper: "Flags values below Q1 − m×IQR or above Q3 + m×IQR. 1.5 is the classic Tukey fence; 3.0 flags only 'far-out' extreme values." }
    : method === "zscore"
    ? { label: "Z-score threshold", helper: "Flags observations whose |z| = |(x − μ)/σ| exceeds this threshold (μ ± threshold×σ)." }
    : { label: "Robust-Z (MAD) threshold", helper: "Uses the median and median absolute deviation: median ± threshold × 1.4826 × MAD — robust to outliers, unlike mean / σ." };
  return <div className="w-48"><NumberField label={spec.label} value={k} step={0.5} min={0} onChange={setK} /><p className="mt-1 text-[11px] leading-4 text-slate-500">{spec.helper}</p></div>;
}

export function OutliersStep() {
  const { config, setOutlierPolicy, markSaved } = useCockpitStore();
  const saved = config.outlierPolicy;
  const [method, setMethod] = useState(saved.globalMethod === "none" ? "iqr" : saved.globalMethod);
  const [k, setK] = useState<number>(saved.params?.k ?? 3);
  const [lower, setLower] = useState<number>((saved.params as any)?.lower ?? 1);
  const [upper, setUpper] = useState<number>((saved.params as any)?.upper ?? 99);
  const [overrides, setOverrides] = useState<Record<string, { method: string }>>((saved.overrides as any) ?? {});
  const [sort, setSort] = useState<{ key: "feature" | "flagged" | "flaggedPct"; dir: 1 | -1 }>({ key: "flagged", dir: -1 });
  const post = usePost<OutlierSummary>();
  const [d, setD] = useState<OutlierSummary | undefined>();

  const params: Record<string, number> = method === "percentile" ? { lower, upper } : { k };
  const previewPolicy = { globalMethod: method, params, overrides };
  const savedKey = JSON.stringify(saved);
  const previewKey = JSON.stringify(previewPolicy);
  const unsaved = savedKey !== previewKey;

  // Reactive preview (debounced): the summary table, cards, and histograms always reflect the current
  // method/parameters — never stale saved policy — from one bounded fold-local (2023) calculation.
  useEffect(() => {
    const t = setTimeout(() => { post.run("/cockpit/outliers", { policy: JSON.parse(previewKey) }); }, 250);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [previewKey]);
  useEffect(() => { if (post.data) setD(post.data); }, [post.data]);

  const save = () => { setOutlierPolicy(previewPolicy); markSaved("outliers"); };
  const setOverride = (feature: string, m: string) => setOverrides((o) => {
    const next = { ...o }; if (m === "global") delete next[feature]; else next[feature] = { method: m }; return next;
  });

  const rows = useMemo(() => {
    if (!d) return [] as OutlierEntry[];
    const val = (f: OutlierEntry) => (sort.key === "feature" ? f.feature : (f as any)[sort.key]);
    return [...d.features].sort((a, b) => (val(a) > val(b) ? sort.dir : val(a) < val(b) ? -sort.dir : 0));
  }, [d, sort]);

  const Th = ({ k: key, label }: { k: "feature" | "flagged" | "flaggedPct"; label: string }) => (
    <th className="cursor-pointer border-b border-slate-200 px-3 py-2 text-xs font-semibold uppercase text-slate-500 hover:text-slate-900"
      onClick={() => setSort((s) => ({ key, dir: s.key === key ? (s.dir === 1 ? -1 : 1) : -1 }))}>
      <span className="inline-flex items-center gap-1">{label}<ArrowUpDown size={11} className={sort.key === key ? "text-cyan-600" : "text-slate-300"} /></span>
    </th>
  );

  return (
    <div className="space-y-4">
      <Card title="Outlier treatment" icon={TriangleAlert} action={<Pill label="FOLD-LOCAL PREPROCESSING · DEV 2023" tone="cyan" />}
        description="Thresholds are fit fold-local on development (2023) only — validation (2024) and frozen final (2025) never determine thresholds. Binary / categorical variables are never capped.">
        <div className="flex flex-wrap items-end gap-4">
          <div><div className="mb-1 text-xs font-semibold uppercase text-slate-500">Global method</div>
            <Segmented value={method} onChange={setMethod as any} options={OUTLIER_METHODS} /></div>
          <OutlierMethodParams method={method} k={k} setK={setK} lower={lower} setLower={setLower} upper={upper} setUpper={setUpper} />
          <Button onClick={save} tone={unsaved ? "primary" : "ghost"}>{unsaved ? "Save outlier policy" : "Saved ✓"}</Button>
        </div>
        <div className="mt-3 flex flex-wrap items-center gap-2 text-xs">
          <Pill label={`Previewing · ${methodLabel(method)} · ${paramSummary(method, k, lower, upper)}`} tone={unsaved ? "amber" : "emerald"} />
          <span className="text-slate-400">Saved policy · {methodLabel(saved.globalMethod)}{saved.globalMethod !== "none" ? ` · ${paramSummary(saved.globalMethod, saved.params?.k ?? 3, (saved.params as any)?.lower ?? 1, (saved.params as any)?.upper ?? 99)}` : ""}</span>
          {unsaved && <span className="rounded bg-amber-100 px-2 py-0.5 font-semibold uppercase tracking-wide text-amber-800">Unsaved preview</span>}
          {post.status === "loading" && d && <span className="text-slate-400">updating…</span>}
        </div>
      </Card>

      {!d && post.status === "loading" && <Card title="Computing…"><div className="flex justify-center py-6"><span className="h-6 w-6 animate-spin rounded-full border-2 border-slate-300 border-t-cyan-600" /></div></Card>}

      {d && (
        <>
          <div className="grid gap-3 sm:grid-cols-4">
            <MetricCard label="Observations" value={fmt.int(d.totalObservations)} detail="development (2023) rows" />
            <MetricCard label="Features analyzed" value={String(d.featuresAnalyzed)} detail="continuous only" />
            <MetricCard label="Features with outliers" value={String(d.featuresWithOutliers)} detail={`under ${methodLabel(method)}`} />
            <MetricCard label="Values flagged" value={fmt.int(d.totalFlagged)} detail={`${fmt.pct(d.flaggedPct, 2)} of evaluated cells`} />
          </div>

          <div className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-700">
            <b>{d.featuresWithOutliers}</b> of <b>{d.featuresAnalyzed}</b> continuous predictors contain observations outside the current {methodLabel(method)} thresholds. <b>{fmt.int(d.totalFlagged)}</b> values ({fmt.pct(d.flaggedPct, 2)} of evaluated continuous cells) would be affected under this preview.
          </div>

          <Card title="Outlier summary" icon={TriangleAlert}
            description="Sorted by outlier count. Change the method or parameters above to update every value. An optional per-feature override reuses the same governed fold-local calculation.">
            <div className="overflow-x-auto">
              <table className="w-full min-w-[720px] text-left text-sm">
                <thead><tr>
                  <Th k="feature" label="Feature" />
                  <Th k="flagged" label="Outliers" />
                  <Th k="flaggedPct" label="Outlier %" />
                  <th className="border-b border-slate-200 px-3 py-2 text-xs font-semibold uppercase text-slate-500">Lower threshold</th>
                  <th className="border-b border-slate-200 px-3 py-2 text-xs font-semibold uppercase text-slate-500">Upper threshold</th>
                  <th className="border-b border-slate-200 px-3 py-2 text-xs font-semibold uppercase text-slate-500">Treatment</th>
                  <th className="border-b border-slate-200 px-3 py-2 text-xs font-semibold uppercase text-slate-500">Override</th>
                </tr></thead>
                <tbody>{rows.map((f) => (
                  <tr key={f.feature} className="hover:bg-cyan-50/40">
                    <td className="border-b border-slate-100 px-3 py-2"><a href={`#outlier-${f.feature}`} className="font-semibold text-slate-800 hover:text-cyan-700">{f.feature}</a> <span className="ml-1 text-[10px] uppercase text-slate-400">{f.role}</span></td>
                    <td className="border-b border-slate-100 px-3 py-2 tabular-nums font-semibold text-slate-900">{fmt.int(f.flagged)}</td>
                    <td className="border-b border-slate-100 px-3 py-2 tabular-nums">{fmt.pct(f.flaggedPct, 2)}</td>
                    <td className="border-b border-slate-100 px-3 py-2 tabular-nums text-slate-600">{f.bounds ? fmt.n(f.bounds.lower, 3) : "—"}</td>
                    <td className="border-b border-slate-100 px-3 py-2 tabular-nums text-slate-600">{f.bounds ? fmt.n(f.bounds.upper, 3) : "—"}</td>
                    <td className="border-b border-slate-100 px-3 py-2"><Pill label={methodLabel(f.method)} tone={f.method === "none" ? "slate" : "cyan"} /></td>
                    <td className="border-b border-slate-100 px-3 py-2">
                      <select value={overrides[f.feature]?.method ?? "global"} onChange={(e) => setOverride(f.feature, e.target.value)} className="rounded-md border border-slate-300 bg-white px-2 py-1 text-xs">
                        <option value="global">Use global</option><option value="iqr">IQR</option><option value="mad">Robust Z</option><option value="zscore">Standard Z</option><option value="percentile">Winsorize</option><option value="none">None</option>
                      </select>
                    </td>
                  </tr>
                ))}</tbody>
              </table>
            </div>
            <p className="mt-2 text-xs text-slate-500">{d.featuresAnalyzed} continuous features analyzed; categorical / binary features (base state, prior-missing indicators) are never outlier-capped.</p>
          </Card>

          {rows.map((f) => (
            <Card key={f.feature} title={f.feature}>
              <div id={`outlier-${f.feature}`} className="-mt-2 mb-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-slate-600">
                <span className="text-sm font-semibold text-slate-900">{fmt.int(f.flagged)} outliers · {fmt.pct(f.flaggedPct, 2)}</span>
                <Pill label={methodLabel(f.method)} tone={f.method === "none" ? "slate" : "cyan"} />
                {f.bounds
                  ? <span>Lower threshold <b>{fmt.n(f.bounds.lower, 3)}</b> · Upper threshold <b>{fmt.n(f.bounds.upper, 3)}</b></span>
                  : <span className="text-slate-400">No thresholds — untreated</span>}
                <span className="text-slate-400">Observed range {fmt.n(f.beforeMin, 3)} – {fmt.n(f.beforeMax, 3)}{f.bounds ? ` · Post-treatment ${fmt.n(f.afterMin, 3)} – ${fmt.n(f.afterMax, 3)}` : ""}</span>
              </div>
              <OutlierHistogramPair before={f.beforeHistogram} after={f.afterHistogram} lower={f.bounds?.lower ?? null} upper={f.bounds?.upper ?? null} treated={f.bounds !== null} />
            </Card>
          ))}
        </>
      )}
    </div>
  );
}

// ============================================================ 05 Missing Values
const MISSING_METHODS = [
  { value: "median", label: "Median" }, { value: "mean", label: "Mean" }, { value: "most_frequent", label: "Most frequent" },
  { value: "constant", label: "Constant 0" }, { value: "none", label: "No imputation" },
];
const MISSING_METHOD_LABELS: Record<string, string> = { median: "Median", mean: "Mean", most_frequent: "Most frequent", constant: "Constant 0", none: "No imputation", none_median_fallback: "Median (fallback)" };
const missingMethodLabel = (m: string) => MISSING_METHOD_LABELS[m] ?? m;
const MISSING_METHOD_HELP: Record<string, string> = {
  median: "Fills missing cells with the development-fold median — robust to outliers.",
  mean: "Fills missing cells with the development-fold mean.",
  most_frequent: "Fills missing cells with the most frequent development value (mode).",
  constant: "Uses literal 0 as the fill value. For a baseball rate 0 is a real domain value — use only when zero is defensible, not as a neutral default.",
  none: "The governed model matrix must be complete; no cockpit model family accepts raw NaN, so this falls back to the development-fold median. Enable the missing indicator to preserve the missingness signal.",
};

export function MissingStep() {
  const { config, setMissingPolicy, markSaved } = useCockpitStore();
  const saved = config.missingPolicy;
  const [method, setMethod] = useState(saved.globalMethod || "median");
  const [indicator, setIndicator] = useState(!!saved.addIndicator);
  const [overrides, setOverrides] = useState<Record<string, { method: string }>>((saved.overrides as any) ?? {});
  const [sort, setSort] = useState<{ key: "feature" | "missing" | "missingPct"; dir: 1 | -1 }>({ key: "missing", dir: -1 });
  const [onlyMissing, setOnlyMissing] = useState(true);
  const post = usePost<MissingSummary>();
  const [d, setD] = useState<MissingSummary | undefined>();

  const previewPolicy = { globalMethod: method, addIndicator: indicator, overrides };
  const savedKey = JSON.stringify({ globalMethod: saved.globalMethod, addIndicator: !!saved.addIndicator, overrides: saved.overrides ?? {} });
  const previewKey = JSON.stringify(previewPolicy);
  const unsaved = savedKey !== previewKey;

  // Reactive preview (debounced): one bounded fold-local (2023) call returns counts, fill statistics,
  // per-season rates, and before/after histograms. The analytical body renders on load — never blank.
  useEffect(() => {
    const t = setTimeout(() => { post.run("/cockpit/missing", { policy: JSON.parse(previewKey) }); }, 250);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [previewKey]);
  useEffect(() => { if (post.data) setD(post.data); }, [post.data]);

  const save = () => { setMissingPolicy(previewPolicy); markSaved("missing"); };
  const setOverride = (feature: string, m: string) => setOverrides((o) => {
    const next = { ...o }; if (m === "global") delete next[feature]; else next[feature] = { method: m }; return next;
  });

  const rows = useMemo(() => {
    if (!d) return [] as MissingEntry[];
    const base = onlyMissing ? d.features.filter((f) => f.missing > 0) : d.features;
    const val = (f: MissingEntry) => (sort.key === "feature" ? f.feature : (f as any)[sort.key]);
    return [...base].sort((a, b) => (val(a) > val(b) ? sort.dir : val(a) < val(b) ? -sort.dir : 0));
  }, [d, sort, onlyMissing]);

  const Th = ({ k: key, label }: { k: "feature" | "missing" | "missingPct"; label: string }) => (
    <th className="cursor-pointer border-b border-slate-200 px-3 py-2 text-xs font-semibold uppercase text-slate-500 hover:text-slate-900"
      onClick={() => setSort((s) => ({ key, dir: s.key === key ? (s.dir === 1 ? -1 : 1) : -1 }))}>
      <span className="inline-flex items-center gap-1">{label}<ArrowUpDown size={11} className={sort.key === key ? "text-cyan-600" : "text-slate-300"} /></span>
    </th>
  );

  return (
    <div className="space-y-4">
      <Card title="Missing-value treatment" icon={CircleSlash} action={<Pill label="FOLD-LOCAL PREPROCESSING · DEV 2023" tone="cyan" />}
        description="Applied after outlier capping. Fill statistics are learned on development (2023) only — validation (2024) and frozen final (2025) never determine imputation values. An optional indicator column preserves the missingness signal.">
        <div className="flex flex-wrap items-end gap-4">
          <div><div className="mb-1 text-xs font-semibold uppercase text-slate-500">Global method</div>
            <Segmented value={method} onChange={setMethod as any} options={MISSING_METHODS} /></div>
          <label className="flex items-center gap-2 text-xs font-semibold text-slate-600">
            <input type="checkbox" checked={indicator} onChange={(e) => setIndicator(e.target.checked)} className="h-4 w-4 rounded border-slate-300" />Add missing indicator</label>
          <Button onClick={save} tone={unsaved ? "primary" : "ghost"}>{unsaved ? "Save missing policy" : "Saved ✓"}</Button>
        </div>
        <p className="mt-2 max-w-3xl text-[11px] leading-4 text-slate-500">{MISSING_METHOD_HELP[method]}</p>
        <p className="mt-1 max-w-3xl text-[11px] leading-4 text-slate-500"><b>Missing indicator:</b> when enabled, a binary column is added <b>only for continuous features that have missing values</b>, so the model can learn whether missingness itself carries signal (no predictive claim is made here).</p>
        <div className="mt-3 flex flex-wrap items-center gap-2 text-xs">
          <Pill label={`Previewing · ${missingMethodLabel(method)} · indicators ${indicator ? "ON" : "OFF"}`} tone={unsaved ? "amber" : "emerald"} />
          <span className="text-slate-400">Saved policy · {missingMethodLabel(saved.globalMethod || "median")} · indicators {saved.addIndicator ? "ON" : "OFF"}</span>
          {unsaved && <span className="rounded bg-amber-100 px-2 py-0.5 font-semibold uppercase tracking-wide text-amber-800">Unsaved preview</span>}
          {post.status === "loading" && d && <span className="text-slate-400">updating…</span>}
        </div>
      </Card>

      {/* State machine — the analytical region always renders a state, never blank. */}
      {!d && post.status === "loading" && (
        <Card title="Calculating development-fold missingness…"><div className="flex justify-center py-6"><span className="h-6 w-6 animate-spin rounded-full border-2 border-slate-300 border-t-cyan-600" /></div></Card>
      )}
      {!d && post.status === "error" && (
        <div className="rounded-xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-800">
          <div className="font-semibold">Missing-value analysis could not be loaded.</div>
          <p className="mt-1 leading-6">The development-fold missingness calculation did not return. Confirm the ASP Model Studio backend is running with the <code>/api/cockpit</code> routes, then reload this page.</p>
          <p className="mt-2 font-mono text-xs text-rose-500">{post.error}</p>
        </div>
      )}

      {d && d.featuresWithMissing === 0 && (
        <Card title="No missing values" icon={CircleSlash}>
          <p className="text-sm text-slate-600">No missing values were detected in the governed development feature set ({d.featuresAnalyzed} predictors, {fmt.int(d.totalObservations)} rows). No imputation is required.</p>
        </Card>
      )}

      {d && d.featuresWithMissing > 0 && (
        <>
          <div className="grid gap-3 sm:grid-cols-4">
            <MetricCard label="Observations" value={fmt.int(d.totalObservations)} detail="development (2023) rows" />
            <MetricCard label="Features analyzed" value={String(d.featuresAnalyzed)} detail={`${d.continuousFeatures} continuous + ${d.categoricalFeatures} categorical/binary`} />
            <MetricCard label="Features with missing values" value={String(d.featuresWithMissing)} />
            <MetricCard label="Missing values" value={fmt.int(d.totalMissing)} detail={`${fmt.pct(d.missingCellPct, 2)} of evaluated cells`} />
          </div>

          <div className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-700">
            <b>{d.featuresWithMissing}</b> of <b>{d.featuresAnalyzed}</b> predictors contain missing values. <b>{fmt.int(d.totalMissing)}</b> feature cells ({fmt.pct(d.missingCellPct, 2)}) are missing across <b>{fmt.int(d.rowsAffected)}</b> development rows ({fmt.pct(d.rowsAffectedPct, 2)}). Missingness is concentrated in prior-history batter and pitcher features and primarily represents players without eligible prior-season history — so it may carry information about player experience / history availability.
          </div>

          <Card title="Missingness summary" icon={CircleSlash}
            description="Sorted by missing count. Fill statistics are learned on development (2023) only. Change the method or a per-feature override above to update every value."
            action={<label className="flex items-center gap-2 text-xs font-semibold text-slate-600"><input type="checkbox" checked={onlyMissing} onChange={(e) => setOnlyMissing(e.target.checked)} className="h-4 w-4 rounded border-slate-300" />Only features with missing values</label>}>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[860px] text-left text-sm">
                <thead><tr>
                  <Th k="feature" label="Feature" />
                  <Th k="missing" label="Missing" />
                  <Th k="missingPct" label="Missing %" />
                  <th className="border-b border-slate-200 px-3 py-2 text-xs font-semibold uppercase text-slate-500">Type</th>
                  <th className="border-b border-slate-200 px-3 py-2 text-xs font-semibold uppercase text-slate-500">Treatment</th>
                  <th className="border-b border-slate-200 px-3 py-2 text-xs font-semibold uppercase text-slate-500">Fill value</th>
                  <th className="border-b border-slate-200 px-3 py-2 text-xs font-semibold uppercase text-slate-500">Indicator</th>
                  <th className="border-b border-slate-200 px-3 py-2 text-xs font-semibold uppercase text-slate-500">Override</th>
                </tr></thead>
                <tbody>{rows.map((f) => (
                  <tr key={f.feature} className="hover:bg-cyan-50/40">
                    <td className="border-b border-slate-100 px-3 py-2"><a href={`#missing-${f.feature}`} className="font-semibold text-slate-800 hover:text-cyan-700">{f.feature}</a> <span className="ml-1 text-[10px] uppercase text-slate-400">{f.role}</span></td>
                    <td className="border-b border-slate-100 px-3 py-2 tabular-nums font-semibold text-slate-900">{fmt.int(f.missing)}</td>
                    <td className="border-b border-slate-100 px-3 py-2 tabular-nums">{fmt.pct(f.missingPct, 2)}</td>
                    <td className="border-b border-slate-100 px-3 py-2 text-xs uppercase text-slate-500">{f.kind}</td>
                    <td className="border-b border-slate-100 px-3 py-2">{f.missing > 0 ? <Pill label={missingMethodLabel(f.resolvedMethod)} tone="cyan" /> : <span className="text-slate-300">—</span>}</td>
                    <td className="border-b border-slate-100 px-3 py-2 tabular-nums text-slate-600">{f.fillValue !== null ? fmt.n(f.fillValue, 3) : "—"}</td>
                    <td className="border-b border-slate-100 px-3 py-2">{f.indicator ? <Pill label="yes" tone="violet" /> : <span className="text-slate-300">—</span>}</td>
                    <td className="border-b border-slate-100 px-3 py-2">
                      <select value={overrides[f.feature]?.method ?? "global"} onChange={(e) => setOverride(f.feature, e.target.value)} disabled={f.missing === 0} className="rounded-md border border-slate-300 bg-white px-2 py-1 text-xs disabled:opacity-40">
                        <option value="global">Use global</option>
                        {f.kind === "continuous"
                          ? <><option value="median">Median</option><option value="mean">Mean</option><option value="constant">Constant 0</option><option value="none">No imputation</option></>
                          : <><option value="most_frequent">Most frequent</option><option value="constant">Constant 0</option><option value="none">No imputation</option></>}
                      </select>
                    </td>
                  </tr>
                ))}</tbody>
              </table>
            </div>
            <p className="mt-2 text-xs text-slate-500">{d.featuresAnalyzed} predictors analyzed ({d.continuousFeatures} continuous + {d.categoricalFeatures} categorical / binary). Categorical / binary predictors carry no missing values in the governed feature set.</p>
          </Card>

          <Card title="Missingness by season" icon={CalendarClock}
            description="Descriptive missing rates only — validation (2024) and frozen final (2025) never determine imputation values. Watch for temporal drift in availability.">
            <div className="overflow-x-auto">
              <table className="w-full min-w-[520px] text-left text-sm">
                <thead><tr className="text-slate-500">{["Feature", "2023 development", "2024 validation", "2025 frozen"].map((h) => <th key={h} className="border-b border-slate-200 px-3 py-2 text-xs font-semibold uppercase">{h}</th>)}</tr></thead>
                <tbody>{rows.map((f) => (
                  <tr key={f.feature}>
                    <td className="border-b border-slate-100 px-3 py-2 font-semibold text-slate-800">{f.feature}</td>
                    <td className="border-b border-slate-100 px-3 py-2 tabular-nums text-emerald-700">{fmt.pct(f.bySeason["2023"], 2)}</td>
                    <td className="border-b border-slate-100 px-3 py-2 tabular-nums text-amber-700">{fmt.pct(f.bySeason["2024"], 2)}</td>
                    <td className="border-b border-slate-100 px-3 py-2 tabular-nums text-rose-700">{fmt.pct(f.bySeason["2025"], 2)}</td>
                  </tr>
                ))}</tbody>
              </table>
            </div>
          </Card>

          {/* Feature treatment visuals — one before/after card per affected continuous feature (Outliers-parity). */}
          {(() => {
            const affected = rows.filter((f) => f.kind === "continuous" && f.missing > 0);
            if (affected.length === 0) return null;
            return (
              <div className="space-y-4">
                <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.14em] text-cyan-700"><CircleSlash size={14} /> Feature treatment visuals — before / after imputation</div>
                {affected.map((f) => (
                  <Card key={f.feature} title={f.feature}>
                    <div id={`missing-${f.feature}`} className="-mt-2 mb-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-slate-600">
                      <span className="text-sm font-semibold text-slate-900">{fmt.int(f.missing)} / {fmt.int(d.totalObservations)} missing · {fmt.pct(f.missingPct, 2)}</span>
                      <Pill label={missingMethodLabel(f.resolvedMethod)} tone="cyan" />
                      {f.fillValue !== null && <span>Development-fold fill <b>{fmt.n(f.fillValue, 3)}</b></span>}
                      <span className="text-slate-400">Observed non-missing {fmt.int(f.nonMissing)}</span>
                      <span>Missing indicator: <b>{f.indicator ? "Yes" : "No"}</b></span>
                    </div>
                    {f.beforeHistogram && f.afterHistogram
                      ? <ImputationHistogramPair before={f.beforeHistogram} after={f.afterHistogram} fill={f.fillValue}
                          fillLabel={`${missingMethodLabel(f.resolvedMethod)} ${f.fillValue !== null ? fmt.n(f.fillValue, 3) : ""}`}
                          afterLabel={`After — ${missingMethodLabel(f.resolvedMethod).toLowerCase()} imputation`} />
                      : <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">Distribution charts are unavailable from the current backend response. Restart the ASP Model Studio backend to load the before/after imputation histograms.</div>}
                  </Card>
                ))}
              </div>
            );
          })()}
        </>
      )}
    </div>
  );
}

// ============================================================ 06 Feature Engineering
const baseRole = (name: string) => (name.startsWith("batter_") ? "batter" : name.startsWith("pitcher_") ? "pitcher" : "context");
const OP_SYMBOL: Record<string, string> = { add: "+", sub: "−", mul: "×", div: "÷" };
function engineeredFormula(e: EngineeredSpec): string {
  const [a, b] = e.inputs ?? [];
  const p: any = e.params ?? {};
  switch (e.kind) {
    case "arithmetic": return `${a} ${OP_SYMBOL[p.op] ?? p.op} ${b}`;
    case "ratio": return `${a} ÷ ${b}`;
    case "interaction": return `${a} × ${b}`;
    case "log": return `log1p(${a})`;
    case "power": return `${a} ^ ${p.exponent}`;
    case "bin": return `quantile_bin(${a}, ${p.bins})`;
    case "indicator": return `[ ${a} > ${p.threshold} ]`;
    case "calendar": return `calendar(${p.subkind})`;
    default: return e.name;
  }
}

// Persistent feature-builder draft. Lives in the cockpit store's notes (so it autosaves and survives
// navigation/refresh), shared by the studio and the summary table's "Use as A/B" actions.
type FeatureDraft = { name: string; kind: string; inputA: string; inputB: string; op: string; threshold: number; exponent: number; bins: number; subkind: string };
const DEFAULT_DRAFT: FeatureDraft = { name: "", kind: "arithmetic", inputA: "batter_obp", inputB: "pitcher_whip", op: "sub", threshold: 0.3, exponent: 2, bins: 5, subkind: "month" };
const FE_DRAFT_KEY = "fe.draft";
const ONE_INPUT_KINDS = ["log", "power", "bin", "indicator"];
const TWO_INPUT_KINDS = ["arithmetic", "ratio", "interaction"];
function useFeatureDraft(): [FeatureDraft, (patch: Partial<FeatureDraft>) => void] {
  const notes = useCockpitStore((s) => s.notes);
  const setNote = useCockpitStore((s) => s.setNote);
  const draft = useMemo<FeatureDraft>(() => {
    try { const raw = notes[FE_DRAFT_KEY]; return raw ? { ...DEFAULT_DRAFT, ...JSON.parse(raw) } : DEFAULT_DRAFT; } catch { return DEFAULT_DRAFT; }
  }, [notes]);
  const setDraft = (patch: Partial<FeatureDraft>) => setNote(FE_DRAFT_KEY, JSON.stringify({ ...draft, ...patch }));
  return [draft, setDraft];
}

// One worked example per supported builder kind. "Load this example" fills the builder — it never adds.
type FeatureExample = { title: string; why: string; draft: Partial<FeatureDraft> };
const FEATURE_EXAMPLES: Record<string, FeatureExample> = {
  arithmetic: { title: "Batter–Pitcher OBP/WHIP contrast", why: "Contrast between batter on-base ability and the pitcher's baserunner-suppression environment (hypothesis, not a proven feature).", draft: { kind: "arithmetic", op: "sub", inputA: "batter_obp", inputB: "pitcher_whip", name: "batter_obp_minus_pitcher_whip" } },
  ratio: { title: "Batter power-to-pitcher HR rate", why: "Batter HR propensity relative to the pitcher's HR-allowed environment. Safe division: a 0 denominator yields NaN, handled as ordinary missingness.", draft: { kind: "ratio", inputA: "batter_hr_per_pa", inputB: "pitcher_hr_per_bfp", name: "batter_hr_pressure_ratio" } },
  interaction: { title: "Batter power × pitcher HR vulnerability", why: "Represents a matchup effect that may be stronger when both batter power and pitcher HR susceptibility are elevated.", draft: { kind: "interaction", inputA: "batter_hr_per_pa", inputB: "pitcher_hr_per_bfp", name: "power_hr_interaction" } },
  log: { title: "Log-compressed batter HR rate", why: "log1p compresses a right-skewed rate. Note batter_log1p_pa is already log-transformed, so this demonstrates log1p on a different, un-logged rate.", draft: { kind: "log", inputA: "batter_hr_per_pa", name: "log_batter_hr_rate" } },
  power: { title: "Squared OBP — nonlinearity probe", why: "Tests whether the OBP → PA-outcome relationship is nonlinear (hypothesis only).", draft: { kind: "power", inputA: "batter_obp", exponent: 2, name: "batter_obp_sq" } },
  bin: { title: "Pitcher WHIP quintile", why: "Quantile bin — cut points are learned on the 2023 development fold only, then applied to validation/frozen.", draft: { kind: "bin", inputA: "pitcher_whip", bins: 5, name: "pitcher_whip_quintile" } },
  indicator: { title: "High-strikeout batter flag", why: "A scientist-specified development threshold flag — not optimized on validation/frozen data.", draft: { kind: "indicator", inputA: "batter_so_per_pa", threshold: 0.28, name: "high_batter_so_rate" } },
  calendar: { title: "Game month", why: "Captures seasonality / schedule effects rather than intrinsic player skill.", draft: { kind: "calendar", subkind: "month", name: "cal_month" } },
};

export function FeatureEngineeringStep() {
  const prof = useEndpoint<Profile>("/cockpit/profile");
  const cat = useEndpoint<FeatureCatalog>("/cockpit/feature-catalog");
  const { config } = useCockpitStore();
  const [, setDraft] = useFeatureDraft();
  const engineered = config.engineeredFeatures || [];
  // "Use as A/B" from the summary table writes into the persistent builder draft.
  const useInput = (slot: "A" | "B", name: string) => setDraft(slot === "A" ? { inputA: name } : { inputB: name });
  const total = ALL_FEATURES.length + engineered.length;

  return (
    <div className="space-y-4">
      {/* Compact header — the scientist's inventory at a glance (no passive walls before the workspace) */}
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <MetricCard label="Current features" value={String(total)} detail={`${ALL_FEATURES.length} base + ${engineered.length} engineered`} />
        <MetricCard label="Selected" value={String(config.features.length)} detail="in the experiment" />
        <MetricCard label="Engineered" value={String(engineered.length)} detail={engineered.length ? "durable in this project" : "none yet"} />
        <MetricCard label="Research families" value="3" detail="advanced — below" />
      </div>

      {/* Prime workspace: signal landscape + creation studio side-by-side on wide screens */}
      <div className="grid gap-4 xl:grid-cols-2">
        <Card title="Feature signal map" description="X = Information Value, Y = Mutual Information. Selected features are solid; faded points are excluded. Find the high-signal, weak, and nonlinear-only features." icon={ScanSearch}>
          <LoadGate state={prof}>
            {prof.data && (
              <FeatureSignalScatter points={[
                ...prof.data.features.map((f) => ({ name: f.name, iv: f.iv.maxIv, mi: f.mi, family: f.role, selected: config.features.includes(f.name) })),
                ...engineered.map((e) => { const p = useCockpitStore.getState().engineeredProfiles[e.name]; return { name: e.name, iv: p?.iv.maxIv ?? 0, mi: p?.mi ?? 0, family: "engineered", selected: config.features.includes(e.name) }; }),
              ]} />
            )}
          </LoadGate>
        </Card>
        <FeatureBuilder />
      </div>

      {/* The primary feature inventory — updates live as features are created / toggled / removed */}
      <FeatureSummaryTable profile={prof.data} onUseInput={useInput} />

      <AblationPanel />

      {/* Advanced research families — accessible but de-emphasized (collapsed) */}
      <details className="overflow-hidden rounded-2xl border border-slate-200 bg-white">
        <summary className="cursor-pointer px-5 py-3 text-sm font-semibold text-slate-800">Advanced feature families — player-state, dynamic recent-form, E1 / E2, handedness</summary>
        <div className="px-2 pb-2"><PlayerStateFeatureFamilies /></div>
      </details>

      {/* Feature catalog — compact expandable with per-family counts */}
      <details className="overflow-hidden rounded-2xl border border-slate-200 bg-white">
        <summary className="cursor-pointer px-5 py-3 text-sm font-semibold text-slate-800">Feature catalog {cat.data ? `— ${cat.data.available.length} governed families` : ""}</summary>
        <div className="px-5 pb-4">
          <LoadGate state={cat}>
            {cat.data && (
              <>
                <div className="grid gap-3 md:grid-cols-3">
                  {cat.data.available.map((a) => (
                    <div key={a.family} className="rounded-xl border border-emerald-200 bg-emerald-50/50 p-3">
                      <div className="flex items-center justify-between"><div className="text-sm font-semibold text-slate-900">{a.family}</div><Pill label={`${a.features.length}`} tone="emerald" /></div>
                      <div className="mt-2 text-[11px] leading-5 text-slate-600">{a.features.join(", ")}</div>
                    </div>
                  ))}
                </div>
                {cat.data.roadmap?.length > 0 && (
                  <div className="mt-3">
                    <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">Roadmap — future / premium families (honestly labelled, not fabricated)</div>
                    <div className="mt-1.5 flex flex-wrap gap-2">{cat.data.roadmap.map((r) => <Pill key={r.family} label={`${r.family} · ${r.status}`} tone="slate" />)}</div>
                  </div>
                )}
              </>
            )}
          </LoadGate>
        </div>
      </details>

      {/* Selected-feature chips — compressed behind a disclosure so they no longer dominate the page */}
      <details className="overflow-hidden rounded-2xl border border-slate-200 bg-white">
        <summary className="cursor-pointer px-5 py-3 text-sm font-semibold text-slate-800">View selected feature set — {config.features.length} selected</summary>
        <div className="flex flex-wrap gap-1.5 px-5 pb-4">
          {config.features.map((f) => (
            <button key={f} onClick={() => useCockpitStore.getState().toggleFeature(f)}
              className="rounded-md border border-cyan-600 bg-cyan-50 px-2 py-1 text-xs font-medium text-cyan-800">{f} ✕</button>
          ))}
        </div>
      </details>
    </div>
  );
}

// Live feature inventory. Reads the governed profile (base features) + engineered-feature profiles from
// the store; updates immediately when a feature is created, toggled, or removed — no page reload.
function FeatureSummaryTable({ profile, onUseInput }: { profile: Profile | undefined; onUseInput: (slot: "A" | "B", name: string) => void }) {
  const { config, engineeredProfiles, toggleFeature, removeEngineered } = useCockpitStore();
  const [draft] = useFeatureDraft();
  const showInputB = TWO_INPUT_KINDS.includes(draft.kind);  // the active studio op needs a second input
  const engineered = config.engineeredFeatures || [];
  const [sort, setSort] = useState<{ key: string; dir: 1 | -1 }>({ key: "iv", dir: -1 });
  const profByName = new Map((profile?.features ?? []).map((f) => [f.name, f]));

  type Row = { name: string; source: "BASE" | "ENGINEERED"; kind: string; role: string; missingPct: number | null; outliers: number | null; iv: number | null; mi: number | null; drift: number | null; selected: boolean; profiled: boolean; formula?: string };
  const rows: Row[] = [
    ...ALL_FEATURES.map((name): Row => { const p = profByName.get(name); return { name, source: "BASE", kind: p?.kind ?? "—", role: p?.role ?? baseRole(name), missingPct: p?.missingPct ?? null, outliers: p?.outlierCount ?? null, iv: p?.iv.maxIv ?? null, mi: p?.mi ?? null, drift: p?.drift ?? null, selected: config.features.includes(name), profiled: !!p }; }),
    ...engineered.map((e): Row => { const p = engineeredProfiles[e.name]; return { name: e.name, source: "ENGINEERED", kind: p?.kind ?? "—", role: "engineered", missingPct: p?.missingPct ?? null, outliers: null, iv: p?.iv.maxIv ?? null, mi: p?.mi ?? null, drift: p?.drift ?? null, selected: config.features.includes(e.name), profiled: !!p, formula: engineeredFormula(e) }; }),
  ];
  const num = (v: number | null) => (v === null ? -Infinity : v);
  const sorted = [...rows].sort((a, b) => {
    const va = sort.key === "name" ? a.name : num((a as any)[sort.key]);
    const vb = sort.key === "name" ? b.name : num((b as any)[sort.key]);
    return va > vb ? sort.dir : va < vb ? -sort.dir : 0;
  });
  const Th = ({ k, label }: { k: string; label: string }) => (
    <th className="cursor-pointer border-b border-slate-200 px-2.5 py-2 text-xs font-semibold uppercase text-slate-500 hover:text-slate-900"
      onClick={() => setSort((s) => ({ key: k, dir: s.key === k ? (s.dir === 1 ? -1 : 1) : -1 }))}>
      <span className="inline-flex items-center gap-1">{label}<ArrowUpDown size={11} className={sort.key === k ? "text-cyan-600" : "text-slate-300"} /></span>
    </th>
  );
  const cell = (v: number | null, dec = 3, profiled = true) => (v !== null ? fmt.n(v, dec) : profiled ? "—" : <span className="text-[10px] uppercase text-amber-600">not profiled</span>);

  return (
    <Card title="Feature set summary" description={`${rows.length} features in the experiment inventory (${ALL_FEATURES.length} base + ${engineered.length} engineered). Sort by any signal column; toggle Selected to include or exclude.`} icon={Wand2}>
      <div className="max-h-[560px] overflow-auto rounded-lg border border-slate-200">
        <table className="w-full min-w-[900px] text-left text-xs">
          <thead className="sticky top-0 bg-slate-50">
            <tr>
              <Th k="name" label="Feature" /><Th k="source" label="Source" />
              <th className="border-b border-slate-200 px-2.5 py-2 text-xs font-semibold uppercase text-slate-500">Type</th>
              <Th k="missingPct" label="Missing %" /><Th k="outliers" label="Outliers" />
              <Th k="iv" label="IV" /><Th k="mi" label="MI" /><Th k="drift" label="Drift" />
              <th className="border-b border-slate-200 px-2.5 py-2 text-xs font-semibold uppercase text-slate-500">Selected</th>
              <th className="border-b border-slate-200 px-2.5 py-2 text-xs font-semibold uppercase text-slate-500">Actions</th>
            </tr>
          </thead>
          <tbody>{sorted.map((r) => (
            <tr key={r.name} className="hover:bg-cyan-50/40">
              <td className="border-b border-slate-100 px-2.5 py-1.5"><span className="font-semibold text-slate-800">{r.name}</span> <span className="ml-1 text-[10px] uppercase text-slate-400">{r.role}</span>{r.formula ? <div className="font-mono text-[10px] text-violet-600">{r.formula}</div> : null}</td>
              <td className="border-b border-slate-100 px-2.5 py-1.5"><Pill label={r.source} tone={r.source === "ENGINEERED" ? "violet" : "slate"} /></td>
              <td className="border-b border-slate-100 px-2.5 py-1.5 text-slate-500">{r.kind}</td>
              <td className="border-b border-slate-100 px-2.5 py-1.5 tabular-nums">{r.missingPct !== null ? fmt.pct(r.missingPct, 1) : (r.profiled ? "—" : <span className="text-[10px] uppercase text-amber-600">not profiled</span>)}</td>
              <td className="border-b border-slate-100 px-2.5 py-1.5 tabular-nums">{r.outliers !== null ? fmt.int(r.outliers) : "—"}</td>
              <td className="border-b border-slate-100 px-2.5 py-1.5 tabular-nums font-semibold text-slate-900">{cell(r.iv, 3, r.profiled)}</td>
              <td className="border-b border-slate-100 px-2.5 py-1.5 tabular-nums">{cell(r.mi, 4, r.profiled)}</td>
              <td className="border-b border-slate-100 px-2.5 py-1.5 tabular-nums">{cell(r.drift, 2, r.profiled)}</td>
              <td className="border-b border-slate-100 px-2.5 py-1.5">
                <button onClick={() => toggleFeature(r.name)} className={`inline-flex h-5 w-5 items-center justify-center rounded border ${r.selected ? "border-cyan-600 bg-cyan-600 text-white" : "border-slate-300 bg-white"}`}>{r.selected ? <Check size={13} /> : null}</button>
              </td>
              <td className="border-b border-slate-100 px-2.5 py-1.5">
                <div className="flex items-center gap-1">
                  <button onClick={() => onUseInput("A", r.name)} title="Set this feature as Input A in the Create Feature Studio." className="rounded border border-slate-300 px-1.5 py-0.5 text-[10px] font-semibold text-slate-600 hover:bg-slate-50">Use as A</button>
                  {showInputB && <button onClick={() => onUseInput("B", r.name)} title="Set this feature as Input B in the Create Feature Studio." className="rounded border border-slate-300 px-1.5 py-0.5 text-[10px] font-semibold text-slate-600 hover:bg-slate-50">Use as B</button>}
                  {r.source === "ENGINEERED" && <button onClick={() => removeEngineered(r.name)} className="rounded border border-rose-300 px-1.5 py-0.5 text-[10px] font-semibold text-rose-600 hover:bg-rose-50">Remove</button>}
                </div>
              </td>
            </tr>
          ))}</tbody>
        </table>
      </div>
      <p className="mt-2 text-xs text-slate-500">Base features carry governed profile metrics; a freshly created engineered feature shows <b>not profiled</b> until you click <b>Profile feature</b>. Governed source features are never deleted — only included or excluded.</p>
    </Card>
  );
}

// Player-state research relocated here (Phase 6D): scientist chooses which player-state feature
// families enter a NEW challenger. The registered D3 champion is immutable — toggles never mutate it.
const BATTER_PRIORS = ["batter_log1p_pa", "batter_avg", "batter_obp", "batter_slg", "batter_so_per_pa", "batter_bb_hbp_per_pa", "batter_hr_per_pa"];
const PITCHER_PRIORS = ["pitcher_log1p_bfp", "pitcher_era9", "pitcher_whip", "pitcher_so_per_bfp", "pitcher_bb_per_bfp", "pitcher_hr_per_bfp", "pitcher_hbp_per_bfp", "pitcher_gs_per_g"];
const MISSING_INDICATORS = ["batter_prior_missing", "pitcher_prior_missing"];

function PlayerStateFeatureFamilies() {
  const { config, setFeatures } = useCockpitStore();
  const has = (fs: string[]) => fs.every((f) => config.features.includes(f));
  const toggleFamily = (fs: string[]) => {
    const included = has(fs);
    setFeatures(included ? config.features.filter((f) => !fs.includes(f)) : [...new Set([...config.features, ...fs])]);
  };
  const evHref = "/player-team-state?from=mlb-workflow&stage=3";

  const base: { name: string; features: string[]; note: string }[] = [
    { name: "Prior-season batter state", features: BATTER_PRIORS, note: "Latest eligible Y−1 batting priors (AVG/OBP/SLG, K/BB/HR rates)." },
    { name: "Prior-season pitcher state", features: PITCHER_PRIORS, note: "Latest eligible Y−1 pitching priors (ERA/WHIP, K/BB/HR rates)." },
    { name: "Missing-history indicators", features: MISSING_INDICATORS, note: "Explicit debut / no-prior flags so imputation is honest." },
  ];
  const research: { name: string; status: string; tone: any; finding: string }[] = [
    { name: "Dynamic recent-form state", status: "RESEARCH ONLY", tone: "amber", finding: "D0–D4 dynamic-state candidates registered; not in the static challenger space yet." },
    { name: "E1 pitch-sequence process features", status: "RESEARCH ONLY", tone: "amber", finding: "Marginal positive predictive value (small, consistent aggregate gain)." },
    { name: "E2 batter × pitcher interactions", status: "RESEARCH ONLY", tone: "amber", finding: "Negative aggregate incremental value; K/BB subclasses improved." },
    { name: "Handedness / platoon", status: "NOT CONFIGURED", tone: "slate", finding: "Future feature family — not materialized in the governed free data." },
  ];

  return (
    <Card title="Player-state feature families" description="Choose which player-state signal enters a new challenger. Prior research guides you; the registered champion is never changed." icon={Wand2}
      action={<Pill label="APPLIES TO NEW CHALLENGER" tone="violet" />}>
      <div className="grid gap-2">
        {base.map((f) => {
          const included = has(f.features);
          return (
            <div key={f.name} className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-slate-200 bg-white px-3 py-2.5">
              <div className="min-w-0"><div className="flex items-center gap-2"><span className="text-sm font-semibold text-slate-900">{f.name}</span>{included ? <Pill label="Currently included" tone="emerald" /> : <Pill label="Excluded" tone="slate" />}</div><div className="mt-0.5 text-xs text-slate-500">{f.note} · {f.features.length} features</div></div>
              <button onClick={() => toggleFamily(f.features)} className={`shrink-0 rounded-lg border px-3 py-1.5 text-xs font-semibold ${included ? "border-slate-300 bg-white text-slate-700 hover:bg-slate-50" : "border-cyan-600 bg-cyan-600 text-white hover:bg-cyan-500"}`}>{included ? "Exclude" : "Include in challenger"}</button>
            </div>
          );
        })}
      </div>
      <div className="mt-4 text-xs font-semibold uppercase tracking-wide text-slate-500">Advanced research families</div>
      <div className="mt-2 grid gap-2 sm:grid-cols-2">
        {research.map((r) => (
          <div key={r.name} className="rounded-xl border border-slate-200 bg-slate-50 p-3">
            <div className="flex items-center justify-between gap-2"><span className="text-sm font-semibold text-slate-800">{r.name}</span><Pill label={r.status} tone={r.tone} /></div>
            <div className="mt-1 text-xs leading-5 text-slate-600">{r.finding}</div>
            <Link to={evHref} className="mt-1.5 inline-flex items-center gap-1 text-[11px] font-semibold text-cyan-700 hover:underline">View evidence ↗</Link>
          </div>
        ))}
      </div>
    </Card>
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
  const [draft, setDraft] = useFeatureDraft();
  const [showExample, setShowExample] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const profile = usePost<EngineeredProfile>();
  const { name, kind, op, threshold, exponent, bins, subkind, inputA: a, inputB: b } = draft;
  const setName = (v: string) => setDraft({ name: v });
  const setKind = (v: string) => setDraft({ kind: v });
  const setInputA = (v: string) => setDraft({ inputA: v });
  const setInputB = (v: string) => setDraft({ inputB: v });
  const setOp = (v: string) => setDraft({ op: v });
  const setThreshold = (v: number) => setDraft({ threshold: v });
  const setExponent = (v: number) => setDraft({ exponent: v });
  const setBins = (v: number) => setDraft({ bins: v });
  const setSubkind = (v: string) => setDraft({ subkind: v });
  const example = FEATURE_EXAMPLES[kind];
  const loadExample = () => { if (example) { setDraft(example.draft); setShowExample(false); } };

  const defaultName = () => {
    if (kind === "calendar") return `cal_${subkind}`;
    if (kind === "log") return `log_${a}`;
    if (kind === "power") return `${a}_pow${exponent}`;
    if (kind === "bin") return `${a}_bin${bins}`;
    if (kind === "indicator") return `${a}_gt_${String(threshold).replace(".", "p")}`;
    if (kind === "ratio") return `${a}_over_${b}`;
    if (kind === "interaction") return `${a}_x_${b}`;
    return `${a}_${op}_${b}`;
  };
  const spec = (): EngineeredSpec => {
    const nm = name.trim() || defaultName();
    if (kind === "calendar") return { name: nm, kind, params: { subkind } };
    if (kind === "log") return { name: nm, kind, inputs: [a] };
    if (kind === "power") return { name: nm, kind, inputs: [a], params: { exponent } };
    if (kind === "bin") return { name: nm, kind, inputs: [a], params: { bins } };
    if (kind === "indicator") return { name: nm, kind, inputs: [a], params: { threshold } };
    if (kind === "ratio" || kind === "interaction") return { name: nm, kind, inputs: [a, b] };
    return { name: nm, kind, inputs: [a, b], params: { op } };
  };

  const oneInput = ["log", "power", "bin", "indicator"].includes(kind);
  const twoInput = ["arithmetic", "ratio", "interaction"].includes(kind);
  const formula = engineeredFormula(spec());

  const validate = (): string | null => {
    const nm = spec().name;
    const engineered = store.config.engineeredFeatures || [];
    if (ALL_FEATURES.includes(nm)) return `"${nm}" collides with a base feature name — choose another name.`;
    if (engineered.some((e) => e.name === nm)) return `An engineered feature named "${nm}" already exists.`;
    if ((kind === "ratio" || (kind === "arithmetic" && op === "div")) && a === b) return "Ratio / divide of a feature by itself is constant — pick different inputs.";
    if (twoInput && a === b && kind === "interaction") return "Interaction of a feature with itself is a square — use Power instead, or pick different inputs.";
    return null;
  };
  const doProfile = () => { const v = validate(); setError(v); if (!v) profile.run("/cockpit/feature/profile", spec()); };
  const add = () => {
    const v = validate(); setError(v); if (v) return;
    store.addEngineered(spec(), profile.data ?? undefined);   // persist the profile snapshot too
    profile.reset(); setName("");
  };

  const p = profile.data;
  return (
    <Card title="Create feature studio" description="Compose a real derived feature, profile it fold-local (2023), then add it to the experiment." icon={Wand2}
      action={<div className="flex items-center gap-2">{example && <button onClick={() => setShowExample((v) => !v)} className="rounded-lg border border-cyan-300 bg-cyan-50 px-2.5 py-1 text-xs font-semibold text-cyan-700 hover:bg-cyan-100">{showExample ? "Hide example" : "View example"}</button>}<Pill label="TEMPORALLY SAFE" tone="emerald" /></div>}>
      {showExample && example && (
        <div className="mb-3 rounded-xl border border-cyan-200 bg-cyan-50/60 p-3">
          <div className="flex items-center justify-between gap-2"><div className="text-sm font-semibold text-slate-900">Example · {example.title}</div><Pill label={KINDS.find((k) => k.id === kind)?.label ?? kind} tone="cyan" /></div>
          <div className="mt-1.5 grid gap-1.5 text-xs sm:grid-cols-2">
            <div><span className="font-semibold uppercase text-slate-400">Formula</span><div className="font-mono text-slate-800">{example.draft.name} = {engineeredFormula({ name: example.draft.name ?? "", kind: example.draft.kind ?? kind, inputs: [example.draft.inputA ?? a, example.draft.inputB ?? b], params: { op: example.draft.op ?? op, exponent: example.draft.exponent ?? exponent, bins: example.draft.bins ?? bins, threshold: example.draft.threshold ?? threshold, subkind: example.draft.subkind ?? subkind } })}</div></div>
            <div><span className="font-semibold uppercase text-slate-400">Why test it?</span><div className="text-slate-600">{example.why}</div></div>
          </div>
          <button onClick={loadExample} className="mt-2 rounded-lg bg-slate-900 px-3 py-1.5 text-xs font-semibold text-white hover:bg-slate-800">Load this example</button>
          <p className="mt-1 text-[10px] text-slate-500">Loads the fields below — it does not add the feature. You still choose Profile feature → Add to experiment.</p>
        </div>
      )}
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="flex flex-col gap-1 text-xs"><span className="font-semibold uppercase text-slate-500">Feature type</span>
          <select value={kind} onChange={(e) => setKind(e.target.value)} className="rounded-lg border border-slate-300 px-2 py-1.5 text-sm">{KINDS.map((k) => <option key={k.id} value={k.id}>{k.label}</option>)}</select></label>
        <label className="flex flex-col gap-1 text-xs"><span className="font-semibold uppercase text-slate-500">Name (optional)</span>
          <input value={name} onChange={(e) => setName(e.target.value)} placeholder={defaultName()} className="rounded-lg border border-slate-300 px-2 py-1.5 text-sm" /></label>
        {(oneInput || twoInput) && <label className="flex flex-col gap-1 text-xs"><span className="font-semibold uppercase text-slate-500">Input A</span>
          <select value={a} onChange={(e) => setInputA(e.target.value)} className="rounded-lg border border-slate-300 px-2 py-1.5 text-sm">{ALL_FEATURES.map((f) => <option key={f} value={f}>{f}</option>)}</select></label>}
        {twoInput && <label className="flex flex-col gap-1 text-xs"><span className="font-semibold uppercase text-slate-500">Input B</span>
          <select value={b} onChange={(e) => setInputB(e.target.value)} className="rounded-lg border border-slate-300 px-2 py-1.5 text-sm">{ALL_FEATURES.map((f) => <option key={f} value={f}>{f}</option>)}</select></label>}
        {kind === "arithmetic" && <label className="flex flex-col gap-1 text-xs"><span className="font-semibold uppercase text-slate-500">Operator</span>
          <select value={op} onChange={(e) => setOp(e.target.value)} className="rounded-lg border border-slate-300 px-2 py-1.5 text-sm">{["add", "sub", "mul", "div"].map((o) => <option key={o} value={o}>{o}</option>)}</select></label>}
        {kind === "calendar" && <label className="flex flex-col gap-1 text-xs"><span className="font-semibold uppercase text-slate-500">Calendar field</span>
          <select value={subkind} onChange={(e) => setSubkind(e.target.value)} className="rounded-lg border border-slate-300 px-2 py-1.5 text-sm">{["month", "day_of_week", "week_of_year", "days_since_season_start"].map((o) => <option key={o} value={o}>{o}</option>)}</select></label>}
        {kind === "indicator" && <NumberField label="Threshold" value={threshold} step={0.05} onChange={setThreshold} />}
        {kind === "power" && <NumberField label="Exponent" value={exponent} step={0.5} onChange={setExponent} />}
        {kind === "bin" && <NumberField label="Quantile bins" value={bins} step={1} min={2} onChange={setBins} />}
      </div>

      {/* Read-only formula preview — generated from the controls above (not an editable expression box) */}
      <div className="mt-3 rounded-lg border border-slate-800 bg-slate-950 px-4 py-3">
        <div className="flex items-center justify-between"><div className="text-[10px] font-semibold uppercase tracking-[0.14em] text-cyan-300">Formula preview</div><span className="rounded bg-white/10 px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wide text-slate-300">read-only</span></div>
        <div className="mt-1 select-text font-mono text-lg text-white">{spec().name} <span className="text-slate-500">=</span> {formula}</div>
        <div className="mt-1 text-[10px] text-slate-500">Generated from the controls above — adjust Feature type / inputs / parameters to change it.</div>
      </div>

      {error && <div className="mt-2 rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-xs font-semibold text-rose-700">{error}</div>}

      <div className="mt-3 flex gap-3">
        <Button onClick={doProfile} tone="dark">{profile.status === "loading" ? "Profiling…" : "Profile feature"}</Button>
        <Button onClick={add} tone="primary">Add to experiment</Button>
      </div>

      {p && (
        <div className="mt-4 space-y-3">
          {/* Quality scorecard — multi-dimensional, never a single magic score */}
          <div className="grid gap-2 sm:grid-cols-3 lg:grid-cols-6">
            <ScoreTile label="Information (IV)" value={fmt.n(p.iv.maxIv, 3)} sub={p.iv.maxIvClass || ""} />
            <ScoreTile label="Nonlinear (MI)" value={fmt.n(p.mi, 4)} />
            <ScoreTile label="Missingness" value={fmt.pct(p.missingPct, 1)} />
            <ScoreTile label="Temporal drift" value={fmt.n(p.drift, 2)} />
            <ScoreTile label="Type" value={p.kind} />
            <ScoreTile label="Simulator" value={p.simulatorAvailability.includes("FULL") || p.simulatorAvailability === "AVAILABLE" ? "Available" : "QUICK-only"} />
          </div>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
            <MetricCard label="Min" value={fmt.n(p.min, 3)} />
            <MetricCard label="Median" value={fmt.n(p.median ?? null, 3)} />
            <MetricCard label="Mean" value={fmt.n(p.mean, 3)} />
            <MetricCard label="Max" value={fmt.n(p.max, 3)} />
            <MetricCard label="Std dev" value={fmt.n(p.std, 3)} />
          </div>
          {p.histogram && p.histogram.length > 0 && (
            <div>
              <div className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-slate-400">Development-fold distribution</div>
              <Histogram bins={p.histogram} color="#7c3aed" height={170} />
            </div>
          )}
          <div className="rounded-lg border border-slate-200 bg-slate-50 p-3 text-xs text-slate-600">
            Temporal safety: <b className="text-emerald-700">fold-local (2023)</b> — IV / MI / statistics learned on development only; validation 2024 and frozen 2025 never determine this feature's parameters. Season means: {Object.entries(p.seasonMeans).map(([y, v]) => `${y} ${v !== null ? fmt.n(v, 3) : "—"}`).join(" · ")}.
          </div>
        </div>
      )}
    </Card>
  );
}

function ScoreTile({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white px-3 py-2">
      <div className="text-[10px] font-semibold uppercase tracking-wide text-slate-500">{label}</div>
      <div className="mt-0.5 text-base font-semibold tabular-nums text-slate-900">{value}</div>
      {sub ? <div className="text-[10px] text-slate-400">{sub}</div> : null}
    </div>
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
    <Card title="Test engineered features" icon={Wand2}
      description="Train the same baseline model twice — Control = current governed feature set, Challenger = current set + your engineered features — holding the model family and preprocessing constant, to see whether the engineered features improve validation performance. (Expert term: controlled feature ablation / addition test.)"
      action={<Button size="sm" onClick={run} disabled={post.status === "loading" || engineered.length === 0} tone="dark">{post.status === "loading" ? "Testing…" : "Compare Base vs Engineered Features"}</Button>}>
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
const SEG_METHODS = [{ value: "kmeans", label: "K-means guidance" }, { value: "dbscan", label: "DBSCAN (density)" }, { value: "grid", label: "3×3 grid" }];

export function SegmentationStep() {
  const { notes, setNote } = useCockpitStore();
  const population = (notes["seg.population"] as "BATTERS" | "PITCHERS") || "BATTERS";
  const setPopulation = (p: string) => setNote("seg.population", p);
  const method = notes["seg.method"] || "kmeans";
  const setMethod = (m: string) => setNote("seg.method", m);
  const summary = useEndpoint<any>(`/cockpit/segmentation/summary?population=${population}`, [population]);
  const feats: string[] = summary.data?.candidateFeatures || [];
  const short = (f: string) => f.replace(population === "BATTERS" ? "batter_" : "pitcher_", "");

  // K-means + PCA + stability at a chosen K (persisted)
  const km = usePost<any>(); const pca = usePost<any>(); const stab = usePost<any>();
  const selectedK = Number(notes["seg.k"]) || 0;
  const runK = () => km.run("/cockpit/segmentation/kmeans", { population, kMin: 2, kMax: 8 }).then((r: any) => selectK(Number(notes["seg.k"]) || r.recommendedK));
  const selectK = (k: number) => { setNote("seg.k", String(k)); pca.run("/cockpit/segmentation/pca", { population, k }); stab.run("/cockpit/segmentation/stability", { population, k }); };
  // Auto-load the bounded K-means guidance on entry so the page is never a blank white region.
  useEffect(() => {
    if (method === "kmeans" && km.status === "idle" && summary.data) runK();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [method, population, summary.data]);

  // DBSCAN
  const db = usePost<any>();
  const [eps, setEps] = useState<number | "">("");
  const [minSamples, setMinSamples] = useState<number | "">("");
  const runDb = () => db.run("/cockpit/segmentation/dbscan", { population, ...(eps !== "" ? { eps } : {}), ...(minSamples !== "" ? { minSamples } : {}) });

  // Grid + guidance
  const grid = usePost<any>();
  const guide = useEndpoint<any>(`/cockpit/segmentation/grid-guidance?population=${population}`, [population]);
  const dimX = notes["seg.dimX"] || (population === "BATTERS" ? "batter_hr_per_pa" : "pitcher_whip");
  const dimY = notes["seg.dimY"] || (population === "BATTERS" ? "batter_so_per_pa" : "pitcher_so_per_bfp");
  const setDim = (axis: "X" | "Y", v: string) => setNote(axis === "X" ? "seg.dimX" : "seg.dimY", v);
  const runGrid = () => grid.run("/cockpit/segmentation/grid", { population, dimX, dimY });

  return (
    <div className="space-y-4">
      <Card title="Player segmentation — exploratory workbench" icon={Boxes} action={<Pill label="RESEARCH ONLY" tone="violet" />}
        description="Do natural batter/pitcher archetypes exist? Fitted on development (2023) player state. It never changes the PA model and creates no per-player boosts — any use as a feature must go through an explicit challenger.">
        <div className="flex flex-wrap items-end gap-4">
          <div><div className="mb-1 text-xs font-semibold uppercase text-slate-500">Population</div>
            <Segmented value={population} onChange={setPopulation as any} options={[{ value: "BATTERS", label: "Batters" }, { value: "PITCHERS", label: "Pitchers" }]} /></div>
          <div><div className="mb-1 text-xs font-semibold uppercase text-slate-500">Method</div>
            <Segmented value={method} onChange={setMethod as any} options={SEG_METHODS} /></div>
          {summary.data && <div className="text-sm text-slate-600">{summary.data.players} players · {feats.length} features</div>}
        </div>
      </Card>

      {/* ---------------- K-means guidance ---------------- */}
      {method === "kmeans" && (
        <>
          <Card title="K-means guidance" icon={Boxes} description="Fit K = 2–8 and read the diagnostics. Higher silhouette and lower Davies-Bouldin are generally better; very small clusters are often unstable. Statistical separation alone does not prove predictive usefulness."
            action={<Button tone="dark" onClick={runK} disabled={km.status === "loading"}>{km.status === "loading" ? "Clustering…" : "▶ Fit K = 2–8"}</Button>}>
            {km.data && (
              <>
                <div className="mb-3 inline-flex items-center gap-2 rounded-lg border border-cyan-200 bg-cyan-50 px-3 py-1.5 text-xs"><Pill label={`Recommended exploratory K = ${km.data.recommendedK}`} tone="cyan" /><span className="text-slate-600">{km.data.recommendationRationale}</span></div>
                <LineChart categories={km.data.results.map((r: any) => `K${r.k}`)}
                  series={[{ name: "Silhouette (↑)", data: km.data.results.map((r: any) => r.silhouette), color: "#0891b2" }, { name: "Davies-Bouldin (↓)", data: km.data.results.map((r: any) => r.daviesBouldin), color: "#e11d48" }]} height={190} />
                <div className="mt-3 overflow-x-auto"><table className="w-full min-w-[560px] text-left text-xs">
                  <thead><tr className="text-slate-500">{["K", "Silhouette", "Davies-Bouldin", "Size balance", "Smallest cluster", "", ""].map((h, i) => <th key={i} className="border-b border-slate-200 px-2 py-1.5 font-semibold uppercase">{h}</th>)}</tr></thead>
                  <tbody>{km.data.results.map((r: any) => (
                    <tr key={r.k} className={selectedK === r.k ? "bg-cyan-50" : ""}>
                      <td className="border-b border-slate-100 px-2 py-1.5 font-semibold">{r.k}{r.k === km.data.recommendedK ? " ★" : ""}</td>
                      <td className="border-b border-slate-100 px-2 py-1.5 tabular-nums">{fmt.n(r.silhouette, 3)}</td>
                      <td className="border-b border-slate-100 px-2 py-1.5 tabular-nums">{fmt.n(r.daviesBouldin, 2)}</td>
                      <td className="border-b border-slate-100 px-2 py-1.5 tabular-nums">{fmt.n(r.sizeBalance, 2)}</td>
                      <td className="border-b border-slate-100 px-2 py-1.5 tabular-nums">{fmt.pct(r.minClusterShare)}{r.tinyCluster ? <Pill label="tiny" tone="amber" /> : null}</td>
                      <td className="border-b border-slate-100 px-2 py-1.5" colSpan={2}><button onClick={() => selectK(r.k)} className={`rounded border px-2 py-0.5 text-[10px] font-semibold ${selectedK === r.k ? "border-cyan-600 bg-cyan-600 text-white" : "border-slate-300 text-slate-600 hover:bg-slate-50"}`}>{selectedK === r.k ? "Selected" : "Explore this K"}</button></td>
                    </tr>))}</tbody>
                </table></div>
                <p className="mt-2 text-xs text-slate-500">{km.data.note}</p>
              </>
            )}
          </Card>
          {(pca.data || stab.data) && <SegClusterViews pca={pca.data} stab={stab.data} feats={feats} short={short} titleK={selectedK} />}
        </>
      )}

      {/* ---------------- DBSCAN ---------------- */}
      {method === "dbscan" && (
        <>
          <Card title="DBSCAN — density segmentation" icon={Boxes} description="Finds dense archetype cores and leaves genuine outliers as NOISE (never forced into a cluster). Leave eps / min-samples blank to use the k-distance heuristic."
            action={<Button tone="dark" onClick={runDb} disabled={db.status === "loading"}>{db.status === "loading" ? "Clustering…" : "▶ Run DBSCAN"}</Button>}>
            <div className="flex flex-wrap items-end gap-3">
              <label className="flex flex-col gap-1 text-xs"><span className="font-semibold uppercase text-slate-500">epsilon (eps)</span><input type="number" step={0.1} value={eps} placeholder={db.data ? String(db.data.suggestedEps) : "auto"} onChange={(e) => setEps(e.target.value === "" ? "" : Number(e.target.value))} className="w-28 rounded-lg border border-slate-300 px-2 py-1.5 text-sm" /></label>
              <label className="flex flex-col gap-1 text-xs"><span className="font-semibold uppercase text-slate-500">min samples</span><input type="number" step={1} value={minSamples} placeholder="dim+1" onChange={(e) => setMinSamples(e.target.value === "" ? "" : Number(e.target.value))} className="w-28 rounded-lg border border-slate-300 px-2 py-1.5 text-sm" /></label>
              {db.data && <div className="text-xs text-slate-500">suggested eps <b>{db.data.suggestedEps}</b> (k-distance 90th pct)</div>}
            </div>
            {db.data && (
              <div className="mt-3 space-y-3">
                <div className="grid gap-3 sm:grid-cols-4">
                  <MetricCard label="Clusters" value={String(db.data.nClusters)} detail={`eps ${db.data.eps} · min ${db.data.minSamples}`} />
                  <MetricCard label="Noise / unassigned" value={fmt.int(db.data.noise)} detail={fmt.pct(db.data.noisePct)} />
                  <MetricCard label="Players" value={String(db.data.players)} detail="development" />
                  <MetricCard label="Assigned" value={String(db.data.players - db.data.noise)} detail={fmt.pct(1 - db.data.noisePct)} />
                </div>
                <div className="grid gap-4 lg:grid-cols-2">
                  <div><div className="mb-1 text-[11px] font-semibold uppercase text-slate-400">k-distance (choose eps at the elbow)</div>
                    <LineChart categories={db.data.kDistance.map((d: any) => String(d.rank))} series={[{ name: `${db.data.minSamples}-distance`, data: db.data.kDistance.map((d: any) => d.dist), color: "#7c3aed" }]} height={180} /></div>
                  <div><div className="mb-1 text-[11px] font-semibold uppercase text-slate-400">PCA map — cluster -1 is noise</div><ScatterClusters points={db.data.points} height={200} /></div>
                </div>
                {db.data.clusters.length > 0 && <div className="overflow-x-auto"><table className="w-full min-w-[560px] text-left text-xs">
                  <thead><tr className="text-slate-500"><th className="border-b border-slate-200 px-2 py-1.5 font-semibold uppercase">Cluster</th><th className="border-b border-slate-200 px-2 py-1.5 font-semibold uppercase">Players</th><th className="border-b border-slate-200 px-2 py-1.5 font-semibold uppercase">PA share</th>{feats.map((f) => <th key={f} className="border-b border-slate-200 px-2 py-1.5 font-semibold">{short(f)}</th>)}</tr></thead>
                  <tbody>{db.data.clusters.map((c: any) => (<tr key={c.cluster}><td className="border-b border-slate-100 px-2 py-1.5 font-semibold">C{c.cluster}</td><td className="border-b border-slate-100 px-2 py-1.5 tabular-nums">{c.players}</td><td className="border-b border-slate-100 px-2 py-1.5 tabular-nums">{fmt.pct(c.paShare)}</td>{feats.map((f) => <td key={f} className="border-b border-slate-100 px-2 py-1.5 tabular-nums text-slate-600">{fmt.n(c.centroid[f], 3)}</td>)}</tr>))}</tbody>
                </table></div>}
                <p className="text-xs text-slate-500">{db.data.note}{km.data ? ` K-means (recommended K=${km.data.recommendedK}) found ${km.data.recommendedK} clusters with no explicit noise set — DBSCAN isolates ${fmt.pct(db.data.noisePct)} as outliers.` : ""}</p>
              </div>
            )}
          </Card>
        </>
      )}

      {/* ---------------- 3×3 grid + guidance ---------------- */}
      {method === "grid" && (
        <>
          <Card title="Grid guidance — suggested dimensions" icon={Boxes} description="Ranked from the real development data (cell balance × non-redundancy), not baseball opinion. Load a suggestion or override.">
            <LoadGate state={guide}>
              {guide.data && <div className="flex flex-wrap gap-2">
                {guide.data.suggestions.map((s: any) => (
                  <button key={`${s.dimX}-${s.dimY}`} onClick={() => { setDim("X", s.dimX); setDim("Y", s.dimY); }}
                    className={`rounded-lg border px-3 py-2 text-left text-xs ${dimX === s.dimX && dimY === s.dimY ? "border-cyan-600 bg-cyan-50" : "border-slate-200 bg-white hover:border-slate-300"}`}>
                    <div className="font-semibold text-slate-800">{short(s.dimX)} × {short(s.dimY)}</div>
                    <div className="mt-0.5 text-[10px] text-slate-500">score {s.score} · |r| {s.absCorr} · balance {s.cellBalance}{s.sparse ? " · sparse ⚠" : ""}</div>
                  </button>))}
              </div>}
              {guide.data && <p className="mt-2 text-[11px] text-slate-500">{guide.data.note}</p>}
            </LoadGate>
          </Card>
          <Card title="3×3 grid designer" icon={Boxes} description="Interpretable segmentation on two dimensions with development-only tercile boundaries."
            action={<Button size="sm" tone="dark" onClick={runGrid} disabled={grid.status === "loading"}>{grid.status === "loading" ? "Building…" : "Build grid"}</Button>}>
            <div className="flex flex-wrap items-end gap-3">
              <label className="flex flex-col gap-1 text-xs"><span className="font-semibold uppercase text-slate-500">Dimension X</span>
                <select value={dimX} onChange={(e) => setDim("X", e.target.value)} className="rounded-lg border border-slate-300 px-2 py-1.5 text-sm">{feats.map((f) => <option key={f} value={f}>{f}</option>)}</select></label>
              <label className="flex flex-col gap-1 text-xs"><span className="font-semibold uppercase text-slate-500">Dimension Y</span>
                <select value={dimY} onChange={(e) => setDim("Y", e.target.value)} className="rounded-lg border border-slate-300 px-2 py-1.5 text-sm">{feats.map((f) => <option key={f} value={f}>{f}</option>)}</select></label>
            </div>
            {grid.data && (() => {
              const minCell = Math.min(...grid.data.cells.map((c: any) => c.players));
              const sparse = minCell < Math.max(3, Math.round(grid.data.players / 30));
              return (
                <div className="mt-4">
                  <div className="grid grid-cols-3 gap-1.5" style={{ maxWidth: 420 }}>
                    {["HIGH", "MED", "LOW"].map((yl) => ["LOW", "MED", "HIGH"].map((xl) => {
                      const cell = grid.data.cells.find((c: any) => c.x === xl && c.y === yl);
                      const share = cell?.paShare || 0;
                      const tiny = (cell?.players ?? 0) < Math.max(3, Math.round(grid.data.players / 30));
                      return <div key={`${xl}-${yl}`} className={`rounded-lg border p-2 text-center ${tiny ? "border-amber-300" : "border-slate-200"}`} style={{ background: `rgba(8,145,178,${Math.min(share * 4, 0.6)})` }}>
                        <div className="text-[10px] font-semibold uppercase text-slate-500">{xl}·{yl}</div>
                        <div className="text-lg font-semibold tabular-nums text-slate-900">{cell?.players ?? 0}</div>
                        <div className="text-[10px] text-slate-500">{fmt.pct(share)} PA</div>
                      </div>;
                    }))}
                  </div>
                  <p className="mt-2 text-xs text-slate-500">X = {grid.data.dimX} (→ LOW/MED/HIGH), Y = {grid.data.dimY} (↑). Boundaries: {grid.data.boundaryScope}.{sparse ? <span className="font-semibold text-amber-700"> Sparse-cell warning: smallest cell has {minCell} players.</span> : ""} Grid is exploratory until predictive-tested via ablation.</p>
                </div>
              );
            })()}
          </Card>
        </>
      )}
    </div>
  );
}

function SegClusterViews({ pca, stab, feats, short, titleK }: { pca: any; stab: any; feats: string[]; short: (f: string) => string; titleK: number }) {
  return (
    <>
      <div className="grid gap-4 lg:grid-cols-2">
        {pca && <Card title={`PCA cluster map${titleK ? ` · K=${titleK}` : ""}`} description={`PC1 ${fmt.pct(pca.explainedVariance[0])} + PC2 ${fmt.pct(pca.explainedVariance[1])} of variance.`} icon={Boxes}>
          <ScatterClusters points={pca.points} />
        </Card>}
        {stab && <Card title="Temporal cluster stability" description="2024 players projected onto 2023-fitted centroids (descriptive)." icon={Boxes}>
          <MetricCard label="Same cluster 2023→2024" value={stab.sameClusterPct != null ? fmt.pct(stab.sameClusterPct) : "—"} detail={`${stab.commonPlayers} common players`} />
          <p className="mt-2 text-xs text-slate-500">{stab.note}</p>
        </Card>}
      </div>
      {pca && <Card title="Cluster profiles" description="Mean prior-state characteristics per cluster (interpret, then label)." icon={Boxes}>
        <div className="overflow-x-auto"><table className="w-full min-w-[720px] text-left text-xs">
          <thead><tr className="text-slate-500"><th className="border-b border-slate-200 px-2 py-1.5 font-semibold uppercase">Cluster</th><th className="border-b border-slate-200 px-2 py-1.5 font-semibold uppercase">Players</th>{feats.map((f) => <th key={f} className="border-b border-slate-200 px-2 py-1.5 font-semibold">{short(f)}</th>)}</tr></thead>
          <tbody>{pca.profiles.map((p: any) => (<tr key={p.cluster}><td className="border-b border-slate-100 px-2 py-1.5 font-semibold">C{p.cluster}</td><td className="border-b border-slate-100 px-2 py-1.5 tabular-nums">{p.players}</td>{feats.map((f) => <td key={f} className="border-b border-slate-100 px-2 py-1.5 tabular-nums text-slate-600">{fmt.n(p.centroid[f], 3)}</td>)}</tr>))}</tbody>
        </table></div>
      </Card>}
    </>
  );
}

// ============================================================ 08 Temporal Split
// Source chronology (2021–2025) that redraws per policy. 2021–2022 remain visible as prior history
// even though they are never Gen-2 target rows; 2025 is never depicted as a tuning fold.
function TemporalChronology({ policy }: { policy: string }) {
  const band = (label: string, cls: string) => ({ label, cls });
  const roles: Record<number, { label: string; cls: string }> = {
    2021: band("PRIOR HISTORY", "bg-slate-400"),
    2022: band("PRIOR HISTORY", "bg-slate-400"),
    2023: band("DEVELOPMENT", "bg-emerald-500"),
    2024: band("VALIDATION", "bg-amber-500"),
    2025: band("FROZEN FINAL", "bg-rose-500 ring-2 ring-rose-300"),
  };
  if (policy === "ROLLING_ORIGIN" || policy === "EXPANDING_WINDOW") { roles[2024] = band("VAL → then DEV", "bg-amber-500"); }
  if (policy === "DATE_HOLDOUT") { roles[2023] = band("DEV | HOLDOUT", "bg-emerald-500"); }
  if (policy === "RANDOM") { roles[2023] = band("RANDOM (no time order)", "bg-rose-400"); }
  return (
    <div className="mb-3">
      <div className="flex gap-1">
        {[2021, 2022, 2023, 2024, 2025].map((y) => (
          <div key={y} className="flex-1 text-center">
            <div className={`flex h-8 items-center justify-center rounded text-xs font-bold text-white ${roles[y].cls}`}>{y}</div>
            <div className="mt-0.5 text-[9px] font-semibold uppercase text-slate-500">{roles[y].label}</div>
          </div>
        ))}
      </div>
      {policy === "RANDOM" && <div className="mt-1 text-[11px] font-semibold text-rose-600">⚠ Random split does not preserve temporal order — research comparison only.</div>}
    </div>
  );
}

const TEMPORAL_POLICIES = [
  { id: "SEASON_HOLDOUT", label: "Season holdout", blurb: "Train 2023 → validate 2024 → frozen 2025. The governed Gen-2 pattern." },
  { id: "ROLLING_ORIGIN", label: "Rolling origin", blurb: "Expanding rolling-origin folds; the frozen season is evaluation-only, never a tuning fold." },
  { id: "EXPANDING_WINDOW", label: "Expanding window", blurb: "Accumulate development history, then validate the next window." },
  { id: "DATE_HOLDOUT", label: "Date holdout", blurb: "Split the development season by an actual game-date boundary." },
  { id: "RANDOM", label: "Random split", blurb: "Ignores time order — for research comparison only." },
];

export function TemporalSplitStep() {
  const split = useEndpoint<TemporalSplit>("/cockpit/temporal-split");
  const { notes, setNote, markSaved } = useCockpitStore();
  const savedPolicy = notes["temporal.policy"] || "SEASON_HOLDOUT";        // governed default
  const [policy, setPolicy] = useState(notes["temporal.previewPolicy"] || savedPolicy);
  const [boundaryDate, setBoundaryDate] = useState("2023-07-01");
  const [ackRandom, setAckRandom] = useState(false);
  const preview = usePost<any>();
  const isRandom = policy === "RANDOM";
  const isRevised = policy !== "SEASON_HOLDOUT";
  const unsaved = policy !== savedPolicy;

  useEffect(() => {
    setNote("temporal.previewPolicy", policy);                             // persist the previewed choice
    preview.run("/cockpit/temporal-split/preview", { policy, boundaryDate });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [policy, boundaryDate]);

  const savePolicy = () => { setNote("temporal.policy", policy); markSaved("split"); };
  const p = preview.data;

  return (
    <LoadGate state={split}>
      {split.data && (
        <div className="space-y-4">
          <Card title="Temporal split policy" icon={CalendarClock}
            description="Choose a validation policy and see the concrete folds with real row counts. Frozen 2025 is never a tuning/selection fold."
            action={<Pill label={unsaved ? "Unsaved preview" : "Saved"} tone={unsaved ? "amber" : "emerald"} />}>
            <div className="flex flex-wrap gap-2">
              {TEMPORAL_POLICIES.map((t) => (
                <button key={t.id} onClick={() => setPolicy(t.id)}
                  className={`rounded-lg border px-3 py-2 text-left text-xs transition-colors ${policy === t.id ? "border-cyan-600 bg-cyan-50 ring-1 ring-cyan-300" : "border-slate-200 bg-white hover:border-slate-300"}`}>
                  <div className="font-semibold text-slate-800">{t.label}{t.id === "SEASON_HOLDOUT" ? " · governed" : ""}{t.id === "RANDOM" ? "" : ""}</div>
                  <div className="mt-0.5 max-w-[220px] text-[11px] text-slate-500">{t.blurb}</div>
                  {t.id === "RANDOM" && <div className="mt-1 text-[10px] font-semibold text-rose-600">NOT RECOMMENDED FOR TEMPORAL SPORTS FORECASTING</div>}
                </button>
              ))}
            </div>
            {policy === "DATE_HOLDOUT" && (
              <label className="mt-3 flex items-center gap-2 text-xs font-semibold text-slate-600">Development date boundary
                <input type="date" value={boundaryDate} min="2023-03-30" max="2023-12-31" onChange={(e) => setBoundaryDate(e.target.value)} className="rounded-lg border border-slate-300 px-2 py-1 text-sm" /></label>
            )}
            {isRandom && (
              <label className="mt-3 flex items-center gap-2 text-xs font-semibold text-rose-700"><input type="checkbox" checked={ackRandom} onChange={(e) => setAckRandom(e.target.checked)} className="h-4 w-4 rounded border-rose-300" /> I acknowledge a random split is research-only and breaks temporal integrity.</label>
            )}
          </Card>

          {preview.status === "loading" && !p && <Card title="Computing folds…"><div className="flex justify-center py-6"><span className="h-6 w-6 animate-spin rounded-full border-2 border-slate-300 border-t-cyan-600" /></div></Card>}
          {preview.status === "error" && <div className="rounded-xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-800">Temporal preview could not be computed. {preview.error}</div>}

          {p && (
            <>
              <Card title="Proposed folds" icon={CalendarClock}
                description={`${p.policy.replace(/_/g, " ")} · ${p.recommended ? "recommended" : p.researchOnly ? "research only" : "eligible"} · ${p.matchesGovernedContract ? "matches the governed Gen-2 contract" : "differs from the governed contract"}.`}>
                <TemporalChronology policy={p.policy} />
                <div className="space-y-2">
                  {p.folds.map((f: any, i: number) => (
                    <div key={i} className="rounded-lg border border-slate-200 p-3">
                      <div className="mb-1 text-xs font-semibold uppercase text-slate-500">{String(f.foldId).replace(/-/g, " ")}{f.researchOnly ? " · research only" : ""}{f.boundaryDate ? ` · boundary ${f.boundaryDate}` : ""}</div>
                      <div className="flex flex-wrap gap-2 text-xs">
                        <span className="rounded bg-emerald-50 px-2 py-1 font-semibold text-emerald-700">Train {(f.training.seasons || [f.training.season]).join(",")}{f.training.dateRange ? ` ${f.training.dateRange[0].slice(0,10)}→${String(f.training.dateRange[1]).slice(0,10)}` : ""} · {fmt.int(f.training.rows)}</span>
                        <span className={`rounded px-2 py-1 font-semibold ${f.validation.role === "FROZEN_EVAL_ONLY" ? "bg-rose-50 text-rose-700" : "bg-amber-50 text-amber-700"}`}>{f.validation.role === "FROZEN_EVAL_ONLY" ? "Frozen eval" : "Validate"} {f.validation.season}{f.validation.dateRange ? ` ${String(f.validation.dateRange[0]).slice(0,10)}→${f.validation.dateRange[1].slice(0,10)}` : ""} · {fmt.int(f.validation.rows)}</span>
                        {f.frozen && <span className="rounded bg-rose-50 px-2 py-1 font-semibold text-rose-700">Frozen {f.frozen.season} · {fmt.int(f.frozen.rows)} (held out)</span>}
                      </div>
                    </div>
                  ))}
                </div>
                <div className="mt-2 text-[11px] text-slate-500">{p.frozenNote} · development dates {p.devDateRange[0].slice(0,10)} → {p.devDateRange[1].slice(0,10)}.</div>
                <div className="mt-3 flex flex-wrap items-center gap-2">
                  {isRevised ? (
                    <>
                      <Button tone="dark" onClick={savePolicy} disabled={isRandom && !ackRandom}>Create revised temporal experiment</Button>
                      <span className="text-[11px] text-slate-500">Saves a research policy for a new challenger — never mutates the governed Gen-2 contract or D3.</span>
                    </>
                  ) : (
                    <><Button tone="primary" onClick={savePolicy}>{unsaved ? "Save temporal policy" : "Saved ✓"}</Button>
                      <span className="text-[11px] text-slate-500">Governed season-holdout — dev 2023 / val 2024 / frozen 2025.</span></>
                  )}
                  <Pill label={p.leakageStatus.replace(/_/g, " ")} tone={p.leakageStatus.includes("PROTECTED") ? "emerald" : "rose"} />
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
            </>
          )}
        </div>
      )}
    </LoadGate>
  );
}
