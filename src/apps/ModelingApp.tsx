import { lazy, Suspense, useEffect, useState } from "react";
import { Link, Navigate, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import CopilotCard from "../components/CopilotCard";
import ModeSwitcher from "../components/ModeSwitcher";
import ProjectSaveStatus from "../components/ProjectSaveStatus";
import PrivateDemoBanner from "../components/PrivateDemoBanner";
import Sidebar from "../components/Sidebar";
import AtlasProgressBar from "../components/ui/AtlasProgressBar";
import { ExportsPage, OpenProject, SettingsPage } from "../steps/ProjectUtilityPages";
import { AccountPage, AdminUsersPage, AuditPage, LoginPage, RegisterPage } from "../steps/AuthPages";
import { useWorkflowStore } from "../state/useWorkflowStore";
import { buildBreadcrumbs, breadcrumbText } from "../lib/breadcrumbs";
import { logout, me } from "../lib/auth";
import type { AtlasUser } from "../lib/datasetLibrary";
import { getUnreadNotificationCount } from "../lib/adminSharing";
import { PanelRightClose, PanelRightOpen, Sparkles } from "lucide-react";

const ExperimentalDesignWorkflowPage = lazy(() => import("../features/experimental-design/pages/ExperimentalDesignWorkflowPage"));
const Dashboard = lazy(() => import("../steps/Dashboard"));
const DecisionJournal = lazy(() => import("../steps/DecisionJournal"));
const DatasetDetail = lazy(() => import("../steps/DatasetDetail"));
const DatasetLibrary = lazy(() => import("../steps/DatasetLibrary"));
const ExperimentComparison = lazy(() => import("../steps/ExperimentComparison"));
const GovernanceReport = lazy(() => import("../steps/GovernanceReport"));
const IntelligentWorkbench = lazy(() => import("../steps/IntelligentWorkbench"));
const NotebookExport = lazy(() => import("../steps/NotebookExport"));
const NotebookStudio = lazy(() => import("../steps/NotebookStudio"));
const NewProject = lazy(() => import("../steps/NewProject"));
const ProjectOverview = lazy(() => import("../steps/ProjectOverview"));
const AnalyticsWorkbench = lazy(() => import("../steps/AnalyticsWorkbench"));
const ChartStudio = lazy(() => import("../steps/ChartStudio"));
const CreditRiskStudio = lazy(() => import("../steps/CreditRiskStudio"));
const EvidenceGraph = lazy(() => import("../steps/EvidenceGraph"));
const ModelDiagnostics = lazy(() => import("../steps/ModelDiagnostics"));
const ModelDocumentationStudio = lazy(() => import("../steps/ModelDocumentationStudio"));
const ManagementDashboard = lazy(() => import("../steps/ManagementDashboard"));
const AdminConsole = lazy(() => import("../steps/AdminConsole"));
const SharingCenter = lazy(() => import("../steps/SharingCenter"));
const NotificationCenter = lazy(() => import("../steps/NotificationCenter"));
const MonitoringCenter = lazy(() => import("../steps/MonitoringCenter"));
const MonitoringPlanDetail = lazy(() => import("../steps/MonitoringPlanDetail"));
const RegistryPage = lazy(() => import("../steps/RegistryPage"));
const RegistryAssetDetail = lazy(() => import("../steps/RegistryAssetDetail"));
const ValidationQueue = lazy(() => import("../steps/ValidationQueue"));
const ValidationCaseDetail = lazy(() => import("../steps/ValidationCaseDetail"));
const RegisterDataset = lazy(() => import("../steps/RegisterDataset"));
const SqlDataStudio = lazy(() => import("../steps/SqlDataStudio"));
const Step00ProjectContext = lazy(() => import("../steps/Step00_ProjectContext"));
const Step01DataAcquisition = lazy(() => import("../steps/Step01_DataAcquisition"));
const Step02EDA = lazy(() => import("../steps/Step02_EDA"));
const Step03Outliers = lazy(() => import("../steps/Step04_Outliers"));
const Step04MissingValues = lazy(() => import("../steps/Step04_MissingValues"));
const Step05EncodingScaling = lazy(() => import("../steps/Step05_EncodingScaling"));
const Step06BalancingSplit = lazy(() => import("../steps/Step06_BalancingSplit"));
const Step07Train = lazy(() => import("../steps/Step06_Train"));
const Step08Evaluation = lazy(() => import("../steps/Step08_Evaluation"));
const Step09Interpretation = lazy(() => import("../steps/Step09_Interpretation"));
const Step10Scoring = lazy(() => import("../steps/Step10_Scoring"));
const Step11ModelDevelopmentDocument = lazy(() => import("../steps/Step11_ModelDevelopmentDocument"));
const Step12ModelImplementation = lazy(() => import("../steps/Step12_ModelImplementation"));
const Step13ModelMonitoring = lazy(() => import("../steps/Step13_ModelMonitoring"));
const SystemDiagnostics = lazy(() => import("../steps/SystemDiagnostics"));
// Visual Intelligence Foundation Phase 1: lazy-loaded so DuckDB-Wasm, ECharts, and D3
// overlay code are absent from every unrelated page's startup bundle (Phase O requirement).
const VisualIntelligenceLab = lazy(() => import("../steps/VisualIntelligenceLab"));
const WorkflowTemplates = lazy(() => import("../steps/WorkflowTemplates"));

export default function ModelingApp() {
  const location = useLocation();
  const navigate = useNavigate();
  const [authChecked, setAuthChecked] = useState(false);
  const [authUser, setAuthUser] = useState<AtlasUser | null>(null);
  const [guideMode, setGuideMode] = useState<"full" | "compact" | "hidden">(() => (localStorage.getItem("atlas-guide-mode") as "full" | "compact" | "hidden") || "full");
  const workflowSteps = useWorkflowStore((state) => state.workflowSteps);
  const workflowId = useWorkflowStore((state) => state.workflowId);
  const normalizeWorkflowOrder = useWorkflowStore((state) => state.normalizeWorkflowOrder);
  const projectName = useWorkflowStore((state) => state.projectName);
  const restoreWarnings = useWorkflowStore((state) => state.restoreWarnings);
  const completed = workflowSteps.filter((step) => step.status === "complete").length;
  const progress = Math.round((completed / Math.max(1, workflowSteps.length)) * 100);
  const currentStep = workflowSteps.find((step) => step.status !== "complete" && step.status !== "skipped") ?? workflowSteps[workflowSteps.length - 1];
  // Breadcrumbs follow the route the user is on. `currentStep` above remains the
  // workflow's next-incomplete step and is used for progress, NOT for location.
  const breadcrumbs = buildBreadcrumbs({
    pathname: location.pathname,
    projectName,
    workflowLabel: workflowId.replace(/-/g, " ").split(" ").map((word) => (word ? word[0].toUpperCase() + word.slice(1) : word)).join(" "),
  });
  const isFullWidthStudioRoute = ["/sql-data-studio", "/notebook-studio", "/model-evidence-center", "/evidence-graph", "/credit-risk-studio", "/management-dashboard", "/registry", "/validation", "/monitoring", "/admin", "/sharing", "/notifications"].includes(location.pathname)
    || location.pathname.startsWith("/registry/")
    || location.pathname.startsWith("/validation/")
    || location.pathname.startsWith("/monitoring/")
    || location.pathname.startsWith("/project-monitoring/")
    || location.pathname.startsWith("/project-validation/");

  useEffect(() => {
    let cancelled = false;
    me()
      .then((payload) => {
        if (!cancelled) setAuthUser(payload.user);
      })
      .catch(() => {
        if (!cancelled) setAuthUser(null);
      })
      .finally(() => {
        if (!cancelled) setAuthChecked(true);
      });
    return () => {
      cancelled = true;
    };
  }, [location.pathname]);

  useEffect(() => {
    if (workflowId) {
      normalizeWorkflowOrder(workflowId);
    }
  }, [normalizeWorkflowOrder, workflowId]);

  const cycleGuideMode = () => {
    setGuideMode((current) => {
      const next = current === "full" ? "compact" : current === "compact" ? "hidden" : "full";
      localStorage.setItem("atlas-guide-mode", next);
      return next;
    });
  };

  if (!authChecked) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-[#f5f5f7] text-sm font-semibold text-slate-600">
        Loading ATLAS security context...
      </div>
    );
  }

  if (!authUser) {
    return (
      <div className="min-h-screen bg-[#f5f5f7] px-4 py-8 text-slate-950">
        <Routes>
        <Route path="/login" element={<LoginPage onAuthenticated={setAuthUser} />} />
        <Route path="/register" element={<RegisterPage onAuthenticated={setAuthUser} />} />
          <Route path="*" element={<Navigate to="/login" replace />} />
        </Routes>
      </div>
    );
  }

  return (
    <div className="atlas-app-bg min-h-screen">
      <div className="flex min-h-screen">
        <Sidebar />

        <div className="flex min-w-0 flex-1 flex-col">
          <header className="sticky top-0 z-20 border-b border-slate-200/80 bg-white/85 shadow-[0_1px_0_rgba(15,23,42,0.04)] backdrop-blur-xl">
            <div className="flex min-h-[68px] flex-col gap-3 px-4 py-3 sm:px-5 lg:px-6 xl:px-8 2xl:flex-row 2xl:items-center 2xl:justify-between">
              <div className="flex min-w-0 flex-1 flex-wrap items-center gap-3">
                <div className="min-w-0">
                  {/* Derived from the ACTIVE ROUTE, never from workflow completion
                      state -- see src/lib/breadcrumbs.ts for the defect this
                      replaced (a completed Data Acquisition made every page
                      display ".../ EDA"). */}
                  <nav
                    aria-label="Breadcrumb"
                    data-testid="atlas-breadcrumb"
                    data-breadcrumb={breadcrumbText(breadcrumbs)}
                  >
                    <ol className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 text-sm">
                      {breadcrumbs.map((crumb, index) => (
                        <li key={`${crumb.label}-${index}`} className="flex min-w-0 items-center gap-2">
                          {index > 0 ? <span aria-hidden="true" className="text-slate-300">/</span> : null}
                          {crumb.current ? (
                            <span
                              aria-current="page"
                              data-testid="atlas-breadcrumb-current"
                              className="truncate font-semibold text-slate-950"
                            >
                              {crumb.label}
                            </span>
                          ) : crumb.href ? (
                            <Link to={crumb.href} className="truncate text-slate-600 hover:text-slate-900">
                              {crumb.label}
                            </Link>
                          ) : (
                            <span className="truncate text-slate-600">{crumb.label}</span>
                          )}
                        </li>
                      ))}
                    </ol>
                  </nav>
                </div>
                <ProjectSaveStatus />
              </div>
              <div className="flex w-full min-w-0 flex-wrap items-center gap-3 2xl:w-auto 2xl:flex-nowrap">
                <div className="min-w-0 flex-[1_1_560px] overflow-hidden rounded-xl border border-slate-200 bg-white/75 p-1 2xl:flex-none">
                  <ModeSwitcher />
                </div>
                <div className="w-56 shrink-0 rounded-xl border border-slate-200 bg-white/80 px-3 py-2 shadow-sm">
                  <div className="mb-1 flex items-center justify-between gap-3 text-[11px] font-semibold text-slate-600">
                    <span>{completed} of {workflowSteps.length} steps</span>
                    <span>{progress}%</span>
                  </div>
                  <AtlasProgressBar value={progress} />
                </div>
                <HeaderUserMenu
                  user={authUser}
                  onLogout={async () => {
                    await logout();
                    setAuthUser(null);
                    navigate("/login");
                  }}
                />
              </div>
            </div>
          </header>

          <PrivateDemoBanner />

          <main className="min-w-0 flex-1 px-3 py-4 sm:px-4 lg:px-6 xl:px-8">
            <div className={`mx-auto grid w-full max-w-[1880px] gap-4 ${isFullWidthStudioRoute || guideMode === "hidden" ? "xl:grid-cols-1" : guideMode === "compact" ? "xl:grid-cols-[minmax(0,1fr)_74px]" : "xl:grid-cols-[minmax(0,1fr)_320px]"}`}>
              <div className="min-w-0">
                {!isFullWidthStudioRoute && guideMode === "hidden" && (
                  <div className="mb-3 flex justify-end">
                    <button type="button" onClick={cycleGuideMode} className="atlas-secondary-button" title="Restore ATLAS Guide"><PanelRightOpen size={15} /> Restore ATLAS Guide</button>
                  </div>
                )}
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
                <Suspense
                  fallback={
                    <div className="flex min-h-[360px] items-center justify-center rounded-xl border border-slate-200 bg-white text-sm font-semibold text-slate-600 shadow-sm">
                      Loading governed analytical workspace...
                    </div>
                  }
                >
                <Routes>
                  <Route path="/login" element={<Navigate to="/dashboard" replace />} />
                  <Route path="/register" element={<Navigate to="/dashboard" replace />} />
                  <Route path="/" element={<Navigate to="/dashboard" replace />} />
                  <Route path="/workbench" element={<IntelligentWorkbench />} />
                  <Route path="/project-overview" element={<ProjectOverview />} />
                  <Route path="/management-dashboard" element={<ManagementDashboard />} />
                  <Route path="/admin" element={<AdminConsole />} />
                  <Route path="/sharing" element={<SharingCenter />} />
                  <Route path="/notifications" element={<NotificationCenter />} />
                  <Route path="/monitoring" element={<MonitoringCenter />} />
                  <Route path="/monitoring/:monitoringPlanId" element={<MonitoringPlanDetail />} />
                  <Route path="/project-monitoring/:projectId" element={<MonitoringPlanDetail />} />
                  <Route path="/registry" element={<RegistryPage />} />
                  <Route path="/registry/:projectId" element={<RegistryAssetDetail />} />
                  <Route path="/validation" element={<ValidationQueue />} />
                  <Route path="/validation/:validationId" element={<ValidationCaseDetail />} />
                  <Route path="/project-validation/:projectId" element={<ValidationCaseDetail />} />
                  <Route path="/projects/new" element={<NewProject />} />
                  <Route path="/projects/open" element={<OpenProject />} />
                  <Route path="/templates" element={<WorkflowTemplates />} />
                  <Route path="/datasets" element={<DatasetLibrary />} />
                  <Route path="/visual-intelligence-lab" element={<VisualIntelligenceLab />} />
                  <Route path="/sql-data-studio" element={<SqlDataStudio />} />
                  <Route path="/notebook-studio" element={<NotebookStudio />} />
                  <Route path="/analytics" element={<AnalyticsWorkbench />} />
                  <Route path="/chart-studio" element={<ChartStudio />} />
                  <Route path="/credit-risk-studio" element={<CreditRiskStudio />} />
                  <Route path="/model-evidence-center" element={<EvidenceGraph />} />
                  <Route path="/evidence-graph" element={<Navigate to="/model-evidence-center" replace />} />
                  <Route path="/model-diagnostics" element={<ModelDiagnostics />} />
                  <Route path="/model-document-studio" element={<ModelDocumentationStudio />} />
                  <Route path="/model-document" element={<Navigate to="/model-document-studio" replace />} />
                  <Route path="/model-development-document" element={<Navigate to="/model-document-studio" replace />} />
                  <Route path="/datasets/register" element={<RegisterDataset />} />
                  <Route path="/datasets/:datasetId" element={<DatasetDetail />} />
                  <Route path="/experiments" element={<ExperimentComparison />} />
                  <Route path="/journal" element={<DecisionJournal />} />
                  <Route path="/governance-report" element={<GovernanceReport />} />
                  <Route path="/notebook-export" element={<NotebookExport />} />
                  <Route path="/exports" element={<ExportsPage />} />
                  <Route path="/settings" element={<SettingsPage />} />
                  <Route path="/account" element={<AccountPage />} />
                  <Route path="/admin/users" element={<AdminUsersPage />} />
                  <Route path="/audit" element={<AuditPage />} />
                  <Route path="/system/diagnostics" element={<SystemDiagnostics />} />
                  <Route path="/dashboard" element={<Dashboard />} />
                  <Route path="/step00" element={<Step00ProjectContext />} />
                  <Route path="/step01" element={<Step01DataAcquisition />} />
                  <Route path="/step01b" element={<Navigate to="/step01?section=credit-bureau-review" replace />} />
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
                </Suspense>
              </div>
              {!isFullWidthStudioRoute && guideMode !== "hidden" && (
                guideMode === "full" ? (
                  <aside className="relative min-w-0">
                    <button type="button" onClick={cycleGuideMode} title="Compact ATLAS Guide" className="absolute right-2 top-2 z-10 rounded-lg border border-slate-200 bg-white p-1.5 text-slate-600 shadow-sm hover:bg-slate-50"><PanelRightClose size={15} /></button>
                    <CopilotCard />
                  </aside>
                ) : (
                  <aside className="flex min-h-[120px] flex-col items-center gap-3 rounded-xl border border-slate-200 bg-white py-3 shadow-sm">
                    <button type="button" onClick={cycleGuideMode} title={guideMode === "compact" ? "Hide ATLAS Guide" : "Restore ATLAS Guide"} className="rounded-lg border border-slate-200 bg-slate-50 p-2 text-slate-700 hover:bg-white">{guideMode === "compact" ? <PanelRightClose size={16} /> : <PanelRightOpen size={16} />}</button>
                    {guideMode === "compact" && <><Sparkles size={18} className="text-blue-600" /><span className="text-[10px] font-semibold uppercase tracking-wide text-slate-500 [writing-mode:vertical-rl]">Guide ready</span></>}
                  </aside>
                )
              )}
            </div>
          </main>
        </div>
      </div>
    </div>
  );
}

function HeaderUserMenu({ user, onLogout }: { user: AtlasUser | null; onLogout: () => Promise<void> }) {
  const [open, setOpen] = useState(false);
  const [unread, setUnread] = useState(0);
  useEffect(() => {
    if (!user) return;
    let cancelled = false;
    getUnreadNotificationCount().then((payload) => {
      if (!cancelled) setUnread(payload.count);
    }).catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [user]);
  if (!user) {
    return (
      <Link to="/login" className="rounded-full border border-slate-200 bg-white px-2.5 py-1 text-[11px] font-semibold text-slate-700 hover:bg-slate-50">
        Sign In
      </Link>
    );
  }
  return (
    <div className="relative">
      <Link
        to="/notifications"
        className="mr-2 inline-flex items-center gap-1 rounded-full border border-slate-200 bg-white px-2.5 py-1 text-[11px] font-semibold text-slate-800 shadow-sm hover:bg-slate-50"
        title="Notification Center"
      >
        Notifications
        {unread > 0 && <span className="rounded-full bg-blue-600 px-1.5 py-0.5 text-[10px] text-white">{unread}</span>}
      </Link>
      <button
        type="button"
        onClick={() => setOpen((current) => !current)}
        className="rounded-full border border-slate-200 bg-white px-2.5 py-1 text-[11px] font-semibold text-slate-800 shadow-sm hover:bg-slate-50"
        title={`Signed in as ${user.displayName}`}
      >
        {user.displayName}
      </button>
      {open && (
        <div className="absolute right-0 z-40 mt-2 w-56 rounded-xl border border-slate-200 bg-white p-2 text-sm shadow-lg">
          <div className="border-b border-slate-100 px-3 py-2">
            <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Signed in as</div>
            <div className="mt-1 truncate font-semibold text-slate-950">{user.displayName}</div>
            <div className="truncate text-xs text-slate-500">{user.email}</div>
          </div>
          <Link to="/account" onClick={() => setOpen(false)} className="mt-2 block rounded-lg px-3 py-2 font-semibold text-slate-700 hover:bg-slate-50">
            Account
          </Link>
          <button
            type="button"
            onClick={async () => {
              setOpen(false);
              await onLogout();
            }}
            className="block w-full rounded-lg px-3 py-2 text-left font-semibold text-red-700 hover:bg-red-50"
          >
            Sign out
          </button>
        </div>
      )}
    </div>
  );
}
