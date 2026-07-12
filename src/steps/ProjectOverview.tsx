import { Link } from "react-router-dom";
import type React from "react";
import { useEffect, useState } from "react";
import { ArrowRight, BookOpenCheck, CheckCircle2, Database, FileClock, FlaskConical, Gauge, Landmark, Network } from "lucide-react";
import BrandLogo from "../components/BrandLogo";
import { getWorkflowDefinition } from "../config/workflows";
import { loadDecisionJournal } from "../lib/decisionJournal";
import { listProjectDatasets, type ProjectDatasetLink } from "../lib/datasetLibrary";
import { listAnalyticsInsights, type AtlasAnalyticsInsight } from "../lib/analyticsWorkbench";
import { autoCaptureEvidence, getEvidenceCoverage, type EvidenceCoverage } from "../lib/evidenceGraph";
import { loadExperiments } from "../lib/experimentTracking";
import { loadProjectContext } from "../lib/projectContext";
import { AB_MARKETING_DEFAULTS, allocationImbalance, analyzeAbLift, decisionRecommendationReason, summarizeAbGroups } from "../lib/abTestingWorkflow";
import { getCreditRiskProfileForProject, getLatestCreditRiskMlModelForProject, getLatestScorecardForProject, getLatestWoeIvAnalysisForProject, type CreditRiskMlModel, type CreditRiskProfile, type ScorecardModel, type WoeIvAnalysis } from "../lib/creditRiskStudio";
import { useWorkflowStore } from "../state/useWorkflowStore";

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
  const current = workflowSteps.find((step) => step.status !== "complete" && step.status !== "skipped") ?? workflowSteps[workflowSteps.length - 1];
  const progress = workflowSteps.length ? Math.round((completed / workflowSteps.length) * 100) : 0;
  const modelId = context.modelId || useWorkflowStore.getState().modelId || "Not assigned";
  const cadence =
    context.monitoringCadence === "custom"
      ? context.monitoringCadenceCustom || "Custom cadence not documented"
      : context.monitoringCadence;
  const [datasetLinks, setDatasetLinks] = useState<ProjectDatasetLink[]>([]);
  const [analyticsInsights, setAnalyticsInsights] = useState<AtlasAnalyticsInsight[]>([]);
  const [evidenceCoverage, setEvidenceCoverage] = useState<EvidenceCoverage | null>(null);
  const [evidenceMessage, setEvidenceMessage] = useState("");
  const [creditRiskProfile, setCreditRiskProfile] = useState<CreditRiskProfile | null>(null);
  const [woeIvAnalysis, setWoeIvAnalysis] = useState<WoeIvAnalysis | null>(null);
  const [scorecardModel, setScorecardModel] = useState<ScorecardModel | null>(null);
  const [creditRiskMlModel, setCreditRiskMlModel] = useState<CreditRiskMlModel | null>(null);
  const abSummary = projectType === "ab-testing" ? summarizeAbGroups() : null;
  const abAnalysis = abSummary ? analyzeAbLift(abSummary) : null;
  const abImbalance = abSummary ? allocationImbalance(abSummary) : null;
  const abDecisionRecommendation = abAnalysis && abImbalance ? decisionRecommendationReason(abAnalysis, abImbalance) : "";

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
    ])
      .then((links) => {
        if (alive) {
          setDatasetLinks(links[0]);
          setAnalyticsInsights(links[1]);
          setEvidenceCoverage(links[2]);
          setCreditRiskProfile(links[3]);
          setWoeIvAnalysis(links[4]);
          setScorecardModel(links[5]);
          setCreditRiskMlModel(links[6]);
        }
      })
      .catch(() => {
        if (alive) {
          setDatasetLinks([]);
          setAnalyticsInsights([]);
          setEvidenceCoverage(null);
          setCreditRiskProfile(null);
          setWoeIvAnalysis(null);
          setScorecardModel(null);
          setCreditRiskMlModel(null);
        }
      });
    return () => {
      alive = false;
    };
  }, [projectId]);

  async function captureProjectEvidence() {
    try {
      const captured = await autoCaptureEvidence({ projectId, projectName });
      setEvidenceMessage(`Captured or refreshed ${captured.length} evidence item(s).`);
      setEvidenceCoverage(await getEvidenceCoverage(projectId));
    } catch (error) {
      setEvidenceMessage(error instanceof Error ? error.message : "ATLAS could not capture project evidence.");
    }
  }

  return (
    <div className="w-full space-y-5">
      <section className="rounded-xl border border-slate-200/80 bg-white/90 p-5 shadow-sm">
        <div className="flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between">
          <div>
            <BrandLogo size="md" variant="light" showSubtitle className="mb-3" />
            <div className="flex items-center gap-2">
              <Gauge size={20} className="text-slate-800" />
              <h1 className="text-xl font-semibold text-slate-950">Current Project Overview</h1>
            </div>
            <p className="mt-1 max-w-3xl text-sm text-slate-600">
              Control center for the selected project, active workflow, recent decisions, experiments, and documentation readiness.
            </p>
          </div>
          {current && (
            <Link to={current.route} className="inline-flex items-center gap-2 rounded-lg bg-slate-950 px-3 py-2 text-sm font-semibold text-white shadow-sm hover:bg-slate-800">
              Next Recommended Action
              <ArrowRight size={15} />
            </Link>
          )}
        </div>
      </section>

      <section className="grid gap-4 md:grid-cols-4">
        <Stat label="Model ID #" value={modelId} />
        <Stat label="Project" value={projectName || context.projectName || "Untitled"} />
        <Stat label="Project Type" value={labelize(projectType)} />
        <Stat label="Completion" value={`${progress}%`} />
      </section>

      <section className="grid gap-5 xl:grid-cols-[1.15fr_0.85fr]">
        <div className="rounded-lg border border-slate-200/80 bg-white/90 p-5 shadow-sm">
          <h2 className="text-sm font-semibold text-slate-950">Current Workflow</h2>
          <p className="mt-1 text-sm text-slate-500">{workflow.description}</p>
          <div className="mt-4 grid gap-2">
            {workflowSteps.map((step, index) => (
              <Link
                key={step.id}
                to={step.route}
                className="grid gap-3 rounded-lg border border-slate-200 bg-slate-50 px-3 py-3 transition hover:border-blue-200 hover:bg-blue-50 sm:grid-cols-[2rem_1fr_auto] sm:items-center"
              >
                <span className={`grid h-8 w-8 place-items-center rounded-full text-xs font-semibold ${step.status === "complete" ? "bg-emerald-100 text-emerald-700" : "bg-white text-slate-600 ring-1 ring-slate-200"}`}>
                  {index + 1}
                </span>
                <span>
                  <span className="block text-sm font-semibold text-slate-950">{step.label}</span>
                  <span className="block text-xs leading-5 text-slate-500">{step.description}</span>
                </span>
                <span className="text-xs font-semibold text-slate-500">{step.status === "complete" ? "Complete" : "Open"}</span>
              </Link>
            ))}
          </div>
        </div>

        <div className="grid gap-5">
          {abSummary && abAnalysis && abImbalance && (
            <Panel icon={<FlaskConical size={18} />} title="A/B Testing Summary">
              <div className="rounded-lg border border-blue-200 bg-blue-50 px-3 py-3">
                <div className="text-xs font-semibold uppercase tracking-wide text-blue-700">Marketing experiment workflow</div>
                <p className="mt-1 text-xs leading-5 text-blue-900">
                  {AB_MARKETING_DEFAULTS.dataset} is mapped with {AB_MARKETING_DEFAULTS.unitIdColumn} as the unit, {AB_MARKETING_DEFAULTS.treatmentColumn} as treatment, and {AB_MARKETING_DEFAULTS.outcomeColumn} as the primary outcome.
                </p>
              </div>
              <div className="grid gap-2 sm:grid-cols-2">
                <SmallStat label="Experiment Name" value={projectName || context.projectName || "Marketing AB Test Workflow Demo"} />
                <SmallStat label="Treatment" value={AB_MARKETING_DEFAULTS.treatmentValue} />
                <SmallStat label="Control" value={AB_MARKETING_DEFAULTS.controlValue} />
                <SmallStat label="Primary Metric" value="Conversion rate" />
                <SmallStat label="Treatment Sample Size" value={abSummary.treatmentCount.toLocaleString()} />
                <SmallStat label="Control Sample Size" value={abSummary.controlCount.toLocaleString()} />
                <SmallStat label="Treatment Conversion Rate" value={`${(abAnalysis.treatmentConversionRate * 100).toFixed(2)}%`} />
                <SmallStat label="Control Conversion Rate" value={`${(abAnalysis.controlConversionRate * 100).toFixed(2)}%`} />
                <SmallStat label="Absolute Lift" value={`${(abAnalysis.absoluteLift * 100).toFixed(2)} pp`} />
                <SmallStat label="Relative Lift" value={`${(abAnalysis.relativeLift * 100).toFixed(2)}%`} />
                <SmallStat label="P-value" value={abAnalysis.pValue.toFixed(4)} />
                <SmallStat label="Evidence Readiness" value={`${evidenceCoverage?.coverageScore ?? 0}%`} />
              </div>
              <div className={`rounded-lg border px-3 py-2 text-xs leading-5 ${abImbalance.warning ? "border-amber-200 bg-amber-50 text-amber-900" : "border-emerald-200 bg-emerald-50 text-emerald-900"}`}>
                <div className="font-semibold">Decision recommendation</div>
                <div>{abDecisionRecommendation}</div>
                <div className="mt-1">Allocation review: {abImbalance.message}</div>
              </div>
              <div className="grid gap-2 sm:grid-cols-3">
                <Link to="/workflow/ab-testing/1" className="atlas-secondary-button justify-center">Open A/B Workflow</Link>
                <Link to="/model-evidence-center" className="atlas-secondary-button justify-center">Open Model Evidence Center</Link>
                <Link to={`/model-document-studio?projectId=${projectId}`} className="atlas-secondary-button justify-center">Open Documentation Studio</Link>
              </div>
            </Panel>
          )}

          <Panel icon={<FileClock size={18} />} title="Recent Decisions">
            {decisions.length ? (
              decisions.map((entry, index) => (
                <div key={`${entry.id ?? entry.timestamp ?? entry.workflowStep ?? "decision"}-${index}`} className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2">
                  <div className="text-xs font-semibold text-slate-900">{entry.subject}</div>
                  <div className="mt-1 text-[11px] leading-4 text-slate-500">{entry.workflowStep} · {entry.actionType}</div>
                </div>
              ))
            ) : (
              <Empty text="No decisions logged yet." />
            )}
          </Panel>

          <Panel icon={<FlaskConical size={18} />} title="Recent Experiments">
            {experiments.length ? (
              experiments.map((experiment, index) => (
                <div key={`${experiment.experimentId ?? experiment.modelType ?? "experiment"}-${index}`} className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2">
                  <div className="text-xs font-semibold text-slate-900">{experiment.modelType}</div>
                  <div className="mt-1 text-[11px] leading-4 text-slate-500">{experiment.champion ? "Champion" : "Challenger"} · {experiment.datasetVersion}</div>
                </div>
              ))
            ) : (
              <Empty text="No experiments recorded yet." />
            )}
          </Panel>

          <Panel icon={<BookOpenCheck size={18} />} title="Documentation Status">
            <div className="rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-900">
              <div className="flex items-center gap-2 font-semibold">
                <CheckCircle2 size={15} />
                Governance-ready structure available
              </div>
              <p className="mt-1 text-xs leading-5">Reports and notebook exports are workflow-aware and will use placeholder outlines for non-modeling workflows.</p>
            </div>
            <Link to={`/model-document-studio?projectId=${projectId}`} className="atlas-secondary-button">
              Open Model Documentation Studio
            </Link>
          </Panel>

          <Panel icon={<Network size={18} />} title="Evidence Summary">
            <div className="grid gap-2 sm:grid-cols-2">
              <SmallStat label="Total" value={String(evidenceCoverage?.totalEvidence ?? 0)} />
              <SmallStat label="Ready" value={String(evidenceCoverage?.readyEvidence ?? 0)} />
              <SmallStat label="Needs Review" value={String(evidenceCoverage?.needsReviewEvidence ?? 0)} />
              <SmallStat label="Coverage" value={`${evidenceCoverage?.coverageScore ?? 0}%`} />
            </div>
            <div className="rounded-lg border border-blue-200 bg-blue-50 px-3 py-2 text-xs leading-5 text-blue-900">
              <div className="font-semibold">Financial Services Evidence</div>
              <div>Suggested domain: {evidenceCoverage?.financialServices?.suggestedDomain?.label ?? "Model Risk / Governance"}</div>
              <div>Credit Risk evidence: {evidenceCoverage?.financialServices?.creditRisk?.readyRequired ?? 0} of {evidenceCoverage?.financialServices?.creditRisk?.totalRequired ?? 0} required items ready.</div>
            </div>
            {evidenceCoverage?.missingRecommended?.length ? (
              <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs leading-5 text-amber-900">
                Missing recommended evidence: {evidenceCoverage.missingRecommended.join(", ")}
              </div>
            ) : null}
            {evidenceMessage && <div className="rounded-lg border border-blue-200 bg-blue-50 px-3 py-2 text-xs text-blue-900">{evidenceMessage}</div>}
            <div className="grid gap-2 sm:grid-cols-2">
              <Link to="/model-evidence-center" className="atlas-secondary-button justify-center">Open Model Evidence Center</Link>
              <button type="button" onClick={captureProjectEvidence} className="inline-flex items-center justify-center rounded-lg bg-slate-950 px-3 py-2 text-sm font-semibold text-white">
                Capture Current Project Evidence
              </button>
            </div>
          </Panel>

          {creditRiskProfile && (
            <Panel icon={<Landmark size={18} />} title="Credit Risk Profile">
              <div className="rounded-lg border border-blue-200 bg-blue-50 px-3 py-3">
                <div className="text-xs font-semibold uppercase tracking-wide text-blue-700">Credit Risk Studio wrapper readiness</div>
                <p className="mt-1 text-xs leading-5 text-blue-900">
                  Credit Risk Studio is linked to the full Predictive Modeling workflow and adds underwriting-specific tools, diagnostics, documentation, evidence, implementation, and monitoring controls.
                </p>
                <div className="mt-3 grid gap-2 sm:grid-cols-3">
                  {creditRiskWrapperReadiness(creditRiskProfile, workflowSteps, woeIvAnalysis, scorecardModel, creditRiskMlModel, evidenceCoverage).map((item) => (
                    <div key={item.label} className={`rounded-lg border px-3 py-2 ${item.tone === "complete" ? "border-emerald-200 bg-emerald-50 text-emerald-900" : item.tone === "review" ? "border-amber-200 bg-amber-50 text-amber-900" : "border-slate-200 bg-white text-slate-700"}`}>
                      <div className="text-[10px] font-semibold uppercase tracking-wide">{item.label}</div>
                      <div className="mt-1 text-sm font-semibold">{item.value}</div>
                      <div className="mt-1 text-[11px] leading-4 opacity-80">{item.detail}</div>
                    </div>
                  ))}
                </div>
              </div>
              <div className="grid gap-2 sm:grid-cols-5">
                {creditRiskOverviewStages(creditRiskProfile, woeIvAnalysis, scorecardModel, creditRiskMlModel).map((stage) => (
                  <div key={stage.label} className={`rounded-lg border px-3 py-2 ${stage.status === "Complete" ? "border-emerald-200 bg-emerald-50 text-emerald-900" : stage.status === "Needs Review" ? "border-amber-200 bg-amber-50 text-amber-900" : "border-slate-200 bg-slate-50 text-slate-600"}`}>
                    <div className="text-[11px] font-semibold uppercase tracking-wide">{stage.label}</div>
                    <div className="mt-1 text-xs font-semibold">{stage.status}</div>
                  </div>
                ))}
              </div>
              <div className="grid gap-2 sm:grid-cols-2">
                <SmallStat label="Product Type" value={creditRiskProfile.productType || "Not selected"} />
                <SmallStat label="Model Purpose" value={creditRiskProfile.modelPurpose || "Not selected"} />
                <SmallStat label="Target Event" value={creditRiskProfile.targetEvent || "Not selected"} />
                <SmallStat label="Target Window" value={creditRiskProfile.targetWindow || "Not documented"} />
                <SmallStat label="TTC / PIT" value={creditRiskProfile.ttcPitAssumption || "Not selected"} />
                <SmallStat label="Readiness" value={`${creditRiskProfile.readinessScore ?? 0}%`} />
                <SmallStat label="Modeling Approach" value={creditRiskApproachLabel(creditRiskProfile.selectedModelingApproach)} />
                <SmallStat label="Scorecard Status" value={creditRiskProfile.scorecardStatus || (scorecardModel ? "Complete" : "Missing")} />
                <SmallStat label="AI/ML Status" value={creditRiskProfile.mlStatus || (creditRiskMlModel ? "Complete" : "Missing")} />
                <SmallStat label="Champion Decision" value={creditRiskProfile.championDecisionStatus || (creditRiskProfile.championDecision?.selectedModelType ? "Ready" : "Needs Review")} />
                <SmallStat label="Champion Model" value={creditRiskProfile.championModelId || "Not selected"} />
                <SmallStat label="WOE / IV Analysis" value={woeIvAnalysis ? (woeIvAnalysis.variableSummaries.some((row) => row.status === "needs_review") ? "Needs Review" : "Complete") : "Missing"} />
                <SmallStat label="Top IV Variable" value={woeIvAnalysis?.variableSummaries?.[0]?.variable || "Not available"} />
                <SmallStat label="Variables Reviewed" value={woeIvAnalysis ? String(woeIvAnalysis.variableSummaries.length) : "0"} />
                <SmallStat label="WOE Review Items" value={woeIvAnalysis ? String(woeIvAnalysis.variableSummaries.filter((row) => row.status === "needs_review").length) : "0"} />
                <SmallStat label="Scorecard Model" value={scorecardModel ? "Complete" : "Missing"} />
                <SmallStat label="Champion Scorecard" value={scorecardModel?.modelId || "Not registered"} />
                <SmallStat label="AUC" value={scorecardModel?.metrics?.auc == null ? "-" : String(scorecardModel.metrics.auc)} />
                <SmallStat label="KS" value={scorecardModel?.metrics?.ks == null ? "-" : String(scorecardModel.metrics.ks)} />
                <SmallStat label="Gini" value={scorecardModel?.metrics?.gini == null ? "-" : String(scorecardModel.metrics.gini)} />
                <SmallStat label="AI/ML AUC" value={creditRiskMlModel?.metrics?.auc == null ? "-" : String(creditRiskMlModel.metrics.auc)} />
                <SmallStat label="AI/ML KS" value={creditRiskMlModel?.metrics?.ks == null ? "-" : String(creditRiskMlModel.metrics.ks)} />
                <SmallStat label="AI/ML Gini" value={creditRiskMlModel?.metrics?.gini == null ? "-" : String(creditRiskMlModel.metrics.gini)} />
                <SmallStat label="Selected Champion" value={creditRiskProfile.championModelType ? creditRiskApproachLabel(creditRiskProfile.championModelType) : "Not selected"} />
                <SmallStat label="Evidence Readiness" value={creditRiskProfile.evidenceStatus || "Needs Review"} />
                <SmallStat label="PDO" value={scorecardModel?.pdoSettings?.pdo == null ? "-" : String(scorecardModel.pdoSettings.pdo)} />
                <SmallStat label="Base Score" value={scorecardModel?.pdoSettings?.baseScore == null ? "-" : String(scorecardModel.pdoSettings.baseScore)} />
                <SmallStat label="Base Odds" value={scorecardModel?.pdoSettings?.baseOdds || "-"} />
                <SmallStat label="Selected Cutoff" value={scorecardModel?.selectedCutoff == null ? "-" : String(scorecardModel.selectedCutoff)} />
              </div>
              <div className="rounded-lg border border-blue-200 bg-blue-50 px-3 py-2 text-xs leading-5 text-blue-900">
                Credit Risk Studio profile is linked to this project and can generate underwriting, scorecard, adverse-action, monitoring, and evidence-center artifacts.
              </div>
              <div className="grid gap-2 sm:grid-cols-2">
                <Link to="/credit-risk-studio" className="atlas-secondary-button justify-center">Open Credit Risk Studio</Link>
                <Link to="/model-diagnostics" className="atlas-secondary-button justify-center">Open Model Diagnostics</Link>
                <Link to={`/model-document-studio?projectId=${projectId}&domain=credit_risk`} className="atlas-secondary-button justify-center">Open Model Documentation Studio</Link>
                <Link to="/model-evidence-center" className="atlas-secondary-button justify-center">Open Model Evidence Center</Link>
              </div>
            </Panel>
          )}

          <Panel icon={<Database size={18} />} title="Linked Datasets">
            {datasetLinks.length ? (
              datasetLinks.map((link) => (
                <Link key={`${link.datasetId}-${link.versionId}`} to={`/datasets/${link.datasetId}`} className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 transition hover:border-blue-200 hover:bg-blue-50">
                  <div className="text-xs font-semibold text-slate-900">{link.dataset?.name || link.datasetId}</div>
                  <div className="mt-1 text-[11px] leading-4 text-slate-500">
                    {link.datasetRole} · {link.versionId} · {link.dataset?.latestVersion?.rowCount?.toLocaleString() ?? "-"} rows
                  </div>
                </Link>
              ))
            ) : (
              <Empty text="No Dataset Library assets linked yet." />
            )}
          </Panel>

          <Panel icon={<Gauge size={18} />} title="Project Analytics Insights and Chart Insights">
            {analyticsInsights.length ? (
              analyticsInsights.slice(0, 4).map((insight) => (
                <Link key={insight.insightId} to={insight.analysisType === "chart_studio" ? "/chart-studio" : "/analytics"} className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 transition hover:border-blue-200 hover:bg-blue-50">
                  <div className="text-xs font-semibold text-slate-900">{insight.title}</div>
                  <div className="mt-1 line-clamp-2 text-[11px] leading-4 text-slate-500">{insight.summary || (insight.analysisType === "chart_studio" ? "Chart Studio insight" : insight.analysisType)}</div>
                </Link>
              ))
            ) : (
              <Empty text="No Analytics Workbench or Chart Studio insights linked to this project yet." />
            )}
          </Panel>

          <Panel icon={<Gauge size={18} />} title="Implementation & Monitoring">
            <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2">
              <div className="text-xs font-semibold text-slate-900">Implementation</div>
              <div className="mt-1 text-[11px] leading-4 text-slate-500">
                Owner: {context.implementationOwner || "Not documented"} · Environment: {context.implementationEnvironment || "Not documented"}
              </div>
            </div>
            <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2">
              <div className="text-xs font-semibold text-slate-900">Monitoring cadence: {cadence}</div>
              <div className="mt-1 text-[11px] leading-4 text-slate-500">
                Metrics: {context.monitoringMetrics.length ? context.monitoringMetrics.join(", ") : "Not selected"}
              </div>
            </div>
          </Panel>
        </div>
      </section>
    </div>
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

function creditRiskOverviewStages(profile: CreditRiskProfile, woeIvAnalysis: WoeIvAnalysis | null, scorecardModel: ScorecardModel | null, mlModel: CreditRiskMlModel | null) {
  const complete = "Complete";
  const review = "Needs Review";
  const missing = "Missing";
  return [
    { label: "Target", status: profile.targetEvent && profile.targetWindow ? complete : missing },
    { label: "EDA", status: profile.edaStatus || (profile.variableMappings?.length ? review : missing) },
    { label: "Screening", status: profile.screeningStatus || (profile.variableMappings?.some((row) => row.include) ? review : missing) },
    { label: "Approach", status: profile.selectedModelingApproach ? complete : review },
    { label: "Scorecard", status: profile.scorecardStatus || profile.scorecardModelStatus || (scorecardModel ? complete : woeIvAnalysis ? review : missing) },
    { label: "AI/ML", status: profile.mlStatus || (mlModel ? complete : profile.selectedModelingApproach === "ml" || profile.selectedModelingApproach === "compare_both" ? review : missing) },
    { label: "Compare", status: profile.championDecisionStatus || profile.comparisonStatus || (profile.championDecision?.selectedModelId ? complete : scorecardModel || mlModel ? review : missing) },
    { label: "Cutoff", status: profile.cutoffStrategyStatus || (profile.decisionStrategy?.notes || scorecardModel?.cutoffTable?.length ? review : missing) },
    { label: "Adverse Action", status: profile.adverseActionStatus || (profile.explainability?.reasonCodeLogic ? review : missing) },
    { label: "Monitoring", status: profile.monitoringStatus || (profile.monitoring?.monitoringCadence ? review : missing) },
    { label: "Evidence", status: profile.evidenceStatus || ((profile.readinessScore ?? 0) >= 80 ? complete : review) },
  ];
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
    {
      label: "Predictive Workflow",
      value: `${completedWorkflow} / ${workflowTotal}`,
      detail: "Uses ATLAS data, EDA, feature engineering, train/test/OOT, interpretation, scoring, implementation, and monitoring steps.",
      tone: completedWorkflow >= workflowTotal ? "complete" : completedWorkflow > 0 ? "review" : "neutral",
    },
    {
      label: "Underwriting Tools",
      value: `${underwritingComplete} / 3`,
      detail: "WOE/IV, traditional scorecard, and AI/ML challenger readiness.",
      tone: underwritingComplete >= 2 ? "complete" : underwritingComplete > 0 ? "review" : "neutral",
    },
    {
      label: "Model Diagnostics",
      value: hasDiagnostics ? "Available" : "Pending",
      detail: "Performance, stability, cutoff, PSI/VSI, scorecard, and challenger diagnostics.",
      tone: hasDiagnostics ? "complete" : "review",
    },
    {
      label: "Documentation Studio",
      value: profile.evidenceStatus || "Needs Review",
      detail: "Credit risk evidence is routed to Model Documentation Studio for governed development documents.",
      tone: profile.evidenceStatus === "Ready" ? "complete" : "review",
    },
    {
      label: "Model Evidence Center",
      value: evidenceTotal ? `${evidenceReady} / ${evidenceTotal}` : "Not captured",
      detail: "Credit risk evidence coverage for validation, documentation, and governance review.",
      tone: evidenceTotal && evidenceReady >= evidenceTotal ? "complete" : evidenceReady > 0 ? "review" : "neutral",
    },
    {
      label: "Monitoring Readiness",
      value: monitoringReady ? "Defined" : "Pending",
      detail: "Production cadence, PSI/VSI, adverse action, fair lending, and challenger monitoring controls.",
      tone: monitoringReady ? "complete" : "review",
    },
  ] as const;
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-slate-200/80 bg-white/90 p-4 shadow-sm">
      <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">{label}</div>
      <div className="mt-2 truncate text-xl font-semibold text-slate-950" title={value}>{value}</div>
    </div>
  );
}

function Panel({ icon, title, children }: { icon: React.ReactNode; title: string; children: React.ReactNode }) {
  return (
    <section className="rounded-lg border border-slate-200/80 bg-white/90 p-5 shadow-sm">
      <div className="flex items-center gap-2 text-slate-900">
        {icon}
        <h2 className="text-sm font-semibold">{title}</h2>
      </div>
      <div className="mt-3 grid gap-2">{children}</div>
    </section>
  );
}

function Empty({ text }: { text: string }) {
  return <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-500">{text}</div>;
}

function SmallStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2">
      <div className="text-[10px] font-semibold uppercase tracking-wide text-slate-500">{label}</div>
      <div className="mt-1 text-sm font-semibold text-slate-950">{value}</div>
    </div>
  );
}
