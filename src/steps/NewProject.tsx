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
import AtlasStatusBadge from "../components/ui/AtlasStatusBadge";
import {
  createCustomWorkflow,
  getWorkflowForProjectType,
  projectTypeOptions,
  type ProjectType,
  type WorkflowStep,
} from "../config/workflows";
import { computeSetupGuidance, isProjectSetupComplete, resolveProjectSetupFormConfig, type ProjectSetupFormConfig } from "../config/projectSetupForms";
import { logDecision } from "../lib/decisionJournal";
import { grantProjectAccess, me } from "../lib/auth";
import { upsertProjectFromState } from "../lib/localProjects";
import { defaultMonitoringMetricsForModelType, loadProjectContext, saveProjectContext } from "../lib/projectContext";
import { useWorkflowStore } from "../state/useWorkflowStore";
import { saveProjectToDatabase } from "../lib/serverPersistence";
import { projectWorkflowRoute } from "../lib/projectScopedRoutes";

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
  // UX-NEWPROJECT-001: this field previously started pre-filled with "Untitled
  // ATLAS Project" -- real content sitting in the input, not a placeholder --
  // which meant the "required" check was always satisfied without the user
  // ever typing anything. It now starts empty for every workflow type, and a
  // workflow-appropriate placeholder (ghost text, never saved) guides input
  // instead.
  const [projectName, setProjectName] = useState("");
  const [projectType, setProjectType] = useState<ProjectType>("predictive-modeling");
  const [projectCreationError, setProjectCreationError] = useState("");
  const [customWorkflowName, setCustomWorkflowName] = useState("Custom Workflow");
  const [customSteps, setCustomSteps] = useState(["Project Context", "Data Review", "Analysis", "Documentation"]);

  const selectedWorkflow = useMemo(() => {
    if (projectType === "custom-workflow") return createCustomWorkflow(customWorkflowName, customSteps);
    return getWorkflowForProjectType(projectType);
  }, [customSteps, customWorkflowName, projectType]);

  // UX-NEWPROJECT-001 (generalization): one shared, schema-driven setup config
  // per workflow type -- see src/config/projectSetupForms.ts. Field labels,
  // helper text, required-ness, button label, and guidance all come from this
  // config; no per-workflow JSX forks or duplicated validation logic below.
  const setupConfig = useMemo(
    () => resolveProjectSetupFormConfig(projectType, selectedWorkflow.label),
    [projectType, selectedWorkflow.label]
  );
  const setupValues = { name: projectName, modelId };
  const canStartProject = isProjectSetupComplete(setupConfig, setupValues);
  const setupGuidance = computeSetupGuidance(setupConfig, setupValues);

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
    setProjectCreationError("");
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
    const createdProject = upsertProjectFromState(nextState);
    if (!createdProject) {
      setProjectCreationError("ATLAS could not create the local project handoff required for durable registration.");
      return;
    }
    if (projectType === "predictive-modeling") {
      try {
        // Scoped workflow hydration starts with an exact backend GET. Await the
        // existing durable save so that request cannot race the compatibility
        // store's delayed mirror and produce a false project-not-found state.
        const saved = await saveProjectToDatabase(createdProject.snapshot);
        if (!saved) {
          throw new Error("the backend did not confirm the project and workflow-state save");
        }
      } catch (error) {
        setProjectCreationError(
          error instanceof Error
            ? `ATLAS could not establish the authoritative project record: ${error.message}`
            : "ATLAS could not establish the authoritative project record. Retry before opening the workflow.",
        );
        return;
      }
    }
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
    navigate(
      projectType === "predictive-modeling"
        ? projectWorkflowRoute(nextState.projectId, "/step00")
        : "/project-overview",
    );
  };

  return (
    <div className="atlas-page-shell">
      {projectCreationError ? (
        <section className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-900" role="alert">
          <div className="font-semibold">Project creation is not yet durable.</div>
          <p className="mt-1">{projectCreationError}</p>
        </section>
      ) : null}
      <UnifiedProjectSetupSection
        config={setupConfig}
        selectedWorkflow={selectedWorkflow}
        projectName={projectName}
        onProjectNameChange={setProjectName}
        modelId={modelId}
        onModelIdChange={setModelId}
        setupGuidance={setupGuidance}
        canStartProject={canStartProject}
        onSubmit={startProject}
      />

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
                  onClick={() => {
                    // UX-NEWPROJECT-001 (generalization): switching workflow types must
                    // not carry a stale value typed under a different field label/
                    // requirement (e.g. a Model Name typed for Predictive Modeling
                    // reappearing as "Project Name" for another workflow, or a Model ID
                    // typed while visible silently persisting after switching to a
                    // workflow where that field is hidden).
                    setProjectType(option.value);
                    setProjectName("");
                    setModelId("");
                  }}
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
    </div>
  );
}

/**
 * UX-NEWPROJECT-001 (generalized): the ONE shared, unified Project Setup
 * section used by every workflow type. Content (heading, description, field
 * labels/placeholders/helper text, required-ness, button label, and the
 * Required/Optional summary chips) is entirely driven by `config`
 * (ProjectSetupFormConfig) -- this component contains no per-workflow
 * branching of its own. It renders above the Workflow Library for every
 * workflow, replacing the old light hero + narrow right-column form.
 */
function UnifiedProjectSetupSection({
  config,
  selectedWorkflow,
  projectName,
  onProjectNameChange,
  modelId,
  onModelIdChange,
  setupGuidance,
  canStartProject,
  onSubmit,
}: {
  config: ProjectSetupFormConfig;
  selectedWorkflow: { label: string; steps: WorkflowStep[] };
  projectName: string;
  onProjectNameChange: (value: string) => void;
  modelId: string;
  onModelIdChange: (value: string) => void;
  setupGuidance: string;
  canStartProject: boolean;
  onSubmit: () => void;
}) {
  const nameFieldId = "new-project-name-field";
  const modelIdFieldId = "new-project-model-id-field";
  const nameInvalid = !projectName.trim();

  return (
    <section
      className="rounded-lg border border-blue-900/60 bg-blue-950 p-6 text-white shadow-sm sm:p-8"
      data-testid="unified-setup-section"
    >
      <div className="text-xs font-semibold uppercase tracking-[0.16em] text-sky-200">Project setup</div>
      <h1 className="mt-2 max-w-4xl text-3xl font-semibold tracking-tight sm:text-4xl">Start a governed ATLAS project</h1>
      <p className="mt-3 max-w-3xl text-sm leading-6 text-blue-100">
        Choose the analytical objective first. ATLAS will configure the workflow, evidence expectations, and documentation
        structure without changing the underlying project logic.
      </p>

      <div className="mt-5 flex flex-wrap gap-3" aria-label="Selected workflow summary">
        <SetupSummaryChip label="Selected Workflow" value={selectedWorkflow.label} />
        <SetupSummaryChip label="Steps" value={String(selectedWorkflow.steps.length)} />
        <SetupSummaryChip label="Required Setup" value={config.requiredSummary} />
        {config.optionalSummary && <SetupSummaryChip label="Optional" value={config.optionalSummary} />}
      </div>

      <form
        className="mt-6 rounded-lg border border-white/15 bg-white/5 p-5"
        onSubmit={(event) => {
          event.preventDefault();
          onSubmit();
        }}
      >
        <h2 className="text-lg font-semibold text-white" data-testid="unified-setup-title">
          {config.heading}
        </h2>
        <p className="mt-2 text-sm leading-6 text-blue-100">{config.description}</p>

        <div className={`mt-5 grid gap-4 ${config.modelIdField ? "sm:grid-cols-3" : ""}`}>
          <div className={`grid gap-1.5 ${config.modelIdField ? "sm:col-span-2" : ""}`}>
            <label htmlFor={nameFieldId} className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-blue-50">
              {config.nameField.label}
              <AtlasStatusBadge tone="neutral" className="normal-case tracking-normal">Required</AtlasStatusBadge>
            </label>
            <input
              id={nameFieldId}
              className={inputClass}
              value={projectName}
              onChange={(event) => onProjectNameChange(event.target.value)}
              placeholder={config.nameField.placeholder}
              required
              aria-required="true"
              aria-invalid={nameInvalid}
              aria-describedby={`${nameFieldId}-helper`}
            />
            <span id={`${nameFieldId}-helper`} className="text-xs leading-5 text-blue-100">
              {config.nameField.helperText}
            </span>
          </div>

          {config.modelIdField && (
            <div className="grid gap-1.5">
              <label htmlFor={modelIdFieldId} className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-blue-50">
                {config.modelIdField.label}
                <AtlasStatusBadge tone="neutral" className="normal-case tracking-normal">
                  {config.modelIdField.required ? "Required" : "Optional"}
                </AtlasStatusBadge>
              </label>
              <input
                id={modelIdFieldId}
                className={inputClass}
                value={modelId}
                onChange={(event) => onModelIdChange(event.target.value)}
                placeholder={config.modelIdField.placeholder}
                required={config.modelIdField.required}
                aria-required={config.modelIdField.required}
                aria-invalid={config.modelIdField.required && !modelId.trim()}
                aria-describedby={`${modelIdFieldId}-helper`}
              />
              <span id={`${modelIdFieldId}-helper`} className="text-xs leading-5 text-blue-100">
                {config.modelIdField.helperText}
              </span>
            </div>
          )}
        </div>

        <p className="mt-4 text-xs leading-5 text-blue-100" role="status" aria-live="polite" data-testid="setup-guidance">
          {setupGuidance}
        </p>

        <button
          type="submit"
          disabled={!canStartProject}
          className="atlas-primary-button mt-3 w-full justify-center sm:w-auto disabled:cursor-not-allowed disabled:bg-slate-400 disabled:text-white"
        >
          {config.buttonLabel}
          <ArrowRight size={15} />
        </button>
      </form>
    </section>
  );
}

function SetupSummaryChip({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-white/15 bg-white/10 px-3 py-2" data-testid={`setup-chip-${label}`}>
      <div className="text-[10px] font-semibold uppercase tracking-wide text-blue-200">{label}</div>
      <div className="mt-0.5 text-sm font-semibold text-white" data-testid={`setup-chip-${label}-value`}>{value}</div>
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
