import type React from "react";
import { useMemo, useState } from "react";
import StepShell from "../components/StepShell";
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

const inputClass =
  "w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 shadow-sm outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100";

const labelClass = "text-xs font-semibold uppercase tracking-wide text-slate-500";

export default function Step00ProjectContext() {
  const [context, setContext] = useState<ProjectContext>(() => loadProjectContext());

  const requiredComplete = Boolean(
    context.projectName.trim() &&
      context.businessObjective.trim() &&
      context.targetDefinition.trim() &&
      context.populationDefinition.trim() &&
      context.intendedModelUse.trim()
  );

  const governanceNote = useMemo(() => summarizeRegulatoryContext(context), [context]);

  const update = <K extends keyof ProjectContext>(key: K, value: ProjectContext[K]) => {
    setContext((current) => ({ ...current, [key]: value }));
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
      nextPath="/step01"
      nextDisabled={!requiredComplete}
      onNext={() => {
        const previous = loadProjectContext();
        saveProjectContext(context);
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
            <Field label="Project name">
              <input
                className={inputClass}
                value={context.projectName}
                onChange={(event) => update("projectName", event.target.value)}
                placeholder="Consumer lending attrition model"
              />
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
            </Field>

            <Field label="Primary success metric">
              <input
                className={inputClass}
                value={context.primarySuccessMetric}
                onChange={(event) => update("primarySuccessMetric", event.target.value)}
                placeholder="PR-AUC, KS, RMSE, lift, recall"
              />
            </Field>
          </div>

          <div className="mt-4 grid gap-4 lg:grid-cols-2">
            <Field label="Business objective">
              <textarea
                className={`${inputClass} min-h-[104px] resize-y`}
                value={context.businessObjective}
                onChange={(event) => update("businessObjective", event.target.value)}
                placeholder="Describe the decision this model will support and the business outcome it should improve."
              />
            </Field>

            <Field label="Intended model use">
              <textarea
                className={`${inputClass} min-h-[104px] resize-y`}
                value={context.intendedModelUse}
                onChange={(event) => update("intendedModelUse", event.target.value)}
                placeholder="Describe how scores, rankings, or predictions will be used by the business."
              />
            </Field>
          </div>
        </section>

        <section className="grid gap-5 xl:grid-cols-[1.1fr_0.9fr]">
          <div className="rounded-lg border border-slate-200/80 bg-white/90 p-5 shadow-sm">
            <h2 className="text-sm font-semibold text-slate-950">Target and Population</h2>
            <div className="mt-4 grid gap-4 lg:grid-cols-2">
              <Field label="Target definition">
                <textarea
                  className={`${inputClass} min-h-[92px] resize-y`}
                  value={context.targetDefinition}
                  onChange={(event) => update("targetDefinition", event.target.value)}
                  placeholder="Define the dependent variable, event logic, exclusions, and timing."
                />
              </Field>

              <Field label="Population definition">
                <textarea
                  className={`${inputClass} min-h-[92px] resize-y`}
                  value={context.populationDefinition}
                  onChange={(event) => update("populationDefinition", event.target.value)}
                  placeholder="Define eligible accounts, customers, loans, applications, or transactions."
                />
              </Field>

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
                <Field label="False positive cost">
                  <input
                    className={inputClass}
                    value={context.falsePositiveCost}
                    onChange={(event) => update("falsePositiveCost", event.target.value)}
                    placeholder="$, operational, customer impact"
                  />
                </Field>

                <Field label="False negative cost">
                  <input
                    className={inputClass}
                    value={context.falseNegativeCost}
                    onChange={(event) => update("falseNegativeCost", event.target.value)}
                    placeholder="$, loss, fraud, compliance impact"
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
                </Field>
              </div>

              <Field label="Secondary metrics">
                <input
                  className={inputClass}
                  value={context.secondaryMetrics}
                  onChange={(event) => update("secondaryMetrics", event.target.value)}
                  placeholder="Calibration, lift, recall, PSI, MAE, stability"
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
                </label>
              );
            })}
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
