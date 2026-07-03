import { Link } from "react-router-dom";
import type React from "react";
import { Activity, AlertTriangle, BarChart3, CheckCircle2, Database, GitBranch, RotateCcw } from "lucide-react";
import BrandLogo from "../components/BrandLogo";
import { BRAND } from "../config/brand";
import { getWorkflowDefinition } from "../config/workflows";
import { buildEscalationQueue, loadProductionModels } from "../lib/modelMonitoring";
import { useWorkflowStore } from "../state/useWorkflowStore";

export default function Dashboard() {
  const workflowSteps = useWorkflowStore((state) => state.workflowSteps);
  const workflowId = useWorkflowStore((state) => state.workflowId);
  const projectName = useWorkflowStore((state) => state.projectName);
  const hasDataset = useWorkflowStore((state) => state.hasDataset);
  const reset = useWorkflowStore((state) => state.reset);
  const workflow = getWorkflowDefinition(workflowId);
  const productionModels = loadProductionModels();
  const escalations = buildEscalationQueue(productionModels);

  const completed = workflowSteps.filter((step) => step.status === "complete").length;
  const inProgress =
    workflowSteps.find((step) => step.status !== "complete" && step.status !== "skipped") ?? workflowSteps[workflowSteps.length - 1];
  const progress = Math.round((completed / Math.max(1, workflowSteps.length)) * 100);

  return (
    <div className="w-full space-y-5">
      <section className="rounded-xl border border-slate-200/80 bg-white/90 p-5 shadow-sm">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <BrandLogo size="lg" variant="light" showSubtitle />
            <p className="mt-3 max-w-2xl text-sm text-slate-600">
              Navigate regulated model development from source data to documented champion model.
            </p>
            <p className="mt-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
              {projectName} · {workflow.label}
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Link to="/projects/new" className="rounded-lg bg-slate-950 px-3 py-2 text-sm font-semibold text-white shadow-sm hover:bg-slate-800">
              Start New Project
            </Link>
            <Link to={inProgress.route} className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-700 shadow-sm hover:bg-slate-50">
              Continue Journey
            </Link>
            <Link to="/step01" className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-700 shadow-sm hover:bg-slate-50">
              Open Existing Project
            </Link>
            <Link to="/project-overview" className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-700 shadow-sm hover:bg-slate-50">
              Project Overview
            </Link>
          </div>
        </div>
        <div className="mt-3 text-xs font-medium text-slate-500">{BRAND.shortDescription}</div>
      </section>

      <section className="grid gap-4 md:grid-cols-4">
        <StatCard icon={<GitBranch size={18} />} label="Journey Steps" value={workflowSteps.length} />
        <StatCard icon={<CheckCircle2 size={18} />} label="Milestones Completed" value={completed} />
        <StatCard icon={<Activity size={18} />} label="Progress" value={`${progress}%`} />
        <StatCard icon={<Database size={18} />} label="Dataset Loaded" value={hasDataset ? "Yes" : "No"} />
      </section>

      <section className="grid gap-4 xl:grid-cols-[1.1fr_0.9fr]">
        <div className="rounded-lg border border-rose-200 bg-rose-50 p-5 shadow-sm">
          <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
            <div>
              <div className="flex items-center gap-2 text-rose-950">
                <AlertTriangle size={18} />
                <h2 className="text-lg font-semibold">Manager Escalation Queue</h2>
              </div>
              <p className="mt-1 text-sm text-rose-800">
                Models requiring Data Science Manager attention due to age, monitoring deterioration, or compliance issues.
              </p>
            </div>
            <Link to="/step13" className="rounded-lg bg-rose-900 px-3 py-2 text-sm font-semibold text-white shadow-sm hover:bg-rose-800">
              Open Monitoring
            </Link>
          </div>
          <div className="mt-4 grid gap-2">
            {escalations.slice(0, 5).map((item, index) => (
              <article key={`${item.modelId}-${index}`} className="rounded-lg border border-rose-200 bg-white px-3 py-3">
                <div className="flex flex-col gap-2 md:flex-row md:items-start md:justify-between">
                  <div>
                    <div className="text-sm font-semibold text-slate-950">{item.modelId} {item.modelName}</div>
                    <div className="mt-1 text-xs leading-5 text-slate-600">{item.reason}</div>
                  </div>
                  <span className={`rounded-full px-2 py-1 text-xs font-semibold ${item.severity === "high" ? "bg-rose-100 text-rose-800" : "bg-amber-100 text-amber-800"}`}>
                    {item.severity}
                  </span>
                </div>
                <div className="mt-2 text-xs text-rose-900">
                  Owner: {item.owner} · Action: {item.action}
                </div>
              </article>
            ))}
            {!escalations.length && (
              <div className="rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-3 text-sm font-medium text-emerald-900">
                No production monitoring escalations are currently open.
              </div>
            )}
          </div>
        </div>

        <div className="rounded-lg border border-slate-200/80 bg-white/90 p-5 shadow-sm">
          <h2 className="text-lg font-semibold text-slate-950">Production Models Under Monitoring</h2>
          <p className="mt-1 text-sm text-slate-500">Current monitored production inventory and latest status summary.</p>
          <div className="mt-4 grid gap-2">
            {productionModels.slice(0, 4).map((model) => {
              const redCount = model.metrics.filter((metric) => metric.status === "red").length;
              const yellowCount = model.metrics.filter((metric) => metric.status === "yellow").length;
              return (
                <article key={`${model.modelId}-${model.modelName}`} className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-3">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <div className="text-sm font-semibold text-slate-950">{model.modelId} {model.modelName}</div>
                      <div className="mt-1 text-xs text-slate-500">Owner: {model.owner} · Cadence: {model.monitoringCadence}</div>
                    </div>
                    <span className={`rounded-full px-2 py-1 text-xs font-semibold ${
                      redCount ? "bg-rose-100 text-rose-800" : yellowCount ? "bg-amber-100 text-amber-800" : "bg-emerald-100 text-emerald-800"
                    }`}>
                      {redCount ? `${redCount} red` : yellowCount ? `${yellowCount} warning` : "green"}
                    </span>
                  </div>
                </article>
              );
            })}
          </div>
        </div>
      </section>

      <section className="rounded-lg border border-slate-200/80 bg-white/90 shadow-sm">
        <div className="flex flex-col gap-3 border-b border-slate-200 px-5 py-4 md:flex-row md:items-center md:justify-between">
          <div>
            <h2 className="text-lg font-semibold text-slate-950">Model Development Journey</h2>
            <p className="text-sm text-slate-500">
              Capture each decision point from source data through governed documentation.
            </p>
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              className="inline-flex items-center gap-2 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-700 shadow-sm hover:bg-slate-50"
              onClick={reset}
            >
              <RotateCcw size={15} />
              Reset Progress
            </button>
            <Link
              to={inProgress.route}
              className="inline-flex items-center gap-2 rounded-lg bg-slate-950 px-3 py-2 text-sm font-medium text-white shadow-sm hover:bg-slate-800"
            >
              <BarChart3 size={15} />
              Continue Journey
            </Link>
          </div>
        </div>

        <div className="grid gap-3 p-4 sm:grid-cols-2 xl:grid-cols-3">
          {workflowSteps.map((step, index) => {
            const status = step.status ?? "pending";
            return (
              <article
                key={step.id}
                className="grid min-h-[150px] gap-4 rounded-lg border border-slate-200/80 bg-slate-50/70 p-4 shadow-[inset_0_1px_0_rgba(255,255,255,0.9)]"
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="flex min-w-0 items-center gap-3">
                    <div
                      className={`grid h-8 w-8 shrink-0 place-items-center rounded-full text-xs font-semibold ${
                        status === "complete"
                          ? "bg-emerald-100 text-emerald-700"
                          : "bg-white text-slate-600 ring-1 ring-slate-200"
                      }`}
                    >
                      {index + 1}
                    </div>
                    <div className="min-w-0">
                      <h3 className="truncate font-semibold text-slate-950">{step.label}</h3>
                      <span
                        className={`mt-1 inline-flex rounded-full px-2 py-0.5 text-[11px] font-medium ${
                          status === "complete"
                            ? "bg-emerald-50 text-emerald-700"
                            : "bg-white text-slate-600 ring-1 ring-slate-200"
                        }`}
                      >
                        {status === "complete" ? "Completed" : status === "skipped" ? "Skipped" : "Pending"}
                      </span>
                    </div>
                  </div>
                  <Link
                    to={step.route}
                    className="inline-flex shrink-0 justify-center rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm font-medium text-slate-700 shadow-sm hover:bg-slate-50"
                  >
                    Open
                  </Link>
                </div>
                <p className="text-sm leading-5 text-slate-500">{step.description}</p>
              </article>
            );
          })}
        </div>
      </section>
    </div>
  );
}

function StatCard({
  icon,
  label,
  value,
}: {
  icon: React.ReactNode;
  label: string;
  value: number | string;
}) {
  return (
    <div className="rounded-lg border border-slate-200/80 bg-white/90 p-4 shadow-sm">
      <div className="flex items-center justify-between text-slate-500">
        <span className="text-xs font-semibold uppercase tracking-wide">{label}</span>
        {icon}
      </div>
      <div className="mt-3 text-2xl font-semibold text-slate-950">{value}</div>
    </div>
  );
}
