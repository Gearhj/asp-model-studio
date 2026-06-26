import { Navigate, Route, Routes } from "react-router-dom";
import Sidebar from "../components/Sidebar";
import Dashboard from "../steps/Dashboard";
import Step01DataAcquisition from "../steps/Step01_DataAcquisition";
import Step02EDA from "../steps/Step02_EDA";
import Step03Outliers from "../steps/Step04_Outliers";
import Step04MissingValues from "../steps/Step04_MissingValues";
import Step05EncodingScaling from "../steps/Step05_EncodingScaling";
import Step06BalancingSplit from "../steps/Step06_BalancingSplit";
import Step07Train from "../steps/Step06_Train";
import Step08Evaluation from "../steps/Step08_Evaluation";
import Step09Interpretation from "../steps/Step09_Interpretation";
import { useWorkflowStore } from "../state/useWorkflowStore";

const workflowStepIds = [
  "step01",
  "step02",
  "step03",
  "step04",
  "step05",
  "step06",
  "step07",
  "step08",
  "step09",
] as const;

const stepLabels = ["Data", "EDA", "Outliers", "Missing", "Features", "Split", "Train", "Evaluate", "Interpret"];

export default function ModelingApp() {
  const steps = useWorkflowStore((state) => state.steps);
  const completed = workflowStepIds.filter((id) => steps[id] === "completed").length;
  const progress = Math.round((completed / workflowStepIds.length) * 100);

  return (
    <div className="min-h-screen bg-slate-100 text-slate-950">
      <div className="flex min-h-screen">
        <Sidebar />

        <div className="flex min-w-0 flex-1 flex-col">
          <header className="border-b border-slate-200 bg-white">
            <div className="px-5 py-4 md:px-8">
              <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
                <div>
                  <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                    Model development workbench
                  </p>
                  <h1 className="mt-1 text-2xl font-semibold text-slate-950">
                    Data Science Modeling Tool
                  </h1>
                </div>

                <div className="w-full max-w-xl">
                  <div className="mb-2 flex items-center justify-between text-xs font-medium text-slate-600">
                    <span>{completed} of {workflowStepIds.length} steps complete</span>
                    <span>{progress}%</span>
                  </div>
                  <div className="grid grid-cols-9 gap-1">
                    {stepLabels.map((label, index) => (
                      <div key={label} className="min-w-0">
                        <div
                          className={`h-2 rounded-full ${
                            index < completed ? "bg-emerald-500" : "bg-slate-200"
                          }`}
                        />
                        <div className="mt-1 truncate text-[10px] text-slate-500">{label}</div>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            </div>
          </header>

          <main className="min-w-0 flex-1 px-4 py-6 md:px-8">
            <Routes>
              <Route path="/" element={<Navigate to="/dashboard" replace />} />
              <Route path="/dashboard" element={<Dashboard />} />
              <Route path="/step01" element={<Step01DataAcquisition />} />
              <Route path="/step02" element={<Step02EDA />} />
              <Route path="/step03" element={<Step03Outliers />} />
              <Route path="/step04" element={<Step04MissingValues />} />
              <Route path="/step05" element={<Step05EncodingScaling />} />
              <Route path="/step06" element={<Step06BalancingSplit />} />
              <Route path="/step07" element={<Step07Train />} />
              <Route path="/step08" element={<Step08Evaluation />} />
              <Route path="/step09" element={<Step09Interpretation />} />
              <Route path="*" element={<Navigate to="/dashboard" replace />} />
            </Routes>
          </main>
        </div>
      </div>
    </div>
  );
}
