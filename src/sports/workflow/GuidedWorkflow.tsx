// Canonical scientist-first MLB PROGRAM workflow (Phase 6D): 9 stages. Stage 2 merges dataset
// preview + identity/leakage data-quality; Stage 3 embeds the full PA Modeling Cockpit. The
// route is /workflows/mlb?projectId=ID&stage=N (old ?step=N bookmarks map forward). No dead-end routes.
import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import {
  ArrowLeft, ArrowRight, CheckCircle2, CircleDashed, CircleDot, Info, Lock,
  PanelLeftClose, PanelLeftOpen, ExternalLink,
  Target, Database, FlaskConical, UsersRound, Orbit, SlidersHorizontal, Gauge, GitBranch, PackageCheck,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { useWorkflowStore } from "../../state/useWorkflowStore";
import { loadSportsProjectMetadata } from "../sportsConfig";
import { useSportsDatasetCatalog, type ActiveSportsDataset, type RefreshableEvidenceState } from "../sportsEvidenceApi";
import { canonicalSportsProjectId, sportsProjectOverviewRoute, SPORTS_PROJECT_ID_PARAM } from "../sportsProjectRoutes";
import {
  resolveStages, firstActionableStage, nextActionable, completionSummary,
  acceptStage2DataReview, adoptStage, PROGRAM_STAGE_COUNT, LEGACY_STEP_TO_STAGE,
  type DatasetBinding, type ForecastContract, type StageResolution, type StageStatus, type EvidenceState, type DecisionClass,
} from "./workflowState";
import { ForecastContractPanel } from "./ForecastContractPanel";
import { GuidedStageContent, AdoptBar } from "./GuidedStageContent";
import { useForecastContract, type ForecastContractState } from "./useForecastContract";
import { ProjectEvidenceDatasetControl } from "./ProjectEvidenceDatasetControl";
import { useProjectSportsEvidenceDataset, type ProjectSportsEvidenceState } from "./projectDatasetLinkage";
import { useCanonicalSportsProject } from "./useCanonicalSportsProject";
import { useProjectCurrentGoldDataReview, useProjectStage3DataAuthority, type CurrentGoldReviewState } from "./currentGoldDataReview";

const STEP_ICONS: LucideIcon[] = [Target, Database, FlaskConical, UsersRound, Orbit, SlidersHorizontal, Gauge, GitBranch, PackageCheck];

const STATUS_STYLE: Record<StageStatus, { chip: string; dot: string; label: string }> = {
  COMPLETE: { chip: "border-emerald-200 bg-emerald-50 text-emerald-800", dot: "bg-emerald-500", label: "Complete" },
  CURRENT: { chip: "border-cyan-300 bg-cyan-50 text-cyan-800", dot: "bg-cyan-500", label: "Current stage" },
  READY: { chip: "border-blue-200 bg-blue-50 text-blue-800", dot: "bg-blue-400", label: "Ready" },
  BLOCKED: { chip: "border-slate-200 bg-slate-100 text-slate-500", dot: "bg-slate-300", label: "Blocked" },
  STALE: { chip: "border-amber-200 bg-amber-50 text-amber-800", dot: "bg-amber-400", label: "Requires review" },
};
const EVIDENCE_BADGE: Partial<Record<EvidenceState, { label: string; cls: string }>> = {
  WORKSPACE_EVIDENCE_AVAILABLE: { label: "Existing workspace evidence available", cls: "border-cyan-200 bg-cyan-50 text-cyan-700" },
  PROJECT_STAGE_COMPLETE: { label: "Adopted by this project", cls: "border-emerald-200 bg-emerald-50 text-emerald-700" },
  NO_EVIDENCE: { label: "Not configured for this project", cls: "border-slate-200 bg-slate-50 text-slate-500" },
};
const CLASS_LABEL: Record<DecisionClass, string> = { CONFIGURE: "Configure", REVIEW_AND_DECIDE: "Review & decide", ANALYZE: "Analyze", DECIDE: "Decide", TERMINAL: "Terminal", BLOCKED: "Blocked" };

function stage2ReviewMatchesBinding(state: CurrentGoldReviewState, binding: DatasetBinding | null) {
  const review = state.review;
  return Boolean(
    state.status === "ready"
    && binding
    && review
    && review.projectId === binding.projectId
    && review.sourceAuthority.registrationId === binding.registrationId
    && review.sourceAuthority.datasetVersionId === binding.datasetVersionId
    && review.sourceAuthority.manifestSha === binding.manifestSha,
  );
}

function stage2AcceptanceReason(state: CurrentGoldReviewState, binding: DatasetBinding | null) {
  if (state.status === "loading" || state.status === "idle") return "Accept Data is locked while the exact project-linked Gold matrix is verified.";
  if (state.status === "error" || !state.review) return "Accept Data is locked because the project-scoped current Gold review is unavailable.";
  if (!stage2ReviewMatchesBinding(state, binding)) return "Accept Data is locked because the materialized matrix differs from the project-linked dataset.";
  if (!state.review.acceptance.allowed) return state.review.acceptance.blockers.join(" ") || "Accept Data is locked by an unresolved data-quality gate.";
  return undefined;
}

export default function GuidedWorkflow() {
  const [params, setParams] = useSearchParams();
  const stateProjectId = useWorkflowStore((s) => s.projectId);
  const projectId = canonicalSportsProjectId(params.get(SPORTS_PROJECT_ID_PARAM), stateProjectId);
  const projectIdentity = useCanonicalSportsProject(projectId, stateProjectId);
  const projectName = useWorkflowStore((s) => s.projectName);
  const datasetCatalog = useSportsDatasetCatalog();
  const projectDataset = useProjectSportsEvidenceDataset(projectId);
  const dataset = datasetCatalog.status === "ready" && projectDataset.linkage
    ? datasetCatalog.data.find((item) => item.registrationId === projectDataset.linkage?.registrationId) ?? null
    : null;
  const metadata = loadSportsProjectMetadata(projectId);
  const contractAuthority = useForecastContract(projectId);
  const contract = contractAuthority.contract;
  const binding = projectDataset.linkage ? {
    projectId,
    registrationId: projectDataset.linkage.registrationId,
    datasetId: projectDataset.linkage.datasetId,
    datasetVersionId: projectDataset.linkage.datasetVersionId,
    manifestSha: projectDataset.linkage.manifestSha,
    seasons: dataset?.seasons ?? [],
    boundAt: "",
  } : null;

  useEffect(() => {
    if (!projectId || params.get(SPORTS_PROJECT_ID_PARAM) === projectId) return;
    setParams((current) => {
      const next = new URLSearchParams(current);
      next.set(SPORTS_PROJECT_ID_PARAM, projectId);
      return next;
    }, { replace: true });
  }, [params, projectId, setParams]);

  // The backend contract is authoritative. A project-scoped compatibility draft may initialize
  // Stage 1, but it cannot make the stage complete until the user explicitly registers it.
  const resolutions = resolveStages(projectId, dataset, contract, binding);
  const summary = completionSummary(resolutions);
  // ?stage=N is canonical; old ?step=N bookmarks map forward.
  const legacyStep = Number(params.get("step")) || 0;
  const focusNumber = Number(params.get("stage")) || (legacyStep ? (LEGACY_STEP_TO_STAGE[legacyStep] || 1) : firstActionableStage(resolutions));
  const focus = resolutions.find((r) => r.number === focusNumber) || resolutions[0];
  const stage2CurrentGoldReview = useProjectCurrentGoldDataReview(projectId,
    Boolean(binding) && focus.number === 2,
  );
  const stage3CurrentGoldReview = useProjectStage3DataAuthority(projectId,
    Boolean(binding) && focus.number === 3,
  );
  const currentGoldReview = focus.number === 3 ? stage3CurrentGoldReview : stage2CurrentGoldReview;
  const justDone = Number(params.get("done")) || 0;
  const [navCollapsed, setNavCollapsed] = useState(false);
  const displayName = projectName && projectName !== "Untitled Sports Project" ? projectName : "MLB Plate Appearance Modeling";

  const goStage = (n: number) => setParams((p) => { const np = new URLSearchParams(p); np.set("stage", String(n)); np.delete("step"); np.delete("done"); return np; });
  const refresh = () => {
    datasetCatalog.refresh();
    void projectDataset.refresh();
    if (focus.number === 2 || focus.number === 3) void currentGoldReview.refresh();
    setParams((p) => { const np = new URLSearchParams(p); np.set("stage", String(focus.number)); np.delete("step"); np.set("v", String(Date.now())); return np; });
  };
  const advanceFrom = (from: number, registeredContract: ForecastContract | null = contract) => {
    const next = firstActionableStage(resolveStages(projectId, dataset, registeredContract, binding));
    setParams((p) => { const np = new URLSearchParams(p); np.set("stage", String(next)); np.delete("step"); np.set("done", String(from)); np.set("v", String(Date.now())); return np; });
  };

  if (projectIdentity.status !== "ready") {
    return <div className="sports-page-shell"><section className={`sports-panel p-6 text-sm ${projectIdentity.status === "error" ? "border-rose-200 bg-rose-50 text-rose-900" : "text-slate-600"}`} role={projectIdentity.status === "error" ? "alert" : "status"}>{projectIdentity.status === "error" ? projectIdentity.error : "Reopening the canonical ASP Model Studio sports project…"}</section></div>;
  }

  return (
    <div className={`sports-page-shell ${focus.number === 3 ? "space-y-2" : "space-y-5"}`} data-stage3-workspace={focus.number === 3 ? "true" : undefined}>
      {focus.number !== 3 ? <section className="sports-hero-panel p-5 sm:p-7">
        <div className="relative z-10">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <Link to={sportsProjectOverviewRoute(projectId)} className="inline-flex items-center gap-2 text-sm font-semibold text-slate-300 hover:text-white"><ArrowLeft size={16} /> Project Overview</Link>
            <span className="sports-status sports-status--teal">MLB · Program Workflow</span>
          </div>
          <div className="mt-6 grid gap-6 lg:grid-cols-[minmax(0,1fr)_320px] lg:items-end">
            <div>
              <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.16em] text-cyan-200"><CircleDot size={15} /> Stage {focus.number} of {PROGRAM_STAGE_COUNT} · {CLASS_LABEL[focus.decisionClass]}</div>
              <h1 className="mt-3 text-3xl font-semibold tracking-tight text-white sm:text-4xl">{displayName}</h1>
              <div className="mt-2 text-lg font-semibold text-cyan-100">{focus.title}</div>
              <p className="mt-3 max-w-3xl text-[15px] leading-7 text-slate-300">{focus.purpose}</p>
            </div>
            <div className="rounded-2xl border border-white/10 bg-white/[0.06] p-5 backdrop-blur">
              <div className="flex items-end justify-between"><span className="text-sm font-medium text-slate-300">Program completion</span><strong className="text-3xl tabular-nums text-white">{summary.complete}<span className="text-base text-slate-500">/{summary.total}</span></strong></div>
              <div className="mt-3 h-2 overflow-hidden rounded-full bg-white/10"><span className="block h-full rounded-full bg-gradient-to-r from-teal-400 to-cyan-300" style={{ width: `${summary.pct}%` }} /></div>
              <p className="mt-3 text-xs leading-5 text-slate-400">{summary.complete} complete · {summary.ready} ready · {summary.available} evidence available · {summary.blocked} blocked</p>
            </div>
          </div>
        </div>
      </section> : null}

      <div className={focus.number === 3 ? "min-w-0" : `grid gap-5 ${navCollapsed ? "lg:grid-cols-[64px_minmax(0,1fr)]" : "lg:grid-cols-[300px_minmax(0,1fr)]"}`}>
        {focus.number !== 3 ? <nav className="lg:sticky lg:top-4 lg:self-start" aria-label="Program stages">
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
                    <button onClick={() => goStage(r.number)} title={r.title} className={`flex w-full items-center gap-3 rounded-xl ${navCollapsed ? "justify-center px-1.5" : "px-3"} py-2.5 text-left transition ${active ? "bg-slate-900 text-white" : "hover:bg-slate-50"}`}>
                      <span className={`grid h-7 w-7 shrink-0 place-items-center rounded-lg text-xs font-bold tabular-nums ${r.status === "COMPLETE" ? "bg-emerald-100 text-emerald-700" : active ? "bg-cyan-400/20 text-cyan-200" : "bg-slate-100 text-slate-500"}`}>
                        {r.status === "COMPLETE" ? <CheckCircle2 size={15} /> : r.number}
                      </span>
                      {!navCollapsed && <>
                        <span className="min-w-0 flex-1">
                          <span className={`block truncate text-sm font-semibold ${active ? "text-white" : "text-slate-800"}`}>{r.title}</span>
                          <span className={`mt-0.5 flex items-center gap-1.5 text-[11px] ${active ? "text-slate-300" : "text-slate-400"}`}><span className={`h-1.5 w-1.5 rounded-full ${style.dot}`} />{avail && r.status !== "COMPLETE" ? "Evidence available" : style.label}</span>
                        </span>
                        {!active && <Icon size={15} className="shrink-0 text-slate-300" />}
                      </>}
                    </button>
                  </li>
                );
              })}
            </ol>
          </div>
        </nav> : null}

        <div className="min-w-0 space-y-4">
          <StageWorkspace key={focus.number} focus={focus} resolutions={resolutions} displayName={displayName} projectId={projectId} metadata={metadata} dataset={dataset} datasetCatalog={datasetCatalog} projectDataset={projectDataset} contractAuthority={contractAuthority} currentGoldReview={currentGoldReview} justDone={justDone} onGoStage={goStage} advanceFrom={advanceFrom} refresh={refresh} />

          {focus.number !== 3 ? <div className="flex items-center justify-between rounded-2xl border border-slate-200 bg-white px-4 py-3 shadow-sm">
            <button onClick={() => goStage(Math.max(1, focus.number - 1))} disabled={focus.number === 1} className="inline-flex items-center gap-2 rounded-lg border border-slate-300 px-3 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50 disabled:opacity-40"><ArrowLeft size={15} /> Previous</button>
            <span className="text-xs font-semibold uppercase tracking-wide text-slate-500">Stage {focus.number} of {PROGRAM_STAGE_COUNT}</span>
            {focus.number === PROGRAM_STAGE_COUNT ? <span className="text-xs font-semibold text-slate-400">End of workflow</span> : (
              <div className="flex flex-col items-end">
                <button onClick={() => goStage(nextActionable(resolutions, focus.number))} disabled={focus.status !== "COMPLETE"} className="inline-flex items-center gap-2 rounded-lg bg-cyan-600 px-4 py-2 text-sm font-semibold text-white hover:bg-cyan-500 disabled:cursor-not-allowed disabled:bg-slate-200 disabled:text-slate-400">Continue <ArrowRight size={15} /></button>
                {focus.status !== "COMPLETE" && <span className="mt-1 text-[11px] text-slate-400">Complete this stage to continue</span>}
              </div>
            )}
          </div> : null}
        </div>
      </div>
    </div>
  );
}

function StageWorkspace({
  focus, resolutions, displayName, projectId, metadata, dataset, datasetCatalog, projectDataset, contractAuthority, currentGoldReview, justDone, onGoStage, advanceFrom, refresh,
}: {
  focus: StageResolution;
  resolutions: StageResolution[];
  displayName: string;
  projectId: string;
  metadata: ReturnType<typeof loadSportsProjectMetadata>;
  dataset: ActiveSportsDataset | null;
  datasetCatalog: RefreshableEvidenceState<ActiveSportsDataset[]>;
  projectDataset: ProjectSportsEvidenceState;
  contractAuthority: ForecastContractState;
  currentGoldReview: CurrentGoldReviewState;
  justDone: number;
  onGoStage: (n: number) => void;
  advanceFrom: (from: number, registeredContract?: ForecastContract | null) => void;
  refresh: () => void;
}) {
  const style = STATUS_STYLE[focus.status];
  const binding = projectDataset.linkage ? {
    projectId,
    registrationId: projectDataset.linkage.registrationId,
    datasetId: projectDataset.linkage.datasetId,
    datasetVersionId: projectDataset.linkage.datasetVersionId,
    manifestSha: projectDataset.linkage.manifestSha,
    seasons: dataset?.seasons ?? [],
    boundAt: "",
  } : null;
  const contract = contractAuthority.contract;
  const formContract = contract ?? contractAuthority.compatibilityDraft;
  const contractFormKey = `${projectId}:${formContract?.version ?? "new"}:${formContract?.savedAt || formContract?.temporalDesignMode || "empty"}`;

  if (focus.status === "BLOCKED") {
    return (
      <section className="sports-panel p-6">
        <span className={`sports-status ${style.chip}`}>Blocked</span>
        <h2 className="mt-3 text-2xl font-semibold text-slate-950">{focus.title}</h2>
        <div className="mt-4 flex items-start gap-3 rounded-xl border border-slate-200 bg-slate-50 px-4 py-3">
          <Lock size={18} className="mt-0.5 shrink-0 text-slate-400" />
          <div><div className="text-sm font-semibold text-slate-800">This stage is not available yet.</div><p className="mt-1 text-sm text-slate-600">{focus.blockedReason}</p></div>
        </div>
        <button onClick={() => onGoStage(focus.blockedByNumber || 1)} className="sports-primary-button mt-5">Go to Stage {focus.blockedByNumber} <ArrowRight size={16} /></button>
      </section>
    );
  }

  const badge = EVIDENCE_BADGE[focus.evidenceState];
  return (
    <div className="space-y-4">
      {justDone > 0 && justDone < focus.number && (
        <div className="flex items-center gap-2 rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-2.5 text-sm font-semibold text-emerald-800">
          <CheckCircle2 size={16} /> Stage {justDone} complete — advanced to Stage {focus.number}.
        </div>
      )}

      {focus.number !== 3 ? <section className="sports-panel p-5 sm:p-6">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.14em] text-cyan-700">Stage {focus.number} · {CLASS_LABEL[focus.decisionClass]} · {focus.estMinutes}</div>
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
      </section> : null}

      {/* Stage 1 — Forecast contract */}
      {focus.number === 1 && <>
        <ProjectEvidenceDatasetControl
          authority={projectDataset}
          catalog={datasetCatalog}
          onLinked={async () => { await contractAuthority.refresh(); refresh(); }}
        />
        {contractAuthority.status === "loading"
          ? <section className="sports-panel p-6 text-sm text-slate-500"><CircleDashed size={20} className="mr-2 inline animate-spin" /> Loading the backend forecast-contract authority…</section>
          : <ForecastContractPanel
            key={contractFormKey}
            projectId={projectId}
            metadata={metadata}
            existing={formContract}
            coverage={contractAuthority.coverage}
            authorityStatus={contractAuthority.status}
            authorityError={contractAuthority.error}
            authorityErrorCode={contractAuthority.errorCode}
            onRegister={async (draft) => {
              const registered = await contractAuthority.register(draft);
              advanceFrom(1, registered);
            }}
          />}
      </>}

      {/* Stage 2 — Data Evidence & Quality (bind, then review data + quality, then accept) */}
      {focus.number === 2 && (!binding
        ? <ProjectEvidenceDatasetControl authority={projectDataset} catalog={datasetCatalog} onLinked={() => refresh()} />
        : <>
            <GuidedStageContent number={2} dataset={dataset} contract={contract} currentGoldReview={currentGoldReview} />
            <AdoptBar
              focus={focus}
              projectId={projectId}
              disabled={!stage2ReviewMatchesBinding(currentGoldReview, binding) || !currentGoldReview.review?.acceptance.allowed}
              disabledReason={stage2AcceptanceReason(currentGoldReview, binding)}
              onAdopt={() => {
                if (!currentGoldReview.review) return;
                acceptStage2DataReview(projectId, binding, currentGoldReview.review);
                advanceFrom(2);
              }}
            />
          </>)}

      {/* Stage 3 — PA Model Development (embedded cockpit) */}
      {focus.number === 3 && <>
        <GuidedStageContent number={3} dataset={dataset} contract={contract} currentGoldReview={currentGoldReview} programStages={resolutions} onGoProgramStage={onGoStage} projectName={displayName} />
        <section className="sports-panel flex flex-col gap-3 p-4 sm:flex-row sm:items-center sm:justify-between" data-testid="stage3-no-champion-gate">
          <div><div className="text-sm font-semibold text-slate-900">Project champion: None yet</div><p className="mt-1 text-sm text-slate-600">Stage 3 remains open until chronological model development produces a separately governed selection decision. This population handoff does not fit, score, promote, or adopt a legacy artifact.</p></div>
          <span className="inline-flex shrink-0 items-center gap-1.5 rounded-lg border border-cyan-200 bg-cyan-50 px-3 py-2 text-sm font-semibold text-cyan-900"><Lock size={14} /> Project-bound development only · no promotion</span>
        </section>
      </>}

      {/* Stages 4–8 — embedded analytical content + adopt */}
      {focus.number >= 4 && focus.number <= 8 && <>
        <GuidedStageContent number={focus.number} dataset={dataset} contract={contract} />
        <AdoptBar focus={focus} projectId={projectId} onAdopt={() => { adoptStage(projectId, focus.number); advanceFrom(focus.number); }} />
      </>}

      {/* Stage 9 — Export / Deployment (gated) */}
      {focus.number === 9 && (
        <section className="sports-panel p-5 sm:p-6">
          <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
            <div><div className="text-sm font-semibold text-slate-900">Export gate</div><p className="mt-1 max-w-2xl text-sm text-slate-600">Export requires a governed Champion Decision from Stage 8. It packages the approved graph as an immutable bundle.</p></div>
            <button disabled className="inline-flex shrink-0 cursor-not-allowed items-center gap-2 rounded-xl bg-slate-200 px-4 py-2.5 text-sm font-semibold text-slate-500"><Lock size={15} /> Export MLB Bundle</button>
          </div>
          <Link to={`/registry-deployment?${new URLSearchParams({ from: "mlb-workflow", stage: "9", projectId }).toString()}`} className="mt-4 inline-flex items-center gap-1.5 text-sm font-semibold text-cyan-700 hover:underline"><ExternalLink size={14} /> Open Registry &amp; Deployment</Link>
        </section>
      )}

      {focus.status === "COMPLETE" && focus.evidence.length > 0 && (
        <section className="sports-panel p-5">
          <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-emerald-700"><CheckCircle2 size={14} /> Adopted project evidence</div>
          <ul className="mt-3 grid gap-1.5 text-sm text-slate-700">{focus.evidence.map((e) => <li key={e} className="flex gap-2"><CheckCircle2 size={15} className="mt-0.5 shrink-0 text-emerald-500" />{e}</li>)}</ul>
        </section>
      )}
    </div>
  );
}
