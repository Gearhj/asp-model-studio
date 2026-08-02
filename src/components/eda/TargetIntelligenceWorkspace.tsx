// EDA Target Intelligence workspace.
//
// Replaces the previous Target tab, which restated Overview's class counts and
// then showed two group tables. This workspace answers the question a reviewer
// actually has to answer -- is the target correctly defined, sufficiently
// populated, stable, measurable, and appropriate for modeling -- in eight
// ordered sections.
//
// Data sourcing, stated once:
//   * Class counts, event rate, imbalance tier, and the Wilson interval come
//     from POST /api/analytics/target-assessment, which reuses the cached exact
//     DuckDB aggregate over the governed artifact.
//   * Identity, quality, leakage, governed time fields, time and segment tables
//     come from the Full Governed Population EDA workspace target section.
//   * Governance narrative comes from the durable backend Project Context.
//   * Target by predictor is on-demand only.
// Nothing on this page is computed from a browser preview.
import { useEffect, useMemo, useRef, useState } from "react";
import type { EChartsOption } from "echarts";
import { AlertTriangle, ArrowRight, CheckCircle2, Clock, Database, Info, Layers, ShieldAlert, Target as TargetIcon } from "lucide-react";
import EChartsPanel, { type EChartsPanelState } from "../../visual-intelligence/EChartsPanel";
import TargetDistributionPanel from "../dataAcquisition/TargetDistributionPanel";
import AnalysisScopeBanner, { type ScopeResolution } from "./AnalysisScopeBanner";
import TargetByPredictorPanel, { type PredictorOption } from "./TargetByPredictorPanel";
import TargetFindingsPanel from "./TargetFindingsPanel";
import {
  TargetBalanceConfidenceVisual,
  TargetPredictorPreview,
  TargetQualityDiagnostic,
  type TargetPredictorPreviewPayload,
  type TargetPredictorPreviewRow,
} from "./TargetVisualInsights";
import { AtlasWorkflowSection } from "../ui/AtlasWorkflow";
import { buildTargetDistribution, formatEventRate, type TargetDistribution } from "../../lib/dataAcquisitionLifecycle";
import { useTargetDistribution } from "../../lib/useTargetDistribution";
import {
  buildTargetEvidencePayload,
  buildTargetGovernanceFields,
  describeConfidenceInterval,
  evidenceDisabledReason,
  formatCount,
  formatRatio,
  GOVERNANCE_ABSENT_LABEL,
  IMBALANCE_TONES,
  isGovernedScope,
  unresolvedGovernanceGaps,
  type AnalysisScope,
  type ConfidenceInterval,
  type GovernanceField,
  type ImbalanceAssessment,
  type TargetClassBalance,
  type TargetFinding,
} from "../../lib/targetIntelligence";
import {
  useTargetAssessment,
  useTargetByPredictor,
  useTargetFindings,
} from "../../lib/useTargetIntelligence";
import {
  createTargetFinding,
  promoteTargetFinding,
  saveGovernedTargetEvidence,
  updateTargetFinding,
} from "../../lib/targetIntelligenceApi";
import { hydrateProjectContext } from "../../lib/projectContextPersistence";
import type { ProjectContext } from "../../lib/projectContext";
import { getCachedUserId } from "../../lib/authSession";
import { safeArray, safeObject } from "../../lib/workflowSafety";

export type TargetWorkspaceData = Record<string, any>;

export type DatasetIdentity = {
  datasetId: string;
  versionId: string;
  datasetName: string;
};

function prefersReducedMotion(): boolean {
  return typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches === true;
}

export default function TargetIntelligenceWorkspace({
  data,
  projectId,
  projectName,
  datasetIdentity,
  eventValue,
  nonEventValue,
  predictorOptions,
  timeField,
  segmentField,
  segmentCandidates,
  onTimeField,
  onSegmentField,
  onRunConditional,
}: {
  data: TargetWorkspaceData;
  projectId: string;
  projectName: string;
  /** Null when the project has no registered Dataset Library version; the exact
   *  server aggregate then cannot be identified and the page says so. */
  datasetIdentity: DatasetIdentity | null;
  eventValue: unknown;
  nonEventValue: unknown;
  predictorOptions: PredictorOption[];
  timeField: string;
  segmentField: string;
  segmentCandidates: string[];
  onTimeField: (value: string) => void;
  onSegmentField: (value: string) => void;
  onRunConditional: () => void;
}) {
  const reducedMotion = prefersReducedMotion();
  const identity = safeObject<Record<string, any>>(data.identity);
  const profile = safeObject<Record<string, any>>(data.profile);
  const quality = safeObject<Record<string, any>>(data.target_quality);
  const governedTimeFields = safeArray<any>(data.governed_time_fields);
  const rejectedTimeField = data.rejected_time_field ? safeObject(data.rejected_time_field) : null;
  const target = String(data.target ?? identity.target ?? "");
  const problemType = String(data.problem_type ?? "classification");
  const isClassification = problemType === "classification";

  // --- Governance narrative (durable backend Project Context) ---------------
  const [context, setContext] = useState<ProjectContext | null>(null);
  const [contextState, setContextState] = useState<"loading" | "loaded" | "absent" | "failed">("loading");
  useEffect(() => {
    let cancelled = false;
    if (!projectId) {
      setContextState("absent");
      return () => undefined;
    }
    hydrateProjectContext(projectId)
      .then((result) => {
        if (cancelled) return;
        setContext(result.context);
        setContextState(result.context ? "loaded" : "absent");
      })
      .catch(() => {
        if (!cancelled) setContextState("failed");
      });
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  const governanceFields = useMemo(() => buildTargetGovernanceFields(context), [context]);
  const governanceGaps = useMemo(() => unresolvedGovernanceGaps(governanceFields), [governanceFields]);

  // --- Exact class balance, imbalance tier, confidence interval -------------
  const assessmentRequest = useMemo(
    () =>
      datasetIdentity && target && isClassification
        ? {
            projectId,
            datasetId: datasetIdentity.datasetId,
            versionId: datasetIdentity.versionId,
            target,
            eventValue,
            nonEventValue,
            confidenceLevel: 0.95,
          }
        : null,
    [datasetIdentity, eventValue, nonEventValue, projectId, target, isClassification]
  );
  const assessment = useTargetAssessment(assessmentRequest);

  const distributionRequest = useMemo(
    () =>
      datasetIdentity && target && isClassification
        ? {
            projectId,
            datasetId: datasetIdentity.datasetId,
            versionId: datasetIdentity.versionId,
            target,
            eventValue,
            nonEventValue,
          }
        : null,
    [datasetIdentity, eventValue, nonEventValue, projectId, target, isClassification]
  );
  const serverDistribution = useTargetDistribution(distributionRequest);

  // The chart reads the same exact aggregate. When no registered version exists,
  // it falls back to the Full Governed Population EDA class table -- never to a preview.
  const distribution: TargetDistribution | null = useMemo(() => {
    const rows = serverDistribution.result?.classDistribution;
    if (rows?.length) {
      return buildTargetDistribution({ target, classDistribution: rows, eventValue, nonEventValue });
    }
    const fallback = safeArray<any>(profile.class_distribution).map((row) => ({
      value: row.value,
      count: Number(row.count) || 0,
      percent: Number(row.rate) || 0,
    }));
    return fallback.length ? buildTargetDistribution({ target, classDistribution: fallback, eventValue, nonEventValue }) : null;
  }, [serverDistribution.result, profile.class_distribution, target, eventValue, nonEventValue]);

  // The registered-version aggregate is preferred because it is keyed to an
  // immutable (dataset, version). When the project has no Dataset Library
  // version, the EDA workspace section carries the same figures over the full
  // backend population -- computed by the same shared server functions, so the
  // two paths cannot disagree. Neither path is a browser preview.
  const workspaceAssessment = data.full_population_assessment
    ? safeObject<Record<string, any>>(data.full_population_assessment)
    : null;

  // --- Analysis Scope (Parts A / B / E) ------------------------------------
  //
  // The scope shown is always the SERVER's. A governed state is only claimed
  // once the registered-version response has actually succeeded -- while it is
  // in flight the banner stays amber and says so, so the page never shows a
  // green governed state over a result produced by the draft path.
  const governedScope: AnalysisScope | null = isGovernedScope(assessment.result?.analysisScope)
    ? (assessment.result?.analysisScope as AnalysisScope)
    : null;
  const draftScope: AnalysisScope | null = data.analysis_scope
    ? (safeObject<Record<string, any>>(data.analysis_scope) as unknown as AnalysisScope)
    : null;

  const scopeResolution: ScopeResolution = governedScope
    ? "governed"
    : assessmentRequest && (assessment.phase === "queued" || assessment.phase === "running")
      ? "resolving"
      : assessmentRequest && assessment.phase === "failed"
        ? "failed"
        : "draft";
  const effectiveScope = governedScope ?? draftScope;
  const governed = scopeResolution === "governed";

  // Governed figures come only from the governed response. The draft figures
  // are still shown while resolving (the banner says they are draft), but they
  // are never relabelled as governed.
  const balance = governed
    ? assessment.result?.classBalance ?? null
    : (workspaceAssessment?.classBalance as TargetClassBalance | undefined) ?? null;
  const imbalance = governed
    ? assessment.result?.imbalance ?? null
    : (workspaceAssessment?.imbalance as ImbalanceAssessment | undefined) ?? null;
  const interval = governed
    ? assessment.result?.confidenceInterval ?? null
    : (workspaceAssessment?.confidenceInterval as ConfidenceInterval | undefined) ?? null;
  const assessmentPhase = governed ? assessment.phase : workspaceAssessment ? "ready" : assessment.phase;

  // Reconciliation: when the registered version disagrees materially with the
  // draft it replaced, say so rather than silently swapping the numbers.
  const reconciliation = useMemo(() => {
    const draft = workspaceAssessment?.classBalance as TargetClassBalance | undefined;
    const registered = assessment.result?.classBalance;
    if (!governed || !draft || !registered) return null;
    const differences: string[] = [];
    if (draft.totalModelingPopulation !== registered.totalModelingPopulation) {
      differences.push(
        `Population rows: draft ${formatCount(draft.totalModelingPopulation)}, registered version ${formatCount(registered.totalModelingPopulation)}.`
      );
    }
    if (draft.eventCount !== registered.eventCount || draft.nonEventCount !== registered.nonEventCount) {
      differences.push(
        `Class counts: draft ${formatCount(draft.eventCount)} / ${formatCount(draft.nonEventCount)}, registered version ${formatCount(registered.eventCount)} / ${formatCount(registered.nonEventCount)}.`
      );
    }
    const draftRate = draft.eventRate ?? 0;
    const registeredRate = registered.eventRate ?? 0;
    if (Math.abs(draftRate - registeredRate) > 1e-9) {
      differences.push(`Event rate: draft ${formatEventRate(draftRate)}, registered version ${formatEventRate(registeredRate)}.`);
    }
    if (String(draft.eventValue ?? "") !== String(registered.eventValue ?? "")) {
      differences.push(
        `Positive value mapping: draft "${draft.eventValue ?? "none"}", registered version "${registered.eventValue ?? "none"}".`
      );
    }
    return differences.length ? differences : null;
  }, [governed, workspaceAssessment, assessment.result]);

  function goToRegistration() {
    // The existing Data Acquisition flow owns registration and version linking.
    // EDA never implements a second registration system.
    window.location.assign("/step01");
  }

  // --- On-demand target by predictor ---------------------------------------
  const predictorAnalysis = useTargetByPredictor();
  const predictorExplorerRef = useRef<HTMLDivElement>(null);
  const [requestedPredictor, setRequestedPredictor] = useState("");
  const predictorPreview = data.predictor_preview
    ? (safeObject<Record<string, any>>(data.predictor_preview) as TargetPredictorPreviewPayload)
    : null;

  function runPredictorAnalysis(input: {
    predictor: string;
    analysisType: "numeric_quantile" | "categorical";
    bands: number;
    includeMissing: boolean;
  }) {
    predictorAnalysis.run({
      projectId,
      datasetId: governed ? governedScope?.datasetId ?? "" : "",
      versionId: governed ? governedScope?.datasetVersionId ?? "" : "",
      workspaceFingerprint: governed ? null : draftScope?.datasetFingerprint ?? null,
      target,
      predictor: input.predictor,
      analysisType: input.analysisType,
      eventValue,
      bands: input.bands,
      includeMissing: input.includeMissing,
    });
  }

  function inspectPreviewPredictor(row: TargetPredictorPreviewRow) {
    setRequestedPredictor(row.feature);
    runPredictorAnalysis({
      predictor: row.feature,
      analysisType: row.kind === "numeric" ? "numeric_quantile" : "categorical",
      bands: Math.max(2, Math.min(10, row.groups.length || 8)),
      includeMissing: true,
    });
    window.requestAnimationFrame(() => {
      predictorExplorerRef.current?.scrollIntoView({
        behavior: reducedMotion ? "auto" : "smooth",
        block: "start",
      });
    });
  }

  // --- Durable findings -----------------------------------------------------
  // Findings follow the resolved scope: a governed query names the exact
  // version, a draft query names the exact workspace fingerprint. Neither can
  // return the other's rows, so a draft finding written against one uploaded
  // file cannot appear after a different file is loaded.
  const findingsScope = useMemo(() => {
    if (!projectId) return null;
    if (governed && governedScope) {
      return {
        projectId,
        scopeMode: "governed_version" as const,
        datasetId: governedScope.datasetId ?? "",
        versionId: governedScope.datasetVersionId ?? "",
        target,
      };
    }
    return {
      projectId,
      scopeMode: "workspace_draft" as const,
      workspaceFingerprint: draftScope?.datasetFingerprint ?? null,
      target,
    };
  }, [projectId, governed, governedScope, draftScope?.datasetFingerprint, target]);
  const findingsState = useTargetFindings(findingsScope);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");
  const [evidenceId, setEvidenceId] = useState<string | null>(null);

  const chartSpecificationRef = useRef<Record<string, unknown>>({});
  chartSpecificationRef.current = {
    classBalanceChart: { library: "echarts", type: "bar", modes: ["population", "rare-event"] },
    targetByPredictorChart: predictorAnalysis.result
      ? {
          library: "echarts",
          type: "bar+line",
          predictor: predictorAnalysis.result.predictor,
          analysisType: predictorAnalysis.result.analysisType,
          groups: predictorAnalysis.result.rows.length,
        }
      : null,
  };

  async function handleCreateFinding(input: { title: string; detail: string; severity: TargetFinding["severity"] }) {
    if (!projectId) {
      setMessage("No active project is selected.");
      return;
    }
    setSaving(true);
    setMessage("Saving target finding...");
    try {
      const finding = await createTargetFinding({
        projectId,
        // Governed identity is only offered when the server has already
        // confirmed governed scope. Otherwise this is a draft finding pinned to
        // the workspace fingerprint -- never a governed row with blank identity.
        datasetId: governed ? governedScope?.datasetId ?? "" : "",
        versionId: governed ? governedScope?.datasetVersionId ?? "" : "",
        workspaceFingerprint: governed ? null : draftScope?.datasetFingerprint ?? null,
        target,
        analysisType: predictorAnalysis.result ? `target_by_${predictorAnalysis.result.analysisType}` : "target_intelligence",
        title: input.title,
        detail: input.detail,
        severity: input.severity,
        metadata: {
          eventRate: balance?.eventRate ?? null,
          imbalanceLabel: imbalance?.label ?? null,
          confidenceInterval: interval,
          selectedPredictor: predictorAnalysis.result?.predictor ?? null,
        },
      });
      findingsState.apply(finding);
      setMessage("Target finding saved.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "The target finding could not be saved.");
    } finally {
      setSaving(false);
    }
  }

  async function handleUpdateFinding(
    findingId: string,
    input: { title?: string; detail?: string; severity?: TargetFinding["severity"]; status?: TargetFinding["status"] }
  ) {
    setSaving(true);
    try {
      const finding = await updateTargetFinding(findingId, { projectId, ...input });
      findingsState.apply(finding);
      setMessage("Target finding updated.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "The target finding could not be updated.");
    } finally {
      setSaving(false);
    }
  }

  const evidencePayload = () =>
    buildTargetEvidencePayload({
      projectId,
      datasetId: governed ? governedScope?.datasetId ?? "" : "",
      versionId: governed ? governedScope?.datasetVersionId ?? "" : "",
      datasetName: effectiveScope?.datasetName ?? datasetIdentity?.datasetName ?? "",
      target,
      scope: effectiveScope,
      assessment: assessment.result,
      governance: governanceFields,
      predictorAnalysis: predictorAnalysis.result,
      timeField,
      segmentField,
      chartSpecification: chartSpecificationRef.current,
      userId: getCachedUserId() || "anonymous",
      capturedAt: new Date().toISOString(),
    });

  /**
   * Governed evidence is created by the SERVER.
   *
   * The previous implementation called the generic `createEvidence` with
   * browser-asserted provenance -- the browser supplied the dataset id, the
   * version, the counts, and the eligibility. This now posts only the
   * analytical SELECTION to a dedicated command that re-resolves authorization,
   * the version, the artifact, and every figure before writing anything.
   */
  async function handleSaveEvidence() {
    if (!governed || !governedScope?.datasetId || !governedScope?.datasetVersionId) {
      setMessage(
        evidenceDisabledReason(effectiveScope, scopeResolution === "resolving") ??
          "This analysis is not eligible for governed evidence."
      );
      return;
    }
    setSaving(true);
    setMessage("Saving governed target analysis to evidence...");
    try {
      const result = await saveGovernedTargetEvidence({
        projectId,
        datasetId: governedScope.datasetId,
        versionId: governedScope.datasetVersionId,
        target,
        eventValue,
        nonEventValue,
        predictor: predictorAnalysis.result?.predictor ?? null,
        predictorAnalysisType: predictorAnalysis.result?.analysisType ?? null,
        timeField: timeField || null,
        segmentField: segmentField || null,
        chartSpecification: chartSpecificationRef.current,
        title: `Target Intelligence -- ${target} @ ${governedScope.datasetVersionId}`,
      });
      setEvidenceId(result.evidenceId);
      setMessage(
        `Governed evidence saved: ${result.evidenceId} (version ${result.analysisScope.datasetVersionId}, ${result.mddEligible ? "MDD eligible" : "not MDD eligible"}).`
      );
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Governed target evidence could not be saved.");
    } finally {
      setSaving(false);
    }
  }

  async function handlePromoteFinding(findingId: string) {
    if (!governed || !governedScope?.datasetId || !governedScope?.datasetVersionId) return;
    setSaving(true);
    try {
      const finding = await promoteTargetFinding(findingId, {
        projectId,
        datasetId: governedScope.datasetId,
        versionId: governedScope.datasetVersionId,
      });
      findingsState.apply(finding);
      setMessage(`Draft finding copied to governed version ${governedScope.datasetVersionId}. The draft record is unchanged.`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "The finding could not be carried forward.");
    } finally {
      setSaving(false);
    }
  }

  /** Part H: a draft summary may be downloaded, but the file and its filename
   *  make its status unmistakable -- it must never look like an approved artifact. */
  function handleExportSummary() {
    const blob = new Blob([JSON.stringify(evidencePayload(), null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = governed
      ? `governed-target-intelligence-${target || "target"}-${governedScope?.datasetVersionId ?? "version"}.json`
      : `WORKSPACE-DRAFT-not-governed-evidence-target-${target || "target"}.json`;
    link.click();
    URL.revokeObjectURL(url);
    setMessage(
      governed
        ? "Governed bounded summary exported."
        : "Workspace Draft summary exported. It is marked Not Governed Evidence, Not Version-Pinned, and Not MDD Eligible."
    );
  }

  const timeRows = safeArray<any>(data.event_rate_by_time);
  const segmentRows = safeArray<any>(data.target_by_segment);
  const timeStability = data.time_stability ? safeObject(data.time_stability) : null;

  return (
    <div
      className="space-y-4"
      data-testid="target-intelligence-workspace"
      data-reduced-motion={reducedMotion ? "true" : "false"}
      data-scope-mode={governed ? "governed_version" : "workspace_draft"}
    >
      {/* Analysis Scope -- persistent, above every section it governs. */}
      <AnalysisScopeBanner
        resolution={scopeResolution}
        scope={effectiveScope}
        error={assessment.error}
        onRegister={goToRegistration}
        onRetry={assessment.retry}
        reconciliation={reconciliation}
      />

      {/* 1 -------------------------------------------------------------- */}
      <TargetIdentitySection
        identity={identity}
        target={target}
        problemType={problemType}
        targetSourceExcluded={safeArray<string>(data.target_source_excluded)}
        datasetIdentity={datasetIdentity}
        datasetVersionFallback={String(data.dataset_version ?? "")}
        governanceFields={governanceFields}
        governanceGaps={governanceGaps}
        contextState={contextState}
      />

      {/* 2 -------------------------------------------------------------- */}
      <div
        className="eda-target-story"
        data-testid="target-prevalence-story"
      >
      <AtlasWorkflowSection
        eyebrow="Section 2"
        title="Class Balance and Prevalence"
        description="Exact class counts and prevalence from the Full Governed Population. Preview row limits and browser sampling do not affect these structural figures."
        tone="info"
      >
        <div data-testid="target-class-balance">
          {isClassification ? (
            <>
              <TargetBalanceConfidenceVisual
                balance={balance}
                interval={interval}
                reducedMotion={reducedMotion}
              />
              <div className="mt-4">
                <TargetDistributionPanel
                  distribution={distribution}
                  showMetricCards={false}
                  state={
                    serverDistribution.phase === "queued" || serverDistribution.phase === "running"
                      ? "loading"
                      : serverDistribution.phase === "failed"
                        ? "error"
                        : distribution
                          ? "ready"
                          : "empty"
                  }
                  scopeLabel={
                    balance?.resolution === "sampled"
                      ? "stratified sample of the registered dataset"
                      : "full registered population"
                  }
                  query={{
                    phase: serverDistribution.phase,
                    elapsedMs: serverDistribution.elapsedMs,
                    error: serverDistribution.error,
                    sampling: serverDistribution.result?.sampling,
                    retry: serverDistribution.retry,
                    calculateExact: serverDistribution.calculateExact,
                  }}
                />
              </div>
            </>
          ) : (
            <p className="text-sm text-slate-700">
              This is a regression target. Class balance does not apply; review the target distribution, extreme-value
              prevalence, and missingness in the sections below.
            </p>
          )}
        </div>
      </AtlasWorkflowSection>
      </div>

      {/* 3 -------------------------------------------------------------- */}
      <TargetQualityDiagnostic
        quality={quality}
        identity={identity}
        targetSourceExcluded={safeArray<string>(data.target_source_excluded)}
      />

      {/* 4 -------------------------------------------------------------- */}
      {isClassification ? (
        <TargetPredictorPreview
          preview={predictorPreview}
          target={target}
          targetSourceExcluded={safeArray<string>(data.target_source_excluded)}
          reducedMotion={reducedMotion}
          onInspect={inspectPreviewPredictor}
        />
      ) : null}

      {/* 5 -------------------------------------------------------------- */}
      <div ref={predictorExplorerRef} data-testid="target-predictor-explorer-anchor">
        <AtlasWorkflowSection
          eyebrow="Section 5"
          title="Target by Predictor"
          description="On-demand only. Choose a predictor and run the analysis; ATLAS computes target-directed bands, category rates, and class summaries on the exact Development Population and returns bounded grouped rows."
          tone="neutral"
        >
          <TargetByPredictorPanel
            predictors={predictorOptions}
            requestedPredictor={requestedPredictor}
            state={predictorAnalysis}
            disabledReason={
              !isClassification ? "Target-by-predictor event rates apply to classification targets." : undefined
            }
            scopeNotice={
              governed
                ? "Development Population. Target-directed bands, category rates, class box plots, and summaries use the current development partition. The sealed final holdout is excluded."
                : "Workspace Draft Analysis. Target-directed results use the available development partition, but the source is not an immutable registered artifact. The result is not version-pinned and is not eligible for governed evidence."
            }
            onRun={runPredictorAnalysis}
            onReset={() => {
              setRequestedPredictor("");
              predictorAnalysis.reset();
            }}
          />
        </AtlasWorkflowSection>
      </div>

      {/* Detailed prevalence guidance follows the visual context. */}
      {isClassification ? (
        <div
          className="eda-target-guidance"
          data-testid="target-uncertainty-guidance"
        >
          <RareEventSection imbalance={imbalance} phase={assessmentPhase} />
        </div>
      ) : null}

      {/* 6 -------------------------------------------------------------- */}
      <TimeAndSegmentSection
        governedTimeFields={governedTimeFields}
        rejectedTimeField={rejectedTimeField}
        timeField={timeField}
        segmentField={segmentField}
        segmentCandidates={segmentCandidates}
        timeRows={timeRows}
        segmentRows={segmentRows}
        timeStability={timeStability}
        segmentMissingCount={Number(data.segment_missing_count ?? 0)}
        reducedMotion={reducedMotion}
        onTimeField={onTimeField}
        onSegmentField={onSegmentField}
        onRun={onRunConditional}
      />

      {/* 7 -------------------------------------------------------------- */}
      <TargetQualitySection quality={quality} governanceGaps={governanceGaps} />

      {/* 8 -------------------------------------------------------------- */}
      <AtlasWorkflowSection
        eyebrow="Section 8"
        title="Target Findings and Evidence"
        description="Findings are stored durably against this project, dataset version, and target. Evidence carries a bounded analytical summary, never population data."
        tone="neutral"
      >
        <TargetFindingsPanel
          findings={findingsState.findings}
          legacyFindings={findingsState.legacyFindings}
          loading={findingsState.loading}
          error={findingsState.error}
          governed={governed}
          scopeLabel={
            governed
              ? `${target || "this target"} on governed version ${governedScope?.datasetVersionId}`
              : `${target || "this target"} on the current workspace dataset (draft, not version-pinned)`
          }
          saving={saving}
          message={message}
          evidenceId={evidenceId}
          evidenceDisabledReason={
            !projectId
              ? "No active project is selected."
              : evidenceDisabledReason(effectiveScope, scopeResolution === "resolving") ?? undefined
          }
          onCreate={handleCreateFinding}
          onUpdate={handleUpdateFinding}
          onPromote={handlePromoteFinding}
          onSaveEvidence={() => void handleSaveEvidence()}
          onExportSummary={handleExportSummary}
          onRegister={goToRegistration}
        />
      </AtlasWorkflowSection>
    </div>
  );
}

function TargetPrevalenceRing({
  eventRate,
  eventCount,
  totalCount,
}: {
  eventRate: number | null;
  eventCount: number | null;
  totalCount: number | null;
}) {
  const normalizedRate =
    typeof eventRate === "number" && Number.isFinite(eventRate)
      ? Math.max(0, Math.min(1, eventRate))
      : 0;
  return (
    <div className="flex flex-col items-center text-center" data-testid="target-prevalence-ring">
      <div
        className="eda-prevalence-ring grid h-44 w-44 place-items-center rounded-full"
        style={{
          background: `conic-gradient(#e11d48 ${normalizedRate * 360}deg, #dbeafe 0deg)`,
        }}
        role="img"
        aria-label={`Configured event prevalence ${formatEventRate(eventRate)}`}
      >
        <div className="grid h-36 w-36 place-items-center rounded-full bg-white">
          <div>
            <div
              className="text-3xl font-bold tabular-nums text-slate-950"
              data-testid="target-event-rate"
            >
              {formatEventRate(eventRate)}
            </div>
            <div className="text-[10px] font-bold uppercase tracking-[0.12em] text-slate-500">
              Event prevalence
            </div>
          </div>
        </div>
      </div>
      <p className="mt-3 text-xs leading-5 text-slate-600">
        <span className="font-semibold tabular-nums" data-testid="target-event-count">
          {formatCount(eventCount)}
        </span>{" "}
        configured events across{" "}
        <span className="font-semibold tabular-nums" data-testid="target-total-population">
          {formatCount(totalCount)}
        </span>{" "}
        modeled rows.
      </p>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Section 1 -- Target Identity (Part C)
// ---------------------------------------------------------------------------

function TargetIdentitySection({
  identity,
  target,
  problemType,
  targetSourceExcluded,
  datasetIdentity,
  datasetVersionFallback,
  governanceFields,
  governanceGaps,
  contextState,
}: {
  identity: Record<string, any>;
  target: string;
  problemType: string;
  targetSourceExcluded: string[];
  datasetIdentity: DatasetIdentity | null;
  datasetVersionFallback: string;
  governanceFields: GovernanceField[];
  governanceGaps: GovernanceField[];
  contextState: "loading" | "loaded" | "absent" | "failed";
}) {
  // Part J: the full governance narrative is NOT repeated here. Project Context
  // and the backend project record remain its authoritative home; this page
  // links to it instead of restating target/population/observation/performance
  // definitions that the reviewer has already read there.
  const recordedDefinitions = governanceFields.filter((field) => field.present).length;
  const positiveValue =
    identity.positive_value === null || identity.positive_value === undefined
      ? "Not defined"
      : String(identity.positive_value);
  const negativeValue =
    identity.negative_value === null || identity.negative_value === undefined
      ? "Not defined"
      : String(identity.negative_value);
  const sourceLabel =
    targetSourceExcluded.find((field) => field === "RiskPerformance") ??
    targetSourceExcluded[0] ??
    "Configured outcome source";
  const helocLineage =
    target === "bad_flag" &&
    targetSourceExcluded.some((field) => field === "RiskPerformance");

  return (
    <section className="eda-section-band overflow-hidden" data-testid="target-identity">
      <div className="border-b border-blue-100 bg-blue-50/80 p-5">
      <div className="text-[11px] font-bold uppercase tracking-wide text-blue-700">Section 1</div>
      <h2 className="mt-1 flex items-center gap-2 text-xl font-bold text-blue-950">
        <TargetIcon size={17} /> Target Identity
      </h2>
      <p className="mt-1 text-sm text-slate-700">
        What the target is, and which immutable dataset version it was measured on.
      </p>
      </div>

      <div
        className="grid gap-3 border-b border-slate-200 bg-white px-5 py-4 md:grid-cols-[minmax(150px,1fr)_auto_minmax(110px,0.75fr)_auto_minmax(110px,0.75fr)_auto_minmax(130px,0.9fr)] md:items-center"
        data-testid="target-governed-lineage"
        role="img"
        aria-label={`Target lineage: ${sourceLabel} to ${helocLineage ? "Bad" : "Event"} equals ${positiveValue}, ${helocLineage ? "Good" : "Non-event"} equals ${negativeValue}, to ${target}. The source is excluded from predictors.`}
      >
        <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2" data-lineage-step="source">
          <div className="text-[10px] font-bold uppercase tracking-[0.12em] text-slate-500">
            Deterministic source
          </div>
          <div className="mt-1 break-words font-semibold text-slate-900">{sourceLabel}</div>
        </div>
        <ArrowRight className="hidden text-slate-400 md:block" size={18} aria-hidden="true" />
        <div className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2" data-lineage-step="event-mapping">
          <div className="text-[10px] font-bold uppercase tracking-[0.12em] text-slate-500">
            Event mapping
          </div>
          <div className="mt-1 break-words font-bold text-rose-800">
            {helocLineage ? "Bad" : "Event"} = {positiveValue}
          </div>
        </div>
        <ArrowRight className="hidden text-slate-400 md:block" size={18} aria-hidden="true" />
        <div className="rounded-lg border border-blue-200 bg-blue-50 px-3 py-2" data-lineage-step="non-event-mapping">
          <div className="text-[10px] font-bold uppercase tracking-[0.12em] text-slate-500">
            Non-event mapping
          </div>
          <div className="mt-1 break-words font-bold text-blue-800">
            {helocLineage ? "Good" : "Non-event"} = {negativeValue}
          </div>
        </div>
        <ArrowRight className="hidden text-slate-400 md:block" size={18} aria-hidden="true" />
        <div className="rounded-lg border border-indigo-200 bg-indigo-50 px-3 py-2" data-lineage-step="modeled-target">
          <div className="text-[10px] font-bold uppercase tracking-[0.12em] text-slate-500">
            Modeling target
          </div>
          <div className="mt-1 break-words font-bold text-indigo-900">{target}</div>
          <div className="mt-1 text-[10px] font-semibold uppercase tracking-wide text-teal-700">
            Source excluded
          </div>
        </div>
      </div>

      <div className="eda-metric-rail grid gap-3 px-5 py-4 sm:grid-cols-2 xl:grid-cols-4">
        <Metric label="Target column" value={target || "Not selected"} testId="target-identity-column" />
        <Metric label="Target data type" value={String(identity.data_type ?? "Not evaluated")} />
        <Metric label="Problem type" value={problemType === "classification" ? "Classification" : "Regression"} />
        <Metric label="Distinct values" value={formatCount(identity.distinct_value_count)} />
        <Metric label="Positive value" value={positiveValue} testId="target-positive-value" />
        <Metric label="Negative value" value={negativeValue} />
        <Metric label="Missing target" value={formatCount(identity.missing_target_count)} testId="target-identity-missing" />
        <Metric label="Population rows" value={formatCount(identity.population_row_count)} testId="target-identity-rows" />
        <Metric label="Dataset name" value={datasetIdentity?.datasetName || "Not registered"} />
        <Metric label="Dataset ID" value={datasetIdentity?.datasetId || "Not registered"} testId="target-identity-dataset-id" />
        <Metric label="Dataset version" value={datasetIdentity?.versionId || datasetVersionFallback || "Unversioned"} testId="target-identity-version" />
        <Metric label="Modeling population" value={formatCount(identity.modeling_population_row_count)} />
      </div>

      {/* Compact, keyboard-accessible pointer to the authoritative narrative. */}
      <div className="flex flex-wrap items-center gap-3 border-t border-blue-100 bg-blue-50/50 px-5 py-3">
        <span className="text-xs text-slate-600" data-testid="target-project-context-summary">
          {contextState === "loading"
            ? "Loading Project Context..."
            : contextState === "failed"
              ? "Project Context could not be loaded."
              : `Business target, population, observation, and performance definitions are recorded in Project Context (${recordedDefinitions} field(s) recorded).`}
        </span>
        <a
          href="/step00"
          className="atlas-secondary-button text-xs"
          data-testid="target-view-project-context"
        >
          View Project Context
        </a>
      </div>
    </section>
  );
}

// ---------------------------------------------------------------------------
// Section 3 -- Rare-Event Assessment (Part E)
// ---------------------------------------------------------------------------

function RareEventSection({ imbalance, phase }: { imbalance: ImbalanceAssessment | null; phase: string }) {
  // Tone follows the CONFIGURED event's prevalence, not the minority share, so
  // a common event does not get an alarming treatment merely because the
  // classes happen to be uneven.
  const tone = IMBALANCE_TONES[imbalance?.eventPrevalence?.severity ?? imbalance?.severity ?? "unknown"];
  const warning = tone === "warning" || tone === "danger";
  return (
    <section
      className={`rounded-xl border-2 p-5 shadow-sm ${warning ? "border-amber-300 bg-amber-50" : "border-slate-200 bg-white"}`}
      data-testid="target-rare-event-assessment"
      data-imbalance-severity={imbalance?.severity ?? "unknown"}
    >
      <div className={`text-[11px] font-bold uppercase tracking-wide ${warning ? "text-amber-700" : "text-slate-500"}`}>Section 3</div>
      <h2 className="mt-1 flex items-center gap-2 text-base font-semibold text-slate-900">
        <Layers size={17} /> Rare-Event Assessment
      </h2>

      {!imbalance ? (
        <p className="mt-2 text-sm text-slate-600">
          {phase === "failed" ? "The prevalence assessment is unavailable." : "Calculating the prevalence assessment..."}
        </p>
      ) : (
        <>
          {/* Two independent statements. The headline describes the CONFIGURED
              event; the second describes how uneven the classes are. Conflating
              them is what made a majority-class event read as "rare". */}
          <div className="mt-3 flex flex-wrap items-center gap-3">
            <span
              className={`rounded-full px-3 py-1 text-sm font-bold ${warning ? "bg-amber-200 text-amber-950" : "bg-slate-100 text-slate-800"}`}
              data-testid="target-prevalence-label"
            >
              Event prevalence: {imbalance.eventPrevalence?.label ?? imbalance.label}
            </span>
            <span
              className="rounded-full bg-slate-100 px-3 py-1 text-sm font-bold text-slate-800"
              data-testid="target-imbalance-label"
            >
              Class imbalance: {imbalance.classImbalance?.label ?? "Not evaluated"}
            </span>
          </div>

          <dl className="mt-3 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <Metric label="Event rate" value={formatEventRate(imbalance.eventPrevalence?.eventRate)} testId="prevalence-event-rate" />
            <Metric
              label="Non-events per event"
              value={formatRatio(imbalance.nonEventsPerEvent)}
              testId="ratio-non-events-per-event"
            />
            <Metric
              label="Majority-to-minority ratio"
              value={formatRatio(imbalance.majorityToMinorityRatio)}
              testId="ratio-majority-to-minority"
            />
            <Metric
              label="Minority class"
              value={
                imbalance.classImbalance?.minorityClass === "event"
                  ? `Event (${formatEventRate(imbalance.minorityShare)})`
                  : imbalance.classImbalance?.minorityClass === "non_event"
                    ? `Non-event (${formatEventRate(imbalance.minorityShare)})`
                    : "Not available"
              }
              testId="minority-class"
            />
          </dl>

          {imbalance.eventIsMajority ? (
            <p
              className="mt-3 rounded-lg border border-amber-300 bg-white px-3 py-2 text-sm text-amber-950"
              data-testid="target-event-is-majority"
            >
              The configured event is the <strong>majority</strong> class, so the <strong>non-event</strong> class is the
              minority class here. This is not a rare-event condition for the configured positive value.
            </p>
          ) : null}
          {imbalance.singleClass ? (
            <p className="mt-3 rounded-lg border border-red-300 bg-white px-3 py-2 text-sm text-red-900" data-testid="target-single-class">
              Only one class is present in the non-missing target, so no prevalence tier is claimed and no
              classification model can be trained on the target as currently defined.
            </p>
          ) : null}

          <p className="mt-2 text-xs text-slate-600" data-testid="target-imbalance-rule">{imbalance.rule}</p>
          <p className="mt-1 text-xs text-slate-500" data-testid="target-ratio-orientation">
            Ratio orientation: {imbalance.ratioOrientation ?? "non-events per event"}. The majority-to-minority ratio is
            independent of which class is configured as the positive value.
          </p>

          <ul className="mt-3 list-disc space-y-1 pl-5 text-sm text-slate-800" data-testid="target-imbalance-implications">
            {(imbalance.implications ?? []).map((item: string) => (
              <li key={item}>{item}</li>
            ))}
          </ul>

          <p className="mt-3 rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs text-slate-700" data-testid="target-no-automatic-treatment">
            <Info size={13} className="mr-1 inline" />
            This section is analytical guidance, not treatment. ATLAS has not enabled SMOTE, set class weights,
            undersampled, or chosen a threshold. Compare treatment alternatives on the Balancing and Split step.
          </p>

          <details className="mt-3">
            <summary className="cursor-pointer text-xs font-semibold text-slate-700">Assessment thresholds</summary>
            <div className="mt-2 grid gap-3 sm:grid-cols-2">
              <ul className="space-y-1 text-xs text-slate-600" data-testid="target-prevalence-thresholds">
                <li className="font-semibold text-slate-700">Event prevalence (on the event rate)</li>
                {(imbalance.prevalenceThresholds ?? []).map((rule: { label: string; minEventRate: number }) => (
                  <li key={rule.label}>
                    Event rate at or above {(rule.minEventRate * 100).toFixed(0)}% - {rule.label}
                  </li>
                ))}
              </ul>
              <ul className="space-y-1 text-xs text-slate-600" data-testid="target-imbalance-thresholds">
                <li className="font-semibold text-slate-700">Class imbalance (on the minority share)</li>
                {(imbalance.thresholds ?? []).map((rule: { label: string; minMinorityShare: number }) => (
                  <li key={rule.label}>
                    Minority share at or above {(rule.minMinorityShare * 100).toFixed(0)}% - {rule.label}
                  </li>
                ))}
              </ul>
            </div>
          </details>
        </>
      )}
    </section>
  );
}

// ---------------------------------------------------------------------------
// Section 4 -- Event-Rate Uncertainty (Part F)
// ---------------------------------------------------------------------------

function ConfidenceIntervalSection({
  interval,
  phase,
  error,
  onRetry,
}: {
  interval: ConfidenceInterval | null;
  phase: string;
  error: string | null;
  onRetry: () => void;
}) {
  return (
    <AtlasWorkflowSection
      eyebrow="Section 4"
      title="Event-Rate Uncertainty"
      description="How precisely the observed prevalence is measured on this population."
      tone="neutral"
    >
      <div data-testid="target-confidence-interval">
        {phase === "failed" ? (
          <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-900">
            <p>{error ?? "The confidence interval could not be calculated."}</p>
            <button type="button" className="atlas-secondary-button mt-2" onClick={onRetry}>
              Retry
            </button>
          </div>
        ) : !interval || interval.pointEstimate === null ? (
          <p className="text-sm text-slate-600">Calculating the event-rate confidence interval...</p>
        ) : (
          <>
            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
              <Metric label="Point estimate" value={formatEventRate(interval.pointEstimate)} testId="ci-point-estimate" />
              <Metric label="Lower bound" value={formatEventRate(interval.lowerBound)} testId="ci-lower-bound" />
              <Metric label="Upper bound" value={formatEventRate(interval.upperBound)} testId="ci-upper-bound" />
              <Metric label="Confidence level" value={`${(interval.confidenceLevel * 100).toFixed(0)}%`} testId="ci-confidence-level" />
              <Metric label="Method" value={interval.method} testId="ci-method" />
              <Metric label="Event count" value={formatCount(interval.eventCount)} />
              <Metric label="Total count" value={formatCount(interval.totalCount)} />
              <Metric label="Half width" value={formatEventRate(interval.halfWidth)} />
            </div>
            <p className="mt-3 rounded-lg border border-teal-200 bg-teal-50 px-3 py-2 text-sm text-teal-950" data-testid="ci-explanation">
              {interval.explanation}
            </p>
            <p className="sr-only" data-testid="ci-summary">{describeConfidenceInterval(interval, formatEventRate)}</p>
          </>
        )}
      </div>
    </AtlasWorkflowSection>
  );
}

// ---------------------------------------------------------------------------
// Section 6 -- Time and Segment Stability (Part H)
// ---------------------------------------------------------------------------

function TimeAndSegmentSection({
  governedTimeFields,
  rejectedTimeField,
  timeField,
  segmentField,
  segmentCandidates,
  timeRows,
  segmentRows,
  timeStability,
  segmentMissingCount,
  reducedMotion,
  onTimeField,
  onSegmentField,
  onRun,
}: {
  governedTimeFields: any[];
  rejectedTimeField: Record<string, any> | null;
  timeField: string;
  segmentField: string;
  segmentCandidates: string[];
  timeRows: any[];
  segmentRows: any[];
  timeStability: Record<string, any> | null;
  segmentMissingCount: number;
  reducedMotion: boolean;
  onTimeField: (value: string) => void;
  onSegmentField: (value: string) => void;
  onRun: () => void;
}) {
  const developmentEventRate = useMemo(() => {
    const sourceRows = timeRows.length ? timeRows : segmentRows;
    const count = sourceRows.reduce((total, row) => total + (Number(row.count) || 0), 0);
    const events = sourceRows.reduce((total, row) => total + (Number(row.events) || 0), 0);
    return count > 0 ? events / count : null;
  }, [segmentRows, timeRows]);
  const timeOption = useMemo<EChartsOption | null>(() => {
    if (!timeRows.length) return null;
    return {
      animation: !reducedMotion,
      animationDuration: reducedMotion ? 0 : 320,
      grid: { left: 8, right: 16, top: 34, bottom: 8, containLabel: true },
      legend: { top: 0, data: ["Development rows", "Event count", "Event rate"] },
      tooltip: { trigger: "axis" },
      xAxis: { type: "category", data: timeRows.map((row) => String(row.group)) },
      yAxis: [
        { type: "value", name: "Rows / events" },
        { type: "value", name: "Event rate", splitLine: { show: false }, axisLabel: { formatter: (value: number) => formatEventRate(value) } },
      ],
      series: [
        { name: "Development rows", type: "bar", data: timeRows.map((row) => Number(row.count) || 0), itemStyle: { color: "#cbd5e1" } },
        { name: "Event count", type: "bar", data: timeRows.map((row) => Number(row.events) || 0), itemStyle: { color: "#1d4ed8" } },
        {
          name: "Event rate",
          type: "line",
          yAxisIndex: 1,
          symbol: "circle",
          data: timeRows.map((row) => Number(row.event_rate) || 0),
          lineStyle: { color: "#b91c1c", width: 2 },
          itemStyle: { color: "#b91c1c" },
          markLine: developmentEventRate
            ? { silent: true, symbol: "none", lineStyle: { color: "#0f766e", type: "dashed" }, data: [{ yAxis: developmentEventRate }] }
            : undefined,
        },
      ],
    };
  }, [timeRows, reducedMotion, developmentEventRate]);

  const segmentOption = useMemo<EChartsOption | null>(() => {
    if (!segmentRows.length) return null;
    return {
      animation: !reducedMotion,
      animationDuration: reducedMotion ? 0 : 320,
      grid: { left: 8, right: 16, top: 12, bottom: 8, containLabel: true },
      tooltip: { trigger: "axis", axisPointer: { type: "shadow" } },
      xAxis: { type: "category", data: segmentRows.map((row) => String(row.group)), axisLabel: { interval: 0, rotate: segmentRows.length > 6 ? 35 : 0, fontSize: 11 } },
      yAxis: { type: "value", name: "Event rate", axisLabel: { formatter: (value: number) => formatEventRate(value) } },
      series: [
        {
          type: "bar",
          barMaxWidth: 46,
          data: segmentRows.map((row) => ({
            value: Number(row.event_rate) || 0,
            itemStyle: { color: row.small_segment ? "#b45309" : "#b91c1c", opacity: row.small_segment ? 0.6 : 1, borderRadius: [4, 4, 0, 0] },
          })),
          markLine: developmentEventRate
            ? {
                silent: true,
                symbol: "none",
                lineStyle: { color: "#0f766e", type: "dashed" },
                label: { formatter: `Development ${formatEventRate(developmentEventRate)}`, fontSize: 10, color: "#0f766e" },
                data: [{ yAxis: developmentEventRate }],
              }
            : undefined,
        },
      ],
    };
  }, [segmentRows, reducedMotion, developmentEventRate]);

  return (
    <AtlasWorkflowSection
      eyebrow="Section 6"
      title="Time and Segment Stability"
      description="Development Population target-directed analysis; the sealed final holdout is excluded. ATLAS never infers that an arbitrary numeric field is a date or renders an empty chart shell before a field is selected."
      tone="neutral"
    >
      <div className="grid gap-4 xl:grid-cols-2">
        {/* TIME */}
        <div className="rounded-lg border border-slate-200 bg-white p-4" data-testid="target-time-analysis">
          <h3 className="flex items-center gap-2 text-sm font-semibold text-slate-900">
            <Clock size={15} /> Target over time
          </h3>
          {!governedTimeFields.length ? (
            <div className="mt-3" data-testid="target-no-governed-time-field">
              <p className="text-sm text-slate-700">No governed time field has been selected.</p>
              <p className="mt-1 text-xs text-slate-600">
                This dataset contains no field that qualifies as a governed time field: a real date/datetime column, or a
                date-named text column that parses as dates. Numeric fields are never inferred as dates.
              </p>
              <button type="button" className="atlas-secondary-button mt-2" disabled data-testid="target-select-time-field">
                Select a Time Field
              </button>
            </div>
          ) : (
            <div className="mt-3">
              <label className="block text-[11px] font-semibold uppercase tracking-wide text-slate-500">Governed time field</label>
              <div className="mt-1 flex gap-2">
                <select
                  value={timeField}
                  onChange={(event) => onTimeField(event.target.value)}
                  data-testid="target-time-field-select"
                  className="w-full rounded-lg border border-slate-300 px-2 py-1.5 text-sm"
                >
                  <option value="">No governed time field selected</option>
                  {governedTimeFields.map((field) => (
                    <option key={field.field} value={field.field}>
                      {field.field} ({field.minimum} to {field.maximum})
                    </option>
                  ))}
                </select>
                <button type="button" className="atlas-secondary-button" onClick={onRun} data-testid="target-select-time-field">
                  Select a Time Field
                </button>
              </div>
              {!timeField ? (
                <p className="mt-3 text-sm text-slate-700" data-testid="target-no-governed-time-field">
                  No governed time field has been selected.
                </p>
              ) : !timeRows.length ? (
                <p className="mt-3 text-sm text-slate-600">Run the analysis to evaluate event-rate movement over {timeField}.</p>
              ) : (
                <>
                  <div className="mt-3">
                    <EChartsPanel
                      option={timeOption}
                      state={(timeOption ? "ready" : "empty") as EChartsPanelState}
                      height={240}
                      ariaLabel={`Development Population rows, event count, and event rate over ${timeField}; sealed final holdout excluded.`}
                      emptyMessage="Select a governed time field to evaluate stability."
                    />
                  </div>
                  {timeStability ? (
                    <div
                      className={`mt-3 rounded-lg border px-3 py-2 text-xs ${timeStability.material_shift ? "border-amber-300 bg-amber-50 text-amber-950" : "border-teal-200 bg-teal-50 text-teal-950"}`}
                      data-testid="target-time-stability"
                    >
                      {timeStability.material_shift
                        ? `Material prevalence shift across ${timeStability.period_count} periods: ${formatEventRate(timeStability.lowest_period_event_rate)} to ${formatEventRate(timeStability.highest_period_event_rate)}.`
                        : `No material prevalence shift across ${timeStability.period_count} periods (${formatEventRate(timeStability.lowest_period_event_rate)} to ${formatEventRate(timeStability.highest_period_event_rate)}).`}
                      <span className="ml-1">{formatCount(timeStability.missing_time_values)} missing time value(s).</span>
                    </div>
                  ) : null}
                </>
              )}
            </div>
          )}
          {rejectedTimeField ? (
            <p className="mt-3 rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-950" data-testid="target-rejected-time-field">
              <strong>{rejectedTimeField.field}</strong> was not used. {rejectedTimeField.reason}
            </p>
          ) : null}
        </div>

        {/* SEGMENT */}
        <div className="rounded-lg border border-slate-200 bg-white p-4" data-testid="target-segment-analysis">
          <h3 className="flex items-center gap-2 text-sm font-semibold text-slate-900">
            <Database size={15} /> Target by segment
          </h3>
          <div className="mt-3 flex gap-2">
            <select
              value={segmentField}
              onChange={(event) => onSegmentField(event.target.value)}
              data-testid="target-segment-field-select"
              className="w-full rounded-lg border border-slate-300 px-2 py-1.5 text-sm"
            >
              <option value="">No segment field selected</option>
              {segmentCandidates.map((field) => (
                <option key={field} value={field}>
                  {field}
                </option>
              ))}
            </select>
            <button type="button" className="atlas-secondary-button" onClick={onRun} data-testid="target-run-segment">
              Run
            </button>
          </div>

          {!segmentField ? (
            <p className="mt-3 text-sm text-slate-700" data-testid="target-no-segment-field">
              No segment field selected.
            </p>
          ) : !segmentRows.length ? (
            <p className="mt-3 text-sm text-slate-600">Run the analysis to evaluate the event rate by {segmentField}.</p>
          ) : (
            <>
              <div className="mt-3">
                <EChartsPanel
                  option={segmentOption}
                  state={(segmentOption ? "ready" : "empty") as EChartsPanelState}
                  height={240}
                  ariaLabel={`Development Population event rate by ${segmentField}; sealed final holdout excluded.`}
                  emptyMessage="Select a segment field to compare event rates."
                />
              </div>
              <div className="mt-3 overflow-x-auto">
                <table className="min-w-full text-xs" data-testid="target-segment-table">
                  <thead className="bg-slate-50 text-left uppercase tracking-wide text-slate-500">
                    <tr>
                      <th className="px-2 py-1.5">Segment</th>
                      <th className="px-2 py-1.5 text-right">Development rows</th>
                      <th className="px-2 py-1.5 text-right">Events</th>
                      <th className="px-2 py-1.5 text-right">Event rate</th>
                      <th className="px-2 py-1.5 text-right">vs development</th>
                      <th className="px-2 py-1.5">Note</th>
                    </tr>
                  </thead>
                  <tbody>
                    {segmentRows.map((row) => (
                      <tr key={String(row.group)} className="border-t border-slate-100">
                        <td className="px-2 py-1.5 font-medium">{String(row.group) === "__MISSING__" ? "Missing" : String(row.group)}</td>
                        <td className="px-2 py-1.5 text-right tabular-nums">{formatCount(row.count)}</td>
                        <td className="px-2 py-1.5 text-right tabular-nums">{formatCount(row.events)}</td>
                        <td className="px-2 py-1.5 text-right tabular-nums">{formatEventRate(row.event_rate)}</td>
                        <td className="px-2 py-1.5 text-right tabular-nums">
                          {row.difference_from_population === null || row.difference_from_population === undefined
                            ? "Not available"
                            : `${row.difference_from_population >= 0 ? "+" : "-"}${formatEventRate(Math.abs(row.difference_from_population))}`}
                        </td>
                        <td className="px-2 py-1.5 text-amber-800">{row.small_segment ? "Small segment" : ""}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {segmentMissingCount ? (
                <p className="mt-2 text-xs text-amber-800">{formatCount(segmentMissingCount)} row(s) have a missing segment value.</p>
              ) : null}
            </>
          )}
        </div>
      </div>
    </AtlasWorkflowSection>
  );
}

// ---------------------------------------------------------------------------
// Section 7 -- Target Quality and Leakage (Part I)
// ---------------------------------------------------------------------------

const LEAKAGE_STATE_LABELS: Record<string, string> = {
  no_signal: "No signal detected",
  review_recommended: "Review recommended",
  likely_leakage: "Likely leakage",
  confirmed_leakage: "Confirmed leakage",
};

function TargetQualitySection({
  quality,
  governanceGaps,
}: {
  quality: Record<string, any>;
  governanceGaps: GovernanceField[];
}) {
  const derived = safeArray<any>(quality.target_derived_candidates);
  const postOutcome = safeArray<any>(quality.post_outcome_candidates);
  const perfect = safeArray<any>(quality.perfect_relationship_candidates);
  const invalid = safeArray<any>(quality.invalid_target_values);
  const unexpected = safeArray<string>(quality.unexpected_target_values);
  const blocking = perfect.length > 0;

  return (
    <AtlasWorkflowSection
      eyebrow="Section 7"
      title="Target Quality and Leakage"
      description="Whether the target is measurable, and whether any field appears to encode it. Conservative language throughout: a high IV, a high correlation, or a differing event rate is never sufficient on its own."
      tone={blocking ? "danger" : derived.length || postOutcome.length ? "warning" : "neutral"}
    >
      <div data-testid="target-quality-leakage">
        <p className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-xs leading-5 text-slate-700">
          The compact diagnostic above carries the quality counts. This evidence section preserves the candidate-level
          analytical basis, conservative leakage state, and governance gaps without repeating the same metric cards.
        </p>

        {unexpected.length ? (
          <p className="mt-3 rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-950">
            Values other than the governed positive and negative values are present: {unexpected.join(", ")}.
          </p>
        ) : null}
        {invalid.length ? (
          <ul className="mt-3 list-disc space-y-1 pl-5 text-xs text-amber-900">
            {invalid.map((item) => (
              <li key={String(item.reason)}>
                {item.reason}: {formatCount(item.count)} row(s)
              </li>
            ))}
          </ul>
        ) : null}

        <div className="mt-4 overflow-x-auto rounded-lg border border-slate-200 bg-white">
          <table className="min-w-full text-sm" data-testid="target-leakage-table">
            <thead className="bg-slate-50 text-left text-[11px] uppercase tracking-wide text-slate-500">
              <tr>
                <th className="px-3 py-2">Field</th>
                <th className="px-3 py-2">Family</th>
                <th className="px-3 py-2">State</th>
                <th className="px-3 py-2">Basis</th>
              </tr>
            </thead>
            <tbody>
              {[...perfect, ...derived, ...postOutcome].length ? (
                [...perfect, ...derived, ...postOutcome].map((item, index) => (
                  <tr key={`${item.feature}-${item.family}-${index}`} className="border-t border-slate-100">
                    <td className="px-3 py-2 font-medium text-slate-900">{item.feature}</td>
                    <td className="px-3 py-2 text-slate-600">{String(item.family).replace(/_/g, " ")}</td>
                    <td className="px-3 py-2">
                      <span
                        className={`rounded-full px-2 py-0.5 text-[11px] font-semibold ${
                          item.state === "likely_leakage" || item.state === "confirmed_leakage"
                            ? "bg-red-100 text-red-900"
                            : "bg-amber-100 text-amber-900"
                        }`}
                        data-testid="leakage-state"
                        data-leakage-state={item.state}
                      >
                        {LEAKAGE_STATE_LABELS[item.state] ?? item.state}
                      </span>
                    </td>
                    <td className="px-3 py-2 text-xs text-slate-600">{item.reason}</td>
                  </tr>
                ))
              ) : (
                <tr>
                  <td className="px-3 py-3 text-sm text-slate-600" colSpan={4} data-testid="leakage-no-signal">
                    {LEAKAGE_STATE_LABELS.no_signal} -- no field name or structural relationship indicates target leakage.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>

        <p className="mt-3 rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs text-slate-700" data-testid="leakage-assessment-rule">
          <ShieldAlert size={13} className="mr-1 inline" />
          {String(quality.assessment_rule ?? "")}
        </p>

        <div className="mt-3 rounded-lg border border-slate-200 bg-white px-3 py-2" data-testid="target-unresolved-governance-gaps">
          <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">Unresolved governance-definition gaps</div>
          {governanceGaps.length ? (
            <ul className="mt-1 list-disc space-y-1 pl-5 text-xs text-amber-900">
              {governanceGaps.map((field) => (
                <li key={field.key}>{field.label} is not recorded in Project Context.</li>
              ))}
            </ul>
          ) : (
            <p className="mt-1 text-xs text-teal-800">
              <CheckCircle2 size={13} className="mr-1 inline" />
              All target-defining governance fields are recorded in Project Context.
            </p>
          )}
        </div>
      </div>
    </AtlasWorkflowSection>
  );
}

// ---------------------------------------------------------------------------

function Metric({
  label,
  value,
  tone = "neutral",
  testId,
}: {
  label: string;
  value: string;
  tone?: "danger" | "info" | "neutral";
  testId?: string;
}) {
  const toneClass = tone === "danger" ? "text-red-900" : tone === "info" ? "text-blue-900" : "text-slate-900";
  return (
    <div className="rounded-lg border border-slate-200 bg-white px-3 py-2" data-testid={testId}>
      <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">{label}</div>
      <div
        className={`mt-1 break-words text-sm font-semibold [overflow-wrap:anywhere] ${toneClass}`}
      >
        {value}
      </div>
    </div>
  );
}
