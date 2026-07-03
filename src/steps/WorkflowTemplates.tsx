import { useNavigate } from "react-router-dom";
import { Boxes, Play } from "lucide-react";
import BrandLogo from "../components/BrandLogo";
import { workflowTemplates } from "../config/workflows";
import { logDecision } from "../lib/decisionJournal";
import { useWorkflowStore } from "../state/useWorkflowStore";

export default function WorkflowTemplates() {
  const navigate = useNavigate();
  const startProjectFromWorkflow = useWorkflowStore((state) => state.startProjectFromWorkflow);

  return (
    <div className="w-full space-y-5">
      <section className="rounded-xl border border-slate-200/80 bg-white/90 p-5 shadow-sm">
        <BrandLogo size="md" variant="light" showSubtitle className="mb-3" />
        <div className="flex items-center gap-2">
          <Boxes size={20} className="text-slate-800" />
          <h1 className="text-xl font-semibold text-slate-950">Workflow Templates</h1>
        </div>
        <p className="mt-1 max-w-3xl text-sm text-slate-600">
          Start an ATLAS project from a governed workflow template. Templates define the journey, Atlas Guide context, and documentation outline.
        </p>
      </section>

      <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {workflowTemplates.map((template) => (
          <article key={template.id} className="grid min-h-[260px] gap-4 rounded-lg border border-slate-200/80 bg-white/90 p-5 shadow-sm">
            <div>
              <div className="flex items-start justify-between gap-3">
                <div>
                  <h2 className="text-base font-semibold text-slate-950">{template.label}</h2>
                  <p className="mt-1 text-sm leading-6 text-slate-600">{template.description}</p>
                </div>
                <span className={intensityClass(template.governanceIntensity)}>{template.governanceIntensity}</span>
              </div>
              <div className="mt-3 text-xs font-semibold uppercase tracking-wide text-slate-500">
                {template.projectType.replace(/-/g, " ")}
              </div>
            </div>

            <div>
              <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Common use cases</div>
              <div className="mt-2 flex flex-wrap gap-2">
                {template.commonUseCases.map((useCase) => (
                  <span key={useCase} className="rounded-full bg-slate-100 px-2 py-1 text-xs font-medium text-slate-700">
                    {useCase}
                  </span>
                ))}
              </div>
            </div>

            <button
              type="button"
              className="mt-auto inline-flex items-center justify-center gap-2 rounded-lg bg-slate-950 px-3 py-2 text-sm font-semibold text-white shadow-sm hover:bg-slate-800"
              onClick={() => {
                startProjectFromWorkflow({
                  projectName: template.label,
                  projectType: template.projectType,
                  workflowId: template.workflowId,
                });
                logDecision({
                  workflowStep: "Workflow Templates",
                  actionType: "workflow_setting_changed",
                  subject: "Project template",
                  previousValue: "-",
                  newValue: template.label,
                  systemRecommendation: "Select a workflow template aligned to the business problem and governance intensity.",
                  followStatus: "not_applicable",
                });
                navigate("/project-overview");
              }}
            >
              <Play size={15} />
              Start Project From Template
            </button>
          </article>
        ))}
      </section>
    </div>
  );
}

function intensityClass(intensity: string) {
  if (intensity === "high") return "rounded-full bg-rose-50 px-2 py-1 text-xs font-semibold text-rose-700";
  if (intensity === "medium") return "rounded-full bg-amber-50 px-2 py-1 text-xs font-semibold text-amber-700";
  return "rounded-full bg-emerald-50 px-2 py-1 text-xs font-semibold text-emerald-700";
}
