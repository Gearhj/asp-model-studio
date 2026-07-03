import { useState } from "react";
import type React from "react";
import LLMWritingAssist from "../components/LLMWritingAssist";
import StepShell from "../components/StepShell";
import { logDecision } from "../lib/decisionJournal";
import { loadProjectContext, saveProjectContext, type ProjectContext } from "../lib/projectContext";

const inputClass =
  "w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 shadow-sm outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100";

const labelClass = "text-xs font-semibold uppercase tracking-wide text-slate-500";

export default function Step12ModelImplementation() {
  const [context, setContext] = useState<ProjectContext>(() => loadProjectContext());

  const update = <K extends keyof ProjectContext>(key: K, value: ProjectContext[K]) => {
    setContext((current) => ({ ...current, [key]: value }));
  };

  return (
    <StepShell
      title="Step 12: Model Implementation"
      subtitle="Document implementation ownership, target environment, approval gates, and production handoff after the model has been developed."
      nextPath="/step13"
      onNext={() => {
        const previous = loadProjectContext();
        saveProjectContext(context);
        logDecision({
          workflowStep: "Model Implementation",
          actionType: "workflow_setting_changed",
          subject: "Implementation plan",
          previousValue: previous,
          newValue: {
            owner: context.implementationOwner,
            targetDate: context.implementationTargetDate,
            environment: context.implementationEnvironment,
            notes: context.implementationNotes,
          },
          systemRecommendation: "Complete implementation planning only after the champion model and documentation are ready for handoff.",
          followStatus: "not_applicable",
        });
      }}
    >
      <section className="rounded-lg border border-slate-200/80 bg-white/90 p-5 shadow-sm">
        <div className="flex flex-col gap-1">
          <h2 className="text-sm font-semibold text-slate-950">Production Handoff Plan</h2>
          <p className="text-sm text-slate-500">
            This step occurs after model development because implementation decisions should reflect the approved champion model, package, and controls.
          </p>
        </div>

        <div className="mt-5 grid gap-4 lg:grid-cols-2">
          <Field label="Model ID #">
            <input className={inputClass} value={context.modelId} onChange={(event) => update("modelId", event.target.value)} />
          </Field>
          <Field label="Model name">
            <input className={inputClass} value={context.projectName} onChange={(event) => update("projectName", event.target.value)} />
          </Field>
          <Field label="Implementation owner">
            <input
              className={inputClass}
              value={context.implementationOwner}
              onChange={(event) => update("implementationOwner", event.target.value)}
              placeholder="Team, owner, or business sponsor"
            />
          </Field>
          <Field label="Target implementation date">
            <input
              className={inputClass}
              value={context.implementationTargetDate}
              onChange={(event) => update("implementationTargetDate", event.target.value)}
              placeholder="YYYY-MM-DD or planned release"
            />
          </Field>
          <Field label="Implementation environment">
            <select
              className={inputClass}
              value={context.implementationEnvironment}
              onChange={(event) => update("implementationEnvironment", event.target.value)}
            >
              <option value="">Select environment</option>
              <option value="batch scoring">Batch scoring</option>
              <option value="real-time API">Real-time API</option>
              <option value="decision engine">Decision engine</option>
              <option value="monitoring only">Monitoring only</option>
              <option value="research handoff">Research handoff</option>
            </select>
          </Field>
          <LLMWritingAssist
            label="Implementation notes"
            value={context.implementationNotes}
            onChange={(value) => update("implementationNotes", value)}
            placeholder="Dependencies, approval gates, model package location, decision engine changes, rollback plan, controls, or handoff notes."
            context={context}
            minHeightClass="min-h-[112px]"
          />
        </div>
      </section>
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
