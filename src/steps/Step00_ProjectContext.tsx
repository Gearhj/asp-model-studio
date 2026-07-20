import type React from "react";
import { useEffect, useMemo, useState } from "react";
import {
  Check,
  CheckCircle2,
  Clipboard,
  ShieldCheck,
  Sparkles,
} from "lucide-react";
import LLMWritingAssist, { type WritingAssistAction } from "../components/LLMWritingAssist";
import StepShell from "../components/StepShell";
import {
  type AtlasWorkflowMetric,
} from "../components/ui/AtlasWorkflow";
import { me } from "../lib/auth";
import { createEvidence } from "../lib/evidenceGraph";
import { logDecision } from "../lib/decisionJournal";
import {
  canonicalModelType,
  loadProjectContext,
  predictiveModelTypeOptions,
  saveProjectContext,
  type ProjectContext,
  type PredictiveModelTypeSelection,
} from "../lib/projectContext";
import { savePredictiveProjectContextToDatabase } from "../lib/serverPersistence";
import { useWorkflowStore } from "../state/useWorkflowStore";

const inputClass = "atlas-input";
const labelClass = "text-[11px] font-semibold uppercase text-slate-600";
const deploymentModes = ["Research", "Development", "Validation", "Limited Pilot", "Production Candidate", "Production"];
const aiActions: WritingAssistAction[] = ["Improve clarity"];

type AssessmentState = "complete" | "incomplete" | "needs_clarification";
type MissingField = { key: string; label: string; sectionId: string };
type ReviewItem = { key: string; label: string; sectionId: string; state: AssessmentState; guidance: string };

function assessText(value: string): AssessmentState {
  const text = value.trim();
  if (!text) return "incomplete";
  const words = text.split(/\s+/).filter(Boolean);
  return text.length >= 24 && words.length >= 4 ? "complete" : "needs_clarification";
}

function assessWindows(observationWindow: string, performanceWindow: string): AssessmentState {
  if (!observationWindow.trim() && !performanceWindow.trim()) return "incomplete";
  return assessText(observationWindow) === "complete" && assessText(performanceWindow) === "complete"
    ? "complete"
    : "needs_clarification";
}

function reviewItems(context: ProjectContext): ReviewItem[] {
  return [
    { key: "businessObjective", label: "Business objective", sectionId: "business-decision", state: assessText(context.businessObjective), guidance: "State the decision or process and the outcome expected to improve." },
    { key: "intendedModelUse", label: "Intended model use", sectionId: "business-decision", state: assessText(context.intendedModelUse), guidance: "Name the user, action, and role of human judgment." },
    { key: "targetDefinition", label: "Target definition", sectionId: "target-population", state: assessText(context.targetDefinition), guidance: "Define the real-world outcome, not a dataset column." },
    { key: "populationDefinition", label: "Population definition", sectionId: "target-population", state: assessText(context.populationDefinition), guidance: "Define which records are eligible for scoring." },
    { key: "timeWindows", label: "Observation and performance windows", sectionId: "time-windows", state: assessWindows(context.observationWindow, context.performanceWindow), guidance: "Define information availability and outcome finalization timing." },
  ];
}

function getMissing(context: ProjectContext): MissingField[] {
  const identity: MissingField[] = [
    ["modelId", "Model ID", "model-identity"],
    ["projectName", "Project Name", "model-identity"],
    ["modelTypeSelection", "Model Type", "model-identity"],
  ].filter(([key]) => !String(context[key as keyof ProjectContext] ?? "").trim()).map(([key, label, sectionId]) => ({ key, label, sectionId }));
  const narrative = reviewItems(context)
    .filter((item) => item.state !== "complete")
    .map((item) => ({ key: item.key, label: item.label, sectionId: item.sectionId }));
  return [...identity, ...narrative];
}

function concise(value: string, fallback = "Not yet defined") {
  const text = value.trim().replace(/\s+/g, " ");
  if (!text) return fallback;
  const sentence = text.match(/^.*?[.!?](?:\s|$)/)?.[0]?.trim() || text;
  return sentence.length <= 150 ? sentence : `${sentence.slice(0, 147).trimEnd()}...`;
}

function buildMissionSummary(context: ProjectContext) {
  if (reviewItems(context).some((item) => item.state !== "complete")) return "";
  return [
    `This project will develop a ${context.modelTypeSelection.toLowerCase()} model for the following business objective: ${concise(context.businessObjective, "")}`,
    `The model output is intended to support this use: ${concise(context.intendedModelUse, "")}`,
    `The model will predict ${concise(context.targetDefinition, "").replace(/[.]$/, "")} for ${concise(context.populationDefinition, "").replace(/[.]$/, "")}.`,
    `The observation window is defined as ${concise(context.observationWindow, "").replace(/[.]$/, "")}; the performance window is ${concise(context.performanceWindow, "").replace(/[.]$/, "")}.`,
    `The current deployment mode is ${context.fraudDetails.deploymentMode}. Dataset binding, target-column selection, validation design, and model selection will be established in later workflow stages.`,
  ].join(" ");
}

function stateLabel(state: AssessmentState) {
  if (state === "complete") return "Complete";
  if (state === "needs_clarification") return "Needs clarification";
  return "Incomplete";
}

export default function Step00ProjectContext() {
  const projectId = useWorkflowStore((state) => state.projectId);
  const activeModelId = useWorkflowStore((state) => state.modelId);
  const activeProjectName = useWorkflowStore((state) => state.projectName);
  const setModelId = useWorkflowStore((state) => state.setModelId);
  const setProjectName = useWorkflowStore((state) => state.setProjectName);
  const markWorkflowStepComplete = useWorkflowStore((state) => state.markWorkflowStepComplete);
  const [context, setContext] = useState<ProjectContext>(() => loadProjectContext());
  const [validated, setValidated] = useState(false);
  const [saveState, setSaveState] = useState("Draft not saved in this session.");
  const [summaryDraft, setSummaryDraft] = useState("");
  const [currentUserId, setCurrentUserId] = useState("");

  const reviews = useMemo(() => reviewItems(context), [context]);
  const missing = useMemo(() => getMissing(context), [context]);
  const isComplete = missing.length === 0;
  const pageCompleted = isComplete && context.completionStatus === "complete" && Boolean(context.completedAt);

  useEffect(() => {
    window.dispatchEvent(new CustomEvent("atlas-project-context-updated", { detail: { projectContext: context } }));
  }, [context]);

  useEffect(() => {
    setContext((current) => {
      const modelId = current.modelId || activeModelId;
      const projectName = current.projectName || (activeProjectName === "Untitled ATLAS Project" ? "" : activeProjectName);
      return modelId === current.modelId && projectName === current.projectName ? current : { ...current, modelId, projectName };
    });
  }, [activeModelId, activeProjectName]);

  useEffect(() => {
    let active = true;
    me().then((response) => {
      if (active) setCurrentUserId(response.user.userId);
    }).catch(() => undefined);
    return () => { active = false; };
  }, []);

  const heroMetrics: AtlasWorkflowMetric[] = [
    { label: "Project", value: context.projectName || "Not defined", tone: context.projectName ? "info" : "warning" },
    { label: "Model ID", value: context.modelId || "Required", tone: context.modelId ? "neutral" : "warning" },
    { label: "Project Type", value: "Predictive Modeling" },
  ];

  const invalidateCompletion = (next: ProjectContext): ProjectContext => ({
    ...next,
    completionStatus: "draft",
    completedAt: undefined,
    completedBy: undefined,
    fraudDetails: { ...next.fraudDetails, completedAt: undefined },
  });

  const update = <K extends keyof ProjectContext>(key: K, value: ProjectContext[K]) => {
    setContext((current) => invalidateCompletion({ ...current, [key]: value }));
    setValidated(false);
  };

  const updateDetail = (key: "deploymentMode" | "approvedUses" | "prohibitedUses" | "humanReviewRequired" | "overrideAuthority", value: string) => {
    setContext((current) => invalidateCompletion({ ...current, fraudDetails: { ...current.fraudDetails, [key]: value } }));
    setValidated(false);
  };

  const updateModelType = (selection: PredictiveModelTypeSelection) => {
    setContext((current) => invalidateCompletion({
      ...current,
      modelType: canonicalModelType(selection),
      modelTypeSelection: selection,
      fraudDetails: { ...current.fraudDetails, modelSubtype: selection },
    }));
    setValidated(false);
  };

  const acceptAiDraft = (key: keyof ProjectContext, draft: string, action: WritingAssistAction) => {
    setContext((current) => invalidateCompletion({
      ...current,
      [key]: draft,
      acceptedAiDrafts: [
        ...current.acceptedAiDrafts,
        { field: String(key), action, text: draft, acceptedAt: new Date().toISOString(), acceptedBy: currentUserId || current.updatedBy },
      ],
    }));
    setValidated(false);
  };

  const acceptBoundaryDraft = (key: "approvedUses" | "prohibitedUses" | "humanReviewRequired" | "overrideAuthority", draft: string, action: WritingAssistAction) => {
    setContext((current) => invalidateCompletion({
      ...current,
      fraudDetails: { ...current.fraudDetails, [key]: draft },
      acceptedAiDrafts: [
        ...current.acceptedAiDrafts,
        { field: key, action, text: draft, acceptedAt: new Date().toISOString(), acceptedBy: currentUserId || current.updatedBy },
      ],
    }));
    setValidated(false);
  };

  const withCurrentUser = async (draft: ProjectContext) => {
    try {
      const response = await me();
      setCurrentUserId(response.user.userId);
      return { ...draft, updatedBy: response.user.userId };
    } catch {
      return draft;
    }
  };

  const persistDraft = async (draft: ProjectContext, message: string) => {
    setSaveState("Saving Project Context...");
    const identified = await withCurrentUser(draft);
    const saved = saveProjectContext(identified);
    setContext(saved);
    setModelId(saved.modelId);
    setProjectName(saved.projectName || "Untitled ATLAS Project");
    await savePredictiveProjectContextToDatabase(projectId, {
      projectName: saved.projectName,
      modelId: saved.modelId,
      projectContext: saved as unknown as Record<string, unknown>,
      validationStatus: getMissing(saved).length ? "incomplete" : saved.completionStatus === "complete" ? "complete" : "ready",
    });
    setSaveState(message);
    return saved;
  };

  const completePage = async () => {
    const requiredMissing = getMissing(context);
    setValidated(true);
    if (requiredMissing.length) {
      setSaveState("Complete or clarify the required fields before marking this page complete.");
      return false;
    }
    const completedAt = new Date().toISOString();
    const completed = await withCurrentUser({
      ...context,
      completionStatus: "complete",
      completedAt,
      completedBy: context.updatedBy,
      fraudDetails: { ...context.fraudDetails, completedAt },
    });
    completed.completedBy = completed.updatedBy;
    const saved = await persistDraft(completed, "Project Context marked complete. Continue to Data Acquisition when ready.");
    markWorkflowStepComplete("step00");
    logDecision({ workflowStep: "Project Context", actionType: "project_context_updated", subject: saved.projectName || "Project Context", newValue: { completion: "passed", mddSections: ["1", "3"] }, followStatus: "followed" });
    await createEvidence({
      projectId,
      projectName: saved.projectName,
      evidenceType: "governance",
      title: "Predictive Modeling Project Context",
      summary: saved.modelingMissionSummary || "Project Context completed with business objective, intended use, target definition, population definition, observation window, and performance window.",
      sourcePage: "Project Context",
      sourceRoute: "/step00",
      status: "needs_review",
      importance: "high",
      modelIds: saved.modelId ? [saved.modelId] : [],
      supportsSections: ["1", "3"],
      tags: ["predictive_modeling", "project_context", "modeling_mission"],
      payload: {
        businessObjective: saved.businessObjective,
        intendedModelUse: saved.intendedModelUse,
        targetDefinition: saved.targetDefinition,
        populationDefinition: saved.populationDefinition,
        observationWindow: saved.observationWindow,
        performanceWindow: saved.performanceWindow,
        deploymentMode: saved.fraudDetails.deploymentMode,
        modelType: saved.modelTypeSelection,
        modelingMissionSummary: saved.modelingMissionSummary || "",
      },
    });
    return true;
  };

  const continueToDataAcquisition = async () => {
    if (!isComplete) {
      setValidated(true);
      setSaveState(`Complete or clarify ${missing.length} required item${missing.length === 1 ? "" : "s"} before continuing.`);
      return false;
    }
    if (pageCompleted) {
      await persistDraft(context, "Project Context saved. Opening Data Acquisition.");
      return true;
    }
    return completePage();
  };

  const saveMissionEvidence = async () => {
    if (!context.modelingMissionSummary) return;
    await createEvidence({
      projectId,
      projectName: context.projectName,
      evidenceType: "governance",
      title: "Modeling Mission Summary",
      summary: context.modelingMissionSummary,
      sourcePage: "Project Context",
      sourceRoute: "/step00",
      status: "needs_review",
      importance: "high",
      modelIds: context.modelId ? [context.modelId] : [],
      supportsSections: ["1", "3"],
      tags: ["predictive_modeling", "modeling_mission"],
      payload: { modelingMissionSummary: context.modelingMissionSummary },
    });
    setSaveState("Modeling Mission Summary saved to the Evidence Center.");
  };

  const generateMissionSummaryDraft = () => {
    const draft = buildMissionSummary(context);
    if (!draft) {
      setSaveState("Complete the six narrative fields before generating a mission summary draft.");
      return;
    }
    setSummaryDraft(draft);
    setSaveState("AI draft generated. Accept, edit, or discard before saving it.");
  };

  const acceptMissionSummary = () => {
    const draft = summaryDraft.trim();
    if (!draft) return;
    setContext((current) => ({
      ...current,
      modelingMissionSummary: draft,
      acceptedAiDrafts: [
        ...current.acceptedAiDrafts,
        { field: "modelingMissionSummary", action: "Draft from current project context", text: draft, acceptedAt: new Date().toISOString(), acceptedBy: currentUserId || current.updatedBy },
      ],
    }));
    setSummaryDraft("");
    setSaveState("Modeling Mission Summary accepted. Continue to Data Acquisition will persist it.");
  };

  const scrollToSection = (sectionId: string) => document.getElementById(sectionId)?.scrollIntoView({ behavior: "smooth", block: "start" });
  const writingContext = {
    projectName: context.projectName,
    modelType: context.modelTypeSelection,
    businessObjective: context.businessObjective,
    intendedModelUse: context.intendedModelUse,
    targetDefinition: context.targetDefinition,
    populationDefinition: context.populationDefinition,
    observationWindow: context.observationWindow,
    performanceWindow: context.performanceWindow,
  };

  return (
    <StepShell
      title="Step 0: Define the Modeling Mission"
      subtitle="Define the business decision, target outcome, population, and time windows that will govern the model before data is connected."
      eyebrow="Predictive Modeling Workflow"
      heroMetrics={heroMetrics}
      showDeveloperTools={false}
      nextPath="/step01"
      nextLabel="Continue to Data Acquisition"
      nextDisabled={!isComplete}
      nextDisabledReason={`Complete or clarify ${missing.length} required item${missing.length === 1 ? "" : "s"} before continuing.`}
      nextStatusLine="Continue saves Project Context and opens Data Acquisition."
      onNext={continueToDataAcquisition}
    >
      <div className="space-y-5" id="project-context-top">
        <div className="grid gap-5 xl:grid-cols-[468px_minmax(0,1fr)]">
          <section id="model-identity" className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
            <div className="flex h-full flex-col gap-5">
              <div>
                <div className="text-[11px] font-bold uppercase tracking-wide text-blue-700">Model identity</div>
                <h2 className="mt-1 text-xl font-semibold text-slate-950">Project Setup</h2>
                <p className="mt-2 text-sm leading-6 text-slate-600">Confirm the project identity created on the New Project screen. Dataset, target column, split, and validation evidence are captured later.</p>
              </div>
              <div className="grid gap-3">
                <Field label="Model ID" required help="Assigned when the project is created."><input className={inputClass} value={context.modelId} readOnly aria-readonly="true" /></Field>
                <Field label="Project Name" required><input className={inputClass} value={context.projectName} onChange={(event) => update("projectName", event.target.value)} placeholder="Card transaction fraud model" /></Field>
                <Field label="Project Type"><input className={inputClass} value="Predictive Modeling" readOnly aria-readonly="true" /></Field>
                <Field label="Model Type" required><select className={inputClass} value={context.modelTypeSelection} onChange={(event) => updateModelType(event.target.value as PredictiveModelTypeSelection)}>{predictiveModelTypeOptions.map((option) => <option key={option}>{option}</option>)}</select></Field>
                <Field label="Deployment Mode"><select className={inputClass} value={context.fraudDetails.deploymentMode} onChange={(event) => updateDetail("deploymentMode", event.target.value)}>{deploymentModes.map((option) => <option key={option}>{option}</option>)}</select></Field>
              </div>
            </div>
          </section>

          <section id="business-decision" className="rounded-xl border border-blue-200 bg-blue-50/70 p-5 shadow-sm">
            <div className="mb-4">
              <div className="text-[11px] font-bold uppercase tracking-wide text-blue-700">Decision foundation</div>
              <h2 className="mt-1 text-xl font-semibold text-slate-950">Business Decision and Intended Use</h2>
              <p className="mt-1 max-w-3xl text-sm leading-6 text-slate-600">Anchor the model to a specific decision, user, action, and role for human judgment.</p>
            </div>
            <div className="grid gap-4">
              <NarrativeField label="Business Objective" required value={context.businessObjective} onChange={(value) => update("businessObjective", value)} onAccept={(draft, action) => acceptAiDraft("businessObjective", draft, action)} placeholder="What decision or business process should this model improve, and what outcome should improve?" context={writingContext} />
              <NarrativeField label="Intended Model Use" required value={context.intendedModelUse} onChange={(value) => update("intendedModelUse", value)} onAccept={(draft, action) => acceptAiDraft("intendedModelUse", draft, action)} placeholder="Who will use the model output, what action may follow, and how will human judgment remain involved?" context={writingContext} />
            </div>
            <details className="mt-4 rounded-lg border border-slate-200 bg-white px-4 py-3">
              <summary className="cursor-pointer text-sm font-semibold text-slate-900">Optional Use Boundaries</summary>
              <div className="mt-4 grid gap-4 xl:grid-cols-2">
                <NarrativeField label="Approved Uses" value={context.fraudDetails.approvedUses} onChange={(value) => updateDetail("approvedUses", value)} onAccept={(draft, action) => acceptBoundaryDraft("approvedUses", draft, action)} placeholder="Approved decisions or workflows" context={writingContext} />
                <NarrativeField label="Prohibited Uses" value={context.fraudDetails.prohibitedUses} onChange={(value) => updateDetail("prohibitedUses", value)} onAccept={(draft, action) => acceptBoundaryDraft("prohibitedUses", draft, action)} placeholder="Uses that remain outside project scope" context={writingContext} />
                <NarrativeField label="Human Review Expectations" value={context.fraudDetails.humanReviewRequired} onChange={(value) => updateDetail("humanReviewRequired", value)} onAccept={(draft, action) => acceptBoundaryDraft("humanReviewRequired", draft, action)} placeholder="Where human review remains required" context={writingContext} />
                <NarrativeField label="Override Authority" value={context.fraudDetails.overrideAuthority} onChange={(value) => updateDetail("overrideAuthority", value)} onAccept={(draft, action) => acceptBoundaryDraft("overrideAuthority", draft, action)} placeholder="Who may override and under what authority" context={writingContext} />
              </div>
            </details>
          </section>
        </div>

        <section id="target-population" className="rounded-xl border border-emerald-200 bg-emerald-50/50 p-5 shadow-sm">
          <div className="mb-4">
            <div className="text-[11px] font-bold uppercase tracking-wide text-emerald-700">Outcome and eligibility</div>
            <h2 className="mt-1 text-lg font-semibold text-slate-950">Target and Population</h2>
            <p className="mt-1 text-sm leading-6 text-slate-600">Define the outcome and eligible scoring population in business terms. Physical columns are selected during Data Acquisition.</p>
          </div>
          <div className="grid gap-4 xl:grid-cols-2">
            <NarrativeField label="Target Definition" required value={context.targetDefinition} onChange={(value) => update("targetDefinition", value)} onAccept={(draft, action) => acceptAiDraft("targetDefinition", draft, action)} placeholder="What real-world outcome will the model predict? Define the outcome in business terms rather than naming a dataset column." context={writingContext} />
            <NarrativeField label="Population Definition" required value={context.populationDefinition} onChange={(value) => update("populationDefinition", value)} onAccept={(draft, action) => acceptAiDraft("populationDefinition", draft, action)} placeholder="Which transactions, customers, accounts, applications, or other records are eligible for scoring?" context={writingContext} />
          </div>
        </section>

        <section id="time-windows" className="rounded-lg border border-slate-200 bg-white/80 p-4 shadow-sm">
          <div className="mb-3">
            <div className="text-[11px] font-bold uppercase tracking-wide text-slate-500">Time design</div>
            <h2 className="mt-1 text-base font-semibold text-slate-950">Observation and Performance Windows</h2>
          </div>
          <div className="grid gap-4 xl:grid-cols-2">
            <NarrativeField label="Observation Window" required value={context.observationWindow} onChange={(value) => update("observationWindow", value)} onAccept={(draft, action) => acceptAiDraft("observationWindow", draft, action)} placeholder="The period and information available when the model would generate a score." help="Example: Transaction attributes available at authorization time." context={writingContext} />
            <NarrativeField label="Performance Window" required value={context.performanceWindow} onChange={(value) => update("performanceWindow", value)} onAccept={(draft, action) => acceptAiDraft("performanceWindow", draft, action)} placeholder="The period after the observation date during which the final outcome is determined." help="Example: Fraud outcome finalized within 90 days after the transaction." context={writingContext} />
          </div>
        </section>

        <section id="project-context-review" className={`rounded-xl border p-4 shadow-sm ${pageCompleted ? "border-emerald-200 bg-emerald-50/60" : isComplete ? "border-blue-200 bg-blue-50/50" : "border-amber-200 bg-amber-50/45"}`}>
          <div className="mb-3">
            <div className="text-[11px] font-bold uppercase tracking-wide text-slate-500">Completion gate</div>
            <h2 className="mt-1 text-base font-semibold text-slate-950">Project Context Review</h2>
            <p className="mt-1 text-sm leading-6 text-slate-600">Confirm the modeling mission before data is connected.</p>
          </div>
          <div className="divide-y divide-slate-200 rounded-lg border border-slate-200 bg-white">
            {reviews.map((item) => (
              <button key={item.key} type="button" className="grid w-full gap-2 px-4 py-3 text-left sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center" onClick={() => scrollToSection(item.sectionId)}>
                <span><span className="block text-sm font-semibold text-slate-950">{item.label}</span><span className="mt-0.5 block text-xs text-slate-500">{item.state === "complete" ? "Required context is clear." : item.guidance}</span></span>
                <ReviewStatus state={item.state} />
              </button>
            ))}
          </div>

          {validated ? <div className={`mt-4 rounded-lg border px-4 py-3 text-sm ${isComplete ? "border-emerald-200 bg-emerald-50 text-emerald-900" : "border-amber-200 bg-amber-50 text-amber-900"}`}>{isComplete ? "Required Project Context fields are valid." : `${missing.length} required item${missing.length === 1 ? " needs" : "s need"} attention.`}</div> : null}

          <div className="mt-4 rounded-lg border border-blue-200 bg-blue-50/70 p-4" data-testid="modeling-mission-summary-workspace">
            <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
              <div>
                <div className="text-xs font-semibold uppercase text-blue-700">Optional AI draft</div>
                <h3 className="mt-1 text-sm font-semibold text-slate-950">Modeling Mission Summary</h3>
                <p className="mt-1 text-xs leading-5 text-slate-600">This summary is not required to complete the page. Generate it only when you want draft documentation language.</p>
              </div>
              <button type="button" className="atlas-primary-button" onClick={generateMissionSummaryDraft}><Sparkles size={14} /> Generate Modeling Mission Summary</button>
            </div>
            {context.modelingMissionSummary ? (
              <div className="mt-4 rounded-lg border border-emerald-200 bg-white p-3" data-testid="accepted-modeling-mission-summary">
                <div className="text-xs font-semibold uppercase text-emerald-700">Accepted summary</div>
                <p className="mt-2 text-sm leading-6 text-slate-800">{context.modelingMissionSummary}</p>
                <div className="mt-3 flex flex-wrap gap-2">
                  <button type="button" className="atlas-secondary-button" onClick={() => { void navigator.clipboard.writeText(context.modelingMissionSummary).then(() => setSaveState("Modeling Mission Summary copied.")); }}><Clipboard size={14} /> Copy Summary</button>
                  <button type="button" className="atlas-secondary-button" onClick={() => void saveMissionEvidence()}><ShieldCheck size={14} /> Save to Evidence Center</button>
                  <button type="button" className="atlas-secondary-button" onClick={() => { setSummaryDraft(context.modelingMissionSummary); setContext((current) => ({ ...current, modelingMissionSummary: "" })); }}>Edit Summary</button>
                </div>
              </div>
            ) : null}
            {summaryDraft ? (
              <div className="mt-4 rounded-lg border border-blue-200 bg-white p-3">
                <div className="text-xs font-semibold uppercase text-blue-700">AI draft - not saved until accepted</div>
                <textarea className={`${inputClass} mt-2 min-h-[132px]`} value={summaryDraft} onChange={(event) => setSummaryDraft(event.target.value)} aria-label="Editable AI Modeling Mission Summary draft" />
                <div className="mt-3 flex flex-wrap gap-2">
                  <button type="button" className="atlas-primary-button" onClick={acceptMissionSummary}><Check size={14} /> Accept Summary</button>
                  <button type="button" className="atlas-secondary-button" onClick={() => setSummaryDraft("")}>Discard</button>
                </div>
              </div>
            ) : null}
          </div>

          <div className="mt-4 rounded-lg border border-slate-200 bg-white px-4 py-3 text-xs text-slate-600"><b>Documentation mapping:</b> Business purpose and intended use support the model overview. Target, population, and time windows support the outcome-definition sections. Dataset and model evidence are assembled later.</div>
        </section>

        <div className="rounded-lg border border-slate-200 bg-white px-4 py-3 text-sm text-slate-700" aria-live="polite"><span className="font-semibold">Save status:</span> {saveState}</div>
      </div>
    </StepShell>
  );
}

function Field({ label, children, required = false, help }: { label: string; children: React.ReactNode; required?: boolean; help?: string }) {
  return <label className="grid content-start gap-1.5"><span className={labelClass}>{label}{required ? <span className="text-rose-600"> *</span> : null}</span>{children}{help ? <span className="text-xs leading-5 text-slate-500">{help}</span> : null}</label>;
}

function NarrativeField({ label, value, onChange, onAccept, placeholder, help, required = false, context }: { label: string; value: string; onChange: (value: string) => void; onAccept: (draft: string, action: WritingAssistAction) => void; placeholder?: string; help?: string; required?: boolean; context: Record<string, unknown> }) {
  return <div className="rounded-lg border border-slate-200 bg-white p-3"><LLMWritingAssist label={`${label}${required ? " (required)" : ""}`} value={value} onChange={onChange} onAcceptDraft={onAccept} actions={aiActions} strictGrounding context={context} placeholder={placeholder} minHeightClass="min-h-[112px]" />{help ? <p className="mt-2 text-xs leading-5 text-slate-500">{help}</p> : null}</div>;
}

function ReviewStatus({ state }: { state: AssessmentState }) {
  const className = state === "complete" ? "border-emerald-200 bg-emerald-50 text-emerald-800" : state === "needs_clarification" ? "border-amber-200 bg-amber-50 text-amber-800" : "border-slate-200 bg-slate-50 text-slate-600";
  return <span className={`inline-flex items-center gap-1.5 rounded-lg border px-2.5 py-1 text-xs font-semibold ${className}`}>{state === "complete" ? <CheckCircle2 size={13} /> : null}{stateLabel(state)}</span>;
}
