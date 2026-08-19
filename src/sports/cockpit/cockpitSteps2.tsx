// Cockpit workflow steps 09–15: Model Laboratory, Hyperparameter Tuning, Evaluation,
// Calibration, Simulation Impact, Champion/Challenger, Registry.
import { useMemo, useState } from "react";
import {
  FlaskConical, SlidersHorizontal, BarChart3, Gauge, Orbit, Trophy, Boxes, Rocket, Check, X,
} from "lucide-react";
import { useEffect } from "react";
import {
  useEndpoint, usePost, useCockpitStore, cockpitPost,
  type ModelFamily, type Champion, type ExperimentResult, type AutopilotResult,
  type SimResult, type ExperimentIndexRow, type Eligibility, type FullSimResult,
} from "./cockpitApi";
import {
  Card, Pill, MetricCard, Button, Segmented, NumberField, LoadGate, GroupedBars, BarChart,
  ConfusionHeatmap, CalibrationChart, fmt,
} from "./cockpitUi";

function useConfig() {
  return useCockpitStore((s) => s.config);
}

// ============================================================ 09 Model Laboratory
export function ModelLabStep() {
  const fams = useEndpoint<{ families: ModelFamily[] }>("/cockpit/model-families");
  const store = useCockpitStore();
  const config = store.config;
  const post = usePost<ExperimentResult>();

  const setHyperKey = (k: string, v: any) => store.setHyper({ ...config.hyperparameters, [k]: v });
  const useD3 = () => {
    store.setFamily("logistic");
    store.setHyper({ C: 0.05, maxIter: 2000 });
  };
  const run = async () => {
    const r = await post.run("/cockpit/experiment/run", config);
    store.setLastResult(r);
  };

  return (
    <LoadGate state={fams}>
      {fams.data && (
        <div className="space-y-4">
          <Card title="Algorithm laboratory" description="Choose a family and hyperparameters, then run a real challenger against the D3 champion. Availability is honest — uninstalled libraries are marked, not faked." icon={FlaskConical}
            action={<Button size="sm" tone="ghost" onClick={useD3}>Use current D3 settings</Button>}>
            <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
              {fams.data.families.map((f) => (
                <button key={f.id} disabled={!f.available} onClick={() => store.setFamily(f.id)}
                  className={`rounded-xl border p-3 text-left transition-colors ${config.family === f.id ? "border-cyan-600 bg-cyan-50 ring-1 ring-cyan-200" : f.available ? "border-slate-200 bg-white hover:border-slate-300" : "border-slate-200 bg-slate-50 opacity-60"}`}>
                  <div className="flex items-center justify-between"><span className="text-sm font-semibold text-slate-900">{f.label}</span></div>
                  <div className="mt-2 flex flex-wrap gap-1">
                    <Pill label={f.status.replace(/_/g, " ")} tone={f.available ? "emerald" : "slate"} />
                    {f.simulatorEligible ? <Pill label="SIM-READY" tone="cyan" /> : null}
                  </div>
                </button>
              ))}
            </div>
          </Card>

          <Card title="Hyperparameters" description={`Feature set: ${config.features.length} features · outliers: ${config.outlierPolicy.globalMethod} · missing: ${config.missingPolicy.globalMethod}${config.missingPolicy.addIndicator ? " +indicator" : ""}`} icon={SlidersHorizontal}>
            <div className="flex flex-wrap gap-4">
              {config.family === "logistic" && <>
                <div className="w-32"><NumberField label="C (inverse reg)" value={config.hyperparameters.C ?? 1} step={0.05} onChange={(v) => setHyperKey("C", v)} /></div>
                <div className="w-32"><NumberField label="max iter" value={config.hyperparameters.maxIter ?? 2000} step={500} onChange={(v) => setHyperKey("maxIter", v)} /></div>
              </>}
              {(config.family === "random_forest" || config.family === "extra_trees") && <>
                <div className="w-32"><NumberField label="n estimators" value={config.hyperparameters.nEstimators ?? 200} step={50} onChange={(v) => setHyperKey("nEstimators", v)} /></div>
                <div className="w-32"><NumberField label="max depth" value={config.hyperparameters.maxDepth ?? 12} step={1} onChange={(v) => setHyperKey("maxDepth", v)} /></div>
                <div className="w-32"><NumberField label="min leaf" value={config.hyperparameters.minSamplesLeaf ?? 50} step={10} onChange={(v) => setHyperKey("minSamplesLeaf", v)} /></div>
              </>}
              {config.family === "hist_gradient_boosting" && <>
                <div className="w-32"><NumberField label="max iter" value={config.hyperparameters.maxIter ?? 200} step={50} onChange={(v) => setHyperKey("maxIter", v)} /></div>
                <div className="w-32"><NumberField label="learning rate" value={config.hyperparameters.learningRate ?? 0.1} step={0.05} onChange={(v) => setHyperKey("learningRate", v)} /></div>
                <div className="w-32"><NumberField label="L2" value={config.hyperparameters.l2 ?? 0} step={0.5} onChange={(v) => setHyperKey("l2", v)} /></div>
              </>}
              {config.family === "mlp" && <div className="w-40"><NumberField label="alpha" value={config.hyperparameters.alpha ?? 0.0001} step={0.0001} onChange={(v) => setHyperKey("alpha", v)} /></div>}
              {(config.family === "xgboost" || config.family === "lightgbm") && <>
                <div className="w-32"><NumberField label="n estimators" value={config.hyperparameters.nEstimators ?? 300} step={50} onChange={(v) => setHyperKey("nEstimators", v)} /></div>
                <div className="w-32"><NumberField label="learning rate" value={config.hyperparameters.learningRate ?? 0.1} step={0.05} onChange={(v) => setHyperKey("learningRate", v)} /></div>
              </>}
              {config.family === "svm" && <div className="w-32"><NumberField label="C" value={config.hyperparameters.C ?? 1} step={0.5} onChange={(v) => setHyperKey("C", v)} /></div>}
            </div>
            {config.family === "svm" && <p className="mt-3 rounded-lg border border-amber-200 bg-amber-50 p-2 text-xs text-amber-800">Linear SVM is calibrated (sigmoid, 3-fold) on the development fold; kernel SVM is not run on the full population. Expect a longer fit.</p>}
            <div className="mt-4 flex items-center gap-3">
              <Button onClick={run} disabled={post.status === "loading" || config.features.length === 0}>{post.status === "loading" ? "Training…" : "▶ Run experiment"}</Button>
              {post.status === "loading" && <span className="flex items-center gap-2 text-sm text-slate-500"><span className="h-4 w-4 animate-spin rounded-full border-2 border-slate-300 border-t-cyan-600" />Fitting on 2023, evaluating 2024 & 2025…</span>}
              {post.status === "error" && <span className="text-sm text-rose-600">{post.error}</span>}
            </div>
          </Card>

          {store.lastResult && <ExperimentHeadline r={store.lastResult} />}
          <AutopilotPanel />
        </div>
      )}
    </LoadGate>
  );
}

function AutopilotPanel() {
  const store = useCockpitStore();
  const post = usePost<AutopilotResult>();
  const [budget, setBudget] = useState<"quick" | "standard" | "deep">("quick");
  const run = async () => {
    const r = await post.run("/cockpit/autopilot", { config: store.config, budget });
    store.setLastAutopilot(r);
  };
  const ap = store.lastAutopilot;
  const mine = store.lastResult;
  return (
    <Card title="Autopilot benchmark" description="An automated, bounded candidate search you compete against. It never silently replaces your model — you run it separately." icon={Rocket}
      action={<Pill label="MY MODEL vs AUTOPILOT" tone="violet" />}>
      <div className="flex flex-wrap items-end gap-4">
        <div><div className="mb-1 text-xs font-semibold uppercase text-slate-500">Budget</div>
          <Segmented value={budget} onChange={setBudget as any} options={[{ value: "quick", label: "Quick" }, { value: "standard", label: "Standard" }, { value: "deep", label: "Deep" }]} /></div>
        <Button onClick={run} disabled={post.status === "loading"} tone="dark">{post.status === "loading" ? "Running Autopilot…" : "▶ Run Autopilot"}</Button>
        {post.status === "loading" && <span className="flex items-center gap-2 text-sm text-slate-500"><span className="h-4 w-4 animate-spin rounded-full border-2 border-slate-300 border-t-cyan-600" />Searching a bounded candidate set on 2023→2024…</span>}
      </div>
      {ap && (
        <div className="mt-4 space-y-4">
          {mine && ap.best && ap.best.val2024 && (
            <div className="grid gap-3 sm:grid-cols-3">
              <div className="rounded-xl border border-cyan-200 bg-cyan-50/60 p-3"><div className="text-xs font-semibold uppercase text-cyan-700">My model</div><div className="mt-1 text-2xl font-semibold tabular-nums text-slate-900">{fmt.n(mine.headline.val2024.logLoss)}</div><div className="text-xs text-slate-500">{mine.familyLabel}</div></div>
              <div className="rounded-xl border border-violet-200 bg-violet-50/60 p-3"><div className="text-xs font-semibold uppercase text-violet-700">Autopilot best</div><div className="mt-1 text-2xl font-semibold tabular-nums text-slate-900">{fmt.n(ap.best.val2024.logLoss)}</div><div className="text-xs text-slate-500">{ap.best.label}</div></div>
              <div className="rounded-xl border border-slate-200 bg-slate-50 p-3"><div className="text-xs font-semibold uppercase text-slate-500">Champion D3</div><div className="mt-1 text-2xl font-semibold tabular-nums text-slate-900">{fmt.n(ap.champion.val2024.logLoss)}</div><div className="text-xs text-slate-500">C4 · C={ap.champion.C}</div></div>
            </div>
          )}
          <div className="overflow-x-auto">
            <table className="w-full min-w-[560px] text-left text-xs">
              <thead><tr className="text-slate-500">{["Candidate", "Family", "2024 LL", "2025 LL", "Runtime", "Status"].map((h) => <th key={h} className="border-b border-slate-200 px-2 py-1.5 font-semibold uppercase">{h}</th>)}</tr></thead>
              <tbody>{ap.candidates.map((c, i) => (
                <tr key={i} className={ap.best && c.label === ap.best.label ? "bg-violet-50/60" : ""}>
                  <td className="border-b border-slate-100 px-2 py-1.5 font-semibold text-slate-800">{c.label}{ap.best && c.label === ap.best.label ? " ★" : ""}</td>
                  <td className="border-b border-slate-100 px-2 py-1.5">{c.family}</td>
                  <td className="border-b border-slate-100 px-2 py-1.5 tabular-nums font-semibold">{c.val2024 ? fmt.n(c.val2024.logLoss) : "—"}</td>
                  <td className="border-b border-slate-100 px-2 py-1.5 tabular-nums text-slate-500">{c.frozen2025 ? fmt.n(c.frozen2025.logLoss) : "—"}</td>
                  <td className="border-b border-slate-100 px-2 py-1.5 tabular-nums text-slate-500">{c.runtimeSeconds ? `${fmt.n(c.runtimeSeconds, 1)}s` : "—"}</td>
                  <td className="border-b border-slate-100 px-2 py-1.5">{c.status === "COMPLETED" ? <Pill label="ok" tone="emerald" /> : <Pill label="failed" tone="rose" />}</td>
                </tr>))}</tbody>
            </table>
          </div>
          <p className="text-xs text-slate-500">{ap.limitations.join(" ")}</p>
        </div>
      )}
    </Card>
  );
}

function ExperimentHeadline({ r }: { r: ExperimentResult }) {
  const beat = r.comparison.beatsChampion2024;
  return (
    <Card title="Latest challenger result" description={`${r.familyLabel} · ${r.featureCount} features → ${r.expandedFeatureCount} columns · fit ${fmt.n(r.fitSeconds, 1)}s`} icon={FlaskConical}
      action={<Pill label={beat ? "BEATS CHAMPION (2024)" : "BELOW CHAMPION (2024)"} tone={beat ? "emerald" : "amber"} />}>
      <div className="grid gap-3 sm:grid-cols-3 lg:grid-cols-6">
        <MetricCard label="2024 log loss" value={fmt.n(r.headline.val2024.logLoss)} detail={fmt.signed(r.comparison.val2024.logLoss)} tone={r.comparison.val2024.logLoss < 0 ? "up" : "down"} />
        <MetricCard label="2024 Brier" value={fmt.n(r.headline.val2024.brierScore)} detail={fmt.signed(r.comparison.val2024.brierScore)} tone={r.comparison.val2024.brierScore < 0 ? "up" : "down"} />
        <MetricCard label="2024 ECE" value={fmt.n(r.headline.val2024.topLabelEce)} />
        <MetricCard label="2025 log loss" value={fmt.n(r.headline.frozen2025.logLoss)} detail={fmt.signed(r.comparison.frozen2025.logLoss)} tone={r.comparison.frozen2025.logLoss < 0 ? "up" : "down"} />
        <MetricCard label="2025 Brier" value={fmt.n(r.headline.frozen2025.brierScore)} />
        <MetricCard label="Champion 2024" value={fmt.n(r.champion.val2024.logLoss)} detail={`D3 C4 · C=${r.champion.C}`} />
      </div>
    </Card>
  );
}

// ============================================================ 10 Hyperparameter Tuning
export function TuningStep() {
  const store = useCockpitStore();
  const config = store.config;
  const [grid, setGrid] = useState("0.05, 0.2, 1.0");
  const [rows, setRows] = useState<{ C: number; ll2024: number; ll2025: number; runtime: number }[] | null>(null);
  const [running, setRunning] = useState(false);
  const combos = grid.split(",").map((x) => Number(x.trim())).filter((x) => !Number.isNaN(x));

  const runGrid = async () => {
    if (config.family !== "logistic") return;
    setRunning(true); setRows(null);
    const out: any[] = [];
    for (const C of combos) {
      const t0 = performance.now();
      const r = await cockpitPost<ExperimentResult>("/cockpit/experiment/run", { ...config, hyperparameters: { ...config.hyperparameters, C } });
      out.push({ C, ll2024: r.headline.val2024.logLoss, ll2025: r.headline.frozen2025.logLoss, runtime: (performance.now() - t0) / 1000 });
    }
    out.sort((a, b) => a.ll2024 - b.ll2024);
    setRows(out); setRunning(false);
    // apply best C to config
    if (out.length) store.setHyper({ ...config.hyperparameters, C: out[0].C });
  };

  return (
    <div className="space-y-4">
      <Card title="Hyperparameter search" description="Manual + grid search on the development/validation policy. The frozen 2025 season never participates in selection." icon={SlidersHorizontal}
        action={<Pill label="FROZEN EVALUATION PROTECTED" tone="rose" />}>
        {config.family !== "logistic" ? (
          <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">Grid search is wired for the Logistic family in this slice (the champion family). Select Logistic in Model Laboratory to run a C-grid. Tree/boosting grids are the next increment.</div>
        ) : (
          <>
            <div className="flex flex-wrap items-end gap-4">
              <label className="flex flex-col gap-1 text-xs"><span className="font-semibold uppercase tracking-wide text-slate-500">C grid (comma-separated)</span>
                <input value={grid} onChange={(e) => setGrid(e.target.value)} className="w-64 rounded-lg border border-slate-300 px-2.5 py-1.5 text-sm text-slate-900 focus:border-cyan-500 focus:outline-none" /></label>
              <div className="text-xs text-slate-500">{combos.length} candidate fits · 1 fold each · ~{combos.length} logistic fits on 2023</div>
              <Button onClick={runGrid} disabled={running || combos.length === 0} tone="dark">{running ? "Searching…" : "▶ Run grid search"}</Button>
            </div>
            {running && <div className="mt-3 flex items-center gap-2 text-sm text-slate-500"><span className="h-4 w-4 animate-spin rounded-full border-2 border-slate-300 border-t-cyan-600" />Fitting {combos.length} candidates…</div>}
            {rows && (
              <div className="mt-4 overflow-x-auto">
                <table className="w-full min-w-[480px] text-left text-sm">
                  <thead><tr className="text-slate-500">{["Rank", "C", "2024 log loss", "2025 log loss", "Runtime"].map((h) => <th key={h} className="border-b border-slate-200 px-3 py-2 text-xs font-semibold uppercase">{h}</th>)}</tr></thead>
                  <tbody>{rows.map((r, i) => (
                    <tr key={r.C} className={i === 0 ? "bg-emerald-50/60" : ""}><td className="border-b border-slate-100 px-3 py-2 font-semibold">{i + 1}{i === 0 ? " ★" : ""}</td>
                      <td className="border-b border-slate-100 px-3 py-2 tabular-nums">{r.C}</td>
                      <td className="border-b border-slate-100 px-3 py-2 tabular-nums font-semibold">{fmt.n(r.ll2024)}</td>
                      <td className="border-b border-slate-100 px-3 py-2 tabular-nums text-slate-500">{fmt.n(r.ll2025)}</td>
                      <td className="border-b border-slate-100 px-3 py-2 tabular-nums text-slate-500">{fmt.n(r.runtime, 1)}s</td></tr>))}</tbody>
                </table>
                <p className="mt-2 text-xs text-slate-500">Best C applied to the active experiment configuration. Selection used 2024 validation only.</p>
              </div>
            )}
          </>
        )}
      </Card>
    </div>
  );
}

// ============================================================ 11 Evaluation & Diagnostics
export function EvaluationStep() {
  const r = useCockpitStore((s) => s.lastResult);
  if (!r) return <NeedRun label="Run a challenger in Model Laboratory to populate evaluation diagnostics." />;
  const [season, setSeason] = useState<"val2024" | "frozen2025">("val2024");
  const m = r.metrics[season];
  const order: string[] = m.classOrder;
  const severe = order.map((c) => ({ c, brier: m.classwiseBrier[c], ece: m.classwiseEce[c] })).sort((a, b) => b.brier - a.brier);
  return (
    <div className="space-y-4">
      <Card title="Model comparison" description="Challenger vs the reproduced D3 champion across both seasons." icon={BarChart3}
        action={<Segmented value={season} onChange={setSeason as any} options={[{ value: "val2024", label: "2024 validation" }, { value: "frozen2025", label: "2025 frozen" }]} />}>
        <GroupedBars categories={["Log loss", "Brier", "Top-label ECE"]}
          series={[
            { name: "Champion D3 C4", data: [r.champion[season].logLoss, r.champion[season].brierScore, r.champion[season].topLabelEce], color: "#94a3b8" },
            { name: r.familyLabel, data: [m.logLoss, m.brierScore, m.topLabelEce], color: "#0891b2" },
          ]} valueFmt={(v) => fmt.n(v, 4)} height={240} />
      </Card>
      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Class-level performance" description="Per-outcome support, precision, recall, and class Brier." icon={BarChart3}>
          <div className="max-h-80 overflow-auto">
            <table className="w-full min-w-[440px] text-left text-xs">
              <thead className="sticky top-0 bg-white"><tr className="text-slate-500">{["Class", "Support", "Recall", "Class Brier", "Class ECE"].map((h) => <th key={h} className="border-b border-slate-200 px-2 py-1.5 font-semibold uppercase">{h}</th>)}</tr></thead>
              <tbody>{order.map((c) => (
                <tr key={c}><td className="border-b border-slate-100 px-2 py-1.5 font-semibold text-slate-800">{c}</td>
                  <td className="border-b border-slate-100 px-2 py-1.5 tabular-nums">{fmt.int(m.perClass[c]?.support)}</td>
                  <td className="border-b border-slate-100 px-2 py-1.5 tabular-nums">{fmt.n(m.perClass[c]?.recall, 3)}</td>
                  <td className="border-b border-slate-100 px-2 py-1.5 tabular-nums">{fmt.n(m.classwiseBrier[c], 4)}</td>
                  <td className="border-b border-slate-100 px-2 py-1.5 tabular-nums">{fmt.n(m.classwiseEce[c], 4)}</td></tr>))}</tbody>
            </table>
          </div>
        </Card>
        <Card title="Confusion (row-normalized)" description="Realized (rows) vs predicted (columns). BIP_OUT absorbs most mass under severe imbalance." icon={BarChart3}>
          <ConfusionHeatmap matrix={m.confusionMatrix} labels={order} />
        </Card>
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Severe-miss concentration" description="Classes ranked by Brier contribution — where the model's probability error concentrates." icon={BarChart3}>
          <BarChart horizontal categories={severe.map((s) => s.c)} values={severe.map((s) => s.brier)} height={220} color="#e11d48" valueFmt={(v) => fmt.n(v, 4)} />
        </Card>
        <Card title="Feature influence" description={r.family === "logistic" ? "Mean |standardized coefficient| across classes." : "Model feature importance."} icon={BarChart3}>
          {r.importance.length ? <BarChart horizontal categories={r.importance.slice(0, 10).map((i) => i.feature)} values={r.importance.slice(0, 10).map((i) => i.importance)} height={240} color="#7c3aed" valueFmt={(v) => fmt.n(v, 3)} />
            : <p className="text-sm text-slate-500">No importance available for this family.</p>}
        </Card>
      </div>
    </div>
  );
}

// ============================================================ 12 Calibration
export function CalibrationStep() {
  const r = useCockpitStore((s) => s.lastResult);
  if (!r) return <NeedRun label="Run a challenger to inspect calibration reliability." />;
  const [season, setSeason] = useState<"val2024" | "frozen2025">("val2024");
  const m = r.metrics[season];
  const topRel = (m.topLabelReliability || []).map((b: any) => ({ meanPredicted: b.meanConfidence, observed: b.accuracy, count: b.count }));
  const order: string[] = m.classOrder;
  const [cls, setCls] = useState<string>("STRIKEOUT");
  const clsRel = (m.classwiseReliability?.[cls] || []).map((b: any) => ({ meanPredicted: b.meanProbability, observed: b.realizedFrequency, count: b.count }));
  return (
    <div className="space-y-4">
      <Card title="Calibration reliability" description="Raw model probabilities. Governed calibration (temperature scaling) is applied only when it does not worsen the frozen season — the champion retains temperature scaling." icon={Gauge}
        action={<Segmented value={season} onChange={setSeason as any} options={[{ value: "val2024", label: "2024" }, { value: "frozen2025", label: "2025 frozen" }]} />}>
        <div className="grid gap-3 sm:grid-cols-3">
          <MetricCard label="Top-label ECE" value={fmt.n(m.topLabelEce)} detail="expected calibration error" />
          <MetricCard label="Brier" value={fmt.n(m.brierScore)} />
          <MetricCard label="Balanced acc." value={fmt.n(m.balancedAccuracy, 3)} />
        </div>
      </Card>
      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Top-label reliability" description="Confidence vs empirical accuracy. On the diagonal = well calibrated." icon={Gauge}>
          <CalibrationChart reliability={topRel} />
        </Card>
        <Card title="Class reliability" description="Per-class predicted probability vs realized frequency." icon={Gauge}
          action={<Segmented value={cls} onChange={setCls as any} options={order.slice(0, 5).map((c) => ({ value: c, label: c.slice(0, 3) }))} />}>
          <CalibrationChart reliability={clsRel} />
        </Card>
      </div>
      <Card title="Calibration policy" icon={Gauge}>
        <ul className="space-y-1.5 text-xs text-slate-600">
          <li className="flex gap-2"><span className="mt-1 h-1.5 w-1.5 rounded-full bg-cyan-500" />Methods: NONE / TEMPERATURE (governed). Temperature scaling is fit on validation, never on frozen 2025.</li>
          <li className="flex gap-2"><span className="mt-1 h-1.5 w-1.5 rounded-full bg-cyan-500" />A calibrator is rejected automatically if it worsens the frozen-season Brier (non-worsening policy).</li>
        </ul>
      </Card>
    </div>
  );
}

// ============================================================ 13 Simulation Impact
export function SimulationStep() {
  const store = useCockpitStore();
  const r = store.lastResult;
  const [mode, setMode] = useState<"quick" | "full">("quick");
  const [season, setSeason] = useState(2024);
  const post = usePost<any>();
  const elig = usePost<Eligibility>();
  const cfg = r?.config || store.config;
  useEffect(() => { elig.run("/cockpit/eligibility", cfg).catch(() => {}); // eslint-disable-next-line
  }, [cfg.family, (cfg.features || []).length, (cfg.engineeredFeatures || []).length]);
  const eligible = elig.data?.eligible;
  const budgets = { quick: { nGames: 40, nSims: 150 }, full: { nGames: 25, nSims: 100 } };
  const run = async () => {
    const b = budgets[mode];
    const res = await post.run("/cockpit/simulate", { config: cfg, season, nGames: b.nGames, nSims: b.nSims, mode });
    store.setLastSim(res);
  };
  const sim: any = store.lastSim;
  const full = sim?.mode === "FULL_LINEUP_ROTATION";
  const VERDICT_TONE: Record<string, any> = { GAME_LEVEL_IMPROVEMENT: "emerald", PA_ONLY_IMPROVEMENT: "amber", NO_MATERIAL_CHANGE: "slate", GAME_LEVEL_DEGRADATION: "rose" };
  const rows: [string, string, number][] = full
    ? [["PA log loss", "paLogLoss", 4], ["Total-run CRPS", "totalRunCrps", 3], ["Total-run bias", "totalRunBias", 3], ["Run-diff MAE", "runDiffMae", 3], ["Home-win Brier", "homeWinBrier", 4], ["Home-win log loss", "homeWinLogLoss", 4], ["50% coverage", "coverage50", 3], ["90% coverage", "coverage90", 3]]
    : [["PA log loss", "paLogLoss", 4], ["PA Brier", "paBrier", 4], ["Total-run CRPS", "totalRunCrps", 3], ["Total-run bias", "totalRunBias", 3], ["Run-diff MAE", "runDiffMae", 3], ["Home-win Brier", "homeWinBrier", 4], ["Home-win log loss", "homeWinLogLoss", 4], ["90% coverage", "intervalCoverage90", 3]];
  return (
    <div className="space-y-4">
      <Card title="Whole-game simulation impact" description="Does the challenger's PA-level change actually improve the whole game? FULL runs the real Phase 5 lineup-rotation kernel via the generic PA provider; QUICK is a bounded marginal-state probe." icon={Orbit}
        action={<Pill label="SIGNATURE FEATURE" tone="cyan" />}>
        <div className="mb-3 flex flex-wrap items-center gap-2">
          <Pill label={eligible ? "FULL SIMULATOR ELIGIBLE" : (elig.data?.status || "…").replace(/_/g, " ")} tone={eligible ? "emerald" : "amber"} />
          {elig.data && !eligible ? <span className="text-xs text-slate-500">{elig.data.reasons[0]}</span> : null}
        </div>
        <div className="flex flex-wrap items-end gap-4">
          <div><div className="mb-1 text-xs font-semibold uppercase text-slate-500">Mode</div>
            <Segmented value={mode} onChange={setMode as any} options={[{ value: "quick", label: "Quick · marginal-state" }, { value: "full", label: "Full · lineup-rotation", disabled: !eligible }]} /></div>
          <div><div className="mb-1 text-xs font-semibold uppercase text-slate-500">Season</div>
            <Segmented value={String(season)} onChange={(v) => setSeason(Number(v))} options={[{ value: "2024", label: "2024" }, { value: "2025", label: "2025 frozen" }]} /></div>
          <Button onClick={run} disabled={post.status === "loading" || (mode === "full" && !eligible)} tone="dark">{post.status === "loading" ? "Simulating…" : "▶ Test in game simulator"}</Button>
          {!r && <span className="text-xs text-amber-600">No trained challenger — simulating the active configuration.</span>}
        </div>
        {post.status === "loading" && <div className="mt-3 flex items-center gap-2 text-sm text-slate-500"><span className="h-4 w-4 animate-spin rounded-full border-2 border-slate-300 border-t-cyan-600" />{mode === "full" ? "Running full lineup-rotation Monte Carlo through the Phase 5 kernel…" : "Running bounded marginal-state Monte Carlo…"}</div>}
        {post.status === "error" && <p className="mt-2 text-sm text-rose-600">{post.error}</p>}
      </Card>
      {sim && (
        <>
          <div className={`rounded-2xl border p-4 ${sim.verdict === "GAME_LEVEL_IMPROVEMENT" ? "border-emerald-300 bg-emerald-50" : sim.verdict === "GAME_LEVEL_DEGRADATION" ? "border-rose-300 bg-rose-50" : "border-slate-200 bg-slate-50"}`}>
            <div className="flex flex-wrap items-center gap-3"><Pill label={sim.verdict.replace(/_/g, " ")} tone={VERDICT_TONE[sim.verdict]} />
              <Pill label={full ? "FULL LINEUP-ROTATION" : "QUICK MARGINAL"} tone={full ? "cyan" : "slate"} />
              <span className="text-sm text-slate-600">{sim.games} games · {sim.simsPerGame} sims/game · {sim.kernel.replace(/_/g, " ")}</span></div>
          </div>
          <Card title="Champion vs challenger — whole-game metrics" description="Identical games, participant orderings, transition kernel, sim count, and RNG lineage. Only the PA provider differs." icon={Orbit}>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[720px] text-left text-sm">
                <thead><tr className="text-slate-500">{["Metric", "Champion", "Challenger", "Δ"].map((h) => <th key={h} className="border-b border-slate-200 px-3 py-2 text-xs font-semibold uppercase">{h}</th>)}</tr></thead>
                <tbody>
                  {rows.map(([label, key, d]) => {
                    const c = sim.champion[key] as number, h = sim.challenger[key] as number;
                    const isCov = key.startsWith("coverage") || key === "intervalCoverage90";
                    const target = key === "coverage50" ? 0.5 : key === "coverage80" ? 0.8 : key === "coverage95" ? 0.95 : 0.9;
                    const better = isCov ? Math.abs(h - target) < Math.abs(c - target) : h < c;
                    return <tr key={label}><td className="border-b border-slate-100 px-3 py-2 font-medium text-slate-800">{label}</td>
                      <td className="border-b border-slate-100 px-3 py-2 tabular-nums text-slate-500">{fmt.n(c, d)}</td>
                      <td className={`border-b border-slate-100 px-3 py-2 tabular-nums font-semibold ${better ? "text-emerald-600" : "text-slate-900"}`}>{fmt.n(h, d)}</td>
                      <td className="border-b border-slate-100 px-3 py-2 tabular-nums text-slate-500">{fmt.signed(h - c, d)}</td></tr>;
                  })}
                </tbody>
              </table>
            </div>
          </Card>
          <Card title="Scope & authority" icon={Orbit}>
            <ul className="space-y-1.5 text-xs text-slate-600">{sim.notes.map((n: string, i: number) => <li key={i} className="flex gap-2"><span className="mt-1 h-1.5 w-1.5 rounded-full bg-cyan-500" />{n}</li>)}
              {sim.provider ? <li className="flex gap-2"><span className="mt-1 h-1.5 w-1.5 rounded-full bg-slate-400" />Provider {sim.provider}</li> : null}</ul>
          </Card>
        </>
      )}
    </div>
  );
}

// ============================================================ 14 Champion / Challenger
export function ChampionChallengerStep() {
  const data = useEndpoint<{ experiments: ExperimentIndexRow[]; champion: Champion }>("/cockpit/experiments");
  const r = useCockpitStore((s) => s.lastResult);
  const sim = useCockpitStore((s) => s.lastSim);
  return (
    <LoadGate state={data}>
      {data.data && (
        <div className="space-y-4">
          <Card title="Champion of record" description="The registered D3 C4 is never overwritten automatically. Challengers remain research status." icon={Trophy}
            action={<Pill label="RESEARCH CHAMPION" tone="emerald" />}>
            <div className="grid gap-3 sm:grid-cols-4">
              <MetricCard label="Family" value="Logistic" detail={`C=${data.data.champion.C}`} />
              <MetricCard label="2024 log loss" value={fmt.n(data.data.champion.val2024.logLoss)} />
              <MetricCard label="2025 log loss" value={fmt.n(data.data.champion.frozen2025.logLoss)} />
              <MetricCard label="Features" value={String(data.data.champion.featureCount)} />
            </div>
          </Card>
          <Card title="Challenger ledger" description="All cockpit experiments, ranked by 2024 validation log loss." icon={FlaskConical}>
            {data.data.experiments.length ? (
              <div className="overflow-x-auto"><table className="w-full min-w-[640px] text-left text-sm">
                <thead><tr className="text-slate-500">{["Experiment", "Family", "Features", "2024 LL", "2025 LL", "Beats champ", "Created"].map((h) => <th key={h} className="border-b border-slate-200 px-3 py-2 text-xs font-semibold uppercase">{h}</th>)}</tr></thead>
                <tbody>{data.data.experiments.map((e) => (
                  <tr key={e.experimentId}><td className="border-b border-slate-100 px-3 py-2 font-mono text-xs text-slate-700">{e.experimentId.replace("cockpit-exp-", "")}</td>
                    <td className="border-b border-slate-100 px-3 py-2">{e.family}</td>
                    <td className="border-b border-slate-100 px-3 py-2 tabular-nums">{e.featureCount}</td>
                    <td className="border-b border-slate-100 px-3 py-2 tabular-nums font-semibold">{fmt.n(e.val2024LogLoss)}</td>
                    <td className="border-b border-slate-100 px-3 py-2 tabular-nums text-slate-500">{fmt.n(e.frozen2025LogLoss)}</td>
                    <td className="border-b border-slate-100 px-3 py-2">{e.beatsChampion2024 ? <Pill label="YES" tone="emerald" /> : <Pill label="no" tone="slate" />}</td>
                    <td className="border-b border-slate-100 px-3 py-2 text-xs text-slate-500">{e.createdAt}</td></tr>))}</tbody>
              </table></div>
            ) : <p className="text-sm text-slate-500">No experiments yet. Run a challenger in Model Laboratory.</p>}
          </Card>
          <Card title="Promotion gates" description="Promotion to research champion requires every gate. This is a research-status action; the registered D3 is not modified." icon={Trophy}
            action={<Button size="sm" tone="ghost" disabled>Promote to research champion</Button>}>
            {r ? <div className="grid gap-2 sm:grid-cols-2">
              {[
                ["Temporal integrity (frozen protected)", r.leakageGuards.frozenSeasonExcludedFromFitting],
                ["Fold-local preprocessing", r.leakageGuards.foldLocalPreprocessing],
                ["Target never a predictor", r.leakageGuards.targetColumnNeverAFeature],
                ["Improves 2024 validation", r.comparison.beatsChampion2024],
                ["Improves 2025 frozen", r.comparison.beatsChampionFrozen],
                ["Simulator impact reviewed", !!sim],
                ["Simulator non-degradation", sim ? sim.verdict !== "GAME_LEVEL_DEGRADATION" : false],
              ].map(([label, ok]) => (
                <div key={label as string} className="flex items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs">
                  {ok ? <Check size={15} className="text-emerald-600" /> : <X size={15} className="text-slate-300" />}<span className={ok ? "font-medium text-slate-800" : "text-slate-400"}>{label}</span>
                </div>
              ))}
            </div> : <p className="text-sm text-slate-500">Run a challenger and a simulation to evaluate promotion gates.</p>}
          </Card>
        </div>
      )}
    </LoadGate>
  );
}

// ============================================================ 15 Registry & Evidence
export function RegistryStep() {
  const r = useCockpitStore((s) => s.lastResult);
  if (!r) return <NeedRun label="Run a challenger to generate a registry record and model card." />;
  return (
    <div className="space-y-4">
      <Card title="Experiment record" description="Content-addressed cockpit experiment evidence." icon={Boxes}
        action={<Pill label="RESEARCH EVIDENCE" tone="cyan" />}>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {[["Experiment ID", r.experimentId], ["Family", r.familyLabel], ["Feature count", String(r.featureCount)], ["Design columns", String(r.expandedFeatureCount)], ["Fit seconds", fmt.n(r.fitSeconds, 2)], ["Created", r.createdAt]].map(([k, v]) => (
            <div key={k} className="rounded-lg border border-slate-200 bg-slate-50 p-3"><div className="text-xs font-semibold uppercase text-slate-500">{k}</div><div className="mt-1 break-words text-sm font-semibold text-slate-900">{v}</div></div>
          ))}
        </div>
      </Card>
      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Model card" description="Objective → data → preprocessing → algorithm → metrics → limitations." icon={Boxes}>
          <dl className="space-y-2 text-sm">
            <Row k="Objective" v="Plate Appearance Outcome (8-class)" />
            <Row k="Population" v="2023 dev · 2024 val · 2025 frozen" />
            <Row k="Preprocessing" v={`outliers: ${r.config.outlierPolicy.globalMethod} · missing: ${r.config.missingPolicy.globalMethod}${r.config.missingPolicy.addIndicator ? " +indicator" : ""}`} />
            <Row k="Algorithm" v={`${r.familyLabel} · ${JSON.stringify(r.config.hyperparameters)}`} />
            <Row k="2024 / 2025 log loss" v={`${fmt.n(r.headline.val2024.logLoss)} / ${fmt.n(r.headline.frozen2025.logLoss)}`} />
            <Row k="vs champion (2024)" v={`${fmt.signed(r.comparison.val2024.logLoss)} log loss`} />
            <Row k="Status" v={r.comparison.beatsChampion2024 ? "CHALLENGER (beats 2024)" : "REJECTED_ON_VALIDATION"} />
          </dl>
        </Card>
        <Card title="Lineage & reproducibility" description="Logical authorities and leakage guards." icon={Boxes}>
          <div className="space-y-2 text-xs">
            <Row k="Feature view" v="MLB_PA_FEATURE_VIEW_V1" />
            <Row k="Evaluation authority" v="server.sports_modeling.metrics" />
            <Row k="Champion baseline" v={`D3 C4 reproduced in-pipeline (C=${r.champion.C})`} />
            {Object.entries(r.leakageGuards).map(([k, v]) => (
              <div key={k} className="flex items-center justify-between gap-2 rounded-lg border border-emerald-200 bg-emerald-50/50 px-3 py-1.5">
                <span className="text-slate-700">{k}</span><Pill label={String(v)} tone="emerald" />
              </div>
            ))}
          </div>
        </Card>
      </div>
    </div>
  );
}
function Row({ k, v }: { k: string; v: string }) {
  return <div className="flex flex-col gap-0.5 border-b border-slate-100 pb-1.5"><dt className="text-xs font-semibold uppercase text-slate-500">{k}</dt><dd className="text-sm text-slate-800">{v}</dd></div>;
}

function NeedRun({ label }: { label: string }) {
  return (
    <div className="rounded-2xl border border-dashed border-slate-300 bg-slate-50 p-10 text-center">
      <Rocket size={28} className="mx-auto text-slate-400" />
      <p className="mx-auto mt-3 max-w-md text-sm text-slate-600">{label}</p>
    </div>
  );
}
