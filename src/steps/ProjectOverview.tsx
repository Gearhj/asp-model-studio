import { Link } from "react-router-dom";
import type React from "react";
import { useEffect, useState } from "react";
import { ArrowRight, BookOpenCheck, Database, FileClock, FlaskConical, Gauge, Share2 } from "lucide-react";
import AtlasCard from "../components/ui/AtlasCard";
import AtlasDisclosure from "../components/ui/AtlasDisclosure";
import AtlasMetricCard from "../components/ui/AtlasMetricCard";
import AtlasPageHero from "../components/ui/AtlasPageHero";
import AtlasProgressBar from "../components/ui/AtlasProgressBar";
import AtlasStatusBadge from "../components/ui/AtlasStatusBadge";
import AtlasTabs from "../components/ui/AtlasTabs";
import ShareResourceDialog from "../components/sharing/ShareResourceDialog";
import { getWorkflowDefinition } from "../config/workflows";
import { loadDecisionJournal } from "../lib/decisionJournal";
import { listProjectDatasets, type ProjectDatasetLink } from "../lib/datasetLibrary";
import { listAnalyticsInsights, type AtlasAnalyticsInsight } from "../lib/analyticsWorkbench";
import { autoCaptureEvidence, getEvidenceCoverage, type EvidenceCoverage } from "../lib/evidenceGraph";
import { loadExperiments } from "../lib/experimentTracking";
import { loadProjectContext } from "../lib/projectContext";
import { AB_WORKFLOW_DEFAULTS, allocationImbalance, analyzeAbLift, decisionRecommendationReason, getAbWorkflowFullDatasetArtifact } from "../lib/abTestingWorkflow";
import { getCreditRiskProfileForProject, getLatestCreditRiskMlModelForProject, getLatestScorecardForProject, getLatestWoeIvAnalysisForProject, type CreditRiskMlModel, type CreditRiskProfile, type ScorecardModel, type WoeIvAnalysis } from "../lib/creditRiskStudio";
import { useWorkflowStore } from "../state/useWorkflowStore";
import { getProjectPersistenceBundle, type ProjectPersistenceBundle } from "../lib/serverPersistence";
import { summarizePersistedEvidence } from "../lib/persistedEvidenceStatus";
import { getRegistryAsset, getRegistryAssets, type RegistryAssetDetail } from "../lib/registryApi";
import { RegistryStatus, formatRegistryDate } from "../components/registry/RegistryPrimitives";
import { createProjectMonitoringPlan, createMonitoringRun, getProjectMonitoringPlan, monitoringPlanStatusLabels, monitoringRunStatusLabels, monitoringStatusTone, startMonitoringRun, type MonitoringPlanDetail } from "../lib/monitoringApi";
import {
  TRANSPORTATION_EVIDENCE_STAGES,
  deriveOptimizationEvidenceSummary,
  loadTransportationOptimizationSnapshot,
  optimizationImplementationReady,
  optimizationWorkflowStepStatus,
  type TransportationOptimizationSnapshot,
} from "../lib/transportationOptimizationEvidence";

export default function ProjectOverview() {
  const projectName = useWorkflowStore((state) => state.projectName);
  const projectId = useWorkflowStore((state) => state.projectId);
  const projectType = useWorkflowStore((state) => state.projectType);
  const workflowId = useWorkflowStore((state) => state.workflowId);
  const workflowSteps = useWorkflowStore((state) => state.workflowSteps);
  const context = loadProjectContext();
  const decisions = loadDecisionJournal().slice(0, 4);
  const experiments = loadExperiments().slice(0, 4);
  const workflow = getWorkflowDefinition(workflowId);
  const completed = workflowSteps.filter((step) => step.status === "complete").length;
  const current = workflowSteps.find((step) => step.status !== "complete" && step.status !== "skipped");
  const progress = workflowSteps.length ? Math.round((completed / workflowSteps.length) * 100) : 0;
  const modelId = context.modelId || useWorkflowStore.getState().modelId || "Not assigned";
  const cadence = context.monitoringCadence === "custom" ? context.monitoringCadenceCustom || "Custom cadence not documented" : context.monitoringCadence;
  const [activeTab, setActiveTab] = useState("summary");
  const [datasetLinks, setDatasetLinks] = useState<ProjectDatasetLink[]>([]);
  const [analyticsInsights, setAnalyticsInsights] = useState<AtlasAnalyticsInsight[]>([]);
  const [evidenceCoverage, setEvidenceCoverage] = useState<EvidenceCoverage | null>(null);
  const [evidenceMessage, setEvidenceMessage] = useState("");
  const [creditRiskProfile, setCreditRiskProfile] = useState<CreditRiskProfile | null>(null);
  const [woeIvAnalysis, setWoeIvAnalysis] = useState<WoeIvAnalysis | null>(null);
  const [scorecardModel, setScorecardModel] = useState<ScorecardModel | null>(null);
  const [creditRiskMlModel, setCreditRiskMlModel] = useState<CreditRiskMlModel | null>(null);
  const [persistenceBundle, setPersistenceBundle] = useState<ProjectPersistenceBundle | null>(null);
  const [registryDetail, setRegistryDetail] = useState<RegistryAssetDetail | null>(null);
  const [monitoringDetail, setMonitoringDetail] = useState<MonitoringPlanDetail | null>(null);
  const [shareOpen, setShareOpen] = useState(false);
  const localOptimizationSummary = projectType === "optimization" ? loadTransportationOptimizationSnapshot(projectId) : null;
  const backendOptimizationState = projectType === "optimization"
    ? (persistenceBundle?.project?.metadata?.optimizationState ?? null) as TransportationOptimizationSnapshot | null
    : null;
  const optimizationSummary = localOptimizationSummary ?? backendOptimizationState;
  const optimizationEvidence = projectType === "optimization" ? deriveOptimizationEvidenceSummary(optimizationSummary) : null;
  const abArtifact = projectType === "ab-testing" ? getAbWorkflowFullDatasetArtifact(AB_WORKFLOW_DEFAULTS) : null;
  const abSummary = abArtifact?.summary ?? null;
  const abAnalysis = abSummary ? analyzeAbLift(abSummary) : null;
  const abImbalance = abSummary ? allocationImbalance(abSummary) : null;
  const abDecisionRecommendation = abAnalysis && abImbalance ? decisionRecommendationReason(abAnalysis, abImbalance) : "";
  const backendEvidence = persistenceBundle?.evidence ?? [];
  const backendEvidenceSummary = summarizePersistedEvidence(backendEvidence, {
    requiredCount: projectType === "optimization" ? TRANSPORTATION_EVIDENCE_STAGES.length : undefined,
    deduplicateByArtifactType: true,
  });
  const backendEvidenceScore = backendEvidence.length ? backendEvidenceSummary.coverageScore : null;
  const latestDocumentation = persistenceBundle?.documentation?.[0] ?? null;
  const latestSolverRun = persistenceBundle?.runs?.find((run) => run.runType === "optimization_solver") ?? null;
  const latestValidationRun = persistenceBundle?.runs?.find((run) => run.runType === "optimization_validation") ?? null;
  const backendDocumentationReady = latestDocumentation && ["ready", "complete"].includes(String(latestDocumentation.status));
  const evidenceScore = Math.max(backendEvidenceScore ?? 0, optimizationEvidence?.coverageScore ?? 0, evidenceCoverage?.coverageScore ?? 0);
  const documentationStatus = backendDocumentationReady
    ? latestDocumentation.status === "complete" ? "Complete" : "Ready for review"
    : optimizationEvidence
    ? optimizationEvidence.packageApproved
      ? "Audit package ready"
      : optimizationEvidence.documentationReady
        ? "Documentation ready"
        : optimizationEvidence.documentationSectionCount
          ? `${optimizationEvidence.documentationSectionCount} of 20 sections populated`
          : "Documentation not started"
    : evidenceScore >= 80 ? "Ready for review" : evidenceScore > 0 ? "Evidence incomplete" : "Structure available";
  const backendCompletedSteps = Array.isArray(persistenceBundle?.workflowState?.completedSteps)
    ? persistenceBundle?.workflowState?.completedSteps.length ?? 0
    : 0;
  const displayedCompleted = Math.max(completed, backendCompletedSteps);
  const displayedProgress = workflowSteps.length ? Math.round((displayedCompleted / workflowSteps.length) * 100) : progress;
  const solverMetrics = latestSolverRun?.metrics ?? {};
  const validationMetrics = latestValidationRun?.metrics ?? {};

  useEffect(() => {
    let alive = true;
    Promise.all([
      listProjectDatasets(projectId),
      listAnalyticsInsights({ projectId }).then((payload) => payload.insights).catch(() => []),
      getEvidenceCoverage(projectId).catch(() => null),
      getCreditRiskProfileForProject(projectId).catch(() => null),
      getLatestWoeIvAnalysisForProject(projectId).catch(() => null),
      getLatestScorecardForProject(projectId).catch(() => null),
      getLatestCreditRiskMlModelForProject(projectId).catch(() => null),
      getProjectPersistenceBundle(projectId).catch(() => null),
      getRegistryAsset(projectId).catch(async () => {
        const payload = await getRegistryAssets({ search: projectName, limit: 25 });
        const normalizedName = projectName.trim().toLowerCase();
        const match = payload.assets.find((asset) => asset.name.trim().toLowerCase() === normalizedName);
        return match ? getRegistryAsset(match.project_id) : null;
      }).catch(() => null),
      getProjectMonitoringPlan(projectId).catch(() => null),
    ]).then((links) => {
      if (!alive) return;
      setDatasetLinks(links[0]);
      setAnalyticsInsights(links[1]);
      setEvidenceCoverage(links[2]);
      setCreditRiskProfile(links[3]);
      setWoeIvAnalysis(links[4]);
      setScorecardModel(links[5]);
      setCreditRiskMlModel(links[6]);
      setPersistenceBundle(links[7]);
      setRegistryDetail(links[8]);
      setMonitoringDetail(links[9]);
    }).catch(() => {
      if (!alive) return;
      setDatasetLinks([]);
      setAnalyticsInsights([]);
      setEvidenceCoverage(null);
      setCreditRiskProfile(null);
      setWoeIvAnalysis(null);
      setScorecardModel(null);
      setCreditRiskMlModel(null);
      setPersistenceBundle(null);
      setRegistryDetail(null);
      setMonitoringDetail(null);
    });
    return () => {
      alive = false;
    };
  }, [projectId, projectName]);

  async function captureProjectEvidence() {
    try {
      const captured = await autoCaptureEvidence({ projectId, projectName });
      setEvidenceMessage(`Captured or refreshed ${captured.length} evidence item(s).`);
      setEvidenceCoverage(await getEvidenceCoverage(projectId));
    } catch (error) {
      setEvidenceMessage(error instanceof Error ? error.message : "ATLAS could not capture project evidence.");
    }
  }

  const tabs = [
    {
      id: "summary",
      label: "Summary",
      panel: (
        <div className={`grid gap-5 ${projectType === "optimization" ? "" : "xl:grid-cols-[minmax(0,1fr)_380px]"}`}>
          {registryDetail?.asset && (
            <AtlasCard
              className="xl:col-span-full"
              title="Registry Status"
              eyebrow="Enterprise analytical asset"
              action={<Link to={`/registry/${encodeURIComponent(registryDetail.asset.project_id)}`} className="atlas-tertiary-button">Open registry detail <ArrowRight size={15} /></Link>}
            >
              <div className="grid gap-x-6 sm:grid-cols-2 lg:grid-cols-4 xl:grid-cols-8">
                <RegistryFact label="Lifecycle" value={<RegistryStatus value={registryDetail.asset.lifecycle_status} />} />
                <RegistryFact label="Evidence" value={<><RegistryStatus value={registryDetail.asset.evidence_status} /><span className="ml-2 text-xs text-slate-500">{registryDetail.asset.evidence_readiness_percent}%</span></>} />
                <RegistryFact label="Documentation" value={<><RegistryStatus value={registryDetail.asset.documentation_status} /><span className="ml-2 text-xs text-slate-500">{registryDetail.asset.documentation_readiness_percent}%</span></>} />
                <RegistryFact label="Validation" value={<><RegistryStatus value={registryDetail.asset.validation_status} />{registryDetail.asset.validation_score !== null && <span className="ml-2 text-xs text-slate-500">{registryDetail.asset.validation_score}%</span>}</>} />
                <RegistryFact label="Recommendation" value={<RegistryStatus value={registryDetail.asset.recommendation_status} />} />
                <RegistryFact label="Implementation" value={<RegistryStatus value={registryDetail.asset.implementation_status} />} />
                <RegistryFact label="Open actions" value={registryDetail.asset.open_action_count} />
                <RegistryFact label="Last activity" value={formatRegistryDate(registryDetail.asset.last_activity_at, true)} />
              </div>
              <div className="mt-4 flex flex-wrap gap-2 border-t border-slate-200 pt-4">
                <Link to={`/project-validation/${encodeURIComponent(registryDetail.asset.project_id)}`} className="atlas-primary-button">
                  {registryDetail.asset.validation_status === "Not submitted" ? "Submit for Validation" : "Open Validation Case"}
                </Link>
                <Link to="/validation" className="atlas-secondary-button">Open Validation Queue</Link>
              </div>
            </AtlasCard>
          )}
          <MonitoringOverviewCard
            projectId={projectId}
            projectName={projectName}
            workflowType={workflowId || projectType}
            detail={monitoringDetail}
            onChanged={setMonitoringDetail}
          />
          <AtlasCard title="Next Recommended Action" eyebrow="Project health">
            <div className="rounded-2xl border border-blue-200 bg-blue-50 p-5">
              <div className="text-xl font-semibold text-blue-950">{current?.label ?? (projectType === "optimization" && optimizationEvidence?.packageReady ? "Optimization study complete" : "Workflow complete")}</div>
              <p className="mt-2 text-sm leading-6 text-blue-900">{current?.description ?? (projectType === "optimization" ? optimizationEvidence?.statusLabel : workflow.description)}</p>
              {current && <Link to={current.route} className="atlas-primary-button mt-4">Continue workflow</Link>}
            </div>
            <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
              <AtlasMetricCard label="Workflow completion" value={`${displayedProgress}%`} detail={`${displayedCompleted} of ${workflowSteps.length} steps complete`} tone={displayedProgress >= 80 ? "success" : "info"} />
              <AtlasMetricCard label="Evidence coverage" value={`${evidenceScore}%`} detail={documentationStatus} tone={evidenceScore >= 80 ? "success" : evidenceScore > 0 ? "warning" : "neutral"} />
              <AtlasMetricCard label="Linked datasets" value={datasetLinks.length} tone={datasetLinks.length ? "success" : "neutral"} />
              <AtlasMetricCard label="Recent decisions" value={Math.max(decisions.length, persistenceBundle?.decisions?.length ?? 0)} />
              <AtlasMetricCard label="Recent experiments" value={experiments.length} />
              <AtlasMetricCard label="Documentation" value={documentationStatus} tone={evidenceScore >= 80 ? "success" : "warning"} />
            </div>
            {(context.businessObjective || context.intendedModelUse) && (
              <div className="atlas-inset-section mt-4">
                <div className="text-sm font-semibold text-slate-950">Business context</div>
                <p className="mt-1 text-sm leading-6 text-slate-600">{context.businessObjective || context.intendedModelUse}</p>
              </div>
            )}
          </AtlasCard>

          <AtlasCard
            title="Access & Sharing"
            eyebrow="Governed collaboration"
            action={<button type="button" className="atlas-primary-button" onClick={() => setShareOpen(true)}><Share2 size={15} /> Share Project</button>}
          >
            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
              <SmallStat label="Owner" value={registryDetail?.asset.owner_display_name || context.implementationOwner || "Current ATLAS owner"} />
              <SmallStat label="Shared users/groups" value={registryDetail ? String((registryDetail.audit_trail || []).filter((event) => String(event.action_type).includes("share")).length) : "Open share dialog"} />
              <SmallStat label="Your permission" value="Owner or assigned access" />
              <SmallStat label="Access history" value="Audit Log" />
            </div>
            <p className="mt-3 text-sm leading-6 text-slate-600">Project access is persisted through resource permissions and recorded in the audit log. Owners and admins can manage access from the share dialog.</p>
          </AtlasCard>

          <div className="grid gap-5">
            {projectType === "optimization" && (
              <AtlasCard title="Transportation Optimization Management Summary" eyebrow="Decision control center">
                <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
                  <SmallStat label="Project ID" value={projectId} />
                  <SmallStat label="Project Name" value={projectName || context.projectName || "Optimization Project"} />
                  <SmallStat label="Template" value="Transportation / Logistics" />
                  <SmallStat label="Solver" value={optimizationSummary?.method?.includes("Linear") ? "Linear programming" : optimizationSummary?.method || "Not configured"} />
                  <SmallStat label="Objective" value={optimizationSummary?.objectiveName || "Minimize total logistics cost"} />
                  <SmallStat label="Total Cost" value={optimizationSummary?.result?.totalCost == null && solverMetrics.total_cost == null ? "Not available" : Number(optimizationSummary?.result?.totalCost ?? solverMetrics.total_cost).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })} />
                  <SmallStat label="Demand Fulfilled" value={optimizationSummary?.result?.demandFulfilled == null && solverMetrics.demand_fulfilled == null ? "Not available" : `${Number(optimizationSummary?.result?.demandFulfilled ?? solverMetrics.demand_fulfilled).toLocaleString()} / ${Number(optimizationSummary?.result?.totalDemand ?? solverMetrics.total_demand ?? optimizationSummary?.formulation?.metrics.totalDemand ?? 0).toLocaleString()}`} />
                  <SmallStat label="Unmet Demand" value={optimizationSummary?.result?.unmetDemand == null && solverMetrics.unmet_demand == null ? "Not available" : Number(optimizationSummary?.result?.unmetDemand ?? solverMetrics.unmet_demand).toLocaleString()} />
                  <SmallStat label="Active Routes" value={optimizationSummary?.result ? `${optimizationSummary.result.activeRoutes} / ${optimizationSummary.result.totalRoutes}` : "Not available"} />
                  <SmallStat label="Route Variables" value={optimizationSummary?.formulation?.metrics.decisionVariableCount ?? 0} />
                  <SmallStat label="Demand Constraints" value={optimizationSummary?.formulation?.metrics.demandConstraintCount ?? 0} />
                  <SmallStat label="Supply Constraints" value={optimizationSummary?.formulation?.metrics.supplyConstraintCount ?? 0} />
                  <SmallStat label="Transport Capacity Constraints" value={optimizationSummary?.formulation?.metrics.transportConstraintCount ?? 0} />
                  <SmallStat label="Scenario Coverage" value={`${optimizationSummary?.scenarioAnalysis?.scenarioCount ?? 0} scenarios`} />
                  <SmallStat label="Infeasible Stress Case" value={optimizationSummary?.scenarioAnalysis?.results.find((row) => !row.businessValid)?.scenarioName || "None identified"} />
                  <SmallStat label="Validation Score" value={optimizationSummary?.validation || validationMetrics.validation_score != null ? `${optimizationSummary?.validation?.score ?? validationMetrics.validation_score}%` : "Not run"} />
                  <SmallStat label="Recommendation" value={optimizationSummary?.recommendationStatus || "Draft"} />
                  <SmallStat label="Implementation" value={optimizationImplementationReady(optimizationSummary) ? "Plan complete" : "Incomplete"} />
                  <SmallStat label="Evidence Package" value={evidenceScore >= 100 ? "Ready" : backendEvidence.length ? backendEvidenceSummary.statusLabel : optimizationEvidence?.statusLabel || "Evidence not yet captured"} />
                  <SmallStat label="Documentation" value={backendDocumentationReady || optimizationEvidence?.documentationReady ? "Ready" : documentationStatus} />
                  <SmallStat label="Business Validity" value={optimizationSummary?.result?.success || solverMetrics.business_validity === "valid" ? "Business-valid" : "Pending"} />
                </div>
                <div className={`mt-3 rounded-xl border px-3 py-2 text-xs leading-5 ${optimizationSummary?.result?.success ? "border-emerald-200 bg-emerald-50 text-emerald-900" : "border-amber-200 bg-amber-50 text-amber-900"}`}>
                  <div className="font-semibold">Decision readiness</div>
                  <div>{optimizationSummary?.result?.success || solverMetrics.business_validity === "valid" ? (optimizationSummary?.recommendation || "The persisted transportation allocation is business-valid; review the recommendation and implementation approval.") : "No business-valid transportation solution has been saved. Solver output is not presented as an approved decision."}</div>
                </div>
                <div className="mt-3 grid gap-2">
                  <Link to="/workflow/optimization/1" className="atlas-secondary-button justify-center">Open Optimization Workflow</Link>
                  <Link to={evidenceScore >= 100 ? "/model-evidence-center" : "/workflow/optimization/14"} className="atlas-primary-button justify-center">{evidenceScore >= 100 ? "Open Evidence Package" : "Capture Optimization Evidence"}</Link>
                </div>
              </AtlasCard>
            )}
            {abSummary && abAnalysis && abImbalance && (
              <AtlasCard title="A/B Testing Summary" eyebrow="Experiment control">
                <div className="grid gap-2 sm:grid-cols-2">
                  <SmallStat label="Treatment Sample Size" value={abSummary.treatmentCount.toLocaleString()} />
                  <SmallStat label="Control Sample Size" value={abSummary.controlCount.toLocaleString()} />
                  <SmallStat label="Treatment Conversion Rate" value={`${(abAnalysis.treatmentConversionRate * 100).toFixed(2)}%`} />
                  <SmallStat label="Control Conversion Rate" value={`${(abAnalysis.controlConversionRate * 100).toFixed(2)}%`} />
                  <SmallStat label="Absolute Lift" value={`${(abAnalysis.absoluteLift * 100).toFixed(2)} pp`} />
                  <SmallStat label="P-value" value={abAnalysis.pValue.toFixed(4)} />
                </div>
                <div className={`mt-3 rounded-xl border px-3 py-2 text-xs leading-5 ${abImbalance.warning ? "border-amber-200 bg-amber-50 text-amber-900" : "border-emerald-200 bg-emerald-50 text-emerald-900"}`}>
                  <div className="font-semibold">Decision recommendation</div>
                  <div>{abDecisionRecommendation}</div>
                  <div className="mt-1">Allocation review: {abImbalance.message}</div>
                </div>
                <AtlasDisclosure title="View experiment details" summary="Mapping, lift, and evidence readiness detail.">
                  <div className="grid gap-2 sm:grid-cols-2">
                    <SmallStat label="Experiment Name" value={projectName || context.projectName || "A/B Testing Experiment"} />
                    <SmallStat label="Dataset" value={AB_WORKFLOW_DEFAULTS.dataset} />
                    <SmallStat label="Unit ID" value={AB_WORKFLOW_DEFAULTS.unitIdColumn} />
                    <SmallStat label="Treatment" value={AB_WORKFLOW_DEFAULTS.treatmentValue} />
                    <SmallStat label="Control" value={AB_WORKFLOW_DEFAULTS.controlValue} />
                    <SmallStat label="Relative Lift" value={`${(abAnalysis.relativeLift * 100).toFixed(2)}%`} />
                    <SmallStat label="Evidence Readiness" value={`${evidenceScore}%`} />
                  </div>
                </AtlasDisclosure>
                <div className="mt-3 grid gap-2">
                  <Link to="/workflow/ab-testing/1" className="atlas-secondary-button justify-center">Open A/B Workflow</Link>
                  <Link to="/model-evidence-center" className="atlas-secondary-button justify-center">Open Model Evidence Center</Link>
                </div>
              </AtlasCard>
            )}

            {creditRiskProfile && (
              <AtlasCard title="Credit Risk Profile" eyebrow="Credit Risk Studio wrapper readiness">
                <div className="grid gap-2">
                  {creditRiskWrapperReadiness(creditRiskProfile, workflowSteps, woeIvAnalysis, scorecardModel, creditRiskMlModel, evidenceCoverage).slice(0, 4).map((item) => (
                    <SmallStat key={item.label} label={item.label} value={item.value} />
                  ))}
                </div>
                <AtlasDisclosure title="View scorecard metrics" summary="Detailed WOE/IV, scorecard, AI/ML, cutoff, evidence, and monitoring values.">
                  <CreditRiskDetail profile={creditRiskProfile} woeIvAnalysis={woeIvAnalysis} scorecardModel={scorecardModel} creditRiskMlModel={creditRiskMlModel} />
                </AtlasDisclosure>
                <div className="mt-3 grid gap-2">
                  <Link to="/credit-risk-studio" className="atlas-secondary-button justify-center">Open Credit Risk Studio</Link>
                  <Link to="/model-diagnostics" className="atlas-secondary-button justify-center">Open Model Diagnostics</Link>
                  <Link to={`/model-document-studio?projectId=${projectId}`} className="atlas-secondary-button justify-center">Open Model Documentation Studio</Link>
                </div>
              </AtlasCard>
            )}
          </div>
        </div>
      ),
    },
    {
      id: "workflow",
      label: "Workflow",
      panel: (
        <AtlasCard title="Complete Workflow" eyebrow={`${completed} of ${workflowSteps.length} complete`}>
          <div className="grid gap-2">
            {workflowSteps.map((step, index) => {
              const isCurrent = step.id === current?.id;
              const optimizationStatus = projectType === "optimization" ? optimizationWorkflowStepStatus(optimizationSummary, index + 1, { current: isCurrent, storeComplete: step.status === "complete" }) : null;
              const statusLabel = optimizationStatus ?? (step.status === "complete" ? "Complete" : isCurrent ? "Current" : step.status === "skipped" ? "Skipped" : "Pending");
              const tone = optimizationStatus === "Evidence" || optimizationStatus === "Complete" || step.status === "complete" ? "success" : optimizationStatus === "Blocked" ? "warning" : isCurrent ? "info" : step.status === "skipped" ? "warning" : "neutral";
              return (
                <Link key={step.id} to={step.route} className={`grid gap-3 rounded-xl border px-4 py-3 transition hover:border-blue-200 hover:bg-blue-50 sm:grid-cols-[2.5rem_minmax(0,1fr)_auto] sm:items-center ${isCurrent ? "border-blue-300 bg-blue-50" : "border-slate-200 bg-white"}`}>
                  <span className="grid h-9 w-9 place-items-center rounded-full bg-slate-100 text-xs font-semibold text-slate-700">{index + 1}</span>
                  <span>
                    <span className="block text-sm font-semibold text-slate-950">{step.label}</span>
                    <span className="block text-xs leading-5 text-slate-500">{step.description}</span>
                  </span>
                  <AtlasStatusBadge tone={tone}>{statusLabel}</AtlasStatusBadge>
                </Link>
              );
            })}
          </div>
        </AtlasCard>
      ),
    },
    {
      id: "evidence",
      label: "Evidence and Governance",
      panel: (
        <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_360px]">
          <AtlasCard title="Evidence Summary" eyebrow="Financial Services Evidence">
            <AtlasProgressBar value={evidenceScore} label="Evidence readiness" />
            <div className="mt-4 grid gap-3 sm:grid-cols-4">
              <AtlasMetricCard label="Generated" value={optimizationEvidence?.generatedCount ?? evidenceCoverage?.totalEvidence ?? 0} />
              <AtlasMetricCard label="Captured" value={optimizationEvidence?.capturedCount ?? evidenceCoverage?.readyEvidence ?? 0} tone="success" />
              <AtlasMetricCard label="Ready" value={optimizationEvidence?.readyCount ?? evidenceCoverage?.readyEvidence ?? 0} tone="success" />
              <AtlasMetricCard label="Coverage" value={`${evidenceScore}%`} />
            </div>
            {optimizationEvidence && <div className={`mt-4 rounded-xl border px-4 py-3 text-sm ${optimizationEvidence.packageReady ? "border-emerald-200 bg-emerald-50 text-emerald-900" : "border-amber-200 bg-amber-50 text-amber-900"}`}><div className="font-semibold">{optimizationEvidence.statusLabel}</div><p className="mt-1 text-xs leading-5">Documentation sections populated: {optimizationEvidence.documentationSectionCount} of 20. Approved artifacts: {optimizationEvidence.records.filter((row) => row.approved).length}.</p></div>}
            {!optimizationEvidence && evidenceCoverage?.missingRecommended?.length ? <div className="atlas-warning-panel mt-4 text-sm">Missing recommended evidence: {evidenceCoverage.missingRecommended.join(", ")}</div> : null}
            {evidenceMessage && <div className="atlas-info-panel mt-4 text-sm">{evidenceMessage}</div>}
            <div className="mt-4 flex flex-wrap gap-2">
              <Link to="/model-evidence-center" className="atlas-secondary-button">Open Model Evidence Center</Link>
              {optimizationEvidence ? <Link to={optimizationEvidence.packageReady ? "/model-evidence-center" : "/workflow/optimization/14"} className="atlas-primary-button">{optimizationEvidence.actionLabel}</Link> : <button type="button" onClick={captureProjectEvidence} className="atlas-primary-button">Capture Current Project Evidence</button>}
              <Link to={`/model-document-studio?projectId=${projectId}`} className="atlas-secondary-button">Open Documentation Studio</Link>
            </div>
          </AtlasCard>
          <div className="grid gap-5">
            <CompactListPanel icon={<FileClock size={18} />} title="Recent Decisions" items={decisions.map((entry, index) => ({ key: `${entry.id ?? entry.timestamp ?? index}`, title: entry.subject, detail: `${entry.workflowStep} / ${entry.actionType}` }))} empty="No decisions logged yet." />
            <CompactListPanel icon={<FlaskConical size={18} />} title="Recent Experiments" items={experiments.map((experiment, index) => ({ key: `${experiment.experimentId ?? experiment.modelType ?? index}`, title: experiment.modelType, detail: `${experiment.champion ? "Champion" : "Challenger"} / ${experiment.dataset_version_id}` }))} empty="No experiments recorded yet." />
          </div>
        </div>
      ),
    },
    {
      id: "assets",
      label: "Assets and Operations",
      panel: (
        <div className="grid gap-5 xl:grid-cols-2">
          <Panel icon={<Database size={18} />} title="Linked Datasets">
            {datasetLinks.length ? datasetLinks.map((link) => (
              <Link key={`${link.datasetId}-${link.versionId}`} to={`/datasets/${link.datasetId}`} className="atlas-compact-row">
                <div className="text-xs font-semibold text-slate-900">{link.dataset?.name || link.datasetId}</div>
                <div className="mt-1 text-[11px] leading-4 text-slate-500">{link.datasetRole} / {link.versionId} / {link.dataset?.latestVersion?.rowCount?.toLocaleString() ?? "-"} rows</div>
              </Link>
            )) : <Empty text="No Dataset Library assets linked yet." />}
          </Panel>
          <Panel icon={<Gauge size={18} />} title="Project Analytics Insights">
            {analyticsInsights.length ? analyticsInsights.slice(0, 4).map((insight) => (
              <Link key={insight.insightId} to={insight.analysisType === "chart_studio" ? "/chart-studio" : "/analytics"} className="atlas-compact-row">
                <div className="text-xs font-semibold text-slate-900">{insight.title}</div>
                <div className="mt-1 line-clamp-2 text-[11px] leading-4 text-slate-500">{insight.summary || (insight.analysisType === "chart_studio" ? "Chart Studio insight" : insight.analysisType)}</div>
              </Link>
            )) : <Empty text="No Analytics Workbench or Chart Studio insights linked to this project yet." />}
          </Panel>
          <Panel icon={<Gauge size={18} />} title="Implementation and Monitoring">
            <SmallStat label="Implementation Owner" value={context.implementationOwner || "Not documented"} />
            <SmallStat label="Implementation Environment" value={context.implementationEnvironment || "Not documented"} />
            <SmallStat label="Monitoring Cadence" value={cadence || "Not documented"} />
            <SmallStat label="Monitoring Metrics" value={context.monitoringMetrics.length ? context.monitoringMetrics.join(", ") : "Not selected"} />
          </Panel>
          <Panel icon={<BookOpenCheck size={18} />} title="Documentation Status">
            <div className={`rounded-xl border px-3 py-2 text-sm ${optimizationEvidence?.documentationReady || evidenceScore >= 80 ? "border-emerald-200 bg-emerald-50 text-emerald-900" : "border-amber-200 bg-amber-50 text-amber-900"}`}>
              <div className="font-semibold">{documentationStatus}</div>
              <p className="mt-1 text-xs leading-5">{optimizationEvidence ? `${optimizationEvidence.documentationSectionCount} of 20 sections are populated. ${optimizationEvidence.statusLabel}.` : "Structure may be available before evidence is complete. Review evidence coverage before final approval."}</p>
            </div>
            <Link to={`/model-document-studio?projectId=${projectId}`} className="atlas-secondary-button">Open Model Documentation Studio</Link>
          </Panel>
        </div>
      ),
    },
  ];

  return (
    <div className="atlas-page-shell">
      <AtlasPageHero
        eyebrow="Project control center"
        title={projectName || context.projectName || "Untitled ATLAS Project"}
        subtitle={`${labelize(projectType)} / ${workflow.label}. ${workflow.description}`}
        actions={
          <>
            {current && <Link to={current.route} className="atlas-primary-button">Continue {current.shortLabel ?? current.label}<ArrowRight size={15} /></Link>}
            <Link to="/model-evidence-center" className="atlas-secondary-button">Open Evidence Center</Link>
            <Link to={`/model-document-studio?projectId=${projectId}`} className="atlas-secondary-button">Open Documentation Studio</Link>
          </>
        }
        aside={
          <div className="rounded-2xl border border-slate-200 bg-slate-50 p-4">
            <SmallStat label="Project ID" value={modelId} />
            <div className="mt-2"><SmallStat label="Status" value={documentationStatus} /></div>
            <AtlasProgressBar className="mt-4" value={progress} label="Workflow progress" />
          </div>
        }
      />

      <section className="grid gap-3 md:grid-cols-3 xl:grid-cols-6">
        <AtlasMetricCard label="Workflow completion" value={`${progress}%`} detail={`${completed} / ${workflowSteps.length}`} />
        <AtlasMetricCard label="Evidence coverage" value={`${evidenceScore}%`} tone={evidenceScore >= 80 ? "success" : "warning"} />
        <AtlasMetricCard label="Linked datasets" value={datasetLinks.length} />
        <AtlasMetricCard label="Recent decisions" value={decisions.length} />
        <AtlasMetricCard label="Analytical runs" value={experiments.length} />
        <AtlasMetricCard label="Documentation" value={documentationStatus} tone={evidenceScore >= 80 ? "success" : "warning"} />
      </section>

      <AtlasTabs tabs={tabs} activeTab={activeTab} onChange={setActiveTab} label="Project overview sections" />
      <ShareResourceDialog
        open={shareOpen}
        onClose={() => setShareOpen(false)}
        resourceType="project"
        resourceId={projectId}
        resourceName={projectName || context.projectName || "Project"}
      />
    </div>
  );
}

function CreditRiskDetail({ profile, woeIvAnalysis, scorecardModel, creditRiskMlModel }: { profile: CreditRiskProfile; woeIvAnalysis: WoeIvAnalysis | null; scorecardModel: ScorecardModel | null; creditRiskMlModel: CreditRiskMlModel | null }) {
  return (
    <div className="grid gap-2 sm:grid-cols-2">
      <SmallStat label="Product Type" value={profile.productType || "Not selected"} />
      <SmallStat label="Model Purpose" value={profile.modelPurpose || "Not selected"} />
      <SmallStat label="Target Event" value={profile.targetEvent || "Not selected"} />
      <SmallStat label="Target Window" value={profile.targetWindow || "Not documented"} />
      <SmallStat label="Readiness" value={`${profile.readinessScore ?? 0}%`} />
      <SmallStat label="Modeling Approach" value={creditRiskApproachLabel(profile.selectedModelingApproach)} />
      <SmallStat label="WOE / IV Analysis" value={woeIvAnalysis ? (woeIvAnalysis.variableSummaries.some((row) => row.status === "needs_review") ? "Needs Review" : "Complete") : "Missing"} />
      <SmallStat label="Top IV Variable" value={topIvVariable(woeIvAnalysis)} />
      <SmallStat label="Variables Reviewed" value={woeIvAnalysis ? String(woeIvAnalysis.variableSummaries.length) : "0"} />
      <SmallStat label="WOE Review Items" value={woeIvAnalysis ? String(woeIvAnalysis.variableSummaries.filter((row) => row.status === "needs_review").length) : "0"} />
      <SmallStat label="Scorecard Model" value={scorecardModel ? "Complete" : "Missing"} />
      <SmallStat label="Champion Scorecard" value={scorecardModel?.modelId || "Not registered"} />
      <SmallStat label="AI/ML Status" value={creditRiskMlModel ? "Available" : "Pending"} />
      <SmallStat label="Champion Decision" value={profile.championModelType ? creditRiskApproachLabel(profile.championModelType) : "Not selected"} />
      <SmallStat label="Champion Model" value={scorecardModel?.champion ? scorecardModel.modelId : creditRiskMlModel?.modelId || scorecardModel?.modelId || "Not selected"} />
      <SmallStat label="AUC" value={scorecardModel?.metrics?.auc == null ? "-" : String(scorecardModel.metrics.auc)} />
      <SmallStat label="KS" value={scorecardModel?.metrics?.ks == null ? "-" : String(scorecardModel.metrics.ks)} />
      <SmallStat label="Gini" value={scorecardModel?.metrics?.gini == null ? "-" : String(scorecardModel.metrics.gini)} />
      <SmallStat label="Selected Cutoff" value={scorecardModel?.selectedCutoff == null ? "Not selected" : String(scorecardModel.selectedCutoff)} />
      <SmallStat label="AI/ML AUC" value={creditRiskMlModel?.metrics?.auc == null ? "-" : String(creditRiskMlModel.metrics.auc)} />
      <SmallStat label="AI/ML KS" value={creditRiskMlModel?.metrics?.ks == null ? "-" : String(creditRiskMlModel.metrics.ks)} />
      <SmallStat label="Selected Champion" value={profile.championModelType ? creditRiskApproachLabel(profile.championModelType) : "Not selected"} />
      <SmallStat label="Evidence Readiness" value={profile.evidenceStatus || "Needs Review"} />
      <SmallStat label="Target" value={profile.targetEvent || "Not selected"} />
      <SmallStat label="EDA" value={woeIvAnalysis ? "Reviewed" : "Pending"} />
      <SmallStat label="Screening" value={woeIvAnalysis ? "Reviewed" : "Pending"} />
      <SmallStat label="Approach" value={creditRiskApproachLabel(profile.selectedModelingApproach)} />
      <SmallStat label="Scorecard" value={scorecardModel ? "Available" : "Pending"} />
      <SmallStat label="AI/ML" value={creditRiskMlModel ? "Available" : "Pending"} />
      <SmallStat label="Compare" value={profile.selectedModelingApproach === "compare_both" ? "Enabled" : "Optional"} />
      <SmallStat label="Cutoff" value={scorecardModel?.selectedCutoff == null ? "Pending" : String(scorecardModel.selectedCutoff)} />
      <SmallStat label="Adverse Action" value={profile.adverseActionStatus || "Review required"} />
      <SmallStat label="Monitoring" value={profile.monitoringStatus || "Pending"} />
      <SmallStat label="Evidence" value={profile.evidenceStatus || "Needs Review"} />
    </div>
  );
}

function CompactListPanel({ icon, title, items, empty }: { icon: React.ReactNode; title: string; items: Array<{ key: string; title: string; detail: string }>; empty: string }) {
  return (
    <Panel icon={icon} title={title}>
      {items.length ? items.map((item) => (
        <div key={item.key} className="atlas-compact-row">
          <div className="text-xs font-semibold text-slate-900">{item.title}</div>
          <div className="mt-1 text-[11px] leading-4 text-slate-500">{item.detail}</div>
        </div>
      )) : <Empty text={empty} />}
    </Panel>
  );
}

function labelize(value: string) {
  return value.replace(/-/g, " ").replace(/\b\w/g, (match) => match.toUpperCase());
}

function creditRiskApproachLabel(value?: string) {
  if (value === "scorecard") return "Traditional Scorecard";
  if (value === "ml") return "AI/ML Underwriting";
  if (value === "compare_both") return "Compare Both";
  return value || "Not selected";
}

function topIvVariable(woeIvAnalysis: WoeIvAnalysis | null) {
  const top = woeIvAnalysis?.variableSummaries?.slice().sort((left, right) => Number(right.iv ?? 0) - Number(left.iv ?? 0))[0];
  return top ? `${top.variable} (${Number(top.iv ?? 0).toFixed(4)})` : "Not available";
}

function creditRiskWrapperReadiness(
  profile: CreditRiskProfile,
  workflowSteps: { status?: string }[],
  woeIvAnalysis: WoeIvAnalysis | null,
  scorecardModel: ScorecardModel | null,
  mlModel: CreditRiskMlModel | null,
  evidenceCoverage: EvidenceCoverage | null,
) {
  const completedWorkflow = workflowSteps.filter((step) => step.status === "complete").length;
  const workflowTotal = Math.max(1, workflowSteps.length);
  const underwritingComplete = [woeIvAnalysis, scorecardModel, mlModel].filter(Boolean).length;
  const hasDiagnostics = Boolean(scorecardModel?.metrics || mlModel?.metrics);
  const evidenceReady = evidenceCoverage?.financialServices?.creditRisk?.readyRequired ?? 0;
  const evidenceTotal = evidenceCoverage?.financialServices?.creditRisk?.totalRequired ?? 0;
  const monitoringReady = Boolean(profile.monitoring?.monitoringCadence || profile.monitoringStatus);
  return [
    { label: "Predictive Workflow", value: `${completedWorkflow} / ${workflowTotal}`, tone: completedWorkflow >= workflowTotal ? "complete" : completedWorkflow > 0 ? "review" : "neutral" },
    { label: "Underwriting Tools", value: `${underwritingComplete} / 3`, tone: underwritingComplete >= 2 ? "complete" : underwritingComplete > 0 ? "review" : "neutral" },
    { label: "Model Diagnostics", value: hasDiagnostics ? "Available" : "Pending", tone: hasDiagnostics ? "complete" : "review" },
    { label: "Documentation Studio", value: profile.evidenceStatus || "Needs Review", tone: profile.evidenceStatus === "Ready" ? "complete" : "review" },
    { label: "Model Evidence Center", value: evidenceTotal ? `${evidenceReady} / ${evidenceTotal}` : "Not captured", tone: evidenceTotal && evidenceReady >= evidenceTotal ? "complete" : evidenceReady > 0 ? "review" : "neutral" },
    { label: "Monitoring Readiness", value: monitoringReady ? "Defined" : "Pending", tone: monitoringReady ? "complete" : "review" },
  ] as const;
}

function Panel({ icon, title, children }: { icon: React.ReactNode; title: string; children: React.ReactNode }) {
  return (
    <section className="atlas-card">
      <div className="flex items-center gap-2 text-slate-900">
        {icon}
        <h2 className="text-sm font-semibold">{title}</h2>
      </div>
      <div className="mt-3 grid gap-2">{children}</div>
    </section>
  );
}

function Empty({ text }: { text: string }) {
  return <div className="rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-500">{text}</div>;
}

function SmallStat({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-slate-50 px-3 py-2">
      <div className="text-[10px] font-semibold uppercase tracking-wide text-slate-500">{label}</div>
      <div className="mt-1 text-sm font-semibold text-slate-950">{value}</div>
    </div>
  );
}

function MonitoringOverviewCard({
  projectId,
  projectName,
  workflowType,
  detail,
  onChanged,
}: {
  projectId: string;
  projectName: string;
  workflowType: string;
  detail: MonitoringPlanDetail | null;
  onChanged: (detail: MonitoringPlanDetail | null) => void;
}) {
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const plan = detail?.plan;
  const latestRun = detail?.runs?.[0];
  const openAlerts = detail?.alerts.filter((alert) => !["resolved", "closed", "accepted_risk"].includes(alert.status)) ?? [];

  async function createPlan() {
    setBusy("create");
    setError("");
    try {
      onChanged(await createProjectMonitoringPlan(projectId, { workflow_type: workflowType, plan_name: `${projectName || projectId} Monitoring Plan` }));
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "ATLAS could not create the monitoring plan.");
    } finally {
      setBusy("");
    }
  }

  async function startRun() {
    if (!plan) return;
    setBusy("run");
    setError("");
    try {
      const created = await createMonitoringRun(plan.monitoring_plan_id, { run_name: `${plan.plan_name} run`, summary: "Manual monitoring run started from Project Overview." });
      await startMonitoringRun(created.run.monitoring_run_id);
      onChanged(await getProjectMonitoringPlan(projectId));
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "ATLAS could not start the monitoring run.");
    } finally {
      setBusy("");
    }
  }

  return (
    <AtlasCard
      className="xl:col-span-full"
      title="Production Monitoring"
      eyebrow="Post-decision control"
      tone={plan ? (openAlerts.length ? "warning" : "success") : "info"}
      action={plan ? <Link to={`/project-monitoring/${encodeURIComponent(projectId)}`} className="atlas-tertiary-button">Open monitoring plan <ArrowRight size={15} /></Link> : undefined}
    >
      {error && <div className="mb-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs font-semibold text-amber-900">{error}</div>}
      {plan ? (
        <>
          <div className="grid gap-x-6 sm:grid-cols-2 lg:grid-cols-4 xl:grid-cols-8">
            <RegistryFact label="Plan status" value={<AtlasStatusBadge tone={monitoringStatusTone(plan.plan_status) as any}>{monitoringPlanStatusLabels[plan.plan_status] || plan.plan_status}</AtlasStatusBadge>} />
            <RegistryFact label="Owner" value={plan.monitoring_owner_name || "Unassigned"} />
            <RegistryFact label="Cadence" value={plan.monitoring_cadence || "Not set"} />
            <RegistryFact label="Last run" value={formatRegistryDate(plan.last_run_at, true)} />
            <RegistryFact label="Next run" value={formatRegistryDate(plan.next_monitoring_date)} />
            <RegistryFact label="Latest status" value={latestRun ? monitoringRunStatusLabels[latestRun.run_status] || latestRun.run_status : "No run"} />
            <RegistryFact label="Open alerts" value={openAlerts.length} />
            <RegistryFact label="Metrics" value={detail?.metrics.length ?? 0} />
          </div>
          <div className="mt-4 flex flex-wrap gap-2 border-t border-slate-200 pt-4">
            <button type="button" className="atlas-primary-button" onClick={() => void startRun()} disabled={Boolean(busy)}>Start monitoring run</button>
            <Link to="/monitoring" className="atlas-secondary-button">Open Monitoring Center</Link>
            <Link to={`/project-monitoring/${encodeURIComponent(projectId)}`} className="atlas-secondary-button">View alerts and actions</Link>
          </div>
        </>
      ) : (
        <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-center">
          <p className="text-sm leading-6 text-slate-600">No production monitoring plan is defined for this project yet. Create a governed plan when the asset is approved for implementation or ongoing control.</p>
          <button type="button" className="atlas-primary-button justify-center" onClick={() => void createPlan()} disabled={Boolean(busy)}>Create monitoring plan</button>
        </div>
      )}
    </AtlasCard>
  );
}

function RegistryFact({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="min-w-0 border-b border-slate-100 py-3 lg:border-b-0">
      <div className="text-[10px] font-semibold uppercase tracking-[0.12em] text-slate-500">{label}</div>
      <div className="mt-2 min-w-0 text-sm font-semibold text-slate-950">{value}</div>
    </div>
  );
}
