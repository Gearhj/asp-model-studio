import { Link } from "react-router-dom";
import type React from "react";
import { useEffect, useState } from "react";
import { ArrowRight, BookOpenCheck, CheckCircle2, Database, FileClock, FlaskConical, Gauge } from "lucide-react";
import BrandLogo from "../components/BrandLogo";
import { getWorkflowDefinition } from "../config/workflows";
import { loadDecisionJournal } from "../lib/decisionJournal";
import { listProjectDatasets, type ProjectDatasetLink } from "../lib/datasetLibrary";
import { loadExperiments } from "../lib/experimentTracking";
import { loadProjectContext } from "../lib/projectContext";
import { useWorkflowStore } from "../state/useWorkflowStore";

export default function ProjectOverview() {
  const projectName = useWorkflowStore((state) => state.projectName);
  const projectId = useWorkflowStore((state) => state.projectId);
  const projectType = useWorkflowStore((state) => state.projectType);
  const workflowId = useWorkflowStore((state) => state.workflowId);
  const workflowSteps = useWorkflowStore((state) => state.workflowSteps);
  const context = loadProjectContext();
  const decisions = loadDecisionJournal().slice(0, 4);
  const experiments = loadExperiments().slice(0, 4);
  const workflow = getWorkflowDefinition(workflowId);
  const completed = workflowSteps.filter((step) => step.status === "complete").length;
  const current = workflowSteps.find((step) => step.status !== "complete" && step.status !== "skipped") ?? workflowSteps[workflowSteps.length - 1];
  const progress = workflowSteps.length ? Math.round((completed / workflowSteps.length) * 100) : 0;
  const modelId = context.modelId || useWorkflowStore.getState().modelId || "Not assigned";
  const cadence =
    context.monitoringCadence === "custom"
      ? context.monitoringCadenceCustom || "Custom cadence not documented"
      : context.monitoringCadence;
  const [datasetLinks, setDatasetLinks] = useState<ProjectDatasetLink[]>([]);

  useEffect(() => {
    let alive = true;
    listProjectDatasets(projectId)
      .then((links) => {
        if (alive) setDatasetLinks(links);
      })
      .catch(() => {
        if (alive) setDatasetLinks([]);
      });
    return () => {
      alive = false;
    };
  }, [projectId]);

  return (
    <div className="w-full space-y-5">
      <section className="rounded-xl border border-slate-200/80 bg-white/90 p-5 shadow-sm">
        <div className="flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between">
          <div>
            <BrandLogo size="md" variant="light" showSubtitle className="mb-3" />
            <div className="flex items-center gap-2">
              <Gauge size={20} className="text-slate-800" />
              <h1 className="text-xl font-semibold text-slate-950">Current Project Overview</h1>
            </div>
            <p className="mt-1 max-w-3xl text-sm text-slate-600">
              Control center for the selected project, active workflow, recent decisions, experiments, and documentation readiness.
            </p>
          </div>
          {current && (
            <Link to={current.route} className="inline-flex items-center gap-2 rounded-lg bg-slate-950 px-3 py-2 text-sm font-semibold text-white shadow-sm hover:bg-slate-800">
              Next Recommended Action
              <ArrowRight size={15} />
            </Link>
          )}
        </div>
      </section>

      <section className="grid gap-4 md:grid-cols-4">
        <Stat label="Model ID #" value={modelId} />
        <Stat label="Project" value={projectName || context.projectName || "Untitled"} />
        <Stat label="Project Type" value={labelize(projectType)} />
        <Stat label="Completion" value={`${progress}%`} />
      </section>

      <section className="grid gap-5 xl:grid-cols-[1.15fr_0.85fr]">
        <div className="rounded-lg border border-slate-200/80 bg-white/90 p-5 shadow-sm">
          <h2 className="text-sm font-semibold text-slate-950">Current Workflow</h2>
          <p className="mt-1 text-sm text-slate-500">{workflow.description}</p>
          <div className="mt-4 grid gap-2">
            {workflowSteps.map((step, index) => (
              <Link
                key={step.id}
                to={step.route}
                className="grid gap-3 rounded-lg border border-slate-200 bg-slate-50 px-3 py-3 transition hover:border-blue-200 hover:bg-blue-50 sm:grid-cols-[2rem_1fr_auto] sm:items-center"
              >
                <span className={`grid h-8 w-8 place-items-center rounded-full text-xs font-semibold ${step.status === "complete" ? "bg-emerald-100 text-emerald-700" : "bg-white text-slate-600 ring-1 ring-slate-200"}`}>
                  {index + 1}
                </span>
                <span>
                  <span className="block text-sm font-semibold text-slate-950">{step.label}</span>
                  <span className="block text-xs leading-5 text-slate-500">{step.description}</span>
                </span>
                <span className="text-xs font-semibold text-slate-500">{step.status === "complete" ? "Complete" : "Open"}</span>
              </Link>
            ))}
          </div>
        </div>

        <div className="grid gap-5">
          <Panel icon={<FileClock size={18} />} title="Recent Decisions">
            {decisions.length ? (
              decisions.map((entry, index) => (
                <div key={`${entry.id ?? entry.timestamp ?? entry.workflowStep ?? "decision"}-${index}`} className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2">
                  <div className="text-xs font-semibold text-slate-900">{entry.subject}</div>
                  <div className="mt-1 text-[11px] leading-4 text-slate-500">{entry.workflowStep} · {entry.actionType}</div>
                </div>
              ))
            ) : (
              <Empty text="No decisions logged yet." />
            )}
          </Panel>

          <Panel icon={<FlaskConical size={18} />} title="Recent Experiments">
            {experiments.length ? (
              experiments.map((experiment, index) => (
                <div key={`${experiment.experimentId ?? experiment.modelType ?? "experiment"}-${index}`} className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2">
                  <div className="text-xs font-semibold text-slate-900">{experiment.modelType}</div>
                  <div className="mt-1 text-[11px] leading-4 text-slate-500">{experiment.champion ? "Champion" : "Challenger"} · {experiment.datasetVersion}</div>
                </div>
              ))
            ) : (
              <Empty text="No experiments recorded yet." />
            )}
          </Panel>

          <Panel icon={<BookOpenCheck size={18} />} title="Documentation Status">
            <div className="rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-900">
              <div className="flex items-center gap-2 font-semibold">
                <CheckCircle2 size={15} />
                Governance-ready structure available
              </div>
              <p className="mt-1 text-xs leading-5">Reports and notebook exports are workflow-aware and will use placeholder outlines for non-modeling workflows.</p>
            </div>
          </Panel>

          <Panel icon={<Database size={18} />} title="Linked Datasets">
            {datasetLinks.length ? (
              datasetLinks.map((link) => (
                <Link key={`${link.datasetId}-${link.versionId}`} to={`/datasets/${link.datasetId}`} className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 transition hover:border-blue-200 hover:bg-blue-50">
                  <div className="text-xs font-semibold text-slate-900">{link.dataset?.name || link.datasetId}</div>
                  <div className="mt-1 text-[11px] leading-4 text-slate-500">
                    {link.datasetRole} · {link.versionId} · {link.dataset?.latestVersion?.rowCount?.toLocaleString() ?? "-"} rows
                  </div>
                </Link>
              ))
            ) : (
              <Empty text="No Dataset Library assets linked yet." />
            )}
          </Panel>

          <Panel icon={<Gauge size={18} />} title="Implementation & Monitoring">
            <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2">
              <div className="text-xs font-semibold text-slate-900">Implementation</div>
              <div className="mt-1 text-[11px] leading-4 text-slate-500">
                Owner: {context.implementationOwner || "Not documented"} · Environment: {context.implementationEnvironment || "Not documented"}
              </div>
            </div>
            <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2">
              <div className="text-xs font-semibold text-slate-900">Monitoring cadence: {cadence}</div>
              <div className="mt-1 text-[11px] leading-4 text-slate-500">
                Metrics: {context.monitoringMetrics.length ? context.monitoringMetrics.join(", ") : "Not selected"}
              </div>
            </div>
          </Panel>
        </div>
      </section>
    </div>
  );
}

function labelize(value: string) {
  return value.replace(/-/g, " ").replace(/\b\w/g, (match) => match.toUpperCase());
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-slate-200/80 bg-white/90 p-4 shadow-sm">
      <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">{label}</div>
      <div className="mt-2 truncate text-xl font-semibold text-slate-950" title={value}>{value}</div>
    </div>
  );
}

function Panel({ icon, title, children }: { icon: React.ReactNode; title: string; children: React.ReactNode }) {
  return (
    <section className="rounded-lg border border-slate-200/80 bg-white/90 p-5 shadow-sm">
      <div className="flex items-center gap-2 text-slate-900">
        {icon}
        <h2 className="text-sm font-semibold">{title}</h2>
      </div>
      <div className="mt-3 grid gap-2">{children}</div>
    </section>
  );
}

function Empty({ text }: { text: string }) {
  return <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-500">{text}</div>;
}
