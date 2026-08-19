// Canonical guided MLB workflow: a persistent shell that always answers where am I, what do I do,
// and what happens next. One stage in focus at a time, a 12-stage stepper with real status, inline
// Stage 1 (forecast contract) and Stage 2 (dataset binding), and deep-links to real modules for the
// rest — every action preserves project context and returns to this workflow.
import { useMemo } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import {
  ArrowLeft, ArrowRight, CheckCircle2, ChevronRight, CircleDot, Database, Info, Lock,
  Target, ShieldCheck, UsersRound, SlidersHorizontal, GitBranch, Gauge, FlaskConical, Clock3,
  Network, PackageCheck, ExternalLink, CircleDashed, TriangleAlert,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { useWorkflowStore } from "../../state/useWorkflowStore";
import { loadSportsProjectMetadata, MLB_WORKFLOW } from "../sportsConfig";
import { useActiveSportsDataset } from "../sportsEvidenceApi";
import {
  resolveStages, firstActionableStage, completionSummary, loadContract, loadBinding,
  type StageResolution, type StageStatus,
} from "./workflowState";
import { ForecastContractPanel } from "./ForecastContractPanel";
import { DatasetBindingPanel } from "./DatasetBindingPanel";

const STEP_ICONS: LucideIcon[] = [Target, Database, ShieldCheck, UsersRound, SlidersHorizontal, GitBranch, Gauge, FlaskConical, Clock3, CheckCircle2, Network, PackageCheck];

const STATUS_STYLE: Record<StageStatus, { chip: string; dot: string; label: string }> = {
  COMPLETE: { chip: "border-emerald-200 bg-emerald-50 text-emerald-800", dot: "bg-emerald-500", label: "Complete" },
  CURRENT: { chip: "border-cyan-300 bg-cyan-50 text-cyan-800", dot: "bg-cyan-500", label: "Current step" },
  READY: { chip: "border-blue-200 bg-blue-50 text-blue-800", dot: "bg-blue-400", label: "Ready" },
  BLOCKED: { chip: "border-slate-200 bg-slate-100 text-slate-500", dot: "bg-slate-300", label: "Blocked" },
  STALE: { chip: "border-amber-200 bg-amber-50 text-amber-800", dot: "bg-amber-400", label: "Requires review" },
};

export default function GuidedWorkflow() {
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const projectId = useWorkflowStore((s) => s.projectId);
  const projectName = useWorkflowStore((s) => s.projectName);
  const datasetEvidence = useActiveSportsDataset();
  const dataset = datasetEvidence.status === "ready" ? datasetEvidence.data : null;
  const metadata = loadSportsProjectMetadata(projectId);

  // resolutions recompute whenever the URL step changes (after save/bind we bump ?step)
  const contract = loadContract(projectId);
  const binding = loadBinding(projectId);
  const resolutions = useMemo(
    () => resolveStages(projectId, dataset, contract, binding),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [projectId, datasetEvidence.status, params.get("step"), params.get("v")],
  );
  const summary = completionSummary(resolutions);
  const focusNumber = Number(params.get("step")) || firstActionableStage(resolutions);
  const focus = resolutions.find((r) => r.number === focusNumber) || resolutions[0];
  const displayName = projectName && projectName !== "Untitled Sports Project" ? projectName : "MLB Plate Appearance Modeling";

  const goStep = (n: number) => setParams((p) => { const np = new URLSearchParams(p); np.set("step", String(n)); return np; });
  const refresh = () => setParams((p) => { const np = new URLSearchParams(p); np.set("v", String(Date.now())); return np; });

  const loading = datasetEvidence.status === "loading";

  return (
    <div className="sports-page-shell space-y-5">
      {/* Persistent context header */}
      <section className="sports-hero-panel p-5 sm:p-7">
        <div className="relative z-10">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <Link to="/project-overview" className="inline-flex items-center gap-2 text-sm font-semibold text-slate-300 hover:text-white"><ArrowLeft size={16} /> Project Overview</Link>
            <span className="sports-status sports-status--teal">MLB · Guided Workflow</span>
          </div>
          <div className="mt-6 grid gap-6 lg:grid-cols-[minmax(0,1fr)_320px] lg:items-end">
            <div>
              <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.16em] text-cyan-200"><CircleDot size={15} /> Step {focus.number} of 12 · {STATUS_STYLE[focus.status].label}</div>
              <h1 className="mt-3 text-3xl font-semibold tracking-tight text-white sm:text-4xl">{displayName}</h1>
              <div className="mt-2 text-lg font-semibold text-cyan-100">{focus.title}</div>
              <p className="mt-3 max-w-3xl text-[15px] leading-7 text-slate-300">{focus.purpose}</p>
            </div>
            <div className="rounded-2xl border border-white/10 bg-white/[0.06] p-5 backdrop-blur">
              <div className="flex items-end justify-between"><span className="text-sm font-medium text-slate-300">Overall completion</span><strong className="text-3xl tabular-nums text-white">{summary.pct}%</strong></div>
              <div className="mt-3 h-2 overflow-hidden rounded-full bg-white/10"><span className="block h-full rounded-full bg-gradient-to-r from-teal-400 to-cyan-300" style={{ width: `${summary.pct}%` }} /></div>
              <p className="mt-3 text-xs leading-5 text-slate-400">{summary.complete} complete · {summary.ready} ready · {summary.blocked} blocked</p>
            </div>
          </div>
        </div>
      </section>

      <div className="grid gap-5 lg:grid-cols-[300px_minmax(0,1fr)]">
        {/* 12-stage stepper */}
        <nav className="lg:sticky lg:top-4 lg:self-start" aria-label="Workflow stages">
          <ol className="space-y-1 rounded-2xl border border-slate-200 bg-white p-3 shadow-sm">
            {resolutions.map((r, i) => {
              const Icon = STEP_ICONS[i];
              const active = r.number === focus.number;
              const st = STATUS_STYLE[r.status];
              return (
                <li key={r.id}>
                  <button onClick={() => goStep(r.number)}
                    className={`flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-left transition ${active ? "bg-slate-900 text-white" : "hover:bg-slate-50"}`}>
                    <span className={`grid h-7 w-7 shrink-0 place-items-center rounded-lg text-xs font-bold tabular-nums ${r.status === "COMPLETE" ? "bg-emerald-100 text-emerald-700" : active ? "bg-cyan-400/20 text-cyan-200" : "bg-slate-100 text-slate-500"}`}>
                      {r.status === "COMPLETE" ? <CheckCircle2 size={15} /> : r.number}
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className={`block truncate text-sm font-semibold ${active ? "text-white" : "text-slate-800"}`}>{r.title}</span>
                      <span className={`mt-0.5 flex items-center gap-1.5 text-[11px] ${active ? "text-slate-300" : "text-slate-400"}`}><span className={`h-1.5 w-1.5 rounded-full ${st.dot}`} />{st.label}</span>
                    </span>
                    {!active && <Icon size={15} className="shrink-0 text-slate-300" />}
                  </button>
                </li>
              );
            })}
          </ol>
        </nav>

        {/* Focused stage workspace */}
        <div className="min-w-0 space-y-4">
          {loading ? (
            <div className="sports-panel p-8 text-center text-sm text-slate-500"><CircleDashed size={22} className="mx-auto animate-spin text-slate-400" /><p className="mt-3">Loading registered MLB evidence…</p></div>
          ) : (
            <StageWorkspace
              key={focus.number}
              focus={focus}
              resolutions={resolutions}
              projectId={projectId}
              metadata={metadata}
              dataset={dataset}
              datasetStatus={datasetEvidence.status}
              onGoStep={goStep}
              onCompleted={(next) => { refresh(); goStep(next); }}
            />
          )}

          {/* Footer navigation */}
          <div className="flex items-center justify-between rounded-2xl border border-slate-200 bg-white px-4 py-3 shadow-sm">
            <button onClick={() => goStep(Math.max(1, focus.number - 1))} disabled={focus.number === 1}
              className="inline-flex items-center gap-2 rounded-lg border border-slate-300 px-3 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50 disabled:opacity-40">
              <ArrowLeft size={15} /> Previous
            </button>
            <span className="text-xs font-semibold uppercase tracking-wide text-slate-500">Step {focus.number} of 12</span>
            <ContinueButton focus={focus} onGoStep={goStep} />
          </div>
        </div>
      </div>
    </div>
  );
}

function ContinueButton({ focus, onGoStep }: { focus: StageResolution; onGoStep: (n: number) => void }) {
  const isLast = focus.number === 12;
  const canContinue = focus.status === "COMPLETE";
  if (isLast) return <span className="text-xs font-semibold text-slate-400">End of workflow</span>;
  return (
    <div className="flex flex-col items-end">
      <button onClick={() => onGoStep(focus.number + 1)} disabled={!canContinue}
        className="inline-flex items-center gap-2 rounded-lg bg-cyan-600 px-4 py-2 text-sm font-semibold text-white hover:bg-cyan-500 disabled:cursor-not-allowed disabled:bg-slate-200 disabled:text-slate-400">
        Continue <ArrowRight size={15} />
      </button>
      {!canContinue && <span className="mt-1 text-[11px] text-slate-400">Complete this step to continue</span>}
    </div>
  );
}

function StageWorkspace({
  focus, resolutions, projectId, metadata, dataset, datasetStatus, onGoStep, onCompleted,
}: {
  focus: StageResolution;
  resolutions: StageResolution[];
  projectId: string;
  metadata: ReturnType<typeof loadSportsProjectMetadata>;
  dataset: ReturnType<typeof useActiveSportsDataset>["data"];
  datasetStatus: string;
  onGoStep: (n: number) => void;
  onCompleted: (next: number) => void;
}) {
  const st = STATUS_STYLE[focus.status];
  const step = MLB_WORKFLOW.steps.find((s) => s.number === focus.number)!;

  // Blocked stage → helpful redirect, never a dead end.
  if (focus.status === "BLOCKED") {
    return (
      <section className="sports-panel p-6">
        <div className="flex items-center gap-2"><span className={`sports-status ${st.chip}`}>Blocked</span></div>
        <h2 className="mt-3 text-2xl font-semibold text-slate-950">{focus.title}</h2>
        <div className="mt-4 flex items-start gap-3 rounded-xl border border-slate-200 bg-slate-50 px-4 py-3">
          <Lock size={18} className="mt-0.5 shrink-0 text-slate-400" />
          <div>
            <div className="text-sm font-semibold text-slate-800">This stage is not available yet.</div>
            <p className="mt-1 text-sm text-slate-600">{focus.blockedReason}</p>
          </div>
        </div>
        <button onClick={() => onGoStep(focus.blockedByNumber || 1)} className="sports-primary-button mt-5">
          Go to Step {focus.blockedByNumber} <ArrowRight size={16} />
        </button>
      </section>
    );
  }

  return (
    <div className="space-y-4">
      {/* Purpose / why it matters */}
      <section className="sports-panel p-5 sm:p-6">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.14em] text-cyan-700">Step {focus.number} · {focus.estMinutes}</div>
          <span className={`sports-status ${st.chip}`}>{st.label}</span>
        </div>
        <h2 className="mt-2 text-2xl font-semibold tracking-tight text-slate-950">{focus.title}</h2>
        <p className="mt-2 text-[15px] leading-7 text-slate-600">{focus.purpose}</p>
        {focus.whyItMatters && (
          <div className="mt-4 flex items-start gap-3 rounded-xl border border-cyan-100 bg-cyan-50/60 px-4 py-3">
            <Info size={17} className="mt-0.5 shrink-0 text-cyan-700" />
            <p className="text-sm leading-6 text-slate-700"><b className="font-semibold text-slate-900">Why this matters.</b> {focus.whyItMatters}</p>
          </div>
        )}
      </section>

      {/* Stage-specific body */}
      {focus.number === 1 && (
        <ForecastContractPanel projectId={projectId} metadata={metadata} existing={loadContract(projectId)} onSaved={() => onCompleted(2)} />
      )}
      {focus.number === 2 && (
        <DatasetBindingPanel projectId={projectId} dataset={dataset} datasetStatus={datasetStatus} bound={focus.status === "COMPLETE"} onBound={() => onCompleted(3)} />
      )}
      {focus.number >= 3 && <DeepLinkStage focus={focus} step={step} />}

      {/* Registered evidence */}
      {focus.evidence.length > 0 && (
        <section className="sports-panel p-5">
          <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-emerald-700"><CheckCircle2 size={14} /> Registered evidence</div>
          <ul className="mt-3 grid gap-1.5 text-sm text-slate-700">
            {focus.evidence.map((e) => <li key={e} className="flex gap-2"><CheckCircle2 size={15} className="mt-0.5 shrink-0 text-emerald-500" />{e}</li>)}
          </ul>
        </section>
      )}

      {/* Advanced technical specification (progressive disclosure) */}
      <details className="sports-panel px-5 py-4">
        <summary className="cursor-pointer text-sm font-semibold text-slate-700">Advanced · technical specification</summary>
        <div className="mt-3 grid gap-4 sm:grid-cols-2">
          <div><div className="text-xs font-semibold uppercase tracking-wide text-slate-400">Scope</div><div className="mt-2 flex flex-wrap gap-1.5">{step.sections.map((s) => <span key={s} className="rounded-md border border-slate-200 bg-slate-50 px-2 py-1 text-xs text-slate-600">{s}</span>)}</div></div>
          <div><div className="text-xs font-semibold uppercase tracking-wide text-slate-400">Expected outputs</div><ul className="mt-2 grid gap-1 text-xs text-slate-600">{step.outputs.map((o) => <li key={o} className="flex gap-2"><span className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-slate-400" />{o}</li>)}</ul></div>
          {step.prerequisites.length > 0 && <div className="sm:col-span-2"><div className="text-xs font-semibold uppercase tracking-wide text-slate-400">Prerequisites</div><p className="mt-1 text-xs text-slate-600">{step.prerequisites.join(" · ")}</p></div>}
        </div>
      </details>
    </div>
  );
}

function DeepLinkStage({ focus, step }: { focus: StageResolution; step: { number: number } }) {
  const isComplete = focus.status === "COMPLETE";
  const isExport = focus.number === 12;
  const route = focus.action.route || "/dashboard";
  const href = `${route}?from=mlb-workflow&step=${focus.number}`;
  return (
    <section className="sports-panel p-5 sm:p-6">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div className="min-w-0">
          <div className="text-sm font-semibold text-slate-900">{isComplete ? "Registered evidence available" : isExport ? "Export gate" : "Primary action"}</div>
          <p className="mt-1 max-w-2xl text-sm text-slate-600">
            {isExport
              ? "Export requires a governed Model Graph & Research Decision from Step 11. It will package the approved graph as an immutable bundle."
              : isComplete
                ? "This stage already has registered evidence. Open the module to review it in full, or continue to the next step."
                : "Open the dedicated workspace to configure and review this stage. Your project context and this workflow are preserved."}
          </p>
        </div>
        {isExport ? (
          <button disabled className="inline-flex shrink-0 cursor-not-allowed items-center gap-2 rounded-xl bg-slate-200 px-4 py-2.5 text-sm font-semibold text-slate-500"><Lock size={15} /> Export MLB Bundle</button>
        ) : (
          <Link to={href} className="sports-primary-button shrink-0">{focus.action.label} <ExternalLink size={15} /></Link>
        )}
      </div>
      {focus.number === 3 && isComplete && (
        <div className="mt-4 grid gap-3 sm:grid-cols-2">
          <a href="/data-warehouse?from=mlb-workflow&step=3" className="inline-flex items-center gap-2 text-sm font-semibold text-cyan-700 hover:underline"><Database size={15} /> Inspect full identity evidence in Data Warehouse</a>
        </div>
      )}
      {isExport && (
        <button className="mt-4 inline-flex items-center gap-2 text-sm font-semibold text-cyan-700 hover:underline"><ChevronRight size={15} /> Requires Step 11 — Model Graph & Decision</button>
      )}
    </section>
  );
}
