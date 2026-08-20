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
  ConfusionHeatmap, CalibrationChart, ModelScatter, fmt,
} from "./cockpitUi";
import { useActiveSportsDataset } from "../sportsEvidenceApi";
import { SevereMissForensicsSection } from "../Phase4Surfaces";

function useConfig() {
  return useCockpitStore((s) => s.config);
}

// ============================================================ 09 Model Laboratory (multi-model)
type FamilyMeta = { group: string; klass: string; desc: string; strengths: string[]; tradeoff: string; compute: "Low" | "Medium" | "High"; interpret: "Low" | "Medium" | "High" };
const MODEL_META: Record<string, FamilyMeta> = {
  logistic: { group: "Linear / interpretable", klass: "Linear model", desc: "Multinomial logistic — the governed champion family; additive log-odds, well-calibrated.", strengths: ["interpretable", "calibrated", "fast"], tradeoff: "linear boundary only", compute: "Low", interpret: "High" },
  svm: { group: "Linear / interpretable", klass: "Linear (calibrated)", desc: "Linear SVM with sigmoid calibration on the development fold.", strengths: ["margin-based", "linear"], tradeoff: "slower fit; needs calibration", compute: "Medium", interpret: "Medium" },
  random_forest: { group: "Tree ensembles", klass: "Bagged trees", desc: "Nonlinear bagged-tree ensemble; robust benchmark for mixed interactions.", strengths: ["nonlinear", "interactions", "robust"], tradeoff: "less interpretable; calibration may need attention", compute: "Medium", interpret: "Medium" },
  extra_trees: { group: "Tree ensembles", klass: "Randomized trees", desc: "Extremely randomized trees; extra variance reduction.", strengths: ["nonlinear", "fast splits"], tradeoff: "less interpretable", compute: "Medium", interpret: "Medium" },
  hist_gradient_boosting: { group: "Tree ensembles", klass: "Boosted trees", desc: "Histogram-binned gradient boosting; strong tabular baseline.", strengths: ["nonlinear", "strong accuracy"], tradeoff: "sequential; tuning matters", compute: "Medium", interpret: "Low" },
  xgboost: { group: "Tree ensembles", klass: "Boosted trees", desc: "Regularized gradient-boosted trees (XGBoost).", strengths: ["nonlinear", "regularized"], tradeoff: "optional dependency; tuning matters", compute: "High", interpret: "Low" },
  lightgbm: { group: "Tree ensembles", klass: "Boosted trees", desc: "Leaf-wise gradient boosting (LightGBM).", strengths: ["fast", "nonlinear"], tradeoff: "optional dependency", compute: "Medium", interpret: "Low" },
  mlp: { group: "Neural", klass: "Feed-forward NN", desc: "Multi-layer perceptron on standardized features.", strengths: ["nonlinear", "flexible"], tradeoff: "needs scaling; less interpretable; longer fit", compute: "High", interpret: "Low" },
};
const GROUP_ORDER = ["Linear / interpretable", "Tree ensembles", "Neural"];
const chip = (v: string) => (v === "High" ? "rose" : v === "Medium" ? "amber" : "emerald") as any;

export function ModelLabStep() {
  const fams = useEndpoint<{ families: ModelFamily[] }>("/cockpit/model-families");
  const obj = useEndpoint<any>("/cockpit/objective");
  const store = useCockpitStore();
  const { config, labSelected, labSuite } = store;
  const [running, setRunning] = useState(false);
  const [detail, setDetail] = useState<string | null>(null);

  const available = (fams.data?.families || []).filter((f) => f.available).map((f) => f.id);
  const selectRecommended = () => store.setLabSelected(available);
  const clear = () => store.setLabSelected([]);
  const championVal = obj.data?.champion?.reference?.val2024?.logLoss as number | undefined;

  const runSuite = async () => {
    const sel = labSelected.filter((f) => available.includes(f));
    if (!sel.length || !config.features.length) return;
    setRunning(true);
    store.clearLabSuite();
    for (const f of sel) store.upsertLabCandidate(f, { key: f, family: f, label: familyLabel(fams.data!, f), status: "queued", source: "suite" });
    for (const f of sel) {
      store.upsertLabCandidate(f, { status: "training" });
      try {
        const r = await cockpitPost<ExperimentResult>("/cockpit/experiment/run", { ...config, family: f, hyperparameters: {} });
        const v = r.metrics.val2024 as any;
        store.upsertLabCandidate(f, {
          status: "complete", experimentId: r.experimentId, fitSeconds: r.fitSeconds,
          featureCount: r.featureCount, expandedFeatureCount: r.expandedFeatureCount,
          val: { logLoss: v.logLoss, brierScore: v.brierScore, topLabelEce: v.topLabelEce, top1Accuracy: v.top1Accuracy, macroF1: v.macroF1 },
          frozen: { logLoss: r.metrics.frozen2025.logLoss, brierScore: (r.metrics.frozen2025 as any).brierScore },
          championVal: r.champion.val2024.logLoss, importance: r.importance, config: r.config,
        });
      } catch (e: any) {
        store.upsertLabCandidate(f, { status: "failed", error: String(e?.message || e) });
      }
    }
    setRunning(false);
  };

  const candidates = Object.values(labSuite);
  const completed = candidates.filter((c) => c.status === "complete" && c.val);
  const ranked = [...completed].sort((a, b) => a.val!.logLoss - b.val!.logLoss);

  return (
    <LoadGate state={fams}>
      {fams.data && (
        <div className="space-y-4">
          <ChampionReferenceCard championVal={championVal} obj={obj.data} />

          {/* Candidate model suite gallery (multi-select) */}
          <Card title="Candidate model suite" icon={FlaskConical}
            description="Select multiple families and train them together as isolated challenger experiments. Availability is honest — uninstalled libraries are marked, not faked."
            action={<div className="flex flex-wrap gap-2">
              <Button size="sm" tone="ghost" onClick={selectRecommended}>Select recommended</Button>
              <Button size="sm" tone="ghost" onClick={clear}>Clear</Button>
            </div>}>
            {GROUP_ORDER.map((g) => {
              const inGroup = fams.data!.families.filter((f) => (MODEL_META[f.id]?.group || "Other") === g);
              if (!inGroup.length) return null;
              return (
                <div key={g} className="mb-3">
                  <div className="mb-1.5 text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-400">{g}</div>
                  <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
                    {inGroup.map((f) => {
                      const m = MODEL_META[f.id]; const on = labSelected.includes(f.id); const done = labSuite[f.id]?.status === "complete";
                      return (
                        <button key={f.id} disabled={!f.available} onClick={() => store.toggleLabFamily(f.id)}
                          className={`rounded-xl border p-3 text-left transition-colors ${on ? "border-cyan-600 bg-cyan-50 ring-1 ring-cyan-200" : f.available ? "border-slate-200 bg-white hover:border-slate-300" : "border-slate-200 bg-slate-50 opacity-60"}`}>
                          <div className="flex items-start justify-between gap-2">
                            <div className="min-w-0"><div className="text-sm font-semibold text-slate-900">{f.label}</div><div className="text-[10px] uppercase text-slate-400">{m?.klass}</div></div>
                            <span className={`mt-0.5 inline-flex h-4 w-4 shrink-0 items-center justify-center rounded border ${on ? "border-cyan-600 bg-cyan-600 text-white" : "border-slate-300"}`}>{on ? <Check size={11} /> : null}</span>
                          </div>
                          <div className="mt-1 text-[11px] leading-4 text-slate-500">{m?.desc}</div>
                          <div className="mt-1.5 flex flex-wrap gap-1">
                            {f.available ? <Pill label={done ? "Evaluated" : "Available"} tone={done ? "cyan" : "emerald"} /> : <Pill label="dependency unavailable" tone="slate" />}
                            {m && <Pill label={`compute ${m.compute}`} tone={chip(m.compute)} />}
                            {m && <Pill label={`interpret ${m.interpret}`} tone={m.interpret === "High" ? "emerald" : m.interpret === "Medium" ? "amber" : "rose"} />}
                          </div>
                        </button>
                      );
                    })}
                  </div>
                </div>
              );
            })}
          </Card>

          {/* Launch panel — exactly what will happen */}
          <LaunchPanel obj={obj.data} config={config} savedSteps={store.savedSteps} selectedCount={labSelected.length}
            onRun={runSuite} running={running} disabled={!labSelected.length || !config.features.length} />

          {/* Live candidate status + leaderboard */}
          {candidates.length > 0 && (
            <Leaderboard candidates={candidates} ranked={ranked} championVal={championVal}
              onDetail={setDetail} tuneSelected={store.labTuneSelected} onToggleTune={(k) => {
                const t = store.labTuneSelected; store.setLabTuneSelected(t.includes(k) ? t.filter((x) => x !== k) : [...t, k]);
              }} />
          )}
          {ranked.length >= 2 && <LeaderboardVisuals ranked={ranked} championVal={championVal} />}

          <AutopilotPanel />
          {detail && <ModelDetailDrawer candidate={labSuite[detail]} config={config} onClose={() => setDetail(null)} />}
        </div>
      )}
    </LoadGate>
  );
}

function familyLabel(fams: { families: ModelFamily[] }, id: string): string {
  return fams.families.find((f) => f.id === id)?.label || id;
}

function ChampionReferenceCard({ championVal, obj }: { championVal?: number; obj: any }) {
  return (
    <div className="rounded-2xl border border-slate-800 bg-slate-950 p-4 text-white">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <div className="text-[10px] font-semibold uppercase tracking-[0.16em] text-cyan-300">Current registered champion</div>
          <div className="mt-0.5 text-lg font-semibold">{obj?.champion?.modelId || "D3 · candidate C4"} <span className="text-sm font-normal text-slate-400">· {obj?.champion?.family || "Multinomial Logistic Regression"}</span></div>
        </div>
        <div className="flex gap-5 text-right">
          <div><div className="text-[10px] uppercase text-slate-400">2024 validation log loss</div><div className="text-xl font-semibold tabular-nums">{championVal != null ? fmt.n(championVal) : "…"}</div></div>
          <div><div className="text-[10px] uppercase text-slate-400">2025 frozen</div><div className="text-sm font-semibold text-rose-300">protected reference only</div></div>
          <div><div className="text-[10px] uppercase text-slate-400">Status</div><div className="text-sm font-semibold text-emerald-300">REGISTERED</div></div>
        </div>
      </div>
      <p className="mt-2 text-[11px] text-slate-400">New candidates never displace the champion automatically — a lower validation log loss is not promotion. Promotion happens later through the governed champion workflow.</p>
    </div>
  );
}

function LaunchPanel({ obj, config, savedSteps, selectedCount, onRun, running, disabled }:
  { obj: any; config: any; savedSteps: Record<string, boolean>; selectedCount: number; onRun: () => void; running: boolean; disabled: boolean }) {
  const outlierUnsaved = !savedSteps.outliers; const missingUnsaved = !savedSteps.missing;
  return (
    <Card title="Model run plan" icon={SlidersHorizontal}
      description="Exactly what a run will do. Frozen 2025 is never used for selection.">
      <div className="grid gap-2 text-xs sm:grid-cols-3 lg:grid-cols-4">
        <PlanItem label="Target" value={obj?.targetColumn || "outcome"} sub={`${obj?.classOrder?.length || 8}-class multiclass`} />
        <PlanItem label="Development" value="2023" sub={`${fmt.int(obj?.totalRows ? 184104 : 184104)} PAs`} />
        <PlanItem label="Validation" value="2024" sub="182,449 PAs" />
        <PlanItem label="Frozen final" value="2025" sub="protected" tone="rose" />
        <PlanItem label="Predictors" value={String(config.features.length)} sub={`${(config.engineeredFeatures || []).length} engineered`} />
        <PlanItem label="Outlier policy" value={config.outlierPolicy.globalMethod} sub={outlierUnsaved ? "UNSAVED PREVIEW" : "saved"} tone={outlierUnsaved ? "amber" : undefined} />
        <PlanItem label="Missing policy" value={config.missingPolicy.globalMethod} sub={missingUnsaved ? "UNSAVED PREVIEW" : "saved"} tone={missingUnsaved ? "amber" : undefined} />
        <PlanItem label="Model families" value={String(selectedCount)} sub="selected" />
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-3">
        <Button onClick={onRun} disabled={disabled || running}>{running ? "Training candidate suite…" : `▶ Run ${selectedCount || 0} candidate model${selectedCount === 1 ? "" : "s"}`}</Button>
        <Pill label="Frozen 2025 used for selection: NO" tone="rose" />
        {running && <span className="flex items-center gap-2 text-sm text-slate-500"><span className="h-4 w-4 animate-spin rounded-full border-2 border-slate-300 border-t-cyan-600" />Fitting each on 2023, evaluating 2024 & 2025…</span>}
      </div>
    </Card>
  );
}

function PlanItem({ label, value, sub, tone }: { label: string; value: string; sub?: string; tone?: "rose" | "amber" }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white px-3 py-2">
      <div className="text-[10px] font-semibold uppercase text-slate-400">{label}</div>
      <div className="text-sm font-semibold text-slate-900">{value}</div>
      {sub ? <div className={`text-[10px] ${tone === "rose" ? "text-rose-600" : tone === "amber" ? "font-semibold text-amber-700" : "text-slate-500"}`}>{sub}</div> : null}
    </div>
  );
}

const STATUS_TONE: Record<string, any> = { queued: "slate", training: "amber", complete: "emerald", failed: "rose" };
function Leaderboard({ candidates, ranked, championVal, onDetail, tuneSelected, onToggleTune }:
  { candidates: any[]; ranked: any[]; championVal?: number; onDetail: (k: string) => void; tuneSelected: string[]; onToggleTune: (k: string) => void }) {
  const pending = candidates.filter((c) => c.status !== "complete");
  return (
    <Card title="Model leaderboard" icon={Trophy}
      description="Ranked by 2024 validation log loss (the champion criterion). The registered champion is shown for reference and is not displaced automatically."
      action={tuneSelected.length ? <Pill label={`${tuneSelected.length} sent to tuning`} tone="violet" /> : undefined}>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[860px] text-left text-xs">
          <thead><tr className="text-slate-500">{["#", "Model", "Status", "Val log loss", "Δ vs champ", "Brier", "ECE", "Top-1 acc", "Macro-F1", "Train", "Features", "Tune", ""].map((h) => <th key={h} className="border-b border-slate-200 px-2 py-1.5 font-semibold uppercase">{h}</th>)}</tr></thead>
          <tbody>
            <tr className="bg-slate-50">
              <td className="border-b border-slate-100 px-2 py-1.5 text-slate-400">★</td>
              <td className="border-b border-slate-100 px-2 py-1.5 font-semibold text-slate-700">Champion D3 · C4</td>
              <td className="border-b border-slate-100 px-2 py-1.5"><Pill label="registered" tone="cyan" /></td>
              <td className="border-b border-slate-100 px-2 py-1.5 tabular-nums font-semibold">{championVal != null ? fmt.n(championVal) : "—"}</td>
              <td className="border-b border-slate-100 px-2 py-1.5 text-slate-400" colSpan={9}>reference line — not a candidate</td>
            </tr>
            {ranked.map((c, i) => {
              const delta = championVal != null && c.val ? c.val.logLoss - championVal : null;
              return (
                <tr key={c.key} className={i === 0 ? "bg-emerald-50/70" : "hover:bg-cyan-50/40"}>
                  <td className="border-b border-slate-100 px-2 py-1.5 font-semibold">{i + 1}{i === 0 ? " 🏅" : ""}</td>
                  <td className="border-b border-slate-100 px-2 py-1.5"><button className="font-semibold text-slate-800 hover:text-cyan-700 hover:underline" onClick={() => onDetail(c.key)}>{c.label}</button>{c.source === "autopilot" ? <Pill label="autopilot" tone="violet" /> : null}</td>
                  <td className="border-b border-slate-100 px-2 py-1.5"><Pill label={c.status} tone={STATUS_TONE[c.status]} /></td>
                  <td className="border-b border-slate-100 px-2 py-1.5 tabular-nums font-semibold text-slate-900">{c.val ? fmt.n(c.val.logLoss) : "—"}</td>
                  <td className={`border-b border-slate-100 px-2 py-1.5 tabular-nums ${delta != null ? (delta < 0 ? "text-emerald-600" : "text-rose-600") : "text-slate-400"}`}>{delta != null ? fmt.signed(delta, 4) : "—"}</td>
                  <td className="border-b border-slate-100 px-2 py-1.5 tabular-nums">{c.val ? fmt.n(c.val.brierScore) : "—"}</td>
                  <td className="border-b border-slate-100 px-2 py-1.5 tabular-nums">{c.val ? fmt.n(c.val.topLabelEce) : "—"}</td>
                  <td className="border-b border-slate-100 px-2 py-1.5 tabular-nums">{c.val?.top1Accuracy != null ? fmt.pct(c.val.top1Accuracy) : "—"}</td>
                  <td className="border-b border-slate-100 px-2 py-1.5 tabular-nums">{c.val?.macroF1 != null ? fmt.n(c.val.macroF1, 3) : "—"}</td>
                  <td className="border-b border-slate-100 px-2 py-1.5 tabular-nums text-slate-500">{c.fitSeconds != null ? `${fmt.n(c.fitSeconds, 1)}s` : "—"}</td>
                  <td className="border-b border-slate-100 px-2 py-1.5 tabular-nums text-slate-500">{c.expandedFeatureCount ?? c.featureCount ?? "—"}</td>
                  <td className="border-b border-slate-100 px-2 py-1.5">{c.status === "complete" && <button onClick={() => onToggleTune(c.key)} className={`inline-flex h-4 w-4 items-center justify-center rounded border ${tuneSelected.includes(c.key) ? "border-violet-600 bg-violet-600 text-white" : "border-slate-300"}`}>{tuneSelected.includes(c.key) ? <Check size={10} /> : null}</button>}</td>
                  <td className="border-b border-slate-100 px-2 py-1.5">{c.error ? <span className="text-[10px] text-rose-500" title={c.error}>error</span> : null}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {pending.length > 0 && <p className="mt-2 text-xs text-slate-500">{pending.map((c) => `${c.label}: ${c.status}`).join(" · ")}</p>}
      {ranked.length > 0 && <p className="mt-2 text-[11px] text-slate-500">#1 best validation candidate: <b>{ranked[0].label}</b>. Check models and open Hyperparameter Tuning to carry them forward. Deltas are descriptive, not a significance claim.</p>}
    </Card>
  );
}

function LeaderboardVisuals({ ranked, championVal }: { ranked: any[]; championVal?: number }) {
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card title="Validation log loss by candidate" icon={BarChart3} description="Lower is better. Champion reference dashed.">
        <BarChart categories={ranked.map((c) => c.label)} values={ranked.map((c) => c.val.logLoss)} height={240} horizontal valueFmt={(v) => fmt.n(v)} />
        {championVal != null && <p className="mt-1 text-[11px] text-slate-500">Champion D3/C4 validation log loss: <b>{fmt.n(championVal)}</b>.</p>}
      </Card>
      <Card title="Performance vs. compute" icon={BarChart3} description="Train time (x) vs validation log loss (y). Lower-left is cheaper and better.">
        <ModelScatter points={ranked.map((c, i) => ({ name: c.label, x: c.fitSeconds ?? 0, y: c.val.logLoss, best: i === 0 }))}
          xLabel="Train time (s)" yLabel="Validation log loss" yRef={championVal != null ? { value: championVal, label: "champion" } : undefined} />
      </Card>
    </div>
  );
}

function ModelDetailDrawer({ candidate, config, onClose }: { candidate: any; config: any; onClose: () => void }) {
  if (!candidate) return null;
  const m = MODEL_META[candidate.family];
  return (
    <div className="fixed inset-0 z-40 flex justify-end bg-slate-900/30" onClick={onClose}>
      <div className="h-full w-full max-w-xl overflow-y-auto bg-white shadow-2xl" onClick={(e) => e.stopPropagation()}>
        <div className="sticky top-0 flex items-center justify-between border-b border-slate-200 bg-white px-5 py-3">
          <div><h3 className="font-semibold text-slate-950">{candidate.label}</h3><p className="text-xs text-slate-500">{m?.klass} · {candidate.source === "autopilot" ? "autopilot candidate" : "research challenger"}</p></div>
          <button onClick={onClose} className="rounded-lg p-1.5 text-slate-500 hover:bg-slate-100"><X size={18} /></button>
        </div>
        <div className="space-y-4 p-5 text-sm">
          <div className="grid grid-cols-2 gap-2 text-xs">
            <Info label="Experiment ID" value={candidate.experimentId || "—"} mono />
            <Info label="Status" value={candidate.status} />
            <Info label="Train rows" value="184,104 (2023)" />
            <Info label="Validation rows" value="182,449 (2024)" />
            <Info label="Fit scope" value="development 2023 only" />
            <Info label="Train time" value={candidate.fitSeconds != null ? `${fmt.n(candidate.fitSeconds, 1)}s` : "—"} />
            <Info label="Features" value={`${candidate.featureCount ?? config.features.length} → ${candidate.expandedFeatureCount ?? "—"} cols`} />
            <Info label="Frozen used for selection" value="NO" />
          </div>
          {candidate.val && <div className="grid grid-cols-3 gap-2">
            <MetricCard label="2024 log loss" value={fmt.n(candidate.val.logLoss)} />
            <MetricCard label="2024 Brier" value={fmt.n(candidate.val.brierScore)} />
            <MetricCard label="2024 ECE" value={fmt.n(candidate.val.topLabelEce)} />
            <MetricCard label="Top-1 acc" value={candidate.val.top1Accuracy != null ? fmt.pct(candidate.val.top1Accuracy) : "—"} />
            <MetricCard label="Macro-F1" value={candidate.val.macroF1 != null ? fmt.n(candidate.val.macroF1, 3) : "—"} />
            <MetricCard label="2025 frozen LL" value={candidate.frozen ? fmt.n(candidate.frozen.logLoss) : "—"} />
          </div>}
          {candidate.importance && candidate.importance.length > 0 && (
            <div><div className="mb-1 text-xs font-semibold uppercase text-slate-500">Feature importance (top 12)</div>
              <BarChart categories={candidate.importance.slice(0, 12).map((r: any) => r.feature)} values={candidate.importance.slice(0, 12).map((r: any) => r.importance)} height={220} horizontal valueFmt={(v) => fmt.n(v, 3)} /></div>
          )}
          <div><div className="mb-1 text-xs font-semibold uppercase text-slate-500">Preprocessing & config</div>
            <div className="rounded-lg border border-slate-200 bg-slate-50 p-2 font-mono text-[11px] text-slate-600">
              outliers: {config.outlierPolicy.globalMethod} · missing: {config.missingPolicy.globalMethod}{config.missingPolicy.addIndicator ? " +indicator" : ""}<br />family: {candidate.family}
            </div></div>
          {candidate.error && <div className="rounded-lg border border-rose-200 bg-rose-50 p-2 text-xs text-rose-700">{candidate.error}</div>}
        </div>
      </div>
    </div>
  );
}

function Info({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return <div className="rounded-lg border border-slate-200 p-2"><div className="text-[10px] font-semibold uppercase text-slate-400">{label}</div><div className={`mt-0.5 font-semibold text-slate-900 ${mono ? "font-mono text-[11px]" : ""}`}>{value}</div></div>;
}

function AutopilotPanel() {
  const store = useCockpitStore();
  const post = usePost<AutopilotResult>();
  const [budget, setBudget] = useState<"quick" | "standard" | "deep">("quick");
  const run = async () => {
    const r = await post.run("/cockpit/autopilot", { config: store.config, budget });
    store.setLastAutopilot(r);
    // Autopilot results enter the same leaderboard, tagged AUTOPILOT.
    for (const c of r.candidates) {
      if (c.status !== "COMPLETED" || !c.val2024) continue;
      const key = `ap:${c.label}`;
      store.upsertLabCandidate(key, {
        key, family: c.family, label: `${c.label}`, status: "complete", source: "autopilot",
        fitSeconds: c.runtimeSeconds, val: { logLoss: c.val2024.logLoss, brierScore: c.val2024.brierScore, topLabelEce: c.val2024.topLabelEce },
        frozen: c.frozen2025 ? { logLoss: c.frozen2025.logLoss, brierScore: c.frozen2025.brierScore } : undefined,
        championVal: r.champion.val2024.logLoss,
      });
    }
  };
  const ap = store.lastAutopilot;
  return (
    <Card title="Autopilot benchmark" icon={Rocket}
      description="Let ASP Model Studio run a bounded automated candidate search using the governed development/validation policy. Autopilot never silently promotes a model — its candidates join the leaderboard above, tagged AUTOPILOT."
      action={<Pill label="AUTOPILOT" tone="violet" />}>
      <div className="flex flex-wrap items-end gap-4">
        <div><div className="mb-1 text-xs font-semibold uppercase text-slate-500">Budget</div>
          <Segmented value={budget} onChange={setBudget as any} options={[{ value: "quick", label: "Quick" }, { value: "standard", label: "Standard" }, { value: "deep", label: "Deep" }]} /></div>
        <Button onClick={run} disabled={post.status === "loading"} tone="dark">{post.status === "loading" ? "Running Autopilot…" : "▶ Run Autopilot benchmark"}</Button>
        {post.status === "loading" && <span className="flex items-center gap-2 text-sm text-slate-500"><span className="h-4 w-4 animate-spin rounded-full border-2 border-slate-300 border-t-cyan-600" />Searching a bounded candidate set on 2023→2024…</span>}
      </div>
      {ap && <p className="mt-3 text-xs text-slate-500">Autopilot best: <b>{ap.best?.label}</b> ({ap.best?.val2024 ? fmt.n(ap.best.val2024.logLoss) : "—"}) · {ap.candidates.length} candidates added to the leaderboard. {ap.limitations.join(" ")}</p>}
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

  const tuneSelected = store.labTuneSelected;
  return (
    <div className="space-y-4">
      {tuneSelected.length > 0 && (
        <div className="rounded-xl border border-violet-200 bg-violet-50/60 px-4 py-3 text-sm text-slate-700">
          <span className="font-semibold text-violet-700">Sent from the Model Laboratory:</span> {tuneSelected.join(", ")} — these candidates were checked for tuning and carried over (selection persists across navigation).
        </div>
      )}
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
  const ds = useActiveSportsDataset();
  const phase4 = ds.status === "ready" ? ds.data.phase4 : undefined;
  const [season, setSeason] = useState<"val2024" | "frozen2025">("val2024");
  if (!r) {
    return (
      <div className="space-y-4">
        <NeedRun label="Run a challenger in Model Laboratory to populate challenger-vs-champion diagnostics." />
        <SevereMissForensicsSection forensics={phase4?.severeMissForensics} />
      </div>
    );
  }
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
      {/* Registered severe-miss / error analysis (relocated Phase 4F): where does the model fail? */}
      <SevereMissForensicsSection forensics={phase4?.severeMissForensics} />
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
