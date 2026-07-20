import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  ArrowDown,
  ArrowRight,
  ArrowUp,
  Beaker,
  Bot,
  BrainCircuit,
  ChartNoAxesCombined,
  Clock3,
  GitBranch,
  Layers3,
  Network,
  Plus,
  Rocket,
  SearchCheck,
  SlidersHorizontal,
  Trash2,
} from "lucide-react";
import AtlasCard from "../components/ui/AtlasCard";
import AtlasMetricCard from "../components/ui/AtlasMetricCard";
import AtlasPageHero from "../components/ui/AtlasPageHero";
import AtlasStatusBadge from "../components/ui/AtlasStatusBadge";
import {
  createCustomWorkflow,
  getWorkflowForProjectType,
  projectTypeOptions,
  type ProjectType,
  type WorkflowStep,
} from "../config/workflows";
import { logDecision } from "../lib/decisionJournal";
import { grantProjectAccess, me } from "../lib/auth";
import { upsertProjectFromState } from "../lib/localProjects";
import { defaultMonitoringMetricsForModelType, loadProjectContext, saveProjectContext } from "../lib/projectContext";
import { useWorkflowStore } from "../state/useWorkflowStore";

const inputClass = "atlas-input";

const projectTypeVisuals: Record<ProjectType, { category: string; maturity: string; icon: JSX.Element; tone: "neutral" | "info" | "success" | "warning" }> = {
  "predictive-modeling": { category: "Model Development", maturity: "Production ready", icon: <BrainCircuit size={18} />, tone: "info" },
  "experimental-design": { category: "Experimentation", maturity: "Structured", icon: <Beaker size={18} />, tone: "success" },
  "ab-testing": { category: "Experimentation", maturity: "Structured", icon: <SearchCheck size={18} />, tone: "success" },
  optimization: { category: "Decision Science", maturity: "Advanced", icon: <SlidersHorizontal size={18} />, tone: "warning" },
  time_series_forecasting: { category: "Time Aware", maturity: "Standard", icon: <Clock3 size={18} />, tone: "info" },
  llm_generative_ai: { category: "Generative AI", maturity: "Specialized", icon: <Bot size={18} />, tone: "neutral" },
  forecasting: { category: "Time Aware", maturity: "Standard", icon: <ChartNoAxesCombined size={18} />, tone: "info" },
  segmentation: { category: "Population Analysis", maturity: "Standard", icon: <Layers3 size={18} />, tone: "neutral" },
  "reinforcement-learning": { category: "Decision Science", maturity: "Advanced", icon: <Bot size={18} />, tone: "warning" },
  "time-series": { category: "Time Aware", maturity: "Standard", icon: <Clock3 size={18} />, tone: "info" },
  nlp: { category: "Unstructured Data", maturity: "Specialized", icon: <Rocket size={18} />, tone: "neutral" },
  "computer-vision": { category: "Unstructured Data", maturity: "Specialized", icon: <Rocket size={18} />, tone: "neutral" },
  "graph-analytics": { category: "Network Analysis", maturity: "Specialized", icon: <Network size={18} />, tone: "neutral" },
  "custom-workflow": { category: "Custom", maturity: "User defined", icon: <GitBranch size={18} />, tone: "neutral" },
};

export default function NewProject() {
  const navigate = useNavigate();
  const startProjectFromWorkflow = useWorkflowStore((state) => state.startProjectFromWorkflow);
  const [modelId, setModelId] = useState("");
  const [projectName, setProjectName] = useState("Untitled ATLAS Project");
  const [projectType, setProjectType] = useState<ProjectType>("predictive-modeling");
  const [customWorkflowName, setCustomWorkflowName] = useState("Custom Workflow");
  const [customSteps, setCustomSteps] = useState(["Project Context", "Data Review", "Analysis", "Documentation"]);

  const selectedWorkflow = useMemo(() => {
    if (projectType === "custom-workflow") return createCustomWorkflow(customWorkflowName, customSteps);
    return getWorkflowForProjectType(projectType);
  }, [customSteps, customWorkflowName, projectType]);
  const requiresModelId = projectType === "predictive-modeling";
  const canStartProject = Boolean(projectName.trim()) && (!requiresModelId || Boolean(modelId.trim()));
  const analysisPatterns = [
    ["Population Segmentation", "Cluster, profile, compare, and label customer, account, merchant, or transaction populations. Use this when segmentation supports another modeling, experimentation, monitoring, or decisioning workflow rather than becoming a governed asset by itself."],
    ["Cohort Analysis", "Compare populations over origination period, campaign cohort, vintage, onboarding date, or policy change window."],
    ["Driver Analysis", "Rank business, behavioral, operational, or risk drivers before formal modeling or decisioning."],
    ["Data Quality Investigation", "Investigate missingness, duplicates, drift, outliers, source breaks, and lineage concerns."],
    ["Fairness Review", "Review protected-class proxies, segment outcomes, adverse impact, and fair-lending monitoring concerns."],
    ["Monitoring Investigation", "Deep dive into production drift, stability, performance changes, and alert root causes."],
    ["Optimization Scenario Analysis", "Compare constraints, tradeoffs, resource plans, and scenario outcomes before governed optimization."],
    ["Model Performance Deep Dive", "Analyze errors, lift, calibration, stability, feature behavior, and challenger gaps."],
    ["Text Exploration", "Explore text volume, topics, labels, extraction candidates, and quality before a governed LLM workflow."],
  ];

  const startProject = async () => {
    if (!canStartProject) return;
    const projectIdentifier = modelId.trim() || `${selectedWorkflow.id}-${Date.now()}`;
    const workflowSteps: WorkflowStep[] | undefined = projectType === "custom-workflow" ? selectedWorkflow.steps : undefined;
    const modelType = projectType === "time_series_forecasting" || projectType === "forecasting" || projectType === "optimization" ? "regression" : "generic classification";
    startProjectFromWorkflow({
      modelId: projectIdentifier,
      projectName,
      projectType,
      workflowId: selectedWorkflow.id,
      workflowSteps,
    });
    const nextState = useWorkflowStore.getState();
    upsertProjectFromState(nextState);
    try {
      const current = await me();
      await grantProjectAccess(nextState.projectId, current.user.userId, "owner");
    } catch {
      // Browser project creation should remain usable if local auth persistence is temporarily unavailable.
    }
    saveProjectContext({
      ...loadProjectContext(),
      modelId: projectIdentifier,
      projectName,
      modelType,
      monitoringMetrics: defaultMonitoringMetricsForModelType(modelType),
    });
    logDecision({
      workflowStep: "New Project",
      actionType: "workflow_setting_changed",
      subject: "Project type",
      previousValue: "-",
      newValue: `${projectIdentifier} ${projectName} (${projectType})`,
      systemRecommendation: "Choose the project type that best matches the analytical objective and governance deliverable.",
      followStatus: "not_applicable",
    });
    navigate(projectType === "predictive-modeling" ? "/step00" : "/project-overview");
  };

  return (
    <div className="atlas-page-shell">
      <AtlasPageHero
        eyebrow="Project setup"
        title="Start a governed ATLAS project"
        subtitle="Choose the analytical objective first. ATLAS will configure the workflow, evidence expectations, and documentation structure without changing the underlying project logic."
        aside={
          <div className="grid gap-2">
            <AtlasMetricCard label="Selected workflow" value={selectedWorkflow.label} tone="info" />
            <AtlasMetricCard label="Steps" value={selectedWorkflow.steps.length} />
          </div>
        }
      />

      <section className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_390px] xl:items-start">
        <div className="grid gap-5">
          <AtlasCard title="Choose Project Type" eyebrow="Workflow library">
            <div className="grid gap-3 md:grid-cols-2">
              {projectTypeOptions.map((option) => {
                const visual = projectTypeVisuals[option.value];
                const selected = projectType === option.value;
                return (
                  <button
                    key={option.value}
                    type="button"
                    className={`rounded-2xl border p-4 text-left shadow-sm transition hover:-translate-y-0.5 hover:border-blue-300 hover:bg-blue-50 ${
                      selected ? "border-blue-300 bg-blue-50 ring-2 ring-blue-100" : "border-slate-200 bg-white"
                    }`}
                    onClick={() => setProjectType(option.value)}
                    aria-pressed={selected}
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div className={`grid h-10 w-10 place-items-center rounded-xl ${selected ? "bg-blue-600 text-white" : "bg-slate-100 text-slate-700"}`}>
                        {visual.icon}
                      </div>
                      <AtlasStatusBadge tone={selected ? "info" : visual.tone}>{visual.maturity}</AtlasStatusBadge>
                    </div>
                    <div className="mt-4 text-[11px] font-semibold uppercase tracking-wide text-slate-500">{visual.category}</div>
                    <div className="mt-1 text-sm font-semibold text-slate-950">{option.label}</div>
                    <p className="mt-1 text-xs leading-5 text-slate-600">{option.description}</p>
                  </button>
                );
              })}
            </div>
          </AtlasCard>

          {projectType === "custom-workflow" && (
            <CustomWorkflowEditor
              name={customWorkflowName}
              steps={customSteps}
              onNameChange={setCustomWorkflowName}
              onStepsChange={setCustomSteps}
            />
          )}

          <AtlasCard title={selectedWorkflow.label} eyebrow="Configured workflow">
            <p className="text-sm leading-6 text-slate-600">{selectedWorkflow.description}</p>
            <div className="mt-5 grid gap-2">
              {selectedWorkflow.steps.map((step, index) => (
                <div key={`${step.id}-${index}`} className="rounded-xl border border-slate-200 bg-slate-50 px-3 py-3">
                  <div className="flex items-start gap-3">
                    <span className="grid h-7 w-7 shrink-0 place-items-center rounded-full bg-white text-xs font-semibold text-slate-600 ring-1 ring-slate-200">
                      {index + 1}
                    </span>
                    <span>
                      <span className="block text-sm font-semibold text-slate-950">{step.label}</span>
                      <span className="block text-xs leading-5 text-slate-500">{step.description}</span>
                    </span>
                  </div>
                </div>
              ))}
            </div>
          </AtlasCard>

          <AtlasCard title="Analysis Patterns Available Inside Analytics Workbench" eyebrow="Reusable analytical patterns">
            <div className="grid gap-3 md:grid-cols-2">
              {analysisPatterns.map(([title, description]) => (
                <div key={title} className="rounded-xl border border-slate-200 bg-slate-50 p-4">
                  <div className="text-sm font-semibold text-slate-950">{title}</div>
                  <p className="mt-1 text-xs leading-5 text-slate-600">{description}</p>
                </div>
              ))}
            </div>
          </AtlasCard>
        </div>

        <aside className="sticky top-24 grid gap-5">
          <AtlasCard title="Project Details" eyebrow="Required setup">
            <label className="grid gap-1.5">
              <span className="text-xs font-semibold uppercase tracking-wide text-slate-500">Project name</span>
              <input className={inputClass} value={projectName} onChange={(event) => setProjectName(event.target.value)} />
            </label>

            <label className="mt-4 grid gap-1.5">
              <span className="text-xs font-semibold uppercase tracking-wide text-slate-500">Model ID #</span>
              <input
                className={inputClass}
                value={modelId}
                onChange={(event) => setModelId(event.target.value)}
                placeholder="15211"
                aria-required={requiresModelId ? "true" : "false"}
              />
              <span className="text-xs leading-5 text-slate-500">
                {requiresModelId ? "Required for Predictive Modeling. Example: 15211 Portfolio Attrition Model." : `Optional for ${selectedWorkflow.label}. ATLAS will create a project identifier if left blank.`}
              </span>
            </label>

            <div className="atlas-info-panel mt-4 text-sm">
              <div className="font-semibold">{selectedWorkflow.label}</div>
              <p className="mt-1 text-xs leading-5">The selected type controls the workflow map, recommendations, and documentation sections for this project.</p>
            </div>

            <button
              type="button"
              onClick={startProject}
              disabled={!canStartProject}
              title={!canStartProject ? (requiresModelId ? "Model ID # is required" : "Project name is required") : "Start Project"}
              className="atlas-primary-button mt-5 w-full justify-center disabled:cursor-not-allowed disabled:bg-slate-400 disabled:text-white"
            >
              Start Project
              <ArrowRight size={15} />
            </button>
          </AtlasCard>
        </aside>
      </section>
    </div>
  );
}

function CustomWorkflowEditor({
  name,
  steps,
  onNameChange,
  onStepsChange,
}: {
  name: string;
  steps: string[];
  onNameChange: (value: string) => void;
  onStepsChange: (value: string[]) => void;
}) {
  const move = (index: number, direction: -1 | 1) => {
    const next = [...steps];
    const target = index + direction;
    if (target < 0 || target >= next.length) return;
    [next[index], next[target]] = [next[target], next[index]];
    onStepsChange(next);
  };

  return (
    <div className="rounded-2xl border border-blue-200 bg-blue-50 p-4 shadow-sm">
      <label className="grid gap-1.5">
        <span className="text-xs font-semibold uppercase tracking-wide text-blue-900">Custom workflow name</span>
        <input className={inputClass} value={name} onChange={(event) => onNameChange(event.target.value)} />
      </label>
      <div className="mt-4 grid gap-2">
        {steps.map((step, index) => (
          <div key={`${step}-${index}`} className="grid gap-2 sm:grid-cols-[1fr_auto]">
            <input
              className={inputClass}
              value={step}
              onChange={(event) => onStepsChange(steps.map((item, stepIndex) => (stepIndex === index ? event.target.value : item)))}
            />
            <div className="flex gap-1">
              <button type="button" className="rounded-lg border border-blue-200 bg-white p-2 text-blue-900 hover:bg-blue-100" onClick={() => move(index, -1)} aria-label={`Move ${step} up`}>
                <ArrowUp size={15} />
              </button>
              <button type="button" className="rounded-lg border border-blue-200 bg-white p-2 text-blue-900 hover:bg-blue-100" onClick={() => move(index, 1)} aria-label={`Move ${step} down`}>
                <ArrowDown size={15} />
              </button>
              <button type="button" className="rounded-lg border border-blue-200 bg-white p-2 text-blue-900 hover:bg-blue-100" onClick={() => onStepsChange(steps.filter((_, stepIndex) => stepIndex !== index))} aria-label={`Remove ${step}`}>
                <Trash2 size={15} />
              </button>
            </div>
          </div>
        ))}
      </div>
      <button
        type="button"
        className="atlas-secondary-button mt-3"
        onClick={() => onStepsChange([...steps, `Step ${steps.length + 1}`])}
      >
        <Plus size={15} />
        Add Step
      </button>
    </div>
  );
}
