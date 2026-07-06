import type React from "react";
import { useMemo, useState } from "react";
import LLMWritingAssist from "../components/LLMWritingAssist";
import StepShell from "../components/StepShell";
import { getWorkflowForProjectType, projectTypeOptions, type ProjectType } from "../config/workflows";
import { logDecision } from "../lib/decisionJournal";
import {
  defaultProjectContext,
  modelTypeOptions,
  regulatoryOptions,
  saveProjectContext,
  summarizeRegulatoryContext,
  type DeploymentExpectation,
  type InterpretabilityRequirement,
  type ModelType,
  type ProjectContext,
  type RegulatoryEnvironment,
  loadProjectContext,
} from "../lib/projectContext";
import { useWorkflowStore } from "../state/useWorkflowStore";

const inputClass =
  "w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 shadow-sm outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100";

const labelClass = "text-xs font-semibold uppercase tracking-wide text-slate-500";
const classificationSuccessMetrics = ["AUC", "KS", "PR-AUC", "Precision", "Recall", "F1", "Lift", "Calibration", "PSI", "VSI"];
const regressionSuccessMetrics = ["RMSE", "MAE", "MAPE", "R-squared", "Adjusted R-squared", "PSI", "VSI"];

const regulatoryDefinitions: Record<RegulatoryEnvironment, string> = {
  "SR 11-7": "Federal Reserve guidance for model risk management: governance, validation, controls, documentation, and ongoing monitoring.",
  OCC: "Office of the Comptroller of the Currency expectations for bank model risk, controls, auditability, and independent review.",
  "Fair Lending": "Review for disparate treatment, disparate impact, proxy risk, explainability, and protected-class fairness concerns.",
  FCRA: "Fair Credit Reporting Act requirements for credit-reporting data use, permissible purpose, accuracy, and adverse action support.",
  ECOA: "Equal Credit Opportunity Act requirements related to prohibited basis discrimination and adverse action explanations.",
  GDPR: "Privacy and automated decisioning requirements for applicable EU personal data.",
  HIPAA: "Health data privacy and security controls for covered healthcare information.",
  "internal governance": "Internal model risk, validation, documentation, implementation, monitoring, and approval standards.",
  none: "No formal regulatory framework selected. Internal documentation and auditability may still be required.",
};

const projectTypeGuidance: Record<ProjectType, string> = Object.fromEntries(
  projectTypeOptions.map((option) => [
    option.value,
    `Definition: ${option.description} Use when the project objective matches this workflow family.`,
  ])
) as Record<ProjectType, string>;

const modelTypeGuidance: Record<ModelType, string> = {
  fraud: "Definition: rare-event abuse or loss detection. Use when the model flags suspicious behavior for review or intervention.",
  "credit risk": "Definition: repayment, default, or loss-risk modeling. Use when credit decisions, pricing, or exposure management are affected.",
  "marketing response": "Definition: likelihood of response or conversion. Use when ranking customers for campaigns or offers.",
  attrition: "Definition: churn or retention-risk modeling. Use when identifying customers likely to leave or reduce engagement.",
  approval: "Definition: eligibility or decision-support modeling. Use when scores influence approve/decline or manual review decisions.",
  collections: "Definition: collections prioritization or treatment modeling. Use when selecting outreach strategy, queue priority, or repayment support.",
  "AML/KYC": "Definition: anti-money-laundering or know-your-customer risk detection. Use when regulatory investigation workflows are affected.",
  "generic classification": "Definition: binary or multiclass outcome modeling. Use when the target is categorical and not covered by a specialized type.",
  regression: "Definition: continuous-target prediction. Use when predicting dollars, rates, balances, time, or another numeric outcome.",
};

const interpretabilityGuidance: Record<InterpretabilityRequirement, string> = {
  low: "Definition: black-box models may be acceptable. Use for research or low-impact decisions with strong monitoring.",
  medium: "Definition: model behavior must be explainable at a feature or segment level. Use for most governed challenger models.",
  high: "Definition: decisions must be readily explainable and defensible. Use for regulated credit, adverse action, or high-impact use cases.",
};

const deploymentGuidance: Record<DeploymentExpectation, string> = {
  "research only": "Definition: exploratory analysis with no production decisioning. Use when validation and deployment are not yet planned.",
  "batch scoring": "Definition: scheduled offline scoring. Use for periodic campaigns, portfolio reviews, or monitoring files.",
  "real-time API": "Definition: low-latency scoring at decision time. Use only when latency, reliability, and controls are production-ready.",
  "monitoring only": "Definition: no new decision model; track stability or performance. Use for surveillance, governance, or challenger observation.",
};

export default function Step00ProjectContext() {
  const [context, setContext] = useState<ProjectContext>(() => loadProjectContext());
  const projectType = useWorkflowStore((state) => state.projectType);
  const setModelId = useWorkflowStore((state) => state.setModelId);
  const setProjectName = useWorkflowStore((state) => state.setProjectName);
  const startProjectFromWorkflow = useWorkflowStore((state) => state.startProjectFromWorkflow);
  const [selectedProjectType, setSelectedProjectType] = useState<ProjectType>(projectType);

  const requiredComplete = Boolean(
    context.modelId.trim() &&
    context.projectName.trim() &&
      context.businessObjective.trim() &&
      context.targetDefinition.trim() &&
      context.populationDefinition.trim() &&
      context.intendedModelUse.trim()
  );

  const governanceNote = useMemo(() => summarizeRegulatoryContext(context), [context]);
  const successMetricOptions = context.modelType === "regression" ? regressionSuccessMetrics : classificationSuccessMetrics;
  const selectedPrimaryMetrics = context.primarySuccessMetric
    .split(",")
    .map((metric) => metric.trim())
    .filter(Boolean);

  const update = <K extends keyof ProjectContext>(key: K, value: ProjectContext[K]) => {
    setContext((current) => ({ ...current, [key]: value }));
  };

  const togglePrimaryMetric = (metric: string) => {
    const selected = selectedPrimaryMetrics.includes(metric)
      ? selectedPrimaryMetrics.filter((item) => item !== metric)
      : [...selectedPrimaryMetrics, metric];
    update("primarySuccessMetric", selected.join(", "));
  };

  const toggleRegulation = (value: RegulatoryEnvironment) => {
    setContext((current) => {
      if (value === "none") return { ...current, regulatoryEnvironment: ["none"] };
      const withoutNone = current.regulatoryEnvironment.filter((item) => item !== "none");
      const next = withoutNone.includes(value)
        ? withoutNone.filter((item) => item !== value)
        : [...withoutNone, value];
      return { ...current, regulatoryEnvironment: next.length ? next : ["none"] };
    });
  };

  return (
    <StepShell
      title="Step 0: Project Context"
      subtitle="Define the business objective, target, population, governance constraints, and deployment expectations before data acquisition."
      nextPath={selectedProjectType === "predictive-modeling" ? "/step01" : "/project-overview"}
      nextDisabled={!requiredComplete}
      onNext={() => {
        const previous = loadProjectContext();
        saveProjectContext(context);
        setModelId(context.modelId);
        setProjectName(context.projectName || "Untitled ATLAS Project");
        if (selectedProjectType !== projectType) {
          const workflow = getWorkflowForProjectType(selectedProjectType);
          startProjectFromWorkflow({
            projectName: context.projectName || "Untitled ATLAS Project",
            modelId: context.modelId,
            projectType: selectedProjectType,
            workflowId: workflow.id,
          });
        }
        logDecision({
          workflowStep: "Project Context",
          actionType: "project_context_updated",
          subject: context.projectName || "Project context",
          previousValue: previous,
          newValue: context,
          followStatus: "not_applicable",
        });
      }}
    >
      <div className="space-y-5">
        <section className="rounded-lg border border-slate-200/80 bg-white/90 p-5 shadow-sm">
          <div className="grid gap-4 lg:grid-cols-3">
            <Field label="Model ID #">
              <input
                className={inputClass}
                value={context.modelId}
                onChange={(event) => update("modelId", event.target.value)}
                placeholder="15211"
                aria-required="true"
              />
            </Field>

            <Field label="Project name">
              <input
                className={inputClass}
                value={context.projectName}
                onChange={(event) => update("projectName", event.target.value)}
                placeholder="Consumer lending attrition model"
              />
            </Field>

            <Field label="Project type">
              <select
                className={inputClass}
                value={selectedProjectType}
                onChange={(event) => setSelectedProjectType(event.target.value as ProjectType)}
              >
                {projectTypeOptions.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
              <GuidanceText>{projectTypeGuidance[selectedProjectType]}</GuidanceText>
            </Field>

            <Field label="Model type">
              <select
                className={inputClass}
                value={context.modelType}
                onChange={(event) => update("modelType", event.target.value as ModelType)}
              >
                {modelTypeOptions.map((option) => (
                  <option key={option} value={option}>
                    {option}
                  </option>
                ))}
              </select>
              <GuidanceText>{modelTypeGuidance[context.modelType]}</GuidanceText>
            </Field>

            <div className="lg:col-span-2">
              <div className={labelClass}>Primary success metric</div>
              <div className="mt-2 flex flex-wrap gap-2">
                {successMetricOptions.map((metric) => {
                  const selected = selectedPrimaryMetrics.includes(metric);
                  return (
                    <button
                      key={metric}
                      type="button"
                      className={`rounded-lg border px-3 py-2 text-sm font-semibold ${
                        selected ? "border-blue-300 bg-blue-50 text-blue-900" : "border-slate-200 bg-white text-slate-700 hover:bg-slate-50"
                      }`}
                      onClick={() => togglePrimaryMetric(metric)}
                    >
                      {metric}
                    </button>
                  );
                })}
              </div>
              <p className="mt-2 text-xs text-slate-500">Selected: {context.primarySuccessMetric || "None selected"}</p>
            </div>
          </div>

          <div className="mt-4 grid gap-4 lg:grid-cols-2">
            <LLMWritingAssist
              label="Business objective"
              value={context.businessObjective}
              onChange={(value) => update("businessObjective", value)}
              placeholder="Describe the decision this model will support and the business outcome it should improve."
              context={context}
            />

            <LLMWritingAssist
              label="Intended model use"
              value={context.intendedModelUse}
              onChange={(value) => update("intendedModelUse", value)}
              placeholder="Describe how scores, rankings, or predictions will be used by the business."
              context={context}
            />
          </div>
        </section>

        <section className="grid gap-5 xl:grid-cols-[1.1fr_0.9fr]">
          <div className="rounded-lg border border-slate-200/80 bg-white/90 p-5 shadow-sm">
            <h2 className="text-sm font-semibold text-slate-950">Target and Population</h2>
            <div className="mt-4 grid gap-4 lg:grid-cols-2">
              <LLMWritingAssist
                label="Target definition"
                value={context.targetDefinition}
                onChange={(value) => update("targetDefinition", value)}
                placeholder="Define the dependent variable, event logic, exclusions, and timing."
                context={context}
                minHeightClass="min-h-[92px]"
              />

              <LLMWritingAssist
                label="Population definition"
                value={context.populationDefinition}
                onChange={(value) => update("populationDefinition", value)}
                placeholder="Define eligible accounts, customers, loans, applications, or transactions."
                context={context}
                minHeightClass="min-h-[92px]"
              />

              <Field label="Observation window">
                <input
                  className={inputClass}
                  value={context.observationWindow}
                  onChange={(event) => update("observationWindow", event.target.value)}
                  placeholder="Example: 2024-01-01 to 2024-06-30"
                />
              </Field>

              <Field label="Performance window">
                <input
                  className={inputClass}
                  value={context.performanceWindow}
                  onChange={(event) => update("performanceWindow", event.target.value)}
                  placeholder="Example: 90 days after observation close"
                />
              </Field>
            </div>
          </div>

          <div className="rounded-lg border border-slate-200/80 bg-white/90 p-5 shadow-sm">
            <h2 className="text-sm font-semibold text-slate-950">Costs and Operating Constraints</h2>
            <div className="mt-4 grid gap-4">
              <div className="grid gap-4 sm:grid-cols-2">
                <Field label={context.modelType === "regression" ? "Overprediction cost" : "False positive cost"}>
                  <input
                    className={inputClass}
                    value={context.falsePositiveCost}
                    onChange={(event) => update("falsePositiveCost", event.target.value)}
                    placeholder={context.modelType === "regression" ? "$, over-reserve, over-price, operational impact" : "$, operational, customer impact"}
                  />
                </Field>

                <Field label={context.modelType === "regression" ? "Underprediction cost" : "False negative cost"}>
                  <input
                    className={inputClass}
                    value={context.falseNegativeCost}
                    onChange={(event) => update("falseNegativeCost", event.target.value)}
                    placeholder={context.modelType === "regression" ? "$, loss, under-price, service-level impact" : "$, loss, fraud, compliance impact"}
                  />
                </Field>
              </div>

              <div className="grid gap-4 sm:grid-cols-2">
                <Field label="Interpretability requirement">
                  <select
                    className={inputClass}
                    value={context.interpretabilityRequirement}
                    onChange={(event) => update("interpretabilityRequirement", event.target.value as InterpretabilityRequirement)}
                  >
                    <option value="low">low</option>
                    <option value="medium">medium</option>
                    <option value="high">high</option>
                  </select>
                  <GuidanceText>{interpretabilityGuidance[context.interpretabilityRequirement]}</GuidanceText>
                </Field>

                <Field label="Deployment expectation">
                  <select
                    className={inputClass}
                    value={context.deploymentExpectation}
                    onChange={(event) => update("deploymentExpectation", event.target.value as DeploymentExpectation)}
                  >
                    <option value="research only">research only</option>
                    <option value="batch scoring">batch scoring</option>
                    <option value="real-time API">real-time API</option>
                    <option value="monitoring only">monitoring only</option>
                  </select>
                  <GuidanceText>{deploymentGuidance[context.deploymentExpectation]}</GuidanceText>
                </Field>
              </div>

              <Field label="Secondary metrics">
                <input
                  className={inputClass}
                  value={context.secondaryMetrics}
                  onChange={(event) => update("secondaryMetrics", event.target.value)}
                  placeholder={context.modelType === "regression" ? "RMSE, MAE, MAPE, R-squared, prediction PSI, VSI" : "Calibration, lift, recall, PSI, stability"}
                />
              </Field>
            </div>
          </div>
        </section>

        <section className="rounded-lg border border-slate-200/80 bg-white/90 p-5 shadow-sm">
          <div className="flex flex-col gap-2 md:flex-row md:items-start md:justify-between">
            <div>
              <h2 className="text-sm font-semibold text-slate-950">Regulatory Environment</h2>
              <p className="mt-1 text-sm text-slate-500">{governanceNote}</p>
            </div>
            <button
              type="button"
              className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-700 shadow-sm hover:bg-slate-50"
              onClick={() => setContext(defaultProjectContext)}
            >
              Reset Context
            </button>
          </div>

          <div className="mt-4 grid gap-2 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5">
            {regulatoryOptions.map((option) => {
              const selected = context.regulatoryEnvironment.includes(option);
              return (
                <label
                  key={option}
                  className={`flex cursor-pointer items-center gap-2 rounded-lg border px-3 py-2 text-sm font-medium ${
                    selected
                      ? "border-indigo-200 bg-indigo-50 text-indigo-900"
                      : "border-slate-200 bg-slate-50 text-slate-700"
                  }`}
                >
                  <input
                    type="checkbox"
                    checked={selected}
                    onChange={() => toggleRegulation(option)}
                    className="h-4 w-4 rounded border-slate-300 text-indigo-600"
                  />
                  {option}
                  <span className="sr-only">{regulatoryDefinitions[option]}</span>
                </label>
              );
            })}
          </div>
          <div className="mt-4 grid gap-2 md:grid-cols-2">
            {regulatoryOptions.map((option) => (
              <div key={`${option}-help`} className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2">
                <div className="text-xs font-semibold text-slate-900">{option}</div>
                <p className="mt-1 text-xs leading-5 text-slate-600">{regulatoryDefinitions[option]}</p>
              </div>
            ))}
          </div>
        </section>
      </div>
    </StepShell>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="grid gap-1.5">
      <span className={labelClass}>{label}</span>
      {children}
    </label>
  );
}

function GuidanceText({ children }: { children: React.ReactNode }) {
  return <span className="text-[11px] font-normal normal-case leading-4 text-slate-500">{children}</span>;
}
