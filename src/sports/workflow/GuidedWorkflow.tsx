// Canonical guided MLB workflow. Honest project-evidence semantics: existing workspace evidence is
// shown as AVAILABLE / READY TO ADOPT, never silently COMPLETE — the project must adopt it. Steps 1
// and 2 auto-advance (no interstitials); Step 3 reviews identity/leakage evidence inline; Steps
// 4–11 review & adopt available evidence or open the real module to configure. No dead-end routes.
import { useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import {
  ArrowLeft, ArrowRight, CheckCircle2, CircleDashed, CircleDot, Database, ExternalLink, Info, Lock,
  PanelLeftClose, PanelLeftOpen,
  Target, ShieldCheck, UsersRound, SlidersHorizontal, GitBranch, Gauge, FlaskConical, Clock3,
  Network, PackageCheck, TriangleAlert,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { useWorkflowStore } from "../../state/useWorkflowStore";
import { loadSportsProjectMetadata, MLB_WORKFLOW } from "../sportsConfig";
import { useActiveSportsDataset, type ActiveSportsDataset } from "../sportsEvidenceApi";
import {
  resolveStages, firstActionableStage, nextActionable, completionSummary, loadContract, loadBinding, adoptStage,
  type StageResolution, type StageStatus, type EvidenceState, type DecisionClass,
} from "./workflowState";
import { ForecastContractPanel } from "./ForecastContractPanel";
import { DatasetBindingPanel } from "./DatasetBindingPanel";
import { GuidedStageContent, AdoptBar, AutoSatisfiedFoundation, FoundationSummary } from "./GuidedStageContent";

const STEP_ICONS: LucideIcon[] = [Target, Database, ShieldCheck, UsersRound, SlidersHorizontal, GitBranch, Gauge, FlaskConical, Clock3, CheckCircle2, Network, PackageCheck];

const STATUS_STYLE: Record<StageStatus, { chip: string; dot: string; label: string }> = {
  COMPLETE: { chip: "border-emerald-200 bg-emerald-50 text-emerald-800", dot: "bg-emerald-500", label: "Complete" },
  CURRENT: { chip: "border-cyan-300 bg-cyan-50 text-cyan-800", dot: "bg-cyan-500", label: "Current step" },
  READY: { chip: "border-blue-200 bg-blue-50 text-blue-800", dot: "bg-blue-400", label: "Ready" },
  BLOCKED: { chip: "border-slate-200 bg-slate-100 text-slate-500", dot: "bg-slate-300", label: "Blocked" },
  STALE: { chip: "border-amber-200 bg-amber-50 text-amber-800", dot: "bg-amber-400", label: "Requires review" },
};
const EVIDENCE_BADGE: Partial<Record<EvidenceState, { label: string; cls: string }>> = {
  WORKSPACE_EVIDENCE_AVAILABLE: { label: "Existing workspace evidence available", cls: "border-cyan-200 bg-cyan-50 text-cyan-700" },
  PROJECT_STAGE_COMPLETE: { label: "Adopted by this project", cls: "border-emerald-200 bg-emerald-50 text-emerald-700" },
  NO_EVIDENCE: { label: "Not configured for this project", cls: "border-slate-200 bg-slate-50 text-slate-500" },
};
const CLASS_LABEL: Record<DecisionClass, string> = { CONFIGURE: "Configure", REVIEW_AND_DECIDE: "Review & decide", ANALYZE: "Analyze", OPTIONAL_CUSTOMIZATION: "Optional customization", AUTO_SATISFIED: "Auto-satisfied", BLOCKED: "Blocked", TERMINAL: "Terminal" };

export default function GuidedWorkflow() {
  const [params, setParams] = useSearchParams();
  const projectId = useWorkflowStore((s) => s.projectId);
  const projectName = useWorkflowStore((s) => s.projectName);
  const datasetEvidence = useActiveSportsDataset();
  const dataset = datasetEvidence.status === "ready" ? datasetEvidence.data : null;
  const metadata = loadSportsProjectMetadata(projectId);

  const resolutions = useMemo(
    () => resolveStages(projectId, dataset),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [projectId, datasetEvidence.status, params.get("step"), params.get("v")],
  );
  const summary = completionSummary(resolutions);
  const focusNumber = Number(params.get("step")) || firstActionableStage(resolutions);
  const focus = resolutions.find((r) => r.number === focusNumber) || resolutions[0];
  const justDone = Number(params.get("done")) || 0;
  const [navCollapsed, setNavCollapsed] = useState(false);
  const displayName = projectName && projectName !== "Untitled Sports Project" ? projectName : "MLB Plate Appearance Modeling";

  const goStep = (n: number) => setParams((p) => { const np = new URLSearchParams(p); np.set("step", String(n)); np.delete("done"); return np; });
  // After completing a stage, re-resolve (localStorage was just written) and jump to the next stage
  // that still needs work — auto-satisfied foundation stages (4, 5) are skipped automatically.
  const advanceFrom = (from: number) => {
    const next = firstActionableStage(resolveStages(projectId, dataset));
    setParams((p) => { const np = new URLSearchParams(p); np.set("step", String(next)); np.set("done", String(from)); np.set("v", String(Date.now())); return np; });
  };

  const loading = datasetEvidence.status === "loading";

  return (
    <div className="sports-page-shell space-y-5">
      <section className="sports-hero-panel p-5 sm:p-7">
        <div className="relative z-10">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <Link to="/project-overview" className="inline-flex items-center gap-2 text-sm font-semibold text-slate-300 hover:text-white"><ArrowLeft size={16} /> Project Overview</Link>
            <span className="sports-status sports-status--teal">MLB · Guided Workflow</span>
          </div>
          <div className="mt-6 grid gap-6 lg:grid-cols-[minmax(0,1fr)_320px] lg:items-end">
            <div>
              <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.16em] text-cyan-200"><CircleDot size={15} /> Step {focus.number} of 12 · {CLASS_LABEL[focus.decisionClass]}</div>
              <h1 className="mt-3 text-3xl font-semibold tracking-tight text-white sm:text-4xl">{displayName}</h1>
              <div className="mt-2 text-lg font-semibold text-cyan-100">{focus.title}</div>
              <p className="mt-3 max-w-3xl text-[15px] leading-7 text-slate-300">{focus.purpose}</p>
            </div>
            <div className="rounded-2xl border border-white/10 bg-white/[0.06] p-5 backdrop-blur">
              <div className="flex items-end justify-between"><span className="text-sm font-medium text-slate-300">Program completion</span><strong className="text-3xl tabular-nums text-white">{summary.complete}<span className="text-base text-slate-500">/12</span></strong></div>
              <div className="mt-3 h-2 overflow-hidden rounded-full bg-white/10"><span className="block h-full rounded-full bg-gradient-to-r from-teal-400 to-cyan-300" style={{ width: `${summary.pct}%` }} /></div>
              <p className="mt-3 text-xs leading-5 text-slate-400">{summary.complete} complete · {summary.ready} ready · {summary.available} evidence available · {summary.blocked} blocked</p>
            </div>
          </div>
        </div>
      </section>

      <div className={`grid gap-5 ${navCollapsed ? "lg:grid-cols-[64px_minmax(0,1fr)]" : "lg:grid-cols-[300px_minmax(0,1fr)]"}`}>
        <nav className="lg:sticky lg:top-4 lg:self-start" aria-label="Workflow stages">
          <div className="rounded-2xl border border-slate-200 bg-white p-2 shadow-sm">
            <button onClick={() => setNavCollapsed((c) => !c)} className="mb-1 flex w-full items-center justify-center gap-2 rounded-lg px-2 py-1.5 text-xs font-semibold text-slate-500 hover:bg-slate-50" title={navCollapsed ? "Expand stages" : "Collapse stages"}>
              {navCollapsed ? <PanelLeftOpen size={15} /> : <><PanelLeftClose size={15} /> Collapse</>}
            </button>
            <ol className="space-y-1">
              {resolutions.map((r, i) => {
                const Icon = STEP_ICONS[i];
                const active = r.number === focus.number;
                const style = STATUS_STYLE[r.status];
                const avail = r.evidenceState === "WORKSPACE_EVIDENCE_AVAILABLE";
                return (
                  <li key={r.id}>
                    <button onClick={() => goStep(r.number)} title={r.title} className={`flex w-full items-center gap-3 rounded-xl ${navCollapsed ? "justify-center px-1.5" : "px-3"} py-2.5 text-left transition ${active ? "bg-slate-900 text-white" : "hover:bg-slate-50"}`}>
                      <span className={`grid h-7 w-7 shrink-0 place-items-center rounded-lg text-xs font-bold tabular-nums ${r.status === "COMPLETE" ? "bg-emerald-100 text-emerald-700" : active ? "bg-cyan-400/20 text-cyan-200" : "bg-slate-100 text-slate-500"}`}>
                        {r.status === "COMPLETE" ? <CheckCircle2 size={15} /> : r.number}
                      </span>
                      {!navCollapsed && <>
                        <span className="min-w-0 flex-1">
                          <span className={`block truncate text-sm font-semibold ${active ? "text-white" : "text-slate-800"}`}>{r.title}</span>
                          <span className={`mt-0.5 flex items-center gap-1.5 text-[11px] ${active ? "text-slate-300" : "text-slate-400"}`}><span className={`h-1.5 w-1.5 rounded-full ${style.dot}`} />{r.autoSatisfied && r.status === "COMPLETE" ? "Foundation ready" : avail && r.status !== "COMPLETE" ? "Evidence available" : style.label}</span>
                        </span>
                        {!active && <Icon size={15} className="shrink-0 text-slate-300" />}
                      </>}
                    </button>
                  </li>
                );
              })}
            </ol>
          </div>
        </nav>

        <div className="min-w-0 space-y-4">
          {loading ? (
            <div className="sports-panel p-8 text-center text-sm text-slate-500"><CircleDashed size={22} className="mx-auto animate-spin text-slate-400" /><p className="mt-3">Loading registered MLB evidence…</p></div>
          ) : (
            <StageWorkspace key={focus.number} focus={focus} resolutions={resolutions} projectId={projectId} metadata={metadata} dataset={dataset} datasetStatus={datasetEvidence.status} justDone={justDone} onGoStep={goStep} advanceFrom={advanceFrom} />
          )}

          <div className="flex items-center justify-between rounded-2xl border border-slate-200 bg-white px-4 py-3 shadow-sm">
            <button onClick={() => goStep(Math.max(1, focus.number - 1))} disabled={focus.number === 1} className="inline-flex items-center gap-2 rounded-lg border border-slate-300 px-3 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50 disabled:opacity-40"><ArrowLeft size={15} /> Previous</button>
            <span className="text-xs font-semibold uppercase tracking-wide text-slate-500">Step {focus.number} of 12</span>
            {focus.number === 12 ? <span className="text-xs font-semibold text-slate-400">End of workflow</span> : (
              <div className="flex flex-col items-end">
                <button onClick={() => goStep(nextActionable(resolutions, focus.number))} disabled={focus.status !== "COMPLETE"} className="inline-flex items-center gap-2 rounded-lg bg-cyan-600 px-4 py-2 text-sm font-semibold text-white hover:bg-cyan-500 disabled:cursor-not-allowed disabled:bg-slate-200 disabled:text-slate-400">Continue <ArrowRight size={15} /></button>
                {focus.status !== "COMPLETE" && <span className="mt-1 text-[11px] text-slate-400">Complete this step to continue</span>}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

function StageWorkspace({
  focus, resolutions, projectId, metadata, dataset, datasetStatus, justDone, onGoStep, advanceFrom,
}: {
  focus: StageResolution;
  resolutions: StageResolution[];
  projectId: string;
  metadata: ReturnType<typeof loadSportsProjectMetadata>;
  dataset: ActiveSportsDataset | null;
  datasetStatus: string;
  justDone: number;
  onGoStep: (n: number) => void;
  advanceFrom: (from: number) => void;
}) {
  const style = STATUS_STYLE[focus.status];
  const step = MLB_WORKFLOW.steps.find((s) => s.number === focus.number)!;

  if (focus.status === "BLOCKED") {
    return (
      <section className="sports-panel p-6">
        <span className={`sports-status ${style.chip}`}>Blocked</span>
        <h2 className="mt-3 text-2xl font-semibold text-slate-950">{focus.title}</h2>
        <div className="mt-4 flex items-start gap-3 rounded-xl border border-slate-200 bg-slate-50 px-4 py-3">
          <Lock size={18} className="mt-0.5 shrink-0 text-slate-400" />
          <div><div className="text-sm font-semibold text-slate-800">This stage is not available yet.</div><p className="mt-1 text-sm text-slate-600">{focus.blockedReason}</p></div>
        </div>
        <button onClick={() => onGoStep(focus.blockedByNumber || 1)} className="sports-primary-button mt-5">Go to Step {focus.blockedByNumber} <ArrowRight size={16} /></button>
      </section>
    );
  }

  const badge = EVIDENCE_BADGE[focus.evidenceState];
  return (
    <div className="space-y-4">
      {justDone > 0 && justDone < focus.number && (
        <div className="flex items-center gap-2 rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-2.5 text-sm font-semibold text-emerald-800">
          <CheckCircle2 size={16} /> Step {justDone} complete — advanced to Step {focus.number}.
        </div>
      )}

      <section className="sports-panel p-5 sm:p-6">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.14em] text-cyan-700">Step {focus.number} · {CLASS_LABEL[focus.decisionClass]} · {focus.estMinutes}</div>
          <div className="flex items-center gap-2">
            {badge && focus.status !== "COMPLETE" ? <span className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11px] font-semibold ${badge.cls}`}>{badge.label}</span> : null}
            <span className={`sports-status ${style.chip}`}>{style.label}</span>
          </div>
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

      {focus.number === 1 && <ForecastContractPanel projectId={projectId} metadata={metadata} existing={loadContract(projectId)} onSaved={() => advanceFrom(1)} />}
      {focus.number === 2 && <DatasetBindingPanel projectId={projectId} dataset={dataset} datasetStatus={datasetStatus} bound={focus.status === "COMPLETE"} onBound={() => advanceFrom(2)} />}
      {focus.number === 3 && <IdentityEvidenceStage focus={focus} dataset={dataset} onAdopt={() => { adoptStage(projectId, 3); advanceFrom(3); }} />}
      {focus.number === 6 && <FoundationSummary resolutions={resolutions} onGoStep={onGoStep} />}
      {focus.number >= 4 && focus.number <= 11 && (
        <>
          {focus.autoSatisfied && focus.number <= 5
            ? <AutoSatisfiedFoundation focus={focus} dataset={dataset} />
            : <GuidedStageContent number={focus.number} dataset={dataset} contract={loadContract(projectId)} />}
          <AdoptBar focus={focus} onAdopt={() => { adoptStage(projectId, focus.number); advanceFrom(focus.number); }} />
        </>
      )}
      {focus.number === 12 && <AdoptOrConfigureStage focus={focus} onAdopt={() => {}} />}

      {focus.status === "COMPLETE" && focus.evidence.length > 0 && (
        <section className="sports-panel p-5">
          <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-emerald-700"><CheckCircle2 size={14} /> Adopted project evidence</div>
          <ul className="mt-3 grid gap-1.5 text-sm text-slate-700">{focus.evidence.map((e) => <li key={e} className="flex gap-2"><CheckCircle2 size={15} className="mt-0.5 shrink-0 text-emerald-500" />{e}</li>)}</ul>
        </section>
      )}

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

// ---- Step 3: inline identity / coverage / leakage evidence ----
function pct(v: number | undefined | null): string {
  if (v === undefined || v === null || Number.isNaN(v)) return "—";
  const p = v <= 1 ? v * 100 : v;
  return `${p.toFixed(1)}%`;
}
function IdentityEvidenceStage({ focus, dataset, onAdopt }: { focus: StageResolution; dataset: ActiveSportsDataset | null; onAdopt: () => void }) {
  const bridge = dataset?.identityBridge;
  const audit = dataset?.featureAudit;
  const ja = bridge?.joinAudit;
  const noFuzzy = bridge?.noNamesOrFuzzyMatching ?? (audit?.joinEvidence?.inferenceOrFuzzyMatchingUsed === false);
  const seasons = audit?.perSeasonRows ?? [];
  const complete = focus.status === "COMPLETE";
  const rights = bridge?.rights;
  const limitations = dataset?.limitations ?? [];
  return (
    <section className="sports-panel p-5 sm:p-6">
      <div className="grid gap-4 md:grid-cols-2">
        <EvidenceBlock title="Player identity" status={ja?.status || (bridge ? "PASS" : "UNVERIFIED")}>
          <Line k="Exact mapping rate" v={pct(ja?.mappingRate)} />
          <Line k="Unresolved" v={ja ? String(ja.unresolvedReferences) : "—"} />
          <Line k="Ambiguous" v={ja ? String(ja.ambiguousReferences) : "—"} />
        </EvidenceBlock>
        <EvidenceBlock title="Leakage review" status={noFuzzy ? "PASS" : "REVIEW"}>
          <div className="text-sm text-slate-600">{noFuzzy ? "Exact identity joins only — no name or fuzzy matching." : "Identity resolution uses inference; review required."}</div>
          <div className="mt-1 text-sm text-slate-600">Point-in-time evidence {audit?.joinEvidence?.sameSeasonPredictorEligibleObserved === false ? "verified (Y−1 priors only)" : "present"}.</div>
        </EvidenceBlock>
      </div>

      {seasons.length > 0 && (
        <div className="mt-4">
          <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Prior coverage by season</div>
          <div className="mt-2 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
            {seasons.map((s) => (
              <div key={s.season} className="rounded-xl border border-slate-200 bg-slate-50 p-3 text-sm">
                <div className="font-semibold text-slate-900">{s.season}</div>
                <div className="mt-1 text-slate-600">Batter Y−1: <b>{pct(s.batterYMinus1JoinMatches / Math.max(1, s.batterYMinus1JoinDenominator))}</b></div>
                <div className="text-slate-600">Pitcher Y−1: <b>{pct(s.pitcherYMinus1JoinMatches / Math.max(1, s.pitcherYMinus1JoinDenominator))}</b></div>
              </div>
            ))}
          </div>
        </div>
      )}

      {limitations.length > 0 && (
        <div className="mt-4">
          <div className="text-xs font-semibold uppercase tracking-wide text-amber-700">Known limitations</div>
          <ul className="mt-1 grid gap-0.5 text-xs text-amber-900">{limitations.slice(0, 5).map((l) => <li key={l}>· {l}</li>)}</ul>
        </div>
      )}

      <details className="mt-4 rounded-xl border border-slate-200 bg-slate-50 px-4 py-3">
        <summary className="cursor-pointer text-sm font-semibold text-slate-700">View technical authority</summary>
        <div className="mt-2 grid gap-1 font-mono text-[11px] text-slate-500">
          {bridge ? <div>identity bridge · {bridge.registrationId} · {bridge.manifestSha.slice(0, 16)}…</div> : null}
          {rights ? <div>rights · {rights.status}</div> : null}
          {audit ? <div>feature audit · {audit.contractVersion} · {audit.status}</div> : null}
        </div>
      </details>

      <div className="mt-5 flex flex-wrap gap-3">
        {!complete && <button onClick={onAdopt} className="sports-primary-button">Adopt Evidence &amp; Continue <ArrowRight size={15} /></button>}
        <Link to="/data-warehouse?from=mlb-workflow&step=3" className="sports-dark-button"><Database size={16} /> Inspect Full Evidence in Data Warehouse</Link>
      </div>
    </section>
  );
}

// ---- Steps 4–12: adopt available evidence, or open the module to configure ----
function AdoptOrConfigureStage({ focus, onAdopt }: { focus: StageResolution; onAdopt: () => void }) {
  const complete = focus.status === "COMPLETE";
  const isExport = focus.number === 12;
  const route = focus.action.route || "/dashboard";
  const href = `${route}?from=mlb-workflow&step=${focus.number}`;
  const moduleLabel = focus.action.moduleLabel || "module";

  if (isExport) {
    return (
      <section className="sports-panel p-5 sm:p-6">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
          <div><div className="text-sm font-semibold text-slate-900">Export gate</div><p className="mt-1 max-w-2xl text-sm text-slate-600">Export requires a governed Model Graph &amp; Research Decision from Step 11. It will package the approved graph as an immutable bundle.</p></div>
          <button disabled className="inline-flex shrink-0 cursor-not-allowed items-center gap-2 rounded-xl bg-slate-200 px-4 py-2.5 text-sm font-semibold text-slate-500"><Lock size={15} /> Export MLB Bundle</button>
        </div>
      </section>
    );
  }

  if (complete) {
    return (
      <section className="sports-panel p-5 sm:p-6">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
          <div><div className="text-sm font-semibold text-slate-900">Adopted — evidence available for review</div><p className="mt-1 max-w-2xl text-sm text-slate-600">This project has adopted this stage's evidence. Open the {moduleLabel} to review it in full or continue.</p></div>
          <Link to={href} className="sports-dark-button shrink-0">Open {moduleLabel} <ExternalLink size={15} /></Link>
        </div>
      </section>
    );
  }

  if (focus.evidenceAvailable) {
    return (
      <section className="sports-panel p-5 sm:p-6">
        {focus.evidence.length > 0 && <ul className="mb-4 grid gap-1.5 text-sm text-slate-700">{focus.evidence.map((e) => <li key={e} className="flex gap-2"><CheckCircle2 size={15} className="mt-0.5 shrink-0 text-cyan-600" />{e}</li>)}</ul>}
        <div className="flex flex-wrap gap-3">
          <button onClick={onAdopt} className="sports-primary-button">{focus.action.label} <ArrowRight size={15} /></button>
          <Link to={href} className="sports-dark-button"><ExternalLink size={16} /> Open {moduleLabel}</Link>
        </div>
        <p className="mt-3 text-xs text-slate-500">Adopting references the registered research evidence for this project. Open the {moduleLabel} to inspect or extend it.</p>
      </section>
    );
  }

  // no reusable evidence — configuration required
  return (
    <section className="sports-panel p-5 sm:p-6">
      <div className="flex items-start gap-3 rounded-xl border border-slate-200 bg-slate-50 px-4 py-3">
        <TriangleAlert size={18} className="mt-0.5 shrink-0 text-amber-500" />
        <div><div className="text-sm font-semibold text-slate-800">This project has not adopted or materialized {focus.title.toLowerCase()} evidence yet.</div><p className="mt-1 text-sm text-slate-600">Open the {moduleLabel} to configure this stage. Your project context is preserved and you can return here.</p></div>
      </div>
      <Link to={href} className="sports-primary-button mt-4">Open {moduleLabel} to configure <ExternalLink size={15} /></Link>
    </section>
  );
}

function EvidenceBlock({ title, status, children }: { title: string; status: string; children: React.ReactNode }) {
  const pass = /pass|valid|ok/i.test(status);
  return (
    <div className="rounded-xl border border-slate-200 bg-slate-50 p-4">
      <div className="flex items-center justify-between"><div className="text-xs font-semibold uppercase tracking-wide text-slate-500">{title}</div><span className={`rounded-full border px-2 py-0.5 text-[11px] font-semibold ${pass ? "border-emerald-200 bg-emerald-50 text-emerald-700" : "border-amber-200 bg-amber-50 text-amber-700"}`}>{status}</span></div>
      <div className="mt-2 space-y-0.5">{children}</div>
    </div>
  );
}
function Line({ k, v }: { k: string; v: string }) {
  return <div className="flex items-center justify-between text-sm"><span className="text-slate-600">{k}</span><span className="font-semibold tabular-nums text-slate-900">{v}</span></div>;
}
