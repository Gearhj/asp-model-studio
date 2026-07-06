import { lazy, Suspense } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import CopilotCard from "../components/CopilotCard";
import BrandLogo from "../components/BrandLogo";
import ModeSwitcher from "../components/ModeSwitcher";
import ProjectSaveStatus from "../components/ProjectSaveStatus";
import Sidebar from "../components/Sidebar";
import Dashboard from "../steps/Dashboard";
import DecisionJournal from "../steps/DecisionJournal";
import DatasetDetail from "../steps/DatasetDetail";
import DatasetLibrary from "../steps/DatasetLibrary";
import ExperimentComparison from "../steps/ExperimentComparison";
import GovernanceReport from "../steps/GovernanceReport";
import IntelligentWorkbench from "../steps/IntelligentWorkbench";
import NotebookExport from "../steps/NotebookExport";
import NewProject from "../steps/NewProject";
import ProjectOverview from "../steps/ProjectOverview";
import { ExportsPage, OpenProject, SettingsPage } from "../steps/ProjectUtilityPages";
import RegisterDataset from "../steps/RegisterDataset";
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
import Step12ModelImplementation from "../steps/Step12_ModelImplementation";
import Step13ModelMonitoring from "../steps/Step13_ModelMonitoring";
import SystemDiagnostics from "../steps/SystemDiagnostics";
import WorkflowTemplates from "../steps/WorkflowTemplates";
import { useWorkflowStore } from "../state/useWorkflowStore";
import { experimentalDesignJourney } from "../config/workflows";

const ExperimentalDesignWorkflowPage = lazy(() => import("../features/experimental-design/pages/ExperimentalDesignWorkflowPage"));

export default function ModelingApp() {
  const workflowSteps = useWorkflowStore((state) => state.workflowSteps);
  const workflowId = useWorkflowStore((state) => state.workflowId);
  const restoreWarnings = useWorkflowStore((state) => state.restoreWarnings);
  const completed = workflowSteps.filter((step) => step.status === "complete").length;
  const progress = Math.round((completed / Math.max(1, workflowSteps.length)) * 100);

  return (
    <div className="min-h-screen bg-[#f5f5f7] text-slate-950">
      <div className="flex min-h-screen">
        <Sidebar />

        <div className="flex min-w-0 flex-1 flex-col">
          <header className="sticky top-0 z-20 border-b border-white/70 bg-white/75 shadow-[0_1px_0_rgba(15,23,42,0.04)] backdrop-blur-xl">
            <div className="px-4 py-3 sm:px-5 lg:px-6 xl:px-8">
              <div className="grid gap-3 xl:grid-cols-[minmax(260px,0.7fr)_minmax(360px,1fr)_minmax(360px,1fr)] xl:items-center">
                <div className="flex flex-wrap items-center gap-3">
                  <BrandLogo size="md" variant="light" showSubtitle />
                  <ProjectSaveStatus />
                </div>

                <ModeSwitcher />

                <div className="w-full rounded-lg border border-slate-200/80 bg-white/70 px-3 py-2 shadow-sm">
                  <div className="mb-2 flex items-center justify-between text-[11px] font-semibold text-slate-600">
                    <span>{completed} of {workflowSteps.length} steps complete</span>
                    <span>{progress}%</span>
                  </div>
                  <div className="grid gap-1" style={{ gridTemplateColumns: `repeat(${Math.max(1, workflowSteps.length)}, minmax(0, 1fr))` }}>
                    {workflowSteps.map((step, index) => (
                      <div
                        key={step.id}
                        className="min-w-0"
                        title={
                          workflowId === "experimental-design"
                            ? experimentalDesignJourney.find((item) => item.id === step.id)?.question ?? step.description
                            : step.description
                        }
                      >
                        <div
                          className={`h-1.5 rounded-full ${
                            index < completed || step.status === "complete" ? "bg-slate-950" : step.status === "skipped" ? "bg-amber-300" : "bg-slate-200"
                          }`}
                        />
                        <div className="mt-1 truncate text-[10px] font-medium text-slate-500">{step.shortLabel ?? step.label}</div>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            </div>
          </header>

          <main className="min-w-0 flex-1 px-3 py-4 sm:px-4 lg:px-6 xl:px-8">
            <div className="mx-auto grid w-full max-w-[1760px] gap-4 xl:grid-cols-[minmax(0,1fr)_320px]">
              <div className="min-w-0">
                {restoreWarnings.length > 0 && (
                  <section className="mb-4 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900 shadow-sm">
                    <div className="font-semibold">Project restored with compact artifacts.</div>
                    <p className="mt-1">
                      Workflow decisions and summaries were restored. Some large artifacts are intentionally not stored
                      in browser persistence.
                    </p>
                    <ul className="mt-2 list-disc space-y-1 pl-5">
                      {restoreWarnings.map((warning) => (
                        <li key={warning}>{warning}</li>
                      ))}
                    </ul>
                  </section>
                )}
                <Routes>
                  <Route path="/" element={<Navigate to="/dashboard" replace />} />
                  <Route path="/workbench" element={<IntelligentWorkbench />} />
                  <Route path="/project-overview" element={<ProjectOverview />} />
                  <Route path="/projects/new" element={<NewProject />} />
                  <Route path="/projects/open" element={<OpenProject />} />
                  <Route path="/templates" element={<WorkflowTemplates />} />
                  <Route path="/datasets" element={<DatasetLibrary />} />
                  <Route path="/datasets/register" element={<RegisterDataset />} />
                  <Route path="/datasets/:datasetId" element={<DatasetDetail />} />
                  <Route path="/experiments" element={<ExperimentComparison />} />
                  <Route path="/journal" element={<DecisionJournal />} />
                  <Route path="/governance-report" element={<GovernanceReport />} />
                  <Route path="/notebook-export" element={<NotebookExport />} />
                  <Route path="/exports" element={<ExportsPage />} />
                  <Route path="/settings" element={<SettingsPage />} />
                  <Route path="/system/diagnostics" element={<SystemDiagnostics />} />
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
                  <Route path="/step12" element={<Step12ModelImplementation />} />
                  <Route path="/step13" element={<Step13ModelMonitoring />} />
                  <Route
                    path="/workflow/:workflowId/:stepNumber"
                    element={
                      <Suspense
                        fallback={
                          <div className="rounded-xl border border-slate-200 bg-white p-6 text-sm font-semibold text-slate-600 shadow-sm">
                            Loading workflow...
                          </div>
                        }
                      >
                        <ExperimentalDesignWorkflowPage />
                      </Suspense>
                    }
                  />
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
