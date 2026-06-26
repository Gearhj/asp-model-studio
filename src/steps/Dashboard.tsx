import { Link } from "react-router-dom";
import type React from "react";
import { Activity, BarChart3, CheckCircle2, Database, GitBranch, RotateCcw } from "lucide-react";
import { useWorkflowStore } from "../state/useWorkflowStore";

const steps = [
  {
    id: "step01",
    title: "Data Acquisition",
    route: "/step01",
    description: "Upload CSV data, select the target, inspect columns, and persist the sample.",
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
    <div className="mx-auto max-w-7xl space-y-6">
      <section className="grid gap-4 md:grid-cols-4">
        <StatCard icon={<GitBranch size={18} />} label="Workflow Steps" value={steps.length} />
        <StatCard icon={<CheckCircle2 size={18} />} label="Completed" value={completed} />
        <StatCard icon={<Activity size={18} />} label="Progress" value={`${progress}%`} />
        <StatCard icon={<Database size={18} />} label="Dataset Loaded" value={hasDataset ? "Yes" : "No"} />
      </section>

      <section className="rounded-lg border border-slate-200 bg-white">
        <div className="flex flex-col gap-3 border-b border-slate-200 px-5 py-4 md:flex-row md:items-center md:justify-between">
          <div>
            <h2 className="text-lg font-semibold text-slate-950">Workflow Progress</h2>
            <p className="text-sm text-slate-500">
              Capture each decision point from source data through model evaluation.
            </p>
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              className="inline-flex items-center gap-2 rounded-md border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
              onClick={reset}
            >
              <RotateCcw size={15} />
              Reset Progress
            </button>
            <Link
              to={inProgress.route}
              className="inline-flex items-center gap-2 rounded-md bg-indigo-600 px-3 py-2 text-sm font-medium text-white hover:bg-indigo-700"
            >
              <BarChart3 size={15} />
              Continue
            </Link>
          </div>
        </div>

        <div className="divide-y divide-slate-100">
          {steps.map((step, index) => {
            const status = workflowSteps[step.id as StepId] ?? "pending";
            return (
              <article key={step.id} className="grid gap-4 px-5 py-4 md:grid-cols-[44px_minmax(0,1fr)_auto] md:items-center">
                <div
                  className={`grid h-10 w-10 place-items-center rounded-full text-sm font-semibold ${
                    status === "completed"
                      ? "bg-emerald-100 text-emerald-700"
                      : "bg-slate-100 text-slate-600"
                  }`}
                >
                  {index + 1}
                </div>
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <h3 className="font-semibold text-slate-950">{step.title}</h3>
                    <span
                      className={`rounded-full px-2 py-0.5 text-xs font-medium ${
                        status === "completed"
                          ? "bg-emerald-50 text-emerald-700"
                          : "bg-slate-100 text-slate-600"
                      }`}
                    >
                      {status === "completed" ? "Completed" : "Pending"}
                    </span>
                  </div>
                  <p className="mt-1 text-sm text-slate-500">{step.description}</p>
                </div>
                <Link
                  to={step.route}
                  className="inline-flex justify-center rounded-md border border-slate-300 px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
                >
                  Open
                </Link>
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
    <div className="rounded-lg border border-slate-200 bg-white p-4">
      <div className="flex items-center justify-between text-slate-500">
        <span className="text-xs font-semibold uppercase tracking-wide">{label}</span>
        {icon}
      </div>
      <div className="mt-3 text-2xl font-semibold text-slate-950">{value}</div>
    </div>
  );
}
