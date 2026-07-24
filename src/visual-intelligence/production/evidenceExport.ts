// ATLAS Visual Intelligence Production Integration, Phase H -- reusable
// "Save Analysis to Evidence" action, shared by all three production panels
// (never duplicated per-explorer). Reuses the existing createEvidence()
// (src/lib/evidenceGraph.ts), which already dual-writes to both the file-based
// and SQLite-backed evidence stores -- no new evidence system is introduced.
import { createEvidence, type EvidenceItem, type EvidenceType } from "../../lib/evidenceGraph";
import type { VisualAnalysisContext } from "./visualAnalysisContext";

export type AnalysisEvidencePackage = {
  title: string;
  analysisType: "distribution" | "classification" | "regression";
  purpose: string;
  context: VisualAnalysisContext;
  visualizationSpec: Record<string, unknown>;
  filters?: Record<string, unknown>;
  threshold?: number;
  selectedSegment?: Record<string, unknown>;
  metrics?: Record<string, unknown>;
  queryMetadata?: {
    exact?: boolean;
    approximate?: boolean;
    sampled?: boolean;
    sampleMethod?: string;
    sourceRowCount?: number | null;
    rowsScanned?: number | null;
    resultRowCount?: number | null;
    queryDurationMs?: number;
  };
  chartImageDataUrl?: string;
};

const ANALYSIS_TYPE_TO_EVIDENCE_TYPE: Record<AnalysisEvidencePackage["analysisType"], EvidenceType> = {
  distribution: "eda",
  classification: "evaluation",
  regression: "evaluation",
};

/**
 * Saves a bounded analysis (visualization spec + filters + metrics + query
 * metadata) to Evidence -- NEVER the underlying raw dataset (Phase H requirement 1).
 * Evidence created from a historical ScoringRun stays pinned to that immutable
 * run's id (context.scoringRunId), never re-resolved to "whatever is latest"
 * on reopen (Phase H requirement 4).
 */
export async function saveAnalysisToEvidence(pkg: AnalysisEvidencePackage): Promise<EvidenceItem> {
  const { context } = pkg;
  return createEvidence({
    evidenceType: ANALYSIS_TYPE_TO_EVIDENCE_TYPE[pkg.analysisType],
    title: pkg.title,
    summary: pkg.purpose,
    projectId: context.projectId,
    sourcePage: "Visual Intelligence",
    sourceRoute: window.location.pathname + window.location.search,
    artifactType: `visual-intelligence-${pkg.analysisType}`,
    artifactId: context.scoringRunId ?? context.datasetVersionId ?? context.datasetId,
    datasetIds: context.datasetId ? [context.datasetId] : [],
    modelIds: context.modelVersionId ?? context.modelId ? [context.modelVersionId ?? context.modelId ?? ""] : [],
    tags: [pkg.analysisType, context.partition ?? "", context.problemType ?? ""].filter(Boolean),
    status: "ready",
    importance: "medium",
    createdBy: context.authenticatedUserId,
    workflowStep: pkg.analysisType === "distribution" ? "eda" : "evaluation",
    sourceRunReference: context.scoringRunId,
    lineage: {
      projectId: context.projectId,
      datasetId: context.datasetId,
      datasetVersionId: context.datasetVersionId,
      modelId: context.modelId,
      modelVersionId: context.modelVersionId,
      modelVersion: context.modelVersion,
      featureManifestVersion: context.featureManifestVersion,
      scoringRunId: context.scoringRunId,
      partition: context.partition,
      sourceType: context.sourceType,
    },
    payload: {
      visualizationSpec: pkg.visualizationSpec,
      filters: pkg.filters ?? {},
      threshold: pkg.threshold,
      selectedSegment: pkg.selectedSegment ?? {},
      metrics: pkg.metrics ?? {},
      queryMetadata: pkg.queryMetadata ?? {},
      target: context.target,
      problemType: context.problemType,
      chartImageDataUrl: pkg.chartImageDataUrl,
    },
  });
}
