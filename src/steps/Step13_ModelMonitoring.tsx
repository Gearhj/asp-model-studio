import { useMemo, useState } from "react";
import type React from "react";
import LLMWritingAssist from "../components/LLMWritingAssist";
import {
  useAuthoritativeProjectContext,
  usePredictiveIdentity,
} from "../components/PredictiveIdentityProvider";
import StepShell from "../components/StepShell";
import { logDecision } from "../lib/decisionJournal";
import {
  bindPromotedModelIdentity,
  projectContextMatchesPromotedModel,
} from "../lib/implementationMonitoringIdentity";
import { buildEscalationQueue, loadProductionModels, type ProductionModelStatus } from "../lib/modelMonitoring";
import {
  defaultMonitoringMetricsForModelType,
  monitoringCadenceOptions,
  monitoringMetricOptionsForModelType,
  defaultProjectContext,
  type MonitoringCadence,
  type ProjectContext,
} from "../lib/projectContext";
import { migrateStoredContext } from "../lib/projectContextPersistence";
import { useProjectContextAutosave } from "../lib/useProjectContextAutosave";
import { useExactPromotedModelIdentity } from "../lib/useExactPromotedModelIdentity";

const inputClass =
  "w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 shadow-sm outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100";

const labelClass = "text-xs font-semibold uppercase tracking-wide text-slate-500";

export default function Step13ModelMonitoring() {
  const {
    readiness: projectReadiness,
    publishSavedProjectMetadata,
    setMetadataRefreshStatus,
    authenticatedUserId,
  } = useAuthoritativeProjectContext();
  const {
    readiness: identityReadiness,
    dataAcquisitionContextReadiness,
  } = usePredictiveIdentity();
  const projectId = projectReadiness.status === "ready"
    ? projectReadiness.project.projectId
    : "";
  const datasetIdentity = identityReadiness.status === "ready"
    && identityReadiness.projectId === projectId
      ? identityReadiness.identity
      : null;
  const target = dataAcquisitionContextReadiness.status === "ready"
    && dataAcquisitionContextReadiness.projectId === projectId
      ? String(dataAcquisitionContextReadiness.context?.target_contract?.target ?? "").trim()
      : "";
  const promotedModel = useExactPromotedModelIdentity({
    projectId,
    userId: authenticatedUserId,
    datasetIdentity,
    target,
  });
  const [context, setContext] = useState<ProjectContext>(() => {
    const authoritative = projectReadiness.status === "ready"
      ? migrateStoredContext(projectReadiness.project.projectContext)
      : null;
    return authoritative
      ? {
          ...authoritative,
          projectName: projectReadiness.status === "ready"
            ? projectReadiness.project.projectName
            : authoritative.projectName,
          modelId: projectReadiness.status === "ready"
            ? projectReadiness.project.modelId
            : authoritative.modelId,
        }
      : {
          ...defaultProjectContext,
          fraudDetails: { ...defaultProjectContext.fraudDetails },
        };
  });
  const autosave = useProjectContextAutosave({
    projectId,
    authenticatedUserId,
    context,
    validationStatus: context.completionStatus === "complete" ? "complete" : "ready",
    enabled: Boolean(projectId && authenticatedUserId),
    onHydrated: (hydrated) => setContext({
      ...hydrated,
      projectName: projectReadiness.status === "ready"
        ? projectReadiness.project.projectName
        : hydrated.projectName,
      modelId: projectReadiness.status === "ready"
        ? projectReadiness.project.modelId
        : hydrated.modelId,
    }),
    onSaved: (notification) => {
      const disposition = publishSavedProjectMetadata({
        ...notification,
        actorUserId: authenticatedUserId,
      });
      setMetadataRefreshStatus(
        disposition === "applied" || disposition === "duplicate"
          ? "saved"
          : "error",
      );
    },
  });
  const durableContextReady = autosave.hydrated && !autosave.hydrating;

  const exactIdentityCarriedForward = Boolean(
    promotedModel.identity
    && projectContextMatchesPromotedModel(context, promotedModel.identity),
  );
  const models = useMemo(
    () => loadProductionModels(
      context,
      exactIdentityCarriedForward ? promotedModel.identity : null,
    ),
    [context, exactIdentityCarriedForward, promotedModel.identity],
  );
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
      nextDisabled={!durableContextReady || promotedModel.status !== "ready" || !exactIdentityCarriedForward}
      nextDisabledReason={!durableContextReady
        ? "Loading the exact project-scoped monitoring plan from ATLAS."
        : promotedModel.status === "loading"
          ? "Verifying the exact promoted model and durable model version."
          : promotedModel.status !== "ready"
            ? promotedModel.error || "A verified promoted model is required before monitoring can be completed."
            : "Return to Model Implementation and save the handoff for this exact promoted model version."}
      onNext={async () => {
        if (!promotedModel.identity || !exactIdentityCarriedForward || !projectId || !authenticatedUserId) return false;
        const previous = context;
        const next = bindPromotedModelIdentity(context, promotedModel.identity);
        setContext(next);
        const persisted = await autosave.saveNow(next);
        if (!persisted) {
          throw new Error(
            autosave.message
              || "ATLAS could not durably save the monitoring plan. The page remains open so the plan can be retried.",
          );
        }
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
            model_id: promotedModel.identity.modelId,
            model_version_id: promotedModel.identity.modelVersionId,
          },
          systemRecommendation: "Monitoring should be configured after model development and implementation planning, using metrics aligned to model type and production risk.",
          followStatus: "not_applicable",
        });
      }}
    >
      <div className="space-y-5">
        <section
          data-testid="monitoring-promoted-model-identity"
          className={`rounded-lg border p-4 text-sm shadow-sm ${
            promotedModel.status === "ready" && exactIdentityCarriedForward
              ? "border-emerald-200 bg-emerald-50 text-emerald-950"
              : "border-amber-200 bg-amber-50 text-amber-950"
          }`}
        >
          <h2 className="font-semibold">Exact promoted model under monitoring</h2>
          {promotedModel.status === "ready" && promotedModel.identity ? (
            exactIdentityCarriedForward ? (
              <div className="mt-2 grid gap-2 text-xs sm:grid-cols-2 lg:grid-cols-4">
                <div><span className="font-semibold">Model ID</span><div className="mt-1 break-all font-mono">{promotedModel.identity.modelId}</div></div>
                <div><span className="font-semibold">Model version ID</span><div className="mt-1 break-all font-mono">{promotedModel.identity.modelVersionId}</div></div>
                <div><span className="font-semibold">Dataset version</span><div className="mt-1 break-all font-mono">{promotedModel.identity.datasetVersionId}</div></div>
                <div><span className="font-semibold">Artifact</span><div className="mt-1 capitalize">{promotedModel.identity.artifactVerificationStatus}</div></div>
              </div>
            ) : (
              <p className="mt-2 text-xs">
                The Model Registry returned <span className="font-mono">{promotedModel.identity.modelVersionId}</span>, but Model Implementation has not carried that exact identity into this project-scoped handoff. Return to Model Implementation to save it.
              </p>
            )
          ) : promotedModel.status === "loading" ? (
            <p className="mt-2 text-xs">Verifying the exact promoted model with the Model Registry...</p>
          ) : (
            <p className="mt-2 text-xs">{promotedModel.error || "The exact promoted model is unavailable."}</p>
          )}
        </section>

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
              disabled={!durableContextReady}
              className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-xs font-semibold text-slate-700 shadow-sm hover:bg-slate-50 disabled:cursor-wait disabled:opacity-60"
              onClick={() => update("monitoringMetrics", defaultMonitoringMetricsForModelType(context.modelType))}
            >
              Use Recommended Metrics
            </button>
          </div>

          <fieldset
            className="mt-5 grid gap-4 disabled:cursor-wait disabled:opacity-70 lg:grid-cols-2"
            disabled={!durableContextReady}
          >
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
          </fieldset>

          <fieldset className="mt-4 disabled:cursor-wait disabled:opacity-70" disabled={!durableContextReady}>
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
          </fieldset>

          <fieldset className="mt-4 disabled:cursor-wait disabled:opacity-70" disabled={!durableContextReady}>
            <LLMWritingAssist
              label="Monitoring notes"
              value={context.monitoringNotes}
              onChange={(value) => update("monitoringNotes", value)}
              placeholder="Thresholds, owners, escalation paths, monitoring evidence, validation cadence, or remediation standards."
              context={context}
              minHeightClass="min-h-[92px]"
            />
          </fieldset>
          <div
            data-testid="monitoring-plan-save-status"
            data-save-status={autosave.status}
            className={`mt-4 rounded-lg border px-3 py-2 text-xs ${
              ["failed", "offline", "conflict"].includes(autosave.status)
                ? "border-red-200 bg-red-50 text-red-900"
                : autosave.status === "saving" || autosave.status === "unsaved" || autosave.hydrating
                  ? "border-amber-200 bg-amber-50 text-amber-900"
                  : "border-emerald-200 bg-emerald-50 text-emerald-900"
            }`}
          >
            {autosave.hydrating
              ? "Loading the exact project-scoped plan from ATLAS..."
              : autosave.status === "saving"
                ? "Saving the monitoring plan to ATLAS..."
                : autosave.status === "unsaved"
                  ? "Monitoring-plan changes are waiting for durable save."
                  : ["failed", "offline", "conflict"].includes(autosave.status)
                    ? autosave.message || "The monitoring plan has not been saved."
                    : "Monitoring-plan changes are saved to the ATLAS project record."}
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
                    {model.modelVersionId ? (
                      <p className="mt-1 break-all text-xs font-medium text-slate-600">
                        Model version: <span className="font-mono">{model.modelVersionId}</span>
                      </p>
                    ) : null}
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
