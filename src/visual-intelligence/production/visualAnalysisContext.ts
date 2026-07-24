// ATLAS Visual Intelligence Production Integration, Phase B -- shared production
// component contract. VisualAnalysisContext is a superset "view" over the
// existing VisualDatasetReference (src/visual-intelligence/types.ts) plus the
// production-only flags (readOnly/evidenceEnabled/registrationEnabled) that a
// workflow page needs to control but a bare data reference never carried.
//
// This does NOT replace VisualDatasetReference or VisualIntelligenceContext --
// it derives from them, so the reusable resolution logic in
// VisualIntelligenceContext.tsx (URL-driven scoringRunId, task-context
// resolution, stale-result rejection) is reused, not duplicated.
import type { ProblemType, ScoringPartition, VisualDatasetReference, VisualSourceType } from "../types";

export type VisualAnalysisContext = {
  authenticatedUserId: string;
  projectId: string;
  problemType: ProblemType | null;
  target: string | null;
  datasetId?: string;
  datasetVersionId?: string;
  modelId?: string;
  /** Durable Model Registry, Phase G: the real ModelVersion identity
   *  (model_versions.model_version_id), resolved from the active ScoringRun --
   *  never a timestamp. Absent when the run predates the registry. */
  modelVersionId?: string;
  /** Display label only (e.g. "v3") -- derived from modelVersionId, not an
   *  identity field itself. See modelVersionId for the actual reference. */
  modelVersion?: string;
  featureManifestVersion?: string;
  scoringRunId?: string;
  partition?: ScoringPartition;
  sourceType: VisualSourceType;
  readOnly: boolean;
  evidenceEnabled: boolean;
  registrationEnabled: boolean;
};

export function buildVisualAnalysisContext(
  reference: VisualDatasetReference,
  overrides: Partial<Pick<VisualAnalysisContext, "modelVersion" | "modelVersionId" | "readOnly" | "evidenceEnabled" | "registrationEnabled">> = {}
): VisualAnalysisContext {
  return {
    authenticatedUserId: reference.authenticatedUserId,
    projectId: reference.projectId,
    problemType: reference.problemType ?? null,
    target: reference.target ?? null,
    datasetId: reference.datasetId,
    datasetVersionId: reference.versionId,
    modelId: reference.modelId,
    modelVersionId: overrides.modelVersionId,
    modelVersion: overrides.modelVersion,
    featureManifestVersion: reference.featureManifestVersion,
    scoringRunId: reference.scoringRunId,
    partition: reference.partition,
    sourceType: reference.sourceType,
    readOnly: overrides.readOnly ?? false,
    evidenceEnabled: overrides.evidenceEnabled ?? true,
    registrationEnabled: overrides.registrationEnabled ?? Boolean(reference.scoringRunId),
  };
}

/** Phase B requirement 4: components must reject a context whose identity no
 *  longer matches what a chart currently reflects -- reuses the exact same
 *  field-by-field comparison already proven in dataAccessLayer.ts's
 *  isStaleResult, applied to the wider VisualAnalysisContext shape. */
export function analysisContextMismatch(active: VisualAnalysisContext, incoming: VisualAnalysisContext): string | null {
  if (active.projectId !== incoming.projectId) return "project";
  if (active.datasetId && incoming.datasetId && active.datasetId !== incoming.datasetId) return "dataset";
  if (active.datasetVersionId && incoming.datasetVersionId && active.datasetVersionId !== incoming.datasetVersionId) return "version";
  if (active.modelId && incoming.modelId && active.modelId !== incoming.modelId) return "model";
  if (active.scoringRunId && incoming.scoringRunId && active.scoringRunId !== incoming.scoringRunId) return "scoring run";
  if (active.problemType && incoming.problemType && active.problemType !== incoming.problemType) return "problem type";
  if (active.partition && incoming.partition && active.partition !== incoming.partition) return "partition";
  return null;
}
