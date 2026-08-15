import { useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { ArrowRight, BookOpenCheck, CheckCircle2, ExternalLink, FileText, ShieldCheck } from "lucide-react";
import BrandLogo from "../components/BrandLogo";
import {
  useAuthoritativeProjectContext,
  usePredictiveIdentity,
} from "../components/PredictiveIdentityProvider";
import {
  buildModelDevelopmentDocument,
  type ModelDevelopmentDocument,
  type ModelDevelopmentDocumentOptions,
} from "../lib/modelDevelopmentDocument";
import { loadProjectDataset } from "../lib/localDataset";
import { createSnapshotFromState, upsertProjectSnapshot } from "../lib/localProjects";
import {
  DURABLE_WORKFLOW_COMPLETION_ERROR,
  saveWorkflowStateToDatabase,
  workflowCompletionSnapshot,
} from "../lib/serverPersistence";
import { useWorkflowStore } from "../state/useWorkflowStore";
import { projectWorkflowRoute } from "../lib/projectScopedRoutes";
import { useExactPromotedModelIdentity } from "../lib/useExactPromotedModelIdentity";
import { persistPredictiveWorkflowCompletionEvidence } from "../lib/predictiveWorkflowCompletionEvidence";

export default function Step11ModelDevelopmentDocument() {
  const [navigationError, setNavigationError] = useState("");
  const navigate = useNavigate();
  const markComplete = useWorkflowStore((state) => state.markComplete);
  const workflowProjectId = useWorkflowStore((state) => state.projectId);
  const workflowSteps = useWorkflowStore((state) => state.workflowSteps);
  const {
    readiness: projectReadiness,
    authenticatedUserId,
  } = useAuthoritativeProjectContext();
  const {
    readiness: identityReadiness,
    dataAcquisitionContextReadiness,
  } = usePredictiveIdentity();
  const projectId = projectReadiness.status === "ready"
    ? projectReadiness.project.projectId
    : "";
  const projectName = projectReadiness.status === "ready"
    ? projectReadiness.project.projectName
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
  const dataset = useMemo(
    () => projectId && authenticatedUserId
      ? loadProjectDataset(authenticatedUserId, projectId)
      : null,
    [authenticatedUserId, datasetIdentity?.dataset_version_id, projectId],
  );
  const documentOptions = useMemo<ModelDevelopmentDocumentOptions>(
    () => ({
      includeFullDecisionJournalAppendix: false,
      projectId,
      authenticatedUserId,
      dataset,
      datasetIdentity,
      target,
      promotedModelIdentity: promotedModel.identity,
    }),
    [
      authenticatedUserId,
      dataset,
      datasetIdentity,
      projectId,
      promotedModel.identity,
      target,
    ],
  );
  const documentResult = useMemo<{
    document: ModelDevelopmentDocument | null;
    error: string;
  }>(
    () => {
      if (promotedModel.status !== "ready" || !promotedModel.identity) {
        return { document: null, error: promotedModel.error };
      }
      try {
        return {
          document: buildModelDevelopmentDocument("governance", documentOptions),
          error: "",
        };
      } catch (error) {
        return {
          document: null,
          error: error instanceof Error
            ? error.message
            : "The exact promoted champion could not be bound to this documentation checkpoint.",
        };
      }
    },
    [documentOptions, promotedModel.error, promotedModel.identity, promotedModel.status],
  );
  const document = documentResult.document;
  const projectScopeMatches = Boolean(projectId && workflowProjectId === projectId);
  const canContinue = promotedModel.status === "ready"
    && Boolean(promotedModel.identity)
    && Boolean(document)
    && projectScopeMatches;
  const completedWorkflowSteps = workflowSteps.filter((step) => step.status === "complete").length;
  const readiness = Math.round((completedWorkflowSteps / Math.max(1, workflowSteps.length)) * 100);
  const requiredSections = document?.sections.length ?? 0;
  const missingEvidenceCount = document?.sections.filter((section) =>
    /needs evidence|not documented|not available|missing/i.test(section.content)
  ).length ?? requiredSections;

  async function handleContinue() {
    try {
      setNavigationError("");
      if (!canContinue || !promotedModel.identity || !datasetIdentity || !document) {
        throw new Error(
          documentResult.error
            || promotedModel.error
            || "Documentation cannot continue until the exact backend-verified champion and durable model version match this project.",
        );
      }
      await persistPredictiveWorkflowCompletionEvidence({
        datasetIdentity,
        projectName,
        stepId: "step11",
        evidenceType: "documentation",
        artifactType: "model_development_document",
        artifactId: document.fileBaseName,
        documentIds: [document.fileBaseName],
        title: "Model Documentation Readiness Completion",
        summary: `${requiredSections} governed documentation sections were assembled for the exact promoted model; ${missingEvidenceCount} section${missingEvidenceCount === 1 ? "" : "s"} contain readiness language requiring reviewer attention.`,
        supportsSections: ["Model Development Document", "Documentation Review", "Governance"],
        tags: ["documentation", "mdd", "readiness_checkpoint"],
        model: promotedModel.identity,
        payload: {
          documentTitle: document.title,
          documentMode: document.mode,
          requiredSections,
          missingEvidenceCount,
          generatedAt: document.generatedAt,
        },
      });
      const completedSnapshot = workflowCompletionSnapshot(
        createSnapshotFromState(useWorkflowStore.getState()),
        "step11",
        "step12",
      );
      const persisted = await saveWorkflowStateToDatabase(completedSnapshot, "step11");
      if (!persisted) throw new Error(DURABLE_WORKFLOW_COMPLETION_ERROR);
      markComplete("step11");
      upsertProjectSnapshot(completedSnapshot, "browser");
      navigate(projectWorkflowRoute(projectId, "/step12"));
      window.scrollTo({ top: 0, left: 0 });
    } catch (error: any) {
      setNavigationError(error?.message ?? "ATLAS could not save this documentation checkpoint before navigating.");
    }
  }

  return (
    <div className="w-full space-y-5">
      <div className="flex flex-col gap-3 pt-2 xl:flex-row xl:items-end xl:justify-between">
        <div>
          <BrandLogo size="md" variant="light" showSubtitle className="mb-3" />
          <div className="flex items-center gap-2">
            <BookOpenCheck size={21} className="text-blue-700" />
            <h1 className="text-xl font-semibold text-slate-950">Step 11: Documentation Review</h1>
          </div>
          <p className="mt-1 max-w-3xl text-sm text-slate-600">
            Confirm that the current project is ready for governed documentation. The authoritative workspace is
            Model Documentation Studio.
          </p>
        </div>
        <Link
          to="/model-document-studio"
          className="inline-flex items-center justify-center gap-2 rounded-lg bg-slate-950 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-slate-800"
        >
          Open Model Documentation Studio
          <ExternalLink size={15} />
        </Link>
      </div>

      <section className="rounded-xl border border-blue-200 bg-blue-50 px-5 py-4 text-blue-950 shadow-sm">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <div className="text-xs font-semibold uppercase tracking-[0.14em] text-blue-700">Documentation checkpoint</div>
            <h2 className="mt-1 text-lg font-semibold">Model documentation is consolidated in the Studio.</h2>
            <p className="mt-2 max-w-4xl text-sm leading-6 text-blue-900">
              This workflow step is a readiness checkpoint. Use the Studio to assemble the Model Development Document,
              attach evidence, run quality checks, and export Word, PowerPoint, and Excel evidence packages.
            </p>
          </div>
          <div className="rounded-xl border border-blue-200 bg-white px-4 py-3 text-center shadow-sm">
            <div className="text-2xl font-semibold text-blue-800">{readiness}%</div>
            <div className="text-xs font-semibold uppercase tracking-wide text-blue-700">workflow readiness</div>
          </div>
        </div>
      </section>

      <section className="grid gap-4 lg:grid-cols-4">
        <MetricCard label="Project" value={projectName || "Current Project"} />
        <MetricCard label="Target" value={target || "Not selected"} />
        <MetricCard label="Champion" value={promotedModel.identity?.modelName || "Not verified"} />
        <MetricCard label="Required sections" value={String(requiredSections)} />
      </section>

      <section
        data-testid="mdd-promoted-model-identity"
        className={`rounded-xl border p-5 shadow-sm ${
          canContinue
            ? "border-emerald-200 bg-emerald-50 text-emerald-950"
            : "border-amber-200 bg-amber-50 text-amber-950"
        }`}
      >
        <div className="flex items-center gap-2">
          <ShieldCheck size={18} />
          <h2 className="text-base font-semibold">Exact champion documentation identity</h2>
        </div>
        {promotedModel.status === "ready" && promotedModel.identity && projectScopeMatches ? (
          <div className="mt-3 grid gap-3 text-xs sm:grid-cols-2 xl:grid-cols-4">
            <IdentityFact label="Champion model" value={promotedModel.identity.modelName} />
            <IdentityFact label="Model version ID" value={promotedModel.identity.modelVersionId} mono />
            <IdentityFact label="Candidate ID" value={promotedModel.identity.candidateId} mono />
            <IdentityFact label="Training run ID" value={promotedModel.identity.trainingRunId} mono />
            <IdentityFact label="Dataset version" value={promotedModel.identity.datasetVersionId} mono />
            <IdentityFact label="Feature manifest" value={promotedModel.identity.featureManifestVersion} mono />
            <IdentityFact label="Validation design" value={promotedModel.identity.validationDesignId} mono />
            <IdentityFact label="Artifact verification" value={promotedModel.identity.artifactVerificationStatus} />
          </div>
        ) : (
          <p className="mt-2 text-sm" role="alert">
            {promotedModel.status === "loading"
              ? "Verifying the exact promoted model and durable model version with the Model Registry..."
              : !projectScopeMatches && projectId
                ? "The browser workflow project contradicts the exact authorized project. Reopen the project before documenting a champion."
                : documentResult.error
                  || promotedModel.error
                  || "An exact backend-verified champion is required before this documentation checkpoint can continue."}
          </p>
        )}
        <p className="mt-3 text-xs leading-5">
          This identity is read-only and comes from the durable Model Registry promotion. Browser experiment flags cannot select or replace the documented champion.
        </p>
      </section>

      <section className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
        <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
          <div className="flex items-center gap-2">
            <ShieldCheck size={18} className="text-emerald-700" />
            <h2 className="text-base font-semibold text-slate-950">Documentation readiness</h2>
          </div>
          <p className="mt-2 text-sm leading-6 text-slate-600">
            The Studio is the single documentation workspace. It handles evidence assembly, section drafting,
            document quality checks, governance notes, and exports. This checkpoint only verifies that the project
            has enough current workflow evidence to proceed.
          </p>
          <div className="mt-4 grid gap-3 md:grid-cols-2">
            <ChecklistItem ready={Boolean(projectName)} label="Project context available" />
            <ChecklistItem ready={Boolean(target)} label="Target or response selected" />
            <ChecklistItem ready={Boolean(promotedModel.identity && document)} label="Champion model selected" />
            <ChecklistItem ready={missingEvidenceCount < requiredSections} label="Evidence available for document sections" />
          </div>
        </div>

        <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
          <div className="flex items-center gap-2">
            <FileText size={18} className="text-slate-700" />
            <h2 className="text-base font-semibold text-slate-950">Studio responsibilities</h2>
          </div>
          <ul className="mt-3 space-y-2 text-sm leading-6 text-slate-700">
            <li>Model Development Document template</li>
            <li>Evidence coverage and quality checks</li>
            <li>Governance notes and documentation readiness</li>
            <li>Word, PowerPoint, and Excel evidence exports</li>
          </ul>
          <Link
            to="/model-document-studio"
            className="mt-4 inline-flex w-full items-center justify-center gap-2 rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm font-semibold text-slate-800 hover:border-blue-300 hover:text-blue-700"
          >
            Open Studio Workspace
            <ExternalLink size={15} />
          </Link>
        </div>
      </section>

      <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
        <h2 className="text-base font-semibold text-slate-950">Current document outline preview</h2>
        <p className="mt-1 text-sm text-slate-600">
          The Studio controls editing and export. This preview confirms the current Model Development Document template
          is available for this project.
        </p>
        <div className="mt-4 grid gap-2 md:grid-cols-2 xl:grid-cols-3">
          {(document?.sections ?? []).slice(0, 12).map((section) => (
            <div key={section.number} className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-700">
              <span className="font-semibold text-slate-950">{section.number}.</span> {section.title}
            </div>
          ))}
        </div>
      </section>

      <div className="flex flex-col items-center gap-3 pb-12 pt-2">
        {navigationError && (
          <div className="w-full max-w-2xl rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-800">
            {navigationError}
          </div>
        )}
        <button
          type="button"
          className="inline-flex items-center gap-2 rounded-lg bg-indigo-600 px-5 py-2.5 text-sm font-semibold text-white shadow-sm hover:bg-indigo-700 disabled:cursor-not-allowed disabled:bg-slate-300 disabled:text-slate-600"
          onClick={handleContinue}
          disabled={!canContinue}
          title={canContinue
            ? "Save the exact champion documentation checkpoint and continue."
            : documentResult.error || promotedModel.error || "Verify the exact durable champion before continuing."}
        >
          Mark Complete & Continue to Implementation
          <ArrowRight size={16} />
        </button>
      </div>
    </div>
  );
}

function MetricCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
      <div className="text-[11px] font-semibold uppercase tracking-[0.12em] text-slate-500">{label}</div>
      <div className="mt-2 truncate text-lg font-semibold text-slate-950" title={value}>
        {value}
      </div>
    </div>
  );
}

function IdentityFact({
  label,
  value,
  mono = false,
}: {
  label: string;
  value: string;
  mono?: boolean;
}) {
  return (
    <div className="rounded-lg border border-current/15 bg-white/70 px-3 py-2">
      <div className="font-semibold uppercase tracking-wide opacity-70">{label}</div>
      <div className={`mt-1 break-all font-semibold ${mono ? "font-mono" : ""}`}>{value}</div>
    </div>
  );
}

function ChecklistItem({ ready, label }: { ready: boolean; label: string }) {
  return (
    <div className="flex items-center gap-2 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm">
      <CheckCircle2 size={16} className={ready ? "text-emerald-600" : "text-slate-400"} />
      <span className={ready ? "font-medium text-slate-800" : "text-slate-500"}>{label}</span>
    </div>
  );
}
