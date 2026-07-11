import { useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { ArrowRight, BookOpenCheck, CheckCircle2, ExternalLink, FileText, ShieldCheck } from "lucide-react";
import BrandLogo from "../components/BrandLogo";
import {
  buildModelDevelopmentDocument,
  type ModelDevelopmentDocument,
  type ModelDevelopmentDocumentOptions,
} from "../lib/modelDevelopmentDocument";
import { loadExperiments } from "../lib/experimentTracking";
import { loadLocalDataset } from "../lib/localDataset";
import { upsertProjectFromState } from "../lib/localProjects";
import { useWorkflowStore } from "../state/useWorkflowStore";

export default function Step11ModelDevelopmentDocument() {
  const [navigationError, setNavigationError] = useState("");
  const navigate = useNavigate();
  const markComplete = useWorkflowStore((state) => state.markComplete);
  const projectName = useWorkflowStore((state) => state.projectName);
  const workflowSteps = useWorkflowStore((state) => state.workflowSteps);
  const dataset = useMemo(() => loadLocalDataset(), []);
  const champion = useMemo(() => loadExperiments().find((experiment) => experiment.champion) ?? null, []);
  const documentOptions = useMemo<ModelDevelopmentDocumentOptions>(
    () => ({ includeFullDecisionJournalAppendix: false }),
    []
  );
  const document = useMemo<ModelDevelopmentDocument>(
    () => buildModelDevelopmentDocument("governance", documentOptions),
    [documentOptions]
  );
  const completedWorkflowSteps = workflowSteps.filter((step) => step.status === "complete").length;
  const readiness = Math.round((completedWorkflowSteps / Math.max(1, workflowSteps.length)) * 100);
  const requiredSections = document.sections.length;
  const missingEvidenceCount = document.sections.filter((section) =>
    /needs evidence|not documented|not available|missing/i.test(section.content)
  ).length;

  async function handleContinue() {
    try {
      setNavigationError("");
      markComplete("step11");
      await upsertProjectFromState(useWorkflowStore.getState());
      navigate("/step12");
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
        <MetricCard label="Target" value={dataset?.target || "Not selected"} />
        <MetricCard label="Champion" value={champion?.modelType || "Not selected"} />
        <MetricCard label="Required sections" value={String(requiredSections)} />
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
            <ChecklistItem ready={Boolean(dataset?.target)} label="Target or response selected" />
            <ChecklistItem ready={Boolean(champion)} label="Champion model selected" />
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
          {document.sections.slice(0, 12).map((section) => (
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
          className="inline-flex items-center gap-2 rounded-lg bg-indigo-600 px-5 py-2.5 text-sm font-semibold text-white shadow-sm hover:bg-indigo-700"
          onClick={handleContinue}
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

function ChecklistItem({ ready, label }: { ready: boolean; label: string }) {
  return (
    <div className="flex items-center gap-2 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm">
      <CheckCircle2 size={16} className={ready ? "text-emerald-600" : "text-slate-400"} />
      <span className={ready ? "font-medium text-slate-800" : "text-slate-500"}>{label}</span>
    </div>
  );
}
