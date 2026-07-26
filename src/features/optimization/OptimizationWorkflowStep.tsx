import { useEffect, useMemo, useRef, useState, type ChangeEvent, type ReactNode } from "react";
import {
  AlertTriangle,
  BarChart3,
  CheckCircle2,
  Database,
  Download,
  Gauge,
  LoaderCircle,
  Plus,
  RefreshCw,
  Scale,
  ShieldCheck,
  SlidersHorizontal,
  Sparkles,
  Trash2,
  Upload,
  type LucideIcon,
} from "lucide-react";
import StepShell from "../../components/StepShell";
import {
  AtlasAttentionPanel,
  AtlasDataScopeBadge,
  AtlasExecutionStatus,
  AtlasStatusStrip,
  AtlasWorkflowSection,
} from "../../components/ui/AtlasWorkflow";
import type { WorkflowStep } from "../../config/workflows";
import {
  OPTIMIZATION_TEMPLATE_REGISTRY,
  getOptimizationTemplate,
  getOptimizationTemplateInputRoles,
  normalizeOptimizationTemplateId,
  readStoredOptimizationTemplateId,
  storeOptimizationTemplateId,
  type OptimizationInputRoleId,
  type OptimizationTemplateId,
} from "../../config/optimizationTemplates";
import {
  getDatasetProfile,
  linkDatasetToProject,
  listDatasets,
  uploadDataset,
  type DatasetProfile,
  type DatasetSummary,
} from "../../lib/datasetLibrary";
import {
  formatOptimizationNumber,
  optimizationReadiness,
  profileOptimizationDataset,
  solveOptimization,
  type OptimizationConstraint,
  type OptimizationDatasetMapping,
  type OptimizationProfile,
  type OptimizationSolveResult,
  type OptimizationVariable,
  type TransportationDatasetReference,
} from "../../lib/optimizationWorkflow";
import { getProjectFromDatabase, saveProjectTemplateToDatabase } from "../../lib/serverPersistence";
import { useWorkflowStore } from "../../state/useWorkflowStore";
import TransportationOptimizationWorkflow, { invalidateTransportationOptimizationState, type OptimizationInputStrategy } from "./TransportationOptimizationWorkflow";

type Scenario = {
  id: string;
  name: string;
  objectiveScale: number;
  capacityScale: number;
  riskScale: number;
  note: string;
};

type ScenarioResult = {
  id: string;
  name: string;
  objectiveValue: number;
  improvement: number;
  feasible: boolean;
  bindingConstraintCount: number;
};

type SensitivityRow = {
  variable: string;
  baseCoefficient: number;
  lowObjective: number;
  baseObjective: number;
  highObjective: number;
  range: number;
  stability: "Stable" | "Sensitive";
};

type OptimizationWorkflowState = {
  templateId: OptimizationTemplateId;
  decisionTitle: string;
  businessObjective: string;
  decisionOwner: string;
  decisionCadence: string;
  population: string;
  governanceBoundary: string;
  sourceMode: "Governed dataset" | "Manual formulation";
  datasetId: string;
  datasetVersionId: string;
  datasetName: string;
  inputBundle: Partial<Record<OptimizationInputRoleId, TransportationDatasetReference>>;
  mapping: OptimizationDatasetMapping;
  profile: OptimizationProfile | null;
  dataConfirmed: boolean;
  objectiveName: string;
  direction: "Maximize" | "Minimize";
  objectiveUnit: string;
  baselineDescription: string;
  horizon: string;
  variables: OptimizationVariable[];
  constraints: OptimizationConstraint[];
  method: "Linear programming (LP)" | "Mixed-integer programming (MILP)" | "Risk-adjusted nonlinear";
  tolerance: number;
  timeLimitSeconds: number;
  riskPenalty: number;
  scenarios: Scenario[];
  scenarioResults: ScenarioResult[];
  result: OptimizationSolveResult | null;
  sensitivity: SensitivityRow[];
  validationChecks: Record<string, boolean>;
  validationNotes: string;
  recommendation: string;
  recommendationOwner: string;
  recommendationStatus: "Draft" | "Recommended" | "Approved" | "Rejected";
  alternatives: string;
  residualRisks: string;
  implementationOwner: string;
  implementationDate: string;
  rolloutStrategy: string;
  monitoringMetric: string;
  monitoringCadence: string;
  reoptimizationTrigger: string;
  fallbackAction: string;
  reviewer: string;
  approvalDate: string;
  savedAt: string;
};

type Props = {
  projectId: string;
  step: WorkflowStep;
  nextStep?: WorkflowStep;
  onComplete: () => boolean;
  navigationError?: string | null;
};

const STORAGE_PREFIX = "atlas-optimization-workflow";
const DEFAULT_MAPPING: OptimizationDatasetMapping = {
  itemColumn: "",
  objectiveColumn: "",
  lowerBoundColumn: "",
  upperBoundColumn: "",
  costColumn: "",
  riskColumn: "",
  groupColumn: "",
};

function id(prefix: string) {
  return `${prefix}-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 7)}`;
}

function initialState(): OptimizationWorkflowState {
  return {
    templateId: "generic_single_table",
    decisionTitle: "",
    businessObjective: "",
    decisionOwner: "",
    decisionCadence: "One-time decision",
    population: "",
    governanceBoundary: "",
    sourceMode: "Governed dataset",
    datasetId: "",
    datasetVersionId: "",
    datasetName: "",
    inputBundle: {},
    mapping: { ...DEFAULT_MAPPING },
    profile: null,
    dataConfirmed: false,
    objectiveName: "",
    direction: "Maximize",
    objectiveUnit: "",
    baselineDescription: "",
    horizon: "",
    variables: [],
    constraints: [],
    method: "Linear programming (LP)",
    tolerance: 1e-7,
    timeLimitSeconds: 30,
    riskPenalty: 0,
    scenarios: [
      { id: "base", name: "Base case", objectiveScale: 100, capacityScale: 100, riskScale: 100, note: "Current approved assumptions" },
      { id: "downside", name: "Downside", objectiveScale: 90, capacityScale: 85, riskScale: 125, note: "Lower value, tighter capacity, higher risk" },
      { id: "upside", name: "Upside", objectiveScale: 110, capacityScale: 110, riskScale: 90, note: "Higher value, more capacity, lower risk" },
    ],
    scenarioResults: [],
    result: null,
    sensitivity: [],
    validationChecks: {},
    validationNotes: "",
    recommendation: "",
    recommendationOwner: "",
    recommendationStatus: "Draft",
    alternatives: "",
    residualRisks: "",
    implementationOwner: "",
    implementationDate: "",
    rolloutStrategy: "Controlled pilot",
    monitoringMetric: "",
    monitoringCadence: "Monthly",
    reoptimizationTrigger: "",
    fallbackAction: "",
    reviewer: "",
    approvalDate: "",
    savedAt: "",
  };
}

function loadState(projectId: string): OptimizationWorkflowState {
  try {
    const parsed = JSON.parse(localStorage.getItem(`${STORAGE_PREFIX}:${projectId}`) || "null") as Partial<OptimizationWorkflowState> | null;
    if (!parsed) return initialState();
    const inputBundle = { ...(parsed.inputBundle ?? {}) };
    if (parsed.datasetId && !inputBundle.candidate_decision_table) {
      inputBundle.candidate_decision_table = { datasetId: parsed.datasetId, versionId: parsed.datasetVersionId };
    }
    return {
      ...initialState(),
      ...parsed,
      templateId: parsed.templateId === "manual_formulation" ? "manual_formulation" : "generic_single_table",
      inputBundle,
      mapping: { ...DEFAULT_MAPPING, ...(parsed.mapping ?? {}) },
      validationChecks: parsed.validationChecks ?? {},
    };
  } catch {
    return initialState();
  }
}

const GENERIC_CHARTER_FIELDS: Array<keyof OptimizationWorkflowState> = [
  "decisionTitle",
  "businessObjective",
  "decisionOwner",
  "decisionCadence",
  "population",
  "governanceBoundary",
];

function invalidateGenericOptimizationState(projectId: string, nextTemplateId: OptimizationTemplateId) {
  try {
    const saved = JSON.parse(localStorage.getItem(`${STORAGE_PREFIX}:${projectId}`) || "null") as Partial<OptimizationWorkflowState> | null;
    if (!saved) return;
    const reset = initialState();
    for (const field of GENERIC_CHARTER_FIELDS) {
      if (saved[field] !== undefined) (reset as Record<string, unknown>)[field] = saved[field] as unknown;
    }
    reset.templateId = nextTemplateId;
    reset.sourceMode = nextTemplateId === "manual_formulation" ? "Manual formulation" : "Governed dataset";
    localStorage.setItem(`${STORAGE_PREFIX}:${projectId}`, JSON.stringify(reset));
  } catch {
    localStorage.removeItem(`${STORAGE_PREFIX}:${projectId}`);
  }
}

function persistState(projectId: string, state: OptimizationWorkflowState) {
  const compact = {
    ...state,
    profile: state.profile ? { ...state.profile, candidateVariables: state.profile.candidateVariables.slice(0, 250) } : null,
    result: state.result ? { ...state.result, decisions: state.result.decisions.slice(0, 250), constraints: state.result.constraints.slice(0, 250) } : null,
    savedAt: new Date().toISOString(),
  };
  localStorage.setItem(`${STORAGE_PREFIX}:${projectId}`, JSON.stringify(compact));
  window.dispatchEvent(new CustomEvent("atlas-workflow-node-updated"));
  return compact;
}

function likelyColumn(columns: string[], patterns: RegExp[]) {
  return columns.find((column) => patterns.some((pattern) => pattern.test(column.toLowerCase()))) ?? "";
}

function suggestedMapping(columns: string[]): OptimizationDatasetMapping {
  return {
    itemColumn: likelyColumn(columns, [/^id$/, /item/, /product/, /campaign/, /account/, /name/]),
    objectiveColumn: likelyColumn(columns, [/objective/, /benefit/, /profit/, /return/, /value/, /yield/, /score/]),
    lowerBoundColumn: likelyColumn(columns, [/lower.*bound/, /^minimum$/, /^min$/]),
    upperBoundColumn: likelyColumn(columns, [/upper.*bound/, /^maximum$/, /^max$/, /capacity/]),
    costColumn: likelyColumn(columns, [/cost/, /spend/, /budget/]),
    riskColumn: likelyColumn(columns, [/risk/, /variance/, /volatility/, /loss/]),
    groupColumn: likelyColumn(columns, [/group/, /category/, /segment/, /portfolio/]),
  };
}

function constraintFormula(constraint: OptimizationConstraint) {
  return Object.entries(constraint.coefficients)
    .filter(([, coefficient]) => coefficient !== 0)
    .map(([name, coefficient]) => `${name}=${coefficient}`)
    .join(", ");
}

function parseConstraintFormula(value: string, variables: OptimizationVariable[]) {
  const validNames = new Set(variables.map((variable) => variable.name));
  return value.split(",").reduce<Record<string, number>>((output, entry) => {
    const [rawName, rawCoefficient] = entry.split("=");
    const name = rawName?.trim();
    const coefficient = Number(rawCoefficient);
    if (name && validNames.has(name) && Number.isFinite(coefficient)) output[name] = coefficient;
    return output;
  }, {});
}

function fieldClass() {
  return "w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-950 outline-none transition focus:border-blue-500 focus:ring-2 focus:ring-blue-100 disabled:bg-slate-100";
}

function permitsZeroDecision(state: OptimizationWorkflowState) {
  if (state.direction !== "Minimize" || !state.variables.length) return false;
  const zeroLowerBounds = state.variables.every((variable) => variable.lowerBound === 0);
  const positiveObjective = state.variables.every((variable) => variable.objectiveCoefficient > 0);
  const actionRequired = state.constraints.some((constraint) => {
    const serviceLike = constraint.category === "Service" || /demand|service|coverage|selection/i.test(constraint.name);
    return serviceLike && constraint.rhs > 0 && (constraint.sense === ">=" || constraint.sense === "=");
  });
  return zeroLowerBounds && positiveObjective && !actionRequired;
}

export default function OptimizationWorkflowStep(props: Props) {
  const [strategy, setStrategy] = useState<OptimizationInputStrategy>(() => readStoredOptimizationTemplateId(props.projectId));
  useEffect(() => {
    let active = true;
    void getProjectFromDatabase(props.projectId)
      .then((project) => {
        if (!active) return;
        const persistedTemplate = normalizeOptimizationTemplateId(project.templateId ?? project.metadata?.optimizationTemplateId);
        const persistedState = project.metadata?.optimizationState;
        if (persistedTemplate === "transportation_logistics" && persistedState && typeof persistedState === "object") {
          const key = `atlas-optimization-transportation:${props.projectId}`;
          if (!localStorage.getItem(key)) localStorage.setItem(key, JSON.stringify(persistedState));
        }
        storeOptimizationTemplateId(props.projectId, persistedTemplate);
        setStrategy(persistedTemplate);
      })
      .catch(() => {
        // Browser persistence remains the compatibility fallback while the backend is unavailable.
      });
    return () => { active = false; };
  }, [props.projectId]);

  const changeStrategy = (next: OptimizationInputStrategy) => {
    if (next === strategy) return;
    invalidateGenericOptimizationState(props.projectId, next);
    invalidateTransportationOptimizationState(props.projectId, next);
    const workflow = useWorkflowStore.getState();
    workflow.workflowSteps.forEach((workflowStep, index) => {
      workflow.setWorkflowStepStatus(workflowStep.id, index === 0 ? "complete" : index === 1 ? "in_progress" : "pending");
    });
    if (workflow.workflowSteps[1]) workflow.setCurrentStepId(workflow.workflowSteps[1].id);
    storeOptimizationTemplateId(props.projectId, next);
    void saveProjectTemplateToDatabase(props.projectId, next);
    setStrategy(next);
    window.dispatchEvent(new CustomEvent("atlas-workflow-node-updated"));
  };

  if (strategy === "transportation_logistics") {
    return <TransportationOptimizationWorkflow {...props} onStrategyChange={changeStrategy} />;
  }
  return <GenericOptimizationWorkflowStep key={strategy} {...props} strategy={strategy} onStrategyChange={changeStrategy} />;
}

function GenericOptimizationWorkflowStep({ projectId, step, nextStep, onComplete, navigationError, strategy, onStrategyChange }: Props & { strategy: OptimizationInputStrategy; onStrategyChange: (strategy: OptimizationInputStrategy) => void }) {
  const stepNumber = Number(step.id.split("-").pop() || "1");
  const [state, setState] = useState<OptimizationWorkflowState>(() => loadState(projectId));
  const stateRef = useRef(state);
  const [datasets, setDatasets] = useState<DatasetSummary[]>([]);
  const [schemaProfile, setSchemaProfile] = useState<DatasetProfile | null>(null);
  const [busy, setBusy] = useState<"datasets" | "upload" | "profile" | "solve" | "scenarios" | "sensitivity" | "">("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  const update = (patch: Partial<OptimizationWorkflowState>) => setState((current) => ({ ...current, ...patch }));
  const readiness = useMemo(() => optimizationReadiness(state), [state.variables, state.constraints, state.result, state.profile]);
  const selectedDataset = datasets.find((dataset) => dataset.datasetId === state.datasetId);
  const columns = schemaProfile?.schema.map((column) => column.name) ?? state.profile?.columns ?? [];

  useEffect(() => {
    stateRef.current = state;
    const timer = window.setTimeout(() => {
      try {
        persistState(projectId, state);
      } catch (saveError) {
        console.warn("ATLAS optimization autosave failed", saveError);
      }
    }, 250);
    return () => window.clearTimeout(timer);
  }, [projectId, state]);

  useEffect(() => {
    const sourceMode = strategy === "manual_formulation" ? "Manual formulation" : "Governed dataset";
    setState((current) => current.sourceMode === sourceMode ? current : {
      ...current,
      templateId: strategy,
      sourceMode,
      dataConfirmed: sourceMode === "Manual formulation" ? false : current.dataConfirmed,
      profile: sourceMode === "Manual formulation" ? null : current.profile,
    });
  }, [strategy]);

  useEffect(() => {
    let active = true;
    setBusy("datasets");
    listDatasets()
      .then((payload) => { if (active) setDatasets(payload.datasets); })
      .catch((datasetError) => { if (active) setError(datasetError instanceof Error ? datasetError.message : "Datasets could not be loaded."); })
      .finally(() => { if (active) setBusy(""); });
    return () => { active = false; };
  }, []);

  useEffect(() => {
    if (!state.datasetId || !state.datasetVersionId) return;
    let active = true;
    getDatasetProfile(state.datasetId, state.datasetVersionId)
      .then((payload) => { if (active) setSchemaProfile(payload.profile); })
      .catch(() => undefined);
    return () => { active = false; };
  }, [state.datasetId, state.datasetVersionId]);

  const selectDataset = async (datasetId: string) => {
    const dataset = datasets.find((item) => item.datasetId === datasetId);
    const versionId = dataset?.latestVersion?.versionId ?? "";
    update({
      datasetId,
      datasetVersionId: versionId,
      datasetName: dataset?.name ?? "",
      inputBundle: { ...state.inputBundle, candidate_decision_table: { datasetId, versionId } },
      dataConfirmed: false,
      profile: null,
      result: null,
      sensitivity: [],
      scenarioResults: [],
    });
    if (!datasetId || !versionId) return;
    setBusy("profile");
    setError("");
    try {
      const payload = await getDatasetProfile(datasetId, versionId);
      setSchemaProfile(payload.profile);
      const suggested = suggestedMapping(payload.profile.schema.map((column) => column.name));
      update({ mapping: suggested });
    } catch (profileError) {
      setError(profileError instanceof Error ? profileError.message : "Dataset schema could not be loaded.");
    } finally {
      setBusy("");
    }
  };

  const selectInputRole = async (roleId: OptimizationInputRoleId, datasetId: string) => {
    if (roleId === "candidate_decision_table") {
      await selectDataset(datasetId);
      return;
    }
    const dataset = datasets.find((item) => item.datasetId === datasetId);
    update({
      inputBundle: {
        ...state.inputBundle,
        [roleId]: { datasetId, versionId: dataset?.latestVersion?.versionId ?? "" },
      },
      result: null,
      sensitivity: [],
      scenarioResults: [],
      validationChecks: {},
    });
  };

  const uploadSource = async (event: ChangeEvent<HTMLInputElement>, roleId: OptimizationInputRoleId = "candidate_decision_table") => {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    setBusy("upload");
    setError("");
    try {
      const dataset = await uploadDataset({ file, name: file.name.replace(/\.[^.]+$/, ""), domain: "Optimization", sourceType: "File upload" });
      const versionId = dataset.latestVersion?.versionId ?? "";
      setDatasets((current) => [dataset, ...current.filter((item) => item.datasetId !== dataset.datasetId)]);
      await linkDatasetToProject(projectId, dataset.datasetId, versionId, `optimization_${roleId}`);
      const nextBundle = { ...state.inputBundle, [roleId]: { datasetId: dataset.datasetId, versionId } };
      if (roleId === "candidate_decision_table") {
        const payload = await getDatasetProfile(dataset.datasetId, versionId);
        setSchemaProfile(payload.profile);
        update({
          sourceMode: "Governed dataset",
          datasetId: dataset.datasetId,
          datasetVersionId: versionId,
          datasetName: dataset.name,
          inputBundle: nextBundle,
          mapping: suggestedMapping(payload.profile.schema.map((column) => column.name)),
          dataConfirmed: false,
          profile: null,
        });
      } else {
        update({ inputBundle: nextBundle, result: null, sensitivity: [], scenarioResults: [], validationChecks: {} });
      }
      setMessage(`${dataset.name} registered for ${roleId.replace(/_/g, " ")} with ${dataset.latestVersion?.rowCount.toLocaleString() ?? "0"} full-artifact rows.`);
    } catch (uploadError) {
      setError(uploadError instanceof Error ? uploadError.message : "Dataset upload failed.");
    } finally {
      setBusy("");
    }
  };

  const analyzeDataset = async () => {
    if (!state.datasetId) return;
    setBusy("profile");
    setError("");
    setMessage("");
    try {
      const profile = await profileOptimizationDataset({ datasetId: state.datasetId, versionId: state.datasetVersionId, mapping: state.mapping });
      const nextVariables = profile.candidateVariables.length ? profile.candidateVariables : state.variables;
      update({ profile, variables: nextVariables, dataConfirmed: profile.fullArtifact, result: null, scenarioResults: [], sensitivity: [] });
      setMessage(`Full dataset profile complete: ${profile.rowCount.toLocaleString()} rows and ${profile.validOptimizationRows.toLocaleString()} valid optimization records.`);
    } catch (profileError) {
      setError(profileError instanceof Error ? profileError.message : "Optimization data profiling failed.");
    } finally {
      setBusy("");
    }
  };

  const runSolve = async () => {
    setBusy("solve");
    setError("");
    setMessage("");
    try {
      const result = await solveOptimization({
        direction: state.direction,
        method: state.method,
        variables: state.variables,
        constraints: state.constraints,
        tolerance: state.tolerance,
        timeLimitSeconds: state.timeLimitSeconds,
        riskPenalty: state.riskPenalty,
      });
      update({ result, sensitivity: [], scenarioResults: [] });
      setMessage(result.success ? "Solver completed with an optimal, feasible solution." : `Solver completed, but review is required: ${result.message}`);
    } catch (solveError) {
      setError(solveError instanceof Error ? solveError.message : "Optimization solve failed.");
    } finally {
      setBusy("");
    }
  };

  const runScenarios = async () => {
    setBusy("scenarios");
    setError("");
    try {
      const results: ScenarioResult[] = [];
      for (const scenario of state.scenarios.slice(0, 8)) {
        const result = await solveOptimization({
          direction: state.direction,
          method: state.method,
          variables: state.variables.map((variable) => ({
            ...variable,
            objectiveCoefficient: variable.objectiveCoefficient * scenario.objectiveScale / 100,
            riskCoefficient: variable.riskCoefficient * scenario.riskScale / 100,
          })),
          constraints: state.constraints.map((constraint) => ({
            ...constraint,
            rhs: ["Capacity", "Budget", "Service"].includes(constraint.category) ? constraint.rhs * scenario.capacityScale / 100 : constraint.rhs,
          })),
          tolerance: state.tolerance,
          timeLimitSeconds: state.timeLimitSeconds,
          riskPenalty: state.riskPenalty,
        });
        results.push({ id: scenario.id, name: scenario.name, objectiveValue: result.riskAdjustedObjective, improvement: result.improvement, feasible: result.feasible, bindingConstraintCount: result.bindingConstraintCount });
      }
      update({ scenarioResults: results });
      setMessage(`${results.length} governed scenarios completed.`);
    } catch (scenarioError) {
      setError(scenarioError instanceof Error ? scenarioError.message : "Scenario analysis failed.");
    } finally {
      setBusy("");
    }
  };

  const runSensitivity = async () => {
    if (!state.result) return;
    setBusy("sensitivity");
    setError("");
    try {
      const ranked = [...state.variables].sort((a, b) => Math.abs(b.objectiveCoefficient) - Math.abs(a.objectiveCoefficient)).slice(0, 6);
      const rows: SensitivityRow[] = [];
      for (const variable of ranked) {
        const objectives: number[] = [];
        for (const scale of [0.9, 1.1]) {
          const result = await solveOptimization({
            direction: state.direction,
            method: state.method,
            variables: state.variables.map((item) => item.name === variable.name ? { ...item, objectiveCoefficient: item.objectiveCoefficient * scale } : item),
            constraints: state.constraints,
            tolerance: state.tolerance,
            timeLimitSeconds: state.timeLimitSeconds,
            riskPenalty: state.riskPenalty,
          });
          objectives.push(result.riskAdjustedObjective);
        }
        const range = Math.abs(objectives[1] - objectives[0]);
        const denominator = Math.max(1e-9, Math.abs(state.result.riskAdjustedObjective));
        rows.push({
          variable: variable.name,
          baseCoefficient: variable.objectiveCoefficient,
          lowObjective: objectives[0],
          baseObjective: state.result.riskAdjustedObjective,
          highObjective: objectives[1],
          range,
          stability: range / denominator <= 0.1 ? "Stable" : "Sensitive",
        });
      }
      update({ sensitivity: rows });
      setMessage("Sensitivity analysis completed for the six strongest objective coefficients.");
    } catch (sensitivityError) {
      setError(sensitivityError instanceof Error ? sensitivityError.message : "Sensitivity analysis failed.");
    } finally {
      setBusy("");
    }
  };

  const addVariable = () => update({ variables: [...state.variables, { name: `Decision_${state.variables.length + 1}`, objectiveCoefficient: 0, lowerBound: 0, upperBound: 1, integer: false, riskCoefficient: 0, costCoefficient: 0, group: "" }], result: null });
  const setVariable = (index: number, patch: Partial<OptimizationVariable>) => update({ variables: state.variables.map((variable, row) => row === index ? { ...variable, ...patch } : variable), result: null, sensitivity: [], scenarioResults: [] });
  const addConstraint = () => update({ constraints: [...state.constraints, { id: id("constraint"), name: `Constraint ${state.constraints.length + 1}`, coefficients: {}, sense: "<=", rhs: 0, category: "Capacity", hard: true }], result: null });
  const setConstraint = (index: number, patch: Partial<OptimizationConstraint>) => update({ constraints: state.constraints.map((constraint, row) => row === index ? { ...constraint, ...patch } : constraint), result: null, sensitivity: [], scenarioResults: [] });

  const validationItems = [
    ["formulation", "Objective, variables, bounds, and units independently reviewed"],
    ["constraints", "Hard constraints and policy rules reconciled to source documentation"],
    ["replication", "Solver result independently replicated with versioned inputs"],
    ["scenarios", "Downside, upside, and stress scenarios reviewed"],
    ["fairness", "Customer, conduct, fair-lending, and regulatory impacts assessed"],
    ["operations", "Recommended values are operationally executable"],
  ] as const;
  const validationCount = validationItems.filter(([key]) => state.validationChecks[key]).length;

  const disabledReason = stepGate(stepNumber, state, validationCount);
  const zeroDecisionRisk = permitsZeroDecision(state);
  const transportationShapeRisk = strategy === "generic_single_table"
    && columns.some((column) => /customer|destination|demand/i.test(column))
    && columns.filter((column) => /supplier|source|origin/i.test(column)).length >= 2;
  const heroMetrics = [
    { label: "Decision variables", value: readiness.configuredVariables.toLocaleString(), detail: `${readiness.boundedVariables} bounded`, tone: readiness.configuredVariables ? "info" as const : "warning" as const },
    { label: "Constraints", value: readiness.constraintCount.toLocaleString(), detail: state.result ? `${state.result.bindingConstraintCount} binding` : "Not solved", tone: readiness.constraintCount ? "neutral" as const : "warning" as const },
    { label: "Solver", value: state.method.replace(/\s*\(.+\)/, ""), detail: state.result?.status ?? "Not run", tone: state.result?.success ? "success" as const : "neutral" as const },
    { label: "Objective", value: state.result ? formatOptimizationNumber(state.result.riskAdjustedObjective) : state.direction, detail: state.objectiveUnit || "Unit not defined", tone: state.result?.success ? "success" as const : "neutral" as const },
  ];

  const exportPackage = () => {
    const payload = { projectId, exportedAt: new Date().toISOString(), workflow: "optimization", state: stateRef.current };
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `atlas-optimization-${projectId}.json`;
    anchor.click();
    URL.revokeObjectURL(url);
  };

  return (
    <StepShell
      title={`Step ${stepNumber}: ${step.label}`}
      subtitle={step.description}
      eyebrow="ATLAS Decision Science / Optimization"
      variant="modeling"
      heroMetrics={heroMetrics}
      nextLabel={nextStep ? `Continue to ${nextStep.label}` : "Complete Optimization Study"}
      nextDisabled={Boolean(disabledReason)}
      nextDisabledReason={disabledReason}
      onNext={() => {
        persistState(projectId, stateRef.current);
        return onComplete();
      }}
    >
      <div className="space-y-4">
        <AtlasStatusStrip
          label="Optimization evidence status"
          items={[
            { label: "Data", state: state.sourceMode === "Manual formulation" || state.profile?.fullArtifact ? "complete" : "pending", detail: state.profile ? `${state.profile.rowCount.toLocaleString()} rows` : state.sourceMode },
            { label: "Formulation", state: state.variables.length ? "complete" : "pending", detail: `${state.variables.length} variables` },
            { label: "Solve", state: state.result?.success ? "complete" : state.result ? "warning" : "pending", detail: state.result?.status ?? "Not run" },
            { label: "Validation", state: validationCount >= 5 ? "complete" : validationCount ? "current" : "pending", detail: `${validationCount}/6 checks` },
          ]}
        />

        {(error || navigationError) && <AtlasAttentionPanel title="Optimization action required" tone="danger">{error || navigationError}</AtlasAttentionPanel>}
        {message && <div className="flex items-start gap-2 rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-950"><CheckCircle2 size={17} className="mt-0.5 shrink-0" />{message}</div>}
        {zeroDecisionRisk && <AtlasAttentionPanel title="Zero-decision formulation risk" tone="warning">This formulation permits a zero-decision solution. Add minimum service, demand, coverage, or selection constraints if action is required.</AtlasAttentionPanel>}
        {transportationShapeRisk && <AtlasAttentionPanel title="Transportation matrix detected" tone="warning">This does not represent a transportation formulation. Use the transportation/logistics template to create route-level variables.</AtlasAttentionPanel>}

        {renderStep({
          stepNumber,
          state,
          update,
          datasets,
          selectedDataset,
          columns,
          schemaProfile,
          busy,
          selectDataset,
          selectInputRole,
          uploadSource,
          analyzeDataset,
          runSolve,
          runScenarios,
          runSensitivity,
          addVariable,
          setVariable,
          addConstraint,
          setConstraint,
          validationItems,
          validationCount,
          exportPackage,
          strategy,
          onStrategyChange,
        })}
      </div>
    </StepShell>
  );
}

type RenderContext = {
  stepNumber: number;
  state: OptimizationWorkflowState;
  update: (patch: Partial<OptimizationWorkflowState>) => void;
  datasets: DatasetSummary[];
  selectedDataset?: DatasetSummary;
  columns: string[];
  schemaProfile: DatasetProfile | null;
  busy: string;
  selectDataset: (datasetId: string) => Promise<void>;
  selectInputRole: (roleId: OptimizationInputRoleId, datasetId: string) => Promise<void>;
  uploadSource: (event: ChangeEvent<HTMLInputElement>, roleId?: OptimizationInputRoleId) => Promise<void>;
  analyzeDataset: () => Promise<void>;
  runSolve: () => Promise<void>;
  runScenarios: () => Promise<void>;
  runSensitivity: () => Promise<void>;
  addVariable: () => void;
  setVariable: (index: number, patch: Partial<OptimizationVariable>) => void;
  addConstraint: () => void;
  setConstraint: (index: number, patch: Partial<OptimizationConstraint>) => void;
  validationItems: readonly (readonly [string, string])[];
  validationCount: number;
  exportPackage: () => void;
  strategy: OptimizationInputStrategy;
  onStrategyChange: (strategy: OptimizationInputStrategy) => void;
};

function renderStep(context: RenderContext) {
  const { stepNumber, state, update } = context;
  if (stepNumber === 1) return <ProjectContext state={state} update={update} strategy={context.strategy} onStrategyChange={context.onStrategyChange} />;
  if (stepNumber === 2) return <DataAcquisition {...context} />;
  if (stepNumber === 3) return <DataFeasibility state={state} />;
  if (stepNumber === 4) return <ObjectiveFunction state={state} update={update} />;
  if (stepNumber === 5) return <VariableEditor {...context} />;
  if (stepNumber === 6) return <ConstraintEditor {...context} />;
  if (stepNumber === 7) return <SolverConfiguration state={state} update={update} />;
  if (stepNumber === 8) return <ScenarioAnalysis {...context} />;
  if (stepNumber === 9) return <OptimizeWorkspace {...context} />;
  if (stepNumber === 10) return <SensitivityWorkspace {...context} />;
  if (stepNumber === 11) return <ValidationWorkspace {...context} />;
  if (stepNumber === 12) return <DecisionWorkspace state={state} update={update} />;
  if (stepNumber === 13) return <ImplementationWorkspace state={state} update={update} />;
  return <DocumentationWorkspace {...context} />;
}

function OptimizationStrategySelector({ strategy, onChange }: { strategy: OptimizationInputStrategy; onChange: (strategy: OptimizationInputStrategy) => void }) {
  const options = Object.values(OPTIMIZATION_TEMPLATE_REGISTRY);
  return <div className="grid gap-3 lg:grid-cols-3">{options.map((option) => <button key={option.template_id} type="button" onClick={() => onChange(option.template_id)} className={`min-h-28 rounded-lg border p-4 text-left transition ${strategy === option.template_id ? "border-blue-500 bg-blue-50 shadow-sm ring-2 ring-blue-100" : "border-slate-200 bg-white hover:border-blue-300 hover:bg-slate-50"}`}><div className="flex items-center justify-between gap-3"><span className="font-semibold text-slate-950">{option.display_name}</span>{strategy === option.template_id && <CheckCircle2 size={17} className="text-blue-600" />}</div><p className="mt-2 text-xs leading-5 text-slate-600">{option.short_description}</p><div className="mt-3 text-[10px] font-semibold uppercase tracking-wide text-slate-500">{option.required_input_roles.length} required | {option.optional_input_roles.length} optional</div></button>)}</div>;
}

function ProjectContext({ state, update, strategy, onStrategyChange }: { state: OptimizationWorkflowState; update: (patch: Partial<OptimizationWorkflowState>) => void; strategy: OptimizationInputStrategy; onStrategyChange: (strategy: OptimizationInputStrategy) => void }) {
  return (
    <div className="space-y-4">
      <AtlasWorkflowSection eyebrow="Input strategy" title="Choose the optimization formulation" description="The selected strategy controls required inputs, variable grain, constraints, solver checks, scenarios, and evidence." tone="info">
        <OptimizationStrategySelector strategy={strategy} onChange={(next) => {
          update({ templateId: next, sourceMode: next === "manual_formulation" ? "Manual formulation" : "Governed dataset", dataConfirmed: false, profile: next === "manual_formulation" ? null : state.profile });
          onStrategyChange(next);
        }} />
      </AtlasWorkflowSection>
      <div className="grid gap-4 xl:grid-cols-[1.25fr_0.75fr]">
      <AtlasWorkflowSection eyebrow="Decision charter" title="Define the decision before the mathematics" description="Anchor the formulation to an accountable business action, population, horizon, value measure, and governance boundary." tone="info">
        <div className="grid gap-4 md:grid-cols-2">
          <TextField label="Optimization decision" value={state.decisionTitle} onChange={(value) => update({ decisionTitle: value })} placeholder="Example: Allocate monthly collections capacity" />
          <TextField label="Decision owner" value={state.decisionOwner} onChange={(value) => update({ decisionOwner: value })} placeholder="Accountable business owner" />
          <TextAreaField label="Business objective" value={state.businessObjective} onChange={(value) => update({ businessObjective: value })} placeholder="State what will improve, for whom, and how the result will be used." />
          <TextAreaField label="Eligible population / scope" value={state.population} onChange={(value) => update({ population: value })} placeholder="Define included entities, exclusions, geography, and time window." />
          <GuidedSelect label="Decision cadence" value={state.decisionCadence} options={["One-time decision", "Daily", "Weekly", "Monthly", "Quarterly", "Event triggered"]} onChange={(value) => update({ decisionCadence: value })} />
          <TextAreaField label="Governance boundary" value={state.governanceBoundary} onChange={(value) => update({ governanceBoundary: value })} placeholder="Policy, fair-lending, conduct, capital, liquidity, customer, or operational constraints." />
        </div>
      </AtlasWorkflowSection>
      <AtlasWorkflowSection eyebrow="Decision standard" title="What a defensible optimization must prove" tone="success">
        <Checklist items={["The objective represents business value without omitting material harm.", "Every controllable variable has explicit units and bounds.", "Hard constraints are encoded, not left as reviewer prose.", "A baseline and adverse scenarios make improvement credible.", "Feasibility, sensitivity, and implementation controls survive independent review."]} />
      </AtlasWorkflowSection>
      </div>
    </div>
  );
}

function DataAcquisition(context: RenderContext) {
  const { state, update, datasets, columns, schemaProfile, busy, selectInputRole, uploadSource, analyzeDataset, strategy, onStrategyChange } = context;
  const template = getOptimizationTemplate(strategy);
  const inputRoles = getOptimizationTemplateInputRoles(strategy);
  const assigned = (roleId: OptimizationInputRoleId) => {
    if (roleId === "candidate_decision_table") return Boolean(state.datasetId);
    return Boolean(state.inputBundle[roleId]?.datasetId);
  };
  const requiredAssigned = template.required_input_roles.filter(assigned).length;
  const optionalAssigned = template.optional_input_roles.filter(assigned).length;
  const datasetLabels = Object.fromEntries(datasets.map((dataset) => [dataset.datasetId, `${dataset.name} (${dataset.latestVersion?.rowCount.toLocaleString() ?? 0} rows)`]));
  return (
    <div className="space-y-4">
      <AtlasWorkflowSection eyebrow="Source strategy" title="Acquire and govern optimization inputs" description="Use a full registered artifact for production studies. Manual formulation remains available for transparent planning or problems whose coefficients are already approved." tone="info">
        <OptimizationStrategySelector strategy={strategy} onChange={(next) => {
          update({ templateId: next, sourceMode: next === "manual_formulation" ? "Manual formulation" : "Governed dataset", dataConfirmed: false, profile: next === "manual_formulation" ? null : state.profile });
          onStrategyChange(next);
        }} />
        <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-4">
          <div className="rounded-lg border border-blue-200 bg-white p-3"><MetaBlock label="Active template" value={template.display_name} /></div>
          <div className="rounded-lg border border-blue-200 bg-white p-3"><MetaBlock label="Decision grain" value={template.expected_decision_grain} /></div>
          <div className="rounded-lg border border-blue-200 bg-white p-3"><MetaBlock label="Default solver" value={template.default_solver} /></div>
          <div className="rounded-lg border border-blue-200 bg-white p-3"><MetaBlock label="Input completeness" value={`${requiredAssigned}/${template.required_input_roles.length} required | ${optionalAssigned}/${template.optional_input_roles.length} optional`} /></div>
        </div>
      </AtlasWorkflowSection>

      <AtlasWorkflowSection eyebrow="Template input contract" title={`${template.display_name} inputs`} description={template.short_description} tone={requiredAssigned === template.required_input_roles.length ? "success" : "neutral"}>
        {inputRoles.length ? <div className="grid gap-3 md:grid-cols-2">{inputRoles.map((role) => {
          const reference = role.role_id === "candidate_decision_table"
            ? { datasetId: state.datasetId, versionId: state.datasetVersionId }
            : state.inputBundle[role.role_id] ?? { datasetId: "", versionId: "" };
          const selected = datasets.find((dataset) => dataset.datasetId === reference.datasetId);
          const ready = Boolean(reference.datasetId);
          const detectedKeys = role.role_id === "candidate_decision_table"
            ? [state.mapping.itemColumn, state.mapping.objectiveColumn].filter(Boolean).join(", ") || role.detected_key_hints.join(", ")
            : role.detected_key_hints.join(", ");
          return <article key={role.role_id} className={`rounded-lg border p-4 ${ready ? "border-blue-200 bg-blue-50/40" : role.requirement === "required" ? "border-amber-200 bg-amber-50/40" : "border-slate-200 bg-slate-50"}`}>
            <div className="flex items-start justify-between gap-3"><div><div className="flex flex-wrap items-center gap-2"><h3 className="text-sm font-semibold text-slate-950">{role.display_name}</h3><span className={`rounded-md border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${role.requirement === "required" ? "border-blue-200 bg-blue-50 text-blue-800" : "border-slate-200 bg-white text-slate-600"}`}>{role.requirement}</span></div><p className="mt-2 text-xs leading-5 text-slate-600">{role.purpose}</p></div>{ready ? <CheckCircle2 size={18} className="shrink-0 text-emerald-600" /> : <Database size={18} className="shrink-0 text-slate-400" />}</div>
            <div className="mt-3 rounded-md border border-slate-200 bg-white p-3"><div className="text-[10px] font-semibold uppercase tracking-wide text-slate-500">Accepted shapes</div><ul className="mt-1 grid gap-1 text-xs leading-5 text-slate-700">{role.accepted_shapes.map((shape) => <li key={shape}>- {shape}</li>)}</ul></div>
            <div className="mt-3 grid gap-2 sm:grid-cols-[1fr_auto]"><GuidedSelect label="Selected dataset" value={reference.datasetId} options={datasets.map((dataset) => dataset.datasetId)} optionLabels={datasetLabels} onChange={(value) => void selectInputRole(role.role_id, value)} placeholder={busy === "datasets" ? "Loading datasets..." : "Select governed dataset"} /><label className="mt-6 inline-flex h-10 cursor-pointer items-center justify-center gap-2 rounded-lg border border-slate-300 bg-white px-3 text-xs font-semibold text-slate-800 shadow-sm hover:bg-slate-50"><Upload size={15} /> Upload<input type="file" accept=".csv,.txt" className="hidden" onChange={(event) => void uploadSource(event, role.role_id)} /></label></div>
            <dl className="mt-3 grid grid-cols-2 gap-2 border-t border-slate-200 pt-3 text-xs"><MetaBlock label="Input role" value={role.role_id} /><MetaBlock label="Selected dataset" value={selected?.name ?? "Not assigned"} /><MetaBlock label="Detected keys" value={detectedKeys} /><MetaBlock label="Rows" value={selected?.latestVersion?.rowCount.toLocaleString() ?? "Not loaded"} /><MetaBlock label="Columns" value={selected?.latestVersion?.columnCount ?? "Not loaded"} /><MetaBlock label="Validation" value={role.role_id === "candidate_decision_table" && state.profile?.fullArtifact ? "Full artifact profiled" : ready ? "Assigned; validation pending" : role.requirement === "required" ? "Required" : "Optional"} /><MetaBlock label="Evidence role" value={role.evidence_role} /><MetaBlock label="Evidence status" value={state.profile?.fullArtifact && role.role_id === "candidate_decision_table" ? "Capturable" : "Not captured"} /></dl>
          </article>;
        })}</div> : <div className="rounded-lg border border-slate-200 bg-slate-50 p-4 text-sm text-slate-700">This template does not require a dataset. Define the formulation directly on the variable and constraint pages.</div>}
        {state.sourceMode === "Manual formulation" && <label className="mt-4 flex cursor-pointer items-start gap-2 rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm font-semibold text-emerald-950"><input type="checkbox" checked={state.dataConfirmed} onChange={(event) => update({ dataConfirmed: event.target.checked })} className="mt-1 h-4 w-4 accent-emerald-600" /><span>I confirm that coefficient provenance and approval evidence will be attached to this study.</span></label>}
      </AtlasWorkflowSection>

      {state.sourceMode === "Governed dataset" && (
        <AtlasWorkflowSection eyebrow="Column mapping" title="Map the analytical grain and coefficients" description="ATLAS profiles the full registered artifact. Browser preview rows are never treated as optimization evidence." tone="neutral" action={state.profile ? <AtlasDataScopeBadge scope="full_dataset" rows={state.profile.rowCount} /> : undefined}>
          {!state.datasetId ? <EmptyState icon={Database} title="Select or upload a dataset" body="The mapping controls appear after ATLAS loads the registered schema." /> : (
            <>
              <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
                <ColumnSelect label="Item / decision ID column" value={state.mapping.itemColumn} columns={columns} onChange={(value) => update({ mapping: { ...state.mapping, itemColumn: value }, dataConfirmed: false })} required />
                <ColumnSelect label="Objective coefficient column" value={state.mapping.objectiveColumn} columns={columns} onChange={(value) => update({ mapping: { ...state.mapping, objectiveColumn: value }, dataConfirmed: false })} required />
                <ColumnSelect label="Lower bound column" value={state.mapping.lowerBoundColumn} columns={columns} onChange={(value) => update({ mapping: { ...state.mapping, lowerBoundColumn: value }, dataConfirmed: false })} />
                <ColumnSelect label="Upper bound column" value={state.mapping.upperBoundColumn} columns={columns} onChange={(value) => update({ mapping: { ...state.mapping, upperBoundColumn: value }, dataConfirmed: false })} />
                <ColumnSelect label="Cost coefficient column" value={state.mapping.costColumn} columns={columns} onChange={(value) => update({ mapping: { ...state.mapping, costColumn: value }, dataConfirmed: false })} />
                <ColumnSelect label="Risk coefficient column" value={state.mapping.riskColumn} columns={columns} onChange={(value) => update({ mapping: { ...state.mapping, riskColumn: value }, dataConfirmed: false })} />
                <ColumnSelect label="Group / portfolio column" value={state.mapping.groupColumn} columns={columns} onChange={(value) => update({ mapping: { ...state.mapping, groupColumn: value }, dataConfirmed: false })} />
              </div>
              <div className="mt-4 flex flex-wrap items-center justify-between gap-3 border-t border-slate-200 pt-4">
                <div className="text-sm text-slate-600">{schemaProfile ? `${schemaProfile.rowCount.toLocaleString()} rows, ${schemaProfile.columnCount} columns, ${schemaProfile.duplicateRowsSample.toLocaleString()} duplicate rows in the governed profile.` : "Schema is loading."}</div>
                <button type="button" className="atlas-primary-button inline-flex items-center gap-2" disabled={busy === "profile" || !state.mapping.itemColumn || !state.mapping.objectiveColumn} onClick={() => void analyzeDataset()}>
                  {busy === "profile" ? <LoaderCircle size={16} className="animate-spin" /> : <Sparkles size={16} />} Profile full dataset & materialize variables
                </button>
              </div>
            </>
          )}
        </AtlasWorkflowSection>
      )}
    </div>
  );
}

function DataFeasibility({ state }: { state: OptimizationWorkflowState }) {
  if (state.sourceMode === "Manual formulation") {
    return <AtlasWorkflowSection eyebrow="Manual input review" title="Formulation readiness" description="Manual studies rely on approved coefficient and bound evidence rather than a row-level dataset." tone="info"><EvidenceMetrics rows={[["Decision variables", state.variables.length], ["Bounded variables", state.variables.filter((item) => item.upperBound !== null).length], ["Constraints", state.constraints.length], ["Input source", "Manual formulation"]]} /><Checklist items={["Document coefficient source and approval date.", "Confirm common units and time horizon.", "Set lower and upper bounds for every variable.", "Retain a reproducible input file in the evidence package."]} /></AtlasWorkflowSection>;
  }
  if (!state.profile) return <EmptyState icon={Database} title="Full dataset profile has not been run" body="Return to Data Acquisition, complete required mappings, and profile the registered full artifact." />;
  const profile = state.profile;
  return (
    <div className="space-y-4">
      <AtlasWorkflowSection eyebrow="Full-artifact evidence" title="Data profile and formulation feasibility" tone={profile.warnings.length ? "warning" : "success"} action={<AtlasDataScopeBadge scope="full_dataset" rows={profile.rowCount} />}>
        <EvidenceMetrics rows={[["Registered rows", profile.rowCount], ["Valid optimization rows", profile.validOptimizationRows], ["Columns", profile.columnCount], ["Unique variable preview", profile.candidateVariables.length], ["Duplicate items", profile.duplicateItems], ["Artifact status", profile.fullArtifact ? "Confirmed" : "Blocked"]]} />
        {profile.warnings.length > 0 && <div className="mt-4"><AtlasAttentionPanel title="Profile review required">{profile.warnings.join(" ")}</AtlasAttentionPanel></div>}
      </AtlasWorkflowSection>
      <AtlasWorkflowSection eyebrow="Coefficient diagnostics" title="Mapped numeric ranges" description="Review scale, missingness, and bounds before declaring the mathematical formulation ready.">
        <DataTable headers={["Column", "Valid", "Missing", "Minimum", "Mean", "Maximum"]} rows={profile.numericSummary.map((row) => [row.column, row.validCount.toLocaleString(), row.missingCount.toLocaleString(), formatOptimizationNumber(row.minimum), formatOptimizationNumber(row.mean), formatOptimizationNumber(row.maximum)])} />
      </AtlasWorkflowSection>
    </div>
  );
}

function ObjectiveFunction({ state, update }: { state: OptimizationWorkflowState; update: (patch: Partial<OptimizationWorkflowState>) => void }) {
  const expression = state.variables.slice(0, 8).map((variable) => `${formatOptimizationNumber(variable.objectiveCoefficient)} x ${variable.name}`).join(" + ") || "Define decision variables to generate the objective expression.";
  return (
    <div className="grid gap-4 xl:grid-cols-[1fr_0.8fr]">
      <AtlasWorkflowSection eyebrow="Mathematical objective" title="Specify the value function" tone="info">
        <div className="grid gap-4 md:grid-cols-2">
          <TextField label="Objective name" value={state.objectiveName} onChange={(value) => update({ objectiveName: value })} placeholder="Expected net contribution" />
          <GuidedSelect label="Optimization direction" value={state.direction} options={["Maximize", "Minimize"]} onChange={(value) => update({ direction: value as OptimizationWorkflowState["direction"], result: null })} />
          <TextField label="Objective unit" value={state.objectiveUnit} onChange={(value) => update({ objectiveUnit: value })} placeholder="USD per month, basis points, minutes" />
          <TextField label="Optimization horizon" value={state.horizon} onChange={(value) => update({ horizon: value })} placeholder="Next month, 12 months, one campaign" />
          <TextAreaField label="Current-state baseline" value={state.baselineDescription} onChange={(value) => update({ baselineDescription: value })} placeholder="Describe the current policy or allocation used for comparison." />
        </div>
      </AtlasWorkflowSection>
      <AtlasWorkflowSection eyebrow="Transparent formula" title={`${state.direction} ${state.objectiveName || "objective"}`} tone="success">
        <div className="rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-4 font-mono text-sm leading-7 text-emerald-950">{expression}{state.variables.length > 8 ? ` + ${state.variables.length - 8} more terms` : ""}</div>
        <p className="mt-3 text-sm leading-6 text-slate-600">Risk-adjusted nonlinear mode subtracts the configured quadratic risk penalty from this gross objective when maximizing.</p>
      </AtlasWorkflowSection>
    </div>
  );
}

function VariableEditor(context: RenderContext) {
  const { state, update, addVariable, setVariable } = context;
  return (
    <AtlasWorkflowSection eyebrow="Controllable decisions" title="Decision variable contract" description="Each row must state a controllable quantity, its value coefficient, valid domain, optional risk coefficient, and whether fractional decisions are permitted." tone="info" action={<button type="button" className="atlas-secondary-button inline-flex items-center gap-2" onClick={addVariable}><Plus size={15} /> Add variable</button>}>
      {state.variables.length === 0 ? <EmptyState icon={SlidersHorizontal} title="No decision variables defined" body="Materialize mapped dataset rows or add a manual variable." action={<button type="button" className="atlas-primary-button" onClick={addVariable}>Add first variable</button>} /> : (
        <div className="overflow-x-auto rounded-xl border border-slate-200">
          <table className="min-w-[1040px] w-full border-collapse text-sm">
            <thead className="bg-slate-950 text-left text-[11px] uppercase tracking-wide text-slate-200"><tr><th className="px-3 py-3">Use</th><th className="px-3 py-3">Variable</th><th className="px-3 py-3">Value coefficient</th><th className="px-3 py-3">Lower</th><th className="px-3 py-3">Upper</th><th className="px-3 py-3">Risk coefficient</th><th className="px-3 py-3">Group</th><th className="px-3 py-3">Integer</th><th className="px-3 py-3"><span className="sr-only">Remove</span></th></tr></thead>
            <tbody className="divide-y divide-slate-100 bg-white">
              {state.variables.map((variable, index) => (
                <tr key={`${variable.name}-${index}`} className="hover:bg-blue-50/50">
                  <td className="px-3 py-2"><span className="inline-flex h-7 w-7 items-center justify-center rounded-md bg-emerald-50 text-emerald-700"><CheckCircle2 size={15} /></span></td>
                  <td className="px-3 py-2"><input className={`${fieldClass()} min-w-40`} value={variable.name} onChange={(event) => setVariable(index, { name: event.target.value })} /></td>
                  <td className="px-3 py-2"><NumericInput value={variable.objectiveCoefficient} onChange={(value) => setVariable(index, { objectiveCoefficient: value })} /></td>
                  <td className="px-3 py-2"><NumericInput value={variable.lowerBound} onChange={(value) => setVariable(index, { lowerBound: value })} /></td>
                  <td className="px-3 py-2"><NumericInput value={variable.upperBound ?? 0} onChange={(value) => setVariable(index, { upperBound: value })} /></td>
                  <td className="px-3 py-2"><NumericInput value={variable.riskCoefficient} onChange={(value) => setVariable(index, { riskCoefficient: value })} /></td>
                  <td className="px-3 py-2"><input className={`${fieldClass()} min-w-28`} value={variable.group} onChange={(event) => setVariable(index, { group: event.target.value })} /></td>
                  <td className="px-3 py-2"><input type="checkbox" checked={variable.integer} onChange={(event) => setVariable(index, { integer: event.target.checked })} className="h-4 w-4 accent-blue-600" /></td>
                  <td className="px-3 py-2"><button type="button" title="Remove variable" className="rounded-md p-2 text-slate-400 hover:bg-red-50 hover:text-red-700" onClick={() => update({ variables: state.variables.filter((_, row) => row !== index), result: null })}><Trash2 size={15} /></button></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </AtlasWorkflowSection>
  );
}

function ConstraintEditor(context: RenderContext) {
  const { state, update, addConstraint, setConstraint } = context;
  return (
    <div className="space-y-4">
      <AtlasWorkflowSection eyebrow="Feasible decision space" title="Constraints and non-negotiable business rules" description="Enter coefficients as variable=value pairs separated by commas. Example: Branch_A=1, Branch_B=1 with <= 100 encodes a shared capacity limit." tone="warning" action={<button type="button" className="atlas-secondary-button inline-flex items-center gap-2" onClick={addConstraint}><Plus size={15} /> Add constraint</button>}>
        {state.constraints.length === 0 ? <EmptyState icon={Scale} title="No constraints defined" body="Unconstrained studies are rarely operationally defensible. Add budget, capacity, risk, service, policy, or regulatory limits." action={<button type="button" className="atlas-primary-button" onClick={addConstraint}>Add first constraint</button>} /> : (
          <div className="grid gap-3">
            {state.constraints.map((constraint, index) => (
              <div key={constraint.id} className="grid gap-3 border-b border-slate-200 pb-4 last:border-0 last:pb-0 xl:grid-cols-[1fr_0.75fr_2fr_0.45fr_0.65fr_auto]">
                <TextField label="Constraint" value={constraint.name} onChange={(value) => setConstraint(index, { name: value })} />
                <GuidedSelect label="Constraint category" value={constraint.category} options={["Capacity", "Budget", "Risk", "Policy", "Service", "Regulatory", "Other"]} onChange={(value) => setConstraint(index, { category: value as OptimizationConstraint["category"] })} />
                <TextField label="Coefficient formula" value={constraintFormula(constraint)} onChange={(value) => setConstraint(index, { coefficients: parseConstraintFormula(value, state.variables) })} placeholder={state.variables.slice(0, 2).map((variable) => `${variable.name}=1`).join(", ")} />
                <GuidedSelect label="Constraint sense" value={constraint.sense} options={["<=", ">=", "="]} onChange={(value) => setConstraint(index, { sense: value as OptimizationConstraint["sense"] })} />
                <label className="grid content-start gap-1.5"><span className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">Right-hand side</span><NumericInput value={constraint.rhs} onChange={(value) => setConstraint(index, { rhs: value })} /></label>
                <button type="button" title="Remove constraint" className="mt-6 rounded-md p-2 text-slate-400 hover:bg-red-50 hover:text-red-700" onClick={() => update({ constraints: state.constraints.filter((_, row) => row !== index), result: null })}><Trash2 size={16} /></button>
              </div>
            ))}
          </div>
        )}
      </AtlasWorkflowSection>
      <AtlasAttentionPanel title="Financial-services control standard" tone="info">Encode hard policy, capital, liquidity, customer-treatment, concentration, fair-lending, conduct, and operational limits directly when mathematically representable. Keep reviewer prose for rationale, not as a substitute for executable constraints.</AtlasAttentionPanel>
    </div>
  );
}

function SolverConfiguration({ state, update }: { state: OptimizationWorkflowState; update: (patch: Partial<OptimizationWorkflowState>) => void }) {
  return (
    <div className="grid gap-4 xl:grid-cols-[1.1fr_0.9fr]">
      <AtlasWorkflowSection eyebrow="Execution policy" title="Solver configuration" description="Choose the simplest method that faithfully represents the decision. ATLAS records every numerical control for reproducibility." tone="info">
        <div className="grid gap-4 md:grid-cols-2">
          <GuidedSelect label="Solver method" value={state.method} options={["Linear programming (LP)", "Mixed-integer programming (MILP)", "Risk-adjusted nonlinear"]} onChange={(value) => update({ method: value as OptimizationWorkflowState["method"], result: null })} />
          <NumberField label="Feasibility tolerance" value={state.tolerance} step={0.0000001} onChange={(value) => update({ tolerance: Math.max(1e-10, value), result: null })} />
          <NumberField label="Time limit (seconds)" value={state.timeLimitSeconds} step={1} onChange={(value) => update({ timeLimitSeconds: Math.max(1, value), result: null })} />
          <NumberField label="Risk penalty" value={state.riskPenalty} step={0.01} onChange={(value) => update({ riskPenalty: Math.max(0, value), result: null })} />
        </div>
      </AtlasWorkflowSection>
      <AtlasWorkflowSection eyebrow="Method fit" title="ATLAS solver interpretation" tone="success">
        <Checklist items={state.method === "Linear programming (LP)" ? ["Continuous decisions", "Linear objective and constraints", "Globally optimal HiGHS solution", "Transparent binding-constraint evidence"] : state.method === "Mixed-integer programming (MILP)" ? ["Integer and yes/no decisions supported", "Linear objective and constraints", "MIP gap and search-node evidence", "Use only where indivisibility is real"] : ["Continuous bounded decisions", "Quadratic risk penalty", "SLSQP local constrained solution", "Stress starting assumptions and sensitivity"]} />
      </AtlasWorkflowSection>
    </div>
  );
}

function ScenarioAnalysis(context: RenderContext) {
  const { state, update, busy, runScenarios } = context;
  return (
    <div className="space-y-4">
      <AtlasWorkflowSection eyebrow="Assumption envelope" title="Baseline and scenario analysis" description="Scale value, constrained capacity, and risk independently. Defaults are planning assumptions and must be reviewed before execution." tone="info" action={<button type="button" className="atlas-primary-button inline-flex items-center gap-2" disabled={!state.variables.length || busy === "scenarios"} onClick={() => void runScenarios()}>{busy === "scenarios" ? <LoaderCircle size={16} className="animate-spin" /> : <RefreshCw size={16} />} Run scenarios</button>}>
        <div className="overflow-x-auto rounded-xl border border-slate-200"><table className="min-w-[900px] w-full text-sm"><thead className="bg-slate-950 text-left text-[11px] uppercase tracking-wide text-slate-200"><tr><th className="px-3 py-3">Scenario</th><th className="px-3 py-3">Objective %</th><th className="px-3 py-3">Capacity %</th><th className="px-3 py-3">Risk %</th><th className="px-3 py-3">Assumption</th></tr></thead><tbody className="divide-y divide-slate-100">{state.scenarios.map((scenario, index) => <tr key={scenario.id}><td className="px-3 py-2"><input className={fieldClass()} value={scenario.name} onChange={(event) => update({ scenarios: state.scenarios.map((item, row) => row === index ? { ...item, name: event.target.value } : item), scenarioResults: [] })} /></td>{(["objectiveScale", "capacityScale", "riskScale"] as const).map((key) => <td key={key} className="px-3 py-2"><NumericInput value={scenario[key]} onChange={(value) => update({ scenarios: state.scenarios.map((item, row) => row === index ? { ...item, [key]: value } : item), scenarioResults: [] })} /></td>)}<td className="px-3 py-2"><input className={`${fieldClass()} min-w-72`} value={scenario.note} onChange={(event) => update({ scenarios: state.scenarios.map((item, row) => row === index ? { ...item, note: event.target.value } : item), scenarioResults: [] })} /></td></tr>)}</tbody></table></div>
      </AtlasWorkflowSection>
      {state.scenarioResults.length > 0 && <AtlasWorkflowSection eyebrow="Scenario outcomes" title="Feasibility and value under stress" tone={state.scenarioResults.every((row) => row.feasible) ? "success" : "warning"}><DataTable headers={["Scenario", "Risk-adjusted objective", "Improvement", "Feasible", "Binding constraints"]} rows={state.scenarioResults.map((row) => [row.name, formatOptimizationNumber(row.objectiveValue), formatOptimizationNumber(row.improvement), row.feasible ? "Yes" : "No", row.bindingConstraintCount])} /></AtlasWorkflowSection>}
    </div>
  );
}

function OptimizeWorkspace(context: RenderContext) {
  const { state, busy, runSolve } = context;
  return (
    <div className="space-y-4">
      <AtlasWorkflowSection eyebrow="Governed execution" title="Solve the approved formulation" description="ATLAS executes the selected solver against the saved objective, variable domains, and constraints. A result is not decision-ready unless it is feasible." tone="info" action={<button type="button" className="atlas-primary-button inline-flex items-center gap-2" disabled={!state.variables.length || busy === "solve"} onClick={() => void runSolve()}>{busy === "solve" ? <LoaderCircle size={16} className="animate-spin" /> : <Sparkles size={16} />} Run optimization</button>}>
        <EvidenceMetrics rows={[["Variables", state.variables.length], ["Integer variables", state.variables.filter((variable) => variable.integer).length], ["Constraints", state.constraints.length], ["Method", state.method], ["Tolerance", state.tolerance], ["Time limit", `${state.timeLimitSeconds}s`]]} />
      </AtlasWorkflowSection>
      {!state.result ? <EmptyState icon={Gauge} title="No solver result yet" body="Run optimization to generate the recommended decision vector, feasibility review, objective improvement, and solver diagnostics." /> : <OptimizationResultView result={state.result} unit={state.objectiveUnit} />}
    </div>
  );
}

function OptimizationResultView({ result, unit }: { result: OptimizationSolveResult; unit: string }) {
  return (
    <div className="space-y-4">
      <AtlasWorkflowSection eyebrow="Solution outcome" title={result.success ? "Optimal feasible solution" : "Solution requires review"} tone={result.success ? "success" : "warning"} action={<AtlasExecutionStatus state={result.success ? "complete" : "failed"} label={result.status.replace(/_/g, " ")} detail={`${formatOptimizationNumber(result.runtimeMs, 1)} ms`} />}>
        <EvidenceMetrics rows={[["Gross objective", `${formatOptimizationNumber(result.objectiveValue)} ${unit}`.trim()], ["Risk-adjusted objective", `${formatOptimizationNumber(result.riskAdjustedObjective)} ${unit}`.trim()], ["Improvement vs lower-bound baseline", formatOptimizationNumber(result.improvement)], ["Binding constraints", `${result.bindingConstraintCount}/${result.constraintCount}`], ["Iterations / nodes", result.iterations], ["Optimality gap", result.optimalityGap === null ? "Not reported" : `${formatOptimizationNumber(result.optimalityGap * 100, 4)}%`]]} />
      </AtlasWorkflowSection>
      <div className="grid gap-4 xl:grid-cols-[1.1fr_0.9fr]">
        <AtlasWorkflowSection eyebrow="Decision vector" title="Recommended values"><DataTable headers={["Decision", "Value", "Contribution", "Risk cost", "Domain"]} rows={result.decisions.map((row) => [row.name, formatOptimizationNumber(row.value, 4), formatOptimizationNumber(row.objectiveContribution), formatOptimizationNumber(row.riskContribution), `${formatOptimizationNumber(row.lowerBound)} to ${row.upperBound === null ? "unbounded" : formatOptimizationNumber(row.upperBound)}${row.integer ? " / integer" : ""}`])} /></AtlasWorkflowSection>
        <AtlasWorkflowSection eyebrow="Constraint evidence" title="Feasibility and slack" tone={result.feasible ? "success" : "warning"}><DataTable headers={["Constraint", "LHS", "Rule", "RHS", "Slack", "Status"]} rows={result.constraints.map((row) => [row.name, formatOptimizationNumber(row.lhs), row.sense, formatOptimizationNumber(row.rhs), formatOptimizationNumber(row.slack), !row.feasible ? "VIOLATION" : row.binding ? "Binding" : "Slack"])} /></AtlasWorkflowSection>
      </div>
    </div>
  );
}

function SensitivityWorkspace(context: RenderContext) {
  const { state, busy, runSensitivity } = context;
  const maxRange = Math.max(1e-9, ...state.sensitivity.map((row) => row.range));
  return (
    <AtlasWorkflowSection eyebrow="Robustness" title="Sensitivity and tradeoff analysis" description="ATLAS perturbs the six strongest objective coefficients by -10% and +10%, re-solves the full model, and compares risk-adjusted outcomes." tone="info" action={<button type="button" className="atlas-primary-button inline-flex items-center gap-2" disabled={!state.result?.success || busy === "sensitivity"} onClick={() => void runSensitivity()}>{busy === "sensitivity" ? <LoaderCircle size={16} className="animate-spin" /> : <BarChart3 size={16} />} Run sensitivity analysis</button>}>
      {state.sensitivity.length === 0 ? <EmptyState icon={BarChart3} title="Sensitivity has not been run" body="Save a feasible optimized solution first, then perturb leading coefficients to identify fragile recommendations." /> : <div className="grid gap-3">{state.sensitivity.map((row) => <div key={row.variable} className="grid gap-2 border-b border-slate-100 pb-3 last:border-0 md:grid-cols-[13rem_1fr_8rem_6rem] md:items-center"><div><div className="font-semibold text-slate-950">{row.variable}</div><div className="text-xs text-slate-500">Coefficient {formatOptimizationNumber(row.baseCoefficient)}</div></div><div><div className="h-3 overflow-hidden rounded-full bg-slate-100"><div className={`h-full rounded-full ${row.stability === "Stable" ? "bg-emerald-500" : "bg-amber-500"}`} style={{ width: `${Math.max(4, row.range / maxRange * 100)}%` }} /></div><div className="mt-1 flex justify-between text-[10px] text-slate-500"><span>{formatOptimizationNumber(row.lowObjective)}</span><span>{formatOptimizationNumber(row.baseObjective)}</span><span>{formatOptimizationNumber(row.highObjective)}</span></div></div><div className="text-right font-semibold">Range {formatOptimizationNumber(row.range)}</div><span className={`rounded-full px-2 py-1 text-center text-xs font-semibold ${row.stability === "Stable" ? "bg-emerald-50 text-emerald-800" : "bg-amber-50 text-amber-900"}`}>{row.stability}</span></div>)}</div>}
    </AtlasWorkflowSection>
  );
}

function ValidationWorkspace(context: RenderContext) {
  const { state, update, validationItems, validationCount } = context;
  return (
    <div className="grid gap-4 xl:grid-cols-[1fr_0.8fr]">
      <AtlasWorkflowSection eyebrow="Independent challenge" title="Validation controls" description="Check each item only after the evidence exists. ATLAS separates mathematical success from business and governance acceptance." tone="info">
        <div className="grid gap-2">{validationItems.map(([key, label]) => <label key={key} className="flex cursor-pointer items-start gap-3 border-b border-slate-100 px-1 py-3 last:border-0"><input type="checkbox" checked={Boolean(state.validationChecks[key])} onChange={(event) => update({ validationChecks: { ...state.validationChecks, [key]: event.target.checked } })} className="mt-0.5 h-4 w-4 accent-blue-600" /><span><span className="block font-semibold text-slate-950">{label}</span><span className="mt-1 block text-xs leading-5 text-slate-500">Retain the reviewer, date, source artifact, result, and exceptions in the evidence package.</span></span></label>)}</div>
        <div className="mt-4"><TextAreaField label="Validation findings and exceptions" value={state.validationNotes} onChange={(value) => update({ validationNotes: value })} placeholder="Document independent replication, challenged assumptions, exceptions, and remediation." /></div>
      </AtlasWorkflowSection>
      <AtlasWorkflowSection eyebrow="Validation scorecard" title={`${validationCount} of 6 controls evidenced`} tone={validationCount >= 5 && state.result?.feasible ? "success" : "warning"}>
        <EvidenceMetrics rows={[["Solver feasible", state.result?.feasible ? "Yes" : "No"], ["Optimality evidence", state.result?.optimalityGap === null || state.result?.optimalityGap === undefined ? "Review" : `${formatOptimizationNumber(state.result.optimalityGap * 100, 4)}% gap`], ["Scenario coverage", `${state.scenarioResults.length}/${state.scenarios.length}`], ["Sensitivity coverage", state.sensitivity.length], ["Control evidence", `${validationCount}/6`]]} />
      </AtlasWorkflowSection>
    </div>
  );
}

function DecisionWorkspace({ state, update }: { state: OptimizationWorkflowState; update: (patch: Partial<OptimizationWorkflowState>) => void }) {
  const topDecisions = state.result?.decisions.slice(0, 5) ?? [];
  return (
    <div className="space-y-4">
      <AtlasWorkflowSection eyebrow="Definitive outcome" title="Decision recommendation" description="Translate the solver result into the business action that an accountable owner can approve, reject, or return for revision." tone="success">
        <div className="grid gap-4 md:grid-cols-2">
          <GuidedSelect label="Recommendation status" value={state.recommendationStatus} options={["Draft", "Recommended", "Approved", "Rejected"]} onChange={(value) => update({ recommendationStatus: value as OptimizationWorkflowState["recommendationStatus"] })} />
          <TextField label="Recommendation owner" value={state.recommendationOwner} onChange={(value) => update({ recommendationOwner: value })} />
          <TextAreaField label="Recommended action" value={state.recommendation} onChange={(value) => update({ recommendation: value })} placeholder="State the decision values to implement, expected improvement, and approval requested." />
          <TextAreaField label="Alternatives considered" value={state.alternatives} onChange={(value) => update({ alternatives: value })} placeholder="Describe baseline, conservative, or operationally simpler alternatives." />
          <TextAreaField label="Residual risks and limitations" value={state.residualRisks} onChange={(value) => update({ residualRisks: value })} placeholder="Document coefficient uncertainty, unmodeled constraints, fairness, operational, and implementation risks." />
        </div>
      </AtlasWorkflowSection>
      {topDecisions.length > 0 && <AtlasWorkflowSection eyebrow="Decision summary" title="Largest recommended contributions"><DataTable headers={["Decision", "Recommended value", "Objective contribution", "Group"]} rows={topDecisions.map((row) => [row.name, formatOptimizationNumber(row.value, 4), formatOptimizationNumber(row.objectiveContribution), row.group || "Unassigned"])} /></AtlasWorkflowSection>}
    </div>
  );
}

function ImplementationWorkspace({ state, update }: { state: OptimizationWorkflowState; update: (patch: Partial<OptimizationWorkflowState>) => void }) {
  return (
    <div className="grid gap-4 xl:grid-cols-[1fr_0.85fr]">
      <AtlasWorkflowSection eyebrow="Operationalization" title="Implementation and monitoring plan" description="A mathematically optimal solution is useful only when the operating system can apply, monitor, override, and reverse it safely." tone="info">
        <div className="grid gap-4 md:grid-cols-2">
          <TextField label="Implementation owner" value={state.implementationOwner} onChange={(value) => update({ implementationOwner: value })} />
          <TextField label="Target implementation date" type="date" value={state.implementationDate} onChange={(value) => update({ implementationDate: value })} />
          <GuidedSelect label="Rollout strategy" value={state.rolloutStrategy} options={["Controlled pilot", "Phased rollout", "Champion / challenger", "Shadow mode", "Full deployment", "Decision support only"]} onChange={(value) => update({ rolloutStrategy: value })} />
          <TextField label="Primary monitoring metric" value={state.monitoringMetric} onChange={(value) => update({ monitoringMetric: value })} placeholder="Realized value, constraint breach rate, service level" />
          <GuidedSelect label="Monitoring cadence" value={state.monitoringCadence} options={["Daily", "Weekly", "Monthly", "Quarterly", "Event triggered"]} onChange={(value) => update({ monitoringCadence: value })} />
          <TextAreaField label="Re-optimization trigger" value={state.reoptimizationTrigger} onChange={(value) => update({ reoptimizationTrigger: value })} placeholder="Demand shift, coefficient drift, capacity change, policy update, or performance threshold." />
          <TextAreaField label="Fallback / rollback action" value={state.fallbackAction} onChange={(value) => update({ fallbackAction: value })} placeholder="Define the safe baseline and owner authorized to invoke it." />
        </div>
      </AtlasWorkflowSection>
      <AtlasWorkflowSection eyebrow="Control loop" title="Decision monitoring architecture" tone="success"><Checklist items={["Compare realized objective value with optimized and baseline expectations.", "Monitor hard-constraint breaches and near-binding headroom.", "Track coefficient and demand drift at the decision grain.", "Log manual overrides with reason and accountable approver.", "Re-optimize on the documented trigger, not an undocumented schedule change.", "Retain the prior feasible decision as rollback." ]} /></AtlasWorkflowSection>
    </div>
  );
}

function DocumentationWorkspace(context: RenderContext) {
  const { state, update, validationCount, exportPackage } = context;
  const rows = [
    ["Decision charter", Boolean(state.decisionTitle && state.decisionOwner)],
    ["Data lineage / manual input provenance", state.sourceMode === "Manual formulation" ? Boolean(state.variables.length) : Boolean(state.profile?.fullArtifact)],
    ["Objective and units", Boolean(state.objectiveName && state.objectiveUnit)],
    ["Variable domains", state.variables.length > 0 && state.variables.every((variable) => variable.upperBound !== null && variable.upperBound >= variable.lowerBound)],
    ["Constraint register", state.constraints.length > 0],
    ["Solver evidence", Boolean(state.result?.success)],
    ["Scenario and sensitivity evidence", Boolean(state.scenarioResults.length && state.sensitivity.length)],
    ["Validation evidence", validationCount >= 5],
    ["Decision recommendation", Boolean(state.recommendation && state.recommendationOwner)],
    ["Implementation controls", Boolean(state.implementationOwner && state.monitoringMetric && state.fallbackAction)],
  ] as const;
  const ready = rows.filter(([, complete]) => complete).length;
  return (
    <div className="space-y-4">
      <AtlasWorkflowSection eyebrow="Governance package" title="Optimization study documentation" description="Package the complete chain from source artifact and mathematical formulation through execution, challenge, decision, and monitoring." tone={ready === rows.length ? "success" : "warning"} action={<button type="button" className="atlas-primary-button inline-flex items-center gap-2" onClick={exportPackage}><Download size={16} /> Export governed JSON</button>}>
        <div className="grid gap-4 lg:grid-cols-[0.7fr_1.3fr]">
          <div className="rounded-xl bg-slate-950 px-5 py-4 text-white"><div className="text-xs font-semibold uppercase tracking-wide text-sky-200">Documentation readiness</div><div className="mt-2 text-4xl font-semibold">{ready}/{rows.length}</div><div className="mt-2 text-sm text-slate-300">{ready === rows.length ? "Evidence package is complete for reviewer sign-off." : "Complete outstanding evidence before final approval."}</div></div>
          <div className="grid gap-2 sm:grid-cols-2">{rows.map(([label, complete]) => <div key={label} className={`flex items-center gap-2 rounded-lg border px-3 py-2 text-sm font-semibold ${complete ? "border-emerald-200 bg-emerald-50 text-emerald-900" : "border-amber-200 bg-amber-50 text-amber-950"}`}>{complete ? <CheckCircle2 size={15} /> : <AlertTriangle size={15} />}{label}</div>)}</div>
        </div>
        <div className="mt-4 grid gap-4 md:grid-cols-2"><TextField label="Final reviewer" value={state.reviewer} onChange={(value) => update({ reviewer: value })} /><TextField label="Approval date" type="date" value={state.approvalDate} onChange={(value) => update({ approvalDate: value })} /></div>
      </AtlasWorkflowSection>
      <AtlasWorkflowSection eyebrow="Package contents" title="Generated evidence inventory"><DataTable headers={["Artifact", "Evidence"]} rows={[["Data lineage", state.profile ? `${state.profile.datasetName}, version ${state.profile.versionId}, ${state.profile.rowCount.toLocaleString()} rows` : "Manual coefficient provenance"], ["Formulation", `${state.direction} ${state.objectiveName || "objective"}; ${state.variables.length} variables; ${state.constraints.length} constraints`], ["Solver", state.result ? `${state.result.method}; ${state.result.status}; ${formatOptimizationNumber(state.result.runtimeMs, 1)} ms` : "Not run"], ["Robustness", `${state.scenarioResults.length} scenarios; ${state.sensitivity.length} sensitivity tests`], ["Decision", state.recommendationStatus], ["Monitoring", `${state.monitoringCadence}; trigger: ${state.reoptimizationTrigger || "Not defined"}`]]} /></AtlasWorkflowSection>
    </div>
  );
}

function stepGate(stepNumber: number, state: OptimizationWorkflowState, validationCount: number) {
  if (stepNumber === 1 && (!state.decisionTitle.trim() || !state.businessObjective.trim() || !state.decisionOwner.trim())) return "Define the optimization decision, business objective, and accountable owner.";
  if (stepNumber === 2 && state.sourceMode === "Governed dataset" && !state.profile?.fullArtifact) return "Profile and confirm the governed full dataset artifact before continuing.";
  if (stepNumber === 2 && state.sourceMode === "Manual formulation" && !state.dataConfirmed) return "Confirm Manual formulation as the input strategy before continuing.";
  if (stepNumber === 3 && state.sourceMode === "Governed dataset" && !state.profile?.fullArtifact) return "A full-artifact profile is required.";
  if (stepNumber === 4 && (!state.objectiveName.trim() || !state.objectiveUnit.trim() || !state.horizon.trim())) return "Define the objective name, unit, and optimization horizon.";
  if (stepNumber === 5 && (!state.variables.length || state.variables.some((variable) => !variable.name.trim() || variable.upperBound === null || variable.upperBound < variable.lowerBound))) return "Define at least one uniquely named variable with valid lower and upper bounds.";
  if (stepNumber === 6 && !state.constraints.length) return "Encode at least one operational, financial, policy, risk, service, or regulatory constraint.";
  if (stepNumber === 7 && !state.method) return "Select a solver method and review numerical controls.";
  if (stepNumber === 8 && state.scenarioResults.length < state.scenarios.length) return "Run all configured baseline and stress scenarios.";
  if (stepNumber === 9 && !state.result?.success) return "Run the solver and obtain a feasible optimal result.";
  if (stepNumber === 10 && !state.sensitivity.length) return "Run coefficient sensitivity analysis on the saved solution.";
  if (stepNumber === 11 && (validationCount < 5 || !state.result?.feasible)) return "Evidence at least five validation controls and retain a feasible result.";
  if (stepNumber === 12 && (!state.recommendation.trim() || !state.recommendationOwner.trim() || state.recommendationStatus === "Draft")) return "Document an owned recommendation and move it beyond Draft.";
  if (stepNumber === 13 && (!state.implementationOwner.trim() || !state.monitoringMetric.trim() || !state.reoptimizationTrigger.trim() || !state.fallbackAction.trim())) return "Define implementation ownership, monitoring, re-optimization, and fallback controls.";
  if (stepNumber === 14 && (!state.reviewer.trim() || !state.approvalDate)) return "Record the final reviewer and approval date.";
  return "";
}

function MetaBlock({ label, value }: { label: string; value: ReactNode }) {
  return <div className="min-w-0"><dt className="text-[9px] font-semibold uppercase tracking-wide text-slate-500">{label}</dt><dd className="mt-1 break-words text-xs font-semibold leading-5 text-slate-800">{value}</dd></div>;
}

function GuidedSelect({ label, value, options, onChange, placeholder = "Select option", optionLabels }: { label: string; value: string; options: string[]; onChange: (value: string) => void; placeholder?: string; optionLabels?: Record<string, string> }) {
  return <label className="grid content-start gap-1.5"><span className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">{label}</span><select className={fieldClass()} value={value} onChange={(event) => onChange(event.target.value)}><option value="">{placeholder}</option>{options.map((option) => <option key={option} value={option}>{optionLabels?.[option] ?? option}</option>)}</select></label>;
}

function ColumnSelect({ label, value, columns, onChange, required = false }: { label: string; value: string; columns: string[]; onChange: (value: string) => void; required?: boolean }) {
  return <GuidedSelect label={`${label}${required ? " (required)" : ""}`} value={value} options={columns} onChange={onChange} placeholder={required ? "Select required column" : "Not mapped"} />;
}

function TextField({ label, value, onChange, placeholder, type = "text" }: { label: string; value: string; onChange: (value: string) => void; placeholder?: string; type?: string }) {
  return <label className="grid content-start gap-1.5"><span className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">{label}</span><input type={type} className={fieldClass()} value={value} placeholder={placeholder} onChange={(event) => onChange(event.target.value)} onInput={type === "date" ? (event) => onChange(event.currentTarget.value) : undefined} /></label>;
}

function TextAreaField({ label, value, onChange, placeholder }: { label: string; value: string; onChange: (value: string) => void; placeholder?: string }) {
  return <label className="grid content-start gap-1.5"><span className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">{label}</span><textarea rows={4} className={fieldClass()} value={value} placeholder={placeholder} onChange={(event) => onChange(event.target.value)} /></label>;
}

function NumberField({ label, value, onChange, step = 1 }: { label: string; value: number; onChange: (value: number) => void; step?: number }) {
  return <label className="grid content-start gap-1.5"><span className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">{label}</span><input type="number" step={step} className={fieldClass()} value={value} onChange={(event) => onChange(Number(event.target.value))} /></label>;
}

function NumericInput({ value, onChange }: { value: number; onChange: (value: number) => void }) {
  return <input type="number" step="any" className={`${fieldClass()} min-w-24`} value={Number.isFinite(value) ? value : 0} onChange={(event) => onChange(Number(event.target.value))} />;
}

function Checklist({ items }: { items: string[] }) {
  return <ul className="grid gap-3 text-sm leading-6 text-slate-700">{items.map((item) => <li key={item} className="flex items-start gap-2"><ShieldCheck size={16} className="mt-1 shrink-0 text-emerald-600" /><span>{item}</span></li>)}</ul>;
}

function EvidenceMetrics({ rows }: { rows: Array<[string, string | number]> }) {
  return <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">{rows.map(([label, value]) => <div key={label} className="border-l-2 border-blue-500 bg-slate-50 px-3 py-2"><div className="text-[10px] font-semibold uppercase tracking-wide text-slate-500">{label}</div><div className="mt-1 break-words text-sm font-semibold text-slate-950">{value}</div></div>)}</div>;
}

function DataTable({ headers, rows }: { headers: string[]; rows: Array<Array<string | number>> }) {
  return <div className="max-h-[520px] overflow-auto rounded-xl border border-slate-200"><table className="min-w-full border-collapse text-sm"><thead className="sticky top-0 z-[1] bg-slate-950 text-left text-[10px] uppercase tracking-wide text-slate-200"><tr>{headers.map((header) => <th key={header} className="whitespace-nowrap px-3 py-3">{header}</th>)}</tr></thead><tbody className="divide-y divide-slate-100 bg-white">{rows.length ? rows.map((row, index) => <tr key={index} className="hover:bg-blue-50/40">{row.map((value, column) => <td key={`${index}-${column}`} className="whitespace-nowrap px-3 py-2.5 text-slate-700 first:font-semibold first:text-slate-950">{value}</td>)}</tr>) : <tr><td colSpan={headers.length} className="px-4 py-8 text-center text-slate-500">No evidence rows available.</td></tr>}</tbody></table></div>;
}

function EmptyState({ icon: Icon, title, body, action }: { icon: LucideIcon; title: string; body: string; action?: ReactNode }) {
  return <div className="flex min-h-48 flex-col items-center justify-center rounded-xl border border-dashed border-slate-300 bg-slate-50 px-6 py-8 text-center"><Icon size={26} className="text-blue-600" /><div className="mt-3 font-semibold text-slate-950">{title}</div><p className="mt-1 max-w-xl text-sm leading-6 text-slate-600">{body}</p>{action && <div className="mt-4">{action}</div>}</div>;
}
