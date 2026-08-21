// Cockpit workflow steps 09–15: Model Laboratory, Hyperparameter Tuning, Evaluation,
// Calibration, Simulation Impact, Champion/Challenger, Registry.
import { useMemo, useState } from "react";
import {
  FlaskConical, SlidersHorizontal, BarChart3, Gauge, Orbit, Trophy, Boxes, Rocket, Check, X, TriangleAlert,
} from "lucide-react";
import { useEffect } from "react";
import {
  useEndpoint, usePost, useCockpitStore, cockpitPost, cockpitGet,
  type ModelFamily, type Champion, type ExperimentResult, type AutopilotResult,
  type SimResult, type ExperimentIndexRow, type Eligibility, type FullSimResult,
} from "./cockpitApi";
import Gen3AuthorityPanel from "./Gen3AuthorityPanel";

// Phase 7A.4 Gate 10 — no scientist-facing component may call a binding-free execution path. The legacy
// candidate suite, Autopilot, and Grid execution are contained behind this flag; model execution is
// server-authorized only (active binding -> run authority -> authorized execution; never scores 2025).
const LEGACY_BINDING_FREE_EXECUTION_DISABLED = true;
import {
  Card, Pill, MetricCard, Button, Segmented, NumberField, LoadGate, GroupedBars, BarChart,
  ConfusionHeatmap, CalibrationChart, ModelScatter, fmt,
} from "./cockpitUi";

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

export function ModelLabStep({ projectId = "mlb-cockpit" }: { projectId?: string } = {}) {
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

  // A2-03 — the legacy binding-free candidate suite (which posted model configs to the D3/C4
  // /cockpit/experiment/run path and returned 2025 metrics) is DISABLED in the scientist workflow.
  // Model execution now flows exclusively through the server-authorized Gen-3 run plan above
  // (active binding -> run authority -> authorized execution -> immutable result). This gallery is
  // retained for viewing prior challenger evidence only.
  const LEGACY_EXECUTION_DISABLED = true;
  const runSuite = async () => {
    if (LEGACY_EXECUTION_DISABLED) return;
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
          {/* Phase 7A.1 — server-authorized Gen-3 run plan + execution (additive; the existing champion
              reference + candidate suite below are unchanged). */}
          <Gen3AuthorityPanel projectId={projectId} />
          <div className="rounded-xl border border-amber-300 bg-amber-50 px-4 py-2.5 text-xs text-amber-900">
            <b>One execution authority.</b> Model execution is server-authorized only (run plan above). The
            legacy binding-free candidate suite below is disabled and retained for viewing prior evidence —
            it no longer posts model configs and never scores 2025.
          </div>
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
            onRun={runSuite} running={running} disabled={true} />

          {/* Live candidate status + leaderboard */}
          {candidates.length > 0 && (
            <Leaderboard candidates={candidates} ranked={ranked} championVal={championVal}
              onDetail={setDetail} tuneSelected={store.labTuneSelected} onToggleTune={(k) => {
                const t = store.labTuneSelected; store.setLabTuneSelected(t.includes(k) ? t.filter((x) => x !== k) : [...t, k]);
              }} />
          )}
          {ranked.length >= 2 && <LeaderboardVisuals ranked={ranked} championVal={championVal} />}

          <AutopilotPanel projectId={projectId} />
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

// Gate 5 — Autopilot runs through the SERVER-AUTHORIZED suite (active binding -> run authority per
// candidate -> authorized execution). No legacy binding-free call; never scores 2025.
const AUTOPILOT_PLAN: Record<string, { family: string; label: string; hyperparameters?: any }[]> = {
  quick: [{ family: "governed_hgb", label: "Governed HGB" }],
  standard: [{ family: "governed_hgb", label: "Governed HGB" }, { family: "governed_logistic", label: "Governed logistic" }],
  deep: [],
};
function AutopilotPanel({ projectId }: { projectId: string }) {
  const store = useCockpitStore();
  const [budget, setBudget] = useState<"quick" | "standard" | "deep">("quick");
  const [binding, setBinding] = useState<{ bindingId: string; generation: string } | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [best, setBest] = useState<{ runId: string; logLoss: number; count: number } | null>(null);
  const [activated, setActivated] = useState<string | null>(null);
  const [activating, setActivating] = useState(false);
  useEffect(() => {
    setBinding(null); setBest(null); setActivated(null); setError(null);
    cockpitGet<{ bindingId: string; generation: string }>(`/cockpit/gen3/binding/${encodeURIComponent(projectId)}`)
      .then(setBinding).catch(() => setBinding(null));
  }, [projectId]);
  const activate = async (runId: string) => {
    setActivating(true); setError(null);
    try { await cockpitPost("/cockpit/gen3/activate", { projectId, runId }); setActivated(runId); }
    catch (e) { setError(String(e)); } finally { setActivating(false); }
  };
  const run = async () => {
    if (!binding || budget === "deep") return;
    setRunning(true); setError(null); setBest(null);
    try {
      const out = await cockpitPost<any>("/cockpit/gen3/run-suite", { projectId, bindingId: binding.bindingId, source: "autopilot", candidates: AUTOPILOT_PLAN[budget] });
      for (const c of out.candidates) {
        store.upsertLabCandidate(`ap:${c.experimentRunId}`, {
          key: `ap:${c.experimentRunId}`, family: c.modelFamily, label: `${c.label}`, status: "complete", source: "autopilot",
          experimentId: c.experimentRunId,
          val: { logLoss: c.metrics.logLoss, brierScore: c.metrics.brierScore, topLabelEce: c.metrics.topLabelEce, top1Accuracy: c.metrics.top1Accuracy, macroF1: c.metrics.macroF1 },
        });
      }
      if (out.best) setBest({ runId: out.best, logLoss: out.bestLogLoss, count: out.candidateCount });
    } catch (e) { setError(String(e)); } finally { setRunning(false); }
  };
  return (
    <Card title="Autopilot benchmark" icon={Rocket}
      description="A bounded automated candidate search that runs entirely through the server-authorized run path (active binding → run authority → authorized execution on 2021–2023 / validated on 2024; 2025 sealed). Candidates join the leaderboard above, tagged AUTOPILOT. No champion is promoted."
      action={<Pill label="AUTOPILOT · SERVER-AUTHORIZED" tone="violet" />}>
      {!binding && <div className="mb-2 rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-800"><X size={12} className="mr-1 inline" />No active dataset binding — select one in Data & Population before running Autopilot.</div>}
      <div className="flex flex-wrap items-end gap-4">
        <div><div className="mb-1 text-xs font-semibold uppercase text-slate-500">Budget</div>
          <Segmented value={budget} onChange={setBudget as any} options={[{ value: "quick", label: "Quick" }, { value: "standard", label: "Standard" }, { value: "deep", label: "Deep" }]} /></div>
        <Button onClick={run} disabled={!binding || budget === "deep" || running} tone="dark">{running ? "Running authorized suite…" : "▶ Run Autopilot benchmark"}</Button>
      </div>
      {budget === "deep" && <p className="mt-1 text-[11px] text-amber-700">Deep is not yet bounded for the authorized path — use Quick (HGB) or Standard (HGB + logistic).</p>}
      {error && <p className="mt-2 text-xs text-rose-700"><X size={12} className="mr-1 inline" />{error}</p>}
      {best && (
        <div className="mt-3 flex flex-wrap items-center gap-3 text-xs text-slate-600">
          <span>Authorized Autopilot best run <b className="font-mono">{best.runId.slice(0, 12)}…</b> (val log loss {fmt.n(best.logLoss)}) · {best.count} candidates added to the leaderboard.</span>
          {/* Gate 17 — activate the best candidate by immutable run id (never a browser result). */}
          {activated === best.runId
            ? <Pill label="ACTIVATED FOR DOWNSTREAM" tone="emerald" />
            : <Button size="sm" tone="dark" onClick={() => activate(best.runId)} disabled={activating}>{activating ? "Activating…" : "Activate best candidate"}</Button>}
        </div>
      )}
    </Card>
  );
}

// ============================================================ 10 Hyperparameter Tuning
export function TuningStep() {
  const store = useCockpitStore();
  const tuneSelected = store.labTuneSelected;
  // Gate 6 — the legacy binding-free C-grid posted configs to the D3/C4 /cockpit/experiment/run path and
  // returned 2025 metrics; it is disabled. There is no authorized per-trial grid endpoint yet, so tuning
  // is presented as an explicit unavailable state that routes the scientist to the authorized bounded
  // search (Autopilot · Standard), which fits its candidates through the server-authorized run path.
  return (
    <div className="space-y-4">
      {tuneSelected.length > 0 && (
        <div className="rounded-xl border border-violet-200 bg-violet-50/60 px-4 py-3 text-sm text-slate-700">
          <span className="font-semibold text-violet-700">Sent from the Model Laboratory:</span> {tuneSelected.join(", ")} — these candidates were checked for tuning and carried over (selection persists across navigation).
        </div>
      )}
      <Card title="Hyperparameter search" description="A dedicated per-trial grid over the server-authorized run path is not wired in this slice." icon={SlidersHorizontal}
        action={<Pill label="AUTHORIZED PATH ONLY" tone="amber" />}>
        <div className="rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">
          <div className="flex items-center gap-2 font-semibold text-amber-800"><TriangleAlert size={15} /> Legacy grid disabled</div>
          <p className="mt-1.5">
            The previous C-grid trained directly on the champion D3/C4 pipeline and reported the sealed 2025 season.
            That binding-free path is disabled. Tuning must run through the same server-authorized execution as every
            other candidate: an active dataset binding → run authority → authorized fit, validated on 2024 with 2025 sealed.
          </p>
          <p className="mt-2">
            Use <b>Model Laboratory → Autopilot → Standard</b> to run a bounded, server-authorized candidate search
            (Governed HGB + Governed logistic). A dedicated hyperparameter grid over the authorized path is a future increment.
          </p>
        </div>
      </Card>
    </div>
  );
}

// Gate 7 — Evaluation resolves the ACTIVE CANDIDATE from the backend by run id (not lastResult / local
// state / config hash). Shows the immutable candidate identity; no 2025 payload.
function Gen3ActiveCandidateCard({ projectId }: { projectId: string }) {
  const [cand, setCand] = useState<any | null>(null);
  const [state, setState] = useState<"LOADING" | "ACTIVE" | "NONE" | "ERROR">("LOADING");
  useEffect(() => {
    cockpitGet<any>(`/cockpit/gen3/active-candidate/${encodeURIComponent(projectId)}`)
      .then((c) => { setCand(c); setState("ACTIVE"); })
      .catch((e) => setState(/failed:\s*404/.test(String(e)) ? "NONE" : "ERROR"));
  }, [projectId]);
  return (
    <Card title="Active candidate · server authority" icon={Trophy}
      description="Downstream evaluation consumes the project's active candidate resolved from the backend by immutable run id — never a local browser result.">
      {state === "LOADING" && <p className="text-sm text-slate-500">Resolving the active candidate…</p>}
      {state === "NONE" && <p className="text-sm text-amber-700">No active candidate — activate one from the Model Laboratory run plan.</p>}
      {state === "ERROR" && <p className="text-sm text-rose-700">Could not resolve the active candidate.</p>}
      {state === "ACTIVE" && cand && (
        <div className="grid gap-2 text-xs sm:grid-cols-2 lg:grid-cols-3">
          <MetricCard label="Run id" value={String(cand.experimentRunId).slice(0, 12) + "…"} detail="immutable" />
          <MetricCard label="Run authority" value={String(cand.runAuthorityId).slice(0, 12) + "…"} />
          <MetricCard label="Dataset" value={cand.generation} detail={String(cand.datasetVersionId).split(":")[0]} />
          <MetricCard label="Development" value={(cand.run?.developmentSeasons || []).join(", ")} />
          <MetricCard label="Validation" value={String(cand.run?.validationSeason ?? "2024")} />
          <MetricCard label="Val log loss" value={cand.run?.metrics?.logLoss != null ? fmt.n(cand.run.metrics.logLoss) : "—"} />
          <MetricCard label="Result fingerprint" value={String(cand.resultFingerprint).slice(0, 12) + "…"} />
        </div>
      )}
    </Card>
  );
}

// ============================================================ 11 Evaluation & Diagnostics
export function EvaluationStep({ projectId = "mlb-cockpit" }: { projectId?: string } = {}) {
  const ev = useActiveEvaluation(projectId);   // Gate 18 — active candidate's immutable 2024 evidence bundle
  if (ev.state === "LOADING") return <div className="space-y-4"><Gen3ActiveCandidateCard projectId={projectId} /><p className="text-sm text-slate-500">Resolving the active candidate's evidence…</p></div>;
  if (ev.state !== "ACTIVE" || !ev.data) {
    return (
      <div className="space-y-4">
        <Gen3ActiveCandidateCard projectId={projectId} />
        <NeedRun label={ev.state === "ERROR" ? "Could not resolve the active candidate's evidence." : "Activate a candidate from the Model Laboratory run plan to populate diagnostics (server-authoritative; 2025 is sealed)."} />
      </div>
    );
  }
  const d = ev.data;
  const m = d.diagnostics;
  const order: string[] = m.classOrder;
  const severe = order.map((c) => ({ c, brier: m.classwiseBrier[c], ece: m.classwiseEce[c] })).sort((a, b) => b.brier - a.brier);
  return (
    <div className="space-y-4">
      <Gen3ActiveCandidateCard projectId={projectId} />
      <Card title="Validation evidence · active candidate" icon={BarChart3}
        description="Diagnostics are resolved from the active candidate's immutable 2024-validation evidence bundle (never a browser result). 2025 is sealed and never scored."
        action={<Pill label={d.recomputationMatchesStored ? "RECOMPUTE VERIFIED" : "RECOMPUTE MISMATCH"} tone={d.recomputationMatchesStored ? "emerald" : "rose"} />}>
        <div className="grid gap-3 sm:grid-cols-3 lg:grid-cols-5">
          <MetricCard label="Log loss" value={fmt.n(d.metrics.logLoss, 6)} detail="2024 validation" />
          <MetricCard label="Brier" value={fmt.n(d.metrics.brierScore, 4)} />
          <MetricCard label="Top-label ECE" value={fmt.n(d.metrics.topLabelEce, 4)} />
          <MetricCard label="Top-1" value={fmt.n(d.metrics.top1Accuracy, 4)} />
          <MetricCard label="Macro F1" value={fmt.n(d.metrics.macroF1, 4)} />
        </div>
        <p className="mt-2 text-[11px] text-slate-500">
          Independent log loss recomputed from the persisted prediction + target artifacts:
          <b className="ml-1 font-mono">{fmt.n(d.independentRecomputedLogLoss, 8)}</b> · run <span className="font-mono">{String(d.runId).slice(0, 12)}…</span> · evidence <span className="font-mono">{String(d.evidenceBundleSha256).slice(0, 12)}…</span> · {d.modelFamily}
        </p>
      </Card>
      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Class-level performance" description="Per-outcome support, recall, class Brier, and class ECE (2024)." icon={BarChart3}>
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
        <Card title="Confusion (row-normalized)" description="Realized (rows) vs predicted (columns) on 2024 validation." icon={BarChart3}>
          <ConfusionHeatmap matrix={m.confusionMatrix} labels={order} />
        </Card>
      </div>
      <Card title="Severe-miss concentration" description="Classes ranked by Brier contribution — where the model's probability error concentrates (2024)." icon={BarChart3}>
        <BarChart horizontal categories={severe.map((s) => s.c)} values={severe.map((s) => s.brier)} height={220} color="#e11d48" valueFmt={(v) => fmt.n(v, 4)} />
      </Card>
      {/* Registered severe-miss / error analysis (relocated Phase 4F): where does the model fail? */}
    </div>
  );
}

// Gate 18/19 — one hook resolves the active candidate's immutable evaluation evidence for a project.
type EvalState = { state: "LOADING" | "ACTIVE" | "NONE" | "ERROR"; data?: any };
function useActiveEvaluation(projectId: string): EvalState {
  const [st, setSt] = useState<EvalState>({ state: "LOADING" });
  useEffect(() => {
    let alive = true; setSt({ state: "LOADING" });
    cockpitGet<any>(`/cockpit/gen3/evaluation/${encodeURIComponent(projectId)}`)
      .then((d) => { if (alive) setSt({ state: "ACTIVE", data: d }); })
      .catch((e) => { if (alive) setSt({ state: /failed:\s*404/.test(String(e)) ? "NONE" : "ERROR" }); });
    return () => { alive = false; };
  }, [projectId]);
  return st;
}

// ============================================================ 12 Calibration
export function CalibrationStep({ projectId = "mlb-cockpit" }: { projectId?: string } = {}) {
  const ev = useActiveEvaluation(projectId);   // Gate 19 — same active candidate evidence as Evaluation
  const [cls, setCls] = useState<string>("STRIKEOUT");
  if (ev.state === "LOADING") return <div className="space-y-4"><Gen3ActiveCandidateCard projectId={projectId} /><p className="text-sm text-slate-500">Resolving the active candidate's evidence…</p></div>;
  if (ev.state !== "ACTIVE" || !ev.data) return (
    <div className="space-y-4">
      <Gen3ActiveCandidateCard projectId={projectId} />
      <NeedRun label="Calibration diagnostics are computed on the server-authorized active candidate. Activate a candidate from the Model Laboratory — 2025 is sealed and is never calibrated." />
    </div>
  );
  const m = ev.data.diagnostics;
  const topRel = (m.topLabelReliability || []).map((b: any) => ({ meanPredicted: b.meanConfidence, observed: b.accuracy, count: b.count }));
  const order: string[] = m.classOrder;
  const clsRel = (m.classwiseReliability?.[cls] || []).map((b: any) => ({ meanPredicted: b.meanProbability, observed: b.realizedFrequency, count: b.count }));
  return (
    <div className="space-y-4">
      <Gen3ActiveCandidateCard projectId={projectId} />
      <div className="rounded-xl border border-amber-300 bg-amber-50 px-4 py-3 text-xs text-amber-900">
        <div className="flex items-center gap-2 font-semibold text-amber-800"><TriangleAlert size={14} /> Raw calibration diagnostics · calibrator not configured</div>
        <p className="mt-1">No governed calibrator artifact is fit for this candidate in this phase. The reliability charts below are the candidate's RAW 2024-validation probabilities — the candidate is <b>not</b> calibrated. 2025 is sealed and is never used to fit or choose a calibrator.</p>
      </div>
      <Card title="Calibration reliability (raw)" description="Raw model probabilities on the 2024 validation season, resolved from the active candidate's evidence bundle." icon={Gauge}
        action={<Pill label="2024 validation · RAW" tone="amber" />}>
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
    </div>
  );
}

// ============================================================ 13 Simulation Impact
// ============================================================ 13 Simulation Impact
export function SimulationStep({ projectId = "mlb-cockpit" }: { projectId?: string } = {}) {
  // Gate 20 — the legacy binding-free whole-game simulator (which accepted the sealed 2025 season and ran
  // on a local browser config) was retired by the Phase 7C cutover. An authoritative simulation bound to the
  // active candidate's verified model/preprocessor on 2024 context is not configured in this phase.
  return (
    <div className="space-y-4">
      <Gen3ActiveCandidateCard projectId={projectId} />
      <Card title="Whole-game simulation impact" icon={Orbit}
        description="Does the challenger's PA-level change improve the whole game? This stage must bind the active candidate's verified model + preprocessor to 2024 historical context."
        action={<Pill label="NOT CONFIGURED" tone="amber" />}>
        <div className="rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">
          <div className="flex items-center gap-2 font-semibold text-amber-800"><TriangleAlert size={15} /> Authoritative simulation impact not configured for this candidate</div>
          <p className="mt-1.5">
            The previous simulator ran on a browser-local configuration through a binding-free endpoint and
            accepted the sealed 2025 season. That path is retired. A canonical simulation that binds the active
            run id, model SHA, preprocessor SHA, and a 2024-only context is a future increment.
          </p>
          <p className="mt-2">No simulation result is shown, and no legacy result is retained to imply otherwise.</p>
        </div>
      </Card>
    </div>
  );
}

// ============================================================ 14 Champion / Challenger
export function ChampionChallengerStep({ projectId = "mlb-cockpit" }: { projectId?: string } = {}) {
  // Gate 30 — the registered D3/C4 champion is a READ-ONLY reference; it is never overwritten, retrained,
  // or promoted, and its historical 2025 metric is not exposed in the ordinary workflow. The challenger is
  // the project's active candidate (server-authoritative), evaluated on 2024 only.
  const ev = useActiveEvaluation(projectId);
  const d = ev.state === "ACTIVE" ? ev.data : null;
  return (
    <div className="space-y-4">
      <Card title="Champion of record" description="The registered D3 C4 champion is a read-only reference. It is never overwritten or promoted automatically, and its sealed-season metrics are not shown in the ordinary workflow." icon={Trophy}
        action={<Pill label="READ-ONLY REFERENCE" tone="emerald" />}>
        <div className="grid gap-3 sm:grid-cols-3">
          <MetricCard label="Family" value="Governed logistic" detail="D3 C4" />
          <MetricCard label="Development" value="2021–2023" />
          <MetricCard label="Validation" value="2024" />
        </div>
      </Card>
      <Card title="Active challenger" description="The project's active candidate, resolved from the server by immutable run id and evaluated on 2024 validation only." icon={FlaskConical}>
        {d ? (
          <div className="grid gap-3 sm:grid-cols-4">
            <MetricCard label="Run id" value={String(d.runId).slice(0, 12) + "…"} detail={d.modelFamily} />
            <MetricCard label="2024 log loss" value={fmt.n(d.metrics.logLoss, 6)} />
            <MetricCard label="Recompute" value={d.recomputationMatchesStored ? "verified" : "MISMATCH"} detail="independent" />
            <MetricCard label="Evidence" value={String(d.evidenceBundleSha256).slice(0, 12) + "…"} />
          </div>
        ) : <p className="text-sm text-slate-500">No active candidate. Activate one from the Model Laboratory.</p>}
      </Card>
      <Card title="Promotion" description="Champion promotion is disabled. No Phase 7C candidate automatically becomes champion; the registered D3/C4 is not modified." icon={Trophy}
        action={<Button size="sm" tone="ghost" disabled>Promote to research champion</Button>}>
        <p className="text-sm text-slate-500">Promotion is a governed, out-of-band action and is intentionally unavailable here.</p>
      </Card>
    </div>
  );
}

// ============================================================ 15 Registry & Evidence
export function RegistryStep({ projectId = "mlb-cockpit" }: { projectId?: string } = {}) {
  const ev = useActiveEvaluation(projectId);   // registry evidence is the active candidate's immutable bundle
  if (ev.state !== "ACTIVE" || !ev.data) return (
    <div className="space-y-4">
      <Gen3ActiveCandidateCard projectId={projectId} />
      <NeedRun label="Activate a candidate from the Model Laboratory to view its immutable registry record and model card (server-authoritative; 2025 sealed)." />
    </div>
  );
  const d = ev.data;
  return (
    <div className="space-y-4">
      <Card title="Run evidence record" description="Content-addressed, immutable, independently-recomputable model-run evidence bundle." icon={Boxes}
        action={<Pill label="SERVER-AUTHORIZED EVIDENCE" tone="cyan" />}>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {[["Run id", String(d.runId)], ["Run authority", String(d.runAuthorityId)], ["Model family", d.modelFamily],
            ["Evidence manifest", String(d.evidenceBundleSha256)], ["Prediction SHA", String(d.predictionSha256)], ["Diagnostics SHA", String(d.diagnosticsSha256)]].map(([k, v]) => (
            <div key={k} className="rounded-lg border border-slate-200 bg-slate-50 p-3"><div className="text-xs font-semibold uppercase text-slate-500">{k}</div><div className="mt-1 break-words font-mono text-[11px] font-semibold text-slate-900">{String(v).slice(0, 24)}{String(v).length > 24 ? "…" : ""}</div></div>
          ))}
        </div>
      </Card>
      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Model card" description="Objective → data → preprocessing → algorithm → metrics → limitations." icon={Boxes}>
          <dl className="space-y-2 text-sm">
            <Row k="Objective" v="Plate Appearance Outcome (8-class)" />
            <Row k="Population" v={`dev ${(d.developmentSeasons || []).join(",")} · val ${d.validationSeason} · 2025 SEALED`} />
            <Row k="Dataset" v={`${d.generation} · ${String(d.datasetVersionId).split(":")[0]}`} />
            <Row k="Algorithm" v={d.modelFamily} />
            <Row k="2024 validation log loss" v={fmt.n(d.metrics.logLoss, 6)} />
            <Row k="Independent recompute" v={`${fmt.n(d.independentRecomputedLogLoss, 6)} · ${d.recomputationMatchesStored ? "verified" : "MISMATCH"}`} />
            <Row k="Calibration" v="RAW — calibrator not configured" />
          </dl>
        </Card>
        <Card title="Lineage & reproducibility" description="Immutable authorities and content digests." icon={Boxes}>
          <div className="space-y-2 text-xs">
            <Row k="Content SHA" v={String(d.datasetContentSha256).slice(0, 24) + "…"} />
            <Row k="Evidence manifest" v={String(d.evidenceBundleSha256).slice(0, 24) + "…"} />
            <Row k="Prediction artifact" v={String(d.predictionSha256).slice(0, 24) + "…"} />
            <Row k="Result fingerprint" v={String(d.resultFingerprint || "").slice(0, 24) + "…"} />
            <Row k="Validation" v={d.validationLabel} />
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
