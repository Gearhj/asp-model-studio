import { Link } from "react-router-dom";
import {
  Activity,
  BarChart3,
  BookOpenCheck,
  CheckCircle2,
  Database,
  LineChart,
  Network,
  RotateCcw,
  Search,
  TerminalSquare,
} from "lucide-react";
import AtlasCard from "../components/ui/AtlasCard";
import AtlasEmptyState from "../components/ui/AtlasEmptyState";
import AtlasMetricCard from "../components/ui/AtlasMetricCard";
import AtlasPageHero from "../components/ui/AtlasPageHero";
import AtlasProgressBar from "../components/ui/AtlasProgressBar";
import AtlasStatusBadge from "../components/ui/AtlasStatusBadge";
import { getWorkflowDefinition } from "../config/workflows";
import { saveActiveProjectBeforeNavigation } from "../lib/localProjects";
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
  const saveBeforeOpenProject = () => {
    saveActiveProjectBeforeNavigation(useWorkflowStore.getState());
  };

  const completed = workflowSteps.filter((step) => step.status === "complete").length;
  const currentStep =
    workflowSteps.find((step) => step.status !== "complete" && step.status !== "skipped") ?? workflowSteps[workflowSteps.length - 1];
  const currentIndex = Math.max(0, workflowSteps.findIndex((step) => step.id === currentStep?.id));
  const lastCompleted = [...workflowSteps].reverse().find((step) => step.status === "complete");
  const upcoming = workflowSteps.slice(currentIndex + 1, currentIndex + 3);
  const progress = Math.round((completed / Math.max(1, workflowSteps.length)) * 100);
  const highCount = escalations.filter((item) => item.severity === "high").length;
  const warningCount = escalations.filter((item) => item.severity !== "high").length;
  const hasMeaningfulProject = projectName !== "Untitled ATLAS Project" || completed > 0 || hasDataset;

  if (!hasMeaningfulProject) {
    return (
      <div className="atlas-page-shell">
        <AtlasPageHero
          dark
          eyebrow="Enterprise decision intelligence"
          title="Move from data to governed decisions."
          subtitle="Use ATLAS to acquire data, analyze evidence, develop models and decision strategies, document results, and prepare governed implementation."
          actions={
            <>
              <Link to="/projects/new" className="atlas-primary-button">Start New Project</Link>
              <Link to="/projects/open" onClick={saveBeforeOpenProject} className="atlas-secondary-button">Open Existing Project</Link>
              <Link to="/datasets" className="atlas-tertiary-button bg-white/10 text-white hover:bg-white/15">Explore Dataset Library</Link>
            </>
          }
          aside={<HeroProgress projectName={projectName} workflowLabel={workflow.label} progress={progress} completed={completed} total={workflowSteps.length} currentStep={currentStep?.label ?? "Project Context"} hasDataset={hasDataset} />}
        />
        <AtlasEmptyState
          title="Start with a project or a governed dataset."
          body="ATLAS will organize workflow steps, evidence, documentation, and monitoring around the project type you choose."
          action={<Link to="/projects/new" className="atlas-primary-button">Start New Project</Link>}
        />
      </div>
    );
  }

  return (
    <div className="atlas-page-shell">
      <AtlasPageHero
        dark
        eyebrow="Enterprise decision intelligence"
        title="Move from data to governed decisions."
        subtitle="Use ATLAS to acquire data, analyze evidence, develop models and decision strategies, document results, and prepare governed implementation."
        actions={
          <>
            <Link to={currentStep.route} className="atlas-primary-button">Continue {currentStep.shortLabel ?? currentStep.label}</Link>
            <Link to="/projects/new" className="atlas-secondary-button">Start New Project</Link>
            <Link to="/projects/open" onClick={saveBeforeOpenProject} className="atlas-tertiary-button bg-white/10 text-white hover:bg-white/15">Open Existing Project</Link>
          </>
        }
        aside={<HeroProgress projectName={projectName} workflowLabel={workflow.label} progress={progress} completed={completed} total={workflowSteps.length} currentStep={currentStep.label} hasDataset={hasDataset} />}
      />

      <section className="grid gap-3 md:grid-cols-2 xl:grid-cols-6">
        {quickAccessItems.map((item) => (
          <Link key={item.to} to={item.to} className="atlas-card group p-4 transition hover:-translate-y-0.5 hover:border-blue-200 hover:shadow-md">
            <item.icon size={18} className="text-blue-600" aria-hidden="true" />
            <div className="mt-3 text-sm font-semibold text-slate-950">{item.label}</div>
            <div className="mt-1 text-xs leading-5 text-slate-500">{item.description}</div>
          </Link>
        ))}
      </section>

      <section className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_minmax(360px,0.56fr)]">
        <AtlasCard title="Continue Your Work" eyebrow="Current project">
          <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_260px]">
            <div>
              <div className="text-2xl font-semibold text-slate-950">{projectName}</div>
              <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-600">{workflow.description}</p>
              <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                <AtlasMetricCard label="Workflow" value={workflow.label} />
                <AtlasMetricCard label="Completed steps" value={`${completed} / ${workflowSteps.length}`} tone={progress >= 70 ? "success" : "info"} />
                <AtlasMetricCard label="Dataset loaded" value={hasDataset ? "Yes" : "No"} tone={hasDataset ? "success" : "warning"} />
                <AtlasMetricCard label="Progress" value={`${progress}%`} icon={<Activity size={16} />} />
              </div>
            </div>
            <div className="rounded-2xl border border-blue-200 bg-blue-50 p-4">
              <div className="atlas-eyebrow text-blue-700">Next required action</div>
              <div className="mt-2 text-lg font-semibold text-blue-950">{currentStep.label}</div>
              <p className="mt-2 text-sm leading-6 text-blue-900">{currentStep.description}</p>
              <Link to={currentStep.route} className="atlas-primary-button mt-4 w-full">Continue workflow</Link>
            </div>
          </div>
        </AtlasCard>

        <AtlasCard title="What Needs Attention" eyebrow={`${highCount} high, ${warningCount} warning`}>
          <div className="grid gap-2">
            {escalations.slice(0, 5).map((item, index) => (
              <article key={`${item.modelId}-${index}`} className="atlas-compact-row">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <div className="text-sm font-semibold text-slate-950">{item.modelId} {item.modelName}</div>
                    <div className="mt-1 text-xs leading-5 text-slate-600">{item.reason}</div>
                    <div className="mt-1 text-xs text-slate-500">Owner: {item.owner}. Action: {item.action}</div>
                  </div>
                  <AtlasStatusBadge tone={item.severity === "high" ? "danger" : "warning"}>{item.severity === "high" ? "High" : "Warning"}</AtlasStatusBadge>
                </div>
              </article>
            ))}
            {!escalations.length && (
              <div className="atlas-success-panel">
                <div className="flex items-center gap-2 font-semibold"><CheckCircle2 size={16} /> No production monitoring escalations are open.</div>
              </div>
            )}
          </div>
          <Link to="/step13" className="atlas-secondary-button mt-4">Open Monitoring</Link>
        </AtlasCard>
      </section>

      <section className="grid gap-5 xl:grid-cols-[0.95fr_1.05fr]">
        <AtlasCard title="Production Monitoring" eyebrow="Operational snapshot">
          <div className="grid gap-2">
            {productionModels.slice(0, 4).map((model) => {
              const redCount = model.metrics.filter((metric) => metric.status === "red").length;
              const yellowCount = model.metrics.filter((metric) => metric.status === "yellow").length;
              return (
                <article key={`${model.modelId}-${model.modelName}`} className="atlas-compact-row">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <div className="text-sm font-semibold text-slate-950">{model.modelId} {model.modelName}</div>
                      <div className="mt-1 text-xs text-slate-500">Owner: {model.owner}. Cadence: {model.monitoringCadence}</div>
                    </div>
                    <AtlasStatusBadge tone={redCount ? "danger" : yellowCount ? "warning" : "success"}>
                      {redCount ? `${redCount} breached` : yellowCount ? `${yellowCount} warning` : "Healthy"}
                    </AtlasStatusBadge>
                  </div>
                </article>
              );
            })}
          </div>
        </AtlasCard>

        <AtlasCard
          title="Workflow Snapshot"
          eyebrow="Progress"
          action={
            <button type="button" className="atlas-secondary-button" onClick={reset}>
              <RotateCcw size={15} />
              Reset Progress
            </button>
          }
        >
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <WorkflowSnapshotItem label="Recently completed" step={lastCompleted} fallback="No completed steps yet" />
            <WorkflowSnapshotItem label="Current step" step={currentStep} emphasized />
            {upcoming.map((step, index) => (
              <WorkflowSnapshotItem key={step.id} label={index === 0 ? "Next step" : "Following step"} step={step} />
            ))}
          </div>
          <AtlasProgressBar className="mt-5" value={progress} label="Overall workflow progress" />
          <div className="mt-4 flex flex-wrap gap-2">
            <Link to="/project-overview" className="atlas-secondary-button">View Project Overview</Link>
            <Link to={currentStep.route} className="atlas-primary-button">
              <BarChart3 size={15} />
              Continue workflow
            </Link>
          </div>
        </AtlasCard>
      </section>
    </div>
  );
}

const quickAccessItems = [
  { label: "Dataset Library", description: "Register and review governed data assets.", to: "/datasets", icon: Database },
  { label: "SQL Data Studio", description: "Prepare governed SQL and extraction logic.", to: "/sql-data-studio", icon: TerminalSquare },
  { label: "Analytics Workbench", description: "Analyze data and save reusable findings.", to: "/analytics", icon: Search },
  { label: "Model Diagnostics", description: "Review model performance and stability.", to: "/model-diagnostics", icon: LineChart },
  { label: "Model Evidence Center", description: "Track evidence for review and approval.", to: "/model-evidence-center", icon: Network },
  { label: "Model Documentation Studio", description: "Prepare governed model documents.", to: "/model-document-studio", icon: BookOpenCheck },
];

function HeroProgress({
  projectName,
  workflowLabel,
  progress,
  completed,
  total,
  currentStep,
  hasDataset,
}: {
  projectName: string;
  workflowLabel: string;
  progress: number;
  completed: number;
  total: number;
  currentStep: string;
  hasDataset: boolean;
}) {
  return (
    <div className="rounded-2xl border border-white/15 bg-white/10 p-4 shadow-sm">
      <div className="text-xs font-semibold uppercase tracking-wide text-blue-100">Current project</div>
      <div className="mt-2 text-lg font-semibold text-white">{projectName}</div>
      <div className="mt-1 text-sm text-blue-100">{workflowLabel}</div>
      <div className="mt-4 grid gap-2">
        <div className="flex items-center justify-between text-xs font-semibold text-blue-100">
          <span>{completed} of {total} steps</span>
          <span>{progress}%</span>
        </div>
        <div className="h-2 overflow-hidden rounded-full bg-white/15">
          <div className="h-full rounded-full bg-sky-300" style={{ width: `${progress}%` }} />
        </div>
      </div>
      <div className="mt-4 grid gap-2 text-sm">
        <div className="rounded-xl bg-white/10 px-3 py-2">
          <span className="block text-xs font-semibold uppercase tracking-wide text-blue-100">Current step</span>
          <span className="mt-1 block font-semibold text-white">{currentStep}</span>
        </div>
        <div className="rounded-xl bg-white/10 px-3 py-2">
          <span className="block text-xs font-semibold uppercase tracking-wide text-blue-100">Dataset status</span>
          <span className="mt-1 block font-semibold text-white">{hasDataset ? "Loaded" : "Not loaded"}</span>
        </div>
      </div>
    </div>
  );
}

function WorkflowSnapshotItem({ label, step, fallback, emphasized = false }: { label: string; step?: { label: string; route: string; description?: string }; fallback?: string; emphasized?: boolean }) {
  if (!step) {
    return (
      <div className="atlas-inset-section">
        <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">{label}</div>
        <div className="mt-2 text-sm font-semibold text-slate-600">{fallback}</div>
      </div>
    );
  }
  return (
    <Link to={step.route} className={`rounded-2xl border p-4 transition hover:border-blue-300 ${emphasized ? "border-blue-200 bg-blue-50" : "border-slate-200 bg-slate-50"}`}>
      <div className={`text-xs font-semibold uppercase tracking-wide ${emphasized ? "text-blue-700" : "text-slate-500"}`}>{label}</div>
      <div className="mt-2 text-sm font-semibold text-slate-950">{step.label}</div>
      {step.description && <div className="mt-1 line-clamp-2 text-xs leading-5 text-slate-500">{step.description}</div>}
    </Link>
  );
}
