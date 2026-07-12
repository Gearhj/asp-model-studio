import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ArrowDown, ArrowUp, Plus, Trash2 } from "lucide-react";
import BrandLogo from "../components/BrandLogo";
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

const inputClass =
  "w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 shadow-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100";

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

  const startProject = async () => {
    if (!canStartProject) return;
    const projectIdentifier = modelId.trim() || `${selectedWorkflow.id}-${Date.now()}`;
    const workflowSteps: WorkflowStep[] | undefined = projectType === "custom-workflow" ? selectedWorkflow.steps : undefined;
    const modelType = projectType === "forecasting" || projectType === "optimization" ? "regression" : "generic classification";
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
    <div className="w-full space-y-5">
      <section className="rounded-xl border border-slate-200/80 bg-white/90 p-5 shadow-sm">
        <BrandLogo size="md" variant="light" showSubtitle className="mb-3" />
        <h1 className="text-xl font-semibold text-slate-950">New Project</h1>
        <p className="mt-1 max-w-3xl text-sm text-slate-600">
          Select a project type so ATLAS can configure the correct workflow, recommendations, and documentation structure.
        </p>
      </section>

      <section className="grid gap-5 xl:grid-cols-[0.8fr_1.2fr]">
        <div className="rounded-lg border border-slate-200/80 bg-white/90 p-5 shadow-sm">
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
            <span className="text-xs text-slate-500">
              {requiresModelId ? "Required. Example: 15211 Portfolio Attrition Model." : `Optional for ${selectedWorkflow.label}. ATLAS will create a project identifier if left blank.`}
            </span>
          </label>

          <div className="mt-4 grid gap-2">
            <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Project type</div>
            {projectTypeOptions.map((option) => (
              <button
                key={option.value}
                type="button"
                className={`rounded-lg border px-3 py-3 text-left transition ${
                  projectType === option.value ? "border-blue-300 bg-blue-50 text-blue-950" : "border-slate-200 bg-slate-50 text-slate-700 hover:bg-white"
                }`}
                onClick={() => setProjectType(option.value)}
              >
                <div className="text-sm font-semibold">{option.label}</div>
                <div className="mt-1 text-xs leading-5 opacity-80">{option.description}</div>
              </button>
            ))}
          </div>
        </div>

        <div className="rounded-lg border border-slate-200/80 bg-white/90 p-5 shadow-sm">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
            <div>
              <h2 className="text-sm font-semibold text-slate-950">{selectedWorkflow.label}</h2>
              <p className="mt-1 text-sm leading-6 text-slate-600">{selectedWorkflow.description}</p>
            </div>
            <button
              type="button"
              onClick={startProject}
              disabled={!canStartProject}
              title={!canStartProject ? (requiresModelId ? "Model ID # is required" : "Project name is required") : "Start Project"}
              className={`rounded-lg px-3 py-2 text-sm font-semibold text-white shadow-sm ${
                canStartProject ? "bg-slate-950 hover:bg-slate-800" : "cursor-not-allowed bg-slate-400"
              }`}
            >
              Start Project
            </button>
          </div>

          {projectType === "custom-workflow" && (
            <CustomWorkflowEditor
              name={customWorkflowName}
              steps={customSteps}
              onNameChange={setCustomWorkflowName}
              onStepsChange={setCustomSteps}
            />
          )}

          <div className="mt-5 grid gap-2">
            {selectedWorkflow.steps.map((step, index) => (
              <div key={`${step.id}-${index}`} className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-3">
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
        </div>
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
    <div className="mt-5 rounded-lg border border-blue-200 bg-blue-50 p-4">
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
              <button type="button" className="rounded-lg border border-blue-200 bg-white p-2 text-blue-900" onClick={() => move(index, -1)}>
                <ArrowUp size={15} />
              </button>
              <button type="button" className="rounded-lg border border-blue-200 bg-white p-2 text-blue-900" onClick={() => move(index, 1)}>
                <ArrowDown size={15} />
              </button>
              <button type="button" className="rounded-lg border border-blue-200 bg-white p-2 text-blue-900" onClick={() => onStepsChange(steps.filter((_, stepIndex) => stepIndex !== index))}>
                <Trash2 size={15} />
              </button>
            </div>
          </div>
        ))}
      </div>
      <button
        type="button"
        className="mt-3 inline-flex items-center gap-2 rounded-lg border border-blue-200 bg-white px-3 py-2 text-sm font-semibold text-blue-900"
        onClick={() => onStepsChange([...steps, `Step ${steps.length + 1}`])}
      >
        <Plus size={15} />
        Add Step
      </button>
    </div>
  );
}
