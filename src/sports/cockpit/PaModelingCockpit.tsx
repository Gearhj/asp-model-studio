import { getCachedUserId, subscribeCachedUserId } from "../../lib/authSession";
// Interactive MLB PA Modeling Cockpit — the 15-step scientist workbench shell.
import { useCallback, useEffect, useRef, useState, useSyncExternalStore, type CSSProperties, type ReactNode, type RefObject } from "react";
import {
  Target, Database, ScanSearch, TriangleAlert, CircleSlash, Wand2, Boxes, CalendarClock,
  FlaskConical, BarChart3, Gauge, Orbit, Trophy, ClipboardList, Cpu, Scissors,
  ChevronLeft, ChevronRight, Check, CloudOff, RefreshCw, Loader2, Menu, ShieldCheck, Lock, DatabaseZap,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { CockpitProjectContext, useCockpitStore } from "./cockpitApi";
import { useCockpitPersistence, type AutosaveStatus } from "./cockpitPersistence";
import { useProjectStage3DataAuthority, type CurrentGoldDataReview, type CurrentGoldReviewState } from "../workflow/currentGoldDataReview";
import type { StageResolution } from "../workflow/workflowState";
import { ProjectBoundLaterStepGate } from "./ProjectBoundStage3";
import { ProjectBoundDataProfile } from "./ProjectBoundDataProfile";
import { ProjectBoundOutlierStudio } from "./ProjectBoundOutlierStudio";
import { ProjectBoundMissingStudio } from "./ProjectBoundMissingStudio";
import { ProjectBoundFeatureEngineering } from "./ProjectBoundFeatureEngineering";
import { ProjectBoundSplitBalance } from "./ProjectBoundSplitBalance";
import { ProjectBoundWorkflowGate } from "./ProjectBoundWorkflowGate";
import { ProjectBoundModelLab } from "./ProjectBoundModelLab";
import { ProjectBoundCandidateEvaluation } from "./ProjectBoundCandidateEvaluation";
import { ProjectBoundModelRefinement } from "./ProjectBoundModelRefinement";
import {
  ProjectBoundCalibration,
  ProjectBoundGameEvaluation,
  ProjectBoundChampionDecision,
  ProjectBoundRegistryHandoff,
} from "./ProjectBoundDownstreamWorkflow";
import { CockpitDrawer } from "./CockpitDrawer";
import { useStage3FocusMode } from "./stage3FocusMode";
import {
  ObjectiveStep, DataPopulationStep, ProfileStep, OutliersStep, MissingStep,
  FeatureEngineeringStep, SegmentationStep, TemporalSplitStep,
} from "./cockpitSteps1";
import {
  ModelLabStep, EvaluationStep, CalibrationStep, SimulationStep,
  ChampionChallengerStep, RegistryStep,
} from "./cockpitSteps2";

type StepCtx = { projectId: string; go: (id: string) => void; currentGoldReview?: CurrentGoldReviewState };
type Step = { id: string; n: string; label: string; icon: LucideIcon; group: string; render: (ctx: StepCtx) => JSX.Element };

const STEPS: Step[] = [
  { id: "objective", n: "01", label: "Objective", icon: Target, group: "Frame", render: (c) => <ObjectiveStep projectId={c.projectId} go={c.go} currentGoldReview={c.currentGoldReview} /> },
  { id: "population", n: "02", label: "Data & Population", icon: Database, group: "Frame", render: (c) => <DataPopulationStep projectId={c.projectId} go={c.go} currentGoldReview={c.currentGoldReview} /> },
  { id: "profile", n: "03", label: "Data Profile", icon: ScanSearch, group: "Understand", render: (c) => c.currentGoldReview ? <ProjectBoundDataProfile state={c.currentGoldReview} projectId={c.projectId} go={c.go} /> : <ProfileStep /> },
  { id: "outliers", n: "04", label: "Outliers", icon: TriangleAlert, group: "Prepare", render: (c) => c.currentGoldReview ? <ProjectBoundOutlierStudio state={c.currentGoldReview} projectId={c.projectId} go={c.go} /> : <OutliersStep /> },
  { id: "missing", n: "05", label: "Missing Values", icon: CircleSlash, group: "Prepare", render: (c) => c.currentGoldReview ? <ProjectBoundMissingStudio state={c.currentGoldReview} projectId={c.projectId} go={c.go} /> : <MissingStep /> },
  { id: "features", n: "06", label: "Feature Engineering", icon: Wand2, group: "Prepare", render: (c) => c.currentGoldReview ? <ProjectBoundFeatureEngineering state={c.currentGoldReview} projectId={c.projectId} go={c.go} /> : <FeatureEngineeringStep /> },
  { id: "segmentation", n: "07", label: "Player Segmentation", icon: Boxes, group: "Prepare", render: (c) => c.currentGoldReview ? <ProjectBoundLaterStepGate state={c.currentGoldReview} stepLabel="Player Segmentation" /> : <SegmentationStep /> },
  { id: "split", n: "08", label: "Split & Balance", icon: CalendarClock, group: "Prepare", render: (c) => c.currentGoldReview ? <ProjectBoundSplitBalance state={c.currentGoldReview} projectId={c.projectId} go={c.go} /> : <TemporalSplitStep /> },
  { id: "modellab", n: "09", label: "Model Development Laboratory", icon: FlaskConical, group: "Model", render: (c) => c.currentGoldReview ? <ProjectBoundModelLab projectId={c.projectId} go={c.go} /> : <ModelLabStep projectId={c.projectId} /> },
  { id: "evaluation", n: "10", label: "Candidate Evaluation", icon: BarChart3, group: "Assess", render: (c) => c.currentGoldReview ? <ProjectBoundCandidateEvaluation projectId={c.projectId} go={c.go} /> : <EvaluationStep projectId={c.projectId} /> },
  { id: "refinement", n: "11", label: "Model Refinement & Explainability", icon: Scissors, group: "Assess", render: (c) => c.currentGoldReview ? <ProjectBoundModelRefinement projectId={c.projectId} go={c.go} /> : <section className="rounded-2xl border border-slate-200 bg-white p-6 text-sm text-slate-600">Model Refinement becomes available after project-bound Candidate Evaluation.</section> },
  { id: "calibration", n: "12", label: "Calibration", icon: Gauge, group: "Assess", render: (c) => c.currentGoldReview ? <ProjectBoundCalibration projectId={c.projectId} go={c.go} /> : <CalibrationStep projectId={c.projectId} /> },
  { id: "simulation", n: "13", label: "Simulation & Game-Level Evaluation", icon: Orbit, group: "Assess", render: (c) => c.currentGoldReview ? <ProjectBoundGameEvaluation projectId={c.projectId} go={c.go} /> : <SimulationStep projectId={c.projectId} /> },
  { id: "champion", n: "14", label: "Champion / Challenger Decision", icon: Trophy, group: "Decide", render: (c) => c.currentGoldReview ? <ProjectBoundChampionDecision projectId={c.projectId} go={c.go} /> : <ChampionChallengerStep projectId={c.projectId} /> },
  { id: "registry", n: "15", label: "Registry, Export & Implementation", icon: ClipboardList, group: "Decide", render: (c) => c.currentGoldReview ? <ProjectBoundRegistryHandoff projectId={c.projectId} go={c.go} /> : <RegistryStep projectId={c.projectId} /> },
];

export default function PaModelingCockpit({
  embedded = false,
  projectId = "",
  currentGoldReview,
  programStages = [],
  onGoProgramStage,
  projectName = "MLB Plate-Appearance Modeling",
}: {
  embedded?: boolean;
  projectId?: string;
  currentGoldReview?: CurrentGoldReviewState;
  programStages?: StageResolution[];
  onGoProgramStage?: (number: number) => void;
  projectName?: string;
} = {}) {
  const requestedStep = new URLSearchParams(window.location.search).get("stage3Step");
  const [active, setActive] = useState(() => STEPS.find((item) => item.id === requestedStep)?.id ?? "objective");
  const [workflowNavigatorOpen, setWorkflowNavigatorOpen] = useState(false);
  const [authorityOpen, setAuthorityOpen] = useState(false);
  const { savedSteps, lastResult } = useCockpitStore();
  const restorePersistedStep = useCallback((id: string) => {
    if (!new URLSearchParams(window.location.search).has("stage3Step")) setActive(id === "tuning" ? "modellab" : id);
  }, []);
  const userId = useSyncExternalStore(subscribeCachedUserId, getCachedUserId, getCachedUserId);
  const autosave = useCockpitPersistence(projectId, active, restorePersistedStep);
  const modelingFocus = useStage3FocusMode();
  const step = STEPS.find((s) => s.id === active) ?? STEPS[0];
  const selectedAuthority = useProjectStage3DataAuthority(projectId, Boolean(currentGoldReview) && Number(step.n) < 9);
  if (currentGoldReview) currentGoldReview = selectedAuthority;
  const workspaceRef = useRef<HTMLDivElement>(null);
  const headerRef = useRef<HTMLElement>(null);
  const contentRef = useRef<HTMLDivElement>(null);
  const [headerHeight, setHeaderHeight] = useState(84);
  const workflowTriggerRef = useRef<HTMLButtonElement>(null);
  const authorityTriggerRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    const header = headerRef.current;
    if (!header) return undefined;
    const synchronizeHeight = () => setHeaderHeight(Math.ceil(header.getBoundingClientRect().height));
    synchronizeHeight();
    if (typeof ResizeObserver === "undefined") return undefined;
    const observer = new ResizeObserver(synchronizeHeight);
    observer.observe(header);
    return () => observer.disconnect();
  }, []);

  // Internal step navigation: swaps the rendered step only. Experiment state lives in the zustand
  // store (config / savedSteps / lastResult), so Previous/Next never reload the app or lose selections.
  const currentLocation = new URL(window.location.href);
  useEffect(() => {
    const restoreHistoryStep = () => {
      const id = new URLSearchParams(window.location.search).get("stage3Step");
      if (id && STEPS.some((item) => item.id === id)) setActive(id);
    };
    window.addEventListener("popstate", restoreHistoryStep);
    return () => window.removeEventListener("popstate", restoreHistoryStep);
  }, []);
  const go = (id: string) => {
    setActive(id);
    currentLocation.searchParams.set("stage3Step", id);
    window.history.pushState(window.history.state, "", currentLocation);
    // Defer until React has committed the requested step, then align the analytical canvas using
    // its shared scroll margin. This prevents the sticky app + Stage 3 chrome from covering the
    // first card without adding page-specific padding.
    requestAnimationFrame(() => {
      contentRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    });
  };

  const workspaceStyle = {
    "--stage3-compact-header-height": `${headerHeight}px`,
  } as CSSProperties;

  return (
    <div
      ref={workspaceRef}
      className="stage3-focus-workspace min-w-0 max-w-full space-y-3 overflow-x-clip pb-10"
      style={workspaceStyle}
      data-testid="stage3-focus-workspace"
      data-focus-mode={modelingFocus.focusModeEnabled ? "active" : "inactive"}
      data-embedded={embedded ? "true" : "false"}
    >
      <Stage3CompactHeader
        headerRef={headerRef}
        projectName={projectName}
        step={step}
        review={currentGoldReview?.review ?? null}
        autosave={autosave}
        focusMode={modelingFocus.focusModeEnabled}
        toggleFocus={modelingFocus.toggleFocusMode}
        openWorkflow={() => setWorkflowNavigatorOpen(true)}
        openAuthority={() => setAuthorityOpen(true)}
        workflowTriggerRef={workflowTriggerRef}
        authorityTriggerRef={authorityTriggerRef}
      />

      <main className="stage3-scroll-target min-w-0 max-w-full" ref={contentRef} data-testid="stage3-analytical-canvas">
        <CockpitProjectContext.Provider key={`${userId}:${projectId}`} value={projectId}>{currentGoldReview && Number(step.n) >= 9 ? <ProjectBoundWorkflowGate key={projectId} projectId={projectId} stepLabel={step.label}>{step.render({ projectId, go, currentGoldReview })}</ProjectBoundWorkflowGate> : step.render({ projectId, go, currentGoldReview })}</CockpitProjectContext.Provider>
        <StepFooter
          active={active}
          go={go}
          suppressNext={Boolean(currentGoldReview) && ["calibration", "simulation", "champion"].includes(active)}
        />
      </main>

      <CockpitDrawer open={workflowNavigatorOpen} onClose={() => setWorkflowNavigatorOpen(false)} title="Workflow navigator" description="All nine program stages and all fifteen Stage 3 steps remain available without occupying the analytical canvas." eyebrow="MLB modeling workflow" returnFocusRef={workflowTriggerRef} side="left" widthClassName="max-w-3xl" testId="stage3-workflow-navigator">
        <WorkflowNavigator programStages={programStages} activeStep={active} savedSteps={savedSteps} hasResult={Boolean(lastResult)} projectBound={Boolean(currentGoldReview)} goProgram={(number) => { onGoProgramStage?.(number); setWorkflowNavigatorOpen(false); }} goStep={(id) => { go(id); setWorkflowNavigatorOpen(false); }} />
      </CockpitDrawer>

      <CockpitDrawer open={authorityOpen} onClose={() => setAuthorityOpen(false)} title="Authority & Audit" description="Project-bound identities, manifests, feature contracts, reconciliation, lineage, and scientific safeguards." eyebrow="Read-only governance evidence" returnFocusRef={authorityTriggerRef} widthClassName="max-w-4xl" testId="stage3-authority-audit-drawer">
        {currentGoldReview?.review ? <Stage3AuthorityAudit review={currentGoldReview.review} /> : <p className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">The current workflow panel shows verified project metadata and prerequisites. Row-level authority is not loaded automatically in downstream views.</p>}
      </CockpitDrawer>
    </div>
  );
}

function Stage3CompactHeader({
  headerRef,
  projectName,
  step,
  review,
  autosave,
  focusMode,
  toggleFocus,
  openWorkflow,
  openAuthority,
  workflowTriggerRef,
  authorityTriggerRef,
}: {
  headerRef: RefObject<HTMLElement>;
  projectName: string;
  step: Step;
  review: CurrentGoldDataReview | null;
  autosave: ReturnType<typeof useCockpitPersistence>;
  focusMode: boolean;
  toggleFocus: () => void;
  openWorkflow: () => void;
  openAuthority: () => void;
  workflowTriggerRef: RefObject<HTMLButtonElement>;
  authorityTriggerRef: RefObject<HTMLButtonElement>;
}) {
  const developmentRows = review?.matrix.development.rows;
  const ootRows = review?.matrix.finalOot.rows;
  const pitStatus = review?.pointInTimeReview.status ?? "NOT_RECOMPUTED";
  const goldName = review?.goldAuthority.datasetId || "See project metadata";

  return (
    <header
      ref={headerRef}
      className="sticky top-0 z-40 overflow-hidden rounded-xl border border-slate-200 bg-white/95 shadow-sm backdrop-blur lg:h-[84px]"
      style={{ top: "var(--stage3-shell-chrome-offset, 0px)" }}
      data-testid="stage3-compact-header"
    >
      <div className="flex min-h-11 min-w-0 items-center gap-2 border-b border-slate-100 px-2.5 py-1.5 sm:px-3">
        <button
          ref={workflowTriggerRef}
          type="button"
          onClick={openWorkflow}
          aria-label="Open workflow navigator"
          className="inline-flex min-w-0 items-center gap-2 rounded-lg border border-slate-200 bg-slate-50 px-2.5 py-1.5 text-left hover:border-cyan-300 hover:bg-cyan-50 focus:outline-none focus:ring-2 focus:ring-cyan-500"
        >
          <Menu size={15} className="shrink-0 text-cyan-700" aria-hidden="true" />
          <span className="min-w-0">
            <span className="block truncate text-[10px] font-semibold uppercase tracking-[0.1em] text-slate-500">Stage 3 of 9 · PA Model Development</span>
            <span className="block truncate text-xs font-semibold text-slate-950">Step {Number(step.n)} of {STEPS.length} · {step.label}</span>
          </span>
        </button>
        <div className="hidden min-w-0 flex-1 sm:block">
          <div className="truncate text-xs font-semibold text-slate-950">{shortProjectName(projectName)}</div>
          <div className="truncate text-[10px] text-slate-500">Project-bound analytical workspace</div>
        </div>
        <AutosaveBadge status={autosave.status} lastSavedAt={autosave.lastSavedAt} onRetry={autosave.retry} />
        <button
          type="button"
          onClick={toggleFocus}
          aria-pressed={focusMode}
          className={`inline-flex shrink-0 rounded-lg border px-2 py-1.5 text-[11px] font-semibold sm:px-2.5 sm:text-xs ${focusMode ? "border-cyan-300 bg-cyan-50 text-cyan-800" : "border-slate-200 bg-white text-slate-600"}`}
        >
          <span className="hidden sm:inline">Focus Mode&nbsp;</span><span className="sm:hidden">Focus&nbsp;</span>{focusMode ? "On" : "Off"}
        </button>
        <button
          ref={authorityTriggerRef}
          type="button"
          onClick={openAuthority}
          className="inline-flex shrink-0 items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-2.5 py-1.5 text-xs font-semibold text-slate-700 hover:border-cyan-300 hover:text-cyan-800 focus:outline-none focus:ring-2 focus:ring-cyan-500"
        >
          <ShieldCheck size={14} aria-hidden="true" /> <span className="hidden md:inline">Authority &amp; Audit</span><span className="md:hidden">Audit</span>
        </button>
      </div>
      <div className="flex min-h-9 items-center gap-1.5 overflow-x-auto px-2.5 py-1.5 text-[10px] font-semibold sm:px-3" aria-label="Modeling authority summary">
        <CompactFact label="Development" value={developmentRows === undefined ? "See verified view" : `${formatInteger(developmentRows)} rows`} tone="cyan" />
        <CompactFact label="Final OOT" value={ootRows === undefined ? "Locked" : `${formatInteger(ootRows)} locked`} tone="slate" icon={<Lock size={10} />} />
        <CompactFact label="Gold" value={goldName} tone="amber" />
        <CompactFact label="Point-in-time" value={pitStatus.replaceAll("_", " ")} tone={pitStatus === "FAIL" ? "rose" : pitStatus === "REVIEW" ? "amber" : "emerald"} />
        <CompactFact label="Models" value={review ? `${review.goldAuthority.modelsFitted} fit · ${review.goldAuthority.modelPromoted ? "promoted" : "0 promoted"}` : "See project evidence"} tone="slate" />
      </div>
    </header>
  );
}

function CompactFact({ label, value, tone, icon }: { label: string; value: string; tone: "cyan" | "slate" | "amber" | "emerald" | "rose"; icon?: JSX.Element }) {
  const styles = {
    cyan: "border-cyan-200 bg-cyan-50 text-cyan-800",
    slate: "border-slate-200 bg-slate-50 text-slate-700",
    amber: "border-amber-200 bg-amber-50 text-amber-900",
    emerald: "border-emerald-200 bg-emerald-50 text-emerald-800",
    rose: "border-rose-200 bg-rose-50 text-rose-800",
  }[tone];
  return <span className={`inline-flex shrink-0 items-center gap-1 rounded-full border px-2 py-1 ${styles}`}><span className="text-slate-500">{label}</span>{icon}<span className="max-w-64 truncate">{value}</span></span>;
}

function WorkflowNavigator({
  programStages,
  activeStep,
  savedSteps,
  hasResult,
  projectBound,
  goProgram,
  goStep,
}: {
  programStages: StageResolution[];
  activeStep: string;
  savedSteps: Record<string, boolean>;
  hasResult: boolean;
  projectBound: boolean;
  goProgram: (number: number) => void;
  goStep: (id: string) => void;
}) {
  return (
    <div className="grid min-h-full gap-0 md:grid-cols-2" data-testid="merged-stage3-navigator">
      <nav className="border-b border-slate-200 p-4 md:border-b-0 md:border-r" aria-label="MLB program stages">
        <div className="mb-3 text-xs font-semibold uppercase tracking-[0.12em] text-slate-500">Program · 9 stages</div>
        <ol className="space-y-1.5">
          {programStages.map((stage) => {
            const status = programStageLabel(stage);
            return (
              <li key={stage.id}>
                <button type="button" onClick={() => goProgram(stage.number)} className={`flex w-full min-w-0 items-center gap-2 rounded-lg border px-2.5 py-2 text-left hover:border-cyan-300 hover:bg-cyan-50 ${stage.number === 3 ? "border-cyan-300 bg-cyan-50" : "border-slate-200 bg-white"}`}>
                  <span className="grid h-6 w-6 shrink-0 place-items-center rounded-md bg-slate-900 text-[10px] font-bold text-white">{stage.number}</span>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-xs font-semibold text-slate-900">{stage.title}</span>
                    <span className="block truncate text-[10px] text-slate-500">{status}</span>
                  </span>
                </button>
              </li>
            );
          })}
          {!programStages.length ? <li className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs text-amber-900">Program-stage authority is not available on this standalone route.</li> : null}
        </ol>
      </nav>
      <nav className="p-4" aria-label="Stage 3 modeling steps">
        <div className="mb-3 text-xs font-semibold uppercase tracking-[0.12em] text-slate-500">Stage 3 · {STEPS.length} steps</div>
        <ol className="space-y-1.5">
          {STEPS.map((candidate, index) => {
            const status = cockpitStepStatus(candidate, index, activeStep, savedSteps, hasResult, projectBound);
            const Icon = candidate.icon;
            return (
              <li key={candidate.id}>
                <button type="button" onClick={() => goStep(candidate.id)} aria-current={candidate.id === activeStep ? "step" : undefined} className={`flex w-full min-w-0 items-center gap-2 rounded-lg border px-2.5 py-2 text-left hover:border-cyan-300 hover:bg-cyan-50 ${candidate.id === activeStep ? "border-cyan-300 bg-cyan-50" : "border-slate-200 bg-white"}`}>
                  <Icon size={15} className="shrink-0 text-cyan-700" aria-hidden="true" />
                  <span className="min-w-0 flex-1 truncate text-xs font-semibold text-slate-900">{candidate.n} · {candidate.label}</span>
                  <span className="shrink-0 text-[10px] font-medium text-slate-500">{status}</span>
                </button>
              </li>
            );
          })}
        </ol>
      </nav>
    </div>
  );
}

function Stage3AuthorityAudit({ review }: { review: CurrentGoldDataReview }) {
  return (
    <div className="space-y-4 p-4 sm:p-5" data-testid="stage3-authority-audit">
      <AuditSection title="Project-linked source authority" icon={<DatabaseZap size={16} />}>
        <AuditGrid rows={[
          ["Registration", review.sourceAuthority.registrationId],
          ["Dataset", review.sourceAuthority.datasetId],
          ["Dataset version", review.sourceAuthority.datasetVersionId],
          ["Source manifest", review.sourceAuthority.manifestSha],
          ["Silver publication", review.sourceAuthority.silverPublicationManifestSha],
          ["Coverage", `${review.sourceAuthority.dateCoverage.earliestDate} through ${review.sourceAuthority.dateCoverage.latestDate}`],
        ]} />
      </AuditSection>
      <AuditSection title="Current Gold authority" icon={<ShieldCheck size={16} />}>
        <AuditGrid rows={[
          ["Dataset", review.goldAuthority.datasetId],
          ["Manifest", review.goldAuthority.manifestSha],
          ["Contract", `${review.goldAuthority.manifestContract} v${review.goldAuthority.manifestVersion}`],
          ["Status", review.goldAuthority.status],
          ["Population", `${formatInteger(review.goldAuthority.rowCount)} rows · ${review.goldAuthority.featureCount} ordered predictors`],
          ["Source Silver", review.goldAuthority.sourceSilverManifestSha],
          ["Review digest", review.reviewDigest],
          ["Model activity", `${review.goldAuthority.modelsFitted} fits · ${review.goldAuthority.modelPromoted ? "promotion recorded" : "0 promotions"}`],
        ]} />
      </AuditSection>
      <AuditSection title="Population reconciliation" icon={<Database size={16} />}>
        <AuditGrid rows={[
          ["Source", `${formatInteger(review.populationReconciliation.sourceRows)} rows`],
          ["Gold", `${formatInteger(review.populationReconciliation.goldRows)} rows`],
          ["Excluded", `${formatInteger(review.populationReconciliation.excludedRows)} rows`],
          ["Reason authority", review.populationReconciliation.exclusionReasonStatus.replaceAll("_", " ")],
          ["Membership SHA-256", review.populationReconciliation.membershipEvidence?.identitySetSha256 || "Not supplied in redacted Stage 3 authority"],
        ]} />
        <div className="mt-3 grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
          {review.populationReconciliation.bySeason.map((season) => <div key={season.season} className="rounded-lg border border-slate-200 bg-slate-50 p-2 text-xs"><span className="font-semibold text-slate-900">{season.season}</span><div className="mt-1 text-slate-600">{formatInteger(season.goldRows)} Gold · {formatInteger(season.excludedRows)} excluded</div></div>)}
        </div>
      </AuditSection>
      <AuditSection title="Frozen temporal contract" icon={<Lock size={16} />}>
        <AuditGrid rows={[
          ["Development", `${review.matrix.development.startDate} through ${review.matrix.development.endDate} · ${formatInteger(review.matrix.development.rows)} rows`],
          ["Final OOT", `${review.matrix.finalOot.startDate} through ${review.matrix.finalOot.endDate} · ${formatInteger(review.matrix.finalOot.rows)} rows · targets locked`],
          ["Point-in-time", `${review.pointInTimeReview.status} · ${review.pointInTimeReview.detail}`],
          ["Leakage gate", `${review.leakageGate.status} · ${review.leakageGate.detail}`],
        ]} />
        <div className="mt-3 space-y-1.5">
          {review.checks.map((check) => <div key={check.code} className={`rounded-lg border px-2.5 py-2 text-xs ${check.status === "FAIL" ? "border-rose-200 bg-rose-50 text-rose-900" : check.status === "REVIEW" ? "border-amber-200 bg-amber-50 text-amber-900" : "border-emerald-200 bg-emerald-50 text-emerald-900"}`}><span className="font-semibold">{check.code} · {check.status}</span> — {check.detail}</div>)}
        </div>
      </AuditSection>
      <AuditSection title={`Exact ordered feature contract · ${review.matrix.orderedPredictors.length}`} icon={<ClipboardList size={16} />}>
        <ol className="grid gap-1.5 sm:grid-cols-2">
          {review.matrix.orderedPredictors.map((feature, index) => <li key={feature} className="flex min-w-0 gap-2 rounded-md border border-slate-200 bg-white px-2 py-1.5 text-xs"><span className="w-6 shrink-0 text-right font-mono text-slate-400">{index + 1}</span><span className="break-all font-medium text-slate-800">{feature}</span></li>)}
        </ol>
      </AuditSection>
      <AuditSection title="Identity and target taxonomy" icon={<Target size={16} />}>
        <AuditGrid rows={[
          ["Target", review.targetTaxonomy.column],
          ["Governed class order", review.targetTaxonomy.classOrder.join(" → ")],
          ["Observed players", formatInteger(review.identity.observedPlayerCount)],
          ["Unresolved / ambiguous players", `${review.identity.unresolvedPlayerIdentities} / ${review.identity.ambiguousPlayerIdentities}`],
          ["Unresolved / ambiguous games", `${review.identity.unresolvedGameIdentities} / ${review.identity.ambiguousGameIdentities}`],
          ["Duplicate canonical PAs", formatInteger(review.identity.duplicateCanonicalPaIdentities)],
        ]} />
      </AuditSection>
      {review.contextualFeaturePack ? <AuditSection title="Contextual challenger authority" icon={<Wand2 size={16} />}><AuditGrid rows={[
        ["Dataset", review.contextualFeaturePack.datasetId],
        ["Manifest", review.contextualFeaturePack.manifestSha256],
        ["Population", `${formatInteger(review.contextualFeaturePack.rowCount)} rows`],
        ["Contract", `${review.contextualFeaturePack.coreFeatureCount} core + ${review.contextualFeaturePack.addedFeatureCount} contextual = ${review.contextualFeaturePack.totalFeatureCount}`],
        ["Rivalry mapping", review.contextualFeaturePack.rivalryMappingStatus],
      ]} />{review.contextualFeaturePack.warnings.map((warning) => <p key={warning} className="mt-2 rounded-lg border border-amber-200 bg-amber-50 p-2 text-xs text-amber-900">{warning}</p>)}</AuditSection> : null}
    </div>
  );
}

function AuditSection({ title, icon, children }: { title: string; icon: JSX.Element; children: ReactNode }) {
  return <section className="overflow-hidden rounded-xl border border-slate-200 bg-slate-50/60"><div className="flex items-center gap-2 border-b border-slate-200 bg-white px-3 py-2 text-sm font-semibold text-slate-950">{icon}{title}</div><div className="p-3">{children}</div></section>;
}

function AuditGrid({ rows }: { rows: [string, string][] }) {
  return <dl className="grid gap-x-4 gap-y-2 text-xs sm:grid-cols-2">{rows.map(([label, value]) => <div key={label} className="min-w-0"><dt className="font-semibold uppercase tracking-[0.08em] text-slate-400">{label}</dt><dd className="mt-0.5 break-all leading-5 text-slate-800">{value}</dd></div>)}</dl>;
}

function programStageLabel(stage: StageResolution) {
  if (stage.status === "COMPLETE") return "Completed";
  if (stage.status === "CURRENT") return "Current";
  if (stage.status === "READY") return stage.evidenceState === "NO_EVIDENCE" ? "Not configured" : "Ready";
  if (stage.status === "STALE") return "Requires review";
  return stage.evidenceState === "NO_EVIDENCE" ? "Not configured" : "Blocked";
}

function cockpitStepStatus(candidate: Step, index: number, activeStep: string, savedSteps: Record<string, boolean>, hasResult: boolean, projectBound: boolean) {
  if (candidate.id === activeStep) return "Current";
  if (savedSteps[candidate.id]) return "Completed";
  if (!projectBound) return "Not configured";
  if (index < 3) return "Ready";
  if (hasResult && ["evaluation", "calibration", "simulation"].includes(candidate.id)) return "Ready";
  return "Requires review";
}

function shortProjectName(value: string) {
  const trimmed = value.trim();
  return trimmed.length <= 48 ? trimmed : `${trimmed.slice(0, 45)}…`;
}

function formatInteger(value: number) {
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 }).format(value);
}

// Compact, non-intrusive autosave indicator. Draft progress persists continuously; a failure never
// discards in-memory work — it surfaces a warning with a manual Retry.
function AutosaveBadge({ status, lastSavedAt, onRetry }: { status: AutosaveStatus; lastSavedAt: string | null; onRetry: () => void }) {
  const time = lastSavedAt ? new Date(lastSavedAt).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" }) : null;
  if (status === "error") {
    return (
      <button onClick={onRetry} className="inline-flex items-center gap-1.5 rounded-full border border-rose-200 bg-rose-50 px-2.5 py-1 text-[11px] font-semibold text-rose-700 hover:bg-rose-100">
        <CloudOff size={12} /> Autosave failed — retry <RefreshCw size={11} />
      </button>
    );
  }
  if (status === "saving") {
    return <span className="inline-flex items-center gap-1.5 rounded-full border border-slate-200 bg-white px-2.5 py-1 text-[11px] font-semibold text-slate-500"><Loader2 size={12} className="animate-spin" /> Saving…</span>;
  }
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full border border-emerald-200 bg-emerald-50 px-2.5 py-1 text-[11px] font-semibold text-emerald-700">
      <Check size={12} /> {status === "saved" && time ? `Saved ${time}` : "Progress autosaved"}
    </span>
  );
}

// Consistent Previous / Next workflow footer at the bottom of every cockpit step. Project-bound
// downstream steps suppress generic Next because their guarded in-page action owns advancement.
// Step 1 has no Previous and Step 15 has no Next.
function StepFooter({ active, go, suppressNext = false }: { active: string; go: (id: string) => void; suppressNext?: boolean }) {
  const idx = STEPS.findIndex((s) => s.id === active);
  const prev = idx > 0 ? STEPS[idx - 1] : null;
  const next = idx < STEPS.length - 1 ? STEPS[idx + 1] : null;
  return (
    <div className="mt-6 flex items-center justify-between gap-3 border-t border-slate-200 pt-4">
      {prev ? (
        <button onClick={() => go(prev.id)}
          className="inline-flex min-w-0 items-center gap-2 rounded-lg border border-slate-200 bg-white px-3.5 py-2 text-sm font-medium text-slate-700 transition-colors hover:bg-slate-50">
          <ChevronLeft size={16} className="shrink-0 text-slate-400" />
          <span className="truncate"><span className="hidden sm:inline">{prev.label}</span><span className="sm:hidden">Previous</span></span>
        </button>
      ) : <span aria-hidden="true" />}
      <div className="shrink-0 text-xs font-semibold tabular-nums text-slate-500">Step {idx + 1} of {STEPS.length}</div>
      {next && !suppressNext ? (
        <button onClick={() => go(next.id)}
          className="inline-flex min-w-0 items-center gap-2 rounded-lg bg-slate-900 px-3.5 py-2 text-sm font-medium text-white transition-colors hover:bg-slate-800">
          <span className="truncate"><span className="hidden sm:inline">{next.label}</span><span className="sm:hidden">Next</span></span>
          <ChevronRight size={16} className="shrink-0 text-cyan-300" />
        </button>
      ) : <span aria-hidden="true" />}
    </div>
  );
}
