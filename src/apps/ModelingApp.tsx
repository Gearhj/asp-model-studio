import { Navigate, Route, Routes } from "react-router-dom";
import CopilotCard from "../components/CopilotCard";
import BrandLogo from "../components/BrandLogo";
import ModeSwitcher from "../components/ModeSwitcher";
import Sidebar from "../components/Sidebar";
import Dashboard from "../steps/Dashboard";
import DecisionJournal from "../steps/DecisionJournal";
import ExperimentComparison from "../steps/ExperimentComparison";
import GovernanceReport from "../steps/GovernanceReport";
import IntelligentWorkbench from "../steps/IntelligentWorkbench";
import NotebookExport from "../steps/NotebookExport";
import Step00ProjectContext from "../steps/Step00_ProjectContext";
import Step01BCreditBureauReview from "../steps/Step01B_CreditBureauReview";
import Step01DataAcquisition from "../steps/Step01_DataAcquisition";
import Step02EDA from "../steps/Step02_EDA";
import Step03Outliers from "../steps/Step04_Outliers";
import Step04MissingValues from "../steps/Step04_MissingValues";
import Step05EncodingScaling from "../steps/Step05_EncodingScaling";
import Step06BalancingSplit from "../steps/Step06_BalancingSplit";
import Step07Train from "../steps/Step06_Train";
import Step08Evaluation from "../steps/Step08_Evaluation";
import Step09Interpretation from "../steps/Step09_Interpretation";
import Step10Scoring from "../steps/Step10_Scoring";
import Step11ModelDevelopmentDocument from "../steps/Step11_ModelDevelopmentDocument";
import { useWorkflowStore } from "../state/useWorkflowStore";

const workflowStepIds = [
  "step00",
  "step01",
  "step01b",
  "step02",
  "step03",
  "step04",
  "step05",
  "step06",
  "step07",
  "step08",
  "step09",
  "step10",
  "step11",
] as const;

const stepLabels = [
  "Context",
  "Data",
  "Bureau",
  "EDA",
  "Outliers",
  "Missing",
  "Features",
  "Split",
  "Train",
  "Evaluate",
  "Interpret",
  "Score",
  "Document",
];

export default function ModelingApp() {
  const steps = useWorkflowStore((state) => state.steps);
  const completed = workflowStepIds.filter((id) => steps[id] === "completed").length;
  const progress = Math.round((completed / workflowStepIds.length) * 100);

  return (
    <div className="min-h-screen bg-[#f5f5f7] text-slate-950">
      <div className="flex min-h-screen">
        <Sidebar />

        <div className="flex min-w-0 flex-1 flex-col">
          <header className="sticky top-0 z-20 border-b border-white/70 bg-white/75 shadow-[0_1px_0_rgba(15,23,42,0.04)] backdrop-blur-xl">
            <div className="px-4 py-3 sm:px-5 lg:px-6 xl:px-8">
              <div className="grid gap-3 xl:grid-cols-[minmax(220px,0.7fr)_minmax(360px,1fr)_minmax(360px,1fr)] xl:items-center">
                <BrandLogo size="md" variant="light" showSubtitle />

                <ModeSwitcher />

                <div className="w-full rounded-lg border border-slate-200/80 bg-white/70 px-3 py-2 shadow-sm">
                  <div className="mb-2 flex items-center justify-between text-[11px] font-semibold text-slate-600">
                    <span>{completed} of {workflowStepIds.length} steps complete</span>
                    <span>{progress}%</span>
                  </div>
                  <div className="grid grid-cols-[repeat(13,minmax(0,1fr))] gap-1">
                    {stepLabels.map((label, index) => (
                      <div key={label} className="min-w-0">
                        <div
                          className={`h-1.5 rounded-full ${
                            index < completed ? "bg-slate-950" : "bg-slate-200"
                          }`}
                        />
                        <div className="mt-1 truncate text-[10px] font-medium text-slate-500">{label}</div>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            </div>
          </header>

          <main className="min-w-0 flex-1 px-3 py-4 sm:px-4 lg:px-6 xl:px-8">
            <div className="mx-auto grid w-full max-w-[1760px] gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
              <div className="min-w-0">
                <Routes>
                  <Route path="/" element={<Navigate to="/dashboard" replace />} />
                  <Route path="/workbench" element={<IntelligentWorkbench />} />
                  <Route path="/experiments" element={<ExperimentComparison />} />
                  <Route path="/journal" element={<DecisionJournal />} />
                  <Route path="/governance-report" element={<GovernanceReport />} />
                  <Route path="/notebook-export" element={<NotebookExport />} />
                  <Route path="/dashboard" element={<Dashboard />} />
                  <Route path="/step00" element={<Step00ProjectContext />} />
                  <Route path="/step01" element={<Step01DataAcquisition />} />
                  <Route path="/step01b" element={<Step01BCreditBureauReview />} />
                  <Route path="/step02" element={<Step02EDA />} />
                  <Route path="/step03" element={<Step03Outliers />} />
                  <Route path="/step04" element={<Step04MissingValues />} />
                  <Route path="/step05" element={<Step05EncodingScaling />} />
                  <Route path="/step06" element={<Step06BalancingSplit />} />
                  <Route path="/step07" element={<Step07Train />} />
                  <Route path="/step08" element={<Step08Evaluation />} />
                  <Route path="/step09" element={<Step09Interpretation />} />
                  <Route path="/step10" element={<Step10Scoring />} />
                  <Route path="/step11" element={<Step11ModelDevelopmentDocument />} />
                  <Route path="*" element={<Navigate to="/dashboard" replace />} />
                </Routes>
              </div>
              <CopilotCard />
            </div>
          </main>
        </div>
      </div>
    </div>
  );
}
