import { useMemo, useState } from "react";
import type React from "react";
import LLMWritingAssist from "../components/LLMWritingAssist";
import StepShell from "../components/StepShell";
import { logDecision } from "../lib/decisionJournal";
import { buildEscalationQueue, loadProductionModels, type ProductionModelStatus } from "../lib/modelMonitoring";
import {
  defaultMonitoringMetricsForModelType,
  loadProjectContext,
  monitoringCadenceOptions,
  monitoringMetricOptionsForModelType,
  saveProjectContext,
  type MonitoringCadence,
  type ProjectContext,
} from "../lib/projectContext";

const inputClass =
  "w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 shadow-sm outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100";

const labelClass = "text-xs font-semibold uppercase tracking-wide text-slate-500";

export default function Step13ModelMonitoring() {
  const [context, setContext] = useState<ProjectContext>(() => loadProjectContext());
  const models = useMemo(() => loadProductionModels(), [context]);
  const escalations = useMemo(() => buildEscalationQueue(models), [models]);

  const update = <K extends keyof ProjectContext>(key: K, value: ProjectContext[K]) => {
    setContext((current) => ({ ...current, [key]: value }));
  };

  const toggleMonitoringMetric = (metric: string) => {
    setContext((current) => ({
      ...current,
      monitoringMetrics: current.monitoringMetrics.includes(metric)
        ? current.monitoringMetrics.filter((item) => item !== metric)
        : [...current.monitoringMetrics, metric],
    }));
  };

  return (
    <StepShell
      title="Step 13: Model Monitoring"
      subtitle="Set monitoring cadence and review production models, drift trends, compliance issues, and escalation items."
      nextPath="/dashboard"
      nextLabel="Mark Complete & Return to Atlas Home"
      onNext={() => {
        const previous = loadProjectContext();
        saveProjectContext(context);
        logDecision({
          workflowStep: "Model Monitoring",
          actionType: "workflow_setting_changed",
          subject: "Monitoring plan",
          previousValue: previous,
          newValue: {
            cadence: context.monitoringCadence,
            customCadence: context.monitoringCadenceCustom,
            metrics: context.monitoringMetrics,
            notes: context.monitoringNotes,
          },
          systemRecommendation: "Monitoring should be configured after model development and implementation planning, using metrics aligned to model type and production risk.",
          followStatus: "not_applicable",
        });
      }}
    >
      <div className="space-y-5">
        <section className="rounded-lg border border-slate-200/80 bg-white/90 p-5 shadow-sm">
          <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
            <div>
              <h2 className="text-sm font-semibold text-slate-950">Monitoring Configuration</h2>
              <p className="mt-1 text-sm text-slate-500">
                Monitoring is configured after the model is developed so cadence, metrics, and thresholds match the approved champion model.
              </p>
            </div>
            <button
              type="button"
              className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-xs font-semibold text-slate-700 shadow-sm hover:bg-slate-50"
              onClick={() => update("monitoringMetrics", defaultMonitoringMetricsForModelType(context.modelType))}
            >
              Use Recommended Metrics
            </button>
          </div>

          <div className="mt-5 grid gap-4 lg:grid-cols-2">
            <Field label="Monitoring cadence">
              <select
                className={inputClass}
                value={context.monitoringCadence}
                onChange={(event) => update("monitoringCadence", event.target.value as MonitoringCadence)}
              >
                {monitoringCadenceOptions.map((option) => (
                  <option key={option} value={option}>
                    {option}
                  </option>
                ))}
              </select>
            </Field>

            {context.monitoringCadence === "custom" && (
              <Field label="Custom cadence">
                <input
                  className={inputClass}
                  value={context.monitoringCadenceCustom}
                  onChange={(event) => update("monitoringCadenceCustom", event.target.value)}
                  placeholder="Every 2 weeks, first business day, etc."
                />
              </Field>
            )}
          </div>

          <div className="mt-4">
            <div className={labelClass}>Performance and stability metrics</div>
            <div className="mt-2 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
              {monitoringMetricOptionsForModelType(context.modelType).map((metric) => {
                const selected = context.monitoringMetrics.includes(metric);
                return (
                  <label
                    key={metric}
                    className={`flex cursor-pointer items-center gap-2 rounded-lg border px-3 py-2 text-sm font-medium ${
                      selected ? "border-blue-200 bg-blue-50 text-blue-900" : "border-slate-200 bg-slate-50 text-slate-700"
                    }`}
                  >
                    <input
                      type="checkbox"
                      checked={selected}
                      onChange={() => toggleMonitoringMetric(metric)}
                      className="h-4 w-4 rounded border-slate-300 text-blue-600"
                    />
                    {metric}
                  </label>
                );
              })}
            </div>
          </div>

          <div className="mt-4">
            <LLMWritingAssist
              label="Monitoring notes"
              value={context.monitoringNotes}
              onChange={(value) => update("monitoringNotes", value)}
              placeholder="Thresholds, owners, escalation paths, monitoring evidence, validation cadence, or remediation standards."
              context={context}
              minHeightClass="min-h-[92px]"
            />
          </div>
        </section>

        <section className="rounded-lg border border-rose-200 bg-rose-50 p-5 shadow-sm">
          <h2 className="text-sm font-semibold text-rose-950">Escalation Queue</h2>
          <p className="mt-1 text-sm text-rose-800">
            Models appear here when they are older than 18 months, trending into a red/yellow monitoring zone, or have a compliance issue.
          </p>
          <div className="mt-4 overflow-auto rounded-lg border border-rose-200 bg-white">
            <table className="min-w-full text-left text-sm">
              <thead className="bg-rose-100 text-xs uppercase tracking-wide text-rose-900">
                <tr>
                  <th className="px-3 py-2">Severity</th>
                  <th className="px-3 py-2">Model</th>
                  <th className="px-3 py-2">Reason</th>
                  <th className="px-3 py-2">Owner</th>
                  <th className="px-3 py-2">Action</th>
                </tr>
              </thead>
              <tbody>
                {escalations.map((item, index) => (
                  <tr key={`${item.modelId}-${index}`} className="border-t border-rose-100">
                    <td className="px-3 py-2 font-semibold text-rose-900">{item.severity}</td>
                    <td className="px-3 py-2 font-semibold text-slate-900">{item.modelId} {item.modelName}</td>
                    <td className="px-3 py-2 text-slate-700">{item.reason}</td>
                    <td className="px-3 py-2 text-slate-700">{item.owner}</td>
                    <td className="px-3 py-2 text-slate-700">{item.action}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>

        <section className="rounded-lg border border-slate-200/80 bg-white/90 p-5 shadow-sm">
          <h2 className="text-sm font-semibold text-slate-950">Production Models Under Monitoring</h2>
          <div className="mt-4 grid gap-3">
            {models.map((model) => (
              <article key={`${model.modelId}-${model.modelName}`} className="rounded-lg border border-slate-200 bg-slate-50 p-4">
                <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                  <div>
                    <h3 className="text-sm font-semibold text-slate-950">{model.modelId} {model.modelName}</h3>
                    <p className="mt-1 text-xs text-slate-500">
                      Owner: {model.owner} · Deployed: {model.deployedAt || "Not implemented"} · Cadence: {model.monitoringCadence}
                    </p>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    {model.metrics.map((metric) => (
                      <span key={metric.name} className={`rounded-full px-2 py-1 text-xs font-semibold ${metricClass(metric.status)}`}>
                        {metric.name}: {metric.value}
                      </span>
                    ))}
                  </div>
                </div>
              </article>
            ))}
          </div>
        </section>
      </div>
    </StepShell>
  );
}

function metricClass(status: ProductionModelStatus) {
  if (status === "red") return "bg-rose-100 text-rose-800";
  if (status === "yellow") return "bg-amber-100 text-amber-800";
  return "bg-emerald-100 text-emerald-800";
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="grid gap-1.5">
      <span className={labelClass}>{label}</span>
      {children}
    </label>
  );
}
