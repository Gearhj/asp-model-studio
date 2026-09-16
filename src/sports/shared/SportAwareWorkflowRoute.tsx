import type { ReactNode } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { AlertTriangle, ArrowLeft, LockKeyhole } from "lucide-react";
import { useWorkflowStore } from "../../state/useWorkflowStore";
import { loadSportsProjectMetadata } from "../sportsConfig";
import { canonicalSportsProjectId } from "../sportsProjectRoutes";
import { useCanonicalSportsProject } from "../workflow/useCanonicalSportsProject";
import type { LeagueCode } from "./sportRegistry";
import { workflowManifestForLeague } from "./workflowManifest";
import { resolveSportAwareWorkflowRoute } from "./workflowRouteGuard";

type Props = {
  requestedLeagueCode: LeagueCode;
  children: ReactNode;
  allowReadinessWithoutProject?: boolean;
};

export default function SportAwareWorkflowRoute({ requestedLeagueCode, children, allowReadinessWithoutProject = false }: Props) {
  const [params] = useSearchParams();
  const stateProjectId = useWorkflowStore((state) => state.projectId);
  const projectId = canonicalSportsProjectId(params.get("projectId"), stateProjectId);
  if (!projectId && allowReadinessWithoutProject) {
    return <WorkflowReadinessSurface leagueCode={requestedLeagueCode} />;
  }
  return <BoundSportWorkflowRoute requestedLeagueCode={requestedLeagueCode} projectId={projectId} stateProjectId={stateProjectId}>{children}</BoundSportWorkflowRoute>;
}

function BoundSportWorkflowRoute({ requestedLeagueCode, projectId, stateProjectId, children }: Props & { projectId: string; stateProjectId: string }) {
  const projectIdentity = useCanonicalSportsProject(projectId, stateProjectId);
  const workflowId = useWorkflowStore((state) => state.workflowId);
  const metadata = loadSportsProjectMetadata(projectId);

  if (projectIdentity.status !== "ready") {
    return <div className="sports-page-shell"><section className={`sports-panel p-6 text-sm ${projectIdentity.status === "error" ? "border-rose-200 bg-rose-50 text-rose-900" : "text-slate-600"}`} role={projectIdentity.status === "error" ? "alert" : "status"}>{projectIdentity.status === "error" ? projectIdentity.error : "Verifying the persisted sport, league, and workflow manifest…"}</section></div>;
  }

  const decision = resolveSportAwareWorkflowRoute(requestedLeagueCode, workflowId, metadata);
  if (!decision.allowed) return <WorkflowMismatch reason={decision.reason} />;
  return <>{children}</>;
}

function WorkflowMismatch({ reason }: { reason: string }) {
  return <main className="sports-page-shell">
    <section className="rounded-2xl border border-rose-300 bg-rose-50 p-6 text-rose-950" role="alert" data-workflow-route-mismatch="true">
      <div className="flex items-start gap-3"><AlertTriangle className="mt-0.5 shrink-0" size={22} /><div><p className="text-xs font-semibold uppercase tracking-[0.15em]">Fail-closed workflow guard</p><h1 className="mt-2 text-2xl font-semibold">Workflow route mismatch</h1><p className="mt-3 max-w-3xl text-sm leading-6">{reason} No workflow, dataset, target, or model authority was substituted.</p></div></div>
      <Link to="/projects/open" className="sports-secondary-button mt-5"><ArrowLeft size={16} /> Return to Sports Projects</Link>
    </section>
  </main>;
}

export function WorkflowReadinessSurface({ leagueCode }: { leagueCode: LeagueCode }) {
  const manifest = workflowManifestForLeague(leagueCode);
  if (!manifest) return <WorkflowMismatch reason={`No ${leagueCode} workflow manifest is registered.`} />;
  return <main className="sports-page-shell space-y-5" data-workflow-readiness={leagueCode}>
    <section className="sports-hero-panel p-6 sm:p-8">
      <span className="sports-status border-white/15 bg-white/10 text-slate-200">{manifest.availability}</span>
      <h1 className="mt-4 text-3xl font-semibold text-white">{manifest.displayName}</h1>
      <p className="mt-3 max-w-3xl text-sm leading-7 text-slate-300">{manifest.description}</p>
    </section>
    <section className="sports-panel p-5 sm:p-6">
      <div className="flex items-start gap-3"><LockKeyhole className="mt-0.5 shrink-0 text-amber-700" size={21} /><div><h2 className="text-xl font-semibold text-slate-950">Readiness and capability declaration</h2><p className="mt-2 text-sm leading-6 text-slate-600">This page describes the manifest only. It does not create a project, bind evidence, fit a model, activate a simulator, or imply deployment readiness.</p></div></div>
      <dl className="mt-5 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <ReadinessFact label="Sport" value={manifest.sportCode} />
        <ReadinessFact label="League" value={manifest.leagueCode} />
        <ReadinessFact label="Participant" value={manifest.participantType} />
        <ReadinessFact label="Simulator adapter" value={manifest.simulatorAdapterCode} />
      </dl>
      <div className="mt-5 flex flex-wrap gap-2">{manifest.deploymentRestrictions.map((item) => <span key={item} className="sports-status sports-status--amber">{item}</span>)}</div>
    </section>
  </main>;
}

function ReadinessFact({ label, value }: { label: string; value: string }) {
  return <div className="rounded-xl border border-slate-200 bg-slate-50 p-3"><dt className="text-xs font-semibold uppercase tracking-wide text-slate-500">{label}</dt><dd className="mt-1 break-words text-sm font-semibold text-slate-900">{value}</dd></div>;
}
