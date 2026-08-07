import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { Check, Loader2, ShieldCheck } from "lucide-react";
import StepShell from "../components/StepShell";
import StepPythonPanel from "../components/StepPythonPanel";
import BureauReviewPanel, {
  FOCUS_FIRST_SPECIAL_VALUE_REVIEW_EVENT,
  type BureauReviewPanelStatus,
  type BureauReviewPanelResult,
} from "../components/BureauReviewPanel";
import BureauMetadataBindingPanel from "../components/BureauMetadataBindingPanel";
import DataAcquisitionSectionNav, {
  type DataAcquisitionSectionNavItem,
} from "../components/dataAcquisition/DataAcquisitionSectionNav";
import { type AtlasWorkflowMetric } from "../components/ui/AtlasWorkflow";
import { logDecision } from "../lib/decisionJournal";
import {
  BROWSER_PARSE_EXTENSIONS,
  DEFAULT_BROWSER_MAX_COLUMNS,
  DEFAULT_BROWSER_MAX_ROWS,
  backendImportFailureMessage,
  buildSelectedDatasetView,
  dataAcquisitionDisabledReason,
  getUploadDecision,
  guessTargetFromHeaders,
  normalizeBackendImportResponse,
  type NormalizedBackendImport,
} from "../lib/dataAcquisitionUpload";
import {
  buildDataAccessMetadata,
  fetchFullDataQualityProfile,
  inferDataQuality,
  loadDataAccessMetadata,
  loadDatasetVersions,
  queryTemplates,
  recordDatasetVersion,
  saveDataAccessMetadata,
  validateSql,
  type DataAccessMetadata,
  type DataQualitySummary,
  type DataSourceType,
  type SamplingMethod,
} from "../lib/enterpriseDataAccess";
import { loadLocalDataset, saveLocalDataset, type LocalDataset } from "../lib/localDataset";
import {
  assertExactDatasetActivation,
  buildTargetPersistencePayload,
  requireCanonicalDatasetIdentity,
  requireLocalDatasetCanonicalIdentity,
  resolveExactReopenDatasetIdentity,
  type CanonicalDatasetIdentity,
} from "../lib/datasetIdentity";
import {
  activateDatasetVersion,
  findSimilarDatasets,
  getDataset,
  getDatasetPreview,
  listDatasets,
  registerWorkspaceDataset,
  type DatasetSummary,
  type DatasetVersionSummary,
} from "../lib/datasetLibrary";
import { useWorkflowStore } from "../state/useWorkflowStore";
import { fetchFullFeatureProfile, predictorEligibility, profileFeaturesInBrowser, type FeatureProfileResponse } from "../lib/featureProfiling";
import {
  ivCellText,
  formatIvExact,
  planWeakSignalExclusion,
  IV_STATUS_LABELS,
  WEAK_SIGNAL_IV_THRESHOLD,
  type PredictorProfile,
  signalStrength,
  leakageScreen,
  LEAKAGE_SCREEN_LABELS,
  predictorEvaluationCounts,
  HIGH_IV_EXPLANATION,
} from "../lib/governedProfile";
import { useTargetProfile } from "../lib/useTargetProfile";
import {
  deriveDataAcquisitionStatus,
  projectLinkLabel,
  registrationLabel,
  type DataAcquisitionStatus,
} from "../lib/dataAcquisitionStatus";
import {
  DATASET_SOURCE_LABELS,
  DATASET_LOAD_STAGES,
  IDLE_LOAD_PROGRESS,
  buildTargetDistribution,
  computeClassDistributionFromRows,
  isAlreadyLinked,
  resolveDatasetSourceKind,
  resolvePersistenceMode,
  resolveRegistrationActionLabel,
  type DatasetLibraryLink,
  type DatasetLoadProgress,
  type DatasetSourceKind,
  type PersistenceMode,
} from "../lib/dataAcquisitionLifecycle";
import DatasetLoadProgressPanel from "../components/dataAcquisition/DatasetLoadProgressPanel";
import TargetDistributionPanel from "../components/dataAcquisition/TargetDistributionPanel";
import { useTargetDistribution } from "../lib/useTargetDistribution";
import { projectWorkflowRoute } from "../lib/projectScopedRoutes";
import {
  REPRODUCIBILITY_CONTEXT_CONFIRMED_EVENT,
  REPRODUCIBILITY_CONTEXT_PENDING_EVENT,
  fetchDataAcquisitionReproducibilityContext,
  markReproducibilityContextPending,
  notifyReproducibilityContextConfirmed,
  type DataAcquisitionReproducibilityContext,
  type ReproducibilityPredictorAuthorization,
} from "../lib/dataAcquisitionReproducibility";
import { fetchCanonicalDataAcquisitionEdaHandoff } from "../lib/dataAcquisitionEdaHandoff";
import {
  analysisPartitionMembershipPreserved,
  canonicalPredictorSelectionKey,
  derivePredictorAuthorizationDraftState,
  predictorAuthorizationLineageMatches,
  shouldHydratePredictorSelectionFromGovernedBaseline,
} from "../lib/predictorAuthorizationReconciliation";

const BASE =
  (import.meta.env?.VITE_API_BASE as string | undefined)?.replace(/\/$/, "") ||
  "http://127.0.0.1:8001/api";

type AnalysisPartitionPhase =
  | "idle"
  | "checking"
  | "required"
  | "confirming"
  | "documenting"
  | "documentation_pending"
  | "current"
  | "error";

type AnalysisPartitionRecord = {
  analysis_partition_id?: string;
  project_id?: string;
  dataset_id?: string;
  dataset_version_id?: string;
  target?: string;
  positive_value?: unknown;
  negative_value?: unknown;
  development_partition_id?: string;
  sealed_holdout_partition_id?: string;
  development_share?: number;
  holdout_share?: number;
  random_seed?: number;
  stratification_policy?: string;
  stratification_field?: string;
  final_holdout_status?: string;
  holdout_isolation_status?: string;
  revision?: number;
  development_rows?: number;
  development_count?: number;
  holdout_rows?: number;
  holdout_count?: number;
  sealed_holdout_rows?: number;
  population_count?: number;
  partition_method?: string;
  created_by?: unknown;
  created_at?: string;
  evidence_id?: string;
  evidence_ref?: string;
  evidence_status?: string;
  mdd_status?: string;
  mdd_ref?: string;
  [key: string]: unknown;
};

type AnalysisPartitionReadiness = {
  phase: AnalysisPartitionPhase;
  code: string;
  message: string;
  recovery: string;
  partition: AnalysisPartitionRecord | null;
  reused?: boolean;
};

type AnalysisPartitionResetImpactState = {
  phase: "idle" | "loading" | "ready" | "error";
  message: string;
  impacts: string[];
  partition: AnalysisPartitionRecord | null;
};

type AnalysisPartitionPolicy = {
  developmentShare: number;
  holdoutShare: number;
  randomSeed: number;
  stratificationPolicy: "target" | "none";
};

type AnalysisPartitionPreviewPhase = "idle" | "loading" | "ready" | "error";

type AnalysisPartitionPreview = {
  phase: AnalysisPartitionPreviewPhase;
  code: string;
  message: string;
  totalEligibleRows?: number;
  developmentRows?: number;
  holdoutRows?: number;
  developmentEventCount?: number;
  developmentNonEventCount?: number;
  holdoutEventCount?: number;
  holdoutNonEventCount?: number;
  developmentEventRate?: number;
  holdoutEventRate?: number;
  fullPopulationEventRate?: number;
  absoluteEventRateDifference?: number;
  targetMinimum?: number;
  targetMaximum?: number;
  targetMean?: number;
  targetStandardDeviation?: number;
  targetQuantiles?: Record<string, number>;
  targetBandCoverage?: unknown;
  extremeValueCoverage?: unknown;
  partitionMethod?: string;
  randomSeed?: number;
  stratificationField?: string;
  recommendationStatus?: "recommended" | "acceptable" | "acceptable_with_warning" | "blocked";
  recommendationRationale?: string;
  rationaleRequired?: boolean;
  warnings: string[];
  blockers: string[];
  previewFingerprint?: string;
  sufficiency?: Record<string, unknown>;
};

type AnalysisPartitionResetResult = {
  readiness: AnalysisPartitionReadiness;
  impacts: string[];
};

type TargetPersistenceContract = {
  targetContractId: string;
  predictorAuthorizationId: string;
};

const EMPTY_ANALYSIS_PARTITION: AnalysisPartitionReadiness = {
  phase: "idle",
  code: "analysis_partition_unchecked",
  message: "Select and activate a dataset version, then confirm the target.",
  recovery: "Complete the required Data Acquisition decisions above.",
  partition: null,
};

const EMPTY_ANALYSIS_PARTITION_RESET_IMPACT: AnalysisPartitionResetImpactState = {
  phase: "idle",
  message: "",
  impacts: [],
  partition: null,
};

const PARTITION_DEFAULTS = {
  developmentShare: 0.8,
  holdoutShare: 0.2,
  randomSeed: 42,
  stratificationPolicy: "target",
} as const;

const MIN_ANALYSIS_PARTITION_RATIONALE_LENGTH = 10;

const INITIAL_HOLDOUT_OPTIONS = [0.3, 0.2, 0.1] as const;

const EMPTY_ANALYSIS_PARTITION_PREVIEW: AnalysisPartitionPreview = {
  phase: "idle",
  code: "analysis_partition_preview_idle",
  message: "Select a standard split to preview exact governed counts.",
  warnings: [],
  blockers: [],
};

function analysisPartitionOptionGuidance(holdoutShare: number) {
  if (holdoutShare === 0.3) {
    return "Provides a larger final evaluation population and a more precise final performance estimate, but leaves fewer observations for model development.";
  }
  if (holdoutShare === 0.1) {
    return "Preserves more observations for model development, but produces a smaller and potentially less precise final evaluation population. It is available only when evaluation counts and target coverage remain adequate.";
  }
  return "Recommended general-purpose balance between model-development capacity and independent final evaluation.";
}

function analysisPartitionOptionLabel(holdoutShare: number) {
  return `${Math.round((1 - holdoutShare) * 100)}% Development / ${Math.round(holdoutShare * 100)}% Final Holdout${
    holdoutShare === PARTITION_DEFAULTS.holdoutShare ? " (Recommended)" : ""
  }`;
}

function initialAnalysisPartitionPolicy(
  holdoutShare: number,
  problemType: "classification" | "regression" = "classification",
): AnalysisPartitionPolicy {
  const selectedHoldout = INITIAL_HOLDOUT_OPTIONS.includes(
    holdoutShare as (typeof INITIAL_HOLDOUT_OPTIONS)[number],
  )
    ? holdoutShare
    : PARTITION_DEFAULTS.holdoutShare;
  return {
    developmentShare: Number((1 - selectedHoldout).toFixed(10)),
    holdoutShare: selectedHoldout,
    randomSeed: PARTITION_DEFAULTS.randomSeed,
    stratificationPolicy:
      problemType === "regression" ? "none" : PARTITION_DEFAULTS.stratificationPolicy,
  };
}

function recordOrEmpty(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function governedErrorDetail(
  payload: unknown,
  fallbackMessage: string,
  fallbackCode: string,
) {
  const envelope = recordOrEmpty(payload);
  const rawDetail = envelope.detail;
  const detail = recordOrEmpty(rawDetail);
  return {
    code: String(detail.code ?? envelope.code ?? fallbackCode),
    message: String(
      (typeof rawDetail === "string" ? rawDetail : detail.message ?? detail.detail) ??
        envelope.message ??
        envelope.error ??
        fallbackMessage,
    ),
    recovery: String(
      detail.recovery ??
        envelope.recovery ??
        "Review the exact governed identity and Analysis Partition, then retry.",
    ),
  };
}

function sameGovernedValue(left: unknown, right: unknown) {
  return String(left ?? "").trim() === String(right ?? "").trim();
}

function currentDurablePredictorAuthorizationId(
  partition: AnalysisPartitionRecord | null | undefined,
) {
  return String(partition?.current_predictor_authorization_id ?? "").trim();
}

function analysisPartitionMatches(
  partition: AnalysisPartitionRecord,
  identity: CanonicalDatasetIdentity,
  target: string,
  eventValue: unknown,
  nonEventValue: unknown,
  policy: AnalysisPartitionPolicy,
) {
  return (
    analysisPartitionIdentityMatches(
      partition,
      identity,
      target,
      eventValue,
      nonEventValue,
    ) && analysisPartitionPolicyMatches(partition, policy, target)
  );
}

function analysisPartitionIdentityMatches(
  partition: AnalysisPartitionRecord,
  identity: CanonicalDatasetIdentity,
  target: string,
  eventValue: unknown,
  nonEventValue: unknown,
) {
  return (
    Boolean(partition.analysis_partition_id) &&
    partition.project_id === identity.project_id &&
    partition.dataset_id === identity.dataset_id &&
    partition.dataset_version_id === identity.dataset_version_id &&
    partition.target === target &&
    sameGovernedValue(partition.positive_value, eventValue) &&
    sameGovernedValue(partition.negative_value, nonEventValue) &&
    Number(partition.revision) > 0 &&
    partition.final_holdout_status === "sealed" &&
    partition.holdout_isolation_status === "verified"
  );
}

function reproducibilityBaselineMatchesPartition(
  context: DataAcquisitionReproducibilityContext | null,
  identity: CanonicalDatasetIdentity | null,
  partition: AnalysisPartitionRecord | null,
  target: string,
  eventValue: unknown,
  nonEventValue: unknown,
) {
  if (
    !context ||
    context.state !== "current" ||
    !identity ||
    !partition ||
    !context.identity ||
    !context.target_contract ||
    !context.predictor_authorization ||
    !context.analysis_partition
  ) {
    return false;
  }
  return (
    context.project_id === identity.project_id &&
    context.identity.project_id === identity.project_id &&
    context.identity.dataset_id === identity.dataset_id &&
    context.identity.dataset_version_id === identity.dataset_version_id &&
    context.target_contract.target === target &&
    sameGovernedValue(context.target_contract.event_value, eventValue) &&
    sameGovernedValue(context.target_contract.non_event_value, nonEventValue) &&
    context.analysis_partition.analysis_partition_id ===
      partition.analysis_partition_id &&
    Number(context.analysis_partition.revision) === Number(partition.revision)
  );
}

function analysisPartitionPolicyMatches(
  partition: AnalysisPartitionRecord,
  policy: AnalysisPartitionPolicy,
  target: string,
) {
  const tolerance = 1e-9;
  return (
    Math.abs(Number(partition.development_share) - policy.developmentShare) < tolerance &&
    Math.abs(Number(partition.holdout_share) - policy.holdoutShare) < tolerance &&
    Number(partition.random_seed) === policy.randomSeed &&
    partition.stratification_policy === policy.stratificationPolicy &&
    String(partition.stratification_field ?? "") ===
      (policy.stratificationPolicy === "target" ? target : "")
  );
}

function predictorIsEligible(
  column: string,
  input: { headers: string[]; rows: Record<string, unknown>[]; target: string },
) {
  // Backend-managed split/lineage fields are never eligible predictors. Keep an
  // explicit atlas_split guard in addition to the shared role classifier so a
  // server-added system field cannot enter a browser selection during restore.
  if (/^atlas(?:_|$)/i.test(column) || /(^|_)(?:system|split|fold|partition|sample_role)(?:_|$)/i.test(column)) {
    return false;
  }
  return predictorEligibility(column, {
    headers: input.headers,
    rows: input.rows,
    target: input.target,
    selected_columns: [],
  }).role === "eligible";
}

async function readAnalysisPartitionReadiness(
  identity: CanonicalDatasetIdentity,
  target: string,
  eventValue: unknown,
  nonEventValue: unknown,
  signal?: AbortSignal,
): Promise<AnalysisPartitionReadiness> {
  const query = new URLSearchParams({
    project_id: identity.project_id,
    dataset_id: identity.dataset_id,
    dataset_version_id: identity.dataset_version_id,
    target,
  });
  const response = await fetch(`${BASE}/analysis-partitions/status?${query.toString()}`, {
    method: "GET",
    credentials: "include",
    signal,
  });
  const payload = await response.json().catch(() => null);
  const envelope = recordOrEmpty(payload);
  if (!response.ok || envelope.ok === false) {
    const detail = governedErrorDetail(
      payload,
      response.status === 409
        ? "A current Analysis Partition has not been confirmed for this governed target."
        : "ATLAS could not verify the Analysis Partition.",
      response.status === 409
        ? "analysis_partition_required"
        : "analysis_partition_status_failed",
    );
    return {
      phase: response.status === 409 ? "required" : "error",
      ...detail,
      partition: null,
    };
  }

  const partition = recordOrEmpty(
    envelope.analysis_partition,
  ) as AnalysisPartitionRecord;
  const readiness = String(envelope.readiness ?? envelope.status ?? "").toLowerCase();
  if (
    readiness === "current" &&
    analysisPartitionIdentityMatches(
      partition,
      identity,
      target,
      eventValue,
      nonEventValue,
    )
  ) {
    return {
      phase: "current",
      code: String(envelope.code ?? "analysis_partition_current"),
      message: "The exact governed Analysis Partition is current and will be reused.",
      recovery: "No action is required unless the dataset, target, or partition policy changes.",
      partition,
      reused: Boolean(envelope.reused ?? true),
    };
  }
  if (
    readiness === "documentation_pending" &&
    analysisPartitionIdentityMatches(
      partition,
      identity,
      target,
      eventValue,
      nonEventValue,
    )
  ) {
    const documentation = recordOrEmpty(envelope.documentation);
    const pendingStages = [
      documentation.evidence_ready === true ? "" : "evidence",
      documentation.mdd_ready === true ? "" : "MDD",
    ].filter(Boolean);
    return {
      phase: "documentation_pending",
      code: String(envelope.code ?? "analysis_partition_documentation_pending"),
      message: String(
        envelope.message ??
          "The sealed Analysis Partition is durable, but its documentation is pending.",
      ),
      recovery: String(
        envelope.recovery ??
          `Complete the missing ${pendingStages.join(" and ") || "documentation"} sidecars without changing membership.`,
      ),
      partition,
      reused: true,
    };
  }

  return {
    phase: "required",
    code:
      readiness === "current"
        ? "analysis_partition_contradictory"
        : String(envelope.code ?? "analysis_partition_required"),
    message:
      readiness === "current"
        ? "The returned Analysis Partition does not match the exact dataset, target, or recommended policy."
        : "Confirm an Analysis Partition before continuing to EDA.",
    recovery: "Choose the development and final-holdout ratio below, then confirm it explicitly.",
    partition: Object.keys(partition).length ? partition : null,
  };
}

async function completeAnalysisPartitionDocumentation(
  identity: CanonicalDatasetIdentity,
  target: string,
  eventValue: unknown,
  nonEventValue: unknown,
  partition: AnalysisPartitionRecord,
): Promise<AnalysisPartitionReadiness> {
  const response = await fetch(`${BASE}/analysis-partitions/complete-documentation`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      project_id: identity.project_id,
      dataset_id: identity.dataset_id,
      dataset_version_id: identity.dataset_version_id,
      target,
      target_contract_id: String(partition.target_contract_id ?? ""),
      predictor_authorization_id: String(
        partition.current_predictor_authorization_id ??
          partition.predictor_authorization_id ??
          "",
      ),
      analysis_partition_id: String(partition.analysis_partition_id ?? ""),
      revision: Number(partition.revision),
    }),
  });
  const payload = await response.json().catch(() => null);
  const envelope = recordOrEmpty(payload);
  if (!response.ok || envelope.ok === false) {
    const detail = governedErrorDetail(
      payload,
      "ATLAS could not complete the Analysis Partition documentation.",
      "analysis_partition_documentation_pending",
    );
    const rawDetail = recordOrEmpty(envelope.detail);
    const stage = String(rawDetail.documentation_stage ?? "").trim();
    return {
      phase: "documentation_pending",
      code: detail.code,
      message: stage ? `${detail.message} Safe failure stage: ${stage}.` : detail.message,
      recovery: detail.recovery,
      partition,
      reused: true,
    };
  }

  const completed = recordOrEmpty(
    envelope.analysis_partition,
  ) as AnalysisPartitionRecord;
  const exactIdentityPreserved =
    analysisPartitionIdentityMatches(
      completed,
      identity,
      target,
      eventValue,
      nonEventValue,
    ) &&
    completed.analysis_partition_id === partition.analysis_partition_id &&
    Number(completed.revision) === Number(partition.revision) &&
    completed.artifact_hash === partition.artifact_hash &&
    completed.assignment_hash === partition.assignment_hash;
  if (
    String(envelope.readiness ?? "").toLowerCase() !== "current" ||
    !exactIdentityPreserved
  ) {
    return {
      phase: "documentation_pending",
      code: "analysis_partition_documentation_readback_failed",
      message: "Documentation returned without proving the exact immutable partition and durable read-back.",
      recovery: "Do not continue to EDA. Retry documentation against this exact partition.",
      partition,
      reused: true,
    };
  }
  return {
    phase: "current",
    code: String(envelope.code ?? "analysis_partition_documentation_completed"),
    message: "Partition evidence and MDD documentation are durably verified. The sealed membership was reused unchanged.",
    recovery: "No additional partition action is required.",
    partition: completed,
    reused: true,
  };
}

function stringList(value: unknown): string[] {
  return Array.isArray(value)
    ? value.map((item) => String(item ?? "").trim()).filter(Boolean)
    : [];
}

function optionalFiniteNumber(value: unknown): number | undefined {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : undefined;
}

function analysisPartitionPreviewHasRequiredEvidence(
  preview: AnalysisPartitionPreview,
  problemType: "classification" | "regression",
): boolean {
  const finite = (value: unknown): value is number =>
    typeof value === "number" && Number.isFinite(value);
  const nonnegative = (value: unknown) => finite(value) && value >= 0;
  const rate = (value: unknown) => finite(value) && value >= 0 && value <= 1;
  const developmentRows = preview.developmentRows;
  const holdoutRows = preview.holdoutRows;
  const totalRows = preview.totalEligibleRows;
  const sufficiency = recordOrEmpty(preview.sufficiency);
  const commonReady =
    preview.phase === "ready" &&
    Boolean(preview.previewFingerprint) &&
    Boolean(preview.recommendationStatus) &&
    nonnegative(totalRows) &&
    nonnegative(developmentRows) &&
    nonnegative(holdoutRows) &&
    Number(developmentRows) + Number(holdoutRows) === Number(totalRows) &&
    Boolean(preview.partitionMethod) &&
    Number.isSafeInteger(preview.randomSeed) &&
    String(sufficiency.overall_status ?? "").trim().length > 0;
  if (!commonReady) return false;

  if (problemType === "classification") {
    return [
      preview.developmentEventCount,
      preview.developmentNonEventCount,
      preview.holdoutEventCount,
      preview.holdoutNonEventCount,
    ].every(nonnegative) && [
      preview.developmentEventRate,
      preview.holdoutEventRate,
      preview.fullPopulationEventRate,
      preview.absoluteEventRateDifference,
    ].every(rate);
  }

  const quantiles = Object.values(preview.targetQuantiles ?? {});
  const bandCoverage = recordOrEmpty(preview.targetBandCoverage);
  const representedBands = optionalFiniteNumber(bandCoverage.represented_bands);
  const totalBands = optionalFiniteNumber(bandCoverage.total_bands);
  const coverageRate = optionalFiniteNumber(bandCoverage.coverage_rate);
  const extremeCoverage = recordOrEmpty(preview.extremeValueCoverage);
  return [
    preview.targetMinimum,
    preview.targetMaximum,
    preview.targetMean,
    preview.targetStandardDeviation,
  ].every(finite) &&
    quantiles.length > 0 &&
    quantiles.every(finite) &&
    nonnegative(representedBands) &&
    finite(totalBands) &&
    totalBands > 0 &&
    Number(representedBands) <= Number(totalBands) &&
    rate(coverageRate) &&
    typeof extremeCoverage.low_extreme_represented === "boolean" &&
    typeof extremeCoverage.high_extreme_represented === "boolean";
}

async function readAnalysisPartitionPreview(
  identity: CanonicalDatasetIdentity,
  target: string,
  eventValue: unknown,
  nonEventValue: unknown,
  problemType: "classification" | "regression",
  policy: AnalysisPartitionPolicy,
  contract?: Partial<TargetPersistenceContract>,
  signal?: AbortSignal,
  resetBaseline?: { analysisPartitionId: string; revision: number },
): Promise<AnalysisPartitionPreview> {
  const previewEndpoint = resetBaseline
    ? `${BASE}/analysis-partitions/reset-preview`
    : `${BASE}/analysis-partitions/preview`;
  const response = await fetch(
    previewEndpoint,
    {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      signal,
      body: JSON.stringify({
      project_id: identity.project_id,
      dataset_id: identity.dataset_id,
      dataset_version_id: identity.dataset_version_id,
      target_contract_id: contract?.targetContractId ?? "",
      target,
      positive_value: eventValue,
      negative_value: nonEventValue,
      predictor_authorization_id: contract?.predictorAuthorizationId ?? "",
      problem_type: problemType,
      development_share: policy.developmentShare,
      holdout_share: policy.holdoutShare,
      random_seed: policy.randomSeed,
      stratification_policy: policy.stratificationPolicy,
      stratification_field:
        policy.stratificationPolicy === "target" ? target : "",
      partition_method: "deterministic_random",
      ...(resetBaseline
        ? {
            expected_current_partition_id:
              resetBaseline.analysisPartitionId,
            expected_current_revision: resetBaseline.revision,
          }
        : {}),
      }),
    },
  );
  const payload = await response.json().catch(() => null);
  const envelope = recordOrEmpty(payload);
  const rawPreview = recordOrEmpty(
    envelope.preview ?? envelope.partition_preview ?? envelope,
  );
  if (!response.ok || envelope.ok === false) {
    const detail = governedErrorDetail(
      payload,
      "ATLAS could not preview the selected Analysis Partition.",
      "analysis_partition_preview_failed",
    );
    return {
      phase: "error",
      code: detail.code,
      message: `${detail.message} ${detail.recovery}`.trim(),
      warnings: stringList(rawPreview.warnings),
      blockers: stringList(rawPreview.blockers),
    };
  }

  const rawRecommendationStatus = String(
    rawPreview.recommendation_status ?? rawPreview.status ?? "",
  ).toLowerCase();
  const recommendationStatus = [
    "recommended",
    "acceptable",
    "acceptable_with_warning",
    "blocked",
  ].includes(rawRecommendationStatus)
    ? rawRecommendationStatus as AnalysisPartitionPreview["recommendationStatus"]
    : undefined;
  return {
    phase: "ready",
    code: String(envelope.code ?? "analysis_partition_preview_ready"),
    message: String(
      rawPreview.recommendation_rationale ??
        envelope.message ??
        "Exact governed preview is ready.",
    ),
    totalEligibleRows: optionalFiniteNumber(rawPreview.total_eligible_rows),
    developmentRows: optionalFiniteNumber(rawPreview.development_rows),
    holdoutRows: optionalFiniteNumber(rawPreview.holdout_rows),
    developmentEventCount: optionalFiniteNumber(rawPreview.development_event_count),
    developmentNonEventCount: optionalFiniteNumber(rawPreview.development_non_event_count),
    holdoutEventCount: optionalFiniteNumber(rawPreview.holdout_event_count),
    holdoutNonEventCount: optionalFiniteNumber(rawPreview.holdout_non_event_count),
    developmentEventRate: optionalFiniteNumber(rawPreview.development_event_rate),
    holdoutEventRate: optionalFiniteNumber(rawPreview.holdout_event_rate),
    fullPopulationEventRate: optionalFiniteNumber(rawPreview.full_population_event_rate),
    absoluteEventRateDifference: optionalFiniteNumber(rawPreview.absolute_event_rate_difference),
    targetMinimum: optionalFiniteNumber(rawPreview.target_minimum),
    targetMaximum: optionalFiniteNumber(rawPreview.target_maximum),
    targetMean: optionalFiniteNumber(rawPreview.target_mean),
    targetStandardDeviation: optionalFiniteNumber(rawPreview.target_standard_deviation),
    targetQuantiles: recordOrEmpty(rawPreview.target_quantiles) as Record<string, number>,
    targetBandCoverage: rawPreview.target_band_coverage,
    extremeValueCoverage: rawPreview.extreme_value_coverage,
    partitionMethod: String(rawPreview.partition_method ?? "") || undefined,
    randomSeed: optionalFiniteNumber(rawPreview.random_seed),
    stratificationField: String(rawPreview.stratification_field ?? ""),
    recommendationStatus,
    recommendationRationale: String(rawPreview.recommendation_rationale ?? ""),
    rationaleRequired: Boolean(rawPreview.rationale_required),
    warnings: stringList(rawPreview.warnings),
    blockers: stringList(rawPreview.blockers),
    previewFingerprint: String(rawPreview.preview_fingerprint ?? "") || undefined,
    sufficiency: recordOrEmpty(rawPreview.sufficiency),
  };
}

async function readAnalysisPartitionResetImpact(
  identity: CanonicalDatasetIdentity,
  signal?: AbortSignal,
): Promise<AnalysisPartitionResetImpactState> {
  const query = new URLSearchParams({
    project_id: identity.project_id,
    dataset_id: identity.dataset_id,
    dataset_version_id: identity.dataset_version_id,
  });
  const response = await fetch(
    `${BASE}/analysis-partitions/reset-impact?${query.toString()}`,
    {
      method: "GET",
      credentials: "include",
      signal,
    },
  );
  const payload = await response.json().catch(() => null);
  const envelope = recordOrEmpty(payload);
  if (!response.ok || envelope.ok === false) {
    const detail = governedErrorDetail(
      payload,
      "ATLAS could not load the governed reset impact.",
      response.status === 409
        ? "analysis_partition_required"
        : "analysis_partition_reset_impact_failed",
    );
    return {
      phase: "error",
      message: `${detail.message} ${detail.recovery}`.trim(),
      impacts: [],
      partition: null,
    };
  }
  const partition = recordOrEmpty(
    envelope.analysis_partition,
  ) as AnalysisPartitionRecord;
  const impacts = Array.isArray(envelope.impacts)
    ? envelope.impacts.map((impact) => String(impact)).filter(Boolean)
    : [];
  if (
    partition.project_id !== identity.project_id ||
    partition.dataset_id !== identity.dataset_id ||
    partition.dataset_version_id !== identity.dataset_version_id ||
    !String(partition.target_contract_id ?? "").trim() ||
    !currentDurablePredictorAuthorizationId(partition) ||
    Number(partition.revision) <= 0 ||
    envelope.requires_explicit_reset !== true ||
    envelope.requires_invalidation_acknowledgement !== true
  ) {
    return {
      phase: "error",
      message:
        "The reset-impact response did not prove the exact current partition and required acknowledgements. No reset was performed.",
      impacts,
      partition: Object.keys(partition).length ? partition : null,
    };
  }
  return {
    phase: "ready",
    message:
      "Review every impact and proposed membership setting before explicitly resetting the current Analysis Partition.",
    impacts,
    partition,
  };
}

async function createOrReuseAnalysisPartition(
  identity: CanonicalDatasetIdentity,
  target: string,
  eventValue: unknown,
  nonEventValue: unknown,
  contract: TargetPersistenceContract,
  policy: AnalysisPartitionPolicy,
  problemType: "classification" | "regression",
  previewFingerprint: string,
  selectionRationale: string,
): Promise<AnalysisPartitionReadiness> {
  const response = await fetch(`${BASE}/analysis-partitions/confirm`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      project_id: identity.project_id,
      dataset_id: identity.dataset_id,
      dataset_version_id: identity.dataset_version_id,
      target_contract_id: contract.targetContractId,
      target,
      positive_value: eventValue,
      negative_value: nonEventValue,
      predictor_authorization_id: contract.predictorAuthorizationId,
      problem_type: problemType,
      development_share: policy.developmentShare,
      holdout_share: policy.holdoutShare,
      random_seed: policy.randomSeed,
      stratification_policy: policy.stratificationPolicy,
      stratification_field:
        policy.stratificationPolicy === "target" ? target : "",
      partition_method: "deterministic_random",
      preview_fingerprint: previewFingerprint,
      selection_rationale: selectionRationale.trim(),
      reset_existing: false,
      reset_reason: "",
      acknowledge_invalidation: false,
    }),
  });
  const payload = await response.json().catch(() => null);
  const envelope = recordOrEmpty(payload);
  if (!response.ok || envelope.ok === false) {
    const detail = governedErrorDetail(
      payload,
      "ATLAS could not confirm the selected Analysis Partition.",
      response.status === 409
        ? "analysis_partition_contradictory"
        : "analysis_partition_confirmation_failed",
    );
    return {
      phase: response.status === 409 ? "required" : "error",
      ...detail,
      partition: null,
    };
  }
  const partition = recordOrEmpty(
    envelope.analysis_partition,
  ) as AnalysisPartitionRecord;
  const readiness = String(envelope.readiness ?? envelope.status ?? "").toLowerCase();
  if (
    readiness !== "current" ||
    !analysisPartitionMatches(
      partition,
      identity,
      target,
      eventValue,
      nonEventValue,
      policy,
    )
  ) {
    return {
      phase: "error",
      code: "analysis_partition_confirmation_unverified",
      message: "The confirmation response did not prove an exact, sealed Analysis Partition.",
      recovery: "Do not continue. Retry confirmation or ask an administrator to review partition integrity.",
      partition: Object.keys(partition).length ? partition : null,
    };
  }
  return {
    phase: "current",
    code: String(envelope.code ?? "analysis_partition_confirmed"),
    message: Boolean(envelope.reused)
      ? "The existing exact Analysis Partition remains current; no duplicate was created."
      : "The Analysis Partition is confirmed and the final holdout is sealed.",
    recovery: "No action is required unless the dataset, target, or partition policy changes.",
    partition,
    reused: Boolean(envelope.reused),
  };
}

async function resetAnalysisPartition(
  identity: CanonicalDatasetIdentity,
  target: string,
  eventValue: unknown,
  nonEventValue: unknown,
  contract: TargetPersistenceContract,
  policy: AnalysisPartitionPolicy,
  problemType: "classification" | "regression",
  previewFingerprint: string,
  resetReason: string,
  previousPartition: AnalysisPartitionRecord,
): Promise<AnalysisPartitionResetResult> {
  const response = await fetch(`${BASE}/analysis-partitions/confirm`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      project_id: identity.project_id,
      dataset_id: identity.dataset_id,
      dataset_version_id: identity.dataset_version_id,
      target_contract_id: contract.targetContractId,
      target,
      positive_value: eventValue,
      negative_value: nonEventValue,
      predictor_authorization_id: contract.predictorAuthorizationId,
      problem_type: problemType,
      development_share: policy.developmentShare,
      holdout_share: policy.holdoutShare,
      random_seed: policy.randomSeed,
      stratification_policy: policy.stratificationPolicy,
      stratification_field:
        policy.stratificationPolicy === "target" ? target : "",
      partition_method: "deterministic_random",
      preview_fingerprint: previewFingerprint,
      selection_rationale: resetReason.trim(),
      reset_existing: true,
      reset_reason: resetReason.trim(),
      acknowledge_invalidation: true,
      expected_current_partition_id: previousPartition.analysis_partition_id,
      expected_current_revision: Number(previousPartition.revision),
    }),
  });
  const payload = await response.json().catch(() => null);
  const envelope = recordOrEmpty(payload);
  const resetImpacts = Array.isArray(envelope.reset_impacts)
    ? envelope.reset_impacts.map((impact) => String(impact)).filter(Boolean)
    : [];
  if (!response.ok || envelope.ok === false) {
    const detail = governedErrorDetail(
      payload,
      "ATLAS could not reset the Analysis Partition.",
      response.status === 409
        ? "analysis_partition_contradictory"
        : "analysis_partition_reset_failed",
    );
    return {
      readiness: {
        phase: response.status === 409 ? "required" : "error",
        ...detail,
        partition: null,
      },
      impacts: resetImpacts,
    };
  }

  const partition = recordOrEmpty(
    envelope.analysis_partition,
  ) as AnalysisPartitionRecord;
  const readiness = String(envelope.readiness ?? envelope.status ?? "").toLowerCase();
  const previousRevision = Number(previousPartition.revision);
  const replacementRevision = Number(partition.revision);
  const verifiedReplacement =
    readiness === "current" &&
    envelope.reused !== true &&
    analysisPartitionIdentityMatches(
      partition,
      identity,
      target,
      eventValue,
      nonEventValue,
    ) &&
    analysisPartitionPolicyMatches(partition, policy, target) &&
    replacementRevision > 0 &&
    replacementRevision > previousRevision &&
    partition.analysis_partition_id !== previousPartition.analysis_partition_id;

  if (!verifiedReplacement) {
    return {
      readiness: {
        phase: "error",
        code: "analysis_partition_reset_unverified",
        message:
          "The reset response did not prove a new positive revision with current, sealed, isolated membership.",
        recovery:
          "Do not continue. Reload the exact reset impact and verify the durable partition state.",
        partition: Object.keys(partition).length ? partition : null,
      },
      impacts: resetImpacts,
    };
  }

  return {
    readiness: {
      phase: "current",
      code: String(envelope.code ?? "analysis_partition_confirmed"),
      message:
        "A new Analysis Partition revision is current and its final holdout is sealed. Downstream evidence remains stale until explicitly recomputed.",
      recovery:
        "Stay in Data Acquisition to review the replacement identity. ATLAS has not continued into EDA or recreated downstream artifacts.",
      partition,
      reused: false,
    },
    impacts: resetImpacts,
  };
}

const sourceCards: { id: DataSourceType; title: string; body: string }[] = [
  { id: "upload", title: "Upload File", body: "CSV and JSON parse locally. Excel, Parquet, Feather, SAS, and ZIP are staged for backend import." },
  { id: "existing", title: "Existing Dataset", body: "Reuse a registered Dataset Library asset and preserve its governed version history." },
  { id: "sql", title: "SQL Database", body: "Author governed SQL, validate queries, capture lineage, and generate Python extraction code." },
  { id: "python", title: "Python Loader", body: "Advanced users can document Python or Spark loading logic that assigns the final dataframe to df." },
  { id: "cloud", title: "Cloud Storage", body: "Document S3, Azure Blob, GCS, SharePoint, or OneDrive paths for governed ingestion." },
];

const WEAK_IV_THRESHOLD = 0.01;
const WEAK_CORRELATION_THRESHOLD = 0.05;

const databaseProviders = ["Oracle", "SQL Server", "PostgreSQL", "MySQL", "Snowflake", "BigQuery", "Databricks SQL", "Teradata", "SQLite", "DuckDB"];
const cloudProviders = ["AWS S3", "Azure Blob Storage", "Google Cloud Storage", "SharePoint", "OneDrive"];

function parseDelimitedLine(line: string) {
  const out: string[] = [];
  let cur = "";
  let inQuotes = false;
  for (let i = 0; i < line.length; i++) {
    const c = line[i];
    if (c === '"') inQuotes = !inQuotes;
    else if (c === "," && !inQuotes) {
      out.push(cur);
      cur = "";
    } else {
      cur += c;
    }
  }
  out.push(cur);
  return out.map((value) => value.replace(/^"(.*)"$/s, "$1").trim());
}

function coerce(value: string) {
  if (value === "") return "";
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : value;
}

export function parseCSV(text: string) {
  const lines = text.replace(/\r/g, "").split("\n").filter((line) => line.trim().length);
  if (!lines.length) return { headers: [] as string[], rows: [] as Record<string, unknown>[] };
  const headers = parseDelimitedLine(lines[0]);
  const rows = lines.slice(1).map((line) => {
    const values = parseDelimitedLine(line);
    const row: Record<string, unknown> = {};
    headers.forEach((header, index) => {
      row[header] = coerce(values[index] ?? "");
    });
    return row;
  });
  return { headers, rows };
}

export function parseJSON(text: string) {
  const parsed = JSON.parse(text);
  const rows = Array.isArray(parsed) ? parsed : Array.isArray(parsed?.data) ? parsed.data : [];
  if (!Array.isArray(rows) || !rows.length) return { headers: [] as string[], rows: [] as Record<string, unknown>[] };
  const headers = Array.from(new Set(rows.flatMap((row) => Object.keys(row ?? {}))));
  return { headers, rows: rows as Record<string, unknown>[] };
}

function isNumericVector(vals: unknown[]) {
  const nonMissing = vals.filter((value) => value !== null && value !== undefined && String(value).trim() !== "");
  if (!nonMissing.length) return false;
  return nonMissing.filter((value) => Number.isFinite(Number(value))).length / nonMissing.length >= 0.6;
}

function targetMeta(rows: Record<string, unknown>[], target: string) {
  if (!target) return { kind: "none" as const, eventRate: null as number | null };
  const vals = rows.map((row) => row[target]);
  if (!isNumericVector(vals)) {
    const counts = new Map<string, number>();
    vals.forEach((value) => counts.set(String(value), (counts.get(String(value)) ?? 0) + 1));
    const sorted = Array.from(counts.values()).sort((a, b) => b - a);
    const total = sorted.reduce((sum, count) => sum + count, 0);
    const event = total - (sorted[0] ?? 0);
    return { kind: "binary" as const, eventRate: total ? event / total : null };
  }
  const ones = vals.filter((value) => Number(value) === 1).length;
  const zeros = vals.filter((value) => Number(value) === 0).length;
  if (ones + zeros >= vals.length * 0.8) return { kind: "binary" as const, eventRate: vals.length ? ones / vals.length : null };
  return { kind: "continuous" as const, eventRate: null };
}

function inferProblemType(rows: Record<string, unknown>[], target: string) {
  return targetMeta(rows, target).kind === "continuous" ? "regression" : "classification";
}

function summarizeColumn(rows: Record<string, unknown>[], column: string, target: string) {
  const values = rows.map((row) => row[column]);
  const missing = values.filter((value) => value === null || value === undefined || String(value).trim() === "").length;
  const numeric = isNumericVector(values);
  const distinct = new Set(values.map(String)).size;
  if (!numeric) return { type: "Categorical", missingPct: rows.length ? missing / rows.length : 0, distinct, mean: null, min: null, max: null };
  const nums = values.map(Number).filter(Number.isFinite);
  const mean = nums.length ? nums.reduce((sum, value) => sum + value, 0) / nums.length : null;
  return {
    type: column === target ? "Target" : "Numeric",
    missingPct: rows.length ? missing / rows.length : 0,
    distinct,
    mean,
    min: nums.length ? Math.min(...nums) : null,
    max: nums.length ? Math.max(...nums) : null,
  };
}

function getBinaryTargetProfile(rows: Record<string, unknown>[], target: string) {
  if (!target) return null;
  const values = rows
    .map((row) => row[target])
    .filter((value) => value !== null && value !== undefined && String(value).trim() !== "");
  if (!values.length) return null;

  const numericCount = values.filter((value) => Number.isFinite(Number(value))).length;
  if (numericCount / values.length >= 0.8) {
    const ones = values.filter((value) => Number(value) === 1).length;
    const zeros = values.filter((value) => Number(value) === 0).length;
    if (ones + zeros >= values.length * 0.8) {
      return { isEvent: (value: unknown) => Number(value) === 1 };
    }
  }

  const counts = new Map<string, number>();
  values.forEach((value) => counts.set(String(value), (counts.get(String(value)) ?? 0) + 1));
  if (counts.size < 2 || counts.size > 20) return null;
  const majority = Array.from(counts.entries()).sort((a, b) => b[1] - a[1])[0]?.[0];
  if (majority === undefined) return null;
  return { isEvent: (value: unknown) => String(value) !== majority };
}

function preferredTarget(headers: string[], fallbackTarget = "") {
  return (fallbackTarget && headers.includes(fallbackTarget) ? fallbackTarget : "") || guessTargetFromHeaders(headers);
}

function quantileBreaks(nums: number[], bins = 10) {
  const sorted = [...nums].sort((a, b) => a - b);
  const breaks: number[] = [];
  for (let i = 1; i < bins; i++) {
    const index = Math.floor((i / bins) * (sorted.length - 1));
    const value = sorted[index];
    if (Number.isFinite(value) && !breaks.includes(value)) breaks.push(value);
  }
  return breaks;
}

function informationValue(rows: Record<string, unknown>[], column: string, target: string) {
  if (!target || column === target || !rows.length) return null;
  const targetProfile = getBinaryTargetProfile(rows, target);
  if (!targetProfile) return null;

  const featureValues = rows.map((row) => row[column]);
  const numeric = isNumericVector(featureValues);
  const numericValues = featureValues.map(Number).filter(Number.isFinite);
  const breaks = numeric && new Set(numericValues).size > 10 ? quantileBreaks(numericValues, 10) : [];
  const rawCategoryCounts = new Map<string, number>();
  if (!numeric) {
    featureValues.forEach((value) => {
      const key = value === null || value === undefined || String(value).trim() === "" ? "__MISSING__" : String(value);
      rawCategoryCounts.set(key, (rawCategoryCounts.get(key) ?? 0) + 1);
    });
  }
  const topCategories = new Set(
    Array.from(rawCategoryCounts.entries())
      .sort((a, b) => b[1] - a[1])
      .slice(0, 20)
      .map(([key]) => key)
  );

  const bucketFor = (value: unknown) => {
    if (value === null || value === undefined || String(value).trim() === "") return "__MISSING__";
    if (!numeric) {
      const key = String(value);
      return topCategories.has(key) ? key : "__OTHER__";
    }
    const num = Number(value);
    if (!Number.isFinite(num)) return "__MISSING__";
    const upper = breaks.find((breakValue) => num <= breakValue);
    return upper === undefined ? `>${breaks.length ? breaks[breaks.length - 1] : "all"}` : `<=${upper}`;
  };

  const buckets = new Map<string, { event: number; nonEvent: number }>();
  let totalEvents = 0;
  let totalNonEvents = 0;
  rows.forEach((row) => {
    const targetValue = row[target];
    if (targetValue === null || targetValue === undefined || String(targetValue).trim() === "") return;
    const key = bucketFor(row[column]);
    const bucket = buckets.get(key) ?? { event: 0, nonEvent: 0 };
    if (targetProfile.isEvent(targetValue)) {
      bucket.event += 1;
      totalEvents += 1;
    } else {
      bucket.nonEvent += 1;
      totalNonEvents += 1;
    }
    buckets.set(key, bucket);
  });

  if (!totalEvents || !totalNonEvents || !buckets.size) return null;
  const epsilon = 0.000001;
  let iv = 0;
  buckets.forEach((bucket) => {
    const eventDist = Math.max(bucket.event / totalEvents, epsilon);
    const nonEventDist = Math.max(bucket.nonEvent / totalNonEvents, epsilon);
    iv += (eventDist - nonEventDist) * Math.log(eventDist / nonEventDist);
  });
  return Number.isFinite(iv) ? Math.max(0, iv) : null;
}

function correlationWithTarget(rows: Record<string, unknown>[], column: string, target: string) {
  if (!target || column === target || !rows.length) return null;
  const pairs = rows
    .map((row) => ({ x: Number(row[column]), y: Number(row[target]) }))
    .filter((row) => Number.isFinite(row.x) && Number.isFinite(row.y));
  if (pairs.length < 3) return null;
  const meanX = pairs.reduce((sum, row) => sum + row.x, 0) / pairs.length;
  const meanY = pairs.reduce((sum, row) => sum + row.y, 0) / pairs.length;
  const numerator = pairs.reduce((sum, row) => sum + (row.x - meanX) * (row.y - meanY), 0);
  const denomX = Math.sqrt(pairs.reduce((sum, row) => sum + (row.x - meanX) ** 2, 0));
  const denomY = Math.sqrt(pairs.reduce((sum, row) => sum + (row.y - meanY) ** 2, 0));
  const corr = numerator / ((denomX || 0) * (denomY || 0));
  return Number.isFinite(corr) ? corr : null;
}

function formatNumber(value: unknown, digits = 4) {
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric.toFixed(digits) : "-";
}

function formatPercent(value: unknown) {
  const numeric = Number(value);
  return Number.isFinite(numeric) ? `${(numeric * 100).toFixed(2)}%` : "-";
}

function ivStatusClass(value: unknown) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return "bg-slate-50 text-slate-400";
  if (numeric >= 0.02) return "bg-emerald-100 font-semibold text-emerald-900";
  return "bg-red-100 font-semibold text-red-900";
}

function signalStatusClass(value: unknown) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return "bg-slate-50 text-slate-400";
  if (Math.abs(numeric) >= 0.1) return "bg-emerald-100 font-semibold text-emerald-900";
  return "bg-red-100 font-semibold text-red-900";
}

function seededRandom(seed: number) {
  let value = Math.max(1, Math.floor(seed)) % 2147483647;
  return () => {
    value = (value * 16807) % 2147483647;
    return (value - 1) / 2147483646;
  };
}

function applyPreviewSampling(input: {
  rows: Record<string, unknown>[];
  method: SamplingMethod;
  rowLimit: number;
  seed: number;
  stratificationColumn?: string;
  timeColumn?: string;
}) {
  const rowLimit = Math.max(1, Math.min(input.rows.length, input.rowLimit));
  if (input.method === "full") return input.rows;
  if (input.method === "random") {
    const random = seededRandom(input.seed);
    return input.rows.map((row) => ({ row, order: random() })).sort((a, b) => a.order - b.order).slice(0, rowLimit).map((item) => item.row);
  }
  if (input.method === "stratified" && input.stratificationColumn) {
    const groups = new Map<string, Record<string, unknown>[]>();
    input.rows.forEach((row) => {
      const key = String(row[input.stratificationColumn as string] ?? "__MISSING__");
      groups.set(key, [...(groups.get(key) ?? []), row]);
    });
    const output: Record<string, unknown>[] = [];
    groups.forEach((group) => {
      const take = Math.max(1, Math.round((group.length / input.rows.length) * rowLimit));
      output.push(...group.slice(0, take));
    });
    return output.slice(0, rowLimit);
  }
  if (input.method === "time_based" && input.timeColumn) {
    return [...input.rows].sort((a, b) => String(a[input.timeColumn as string] ?? "").localeCompare(String(b[input.timeColumn as string] ?? ""))).slice(0, rowLimit);
  }
  return input.rows.slice(0, rowLimit);
}

export default function Step01DataAcquisition() {
  const [searchParams, setSearchParams] = useSearchParams();
  const analysisPartitionResetMode =
    searchParams.get("analysisPartition") === "reset";
  const [sourceType, setSourceType] = useState<DataSourceType>("upload");
  const [headers, setHeaders] = useState<string[]>([]);
  const [rows, setRows] = useState<Record<string, unknown>[]>([]);
  const [fileName, setFileName] = useState("");
  const [message, setMessage] = useState("");
  const [target, setTarget] = useState("");
  const [kept, setKept] = useState<Record<string, boolean>>({});
  const [autoExcludeWeakSignals, setAutoExcludeWeakSignals] = useState(false);
  const [previewSamplingMethod, setPreviewSamplingMethod] = useState<SamplingMethod>("top_n");
  const [previewRowLimit, setPreviewRowLimit] = useState(100);
  const [profileRowLimit, setProfileRowLimit] = useState(5000);
  const [previewRandomSeed, setPreviewRandomSeed] = useState(42);
  const [previewStratificationColumn, setPreviewStratificationColumn] = useState("");
  const [previewTimeColumn, setPreviewTimeColumn] = useState("");
  const [browserDataComplete, setBrowserDataComplete] = useState(false);
  const [eventValue, setEventValue] = useState<unknown>(1);
  const [nonEventValue, setNonEventValue] = useState<unknown>(0);
  const [connectionName, setConnectionName] = useState("Development connection");
  const [provider, setProvider] = useState("Oracle");
  const [database, setDatabase] = useState("");
  const [schema, setSchema] = useState("");
  const [sql, setSql] = useState(queryTemplates()[0].sql);
  const [savedQueries, setSavedQueries] = useState<string[]>([]);
  const [favoriteQueries, setFavoriteQueries] = useState<string[]>([]);
  const [cloudProvider, setCloudProvider] = useState("AWS S3");
  const [cloudPath, setCloudPath] = useState("");
  const [pythonCode, setPythonCode] = useState("import pandas as pd\n\n# Assign final dataframe to df\n# df = pd.read_sql(...)\n");
  const [metadata, setMetadata] = useState<DataAccessMetadata | null>(() => loadDataAccessMetadata());
  const [quality, setQuality] = useState<DataQualitySummary | null>(null);
  const [qualityLoading, setQualityLoading] = useState(false);
  const [featureProfile, setFeatureProfile] = useState<FeatureProfileResponse | null>(null);
  const [featureProfileError, setFeatureProfileError] = useState("");
  const [featureProfileRetryRevision, setFeatureProfileRetryRevision] = useState(0);
  const [isImporting, setIsImporting] = useState(false);
  const [importError, setImportError] = useState<string | null>(null);
  const [backendImportSynced, setBackendImportSynced] = useState(false);
  const [backendRowCount, setBackendRowCount] = useState<number | null>(null);
  const [libraryDatasets, setLibraryDatasets] = useState<DatasetSummary[]>([]);
  const [selectedDatasetVersions, setSelectedDatasetVersions] = useState<DatasetVersionSummary[]>([]);
  const [selectedLibraryDatasetId, setSelectedLibraryDatasetId] = useState("");
  const [selectedLibraryVersionId, setSelectedLibraryVersionId] = useState("");
  const [libraryLoading, setLibraryLoading] = useState(false);
  // Part A/H1: which dataset+version was actually loaded, plus the real load
  // milestones. Identity is tracked by datasetId/versionId (never by display
  // name or filename) so changing either selector honestly resets the action.
  const [loadedLibraryIdentity, setLoadedLibraryIdentity] = useState<{ datasetId: string; versionId: string } | null>(null);
  const [activeDatasetIdentity, setActiveDatasetIdentity] = useState<CanonicalDatasetIdentity | null>(null);
  const [datasetIdentityError, setDatasetIdentityError] = useState("");
  const [reactivationRequired, setReactivationRequired] = useState(false);
  const [activeActivationRevision, setActiveActivationRevision] = useState("");
  const [analysisPartition, setAnalysisPartition] =
    useState<AnalysisPartitionReadiness>(EMPTY_ANALYSIS_PARTITION);
  const [analysisPartitionHoldoutShare, setAnalysisPartitionHoldoutShare] =
    useState<number>(PARTITION_DEFAULTS.holdoutShare);
  const [analysisPartitionPreview, setAnalysisPartitionPreview] =
    useState<AnalysisPartitionPreview>(EMPTY_ANALYSIS_PARTITION_PREVIEW);
  const [analysisPartitionRationale, setAnalysisPartitionRationale] =
    useState("");
  const [confirmedPartitionPredictorKey, setConfirmedPartitionPredictorKey] =
    useState("");
  const [analysisPartitionResetImpact, setAnalysisPartitionResetImpact] =
    useState<AnalysisPartitionResetImpactState>(
      EMPTY_ANALYSIS_PARTITION_RESET_IMPACT,
    );
  const [analysisPartitionResetHoldoutShare, setAnalysisPartitionResetHoldoutShare] =
    useState("0.2");
  const [analysisPartitionResetRandomSeed, setAnalysisPartitionResetRandomSeed] =
    useState("42");
  const [analysisPartitionResetStratification, setAnalysisPartitionResetStratification] =
    useState<"target" | "none">("target");
  const [analysisPartitionResetReason, setAnalysisPartitionResetReason] =
    useState("");
  const [analysisPartitionResetInvalidationAcknowledged, setAnalysisPartitionResetInvalidationAcknowledged] =
    useState(false);
  const [analysisPartitionResetFeedback, setAnalysisPartitionResetFeedback] =
    useState("");
  const [analysisPartitionResetCompleted, setAnalysisPartitionResetCompleted] =
    useState<{
      partitionId: string;
      previousRevision: number;
      revision: number;
      impacts: string[];
    } | null>(null);
  // Governed target-dependent profiling. The analytical identity includes the
  // dataset version AND the event mapping, so changing either invalidates every
  // target-dependent result rather than leaving stale IV on screen.
  const [weakSignalUndo, setWeakSignalUndo] = useState<Record<string, boolean> | null>(null);
  const [weakSignalNotice, setWeakSignalNotice] = useState("");
  const [loadProgress, setLoadProgress] = useState<DatasetLoadProgress>(IDLE_LOAD_PROGRESS);
  const bureauReviewContextKey = [
    activeDatasetIdentity?.project_id,
    activeDatasetIdentity?.dataset_id,
    activeDatasetIdentity?.dataset_version_id,
    activeDatasetIdentity?.activation_revision,
    target,
    String(eventValue ?? ""),
  ].join(":");
  const [bureauReviewStatusState, setBureauReviewStatusState] = useState<{
    contextKey: string;
    status: BureauReviewPanelStatus;
  } | null>(null);
  const bureauReviewStatus =
    bureauReviewStatusState?.contextKey === bureauReviewContextKey
      ? bureauReviewStatusState.status
      : null;
  const handleBureauReviewStatus = useCallback(
    (status: BureauReviewPanelStatus) =>
      setBureauReviewStatusState({ contextKey: bureauReviewContextKey, status }),
    [bureauReviewContextKey],
  );
  const [bureauReviewResultState, setBureauReviewResultState] = useState<{
    contextKey: string;
    result: BureauReviewPanelResult;
  } | null>(null);
  const bureauReviewResult =
    bureauReviewResultState?.contextKey === bureauReviewContextKey
      ? bureauReviewResultState.result
      : null;
  const handleBureauReviewResult = useCallback(
    (result: BureauReviewPanelResult | null) =>
      setBureauReviewResultState(
        result ? { contextKey: bureauReviewContextKey, result } : null,
      ),
    [bureauReviewContextKey],
  );
  const datasetVersions = loadDatasetVersions();
  const projectId = useWorkflowStore((state) => state.projectId);
  const projectName = useWorkflowStore((state) => state.projectName);
  const workflowDatasetIdentity = useWorkflowStore((state) => state.datasetIdentity);
  const setWorkflowDatasetIdentity = useWorkflowStore((state) => state.setDatasetIdentity);
  const applyAuthoritativeWorkflowState = useWorkflowStore((state) => state.applyAuthoritativeWorkflowState);
  const [reproducibilityContext, setReproducibilityContext] =
    useState<DataAcquisitionReproducibilityContext | null>(null);
  const [reproducibilityContextPhase, setReproducibilityContextPhase] =
    useState<"idle" | "loading" | "pending" | "ready" | "error">("idle");
  const [reproducibilityContextError, setReproducibilityContextError] =
    useState("");
  const [predictorAuthorizationSaving, setPredictorAuthorizationSaving] =
    useState(false);
  const [predictorAuthorizationFeedback, setPredictorAuthorizationFeedback] =
    useState("");
  const [predictorAuthorizationVerificationError, setPredictorAuthorizationVerificationError] =
    useState("");
  const predictorAuthorizationOperationRevision = useRef(0);
  const predictorSelectionTouched = useRef(false);

  useEffect(() => {
    let active = true;
    let requestRevision = 0;
    let localDraftPending = false;
    const controller = new AbortController();

    const refresh = () => {
      if (!projectId) {
        setReproducibilityContext(null);
        setReproducibilityContextPhase("idle");
        setReproducibilityContextError("");
        return;
      }
      const revision = ++requestRevision;
      setReproducibilityContext(null);
      setReproducibilityContextPhase("loading");
      setReproducibilityContextError("");
      void fetchDataAcquisitionReproducibilityContext(
        projectId,
        controller.signal,
      )
        .then((context) => {
          if (!active || revision !== requestRevision) return;
          setReproducibilityContext(context);
          setReproducibilityContextPhase(
            localDraftPending
              ? "pending"
              : context.state === "current"
                ? "ready"
                : "pending",
          );
        })
        .catch((error) => {
          if (!active || controller.signal.aborted || revision !== requestRevision) {
            return;
          }
          setReproducibilityContext(null);
          setReproducibilityContextPhase("error");
          setReproducibilityContextError(
            error instanceof Error
              ? error.message
              : "ATLAS could not verify the exact Data Acquisition context.",
          );
        });
    };
    const markPending = () => {
      localDraftPending = true;
      setReproducibilityContextPhase("pending");
      setReproducibilityContextError("");
    };
    const refreshConfirmed = () => {
      localDraftPending = false;
      refresh();
    };

    refresh();
    window.addEventListener(
      REPRODUCIBILITY_CONTEXT_PENDING_EVENT,
      markPending,
    );
    window.addEventListener(
      REPRODUCIBILITY_CONTEXT_CONFIRMED_EVENT,
      refreshConfirmed,
    );
    return () => {
      active = false;
      requestRevision += 1;
      controller.abort();
      window.removeEventListener(
        REPRODUCIBILITY_CONTEXT_PENDING_EVENT,
        markPending,
      );
      window.removeEventListener(
        REPRODUCIBILITY_CONTEXT_CONFIRMED_EVENT,
        refreshConfirmed,
      );
    };
  }, [projectId]);

  useEffect(() => {
    predictorAuthorizationOperationRevision.current += 1;
    predictorSelectionTouched.current = false;
    setPredictorAuthorizationSaving(false);
    setPredictorAuthorizationFeedback("");
    setPredictorAuthorizationVerificationError("");
  }, [
    projectId,
    activeDatasetIdentity?.dataset_id,
    activeDatasetIdentity?.dataset_version_id,
    target,
    eventValue,
    nonEventValue,
  ]);

  // Dataset Persistence (dataset lifecycle audit): explicit workspace-only vs
  // register-to-Library choice, defaulting to workspace-only per the ADR.
  const [persistenceChoice, setPersistenceChoice] = useState<"workspace" | "register">("workspace");
  const [registerName, setRegisterName] = useState("");
  const [registerDescription, setRegisterDescription] = useState("");
  const [registerTags, setRegisterTags] = useState("");
  const [registering, setRegistering] = useState(false);
  const [registrationResult, setRegistrationResult] = useState<DatasetSummary | null>(null);
  const [registrationError, setRegistrationError] = useState("");
  const [duplicateCandidates, setDuplicateCandidates] = useState<DatasetSummary[]>([]);
  const [checkingDuplicates, setCheckingDuplicates] = useState(false);

  useEffect(() => {
    const saved = loadLocalDataset();
    if (!saved?.headers.length) return;

    // A browser cache is subordinate evidence. Never paint cached rows into a
    // restored project until they match the project's persisted canonical
    // triple exactly; legacy projects must recover through an explicit Dataset
    // Library selection instead of silently inheriting whichever cache happens
    // to be present in this browser.
    if (!workflowDatasetIdentity) return;
    try {
      const localIdentity = requireLocalDatasetCanonicalIdentity(
        projectId,
        saved,
        "Cached Data Acquisition dataset identity",
      );
      resolveExactReopenDatasetIdentity(workflowDatasetIdentity, [localIdentity]);
    } catch {
      return;
    }

    const savedTarget = saved.target ?? "";
    const selectedSet = new Set(saved.selected_columns ?? []);
    setHeaders(saved.headers);
    setRows(saved.rows ?? []);
    setTarget(savedTarget);
    setEventValue(saved.event_value ?? 1);
    setNonEventValue(saved.non_event_value ?? 0);
    setBrowserDataComplete(saved.browser_data_complete === true);
    setKept(
      Object.fromEntries(
        saved.headers.map((header) => [header, header !== savedTarget && selectedSet.has(header)])
      )
    );
    setImportError(null);
    setBackendImportSynced(false);
    setBackendRowCount(saved.registered_row_count ?? null);
    setMessage((current) => current || "Restored the cached modeling dataset and selected features for this browser session.");
    setQuality(
      saved.data_quality ??
        inferDataQuality({ headers: saved.headers, rows: saved.rows ?? [], target: savedTarget || null })
    );
    if (saved.data_access) setMetadata(saved.data_access);
  }, [
    projectId,
    workflowDatasetIdentity?.dataset_id,
    workflowDatasetIdentity?.dataset_version_id,
  ]);

  useEffect(() => {
    const saved = loadLocalDataset();
    if (!workflowDatasetIdentity) {
      const detail =
        "This restored project has no verified Dataset Library binding. Select and load one exact registered dataset version to recover canonical identity.";
      setActiveDatasetIdentity(null);
      setBackendImportSynced(false);
      setReactivationRequired(Boolean(saved));
      setDatasetIdentityError(detail);
      setImportError(detail);
      return;
    }
    let persisted: CanonicalDatasetIdentity;
    try {
      persisted = requireCanonicalDatasetIdentity(
        workflowDatasetIdentity,
        "Persisted Data Acquisition dataset identity",
      );
      if (persisted.project_id !== projectId) {
        throw new Error("The persisted dataset selection belongs to a different project.");
      }
      if (saved) {
        const localIdentity = requireLocalDatasetCanonicalIdentity(
          projectId,
          saved,
          "Restored Data Acquisition dataset identity",
        );
        persisted = resolveExactReopenDatasetIdentity(persisted, [localIdentity]);
      }
    } catch (error) {
      const detail =
        error instanceof Error
          ? error.message
          : "The restored workflow does not contain one exact Dataset Library identity.";
      setActiveDatasetIdentity(null);
      setBackendImportSynced(false);
      setReactivationRequired(true);
      setDatasetIdentityError(detail);
      setImportError(detail);
      return;
    }

    let alive = true;
    const restoreExactIdentity = async () => {
      try {
        const response = await fetch(
          `${BASE}/data/active-identity?project_id=${encodeURIComponent(projectId)}`,
          { credentials: "include" }
        );
        const payload = await response.json().catch(() => null);
        if (!response.ok || !payload?.ok) {
          throw new Error(
            payload?.detail ??
              payload?.error ??
              "The saved Dataset Library version is not currently active. Reactivate it explicitly below.",
          );
        }
        const resolved = resolveExactReopenDatasetIdentity(persisted, [payload]);
        if (!alive) return;
        setActiveDatasetIdentity(resolved);
        setWorkflowDatasetIdentity(resolved);
        setLoadedLibraryIdentity({
          datasetId: resolved.dataset_id,
          versionId: resolved.dataset_version_id,
        });
        setSelectedLibraryDatasetId(resolved.dataset_id);
        setSelectedLibraryVersionId(resolved.dataset_version_id);
        // An exact restored Dataset Library identity must reopen the registered
        // source, including after a defensive remount. Draft target edits do not
        // change this source binding.
        setSourceType("existing");
        void getDataset(resolved.dataset_id).then((dataset) => {
          if (alive) setSelectedDatasetVersions(dataset.versions);
        }).catch(() => undefined);
        setBackendImportSynced(true);
        setReactivationRequired(false);
        setActiveActivationRevision(
          payload.activation_revision == null ? "" : String(payload.activation_revision),
        );
        setDatasetIdentityError("");
        setImportError(null);
      } catch (error) {
        if (!alive) return;
        const detail =
          error instanceof Error
            ? error.message
            : "The exact registered Dataset Library version could not be restored.";
        setActiveDatasetIdentity(null);
        setBackendImportSynced(false);
        setReactivationRequired(true);
        setActiveActivationRevision("");
        setSourceType("existing");
        setSelectedLibraryDatasetId(persisted.dataset_id);
        setSelectedLibraryVersionId(persisted.dataset_version_id);
        void getDataset(persisted.dataset_id).then((dataset) => {
          if (alive) setSelectedDatasetVersions(dataset.versions);
        }).catch(() => undefined);
        setDatasetIdentityError(detail);
        setImportError(detail);
      }
    };
    void restoreExactIdentity();
    return () => {
      alive = false;
    };
  }, [
    projectId,
    setWorkflowDatasetIdentity,
    workflowDatasetIdentity?.dataset_id,
    workflowDatasetIdentity?.dataset_version_id,
  ]);

  useEffect(() => {
    if (sourceType !== "existing") return;
    let alive = true;
    setLibraryLoading(true);
    listDatasets()
      .then((payload) => {
        if (!alive) return;
        setLibraryDatasets(payload.datasets);
      })
      .catch((error) => setMessage(error instanceof Error ? error.message : "ATLAS could not load Dataset Library records."))
      .finally(() => alive && setLibraryLoading(false));
    return () => {
      alive = false;
    };
  }, [sourceType, selectedLibraryDatasetId]);

  const fullSourceRows = rows;
  const registeredRowCount = backendRowCount ?? fullSourceRows.length;
  const completeBrowserDataset = browserDataComplete && fullSourceRows.length === registeredRowCount;
  const previewRows = useMemo(() => applyPreviewSampling({
    rows: fullSourceRows,
    method: previewSamplingMethod,
    rowLimit: previewRowLimit,
    seed: previewRandomSeed,
    stratificationColumn: previewStratificationColumn,
    timeColumn: previewTimeColumn,
  }), [fullSourceRows, previewSamplingMethod, previewRowLimit, previewRandomSeed, previewStratificationColumn, previewTimeColumn]);
  const profilingRows = useMemo(
    () => fullSourceRows.slice(0, Math.max(1, profileRowLimit)),
    [fullSourceRows, profileRowLimit]
  );
  const targetAnalysisRows = completeBrowserDataset ? fullSourceRows : profilingRows;
  const targetInfo = useMemo(() => targetMeta(targetAnalysisRows, target), [targetAnalysisRows, target]);

  // UX-DATAACQ-004 / Part C: the active source's governed identity decides which
  // persistence UI applies. `datasetLibraryLink` is the authoritative signal --
  // it is only ever written with a real datasetId/versionId pair.
  const datasetLibraryLink = useMemo(() => {
    if (!activeDatasetIdentity) return null;
    const savedLink = loadLocalDataset()?.dataset_library;
    return {
      ...(savedLink ?? {}),
      datasetId: activeDatasetIdentity.dataset_id,
      versionId: activeDatasetIdentity.dataset_version_id,
    };
  }, [headers, fileName, backendImportSynced, loadedLibraryIdentity, activeDatasetIdentity]);
  const datasetSourceKind: DatasetSourceKind = useMemo(
    () =>
      resolveDatasetSourceKind({
        sourceType,
        libraryLink: datasetLibraryLink,
        registeredDatasetId: registrationResult?.datasetId ?? null,
      }),
    [sourceType, datasetLibraryLink, registrationResult]
  );
  const persistenceMode = resolvePersistenceMode(datasetSourceKind);

  // Part F: the Target Profile must not report a rare-event rate computed from a
  // ~100-row browser preview. Backend full-population profiling wins when present.
  const governedProfileRequest = useMemo(
    () =>
      target
        ? {
            projectId,
            datasetId: activeDatasetIdentity?.dataset_id ?? null,
            versionId: activeDatasetIdentity?.dataset_version_id ?? null,
            target,
            eventValue,
            nonEventValue,
            problemType: (targetInfo.kind === "continuous" ? "regression" : "classification") as
              | "regression"
              | "classification",
          }
        : null,
    [projectId, activeDatasetIdentity, target, eventValue, nonEventValue, targetInfo.kind]
  );
  const governedProfile = useTargetProfile(governedProfileRequest);
  const governedPredictors = useMemo(() => {
    const map = new Map<string, PredictorProfile>();
    for (const row of governedProfile.profile?.predictors ?? []) map.set(row.predictor, row);
    return map;
  }, [governedProfile.profile]);

  // Target Distribution performance: for a registered Dataset Library version the
  // counts come from a dedicated bounded server aggregate that loads independently
  // of quality profiling. Reading them out of the full quality profile cost ~4s of
  // server compute on the 170,884-row CLASS_TRAIN asset just to obtain two rows.
  const targetDistributionRequest = useMemo(() => {
    if (!target || targetInfo.kind === "continuous") return null;
    if (!activeDatasetIdentity) return null;
    return {
      projectId: activeDatasetIdentity.project_id,
      datasetId: activeDatasetIdentity.dataset_id,
      versionId: activeDatasetIdentity.dataset_version_id,
      target,
      eventValue,
      nonEventValue,
    };
  }, [target, targetInfo.kind, activeDatasetIdentity, eventValue, nonEventValue]);

  const serverDistribution = useTargetDistribution(targetDistributionRequest);

  // A workspace dataset the browser already holds in full needs no server round
  // trip -- those counts are already exact and instant.
  const localDistribution = useMemo(
    () =>
      targetDistributionRequest
        ? null
        : buildTargetDistribution({
            target,
            classDistribution: quality?.classDistribution,
            eventValue: quality?.targetEventValue ?? eventValue,
            nonEventValue,
          }),
    [targetDistributionRequest, target, quality?.classDistribution, quality?.targetEventValue, eventValue, nonEventValue]
  );

  const targetDistribution = useMemo(() => {
    if (!targetDistributionRequest) return localDistribution;
    if (!serverDistribution.result?.supported) return null;
    return buildTargetDistribution({
      target,
      classDistribution: serverDistribution.result.classDistribution,
      eventValue,
      nonEventValue,
    });
  }, [targetDistributionRequest, localDistribution, serverDistribution.result, target, eventValue, nonEventValue]);

  const targetDistributionState = useMemo(() => {
    if (!target) return "empty" as const;
    if (targetInfo.kind === "continuous") return "unsupported" as const;
    if (targetDistributionRequest) {
      if (serverDistribution.phase === "queued" || serverDistribution.phase === "running") return "loading" as const;
      if (serverDistribution.phase === "failed") return "error" as const;
      if (serverDistribution.phase === "unsupported") return "unsupported" as const;
      return targetDistribution ? ("ready" as const) : ("empty" as const);
    }
    if (qualityLoading || !quality) return "loading" as const;
    return targetDistribution ? ("ready" as const) : ("empty" as const);
  }, [target, targetInfo.kind, targetDistributionRequest, serverDistribution.phase, qualityLoading, quality, targetDistribution]);
  const selectable = headers.filter((header) =>
    predictorIsEligible(header, { headers, rows: profilingRows, target }),
  );
  const selected = selectable.filter((header) => kept[header]);
  const selectedPredictorKey = canonicalPredictorSelectionKey(selected);
  const governedPredictorKey = canonicalPredictorSelectionKey(
    reproducibilityContext?.predictor_authorization?.selected_predictors ?? [],
  );
  const reproducibilityBaselineExact = reproducibilityBaselineMatchesPartition(
    reproducibilityContext,
    activeDatasetIdentity,
    analysisPartition.partition,
    target,
    eventValue,
    nonEventValue,
  );

  useEffect(() => {
    setAnalysisPartitionHoldoutShare(PARTITION_DEFAULTS.holdoutShare);
    setAnalysisPartitionPreview(EMPTY_ANALYSIS_PARTITION_PREVIEW);
    setAnalysisPartitionRationale("");
    setConfirmedPartitionPredictorKey("");
    if (!activeDatasetIdentity || !target) {
      setAnalysisPartition({
        ...EMPTY_ANALYSIS_PARTITION,
        phase: "required",
        code: !activeDatasetIdentity
          ? "dataset_identity_unavailable"
          : "target_contract_stale",
        message: !activeDatasetIdentity
          ? "Activate the exact registered dataset version before confirming an Analysis Partition."
          : "Confirm the governed target before confirming an Analysis Partition.",
      });
      return;
    }

    const controller = new AbortController();
    setAnalysisPartition((current) => ({
      ...current,
      phase: "checking",
      code: "analysis_partition_checking",
      message: "Checking for an exact current Analysis Partition...",
    }));
    void readAnalysisPartitionReadiness(
      activeDatasetIdentity,
      target,
      eventValue,
      nonEventValue,
      controller.signal,
    )
      .then((next) => {
        if (!controller.signal.aborted) {
          setAnalysisPartition(next);
        }
      })
      .catch((cause) => {
        if (controller.signal.aborted) return;
        setAnalysisPartition({
          phase: "error",
          code: "analysis_partition_status_failed",
          message:
            cause instanceof Error
              ? cause.message
              : "ATLAS could not verify the Analysis Partition.",
          recovery: "Confirm the backend is available, then retry the readiness check.",
          partition: null,
        });
      });
    return () => controller.abort();
  }, [
    activeDatasetIdentity?.project_id,
    activeDatasetIdentity?.dataset_id,
    activeDatasetIdentity?.dataset_version_id,
    target,
    eventValue,
    nonEventValue,
  ]);

  useEffect(() => {
    const resetPreviewSettled =
      analysisPartitionResetMode &&
      (analysisPartition.phase === "confirming" ||
        Boolean(analysisPartitionResetCompleted));
    if (resetPreviewSettled) {
      return undefined;
    }
    const resetPreviewReady =
      analysisPartitionResetMode &&
      analysisPartitionResetImpact.phase === "ready" &&
      Boolean(analysisPartitionResetImpact.partition);
    const initialPreviewReady =
      !analysisPartitionResetMode && analysisPartition.phase === "required";
    if (!activeDatasetIdentity || !target || (!resetPreviewReady && !initialPreviewReady)) {
      return undefined;
    }
    const selectedHoldoutShare = analysisPartitionResetMode
      ? Number(analysisPartitionResetHoldoutShare)
      : analysisPartitionHoldoutShare;
    const contractPartition = analysisPartitionResetMode
      ? analysisPartitionResetImpact.partition
      : analysisPartition.partition;
    if (
      analysisPartitionResetMode &&
      contractPartition &&
      Number.isFinite(selectedHoldoutShare) &&
      Math.abs(
        selectedHoldoutShare - Number(contractPartition.holdout_share),
      ) < 1e-9
    ) {
      setAnalysisPartitionPreview({
        ...EMPTY_ANALYSIS_PARTITION_PREVIEW,
        code: "analysis_partition_reset_change_required",
        message:
          "Choose a different governed split ratio to preview a replacement revision. The current sealed partition remains unchanged.",
      });
      return undefined;
    }
    const policy = initialAnalysisPartitionPolicy(
      selectedHoldoutShare,
      targetInfo.kind === "continuous" ? "regression" : "classification",
    );
    const controller = new AbortController();
    setAnalysisPartitionPreview({
      ...EMPTY_ANALYSIS_PARTITION_PREVIEW,
      phase: "loading",
      code: "analysis_partition_preview_loading",
      message: "Calculating exact governed counts and split sufficiency...",
    });
    void readAnalysisPartitionPreview(
      activeDatasetIdentity,
      target,
      eventValue,
      nonEventValue,
      targetInfo.kind === "continuous" ? "regression" : "classification",
      policy,
      {
        targetContractId: String(contractPartition?.target_contract_id ?? ""),
        predictorAuthorizationId: analysisPartitionResetMode
          ? currentDurablePredictorAuthorizationId(contractPartition)
          : String(contractPartition?.predictor_authorization_id ?? ""),
      },
      controller.signal,
      analysisPartitionResetMode && contractPartition
        ? {
            analysisPartitionId: String(
              contractPartition.analysis_partition_id ?? "",
            ),
            revision: Number(contractPartition.revision),
          }
        : undefined,
    )
      .then((preview) => {
        if (!controller.signal.aborted) setAnalysisPartitionPreview(preview);
      })
      .catch((cause) => {
        if (controller.signal.aborted) return;
        setAnalysisPartitionPreview({
          ...EMPTY_ANALYSIS_PARTITION_PREVIEW,
          phase: "error",
          code: "analysis_partition_preview_failed",
          message:
            cause instanceof Error
              ? cause.message
              : "ATLAS could not preview the selected Analysis Partition.",
        });
      });
    return () => controller.abort();
  }, [
    activeDatasetIdentity?.project_id,
    activeDatasetIdentity?.dataset_id,
    activeDatasetIdentity?.dataset_version_id,
    analysisPartition.phase,
    analysisPartitionHoldoutShare,
    analysisPartitionResetMode,
    analysisPartitionResetHoldoutShare,
    analysisPartitionResetImpact.phase,
    analysisPartitionResetImpact.partition,
    analysisPartitionResetCompleted,
    eventValue,
    nonEventValue,
    target,
    targetInfo.kind,
  ]);

  useEffect(() => {
    if (!analysisPartitionResetMode) {
      setAnalysisPartitionResetImpact(
        EMPTY_ANALYSIS_PARTITION_RESET_IMPACT,
      );
      setAnalysisPartitionResetReason("");
      setAnalysisPartitionResetInvalidationAcknowledged(false);
      setAnalysisPartitionResetFeedback("");
      setAnalysisPartitionResetCompleted(null);
      return;
    }
    if (!activeDatasetIdentity) {
      setAnalysisPartitionResetImpact({
        phase: "loading",
        message:
          "Waiting for the exact governed Dataset Library identity before loading reset impacts...",
        impacts: [],
        partition: null,
      });
      return;
    }

    const controller = new AbortController();
    setAnalysisPartitionResetImpact((current) => ({
      ...current,
      phase: "loading",
      message: "Loading the durable reset impact for the exact current partition...",
    }));
    setAnalysisPartitionResetFeedback("");
    setAnalysisPartitionResetCompleted(null);
    void readAnalysisPartitionResetImpact(
      activeDatasetIdentity,
      controller.signal,
    )
      .then((impact) => {
        if (controller.signal.aborted) return;
        setAnalysisPartitionResetImpact(impact);
        const partition = impact.partition;
        if (impact.phase === "ready" && partition) {
          const holdoutShare = Number(partition.holdout_share);
          const randomSeed = Number(partition.random_seed);
          setAnalysisPartitionResetHoldoutShare(
            Number.isFinite(holdoutShare)
              ? String(holdoutShare)
              : String(PARTITION_DEFAULTS.holdoutShare),
          );
          setAnalysisPartitionResetRandomSeed(
            Number.isInteger(randomSeed)
              ? String(randomSeed)
              : String(PARTITION_DEFAULTS.randomSeed),
          );
          setAnalysisPartitionResetStratification(
            partition.stratification_policy === "none" ? "none" : "target",
          );
          window.setTimeout(() => {
            document
              .querySelector('[data-testid="analysis-partition-reset-workspace"]')
              ?.scrollIntoView({ behavior: "smooth", block: "center" });
          }, 0);
        }
      })
      .catch((cause) => {
        if (controller.signal.aborted) return;
        setAnalysisPartitionResetImpact({
          phase: "error",
          message:
            cause instanceof Error
              ? cause.message
              : "ATLAS could not load the governed reset impact.",
          impacts: [],
          partition: null,
        });
      });
    return () => controller.abort();
  }, [
    analysisPartitionResetMode,
    activeDatasetIdentity?.project_id,
    activeDatasetIdentity?.dataset_id,
    activeDatasetIdentity?.dataset_version_id,
    activeDatasetIdentity?.activation_revision,
    target,
    eventValue,
    nonEventValue,
  ]);

  useEffect(() => {
    if (
      shouldHydratePredictorSelectionFromGovernedBaseline({
        partitionCurrent: analysisPartition.phase === "current",
        baselineExact: reproducibilityBaselineExact,
        selectionTouched: predictorSelectionTouched.current,
        governedPredictors:
          reproducibilityContext?.predictor_authorization?.selected_predictors ??
          [],
        localPredictors: selected,
      })
    ) {
      const governedSelection = new Set(
        reproducibilityContext?.predictor_authorization?.selected_predictors ??
          [],
      );
      setKept(
        Object.fromEntries(
          headers.map((header) => [header, governedSelection.has(header)]),
        ),
      );
    }
  }, [
    analysisPartition.phase,
    headers,
    reproducibilityBaselineExact,
    reproducibilityContext?.predictor_authorization?.selected_predictors,
    selected,
  ]);

  useEffect(() => {
    if (
      analysisPartition.phase === "current" &&
      (reproducibilityContextPhase === "ready" ||
        reproducibilityContextPhase === "pending") &&
      reproducibilityBaselineExact &&
      governedPredictorKey &&
      !predictorAuthorizationSaving &&
      !predictorAuthorizationVerificationError
    ) {
      setConfirmedPartitionPredictorKey(governedPredictorKey);
    }
  }, [
    analysisPartition.phase,
    analysisPartition.partition?.analysis_partition_id,
    governedPredictorKey,
    predictorAuthorizationSaving,
    predictorAuthorizationVerificationError,
    reproducibilityBaselineExact,
    reproducibilityContextPhase,
  ]);

  const predictorAuthorizationDraft = derivePredictorAuthorizationDraftState({
    partitionCurrent: analysisPartition.phase === "current",
    confirmedSelectionKey: confirmedPartitionPredictorKey,
    selectedPredictors: selected,
    saving: predictorAuthorizationSaving,
    baselinePhase: reproducibilityContextPhase,
  });
  const predictorAuthorizationActionLabel =
    predictorAuthorizationVerificationError
      ? "Retry Predictor Authorization"
      : predictorAuthorizationDraft.actionLabel;

  const analysisPartitionIsCurrent = analysisPartition.phase === "current";
  const analysisPartitionBlockingReason = analysisPartitionIsCurrent
    ? ""
    : analysisPartition.phase === "checking" || analysisPartition.phase === "confirming"
      ? "Wait for ATLAS to verify the Analysis Partition."
      : analysisPartition.message ||
        "Confirm the selected Analysis Partition before continuing to EDA.";

  // Part D: a single readiness status derived only from findings ATLAS already computes.

  // Part B: ONE derivation feeds every Data Acquisition status. Previously the
  // hero used `nextDisabledReason`, the strip used `readiness.status`, and the
  // checkpoint used READINESS_LABELS -- three answers to one question.
  const [dataAcquisitionReviewed, setDataAcquisitionReviewed] = useState(false);
  const baseAcquisitionStatus = useMemo(
    () =>
      deriveDataAcquisitionStatus({
        hasSelectedVersion: Boolean(activeDatasetIdentity?.dataset_version_id),
        isRegisteredAsset: Boolean(activeDatasetIdentity?.dataset_id),
        isLinkedToProject: Boolean(activeDatasetIdentity?.project_id === projectId),
        isLoaded: Boolean(headers.length && backendImportSynced && activeDatasetIdentity),
        isLoading: isImporting,
        loadError: datasetIdentityError || importError,
        target,
        eventValue,
        nonEventValue,
        selectedPredictorCount:
          reproducibilityContext?.predictor_authorization?.funnel
            .authorized_predictor_count ?? 0,
        profilePhase: governedProfile.phase,
        profileError: governedProfile.error,
        authoritativeEventCount: governedProfile.profile?.quality.eventCount ?? governedProfile.quality?.quality.eventCount ?? null,
        authoritativeNonEventCount: governedProfile.profile?.quality.nonEventCount ?? governedProfile.quality?.quality.nonEventCount ?? null,
        duplicateRows: governedProfile.quality?.quality.duplicateRows ?? governedProfile.profile?.quality.duplicateRows ?? null,
        columnsWithMissingValues:
          governedProfile.quality?.quality.columnsWithMissingValues ?? governedProfile.profile?.quality.columnsWithMissingValues ?? null,
        unusuallyStrongPredictorCount: (governedProfile.profile?.predictors ?? []).filter(
          (row) => row.ivStatus === "available" && (row.iv ?? 0) >= 0.5
        ).length,
        isRareEvent: Boolean(
          (governedProfile.quality?.quality.eventRate ?? governedProfile.profile?.quality.eventRate ?? 0) > 0 &&
            (governedProfile.quality?.quality.eventRate ?? governedProfile.profile?.quality.eventRate ?? 1) < 0.01
        ),
        reviewCompleted: dataAcquisitionReviewed,
      }),
    [
      activeDatasetIdentity, projectId, datasetIdentityError,
      headers.length, backendImportSynced, isImporting, importError, target, eventValue, nonEventValue,
      reproducibilityContext, governedProfile.phase, governedProfile.error, governedProfile.profile,
      governedProfile.quality, dataAcquisitionReviewed,
    ]
  );
  const acquisitionStatus = useMemo<DataAcquisitionStatus>(() => {
    if (analysisPartitionResetMode) {
      const resetComplete = Boolean(analysisPartitionResetCompleted);
      return {
        ...baseAcquisitionStatus,
        readiness: "blocked",
        readinessLabel: resetComplete
          ? "Split changed · downstream stale"
          : "Governed split-ratio impact review",
        readinessTone: resetComplete ? "warning" : "danger",
        canContinue: false,
        blockingReasons: [
          resetComplete
            ? "The replacement partition is current, but downstream artifacts remain stale. Close the change review before making a separate navigation decision."
            : "Complete or cancel the governed split-ratio impact review before continuing.",
        ],
        recommendedAction: resetComplete
          ? "Review the new partition revision and stale-artifact list, then close change mode without automatic navigation."
          : "Review every invalidation impact, choose the replacement ratio, and explicitly confirm or cancel the change.",
        currentActiveMilestone: "Analysis Partition split change",
        continueLabel: resetComplete
          ? "Downstream stale · review split result"
          : "Complete split-ratio impact review",
      };
    }
    if (predictorAuthorizationVerificationError) {
      const reason = `Predictor authorization update is not verified: ${predictorAuthorizationVerificationError}`;
      return {
        ...baseAcquisitionStatus,
        readiness: "blocked",
        readinessLabel: "Predictor authorization verification failed",
        readinessTone: "danger",
        canContinue: false,
        blockingReasons: [reason],
        recommendedAction: "Retry the predictor authorization update and exact partition read-back.",
        currentActiveMilestone: "Predictor Authorization",
        continueLabel: "Retry Predictor Authorization to Continue",
      };
    }
    if (predictorAuthorizationDraft.dirty) {
      return {
        ...baseAcquisitionStatus,
        readiness: "blocked",
        readinessLabel: predictorAuthorizationSaving
          ? "Updating predictor authorization"
          : "Predictor authorization update required",
        readinessTone: predictorAuthorizationSaving ? "info" : "warning",
        canContinue: false,
        blockingReasons: [predictorAuthorizationDraft.reason],
        recommendedAction: predictorAuthorizationDraft.reason,
        currentActiveMilestone: "Predictor Authorization",
        continueLabel: predictorAuthorizationSaving
          ? "Updating Predictor Authorization..."
          : predictorAuthorizationDraft.canUpdate
            ? "Update Predictor Authorization to Continue"
            : predictorAuthorizationDraft.canRetryBaseline
              ? "Retry Predictor Authorization Context"
              : predictorAuthorizationDraft.needsBaseline
                ? "Verifying Predictor Authorization..."
                : "Review Predictor Selection to Continue",
      };
    }
    if (!baseAcquisitionStatus.canContinue) {
      return baseAcquisitionStatus;
    }
    const specialValueReviewExpected = Boolean(
      activeDatasetIdentity && headers.length && registeredRowCount && target,
    );
    if (
      specialValueReviewExpected &&
      (!bureauReviewStatus || bureauReviewStatus.loading || bureauReviewStatus.blocking)
    ) {
      const unresolved = bureauReviewStatus?.unresolvedRequirements ?? 0;
      const loadingReview = !bureauReviewStatus || bureauReviewStatus.loading;
      return {
        ...baseAcquisitionStatus,
        readiness: "blocked",
        readinessLabel: loadingReview
          ? "Verifying special-value review"
          : "Special-value review required",
        readinessTone: loadingReview ? "info" : "danger",
        canContinue: false,
        blockingReasons: [
          loadingReview
            ? "Wait for ATLAS to read the exact special-value review status."
            : unresolved
              ? `${unresolved} special-value treatment requirement${unresolved === 1 ? "" : "s"} remain unresolved.`
              : "Confirm the governed Special-Value Treatment Review before continuing.",
        ],
        recommendedAction: loadingReview
          ? "Wait for the exact dataset-version review status."
          : "Open Special-Value Treatment Review, resolve every required rationale, and confirm the governed treatment contract.",
        currentActiveMilestone: "Special-Value Treatment Review",
        continueLabel: "Complete Special-Value Review to Continue",
      };
    }
    if (analysisPartitionIsCurrent) return baseAcquisitionStatus;
    const documentationPending =
      analysisPartition.phase === "documentation_pending" ||
      analysisPartition.phase === "documenting";
    const checking =
      analysisPartition.phase === "checking" ||
      analysisPartition.phase === "confirming" ||
      analysisPartition.phase === "documenting";
    return {
      ...baseAcquisitionStatus,
      readiness: "blocked",
      readinessLabel: documentationPending
        ? analysisPartition.phase === "documenting"
          ? "Completing partition documentation"
          : "Partition documentation pending"
        : checking
          ? "Verifying Analysis Partition"
          : "Analysis Partition required",
      readinessTone: documentationPending ? "warning" : checking ? "info" : "danger",
      canContinue: false,
      blockingReasons: [analysisPartitionBlockingReason],
      recommendedAction: documentationPending
        ? "Complete the evidence and MDD sidecars for the exact sealed partition."
        : checking
          ? "Wait for the governed partition verification to finish."
          : "Review and confirm the selected Analysis Partition.",
      currentActiveMilestone: documentationPending
        ? "Analysis Partition documentation"
        : "Analysis Partition",
      continueLabel: documentationPending
        ? "Complete Partition Documentation"
        : checking
          ? "Verifying Analysis Partition..."
          : "Confirm Analysis Partition to Continue",
    };
  }, [
    analysisPartitionResetCompleted,
    analysisPartitionResetMode,
    analysisPartition.phase,
    analysisPartitionBlockingReason,
    analysisPartitionIsCurrent,
    activeDatasetIdentity,
    baseAcquisitionStatus,
    bureauReviewStatus,
    headers.length,
    predictorAuthorizationDraft,
    predictorAuthorizationSaving,
    predictorAuthorizationVerificationError,
    registeredRowCount,
    selected.length,
    target,
  ]);

  const sqlWarnings = useMemo(() => validateSql(sql), [sql]);
  const generatedMetadata = useMemo(() => {
    if (!headers.length) return null;
    return buildDataAccessMetadata({
      dataset: { headers, rows: completeBrowserDataset ? fullSourceRows : profilingRows, target },
      sourceType,
      sourceLabel:
        sourceType === "sql"
          ? `${provider} SQL`
          : sourceType === "cloud"
            ? cloudProvider
            : sourceType === "python"
              ? "Python loader"
              : sourceType === "existing"
                ? `Dataset Library: ${libraryDatasets.find((dataset) => dataset.datasetId === selectedLibraryDatasetId)?.name ?? (fileName || "Existing dataset")}`
                : fileName || "Uploaded file",
      fileName,
      fileType: fileName.split(".").pop(),
      connectionName,
      provider,
      database,
      schema,
      sqlQuery: sourceType === "sql" ? sql : undefined,
      cloudProvider: sourceType === "cloud" ? cloudProvider : undefined,
      cloudPath: sourceType === "cloud" ? cloudPath : undefined,
      pythonCode: sourceType === "python" ? pythonCode : undefined,
      samplingMethod: "full",
      samplingDetail: "Registered modeling dataset",
      rowCountOverride: registeredRowCount,
    });
  }, [headers, fullSourceRows, profilingRows, completeBrowserDataset, target, sourceType, provider, cloudProvider, fileName, connectionName, database, schema, sql, cloudPath, pythonCode, registeredRowCount, libraryDatasets, selectedLibraryDatasetId]);


  /** IV for one predictor from the authoritative profile. While the profile is
   *  still running every eligible predictor reports `pending` ("Calculating"),
   *  never a zero placeholder. */
  function governedIv(column: string): Pick<PredictorProfile, "iv" | "ivStatus"> {
    const row = governedPredictors.get(column);
    if (row) return { iv: row.iv, ivStatus: row.ivStatus };
    if (governedProfile.phase === "artifact_missing") return { iv: null, ivStatus: "unavailable_not_eligible" };
    if (governedProfile.phase === "failed") return { iv: null, ivStatus: "failed" };
    return { iv: null, ivStatus: "pending" };
  }

  // Part F: counts by analytical role. The target is never counted as an
  // unavailable predictor.
  const predictorCounts = useMemo(
    () => predictorEvaluationCounts(governedProfile.profile, target),
    [governedProfile.profile, target]
  );

  const bureauSpecialValueProfiles = useMemo(() => {
    const profiles = new Map<
      string,
      {
        count: number;
        rate: number;
        codes: number[];
        datatype: string;
        reviewStatus: "Review required" | "Reviewed draft" | "Confirmed" | "Detected";
      }
    >();
    if (!bureauReviewResult) return profiles;
    const openItems = new Set(bureauReviewResult.review.open_items);
    const reviewedVariables = new Set(
      bureauReviewResult.review.variable_decisions.map(
        (decision) => decision.variable,
      ),
    );
    for (const variable of bureauReviewResult.detection.variables) {
      if (variable.special_value_count <= 0) continue;
      const reviewStatus = openItems.has(variable.variable)
        ? "Review required"
        : bureauReviewResult.review.status === "confirmed"
          ? "Confirmed"
          : reviewedVariables.has(variable.variable)
            ? "Reviewed draft"
            : "Detected";
      profiles.set(variable.variable, {
        count: variable.special_value_count,
        rate: variable.special_value_frequency,
        codes: variable.special_values.map((profile) => profile.value),
        datatype: variable.datatype,
        reviewStatus,
      });
    }
    return profiles;
  }, [bureauReviewResult]);

  const variableSummary = useMemo(() => {
    const withSpecialValues = (column: string) => {
      const specialValues = bureauSpecialValueProfiles.get(column);
      return {
        specialValueCount: specialValues?.count ?? 0,
        specialValueRate: specialValues?.rate ?? 0,
        specialValueCodes: specialValues?.codes ?? [],
        specialValueReviewStatus: specialValues?.reviewStatus ?? "Not detected",
      };
    };
    if (featureProfile) {
      return featureProfile.features.map((row) => {
        return {
          column: row.predictor,
          type: row.datatype,
          missingPct: row.missingPercent,
          distinct: row.distinctCount,
          mean: row.mean,
          min: row.minimum,
          max: row.maximum,
          ...withSpecialValues(row.predictor),
          // Root causes 1-3: IV now comes from the authoritative server profile and
          // carries an explicit status. `null` stays `null` -- it is never coerced
          // to a number, and therefore never rendered as a misleading 0.0000.
          iv: row.iv,
          corr: row.correlationWithTarget,
          role: row.role,
          exclusionReason: row.exclusionReason,
        };
      });
    }

    // Exact headers and exact-lineage detection remain visible when the richer
    // feature profile is temporarily unavailable. Target-directed metrics stay
    // null: this fallback never calculates or invents IV/correlation evidence.
    const fallbackDataset: LocalDataset = {
      headers,
      rows: [],
      target,
      selected_columns: selected,
    };
    const fallbackColumns = Array.from(
      new Set([...headers, ...bureauSpecialValueProfiles.keys()]),
    );
    return fallbackColumns.map((column) => {
      const eligibility = predictorEligibility(column, fallbackDataset);
      const specialValues = bureauSpecialValueProfiles.get(column);
      return {
        column,
        type: specialValues?.datatype ?? "Unavailable",
        missingPct: undefined,
        distinct: undefined,
        mean: undefined,
        min: undefined,
        max: undefined,
        ...withSpecialValues(column),
        iv: null,
        corr: null,
        role: eligibility.role,
        exclusionReason:
          eligibility.reason ||
          "Variable statistics are pending the authoritative feature profile.",
      };
    });
  }, [bureauSpecialValueProfiles, featureProfile, headers, selected, target]);
  const predictorVariableSummary = useMemo(
    () => variableSummary.filter((row) => row.column !== target),
    [variableSummary, target],
  );

  useEffect(() => {
    if (!headers.length || !target || !profilingRows.length) {
      setFeatureProfile(null);
      setFeatureProfileError("");
      return;
    }
    let alive = true;
    const profileDataset: LocalDataset = {
      headers,
      rows: profilingRows,
      dataset_id: activeDatasetIdentity?.dataset_id,
      dataset_version_id: activeDatasetIdentity?.dataset_version_id,
      dataset_version: activeDatasetIdentity?.dataset_version_id,
      target,
      selected_columns: selected,
      problem_type: targetInfo.kind === "continuous" ? "regression" : "classification",
      registered_row_count: registeredRowCount,
      browser_data_complete: completeBrowserDataset,
      event_value: eventValue,
      non_event_value: nonEventValue,
    };
    const browserProfile = () => profileFeaturesInBrowser(
      profileDataset,
      completeBrowserDataset ? fullSourceRows : profilingRows,
      completeBrowserDataset ? "complete_browser_dataset" : "preview_profile",
    );
    if (backendImportSynced) {
      if (!activeDatasetIdentity) {
        setFeatureProfile(null);
        setFeatureProfileError(
          "The exact active Dataset Library identity is required before predictor statistics can be loaded.",
        );
        return;
      }
      // Root cause 2: this used to `.catch(() => setFeatureProfile(browserProfile()))`,
      // silently replacing a failed governed profile with a 100-row preview
      // computation that still reported itself as full_dataset. A failure is now
      // a failure: the authoritative profile hook surfaces it, and the browser
      // profile is never substituted for target-dependent statistics.
      setFeatureProfile(null);
      setFeatureProfileError("");
      fetchFullFeatureProfile(profileDataset, projectId)
        .then((payload) => {
          if (!alive) return;
          setFeatureProfile(payload);
          setFeatureProfileError("");
        })
        .catch((cause: unknown) => {
          if (!alive) return;
          setFeatureProfile(null);
          setFeatureProfileError(
            cause instanceof Error && cause.message.trim()
              ? cause.message
              : "The authoritative predictor statistics could not be loaded.",
          );
        });
    } else {
      // No backend population at all: the browser profile is retained ONLY for
      // its non-target-dependent inspection columns. Its scope says preview, and
      // IV comes from the authoritative profile (or reports why it cannot).
      setFeatureProfile(browserProfile());
      setFeatureProfileError("");
    }
    return () => {
      alive = false;
    };
  }, [headers, target, profilingRows, fullSourceRows, selected.join("|"), targetInfo.kind, registeredRowCount, completeBrowserDataset, backendImportSynced, eventValue, nonEventValue, activeDatasetIdentity, featureProfileRetryRevision, projectId]);

  useEffect(() => {
    if (!headers.length || !profilingRows.length) {
      setQuality(null);
      return;
    }
    let alive = true;
    const browserQuality = () => {
      const base = inferDataQuality({ headers, rows: completeBrowserDataset ? fullSourceRows : profilingRows, target: target || null });
      return {
        ...base,
        // Part H3/2: class counts are only supplied when the browser genuinely holds
        // the complete registered dataset. For a bounded preview they are omitted, so
        // the distribution chart shows an honest empty state rather than preview-derived
        // proportions that would misrepresent a rare-event population.
        classDistribution: completeBrowserDataset
          ? computeClassDistributionFromRows(fullSourceRows, target) ?? undefined
          : undefined,
        targetEventValue: completeBrowserDataset ? eventValue : undefined,
        profileScope: completeBrowserDataset ? "complete_browser_dataset" as const : "preview_profile" as const,
        profiledRowCount: completeBrowserDataset ? fullSourceRows.length : profilingRows.length,
        registeredRowCount,
        rowCount: registeredRowCount,
        warnings: completeBrowserDataset ? base.warnings : ["This report is based on configured profiling rows, not the full registered dataset."],
        readinessStatus: "needs_review" as const,
      };
    };
    if (backendImportSynced) {
      // Part H3/10: reject stale asynchronous results. `alive` is flipped by this
      // effect's own cleanup, so a response that arrives after the project,
      // dataset/version, or target changed is discarded instead of overwriting
      // the newer selection's profile.
      setQualityLoading(true);
      if (!activeDatasetIdentity) {
        setQuality(null);
        setQualityLoading(false);
        setMessage("Full-population data quality profiling requires an exact active Dataset Library version.");
        return () => {
          alive = false;
        };
      }
      fetchFullDataQualityProfile({
        projectId,
        datasetIdentity: activeDatasetIdentity,
        target,
        eventValue,
        nonEventValue,
        selectedColumns: selected,
      })
        .then((payload) => {
          if (!alive) return;
          setQuality(payload);
        })
        .catch((error) => {
          if (!alive) return;
          // No silent downgrade. The page shows that governed quality profiling
          // failed rather than presenting preview statistics as registered-
          // population findings.
          setQuality(null);
          setMessage(
            error instanceof Error
              ? `Full-population data quality profiling failed: ${error.message}`
              : "Full-population data quality profiling failed."
          );
        })
        .finally(() => alive && setQualityLoading(false));
    } else {
      setQualityLoading(false);
      setQuality(browserQuality());
    }
    return () => {
      alive = false;
    };
  }, [headers, target, profilingRows, fullSourceRows, completeBrowserDataset, registeredRowCount, backendImportSynced, eventValue, nonEventValue, selected.join("|"), projectId, loadedLibraryIdentity, activeDatasetIdentity]);

  function saveKeptSelection(nextKept: Record<string, boolean>) {
    predictorSelectionTouched.current = true;
    if (predictorAuthorizationSaving) {
      predictorAuthorizationOperationRevision.current += 1;
      setPredictorAuthorizationSaving(false);
      setPredictorAuthorizationVerificationError(
        "The predictor selection changed before the prior authorization update completed. Retry with the current selection.",
      );
    }
    const currentDataset = loadLocalDataset();
    const localView = buildSelectedDatasetView({
      headers,
      rows: profilingRows,
      selectedColumns: headers.filter(
        (header) =>
          predictorIsEligible(header, { headers, rows: profilingRows, target }) &&
          nextKept[header] !== false,
      ),
      target: target || null,
    });
    const nextSelectionKey = canonicalPredictorSelectionKey(
      localView.selectedColumns,
    );
    if (
      analysisPartition.phase === "current" &&
      confirmedPartitionPredictorKey &&
      nextSelectionKey === confirmedPartitionPredictorKey
    ) {
      markReproducibilityContextPending();
    } else {
      markReproducibilityContextPending();
    }
    setPredictorAuthorizationFeedback("");
    setKept(nextKept);
    saveLocalDataset({
      ...(currentDataset ?? {}),
      headers: localView.headers,
      rows: localView.rows,
      target: target || null,
      selected_columns: localView.selectedColumns,
      problem_type: target ? inferProblemType(localView.rows, target) : undefined,
      registered_row_count: registeredRowCount,
      browser_data_complete: completeBrowserDataset,
      event_value: eventValue,
      non_event_value: nonEventValue,
      dataset_library: currentDataset?.dataset_library,
    });
    window.dispatchEvent(new CustomEvent("atlas-dataset-updated"));
  }

  // Part H: automatic weak-signal exclusion, hardened.
  //
  // The previous implementation did `Number(row.iv) < threshold`. With
  // `row.iv === null` that is `0 < 0.01`, so every predictor whose IV was merely
  // UNAVAILABLE was silently deselected. The plan below never treats null,
  // pending, preview-only, or failed as zero, and it is computed before the user
  // confirms so the affected count can be shown up front.
  const weakSignalPlan = useMemo(
    () =>
      planWeakSignalExclusion({
        profile: governedProfile.profile,
        loading: governedProfile.phase === "quality" || governedProfile.phase === "iv",
        error: governedProfile.phase === "failed" || governedProfile.phase === "artifact_missing" ? governedProfile.error : null,
        problemType: targetInfo.kind === "continuous" ? "regression" : "classification",
        selected,
      }),
    [governedProfile.profile, governedProfile.phase, governedProfile.error, targetInfo.kind, headers, kept, target]
  );

  function applyWeakSignalFilter() {
    if (!weakSignalPlan.eligible) {
      setWeakSignalNotice(weakSignalPlan.blockedReason ?? "Automatic weak-signal exclusion is unavailable.");
      return;
    }
    const previous = { ...kept };
    const nextKept = { ...kept };
    // Only predictors with a genuinely computed, genuinely weak IV are removed.
    weakSignalPlan.affected.forEach((column) => {
      nextKept[column] = false;
    });
    saveKeptSelection(nextKept);
    setWeakSignalUndo(previous);
    setWeakSignalNotice(
      `${weakSignalPlan.affected.length} predictor(s) deselected. ${weakSignalPlan.protectedFromRemoval.length} predictor(s) with unavailable Information Value were kept.`
    );
    logDecision({
      workflowStep: "Data Acquisition",
      actionType: "feature_inclusion_changed",
      subject: "Automatic weak-signal exclusion",
      previousValue: Object.keys(previous).filter((key) => previous[key] !== false),
      newValue: Object.keys(nextKept).filter((key) => nextKept[key] !== false),
      systemRecommendation: `Configured ATLAS weak-signal threshold ${weakSignalPlan.threshold}`,
      userReason: JSON.stringify({
        scopeMode: governedProfile.profile?.analysisScope.mode,
        datasetId: governedProfile.profile?.datasetId,
        datasetVersionId: governedProfile.profile?.datasetVersionId,
        target,
        eventValue,
        nonEventValue,
        calculationVersion: governedProfile.profile?.calculationVersion,
        affected: weakSignalPlan.affected,
        keptBecauseUnavailable: weakSignalPlan.protectedFromRemoval,
      }),
    });
  }

  function undoWeakSignalFilter() {
    if (!weakSignalUndo) return;
    saveKeptSelection(weakSignalUndo);
    setWeakSignalUndo(null);
    setWeakSignalNotice("Automatic weak-signal exclusion was undone.");
    logDecision({
      workflowStep: "Data Acquisition",
      actionType: "feature_inclusion_changed",
      subject: "Automatic weak-signal exclusion undone",
      previousValue: "applied",
      newValue: "reverted",
    });
  }

  function applyLoadedDataset(normalized: NormalizedBackendImport, options: {
    sourceLabel: string;
    backendSynced: boolean;
    browserComplete?: boolean;
    datasetLibrary?: LocalDataset["dataset_library"];
    canonicalIdentity?: CanonicalDatasetIdentity;
  }) {
    const guessedTarget = preferredTarget(normalized.headers, normalized.target);
    const keep: Record<string, boolean> = {};
    normalized.headers.forEach((header) => {
      keep[header] = predictorIsEligible(header, {
        headers: normalized.headers,
        rows: normalized.previewRows,
        target: guessedTarget,
      });
    });
    setHeaders(normalized.headers);
    setRows(normalized.previewRows);
    setKept(keep);
    setTarget(guessedTarget);
    setImportError(null);
    setBackendImportSynced(options.backendSynced);
    setBackendRowCount(options.backendSynced ? normalized.rowCount : null);
    setBrowserDataComplete(options.browserComplete ?? (!options.backendSynced && normalized.previewRows.length === normalized.rowCount));
    setPreviewSamplingMethod("top_n");
    const requestedSelectedColumns = normalized.selectedColumns.length
      ? normalized.selectedColumns
      : normalized.headers;
    const selectedColumns = requestedSelectedColumns.filter((header) =>
      predictorIsEligible(header, {
        headers: normalized.headers,
        rows: normalized.previewRows,
        target: guessedTarget,
      }),
    );
    const localView = buildSelectedDatasetView({
      headers: normalized.headers,
      rows: normalized.previewRows.slice(0, 5000),
      selectedColumns,
      target: guessedTarget || null,
    });
    saveLocalDataset({
      headers: localView.headers,
      rows: localView.rows,
      target: guessedTarget || null,
      selected_columns: localView.selectedColumns,
      problem_type: guessedTarget ? inferProblemType(localView.rows, guessedTarget) : undefined,
      registered_row_count: normalized.rowCount,
      browser_data_complete: options.browserComplete ?? (!options.backendSynced && normalized.previewRows.length === normalized.rowCount),
      event_value: eventValue,
      non_event_value: nonEventValue,
      dataset_id: options.canonicalIdentity?.dataset_id,
      dataset_version_id: options.canonicalIdentity?.dataset_version_id,
      dataset_version: options.canonicalIdentity?.dataset_version_id,
      dataset_library: options.datasetLibrary,
    });
    window.dispatchEvent(new CustomEvent("atlas-dataset-updated"));
    // The profiling effect recomputes quality (with correct scope and aggregates) as
    // soon as the new headers/rows land, so no interim profile is written here.
    logDecision({
      workflowStep: "Data Acquisition",
      actionType: "workflow_setting_changed",
      subject: "Data source",
      previousValue: metadata?.sourceLabel,
      newValue: options.sourceLabel,
      systemRecommendation: "Capture data source, version, sampling method, and data quality immediately after import.",
      followStatus: "followed",
    });
  }

  async function importCsvThroughBackend(file: File) {
    setIsImporting(true);
    setImportError(null);
    setMessage(`Importing ${file.name} through the ATLAS backend. The browser will show a governed preview sample when loading is complete.`);
    try {
      const formData = new FormData();
      formData.append("file", file);
      formData.append("project_id", projectId);
      const response = await fetch(`${BASE}/data/upload_csv`, {
        method: "POST",
        credentials: "include",
        body: formData,
      });
      const payload = await response.json().catch(() => null);
      if (!response.ok || !payload?.ok) {
        const errorMessage = payload?.detail ?? payload?.error ?? `HTTP ${response.status}`;
        throw new Error(backendImportFailureMessage(errorMessage, payload?.max_upload_mb));
      }
      const normalized = normalizeBackendImportResponse(payload);
      if (!normalized.headers.length || !normalized.previewRows.length || !normalized.rowCount) {
        throw new Error("Backend import completed but did not return usable columns and preview rows.");
      }
      const canonical = requireCanonicalDatasetIdentity(
        {
          project_id: normalized.projectId,
          dataset_id: normalized.datasetId,
          dataset_version_id: normalized.datasetVersionId,
        },
        "Registered upload response"
      );
      if (canonical.project_id !== projectId) {
        throw new Error("Backend upload returned a dataset identity for a different project.");
      }
      applyLoadedDataset(normalized, {
        sourceLabel: `Registered backend import: ${file.name}`,
        backendSynced: true,
        canonicalIdentity: canonical,
        datasetLibrary: {
          datasetId: canonical.dataset_id,
          versionId: canonical.dataset_version_id,
          datasetName: file.name,
          datasetRole: "development",
          sourceType: "dataset-library",
          rowCount: normalized.rowCount,
          columnCount: normalized.columnCount,
          linkedAt: new Date().toISOString(),
        },
      });
      setActiveDatasetIdentity(canonical);
      setLoadedLibraryIdentity({
        datasetId: canonical.dataset_id,
        versionId: canonical.dataset_version_id,
      });
      setSelectedLibraryDatasetId(canonical.dataset_id);
      setSelectedLibraryVersionId(canonical.dataset_version_id);
      setSelectedDatasetVersions([
        {
          versionId: canonical.dataset_version_id,
          createdAt: new Date().toISOString(),
          rowCount: normalized.rowCount,
          columnCount: normalized.columnCount,
        },
      ]);
      setDatasetIdentityError("");
      setMessage(`Loaded ${normalized.rowCount.toLocaleString()} rows and ${normalized.columnCount.toLocaleString()} columns through backend import. The browser preview shows ${normalized.previewRows.length.toLocaleString()} rows.`);
    } catch (err: any) {
      const errorText = err?.message ?? "ATLAS could not import this file through the backend.";
      setImportError(errorText);
      setBackendImportSynced(false);
      setBackendRowCount(null);
      setMessage(errorText);
    } finally {
      setIsImporting(false);
    }
  }

  async function onFile(file: File) {
    markReproducibilityContextPending();
    setMessage("");
    setImportError(null);
    setFileName(file.name);
    setBackendImportSynced(false);
    setBackendRowCount(null);
    setBrowserDataComplete(false);
    const decision = getUploadDecision({ fileName: file.name, fileSize: file.size });
    if (decision.mode === "invalid" || decision.mode === "recognized_unsupported") {
      setImportError(decision.message);
      setMessage(decision.message);
      return;
    }
    if (decision.mode === "backend") {
      await importCsvThroughBackend(file);
      return;
    }
    const extension = decision.extension;
    if (!BROWSER_PARSE_EXTENSIONS.has(extension)) {
      setMessage(`${extension.toUpperCase()} files are recognized but require backend parser support before they can be loaded into the browser preview.`);
      return;
    }
    try {
      const text = await file.text();
      const parsed = extension === "json" ? parseJSON(text) : parseCSV(text);
      if (parsed.headers.length > DEFAULT_BROWSER_MAX_COLUMNS) {
        setMessage(`This dataset has ${parsed.headers.length.toLocaleString()} columns. Browser preview is limited to ${DEFAULT_BROWSER_MAX_COLUMNS.toLocaleString()} columns.`);
        return;
      }
      if (parsed.rows.length > DEFAULT_BROWSER_MAX_ROWS) {
        setMessage(`This dataset has ${parsed.rows.length.toLocaleString()} rows. Browser preview is limited to ${DEFAULT_BROWSER_MAX_ROWS.toLocaleString()} rows; use sampling or backend import for larger files.`);
        return;
      }
      const normalized = {
        headers: parsed.headers,
        previewRows: parsed.rows,
        rowCount: parsed.rows.length,
        columnCount: parsed.headers.length,
        target: preferredTarget(parsed.headers),
        selectedColumns: parsed.headers.filter((header) => header !== preferredTarget(parsed.headers)),
        filename: file.name,
        projectId: "",
        datasetId: "",
        datasetVersionId: "",
      };
      applyLoadedDataset(normalized, { sourceLabel: `Uploaded ${file.name}`, backendSynced: false, browserComplete: true });
      setMessage(`Loaded the complete browser dataset with ${parsed.rows.length.toLocaleString()} rows and ${parsed.headers.length.toLocaleString()} columns.`);
    } catch (err: any) {
      const errorText = err?.message ?? "Unable to parse file.";
      setImportError(errorText);
      setMessage(errorText);
    }
  }

  function saveQueryMetadata() {
    const stubHeaders = ["customer_id", "observation_date", "target", "feature_1", "feature_2"];
    const stubRows: Record<string, unknown>[] = [];
    setHeaders(stubHeaders);
    setRows(stubRows);
    const keep: Record<string, boolean> = {};
    stubHeaders.forEach((header) => {
      keep[header] = header !== "target";
    });
    setKept(keep);
    setTarget("target");
    setImportError(null);
    setBackendImportSynced(false);
    setBackendRowCount(null);
    setBrowserDataComplete(false);
    setMessage("SQL metadata saved. Real query execution requires a backend connector; upload query output or connect the backend to populate rows.");
  }

  async function persistDataset(
    identityOverride?: CanonicalDatasetIdentity,
  ): Promise<TargetPersistenceContract> {
    if (!headers.length) throw new Error("No dataset or query metadata is available.");
    const canonical = requireCanonicalDatasetIdentity(
      identityOverride ?? activeDatasetIdentity,
      "Active Data Acquisition dataset identity"
    );
    if (canonical.project_id !== projectId) {
      throw new Error("The active registered dataset belongs to a different project.");
    }
    const selectedColumns = selected;
    const localView = buildSelectedDatasetView({
      headers,
      rows: profilingRows,
      selectedColumns,
      target: target || null,
    });
    const meta = generatedMetadata;
    const dq = quality ?? inferDataQuality({ headers, rows: completeBrowserDataset ? fullSourceRows : profilingRows, target: target || null });
    const problemType = targetInfo.kind === "continuous" ? "regression" : "classification";
    const localPayload: LocalDataset = {
      headers: localView.headers,
      rows: localView.rows,
      target: target || null,
      selected_columns: localView.selectedColumns,
      problem_type: problemType,
      registered_row_count: registeredRowCount,
      browser_data_complete: completeBrowserDataset,
      dataset_id: canonical.dataset_id,
      dataset_version_id: canonical.dataset_version_id,
      dataset_version: canonical.dataset_version_id,
      event_value: eventValue,
      non_event_value: nonEventValue,
      dataset_library: {
        datasetId: canonical.dataset_id,
        versionId: canonical.dataset_version_id,
        datasetName:
          libraryDatasets.find((dataset) => dataset.datasetId === canonical.dataset_id)?.name ??
          datasetLibraryLink?.datasetName ??
          fileName ??
          "Dataset Library asset",
        datasetRole: datasetLibraryLink?.datasetRole ?? "modeling",
        sourceType: "dataset-library",
        rowCount: registeredRowCount,
        columnCount: headers.length,
        linkedAt: datasetLibraryLink?.linkedAt ?? new Date().toISOString(),
      },
      data_access: meta ?? undefined,
      data_quality: dq,
    };
    const localSaveStatus = saveLocalDataset(localPayload);
    setWorkflowDatasetIdentity(canonical);
    if (localSaveStatus === "failed") {
      setMessage("Dataset preview loaded, but browser session storage could not cache the sample. Continue is allowed; reload the source file if the browser session is refreshed.");
    }
    if (meta) {
      try {
        saveDataAccessMetadata(meta);
        recordDatasetVersion(localPayload, meta);
      } catch (error) {
        console.warn("ATLAS could not update data access metadata history", error);
        setMessage("Dataset is loaded and usable, but ATLAS could not update browser metadata history because local storage is full. Navigation is still allowed.");
      }
      setMetadata(meta);
    }
    setQuality(dq);
    useWorkflowStore.setState((state: any) => ({
      ...state,
      hasDataset: rows.length > 0 || headers.length > 0,
      trainSpec: {
        ...(state?.trainSpec ?? {}),
        data: {
          ...(state?.trainSpec?.data ?? {}),
          source: sourceType,
          n_samples: registeredRowCount,
          task: problemType === "regression" ? "regression" : "binary",
          target,
          selected_columns: localView.selectedColumns,
          dataset_id: canonical.dataset_id,
          dataset_version_id: canonical.dataset_version_id,
          dataset_version: canonical.dataset_version_id,
        },
      },
    }));

    let backendSynced = false;
    let targetContractId = "";
    let predictorAuthorizationId = "";
    try {
      const targetPayload = buildTargetPersistencePayload(canonical, {
        target: target || null,
        selected_columns: localView.selectedColumns,
        event_value: eventValue,
        non_event_value: nonEventValue,
      });
      const backendRes = await fetch(`${BASE}/data/set_target`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({
          ...targetPayload,
          access_metadata_id: meta?.accessMetadataId,
        }),
      });
      const backendJson = await backendRes.json().catch(() => null);
      if (!backendRes.ok || !backendJson?.ok) {
        throw new Error(backendJson?.detail ?? backendJson?.error ?? "Backend did not accept the modeling dataset.");
      }
      assertExactDatasetActivation(canonical, backendJson);
      targetContractId = String(backendJson.target_contract_id ?? "").trim();
      predictorAuthorizationId = String(
        backendJson.predictor_authorization_id ??
          backendJson.eda_readiness?.predictor_authorization_id ??
          "",
      ).trim();
      if (!targetContractId || !predictorAuthorizationId) {
        throw new Error(
          "Backend target persistence did not return the governed target and predictor-authorization contract IDs.",
        );
      }
      backendSynced = true;
      notifyReproducibilityContextConfirmed();
    } catch (err: any) {
      const detail = err?.message ?? "Unable to send target configuration to the backend.";
      setMessage(`Dataset preview is saved locally. Backend sync did not complete: ${detail}`);
      throw new Error(detail);
    }

    if (backendSynced && localSaveStatus === "sample") {
      setMessage(`Cached ${profilingRows.length.toLocaleString()} profiling rows in the browser and sent ${registeredRowCount.toLocaleString()} rows to the backend for modeling.`);
    } else if (backendSynced && localSaveStatus !== "failed") {
      setMessage(`Cached ${profilingRows.length.toLocaleString()} profiling rows in the browser and preserved ${registeredRowCount.toLocaleString()} registered modeling rows.`);
    }
    logDecision({
      workflowStep: "Data Acquisition",
      actionType: "workflow_setting_changed",
      subject: "Dataset version",
      previousValue: loadLocalDataset()?.dataset_version_id,
      newValue: canonical.dataset_version_id,
      systemRecommendation: "Use dataset version, hash, source, query, and sampling metadata in model governance documentation.",
      followStatus: "followed",
    });
    return { targetContractId, predictorAuthorizationId };
  }

  async function updatePredictorAuthorization() {
    const baseline = analysisPartition.partition;
    const retryingVerification = Boolean(predictorAuthorizationVerificationError);
    if (
      analysisPartition.phase !== "current" ||
      !baseline ||
      (!predictorAuthorizationDraft.dirty && !retryingVerification) ||
      !selected.length
    ) {
      setPredictorAuthorizationFeedback(
        selected.length
          ? "A current sealed Analysis Partition and a changed predictor selection are required."
          : "Approve at least one eligible predictor before updating the governed authorization.",
      );
      return;
    }
    const operationRevision =
      predictorAuthorizationOperationRevision.current + 1;
    predictorAuthorizationOperationRevision.current = operationRevision;
    const submittedPredictorKey = selectedPredictorKey;
    setPredictorAuthorizationSaving(true);
    setPredictorAuthorizationVerificationError("");
    setPredictorAuthorizationFeedback(
      "Saving the predictor selection and verifying preserved partition membership...",
    );
    try {
      const canonical = requireCanonicalDatasetIdentity(
        activeDatasetIdentity,
        "Predictor Authorization dataset identity",
      );
      const contract = await persistDataset(canonical);
      if (operationRevision !== predictorAuthorizationOperationRevision.current) {
        return;
      }
      const refreshed = await readAnalysisPartitionReadiness(
        canonical,
        target,
        eventValue,
        nonEventValue,
      );
      if (operationRevision !== predictorAuthorizationOperationRevision.current) {
        return;
      }
      const current = refreshed.partition;
      if (
        refreshed.phase !== "current" ||
        !current ||
        !analysisPartitionMembershipPreserved(baseline, current) ||
        !predictorAuthorizationLineageMatches(
          current,
          contract.predictorAuthorizationId,
        )
      ) {
        throw new Error(
          "The backend did not prove that the exact sealed Analysis Partition membership was preserved with the updated predictor authorization.",
        );
      }
      setAnalysisPartition(refreshed);
      setConfirmedPartitionPredictorKey(submittedPredictorKey);
      setPredictorAuthorizationFeedback(
        "Predictor authorization updated. The existing Analysis Partition ID, revision, assignment, artifact, and sealed holdout membership were preserved.",
      );
      notifyReproducibilityContextConfirmed();
      logDecision({
        workflowStep: "Data Acquisition",
        actionType: "feature_inclusion_changed",
        subject: "Predictor Authorization",
        previousValue: String(
          baseline.current_predictor_authorization_id ??
            baseline.predictor_authorization_id ??
            "",
        ),
        newValue: contract.predictorAuthorizationId,
        systemRecommendation:
          "Publish the changed predictor authorization without redrawing sealed Analysis Partition membership.",
        followStatus: "followed",
      });
    } catch (cause) {
      if (operationRevision !== predictorAuthorizationOperationRevision.current) {
        return;
      }
      const detail =
        cause instanceof Error
          ? cause.message
          : "ATLAS could not update the predictor authorization.";
      setPredictorAuthorizationVerificationError(detail);
      setPredictorAuthorizationFeedback(detail);
      setMessage(detail);
    } finally {
      if (operationRevision === predictorAuthorizationOperationRevision.current) {
        setPredictorAuthorizationSaving(false);
      }
    }
  }

  function retryPredictorAuthorizationContext() {
    setPredictorAuthorizationFeedback(
      "Retrying the exact governed predictor-authorization context check...",
    );
    notifyReproducibilityContextConfirmed();
  }

  function focusDataAcquisitionBlocker() {
    const predictorBlocker = Boolean(
      predictorAuthorizationVerificationError ||
      predictorAuthorizationDraft.dirty ||
      !reproducibilityContext?.predictor_authorization?.funnel
        .authorized_predictor_count,
    );
    const specialValueBlocker = Boolean(
      bureauReviewStatus &&
        (bureauReviewStatus.loading || bureauReviewStatus.blocking),
    );
    if (specialValueBlocker) {
      window.dispatchEvent(
        new Event(FOCUS_FIRST_SPECIAL_VALUE_REVIEW_EVENT),
      );
      return;
    }
    const sectionId = predictorBlocker
      ? "predictor-authorization"
      : analysisPartition.phase !== "current"
          ? "analysis-partition-readiness"
          : "source-target";
    const section = document.getElementById(sectionId);
    const firstUnresolvedVariable = String(
      (
        bureauReviewStatus as
          | (BureauReviewPanelStatus & { firstUnresolvedVariable?: string })
          | null
      )?.firstUnresolvedVariable ?? "",
    ).trim();
    const firstUnresolvedRow =
      firstUnresolvedVariable && section
        ? Array.from(
            section.querySelectorAll<HTMLElement>(
              "[data-special-value-variable]",
            ),
          ).find(
            (candidate) =>
              candidate.dataset.specialValueVariable === firstUnresolvedVariable,
          ) ?? null
        : null;
    const blockerTarget = firstUnresolvedRow ?? section;
    blockerTarget?.scrollIntoView({ behavior: "smooth", block: "center" });
    window.setTimeout(() => {
      const preferredSelector = predictorBlocker
        ? predictorAuthorizationDraft.canUpdate ||
          predictorAuthorizationDraft.canRetryBaseline ||
          Boolean(predictorAuthorizationVerificationError)
          ? '[data-testid="update-predictor-authorization"]:not([disabled])'
          : '[data-testid="predictor-select-all"]:not([disabled])'
        : specialValueBlocker
          ? "summary, button:not([disabled]), input:not([disabled]), select:not([disabled])"
          : analysisPartition.phase !== "current"
            ? '[data-testid="create-analysis-partition"]:not([disabled]), [data-testid="analysis-partition-holdout-ratio"]:not([disabled])'
            : 'button:not([disabled]), input:not([disabled]), select:not([disabled])';
      const focusTarget =
        blockerTarget?.querySelector<HTMLElement>(preferredSelector) ??
        (blockerTarget?.matches(
          "button:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex='-1'])",
        )
          ? blockerTarget
          : null);
      focusTarget?.focus();
    }, 0);
  }

  function resolveDataAcquisitionBlocker() {
    if (predictorAuthorizationDraft.canRetryBaseline) {
      retryPredictorAuthorizationContext();
      return;
    }
    if (
      predictorAuthorizationVerificationError ||
      predictorAuthorizationDraft.canUpdate
    ) {
      void updatePredictorAuthorization();
      return;
    }
    focusDataAcquisitionBlocker();
  }

  async function confirmRecommendedAnalysisPartition() {
    const previewFingerprint = analysisPartitionPreview.previewFingerprint;
    if (
      !previewFingerprint ||
      !analysisPartitionPreviewHasRequiredEvidence(
        analysisPartitionPreview,
        targetInfo.kind === "continuous" ? "regression" : "classification",
      )
    ) {
      setAnalysisPartition((current) => ({
        ...current,
        phase: "required",
        code: "analysis_partition_preview_required",
        message: "Wait for the complete exact backend preview, including its fingerprint, population evidence, and sufficiency result, before creating the Analysis Partition.",
      }));
      return;
    }
    if (
      analysisPartitionPreview.recommendationStatus === "blocked" ||
      analysisPartitionPreview.blockers.length
    ) {
      setAnalysisPartition((current) => ({
        ...current,
        phase: "required",
        code: "analysis_partition_preview_blocked",
        message: analysisPartitionPreview.blockers[0] ?? "The selected split is blocked by the governed sufficiency policy.",
      }));
      return;
    }
    if (
      analysisPartitionPreview.rationaleRequired &&
      analysisPartitionRationale.trim().length <
        MIN_ANALYSIS_PARTITION_RATIONALE_LENGTH
    ) {
      setAnalysisPartition((current) => ({
        ...current,
        phase: "required",
        code: "analysis_partition_rationale_required",
        message: `Add an analyst rationale of at least ${MIN_ANALYSIS_PARTITION_RATIONALE_LENGTH} characters for this acceptable nonrecommended split.`,
      }));
      return;
    }
    const canonical = requireCanonicalDatasetIdentity(
      activeDatasetIdentity,
      "Analysis Partition dataset identity",
    );
    if (!target) {
      setAnalysisPartition({
        phase: "required",
        code: "target_contract_stale",
        message: "Confirm the target before creating the Analysis Partition.",
        recovery: "Select the target and class mapping in Target Setup.",
        partition: null,
      });
      return;
    }

    setAnalysisPartition((current) => ({
      ...current,
      phase: "confirming",
      code: "analysis_partition_confirming",
      message: "Persisting the target contract and sealing the final holdout...",
    }));
    try {
      const policy = initialAnalysisPartitionPolicy(
        analysisPartitionHoldoutShare,
        targetInfo.kind === "continuous" ? "regression" : "classification",
      );
      const contract = await persistDataset(canonical);
      const confirmed = await createOrReuseAnalysisPartition(
        canonical,
        target,
        eventValue,
        nonEventValue,
        contract,
        policy,
        targetInfo.kind === "continuous" ? "regression" : "classification",
        previewFingerprint,
        analysisPartitionRationale,
      );
      setAnalysisPartition(confirmed);
      if (confirmed.phase === "current") {
        setConfirmedPartitionPredictorKey(selectedPredictorKey);
        notifyReproducibilityContextConfirmed();
        setMessage(confirmed.message);
        logDecision({
          workflowStep: "Data Acquisition",
          actionType: "workflow_setting_changed",
          subject: "Analysis Partition",
          previousValue: "required",
          newValue: confirmed.partition?.analysis_partition_id ?? "current",
          systemRecommendation:
            `Use a ${Math.round(policy.developmentShare * 100)}% development population and a sealed ${Math.round(policy.holdoutShare * 100)}% final holdout with random seed ${policy.randomSeed} and target stratification.`,
          followStatus: "followed",
        });
      } else {
        setMessage(`${confirmed.message} ${confirmed.recovery}`.trim());
      }
    } catch (cause) {
      const detail =
        cause instanceof Error
          ? cause.message
          : "ATLAS could not confirm the Analysis Partition.";
      setAnalysisPartition({
        phase: "error",
        code: "analysis_partition_confirmation_failed",
        message: detail,
        recovery: "Retry after confirming the exact dataset and target are still active.",
        partition: null,
      });
      setMessage(detail);
    }
  }

  async function retryAnalysisPartitionDocumentation() {
    const partition = analysisPartition.partition;
    if (
      analysisPartition.phase !== "documentation_pending" ||
      !partition?.analysis_partition_id ||
      !activeDatasetIdentity
    ) {
      return;
    }
    const canonical = requireCanonicalDatasetIdentity(
      activeDatasetIdentity,
      "Analysis Partition documentation identity",
    );
    setAnalysisPartition((current) => ({
      ...current,
      phase: "documenting",
      code: "analysis_partition_documentation_retrying",
      message: "Completing exact partition evidence and MDD documentation...",
      recovery: "Membership remains sealed and unchanged during this retry.",
    }));
    try {
      const completed = await completeAnalysisPartitionDocumentation(
        canonical,
        target,
        eventValue,
        nonEventValue,
        partition,
      );
      setAnalysisPartition(completed);
      setMessage(`${completed.message} ${completed.recovery}`.trim());
      if (completed.phase === "current") {
        setConfirmedPartitionPredictorKey(selectedPredictorKey);
        notifyReproducibilityContextConfirmed();
      }
    } catch (cause) {
      const detail =
        cause instanceof Error
          ? cause.message
          : "ATLAS could not complete partition documentation.";
      setAnalysisPartition({
        phase: "documentation_pending",
        code: "analysis_partition_documentation_pending",
        message: detail,
        recovery: "Retry Complete Partition Documentation. The sealed membership remains unchanged.",
        partition,
        reused: true,
      });
      setMessage(detail);
    }
  }

  function leaveAnalysisPartitionResetMode() {
    const next = new URLSearchParams(searchParams);
    next.delete("analysisPartition");
    setSearchParams(next, { replace: true });
    setMessage(
      analysisPartitionResetCompleted
        ? "Split-ratio change review closed. Downstream artifacts remain stale and must be recomputed explicitly."
        : "Split-ratio change canceled. The current Analysis Partition was not changed.",
    );
    if (!analysisPartitionResetCompleted) {
      notifyReproducibilityContextConfirmed();
    }
  }

  async function confirmGovernedAnalysisPartitionReset() {
    const baseline = analysisPartitionResetImpact.partition;
    if (analysisPartitionResetImpact.phase !== "ready" || !baseline) {
      setAnalysisPartitionResetFeedback(
        "Load and review the exact current partition impact before changing the split ratio.",
      );
      return;
    }
    const resetReason = analysisPartitionResetReason.trim();
    if (!resetReason) {
      setAnalysisPartitionResetFeedback(
        "Enter a governed reason for replacing the current partition membership.",
      );
      return;
    }
    if (
      analysisPartitionPreview.rationaleRequired &&
      resetReason.length < MIN_ANALYSIS_PARTITION_RATIONALE_LENGTH
    ) {
      setAnalysisPartitionResetFeedback(
        `Enter at least ${MIN_ANALYSIS_PARTITION_RATIONALE_LENGTH} characters because the proposed split requires a policy rationale.`,
      );
      return;
    }
    if (!analysisPartitionResetInvalidationAcknowledged) {
      setAnalysisPartitionResetFeedback(
        "Acknowledge that every listed downstream artifact becomes stale before changing membership.",
      );
      return;
    }
    const resetPreviewFingerprint =
      analysisPartitionPreview.phase === "ready"
        ? String(analysisPartitionPreview.previewFingerprint ?? "").trim()
        : "";
    if (!resetPreviewFingerprint || analysisPartitionPreview.blockers.length > 0) {
      setAnalysisPartitionResetFeedback(
        "Wait for the backend split preview to finish without blockers before creating a new revision.",
      );
      return;
    }
    const holdoutShare = Number(analysisPartitionResetHoldoutShare);
    if (
      !Number.isFinite(holdoutShare) ||
      !INITIAL_HOLDOUT_OPTIONS.some(
        (supportedShare) => Math.abs(supportedShare - holdoutShare) < 1e-9,
      )
    ) {
      setAnalysisPartitionResetFeedback(
        "Select exactly 70/30, 80/20, or 90/10 for the replacement partition.",
      );
      return;
    }
    const randomSeed = Number(analysisPartitionResetRandomSeed);
    if (
      !Number.isInteger(randomSeed) ||
      randomSeed < 0 ||
      randomSeed > 2_147_483_647
    ) {
      setAnalysisPartitionResetFeedback(
        "Random seed must be a whole number from 0 through 2,147,483,647.",
      );
      return;
    }
    const canonical = requireCanonicalDatasetIdentity(
      activeDatasetIdentity,
      "Analysis Partition split-change dataset identity",
    );
    if (!target) {
      setAnalysisPartitionResetFeedback(
        "The exact governed target must be current before changing the Analysis Partition.",
      );
      return;
    }

    setAnalysisPartitionResetFeedback(
      "Rechecking the exact split-change impact before replacing membership...",
    );
    try {
      const latestImpact = await readAnalysisPartitionResetImpact(canonical);
      const latest = latestImpact.partition;
      if (latestImpact.phase !== "ready" || !latest) {
        setAnalysisPartitionResetImpact(latestImpact);
        setAnalysisPartitionResetFeedback(latestImpact.message);
        return;
      }
      const baselinePredictorAuthorizationId =
        currentDurablePredictorAuthorizationId(baseline);
      const latestPredictorAuthorizationId =
        currentDurablePredictorAuthorizationId(latest);
      const baselineTargetContractId = String(
        baseline.target_contract_id ?? "",
      ).trim();
      const latestTargetContractId = String(
        latest.target_contract_id ?? "",
      ).trim();
      if (
        latest.analysis_partition_id !== baseline.analysis_partition_id ||
        Number(latest.revision) !== Number(baseline.revision) ||
        latestPredictorAuthorizationId !== baselinePredictorAuthorizationId ||
        latestTargetContractId !== baselineTargetContractId
      ) {
        setAnalysisPartitionResetImpact(latestImpact);
        setAnalysisPartitionResetHoldoutShare(
          String(latest.holdout_share ?? PARTITION_DEFAULTS.holdoutShare),
        );
        setAnalysisPartitionResetRandomSeed(
          String(latest.random_seed ?? PARTITION_DEFAULTS.randomSeed),
        );
        setAnalysisPartitionResetStratification(
          latest.stratification_policy === "none" ? "none" : "target",
        );
        setAnalysisPartitionResetInvalidationAcknowledged(false);
        setAnalysisPartitionResetFeedback(
          "The current partition or its durable authority changed while this review was open. ATLAS refreshed the baseline; review the impacts and acknowledge them again.",
        );
        return;
      }

      const policy: AnalysisPartitionPolicy = {
        developmentShare: Number((1 - holdoutShare).toFixed(10)),
        holdoutShare,
        randomSeed,
        stratificationPolicy:
          targetInfo.kind === "continuous"
            ? "none"
            : analysisPartitionResetStratification,
      };
      if (!latestTargetContractId || !latestPredictorAuthorizationId) {
        setAnalysisPartitionResetFeedback(
          "The current durable target and predictor authorization could not be verified. No split revision was created.",
        );
        return;
      }
      setAnalysisPartition((current) => ({
        ...current,
        phase: "confirming",
        code: "analysis_partition_reset_confirming",
        message:
          "Replacing partition membership and invalidating downstream evidence...",
      }));
      const contract: TargetPersistenceContract = {
        targetContractId: latestTargetContractId,
        predictorAuthorizationId: latestPredictorAuthorizationId,
      };
      const result = await resetAnalysisPartition(
        canonical,
        target,
        eventValue,
        nonEventValue,
        contract,
        policy,
        targetInfo.kind === "continuous" ? "regression" : "classification",
        resetPreviewFingerprint,
        analysisPartitionResetReason,
        latest,
      );
      setAnalysisPartition(result.readiness);
      if (result.readiness.phase !== "current" || !result.readiness.partition) {
        setAnalysisPartitionResetFeedback(
          `${result.readiness.message} ${result.readiness.recovery}`.trim(),
        );
        return;
      }

      const replacement = result.readiness.partition;
      const impacts = result.impacts.length
        ? result.impacts
        : latestImpact.impacts;
      setConfirmedPartitionPredictorKey(
        reproducibilityContext?.predictor_authorization
          ?.predictor_authorization_id === latestPredictorAuthorizationId
          ? governedPredictorKey
          : "",
      );
      notifyReproducibilityContextConfirmed();
      setAnalysisPartitionResetCompleted({
        partitionId: String(replacement.analysis_partition_id),
        previousRevision: Number(latest.revision),
        revision: Number(replacement.revision),
        impacts,
      });
      setAnalysisPartitionResetInvalidationAcknowledged(false);
      setAnalysisPartitionResetFeedback(
        "Split-ratio change confirmed. The replacement partition is current and sealed; every listed downstream artifact remains stale. No predictor checkbox draft was submitted, and no navigation or recomputation occurred.",
      );
      setMessage(result.readiness.message);
      logDecision({
        workflowStep: "Data Acquisition",
        actionType: "workflow_setting_changed",
        subject: "Analysis Partition split-ratio change",
        previousValue: latest.analysis_partition_id,
        newValue: replacement.analysis_partition_id,
        systemRecommendation:
          "Change the split only after reviewing the complete invalidation impact; keep the replacement final holdout sealed and recompute downstream evidence explicitly.",
        followStatus: "followed",
        userReason: analysisPartitionResetReason.trim(),
      });
    } catch (cause) {
      const detail =
        cause instanceof Error
          ? cause.message
          : "ATLAS could not complete the governed Analysis Partition split change.";
      setAnalysisPartitionResetFeedback(detail);
      setAnalysisPartition((current) => ({
        ...current,
        phase: "error",
        code: "analysis_partition_reset_failed",
        message: detail,
        recovery:
          "No automatic continuation occurred. Reload the exact impact and verify the current durable partition before retrying.",
      }));
    }
  }

  // `dataAcquisitionDisabledReason` no longer gates this page: progression is
  // decided by `acquisitionStatus.canContinue`, which considers the governed
  // profile as well as the import state. The helper remains exported for other
  // callers and its own tests.
  // Part D: a successful load is GREEN. The previous default painted the
  // "Loaded CLASS_TRAIN..." confirmation amber, so success read as a warning.
  const messageClass =
    importError && !headers.length
      ? "border-red-200 bg-red-50 text-red-900"
      : isImporting
        ? "border-blue-200 bg-blue-50 text-blue-900"
        : /^(Loaded|Registered|Cached|Linked|Saved)/i.test(message)
          ? "border-emerald-200 bg-emerald-50 text-emerald-900"
          : "border-amber-200 bg-amber-50 text-amber-900";
  const updateTarget = (next: string) => {
    markReproducibilityContextPending();
    logDecision({
      workflowStep: "Data Acquisition",
      actionType: "target_variable_selected",
      subject: "Target variable",
      previousValue: target,
      newValue: next,
    });
    setTarget(next);
    const currentDataset = loadLocalDataset();
    if (headers.length) setImportError(null);
    const localView = buildSelectedDatasetView({
      headers,
      rows: profilingRows,
      selectedColumns: headers.filter(
        (header) =>
          predictorIsEligible(header, { headers, rows: profilingRows, target: next }) &&
          kept[header] !== false,
      ),
      target: next || null,
    });
    saveLocalDataset({
      ...(currentDataset ?? {}),
      headers: localView.headers,
      rows: localView.rows,
      target: next || null,
      selected_columns: localView.selectedColumns,
      problem_type: next ? inferProblemType(localView.rows, next) : undefined,
      registered_row_count: registeredRowCount,
      browser_data_complete: completeBrowserDataset,
      event_value: eventValue,
      non_event_value: nonEventValue,
      dataset_library: currentDataset?.dataset_library,
    });
    window.dispatchEvent(new CustomEvent("atlas-dataset-updated"));
    // Quality is recomputed by the profiling effect, which is the single source of
    // truth for profile scope, registered row counts, and class aggregates. Writing a
    // bare inferDataQuality() result here raced that effect and could leave a preview
    // profile mislabelled as a complete-dataset profile with no class distribution.
  };

  // Debounced on registerName changes (NOT on the name field's onBlur): blurring that
  // field is also the first event a click on "Register Development Dataset" fires, so
  // triggering an async state update from onBlur raced the click itself -- the
  // duplicate-check's re-render could land between the button's mousedown and mouseup
  // and silently swallow the click. Typing-driven debounce has no such coupling.
  useEffect(() => {
    if (persistenceChoice !== "register" || !registerName.trim()) {
      setDuplicateCandidates([]);
      return;
    }
    const timer = setTimeout(() => void checkForSimilarDatasets(registerName), 500);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [registerName, persistenceChoice]);

  async function checkForSimilarDatasets(name: string) {
    if (!name.trim()) {
      setDuplicateCandidates([]);
      return;
    }
    setCheckingDuplicates(true);
    try {
      const candidates = await findSimilarDatasets({
        name,
        target: target || undefined,
        rowCount: registeredRowCount || undefined,
        columnCount: headers.length || undefined,
      });
      setDuplicateCandidates(candidates);
    } catch {
      setDuplicateCandidates([]);
    } finally {
      setCheckingDuplicates(false);
    }
  }

  async function handleRegisterDevelopmentDataset() {
    if (!registerName.trim()) {
      setRegistrationError("Enter a Dataset Library name before registering.");
      return;
    }
    setRegistering(true);
    setRegistrationError("");
    try {
      if (activeDatasetIdentity) {
        setMessage(
          `This workflow already uses registered version ${activeDatasetIdentity.dataset_version_id}.`
        );
        return;
      }
      if (!completeBrowserDataset || !fullSourceRows.length) {
        throw new Error(
          "Load the complete dataset through backend registration before creating a governed Dataset Library version."
        );
      }
      const draftView = buildSelectedDatasetView({
        headers,
        rows: fullSourceRows,
        selectedColumns: selected,
        target: target || null,
      });
      const draftResponse = await fetch(`${BASE}/data/set_sample`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({
          project_id: projectId,
          headers: draftView.headers,
          rows: draftView.rows,
          target,
          selected_columns: draftView.selectedColumns,
          access_metadata_id: generatedMetadata?.accessMetadataId,
        }),
      });
      const draftPayload = await draftResponse.json().catch(() => null);
      if (!draftResponse.ok || !draftPayload?.ok) {
        throw new Error(
          draftPayload?.detail ?? draftPayload?.error ?? "ATLAS could not stage the workspace dataset for registration."
        );
      }
      const registration = await registerWorkspaceDataset({
        projectId,
        name: registerName.trim(),
        description: registerDescription.trim(),
        tags: registerTags.split(",").map((tag) => tag.trim()).filter(Boolean),
      });
      const dataset = registration.dataset;
      setRegistrationResult(dataset);
      const createdVersionId = registration.created_dataset_version_id;
      const registeredVersion = registration.created_version;
      if (
        !dataset.datasetId ||
        !createdVersionId ||
        !registeredVersion ||
        registeredVersion.versionId !== createdVersionId
      ) {
        throw new Error("Dataset registration did not return an exact immutable version.");
      }
      const canonical = assertExactDatasetActivation(
        {
          project_id: projectId,
          dataset_id: dataset.datasetId,
          dataset_version_id: createdVersionId,
        },
        registration
      );
      setActiveDatasetIdentity(canonical);
      setLoadedLibraryIdentity({
        datasetId: canonical.dataset_id,
        versionId: canonical.dataset_version_id,
      });
      setSelectedLibraryDatasetId(canonical.dataset_id);
      setSelectedLibraryVersionId(canonical.dataset_version_id);
      setSelectedDatasetVersions([registeredVersion]);
      setBackendImportSynced(true);
      setDatasetIdentityError("");
      await persistDataset(canonical);
      const existing = loadLocalDataset();
      if (existing) {
        saveLocalDataset({
          ...existing,
          dataset_id: canonical.dataset_id,
          dataset_version_id: canonical.dataset_version_id,
          dataset_version: canonical.dataset_version_id,
          dataset_library: {
            datasetId: canonical.dataset_id,
            versionId: canonical.dataset_version_id,
            datasetName: dataset.name ?? registerName.trim(),
            datasetRole: "modeling",
            sourceType: "dataset-library",
            rowCount: registeredVersion.rowCount ?? existing.registered_row_count,
            columnCount: registeredVersion.columnCount ?? existing.headers.length,
            linkedAt: new Date().toISOString(),
          },
        });
        window.dispatchEvent(new CustomEvent("atlas-dataset-updated"));
      }
      logDecision({
        workflowStep: "Data Acquisition",
        actionType: "workflow_setting_changed",
        subject: "Dataset Library registration",
        newValue: dataset.datasetId,
        systemRecommendation: "Registered datasets are governed, versioned, and reusable across authorized projects.",
        followStatus: "followed",
      });
    } catch (error) {
      setRegistrationError(error instanceof Error ? error.message : "ATLAS could not register this dataset to the Dataset Library.");
    } finally {
      setRegistering(false);
    }
  }

  const existingDatasetPicker = (
    <ExistingDatasetPanel
      versions={datasetVersions}
      libraryDatasets={libraryDatasets}
      libraryVersions={selectedDatasetVersions}
      selectedDatasetId={selectedLibraryDatasetId}
      selectedVersionId={selectedLibraryVersionId}
      loading={libraryLoading}
      loadProgress={loadProgress}
      isLoaded={isAlreadyLinked(loadedLibraryIdentity, { datasetId: selectedLibraryDatasetId, versionId: selectedLibraryVersionId })}
      onDatasetChange={async (datasetId) => {
        markReproducibilityContextPending();
        setSelectedLibraryDatasetId(datasetId);
        setSelectedLibraryVersionId("");
        setSelectedDatasetVersions([]);
        setActiveDatasetIdentity(null);
        setDatasetIdentityError("");
        if (datasetId) {
          try {
            const dataset = await getDataset(datasetId);
            setSelectedDatasetVersions(dataset.versions);
          } catch (error) {
            setDatasetIdentityError(
              error instanceof Error
                ? error.message
                : "ATLAS could not resolve the selected dataset's exact versions."
            );
          }
        }
        // Part A/5 + H1/8: a different selection is not the loaded version.
        setLoadProgress(IDLE_LOAD_PROGRESS);
      }}
      onVersionChange={(versionId) => {
        markReproducibilityContextPending();
        setSelectedLibraryVersionId(versionId);
        setLoadProgress(IDLE_LOAD_PROGRESS);
      }}
      onRefresh={async () => {
        setLibraryLoading(true);
        try {
          const payload = await listDatasets();
          setLibraryDatasets(payload.datasets);
        } finally {
          setLibraryLoading(false);
        }
      }}
      onLoad={async () => {
        if (!selectedLibraryDatasetId || !selectedLibraryVersionId) {
          setMessage("Select a dataset and version before loading from the Dataset Library.");
          return;
        }
        const dataset = libraryDatasets.find((item) => item.datasetId === selectedLibraryDatasetId);
        setIsImporting(true);
        // Part H1: stages advance only at real observable boundaries. The
        // activation endpoint transactionally creates/verifies the project link
        // and commits the exact active version before returning success.
        const advance = (activeStageIndex: number) =>
          setLoadProgress({ phase: "loading", activeStageIndex, failedStageIndex: null, error: null });
        let stageIndex = 0;
        let durablyActivated: CanonicalDatasetIdentity | null = null;
        try {
          advance(0); // Authorizing and durably activating the exact dataset version
          const activation = await activateDatasetVersion(
            selectedLibraryDatasetId,
            selectedLibraryVersionId,
            projectId
          );
          const canonical = assertExactDatasetActivation(
            {
              project_id: projectId,
              dataset_id: selectedLibraryDatasetId,
              dataset_version_id: selectedLibraryVersionId,
            },
            activation
          );
          durablyActivated = canonical;
          setActiveDatasetIdentity(canonical);
          setWorkflowDatasetIdentity(canonical);
          if (activation.workflow_effective_state) {
            applyAuthoritativeWorkflowState(activation.workflow_effective_state);
          }
          setDatasetIdentityError("");
          setReactivationRequired(false);
          setActiveActivationRevision(String(activation.activation_revision));

          stageIndex = 1;
          advance(1); // Resolving dataset version
          const resolvedRowCount = activation.row_count;

          stageIndex = 2;
          advance(2); // Reading governed schema
          const preview = await getDatasetPreview(
            canonical.dataset_id,
            canonical.dataset_version_id
          );

          stageIndex = 3;
          advance(3); // Profiling target and predictors
          const guessedTarget = preferredTarget(preview.columns);
          const normalized = {
            headers: preview.columns,
            previewRows: preview.rows,
            rowCount: resolvedRowCount || preview.rows.length,
            columnCount: preview.columns.length,
            target: guessedTarget,
            selectedColumns: preview.columns.filter((header) => header !== guessedTarget),
            filename: dataset?.name ?? selectedLibraryDatasetId,
            projectId: canonical.project_id,
            datasetId: canonical.dataset_id,
            datasetVersionId: canonical.dataset_version_id,
          };

          stageIndex = 4;
          advance(4); // Evaluating data quality (the quality effect refetches on the new dataset)

          stageIndex = 5;
          advance(5); // Preparing browser preview
          applyLoadedDataset(normalized, {
            sourceLabel: `Dataset Library: ${dataset?.name ?? selectedLibraryDatasetId} (${selectedLibraryVersionId})`,
            backendSynced: true,
            browserComplete: false,
            canonicalIdentity: canonical,
            datasetLibrary: {
              datasetId: canonical.dataset_id,
              versionId: canonical.dataset_version_id,
              datasetName: dataset?.name ?? "Dataset Library asset",
              datasetRole: "modeling",
              sourceType: "dataset-library",
              rowCount: normalized.rowCount,
              columnCount: normalized.columnCount,
              linkedAt: new Date().toISOString(),
            },
          });
          setFileName(dataset?.name ?? "Dataset Library asset");
          setLoadedLibraryIdentity({
            datasetId: canonical.dataset_id,
            versionId: canonical.dataset_version_id,
          });
          setLoadProgress({ phase: "loaded", activeStageIndex: DATASET_LOAD_STAGES.length - 1, failedStageIndex: null, error: null });
          // Part A/6: identity, not display name, is what the analyst is told was loaded.
          setMessage(
            `Loaded ${dataset?.name ?? "Dataset Library asset"}, version ${selectedLibraryVersionId}, into this project after durable activation revision ${activation.activation_revision}.`,
          );
        } catch (error) {
          const detail = error instanceof Error ? error.message : "ATLAS could not load the selected dataset version.";
          // Part H1/7: completed milestones survive, the failed stage is named, no green completion.
          setLoadProgress({ phase: "failed", activeStageIndex: stageIndex, failedStageIndex: stageIndex, error: detail });
          setLoadedLibraryIdentity(null);
          if (!durablyActivated) {
            setActiveDatasetIdentity(null);
            setBackendImportSynced(false);
            setReactivationRequired(true);
            setActiveActivationRevision("");
          }
          setDatasetIdentityError(detail);
          setMessage(detail);
        } finally {
          setIsImporting(false);
        }
      }}
    />
  );

  const governedIdentity = reproducibilityContext?.identity ?? null;
  const governedTargetContract =
    reproducibilityContext?.target_contract ?? null;
  const governedPredictorAuthorization =
    reproducibilityContext?.predictor_authorization ?? null;
  const governedAnalysisPartition =
    reproducibilityContext?.analysis_partition ?? null;
  const reproducibilityContextIsCurrent =
    reproducibilityContextPhase === "ready" &&
    reproducibilityContext?.state === "current";
  const developmentPopulationRows = optionalFiniteNumber(
    governedAnalysisPartition?.development_rows,
  );
  const sealedHoldoutPopulationRows = optionalFiniteNumber(
    governedAnalysisPartition?.sealed_holdout_rows,
  );
  const partitionSplitLabel =
    reproducibilityContextIsCurrent &&
    optionalFiniteNumber(governedAnalysisPartition?.development_share) != null &&
    optionalFiniteNumber(governedAnalysisPartition?.holdout_share) != null
      ? `${Math.round(Number(governedAnalysisPartition?.development_share) * 100)}/${Math.round(Number(governedAnalysisPartition?.holdout_share) * 100)} · sealed`
      : reproducibilityContextPhase === "loading"
        ? "Verifying"
        : "Required";
  const durablePredictorAuthorizationId = String(
    governedPredictorAuthorization?.predictor_authorization_id ?? "",
  ).trim();
  const sectionNavItems = useMemo<DataAcquisitionSectionNavItem[]>(
    () => [
      {
        id: "source-target",
        label: "Source & Target",
        state: activeDatasetIdentity && headers.length && target ? "complete" : "current",
      },
      {
        id: "data-quality-readiness",
        label: "Quality",
        state: quality ? "complete" : headers.length ? "current" : "pending",
      },
      {
        id: "credit-bureau-review",
        label: "Special Values",
        state: bureauReviewStatus?.blocking
          ? "attention"
          : bureauReviewStatus && !bureauReviewStatus.loading
            ? "complete"
            : headers.length
              ? "current"
              : "pending",
        unresolvedCount: bureauReviewStatus?.unresolvedRequirements,
      },
      {
        id: "predictor-authorization",
        label: "Predictors",
        state: durablePredictorAuthorizationId ? "complete" : target ? "current" : "pending",
      },
      {
        id: "analysis-partition-readiness",
        label: "Partition",
        state: reproducibilityContextIsCurrent ? "complete" : activeDatasetIdentity && target ? "current" : "pending",
      },
      {
        id: "code-lineage",
        label: "Code & Lineage",
        state: reproducibilityContextIsCurrent ? "complete" : "pending",
      },
    ],
    [
      activeDatasetIdentity,
      bureauReviewStatus,
      durablePredictorAuthorizationId,
      headers.length,
      quality,
      reproducibilityContextIsCurrent,
      target,
    ],
  );

  return (
    <StepShell
      title="Data Acquisition"
      eyebrow="Predictive Modeling · Step 1 of 13 · Data Contract"
      subtitle="Bind one exact governed dataset version, target contract, predictor authorization, and protected analysis population."
      variant="data"
      heroMetrics={[
        { label: "Dataset", value: governedIdentity?.dataset_name || "Backend confirmation pending" },
        { label: "Exact Version", value: governedIdentity?.dataset_version_id || "Backend confirmation pending", tone: governedIdentity ? "success" : "warning" },
        { label: "Eligible Population", value: governedIdentity?.governed_population_rows != null ? `${governedIdentity.governed_population_rows.toLocaleString()} rows` : "Backend confirmation pending" },
        { label: "Source Columns", value: governedIdentity?.source_columns != null ? governedIdentity.source_columns.toLocaleString() : "Backend confirmation pending" },
        { label: "Target", value: governedTargetContract ? `${governedTargetContract.target} · event ${String(governedTargetContract.event_value)}` : "Backend confirmation pending", tone: governedTargetContract ? "success" : "warning" },
        { label: "Authorized Predictors", value: governedPredictorAuthorization ? `${governedPredictorAuthorization.funnel.authorized_predictor_count.toLocaleString()} current` : "Backend confirmation pending", tone: governedPredictorAuthorization ? "success" : "warning" },
        { label: "Source Type", value: governedIdentity ? formatGovernedSourceType(governedIdentity.source_type) : "Backend confirmation pending" },
        { label: "Registration", value: registrationLabel(acquisitionStatus.registrationState), tone: acquisitionStatus.registrationState === "registered" ? "success" : "warning" },
        { label: "Project Link", value: projectLinkLabel(acquisitionStatus.linkState), tone: acquisitionStatus.linkState === "linked" ? "success" : "warning" },
        { label: "Analysis Partition", value: partitionSplitLabel, tone: reproducibilityContextIsCurrent ? "success" : "warning" },
      ] satisfies AtlasWorkflowMetric[]}
      heroAction={(
        <DataContractStatusChips
          registered={acquisitionStatus.registrationState === "registered"}
          linked={acquisitionStatus.linkState === "linked"}
          loaded={Boolean(governedIdentity)}
          targetConfirmed={Boolean(governedTargetContract)}
          predictorAuthorizationCurrent={Boolean(durablePredictorAuthorizationId)}
          partitionCurrent={reproducibilityContextIsCurrent}
        />
      )}
      showDeveloperTools={false}
      nextDisabled={!acquisitionStatus.canContinue}
      onBlockedNextClick={resolveDataAcquisitionBlocker}
      nextDisabledReason={acquisitionStatus.blockingReasons[0] ?? ""}
      nextLabel={acquisitionStatus.continueLabel}
      nextPath="/step02"
      onNext={async () => {
        const persisted = await persistDataset();
        const canonical = requireCanonicalDatasetIdentity(
          activeDatasetIdentity,
          "Analysis Partition navigation identity",
        );
        const refreshed = await readAnalysisPartitionReadiness(
          canonical,
          target,
          eventValue,
          nonEventValue,
        );
        setAnalysisPartition(refreshed);
        if (refreshed.phase !== "current") {
          throw new Error(
            `${refreshed.message} ${refreshed.recovery}`.trim(),
          );
        }
        const handoff = await fetchCanonicalDataAcquisitionEdaHandoff({
          projectId,
          expectedIdentity: canonical,
        });
        const context = handoff.context;
        const exactTargetMapping =
          context.target_contract.target === target &&
          String(context.target_contract.event_value ?? "") ===
            String(eventValue ?? "") &&
          String(context.target_contract.non_event_value ?? "") ===
            String(nonEventValue ?? "");
        const exactPersistedContracts =
          context.target_contract.target_contract_id ===
            persisted.targetContractId &&
          context.predictor_authorization.predictor_authorization_id ===
            persisted.predictorAuthorizationId;
        const exactPartition =
          context.analysis_partition.analysis_partition_id ===
            refreshed.partition?.analysis_partition_id &&
          context.analysis_partition.revision ===
            refreshed.partition?.revision;
        if (!exactTargetMapping || !exactPersistedContracts || !exactPartition) {
          throw new Error(
            "The final Data Acquisition read-back did not match the exact target, predictor authorization, and Analysis Partition that were just verified.",
          );
        }
        setReproducibilityContext(context);
        setReproducibilityContextPhase("ready");
        setReproducibilityContextError("");
        setConfirmedPartitionPredictorKey(selectedPredictorKey);
        notifyReproducibilityContextConfirmed();
      }}
    >
      <div className="space-y-5">
        <DataAcquisitionSectionNav items={sectionNavItems} />

        <div
          className="grid gap-px overflow-hidden rounded-xl border border-slate-200 bg-slate-200 sm:grid-cols-2 xl:grid-cols-4"
          data-testid="data-acquisition-scope-strip"
          aria-label="Data population scopes"
        >
          <ScopeDatum label="Full governed population" value={governedIdentity?.governed_population_rows ?? null} tone="slate" />
          <ScopeDatum label="Browser preview" value={previewRows.length || null} tone="blue" />
          <ScopeDatum label="Development population" value={developmentPopulationRows ?? null} tone="indigo" />
          <ScopeDatum label="Sealed final holdout" value={sealedHoldoutPopulationRows ?? null} tone="violet" />
        </div>

        {bureauReviewStatus?.blocking &&
        !bureauReviewStatus.loading &&
        !bureauReviewStatus.error ? (
          <section
            className="flex flex-col gap-3 rounded-xl border border-amber-300 bg-amber-50 px-4 py-3 text-amber-950 shadow-sm sm:flex-row sm:items-center sm:justify-between"
            role="status"
            data-testid="special-value-attention-callout"
          >
            <div>
              <div className="text-sm font-semibold">Special-value review requires attention</div>
              <p className="mt-1 text-xs leading-5">
                {bureauReviewStatus.totalVariables.toLocaleString()} bureau variable{bureauReviewStatus.totalVariables === 1 ? "" : "s"} detected · {bureauReviewStatus.unresolvedRequirements.toLocaleString()} treatment requirement{bureauReviewStatus.unresolvedRequirements === 1 ? "" : "s"} unresolved.
              </p>
            </div>
            <button
              type="button"
              className="atlas-secondary-button shrink-0 border-amber-400 bg-white text-xs text-amber-950"
              onClick={() => document.getElementById("credit-bureau-review")?.scrollIntoView({ behavior: "smooth", block: "start" })}
            >
              Go to Special-Value Review
            </button>
          </section>
        ) : null}

        {reactivationRequired && workflowDatasetIdentity && (
          <section
            className="rounded-xl border-2 border-amber-400 bg-amber-50 p-4 text-amber-950 shadow-sm"
            role="alert"
            data-testid="explicit-dataset-reactivation-required"
          >
            <div className="text-sm font-semibold">Explicit dataset reactivation required</div>
            <p className="mt-1 text-sm leading-6">
              ATLAS did not reactivate a dataset from browser storage. Review the saved exact Dataset Library identity below,
              then choose <strong>Load Selected Version</strong> to authorize and durably activate it for this project.
            </p>
            <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 font-mono text-xs">
              <span>dataset_id: {workflowDatasetIdentity.dataset_id}</span>
              <span>dataset_version_id: {workflowDatasetIdentity.dataset_version_id}</span>
            </div>
            <button
              type="button"
              className="mt-3 rounded-lg border border-amber-500 bg-white px-3 py-2 text-sm font-semibold text-amber-950"
              onClick={() => setSourceType("existing")}
              data-testid="review-exact-dataset-reactivation"
            >
              Review exact version
            </button>
          </section>
        )}
        {!reactivationRequired && activeActivationRevision && (
          <div className="sr-only" data-testid="durable-dataset-activation-revision">
            Durable activation revision {activeActivationRevision}
          </div>
        )}
        {message && (
          <div
            className={`rounded-lg border px-4 py-3 text-sm ${messageClass}`}
            role="status"
            aria-live="polite"
            data-testid="data-acquisition-message"
            data-tone={
              importError && !headers.length
                ? "danger"
                : isImporting
                  ? "info"
                  : /^(Loaded|Registered|Cached|Linked|Saved)/i.test(message)
                    ? "success"
                    : "warning"
            }
          >
            {message}
          </div>
        )}

        {/* Part H6: the source-and-load command section carries a strong slate
            identity so the page reads as a sequence of sections rather than a
            uniform white sheet. */}
        <section id="source-target" className="scroll-mt-24 rounded-xl border-2 border-slate-400 bg-slate-100 p-5 shadow-sm" data-testid="source-command-section">
          <div>
            <div className="text-[11px] font-bold uppercase tracking-wide text-slate-600">Source and load</div>
            <h2 className="mt-1 text-base font-semibold text-slate-950">Source and Target</h2>
            <p className="mt-1 text-sm text-slate-700">Start here: load the source file and confirm the target column before reviewing summaries or downstream settings.</p>
          </div>
          <div className="mt-4 grid gap-3 md:grid-cols-5">
            {sourceCards.map((card) => (
              <button
                key={card.id}
                type="button"
                className={`rounded-xl border p-4 text-left shadow-sm transition ${sourceType === card.id ? "border-slate-950 bg-slate-950 text-white" : "border-slate-200 bg-white/80 text-slate-900 hover:bg-white"}`}
                onClick={() => setSourceType(card.id)}
                aria-pressed={sourceType === card.id}
                data-testid={`source-card-${card.id}`}
              >
                <div className={`text-sm font-semibold ${sourceType === card.id ? "text-white" : "text-slate-950"}`}>{card.title}</div>
                <p className={`mt-2 text-xs leading-5 ${sourceType === card.id ? "text-slate-200" : "text-slate-500"}`}>{card.body}</p>
              </button>
            ))}
          </div>
          <div className="mt-4">
            {sourceType === "upload" && (
              <UploadPanel fileName={fileName} onFile={onFile} />
            )}
            {sourceType === "existing" && existingDatasetPicker}
            <div className="mt-5">
              <TargetSetup
                headers={headers}
                target={target}
                setTarget={updateTarget}
                eventValue={eventValue}
                setEventValue={(value) => {
                  markReproducibilityContextPending();
                  setEventValue(value);
                }}
                nonEventValue={nonEventValue}
                setNonEventValue={(value) => {
                  markReproducibilityContextPending();
                  setNonEventValue(value);
                }}
                problemType={targetInfo.kind === "continuous" ? "regression" : "classification"}
              />
            </div>
            {/* Part H3: appears once a classification target is confirmed. */}
            {!!target && targetInfo.kind !== "continuous" && (
              <div className="mt-5">
                <TargetDistributionPanel
                  distribution={targetDistribution}
                  state={targetDistributionState}
                  scopeLabel={
                    targetDistributionRequest
                      ? "full registered population"
                      : quality?.profileScope === "full_dataset"
                        ? "full registered population"
                        : quality?.profileScope === "complete_browser_dataset"
                          ? "complete browser dataset"
                          : "registered population"
                  }
                  query={
                    targetDistributionRequest
                      ? {
                          phase: serverDistribution.phase,
                          elapsedMs: serverDistribution.elapsedMs,
                          error: serverDistribution.error,
                          sampling: serverDistribution.result?.sampling,
                          retry: serverDistribution.retry,
                          calculateExact: serverDistribution.calculateExact,
                        }
                      : undefined
                  }
                />
              </div>
            )}
            {headers.length > 0 && target && (
              <DatasetPersistenceCard
                projectName={projectName}
                target={target}
                rowCount={registeredRowCount}
                columnCount={headers.length}
                choice={persistenceChoice}
                onChoice={setPersistenceChoice}
                registerName={registerName}
                onRegisterNameChange={(value) => {
                  setRegisterName(value);
                  setRegistrationResult(null);
                }}
                registerDescription={registerDescription}
                onRegisterDescriptionChange={setRegisterDescription}
                registerTags={registerTags}
                onRegisterTagsChange={setRegisterTags}
                registering={registering}
                registrationResult={registrationResult}
                registrationError={registrationError}
                duplicateCandidates={duplicateCandidates}
                checkingDuplicates={checkingDuplicates}
                onRegister={() => void handleRegisterDevelopmentDataset()}
                persistenceMode={persistenceMode}
                sourceKindLabel={DATASET_SOURCE_LABELS[datasetSourceKind]}
                registrationActionLabel={resolveRegistrationActionLabel(datasetSourceKind, Boolean(datasetLibraryLink?.datasetId))}
                libraryLink={datasetLibraryLink}
                assetOwner={libraryDatasets.find((item) => item.datasetId === datasetLibraryLink?.datasetId)?.ownerDisplayName}
              />
            )}
            {(sourceType === "sql" || sourceType === "cloud" || sourceType === "python") && (
              <details className="rounded-xl border border-slate-200 bg-slate-50 p-3" open>
                <summary className="cursor-pointer text-sm font-semibold text-slate-900">Configure {sourceCards.find((card) => card.id === sourceType)?.title}</summary>
                <div className="mt-4">
                {sourceType === "sql" && (
                  <SqlPanel
                    provider={provider}
                    setProvider={setProvider}
                    connectionName={connectionName}
                    setConnectionName={setConnectionName}
                    database={database}
                    setDatabase={setDatabase}
                    schema={schema}
                    setSchema={setSchema}
                    sql={sql}
                    setSql={setSql}
                    warnings={sqlWarnings}
                    savedQueries={savedQueries}
                    favoriteQueries={favoriteQueries}
                    onTemplate={(template) => setSql(template)}
                    onSave={() => setSavedQueries((current) => [sql, ...current].slice(0, 8))}
                    onFavorite={() => setFavoriteQueries((current) => [sql, ...current.filter((item) => item !== sql)].slice(0, 5))}
                    onSaveMetadata={saveQueryMetadata}
                  />
                )}
                {sourceType === "cloud" && (
                  <CloudPanel cloudProvider={cloudProvider} setCloudProvider={setCloudProvider} cloudPath={cloudPath} setCloudPath={setCloudPath} />
                )}
                {sourceType === "python" && (
                  <PythonPanel pythonCode={pythonCode} setPythonCode={setPythonCode} />
                )}
                </div>
              </details>
            )}
          </div>
        </section>

        <section className="grid gap-5 xl:grid-cols-[minmax(0,1fr)] xl:items-start">
          <DataPreview
            headers={headers}
            rows={previewRows}
            governedPopulationRowCount={backendRowCount}
            previewRowCount={previewRows.length}
          />
        </section>

        {/* UX-DATAACQ-003 / Part D: this is a readiness checkpoint, not a grey
            appendix. Light-teal identity, stronger border, explicit readiness
            status, and white internal metric cards. */}
        <section
          className="rounded-xl border-2 border-teal-300 bg-teal-50 p-5 shadow-sm"
          data-testid="data-quality-readiness"
          id="data-quality-readiness"
        >
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <div className="text-[11px] font-bold uppercase tracking-wide text-teal-700">Full-population structural review</div>
              <h2 className="mt-1 text-base font-semibold text-teal-950">Data Quality</h2>
              <p className="mt-1 text-sm text-slate-700">Review unique structural findings without repeating the governed dataset identity.</p>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <ReadinessBadge status={acquisitionStatus} />
              <ProfileScopeBadge quality={quality} />
            </div>
          </div>
          <div className="mt-4 rounded-xl border border-teal-200 bg-white p-4">
            <DataQualityPanel quality={quality} />
          </div>
        </section>

        <BureauMetadataBindingPanel
          projectId={projectId}
          datasetIdentity={activeDatasetIdentity}
          featureNames={headers.filter((header) => header !== target)}
          sourceLabel={fileName}
          enabled={!!headers.length && !!registeredRowCount}
        />

        <BureauReviewPanel
          target={target}
          eventValue={eventValue}
          enabled={!!headers.length && !!registeredRowCount}
          datasetIdentity={activeDatasetIdentity}
          onReviewStatus={handleBureauReviewStatus}
          onReviewResult={handleBureauReviewResult}
        />

        {!!headers.length && (
          <section id="predictor-authorization" className="scroll-mt-24 rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
            <div className="flex items-center justify-between gap-3">
              <div>
                <div className="text-[11px] font-bold uppercase tracking-wide text-blue-700">Predictor authorization</div>
                <h2 className="mt-1 text-base font-semibold text-slate-950">Predictor Authorization and Variable Review</h2>
                <p className="mt-1 text-sm text-slate-500">Reconcile source, exclusion, authorization, and analytical-evaluation scopes before reviewing the detailed variable table.</p>
              </div>
              <div className="flex flex-wrap items-center justify-end gap-2">
                <label className="flex max-w-md items-start gap-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs leading-5 text-amber-950">
                  <input
                    className="mt-1"
                    type="checkbox"
                    checked={autoExcludeWeakSignals}
                    disabled={!weakSignalPlan.eligible}
                    onChange={(event) => setAutoExcludeWeakSignals(event.target.checked)}
                    data-testid="weak-signal-toggle" 
                  />
                  <span>
                    Uncheck weak-signal features automatically. Classification uses the configured ATLAS weak-signal
                    threshold IV &lt; {WEAK_SIGNAL_IV_THRESHOLD}; regression uses absolute correlation &lt;{" "}
                    {WEAK_CORRELATION_THRESHOLD.toFixed(2)}. Predictors whose Information Value is unavailable are never
                    removed.
                  </span>
                </label>
                {autoExcludeWeakSignals && weakSignalPlan.eligible ? (
                  <button
                    type="button"
                    className="rounded-lg border border-amber-400 bg-white px-3 py-2 text-sm font-semibold text-amber-900"
                    data-testid="weak-signal-apply"
                    onClick={applyWeakSignalFilter}
                  >
                    Apply to {weakSignalPlan.affected.length} predictor(s)
                  </button>
                ) : null}
                {weakSignalUndo ? (
                  <button
                    type="button"
                    className="rounded-lg border px-3 py-2 text-sm"
                    data-testid="weak-signal-undo"
                    onClick={undoWeakSignalFilter}
                  >
                    Undo
                  </button>
                ) : null}
                <button
                  className="rounded-lg border px-3 py-2 text-sm"
                  data-testid="predictor-select-all"
                  onClick={() => {
                    const nextKept = Object.fromEntries(predictorVariableSummary.map((row) => [row.column, row.role === "eligible"]));
                    saveKeptSelection(nextKept);
                  }}
                >
                  Select all
                </button>
                <button
                  className="rounded-lg border px-3 py-2 text-sm"
                  onClick={() => {
                    const nextKept = Object.fromEntries(headers.map((header) => [header, false]));
                    saveKeptSelection(nextKept);
                  }}
                >
                  None
                </button>
                <button
                  type="button"
                  className="rounded-lg bg-blue-700 px-3 py-2 text-sm font-semibold text-white shadow-sm hover:bg-blue-800 disabled:cursor-not-allowed disabled:opacity-50"
                  data-testid="update-predictor-authorization"
                  disabled={
                    !predictorAuthorizationDraft.canUpdate &&
                    !predictorAuthorizationDraft.canRetryBaseline &&
                    !predictorAuthorizationVerificationError
                  }
                  onClick={() => {
                    if (predictorAuthorizationDraft.canRetryBaseline) {
                      retryPredictorAuthorizationContext();
                    } else {
                      void updatePredictorAuthorization();
                    }
                  }}
                >
                  {predictorAuthorizationActionLabel}
                </button>
              </div>
            </div>
            {predictorAuthorizationDraft.dirty ? (
              <div
                className="mt-3 rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-xs leading-5 text-amber-950"
                data-testid="predictor-authorization-draft-status"
                role="status"
              >
                {predictorAuthorizationDraft.reason}
              </div>
            ) : null}
            {predictorAuthorizationFeedback ? (
              <div
                className="mt-2 rounded-lg border border-blue-200 bg-blue-50 px-3 py-2 text-xs leading-5 text-blue-950"
                data-testid="predictor-authorization-feedback"
                role="status"
                aria-live="polite"
              >
                {predictorAuthorizationFeedback}
              </div>
            ) : null}
            <PredictorAuthorizationFunnel
              authorization={governedPredictorAuthorization}
              contextPhase={reproducibilityContextPhase}
              contextError={reproducibilityContextError}
              evaluatedCount={
                governedProfile.profile ? predictorCounts.evaluated : null
              }
              unavailable={predictorCounts.unavailable}
            />
            {!weakSignalPlan.eligible && weakSignalPlan.blockedReason ? (
              <p className="mt-3 rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-950" data-testid="weak-signal-blocked-reason">
                {weakSignalPlan.blockedReason}
              </p>
            ) : null}
            {weakSignalNotice ? (
              <p className="mt-2 text-xs font-semibold text-slate-700" role="status" aria-live="polite" data-testid="weak-signal-notice">
                {weakSignalNotice}
              </p>
            ) : null}
            <p className="mt-3 text-xs text-slate-600" data-testid="variable-summary-scope">
              {governedProfile.profile
                ? `Scope: ${governedProfile.profile.analysisScope.label} - ${governedProfile.profile.quality.populationRows.toLocaleString()} rows - calculated ${new Date(governedProfile.profile.generatedAt).toLocaleString()}.`
                : governedProfile.phase === "artifact_missing"
                  ? "Legacy Dataset Version: Full Artifact Unavailable. Information Value cannot be calculated for this version."
                  : governedProfile.phase === "failed"
                    ? `Authoritative predictor profiling failed: ${governedProfile.error}`
                    : "Calculating the authoritative predictor profile..."}
            </p>
            {governedProfile.profile ? (
              <div
                className="mt-2 grid gap-2 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-xs sm:grid-cols-2 xl:grid-cols-4"
                data-testid="predictor-evaluation-summary"
              >
                <div>
                  <span className="font-semibold text-slate-900" data-testid="predictors-evaluated">
                    {predictorCounts.evaluated} predictors evaluated
                  </span>
                  <div className="text-slate-600">Development-population analytical coverage</div>
                </div>
                <div>
                  <span className="font-semibold text-amber-900" data-testid="unusually-strong-count">
                    {predictorCounts.unusuallyStrong} unusually strong
                  </span>
                  <div className="text-slate-600">Require human review</div>
                </div>
                <div>
                  <span className="font-semibold text-slate-900" data-testid="leakage-review-count">
                    {predictorCounts.leakageReview} automated leakage signals
                  </span>
                  <div className="text-slate-600">Review recommended, not confirmed</div>
                </div>
                <div>
                  <span className="font-semibold text-slate-900" data-testid="unavailable-predictor-count">
                    {predictorCounts.unavailable.length} predictors unavailable
                  </span>
                  {predictorCounts.unavailable.length ? (
                    <details className="text-slate-600">
                      <summary className="cursor-pointer">Show details</summary>
                      <ul className="mt-1 list-disc pl-4" data-testid="unavailable-predictor-list">
                        {predictorCounts.unavailable.slice(0, 10).map((item) => (
                          <li key={item.predictor}>
                            {item.predictor}: {item.reason}
                          </li>
                        ))}
                      </ul>
                      {predictorCounts.unavailable.length > 10 ? (
                        <p className="mt-1">{predictorCounts.unavailable.length - 10} more not listed.</p>
                      ) : null}
                    </details>
                  ) : (
                    <div className="text-slate-600">All selected predictors evaluated</div>
                  )}
                </div>
              </div>
            ) : null}
            {predictorCounts.unusuallyStrong ? (
              <p
                className="mt-2 rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-950"
                data-testid="high-iv-explanation"
              >
                <strong>Why unusually high Information Value matters:</strong> {HIGH_IV_EXPLANATION} These predictors are
                not deselected automatically and do not block Data Acquisition.
              </p>
            ) : null}
            {governedProfile.phase === "artifact_missing" && governedProfile.artifactMissing ? (
              <div className="mt-2 rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-950" data-testid="legacy-artifact-missing">
                <p className="font-semibold">Legacy Dataset Version: Full Artifact Unavailable</p>
                <p className="mt-1">{governedProfile.artifactMissing.disclosure}</p>
                <ul className="mt-1 list-disc pl-5">
                  {governedProfile.artifactMissing.recovery.map((item) => (<li key={item}>{item}</li>))}
                </ul>
              </div>
            ) : null}
            {governedProfile.phase === "failed" ? (
              <button type="button" className="mt-2 rounded-lg border px-3 py-1.5 text-xs" data-testid="profile-retry" onClick={governedProfile.retry}>
                Retry profiling
              </button>
            ) : null}
            {featureProfileError ? (
              <div
                className="mt-3 flex flex-wrap items-center justify-between gap-3 rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-xs leading-5 text-amber-950"
                data-testid="feature-profile-error"
                role="alert"
              >
                <span>
                  <strong>Variable statistics are unavailable.</strong>{" "}
                  {featureProfileError}
                </span>
                <button
                  type="button"
                  className="rounded-lg border border-amber-400 bg-white px-3 py-1.5 font-semibold text-amber-950"
                  data-testid="feature-profile-retry"
                  onClick={() =>
                    setFeatureProfileRetryRevision((revision) => revision + 1)
                  }
                >
                  Retry variable statistics
                </button>
              </div>
            ) : null}
            <div className="mt-4 max-h-[560px] overflow-auto rounded-lg border border-slate-200">
              <table className="min-w-full text-sm">
                <thead className="sticky top-0 bg-slate-50 text-xs uppercase text-slate-500">
                  <tr>
                    <th className="px-3 py-2 text-center">Keep</th>
                    <th className="px-3 py-2 text-left">Column</th>
                    <th className="px-3 py-2 text-left">Role</th>
                    <th className="px-3 py-2 text-left">Type</th>
                    <th className="px-3 py-2 text-right">Special values</th>
                    <th className="px-3 py-2 text-right">Special %</th>
                    <th className="px-3 py-2 text-left">Observed codes</th>
                    <th className="px-3 py-2 text-left">Special-value review</th>
                    <th className="px-3 py-2 text-right">{targetInfo.kind === "continuous" ? "Corr(Target)" : "IV"}</th>
                    <th className="px-3 py-2 text-left">Signal strength</th>
                    <th className="px-3 py-2 text-left">Calculation status</th>
                    <th className="px-3 py-2 text-right">Missing %</th>
                    <th className="px-3 py-2 text-right">Distinct</th>
                    <th className="px-3 py-2 text-right">Mean</th>
                    <th className="px-3 py-2 text-right">Min</th>
                    <th className="px-3 py-2 text-right">Max</th>
                    <th className="px-3 py-2 text-left">Leakage status</th>
                    <th className="px-3 py-2 text-left">Reason</th>
                  </tr>
                </thead>
                <tbody>
                  {predictorVariableSummary.map((row) => {
                    const leakageRole = row.role === "eligible" ? "" : row.role;
                    const role = leakageRole || "Candidate Predictor";
                    return (
                      <tr key={row.column} className="border-t">
                        <td className="px-3 py-2 text-center">
                          {leakageRole ? (
                            <input type="checkbox" disabled checked={false} aria-label={`${row.column} disabled excluded predictor`} />
                          ) : (
                            <input
                              type="checkbox"
                              checked={!!kept[row.column]}
                              onChange={(event) => {
                                const nextKept = { ...kept, [row.column]: event.target.checked };
                                saveKeptSelection(nextKept);
                                logDecision({
                                  workflowStep: "Data Acquisition",
                                  actionType: "feature_inclusion_changed",
                                  subject: row.column,
                                  previousValue: kept[row.column] ? "included" : "excluded",
                                  newValue: event.target.checked ? "included" : "excluded",
                                });
                              }}
                            />
                          )}
                        </td>
                        <td className="px-3 py-2 font-medium">{row.column}</td>
                        <td className="px-3 py-2 text-xs font-semibold text-slate-700">{role}</td>
                        <td className="px-3 py-2">{row.type}</td>
                        <td className="px-3 py-2 text-right" data-testid="predictor-special-value-count">
                          {row.specialValueCount.toLocaleString()}
                        </td>
                        <td className="px-3 py-2 text-right" data-testid="predictor-special-value-rate">
                          {formatPercent(row.specialValueRate)}
                        </td>
                        <td className="whitespace-nowrap px-3 py-2 text-xs" data-testid="predictor-special-value-codes">
                          {row.specialValueCodes.length
                            ? row.specialValueCodes.join(", ")
                            : "—"}
                        </td>
                        <td
                          className={`whitespace-nowrap px-3 py-2 text-xs font-semibold ${
                            row.specialValueReviewStatus === "Review required"
                              ? "text-amber-800"
                              : row.specialValueReviewStatus === "Confirmed"
                                ? "text-emerald-700"
                                : "text-slate-600"
                          }`}
                          data-testid="predictor-special-value-review-status"
                        >
                          {row.specialValueReviewStatus}
                        </td>
                        {targetInfo.kind === "continuous" ? (
                          <td className={`px-3 py-2 text-right ${signalStatusClass(row.corr)}`}>{formatNumber(row.corr)}</td>
                        ) : (
                          <td className="px-3 py-2 text-right" data-testid="iv-cell" data-iv-status={governedIv(row.column).ivStatus}>
                            <span
                              className={governedIv(row.column).ivStatus === "available" ? ivStatusClass(governedIv(row.column).iv) : "text-slate-500"}
                              title={
                                governedIv(row.column).ivStatus === "available"
                                  ? `Exact Information Value: ${formatIvExact(governedIv(row.column).iv)}`
                                  : IV_STATUS_LABELS[governedIv(row.column).ivStatus]
                              }
                            >
                              {ivCellText(governedIv(row.column))}
                            </span>
                          </td>
                        )}
                        <td className="px-3 py-2 text-xs" data-testid="signal-strength-cell">
                          {(() => {
                            const strength = signalStrength(governedIv(row.column));
                            if (!strength) return <span className="text-slate-400">Not available</span>;
                            return (
                              <span
                                data-signal-strength={strength.key}
                                className={
                                  strength.tone === "warning"
                                    ? "rounded-full border border-amber-300 bg-amber-50 px-2 py-0.5 font-semibold text-amber-900"
                                    : "text-slate-700"
                                }
                                title={strength.reviewRecommended ? HIGH_IV_EXPLANATION : undefined}
                              >
                                {strength.label}
                                {strength.reviewRecommended ? " - review recommended" : ""}
                              </span>
                            );
                          })()}
                        </td>
                        <td className="px-3 py-2 text-xs text-slate-600" data-testid="iv-status-cell">
                          {targetInfo.kind === "continuous" ? "Correlation" : IV_STATUS_LABELS[governedIv(row.column).ivStatus]}
                        </td>
                        <td className="px-3 py-2 text-right">{formatPercent(row.missingPct)}</td>
                        <td className="px-3 py-2 text-right">
                          {typeof row.distinct === "number"
                            ? row.distinct.toLocaleString()
                            : "-"}
                        </td>
                        <td className="px-3 py-2 text-right">{formatNumber(row.mean)}</td>
                        <td className="px-3 py-2 text-right">{formatNumber(row.min)}</td>
                        <td className="px-3 py-2 text-right">{formatNumber(row.max)}</td>
                        <td className="px-3 py-2 text-xs font-semibold" data-testid="leakage-screen-cell">
                          {(() => {
                            const state = leakageScreen({
                              iv: governedIv(row.column).iv,
                              ivStatus: governedIv(row.column).ivStatus,
                              role: row.role,
                              eligible: !leakageRole,
                            });
                            const label = leakageRole ? "Excluded" : LEAKAGE_SCREEN_LABELS[state];
                            return (
                              <span
                                data-leakage-state={leakageRole ? "excluded" : state}
                                className={
                                  leakageRole
                                    ? "text-rose-700"
                                    : state === "review_recommended"
                                      ? "text-amber-800"
                                      : "text-slate-700"
                                }
                              >
                                {label}
                              </span>
                            );
                          })()}
                        </td>
                        <td className="px-3 py-2 text-xs text-slate-600">{row.exclusionReason || "Eligible predictor."}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </section>
        )}

        {analysisPartitionResetMode ? (
          <AnalysisPartitionResetWorkspace
            impact={analysisPartitionResetImpact}
            preview={analysisPartitionPreview}
            readiness={analysisPartition}
            holdoutShare={analysisPartitionResetHoldoutShare}
            onHoldoutShare={(value) => {
              markReproducibilityContextPending();
              setAnalysisPartitionResetHoldoutShare(value);
            }}
            randomSeed={analysisPartitionResetRandomSeed}
            onRandomSeed={setAnalysisPartitionResetRandomSeed}
            stratificationPolicy={analysisPartitionResetStratification}
            onStratificationPolicy={setAnalysisPartitionResetStratification}
            reason={analysisPartitionResetReason}
            onReason={setAnalysisPartitionResetReason}
            invalidationAcknowledged={analysisPartitionResetInvalidationAcknowledged}
            onInvalidationAcknowledged={setAnalysisPartitionResetInvalidationAcknowledged}
            feedback={analysisPartitionResetFeedback}
            completed={analysisPartitionResetCompleted}
            canReset={Boolean(
              activeDatasetIdentity &&
                target &&
                String(
                  analysisPartitionResetImpact.partition?.target_contract_id ??
                    "",
                ).trim() &&
                currentDurablePredictorAuthorizationId(
                  analysisPartitionResetImpact.partition,
                ),
            )}
            target={target}
            problemType={targetInfo.kind === "continuous" ? "regression" : "classification"}
            onConfirm={() => void confirmGovernedAnalysisPartitionReset()}
            onExit={leaveAnalysisPartitionResetMode}
          />
        ) : (
          <AnalysisPartitionWorkspace
            readiness={analysisPartition}
            holdoutShare={analysisPartitionHoldoutShare}
            onHoldoutShare={(value) => {
              markReproducibilityContextPending();
              setAnalysisPartitionHoldoutShare(value);
              setAnalysisPartitionRationale("");
            }}
            preview={analysisPartitionPreview}
            rationale={analysisPartitionRationale}
            onRationale={setAnalysisPartitionRationale}
            onConfirm={() => void confirmRecommendedAnalysisPartition()}
            onCompleteDocumentation={() => void retryAnalysisPartitionDocumentation()}
            canConfirm={Boolean(
              activeDatasetIdentity && target && selected.length,
            )}
            target={target}
            problemType={targetInfo.kind === "continuous" ? "regression" : "classification"}
            projectId={projectId}
          />
        )}

        {!!headers.length && (
          <section id="code-lineage" className="scroll-mt-24 space-y-4">
            <div>
              <div className="text-[11px] font-bold uppercase tracking-wide text-slate-600">Data Lineage and Reproducibility</div>
              <h2 className="mt-1 text-base font-semibold text-slate-950">Code &amp; Lineage</h2>
              <p className="mt-1 text-sm text-slate-600">Inspect governed provenance and copy exact backend-confirmed Python, SAS, or metadata context.</p>
            </div>
            <div className="grid gap-4">
              <LineagePanel metadata={generatedMetadata ?? metadata} />
              <StepPythonPanel />
            </div>
          </section>
        )}
      </div>
    </StepShell>
  );
}

function AnalysisPartitionResetWorkspace(props: {
  impact: AnalysisPartitionResetImpactState;
  preview: AnalysisPartitionPreview;
  readiness: AnalysisPartitionReadiness;
  holdoutShare: string;
  onHoldoutShare: (value: string) => void;
  randomSeed: string;
  onRandomSeed: (value: string) => void;
  stratificationPolicy: "target" | "none";
  onStratificationPolicy: (value: "target" | "none") => void;
  reason: string;
  onReason: (value: string) => void;
  invalidationAcknowledged: boolean;
  onInvalidationAcknowledged: (value: boolean) => void;
  feedback: string;
  completed: {
    partitionId: string;
    previousRevision: number;
    revision: number;
    impacts: string[];
  } | null;
  canReset: boolean;
  target: string;
  problemType: "classification" | "regression";
  onConfirm: () => void;
  onExit: () => void;
}) {
  const busy =
    props.impact.phase === "loading" ||
    props.readiness.phase === "confirming";
  const baseline = props.impact.partition;
  const holdoutShare = Number(props.holdoutShare);
  const developmentShare = Number.isFinite(holdoutShare)
    ? 1 - holdoutShare
    : Number.NaN;
  const currentDevelopmentRows = optionalFiniteNumber(
    baseline?.development_count ?? baseline?.development_rows,
  );
  const currentHoldoutRows = optionalFiniteNumber(
    baseline?.holdout_count ??
      baseline?.holdout_rows ??
      baseline?.sealed_holdout_rows,
  );
  const currentEligibleRows =
    optionalFiniteNumber(baseline?.population_count) ??
    (currentDevelopmentRows != null && currentHoldoutRows != null
      ? currentDevelopmentRows + currentHoldoutRows
      : undefined);
  const resetReasonLength = props.reason.trim().length;
  const resetReasonReady =
    resetReasonLength > 0 &&
    (!props.preview.rationaleRequired ||
      resetReasonLength >= MIN_ANALYSIS_PARTITION_RATIONALE_LENGTH);
  const canSubmit =
    props.impact.phase === "ready" &&
    Boolean(baseline) &&
    props.preview.phase === "ready" &&
    props.preview.blockers.length === 0 &&
    Boolean(props.preview.previewFingerprint) &&
    props.canReset &&
    resetReasonReady &&
    props.invalidationAcknowledged &&
    !props.completed &&
    !busy;
  const displayedImpacts = props.completed?.impacts.length
    ? props.completed.impacts
    : props.impact.impacts;
  const formatPercent = (value: unknown) => {
    const numeric = Number(value);
    return Number.isFinite(numeric) ? `${(numeric * 100).toFixed(0)}%` : "Unavailable";
  };

  return (
    <section
      id="analysis-partition-readiness"
      data-testid="analysis-partition-reset-workspace"
      data-reset-mode="explicit"
      data-downstream-status={props.completed ? "stale" : "unchanged"}
      className="overflow-hidden rounded-xl border-2 border-amber-500 bg-white shadow-[0_14px_34px_rgba(180,83,9,0.14)]"
    >
      <div className="flex flex-wrap items-start justify-between gap-3 bg-gradient-to-r from-amber-800 to-orange-700 px-5 py-4 text-white">
        <div>
          <div className="text-[10px] font-bold uppercase tracking-[0.18em] text-amber-100">
            Governed split-ratio change
          </div>
          <h2 className="mt-1 text-lg font-semibold">
            Change Split Ratio — Creates New Revision
          </h2>
          <p className="mt-1 max-w-3xl text-xs leading-5 text-amber-50">
            Review the impact before authorizing a new partition revision. The current partition remains sealed and unchanged until explicit confirmation succeeds.
          </p>
        </div>
        <span className="rounded-full border border-amber-200 bg-amber-50 px-3 py-1 text-xs font-bold text-amber-950">
          {props.completed
            ? "Ratio changed · downstream stale"
            : busy
              ? "Loading governed impact"
              : "Explicit confirmation required"}
        </span>
      </div>

      <div className="space-y-5 p-5">
        <div
          className={`rounded-lg border px-4 py-3 text-sm ${
            props.impact.phase === "error"
              ? "border-red-300 bg-red-50 text-red-950"
              : "border-amber-300 bg-amber-50 text-amber-950"
          }`}
          role={props.impact.phase === "error" ? "alert" : "status"}
        >
          <div className="font-semibold">
            {props.impact.message || "Loading the split-change impact for the exact current partition..."}
          </div>
          {baseline ? (
            <dl className="mt-3 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
              <div><dt className="text-xs font-semibold uppercase tracking-wide">Current partition</dt><dd className="mt-1 break-all font-mono text-xs">{baseline.analysis_partition_id}</dd></div>
              <div><dt className="text-xs font-semibold uppercase tracking-wide">Current revision</dt><dd className="mt-1 font-semibold">{baseline.revision}</dd></div>
              <div><dt className="text-xs font-semibold uppercase tracking-wide">Current holdout</dt><dd className="mt-1 font-semibold">{formatPercent(baseline.holdout_share)}</dd></div>
              <div><dt className="text-xs font-semibold uppercase tracking-wide">Current policy</dt><dd className="mt-1 font-semibold">Seed {baseline.random_seed ?? "Unavailable"} · {baseline.stratification_policy === "none" ? "Not stratified" : `Stratified by ${baseline.stratification_field ?? props.target}`}</dd></div>
            </dl>
          ) : null}
        </div>

        <div className="rounded-xl border border-red-200 bg-red-50 p-4">
          <h3 className="text-sm font-semibold text-red-950">Change impact · dependent artifacts become stale</h3>
          <p className="mt-1 text-xs leading-5 text-red-900">
            ATLAS does not delete the prior sealed holdout. It preserves that revision for audit and invalidates dependent evidence before any work can be recomputed against the replacement.
          </p>
          {displayedImpacts.length ? (
            <ul className="mt-3 list-disc space-y-1.5 pl-5 text-xs leading-5 text-red-950" data-testid="analysis-partition-reset-impacts">
              {displayedImpacts.map((impact) => <li key={impact}>{impact}</li>)}
            </ul>
          ) : (
            <p className="mt-3 text-xs font-semibold text-red-900">
              No change can be submitted until the durable impact list loads.
            </p>
          )}
        </div>

        <div className="rounded-xl border border-slate-200 bg-slate-50 p-4">
          <div className="flex flex-wrap items-start justify-between gap-2">
            <div>
              <h3 className="text-sm font-semibold text-slate-950">Choose the proposed split ratio</h3>
              <p className="mt-1 text-xs leading-5 text-slate-600">
                ATLAS offers the same governed standard choices used when a new partition is created. Seed and stratification remain fixed to the current sealed policy.
              </p>
            </div>
            <span className="rounded-full border border-slate-300 bg-white px-3 py-1 text-xs font-semibold text-slate-700">
              Proposed development {Number.isFinite(developmentShare) ? formatPercent(developmentShare) : "Unavailable"}
            </span>
          </div>
          <div
            className="mt-4 grid gap-3 lg:grid-cols-[1fr_auto_1fr] lg:items-stretch"
            data-testid="analysis-partition-reset-comparison"
            aria-label="Current versus proposed Analysis Partition"
          >
            <div className="rounded-lg border border-slate-300 bg-white p-4">
              <div className="text-[10px] font-bold uppercase tracking-wide text-slate-600">
                Current governed partition
              </div>
              <div className="mt-2 text-base font-semibold text-slate-950">
                {baseline
                  ? `${formatPercent(1 - Number(baseline.holdout_share))} development / ${formatPercent(baseline.holdout_share)} final holdout`
                  : "Current ratio unavailable"}
              </div>
              <p className="mt-1 text-xs text-slate-600">
                Revision {baseline?.revision ?? "Unavailable"} remains current and sealed until confirmation succeeds.
              </p>
              <dl
                className="mt-3 grid gap-2 sm:grid-cols-3"
                data-testid="analysis-partition-reset-current-counts"
              >
                <SummaryDatum
                  label="Current eligible rows"
                  value={currentEligibleRows?.toLocaleString() ?? "Unavailable"}
                />
                <SummaryDatum
                  label="Current development rows"
                  value={currentDevelopmentRows?.toLocaleString() ?? "Unavailable"}
                />
                <SummaryDatum
                  label="Current final holdout rows"
                  value={currentHoldoutRows?.toLocaleString() ?? "Unavailable"}
                />
              </dl>
            </div>
            <div className="hidden items-center justify-center text-lg font-bold text-amber-700 lg:flex" aria-hidden="true">
              →
            </div>
            <div className="rounded-lg border-2 border-amber-400 bg-amber-50 p-4">
              <div className="text-[10px] font-bold uppercase tracking-wide text-amber-800">
                Proposed new revision
              </div>
              <div className="mt-2 text-base font-semibold text-amber-950">
                {Number.isFinite(developmentShare)
                  ? `${formatPercent(developmentShare)} development / ${formatPercent(holdoutShare)} final holdout`
                  : "Select a governed ratio"}
              </div>
              <p className="mt-1 text-xs text-amber-900">
                Creates revision {Number.isFinite(Number(baseline?.revision)) ? Number(baseline?.revision) + 1 : "after current"}; it never edits the existing revision in place.
              </p>
            </div>
          </div>
          <div className="mt-4 grid gap-4 lg:grid-cols-[minmax(260px,1fr)_minmax(0,2fr)]">
            <label className="text-xs font-semibold text-slate-700">
              Development / Final Holdout Split
              <select
                data-testid="analysis-partition-reset-holdout-share"
                className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-950"
                value={props.holdoutShare}
                disabled={busy || Boolean(props.completed)}
                onChange={(event) => props.onHoldoutShare(event.target.value)}
              >
                {INITIAL_HOLDOUT_OPTIONS.map((holdoutShare) => (
                  <option key={holdoutShare} value={holdoutShare}>
                    {Math.round((1 - holdoutShare) * 100)}% Development / {Math.round(holdoutShare * 100)}% Final Holdout
                    {holdoutShare === PARTITION_DEFAULTS.holdoutShare ? " (Recommended)" : ""}
                  </option>
                ))}
              </select>
            </label>
            <dl className="grid gap-2 sm:grid-cols-2">
              <SummaryDatum label="Fixed random seed" value={baseline?.random_seed ?? props.randomSeed} />
              <SummaryDatum label="Fixed stratification" value={baseline?.stratification_policy === "none" ? "Not stratified" : `Target · ${baseline?.stratification_field ?? props.target}`} />
              <SummaryDatum label="Current partition ID" value={baseline?.analysis_partition_id ?? "Unavailable"} mono />
              <SummaryDatum label="Current revision" value={baseline?.revision ?? "Unavailable"} />
            </dl>
          </div>
          <div className="mt-4 rounded-lg border border-indigo-200 bg-white p-4" data-testid="analysis-partition-reset-preview">
            <div className="flex items-center justify-between gap-3">
              <div className="text-xs font-bold uppercase tracking-wide text-indigo-700">Backend-authoritative preview</div>
              <span className="rounded-full bg-slate-100 px-2.5 py-1 text-[11px] font-semibold text-slate-700">
                {props.preview.phase === "loading" ? "Calculating" : props.preview.phase}
              </span>
            </div>
            {props.preview.phase === "ready" ? (
              <>
                <dl className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
                  <SummaryDatum label="Eligible rows" value={props.preview.totalEligibleRows?.toLocaleString() ?? "Unavailable"} />
                  <SummaryDatum label="Development rows" value={props.preview.developmentRows?.toLocaleString() ?? "Unavailable"} />
                  <SummaryDatum label="Final holdout rows" value={props.preview.holdoutRows?.toLocaleString() ?? "Unavailable"} />
                  <SummaryDatum label="Sufficiency" value={props.preview.recommendationStatus ?? "Unavailable"} />
                </dl>
                <MessageList title="Warnings" items={props.preview.warnings} tone="amber" />
                <MessageList title="Blockers" items={props.preview.blockers} tone="red" />
              </>
            ) : (
              <p className="mt-2 text-xs leading-5 text-slate-600">{props.preview.message}</p>
            )}
          </div>
        </div>

        <label className="block text-xs font-semibold text-slate-700">
          Required analyst rationale
          <textarea
            rows={3}
            data-testid="analysis-partition-reset-reason"
            className="mt-1 w-full resize-y rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-normal text-slate-950"
            value={props.reason}
            minLength={
              props.preview.rationaleRequired
                ? MIN_ANALYSIS_PARTITION_RATIONALE_LENGTH
                : 1
            }
            disabled={busy || Boolean(props.completed)}
            onChange={(event) => props.onReason(event.target.value)}
            placeholder="Explain why new partition membership is required and why invalidating downstream evidence is justified."
          />
          <span className="mt-1 block font-normal text-slate-600">
            {props.preview.rationaleRequired
              ? `The proposed split requires at least ${MIN_ANALYSIS_PARTITION_RATIONALE_LENGTH} characters under the backend policy.`
              : "A reset reason is required; this split does not require the additional policy-rationale minimum."}
          </span>
        </label>

        <label className="flex items-start gap-3 rounded-lg border border-red-300 bg-red-50 p-4 text-sm leading-6 text-red-950">
          <input
            className="mt-1"
            type="checkbox"
            data-testid="analysis-partition-reset-invalidation-acknowledgement"
            checked={props.invalidationAcknowledged}
            disabled={busy || Boolean(props.completed) || props.impact.phase !== "ready"}
            onChange={(event) => props.onInvalidationAcknowledged(event.target.checked)}
          />
          <span>
            I reviewed every impact above and authorize ATLAS to mark EDA, preprocessing, feature, validation, training, evaluation, interpretation, and promotion artifacts stale when the replacement partition is created.
          </span>
        </label>

        {props.feedback ? (
          <div
            className={`rounded-lg border px-4 py-3 text-sm ${
              props.completed
                ? "border-emerald-300 bg-emerald-50 text-emerald-950"
                : "border-amber-300 bg-amber-50 text-amber-950"
            }`}
            role={props.completed ? "status" : "alert"}
          >
            {props.feedback}
          </div>
        ) : null}

        {props.completed ? (
          <div
            className="rounded-xl border-2 border-emerald-400 bg-emerald-50 p-4 text-emerald-950"
            data-testid="analysis-partition-reset-result"
            data-readiness="current"
            data-final-holdout="sealed"
            data-holdout-isolation="verified"
            data-downstream-status="stale"
          >
            <div className="flex items-center gap-2 text-sm font-semibold"><ShieldCheck size={17} /> Durable replacement verified</div>
            <dl className="mt-3 grid gap-3 sm:grid-cols-3">
              <div><dt className="text-xs font-semibold uppercase tracking-wide">Previous revision</dt><dd className="mt-1 font-semibold">{props.completed.previousRevision}</dd></div>
              <div><dt className="text-xs font-semibold uppercase tracking-wide">New positive revision</dt><dd className="mt-1 font-semibold">{props.completed.revision}</dd></div>
              <div><dt className="text-xs font-semibold uppercase tracking-wide">New partition</dt><dd className="mt-1 break-all font-mono text-xs">{props.completed.partitionId}</dd></div>
            </dl>
            <p className="mt-3 text-xs leading-5" data-testid="analysis-partition-downstream-stale">
              The replacement is current, the final holdout is sealed, and isolation is verified. Downstream artifacts remain stale; ATLAS did not continue, rebuild, or navigate automatically.
            </p>
          </div>
        ) : null}

        <div className="flex flex-wrap justify-end gap-3 border-t border-slate-200 pt-4">
          <button
            type="button"
            className="atlas-secondary-button"
            onClick={props.onExit}
            disabled={busy}
          >
            {props.completed ? "Close change review · stay on Data Acquisition" : "Cancel change · keep current partition"}
          </button>
          {!props.completed ? (
            <button
              type="button"
              data-testid="confirm-analysis-partition-reset"
              className="inline-flex items-center justify-center gap-2 rounded-lg bg-red-700 px-4 py-2.5 text-sm font-semibold text-white shadow-sm hover:bg-red-800 disabled:cursor-not-allowed disabled:opacity-55"
              disabled={!canSubmit}
              onClick={props.onConfirm}
            >
              {props.readiness.phase === "confirming" ? <Loader2 size={16} className="animate-spin" /> : <ShieldCheck size={16} />}
              Create New Analysis Partition Revision
            </button>
          ) : null}
        </div>
      </div>
    </section>
  );
}

function AnalysisPartitionWorkspace(props: {
  readiness: AnalysisPartitionReadiness;
  holdoutShare: number;
  onHoldoutShare: (value: number) => void;
  preview: AnalysisPartitionPreview;
  rationale: string;
  onRationale: (value: string) => void;
  onConfirm: () => void;
  onCompleteDocumentation: () => void;
  canConfirm: boolean;
  target: string;
  problemType: "classification" | "regression";
  projectId: string;
}) {
  const current = props.readiness.phase === "current";
  const documentationPending =
    props.readiness.phase === "documentation_pending" ||
    props.readiness.phase === "documenting";
  const partitionPresent = current || documentationPending;
  const busy =
    props.readiness.phase === "checking" ||
    props.readiness.phase === "confirming" ||
    props.readiness.phase === "documenting";
  const partition = props.readiness.partition;
  const proposedPolicy = initialAnalysisPartitionPolicy(
    props.holdoutShare,
    props.problemType,
  );
  const statusClass = current
    ? "border-emerald-300 bg-emerald-50 text-emerald-900"
    : props.readiness.phase === "error"
      ? "border-red-300 bg-red-50 text-red-900"
      : "border-amber-300 bg-amber-50 text-amber-950";
  const previewBlocked = props.preview.recommendationStatus === "blocked" || props.preview.blockers.length > 0;
  const previewEvidenceComplete = analysisPartitionPreviewHasRequiredEvidence(
    props.preview,
    props.problemType,
  );
  const canCreate =
    props.canConfirm &&
    !busy &&
    previewEvidenceComplete &&
    !previewBlocked &&
    (!props.preview.rationaleRequired ||
      props.rationale.trim().length >=
        MIN_ANALYSIS_PARTITION_RATIONALE_LENGTH);
  const createdBy = recordOrEmpty(partition?.created_by);
  const createdByLabel = String(createdBy.display_name ?? createdBy.user_id ?? partition?.created_by ?? partition?.actor_user_id ?? "Unavailable");
  const developmentRows = optionalFiniteNumber(partition?.development_rows ?? partition?.development_count);
  const holdoutRows = optionalFiniteNumber(partition?.sealed_holdout_rows ?? partition?.holdout_rows ?? partition?.holdout_count);
  const evidenceId = String(partition?.evidence_id ?? partition?.evidence_ref ?? partition?.partition_evidence_id ?? "");
  const previewStatusLabel = String(props.preview.recommendationStatus ?? "pending").replace(/_/g, " ");
  const targetQuantiles = Object.entries(props.preview.targetQuantiles ?? {});
  const targetBandCoverage = recordOrEmpty(props.preview.targetBandCoverage);
  const extremeValueCoverage = recordOrEmpty(props.preview.extremeValueCoverage);
  const targetBandCoverageLabel =
    optionalFiniteNumber(targetBandCoverage.represented_bands) != null &&
    optionalFiniteNumber(targetBandCoverage.total_bands) != null
      ? `${Number(targetBandCoverage.represented_bands).toLocaleString()} of ${Number(targetBandCoverage.total_bands).toLocaleString()} bands (${formatPercent(targetBandCoverage.coverage_rate)})`
      : "Unavailable";
  const extremeCoverageAvailable =
    typeof extremeValueCoverage.low_extreme_represented === "boolean" &&
    typeof extremeValueCoverage.high_extreme_represented === "boolean";
  const extremeCoverageLabel = extremeCoverageAvailable
    ? [
        `Low extreme ${extremeValueCoverage.low_extreme_represented === true ? "represented" : "not represented"}`,
        `High extreme ${extremeValueCoverage.high_extreme_represented === true ? "represented" : "not represented"}`,
      ].join(" · ")
    : "Unavailable";
  const splitRatioLabel =
    optionalFiniteNumber(partition?.development_share) != null &&
    optionalFiniteNumber(partition?.holdout_share) != null
      ? `${Math.round(Number(partition?.development_share) * 100)}% development / ${Math.round(Number(partition?.holdout_share) * 100)}% final holdout`
      : "Split ratio unavailable";

  return (
    <section
      className="overflow-hidden rounded-xl border-2 border-indigo-400 bg-white shadow-[0_14px_34px_rgba(79,70,229,0.12)]"
      data-testid="analysis-partition-readiness"
      data-partition-phase={props.readiness.phase}
    >
      <div className="flex flex-wrap items-start justify-between gap-3 bg-gradient-to-r from-indigo-800 to-blue-700 px-5 py-4 text-white">
        <div>
          <div className="text-[10px] font-bold uppercase tracking-[0.18em] text-indigo-100">
            Required before EDA
          </div>
          <h2 className="mt-1 text-lg font-semibold">Reserve Development and Final Evaluation Populations</h2>
          <p className="mt-1 max-w-3xl text-xs leading-5 text-indigo-100">
            Assign every eligible observation to a modeling role before target-aware EDA can influence predictor selection, feature engineering, binning, transformations, tuning, candidate ranking, or threshold selection.
          </p>
        </div>
        <span className={`rounded-full border px-3 py-1 text-xs font-bold ${statusClass}`}>
          {current
            ? "Current · holdout sealed"
            : documentationPending
              ? props.readiness.phase === "documenting"
                ? "Completing documentation"
                : "Documentation pending"
              : busy
                ? "Checking"
                : "Confirmation required"}
        </span>
      </div>

      <div className="space-y-4 p-5">
        <div className="grid gap-3 lg:grid-cols-2">
          <div className="rounded-lg border border-blue-200 bg-blue-50 p-4 text-xs leading-5 text-blue-950">
            <div className="font-bold uppercase tracking-wide text-blue-700">Development population</div>
            <p className="mt-1">Used for EDA, preparation and feature decisions, cross-validation, tuning, and candidate ranking.</p>
          </div>
          <div className="rounded-lg border border-violet-200 bg-violet-50 p-4 text-xs leading-5 text-violet-950">
            <div className="font-bold uppercase tracking-wide text-violet-700">Sealed final holdout</div>
            <p className="mt-1">Opened only after the candidate is locked, to estimate unseen-observation performance using ROC-AUC, PR-AUC, KS, calibration, lift, gain, confusion-matrix and threshold-specific metrics, and business impact.</p>
          </div>
        </div>
        <p className="text-xs leading-5 text-slate-600">This partition does not change the eligible modeling population. It creates one durable role assignment for every eligible observation and prevents the final holdout from influencing development decisions.</p>

        <div className={`rounded-lg border px-4 py-3 text-sm ${statusClass}`} role={props.readiness.phase === "error" ? "alert" : "status"}>
          <div className="flex items-start gap-2">
            {current ? <ShieldCheck size={18} className="mt-0.5 shrink-0" aria-hidden="true" /> : <AlertTriangleIcon />}
            <div>
              <div className="font-semibold">{props.readiness.message}</div>
              {!current ? <p className="mt-1 text-xs leading-5">{props.readiness.recovery}</p> : null}
              {partition?.analysis_partition_id ? (
                <dl className="mt-2 grid gap-x-5 gap-y-1 text-xs sm:grid-cols-2 xl:grid-cols-4">
                  <div><dt className="font-semibold">Partition ID</dt><dd className="break-all font-mono">{partition.analysis_partition_id}</dd></div>
                   <div><dt className="font-semibold">Development partition</dt><dd className="break-all font-mono">{partition.development_partition_id ?? "Unavailable"}</dd></div>
                   <div><dt className="font-semibold">Final holdout partition</dt><dd className="break-all font-mono">{partition.sealed_holdout_partition_id ?? "Unavailable"}</dd></div>
                   <div><dt className="font-semibold">Revision</dt><dd>{partition.revision ?? "Unavailable"}</dd></div>
                </dl>
              ) : null}
            </div>
          </div>
        </div>

        <div className="space-y-4 rounded-lg border border-indigo-200 bg-indigo-50 p-4">
          {partitionPresent ? (
            <div
              className="space-y-3"
              data-testid={current ? "current-analysis-partition-summary" : "sealed-analysis-partition-summary"}
              data-documentation-readiness={current ? "current" : "documentation_pending"}
            >
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <div className={`text-[10px] font-bold uppercase tracking-wide ${current ? "text-emerald-700" : "text-amber-700"}`}>
                    {current ? "Analysis Partition Current" : "Sealed Partition · Documentation Pending"}
                  </div>
                  <div className="mt-1 text-sm font-semibold text-emerald-950">
                    {splitRatioLabel}
                  </div>
                </div>
                <div className="flex flex-wrap gap-2">
                  {documentationPending ? (
                    <button
                      type="button"
                      data-testid="complete-analysis-partition-documentation"
                      className="inline-flex items-center justify-center gap-2 rounded-lg bg-amber-700 px-4 py-2 text-xs font-semibold text-white shadow-sm hover:bg-amber-800 disabled:cursor-not-allowed disabled:opacity-55"
                      disabled={busy}
                      onClick={props.onCompleteDocumentation}
                    >
                      {props.readiness.phase === "documenting" ? (
                        <Loader2 size={15} className="animate-spin" aria-hidden="true" />
                      ) : (
                        <ShieldCheck size={15} aria-hidden="true" />
                      )}
                      Complete Partition Documentation
                    </button>
                  ) : null}
                  {evidenceId ? (
                    <Link to={`/model-evidence-center?evidenceId=${encodeURIComponent(evidenceId)}`} className="atlas-secondary-button text-xs">View Partition Evidence</Link>
                  ) : (
                    <span className="rounded-lg border border-slate-300 bg-slate-100 px-3 py-2 text-xs font-semibold text-slate-500" aria-disabled="true">Partition evidence unavailable</span>
                  )}
                </div>
              </div>
              {current ? (
                <div
                  className="flex flex-col gap-3 rounded-xl border-2 border-indigo-400 bg-white p-4 shadow-sm sm:flex-row sm:items-center sm:justify-between"
                  data-testid="current-analysis-partition-command-strip"
                >
                  <div>
                    <div className="text-xs font-bold uppercase tracking-wide text-indigo-700">
                      Current partition command
                    </div>
                    <p className="mt-1 text-sm font-semibold text-slate-950">
                      {splitRatioLabel} · revision {partition?.revision ?? "Unavailable"}
                    </p>
                    <p className="mt-1 text-xs leading-5 text-slate-600">
                      Review the current-versus-proposed impact before creating a replacement. The current revision remains unchanged until explicit confirmation.
                    </p>
                  </div>
                  <Link
                    to={`${projectWorkflowRoute(props.projectId, "/step01")}?analysisPartition=reset`}
                    className="inline-flex shrink-0 items-center justify-center rounded-lg bg-indigo-700 px-4 py-2.5 text-sm font-semibold text-white shadow-sm hover:bg-indigo-800"
                    data-testid="open-analysis-partition-reset"
                  >
                    Change Split Ratio — Creates New Revision
                  </Link>
                </div>
              ) : null}
              <dl className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
                <SummaryDatum label="Partition ID" value={partition?.analysis_partition_id ?? "Unavailable"} mono />
                <SummaryDatum label="Revision" value={partition?.revision ?? "Unavailable"} />
                <SummaryDatum label="Development rows" value={developmentRows == null ? "Unavailable" : developmentRows.toLocaleString()} />
                <SummaryDatum label="Final holdout rows" value={holdoutRows == null ? "Unavailable" : holdoutRows.toLocaleString()} />
                <SummaryDatum label="Partition method" value={partition?.partition_method ?? "Unavailable"} />
                <SummaryDatum label="Random seed" value={partition?.random_seed ?? "Unavailable"} />
                <SummaryDatum label="Stratification" value={partition?.stratification_policy === "target" ? `Target · ${partition?.stratification_field ?? "field unavailable"}` : partition?.stratification_policy ?? "Unavailable"} />
                <SummaryDatum label="Seal status" value={partition?.final_holdout_status ?? "Unavailable"} />
                <SummaryDatum label="Created by" value={createdByLabel} />
                <SummaryDatum label="Created at" value={partition?.created_at ?? "Unavailable"} />
                <SummaryDatum label="Evidence" value={evidenceId || partition?.evidence_status || "Unavailable"} mono={Boolean(evidenceId)} />
                <SummaryDatum label="MDD status" value={partition?.mdd_status ?? "Unavailable"} />
              </dl>
              {documentationPending ? (
                <div className="rounded-lg border border-amber-300 bg-amber-50 px-4 py-3 text-xs leading-5 text-amber-950" data-testid="analysis-partition-documentation-pending-note">
                  Evidence and MDD read-back must complete before EDA. This retry reuses the exact partition ID, revision, assignment hash, and artifact hash; it never redraws membership or opens the final holdout.
                </div>
              ) : null}
              <p className={`text-xs leading-5 ${current ? "text-emerald-800" : "text-amber-900"}`}>A split-ratio change requires impact review, rationale, optimistic concurrency validation, and a new durable revision.</p>
            </div>
          ) : (
            <div className="space-y-4">
            <label className="block text-xs font-semibold text-indigo-950">
              Development / Final Holdout Split
              <select
                data-testid="analysis-partition-holdout-ratio"
                className="mt-1 w-full rounded-lg border border-indigo-300 bg-white px-3 py-2.5 text-sm font-semibold text-slate-950"
                value={proposedPolicy.holdoutShare}
                disabled={busy || !props.canConfirm}
                onChange={(event) => props.onHoldoutShare(Number(event.target.value))}
              >
                {INITIAL_HOLDOUT_OPTIONS.map((holdoutShare) => (
                  <option key={holdoutShare} value={holdoutShare}>
                    {analysisPartitionOptionLabel(holdoutShare)}
                  </option>
                ))}
              </select>
            </label>
              <div className="grid gap-2 md:grid-cols-3" aria-label="Split option guidance">
                {INITIAL_HOLDOUT_OPTIONS.map((holdoutShare) => (
                  <div key={holdoutShare} className={`rounded-lg border p-3 text-left text-xs leading-5 ${holdoutShare === proposedPolicy.holdoutShare ? "border-indigo-500 bg-white ring-2 ring-indigo-200" : "border-indigo-200 bg-indigo-50/60"}`} aria-current={holdoutShare === proposedPolicy.holdoutShare ? "true" : undefined}>
                    <span className="block font-semibold text-indigo-950">{analysisPartitionOptionLabel(holdoutShare)}</span>
                    <span className="mt-1 block text-indigo-800">{analysisPartitionOptionGuidance(holdoutShare)}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
          {!partitionPresent ? (
            <div className="rounded-lg border border-indigo-200 bg-white p-4" data-testid="analysis-partition-preview">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="text-xs font-bold uppercase tracking-wide text-indigo-700">Backend preview</div>
                <span className={`rounded-full px-2.5 py-1 text-[11px] font-semibold ${previewBlocked ? "bg-red-100 text-red-800" : props.preview.phase === "ready" ? "bg-emerald-100 text-emerald-800" : "bg-slate-100 text-slate-700"}`}>
                  {props.preview.phase === "loading" ? "Calculating" : previewStatusLabel}
                </span>
              </div>
              {props.preview.phase === "ready" ? (
                <>
                  <dl className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
                    <SummaryDatum label="Eligible rows" value={props.preview.totalEligibleRows?.toLocaleString() ?? "Unavailable"} />
                    <SummaryDatum label="Development rows" value={props.preview.developmentRows?.toLocaleString() ?? "Unavailable"} />
                    <SummaryDatum label="Final holdout rows" value={props.preview.holdoutRows?.toLocaleString() ?? "Unavailable"} />
                    <SummaryDatum label="Method" value={props.preview.partitionMethod || "Unavailable"} />
                    <SummaryDatum label="Random seed" value={props.preview.randomSeed ?? "Unavailable"} />
                    <SummaryDatum label="Stratification" value={props.problemType === "regression" ? "Not stratified" : props.preview.stratificationField || "Unavailable"} />
                    <SummaryDatum label="Sufficiency" value={props.preview.sufficiency?.overall_status ?? "Unavailable"} />
                    <SummaryDatum label="Policy" value={[props.preview.sufficiency?.policy_id, props.preview.sufficiency?.policy_version].filter(Boolean).join(" ") || "Unavailable"} />
                  </dl>
                  {props.problemType === "classification" ? (
                    <dl className="mt-2 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
                      <SummaryDatum label="Development events" value={props.preview.developmentEventCount?.toLocaleString() ?? "Unavailable"} />
                      <SummaryDatum label="Development non-events" value={props.preview.developmentNonEventCount?.toLocaleString() ?? "Unavailable"} />
                      <SummaryDatum label="Holdout events" value={props.preview.holdoutEventCount?.toLocaleString() ?? "Unavailable"} />
                      <SummaryDatum label="Holdout non-events" value={props.preview.holdoutNonEventCount?.toLocaleString() ?? "Unavailable"} />
                      <SummaryDatum label="Development event rate" value={formatPercent(props.preview.developmentEventRate)} />
                      <SummaryDatum label="Holdout event rate" value={formatPercent(props.preview.holdoutEventRate)} />
                      <SummaryDatum label="Full-population event rate" value={formatPercent(props.preview.fullPopulationEventRate)} />
                      <SummaryDatum label="Absolute event-rate difference" value={formatPercent(props.preview.absoluteEventRateDifference)} />
                    </dl>
                  ) : (
                    <>
                      <dl className="mt-2 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
                        <SummaryDatum label="Target minimum" value={props.preview.targetMinimum ?? "Unavailable"} />
                        <SummaryDatum label="Target maximum" value={props.preview.targetMaximum ?? "Unavailable"} />
                        <SummaryDatum label="Target mean" value={props.preview.targetMean ?? "Unavailable"} />
                        <SummaryDatum label="Target standard deviation" value={props.preview.targetStandardDeviation ?? "Unavailable"} />
                        <SummaryDatum label="Target-band coverage" value={targetBandCoverageLabel} />
                        <SummaryDatum label="Extreme-value coverage" value={extremeCoverageLabel} />
                        {targetQuantiles.map(([quantile, value]) => (
                          <SummaryDatum key={quantile} label={`Target quantile ${quantile}`} value={value} />
                        ))}
                      </dl>
                    </>
                  )}
                  {props.preview.recommendationRationale ? <p className="mt-3 text-xs leading-5 text-slate-700">{props.preview.recommendationRationale}</p> : null}
                  <MessageList title="Warnings" items={props.preview.warnings} tone="amber" />
                  <MessageList title="Blockers" items={props.preview.blockers} tone="red" />
                </>
              ) : <p className="mt-2 text-xs leading-5 text-slate-600">{props.preview.message || "Select a ratio to calculate the governed preview."}</p>}
              {props.preview.rationaleRequired ? (
                <label className="mt-3 block text-xs font-semibold text-indigo-950">
                  Selection rationale required by policy
                  <textarea className="mt-1 min-h-24 w-full rounded-lg border border-indigo-300 bg-white px-3 py-2 text-sm font-normal text-slate-950" data-testid="analysis-partition-selection-rationale" value={props.rationale} minLength={MIN_ANALYSIS_PARTITION_RATIONALE_LENGTH} onChange={(event) => props.onRationale(event.target.value)} placeholder="Explain why this ratio is appropriate for the governed modeling objective." />
                  <span className="mt-1 block font-normal text-indigo-800">
                    Minimum {MIN_ANALYSIS_PARTITION_RATIONALE_LENGTH} characters, matching the backend policy.
                  </span>
                </label>
              ) : null}
            </div>
          ) : null}
          {!partitionPresent ? (
          <button
            type="button"
            data-testid="create-analysis-partition"
            className="inline-flex shrink-0 items-center justify-center gap-2 rounded-lg bg-indigo-700 px-4 py-2.5 text-sm font-semibold text-white shadow-sm hover:bg-indigo-800 disabled:cursor-not-allowed disabled:opacity-55"
            disabled={!canCreate}
            onClick={props.onConfirm}
          >
            {props.readiness.phase === "confirming" ? (
              <Loader2 size={16} className="animate-spin" aria-hidden="true" />
            ) : (
              <ShieldCheck size={16} aria-hidden="true" />
            )}
            Create &amp; Seal Analysis Partition
          </button>
          ) : null}
        </div>
      </div>
    </section>
  );
}

function SummaryDatum(props: { label: string; value: unknown; mono?: boolean }) {
  return (
    <div className="rounded-md border border-slate-200 bg-white px-3 py-2 text-xs">
      <dt className="font-semibold text-slate-500">{props.label}</dt>
      <dd className={`mt-1 break-all font-semibold text-slate-900 ${props.mono ? "font-mono" : ""}`}>{String(props.value ?? "Unavailable")}</dd>
    </div>
  );
}

function MessageList(props: { title: string; items: string[]; tone: "amber" | "red" }) {
  if (!props.items.length) return null;
  const toneClass = props.tone === "red" ? "border-red-200 bg-red-50 text-red-900" : "border-amber-200 bg-amber-50 text-amber-900";
  return (
    <div className={`mt-3 rounded-md border px-3 py-2 text-xs ${toneClass}`}>
      <div className="font-semibold">{props.title}</div>
      <ul className="mt-1 list-disc space-y-1 pl-4">{props.items.map((item) => <li key={item}>{item}</li>)}</ul>
    </div>
  );
}

function AlertTriangleIcon() {
  return (
    <span className="mt-0.5 inline-flex h-[18px] w-[18px] shrink-0 items-center justify-center rounded-full border border-current text-[11px] font-bold" aria-hidden="true">
      !
    </span>
  );
}

function DataContractStatusChips(props: {
  registered: boolean;
  linked: boolean;
  loaded: boolean;
  targetConfirmed: boolean;
  predictorAuthorizationCurrent: boolean;
  partitionCurrent: boolean;
}) {
  const items = [
    ["Registered", props.registered],
    ["Linked", props.linked],
    ["Version loaded", props.loaded],
    ["Target confirmed", props.targetConfirmed],
    ["Predictor authorization", props.predictorAuthorizationCurrent],
    ["Partition current", props.partitionCurrent],
  ] as const;
  return (
    <div className="grid min-w-[190px] gap-1.5" aria-label="Data Contract status" data-testid="data-contract-status-chips">
      {items.map(([label, complete]) => (
        <span
          key={label}
          className={`inline-flex items-center gap-2 rounded-full border px-2.5 py-1 text-[10px] font-semibold ${
            complete
              ? "border-emerald-300/60 bg-emerald-300/15 text-emerald-50"
              : "border-amber-300/60 bg-amber-300/15 text-amber-50"
          }`}
          data-contract-status={complete ? "current" : "pending"}
        >
          {complete ? <Check size={12} aria-hidden="true" /> : <span className="h-2 w-2 rounded-full bg-current" aria-hidden="true" />}
          {label}
        </span>
      ))}
    </div>
  );
}

function ScopeDatum({
  label,
  value,
  tone,
}: {
  label: string;
  value: number | null;
  tone: "slate" | "blue" | "indigo" | "violet";
}) {
  const toneClass = {
    slate: "text-slate-950",
    blue: "text-blue-950",
    indigo: "text-indigo-950",
    violet: "text-violet-950",
  } as const;
  return (
    <div className="bg-white px-4 py-3">
      <div className="text-[10px] font-semibold uppercase tracking-wide text-slate-500">{label}</div>
      <div className={`mt-1 text-sm font-bold tabular-nums ${toneClass[tone]}`}>
        {value == null ? "Pending" : `${value.toLocaleString()} rows`}
      </div>
    </div>
  );
}

function formatGovernedSourceType(value: string) {
  const normalized = String(value || "").trim();
  if (!normalized) return "Registered dataset";
  return normalized
    .replaceAll("_", " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function PredictorAuthorizationFunnel({
  authorization,
  contextPhase,
  contextError,
  evaluatedCount,
  unavailable,
}: {
  authorization: ReproducibilityPredictorAuthorization | null;
  contextPhase: "idle" | "loading" | "pending" | "ready" | "error";
  contextError: string;
  evaluatedCount: number | null;
  unavailable: Array<{ predictor: string; reason: string }>;
}) {
  if (!authorization) {
    const message =
      contextPhase === "error"
        ? contextError || "ATLAS could not verify the predictor authorization."
        : contextPhase === "loading"
          ? "Verifying the exact backend predictor authorization..."
          : "Confirm the exact dataset version, target mapping, and predictor selection to publish this funnel.";
    return (
      <div
        className={`mt-4 rounded-xl border px-4 py-3 text-sm ${
          contextPhase === "error"
            ? "border-rose-300 bg-rose-50 text-rose-950"
            : "border-amber-300 bg-amber-50 text-amber-950"
        }`}
        data-testid="predictor-authorization-funnel-pending"
        role={contextPhase === "error" ? "alert" : "status"}
      >
        <div className="font-semibold">Backend-authoritative funnel pending</div>
        <p className="mt-1 text-xs leading-5">{message}</p>
      </div>
    );
  }

  const { funnel } = authorization;
  const stages = [
    {
      label: "Source columns",
      value: funnel.source_column_count.toLocaleString(),
      note: "Exact registered schema",
      testId: "funnel-source-columns",
    },
    {
      label: "Candidate predictors",
      value: funnel.candidate_predictor_count.toLocaleString(),
      note: "After target exclusion",
      testId: "funnel-candidate-predictors",
    },
    {
      label: "Analyst-selected",
      value: funnel.selected_predictor_count.toLocaleString(),
      note: "Submitted to authorization",
      testId: "funnel-selected-predictors",
    },
    {
      label: "Authorized predictors",
      value: funnel.authorized_predictor_count.toLocaleString(),
      note: "Current governed contract",
      testId: "funnel-authorized-predictors",
    },
    {
      label: "Analytically evaluated",
      value: evaluatedCount == null ? "Pending" : evaluatedCount.toLocaleString(),
      note: "Development-population evidence",
      testId: "funnel-evaluated-predictors",
    },
    {
      label: "Model-ready predictors",
      value: "Not established here",
      note: "Established by training preflight",
      testId: "funnel-model-ready-predictors",
    },
  ];
  const deterministic = authorization.deterministic_source_exclusions;
  const additional = Object.entries(funnel.additional_exclusions);

  return (
    <div
      className="mt-4 rounded-xl border border-blue-200 bg-blue-50/60 p-4"
      data-testid="predictor-authorization-funnel"
      data-predictor-authorization-id={authorization.predictor_authorization_id}
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="text-xs font-bold uppercase tracking-wide text-blue-800">
            Backend-authoritative Predictor Authorization Funnel
          </div>
          <p className="mt-1 text-xs leading-5 text-slate-600">
            Every count has a named scope. Browser selections cannot replace this exact governed contract.
          </p>
        </div>
        <span className="rounded-full border border-blue-300 bg-white px-2.5 py-1 font-mono text-[10px] text-blue-950">
          {authorization.predictor_authorization_id}
        </span>
      </div>
      <div className="mt-3 grid gap-2 sm:grid-cols-2 xl:grid-cols-6">
        {stages.map((stage, index) => (
          <div key={stage.label} className="relative rounded-lg border border-slate-200 bg-white px-3 py-2.5">
            {index > 0 ? (
              <span className="absolute -left-2 top-1/2 hidden -translate-y-1/2 text-slate-400 xl:block" aria-hidden="true">
                →
              </span>
            ) : null}
            <div className="text-[10px] font-semibold uppercase tracking-wide text-slate-500">{stage.label}</div>
            <div className="mt-1 text-base font-bold text-slate-950" data-testid={stage.testId}>{stage.value}</div>
            <div className="mt-0.5 text-[10px] leading-4 text-slate-600">{stage.note}</div>
          </div>
        ))}
      </div>

      <div className="mt-3 grid gap-2 lg:grid-cols-3">
        <div className="rounded-lg border border-slate-200 bg-white px-3 py-2.5" data-testid="funnel-target-exclusions">
          <div className="text-[10px] font-bold uppercase tracking-wide text-slate-500">Target exclusion</div>
          {funnel.target_exclusions.length ? funnel.target_exclusions.map((item) => (
            <div key={item.field} className="mt-1 text-xs text-slate-800">
              <span className="font-mono font-semibold">{item.field}</span>: {item.reason}
            </div>
          )) : <div className="mt-1 text-xs text-amber-800">Exact target exclusion pending.</div>}
        </div>
        <div className="rounded-lg border border-violet-200 bg-white px-3 py-2.5" data-testid="funnel-deterministic-exclusions">
          <div className="text-[10px] font-bold uppercase tracking-wide text-violet-700">Deterministic-source exclusions</div>
          {deterministic.length ? deterministic.map((field) => (
            <div key={field} className="mt-1 text-xs text-slate-800">
              <span className="font-mono font-semibold">{field}</span>: {authorization.excluded_fields[field] || "Deterministic source of the modeling target"}
            </div>
          )) : (
            <div className="mt-1 text-xs text-slate-600">
              None in the current contract · scope {authorization.target_source_detection_scope || "not reported"}
            </div>
          )}
        </div>
        <div className="rounded-lg border border-slate-200 bg-white px-3 py-2.5">
          <div className="text-[10px] font-bold uppercase tracking-wide text-slate-500">Remaining differences</div>
          <div className="mt-1 text-xs text-slate-700">
            {additional.length.toLocaleString()} additional authorization exclusion{additional.length === 1 ? "" : "s"} · {unavailable.length.toLocaleString()} analytically unavailable
          </div>
          {additional.length || unavailable.length ? (
            <details className="mt-1 text-xs text-slate-700">
              <summary className="cursor-pointer font-semibold text-blue-800">View exact fields and reasons</summary>
              <ul className="mt-1 list-disc space-y-1 pl-4">
                {additional.map(([field, reason]) => <li key={`excluded-${field}`}><span className="font-mono">{field}</span>: {reason}</li>)}
                {unavailable.map((item) => <li key={`unavailable-${item.predictor}`}><span className="font-mono">{item.predictor}</span>: {item.reason}</li>)}
              </ul>
            </details>
          ) : <div className="mt-1 text-xs text-emerald-700">No unexplained difference remains.</div>}
        </div>
      </div>
    </div>
  );
}

function UploadPanel({ fileName, onFile }: { fileName: string; onFile: (file: File) => void }) {
  return (
    <div>
      <h2 className="text-base font-semibold text-slate-950">Upload File</h2>
      <p className="mt-1 text-sm text-slate-500">Supported source types: CSV, Excel, Parquet, Feather, JSON, SAS datasets, and ZIP. CSV and JSON parse locally today.</p>
      <div className="mt-4 flex flex-wrap items-center gap-3">
        <label className="cursor-pointer rounded-lg bg-slate-950 px-4 py-2 text-sm font-semibold text-white">
          Choose File
          <input className="hidden" type="file" accept=".csv,.txt,.json,.xlsx,.xls,.parquet,.feather,.sas7bdat,.zip" onChange={(event) => event.target.files?.[0] && onFile(event.target.files[0])} />
        </label>
        <span className="text-sm text-slate-600">{fileName || "No file selected"}</span>
      </div>
    </div>
  );
}

function DatasetPersistenceCard(props: {
  projectName: string;
  target: string;
  rowCount: number;
  columnCount: number;
  choice: "workspace" | "register";
  onChoice: (choice: "workspace" | "register") => void;
  registerName: string;
  onRegisterNameChange: (value: string) => void;
  registerDescription: string;
  onRegisterDescriptionChange: (value: string) => void;
  registerTags: string;
  onRegisterTagsChange: (value: string) => void;
  registering: boolean;
  registrationResult: DatasetSummary | null;
  registrationError: string;
  duplicateCandidates: DatasetSummary[];
  checkingDuplicates: boolean;
  onRegister: () => void;
  /** Part C: which persistence UI applies for the current source state. */
  persistenceMode: PersistenceMode;
  sourceKindLabel: string;
  registrationActionLabel: string;
  libraryLink: DatasetLibraryLink | null;
  assetOwner?: string;
}) {
  // UX-DATAACQ-004 / Part C1: data that is already a registered governed asset gets
  // a read-only status panel. Offering "Project Workspace Only" vs "Register in
  // Dataset Library" here implied a duplicate-registration or overwrite risk that
  // does not exist, and invited the analyst to re-register their own source.
  if (props.persistenceMode === "registered-status") {
    return (
      <details
        className="mt-5 rounded-xl border border-emerald-300 bg-emerald-50/70"
        data-testid="dataset-persistence-card"
        data-persistence-mode="registered-status"
      >
        <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-4 py-3 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-600">
          <span className="flex min-w-0 items-center gap-2 text-sm font-semibold text-emerald-950">
            <ShieldCheck size={16} aria-hidden="true" />
            Registered and linked to this project
          </span>
          <span className="text-xs font-semibold text-emerald-800">View dataset provenance</span>
        </summary>
        <div className="border-t border-emerald-200 bg-white p-4">
          <dl className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
            <SummaryDatum label="Dataset ID" value={props.libraryLink?.datasetId ?? "Unavailable"} mono />
            <SummaryDatum label="Version ID" value={props.libraryLink?.versionId ?? "Unavailable"} mono />
            <SummaryDatum label="Owner" value={props.assetOwner || "Unavailable"} />
            <SummaryDatum label="Source type" value={props.sourceKindLabel} />
            <SummaryDatum label="Registration" value="Dataset Library" />
            <SummaryDatum label="Project link" value="Current" />
          </dl>
          <p className="mt-3 text-xs leading-5 text-slate-600">
            The immutable source version remains in Dataset Library if this project is deleted. ATLAS does not offer duplicate registration for an already governed asset.
          </p>
          {props.libraryLink?.datasetId ? (
            <Link
              className="mt-3 inline-flex rounded-lg border border-emerald-300 bg-white px-3 py-2 text-xs font-semibold text-emerald-900"
              to={`/datasets/${props.libraryLink.datasetId}`}
            >
              Open in Dataset Library
            </Link>
          ) : null}
        </div>
      </details>
    );
  }

  const isDerived = props.persistenceMode === "derived-choice";
  return (
    <section className="mt-5 rounded-xl border border-slate-200 bg-white p-5 shadow-sm" data-testid="dataset-persistence-card" data-persistence-mode={props.persistenceMode}>
      <h2 className="text-base font-semibold text-slate-950">Dataset Persistence</h2>
      <p className="mt-1 text-sm text-slate-500">
        Choose how ATLAS should store this dataset. Status: <span className="font-semibold text-slate-800" data-testid="persistence-source-label">{props.sourceKindLabel}</span>
      </p>
      {isDerived && (
        <p className="mt-3 rounded-lg border border-blue-200 bg-blue-50 px-3 py-2 text-xs leading-5 text-blue-900" data-testid="derived-dataset-notice">
          This is a {props.sourceKindLabel.toLowerCase()}. Registering it creates a new governed record; it never modifies or
          overwrites the immutable source version it was derived from.
        </p>
      )}
      <div className="mt-4 grid gap-3 md:grid-cols-2">
        <button
          type="button"
          onClick={() => props.onChoice("workspace")}
          aria-pressed={props.choice === "workspace"}
          className={`rounded-xl border p-4 text-left shadow-sm transition ${props.choice === "workspace" ? "border-slate-950 bg-slate-950 text-white" : "border-slate-200 bg-white hover:bg-slate-50"}`}
        >
          <div className={`text-sm font-semibold ${props.choice === "workspace" ? "text-white" : "text-slate-950"}`}>Project Workspace Only</div>
          <p className={`mt-2 text-xs leading-5 ${props.choice === "workspace" ? "text-slate-200" : "text-slate-500"}`}>
            Use this dataset only in the current project. It will not appear in the Dataset Library unless you register it later. Deleting this project deletes this workspace copy.
          </p>
        </button>
        <button
          type="button"
          onClick={() => props.onChoice("register")}
          aria-pressed={props.choice === "register"}
          className={`rounded-xl border p-4 text-left shadow-sm transition ${props.choice === "register" ? "border-slate-950 bg-slate-950 text-white" : "border-slate-200 bg-white hover:bg-slate-50"}`}
        >
          <div className={`text-sm font-semibold ${props.choice === "register" ? "text-white" : "text-slate-950"}`}>Register in Dataset Library</div>
          <p className={`mt-2 text-xs leading-5 ${props.choice === "register" ? "text-slate-200" : "text-slate-500"}`}>
            Create a governed, versioned data asset that authorized projects can reuse. If this project is later deleted, the registered asset and its Library link to other projects remain.
          </p>
        </button>
      </div>

      {props.choice === "register" && !props.registrationResult && (
        <div className="mt-5 space-y-3 rounded-lg border border-blue-100 bg-blue-50/60 p-4">
          <div className="grid gap-3 md:grid-cols-2">
            <label className="grid gap-1 text-xs font-semibold text-slate-700">
              Dataset Library name
              <input
                className="atlas-input"
                value={props.registerName}
                placeholder={`${props.projectName || "ATLAS Project"} - Development Dataset`}
                onChange={(event) => props.onRegisterNameChange(event.target.value)}
              />
            </label>
            <label className="grid gap-1 text-xs font-semibold text-slate-700">
              Tags (comma-separated)
              <input className="atlas-input" value={props.registerTags} onChange={(event) => props.onRegisterTagsChange(event.target.value)} placeholder="development, governed" />
            </label>
          </div>
          <label className="grid gap-1 text-xs font-semibold text-slate-700">
            Description / business purpose
            <textarea className="atlas-input" rows={2} value={props.registerDescription} onChange={(event) => props.onRegisterDescriptionChange(event.target.value)} placeholder="What this dataset is and how it should be used." />
          </label>
          <div className="text-xs text-slate-500">Target <strong>{props.target}</strong>, {props.rowCount.toLocaleString()} rows, {props.columnCount} columns, and the current project owner will be recorded automatically.</div>

          {props.checkingDuplicates && <div className="text-xs text-slate-500">Checking for similar existing assets...</div>}
          {!props.checkingDuplicates && props.duplicateCandidates.length > 0 && (
            <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs text-amber-950" data-testid="duplicate-suggestions">
              <div className="font-semibold">Possibly similar assets already exist. Review before registering a new one:</div>
              <ul className="mt-2 space-y-1">
                {props.duplicateCandidates.map((candidate) => (
                  <li key={candidate.datasetId}>
                    <Link className="underline" to={`/datasets/${candidate.datasetId}`} target="_blank" rel="noreferrer">
                      {candidate.name}
                    </Link>{" "}
                    ({candidate.latestVersion?.rowCount?.toLocaleString() ?? "-"} rows, owner {candidate.ownerDisplayName ?? candidate.ownerUserId})
                  </li>
                ))}
              </ul>
              <div className="mt-2">This is a suggestion only -- registering below always creates your own new asset.</div>
            </div>
          )}

          {props.registrationError && <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-xs text-red-900">{props.registrationError}</div>}

          <button type="button" onClick={props.onRegister} disabled={props.registering} data-testid="register-dataset-action" className="rounded-lg bg-blue-700 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-blue-800 disabled:opacity-60">
            {props.registering ? "Registering..." : props.registrationActionLabel}
          </button>
        </div>
      )}

      {props.registrationResult && (
        <div className="mt-5 rounded-lg border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-950" data-testid="registration-success">
          <div className="font-semibold">Registered to the Dataset Library</div>
          <div className="mt-2 grid gap-1 text-xs">
            <div>Asset ID: <span className="font-mono">{props.registrationResult.datasetId}</span></div>
            <div>Version ID: <span className="font-mono">{props.registrationResult.latestVersion?.versionId ?? "-"}</span></div>
            <div>This project is now linked to this asset.</div>
          </div>
          <Link className="mt-3 inline-block rounded-lg border border-emerald-300 bg-white px-3 py-2 text-xs font-semibold text-emerald-900" to={`/datasets/${props.registrationResult.datasetId}`}>
            Open in Dataset Library
          </Link>
        </div>
      )}
    </section>
  );
}

function TargetSetup(props: {
  headers: string[];
  target: string;
  setTarget: (value: string) => void;
  eventValue: unknown;
  setEventValue: (value: unknown) => void;
  nonEventValue: unknown;
  setNonEventValue: (value: unknown) => void;
  problemType: "classification" | "regression";
}) {
  const targetConfirmed = Boolean(props.target);
  return (
    <section
      id="data-acquisition-target-setup"
      className="overflow-hidden rounded-xl border-2 border-blue-500 bg-gradient-to-br from-blue-50 via-white to-cyan-50 shadow-[0_14px_34px_rgba(37,99,235,0.16)]"
      data-testid="data-acquisition-target-setup"
      role="region"
      aria-labelledby="data-acquisition-target-heading"
    >
      <div className="flex flex-wrap items-center justify-between gap-3 bg-gradient-to-r from-blue-700 to-cyan-700 px-5 py-3 text-white">
        <div className="flex items-center gap-3">
          <span className="flex h-8 w-8 items-center justify-center rounded-full bg-white text-sm font-black text-blue-700">
            2
          </span>
          <div>
            <div className="text-[10px] font-bold uppercase tracking-[0.18em] text-blue-100">
              Required modeling decision
            </div>
            <h2 id="data-acquisition-target-heading" className="text-base font-semibold">Identify the Target Variable</h2>
          </div>
        </div>
        <span
          role="status"
          aria-live="polite"
          className={`rounded-full border px-3 py-1 text-xs font-bold ${
            targetConfirmed
              ? "border-emerald-200 bg-emerald-50 text-emerald-800"
              : "border-amber-200 bg-amber-50 text-amber-900"
          }`}
        >
          {targetConfirmed ? `Target confirmed: ${props.target}` : "Target required"}
        </span>
      </div>
      <div className="p-5">
      <p className="text-sm leading-6 text-slate-700">
        Select the outcome ATLAS must predict. This choice becomes the
        authoritative target for EDA, predictor exclusion, feature engineering,
        validation, and modeling.
      </p>
      <div
        className="mt-4 rounded-xl border-2 border-blue-600 bg-white p-4 shadow-[0_8px_24px_rgba(37,99,235,0.18)] ring-4 ring-blue-100"
        data-testid="target-column-priority-control"
      >
        <div className="flex flex-wrap items-center justify-between gap-2">
          <label
            htmlFor="data-acquisition-target-column"
            className="text-sm font-black uppercase tracking-[0.14em] text-blue-950"
          >
            Target Column
          </label>
          <span className="rounded-full bg-amber-100 px-2.5 py-1 text-[11px] font-extrabold uppercase tracking-wide text-amber-950">
            Required
          </span>
        </div>
        <p id="data-acquisition-target-help" className="mt-1 text-xs leading-5 text-slate-600">
          Choose the outcome to predict. Your loaded dataset stays selected while this draft target contract is reviewed.
        </p>
        <select
          id="data-acquisition-target-column"
          data-testid="target-column-select"
          className="mt-3 min-h-12 w-full rounded-xl border-2 border-blue-600 bg-white px-4 py-3 text-base font-bold text-slate-950 shadow-sm outline-none transition focus:border-blue-800 focus:ring-4 focus:ring-blue-200"
          value={props.target}
          onChange={(event) => props.setTarget(event.target.value)}
          required
          aria-required="true"
          aria-describedby="data-acquisition-target-help"
        >
          <option value="" disabled>Select a target column</option>
          {props.headers.filter(Boolean).map((header) => (
            <option key={header} value={header}>{header}</option>
          ))}
        </select>
      </div>
      <div className="mt-4 grid gap-3 md:grid-cols-2">
        {props.problemType === "classification" ? (
          <>
            <Input label="Event / Positive Value" value={String(props.eventValue ?? "")} onChange={props.setEventValue} />
            <Input label="Non-event / Negative Value" value={String(props.nonEventValue ?? "")} onChange={props.setNonEventValue} />
          </>
        ) : (
          <ReadOnlyField label="Target behavior" value="Continuous regression target" />
        )}
      </div>
      <p className="mt-4 rounded-lg border border-blue-200 bg-blue-50 px-3 py-2 text-xs leading-5 text-blue-950">
        ATLAS will exclude <strong>{props.target || "the selected target"}</strong>{" "}
        and any deterministic target-source fields from the predictor set.
      </p>
      </div>
    </section>
  );
}

function PreviewProfilingSettings(props: {
  headers: string[];
  method: SamplingMethod;
  setMethod: (value: SamplingMethod) => void;
  previewRowLimit: number;
  setPreviewRowLimit: (value: number) => void;
  profileRowLimit: number;
  setProfileRowLimit: (value: number) => void;
  randomSeed: number;
  setRandomSeed: (value: number) => void;
  stratificationColumn: string;
  setStratificationColumn: (value: string) => void;
  timeColumn: string;
  setTimeColumn: (value: string) => void;
  registeredRowCount: number;
  previewRowCount: number;
  profileRowCount: number;
  browserDataComplete: boolean;
}) {
  const stratifiedDisabled = !props.browserDataComplete || !props.headers.length;
  const timeDisabled = !props.browserDataComplete || !props.headers.some((header) => /date|time|timestamp/i.test(header));
  return (
    <details className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
      <summary className="cursor-pointer text-base font-semibold text-slate-950">Preview & Profiling Settings</summary>
      <div className="mt-4 grid gap-3 md:grid-cols-3">
        <label className="grid gap-1 text-xs font-semibold text-slate-700">
          Preview method
          <select className="atlas-input" value={props.method} onChange={(event) => props.setMethod(event.target.value as SamplingMethod)}>
            <option value="top_n">First rows</option>
            <option value="random">Random sample</option>
            <option value="stratified" disabled={stratifiedDisabled}>Stratified preview</option>
            <option value="time_based" disabled={timeDisabled}>Time-ordered preview</option>
            <option value="full" disabled={!props.browserDataComplete}>Use all available browser rows</option>
          </select>
        </label>
        <NumberInput label="Preview row limit" value={props.previewRowLimit} onChange={props.setPreviewRowLimit} />
        <NumberInput label="Profile row limit" value={props.profileRowLimit} onChange={props.setProfileRowLimit} />
        {props.method === "random" && <NumberInput label="Random seed" value={props.randomSeed} onChange={props.setRandomSeed} />}
        {props.method === "stratified" && <Select label="Stratification variable" value={props.stratificationColumn} onChange={props.setStratificationColumn} options={props.headers} />}
        {props.method === "time_based" && <Select label="Time field" value={props.timeColumn} onChange={props.setTimeColumn} options={props.headers.filter((header) => /date|time|timestamp/i.test(header))} />}
      </div>
      {(stratifiedDisabled || timeDisabled) && (
        <p className="mt-3 text-xs text-amber-800">Stratified and time-ordered previews are enabled only when the complete browser dataset and the required fields are available.</p>
      )}
      <div className="mt-4 grid gap-3 sm:grid-cols-3">
        <ReadOnlyField label="Current modeling row count" value={props.registeredRowCount.toLocaleString()} />
        <ReadOnlyField label="Current preview row count" value={props.previewRowCount.toLocaleString()} />
        <ReadOnlyField label="Current profile row count" value={props.profileRowCount.toLocaleString()} />
      </div>
      <p className="mt-3 text-sm font-semibold text-emerald-800">Preview and profiling settings do not change the registered modeling dataset.</p>
    </details>
  );
}

function NumberInput({ label, value, onChange }: { label: string; value: number; onChange: (value: number) => void }) {
  return (
    <label className="grid gap-1 text-xs font-semibold text-slate-700">
      {label}
      <input className="atlas-input" type="number" min={1} value={value} onChange={(event) => onChange(Math.max(1, Number(event.target.value) || 1))} />
    </label>
  );
}

function ReadOnlyField({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2">
      <div className="text-[10px] font-semibold uppercase tracking-wide text-slate-500">{label}</div>
      <div className="mt-1 text-sm font-semibold text-slate-950">{value}</div>
    </div>
  );
}

function SqlPanel(props: {
  provider: string;
  setProvider: (value: string) => void;
  connectionName: string;
  setConnectionName: (value: string) => void;
  database: string;
  setDatabase: (value: string) => void;
  schema: string;
  setSchema: (value: string) => void;
  sql: string;
  setSql: (value: string) => void;
  warnings: string[];
  savedQueries: string[];
  favoriteQueries: string[];
  onTemplate: (sql: string) => void;
  onSave: () => void;
  onFavorite: () => void;
  onSaveMetadata: () => void;
}) {
  return (
    <div className="grid gap-4 xl:grid-cols-[280px_minmax(0,1fr)]">
      <aside className="rounded-lg border border-slate-200 bg-slate-50 p-3">
        <h2 className="text-sm font-semibold text-slate-950">Database Explorer</h2>
        <div className="mt-3 space-y-2 text-sm text-slate-700">
          <div className="font-medium">{props.provider}</div>
          <div className="pl-3">Connection: {props.connectionName}</div>
          <div className="pl-3">Schemas</div>
          <div className="pl-6">CUSTOMER_BASE</div>
          <div className="pl-8 text-xs text-slate-500">customer_id PK, open_date, status</div>
          <div className="pl-6">TRANSACTION_HISTORY</div>
          <div className="pl-8 text-xs text-slate-500">customer_id FK, amount, txn_date</div>
          <div className="pl-6">BUREAU_ATTRIBUTES</div>
          <div className="pl-8 text-xs text-slate-500">fico_score, trades, inquiries</div>
        </div>
      </aside>
      <div>
        <div className="grid gap-3 md:grid-cols-4">
          <Select label="Provider" value={props.provider} onChange={props.setProvider} options={databaseProviders} />
          <Input label="Connection Name" value={props.connectionName} onChange={props.setConnectionName} />
          <Input label="Database" value={props.database} onChange={props.setDatabase} />
          <Input label="Schema" value={props.schema} onChange={props.setSchema} />
        </div>
        <div className="mt-4 flex flex-wrap gap-2">
          {queryTemplates().map((template) => (
            <button key={template.name} className="rounded-full border border-slate-300 bg-white px-3 py-1 text-xs font-medium" onClick={() => props.onTemplate(template.sql)}>
              {template.name}
            </button>
          ))}
        </div>
        <textarea
          className="mt-4 min-h-[260px] w-full rounded-lg border border-slate-300 bg-slate-950 p-4 font-mono text-sm text-emerald-100"
          value={props.sql}
          onChange={(event) => props.setSql(event.target.value)}
          spellCheck={false}
        />
        <div className="mt-3 flex flex-wrap gap-2">
          <button className="rounded-lg border px-3 py-2 text-sm" onClick={props.onSave}>Save Query</button>
          <button className="rounded-lg border px-3 py-2 text-sm" onClick={props.onFavorite}>Favorite</button>
          <button className="rounded-lg bg-slate-950 px-3 py-2 text-sm font-semibold text-white" onClick={props.onSaveMetadata}>Validate & Save Query Metadata</button>
        </div>
        {!!props.warnings.length && (
          <div className="mt-3 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">
            <div className="font-semibold">Query validation</div>
            <ul className="mt-1 list-disc pl-5">{props.warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul>
          </div>
        )}
        <div className="mt-3 grid gap-3 md:grid-cols-2">
          <QueryList title="Saved Queries" queries={props.savedQueries} />
          <QueryList title="Favorites" queries={props.favoriteQueries} />
        </div>
      </div>
    </div>
  );
}

function CloudPanel({ cloudProvider, setCloudProvider, cloudPath, setCloudPath }: { cloudProvider: string; setCloudProvider: (value: string) => void; cloudPath: string; setCloudPath: (value: string) => void }) {
  return (
    <div>
      <h2 className="text-base font-semibold text-slate-950">Cloud Storage</h2>
      <p className="mt-1 text-sm text-slate-500">Capture cloud data source metadata now. Actual object reads should be handled by backend connectors with governed credentials.</p>
      <div className="mt-4 grid gap-3 md:grid-cols-[240px_minmax(0,1fr)]">
        <Select label="Cloud Provider" value={cloudProvider} onChange={setCloudProvider} options={cloudProviders} />
        <Input label="Path / URL" value={cloudPath} onChange={setCloudPath} placeholder="s3://bucket/path/train.parquet" />
      </div>
    </div>
  );
}

function ExistingDatasetPanel({
  versions,
  libraryDatasets,
  libraryVersions,
  selectedDatasetId,
  selectedVersionId,
  loading,
  loadProgress,
  isLoaded,
  onDatasetChange,
  onVersionChange,
  onRefresh,
  onLoad,
}: {
  versions: ReturnType<typeof loadDatasetVersions>;
  libraryDatasets: DatasetSummary[];
  libraryVersions: DatasetVersionSummary[];
  selectedDatasetId: string;
  selectedVersionId: string;
  loading: boolean;
  loadProgress: DatasetLoadProgress;
  isLoaded: boolean;
  onDatasetChange: (datasetId: string) => void;
  onVersionChange: (versionId: string) => void;
  onRefresh: () => void;
  onLoad: () => void;
}) {
  const selectedDataset = libraryDatasets.find((dataset) => dataset.datasetId === selectedDatasetId);
  const isLoading = loadProgress.phase === "loading";
  const failed = loadProgress.phase === "failed";
  // Part A/5: a successful load only counts for the selection that produced it.
  const showLoaded = isLoaded && loadProgress.phase === "loaded";
  const canLoad = Boolean(selectedDatasetId && selectedVersionId) && !isLoading;

  const buttonLabel = isLoading
    ? "Loading Selected Version..."
    : showLoaded
      ? "Version Loaded"
      : failed
        ? "Retry Load"
        : "Load Selected Version";
  const buttonClass = isLoading
    ? "border-blue-300 bg-blue-100 text-blue-800"
    : showLoaded
      ? "border-emerald-600 bg-emerald-600 text-white hover:bg-emerald-700"
      : "border-blue-700 bg-blue-700 text-white hover:bg-blue-800";

  return (
    <div>
      <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <h2 className="text-base font-semibold text-slate-950">Existing Dataset Library Asset</h2>
          <p className="mt-1 text-sm text-slate-500">
            Load one governed Dataset Library version. ATLAS authorizes the project link and commits the exact active version as one durable operation.
          </p>
        </div>
        <button type="button" onClick={onRefresh} className="rounded-lg border border-slate-300 px-3 py-2 text-sm font-semibold text-slate-700">
          {loading ? "Refreshing..." : "Refresh Library"}
        </button>
      </div>

      {/* UX-DATAACQ-001: the load action is a primary command directly beneath its
          own selectors, not a weak control at the far-right edge of the row. */}
      <div className="mt-4 rounded-xl border-2 border-blue-300 bg-blue-50 p-4" data-testid="dataset-load-command">
        <div className="grid gap-3 md:grid-cols-2">
          <Select
            label="Dataset"
            value={selectedDatasetId}
            onChange={onDatasetChange}
            options={libraryDatasets.map((dataset) => dataset.datasetId)}
            optionLabels={Object.fromEntries(libraryDatasets.map((dataset) => [dataset.datasetId, `${dataset.name} (${dataset.latestVersion?.rowCount?.toLocaleString() ?? 0} rows)`]))}
          />
          <Select
            label="Version"
            value={selectedVersionId}
            onChange={onVersionChange}
            options={libraryVersions.map((version) => version.versionId)}
          />
        </div>
        <div className="mt-4 flex flex-wrap items-center gap-3">
          <button
            type="button"
            onClick={onLoad}
            disabled={!canLoad}
            aria-busy={isLoading}
            data-testid="load-selected-version"
            data-load-state={isLoading ? "loading" : showLoaded ? "loaded" : failed ? "failed" : "unloaded"}
            className={`inline-flex items-center gap-2 rounded-lg border-2 px-5 py-2.5 text-sm font-semibold shadow-sm transition disabled:cursor-not-allowed disabled:opacity-60 ${buttonClass}`}
          >
            {isLoading && <Loader2 size={16} className="motion-safe:animate-spin" aria-hidden="true" />}
            {showLoaded && <Check size={16} aria-hidden="true" />}
            {buttonLabel}
          </button>
          {showLoaded && (
            <span className="text-xs font-semibold text-emerald-800" data-testid="dataset-loaded-identity">
              {selectedDataset?.name ?? selectedDatasetId}, version <span className="font-mono">{selectedVersionId}</span>, loaded into this project.
            </span>
          )}
        </div>
        <DatasetLoadProgressPanel progress={loadProgress} />
      </div>

      {!libraryDatasets.length && (
        <div className="mt-4 rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">
          No reusable datasets are registered yet. Open Dataset Library to upload or register governed datasets.
        </div>
      )}

      {/* UX-DATAACQ-002: browser-session import records are lineage diagnostics, not
          analyst workflow input. They stay available (and keep flowing into project
          snapshots) but are collapsed, and never render an empty placeholder table. */}
      {versions.length > 0 && (
        <details className="mt-5 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2" data-testid="advanced-session-details">
          <summary className="cursor-pointer text-xs font-semibold text-slate-700">
            Advanced session details ({versions.length} browser import record{versions.length === 1 ? "" : "s"})
          </summary>
          <div className="mt-2 overflow-auto rounded-lg border border-slate-200 bg-white">
            <table className="min-w-full text-sm">
              <thead className="bg-slate-50 text-xs uppercase text-slate-500">
                <tr><th className="px-3 py-2 text-left">Access snapshot</th><th className="px-3 py-2 text-left">Source</th><th className="px-3 py-2 text-right">Rows</th><th className="px-3 py-2 text-right">Columns</th><th className="px-3 py-2 text-left">Imported</th></tr>
              </thead>
              <tbody>{versions.map((row) => <tr key={row.accessMetadataId} className="border-t"><td className="px-3 py-2 font-mono text-xs">{row.accessMetadataId}</td><td className="px-3 py-2">{row.sourceLabel}</td><td className="px-3 py-2 text-right">{row.rows}</td><td className="px-3 py-2 text-right">{row.columns}</td><td className="px-3 py-2">{new Date(row.importedAt).toLocaleString()}</td></tr>)}</tbody>
            </table>
          </div>
        </details>
      )}
    </div>
  );
}

function PythonPanel({ pythonCode, setPythonCode }: { pythonCode: string; setPythonCode: (value: string) => void }) {
  return (
    <div>
      <h2 className="text-base font-semibold text-slate-950">Python Loader</h2>
      <p className="mt-1 text-sm text-slate-500">Document advanced loading code. Backend execution can later synchronize the resulting dataframe back into the app.</p>
      <textarea className="mt-4 min-h-[260px] w-full rounded-lg border border-slate-300 bg-slate-950 p-4 font-mono text-sm text-emerald-100" value={pythonCode} onChange={(event) => setPythonCode(event.target.value)} spellCheck={false} />
    </div>
  );
}

function DataPreview(props: {
  headers: string[];
  rows: Record<string, unknown>[];
  governedPopulationRowCount: number | null;
  previewRowCount: number;
}) {
  const hasGovernedPopulation =
    Number.isFinite(props.governedPopulationRowCount) &&
    Number(props.governedPopulationRowCount) >= 0;
  return (
    <section className="min-w-0 rounded-xl border border-slate-200 bg-white p-5 shadow-sm" data-testid="data-preview">
      <h2 className="text-base font-semibold text-slate-950">Data Preview</h2>
      <p className="mt-1 text-sm text-slate-600" data-testid="browser-preview-scope-note">
        {hasGovernedPopulation
          ? `Showing ${props.previewRowCount.toLocaleString()} browser preview rows from a governed population of ${Number(props.governedPopulationRowCount).toLocaleString()}. Preview limits do not change backend modeling scope.`
          : `Showing ${props.previewRowCount.toLocaleString()} browser preview rows from the current unregistered workspace. Backend modeling scope is not governed until registration and exact-version activation succeed.`}
      </p>
      <div className="mt-4 max-h-[360px] overflow-auto rounded-lg border border-slate-200">
        <table className="min-w-full text-xs">
          <thead className="sticky top-0 bg-slate-50 text-slate-500">
            <tr>{props.headers.map((header) => <th key={header} className="whitespace-nowrap px-3 py-2 text-left">{header}</th>)}</tr>
          </thead>
          <tbody>{props.rows.map((row, index) => <tr key={index} className="border-t">{props.headers.map((header) => <td key={header} className="whitespace-nowrap px-3 py-2">{String(row[header] ?? "")}</td>)}</tr>)}</tbody>
        </table>
        {!props.headers.length && <div className="p-8 text-center text-sm text-slate-500">Load data or save SQL metadata to begin.</div>}
      </div>
    </section>
  );
}

function DataQualityPanel({ quality }: { quality: DataQualitySummary | null }) {
  if (!quality) return <div className="atlas-empty-state text-sm text-slate-600">Quality profiling has not been generated.</div>;
  const actualOr = (values: string[], empty = "None detected") => values.length ? values.join(", ") : empty;
  return (
    <div className="space-y-4">
      {!!quality.warnings?.length && (
        <div className="atlas-warning-panel">
          <div className="text-sm font-semibold">Priority findings</div>
          <ul className="mt-2 list-disc space-y-1 pl-5 text-xs">{quality.warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul>
        </div>
      )}
      {/* Part D: the five findings groups are visually separated and semantically
          toned -- green when a check is clean, amber when it needs attention. Grey
          is reserved for genuinely neutral information. */}
      <div className="grid gap-4 lg:grid-cols-2">
        <QualityGroup title="Row and column health" tone={quality.duplicateRows || quality.constantColumns.length || quality.nearZeroVarianceColumns.length ? "warning" : "success"}>
          <QualityLine label="Duplicate rows" value={quality.duplicateRows.toLocaleString()} />
          <QualityLine label="Duplicate ID candidates" value={actualOr(quality.duplicateIdCandidates)} />
          <QualityLine label="Constant columns" value={actualOr(quality.constantColumns)} />
          <QualityLine label="Near-zero variance" value={actualOr(quality.nearZeroVarianceColumns)} />
        </QualityGroup>
        <QualityGroup title="Missingness and duplicates" tone={quality.missing.some((row) => row.percent > 0) || quality.unexpectedDatatypeColumns.length ? "warning" : "success"}>
          <QualityLine label="Highest missing fields" value={quality.missing.slice(0, 5).map((row) => `${row.column} ${formatPercent(row.percent)}`).join(", ") || "None detected"} />
          <QualityLine label="High-cardinality categoricals" value={actualOr(quality.highCardinalityCategoricals)} />
          <QualityLine label="Unexpected datatypes" value={actualOr(quality.unexpectedDatatypeColumns)} />
        </QualityGroup>
        <QualityGroup title="Predictor readiness" tone={quality.outlierPrevalence.length ? "warning" : "success"}>
          <QualityLine label="Outlier prevalence" value={quality.outlierPrevalence.length ? quality.outlierPrevalence.slice(0, 5).map((row) => `${row.column} ${formatPercent(row.percent)}`).join(", ") : "None detected"} />
          <QualityLine label="Legitimate date ranges" value={quality.dateRanges.length ? quality.dateRanges.map((row) => `${row.column}: ${row.min} to ${row.max}`).join(", ") : "None detected"} />
        </QualityGroup>
        <QualityGroup title="Leakage screening" tone={quality.potentialLeakageColumns.length ? "warning" : "success"}>
          <QualityLine label="Potential leakage candidates" value={actualOr(quality.potentialLeakageColumns)} />
          <QualityLine label="Special-value handling" value="Reviewed separately in the governed Special-Value Treatment workspace" />
        </QualityGroup>
      </div>
    </div>
  );
}

function QualityGroup({
  title,
  tone,
  children,
}: {
  title: string;
  tone: "success" | "warning";
  children: React.ReactNode;
}) {
  const toneClass = tone === "warning" ? "border-amber-300 bg-amber-50" : "border-emerald-200 bg-emerald-50";
  const headingClass = tone === "warning" ? "text-amber-900" : "text-emerald-900";
  return (
    <div className={`rounded-xl border p-4 ${toneClass}`} data-quality-group={title} data-quality-tone={tone}>
      <div className="flex items-center justify-between gap-2">
        <h3 className={`text-xs font-bold uppercase tracking-wide ${headingClass}`}>{title}</h3>
        {/* Text status, so the group is readable without relying on color. */}
        <span className={`text-[10px] font-semibold uppercase tracking-wide ${headingClass}`}>
          {tone === "warning" ? "Review" : "Clear"}
        </span>
      </div>
      <div className="mt-3 grid gap-2 rounded-lg bg-white p-3 text-sm">{children}</div>
    </div>
  );
}

/**
 * Lifecycle badge for the readiness checkpoint.
 *
 * Part A closure: this used to take `readiness.status` from
 * `computeReadinessStatus` -- a SECOND lifecycle derivation that could report
 * "Blocked" while the hero reported "Ready with warnings". It now renders the
 * one shared `acquisitionStatus`, so the checkpoint cannot disagree with the
 * rest of the page.
 */
function ReadinessBadge({ status }: { status: DataAcquisitionStatus }) {
  const toneClass: Record<string, string> = {
    success: "border-emerald-300 bg-emerald-50 text-emerald-900",
    warning: "border-amber-300 bg-amber-50 text-amber-900",
    danger: "border-red-300 bg-red-50 text-red-900",
    info: "border-blue-200 bg-blue-50 text-blue-900",
    neutral: "border-slate-200 bg-slate-50 text-slate-700",
  };
  return (
    <span
      className={`rounded-full border px-3 py-1 text-xs font-bold ${toneClass[status.readinessTone]}`}
      data-testid="readiness-status-badge"
      data-readiness-status={status.readiness}
      data-review-state={status.reviewState}
    >
      {status.readinessLabel}
    </span>
  );
}

function ProfileScopeBadge({ quality }: { quality: DataQualitySummary | null }) {
  const label = !quality
    ? "Not Generated"
    : quality.profileScope === "full_dataset"
      ? "Full Dataset"
      : quality.profileScope === "complete_browser_dataset"
        ? "Complete Browser Dataset"
        : quality.profileScope === "preview_profile"
          ? `Preview Profile: ${(quality.profiledRowCount ?? quality.rowCount).toLocaleString()} Rows`
          : "Not Generated";
  return <span className="rounded-full border border-blue-200 bg-blue-50 px-3 py-1 text-xs font-semibold text-blue-800">{label}</span>;
}

function LineagePanel({ metadata }: { metadata: DataAccessMetadata | null }) {
  return (
    <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
      <h3 className="text-sm font-semibold text-slate-950">Governed lineage</h3>
      <div className="mt-4 flex flex-wrap items-center gap-2 text-sm">
        {(metadata?.lineage ?? ["Source not captured"]).map((item, index, arr) => (
          <span key={`${item}-${index}`} className="flex items-center gap-2">
            <span className="rounded-full border border-slate-200 bg-slate-50 px-3 py-1">{item}</span>
            {index < arr.length - 1 && <span className="text-slate-400">to</span>}
          </span>
        ))}
      </div>
    </section>
  );
}

function Select({
  label,
  value,
  onChange,
  options,
  optionLabels,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  options: string[];
  optionLabels?: Record<string, string>;
}) {
  return (
    <label className="grid gap-1 text-xs font-semibold uppercase text-slate-500">
      {label}
      <select className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-normal normal-case text-slate-900" value={value} onChange={(event) => onChange(event.target.value)}>
        {options.map((option) => <option key={option} value={option}>{optionLabels?.[option] ?? (option || "Select")}</option>)}
      </select>
    </label>
  );
}

function Input({ label, value, onChange, placeholder }: { label: string; value: string; onChange: (value: string) => void; placeholder?: string }) {
  return (
    <label className="grid gap-1 text-xs font-semibold uppercase text-slate-500">
      {label}
      <input className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm font-normal normal-case text-slate-900" value={value} placeholder={placeholder} onChange={(event) => onChange(event.target.value)} />
    </label>
  );
}

function Stat({ label, value, testId }: { label: string; value: unknown; testId?: string }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white px-3 py-2" data-testid={testId}>
      <div className="text-xs font-semibold uppercase text-slate-500">{label}</div>
      <div className="mt-1 truncate text-sm font-semibold text-slate-950" title={String(value)}>{String(value)}</div>
    </div>
  );
}

function QualityLine({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-slate-200 px-3 py-2">
      <div className="text-xs font-semibold uppercase text-slate-500">{label}</div>
      <div className="mt-1 text-slate-800">{value}</div>
    </div>
  );
}

function QueryList({ title, queries }: { title: string; queries: string[] }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-slate-50 p-3">
      <div className="text-xs font-semibold uppercase text-slate-500">{title}</div>
      <div className="mt-2 space-y-2">{queries.length ? queries.map((query, index) => <div key={index} className="truncate text-xs text-slate-600">{query}</div>) : <div className="text-xs text-slate-400">None</div>}</div>
    </div>
  );
}
