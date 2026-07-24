// ATLAS Visual Intelligence Production Integration, Phase B -- the shared
// production wrapper every workflow-page integration renders. Wraps the
// EXISTING VisualIntelligenceProvider (context resolution: project/user/task/
// URL-driven scoringRunId -- unchanged, reused, not duplicated) with the
// production chrome: identity badges, the Scoring Run selector, and the
// reusable action bar (Save Evidence / Export / Open Run / Compare /
// Register / Reset). The embedded prototype (children) is rendered exactly
// as-is -- this file contains ZERO visualization/chart logic of its own.
import { useEffect, useState, type ReactNode } from "react";
import {
  VisualIntelligenceProvider,
  useVisualIntelligenceContext,
} from "../VisualIntelligenceContext";
import { useInteractionStore } from "../interactionStore";
import { useWorkflowStore } from "../../state/useWorkflowStore";
import { buildVisualAnalysisContext } from "./visualAnalysisContext";
import { saveAnalysisToEvidence } from "./evidenceExport";
import { exportChartPng, exportVisualizationSpecJson } from "./chartExport";
import ScoringRunSelector from "./ScoringRunSelector";
import RunComparePanel from "./RunComparePanel";
import RegisterScoredDatasetButton from "./RegisterScoredDatasetButton";
import type { ProblemType } from "../types";

export type VisualAnalysisPanelProps = {
  analysisType: "distribution" | "classification" | "regression";
  title: string;
  description?: string;
  /** Restricts the embedded explorer to one problem type -- e.g. Step08 only
   *  mounts the Classification panel when problemType === "classification". */
  expectedProblemType?: ProblemType;
  children: ReactNode;
};

function ActionBar({ analysisType }: { analysisType: VisualAnalysisPanelProps["analysisType"] }) {
  const { baseReference, scoringRunId, selectScoringRun } = useVisualIntelligenceContext();
  const [showCompare, setShowCompare] = useState(false);
  const [showRunDetails, setShowRunDetails] = useState(false);
  const [savingEvidence, setSavingEvidence] = useState(false);
  const [evidenceMessage, setEvidenceMessage] = useState<string | null>(null);

  const chartInstance = useInteractionStore((state) => state.chartInstance);
  const activeFilters = useInteractionStore((state) => state.activeFilters);
  const selectedRange = useInteractionStore((state) => state.selectedRange);
  const classificationThreshold = useInteractionStore((state) => state.classificationThreshold);
  const activePartition = useInteractionStore((state) => state.activePartition);
  const interaction = { activeFilters, selectedRange, classificationThreshold, activePartition };
  const resolvedModelVersion = useResolvedModelVersion(scoringRunId);

  if (!baseReference) return null;
  const context = buildVisualAnalysisContext(baseReference, {
    modelVersion: resolvedModelVersion ? `v${resolvedModelVersion.versionNumber}` : undefined,
    modelVersionId: resolvedModelVersion?.modelVersionId,
  });

  async function handleSaveEvidence() {
    setSavingEvidence(true);
    setEvidenceMessage(null);
    try {
      await saveAnalysisToEvidence({
        title: `${analysisType[0].toUpperCase()}${analysisType.slice(1)} analysis -- ${context.partition ?? interaction.activePartition ?? "TRAIN"}`,
        analysisType,
        purpose: `Saved from the Visual Intelligence ${analysisType} explorer embedded in the Predictive Modeling workflow.`,
        context: {
          ...context,
          modelId: resolvedModelVersion?.modelId ?? context.modelId,
        },
        visualizationSpec: { analysisType, filters: interaction.activeFilters, selectedRange: interaction.selectedRange },
        filters: interaction.activeFilters,
        threshold: analysisType === "classification" ? interaction.classificationThreshold : undefined,
        selectedSegment: interaction.selectedRange ?? undefined,
      });
      setEvidenceMessage("Saved to Evidence.");
    } catch (err) {
      setEvidenceMessage(err instanceof Error ? err.message : "Failed to save evidence.");
    } finally {
      setSavingEvidence(false);
    }
  }

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-2" role="toolbar" aria-label={`${analysisType} analysis actions`}>
        <button type="button" data-testid="va-save-evidence" className="atlas-secondary-button text-xs" onClick={handleSaveEvidence} disabled={savingEvidence}>
          {savingEvidence ? "Saving..." : "Save Analysis to Evidence"}
        </button>
        <button
          type="button"
          data-testid="va-export-png"
          className="atlas-secondary-button text-xs"
          onClick={() => exportChartPng(chartInstance, analysisType, context)}
          disabled={!chartInstance}
        >
          Export Chart (PNG)
        </button>
        <button
          type="button"
          data-testid="va-export-json"
          className="atlas-secondary-button text-xs"
          onClick={() => exportVisualizationSpecJson({ analysisType, filters: interaction.activeFilters, threshold: interaction.classificationThreshold }, analysisType, context)}
        >
          Export Spec (JSON)
        </button>
        {scoringRunId ? (
          <button type="button" data-testid="va-open-run" className="atlas-secondary-button text-xs" onClick={() => setShowRunDetails((v) => !v)}>
            {showRunDetails ? "Hide Run Details" : "Open Scoring Run"}
          </button>
        ) : null}
        <button type="button" data-testid="va-compare-runs" className="atlas-secondary-button text-xs" onClick={() => setShowCompare((v) => !v)}>
          {showCompare ? "Hide Comparison" : "Compare Runs"}
        </button>
        {scoringRunId && analysisType !== "distribution" ? (
          <RegisterScoredDatasetButton context={context} />
        ) : null}
        {scoringRunId ? (
          <button type="button" data-testid="va-reset-analysis" className="atlas-secondary-button text-xs" onClick={() => selectScoringRun(null)}>
            Reset Analysis
          </button>
        ) : null}
        {evidenceMessage ? <span role="status" aria-live="polite" className="text-xs text-slate-600" data-testid="va-evidence-status">{evidenceMessage}</span> : null}
      </div>

      {showRunDetails && scoringRunId ? <RunDetailsInline scoringRunId={scoringRunId} /> : null}
      {showCompare ? <RunComparePanel projectId={context.projectId} anchorRunId={scoringRunId ?? null} /> : null}
    </div>
  );
}

function RunDetailsInline({ scoringRunId }: { scoringRunId: string }) {
  const [detail, setDetail] = useState<Record<string, unknown> | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    import("../../scoring-runs/scoringRunClient").then(({ getScoringRun, getScoringRunLineage }) =>
      Promise.all([getScoringRun(scoringRunId), getScoringRunLineage(scoringRunId)]).then(([run, lineage]) => {
        if (cancelled) return;
        setDetail({ ...run, lineage });
        setLoading(false);
      })
    );
    return () => {
      cancelled = true;
    };
  }, [scoringRunId]);

  if (loading || !detail) return <p className="text-xs text-slate-500" role="status">Loading run details...</p>;
  return (
    <div className="rounded-md border border-slate-200 bg-slate-50 p-3 text-xs" data-testid="va-run-details">
      <dl className="grid grid-cols-2 gap-x-4 gap-y-1 sm:grid-cols-3">
        <div><dt className="font-semibold text-slate-500">Scoring Run</dt><dd>{String(detail.scoringRunId)}</dd></div>
        <div><dt className="font-semibold text-slate-500">Model</dt><dd>{String(detail.modelId ?? "-")}</dd></div>
        <div><dt className="font-semibold text-slate-500">Dataset/Version</dt><dd>{String(detail.datasetId ?? detail.datasetIdentity ?? "-")}</dd></div>
        <div><dt className="font-semibold text-slate-500">Row count</dt><dd>{String(detail.rowCount ?? "-")}</dd></div>
        <div><dt className="font-semibold text-slate-500">Status</dt><dd>{String(detail.status)}</dd></div>
        <div><dt className="font-semibold text-slate-500">Checksum</dt><dd className="truncate">{String(detail.checksum ?? "-")}</dd></div>
      </dl>
    </div>
  );
}

/** Durable Model Registry, Phase G: when the active analysis is pinned to a
 *  ScoringRun, resolve its ModelVersion (algorithm/version/dataset version)
 *  from the registry -- never inferred, never a timestamp. Silently shows
 *  nothing extra when the run predates the registry (modelVersionId absent). */
type ResolvedModelVersion = { modelVersionId: string; modelId: string; algorithm: string | null; versionNumber: number; datasetVersionId: string | null };

function useResolvedModelVersion(scoringRunId: string | null): ResolvedModelVersion | null {
  const [modelVersion, setModelVersion] = useState<ResolvedModelVersion | null>(null);

  useEffect(() => {
    let cancelled = false;
    setModelVersion(null);
    if (!scoringRunId) return;
    import("../../scoring-runs/scoringRunClient").then(async ({ getScoringRun }) => {
      const run = await getScoringRun(scoringRunId);
      if (cancelled || !run.modelVersionId) return;
      const { getModelVersion } = await import("../../model-registry/modelRegistryClient");
      const version = await getModelVersion(run.modelVersionId);
      if (cancelled) return;
      setModelVersion({ modelVersionId: version.modelVersionId, modelId: version.modelId, algorithm: version.algorithm, versionNumber: version.versionNumber, datasetVersionId: version.datasetVersionId });
    }).catch(() => !cancelled && setModelVersion(null));
    return () => {
      cancelled = true;
    };
  }, [scoringRunId]);

  return modelVersion;
}

function IdentityBadges({ analysisType }: { analysisType: string }) {
  const { baseReference, problemType, target, scoringRunId, loading } = useVisualIntelligenceContext();
  const modelVersion = useResolvedModelVersion(scoringRunId);
  if (loading) return <p role="status" aria-live="polite" className="text-xs text-slate-500">Resolving analysis context...</p>;
  if (!baseReference) return null;
  return (
    <div className="flex flex-wrap items-center gap-2 text-xs text-slate-600" data-testid="va-identity-badges">
      {problemType ? <Badge label="Problem type" value={problemType} /> : null}
      {target ? <Badge label="Target" value={target} /> : null}
      {baseReference.partition ? <Badge label="Partition" value={baseReference.partition.toUpperCase()} /> : null}
      {baseReference.datasetId ? <Badge label="Dataset" value={baseReference.datasetId} /> : null}
      {baseReference.versionId ? <Badge label="Version" value={baseReference.versionId} /> : null}
      {modelVersion?.algorithm ? <Badge label="Algorithm" value={modelVersion.algorithm} /> : null}
      {modelVersion ? <Badge label="Model Version" value={`v${modelVersion.versionNumber}`} /> : null}
      {modelVersion?.datasetVersionId ? <Badge label="Dataset Version" value={modelVersion.datasetVersionId} /> : null}
      {scoringRunId ? <Badge label="Scoring Run" value={scoringRunId} /> : null}
      <Badge
        label="Source"
        value={scoringRunId ? "Durable scoring run" : "Live workspace"}
        tone={scoringRunId ? "durable" : "ephemeral"}
      />
      <span className="sr-only">{analysisType} analysis identity summary</span>
    </div>
  );
}

function Badge({ label, value, tone }: { label: string; value: string; tone?: "durable" | "ephemeral" }) {
  return (
    <span className={`rounded border px-1.5 py-0.5 ${tone === "durable" ? "border-blue-200 bg-blue-50 text-blue-800" : tone === "ephemeral" ? "border-amber-200 bg-amber-50 text-amber-800" : "border-slate-200 bg-slate-50"}`}>
      <span className="font-semibold">{label}:</span> {value}
    </span>
  );
}

function PanelBody({ analysisType, children }: { analysisType: VisualAnalysisPanelProps["analysisType"]; children: ReactNode }) {
  const projectId = useWorkflowStore((state) => state.projectId);
  const { scoringRunId, selectScoringRun, problemType } = useVisualIntelligenceContext();
  return (
    <div className="space-y-3">
      <IdentityBadges analysisType={analysisType} />
      <ScoringRunSelector projectId={projectId} value={scoringRunId} onChange={selectScoringRun} problemType={problemType} />
      <ActionBar analysisType={analysisType} />
      {children}
    </div>
  );
}

/** The only place a workflow page should mount a Visual Intelligence prototype.
 *  `expectedProblemType`, when given, is an EARLY, honest refusal (never a
 *  silently-wrong chart) when the active project's resolved problemType does
 *  not match what this panel is built to show. */
export default function VisualAnalysisPanel({ analysisType, title, description, expectedProblemType, children }: VisualAnalysisPanelProps) {
  return (
    <VisualIntelligenceProvider>
      <section className="space-y-3 rounded-lg border border-slate-200 bg-white p-4" data-testid={`visual-analysis-panel-${analysisType}`} aria-label={title}>
        <header>
          <h3 className="text-sm font-semibold text-slate-950">{title}</h3>
          {description ? <p className="mt-0.5 text-xs text-slate-600">{description}</p> : null}
        </header>
        <ProblemTypeGate expectedProblemType={expectedProblemType} analysisType={analysisType}>
          <PanelBody analysisType={analysisType}>{children}</PanelBody>
        </ProblemTypeGate>
      </section>
    </VisualIntelligenceProvider>
  );
}

function ProblemTypeGate({ expectedProblemType, analysisType, children }: { expectedProblemType?: ProblemType; analysisType: string; children: ReactNode }) {
  const { problemType, loading } = useVisualIntelligenceContext();
  if (loading) return <p role="status" aria-live="polite" className="text-xs text-slate-500">Resolving analysis context...</p>;
  if (expectedProblemType && problemType && problemType !== expectedProblemType) {
    return (
      <p role="status" data-testid="va-wrong-problem-type" className="rounded-md border border-dashed border-amber-300 bg-amber-50 p-3 text-xs text-amber-800">
        This project is a {problemType} project. The {analysisType} explorer is not applicable here.
      </p>
    );
  }
  return <>{children}</>;
}
