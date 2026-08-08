import { useState } from "react";
import type React from "react";
import LLMWritingAssist from "../components/LLMWritingAssist";
import {
  useAuthoritativeProjectContext,
  usePredictiveIdentity,
} from "../components/PredictiveIdentityProvider";
import StepShell from "../components/StepShell";
import { logDecision } from "../lib/decisionJournal";
import { bindPromotedModelIdentity } from "../lib/implementationMonitoringIdentity";
import { defaultProjectContext, type ProjectContext } from "../lib/projectContext";
import { migrateStoredContext } from "../lib/projectContextPersistence";
import { useProjectContextAutosave } from "../lib/useProjectContextAutosave";
import { useExactPromotedModelIdentity } from "../lib/useExactPromotedModelIdentity";

const inputClass =
  "w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 shadow-sm outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100";

const labelClass = "text-xs font-semibold uppercase tracking-wide text-slate-500";

export default function Step12ModelImplementation() {
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

  const update = <K extends keyof ProjectContext>(key: K, value: ProjectContext[K]) => {
    setContext((current) => ({ ...current, [key]: value }));
  };

  return (
    <StepShell
      title="Step 12: Model Implementation"
      subtitle="Document implementation ownership, target environment, approval gates, and production handoff after the model has been developed."
      nextPath="/step13"
      nextDisabled={!durableContextReady || promotedModel.status !== "ready" || !promotedModel.identity}
      nextDisabledReason={!durableContextReady
        ? "Loading the exact project-scoped implementation plan from ATLAS."
        : promotedModel.status === "loading"
          ? "Verifying the exact promoted model and durable model version."
          : promotedModel.error || "A verified promoted model is required before implementation planning can be completed."}
      onNext={async () => {
        if (!promotedModel.identity || !projectId || !authenticatedUserId) return false;
        const previous = context;
        const next = bindPromotedModelIdentity(context, promotedModel.identity);
        setContext(next);
        const persisted = await autosave.saveNow(next);
        if (!persisted) {
          throw new Error(
            autosave.message
              || "ATLAS could not durably save the implementation plan. The page remains open so the plan can be retried.",
          );
        }
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
            model_id: promotedModel.identity.modelId,
            model_version_id: promotedModel.identity.modelVersionId,
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

        <fieldset
          className="mt-5 grid gap-4 disabled:cursor-wait disabled:opacity-70 lg:grid-cols-2"
          disabled={!durableContextReady}
        >
          <Field label="Promoted model ID">
            <input
              className={`${inputClass} bg-slate-100 font-mono`}
              value={promotedModel.identity?.modelId ?? ""}
              readOnly
              aria-describedby="implementation-model-identity-note"
            />
          </Field>
          <Field label="Promoted model version ID">
            <input
              className={`${inputClass} bg-slate-100 font-mono`}
              value={promotedModel.identity?.modelVersionId ?? ""}
              readOnly
              aria-describedby="implementation-model-identity-note"
            />
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
        </fieldset>
        <div
          id="implementation-model-identity-note"
          data-testid="implementation-promoted-model-identity"
          className={`mt-4 rounded-lg border p-3 text-xs ${
            promotedModel.status === "ready"
              ? "border-emerald-200 bg-emerald-50 text-emerald-900"
              : "border-amber-200 bg-amber-50 text-amber-900"
          }`}
        >
          {promotedModel.status === "ready" && promotedModel.identity ? (
            <>
              Backend-verified champion for project <span className="font-mono">{promotedModel.identity.projectId}</span>, dataset version{" "}
              <span className="font-mono">{promotedModel.identity.datasetVersionId}</span>, candidate{" "}
              <span className="font-mono">{promotedModel.identity.candidateId}</span>. Artifact verification: {promotedModel.identity.artifactVerificationStatus}.
              Model identity is read-only and cannot be replaced on this page.
            </>
          ) : promotedModel.status === "loading" ? (
            "Verifying the exact promoted model with the Model Registry..."
          ) : (
            promotedModel.error || "The exact promoted model is unavailable."
          )}
        </div>
        <div
          data-testid="implementation-plan-save-status"
          data-save-status={autosave.status}
          className={`mt-3 rounded-lg border px-3 py-2 text-xs ${
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
              ? "Saving the implementation plan to ATLAS..."
              : autosave.status === "unsaved"
                ? "Implementation-plan changes are waiting for durable save."
                : ["failed", "offline", "conflict"].includes(autosave.status)
                  ? autosave.message || "The implementation plan has not been saved."
                  : "Implementation-plan changes are saved to the ATLAS project record."}
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
