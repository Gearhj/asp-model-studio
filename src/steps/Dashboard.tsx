import { Link } from "react-router-dom";
import type React from "react";
import { Activity, BarChart3, CheckCircle2, Database, GitBranch, RotateCcw } from "lucide-react";
import BrandLogo from "../components/BrandLogo";
import { BRAND } from "../config/brand";
import { useWorkflowStore } from "../state/useWorkflowStore";

const steps = [
  {
    id: "step00",
    title: "Project Context",
    route: "/step00",
    description: "Define the objective, target, population, windows, costs, governance constraints, and deployment plan.",
  },
  {
    id: "step01",
    title: "Data Acquisition",
    route: "/step01",
    description: "Upload CSV data, select the target, inspect columns, and persist the sample.",
  },
  {
    id: "step01b",
    title: "Credit Bureau Review",
    route: "/step01b",
    description: "Identify bureau special values, attach metadata, choose treatments, and document rationale.",
  },
  {
    id: "step02",
    title: "Exploratory Data Analysis",
    route: "/step02",
    description: "Review distributions, box plots, correlations, and pairwise relationships.",
  },
  {
    id: "step03",
    title: "Outlier Analysis",
    route: "/step03",
    description: "Choose per-feature detection and capping methods for numeric fields.",
  },
  {
    id: "step04",
    title: "Missing Values",
    route: "/step04",
    description: "Assign imputation or drop strategies for numeric and categorical variables.",
  },
  {
    id: "step05",
    title: "Feature Engineering",
    route: "/step05",
    description: "Create encodings, scaling choices, bins, interactions, and rule features.",
  },
  {
    id: "step06",
    title: "Balancing & Split",
    route: "/step06",
    description: "Set holdout or cross-validation strategy and class balancing behavior.",
  },
  {
    id: "step07",
    title: "Model Training",
    route: "/step07",
    description: "Select candidate models, submit training, and review basic run metrics.",
  },
  {
    id: "step08",
    title: "Evaluation",
    route: "/step08",
    description: "Compare the leaderboard, champion metrics, curves, and decile lift.",
  },
  {
    id: "step09",
    title: "Model Interpretation",
    route: "/step09",
    description: "Review feature importance, PDP, SHAP-style impacts, sensitivity, model details, and RFE.",
  },
  {
    id: "step10",
    title: "Final Scoring",
    route: "/step10",
    description: "Score holdout and OOT data, review stability, and prepare final production outputs.",
  },
  {
    id: "step11",
    title: "Model Development Document",
    route: "/step11",
    description: "Generate the formal model development document for governance and validation.",
  },
] as const;

type StepId = typeof steps[number]["id"];

export default function Dashboard() {
  const workflowSteps = useWorkflowStore((state) => state.steps);
  const hasDataset = useWorkflowStore((state) => state.hasDataset);
  const reset = useWorkflowStore((state) => state.reset);

  const completed = steps.filter((step) => workflowSteps[step.id as StepId] === "completed").length;
  const inProgress =
    steps.find((step) => workflowSteps[step.id as StepId] !== "completed") ?? steps[steps.length - 1];
  const progress = Math.round((completed / steps.length) * 100);

  return (
    <div className="w-full space-y-5">
      <section className="rounded-xl border border-slate-200/80 bg-white/90 p-5 shadow-sm">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <BrandLogo size="lg" variant="light" showSubtitle />
            <p className="mt-3 max-w-2xl text-sm text-slate-600">
              Navigate regulated model development from source data to documented champion model.
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Link to="/step00" className="rounded-lg bg-slate-950 px-3 py-2 text-sm font-semibold text-white shadow-sm hover:bg-slate-800">
              Start New Project
            </Link>
            <Link to={inProgress.route} className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-700 shadow-sm hover:bg-slate-50">
              Continue Journey
            </Link>
            <Link to="/step01" className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-700 shadow-sm hover:bg-slate-50">
              Open Existing Project
            </Link>
            <Link to="/step11" className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-700 shadow-sm hover:bg-slate-50">
              View Model Development Document
            </Link>
          </div>
        </div>
        <div className="mt-3 text-xs font-medium text-slate-500">{BRAND.shortDescription}</div>
      </section>

      <section className="grid gap-4 md:grid-cols-4">
        <StatCard icon={<GitBranch size={18} />} label="Journey Steps" value={steps.length} />
        <StatCard icon={<CheckCircle2 size={18} />} label="Milestones Completed" value={completed} />
        <StatCard icon={<Activity size={18} />} label="Progress" value={`${progress}%`} />
        <StatCard icon={<Database size={18} />} label="Dataset Loaded" value={hasDataset ? "Yes" : "No"} />
      </section>

      <section className="rounded-lg border border-slate-200/80 bg-white/90 shadow-sm">
        <div className="flex flex-col gap-3 border-b border-slate-200 px-5 py-4 md:flex-row md:items-center md:justify-between">
          <div>
            <h2 className="text-lg font-semibold text-slate-950">Model Development Journey</h2>
            <p className="text-sm text-slate-500">
              Capture each decision point from source data through model evaluation.
            </p>
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              className="inline-flex items-center gap-2 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-700 shadow-sm hover:bg-slate-50"
              onClick={reset}
            >
              <RotateCcw size={15} />
              Reset Progress
            </button>
            <Link
              to={inProgress.route}
              className="inline-flex items-center gap-2 rounded-lg bg-slate-950 px-3 py-2 text-sm font-medium text-white shadow-sm hover:bg-slate-800"
            >
              <BarChart3 size={15} />
              Continue Journey
            </Link>
          </div>
        </div>

        <div className="grid gap-3 p-4 sm:grid-cols-2 xl:grid-cols-3">
          {steps.map((step, index) => {
            const status = workflowSteps[step.id as StepId] ?? "pending";
            return (
              <article
                key={step.id}
                className="grid min-h-[150px] gap-4 rounded-lg border border-slate-200/80 bg-slate-50/70 p-4 shadow-[inset_0_1px_0_rgba(255,255,255,0.9)]"
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="flex min-w-0 items-center gap-3">
                    <div
                      className={`grid h-8 w-8 shrink-0 place-items-center rounded-full text-xs font-semibold ${
                        status === "completed"
                          ? "bg-emerald-100 text-emerald-700"
                          : "bg-white text-slate-600 ring-1 ring-slate-200"
                      }`}
                    >
                      {index + 1}
                    </div>
                    <div className="min-w-0">
                      <h3 className="truncate font-semibold text-slate-950">{step.title}</h3>
                      <span
                        className={`mt-1 inline-flex rounded-full px-2 py-0.5 text-[11px] font-medium ${
                          status === "completed"
                            ? "bg-emerald-50 text-emerald-700"
                            : "bg-white text-slate-600 ring-1 ring-slate-200"
                        }`}
                      >
                        {status === "completed" ? "Completed" : "Pending"}
                      </span>
                    </div>
                  </div>
                  <Link
                    to={step.route}
                    className="inline-flex shrink-0 justify-center rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm font-medium text-slate-700 shadow-sm hover:bg-slate-50"
                  >
                    Open
                  </Link>
                </div>
                <p className="text-sm leading-5 text-slate-500">{step.description}</p>
              </article>
            );
          })}
        </div>
      </section>
    </div>
  );
}

function StatCard({
  icon,
  label,
  value,
}: {
  icon: React.ReactNode;
  label: string;
  value: number | string;
}) {
  return (
    <div className="rounded-lg border border-slate-200/80 bg-white/90 p-4 shadow-sm">
      <div className="flex items-center justify-between text-slate-500">
        <span className="text-xs font-semibold uppercase tracking-wide">{label}</span>
        {icon}
      </div>
      <div className="mt-3 text-2xl font-semibold text-slate-950">{value}</div>
    </div>
  );
}
