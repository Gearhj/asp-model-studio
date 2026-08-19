import { lazy, Suspense, useEffect, useMemo, useState, type ReactNode } from "react";
import { Link, Navigate, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { ChevronDown, LogOut, Settings2, ShieldCheck, UserCircle } from "lucide-react";
import BrandLogo from "../components/BrandLogo";
import ErrorBoundary from "../components/ErrorBoundary";
import ProjectSaveStatus from "../components/ProjectSaveStatus";
import Sidebar from "../components/Sidebar";
import { AccountPage, AdminUsersPage, LoginPage } from "../steps/AuthPages";
import { logout, me } from "../lib/auth";
import { loginPathForReturnTo } from "../lib/authReturnPath";
import { setCachedUserId } from "../lib/authSession";
import type { AtlasUser } from "../lib/datasetLibrary";
import { useWorkflowStore } from "../state/useWorkflowStore";
import StudioHome from "../sports/StudioHome";
import WorkflowLibrary from "../sports/WorkflowLibrary";
import ForecastWorkflow from "../sports/ForecastWorkflow";
import NewSportsProject from "../sports/NewSportsProject";
import SportsProjects from "../sports/SportsProjects";
import SportsProjectOverview from "../sports/SportsProjectOverview";
import {
  AdministrationPage,
  DataSourcesRightsPage,
  DataWarehousePage,
  EvaluationCalibrationPage,
  ForwardMonitoringPage,
  LegacyWorkflowUnavailablePage,
  ModelGraphPage,
  ModelLaboratoryPage,
  ParticipationUsagePage,
  PlayerTeamStatePage,
  RegistryDeploymentPage,
  ResearchToolsPage,
  SimulationStudioPage,
  UsersSettingsPage,
} from "../sports/StudioModules";
import { isSportsWorkflow, sportsWorkflowForId } from "../sports/sportsConfig";

const PaModelingCockpit = lazy(() => import("../sports/cockpit/PaModelingCockpit"));
const AnalyticsWorkbench = lazy(() => import("../steps/AnalyticsWorkbench"));
const SqlDataStudio = lazy(() => import("../steps/SqlDataStudio"));
const ChartStudio = lazy(() => import("../steps/ChartStudio"));
const ModelDocumentationStudio = lazy(() => import("../steps/ModelDocumentationStudio"));

const LEGACY_ROUTES = [
  "/credit-risk-studio",
  "/management-dashboard",
  "/validation",
  "/validation/:validationId",
  "/sharing",
  "/audit",
  "/governance-report",
  "/journal",
  "/step00",
  "/step01",
  "/step01b",
  "/step02",
  "/step03",
  "/step04",
  "/step05",
  "/step06",
  "/step07",
  "/step08",
  "/step09",
  "/step10",
  "/step11",
  "/step12",
  "/step13",
  "/projects/:projectId/step00",
  "/projects/:projectId/step01",
  "/projects/:projectId/step02",
  "/projects/:projectId/step03",
  "/projects/:projectId/step04",
  "/projects/:projectId/step05",
  "/projects/:projectId/step06",
  "/projects/:projectId/step07",
  "/projects/:projectId/step08",
  "/projects/:projectId/step09",
  "/projects/:projectId/step10",
  "/projects/:projectId/step11",
  "/projects/:projectId/step12",
  "/projects/:projectId/step13",
];

const ROUTE_LABELS: Array<[string, string]> = [
  ["/project-overview", "Project Overview"],
  ["/projects/new", "Create Sports Project"],
  ["/projects/open", "Sports Projects"],
  ["/templates", "Sport Workflow Library"],
  ["/workflows/mlb", "MLB Forecasting"],
  ["/workflows/nfl", "NFL Forecasting"],
  ["/data-warehouse", "Data Warehouse"],
  ["/model-laboratory", "Model Laboratory"],
  ["/simulation-studio", "Simulation Studio"],
  ["/evaluation-calibration", "Evaluation & Calibration"],
  ["/model-graph", "Model Graph"],
  ["/registry-deployment", "Registry & Deployment"],
  ["/forward-monitoring", "Forward Monitoring"],
  ["/research-tools", "Research Tools"],
  ["/analytics", "Analytics Workbench"],
  ["/sql-lab", "SQL Lab"],
  ["/visualization-studio", "Visualization Studio"],
  ["/model-documentation", "Model Documentation"],
  ["/data-sources-rights", "Data Sources & Rights"],
  ["/users-settings", "Users & Settings"],
  ["/admin", "Administration"],
  ["/account", "Account"],
  ["/dashboard", "Studio Home"],
];

function pageLabel(pathname: string) {
  const routeLabel = ROUTE_LABELS.find(([route]) => pathname === route || pathname.startsWith(`${route}/`))?.[1];
  if (routeLabel) return routeLabel;
  if (
    LEGACY_ROUTES.includes(pathname)
    || pathname.startsWith("/workflow/")
    || pathname.startsWith("/validation/")
    || /^\/projects\/[^/]+\/step\d+$/.test(pathname)
  ) return "Legacy Workflow Unavailable";
  return "Studio Home";
}

export default function ModelingApp() {
  const location = useLocation();
  const navigate = useNavigate();
  const [authChecked, setAuthChecked] = useState(false);
  const [authUser, setAuthUser] = useState<AtlasUser | null>(null);
  const projectName = useWorkflowStore((state) => state.projectName);
  const workflowId = useWorkflowStore((state) => state.workflowId);
  const page = useMemo(() => pageLabel(location.pathname), [location.pathname]);
  const inSportsProject = isSportsWorkflow(workflowId) && projectName !== "Untitled Sports Project";

  useEffect(() => {
    let cancelled = false;
    me()
      .then((payload) => {
        if (cancelled) return;
        setCachedUserId(payload.user.userId);
        setAuthUser(payload.user);
      })
      .catch(() => {
        if (!cancelled) setAuthUser(null);
      })
      .finally(() => {
        if (!cancelled) setAuthChecked(true);
      });
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    document.title = `${page} | ASP Model Studio`;
  }, [page]);

  if (!authChecked) {
    return (
      <div className="grid min-h-screen place-items-center bg-slate-950 px-6 text-white">
        <div className="text-center">
          <BrandLogo size="lg" variant="dark" showSubtitle />
          <div className="mx-auto mt-8 h-1.5 w-48 overflow-hidden rounded-full bg-white/10"><span className="sports-flow-line block h-full w-full" /></div>
          <p className="mt-4 text-sm font-medium text-slate-400">Loading secure sports modeling workspace…</p>
        </div>
      </div>
    );
  }

  if (!authUser) {
    const loginPath = loginPathForReturnTo(location.pathname, location.search, location.hash);
    return (
      <div className="min-h-screen bg-slate-100 p-3 sm:p-6 lg:p-8">
        <Routes>
          <Route path="/login" element={<LoginPage onAuthenticated={(user) => { setCachedUserId(user.userId); setAuthUser(user); }} />} />
          <Route path="/register" element={<Navigate to="/login" replace />} />
          <Route path="*" element={<Navigate to={loginPath} replace />} />
        </Routes>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-[#f3f6f8] text-slate-950">
      <div className="flex min-h-screen">
        <Sidebar />
        <div className="flex min-w-0 flex-1 flex-col pt-16 lg:pt-0">
          <header className="sticky top-16 z-30 border-b border-slate-200/90 bg-white/90 shadow-[0_1px_0_rgba(15,23,42,.04)] backdrop-blur-xl lg:top-0">
            <div className="flex min-h-[68px] items-center justify-between gap-4 px-4 py-3 sm:px-6 xl:px-8">
              <div className="min-w-0">
                <nav className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.12em] text-slate-400" aria-label="Breadcrumb">
                  <Link to="/dashboard" className="hover:text-teal-700">ASP Model Studio</Link>
                  {inSportsProject && location.pathname !== "/dashboard" && <><span>/</span><span className="max-w-48 truncate">{projectName}</span></>}
                </nav>
                <div className="mt-1 truncate text-lg font-semibold tracking-tight text-slate-950 sm:text-xl">{page}</div>
              </div>
              <div className="flex shrink-0 items-center gap-2 sm:gap-3">
                {(location.pathname === "/project-overview" || location.pathname.startsWith("/workflows/")) && <div className="hidden sm:block"><ProjectSaveStatus /></div>}
                <HeaderUserMenu
                  user={authUser}
                  onLogout={async () => {
                    await logout();
                    useWorkflowStore.getState().reset();
                    setCachedUserId(null);
                    setAuthUser(null);
                    navigate("/login", { replace: true });
                  }}
                />
              </div>
            </div>
          </header>

          <main className="min-w-0 flex-1 px-3 py-4 sm:px-5 sm:py-6 xl:px-8">
            <div className="mx-auto w-full max-w-[1880px]">
              <ErrorBoundary title="This sports modeling surface could not be rendered safely." resetKey={location.pathname}>
                <Routes>
                  <Route path="/" element={<Navigate to="/dashboard" replace />} />
                  <Route path="/login" element={<Navigate to="/dashboard" replace />} />
                  <Route path="/register" element={<Navigate to="/dashboard" replace />} />
                  <Route path="/dashboard" element={<StudioHome />} />
                  <Route path="/projects" element={<Navigate to="/projects/open" replace />} />
                  <Route path="/projects/open" element={<SportsProjects />} />
                  <Route path="/projects/new" element={<NewSportsProject />} />
                  <Route path="/project-overview" element={<SportsProjectOverview />} />
                  <Route path="/templates" element={<WorkflowLibrary />} />
                  <Route path="/workflows" element={<Navigate to="/templates" replace />} />
                  <Route path="/workflows/mlb" element={<ForecastWorkflow workflowKey="mlb" />} />
                  <Route path="/workflows/nfl" element={<ForecastWorkflow workflowKey="nfl" />} />
                  <Route path="/data-warehouse" element={<DataWarehousePage />} />
                  <Route path="/datasets" element={<Navigate to="/data-warehouse" replace />} />
                  <Route path="/datasets/*" element={<Navigate to="/data-warehouse" replace />} />
                  <Route path="/player-team-state" element={<PlayerTeamStatePage />} />
                  <Route path="/participation-usage" element={<ParticipationUsagePage />} />
                  <Route path="/model-laboratory" element={<ModelLaboratoryPage />} />
                  <Route path="/pa-modeling-cockpit" element={<RetainedToolRoute label="MLB PA Modeling Cockpit"><PaModelingCockpit /></RetainedToolRoute>} />
                  <Route path="/modeling-cockpit" element={<Navigate to="/pa-modeling-cockpit" replace />} />
                  <Route path="/experiments" element={<Navigate to="/model-laboratory" replace />} />
                  <Route path="/simulation-studio" element={<SimulationStudioPage />} />
                  <Route path="/evaluation-calibration" element={<EvaluationCalibrationPage />} />
                  <Route path="/model-diagnostics" element={<Navigate to="/evaluation-calibration" replace />} />
                  <Route path="/model-graph" element={<ModelGraphPage />} />
                  <Route path="/model-evidence-center" element={<Navigate to="/model-graph" replace />} />
                  <Route path="/evidence-graph" element={<Navigate to="/model-graph" replace />} />
                  <Route path="/registry-deployment" element={<RegistryDeploymentPage />} />
                  <Route path="/registry" element={<Navigate to="/registry-deployment" replace />} />
                  <Route path="/registry/*" element={<Navigate to="/registry-deployment" replace />} />
                  <Route path="/exports" element={<Navigate to="/registry-deployment" replace />} />
                  <Route path="/forward-monitoring" element={<ForwardMonitoringPage />} />
                  <Route path="/monitoring" element={<Navigate to="/forward-monitoring" replace />} />
                  <Route path="/monitoring/*" element={<Navigate to="/forward-monitoring" replace />} />
                  <Route path="/research-tools" element={<ResearchToolsPage />} />
                  <Route path="/analytics" element={<RetainedToolRoute label="Analytics Workbench"><AnalyticsWorkbench /></RetainedToolRoute>} />
                  <Route path="/workbench" element={<Navigate to="/analytics" replace />} />
                  <Route path="/sql-lab" element={<RetainedToolRoute label="SQL Lab"><SqlDataStudio /></RetainedToolRoute>} />
                  <Route path="/sql-data-studio" element={<Navigate to="/sql-lab" replace />} />
                  <Route path="/visualization-studio" element={<RetainedToolRoute label="Visualization Studio"><ChartStudio /></RetainedToolRoute>} />
                  <Route path="/chart-studio" element={<Navigate to="/visualization-studio" replace />} />
                  <Route path="/model-documentation" element={<RetainedToolRoute label="Model Documentation"><ModelDocumentationStudio /></RetainedToolRoute>} />
                  <Route path="/model-document-studio" element={<Navigate to="/model-documentation" replace />} />
                  <Route path="/model-development-document" element={<Navigate to="/model-documentation" replace />} />
                  <Route path="/notebook-studio" element={<Navigate to="/research-tools" replace />} />
                  <Route path="/notebook-export" element={<Navigate to="/research-tools" replace />} />
                  <Route path="/data-sources-rights" element={<DataSourcesRightsPage />} />
                  <Route path="/admin" element={<AdministrationPage />} />
                  <Route path="/users-settings" element={<UsersSettingsPage />} />
                  <Route path="/settings" element={<Navigate to="/users-settings" replace />} />
                  <Route path="/account" element={<AccountPage />} />
                  <Route path="/admin/users" element={<AdminUsersPage />} />
                  <Route path="/workflow/*" element={<LegacyWorkflowUnavailablePage />} />
                  {LEGACY_ROUTES.map((path) => <Route key={path} path={path} element={<LegacyWorkflowUnavailablePage />} />)}
                  <Route path="*" element={<Navigate to="/dashboard" replace />} />
                </Routes>
              </ErrorBoundary>
            </div>
          </main>
        </div>
      </div>
    </div>
  );
}

function RetainedToolRoute({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="asp-retained-tool min-w-0">
      <Suspense fallback={(
        <section className="grid min-h-[52vh] place-items-center rounded-2xl border border-slate-200 bg-white p-8 text-center shadow-sm">
          <div>
            <div className="mx-auto h-1.5 w-44 overflow-hidden rounded-full bg-slate-100"><span className="sports-flow-line block h-full w-full" /></div>
            <p className="mt-4 text-sm font-semibold text-slate-600">Loading {label}&hellip;</p>
          </div>
        </section>
      )}>
        {children}
      </Suspense>
    </div>
  );
}

function HeaderUserMenu({ user, onLogout }: { user: AtlasUser; onLogout: () => Promise<void> }) {
  const [open, setOpen] = useState(false);
  const initials = user.displayName.split(/\s+/).map((part) => part[0]).join("").slice(0, 2).toUpperCase();
  return (
    <div className="relative">
      <button type="button" onClick={() => setOpen((current) => !current)} className="flex min-h-10 items-center gap-2 rounded-xl border border-slate-200 bg-white px-2.5 py-1.5 text-sm font-semibold text-slate-800 shadow-sm hover:border-slate-300" aria-expanded={open}>
        <span className="grid h-7 w-7 place-items-center rounded-lg bg-slate-950 text-xs text-cyan-200">{initials || "AS"}</span>
        <span className="hidden max-w-48 truncate sm:block md:max-w-56 xl:max-w-72">{user.displayName}</span>
        <ChevronDown size={15} className="text-slate-400" />
      </button>
      {open && (
        <div className="absolute right-0 z-50 mt-2 w-64 overflow-hidden rounded-xl border border-slate-200 bg-white shadow-2xl">
          <div className="border-b border-slate-100 px-4 py-3">
            <div className="truncate font-semibold text-slate-950">{user.displayName}</div>
            <div className="mt-0.5 truncate text-xs text-slate-500">{user.email}</div>
          </div>
          <div className="p-2 text-sm">
            <Link to="/account" onClick={() => setOpen(false)} className="flex items-center gap-2 rounded-lg px-3 py-2 font-medium text-slate-700 hover:bg-slate-50"><UserCircle size={16} /> Account</Link>
            <Link to="/users-settings" onClick={() => setOpen(false)} className="flex items-center gap-2 rounded-lg px-3 py-2 font-medium text-slate-700 hover:bg-slate-50"><Settings2 size={16} /> Users & Settings</Link>
            {String(user.role).toLowerCase() === "admin" && <Link to="/admin/users" onClick={() => setOpen(false)} className="flex items-center gap-2 rounded-lg px-3 py-2 font-medium text-slate-700 hover:bg-slate-50"><ShieldCheck size={16} /> User Administration</Link>}
            <button type="button" onClick={async () => { setOpen(false); await onLogout(); }} className="mt-1 flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left font-semibold text-red-700 hover:bg-red-50"><LogOut size={16} /> Sign out</button>
          </div>
        </div>
      )}
    </div>
  );
}
